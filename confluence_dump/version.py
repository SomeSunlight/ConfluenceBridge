"""Offline version identity of the *executing* ConfluenceBridge tool.

Confluence content version numbers and workspace manifests are unrelated.
No import in this module contacts Confluence, reads credentials, or starts an export.
"""
from __future__ import annotations

import json
import re
import subprocess
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from . import __version__

_DISTRIBUTION_NAME = "confluence_dump"
_DISPLAY_NAME = "confluencebridge"
_FULL_COMMIT = re.compile(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}")


def release_version() -> str:
    """One canonical release version, shared with setup.py and installed wheels."""
    return __version__


def _project_root() -> Path | None:
    """Only the tool's own checkout qualifies, never the user's current CWD."""
    root = Path(__file__).resolve().parent.parent
    if (root / ".git").exists() and (root / "setup.py").is_file():
        return root
    return None


def _git(root: Path, *args: str) -> str | None:
    try:
        process = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if process.returncode != 0:
        return None
    return process.stdout.strip()


def git_origin(project_root: Path | None = None) -> tuple[str, str, str | None] | None:
    """Checkout remote URL, full commit and optional symbolic branch."""
    root = project_root or _project_root()
    if root is None or not (root / ".git").exists():
        return None
    commit = _git(root, "rev-parse", "HEAD")
    if not commit or not _FULL_COMMIT.fullmatch(commit):
        return None
    url = _git(root, "remote", "get-url", "origin")
    if not url:
        return None
    branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    return url, commit.lower(), branch


def git_provenance(project_root: Path | None = None) -> str | None:
    """Display a locally checked-out commit, branch and dirty status."""
    root = project_root or _project_root()
    if root is None or not (root / ".git").exists():
        return None
    commit = _git(root, "rev-parse", "HEAD")
    if not commit or not _FULL_COMMIT.fullmatch(commit):
        return None
    branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD") or "detached"
    status = _git(root, "status", "--porcelain", "--untracked-files=normal")
    dirty = ", dirty" if status else ""
    return f"{branch}@{commit[:7].lower()}{dirty}"


def installed_git_origin() -> tuple[str, str, str | None] | None:
    """PEP 610 VCS URL, resolved immutable commit and optional requested ref."""
    try:
        raw = distribution(_DISTRIBUTION_NAME).read_text("direct_url.json")
    except (PackageNotFoundError, OSError):
        return None
    if not raw:
        return None
    try:
        record = json.loads(raw)
        info = record["vcs_info"]
        if info["vcs"] != "git":
            return None
        url = record["url"]
        commit = info["commit_id"]
        revision = info.get("requested_revision")
        if not isinstance(url, str) or not url:
            return None
        if not isinstance(commit, str) or not _FULL_COMMIT.fullmatch(commit):
            return None
        if revision is not None and (
            not isinstance(revision, str) or any(c in revision for c in "\r\n\t")
        ):
            return None
        return url, commit.lower(), revision or None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def installed_git_provenance() -> str | None:
    origin = installed_git_origin()
    if origin is None:
        return None
    _, commit, requested = origin
    label = (requested or "git").removeprefix("refs/heads/").removeprefix("refs/tags/")
    if not label or re.fullmatch(r"[a-fA-F0-9]{7,64}", label):
        label = "detached"
    return f"{label}@{commit[:7]}"


def display_version(project_root: Path | None = None) -> str:
    """Fully offline: release label and exact executing checkout/installed SHA."""
    provenance = git_provenance(project_root)
    if provenance is None and project_root is None:
        provenance = installed_git_provenance()
    release = release_version()
    return f"{release} ({provenance})" if provenance else release
