from __future__ import annotations

import datetime
import hashlib
import json
import re
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from marketing_os.core.results import finding

MODES = ("in-house", "agency", "client")
MONTH_FOLDER_STYLES = ("MM", "MM-Mon")
#: The trees whose artifacts are filed as ``YYYY/<month>/YYYY-MM-DD-slug``.
DATED_ROOTS = ("content", "campaigns", "outputs", "business/decisions", "knowledge/sources")
MONTH_ABBREVIATIONS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_MONTH_NAME = re.compile(r"(0[1-9]|1[0-2])(?:-(.+))?")


def assets_root() -> Path:
    return Path(str(resources.files("marketing_os").joinpath("assets")))


def template_root() -> Path:
    return assets_root() / "business-template"


def overlay_root() -> Path:
    return assets_root() / "mode-overlays"


def skills_root() -> Path:
    return assets_root() / "skills"


@lru_cache(maxsize=1)
def _schema_text() -> str:
    return (assets_root() / "schema.json").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    """The packaged schema, parsed once per process.

    It is a read-only asset inside the installed distribution, so it cannot change while
    this process runs, and it was being re-read thousands of times per status check: once
    per document from ``catalog.describe`` and once more per document from
    ``is_exempt_name``, six thousand reads of the same 2.5 kilobyte file for one request
    on a real brain. Reading it once instead is the single largest saving in the program.

    Every caller indexes or ``.get()``s the result and none mutates it, which is what
    makes one shared dictionary safe to hand out. Anything that needs to change the schema
    should copy what it needs first.
    """
    return json.loads(_schema_text())


@lru_cache(maxsize=1)
def schema_fingerprint() -> str:
    """A digest of the packaged schema, for caches that hold schema-derived answers.

    A document's catalogue entry is a reading of that document against this schema, so an
    upgrade that changes the contract has to invalidate every cached reading. Naming the
    schema by its content says so exactly, and costs nothing after the first call.
    """
    return hashlib.sha256(_schema_text().encode("utf-8")).hexdigest()


@lru_cache(maxsize=8192)
def is_exempt_name(name: str) -> bool:
    """Whether a file name is structural and outside the frontmatter contract.

    Exact names (``BRAIN.md``, ``_index.md``, ...) are the agent- and index-facing files;
    suffixes cover files another tool owns, such as Excalidraw's ``*.excalidraw.md``
    drawings, whose body is that tool's data rather than a document.

    A pure function of the name and of a schema that cannot change under it, asked once
    per document per validation pass, so the answers are kept.
    """
    contract = load_schema()["frontmatter_contract"]
    if name in contract["exempt_names"]:
        return True
    return name.endswith(tuple(contract.get("exempt_suffixes", ())))


def read_config(root: Path) -> dict[str, Any] | None:
    path = root / ".mos" / "config.yaml"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def find_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".mos" / "config.yaml").is_file():
            return candidate
    return None


def config_text(name: str, *, mode: str | None = None, agency: str | None = None) -> str:
    payload: dict[str, Any] = {
        "schema": "mos.business-repo.v1",
        "schema_version": 1,
        "business_name": name.strip(),
    }
    if mode is not None:
        payload["mode"] = mode
    if agency is not None and agency.strip():
        payload["agency"] = agency.strip()
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def repo_mode(config: dict[str, Any] | None) -> tuple[str, list[dict[str, str]]]:
    """Resolve the repository mode and any read findings.

    Missing ``mode`` implies ``in-house`` with a warning (legacy repo). A present
    but unrecognized value fails closed with an ``invalid-mode`` error and is
    returned verbatim so callers never guess.
    """
    raw = config.get("mode") if isinstance(config, dict) else None
    if raw is None:
        return "in-house", [
            finding(
                "missing-mode",
                'Config has no "mode"; assuming in-house. Add "mode" to .mos/config.yaml.',
                severity="warning",
                path=".mos/config.yaml",
            )
        ]
    if raw not in MODES:
        return str(raw), [
            finding(
                "invalid-mode",
                f"Config mode {raw!r} is not one of in-house, agency, client.",
                path=".mos/config.yaml",
            )
        ]
    return raw, []


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "business"


def month_folder_style(config: dict[str, Any] | None) -> tuple[str, list[dict[str, str]]]:
    """Resolve how month folders under the dated trees are named.

    Missing ``month_folder`` means ``MM-Mon`` (``09-Sep``), the default since 0.5.0.
    ``MM`` (``09``) is the legacy opt-out a brain keeps by saying so. An unrecognised
    value returns an ``invalid-month-folder`` error and is returned verbatim so callers
    never guess.
    """
    raw = config.get("month_folder") if isinstance(config, dict) else None
    if raw is None:
        return "MM-Mon", []
    if raw not in MONTH_FOLDER_STYLES:
        return str(raw), [
            finding(
                "invalid-month-folder",
                f"Config month_folder {raw!r} is not one of MM, MM-Mon.",
                path=".mos/config.yaml",
            )
        ]
    return raw, []


def month_dir(when: datetime.date, config: dict[str, Any] | None) -> str:
    """The month folder name for a date: ``09-Sep`` by default, ``09`` under ``MM``.

    The single formatter every path generator uses, so a brain's month folders are
    always written the way its validator reads them. An invalid style falls back to
    ``MM-Mon``; validation reports the bad value separately.
    """
    style, findings = month_folder_style(config)
    number = f"{when.month:02d}"
    if style == "MM" and not findings:
        return number
    return f"{number}-{MONTH_ABBREVIATIONS[when.month - 1]}"


def is_month_like(name: str) -> bool:
    """Whether a name is shaped like a month folder at all: ``01``-``12``, maybe suffixed.

    Only these children of a year folder are judged as month folders. Anything else a year
    folder holds is not a month folder, so it is neither validated nor renamed as one.
    """
    return _MONTH_NAME.fullmatch(name) is not None


def is_month_dir(name: str, style: str) -> bool:
    """Whether a folder name is a valid month folder in the given style."""
    match = _MONTH_NAME.fullmatch(name)
    if match is None:
        return False
    number, suffix = match.groups()
    if style == "MM-Mon":
        return suffix == MONTH_ABBREVIATIONS[int(number) - 1]
    return suffix is None
