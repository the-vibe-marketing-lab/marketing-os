---
name: mos-migrate
description: Migrate a messy folder into the canonical marketing-os structure. You produce the routing plan (the judgement); `mos migrate` applies it deterministically and safely. Use when files exist but are not in canonical locations, or when adopting an existing folder.
---

# Migrate

Route off-schema files into the canonical structure. The command is model-free: it diagnoses what
is off-schema and applies a routing plan, but it never guesses destinations. You read the
diagnosis, decide where each stray file belongs, write the plan, and apply it.

## Why a skill, not just the command

Deciding that `old-posts/launch.md` belongs at `content/2026/07/2026-07-15-launch/` is judgement —
exactly what the CLI leaves to you. The command owns the safe file moves; you own the mapping.

## How to run this skill (interaction contract)

Migrating moves the operator's real files, so treat this as an interactive flow, not a batch job:

- Never guess where a stray file belongs — that mapping is the operator's call. Show them the
  diagnosis, propose destinations, and confirm the plan with them before applying it.
- Ask one thing at a time and wait; use `AskUserQuestion` when a file could plausibly go to more
  than one place.
- Preview with `--plan` and get explicit approval before the `--yes` apply. Never move files the
  user has not signed off on.

## 1. Initialize, then diagnose

If the folder is not yet a repo, scaffold it first with the onboard skill (`mos onboard`) — or,
when it already holds a brain in an older layout, adopt it with `mos attach "<path>" --plan`
then `--yes`, which rewrites only the config and never moves content. Then diagnose:

```bash
mos migrate "<path>" --plan --json
```

Read `unrouted` (the stray top-level entries) and `plan_schema`. Nothing is written.

## 2. Build the routing plan

Write a `mos.migrate-plan.v1` file mapping each stray entry to a canonical destination. Paths are
relative to the repo root:

```json
{
  "schema": "mos.migrate-plan.v1",
  "mkdirs": ["content/2026/07"],
  "moves": [
    { "source": "old-posts/launch.md", "destination": "content/2026/07/2026-07-15-launch/launch.md" }
  ]
}
```

Follow the canonical naming: dated artifacts as `YYYY/MM/YYYY-MM-DD-slug/` under `content`,
`campaigns`, `outputs`, `business/decisions`, and `knowledge/sources`; reports as `YYYY/QN/YYYY-MM`.

## 3. Preview, then apply

```bash
mos migrate "<path>" --plan-file plan.json --plan --json   # validate + preview, no writes
mos migrate "<path>" --plan-file plan.json --yes --json    # apply the moves
```

The plan is applied as a set: if any move is invalid (missing source, a destination that would
escape the repo, or a destination that already exists) nothing is written and the findings tell
you what to fix. Existing files are never overwritten.

## 4. Confirm

```bash
mos validate . --json
```

Report `moved`, `created_dirs`, and any remaining `unrouted` entries, plus one next action.

## Guardrails

- The command never overwrites and never moves outside the repo — trust the findings, fix the plan.
- Prefer previewing with `--plan --plan-file` before `--yes` on anything you have not routed before.
- Migrate moves files; it does not rewrite their contents. Update internal links separately.

## Document contract

Migrated files land in the canonical structure but keep whatever frontmatter they arrived
with, so a migration routinely leaves contract gaps behind. The repository's `CONTRACT.md`
requires `title`, `type`, `description`, `date`, `status`, plus at least one of `sources`,
`related`, or `produced_by`; deliverables under `content/`, `campaigns/`, `reporting/`, and
`outputs/` must carry `sources:`. After applying a migration, run `mos validate . --json` and
report the contract gaps as the next action — do not leave them silent.
