import json
from pathlib import Path

from marketing_os.core.schema import config_text
from marketing_os.core.setup import setup_repo
from marketing_os.core.statusline import (
    display_path,
    divider_width,
    render_badge,
    render_divider,
    statusline_repo,
)


def test_statusline_inactive_outside_repo(tmp_path: Path, monkeypatch) -> None:
    # Windows keeps temp under the home folder; move home aside so the path stays full.
    home = tmp_path.parent / f"{tmp_path.name}-home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    result = statusline_repo(tmp_path)
    assert result["ok"] is True
    assert result["active"] is False
    assert result["cwd"] == str(tmp_path.resolve())
    assert result["line"] == f"MARKETINGOS │ ○ INACTIVE │ CWD: {tmp_path.resolve()}"


def test_statusline_inactive_shortens_home(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    folder = home / "projects" / "site"
    folder.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    result = statusline_repo(folder)
    assert result["line"].endswith(f"CWD: {Path('~') / 'projects' / 'site'}")
    assert display_path(home.resolve()) == "~"


def test_statusline_active_line_is_plain(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Acme Co", "all", mode="in-house", apply=True)
    result = statusline_repo(root)
    assert result["ok"] is True
    assert result["active"] is True
    assert result["line"].startswith("MARKETINGOS │ ● ACTIVE │ IN-HOUSE BRAIN · Acme Co")
    assert "skills" in result["line"]
    assert "\x1b" not in result["line"]
    assert result["skills"]["installed"] == result["skills"]["total"]
    assert result["skills"]["total"] >= 1


def test_statusline_walks_up_from_subdir(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Acme Co", "all", mode="in-house", apply=True)
    result = statusline_repo(root / "business" / "brand")
    assert result["active"] is True
    assert result["repo"] == str(root.resolve())
    assert "Acme Co" in result["line"]


def test_statusline_counts_missing_skills(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    (root / ".mos").mkdir(parents=True)
    (root / ".mos" / "config.yaml").write_text(config_text("Solo"), encoding="utf-8")
    result = statusline_repo(root)
    assert result["active"] is True
    assert result["skills"]["installed"] == 0
    total = result["skills"]["total"]
    assert total >= 1
    # A config with no mode names a plain brain rather than guessing its type.
    assert result["line"] == f"MARKETINGOS │ ● ACTIVE │ BRAIN · Solo │ skills 0/{total}"


def test_statusline_includes_mode_segment(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Acme Co", "all", mode="agency", apply=True)
    result = statusline_repo(root)
    assert result["mode"] == "agency"
    assert "│ AGENCY BRAIN · Acme Co │" in result["line"]


def test_statusline_omits_mode_for_legacy_repo(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    (root / ".mos").mkdir(parents=True)
    (root / ".mos" / "config.yaml").write_text(config_text("Legacy Co"), encoding="utf-8")
    result = statusline_repo(root)
    assert result["mode"] is None
    total = result["skills"]["total"]
    assert result["line"] == f"MARKETINGOS │ ● ACTIVE │ BRAIN · Legacy Co │ skills 0/{total}"


def test_statusline_omits_invalid_mode_but_keeps_fact(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Acme Co", "all", mode="in-house", apply=True)
    config_path = root / ".mos" / "config.yaml"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["mode"] = "franchise"
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = statusline_repo(root)
    # The invalid value is carried verbatim in facts but never rendered on the line.
    assert result["mode"] == "franchise"
    assert "franchise" not in result["line"].lower()
    total = result["skills"]["total"]
    assert result["line"] == f"MARKETINGOS │ ● ACTIVE │ BRAIN · Acme Co │ skills {total}/{total}"


def test_statusline_business_fact_is_status_shaped(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Acme Co", "all", mode="in-house", apply=True)
    result = statusline_repo(root)
    # Matches core/status.py's business shape.
    assert result["business"] == {"name": "Acme Co"}


def test_statusline_counts_mismatched_skills_as_not_installed(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Acme Co", "all", mode="in-house", apply=True)
    baseline = statusline_repo(root)
    total = baseline["skills"]["total"]
    assert baseline["skills"]["installed"] == total

    # Make one installed Claude skill stale so its content hash no longer matches.
    skill_file = next(
        path for path in sorted((root / ".claude" / "skills").rglob("*")) if path.is_file()
    )
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8") + "\nstale drift\n", encoding="utf-8"
    )

    result = statusline_repo(root)
    assert result["skills"]["total"] == total
    # A stale (mismatched) skill is not installed.
    assert result["skills"]["installed"] == total - 1
    assert result["line"].endswith(f"skills {total - 1}/{total}")


def test_statusline_color_wraps_segments_and_plain_matches(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Acme Co", "all", mode="agency", apply=True)
    result = statusline_repo(root)
    colored = render_badge(result, color=True)
    assert "\x1b[38;2;201;100;66mMARKETINGOS\x1b[0m" in colored
    assert "\x1b[38;2;74;222;128m● ACTIVE\x1b[0m" in colored
    assert "\x1b[38;2;201;100;66mAGENCY BRAIN\x1b[0m" in colored
    stripped = colored
    for code in ("\x1b[38;2;201;100;66m", "\x1b[38;2;74;222;128m", "\x1b[38;2;148;163;184m"):
        stripped = stripped.replace(code, "")
    stripped = stripped.replace("\x1b[38;2;71;85;105m", "").replace("\x1b[0m", "")
    assert stripped == result["line"]


def test_statusline_inactive_color_is_slate(tmp_path: Path) -> None:
    colored = render_badge(statusline_repo(tmp_path), color=True)
    assert "\x1b[38;2;148;163;184m○ INACTIVE\x1b[0m" in colored


def test_divider_width_is_capped_and_floored() -> None:
    assert divider_width("200") == 72
    assert divider_width("40") == 40
    assert divider_width("3") == 10
    assert divider_width("not-a-number") == 72
    assert divider_width("") == 72
    assert render_divider(columns="20") == "─" * 20
    assert render_divider(color=True, columns="12") == "\x1b[38;2;71;85;105m" + "─" * 12 + "\x1b[0m"
