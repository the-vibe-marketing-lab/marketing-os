"""Find the context a brain already holds, wherever its owner actually put it.

``mos status`` used to ask one question per field: is there real content at the single path
the schema names? A brain that answers brand, voice, audience and offer at length, in folders
of its own naming, reported all four as missing — and the dashboard then asked its owner to
write again what he had already written at length. That is the failure this module exists to
stop.

Nothing here guesses at meaning. A file becomes a candidate only when its **own name** claims
the field — the folder it sits in can corroborate that claim but can never make it alone,
because a folder name is a filing decision and says nothing about what any particular
document inside it contains. Candidates are then ranked on evidence that is cheap to read and
hard to fake: what the file is called, where it sits, and what its frontmatter claims about
itself. Every rule is a fixed integer, so the same tree always resolves the same way — no
model, no randomness, nothing a dashboard cannot reproduce.

Discovery never overrides an exact hit. A substantive canonical file short-circuits the scan
and is never scored, so a brain that follows the schema resolves exactly as it did before this
module existed. A scan that finds nothing convincing reports the field missing rather than
settling for the best of a bad field: being asked a question you have already answered is
annoying, but being told you have answered one you have not is worse. That asymmetry is why
navigation files, generated indexes and documents that mark themselves superseded are refused
outright rather than merely marked down — a folder map that lists what is missing must never
be read as the thing that is missing.
"""

from __future__ import annotations

import os
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from marketing_os.core.catalog import parse_frontmatter
from marketing_os.core.index import GENERATED
from marketing_os.core.schema import load_schema
from marketing_os.core.status import substantive, substantive_body

#: The words each field is known by, written the way an operator would actually spell them.
#: They are normalised once at import, so a folder called ``offers`` and a file called
#: ``offer.md`` are the same evidence and neither spelling has to be listed twice.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "brand": ("brand", "positioning", "identity", "brand-guidelines", "soul"),
    "voice": ("voice", "tone", "tone-of-voice", "writing-style", "style"),
    "audience": ("audience", "avatar", "persona", "icp", "primary", "customer", "segment"),
    "offer": ("offer", "offer-definition", "offer-backbone", "pricing", "package"),
    "strategy": ("strategy", "strategic", "roadmap", "okr", "plan"),
    "proof": ("proof", "testimonial", "case-study", "casestudy", "review", "result", "win"),
}

#: Folders that never hold a current answer: machinery, working scratch, and things already
#: retired. Reading them would let an abandoned draft speak for the business. They are
#: compared in the same normalised spelling as everything else in this module, so ``archives``
#: is excluded for the same reason ``archive`` is and neither spelling has to be listed twice.
EXCLUDED_SEGMENTS = frozenset(
    {
        ".git",
        ".obsidian",
        ".claude",
        ".agents",
        ".codex",
        ".mos",
        "_archive",
        "archive",
        "_templates",
        "templates",
        "brain-dump",
        "raw",
        "outputs",
        "node_modules",
        "graphify-out",
        ".venv",
        "__pycache__",
        "example",
        "sample",
        "draft",
        "scratch",
        "old",
        "backup",
        "fixture",
        "test",
        "tmp",
        "temp",
    }
)

#: File names that are somebody's navigation rather than anybody's answer. ``core.validation``
#: keeps a ``NAV_FILES`` of its own for the dated-folder grammar, and this is the same idea in
#: the same vocabulary — the file name as it is written on disk, lower-cased — so a reader who
#: has met one meets no second spelling here. The schema-derived list below is the reason most
#: of these are refused; this set is the floor that does not move when the schema does, because
#: a folder map is never an answer regardless of what any list later grows to contain.
NAV_FILES = frozenset(
    {
        "readme.md",
        "index.md",
        "_index.md",
        "log.md",
        "_log.md",
        "changelog.md",
        "contributing.md",
        "license.md",
        "notes.md",
        "todo.md",
    }
)

#: Frontmatter ``status`` values that say the document is not the answer: either it has been
#: left behind, or it is a placeholder standing where an answer will go. A document that says
#: this about itself is refused outright, not marked down — no amount of perfect naming should
#: let a retired file, or an admitted gap, answer for a live field. This is the lever an
#: operator has over discovery: a proof document that exists to record that there is no proof
#: yet says ``status: gap`` and stops being read as proof.
STALE_STATUSES = frozenset(
    {"stale", "archived", "superseded", "deprecated", "gap", "placeholder", "todo", "planned"}
)

#: What a hand-written ``canonical:`` flag looks like when it means yes.
TRUTHY = frozenset({"true", "yes", "1"})

#: The two folders a brain keeps content in. Nothing outside them is read: a symlink is not
#: a search root, so no link anyone leaves in the folder can widen what a status check reads.
SEARCH_ROOT_NAMES = ("business", "reference")

#: How far below a search root a scan will walk, counted in path segments. This is also what
#: terminates a symlink cycle, so the walk needs no global visited set to stay finite.
MAX_DEPTH = 4

#: A file this close to its search root was filed deliberately, not buried.
SHALLOW_DEPTH = 2

#: The score a candidate must reach before it is allowed to answer for a field. The weights
#: below are chosen against it: a whole-name match is enough on its own, a name that merely
#: contains one of the field's words is not, and placement contributes nothing by itself
#: because no file is ever scored on placement alone.
MIN_CONFIDENCE = 40

#: The file's own name is the field's name.
NAME_EXACT = 50
#: The file's own name is one of the words the field is known by. Deliberately short of the
#: bar on its own: ``business/pricing.md`` is the right word and nothing else, and one word
#: is not enough to let a file speak for what the business sells.
NAME_ALIAS = 30
#: One hyphen-separated word of the file's name is. ``tvml-strategy.md`` is evidence;
#: on its own it is deliberately not enough evidence, so it needs the folder to agree.
NAME_TOKEN = 20
#: The folder is named for the field.
PLACE_EXACT = 30
#: The folder is named for one of the field's other words.
PLACE_ALIAS = 20
#: The document says of itself that it is the source of truth.
CANONICAL_CLAIM = 20
#: Filed near the top of its tree rather than buried.
SHALLOW_BONUS = 5
#: An underscore-prefixed path part is a working area by convention.
UNDERSCORE_PENALTY = 20

#: An exact hit is not scored; it is simply believed.
CANONICAL_CONFIDENCE = 100

#: The most markdown files one resolution will open, across every root. Only files whose own
#: name already claims a field are opened, so noise in a neighbouring folder cannot spend the
#: budget the real answer needed.
FILE_BUDGET = 5000

#: The most directory entries one resolution will look at. ``FILE_BUDGET`` bounds the reading;
#: this bounds the walking, which is the cost a tree of empty folders runs up.
SCAN_BUDGET = 100_000

#: Enough of a file to hold its frontmatter and decide whether there is an answer under it.
#: A 200-megabyte transcript is not read into memory to find out it is not a voice document.
READ_LIMIT = 64 * 1024


def normalise(name: str) -> str:
    """One spelling for a file stem or a folder name, so near-misses compare equal.

    ``Offer_Definition.md``, ``offer-definition`` and ``offer-definitions`` all reduce to the
    same word. The trailing ``s`` only goes when what is left is longer than two characters,
    which keeps ``offers`` and ``okrs`` singular without turning ``ops`` into ``op``; ``-ies``
    becomes ``-y`` so ``strategies`` and ``case-studies`` reach the words they are plurals of;
    and a word ending ``ss`` is left alone, because ``business`` is not a plural of anything.
    """
    text = name.lower()
    if text.endswith(".md"):
        text = text[: -len(".md")]
    text = text.replace("_", "-")
    if text.startswith("-"):
        # ``_shared`` becomes ``-shared`` on the line above; the hyphen is punctuation the
        # author never typed, so it is not evidence either way.
        text = text[1:]
    if text.endswith("ies") and len(text) > 4:
        return text[: -len("ies")] + "y"
    if text.endswith("ss"):
        return text
    if text.endswith("s") and len(text) - 1 > 2:
        text = text[:-1]
    return text


#: The alias table in the one spelling the scan compares against.
ALIASES: dict[str, frozenset[str]] = {
    field: frozenset(normalise(word) for word in words) for field, words in FIELD_ALIASES.items()
}

#: The exclusion list in that same spelling, so ``archives`` and ``Templates`` are excluded
#: for the reasons ``archive`` and ``templates`` are.
EXCLUDED_NAMES: frozenset[str] = frozenset(normalise(name) for name in EXCLUDED_SEGMENTS)


@lru_cache(maxsize=1)
def meta_names() -> frozenset[str]:
    """File names that are navigation or machinery rather than anybody's answer.

    The schema already names most of these twice over — ``generated_files`` is what ``mos index
    sync`` writes, and ``frontmatter_contract.exempt_names`` is the set of files exempt from the
    document contract precisely because they are structural. Reading those lists rather than
    copying them is what stops ``business/audience/_index.md``, a file this program generates
    itself, from answering the audience question, and it keeps this module honest when the
    schema gains a structural file.

    ``NAV_FILES`` is then unioned in as the floor. It overlaps the schema deliberately: the
    schema is a contract about documents and could reasonably stop exempting ``README.md``
    tomorrow, and the day it does, a folder map must still not be able to answer for the folder
    it maps.
    """
    schema = load_schema()
    names = {str(name).lower() for name in schema.get("generated_files", ())}
    names.update(
        str(name).lower() for name in schema["frontmatter_contract"].get("exempt_names", ())
    )
    names.update(NAV_FILES)
    return frozenset(names)


@dataclass(frozen=True)
class Resolution:
    """Where one context field is actually answered, and how sure we are that it is.

    ``path`` is the file that answers the field, or the canonical path when nothing does, so
    a caller always has somewhere to point. ``confidence`` is 100 for an exact hit, the
    winning score for a discovered file, and 0 when nothing cleared the bar. ``considered``
    counts the candidates that were scored, which is how a caller tells "there was nothing
    to look at" from "there were six and none of them convinced us". ``truncated`` says the
    scan ran out of budget before it finished, so a ``missing`` verdict beside it means
    "not found in what we looked at" rather than "not there".
    """

    path: Path
    source: str
    confidence: int
    considered: int
    truncated: bool = False


@dataclass(frozen=True)
class _Candidate:
    """One scored file, with the repo-relative path the tie-break and the caller both use."""

    path: Path
    relative: str
    score: int


def _rank(candidate: _Candidate) -> tuple[int, int, str]:
    """The one ordering used for every choice between candidates.

    Highest score wins; a tie goes to the shorter path, then to the earlier one
    alphabetically, so two equally good answers always resolve the same way. The same key
    picks the winner and picks which of a file's several reachable names to report it under.
    """
    return (-candidate.score, len(candidate.relative), candidate.relative)


def _read(path: Path) -> str | None:
    """The head of the file's text, or ``None`` if it cannot be read as text.

    A brain is full of things that are not prose — exports, half-copied binaries, a file the
    operator has no permission to open. None of them can answer a question, and none of them
    is worth failing a status check over. A byte-order mark is consumed rather than kept,
    because a leading ``\\ufeff`` would push the frontmatter fence off the first line and
    silently hide both the staleness marker and the canonical claim.
    """
    try:
        with path.open(encoding="utf-8-sig") as handle:
            return handle.read(READ_LIMIT)
    except (OSError, ValueError):
        return None


def _entries(directory: Path) -> list[os.DirEntry[str]]:
    """The directory's entries in name order, or none at all when it cannot be read.

    Name order is what makes a scan reproducible: the budget below decides which files are
    reached, so the order they are reached in has to be the same on every run.
    """
    try:
        with os.scandir(directory) as scan:
            return sorted(scan, key=lambda entry: entry.name)
    except OSError:
        return []


def _entry_is_dir(entry: os.DirEntry[str]) -> bool:
    """Whether the entry is a directory, following symlinks, treating errors as no."""
    try:
        return entry.is_dir()
    except OSError:
        return False


def _entry_is_symlink(entry: os.DirEntry[str]) -> bool:
    """Whether the entry is itself a link, treating errors as no."""
    try:
        return entry.is_symlink()
    except OSError:
        return False


def _real_child(parent_real: str, entry: os.DirEntry[str]) -> str:
    """The real path of one entry, resolved only when it can actually differ.

    ``realpath`` is a syscall per component, and on a mounted Windows filesystem that is the
    single most expensive thing this scan does. It is also unnecessary for all but a handful
    of entries: if the parent's real path is already resolved and the child is not a link,
    the child's real path is the two joined. Only a link needs the kernel's answer.
    """
    if _entry_is_symlink(entry):
        return os.path.realpath(entry.path)
    return os.path.join(parent_real, entry.name)


def _inside(candidate: str, root_real: str) -> bool:
    """Whether a resolved path is somewhere strictly below the repository being looked at.

    Every path this module reports is repo-relative, so a link that resolves outside would
    report a file that is not in the brain under a name that says it is. A link resolving to
    the repository root is refused for the same reason: it would turn the whole repository
    into a search root and expose the folders the two-root design deliberately leaves out.
    """
    if not candidate or candidate == root_real:
        return False
    return candidate.startswith(root_real.rstrip(os.sep) + os.sep)


def _excluded(name: str) -> bool:
    """Whether a directory entry is one of the folders a scan never reads."""
    return name.lower() in EXCLUDED_SEGMENTS or normalise(name) in EXCLUDED_NAMES


def _search_roots(root: Path, root_real: str) -> list[tuple[Path, str]]:
    """Each tree worth walking, with its real path.

    Those are the two content folders and nothing else. An earlier version promoted every
    top-level symlink to a search root, which read whatever anyone had linked into the folder
    — a parent directory of sibling repositories, a home directory, the repository itself —
    and reported files from outside the brain under repo-relative names. A brain's content
    lives in ``business/`` and ``reference/``; a link is not a third place for it to live.
    """
    roots: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for name in SEARCH_ROOT_NAMES:
        path = root / name
        if not path.is_dir():
            continue
        real = os.path.realpath(path)
        if not _inside(real, root_real) or real in seen:
            continue
        seen.add(real)
        roots.append((path, real))
    return roots


def _name_signal(stem: str, tokens: frozenset[str], aliases: frozenset[str]) -> bool:
    """Whether the file's own name claims this field at all.

    This is the gate placement cannot open. A folder called ``audience/`` says where its owner
    files things, not what any one document in it says, so a file whose own name carries no
    trace of the field — a README, a research bank, a copyright notice — is never opened,
    never scored, and never able to answer. The whole name is the strong form; one
    hyphen-separated word of it is the weak form, which the weights below leave short of the
    bar on its own.
    """
    return stem in aliases or bool(tokens & aliases)


def _score(
    name: str,
    aliases: frozenset[str],
    stem: str,
    tokens: frozenset[str],
    parent: str,
    parts: tuple[str, ...],
    meta: dict[str, Any],
) -> int:
    """How much evidence there is that this file answers this field.

    Naming carries the most weight, because it is the one thing an operator chooses per
    document: a file called ``voice.md`` is a claim about that file, where a file that merely
    sits in ``voice/`` is a claim about the folder. Placement corroborates and cannot stand
    alone. The frontmatter adjustment is the document's own claim about itself — a brain that
    marks its source of truth deserves to be believed. ``parts`` is the path below its search
    root, so an underscore-prefixed folder — a working area by convention — costs the file
    its lead.
    """
    score = 0
    if stem == name:
        score += NAME_EXACT
    elif stem in aliases:
        score += NAME_ALIAS
    elif tokens & aliases:
        score += NAME_TOKEN
    if parent == name:
        score += PLACE_EXACT
    elif parent in aliases:
        score += PLACE_ALIAS
    if str(meta.get("canonical", "")).strip().lower() in TRUTHY:
        score += CANONICAL_CLAIM
    if len(parts) <= SHALLOW_DEPTH:
        score += SHALLOW_BONUS
    if any(part.startswith("_") for part in parts):
        score -= UNDERSCORE_PENALTY
    return score


def _is_answer(text: str, meta: dict[str, Any], body: str) -> bool:
    """Whether this document is allowed to answer for a field at all.

    Three refusals, all of them outright rather than a deduction. A document with no
    substance is not an answer. A document this program generated is a map of the brain, and
    a map that lists what is missing must never be mistaken for the thing that is missing. A
    document that marks itself superseded, or a placeholder standing where an answer will go,
    has told us in its own words not to read it.

    The body arrives already parsed. Judging the whole text instead would parse the
    frontmatter a second time for every candidate, which is the sort of cost that is
    invisible in a unit test and measurable on a real brain.
    """
    if not substantive_body(body):
        return False
    if GENERATED in text:
        return False
    return str(meta.get("status", "")).strip().lower() not in STALE_STATUSES


def _collect(root: Path, fields: tuple[str, ...]) -> tuple[dict[str, list[_Candidate]], bool]:
    """Every substantive file that could be answering any of ``fields``, scored, in one walk.

    One walk, not one per field. The tree a status check reads is the same tree for every
    question asked of it, and walking it six times was the whole of the cost: only the alias
    test and the score depend on which field is being asked about, and both are arithmetic
    on names already in hand.

    The walk is breadth-first through sorted entries, so the shallow files — the ones most
    likely to be the real answer — are reached first and the budget bites at the bottom of a
    deep tree rather than in the middle of a shallow one. Depth alone terminates it: a
    symlink loop cannot outrun ``MAX_DEPTH``, so no global visited set is needed, and that
    matters because a visited set claimed at enqueue time hid the real directory whenever a
    symlink to it happened to sort earlier. Files are instead deduplicated by real path once
    they are scored, and a file reachable under several names is reported under its best one.
    """
    names = {field: normalise(field) for field in fields}
    alias_map = {field: ALIASES.get(field) or frozenset({names[field]}) for field in fields}
    root_real = os.path.realpath(root)
    best: dict[str, dict[str, _Candidate]] = {field: {} for field in fields}
    opened = 0
    scanned = 0
    truncated = False
    queue: deque[tuple[Path, Path, int, str]] = deque()
    for base, base_real in _search_roots(root, root_real):
        queue.append((base, base, 0, base_real))

    while queue:
        directory, base, depth, directory_real = queue.popleft()
        parent = normalise(directory.name)
        for entry in _entries(directory):
            scanned += 1
            if scanned > SCAN_BUDGET:
                truncated = True
                queue.clear()
                break
            if _excluded(entry.name):
                continue
            path = Path(entry.path)
            if _entry_is_dir(entry):
                # A directory at MAX_DEPTH could only hold files below it, so it is not worth
                # opening. A link out of the repository is not worth opening at all.
                if depth + 1 >= MAX_DEPTH:
                    continue
                real = _real_child(directory_real, entry)
                if not _inside(real, root_real):
                    continue
                queue.append((path, base, depth + 1, real))
                continue
            lower = entry.name.lower()
            if not lower.endswith(".md") or lower in meta_names():
                continue
            stem = normalise(entry.name)
            tokens = frozenset(stem.split("-"))
            interested = [field for field in fields if _name_signal(stem, tokens, alias_map[field])]
            if not interested:
                continue
            opened += 1
            if opened > FILE_BUDGET:
                truncated = True
                queue.clear()
                break
            text = _read(path)
            if text is None:
                continue
            meta, body = parse_frontmatter(text)
            if not _is_answer(text, meta, body):
                continue
            real = _real_child(directory_real, entry)
            parts = path.relative_to(base).parts
            relative = path.relative_to(root).as_posix()
            for field in interested:
                candidate = _Candidate(
                    path=path,
                    relative=relative,
                    score=_score(names[field], alias_map[field], stem, tokens, parent, parts, meta),
                )
                seen = best[field].get(real)
                if seen is None or _rank(candidate) < _rank(seen):
                    best[field][real] = candidate
    return {field: list(found.values()) for field, found in best.items()}, truncated


def resolve_fields(root: Path, canonical: Mapping[str, Path]) -> dict[str, Resolution]:
    """Where every field in ``canonical`` is actually answered, in a single pass of the tree.

    Each canonical path is asked first and, when it holds a real answer, wins outright
    without being scored — an exact hit needs no evidence. Only the fields whose canonical
    path is missing or still boilerplate reach the walk, so a brain that follows the schema
    costs nothing at all, and a brain that follows none of it still costs one walk rather
    than one per question.
    """
    resolved: dict[str, Resolution] = {}
    pending: dict[str, Path] = {}
    for field, path in canonical.items():
        if substantive(path):
            resolved[field] = Resolution(
                path=path,
                source="canonical",
                confidence=CANONICAL_CONFIDENCE,
                considered=0,
            )
        else:
            pending[field] = path
    if not pending:
        return resolved

    found, truncated = _collect(root, tuple(pending))
    for field, path in pending.items():
        candidates = found.get(field) or []
        best = min(candidates, key=_rank) if candidates else None
        if best is not None and best.score >= MIN_CONFIDENCE:
            resolved[field] = Resolution(
                path=best.path,
                source="discovered",
                confidence=best.score,
                considered=len(candidates),
                truncated=truncated,
            )
        else:
            resolved[field] = Resolution(
                path=path,
                source="missing",
                confidence=0,
                considered=len(candidates),
                truncated=truncated,
            )
    return resolved


def resolve_field(root: Path, field: str, canonical: Path) -> Resolution:
    """Where one field is answered in the brain at ``root``."""
    return resolve_fields(root, {field: canonical})[field]
