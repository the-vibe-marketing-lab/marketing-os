"""Build the skills catalogue the local app's Skills page reads.

Walks every public repository of the-vibe-marketing-lab organisation for SKILL.md files,
reads each one's frontmatter (name, description), and writes them to
``src/marketing_os/ui/static/catalog/skills.json`` grouped by repository. Runs at
development time with the ``gh`` CLI; the app itself never talks to the network.

    python scripts/build_skill_catalog.py
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ORG = "the-vibe-marketing-lab"
OUT = Path(__file__).resolve().parents[1] / "src/marketing_os/ui/static/catalog/skills.json"

# The engine's own repository ships the nine bootstrap skills inside the wheel; every other
# repository is a pack the operator installs beside them.
CATEGORY = {
    "marketing-os": ("Built in", "Ships with MarketingOS. Installed by mos install."),
    "marketing-os-skills": (
        "Knowledge library",
        "The default wiki skills and the index of every pack.",
    ),
    "mos-hormozi-skills": ("Offers", "Avatar, offer and money-model workbooks, the $100M chain."),
    "mos-copywriting-skills": (
        "Copywriting",
        "Research ladder, framework-driven copy, proofread QA.",
    ),
    "mos-smma-skills": ("Social", "LinkedIn and X posts in your voice."),
    "mos-yt-skills": ("YouTube", "Channel transcripts and subtitles, fast."),
    "mos-geo-skills": ("GEO", "Getting cited by AI search."),
}


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def frontmatter(text: str) -> dict[str, str]:
    """The frontmatter's top-level string fields, folded and quoted scalars included."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    fields: dict[str, str] = {}
    if not match:
        return fields
    lines = match.group(1).splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", lines[i])
        i += 1
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if value in (">", "|", ">-", "|-", ">+", "|+"):
            block: list[str] = []
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            value = " ".join(part for part in block if part)
        elif value and value[0] in "\"'" and (len(value) < 2 or value[-1] != value[0]):
            quote = value[0]
            parts = [value[1:]]
            while i < len(lines):
                part = lines[i].strip()
                i += 1
                if part.endswith(quote):
                    parts.append(part[:-1])
                    break
                parts.append(part)
            value = " ".join(parts)
        elif len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key] = " ".join(value.split())
    return fields


def first_sentence(text: str) -> str:
    text = " ".join(text.split())
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    return (m.group(1) if m else text)[:200]


def main() -> int:
    repos = json.loads(
        gh(
            "repo",
            "list",
            ORG,
            "--limit",
            "50",
            "--json",
            "name,description,url,defaultBranchRef,isPrivate",
        )
    )
    skills: list[dict] = []
    repos_out: list[dict] = []
    for repo in sorted(repos, key=lambda r: r["name"]):
        if repo["isPrivate"]:
            continue
        name = repo["name"]
        branch = (repo.get("defaultBranchRef") or {}).get("name") or "main"
        tree = json.loads(gh("api", f"repos/{ORG}/{name}/git/trees/{branch}?recursive=1"))
        paths = [
            item["path"]
            for item in tree.get("tree", [])
            if item["path"].endswith("/SKILL.md") or item["path"] == "SKILL.md"
        ]
        label, blurb = CATEGORY.get(name, (name, repo.get("description") or ""))
        repos_out.append(
            {
                "repo": name,
                "label": label,
                "blurb": blurb,
                "description": repo.get("description") or "",
                "url": repo["url"],
                "branch": branch,
                "count": len(paths),
            }
        )
        for path in sorted(paths):
            raw = gh(
                "api",
                f"repos/{ORG}/{name}/contents/{path}?ref={branch}",
                "-H",
                "Accept: application/vnd.github.raw",
            )
            fields = frontmatter(raw)
            folder = path.rsplit("/", 1)[0] if "/" in path else ""
            skill_name = fields.get("name") or folder.rsplit("/", 1)[-1]
            description = fields.get("description") or ""
            skills.append(
                {
                    "name": skill_name,
                    "command": "/" + skill_name,
                    "repo": name,
                    "path": folder,
                    "url": f"{repo['url']}/tree/{branch}/{folder}" if folder else repo["url"],
                    "summary": first_sentence(description),
                    "description": " ".join(description.split()),
                    "bundled": name == "marketing-os",
                }
            )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "schema": "mos.skill-catalog.v1",
                "generated": datetime.now(UTC).strftime("%Y-%m-%d"),
                "org": f"https://github.com/orgs/{ORG}/repositories",
                "repos": repos_out,
                "skills": skills,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{len(skills)} skills across {len(repos_out)} repositories -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
