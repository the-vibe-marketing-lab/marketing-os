"""``mos fix invalid-month`` — rename legacy ``YYYY/MM`` month folders to ``YYYY/MM-Mon``.

Since 0.5.0 a brain with no ``month_folder`` key files its dated work under ``09-Sep``
rather than ``09``. A brain made before then still has ``09`` folders, and every document
that points into them. This module moves both across in one deterministic pass:

- every ``YYYY/MM`` directory under the dated trees becomes ``YYYY/MM-Mon``;
- every reference to an old path in the brain's Markdown — frontmatter ``sources:`` and
  ``related:``, ``[[wikilinks]]`` and ordinary links — is rewritten to the new one.

It never merges. If ``09-Sep`` already sits beside ``09`` the whole run is refused and
nothing is written, because deciding which copy of a month wins is a judgement call. A
brain that says ``month_folder: "MM"`` has opted out and is left alone. Running it twice
is safe: the second run finds nothing to rename and no reference left to rewrite.
"""

from __future__ import annotations

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

Rename = tuple[Path, Path]
Rewriter = tuple[re.Pattern[str], str]


def _month_folders(root: Path) -> list[Path]:
    """Every month-shaped directory (``09``, ``09-Sep``) under the dated trees."""
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


def _renames(root: Path) -> list[Rename]:
    """Every bare ``YYYY/MM`` directory under the dated trees, with its ``MM-Mon`` name."""
    return [
        (month, month.parent / _new_name(month.name))
        for month in _month_folders(root)
        if is_month_dir(month.name, "MM")
    ]


def _links(root: Path, moves: list[Rename]) -> list[tuple[str, str, str, str]]:
    """``(tree, year, MM, MM-Mon)`` for every month a reference may still name the old way.

    That is each month about to be renamed and each one already named ``MM-Mon``: an old
    reference to a month renamed by an earlier run, or by hand, still points at nothing,
    so it is carried across too. That is also what lets a run that stopped between the
    renames and the rewrites finish on the next one.
    """
    targets = [target for _, target in moves]
    targets.extend(
        month
        for month in _month_folders(root)
        if is_month_dir(month.name, "MM-Mon") and not (month.parent / month.name[:2]).exists()
    )
    return sorted(
        {
            (
                month.parent.parent.relative_to(root).as_posix(),
                month.parent.name,
                month.name[:2],
                month.name,
            )
            for month in targets
        }
    )


def _rewriters(root: Path, moves: list[Rename]) -> list[Rewriter]:
    """The substitutions that carry references across to the ``MM-Mon`` names.

    Two shapes are rewritten. A path that names the tree (``content/2026/09``, however it
    is prefixed) is rewritten wherever it stands, including a link to the month folder
    itself. A relative path that does not name the tree is rewritten only when the next
    segment is an artifact dated in that same month (``2026/09/2026-09-21-slug``), which
    is what keeps an unrelated ``2026/09`` in prose or a URL untouched. The trailing
    ``(?![\\w-])`` is what makes a second run a no-op: ``09-Sep`` never matches ``09``.
    """
    links = _links(root, moves)
    rewriters: list[Rewriter] = []
    for tree, year, number, new in links:
        pattern = rf"(?<![\w-])({re.escape(tree)}/{year}/){number}(?![\w-])"
        rewriters.append((re.compile(pattern), rf"\g<1>{new}"))
    for year, number, new in sorted({(year, number, new) for _, year, number, new in links}):
        pattern = rf"(?<![\w-])({year}/){number}(/{year}-{number}-\d{{2}}-)"
        rewriters.append((re.compile(pattern), rf"\g<1>{new}\g<2>"))
    return rewriters


def _markdown_files(root: Path) -> list[Path]:
    """The brain's Markdown, skipping hidden machinery (``.git``, ``.mos``, ``.obsidian``)."""
    return sorted(
        path
        for path in root.rglob("*.md")
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(root).parts[:-1])
    )


def _read(path: Path) -> str | None:
    """Read without newline translation, so a CRLF document is written back as CRLF."""
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def _rewrites(root: Path, rewriters: list[Rewriter]) -> list[tuple[Path, str, int]]:
    """Each Markdown file a rewrite changes, with its new text and how many links moved."""
    edits: list[tuple[Path, str, int]] = []
    for path in _markdown_files(root):
        text = _read(path)
        if text is None:
            continue
        total = 0
        for pattern, replacement in rewriters:
            text, count = pattern.subn(replacement, text)
            total += count
        if total:
            edits.append((path, text, total))
    return edits


def _refusal(
    root: Path, apply: bool, findings: list[dict[str, str]], action: dict[str, str]
) -> dict[str, Any]:
    """An envelope that wrote nothing, with the counts a caller reads set to zero."""
    return envelope(
        "month-folders",
        root,
        ok=False,
        findings=findings,
        action=action,
        applied=False,
        planned=not apply,
        renamed=0,
        rewritten_files=0,
        rewritten_links=0,
    )


def _style_refusal(root: Path, apply: bool) -> dict[str, Any] | None:
    """Refuse a folder that is not a brain, or one whose month style is unknown."""
    config = read_config(root)
    if config is None:
        return _refusal(
            root,
            apply,
            [finding("not-marketing-os", "This folder is not a marketing-os brain.")],
            next_action("onboard", "Run onboard to create the brain first."),
        )
    _, style_findings = month_folder_style(config)
    if style_findings:
        return _refusal(
            root,
            apply,
            style_findings,
            next_action("fix-config", "Set month_folder to MM-Mon or MM, or remove it."),
        )
    return None


def migrate_month_folders(root: Path, apply: bool) -> dict[str, Any]:
    """Preview or apply the ``MM`` to ``MM-Mon`` month folder migration."""
    root = root.expanduser().resolve()
    refused = _style_refusal(root, apply)
    if refused is not None:
        return refused
    style, _ = month_folder_style(read_config(root))
    if style == "MM":
        return envelope(
            "month-folders",
            root,
            ok=True,
            action=next_action(
                "none",
                'This brain keeps MM month folders (month_folder: "MM"); remove that key '
                "to move to MM-Mon, then run this again.",
            ),
            applied=False,
            planned=not apply,
            renamed=0,
            rewritten_files=0,
            rewritten_links=0,
        )

    moves = _renames(root)
    collisions = [
        finding(
            "month-folder-exists",
            f"{target.name} already exists beside {source.name}; merge them by hand, "
            "then run this again.",
            path=source.relative_to(root).as_posix(),
        )
        for source, target in moves
        if target.exists()
    ]
    if collisions:
        return _refusal(
            root,
            apply,
            collisions,
            next_action("merge-by-hand", "Merge each month into one folder, then re-run."),
        )

    rewriters = _rewriters(root, moves)
    edits = _rewrites(root, rewriters)
    changes = [
        f"rename {source.relative_to(root).as_posix()} -> {target.relative_to(root).as_posix()}"
        for source, target in moves
    ]
    changes.extend(
        f"rewrite {count} link{'s' if count != 1 else ''} in {path.relative_to(root).as_posix()}"
        for path, _, count in edits
    )

    if apply and (moves or edits):
        for source, target in moves:
            source.rename(target)
        # The files are read again after the move: one that lived in a renamed month is
        # now at its new path, and that is where its rewritten text belongs.
        edits = _rewrites(root, rewriters)
        for path, text, _ in edits:
            atomic_write(path, text)

    if not changes:
        action = next_action("none", "Every month folder is already MM-Mon; nothing to rename.")
    elif apply:
        action = next_action("run-validate", "Month folders renamed; run validate to confirm.")
    else:
        action = next_action("apply-fix", "Review the plan, then run it again with --yes.")
    return envelope(
        "month-folders",
        root,
        ok=True,
        changes=changes,
        action=action,
        applied=apply and bool(changes),
        planned=not apply,
        renamed=len(moves),
        rewritten_files=len(edits),
        rewritten_links=sum(count for _, _, count in edits),
    )
