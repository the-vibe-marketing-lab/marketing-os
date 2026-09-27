import datetime
import json
from pathlib import Path

import pytest

from marketing_os.core.ingest import ingest_repo
from marketing_os.core.schema import is_month_dir, month_dir, month_folder_style
from marketing_os.core.setup import setup_repo
from marketing_os.core.think import think_repo
from marketing_os.core.validation import validate_repo

ABBREVIATIONS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _brain(tmp_path: Path, month_folder: str | None) -> Path:
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    config_path = root / ".mos" / "config.yaml"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if month_folder is not None:
        config["month_folder"] = month_folder
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return root


def _dated(root: Path, month: str) -> Path:
    folder = root / "content" / "2026" / month / "2026-09-26-x"
    folder.mkdir(parents=True)
    return folder


def _month_findings(root: Path) -> list[dict[str, str]]:
    return [item for item in validate_repo(root)["findings"] if item["code"] == "invalid-month"]


def test_month_dir_defaults_to_mm_mon() -> None:
    day = datetime.date(2026, 9, 26)
    assert month_dir(day, None) == "09-Sep"
    assert month_dir(day, {}) == "09-Sep"
    assert month_dir(day, {"month_folder": "MM-Mon"}) == "09-Sep"
    assert month_folder_style({}) == ("MM-Mon", [])


def test_month_dir_keeps_the_bare_number_under_an_explicit_mm() -> None:
    assert month_dir(datetime.date(2026, 9, 26), {"month_folder": "MM"}) == "09"
    assert month_folder_style({"month_folder": "MM"}) == ("MM", [])


@pytest.mark.parametrize("config", [None, {"month_folder": "MM-Mon"}])
def test_month_dir_names_every_month_under_mm_mon(config: dict[str, str] | None) -> None:
    names = [month_dir(datetime.date(2026, month, 1), config) for month in range(1, 13)]
    assert names == [f"{index:02d}-{abbr}" for index, abbr in enumerate(ABBREVIATIONS, start=1)]
    assert "09-Sept" not in names


def test_month_dir_falls_back_to_mm_mon_for_an_invalid_style() -> None:
    assert month_dir(datetime.date(2026, 9, 26), {"month_folder": "Month"}) == "09-Sep"


@pytest.mark.parametrize("value", ["Month", "mm-mon", "MM-MON", "", 9])
def test_an_invalid_style_is_a_config_finding(value: object) -> None:
    style, findings = month_folder_style({"month_folder": value})
    assert style == str(value)
    assert [item["code"] for item in findings] == ["invalid-month-folder"]
    assert findings[0]["path"] == ".mos/config.yaml"


@pytest.mark.parametrize(
    ("name", "mm", "mm_mon"),
    [
        ("09", True, False),
        ("09-Sep", False, True),
        ("12-Dec", False, True),
        ("09-Aug", False, False),
        ("09-sep", False, False),
        ("09-Sept", False, False),
        ("9", False, False),
        ("13", False, False),
        ("00-Jan", False, False),
        ("09-", False, False),
    ],
)
def test_is_month_dir(name: str, mm: bool, mm_mon: bool) -> None:
    assert is_month_dir(name, "MM") is mm
    assert is_month_dir(name, "MM-Mon") is mm_mon


@pytest.mark.parametrize("month_folder", [None, "MM-Mon"])
def test_mm_mon_brain_accepts_a_named_month(tmp_path: Path, month_folder: str | None) -> None:
    root = _brain(tmp_path, month_folder)
    _dated(root, "09-Sep")
    assert _month_findings(root) == []
    assert validate_repo(root)["ok"] is True


@pytest.mark.parametrize("month_folder", [None, "MM-Mon"])
@pytest.mark.parametrize("name", ["09-Aug", "09-sep", "09-Sept"])
def test_mm_mon_brain_rejects_other_month_names(
    tmp_path: Path, name: str, month_folder: str | None
) -> None:
    root = _brain(tmp_path, month_folder)
    _dated(root, name)
    flagged = _month_findings(root)
    assert len(flagged) == 1
    assert flagged[0]["message"] == "Expected an MM-Mon directory like 09-Sep."
    assert validate_repo(root)["ok"] is False


@pytest.mark.parametrize("month_folder", [None, "MM-Mon"])
def test_a_bare_month_names_the_fix_command(tmp_path: Path, month_folder: str | None) -> None:
    root = _brain(tmp_path, month_folder)
    _dated(root, "09")
    flagged = _month_findings(root)
    assert len(flagged) == 1
    message = flagged[0]["message"]
    assert message.startswith("Expected an MM-Mon directory like 09-Sep.")
    assert "mos fix invalid-month --plan" in message
    assert validate_repo(root)["ok"] is False


def test_a_folder_not_shaped_like_a_month_is_not_judged_as_one(tmp_path: Path) -> None:
    root = _brain(tmp_path, "MM-Mon")
    _dated(root, "September")
    assert _month_findings(root) == []


def test_explicit_mm_brain_keeps_the_mm_grammar(tmp_path: Path) -> None:
    root = _brain(tmp_path, "MM")
    _dated(root, "09")
    (root / "outputs" / "2026" / "09-Sep").mkdir(parents=True)
    flagged = _month_findings(root)
    assert [Path(item["path"]).name for item in flagged] == ["09-Sep"]
    assert flagged[0]["message"] == "Expected an MM directory."


def test_invalid_style_is_reported_and_months_are_not_judged(tmp_path: Path) -> None:
    root = _brain(tmp_path, "Month")
    _dated(root, "09")
    _dated(root, "10-Oct")
    validation = validate_repo(root)
    codes = [item["code"] for item in validation["findings"]]
    assert validation["ok"] is False
    assert "invalid-month-folder" in codes
    assert "invalid-month" not in codes


@pytest.mark.parametrize(
    ("month_folder", "segment"), [(None, "09-Sep"), ("MM-Mon", "09-Sep"), ("MM", "09")]
)
def test_ingest_writes_the_configured_month_folder(
    tmp_path: Path, month_folder: str | None, segment: str
) -> None:
    root = _brain(tmp_path, month_folder)
    result = ingest_repo(root, "a note", topic=None, slug="x", date="2026-09-26", apply=True)
    assert result["ok"] is True
    assert result["source_dir"] == f"knowledge/sources/2026/{segment}/2026-09-26-x"
    assert (root / result["source_dir"] / "source.md").is_file()
    assert _month_findings(root) == []


@pytest.mark.parametrize("month_folder", [None, "MM-Mon", "MM"])
def test_think_names_the_configured_month_folder(tmp_path: Path, month_folder: str | None) -> None:
    root = _brain(tmp_path, month_folder)
    today = datetime.date.today()
    segment = f"{today.month:02d}"
    if month_folder != "MM":
        segment += f"-{ABBREVIATIONS[today.month - 1]}"
    expected = f"business/decisions/{today.year:04d}/{segment}/{today.isoformat()}-pricing/"
    steps = " ".join(think_repo(root, "pricing")["prompt"]["steps"])
    assert expected in steps


def test_only_month_shaped_folders_of_a_year_are_judged(tmp_path: Path) -> None:
    """Richard's scope rule: files and other folders in a year folder are not months."""
    root = _brain(tmp_path, None)
    year = root / "content" / "2026"
    year.mkdir(parents=True)
    (year / "09-Sep.md").write_text("a file", encoding="utf-8")
    (year / "09").write_text("a file named like a month", encoding="utf-8")
    (year / "notes").mkdir()
    (year / "2026-09").mkdir()
    assert _month_findings(root) == []
    (year / "10").mkdir()
    assert [Path(item["path"]).name for item in _month_findings(root)] == ["10"]


def test_reporting_keeps_its_quarter_grammar(tmp_path: Path) -> None:
    root = _brain(tmp_path, None)
    (root / "reporting" / "2026" / "Q3" / "2026-09").mkdir(parents=True)
    assert validate_repo(root)["ok"] is True
    (root / "reporting" / "2026" / "09-Sep").mkdir()
    codes = [item["code"] for item in validate_repo(root)["findings"]]
    assert "invalid-quarter" in codes and "invalid-month" not in codes
