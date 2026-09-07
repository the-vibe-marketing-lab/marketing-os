import datetime
from pathlib import Path

import pytest

from marketing_os.core import ingest as ingest_mod
from marketing_os.core.ingest import ingest_repo, pending_sources
from marketing_os.core.schema import config_text


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    (root / ".mos").mkdir(parents=True)
    (root / ".mos" / "config.yaml").write_text(config_text("Example Business"), encoding="utf-8")
    return root


def test_ingest_file_writes_source_with_header(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    note = tmp_path / "note.md"
    note.write_text("Raw research body.", encoding="utf-8")
    result = ingest_repo(root, str(note), topic=None, slug=None, date="2026-07-18", apply=True)
    assert result["ok"] is True
    assert result["form"] == "file"
    assert result["source_dir"] == "knowledge/sources/2026/07/2026-07-18-note"
    text = (root / "knowledge/sources/2026/07/2026-07-18-note/source.md").read_text(
        encoding="utf-8"
    )
    assert "# Source: note" in text
    assert "- Ingested: 2026-07-18" in text
    assert "Raw research body." in text
    assert result["next_action"]["id"] == "compile-source"
    # The compile-source reason is self-contained: it names the real folder.
    assert "knowledge/sources/2026/07/2026-07-18-note/source.md" in result["next_action"]["reason"]
    assert "2026-07-18-note" in result["next_action"]["reason"]


def test_ingest_directory_copies_text_files_under_files_and_manifest(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    src = tmp_path / "dump"
    (src / "sub").mkdir(parents=True)
    (src / "a.md").write_text("alpha", encoding="utf-8")
    (src / "sub" / "b.txt").write_text("bravo", encoding="utf-8")
    (src / "ignore.pdf").write_text("nope", encoding="utf-8")
    result = ingest_repo(root, str(src), topic="Research", slug=None, date="2026-07-18", apply=True)
    assert result["ok"] is True
    # Topic is metadata-only; it is not a path segment.
    assert result["topic"] == "Research"
    assert result["source_dir"] == "knowledge/sources/2026/07/2026-07-18-dump"
    folder = root / "knowledge/sources/2026/07/2026-07-18-dump"
    manifest = (folder / "source.md").read_text(encoding="utf-8")
    assert "- Topic: Research" in manifest
    assert "## Files" in manifest
    assert "- files/a.md" in manifest
    assert "- files/sub/b.txt" in manifest
    assert (folder / "files" / "a.md").read_text(encoding="utf-8") == "alpha"
    assert (folder / "files" / "sub" / "b.txt").read_text(encoding="utf-8") == "bravo"
    assert not (folder / "files" / "ignore.pdf").exists()


def test_ingest_directory_member_named_source_md_does_not_clobber_manifest(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    src = tmp_path / "dump"
    src.mkdir()
    (src / "source.md").write_text("member body, not the manifest", encoding="utf-8")
    (src / "notes.md").write_text("notes body", encoding="utf-8")
    result = ingest_repo(root, str(src), topic=None, slug=None, date="2026-07-18", apply=True)
    assert result["ok"] is True
    folder = root / "knowledge/sources/2026/07/2026-07-18-dump"
    # The root source.md is the manifest, not the member content.
    manifest = (folder / "source.md").read_text(encoding="utf-8")
    assert "## Files" in manifest
    assert "- files/source.md" in manifest
    assert "member body" not in manifest
    # The member landed under files/ intact.
    assert (folder / "files" / "source.md").read_text(encoding="utf-8") == (
        "member body, not the manifest"
    )


def test_ingest_url_is_stored_verbatim_without_fetch(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    url = "https://example.com/post/deep-dive"
    result = ingest_repo(root, url, topic=None, slug="deep-dive", date="2026-07-18", apply=True)
    assert result["form"] == "url"
    assert result["origin"] == url
    text = (root / "knowledge/sources/2026/07/2026-07-18-deep-dive/source.md").read_text(
        encoding="utf-8"
    )
    assert url in text


def test_ingest_literal_text(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = ingest_repo(
        root, "A quick idea worth capturing", topic=None, slug=None, date="2026-07-18", apply=True
    )
    assert result["form"] == "literal"
    assert result["origin"] == "literal"
    text = (root / result["source_dir"] / "source.md").read_text(encoding="utf-8")
    assert "A quick idea worth capturing" in text


def test_default_date_is_today(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = ingest_repo(root, "idea", topic=None, slug="idea", date=None, apply=True)
    today = datetime.date.today()
    expected = f"knowledge/sources/{today.year:04d}/{today.month:02d}/{today.isoformat()}-idea"
    assert result["source_dir"] == expected


def test_plan_mode_writes_nothing(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    note = tmp_path / "note.md"
    note.write_text("body", encoding="utf-8")
    before = {path.relative_to(root).as_posix() for path in root.rglob("*")}
    result = ingest_repo(root, str(note), topic=None, slug=None, date="2026-07-18", apply=False)
    after = {path.relative_to(root).as_posix() for path in root.rglob("*")}
    assert result["ok"] is True
    assert result["planned"] is True
    assert result["changes"] == ["create knowledge/sources/2026/07/2026-07-18-note/source.md"]
    assert before == after
    assert not (root / "knowledge").exists()


def test_collision_refuses_and_leaves_original_intact(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    note = tmp_path / "note.md"
    note.write_text("first", encoding="utf-8")
    ingest_repo(root, str(note), topic=None, slug=None, date="2026-07-18", apply=True)
    note.write_text("second", encoding="utf-8")
    result = ingest_repo(root, str(note), topic=None, slug=None, date="2026-07-18", apply=True)
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "source-exists"
    assert result["changes"] == []
    text = (root / "knowledge/sources/2026/07/2026-07-18-note/source.md").read_text(
        encoding="utf-8"
    )
    assert "first" in text
    assert "second" not in text


def test_bad_date_is_rejected_with_value_in_message(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = ingest_repo(root, "text", topic=None, slug=None, date="18-07-2026", apply=True)
    assert result["ok"] is False
    bad = result["findings"][0]
    assert bad["code"] == "bad-date"
    # The bad value goes in the message; the path field stays empty.
    assert "18-07-2026" in bad["message"]
    assert bad["path"] == ""
    assert not (root / "knowledge").exists()


def test_out_of_range_date_is_rejected(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = ingest_repo(root, "text", topic=None, slug=None, date="2026-13-40", apply=True)
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "bad-date"


def test_empty_source_is_rejected(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = ingest_repo(root, "   ", topic=None, slug=None, date=None, apply=True)
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "empty-source"


def test_ingest_outside_repo_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    result = ingest_repo(outside, "idea", topic=None, slug="idea", date="2026-07-18", apply=True)
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "not-a-mos-repo"
    assert result["next_action"]["id"] == "run-setup"
    assert not (outside / "knowledge").exists()


def test_atomic_failure_leaves_no_dest_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    src = tmp_path / "dump"
    src.mkdir()
    (src / "a.md").write_text("alpha", encoding="utf-8")
    (src / "b.md").write_text("bravo", encoding="utf-8")

    calls = {"n": 0}
    real_write = ingest_mod._write_text

    def flaky(path: Path, content: str) -> None:
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OSError("disk full")
        real_write(path, content)

    monkeypatch.setattr(ingest_mod, "_write_text", flaky)
    result = ingest_repo(root, str(src), topic=None, slug=None, date="2026-07-18", apply=True)
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "ingest-failed"
    dest = root / "knowledge/sources/2026/07/2026-07-18-dump"
    assert not dest.exists()
    # No half-written temp folder is left behind either.
    month_dir = root / "knowledge/sources/2026/07"
    assert list(month_dir.iterdir()) == []


def test_pending_lists_uncompiled_sources(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    ingest_repo(root, "one", topic=None, slug="one", date="2026-07-18", apply=True)
    ingest_repo(root, "two", topic=None, slug="two", date="2026-07-18", apply=True)
    wiki = root / "knowledge" / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    (wiki / "_log.md").write_text("- compiled 2026-07-18-one into pages\n", encoding="utf-8")
    result = pending_sources(root)
    assert result["ok"] is True
    assert result["schema"] == "mos.ingest-pending.v1"
    assert result["command"] == "ingest-pending"
    assert result["pending"] == ["knowledge/sources/2026/07/2026-07-18-two"]
    assert result["next_action"]["id"] == "compile-source"


def test_pending_whole_token_matching_ignores_superstrings(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    ingest_repo(root, "two", topic=None, slug="two", date="2026-07-18", apply=True)
    ingest_repo(root, "two b", topic=None, slug="two-b", date="2026-07-18", apply=True)
    wiki = root / "knowledge" / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    # The log mentions only the longer folder name.
    (wiki / "_log.md").write_text("- compiled 2026-07-18-two-b\n", encoding="utf-8")
    result = pending_sources(root)
    # 2026-07-18-two must still be pending: it is not a whole token in the log.
    assert result["pending"] == ["knowledge/sources/2026/07/2026-07-18-two"]


def test_pending_matches_slash_delimited_token(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    ingest_repo(root, "one", topic=None, slug="one", date="2026-07-18", apply=True)
    wiki = root / "knowledge" / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    # A path-style reference: the folder name is a slash-delimited token.
    (wiki / "_log.md").write_text(
        "- compiled knowledge/sources/2026/07/2026-07-18-one\n", encoding="utf-8"
    )
    result = pending_sources(root)
    assert result["pending"] == []


def test_pending_ignores_nested_files_source_md(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    src = tmp_path / "dump"
    src.mkdir()
    (src / "source.md").write_text("member", encoding="utf-8")
    ingest_repo(root, str(src), topic=None, slug=None, date="2026-07-18", apply=True)
    result = pending_sources(root)
    # Only the top-level dated folder counts, not the nested files/source.md copy.
    assert result["pending"] == ["knowledge/sources/2026/07/2026-07-18-dump"]


def test_pending_empty_when_no_sources(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = pending_sources(root)
    assert result["ok"] is True
    assert result["pending"] == []
    assert result["next_action"]["id"] == "none"


def test_pending_outside_repo_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    result = pending_sources(outside)
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "not-a-mos-repo"
    assert result["next_action"]["id"] == "run-setup"
