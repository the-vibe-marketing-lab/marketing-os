"""Machine-local state for the local app: where it lives, whether it is running.

The state file must work before any brain exists, so it lives under the user's home
directory rather than inside a repository. ``MOS_HOME`` overrides the location, which
is what keeps tests off a developer's real home directory.

The session token is deliberately absent from everything written here: the state file
records pid, port, url and root only, so a file leak never hands anyone the ability to
drive the API.
"""

from __future__ import annotations

import contextlib
import ctypes
import datetime
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path
from typing import Any

HOME_ENV = "MOS_HOME"
STATE_FILE = "ui.json"
OPEN_MARKER = "ui-opened"
LOG_FILE = "ui.log"
STATE_SCHEMA = "mos.ui-state.v1"

# The only URL shape the browser fallbacks will ever be handed. Everything reaching
# them is generated from a bound socket, but matching first means no value that is not
# a loopback URL can reach an external program under any future refactor.
_LOOPBACK_URL = re.compile(r"^http://127\.0\.0\.1:\d{1,5}/?$")

# A launcher that has not returned by now is not going to tell us anything useful.
_LAUNCH_TIMEOUT = 15

# Browsers that "open" a URL inside this terminal instead of in a window. Handing the app
# to one of these is not opening it, so they never count as success.
_TEXT_BROWSERS = frozenset(
    {
        "elinks",
        "links",
        "links2",
        "lynx",
        "netrik",
        "retawq",
        "termux-open-url",
        "w3m",
        "www-browser",
    }
)


def home_dir() -> Path:
    override = os.environ.get(HOME_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".marketing-os"


def state_path() -> Path:
    return home_dir() / STATE_FILE


def marker_path() -> Path:
    return home_dir() / OPEN_MARKER


def log_path() -> Path:
    return home_dir() / LOG_FILE


def read_state() -> dict[str, Any] | None:
    """Return the recorded state, or None when it is absent or unreadable."""
    path = state_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("pid"), int) or not isinstance(payload.get("port"), int):
        return None
    return payload


def write_state(*, pid: int, port: int, url: str, root: Path) -> Path:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": STATE_SCHEMA,
        "pid": int(pid),
        "port": int(port),
        "url": url,
        "root": str(root),
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    return path


def clear_state() -> bool:
    """Remove the state file. True when a file was actually removed."""
    try:
        state_path().unlink()
    except OSError:
        return False
    return True


# The Win32 liveness probe. SYNCHRONIZE is the least access ``WaitForSingleObject`` needs,
# so the handle opened below carries no right to change the process — only the right to ask
# whether it has ended. A process handle is signalled once the process exits, so a wait that
# times out is the answer "still running".
_SYNCHRONIZE = 0x00100000
_WAIT_TIMEOUT = 0x00000102
_ERROR_ACCESS_DENIED = 5


def _windows_pid_alive(pid: int) -> bool:
    """Whether ``pid`` is a running process on Windows, asked without touching it.

    ``os.kill(pid, 0)`` cannot ask this here, and is not safe to try. CPython's
    ``os_kill_impl`` (Modules/posixmodule.c) tests ``sig == CTRL_C_EVENT ||
    sig == CTRL_BREAK_EVENT`` before anything else and ``CTRL_C_EVENT`` is 0, so signal 0
    becomes ``GenerateConsoleCtrlEvent(CTRL_C_EVENT, pid)``: a real Ctrl+C aimed at that
    console group, which arrives as KeyboardInterrupt in us whenever the target shares our
    console. When that call fails the C code does not return either — it falls through to
    ``OpenProcess(PROCESS_ALL_ACCESS, ...)`` and ``TerminateProcess(handle, sig)``, which
    ends the process. No signal number merely asks, so nothing here goes near ``os.kill``.

    ``OpenProcess`` alone would not answer it: a pid stays openable after the process has
    exited, for as long as anything still holds a handle to it. The zero-length wait is what
    separates running from exited. Being denied the handle means the process is someone
    else's, not that it is gone — the same answer POSIX gives through ``PermissionError``.
    """
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Handles are pointer-sized; the default ``c_int`` restype would truncate one.
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel32.OpenProcess(_SYNCHRONIZE, 0, pid)
        if not handle:
            return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
        try:
            return kernel32.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    except OSError:
        # No kernel32, or a call that could not be made at all: the same answer a POSIX
        # OSError earns below, because nothing here is evidence that anything is running.
        return False


def pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def port_open(port: int, *, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    if not isinstance(port, int) or not 0 < port <= 65535:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def live_state() -> tuple[dict[str, Any] | None, bool]:
    """Resolve the truth about the app, cleaning up after a dead server.

    Returns ``(state, cleaned)``. A recorded pid that is dead — or alive but no longer
    holding the port, which is what a recycled pid looks like — is treated as not
    running and the stale file is deleted.
    """
    state = read_state()
    if state is None:
        if state_path().exists():
            return None, clear_state()
        return None, False
    if pid_alive(int(state["pid"])) and port_open(int(state["port"])):
        return state, False
    return None, clear_state()


def is_wsl() -> bool:
    """True on WSL. Three independent markers, because no single one is universal."""
    with contextlib.suppress(OSError):
        if Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists():
            return True
    for name in ("WSL_DISTRO_NAME", "WSL_INTEROP"):
        if os.environ.get(name, "").strip():
            return True
    with contextlib.suppress(OSError):
        version = Path("/proc/version").read_text(encoding="utf-8", errors="replace")
        return "microsoft" in version.lower()
    return False


def _launchers(url: str) -> list[tuple[str, list[str]]]:
    """The mechanisms to try, in the order that works on this platform.

    Windows has one launcher every install carries: ``start``, which hands a URL to the
    default browser. It is a ``cmd.exe`` built-in rather than a program, so it is reached
    through ``cmd /c``, with an empty first argument so the URL is not read as a window
    title. WSL leads with the two escape hatches — ``wslview``, then that same ``cmd.exe``
    — because the generic path resolves to ``gio`` there, which cannot open an http URL at
    all. macOS keeps ``open`` and a real Linux desktop keeps ``xdg-open``; ``webbrowser`` is
    tried last everywhere, by ``open_browser`` itself, so a platform whose launchers are
    all missing still gets its default browser.
    """
    if sys.platform == "darwin":
        return [("open", ["open", url])]
    windows = ("cmd.exe", ["cmd.exe", "/c", "start", "", url])
    if sys.platform == "win32":
        return [windows]
    if is_wsl():
        return [("wslview", ["wslview", url]), windows]
    return [("xdg-open", ["xdg-open", url]), ("gio", ["gio", "open", url])]


def _resolve(argv: list[str]) -> list[str] | None:
    """Turn a command name into a real executable path, or None when it is not installed."""
    if not argv:
        return None
    executable = shutil.which(argv[0])
    if executable is None:
        return None
    return [executable, *argv[1:]]


def _launch_cwd(executable: str) -> str | None:
    """Where to run a launcher from.

    ``cmd.exe`` writes a UNC warning to stderr whenever its working directory is a path
    Windows cannot see, which on WSL is most of them. Running it from its own directory —
    always a real Windows path — keeps that warning from being mistaken for a failure.
    """
    if Path(executable).name.lower() != "cmd.exe":
        return None
    parent = Path(executable).parent
    return str(parent) if parent.is_dir() else None


def _launch(argv: list[str]) -> bool:
    """Run a launcher and report whether it actually worked.

    Success means it exited zero and said nothing on stderr. Output is captured either
    way, so a failing launcher can never write over an envelope on our stdout. Never
    raises; a launcher that hangs past the timeout is killed by ``subprocess.run`` and
    counted as a failure, because a killed child is not evidence that anything opened.
    """
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, loopback URL only
            argv,
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            cwd=_launch_cwd(argv[0]),
            timeout=_LAUNCH_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if completed.returncode != 0:
        return False
    return not completed.stderr.strip()


@contextlib.contextmanager
def _quiet_streams():
    """Point file descriptors 1 and 2 at a scratch file for the duration of the block.

    ``webbrowser`` hands its own stdio to whatever it spawns, so redirecting at the file
    descriptor is the only thing that also silences the children it starts. The captured
    bytes are thrown away: this exists so ``mos ui --json`` stays one JSON document.
    """
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.flush()
    saved: list[tuple[int, int]] = []
    try:
        with tempfile.TemporaryFile() as sink:
            for fd in (1, 2):
                with contextlib.suppress(OSError):
                    saved.append((fd, os.dup(fd)))
                    os.dup2(sink.fileno(), fd)
            yield
    finally:
        for stream in (sys.stdout, sys.stderr):
            with contextlib.suppress(Exception):
                stream.flush()
        for fd, backup in saved:
            with contextlib.suppress(OSError):
                os.dup2(backup, fd)
            with contextlib.suppress(OSError):
                os.close(backup)


def _webbrowser_opened(url: str) -> bool:
    """Open through ``webbrowser``, verifying the outcome instead of trusting it.

    ``GenericBrowser`` and ``BackgroundBrowser`` report only that a child was spawned —
    on WSL that child is ``gio``, which returns 2 and prints to stderr while
    ``webbrowser.open`` still returns True — so those two are run here as ordinary
    launchers and judged on what they actually did. Every other controller checks its own
    exit status, and is called inside a stream guard so nothing it spawns can leak.
    """
    try:
        controller = webbrowser.get()
    except Exception:
        return False
    name = str(getattr(controller, "name", "") or "")
    if Path(name).name.lower().removesuffix(".exe") in _TEXT_BROWSERS:
        return False
    args = getattr(controller, "args", None)
    if isinstance(args, list):
        argv = _resolve([name, *[str(arg).replace("%s", url) for arg in args]])
        return argv is not None and _launch(argv)
    with _quiet_streams():
        try:
            return bool(webbrowser.open(url, new=2))
        except Exception:
            return False


def open_browser(url: str) -> str:
    """Open the app in a browser. Never raises; returns the mechanism that actually worked.

    Every mechanism is verified rather than trusted. A launcher counts only when it exits
    zero and writes nothing to stderr; ``webbrowser`` counts only once the browser it chose
    has been checked the same way. ``webbrowser.open`` returning True is not evidence — on
    WSL it spawns ``gio``, which claims success and then fails — so "webbrowser" is never
    reported for a browser that did not open. Returns "none" when nothing worked, which is
    the caller's cue to print the URL instead.

    The URL is matched against the loopback pattern before any mechanism runs, and every
    launcher is a fixed argv list with no shell and no interpolation.
    """
    if not _LOOPBACK_URL.match(url):
        return "none"
    for mechanism, argv in _launchers(url):
        resolved = _resolve(argv)
        if resolved is None:
            continue
        if _launch(resolved):
            return mechanism
    if _webbrowser_opened(url):
        return "webbrowser"
    return "none"


def first_open_recorded() -> bool:
    return marker_path().exists()


def record_first_open() -> bool:
    """Write the first-install marker. False when it could not be written."""
    marker = marker_path()
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds") + "\n",
            encoding="utf-8",
        )
    except OSError:
        return False
    return True
