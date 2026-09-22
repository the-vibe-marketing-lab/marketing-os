---
name: mos-onboard
description: Create a new marketing brain or complete an existing one — scaffold, git, the context interview, and (for agencies) client registration. Use this whenever someone wants to set up, create, initialise, scaffold, onboard, or finish setting up a marketing-os business brain, whether it's a brand-new folder or an existing repo missing its context. The single front door for standing up a brain.
---

# Onboard

Stand up a marketing brain and teach it the business. One command handles both cases:

- **A new, empty folder** — scaffold the canonical structure, initialise git with a first commit,
  then interview for real context.
- **An existing brain missing context or wiring** — complete it in place (git is initialised only
  if it isn't already a repo).

`mos onboard` owns the deterministic mechanics (scaffold, git, skill wiring); you own the
judgement — the interview and the business truth it produces.

## How to run this skill (interaction contract)

This is an interactive, guided flow — not a batch job. Onboarding creates a real repository and
writes the operator's business truth, so a wrong guess costs more than a question. At every step:

- Never invent or assume the business name, mode, agency, destination, or any context value — each
  comes from the user. Gather every input through `AskUserQuestion` so they click rather than
  compose prose; offer sensible options and rely on the custom-answer option for anything
  open-ended. Ask one thing at a time and wait.
- Show the plan and get explicit approval before applying — never run `--yes` until the user has
  seen it and told you to proceed.
- If a step needs something the user hasn't given you, ask them; don't proceed on a guess.

## 1. Detect what is already here

Run `mos status . --json` first, and tell the user what you found:

- **A ready or incomplete marketing-os brain** — continue in place and complete the missing
  context.
- **An empty directory** — you'll create a new brain here; you still need the name, mode, and
  destination (steps 2–3).
- **A folder that already holds a brain the engine does not recognise** — a `.mos/config.yaml`
  written as YAML, or a `BRAIN.md` beside a `business/` tree — do not scaffold over it. Hand it
  to `mos attach "<path>" --plan --json` (preview, then `--yes` after approval); attach rewrites
  only the config and adds only missing scaffold files, never the user's content.
- **A non-empty directory that is neither** — do not adopt or migrate it. Tell the user and ask
  for a new, empty destination instead.

## 2. Ask for the business name and destination

Ask both through `AskUserQuestion`, and wait for the answers:

- **What is the business called?** Offer any name suggested by the surrounding context plus a
  throwaway test name, and let them type their own. Use their exact name — never a placeholder.
- **Where should the brain live?** For a new brain, confirm a new, empty folder; offer a default
  path and one named after the business (the `<slug>-hq` convention). For an existing brain, it's
  the current directory.

## 3. Ask which mode (use AskUserQuestion)

Onboarding requires a mode. Ask with `AskUserQuestion` and wait:

- **in-house** — one brand you own. Knowledge is global to the brand.
- **agency** — you serve clients; this creates the agency HQ with a client registry
  (`business/clients/clients.md`, pointers only). Each client gets its own brain, onboarded
  separately, because the repo is the access boundary.
- **client** — a brain for one agency client. Ask for the agency name (`--agency`), and for the
  path to the agency HQ (`--hq`) so the client is registered there.

If you run onboard without `--mode`, it returns `ok=false` with a `choose-mode` next action —
relay its question and wait; never pick a mode for them.

## 4. Plan, then ask approval before writing

Preview — this writes nothing:

```bash
mos onboard "<path>" --name "<business name>" --mode <in-house|agency|client> --runtime all --plan --json
```

For a client, add `--agency "<agency name>"`, and `--hq "<agency hq path>"` to register the client
in the agency's registry. Explain the plan — the scaffold, plus `git init`, `git add -A`, and a
first commit when the folder isn't already a repo. **Then stop and ask for approval.** Only after
they approve:

```bash
mos onboard "<path>" --name "<business name>" --mode <mode> --runtime all --yes --json
```

## 5. Establish minimum context — one topic at a time

The result carries an `interview` handoff listing the unfilled business files. Gather these inputs
conversationally, asking one at a time and waiting for each answer — never fill them in yourself:

1. What the business is and wants to be known for.
2. Who the primary audience is and what they are trying to change.
3. The primary offer: name, promise, mechanism, price or commercial model, and next step.
4. How the business should sound, including representative examples and language to avoid.
5. The strategy: how the business intends to win, the goals worth measuring, and the roadmap of
   phases ahead. Draw out a lean first pass the operator can sharpen later rather than forcing
   false precision.

For each answer, propose the exact edit and get approval before saving. After approval:

- update `business/brand/brand.md` and `business/brand/voice.md`;
- update `business/audience/primary.md`;
- create `business/offers/<offer-slug>/offer.md` using a lowercase hyphenated slug;
- update `business/strategy/strategy.md` (the approach to win), `business/strategy/goals.md`
  (measurable targets), and `business/strategy/roadmap.md` (the phases ahead);
- update `CONTEXT.md` with the current focus and desired outcome.

Never collect secrets, credentials, raw customer exports, or private account data into tracked
files. Never replace a non-placeholder business file without asking the user first.

## 6. Ship it (optional) and verify

Onboard's first commit is local. If the user wants the brain on GitHub, hand off the exact command
after confirming the account and visibility — never create a remote or push on their behalf:

```bash
gh repo create <owner>/<repo> --private --source . --push
```

Then verify:

```bash
mos validate . --json
mos status . --json
mos doctor . --json
```

Finish with the business outcome, any context gaps, runtime readiness, and one next action — then
ask what they want to do next.

## Document contract

Every file you write under `business/`, `knowledge/`, `content/`, `campaigns/`, `reporting/`,
or `outputs/` opens with the frontmatter block defined in the repository's `CONTRACT.md`:
`title`, `type`, `description`, `date`, `status`, plus at least one of `sources`, `related`,
or `produced_by`. Deliverables must carry `sources:` — an output with no sources is not
finished. Emit the block as you write the file; never leave it for a later pass.
