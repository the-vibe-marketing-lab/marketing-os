# Architecture

marketing-os is two repositories with different jobs. This one, the **engine repository**,
holds the `mos` CLI, the packaged skills, and the templates. It never contains a business.
Running `mos onboard` (or the bundled onboard skill) produces a **business repository**: a
generated, self-contained marketing brain that holds one business's truth and its execution
artifacts. Judgment, interviews, synthesis, and writing happen in the business repository,
driven by agents. See [the business-repo architecture](business-repo.md) for the generated
structure.

## The engine is model-free, with exactly one documented exception

Every command in this engine calls no model, with one exception that is named here rather than
left to be discovered. Determinism is a separate claim with its own carve-outs, listed in the
same place and in [philosophy.md](philosophy.md):

- `core/assist.py`, reached only through `mos assist status` and `mos assist ask`, may invoke
  an agent runtime the operator already has installed — `claude` or `codex` — as a child
  process. It runs on the operator's own subscription, on their machine, and only when they
  explicitly ask for it. It exists because the in-app interview otherwise hands a business
  owner an empty box and asks them to write about their own business cold.
- Nothing else in the engine calls a model. `mos ui` — and the one-time browser open on a
  first `mos install --yes` — binds a loopback socket and starts the operator's browser, but
  invokes no runtime and makes no outbound call of its own. It sits outside the determinism
  claim all the same: the pid, port and URL it reports are whatever that run happened to get.
- Two commands leave the filesystem, as child processes rather than as network code of their
  own. `mos update` runs `git -C <root> pull --ff-only`, `pipx upgrade marketing-os` or
  `uv tool upgrade marketing-os` — a
  deliberate fetch, on the operator's own credentials — and reports the exact argv as
  `run_command`, so `--plan` shows what `--yes` will do. `mos onboard --yes` shells out to
  `git init`, `git add` and `git commit`. Every other command is filesystem-only: no network,
  no subprocess, and the same repository in gives the same structure out, allowing for the
  dated execution trees that stamp today's date.
- `dependencies = []` still holds. There is no SDK and no HTTP client here. The engine runs a
  binary the operator already installed, as a child process with a fixed argument list and no
  shell, and never makes a network call of its own — the child does its own networking, on its
  own credentials.
- Nothing that seam produces is written by it. `mos assist ask` returns a draft as data; only
  `mos context set`, under the existing `--plan`/`--yes` gating, writes anything to disk.
- A runtime's output is untrusted input. It is parsed defensively, stripped of escape
  sequences and control characters, length-checked, and returned as a string. It never becomes
  markup, a path, a command, or an argument to anything.

## Engine module map

The engine lives under `src/marketing_os/`:

- `cli/` — the `mos` argument parser and command dispatch. It renders every result as text
  or `--json` and owns the `--plan`/`--yes` gating on mutating commands.
- `core/schema.py` — locates packaged assets (including the `mode-overlays/` tree), reads
  `.mos/config.yaml`, finds the repository root, emits its canonical text (`config_text`, which
  records `mode`/`agency`), and resolves the repository mode (`repo_mode`). It never writes:
  `core/setup.py` and `core/attach.py` do that.
- `core/setup.py` — plans and applies the scaffold: copies the business template, then the
  chosen mode's overlay tree (only agency has one), renders `{{BUSINESS_NAME}}`, writes the
  config, and wires runtime skills. It gates on `--mode` (returning a `choose-mode` handoff
  when omitted) and never overwrites an existing business file.
- `core/skills.py` — the runtime sync engine: the packaged skill source, `RUNTIME_DIRS`,
  content hashing (`tree_hash`), the plan/apply cycle, and the manifests that track what was
  installed.
- `core/status.py` — `mos status` and `mos doctor`; derives the repository state and the
  context-readiness view.
- `core/discover.py` — where a context field is actually answered when the canonical path is
  still empty. Status used to ask one question per field: is there real content at the single
  path the schema names? A brain that answered brand and audience at length, in folders of its
  owner's own naming, reported both as missing and then asked him to write again what he had
  already written. Discovery walks `business/` and `reference/` four segments deep — those two
  trees and nothing else, so no symlink anyone leaves in the folder can widen what a status
  check reads, and every path it resolves is inside the repository as well as relative to it.
  It considers only markdown whose **own name** is one of that field's aliases: a folder name
  corroborates a candidate and can never stand in for one, because a README, a research bank
  or a copyright notice in `business/voice/` is not the voice of the business. Navigation and
  machinery are refused outright rather than marked down — the `_index.md` files this program
  generates, `README.md`, and any document whose frontmatter marks it `archived`, `superseded`
  or `gap`. Survivors are scored on naming, placement, and what their frontmatter claims about
  themselves. A substantive canonical file short-circuits the scan and is never scored, so a
  schema-following brain resolves exactly as it did before this module existed and costs
  nothing to check; a best candidate below the confidence floor is discarded rather than
  settled for, because being told you have answered something you have not is worse than being
  asked twice. Every rule is a fixed integer, so the same tree always resolves the same way.
  All the unanswered fields are resolved in one walk of the tree rather than one walk each —
  the walk does not depend on which field is being asked about — and a scan that hits its
  budget reports `truncated` rather than passing a partial answer off as a complete one. A
  winner is reported as `source: "discovered"` with a `discovered_path`, and the canonical
  `path` never moves — that is still where `mos context set` writes and what `mos validate`
  measures.
- `core/context.py` — `mos context show` and `mos context set`; the other half of the status
  contract. `show` turns each gap into a question a person can answer, `set` writes one answer
  into the file backing one field, and both judge text with the same
  `status.substantive_text` that `mos status` uses, so neither over- nor under-reads a file it
  is looking at. That is not the same as agreeing with `mos status`: `set` reports
  `field_complete` for the canonical file it is writing, while status resolves the field
  through `discover.py`, so a field discovered elsewhere reads complete in status and
  `field_complete: false` in a short `set --plan` against the stub — with an
  `answer-too-short` message that overstates the case. The write goes through `atomic_write`,
  and an answer carrying an unpaired surrogate — what half an emoji looks like — is refused up
  front under `--plan` and `--yes` alike, because encoding it would empty the document it was
  meant to fill. An offer answer with no `--slug` lands at
  `business/offers/core-offer/offer.md` when the brain has no canonical offer, and in that
  offer's own file when it has exactly one; a brain with more than one refuses until one is
  named. One rough edge to know about: `show` reads the canonical path, so a field that
  status completed from a discovered file elsewhere comes back `complete` with an empty
  `body`, and a `set` there writes a second copy rather than editing the answer already on
  disk.
- `core/validation.py` — `mos validate`; checks required directories and files, unknown
  top-level paths, the dated-folder grammar, mode-aware structure (the agency client
  registry, stray client folders, and fail-closed `invalid-mode`), and the frontmatter
  contract, with `--strict` promoting contract warnings to errors.
- `core/catalog.py` — `mos index build`; parses frontmatter and links across every document
  and writes `.mos/local/catalog.json`. The frontmatter parser and `coverage` are shared by
  the sensors, the hierarchy generator, and `query`. The walk prunes skipped folders as it
  descends rather than filtering afterwards, reads each level's directories together, and
  keeps every document's size and modification time in `.mos/local/scan-cache.json` so a
  later run opens only the documents that have actually changed. That is per-file
  invalidation and nothing coarser: a folder's modification time does not move when a file
  inside it is edited, so a cache keyed on folders would show an operator yesterday's answer
  to a question they just answered.
- `core/index.py` — `mos index sync` and `mos index status`; generates the three-level
  `_index.md` hierarchy from the catalogue, with a size-bounded explode threshold and a
  do-not-overwrite rule for hand-written indexes.
- `core/related.py` — `mos related`; term-frequency scoring over titles and descriptions with
  a cross-folder weighting and a confidence floor, writing `## Related` blocks without
  disturbing line endings.
- `core/fix.py` — `mos fix`; the one table from a finding code to the existing core fixer
  that puts it right, and the `FIXABLE` set the app reads to decide which rows get
  preview-and-apply.
- `core/graphlint.py` — the frontmatter-contract sensors, surfaced through `mos validate`
  rather than a command of their own, because the repository already has one place for
  structural truth.
- `core/ingest.py` — `mos ingest`; captures a file, directory, URL, or literal text into a
  validator-conformant `knowledge/sources/YYYY/MM/YYYY-MM-DD-slug/` folder (atomically) and
  lists sources not yet compiled (`--pending`).
- `core/query.py` — `mos query`; a deterministic retrieval planner. It scores catalogued
  metadata when a catalogue exists and falls back to a body scan when it does not, returns
  candidate documents plus the `_index.md` route to them, and offers `--grep` for literal
  lookups (its `score_corpus` is reused by `think`).
- `core/think.py` — `mos think`; emits a grounded thinking handoff (objective, context paths,
  steps, output contract) that targets a `business/decisions/YYYY/MM/YYYY-MM-DD-slug/` file.
- `core/onboard.py` — `mos onboard`; reuses the setup scaffold, optionally `git init`s the
  repository, appends a client row to an agency HQ registry when `--mode client --hq` is given,
  and hands off the interview for unfilled business files.
- `core/attach.py` — `mos attach`; the other front door. `onboard` scaffolds a new brain and
  refuses a non-empty folder that is not already one, so a folder that grew a brain before
  this engine existed needs a different door. Attach rewrites `.mos/config.yaml` in the
  canonical JSON form, keeping the previous text as `.mos/config.legacy.yaml` when it differs,
  and adds only the scaffold files the operator does not already have. Nothing that exists is
  overwritten, and no `business/` or `knowledge/` content file is ever created, so nothing of
  the engine's can shadow what the operator wrote. Anything off-schema comes back as a finding
  pointing at `mos migrate --plan`.
- `core/migrate.py` — `mos migrate`; with no `--plan-file` it diagnoses the stray top-level
  entries and writes nothing. Given a `mos.migrate-plan.v1` plan file it validates the moves as
  a set before touching anything — a source that is missing or outside the repository, a
  destination that escapes it, or a destination that already exists fails the whole plan — and
  only then applies them. Deciding where a stray file belongs is the agent's judgment; making
  the move safely is the CLI's.
- `core/update.py` — `mos update`; detects the install mode (source checkout, pipx, unknown)
  and plans or runs the matching self-update command under guards.
- `core/statusline.py` — `mos statusline`; renders the one-line ambient badge and the skill
  install counts.
- `core/assist.py` — `mos assist status` and `mos assist ask`; the one seam that may invoke an
  agent runtime. `status` probes each candidate by actually running it, so a binary that is on
  PATH but cannot answer is reported unavailable. `ask` runs one stateless interview turn: the
  caller holds the conversation and passes it back, the engine keeps no session and no state
  file. The whole prompt travels to the child on stdin, never in its argv; the child's stdout
  and stderr go to files so nothing it prints can contaminate a `--json` envelope; it runs in a
  scratch directory that is deleted afterwards; and it is bounded in wall clock, in bytes, and
  at four questions before a draft is compulsory. `claude` is the runtime this was built and
  verified against; the `codex` entry follows that tool's documented `codex exec` interface and
  has not been exercised against a real install.
- `core/results.py` — the shared JSON envelope (`envelope`, `finding`, `next_action`) every
  command returns.
- `core/atomic.py` — `atomic_write`, the single way every command rewrites a document in the
  operator's repository. `Path.write_text` truncates the target and encodes afterwards, so a
  failure between those two moments leaves an empty file where a document was. `atomic_write`
  encodes first, writes a temporary file in the target's own directory, `fsync`s it, and
  renames it over the target, so a failed write leaves the original exactly as it was.
  Generated machine-local state (`.mos/local/catalog.json`, the runtime manifests, the app's
  `ui.json`) stays on `write_text` deliberately: those readers already treat an unreadable
  file as absent, and the next run writes a fresh one. Two exceptions go through
  `atomic_write`: `brains.json`, because it records something no later run can rebuild —
  which brains the operator has, and when each was last opened — and `scan-cache.json`,
  because the local app answers state requests for one brain concurrently, so two writers
  meeting inside one `write_text` is a normal event there rather than a crash.
- `assets/` — the packaged data: `schema.json` (the canonical structure), the
  `business-template/` scaffold, the `mode-overlays/` per-mode trees, and the `skills/` source
  of truth.
- `ui/` — the local app, a browser client for this same CLI. `server.py` is the stdlib HTTP
  shell, its guards and its routes; `lifecycle.py` starts, stops and reports on the server;
  `commands.py` is the allowlist that turns a request into an argv list; `state.py` owns the
  `~/.marketing-os` state file and the verified browser launch; `registry.py` keeps
  `brains.json`, the brains the app knows about; `places.py` supplies suggested places, folder
  listings, and WSL path conversion; `picker.py` opens the operating system's own folder
  window on the page's behalf. The browser client itself is three files under `ui/static/` —
  `index.html`, `app.js`, `styles.css` — shipped as package data. See
  [the local app](#the-local-app) below.

## The local app

`mos ui` opens the brain in a browser instead of a terminal. It is a third door onto the same
engine, not a second implementation of it: the page never names an argv. It names one of the
twenty-one allowlisted commands plus a flat bag of arguments, `ui/commands.py` builds the argv
from that, and `cli/main.py`'s `run_argv` dispatches it through the same parser and the same
handlers the terminal runs. The exact `mos …` line is shown back to the operator every time,
so what the app did is always a line they could have typed themselves. The one dispatchable
command missing from the allowlist is `ui` itself — the app cannot start or stop a server
through the browser.

```text
mos ui [target] [--port PORT] [--no-open] [--json]
```

`target` defaults to the current folder. Two literal words are magic: `mos ui stop` and
`mos ui status` act on the running server rather than opening a folder by that name. Starting
binds `127.0.0.1` on the first free port from 4321 through 4370, or the exact `--port` given.
The address is a module constant; there is no host flag and no LAN mode.

Starting must not hold the terminal hostage. Where `os.fork` exists the bound server is handed
to a detached child, the parent prints the URL and returns, and the app runs until it is
stopped — `mos ui stop` sends `SIGTERM` and waits up to ten seconds for the pid to release the
port. Where fork does not exist the server runs on a non-daemon thread of the launching
process and occupies that window, which is reported as a `ui-foreground` warning rather than
pretended away. The first-install open asks for a background start specifically, so on such a
platform it declines with `ui-needs-foreground` rather than holding the install open.

The API surface is small on purpose: three GET routes (the page, `/static/*`, and
`/api/state`) and four POST routes (`/api/run`, `/api/browse`, `/api/pick-folder`,
`/api/brains`). Everything else answers 404 as an envelope.

`/api/state` is the page's own shape and is the one place an envelope is trimmed. It carries
the first two hundred findings, errors before warnings, with `findings_total` and
`findings_counts` taken from the whole list, because a brain mid-migration can answer with
thousands and the page states the count rather than building a row for each; and the doctor
envelope it carries keeps its `checks` and drops the `findings` and `runtimes` that are the
status envelope's, item for item. Both envelopes are computed inside one
`core.status.reuse()` block, so `doctor` does not re-walk the brain `status` has just walked.
The envelopes `/api/run` returns, and everything the terminal prints, are the contract and
are never trimmed.

`mos ui` itself takes no `--plan`/`--yes` gate, because starting a server writes nothing to a
brain — it does write machine-local state, covered under [Local state](#local-state). Commands
run *through* the app keep their own gating unchanged: the page has to send `--yes` like
anyone else, and for a mutating command the Commands tab keeps the apply button disabled until
a `--plan` run with the identical argument signature has come back ok. Change any field and
the preview is invalidated.

The client is deliberately unremarkable technology. The server is stdlib
`http.server.ThreadingHTTPServer` — `dependencies = []` still holds here too, so there is no
web framework. The page is vanilla JavaScript in one file, with no framework, no bundler, no
build step, and no npm. Nothing is fetched from a network: no CDN, no web fonts, no remote
images. That is not minimalism for its own sake — a browser client with a build step is a
second thing to install, version, and break, and this one has to work on a machine where the
operator has installed exactly one thing.

### What guards the app

A local server is still a server, and a page in the same browser is still a stranger. The
defences, each doing one job:

- **Loopback only.** The bind address is hardcoded `127.0.0.1`; only the port is configurable.
- **A per-session token.** Minted at bind time, substituted into the page as it is served,
  compared with a constant-time comparison, and required on every `/api/*` route. It is
  deliberately never written to disk, so a leaked state file hands nobody the ability to drive
  the API.
- **Host and Origin guards.** A present `Host` must be a loopback name on the bound port, and a
  present `Origin` or `Referer` must be this exact server. The Host check is what closes DNS
  rebinding: a page that resolves its own domain to 127.0.0.1 becomes same-origin, and a
  same-origin GET sends no Origin header at all, so the origin guard alone would never fire.
- **A command allowlist.** Unknown commands, unknown argument names, missing required
  arguments, and asking for both `--plan` and `--yes` are all refused before the parser sees
  them.
- **Two independent argv-injection defences.** Every positional value is refused if it begins
  with `-`, and argv is emitted as `<command> <options> <flags> -- <positionals>` so that
  everything after `--` is read as a value. Either one is sufficient; both are there because a
  positional that argparse accepts as a flag can change the approval gate and the target at
  the same time.
- **Absolute paths only.** Every `path` positional must be a full path, so a relative or
  Windows-spelled one can never land a brain inside the server's own working directory. A
  Windows spelling is converted through `wslpath` before the argv exists, and one that cannot
  be converted is refused.
- **A write lock held only for writes.** The server lock is taken for argv containing `--yes`,
  so two writes never interleave on one brain, while reads keep answering — a status probe
  must not queue behind an install.
- **A capped request body, and headers on every response.** Bodies over 256 KB are refused, as
  are a bad `Content-Length`, a non-UTF-8 body, and a body that is not a JSON object. Every
  response carries a content security policy that permits scripts only from this origin
  (`script-src 'self'` — an origin restriction, not a path one), and the only route serving
  script is `/static`. Plus `nosniff`, `DENY`, `no-referrer`, and `no-store`.

A handler fault returns an envelope rather than a stack trace, and never takes the server down.

## Skill sync model

The bundled skills have a single source, `src/marketing_os/assets/skills/`. Runtime
copies are generated into `RUNTIME_DIRS` (`.claude/skills/` for Claude Code, `.agents/skills/`
for Codex), are ignored by git, and are compared by a content hash of the source tree
(`tree_hash`), not by timestamps. `mos skills sync` plans the difference and applies it only
under `--yes`. A directory the tooling did not generate is treated as unrecognized and is
never overwritten; the plan reports it as a conflict instead. Installs are recorded in a
manifest so a later run can tell a stale generated copy from a hand-authored one. See
[the agent runtime contract](agent-runtime-contract.md) for the full rules.

## Local state

Machine-local runtime state lives below `.mos/local/` inside a brain and is never committed;
the project-level runtime manifest, the document catalogue, and the scan cache that lets a
status check skip re-reading unchanged documents are written there.

The rest lives in `~/.marketing-os/`, outside every brain, because the local app has to work
before any brain exists:

- `runtime-manifest.json` — what `mos install` wired into the home directory's runtime dirs.
- `ui.json` — the running app's pid, port, url, root, and start time, written `0600`. The
  session token is deliberately not in it.
- `brains.json` — the brains the app knows about, so the switcher can list them without
  sweeping the filesystem. Capped at two hundred entries, oldest first out.
- `ui.log` — where a detached server's stdout and stderr go.
- `ui-opened` — the marker that says the one-time open has already been attempted. Only
  `mos install` writes it; `mos ui` never does.

That marker is what makes a first successful `mos install --yes` start the app and open a
browser at most once. It is written *before* the start, not after, so a crash mid-start cannot
turn the open into a loop on every later install. The cost of that ordering is that the one
attempt can be spent without opening anything: the install path demands a detached server, so
on a platform with no `os.fork` it returns `ui-needs-foreground` with `running: false` and no
later install retries — the operator starts the app with `mos ui`. `--no-ui` opts out
entirely, a browser that will not open degrades to `browser: "none"` (the caller's cue to
print the URL), and installing never fails over any of it.

`MOS_HOME` relocates this directory, which is what keeps tests off a real home directory. It
moves the app's four files only: `mos install` always targets `Path.home()`, so its manifest
stays at `~/.marketing-os/runtime-manifest.json` whatever `MOS_HOME` says.

## Two thin loaders

`AGENTS.md` and `CLAUDE.md` in a business repository are intentionally thin runtime loaders.
Both point to `BRAIN.md`, preventing two instruction systems from drifting apart.

## Memory layers

- `BRAIN.md` is the shared operating contract.
- `CONTEXT.md` records the current focus and constraints.
- `business/` is the sole source of business truth.
- `knowledge/` contains immutable sources and maintainable synthesized knowledge.
- Execution work goes to the matching dated content, campaign, report, or output folder.
- `archive/` is excluded from ordinary grounding.
