"""The brains the local app knows about: a registry, not a filesystem sweep.

A brain becomes known when the wizard creates it, the operator opens or attaches it, or
the server is started inside it. Those facts persist in ``brains.json`` beside the app's
state file, so the sidebar can list every brain without scanning the home folder. The
first suggested place (normally the Desktop) is scanned one level deep on request so
brains sitting there appear before they have ever been opened.

The file is machine-local state, but unlike the pid file it records something the next
run cannot rebuild — which brains the operator has and when each was last opened — so it
is written with ``atomic_write`` and read with every failure treated as "nothing known".
"""

from __future__ import annotations

import datetime
import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from marketing_os.core.atomic import atomic_write
from marketing_os.ui.places import _brain_summary, _path_key, existing_brains, suggested_places
from marketing_os.ui.state import home_dir

REGISTRY_FILE = "brains.json"
REGISTRY_SCHEMA = "mos.brains.v1"
# The registry only ever grows by an operator action, so this ceiling is a safety net
# against a runaway caller, not a limit anyone should meet. Oldest ``last_opened`` goes.
MAX_ENTRIES = 200

Places = Iterable[Mapping[str, object]]


def registry_path() -> Path:
    """Where the registry lives: the same directory as ``ui.json``, honouring ``MOS_HOME``."""
    return home_dir() / REGISTRY_FILE


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _normalise(path: str | os.PathLike[str]) -> Path:
    """An absolute, normalised spelling of ``path``; relative paths hang off the cwd."""
    text = os.fspath(path).strip()
    if not text:
        raise ValueError("A brain path is required.")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return Path(os.path.normpath(str(candidate)))


def _key(path: str | Path) -> str:
    return _path_key(Path(path))


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _first_text(*candidates: object) -> str | None:
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None


def _empty() -> dict[str, Any]:
    return {"schema": REGISTRY_SCHEMA, "brains": []}


def _clean_entry(raw: object) -> dict[str, Any] | None:
    """A stored record with every field coerced to its documented type, or None."""
    if not isinstance(raw, Mapping):
        return None
    path = raw.get("path")
    if not isinstance(path, str) or not path.strip():
        return None
    last_opened = raw.get("last_opened")
    return {
        "path": path,
        "name": _first_text(raw.get("name")) or Path(path).name,
        "mode": _first_text(raw.get("mode")),
        "last_opened": last_opened if isinstance(last_opened, str) else None,
    }


def load() -> dict[str, Any]:
    """Return the registry. A missing, unreadable or malformed file is an empty registry."""
    try:
        payload = json.loads(registry_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(payload, dict):
        return _empty()
    raw_brains = payload.get("brains")
    brains: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_brains if isinstance(raw_brains, list) else []:
        entry = _clean_entry(raw)
        if entry is None:
            continue
        key = _key(entry["path"])
        if key in seen:
            continue
        seen.add(key)
        brains.append(entry)
    return {"schema": REGISTRY_SCHEMA, "brains": brains}


def _save(brains: list[dict[str, Any]]) -> dict[str, Any]:
    """Write the registry atomically, most recently opened first, capped at ``MAX_ENTRIES``."""
    ordered = sorted(brains, key=lambda brain: brain.get("last_opened") or "", reverse=True)
    payload = {"schema": REGISTRY_SCHEMA, "brains": ordered[:MAX_ENTRIES]}
    atomic_write(registry_path(), json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def _find(brains: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    return next((brain for brain in brains if _key(brain["path"]) == key), None)


def remember(
    path: str | os.PathLike[str], name: str | None = None, mode: str | None = None
) -> dict[str, Any]:
    """Record that ``path`` is a brain the operator uses, and that it was opened just now.

    The same folder spelled two ways is one entry. ``name`` and ``mode`` are taken from
    the folder's own config when not given; a folder that is not (or no longer) a brain
    keeps whatever the registry already knew, falling back to the folder name. Returns
    the registry as written. A failed write propagates and leaves the file untouched.
    """
    target = _normalise(path)
    key = _key(target)
    brains = load()["brains"]
    existing = _find(brains, key)
    summary = _brain_summary(target) if _is_dir(target) else None
    entry = {
        "path": str(target),
        "name": _first_text(
            name, summary and summary["name"], existing and existing["name"], target.name
        ),
        "mode": _first_text(mode, summary and summary["mode"], existing and existing["mode"]),
        "last_opened": _now(),
    }
    if existing is None:
        brains.append(entry)
    else:
        existing.update(entry)
    return _save(brains)


def forget(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Drop ``path`` from the registry. Returns the registry; nothing is written if absent."""
    key = _key(_normalise(path))
    registry = load()
    kept = [brain for brain in registry["brains"] if _key(brain["path"]) != key]
    if len(kept) == len(registry["brains"]):
        return registry
    return _save(kept)


def _describe(entry: dict[str, Any]) -> dict[str, Any]:
    """A registry record re-read from disk, so name, mode and flags are current."""
    target = Path(entry["path"])
    exists = _is_dir(target)
    summary = _brain_summary(target) if exists else None
    legacy = bool(summary["legacy"]) if summary else False
    return {
        "path": entry["path"],
        "name": summary["name"] if summary else entry["name"],
        "mode": summary["mode"] if summary else entry["mode"],
        "legacy": legacy,
        "attachable": legacy,
        # A folder that is still there but no longer holds a brain (its config was
        # deleted, say) must not render as a healthy brain the operator can open.
        "is_brain": summary is not None,
        "exists": exists,
        "last_opened": entry["last_opened"],
    }


def _scan_first_place(places: Places | None) -> list[dict[str, Any]]:
    """Brains at or one level below the first place only. Never raises."""
    try:
        candidates = list(suggested_places() if places is None else places)
    except Exception:
        # A broken places seam costs the scan, never the registry.
        return []
    return existing_brains(candidates[:1], max_depth=1)


def _ordered(brains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Existing first, then by name. Each pass is stable.

    Never by recency: opening a brain must not move it, or the list reshuffles under the
    hand that just pressed it (pinned 2026-09-10). ``last_opened`` still decides which
    entry the cap drops.
    """
    by_name = sorted(brains, key=lambda brain: str(brain["name"]).casefold())
    return sorted(by_name, key=lambda brain: not brain["exists"])


def known_brains(places: Places | None = None) -> list[dict[str, Any]]:
    """Every brain the app should list: the registry plus a scan of the first place.

    Registry entries whose folder is gone stay listed with ``exists`` False and their
    stored name, so the operator can see them and choose to forget them. Scanned brains
    that were never opened carry ``last_opened`` None. Deduplicated by resolved path.
    """
    brains: dict[str, dict[str, Any]] = {}
    for entry in load()["brains"]:
        brains[_key(entry["path"])] = _describe(entry)
    for found in _scan_first_place(places):
        key = _key(str(found["path"]))
        if key in brains:
            continue
        legacy = bool(found.get("legacy"))
        brains[key] = {
            "path": str(found["path"]),
            "name": found["name"],
            "mode": found["mode"],
            "legacy": legacy,
            "attachable": legacy,
            "is_brain": True,
            "exists": True,
            "last_opened": None,
        }
    return _ordered(list(brains.values()))
