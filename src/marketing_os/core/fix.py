"""``mos fix`` — one front door for every fix the check can make on its own.

The dashboard is a client of the CLI, so the map from a finding code to the command
that puts it right lives here, once. A code with no entry is a judgement call, and the
operator gets the prompt for their assistant instead.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from marketing_os.core.catalog import build_repo as build_catalog
from marketing_os.core.related import related_repo
from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import read_config, repo_mode
from marketing_os.core.setup import setup_repo
from marketing_os.core.skills import sync_result

Fixer = Callable[[Path, bool], dict[str, Any]]


def _scaffold(root: Path, apply: bool) -> dict[str, Any]:
    """Put back whatever the scaffold shipped and the brain no longer has.

    The scaffold only ever creates what is missing, so this is safe on a brain that is
    otherwise full of the operator's work. The name and mode come from the brain's own
    settings; without a name there is nothing to render the templates with.
    """
    config = read_config(root) or {}
    name = str(config.get("business_name") or "").strip()
    if not name:
        return envelope(
            "setup",
            root,
            ok=False,
            findings=[
                finding(
                    "needs-name",
                    "Setting the brain up again needs its business name; "
                    "run onboard or use the app's set-up.",
                )
            ],
            action=next_action("onboard", "Run onboard with the business name."),
            planned=not apply,
        )
    mode, _ = repo_mode(config)
    return setup_repo(root, name, "all", mode=mode, agency=config.get("agency"), apply=apply)


def _catalogue(root: Path, apply: bool) -> dict[str, Any]:
    # The catalogue build has no plan of its own: it writes machine-local state and
    # touches no document, so the preview is the one line that says so.
    if apply:
        return build_catalog(root)
    return envelope("index-build", root, ok=True, changes=["rebuild the catalogue"], planned=True)


def _related(root: Path, apply: bool) -> dict[str, Any]:
    return related_repo(root, apply=apply, limit=None)


def _skills(root: Path, apply: bool) -> dict[str, Any]:
    return sync_result(root, "all", apply=apply, global_install=False)


#: Finding code -> the fixer that puts it right. Table order is the order ``--all`` runs.
FIXERS: dict[str, Fixer] = {
    "missing-file": _scaffold,
    "missing-directory": _scaffold,
    "missing-client-registry": _scaffold,
    "no-catalog": _catalogue,
    "stale-catalog": _catalogue,
    "unlinked-document": _related,
    "runtime-not-ready": _skills,
}

#: The codes the dashboard may offer "Preview the fix" for.
FIXABLE: frozenset[str] = frozenset(FIXERS)


def fix_repo(
    root: Path, code: str | None, *, apply: bool, all_codes: bool = False
) -> dict[str, Any]:
    """``mos fix`` — run the deterministic fix for one finding code, or every one."""
    root = root.expanduser().resolve()
    if all_codes:
        return _fix_all(root, apply)
    fixer = FIXERS.get(code or "")
    if fixer is None:
        return envelope(
            "fix",
            root,
            ok=False,
            findings=[
                finding(
                    "no-deterministic-fix",
                    f"There is no automatic fix for {code}; "
                    "ask your assistant with the prompt instead.",
                )
            ],
            action=next_action("copy-prompt", "Copy the prompt and give it to your assistant."),
            code=code,
            ran=[],
            planned=not apply,
        )
    inner = fixer(root, apply)
    return envelope(
        "fix",
        root,
        ok=inner["ok"],
        changes=inner["changes"],
        findings=inner["findings"],
        action=inner["next_action"],
        code=code,
        ran=[inner["command"]],
        applied=apply and inner["ok"],
        planned=not apply,
    )


def _fix_all(root: Path, apply: bool) -> dict[str, Any]:
    changes: list[str] = []
    findings: list[dict[str, str]] = []
    ran: list[str] = []
    ok = True
    done: list[Fixer] = []
    for code, fixer in FIXERS.items():
        if fixer in done:
            continue  # three codes share the scaffold; it runs once
        done.append(fixer)
        inner = fixer(root, apply)
        ok = ok and inner["ok"]
        changes.extend(f"{code}: {change}" for change in inner["changes"])
        findings.extend(inner["findings"])
        if inner["changes"]:
            ran.append(code)
    if ok:
        action = next_action("run-status", "Run status to confirm the brain is whole.")
    else:
        action = next_action("review-findings", "Review the findings before applying.")
    return envelope(
        "fix",
        root,
        ok=ok,
        changes=changes,
        findings=findings,
        action=action,
        code="all",
        ran=ran,
        applied=apply and ok,
        planned=not apply,
    )
