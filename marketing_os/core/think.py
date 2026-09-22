from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

from marketing_os.core.query import score_corpus, tokenize
from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import find_root, slugify

_ALWAYS = ("BRAIN.md", "business/strategy/strategy.md", "business/strategy/goals.md")


def think_repo(root: Path, topic: str) -> dict[str, Any]:
    """Emit a grounded thinking handoff for a topic against a valid repository."""
    start = root.expanduser().resolve()
    found = find_root(start)
    if found is None:
        return envelope(
            "think",
            start,
            ok=False,
            findings=[finding("not-a-mos-repo", "This is not a marketing-os business repository.")],
            action=next_action(
                "run-setup", "Create a new business brain with the setup skill first."
            ),
            topic=topic,
            prompt={},
        )

    root = found
    scored = score_corpus(root, tokenize(topic))

    context_paths: list[str] = []
    for name in _ALWAYS:
        if (root / name).is_file():
            context_paths.append(name)
    for path, _score, _matched in scored[:5]:
        relative = path.relative_to(root).as_posix()
        if relative not in context_paths:
            context_paths.append(relative)

    today = datetime.date.today()
    iso = today.isoformat()
    decision_path = (
        f"business/decisions/{today.year:04d}/{today.month:02d}/{iso}-{slugify(topic)}/decision.md"
    )
    prompt = {
        "objective": f"Reason to a grounded recommendation on: {topic}.",
        "context_paths": context_paths,
        "steps": [
            "Read every context path listed above.",
            "Reason through the realistic options and their tradeoffs.",
            "Make a single clear recommendation.",
            f"Write the decision to {decision_path} with its rationale.",
            "Append a line naming the decision file to knowledge/wiki/_log.md.",
        ],
        "output_contract": [
            "decision",
            "why",
            "alternatives rejected",
            "revisit-when",
        ],
    }
    return envelope(
        "think",
        root,
        ok=True,
        action=next_action("run-think", "Execute the grounded thinking prompt now."),
        topic=topic,
        prompt=prompt,
    )
