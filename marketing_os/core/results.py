from __future__ import annotations

from pathlib import Path
from typing import Any


def finding(code: str, message: str, *, severity: str = "error", path: str = "") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message, "path": path}


def next_action(action_id: str, reason: str) -> dict[str, str]:
    return {"id": action_id, "reason": reason}


def envelope(
    command: str,
    repo: Path,
    *,
    ok: bool,
    changes: list[str] | None = None,
    findings: list[dict[str, str]] | None = None,
    action: dict[str, str] | None = None,
    **facts: Any,
) -> dict[str, Any]:
    return {
        "schema": f"mos.{command}.v1",
        "command": command,
        "ok": ok,
        "repo": str(repo.resolve()),
        "changes": changes or [],
        "findings": findings or [],
        "next_action": action or next_action("none", "No further action is required."),
        **facts,
    }
