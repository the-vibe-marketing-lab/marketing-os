import io
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from marketing_os.cli.main import main, run_argv
from marketing_os.core import statusline_install as wiring
from marketing_os.core import statusline_options as options
from marketing_os.core.setup import setup_repo
from marketing_os.core.statusline import OPTION_DEFAULTS, render_badge, statusline_repo

ANSI = "\x1b["


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    # Never the real ~/.claude or ~/.marketing-os.
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    monkeypatch.setattr(wiring.shutil, "which", lambda name: "/opt/mos/bin/mos")
    return path


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    setup_repo(root, "Acme Co", "all", mode="agency", apply=True)
    return root


def _record() -> dict:
    return json.loads(wiring.record_path().read_text(encoding="utf-8"))


def _stdin(monkeypatch, data: bytes) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data), encoding="utf-8"))


def _plain(text: str) -> str:
    out = text
    while ANSI in out:
        start = out.index(ANSI)
        end = out.index("m", start)
        out = out[:start] + out[end + 1 :]
    return out


# --- rendering -------------------------------------------------------------------


def test_defaults_render_the_documented_badge(brain: Path) -> None:
    result = statusline_repo(brain)
    total = result["skills"]["total"]
    assert (
        result["line"]
        == f"MARKETINGOS │ ● ACTIVE │ AGENCY BRAIN · Acme Co │ SKILLS {total}/{total}"
    )
    assert render_badge(result, options=dict(OPTION_DEFAULTS)) == result["line"]


def test_label_and_accent_change_the_head(brain: Path) -> None:
    result = statusline_repo(brain)
    painted = render_badge(result, color=True, options={"label": "MOS", "accent": "#22C55E"})
    assert painted.startswith("\x1b[38;2;34;197;94mMOS\x1b[0m")
    assert "\x1b[38;2;34;197;94mAGENCY BRAIN\x1b[0m" in painted
    assert _plain(painted).startswith("MOS │ ● ACTIVE │ AGENCY BRAIN")
    inactive = statusline_repo(brain.parent / "nowhere", options={"label": "MOS"})
    assert inactive["line"].startswith("MOS │ ○ INACTIVE │ CWD: ")


def test_show_name_and_show_skills_drop_their_segments(brain: Path) -> None:
    result = statusline_repo(brain)
    assert render_badge(result, options={"show_name": False}) == (
        "MARKETINGOS │ ● ACTIVE │ AGENCY BRAIN │ SKILLS "
        f"{result['skills']['installed']}/{result['skills']['total']}"
    )
    assert render_badge(result, options={"show_skills": False}) == (
        "MARKETINGOS │ ● ACTIVE │ AGENCY BRAIN · Acme Co"
    )
    assert render_badge(result, options={"show_name": False, "show_skills": False}) == (
        "MARKETINGOS │ ● ACTIVE │ AGENCY BRAIN"
    )


def test_show_cwd_drops_the_folder_on_the_inactive_line(tmp_path: Path) -> None:
    result = statusline_repo(tmp_path)
    assert render_badge(result, options={"show_cwd": False}) == "MARKETINGOS │ ○ INACTIVE"
    # The active line has no folder segment, so the option leaves it alone.
    root = tmp_path / "brain"
    setup_repo(root, "Acme Co", "all", mode="in-house", apply=True)
    active = statusline_repo(root)
    assert render_badge(active, options={"show_cwd": False}) == active["line"]


# --- the CLI badge forms ---------------------------------------------------------


def test_claude_form_draws_with_saved_options(home: Path, brain: Path, capsys, monkeypatch):
    wiring.rewrite_record_options({"label": "MOS", "show_skills": False, "divider": False})
    _stdin(monkeypatch, json.dumps({"cwd": str(brain)}).encode())
    assert main(["statusline", "--claude"]) == 0
    out = capsys.readouterr().out
    assert ANSI in out  # colour is on by default
    assert _plain(out) == "MOS │ ● ACTIVE │ AGENCY BRAIN · Acme Co\n"


def test_plain_form_ignores_saved_options(home: Path, brain: Path, capsys) -> None:
    wiring.rewrite_record_options({"label": "MOS", "divider": True, "color": True})
    assert main(["statusline", str(brain)]) == 0
    out = capsys.readouterr().out
    assert ANSI not in out
    assert out.startswith("MARKETINGOS │ ● ACTIVE │ AGENCY BRAIN · Acme Co │ SKILLS ")
    assert out.count("\n") == 1


def test_flags_override_saved_options(home: Path, tmp_path: Path, capsys, monkeypatch) -> None:
    wiring.rewrite_record_options({"color": False, "divider": False})
    monkeypatch.setenv("COLUMNS", "20")
    _stdin(monkeypatch, json.dumps({"cwd": str(tmp_path)}).encode())
    assert main(["statusline", "--claude", "--color", "--divider"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("\x1b[38;2;201;100;66mMARKETINGOS\x1b[0m")
    assert lines[1] == "\x1b[38;2;71;85;105m" + "─" * 20 + "\x1b[0m"

    wiring.rewrite_record_options({"color": True, "divider": True})
    _stdin(monkeypatch, json.dumps({"cwd": str(tmp_path)}).encode())
    assert main(["statusline", "--claude", "--no-color", "--no-divider"]) == 0
    out = capsys.readouterr().out
    assert ANSI not in out
    assert out.count("\n") == 1


def test_color_and_no_color_are_exclusive() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["statusline", "--color", "--no-color"])
    assert exc.value.code == 2


def _old_bar(tmp_path: Path, text: str) -> dict:
    script = tmp_path / "old_bar.py"
    script.write_text(f"import sys\nsys.stdout.write({text!r})\n", encoding="utf-8")
    argv = [sys.executable, str(script)]
    line = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    return {"type": "command", "command": line}


def test_position_bottom_puts_the_badge_under_the_chained_bar(
    home: Path, tmp_path: Path, capsys, monkeypatch
) -> None:
    wiring.settings_path().parent.mkdir(parents=True)
    wiring.settings_path().write_text(
        json.dumps({"statusLine": _old_bar(tmp_path, "OLD BAR\n")}), encoding="utf-8"
    )
    wiring.install_statusline(apply=True)
    options.set_options(["position=bottom", "color=false"], apply=True)
    monkeypatch.setenv("COLUMNS", "12")
    _stdin(monkeypatch, json.dumps({"cwd": str(tmp_path)}).encode())
    assert main(["statusline", "--claude", "--chain"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "OLD BAR"
    assert lines[1] == "─" * 12
    assert lines[2].startswith("MARKETINGOS │ ○ INACTIVE")

    options.set_options(["position=top"], apply=True)
    _stdin(monkeypatch, json.dumps({"cwd": str(tmp_path)}).encode())
    assert main(["statusline", "--claude", "--chain"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("MARKETINGOS │ ○ INACTIVE")
    assert lines[1] == "─" * 12
    assert lines[2] == "OLD BAR"


# --- --options, --set, --reset ---------------------------------------------------


def test_options_reports_defaults_merged_with_saved(home: Path, capsys) -> None:
    result = options.show_options()
    assert result["ok"] is True
    assert result["operation"] == "options"
    assert result["options"] == OPTION_DEFAULTS
    assert result["saved"] == {}
    assert result["installed"] is False
    assert result["defaults"] == OPTION_DEFAULTS

    wiring.rewrite_record_options({"label": "MOS"})
    assert main(["statusline", "--options"]) == 0
    out = capsys.readouterr().out
    assert "Installed: no" in out
    assert '  label: "MOS" (saved)' in out
    assert "  color: true (default)" in out
    assert main(["statusline", "--options", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["options"]["label"] == "MOS"
    assert payload["saved"] == {"label": "MOS"}


def test_set_plan_writes_nothing_and_yes_writes(home: Path) -> None:
    plan = options.set_options(["label=MOS", "accent=#22C55E", "show_skills=no"], apply=False)
    assert plan["ok"] is True
    assert plan["applied"] is False
    assert plan["next_action"]["id"] == "apply"
    assert plan["changes"] == [
        "set label: 'MARKETINGOS' -> 'MOS'",
        "set accent: '#c96442' -> '#22c55e'",
        "set show_skills: True -> False",
    ]
    assert plan["options"]["label"] == "MOS"
    assert plan["saved"] == {}
    assert not wiring.record_path().exists()

    done = options.set_options(["label=MOS", "accent=#22C55E", "show_skills=no"], apply=True)
    assert done["applied"] is True
    assert done["installed"] is False
    assert _record() == {
        "schema": "mos.statusline-record.v2",
        "options": {"label": "MOS", "accent": "#22c55e", "show_skills": False},
    }
    assert options.effective_options()["accent"] == "#22c55e"


def test_set_is_a_no_op_when_nothing_changes(home: Path) -> None:
    result = options.set_options(["label=MARKETINGOS", "color=TRUE"], apply=True)
    assert result["changes"] == []
    assert result["applied"] is False
    assert not wiring.record_path().exists()


@pytest.mark.parametrize(
    ("pair", "code", "key"),
    [
        ("colour=true", "unknown-option", "colour"),
        ("color=maybe", "invalid-option", "color"),
        ("accent=red", "invalid-option", "accent"),
        ("accent=#abc", "invalid-option", "accent"),
        ("position=left", "invalid-option", "position"),
        ("label=", "invalid-option", "label"),
        ("label=" + "x" * 25, "invalid-option", "label"),
        ("label=a\tb", "invalid-option", "label"),
        ("nonsense", "invalid-option", "nonsense"),
    ],
)
def test_set_rejects_bad_pairs_and_writes_nothing(home: Path, pair, code, key) -> None:
    result = options.set_options(["show_name=false", pair], apply=True)
    assert result["ok"] is False
    assert [item["code"] for item in result["findings"]] == [code]
    assert key in result["findings"][0]["message"]
    assert result["next_action"]["id"] == "review-options"
    assert not wiring.record_path().exists()


def test_set_keeps_the_recorded_bar_and_earlier_options(home: Path) -> None:
    wiring.settings_path().parent.mkdir(parents=True)
    wiring.settings_path().write_text(
        json.dumps({"statusLine": {"type": "command", "command": "bash ~/old-bar.sh"}}),
        encoding="utf-8",
    )
    wiring.install_statusline(apply=True)
    options.set_options(["label=MOS"], apply=True)
    result = options.set_options(["accent=#000000"], apply=True)
    assert result["installed"] is True
    record = _record()
    assert record["previous"] == {"type": "command", "command": "bash ~/old-bar.sh"}
    assert record["options"] == {"label": "MOS", "accent": "#000000"}
    assert wiring.chained_command() == "bash ~/old-bar.sh"


def test_set_on_a_v1_record_keeps_its_previous_bar(home: Path) -> None:
    wiring.record_path().parent.mkdir(parents=True)
    previous = {"type": "command", "command": "bash ~/old-bar.sh"}
    wiring.record_path().write_text(
        json.dumps({"schema": "mos.statusline-record.v1", "previous": previous}),
        encoding="utf-8",
    )
    assert options.saved_options() == {}
    assert options.effective_options() == OPTION_DEFAULTS
    options.set_options(["show_cwd=off"], apply=True)
    assert _record() == {
        "schema": "mos.statusline-record.v2",
        "previous": previous,
        "options": {"show_cwd": False},
    }


def test_hand_edited_bad_values_are_ignored_not_fatal(home: Path, tmp_path: Path, capsys):
    wiring.record_path().parent.mkdir(parents=True)
    wiring.record_path().write_text(
        json.dumps({"options": {"accent": "red", "label": "MOS", "bogus": 1, "color": 0}}),
        encoding="utf-8",
    )
    assert options.saved_options() == {"label": "MOS", "color": False}
    assert main(["statusline", "--preview", str(tmp_path)]) == 0
    assert capsys.readouterr().out.startswith("MOS │ ○ INACTIVE")


def test_reset_removes_the_options_and_keeps_the_bar(home: Path) -> None:
    assert options.reset_options(apply=True)["changes"] == []
    wiring.settings_path().parent.mkdir(parents=True)
    wiring.settings_path().write_text(json.dumps({}), encoding="utf-8")
    wiring.install_statusline(apply=True)
    options.set_options(["label=MOS"], apply=True)
    plan = options.reset_options(apply=False)
    assert plan["applied"] is False
    assert len(plan["changes"]) == 1
    assert _record()["options"] == {"label": "MOS"}
    done = options.reset_options(apply=True)
    assert done["applied"] is True
    assert done["options"] == OPTION_DEFAULTS
    assert done["saved"] == {}
    assert _record() == {"schema": "mos.statusline-record.v2", "previous": None}

    # With no recorded bar either, the file goes away.
    wiring.uninstall_statusline(apply=True)
    options.set_options(["label=MOS"], apply=True)
    options.reset_options(apply=True)
    assert not wiring.record_path().exists()


def test_set_and_reset_need_plan_or_yes(home: Path, capsys) -> None:
    assert main(["statusline", "--set", "label=MOS", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert main(["statusline", "--reset", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert main(["statusline", "--options", "--yes", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert main(["statusline", "--set", "label=MOS", "--reset", "--yes", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert not wiring.record_path().exists()


def test_cli_set_round_trip(home: Path, capsys) -> None:
    assert main(["statusline", "--set", "label=MOS", "--set", "position=bottom", "--plan"]) == 0
    out = capsys.readouterr().out
    assert "set label: 'MARKETINGOS' -> 'MOS'" in out
    assert '  label: "MOS" (pending)' in out
    assert '  position: "bottom" (pending)' in out
    assert not wiring.record_path().exists()
    assert main(["statusline", "--set", "label=MOS", "--set", "position=bottom", "--yes"]) == 0
    assert '  label: "MOS" (saved)' in capsys.readouterr().out
    assert _record()["options"] == {"label": "MOS", "position": "bottom"}
    assert main(["statusline", "--set", "accent=red", "--yes", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["findings"][0]["code"] == "invalid-option"
    assert _record()["options"] == {"label": "MOS", "position": "bottom"}
    assert main(["statusline", "--reset", "--yes"]) == 0
    assert not wiring.record_path().exists()


def test_run_argv_serves_the_option_forms(home: Path) -> None:
    payload = run_argv(["statusline", "--set", "label=MOS", "--yes"])
    assert payload["ok"] is True and payload["applied"] is True
    assert run_argv(["statusline", "--options"])["options"]["label"] == "MOS"
    assert run_argv(["statusline", "--reset", "--yes"])["applied"] is True


# --- --preview -------------------------------------------------------------------


def test_preview_draws_saved_plus_pending_and_writes_nothing(
    home: Path, brain: Path, capsys, monkeypatch
) -> None:
    options.set_options(["label=MOS", "color=false"], apply=True)
    monkeypatch.setenv("COLUMNS", "15")
    code = main(["statusline", "--preview", "--set", "show_skills=false", str(brain)])
    assert code == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == ["MOS │ ● ACTIVE │ AGENCY BRAIN · Acme Co", "─" * 15]
    assert _record()["options"] == {"label": "MOS", "color": False}

    assert main(["statusline", "--preview", "--set", "accent=#000000", "--json", str(brain)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "preview"
    assert payload["pending"] == {"accent": "#000000"}
    assert payload["options"]["label"] == "MOS"
    assert payload["options"]["accent"] == "#000000"
    assert payload["line"] == "MOS │ ● ACTIVE │ AGENCY BRAIN · Acme Co │ SKILLS " + (
        f"{payload['skills']['installed']}/{payload['skills']['total']}"
    )
    assert payload["rendered"].startswith("MOS │ ● ACTIVE")
    assert payload["installed"] is False


def test_preview_paints_when_colour_is_on(home: Path, tmp_path: Path, capsys) -> None:
    assert main(["statusline", "--preview", "--no-divider", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("\x1b[38;2;201;100;66mMARKETINGOS\x1b[0m")
    assert out.count("\n") == 1
    argv = ["statusline", "--preview", "--set", "accent=#22c55e", "--json", str(tmp_path)]
    assert main(argv) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rendered"].startswith("\x1b[38;2;34;197;94mMARKETINGOS\x1b[0m")


def test_preview_reports_a_bad_pair_like_any_command(home: Path, tmp_path: Path, capsys):
    assert main(["statusline", "--preview", "--set", "position=middle", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert out.startswith("NEEDS ATTENTION: statusline")
    assert "position must be top or bottom" in out
    assert not wiring.record_path().exists()
