"""``mos fix invalid-month`` — rename legacy ``YYYY/MM`` month folders to ``YYYY/MM-Mon``.

Since 0.5.0 a brain with no ``month_folder`` key files its dated work under ``09-Sep``
rather than ``09``. A brain made before then still has ``09`` folders, and every document
that points into them. This module moves both across in one deterministic pass.

Scope: only a bare ``MM`` directory directly inside a four-digit year folder of
``content``, ``campaigns``, ``outputs``, ``business/decisions`` or ``knowledge/sources`` is
renamed. ``reporting/`` (quarters), ``YYYY-MM`` names, files and any other folder are never
touched. When an ``MM-Mon`` folder for the same month already exists (the first
``mos ingest`` after an upgrade makes one), the two are merged, unless an entry of the same
name is in both. A folder whose name differs from ``09-Sep`` only in case (``09-sep``) is
refused rather than guessed at, because a case-insensitive disk would merge into it.

Links: ``core/monthlinks.py`` decides what is a link and rewrites only links that resolve
into a folder this command moved. Prose, headings, tables, dates and code are never touched.

Recovery: each move is journalled in ``.mos/local/month-moves.json`` before it happens and
confirmed after, one entry per child during a merge. A run that stops part-way (a file held
open on Windows, a crash) still rewrites the links for what moved, and the next run
finishes. An entry is honoured only while its old path is gone and its new path exists, and
the journal is deleted after a run that finished without an error, so a later hand rename
is never mistaken for one of these moves. A brain that says ``month_folder: "MM"`` has
opted out and is left alone. A second run changes nothing.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any

from marketing_os.core import monthlinks
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
#: The documents whose links are rewritten: notes, canvases and bases.
SUFFIXES = (".md", ".canvas", ".base")
#: Machine-local record of the moves this command makes, under ``.mos/local/``, which
#: every brain ignores.
JOURNAL = ".mos/local/month-moves.json"
JOURNAL_SCHEMA = "mos.month-moves.v2"
#: A merge drops the source's copy of these instead of calling it a clash.
DISPOSABLE = frozenset({".gitkeep"})

WARNINGS = {
    "ambiguous-link": (
        "A link here reads as two different existing paths (from this document's folder and "
        "from the brain root) and one is a moved month; it was left alone, so check it by hand."
    ),
    "backslash-link": (
        "A link here uses backslashes and points into a moved month; it was left alone, so "
        "rewrite it with forward slashes by hand."
    ),
}

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


def _plan_one(root: Path, month: Path) -> tuple[Move | None, dict[str, str] | None]:
    """How one bare month folder moves, or why it cannot.

    The year folder's real entry names are compared, not ``exists()``: on a case-insensitive
    disk ``09-Sep`` "exists" when only ``09-sep`` does, and a merge would land there.
    """
    name = _new_name(month.name)
    target = month.parent / name
    siblings = os.listdir(month.parent)
    if name not in siblings:
        twins = sorted(entry for entry in siblings if entry.lower() == name.lower())
        if twins:
            return None, finding(
                "month-folder-case",
                f"{twins[0]} differs from {name} only in case; rename it to {name} by hand, "
                "then run this again.",
                path=_rel(root, month),
            )
        return (month, target, False), None
    if not target.is_dir():
        return None, finding(
            "month-folder-exists",
            f"{name} beside {month.name} is not a folder; move it aside by hand, then run "
            "this again.",
            path=_rel(root, month),
        )
    present = set(os.listdir(target))
    both = sorted(
        child for child in os.listdir(month) if child not in DISPOSABLE and child in present
    )
    if both:
        return None, finding(
            "month-folder-exists",
            f"{name} already exists beside {month.name} and both hold {', '.join(both)}; "
            "merge those by hand, then run this again.",
            path=_rel(root, month),
        )
    return (month, target, True), None


def _plan_moves(root: Path) -> tuple[list[Move], list[dict[str, str]]]:
    """Every bare month folder's move, and a finding for each one that cannot be made."""
    moves: list[Move] = []
    problems: list[dict[str, str]] = []
    for month in _month_folders(root):
        if not is_month_dir(month.name, "MM"):
            continue
        move, problem = _plan_one(root, month)
        if move is not None:
            moves.append(move)
        if problem is not None:
            problems.append(problem)
    return moves, problems


# --- journal ----------------------------------------------------------------------------


def _journal_entries(root: Path) -> dict[str, dict[str, str]]:
    try:
        payload = json.loads((root / JOURNAL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    moves = payload.get("moves") if isinstance(payload, dict) else None
    if not isinstance(moves, dict):
        return {}
    return {
        str(old): {"new": str(entry.get("new")), "state": str(entry.get("state"))}
        for old, entry in moves.items()
        if isinstance(entry, dict) and entry.get("new")
    }


def _journal_write(root: Path, old: str, new: str, state: str) -> None:
    """Record one move's state; losing the journal only loses crash recovery."""
    with contextlib.suppress(OSError):
        entries = _journal_entries(root)
        entries[old] = {"new": new, "state": state}
        payload = {"schema": JOURNAL_SCHEMA, "moves": dict(sorted(entries.items()))}
        atomic_write(root / JOURNAL, json.dumps(payload, indent=2) + "\n")


def _journalled(root: Path) -> dict[str, str]:
    """Journal entries that describe a move that really happened: old gone, new there.

    A ``pending`` entry whose move did happen (a crash before it was confirmed) passes this
    too, which is what reconciles it; one whose move did not is ignored, and the plan
    proposes that move again.
    """
    return {
        old: entry["new"]
        for old, entry in _journal_entries(root).items()
        if not (root / old).exists() and (root / entry["new"]).exists()
    }


# --- links ------------------------------------------------------------------------------


def _moved(root: Path, moves: list[Move]) -> dict[str, str]:
    """Old path -> new path for every folder this command moves or has moved.

    A folder someone renamed by hand is not this rule's to follow, and a month folder that
    was always ``MM-Mon`` was never renamed at all, so neither is here.
    """
    moved = _journalled(root)
    moved.update({_rel(root, source): _rel(root, target) for source, target, _ in moves})
    return moved


def _exists(root: Path, moved: dict[str, str]) -> monthlinks.Exists:
    """Whether a path existed before the moves, answered before or after them."""

    def exists(relative: str) -> bool:
        if (root / relative).exists():
            return True
        parts = relative.split("/")
        for depth in range(len(parts), 0, -1):
            new = moved.get("/".join(parts[:depth]))
            if new is not None:
                return (root / new).joinpath(*parts[depth:]).exists()
        return False

    return exists


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
    """Each document a rewrite changes, and a warning for each link or file it left alone."""
    edits: list[Edit] = []
    notes: list[dict[str, str]] = []
    if not moved:
        return edits, notes
    exists = _exists(root, moved)
    for path in _documents(root):
        relative = _rel(root, path)
        text, problem = _read(path, relative)
        if text is None:
            if problem is not None:
                notes.append(problem)
            continue
        folder = relative.split("/")[:-1]
        new, count, warnings = monthlinks.rewrite(text, path.suffix, folder, moved, exists)
        notes.extend(
            finding(code, WARNINGS[code], severity="warning", path=relative)
            for code in sorted(set(warnings))
        )
        if count:
            edits.append((path, new, count))
    return edits, notes


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


def _step(root: Path, source: Path, target: Path) -> None:
    """One journalled rename: intent first, then the move, then the confirmation."""
    old, new = _rel(root, source), _rel(root, target)
    _journal_write(root, old, new, "pending")
    source.rename(target)
    _journal_write(root, old, new, "done")


def _move(root: Path, source: Path, target: Path, merge: bool, progress: list[str]) -> None:
    """Rename a month, or merge it child by child; ``progress`` names each child moved."""
    if not merge:
        _step(root, source, target)
        return
    for child in sorted(source.iterdir()):
        if child.name in DISPOSABLE and (target / child.name).exists():
            child.unlink()
            continue
        _step(root, child, target / child.name)
        progress.append(child.name)
    source.rmdir()
    _journal_write(root, _rel(root, source), _rel(root, target), "done")


def _move_all(root: Path, moves: list[Move]) -> tuple[list[str], int, list[dict[str, str]]]:
    """Move in order, stopping at the first failure: change lines, whole moves, findings."""
    lines: list[str] = []
    for count, move in enumerate(moves):
        progress: list[str] = []
        try:
            _move(root, *move, progress)
        except OSError as exc:
            if progress:
                lines.append(
                    f"{_move_line(root, move)} (partly: {len(progress)} "
                    f"entr{'y' if len(progress) == 1 else 'ies'} moved)"
                )
            return lines, count, [
                finding(
                    "month-move-failed",
                    f"Could not move it ({exc.strerror or exc}); "
                    f"{len(progress)} of its entries had already moved. Close any app holding "
                    "files in it open, then run this again to finish.",
                    path=_rel(root, move[0]),
                )
            ]
        lines.append(_move_line(root, move))
    return lines, len(moves), []


def _write(root: Path, edits: list[Edit]) -> tuple[list[Edit], list[dict[str, str]]]:
    written: list[Edit] = []
    failures: list[dict[str, str]] = []
    for edit in edits:
        try:
            atomic_write(edit[0], edit[1])
        except OSError:
            failures.append(
                finding(
                    "rewrite-failed",
                    "Could not rewrite its links; run this again to finish.",
                    path=_rel(root, edit[0]),
                )
            )
            continue
        written.append(edit)
    return written, failures


def _apply(root: Path, moves: list[Move]) -> dict[str, Any]:
    """Move what can be moved, then rewrite the links to everything that did move."""
    lines, renamed, findings = _move_all(root, moves)
    # The journal now holds exactly what moved, this run's and any interrupted run's.
    edits, notes = _rewrites(root, _moved(root, []))
    written, failures = _write(root, edits)
    findings.extend(failures)
    findings.extend(notes)
    failed = any(item["severity"] == "error" for item in findings)
    if not failed:
        # Finished: nothing is left to recover, so nothing may be mistaken for a move later.
        with contextlib.suppress(OSError):
            (root / JOURNAL).unlink(missing_ok=True)
    if failed:
        action = next_action("rerun-fix", "Part of it did not finish; run it again to complete.")
    elif lines or written:
        action = next_action("run-validate", "Month folders renamed; run validate to confirm.")
    else:
        action = next_action("none", "Every month folder is already MM-Mon; nothing to rename.")
    return _envelope(
        root,
        True,
        ok=not failed,
        applied=bool(lines or written),
        changes=lines + _edit_lines(root, written),
        findings=findings,
        action=action,
        renamed=renamed,
        rewritten_files=len(written),
        rewritten_links=sum(count for _, _, count in written),
    )


def migrate_month_folders(root: Path, apply: bool) -> dict[str, Any]:
    """Preview or apply the ``MM`` to ``MM-Mon`` month folder migration."""
    root = root.expanduser().resolve()
    refused = _style_refusal(root, apply)
    if refused is not None:
        return refused

    moves, problems = _plan_moves(root)
    if problems:
        return _envelope(
            root,
            apply,
            ok=False,
            applied=False,
            findings=problems,
            action=next_action("merge-by-hand", "Resolve each one by hand, then re-run."),
        )
    if apply:
        return _apply(root, moves)

    edits, notes = _rewrites(root, _moved(root, moves))
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
        findings=notes,
        action=action,
        renamed=len(moves),
        rewritten_files=len(edits),
        rewritten_links=sum(count for _, _, count in edits),
    )
