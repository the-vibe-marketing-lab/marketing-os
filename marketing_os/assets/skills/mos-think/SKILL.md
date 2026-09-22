---
name: mos-think
description: Research a marketing question from repository truth, decide with the operator, and codify the decision as durable memory.
---

# Think

Turn uncertainty into evidence, a decision, and — only when useful — durable business memory.

## How to run this skill (interaction contract)

Thinking ends in durable business memory, so run it as an interactive flow, not a batch job:

- Ground in evidence first, then bring the operator a clear recommendation — but the decision is
  theirs. Ask them to accept, revise, or defer, and wait, before you write anything.
- Separate sourced fact from your own inference so they can judge it honestly.
- Codify only after explicit approval; publishing, spend, and customer contact stay
  operator-gated even once the decision is recorded.

## Ground

Start from the grounded handoff:

```bash
mos think "<topic>" . --json
```

Read only the files it lists as context paths — the operating contract, strategy, and the
top-scoring corpus documents. For follow-up retrieval on a specific question, use:

```bash
mos query "<question>" . --json
```

Use local repository evidence first. Do not expect unshipped fields, and do not read
`archive/` for ordinary grounding.

## Decide

State the question, the realistic options, the evidence for each, the tradeoffs, your
confidence, and a single clear recommendation. Separate sourced fact from inference. Ask the
operator to accept, revise, or defer before creating any durable record.

## Codify

Only after approval, write the decision as a schema-conformant dated artifact:

```
business/decisions/YYYY/MM/YYYY-MM-DD-<slug>/decision.md
```

Use today's date and a lowercase hyphenated slug. Record the question, the decision, the
rationale, the evidence, the alternatives rejected, and a revisit-when trigger. Then update the
relevant wiki page and `CONTEXT.md` if the current focus changed.

Verify the write:

```bash
mos validate . --json
```

Publishing, spend, customer contact, and destructive operations remain operator-gated. Do not
turn early exploration into permanent truth without an explicit decision.

## Document contract

Every file you write under `business/`, `knowledge/`, `content/`, `campaigns/`, `reporting/`,
or `outputs/` opens with the frontmatter block defined in the repository's `CONTRACT.md`:
`title`, `type`, `description`, `date`, `status`, plus at least one of `sources`, `related`,
or `produced_by`. Deliverables must carry `sources:` — an output with no sources is not
finished. Emit the block as you write the file; never leave it for a later pass.
