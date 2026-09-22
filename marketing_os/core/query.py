"""Deterministic retrieval planning.

Two retrieval paths, in preference order. When a catalogue exists the question is scored
against ``title``, ``description``, ``type`` and the path — metadata only, no document
bodies, so cost does not grow with document length. Without a catalogue it falls back to
the body scan, which is slower but always available on a fresh clone.

Either way the answer includes a ``route``: the ``_index.md`` chain leading to the best
candidate. Handing a model the branch rather than only the leaf is the whole point of the
navigation layer.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from marketing_os.core.catalog import SKIP_DIRS, excluded_roots, load_catalog
from marketing_os.core.results import envelope, finding, next_action

TERM = re.compile(r"[a-z0-9]+")

TITLE_WEIGHT = 3
DESCRIPTION_WEIGHT = 2
PATH_WEIGHT = 1

GREP_MAX_MATCHES = 40
GREP_LINE_LIMIT = 200


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric terms longer than two characters."""
    return [term for term in TERM.findall(text.lower()) if len(term) > 2]


def _corpus_files(root: Path) -> list[Path]:
    """Every groundable document in the brain.

    Widened past `business/` and `knowledge/wiki/`: a question about last quarter's launch
    cannot be answered from a corpus that never includes the launch.
    """
    skipped = excluded_roots()
    files: list[Path] = []
    for path in root.rglob("*.md"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        parts = relative.parts
        if any(part in SKIP_DIRS for part in parts):
            continue
        if parts and parts[0] in skipped:
            continue
        if path.name.startswith("_"):
            continue
        files.append(path)
    unique = {path.resolve(): path for path in files}
    return sorted(unique.values(), key=lambda path: path.as_posix())


def score_corpus(root: Path, terms: list[str]) -> list[tuple[Path, int, list[str]]]:
    """Score every corpus document against the query terms by reading bodies.

    Returns ``(path, score, matched_terms)`` tuples for documents with a positive score,
    sorted by descending score with a deterministic path tie-break. Score is the summed
    term frequency across the filename stem and body; ``matched_terms`` are the sorted
    unique query terms that appeared.
    """
    root = root.expanduser().resolve()
    wanted = [term for term in terms if term]
    results: list[tuple[Path, int, list[str]]] = []
    if not wanted:
        return results
    for path in _corpus_files(root):
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            continue
        counts = Counter(tokenize(path.stem + " " + body))
        score = sum(counts[term] for term in wanted)
        if score <= 0:
            continue
        matched = sorted({term for term in wanted if counts[term] > 0})
        results.append((path, score, matched))
    results.sort(key=lambda item: (-item[1], item[0].as_posix()))
    return results


def score_catalog(
    docs: dict[str, dict[str, Any]], terms: list[str]
) -> list[tuple[str, int, list[str]]]:
    """Score catalogued metadata against the query terms. Reads no document bodies."""
    wanted = [term for term in terms if term]
    results: list[tuple[str, int, list[str]]] = []
    if not wanted:
        return results
    for relative in sorted(docs):
        if Path(relative).name.startswith("_"):
            continue
        doc = docs[relative]
        title = Counter(tokenize(str(doc.get("title", ""))))
        description = Counter(tokenize(str(doc.get("description", ""))))
        context = Counter(
            tokenize(f"{relative.replace('/', ' ').replace('-', ' ')} {doc.get('type', '')}")
        )
        score = 0
        matched: set[str] = set()
        for term in wanted:
            hit = (
                title[term] * TITLE_WEIGHT
                + description[term] * DESCRIPTION_WEIGHT
                + context[term] * PATH_WEIGHT
            )
            if hit:
                matched.add(term)
                score += hit
        if score > 0:
            results.append((relative, score, sorted(matched)))
    results.sort(key=lambda item: (-item[1], item[0]))
    return results


def route_to(root: Path, relative: str) -> list[str]:
    """The chain of existing index files leading to a document."""
    chain: list[str] = []
    if (root / "_index.md").is_file():
        chain.append("_index.md")
    parts = Path(relative).parent.parts
    for depth in range(1, len(parts) + 1):
        candidate = Path(*parts[:depth]) / "_index.md"
        if (root / candidate).is_file():
            chain.append(candidate.as_posix())
    return chain


def grep_repo(root: Path, literal: str, *, limit: int = GREP_MAX_MATCHES) -> dict[str, Any]:
    """Literal substring lookup, for the searches term frequency handles badly.

    URLs, names, error strings and identifiers are exact things. Ranking them by term
    overlap is the wrong tool.
    """
    root = root.expanduser().resolve()
    needle = literal.strip()
    matches: list[dict[str, Any]] = []
    truncated = False
    if needle:
        lowered = needle.lower()
        for path in _corpus_files(root):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if lowered not in line.lower():
                    continue
                if len(matches) >= limit:
                    truncated = True
                    break
                matches.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "line": number,
                        "text": line.strip()[:GREP_LINE_LIMIT],
                    }
                )
            if truncated:
                break
    findings: list[dict[str, str]] = []
    if not needle:
        findings.append(finding("empty-query", "Nothing to search for.", severity="warning"))
    elif not matches:
        findings.append(
            finding("no-matches", "No document contains that literal string.", severity="warning")
        )
    if truncated:
        findings.append(
            finding(
                "results-truncated",
                f"Stopped after {limit} matches; narrow the string.",
                severity="warning",
            )
        )
    return envelope(
        "query",
        root,
        ok=True,
        findings=findings,
        action=next_action(
            "read-matches", "Open the matching files at the reported lines and answer from them."
        ),
        question=literal,
        mode="grep",
        source="filesystem",
        matches=matches,
        candidates=[],
        indexes=[],
        route=[],
    )


def query_repo(
    root: Path, question: str, *, limit: int = 5, literal: bool = False
) -> dict[str, Any]:
    """Plan deterministic retrieval for a question against the repository corpus."""
    root = root.expanduser().resolve()
    if literal:
        return grep_repo(root, question)

    terms = tokenize(question)
    docs = load_catalog(root)
    source = "catalog"
    scored: list[tuple[str, int, list[str]]] = score_catalog(docs, terms) if docs else []
    if not scored:
        source = "body-scan"
        scored = [
            (path.relative_to(root).as_posix(), score, matched)
            for path, score, matched in score_corpus(root, terms)
        ]

    top = scored[: limit if limit > 0 else 0]
    candidates = [
        {"path": relative, "score": score, "matched_terms": matched}
        for relative, score, matched in top
    ]
    index_path = root / "knowledge" / "wiki" / "_index.md"
    indexes = [index_path.relative_to(root).as_posix()] if index_path.is_file() else []
    route = route_to(root, top[0][0]) if top else route_to(root, "_index.md")

    findings: list[dict[str, str]] = []
    if not candidates:
        findings.append(
            finding(
                "no-matches",
                "No corpus document matched the question terms.",
                severity="warning",
            )
        )
    if docs is None:
        findings.append(
            finding(
                "no-catalog",
                "No catalogue on disk, so every document was read. Run `mos index build .`.",
                severity="warning",
                path=".mos/local/catalog.json",
            )
        )
    action = next_action(
        "synthesize-answer",
        "Walk the route indexes to confirm scope, then read the candidate files and answer "
        "the question with citations to those paths.",
    )
    return envelope(
        "query",
        root,
        ok=True,
        findings=findings,
        action=action,
        question=question,
        mode="terms",
        source=source,
        candidates=candidates,
        indexes=indexes,
        route=route,
    )
