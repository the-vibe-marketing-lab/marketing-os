"""The badge's look, saved as options a member changes with ``mos statusline --set``.

Options live under ``options`` in the same ``~/.marketing-os/statusline.json`` record the
install writes, so the installed status bar command carries no flags for them: change an
option and the bar picks it up on its next redraw. They are saved whether or not the badge
is installed, so a member can set the look first and switch the bar on later.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.statusline import (
    HEX_COLOUR,
    LABEL_MAX,
    OPTION_DEFAULTS,
    POSITIONS,
    render_badge,
    render_divider,
    statusline_repo,
)
from marketing_os.core.statusline_install import (
    _read_json,
    is_badge_command,
    read_record,
    record_path,
    rewrite_record_options,
    settings_path,
)

TRUE_WORDS = {"true", "yes", "on", "1"}
FALSE_WORDS = {"false", "no", "off", "0"}
BOOL_KEYS = ("color", "divider", "show_name", "show_skills", "show_cwd")


def parse_bool(raw: str) -> bool | None:
    word = raw.strip().lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    return None


def _check(key: str, raw: str) -> tuple[Any, str]:
    """The typed value for one option, or the reason the text is not one."""
    if key in BOOL_KEYS:
        value = parse_bool(raw)
        return value, "" if value is not None else "must be true or false"
    if key == "label":
        clean = raw.strip()
        if not clean or len(clean) > LABEL_MAX or not clean.isprintable():
            return None, f"must be 1 to {LABEL_MAX} printable characters"
        return clean, ""
    if key == "accent":
        if not HEX_COLOUR.match(raw.strip()):
            return None, "must be a hex colour like #c96442"
        return raw.strip().lower(), ""
    if key == "position":
        word = raw.strip().lower()
        return word, "" if word in POSITIONS else "must be top or bottom"
    return None, "is not an option"


def parse_pairs(pairs: list[str]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Validate ``KEY=VALUE`` pairs into typed options, naming every bad one."""
    values: dict[str, Any] = {}
    findings: list[dict[str, str]] = []
    for pair in pairs:
        key, separator, raw = pair.partition("=")
        key = key.strip().lower().replace("-", "_")
        if not separator or not key:
            findings.append(finding("invalid-option", f"{pair!r} is not KEY=VALUE."))
            continue
        if key not in OPTION_DEFAULTS:
            findings.append(
                finding(
                    "unknown-option",
                    f"{key} is not an option; choose from {', '.join(OPTION_DEFAULTS)}.",
                )
            )
            continue
        value, problem = _check(key, raw)
        if problem:
            findings.append(finding("invalid-option", f"{key} {problem}: {raw!r}."))
            continue
        values[key] = value
    return values, findings


def saved_options() -> dict[str, Any]:
    """The options in the record, keeping only the ones that are still valid.

    A hand-edited value that no longer parses is dropped rather than failing: the badge
    is drawn on every redraw and must never break over its own record.
    """
    raw = read_record().get("options")
    if not isinstance(raw, dict):
        return {}
    kept: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in OPTION_DEFAULTS:
            continue
        typed, problem = _check(key, value if isinstance(value, str) else str(value))
        if not problem:
            kept[key] = typed
    return kept


def effective_options(pending: dict[str, Any] | None = None) -> dict[str, Any]:
    return {**OPTION_DEFAULTS, **saved_options(), **(pending or {})}


def badge_installed() -> bool:
    settings, _ = _read_json(settings_path())
    return bool(settings) and is_badge_command(settings.get("statusLine"))


def _result(operation: str, *, ok: bool = True, changes=None, applied=False, **facts: Any):
    findings = facts.pop("findings", None)
    action = facts.pop("action", None)
    if action is None and changes and not applied:
        action = next_action("apply", "Review the changes, then run the same command with --yes.")
    return envelope(
        "statusline",
        settings_path().parent,
        ok=ok,
        changes=changes or [],
        findings=findings,
        action=action,
        operation=operation,
        applied=applied and bool(changes),
        installed=badge_installed(),
        record=str(record_path()),
        defaults=dict(OPTION_DEFAULTS),
        **facts,
    )


def show_options() -> dict[str, Any]:
    saved = saved_options()
    return _result("options", options={**OPTION_DEFAULTS, **saved}, saved=saved)


def _invalid(operation: str, findings: list[dict[str, str]], **facts: Any) -> dict[str, Any]:
    return _result(
        operation,
        ok=False,
        findings=findings,
        action=next_action("review-options", "Fix the named option, then run the command again."),
        options=effective_options(),
        **facts,
    )


def set_options(pairs: list[str], *, apply: bool) -> dict[str, Any]:
    pending, findings = parse_pairs(pairs)
    if findings:
        return _invalid("set", findings, pending={})
    saved = saved_options()
    current = {**OPTION_DEFAULTS, **saved}
    changes = [
        f"set {key}: {current[key]!r} -> {value!r}"
        for key, value in pending.items()
        if current[key] != value
    ]
    merged = {**saved, **pending}
    if apply and changes:
        rewrite_record_options(merged)
    return _result(
        "set",
        changes=changes,
        applied=apply,
        options={**OPTION_DEFAULTS, **merged},
        saved=merged if apply else saved,
        pending=pending,
    )


def reset_options(*, apply: bool) -> dict[str, Any]:
    saved = saved_options()
    changes = [f"remove the saved options from {record_path()}"] if saved else []
    if apply and changes:
        rewrite_record_options(None)
    return _result(
        "reset",
        changes=changes,
        applied=apply,
        options=dict(OPTION_DEFAULTS),
        saved={} if apply else saved,
    )


def preview_badge(path: Path, pairs: list[str]) -> dict[str, Any]:
    """The badge as the installed command would draw it, with any ``--set`` pairs applied
    for this render only. Nothing is written."""
    pending, findings = parse_pairs(pairs)
    if findings:
        return _invalid("preview", findings, pending={})
    options = effective_options(pending)
    result = statusline_repo(path, options=options)
    color = bool(options["color"])
    lines = [render_badge(result, color=color, options=options)]
    if options["divider"]:
        lines.append(render_divider(color=color))
    result.update(
        operation="preview",
        options=options,
        pending=pending,
        installed=badge_installed(),
        rendered="\n".join(lines),
    )
    return result
