"""Opt-in wiring of the MarketingOS badge into Claude Code's status bar.

``mos statusline --install`` layers the badge on top of whatever status bar the person
already runs rather than replacing it. The previous ``statusLine`` setting is recorded
under ``~/.marketing-os/statusline.json`` and ``--chain`` runs it after the badge, so a
member's own status line keeps working underneath. ``--uninstall`` puts it back.

The same record file carries the badge's ``options`` (label, colour, what is shown), so
the installed command needs no flags for them and a member can change the look without
touching ``settings.json`` again. Uninstalling forgets the recorded status bar and keeps the
options; ``--reset`` is what drops those.

Only the user-scope ``~/.claude/settings.json`` is touched: a brain's project settings
would override a member's own status bar for everyone who opens that brain.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from marketing_os.core.results import envelope, finding, next_action

RECORD_SCHEMA = "mos.statusline-record.v2"
BADGE_ARGS = "statusline --claude --chain"
#: The spelling an earlier ``--install`` wrote, before the options file carried the look.
LEGACY_BADGE_ARGS = "statusline --claude --color --divider --chain"
CHAIN_TIMEOUT_SECONDS = 10


def settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def record_path() -> Path:
    return Path.home() / ".marketing-os" / "statusline.json"


def badge_command() -> str:
    """The status bar command, with ``mos`` resolved to a full path when it can be.

    Claude Code runs the command through a shell whose PATH may not include the folder
    ``mos`` was installed to, so a full path is the reliable spelling.
    """
    executable = running_executable() or shutil.which("mos") or "mos"
    if os.name == "nt":
        quoted = f'"{executable}"' if " " in executable else executable
    else:
        quoted = shlex.quote(executable)
    return f"{quoted} {BADGE_ARGS}"


def running_executable() -> str:
    """The ``mos`` launcher running right now, so the status bar calls this same install.

    PATH can hold an older ``mos`` ahead of the one that ran ``--install``; that one would
    not know the badge flags.
    """
    launched = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if launched is None or launched.stem.lower() != "mos":
        return ""
    found = launched if launched.is_file() else None
    if found is None and not launched.parent.name:
        which = shutil.which(launched.name)
        found = Path(which) if which else None
    return str(found.resolve()) if found else ""


def is_badge_command(value: Any) -> bool:
    """Whether a ``statusLine`` setting is ours, in this or an earlier install's spelling."""
    command = value.get("command", "") if isinstance(value, dict) else ""
    return isinstance(command, str) and (BADGE_ARGS in command or LEGACY_BADGE_ARGS in command)


def is_legacy_badge_command(value: Any) -> bool:
    command = value.get("command", "") if isinstance(value, dict) else ""
    return isinstance(command, str) and LEGACY_BADGE_ARGS in command


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return {}, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError) as exc:
        return None, f"{path} is not readable JSON: {exc}"
    if not isinstance(data, dict):
        return None, f"{path} does not hold a JSON object."
    return data, ""


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read_record() -> dict[str, Any]:
    """The record file as a dict; an unreadable or absent file reads as empty."""
    record, _ = _read_json(record_path())
    return record or {}


_UNSET: Any = object()


def write_record(*, previous: Any = _UNSET, options: dict[str, Any] | None = None) -> None:
    """Write the record, or remove the file when nothing is left to record.

    ``previous`` is kept even when it is ``None``: that records an install over no status
    bar at all, which is different from never having installed.
    """
    record: dict[str, Any] = {}
    if previous is not _UNSET:
        record["previous"] = previous
    if options:
        record["options"] = options
    if not record:
        if record_path().exists():
            record_path().unlink()
        return
    _write_json(record_path(), {"schema": RECORD_SCHEMA, **record})


def rewrite_record_options(options: dict[str, Any] | None) -> None:
    """Replace the saved options and leave the recorded status bar, if any, as it is."""
    record = read_record()
    if "previous" in record:
        write_record(previous=record["previous"], options=options)
    else:
        write_record(options=options)


def _backup(path: Path) -> Path:
    # Microseconds plus a counter, so a second backup never overwrites the first.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = path.with_name(f"{path.name}.mos-backup-{stamp}")
    counter = 1
    while target.exists():
        target = path.with_name(f"{path.name}.mos-backup-{stamp}-{counter}")
        counter += 1
    shutil.copy2(path, target)
    return target


def _result(
    ok: bool, operation: str, changes: list[str], applied: bool, **facts: Any
) -> dict[str, Any]:
    findings = facts.pop("findings", None)
    action = facts.pop("action", None)
    if action is None and changes and not applied:
        action = next_action("apply", "Review the changes, then run the same command with --yes.")
    return envelope(
        "statusline",
        settings_path().parent,
        ok=ok,
        changes=changes,
        findings=findings,
        action=action,
        operation=operation,
        applied=applied and bool(changes),
        settings=str(settings_path()),
        record=str(record_path()),
        **facts,
    )


def _unreadable(operation: str, message: str) -> dict[str, Any]:
    return _result(
        False,
        operation,
        [],
        False,
        findings=[finding("settings-unreadable", message)],
        action=next_action("review-settings", "Fix the JSON file, then run the command again."),
    )


def _upgrade_statusline(settings: dict[str, Any], current: dict[str, Any], *, apply: bool):
    """Rewrite an earlier install's command to the current spelling; the record stays."""
    command = badge_command()
    new_line = {**current, "command": command}
    changes = [f"back up {settings_path()}", f"update statusLine.command to: {command}"]
    if apply:
        _backup(settings_path())
        settings["statusLine"] = new_line
        _write_json(settings_path(), settings)
    return _result(
        True,
        "install",
        changes,
        apply,
        installed=True,
        status_command=command,
        previous=read_record().get("previous"),
    )


def install_statusline(*, apply: bool) -> dict[str, Any]:
    settings, error = _read_json(settings_path())
    if settings is None:
        return _unreadable("install", error)
    current = settings.get("statusLine")
    if is_legacy_badge_command(current):
        return _upgrade_statusline(settings, current, apply=apply)
    if is_badge_command(current):
        return _result(
            True, "install", [], apply, installed=True, status_command=current["command"]
        )

    command = badge_command()
    new_line: dict[str, Any] = {"type": "command", "command": command}
    if isinstance(current, dict) and "padding" in current:
        new_line["padding"] = current["padding"]
    changes = []
    if settings_path().exists():
        changes.append(f"back up {settings_path()}")
    changes.append(f"record the current status bar in {record_path()}")
    changes.append(f"set statusLine.command to: {command}")
    if apply:
        if settings_path().exists():
            _backup(settings_path())
        write_record(previous=current, options=read_record().get("options"))
        settings["statusLine"] = new_line
        _write_json(settings_path(), settings)
    return _result(
        True, "install", changes, apply, installed=apply, status_command=command, previous=current
    )


def uninstall_statusline(*, apply: bool) -> dict[str, Any]:
    settings, error = _read_json(settings_path())
    if settings is None:
        return _unreadable("uninstall", error)
    record = read_record()
    has_previous = "previous" in record
    ours = is_badge_command(settings.get("statusLine"))
    if not ours and not has_previous:
        return _result(True, "uninstall", [], apply, installed=False)

    changes: list[str] = []
    findings = []
    previous = record.get("previous")
    if ours:
        changes.append(f"back up {settings_path()}")
        if previous is None:
            changes.append("remove statusLine from the settings")
        else:
            changes.append(f"restore the previous status bar: {previous}")
    else:
        findings.append(
            finding(
                "statusline-changed",
                "The status bar was changed after the badge was installed; it is left alone.",
                severity="warning",
            )
        )
    if has_previous:
        if record.get("options"):
            changes.append(f"forget the recorded status bar in {record_path()} (options kept)")
        else:
            changes.append(f"delete {record_path()}")
    if apply:
        if ours:
            _backup(settings_path())
            if previous is None:
                settings.pop("statusLine", None)
            else:
                settings["statusLine"] = previous
            _write_json(settings_path(), settings)
        if has_previous:
            write_record(options=record.get("options"))
    return _result(
        True,
        "uninstall",
        changes,
        apply,
        installed=ours and not apply,
        findings=findings,
        previous=previous,
    )


def chained_command() -> str:
    previous = read_record().get("previous")
    if not isinstance(previous, dict) or is_badge_command(previous):
        return ""
    command = previous.get("command")
    return command if isinstance(command, str) else ""


def run_chained(stdin: bytes) -> bytes:
    """Run the recorded status bar with the same stdin and return what it printed.

    The recorded value is a shell command line the person configured for Claude Code,
    which Claude Code itself runs through a shell, so it is run the same way. Any
    failure returns nothing: the badge must never break because the old bar did.
    """
    command = chained_command()
    if not command:
        return b""
    try:
        completed = subprocess.run(
            command,
            shell=True,
            input=stdin,
            capture_output=True,
            timeout=CHAIN_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return b""
    return completed.stdout or b""
