"""Explicit, read-only public GitHub check of ConfluenceBridge's own source.

Only an explicit "version check" command reaches this module's network path.
Never access Confluence, local exports, credentials, or arbitrary Git remotes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .version import _FULL_COMMIT, _git, _project_root, display_version, git_origin, installed_git_origin

_PUBLIC_REPO = ("somesunlight", "confluencebridge")
_API = "https://api.github.com/repos/SomeSunlight/ConfluenceBridge"


@dataclass(frozen=True)
class InstallIdentity:
    url: str
    commit: str
    branch: str | None


@dataclass(frozen=True)
class VersionCheck:
    installed: str
    remote: str
    status: str
    detail: str = ""

    @property
    def exit_code(self) -> int:
        if self.status == "up to date":
            return 0
        return 2 if self.status == "unknown" else 1

    def render(self) -> str:
        detail = f" ({self.detail})" if self.detail else ""
        return f"Installed: {self.installed}\nRemote:    {self.remote}\nStatus:    {self.status}{detail}\n"


def _identity(project_root: Path | None = None) -> InstallIdentity | None:
    root = project_root or _project_root()
    if root is not None and (root / ".git").exists():
        source = git_origin(root)
        return InstallIdentity(*source) if source is not None else None

    if project_root is not None:
        return None
    source = installed_git_origin()
    if source is None:
        return None
    url, commit, revision = source
    # Do not guess a branch from a pin to an immutable SHA or a tag.
    if revision and revision.startswith("refs/tags/"):
        revision = None
    elif revision:
        revision = revision.removeprefix("refs/heads/")
        if re.fullmatch(r"[a-fA-F0-9]{7,64}", revision):
            revision = None
    return InstallIdentity(url, commit, revision)


def _github_coordinates(source: str) -> tuple[str, str] | None:
    """Accept credential-free GitHub.com URLs only."""
    if source.startswith("git@github.com:"):
        path = source.removeprefix("git@github.com:")
    else:
        try:
            parsed = urlsplit(source)
            if parsed.hostname != "github.com" or parsed.username not in (None, "git") or parsed.password:
                return None
            if parsed.scheme not in ("https", "ssh") or parsed.query or parsed.fragment:
                return None
            if parsed.port not in (None, 22, 443):
                return None
            path = parsed.path.lstrip("/")
        except ValueError:
            return None
    parts = path.strip("/").removesuffix(".git").split("/")
    if len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts):
        return None
    return parts[0], parts[1]


def _read_json(url: str) -> dict:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ConfluenceBridge-version-check",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request, timeout=5) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError("GitHub response too large")
    document = json.loads(data)
    if not isinstance(document, dict):
        raise ValueError("Invalid GitHub response")
    return document


def check_remote_version(*, branch: str | None = None,
                         project_root: Path | None = None) -> VersionCheck:
    """Compare the tool's installed Git commit, never a workspace page version."""
    installed = f"confluencebridge {display_version(project_root)}"
    origin = _identity(project_root)
    if origin is None:
        return VersionCheck(installed, "unavailable", "unknown", "no installed Git provenance")

    coordinates = _github_coordinates(origin.url)
    if coordinates is None or tuple(x.lower() for x in coordinates) != _PUBLIC_REPO:
        return VersionCheck(installed, "unavailable", "unknown", "origin is not the public ConfluenceBridge repository")

    if branch is not None and (
        not branch or len(branch) > 200 or any(c in branch for c in "\r\n\t")
    ):
        return VersionCheck(installed, "unavailable", "unknown", "invalid branch")
    target_branch = branch or origin.branch
    target = "unavailable"
    try:
        if not target_branch:
            repo = _read_json(_API)
            target_branch = repo.get("default_branch")
            if not isinstance(target_branch, str) or not target_branch:
                raise ValueError("Missing default branch")
        target = f"{target_branch}@unknown"
        branch_info = _read_json(f"{_API}/branches/{quote(target_branch, safe='')}")
        remote_commit = branch_info["commit"]["sha"]
        if not isinstance(remote_commit, str) or not _FULL_COMMIT.fullmatch(remote_commit):
            raise ValueError("Invalid GitHub commit")
        remote_commit = remote_commit.lower()
        target = f"{target_branch}@{remote_commit[:7]}"
        if remote_commit == origin.commit:
            return VersionCheck(installed, target, "up to date")

        comparison = _read_json(f"{_API}/compare/{origin.commit}...{remote_commit}?per_page=1")
        # GitHub's compare status is relative to its remote HEAD.
        statuses = {
            "identical": "up to date",
            "ahead": "behind",
            "behind": "ahead",
            "diverged": "diverged",
        }
        relation = comparison.get("status")
        if relation not in statuses:
            raise ValueError("Unknown Git ancestry")
        return VersionCheck(installed, target, statuses[relation])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return VersionCheck(installed, target, "unknown", f"remote comparison unavailable ({type(exc).__name__})")
