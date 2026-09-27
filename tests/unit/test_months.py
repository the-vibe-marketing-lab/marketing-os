import json
from pathlib import Path

from marketing_os.cli.main import run_argv
from marketing_os.core.fix import FIXABLE
from marketing_os.core.months import migrate_month_folders
from marketing_os.core.setup import setup_repo
from marketing_os.core.validation import validate_repo

DECISION = "business/decisions/2026/09/2026-09-22-platform/decision.md"
SOURCE = "knowledge/sources/2026/09/2026-09-21-concept/source.md"


def _brain(tmp_path: Path, month_folder: str | None = None) -> Path:
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    if month_folder is not None:
        config_path = root / ".mos" / "config.yaml"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["month_folder"] = month_folder
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return root


def _doc(
    root: Path, relative: str, body: str, *, sources: str = "", type_: str = "decision"
) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    front = (
        f"---\ntitle: Doc\ntype: {type_}\ndescription: A doc.\ndate: 2026-09-22\nstatus: active\n"
    )
    front += sources or "related:\n  - business/strategy/strategy.md\n"
    path.write_text(f"{front}---\n{body}\n", encoding="utf-8")
    return path


def _legacy_brain(tmp_path: Path) -> Path:
    """A brain made before 0.5.0: bare 09 folders, and documents that point into them."""
    root = _brain(tmp_path)
    _doc(
        root,
        SOURCE,
        "# Concept",
        sources="sources:\n  - https://example.com/2026/09/post\n",
        type_="source",
    )
    _doc(root, DECISION, f"# Platform\n\nFrom [[{SOURCE}]].", sources=f"sources:\n  - {SOURCE}\n")
    context = root / "CONTEXT.md"
    context.write_text(
        context.read_text(encoding="utf-8")
        + f"\n- [[{DECISION}]]\n- [The month](business/decisions/2026/09)\n"
        + "- Relative: ../decisions/2026/09/2026-09-22-platform/decision.md\n"
        + "- Prose: sales rose 2026/09 to 2026/10.\n",
        encoding="utf-8",
    )
    _doc(
        root,
        "business/strategy/strategy.md",
        "# Strategy",
        sources=f"sources:\n  - {SOURCE}\nrelated:\n  - {DECISION}\n",
        type_="business",
    )
    return root


def test_invalid_month_is_a_deterministic_fix() -> None:
    assert "invalid-month" in FIXABLE


def test_plan_lists_every_rename_and_rewrite_and_writes_nothing(tmp_path: Path) -> None:
    root = _legacy_brain(tmp_path)
    before = (root / "CONTEXT.md").read_text(encoding="utf-8")
    result = migrate_month_folders(root, apply=False)
    assert result["ok"] is True
    assert result["planned"] is True and result["applied"] is False
    assert (
        "rename business/decisions/2026/09 -> business/decisions/2026/09-Sep" in result["changes"]
    )
    assert "rename knowledge/sources/2026/09 -> knowledge/sources/2026/09-Sep" in result["changes"]
    assert "rewrite 3 links in CONTEXT.md" in result["changes"]
    assert "rewrite 2 links in business/strategy/strategy.md" in result["changes"]
    assert result["renamed"] == 2
    assert (root / DECISION).is_file()
    assert not (root / "business/decisions/2026/09-Sep").exists()
    assert (root / "CONTEXT.md").read_text(encoding="utf-8") == before


def test_apply_renames_rewrites_references_and_validates(tmp_path: Path) -> None:
    root = _legacy_brain(tmp_path)
    assert validate_repo(root)["ok"] is False
    result = migrate_month_folders(root, apply=True)
    assert result["ok"] is True and result["applied"] is True
    new_decision = DECISION.replace("/2026/09/", "/2026/09-Sep/")
    new_source = SOURCE.replace("/2026/09/", "/2026/09-Sep/")
    assert (root / new_decision).is_file()
    assert not (root / "business/decisions/2026/09").exists()

    context = (root / "CONTEXT.md").read_text(encoding="utf-8")
    assert f"[[{new_decision}]]" in context
    assert "[The month](business/decisions/2026/09-Sep)" in context
    assert "../decisions/2026/09-Sep/2026-09-22-platform/decision.md" in context
    assert "sales rose 2026/09 to 2026/10." in context  # prose is not a path

    strategy = (root / "business/strategy/strategy.md").read_text(encoding="utf-8")
    assert f"  - {new_source}\n" in strategy and f"  - {new_decision}\n" in strategy
    decision = (root / new_decision).read_text(encoding="utf-8")
    assert f"[[{new_source}]]" in decision  # a document inside a moved month is rewritten too
    source = (root / new_source).read_text(encoding="utf-8")
    assert "https://example.com/2026/09/post" in source  # a URL is left alone

    assert [f for f in validate_repo(root)["findings"] if f["code"] == "invalid-month"] == []
    assert validate_repo(root)["ok"] is True


def test_a_second_run_changes_nothing(tmp_path: Path) -> None:
    root = _legacy_brain(tmp_path)
    migrate_month_folders(root, apply=True)
    snapshot = {p: p.read_bytes() for p in root.rglob("*.md")}
    again = migrate_month_folders(root, apply=True)
    assert again["ok"] is True
    assert again["changes"] == [] and again["applied"] is False
    assert again["next_action"]["id"] == "none"
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == snapshot


def test_a_collision_refuses_the_whole_run(tmp_path: Path) -> None:
    root = _legacy_brain(tmp_path)
    (root / "business/decisions/2026/09-Sep").mkdir()
    before = (root / "CONTEXT.md").read_text(encoding="utf-8")
    result = migrate_month_folders(root, apply=True)
    assert result["ok"] is False and result["applied"] is False
    assert [f["code"] for f in result["findings"]] == ["month-folder-exists"]
    assert result["findings"][0]["path"] == "business/decisions/2026/09"
    # Nothing moved anywhere, not even the month that had no collision.
    assert (root / "knowledge/sources/2026/09").is_dir()
    assert not (root / "knowledge/sources/2026/09-Sep").exists()
    assert (root / "CONTEXT.md").read_text(encoding="utf-8") == before


def test_links_to_a_month_renamed_by_hand_are_still_carried_across(tmp_path: Path) -> None:
    root = _legacy_brain(tmp_path)
    for tree in ("business/decisions", "knowledge/sources"):
        (root / tree / "2026" / "09").rename(root / tree / "2026" / "09-Sep")
    result = migrate_month_folders(root, apply=True)
    assert result["renamed"] == 0
    assert result["rewritten_links"] > 0
    assert "business/decisions/2026/09/" not in (root / "CONTEXT.md").read_text(encoding="utf-8")


def test_crlf_documents_keep_their_line_endings(tmp_path: Path) -> None:
    root = _legacy_brain(tmp_path)
    note = root / "knowledge" / "wiki" / "note.md"
    note.write_bytes(f"---\r\ntitle: N\r\n---\r\nSee [[{DECISION}]].\r\n".encode())
    migrate_month_folders(root, apply=True)
    assert (
        note.read_bytes()
        == (
            "---\r\ntitle: N\r\n---\r\nSee "
            f"[[{DECISION.replace('/2026/09/', '/2026/09-Sep/')}]].\r\n"
        ).encode()
    )


def test_hidden_machinery_is_not_rewritten(tmp_path: Path) -> None:
    root = _legacy_brain(tmp_path)
    hidden = root / ".obsidian" / "note.md"
    hidden.write_text(f"[[{DECISION}]]\n", encoding="utf-8")
    migrate_month_folders(root, apply=True)
    assert hidden.read_text(encoding="utf-8") == f"[[{DECISION}]]\n"


def test_an_mm_brain_is_left_alone(tmp_path: Path) -> None:
    root = _brain(tmp_path, "MM")
    _doc(root, DECISION, "# Platform")
    result = migrate_month_folders(root, apply=True)
    assert result["ok"] is True and result["changes"] == [] and result["applied"] is False
    assert (root / DECISION).is_file()
    assert validate_repo(root)["ok"] is True


def test_an_invalid_style_or_a_non_brain_is_refused(tmp_path: Path) -> None:
    root = _brain(tmp_path, "Month")
    _doc(root, DECISION, "# Platform")
    refused = migrate_month_folders(root, apply=True)
    assert refused["ok"] is False
    assert [f["code"] for f in refused["findings"]] == ["invalid-month-folder"]
    assert (root / DECISION).is_file()

    elsewhere = tmp_path / "not-a-brain"
    (elsewhere / "content" / "2026" / "09").mkdir(parents=True)
    result = migrate_month_folders(elsewhere, apply=True)
    assert result["ok"] is False
    assert [f["code"] for f in result["findings"]] == ["not-marketing-os"]
    assert (elsewhere / "content" / "2026" / "09").is_dir()


def test_mos_fix_invalid_month_runs_the_migration(tmp_path: Path) -> None:
    root = _legacy_brain(tmp_path)
    preview = run_argv(["fix", "invalid-month", str(root), "--plan", "--json"])
    assert preview["ok"] is True and preview["planned"] is True
    assert preview["ran"] == ["month-folders"]
    assert "rename knowledge/sources/2026/09 -> knowledge/sources/2026/09-Sep" in preview["changes"]
    assert (root / DECISION).is_file()

    applied = run_argv(["fix", "invalid-month", str(root), "--yes", "--json"])
    assert applied["ok"] is True and applied["applied"] is True
    assert validate_repo(root)["ok"] is True
