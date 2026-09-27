"""``mos fix invalid-month`` — rename legacy ``YYYY/MM`` month folders to ``YYYY/MM-Mon``.

Since 0.5.0 a brain with no ``month_folder`` key files its dated work under ``09-Sep``
rather than ``09``. A brain made before then still has ``09`` folders, and every document
that points into them. This module moves both across in one deterministic pass:

- every ``YYYY/MM`` directory under the dated trees becomes ``YYYY/MM-Mon``. Only a bare
  month directly inside a four-digit year folder of ``content``, ``campaigns``, ``outputs``,
  ``business/decisions`` or ``knowledge/sources`` is renamed: ``reporting/`` (quarters),
  ``YYYY-MM`` names and any other folder are never touched; when an
  ``MM-Mon`` folder for the same month already exists (the first ``mos ingest`` after an
  upgrade makes one), the two are merged, unless an entry of the same name is in both;
- every reference that resolves into a moved folder is rewritten, in the brain's Markdown,
  Obsidian canvases and bases. A reference is resolved the way Obsidian resolves it — from
  the brain root, or from the document's own folder — so ``archive/content/2026/09`` (never
  moved), ``content/2026/09.md`` (a file, not the month) and anything with a ``://`` in it
  are left alone, and a month-relative ``../09/...`` is carried across. Code spans and
  fenced blocks are never touched.

A merge never overwrites: a name clash refuses the whole run. A move that fails part-way
(a file held open on Windows) stops there, the links to the months already moved are still
rewritten, and running it again finishes the job: each completed move is journalled in
``.mos/local/month-moves.json``, and a later run rewrites links for journalled months too.
Only links into a month this command moved are rewritten. A brain that says
``month_folder: "MM"`` has opted out and is left alone. A second run changes nothing.
"""

from __future__ import annotations

import bisect
import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any

from marketing_os.core.atomic import atomic_write
from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import (
    DATED_ROOTS,
    MONTH_ABBREVIATIONS,
    is_month_dir,
    month_folder_style,
    read_config,
)

YEAR = re.compile(r"^\d{4}$")
#: The documents whose references are rewritten: notes, canvases and bases.
SUFFIXES = (".md", ".canvas", ".base")
#: One path-like run of text. The delimiters are what surround a path in Markdown, a
#: wikilink, YAML and JSON, so a token is the path and nothing around it.
TOKEN = re.compile(r"[^\s()\[\]<>|\"'`#,;{}*]+")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1")
#: Machine-local record of the months this command moved, so an interrupted run's links
#: are finished by the next one. Under ``.mos/local/``, which every brain ignores.
JOURNAL = ".mos/local/month-moves.json"
JOURNAL_SCHEMA = "mos.month-moves.v1"
#: A merge drops the source's copy of these instead of calling it a clash.
DISPOSABLE = frozenset({".gitkeep"})

Move = tuple[Path, Path, bool]  # source, target, whether the target already exists
Edit = tuple[Path, str, int]


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _month_folders(root: Path) -> list[Path]:
    """Every directory directly under a year folder of the dated trees."""
    folders: list[Path] = []
    for relative in DATED_ROOTS:
        base = root / relative
        if not base.is_dir():
            continue
        for year in sorted(base.iterdir()):
            if year.is_dir() and YEAR.fullmatch(year.name):
                folders.extend(month for month in sorted(year.iterdir()) if month.is_dir())
    return folders


def _new_name(number: str) -> str:
    return f"{number}-{MONTH_ABBREVIATIONS[int(number) - 1]}"


def _plan_moves(root: Path) -> tuple[list[Move], list[dict[str, str]]]:
    """Every bare month folder's move, and a finding for each merge that would clash."""
    moves: list[Move] = []
    clashes: list[dict[str, str]] = []
    for month in _month_folders(root):
        if not is_month_dir(month.name, "MM"):
            continue
        target = month.parent / _new_name(month.name)
        if not target.exists():
            moves.append((month, target, False))
            continue
        both = sorted(
            child.name
            for child in month.iterdir()
            if child.name not in DISPOSABLE and (target / child.name).exists()
        )
        if both:
            clashes.append(
                finding(
                    "month-folder-exists",
                    f"{target.name} already exists beside {month.name} and both hold "
                    f"{', '.join(both)}; merge those by hand, then run this again.",
                    path=_rel(root, month),
                )
            )
        else:
            moves.append((month, target, True))
    return moves, clashes


def _journal(root: Path) -> dict[str, str]:
    """The months this command has already moved in this brain, old path -> new name."""
    try:
        payload = json.loads((root / JOURNAL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    moves = payload.get("moves") if isinstance(payload, dict) else None
    if not isinstance(moves, dict):
        return {}
    return {str(old): str(new) for old, new in moves.items()}


def _record(root: Path, source: Path, target: Path) -> None:
    """Journal one completed move, so a run that stops before its links finishes them later."""
    moves = _journal(root)
    moves[_rel(root, source)] = target.name
    payload = {"schema": JOURNAL_SCHEMA, "moves": dict(sorted(moves.items()))}
    atomic_write(root / JOURNAL, json.dumps(payload, indent=2) + "\n")


def _moved(root: Path, moves: list[Move]) -> dict[str, str]:
    """Old month path -> new month name, for every month a reference may still name.

    Only months this command moves: the ones about to move and the ones an earlier run
    moved (the journal). A folder someone renamed by hand is not this rule's to follow, and
    a month folder that was always ``MM-Mon`` was never renamed at all.
    """
    moved = _journal(root)
    moved.update({_rel(root, source): target.name for source, target, _ in moves})
    return moved


def _walk(base: list[str], parts: list[str], moved: dict[str, str]) -> str | None:
    """Resolve ``parts`` from ``base``; the token with each moved segment renamed, or None."""
    current = list(base)
    out = list(parts)
    changed = False
    for index, segment in enumerate(parts):
        if segment in ("", "."):
            continue
        if segment == "..":
            if not current:
                return None  # climbs out of the brain
            current.pop()
            continue
        current.append(segment)
        new = moved.get("/".join(current))
        if new is not None:
            out[index] = current[-1] = new
            changed = True
    return "/".join(out) if changed else None


def _retarget(token: str, folder: list[str], moved: dict[str, str]) -> str | None:
    """The rewritten token when it resolves into a moved month, else None."""
    if "/" not in token or "://" in token or token.startswith("//"):
        return None
    parts = token.split("/")
    if ":" in parts[0]:
        return None  # mailto:, C:, and other schemes
    if parts[0] in (".", ".."):
        bases = [folder]
    elif parts[0] == "":
        bases = [[]]  # a leading slash means the brain root
    else:
        bases = [[], folder]  # vault-absolute first, then relative to the document
    for base in bases:
        new = _walk(base, parts, moved)
        if new is not None:
            return new
    return None


def _protected(text: str) -> list[tuple[int, int]]:
    """The spans of fenced code blocks and inline code, which are never rewritten."""
    spans: list[tuple[int, int]] = []
    fence: str | None = None
    offset = 0
    for line in text.splitlines(keepends=True):
        opener = FENCE.match(line)
        if fence is not None:
            spans.append((offset, offset + len(line)))
            if line.lstrip().startswith(fence):
                fence = None
        elif opener:
            spans.append((offset, offset + len(line)))
            fence = opener.group(1)[0] * 3
        else:
            spans.extend((offset + m.start(), offset + m.end()) for m in INLINE_CODE.finditer(line))
        offset += len(line)
    return spans


def _rewrite_text(
    text: str, folder: list[str], moved: dict[str, str], markdown: bool
) -> tuple[str, int]:
    spans = _protected(text) if markdown else []
    starts = [start for start, _ in spans]
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        index = bisect.bisect_right(starts, match.start()) - 1
        if index >= 0 and match.start() < spans[index][1]:
            return match.group(0)
        new = _retarget(match.group(0), folder, moved)
        if new is None:
            return match.group(0)
        count += 1
        return new

    return TOKEN.sub(replace, text), count


def _documents(root: Path) -> list[Path]:
    """The brain's documents, skipping hidden machinery and never following a linked folder."""
    found: list[Path] = []
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if not name.startswith("."))
        found.extend(Path(current) / name for name in sorted(files) if name.endswith(SUFFIXES))
    return found


def _read(path: Path, relative: str) -> tuple[str | None, dict[str, str] | None]:
    """A document's text, or the warning that says why it was not checked."""
    if path.is_symlink():
        return None, finding(
            "linked-document",
            "A symlinked document is not rewritten; update its month links by hand.",
            severity="warning",
            path=relative,
        )
    try:
        # Bytes, decoded: no newline translation, so a CRLF document stays CRLF.
        return path.read_bytes().decode("utf-8"), None
    except (OSError, UnicodeDecodeError):
        return None, finding(
            "unreadable-document",
            "Not readable as UTF-8, so its month links were not checked; update them by hand.",
            severity="warning",
            path=relative,
        )


def _rewrites(root: Path, moved: dict[str, str]) -> tuple[list[Edit], list[dict[str, str]]]:
    """Each document a rewrite changes, and a warning for each one it could not check."""
    edits: list[Edit] = []
    skipped: list[dict[str, str]] = []
    if not moved:
        return edits, skipped
    for path in _documents(root):
        relative = _rel(root, path)
        text, problem = _read(path, relative)
        if text is None:
            if problem is not None:
                skipped.append(problem)
            continue
        new, count = _rewrite_text(text, relative.split("/")[:-1], moved, path.suffix == ".md")
        if count:
            edits.append((path, new, count))
    return edits, skipped


def _envelope(root: Path, apply: bool, **facts: Any) -> dict[str, Any]:
    ok = facts.pop("ok", True)
    return envelope(
        "month-folders",
        root,
        ok=ok,
        changes=facts.pop("changes", []),
        findings=facts.pop("findings", []),
        action=facts.pop("action", None),
        planned=not apply,
        renamed=facts.pop("renamed", 0),
        rewritten_files=facts.pop("rewritten_files", 0),
        rewritten_links=facts.pop("rewritten_links", 0),
        **facts,
    )


def _style_refusal(root: Path, apply: bool) -> dict[str, Any] | None:
    """Refuse a folder that is not a brain, one whose style is unknown, or step aside for MM."""
    config = read_config(root)
    if config is None:
        return _envelope(
            root,
            apply,
            ok=False,
            applied=False,
            findings=[finding("not-marketing-os", "This folder is not a marketing-os brain.")],
            action=next_action("onboard", "Run onboard to create the brain first."),
        )
    style, style_findings = month_folder_style(config)
    if style_findings:
        return _envelope(
            root,
            apply,
            ok=False,
            applied=False,
            findings=style_findings,
            action=next_action("fix-config", "Set month_folder to MM-Mon or MM, or remove it."),
        )
    if style == "MM":
        return _envelope(
            root,
            apply,
            applied=False,
            action=next_action(
                "none",
                'This brain keeps MM month folders (month_folder: "MM"); remove that key '
                "to move to MM-Mon, then run this again.",
            ),
        )
    return None


def _move_line(root: Path, move: Move) -> str:
    source, target, merge = move
    if merge:
        return f"merge {_rel(root, source)} into {_rel(root, target)}"
    return f"rename {_rel(root, source)} -> {_rel(root, target)}"


def _edit_lines(root: Path, edits: list[Edit]) -> list[str]:
    return [
        f"rewrite {count} link{'s' if count != 1 else ''} in {_rel(root, path)}"
        for path, _, count in edits
    ]


def _move(source: Path, target: Path, merge: bool) -> None:
    if not merge:
        source.rename(target)
        return
    for child in sorted(source.iterdir()):
        if child.name in DISPOSABLE and (target / child.name).exists():
            child.unlink()
        else:
            child.rename(target / child.name)
    source.rmdir()


def _move_all(root: Path, moves: list[Move]) -> tuple[list[Move], list[dict[str, str]]]:
    """Move in order, stopping at the first failure; the moves that happened, and why not."""
    done: list[Move] = []
    for move in moves:
        try:
            _move(*move)
        except OSError as exc:
            return done, [
                finding(
                    "month-move-failed",
                    f"Could not move it ({exc.strerror or exc}). Close any app holding "
                    "files in it open, then run this again to finish.",
                    path=_rel(root, move[0]),
                )
            ]
        done.append(move)
        with contextlib.suppress(OSError):  # losing the journal only loses crash recovery
            _record(root, move[0], move[1])
    return done, []


def _apply(root: Path, moves: list[Move]) -> dict[str, Any]:
    """Move what can be moved, then rewrite the links to every month that did move."""
    done, findings = _move_all(root, moves)
    # Links follow exactly the months that moved: this run's, and any an earlier,
    # interrupted run moved (the journal).
    edits, skipped = _rewrites(root, _moved(root, done))
    findings.extend(skipped)
    written: list[Edit] = []
    for edit in edits:
        try:
            atomic_write(edit[0], edit[1])
        except OSError:
            findings.append(
                finding(
                    "rewrite-failed",
                    "Could not rewrite its links; run this again to finish.",
                    path=_rel(root, edit[0]),
                )
            )
            continue
        written.append(edit)
    failed = any(item["severity"] == "error" for item in findings)
    if failed:
        action = next_action("rerun-fix", "Part of it did not finish; run it again to complete.")
    elif done or written:
        action = next_action("run-validate", "Month folders renamed; run validate to confirm.")
    else:
        action = next_action("none", "Every month folder is already MM-Mon; nothing to rename.")
    return _envelope(
        root,
        True,
        ok=not failed,
        applied=bool(done or written),
        changes=[_move_line(root, move) for move in done] + _edit_lines(root, written),
        findings=findings,
        action=action,
        renamed=len(done),
        rewritten_files=len(written),
        rewritten_links=sum(count for _, _, count in written),
    )


def migrate_month_folders(root: Path, apply: bool) -> dict[str, Any]:
    """Preview or apply the ``MM`` to ``MM-Mon`` month folder migration."""
    root = root.expanduser().resolve()
    refused = _style_refusal(root, apply)
    if refused is not None:
        return refused

    moves, clashes = _plan_moves(root)
    if clashes:
        return _envelope(
            root,
            apply,
            ok=False,
            applied=False,
            findings=clashes,
            action=next_action("merge-by-hand", "Resolve each clash by hand, then re-run."),
        )
    if apply:
        return _apply(root, moves)

    edits, skipped = _rewrites(root, _moved(root, moves))
    changes = [_move_line(root, move) for move in moves] + _edit_lines(root, edits)
    if changes:
        action = next_action("apply-fix", "Review the plan, then run it again with --yes.")
    else:
        action = next_action("none", "Every month folder is already MM-Mon; nothing to rename.")
    return _envelope(
        root,
        False,
        applied=False,
        changes=changes,
        findings=skipped,
        action=action,
        renamed=len(moves),
        rewritten_files=len(edits),
        rewritten_links=sum(count for _, _, count in edits),
    )
