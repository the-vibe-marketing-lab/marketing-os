from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import (
    MODES,
    config_text,
    overlay_root,
    read_config,
    slugify,
    template_root,
)
from marketing_os.core.skills import apply_sync, plan_sync, project_manifest

CHOOSE_MODE_REASON = (
    "Ask the user: are you marketing one brand you run in-house, or running an agency "
    "that serves clients? Choices: in-house (one brand you own), agency (you serve "
    "clients; creates the agency HQ with a client registry), client (a brain for one "
    "agency client). Then re-run setup with --mode <choice> (client mode: add "
    "--agency <agency name>)."
)


def _render(text: str, name: str) -> str:
    """Fill template placeholders.

    ``{{TODAY}}`` seeds the ``date`` field of the frontmatter contract so scaffolded
    documents are born contract-compliant instead of needing a later backfill.
    """
    return text.replace("{{BUSINESS_NAME}}", name.strip()).replace(
        "{{TODAY}}", datetime.date.today().isoformat()
    )


def _tree_actions(root: Path, target: Path) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    if not root.is_dir():
        return actions
    for source in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = source.relative_to(root)
        destination = target / relative
        if destination.exists():
            continue
        actions.append(
            {
                "source": str(source),
                "destination": str(destination),
                "relative": relative.as_posix(),
            }
        )
    return actions


def suggested_repo_name(name: str, mode: str, agency: str | None) -> str:
    slug = slugify(name)
    if mode == "client" and agency and agency.strip():
        return f"{slugify(agency)}-{slug}"
    return f"{slug}-hq"


def _template_actions(
    target: Path, name: str, mode: str, agency: str | None
) -> list[dict[str, str]]:
    actions = _tree_actions(template_root(), target)
    actions.extend(_tree_actions(overlay_root() / mode, target))
    config = target / ".mos" / "config.yaml"
    if not config.exists():
        stored_agency = agency if mode == "client" else None
        actions.append(
            {
                "source": "",
                "destination": str(config),
                "relative": ".mos/config.yaml",
                "content": config_text(name, mode=mode, agency=stored_agency),
            }
        )
    return actions


def _apply_templates(actions: list[dict[str, str]], name: str) -> None:
    for action in actions:
        destination = Path(action["destination"])
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if "content" in action:
            text = action["content"]
        else:
            text = Path(action["source"]).read_text(encoding="utf-8")
        destination.write_text(_render(text, name), encoding="utf-8")


def setup_repo(
    target: Path,
    name: str,
    runtime: str,
    *,
    mode: str | None = None,
    agency: str | None = None,
    apply: bool,
) -> dict[str, Any]:
    target = target.expanduser().resolve()
    findings: list[dict[str, str]] = []
    if not name.strip():
        findings.append(finding("missing-name", "Business name must not be empty."))
    if target.exists() and any(target.iterdir()) and read_config(target) is None:
        findings.append(
            finding(
                "unsupported-directory",
                "The destination is non-empty and is not a marketing-os repository. "
                "Use a new empty destination.",
                path=str(target),
            )
        )

    mode_blocked = False
    if mode is None:
        mode_blocked = True
        findings.append(
            finding(
                "mode-required",
                "Setup requires --mode; choose in-house, agency, or client.",
            )
        )
    elif mode not in MODES:
        mode_blocked = True
        findings.append(
            finding("invalid-mode", f"Mode {mode!r} is not one of in-house, agency, client.")
        )
    elif mode == "client" and not (agency and agency.strip()):
        mode_blocked = True
        findings.append(finding("agency-required", "Client mode requires --agency <agency name>."))
    elif mode != "client" and agency and agency.strip():
        findings.append(
            finding(
                "agency-ignored",
                f"--agency is only recorded in client mode; ignored for {mode}.",
                severity="warning",
            )
        )

    if any(item["severity"] == "error" for item in findings):
        if mode_blocked:
            action = next_action("choose-mode", CHOOSE_MODE_REASON)
        else:
            action = next_action(
                "choose-empty-destination", "Choose an empty folder for the new business brain."
            )
        return envelope(
            "setup",
            target,
            ok=False,
            findings=findings,
            action=action,
            applied=False,
            planned=not apply,
        )

    assert mode is not None  # narrowed by the guards above
    repo_name = suggested_repo_name(name, mode, agency)
    file_actions = _template_actions(target, name, mode, agency)
    skill_actions, skill_findings = plan_sync(
        target, runtime, manifest_path=project_manifest(target)
    )
    findings.extend(skill_findings)
    changes = [f"create {item['relative']}" for item in file_actions]
    changes.extend(
        f"{item['action']} {Path(item['destination']).relative_to(target).as_posix()}"
        for item in skill_actions
    )
    errors = [item for item in findings if item["severity"] == "error"]
    if apply and not errors:
        target.mkdir(parents=True, exist_ok=True)
        _apply_templates(file_actions, name)
        apply_sync(skill_actions, project_manifest(target))

    ok = not errors
    action = next_action(
        "apply-setup" if not apply and changes else "complete-context",
        "Apply the reviewed setup plan."
        if not apply and changes
        else "Complete the audience, offer, and voice context with the setup skill.",
    )
    if apply and not changes:
        action = next_action("run-start", "The repository is already scaffolded and wired.")
    return envelope(
        "setup",
        target,
        ok=ok,
        changes=changes,
        findings=findings,
        action=action,
        applied=apply and ok,
        planned=not apply,
        mode=mode,
        suggested_repo_name=repo_name,
    )
