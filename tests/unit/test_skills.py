import shutil
from pathlib import Path

from marketing_os.core.setup import setup_repo
from marketing_os.core.skills import (
    apply_sync,
    inspect_runtimes,
    plan_sync,
    project_manifest,
    skills_root,
    tree_hash,
)


def test_both_runtimes_receive_identical_skills(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    for name in ("mos-onboard", "mos-start", "mos-help"):
        expected = tree_hash(skills_root() / name)
        assert tree_hash(root / ".claude/skills" / name) == expected
        assert tree_hash(root / ".agents/skills" / name) == expected
    assert all(item["ready"] for item in inspect_runtimes(root).values())


def test_clone_recovery_regenerates_ignored_runtime_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    clone = tmp_path / "clone"
    setup_repo(source, "Example Business", "all", mode="in-house", apply=True)
    shutil.copytree(
        source,
        clone,
        ignore=shutil.ignore_patterns(".claude", ".agents", "local"),
    )
    actions, findings = plan_sync(clone, "all", manifest_path=project_manifest(clone))
    assert findings == []
    assert len(actions) == 20  # ten skills, two runtimes
    apply_sync(actions, project_manifest(clone))
    assert all(item["ready"] for item in inspect_runtimes(clone).values())


def test_unrecognized_skill_directory_is_not_overwritten(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    conflict = root / ".agents/skills/mos-start"
    conflict.mkdir(parents=True)
    (conflict / "SKILL.md").write_text("custom", encoding="utf-8")
    actions, findings = plan_sync(root, "codex", manifest_path=project_manifest(root))
    assert any(item["code"] == "skill-conflict" for item in findings)
    assert all(item["skill"] != "mos-start" for item in actions)
    assert (conflict / "SKILL.md").read_text(encoding="utf-8") == "custom"
