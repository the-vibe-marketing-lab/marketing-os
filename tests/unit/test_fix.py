from pathlib import Path

from marketing_os.cli.main import run_argv
from marketing_os.core.fix import FIXABLE, fix_repo
from marketing_os.core.setup import setup_repo


def _brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    setup_repo(root, "Fix Co", "all", mode="in-house", apply=True)
    return root


def test_missing_file_plan_names_the_file_and_writes_nothing(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    (root / "CONTRACT.md").unlink()
    result = fix_repo(root, "missing-file", apply=False)
    assert result["schema"] == "mos.fix.v1"
    assert result["ok"] is True and result["planned"] is True
    assert any("CONTRACT.md" in change for change in result["changes"])
    assert result["ran"] == ["setup"]
    assert not (root / "CONTRACT.md").exists()


def test_missing_file_apply_puts_the_file_back(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    (root / "CONTRACT.md").unlink()
    result = fix_repo(root, "missing-file", apply=True)
    assert result["ok"] is True and result["applied"] is True
    assert (root / "CONTRACT.md").is_file()


def test_an_unknown_code_has_no_deterministic_fix(tmp_path: Path) -> None:
    result = fix_repo(_brain(tmp_path), "nope", apply=False)
    assert result["ok"] is False
    assert [item["code"] for item in result["findings"]] == ["no-deterministic-fix"]
    assert result["next_action"]["id"] == "copy-prompt"
    assert result["ran"] == []


def test_unlinked_document_runs_related(tmp_path: Path) -> None:
    result = fix_repo(_brain(tmp_path), "unlinked-document", apply=False)
    assert result["schema"] == "mos.fix.v1" and result["command"] == "fix"
    assert result["ran"] == ["related"]


def test_missing_file_without_a_config_needs_the_name(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    (root / ".mos" / "config.yaml").unlink()
    result = fix_repo(root, "missing-file", apply=False)
    assert result["ok"] is False
    assert [item["code"] for item in result["findings"]] == ["needs-name"]
    assert result["next_action"]["id"] == "onboard"


def test_all_on_a_healthy_brain_only_offers_the_catalogue(tmp_path: Path) -> None:
    result = fix_repo(_brain(tmp_path), None, apply=False, all_codes=True)
    assert result["ok"] is True and result["code"] == "all"
    assert result["ran"] in ([], ["no-catalog"])
    assert all(":" in change for change in result["changes"])


def test_fixable_is_the_table(tmp_path: Path) -> None:
    assert "missing-file" in FIXABLE and "unknown-top-level" not in FIXABLE


def test_cli_plan_returns_the_envelope(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    (root / "CONTRACT.md").unlink()
    result = run_argv(["fix", "missing-file", str(root), "--plan", "--json"])
    assert result["schema"] == "mos.fix.v1" and result["ok"] is True
    assert any("CONTRACT.md" in change for change in result["changes"])
    assert not (root / "CONTRACT.md").exists()


def test_cli_without_a_code_or_all_is_a_clean_error(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    result = run_argv(["fix", str(root), "--plan"])
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "command-error"
    assert "--all" in result["findings"][0]["message"]


def test_cli_all_takes_the_folder_as_its_only_positional(tmp_path: Path) -> None:
    root = _brain(tmp_path)
    result = run_argv(["fix", "--all", str(root), "--plan"])
    assert result["ok"] is True and result["code"] == "all"
    assert result["repo"] == str(root.resolve())
