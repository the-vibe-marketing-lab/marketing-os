from pathlib import Path

from marketing_os.core.catalog import (
    build_catalog,
    build_repo,
    coverage,
    first_sentence,
    load_catalog,
    parse_frontmatter,
)
from marketing_os.core.schema import config_text


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _brain(root: Path) -> None:
    _write(root / ".mos" / "config.yaml", config_text("Example Business"))
    _write(
        root / "business" / "strategy" / "pricing.md",
        "---\ntitle: Pricing\ntype: business\ndescription: How the business prices.\n"
        "date: 2026-08-20\nstatus: active\nrelated:\n  - business/strategy/goals.md\n---\n\n"
        "# Pricing\n\nBody text.\n",
    )
    _write(root / "archive" / "old.md", "---\ntitle: Old\n---\n\nRetired.\n")
    _write(root / ".claude" / "skills" / "mos-help" / "SKILL.md", "# generated\n")


def test_parse_frontmatter_reads_scalars_and_sequences() -> None:
    meta, body = parse_frontmatter(
        "---\ntitle: A Doc\nstatus: 'active'\nrelated:\n  - one.md\n  - two.md\n"
        "tags: [alpha, beta]\n---\n\nBody.\n"
    )
    assert meta["title"] == "A Doc"
    assert meta["status"] == "active"
    assert meta["related"] == ["one.md", "two.md"]
    assert meta["tags"] == ["alpha", "beta"]
    assert body.strip() == "Body."


def test_parse_frontmatter_without_a_block_returns_the_text() -> None:
    meta, body = parse_frontmatter("# Title\n\nNo frontmatter.\n")
    assert meta == {}
    assert body.startswith("# Title")


def test_parse_frontmatter_ignores_an_unterminated_block() -> None:
    meta, body = parse_frontmatter("---\ntitle: Broken\n\nstill going\n")
    assert meta == {}
    assert body.startswith("---")


def test_first_sentence_skips_headings_and_short_lines() -> None:
    body = "# Heading\n\n- bullet\n\nHi\n\nThis paragraph is long enough to be a summary.\n"
    assert first_sentence(body) == "This paragraph is long enough to be a summary."


def test_first_sentence_truncates_on_a_word_boundary() -> None:
    body = "word " * 60
    summary = first_sentence(body, limit=40)
    assert summary.endswith("...")
    assert len(summary) <= 44


def test_first_sentence_returns_empty_when_nothing_qualifies() -> None:
    assert first_sentence("# Only\n\n- a\n- b\n") == ""


def test_build_catalog_skips_runtime_and_archive(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    _brain(root)
    docs = build_catalog(root)
    assert "business/strategy/pricing.md" in docs
    assert "archive/old.md" not in docs
    assert not any(path.startswith(".claude/") for path in docs)


def test_catalog_records_the_contract_fields(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    _brain(root)
    doc = build_catalog(root)["business/strategy/pricing.md"]
    assert doc["title"] == "Pricing"
    assert doc["type"] == "business"
    assert doc["description"] == "How the business prices."
    assert doc["connective_keys"] == ["related"]
    assert doc["missing_keys"] == []
    assert doc["links_out"] == ["business/strategy/goals.md"]
    assert doc["has_frontmatter"] is True


def test_catalog_falls_back_to_the_first_sentence(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    _write(root / "business" / "notes.md", "# Notes\n\nA description derived from the body.\n")
    doc = build_catalog(root)["business/notes.md"]
    assert doc["description"] == "A description derived from the body."
    assert doc["has_frontmatter"] is False
    assert doc["missing_keys"] == ["title", "type", "description", "date", "status"]


def test_build_repo_writes_machine_local_state(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    _brain(root)
    result = build_repo(root)
    assert result["schema"] == "mos.index-build.v1"
    assert result["ok"] is True
    assert result["catalog"] == ".mos/local/catalog.json"
    assert (root / ".mos" / "local" / "catalog.json").is_file()
    assert load_catalog(root) == build_catalog(root)


def test_load_catalog_is_none_when_absent_or_corrupt(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    _brain(root)
    assert load_catalog(root) is None
    _write(root / ".mos" / "local" / "catalog.json", "{not json")
    assert load_catalog(root) is None


def test_coverage_excludes_generated_navigation_files() -> None:
    docs = {
        "a.md": {
            "has_frontmatter": True,
            "description": "x",
            "links_out": ["b"],
            "has_related_block": False,
        },
        "_index.md": {
            "has_frontmatter": True,
            "description": "x",
            "links_out": [],
            "has_related_block": False,
        },
    }
    assert coverage(docs)["documents"] == 1
