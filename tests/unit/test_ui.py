import contextlib
import json
import os
import socket
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from marketing_os.cli.main import build_parser, main, run_argv
from marketing_os.core.setup import setup_repo
from marketing_os.ui import state as ui_state
from marketing_os.ui.commands import (
    COMMANDS,
    SEPARATOR,
    CommandError,
    allowlist,
    build_argv,
    command_line,
    describe,
)
from marketing_os.ui.server import TOKEN_HEADER, create_server

PLANNED_ALLOWLIST = {
    "status",
    "assist status",
    "assist ask",
    "validate",
    "doctor",
    "onboard",
    "attach",
    "install",
    "skills sync",
    "index build",
    "index sync",
    "index status",
    "related",
    "query",
    "think",
    "ingest",
    "migrate",
    "update",
    "statusline",
    "context show",
    "context set",
    # The rename and open commands landed with the overview header controls.
    "rename",
    "open",
}

#: A full path, spelled the way the platform running these tests spells one. The probe asks
#: pathlib the same question the guard asks, because that is what "full path" means here:
#: on Windows a drive is part of it, so "/tmp/brain" is relative to the current drive.
_WINDOWS_HERE = Path("C:/brain").is_absolute()
FULL_PATH = "C:/brain" if _WINDOWS_HERE else "/tmp/brain"
#: A full path as the *other* platform spells one, which is a relative path on this one.
FOREIGN_FULL_PATH = "/home/you/brain" if _WINDOWS_HERE else "C:/Users/you/Desktop"
#: How ``command_line`` quotes a value with a space in it on this platform.
QUOTE = '"' if _WINDOWS_HERE else "'"


def _home(monkeypatch, tmp_path: Path) -> Path:
    home = tmp_path / "machine-home" / ".marketing-os"
    monkeypatch.setenv(ui_state.HOME_ENV, str(home))
    return home


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path: Path) -> None:
    """Every server in this module registers its root; none of them may touch the
    operator's real registry."""
    monkeypatch.setenv(ui_state.HOME_ENV, str(tmp_path / "mos-home"))


def _dead_pid() -> int:
    for candidate in range(999_999, 900_000, -1):
        if not ui_state.pid_alive(candidate):
            return candidate
    raise RuntimeError("no dead pid available on this machine")


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


# --- state file ---------------------------------------------------------------------


def test_state_file_round_trips_before_any_brain_exists(monkeypatch, tmp_path: Path) -> None:
    home = _home(monkeypatch, tmp_path)
    assert not home.exists()
    assert ui_state.read_state() is None

    ui_state.write_state(pid=4321, port=4321, url="http://127.0.0.1:4321/", root=tmp_path)
    recorded = ui_state.read_state()
    assert recorded is not None
    assert recorded["pid"] == 4321
    assert recorded["port"] == 4321
    assert recorded["url"] == "http://127.0.0.1:4321/"
    assert recorded["root"] == str(tmp_path)
    assert ui_state.state_path() == home / "ui.json"


def test_state_file_never_records_a_session_token(monkeypatch, tmp_path: Path) -> None:
    _home(monkeypatch, tmp_path)
    ui_state.write_state(pid=1, port=2, url="http://127.0.0.1:2/", root=tmp_path)
    payload = json.loads(ui_state.state_path().read_text(encoding="utf-8"))
    assert set(payload) == {"schema", "pid", "port", "url", "root", "started_at"}


def test_stale_pid_is_reported_as_not_running_and_cleaned(monkeypatch, tmp_path: Path) -> None:
    _home(monkeypatch, tmp_path)
    ui_state.write_state(
        pid=_dead_pid(), port=_closed_port(), url="http://127.0.0.1:1/", root=tmp_path
    )
    state, cleaned = ui_state.live_state()
    assert state is None
    assert cleaned is True
    assert not ui_state.state_path().exists()


def test_a_live_pid_without_the_port_is_still_stale(monkeypatch, tmp_path: Path) -> None:
    """A recycled pid must not be mistaken for a running server."""
    import os

    _home(monkeypatch, tmp_path)
    ui_state.write_state(
        pid=os.getpid(), port=_closed_port(), url="http://127.0.0.1:1/", root=tmp_path
    )
    state, cleaned = ui_state.live_state()
    assert state is None
    assert cleaned is True


def test_unreadable_state_is_discarded(monkeypatch, tmp_path: Path) -> None:
    home = _home(monkeypatch, tmp_path)
    home.mkdir(parents=True)
    ui_state.state_path().write_text("not json at all", encoding="utf-8")
    state, cleaned = ui_state.live_state()
    assert state is None
    assert cleaned is True
    assert not ui_state.state_path().exists()


# --- pid liveness -------------------------------------------------------------------

# Win32 values, written out here rather than read from the module, so these tests pin the
# contract instead of agreeing with whatever the module happens to say.
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_ERROR_ACCESS_DENIED = 5
_ERROR_INVALID_PARAMETER = 87


class _Win32Call:
    """One kernel32 export: records the arguments it was handed, returns a set answer."""

    def __init__(self, result: int = 0) -> None:
        self.result = result
        self.calls: list[tuple] = []

    def __call__(self, *args) -> int:
        self.calls.append(args)
        return self.result


def _fake_ctypes(*, handle: int = 0, wait: int = _WAIT_TIMEOUT, last_error: int = 0):
    """Stand in for ``ctypes`` so the Windows probe can be run on a machine that is not one.

    ``WinDLL`` does not exist off Windows, so the three kernel32 calls are faked and what
    gets checked is the decision made from their answers — and which calls were made at all.
    """
    kernel32 = SimpleNamespace(
        OpenProcess=_Win32Call(handle),
        WaitForSingleObject=_Win32Call(wait),
        CloseHandle=_Win32Call(1),
    )
    fake = SimpleNamespace(
        WinDLL=lambda name, use_last_error=False: kernel32,
        get_last_error=lambda: last_error,
        c_void_p=int,
        c_uint32=int,
        c_int=int,
    )
    return fake, kernel32


def _explode(*args, **kwargs):
    raise AssertionError(f"the wrong platform path ran: {args}")


def test_pid_alive_answers_about_real_processes() -> None:
    """The POSIX contract, unchanged: this process is alive, an unused pid is not."""
    assert ui_state.pid_alive(os.getpid()) is True
    assert ui_state.pid_alive(_dead_pid()) is False
    assert ui_state.pid_alive(0) is False
    assert ui_state.pid_alive(-1) is False
    assert ui_state.pid_alive("4321") is False


def test_pid_alive_on_posix_still_probes_with_signal_zero(monkeypatch) -> None:
    """The signal number is the whole contract on POSIX; nothing may drift it off zero."""
    seen: list[tuple[int, int]] = []
    monkeypatch.setattr(ui_state.os, "name", "posix")
    monkeypatch.setattr(ui_state.os, "kill", lambda pid, sig: seen.append((pid, sig)))
    monkeypatch.setattr(ui_state, "_windows_pid_alive", _explode)
    assert ui_state.pid_alive(4321) is True
    assert seen == [(4321, 0)]


@pytest.mark.parametrize(
    ("raised", "expected"),
    [(ProcessLookupError, False), (PermissionError, True), (OSError, False)],
)
def test_pid_alive_maps_every_posix_answer(monkeypatch, raised, expected) -> None:
    def _raise(pid: int, sig: int) -> None:
        raise raised("from the kernel")

    monkeypatch.setattr(ui_state.os, "name", "posix")
    monkeypatch.setattr(ui_state.os, "kill", _raise)
    assert ui_state.pid_alive(4321) is expected


def test_pid_alive_never_signals_anything_on_windows(monkeypatch) -> None:
    """The bug: ``os.kill(pid, 0)`` on Windows is not a probe.

    ``signal.CTRL_C_EVENT`` is 0 and CPython's ``os_kill_impl`` matches the console branch
    first, so signal 0 becomes ``GenerateConsoleCtrlEvent(CTRL_C_EVENT, pid)`` — a real
    Ctrl+C into that console group, which ended a Windows pytest run at test 550 with 204
    tests never executed. Should that call fail, the C code falls through to
    ``TerminateProcess``. Neither belongs anywhere near a liveness question.
    """
    fake, kernel32 = _fake_ctypes(handle=0x1F4, wait=_WAIT_TIMEOUT)
    monkeypatch.setattr(ui_state.os, "name", "nt")
    monkeypatch.setattr(ui_state, "ctypes", fake)
    monkeypatch.setattr(ui_state.os, "kill", _explode)

    assert ui_state.pid_alive(500) is True
    # SYNCHRONIZE alone: the handle we hold cannot terminate anything even by accident.
    assert kernel32.OpenProcess.calls == [(_SYNCHRONIZE, 0, 500)]


@pytest.mark.parametrize(
    ("wait", "expected"), [(_WAIT_TIMEOUT, True), (_WAIT_OBJECT_0, False)]
)
def test_the_windows_probe_reads_the_wait_and_always_closes_the_handle(
    monkeypatch, wait, expected
) -> None:
    """A pid stays openable after the process exits, so the wait is the real answer."""
    fake, kernel32 = _fake_ctypes(handle=0x1F4, wait=wait)
    monkeypatch.setattr(ui_state, "ctypes", fake)

    assert ui_state._windows_pid_alive(4321) is expected
    assert kernel32.WaitForSingleObject.calls == [(0x1F4, 0)]
    assert kernel32.CloseHandle.calls == [(0x1F4,)]


@pytest.mark.parametrize(
    ("error", "expected"), [(_ERROR_ACCESS_DENIED, True), (_ERROR_INVALID_PARAMETER, False)]
)
def test_a_windows_process_we_cannot_open_is_dead_only_when_it_is_absent(
    monkeypatch, error, expected
) -> None:
    """Denied is somebody else's running process — what ``PermissionError`` means on POSIX."""
    fake, kernel32 = _fake_ctypes(handle=0, last_error=error)
    monkeypatch.setattr(ui_state, "ctypes", fake)

    assert ui_state._windows_pid_alive(4321) is expected
    assert kernel32.WaitForSingleObject.calls == []
    assert kernel32.CloseHandle.calls == []


def test_the_windows_probe_never_raises(monkeypatch) -> None:
    """``live_state`` calls this on every ``mos ui``; a missing kernel32 is not a crash."""

    def _no_kernel32(name: str, use_last_error: bool = False):
        raise OSError("could not load kernel32")

    monkeypatch.setattr(ui_state, "ctypes", SimpleNamespace(WinDLL=_no_kernel32))
    assert ui_state._windows_pid_alive(4321) is False


def _script(path: Path, *, out: str = "", err: str = "", code: int = 0) -> Path:
    """A stand-in launcher. Real process, real exit code, real streams.

    A shell script here; on Windows a batch file, the one kind of script ``CreateProcess``
    runs by itself, so the launcher is a real process there too. The ``.cmd`` suffix is what
    tells Windows to do that, so the path handed back — not the one asked for — is the one
    to run.
    """
    if _WINDOWS_HERE:
        path = path.with_suffix(".cmd")
        lines = ["@echo off"]
        if out:
            lines.append(f"echo {out}")
        if err:
            lines.append(f"echo {err} 1>&2")
        lines.append(f"exit /b {code}")
        path.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
        return path
    lines = ["#!/bin/sh"]
    if out:
        lines.append(f'echo "{out}"')
    if err:
        lines.append(f'echo "{err}" >&2')
    lines.append(f"exit {code}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o755)
    return path


class _SpawnOnlyBrowser:
    """What ``webbrowser.get()`` hands back on WSL: a BackgroundBrowser around ``gio``.

    ``open`` reports whether a child was *spawned*, never whether it worked, which is the
    lie the old ``open_browser`` believed.
    """

    def __init__(self, executable: Path, *, run: bool = False) -> None:
        self.name = str(executable)
        self.args = ["open", "--", "%s"]
        self.run = run

    def open(self, url: str, new: int = 0, autoraise: bool = True) -> bool:
        if self.run:
            # BackgroundBrowser hands the child our own stdout and stderr.
            subprocess.run([self.name, "open", "--", url], check=False)
        return True


def test_open_browser_never_raises(monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise RuntimeError("no display")

    monkeypatch.setattr("marketing_os.ui.state.webbrowser.get", explode)
    monkeypatch.setattr("marketing_os.ui.state.webbrowser.open", explode)
    monkeypatch.setattr("marketing_os.ui.state.shutil.which", lambda name: None)
    assert ui_state.open_browser("http://127.0.0.1:4321/") == "none"


def test_open_browser_refuses_a_non_loopback_url(monkeypatch) -> None:
    monkeypatch.setattr("marketing_os.ui.state.webbrowser.open", lambda *a, **k: False)
    called: list[str] = []
    monkeypatch.setattr(
        "marketing_os.ui.state.shutil.which", lambda name: called.append(name) or None
    )
    assert ui_state.open_browser("https://example.com/evil") == "none"
    assert called == []


def test_a_browser_that_only_claims_success_is_not_accepted(monkeypatch, tmp_path: Path) -> None:
    """The WSL bug: ``gio`` exits 2, ``webbrowser.open`` returns True, nothing opens."""
    gio = _script(tmp_path / "gio", err="gio: Operation not supported", code=2)
    browser = _SpawnOnlyBrowser(gio)
    monkeypatch.setattr("marketing_os.ui.state._launchers", lambda url: [], raising=False)
    monkeypatch.setattr("marketing_os.ui.state.webbrowser.get", lambda *a, **k: browser)
    monkeypatch.setattr("marketing_os.ui.state.webbrowser.open", browser.open)

    assert ui_state.open_browser("http://127.0.0.1:4321/") == "none"


def test_no_browser_output_can_reach_our_streams(monkeypatch, tmp_path: Path, capfd) -> None:
    """A chatty browser used to print over the ``--json`` envelope. It gets captured now."""
    gio = _script(
        tmp_path / "gio", out="gio: chatter on stdout", err="gio: Operation not supported", code=2
    )
    browser = _SpawnOnlyBrowser(gio, run=True)
    monkeypatch.setattr("marketing_os.ui.state._launchers", lambda url: [], raising=False)
    monkeypatch.setattr("marketing_os.ui.state.webbrowser.get", lambda *a, **k: browser)
    monkeypatch.setattr("marketing_os.ui.state.webbrowser.open", browser.open)

    mechanism = ui_state.open_browser("http://127.0.0.1:4321/")
    streams = capfd.readouterr()
    assert streams.out == ""
    assert streams.err == ""
    assert mechanism == "none"


def test_a_launcher_that_writes_to_stderr_does_not_count(monkeypatch, tmp_path: Path) -> None:
    """Exit zero is not enough: ``cmd.exe`` exits zero while warning that it did nothing."""
    noisy = _script(tmp_path / "wslview", err="UNC paths are not supported.")
    quiet = _script(tmp_path / "cmd.exe")
    monkeypatch.setattr(
        "marketing_os.ui.state._launchers",
        lambda url: [("wslview", [str(noisy), url]), ("cmd.exe", [str(quiet), url])],
        raising=False,
    )
    monkeypatch.setattr("marketing_os.ui.state.webbrowser.get", lambda *a, **k: None)
    # Were the launchers to fail, the fallback would open a real browser on this machine.
    monkeypatch.setattr("marketing_os.ui.state.webbrowser.open", lambda *a, **k: False)

    assert ui_state.open_browser("http://127.0.0.1:4321/") == "cmd.exe"


def test_cmd_exe_runs_from_its_own_folder_and_nothing_else_moves(monkeypatch, tmp_path) -> None:
    """From a folder Windows cannot see, ``cmd.exe`` warns on stderr, which reads as failure
    here; so it runs from its own folder. Every other launcher keeps ours."""
    url = "http://127.0.0.1:4321/"
    ran: list[dict] = []

    def run(argv, **kwargs):
        ran.append(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr("marketing_os.ui.state.subprocess.run", run)
    assert ui_state._launch([str(tmp_path / "cmd.exe"), "/c", "start", "", url]) is True
    assert ui_state._launch([str(tmp_path / "xdg-open"), url]) is True
    assert [kwargs["cwd"] for kwargs in ran] == [str(tmp_path), None]


def test_a_text_browser_is_never_treated_as_opening_the_app(monkeypatch, tmp_path: Path) -> None:
    """Refused by name, before anything runs: a text browser that would exit zero still
    only ever opens the app inside this terminal."""
    lynx = _SpawnOnlyBrowser(tmp_path / "lynx")
    monkeypatch.setattr("marketing_os.ui.state._launch", _explode)
    monkeypatch.setattr("marketing_os.ui.state._launchers", lambda url: [], raising=False)
    monkeypatch.setattr("marketing_os.ui.state.webbrowser.get", lambda *a, **k: lynx)
    monkeypatch.setattr("marketing_os.ui.state.webbrowser.open", lynx.open)

    assert ui_state.open_browser("http://127.0.0.1:4321/") == "none"


def test_wsl_reaches_the_windows_launchers_before_the_generic_path(monkeypatch) -> None:
    monkeypatch.setattr("marketing_os.ui.state.is_wsl", lambda: True)
    monkeypatch.setattr("marketing_os.ui.state.sys.platform", "linux")
    assert [name for name, _ in ui_state._launchers("http://127.0.0.1:4321/")] == [
        "wslview",
        "cmd.exe",
    ]


def test_windows_native_gets_start_through_cmd_and_nothing_else(monkeypatch) -> None:
    """The one launcher every Windows carries. Empty title argument, or ``start`` reads the
    URL as the window name and opens nothing."""
    monkeypatch.setattr("marketing_os.ui.state.sys.platform", "win32")
    monkeypatch.setattr("marketing_os.ui.state.is_wsl", _explode)
    url = "http://127.0.0.1:4321/"
    assert ui_state._launchers(url) == [("cmd.exe", ["cmd.exe", "/c", "start", "", url])]


def test_wsl_is_detected_from_any_one_marker(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.delenv("WSL_INTEROP", raising=False)
    monkeypatch.setattr("marketing_os.ui.state.Path", _MissingProcPath)
    assert ui_state.is_wsl() is False
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu-24.04")
    assert ui_state.is_wsl() is True


@pytest.mark.skipif(
    not hasattr(__import__("os"), "fork"), reason="requires os.fork to detach the server"
)
def test_a_browser_that_never_opens_still_warns_and_prints_the_url(
    monkeypatch, tmp_path, capsys
) -> None:
    """The degrade path: "none" has to reach the envelope and raise the caller's warning."""
    from marketing_os.ui.lifecycle import stop_ui

    _home(monkeypatch, tmp_path)
    monkeypatch.setattr("marketing_os.ui.state.open_browser", lambda url: "none")
    try:
        code = main(["ui", str(tmp_path), "--port", "0", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["browser"] == "none"
        assert "browser-not-opened" in {item["code"] for item in payload["findings"]}
        assert payload["url"] in payload["next_action"]["reason"]
    finally:
        stop_ui()


class _MissingProcPath(type(Path())):
    """A Path whose /proc probes all come up empty, so only the env markers can fire.

    Subclasses the concrete flavour (``PosixPath``/``WindowsPath``) that ``Path()`` returns
    rather than ``Path`` itself: before 3.12, ``Path`` carries no ``_flavour``, so a direct
    subclass raises ``AttributeError`` on the first instantiation. We support 3.10.
    """

    def exists(self, *args, **kwargs) -> bool:
        if str(self).startswith("/proc/"):
            return False
        return super().exists(*args, **kwargs)

    def read_text(self, *args, **kwargs) -> str:
        if str(self).startswith("/proc/"):
            raise OSError("no /proc here")
        return super().read_text(*args, **kwargs)


# --- the allowlist ------------------------------------------------------------------


def test_allowlist_matches_the_plan() -> None:
    assert set(allowlist()) == PLANNED_ALLOWLIST


def test_describe_exposes_every_allowlisted_command() -> None:
    described = {item["command"] for item in describe()}
    assert described == PLANNED_ALLOWLIST
    onboard = next(item for item in describe() if item["command"] == "onboard")
    assert onboard["mutating"] is True


def test_build_argv_maps_a_bag_of_arguments_onto_the_real_cli() -> None:
    argv = build_argv(
        "onboard",
        {"path": FULL_PATH, "name": "Acme Co", "mode": "agency", "yes": True},
    )
    assert argv == ["onboard", "--name", "Acme Co", "--mode", "agency", "--yes", "--", FULL_PATH]
    assert command_line(argv) == (
        f"mos onboard --name {QUOTE}Acme Co{QUOTE} --mode agency --yes -- {FULL_PATH}"
    )


def test_build_argv_handles_nested_subcommands_and_numbers() -> None:
    assert build_argv("index sync", {"path": FULL_PATH, "plan": True}) == [
        "index",
        "sync",
        "--plan",
        "--",
        FULL_PATH,
    ]
    assert build_argv("query", {"question": "pricing", "path": FULL_PATH, "limit": 3}) == [
        "query",
        "--limit",
        "3",
        "--",
        "pricing",
        FULL_PATH,
    ]


def test_build_argv_omits_flags_that_are_not_true() -> None:
    assert build_argv("validate", {"path": FULL_PATH, "strict": False}) == [
        "validate",
        "--",
        FULL_PATH,
    ]


@pytest.mark.parametrize("value", [".", "relative/brain", FOREIGN_FULL_PATH, "brain"])
def test_build_argv_refuses_a_path_that_is_not_a_full_path(value: str) -> None:
    """The CLI resolves a relative path against its own cwd, which for the app is wherever
    the server was started; the other platform's spelling of a full path is relative too."""
    with pytest.raises(CommandError, match="must be a full path") as caught:
        build_argv("status", {"path": value})
    assert caught.value.code == "bad-path"


def test_build_argv_accepts_the_home_tilde_as_a_full_path() -> None:
    assert build_argv("status", {"path": "~"}) == ["status", "--", "~"]
    assert build_argv("status", {"path": "~/brain"}) == ["status", "--", "~/brain"]


def test_build_argv_omits_the_separator_when_there_is_no_positional() -> None:
    assert build_argv("update", {"plan": True}) == ["update", "--plan"]
    assert build_argv("assist status", {}) == ["assist", "status"]


def test_build_argv_rejects_an_unknown_command() -> None:
    with pytest.raises(CommandError, match="not allowlisted"):
        build_argv("rm", {})
    with pytest.raises(CommandError, match="not allowlisted"):
        build_argv("skills", {})


def test_build_argv_rejects_unknown_arguments() -> None:
    with pytest.raises(CommandError, match="does not accept"):
        build_argv("status", {"path": ".", "exec": "whoami"})


def test_build_argv_rejects_a_missing_required_positional() -> None:
    with pytest.raises(CommandError, match="requires"):
        build_argv("query", {"path": "."})


def test_build_argv_refuses_a_positional_gap() -> None:
    with pytest.raises(CommandError, match="before"):
        build_argv("ingest", {"path": FULL_PATH, "yes": True})


def test_build_argv_refuses_both_mutation_flags() -> None:
    with pytest.raises(CommandError, match="exactly one"):
        build_argv("onboard", {"path": ".", "name": "X", "plan": True, "yes": True})


def test_build_argv_rejects_a_non_scalar_value() -> None:
    with pytest.raises(CommandError, match="string or number"):
        build_argv("query", {"question": ["a", "b"]})


# --- a positional must never be readable as a flag ----------------------------------


def _benign(spec) -> dict:
    """The smallest argument bag that builds a valid argv for one command."""
    args: dict = {name: "value" for name in spec.positionals}
    if "path" in args:  # a path must be a full path; the other positionals are free text
        args["path"] = FULL_PATH
    args.update({name: "value" for name in spec.required if name in spec.options})
    if "name" in spec.options:  # mos onboard requires --name at the parser
        args["name"] = "Acme Co"
    if "plan" in spec.flags:
        args["plan"] = True
    return args


def test_a_flag_shaped_path_cannot_carry_the_approval_gate_into_context_set() -> None:
    """The reported defect: --yes as a value became --yes as the flag, and applied."""
    with pytest.raises(CommandError, match="must not begin with"):
        build_argv(
            "context set",
            {"path": "--yes", "field": "voice", "text": "How we sound at our best."},
        )


def test_a_flag_shaped_source_cannot_shift_what_the_other_positionals_mean() -> None:
    """An accepted flag moves ingest's path into source; the file read was arbitrary."""
    with pytest.raises(CommandError, match="must not begin with"):
        build_argv("ingest", {"source": "--yes", "path": "/etc/hostname"})


def test_every_positional_on_every_command_refuses_a_flag_shaped_value() -> None:
    for command, spec in COMMANDS.items():
        for target in spec.positionals:
            args = _benign(spec)
            args[target] = "--yes"
            with pytest.raises(CommandError, match="must not begin with"):
                build_argv(command, args)


def test_the_separator_makes_argparse_read_every_positional_as_a_value() -> None:
    """The second defence, checked against the real parser rather than assumed.

    Each command's own argv is rebuilt with every positional replaced by ``--yes``, which
    is the exact string the rejection above stops. The parser must still read them as
    values: the approval flag stays off and the value lands on the positional.
    """
    parser = build_parser()
    covered = 0
    for command, spec in COMMANDS.items():
        argv = build_argv(command, _benign(spec))
        if SEPARATOR not in argv:
            continue
        cut = argv.index(SEPARATOR)
        hostile = [*argv[: cut + 1], *["--yes"] * (len(argv) - cut - 1)]
        parsed = parser.parse_args(hostile)
        for name in spec.positionals:
            assert getattr(parsed, name.replace("-", "_")) == "--yes", command
        if "yes" in spec.flags:
            assert parsed.yes is False, command
            assert parsed.plan is True, command
        covered += 1
    assert covered >= 15  # every allowlisted command that takes a positional


def test_an_option_value_may_still_begin_with_a_dash() -> None:
    """--field and its value are two argv elements, so the value is never read as a flag."""
    argv = build_argv("query", {"question": "pricing", "limit": 3})
    assert argv == ["query", "--limit", "3", "--", "pricing"]
    parsed = build_parser().parse_args(build_argv("think", {"topic": "a -- b"}))
    assert parsed.topic == "a -- b"


# --- the in-process seam ------------------------------------------------------------


def test_run_argv_returns_the_same_envelope_as_the_terminal(tmp_path: Path, capsys) -> None:
    brain = tmp_path / "brain"
    main(["onboard", str(brain), "--name", "Seam Co", "--mode", "in-house", "--yes", "--json"])
    capsys.readouterr()

    main(["status", str(brain), "--json"])
    from_terminal = json.loads(capsys.readouterr().out)
    from_seam = run_argv(["status", str(brain)])
    assert from_seam == from_terminal
    assert capsys.readouterr().out == ""


def test_run_argv_turns_a_usage_error_into_an_envelope(capsys) -> None:
    result = run_argv(["onboard", "/tmp/nowhere"])
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "command-error"
    assert "--name" in result["findings"][0]["message"]
    assert capsys.readouterr().out == ""


def test_run_argv_turns_an_unknown_command_into_an_envelope() -> None:
    result = run_argv(["definitely-not-a-command"])
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "command-error"


def test_run_argv_honours_the_mutation_gate(tmp_path: Path) -> None:
    brain = tmp_path / "brain"
    result = run_argv(["onboard", str(brain), "--name", "Gate Co", "--mode", "in-house"])
    assert result["ok"] is False
    assert not brain.exists()


# --- the lifecycle envelopes --------------------------------------------------------


def test_ui_status_envelope_when_nothing_is_running(monkeypatch, tmp_path, capsys) -> None:
    _home(monkeypatch, tmp_path)
    code = main(["ui", "status", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema"] == "mos.ui.v1"
    assert payload["command"] == "ui"
    assert payload["operation"] == "status"
    assert payload["running"] is False
    assert payload["url"] is None
    assert payload["port"] is None
    assert payload["pid"] is None
    assert payload.keys() >= {"schema", "command", "ok", "repo", "changes", "findings"}


def test_ui_stop_is_idempotent(monkeypatch, tmp_path, capsys) -> None:
    _home(monkeypatch, tmp_path)
    code = main(["ui", "stop", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["running"] is False
    assert {item["code"] for item in payload["findings"]} == {"ui-not-running"}


def test_ui_status_recovers_from_a_stale_pid(monkeypatch, tmp_path, capsys) -> None:
    _home(monkeypatch, tmp_path)
    ui_state.write_state(
        pid=_dead_pid(), port=_closed_port(), url="http://127.0.0.1:1/", root=tmp_path
    )
    code = main(["ui", "status", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["running"] is False
    assert "clear stale ui state" in payload["changes"]
    assert not ui_state.state_path().exists()


def test_ui_start_reports_an_unavailable_port(monkeypatch, tmp_path, capsys) -> None:
    _home(monkeypatch, tmp_path)
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        taken = int(held.getsockname()[1])
        code = main(["ui", str(tmp_path), "--port", str(taken), "--no-open", "--json"])
        payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert payload["findings"][0]["code"] == "ui-port-unavailable"
    assert payload["next_action"]["id"] == "choose-port"


# --- first-install auto-open --------------------------------------------------------


def test_install_with_no_ui_never_opens_the_app(monkeypatch, tmp_path, capsys) -> None:
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    _home(monkeypatch, tmp_path)

    code = main(["install", "--yes", "--no-ui", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert "ui" not in payload
    assert not ui_state.marker_path().exists()
    assert (home / ".claude" / "skills" / "mos-start" / "SKILL.md").is_file()


@pytest.mark.skipif(
    not hasattr(__import__("os"), "fork"), reason="requires os.fork to detach the server"
)
def test_install_opens_the_app_once_and_never_again(monkeypatch, tmp_path, capsys) -> None:
    from marketing_os.ui.lifecycle import first_install_open, stop_ui

    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    _home(monkeypatch, tmp_path)
    opened: list[str] = []
    # Patch the whole mechanism, not webbrowser: which one works is platform-specific, and
    # the suite must not fire a real browser window to prove the marker is honoured.
    monkeypatch.setattr(
        "marketing_os.ui.state.open_browser",
        lambda url: bool(opened.append(url)) and "stub" or "stub",
    )

    try:
        first = first_install_open(tmp_path)
        assert first["opened"] is True
        assert opened == [first["url"]]
        assert ui_state.marker_path().is_file()
        assert ui_state.port_open(int(first["port"]))

        # The marker makes it a one-time event, however often install is re-run.
        assert first_install_open(tmp_path) == {"opened": False, "reason": "already-opened"}
        assert opened == [first["url"]]
    finally:
        stopped = stop_ui()
    assert stopped["running"] is False


# --- the assisted interview, in a running app ---------------------------------------
# A static test can prove app.js contains no markup sink. It cannot prove what a hostile
# question actually renders as, or that a timed-out assist leaves a half-typed answer
# alone. Those need the shipped app.js executing against real nodes, so tests/support
# gives it a small DOM and a scripted server and reports what happened.

HARNESS = Path(__file__).resolve().parents[1] / "support" / "ui_harness.cjs"
HOSTILE = '<img src=x onerror="alert(1)"> [click me](javascript:alert(2)) & <b>bold</b>'
DRAFTED = "We coach beginners in <script>alert(3)</script> Marrickville, six days a week."


@pytest.fixture(scope="module")
def browser() -> dict:
    """Boot the real app.js once, run every assisted-interview scenario, return the lot."""
    import shutil as _shutil
    import tempfile

    node = _shutil.which("node")
    if node is None:
        pytest.skip("node is needed to run the shipped app.js against a DOM")

    from marketing_os.ui.commands import describe as describe_commands
    from marketing_os.ui.server import static_root as ui_static_root

    with tempfile.TemporaryDirectory() as scratch:
        brain = Path(scratch) / "brain"
        run_argv(["onboard", str(brain), "--name", "Test Gym", "--mode", "in-house", "--yes"])
        status = run_argv(["status", str(brain)])
        doctor = run_argv(["doctor", str(brain)])
        context = run_argv(["context", "show", str(brain)])
        rename = run_argv(["rename", str(brain), "--name", "Test Gym Two", "--plan"])
        fixture = {
            "static": str(ui_static_root()),
            "state": {
                "schema": "mos.ui.state.v1",
                "cwd": str(brain),
                "root": str(brain),
                "is_brain": True,
                "home": "/home/you",
                "places": [
                    {"path": "/home/you/Desktop", "kind": "desktop"},
                    {"path": "/home/you", "kind": "home"},
                ],
                "brains": [
                    {
                        "path": str(brain),
                        "name": "Test Gym",
                        "mode": "in-house",
                        "legacy": False,
                        "attachable": False,
                        "exists": True,
                        "last_opened": "2026-08-28T00:00:00+00:00",
                    }
                ],
                "command_specs": describe_commands(),
                "status": status,
                "doctor": doctor,
            },
            "envelopes": {
                "status": status,
                "doctor": doctor,
                "context show": context,
                "rename": rename,
                # `mos open` would pop a terminal here; the app only needs its shape.
                "open": {
                    "schema": "mos.open.v1",
                    "command": "open",
                    "ok": True,
                    "repo": str(brain),
                    "changes": [],
                    "findings": [],
                    "next_action": {
                        "id": "type-start",
                        "reason": "Claude Code is opening in a console window, in this "
                        "brain's folder. Type /mos-start there.",
                    },
                    "launched": True,
                    "terminal": "a console window",
                },
            },
            "probe": {
                "schema": "mos.assist.v1",
                "command": "assist",
                "ok": True,
                "repo": str(brain),
                "changes": [],
                "findings": [],
                "operation": "status",
                "ready": True,
                "runtimes": [{"name": "claude", "path": "/usr/bin/claude", "version": "2.1.246"}],
                "checked": [],
            },
        }
        path = Path(scratch) / "fixture.json"
        path.write_text(json.dumps(fixture), encoding="utf-8")
        # The harness writes UTF-8 whatever the console's code page; an em dash read as
        # cp1252 is three characters.
        done = subprocess.run(
            [node, str(HARNESS), str(path)], capture_output=True, encoding="utf-8", timeout=180
        )
    assert done.returncode == 0, done.stderr
    results = json.loads(done.stdout)
    for name, payload in results.items():
        assert "error" not in payload, f"{name}: {payload.get('error')}"
    results["root"] = fixture["state"]["root"]  # the fixture brain, as this machine spells it
    return results


def test_no_runtime_leaves_no_trace_on_the_screen(browser: dict) -> None:
    """Graceful absence. Not a disabled button, not an error, not an empty outline."""
    absent = browser["absence"]
    assert absent["hostChildren"] == 0
    assert absent["hostText"] == ""
    assert absent["answered"] is True, "the plain textarea must still be the whole path"
    for label in absent["buttons"]:
        assert "assistant interview me" not in label
    assert "assist ask" not in absent["calls"]


def test_the_offer_names_the_runtime_and_what_it_costs(browser: dict) -> None:
    offer = browser["offer"]
    assert offer["label"] == "Let my assistant interview me"
    assert offer["describedBy"] == offer["costId"] == "iv-assist-cost"
    assert "Claude Code" in offer["cost"]
    assert "your own subscription" in offer["cost"]
    assert "spends your own tokens" in offer["cost"]
    assert offer["divider"] == "or write it yourself"
    assert offer["askedBeforeClick"] == 0


def test_nothing_asks_a_model_until_someone_presses_the_button(browser: dict) -> None:
    """The rule that was a condition of building this at all."""
    seen = browser["onlyOnClick"]
    assert "assist ask" not in seen["before"]
    assert seen["afterWaiting"] == seen["before"], "something fired on its own while idle"
    assert seen["afterClick"][-1] == "assist ask"
    assert seen["asked"] == 1, "one press, one turn"


def test_a_hostile_question_renders_as_literal_characters(browser: dict) -> None:
    """Model output is data. A tag in it is text, not an element."""
    hostile = browser["hostileQuestion"]
    assert hostile["text"] == "Your assistant asks: " + HOSTILE
    assert hostile["elements"] == [], "the question built no elements of its own"
    assert hostile["allTags"] == [], "nothing it said became a tag anywhere on the page"
    assert hostile["answerBox"] is True
    # The button that was pressed no longer exists; focus must have gone somewhere real.
    assert hostile["focused"] == "iv-assist-answer"


def test_a_failed_assist_keeps_every_character_already_typed(browser: dict) -> None:
    failed = browser["failureKeepsTypedText"]
    assert failed["typed"] == "We are a boxing gym in Marrickville and we only take beginners."
    assert failed["said"] == (
        "Your assistant did not answer in time. Nothing you have written has been touched."
    )
    assert failed["question"] is False
    assert failed["retry"] is True


def test_the_app_falling_over_is_the_same_promise(browser: dict) -> None:
    lost = browser["transportFailureKeepsTypedText"]
    assert lost["typed"] == "Typed before the app fell over."
    assert lost["said"] == (
        "The local app did not answer. Nothing you have written has been touched."
    )


def test_four_questions_then_a_draft_lands_in_the_box(browser: dict) -> None:
    full = browser["fullInterview"]
    assert full["metas"] == [
        f"Question {n} of up to 4, from Claude Code" for n in (1, 2, 3, 4)
    ]
    assert full["transcriptLengths"] == [0, 1, 2, 3, 4], "the interview is bounded at four"
    assert full["draftInBox"] == DRAFTED
    assert full["reviewBlocked"] == "false", "a drafted answer is reviewable straight away"
    assert full["offerBack"] is True


def test_a_draft_never_lands_on_top_of_words_the_operator_wrote(browser: dict) -> None:
    kept = browser["draftNeverOverwritesSilently"]
    assert kept["afterAsk"] == "My own words, which I would like to keep."
    assert kept["shownDraft"] == DRAFTED
    assert kept["shownElements"] == []
    assert kept["afterKeep"] == "My own words, which I would like to keep."
    assert kept["offerBack"] is True


def test_the_wizard_names_the_brain_folder_after_the_business(browser: dict) -> None:
    """Step 1 chooses a place (the desktop by default); the folder inside it is the
    business name as a slug. marketing-os is the engine, never the brain's folder."""
    wiz = browser["wizardNamesTheFolderAfterTheBusiness"]
    assert wiz["placeProbed"] == "/home/you/Desktop"
    assert wiz["chips"][0] == ["On your desktop", "/home/you/Desktop"]
    assert wiz["chips"][1] == ["In your home folder", "/home/you"]
    assert "A new folder, named after your business, on your desktop." in wiz["readout"]
    assert "marketing-os" not in wiz["readout"]
    assert wiz["pathProbed"] == "/home/you/Desktop/cascade-strength-co"
    assert "cascade-strength-co" in wiz["nameReadout"]
    assert "on your desktop" in wiz["nameReadout"]
    # Typing the exact final path, slug included, does not double the slug.
    assert wiz["typedProbed"] == "/home/you/Desktop/cascade-strength-co"


def test_the_button_opens_the_os_folder_window_and_its_answer_is_the_place(browser: dict) -> None:
    """With a window available, the click asks the server for it, waits in the readout
    (not the live region), and the answer becomes the place: chips, probe, announcement."""
    picked = browser["nativePickerChoosesThePlace"]
    assert picked["posted"] == ["/home/you/Desktop"], "the window starts at the current place"
    assert "Waiting for the folder window" in picked["waiting"]
    assert picked["place"] == "/home/you/Projects"
    assert picked["probed"] == "/home/you/Projects"
    assert picked["pressed"] == ["/home/you/Projects"]
    assert picked["live"].startswith("Folder chosen: ") or picked["live"].startswith("Ready: ")
    assert picked["panelHidden"] is True and picked["browsed"] == 0
    quiet = browser["nativePickerCancelledLeavesEverything"]
    assert "Waiting for the folder window" not in quiet["after"]


def test_a_closed_folder_window_changes_nothing(browser: dict) -> None:
    quiet = browser["nativePickerCancelledLeavesEverything"]
    assert quiet["posted"] == 1
    assert quiet["after"] == quiet["before"]
    assert quiet["placeAfter"] == quiet["placeBefore"]
    assert quiet["liveAfter"] == quiet["liveBefore"], "cancelling is not announced"
    assert quiet["panelHidden"] is True


def test_without_a_folder_window_the_button_opens_the_in_page_list(browser: dict) -> None:
    panel = browser["noPickerOpensThePanel"]
    assert panel["posted"] == 0, "no window was asked for"
    assert panel["browsed"] == ["/home/you/Desktop"]
    assert panel["panelHidden"] is False
    assert panel["expanded"] == "true"
    assert "so pick from the list below" not in panel["panelText"]


def test_a_folder_window_that_could_not_open_falls_back_with_one_sentence(browser: dict) -> None:
    fallen = browser["pickerFailureFallsBackToThePanel"]
    assert fallen["posted"] == 1 and fallen["browsed"] == 1
    assert fallen["panelHidden"] is False
    reason = "The folder window could not open here, so pick from the list below."
    assert reason in fallen["panelText"]
    assert "Waiting for the folder window" not in fallen["readout"]


def test_but_it_does_replace_them_when_asked_to(browser: dict) -> None:
    taken = browser["draftReplacesOnRequest"]
    assert taken["box"] == DRAFTED
    assert taken["reviewBlocked"] == "false"
    assert taken["note"] == "", "the 'write an answer' note must clear itself"


def test_found_brains_are_the_ones_in_the_chosen_folder(browser: dict) -> None:
    """The wizard looks in the place it points at and nowhere else: the note lists what
    that look reported, and the count sentence says how many."""
    found = browser["foundBrainsFollowThePlace"]
    assert found["asked"] == ["/home/you/Desktop"], "one look, at the chosen place only"
    assert found["lede"].startswith("Brains already in this folder (2).")
    # The twins are told apart with "in <folder>": the Ember retheme retired em dashes.
    assert [b[0] for b in found["buttons"]] == [
        "Open Cascade Strength Co. in cascade",
        "Open Cascade Strength Co. in cascade-old",
    ], "two brains with one name are told apart by folder name, not by path"


def test_found_brains_carry_paths_only_in_titles(browser: dict) -> None:
    found = browser["foundBrainsFollowThePlace"]
    assert "/" not in found["text"], "no path, not even a fragment, in the visible copy"
    for _text, title, aria in found["buttons"]:
        assert title.startswith("/home/you/Desktop/")
        assert "/" not in aria


def test_an_older_brain_is_tagged_and_opens_the_attach_screen(browser: dict) -> None:
    """Pressing it asks for the attach plan and shows it; nothing is written, and the
    stored path does not move until the brain is actually attached."""
    found = browser["foundBrainsFollowThePlace"]
    assert found["tags"] == ["needs attach"]
    older = [b for b in found["buttons"] if b[0].endswith("cascade-old")][0]
    assert older[2].endswith(", needs attach")
    assert found["attachPlanned"] == {"path": "/home/you/Desktop/cascade-old", "plan": True}
    assert found["attachShown"] is True
    assert found["attachTitle"] == "Attach Cascade Strength Co."
    assert found["opened"] is None


def test_changing_the_place_looks_there_and_drops_the_note_when_it_is_empty(
    browser: dict,
) -> None:
    found = browser["foundBrainsFollowThePlace"]
    assert found["askedAfter"] == ["/home/you/Desktop", "/home/you"]
    assert found["afterChildren"] == 0 and found["afterText"] == ""


# --- the sidebar, in a running app ------------------------------------------------------


def test_the_sidebar_lists_every_brain_by_name_and_never_by_path(browser: dict) -> None:
    listed = browser["sidebarListsBrains"]
    assert listed["hidden"] is False
    assert [row["name"] for row in listed["rows"]] == ["Test Gym", "Second Co", "Gone Co", "Old Co"]
    assert "/" not in listed["visible"], "paths ride in titles only"
    assert [row["title"] for row in listed["rows"]] == [
        browser["root"],
        "/home/you/Desktop/second",
        "/home/you/Desktop/gone",
        "/home/you/Desktop/old",
    ], "the path is on the title, for the tooltip"
    assert listed["tabs"] == ["true", "false"] and listed["tabsShown"] is True
    assert listed["topbar"] == "Test Gym"


def test_the_open_brain_is_marked_in_words_not_colour_alone(browser: dict) -> None:
    rows = browser["sidebarListsBrains"]["rows"]
    current = [row for row in rows if row["current"] == "true"]
    assert [row["name"] for row in current] == ["Test Gym"]
    assert current[0]["tags"] == ["current"]
    assert all(row["current"] is None for row in rows if row["name"] != "Test Gym")


def test_a_missing_brain_is_greyed_tagged_and_forgettable(browser: dict) -> None:
    gone = browser["missingBrainForget"]
    assert gone["row"]["tags"] == ["not found"]
    assert gone["row"]["disabled"] == "true"
    assert gone["row"]["forget"] == [["Forget", "Forget Gone Co"]]
    # Pressing the greyed name goes nowhere; the open brain is still the open brain.
    assert gone["stillHere"] == "Test Gym"
    assert gone["ops"] == [{"op": "forget", "path": "/home/you/Desktop/gone"}]
    assert gone["names"] == ["Test Gym", "Second Co", "Old Co"]
    assert gone["live"] == "Forgot Gone Co."
    assert gone["focusedInList"] is True


def test_one_press_switches_the_whole_app_to_that_brain(browser: dict) -> None:
    switched = browser["switchingBrains"]
    assert switched["before"] == "Test Gym"
    assert switched["title"] == "Second Co"
    assert switched["topbar"] == "Second Co"
    assert "Folder: second" in switched["meta"], "the dashboard is about the new root"
    assert switched["stored"] == "/home/you/Desktop/second"
    assert switched["ops"] == [{"op": "remember", "path": "/home/you/Desktop/second"}]
    assert switched["current"] == ["Second Co"]
    assert switched["live"] == "Now showing Second Co."
    assert switched["dashboardShown"] is True
    assert switched["focused"] == "/home/you/Desktop/second", "focus follows the pressed brain"


def test_an_older_brain_shows_the_attach_plan_then_attaches_on_one_press(browser: dict) -> None:
    flow = browser["attachableBrainFlow"]
    assert flow["row"]["tags"] == ["needs attach"]
    assert flow["attachShown"] is True and flow["dashboardHidden"] is True
    assert flow["title"] == "Attach Old Co"
    assert flow["planCalls"] == [{"path": "/home/you/Desktop/old", "plan": True}]
    assert flow["storedBefore"] is None, "nothing moved before the operator said yes"
    assert flow["changes"] == 3, "the plan's changes are on screen before anything runs"
    assert flow["buttons"] == ["Attach this brain", "Not now"]
    assert flow["calls"] == [
        {"path": "/home/you/Desktop/old", "plan": True},
        {"path": "/home/you/Desktop/old", "yes": True},
    ]
    assert flow["afterShown"] is True and flow["afterTitle"] == "Old Co"
    assert flow["storedAfter"] == "/home/you/Desktop/old"
    assert ["remember", "/home/you/Desktop/old"] in flow["ops"]


def test_not_now_on_the_attach_screen_goes_back_to_the_open_brain(browser: dict) -> None:
    back = browser["attachNotNow"]
    assert back["dashboardShown"] is True
    assert back["title"] == "Test Gym"
    assert back["calls"] == [{"path": "/home/you/Desktop/old", "plan": True}], "plan only"


def test_the_menu_button_owns_the_drawer(browser: dict) -> None:
    drawer = browser["drawerWiring"]
    assert drawer["before"] == {"expanded": "false", "open": False}
    assert drawer["opened"] == {"expanded": "true", "open": True, "focused": "btn-drawer-close"}
    assert drawer["closed"] == {"expanded": "false", "open": False, "focused": "btn-menu"}
    assert drawer["afterTab"] == {"expanded": "false", "view": "commands"}


# --- the folder browser: /api/browse ---------------------------------------------------
# The page lists one level of directories at a time and never reads a file. These run
# against a bound server so the token gate and the JSON shape are what the browser sees.

BROWSE_TOKEN = "browse-test-token-0123456789"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@contextlib.contextmanager
def _serving(root: Path):
    server = create_server(root, port=0, token=BROWSE_TOKEN)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _post(server, path: str, body: dict, *, token: str | None = BROWSE_TOKEN):
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    if token is not None:
        request.add_header(TOKEN_HEADER, token)
    try:
        with _OPENER.open(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _get(server, path: str, *, token: str | None = BROWSE_TOKEN):
    request = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}")
    if token is not None:
        request.add_header(TOKEN_HEADER, token)
    with _OPENER.open(request, timeout=30) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "places"
    (root / "plain").mkdir(parents=True)
    (root / ".hidden").mkdir()
    (root / "a-file.txt").write_text("not a folder", encoding="utf-8")
    setup_repo(root / "brain", "Browse Co", "all", mode="in-house", apply=True)
    return root


def test_browse_lists_directories_and_flags_the_brain(tree: Path) -> None:
    with _serving(tree) as server:
        status, body = _post(server, "/api/browse", {"path": str(tree)})
    assert status == 200
    assert body["error"] is None
    assert body["path"] == str(tree)
    assert body["parent"] == str(tree.parent)
    assert body["is_brain"] is False and body["brain"] is None
    # Hidden directories and files are not offered; the rest is sorted by name.
    assert [child["name"] for child in body["children"]] == ["brain", "plain"]
    brain, plain = body["children"]
    assert brain["is_brain"] is True
    assert brain["brain"] == {"name": "Browse Co", "mode": "in-house", "legacy": False}
    assert brain["path"] == str(tree / "brain")
    assert plain["is_brain"] is False and plain["brain"] is None


def test_browse_describes_a_brain_folder_itself(tree: Path) -> None:
    with _serving(tree) as server:
        _, body = _post(server, "/api/browse", {"path": str(tree / "brain")})
    assert body["is_brain"] is True
    assert body["brain"] == {"name": "Browse Co", "mode": "in-house", "legacy": False}
    assert body["parent"] == str(tree)


def test_browse_reports_a_missing_folder_with_the_nearest_parent(tree: Path) -> None:
    missing = tree / "plain" / "gone" / "deeper"
    with _serving(tree) as server:
        status, body = _post(server, "/api/browse", {"path": str(missing)})
    assert status == 200
    assert body["error"]
    assert body["children"] == []
    assert body["is_brain"] is False
    assert body["parent"] == str(tree / "plain")


def test_browse_expands_the_home_tilde(tree: Path, monkeypatch) -> None:
    # expanduser reads the environment, which is also what the operator's shell does:
    # HOME on POSIX, USERPROFILE on Windows.
    monkeypatch.setenv("HOME", str(tree))
    monkeypatch.setenv("USERPROFILE", str(tree))
    with _serving(tree) as server:
        _, body = _post(server, "/api/browse", {"path": "~/plain"})
    assert body["path"] == str(tree / "plain")
    assert body["error"] is None


def test_browse_starts_at_the_first_place_when_nothing_is_typed(tree: Path, monkeypatch) -> None:
    from marketing_os.ui import places

    monkeypatch.setattr(places.Path, "home", lambda: tree)
    monkeypatch.setattr(places, "desktop_dir", lambda **kwargs: None)
    with _serving(tree) as server:
        _, body = _post(server, "/api/browse", {"path": ""})
    assert body["path"] == str(tree)
    assert [child["name"] for child in body["children"]] == ["brain", "plain"]


def test_browse_requires_the_session_token(tree: Path) -> None:
    with _serving(tree) as server:
        status, body = _post(server, "/api/browse", {"path": str(tree)}, token=None)
        wrong, _ = _post(server, "/api/browse", {"path": str(tree)}, token="nope")
    assert status == 403 and wrong == 403
    assert body["envelope"]["findings"][0]["code"] == "invalid-token"


def test_browse_never_descends_into_kernel_views(tree: Path) -> None:
    with _serving(tree) as server:
        _, body = _post(server, "/api/browse", {"path": "/proc"})
    assert body["error"]
    assert body["children"] == []


def test_browse_refuses_a_non_string_path(tree: Path) -> None:
    with _serving(tree) as server:
        status, _ = _post(server, "/api/browse", {"path": 7})
    assert status == 400


# --- the native folder window: /api/pick-folder --------------------------------------
# The dialog itself is never opened here (it would land on a real screen and wait). The
# picker is replaced wholesale; what is under test is the route: its guards, its body
# check, and that the picker's answer reaches the page untouched.


def _picker_says(monkeypatch, **answer):
    seen: list[object] = []

    def fake(start, **kwargs):
        seen.append(start)
        return dict({"path": None, "cancelled": False, "available": True, "busy": False,
                     "error": None, "backend": "wsl"}, **answer)

    monkeypatch.setattr("marketing_os.ui.server.pick_folder", fake)
    return seen


def test_pick_folder_returns_the_chosen_path(tree: Path, monkeypatch) -> None:
    seen = _picker_says(monkeypatch, path=str(tree / "plain"))
    with _serving(tree) as server:
        status, body = _post(server, "/api/pick-folder", {"start": str(tree)})
    assert status == 200
    assert body["path"] == str(tree / "plain")
    assert body["cancelled"] is False and body["available"] is True
    assert seen == [str(tree)]


def test_pick_folder_reports_a_closed_window(tree: Path, monkeypatch) -> None:
    seen = _picker_says(monkeypatch, cancelled=True)
    with _serving(tree) as server:
        status, body = _post(server, "/api/pick-folder", {"start": None})
    assert status == 200
    assert body == {"path": None, "cancelled": True, "available": True, "busy": False,
                    "error": None, "backend": "wsl"}
    assert seen == [None]


def test_pick_folder_reports_that_no_window_can_open(tree: Path, monkeypatch) -> None:
    _picker_says(monkeypatch, available=False, error="No folder window can open here.",
                 backend="none")
    with _serving(tree) as server:
        status, body = _post(server, "/api/pick-folder", {})
    assert status == 200
    assert body["available"] is False
    assert body["error"] == "No folder window can open here."


def test_pick_folder_requires_the_session_token(tree: Path, monkeypatch) -> None:
    seen = _picker_says(monkeypatch, path=str(tree))
    with _serving(tree) as server:
        status, body = _post(server, "/api/pick-folder", {"start": None}, token=None)
        wrong, _ = _post(server, "/api/pick-folder", {"start": None}, token="nope")
    assert status == 403 and wrong == 403
    assert body["envelope"]["findings"][0]["code"] == "invalid-token"
    assert seen == [], "a refused request must never open a window"


def test_pick_folder_refuses_a_non_string_start(tree: Path, monkeypatch) -> None:
    seen = _picker_says(monkeypatch, path=str(tree))
    with _serving(tree) as server:
        status, _ = _post(server, "/api/pick-folder", {"start": 7})
    assert status == 400
    assert seen == []


def test_pick_folder_never_raises_through_the_route(tree: Path, monkeypatch) -> None:
    def explode(start, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("marketing_os.ui.server.pick_folder", explode)
    with _serving(tree) as server:
        status, body = _post(server, "/api/pick-folder", {"start": None})
    assert status == 500
    assert body["envelope"]["findings"][0]["code"] == "ui-handler-error"


@pytest.mark.parametrize("answer", [True, False])
def test_app_state_says_whether_a_folder_window_can_open(
    tree: Path, monkeypatch, answer: bool
) -> None:
    monkeypatch.setattr("marketing_os.ui.server.picker_available", lambda: answer)
    with _serving(tree) as server:
        _, state = _get(server, "/api/state")
    assert state["picker"] is answer


def test_app_state_carries_the_places_and_only_the_first_places_brains(
    tree: Path, monkeypatch
) -> None:
    """The brain sits in the home folder; the desktop is the first place. The state
    payload looks in the first place alone, so a home folder full of scratch copies never
    reaches the page; and it looks there once, through `brains`, not through a second
    key nothing reads."""
    from marketing_os.ui import places

    monkeypatch.setattr(places.Path, "home", lambda: tree)
    monkeypatch.setattr(places, "desktop_dir", lambda **kwargs: tree / "plain")
    with _serving(tree / "plain") as server:
        _, state = _get(server, "/api/state")
    assert state["home"] == str(tree)
    assert state["places"] == [
        {"path": str(tree / "plain"), "kind": "desktop"},
        {"path": str(tree), "kind": "home"},
    ]
    assert state["brains"] == []
    assert "existing_brains" not in state


def test_app_state_finds_the_brains_in_the_first_place(tree: Path, monkeypatch) -> None:
    from marketing_os.ui import places

    monkeypatch.setattr(places.Path, "home", lambda: tree / "plain")
    monkeypatch.setattr(places, "desktop_dir", lambda **kwargs: tree)
    with _serving(tree / "plain") as server:
        _, state = _get(server, "/api/state")
    assert state["places"][0] == {"path": str(tree), "kind": "desktop"}
    assert state["brains"] == [
        {
            "path": str(tree / "brain"),
            "name": "Browse Co",
            "mode": "in-house",
            "legacy": False,
            "attachable": False,
            "is_brain": True,
            "exists": True,
            "last_opened": None,
        }
    ]


# --- the brain registry, over HTTP ------------------------------------------------------


def _second_brain(tmp_path: Path) -> Path:
    other = tmp_path / "elsewhere" / "second"
    setup_repo(other, "Second Co", "all", mode="agency", apply=True)
    return other


def test_app_state_carries_every_known_brain(tree: Path, tmp_path: Path) -> None:
    """The server's own root is registered on the first state request; the registry
    plus the first place's brains come back as `brains`, each with `exists`."""
    from marketing_os.ui import registry

    second = _second_brain(tmp_path)
    registry.remember(second)
    with _serving(tree / "brain") as server:
        _, state = _get(server, "/api/state")
    by_path = {brain["path"]: brain for brain in state["brains"]}
    assert str(tree / "brain") in by_path, "the folder the server runs in is a known brain"
    assert by_path[str(tree / "brain")]["name"] == "Browse Co"
    assert by_path[str(second)] == {
        "path": str(second),
        "name": "Second Co",
        "mode": "agency",
        "legacy": False,
        "attachable": False,
        "is_brain": True,
        "exists": True,
        "last_opened": by_path[str(second)]["last_opened"],
    }
    assert registry.load()["brains"][0]["path"] in (str(tree / "brain"), str(second))


def test_a_scratch_root_is_not_registered_as_a_brain(tree: Path) -> None:
    from marketing_os.ui import registry

    with _serving(tree / "plain") as server:
        _get(server, "/api/state")
    assert registry.load()["brains"] == []


def test_app_state_answers_for_another_root_on_request(tree: Path, tmp_path: Path) -> None:
    second = _second_brain(tmp_path)
    with _serving(tree / "brain") as server:
        _, own = _get(server, "/api/state")
        _, other = _get(server, f"/api/state?path={urllib.parse.quote(str(second))}")
    assert own["root"] == str(tree / "brain") and own["business_name"] == "Browse Co"
    assert other["root"] == str(second)
    assert other["business_name"] == "Second Co" and other["mode"] == "agency"
    assert other["is_brain"] is True
    assert other["status"]["repo"] == str(second)
    assert other["doctor"]["repo"] == str(second)
    assert other["schema"] == own["schema"]
    assert other["port"] == own["port"], "the envelope is the same shape, for another root"
    assert [b["path"] for b in other["brains"]] == [b["path"] for b in own["brains"]]


@pytest.mark.parametrize("value", ["relative/folder", "", "/definitely/not/here/at/all"])
def test_app_state_refuses_a_root_that_is_not_an_existing_absolute_folder(
    tree: Path, value: str
) -> None:
    with _serving(tree) as server:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/state?path={urllib.parse.quote(value)}"
        )
        request.add_header(TOKEN_HEADER, BROWSE_TOKEN)
        with pytest.raises(urllib.error.HTTPError) as caught:
            _OPENER.open(request, timeout=30)
    assert caught.value.code == 400
    body = json.loads(caught.value.read().decode("utf-8"))
    assert body["envelope"]["findings"][0]["code"] == "bad-path"


@pytest.mark.parametrize("value", ["/proc", "/proc/self", "/sys", "/dev"])
def test_app_state_for_another_root_never_descends_into_kernel_views(
    tree: Path, value: str
) -> None:
    """The same never-descend guard as /api/browse: a kernel view is an existing absolute
    folder, and still not one the page may be pointed at."""
    with _serving(tree) as server:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/state?path={urllib.parse.quote(value)}"
        )
        request.add_header(TOKEN_HEADER, BROWSE_TOKEN)
        with pytest.raises(urllib.error.HTTPError) as caught:
            _OPENER.open(request, timeout=30)
    assert caught.value.code == 400
    body = json.loads(caught.value.read().decode("utf-8"))
    assert body["envelope"]["findings"][0]["code"] == "bad-path"


def test_app_state_expands_only_the_operators_own_tilde(tree: Path, monkeypatch) -> None:
    monkeypatch.setattr("marketing_os.ui.server.home_dir", lambda: tree)
    with _serving(tree / "plain") as server:
        _, bare = _get(server, "/api/state?path=~")
        _, nested = _get(server, "/api/state?path=" + urllib.parse.quote("~/brain"))
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/state?path={urllib.parse.quote('~root')}"
        )
        request.add_header(TOKEN_HEADER, BROWSE_TOKEN)
        with pytest.raises(urllib.error.HTTPError) as caught:
            _OPENER.open(request, timeout=30)
    assert bare["root"] == str(tree)
    assert nested["root"] == str(tree / "brain") and nested["business_name"] == "Browse Co"
    assert caught.value.code == 400, "~otheruser is another account's home, never expanded"


def test_app_state_for_another_root_still_needs_the_token(tree: Path) -> None:
    with _serving(tree) as server:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/state?path={urllib.parse.quote(str(tree))}"
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            _OPENER.open(request, timeout=30)
    assert caught.value.code == 403


def test_brains_remember_and_forget_round_trip(tree: Path, tmp_path: Path) -> None:
    from marketing_os.ui import registry

    second = _second_brain(tmp_path)
    with _serving(tree / "plain") as server:
        status, remembered = _post(server, "/api/brains", {"op": "remember", "path": str(second)})
        assert status == 200
        assert str(second) in [b["path"] for b in remembered["brains"]]
        assert registry.load()["brains"][0]["path"] == str(second)

        status, forgotten = _post(server, "/api/brains", {"op": "forget", "path": str(second)})
    assert status == 200
    assert str(second) not in [b["path"] for b in forgotten["brains"]]
    assert registry.load()["brains"] == []


def test_a_forgotten_brain_that_still_sits_in_the_first_place_stays_listed(
    tree: Path, monkeypatch
) -> None:
    """Forget drops the registry record; the scan of the first place is a separate
    fact, and a brain sitting on the desktop is still on the desktop."""
    from marketing_os.ui import places

    monkeypatch.setattr(places.Path, "home", lambda: tree / "plain")
    monkeypatch.setattr(places, "desktop_dir", lambda **kwargs: tree)
    with _serving(tree / "plain") as server:
        _, body = _post(server, "/api/brains", {"op": "forget", "path": str(tree / "brain")})
    assert [b["path"] for b in body["brains"]] == [str(tree / "brain")]
    assert body["brains"][0]["last_opened"] is None


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"op": "rename", "path": "/tmp"}, "bad-request"),
        ({"op": "remember"}, "bad-request"),
        ({"op": "remember", "path": ""}, "bad-request"),
        ({"op": "remember", "path": 42}, "bad-request"),
        ({"op": "remember", "path": "relative/place"}, "bad-path"),
        ({"op": "remember", "path": "/definitely/not/here/at/all"}, "bad-path"),
        ({"op": "forget", "path": "relative/place"}, "bad-path"),
    ],
)
def test_brains_refuses_a_bad_request(tree: Path, payload: dict, code: str) -> None:
    from marketing_os.ui import registry

    with _serving(tree) as server:
        status, body = _post(server, "/api/brains", payload)
    assert status == 400
    assert body["envelope"]["findings"][0]["code"] == code
    assert registry.load()["brains"] == []


def test_brains_requires_the_session_token(tree: Path) -> None:
    with _serving(tree) as server:
        status, body = _post(
            server, "/api/brains", {"op": "remember", "path": str(tree)}, token=None
        )
    assert status == 403
    assert body["envelope"]["findings"][0]["code"] == "invalid-token"


# --- the path a command targets, over HTTP -----------------------------------------------
# A relative path reaches the CLI as relative to the server's cwd, which under the app is
# wherever `mos ui` was started. That is how `C:/Users/you/Desktop/foo` once planned a
# brain inside the repo. The route refuses anything that is not a full path, and under
# WSL converts a Windows spelling first.


@pytest.mark.parametrize("value", ["relative/brain", ".", "brain"])
def test_run_refuses_a_path_that_is_not_a_full_path(tree: Path, value: str) -> None:
    with _serving(tree) as server:
        status, body = _post(server, "/api/run", {"command": "status", "args": {"path": value}})
    assert status == 400
    assert body["envelope"]["findings"][0]["code"] == "bad-path"


def test_run_refuses_a_windows_path_where_wslpath_cannot_convert_it(
    tree: Path, monkeypatch
) -> None:
    monkeypatch.setattr("marketing_os.ui.server.windows_to_wsl", lambda value: None)
    before = sorted(tree.iterdir())
    with _serving(tree) as server:
        status, body = _post(
            server,
            "/api/run",
            {"command": "onboard", "args": {"path": "C:/Users/you/Desktop/foo", "plan": True}},
        )
    assert status == 400
    assert body["envelope"]["findings"][0]["code"] == "bad-path"
    assert sorted(tree.iterdir()) == before, "nothing is planned relative to the server's cwd"


def test_run_refuses_a_windows_path_outside_wsl(tree: Path, monkeypatch) -> None:
    """Off WSL the spelling comes back unchanged; on this side it is not a full path."""
    monkeypatch.setattr("marketing_os.ui.server.windows_to_wsl", lambda value: value)
    with _serving(tree) as server:
        status, body = _post(
            server, "/api/run", {"command": "status", "args": {"path": FOREIGN_FULL_PATH}}
        )
    assert status == 400
    assert body["envelope"]["findings"][0]["code"] == "bad-path"


def test_run_converts_a_windows_path_under_wsl_before_dispatch(
    tree: Path, monkeypatch
) -> None:
    seen: list[str] = []

    def convert(value: str) -> str:
        seen.append(value)
        return str(tree / "brain")

    monkeypatch.setattr("marketing_os.ui.server.windows_to_wsl", convert)
    with _serving(tree) as server:
        status, body = _post(
            server,
            "/api/run",
            {"command": "status", "args": {"path": "C:\\Users\\you\\Desktop\\brain"}},
        )
    assert status == 200
    assert seen == ["C:\\Users\\you\\Desktop\\brain"]
    assert body["envelope"]["repo"] == str(tree / "brain")
    assert body["envelope"]["business"]["name"] == "Browse Co"
    assert body["command_line"] == f"mos status -- {tree / 'brain'}"


def test_a_read_only_command_does_not_wait_for_the_server_lock(tree: Path) -> None:
    """The lock serialises writes. A status probe, a plan, and the state request itself
    must answer while an install holds it, or the page freezes behind every --yes."""
    with _serving(tree) as server, server.lock:
        status, body = _post(
            server, "/api/run", {"command": "status", "args": {"path": str(tree / "brain")}}
        )
        planned, plan = _post(
            server,
            "/api/run",
            {"command": "index sync", "args": {"path": str(tree / "brain"), "plan": True}},
        )
        state_status, state = _get(server, "/api/state")
    assert status == 200 and body["envelope"]["business"]["name"] == "Browse Co"
    assert planned == 200 and plan["envelope"]["command"] == "index-sync"
    assert state_status == 200 and state["schema"] == "mos.ui-app-state.v1"


def test_a_mutating_command_takes_the_server_lock(tree: Path) -> None:
    import time

    with _serving(tree) as server:
        server.lock.acquire()
        done: list[tuple[int, dict]] = []
        worker = threading.Thread(
            target=lambda: done.append(
                _post(
                    server,
                    "/api/run",
                    {"command": "index sync", "args": {"path": str(tree / "brain"), "yes": True}},
                )
            ),
            daemon=True,
        )
        worker.start()
        time.sleep(0.5)
        assert done == [], "a --yes command waits for the lock"
        server.lock.release()
        worker.join(timeout=60)
    assert done and done[0][0] == 200


# --- the page against the fixes above ----------------------------------------------------


def test_a_typed_path_that_is_not_full_is_named_and_never_probed(browser: dict) -> None:
    typed = browser["typedRelativePathIsNotProbed"]
    relative = typed["relative"]
    assert relative["readout"].startswith("That is not a full path.")
    assert relative["live"] == relative["readout"]
    assert relative["probed"] == ["/home/you/Desktop"], "only the default place was probed"
    assert relative["browsed"] == ["/home/you/Desktop"], "and only it was looked in"
    assert relative["probedAfterContinue"] == relative["probed"], "Continue sends nothing"
    assert relative["readoutAfterContinue"].startswith("That is not a full path.")
    # A Windows spelling is a full path; the server converts it under WSL.
    assert typed["windows"]["probed"][-1] == "C:\\Users\\you\\Desktop"
    assert "not a full path" not in typed["windows"]["readout"]


def test_a_listed_folder_that_lost_its_brain_is_greyed_and_forgettable(browser: dict) -> None:
    hollow = browser["notABrainRow"]
    assert hollow["row"]["tags"] == ["not a brain"]
    assert hollow["row"]["disabled"] == "true"
    assert hollow["row"]["forget"] == [["Forget", "Forget Hollow Co"]]
    assert hollow["stillHere"] == "Test Gym" and hollow["stateCalls"] == 0
    # Rows without the flag (an older server, or a real brain) are untouched.
    assert hollow["others"] == [
        ["Test Gym", None], ["Second Co", None], ["Gone Co", "true"], ["Old Co", None]
    ]


def test_a_switch_the_server_refuses_moves_nothing(browser: dict) -> None:
    refused = browser["switchToVanishedBrain"]
    assert refused["before"]["tags"] == [] and refused["before"]["disabled"] is None
    assert refused["stored"] is None, "nothing was committed before the server answered"
    assert refused["ops"] == [], "and the registry was not told it was opened"
    assert refused["title"] == "Test Gym" and refused["dashboardShown"] is True
    assert refused["current"] == ["Test Gym"]
    assert refused["toast"] == "Could not open Second Co: the folder is missing or not allowed."
    assert refused["live"].startswith("Could not open Second Co.")
    assert refused["after"]["tags"] == ["not found"] and refused["after"]["disabled"] == "true"
    assert refused["after"]["forget"] == [["Forget", "Forget Second Co"]]


def test_a_switch_to_a_folder_that_lost_its_brain_opens_the_wizard(browser: dict) -> None:
    hollow = browser["switchToHollowBrain"]
    assert hollow["stored"] == "/home/you/Desktop/second", "the folder is real, so it is opened"
    assert hollow["ops"] == [["remember", "/home/you/Desktop/second"]]
    assert hollow["wizardShown"] is True and hollow["dashboardShown"] is False


def test_attaching_a_folder_while_a_window_is_open_says_so_and_nothing_else(
    browser: dict,
) -> None:
    busy = browser["attachFolderWhileWindowOpen"]
    assert busy["posted"] == 1
    assert busy["live"] == "A folder window is already open. Finish with that one."
    assert busy["attachShown"] is False and busy["wizardShown"] is False
    assert busy["panelHidden"] is True, "never the in-page list"
    assert busy["dashboardShown"] is True
    # Two more presses while one request is out: one request, one sentence.
    assert busy["pending"] == 2
    assert busy["pendingLive"] == "A folder window is already open. Finish with that one."
    assert busy["afterCancel"] == "No folder chosen."


def test_the_business_can_be_renamed_from_the_header(browser: dict) -> None:
    """The title gives way to a form; the plan is previewed, the apply is the one filled
    button while it is offered, and a rename closes the form, says so and re-reads."""
    seen = browser["renameFromHeader"]
    root = browser["root"]
    assert seen["opened"] is True and seen["prefilled"] == "Test Gym"
    assert seen["focused"] is True, "focus moves into the input"
    assert seen["titleHidden"] is True
    assert seen["headerPrimary"] == 0, "the header action steps back while editing"
    assert seen["planned"] == [{"path": root, "name": "Test Gym Two", "plan": True}]
    assert seen["applyShown"] is True
    assert seen["readoutLabel"] == "Preview only, nothing written"
    assert seen["calls"][-1] == {"path": root, "name": "Test Gym Two", "yes": True}
    assert "status" in seen["afterApply"] and "doctor" in seen["afterApply"], "re-read after"
    assert seen["toast"] == "Renamed to Test Gym Two"
    assert seen["closed"] is True and seen["titleShown"] is True
    assert seen["focusedAfter"] == "btn-rename"
    assert seen["headerPrimaryAfter"] == 1, "the header action comes back"


def test_open_in_claude_code_is_one_press_and_says_where_it_opened(browser: dict) -> None:
    """The quick action runs `mos open` for this brain and repeats the envelope's own
    sentence; the lines stay behind their closed disclosure as the fallback."""
    seen = browser["openFromQuickActions"]
    assert seen["calls"] == [{"path": browser["root"]}]
    assert seen["toast"].startswith("Claude Code is opening in a console window")
    assert seen["linesOpen"] is False
    assert seen["failShown"] is False
