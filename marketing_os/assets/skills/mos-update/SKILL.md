---
name: mos-update
description: Update the marketing-os engine, then refresh the bundled skills and verify runtime wiring.
---

# Update

Update the installed marketing-os engine and refresh its generated skill copies. The CLI owns
the mechanics; do not ask the user whether they installed from source or pipx, and do not reach
for raw package commands as the first path.

## How to run this skill (interaction contract)

Updating changes the installed engine and regenerates skill copies, so run it interactively —
though "interactive" here means confirming the *actions*, not quizzing the user on install
mechanics (the CLI already owns those):

- Preview every stage with `--plan` and explain what it will change before applying it.
- Get explicit approval before each `--yes`; if a stage reports not-ok, show the finding and
  stop rather than pressing on as if it worked.
- Tell the user when a session restart is needed for new skills to load, so nothing silently
  no-ops.

## Preview

Run:

```bash
mos update --plan --json
```

Explain what the plan reports — the detected install mode and whether an engine change is
pending. If it is already current, say so and stop.

## Apply

After approval:

```bash
mos update --yes --json
```

If the result is not ok, show the first finding and stop. Do not continue as if the update
succeeded.

## Refresh skills

A new engine can ship new or changed skills. Refresh the generated copies, previewing first:

```bash
mos install --plan --json
mos skills sync . --plan --json
```

After approval, apply the ones with pending changes:

```bash
mos install --yes --json
mos skills sync . --yes --json
```

## Verify

Confirm the runtime adapters are healthy:

```bash
mos doctor . --json
```

If skill directories changed, tell the user that Claude Code loads its skills at session start,
so a restart from this repository may be needed before new routes appear.

## Document contract

Every file you write under `business/`, `knowledge/`, `content/`, `campaigns/`, `reporting/`,
or `outputs/` opens with the frontmatter block defined in the repository's `CONTRACT.md`:
`title`, `type`, `description`, `date`, `status`, plus at least one of `sources`, `related`,
or `produced_by`. Deliverables must carry `sources:` — an output with no sources is not
finished. Emit the block as you write the file; never leave it for a later pass.
