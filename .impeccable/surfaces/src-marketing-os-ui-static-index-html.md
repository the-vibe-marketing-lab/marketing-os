---
version: 1
slug: "src-marketing-os-ui-static-index-html"
primary_target: "src/marketing_os/ui/static/index.html"
related_targets: ["src/marketing_os/ui/static/app.js","src/marketing_os/ui/static/styles.css"]
---

# Surface brief: the local app (all views; the dashboard leads)

Scope: src/marketing_os/ui/static (index.html, app.js, styles.css). Mode: Operate on every view.

Audience and job: a marketer who has never opened a terminal, creating and maintaining a business brain. Task: see the business in their own words, take the one next action, open the brain in Claude Code. The CLI stays one closed disclosure away.

Chosen direction: Ember world (tvml-website-next public/design.md, src/styles/ember.css; dark only). Dashboard structure: The Ledger. Business name in Bricolage Grotesque 800, mode as a lowercase eyebrow, one Ember next-action row with its fix, then one grid of ten peer cards (six answers, then Structure, Assistants, Findings, Navigation), each an Ember card with a name, a ready / needs-you state word and one line, opening in place to the full answer or the check's rows with one ghost action, a closing "Open this brain in Claude Code" row with the start line behind the disclosure. Cards only in that grid, never nested, no shadows; hairline dividers elsewhere. Pinned by the product owner on 2026-09-06: cards with a pass/fail state. Wordmark "MarketingOS" live text in the rail; "tvml" footer credit. Memorable moment: a card opening in place into the operator's own words.

Structural calls in scope: desktop topbar removed at 900px and up; drawer becomes the rail; health tiles and assistants card merge into the status row; Commands tiered everyday / maintenance / advanced with everyday reachable from the ledger; wizard step 4 tree collapsed to the operator's documents; interview answer as prose, headings stripped; "Set up a brain" when no brains exist.

Untouched: preview-then-apply contract and copy, every command the UI runs, the interview questions, the assist cost sentence pinned by tests, accessibility scaffolding, static contract tests.

Anti-goals: light theme, toggle, any blue, cards around sections, pills for metadata, gradients or shadows beyond the one hero atmosphere, mono outside code and terminal blocks.

Constraints: vanilla HTML/CSS/JS, no build step, CSP same-origin fonts (Bricolage Grotesque and Figtree vendored as latin woff2 under static/fonts), code-led build. Unresolved: whether answer rows show a last-changed date from git.
