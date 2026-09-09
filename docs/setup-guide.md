# Setup Guide

A first-run walkthrough, from installing the CLI to a healthy business brain. Every
command shown here exists in the `mos` CLI; run `mos --help` or `mos <command> --help`
at any point to confirm syntax.

There are two routes through the middle of this guide. Sections 1 and 2 are common to
both. From there, either work through sections 4 to 7 in a terminal, or start the local
app (section 3) and do the same steps in a browser. The app drives the same CLI through
the same parser, so a brain built one way is identical to a brain built the other.

## 1. Install the CLI

`marketing-os` is on PyPI. pipx puts `mos` on your path in an environment of its own:

```bash
pipx install marketing-os
```

If you would rather have your coding agent run this step and the next, the
[README](../README.md#install-with-your-agent) has a block to paste into it.

If you are working on the engine itself, install from a source checkout instead. It puts the
same `mos` on your path from the working tree, so edits show up without reinstalling, and
every command in this guide behaves identically either way:

```bash
git clone https://github.com/the-vibe-marketing-lab/marketing-os
cd marketing-os
python -m pip install -e .
```

Check it is available:

```bash
mos --version
```

You should see `mos 0.4.0`. `mos open` and `mos rename` are the newest two commands; if
`mos open --help` answers `invalid choice: 'open'` you are on an older install, and section 3
will not work until you upgrade (`pipx upgrade marketing-os`, or pull the checkout).

## 2. Install the bootstrap skills globally

`mos install` copies the nine bundled skills — `mos-onboard`, `mos-start`, `mos-status`,
`mos-help`, `mos-think`, `mos-bet`, `mos-end`, `mos-update`, and `mos-migrate` — into your
home directory so every runtime can find them. It targets `~/.claude/skills` for Claude Code
and `~/.agents/skills` for Codex, and records what it installed in
`~/.marketing-os/runtime-manifest.json`. Section 9 says what each skill is for.

(`mos --help` still lists install as "Install the three bootstrap skills globally". That
count is stale, and it is the parent listing that carries it — `mos install --help` has no
description line at all. The packaged `manifest.json` is what the command actually reads,
and it lists nine.)

Like every mutating command, `install` requires exactly one of `--plan` or `--yes`.
Preview first:

```bash
mos install --runtime all --plan
```

The plan lists the skill directories it would create, and writes nothing. Read it,
then apply:

```bash
mos install --runtime all --yes
```

Use `--runtime claude` or `--runtime codex` to install for a single runtime; `all`
installs both. After applying, the manifest records a content hash for each installed
skill so later runs know when a copy is stale and can be refreshed instead of duplicated.

On macOS and Linux a first successful apply also opens the local app in your browser, once.
The run is recorded at `~/.marketing-os/ui-opened` — written before the server starts, so a
crash cannot turn it into a browser window on every install — and never repeats. That
ordering is why Windows gets no browser window: this path needs a detached server, and with
no `os.fork` nothing starts, the attempt reports `ui-needs-foreground`, and the marker is
already spent. Start the app yourself with `mos ui` (section 3). Skip the attempt entirely
with `--no-ui`:

```bash
mos install --runtime all --yes --no-ui
```

Note that `install` always writes into your home directory rather than into a brain,
whatever folder you run it from. It takes no path argument for that reason.

## 3. The local app, if you would rather not use a terminal

`mos ui` puts the same CLI in a browser:

```bash
mos ui
```

It binds `127.0.0.1` on the first free port between 4321 and 4370, starts a detached
server, prints the URL, and opens your browser. Loopback only: the bind address is a
constant rather than a flag, so there is no LAN or remote mode and nothing else on your
network can reach it. On a platform with no `os.fork` there is nothing to detach to, so the
server runs in the window you started it in and says so with a `ui-foreground` warning
rather than pretending otherwise.

Managing it:

- `mos ui status` — whether it is running, with the pid, port, and URL.
- `mos ui stop` — sends SIGTERM to the recorded process and waits up to ten seconds.
- `mos ui --port 4400` — bind one port instead of walking the range.
- `mos ui --no-open` — start the server without opening a browser.
- `mos ui ./my-business` — open a particular folder rather than the current one.

The app opens on a five-step wizard — Folder, Who it's for, Name, Preview, Create — which
is sections 4 to 6 of this guide as a click-through. You can pick the folder from an
in-page browser, from a suggested-place chip, or through your operating system's own folder
window. Step 4 shows you the real `mos onboard --plan` envelope before anything is written,
and step 5 runs onboard, then validate, then status. After that you get a dashboard (a
health verdict, what context is still missing, runtime wiring) and a Commands tab covering
21 of the CLI's 22 command paths, each rendered as the exact `mos …` line the server will
run. A command that writes stays disabled until its `--plan` has run with the same
arguments and come back ok.

`mos ui` has no `--plan`/`--yes` gate, because starting a server changes nothing in a brain.
The command writes `ui.json` and `ui.log` under `~/.marketing-os`, never inside a brain; the
`brains.json` registry is written by the running server as the app opens brains, and the
first-open marker belongs to `mos install` (section 2). It is also the one command missing
from the Commands tab: the app cannot start or stop itself.

If you take this route, rejoin the guide at section 8 once the dashboard reports a healthy
brain. [troubleshooting.md](troubleshooting.md) has a section for the app's own failures.

## 4. Create a folder for your business

Onboard scaffolds into an empty folder. It also accepts a folder it already recognises as a
marketing-os brain, because completing one is the same job. Every other non-empty folder is
refused — anything holding anything at all, a dotfile included — with an
`unsupported-directory` finding and a `choose-empty-destination` next action.

That is why this guide runs onboard from the parent folder rather than from inside the new
one:

```bash
mkdir my-business
```

Leave it empty, drive onboard at it by path (section 5), and open the folder in your agent
afterwards. The order matters, because an agent that writes anything at all into the folder
first closes the door — Claude Code records an approved permission in
`.claude/settings.local.json`, for instance, and a folder holding only that file is already
non-empty as far as onboard is concerned.

Two other doors, for folders that are not empty:

- **A folder that already holds a brain** — a `.mos/config.yaml` written as YAML that the
  JSON reader rejects, or a `BRAIN.md` beside a `business/` tree. That is `mos attach`; see
  the end of section 5.
- **A folder full of unrelated work** — neither door opens. Onboard refuses it as non-empty,
  and attach refuses it as `not-a-brain` and sends you back to onboard. Scaffold a new empty
  folder, then route the old material in with `mos migrate`.

## 5. Run onboard

Inside an agent, run the onboard skill:

- Claude Code: `/mos-onboard`
- Codex: `$mos-onboard`

Both load the same workflow. Before it scaffolds anything, the skill settles the one
question that shapes the whole brain: **which mode?**

- `in-house` — one brand you run yourself. Knowledge is global to the brand.
- `agency` — you serve clients. This HQ repo holds a client *registry* (pointers only);
  each client later gets its own repo via `mos onboard`.
- `client` — the brain for a single agency client. Pass `--agency "<agency name>"` so the
  repo records who runs it.

`--mode` is required, though argparse does not enforce it. Leave it off and onboard writes
nothing and returns a `choose-mode` next action whose reason is the exact question to put
to the user.

The skill checks the current state with `mos status`, asks for the business name and the
destination, then previews the scaffold before writing anything:

```bash
mos onboard ./my-business --name "My Business" --mode in-house --runtime all --plan --json
```

The plan lists the files and skill copies it would create. After you approve, the skill
applies it:

```bash
mos onboard ./my-business --name "My Business" --mode in-house --runtime all --yes --json
```

Those two commands work on their own if you have no agent open. You then do section 6's
interview yourself.

This creates the canonical brain: `BRAIN.md`, `CONTEXT.md`, the `business/`, `knowledge/`,
`content/`, `campaigns/`, `reporting/`, and `outputs/` trees, and the generated runtime
skill copies under `.claude/skills/` and `.agents/skills/`. See
[business-repo.md](business-repo.md) for the full structure.

It also runs `git init`, `git add -A`, and a first commit. The commit is authored as
`marketing-os <onboard@marketing-os.local>` rather than as you, so amend it before pushing
if authorship matters. If the folder is already a git repository the whole step is skipped.
If git is not on PATH, onboard records a warning-severity `git-unavailable` finding and
carries on; a git step that fails surfaces as `git-init-failed`, also a warning. Neither
blocks the scaffold.

Onboard is driven from the parent folder, but the rest of this guide works from inside the
brain. Step into it now, so that every `.` from section 6 onward means the folder you just
created:

```bash
cd my-business
```

### Adopting a folder that already holds a brain

`mos attach` is the other door — for a folder that grew a brain before this engine existed.
Preview, then apply:

```bash
mos attach ./old-brain --plan
mos attach ./old-brain --yes
```

Attach makes three kinds of write. It rewrites `.mos/config.yaml` in the canonical JSON form,
keeping the previous text as `.mos/config.legacy.yaml` when the two differ, because that file
is how every other command recognises a brain. It adds the top-level contract documents and
required directories you do not already have. And it generates the runtime skill copies under
`.claude/skills/` and `.agents/skills/` — eighteen directories on a `--runtime all` run, which
is why the `--runtime` default below matters. It never creates or overwrites a `business/` or
`knowledge/` document, and it does not touch git. `--name` and `--mode`
default from the existing config, then from the folder name and `in-house`; `--runtime`
defaults to `all`. Anything off-schema at the top level comes back as an `off-schema-entry`
warning pointing at `mos migrate --plan`.

That restraint has a consequence to plan for. Every required document you do not already
have is reported as a `missing-content-file` warning and left unwritten, so an attached
brain usually lands in `repo_state: invalid` with a `missing-file` error for each. Run
onboard over the same folder afterwards to fill exactly those:

```bash
mos onboard ./old-brain --name "Old Brain" --mode in-house --runtime all --plan
mos onboard ./old-brain --name "Old Brain" --mode in-house --runtime all --yes
```

Onboard no longer refuses the folder — it is a recognised brain now — and the scaffold
skips every destination that already exists, so what you wrote stays exactly as it was.

## 6. Establish minimum context

Scaffolding creates empty rooms. Six fields furnish them: brand, voice, audience, offer,
strategy, and proof. Only the first four gate readiness — `mos status` reports
`needs-context` until brand, voice, audience, and offer are answered. Strategy
(`business/strategy/strategy.md`) and proof are interviewed and settable the same way, but
a brain reaches `ready` without them.

Run inside an agent, the onboard skill interviews you across all six, proposes the exact
edits, and saves them only after you approve. Nothing is invented and no non-placeholder
file is overwritten without discussion.

### Filling context without an agent

The same job from the terminal:

```bash
mos context show .
mos context set . --field brand --text "..." --plan
mos context set . --field brand --text "..." --yes
```

`context show` turns every field into a question with its hint, the file behind it, and
the answer already on file. `context set --plan` prints a real unified diff of the change;
`--yes` writes it through an atomic write, so a failed write leaves the original byte for
byte. The same text test judges both, so a preview never over- or under-reads the file it is
about to write.

It can still disagree with `mos status`, and knowing why saves confusion. `context set`
reports `field_complete` for the canonical file it is writing; `mos status` reports a field
complete when discovery finds the answer anywhere (see "An answer already on disk counts"
below). So on a brain whose brand is answered at `business/positioning/brand.md`, a short
`context set --field brand --plan` returns `field_complete: false` and an `answer-too-short`
warning saying status will still report the field missing — while status reports it complete
and the same envelope's own `missing` list does not contain it. Trust `mos status` for whether
a field is answered; trust `field_complete` for whether the text you just supplied is
substantial.

`--field offer` is the one that needs care, and it has three cases. With no `--slug`: a brain
with no canonical offer gets `business/offers/core-offer/offer.md`; a brain with exactly one
gets that offer's own file, whatever it is called; a brain with more than one is refused with
a `choose-offer` action until you name which with `--slug`.

`--text -` reads the answer from stdin. That works in a terminal only — the seam the local
app uses rejects the sentinel rather than blocking a request thread on a console that is
not there.

To be interviewed rather than write cold:

```bash
mos assist status
mos assist ask . --field brand
```

`assist status` resolves and version-probes each agent runtime on this machine and reports
which can actually answer. `assist ask` runs one stateless turn against one of them and
writes nothing — the draft comes back as data for you to read and pass to `context set`.
This is the engine's one documented exception to being model-free.

### An answer already on disk counts

Status does not only look at the canonical file. When that file is missing or still
boilerplate, it searches `business/` and `reference/` for a substantive document whose own
name is one of the words the field is known by. The name is the gate and the folder only
corroborates it: candidates are scored on naming, placement and frontmatter and must clear a
confidence floor, so a substantive `business/positioning/brand.md` closes brand without
`business/brand/brand.md` ever being touched, while a lone `business/pricing.md` — the right
word, but only on the file name and nothing agreeing with it — scores too low to close offer,
and a `README.md` or a generated `_index.md` in a field's own folder never answers at all.
The field then reports `"source": "discovered"` and a `discovered_path`.

That is deliberate: a brain that already answered these questions at length, under its own
folder names, should not be asked to answer them again. It does mean a field can read
complete while the file that status names is still a stub. The needs-context section of
[troubleshooting.md](troubleshooting.md) covers what to do about that.

## 7. Verify

Confirm the brain is structurally sound and both runtimes are wired:

```bash
mos status . --json
mos doctor . --json
```

Both read `.mos/config.yaml` at exactly the path you give them and do not search upward, so
run them from the repository root — which is where the `cd` at the end of section 5 left you —
or pass the root explicitly (`mos status ./my-business --json` from the parent). Run from a
subfolder, they report the folder as not a marketing-os repository.

`mos status` reports a `repo_state`. You are aiming for `ready`. Along the way you may see:

- `absent` - the folder is not a marketing-os repository; either there is no brain here yet,
  or you are pointing at the wrong path.
- `invalid` - a structural error to repair before doing business work.
- `needs-runtime-sync` - the project-local skill copies under `.claude/skills/` and
  `.agents/skills/` are missing or stale; run `mos skills sync . --runtime all --plan`, then
  `--yes`.
- `needs-context` - structure and wiring are fine but a required context area is still empty.
- `ready` - structure, runtime wiring, and required context are all complete.

`mos doctor` adds an explicit verdict over two things: structure, and runtime wiring for
both Claude Code and Codex. It reports context readiness beside them under
`checks.context_ready`, but that check does not feed the verdict — doctor returns ok and
"The repository is healthy" on a brain with no context filled in at all. Use `mos status`'s
`repo_state` as the context gate.

When status reports `ready`, run the start skill (`/mos-start` or `$mos-start`) to begin
working from `CONTEXT.md`.

If anything looks off, [troubleshooting.md](troubleshooting.md) maps each state to a remedy.

## 8. Open it in Obsidian

Every brain is born an Obsidian vault. In Obsidian choose **File → Open vault → Open folder as
vault** and pick the brain folder. Nothing to configure: the scaffold ships a `.obsidian/`
with three plugins already installed and enabled — two from the community, one that ships
with marketing-os itself:

- **Iconize** (`obsidian-icon-folder`) - community. The emoji in front of every folder
  (💼 business, 📚 knowledge, 📣 campaigns, 🎬 content, 📦 outputs, 📊 reporting, 🗄️ archive).
  The icons live in the plugin's `data.json`, so the folder names on disk stay exactly what
  the schema and the CLI expect.
- **Git File Explorer Colors** (`git-file-explorer-colors`) - community. Changed and new
  files stand out in the file explorer.
- **Hide Empty Folders** (`hide-empty-folders`) - ships with marketing-os. A folder that
  holds only `.gitkeep` stays out of the way until the first real file lands in it. It is not
  in Obsidian's community browser, so it updates with the engine rather than with Obsidian.

Agent-facing files (`CLAUDE.md`, `AGENTS.md`, `CONTEXT.md`, `CONTRACT.md`, `README.md`,
anything starting with `_`) are handled by two separate mechanisms. The `hide-machinery`
snippet is CSS, and hides their rows in the file explorer; the Hide Empty Folders plugin
mirrors the same rules. Search exclusion is `userIgnoreFilters` in `.obsidian/app.json`.
Disabling the snippet therefore changes the explorer but not what search returns. New notes
default to `knowledge/sources/`. The theme is left on Obsidian's default - pick your own
under Settings → Appearance. The vault config and plugins are committed with the brain so a
fresh clone opens identically; only per-machine UI state (`workspace.json`, caches,
`.trash/`) is ignored.

**Recommended: Excalidraw.** Drawings are a one-click install rather than bundled (its
AGPL-3.0 licence does not sit inside an MIT wheel, and it weighs eight megabytes): Settings →
Community
plugins → Browse → search "Excalidraw" → Install → Enable. Save each drawing beside the note
it illustrates, inside a dated source folder such as
`knowledge/sources/2026/08/2026-08-28-funnel-map/` (a loose `drawings/` folder, or
Excalidraw's default `Excalidraw/` folder at the vault root, is off-schema and `mos validate`
will say so). `*.excalidraw.md` files are exempt from the frontmatter contract, so
`mos validate --strict` never flags a drawing.

## 9. The nine bundled skills

All nine install to both runtimes. Invoke one as `/name` in Claude Code, `$name` in Codex.

| Skill | What it does |
| --- | --- |
| `mos-onboard` | Create a new brain or complete an existing one: scaffold, git, the context interview, and client registration for agencies. |
| `mos-start` | Start or resume work from deterministic repository facts, and recommend one useful next action. |
| `mos-status` | A deterministic briefing: what is healthy, what context is missing, and the single next action. |
| `mos-help` | Explain setup, architecture, routing, status, validation, and Claude Code or Codex wiring. |
| `mos-think` | Research a question from repository truth, decide with you, and codify the decision as durable memory. |
| `mos-bet` | Open, update, close, list, or narrate a falsifiable business bet as a dated decision artifact. |
| `mos-end` | Close a session: record the current focus, log what changed, and propose a safe commit. |
| `mos-update` | Update the engine, refresh the bundled skills, and verify runtime wiring. |
| `mos-migrate` | Route a messy folder into the canonical structure. The skill produces the plan; `mos migrate` applies it. |

Five of the nine are named for a CLI command they wrap: `mos-status`, `mos-think`,
`mos-update`, `mos-onboard`, and `mos-migrate`. The other four narrate the CLI without
sharing a name with one — `mos-bet` and `mos-end` say so themselves, because a bet is a dated
decision artifact rather than a command and git is already the checkpoint mechanism. All nine
run `mos` commands; `mos-bet` and `mos-end` both lean on `mos status` and `mos validate`.
