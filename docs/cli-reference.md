# CLI Reference

`mos` is a deterministic command line tool that manages a file-based marketing
brain. It scaffolds structure, reports facts, validates the canonical schema,
captures raw material, and wires the shared skills into each runtime. It never
writes business prose; that is the agent's job.

Every command here is model-free except `mos assist`, which may run an agent runtime
the operator already installed, only when they ask for it, and which writes nothing.
That exception is stated in full in [architecture.md](architecture.md).

```text
mos [--version] <command> [arguments] [options]
```

- `--version` prints `mos <version>` and exits.
- Every command accepts `--json` to emit the machine envelope only.
- Exit code is `0` when the result is `ok`, otherwise `1`. Two exceptions:
  `mos statusline` always exits `0`, and a usage error argparse rejects — a bad
  flag, a missing required option, a subcommand group with no subcommand — exits
  `2` before any handler runs.

Most commands take the repository `path` as their last positional, defaulting to
the current folder. The exceptions are worth knowing before you type: `query` takes
`"<question>" [path]`, `think` takes `<topic> [path]`, `ingest` takes
`[source] [path]`, `ui` takes a single `target`, and `install`, `update` and
`assist status` take no positional at all.

Four commands are groups and need their subcommand: `skills sync`,
`index build|sync|status`, `context show|set`, and `assist status|ask`. `mos skills`
on its own is a usage error, not a default.

See [json-output-contract.md](json-output-contract.md) for the envelope shape and
[agent-runtime-contract.md](agent-runtime-contract.md) for the skill sync model.

## Mutation gating

The mutating commands — `install`, `onboard`, `attach`, `migrate`, `skills sync`,
`index sync`, `related`, `context set`, `update` — require **exactly one** of:

- `--plan` — preview the changes without writing anything.
- `--yes` — apply the reviewed changes.

The two flags form a required, mutually exclusive group. Passing both or neither
is rejected before any work runs. The convention is: plan, review the reported
changes, then apply.

`ingest` is the exception in form only. Its group is declared optional so that
`ingest --pending`, which is read-only, can run without a flag; a real capture still
fails with `choose exactly one of --plan or --yes` when neither is given, so it is
gated like everything else.

The rest take no mutation flag: `status`, `validate`, `doctor`, `index build`,
`index status`, `query`, `think`, `context show`, `assist status`, `assist ask`,
`statusline`, `ui`, and `ingest --pending`. Two of those still write, and it is
worth being precise about where. `index build` writes the catalogue to
`.mos/local/`, which is machine-local and gitignored; `ui` writes its own state
under `~/.marketing-os`. Neither touches a document in the brain, which is what the
gate exists to protect.

## Output modes

Without `--json`, `mos` prints a human summary: a state line (`OK` or
`NEEDS ATTENTION`), the repository path, any changes, any findings, and the next
action's reason. With `--json`, it prints only the sorted, indented envelope.
Failures are still reported through the envelope, never as a stack trace.

`mos statusline` is the one command that does not follow this. Without `--json` it
prints its badge line alone — no state line, no findings, no next action — and
prints nothing at all when that line is empty.

## Commands

### `mos install`

```text
mos install [--runtime claude|codex|all] [--no-ui] (--plan | --yes) [--json]
```

Installs every bundled skill (the set listed in the packaged `manifest.json`)
**globally** into your home directory so they are available in every project. The
target runtime directories are `~/.claude/skills` (Claude Code) and
`~/.agents/skills` (Codex); `--runtime all` (the default) does both. Installed
copies are tracked in the global manifest at
`~/.marketing-os/runtime-manifest.json`. Run this once per machine before opening
any business folder. (`mos --help` still describes install as "the three bootstrap
skills". That string is the subparser's `help=`, so it appears in the parent command
listing and not in `mos install --help`, which carries no description at all. The count
is stale either way; the manifest below is the truth.)

Nine skills ship in the manifest:

| Skill | What it does |
|-------|--------------|
| `mos-onboard` | Create a new brain or complete an existing one: scaffold, git, the context interview, and client registration for agencies. |
| `mos-start` | Start or resume work from repository facts and recommend one useful next action. |
| `mos-status` | Brief you on what is healthy, what context is missing, and the single next action. |
| `mos-help` | Explain setup, architecture, routing, status, validation, and Claude Code or Codex wiring. |
| `mos-think` | Research a question from repository truth, decide with you, and codify the decision as durable memory. |
| `mos-bet` | Open, update, close, list, or narrate a falsifiable business bet as a dated decision artifact. |
| `mos-migrate` | Produce the routing plan for a messy folder that `mos migrate` then applies. |
| `mos-update` | Update the engine, refresh the bundled skills, and verify runtime wiring. |
| `mos-end` | Close a session: record the current focus, log what changed, and propose a safe commit. |

Each is invoked as `/mos-start` in Claude Code and `$mos-start` in Codex. Five are named for
a CLI command they wrap: `mos-status`, `mos-think`, `mos-update`, `mos-onboard`, and
`mos-migrate`. The other four are not, and `mos-bet` and `mos-end` say so themselves — there
is no `mos bet` and no checkpoint command, because a bet is a decision artifact and git is
already the save mechanism. All nine are thin narrations over the CLI regardless; `mos-bet`
and `mos-end` both run `mos status` and `mos validate`.

On the first successful `--yes`, install also opens the local app in a browser, at most once
per machine. A `ui-opened` marker under `~/.marketing-os` is written *before* the attempt, so a
crash cannot turn it into an open on every install — and that ordering has a consequence on
Windows. This path demands a detached server, so on a platform with no `os.fork` nothing
starts: the attempt returns a `ui-needs-foreground` finding with `running: false`, the marker
is already spent, and no later install retries. Start the app yourself with `mos ui`. The
outcome is reported in a `ui` block on the envelope, which the human renderer does not print,
so read it with `--json`. `--no-ui` suppresses the attempt, and a browser that will not open
is never allowed to fail the install.

### `mos onboard`

```text
mos onboard [path] --name "<business name>" --mode in-house|agency|client [--agency "<name>"] \
    [--hq <path>] [--runtime claude|codex|all] (--plan | --yes) [--json]
```

The single command to create **or** complete a business brain. Onboard works on a
new empty folder (scaffold + `git init` + first commit + interview) and on an
existing brain (complete or repair in place; `git init` only when the folder is not
already a repository). `--name` is required. `--mode` is also required and decides
how the brain is shaped:

- `in-house` — one brand you run yourself; knowledge is global to the brand.
- `agency` — you serve clients; the HQ repo also scaffolds
  `business/clients/clients.md`, a registry of pointers to each client's own repo.
- `client` — the brain for a single agency client; requires `--agency "<name>"`,
  which is recorded in the config. Passing `--agency` in any other mode is ignored
  with an `agency-ignored` warning.

Omitting `--mode` returns `ok: false` with a `mode-required` finding and a
`choose-mode` next action (nothing is written); the action's `reason` is the
verbatim question to put to the user. An unrecognized value never reaches onboard:
`--mode` is declared with `choices`, so argparse rejects it with `invalid choice` and
exit `2` before any handler runs.

Onboard writes the template tree, the agency overlay when relevant, the
`.mos/config.yaml` identity file (carrying `mode`, plus `agency` in client mode),
and the project-local runtime skill copies. It refuses a non-empty destination that
is not already a marketing-os repository, and it never overwrites an existing
business file. It then runs the context interview — brand, voice, audience, offer,
and strategy (`business/strategy/{strategy,goals,roadmap}.md`) — and carries an
`interview` block in the envelope listing still-unfilled business files. On apply it
also initializes a git repository and records a first commit; when git is unavailable
the step is skipped with a `git-unavailable` warning.

`--hq <path>` applies only in client mode. It points at the agency HQ repo and, on
apply, appends a registry row to `<hq>/business/clients/clients.md`, inserted
directly after the `_example-client_` row (else at the table tail). The row records
the client repo as a **relative, forward-slash path** from the HQ root (falling back
to an absolute path only across Windows drives). Duplicate client names (compared
case-insensitively) are skipped with `client-already-registered`; an HQ path that is
not an agency repo warns `no-client-registry`; a registry file with no markdown
table warns `registry-malformed`; and `--hq` in a non-client mode warns
`hq-ignored`. In `--plan` mode nothing is written to the registry. The envelope adds
`mode` and `suggested_repo_name` facts on success (`{slug}-hq` for in-house/agency,
`{agency-slug}-{slug}` for client).

After onboard, push to GitHub with the manual handoff:
`gh repo create <owner>/<repo> --private --source . --push`

### `mos attach`

```text
mos attach [path] [--name "<business name>"] [--mode in-house|agency|client] \
    [--runtime claude|codex|all] (--plan | --yes) [--json]
```

Adopts a folder that already holds a brain in an older layout — a `.mos/config.yaml`
written as plain YAML (`mode: in-house`, `name: ...`), or a `BRAIN.md` beside a
`business/` tree — as a first-class marketing-os brain **without rewriting its
content**. Exactly two kinds of write happen: `.mos/config.yaml` is rewritten in the
canonical JSON form (the previous text is kept as `.mos/config.legacy.yaml` when it
differs), and scaffold files the folder lacks are added — the top-level contract
documents (`BRAIN.md`, `CONTRACT.md`, `AGENTS.md`, `.gitattributes`, ...), the required
empty directories, and the generated runtime skill copies. Nothing that exists is
overwritten, and no `business/` or `knowledge/` content file is ever created; a missing
required document is reported as a `missing-content-file` warning and every stray
top-level entry as `off-schema-entry`, both pointing at `mos migrate --plan`.

The name comes from `--name`, then the legacy config's `business_name` or `name`, then
the folder name; the mode from `--mode`, then a valid legacy `mode`, then `in-house`.
A canonical brain is an `ok` no-op with an `already-attached` finding; a folder with no
brain signals is refused with `not-a-brain` and a `run-onboard` next action. The
envelope adds `name`, `mode`, `legacy` (the parsed YAML, or null) and `unrouted`; after
`--yes` the next action is `run-status`.

### `mos migrate`

```text
mos migrate [path] [--plan-file <plan.json>] (--plan | --yes) [--json]
```

Routes off-schema files into the canonical structure. It is model-free: with no
`--plan-file` in `--plan` mode it **diagnoses**, listing the stray top-level entries
as `unrouted` (dotfiles and canonical areas are ignored) — nothing is written. Given
a `--plan-file` — a `mos.migrate-plan.v1` document with `mkdirs` and `moves` — it
validates the moves as a set and, under `--yes`, applies them. The plan is atomic:
if any move is invalid (missing source, a destination that escapes the repo, or a
destination that already exists) **nothing** is written and the findings name what to
fix; existing files are never overwritten. The judgement of where each stray file
belongs lives in the `mos-migrate` skill, not the command. The envelope adds
`unrouted`, `plan_schema`, `moved`, and `created_dirs` facts.

### `mos status`

```text
mos status [path] [--json]
```

Inspects structure, context readiness, and runtime wiring, then reports a single
`repo_state` (see below). This is the primary orientation command. It is
read-only. Exit code is `0` for `needs-runtime-sync`, `needs-context`, and
`ready`; `absent` and `invalid` exit `1`.

### `mos validate`

```text
mos validate [path] [--strict] [--json]
```

Validates the canonical schema, the dated-folder grammar (config identity,
required directories and files, allowed top-level paths, and the
`YYYY/MM/YYYY-MM-DD-slug` layout for dated artifacts), and the frontmatter
contract. Structural problems are `error` findings; unknown top-level paths and
contract gaps are `warning` findings. Exit is `1` only when there is at least one
error.

`--strict` promotes every contract finding to an error, which is what continuous
integration should run. Warnings are the default so an early-stage brain, where
most documents are still stubs, is never blocked from doing work.

Contract findings:

| Code | Meaning |
|------|---------|
| `missing-frontmatter` | No contract block, or one of the five required keys is absent. |
| `missing-connective-key` | No `sources`, `related`, or `produced_by`, so nothing reaches this document. |
| `output-without-sources` | A file under `content/`, `campaigns/`, `reporting/`, or `outputs/` with no `sources:`. An output with no sources is not finished. |
| `unlinked-document` | A substantial document that links to nothing. Fix with `mos related`. |
| `invalid-type` | `type` is outside the vocabulary, or contradicts the folder it sits in. |
| `invalid-status` | `status` is not one of draft, active, archived, superseded. |

The `summary` block reports `errors`, `warnings`, and `contract_gaps`.

### `mos doctor`

```text
mos doctor [path] [--json]
```

Runs the `status` checks plus an explicit health verdict for both runtime
adapters. It reports a `checks` block (`structure`, `runtime_wiring`,
`context_ready`) and is `ok` only when structure is sound **and** Claude Code and
Codex skill discovery are both ready.

### `mos rename`

```text
mos rename [path] --name NAME (--plan | --yes) [--json]
```

Changes the business name a brain belongs to, in `.mos/config.yaml`, and nothing else.
Documents that mention the old name are left as they are. `--plan` names the change
without writing; `--yes` applies it. The envelope carries `name` and `previous_name`.
The same name is `ok` with no changes; an empty name is a `missing-name` error.

### `mos skills sync`

```text
mos skills sync [path] [--runtime claude|codex|all] (--plan | --yes) [--json]
```

Plans or synchronizes the **project-local** runtime skill copies against the
packaged source, using content-hash staleness detection. It creates missing skill
directories and replaces stale generated ones, but never overwrites an
unrecognized directory — those raise a `skill-conflict` finding for you to resolve
by hand. Project sync state lives in `.mos/local/runtime-manifest.json`.

### `mos ingest`

```text
mos ingest <source> [path] [--topic <label>] [--slug <slug>] [--date YYYY-MM-DD] \
    (--plan | --yes) [--json]
mos ingest --pending [path] [--json]
```

Captures raw material into `knowledge/sources/` so it can be distilled later.
`source` is a file, a directory, an `http://` or `https://` URL, or literal text —
checked in that order, so an argument that names a real file is a file and anything
left over is text. The capture lands in
`knowledge/sources/YYYY/MM/YYYY-MM-DD-slug/source.md`: a file's contents are copied
in under a short header, a directory writes a manifest plus every `.md` and `.txt`
member beneath `files/`, a URL records the address, and literal text becomes the
body. Directory members go under `files/` rather than the folder root so a member
called `source.md` can never overwrite the manifest.

The slug comes from `--slug`, else from the file stem, the directory name, the URL,
or the first eight words of the text. `--date` defaults to today and must be
`YYYY-MM-DD`; anything else returns a `bad-date` finding and writes nothing.
`--topic` is a label recorded in the header and used nowhere else. A folder that
already exists for that date and slug is never overwritten: the command refuses with
`source-exists` and asks for a different `--slug` or `--date`. On apply the folder is
built in a temporary directory beside its destination and moved into place, so a
failed write leaves no half-capture behind.

`--pending` lists captures that have not been compiled yet: every
`knowledge/sources/YYYY/MM/<folder>/source.md` whose folder name does not appear in
`knowledge/wiki/_log.md`. That log line is the entire bookkeeping mechanism — writing
the folder name into `_log.md` is what marks a source as done.

**`--pending` reads a lone positional as the repository, not the source.** It is
read-only, so it refuses `--plan` and `--yes`, and it accepts an optional repository
path and nothing else. But `source` is the first positional, so
`mos ingest --pending ./notes.md` looks for a brain at `./notes.md` rather than
checking that file. Two positionals are refused outright. Pass a path here only when
you mean the brain.

### `mos index build`

```text
mos index build [path] [--json]
```

Reads every document once and writes the catalogue to `.mos/local/catalog.json`
(machine-local, gitignored). The catalogue records each document's title,
description, type, status, word count, outgoing links, and which contract keys it
carries. It is what lets `mos query` answer without opening a single document
body.

### `mos index sync`

```text
mos index sync [path] (--plan | --yes) [--json]
```

Regenerates the `_index.md` navigation hierarchy from the live corpus. Three
levels: the root index names every folder holding documents; a folder index lists
its groups or its documents; a group index lists documents. A folder at or below
40 documents lists them inline, above that it explodes into child indexes, which
is what keeps any single navigation file small enough to be worth reading.

Below 25 documents in total, only the root index is generated — a hierarchy over a
near-empty brain is noise, and the command says so with a `small-corpus` finding.

Generated files carry a do-not-hand-edit marker. If a file of the same name exists
without that marker, the generator leaves it alone and raises
`hand-written-index`. Re-running when nothing has changed writes nothing.

### `mos index status`

```text
mos index status [path] [--json]
```

Reports catalogue freshness and navigation coverage: the share of documents
carrying frontmatter, a description, and an outgoing link, plus which folder
indexes exist. A `no-catalog` finding means `mos query` is reading every document. A
`stale-catalog` finding means something else: `mos query` scores whatever catalogue is on
disk regardless of freshness, so it is still answering from the catalogue —
`source: catalog` — but from metadata that no longer matches the corpus. It drops to a body
scan only when the stale catalogue scores nothing at all, which is exactly the case where the
answer lives in text added since the last build. Rebuild with `mos index build`.

### `mos related`

```text
mos related [path] (--plan | --yes) [--limit N] [--json]
```

Proposes a `## Related` block for every substantial document that links to
nothing. Candidates are scored by term overlap across `title` and `description`
only — not bodies, so a long document cannot dominate by length — and targets in a
different top-level folder are weighted higher, because those are the connections
nothing else in the repository supplies.

A weak match emits nothing rather than a plausible-looking wrong link, so on a small
corpus the correct output is often an empty plan.

Two different rules govern the two ends of a link, and they do not cover the same set.
Documents under 120 words, `knowledge/sources/`, `archive/`, any path containing
`_archive/`, `_archived/` or `_superseded/`, and structural files are never **touched** — no
`## Related` block is appended to them. Archived or superseded material is never **linked
to**: a frontmatter `status:` of `archived` or `superseded` disqualifies a document as a
target. That status is checked only on the target side, so a document declaring
`status: archived` outside an archive folder is still eligible to have a block appended to
it. Existing line endings are preserved.

`--limit N` caps how many documents the plan touches, not how many links each one
gets — that is fixed at four. Omit it and the plan covers every eligible document.

### `mos query`

```text
mos query "<question>" [path] [--limit N] [--grep] [--json]
```

Plans deterministic retrieval. With a catalogue present it scores the question
against titles, descriptions, types, and paths, so cost does not grow with
document length; without one it falls back to reading bodies and says so in
`source`. The corpus covers every non-archived document, not just `business/` and
`knowledge/wiki/`.

Alongside `candidates`, the response carries `route`: the chain of `_index.md`
files leading to the best candidate. Walking that chain first is what turns
retrieval into navigation — the model gets the branch, not only the leaf.

`--grep` switches to literal substring lookup and returns `path`, `line`, and the
matching text. Use it for URLs, names, identifiers, and error strings, where term
scoring is the wrong tool.

`--limit` caps the candidate documents returned and defaults to 5. It does not apply to
`--grep`, which stops at 40 matches and says so with a `results-truncated` finding.

### `mos think`

```text
mos think "<topic>" [path] [--json]
```

Builds a grounded thinking handoff for a topic and writes nothing. `topic` is a
required positional, not a flag; `path` is the optional second positional.

The `prompt` block carries an `objective`, the `context_paths` to read, the `steps`
to follow, and an `output_contract` of decision, why, alternatives rejected, and
revisit-when. `context_paths` always leads with `BRAIN.md`,
`business/strategy/strategy.md` and `business/strategy/goals.md` when they exist,
then adds up to five documents scored against the topic by the same scorer `mos
query` uses. Those three go in whatever the topic is, because a recommendation
reasoned without them is a recommendation about a different business.

The steps name the file the decision should land in —
`business/decisions/YYYY/MM/YYYY-MM-DD-<topic-slug>/decision.md` — and tell the agent to
append a line naming that decision file to `knowledge/wiki/_log.md`. (The folder-name
convention is `mos ingest --pending`'s, for sources; it is not what think emits.) The command
supplies the prompt; the `mos-think` skill is what runs it.

### `mos context show`

```text
mos context show [path] [--json]
```

Turns every context gap `mos status` reports into a question a person can answer.
For each field it returns the `name`, a plain-language `question` and `hint`, the
canonical file `path`, `writes_to` (where an answer would land), whether it is
`complete`, whether it is `required`, and `body` — the operator's own words, with the
document's heading stripped. The offer field also carries `files`, the offer
documents that already exist. The four required fields — brand, voice, audience,
offer — come first, then strategy and proof.

Completeness is decided by the same function `mos status` uses, so untouched
template boilerplate reports as no answer and the two commands can never disagree.
Read-only.

That shared function does more than check the canonical path, and it is worth knowing what
it does. A field also completes from a substantive file under `business/` or `reference/`
whose own name is one of the words the field is known by — `positioning` or `identity` for
brand, `tone` or `writing-style` for voice, `avatar` or `icp` for audience, `pricing` or
`package` for offer.

The file's own name is the gate. A folder can corroborate a name and can never stand in for
one, because a folder name is a filing decision and says nothing about what any one document
inside it contains: a README, a research bank or a copyright notice sitting in `business/voice/`
is not the voice of the business. Beyond that, every candidate is scored on naming, placement
and what its frontmatter claims about itself, and only one clearing a confidence floor is
accepted. `business/positioning/brand.md` and `business/pricing/pricing.md` resolve; a lone
`business/pricing.md` — an alias on the file name and nothing else — scores below the floor,
and offer still reports missing. Navigation and generated files never answer at all: a
`README.md`, an `_index.md` written by `mos index sync`, or any document whose frontmatter
`status` says `archived`, `superseded` or `gap` is refused outright rather than marked down.
The walk goes at most four levels below `business/` and `reference/`, follows nothing out of
the repository, and skips archive, template, scratch and machinery folders in any spelling,
so "anywhere under" is not quite it.

That exists so a brain which answered a question at length in a folder of its owner's naming
is not asked to answer it again. An exact canonical hit short-circuits the scan, and a scan
that finds nothing convincing reports the field missing rather than settling.

`mos status` reports each field's `source` as `canonical`, `discovered` or `missing` and
names the file it found in `discovered_path`; `mos context show` passes both through and
reads the answer from wherever it actually is, so a discovered field shows its own words in
`body` and names the file they came from in `answered_in`. The seam that remains is
deliberate: `writes_to` stays the canonical path, because that is where `mos context set`
writes. Answering a question that already reads as answered therefore produces a second copy
of the same truth in a second file. If you want the canonical file to hold it, move the
discovered document rather than retyping it.

### `mos context set`

```text
mos context set [path] --field <name> --text <answer> [--slug <offer-slug>] (--plan | --yes) [--json]
```

Writes one answer into the file that backs one context field, and nothing else.
`--text -` reads the answer from stdin, so a long answer is never mangled by the
shell. That works in the terminal only: dispatched in process — the seam the local
app uses — `-` is refused with an explicit error rather than blocking a request
thread on a console that is not there.

`--slug` chooses which offer to write. It is required once a brain has more than one
offer, and a brain with none gets `business/offers/core-offer/offer.md` by default;
with exactly one existing offer, that one is the target. On every other field a
`--slug` is ignored with a `slug-ignored` warning.

Frontmatter that is already on the file is preserved line for line apart from
`date`, which is refreshed; a file with no contract block is given one per
`CONTRACT.md`. Only the body beneath the block is replaced, and the file's existing
line endings are kept, so a one-line answer produces a one-line diff rather than a
whole-file rewrite.

`--plan` returns a real unified diff in `diff` and writes nothing. `field_complete` says
whether the answer is substantial enough to count; a short one still writes but returns an
`answer-too-short` warning.

`field_complete` is a verdict on the text going into the canonical file, not on the field.
`mos status` resolves a field through discovery, so on a brain that answered brand at
`business/positioning/brand.md` a short answer here returns `field_complete: false` — and the
same envelope's own `missing` list does not contain brand, because status already counts it
answered. The `answer-too-short` message says status will still report the field missing;
that holds for a field with no answer anywhere, not for a discovered one.

### `mos assist status`

```text
mos assist status [--json]
```

Reports which agent runtimes on this machine can genuinely answer. Being on PATH is
not the test: each candidate (`claude`, then `codex`) is resolved with `shutil.which`
and then actually run with `--version` under a short timeout. One that resolves but
exits non-zero, prints nothing, or never returns is reported unavailable with the
reason it failed.

`runtimes` lists only the invocable ones, each with `name`, `path`, and `version`.
`checked` lists every candidate with `resolved`, `available`, `reason`, and `version`,
so a caller can explain the absence. `ready` is whether anything answered. This
command writes nothing and needs no repository.

`claude` is the runtime this was built and verified against. The `codex` entry follows
that tool's documented `codex exec` interface and has not been exercised against a
real install, so `available: true` for `codex` is a statement about its version probe,
not a promise that a turn will succeed.

### `mos assist ask`

```text
mos assist ask [path] --field <name> [--transcript-json <json>] [--json]
```

Runs one stateless interview turn for one context field, using the first runtime that
answered. It runs on the operator's own subscription and spends their tokens, only on
an explicit request.

The caller owns the conversation. `--transcript-json` is the whole memory of the
interview: a JSON array of `{"question": ..., "answer": ...}` objects, defaulting to
`[]` on the first turn. The engine keeps no session, no state file, and no history on
disk between turns.

Before it asks anything the assistant is given what the brain already knows — the
business name, the mode, and every field already answered with the operator's own
words — read from the same place `mos context show` reads it, so nobody is asked
twice about something they have already said.

Two shapes come back, both inside the standard envelope on schema `mos.assist.v1`:

```json
{ "schema": "mos.assist.v1", "ok": true, "operation": "ask", "field": "brand",
  "runtime": "claude", "done": false, "question": "...", "draft": "",
  "turn": 2, "turns_used": 1 }
```

```json
{ "schema": "mos.assist.v1", "ok": true, "operation": "ask", "field": "brand",
  "runtime": "claude", "done": true, "question": "", "draft": "...",
  "turn": 5, "turns_used": 4 }
```

The interview is bounded at four questions. The fifth turn must produce a draft, and
that is enforced by the engine rather than by the wording sent to the model: a reply
that asks a fifth question is discarded and reported as an error, never handed back as
a question. A transcript longer than four turns is refused outright.

**This command writes nothing.** The draft comes back as data for the operator to read
and edit; `mos context set`, under the existing `--plan`/`--yes` gating, is still the
only thing that writes it to a file.

The whole prompt — the field, the grounding, and the transcript — is written to a file
this command creates and handed to the child on stdin. Nothing operator-authored or
model-authored is ever placed in the child's argument list, so a field name, an answer,
or a draft that begins with `-` has no route to being parsed as a flag. `--field` is
additionally checked against the closed set of context fields. There is no shell. The
child's stdout and stderr go to files rather than to inherited descriptors, so nothing
it prints can contaminate the `--json` envelope, and it runs in a scratch directory
that is removed when the turn ends.

Failures are envelopes, never hangs and never stack traces: `no-runtime` when nothing
answered, `unknown-field`, `bad-transcript`, `assist-timeout`, `assist-reply-too-large`,
`assist-failed` when the runtime exited non-zero, and `assist-unusable-reply` when the
reply was not a usable question or draft. In every one of them `question` and `draft`
are empty.

### `mos update`

```text
mos update (--plan | --yes) [--json]
```

Updates the marketing-os engine itself. It is the only mutating command that takes no
path, because what it changes is the installed package, not a brain.

It works out how the engine was installed by walking up from the installed package
and reports the answer as `mode`:

- `source` — an ancestor directory holding a `marketing-os` `pyproject.toml` beside a
  `.git` directory. Updates with `git -C <root> pull --ff-only`.
- `pipx` — the install path contains `pipx`. Updates with `pipx upgrade marketing-os`.
- `uv` — the install path is under a `uv/tools/` prefix, which is where `uv tool install`
  puts it. Updates with `uv tool upgrade marketing-os`.
- `unknown` — neither. Nothing runs; you get an `unknown-install` warning telling you
  to upgrade through whichever installer you used.

Source mode checks two guards before anything runs: the checkout must be on `main`,
and the worktree must be clean. Either one fails the command with nothing run and no
changes reported — `not-on-main` or `dirty-worktree` — because fast-forwarding over
someone's uncommitted work is exactly the surprise an update command must not spring.
The envelope always carries `run_command`, the exact command it would run or did run,
so `--plan` tells you precisely what `--yes` will do.

### `mos statusline`

```text
mos statusline [path] [--json]
```

Prints one line for an ambient status bar, and writes nothing:

```text
mos | Acme Co | in-house | skills 9/9
```

The skill count is this brain's project-local Claude Code copies measured against the
bundled manifest, so it drops the moment one goes missing or stale. The mode segment is
omitted when the config carries no mode or an invalid one, because a status bar is the wrong
place to argue about it. The two are not identical in the envelope: an invalid value is
carried verbatim as the `mode` fact so a caller can see what is wrong, while a missing one
reports `mode: null` — there is no value to read.

Two exceptions to the rules at the top of this file, both so a shell prompt can call
this on every redraw without ever breaking:

- Without `--json` it prints the badge line and nothing else, and prints nothing at
  all outside a brain, where the envelope carries `active: false` and an empty `line`.
- It always exits `0`, whatever the envelope says.

### `mos ui`

```text
mos ui [target] [--port N] [--no-open] [--json]
```

Starts, stops, or inspects the local app — a small server on `127.0.0.1` that drives
this same CLI from a browser. `target` is the folder to open, defaulting to the
current one, or one of two literal words:

- `mos ui stop` signals the recorded process, waits up to ten seconds for the port to
  clear, then clears the state file. Stopping nothing is a success with a
  `ui-not-running` warning; a process that will not go reports `ui-stop-timeout` and
  the pid to end by hand.
- `mos ui status` reports `running`, plus `pid`, `port` and `url` when it is.

Those two are matched as exact strings before the argument is treated as a path, so a
folder literally named `stop` or `status` cannot be opened this way. Write it with a
separator — `mos ui ./stop` — and it opens normally.

With no `--port`, start walks up from 4321 to 4370 and binds the first free one;
`--port` binds exactly that port and fails with `ui-port-unavailable` rather than
looking elsewhere. Where the platform has `os.fork` the server is handed to a detached
child and the terminal comes straight back; where it does not, the server runs on a
thread of this process and holds the window — reported as a `ui-foreground` warning
rather than hidden. A browser opens unless `--no-open`, and a browser that will not
open is a warning, not a failure. Starting again while one is running reuses it and
says so with `ui-already-running`.

`ui` has no `--plan`/`--yes` gate because it never writes to the brain. The command itself
writes two files of machine-local state under `~/.marketing-os`, or under `$MOS_HOME` when
that is set: `ui.json` (pid, port, url and root — deliberately never the session token) and
`ui.log`. Two other files in that folder are often mistaken for its work. The `brains.json`
registry is written by the *running server*, when the browser app asks for state or a brain is
opened or created in it — not by the `mos ui` invocation. The `ui-opened` marker belongs to
`mos install`, which is the only thing that writes it; see that command above. The envelope
carries `operation` and `running` every time, `pid`, `port` and `url` when there is a server,
and `state_file` when one is recorded.

## Repository states

`mos status` resolves the repository into exactly one `repo_state`:

| State | Meaning | Suggested action |
|-------|---------|------------------|
| `absent` | No canonical `.mos/config.yaml`; this is not a marketing-os repository. | Run `mos onboard`, or `mos attach` if the folder already holds an older brain. |
| `invalid` | Structural `error` findings (missing config, directories, files, or malformed dated folders). | Repair structure, then re-check. |
| `needs-runtime-sync` | Structure is sound but Claude Code or Codex skill copies are missing or stale. | Run `mos skills sync`. |
| `needs-context` | Structure and wiring are sound but required context (brand, voice, audience, offer) is incomplete. | Complete the first missing context file. |
| `ready` | Structure, wiring, and required context are all in place. | Follow `CONTEXT.md` for the current priority. |

Only `absent` and `invalid` make `mos status` return a non-zero exit; the other
states are `ok` because the structure itself is valid.

## Examples

```bash
# One-time global install of the nine bundled skills
mos install --runtime all --plan
mos install --runtime all --yes

# Create a new brain (or complete an existing one), review then apply
mos onboard ./acme --name "Acme Co" --mode in-house --plan
mos onboard ./acme --name "Acme Co" --mode in-house --yes

# Adopt a folder that already holds a brain in an older layout
mos attach ./the-lab --plan
mos attach ./the-lab --yes

# Onboard an agency client and register it in the agency HQ
mos onboard ./acme-widgets --name "Widgets Inc" --mode client \
    --agency "Acme Co" --hq ../acme-co-hq --plan
mos onboard ./acme-widgets --name "Widgets Inc" --mode client \
    --agency "Acme Co" --hq ../acme-co-hq --yes

# Daily orientation and machine-readable facts
mos status .
mos status . --json

# Repair loop
mos validate . --json
mos skills sync . --runtime all --plan
mos skills sync . --runtime all --yes
mos doctor . --json

# Refresh the navigation layer after writing documents
mos index build .
mos index sync . --plan
mos index sync . --yes
mos related . --plan
mos related . --yes
mos index status . --json

# Ask the brain a question, or find an exact string
mos query "how should we price the retention offer" . --json
mos query "https://example.com/pricing" . --grep --json

# Hand a topic to the agent with the strategy files already attached
mos think "should we raise prices" . --json

# Capture raw material, then see what has not been compiled yet
mos ingest ./call-notes.md . --topic pricing --plan
mos ingest ./call-notes.md . --topic pricing --yes
mos ingest "three gyms asked about payment plans this week" . --yes
mos ingest --pending .

# Open the local app, check it, close it
mos ui .
mos ui status --json
mos ui stop

# One line for a shell prompt, and updating the engine itself
mos statusline .
mos update --plan
mos update --yes

# Fail continuous integration on contract gaps
mos validate . --strict --json
```
