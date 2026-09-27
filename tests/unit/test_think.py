import datetime
from pathlib import Path

from marketing_os.core.schema import MONTH_ABBREVIATIONS, config_text
from marketing_os.core.think import think_repo


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_repo(root: Path) -> None:
    _write(root / ".mos" / "config.yaml", config_text("Example Business"))
    _write(root / "BRAIN.md", "# Brain\n\nOperating context for the business.\n")
    _write(
        root / "business" / "strategy" / "strategy.md",
        "# Strategy\n\nExpand into the pricing-led segment.\n",
    )
    _write(
        root / "business" / "strategy" / "goals.md",
        "# Goals\n\nGrow pricing experiments this quarter.\n",
    )
    _write(
        root / "business" / "strategy" / "pricing.md",
        "# Pricing\n\nPricing strategy and pricing tiers and pricing model.\n",
    )


def test_think_on_non_repo_reports_not_a_mos_repo(tmp_path: Path) -> None:
    result = think_repo(tmp_path, "how should we price")
    assert result["ok"] is False
    assert result["schema"] == "mos.think.v1"
    assert any(item["code"] == "not-a-mos-repo" for item in result["findings"])
    assert result["prompt"] == {}


def test_think_emits_grounded_prompt(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    _make_repo(root)
    result = think_repo(root, "pricing strategy")

    assert result["ok"] is True
    assert result["topic"] == "pricing strategy"
    assert result["next_action"]["id"] == "run-think"

    prompt = result["prompt"]
    assert set(prompt) == {"objective", "context_paths", "steps", "output_contract"}
    assert "pricing strategy" in prompt["objective"]
    assert prompt["output_contract"] == ["decision", "why", "alternatives rejected", "revisit-when"]

    context = prompt["context_paths"]
    # Always-present strategy anchors come first.
    assert context[0] == "BRAIN.md"
    assert "business/strategy/strategy.md" in context
    assert "business/strategy/goals.md" in context
    # The topic-relevant doc is added via the reused scorer, without duplication.
    assert "business/strategy/pricing.md" in context
    assert len(context) == len(set(context))


def test_think_steps_reference_todays_decision_file(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    _make_repo(root)
    result = think_repo(root, "Pricing Strategy")
    today = datetime.date.today()
    month = f"{today.month:02d}-{MONTH_ABBREVIATIONS[today.month - 1]}"
    expected = (
        f"business/decisions/{today.year:04d}/{month}/"
        f"{today.isoformat()}-pricing-strategy/decision.md"
    )
    steps_text = " ".join(result["prompt"]["steps"])
    assert expected in steps_text
    assert "knowledge/wiki/_log.md" in steps_text


def test_think_finds_repo_from_subdirectory(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    _make_repo(root)
    nested = root / "business" / "strategy"
    result = think_repo(nested, "pricing")
    assert result["ok"] is True
    assert result["repo"] == str(root.resolve())
