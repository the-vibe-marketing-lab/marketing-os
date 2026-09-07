import json
from pathlib import Path

from marketing_os.core.setup import setup_repo


def test_setup_plan_is_non_mutating(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    result = setup_repo(target, "Example Business", "all", mode="in-house", apply=False)
    assert result["ok"] is True
    assert result["planned"] is True
    assert result["changes"]
    assert not target.exists()


def test_setup_apply_and_repeat_are_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    first = setup_repo(target, "Example Business", "all", mode="in-house", apply=True)
    before = {
        path.relative_to(target).as_posix(): path.read_bytes()
        for path in target.rglob("*")
        if path.is_file()
    }
    second = setup_repo(target, "Example Business", "all", mode="in-house", apply=True)
    after = {
        path.relative_to(target).as_posix(): path.read_bytes()
        for path in target.rglob("*")
        if path.is_file()
    }
    assert first["ok"] is True
    assert first["changes"]
    assert second["ok"] is True
    assert second["changes"] == []
    assert after == before


def test_setup_never_overwrites_business_truth(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    setup_repo(target, "Example Business", "all", mode="in-house", apply=True)
    voice = target / "business" / "brand" / "voice.md"
    voice.write_text("# Voice\n\nA deliberately specific voice.\n", encoding="utf-8")
    setup_repo(target, "Example Business", "all", mode="in-house", apply=True)
    assert voice.read_text(encoding="utf-8") == "# Voice\n\nA deliberately specific voice.\n"


def test_setup_refuses_nonempty_unidentified_directory(tmp_path: Path) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    (target / "notes.md").write_text("existing", encoding="utf-8")
    result = setup_repo(target, "Example Business", "all", mode="in-house", apply=True)
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "unsupported-directory"
    assert not (target / "BRAIN.md").exists()


def test_setup_without_mode_is_blocked_and_writes_nothing(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    result = setup_repo(target, "Example Business", "all", apply=True)
    assert result["ok"] is False
    assert result["next_action"]["id"] == "choose-mode"
    assert "re-run setup with --mode" in result["next_action"]["reason"]
    assert any(item["code"] == "mode-required" for item in result["findings"])
    assert not target.exists()


def test_setup_agency_scaffolds_client_registry(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    result = setup_repo(target, "Example Agency", "all", mode="agency", apply=True)
    assert result["ok"] is True
    assert result["mode"] == "agency"
    registry = target / "business" / "clients" / "clients.md"
    assert registry.is_file()
    assert "_example-client_" in registry.read_text(encoding="utf-8")
    assert "create business/clients/clients.md" in result["changes"]


def test_setup_in_house_has_no_clients_folder(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    result = setup_repo(target, "Example Business", "all", mode="in-house", apply=True)
    assert result["ok"] is True
    assert not (target / "business" / "clients").exists()
    assert result["suggested_repo_name"] == "example-business-hq"


def test_setup_client_requires_agency(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    result = setup_repo(target, "Client Brand", "all", mode="client", apply=True)
    assert result["ok"] is False
    assert result["next_action"]["id"] == "choose-mode"
    assert any(item["code"] == "agency-required" for item in result["findings"])
    assert not target.exists()


def test_setup_client_records_agency_and_repo_name(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    result = setup_repo(target, "Client Brand", "all", mode="client", agency="Acme Co", apply=True)
    assert result["ok"] is True
    assert result["suggested_repo_name"] == "acme-co-client-brand"
    config = json.loads((target / ".mos" / "config.yaml").read_text(encoding="utf-8"))
    assert config["mode"] == "client"
    assert config["agency"] == "Acme Co"


def test_setup_agency_flag_ignored_outside_client(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    result = setup_repo(
        target, "Example Business", "all", mode="in-house", agency="Acme Co", apply=True
    )
    assert result["ok"] is True
    assert any(item["code"] == "agency-ignored" for item in result["findings"])
    config = json.loads((target / ".mos" / "config.yaml").read_text(encoding="utf-8"))
    assert "agency" not in config


def test_setup_plan_lists_overlay_files(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    result = setup_repo(target, "Example Agency", "all", mode="agency", apply=False)
    assert "create business/clients/clients.md" in result["changes"]
    assert not target.exists()


def test_setup_invalid_mode_is_blocked(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    result = setup_repo(target, "Example Business", "all", mode="franchise", apply=True)
    assert result["ok"] is False
    assert result["next_action"]["id"] == "choose-mode"
    assert any(item["code"] == "invalid-mode" for item in result["findings"])
    assert not target.exists()


def test_setup_suggested_repo_name_falls_back_for_empty_slug(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    # A name that slugifies to nothing must still yield a usable suggestion.
    result = setup_repo(target, "!!!", "all", mode="in-house", apply=False)
    assert result["ok"] is True
    assert result["suggested_repo_name"] == "business-hq"


def test_setup_config_json_is_sorted(tmp_path: Path) -> None:
    target = tmp_path / "brain"
    setup_repo(target, "Client Brand", "all", mode="client", agency="Acme", apply=True)
    raw = (target / ".mos" / "config.yaml").read_text(encoding="utf-8")
    reserialized = json.dumps(json.loads(raw), indent=2, sort_keys=True) + "\n"
    assert raw == reserialized
