# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: a marketer, agency owner or small-business operator (a gym owner is the canonical
example) who has installed marketing-os to give an AI assistant a working model of their
business. They have never opened a terminal and do not intend to. They arrive from the
install flow with a browser tab that opened itself, or from a member post in The Vibe
Marketing Lab, and they want a "business brain" that exists, is filled in, and is being read
by Claude Code or Codex.

Secondary: the same person's more technical peers, and Richard himself, who live in Claude
Code and use the app to check a brain, switch between brains, or run one command without
remembering its flags. They must never be blocked, but they are not who the surface is
designed for. Confirmed 2026-09-05: marketer first; every command line, path and raw result
stays available behind a closed-by-default technical disclosure.

## Product Purpose

marketing-os (`mos`) creates and maintains a file-based marketing brain: one folder of
ordinary markdown files holding brand, voice, audience, offer, strategy and proof, plus the
skills that let Claude Code and Codex read and act on it. The local app (`mos ui`, served on
127.0.0.1:4321 from inside the Python wheel) is the main place people create their brains.
Success is a person ending up with a validated brain on disk, filled in their own words, and
knowing how to open it in their assistant, without typing a command.

## Positioning

The brain is plain files the operator owns, in a folder they can see, that any assistant
can read. The CLI owns filesystem facts, validation and runtime wiring; agents own the
interview, judgment and writing. The app is a client of that CLI, never a second
implementation: every action is a real `mos` command, previewed before it writes. Nothing is
invented by the app and nothing is written until the operator confirms. That is the claim a
hosted "AI marketing platform" cannot make.

## Operating Context

- Installed with pipx or uv; the app opens once after the first `mos install`, then from
  `mos ui` or the `/mos-*` skills inside Claude Code and Codex.
- Brains are registered in `~/.marketing-os/brains.json`; the app switches between them.
- Three brain modes: in-house (one brand), agency (adds a client list), client (one brain
  per client, names its agency).
- The interview fills six context fields, four required; answers can be drafted by the
  operator's own Claude Code or Codex on their own account, one question at a time.
- Validation, doctor and skill sync run on demand and after every change; findings come
  back as coded envelopes the app translates into plain sentences.
- Obsidian and git are set up inside every brain as machinery the operator is not expected
  to touch.
- Richard's users meet this app through The Vibe Marketing Lab, a Skool community; MarketingOS
  is the free installable tier of that value ladder.

## Capabilities and Constraints

- Vanilla HTML, CSS and JavaScript. No framework, no bundler, no build step, no Node.
  `dependencies = []` stays empty. Served by the Python standard library.
- Content Security Policy: `script-src 'self'`, `font-src 'self'`. Fonts must ship inside
  the static folder; no external hosts. Decided 2026-09-05: vendor General Sans, Inter and
  JetBrains Mono as woff2 in the wheel (licence check before shipping: Fontshare ITF Free
  Font Licence for General Sans, SIL OFL for the other two).
- Localhost only, session token on every API call, explicit command allowlist, no shell.
- Mutation gating: every writing command is previewed with `--plan` and applied with `--yes`
  after an explicit confirm. The UI must keep that visible.
- Tested by static contract tests that read `app.js`, `index.html` and `styles.css`
  directly: no inline script, no markup sinks, no filesystem path in default-visible copy,
  audited contrast pairs, no copy that denies a capability the app ships, one plain sentence
  per checker code. Any rebrand must keep those passing.
- Python 3.10+, ruff at line-length 100, full pytest suite green, six-cell CI matrix
  including Windows.
- Terminology: brain, mode (in-house, agency, client), context fields ("Your brand", "How
  you sound", "Who you are talking to", "What you sell", "Where you are going", "Your
  proof"), assistant (never "runtime" or "agent runtime" to a reader), findings, the check,
  the technical disclosure. "Schema" never reaches a reader.

## Brand Commitments

- The visual system is **Ember**, the Lab's third identity and the one that ships today.
  Source of truth: `tvml-website-next/public/design.md` (served at
  thevibemarketinglab.com/design.md) and the tokens in `tvml-website-next/src/styles/ember.css`.
  When the two disagree, the CSS is right. The v2.1 guidelines in the Lab brain
  (`business/brand/guidelines/brand-guidelines.md`: Lab Blue #3E5FFF, General Sans, Inter,
  JetBrains Mono) are retired and must not be used.
- Ember tokens: Ink #0d0b0a (page ground, brown-black), Surface #1a1614, Surface-2 #241e1b,
  Surface-3 #201a17, Paper #faf7f2 (text), Ember #c96442 (the one accent: primary button,
  rule, one emphasis per surface), Ember Bright #e2794f (accent text, hover, focus ring),
  Ember Soft / Ember Line (soft fill and accent border), Sun #f4c24b (status and highlight
  only, never a second call to action), Mist #2c2622 (card border), Divider #241f1c.
  Semantic roles: text-primary, text-body (Paper 78%), text-muted (50%), text-subtle (32%),
  text-on-accent (Ink on Ember; Paper on Ember fails AA at button sizes).
- Typography: Bricolage Grotesque 800 and 600 for display, Figtree 400 to 800 for body,
  labels, buttons and interface. No monospace face on an Ember surface; the old mono label
  became Figtree uppercase at 0.14em tracking. Body 18px, small 15px, eyebrow 13px.
- Shape and depth: radius 18px cards, 24px largest surfaces, pill buttons; nothing else
  rounded. Cards cast no shadow. The one ornament is the Lab Rule (56 by 3px Ember bar).
  One atmosphere per page (a blurred Ember radial behind the hero). No gradients, glows,
  grids, glass or texture beyond those two. No pulsing, looping or self-scrolling motion.
- Dark only on the web. No light theme, no theme toggle. A paper variant exists for
  newsletter and print only.
- Icons: one pack, 24px canvas, 1.5px stroke, round joins and caps, currentColor. Never in
  tinted tiles, never emoji.
- Confirmed 2026-09-05: the app is branded MarketingOS, set as a wordmark in Bricolage
  Grotesque 800 with the wordmark tracking. The Vibe Marketing Lab appears only as a quiet
  credit, in the footer form the site uses (monogram, year, place).
- Fonts are vendored in the wheel (decided 2026-09-05): Bricolage Grotesque and Figtree are
  SIL Open Font Licence faces on Google Fonts; download the latin woff2 files into the static
  folder because the app's CSP allows same-origin fonts only.
- Voice: Richard talking to a peer, first person, Australian English, sentence case for every
  heading and button, eyebrows typed lowercase, no em dashes, no hype or corporate
  vocabulary, "state the gap out loud".
- Open decision for the app: Ember has no monospace face, but the app shows command lines
  and file paths behind the technical disclosure. Proposed: the browser's mono stack inside
  code and terminal blocks only, as the blog template already does for code blocks.

## Evidence on Hand

- Two real brains on this machine: Flowstate (agency) and the-vibe-marketing-lab (in-house),
  registered in `~/.marketing-os/brains.json`.
- The 2026-09-05 audit and screenshots (technical 14/20, heuristics 21/40) with prioritised
  findings; the P0 copy fixes shipped in PR #11.
- No logo file, no font files, no product screenshots or sample assistant output exist yet.
  Future work must not fabricate testimonials, member counts or sample outputs presented as
  real.

## Product Principles

1. The operator sees their business, not the container. Answers, proof and what the
   assistant produces come before structure, wiring and findings.
2. Preview, then apply. Every write is shown first and confirmed once; that contract is
   visible on the surface.
3. One thing per surface. The next action is the hero; everything else recedes or folds.
4. Teach the terminal without making anyone use it. The exact command line is always one
   disclosure away and never in the way.
5. Plain words for every finding. A code without a sentence is a bug.

## Accessibility & Inclusion

WCAG 2.2 AA is the floor and is already met for contrast, focus and landmarks; keep it
through any retheme. Mobile targets at 44px, drawer containment, forced-colours support and
respect for the reader's default font size are the known gaps to close.
