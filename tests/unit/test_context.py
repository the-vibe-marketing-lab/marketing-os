import re
from pathlib import Path

import pytest

from marketing_os.core import atomic as atomic_module
from marketing_os.core.context import set_context, show_context
from marketing_os.core.setup import setup_repo
from marketing_os.core.status import status_repo
from marketing_os.core.validation import validate_repo

BRAND = (
    "We are the boxing gym for people who were never picked for the team. Beginners "
    "first, no egos, no shouting."
)
AUDIENCE = (
    "Adults aged 25 to 45 who have wanted to try boxing for years and never walked in. "
    "They decide when a friend offers to come along."
)
OFFER = (
    "The Beginner Six Week Course. Two classes a week, gloves included, ninety-nine "
    "dollars, for people who have never thrown a punch."
)


def _brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    setup_repo(root, "Southside Boxing", "all", mode="in-house", apply=True)
    return root


def _field(result: dict, name: str) -> dict:
    return next(item for item in result["fields"] if item["name"] == name)


def _read_raw(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _write_raw(path: Path, text: str) -> None:
    """Write without newline translation, so a test's line endings mean what they say."""
    path.write_text(text, encoding="utf-8", newline="")


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


# --- show ---------------------------------------------------------------------------


def test_show_asks_every_context_field_on_a_fresh_brain(tmp_path: Path) -> None:
    result = show_context(_brain(tmp_path))
    assert result["schema"] == "mos.context.v1"
    assert result["operation"] == "show"
    assert result["ok"] is True
    assert result["ready"] is False
    names = [item["name"] for item in result["fields"]]
    assert names[:4] == ["brand", "voice", "audience", "offer"]
    assert set(names) == {
        "brand",
        "voice",
        "audience",
        "offer",
        "strategy",
        "proof",
        "competitors",
        "inspiration",
    }
    for item in result["fields"]:
        assert item["question"].endswith("?")
        assert item["path"]
        assert item["complete"] is False
        assert item["body"] == ""
    assert result["missing"] == ["brand", "voice", "audience", "offer"]


def test_show_reports_scaffolded_boilerplate_as_no_answer(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    brand = root / "business" / "brand" / "brand.md"
    assert "TODO:" in brand.read_text(encoding="utf-8")
    assert _field(show_context(root), "brand")["body"] == ""


def test_show_agrees_with_status_about_what_is_missing(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    set_context(root, "brand", BRAND, apply=True)
    assert show_context(root)["missing"] == status_repo(root)["context"]["missing"]


def test_show_returns_the_operator_body_without_the_heading(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    set_context(root, "brand", BRAND, apply=True)
    entry = _field(show_context(root), "brand")
    assert entry["complete"] is True
    assert entry["body"] == BRAND
    assert not entry["body"].startswith("#")


def test_show_refuses_a_path_that_is_not_a_brain(tmp_path: Path) -> None:
    result = show_context(tmp_path / "nowhere")
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "not-a-mos-repo"
    assert result["fields"] == []


# --- set: the gate ------------------------------------------------------------------


def test_set_plan_previews_a_diff_and_writes_nothing(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    before = _snapshot(root)
    result = set_context(root, "brand", BRAND, apply=False)
    assert result["ok"] is True
    assert result["planned"] is True
    assert result["applied"] is False
    assert result["changes"] == ["update business/brand/brand.md"]
    assert "--- a/business/brand/brand.md" in result["diff"]
    assert f"+{BRAND}" in result["diff"]
    assert _snapshot(root) == before


def test_set_writes_the_answer_and_status_agrees(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    missing_before = status_repo(root)["context"]["missing"]
    result = set_context(root, "brand", BRAND, apply=True)
    missing_after = status_repo(root)["context"]["missing"]
    assert result["applied"] is True
    assert result["field_complete"] is True
    assert BRAND in (root / "business" / "brand" / "brand.md").read_text(encoding="utf-8")
    assert len(missing_after) == len(missing_before) - 1
    assert set(missing_before) - set(missing_after) == {"brand"}
    assert result["missing"] == missing_after
    assert _field(show_context(root), "brand")["complete"] is True


def test_set_touches_only_the_backing_file(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    before = _snapshot(root)
    set_context(root, "audience", AUDIENCE, apply=True)
    after = _snapshot(root)
    changed = {name for name in after if after[name] != before.get(name)}
    assert changed == {"business/audience/primary.md"}
    assert set(after) == set(before)


# --- set: the document ---------------------------------------------------------------


def test_set_preserves_existing_frontmatter_and_refreshes_the_date(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    target = root / "business" / "audience" / "primary.md"
    seeded = re.sub(r"date: \d{4}-\d{2}-\d{2}", "date: 2019-04-01", _read_raw(target)).replace(
        "status: draft", "status: draft\ntags: [gyms]"
    )
    _write_raw(target, seeded)

    set_context(root, "audience", AUDIENCE, apply=True)
    written = _read_raw(target)
    assert "tags: [gyms]" in written
    assert "date: 2019-04-01" not in written
    assert "title: Primary audience" in written
    assert "  - business/brand/voice.md" in written
    assert written.count("---") >= 2
    assert AUDIENCE in written


def test_set_creates_a_contract_block_when_the_file_has_none(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    result = set_context(root, "offer", OFFER, slug="beginner-six-week", apply=True)
    target = root / "business" / "offers" / "beginner-six-week" / "offer.md"
    assert result["created"] is True
    assert result["changes"] == ["create business/offers/beginner-six-week/offer.md"]
    text = target.read_text(encoding="utf-8")
    for key in ("title:", "type: business", "description:", "date:", "status:", "related:"):
        assert key in text
    assert validate_repo(root, strict=True)["summary"]["contract_gaps"] == 0


def test_set_preserves_crlf_and_leaves_untouched_lines_byte_identical(tmp_path: Path) -> None:
    """A CRLF file must come back CRLF. Rewriting every line to LF would turn a one-line
    answer into a whole-file diff, which is how line-ending churn hides real changes."""
    root = _brain(tmp_path)
    target = root / "business" / "audience" / "primary.md"
    crlf = _read_raw(target).replace("\r\n", "\n").replace("\n", "\r\n")
    target.write_bytes(crlf.encode("utf-8"))
    before = target.read_bytes()
    assert before.count(b"\n") == before.count(b"\r\n")

    set_context(root, "audience", AUDIENCE, apply=True)
    after = target.read_bytes()

    assert after.count(b"\n") == after.count(b"\r\n"), "no line may have been rewritten to LF"
    before_front = before.split(b"\r\n---\r\n")[0].split(b"\r\n")
    after_front = after.split(b"\r\n---\r\n")[0].split(b"\r\n")
    unchanged_before = [line for line in before_front if not line.startswith(b"date:")]
    unchanged_after = [line for line in after_front if not line.startswith(b"date:")]
    assert unchanged_after == unchanged_before


def test_show_then_set_is_a_stable_round_trip(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    set_context(root, "brand", BRAND, apply=True)
    target = root / "business" / "brand" / "brand.md"
    first = target.read_bytes()
    set_context(root, "brand", _field(show_context(root), "brand")["body"], apply=True)
    assert target.read_bytes() == first
    assert target.read_text(encoding="utf-8").count("# Brand") == 1


# --- set: refusals -------------------------------------------------------------------


def test_set_refuses_an_unknown_field_and_names_the_valid_ones(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    before = _snapshot(root)
    result = set_context(root, "vibe", BRAND, apply=True)
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "unknown-field"
    for name in (
        "brand",
        "voice",
        "audience",
        "offer",
        "strategy",
        "proof",
        "competitors",
        "inspiration",
    ):
        assert name in result["findings"][0]["message"]
    assert result["next_action"]["id"] == "choose-field"
    assert _snapshot(root) == before


def test_set_refuses_an_empty_answer(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    before = _snapshot(root)
    result = set_context(root, "brand", "   \n  ", apply=True)
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "empty-answer"
    assert _snapshot(root) == before


def test_set_refuses_a_path_that_is_not_a_brain(tmp_path: Path) -> None:
    target = tmp_path / "nowhere"
    result = set_context(target, "brand", BRAND, apply=True)
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "not-a-mos-repo"
    assert result["next_action"]["id"] == "run-onboard"
    assert not target.exists()


def test_set_warns_when_an_answer_is_too_short_to_count(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    result = set_context(root, "voice", "Direct.", apply=True)
    assert result["ok"] is True
    assert result["field_complete"] is False
    assert [item["code"] for item in result["findings"]] == ["answer-too-short"]
    assert "voice" in status_repo(root)["context"]["missing"]


def test_set_refuses_an_ambiguous_offer_without_a_slug(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    set_context(root, "offer", OFFER, slug="beginner-six-week", apply=True)
    set_context(root, "offer", OFFER, slug="private-coaching", apply=True)
    result = set_context(root, "offer", OFFER, apply=True)
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "ambiguous-offer"
    assert "beginner-six-week" in result["findings"][0]["message"]
    assert result["next_action"]["id"] == "choose-offer"


def test_set_targets_the_only_existing_offer_without_a_slug(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    set_context(root, "offer", OFFER, slug="beginner-six-week", apply=True)
    result = set_context(root, "offer", OFFER + " Now with a free gumshield.", apply=True)
    assert result["path"] == "business/offers/beginner-six-week/offer.md"
    assert result["created"] is False


def test_set_warns_that_slug_is_ignored_off_the_offer_field(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    result = set_context(root, "brand", BRAND, slug="something", apply=False)
    assert result["ok"] is True
    assert [item["code"] for item in result["findings"]] == ["slug-ignored"]


# --- a write either happens or does not ---------------------------------------------


def _brand_file(root: Path) -> Path:
    return root / "business" / "brand" / "brand.md"


def test_an_unwritable_answer_is_refused_before_the_file_is_touched(tmp_path: Path) -> None:
    """A lone surrogate is what half an emoji looks like, and it used to empty the file.

    ``Path.write_text`` truncates the file and encodes afterwards, so the failure landed
    after the document was already gone: 386 bytes to 0, frontmatter and all.
    """
    root = _brain(tmp_path)
    set_context(root, "brand", BRAND, apply=True)
    target = _brand_file(root)
    before = target.read_bytes()
    assert before

    result = set_context(root, "brand", BRAND + " We opened in \ud83d", apply=True)

    assert result["ok"] is False
    assert result["findings"][0]["code"] == "unwritable-answer"
    assert result["applied"] is False
    assert target.read_bytes() == before


def test_the_plan_refuses_the_same_answer_the_apply_cannot_write(tmp_path: Path) -> None:
    """The plan used to show a clean diff for a write that could only destroy the file."""
    root = _brain(tmp_path)
    planned = set_context(root, "brand", BRAND + " \ud83d", apply=False)
    assert planned["ok"] is False
    assert planned["findings"][0]["code"] == "unwritable-answer"
    assert planned["planned"] is True
    assert not planned.get("diff")


def test_a_failed_write_leaves_the_previous_answer_exactly_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The last step is a rename over the target, so nothing observes a half-written file."""
    root = _brain(tmp_path)
    set_context(root, "brand", BRAND, apply=True)
    target = _brand_file(root)
    before = target.read_bytes()

    def explode(source: object, destination: object) -> None:
        raise OSError("the disk went away mid-write")

    monkeypatch.setattr(atomic_module.os, "replace", explode)
    with pytest.raises(OSError):
        set_context(root, "brand", BRAND + " We also run Saturday sparring.", apply=True)

    assert target.read_bytes() == before
    assert list(target.parent.glob(".brand.md.*")) == []  # and no scratch file left behind


def test_a_successful_write_leaves_no_scratch_file_beside_the_target(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    result = set_context(root, "brand", BRAND, apply=True)
    assert result["applied"] is True
    target = _brand_file(root)
    assert BRAND in target.read_text(encoding="utf-8")
    assert [path.name for path in target.parent.glob(".*")] == []


def test_an_answer_found_elsewhere_is_shown_and_grounded_with_its_own_words(
    tmp_path: Path,
) -> None:
    """``complete`` and ``body`` are two halves of one record and must not contradict.

    ``show`` read the body from the canonical path alone, so a field answered somewhere else
    came back marked answered with nothing in it — and that empty string went on to the
    assistant as the operator's own words. Being told a question is answered and handed
    nothing is strictly worse than being told it is missing, because a model that believes it
    is answered stops asking.
    """
    from marketing_os.core.assist import grounding

    root = _brain(tmp_path)
    core = root / "reference/core"
    core.mkdir(parents=True, exist_ok=True)
    (core / "voice.md").write_text(
        "# Voice\n\nPlain, direct and never salesy. We write the way a coach talks to a "
        "beginner on their first night in the gym.\n",
        encoding="utf-8",
    )

    voice = _field(show_context(root), "voice")

    assert voice["complete"] is True
    assert voice["source"] == "discovered"
    assert voice["discovered_path"] == "reference/core/voice.md"
    assert "never salesy" in voice["body"]
    # The canonical path keeps its meaning: it is still where the next answer is written.
    assert voice["path"] == "business/brand/voice.md"
    assert voice["writes_to"] == "business/brand/voice.md"
    assert voice["answered_in"] == "reference/core/voice.md"

    answered = {item["name"]: item["text"] for item in grounding(root)["answered"]}
    assert "never salesy" in answered["voice"]


def test_show_survives_a_canonical_file_that_is_not_utf8(tmp_path: Path) -> None:
    """``status`` already tolerated this file; ``show`` raising on it made them disagree."""
    root = _brain(tmp_path)
    (root / "business/brand/brand.md").write_bytes(
        b"---\ntitle: Brand\n---\n\xff\xfe not valid utf-8 at all\n"
    )

    result = show_context(root)

    assert result["ok"] is True
    assert _field(result, "brand")["complete"] is False
    assert _field(result, "brand")["body"] == ""
