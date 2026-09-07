from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from marketing_os.core import update as update_mod
from marketing_os.core.update import _detect_mode, update_engine


def make_run(branch: str = "main", status: str = "", rc: int = 0) -> Any:
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(list(argv))
        if "rev-parse" in argv:
            return SimpleNamespace(returncode=0, stdout=branch + "\n", stderr="")
        if "status" in argv:
            return SimpleNamespace(returncode=0, stdout=status, stderr="")
        return SimpleNamespace(returncode=rc, stdout="done", stderr="failure" if rc else "")

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_source_plan_reports_command_and_runs_no_pull(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(update_mod, "_detect_mode", lambda _p: ("source", tmp_path))
    run = make_run(branch="main", status="")
    monkeypatch.setattr(update_mod.subprocess, "run", run)
    result = update_engine(apply=False)
    assert result["ok"] is True
    assert result["mode"] == "source"
    assert "pull --ff-only" in result["run_command"]
    # Plan-mode changes are prefixed with "run: ".
    assert result["changes"] == [f"run: {result['run_command']}"]
    assert result["planned"] is True
    assert not any("pull" in call for call in run.calls)
    assert any("rev-parse" in call for call in run.calls)


def test_source_not_on_main_blocks_pull(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod, "_detect_mode", lambda _p: ("source", tmp_path))
    run = make_run(branch="feature", status="")
    monkeypatch.setattr(update_mod.subprocess, "run", run)
    result = update_engine(apply=True)
    assert result["ok"] is False
    assert any(item["code"] == "not-on-main" for item in result["findings"])
    assert not any("pull" in call for call in run.calls)
    # A guard trip means nothing will run: changes must be empty, run_command kept.
    assert result["changes"] == []
    assert "pull --ff-only" in result["run_command"]


def test_source_dirty_worktree_blocks_pull(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod, "_detect_mode", lambda _p: ("source", tmp_path))
    run = make_run(branch="main", status=" M core/update.py\n")
    monkeypatch.setattr(update_mod.subprocess, "run", run)
    result = update_engine(apply=True)
    assert result["ok"] is False
    assert any(item["code"] == "dirty-worktree" for item in result["findings"])
    assert not any("pull" in call for call in run.calls)


def test_source_apply_runs_pull(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod, "_detect_mode", lambda _p: ("source", tmp_path))
    run = make_run(branch="main", status="", rc=0)
    monkeypatch.setattr(update_mod.subprocess, "run", run)
    result = update_engine(apply=True)
    assert result["ok"] is True
    assert result["applied"] is True
    assert result["next_action"]["id"] == "run-doctor"
    assert any("pull" in call for call in run.calls)


def test_source_apply_pull_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod, "_detect_mode", lambda _p: ("source", tmp_path))
    run = make_run(branch="main", status="", rc=1)
    monkeypatch.setattr(update_mod.subprocess, "run", run)
    result = update_engine(apply=True)
    assert result["ok"] is False
    assert any(item["code"] == "update-failed" for item in result["findings"])


def test_pipx_plan_runs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod, "_detect_mode", lambda _p: ("pipx", None))
    run = make_run()
    monkeypatch.setattr(update_mod.subprocess, "run", run)
    result = update_engine(apply=False)
    assert result["ok"] is True
    assert result["mode"] == "pipx"
    assert result["run_command"] == "pipx upgrade marketing-os"
    assert run.calls == []


def test_pipx_apply_runs_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod, "_detect_mode", lambda _p: ("pipx", None))
    run = make_run(rc=0)
    monkeypatch.setattr(update_mod.subprocess, "run", run)
    result = update_engine(apply=True)
    assert result["ok"] is True
    assert result["next_action"]["id"] == "run-doctor"
    assert run.calls and run.calls[0][0] == "pipx"


def test_unknown_install_is_noop_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod, "_detect_mode", lambda _p: ("unknown", None))
    run = make_run()
    monkeypatch.setattr(update_mod.subprocess, "run", run)
    result = update_engine(apply=True)
    assert result["ok"] is True
    assert result["mode"] == "unknown"
    assert any(item["code"] == "unknown-install" for item in result["findings"])
    assert result["next_action"]["id"] == "manual-update"
    assert run.calls == []


def test_detect_mode_source_checkout(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('name = "marketing-os"\n', encoding="utf-8")
    (tmp_path / ".git").mkdir()
    module = tmp_path / "src" / "marketing_os" / "core" / "update.py"
    module.parent.mkdir(parents=True)
    module.write_text("", encoding="utf-8")
    mode, root = _detect_mode(module.resolve())
    assert mode == "source"
    assert root == tmp_path.resolve()


def test_detect_mode_pipx(tmp_path: Path) -> None:
    module = tmp_path / "pipx" / "venvs" / "marketing-os" / "module.py"
    module.parent.mkdir(parents=True)
    module.write_text("", encoding="utf-8")
    mode, root = _detect_mode(module)
    assert mode == "pipx"
    assert root is None


def test_detect_mode_unknown(tmp_path: Path) -> None:
    module = tmp_path / "packages" / "marketing_os" / "module.py"
    module.parent.mkdir(parents=True)
    module.write_text("", encoding="utf-8")
    mode, root = _detect_mode(module)
    assert mode == "unknown"
    assert root is None


def test_uv_tool_plan_runs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod, "_detect_mode", lambda _p: ("uv", None))
    run = make_run()
    monkeypatch.setattr(update_mod.subprocess, "run", run)
    result = update_engine(apply=False)
    assert result["ok"] is True
    assert result["mode"] == "uv"
    assert result["run_command"] == "uv tool upgrade marketing-os"
    assert result["changes"] == ["run: uv tool upgrade marketing-os"]
    assert result["next_action"]["id"] == "apply-update"
    assert run.calls == []


def test_uv_tool_apply_runs_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_mod, "_detect_mode", lambda _p: ("uv", None))
    run = make_run(rc=0)
    monkeypatch.setattr(update_mod.subprocess, "run", run)
    result = update_engine(apply=True)
    assert result["ok"] is True
    assert result["mode"] == "uv"
    assert result["next_action"]["id"] == "run-doctor"
    assert run.calls == [["uv", "tool", "upgrade", "marketing-os"]]


def test_detect_mode_uv_tool(tmp_path: Path) -> None:
    """The prefix ``uv tool install`` uses: ``<data dir>/uv/tools/<package>/<venv>``."""
    prefix = tmp_path / ".local" / "share" / "uv" / "tools" / "marketing-os"
    site = prefix / "lib" / "python3.12" / "site-packages"
    module = site / "marketing_os" / "__init__.py"
    module.parent.mkdir(parents=True)
    module.write_text("", encoding="utf-8")
    dist_info = site / "marketing_os-0.3.0.dist-info"
    dist_info.mkdir()
    (dist_info / "INSTALLER").write_text("uv\n", encoding="utf-8")
    mode, root = _detect_mode(module.resolve())
    assert mode == "uv"
    assert root is None
