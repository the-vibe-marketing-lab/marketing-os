"""Contract tests for the three shipped static assets.

These are sensors for rules that were violated once and must not come back: the CSP
promise, the no-markup-from-envelopes promise, the aria-disabled promise, and — the one
that needed real arithmetic rather than an assertion — the contrast of every token pair
the round-2 accessibility audit measured, in both palettes.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple

import pytest

from marketing_os.core import assist as assist_engine
from marketing_os.core import graphlint, skills, status, validation
from marketing_os.ui.server import static_root

STATIC = static_root()
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")


# --- the page cannot smuggle script or markup ---------------------------------------


def test_no_inline_script_survives_the_csp() -> None:
    """script-src 'self' means every script is a real file under /static."""
    body = re.sub(r"<!--.*?-->", "", HTML, flags=re.S)
    tags = re.findall(r"<script\b[^>]*>", body)
    assert tags == ['<script src="/static/app.js">'], tags


@pytest.mark.parametrize(
    "sink",
    ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"],
)
def test_no_markup_sink_in_the_renderer(sink: str) -> None:
    """Envelope values reach the DOM as text or not at all."""
    assert sink not in JS


def test_the_header_comment_does_not_overclaim() -> None:
    """It used to say 'Nothing is invented', which was false: a third of the copy is ours."""
    assert "Nothing is invented" not in JS
    assert "authored copy" in JS
    assert "heroPlan" in JS.split("*/", 1)[0]


# --- keyboard and assistive technology ----------------------------------------------


def test_buttons_are_never_disabled_out_of_the_tab_order() -> None:
    """Disabling a focused button drops focus to <body>; aria-disabled does not."""
    assert not re.search(r"\.disabled\s*=", JS), "use setBlocked()/aria-disabled instead"
    assert 'setAttribute("aria-disabled"' in JS


def test_tabs_have_a_tablist_and_the_panels_are_focusable() -> None:
    assert 'role="tablist"' in HTML
    assert HTML.count('role="tabpanel" tabindex="0"') == 2


def test_the_sidebar_is_one_labelled_navigation_landmark() -> None:
    """The brains, the section tabs and Refresh sit in one <nav> with a name; the
    tablist keeps its own role inside it, and the old top-bar strip is gone."""
    nav = re.search(r'<nav class="sidebar" id="sidebar"[^>]*>', HTML)
    assert nav is not None
    assert 'aria-label="Brains and sections"' in nav.group(0)
    sidebar = HTML.split('<nav class="sidebar"', 1)[1].split("</nav>", 1)[0]
    for needle in ('id="brains"', 'role="tablist"', 'id="btn-refresh"', 'id="btn-new-brain"',
                   'id="btn-attach-folder"'):
        assert needle in sidebar, needle
    assert 'aria-orientation="vertical"' in sidebar
    assert "Set up another brain" in sidebar and "Attach a folder&hellip;" in sidebar
    topbar = HTML.split('<header class="topbar"', 1)[1].split("</header>", 1)[0]
    assert 'role="tablist"' not in topbar and 'id="btn-refresh"' not in topbar
    assert 'id="topbar-brain"' in topbar
    # The list is refilled whole on every change; a live region would read the lot.
    brains = re.search(r'<ul class="brains"[^>]*>', HTML)
    assert brains is not None and "aria-live" not in brains.group(0)


def test_the_menu_button_declares_the_drawer_it_controls() -> None:
    menu = re.search(r'<button[^>]*id="btn-menu"[^>]*>', HTML)
    assert menu is not None
    assert 'aria-expanded="false"' in menu.group(0)
    assert 'aria-controls="sidebar"' in menu.group(0)
    assert 'id="btn-drawer-close"' in HTML
    # Escape closes, focus goes in on open and back to the button on close.
    section = _js_section("var drawer = { open: false };", "function renderTopbarName()")
    assert '$("btn-drawer-close").focus();' in section
    assert '$("btn-menu").focus();' in section
    assert 'event.key !== "Escape"' in section
    assert ".sidebar.sidebar--open" in CSS
    assert "@media (max-width: 900px)" in CSS


def test_the_open_brain_is_marked_in_words_and_switching_is_one_request() -> None:
    """The marker is a word as well as a colour; missing folders are tagged and can be
    forgotten; names on the buttons, paths in their titles; one state request per switch."""
    section = JS.split("function renderSidebar()", 1)[1].split("\n  }\n", 1)[0]
    assert 'text: "current"' in section
    assert 'text: "not found"' in section
    assert 'text: "needs attach"' in section
    assert 'text: "Forget"' in section
    assert "title: brain.path" in section
    assert '"aria-current": isActive ? "true" : null' in section
    assert ".brain__open[aria-current=\"true\"]" in CSS
    switching = JS.split("function switchBrain(", 1)[1].split("\n  }\n", 1)[0]
    assert 'request("/api/state?path=" + encodeURIComponent(path))' in switching
    assert 'announce("Now showing "' in switching
    assert "rememberBrain(path)" in switching


def test_the_toast_is_a_live_region() -> None:
    toast = re.search(r'<div class="toast"[^>]*>', HTML)
    assert toast is not None
    assert 'role="status"' in toast.group(0)
    assert 'aria-live="polite"' in toast.group(0)


def test_the_wizard_render_targets_are_not_live_regions() -> None:
    """Whole subtrees get injected into these; a live region reads the lot, six times."""
    for target in ("preview-body", "apply-body"):
        block = re.search(rf'<div id="{target}"[^>]*>', HTML)
        assert block is not None, target
        assert "aria-live" not in block.group(0), target


def test_a_choices_argument_shows_what_it_holds() -> None:
    """The blocker: a <select> whose displayed value and submitted value disagreed."""
    assert 'el("option", { value: "", text: info.empty || "Not set" })' in JS
    assert "cmd.values[argName] = control.value;" in JS


def test_required_arguments_are_exposed_to_assistive_technology() -> None:
    assert 'control.setAttribute("aria-required", "true")' in JS
    assert 'class: "field__req", text: "required"' in JS
    assert '" *", "aria-hidden": "true"' not in JS


# --- contrast, computed rather than asserted ----------------------------------------


def _luminance(hex_colour: str) -> float:
    raw = hex_colour.lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    channels = []
    for index in (0, 2, 4):
        value = int(raw[index : index + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(foreground: str, background: str) -> float:
    first, second = _luminance(foreground), _luminance(background)
    high, low = max(first, second), min(first, second)
    return (high + 0.05) / (low + 0.05)


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\s*;", block))


def palettes() -> dict[str, dict[str, str]]:
    light = _tokens(CSS.split(":root {", 1)[1].split("@media (prefers-color-scheme: dark)", 1)[0])
    dark = dict(light)
    dark.update(_tokens(CSS.split("@media (prefers-color-scheme: dark)", 1)[1].split("*,", 1)[0]))
    return {"light": light, "dark": dark}


# Every pair the audit measured, plus the control-border pair hardened alongside them.
# 4.5 is AA for text under 18pt; 3.0 is SC 1.4.11 for meaningful graphics and controls.
PAIRS = [
    ("mode tag on surface-3", "ink-3", "surface-3", 4.5),
    ("selected mode tag", "accent-ink", "accent", 4.5),
    ("nested field help", "ink-3", "accent-soft", 4.5),
    ("count label on surface-2", "ink-3", "surface-2", 4.5),
    ("cli hint on the page ground", "ink-3", "bg", 4.5),
    ("done tick on ok", "ok-ink", "ok", 3.0),
    ("failed cross on err", "err-ink", "err", 3.0),
    ("focus indicator on surface", "accent", "surface", 3.0),
    ("card sub on surface", "ink-3", "surface", 4.5),
    ("control border on surface", "control-line", "surface", 3.0),
    ("control border on surface-2", "control-line", "surface-2", 3.0),
    # Accent text on the accent wash is Ember Bright (--accent-hover), never base Ember:
    # the Ember system's own rule, and base Ember measures 4.30:1 on the wash.
    ("selected place chip", "accent-hover", "accent-soft", 4.5),
    ("assist question on its panel", "ink", "accent-soft", 4.5),
    ("assist meta on its panel", "ink-3", "accent-soft", 4.5),
    # The sidebar: a brain or a section at rest, the open one on its accent ground, the
    # marker pill on that ground, and the "needs attach" tag on its warning ground.
    ("sidebar item on surface", "ink-2", "surface", 4.5),
    ("open brain on its ground", "ink", "accent-soft", 4.5),
    ("open brain sub on its ground", "ink-3", "accent-soft", 4.5),
    ("current marker on its ground", "accent-hover", "accent-soft", 4.5),
    ("needs-attach tag on its ground", "warn", "warn-soft", 4.5),
    ("open section icon on its ground", "accent", "accent-soft", 3.0),
]


@pytest.mark.parametrize(("label", "fg", "bg", "need"), PAIRS)
@pytest.mark.parametrize("palette", ["light", "dark"])
def test_audited_contrast_pairs_clear_aa(
    palette: str, label: str, fg: str, bg: str, need: float
) -> None:
    tokens = palettes()[palette]
    ratio = contrast(tokens[fg], tokens[bg])
    assert ratio >= need, f"{palette} {label}: {ratio:.2f}:1 needs {need}:1"


def test_the_dark_palette_never_hard_codes_a_glyph_colour() -> None:
    """#fff on the dark --ok is 2.11:1; --ok-ink flips with the palette."""
    assert "color: #fff;" not in CSS
    assert "--ok-ink" in CSS and "--err-ink" in CSS


def test_the_focus_ring_is_not_the_invisible_soft_accent() -> None:
    rule = CSS.split(".input:focus-visible", 1)[1].split("}", 1)[0]
    assert "outline: 2px solid var(--accent);" in rule
    assert "outline: 2px solid var(--accent-soft)" not in CSS


# --- no filesystem path in default-visible copy -------------------------------------
# Round 2 ruled that every path, command line and raw envelope lives behind a "show the
# technical bit" disclosure, off by default. Round 2's verifier then pointed out that
# nothing enforced it, so it could come back silently — which is exactly how the preview
# step regressed. The rule now lives in a test instead of a document.

PATH_SHAPED = re.compile(
    r"""
      (?:[A-Za-z]:\\[^\s"'`]+)                                       # C:\Users\...
    | (?:(?<![\w.])~?/[A-Za-z0-9_.<>-]+(?:/[A-Za-z0-9_.<>-]+)+)      # /tmp/x, ~/x/y
    | (?:(?<![\w./])\.[A-Za-z][A-Za-z0-9_-]*(?:/[A-Za-z0-9_.<>-]+)+) # .claude/skills
    | (?:
        (?<![\w./])[A-Za-z0-9_<>-]+(?:/[A-Za-z0-9_.<>-]+)*
        /[A-Za-z0-9_<>-]+\.[A-Za-z]{1,5}(?![\w/])                    # business/x/y.md
      )
    """,
    re.X,
)

# A whole literal that is nothing but path segments, so `"business/clients/"` cannot
# slip through by ending in a slash instead of an extension.
BARE_PATH = re.compile(r"^[A-Za-z0-9_.<>-]+(?:/[A-Za-z0-9_.<>-]*){2,}$")

# Machinery, not copy. Every entry here is a deliberate, reviewable exception: an app
# route or a spec-mandated namespace, none of which is ever rendered to a reader.
NOT_COPY = {
    "/api/run",
    "/api/state",
    "/api/state?path=",
    "/api/browse",
    "/api/pick-folder",
    "/api/brains",
    # The bundled skill catalogue, served like the fonts: a route, never rendered.
    "/static/catalog/skills.json",
    "http://www.w3.org/2000/svg",
}

# Subtrees whose whole point is to carry the technical detail, plus the ones that carry
# no prose at all.
HIDDEN_TAGS = {"code", "pre", "script", "style", "svg"}


class _VisibleText(HTMLParser):
    """The text a reader sees with every disclosure closed."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip:
            self._skip += 1
            return
        classes = dict(attrs).get("class") or ""
        if tag in HIDDEN_TAGS or (tag == "details" and "tech" in classes):
            self._skip = 1

    def handle_endtag(self, tag: str) -> None:
        if self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.chunks.append(data)


def visible_html_text() -> str:
    parser = _VisibleText()
    parser.feed(re.sub(r"<!--.*?-->", "", HTML, flags=re.S))
    return " ".join(parser.chunks)


def js_string_literals() -> list[str]:
    doubles = re.findall(r'"((?:[^"\\\n]|\\.)*)"', JS)
    singles = re.findall(r"'((?:[^'\\\n]|\\.)*)'", JS)
    return doubles + singles


def test_no_filesystem_path_in_the_markup_a_reader_sees() -> None:
    """Every path in index.html belongs inside <code> inside a .tech disclosure."""
    found = sorted(set(PATH_SHAPED.findall(visible_html_text())))
    assert found == [], f"filesystem paths in default-visible markup: {found}"


def test_no_filesystem_path_is_written_into_the_apps_copy() -> None:
    """app.js authors a third of the words on screen; none of them may be a path."""
    offenders: dict[str, str] = {}
    for literal in js_string_literals():
        if literal in NOT_COPY:
            continue
        hit = PATH_SHAPED.search(literal)
        if hit:
            offenders[hit.group(0)] = literal
        elif BARE_PATH.match(literal):
            offenders[literal] = literal
    assert offenders == {}, f"filesystem paths in authored copy: {sorted(offenders)}"


def _js_section(start: str, end: str) -> str:
    begin = JS.index(start)
    return JS[begin : JS.index(end, begin)]


def test_the_desktop_is_named_as_a_place_in_words() -> None:
    """The default folder sits on the desktop, and the page says so, not its path."""
    assert "on your desktop" in JS
    assert "inside \" + up.name + \", on your desktop" in JS


def test_the_folder_browser_speaks_in_words_and_carries_paths_in_titles() -> None:
    """Every string the browser panel renders is copy; the path only ever rides in title."""
    section = _js_section("var browse = {", "function wireWizard()")
    for literal in re.findall(r'"((?:[^"\\\n]|\\.)*)"', section):
        if literal in NOT_COPY:
            continue
        assert not PATH_SHAPED.search(literal), literal
        assert not BARE_PATH.match(literal), literal
    for words in ("Up", "Put the brain here", "Open this brain", "No folders inside this one."):
        assert f'"{words}"' in section, words
    # The ellipsis is the convention for "opens a window"; the old label promised a list.
    assert "Choose a folder&hellip;</button>" in HTML
    assert "Choose a folder on this computer" not in HTML
    assert 'id="browse-panel"' in HTML
    # A whole folder list lands on every step; a live region would read the lot.
    panel = re.search(r'<div class="browse__panel"[^>]*>', HTML)
    assert panel is not None and "aria-live" not in panel.group(0)
    # The brain marker is a word, so it survives colour-blindness and a screen reader.
    assert 'text: "brain" + who' in section


def test_the_native_folder_window_is_asked_for_first_and_the_panel_stands_in() -> None:
    """One button, two mechanisms: the OS window when the server can open one, the
    in-page list otherwise. The page never decides on its own which one this machine
    has; it reads the server's answer. A closed window says nothing; a failed one says
    one sentence and opens the list."""
    section = _js_section("var picking = false;", "function wireWizard()")
    assert "App.state.picker" in section
    assert 'request("/api/pick-folder", "POST", { start: wizPlace() || null })' in section
    assert "Waiting for the folder window" in section
    assert "if (data && data.cancelled) return;" in section
    assert "openBrowse(PICKER_FALLBACK)" in section
    assert "so pick from the list below." in section
    # The chosen folder is the place; the brain's own folder still goes inside it.
    picked = JS.split("function pickedFolder(path)", 1)[1].split("\n  }", 1)[0]
    assert "setPlace(path)" in picked
    assert "Folder chosen: " in picked
    wiring = JS.split("function wireWizard()", 1)[1].split("\n  }", 1)[0]
    assert "if (pickerAvailable()) pickFolder();" in wiring
    assert "else toggleBrowse();" in wiring


def test_the_sensor_can_actually_see_a_path() -> None:
    """A sensor never shown failing is not a sensor. These are the shapes it must catch."""
    for sample in (
        "It lands in business/brand/brand.md.",
        "Look in .claude/skills for the wiring.",
        "Your brain will live in /home/you/marketing-os.",
        "Try ~/Documents/marketing-os instead.",
        "Open C:\\Users\\you\\marketing-os.",
    ):
        assert PATH_SHAPED.search(sample), sample
    assert BARE_PATH.match("business/clients/")
    # And must not fire on ordinary prose, or on a bare folder name.
    for clean in (
        "One folder of ordinary files you can read, edit and back up.",
        "A folder called marketing-os, in your home folder.",
        "Claude Code and/or Codex can both see the skills.",
        "19 documents to fill in",
    ):
        assert not PATH_SHAPED.search(clean), clean
        assert not BARE_PATH.match(clean), clean


# --- the round-3 fixes, held in place -----------------------------------------------


def test_the_selected_place_is_not_signalled_by_colour_alone() -> None:
    """Both critics found neither option rendering as selected."""
    assert '"aria-pressed": pressed ? "true" : "false"' in JS
    assert '.chip--place[aria-pressed="true"]' in CSS
    # The tick is the sprite's check, shown only when pressed (it used to be a text glyph).
    assert ".chip--place[aria-pressed=\"true\"] .chip__tick .icon" in CSS


def test_the_confirmation_and_the_option_are_built_from_one_phrase() -> None:
    """The state readout contradicted its own controls; now they share a function."""
    assert "function placeLabel(value)" in JS
    assert JS.count("placeLabel(") >= 4


def test_one_place_cannot_be_offered_twice_under_the_same_words() -> None:
    """Verifier find: typing the default back with a trailing slash — what shell
    completion leaves — keyed a second option off the raw string, so two pills read
    identically with only one pressed. That is round 3's own bug, re-made by its fix.
    Both the dedupe key and the pressed test must run through normPath()."""
    assert "function normPath(value)" in JS
    options = JS.split("function placeOptions()", 1)[1].split("\n  }", 1)[0]
    assert "var key = normPath(value);" in options
    assert "seen[key]" in options and "seen[value]" not in options
    chips = JS.split("function renderPathChips(", 1)[1].split("\n  }", 1)[0]
    assert "normPath(option.value) === current" in chips
    assert "option.value === current" not in chips


def test_clearing_the_field_does_not_leave_a_stale_ready_announcement() -> None:
    """The visible readout said 'pick a place' while #where-live still said 'Ready:'.
    Same contradiction as the chips, only a screen reader hears this one."""
    empty = JS.split("function probePath(immediate)", 1)[1].split("var work =", 1)[0]
    assert '$("where-live").textContent' in empty


def test_the_commit_point_and_the_summary_cannot_scroll_away() -> None:
    """The round-3 regression: a card taller than the viewport hid the decision."""
    foot = CSS.split(".wizard__foot {", 1)[1].split("}", 1)[0]
    assert "position: sticky;" in foot and "bottom: 0;" in foot
    summary = CSS.split(".plan-sum {", 1)[1].split("}", 1)[0]
    assert "position: sticky;" in summary and "top: var(--topbar-h);" in summary
    card = CSS.split(".wizard__card {", 1)[1].split("}", 1)[0]
    assert "overflow: clip;" in card, "overflow:hidden makes the card a scroll container"


def test_scaffolding_recedes_in_the_plan_tree() -> None:
    """Ten .gitkeep rows at full weight drowned the documents that matter."""
    assert "tree__row--faint" in JS and ".tree__row--faint" in CSS
    assert "tree__row--doc" in JS and ".tree__row--doc" in CSS
    # De-emphasis by opacity is de-emphasis nobody measured: 62% put it at 3.02:1.
    faint = CSS.split(".tree__row--faint {", 1)[1].split("}", 1)[0]
    assert "opacity" not in faint


def test_one_status_system_per_fact_on_the_dashboard() -> None:
    """Header pill, health tile and checklist badge all counted the same thing."""
    assert "top-health" not in JS and "top-health" not in HTML
    assert "Same count as the checklist below" not in JS
    assert JS.count('text: counts.requiredDone + " of " + counts.required + " required"') == 1


def test_no_copy_promises_the_reader_will_edit_a_file() -> None:
    assert "editing one file" not in JS and "editing one file" not in HTML


def test_the_mobile_hint_gets_its_own_line() -> None:
    """`width: 100%` loses to the base rule's `flex: 1` (a 0 basis), which is how one
    sentence became a five-line column wedged against Continue."""
    mobile = CSS.split("@media (max-width: 640px) {", 1)[1]
    hint = mobile.split(".wizard__hint {", 1)[1].split("}", 1)[0]
    assert "flex: 1 1 100%;" in hint, "a 100% basis, not a 100% width"


def test_the_mode_consequences_are_not_dressed_as_success() -> None:
    """Green on a static label reads as 'checked and approved'. Nothing was checked."""
    delta = CSS.split(".mode__delta {", 1)[1].split("}", 1)[0]
    assert "--ok" not in delta, "success green belongs to state that has been measured"


# --- the assisted interview ---------------------------------------------------------
# The one feature in this app that can spend the operator's money. Every rule below was
# a condition of building it at all, so each one is a sensor rather than a paragraph.

ASSIST_JS = JS.split("the assisted interview */", 1)[1].split("function openQuestions()", 1)[0]
ENGINE = Path(assist_engine.__file__).read_text(encoding="utf-8")


def _call_sites(source: str, name: str) -> list[int]:
    """Every call of ``name(``, ignoring its own declaration."""
    return [
        hit.start()
        for hit in re.finditer(re.escape(name) + r"\(", source)
        if not source[max(0, hit.start() - 9) : hit.start()].endswith("function ")
    ]


def test_the_model_is_asked_only_from_a_press() -> None:
    """The blocker. No page load, no timer, no prefetch, no warm-up, no polling."""
    assert JS.count('run("assist ask"') == 1, "one caller, or the rule cannot be checked"
    turn = ASSIST_JS.split("function assistTurn(", 1)[1].split("\n  }", 1)[0]
    assert 'run("assist ask"' in turn, "the only caller must be assistTurn"

    sites = _call_sites(JS, "assistTurn")
    assert len(sites) >= 3
    for site in sites:
        window = JS[max(0, site - 400) : site]
        assert '"click"' in window, f"assistTurn called outside a click handler at {site}"

    for banned in ("setTimeout", "setInterval", "requestAnimationFrame", "requestIdleCallback"):
        assert banned not in ASSIST_JS, f"{banned} has no business in the assisted interview"

    boot = JS.split("function boot()", 1)[1]
    for source in (boot, JS.split("function refresh(showBoot)", 1)[1].split("\n  }", 1)[0]):
        assert "assistTurn" not in source
        assert "assist ask" not in source


def test_the_capability_probe_runs_once_and_asks_no_model() -> None:
    """`assist status` runs `--version`; it spends nothing, so it may run unasked — once."""
    assert JS.count('run("assist status"') == 1
    probe = ASSIST_JS.split("function probeAssist(", 1)[1].split("\n  }", 1)[0]
    assert 'run("assist status"' in probe
    assert "if (assist.probing) return assist.probing;" in probe
    assert len(_call_sites(JS, "probeAssist")) == 1
    opened = JS.split("function openInterview(", 1)[1].split("\n  }", 1)[0]
    assert "probeAssist()" in opened, "the probe belongs to opening the interview, not to boot"


def test_no_runtime_renders_no_control_at_all() -> None:
    """Graceful absence: not a disabled button, not an error, not an empty box with a rule."""
    render = ASSIST_JS.split("function renderAssist(ctx)", 1)[1].split("\n  }", 1)[0]
    guard = render.split("if (!assist.ready)", 1)
    assert len(guard) == 2, "the absence guard must exist"
    assert "fill(ctx.host, []);" in guard[1].split("}", 1)[0]
    assert "assistPanel(" not in guard[0], "nothing may be built before the guard"
    assert "#iv-assist:empty" in CSS
    assert "display: none;" in CSS.split("#iv-assist:empty", 1)[1][:40]
    # The offer itself is never rendered blocked: the only blocked button here is the one
    # that sends an empty answer back.
    assert "setBlocked(send," in ASSIST_JS
    assert "setBlocked(button" not in ASSIST_JS


# Every shape in which the assistant's words are allowed to be handled. Anything else
# touching them fails this test, which is the only reason it can be trusted.
ASSIST_TEXT_SAFE = re.compile(
    r"""
      ^assist\.(question|draft|inserted)\s*=
    | ^var\ question\ =\ String\(envelope\.question
    | createTextNode\(assist\.(question|draft)\)
    | ^if\ \(assist\.(question|draft)\)
    | ^takeDraft\(ctx,\ assist\.draft\);
    | ^assist\.turns\.push\(
    | ^finishAssist\(ctx,\ String\(envelope\.draft
    | ^ctx\.area\.value\ =\ draft;
    | ^draft:\ ""
    | ^question:\ ""
    """,
    re.X,
)


def test_the_assistants_words_reach_the_page_as_text_and_nothing_else() -> None:
    """Model output is data. It is a text node or a textarea value, never markup."""
    assert "document.createTextNode(assist.question)" in ASSIST_JS
    assert "document.createTextNode(assist.draft)" in ASSIST_JS
    take = ASSIST_JS.split("function takeDraft(", 1)[1].split("\n  }", 1)[0]
    assert "ctx.area.value = draft;" in take, "the box is the only other place a draft lands"

    for raw in ASSIST_JS.splitlines():
        line = raw.strip()
        if line.startswith("//") or line.startswith("*") or line.startswith("/*"):
            continue
        if not re.search(r"assist\.(question|draft)|envelope\.(question|draft)", line):
            continue
        assert ASSIST_TEXT_SAFE.search(line), f"unreviewed handling of model text: {line}"


def test_a_failed_turn_shows_our_sentence_and_never_the_models() -> None:
    """A refusal carries the child's stderr. None of it may become the headline."""
    trouble = ASSIST_JS.split("function assistTrouble(", 1)[1].split("\n  }", 1)[0]
    assert "ASSIST_TROUBLE[code]" in trouble
    assert ".message" not in trouble, "the envelope's message is the engine's, not our copy"
    keys = set(re.findall(r'"([a-z][a-z-]+)": "', ASSIST_JS.split("ASSIST_TROUBLE = {", 1)[1]))
    engine_codes = {
        code for code in re.findall(r'"(assist-[a-z-]+)"', ENGINE) if not code.endswith("-detail")
    }
    assert engine_codes, "the sensor must be able to see the engine's codes"
    assert engine_codes <= keys, f"unhandled failures: {sorted(engine_codes - keys)}"
    for code in ("no-runtime", "unknown-field", "bad-transcript", "not-a-mos-repo"):
        assert code in keys and f'"{code}"' in ENGINE


def test_what_it_costs_is_said_where_the_choice_is_made() -> None:
    offer = ASSIST_JS.split("function assistOffer(", 1)[1].split("\n  }", 1)[0]
    assert "Let my assistant interview me" in offer
    assert "assistRuntimeName()" in offer, "name the runtime, do not say 'an assistant'"
    assert "on your own " in offer and "subscription" in offer
    assert "spends your own tokens" in offer
    assert "only when you press this button" in offer
    assert 'id: "iv-assist-cost"' in offer and 'aria-describedby": "iv-assist-cost' in offer


def test_the_manual_path_is_still_offered_in_words() -> None:
    assert "or write it yourself" in ASSIST_JS
    assert ".assist-or::before" in CSS and ".assist-or::after" in CSS



# --- copy may not deny a capability the app ships -----------------------------------
# Three times now a true sentence has outlived the build that made it true. The header
# said "Nothing is invented" after a third of the prose became ours. The interview
# preview promised the rest of the file "stays exactly as it is" while the writer
# replaced the body. The post-create screen promised "no terminal, no assistant, no
# editing files" one click before offering "Let my assistant interview me". Same shape
# every time: a reassurance written when the app could not do the thing, left standing
# after it could, and nothing that reads the copy back against the code.
#
# So this reads the copy back against the code. Each row below is a capability the app
# demonstrably ships, plus the grammar in which copy could deny it; the test fails when
# a denial and its evidence are both present. It is a grammar rather than a list of
# banned sentences, so the fourth instance is caught in whatever words it arrives in.


def concatenated_js_literals() -> list[str]:
    """String literals, with `"a " +\\n  "b"` continuations stitched back together.

    A reader sees the whole sentence, not the line it was wrapped on, so a claim that
    straddles a line wrap must still be one string by the time the sensor reads it.
    """
    stitched = re.sub(r'"\s*\+\s*\n\s*"', "", JS)
    doubles = re.findall(r'"((?:[^"\\\n]|\\.)*)"', stitched)
    singles = re.findall(r"'((?:[^'\\\n]|\\.)*)'", stitched)
    return doubles + singles


def user_facing_copy() -> list[str]:
    """Every sentence a reader can be shown: the app's own words plus the page's."""
    return concatenated_js_literals() + [visible_html_text()]


class Capability(NamedTuple):
    """Something this app can do, and the words in which copy might swear it cannot."""

    name: str
    evidence: tuple[str, ...]  # substrings in app.js that prove the shipped app has it
    nouns: str = ""  # what an operator would call the thing: "assistant", "agent"
    participles: str = ""  # "nothing is <invented>"
    verbs: str = ""  # "it will never <invent>"
    extra: tuple[str, ...] = ()  # shapes seen in the wild that the grammar misses


def absence_claims(cap: Capability) -> list[re.Pattern[str]]:
    """The shapes an absence-claim takes, built from one capability's vocabulary.

    The bare-denial shape is deliberately anchored at both ends of its clause: a
    reassurance list reads "..., no assistant, ...", whereas a denial with a subject
    and a verb in front of it ("It runs their version check and asks no model") is
    scoped to that subject and is nobody's overclaim. The needs/never shapes cover the
    same denial once it grows a verb of its own ("needs no assistant").
    """
    patterns: list[str] = []
    if cap.nouns:
        article = r"(?:an?\s+|any\s+)?"
        patterns += [
            rf"(?:^|[.,;:!?]\s*)(?:no|without)\s+{article}(?:{cap.nouns})\b\s*(?=[,.;:!?]|$)",
            rf"\b(?:needs?|requires?|uses?|involves?|wants?)\s+(?:no|any)\s+(?:{cap.nouns})\b",
            rf"\b(?:never|cannot|can't|does not|do not|will not|won't)"
            rf"\s+(?:need|require|use|involve|open|touch|ask|call)s?\s+{article}(?:{cap.nouns})\b",
            rf"\bwithout\s+{article}(?:{cap.nouns})\b",
        ]
    if cap.participles:
        patterns.append(rf"\bnothing\s+(?:is|gets|will be)\s+(?:{cap.participles})\b")
    if cap.verbs:
        patterns.append(
            rf"\b(?:never|does not|do not|will not|won't|cannot|can't)\s+(?:{cap.verbs})s?\b"
        )
    return [re.compile(pattern, re.I) for pattern in patterns + list(cap.extra)]


CAPABILITIES = [
    Capability(
        name="the assisted interview",
        # One click from the post-create screen, the interview offers to run the
        # operator's own agent runtime. Copy that swears there is no assistant here is
        # false the moment this button exists.
        evidence=('run("assist ask"', "Let my assistant interview me"),
        nouns=r"assistants?|agents?|ai|models?|claude code|codex|robots?|bots?",
    ),
    Capability(
        name="a network call made on the operator's behalf",
        # The engine makes none of its own, but the runtime it starts does, on the
        # operator's credentials. "Works without the internet" is not ours to promise.
        evidence=('run("assist ask"',),
        nouns=r"internet|network|cloud",
    ),
    Capability(
        name="copy this app writes itself",
        # A third of the words on screen are authored here, not read out of an
        # envelope. That is what made "Nothing is invented" false.
        evidence=("authored copy", "heroPlan"),
        participles=r"invented|made up|fabricated|imagined",
        verbs=r"invent|make up|fabricate|imagine",
    ),
    Capability(
        name="replacing what a context file already says",
        # `mos context set` writes a whole body, so no screen may promise that the rest
        # of a file survives an answer untouched.
        evidence=('run("context set"',),
        participles=r"changed|replaced|rewritten|overwritten",
        verbs=r"change|replace|rewrite|overwrite",
        extra=(r"\beverything else\s+(?:in\s+)?(?:that|the)?\s*file\s+stays\b",),
    ),
]


@pytest.mark.parametrize("cap", CAPABILITIES, ids=lambda cap: cap.name)
def test_no_user_facing_copy_denies_a_capability_the_app_ships(cap: Capability) -> None:
    offenders: list[tuple[str, str]] = []
    for text in user_facing_copy():
        for pattern in absence_claims(cap):
            hit = pattern.search(text)
            if hit:
                offenders.append((hit.group(0).strip(), text))
    assert offenders == [], f"copy denies {cap.name}: {offenders}"


def test_every_capability_in_the_table_is_still_shipped() -> None:
    """A denial is only false while the capability exists, so a rotted evidence marker
    would switch a whole row off in silence. If one of these really was removed, delete
    its row on purpose — do not let the marker drift."""
    for cap in CAPABILITIES:
        missing = [marker for marker in cap.evidence if marker not in JS]
        assert missing == [], f"{cap.name}: evidence no longer in app.js: {missing}"


def test_the_absence_sensor_can_actually_see_a_false_claim() -> None:
    """A sensor never shown failing is not a sensor. The first three are the exact
    sentences this project has already shipped and had to withdraw."""
    by_name = {cap.name: absence_claims(cap) for cap in CAPABILITIES}
    caught = [
        (
            "the assisted interview",
            "The app asks one question at a time, in plain English, and writes the "
            "answers for you. No terminal, no assistant, no editing files.",
        ),
        ("copy this app writes itself", "Nothing is invented."),
        (
            "replacing what a context file already says",
            "Everything else in that file stays exactly as it is.",
        ),
        ("the assisted interview", "Setting this up needs no AI."),
        ("the assisted interview", "It never asks a model."),
        ("the assisted interview", "This works without an assistant."),
        ("a network call made on the operator's behalf", "No internet, no accounts."),
        ("copy this app writes itself", "This app will never invent a number."),
    ]
    for name, sample in caught:
        assert any(pattern.search(sample) for pattern in by_name[name]), sample

    # And must stay quiet on true copy: a denial scoped to one command by its own
    # subject, a report about this machine, and ordinary reassurance about the
    # operator's own words.
    for clean in (
        "It runs their version check and asks no model, so it costs nothing.",
        "No assistants detected",
        "Nothing you have written has been touched.",
        "Nothing is written until you confirm on step 4.",
        "Claude Code and Codex can both see the skills.",
        "Straight from the checker. Nothing added, nothing hidden.",
    ):
        for name, patterns in by_name.items():
            for pattern in patterns:
                hit = pattern.search(clean)
                assert hit is None, f"{name} fired on true copy ({hit!r}): {clean}"


# --- one word, one meaning, per screen ----------------------------------------------

APPLIED_JS = JS.split("function renderApplied(done)", 1)[1].split("\n  }", 1)[0]


def test_the_post_create_screen_names_the_runtimes_rather_than_saying_assistant() -> None:
    """The same screen said "both assistants can see the skills" and, seven lines on,
    "no assistant" — the first meaning Claude Code and Codex, the second meaning the
    interviewer the next click offers. One word, two referents, one screen. It now
    names the runtimes and drops the ambiguous noun."""
    assert "assistant" not in APPLIED_JS.lower(), "name the runtimes on this screen"
    assert "Claude Code" in APPLIED_JS and "Codex" in APPLIED_JS


def test_the_post_create_screen_still_promises_no_terminal_and_no_hand_editing() -> None:
    """The false half of that sentence went; the reassurance it carried is true and had
    to stay, or the fix would have left a non-technical operator colder than it found
    them."""
    assert "will not open a terminal" in APPLIED_JS
    assert "will not edit anything by " in APPLIED_JS
    assert "one question at a time" in APPLIED_JS


# --- the desktop is where operators actually keep their work -------------------------


def test_the_desktop_is_named_in_words_like_every_other_place() -> None:
    """Step 1 defaults to the desktop, so the readout had to learn to say so. Every other
    place is described in words rather than a path, and the desktop is not an exception."""
    assert "on your desktop" in JS
    assert "inside " in JS and ", on your desktop" in JS


def test_the_brain_folder_is_named_after_the_business_never_after_the_engine() -> None:
    """marketing-os is the engine's name, not the brain's. Step 1 chooses a place; the
    folder inside it takes its name from the business named on step 3. No site in the
    path-building code may hard-code a folder name."""
    assert '"/marketing-os"' not in JS
    assert "BRAIN_FOLDER" not in JS
    assert "function brainSlug()" in JS
    assert "function wizPlace()" in JS
    assert "function wizPath()" in JS
    path_fn = JS.split("function wizPath()", 1)[1].split("\n  }", 1)[0]
    assert "brainSlug()" in path_fn
    # The typed exact path already ending in the slug is used as is, never doubled.
    assert "folderName(norm) === slug" in path_fn
    # The folder browser chooses the place; it never appends a folder name of its own.
    chooser = JS.split("function chooseFolder(data)", 1)[1].split("\n  }", 1)[0]
    assert "setPlace(data.path)" in chooser
    assert "+ " not in chooser.split("where-live")[0]
    # The chips offer places, and the readout says where the brain goes in words.
    options = JS.split("function placeOptions()", 1)[1].split("\n  }", 1)[0]
    assert "offer(place.path);" in options
    assert "A new folder, named after your business, " in JS


def test_the_places_come_from_the_server_not_from_the_page() -> None:
    """Only the server can tell which desktop is real: under WSL the one that matters
    belongs to Windows, and no amount of guessing in the page can find it."""
    assert "App.state && App.state.places" in JS
    # The old `status ~` round trip survives only as a fallback for an older server.
    assert "res.data.home" in JS
    assert "function findHome" in JS


def test_found_brains_are_offered_by_name_and_never_by_path() -> None:
    """The list of brains already in the chosen folder is copy the operator reads, so it
    obeys the same rule as the rest of the copy: names and place words, path in the title."""
    found = JS.split("function renderFoundBrains", 1)[1].split("\n  }\n", 1)[0]
    assert "placeLabel(" in found
    assert "title: brain.path" in found


def test_found_brains_come_from_a_look_at_the_chosen_place_never_a_home_sweep() -> None:
    """The wizard asks about the one folder it points at; it never reads a background
    scan of the home folder, and a late answer for an abandoned place is thrown away."""
    refresh = JS.split("function refreshFoundBrains", 1)[1].split("\n  }\n", 1)[0]
    assert '"/api/browse"' in refresh
    assert "wizPlace() !== place" in refresh
    assert "existing_brains" not in JS


# --- findings reach the reader in plain words ----------------------------------------
# The checker's messages are written for a terminal: "No contract block. See CONTRACT.md
# for the five required keys." told a marketer to open the file the row above said was
# missing. FINDING_COPY in app.js carries one sentence and one recovery per code. This
# reads the codes the checker can emit back against that table, so a new code cannot ship
# without its sentence; an untranslated code still renders the checker's words, so the
# failure mode is dull, never silent.

CHECKER_MODULES = (validation, graphlint, status, skills)


def checker_codes() -> set[str]:
    codes: set[str] = set()
    for module in CHECKER_MODULES:
        source = Path(module.__file__).read_text(encoding="utf-8")
        codes.update(re.findall(r'finding\(\s*"([a-z-]+)"', source))
    return codes


def finding_copy_codes() -> set[str]:
    table = JS.split("var FINDING_COPY = {", 1)[1].split("\n  };", 1)[0]
    return set(re.findall(r'^\s+"([a-z-]+)": \{', table, re.M))


def test_every_checker_code_has_a_plain_sentence() -> None:
    assert checker_codes() - finding_copy_codes() == set()


def test_the_plain_sentences_carry_a_count_where_more_than_one_can_happen() -> None:
    """A `many` sentence that never says how many reads as if there were one."""
    table = JS.split("var FINDING_COPY = {", 1)[1].split("\n  };", 1)[0]
    entries = re.findall(r'"([a-z-]+)": \{\s*one: "([^"]+)",\s*many: "([^"]+)"', table)
    assert entries, "the table did not parse"
    for code, one, many in entries:
        if one != many:
            assert "{n}" in many, f"{code}: the many sentence has no count"


def test_the_reader_is_never_told_about_a_schema() -> None:
    """The brain has folders and files where it expects them; it has no schema."""
    # A bare kebab-case literal is a code the envelope carries, never a sentence shown.
    hits = [
        text
        for text in user_facing_copy()
        if not re.fullmatch(r"[a-z-]+", text) and re.search(r"\bschemas?\b", text, re.I)
    ]
    assert hits == [], hits
