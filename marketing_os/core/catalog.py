"""Catalogue every markdown document in a brain.

The catalogue is the retrieval interface. Corpus2Skill (arXiv 2604.14572) and
"Is Grep All You Need?" (arXiv 2605.15184) both land on the same result: for a corpus an
agent navigates with a filesystem, a hierarchy of small index files beats an embedding
index. Both need one thing first — every document must state what it is. This module
reads that statement, and nothing here calls a model.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from marketing_os.core.atomic import atomic_write
from marketing_os.core.parallel import pmap
from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import load_schema, schema_fingerprint

SKIP_DIRS = frozenset(
    {
        ".git",
        ".mos",
        ".claude",
        ".agents",
        ".codex",
        ".obsidian",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
    }
)

WIKILINK = re.compile(r"\[\[([^\]|#]+)")
RELATED_HEADING = re.compile(r"(?m)^##\s+Related\s*$")
KEY_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(.*)$")
SEQUENCE_ITEM = re.compile(r"^\s+-\s+(.*)$")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a YAML-fenced frontmatter block from its body.

    Understands the subset the contract uses: scalars, inline ``[a, b]`` lists, and block
    sequences. Anything richer is not worth a dependency here.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta: dict[str, Any] = {}
    key: str | None = None
    body_at: int | None = None
    for offset, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body_at = offset + 1
            break
        item = SEQUENCE_ITEM.match(line)
        if item and key is not None:
            value = _unquote(item.group(1))
            existing = meta.get(key)
            if isinstance(existing, list):
                existing.append(value)
            else:
                meta[key] = [value] if not existing else [existing, value]
            continue
        match = KEY_LINE.match(line)
        if not match:
            continue
        key = match.group(1).strip()
        raw = match.group(2).strip()
        if raw.startswith("[") and raw.endswith("]"):
            meta[key] = [_unquote(part) for part in raw[1:-1].split(",") if part.strip()]
        elif raw:
            meta[key] = _unquote(raw)
        else:
            meta[key] = ""
    if body_at is None:
        return {}, text
    return meta, "\n".join(lines[body_at:])


def first_sentence(body: str, limit: int = 160) -> str:
    """Best available one-line summary when a document declares no description."""
    for para in body.split("\n\n"):
        text = para.strip()
        if not text or text.startswith(("#", "|", ">", "```", "- ", "* ", "!")):
            continue
        text = re.sub(r"\[\[([^\]|]+)\|?([^\]]*)\]\]", r"\2\1", text)
        text = re.sub(r"[*_`#]", "", text).replace("\n", " ").strip()
        if len(text) < 20:
            continue
        if len(text) <= limit:
            return text
        return text[:limit].rsplit(" ", 1)[0] + "..."
    return ""


def excluded_roots() -> tuple[str, ...]:
    return tuple(load_schema().get("excluded_from_grounding", ()))


#: One catalogued file: where it is, what it is called from the brain root, and the two
#: numbers that say whether it is the same file it was last time.
Scanned = tuple[Path, str, int, int]


#: What one directory holds: its subdirectories, then its markdown files, each as
#: ``(name, path)``.
Listing = tuple[list[tuple[str, str]], list[tuple[str, str]]]


def _read_dir(directory: str) -> Listing:
    """One directory's subdirectories and markdown files, or empty when it cannot be read.

    ``is_dir(follow_symlinks=False)`` answers from what the directory read already
    returned, so this costs one syscall however many entries come back.
    """
    subdirectories: list[tuple[str, str]] = []
    files: list[tuple[str, str]] = []
    try:
        with os.scandir(directory) as entries:
            listing = list(entries)
    except OSError:
        return subdirectories, files
    for entry in listing:
        try:
            if entry.is_dir(follow_symlinks=False):
                subdirectories.append((entry.name, entry.path))
            elif entry.name.endswith(".md"):
                files.append((entry.name, entry.path))
        except OSError:
            continue
    return subdirectories, files


def _stamp(path: str) -> tuple[int, int] | None:
    """A file's modification time and size, or ``None`` when it cannot be stat-ed."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def scan(root: Path) -> list[Scanned]:
    """Every catalogued markdown file with its size and modification time.

    Pruned while walking rather than filtered afterwards. ``rglob`` reads a directory to
    find its subdirectories and reads it again to match its files, then descends into
    everything before the caller throws the wrong branches away: on a real brain that was
    2,044 directory reads to return 1,524 files, 1,438 of them spent inside ``.git``,
    ``node_modules`` and the excluded roots. Refusing to descend costs 606 reads for the
    identical answer.

    Each level is read with its siblings, because the cost here is round-trip latency
    rather than work — see ``core.parallel``. Symlinked directories are not followed,
    which is what ``rglob`` does and what keeps the walk finite without a visited set.

    The stat is taken here, while the directory is being read anyway, because it is what
    lets the caller decide whether a document has to be opened at all.
    """
    skipped = excluded_roots()
    #: Every markdown file the walk reached, as ``(path, repo-relative posix path)``.
    reached: list[tuple[str, str]] = []
    level = [(str(root), "")]
    while level:
        listings = pmap(_read_dir, [directory for directory, _prefix in level])
        below: list[tuple[str, str]] = []
        for (_directory, prefix), (subdirectories, files) in zip(level, listings, strict=True):
            for name, path in subdirectories:
                if name in SKIP_DIRS or (not prefix and name in skipped):
                    continue
                below.append((path, f"{prefix}/{name}" if prefix else name))
            for name, path in files:
                reached.append((path, f"{prefix}/{name}" if prefix else name))
        level = below

    # Every file at once rather than a directory's worth at a time. A walk is only as wide
    # as the level it is on, and a brain has levels holding two folders and three hundred
    # documents; stat-ing inside the directory read left those three hundred waits in a
    # queue behind each other, which measured 1.8 seconds against 0.8 for this.
    stamps = pmap(_stamp, [path for path, _relative in reached])
    found: list[Scanned] = [
        (Path(path), relative, stamp[0], stamp[1])
        for (path, relative), stamp in zip(reached, stamps, strict=True)
        if stamp is not None
    ]
    return sorted(found, key=lambda item: item[1])


def docs_iter(root: Path) -> list[tuple[Path, str]]:
    """Every catalogued markdown file, as ``(absolute path, repo-relative posix path)``."""
    return [(path, relative) for path, relative, _mtime, _size in scan(root)]


def _link_targets(meta: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    for key in ("related", "sources"):
        value = meta.get(key)
        if isinstance(value, list):
            targets.extend(str(item) for item in value)
        elif isinstance(value, str) and value:
            targets.append(value)
    return [item.strip() for item in targets if "/" in item or item.endswith(".md")]


def describe(path: Path, relative: str, text: str) -> dict[str, Any]:
    meta, body = parse_frontmatter(text)
    contract = load_schema()["frontmatter_contract"]
    links = {match.strip() for match in WIKILINK.findall(text)}
    links.update(target.strip() for target in _link_targets(meta))
    description = str(meta.get("description") or "").strip() or first_sentence(body)
    present = [key for key in contract["connective_keys"] if meta.get(key)]
    return {
        "title": str(meta.get("title") or path.stem.replace("-", " ")).strip(),
        "description": description,
        "type": str(meta.get("type") or ""),
        "status": str(meta.get("status") or ""),
        "date": str(meta.get("date") or ""),
        "words": len(body.split()),
        "links_out": sorted(links),
        "connective_keys": present,
        "has_frontmatter": bool(meta),
        "has_related_block": bool(RELATED_HEADING.search(text)),
        "missing_keys": [key for key in contract["required_keys"] if not meta.get(key)],
        "path": relative,
    }


#: What the scan cache is, so a file written by an older version is ignored rather than
#: misread. The fingerprint inside it names the schema the entries were read against.
SCAN_CACHE_SCHEMA = "mos.scan-cache.v1"


def scan_cache_path(root: Path) -> Path:
    return root / ".mos" / "local" / "scan-cache.json"


def _load_scan_cache(root: Path) -> dict[str, tuple[int, int, dict[str, Any]]]:
    """Last run's readings, keyed by path, or nothing at all if anything looks wrong.

    Every failure — absent, unreadable, half-written by a run that was killed, written by
    a version whose schema said something else — is the same answer: nothing is known, so
    read the brain. A cache is only ever allowed to save work, never to decide anything.
    """
    try:
        payload = json.loads(scan_cache_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema") != SCAN_CACHE_SCHEMA:
        return {}
    if payload.get("fingerprint") != schema_fingerprint():
        return {}
    stored = payload.get("docs")
    if not isinstance(stored, dict):
        return {}
    known: dict[str, tuple[int, int, dict[str, Any]]] = {}
    for relative, record in stored.items():
        if not isinstance(record, dict) or not isinstance(record.get("doc"), dict):
            continue
        stamp = record.get("stamp")
        if not isinstance(stamp, list) or len(stamp) != 2:
            continue
        mtime, size = stamp
        if not isinstance(mtime, int) or not isinstance(size, int):
            continue
        known[relative] = (mtime, size, record["doc"])
    return known


def _write_scan_cache(root: Path, entries: list[Scanned], docs: dict[str, dict[str, Any]]) -> None:
    """Record what was read, so the next run only opens what has actually changed.

    Machine-local state under ``.mos/local/``, beside the runtime manifest, and ignored by
    the brain's own ``.gitignore``. Written atomically because two status requests for one
    brain are normal in the app — reads are deliberately unlocked there — and a reader
    must never meet half a file. A brain that cannot be written to keeps working: it just
    pays full price every time.
    """
    stamps = {relative: (mtime, size) for _path, relative, mtime, size in entries}
    payload = {
        "schema": SCAN_CACHE_SCHEMA,
        "fingerprint": schema_fingerprint(),
        "docs": {
            relative: {"stamp": list(stamps[relative]), "doc": doc}
            for relative, doc in docs.items()
            if relative in stamps
        },
    }
    try:
        atomic_write(
            scan_cache_path(root), json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
    except OSError:
        return


def _read_document(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def build_catalog(root: Path) -> dict[str, dict[str, Any]]:
    """The catalogue: what every markdown document in the brain says it is.

    Reading fifteen hundred documents is the most expensive thing this program does, and
    on a repeat run almost none of them have changed. So the walk takes each file's size
    and modification time, which it is already in the directory for, and a document whose
    two numbers match the last run's is not opened at all — its previous reading is reused
    verbatim. Everything else is read, and read alongside its neighbours rather than after
    them.

    This is per-file invalidation, which is the only kind that can be trusted here: a
    folder's modification time does not move when a file inside it is edited, so a cache
    keyed on folders would keep showing yesterday's answer to an operator who has just
    filled in a field, which is worse than being slow. Editing, adding, removing, renaming
    or replacing a document all change one of the two numbers, and a schema upgrade
    invalidates every entry at once through the fingerprint.

    Nothing here decides anything: the cache only ever says "this file is byte-for-byte
    the file you already read", and the answer is what a full read would have produced.
    """
    entries = scan(root)
    cached = _load_scan_cache(root)
    docs: dict[str, dict[str, Any]] = {}
    unread: list[tuple[Path, str]] = []
    for path, relative, mtime, size in entries:
        known = cached.get(relative)
        if known is not None and known[0] == mtime and known[1] == size:
            docs[relative] = known[2]
            continue
        docs[relative] = {}
        unread.append((path, relative))

    texts = pmap(_read_document, [path for path, _relative in unread])
    for (path, relative), text in zip(unread, texts, strict=True):
        if text is None:
            del docs[relative]
            continue
        docs[relative] = describe(path, relative, text)

    if any(relative in docs for _path, relative in unread) or set(docs) != set(cached):
        _write_scan_cache(root, entries, docs)
    return docs


def catalog_path(root: Path) -> Path:
    return root / ".mos" / "local" / "catalog.json"


def write_catalog(root: Path, docs: dict[str, dict[str, Any]]) -> Path:
    target = catalog_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(docs, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def load_catalog(root: Path) -> dict[str, dict[str, Any]] | None:
    """Return the persisted catalogue, or ``None`` when it is absent or unreadable."""
    target = catalog_path(root)
    if not target.is_file():
        return None
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


NAV_NAMES = frozenset({"_index.md", "_log.md"})


def coverage(docs: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Contract coverage over real documents.

    Generated indexes are excluded: they are the map, not the territory, and counting
    them would flatter every percentage the sensors report.
    """
    real = [item for path, item in docs.items() if Path(path).name not in NAV_NAMES]
    return {
        "documents": len(real),
        "with_frontmatter": sum(1 for item in real if item["has_frontmatter"]),
        "with_description": sum(1 for item in real if item["description"]),
        "with_outgoing_links": sum(
            1 for item in real if item["links_out"] or item["has_related_block"]
        ),
    }


def build_repo(root: Path) -> dict[str, Any]:
    """``mos index build`` — catalogue the brain into machine-local state."""
    root = root.expanduser().resolve()
    docs = build_catalog(root)
    target = write_catalog(root, docs)
    stats = coverage(docs)
    findings: list[dict[str, str]] = []
    if not docs:
        findings.append(
            finding("empty-corpus", "No markdown documents to catalogue.", severity="warning")
        )
    return envelope(
        "index-build",
        root,
        ok=True,
        changes=[f"write {target.relative_to(root).as_posix()}"],
        findings=findings,
        action=next_action(
            "sync-indexes", "Regenerate the navigation hierarchy with `mos index sync . --yes`."
        ),
        catalog=target.relative_to(root).as_posix(),
        coverage=stats,
    )
