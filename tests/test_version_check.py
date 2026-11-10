"""ConfluenceBridge executable provenance and opt-in remote-version contract.

All HTTP is mocked, and the CLI tests deliberately require no Confluence APIs,
export files, tokens, Playwright, WeasyPrint or credentials.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from confluence_dump import __version__
from confluence_dump.__main__ import main
from confluence_dump.version import (
    _project_root,
    display_version,
    git_origin,
    git_provenance,
    installed_git_origin,
    installed_git_provenance,
    release_version,
)
from confluence_dump.version_check import (
    InstallIdentity,
    VersionCheck,
    _github_coordinates,
    _identity,
    _read_json,
    check_remote_version,
)


LOCAL_SHA = "a" * 40
REMOTE_SHA = "b" * 40
SELF_URL = "https://github.com/SomeSunlight/ConfluenceBridge.git"


def _distribution(raw):
    dist = Mock()
    dist.read_text.return_value = raw
    return dist


def test_one_canonical_release_label_and_separate_page_manifest_version():
    assert __version__ == release_version() == "3.0.1"
    # Do not accidentally surface the unrelated Confluence manifest "1.0".
    from confluence_dump.api.manifest import Manifest
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
        assert Manifest(Path(directory)).data["version"] == "1.0"


def test_pep610_installed_resolved_sha_and_branch():
    metadata = json.dumps({
        "url": SELF_URL,
        "vcs_info": {"vcs": "git", "commit_id": LOCAL_SHA, "requested_revision": "main"},
    })
    with patch("confluence_dump.version.distribution", return_value=_distribution(metadata)):
        assert installed_git_origin() == (SELF_URL, LOCAL_SHA, "main")
        assert installed_git_provenance() == "main@aaaaaaa"
        with patch("confluence_dump.version._project_root", return_value=None):
            assert display_version() == "3.0.1 (main@aaaaaaa)"


def test_installed_pinned_sha_and_no_requested_branch():
    for requested, expected in [(LOCAL_SHA, "detached@aaaaaaa"),
                                (None, "git@aaaaaaa")]:
        info = {"vcs": "git", "commit_id": LOCAL_SHA}
        if requested:
            info["requested_revision"] = requested
        metadata = json.dumps({"url": SELF_URL, "vcs_info": info})
        with patch("confluence_dump.version.distribution", return_value=_distribution(metadata)):
            assert installed_git_provenance() == expected


@pytest.mark.parametrize("metadata", [
    None,
    "{bad",
    "[]",
    '{"url":"https://example.com/wheel.whl","archive_info":{}}',
    json.dumps({"url": SELF_URL, "vcs_info": {"vcs": "hg", "commit_id": LOCAL_SHA}}),
    json.dumps({"url": SELF_URL, "vcs_info": {"vcs": "git", "commit_id": "bad"}}),
    json.dumps({"url": SELF_URL, "vcs_info": {"vcs": "git", "commit_id": LOCAL_SHA,
                                             "requested_revision": "bad\ninject"}}),
])
def test_missing_or_malformed_install_metadata_is_never_invented(metadata):
    with patch("confluence_dump.version.distribution", return_value=_distribution(metadata)):
        assert installed_git_origin() is None


def test_cli_version_does_not_touch_network_confluence_or_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    original = tmp_path / "manifest.json"
    original.write_text('{"version":"1.0","pages":{}}', encoding="utf-8")
    monkeypatch.setenv("CONFLUENCE_TOKEN", "TEST-SECRET-MUST-NOT-BE-READ")
    with patch("confluence_dump.version_check._read_json", side_effect=AssertionError("unexpected API")):
        with patch("confluence_dump.version_check.urlopen", side_effect=AssertionError("network")):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                with pytest.raises(SystemExit) as ended:
                    main(["--version"])
            assert ended.value.code == 0
            assert output.getvalue().startswith("confluencebridge 3.0.1")
            assert "TEST-SECRET" not in output.getvalue()
    assert original.read_text(encoding="utf-8") == '{"version":"1.0","pages":{}}'
    assert sorted(p.name for p in tmp_path.iterdir()) == ["manifest.json"]


def test_git_checkout_reports_branch_sha_dirty_and_tool_origin(tmp_path):
    root = tmp_path / "code"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    (root / "test.txt").write_text("tracked", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "test.txt"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "baseline"], check=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin", SELF_URL], check=True)
    before = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True)
    origin = git_origin(root)
    assert origin is not None and origin[0] == SELF_URL and len(origin[1]) == 40
    assert origin[2] == "main"
    assert git_provenance(root) == "main@" + origin[1][:7]
    with patch("confluence_dump.version_check._read_json", return_value={"commit": {"sha": origin[1]}}):
        checked = check_remote_version(project_root=root)
    assert checked.status == "up to date"
    after = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True)
    assert before == after
    (root / "untracked.txt").write_text("dirty", encoding="utf-8")
    assert git_provenance(root) == f"main@{origin[1][:7]}, dirty"


def test_check_uses_installed_metadata_not_invoking_cwd():
    with patch("confluence_dump.version_check._project_root", return_value=None):
        with patch("confluence_dump.version_check.installed_git_origin",
                   return_value=(SELF_URL, LOCAL_SHA, "main")):
            assert _identity() == InstallIdentity(SELF_URL, LOCAL_SHA, "main")


def test_explicit_unavailable_checkout_never_falls_back_to_another_tool():
    with patch("confluence_dump.version_check.installed_git_origin",
               side_effect=AssertionError("metadata consulted")):
        assert _identity(Path("/nonexistent/ConfluenceBridge")) is None


@pytest.mark.parametrize("relation,status,code", [
    ("ahead", "behind", 1), ("behind", "ahead", 1),
    ("diverged", "diverged", 1), ("identical", "up to date", 0),
])
def test_github_compare_has_contextcanon_direction_and_exit_code(relation,status,code):
    identity = InstallIdentity(SELF_URL, LOCAL_SHA, "main")
    with patch("confluence_dump.version_check._identity", return_value=identity):
        with patch("confluence_dump.version_check._read_json", side_effect=[
            {"commit": {"sha": REMOTE_SHA}}, {"status": relation}
        ]) as read:
            result = check_remote_version()
    assert (result.status, result.exit_code) == (status,code)
    assert "/compare/" + LOCAL_SHA + "..." + REMOTE_SHA in read.call_args_list[-1].args[0]


def test_equal_remote_sha_skips_second_http_request():
    with patch("confluence_dump.version_check._identity",
               return_value=InstallIdentity(SELF_URL, LOCAL_SHA, "main")):
        with patch("confluence_dump.version_check._read_json",
                   return_value={"commit": {"sha": LOCAL_SHA}}) as read:
            result = check_remote_version()
    assert result.status == "up to date" and result.exit_code == 0
    read.assert_called_once()


def test_resolve_default_branch_or_override():
    identity = InstallIdentity(SELF_URL, LOCAL_SHA, None)
    with patch("confluence_dump.version_check._identity", return_value=identity):
        with patch("confluence_dump.version_check._read_json",
                   side_effect=[{"default_branch": "main"},
                                {"commit": {"sha": REMOTE_SHA}},
                                {"status": "ahead"}]) as read:
            result = check_remote_version()
            assert result.status == "behind"
            assert read.call_args_list[0].args[0].endswith("/SomeSunlight/ConfluenceBridge")
        with patch("confluence_dump.version_check._read_json",
                   side_effect=[{"commit": {"sha": REMOTE_SHA}},
                                {"status": "diverged"}]) as read:
            result = check_remote_version(branch="feature/a")
            assert result.status == "diverged"
            assert "/branches/feature%2Fa" in read.call_args_list[0].args[0]


@pytest.mark.parametrize("identity,branch", [
    (None, None),
    (InstallIdentity("https://evil.invalid/ConfluenceBridge", LOCAL_SHA, "main"), None),
    (InstallIdentity("https://github.com/other/ConfluenceBridge", LOCAL_SHA, "main"), None),
    (InstallIdentity(SELF_URL, LOCAL_SHA, "main"), "main\nInjection: bad"),
])
def test_reject_untrusted_origins_and_bad_branch_without_network(identity,branch):
    with patch("confluence_dump.version_check._identity", return_value=identity):
        with patch("confluence_dump.version_check._read_json",
                   side_effect=AssertionError("network")):
            outcome = check_remote_version(branch=branch)
    assert outcome.status == "unknown" and outcome.exit_code == 2


@pytest.mark.parametrize("exception", [OSError("offline"), ValueError("invalid"), KeyError("sha")])
def test_api_failures_are_unknown_not_falsely_up_to_date(exception):
    with patch("confluence_dump.version_check._identity",
               return_value=InstallIdentity(SELF_URL, LOCAL_SHA, "main")):
        with patch("confluence_dump.version_check._read_json", side_effect=exception):
            result = check_remote_version()
    assert result.status == "unknown" and result.exit_code == 2


def test_github_url_validation_rejects_credentials_and_wrong_hosts():
    assert _github_coordinates("git@github.com:SomeSunlight/ConfluenceBridge.git") == (
        "SomeSunlight", "ConfluenceBridge"
    )
    assert _github_coordinates("ssh://git@github.com/SomeSunlight/ConfluenceBridge") == (
        "SomeSunlight", "ConfluenceBridge"
    )
    for url in ["https://github.com.evil.example/SomeSunlight/ConfluenceBridge",
                "https://github.com:invalid/SomeSunlight/ConfluenceBridge",
                "https://secret:token@github.com/SomeSunlight/ConfluenceBridge",
                "https://other.example/SomeSunlight/ConfluenceBridge"]:
        assert _github_coordinates(url) is None


def test_api_has_bounded_requests_and_payloads():
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b'{"default_branch":"main"}'
    with patch("confluence_dump.version_check.urlopen", return_value=response) as urlopen:
        assert _read_json("https://api.github.com/repos/SomeSunlight/ConfluenceBridge") == {
            "default_branch": "main"
        }
        assert urlopen.call_args.kwargs["timeout"] == 5
        response.read.assert_called_with(2_000_001)
    response.read.return_value = b"x" * 2_000_001
    with patch("confluence_dump.version_check.urlopen", return_value=response):
        with pytest.raises(ValueError):
            _read_json("https://api.github.com/repos/SomeSunlight/ConfluenceBridge")


def test_version_check_cli_stdout_and_explicit_status():
    result = VersionCheck("confluencebridge 3.0.1 (main@aaaaaaa)", "main@bbbbbbb", "behind")
    out = io.StringIO()
    with patch("confluence_dump.version_check.check_remote_version",
               return_value=result) as check:
        with contextlib.redirect_stdout(out):
            assert main(["version", "check", "--branch", "main"]) == 1
        check.assert_called_once_with(branch="main")
    assert out.getvalue().splitlines() == [
        "Installed: confluencebridge 3.0.1 (main@aaaaaaa)",
        "Remote:    main@bbbbbbb",
        "Status:    behind",
    ]
    with patch("confluence_dump.version_check.check_remote_version",
               return_value=VersionCheck("confluencebridge 3.0.1", "unavailable", "unknown")):
        assert main(["version", "check"]) == 2


def test_version_module_is_lightweight_without_export_dependencies():
    # In a clean source checkout no third-party packages are needed for version.
    # Check in a subprocess to catch accidental heavy imports/transitive effects.
    code = (
        "import sys; import confluence_dump.__main__;"
        "assert 'confluenceDumpToHTML' not in sys.modules;"
        "assert 'confluence_dump.api.client' not in sys.modules;"
        "assert 'playwright' not in sys.modules;"
        "assert 'weasyprint' not in sys.modules;"
        "print('minimal')"
    )
    result = subprocess.run([sys.executable, "-c", code],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "minimal"
