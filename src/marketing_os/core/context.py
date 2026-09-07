"""Ask the business questions in place, and write the answers where status looks for them.

``mos status`` already knows which context a brain is missing and which file backs each
gap. What it could not do was close one. Without that, the only way to fill a brain was to
open a terminal, start an agent, and run a skill — which is exactly where a non-technical
operator is abandoned.

This module is the other half of that contract. ``show`` turns each gap into a question a
person can answer; ``set`` writes one answer into the file that backs it. Completeness is
judged by ``status.substantive_text``, the same function ``mos status`` uses, so the two
commands can never disagree about whether a field is done.

Nothing here writes outside the one file that backs the named field, and nothing here
half-writes one. ``Path.write_text`` opens for truncation and encodes afterwards, so text
that cannot be encoded empties the document it was meant to fill before it fails — a lone
surrogate, which is what half an emoji looks like, is enough to do it, and the plan the
operator approved shows a clean diff right up until the moment the file is destroyed. An
answer carrying one is refused up front, under ``--plan`` and ``--yes`` alike, and the
write itself goes through ``core.atomic.atomic_write``, which leaves the original exactly
as it was if anything fails.
"""

from __future__ import annotations

import datetime
import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marketing_os.core.atomic import atomic_write
from marketing_os.core.catalog import parse_frontmatter
from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import find_root, load_schema, slugify
from marketing_os.core.status import (
    REQUIRED_FIELDS,
    context_status,
    read_document,
    substantive_text,
)

DATE_KEY = re.compile(r"^date\s*:")
#: Unpaired surrogates: the only characters a ``str`` can hold that UTF-8 cannot encode.
SURROGATE = re.compile("[\ud800-\udfff]")
DEFAULT_OFFER_SLUG = "core-offer"
STDIN_SENTINEL = "-"


@dataclass(frozen=True)
class FieldSpec:
    """The human-facing half of one context field.

    ``question`` is what the operator is asked; ``title``/``description``/``related`` seed
    a contract block when the backing file has none, so an answer never lands as an
    off-contract document.
    """

    question: str
    hint: str
    title: str
    description: str
    related: tuple[str, ...] = ()


FIELDS: dict[str, FieldSpec] = {
    "brand": FieldSpec(
        question=(
            "What should your business be known for, and what stays true "
            "no matter where you show up?"
        ),
        hint="Name what you do, who you do it for, and the promise you will not break.",
        title="Brand",
        description=(
            "What the business should be known for and the principles that hold "
            "across every channel."
        ),
        related=("business/strategy/strategy.md", "business/brand/voice.md"),
    ),
    "voice": FieldSpec(
        question="How does your business sound when it is at its best?",
        hint="Describe the tone, the words you reach for, and the words you never use.",
        title="Voice",
        description=(
            "How the business sounds at its best, with the language to use and the habits to avoid."
        ),
        related=("business/brand/brand.md", "business/audience/primary.md"),
    ),
    "audience": FieldSpec(
        question="Who is your ideal customer, and what are they trying to change?",
        hint=(
            "Describe one real person: their situation, what they have already tried, "
            "and what finally makes them decide."
        ),
        title="Primary audience",
        description=(
            "Who the primary customer is, what they are trying to change, and how they decide."
        ),
        related=("business/brand/voice.md", "business/proof/testimonials.md"),
    ),
    "offer": FieldSpec(
        question="What do you sell, who is it for, and what does it promise?",
        hint="Name the offer, what is included, what it costs, and the result the buyer gets.",
        title="Offer",
        description="What this offer is, who it is for, what it costs, and what it promises.",
        related=("business/audience/primary.md", "business/strategy/strategy.md"),
    ),
    "strategy": FieldSpec(
        question="Where will you compete, and how will you win there?",
        hint="Name the ground you are choosing and why you beat the alternatives on it.",
        title="Strategy",
        description=(
            "Where the business plays and how it wins; the choice every other decision answers to."
        ),
        related=("business/strategy/goals.md", "business/brand/brand.md"),
    ),
    "proof": FieldSpec(
        question="What results can you point to publicly?",
        hint=(
            "For each: whose result, what changed, over what timeframe, and whether you "
            "have permission to share it."
        ),
        title="Testimonials and proof",
        description=(
            "Evidence the business can point to publicly, with permission status and how "
            "representative it is."
        ),
        related=("business/audience/primary.md", "business/strategy/strategy.md"),
    ),
}


def field_names() -> tuple[str, ...]:
    """Every settable field, required ones first, in the order an operator meets them."""
    schema_fields = list(load_schema()["context_files"]) + ["offer"]
    rest = [name for name in schema_fields if name not in REQUIRED_FIELDS]
    return (*REQUIRED_FIELDS, *rest)


def _spec(name: str) -> FieldSpec:
    """The spec for a field, generating a usable fallback for one the registry misses."""
    known = FIELDS.get(name)
    if known is not None:
        return known
    label = name.replace("-", " ").replace("_", " ")
    return FieldSpec(
        question=f"What should the brain know about {label}?",
        hint="Answer in your own words; specifics beat adjectives.",
        title=label.title(),
        description=f"The {label} context this brain works from.",
    )


# --- document surgery ---------------------------------------------------------------


def _read_raw(path: Path) -> str:
    """Read without newline translation so a CRLF file survives the round trip.

    ``Path.read_text`` only accepts ``newline=`` on 3.13+; ``open()`` works on 3.10.
    """
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _newline_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _split_document(text: str) -> tuple[list[str], list[str]]:
    """Split into (frontmatter lines including both fences, body lines).

    Lines come back without their endings so the caller can rejoin them with the file's
    own convention. An unterminated fence is treated as body, matching
    ``catalog.parse_frontmatter``, so a malformed document is never silently truncated.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return [], lines
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[: index + 1], lines[index + 1 :]
    return [], lines


def _with_today(front: list[str], today: str) -> list[str]:
    """Refresh ``date:`` in place, adding it only when the block does not carry one.

    Every other line is returned untouched, which is what keeps the diff small.
    """
    updated = list(front)
    for index, line in enumerate(updated):
        if index == 0 or line.strip() == "---":
            continue
        if DATE_KEY.match(line):
            updated[index] = f"date: {today}"
            return updated
    return [*updated[:-1], f"date: {today}", updated[-1]]


def _new_frontmatter(spec: FieldSpec, title: str, today: str) -> list[str]:
    block = [
        "---",
        f"title: {title}",
        "type: business",
        f"description: {spec.description}",
        f"date: {today}",
        "status: draft",
    ]
    if spec.related:
        block.append("related:")
        block.extend(f"  - {item}" for item in spec.related)
    block.append("---")
    return block


def _heading(body: list[str]) -> str:
    """The document's H1, when it opens with one, so a rewrite keeps the page titled."""
    for line in body:
        if not line.strip():
            continue
        return line if line.startswith("# ") else ""
    return ""


def _without_heading(body: str) -> str:
    """The body with its leading H1 removed.

    The H1 is the document's title, not the operator's answer. Stripping it on the way out
    keeps ``show`` honest, and stripping it on the way in makes ``show`` then ``set`` a true
    round trip instead of stacking a second heading on every pass.
    """
    lines = body.splitlines()
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index < len(lines) and lines[index].startswith("# "):
        index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        return "\n".join(lines[index:])
    return body


def _compose(front: list[str], heading: str, body: str, newline: str) -> str:
    parts = list(front)
    if heading:
        parts.extend([heading, ""])
    parts.extend(_without_heading(body).strip("\r\n").splitlines())
    return newline.join(parts) + newline


def render_answer(existing: str | None, spec: FieldSpec, title: str, body: str, today: str) -> str:
    """The full text of the backing file once the operator's answer replaces the body.

    Frontmatter that is already there is preserved line for line apart from ``date``;
    a document with none is given a contract block. Only the body below the block is
    replaced.
    """
    if existing is None:
        return _compose(_new_frontmatter(spec, title, today), f"# {title}", body, "\n")
    front, existing_body = _split_document(existing)
    front = _with_today(front, today) if front else _new_frontmatter(spec, title, today)
    heading = _heading(existing_body) or f"# {title}"
    return _compose(front, heading, body, _newline_of(existing))


def _unified(before: str, after: str, relative: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
            lineterm="",
        )
    )


# --- envelopes ----------------------------------------------------------------------


def _not_a_repo(start: Path, *, apply: bool | None = None) -> dict[str, Any]:
    facts: dict[str, Any] = {"fields": [], "required": [], "missing": [], "ready": False}
    if apply is not None:
        facts.update(applied=False, planned=not apply)
    return envelope(
        "context",
        start,
        ok=False,
        findings=[finding("not-a-mos-repo", "This is not a marketing-os business repository.")],
        action=next_action("run-onboard", "Create a business brain here first."),
        operation="set" if apply is not None else "show",
        **facts,
    )


def _operator_body(root: Path, entry: dict[str, Any]) -> tuple[str, str]:
    """The operator's own words for one field, and the file they came from.

    Template boilerplate reports as empty, because the same completeness test that
    ``mos status`` applies decides whether there is an answer here at all.

    A field answered away from its canonical path is read from where the answer actually is.
    Without that last fallback ``complete`` and ``body`` contradicted each other in the same
    record: the field reported answered and the answer came back empty, and the empty string
    went on to the assistant as the operator's own words — worse than reporting the field
    missing, because a model told a question is answered stops asking it.
    """
    candidates = list(entry.get("files") or []) or [entry["path"]]
    discovered = entry.get("discovered_path")
    if discovered and discovered not in candidates:
        candidates.append(discovered)
    for relative in candidates:
        path = root / relative
        if not path.is_file():
            continue
        text = read_document(path)
        if text is None or not substantive_text(text):
            continue
        _meta, body = parse_frontmatter(text)
        return _without_heading(body).strip(), relative
    return "", ""


def _offer_target(entry: dict[str, Any], slug: str | None) -> tuple[str, str]:
    """Where an offer answer lands, as ``(relative path, offer slug)``.

    An explicit slug always wins. With none, a lone existing offer is the obvious
    target; an empty ``business/offers/`` gets a first one.
    """
    if slug:
        resolved = slugify(slug)
        return f"business/offers/{resolved}/offer.md", resolved
    files = list(entry.get("files") or [])
    if len(files) == 1:
        return files[0], Path(files[0]).parent.name
    return f"business/offers/{DEFAULT_OFFER_SLUG}/offer.md", DEFAULT_OFFER_SLUG


def show_context(root: Path) -> dict[str, Any]:
    """Every context field as a question, with the operator's answer when there is one."""
    start = root.expanduser().resolve()
    found = find_root(start)
    if found is None:
        return _not_a_repo(start)

    status = context_status(found)
    required = list(status["required"])
    fields: list[dict[str, Any]] = []
    for name in field_names():
        entry = status["fields"].get(name)
        if entry is None:
            continue
        spec = _spec(name)
        body, answered_in = _operator_body(found, entry)
        # Where an answer lands, which is not always where the current one lives: a field
        # answered somewhere else is still rewritten at its canonical path.
        writes_to = _offer_target(entry, None)[0] if name == "offer" else entry["path"]
        record: dict[str, Any] = {
            "name": name,
            "question": spec.question,
            "hint": spec.hint,
            "path": entry["path"],
            "writes_to": writes_to,
            "answered_in": answered_in,
            "complete": entry["complete"],
            "source": entry.get("source", "canonical" if entry["complete"] else "missing"),
            "required": name in required,
            "body": body,
        }
        if "discovered_path" in entry:
            record["discovered_path"] = entry["discovered_path"]
        if "files" in entry:
            record["files"] = list(entry["files"])
        fields.append(record)

    missing = list(status["missing"])
    if missing:
        first = missing[0]
        action = next_action(f"complete-{first}", _spec(first).question)
    else:
        action = next_action(
            "run-start", "Every required context field is answered; the brain is ready to work."
        )
    return envelope(
        "context",
        found,
        ok=True,
        action=action,
        operation="show",
        fields=fields,
        required=required,
        missing=missing,
        ready=status["ready"],
    )


def _refusal(
    root: Path, code: str, message: str, action: dict[str, str], *, apply: bool
) -> dict[str, Any]:
    return envelope(
        "context",
        root,
        ok=False,
        findings=[finding(code, message)],
        action=action,
        operation="set",
        applied=False,
        planned=not apply,
        fields=[],
    )


def set_context(
    root: Path,
    field: str,
    text: str,
    *,
    slug: str | None = None,
    apply: bool,
) -> dict[str, Any]:
    """Write one operator answer into the file that backs one context field."""
    start = root.expanduser().resolve()
    found = find_root(start)
    if found is None:
        return _not_a_repo(start, apply=apply)

    names = field_names()
    if field not in names:
        return _refusal(
            found,
            "unknown-field",
            f"{field!r} is not a context field. Valid fields: {', '.join(names)}.",
            next_action("choose-field", f"Re-run with --field set to one of: {', '.join(names)}."),
            apply=apply,
        )
    if not text.strip():
        return _refusal(
            found,
            "empty-answer",
            "An answer is required; pass --text with the operator's own words.",
            next_action("provide-answer", _spec(field).question),
            apply=apply,
        )
    if SURROGATE.search(text):
        # Refused rather than repaired: half a character carries no meaning, and silently
        # dropping it would write something the operator did not review. This is a refusal
        # under --plan too, so the plan and the apply agree instead of the plan promising
        # a write that the apply cannot make.
        return _refusal(
            found,
            "unwritable-answer",
            "This answer contains characters that cannot be written to a UTF-8 file — "
            "usually an emoji or a symbol that arrived cut in half. Remove them and "
            "send the answer again.",
            next_action("resend-answer", "Send the answer again without the broken characters."),
            apply=apply,
        )

    status = context_status(found)
    entry = status["fields"][field]
    findings: list[dict[str, str]] = []
    spec = _spec(field)
    title = spec.title

    if field == "offer":
        files = list(entry.get("files") or [])
        if slug is None and len(files) > 1:
            return _refusal(
                found,
                "ambiguous-offer",
                "This brain has more than one offer; name which with --slug. Existing: "
                + ", ".join(files)
                + ".",
                next_action("choose-offer", "Re-run with --slug <offer-slug>."),
                apply=apply,
            )
        relative, offer_slug = _offer_target(entry, slug)
        title = offer_slug.replace("-", " ").title()
    else:
        if slug:
            findings.append(
                finding(
                    "slug-ignored",
                    f"--slug only selects an offer; ignored for the {field} field.",
                    severity="warning",
                )
            )
        relative = entry["path"]

    target = found / relative
    existed = target.is_file()
    before = _read_raw(target) if existed else ""
    after = render_answer(
        before if existed else None, spec, title, text, datetime.date.today().isoformat()
    )

    if not substantive_text(after):
        findings.append(
            finding(
                "answer-too-short",
                "This answer is too short to count as complete; add a couple more specific "
                "sentences and mos status will still report this field as missing.",
                severity="warning",
                path=relative,
            )
        )

    changes = [f"{'update' if existed else 'create'} {relative}"]
    diff = _unified(before, after, relative)

    if apply:
        # Bytes, not text: atomic_write never translates a newline, which is what the
        # newline="" on the old text write was for.
        atomic_write(target, after)

    remaining = context_status(found)["missing"] if apply else status["missing"]
    if not apply:
        action = next_action("apply-context-set", "Apply the reviewed change to write it.")
    elif remaining:
        action = next_action(f"complete-{remaining[0]}", _spec(remaining[0]).question)
    else:
        action = next_action(
            "run-start", "Every required context field is answered; the brain is ready to work."
        )

    return envelope(
        "context",
        found,
        ok=True,
        changes=changes,
        findings=findings,
        action=action,
        operation="set",
        applied=apply,
        planned=not apply,
        field=field,
        path=relative,
        created=not existed,
        diff=diff,
        field_complete=substantive_text(after),
        missing=remaining,
    )
