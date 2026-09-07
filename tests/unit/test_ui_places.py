from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from marketing_os.core.setup import setup_repo
from marketing_os.ui import places
from marketing_os.ui.places import (
    desktop_dir,
    existing_brains,
    home_dir,
    suggested_places,
    windows_to_wsl,
)


def _completed(args: list[str], stdout: str, *, returncode: int = 0):
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")


def test_home_dir_is_path_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(places.Path, "home", lambda: tmp_path)
    assert home_dir() == tmp_path


def test_wsl_desktop_uses_cmd_profile_and_wslpath(tmp_path: Path) -> None:
    profile = tmp_path / "mnt" / "c" / "Users" / "Operator"
    desktop = profile / "Desktop"
    desktop.mkdir(parents=True)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(args: list[str], **kwargs):
        calls.append((args, kwargs))
        if args[0] == "cmd.exe":
            return _completed(args, "C:\\Users\\Operator\r\n")
        return _completed(args, f"{profile}\n")

    result = desktop_dir(
        env={},
        home=tmp_path / "linux-home",
        proc_version="Linux microsoft-standard-WSL2",
        run=run,
        platform_name="posix",
        wsl_users_root=tmp_path / "unused",
    )

    assert result == desktop
    assert [args for args, _ in calls] == [
        ["cmd.exe", "/c", "echo", "%USERPROFILE%"],
        ["wslpath", "-u", "C:\\Users\\Operator"],
    ]
    assert all(kwargs["timeout"] == 3 for _, kwargs in calls)
    assert all(kwargs["capture_output"] is True for _, kwargs in calls)
    assert all(kwargs["check"] is False for _, kwargs in calls)
    assert all(kwargs["text"] is True for _, kwargs in calls)


def test_wsl_environment_marker_uses_windows_desktop(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    desktop = profile / "Desktop"
    desktop.mkdir(parents=True)

    def run(args: list[str], **kwargs):
        if args[0] == "cmd.exe":
            return _completed(args, "C:\\Users\\Operator\n")
        return _completed(args, f"{profile}\n")

    assert (
        desktop_dir(
            env={"WSL_DISTRO_NAME": "Ubuntu"},
            home=tmp_path / "home",
            proc_version="ordinary Linux",
            run=run,
            platform_name="posix",
            wsl_users_root=tmp_path / "unused",
        )
        == desktop
    )


@pytest.mark.parametrize(
    "failure",
    ["missing", "nonzero", "timeout", "empty", "literal", "multiline"],
)
def test_wsl_process_failures_fall_back_to_profile_scan(tmp_path: Path, failure: str) -> None:
    users = tmp_path / "mnt" / "c" / "Users"
    public = users / "Public" / "Desktop"
    expected = users / "Operator" / "Desktop"
    public.mkdir(parents=True)
    expected.mkdir(parents=True)

    def run(args: list[str], **kwargs):
        if failure == "missing":
            raise FileNotFoundError(args[0])
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        if failure == "nonzero":
            return _completed(args, "", returncode=1)
        if failure == "empty":
            return _completed(args, "")
        if failure == "literal":
            return _completed(args, "%USERPROFILE%\n")
        return _completed(args, "first\nsecond\n")

    result = desktop_dir(
        env={},
        home=tmp_path / "home",
        proc_version="Microsoft WSL",
        run=run,
        platform_name="posix",
        wsl_users_root=users,
    )

    assert result == expected
    assert result != public


def _unavailable(*args, **kwargs):
    raise OSError("cmd.exe unavailable")


def _wsl_desktop(users: Path, home: Path, env: dict[str, str]) -> Path | None:
    return desktop_dir(
        env=env,
        home=home,
        proc_version="microsoft",
        run=_unavailable,
        platform_name="posix",
        wsl_users_root=users,
    )


def test_wsl_fallback_prefers_the_profile_named_after_the_login(tmp_path: Path) -> None:
    users = tmp_path / "Users"
    for profile in ("Public", "Default", "Default User", "All Users", "Zulu", "Alpha"):
        (users / profile / "Desktop").mkdir(parents=True)
    assert _wsl_desktop(users, tmp_path / "home", {"USER": "zulu"}) == users / "Zulu" / "Desktop"


def test_wsl_fallback_never_guesses_between_several_profiles(tmp_path: Path) -> None:
    """Two profiles and no match is a guess, and a wrong guess puts the wizard's default
    folder on someone else's Desktop. The home folder stands in instead."""
    users = tmp_path / "Users"
    for profile in ("Public", "Zulu", "Alpha"):
        (users / profile / "Desktop").mkdir(parents=True)
    assert _wsl_desktop(users, tmp_path / "home", {"USER": "nobody-here"}) is None
    assert suggested_places(
        env={"USER": "nobody-here"},
        home=tmp_path / "home",
        proc_version="microsoft",
        run=_unavailable,
        platform_name="posix",
        wsl_users_root=users,
    ) == [{"path": str(tmp_path / "home"), "kind": "home"}]


def test_wsl_fallback_takes_the_only_profile_and_skips_shared_ones(tmp_path: Path) -> None:
    users = tmp_path / "Users"
    for profile in ("Public", "Default", "Default User", "All Users", "Only"):
        (users / profile / "Desktop").mkdir(parents=True)
    only = _wsl_desktop(users, tmp_path / "home", {"USER": "someone-else"})
    assert only == users / "Only" / "Desktop"


# --- Windows spellings arriving from the page ---------------------------------------------


def _wslpath(args: list[str], **kwargs):
    assert args[:2] == ["wslpath", "-u"]
    return _completed(args, "/mnt/c/Users/you/Desktop/foo\n")


@pytest.mark.parametrize("value", ["C:/Users/you/Desktop/foo", "c:\\Users\\you\\Desktop\\foo"])
def test_windows_path_is_converted_under_wsl(value: str) -> None:
    converted = windows_to_wsl(value, env={"WSL_DISTRO_NAME": "Ubuntu"}, run=_wslpath)
    assert converted == "/mnt/c/Users/you/Desktop/foo"


@pytest.mark.parametrize("value", ["/home/you/brain", "~/brain", "relative/brain", "brain"])
def test_a_non_windows_spelling_comes_back_unchanged(value: str) -> None:
    def never(*args, **kwargs):
        raise AssertionError("wslpath must not run")

    assert windows_to_wsl(value, env={"WSL_DISTRO_NAME": "Ubuntu"}, run=never) == value


def test_a_windows_spelling_off_wsl_comes_back_unchanged() -> None:
    def never(*args, **kwargs):
        raise AssertionError("wslpath must not run")

    value = "C:/Users/you/Desktop/foo"
    assert windows_to_wsl(value, env={}, proc_version="Linux", run=never) == value


@pytest.mark.parametrize("failure", ["missing", "nonzero", "empty", "relative", "timeout"])
def test_a_conversion_that_cannot_answer_is_none_never_a_relative_path(failure: str) -> None:
    def run(args: list[str], **kwargs):
        if failure == "missing":
            raise FileNotFoundError(args[0])
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        if failure == "nonzero":
            return _completed(args, "", returncode=1)
        if failure == "empty":
            return _completed(args, "")
        return _completed(args, "Users/you/Desktop/foo\n")

    assert windows_to_wsl("C:/Users/you/Desktop/foo", env={"WSL_DISTRO_NAME": "U"}, run=run) is None


def test_posix_suggestions_put_desktop_before_home(tmp_path: Path) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()

    assert suggested_places(env={}, home=tmp_path, proc_version="Linux", platform_name="posix") == [
        {"path": str(desktop), "kind": "desktop"},
        {"path": str(tmp_path), "kind": "home"},
    ]


def test_posix_suggestions_use_home_alone_without_desktop(tmp_path: Path) -> None:
    assert suggested_places(env={}, home=tmp_path, proc_version="Linux", platform_name="posix") == [
        {"path": str(tmp_path), "kind": "home"}
    ]


def test_native_windows_uses_userprofile(tmp_path: Path) -> None:
    profile = tmp_path / "Windows Profile"
    desktop = profile / "Desktop"
    desktop.mkdir(parents=True)

    assert (
        desktop_dir(
            env={"USERPROFILE": str(profile)},
            home=tmp_path / "other-home",
            proc_version="not WSL",
            platform_name="nt",
        )
        == desktop
    )
    assert (
        desktop_dir(
            env={},
            home=tmp_path / "other-home",
            proc_version="not WSL",
            platform_name="nt",
        )
        is None
    )


def test_suggestions_deduplicate_a_desktop_resolving_to_home(tmp_path: Path) -> None:
    operator_home = tmp_path / "operator-home"
    operator_home.mkdir()
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "Desktop").symlink_to(operator_home, target_is_directory=True)

    assert suggested_places(
        env={"USERPROFILE": str(profile)},
        home=operator_home,
        proc_version="not WSL",
        platform_name="nt",
    ) == [{"path": str(operator_home), "kind": "home"}]


def test_existing_brains_finds_visible_child_and_ignores_hidden_child(tmp_path: Path) -> None:
    desktop = tmp_path / "Desktop"
    visible = desktop / "visible-brain"
    hidden = desktop / ".hidden-brain"
    setup_repo(visible, "Visible Business", "all", mode="agency", apply=True)
    setup_repo(hidden, "Hidden Business", "all", mode="in-house", apply=True)

    assert existing_brains([{"path": str(desktop), "kind": "desktop"}]) == [
        {"path": str(visible), "name": "Visible Business", "mode": "agency", "legacy": False}
    ]


def test_existing_brains_checks_place_itself_and_deduplicates_paths(tmp_path: Path) -> None:
    brain = tmp_path / "brain"
    setup_repo(brain, "Root Business", "all", mode="in-house", apply=True)
    places_list = [
        {"path": str(brain), "kind": "desktop"},
        {"path": str(brain), "kind": "home"},
    ]

    assert existing_brains(places_list) == [
        {"path": str(brain), "name": "Root Business", "mode": "in-house", "legacy": False}
    ]


def test_existing_brains_honours_max_depth(tmp_path: Path) -> None:
    place = tmp_path / "place"
    nested = place / "group" / "nested-brain"
    setup_repo(nested, "Nested Business", "all", mode="client", agency="Agency", apply=True)

    assert existing_brains([{"path": str(place)}]) == []
    assert existing_brains([{"path": str(place)}], max_depth=2) == [
        {"path": str(nested), "name": "Nested Business", "mode": "client", "legacy": False}
    ]
    assert existing_brains([{"path": str(place)}], max_depth=-1) == []


def test_existing_brains_stops_before_walking_a_pathological_tree(
    monkeypatch, tmp_path: Path
) -> None:
    """The cap is a guard against a place holding absurdly many folders, not a limit on a
    normal desktop. It was 50 once, which silently hid every brain late in the alphabet on
    a desktop used as a projects folder."""
    place = tmp_path / "place"
    place.mkdir()
    for index in range(places._MAX_DIRECTORIES_PER_PLACE + 25):
        (place / f"candidate-{index:04d}").mkdir()
    scanned: list[Path] = []

    def record(candidate: Path):
        scanned.append(candidate)
        return None

    monkeypatch.setattr(places, "read_config", record)
    assert existing_brains([{"path": str(place)}]) == []
    assert len(scanned) == places._MAX_DIRECTORIES_PER_PLACE
    assert places._MAX_DIRECTORIES_PER_PLACE > 128, "a desktop of folders must not truncate"


def test_existing_brains_returns_partial_results_when_discovery_fails(
    monkeypatch, tmp_path: Path
) -> None:
    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    brain = tmp_path / "brain"
    setup_repo(brain, "Readable Business", "all", mode="in-house", apply=True)
    original_iterdir = places.Path.iterdir

    def iterdir(path: Path):
        if path == unreadable:
            raise PermissionError(path)
        return original_iterdir(path)

    monkeypatch.setattr(places.Path, "iterdir", iterdir)
    result = existing_brains(
        [
            {"path": str(unreadable)},
            {"path": str(tmp_path / "vanished")},
            {"path": str(brain)},
            {"path": 42},
        ]
    )

    assert result == [
        {"path": str(brain), "name": "Readable Business", "mode": "in-house", "legacy": False}
    ]


def test_desktop_and_existing_brains_never_raise_for_bad_seams(tmp_path: Path) -> None:
    class BrokenEnvironment:
        def get(self, key: str, default: str = "") -> str:
            raise RuntimeError("environment unavailable")

    def broken_places():
        yield {"path": str(tmp_path)}
        raise RuntimeError("places vanished")

    assert desktop_dir(env=BrokenEnvironment(), home=tmp_path, proc_version="Linux") is None
    assert existing_brains(broken_places()) == []


def test_a_brain_without_a_mode_is_still_a_brain(tmp_path: Path) -> None:
    """`config_text` only writes `mode` when one was chosen, so requiring it hid real
    brains from the setup wizard entirely."""
    brain = tmp_path / "no-mode"
    (brain / ".mos").mkdir(parents=True)
    (brain / ".mos" / "config.yaml").write_text(
        json.dumps(
            {
                "schema": "mos.business-repo.v1",
                "schema_version": 1,
                "business_name": "Modeless Co.",
            }
        ),
        encoding="utf-8",
    )

    assert existing_brains([{"path": str(tmp_path), "kind": "desktop"}]) == [
        {"path": str(brain), "name": "Modeless Co.", "mode": None, "legacy": False}
    ]


def test_a_desktop_holding_many_folders_is_scanned_past_the_first_fifty(
    tmp_path: Path,
) -> None:
    """A desktop used as a projects folder easily passes fifty entries, and the brain that
    matters is as likely to be late in the alphabet as early."""
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    for index in range(80):
        (desktop / f"folder-{index:03d}").mkdir()
    brain = desktop / "zzz-last-of-all"
    (brain / ".mos").mkdir(parents=True)
    (brain / ".mos" / "config.yaml").write_text(
        json.dumps({"business_name": "Late Riser", "mode": "agency"}), encoding="utf-8"
    )

    found = existing_brains([{"path": str(desktop), "kind": "desktop"}])

    assert found == [{"path": str(brain), "name": "Late Riser", "mode": "agency", "legacy": False}]


# --- legacy brains are surfaced as attachable, never hidden -------------------------


def _legacy_brain(root: Path) -> Path:
    (root / ".mos").mkdir(parents=True)
    (root / ".mos" / "config.yaml").write_text("mode: agency\nname: Legacy Lab\n", encoding="utf-8")
    (root / "BRAIN.md").write_text("# Mine\n", encoding="utf-8")
    (root / "business").mkdir()
    return root


def test_existing_brains_flags_legacy_brains_as_attachable(tmp_path: Path) -> None:
    desktop = tmp_path / "Desktop"
    canonical = desktop / "canonical"
    setup_repo(canonical, "Canon Co", "all", mode="in-house", apply=True)
    legacy = _legacy_brain(desktop / "legacy")
    assert existing_brains([{"path": str(desktop), "kind": "desktop"}]) == [
        {"path": str(canonical), "name": "Canon Co", "mode": "in-house", "legacy": False},
        {"path": str(legacy), "name": "Legacy Lab", "mode": "agency", "legacy": True},
    ]


def test_describe_folder_marks_legacy_children_attachable(tmp_path: Path) -> None:
    from marketing_os.ui.places import describe_folder

    canonical = tmp_path / "canonical"
    setup_repo(canonical, "Canon Co", "all", mode="in-house", apply=True)
    _legacy_brain(tmp_path / "legacy")
    (tmp_path / "plain").mkdir()
    described = describe_folder(str(tmp_path))
    by_name = {child["name"]: child for child in described["children"]}
    assert by_name["canonical"]["is_brain"] is True
    assert by_name["canonical"]["attachable"] is False
    assert by_name["canonical"]["brain"]["legacy"] is False
    assert by_name["legacy"]["is_brain"] is False
    assert by_name["legacy"]["attachable"] is True
    assert by_name["legacy"]["brain"] == {"name": "Legacy Lab", "mode": "agency", "legacy": True}
    assert by_name["plain"]["is_brain"] is False
    assert by_name["plain"]["attachable"] is False
    assert by_name["plain"]["brain"] is None

    folder = describe_folder(str(tmp_path / "legacy"))
    assert folder["is_brain"] is False
    assert folder["attachable"] is True
