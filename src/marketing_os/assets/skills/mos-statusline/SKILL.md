---
name: mos-statusline
description: Turn the MarketingOS status bar badge on or off in Claude Code, and customise it. The badge shows which brain you are in (active or inactive, agency or in-house, the business name, the skills count) on top of the status bar you already have. Use when someone says "/mos-statusline", statusline, status bar, status line, show which brain I'm in, the active/inactive badge, turn the badge on or off, activate or deactivate the status bar, change the status line colour, label or position, or hide the skills count. Claude Code only.
---

# Statusline

Switch the MarketingOS badge on or off in Claude Code's status bar, and change how it looks.
The CLI owns every write; you read its output, explain it, and ask before applying.

## How to run this skill (interactive)

Every write goes through a plan the member has seen:

- Run the `--plan` form first and say, in plain words, what will change and where.
- Run `--yes` only after the member says go. Never assume it.
- Use only facts the commands return. Do not describe files, colours, or behaviour you
  have not seen in the output.

## Check

Run:

```bash
mos statusline --options --json
```

`installed` says whether the badge is in the status bar now. `options` are the settings in
effect, `saved` the ones the member changed, `defaults` what `--reset` returns to. Report
both in a sentence: "The badge is on, with the label changed to MOS" or "The badge is off;
the defaults are in place."

## Activate

Preview first:

```bash
mos statusline --install --plan --json
```

Explain the `changes` list: the member's user-scope `~/.claude/settings.json` is backed up
beside itself, the status bar they have now (`previous`) is recorded under
`~/.marketing-os/statusline.json`, and the `statusLine` command becomes `status_command`.
Their existing bar keeps running underneath the badge, because the installed command runs it
after drawing the badge. An empty `changes` list means it is already installed; say so.

After approval:

```bash
mos statusline --install --yes --json
```

Tell the member the badge appears on the next status bar redraw (their next message), and
that it updates as they move between folders; no restart is needed.

## Deactivate

```bash
mos statusline --uninstall --plan --json
```

Explain the changes: the recorded status bar goes back (or `statusLine` is removed when
there was none), the settings file is backed up again, and the record forgets the old bar.
Saved options stay, so switching the badge back on keeps the same look. If `findings`
carries `statusline-changed`, the status bar was edited after the badge went in; the CLI
leaves it alone. Say so plainly, and point at the backup files if they want to compare.

After approval:

```bash
mos statusline --uninstall --yes --json
```

## Customise

Ask what they want to change. Offer the options in plain language, with the defaults:

- `label` — the word at the start (`MARKETINGOS`; 1 to 24 characters)
- `accent` — the colour of the label and brain type (`#c96442`, a hex colour)
- `color` — colour on or off (`true`)
- `divider` — the rule between the badge and the bar underneath (`true`)
- `show_name` — the business name on the active line (`true`)
- `show_skills` — the `SKILLS n/m` count (`true`)
- `show_cwd` — the folder on the inactive line (`true`)
- `position` — the badge above the existing bar (`top`) or below it (`bottom`)

Show them the result before writing anything. `--preview` draws the badge with the saved
options plus the pending pairs and writes nothing:

```bash
mos statusline --preview --set label=MOS --set show_skills=false --json .
```

`line` is the plain badge and `rendered` the coloured one; show `line` and name the colour.
The preview draws the badge alone, so when `position` or `divider` is changing, say in
words where it will sit: above or below their own status bar, with or without the rule.
A bad value fails here with an `invalid-option` or `unknown-option` finding that names the
key. Fix it with the member rather than guessing.

Then plan and apply:

```bash
mos statusline --set label=MOS --set show_skills=false --plan --json
mos statusline --set label=MOS --set show_skills=false --yes --json
```

Options save whether or not the badge is installed (`installed` says which). To go back to
the defaults, `mos statusline --reset --plan --json`, then `--yes` after approval.

## Limits

- Claude Code only. Codex has no status bar; say so rather than trying.
- Only the user-scope `~/.claude/settings.json` is touched, never a brain's project settings.
- Never edit `settings.json` or `statusline.json` by hand when the CLI can do it.
- Never run `--yes` without the member's go-ahead.

## Document contract

Every file you write under `business/`, `knowledge/`, `content/`, `campaigns/`, `reporting/`,
or `outputs/` opens with the frontmatter block defined in the repository's `CONTRACT.md`:
`title`, `type`, `description`, `date`, `status`, plus at least one of `sources`, `related`,
or `produced_by`. Deliverables must carry `sources:` — an output with no sources is not
finished. Emit the block as you write the file; never leave it for a later pass.
