---
name: mos-help
description: Explain marketing-os setup, architecture, routing, status, validation, and Claude Code or Codex wiring.
---

# Help

Answer in plain business language using current facts rather than remembered command syntax.

## How to run this skill (interactive)

Help is a dialogue, not a lecture:

- If the question is broad or ambiguous, ask what the user is trying to do before explaining — a
  targeted answer beats a tour.
- After answering, offer the natural next step and ask whether they want to take it.

## Sources of truth

- Use `mos --help` and `mos <command> --help` for command syntax.
- For repository-specific questions, run `mos status . --json`.
- For health or discovery questions, run `mos doctor . --json`.
- Use `BRAIN.md` for routing and safety rules.

## System model

- `business/` is the sole source of business truth.
- `knowledge/` holds immutable sources and maintainable synthesized knowledge.
- `content/`, `campaigns/`, `reporting/`, and `outputs/` hold execution work.
- `mos` owns deterministic setup, facts, validation, and runtime wiring.
- The agent owns interviewing, judgment, synthesis, and writing.
- Claude Code and Codex consume generated copies of the same packaged skills.

## Common routes

- New or incomplete repository: `mos-onboard`.
- An existing folder that already holds a brain (legacy YAML config, or `BRAIN.md` beside
  `business/`): `mos attach <path> --plan`, then `--yes` — adopts it without rewriting content.
- Daily orientation: `mos-start`.
- Structural errors: `mos validate . --json`.
- Runtime discovery errors: preview and then apply `mos skills sync`.

Explain the outcome first. Include technical commands only when they help the user act or verify.
Do not claim that an uninstalled skill or unsupported command exists.

## Document contract

Every file you write under `business/`, `knowledge/`, `content/`, `campaigns/`, `reporting/`,
or `outputs/` opens with the frontmatter block defined in the repository's `CONTRACT.md`:
`title`, `type`, `description`, `date`, `status`, plus at least one of `sources`, `related`,
or `produced_by`. Deliverables must carry `sources:` — an output with no sources is not
finished. Emit the block as you write the file; never leave it for a later pass.
