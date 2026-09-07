from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from marketing_os.core.catalog import build_catalog
from marketing_os.core.graphlint import CODES, contract_findings
from marketing_os.core.parallel import gather
from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import load_schema, read_config, repo_mode

CONTRACT_CODES = frozenset(CODES)

YEAR = re.compile(r"^\d{4}$")
MONTH = re.compile(r"^(0[1-9]|1[0-2])$")
DATED = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*$")
QUARTER = re.compile(r"^Q[1-4]$")
YEAR_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


NAV_FILES = frozenset({".gitkeep", "_index.md", "_log.md"})


def _visible_children(path: Path) -> list[Path]:
    """Children that carry the dated-folder grammar.

    Generated navigation files live alongside dated folders and are not artifacts, so
    judging them against the YYYY/MM grammar would report the map as malformed content.
    """
    if not path.is_dir():
        return []
    return [child for child in path.iterdir() if child.name not in NAV_FILES]


def _check_year_month_dated(root: Path, relative: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    base = root / relative
    for year in _visible_children(base):
        if not year.is_dir() or not YEAR.fullmatch(year.name):
            findings.append(finding("invalid-year", "Expected a YYYY directory.", path=str(year)))
            continue
        for month in _visible_children(year):
            if not month.is_dir() or not MONTH.fullmatch(month.name):
                findings.append(
                    finding("invalid-month", "Expected an MM directory.", path=str(month))
                )
                continue
            for artifact in _visible_children(month):
                if not artifact.is_dir() or not DATED.fullmatch(artifact.name):
                    findings.append(
                        finding(
                            "invalid-dated-artifact",
                            "Expected a YYYY-MM-DD-slug directory.",
                            path=str(artifact),
                        )
                    )
    return findings


def _check_reporting(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for year in _visible_children(root / "reporting"):
        if not year.is_dir() or not YEAR.fullmatch(year.name):
            findings.append(finding("invalid-year", "Expected a YYYY directory.", path=str(year)))
            continue
        for quarter in _visible_children(year):
            if not quarter.is_dir() or not QUARTER.fullmatch(quarter.name):
                findings.append(
                    finding("invalid-quarter", "Expected a Q1-Q4 directory.", path=str(quarter))
                )
                continue
            for month in _visible_children(quarter):
                if not month.is_dir() or not YEAR_MONTH.fullmatch(month.name):
                    findings.append(
                        finding(
                            "invalid-report-month", "Expected a YYYY-MM directory.", path=str(month)
                        )
                    )
    return findings


def validation_findings(root: Path) -> list[dict[str, str]]:
    schema = load_schema()
    findings: list[dict[str, str]] = []
    config = read_config(root)
    if config is None:
        findings.append(
            finding(
                "missing-or-invalid-config",
                "Missing or invalid .mos/config.yaml.",
                path=".mos/config.yaml",
            )
        )
    elif (
        config.get("schema") != schema["schema"]
        or config.get("schema_version") != schema["version"]
    ):
        findings.append(
            finding(
                "unsupported-schema",
                "The repository schema is not supported.",
                path=".mos/config.yaml",
            )
        )

    if config is not None:
        mode, mode_findings = repo_mode(config)
        findings.extend(mode_findings)
        registry = root / "business" / "clients" / "clients.md"
        if any(item["code"] == "invalid-mode" for item in mode_findings):
            pass  # fail closed: do not judge structure against an unknown mode
        elif mode == "agency":
            if not registry.is_file():
                findings.append(
                    finding(
                        "missing-client-registry",
                        "Agency mode requires a client registry.",
                        path="business/clients/clients.md",
                    )
                )
        elif (root / "business" / "clients").is_dir():
            missing_mode = any(item["code"] == "missing-mode" for item in mode_findings)
            if missing_mode and registry.is_file():
                # Legacy repo (no explicit mode) that already carries a client
                # registry is almost certainly an agency HQ; guide the upgrade
                # instead of asserting it is in-house.
                findings.append(
                    finding(
                        "set-mode-agency",
                        'This repo has a client registry; add "mode": "agency" to '
                        ".mos/config.yaml.",
                        severity="warning",
                        path=".mos/config.yaml",
                    )
                )
            else:
                findings.append(
                    finding(
                        "unexpected-clients-folder",
                        f"{mode} mode should not hold a client registry.",
                        severity="warning",
                        path="business/clients",
                    )
                )

    # Two walks of two different parts of the brain: the shape of its folders, and the
    # contract inside its documents. Neither needs the other's answer, and both are almost
    # entirely spent waiting, so they run together. The findings are put back in the order
    # they have always come in — structure, then contract — because a caller comparing two
    # validation runs must not see them shuffle.
    structure, contract = gather(
        lambda: _structure_findings(root, schema),
        # The catalogue is built here and handed down. ``contract_findings`` has always
        # taken one and has always built its own when it was not given one, which meant
        # every validation pass read all fifteen hundred documents a second time for an
        # identical answer: the seam existed, nobody used it.
        lambda: contract_findings(root, build_catalog(root)),
    )
    findings.extend(structure)
    findings.extend(contract)
    return findings


def _structure_findings(root: Path, schema: dict[str, Any]) -> list[dict[str, str]]:
    """Everything the brain's folders say about themselves: what is missing, what is odd.

    Split out of ``validation_findings`` so it can be walked alongside the catalogue rather
    than before it. It reads directories only; nothing here opens a document.
    """
    findings: list[dict[str, str]] = []
    for relative in schema["required_directories"]:
        if not (root / relative).is_dir():
            findings.append(
                finding("missing-directory", "Required directory is missing.", path=relative)
            )
    for relative in schema["required_files"]:
        if not (root / relative).is_file():
            findings.append(finding("missing-file", "Required file is missing.", path=relative))

    allowed = set(schema["allowed_top_level"])
    allowed_files = {
        Path(relative).name for relative in schema["required_files"] if "/" not in relative
    }
    # Generated navigation files are legitimate top-level residents.
    allowed_files.update(schema.get("generated_files", []))
    if root.is_dir():
        for child in root.iterdir():
            if child.name.startswith(".") or child.name in allowed or child.name in allowed_files:
                continue
            findings.append(
                finding(
                    "unknown-top-level",
                    "Top-level path is outside the canonical architecture.",
                    severity="warning",
                    path=child.name,
                )
            )

    for relative in (
        "content",
        "campaigns",
        "outputs",
        "business/decisions",
        "knowledge/sources",
    ):
        findings.extend(_check_year_month_dated(root, relative))
    findings.extend(_check_reporting(root))
    return findings


def validate_repo(root: Path, *, strict: bool = False) -> dict[str, Any]:
    """Validate structure, dated-folder grammar, and the frontmatter contract.

    Contract gaps are warnings so an early-stage brain is never blocked. ``strict``
    promotes them to errors, which is what continuous integration should run.
    """
    root = root.expanduser().resolve()
    findings = validation_findings(root)
    if strict:
        findings = [
            {**item, "severity": "error"} if item["code"] in CONTRACT_CODES else item
            for item in findings
        ]
    errors = [item for item in findings if item["severity"] == "error"]
    contract_gaps = sum(1 for item in findings if item["code"] in CONTRACT_CODES)
    if errors:
        action = next_action("repair-structure", "Repair the reported structural errors.")
    elif contract_gaps:
        action = next_action(
            "close-contract-gaps",
            "Add the missing frontmatter and links so navigation stays cheap; "
            "`mos related . --yes` proposes the links.",
        )
    else:
        action = next_action("run-status", "Inspect context readiness and the next useful action.")
    return envelope(
        "validate",
        root,
        ok=not errors,
        findings=findings,
        action=action,
        strict=strict,
        summary={
            "errors": len(errors),
            "warnings": sum(1 for item in findings if item["severity"] == "warning"),
            "contract_gaps": contract_gaps,
        },
    )
