from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from marketing_os.core.atomic import atomic_write
from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import read_config, template_root
from marketing_os.core.setup import _render, setup_repo

_INTERVIEW_GUIDANCE = (
    "Interview the user about their brand, audience, offer, and strategy, then rewrite "
    "each unfilled business file with real, specific content grounded in their answers."
)


def _registry_repo_path(hq: Path, client_repo: Path) -> str:
    """Record the client repo relative to the HQ root as a forward-slash path.

    Falls back to the absolute posix path when a relative path cannot be
    computed (e.g. a different Windows drive, where ``relpath`` raises
    ``ValueError``).
    """
    try:
        relative = os.path.relpath(client_repo, hq)
    except ValueError:
        return client_repo.as_posix()
    return Path(relative).as_posix()


def _registry_row(name: str, repo: str) -> str:
    return f"| {name.strip()} | `{repo}` | active | you |"


def _has_table(text: str) -> bool:
    return any(line.lstrip().startswith("|") for line in text.splitlines())


def _client_registered(text: str, name: str) -> bool:
    target = name.strip().casefold()
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells and cells[0].casefold() == target:
            return True
    return False


def _insert_registry_row(text: str, row: str, newline: str = "\n") -> str:
    lines = text.splitlines()
    trailing = newline if text.endswith(("\n", "\r")) else ""
    for index, line in enumerate(lines):
        if "_example-client_" in line:
            lines.insert(index + 1, row)
            return newline.join(lines) + trailing
    last_table = None
    for index, line in enumerate(lines):
        if line.lstrip().startswith("|"):
            last_table = index
    if last_table is None:
        lines.append(row)
    else:
        lines.insert(last_table + 1, row)
    return newline.join(lines) + trailing


def _append_to_registry(
    hq: Path, name: str, client_repo: Path, *, apply: bool
) -> tuple[list[str], list[dict[str, str]]]:
    changes: list[str] = []
    findings: list[dict[str, str]] = []
    registry = hq / "business" / "clients" / "clients.md"
    if read_config(hq) is None or not registry.is_file():
        findings.append(
            finding(
                "no-client-registry",
                "No client registry at the --hq path; is this an agency HQ repo?",
                severity="warning",
                path=str(registry),
            )
        )
        return changes, findings
    # Read without newline translation so CRLF files survive the round trip.
    # (Path.read_text only accepts newline= on 3.13+; open() works on 3.10.)
    with registry.open(encoding="utf-8", newline="") as handle:
        text = handle.read()
    if not _has_table(text):
        findings.append(
            finding(
                "registry-malformed",
                "The client registry has no markdown table; skipped the append.",
                severity="warning",
                path=str(registry),
            )
        )
        return changes, findings
    if _client_registered(text, name):
        findings.append(
            finding(
                "client-already-registered",
                f"A registry row for {name.strip()!r} already exists; skipped the append.",
                severity="warning",
                path=str(registry),
            )
        )
        return changes, findings
    changes.append(f"register client {name.strip()} in {registry}")
    if apply:
        newline = "\r\n" if "\r\n" in text else "\n"
        row = _registry_row(name, _registry_repo_path(hq, client_repo))
        # The registry is a hand-maintained document being rewritten whole to insert one
        # row, so a truncating write that fails costs every row already in it.
        atomic_write(registry, _insert_registry_row(text, row, newline))
    return changes, findings


def _git_available() -> bool:
    return shutil.which("git") is not None


def _run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def _git_commands(name: str) -> list[str]:
    return ["git init", "git add -A", f'git commit -m "mos: onboard {name.strip()}"']


def _apply_git(root: Path, name: str) -> tuple[list[str], list[dict[str, str]]]:
    changes: list[str] = []
    findings: list[dict[str, str]] = []
    steps: list[list[str]] = [
        ["init"],
        ["add", "-A"],
        [
            "-c",
            "user.name=marketing-os",
            "-c",
            "user.email=onboard@marketing-os.local",
            "commit",
            "-m",
            f"mos: onboard {name.strip()}",
        ],
    ]
    labels = _git_commands(name)
    for label, args in zip(labels, steps, strict=True):
        try:
            result = _run_git(root, args)
        except FileNotFoundError:
            findings.append(
                finding(
                    "git-unavailable",
                    "git is not available on PATH; skipped repository initialization.",
                    severity="warning",
                )
            )
            return changes, findings
        except subprocess.TimeoutExpired:
            findings.append(
                finding(
                    "git-failed",
                    f"'{label}' timed out after 60s during repository initialization.",
                )
            )
            return changes, findings
        if result.returncode != 0:
            findings.append(
                finding(
                    "git-init-failed",
                    f"'{label}' failed: {result.stderr.strip() or 'unknown error'}",
                    severity="warning",
                )
            )
            return changes, findings
        changes.append(label)
    return changes, findings


def _interview_unfilled(root: Path, name: str) -> list[str]:
    template = template_root()
    business = template / "business"
    unfilled: list[str] = []
    for source in sorted(business.rglob("*.md")):
        relative = source.relative_to(template)
        rendered = _render(source.read_text(encoding="utf-8"), name)
        destination = root / relative
        if not destination.is_file() or destination.read_text(encoding="utf-8") == rendered:
            unfilled.append(relative.as_posix())
    return unfilled


def onboard_repo(
    root: Path,
    name: str,
    runtime: str,
    *,
    mode: str | None = None,
    agency: str | None = None,
    hq: Path | None = None,
    apply: bool,
) -> dict[str, Any]:
    root = root.expanduser().resolve()
    scaffold = setup_repo(root, name, runtime, mode=mode, agency=agency, apply=apply)
    changes = list(scaffold["changes"])
    findings = list(scaffold["findings"])

    if not scaffold["ok"]:
        return envelope(
            "onboard",
            root,
            ok=False,
            changes=changes,
            findings=findings,
            action=scaffold["next_action"],
            applied=False,
            planned=not apply,
        )

    if hq is not None:
        if mode == "client":
            registry_changes, registry_findings = _append_to_registry(
                hq.expanduser().resolve(), name, root, apply=apply
            )
            changes.extend(registry_changes)
            findings.extend(registry_findings)
        else:
            findings.append(
                finding(
                    "hq-ignored",
                    "--hq is only used when onboarding a client; ignored otherwise.",
                    severity="warning",
                )
            )

    git_present = (root / ".git").is_dir()
    if not git_present:
        if not _git_available():
            findings.append(
                finding(
                    "git-unavailable",
                    "git is not available on PATH; skipped repository initialization.",
                    severity="warning",
                )
            )
        elif apply:
            git_changes, git_findings = _apply_git(root, name)
            changes.extend(git_changes)
            findings.extend(git_findings)
        else:
            changes.extend(_git_commands(name))

    unfilled = _interview_unfilled(root, name)
    interview = {"unfilled": unfilled, "guidance": _INTERVIEW_GUIDANCE}

    if unfilled:
        action = next_action(
            "run-interview",
            "Interview the user and rewrite the unfilled business files with real content.",
        )
    else:
        action = next_action(
            "run-start",
            "The business brain is scaffolded and filled; run the start routine.",
        )

    ok = not any(item["severity"] == "error" for item in findings)
    return envelope(
        "onboard",
        root,
        ok=ok,
        changes=changes,
        findings=findings,
        action=action,
        applied=apply and ok,
        planned=not apply,
        interview=interview,
        mode=scaffold.get("mode"),
        suggested_repo_name=scaffold.get("suggested_repo_name"),
    )
