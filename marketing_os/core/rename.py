"""Rename a brain: the business name in its settings, and nothing else.

The name lives in ``.mos/config.yaml`` and is what every surface shows for the brain.
Documents that already mention the old name are left as they are: they are the
operator's writing, and a rename is not a licence to edit it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import read_config

CONFIG_RELATIVE = ".mos/config.yaml"


def rename_repo(root: Path, name: str, *, apply: bool) -> dict[str, Any]:
    root = root.expanduser().resolve()
    config = read_config(root)
    clean = name.strip()
    findings: list[dict[str, str]] = []
    if config is None:
        findings.append(
            finding("not-marketing-os", "This is not a marketing-os business repository.")
        )
    if not clean:
        findings.append(finding("missing-name", "Business name must not be empty."))
    if findings:
        return envelope(
            "rename",
            root,
            ok=False,
            findings=findings,
            action=next_action(
                "choose-name" if config is not None else "choose-brain",
                "Give the business a name." if config is not None else "Point at a brain first.",
            ),
            applied=False,
            planned=not apply,
        )

    assert config is not None  # narrowed above
    previous = str(config.get("business_name", ""))
    if clean == previous:
        return envelope(
            "rename",
            root,
            ok=True,
            changes=[],
            action=next_action("none", "The brain already has that name."),
            applied=False,
            planned=not apply,
            name=clean,
            previous_name=previous,
        )

    changes = [f"update {CONFIG_RELATIVE}"]
    if apply:
        config["business_name"] = clean
        (root / ".mos" / "config.yaml").write_text(
            json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return envelope(
        "rename",
        root,
        ok=True,
        changes=changes,
        action=next_action(
            "apply-rename" if not apply else "run-status",
            "Apply the rename." if not apply else "The brain has its new name.",
        ),
        applied=apply,
        planned=not apply,
        name=clean,
        previous_name=previous,
    )
