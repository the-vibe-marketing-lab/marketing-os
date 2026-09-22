"""Propose cross-document links from term overlap.

Ported unchanged in behaviour from the navigation layer that took a 1,177-document corpus
from 2% of documents carrying an outgoing link to 64%. Term frequency runs over
``title + description`` only: that keeps it fast, and it stops a long document from
dominating simply by being long. Cross-folder targets are weighted higher because those
are the edges nothing else in the repository supplies.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from marketing_os.core.atomic import atomic_write
from marketing_os.core.catalog import build_catalog, excluded_roots
from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import is_exempt_name

TERM = re.compile(r"[a-z][a-z0-9-]{2,}")

RELATED_MIN_WORDS = 120
RELATED_MIN_SCORE = 6.0
CROSS_FOLDER_BOOST = 1.4
RELATED_LINKS = 4
DEAD_STATUSES = frozenset({"archived", "superseded"})
NO_LINK_MARKERS = ("/_archive/", "/_archived/", "/_superseded/")
NO_LINK_PREFIXES = ("knowledge/sources/",)

_STOPWORDS = """
the a an and or but if then than that this these those of to in on for with from by at as is
are was were be been being it its you your we our they their he she his her not no do does
did done can will would should could may might must have has had how what when where which
who why all any some more most other into over under about after before new use used using
make made get got one two three vs via per etc
"""
STOPWORDS = frozenset(_STOPWORDS.split())


def _blocked_prefixes() -> tuple[str, ...]:
    return NO_LINK_PREFIXES + tuple(f"{name}/" for name in excluded_roots())


def is_link_target(relative: str, doc: dict[str, Any]) -> bool:
    """Whether a document may be linked *to*.

    Live work must never point at dead work; that adds edges and destroys navigation.
    """
    if is_exempt_name(Path(relative).name):
        return False
    if relative.startswith(_blocked_prefixes()):
        return False
    if any(marker in "/" + relative for marker in NO_LINK_MARKERS):
        return False
    return str(doc.get("status", "")).lower() not in DEAD_STATUSES


def terms_of(doc: dict[str, Any]) -> list[str]:
    text = f"{doc.get('title', '')} {doc.get('description', '')}".lower()
    return [term for term in TERM.findall(text) if term not in STOPWORDS]


def build_tfidf(docs: dict[str, dict[str, Any]]) -> tuple[dict[str, Counter], dict[str, float]]:
    frequencies: dict[str, Counter] = {}
    document_count: Counter = Counter()
    for relative, doc in docs.items():
        counts = Counter(terms_of(doc))
        frequencies[relative] = counts
        for term in counts:
            document_count[term] += 1
    total = max(len(docs), 1)
    idf = {term: math.log(1 + total / (1 + count)) for term, count in document_count.items()}
    return frequencies, idf


def related_for(
    relative: str,
    docs: dict[str, dict[str, Any]],
    frequencies: dict[str, Counter],
    idf: dict[str, float],
    *,
    limit: int = RELATED_LINKS,
) -> list[str]:
    mine = frequencies.get(relative)
    if not mine:
        return []
    ranked = sorted(mine.items(), key=lambda pair: -pair[1] * idf.get(pair[0], 0.0))
    my_top = {term for term, _ in ranked[:12]}
    my_folder = relative.split("/")[0]
    scores: list[tuple[float, str]] = []
    for other, counts in frequencies.items():
        if other == relative or not is_link_target(other, docs[other]):
            continue
        shared = my_top & set(counts)
        if not shared:
            continue
        score = sum(idf.get(term, 0.0) * min(counts[term], 3) for term in shared)
        if other.split("/")[0] != my_folder:
            score *= CROSS_FOLDER_BOOST
        scores.append((score, other))
    scores.sort(key=lambda pair: (-pair[0], pair[1]))
    return [other for score, other in scores[:limit] if score >= RELATED_MIN_SCORE]


def unlinked(docs: dict[str, dict[str, Any]]) -> list[str]:
    """Substantial documents that point at nothing. These are the graph's dead ends."""
    blocked = _blocked_prefixes()
    return sorted(
        relative
        for relative, doc in docs.items()
        if not is_exempt_name(Path(relative).name)
        and not relative.startswith(blocked)
        and not any(marker in "/" + relative for marker in NO_LINK_MARKERS)
        and not doc["links_out"]
        and not doc["has_related_block"]
        and doc["words"] >= RELATED_MIN_WORDS
    )


def plan_related(docs: dict[str, dict[str, Any]], *, limit: int | None = None) -> list[dict]:
    frequencies, idf = build_tfidf(docs)
    targets = unlinked(docs)
    if limit:
        targets = targets[:limit]
    plan: list[dict] = []
    for relative in targets:
        links = related_for(relative, docs, frequencies, idf)
        if links:
            plan.append({"relative": relative, "links": links})
    return plan


def _block(links: list[str], docs: dict[str, dict[str, Any]], newline: str) -> str:
    lines = ["", "## Related", ""]
    for link in links:
        description = str(docs[link].get("description", "")).strip().replace("\n", " ")[:100]
        target = link[:-3] if link.endswith(".md") else link
        lines.append(f"- [[{target}]] — {description}" if description else f"- [[{target}]]")
    return newline.join(lines) + newline


def apply_related(root: Path, plan: list[dict], docs: dict[str, dict[str, Any]]) -> list[str]:
    written: list[str] = []
    for item in plan:
        target = root / item["relative"]
        if not target.is_file():
            continue
        # newline="" keeps existing line endings intact. Universal-newline reads turn a
        # CRLF file into LF on write, which makes the diff the whole file instead of the
        # four lines actually added. atomic_write writes bytes, so it translates nothing
        # either.
        with open(target, encoding="utf-8", errors="replace", newline="") as handle:
            text = handle.read()
        newline = "\r\n" if "\r\n" in text else "\n"
        body = text.rstrip("\r\n") + newline + _block(item["links"], docs, newline)
        # Four lines are appended, but the whole document is rewritten to do it. A
        # truncating write that fails here costs the operator the document, not the four
        # lines, so the replacement happens in one step or not at all.
        atomic_write(target, body)
        written.append(item["relative"])
    return written


def related_repo(root: Path, *, apply: bool, limit: int | None = None) -> dict[str, Any]:
    """``mos related`` — propose or write ``## Related`` blocks for dead-end documents."""
    root = root.expanduser().resolve()
    docs = build_catalog(root)
    plan = plan_related(docs, limit=limit)
    applied = apply_related(root, plan, docs) if apply else []
    changes = [
        f"append ## Related to {item['relative']} ({len(item['links'])} links)" for item in plan
    ]
    dead_ends = len(unlinked(docs))
    findings: list[dict[str, str]] = []
    if dead_ends and not plan:
        findings.append(
            finding(
                "no-confident-links",
                f"{dead_ends} document(s) have no outgoing links, but no candidate scored "
                "above the confidence floor. Add descriptions before retrying.",
                severity="warning",
            )
        )
    if plan and not apply:
        action = next_action("apply-related", "Apply the reviewed link plan with `--yes`.")
    else:
        action = next_action("rebuild-catalog", "Re-run `mos index build .` to refresh coverage.")
    return envelope(
        "related",
        root,
        ok=True,
        changes=changes,
        findings=findings,
        action=action,
        applied=applied,
        planned=not apply,
        proposals=plan,
        dead_ends=dead_ends,
    )
