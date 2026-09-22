"""Operator-facing places where a marketing brain can live.

The local app uses these filesystem facts before a brain exists. Discovery therefore
stays best-effort: an unavailable platform helper or an unreadable directory removes a
candidate, but never breaks the request that asked for app state.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from marketing_os.core.attach import legacy_summary
from marketing_os.core.schema import read_config

_PROCESS_TIMEOUT = 3
_MAX_DIRECTORIES_PER_PLACE = 500
_WSL_USERS_ROOT = Path("/mnt/c/Users")
_WINDOWS_SHARED_PROFILES = frozenset(
    name.casefold() for name in ("Public", "Default", "Default User", "All Users")
)
#: A drive-letter path as Windows spells it: ``C:\Users\...`` or ``C:/Users/...``.
_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")

Run = Callable[..., subprocess.CompletedProcess[str]]


def home_dir() -> Path:
    """Return the operator's home directory."""
    return Path.home()


def _is_wsl(env: Mapping[str, str], proc_version: str | None) -> bool:
    distro = env.get("WSL_DISTRO_NAME", "")
    if isinstance(distro, str) and distro.strip():
        return True
    if proc_version is None:
        try:
            proc_version = Path("/proc/version").read_text(encoding="utf-8", errors="replace")
        except OSError:
            # A missing or unreadable proc file means this marker gives no evidence.
            proc_version = ""
    return "microsoft" in proc_version.casefold()


def _stdout_line(result: Any) -> str | None:
    if getattr(result, "returncode", None) != 0:
        return None
    stdout = getattr(result, "stdout", None)
    if not isinstance(stdout, str):
        return None
    lines = stdout.strip().splitlines()
    if len(lines) != 1:
        return None
    value = lines[0].strip()
    return value or None


def _windows_profile_from_wsl(run: Run) -> Path | None:
    try:
        profile_result = run(
            ["cmd.exe", "/c", "echo", "%USERPROFILE%"],
            capture_output=True,
            check=False,
            text=True,
            timeout=_PROCESS_TIMEOUT,
        )
        windows_profile = _stdout_line(profile_result)
        if windows_profile is None or windows_profile.casefold() == "%userprofile%":
            return None
        converted_result = run(
            ["wslpath", "-u", windows_profile],
            capture_output=True,
            check=False,
            text=True,
            timeout=_PROCESS_TIMEOUT,
        )
        converted = _stdout_line(converted_result)
        if converted is None:
            return None
        profile = Path(converted)
        return profile if profile.is_absolute() else None
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        # Platform helpers are optional evidence; the deterministic directory scan follows.
        return None


def _login_name(env: Mapping[str, str]) -> str | None:
    """The name the operator logs in with, from the environment or the session."""
    value = env.get("USER") or env.get("USERNAME") or ""
    if isinstance(value, str) and value.strip():
        return value.strip()
    try:
        return os.getlogin() or None
    except OSError:
        return None


def _wsl_desktop_from_profiles(users_root: Path, login: str | None = None) -> Path | None:
    """The Windows Desktop of the profile that is the operator's, from the profile list.

    A profile whose name matches the login name wins. With no match the answer is only
    safe when exactly one profile has a Desktop: several profiles and no match means a
    guess, and a guess here puts the wizard's default folder on someone else's Desktop.
    """
    try:
        profiles = sorted(users_root.iterdir(), key=lambda path: path.name.casefold())
    except OSError:
        return None
    desktops: list[Path] = []
    for profile in profiles:
        if profile.name.casefold() in _WINDOWS_SHARED_PROFILES:
            continue
        try:
            if not profile.is_dir():
                continue
            desktop = profile / "Desktop"
            if not desktop.is_dir():
                continue
        except OSError:
            # A profile can vanish or become unreadable while the scan is in progress.
            continue
        if login and profile.name.casefold() == login.casefold():
            return desktop
        desktops.append(desktop)
    return desktops[0] if len(desktops) == 1 else None


def desktop_dir(
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    proc_version: str | None = None,
    run: Run = subprocess.run,
    platform_name: str | None = None,
    wsl_users_root: Path = _WSL_USERS_ROOT,
) -> Path | None:
    """Return the first existing Desktop for this platform, or None.

    All platform facts are injectable so tests can exercise Windows, WSL and POSIX
    discovery without changing the machine that runs them. This function never raises.
    """
    try:
        environment = os.environ if env is None else env
        operator_home = home_dir() if home is None else home
        current_platform = os.name if platform_name is None else platform_name
        if _is_wsl(environment, proc_version):
            profile = _windows_profile_from_wsl(run)
            if profile is not None:
                desktop = profile / "Desktop"
                if desktop.is_dir():
                    return desktop
            return _wsl_desktop_from_profiles(wsl_users_root, _login_name(environment))
        if current_platform == "nt":
            profile_value = environment.get("USERPROFILE", "")
            if not isinstance(profile_value, str) or not profile_value.strip():
                return None
            desktop = Path(profile_value.strip()) / "Desktop"
            return desktop if desktop.is_dir() else None
        desktop = operator_home / "Desktop"
        return desktop if desktop.is_dir() else None
    except Exception:
        # App state must still load when an injected seam or filesystem probe misbehaves.
        return None


def is_windows_path(value: str) -> bool:
    """Whether ``value`` is spelled the way Windows spells a full path."""
    return bool(_WINDOWS_PATH.match(value.strip()))


def windows_to_wsl(
    value: str,
    *,
    env: Mapping[str, str] | None = None,
    proc_version: str | None = None,
    run: Run = subprocess.run,
) -> str | None:
    """A Windows-spelled path as this side of WSL sees it.

    Anything that is not a Windows spelling, or any machine that is not WSL, gets the
    value back unchanged so the caller's own absolute-path check decides. Under WSL the
    path goes through ``wslpath -u``; when that cannot answer the result is None, because
    a half-converted path would be a relative one, and a relative path lands in the cwd.
    """
    text = value.strip()
    if not is_windows_path(text):
        return value
    if not _is_wsl(os.environ if env is None else env, proc_version):
        return value
    try:
        converted = _stdout_line(
            run(
                ["wslpath", "-u", text],
                capture_output=True,
                check=False,
                text=True,
                timeout=_PROCESS_TIMEOUT,
            )
        )
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return None
    # ``wslpath -u`` answers with a path on the Linux side, so it is judged as one whatever
    # the host: a ``WindowsPath`` would call ``/mnt/c/...`` relative for want of a drive.
    if converted is None or not PurePosixPath(converted).is_absolute():
        return None
    return converted


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve(strict=False))
    except OSError:
        # The unresolved spelling still provides stable best-effort deduplication.
        return str(path.absolute())


def suggested_places(
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    proc_version: str | None = None,
    run: Run = subprocess.run,
    platform_name: str | None = None,
    wsl_users_root: Path = _WSL_USERS_ROOT,
) -> list[dict[str, str]]:
    """Return the Desktop first and the operator's home last."""
    operator_home = home_dir() if home is None else home
    desktop = desktop_dir(
        env=env,
        home=operator_home,
        proc_version=proc_version,
        run=run,
        platform_name=platform_name,
        wsl_users_root=wsl_users_root,
    )
    places: list[dict[str, str]] = []
    if desktop is not None and _path_key(desktop) != _path_key(operator_home):
        places.append({"path": str(desktop), "kind": "desktop"})
    places.append({"path": str(operator_home), "kind": "home"})
    return places


def _child_directories(parent: Path) -> list[Path]:
    children: list[Path] = []
    try:
        with os.scandir(parent) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                try:
                    # scandir reuses the stat from the directory read, so this stays one
                    # syscall per entry even on a Desktop holding hundreds of folders.
                    if entry.is_dir():
                        children.append(Path(entry.path))
                except OSError:
                    # An entry may vanish between enumeration and inspection.
                    continue
    except OSError:
        return []
    children.sort(key=lambda path: path.name.casefold())
    return children


def _brain_config(candidate: Path) -> dict[str, Any] | None:
    try:
        config = read_config(candidate)
    except Exception:
        # A bad or concurrently removed config is not evidence of a usable brain.
        return None
    if not isinstance(config, dict):
        return None
    # business_name identifies the brain, so its absence means there is nothing to show.
    # mode is optional in config_text, so a mode-less brain is still a real brain.
    if not isinstance(config.get("business_name"), str):
        return None
    return config


def legacy_brain(candidate: Path) -> dict[str, Any] | None:
    """Name and mode of a legacy (pre-engine) brain at ``candidate``, or None.

    A legacy brain is surfaced, never hidden: the app shows it as attachable so the
    operator can adopt it with ``mos attach`` instead of scaffolding beside it.
    """
    try:
        return legacy_summary(candidate)
    except Exception:
        return None


def _place_path(place: object) -> Path | None:
    if not isinstance(place, Mapping):
        return None
    value = place.get("path")
    if not isinstance(value, str) or not value:
        return None
    return Path(value)


def _scan_place(root: Path, max_depth: int) -> list[dict[str, Any]]:
    try:
        if not root.is_dir():
            return []
    except OSError:
        return []
    found: list[dict[str, Any]] = []
    pending = deque([(root, 0)])
    queued = {_path_key(root)}
    scanned = 0
    while pending and scanned < _MAX_DIRECTORIES_PER_PLACE:
        candidate, depth = pending.popleft()
        scanned += 1
        summary = _brain_summary(candidate)
        if summary is not None:
            found.append({"path": str(candidate), **summary})
        if depth >= max_depth:
            continue
        for child in _child_directories(candidate):
            key = _path_key(child)
            if key in queued:
                continue
            queued.add(key)
            pending.append((child, depth + 1))
    return found


def existing_brains(
    places: Iterable[Mapping[str, object]], *, max_depth: int = 1
) -> list[dict[str, Any]]:
    """Return brains at or below each place, tolerating every discovery failure.

    Each entry carries ``legacy``: False for a canonical brain, True for one that needs
    ``mos attach`` before the rest of the engine will recognise it.
    """
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0:
        return []
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for place in places:
            root = _place_path(place)
            if root is None:
                continue
            for brain in _scan_place(root, max_depth):
                key = _path_key(Path(str(brain["path"])))
                if key in seen:
                    continue
                seen.add(key)
                found.append(brain)
    except Exception:
        # Partial results are correct when an input iterable or filesystem seam fails.
        return found
    return found


# --- the in-page folder browser ---------------------------------------------------

_MAX_CHILDREN = 200
# Kernel views, not places for files. Listing them is slow and never what anyone meant.
_NEVER_DESCEND = ("/proc", "/sys", "/dev")


def _brain_summary(candidate: Path) -> dict[str, Any] | None:
    """Name, mode and a ``legacy`` flag for a canonical or legacy brain; None otherwise."""
    config = _brain_config(candidate)
    if config is not None:
        mode = config.get("mode")
        return {
            "name": config["business_name"],
            "mode": mode if isinstance(mode, str) else None,
            "legacy": False,
        }
    legacy = legacy_brain(candidate)
    if legacy is None:
        return None
    return {"name": legacy["name"], "mode": legacy["mode"], "legacy": True}


def _is_canonical(brain: dict[str, Any] | None) -> bool:
    return brain is not None and not brain.get("legacy")


def _is_attachable(brain: dict[str, Any] | None) -> bool:
    return brain is not None and bool(brain.get("legacy"))


def _is_forbidden(path: Path) -> bool:
    key = _path_key(path)
    return any(key == root or key.startswith(root + "/") for root in _NEVER_DESCEND)


def _nearest_existing(path: Path) -> Path | None:
    for ancestor in (path, *path.parents):
        try:
            if ancestor.is_dir():
                return ancestor
        except OSError:
            # An unreadable ancestor is not a place to land; keep climbing.
            continue
    return None


def _folder(
    path: Path,
    *,
    parent: Path | None,
    brain: dict[str, Any] | None = None,
    children: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "path": str(path),
        "parent": str(parent) if parent is not None else None,
        "is_brain": _is_canonical(brain),
        "attachable": _is_attachable(brain),
        "brain": brain,
        "children": children or [],
        "error": error,
    }


def _browse_start(value: object, places: Iterable[Mapping[str, object]] | None) -> Path:
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        candidates = list(suggested_places() if places is None else places)
        start = _place_path(candidates[0]) if candidates else None
        text = str(start or home_dir())
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = home_dir() / path
    return Path(os.path.normpath(str(path)))


def _describe_folder(
    value: object, places: Iterable[Mapping[str, object]] | None
) -> dict[str, Any]:
    path = _browse_start(value, places)
    parent = path.parent if path.parent != path else None
    if _is_forbidden(path):
        return _folder(path, parent=parent, error="That folder belongs to the operating system.")
    if not path.is_dir():
        nearest = _nearest_existing(path.parent) if parent is not None else None
        return _folder(path, parent=nearest, error="That folder does not exist.")
    children: list[dict[str, Any]] = []
    for child in _child_directories(path):
        if len(children) >= _MAX_CHILDREN:
            break
        if _is_forbidden(child):
            continue
        child_brain = _brain_summary(child)
        children.append(
            {
                "name": child.name,
                "path": str(child),
                "is_brain": _is_canonical(child_brain),
                "attachable": _is_attachable(child_brain),
                "brain": child_brain,
            }
        )
    return _folder(path, parent=parent, brain=_brain_summary(path), children=children)


def describe_folder(
    value: object, *, places: Iterable[Mapping[str, object]] | None = None
) -> dict[str, Any]:
    """Describe one directory for the folder browser: its brain, its parent, its subfolders.

    An empty value starts at the first suggested place. Hidden and unreadable entries are
    skipped, children are capped, and no exception ever leaves this function.
    """
    try:
        return _describe_folder(value, places)
    except Exception:
        fallback = Path(value) if isinstance(value, str) and value else home_dir()
        return _folder(fallback, parent=None, error="That folder could not be read.")
