---
name: MarketingOS local app
description: Ember, applied as a SaaS overview shell. Ember is the authority; this file records only what the app adds or maps.
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
  term-bg: "#0d0b0a"
  term-ink: "#faf7f2"
  term-dim: "#8d8a87"
typography:
  display:
    fontFamily: "Bricolage Grotesque, Figtree, system-ui, sans-serif"
    fontSize: "40px"
    fontWeight: 800
    lineHeight: 1.05
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Bricolage Grotesque, Figtree, system-ui, sans-serif"
    fontSize: "32px"
    fontWeight: 800
    lineHeight: 1.1
    letterSpacing: "-0.03em"
  title:
    fontFamily: "Bricolage Grotesque, Figtree, system-ui, sans-serif"
    fontSize: "30px"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  stat:
    fontFamily: "Bricolage Grotesque, Figtree, system-ui, sans-serif"
    fontSize: "28px"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  card-title:
    fontFamily: "Bricolage Grotesque, Figtree, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.02em"
  panel-title:
    fontFamily: "Figtree, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "16px"
    fontWeight: 700
    lineHeight: 1.3
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
    fontSize: "12px"
    fontWeight: 700
    lineHeight: 1.4
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
  topbar-h: "52px"
  sidebar-w: "240px"
  content: "1240px"
  column: "720px"
  gutter: "32px"
  main-pad: "28px 32px 96px"
  rail-pad: "28px 18px 20px"
  panel-pad: "24px"
  tile-pad: "20px"
  strip-gap: "16px"
  ov-gap: "20px"
  row-pad: "14px 0"
  qa-row-pad: "10px 0"
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
  button-icon:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.pill}"
    padding: "6px 12px"
    height: "36px"
  tile:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "20px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.lg}"
    padding: "24px"
  prompt:
    backgroundColor: "{colors.term-bg}"
    textColor: "{colors.term-ink}"
    rounded: "{rounded.md}"
    padding: "14px 16px"
  term:
    backgroundColor: "{colors.term-bg}"
    textColor: "{colors.term-ink}"
    rounded: "{rounded.md}"
    padding: "12px 12px 12px 16px"
  input:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "12px 15px"
  note:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.lg}"
    padding: "16px 18px"
  toast:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "11px 20px"
---

# Design System: MarketingOS local app

Recorded from the built code at commit `0205694` on `ui-rebrand` (the static files are unchanged since `d2e3b79`) (`src/marketing_os/ui/static/styles.css`, `index.html`, `app.js`) and the screenshots at 1440, 1100 and 390. Where this file and the stylesheet disagree, the stylesheet is right.

## Overview

**Creative North Star: "The Overview"**

This app implements **Ember**, The Vibe Marketing Lab's design system. Ember is the authority: `tvml-website-next/public/design.md` for the rules and `tvml-website-next/src/styles/ember.css` for the tokens; when those two disagree the CSS wins. Nothing here overrides Ember. This file records only what the app adds on top of it or how it maps Ember onto its own names.

The app reads as a SaaS project overview, not a landing page. A 240px rail, a 52px app bar on every width, and a content area that runs full width to 1240px, top-aligned. The overview opens with a compact header (eyebrow, business name with a one-word health state beside it, the Lab Rule, a meta line) and the view's one Ember button at the right; then four status tiles; then two columns, 8/4: "Do this next" and "Your answers" at left, "Quick actions", "Assistants" and "Navigation" at right. Panels hold hairline rows, never boxes. The wizard and the interview keep a 720px reading column inside the same shell. Every command line, path and raw envelope lives behind a closed disclosure.

**Key Characteristics:**
- Ember's warm dark ground and Paper text, dark only, no toggle.
- One Ember object per view: the primary button. Every other emphasis is a Paper word; Sun is for "needs you" and nothing else.
- Bricolage Grotesque for the business name, tile values, step and card titles and the wordmark; Figtree for everything else, including panel titles.
- Hairlines, not boxes. Status is a tracked uppercase word, not a capsule.
- Mono inside `code`, `pre`, `.term` and `.row__path` only; never a label, never prose.

## Colors

Ember's warm neutrals and single accent, re-keyed to the app's own semantic names because the static contract tests read `--bg`, `--surface`, `--ink`, `--accent`, `--ok`, `--warn`, `--err` and their `-ink`, `-soft`, `-line` companions from `:root`. Alpha primitives are flattened over Ink so every token is a hex the contrast test can measure.

### Mapping to Ember

| App token | Ember primitive | Note |
|---|---|---|
| `bg`, `term-bg` | Ink | Page ground, input ground, terminal and prompt ground. |
| `surface`, `surface-2`, `surface-3` | Surface, Surface-2, Surface-3 | Tiles and panels; the open rail item; mode-card hover. |
| `line` | Divider | The hairline between rows and under the app bar. |
| `line-strong` | Mist | Tile, panel, card and ghost-button border. |
| `ink`, `ink-2`, `ink-3` | Paper at 100%, 78%, 54% over Ink | Flattened to hex. `term-ink` and `term-dim` repeat `ink` and `ink-3`. |
| `control-line` | Paper at 42% over Ink | Form-control borders and the tile hover border; 3:1 as non-text contrast. |
| `accent`, `accent-hover`, `accent-ink` | Ember, Ember Bright, Ink | Fill, accent text and focus ring, text on the fill. |
| `accent-soft`, `accent-line` | Ember Soft, Ember Line | Flattened over Ink. |
| `warn`, `warn-soft`, `warn-line` | Sun, Sun Soft, Sun Line | Status only. |
| `err`, `err-soft`, `err-line` | Ember Bright, Ember Soft, Ember Line | Ember has no red; error is Ember Bright. |
| `ok`, `ok-soft`, `ok-line` | Paper, and two warm greys | Ember has no green; a finished thing is quiet Paper with Ink on it. |

### Primary
- **Ember** (`accent`): the fill of the one primary button on a view, the Lab Rule under the overview title, the selection colour, the checkbox accent, the indeterminate progress bar, the spinner's leading edge.
- **Ember Bright** (`accent-hover`): links, the focus ring on every control, the input caret, the error colour.

### Neutral
- **Paper** (`ink`): headings, tile values, the to-do title, the answer's name, quick-action labels, the breadcrumb's brain name.
- **Paper 78** (`ink-2`): body copy, the tile line, the answer's first line, secondary-button text, rail items at rest, the "ready" state word.
- **Paper 54** (`ink-3`): eyebrows, help lines, ghost buttons, disclosure summaries, meta, counts, the "optional" state word, the credit. Ember's own text-muted is 50%; the app steps to 54% because 50% measured 4.25:1 on Surface-2 and 4.33:1 on the accent wash.

### Status
- **Sun** (`warn`): the "needs you" health word, the "needs you" state word in tiles and panel heads, warning icons and the "warning" word on a finding row. Never a call to action.
- **Paper** (`ok`): a completed step dot, a done run-step, a done checkbox. Success is not green.

### Named Rules
**The One Ember Object Rule.** A view gets one Ember fill, and it is the primary button. The open brain's "current" marker, the "ready" word and every other emphasis is a Paper word.
**The Ready / Needs-You Rule.** Every fact on the overview resolves to one of two words, typed lowercase: "ready" in Paper 78, "needs you" in Sun. "optional" in Paper 54 is the third, used only for an unanswered optional question. `test_one_status_system_per_fact_on_the_dashboard` pins one status system per fact.
**The No Red, No Green Rule.** Error is Ember Bright (`err`); done is Paper (`ok`). `test_the_mode_consequences_are_not_dressed_as_success` pins that `--ok` never colours a static label.
**The Fifty-Four Rule.** Muted text is Paper at 54%, not Ember's 50%, because every audited pair must clear its ratio. `test_audited_contrast_pairs_clear_aa` measures twenty-one pairs from `:root` on every run: 4.5:1 for `ink-3` on `surface`, `surface-2`, `surface-3`, `bg` and `accent-soft`; `accent-ink` on `accent`; `ink` and `accent-hover` on `accent-soft`; `ink-2` on `surface`; `warn` on `warn-soft`; and 3:1 for `ok-ink` on `ok`, `err-ink` on `err`, `accent` on `surface` and on `accent-soft`, and `control-line` on `surface` and `surface-2`.

## Typography

**Display Font:** Bricolage Grotesque (with Figtree, system-ui)
**Body Font:** Figtree (with system-ui, -apple-system, Segoe UI)
**Mono Font:** the browser's mono stack (ui-monospace, SF Mono, Menlo, Consolas, Liberation Mono)

Both faces are vendored as variable woff2 under `static/fonts/` (SIL OFL 1.1, weight range 400 to 800) because the CSP allows same-origin fonts only. `font-display: swap`.

**Character:** Bricolage carries the name, the numbers and the titles; Figtree does the work, including every panel title on the overview. The eyebrow is Figtree uppercase at 0.14em tracking, typed lowercase in the source and uppercased by CSS. There is no mono label anywhere.

### Hierarchy
- **Display** (800, 40px, 1.05, -0.03em): the page-head title on the interview, attach and commands views; 32px at 640px and below. The interview question is 32px 600.
- **Headline** (800, 32px, 1.1, -0.03em): the business name in the overview header; 28px at 640px and below.
- **Title** (600, 30px, 1.15, -0.02em): wizard step titles; 26px on small screens. The boot title is 26px 600.
- **Stat** (600, 28px, 1.1, -0.02em, tabular): the tile value; 24px at 640px and below.
- **Card title** (600, 20px, 1.25, -0.02em): result and card titles outside a panel.
- **Wordmark** (800, 22px, 1, -0.03em): "MarketingOS" in the rail, live text; the "tvml" monogram in the credit.
- **Panel title** (Figtree 700, 16px, 1.3): every panel head on the overview, and a compact readout's title inside a panel or a to-do row.
- **Body** (400, 18px, 1.6): the base size. 17px at 640px and below. Prose measures 62ch; ledes 56ch.
- **Small** (400 or 700, 15px): the tile line, to-do and answer rows, quick actions, meta, help, buttons, the prompt text.
- **Label** (700, 13px, 0.14em, uppercase): eyebrows, tile labels (12px), group labels, subheads, the rail's "brains" title.
- **Status** (700, 12px, 0.1em, uppercase): `.state`, `.ov-head__health` and `.pill` words; the prompt caption is 13px.
- **Mono** (14px, 1.5; 13px in lists and paths): command lines, paths, raw output.

### Named Rules
**The Mono Is Data Rule.** Mono appears inside `code`, `kbd`, `pre`, `samp`, `.term`, `.row__path`, `.cmd-item__cli`, `.changes`, `.input--mono` and `.boot__detail`: command lines, file paths and raw envelopes. Never a label, a heading or a sentence. The prompt box is prose in Figtree on the terminal ground.
**The Lowercase Eyebrow Rule.** Eyebrows, state words and the health word are typed lowercase in the markup and JavaScript ("agency hq", "needs you", "on file now") and uppercased by the stylesheet.

## Layout

A two-column shell under a sticky 52px app bar: a 240px sticky rail and a main area padded 28px 32px 96px, content top-aligned and capped at 1240px (`--content`). Wizard, interview and attach keep a 720px column (`--column`, `.view--form`) inside the same shell, left-aligned, never centred. When the rail is hidden (boot, fatal) the shell collapses to one column with no empty gutter.

The overview: header, then the status strip (four tiles, 16px gap), then the body grid at 8/4 (`minmax(0, 8fr) minmax(0, 4fr)`, 20px gap, 20px above). Panels stack at 20px inside each column. Rows inside a panel are 14px 0 (to-do), 10px 0 (answers, quick actions) with a Divider hairline below each and one above the list.

Breakpoints: at 1100px and below the body grid drops to one column. At 900px and below the drawer button appears, the rail becomes a fixed panel under the app bar over a scrim, the strip goes 2x2, the commands view stacks, and the answer row drops its first line under the name clamped to two lines. At 640px and below body is 17px, main padding 24px 16px 80px, tiles 16px and panels 18px, icon-button labels become visually hidden, the header actions and to-do actions go full width, and every visible control is 44px tall. At 460px and below the mode cards collapse to a headline and one line.

The wizard footer is sticky at the bottom and the plan summary sticky at the top (`test_the_commit_point_and_the_summary_cannot_scroll_away`).

## Elevation & Depth

Flat. Cards cast no shadow; `--shadow-1/2/3` are `none`. Depth is Surface on Ink and hairlines: Divider between rows, Mist around tiles, panels and the few genuine containers. The app bar sits on Ink at 82% behind `--blur-nav` (saturate 180%, blur 20px). The one shadow in the system is `--shadow-ember` (0 12px 32px rgba(201,100,66,0.4)) on the primary button on hover, with a 3px lift. There is no hero atmosphere in the app.

### Named Rules
**The Hover Only Shadow Rule.** The Ember shadow appears on the primary button on hover and nowhere else. Reduced motion removes both the lift and the shadow.
**The Contained Element Rule.** A panel holds hairline rows. The one contained element it may hold is a prompt box or a terminal block, on the Ink ground with a Mist border; a compact readout sits on the panel with a hairline above it, not in a box.

## Shapes

Ember's radii plus two smaller steps for controls: 8px (`sm`) for browse items and found-path chips; 12px (`md`) for inputs, rail items, command items, the prompt box and the terminal block; 18px (`lg`) for tiles, panels, cards, notes and mode cards; 24px (`xl`) declared, unused; pill for every button, place chip, the copy button and the toast. Quick-action rows and answer heads are square. Nothing else is rounded. The Lab Rule is a 56 by 3px Ember bar, 14px under the overview title, once per page.

## Components

### App bar (`.topbar`, `.crumbs`, `.topbar__brain`, `.crumbs__sep`, `.crumbs__here`, `.topbar__tools`)
52px, sticky, on every width: Ink at 82% behind the nav blur, Divider hairline below, 32px gutters (16px below 900, 12px below 640). Left, the drawer button (below 900 only) and the breadcrumb: brain name in Paper 700 15px, the sprite chevron in `ink-3`, the section name in `ink-3` 700. Right, two ghost icon buttons (Re-check, Open in Claude Code) at 36px, `ink-2` 14px, 4px apart; labels visually hidden below 640 and the buttons grow to 44px.

### Rail (`.sidebar`, `.brand__name`, `.brain__open`, `.sidebar__action`, `.tab`, `.sidebar__foot`, `.credit`)
240px, sticky under the app bar, Ink ground with a Divider right border, padded 28px 18px 20px, sections 28px apart. Wordmark in Bricolage 800 22px. Items are 12px-radius text buttons at 15px 700, 44px tall: rest `ink-2` (tabs `ink-3`), hover Surface and Paper, current Surface-2 and Paper (`aria-current`); the open brain's "current" marker is a Paper word. Tabs are a vertical tablist with their icons hidden. Footer above a hairline: ghost icon buttons in `ink-3` and the credit in `ink-3` 13px with a Bricolage 800 "tvml" monogram. Below 900 the rail is a fixed drawer (Surface, Mist bottom border) under the bar, over an Ink 82% scrim.

### Overview header (`.ov-head`, `.ov-head__row`, `.ov-head__title`, `.ov-head__health`, `.em-rule`, `.page-head__meta`, `.ov-head__actions`)
Flex, bottom-aligned, 24px below. Left: the mode eyebrow (`ink-3`, 13px, 0.14em), the business name in Bricolage 800 32px with the health word beside it on the baseline (12px 700 0.1em uppercase, `ink-2` for "ready", Sun with `--needs` for "needs you"), the Lab Rule 14px under, then the meta line 12px under (`ink-3` 15px, items separated by a middle dot). Right: the one primary button and one secondary beside it. Below 640 both buttons fill the width.

### Status tile (`.strip`, `.tile`, `.tile__label`, `.tile__value`, `.tile__line`, `.state`)
Four peer tiles in a row (2x2 below 900), each a `<button>` that scrolls to its panel: Surface, Mist, 18px radius, 20px padding, no shadow, 6px internal gap. Eyebrow label at 12px, value in Bricolage 600 28px tabular, one `ink-2` 15px line, then the state word. Hover lifts the border to `control-line`; never Ember.

### Panel (`.panel`, `.panel__head`, `.panel__title`, `.panel__end`, `.panel__count`, `.panel__line`, `.panel__more`)
Surface, Mist, 18px radius, 24px padding (18px below 640). Head: title in Figtree 700 16px, right end holds a count in `ink-3` 14px, a state word, or a small ghost button; 14px below. Rows inside are hairline-separated, never boxed. A "nothing to do" panel carries one `ink-2` 15px line. A disclosure at the foot (`.panel__more`) sits 14px under the rows.

### To-do row (`.todos`, `.todo`, `.todo__row`, `.todo__title`, `.todo__sub`, `.todo__action`, `.todo__pointer`, `.todo__readouts`)
One row per finding group, 14px 0, hairline below: a severity icon at 16px (`row__icon--err` Ember Bright, `--warn` Sun), the sentence in Paper 700 15px, the fix line in `ink-3` 14px, and one action at the right (a small secondary button, or a pointer in `ink-3` 14px when the fix is the header button). A preview's readout opens inside the row above its text, and the row resolves in place. Below 640 the action drops under the text, indented 28px.

### Answer row (`.arows`, `.arow`, `.arow__head`, `.arow__name`, `.arow__line`, `.arow__end`, `.arow__body`, `.ledger__prose`)
One row per question. The head is a button, 44px minimum, 10px 0: an 11rem name column in Paper 700 15px, the state word, the first line in `ink-2` 15px clamped to one line; a small ghost "Change" at the right. Opening swaps the line for the prose (62ch, first paragraph in Paper, the rest `ink-2`) with the 0.22s reveal; one open at a time. Below 900 the name and the line stack, the line clamped to two.

### Quick-action row (`.qas`, `.qa`, `.qa__icon`, `.qa__label`, `.qa__go`, `.qa-tech`)
A full-width button, 48px minimum, 10px 0, square, hairline below: sprite icon at 18px in `ink-3`, label in Paper 700 15px, a chevron at 16px in `ink-3`. Hover underlines the label. The "Open in Claude Code" row is a disclosure in the same shape (`.qa-tech`) whose body holds the terminal block.

### Compact readout (`.readout__body`, `resultCard(result, { compact: true })`)
A result rendered inside a panel or a to-do row: hairline above, 14px of padding, title in Figtree 700 16px with one label beside it ("Preview only, nothing written", "Done" or "Needs you" as a `.pill` word), the sentence, the "Show every one" disclosure, then the command line, raw result and elapsed time behind one "Show the command line and the raw result" disclosure. No problem or warning counts and no elapsed time in the head. An apply button follows it as the panel's next Ember object only when the preview replaces the header action.

### Prompt box (`.prompt`, `.prompt__cap`, `.prompt__text`)
The paste-into-Claude-Code block: Ink ground, Mist border, 12px radius, 14px 16px padding, 16px above. Caption in `ink-3` 13px 700 0.1em uppercase; the text in Figtree 15px 1.55, pre-wrapped, in Paper; a copy button row 12px under.

### Terminal block (`.term`, `.term__prompt`, `.term__line`, `.term__copy`, `.term__cap`)
Ink ground, Mist border, 12px radius, mono 14px, a dim prompt glyph and a small pill copy button in `ink-2` 13px. Only inside a disclosure.

### Buttons (`.btn`)
- **Shape:** pill (999px), 44px minimum height, 11px 22px padding, Figtree 700 15px, 1px transparent border, 8px icon gap. Hover changes colour or lifts, never size.
- **Primary** (`.btn--primary`): Ember fill, Ink text. Hover keeps the fill and adds the Ember shadow and 3px lift.
- **Secondary** (`.btn--secondary`): Mist border, `ink-2` text; hover to `control-line` and Paper.
- **Ghost** (`.btn--ghost`): Divider border, `ink-3` text; hover to Mist and Paper.
- **Sizes:** `--lg` 15px 30px at 17px; `--sm` 36px tall, 7px 16px at 14px; `--icon` 8px 14px at 14px (36px and 6px 12px in the app bar).
- **Blocked:** `aria-disabled="true"`, opacity 0.5, still focusable; `test_buttons_are_never_disabled_out_of_the_tab_order` bans the `disabled` property in app.js. `aria-busy` shows a 13px spinner.
- **Focus:** 2px Ember Bright outline, 3px offset, on every control.

### Status words (`.state`, `.ov-head__health`, `.pill`)
Not pills. Inline uppercase words at 12px 700, 0.1em tracking, no capsule. `.state` and the health word: `ink-2` "ready", Sun "needs you", `ink-3` "optional". `.pill` (the class name stays because the harness reads it): `ink-3` by default, `--ok` and `--accent` `ink-2`, `--warn` Sun, `--err` Ember Bright, `--found` a dashed underline for an answer filed away from its canonical place.

### Eyebrow (`.eyebrow`, `.page-head__eyebrow`, `.tile__label`)
Figtree 700 13px, 0.14em, uppercase, `ink-3`; 12px in a tile. `--accent` variant declared, unused.

### Disclosure (`.tech`, `.tech__sum`, `.tech__body`, `.disc`)
A `details` block with a hairline top border, summary at 14px 700 `ink-3` with a 44px hit height, and the sprite's down chevron (`.disc`, 16px, `ink-3`) that rotates 180 degrees over 0.15s when open. Every path, command line, diff and raw envelope lives inside one, closed by default.

### Inputs (`.input`, `.textarea`, `.select`)
Ink ground, `control-line` border, 12px radius, 12px 15px padding, 16px Figtree, Ember Bright caret. Hover borders `ink-3`. Focus: Ember border plus a 2px Ember outline at 0 offset and a 4px `accent-soft` ring. Invalid: Ember Bright border. `--lg` 20px for the business name; `--mono` 14px for the path field.

### Callout (`.note`)
Surface fill, Mist border, 18px radius, 16px 18px padding, icon in `ink-3`, 15px text in `ink-2`. `--accent` is the same Surface and Mist (information is not a second accent); `--warn` and `--err` use the soft and line tokens; `--ok` uses the warm greys.

### Mode option (`.mode__card`)
Ink ground, Mist border, 18px radius, 18px 20px padding. Hover Surface-3; checked Surface with an `ink-2` border and a filled Paper tick. No icon tile.

### Toast (`.toast`)
Fixed bottom centre, Surface-2, Mist border, pill, Paper 15px 700.

### Motion
`--ease` cubic-bezier(0.2, 0, 0, 1); `--fast` 0.15s for hover, border, colour and the chevron; `--base` 0.22s for the answer row's in-place reveal (4px rise and fade); `--lift` translateY(-3px). Busy cues: the spinner and the running step icon rotate at 0.7s, the button spinner at 0.65s, the indeterminate progress bar slides at 1.15s. Under `prefers-reduced-motion: reduce` every transition and transform is removed, the primary hover loses its lift and shadow, each busy cue becomes an opacity pulse between 0.45 and 1 at 1.8s, the progress bar goes full width at 0.35 opacity, and the skip link and toast get static resting places; the open chevron keeps its turn because it is a state.

### Forced colours
Buttons, rail items, command items, tiles, answer heads and quick-action rows gain a 1px ButtonText border; the Lab Rule, the done step dot, the done run-step icon and the done checkbox keep their fills with `forced-color-adjust: none`.

## Do's and Don'ts

### Do:
- **Do** keep the app's own token names in `:root`; the contrast test reads `:root {` up to `@media (prefers-color-scheme: dark)` as the palette and the block after it as the dark overrides, so the empty dark block (carrying only `color-scheme: dark`) must stay.
- **Do** put text on an Ember fill in Ink (`accent-ink`); Paper on Ember is 3.6:1.
- **Do** keep the input focus ring `outline: 2px solid var(--accent)`; `test_the_focus_ring_is_not_the_invisible_soft_accent` fails on `accent-soft` as an outline anywhere.
- **Do** make every target 44px tall (buttons, rail items, summaries, tiles, answer heads) and keep the 2px Ember Bright focus ring on every control.
- **Do** use `ink-3`, not opacity, to make text recede; `test_scaffolding_recedes_in_the_plan_tree` bans `opacity` on faint rows.
- **Do** mark state with a word or a tick as well as colour; the done dot swaps its digit for a tick, the pressed chip gains a filled tick and `aria-pressed`.
- **Do** give every checker code one plain sentence in `FINDING_COPY`, with `{n}` in the `many` form; `test_every_checker_code_has_a_plain_sentence` and `test_the_plain_sentences_carry_a_count_where_more_than_one_can_happen` read the table back against the checker.
- **Do** keep one Ember fill per view and one Lab Rule per page.

### Don't:
- **Don't** use blue, any cool grey, green or a red; Ember bans blue, and the app maps error to Ember Bright and done to Paper.
- **Don't** write `color: #fff;` anywhere; `test_the_dark_palette_never_hard_codes_a_glyph_colour` reads the stylesheet for it and requires `--ok-ink` and `--err-ink`.
- **Don't** show a filesystem path outside `<code>` inside a `.tech` disclosure or an envelope-reported `.row__path`; `test_no_filesystem_path_in_the_markup_a_reader_sees` and `test_no_filesystem_path_is_written_into_the_apps_copy` read index.html and app.js for path shapes.
- **Don't** let the word "schema" reach a reader; `test_the_reader_is_never_told_about_a_schema` reads every string literal and the page's visible text.
- **Don't** write copy that denies a capability the app ships. `test_no_user_facing_copy_denies_a_capability_the_app_ships` matches a grammar, not a list: a bare "no assistant" or "without an agent" bounded by punctuation, "needs no / requires no / uses no <noun>", "never / cannot / does not need, use, open, touch, ask or call a <noun>", "nothing is <invented>", and "never / won't <verb>", for each capability whose evidence is in app.js.
- **Don't** put a card around a section, a card inside a panel, or a shadow on anything but the primary button's hover.
- **Don't** put metadata in a capsule; a status word is text. Pills are for buttons, place chips, the copy button and the toast.
- **Don't** use mono outside `code`, `pre`, `.term` and `.row__path` (and their list forms), and never as a label; the prompt box is prose.
- **Don't** add a light theme, a theme toggle, a gradient, a glow or a hero atmosphere; this app has none.
- **Don't** set `.disabled = true` on a button; use `aria-disabled`.
- **Don't** use em dashes, hype vocabulary or third-person brand voice in interface copy.
