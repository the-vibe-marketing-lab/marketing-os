from pathlib import Path

import pytest

from marketing_os.core import atomic as atomic_module
from marketing_os.core.catalog import build_catalog
from marketing_os.core.related import (
    CROSS_FOLDER_BOOST,
    RELATED_MIN_WORDS,
    apply_related,
    build_tfidf,
    is_link_target,
    plan_related,
    related_for,
    related_repo,
    unlinked,
)
from marketing_os.core.schema import config_text

TODAY = "2026-08-20"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _doc(root: Path, relative: str, title: str, kind: str, description: str, words: int) -> None:
    body = "prose " * words
    _write(
        root / relative,
        f"---\ntitle: {title}\ntype: {kind}\ndescription: {description}\n"
        f"date: {TODAY}\nstatus: active\nproduced_by: test\n---\n\n# {title}\n\n{body}\n",
    )


SUBJECTS = (
    "onboarding",
    "retention",
    "positioning",
    "webinars",
    "referrals",
    "attribution",
    "churn",
    "podcasts",
    "partnerships",
    "newsletters",
    "events",
    "lifecycle",
    "advocacy",
    "packaging",
    "syndication",
    "localisation",
    "accessibility",
    "analytics",
)


def _brain(root: Path) -> None:
    """A corpus large enough for term weighting to mean something.

    Below roughly two dozen documents every score sits under the confidence floor, which
    is correct behaviour rather than a bug: weak links are worse than none.
    """
    _write(root / ".mos" / "config.yaml", config_text("Example Business"))
    for index, subject in enumerate(SUBJECTS):
        folder = "business/operations" if index % 2 else "knowledge/wiki"
        _doc(
            root,
            f"{folder}/{subject}.md",
            subject.title(),
            "business" if index % 2 else "knowledge",
            f"Everything the team knows about {subject} and how it is run.",
            200,
        )
    _doc(
        root,
        "business/strategy/pricing.md",
        "Pricing strategy",
        "business",
        "Pricing strategy and pricing tiers for the subscription pricing model.",
        200,
    )
    _doc(
        root,
        "knowledge/wiki/pricing-research.md",
        "Pricing research",
        "knowledge",
        "Research into pricing tiers and subscription pricing across the market.",
        200,
    )
    _doc(
        root,
        "business/brand/voice.md",
        "Voice",
        "business",
        "How the brand sounds, its rhythm and its vocabulary.",
        200,
    )
    _doc(
        root,
        "archive/old-pricing.md",
        "Old pricing",
        "business",
        "Retired pricing tiers and subscription pricing notes.",
        200,
    )


def test_unlinked_finds_substantial_dead_ends(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    _brain(root)
    _doc(root, "knowledge/wiki/stub.md", "Stub", "knowledge", "A very short stub.", 5)
    docs = build_catalog(root)
    dead = unlinked(docs)
    assert "business/strategy/pricing.md" in dead
    assert "knowledge/wiki/stub.md" not in dead
    assert "archive/old-pricing.md" not in dead


def test_short_documents_are_left_alone(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    _write(root / ".mos" / "config.yaml", config_text("Example Business"))
    _doc(
        root,
        "business/a.md",
        "Alpha",
        "business",
        "Pricing tiers overview.",
        RELATED_MIN_WORDS - 30,
    )
    _doc(root, "business/b.md", "Beta", "business", "Pricing tiers detail.", RELATED_MIN_WORDS - 30)
    assert unlinked(build_catalog(root)) == []


def test_archived_and_source_material_is_never_a_link_target() -> None:
    assert is_link_target("knowledge/wiki/page.md", {"status": "active"}) is True
    assert is_link_target("knowledge/sources/2026/08/raw.md", {"status": "active"}) is False
    assert is_link_target("business/_archive/old.md", {"status": "active"}) is False
    assert is_link_target("business/page.md", {"status": "superseded"}) is False
    assert is_link_target("business/_index.md", {"status": "active"}) is False


def test_cross_folder_targets_are_weighted_higher(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    _brain(root)
    docs = build_catalog(root)
    frequencies, idf = build_tfidf(docs)
    links = related_for("business/strategy/pricing.md", docs, frequencies, idf)
    assert links[0] == "knowledge/wiki/pricing-research.md"
    assert "archive/old-pricing.md" not in links
    assert CROSS_FOLDER_BOOST > 1


def test_related_writes_a_block_and_preserves_line_endings(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    _brain(root)
    target = root / "business" / "strategy" / "pricing.md"
    target.write_bytes(target.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
    result = related_repo(root, apply=True)
    assert "business/strategy/pricing.md" in result["applied"]
    raw = target.read_bytes()
    assert b"\r\n## Related\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")  # nothing was normalised to LF


def test_related_plan_does_not_write(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    _brain(root)
    before = (root / "business" / "strategy" / "pricing.md").read_text(encoding="utf-8")
    result = related_repo(root, apply=False)
    assert result["planned"] is True
    assert result["applied"] == []
    assert result["changes"]
    assert (root / "business" / "strategy" / "pricing.md").read_text(encoding="utf-8") == before


def test_related_is_not_applied_twice(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    _brain(root)
    first = related_repo(root, apply=True)
    assert "business/strategy/pricing.md" in first["applied"]
    again = related_repo(root, apply=True)
    assert again["applied"] == []
    text = (root / "business" / "strategy" / "pricing.md").read_text(encoding="utf-8")
    assert text.count("## Related") == 1


def test_limit_caps_the_documents_touched(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    _brain(root)
    assert len(plan_related(build_catalog(root), limit=1)) <= 1
    assert len(plan_related(build_catalog(root))) > 1


def test_weak_matches_emit_nothing(tmp_path: Path) -> None:
    """A small corpus should write nothing rather than invent noise."""
    root = tmp_path / "brain"
    _write(root / ".mos" / "config.yaml", config_text("Example Business"))
    _doc(root, "business/one.md", "Alpha", "business", "Completely unrelated subject matter.", 200)
    _doc(root, "business/two.md", "Beta", "business", "An entirely different discipline.", 200)
    result = related_repo(root, apply=True)
    assert result["applied"] == []
    assert result["dead_ends"] == 2
    assert any(item["code"] == "no-confident-links" for item in result["findings"])


# --- a Related block either lands whole or not at all ---------------------------------


def _first_planned_write(tmp_path: Path) -> tuple[Path, Path, list[dict], dict[str, dict]]:
    """A brain, its link plan, and the document the first planned write would rewrite."""
    root = tmp_path / "brain"
    _brain(root)
    docs = build_catalog(root)
    plan = plan_related(docs)
    assert plan
    return root, root / plan[0]["relative"], plan, docs


def test_a_failed_related_write_leaves_the_document_exactly_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Four lines are appended, but the whole document is rewritten to append them.

    A truncating write that failed here cost the operator the document, not the four lines.
    """
    root, target, plan, docs = _first_planned_write(tmp_path)
    before = target.read_bytes()
    assert before

    def explode(source: object, destination: object) -> None:
        raise OSError("the disk went away mid-write")

    monkeypatch.setattr(atomic_module.os, "replace", explode)
    with pytest.raises(OSError):
        apply_related(root, plan, docs)

    assert target.read_bytes() == before
    assert list(target.parent.glob(f".{target.name}.*")) == []  # and no scratch file left


def test_a_block_that_cannot_be_encoded_never_empties_the_document(tmp_path: Path) -> None:
    """The block quotes each target's description, and a description can be unwritable.

    A lone surrogate — half an emoji, or a filename holding bytes that are not valid UTF-8
    — is the one thing a ``str`` can hold that UTF-8 cannot encode. Encoding happens before
    the file is touched, so the document survives the failure.
    """
    root, target, plan, docs = _first_planned_write(tmp_path)
    before = target.read_bytes()
    docs[plan[0]["links"][0]]["description"] = "Pricing \udcff research"

    with pytest.raises(UnicodeEncodeError):
        apply_related(root, plan, docs)

    assert target.read_bytes() == before
    assert list(target.parent.glob(f".{target.name}.*")) == []
