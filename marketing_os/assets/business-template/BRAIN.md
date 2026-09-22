# {{BUSINESS_NAME}} Marketing Brain

This file is the canonical operating contract for Claude Code and Codex.

## Grounding order

Before producing work:

1. Read `CONTEXT.md` for the current focus, desired outcome, and constraints.
2. Read only the relevant truth under `business/`.
3. Read relevant synthesized knowledge under `knowledge/wiki/`.
4. Retrieve related prior work only when it materially improves the task.

## Routing

- Business identity, audience, offers, strategy, proof, and operations belong in `business/`.
- Immutable source material belongs in `knowledge/sources/YYYY/MM/YYYY-MM-DD-source/`.
- Reusable synthesized knowledge belongs in `knowledge/wiki/`.
- Organic deliverables belong in `content/YYYY/MM/YYYY-MM-DD-topic/<channel>/`.
- Coordinated or paid work belongs in `campaigns/YYYY/MM/YYYY-MM-DD-campaign/<platform>/`.
- Performance reports belong in `reporting/YYYY/QN/YYYY-MM/`.
- Work with no better destination belongs in `outputs/YYYY/MM/YYYY-MM-DD-slug/`.
- Retired material belongs in `archive/` and must not be used for ordinary grounding.

## Navigation

Retrieval here is navigation, not blind search. Read `_index.md` at the level you need,
choose a branch from its one-line summaries, then open the two or three documents that
matter. `mos query "<question>" . --json` returns both the candidate documents and the
index chain to walk.

- `mos index build .` catalogues every document.
- `mos index sync . --yes` regenerates the `_index.md` hierarchy from that catalogue.
- `mos related . --yes` proposes `## Related` blocks for substantial documents that have none.

Generated index files carry a do-not-hand-edit marker. Edit the documents; regenerate the map.

## Frontmatter contract

Every document you write under `business/`, `knowledge/`, `content/`, `campaigns/`,
`reporting/`, or `outputs/` opens with the contract block defined in `CONTRACT.md`:
`title`, `type`, `description`, `date`, `status`, plus at least one connective key
(`sources`, `related`, or `produced_by`).

- `description` is one sentence and is what every index and link is built from.
- Anything under `content/`, `campaigns/`, `reporting/`, or `outputs/` must carry
  `sources:`. An output with no sources is not finished.
- `BRAIN.md`, `CONTEXT.md`, `README.md`, `AGENTS.md`, `CLAUDE.md`, `CONTRACT.md`, and any
  `_index.md` or `_log.md` are structural and exempt, as are `*.excalidraw.md` drawings.

Emit the block as you write the file. `mos validate .` reports gaps; `--strict` fails on them.

## Invariants

- `business/` is the sole source of business truth. Never create a parallel identity layer.
- Living business documents keep stable filenames and are edited in place.
- Execution artifacts use dated folders.
- Sources are immutable after capture; wiki pages may be improved.
- Never overwrite an existing business file during setup or repair.
- Never store secrets, credentials, raw customer exports, or runtime-local state in tracked files.

## Approval gates

Ask before publishing, spending, contacting customers, mutating external accounts, deleting
files, or performing any destructive operation.
