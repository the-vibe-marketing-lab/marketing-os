import shutil
import subprocess
from pathlib import Path

import pytest

from marketing_os.core import atomic as atomic_module
from marketing_os.core import onboard as onboard_mod
from marketing_os.core.onboard import onboard_repo
from marketing_os.core.setup import setup_repo

HAS_GIT = shutil.which("git") is not None


def test_onboard_plan_is_non_mutating(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("no subprocess should run in plan mode")

    monkeypatch.setattr(onboard_mod.subprocess, "run", boom)
    monkeypatch.setattr(onboard_mod.shutil, "which", lambda _name: "git")
    target = tmp_path / "brain"
    result = onboard_repo(target, "Example Business", "all", mode="in-house", apply=False)
    assert result["ok"] is True
    assert result["planned"] is True
    assert not target.exists()
    assert any(change.startswith("create ") for change in result["changes"])
    assert "git init" in result["changes"]
    assert result["next_action"]["id"] == "run-interview"
    assert result["interview"]["unfilled"]


@pytest.mark.skipif(not HAS_GIT, reason="git is required for this integration path")
def test_onboard_apply_scaffolds_and_commits(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    result = onboard_repo(target, "Example Business", "all", mode="in-house", apply=True)
    assert result["ok"] is True
    assert result["applied"] is True
    assert (target / "BRAIN.md").exists()
    assert (target / ".git").is_dir()
    assert "git init" in result["changes"]
    log = subprocess.run(
        ["git", "-C", str(target), "log", "-1", "--pretty=%s"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert log.stdout.strip() == "mos: onboard Example Business"
    assert result["next_action"]["id"] == "run-interview"


def test_onboard_over_existing_setup_reuses_scaffold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "brain"
    setup_repo(target, "Example Business", "all", mode="in-house", apply=True)
    (target / ".git").mkdir()

    def boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("git must not run when .git already exists")

    monkeypatch.setattr(onboard_mod.subprocess, "run", boom)
    result = onboard_repo(target, "Example Business", "all", mode="in-house", apply=True)
    assert result["ok"] is True
    assert result["changes"] == []
    assert result["next_action"]["id"] == "run-interview"


def test_unfilled_detection_tracks_edited_files(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    setup_repo(target, "Example Business", "all", mode="in-house", apply=True)
    voice = target / "business" / "brand" / "voice.md"
    voice.write_text("# Voice\n\nReal and specific voice content.\n", encoding="utf-8")
    result = onboard_repo(target, "Example Business", "all", mode="in-house", apply=False)
    unfilled = result["interview"]["unfilled"]
    assert "business/brand/voice.md" not in unfilled
    assert "business/audience/primary.md" in unfilled
    assert result["interview"]["guidance"]


def test_onboard_reports_git_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onboard_mod.shutil, "which", lambda _name: None)
    target = tmp_path / "brain"
    result = onboard_repo(target, "Example Business", "all", mode="in-house", apply=True)
    assert result["ok"] is True
    codes = [item["code"] for item in result["findings"]]
    assert "git-unavailable" in codes
    assert not (target / ".git").exists()
    assert (target / "BRAIN.md").exists()


def test_onboard_propagates_scaffold_failure(tmp_path: Path) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    (target / "notes.md").write_text("existing", encoding="utf-8")
    result = onboard_repo(target, "Example Business", "all", mode="in-house", apply=True)
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "unsupported-directory"
    assert not (target / "BRAIN.md").exists()


def test_onboard_without_mode_hands_off_choose_mode(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    result = onboard_repo(target, "Example Business", "all", apply=True)
    assert result["ok"] is False
    assert result["next_action"]["id"] == "choose-mode"
    assert not target.exists()


def _agency_hq(tmp_path: Path) -> Path:
    hq = tmp_path / "agency-hq"
    setup_repo(hq, "Example Agency", "all", mode="agency", apply=True)
    return hq


def test_onboard_client_appends_registry_row_after_example(tmp_path: Path) -> None:
    hq = _agency_hq(tmp_path)
    client = tmp_path / "acme-widgets"
    result = onboard_repo(
        client,
        "Widgets Inc",
        "all",
        mode="client",
        agency="Example Agency",
        hq=hq,
        apply=True,
    )
    assert result["ok"] is True
    registry = (hq / "business" / "clients" / "clients.md").read_text(encoding="utf-8")
    lines = registry.splitlines()
    example_index = next(i for i, line in enumerate(lines) if "_example-client_" in line)
    assert "Widgets Inc" in lines[example_index + 1]
    # The row records a relative, forward-slash path from the HQ root, not an absolute one.
    assert "`../acme-widgets`" in lines[example_index + 1]
    assert "\\" not in lines[example_index + 1]
    assert lines[example_index + 1].endswith("active | you |")


def test_onboard_client_cross_drive_falls_back_to_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hq = _agency_hq(tmp_path)
    client = tmp_path / "acme-widgets"

    def _raise(*_args: object, **_kwargs: object) -> str:
        raise ValueError("path is on mount 'C:', start on mount 'D:'")

    monkeypatch.setattr(onboard_mod.os.path, "relpath", _raise)
    result = onboard_repo(
        client, "Widgets Inc", "all", mode="client", agency="Example Agency", hq=hq, apply=True
    )
    assert result["ok"] is True
    registry = (hq / "business" / "clients" / "clients.md").read_text(encoding="utf-8")
    example_index = next(
        i for i, line in enumerate(registry.splitlines()) if "_example-client_" in line
    )
    assert f"`{client.resolve().as_posix()}`" in registry.splitlines()[example_index + 1]


def test_onboard_client_preserves_crlf_registry(tmp_path: Path) -> None:
    hq = _agency_hq(tmp_path)
    registry = hq / "business" / "clients" / "clients.md"
    # Force the registry onto CRLF line endings.
    crlf = registry.read_text(encoding="utf-8").replace("\n", "\r\n")
    registry.write_bytes(crlf.encode("utf-8"))
    client = tmp_path / "acme-widgets"
    onboard_repo(
        client, "Widgets Inc", "all", mode="client", agency="Example Agency", hq=hq, apply=True
    )
    raw = registry.read_bytes()
    assert b"Widgets Inc" in raw
    # Every newline stays CRLF; no bare LF was introduced.
    assert raw.count(b"\r\n") == raw.count(b"\n")
    assert b"\r\n" in raw


def test_onboard_client_duplicate_is_case_insensitive(tmp_path: Path) -> None:
    hq = _agency_hq(tmp_path)
    onboard_repo(
        tmp_path / "acme-widgets",
        "Widgets Inc",
        "all",
        mode="client",
        agency="Example Agency",
        hq=hq,
        apply=True,
    )
    before = (hq / "business" / "clients" / "clients.md").read_text(encoding="utf-8")
    result = onboard_repo(
        tmp_path / "acme-widgets-2",
        "widgets inc",
        "all",
        mode="client",
        agency="Example Agency",
        hq=hq,
        apply=True,
    )
    codes = [item["code"] for item in result["findings"]]
    assert "client-already-registered" in codes
    after = (hq / "business" / "clients" / "clients.md").read_text(encoding="utf-8")
    assert after == before


def test_onboard_client_malformed_registry_warns_and_skips(tmp_path: Path) -> None:
    hq = _agency_hq(tmp_path)
    registry = hq / "business" / "clients" / "clients.md"
    registry.write_text("# Client Registry\n\nNo table here yet.\n", encoding="utf-8")
    before = registry.read_text(encoding="utf-8")
    client = tmp_path / "acme-widgets"
    result = onboard_repo(
        client, "Widgets Inc", "all", mode="client", agency="Example Agency", hq=hq, apply=True
    )
    codes = [item["code"] for item in result["findings"]]
    assert "registry-malformed" in codes
    assert registry.read_text(encoding="utf-8") == before


def test_onboard_client_plan_does_not_touch_registry(tmp_path: Path) -> None:
    hq = _agency_hq(tmp_path)
    before = (hq / "business" / "clients" / "clients.md").read_text(encoding="utf-8")
    client = tmp_path / "acme-widgets"
    result = onboard_repo(
        client,
        "Widgets Inc",
        "all",
        mode="client",
        agency="Example Agency",
        hq=hq,
        apply=False,
    )
    assert result["planned"] is True
    after = (hq / "business" / "clients" / "clients.md").read_text(encoding="utf-8")
    assert after == before


def test_onboard_client_duplicate_row_warns_and_skips(tmp_path: Path) -> None:
    hq = _agency_hq(tmp_path)
    client = tmp_path / "acme-widgets"
    onboard_repo(
        client, "Widgets Inc", "all", mode="client", agency="Example Agency", hq=hq, apply=True
    )
    before = (hq / "business" / "clients" / "clients.md").read_text(encoding="utf-8")
    second = tmp_path / "acme-widgets-2"
    result = onboard_repo(
        second, "Widgets Inc", "all", mode="client", agency="Example Agency", hq=hq, apply=True
    )
    codes = [item["code"] for item in result["findings"]]
    assert "client-already-registered" in codes
    after = (hq / "business" / "clients" / "clients.md").read_text(encoding="utf-8")
    assert after == before


def test_onboard_client_missing_registry_warns(tmp_path: Path) -> None:
    plain = tmp_path / "not-agency"
    setup_repo(plain, "Plain Brand", "all", mode="in-house", apply=True)
    client = tmp_path / "acme-widgets"
    result = onboard_repo(
        client, "Widgets Inc", "all", mode="client", agency="Example Agency", hq=plain, apply=True
    )
    codes = [item["code"] for item in result["findings"]]
    assert "no-client-registry" in codes
    assert result["ok"] is True


def test_onboard_hq_ignored_for_non_client_mode(tmp_path: Path) -> None:
    hq = _agency_hq(tmp_path)
    target = tmp_path / "brain"
    result = onboard_repo(target, "Example Business", "all", mode="in-house", hq=hq, apply=True)
    codes = [item["code"] for item in result["findings"]]
    assert "hq-ignored" in codes
    assert result["ok"] is True


def test_a_failed_registry_write_leaves_the_registry_exactly_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One row is inserted, but the whole registry is rewritten to insert it.

    A truncating write that failed mid-insert cost every client already listed. The last
    step is now a rename over the target, so the registry is either the old one or the new
    one.
    """
    hq = _agency_hq(tmp_path)
    registry = hq / "business" / "clients" / "clients.md"
    before = registry.read_bytes()
    assert before

    def explode(source: object, destination: object) -> None:
        raise OSError("the disk went away mid-write")

    monkeypatch.setattr(atomic_module.os, "replace", explode)
    with pytest.raises(OSError):
        onboard_repo(
            tmp_path / "acme-widgets",
            "Widgets Inc",
            "all",
            mode="client",
            agency="Example Agency",
            hq=hq,
            apply=True,
        )

    assert registry.read_bytes() == before
    assert list(registry.parent.glob(".clients.md.*")) == []  # and no scratch file left behind


def test_onboard_scaffolds_the_obsidian_vault(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    result = setup_repo(target, "Vault Business", "all", mode="agency", apply=True)
    assert result["ok"] is True
    assert (target / ".obsidian" / "app.json").is_file()
    plugins = target / ".obsidian" / "plugins"
    for plugin_id in (
        "obsidian-icon-folder",
        "git-file-explorer-colors",
        "hide-empty-folders",
    ):
        assert (plugins / plugin_id / "main.js").is_file(), plugin_id
        assert (plugins / plugin_id / "manifest.json").is_file(), plugin_id
    # The agency overlay adds files; it must not clobber the shipped vault config.
    icons = (plugins / "obsidian-icon-folder" / "data.json").read_text(encoding="utf-8")
    assert '"business/clients"' in icons
    assert (target / "business" / "clients" / "clients.md").is_file()
