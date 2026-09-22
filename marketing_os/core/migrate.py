from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import load_schema, read_config

PLAN_SCHEMA = "mos.migrate-plan.v1"


def _canonical_top_level() -> tuple[set[str], set[str]]:
    schema = load_schema()
    allowed_dirs = set(schema["allowed_top_level"])
    allowed_files = {Path(rel).name for rel in schema["required_files"] if "/" not in rel}
    return allowed_dirs, allowed_files


def _stray_entries(root: Path) -> list[str]:
    allowed_dirs, allowed_files = _canonical_top_level()
    stray: list[str] = []
    if not root.is_dir():
        return stray
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if child.name.startswith("."):
            continue
        if child.is_dir() and child.name in allowed_dirs:
            continue
        if child.is_file() and child.name in allowed_files:
            continue
        stray.append(child.name)
    return stray


def _resolve_inside(root: Path, relative: str) -> Path | None:
    """Resolve ``relative`` against ``root`` and confirm the result stays inside the repo."""
    raw = Path(relative)
    candidate = (raw if raw.is_absolute() else root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _diagnose(root: Path, *, apply: bool) -> dict[str, Any]:
    stray = _stray_entries(root)
    findings: list[dict[str, str]] = []
    if read_config(root) is None:
        findings.append(
            finding(
                "not-marketing-os",
                "Initialize the canonical structure with setup before routing files.",
                severity="warning",
            )
        )
    findings.extend(
        finding(
            "off-schema-entry",
            "Top-level entry is outside the canonical architecture; route it with a plan.",
            severity="warning",
            path=name,
        )
        for name in stray
    )
    if stray:
        action = next_action(
            "build-migrate-plan",
            f"Write a {PLAN_SCHEMA} file mapping each stray entry to a canonical destination, "
            "then apply it with --plan-file.",
        )
    else:
        action = next_action("run-status", "No off-schema entries found; nothing to migrate.")
    return envelope(
        "migrate",
        root,
        ok=True,
        findings=findings,
        action=action,
        applied=False,
        planned=not apply,
        unrouted=stray,
        plan_schema=PLAN_SCHEMA,
    )


def _load_plan(plan_path: Path) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    if not plan_path.is_file():
        return None, [
            finding("missing-plan-file", "The plan file does not exist.", path=str(plan_path))
        ]
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, [
            finding("invalid-plan-file", "The plan file is not valid JSON.", path=str(plan_path))
        ]
    if not isinstance(payload, dict) or payload.get("schema") != PLAN_SCHEMA:
        return None, [finding("unsupported-plan", f"The plan must declare schema {PLAN_SCHEMA}.")]
    return payload, []


def _validate_moves(
    root: Path, moves: Any
) -> tuple[list[tuple[Path, Path, str, str]], list[dict[str, str]]]:
    valid: list[tuple[Path, Path, str, str]] = []
    findings: list[dict[str, str]] = []
    if not isinstance(moves, list):
        return valid, [finding("invalid-plan", "Plan 'moves' must be a list.")]
    for index, move in enumerate(moves):
        if not isinstance(move, dict) or "source" not in move or "destination" not in move:
            findings.append(
                finding(
                    "invalid-move",
                    "Each move needs a source and a destination.",
                    path=str(index),
                )
            )
            continue
        source = _resolve_inside(root, str(move["source"]))
        destination = _resolve_inside(root, str(move["destination"]))
        if source is None or not source.exists():
            findings.append(
                finding(
                    "missing-source",
                    "Move source is missing or outside the repo.",
                    path=str(move["source"]),
                )
            )
            continue
        if destination is None:
            findings.append(
                finding(
                    "destination-outside-repo",
                    "Move destination escapes the repository.",
                    path=str(move["destination"]),
                )
            )
            continue
        if destination.exists():
            findings.append(
                finding(
                    "destination-exists",
                    "Move destination already exists; refusing to overwrite.",
                    path=str(move["destination"]),
                )
            )
            continue
        valid.append((source, destination, str(move["source"]), str(move["destination"])))
    return valid, findings


def _validate_mkdirs(root: Path, mkdirs: Any) -> tuple[list[Path], list[dict[str, str]]]:
    valid: list[Path] = []
    findings: list[dict[str, str]] = []
    if not isinstance(mkdirs, list):
        return valid, [finding("invalid-plan", "Plan 'mkdirs' must be a list.")]
    for relative in mkdirs:
        target = _resolve_inside(root, str(relative))
        if target is None:
            findings.append(
                finding(
                    "mkdir-outside-repo",
                    "Directory escapes the repository.",
                    path=str(relative),
                )
            )
            continue
        valid.append(target)
    return valid, findings


def migrate_repo(root: Path, *, plan_file: str | None = None, apply: bool) -> dict[str, Any]:
    """Diagnose off-schema entries, or apply a deterministic routing plan.

    Without ``plan_file`` and in plan mode, report the stray top-level entries so a skill can
    build a routing plan. With a ``plan_file`` the moves are validated as a set and applied
    atomically — nothing is written if any move is invalid, and existing paths are never
    overwritten.
    """
    root = root.expanduser().resolve()

    if plan_file is None:
        if apply:
            return envelope(
                "migrate",
                root,
                ok=False,
                findings=[
                    finding(
                        "missing-plan-file",
                        "Applying a migration requires --plan-file. Run --plan first to diagnose.",
                    )
                ],
                action=next_action(
                    "build-migrate-plan",
                    "Run migrate --plan to see off-schema entries, then build a plan file.",
                ),
                applied=False,
                planned=False,
            )
        return _diagnose(root, apply=apply)

    plan, findings = _load_plan(Path(plan_file).expanduser().resolve())
    if plan is None:
        return envelope(
            "migrate",
            root,
            ok=False,
            findings=findings,
            action=next_action("fix-plan-file", f"Provide a valid {PLAN_SCHEMA} plan file."),
            applied=False,
            planned=not apply,
        )

    mkdir_targets, mkdir_findings = _validate_mkdirs(root, plan.get("mkdirs", []) or [])
    valid_moves, move_findings = _validate_moves(root, plan.get("moves", []) or [])
    findings.extend(mkdir_findings)
    findings.extend(move_findings)

    changes = [f"mkdir {rel}" for rel in (plan.get("mkdirs", []) or [])]
    changes.extend(f"move {source} -> {destination}" for _, _, source, destination in valid_moves)

    errors = [item for item in findings if item["severity"] == "error"]
    if errors:
        return envelope(
            "migrate",
            root,
            ok=False,
            changes=changes,
            findings=findings,
            action=next_action("repair-plan", "Fix the reported plan errors, then re-apply."),
            applied=False,
            planned=not apply,
            moved=0,
        )

    if apply:
        for target in mkdir_targets:
            target.mkdir(parents=True, exist_ok=True)
        for source, destination, _, _ in valid_moves:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))

    action = (
        next_action("run-validate", "Routing applied; run validate to confirm the structure.")
        if apply
        else next_action("apply-migrate", "Apply the reviewed migrate plan.")
    )
    return envelope(
        "migrate",
        root,
        ok=True,
        changes=changes,
        findings=findings,
        action=action,
        applied=apply,
        planned=not apply,
        moved=len(valid_moves),
        created_dirs=len(mkdir_targets),
    )
