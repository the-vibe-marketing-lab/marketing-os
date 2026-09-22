---
title: Document contract
type: reference
description: The frontmatter and linking contract every document in this brain follows, so navigation stays cheap and nothing becomes unreachable.
date: {{TODAY}}
status: active
related:
  - BRAIN.md
---

# Document contract

Retrieval in this brain is navigation, not search. An agent reads a small `_index.md`,
chooses a branch, and opens one or two documents. That only works while every document
declares what it is and what it connects to. This file is that declaration, and
`mos validate` enforces it.

## The block

Every document under `business/`, `knowledge/`, `content/`, `campaigns/`, `reporting/`,
and `outputs/` opens with this block:

```yaml
---
title: Human-readable name
type: business | knowledge | source | decision | content | campaign | report | output | reference
description: One sentence saying what this holds and when to read it.
date: YYYY-MM-DD
status: draft | active | archived | superseded
---
```

`description` is the highest-leverage field in the repository. Every index entry, every
routing decision, and every `## Related` link is built from it. A document with no
description is invisible to navigation even though it sits on disk.

## Connective keys

The five keys above are not enough on their own. Add at least one of these:

- `sources:` — the material this was built from. Backward edge.
  **Mandatory for anything under `content/`, `campaigns/`, `reporting/`, and `outputs/`:
  an output with no sources is not finished.**
- `related:` — lateral links to sibling documents. Cross-folder links are worth more than
  same-folder ones, because those are the connections nothing else supplies.
- `produced_by:` — the skill or command that generated the file. This turns every skill
  into a hub: "show me everything `mos-think` has produced" becomes one search.

## Type vocabulary

Types are checkable because they map onto the folders:

| Folder | Type |
| --- | --- |
| `business/` | `business` |
| `business/decisions/` | `decision` |
| `knowledge/sources/` | `source` |
| `knowledge/wiki/` | `knowledge` |
| `content/` | `content` |
| `campaigns/` | `campaign` |
| `reporting/` | `report` |
| `outputs/` | `output` |
| navigation and meta files | `reference` |

## Related blocks

A substantial document ends with a `## Related` block of three to five links:

```markdown
## Related

- [[business/strategy/strategy.md]] — where the business plays and how it wins
- [[knowledge/wiki/positioning.md]] — the positioning research this rests on
```

Never link into `archive/`, or into anything marked `status: archived` or
`status: superseded`. Linking live work to dead work adds edges and destroys navigation.

## Exempt files

`BRAIN.md`, `CONTEXT.md`, `README.md`, `AGENTS.md`, `CLAUDE.md`, this file, and any
`_index.md` or `_log.md` are structural. They carry no contract block and never receive a
`## Related` block. The same goes for `*.excalidraw.md` drawings, whose body belongs to
Excalidraw rather than to this contract.

## Who enforces this

- `mos validate .` reports contract gaps as warnings; `mos validate . --strict` makes them
  errors for continuous integration.
- `mos index build .` catalogues every document; `mos index sync . --yes` regenerates the
  `_index.md` hierarchy from that catalogue.
- `mos related . --yes` proposes `## Related` blocks for substantial documents that have none.

The rule that matters most: **skills and commands that write files here emit the contract
block themselves.** Fixing the writer is worth more than fixing a hundred documents by hand.
