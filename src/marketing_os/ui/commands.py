"""The allowlist that turns a browser request into a real ``mos`` argv list.

The UI is a client of the CLI, never a second implementation. Every action names an
allowlisted command and a flat bag of arguments; this module turns that into the exact
argv a person would type, which the server both dispatches and shows back to them.
Anything not described here is rejected before it can reach the parser.

An option is two argv elements, so its value can never be read as a flag. A positional is
one, so it can: a ``path`` of ``--yes`` would otherwise arrive at the parser as the
approval flag itself, and because an accepted flag also shifts what the remaining
positionals mean, one injected value can change both the gate and the target. Two
defences, either of which is sufficient, close that:

* Every positional value is refused if it begins with ``-``. ``argparse`` only ever reads
  an argument as an option when it begins with a prefix character, so a value that cannot
  begin with one cannot become a flag.
* Options and flags are emitted first, then ``--``, then the positionals. ``argparse``
  reads everything after ``--`` as a value, which was verified against this parser for
  every allowlisted command rather than assumed.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CommandError(ValueError):
    """A request that must never reach the CLI parser.

    ``code`` is the envelope finding the server answers with: ``command-not-allowed`` for
    a request outside the allowlist, ``bad-path`` for a target that is not a full path.
    """

    def __init__(self, message: str, *, code: str = "command-not-allowed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CommandSpec:
    """How one allowlisted command maps a flat argument bag onto argv."""

    argv: tuple[str, ...]
    positionals: tuple[str, ...] = ()
    options: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    required: tuple[str, ...] = ()


_MUTATION = ("plan", "yes")

#: End of options. Everything after it is a value, whatever it looks like.
SEPARATOR = "--"

COMMANDS: dict[str, CommandSpec] = {
    "status": CommandSpec(("status",), positionals=("path",)),
    "validate": CommandSpec(("validate",), positionals=("path",), flags=("strict",)),
    "doctor": CommandSpec(("doctor",), positionals=("path",)),
    "statusline": CommandSpec(("statusline",), positionals=("path",)),
    "install": CommandSpec(
        ("install",), options=("runtime",), flags=(*_MUTATION, "no-ui")
    ),
    "onboard": CommandSpec(
        ("onboard",),
        positionals=("path",),
        options=("name", "mode", "agency", "hq", "runtime"),
        flags=_MUTATION,
    ),
    "skills sync": CommandSpec(
        ("skills", "sync"), positionals=("path",), options=("runtime",), flags=_MUTATION
    ),
    "assist status": CommandSpec(("assist", "status")),
    "assist ask": CommandSpec(
        ("assist", "ask"),
        positionals=("path",),
        options=("field", "transcript-json"),
        required=("field",),
    ),
    "index build": CommandSpec(("index", "build"), positionals=("path",)),
    "index sync": CommandSpec(("index", "sync"), positionals=("path",), flags=_MUTATION),
    "index status": CommandSpec(("index", "status"), positionals=("path",)),
    "rename": CommandSpec(
        ("rename",), positionals=("path",), options=("name",), flags=_MUTATION
    ),
    "related": CommandSpec(
        ("related",), positionals=("path",), options=("limit",), flags=_MUTATION
    ),
    "query": CommandSpec(
        ("query",),
        positionals=("question", "path"),
        options=("limit",),
        flags=("grep",),
        required=("question",),
    ),
    "think": CommandSpec(("think",), positionals=("topic", "path"), required=("topic",)),
    "context show": CommandSpec(("context", "show"), positionals=("path",)),
    "context set": CommandSpec(
        ("context", "set"),
        positionals=("path",),
        options=("field", "text", "slug"),
        flags=_MUTATION,
        required=("field", "text"),
    ),
    "ingest": CommandSpec(
        ("ingest",),
        positionals=("source", "path"),
        options=("topic", "slug", "date"),
        flags=("pending", *_MUTATION),
    ),
    "attach": CommandSpec(
        ("attach",),
        positionals=("path",),
        options=("name", "mode", "runtime"),
        flags=_MUTATION,
    ),
    "migrate": CommandSpec(
        ("migrate",), positionals=("path",), options=("plan-file",), flags=_MUTATION
    ),
    "update": CommandSpec(("update",), flags=_MUTATION),
}


def allowlist() -> tuple[str, ...]:
    return tuple(sorted(COMMANDS))


def describe() -> list[dict[str, Any]]:
    """The allowlist as data, so the UI can render controls without hardcoding it."""
    return [
        {
            "command": name,
            "positionals": list(spec.positionals),
            "options": list(spec.options),
            "flags": list(spec.flags),
            "required": list(spec.required),
            "mutating": bool(set(spec.flags) & set(_MUTATION)),
        }
        for name, spec in sorted(COMMANDS.items())
    ]


def _scalar(name: str, value: Any) -> str:
    if isinstance(value, bool) or value is None:
        raise CommandError(f"argument {name!r} must be a string or number")
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    raise CommandError(f"argument {name!r} must be a string or number")


def _positional(name: str, value: Any) -> str:
    """One positional value, refused outright if it is shaped like a flag.

    The Commands tab renders a free-text box for every positional, so this is reachable by
    typing rather than only by a crafted request. An option's value needs no such check:
    ``--field`` and its value are two argv elements, and the second is never read as a flag.
    """
    text = _scalar(name, value)
    if text.startswith("-"):
        raise CommandError(
            f"argument {name!r} must not begin with '-'; it is a value, not a flag"
        )
    if name == "path" and not Path(text).expanduser().is_absolute():
        # The CLI resolves a relative path against its own cwd, which for the app is
        # wherever the server was started: a Windows spelling such as ``C:/Users/x``
        # would silently land inside that folder. Only a full path names a folder.
        raise CommandError(
            f"argument {name!r} must be a full path, starting from the top of the drive",
            code="bad-path",
        )
    return text


def _given(args: dict[str, Any], name: str) -> bool:
    value = args.get(name)
    if value is None:
        return False
    return not (isinstance(value, str) and not value.strip())


def build_argv(command: Any, args: Any = None) -> list[str]:
    """Turn an allowlisted command plus a flat argument bag into a real argv list.

    The layout is ``<command> <options> <flags> -- <positionals>``, which is what keeps a
    positional value from being read as an approval flag. See the module docstring.
    """
    if not isinstance(command, str):
        raise CommandError("command must be a string")
    spec = COMMANDS.get(command)
    if spec is None:
        raise CommandError(f"command {command!r} is not allowlisted")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise CommandError("args must be an object")

    known = set(spec.positionals) | set(spec.options) | set(spec.flags)
    unknown = sorted(str(key) for key in args if key not in known)
    if unknown:
        raise CommandError(f"{command!r} does not accept: {', '.join(unknown)}")

    missing = [name for name in spec.required if not _given(args, name)]
    if missing:
        raise CommandError(f"{command!r} requires: {', '.join(missing)}")
    if set(_MUTATION) <= set(spec.flags) and all(args.get(name) is True for name in _MUTATION):
        raise CommandError(f"{command!r} takes exactly one of plan or yes")

    argv = list(spec.argv)
    for name in spec.options:
        if _given(args, name):
            argv.extend([f"--{name}", _scalar(name, args[name])])
    for name in spec.flags:
        if args.get(name) is True:
            argv.append(f"--{name}")

    positionals: list[str] = []
    skipped: str | None = None
    for name in spec.positionals:
        if not _given(args, name):
            skipped = name
            continue
        if skipped is not None:
            raise CommandError(f"{command!r} needs {skipped!r} before {name!r}")
        positionals.append(_positional(name, args[name]))
    if positionals:
        # Options come first so this separator has only values after it. Put it before the
        # options instead and argparse reads --field itself as a positional.
        argv.append(SEPARATOR)
        argv.extend(positionals)
    return argv


def command_line(argv: list[str]) -> str:
    """The copy-pasteable terminal equivalent of a dispatched argv list.

    Quoted for the shell on this machine. ``shlex`` speaks POSIX, where a backslash is an
    escape, so it would wrap every Windows path in single quotes that neither cmd.exe nor
    PowerShell reads as a path. On Windows ``list2cmdline`` follows the CreateProcess rules
    both of them accept instead — closer to what the shell wants, not shell-safe: it quotes
    spaces and quotes, and leaves cmd's own metacharacters such as ``&`` and ``%`` alone.
    """
    if sys.platform == "win32":
        return "mos " + subprocess.list2cmdline(argv)
    return "mos " + shlex.join(argv)
