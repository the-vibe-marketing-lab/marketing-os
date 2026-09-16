from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from marketing_os.core.results import envelope
from marketing_os.core.schema import find_root, read_config, repo_mode
from marketing_os.core.skills import bundled_skills, inspect_runtimes

SEPARATOR = " │ "
LABEL = "MARKETINGOS"
DIVIDER_CHAR = "─"
DIVIDER_MAX = 72
DIVIDER_MIN = 10

BRAIN_KINDS = {"agency": "AGENCY BRAIN", "in-house": "IN-HOUSE BRAIN"}

# Truecolor foregrounds. Ember is the MarketingOS brand colour.
EMBER = "\x1b[38;2;201;100;66m"
GREEN = "\x1b[38;2;74;222;128m"
SLATE = "\x1b[38;2;148;163;184m"
RULE = "\x1b[38;2;71;85;105m"
RESET = "\x1b[0m"


def display_path(path: Path) -> str:
    """The path as a person reads it: the home folder shortened to ``~``."""
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        return str(path)
    if path == home:
        return "~"
    try:
        return str(Path("~") / path.relative_to(home))
    except ValueError:
        return str(path)


def statusline_repo(start: Path) -> dict[str, Any]:
    start = start.expanduser().resolve()
    root = find_root(start)
    if root is None:
        result = envelope("statusline", start, ok=True, active=False, cwd=str(start))
        result["line"] = render_badge(result)
        return result

    config = read_config(root) or {}
    business_name = str(config.get("business_name", "")).strip()
    # Resolve mode through the shared read semantics. Name the brain type only for an
    # explicit, valid mode; legacy/missing config reports mode null, and an invalid value
    # keeps the verbatim string as a fact but stays off the line.
    resolved, mode_findings = repo_mode(config)
    codes = {item["code"] for item in mode_findings}
    mode = None if "missing-mode" in codes else resolved
    show_mode = not codes & {"missing-mode", "invalid-mode"}

    total = len(bundled_skills())
    runtime = inspect_runtimes(root).get("claude", {})
    missing = runtime.get("missing", [])
    mismatched = runtime.get("mismatched", [])
    # A missing OR a stale (mismatched) skill is not installed.
    uninstalled = (len(missing) if isinstance(missing, list) else 0) + (
        len(mismatched) if isinstance(mismatched, list) else 0
    )

    result = envelope(
        "statusline",
        root,
        ok=True,
        active=True,
        cwd=str(start),
        business={"name": business_name},
        skills={"installed": total - uninstalled, "total": total},
        mode=mode,
        show_mode=show_mode,
    )
    result["line"] = render_badge(result)
    return result


def _segments(result: dict[str, Any]) -> list[list[tuple[str, str]]]:
    """The badge as coloured pieces, so plain and colour output share one layout."""
    head = [(LABEL, EMBER)]
    if not result.get("active"):
        cwd = display_path(Path(result.get("cwd") or result["repo"]))
        return [head, [("○ INACTIVE", SLATE)], [("CWD:", SLATE), (" " + cwd, "")]]
    mode = result.get("mode")
    kind = BRAIN_KINDS.get(mode, "BRAIN") if result.get("show_mode") else "BRAIN"
    brain = [(kind, EMBER)]
    name = result.get("business", {}).get("name", "")
    if name:
        brain += [(" · ", RULE), (name, "")]
    skills = result.get("skills", {})
    count = f"SKILLS {skills.get('installed', 0)}/{skills.get('total', 0)}"
    return [head, [("● ACTIVE", GREEN)], brain, [(count, SLATE)]]


def _paint(text: str, colour: str, color: bool) -> str:
    return f"{colour}{text}{RESET}" if color and colour else text


def render_badge(result: dict[str, Any], *, color: bool = False) -> str:
    separator = _paint(SEPARATOR, RULE, color)
    return separator.join(
        "".join(_paint(text, colour, color) for text, colour in segment)
        for segment in _segments(result)
    )


def divider_width(columns: str | None = None) -> int:
    raw = os.environ.get("COLUMNS", "") if columns is None else columns
    try:
        width = int(raw)
    except ValueError:
        width = DIVIDER_MAX
    return max(DIVIDER_MIN, min(width, DIVIDER_MAX))


def render_divider(*, color: bool = False, columns: str | None = None) -> str:
    return _paint(DIVIDER_CHAR * divider_width(columns), RULE, color)
