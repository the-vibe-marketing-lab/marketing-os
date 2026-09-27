import json
from pathlib import Path

import pytest

from marketing_os.cli.main import run_argv
from marketing_os.core import months as months_mod
from marketing_os.core.fix import FIXABLE, fix_repo
from marketing_os.core.ingest import ingest_repo
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
        + "- [Relative](./business/decisions/2026/09/2026-09-22-platform/decision.md)\n"
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
    assert "./business/decisions/2026/09-Sep/2026-09-22-platform/decision.md" in context
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
    # The same dated slug in both folders is a real clash; an empty 09-Sep is not.
    (root / "business/decisions/2026/09-Sep/2026-09-22-platform").mkdir(parents=True)
    before = (root / "CONTEXT.md").read_text(encoding="utf-8")
    result = migrate_month_folders(root, apply=True)
    assert result["ok"] is False and result["applied"] is False
    assert [f["code"] for f in result["findings"]] == ["month-folder-exists"]
    assert result["findings"][0]["path"] == "business/decisions/2026/09"
    # Nothing moved anywhere, not even the month that had no collision.
    assert (root / "knowledge/sources/2026/09").is_dir()
    assert not (root / "knowledge/sources/2026/09-Sep").exists()
    assert (root / "CONTEXT.md").read_text(encoding="utf-8") == before


def test_links_to_a_month_renamed_by_hand_are_not_this_rules_to_follow(tmp_path: Path) -> None:
    """Only folders this command renamed are link targets; a hand rename is not one."""
    root = _legacy_brain(tmp_path)
    for tree in ("business/decisions", "knowledge/sources"):
        (root / tree / "2026" / "09").rename(root / tree / "2026" / "09-Sep")
    before = (root / "CONTEXT.md").read_text(encoding="utf-8")
    result = migrate_month_folders(root, apply=True)
    assert result["renamed"] == 0 and result["rewritten_links"] == 0
    assert (root / "CONTEXT.md").read_text(encoding="utf-8") == before


def test_a_failed_rewrite_is_finished_by_the_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The journal carries a moved month's links across runs."""
    root = _legacy_brain(tmp_path)
    real = months_mod.atomic_write

    def full_disk(path: Path, text: str) -> None:
        if path.name == "CONTEXT.md":
            raise OSError(28, "No space left on device")
        real(path, text)

    monkeypatch.setattr(months_mod, "atomic_write", full_disk)
    first = migrate_month_folders(root, apply=True)
    assert first["ok"] is False
    assert [f["code"] for f in first["findings"]] == ["rewrite-failed"]
    assert first["renamed"] == 2
    journal = json.loads((root / ".mos/local/month-moves.json").read_text(encoding="utf-8"))
    assert journal["moves"] == {
        "business/decisions/2026/09": {"new": "business/decisions/2026/09-Sep", "state": "done"},
        "knowledge/sources/2026/09": {"new": "knowledge/sources/2026/09-Sep", "state": "done"},
    }
    monkeypatch.setattr(months_mod, "atomic_write", real)
    second = migrate_month_folders(root, apply=True)
    assert second["ok"] is True and second["renamed"] == 0
    assert second["changes"] == ["rewrite 3 links in CONTEXT.md"]
    assert not (root / ".mos/local/month-moves.json").exists()  # a clean run clears it


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


def _post(root: Path, relative: str, body: str) -> Path:
    return _doc(root, relative, body, sources="sources:\n  - business/strategy/strategy.md\n")


def test_only_links_that_resolve_into_a_moved_month_are_rewritten(tmp_path: Path) -> None:
    """Review item 1 and 10: archive copies and a 09.md file are not the moved month."""
    root = _legacy_brain(tmp_path)
    note = root / "knowledge" / "wiki" / "note.md"
    note.write_text(
        "- [[archive/content/2026/09/2026-09-01-old/post.md]]\n"
        "- [file](content/2026/09.md)\n"
        f"- [[{DECISION}]]\n",
        encoding="utf-8",
    )
    migrate_month_folders(root, apply=True)
    text = note.read_text(encoding="utf-8")
    assert "archive/content/2026/09/2026-09-01-old/post.md" in text
    assert "(content/2026/09.md)" in text
    assert DECISION.replace("/2026/09/", "/2026/09-Sep/") in text


def test_urls_and_code_are_never_rewritten(tmp_path: Path) -> None:
    """Review item 2: provenance URLs, inline code and fenced blocks keep their text."""
    root = _legacy_brain(tmp_path)
    note = root / "knowledge" / "wiki" / "note.md"
    body = (
        "---\ntitle: N\nsources:\n"
        "  - https://example.com/content/2026/09/launch\n"
        "  - https://blog.example.com/2026/09/2026-09-15-launch\n---\n"
        f"Inline `{DECISION}` stays.\n\n```\n{DECISION}\n```\n\n"
        f"~~~text\n{DECISION}\n~~~\n\nBut [[{DECISION}]] moves.\n"
    )
    note.write_text(body, encoding="utf-8")
    result = migrate_month_folders(root, apply=True)
    assert "rewrite 1 link in knowledge/wiki/note.md" in result["changes"]
    expected = body.replace(f"[[{DECISION}]]", f"[[{DECISION.replace('/09/', '/09-Sep/')}]]")
    assert note.read_text(encoding="utf-8") == expected


def test_month_relative_links_are_carried_across(tmp_path: Path) -> None:
    """Review item 3: links that climb to, or start from, the year folder."""
    root = _brain(tmp_path)
    _post(root, "content/2026/09/2026-09-01-a/post.md", "# A")
    october = _post(
        root, "content/2026/10-Oct/2026-10-01-b/post.md", "[a](../../09/2026-09-01-a/post.md)"
    )
    index = root / "content" / "2026" / "index.md"
    index.write_text("[sep](09/2026-09-01-a/post.md) and [dot](./09/2026-09-01-a/post.md)\n")
    migrate_month_folders(root, apply=True)
    assert "(../../09-Sep/2026-09-01-a/post.md)" in october.read_text(encoding="utf-8")
    assert index.read_text() == (
        "[sep](09-Sep/2026-09-01-a/post.md) and [dot](./09-Sep/2026-09-01-a/post.md)\n"
    )


def test_a_failed_move_still_rewrites_what_moved_and_finishes_on_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review item 4: a file lock part-way leaves a consistent brain and a rerun path."""
    root = _legacy_brain(tmp_path)
    real = months_mod._move

    def locked(root: Path, source: Path, target: Path, merge: bool, progress: list) -> None:
        if source.as_posix().endswith("knowledge/sources/2026/09"):
            raise PermissionError(13, "The process cannot access the file")
        real(root, source, target, merge, progress)

    monkeypatch.setattr(months_mod, "_move", locked)
    result = migrate_month_folders(root, apply=True)
    assert result["ok"] is False and result["applied"] is True
    assert [f["code"] for f in result["findings"]] == ["month-move-failed"]
    assert result["next_action"]["id"] == "rerun-fix"
    assert "rename business/decisions/2026/09 -> business/decisions/2026/09-Sep" in result[
        "changes"
    ]
    context = (root / "CONTEXT.md").read_text(encoding="utf-8")
    assert "business/decisions/2026/09-Sep/" in context  # the moved month's links followed
    assert "business/decisions/2026/09/" not in context

    monkeypatch.setattr(months_mod, "_move", real)
    again = migrate_month_folders(root, apply=True)
    assert again["ok"] is True and again["renamed"] == 1
    assert validate_repo(root)["ok"] is True
    assert "knowledge/sources/2026/09/" not in (root / "CONTEXT.md").read_text(encoding="utf-8")


def test_fix_all_never_runs_the_month_migration(tmp_path: Path) -> None:
    """Review item 5: the rename runs only when named."""
    root = _legacy_brain(tmp_path)
    result = fix_repo(root, None, apply=True, all_codes=True)
    assert "invalid-month" not in result["ran"]
    assert (root / "business/decisions/2026/09").is_dir()
    assert not (root / "business/decisions/2026/09-Sep").exists()


def test_ingest_before_migrating_is_merged_not_refused(tmp_path: Path) -> None:
    """Review item 6: the first capture after upgrading makes 09-Sep beside the legacy 09."""
    root = _legacy_brain(tmp_path)
    captured = ingest_repo(root, "a note", topic=None, slug="new", date="2026-09-26", apply=True)
    assert captured["source_dir"] == "knowledge/sources/2026/09-Sep/2026-09-26-new"
    plan = migrate_month_folders(root, apply=False)
    assert plan["ok"] is True
    assert "merge knowledge/sources/2026/09 into knowledge/sources/2026/09-Sep" in plan["changes"]
    result = migrate_month_folders(root, apply=True)
    assert result["ok"] is True
    merged = root / "knowledge/sources/2026/09-Sep"
    assert {child.name for child in merged.iterdir()} >= {"2026-09-21-concept", "2026-09-26-new"}
    assert not (root / "knowledge/sources/2026/09").exists()
    assert validate_repo(root)["ok"] is True


def test_unreadable_and_symlinked_documents_are_reported(tmp_path: Path) -> None:
    """Review items 7 and 9: never silently skipped, and a symlink stays a symlink."""
    root = _legacy_brain(tmp_path)
    (root / "knowledge/wiki/latin1.md").write_bytes(f"caf\xe9 [[{DECISION}]]\n".encode("latin-1"))
    real = root / "knowledge/wiki/real.md"
    real.write_text(f"[[{DECISION}]]\n", encoding="utf-8")
    link = root / "knowledge/wiki/link.md"
    link.symlink_to(real)
    plan = migrate_month_folders(root, apply=False)
    codes = {(f["code"], f["path"]) for f in plan["findings"]}
    assert ("unreadable-document", "knowledge/wiki/latin1.md") in codes
    assert ("linked-document", "knowledge/wiki/link.md") in codes
    assert all(f["severity"] == "warning" for f in plan["findings"])
    migrate_month_folders(root, apply=True)
    assert link.is_symlink()


def test_rewritten_documents_keep_their_mode(tmp_path: Path) -> None:
    """Review item 9: the atomic rewrite no longer leaves documents 0600."""
    root = _legacy_brain(tmp_path)
    context = root / "CONTEXT.md"
    context.chmod(0o644)
    migrate_month_folders(root, apply=True)
    assert context.stat().st_mode & 0o777 == 0o644


def test_canvas_and_base_file_paths_are_rewritten(tmp_path: Path) -> None:
    """Review item 8: Obsidian canvases and bases carry vault paths too."""
    root = _legacy_brain(tmp_path)
    canvas = root / "knowledge/wiki/map.canvas"
    canvas.write_text(json.dumps({"nodes": [{"type": "file", "file": DECISION}]}))
    base = root / "knowledge/wiki/decisions.base"
    base.write_text('filters:\n  - file.inFolder("business/decisions/2026/09")\n')
    migrate_month_folders(root, apply=True)
    new = DECISION.replace("/2026/09/", "/2026/09-Sep/")
    assert json.loads(canvas.read_text())["nodes"][0]["file"] == new
    assert 'file.inFolder("business/decisions/2026/09-Sep")' in base.read_text()


def test_update_skill_offers_the_migration_or_the_mm_pin() -> None:
    """Review item 11: an upgraded brain goes red, so /mos-update says how to go green."""
    from marketing_os.core.schema import assets_root

    text = (assets_root() / "skills" / "mos-update" / "SKILL.md").read_text(encoding="utf-8")
    assert "mos validate . --json" in text
    assert "mos fix invalid-month . --plan --json" in text
    assert '"month_folder": "MM"' in text
    assert "not part of `mos fix --all`" in text


def test_reporting_is_out_of_scope(tmp_path: Path) -> None:
    """Richard's scope rule: reporting/YYYY/QN/YYYY-MM holds quarters, not months."""
    root = _legacy_brain(tmp_path)
    report = _doc(
        root,
        "reporting/2026/Q3/2026-09/report.md",
        "# September",
        sources=f"sources:\n  - {SOURCE}\n",
        type_="report",
    )
    note = root / "knowledge/wiki/note.md"
    note.write_text("[[reporting/2026/Q3/2026-09/report.md]]\n", encoding="utf-8")
    migrate_month_folders(root, apply=True)
    assert report.is_file()
    assert sorted(p.name for p in (root / "reporting/2026").iterdir()) == ["Q3"]
    assert note.read_text(encoding="utf-8") == "[[reporting/2026/Q3/2026-09/report.md]]\n"
    assert validate_repo(root)["ok"] is True


def test_a_year_folder_without_months_is_left_alone(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    year = root / "content" / "2026"
    (year / "notes").mkdir(parents=True)
    (year / "2026-09").mkdir()
    (year / "readme.txt").write_text("loose file", encoding="utf-8")
    result = migrate_month_folders(root, apply=True)
    assert result["changes"] == []
    assert sorted(p.name for p in year.iterdir()) == ["2026-09", "notes", "readme.txt"]
    codes = [f["code"] for f in validate_repo(root)["findings"]]
    assert "invalid-month" not in codes


def test_a_mixed_year_folder_renames_only_its_bare_months(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    _post(root, "content/2026/09/2026-09-01-a/post.md", "# A")
    _post(root, "content/2026/10-Oct/2026-10-01-b/post.md", "# B")
    year = root / "content" / "2026"
    (year / "notes").mkdir()
    (year / "2026-11").mkdir()
    result = migrate_month_folders(root, apply=True)
    assert result["changes"][0] == "rename content/2026/09 -> content/2026/09-Sep"
    assert result["renamed"] == 1
    assert sorted(p.name for p in year.iterdir()) == ["09-Sep", "10-Oct", "2026-11", "notes"]


# --- final review round -------------------------------------------------------------------


def _with_content_month(tmp_path: Path) -> Path:
    root = _legacy_brain(tmp_path)
    _post(root, "content/2026/09/2026-09-01-a/post.md", "# A")
    return root


def test_text_outside_link_positions_is_never_rewritten(tmp_path: Path) -> None:
    """Dates and month-looking text in prose, headings, tables and other keys stay put."""
    root = _with_content_month(tmp_path)
    page = root / "content" / "p.md"
    page_text = (
        "---\ntitle: P\ndate: 2026/09/15\nperiod: 2026/09\nnotes: content/2026/09\n---\n"
        "# In 2026/09 we launched\n\n| Month | Result |\n|---|---|\n| 2026/09 | up |\n\n"
        "On 2026/09/15 we shipped content/2026/09/2026-09-01-a/post.md as plain text.\n"
    )
    page.write_text(page_text, encoding="utf-8")
    year_note = root / "content" / "2026" / "c.md"
    year_note.write_text("US date 09/15 and 09/2026, and 09/2026-09-01-a in prose.\n")
    migrate_month_folders(root, apply=True)
    assert page.read_text(encoding="utf-8") == page_text
    assert year_note.read_text() == "US date 09/15 and 09/2026, and 09/2026-09-01-a in prose.\n"


def test_every_link_position_is_rewritten(tmp_path: Path) -> None:
    root = _with_content_month(tmp_path)
    target = "content/2026/09/2026-09-01-a/post.md"
    moved = target.replace("/09/", "/09-Sep/")
    page = root / "knowledge" / "wiki" / "links.md"
    page.write_text(
        "---\ntitle: L\n"
        f"sources: {target}\n"
        f'related: [{target}, "content/2026/09"]\n'
        "---\n"
        f"[a]({target}) ![img]({target}) [t](<{target}> \"Title\") [h]({target}#part)\n"
        f"[[{target}|Alias]] ![[{target}#Heading]]\n\n"
        f"[ref]: {target}\n",
        encoding="utf-8",
    )
    result = migrate_month_folders(root, apply=True)
    assert "rewrite 10 links in knowledge/wiki/links.md" in result["changes"]
    assert page.read_text(encoding="utf-8") == (
        "---\ntitle: L\n"
        f"sources: {moved}\n"
        f'related: [{moved}, "content/2026/09-Sep"]\n'
        "---\n"
        f"[a]({moved}) ![img]({moved}) [t](<{moved}> \"Title\") [h]({moved}#part)\n"
        f"[[{moved}|Alias]] ![[{moved}#Heading]]\n\n"
        f"[ref]: {moved}\n"
    )


def test_a_document_relative_link_that_exists_wins(tmp_path: Path) -> None:
    """A Markdown link in archive/ that names archive's own copy is not redirected."""
    root = _with_content_month(tmp_path)
    old = "content/2026/09/2026-09-01-old/a.md"
    (root / "archive" / old).parent.mkdir(parents=True)
    (root / "archive" / old).write_text("# Old\n", encoding="utf-8")
    index = root / "archive" / "idx.md"
    index.write_text(f"[a]({old})\n", encoding="utf-8")
    result = migrate_month_folders(root, apply=True)
    assert index.read_text(encoding="utf-8") == f"[a]({old})\n"
    assert not [f for f in result["findings"] if f["path"] == "archive/idx.md"]


def test_a_link_that_reads_two_existing_ways_is_reported(tmp_path: Path) -> None:
    root = _with_content_month(tmp_path)
    link = "content/2026/09/2026-09-01-a/post.md"
    (root / "archive" / link).parent.mkdir(parents=True)
    (root / "archive" / link).write_text("# Copy\n", encoding="utf-8")
    index = root / "archive" / "idx.md"
    index.write_text(f"[a]({link})\n", encoding="utf-8")
    plan = migrate_month_folders(root, apply=False)
    found = {(f["code"], f["path"]) for f in plan["findings"]}
    assert ("ambiguous-link", "archive/idx.md") in found
    migrate_month_folders(root, apply=True)
    assert index.read_text(encoding="utf-8") == f"[a]({link})\n"


def test_the_journal_does_not_outlive_a_clean_run(tmp_path: Path) -> None:
    root = _with_content_month(tmp_path)
    assert migrate_month_folders(root, apply=True)["ok"] is True
    assert not (root / ".mos/local/month-moves.json").exists()
    # Later, by hand: a new 2025 month, renamed, and a note that links the old name.
    (root / "content/2025/09/2025-09-01-z").mkdir(parents=True)
    (root / "content/2025/09").rename(root / "content/2025/09-Sep")
    note = root / "knowledge/wiki/later.md"
    note.write_text("[[content/2025/09/2025-09-01-z/post.md]]\n", encoding="utf-8")
    plan = migrate_month_folders(root, apply=False)
    assert plan["changes"] == []


def test_a_stale_journal_entry_is_ignored(tmp_path: Path) -> None:
    root = _with_content_month(tmp_path)
    journal = root / ".mos/local/month-moves.json"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        json.dumps({"moves": {"content/2025/09": {"new": "content/2025/09-Sep", "state": "done"}}})
    )
    note = root / "knowledge/wiki/later.md"
    note.write_text("[[content/2025/09/x.md]]\n", encoding="utf-8")
    plan = migrate_month_folders(root, apply=False)
    assert not any("later.md" in line for line in plan["changes"])


def test_a_partial_merge_is_journalled_reported_and_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _with_content_month(tmp_path)
    _post(root, "content/2026/09/2026-09-02-b/post.md", "# B")
    (root / "content/2026/09-Sep/2026-09-26-new").mkdir(parents=True)
    note = root / "knowledge/wiki/n.md"
    note.write_text("[[content/2026/09/2026-09-01-a/post.md]]\n", encoding="utf-8")
    real = months_mod._step

    def locked(root_: Path, source: Path, target: Path) -> None:
        if source.name == "2026-09-02-b":
            raise PermissionError(13, "The process cannot access the file")
        real(root_, source, target)

    monkeypatch.setattr(months_mod, "_step", locked)
    first = migrate_month_folders(root, apply=True)
    assert first["ok"] is False and first["applied"] is True
    assert (
        "merge content/2026/09 into content/2026/09-Sep (partly: 1 entry moved)" in first["changes"]
    )
    assert note.read_text() == "[[content/2026/09-Sep/2026-09-01-a/post.md]]\n"
    monkeypatch.setattr(months_mod, "_step", real)
    second = migrate_month_folders(root, apply=True)
    assert second["ok"] is True
    assert not (root / "content/2026/09").exists()
    assert validate_repo(root)["ok"] is True


def test_a_backslash_link_into_a_moved_month_is_reported(tmp_path: Path) -> None:
    root = _with_content_month(tmp_path)
    note = root / "knowledge/wiki/win.md"
    note.write_text("[a](content\\2026\\09\\2026-09-01-a\\post.md)\n", encoding="utf-8")
    plan = migrate_month_folders(root, apply=False)
    assert ("backslash-link", "knowledge/wiki/win.md") in {
        (f["code"], f["path"]) for f in plan["findings"]
    }
    migrate_month_folders(root, apply=True)
    assert note.read_text() == "[a](content\\2026\\09\\2026-09-01-a\\post.md)\n"


def test_a_case_only_twin_is_refused(tmp_path: Path) -> None:
    """On a case-insensitive disk 09-sep would pass for 09-Sep; the real name is compared."""
    root = _with_content_month(tmp_path)
    (root / "content/2026/09-sep").mkdir()
    result = migrate_month_folders(root, apply=True)
    assert result["ok"] is False
    assert [f["code"] for f in result["findings"]] == ["month-folder-case"]
    assert (root / "content/2026/09").is_dir()
    assert (root / "business/decisions/2026/09").is_dir()  # nothing moved anywhere


def test_a_crash_after_a_move_is_reconciled_on_the_next_run(tmp_path: Path) -> None:
    """Intent is journalled before a move, so a move whose links never ran is finished."""
    root = _legacy_brain(tmp_path)
    journal = root / ".mos/local/month-moves.json"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        json.dumps(
            {
                "moves": {
                    "business/decisions/2026/09": {
                        "new": "business/decisions/2026/09-Sep",
                        "state": "pending",
                    }
                }
            }
        )
    )
    # The crash: the rename happened, the confirmation and the link rewrites did not.
    (root / "business/decisions/2026/09").rename(root / "business/decisions/2026/09-Sep")
    result = migrate_month_folders(root, apply=True)
    assert result["ok"] is True
    context = (root / "CONTEXT.md").read_text(encoding="utf-8")
    assert "business/decisions/2026/09-Sep/2026-09-22-platform" in context
    assert "business/decisions/2026/09/" not in context
    assert not journal.exists()
    assert validate_repo(root)["ok"] is True
