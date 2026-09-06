"""Open an assistant in a brain's folder, in a new terminal window.

The operator has Claude Code or Codex on this computer already (the assist engine
proved as much); what they do not have is a way to get from the local app into it
without typing. This opens their terminal in the brain's folder running the assistant.

Never a shell: fixed argv, the executable resolved with ``shutil.which``, nothing
interpolated into a command string. The only thing taken from the caller is the folder,
and it has to be a brain. Each platform gets the terminal it has:

* WSL: Windows Terminal when it is on the PATH, else a console window from ``cmd.exe``,
  both handing off to ``wsl.exe --cd <folder> --exec <assistant>``.
* Windows: Windows Terminal, else a console window.
* macOS: Terminal.app opening a one-line ``.command`` file written under ``~/.marketing-os``.
* Linux: the first of gnome-terminal, konsole, x-terminal-emulator, xterm that is installed.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import read_config

RUNTIME_LABELS = {"claude": "Claude Code", "codex": "Codex"}


def detect_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    try:
        version = Path("/proc/version").read_text(encoding="utf-8", errors="replace")
    except OSError:
        version = ""
    return "wsl" if "microsoft" in version.lower() else "linux"


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _plan(
    platform: str, root: Path, executable: str, which: Callable[[str], str | None], launch_dir: Path
) -> tuple[list[str], Path | None, str] | None:
    """The argv, working directory and terminal name for one platform, or None."""
    if platform == "wsl":
        handoff = ["wsl.exe", "--cd", str(root), "--exec", executable]
        if which("wt.exe"):
            return (["wt.exe", *handoff], None, "Windows Terminal")
        if which("cmd.exe"):
            return (["cmd.exe", "/c", "start", "", *handoff], Path("/mnt/c"), "a console window")
        return None
    if platform == "windows":
        if which("wt.exe"):
            return (["wt.exe", "-d", str(root), executable], root, "Windows Terminal")
        if which("cmd.exe"):
            return (["cmd.exe", "/c", "start", "", executable], root, "a console window")
        return None
    if platform == "darwin":
        launch_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
        script = launch_dir / f"open-{digest}.command"
        script.write_text(
            "#!/bin/sh\ncd " + _sh_quote(str(root)) + " && exec " + _sh_quote(executable) + "\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        return (["open", "-a", "Terminal", str(script)], root, "Terminal")
    for name, argv in (
        ("gnome-terminal", ["gnome-terminal", "--working-directory", str(root), "--", executable]),
        ("konsole", ["konsole", "--workdir", str(root), "-e", executable]),
        ("x-terminal-emulator", ["x-terminal-emulator", "-e", executable]),
        ("xterm", ["xterm", "-e", executable]),
    ):
        if which(name):
            return (argv, root, name)
    return None


def launch_repo(
    root: Path,
    runtime: str = "claude",
    *,
    platform: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    popen: Callable[..., Any] = subprocess.Popen,
    launch_dir: Path | None = None,
) -> dict[str, Any]:
    root = root.expanduser().resolve()
    label = RUNTIME_LABELS.get(runtime, runtime)
    findings: list[dict[str, str]] = []
    if runtime not in RUNTIME_LABELS:
        findings.append(finding("invalid-runtime", "Runtime must be claude or codex."))
    if read_config(root) is None:
        findings.append(
            finding("not-marketing-os", "This is not a marketing-os business repository.")
        )
    executable = which(runtime) if not findings else None
    if not findings and not executable:
        findings.append(
            finding(
                "runtime-not-found",
                f"{label} is not installed on this computer, or is not on the PATH.",
            )
        )
    if findings:
        return envelope(
            "open",
            root,
            ok=False,
            findings=findings,
            action=next_action(
                "open-by-hand", "Open a terminal in the folder and start it yourself."
            ),
            runtime=runtime,
            launched=False,
        )

    assert executable is not None  # narrowed above
    where = platform or detect_platform()
    plan = _plan(
        where, root, executable, which, launch_dir or Path.home() / ".marketing-os" / "launch"
    )
    if plan is None:
        return envelope(
            "open",
            root,
            ok=False,
            findings=[finding("no-terminal", "No terminal program was found to open.")],
            action=next_action(
                "open-by-hand", "Open a terminal in the folder and start it yourself."
            ),
            runtime=runtime,
            launched=False,
            platform=where,
        )
    argv, cwd, terminal = plan
    try:
        popen(  # noqa: S603 - fixed argv, resolved executable, no shell
            argv,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        return envelope(
            "open",
            root,
            ok=False,
            findings=[finding("launch-failed", f"The terminal could not be opened: {error}.")],
            action=next_action(
                "open-by-hand", "Open a terminal in the folder and start it yourself."
            ),
            runtime=runtime,
            launched=False,
            platform=where,
            terminal=terminal,
        )
    return envelope(
        "open",
        root,
        ok=True,
        action=next_action(
            "type-start",
            f"{label} is opening in {terminal}, in this brain's folder. Type /mos-start there.",
        ),
        runtime=runtime,
        launched=True,
        platform=where,
        terminal=terminal,
        argv=argv,
    )
