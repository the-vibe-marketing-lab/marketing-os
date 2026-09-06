# Changelog

All notable changes to marketing-os are recorded here. Versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **A prompt to paste into Claude Code.** The Structure and Findings cards, and the
  next-action row behind "Ask Claude Code to fix it", carry a copyable prompt built from
  the checker's findings: what is wrong, where, and what to do about each, with the
  brain's own onboard command filled in.
- **The local app wears the Lab's Ember system, and the dashboard is a ledger.** The app
  is branded MarketingOS: a live-text wordmark in Bricolage Grotesque, Figtree for
  everything else, both vendored as woff2 inside the wheel because the page's CSP allows
  same-origin fonts only. Warm dark ground, one Ember object per view, Sun for status,
  hairlines between rows, no card shadows, no gradients, no light theme. The dashboard's
  hero card, two health tiles, checklist card, assistants card and findings card are gone;
  in their place is one column of rows: the next action with its fix, then one row per
  business question showing the first line of the operator's own answer, its state and a
  Change button, then one status row (assistants, structure, answers by count, findings
  with a count that open in place), then how to open the brain in Claude Code with the
  exact lines behind the technical disclosure. A row opens in place into the whole answer
  as prose. Pinned on 2026-09-06: the six answers and four checks (structure,
  assistants, findings, navigation) are one grid of Ember cards, each with a ready or
  needs-you state word and one line, opening in place to its details. The answers are read once per brain through `mos context show` and reach the
  page as text, never markup. The rail carries the brains, Set up a brain (or another),
  the two section links, and Attach a folder beside Refresh; the top bar is drawn only
  below 900px, where it is the drawer's handle. Commands are tiered everyday, maintenance
  and advanced, with advanced folded by default. The wizard's preview tree shows the
  documents a person will open and folds the skills, dot folders and git steps into one
  faint row. The interview shows the answer on file as prose above the box that edits it.
  The token names the contract tests read are unchanged; `--ink-3` sits at Paper 54%
  rather than Ember's 50% because 50% measures under 4.5:1 on two surfaces and the accent
  wash, and accent text on the wash is Ember Bright, which the two affected contrast
  pairs now measure.

### Fixed

- **The mobile drawer contains focus.** Open, it now puts a scrim over the page, makes the
  page inert so no Tab stop or screen reader lands behind it, closes on a tap outside, and
  closes on Escape from anywhere rather than only while focus was already inside it.
- **The dashboard reads findings to the operator in plain words.** The hero card keyed
  a fixed sentence off the next-action id, so a missing `CONTRACT.md` was announced as
  "files are not where the schema expects them" with a migrate button that could not
  create a file, on every brain alike. It is now built from the worst finding: a missing
  required file previews and applies a scaffold that adds only what is missing; documents
  without a header or links get their own sentence and fix. Findings that share a code
  are one row with a count and a closed list of where, instead of ten copies of the
  checker's terminal message. `FINDING_COPY` in `app.js` carries one sentence and one
  recovery per checker code, and a contract test fails when a code ships without one.
  The word "schema" no longer reaches a reader; GitHub naming and the git setup steps sit
  behind the technical disclosure.
- **`mos doctor` agrees with `mos status` about discovered context.** On a brain whose
  brand, voice, audience, strategy and proof were answered in files of its owner's naming,
  status reported every field complete while doctor, reading the same brain in the same
  second, reported each canonical file as a `missing-file` error and `checks.structure`
  false. The structure check predates discovery and reads directories only. Status now
  hands the context scan it has already run to the findings it has already gathered: a
  `missing-file` whose path is the canonical file of a field discovery resolved becomes a
  `file-discovered` warning carrying that `path` and, as `discovered_path`, the file that
  answered. `checks.structure` and `ok` count only the errors that remain; required files
  that are not context fields (`goals.md`, `roadmap.md`) and fields nothing answered stay
  errors, and a brain with nothing discovered produces byte-identical output. `mos validate`
  is unchanged: it measures the canonical path and still reports it absent.
- **`mos update` recognises a `uv tool install`.** The published package installed with
  `uv tool install marketing-os` came back `unknown-install`, because the detector knew a
  source checkout and pipx only. An install path under `uv/tools/` now reports
  `mode: "uv"` and runs `uv tool upgrade marketing-os`; the pipx branch is the same code
  with a different argv.

## [0.3.0] - 2026-09-02 — Local app

### Added

- **`mos status` finds the context a brain already holds, wherever its owner filed it.** A
  brain that had answered brand, voice, audience and offer at length — in folders of its own
  naming — reported all four missing, and the dashboard then asked its owner to write again
  what he had already written. New module `marketing_os.core.discover`: when a canonical
  context file is missing or still boilerplate, it walks `business/` and `reference/` four
  segments deep and scores every markdown document whose **own name** is one of the words the
  field is known by (`positioning` and `identity` for brand, `tone` and `writing-style` for
  voice, `avatar` and `icp` for audience, `pricing` and `package` for offer). The name is the
  gate; a folder can corroborate it and can never stand in for it, because a folder name is a
  filing decision and says nothing about what any one document inside it contains — a README,
  a research bank or a copyright notice in `business/voice/` is not the voice of the business.
  Navigation and machinery are refused outright rather than marked down: the `_index.md` files
  `mos index sync` writes (read from the schema's own `generated_files` and
  `frontmatter_contract.exempt_names` rather than copied out of them), every other name that is
  somebody's navigation — `README.md`, `index.md`, `log.md`, `_log.md`, `changelog.md`,
  `contributing.md`, `license.md`, `notes.md`, `todo.md` — held in a `NAV_FILES` set that stays
  put when the schema moves, any document carrying the generated-by marker, and any whose
  frontmatter `status` says
  `archived`, `superseded`, `gap` or `placeholder` — which is the lever an operator has over
  discovery, and the way a proof file that exists to record an absence stops being read as
  proof. Everything else is scored on naming, placement and what its frontmatter claims about
  itself, and only a candidate clearing a confidence floor may answer: a best candidate below
  it is discarded rather than settled for, because being told you have answered a question you
  have not is worse than being asked twice. Every rule is a fixed integer and the tie-break is
  total, so the same tree always resolves the same way — no model, no randomness. A substantive
  canonical file short-circuits the scan entirely and is never scored, so a schema-following
  brain resolves exactly as it did before and costs nothing to check. All the unanswered fields
  are resolved in one walk of the tree rather than one walk each; on a 9,000-file brain on a
  mounted Windows filesystem that took the context check from 2.8s to 0.6s. The scan follows
  nothing out of the repository — the two content trees are the only search roots, and a linked
  directory resolving outside the repo is not descended into — so a `vault -> /elsewhere` or an
  `up -> ..` left in the folder can no longer answer for the business with a file that is not
  in it. A file reachable under several names (through a symlink beside its own folder) is
  scored under all of them and reported under the best, so the answer no longer depends on
  where a symlink sorts alphabetically. A scan that hits its budget reports `truncated`, and
  the budget is spent on files that might be answers rather than on every file seen, so an
  exported transcript dumped under `business/` cannot starve the walk before it reaches the
  real one. Status field entries gain `source` (`canonical`, `discovered` or `missing`),
  `discovered_path`, and `truncated`; `path` still means the canonical path, which is where
  `mos context set` writes and what `mos validate` measures. `mos context show` reads the body
  from wherever the answer really is and names that file in `answered_in`, so a discovered
  field can never report answered with nothing to read — and `mos assist` grounds on the
  operator's real words rather than an empty string. The dashboard shows the third state in
  words: a "Found elsewhere" pill, the path it was found in, and a "N found elsewhere" count
  beside the required badge. Documented in
  [docs/json-output-contract.md](docs/json-output-contract.md#context-field).

- **The app has a left sidebar with every brain, and one press switches between them.**
  Brains the operator has — created by the wizard, opened, attached, the folder the server
  was started in, or sitting in the first place (the desktop) — are listed by name in a
  `~/.marketing-os/brains.json` registry (`marketing_os.ui.registry`, written atomically,
  never a home-folder sweep). The open brain carries a "current" marker in words as well as
  colour; a brain whose folder is gone stays listed, greyed, tagged "not found" with a Forget;
  one from an older layout is tagged "needs attach" and opens an attach screen that shows
  the real `mos attach --plan` before "Attach this brain" runs `--yes` and switches to it.
  Switching loads `GET /api/state?path=<root>` in one request, moves the dashboard, the
  Commands default path and every command target, keeps the choice (session storage plus
  `last_opened` server-side), and announces "Now showing <name>". "Set up another brain"
  and "Attach a folder…" (the operating system's folder window, or step 1's in-page list
  where none can open) live in the same panel. Navigation (Dashboard, Commands) moved off
  the top bar into the sidebar as a vertical tablist; Refresh sits in its footer. Under
  900px the sidebar is a drawer opened by a Menu button (`aria-expanded`, focus in on open,
  Escape and the close button return it), so the 390px screen still has every brain one
  press away; the top bar now carries only that button and the name of the brain on
  screen. New route `POST /api/brains` `{op: remember|forget, path}`; `/api/state` carries
  `brains`.
- **Step 1 only reports brains in the folder it points at.** The "you already have N
  brains" sweep of every usual place is gone. Whenever the place changes (a chip, the
  exact-location field, the folder window, "Put the brain here", or opening the wizard)
  the page looks at that one folder through `POST /api/browse` and shows "Brains already
  in this folder (N)" with one "Open <name>" button each; two with one name are told apart
  by folder name, a brain from an older layout is tagged "needs attach" and still opens, an
  empty folder shows nothing, and a late answer for a place since abandoned is dropped.
  `GET /api/state` scans the first place alone (the desktop, or home without one), once,
  through `brains`; the unread `existing_brains` key is gone, so home-folder scratch
  copies never reach the page and a state request costs one Desktop scan, not two.
- **`scripts/ui_shots.py` no longer litters the home folder.** Its fixture brains are
  scaffolded under a `mos-shots-*` folder in the system temp dir and removed when the run
  ends; screenshots still land in `.mos-shots/`.
- **Step 1 of the app opens the operating system's own folder window.** "Choose a folder…"
  now asks the local server to open the native dialog — Explorer under Windows and WSL
  (PowerShell `FolderBrowserDialog`, paths converted with `wslpath` both ways), Finder on a Mac
  (`osascript`), zenity, kdialog or Tk on Linux — and the chosen folder becomes the place the
  brain goes. A closed window changes nothing. `GET /api/state` reports `picker`; where no
  window can open (headless, SSH, no display) or the one asked for fails, the in-page folder
  list stands in and says why in one sentence. New module `marketing_os.ui.picker`, new route
  `POST /api/pick-folder`.
- **Every brain opens as an Obsidian vault out of the box.** The scaffold now ships a
  `.obsidian/` modelled on the hand-built Vibe Marketing Lab vault: `app.json` (agent-facing
  files excluded from search, new notes default to `knowledge/sources/`), `core-plugins.json`,
  a `hide-machinery` CSS snippet, and three community plugins pre-installed and enabled -
  Iconize 2.14.7, Git File Explorer Colors 1.0.2 and Hide Empty Folders 1.0.0 - each with
  its LICENSE. Excalidraw is recommended as a one-click install instead of bundled, because
  its AGPL-3.0 licence does not belong inside an MIT wheel (and it weighs 8 megabytes); the
  frontmatter contract gains `exempt_suffixes` so `*.excalidraw.md` drawings never trip
  `mos validate --strict`. Folder emojis (💼 business, 📚 knowledge, 📣 campaigns,
  🎬 content, 📦 outputs, 📊 reporting, 🗄️ archive, plus the `business/` and `knowledge/`
  children) come from the Iconize icon map, so folder names on disk stay schema-exact. The
  theme is left on Obsidian's default. The template `.gitignore` keeps the vault config and
  plugins tracked and ignores only per-machine UI state (`workspace*.json`, `.obsidian/cache`,
  `.trash/`). The wheel's package data, the golden tree, the assets contract and the wheel
  smoke all assert the vault ships; `docs/setup-guide.md` gains "Open it in Obsidian".
- **`mos attach <path>` — adopt an existing brain without rewriting it.** A folder that grew
  a brain before this engine — a `.mos/config.yaml` written as YAML, or a `BRAIN.md` beside
  `business/` — was invisible to `status`, `find_root`, the skills and the app, and `onboard`
  refused it as a non-empty folder. `attach` rewrites only `.mos/config.yaml` in the canonical
  JSON form (keeping the old text as `.mos/config.legacy.yaml`), adds only the scaffold files
  the folder lacks (contract documents, required empty directories, runtime skill copies), and
  never creates or overwrites a `business/` or `knowledge/` document; off-schema entries and
  missing required documents are findings that point at `mos migrate --plan`. `--name` and
  `--mode` override what the legacy config says; `--plan`/`--yes` gate it like every other
  mutation, and the envelope is `mos.attach.v1`. The app's folder browser and
  `existing_brains` now surface such folders with `legacy: true` and `attachable: true`
  instead of hiding them, and `attach` is on the `/api/run` allowlist.
- **The app itself: a five-step setup wizard and a dashboard.** `index.html`, `styles.css` and
  `app.js` under `marketing_os/ui/static/` are hand-written vanilla HTML, CSS and JavaScript —
  no framework, no bundler, no build step, no web fonts, no network at runtime. Setup asks one
  thing per screen (folder, who it is for, name, preview, create) in the words a gym owner would
  use: agency mode visibly promises the client list at `business/clients/clients.md`, client mode
  collects the agency name, and step 4 renders the real `--plan` output as a file tree so nothing
  is written before an explicit confirm. The dashboard reads only from `status`, `validate` and
  `doctor` envelopes — health tiles, a context checklist, assistant wiring, every finding, and one
  next action wired to a real command. Every allowlisted command is reachable with its equivalent
  `mos ...` line, mutating ones gated behind a preview. Light and dark via
  `prefers-color-scheme`, responsive to 390px, keyboard operable end to end, and honest loading,
  empty and error states throughout.
- **`mos ui` — the local app.** A localhost server that puts the CLI in a browser for people
  who do not live in a terminal. `mos ui [path]` binds `127.0.0.1`, starts a detached server,
  prints the URL and returns; `mos ui status` and `mos ui stop` manage its lifetime. The
  envelope is `mos.ui.v1` with `running`, `url`, `port`, and `pid` alongside the standard
  fields, and machine-local state lives in `~/.marketing-os/ui.json` so it works before any
  brain exists. A dead pid — or a live pid that no longer holds the port — is reported as not
  running and the stale file is cleaned up.
- **A JSON API that is a client of the CLI, never a second implementation.** `POST /api/run`
  takes `{"command", "args"}`, maps it onto a real `mos` argv, dispatches it through the same
  parser and handlers the terminal uses, and answers `{"envelope", "command_line"}` — the app
  teaches the CLI instead of hiding it. `GET /api/state` reports the folder, whether it is a
  brain, and the current `status` and `doctor` envelopes. The command allowlist is explicit;
  anything else is a 400, and the `--plan`/`--yes` mutation gate is untouched.
- **Session-token security.** A `secrets.token_urlsafe(32)` token is minted per run and injected
  into `index.html` at serve time; every `/api/*` request must present it as `X-MOS-Token` or
  get a 403. Requests carrying a foreign `Origin` or `Referer` are refused, a `Host` header that
  is not a loopback name on the bound port is refused before the page is served — which is what
  closes DNS rebinding, where an attacker domain resolved to `127.0.0.1` becomes same-origin and
  sends no `Origin` at all — static serving rejects traversal, and the token is never written to
  disk.
- **First-install auto-open.** `mos install --yes` opens the app the first time only, tracked by
  a marker in `~/.marketing-os/`. `--no-ui` opts out, and a browser that will not open degrades
  to printing the URL rather than failing the install.
- **`run_argv` seam** in `marketing_os.cli.main`: parse and dispatch an argv list in-process and
  get the envelope back, with nothing written to stdout or stderr.
- **`mos assist` — an opt-in assisted interview, and the engine's one documented exception to
  being model-free.** `mos assist status` reports which agent runtimes on this machine can
  genuinely answer, probing each by actually running it, so a binary that is on `PATH` but
  cannot reply is reported unavailable. `mos assist ask` runs one stateless turn of the context
  interview: the caller holds the conversation and passes it back, the engine keeps no session
  and no state file. It never runs on its own — in the app it fires on an explicit click and
  nothing else, no page load, no timer, no warm-up — and when it does, it starts the `claude` or
  `codex` the operator already installed, on their own subscription and their own tokens, as a
  child process with a fixed argument list and no shell. The prompt travels on stdin, the child's
  output goes to files so it cannot contaminate a `--json` envelope, and the turn is bounded in
  wall clock, in bytes, and at four questions before a draft is compulsory. What comes back is
  untrusted data: it is stripped, length-checked, and returned as a string that never becomes
  markup, a path, or an argument. Nothing that seam produces is written by it — the draft comes
  back as data, and only `mos context set`, under the existing `--plan`/`--yes` gate, writes to
  disk. Every other command in the engine is still deterministic and calls no model, and
  `dependencies = []` still holds: there is no SDK and no HTTP client here. `claude` is the
  runtime this was built and verified against; the `codex` entry follows that tool's documented
  `codex exec` interface and has not been exercised against a real install. The exception is
  written down in [docs/architecture.md](docs/architecture.md) rather than left to be discovered.

### Fixed

- **One unreadable offer file no longer takes down `mos status`.** An offer document saved as
  UTF-16, or round-tripped through a Windows editor, raised `UnicodeDecodeError` out of
  `status`, `doctor`, `context show` and `context set` alike — every command that measures
  context. Completeness now treats a file it cannot read as an unanswered one, everywhere,
  and a leading byte-order mark is consumed rather than counted as content (which had been
  hiding the whole frontmatter block, and with it every rule read from it).
- **A page of `- TODO:` bullets no longer counts as an answer.** `substantive_text` skipped a
  line starting `todo:` but not one starting `- todo:`, so the template convention this repo
  uses for its own stubs was one bullet marker away from reporting a field complete. List,
  numbered, quote and checkbox markers are stripped before the test.
- **Folders excluded from the search are excluded in any spelling.** The exclusion list was
  compared against raw directory names while every other name in the module went through the
  same normaliser, so plural tolerance ran one way only: it helped a folder match a field and
  never helped one get excluded. `archives/`, `Templates/` and `brain-dumps/` were all walked;
  `example`, `sample`, `draft`, `scratch`, `old`, `backup`, `fixture`, `test`, `tmp` and `temp`
  join the list. `normalise` also handles the `-ies` plural (`strategies`, `case-studies`,
  `identities`) and leaves a word ending in a doubled `s` alone.

- **A Windows-spelled path can no longer put a brain inside the app's own folder.** Typed
  into the wizard's exact-location field under WSL, `C:\Users\you\Desktop\foo` reached
  the CLI as a relative path and `onboard --plan` reported it fine, relative to wherever
  `mos ui` was started. Every `path` a page command targets must now be a full path
  (`/api/run` answers `bad-path` otherwise), a Windows spelling is converted with
  `wslpath -u` on the server before dispatch, and step 1 says "That is not a full path"
  for anything else instead of probing it. `GET /api/state?path=` also refuses kernel
  views (`/proc`, `/sys`, `/dev`) and expands only the operator's own `~`.
- **A listed brain whose folder lost its brain no longer renders as healthy.** The sidebar
  greys it, tags it "not a brain" and offers Forget, the way a missing folder is shown.
  `/api/state` `brains` entries carry `is_brain`.
- **Switching to a brain the server refuses moves nothing.** The page used to commit the
  new path and remember it before the server answered, so a folder that had vanished
  since the list was drawn left the app pointed at nothing. The path is now committed
  only once the state comes back; a refusal shows a toast, keeps the open brain open,
  and redraws the list so the row says "not found".
- **`mos attach --yes` keeps every earlier config.** A second attach against a folder whose
  config had changed since the first found `config.legacy.yaml` already there and
  overwrote `.mos/config.yaml` with no backup. The new text now goes to the next free
  `config.legacy.1.yaml`, `config.legacy.2.yaml`, ... first. The plan also names the
  `.gitkeep` apply drops into every directory it makes, client mode with no known agency
  is flagged `legacy-agency-missing`, and a legacy `agency:` line is carried into the new
  config.
- The WSL Desktop fallback prefers the Windows profile named after the login and never
  guesses between several; the native folder window times out after two minutes as a
  cancel (not "no window can open here"), and a second "Attach a folder…" press while one
  is open says so instead of opening the in-page list. Read-only commands no longer wait
  behind a `--yes` on the server lock.

### Changed

- **Switching brains in the local app is roughly eighteen times faster.** On a real brain of
  1,556 markdown documents on a mounted Windows drive, `GET /api/state` went from 28.1
  seconds and 1,370,838 bytes to 1.6 seconds and 59,161. Nothing about what it reports
  changed: the 2,561 findings, their order, and all six resolved context fields are identical
  before and after. Four things did it. Filesystem work is now overlapped
  (`marketing_os.core.parallel`), because on a mount every cost is round-trip latency rather
  than computation — walking 606 folders falls from 2.97 seconds to 0.41 that way. The
  packaged schema is parsed once per process instead of 6,105 times per request. The
  catalogue is built once per validation pass instead of twice, and is cached per document in
  `.mos/local/scan-cache.json` against each file's size and modification time, so an
  unchanged document is never reopened and an edited one always is. And `mos doctor` inside
  the app's state request reuses the status it was just given instead of re-walking the brain
  (`core.status.reuse`), which was half the request on its own. `mos status`, `mos validate`
  and `mos doctor` in the terminal are faster for the same reasons and print exactly what
  they printed before.
- `/api/state` — the page's own shape, not the CLI contract — now carries the first two
  hundred findings with the true `findings_total` and `findings_counts` beside them, errors
  first, and drops the doctor findings and runtimes that duplicate the status envelope's. The
  dashboard states the checker's real count and says how many rows it is not listing.
- Merged the former `setup` subcommand into `mos onboard`. Onboard is now the single command to create or complete a brain (new or existing) — scaffold, git, the context interview (now including strategy), and agency client registration. The `setup` subcommand and its bundled skill are retired; use `mos onboard` and `/mos-onboard` going forward.

## [0.2.0] - 2026-08-20 — Navigation layer

Retrieval in a `mos` brain is now navigation rather than search. The brain declares its own
structure, generates a map of itself, and answers questions from that map instead of reading
every document. Everything below is deterministic and model-free, per the engine contract.

The design follows two 2026 results: Corpus2Skill (arXiv 2604.14572), which found that a tree
of small navigation files beats dense retrieval on the same questions, and "Is Grep All You
Need?" (arXiv 2605.15184), which found that filesystem structure and index files close most of
the remaining gap. Rationale and measurements are in
[docs/knowledge-graph.md](docs/knowledge-graph.md).

### Added

- **Frontmatter contract.** A new `CONTRACT.md` ships in the business template: five required
  keys (`title`, `type`, `description`, `date`, `status`) plus at least one connective key
  (`sources`, `related`, `produced_by`). Deliverables under `content/`, `campaigns/`,
  `reporting/`, and `outputs/` must carry `sources:` — an output with no sources is not
  finished. The contract is published machine-readably in `schema.json` under
  `frontmatter_contract`, so the vocabulary has exactly one definition.
- **`mos index build`** catalogues every document into `.mos/local/catalog.json` — title,
  description, type, status, word count, outgoing links, and which contract keys are present.
- **`mos index sync --plan|--yes`** generates the three-level `_index.md` hierarchy from that
  catalogue. Folders at or below 40 documents list inline; larger ones explode into child
  indexes. Below 25 documents in total only the root index is generated, because a hierarchy
  over a near-empty brain is noise. Generated files carry a do-not-hand-edit marker, and any
  hand-written index of the same name is left untouched with a `hand-written-index` finding.
- **`mos index status`** reports catalogue freshness and the share of documents carrying
  frontmatter, a description, and an outgoing link.
- **`mos related --plan|--yes`** proposes `## Related` blocks for substantial documents that
  link to nothing. Scoring runs over `title` and `description` only, so a long document cannot
  dominate by length, and cross-folder targets are weighted higher because those are the edges
  nothing else supplies. A weak match writes nothing rather than a plausible wrong link.
  Archived, superseded, and raw source material is never a link target.
- **`mos validate --strict`** promotes frontmatter-contract findings to errors for continuous
  integration. New findings: `missing-frontmatter`, `missing-connective-key`,
  `output-without-sources`, `unlinked-document`, `invalid-type`, `invalid-status`.
- **`mos query --grep`** does literal substring lookup with file and line numbers, for URLs,
  names, identifiers, and error strings, where term scoring is the wrong tool.
- A `.gitattributes` in the business template pins line endings, so generated brains never
  produce whole-file diffs from line-ending churn.
- [docs/knowledge-graph.md](docs/knowledge-graph.md) explains why the model-backed graph layer
  stays outside the CLI, with the before-and-after measurements behind that decision.

### Changed

- **`mos query` scores catalogued metadata** — title, description, type, and path — instead of
  reading every document body, so cost no longer grows with document length. Without a
  catalogue it falls back to the body scan and reports which path it took in `source`.
- **`mos query` corpus widened** beyond `business/` and `knowledge/wiki/` to every
  non-archived document, so questions about content, campaigns, reporting, and outputs can be
  answered at all.
- **`mos query` returns `route`** — the chain of `_index.md` files leading to the best
  candidate — alongside `candidates`. Handing the model the branch, not only the leaf, is what
  makes retrieval navigable.
- **`mos validate` checks the frontmatter contract**, as warnings by default so an
  early-stage brain is never blocked, and reports `contract_gaps` in its summary.
- **Business template documents ship contract-compliant.** Every scaffolded document carries
  the frontmatter block with the scaffold date rendered in, so a brain never accumulates a
  backfill. `knowledge/wiki/_index.md` is now a generated navigation file rather than a
  hand-written stub.
- **`BRAIN.md` gained Navigation and Frontmatter contract sections**, and every bundled skill
  now states the contract it must emit. `mos-end` refreshes the map before proposing a commit;
  `mos-start` navigates the hierarchy; `mos-status` reports navigation coverage.
- The dated-folder validators tolerate generated navigation files sitting alongside dated
  artifacts, instead of reporting the map as malformed content.

### Fixed

- **A failed write can no longer empty a document.** `Path.write_text` opens the target for
  truncation and encodes afterwards, so anything that failed in between — text UTF-8 cannot
  represent, a full disk, a process killed mid-write — landed after the document was already
  gone. Every command that rewrites a document in the repository now goes through one
  `atomic_write` helper (encode, write a temporary file beside the target, `fsync`, rename
  over it): `mos context set`, `mos index sync --yes`, `mos related --yes`, and the client
  registry row `mos onboard` inserts. A failed write leaves the original byte for byte and no
  scratch file behind.
- Context readiness (`mos status`) no longer counts a document's frontmatter as operator
  content, which would have reported an untouched template stub as complete.
- `## Related` blocks are written with line endings preserved, so appending four lines
  produces a four-line diff rather than a whole-file one.

## [0.1.0] - 2026-08-19 — Foundation

### Added

- Clean deterministic marketing-os CLI.
- Canonical single-business brain scaffold.
- Shared `mos-onboard`, `mos-start`, and `mos-help` skills for Claude Code and Codex.
- Built out the `docs/` set: architecture, business-repo, and troubleshooting references, plus the documentation index and code-derived contract docs.
- `mos migrate` — model-free routing of off-schema files into the canonical structure: `--plan` diagnoses stray top-level entries, and a `mos.migrate-plan.v1` `--plan-file` is applied atomically (no overwrite, no escaping the repo), plus the `mos-migrate` skill that owns the routing judgement.
