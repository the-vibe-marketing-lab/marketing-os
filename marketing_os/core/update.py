from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import marketing_os
from marketing_os.core.results import envelope, finding, next_action

_PROJECT_NAME = 'name = "marketing-os"'


def _install_path() -> Path:
    return Path(marketing_os.__file__).resolve()


def _detect_mode(path: Path) -> tuple[str, Path | None]:
    for ancestor in path.parents:
        pyproject = ancestor / "pyproject.toml"
        if pyproject.is_file():
            try:
                text = pyproject.read_text(encoding="utf-8")
            except OSError:
                text = ""
            if _PROJECT_NAME in text and (ancestor / ".git").is_dir():
                return "source", ancestor
    if "/uv/tools/" in path.as_posix().lower():
        return "uv", None
    if "pipx" in str(path).lower():
        return "pipx", None
    return "unknown", None


def _run(
    argv: list[str], cwd: Path | None = None, *, timeout: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=None if cwd is None else str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def _git_read(root: Path, args: list[str]) -> str | None:
    try:
        result = _run(["git", "-C", str(root), *args], timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _update_source(root: Path, *, apply: bool) -> dict[str, Any]:
    command = f"git -C {root} pull --ff-only"
    argv = ["git", "-C", str(root), "pull", "--ff-only"]
    findings: list[dict[str, str]] = []

    branch = _git_read(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    if branch != "main":
        findings.append(
            finding(
                "not-on-main",
                f"The checkout is on '{branch or 'unknown'}', not main; switch before updating.",
            )
        )
    status = _git_read(root, ["status", "--porcelain"])
    if status is None or status != "":
        findings.append(
            finding(
                "dirty-worktree",
                "The checkout has uncommitted changes; commit or stash them before updating.",
            )
        )

    if findings:
        # A guard trip means nothing will run: changes must be empty.
        return envelope(
            "update",
            root,
            ok=False,
            changes=[],
            findings=findings,
            action=next_action("resolve-guards", "Resolve the guards, then retry the update."),
            mode="source",
            run_command=command,
            applied=False,
            planned=not apply,
        )

    if not apply:
        return envelope(
            "update",
            root,
            ok=True,
            changes=[f"run: {command}"],
            action=next_action("apply-update", "Re-run with --yes to fast-forward the checkout."),
            mode="source",
            run_command=command,
            applied=False,
            planned=True,
        )

    try:
        result = _run(argv, timeout=120)
    except FileNotFoundError:
        return envelope(
            "update",
            root,
            ok=False,
            changes=[f"run: {command}"],
            findings=[finding("git-unavailable", "git is not available on PATH.")],
            action=next_action("manual-update", "Install git or update the checkout manually."),
            mode="source",
            run_command=command,
            applied=False,
        )
    except subprocess.TimeoutExpired:
        return envelope(
            "update",
            root,
            ok=False,
            changes=[f"run: {command}"],
            findings=[finding("update-failed", f"'{command}' timed out after 120s.")],
            action=next_action("resolve-update-failure", "Inspect the update output and retry."),
            mode="source",
            run_command=command,
            applied=False,
        )
    return _result_envelope(root, result, run_command=command, mode="source")


def _update_installer(mode: str, argv: list[str], *, apply: bool) -> dict[str, Any]:
    """Upgrade through the tool installer named by ``mode``: pipx, or uv's tool command."""
    repo = Path.cwd()
    command = " ".join(argv)
    tool = argv[0]

    if not apply:
        return envelope(
            "update",
            repo,
            ok=True,
            changes=[f"run: {command}"],
            action=next_action("apply-update", f"Re-run with --yes to upgrade via {tool}."),
            mode=mode,
            run_command=command,
            applied=False,
            planned=True,
        )

    try:
        result = _run(argv, timeout=120)
    except FileNotFoundError:
        return envelope(
            "update",
            repo,
            ok=False,
            changes=[f"run: {command}"],
            findings=[finding("installer-unavailable", f"{tool} is not available on PATH.")],
            action=next_action(
                "manual-update", f"Install {tool} or upgrade marketing-os manually."
            ),
            mode=mode,
            run_command=command,
            applied=False,
        )
    except subprocess.TimeoutExpired:
        return envelope(
            "update",
            repo,
            ok=False,
            changes=[f"run: {command}"],
            findings=[finding("update-failed", f"'{command}' timed out after 120s.")],
            action=next_action("resolve-update-failure", "Inspect the update output and retry."),
            mode=mode,
            run_command=command,
            applied=False,
        )
    return _result_envelope(repo, result, run_command=command, mode=mode)


def _update_unknown(*, apply: bool) -> dict[str, Any]:
    repo = Path.cwd()
    return envelope(
        "update",
        repo,
        ok=True,
        findings=[
            finding(
                "unknown-install",
                "The install method could not be determined; update through your installer.",
                severity="warning",
            )
        ],
        action=next_action(
            "manual-update",
            "Upgrade marketing-os with the installer you used "
            "(pip, pipx, uv, or a source checkout).",
        ),
        mode="unknown",
        run_command="",
        applied=False,
        planned=not apply,
    )


def _result_envelope(
    repo: Path, result: subprocess.CompletedProcess[str], *, run_command: str, mode: str
) -> dict[str, Any]:
    ok = result.returncode == 0
    findings: list[dict[str, str]] = []
    if ok:
        action = next_action("run-doctor", "Verify the updated engine, then continue.")
    else:
        findings.append(
            finding(
                "update-failed",
                f"'{run_command}' exited with code {result.returncode}: "
                f"{result.stderr.strip() or 'no output'}",
            )
        )
        action = next_action("resolve-update-failure", "Inspect the update output and retry.")
    return envelope(
        "update",
        repo,
        ok=ok,
        changes=[f"run: {run_command}"],
        findings=findings,
        action=action,
        mode=mode,
        run_command=run_command,
        applied=True,
    )


def update_engine(*, apply: bool) -> dict[str, Any]:
    path = _install_path()
    mode, root = _detect_mode(path)
    if mode == "source" and root is not None:
        return _update_source(root, apply=apply)
    if mode == "pipx":
        return _update_installer("pipx", ["pipx", "upgrade", "marketing-os"], apply=apply)
    if mode == "uv":
        return _update_installer("uv", ["uv", "tool", "upgrade", "marketing-os"], apply=apply)
    return _update_unknown(apply=apply)
