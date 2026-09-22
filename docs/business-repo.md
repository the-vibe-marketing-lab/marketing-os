# Business-Repo Architecture

`mos onboard` creates one canonical marketing brain:

```text
my-business/
|-- BRAIN.md
|-- CONTEXT.md
|-- CONTRACT.md
|-- AGENTS.md
|-- CLAUDE.md
|-- README.md
|-- .gitignore
|-- .gitattributes
|-- .mos/
|   |-- config.yaml
|   `-- local/                         generated and ignored
|-- .obsidian/                         vault config: 21 files, tracked
|-- .claude/skills/                    generated and ignored
|-- .agents/skills/                    generated and ignored
|-- business/
|   |-- brand/{brand.md,voice.md,assets/}
|   |-- audience/primary.md
|   |-- offers/<offer-slug>/offer.md
|   |-- strategy/{strategy.md,goals.md,roadmap.md}
|   |-- proof/testimonials.md
|   |-- operations/
|   |-- clients/clients.md             agency mode only, from the mode overlay
|   `-- decisions/YYYY/MM/YYYY-MM-DD-slug/decision.md
|-- knowledge/
|   |-- sources/YYYY/MM/YYYY-MM-DD-source/
|   `-- wiki/{_index.md,_log.md}
|-- content/YYYY/MM/YYYY-MM-DD-topic/<channel>/
|-- campaigns/YYYY/MM/YYYY-MM-DD-campaign/<platform>/
|-- reporting/YYYY/QN/YYYY-MM/
|-- outputs/YYYY/MM/YYYY-MM-DD-slug/
`-- archive/
```

The required directories, the seventeen required files and the allowed top-level paths above
come from one file, `src/marketing_os/assets/schema.json`, and `mos validate` reports any
deviation from those three. Not everything in the tree is in it. `.gitattributes` and the
`.obsidian/` vault come from the business template
(`src/marketing_os/assets/business-template/`); `business/clients/clients.md` comes from the
agency mode overlay; `.claude/skills/` and `.agents/skills/` come from `RUNTIME_DIRS` in
`core/skills.py`. None of those four appear in schema.json.

Two of its other keys are read elsewhere. `context_files` names the file backing each context
field — every one except `offer`, which is a folder of offers rather than a single file and
is carried in `core/status.py` instead, so a reader editing schema.json to change or add a
context field will not find offer there. `generated_files` is what keeps a generated
`_index.md` from being reported as an unknown top-level path. One key is not a validation rule
at all: `excluded_from_grounding` (currently just `archive/`) is read by the catalogue build,
by `mos query`'s no-catalogue body scan, and by `mos related` when it decides what may be
linked to — but never by `mos validate`, so nothing is reported against it.

The `.obsidian/` tree is tracked rather than ignored, so a brain opens as a configured vault
on any machine that clones it; see the Obsidian section of [setup-guide.md](setup-guide.md).

One inconsistency to know about before you create a top-level `reference/` folder. Context
discovery searches `business/` and `reference/` for answers a field already has (see
`core/discover.py` in [architecture.md](architecture.md)), but `reference` is not in
`allowed_top_level`, so `mos validate` reports the same folder as an `unknown-top-level`
warning. Both halves are true today. Keep business truth under `business/` if you want a
clean validate.

## Memory layers

- `BRAIN.md` is the shared operating contract.
- `CONTEXT.md` records the current focus and constraints.
- `business/` is the sole source of business truth.
- `knowledge/` contains immutable sources and maintainable synthesized knowledge.
- Execution work goes to the matching dated content, campaign, report, or output folder.
- `archive/` is excluded from ordinary grounding.

## business/operations/

`business/operations/` is a living reference for how the marketing function runs day to
day: standard operating procedures, channel checklists, publishing and approval workflows,
posting cadences, and the inventory of tools and accounts the business depends on. It ships
as a bare directory with no required files, so add plain-language pages as the practices
become real. These are living files on stable paths, edited in place rather than dated;
keep credentials and secrets out and record only the process itself.

## business/decisions/

`business/decisions/` is the per-event record of marketing decisions: each entry captures
what was decided, the reasoning, the alternatives considered, and the expected outcome, so
later work can trace why the current strategy exists. Unlike `operations/`, this tree is
dated. Each decision lives at `business/decisions/YYYY/MM/YYYY-MM-DD-slug/decision.md`, and
`mos validate` checks the folder names against the dated grammar below. Keep this business
record distinct from the engine repository's own `docs/` and `decisions/`, which document
the tooling rather than a business.

## .mos/config.yaml

`mos onboard` and `mos attach` write the repository marker to `.mos/config.yaml`. Despite the
`.yaml` extension the file currently holds JSON, and the tooling reads it back with a JSON
parser (`json.loads` in `read_config`); YAML is a superset of JSON, so a strict JSON document
still parses. `mos onboard` emits sorted keys, for example an agency HQ:

```json
{
  "business_name": "My Business",
  "mode": "agency",
  "schema": "mos.business-repo.v1",
  "schema_version": 1
}
```

Client repos additionally carry an `agency` key. Repos created before modes existed omit
`mode` entirely and read as in-house (see Modes below).

`mos status`, `mos validate`, and `mos doctor` read `.mos/config.yaml` at exactly the path
they are given. They do not walk up, so run them from the repository root or pass it
explicitly — pointed at `business/` inside a healthy brain, `mos status` reports
`not-marketing-os`. What they do check is that `schema` and `schema_version` match the packaged
schema; a missing, unparseable, or schema-mismatched file makes the repository read as absent
or invalid.

`mos statusline`, `mos ingest`, `mos think`, `mos context`, and `mos assist` do walk up, via
`find_root` in `core/schema.py`, so those work from anywhere inside a brain.

## Modes

`mos onboard --mode` records how the brain is shaped in an additive `mode` field (the schema
version stays 1):

- **in-house** — one brand you run yourself; knowledge is global to the brand.
- **agency** — you serve clients. The agency HQ repo carries a client registry at
  `business/clients/clients.md` (pointers only, never client work), scaffolded from the
  agency mode overlay. Each client gets its own repo via
  `mos onboard --mode client --agency "<name>" --hq "<agency-hq-path>"`, which appends a row
  to that registry. Separate repos because the repo is the access boundary.
- **client** — the brain for one agency client; the config also records `agency`.

Agency is the only mode with an overlay. `assets/mode-overlays/agency/` holds exactly one
file, the client registry; in-house and client brains get the base template unchanged. That is
why an agency HQ built from the tree at the top of this page alone would fail validation —
`clients/clients.md` comes from the overlay, not the template.

Read semantics are centralized in `repo_mode()` (`core/schema.py`): a missing `mode` is
treated as in-house with a `missing-mode` warning (legacy repos), while an unrecognized
value raises `invalid-mode` and fails closed — structure is then not judged at all, rather
than judged against a mode nobody understands. `mos validate` requires the registry in agency
mode (`missing-client-registry`) and warns if an in-house or client repo holds a
`business/clients/` folder (`unexpected-clients-folder`), with one exception: a legacy repo
that has no `mode` key but does carry a real registry file gets `set-mode-agency` instead,
which guides the upgrade rather than asserting the repo is in-house. `mos onboard` without
`--mode` returns a `choose-mode` handoff instead of guessing: its `reason` carries the whole
question for an agent to relay. One wrinkle to read past, as in the `absent` state — that
reason still ends "re-run **setup** with --mode <choice>", naming a command retired when
`setup` merged into `mos onboard`. Read it as `mos onboard`.

## The navigation layer

A brain is only as useful as the speed at which an agent finds the right document in it. Two
2026 results shape how that works here. Corpus2Skill (arXiv 2604.14572) showed that compiling
a corpus into a tree of small navigation files beats dense retrieval on the same questions —
Token F1 0.460 against 0.363 — because the hierarchy, not an embedding index, is the
interface. "Is Grep All You Need?" (arXiv 2605.15184) showed that with a decent harness,
filesystem navigation and literal search close most of the remaining gap. An agent working in
a `mos` brain already has that harness. What it needs is a map.

Three mechanisms make one:

1. **The frontmatter contract** in `CONTRACT.md`. Five keys plus a connective key on every
   document. `description` is the field everything else is built from.
2. **The `_index.md` hierarchy**, generated by `mos index sync`. Root names the folders; each
   folder index lists its groups or documents with one-line summaries; large folders explode
   into child indexes so no navigation file grows past the point of being read.
3. **`## Related` blocks**, proposed by `mos related`. Term overlap across titles and
   descriptions, weighted toward cross-folder targets, with a floor below which nothing is
   written.

The order matters. In a corpus that reached 1,177 documents without a contract, only 2% of
documents carried an outgoing link, and a deeper extraction pass over the same corpus moved
that number by zero — a tool can only record a relationship a document actually states.
Adding the contract and the hierarchy took it to 64%. Starting a brain with the contract in
place is how you never pay that bill: every document is born compliant, and no backfill is
ever needed.

`mos validate` reports gaps as warnings, `--strict` makes them errors, and
`mos index status` reports the coverage percentages. The graph layer that sat on top of that
corpus — model-backed entity extraction and community detection — is deliberately not part of
the CLI; see [knowledge-graph.md](knowledge-graph.md).

## Dated-folder grammar

Execution trees use dated folders so artifacts sort chronologically and validate
deterministically. `mos validate` enforces the exact names:

- Execution dirs (`content/`, `campaigns/`, `outputs/`, `business/decisions/`, and
  `knowledge/sources/`) nest as `YYYY/MM/YYYY-MM-DD-slug/`. The year is four digits, the
  month is `01`-`12`, and the leaf is a `YYYY-MM-DD` date followed by a lowercase hyphenated
  slug (`a-z`, `0-9`, and single hyphens between segments), for example
  `content/2026/07/2026-07-18-launch-recap/`.
- Reporting uses `reporting/YYYY/QN/YYYY-MM/` instead: a four-digit year, a quarter
  `Q1`-`Q4`, then a `YYYY-MM` month, for example `reporting/2026/Q3/2026-07/`.

The leaf check is a shape check, not a calendar one: the month and day inside the leaf name
are matched as two digits each, so `2026-99-99-launch` passes. It is the enclosing `YYYY/MM/`
folders that carry the real month range. The check exists to keep artifacts sorting and
validating deterministically, not to catch a typo in a date.

Three file names are skipped by the checker — `.gitkeep`, `_index.md`, and `_log.md` — so an
empty scaffolded tree passes and a generated navigation file sitting beside dated folders is
not read as malformed content. Any folder that breaks the grammar surfaces as an
`invalid-year`, `invalid-month`, `invalid-dated-artifact`, `invalid-quarter`, or
`invalid-report-month` finding.

## File lifecycle

Living business files retain stable paths and are edited in place. Execution artifacts use
dated folders. `mos onboard` and `mos attach` create missing generated files but never replace
an existing business or knowledge file — the scaffold skips any destination that is already
there — so either is safe to re-run to recreate something genuinely missing. The one file
attach does replace is `.mos/config.yaml`, which it rewrites in canonical JSON after keeping
the old text as `.mos/config.legacy.yaml`.
