from __future__ import annotations

import json
from pathlib import Path

from marketing_os.core.rename import rename_repo
from marketing_os.core.setup import setup_repo


def _brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="agency", apply=True)
    return root


def _config(root: Path) -> dict:
    return json.loads((root / ".mos" / "config.yaml").read_text(encoding="utf-8"))


def test_a_plan_names_the_change_and_writes_nothing(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    report = rename_repo(root, "Example Co", apply=False)
    assert report["ok"] is True and report["planned"] is True and report["applied"] is False
    assert report["changes"] == ["update .mos/config.yaml"]
    assert report["previous_name"] == "Example Business" and report["name"] == "Example Co"
    assert _config(root)["business_name"] == "Example Business"


def test_applying_renames_and_keeps_the_rest_of_the_settings(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    report = rename_repo(root, "  Example Co  ", apply=True)
    assert report["applied"] is True
    config = _config(root)
    assert config["business_name"] == "Example Co"
    assert config["mode"] == "agency"
    assert config["schema"] == "mos.business-repo.v1"


def test_the_same_name_is_nothing_to_do(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    report = rename_repo(root, "Example Business", apply=True)
    assert report["ok"] is True and report["changes"] == [] and report["applied"] is False
    assert report["next_action"]["id"] == "none"


def test_an_empty_name_is_refused(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    report = rename_repo(root, "   ", apply=True)
    assert report["ok"] is False
    assert [item["code"] for item in report["findings"]] == ["missing-name"]
    assert _config(root)["business_name"] == "Example Business"


def test_a_folder_that_is_not_a_brain_is_refused(tmp_path: Path) -> None:
    report = rename_repo(tmp_path, "Anything", apply=True)
    assert report["ok"] is False
    assert [item["code"] for item in report["findings"]] == ["not-marketing-os"]
