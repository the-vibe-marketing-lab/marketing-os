import json
from pathlib import Path

from marketing_os.core.schema import config_text
from marketing_os.core.setup import setup_repo
from marketing_os.core.statusline import statusline_repo


def test_statusline_inactive_outside_repo(tmp_path: Path) -> None:
    result = statusline_repo(tmp_path)
    assert result["ok"] is True
    assert result["active"] is False
    assert result["line"] == ""


def test_statusline_active_line_is_plain(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Acme Co", "all", mode="in-house", apply=True)
    result = statusline_repo(root)
    assert result["ok"] is True
    assert result["active"] is True
    assert result["line"].startswith("mos")
    assert "Acme Co" in result["line"]
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
    # Separator is plain ASCII " | ", not the middot.
    assert result["line"] == f"mos | Solo | skills 0/{total}"


def test_statusline_includes_mode_segment(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Acme Co", "all", mode="agency", apply=True)
    result = statusline_repo(root)
    assert result["mode"] == "agency"
    assert " | agency | " in result["line"]


def test_statusline_omits_mode_for_legacy_repo(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    (root / ".mos").mkdir(parents=True)
    (root / ".mos" / "config.yaml").write_text(config_text("Legacy Co"), encoding="utf-8")
    result = statusline_repo(root)
    assert result["mode"] is None
    total = result["skills"]["total"]
    assert result["line"] == f"mos | Legacy Co | skills 0/{total}"


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
    assert "franchise" not in result["line"]
    total = result["skills"]["total"]
    assert result["line"] == f"mos | Acme Co | skills {total}/{total}"


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
