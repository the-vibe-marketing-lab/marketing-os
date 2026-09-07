"""The native folder window: which backend a machine gets, and what each answer means.

No dialog is ever opened here. Every subprocess goes through an injected ``run`` that
records the argv and answers from a script, so the suite can prove the PowerShell that
would run, the wslpath round trip, and the cancel/timeout/failure paths without a
window ever landing on a real screen.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path

import pytest

from marketing_os.ui import picker
from marketing_os.ui.picker import Host, backend_for, pick_folder, picker_available

WIN_DESKTOP = "C:\\Users\\you\\Desktop"


def which_of(*names: str):
    present = set(names)
    return lambda name: f"/bin/{name}" if name in present else None


def machine(
    platform: str = "linux",
    *,
    wsl: bool = False,
    display: bool = True,
    tkinter: bool = True,
    interop: bool = True,
    binaries: tuple[str, ...] = (),
) -> Host:
    return Host(
        platform=platform,
        wsl=wsl,
        display=display,
        which=which_of(*binaries),
        tkinter=tkinter,
        interop=interop,
    )


class Script:
    """A scripted ``subprocess.run``: answers keyed by argv[0], every call recorded."""

    def __init__(self, **answers) -> None:
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        answer = self.answers.get(Path(argv[0]).name)
        if answer is None:
            raise FileNotFoundError(argv[0])
        if callable(answer):
            answer = answer(argv)
        if isinstance(answer, BaseException):
            raise answer
        code, stdout, stderr = answer
        return subprocess.CompletedProcess(argv, code, stdout, stderr)


def decoded_powershell(argv: list[str]) -> str:
    encoded = argv[argv.index("-EncodedCommand") + 1]
    return base64.b64decode(encoded).decode("utf-16-le")


# --- which backend --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        (machine(wsl=True, display=False, binaries=("powershell.exe",)), "wsl"),
        (machine(wsl=True, display=False, binaries=()), None),
        # powershell.exe on PATH but no binfmt registration: it cannot be run from here.
        (machine(wsl=True, display=False, interop=False, binaries=("powershell.exe",)), None),
        (machine(wsl=True, interop=False, binaries=("powershell.exe", "zenity")), "zenity"),
        (machine(wsl=True, binaries=()), "tkinter"),
        (machine("win32", display=False, binaries=("powershell",)), "windows"),
        (machine("win32", display=False, binaries=("pwsh",)), "windows"),
        (machine("win32", display=False, binaries=()), None),
        (machine("darwin", display=False, binaries=("osascript",)), "macos"),
        (machine("darwin", display=False, binaries=()), None),
        (machine(binaries=("zenity", "kdialog")), "zenity"),
        (machine(binaries=("kdialog",)), "kdialog"),
        (machine(binaries=()), "tkinter"),
        (machine(binaries=(), tkinter=False), None),
        (machine(display=False, binaries=("zenity",)), None),
    ],
)
def test_the_first_backend_that_can_open_wins(host: Host, expected: str | None) -> None:
    assert backend_for(host) == expected
    assert picker_available(host) is (expected is not None)


def test_interop_is_read_from_binfmt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(picker, "_BINFMT", tmp_path / "missing")
    assert picker._wsl_interop_enabled() is True, "no evidence either way means yes"
    binfmt = tmp_path / "binfmt_misc"
    binfmt.mkdir()
    (binfmt / "register").write_text("", encoding="utf-8")
    monkeypatch.setattr(picker, "_BINFMT", binfmt)
    assert picker._wsl_interop_enabled() is False
    (binfmt / "WSLInterop-late").write_text("enabled", encoding="utf-8")
    assert picker._wsl_interop_enabled() is True


def test_this_machine_is_probed_without_raising() -> None:
    """A real probe, no window: just the answer to 'could one open here?'"""
    assert picker_available() in (True, False)


def test_no_backend_means_unavailable_and_nothing_runs() -> None:
    run = Script()
    answer = pick_folder("/tmp", run=run, machine=machine(binaries=(), tkinter=False))
    assert answer == {
        "path": None,
        "cancelled": False,
        "available": False,
        "busy": False,
        "error": "No folder window can open here.",
        "backend": "none",
    }
    assert run.calls == []


# --- WSL: PowerShell through the interop, paths converted both ways --------------------


def test_wsl_runs_the_winforms_dialog_and_converts_both_ways(tmp_path: Path) -> None:
    run = Script(
        wslpath=lambda argv: (
            (0, WIN_DESKTOP + "\n", "")
            if argv[1] == "-w"
            else (0, "/mnt/c/Users/you/Desktop/Brain Co\n", "")
        ),
        **{"powershell.exe": (0, "\ufeffC:\\Users\\you\\Desktop\\Brain Co\r\n", "")},
    )
    answer = pick_folder(tmp_path, run=run, machine=machine(wsl=True, binaries=("powershell.exe",)))
    assert answer["path"] == "/mnt/c/Users/you/Desktop/Brain Co"
    assert answer["backend"] == "wsl" and answer["cancelled"] is False
    assert answer["available"] is True and answer["error"] is None

    to_windows, dialog, back = run.calls
    assert to_windows == ["wslpath", "-w", str(tmp_path)]
    assert back == ["wslpath", "-u", "C:\\Users\\you\\Desktop\\Brain Co"]
    assert dialog[:6] == [
        "powershell.exe",
        "-NoProfile",
        "-STA",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
    ]
    script = decoded_powershell(dialog)
    assert "Add-Type -AssemblyName System.Windows.Forms" in script
    assert "New-Object System.Windows.Forms.FolderBrowserDialog" in script
    assert f"$dialog.SelectedPath = '{WIN_DESKTOP}'" in script
    assert "$dialog.ShowNewFolderButton = $true" in script
    assert f"$dialog.Description = '{picker.PROMPT}'" in script
    assert "[System.Windows.Forms.DialogResult]::OK" in script
    assert "[Console]::Out.Write($dialog.SelectedPath)" in script


def test_wsl_reports_a_closed_window_as_cancelled(tmp_path: Path) -> None:
    run = Script(wslpath=(0, WIN_DESKTOP, ""), **{"powershell.exe": (0, "", "")})
    answer = pick_folder(tmp_path, run=run, machine=machine(wsl=True, binaries=("powershell.exe",)))
    assert answer["cancelled"] is True and answer["path"] is None
    assert answer["available"] is True and answer["error"] is None
    assert [call[0] for call in run.calls] == ["wslpath", "powershell.exe"]


def test_wsl_with_no_start_folder_omits_the_selected_path() -> None:
    run = Script(**{"powershell.exe": (0, "", "")})
    pick_folder(None, run=run, machine=machine(wsl=True, binaries=("powershell.exe",)))
    (dialog,) = run.calls
    assert "$dialog.SelectedPath = " not in decoded_powershell(dialog)


def test_a_missing_start_folder_climbs_to_the_nearest_existing_parent(tmp_path: Path) -> None:
    run = Script(wslpath=(0, WIN_DESKTOP, ""), **{"powershell.exe": (0, "", "")})
    pick_folder(
        tmp_path / "not" / "yet",
        run=run,
        machine=machine(wsl=True, binaries=("powershell.exe",)),
    )
    assert run.calls[0] == ["wslpath", "-w", str(tmp_path)]


def test_a_failed_dialog_reports_its_last_line(tmp_path: Path) -> None:
    run = Script(
        wslpath=(0, WIN_DESKTOP, ""),
        **{"powershell.exe": (1, "", "Add-Type : Cannot add type.\nAt line:2 char:1")},
    )
    answer = pick_folder(tmp_path, run=run, machine=machine(wsl=True, binaries=("powershell.exe",)))
    assert answer["cancelled"] is False and answer["path"] is None
    assert answer["error"] == "The folder window failed: At line:2 char:1"


def test_a_window_that_never_answers_is_a_cancel_with_the_reason(tmp_path: Path) -> None:
    """The window opened; nobody answered it. That is a cancel, so the page keeps its
    place and never falls back to the in-page list as if no window could open."""
    run = Script(
        wslpath=(0, WIN_DESKTOP, ""),
        **{"powershell.exe": subprocess.TimeoutExpired(["powershell.exe"], 7)},
    )
    answer = pick_folder(
        tmp_path, timeout=7, run=run, machine=machine(wsl=True, binaries=("powershell.exe",))
    )
    assert answer["cancelled"] is True and answer["available"] is True
    assert answer["busy"] is False and answer["path"] is None
    assert answer["error"] == "The folder window did not answer within 7 seconds."
    assert answer["backend"] == "wsl"


def test_the_default_timeout_is_two_minutes() -> None:
    assert picker.DEFAULT_TIMEOUT == 120


def test_a_crashing_backend_never_raises(tmp_path: Path) -> None:
    run = Script(wslpath=(0, WIN_DESKTOP, ""))  # powershell.exe is not scripted -> OSError
    answer = pick_folder(tmp_path, run=run, machine=machine(wsl=True, binaries=("powershell.exe",)))
    assert answer["available"] is False
    assert answer["error"].startswith("FileNotFoundError")


def test_the_dialog_command_is_bounded_by_the_timeout(tmp_path: Path) -> None:
    seen = {}

    def run(argv, **kwargs):
        seen[Path(argv[0]).name] = kwargs.get("timeout")
        return subprocess.CompletedProcess(argv, 0, WIN_DESKTOP if argv[0] == "wslpath" else "", "")

    wsl = machine(wsl=True, binaries=("powershell.exe",))
    pick_folder(tmp_path, timeout=42, run=run, machine=wsl)
    assert seen["powershell.exe"] == 42
    assert seen["wslpath"] == picker._CONVERT_TIMEOUT


@pytest.mark.skipif(shutil.which("wslpath") is None, reason="wslpath only exists under WSL")
def test_wslpath_really_round_trips_a_desktop_path() -> None:
    """The one real subprocess in this file. wslpath opens no window."""
    here = Path("/mnt/c/Users")
    if not here.is_dir():
        pytest.skip("no Windows drive mounted")
    windows = picker._wslpath(subprocess.run, "-w", str(here))
    assert windows is not None and windows.startswith("C:\\")
    assert picker._wslpath(subprocess.run, "-u", windows) == str(here)


def test_native_windows_uses_powershell_without_wslpath() -> None:
    run = Script(powershell=(0, "C:\\Brains\\Acme", ""))
    answer = pick_folder("C:\\Brains", run=run, machine=machine("win32", binaries=("powershell",)))
    assert answer["path"] == "C:\\Brains\\Acme" and answer["backend"] == "windows"
    assert [call[0] for call in run.calls] == ["powershell"]


def test_a_second_click_while_the_window_is_open_does_not_stack_another(tmp_path: Path) -> None:
    run = Script(**{"powershell.exe": (0, "", "")})
    with picker._BUSY:
        answer = pick_folder(None, run=run, machine=machine(wsl=True, binaries=("powershell.exe",)))
    assert answer["path"] is None and answer["cancelled"] is False
    assert answer["busy"] is True and answer["available"] is True
    assert answer["error"] == "A folder window is already open. Finish with that one."
    assert run.calls == []


# --- macOS --------------------------------------------------------------------------------


def test_mac_asks_finder_through_osascript(tmp_path: Path) -> None:
    run = Script(osascript=(0, "/Users/you/Brains/\n", ""))
    answer = pick_folder(tmp_path, run=run, machine=machine("darwin", binaries=("osascript",)))
    assert answer["path"] == "/Users/you/Brains" and answer["backend"] == "macos"
    (argv,) = run.calls
    assert argv[:2] == ["osascript", "-e"]
    # AppleScript doubles a backslash inside a string, so a Windows tmp_path arrives escaped.
    quoted = str(tmp_path).replace("\\", "\\\\")
    assert argv[2] == (
        f'POSIX path of (choose folder with prompt "{picker.PROMPT}" '
        f'default location POSIX file "{quoted}")'
    )


def test_mac_reports_a_closed_window_as_cancelled() -> None:
    run = Script(osascript=(1, "", "execution error: User canceled. (-128)"))
    answer = pick_folder(None, run=run, machine=machine("darwin", binaries=("osascript",)))
    assert answer["cancelled"] is True and answer["error"] is None


def test_mac_quotes_a_path_with_a_double_quote_in_it() -> None:
    run = Script(osascript=(0, "/x/\n", ""))
    pick_folder("/tmp", run=run, machine=machine("darwin", binaries=("osascript",)))
    assert picker.applescript('/Users/a "b"') == (
        f'POSIX path of (choose folder with prompt "{picker.PROMPT}" '
        'default location POSIX file "/Users/a \\"b\\"")'
    )


# --- Linux: zenity, then kdialog, then Tk ----------------------------------------------


def test_zenity_is_asked_for_a_directory(tmp_path: Path) -> None:
    run = Script(zenity=(0, "/home/you/Brains\n", ""))
    answer = pick_folder(tmp_path, run=run, machine=machine(binaries=("zenity", "kdialog")))
    assert answer["path"] == "/home/you/Brains" and answer["backend"] == "zenity"
    (argv,) = run.calls
    assert argv[:3] == ["zenity", "--file-selection", "--directory"]
    assert f"--title={picker.PROMPT}" in argv
    assert f"--filename={tmp_path}/" in argv


def test_zenity_exit_one_is_a_cancel() -> None:
    run = Script(zenity=(1, "", ""))
    answer = pick_folder(None, run=run, machine=machine(binaries=("zenity",)))
    assert answer["cancelled"] is True and answer["available"] is True


def test_kdialog_stands_in_when_zenity_is_missing(tmp_path: Path) -> None:
    run = Script(kdialog=(0, "/home/you/Brains\n", ""))
    answer = pick_folder(tmp_path, run=run, machine=machine(binaries=("kdialog",)))
    assert answer["path"] == "/home/you/Brains" and answer["backend"] == "kdialog"
    (argv,) = run.calls
    assert argv == ["kdialog", "--getexistingdirectory", str(tmp_path), "--title", picker.PROMPT]


def test_tkinter_runs_in_its_own_process_when_nothing_else_is_there(tmp_path: Path) -> None:
    run = Script(**{Path(picker.sys.executable).name: (0, "/home/you/Brains", "")})
    answer = pick_folder(tmp_path, run=run, machine=machine(binaries=()))
    assert answer["path"] == "/home/you/Brains" and answer["backend"] == "tkinter"
    (argv,) = run.calls
    assert argv[0] == picker.sys.executable and argv[1] == "-c"
    assert "filedialog.askdirectory" in argv[2]
    assert argv[3:] == [str(tmp_path), picker.PROMPT]


def test_tkinter_without_a_display_is_a_failure_not_a_cancel() -> None:
    run = Script(**{Path(picker.sys.executable).name: (1, "", "_tkinter.TclError: no display")})
    answer = pick_folder(None, run=run, machine=machine(binaries=()))
    assert answer["cancelled"] is False and answer["path"] is None
    assert answer["error"] == "The folder window failed: _tkinter.TclError: no display"


def test_tkinter_empty_answer_is_a_cancel() -> None:
    run = Script(**{Path(picker.sys.executable).name: (0, "", "")})
    answer = pick_folder(None, run=run, machine=machine(binaries=()))
    assert answer["cancelled"] is True
