"""The operating system's own "choose a folder" window, opened on the page's behalf.

A browser page cannot learn an absolute path from a file input, so the local app opens
the native dialog itself — Explorer under Windows and WSL, Finder on a Mac, zenity or
kdialog or Tk on Linux — and hands the chosen folder back. Every backend is best-effort:
a missing binary, a closed display, a timeout or a crash all come back as a plain
answer the page can act on, never as an exception.
"""

from __future__ import annotations

import base64
import importlib.util
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marketing_os.ui.places import _is_wsl, _stdout_line

# Two minutes: long enough to find a folder, short enough that a window left open
# behind the browser is not a request hanging for the rest of the session.
DEFAULT_TIMEOUT = 120
PROMPT = "Choose the folder your business brain should live in"
_CONVERT_TIMEOUT = 5

Run = Callable[..., subprocess.CompletedProcess[str]]
Which = Callable[[str], str | None]

# One dialog at a time: a second click while the first window is open must not stack
# a second window behind it.
_BUSY = threading.Lock()


@dataclass(frozen=True)
class Host:
    """The facts about this machine that decide which dialog can open."""

    platform: str
    wsl: bool
    display: bool
    which: Which
    tkinter: bool
    # WSL can see powershell.exe on PATH and still be unable to run it: interop is a
    # binfmt registration, and a shell without it gets "Exec format error" instead.
    interop: bool = True


_BINFMT = Path("/proc/sys/fs/binfmt_misc")


def _wsl_interop_enabled() -> bool:
    """Whether Windows executables can actually be run from here. No evidence means yes."""
    try:
        entries = [entry.name for entry in _BINFMT.iterdir()]
    except OSError:
        return True
    return any(name.startswith("WSLInterop") for name in entries)


def host(
    *,
    env: Mapping[str, str] | None = None,
    which: Which = shutil.which,
    platform: str | None = None,
    proc_version: str | None = None,
) -> Host:
    environment = os.environ if env is None else env
    return Host(
        platform=platform or sys.platform,
        wsl=_is_wsl(environment, proc_version),
        display=bool(environment.get("DISPLAY") or environment.get("WAYLAND_DISPLAY")),
        which=which,
        tkinter=importlib.util.find_spec("tkinter") is not None,
        interop=_wsl_interop_enabled(),
    )


def backend_for(machine: Host) -> str | None:
    """The first backend that can open on this machine, or None when none can."""
    which = machine.which
    if machine.wsl and machine.interop and which("powershell.exe"):
        return "wsl"
    if machine.platform.startswith("win"):
        return "windows" if (which("powershell") or which("pwsh")) else None
    if machine.platform == "darwin":
        return "macos" if which("osascript") else None
    if not machine.display:
        return None
    for name in ("zenity", "kdialog"):
        if which(name):
            return name
    return "tkinter" if machine.tkinter else None


def picker_available(machine: Host | None = None) -> bool:
    """A cheap probe for app state: can a folder window open here at all?"""
    try:
        return backend_for(machine or host()) is not None
    except Exception:
        return False


def pick_folder(
    start: Path | str | None,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    run: Run = subprocess.run,
    machine: Host | None = None,
) -> dict[str, Any]:
    """Open the native folder window and wait for an answer.

    Returns ``{"path", "cancelled", "available", "busy", "error", "backend"}``. ``path``
    is set only when a folder was chosen; ``cancelled`` when the operator closed the
    window, or left it unanswered past ``timeout`` (``error`` then says so); ``busy``
    when a window is already open and this call opened nothing; ``available`` is False
    when no window could open at all, with ``error`` saying why.
    """
    backend = backend_for(machine or host())
    if backend is None:
        return _result("none", available=False, error="No folder window can open here.")
    if not _BUSY.acquire(blocking=False):
        return _result(
            backend, busy=True, error="A folder window is already open. Finish with that one."
        )
    try:
        return _BACKENDS[backend](_start_dir(start), timeout=timeout, run=run)
    except subprocess.TimeoutExpired:
        # The window opened and nobody answered it: that is a cancel, not a machine that
        # cannot open one, so the page must not fall back to its in-page list.
        return _result(
            backend,
            cancelled=True,
            error=f"The folder window did not answer within {timeout} seconds.",
        )
    except Exception as exc:
        return _result(backend, available=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        _BUSY.release()


# --- shared -----------------------------------------------------------------------------


def _result(
    backend: str,
    *,
    path: str | None = None,
    cancelled: bool = False,
    available: bool = True,
    busy: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "path": path,
        "cancelled": cancelled,
        "available": available,
        "busy": busy,
        "error": error,
        "backend": backend,
    }


def _start_dir(start: Path | str | None) -> str | None:
    """The nearest existing directory at or above the requested start, if any."""
    if start is None or not str(start).strip():
        return None
    candidate = Path(str(start).strip()).expanduser()
    for node in (candidate, *candidate.parents):
        try:
            if node.is_dir():
                return str(node)
        except OSError:
            continue
    return None


def _call(run: Run, argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return run(
        argv,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _chosen(result: subprocess.CompletedProcess[str]) -> str:
    """The path a dialog printed, stripped of the BOM and newline that consoles add."""
    stdout = result.stdout if isinstance(result.stdout, str) else ""
    return stdout.lstrip("\ufeff").strip()


def _finish(
    backend: str, result: subprocess.CompletedProcess[str], *, cancel_codes: tuple[int, ...] = (1,)
) -> dict[str, Any]:
    """The common outcome shape: a path, a cancel, or the dialog's own error text."""
    chosen = _chosen(result)
    if result.returncode == 0 and chosen:
        return _result(backend, path=chosen)
    if result.returncode == 0 or result.returncode in cancel_codes:
        return _result(backend, cancelled=True)
    detail = (result.stderr or "").strip().splitlines()
    error = detail[-1] if detail else f"exit status {result.returncode}"
    return _result(backend, error=f"The folder window failed: {error}")


# --- Windows and WSL: PowerShell + WinForms ----------------------------------------------


def powershell_script(start: str | None) -> str:
    """The script the dialog runs. ``start`` is a Windows path, already converted."""
    lines = [
        "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false",
        "Add-Type -AssemblyName System.Windows.Forms",
        "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog",
        f"$dialog.Description = '{_ps_quote(PROMPT)}'",
        "$dialog.ShowNewFolderButton = $true",
        "if ($dialog.PSObject.Properties['UseDescriptionForTitle']) "
        "{ $dialog.UseDescriptionForTitle = $true }",
    ]
    if start:
        lines.append(f"$dialog.SelectedPath = '{_ps_quote(start)}'")
    lines += [
        # An owner window that is topmost brings the dialog in front of the browser.
        "$owner = New-Object System.Windows.Forms.Form",
        "$owner.TopMost = $true",
        "$result = $dialog.ShowDialog($owner)",
        "if ($result -eq [System.Windows.Forms.DialogResult]::OK) "
        "{ [Console]::Out.Write($dialog.SelectedPath) }",
    ]
    return "\n".join(lines)


def _ps_quote(value: str) -> str:
    return value.replace("'", "''")


def powershell_argv(executable: str, start: str | None) -> list[str]:
    """``-EncodedCommand`` carries the script intact across the WSL/Windows boundary,
    where quotes and newlines in a plain ``-Command`` argument would not survive."""
    encoded = base64.b64encode(powershell_script(start).encode("utf-16-le")).decode("ascii")
    return [
        executable,
        "-NoProfile",
        "-STA",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encoded,
    ]


def _pick_windows(start: str | None, *, timeout: int, run: Run) -> dict[str, Any]:
    # PowerShell exits 0 with nothing printed on cancel; a non-zero status is a failure.
    result = _call(run, powershell_argv("powershell", start), timeout)
    return _finish("windows", result, cancel_codes=())


def _wslpath(run: Run, flag: str, value: str) -> str | None:
    try:
        return _stdout_line(_call(run, ["wslpath", flag, value], _CONVERT_TIMEOUT))
    except (OSError, subprocess.SubprocessError):
        return None


def _pick_wsl(start: str | None, *, timeout: int, run: Run) -> dict[str, Any]:
    windows_start = _wslpath(run, "-w", start) if start else None
    result = _call(run, powershell_argv("powershell.exe", windows_start), timeout)
    outcome = _finish("wsl", result, cancel_codes=())
    if outcome["path"]:
        converted = _wslpath(run, "-u", outcome["path"])
        if converted is None:
            return _result("wsl", error="The chosen folder has no path on this side of WSL.")
        outcome["path"] = converted
    return outcome


# --- macOS: AppleScript ------------------------------------------------------------------


def applescript(start: str | None) -> str:
    script = f'choose folder with prompt "{_as_quote(PROMPT)}"'
    if start:
        script += f' default location POSIX file "{_as_quote(start)}"'
    return f"POSIX path of ({script})"


def _as_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _pick_macos(start: str | None, *, timeout: int, run: Run) -> dict[str, Any]:
    result = _call(run, ["osascript", "-e", applescript(start)], timeout)
    # AppleScript reports a closed window as error -128 on stderr, exit status 1.
    if result.returncode != 0 and "-128" in (result.stderr or ""):
        return _result("macos", cancelled=True)
    outcome = _finish("macos", result, cancel_codes=())
    if outcome["path"] and len(outcome["path"]) > 1:
        outcome["path"] = outcome["path"].rstrip("/")
    return outcome


# --- Linux: zenity, kdialog, then Tk -----------------------------------------------------


def _pick_zenity(start: str | None, *, timeout: int, run: Run) -> dict[str, Any]:
    argv = ["zenity", "--file-selection", "--directory", f"--title={PROMPT}"]
    if start:
        argv.append(f"--filename={start.rstrip('/')}/")
    return _finish("zenity", _call(run, argv, timeout))


def _pick_kdialog(start: str | None, *, timeout: int, run: Run) -> dict[str, Any]:
    argv = ["kdialog", "--getexistingdirectory", start or ".", "--title", PROMPT]
    return _finish("kdialog", _call(run, argv, timeout))


TK_SCRIPT = """\
import sys
from tkinter import Tk, filedialog
root = Tk()
root.withdraw()
root.attributes("-topmost", True)
start = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None
chosen = filedialog.askdirectory(title=sys.argv[2], initialdir=start, mustexist=False)
sys.stdout.write(chosen or "")
"""


def _pick_tkinter(start: str | None, *, timeout: int, run: Run) -> dict[str, Any]:
    # Its own process, so a display that is not there fails the call, not the server.
    argv = [sys.executable, "-c", TK_SCRIPT, start or "", PROMPT]
    return _finish("tkinter", _call(run, argv, timeout), cancel_codes=())


_BACKENDS: dict[str, Callable[..., dict[str, Any]]] = {
    "wsl": _pick_wsl,
    "windows": _pick_windows,
    "macos": _pick_macos,
    "zenity": _pick_zenity,
    "kdialog": _pick_kdialog,
    "tkinter": _pick_tkinter,
}
