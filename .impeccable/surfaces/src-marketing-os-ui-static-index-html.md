---
version: 1
slug: "src-marketing-os-ui-static-index-html"
primary_target: "src/marketing_os/ui/static/index.html"
related_targets: ["src/marketing_os/ui/static/app.js","src/marketing_os/ui/static/styles.css"]
---

# Surface brief: the local app (all views; the dashboard leads)

Scope: src/marketing_os/ui/static (index.html, app.js, styles.css). Mode: Operate on every view.

Audience and job: a marketer who has never opened a terminal, creating and maintaining a business brain. Task: see the brain's health at a glance, take the one next action, read and change answers, open the brain in Claude Code. The CLI stays one closed disclosure away.

Chosen direction (pinned by the product owner on 2026-09-06: "a dashboard, not a landing page; same colours; decide from Mobbin"): Ember world unchanged (tvml-website-next public/design.md, src/styles/ember.css; dark only). Dashboard structure: the SaaS project-overview shell seen on Vercel, Supabase and Cloudflare overview pages on Mobbin, with HoneyBook's KPI strip and Remote's things-to-do plus quick-actions columns. References: https://mobbin.com/screens/d9ffa644-353c-41e4-b614-24319c8e8354 (Vercel), https://mobbin.com/screens/2e0ffd2d-c588-4513-bd84-d3effa2e31ed (Supabase), https://mobbin.com/screens/5f8e667f-9ad8-4d84-adc2-a4df5241c6f9 (Cloudflare), https://mobbin.com/screens/45bc05e0-e55f-4da9-a6b0-67ea0661d47e (HoneyBook), https://mobbin.com/screens/11d6ea57-d47c-4e09-bb9c-cd0001338e14 (Remote).

Composition: persistent 240px rail; a slim app bar on every width carrying the brain name as a breadcrumb and two ghost utilities; a full-width content area (up to 1240px, 32px gutters, top-aligned, never a centred 720px column); a compact page header with the business name, mode, a one-word health state and the single Ember action at the right; a four-tile status strip (Answers, Structure, Assistants, Findings) with one number and one line each; a two-column body (8/4): left "Do this next" as a things-to-do list with a fix per row and the copyable Claude Code prompt, then "Your answers" as a dense expandable list; right "Quick actions", "Assistants" and "Navigation" panels. Memorable moment: the status strip reading green-to-Sun at a glance, and a to-do row resolving in place.

Untouched: preview-then-apply contract and copy, every command the UI runs, the interview questions, the assist cost sentence pinned by tests, accessibility scaffolding, static contract tests, FINDING_COPY and the prompt box.

Anti-goals: light theme, toggle, any blue, cards inside cards, pills for metadata, gradients or shadows beyond the one hero atmosphere, mono outside code and terminal blocks, a second Ember object on the page.

Constraints: vanilla HTML/CSS/JS, no build step, CSP same-origin fonts, code-led build. Unresolved: whether the status tiles should carry sparklines once history exists (no history today; none invented).
