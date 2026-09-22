"""Contract sensors for the navigation layer.

Prose in a contract file decays; a sensor does not. These checks are what keep the
frontmatter contract true, and they are the reason a brain never needs the retrospective
backfill that a corpus without them eventually demands.

Everything here is a warning by default, so an early-stage brain is never blocked. The
``--strict`` flag on ``mos validate`` promotes them to errors for continuous integration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from marketing_os.core.catalog import build_catalog
from marketing_os.core.related import RELATED_MIN_WORDS
from marketing_os.core.results import finding
from marketing_os.core.schema import is_exempt_name, load_schema

CODES = (
    "missing-frontmatter",
    "missing-connective-key",
    "output-without-sources",
    "unlinked-document",
    "invalid-type",
    "invalid-status",
)


def _contract() -> dict[str, Any]:
    return load_schema()["frontmatter_contract"]


def expected_type(relative: str, folder_types: dict[str, str]) -> str | None:
    """The type a document's location implies, longest folder match first."""
    best: tuple[int, str] | None = None
    for folder, kind in folder_types.items():
        if relative.startswith(folder + "/") and (best is None or len(folder) > best[0]):
            best = (len(folder), kind)
    return best[1] if best else None


def contract_findings(
    root: Path, docs: dict[str, dict[str, Any]] | None = None
) -> list[dict[str, str]]:
    """Every contract gap in the brain, as warnings, sorted by path then code."""
    contract = _contract()
    types = set(contract["types"])
    statuses = set(contract["statuses"])
    folder_types: dict[str, str] = contract["folder_types"]
    sources_required = tuple(f"{name}/" for name in contract["sources_required_in"])
    if docs is None:
        docs = build_catalog(root)

    findings: list[dict[str, str]] = []
    for relative in sorted(docs):
        if is_exempt_name(Path(relative).name):
            continue
        doc = docs[relative]
        if not doc["has_frontmatter"]:
            findings.append(
                finding(
                    "missing-frontmatter",
                    "No contract block. See CONTRACT.md for the five required keys.",
                    severity="warning",
                    path=relative,
                )
            )
        elif doc["missing_keys"]:
            findings.append(
                finding(
                    "missing-frontmatter",
                    "Contract block is missing " + ", ".join(doc["missing_keys"]) + ".",
                    severity="warning",
                    path=relative,
                )
            )
        kind = doc["type"]
        if kind and kind not in types:
            findings.append(
                finding(
                    "invalid-type",
                    f"Type {kind!r} is outside the schema vocabulary.",
                    severity="warning",
                    path=relative,
                )
            )
        else:
            wanted = expected_type(relative, folder_types)
            if kind and wanted and kind != wanted:
                findings.append(
                    finding(
                        "invalid-type",
                        f"Type {kind!r} does not match this location; expected {wanted!r}.",
                        severity="warning",
                        path=relative,
                    )
                )
        status = doc["status"]
        if status and status not in statuses:
            findings.append(
                finding(
                    "invalid-status",
                    f"Status {status!r} is not one of " + ", ".join(sorted(statuses)) + ".",
                    severity="warning",
                    path=relative,
                )
            )
        if relative.startswith(sources_required) and "sources" not in doc["connective_keys"]:
            findings.append(
                finding(
                    "output-without-sources",
                    "Deliverables record what they were built from. An output with no "
                    "sources is not finished.",
                    severity="warning",
                    path=relative,
                )
            )
        elif doc["has_frontmatter"] and not doc["connective_keys"]:
            findings.append(
                finding(
                    "missing-connective-key",
                    "Add one of sources, related, or produced_by so this document is "
                    "reachable from somewhere else.",
                    severity="warning",
                    path=relative,
                )
            )
        if (
            doc["words"] >= RELATED_MIN_WORDS
            and not doc["links_out"]
            and not doc["has_related_block"]
        ):
            findings.append(
                finding(
                    "unlinked-document",
                    "Substantial document with no outgoing links. Run `mos related . --yes`.",
                    severity="warning",
                    path=relative,
                )
            )
    return findings
