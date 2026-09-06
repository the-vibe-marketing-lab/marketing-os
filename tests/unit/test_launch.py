from __future__ import annotations

from pathlib import Path

from marketing_os.core.launch import launch_repo
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
