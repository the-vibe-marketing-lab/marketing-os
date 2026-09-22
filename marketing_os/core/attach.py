"""Adopt a folder that already holds a brain-shaped layout as a marketing-os brain.

``onboard`` scaffolds a new brain and refuses a non-empty folder that is not already one.
``attach`` is the other door: a folder that grew a brain before this engine existed — a
YAML ``.mos/config.yaml`` the JSON reader rejects, a ``BRAIN.md`` beside a ``business/``
tree — is recognised for what it is and wired up **without** touching the operator's own
documents. Only two kinds of write ever happen here:

1. ``.mos/config.yaml`` is rewritten in the canonical JSON form (the old text is kept as
   ``.mos/config.legacy.yaml`` when it differs), because that file is how every other
   command recognises a brain.
2. Scaffold files the operator does not have yet — the top-level contract documents, the
   required (empty) directories, and the generated runtime skill copies — are added.
   Nothing that exists is overwritten, and no ``business/`` or ``knowledge/`` content file
   is ever created, so nothing of the engine's can shadow what the operator wrote.

Anything off-schema is reported as a finding that points at ``mos migrate --plan``; the
judgement of where a stray file belongs is not made here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from marketing_os.core.atomic import atomic_write
from marketing_os.core.migrate import _stray_entries
from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import (
    MODES,
    config_text,
    load_schema,
    read_config,
    template_root,
)
from marketing_os.core.setup import _render
from marketing_os.core.skills import apply_sync, plan_sync, project_manifest

CONFIG_RELATIVE = Path(".mos") / "config.yaml"
LEGACY_BACKUP_RELATIVE = Path(".mos") / "config.legacy.yaml"
DEFAULT_MODE = "in-house"
#: Legacy config keys that may carry the business name, most specific first.
_NAME_KEYS = ("business_name", "name")
#: Directories whose scaffold documents are the operator's to write, never the engine's.
_OPERATOR_CONTENT = ("business", "knowledge")


# --- detection ---------------------------------------------------------------------


def parse_simple_yaml(text: str) -> dict[str, str]:
    """Read the flat ``key: value`` subset of YAML a legacy config was written in.

    Deliberately tiny: top-level scalar pairs only, comments and blank lines skipped,
    matching quotes stripped. Indented or structured lines are ignored rather than
    guessed at, and a text that yields no pair is simply not a legacy config.
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or raw[:1].isspace():
            continue
        if raw.strip() == "---" or ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        if not key or " " in key or key.startswith(("-", "{", "[")):
            continue
        if " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if not value:
            # A bare ``key:`` opens a nested mapping, which this reader does not follow.
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def legacy_config(root: Path) -> dict[str, str] | None:
    """The parsed legacy config, or None when the file is absent, JSON, or unreadable."""
    path = root / CONFIG_RELATIVE
    try:
        if not path.is_file() or read_config(root) is not None:
            return None
        parsed = parse_simple_yaml(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    return parsed or None


def looks_like_brain(root: Path) -> bool:
    """A ``BRAIN.md`` beside a ``business/`` tree is a brain, whatever its config says."""
    try:
        return (root / "BRAIN.md").is_file() and (root / "business").is_dir()
    except OSError:
        return False


def legacy_summary(root: Path) -> dict[str, Any] | None:
    """Name and mode of a legacy brain at ``root``, or None when it is not one.

    A canonical brain is never legacy; the caller checks ``read_config`` for that.
    """
    try:
        if read_config(root) is not None:
            return None
        legacy = legacy_config(root)
        if legacy is None and not looks_like_brain(root):
            return None
    except Exception:
        return None
    name, mode = _resolve_identity(root, legacy or {}, None, None)
    return {"name": name, "mode": mode}


def _resolve_identity(
    root: Path, legacy: dict[str, str], name: str | None, mode: str | None
) -> tuple[str, str]:
    resolved_name = (name or "").strip()
    if not resolved_name:
        for key in _NAME_KEYS:
            if legacy.get(key, "").strip():
                resolved_name = legacy[key].strip()
                break
    if not resolved_name:
        resolved_name = root.name or "business"
    resolved_mode = (mode or "").strip() or legacy.get("mode", "").strip()
    if resolved_mode not in MODES:
        resolved_mode = DEFAULT_MODE
    return resolved_name, resolved_mode


# --- planning ----------------------------------------------------------------------


def _backup_target(root: Path, existing: str) -> Path | None:
    """Where the current config text is kept before it is overwritten, or None.

    The first backup is ``config.legacy.yaml``. A later attach that finds a different
    config (the operator restored an old one, say) must not overwrite it silently and
    must not clobber the first backup either, so it takes the next free number:
    ``config.legacy.1.yaml``, ``config.legacy.2.yaml``, ... A backup that already holds
    this exact text needs no twin.
    """
    backup = root / LEGACY_BACKUP_RELATIVE
    if not backup.exists():
        return backup
    candidates = [backup, *sorted(backup.parent.glob("config.legacy.*.yaml"))]
    for candidate in candidates:
        try:
            if candidate.read_text(encoding="utf-8") == existing:
                return None
        except (OSError, UnicodeDecodeError):
            continue
    number = 1
    while (backup.parent / f"config.legacy.{number}.yaml").exists():
        number += 1
    return backup.parent / f"config.legacy.{number}.yaml"


def _config_actions(root: Path, name: str, mode: str, agency: str | None) -> list[dict[str, str]]:
    config = root / CONFIG_RELATIVE
    text = config_text(name, mode=mode, agency=agency)
    actions: list[dict[str, str]] = []
    existing = config.read_text(encoding="utf-8") if config.is_file() else None
    backup = _backup_target(root, existing) if existing is not None and existing != text else None
    if existing is not None and backup is not None:
        actions.append(
            {
                "kind": "backup",
                "relative": backup.relative_to(root).as_posix(),
                "destination": str(backup),
                "content": existing,
            }
        )
    if existing != text:
        actions.append(
            {
                "kind": "config",
                "relative": CONFIG_RELATIVE.as_posix(),
                "destination": str(config),
                "content": text,
            }
        )
    return actions


def _scaffold_actions(root: Path) -> list[dict[str, str]]:
    """Missing top-level scaffold files and required directories, never content files."""
    template = template_root()
    actions: list[dict[str, str]] = []
    for source in sorted(template.iterdir(), key=lambda item: item.name):
        if not source.is_file() or (root / source.name).exists():
            continue
        actions.append(
            {
                "kind": "create",
                "relative": source.name,
                "destination": str(root / source.name),
                "source": str(source),
            }
        )
    for relative in load_schema()["required_directories"]:
        if relative == ".mos" or (root / relative).exists():
            continue
        keep = template / relative / ".gitkeep"
        actions.append(
            {
                "kind": "mkdir",
                "relative": relative,
                "destination": str(root / relative),
                "source": str(keep) if keep.is_file() else "",
            }
        )
    return actions


def _apply_file_actions(actions: list[dict[str, str]], name: str) -> None:
    for action in actions:
        destination = Path(action["destination"])
        kind = action["kind"]
        if kind == "mkdir":
            destination.mkdir(parents=True, exist_ok=True)
            if action["source"] and not (destination / ".gitkeep").exists():
                (destination / ".gitkeep").write_bytes(Path(action["source"]).read_bytes())
            continue
        if kind == "create":
            if destination.exists():
                continue
            text = _render(Path(action["source"]).read_text(encoding="utf-8"), name)
        else:
            text = action["content"]
        # The config and its backup are the operator's recognition record; a half-written
        # config would make the brain vanish from every command at once.
        atomic_write(destination, text)


def _content_findings(root: Path, stray: list[str]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for relative in load_schema()["required_files"]:
        if not relative.startswith(_OPERATOR_CONTENT) or (root / relative).is_file():
            continue
        findings.append(
            finding(
                "missing-content-file",
                "A required document is missing; attach never writes operator content. "
                "Route an existing file there with mos migrate --plan, or write it.",
                severity="warning",
                path=relative,
            )
        )
    findings.extend(
        finding(
            "off-schema-entry",
            "Top-level entry is outside the canonical architecture; "
            "route it with mos migrate --plan.",
            severity="warning",
            path=name,
        )
        for name in stray
    )
    return findings


def _refuse(
    root: Path, code: str, message: str, action: dict[str, str], *, apply: bool
) -> dict[str, Any]:
    return envelope(
        "attach",
        root,
        ok=False,
        findings=[finding(code, message, path=str(root))],
        action=action,
        applied=False,
        planned=not apply,
    )


def attach_repo(
    root: Path,
    *,
    name: str | None = None,
    mode: str | None = None,
    runtime: str = "all",
    apply: bool,
) -> dict[str, Any]:
    """Plan or apply the adoption of ``root`` as a marketing-os brain."""
    root = root.expanduser().resolve()
    if not root.is_dir():
        return _refuse(
            root,
            "missing-directory",
            "The folder to attach does not exist.",
            next_action("choose-folder", "Point attach at an existing folder."),
            apply=apply,
        )
    if mode is not None and mode not in MODES:
        return _refuse(
            root,
            "invalid-mode",
            f"Mode {mode!r} is not one of in-house, agency, client.",
            next_action("choose-mode", "Re-run attach with --mode in-house, agency, or client."),
            apply=apply,
        )
    canonical = read_config(root)
    if canonical is not None:
        return envelope(
            "attach",
            root,
            ok=True,
            findings=[
                finding(
                    "already-attached",
                    "This folder is already a marketing-os brain; nothing to do.",
                    severity="info",
                    path=str(root),
                )
            ],
            action=next_action("run-status", f"Run mos status {root}."),
            applied=False,
            planned=not apply,
            name=canonical.get("business_name"),
            mode=canonical.get("mode"),
            legacy=None,
        )
    legacy = legacy_config(root)
    if legacy is None and not looks_like_brain(root):
        return _refuse(
            root,
            "not-a-brain",
            "No legacy .mos/config.yaml and no BRAIN.md beside business/; "
            "attach adopts existing brains only. Create a new one with mos onboard.",
            next_action("run-onboard", "Scaffold a new brain here with mos onboard."),
            apply=apply,
        )

    findings: list[dict[str, str]] = []
    legacy_mode = (legacy or {}).get("mode", "").strip()
    if legacy_mode and legacy_mode not in MODES and mode is None:
        findings.append(
            finding(
                "legacy-mode-ignored",
                f"Legacy mode {legacy_mode!r} is not one of in-house, agency, client; "
                f"using {DEFAULT_MODE}. Override with --mode.",
                severity="warning",
                path=CONFIG_RELATIVE.as_posix(),
            )
        )
    resolved_name, resolved_mode = _resolve_identity(root, legacy or {}, name, mode)
    agency = (legacy or {}).get("agency", "").strip() or None
    if resolved_mode == "client" and agency is None:
        findings.append(
            finding(
                "legacy-agency-missing",
                "Client mode, but no agency is known: the legacy config has no agency key. "
                "Add one to .mos/config.yaml after attaching so the client can be tied "
                "to its agency HQ.",
                severity="warning",
                path=CONFIG_RELATIVE.as_posix(),
            )
        )

    file_actions = _config_actions(root, resolved_name, resolved_mode, agency)
    file_actions.extend(_scaffold_actions(root))
    skill_actions, skill_findings = plan_sync(root, runtime, manifest_path=project_manifest(root))
    findings.extend(skill_findings)
    stray = _stray_entries(root)
    findings.extend(_content_findings(root, stray))

    changes: list[str] = []
    for item in file_actions:
        changes.append(f"{item['kind']} {item['relative']}")
        if item["kind"] == "mkdir" and item["source"]:
            # Apply drops a .gitkeep into every directory it makes; the plan says so too.
            changes.append(f"create {item['relative']}/.gitkeep")
    changes.extend(
        f"{item['action']} {Path(item['destination']).relative_to(root).as_posix()}"
        for item in skill_actions
    )
    errors = [item for item in findings if item["severity"] == "error"]
    if apply and not errors:
        _apply_file_actions(file_actions, resolved_name)
        apply_sync(skill_actions, project_manifest(root))

    if errors:
        action = next_action("resolve-skill-conflict", "Review the conflicting skill directories.")
    elif apply:
        action = next_action("run-status", f"Run mos status {root}.")
    else:
        action = next_action("apply-attach", "Apply the reviewed attach plan with --yes.")
    return envelope(
        "attach",
        root,
        ok=not errors,
        changes=changes,
        findings=findings,
        action=action,
        applied=apply and not errors,
        planned=not apply,
        name=resolved_name,
        mode=resolved_mode,
        legacy=legacy,
        unrouted=stray,
    )


def plan_attach(
    root: Path, *, name: str | None = None, mode: str | None = None, runtime: str = "all"
) -> dict[str, Any]:
    return attach_repo(root, name=name, mode=mode, runtime=runtime, apply=False)


def apply_attach(
    root: Path, *, name: str | None = None, mode: str | None = None, runtime: str = "all"
) -> dict[str, Any]:
    return attach_repo(root, name=name, mode=mode, runtime=runtime, apply=True)
