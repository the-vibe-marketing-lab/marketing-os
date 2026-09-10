from __future__ import annotations

import hashlib
import json
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any

from marketing_os.core.parallel import pmap
from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import skills_root

RUNTIME_DIRS = {"claude": Path(".claude/skills"), "codex": Path(".agents/skills")}


def normalize_runtimes(runtime: str) -> tuple[str, ...]:
    if runtime == "all":
        return ("claude", "codex")
    if runtime in RUNTIME_DIRS:
        return (runtime,)
    raise ValueError("runtime must be one of: claude, codex, all")


@lru_cache(maxsize=1)
def bundled_skills() -> tuple[str, ...]:
    """The skills this distribution ships, named by the packaged manifest.

    Read once per process: the manifest is inside the installed distribution and cannot
    change under a running one. The tuple is immutable, so one shared answer is safe.
    """
    payload = json.loads((skills_root() / "manifest.json").read_text(encoding="utf-8"))
    names = payload.get("skills", [])
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError("invalid packaged skill manifest")
    return tuple(names)


@lru_cache(maxsize=64)
def source_hash(name: str) -> str:
    """The digest of one packaged skill, computed once per process.

    ``inspect_runtimes`` asks what every skill ought to hash to once per runtime, and
    ``mos doctor`` used to ask the whole question twice, so the same nine read-only
    directories inside the installed distribution were being hashed thirty-six times for
    one dashboard. They are the same nine directories every time.
    """
    return tree_hash(skills_root() / name)


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.is_dir():
        return ""
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        relative = item.relative_to(path).as_posix()
        if "__pycache__" in item.parts:
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema": "mos.runtime-manifest.v1", "runtimes": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": "mos.runtime-manifest.v1", "runtimes": {}}
    return (
        payload
        if isinstance(payload, dict)
        else {"schema": "mos.runtime-manifest.v1", "runtimes": {}}
    )


def project_manifest(root: Path) -> Path:
    return root / ".mos" / "local" / "runtime-manifest.json"


def global_manifest(home: Path) -> Path:
    return home / ".marketing-os" / "runtime-manifest.json"


def plan_sync(
    target: Path,
    runtime: str,
    *,
    manifest_path: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    actions: list[dict[str, str]] = []
    findings: list[dict[str, str]] = []
    manifest = _load_manifest(manifest_path)
    recorded = manifest.get("runtimes", {})
    if not isinstance(recorded, dict):
        recorded = {}

    for runtime_name in normalize_runtimes(runtime):
        runtime_record = recorded.get(runtime_name, {})
        if not isinstance(runtime_record, dict):
            runtime_record = {}
        for name in bundled_skills():
            source = skills_root() / name
            destination = target / RUNTIME_DIRS[runtime_name] / name
            expected = source_hash(name)
            current = tree_hash(destination)
            previous = runtime_record.get(name, "")
            if current == expected:
                continue
            if not destination.exists():
                action = "create"
            elif previous and current == previous:
                action = "replace"
            else:
                findings.append(
                    finding(
                        "skill-conflict",
                        "An unrecognized skill directory blocks generated runtime wiring.",
                        path=str(destination),
                    )
                )
                continue
            actions.append(
                {
                    "action": action,
                    "runtime": runtime_name,
                    "skill": name,
                    "source": str(source),
                    "destination": str(destination),
                    "hash": expected,
                }
            )
    return actions, findings


def apply_sync(actions: list[dict[str, str]], manifest_path: Path) -> None:
    if not actions:
        return
    manifest = _load_manifest(manifest_path)
    runtimes = manifest.setdefault("runtimes", {})
    if not isinstance(runtimes, dict):
        runtimes = {}
        manifest["runtimes"] = runtimes

    for action in actions:
        source = Path(action["source"])
        destination = Path(action["destination"])
        if action["action"] == "replace" and destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
        runtime_record = runtimes.setdefault(action["runtime"], {})
        if isinstance(runtime_record, dict):
            runtime_record[action["skill"]] = action["hash"]

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def sync_result(root: Path, runtime: str, *, apply: bool, global_install: bool) -> dict[str, Any]:
    """Plan or apply a skill sync and report it as an envelope.

    Shared by ``mos install``, ``mos skills sync`` and ``mos fix runtime-not-ready``, so
    the three can never drift apart on what a sync reports.
    """
    if global_install:
        manifest = global_manifest(root)
        command = "install"
    else:
        manifest = project_manifest(root)
        command = "skills-sync"
    actions, findings = plan_sync(root, runtime, manifest_path=manifest)
    if apply and not findings:
        apply_sync(actions, manifest)
    changes = [
        f"{item['action']} {Path(item['destination']).relative_to(root).as_posix()}"
        for item in actions
    ]
    if findings:
        action = next_action("resolve-skill-conflict", "Review the conflicting skill directories.")
    elif actions and not apply:
        action = next_action("apply-skill-sync", "Apply the reviewed skill synchronization plan.")
    else:
        action = next_action("run-start", "The shared skills are ready.")
    return envelope(
        command,
        root,
        ok=not findings,
        changes=changes,
        findings=findings,
        action=action,
        applied=apply and not findings,
        planned=not apply,
        runtime=runtime,
    )


def inspect_runtimes(root: Path) -> dict[str, dict[str, Any]]:
    """What each runtime's skill directory holds, against what this distribution ships.

    Every installed skill is hashed at the same time as the others. There are eighteen of
    them across the two runtimes, each one a small directory read on a filesystem where the
    read is the cost, and asking for them one after another was a third of what a status
    check spent. The answers are put back against the pair that asked for them, so the
    envelope is the same envelope in the same order.
    """
    names = bundled_skills()
    pairs = [(runtime, name) for runtime in RUNTIME_DIRS for name in names]
    digests = dict(
        zip(
            pairs,
            pmap(lambda pair: tree_hash(root / RUNTIME_DIRS[pair[0]] / pair[1]), pairs),
            strict=True,
        )
    )
    result: dict[str, dict[str, Any]] = {}
    for runtime_name, relative in RUNTIME_DIRS.items():
        missing: list[str] = []
        mismatched: list[str] = []
        hashes: dict[str, str] = {}
        for name in names:
            expected = source_hash(name)
            current = digests[(runtime_name, name)]
            hashes[name] = current
            if not current:
                missing.append(name)
            elif current != expected:
                mismatched.append(name)
        result[runtime_name] = {
            "ready": not missing and not mismatched,
            "skill_dir": str((root / relative).resolve()),
            "missing": missing,
            "mismatched": mismatched,
            "hashes": hashes,
        }
    return result
