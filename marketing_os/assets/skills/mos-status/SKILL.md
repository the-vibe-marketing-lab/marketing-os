---
name: mos-status
description: Give a deterministic marketing-os briefing of what is healthy, what context is missing, and the single next action.
---

# Status

Translate deterministic repository facts into one owner-facing briefing. This skill is read-only.

## How to run this skill (interactive)

Read-only, but a briefing is a conversation opener, not a data dump:

- If it is unclear what the user is trying to decide, ask before reporting.
- Lead with the single most useful next action and ask whether they want to take it (or the route
  that serves it) — don't list everything and stop.

## Inspect

Run:

```bash
mos status . --json
```

If runtime wiring is in question, also run `mos doctor . --json`. If structure is in
question, also run `mos validate . --json`.

Use only fields the commands actually return. Do not fabricate provider readiness, financial
state, revenue, or external activity.

## Report

Lead with business meaning, then the supporting facts:

1. the current state in one sentence;
2. context completeness — whether brand, voice, audience, and offer grounding exist;
3. structural or runtime health, with the specific failing item when unhealthy;
4. open work or gaps worth surfacing, only when relevant;
5. one recommended next action and the skill or CLI route that serves it.

Read available capabilities from the `installed_skills` status field. Never route to a skill
that is not installed. When the repository is unhealthy, name the exact repair route
(`mos validate . --json`, `mos doctor . --json`, or `mos skills sync`) rather than guessing.

If this is not a marketing-os repository, say so plainly and route to `mos-onboard`.

## Document contract

Every file you write under `business/`, `knowledge/`, `content/`, `campaigns/`, `reporting/`,
or `outputs/` opens with the frontmatter block defined in the repository's `CONTRACT.md`:
`title`, `type`, `description`, `date`, `status`, plus at least one of `sources`, `related`,
or `produced_by`. Deliverables must carry `sources:` — an output with no sources is not
finished. Emit the block as you write the file; never leave it for a later pass.

## Navigation coverage

Run `mos index status . --json` for catalogue freshness and the share of documents carrying
frontmatter, a description, and an outgoing link. A stale or absent catalogue means
`mos query` is reading every document on every question; fix it with `mos index build .`.
