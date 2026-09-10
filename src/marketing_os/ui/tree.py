"""The brain's folder, two levels deep, with each entry marked by who put it there.

The overview's quick action shows the operator what MarketingOS set up against what they
or their assistant added. An entry is MarketingOS's when the same relative path exists in
the scaffold template or a mode overlay (agency mode adds ``business/clients``), when it
sits under one of the assistant machinery folders or is a git setup file at the root, or
when it is a navigation file ``mos index sync`` writes. Everything else is theirs. The walk stops at two levels, never enters ``.git``, lists the
machinery folders without opening them, and never follows a symlink.
"""

from __future__ import annotations

import os
from pathlib import Path

from marketing_os.core.schema import overlay_root, template_root

TREE_SCHEMA = "mos.tree.v1"
# Assistant machinery: each listed as one folder with a count, never opened.
MACHINERY = {".claude", ".agents", ".obsidian", ".mos", ".codex"}
# Written by the scaffold at the root, outside the template's own tree.
SETUP_FILES = {".gitignore", ".gitattributes"}
# Written by ``mos index sync``, wherever they land.
GENERATED = {"_index.md", "_log.md"}


def _origin(rel: str) -> str:
    first, _, _rest = rel.partition("/")
    name = rel.rsplit("/", 1)[-1]
    if first in MACHINERY or first in SETUP_FILES or name in GENERATED:
        return "marketing-os"
    return "marketing-os" if any((base / rel).exists() for base in _scaffold_roots()) else "yours"


def _scaffold_roots() -> list[Path]:
    """The template plus every mode overlay: what ``mos onboard`` can lay down."""
    overlays = overlay_root()
    modes = sorted(p for p in overlays.iterdir() if p.is_dir()) if overlays.is_dir() else []
    return [template_root(), *modes]


def _count(path: str) -> int:
    try:
        with os.scandir(path) as it:
            return sum(1 for _ in it)
    except OSError:
        return 0


def _listing(path: Path) -> list[os.DirEntry[str]]:
    """Folders first, then names casefolded; ``.git`` is never part of the picture."""
    try:
        with os.scandir(path) as it:
            entries = [entry for entry in it if entry.name != ".git"]
    except OSError:
        return []
    entries.sort(key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.casefold()))
    return entries


def describe_tree(root: Path, depth: int = 2) -> dict[str, object]:
    """The entries under ``root`` to ``depth`` levels, root's children being level 1."""
    entries: list[dict[str, object]] = []

    def walk(folder: Path, prefix: str, level: int) -> None:
        for entry in _listing(folder):
            rel = prefix + entry.name
            is_dir = entry.is_dir(follow_symlinks=False)
            item: dict[str, object] = {
                "path": rel,
                "kind": "dir" if is_dir else "file",
                "origin": _origin(rel),
            }
            if is_dir:
                item["children"] = _count(entry.path)
            entries.append(item)
            if is_dir and level < depth and entry.name not in MACHINERY:
                walk(Path(entry.path), rel + "/", level + 1)

    walk(root, "", 1)
    return {"schema": TREE_SCHEMA, "root": str(root), "entries": entries}
