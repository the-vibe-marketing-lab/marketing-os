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


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _script(launch_dir: Path, root: Path, command: list[str], kind: str) -> Path:
    """A launcher file that changes to the brain and starts the assistant, with the
    prompt (when there is one) quoted inside it. The prompt never reaches a Windows
    command line this way: Windows Terminal splits its own command line on ``;`` and
    ``cmd.exe`` expands ``%VAR%`` and breaks on newlines, and a prompt is prose.

    ``kind`` is ``sh`` (a POSIX script, also the macOS ``.command`` file) or ``ps1`` (a
    PowerShell script for native Windows, run with ``-ExecutionPolicy Bypass -File``).
    The file name carries a digest of the folder and the command, so two prompts for
    the same brain do not overwrite each other mid-launch.
    """
    launch_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256("\0".join([str(root), *command]).encode("utf-8")).hexdigest()[:12]
    if kind == "ps1":
        script = launch_dir / f"open-{digest}.ps1"
        body = (
            "Set-Location -LiteralPath " + _ps_quote(str(root)) + "\n"
            "& " + " ".join(_ps_quote(part) for part in command) + "\n"
        )
        script.write_text(body, encoding="utf-8")
        return script
    suffix = ".command" if sys.platform == "darwin" else ".sh"
    script = launch_dir / f"open-{digest}{suffix}"
    script.write_text(
        "#!/bin/sh\ncd "
        + _sh_quote(str(root))
        + " && exec "
        + " ".join(_sh_quote(part) for part in command)
        + "\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _plan(
    platform: str,
    root: Path,
    executable: str,
    which: Callable[[str], str | None],
    launch_dir: Path,
    prompt: str | None = None,
) -> tuple[list[str], Path | None, str] | None:
    """The argv, working directory and terminal name for one platform, or None.

    Without a prompt the argv is what it always was. With one, the assistant is started
    from a launcher file (see ``_script``) on WSL, Windows and macOS, and given the
    prompt as one argv element on Linux, where the terminal takes argv, not a string.
    """
    command = [executable] + ([prompt] if prompt else [])
    if platform == "wsl":
        if prompt:
            handoff = [
                "wsl.exe",
                "--exec",
                "/bin/sh",
                str(_script(launch_dir, root, command, "sh")),
            ]
        else:
            handoff = ["wsl.exe", "--cd", str(root), "--exec", executable]
        if which("wt.exe"):
            return (["wt.exe", *handoff], None, "Windows Terminal")
        if which("cmd.exe"):
            return (["cmd.exe", "/c", "start", "", *handoff], Path("/mnt/c"), "a console window")
        return None
    if platform == "windows":
        if prompt:
            script = _script(launch_dir, root, command, "ps1")
            start = [
                "powershell.exe",
                "-NoExit",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ]
        else:
            start = [executable]
        if which("wt.exe"):
            return (["wt.exe", "-d", str(root), *start], root, "Windows Terminal")
        if which("cmd.exe"):
            return (["cmd.exe", "/c", "start", "", *start], root, "a console window")
        return None
    if platform == "darwin":
        script = _script(launch_dir, root, command, "sh")
        return (["open", "-a", "Terminal", str(script)], root, "Terminal")
    for name, argv in (
        ("gnome-terminal", ["gnome-terminal", "--working-directory", str(root), "--", *command]),
        ("konsole", ["konsole", "--workdir", str(root), "-e", *command]),
        ("x-terminal-emulator", ["x-terminal-emulator", "-e", *command]),
        ("xterm", ["xterm", "-e", *command]),
    ):
        if which(name):
            return (argv, root, name)
    return None


def launch_repo(
    root: Path,
    runtime: str = "claude",
    *,
    prompt: str | None = None,
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
        where,
        root,
        executable,
        which,
        launch_dir or Path.home() / ".marketing-os" / "launch",
        prompt,
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
            "watch-terminal" if prompt else "type-start",
            f"{label} is opening in {terminal} with the fix already typed in. Watch it there."
            if prompt
            else f"{label} is opening in {terminal}, in this brain's folder. "
            "Type /mos-start there.",
        ),
        runtime=runtime,
        launched=True,
        prompted=bool(prompt),
        platform=where,
        terminal=terminal,
        argv=argv,
    )
