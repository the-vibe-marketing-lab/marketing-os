from __future__ import annotations

from pathlib import Path

from marketing_os.core.launch import _sh_quote, launch_repo
from marketing_os.core.setup import setup_repo


def _brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    return root


class _Popen:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), **kwargs})
        return object()


def _which(available: dict[str, str]):
    return lambda name: available.get(name)


def test_wsl_hands_off_to_windows_terminal_with_the_resolved_executable(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    popen = _Popen()
    report = launch_repo(
        root,
        "claude",
        platform="wsl",
        which=_which({"claude": "/home/me/.local/bin/claude", "wt.exe": "/mnt/c/wt.exe"}),
        popen=popen,
    )
    assert report["ok"] is True and report["launched"] is True
    assert report["terminal"] == "Windows Terminal"
    assert popen.calls[0]["argv"] == [
        "wt.exe",
        "wsl.exe",
        "--cd",
        str(root.resolve()),
        "--exec",
        "/home/me/.local/bin/claude",
    ]
    assert popen.calls[0]["start_new_session"] is True
    assert "/mos-start" in report["next_action"]["reason"]


def test_wsl_without_windows_terminal_uses_a_console_window(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    popen = _Popen()
    report = launch_repo(
        root,
        platform="wsl",
        which=_which({"claude": "/usr/bin/claude", "cmd.exe": "/mnt/c/cmd.exe"}),
        popen=popen,
    )
    assert report["ok"] is True
    assert popen.calls[0]["argv"][:4] == ["cmd.exe", "/c", "start", ""]
    assert popen.calls[0]["cwd"] == "/mnt/c"


def test_mac_writes_a_command_file_and_opens_terminal(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    popen = _Popen()
    report = launch_repo(
        root,
        platform="darwin",
        which=_which({"claude": "/opt/bin/claude"}),
        popen=popen,
        launch_dir=tmp_path / "launch",
    )
    assert report["ok"] is True and report["terminal"] == "Terminal"
    argv = popen.calls[0]["argv"]
    assert argv[:3] == ["open", "-a", "Terminal"]
    script = Path(argv[3])
    assert script.read_text(encoding="utf-8") == (
        "#!/bin/sh\ncd '" + str(root.resolve()) + "' && exec '/opt/bin/claude'\n"
    )


def test_linux_picks_the_first_terminal_it_finds(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    popen = _Popen()
    report = launch_repo(
        root,
        platform="linux",
        which=_which({"claude": "/usr/bin/claude", "konsole": "/usr/bin/konsole"}),
        popen=popen,
    )
    assert report["ok"] is True and report["terminal"] == "konsole"
    assert popen.calls[0]["argv"] == [
        "konsole",
        "--workdir",
        str(root.resolve()),
        "-e",
        "/usr/bin/claude",
    ]


def test_a_missing_assistant_is_a_finding_and_nothing_is_opened(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    popen = _Popen()
    report = launch_repo(root, platform="linux", which=_which({}), popen=popen)
    assert report["ok"] is False and report["launched"] is False
    assert [item["code"] for item in report["findings"]] == ["runtime-not-found"]
    assert popen.calls == []


def test_a_folder_that_is_not_a_brain_is_refused(tmp_path: Path) -> None:
    popen = _Popen()
    report = launch_repo(
        tmp_path, platform="linux", which=_which({"claude": "/usr/bin/claude"}), popen=popen
    )
    assert report["ok"] is False
    assert [item["code"] for item in report["findings"]] == ["not-marketing-os"]
    assert popen.calls == []


def test_no_terminal_is_a_finding(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    popen = _Popen()
    report = launch_repo(
        root, platform="linux", which=_which({"claude": "/usr/bin/claude"}), popen=popen
    )
    assert report["ok"] is False
    assert [item["code"] for item in report["findings"]] == ["no-terminal"]


def test_a_prompt_never_touches_a_windows_command_line(tmp_path: Path) -> None:
    """Windows Terminal splits its command line on ``;`` and cmd.exe expands ``%`` and
    breaks on newlines, so on WSL and Windows the prompt goes into a launcher file and
    only that file's path reaches the terminal. Linux terminals take argv, so there the
    prompt is one element. Without a prompt, every argv is what it always was."""
    root = _brain(tmp_path)
    text = "Run `mos update --plan`; then `mos doctor .`.\n- 100% of it, with 'quotes'"
    launch_dir = tmp_path / "launch"

    popen = _Popen()
    report = launch_repo(
        root,
        "claude",
        prompt=text,
        platform="wsl",
        which=_which({"claude": "/home/me/.local/bin/claude", "wt.exe": "/mnt/c/wt.exe"}),
        popen=popen,
        launch_dir=launch_dir,
    )
    argv = popen.calls[0]["argv"]
    assert report["ok"] is True and report["prompted"] is True
    assert argv[:4] == ["wt.exe", "wsl.exe", "--exec", "/bin/sh"]
    assert text not in " ".join(argv) and ";" not in " ".join(argv)
    script = Path(argv[4]).read_text(encoding="utf-8")
    assert script == (
        "#!/bin/sh\ncd " + _sh_quote(str(root.resolve())) + " && exec "
        "'/home/me/.local/bin/claude' " + _sh_quote(text) + "\n"
    )
    assert "typed in" in report["next_action"]["reason"]

    popen = _Popen()
    launch_repo(
        root,
        prompt=text,
        platform="wsl",
        which=_which({"claude": "/usr/bin/claude", "cmd.exe": "/mnt/c/cmd.exe"}),
        popen=popen,
        launch_dir=launch_dir,
    )
    argv = popen.calls[0]["argv"]
    assert argv[:7] == ["cmd.exe", "/c", "start", "", "wsl.exe", "--exec", "/bin/sh"]
    assert text not in " ".join(argv)

    popen = _Popen()
    launch_repo(
        root,
        prompt=text,
        platform="windows",
        which=_which({"claude": "C:/claude.exe", "wt.exe": "C:/wt.exe"}),
        popen=popen,
        launch_dir=launch_dir,
    )
    argv = popen.calls[0]["argv"]
    assert argv[:9] == [
        "wt.exe",
        "-d",
        str(root.resolve()),
        "powershell.exe",
        "-NoExit",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        argv[8],
    ]
    assert argv[8].endswith(".ps1") and text not in " ".join(argv)
    ps1 = Path(argv[8]).read_text(encoding="utf-8")
    assert ps1 == (
        "Set-Location -LiteralPath '" + str(root.resolve()) + "'\n"
        "& 'C:/claude.exe' '" + text.replace("'", "''") + "'\n"
    )

    popen = _Popen()
    launch_repo(
        root,
        prompt=text,
        platform="windows",
        which=_which({"claude": "C:/claude.exe", "cmd.exe": "C:/cmd.exe"}),
        popen=popen,
        launch_dir=launch_dir,
    )
    argv = popen.calls[0]["argv"]
    assert argv[:5] == ["cmd.exe", "/c", "start", "", "powershell.exe"]
    assert text not in " ".join(argv)

    popen = _Popen()
    launch_repo(
        root,
        prompt=text,
        platform="darwin",
        which=_which({"claude": "/usr/local/bin/claude", "open": "/usr/bin/open"}),
        popen=popen,
        launch_dir=launch_dir,
    )
    script = Path(popen.calls[0]["argv"][3]).read_text(encoding="utf-8")
    assert script.endswith(" && exec '/usr/local/bin/claude' " + _sh_quote(text) + "\n")

    popen = _Popen()
    launch_repo(
        root,
        prompt=text,
        platform="linux",
        which=_which({"claude": "/usr/bin/claude", "gnome-terminal": "/usr/bin/gnome-terminal"}),
        popen=popen,
    )
    assert popen.calls[0]["argv"][-3:] == ["--", "/usr/bin/claude", text]

    # No prompt: the plain argv, byte for byte, on the two platforms that changed shape.
    popen = _Popen()
    launch_repo(
        root,
        platform="wsl",
        which=_which({"claude": "/usr/bin/claude", "wt.exe": "/mnt/c/wt.exe"}),
        popen=popen,
    )
    assert popen.calls[0]["argv"] == [
        "wt.exe",
        "wsl.exe",
        "--cd",
        str(root.resolve()),
        "--exec",
        "/usr/bin/claude",
    ]
    popen = _Popen()
    report = launch_repo(
        root,
        platform="windows",
        which=_which({"claude": "C:/claude.exe", "wt.exe": "C:/wt.exe"}),
        popen=popen,
    )
    assert report["prompted"] is False
    assert popen.calls[0]["argv"] == ["wt.exe", "-d", str(root.resolve()), "C:/claude.exe"]
