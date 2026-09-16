import io
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from marketing_os.cli.main import main
from marketing_os.core import statusline_install as wiring
from marketing_os.core.setup import setup_repo


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    # Never the real ~/.claude or ~/.marketing-os.
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    monkeypatch.setattr(wiring.shutil, "which", lambda name: "/opt/mos/bin/mos")
    return path


def _settings(home: Path) -> Path:
    return home / ".claude" / "settings.json"


def _write_settings(home: Path, data: dict) -> None:
    _settings(home).parent.mkdir(parents=True, exist_ok=True)
    _settings(home).write_text(json.dumps(data), encoding="utf-8")


def _read_settings(home: Path) -> dict:
    return json.loads(_settings(home).read_text(encoding="utf-8"))


def _backups(home: Path) -> list[Path]:
    return sorted(_settings(home).parent.glob("settings.json.mos-backup-*"))


def _command_line(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


PREVIOUS = {"type": "command", "command": "bash ~/old-bar.sh", "padding": 2}


def test_install_plan_writes_nothing(home: Path) -> None:
    _write_settings(home, {"model": "opus", "statusLine": PREVIOUS})
    result = wiring.install_statusline(apply=False)
    assert result["ok"] is True
    assert result["applied"] is False
    assert any("set statusLine.command" in change for change in result["changes"])
    assert result["next_action"]["id"] == "apply"
    assert _read_settings(home)["statusLine"] == PREVIOUS
    assert not wiring.record_path().exists()
    assert _backups(home) == []


def test_install_layers_on_top_and_records_previous(home: Path) -> None:
    _write_settings(home, {"model": "opus", "statusLine": PREVIOUS})
    result = wiring.install_statusline(apply=True)
    assert result["applied"] is True
    settings = _read_settings(home)
    assert settings["model"] == "opus"
    assert settings["statusLine"] == {
        "type": "command",
        "command": "/opt/mos/bin/mos statusline --claude --color --divider --chain",
        "padding": 2,
    }
    record = json.loads(wiring.record_path().read_text(encoding="utf-8"))
    assert record == {"schema": "mos.statusline-record.v1", "previous": PREVIOUS}
    assert len(_backups(home)) == 1
    assert json.loads(_backups(home)[0].read_text(encoding="utf-8"))["statusLine"] == PREVIOUS
    assert wiring.chained_command() == "bash ~/old-bar.sh"


def test_install_twice_never_chains_to_itself(home: Path) -> None:
    _write_settings(home, {"statusLine": PREVIOUS})
    wiring.install_statusline(apply=True)
    again = wiring.install_statusline(apply=True)
    assert again["changes"] == []
    assert again["installed"] is True
    record = json.loads(wiring.record_path().read_text(encoding="utf-8"))
    assert record["previous"] == PREVIOUS
    assert len(_backups(home)) == 1


def test_install_without_settings_or_previous_bar(home: Path) -> None:
    result = wiring.install_statusline(apply=True)
    assert result["ok"] is True
    assert _read_settings(home)["statusLine"]["command"].endswith(wiring.BADGE_ARGS)
    assert _backups(home) == []
    assert wiring.chained_command() == ""
    assert wiring.run_chained(b"{}") == b""

    removed = wiring.uninstall_statusline(apply=True)
    assert removed["applied"] is True
    assert "statusLine" not in _read_settings(home)
    assert not wiring.record_path().exists()


def test_uninstall_restores_previous_bar(home: Path) -> None:
    _write_settings(home, {"statusLine": PREVIOUS})
    wiring.install_statusline(apply=True)
    plan = wiring.uninstall_statusline(apply=False)
    assert plan["applied"] is False
    assert plan["installed"] is True
    assert wiring.record_path().exists()

    result = wiring.uninstall_statusline(apply=True)
    assert result["installed"] is False
    assert _read_settings(home)["statusLine"] == PREVIOUS
    assert not wiring.record_path().exists()
    assert len(_backups(home)) == 2


def test_uninstall_when_nothing_installed_is_a_no_op(home: Path) -> None:
    _write_settings(home, {"statusLine": PREVIOUS})
    result = wiring.uninstall_statusline(apply=True)
    assert result["changes"] == []
    assert _read_settings(home)["statusLine"] == PREVIOUS


def test_uninstall_leaves_a_bar_changed_since_install(home: Path) -> None:
    _write_settings(home, {"statusLine": PREVIOUS})
    wiring.install_statusline(apply=True)
    replaced = {"type": "command", "command": "starship statusline"}
    _write_settings(home, {"statusLine": replaced})
    result = wiring.uninstall_statusline(apply=True)
    assert [item["code"] for item in result["findings"]] == ["statusline-changed"]
    assert _read_settings(home)["statusLine"] == replaced
    assert not wiring.record_path().exists()


def test_unreadable_settings_are_never_overwritten(home: Path) -> None:
    _settings(home).parent.mkdir(parents=True)
    _settings(home).write_text("{not json", encoding="utf-8")
    result = wiring.install_statusline(apply=True)
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "settings-unreadable"
    assert _settings(home).read_text(encoding="utf-8") == "{not json"


def test_chain_passes_stdin_through(home: Path, tmp_path: Path) -> None:
    script = tmp_path / "old_bar.py"
    script.write_text(
        "import sys\nsys.stdout.write('OLD BAR ' + sys.stdin.read())\n", encoding="utf-8"
    )
    previous = {"type": "command", "command": _command_line([sys.executable, str(script)])}
    _write_settings(home, {"statusLine": previous})
    wiring.install_statusline(apply=True)
    assert wiring.run_chained(b'{"a": 1}') == b'OLD BAR {"a": 1}'


def test_chain_failure_returns_nothing(home: Path) -> None:
    wiring.record_path().parent.mkdir(parents=True)
    wiring.record_path().write_text(
        json.dumps({"previous": {"type": "command", "command": "exit 3"}}), encoding="utf-8"
    )
    assert wiring.run_chained(b"") == b""


def _stdin(monkeypatch, data: bytes) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data), encoding="utf-8"))


def test_cli_claude_reads_the_workspace_folder(home: Path, tmp_path: Path, capsys, monkeypatch):
    root = tmp_path / "brain"
    setup_repo(root, "Acme Co", "all", mode="agency", apply=True)
    _stdin(monkeypatch, json.dumps({"workspace": {"current_dir": str(root / "business")}}).encode())
    code = main(["statusline", "--claude", str(tmp_path)])
    output = capsys.readouterr().out
    assert code == 0
    assert output.startswith("MARKETINGOS │ ● ACTIVE │ AGENCY BRAIN · Acme Co │ SKILLS ")


def test_cli_claude_falls_back_to_cwd_field(home: Path, tmp_path: Path, capsys, monkeypatch):
    _stdin(monkeypatch, json.dumps({"cwd": str(tmp_path)}).encode())
    code = main(["statusline", "--claude", str(home)])
    assert code == 0
    assert capsys.readouterr().out.endswith(f"CWD: {tmp_path.resolve()}\n")


@pytest.mark.parametrize("payload", [b"", b"not json", b"[1, 2]", b'{"workspace": 5}'])
def test_cli_claude_survives_bad_stdin(home: Path, tmp_path, capsys, monkeypatch, payload):
    _stdin(monkeypatch, payload)
    code = main(["statusline", "--claude", str(tmp_path)])
    assert code == 0
    assert capsys.readouterr().out.startswith("MARKETINGOS │ ○ INACTIVE │ CWD: ")


def test_cli_claude_never_reads_a_terminal(home: Path, tmp_path, capsys, monkeypatch):
    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

        def read(self, *args):  # pragma: no cover - reading here would hang a real terminal
            raise AssertionError("stdin must not be read from a terminal")

    monkeypatch.setattr(sys, "stdin", Terminal())
    assert main(["statusline", "--claude", "--chain", str(tmp_path)]) == 0
    assert "INACTIVE" in capsys.readouterr().out


def test_cli_divider_and_chain(home: Path, tmp_path: Path, capsys, monkeypatch) -> None:
    script = tmp_path / "old_bar.py"
    script.write_text("import sys\nsys.stdout.write('OLD BAR\\n')\n", encoding="utf-8")
    previous = {"type": "command", "command": _command_line([sys.executable, str(script)])}
    _write_settings(home, {"statusLine": previous})
    wiring.install_statusline(apply=True)
    monkeypatch.setenv("COLUMNS", "30")
    _stdin(monkeypatch, json.dumps({"cwd": str(tmp_path)}).encode())
    code = main(["statusline", "--claude", "--divider", "--chain"])
    lines = capsys.readouterr().out.splitlines()
    assert code == 0
    assert lines[0].startswith("MARKETINGOS │ ○ INACTIVE")
    assert lines[1] == "─" * 30
    assert lines[2] == "OLD BAR"


def test_cli_install_requires_plan_or_yes(home: Path, capsys) -> None:
    code = main(["statusline", "--install", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert not _settings(home).exists()


def test_cli_plan_without_install_is_rejected(home: Path, tmp_path: Path, capsys) -> None:
    code = main(["statusline", str(tmp_path), "--plan", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert code == 0  # the badge form always exits 0, even for a usage mistake


def test_cli_install_and_uninstall_round_trip(home: Path, capsys) -> None:
    _write_settings(home, {"statusLine": PREVIOUS})
    assert main(["statusline", "--install", "--yes"]) == 0
    output = capsys.readouterr().out
    assert "set statusLine.command" in output
    assert _read_settings(home)["statusLine"]["command"].endswith(wiring.BADGE_ARGS)
    assert main(["statusline", "--uninstall", "--yes", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "uninstall"
    assert _read_settings(home)["statusLine"] == PREVIOUS


def test_install_and_uninstall_are_exclusive(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["statusline", "--install", "--uninstall", "--yes"])
    assert exc.value.code == 2


def test_badge_command_prefers_the_running_mos(home: Path, tmp_path: Path, monkeypatch) -> None:
    launcher = tmp_path / "venv" / "bin" / "mos"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(launcher), "statusline", "--install"])
    assert wiring.badge_command().startswith(_command_line([str(launcher.resolve())]))


def test_badge_command_falls_back_to_path(home: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["python", "-m", "marketing_os"])
    assert wiring.running_executable() == ""
    assert wiring.badge_command() == "/opt/mos/bin/mos " + wiring.BADGE_ARGS


def test_cli_badge_survives_a_closed_pipe(home: Path, tmp_path: Path, monkeypatch) -> None:
    class ClosedPipe(io.StringIO):
        def write(self, text: str) -> int:
            raise BrokenPipeError

    monkeypatch.setattr(sys, "stdout", ClosedPipe())
    assert main(["statusline", str(tmp_path), "--divider"]) == 0
