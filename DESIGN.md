---
name: MarketingOS local app
description: Ember, applied to one ledger of the operator's own words. Ember is the authority; this file records only what the app adds or maps.
colors:
  bg: "#0d0b0a"
  surface: "#1a1614"
  surface-2: "#241e1b"
  surface-3: "#201a17"
  line: "#241f1c"
  line-strong: "#2c2622"
  control-line: "#716e6b"
  ink: "#faf7f2"
  ink-2: "#c6c3bf"
  ink-3: "#8d8a87"
  accent: "#c96442"
  accent-hover: "#e2794f"
  accent-ink: "#0d0b0a"
  accent-soft: "#2b1913"
  accent-line: "#49271c"
  ok: "#faf7f2"
  ok-ink: "#0d0b0a"
  ok-soft: "#201e1d"
  ok-line: "#383534"
  warn: "#f4c24b"
  warn-soft: "#2d2513"
  warn-line: "#57461f"
  err: "#e2794f"
  err-ink: "#0d0b0a"
  err-soft: "#2b1913"
  err-line: "#49271c"
typography:
  display:
    fontFamily: "Bricolage Grotesque, Figtree, system-ui, sans-serif"
    fontSize: "40px"
    fontWeight: 800
    lineHeight: 1.05
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Bricolage Grotesque, Figtree, system-ui, sans-serif"
    fontSize: "30px"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Bricolage Grotesque, Figtree, system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Figtree, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: 1.6
  small:
    fontFamily: "Figtree, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Figtree, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0.14em"
  status:
    fontFamily: "Figtree, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    letterSpacing: "0.1em"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace"
    fontSize: "14px"
    lineHeight: 1.5
rounded:
  sm: "8px"
  md: "12px"
  lg: "18px"
  xl: "24px"
  pill: "999px"
spacing:
  hairline-row: "22px 0"
  row-gap: "8px 24px"
  page-head-gap: "40px"
  main-pad: "56px 40px 120px"
  sidebar-w: "240px"
  column: "720px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.pill}"
    padding: "11px 22px"
    height: "44px"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.pill}"
    padding: "11px 22px"
    height: "44px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-3}"
    rounded: "{rounded.pill}"
    padding: "11px 22px"
    height: "44px"
  input:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "12px 15px"
  ledger-row:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "0"
    padding: "22px 0"
  term:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "12px 12px 12px 16px"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.lg}"
    padding: "24px"
  toast:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "11px 20px"
---

# Design System: MarketingOS local app

Recorded from the built code at commit `a99e4c5` (`src/marketing_os/ui/static/styles.css`, `index.html`, `app.js`). Where this file and the stylesheet disagree, the stylesheet is right.

## Overview

**Creative North Star: "The Ledger"**

This app implements **Ember**, The Vibe Marketing Lab's design system. Ember is the authority: `tvml-website-next/public/design.md` for the rules and `tvml-website-next/src/styles/ember.css` for the tokens, and when those two disagree the CSS wins. Nothing here overrides Ember. This file records only what the app adds on top of it or how it maps Ember onto its own names.

The app's one idea is the ledger: a single 720px column that reads top to bottom, the next action first, then ten peer cards (six answers in the operator's own words, four checks) each with a state word and one line, opening in place to their details, then how to open the brain in Claude Code. Cards are Ember's card atom and never nest; there are no tiles and no shadows. The rail on the left (240px) carries the MarketingOS wordmark, the brains, two section tabs and a quiet footer credit. Every command line, path and raw envelope lives behind a closed disclosure.

**Key Characteristics:**
- Ember's warm dark ground and Paper text, dark only, no toggle.
- One Ember object per view: the primary button. Everything else is Paper at three strengths.
- Bricolage Grotesque only for the business name, step titles and the wordmark; Figtree for everything else.
- Hairlines, not boxes. Status is a tracked uppercase word, not a pill.
- Mono for command lines, paths and raw output only; never for prose.

## Colors

Ember's warm neutrals and single accent, re-keyed to the app's semantic names because the static contract tests read `--bg`, `--surface`, `--ink`, `--accent`, `--ok`, `--warn`, `--err` and their `-ink`, `-soft`, `-line` companions from `:root`.

### Mapping to Ember

| App token | Ember primitive | Note |
|---|---|---|
| `bg` | Ink | Page ground, terminal ground, input ground. |
| `surface`, `surface-2`, `surface-3` | Surface, Surface-2, Surface-3 | Panels, the open brain row, hover. |
| `line` | Divider | The hairline between rows. |
| `line-strong` | Mist | The card and ghost-button border. |
| `ink`, `ink-2`, `ink-3` | Paper at 100%, 78%, 54% over Ink | Flattened to hex so the contrast test can measure them. |
| `control-line` | Paper at 42% over Ink | Form-control borders; needs 3:1 as non-text contrast. |
| `accent`, `accent-hover`, `accent-ink` | Ember, Ember Bright, Ink | Fill, accent text and focus, text on the fill. |
| `accent-soft`, `accent-line` | Ember Soft, Ember Line | Flattened over Ink. |
| `warn`, `warn-soft`, `warn-line` | Sun, Sun Soft, Sun Line | Status only. |
| `err`, `err-soft`, `err-line` | Ember Bright, Ember Soft, Ember Line | Ember has no red; error is Ember Bright. |
| `ok`, `ok-soft`, `ok-line` | Paper, and two warm greys | Ember has no green; a finished thing is quiet Paper with Ink on it. |

### Primary
- **Ember** (`accent`): the fill of the one primary button on a view, the Lab Rule under the dashboard title, the selection colour, the checkbox accent, the progress bar.
- **Ember Bright** (`accent-hover`): links, the focus ring on every control, the input caret, and the error colour.

### Neutral
- **Paper** (`ink`): headings, the operator's own words in a row, values in the status row, labels.
- **Paper 78** (`ink-2`): body copy, secondary button text, rail items at rest.
- **Paper 54** (`ink-3`): eyebrows, state words, help lines, ghost buttons, disclosure summaries, the credit. Ember's own text-muted is 50%; the app steps to 54% because 50% measured 4.25:1 on Surface-2 and 4.33:1 on the accent wash.

### Status
- **Sun** (`warn`): "needed" state words, the "needs attach" and "warning" words, the out-of-place count in the status row. Never a call to action.
- **Paper** (`ok`): a completed step dot, a done checkbox, an "answered" tick. Success is not green.

### Named Rules
**The One Ember Object Rule.** A view gets one Ember fill, and it is the primary button. The open brain marker, the "current" tag and every other emphasis is a Paper word.
**The No Red, No Green Rule.** Error is Ember Bright (`err`); done is Paper (`ok`). `test_the_mode_consequences_are_not_dressed_as_success` pins that `--ok` never colours a static label.
**The Fifty-Four Rule.** Muted text is Paper at 54%, not Ember's 50%, because every audited pair must clear 4.5:1. `test_audited_contrast_pairs_clear_aa` measures twenty pairs from `:root` on every run.

## Typography

**Display Font:** Bricolage Grotesque (with Figtree, system-ui)
**Body Font:** Figtree (with system-ui, -apple-system, Segoe UI)
**Mono Font:** the browser's mono stack (ui-monospace, SF Mono, Menlo, Consolas, Liberation Mono)

Both faces are vendored as variable woff2 under `static/fonts/` (SIL OFL 1.1) because the CSP allows same-origin fonts only. Weight range 400 to 800 on both.

**Character:** Bricolage carries the business name and nothing else of note; Figtree does the work. The eyebrow is Figtree uppercase at 0.14em tracking, typed lowercase in the source and uppercased by CSS. There is no mono label anywhere.

### Hierarchy
- **Display** (800, 40px, 1.05, -0.03em): the page-head title, which is the business name on the dashboard. 32px at 640px and below.
- **Headline** (600, 30px, 1.15, -0.02em): wizard step titles. 26px on small screens. The interview question is 32px 600.
- **Title** (600, 22px, 1.25, -0.02em): the next-action title in the ledger; 20px for result and card titles; 26px for the boot title.
- **Wordmark** (800, 22px, 1, -0.03em): "MarketingOS" in the rail, live text.
- **Body** (400, 18px, 1.6): the base size and the first line of every answer row. 17px at 640px and below. Prose measures 62ch; ledes 56ch.
- **Small** (400 or 700, 15px): labels, help, meta, rail items, buttons.
- **Label** (700, 13px, 0.14em, uppercase): eyebrows, group labels, subheads, the rail's "brains" title.
- **Status** (700, 12 to 13px, 0.1em, uppercase): the `.pill` and `.ledger__state` words.
- **Mono** (14px, 1.5; 13px in lists): command lines, paths, raw output.

### Named Rules
**The Mono Is Data Rule.** Mono appears inside `code`, `kbd`, `pre`, `samp`, `.term`, `.row__path`, `.cmd-item__cli`, `.changes`, `.input--mono` and `.boot__detail`: command lines, file paths and raw envelopes. Never a label, a heading or a sentence.
**The Lowercase Eyebrow Rule.** Eyebrows are typed lowercase in the markup and JavaScript ("agency hq", "on file now") and uppercased by the stylesheet.

## Layout

A two-column shell: a 240px sticky rail and a main area padded 56px 40px 120px. Views are centred at 720px (`--column`); the Commands view widens to 1000px with a 17rem sticky command list beside the panel. When the rail is hidden (boot, fatal) the shell collapses to one column with no empty gutter.

The ledger row is a three-column grid, 164px label, fluid body, auto end column, 22px vertical padding, hairline below. At 900px and below the topbar appears (56px, sticky), the rail becomes a fixed drawer under it, and the row drops its label onto its own line. At 640px and below the body drops to 17px, main padding to 24px 16px 80px, and icon-button labels become visually hidden. At 460px and below the mode cards collapse to a headline and one line.

The wizard footer is sticky at the bottom and the plan summary sticky at the top, so the commit point and the count never scroll away (`test_the_commit_point_and_the_summary_cannot_scroll_away`).

## Elevation & Depth

Flat. Cards cast no shadow; `--shadow-1/2/3` are `none`. Depth is Surface tones on Ink and hairlines: Divider between rows, Mist around the few genuine containers. The one shadow in the system is `--shadow-ember` (0 12px 32px rgba(201,100,66,0.4)) on the primary button on hover, with a 3px lift. Inputs and the accent fill stay flat.

### Named Rules
**The Hover Only Shadow Rule.** The Ember shadow appears on the primary button on hover and nowhere else. Reduced motion removes both the lift and the shadow.

## Shapes

Ember's radii, plus two smaller steps the app needs for controls: 8px (`sm`) for browse items, paths and chips' inner boxes; 12px (`md`) for inputs, rail items, command items and the terminal block; 18px (`lg`) for the few cards, notes and the assist panel; 24px (`xl`) declared, unused in the rebuild; pill for every button, chip, tag and the toast. Nothing else is rounded. The Lab Rule is a 56 by 3px Ember bar, 18px under the dashboard title, once per page.

## Components

### App bar (`.topbar`, `.crumbs`, `.topbar__brain`, `.crumbs__here`, `.topbar__tools`)
52px, sticky, on every width: Ink at 82% behind `--blur-nav`, hairline below, 32px gutters (16px below 900). Left, the drawer button (below 900) and the breadcrumb: brain name in Paper 700 15px, the sprite chevron, the section in `ink-3`. Right, two ghost icon buttons (Re-check, Open in Claude Code) at 36px, labels visually hidden below 640.

### Status tile (`.strip`, `.tile`, `.tile__label`, `.tile__value`, `.tile__line`, `.state`)
Four peer tiles in a row (2x2 below 900), each a `<button>` to its panel: Ember card (Surface, Mist, 18px radius, 20px padding, no shadow), eyebrow label, value in Bricolage 600 28px tabular, one `ink-2` 15px line, then the state word (`.state`: `ink-2` "ready", Sun "needs you", `ink-3` "optional"; typed lowercase, uppercased at 0.1em). Hover lifts the border to `control-line`; never Ember.

### Panel (`.panel`, `.panel__head`, `.panel__title`, `.panel__end`, `.todos`, `.arows`, `.qas`)
Ember's card with a head: title in Figtree 700 16px, an optional count or ghost action at the right. Rows inside are hairline-separated, never boxed: to-do rows (severity icon, sentence, fix line, one secondary action), answer rows (name, state word, first line clamped to one line, ghost Change; the head is a button and opening swaps the line for the prose, one open at a time, Escape closes) and quick-action rows (sprite icon, label, chevron). The prompt box and the terminal blocks are the one contained element a panel may hold. Layout: 8/4 columns at 1100px and up, one column below; 20px gaps.

### The next-action row (`.next__title`, `.next__body`, `.next__actions`)
Bricolage 600 22px title, `ink-3` 15px body at 56ch, then the view's one primary button and a ghost beside it.

### Buttons (`.btn`)
- **Shape:** pill (999px), 44px minimum height, 11px 22px padding, Figtree 700 15px, 1px transparent border.
- **Primary** (`.btn--primary`): Ember fill, Ink text. Hover keeps the fill and adds the Ember shadow and 3px lift. Never changes size.
- **Secondary** (`.btn--secondary`): Mist border, `ink-2` text; hover borders `control-line` and lifts text to Paper.
- **Ghost** (`.btn--ghost`): Divider border, `ink-3` text; hover to Mist and Paper.
- **Sizes:** `--lg` 15px 30px at 17px; `--sm` 36px tall at 14px; `--icon` 8px 14px at 14px.
- **Blocked:** `aria-disabled="true"`, opacity 0.5, still focusable. `test_buttons_are_never_disabled_out_of_the_tab_order` bans the `disabled` property in app.js.
- **Focus:** 2px Ember Bright outline, 3px offset, on every control.

### Status words (`.pill`)
Not pills. Inline uppercase words at 12px 700, 0.1em tracking, no capsule, `ink-3` by default. `--ok` and `--accent` are `ink-2` (the open brain's "current" marker is a Paper word), `--warn` Sun, `--err` Ember Bright. The class name stays because the test harness reads it.

### Eyebrow (`.eyebrow`, `.page-head__eyebrow`)
Figtree 700 13px, 0.14em, uppercase, `ink-3`. `--accent` variant declared, unused.

### Lab Rule (`.em-rule`)
56 by 3px Ember bar under the dashboard title. Never full width, never twice.

### Technical disclosure (`.tech`, `.tech__sum`, `.disc`)
A `details` block with a hairline top border, summary at 14px 700 `ink-3` with a 44px hit height, and the sprite's chevron (`.disc`, 16px) that rotates 180 degrees when open. Every path, command line, diff and raw envelope lives inside one, closed by default; `test_no_filesystem_path_in_default_visible_copy` enforces it.

### Terminal block (`.term`, `.term__prompt`, `.term__line`, `.term__copy`)
Ink ground, Mist border, 12px radius, mono 14px, a dim prompt glyph and a small pill copy button. Only inside a disclosure.

### Inputs (`.input`, `.textarea`, `.select`)
Ink ground, `control-line` border (3:1), 12px radius, 12px 15px padding, 16px Figtree, Ember Bright caret. Hover borders `ink-3`. Focus: Ember border plus a 2px Ember outline and a 4px `accent-soft` ring; `test_the_focus_ring_is_not_the_invisible_soft_accent` pins the solid outline. Invalid: Ember Bright border. `--lg` 20px for the business name; `--mono` 14px for the path field.

### Rail (`.sidebar`, `.brand__name`, `.brain__open`, `.tab`, `.credit`)
Ink ground with a Divider right border, 28px 18px 20px padding. Items are 12px-radius text buttons at 15px 700: rest `ink-2` (tabs `ink-3`), hover Surface and Paper, current Surface-2 and Paper (`aria-current`, pinned by test). Tabs are a vertical `tablist`. Footer: ghost icon buttons and the credit in `ink-3` 13px with a Bricolage 800 "tvml" monogram.

### Callout (`.note`)
Surface fill, Mist border, 18px radius, 16px 18px padding, icon in `ink-3`. `--accent` is the same Surface and Mist (information is not a second accent); `--warn` and `--err` use the soft and line tokens; `--ok` uses the warm greys.

### Card (`.card`)
Surface fill, Mist border, 18px radius, 24px padding, no shadow. Used for results, previews and the assist panel; the ledger, the interview and the command panel sit on the ground instead.

### Mode option (`.mode__card`)
Ink ground, Mist border, 18px radius. Hover Surface-3; checked Surface with an `ink-2` border and a filled Paper tick. No icon tile.

### Toast (`.toast`)
Fixed bottom centre, Surface-2, Mist border, pill, Paper 15px 700.

### Motion
`--ease` cubic-bezier(0.2, 0, 0, 1); `--fast` 0.15s for hover, focus and the chevron; `--base` 0.22s for the in-place reveal. Busy cues: the spinner and the step icon rotate at 0.7s, the indeterminate progress bar slides at 1.15s. Under `prefers-reduced-motion` every transform and transition is removed, the primary hover loses its lift and shadow, and each busy cue becomes an opacity pulse at 1.8s; the open chevron keeps its turn because it is a state.

### Forced colours
Buttons, rail items and the card head gain a ButtonText border; the rule and the done marks keep their fills with `forced-color-adjust: none`.

## Do's and Don'ts

### Do:
- **Do** keep the app's own token names in `:root`; the contrast test parses `:root {` up to `@media (prefers-color-scheme: dark)` and the empty dark block must stay for that parser.
- **Do** use `ink-3` (#8d8a87), not opacity, to make text recede; `test_scaffolding_recedes_in_the_plan_tree` bans `opacity` on faint rows.
- **Do** put text on an Ember fill in Ink (`accent-ink`); Paper on Ember is 3.6:1.
- **Do** make every target 44px tall (buttons, rail items, summaries, place chips) and keep the 2px Ember Bright focus ring on every control.
- **Do** mark state with a word or a tick as well as colour: the done dot swaps its digit for a tick, the pressed chip gains a filled tick and `aria-pressed`.
- **Do** keep one Ember fill per view and one Lab Rule per page.

### Don't:
- **Don't** use blue, any cool grey, green or a red; Ember bans blue, and the app maps error to Ember Bright and done to Paper.
- **Don't** put a card around a section, a border to repair hierarchy, or a shadow on anything but the primary button's hover.
- **Don't** put metadata in a capsule; a status word is text. Pills are for buttons, place chips and the toast.
- **Don't** use mono outside code, terminal blocks, paths and raw output, and never as a label.
- **Don't** add a light theme, a theme toggle, a gradient, a glow or a hero atmosphere; this app has none and Ember allows only one atmosphere per page.
- **Don't** hard-code `color: #fff` or set `.disabled = true`; both are pinned by tests.
- **Don't** show a filesystem path, command line or raw envelope outside a `.tech` disclosure.
- **Don't** use em dashes, hype vocabulary or third-person brand voice in interface copy.
