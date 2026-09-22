import json
from pathlib import Path

from marketing_os.core.schema import assets_root, load_schema
from marketing_os.core.setup import setup_repo
from marketing_os.core.skills import bundled_skills


def test_package_has_canonical_skill_catalog() -> None:
    assert bundled_skills() == (
        "mos-start",
        "mos-help",
        "mos-status",
        "mos-end",
        "mos-think",
        "mos-bet",
        "mos-update",
        "mos-onboard",
        "mos-migrate",
        "mos-statusline",
    )
    assert not Path(".claude/skills").exists()
    assert not Path(".agents/skills").exists()


def test_schema_is_machine_readable_and_versioned() -> None:
    schema = load_schema()
    assert schema["schema"] == "mos.business-repo.v1"
    assert schema["version"] == 1
    assert "business/brand/voice.md" in schema["required_files"]
    json.loads((assets_root() / "schema.json").read_text(encoding="utf-8"))


def test_skills_document_only_shipped_commands() -> None:
    skills = assets_root() / "skills"
    text = "\n".join(path.read_text(encoding="utf-8") for path in skills.rglob("SKILL.md"))
    for command in ("mos onboard", "mos status", "mos validate", "mos doctor", "mos skills sync"):
        assert command in text


def test_setup_matches_golden_tree(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Golden Business", "all", mode="in-house", apply=True)
    actual = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
    expected = sorted(
        line
        for line in (Path(__file__).parents[1] / "fixtures" / "golden-tree.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    )
    assert actual == expected


def test_agency_overlay_ships_and_scaffolds(tmp_path: Path) -> None:
    overlay = assets_root() / "mode-overlays" / "agency" / "business" / "clients" / "clients.md"
    assert overlay.is_file()
    root = tmp_path / "brain"
    setup_repo(root, "Golden Agency", "all", mode="agency", apply=True)
    registry = root / "business" / "clients" / "clients.md"
    assert registry.is_file()
    text = registry.read_text(encoding="utf-8")
    assert "# Client Registry" in text
    assert "| Client | Repo | Status | Access |" in text


def test_schema_publishes_the_frontmatter_contract() -> None:
    contract = load_schema()["frontmatter_contract"]
    assert contract["required_keys"] == ["title", "type", "description", "date", "status"]
    assert set(contract["connective_keys"]) == {"sources", "related", "produced_by"}
    assert set(contract["sources_required_in"]) == {
        "content",
        "campaigns",
        "reporting",
        "outputs",
    }
    assert set(contract["folder_types"].values()) <= set(contract["types"])
    assert contract["exempt_suffixes"] == [".excalidraw.md"]
    assert "CONTRACT.md" in load_schema()["required_files"]


def test_scaffolded_documents_satisfy_their_own_contract(tmp_path: Path) -> None:
    """Documents are born compliant, so no brain ever needs a retrospective backfill."""
    from marketing_os.core.catalog import build_catalog
    from marketing_os.core.graphlint import contract_findings

    root = tmp_path / "brain"
    setup_repo(root, "Golden Business", "all", mode="agency", apply=True)
    docs = build_catalog(root)
    contract = load_schema()["frontmatter_contract"]
    exempt = set(contract["exempt_names"])
    checked = 0
    for relative, doc in docs.items():
        if Path(relative).name in exempt:
            continue
        checked += 1
        assert doc["has_frontmatter"], relative
        assert doc["missing_keys"] == [], relative
        assert doc["connective_keys"], relative
    assert checked >= 8
    assert contract_findings(root) == []


def test_scaffolded_dates_are_rendered_not_placeholders(tmp_path: Path) -> None:
    import datetime

    root = tmp_path / "brain"
    setup_repo(root, "Golden Business", "all", mode="in-house", apply=True)
    text = (root / "business" / "brand" / "brand.md").read_text(encoding="utf-8")
    assert "{{TODAY}}" not in text
    assert datetime.date.today().isoformat() in text
    assert "{{BUSINESS_NAME}}" not in text


def test_template_ships_a_line_ending_contract() -> None:
    attributes = assets_root() / "business-template" / ".gitattributes"
    assert attributes.is_file()
    assert "text=auto" in attributes.read_text(encoding="utf-8")


def test_skills_document_the_navigation_commands() -> None:
    skills = assets_root() / "skills"
    text = "\n".join(path.read_text(encoding="utf-8") for path in skills.rglob("SKILL.md"))
    for command in ("mos index build", "mos index sync", "mos related"):
        assert command in text


def test_every_skill_states_the_frontmatter_contract() -> None:
    skills = assets_root() / "skills"
    for path in sorted(skills.rglob("SKILL.md")):
        assert "CONTRACT.md" in path.read_text(encoding="utf-8"), path.parent.name


def _obsidian_root() -> Path:
    return assets_root() / "business-template" / ".obsidian"


def test_template_ships_an_obsidian_vault_config() -> None:
    root = _obsidian_root()
    for name in ("app.json", "appearance.json", "core-plugins.json", "community-plugins.json"):
        json.loads((root / name).read_text(encoding="utf-8"))
    enabled = json.loads((root / "community-plugins.json").read_text(encoding="utf-8"))
    assert enabled == [
        "obsidian-icon-folder",
        "git-file-explorer-colors",
        "hide-empty-folders",
    ]
    for plugin_id in enabled:
        folder = root / "plugins" / plugin_id
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["id"] == plugin_id
        assert (folder / "main.js").is_file(), plugin_id
        assert (folder / "LICENSE").is_file(), plugin_id
    appearance = json.loads((root / "appearance.json").read_text(encoding="utf-8"))
    for snippet in appearance["enabledCssSnippets"]:
        assert (root / "snippets" / f"{snippet}.css").is_file(), snippet
    assert appearance["theme"] == "obsidian"
    theme = root / "themes" / appearance["cssTheme"]
    manifest = json.loads((theme / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == appearance["cssTheme"] == "MarketingOS"
    assert (theme / "theme.css").is_file()


def test_obsidian_icon_map_names_real_template_folders() -> None:
    """Folder emojis come from the Iconize map, never from renaming schema folders."""
    template = assets_root() / "business-template"
    overlay = assets_root() / "mode-overlays" / "agency"
    data = json.loads(
        (_obsidian_root() / "plugins" / "obsidian-icon-folder" / "data.json").read_text(
            encoding="utf-8"
        )
    )
    mapped = {key for key in data if key != "settings"}
    for top in load_schema()["allowed_top_level"]:
        assert top in mapped, top
    for path in mapped:
        assert (template / path).exists() or (overlay / path).exists(), path
    visible = {c.name for c in template.iterdir() if c.is_dir() and not c.name.startswith(".")}
    assert set(load_schema()["allowed_top_level"]) == visible


def test_template_gitignore_keeps_vault_config_but_drops_ui_state() -> None:
    text = (assets_root() / "business-template" / ".gitignore").read_text(encoding="utf-8")
    assert ".obsidian/workspace.json" in text
    assert ".obsidian/cache" in text
    assert ".trash/" in text
    rules = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert ".obsidian/" not in rules
    assert not any("plugins" in rule for rule in rules)
