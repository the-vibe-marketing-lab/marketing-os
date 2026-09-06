/* MarketingOS local app.
 *
 * Contract with the server (marketing_os/ui/server.py):
 *   - the session token lives in <meta name="mos-token">
 *   - every /api/* request sends it as the X-MOS-Token header
 *   - GET  /api/state  -> cwd, root, is_brain, command_specs, status + doctor envelopes,
 *                         and `brains`: every brain the operator has; ?path= asks about
 *                         another root, which is how switching brains works
 *                         Its two envelopes are trimmed for the page: `status.findings`
 *                         carries the first few hundred, errors first, with the true
 *                         numbers in `findings_total` and `findings_counts`; doctor keeps
 *                         its `checks` and drops the findings and runtimes that are the
 *                         status envelope's, item for item. /api/run is never trimmed, so
 *                         read counts through findingsTotal() and severityCount() and
 *                         both shapes answer the same.
 *   - POST /api/brains -> {op: remember|forget, path} -> {brains}
 *   - POST /api/run    -> {command, args} -> {envelope, command_line}
 *   - POST /api/browse -> {path} -> one folder: its parent, subfolders, brain if any
 *   - POST /api/pick-folder -> {start} -> the OS folder window's answer: path or cancelled
 *   - command_line is always shown, because the app teaches the CLI instead of hiding it
 *
 * Content-Security-Policy is script-src 'self': no inline script, no external anything.
 *
 * What is, and is not, from the server. No envelope value is ever interpolated as markup:
 * every one reaches the DOM as text, through el()'s `text:` or add()'s createTextNode. But
 * a large share of the words on screen are written here rather than reported — CONTEXT_INFO,
 * COMMAND_INFO, ARG_INFO, APPLY_STEPS, the cards' copy and the whole of heroPlan()
 * are authored copy, keyed off envelope ids. Facts (counts, paths, findings, changes, diffs)
 * come from envelopes; the sentences around them are ours. Do not read heroPlan's diagnoses
 * as something the server said.
 */
(function () {
  "use strict";

  var SVG = "http://www.w3.org/2000/svg";
  var meta = document.querySelector('meta[name="mos-token"]');
  var TOKEN = meta ? meta.getAttribute("content") : "";

  /* ============================================================ dom helpers */

  function el(tag, attrs, kids) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        var value = attrs[key];
        if (value === null || value === undefined || value === false) return;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key === "on") {
          Object.keys(value).forEach(function (evt) {
            node.addEventListener(evt, value[evt]);
          });
        } else if (value === true) node.setAttribute(key, "");
        else node.setAttribute(key, String(value));
      });
    }
    add(node, kids);
    return node;
  }

  function add(node, kids) {
    if (kids === null || kids === undefined || kids === false) return node;
    if (Array.isArray(kids)) {
      kids.forEach(function (kid) {
        add(node, kid);
      });
      return node;
    }
    node.appendChild(typeof kids === "string" ? document.createTextNode(kids) : kids);
    return node;
  }

  function icon(name, cls) {
    var svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", cls ? "icon " + cls : "icon");
    svg.setAttribute("aria-hidden", "true");
    var use = document.createElementNS(SVG, "use");
    use.setAttribute("href", "#i-" + name);
    svg.appendChild(use);
    return svg;
  }

  function fill(node, kids) {
    while (node.firstChild) node.removeChild(node.firstChild);
    add(node, kids);
    return node;
  }

  function $(id) {
    return document.getElementById(id);
  }

  function show(node, visible) {
    if (visible) node.removeAttribute("hidden");
    else node.setAttribute("hidden", "");
  }

  function plural(n, one, many) {
    return n + " " + (n === 1 ? one : many || one + "s");
  }

  function announce(message) {
    var live = $("live");
    // An identical string is not re-announced, so clear it first.
    if (live.textContent === message) live.textContent = "";
    live.textContent = message;
  }

  /* Put focus somewhere deliberate after an async view swap, never on <body>. The
   * default focus scroll brings the result into view, and html's scroll-padding-top
   * keeps it clear of the sticky bar. */
  function land(node, message) {
    if (message) announce(message);
    if (!node) return;
    node.tabIndex = -1;
    node.focus();
  }

  var toastTimer = null;
  function toast(message) {
    var node = $("toast");
    node.textContent = message;
    show(node, true);
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      show(node, false);
      node.textContent = "";
    }, 2600);
  }

  function copy(value, said) {
    var done = function () {
      toast(said || "Copied");
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(done, function () {
        legacyCopy(value, done);
      });
      return;
    }
    legacyCopy(value, done);
  }

  function legacyCopy(value, done) {
    var area = el("textarea", { class: "sr-only" });
    area.value = value;
    document.body.appendChild(area);
    area.select();
    try {
      document.execCommand("copy");
      done();
    } catch (err) {
      // The one error path with no other surface: say it out loud as well as showing it.
      toast("Copy failed - select the text instead");
      announce("Copy failed. Select the text and copy it yourself.");
    }
    document.body.removeChild(area);
  }

  /* ==================================================================== api */

  function request(path, method, body) {
    var headers = { "X-MOS-Token": TOKEN };
    if (body) headers["Content-Type"] = "application/json";
    return fetch(path, {
      method: method || "GET",
      headers: headers,
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (response) {
      return response
        .json()
        .catch(function () {
          return null;
        })
        .then(function (data) {
          return { ok: response.ok, status: response.status, data: data };
        });
    });
  }

  /* Run one allowlisted command. Always resolves; failures come back as envelopes. */
  function run(command, args) {
    var started = Date.now();
    return request("/api/run", "POST", { command: command, args: args || {} }).then(
      function (res) {
        var payload = res.data || {};
        return {
          ok: res.ok,
          envelope: payload.envelope || null,
          commandLine: payload.command_line || "",
          elapsed: Date.now() - started,
          transport: res.ok
            ? null
            : "The local app refused that request (HTTP " + res.status + ").",
        };
      },
      function (error) {
        return {
          ok: false,
          envelope: null,
          commandLine: "",
          elapsed: Date.now() - started,
          transport: "Could not reach the local app: " + error,
        };
      }
    );
  }

  /* An envelope missing a key must not throw inside a .then and strand a spinning
   * button forever. Every list is read through these. */
  function findingsOf(envelope) {
    return (envelope && Array.isArray(envelope.findings) && envelope.findings) || [];
  }

  function changesOf(envelope) {
    return (envelope && Array.isArray(envelope.changes) && envelope.changes) || [];
  }

  function bySeverity(envelope, severity) {
    return findingsOf(envelope).filter(function (item) {
      return item && item.severity === severity;
    });
  }

  /* How many findings there really are, which is not always how many arrived. The state
   * request carries a few hundred rows and states its totals separately, so the page can
   * be built without thousands of elements in it while still saying what the checker
   * found. A /api/run envelope carries every finding and no totals, and there the list is
   * the count. Both are read through these two, so no number on screen depends on which
   * request a status envelope came from. */
  function findingsTotal(envelope) {
    var total = envelope && envelope.findings_total;
    return typeof total === "number" ? total : findingsOf(envelope).length;
  }

  function severityCount(envelope, severity) {
    var counts = envelope && envelope.findings_counts;
    if (counts && typeof counts[severity] === "number") return counts[severity];
    return bySeverity(envelope, severity).length;
  }

  /* ================================================================== words */

  var MODE_LABEL = { "in-house": "In-house brain", agency: "Agency HQ", client: "Client brain" };
  var MODE_SHORT = { "in-house": "In-house", agency: "Agency", client: "Client" };
  var RUNTIME_LABEL = { claude: "Claude Code", codex: "Codex" };

  var CONTEXT_INFO = {
    brand: {
      title: "Your brand",
      body: "What the business is, who it serves, and what makes it different from the one down the road.",
    },
    voice: {
      title: "How you sound",
      body: "The words you use and the ones you never use, so anything written for you sounds like you.",
    },
    audience: {
      title: "Who you are talking to",
      body: "The person you want to reach: what they want, and what is stopping them buying.",
    },
    offer: {
      title: "What you sell",
      body: "At least one offer, described the way a customer would hear it rather than how you file it.",
    },
    strategy: {
      title: "Where you are going",
      body: "This year's plan, so the advice you get is aimed at the right target.",
    },
    proof: {
      title: "Your proof",
      body: "Results and testimonials you can point at when someone asks why you.",
    },
  };

  function contextInfo(key) {
    return CONTEXT_INFO[key] || { title: String(key), body: "" };
  }

  var COMMAND_INFO = {
    status: {
      group: "everyday",
      order: 1,
      title: "Check the brain",
      blurb: "What is in the folder, what is filled in, and whether both assistants can see the skills.",
    },
    "context set": {
      group: "everyday",
      order: 2,
      title: "Answer a business question",
      blurb: "Writes one answer into the file behind it. The in-app interview runs this for you.",
    },
    update: {
      group: "everyday",
      order: 3,
      title: "Update MarketingOS",
      blurb: "Updates the engine itself to the latest release.",
    },
    "skills sync": {
      group: "maintenance",
      order: 1,
      title: "Sync the assistant skills",
      blurb: "Copies this version's shared skills into each assistant's own skill folder.",
    },
    "index sync": {
      group: "maintenance",
      order: 2,
      title: "Rebuild the navigation",
      blurb: "Regenerates every navigation page so the map matches the files that actually exist.",
    },
    related: {
      group: "maintenance",
      order: 3,
      title: "Link up orphan documents",
      blurb: "Proposes a Related block for documents that link to nothing, so no note is stranded.",
    },
    ingest: {
      group: "maintenance",
      order: 4,
      title: "Capture raw material",
      blurb: "Files a document, a URL or pasted text into the knowledge folder with the right frontmatter.",
    },
    validate: {
      group: "maintenance",
      order: 5,
      title: "Validate the structure",
      blurb: "Checks that every folder and file is where the brain expects it, and reports anything out of place.",
    },
    doctor: {
      group: "maintenance",
      order: 6,
      title: "Health check",
      blurb: "Structure and assistant wiring in one pass. The fastest answer to is anything broken.",
    },
    "context show": {
      group: "maintenance",
      order: 7,
      title: "See the questions",
      blurb: "Every business question, whether it has been answered, and the answer on file.",
    },
    query: {
      group: "maintenance",
      order: 8,
      title: "Find something",
      blurb: "Ask a question, get back the documents in this brain most likely to answer it.",
    },
    think: {
      group: "maintenance",
      order: 9,
      title: "Think about a topic",
      blurb: "Gathers the grounded context for a topic and hands it to an assistant to reason over.",
    },
    "assist status": {
      group: "advanced",
      order: 1,
      title: "Can an assistant interview you",
      blurb:
        "Which assistants on this computer can actually answer. It runs their version " +
        "check and asks no model, so it costs nothing.",
    },
    "assist ask": {
      group: "advanced",
      order: 2,
      title: "One turn of the assisted interview",
      blurb:
        "Your assistant either asks you one question or drafts an answer from what it has " +
        "been told. It runs on your own subscription and spends your own tokens, and it " +
        "writes nothing: the draft comes back for you to save yourself.",
    },
    "index status": {
      group: "advanced",
      order: 3,
      title: "Navigation freshness",
      blurb: "Whether the catalogue and the navigation map still match what is on disk.",
    },
    "index build": {
      group: "advanced",
      order: 4,
      title: "Rebuild the catalogue",
      blurb: "Re-reads every document into machine-local state. Safe to run any time.",
    },
    statusline: {
      group: "advanced",
      order: 5,
      title: "One-line summary",
      blurb: "The short badge meant for a terminal prompt or a status bar.",
    },
    install: {
      group: "advanced",
      order: 6,
      title: "Install the global skills",
      blurb: "Puts the bootstrap skills in your home folder so any assistant can find MarketingOS.",
    },
    migrate: {
      group: "advanced",
      order: 7,
      title: "Tidy files into place",
      blurb: "Diagnoses files sitting in the wrong place, and applies a routing plan when you have one.",
    },
    attach: {
      group: "advanced",
      order: 8,
      title: "Adopt an existing folder",
      blurb: "Brings a brain made with an older layout up to date. Every change is previewed before it is written.",
    },
    onboard: {
      group: "advanced",
      order: 9,
      title: "Create or complete a brain",
      blurb: "Scaffolds folders, wires the skills, starts git, and lists the business files still to fill in.",
    },
  };

  function commandInfo(name) {
    return COMMAND_INFO[name] || { group: "advanced", order: 99, title: name, blurb: "" };
  }

  /* Three tiers: what an operator runs most days, what keeps a brain tidy, and the rest.
   * Typed lowercase; the stylesheet sets them as eyebrows. */
  var GROUPS = [
    { id: "everyday", label: "everyday" },
    { id: "maintenance", label: "maintenance" },
    { id: "advanced", label: "advanced", folded: true },
  ];

  var ARG_INFO = {
    path: { label: "Folder", help: "Which brain to act on.", mono: true },
    name: { label: "Business name", placeholder: "Cascade Strength Co." },
    mode: {
      label: "Who it is for",
      help: "In-house is one brand you own; agency adds a client list; client belongs to an agency.",
      choices: ["in-house", "agency", "client"],
      empty: "Choose one",
    },
    agency: { label: "Agency name", help: "Recorded when the mode is client." },
    hq: {
      label: "Agency HQ folder",
      help: "Client mode only: adds a row to that agency's client list.",
      mono: true,
    },
    runtime: {
      label: "Assistant",
      help: "Whose skill folder to touch. All does both.",
      choices: ["all", "claude", "codex"],
      initial: "all",
      empty: "Not set",
    },
    limit: { label: "How many results", type: "number" },
    question: { label: "Your question", placeholder: "What do we promise first-time buyers?" },
    topic: { label: "Topic", placeholder: "spring campaign" },
    source: { label: "What to capture", help: "A file, a folder, a URL, or text.", mono: true },
    field: {
      label: "Which question",
      help: "The business question this answer belongs to.",
      choices: ["brand", "voice", "audience", "offer", "strategy", "proof"],
      empty: "Choose one",
    },
    text: { label: "Your answer", help: "In your own words. Specifics beat adjectives." },
    "transcript-json": {
      label: "The conversation so far",
      help: "The questions and answers already exchanged, as JSON. The interview fills this in for you.",
      mono: true,
    },
    slug: { label: "File name override" },
    date: { label: "Capture date", placeholder: "YYYY-MM-DD" },
    "plan-file": { label: "Routing plan file", mono: true },
    strict: { label: "Strict - treat frontmatter warnings as errors" },
    grep: { label: "Exact text match instead of ranked search" },
    pending: { label: "Only list captures the wiki has not compiled yet" },
    "no-ui": { label: "Do not open this app afterwards" },
  };

  function argInfo(name) {
    return ARG_INFO[name] || { label: name };
  }

  /* ================================================================== state */

  var App = {
    state: null,
    home: "",
    path: "",
    view: "dashboard",
    status: null,
    doctor: null,
    specs: [],
    brains: [], // every brain the app knows, as /api/state last reported them
  };

  function remember(path) {
    try {
      window.sessionStorage.setItem("mos.path", path);
    } catch (err) {
      /* private mode: the app still works, it just forgets. */
    }
  }

  function remembered() {
    try {
      return window.sessionStorage.getItem("mos.path") || "";
    } catch (err) {
      return "";
    }
  }

  /* -------------------------------------------------- talking about places */

  /* One place, one spelling. A trailing slash — what shell completion leaves behind —
   * makes the same folder a different string, and an option keyed on the raw string
   * gets offered twice under identical words, one pressed and one not. That is "so
   * which one did I pick?" back again, wearing the fix. */
  function normPath(value) {
    var raw = String(value || "");
    var norm = raw.replace(/\\/g, "/").replace(/\/+$/, "");
    if (norm) return norm;
    return raw ? "/" : "";
  }

  function splitPath(value) {
    var norm = normPath(value);
    var parts = norm.split("/");
    var name = parts.pop() || norm;
    return { name: name, parent: parts.join("/") };
  }

  function folderName(value) {
    return splitPath(value).name;
  }

  /* A path short enough to sit on one line, trimmed from the left so the file name — the
   * part that says which answer this is — always survives. Callers put the whole path in a
   * title attribute, so nothing is lost by shortening what is drawn. */
  function shortPath(value, max) {
    var text = normPath(value);
    var limit = max || 44;
    if (text.length <= limit) return text;
    var parts = text.split("/");
    var out = parts.pop() || text;
    if (out.length + 2 > limit) return "\u2026" + out.slice(out.length - (limit - 1));
    while (parts.length) {
      var wider = parts[parts.length - 1] + "/" + out;
      if (wider.length + 2 > limit) break;
      out = wider;
      parts.pop();
    }
    return "\u2026/" + out;
  }

  /* Where a folder is, in words. It never returns a path: that is the whole point.
   * The desktop is checked before the home folder because it is the place an operator
   * can actually point at on screen, and on most systems it sits inside home anyway. */
  function placePhrase(value) {
    var here = splitPath(value);
    var desk = placeOfKind("desktop");
    if (desk && here.parent === desk) return "on your desktop";
    if (App.home && here.parent === App.home) return "in your home folder";
    var up = splitPath(here.parent);
    if (!up.name) return "at the top level of this drive";
    if (desk && up.parent === desk) return "inside " + up.name + ", on your desktop";
    if (App.home && up.parent === App.home) return "inside " + up.name + ", in your home folder";
    return "inside a folder called " + up.name;
  }

  /* The single phrase for a destination. Every option label and the readout that
   * confirms the choice are built from this one function, so the words on the option
   * the operator picked and the words in the confirmation can never disagree. */
  function placeLabel(value) {
    return "a folder called " + folderName(value) + ", " + placePhrase(value);
  }

  /* A place the brain's folder goes into, in words: "on your desktop", "in your home
   * folder", or "in a folder called X, ...". The wizard's chips and its readout share it. */
  function placeWords(value) {
    var norm = normPath(value);
    if (norm && norm === normPath(placeOfKind("desktop"))) return "on your desktop";
    if (App.home && norm === normPath(App.home)) return "in your home folder";
    if (!splitPath(norm).parent) return "at the top level of this drive";
    return "in " + placeLabel(value);
  }

  function sentence(text) {
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  /* ================================================================== shell */

  var VIEWS = ["boot", "wizard", "interview", "attach", "dashboard", "commands"];

  function setView(name) {
    App.view = name;
    VIEWS.forEach(function (id) {
      show($(id), id === name);
    });
    var onBrain = name === "dashboard" || name === "commands";
    show($("tabs"), onBrain);
    show($("btn-refresh"), onBrain);
    renderTopbarName();
    ["dashboard", "commands"].forEach(function (id) {
      var tab = $("tab-" + id);
      var selected = id === name;
      tab.setAttribute("aria-selected", selected ? "true" : "false");
      tab.tabIndex = selected ? 0 : -1;
    });
    window.scrollTo(0, 0);
  }

  function wireTabs() {
    // Each tab's id names its panel, so the mapping lives in one place.
    var views = ["dashboard", "commands"];
    var tabs = views.map(function (name) {
      return $("tab-" + name);
    });
    tabs.forEach(function (tab, index) {
      tab.addEventListener("click", function () {
        closeDrawer();
        setView(views[index]);
      });
      tab.addEventListener("keydown", function (event) {
        var next = null;
        // The list is stacked in the sidebar, so the vertical arrows work as well as the
        // horizontal ones the tablist pattern started with.
        if (event.key === "ArrowRight" || event.key === "ArrowDown") {
          next = tabs[(index + 1) % tabs.length];
        } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
          next = tabs[(index + tabs.length - 1) % tabs.length];
        }
        else if (event.key === "Home") next = tabs[0];
        else if (event.key === "End") next = tabs[tabs.length - 1];
        if (!next) return;
        event.preventDefault();
        setView(views[tabs.indexOf(next)]);
        next.focus();
      });
    });
    $("btn-refresh").addEventListener("click", function () {
      closeDrawer();
      refresh(true);
    });
    $("iv-exit").addEventListener("click", leaveInterview);
  }

  /* ================================================================ sidebar */

  /* The left panel: every brain the operator has, the section tabs, Refresh. On a
   * narrow screen the same panel is a drawer under the bar; `drawer.open` is the one
   * fact about it, and only the Menu button can set it. */
  var drawer = { open: false };

  function hasClass(node, name) {
    return (" " + (node.className || "") + " ").indexOf(" " + name + " ") !== -1;
  }

  function setClass(node, name, on) {
    var names = (node.className || "").split(/\s+/).filter(function (item) {
      return item && item !== name;
    });
    if (on) names.push(name);
    node.className = names.join(" ");
  }

  function openDrawer() {
    drawer.open = true;
    setClass($("sidebar"), "sidebar--open", true);
    $("btn-menu").setAttribute("aria-expanded", "true");
    // The page behind the drawer is out of reach while it is open: no Tab stop lands
    // on it, no reader announces it, and a tap on the scrim closes the drawer.
    $("main").inert = true;
    $("main").setAttribute("aria-hidden", "true");
    $("scrim").removeAttribute("hidden");
    // Focus lands inside the drawer, on the control that closes it again.
    $("btn-drawer-close").focus();
  }

  /* Closing is safe to call from anywhere: when the panel is simply the sidebar, in
   * the flow of the page, there is nothing to close and focus stays where it was. */
  function closeDrawer() {
    if (!drawer.open) return;
    drawer.open = false;
    setClass($("sidebar"), "sidebar--open", false);
    $("btn-menu").setAttribute("aria-expanded", "false");
    $("main").inert = false;
    $("main").removeAttribute("aria-hidden");
    $("scrim").setAttribute("hidden", "");
    $("btn-menu").focus();
  }

  function wireSidebar() {
    $("btn-menu").setAttribute("aria-expanded", "false");
    $("btn-menu").addEventListener("click", function () {
      if (drawer.open) closeDrawer();
      else openDrawer();
    });
    $("btn-drawer-close").addEventListener("click", closeDrawer);
    $("scrim").addEventListener("click", closeDrawer);
    // Escape closes the drawer from inside it, and from anywhere else on the page: the
    // second listener is a no-op once the first has closed it.
    function escapeCloses(event) {
      if (event.key !== "Escape" || !drawer.open) return;
      event.preventDefault();
      closeDrawer();
    }
    $("sidebar").addEventListener("keydown", escapeCloses);
    document.addEventListener("keydown", escapeCloses);
    $("btn-new-brain").addEventListener("click", function () {
      closeDrawer();
      startWizard(suggestedPlace());
    });
    $("btn-attach-folder").addEventListener("click", function () {
      closeDrawer();
      attachFolder();
    });
  }

  /* The name of the brain on screen, in the bar. Empty while nothing is open. */
  function renderTopbarName() {
    var node = $("topbar-brain");
    if (!node) return;
    var onBrain = App.view === "dashboard" || App.view === "commands";
    node.textContent = onBrain ? activeBrainName() : App.view === "wizard" ? "Setting up a brain" : "";
  }

  function activeBrainName() {
    if (App.status && App.status.business && App.status.business.name) {
      return App.status.business.name;
    }
    var known = brainAt(App.path);
    if (known && known.name) return known.name;
    return App.path ? folderName(App.path) : "";
  }

  function brainAt(path) {
    var key = normPath(path);
    return (
      App.brains.filter(function (brain) {
        return normPath(brain.path) === key;
      })[0] || null
    );
  }

  /* The list is names and words, like the found-brains note: the path rides in the
   * title. The active brain carries a text marker as well as its colour; a brain whose
   * folder is gone stays listed, greyed, with "not found" and a Forget; one whose folder
   * is there but no longer holds a brain gets the same treatment, tagged "not a brain";
   * one from an older layout is tagged "needs attach" and opens the attach screen
   * instead. Redrawing replaces the pressed button, so focus follows the brain it was on. */
  function renderSidebar() {
    var host = $("brains");
    if (!host) return;
    var focusedPath = null;
    var focused = document.activeElement;
    if (focused && focused.closest && focused.closest("#brains")) {
      focusedPath = focused.getAttribute("title");
    }
    var active = normPath(App.path);
    var seen = {};
    App.brains.forEach(function (brain) {
      var key = String(brain.name || "").trim().toLowerCase();
      seen[key] = (seen[key] || 0) + 1;
    });
    var items = App.brains.map(function (brain) {
      var name = brain.name || folderName(brain.path);
      var twin = seen[String(brain.name || "").trim().toLowerCase()] > 1;
      var isActive = !!active && normPath(brain.path) === active;
      var gone = brain.exists === false;
      // An older server sends no is_brain; only an explicit false means "not a brain".
      var hollow = !gone && brain.is_brain === false && !brain.attachable;
      var missing = gone || hollow;
      var tags = [];
      if (isActive) tags.push(el("span", { class: "pill pill--accent brain__tag", text: "current" }));
      if (gone) tags.push(el("span", { class: "pill brain__tag", text: "not found" }));
      else if (hollow) tags.push(el("span", { class: "pill brain__tag", text: "not a brain" }));
      else if (brain.attachable) {
        tags.push(el("span", { class: "pill pill--warn brain__tag", text: "needs attach" }));
      }
      var sub = gone
        ? "Folder is missing"
        : hollow
          ? "No brain in this folder"
          : brain.attachable
            ? "Older layout"
            : MODE_SHORT[brain.mode] || brain.mode || "";
      if (twin) sub = folderName(brain.path) + (sub ? " \u00b7 " + sub : "");
      var open = el(
        "button",
        {
          class: "brain__open",
          type: "button",
          title: brain.path,
          "aria-current": isActive ? "true" : null,
          "aria-disabled": missing ? "true" : null,
          on: {
            click: function () {
              if (missing) return;
              closeDrawer();
              if (brain.attachable) attachBrain(brain.path, brain.name);
              else if (!isActive) switchBrain(brain.path);
              else setView("dashboard");
            },
          },
        },
        [
          el("span", { class: "brain__name" }, [el("span", { text: name })].concat(tags)),
          sub ? el("span", { class: "brain__sub", text: sub }) : null,
        ]
      );
      var kids = [open];
      if (missing) {
        kids.push(
          el("button", {
            class: "brain__forget",
            type: "button",
            text: "Forget",
            title: brain.path,
            "aria-label": "Forget " + name,
            on: {
              click: function () {
                forgetBrain(brain.path);
              },
            },
          })
        );
      }
      return el("li", { class: "brain" }, kids);
    });
    fill(host, items.length ? items : [el("p", { class: "brains__empty", text: "No brains yet." })]);
    var setUp = $("btn-new-brain") && $("btn-new-brain").querySelector("span");
    if (setUp) setUp.textContent = items.length ? "Set up another brain" : "Set up a brain";
    show($("sidebar"), true);
    renderTopbarName();
    if (!focusedPath) return;
    var again = Array.prototype.filter.call(host.querySelectorAll("button"), function (node) {
      return node.getAttribute("title") === focusedPath;
    })[0];
    if (again) again.focus();
  }

  function takeBrains(res) {
    if (res.ok && res.data && Array.isArray(res.data.brains)) {
      App.brains = res.data.brains;
      renderSidebar();
      return true;
    }
    return false;
  }

  /* Redraw the list from what is on disk now. Best effort, the same as the rest. */
  function refreshBrains() {
    return request("/api/state").then(takeBrains, function () {
      return false;
    });
  }

  /* Tell the registry this brain was opened just now. Best effort: the sidebar redraws
   * from the answer, and a refused request changes nothing on screen. */
  function rememberBrain(path) {
    return request("/api/brains", "POST", { op: "remember", path: path }).then(takeBrains, function () {
      return false;
    });
  }

  function forgetBrain(path) {
    var known = brainAt(path);
    var name = (known && known.name) || folderName(path);
    return request("/api/brains", "POST", { op: "forget", path: path }).then(
      function (res) {
        if (!takeBrains(res)) return;
        // The Forget button is gone with its row; say what happened and keep the
        // keyboard in the list.
        announce("Forgot " + name + ".");
        var first = $("brains").querySelector("button");
        if (first) first.focus();
      },
      function () {
        announce("Could not forget " + name + ". The local app did not answer.");
      }
    );
  }

  /* Make `path` the brain on screen: the dashboard, the Commands default path and every
   * command target it from here on. The state for that root comes from one request; an
   * older server that only answers for its own folder falls back to the two-command
   * refresh. A folder from an older layout goes to the attach screen instead, and the
   * brain that was open stays open behind it. */
  function switchBrain(path, name) {
    return request("/api/state?path=" + encodeURIComponent(path)).then(
      function (res) {
        var data = res.ok && res.data && res.data.schema ? res.data : null;
        if (data && data.attachable) {
          attachBrain(path, name);
          return null;
        }
        if (!data && res.status === 400) {
          // The server refused the folder: gone, or not one it may open. Nothing has
          // moved, so the brain on screen stays; the list is redrawn from disk so the
          // row says "not found" instead of inviting the same press again.
          var known = brainAt(path);
          var label = (known && known.name) || folderName(path) || "that brain";
          toast("Could not open " + label + ": the folder is missing or not allowed.");
          announce("Could not open " + label + ". The folder is missing or not allowed.");
          refreshBrains();
          return null;
        }
        App.path = path;
        remember(path);
        if (cmd.current && cmd.builtFor !== App.path) selectCommand(cmd.current.command);
        if (!data || normPath(data.root) !== normPath(path)) return refresh(true);
        App.state = data;
        App.specs = data.command_specs || App.specs;
        App.status = data.status;
        App.doctor = data.doctor;
        if (Array.isArray(data.brains)) App.brains = data.brains;
        rememberBrain(path);
        renderSidebar();
        if (!data.is_brain || !App.status || App.status.repo_state === "absent") {
          startWizard(preferredStart(path));
          return null;
        }
        renderDashboard();
        if (App.view !== "commands") setView("dashboard");
        announce("Now showing " + activeBrainName() + ".");
        return data;
      },
      function (error) {
        fatal(
          "The local app is not answering",
          "Nothing is lost: your files are on disk. Start the app again from the terminal, then reload this page.",
          String(error)
        );
        return null;
      }
    );
  }

  /* --------------------------------------------------- attaching a folder */

  var attach = { path: "", back: "" };

  /* The attach screen: what `mos attach` would change, read back from the real plan,
   * and one button to run it. Nothing is written until that button is pressed. */
  function attachBrain(path, hint) {
    // An older layout has no business_name the server can report; the caller that
    // found it (the sidebar, the found-brains note, the folder list) knows its name.
    var entry = brainAt(path);
    var name = hint || (entry && entry.name) || folderName(path) || "this folder";
    attach.path = path;
    if (App.view !== "attach") attach.back = App.view;
    $("attach-title").textContent = "Attach " + name;
    $("attach-lede").textContent =
      "This folder holds a brain from an older layout. Attaching brings it up to the current " +
      "structure so the app and the assistants can read it. Here is exactly what would change.";
    fill($("attach-body"), note("info", "info", ["Working out the changes\u2026"]));
    setView("attach");
    run("attach", { path: path, plan: true }).then(function (result) {
      if (attach.path !== path) return;
      var envelope = result.envelope;
      var actions = [];
      if (envelope && envelope.ok) {
        var go = el("button", { class: "btn btn--primary", type: "button", text: "Attach this brain" });
        go.addEventListener("click", function () {
          if (blocked(go)) return;
          busy(go, true, "Attaching");
          run("attach", { path: path, yes: true }).then(function (applied) {
            if (attach.path !== path) return;
            if (!applied.envelope || !applied.envelope.ok) {
              fill($("attach-body"), [
                el("div", { class: "readout" }, [
                  el("div", { class: "card" }, [resultCard(applied, { title: "What stopped it" })]),
                ]),
                el("div", { class: "btn-row" }, [leaveAttachButton()]),
              ]);
              land($("attach-title"), resultSummary(applied, "Attach " + name));
              return;
            }
            announce("Attached. Opening " + name + ".");
            rememberBrain(path);
            switchBrain(path);
          });
        });
        actions.push(go);
      }
      actions.push(leaveAttachButton());
      fill($("attach-body"), [
        el("div", { class: "readout" }, [
          el("div", { class: "card" }, [
            resultCard(result, {
              title: "What would change",
              emptyChanges: "Nothing needs to change.",
            }),
          ]),
        ]),
        el("div", { class: "btn-row" }, actions),
      ]);
      land($("attach-title"), resultSummary(result, "Attach " + name));
    });
  }

  function leaveAttachButton() {
    return el("button", {
      class: "btn btn--secondary",
      type: "button",
      text: "Not now",
      on: { click: leaveAttach },
    });
  }

  /* Back to wherever the operator came from: the brain that stayed open, the wizard
   * step they were on, or the wizard fresh when there was nothing open at all. */
  function leaveAttach() {
    attach.path = "";
    var back = attach.back;
    if (back === "wizard" || back === "commands" || back === "interview") setView(back);
    else if (App.status && App.status.repo_state !== "absent") setView("dashboard");
    else startWizard(suggestedPlace());
  }

  /* "Attach a folder…": the operating system's own folder window when one can open,
   * answered with the attach screen for the chosen folder. Where no window can open,
   * or the one asked for fails, step 1 of the wizard stands in: its in-page list and
   * its found-brains note both open a folder through the same attach screen. */
  function attachFolder() {
    if (!pickerAvailable()) {
      startWizard(suggestedPlace());
      openBrowse(PICKER_FALLBACK);
      return;
    }
    // One window at a time, shared with step 1's button: a second press while the
    // first window is up must neither stack a window nor open the in-page list.
    if (picking) {
      announce(PICKER_BUSY);
      return;
    }
    picking = true;
    announce("Waiting for the folder window.");
    request("/api/pick-folder", "POST", { start: suggestedPlace() || null }).then(
      function (res) {
        picking = false;
        var data = res.ok && res.data ? res.data : null;
        if (data && typeof data.path === "string" && data.path) {
          attachBrain(data.path);
          return;
        }
        if (data && data.busy) {
          announce(PICKER_BUSY);
          return;
        }
        if (data && data.cancelled) {
          announce("No folder chosen.");
          return;
        }
        startWizard(suggestedPlace());
        openBrowse(PICKER_FALLBACK);
      },
      function () {
        picking = false;
        startWizard(suggestedPlace());
        openBrowse(PICKER_FALLBACK);
      }
    );
  }

  /* ================================================ shared result rendering */

  function severityIcon(severity) {
    if (severity === "error") return { name: "alert", cls: "row__icon--err" };
    if (severity === "warning") return { name: "alert", cls: "row__icon--warn" };
    return { name: "info", cls: "row__icon--info" };
  }

  function severityPill(severity) {
    if (severity === "error") return "pill pill--err";
    if (severity === "warning") return "pill pill--warn";
    return "pill";
  }

  /* One plain sentence per checker code, and what to do about it. The checker's own
   * messages are written for a terminal and a maintainer; the operator reading this page
   * is neither. `one` and `many` take the count of findings that share the code; `fix`
   * is the recovery, in words. A code that is not here falls back to the checker's own
   * message, so a new finding is never hidden — it is only un-translated. Authored copy,
   * like heroPlan: facts (counts, paths) come from the envelope; these sentences are ours. */
  var FINDING_COPY = {
    "no-catalog": {
      one: "The catalogue has not been built yet.",
      many: "The catalogue has not been built yet.",
      fix: "Searching still works; it reads every document instead. Rebuilding the navigation makes it faster.",
    },
    "stale-catalog": {
      one: "The catalogue is behind the documents on disk.",
      many: "The catalogue is behind the documents on disk.",
      fix: "Rebuilding the navigation brings it back in step. Nothing is written until you confirm.",
    },
    "missing-file": {
      one: "A required file is missing.",
      many: "{n} required files are missing.",
      fix: "Setting the brain up again adds only what is missing and leaves every answer as it is.",
    },
    "missing-directory": {
      one: "A required folder is missing.",
      many: "{n} required folders are missing.",
      fix: "Setting the brain up again adds only what is missing and leaves every answer as it is.",
    },
    "file-discovered": {
      one: "A required answer lives in a file of your own naming.",
      many: "{n} required answers live in files of your own naming.",
      fix: "It counts as answered. The interview writes to the expected place whenever you change it.",
    },
    "missing-frontmatter": {
      one: "A document has no summary header yet.",
      many: "{n} documents have no summary header yet.",
      fix:
        "The header is a short block at the top saying what the document is and when it was " +
        "written; assistants read it before the body. Saving an answer from the interview adds " +
        "one, or ask your assistant to add the rest.",
    },
    "unlinked-document": {
      one: "A document links to nothing else.",
      many: "{n} documents link to nothing else.",
      fix:
        "Links are how an assistant moves between related documents. The related tool " +
        "proposes them and writes nothing until you apply.",
    },
    "output-without-sources": {
      one: "A deliverable does not say what it was built from.",
      many: "{n} deliverables do not say what they were built from.",
      fix: "Add the sources it drew on to its summary header.",
    },
    "missing-connective-key": {
      one: "A document is not connected to anything.",
      many: "{n} documents are not connected to anything.",
      fix: "Its summary header needs a sources, related, or produced-by line.",
    },
    "unknown-top-level": {
      one: "A file or folder sits at the top level where the brain does not expect one.",
      many: "{n} files or folders sit at the top level where the brain does not expect them.",
      fix: "The migrate tool works out where each one belongs and moves it when you say so.",
    },
    "invalid-dated-artifact": {
      one: "A folder in the log is not named by date.",
      many: "{n} folders in the log are not named by date.",
      fix: "Log folders are named year-month-day-topic so they sort by when they happened.",
    },
    "invalid-year": {
      one: "A folder in the log is not named for a year.",
      many: "{n} folders in the log are not named for a year.",
      fix: "Log years are four digits.",
    },
    "invalid-quarter": {
      one: "A folder in the log is not named for a quarter.",
      many: "{n} folders in the log are not named for a quarter.",
      fix: "Quarters are Q1 to Q4.",
    },
    "invalid-month": {
      one: "A folder in the log is not named for a month.",
      many: "{n} folders in the log are not named for a month.",
      fix: "Months are two digits, 01 to 12.",
    },
    "invalid-report-month": {
      one: "A report folder is not named for a month.",
      many: "{n} report folders are not named for a month.",
      fix: "Report folders are named year-month.",
    },
    "missing-or-invalid-config": {
      one: "The brain's settings file is missing or unreadable.",
      many: "The brain's settings file is missing or unreadable.",
      fix: "Setting the brain up again writes a fresh one and leaves every answer as it is.",
    },
    "unsupported-schema": {
      one: "This brain was made by a version the app does not recognise.",
      many: "This brain was made by a version the app does not recognise.",
      fix: "Update marketing-os, then check again.",
    },
    "missing-client-registry": {
      one: "An agency brain needs a client list, and this one has none.",
      many: "An agency brain needs a client list, and this one has none.",
      fix: "Setting the brain up again adds it.",
    },
    "set-mode-agency": {
      one: "This brain holds a client list but is not set up as an agency.",
      many: "This brain holds a client list but is not set up as an agency.",
      fix: "Change its mode to agency in the settings file, or remove the client list.",
    },
    "unexpected-clients-folder": {
      one: "There is a clients folder, but only an agency brain keeps one.",
      many: "There is a clients folder, but only an agency brain keeps one.",
      fix: "Move it out, or set the brain up as an agency.",
    },
    "invalid-type": {
      one: "A document's summary header names a kind of document the brain does not use.",
      many: "{n} documents' summary headers name a kind of document the brain does not use.",
      fix: "The kinds the brain uses are listed in the contract at the root of the brain.",
    },
    "invalid-status": {
      one: "A document's summary header names a status the brain does not use.",
      many: "{n} documents' summary headers name a status the brain does not use.",
      fix: "The statuses the brain uses are listed in the contract at the root of the brain.",
    },
    "skill-conflict": {
      one: "Something that is not a shared skill sits where a skill belongs.",
      many: "{n} things that are not shared skills sit where skills belong.",
      fix: "Move it, then sync the skills again.",
    },
    "runtime-not-ready": {
      one: "Claude Code and Codex cannot both see the skills.",
      many: "Claude Code and Codex cannot both see the skills.",
      fix: "Sync the skills to give each assistant its own copy.",
    },
    "not-marketing-os": {
      one: "This folder is not a brain yet.",
      many: "This folder is not a brain yet.",
      fix: "Set one up here, or point at the right folder.",
    },
  };

  /* Findings that share a code are one thing that is wrong in several places, and are
   * read as one row: ten documents without a header is one sentence and a list of ten
   * paths, not ten sentences. Order is the checker's, errors first, first appearance. */
  function groupFindings(findings) {
    var groups = [];
    var byKey = {};
    findings.forEach(function (item) {
      if (!item) return;
      var key = (item.code || "") + "|" + (item.severity || "");
      var group = byKey[key];
      if (!group) {
        group = byKey[key] = {
          code: item.code || "",
          severity: item.severity || "info",
          message: item.message || "",
          items: [],
        };
        groups.push(group);
      }
      group.items.push(item);
    });
    return groups;
  }

  function findingWords(group) {
    var copy = FINDING_COPY[group.code];
    var n = group.items.length;
    if (!copy) return { title: group.message, fix: "" };
    var title = n === 1 ? copy.one : copy.many.replace("{n}", String(n));
    return { title: title, fix: copy.fix };
  }

  function findingRow(group) {
    var look = severityIcon(group.severity);
    var words = findingWords(group);
    var paths = group.items
      .map(function (item) {
        return item.path;
      })
      .filter(Boolean);
    var body = [el("p", { class: "row__msg", text: words.title })];
    if (words.fix) body.push(el("p", { class: "row__sub", text: words.fix }));
    // Envelope-reported file locations: the checker's own data, not our prose.
    if (paths.length === 1) {
      body.push(el("p", { class: "row__path", text: paths[0] }));
    } else if (paths.length > 1) {
      body.push(
        el("details", { class: "row__which" }, [
          el("summary", {}, [icon("down", "disc"), el("span", { text: "Show which " + paths.length })]),
          el(
            "ul",
            { class: "row__paths", role: "list" },
            paths.map(function (path) {
              return el("li", { class: "row__path", text: path });
            })
          ),
        ])
      );
    }
    return el("li", { class: "row" }, [
      icon(look.name, "row__icon " + look.cls),
      el("div", { class: "row__body" }, body),
      el("span", { class: "row__end" }, [
        el("span", { class: severityPill(group.severity), text: group.severity }),
      ]),
    ]);
  }

  function findingRows(findings) {
    return el("ul", { class: "rows", role: "list" }, groupFindings(findings).map(findingRow));
  }

  function emptyState(title, body, iconName) {
    return el("div", { class: "empty" }, [
      icon(iconName || "check"),
      el("p", { class: "empty__title", text: title }),
      body ? el("p", { class: "empty__body", text: body }) : null,
    ]);
  }

  /* Everything technical — paths, command lines, raw envelopes, diffs — lives in one of
   * these, closed by default, so no filesystem path lands in plain-language copy. */
  function tech(kids, label) {
    return el("details", { class: "tech" }, [
      el("summary", { class: "tech__sum" }, [
        icon("down", "disc"),
        el("span", { text: label || "Show the technical bit" }),
      ]),
      el("div", { class: "tech__body" }, kids),
    ]);
  }

  function terminal(line, caption) {
    if (!line) return null;
    return el("div", { class: "term-wrap" }, [
      caption ? el("p", { class: "term__cap", text: caption }) : null,
      el("div", { class: "term" }, [
        el("span", { class: "term__prompt", text: "$", "aria-hidden": "true" }),
        el("code", { class: "term__line", text: line }),
        el("button", {
          class: "term__copy",
          type: "button",
          text: "Copy",
          on: {
            click: function () {
              copy(line, "Command copied");
            },
          },
        }),
      ]),
    ]);
  }

  function scrollRegion(tag, cls, label, kids) {
    // A scroll container with nothing focusable inside is unreachable by keyboard on
    // engines that have not shipped automatic focusability. Name it and let it take tab.
    return el(
      tag,
      { class: cls, role: "region", "aria-label": label, tabindex: "0" },
      kids
    );
  }

  function changesList(changes, label) {
    return scrollRegion(
      "ul",
      "changes",
      label || "Every file this touches",
      changes.map(function (change) {
        return el("li", { text: change });
      })
    );
  }

  function note(kind, iconName, kids, actions) {
    return el("div", { class: "note note--" + kind }, [
      icon(iconName),
      el("div", { class: "note__body" }, [
        el("p", {}, kids),
        actions && actions.length ? el("div", { class: "note__actions" }, actions) : null,
      ]),
    ]);
  }

  function subhead(text) {
    return el("h3", { class: "subhead", text: text });
  }

  function rawPre(envelope) {
    return scrollRegion("pre", "raw__pre", "The raw result", [
      el("code", { text: JSON.stringify(envelope, null, 2) }),
    ]);
  }

  /* One envelope, rendered the way a person reads it. */
  function resultCard(result, options) {
    var opts = options || {};
    var envelope = result.envelope;
    var body = el("div", {});

    if (!envelope) {
      add(
        body,
        el("h2", { class: "result__title", text: opts.title || "What came back" })
      );
      add(
        body,
        note("err", "alert", [
          el("strong", { text: "Nothing came back. " }),
          result.transport || "The command did not return a result.",
        ])
      );
      return body;
    }

    var findings = findingsOf(envelope);
    var errors = bySeverity(envelope, "error");
    var warnings = bySeverity(envelope, "warning");
    var changes = changesOf(envelope);

    add(
      body,
      el("div", { class: "result__head" }, [
        el("h2", { class: "result__title", text: opts.title || "What came back" }),
        el("span", {
          class: envelope.ok ? "pill pill--ok" : "pill pill--err",
          text: !envelope.ok
            ? "Needs attention"
            : envelope.planned
              ? "Preview only, nothing written"
              : "Done",
        }),
        errors.length
          ? el("span", { class: "pill pill--err", text: plural(errors.length, "problem") })
          : null,
        warnings.length
          ? el("span", { class: "pill pill--warn", text: plural(warnings.length, "warning") })
          : null,
        el("span", { class: "result__elapsed", text: (result.elapsed / 1000).toFixed(1) + "s" }),
      ])
    );

    if (findings.length) {
      add(body, subhead(envelope.ok ? "Worth knowing" : "What is wrong"));
      add(body, findingRows(findings));
    }

    if (changes.length) {
      add(body, subhead(envelope.planned ? "Would change" : "Changed"));
      add(
        body,
        el("p", {
          class: "result__line",
          text:
            plural(changes.length, "file or folder", "files or folders") +
            (envelope.planned ? " would be touched." : " touched."),
        })
      );
      add(body, tech([changesList(changes)], "Show every one"));
    } else if (opts.emptyChanges) {
      add(body, subhead("Changes"));
      add(body, emptyState("Nothing to change", opts.emptyChanges));
    }

    // A preview's next step is the apply button beside it; the envelope's own next
    // action only matters once something has actually happened.
    if (!envelope.planned && envelope.next_action && envelope.next_action.id !== "none") {
      add(body, subhead("Next"));
      add(body, el("p", { class: "result__next" }, [icon("right"), envelope.next_action.reason]));
    }

    add(
      body,
      tech(
        [terminal(result.commandLine, "The exact command this ran"), rawPre(envelope)],
        "Show the command line and the raw result"
      )
    );
    return body;
  }

  /* A one-line state summary for #live. A screen reader gets what changed, not the whole
   * re-rendered subtree. */
  function resultSummary(result, label) {
    var envelope = result.envelope;
    if (!envelope) return label + " did not return a result.";
    var errors = bySeverity(envelope, "error");
    var changes = changesOf(envelope);
    if (errors.length) {
      return label + ": " + plural(errors.length, "problem") + " found. " + (errors[0].message || "");
    }
    if (changes.length) {
      return (
        label +
        ": " +
        plural(changes.length, "file or folder", "files or folders") +
        (envelope.planned ? " would be touched. Nothing written yet." : " touched.")
      );
    }
    return label + ": done, nothing to change.";
  }

  /* --- busy and blocked buttons ----------------------------------------- */

  /* Never set the disabled property on a button the operator might be standing on: every
   * engine drops focus to <body> when the focused element is disabled. aria-disabled keeps
   * it in the tab order, and the click handler explains the block instead of doing nothing. */
  function blocked(button) {
    return button.getAttribute("aria-disabled") === "true";
  }

  function setBlocked(button, isBlocked, describedBy) {
    button.setAttribute("aria-disabled", isBlocked ? "true" : "false");
    if (describedBy) button.setAttribute("aria-describedby", describedBy);
  }

  function busy(button, isBusy, label) {
    var hadFocus = document.activeElement === button;
    button.setAttribute("aria-disabled", isBusy ? "true" : "false");
    button.setAttribute("aria-busy", isBusy ? "true" : "false");
    if (isBusy) {
      fill(button, [el("span", { class: "btn__spin", "aria-hidden": "true" }), label || "Working"]);
    }
    if (hadFocus && document.activeElement !== button) button.focus();
  }

  /* ================================================================= wizard */

  var wiz = {
    step: 1,
    mode: null,
    place: "", // the folder the brain's own folder goes into; never the brain itself
    probe: null,
    nameProbe: null,
    plan: null,
    planKey: "",
    applying: false,
    done: null,
  };

  function slugify(value) {
    var slug = value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
    return slug || "business";
  }

  function wizName() {
    return $("in-name").value.trim();
  }

  /* The brain's folder is named after the business, never after the engine: marketing-os
   * is the product, not the brain. Lowercase, punctuation and spaces become one dash. */
  function brainSlug() {
    var name = wizName();
    return name ? slugify(name) : "business-brain";
  }

  function wizPlace() {
    return wiz.place;
  }

  function setPlace(value) {
    wiz.place = String(value || "").trim();
    $("in-path").value = wiz.place;
  }

  /* The final path: the slug inside the place. An operator who typed the full path,
   * slug included, gets exactly what they typed rather than the slug twice over. */
  function wizPath() {
    var place = wizPlace();
    if (!place) return "";
    var slug = brainSlug();
    var norm = normPath(place);
    if (folderName(norm) === slug) return norm;
    return (norm === "/" ? "" : norm) + "/" + slug;
  }

  function wizAgency() {
    return $("in-agency").value.trim();
  }

  function onboardArgs(extra) {
    var args = { path: wizPath(), name: wizName(), mode: wiz.mode };
    if (wiz.mode === "client" && wizAgency()) args.agency = wizAgency();
    Object.keys(extra || {}).forEach(function (key) {
      args[key] = extra[key];
    });
    return args;
  }

  function planKey() {
    return [wizPath(), wiz.mode, wizAgency(), wizName()].join(" ");
  }

  /* The places worth offering, in the order the server ranked them: the desktop first
   * when the operator has one, the home folder last. Only the server can tell which
   * desktop is real, because under WSL the one that matters belongs to Windows. */
  function places() {
    var list = (App.state && App.state.places) || [];
    if (list.length) return list;
    // An older server sends no places, so the home folder found by `status ~` stands in.
    return App.home ? [{ path: App.home, kind: "home" }] : [];
  }

  function placeOfKind(kind) {
    var list = places();
    for (var i = 0; i < list.length; i++) {
      if (list[i].kind === kind) return list[i].path;
    }
    return "";
  }

  /* A real, human place: the best one the server found (the desktop, then home), never
   * the temporary directory the app happened to be started from. */
  function suggestedPlace() {
    var list = places();
    if (list.length) return list[0].path;
    if (App.home) return App.home;
    var root = (App.state && App.state.root) || "";
    return looksTemporary(root) ? "" : root;
  }

  /* A scratch directory the OS wipes is never a suggestion. */
  function looksTemporary(value) {
    return (
      /^\/(tmp|var\/folders|private\/var\/folders)(\/|$)/.test(value) ||
      /\/(Temp|tmp)(\/|$)/i.test(value)
    );
  }

  /* A folder the app was explicitly pointed at (`mos ui <path>` run from somewhere
   * else). It is offered as an alternative, never as the default: the default has to be
   * a place nobody needs to think about. */
  function pointedAt() {
    if (!App.state) return "";
    var root = App.state.root || "";
    if (!root || root === App.state.cwd) return "";
    if (App.home && (root === App.home || root === suggestedPlace())) return "";
    if (looksTemporary(root)) return "";
    return root;
  }

  /* Step 1 is a confirmation, not a decision: the answer is already chosen. */
  function preferredStart(candidate) {
    if (places().length) return suggestedPlace();
    if (!candidate || looksTemporary(candidate)) return suggestedPlace();
    return candidate;
  }

  function startWizard(defaultPlace) {
    wiz.step = 1;
    wiz.plan = null;
    wiz.planKey = "";
    wiz.done = null;
    wiz.nameProbe = null;
    wiz.applying = false;
    setPlace(defaultPlace || suggestedPlace());
    renderPathChips();
    renderFoundBrains();
    probePath(true);
    setView("wizard");
    goStep(1);
  }

  /* Suggestions are places, named in words. Every option is labelled with the same
   * phrase the confirmation uses, so the two can never contradict each other. The path
   * each one sets lives in its title attribute and in the field below, never in the
   * label. */
  function placeOptions() {
    var seen = {};
    var options = [];
    function offer(value) {
      var key = normPath(value);
      if (!key || seen[key]) return;
      seen[key] = true;
      options.push({ value: value, label: sentence(placeWords(value)) });
    }
    places().forEach(function (place) {
      offer(place.path);
    });
    offer(pointedAt());
    // Whatever is actually typed is always one of the options, and always the pressed
    // one, so exactly one option is selected at every moment.
    offer(wizPlace());
    return options;
  }

  /* Re-rendering replaces the very button that was clicked, which would drop focus to
   * <body> — the round-2 blocker, in a new place. Focus follows the option instead. */
  function renderPathChips(keepFocusOn) {
    var current = normPath(wizPlace());
    var nodes = placeOptions().map(function (option) {
      var pressed = !!current && normPath(option.value) === current;
      var chip = el("button", {
        class: "chip chip--place",
        type: "button",
        title: option.value,
        "aria-pressed": pressed ? "true" : "false",
        "data-place": option.label,
        on: {
          click: function () {
            setPlace(option.value);
            renderPathChips(option.value);
            probePath(true);
            updateFoot();
          },
        },
      });
      add(chip, [el("span", { class: "chip__tick", "aria-hidden": "true" }), option.label]);
      return chip;
    });
    fill($("path-chips"), nodes);
    if (!keepFocusOn) return;
    nodes.forEach(function (node) {
      if (node.getAttribute("title") === keepFocusOn) node.focus();
    });
  }

  /* Step 1 probes the place, not the brain's future folder: the question there is
   * whether the place itself is already a brain, which is worth opening instead. The
   * final path is probed again once the business has a name (see probeName). */
  var probeTimer = null;

  /* A full path starts at the top of a drive: "/...", "~" for the home folder, or a
   * Windows drive letter. Anything else is relative to wherever the app was started,
   * which is never the place the operator meant, so it is not even sent to be probed. */
  function isFullPath(value) {
    return /^(\/|~(\/|$)|[A-Za-z]:[\\/])/.test(String(value || ""));
  }

  function probePath(immediate) {
    window.clearTimeout(probeTimer);
    var value = wizPlace();
    if (!value) {
      wiz.probe = null;
      fill($("where-readout"), note("warn", "info", ["Open \u201cPut it somewhere else\u201d and pick a place."]));
      // The visible readout and the one a screen reader hears are the same readout.
      // Leaving the old "Ready: ..." here is the contradiction round 3 named, silent.
      $("where-live").textContent = "No place chosen yet.";
      renderFoundBrains();
      return Promise.resolve(null);
    }
    if (!isFullPath(value)) {
      wiz.probe = null;
      var partial = "That is not a full path. Start from the top of the drive, or use the folder window.";
      fill($("where-readout"), note("warn", "alert", [partial]));
      $("where-live").textContent = partial;
      renderFoundBrains();
      return Promise.resolve(null);
    }
    var work = function () {
      refreshFoundBrains(value);
      return run("status", { path: value }).then(function (result) {
        wiz.probe = { path: value, result: result };
        if (wizPlace() === value) renderProbe();
        return result;
      });
    };
    if (immediate) return work();
    return new Promise(function (resolve) {
      probeTimer = window.setTimeout(function () {
        // The "checking" note is written inside the debounce, not on every keystroke,
        // and #where-readout is not a live region, so typing is never narrated.
        fill($("where-readout"), note("info", "info", ["Checking that folder..."]));
        work().then(resolve);
      }, 320);
    });
  }

  /* Opening a brain is one move wherever the button lives: the found-brains note, the
   * readout for a typed path, the folder browser and the sidebar all switch to it. */
  function openBrain(path, name) {
    return switchBrain(path, name);
  }

  /* The brains already sitting in the chosen place, as the last look at that folder
   * reported them: the folder itself when it is a brain, then any child that is one.
   * Only the place the operator is pointing at is ever looked in; the wizard never
   * sweeps the home folder in the background. `place` is the folder the list is true
   * of, so a late answer for a place since abandoned is never drawn. */
  var found = { place: "", brains: [] };

  function brainsInFolder(data) {
    var list = [];
    function keep(path, entry, attachable) {
      list.push({ path: path, name: (entry && entry.name) || "", attachable: !!attachable });
    }
    if (data.is_brain || data.attachable) keep(data.path, data.brain, data.attachable);
    (data.children || []).forEach(function (child) {
      if (child.is_brain || child.attachable) keep(child.path, child.brain, child.attachable);
    });
    return list;
  }

  /* Ask the local app what is in `place` and redraw the note if that is still the place.
   * Callers are already debounced through probePath, so every place change asks once. */
  function refreshFoundBrains(place) {
    return request("/api/browse", "POST", { path: place }).then(
      function (res) {
        if (wizPlace() !== place) return;
        var ok = res.ok && res.data && typeof res.data.path === "string";
        found = { place: place, brains: ok ? brainsInFolder(res.data) : [] };
        renderFoundBrains();
      },
      function () {
        if (wizPlace() !== place) return;
        found = { place: place, brains: [] };
        renderFoundBrains();
      }
    );
  }

  /* Brains already in the chosen folder. Step 1 shows them so a second brain never gets
   * built beside one that exists. Names and place words only: the path rides in the
   * title attribute, the way the chips carry theirs. Two brains with one name are told
   * apart by their folder names. A brain from an older layout is tagged "needs attach"
   * and still opens. Nothing found, or a place not yet looked at, draws nothing. */
  function renderFoundBrains() {
    var host = $("where-found");
    if (!host) return;
    var place = wizPlace();
    var brains = place && found.place === place ? found.brains : [];
    if (!brains.length) {
      fill(host, []);
      return;
    }
    var seen = {};
    brains.forEach(function (brain) {
      var key = brain.name.trim().toLowerCase();
      seen[key] = (seen[key] || 0) + 1;
    });
    var openers = brains.map(function (brain) {
      var name = brain.name || "This brain";
      var label = placeLabel(brain.path);
      var text = "Open " + name;
      if (seen[brain.name.trim().toLowerCase()] > 1) text += " in " + folderName(brain.path);
      var button = el("button", {
        class: "btn btn--secondary",
        type: "button",
        title: brain.path,
        text: text,
        "aria-label": "Open " + name + ", " + label + (brain.attachable ? ", needs attach" : ""),
        on: {
          click: function () {
            openBrain(brain.path, brain.name);
          },
        },
      });
      if (!brain.attachable) return button;
      return el("span", { class: "found__item" }, [
        button,
        " ",
        el("span", { class: "pill pill--warn", text: "needs attach" }),
      ]);
    });
    var lede = [
      el("strong", { text: "Brains already in this folder (" + brains.length + "). " }),
      "You can open one instead of building another beside it.",
    ];
    fill(host, note("accent", "info", lede, openers));
  }

  function renderProbe() {
    renderFoundBrains();
    var probe = wiz.probe;
    if (!probe) return;
    var envelope = probe.result.envelope;
    if (!envelope) {
      fill(
        $("where-readout"),
        note("err", "alert", [probe.result.transport || "That place could not be read."])
      );
      $("where-live").textContent = "That place could not be read.";
      return;
    }
    var resolved = envelope.repo;
    if (envelope.repo_state && envelope.repo_state !== "absent") {
      var name = (envelope.business && envelope.business.name) || "A business";
      fill(
        $("where-readout"),
        note(
          "accent",
          "info",
          [
            el("strong", { text: "There is already a brain here. " }),
            name + " lives in " + placeLabel(resolved) + ". You can open it instead of "
            + "building a new one.",
          ],
          [
            el("button", {
              class: "btn btn--secondary",
              type: "button",
              text: "Open this brain",
              on: {
                click: function () {
                  openBrain(resolved, name);
                },
              },
            }),
          ]
        )
      );
      $("where-live").textContent = name + " already has a brain in that place.";
      return;
    }
    var label = placeWords(resolved);
    var readout = note("ok", "check", [
      el("strong", { text: "A new folder, named after your business, " + label + "." }),
      " It is created for you on step 4, and you can move it later.",
    ]);
    readout.setAttribute("data-place", sentence(label));
    readout.setAttribute("title", resolved);
    fill($("where-readout"), readout);
    $("where-live").textContent = "Ready: a new folder, named after your business, " + label + ".";
  }

  /* --- after step 3: the folder now has a name, so the final path can collide ---- */

  var nameProbeTimer = null;
  function probeName() {
    window.clearTimeout(nameProbeTimer);
    var value = wizPath();
    if (!wizName() || !value) {
      wiz.nameProbe = null;
      return Promise.resolve(null);
    }
    return new Promise(function (resolve) {
      nameProbeTimer = window.setTimeout(function () {
        run("status", { path: value }).then(function (result) {
          wiz.nameProbe = { path: value, result: result };
          if (wizPath() === value) {
            renderNameReadout();
            updateFoot();
          }
          resolve(result);
        });
      }, 320);
    });
  }

  /* The brain the final path already holds, if the probe found one there. */
  function nameCollision() {
    var probe = wiz.nameProbe;
    if (!probe || probe.path !== wizPath()) return null;
    var envelope = probe.result && probe.result.envelope;
    if (!envelope || !envelope.repo_state || envelope.repo_state === "absent") return null;
    return envelope;
  }

  /* ------------------------------------------------- choosing a folder */

  /* The in-page folder browser. It only ever lists directories the server describes,
   * one level at a time, and it names the current place in words: the path itself rides
   * in title attributes. Not a live region, because a whole list lands on every step. */
  var browse = { data: null, transport: "", reason: "" };

  /* The current place, said the way a person would. The desktop and the home folder are
   * named outright; anywhere else gets the same phrase the chips use. */
  function placeName(value) {
    var norm = normPath(value);
    if (norm && norm === normPath(placeOfKind("desktop"))) return "your desktop";
    if (App.home && norm === normPath(App.home)) return "your home folder";
    if (!splitPath(norm).parent) return "the top level of this drive";
    return placeLabel(value);
  }

  function browseOpen() {
    return !$("browse-panel").hasAttribute("hidden");
  }

  function browseTo(path, focusPath) {
    return request("/api/browse", "POST", { path: path || "" }).then(
      function (res) {
        var ok = res.ok && res.data && typeof res.data.path === "string";
        browse.data = ok ? res.data : null;
        browse.transport = ok ? "" : "The local app refused that request (HTTP " + res.status + ").";
        renderBrowse(focusPath);
      },
      function (error) {
        browse.data = null;
        browse.transport = "Could not reach the local app: " + error;
        renderBrowse(focusPath);
      }
    );
  }

  function toggleBrowse() {
    if (browseOpen()) {
      closeBrowse();
      return;
    }
    openBrowse("");
  }

  /* The panel opens with one sentence of reason when it is standing in for the folder
   * window that could not open; none when the operator asked for it outright. */
  function openBrowse(reason) {
    browse.reason = reason || "";
    show($("browse-panel"), true);
    $("btn-browse").setAttribute("aria-expanded", "true");
    // Start in the chosen place, so the operator lands where the suggestion points.
    browseTo(wizPlace() || "", "");
  }

  function closeBrowse() {
    browse.reason = "";
    show($("browse-panel"), false);
    $("btn-browse").setAttribute("aria-expanded", "false");
    $("btn-browse").focus();
  }

  /* "Put the brain here" chooses the place. The brain's own folder, named after the
   * business, goes inside it: the browser never invents a folder name of its own. */
  function chooseFolder(data) {
    setPlace(data.path);
    renderPathChips();
    probePath(true);
    updateFoot();
    $("where-live").textContent = "Chosen: " + placeWords(data.path) + ".";
    closeBrowse();
  }

  function browseItem(child) {
    var kids = [icon("folder"), el("span", { class: "browse__name", text: child.name })];
    if (child.is_brain) {
      var who = child.brain && child.brain.name ? ": " + child.brain.name : "";
      kids.push(el("span", { class: "pill pill--accent browse__badge", text: "brain" + who }));
    }
    return el("li", { class: "browse__row" }, [
      el("button", {
        class: "browse__item",
        type: "button",
        title: child.path,
        on: {
          click: function () {
            browseTo(child.path, "");
          },
        },
      }, kids),
    ]);
  }

  function browseAction(data) {
    if (data.is_brain) {
      var name = (data.brain && data.brain.name) || "A business";
      return [
        el("p", { class: "browse__note" }, [
          el("strong", { text: "There is already a brain here. " }),
          name + " lives in this folder.",
        ]),
        el("button", {
          class: "btn btn--secondary",
          type: "button",
          text: "Open this brain",
          title: data.path,
          on: {
            click: function () {
              openBrain(data.path, name);
            },
          },
        }),
      ];
    }
    if (data.error) return [];
    return [
      el("button", {
        class: "btn btn--primary",
        type: "button",
        text: "Put the brain here",
        title: data.path,
        on: {
          click: function () {
            chooseFolder(data);
          },
        },
      }),
    ];
  }

  /* Re-rendering replaces every button, so focus is placed on purpose: on the folder we
   * just came up out of when there is one, otherwise on the heading that says where we
   * are, so a screen reader hears the new place rather than silence. */
  function renderBrowse(focusPath) {
    var panel = $("browse-panel");
    var data = browse.data;
    if (!data) {
      fill(panel, note("err", "alert", [browse.transport || "That folder could not be read."]));
      return;
    }
    var up = el("button", {
      class: "btn btn--secondary",
      type: "button",
      title: data.parent || "",
      "aria-disabled": data.parent ? "false" : "true",
      on: {
        click: function () {
          if (data.parent) browseTo(data.parent, data.path);
        },
      },
    }, [icon("left"), "Up"]);
    var where = el("p", {
      class: "browse__where",
      tabindex: "-1",
      title: data.path,
      text: sentence(placeName(data.path)),
    });
    var kids = [el("div", { class: "browse__head" }, [up, where])];
    if (browse.reason) kids.unshift(note("info", "info", [browse.reason]));
    if (data.error) kids.push(note("warn", "alert", [data.error]));
    if (data.children.length) {
      kids.push(el("ul", { class: "browse__list", role: "list" }, data.children.map(browseItem)));
    } else if (!data.error) {
      kids.push(el("p", { class: "browse__empty", text: "No folders inside this one." }));
    }
    kids.push(el("div", { class: "browse__foot" }, browseAction(data)));
    fill(panel, kids);
    var target = where;
    Array.prototype.forEach.call(panel.querySelectorAll(".browse__item"), function (node) {
      if (focusPath && node.getAttribute("title") === focusPath) target = node;
    });
    target.focus();
  }

  /* --- the operating system's own folder window ---------------------------------- */

  /* The page cannot learn a path from a file input, so the local app opens the OS's
   * folder window itself and hands the answer back. Only the server knows whether one
   * can open here (a display, PowerShell, osascript, zenity...); the page asks once at
   * boot and falls back to the in-page browser above when the answer is no, or when a
   * window that should have opened did not. */
  var picking = false;

  function pickerAvailable() {
    return !!(App.state && App.state.picker);
  }

  var PICKER_FALLBACK = "The folder window could not open here, so pick from the list below.";
  // The server says this when a window is already up (another tab asked first, say).
  var PICKER_BUSY = "A folder window is already open. Finish with that one.";

  function pickFolder() {
    if (picking) return;
    picking = true;
    var readout = $("where-readout");
    // Kept, not re-probed: a closed window changes nothing, so the readout goes back
    // exactly as it was, without a word said.
    var kept = Array.prototype.slice.call(readout.childNodes);
    var restore = function () {
      fill(readout, kept);
    };
    fill(readout, note("info", "info", ["Waiting for the folder window\u2026"]));
    request("/api/pick-folder", "POST", { start: wizPlace() || null }).then(
      function (res) {
        picking = false;
        var data = res.ok && res.data ? res.data : null;
        if (data && typeof data.path === "string" && data.path) {
          pickedFolder(data.path);
          return;
        }
        restore();
        if (data && data.busy) {
          // Another window is up already; the answer will come through that one.
          announce(PICKER_BUSY);
          return;
        }
        if (data && data.cancelled) return;
        openBrowse(PICKER_FALLBACK);
      },
      function () {
        picking = false;
        restore();
        openBrowse(PICKER_FALLBACK);
      }
    );
  }

  /* The window answered with a place. The brain's own folder, named after the business,
   * goes inside it, the same as a chip or the in-page browser. */
  function pickedFolder(path) {
    setPlace(path);
    renderPathChips();
    probePath(true);
    updateFoot();
    $("where-live").textContent = "Folder chosen: " + placeName(path) + ".";
  }

  function wireWizard() {
    $("btn-browse").addEventListener("click", function () {
      if (pickerAvailable()) pickFolder();
      else toggleBrowse();
    });
    $("browse-panel").addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeBrowse();
    });
    $("in-path").addEventListener("input", function () {
      wiz.place = $("in-path").value.trim();
      renderPathChips();
      probePath();
      updateFoot();
    });

    Array.prototype.forEach.call(document.querySelectorAll('input[name="mode"]'), function (input) {
      input.addEventListener("change", function () {
        wiz.mode = input.value;
        var wantsAgency = input.value === "client";
        // Reveal, never steal focus: arrow keys move through a radio group, and yanking
        // the caret into a text field would trap the keyboard on "client". Say what
        // appeared instead, so the change is not silent.
        show($("agency-field"), wantsAgency);
        if (wantsAgency) {
          announce("An agency name is now required. The field is just below the options.");
        }
        updateFoot();
      });
    });

    $("in-agency").addEventListener("input", updateFoot);
    $("in-name").addEventListener("input", onNameInput);
    $("btn-back").addEventListener("click", function () {
      if (wiz.step > 1) goStep(wiz.step - 1);
    });
    $("btn-next").addEventListener("click", onNext);
  }

  function onNameInput() {
    renderNameReadout();
    probeName();
    updateFoot();
  }

  function renderNameReadout() {
    var value = wizName();
    var host = $("name-readout");
    if (!value) {
      fill(host, []);
      return;
    }
    var taken = nameCollision();
    if (taken) {
      var who = (taken.business && taken.business.name) || "A business";
      fill(
        host,
        note(
          "accent",
          "info",
          [
            el("strong", { text: "There is already a brain here. " }),
            who + " lives in " + placeLabel(taken.repo) + ". Open it instead, or use a "
              + "different name.",
          ],
          [
            el("button", {
              class: "btn btn--secondary",
              type: "button",
              text: "Open this brain",
              title: taken.repo,
              on: {
                click: function () {
                  openBrain(taken.repo);
                },
              },
            }),
          ]
        )
      );
      return;
    }
    var repo =
      wiz.mode === "client" && wizAgency()
        ? slugify(wizAgency()) + "-" + slugify(value)
        : slugify(value) + "-hq";
    var target = wizPath();
    var readout = note("info", "info", [
      "Its folder will be called ",
      el("code", { text: folderName(target) }),
      ", " + placeWords(splitPath(target).parent) + ".",
    ]);
    readout.setAttribute("title", target);
    fill(host, [
      readout,
      tech(
        [
          el("p", { class: "tech__line" }, [
            "If you ever put this brain on GitHub, ",
            el("code", { text: repo }),
            " is the name it suggests.",
          ]),
        ],
        "If you use GitHub"
      ),
    ]);
  }

  var STEP_STATE = { done: "Completed", current: "Current step", todo: "Not started" };

  function goStep(step) {
    wiz.step = step;
    Array.prototype.forEach.call(document.querySelectorAll(".step"), function (node) {
      show(node, Number(node.getAttribute("data-step")) === step);
    });
    Array.prototype.forEach.call($("stepper").children, function (item) {
      var n = Number(item.getAttribute("data-step"));
      var state = n < step ? "done" : n === step ? "current" : "todo";
      item.setAttribute("data-state", state);
      // Colour alone never carries the state: CSS swaps the digit for a tick, and the
      // word below survives the mobile rule that hides the label.
      var word = item.querySelector(".stepper__state");
      if (word) word.textContent = STEP_STATE[state] + ": ";
      if (n === step) item.setAttribute("aria-current", "step");
      else item.removeAttribute("aria-current");
    });
    updateFoot();
    if (step === 4) loadPlan();
    if (step === 5) applyPlan();
    var heading = document.querySelector('.step[data-step="' + step + '"] .step__title');
    if (heading) land(heading, "Step " + step + " of 5. " + heading.textContent);
  }

  var REASSURANCE = {
    1: "Nothing is written until you confirm on step 4.",
    2: "You can change this later.",
    3: "You can rename the business later.",
    4: "Nothing has been written yet.",
    5: "",
  };

  /* Why Continue will not go through, in the operator's own words. "" means it will. */
  function blockReason() {
    if (wiz.step === 1) return wizPlace() ? "" : "Choose where the brain should live to continue.";
    if (wiz.step === 2) {
      if (!wiz.mode) return "Pick who this brain is for to continue.";
      if (wiz.mode === "client" && !wizAgency()) return "Enter the agency's name to continue.";
      return "";
    }
    if (wiz.step === 3) {
      if (!wizName()) return "Enter a business name to continue.";
      if (nameCollision()) return "There is already a brain in that folder. Open it, or use a different name.";
      return "";
    }
    if (wiz.step === 4) {
      if (!wiz.plan) return "Still working out what would be created.";
      if (!wiz.plan.envelope) return "The preview did not come back. Go back and pick another place.";
      if (!wiz.plan.envelope.ok) return "This place cannot be used. Go back and pick another.";
      if (!changesOf(wiz.plan.envelope).length) return "There is nothing left to create here.";
      return "";
    }
    return "";
  }

  function blockedField() {
    if (wiz.step === 1) return $("in-path");
    if (wiz.step === 2) {
      return wiz.mode === "client" && !wizAgency() ? $("in-agency") : $("mode-in-house");
    }
    if (wiz.step === 3) return $("in-name");
    return null;
  }

  function updateFoot() {
    var next = $("btn-next");
    var back = $("btn-back");
    show(back, wiz.step > 1 && wiz.step !== 5);

    if (wiz.step === 5) {
      show(next, false);
      $("wizard-hint").textContent = "";
      return;
    }
    show(next, true);
    next.setAttribute("aria-busy", "false");

    var reason = blockReason();
    $("wizard-hint").textContent = reason || REASSURANCE[wiz.step] || "";
    setBlocked(next, !!reason, "wizard-hint");

    if (wiz.step === 4) {
      var count = wiz.plan ? changesOf(wiz.plan.envelope).length : 0;
      fill(next, ["Create " + plural(count, "item")]);
      add(next, icon("right"));
      return;
    }
    fill(next, ["Continue"]);
    add(next, icon("right"));
  }

  function onNext() {
    var next = $("btn-next");
    var reason = blockReason();
    if (reason) {
      // Blocked, not gone: say why, and put the cursor on the thing that is missing.
      announce(reason);
      var field = blockedField();
      if (field) {
        var host = field.closest ? field.closest("details") : null;
        if (host) host.open = true;
        field.focus();
      }
      return;
    }
    if (blocked(next)) return;
    if (wiz.step === 1) {
      busy(next, true, "Checking");
      probePath(true).then(function () {
        busy(next, false);
        updateFoot();
        if (wiz.probe && wiz.probe.result.envelope) goStep(2);
      });
      return;
    }
    goStep(wiz.step + 1);
  }

  /* --- step 4: the plan -------------------------------------------------- */

  function loadPlan() {
    var key = planKey();
    if (wiz.plan && wiz.planKey === key) {
      renderPlan();
      return;
    }
    wiz.plan = null;
    wiz.planKey = key;
    fill($("preview-body"), [
      el("div", { class: "note note--accent" }, [
        el("span", { class: "btn__spin", "aria-hidden": "true" }),
        el("div", { class: "note__body" }, [
          el("p", { text: "Working out exactly what would be created..." }),
        ]),
      ]),
    ]);
    announce("Working out the plan.");
    updateFoot();
    run("onboard", onboardArgs({ plan: true })).then(function (result) {
      if (planKey() !== key) return;
      wiz.plan = result;
      renderPlan();
      updateFoot();
    });
  }

  var PLACEHOLDER = /(^|\/)\.gitkeep$/;

  /* A .gitkeep is not a document: it is the marker that keeps an empty folder in place.
   * Counting the two together is what let ten of them shout over the six files a person
   * will actually open. */
  /* Machinery is everything the operator is not expected to open: dot folders and dot
   * files at the root of the brain, and the two assistant entry files. */
  var MACHINERY = /^(?:\.[^/]+(?:\/|$)|CLAUDE\.md$|AGENTS\.md$)/;

  function parsePlan(changes) {
    var docs = [];
    var placeholders = [];
    var skills = [];
    var machinery = [];
    var setup = [];
    changes.forEach(function (change) {
      var match = /^(create|replace|copy|link)\s+(.+)$/.exec(change);
      if (!match) {
        setup.push(change);
        return;
      }
      var target = match[2];
      if (/^\.(claude|agents)\/skills\//.test(target)) skills.push(target);
      else if (PLACEHOLDER.test(target)) placeholders.push(target);
      else if (MACHINERY.test(target)) machinery.push(target);
      else docs.push(target);
    });
    return {
      docs: docs,
      placeholders: placeholders,
      skills: skills,
      machinery: machinery,
      setup: setup,
      files: docs.concat(placeholders),
    };
  }

  function buildTree(paths) {
    var root = { name: "", dirs: {}, files: [] };
    paths.forEach(function (path) {
      var parts = path.split("/");
      var node = root;
      for (var i = 0; i < parts.length - 1; i += 1) {
        var name = parts[i];
        if (!node.dirs[name]) node.dirs[name] = { name: name, dirs: {}, files: [] };
        node = node.dirs[name];
      }
      node.files.push({ name: parts[parts.length - 1], path: path });
    });
    return root;
  }

  function countLeaves(node) {
    var total = node.files.length;
    Object.keys(node.dirs).forEach(function (name) {
      total += countLeaves(node.dirs[name]);
    });
    return total;
  }

  /* Documents first, then ordinary files, then the placeholders. */
  function fileRank(file) {
    if (PLACEHOLDER.test(file.path)) return 2;
    return /\.md$/.test(file.name) ? 0 : 1;
  }

  function renderTree(node, depth) {
    var dirNames = Object.keys(node.dirs).sort();
    var files = node.files.slice().sort(function (a, b) {
      if (fileRank(a) !== fileRank(b)) return fileRank(a) - fileRank(b);
      return a.name < b.name ? -1 : 1;
    });
    var list = el("ul", { role: "list" });

    dirNames.forEach(function (name) {
      var child = node.dirs[name];
      var collapsed = depth === 0 && (name === ".claude" || name === ".agents");
      var row = el("span", { class: "tree__row tree__row--dir" }, [
        icon("folder"),
        el("span", { class: "tree__name", text: name + "/" }),
        el("span", { class: "tree__count", text: plural(countLeaves(child), "item") }),
      ]);
      if (collapsed) {
        list.appendChild(
          el("li", {}, [el("details", {}, [el("summary", {}, [row]), renderTree(child, depth + 1)])])
        );
      } else {
        list.appendChild(el("li", {}, [row, renderTree(child, depth + 1)]));
      }
    });

    files.forEach(function (file) {
      var isSkillDir = /^\.(claude|agents)\/skills\//.test(file.path);
      var rank = fileRank(file);
      var weight = rank === 2 ? " tree__row--faint" : rank === 0 ? " tree__row--doc" : "";
      list.appendChild(
        el("li", {}, [
          el("span", { class: "tree__row" + weight }, [
            icon(isSkillDir ? "folder" : "file"),
            el("span", { class: "tree__name", text: file.name + (isSkillDir ? "/" : "") }),
          ]),
        ])
      );
    });
    return list;
  }

  /* The skills, the dot folders and the git steps, folded to one faint row that opens
   * into the full list. They keep the brain working; nobody is expected to open them. */
  function machineryRow(parts) {
    var lines = parts.skills.concat(parts.machinery, parts.setup);
    if (!lines.length) return null;
    return el("div", { class: "tree__machinery" }, [
      tech(
        [changesList(lines, "The machinery")],
        "and " + plural(lines.length, "piece", "pieces") + " of machinery that keep it working"
      ),
    ]);
  }

  function countPart(n, label) {
    if (!n) return null;
    return el("li", { class: "plan-sum__part" }, [
      el("strong", { class: "plan-sum__n", text: String(n) }),
      " " + label,
    ]);
  }

  /* The decision must be on screen with the evidence, always. This block is sticky at
   * the top of the step and the wizard footer is sticky at the bottom, so however long
   * the tree runs, what is about to happen and the button that does it are both in
   * view. */
  function planSummary(parts, changes, repo) {
    return el("div", { class: "plan-sum" }, [
      el("p", { class: "plan-sum__lead", title: repo }, [
        "About to create ",
        el("strong", { text: plural(changes.length, "thing") }),
        " in ",
        el("strong", { text: placeLabel(repo) }),
        ".",
      ]),
      el("ul", { class: "plan-sum__parts", role: "list" }, [
        countPart(parts.docs.length, "documents to fill in"),
        countPart(parts.placeholders.length, "empty folders, ready for what you add"),
        countPart(
          parts.skills.length + parts.machinery.length + parts.setup.length,
          "pieces of machinery, including the assistant skills and git"
        ),
      ]),
    ]);
  }

  function renderPlan() {
    var result = wiz.plan;
    var body = $("preview-body");
    if (!result || !result.envelope) {
      fill(
        body,
        note("err", "alert", [(result && result.transport) || "The preview could not be produced."])
      );
      announce("The preview could not be produced.");
      return;
    }
    var envelope = result.envelope;
    var errors = bySeverity(envelope, "error");
    var changes = changesOf(envelope);
    var parts = parsePlan(changes);
    var frag = el("div", {});

    if (errors.length) {
      add(
        frag,
        el("div", { class: "readout" }, [
          note(
            "err",
            "alert",
            [el("strong", { text: "This place cannot be used. " }), errors[0].message],
            [
              el("button", {
                class: "btn btn--secondary",
                type: "button",
                text: "Pick somewhere else",
                on: {
                  click: function () {
                    goStep(1);
                    $("where-tech").open = true;
                    var first = $("path-chips").querySelector(".chip");
                    if (first) first.focus();
                  },
                },
              }),
            ]
          ),
        ])
      );
      if (errors.length > 1) {
        add(frag, el("div", { class: "readout" }, [findingRows(errors.slice(1))]));
      }
      fill(body, frag);
      announce("This place cannot be used. " + errors[0].message);
      return;
    }

    if (!changes.length) {
      add(
        frag,
        el("div", { class: "readout" }, [
          emptyState(
            "Everything is already there",
            "This folder already has every file the plan would create. Go back to step 1 and open it instead."
          ),
        ])
      );
      fill(body, frag);
      announce("Everything the plan would create is already there.");
      return;
    }

    add(frag, planSummary(parts, changes, envelope.repo));

    // No nested scroller on the one screen whose job is "look this over": the tree grows
    // to its full height and the page does the scrolling, once.
    add(
      frag,
      el("div", { class: "tree-wrap" }, [
        el("div", { class: "tree-wrap__head" }, [
          el("span", { class: "tree-wrap__title", text: "Your new folder, in full" }),
          el("span", {
            class: "pill",
            text: plural(parts.files.length, "item"),
          }),
          el("p", {
            class: "tree-wrap__note",
            text:
              "The darker rows are documents you will open. The faint ones are markers "
              + "that keep an empty folder in place until you put something in it.",
          }),
        ]),
        el("div", { class: "tree" }, [
          renderTree(buildTree(parts.files), 0),
          machineryRow(parts),
        ]),
      ])
    );

    if (wiz.mode === "agency") {
      add(
        frag,
        el("div", { class: "readout" }, [
          note("ok", "check", [
            el("strong", { text: "Your client list is in there. " }),
            "Look for the ",
            el("strong", { text: "clients" }),
            " folder in the tree above. Every client you sign gets a row.",
          ]),
        ])
      );
    }

    var warnings = bySeverity(envelope, "warning");
    if (warnings.length) {
      add(frag, subhead("Worth knowing"));
      add(frag, findingRows(warnings));
    }

    add(
      frag,
      tech(
        [
          el("p", { class: "tech__line" }, [
            "It all lands in ",
            el("code", { text: envelope.repo, title: envelope.repo }),
            ".",
          ]),
          terminal(result.commandLine, "The exact command this runs"),
          rawPre(envelope),
        ],
        "Show the command line and the exact location"
      )
    );
    fill(body, frag);
    announce(
      "Plan ready: " + plural(changes.length, "item") + " would be created. Nothing written yet."
    );
  }

  /* --- step 5: apply and verify ------------------------------------------ */

  var APPLY_STEPS = [
    { id: "write", title: "Creating the files", sub: "Writing the folder and wiring the skills" },
    {
      id: "validate",
      title: "Checking the structure",
      sub: "Making sure every file landed where it should",
    },
    { id: "status", title: "Reading what is left", sub: "Working out what still needs your input" },
  ];

  function applyPlan() {
    if (wiz.applying) return;
    if (wiz.done) {
      renderApplied(wiz.done);
      return;
    }
    wiz.applying = true;
    $("apply-title").textContent = "Building your brain";
    $("apply-lede").textContent =
      "Writing the files, then checking the result. This usually takes a few seconds.";

    var states = { write: "pending", validate: "pending", status: "pending" };
    var subs = {};
    var target = wizPath();

    function paint() {
      fill(
        $("apply-body"),
        el(
          "div",
          { class: "runlist" },
          APPLY_STEPS.map(function (step) {
            var state = states[step.id];
            return el("div", { class: "runstep", "data-state": state }, [
              el(
                "span",
                { class: "runstep__icon" },
                state === "done" ? icon("check") : state === "failed" ? icon("x") : null
              ),
              el("div", { class: "runstep__text" }, [
                el("p", { class: "runstep__title", text: step.title }),
                el("p", { class: "runstep__sub", text: subs[step.id] || step.sub }),
              ]),
            ]);
          })
        )
      );
    }

    states.write = "running";
    paint();
    // paint() runs six times. Announce the transitions, never the re-rendered subtree.
    announce("Creating your brain.");

    run("onboard", onboardArgs({ yes: true })).then(function (created) {
      var envelope = created.envelope;
      if (!envelope || !envelope.ok) {
        states.write = "failed";
        subs.write = envelope ? "Stopped before finishing" : created.transport;
        paint();
        wiz.applying = false;
        renderApplyFailure(created);
        return;
      }
      states.write = "done";
      subs.write = plural(changesOf(envelope).length, "item") + " created";
      states.validate = "running";
      paint();
      announce("Files created. Checking the structure.");
      // The new brain is one of the operator's from this moment, whatever the checks say.
      rememberBrain(target);

      run("validate", { path: target }).then(function (validated) {
        var vEnv = validated.envelope;
        var vErrors = bySeverity(vEnv, "error");
        states.validate = vEnv && vEnv.ok ? "done" : "failed";
        subs.validate = !vEnv
          ? validated.transport
          : vEnv.ok
            ? "No structural problems"
            : plural(vErrors.length, "problem") + " found";
        states.status = "running";
        paint();

        run("status", { path: target }).then(function (statused) {
          var sEnv = statused.envelope;
          states.status = sEnv ? "done" : "failed";
          if (sEnv) {
            var missing = (sEnv.context && sEnv.context.missing) || [];
            subs.status = missing.length
              ? plural(missing.length, "question") + " still to answer"
              : "Everything it needs is filled in";
          } else {
            subs.status = statused.transport;
          }
          paint();
          wiz.applying = false;
          wiz.done = { created: created, validated: validated, statused: statused, target: target };
          window.setTimeout(function () {
            renderApplied(wiz.done);
          }, 320);
        });
      });
    });
  }

  function renderApplyFailure(created) {
    $("apply-title").textContent = "That did not go through";
    $("apply-lede").textContent = "Nothing is half-built. Here is exactly what stopped it.";
    var frag = el("div", { class: "readout" }, [
      el("div", { class: "card" }, [resultCard(created, { title: "What stopped it" })]),
    ]);
    add(
      frag,
      el("div", { class: "btn-row" }, [
        el("button", {
          class: "btn btn--primary",
          type: "button",
          text: "Try again",
          on: {
            click: function () {
              wiz.done = null;
              applyPlan();
            },
          },
        }),
        el("button", {
          class: "btn btn--secondary",
          type: "button",
          text: "Choose somewhere else",
          on: {
            click: function () {
              wiz.done = null;
              goStep(1);
            },
          },
        }),
      ])
    );
    add($("apply-body"), frag);
    land($("apply-title"), resultSummary(created, "Setting up the brain"));
  }

  function renderApplied(done) {
    var status = done.statused.envelope;
    var created = done.created.envelope;
    var name = (status && status.business && status.business.name) || wizName();
    $("apply-title").textContent = name + " is ready";
    $("apply-lede").textContent =
      "The folder exists, the files are written, and Claude Code and Codex can both see the skills.";

    var missing = (status && status.context && status.context.missing) || [];
    var frag = el("div", {});

    add(
      frag,
      el("div", { class: "readout" }, [
        note("ok", "check", [
          el("strong", { text: plural(changesOf(created).length, "item") + " created " }),
          "in a folder called ",
          el("strong", { text: folderName(created.repo) }),
          ", " + placePhrase(created.repo) + ".",
        ]),
      ])
    );

    if (missing.length) {
      add(frag, subhead("It still needs to hear from you"));
      add(
        frag,
        el(
          "div",
          { class: "clist" },
          missing.map(function (key) {
            var info = contextInfo(key);
            return el("div", { class: "citem", "data-done": "false" }, [
              el("span", { class: "citem__box" }),
              el("div", { class: "citem__text" }, [
                el("p", { class: "citem__title" }, [info.title]),
                el("p", { class: "citem__body", text: info.body }),
              ]),
            ]);
          })
        )
      );
      add(
        frag,
        el("div", { class: "readout" }, [
          note("accent", "chat", [
            el("strong", { text: "You can answer these right here. " }),
            "The app asks one question at a time, in plain English, and writes each answer to the " +
              "right file for you. You will not open a terminal and you will not edit anything by " +
              "hand. If Claude Code or Codex is on this computer, one button can also interview you " +
              "and draft an answer for you to check. It only ever runs when you press it.",
          ]),
        ])
      );
    } else {
      add(
        frag,
        el("div", { class: "readout" }, [
          emptyState("Nothing left to fill in", "This brain is ready to work with."),
        ])
      );
    }

    var openDash = el(
      "button",
      {
        class: missing.length ? "btn btn--secondary btn--lg" : "btn btn--primary btn--lg",
        type: "button",
        on: {
          click: function () {
            switchBrain(done.target);
          },
        },
      },
      ["Open the dashboard", icon("right")]
    );

    var actions = [];
    if (missing.length) {
      actions.push(
        el(
          "button",
          {
            class: "btn btn--primary btn--lg",
            type: "button",
            on: {
              click: function () {
                switchBrain(done.target).then(function () {
                  openInterview();
                });
              },
            },
          },
          ["Answer the first question", icon("right")]
        )
      );
    }
    actions.push(openDash);
    add(frag, el("div", { class: "btn-row" }, actions));

    fill($("apply-body"), frag);
    land(
      $("apply-title"),
      name +
        " is ready. " +
        (missing.length
          ? plural(missing.length, "question") + " left to answer."
          : "Nothing left to fill in.")
    );
  }

  /* ============================================================== interview */

  /* The app's answer to "open this folder in Claude Code and run a skill". One question
   * per screen, in the operator's language; every answer goes out through
   * `mos context set` with the same preview-then-apply gate as any other mutating
   * command, so the UI still never touches a file itself. */

  var iv = { fields: [], index: 0, saving: false, ctx: null };

  /* ------------------------------------------------ the assisted interview */

  /* The only code in this app that spends the operator's tokens, and it spends them on
   * an explicit press and on nothing else. `assistTurn` is the single caller of
   * `mos assist ask`, and every one of its call sites is inside a click handler. There
   * is no timer here, nothing is warmed up, nothing is prefetched, and nothing runs at
   * load: opening this screen does not ask a model anything.
   *
   * `mos assist status` is a different thing and runs without being asked, once. It runs
   * the runtime's `--version` and reads the answer; no model is involved and no tokens
   * are spent. The control cannot be offered honestly without it, because a runtime that
   * is not there must leave nothing at all on the screen.
   *
   * Everything the assistant says is untrusted data. Its questions and its draft reach
   * the page through createTextNode and a textarea's value, and nowhere else: never as
   * markup, never as a command, never as a path, never executed. The sentence shown when
   * a turn fails is authored here and keyed off the envelope's finding code, so a failure
   * cannot put the model's words on screen either. */

  var MAX_ASSIST_QUESTIONS = 4;

  /* Authored copy, one plain sentence per finding code the engine can return. */
  var ASSIST_TROUBLE = {
    "no-runtime": "Your assistant is not available on this computer.",
    "assist-timeout": "Your assistant did not answer in time.",
    "assist-reply-too-large": "Your assistant sent back more than this app will read.",
    "assist-unusable-reply": "Your assistant's reply could not be used.",
    "assist-not-runnable": "Your assistant could not be started.",
    "assist-failed": "Your assistant stopped before it answered.",
    "bad-transcript": "This conversation could not be sent back to your assistant.",
    "unknown-field": "This question cannot be handed to your assistant.",
    "not-a-mos-repo": "This folder is not a brain any more.",
  };

  var UNTOUCHED = " Nothing you have written has been touched.";

  var assist = {
    probing: null, // the one probe promise, so it can never run twice
    ready: false, // a runtime on this machine actually answered
    runtime: "", // its name, as the envelope reported it
    field: "", // the question this conversation belongs to
    turns: [], // [{question, answer}] — the whole conversation lives here
    question: "", // model text, waiting for an answer
    draft: "", // model text, waiting for a decision about existing words
    inserted: "", // the exact draft last put in the box, so it can be replaced freely
    busy: false,
    trouble: "", // one authored sentence, never the model's words
    last: null, // the failed result, for the technical disclosure
  };

  function assistRuntimeName() {
    return RUNTIME_LABEL[assist.runtime] || assist.runtime || "Your assistant";
  }

  /* Ask the CLI which runtimes can genuinely answer. Once per session: the answer cannot
   * change while the app is open unless the operator installs something, and re-asking on
   * a timer is precisely the behaviour this feature is not allowed to have. */
  function probeAssist() {
    if (assist.probing) return assist.probing;
    assist.probing = run("assist status", {}).then(function (result) {
      var envelope = result.envelope;
      var runtimes = (envelope && Array.isArray(envelope.runtimes) && envelope.runtimes) || [];
      assist.ready = !!(envelope && envelope.ok && envelope.ready && runtimes.length);
      assist.runtime = assist.ready ? String(runtimes[0].name || "") : "";
      return assist.ready;
    });
    return assist.probing;
  }

  function resetAssist(fieldName) {
    assist.field = fieldName;
    assist.turns = [];
    assist.question = "";
    assist.draft = "";
    assist.inserted = "";
    assist.busy = false;
    assist.trouble = "";
    assist.last = null;
  }

  function assistTrouble(result) {
    if (!result.envelope) return "The local app did not answer.";
    var code = (findingsOf(result.envelope)[0] || {}).code || "";
    return ASSIST_TROUBLE[code] || "Your assistant could not finish that.";
  }

  /* One turn of the interview. Called from a click handler; never from anywhere else. */
  function assistTurn(ctx) {
    if (assist.busy) return;
    assist.busy = true;
    assist.trouble = "";
    assist.question = "";
    assist.draft = "";
    assist.last = null;
    renderAssist(ctx);
    // The button that was just pressed no longer exists. Land on the waiting line rather
    // than letting focus fall to <body>, which is the same defect aria-disabled exists to
    // avoid everywhere else in this app.
    land(
      ctx.host.querySelector(".assist__meta"),
      assist.turns.length >= MAX_ASSIST_QUESTIONS
        ? "Writing your draft. This can take a moment."
        : "Asking " + assistRuntimeName() + ". This can take a moment."
    );
    run("assist ask", {
      path: App.path,
      field: ctx.field.name,
      "transcript-json": JSON.stringify(assist.turns),
    }).then(function (result) {
      assist.busy = false;
      var envelope = result.envelope;
      if (!envelope || !envelope.ok) {
        assist.last = result;
        assist.trouble = assistTrouble(result);
        renderAssist(ctx);
        land(ctx.host.querySelector(".note__body"), assist.trouble + UNTOUCHED);
        return;
      }
      if (envelope.done) {
        finishAssist(ctx, String(envelope.draft || ""));
        return;
      }
      var question = String(envelope.question || "");
      if (!question) {
        assist.trouble = "Your assistant sent nothing back.";
        renderAssist(ctx);
        land(ctx.host.querySelector(".note__body"), assist.trouble + UNTOUCHED);
        return;
      }
      assist.question = question;
      renderAssist(ctx);
      var box = $("iv-assist-answer");
      if (box) box.focus();
      announce(
        "Question " +
          (assist.turns.length + 1) +
          " of up to " +
          MAX_ASSIST_QUESTIONS +
          ", from " +
          assistRuntimeName() +
          ". " +
          question
      );
    });
  }

  /* A finished draft. It never lands on top of the operator's own words unasked. */
  function finishAssist(ctx, draft) {
    if (!draft) {
      assist.trouble = "Your assistant sent nothing back.";
      renderAssist(ctx);
      land(ctx.host.querySelector(".note__body"), assist.trouble + UNTOUCHED);
      return;
    }
    var typed = ctx.area.value;
    if (!typed.trim() || typed === assist.inserted) {
      takeDraft(ctx, draft);
      return;
    }
    assist.draft = draft;
    renderAssist(ctx);
    land(
      ctx.host.querySelector(".assist__meta"),
      "There is a draft ready, and you have already written something here. Choose which one to keep."
    );
  }

  function takeDraft(ctx, draft) {
    resetAssist(ctx.field.name);
    assist.inserted = draft;
    ctx.area.value = draft;
    ctx.sync();
    renderAssist(ctx);
    ctx.area.focus();
    announce(
      "The draft is in the box below. Read it, change anything that is not true, then review it."
    );
  }

  function abandonAssist(ctx, said) {
    resetAssist(ctx.field.name);
    renderAssist(ctx);
    ctx.area.focus();
    announce(said);
  }

  /* Graceful absence lives here: with no runtime, this host stays empty and the screen is
   * the plain textarea it was before. Not a disabled button, not an explanation. */
  function renderAssist(ctx) {
    if (assist.field !== ctx.field.name) resetAssist(ctx.field.name);
    if (!assist.ready) {
      fill(ctx.host, []);
      return;
    }
    fill(ctx.host, [assistPanel(ctx), assistDivider()]);
  }

  function assistDivider() {
    return el("p", { class: "assist-or" }, [
      el("span", { class: "assist-or__word", text: "or write it yourself" }),
    ]);
  }

  function assistPanel(ctx) {
    if (assist.busy) return assistWaiting();
    if (assist.trouble) return assistTroublePanel(ctx);
    if (assist.draft) return assistDraftPanel(ctx);
    if (assist.question) return assistQuestionPanel(ctx);
    return assistOffer(ctx);
  }

  function assistShell(kids) {
    return el("section", { class: "assist", "aria-label": "Assisted interview" }, kids);
  }

  function assistOffer(ctx) {
    var button = el("button", {
      class: "btn btn--ghost assist__go",
      type: "button",
      "aria-describedby": "iv-assist-cost",
    });
    add(button, [icon("chat"), "Let my assistant interview me"]);
    button.addEventListener("click", function () {
      assistTurn(ctx);
    });
    return assistShell([
      button,
      el("p", {
        class: "assist__cost",
        id: "iv-assist-cost",
        text:
          assistRuntimeName() +
          " is on this computer. It asks up to " +
          MAX_ASSIST_QUESTIONS +
          " short questions, then drafts this answer from what you tell it. It runs on your own " +
          "subscription and spends your own tokens, only when you press this button.",
      }),
    ]);
  }

  function assistWaiting() {
    return assistShell([
      el("p", { class: "assist__meta" }, [
        el("span", { class: "btn__spin", "aria-hidden": "true" }),
        assist.turns.length >= MAX_ASSIST_QUESTIONS
          ? "Writing your draft..."
          : "Asking " + assistRuntimeName() + "...",
      ]),
    ]);
  }

  function assistQuestionPanel(ctx) {
    var box = el("textarea", {
      class: "textarea assist__answer",
      id: "iv-assist-answer",
      rows: "3",
      "aria-describedby": "iv-assist-answer-help",
      placeholder: "A sentence or two is plenty.",
    });
    var send = el("button", {
      class: "btn btn--secondary",
      type: "button",
      text: "Send this answer",
    });
    setBlocked(send, true, "iv-assist-answer-help");
    box.addEventListener("input", function () {
      setBlocked(send, !box.value.trim(), "iv-assist-answer-help");
    });
    send.addEventListener("click", function () {
      if (blocked(send)) {
        announce("Answer the question first, then send it.");
        box.focus();
        return;
      }
      assist.turns.push({ question: assist.question, answer: box.value.trim() });
      assist.question = "";
      assistTurn(ctx);
    });
    return assistShell([
      el("p", {
        class: "assist__meta",
        text:
          "Question " +
          (assist.turns.length + 1) +
          " of up to " +
          MAX_ASSIST_QUESTIONS +
          ", from " +
          assistRuntimeName(),
      }),
      // The assistant's words. A text node, so a tag or a link in them is just characters.
      el("p", { class: "assist__q" }, [
        el("span", { class: "sr-only", text: "Your assistant asks: " }),
        document.createTextNode(assist.question),
      ]),
      // Not "Your answer": that is the box below, and the two must not read alike.
      el("label", { class: "field__label", for: "iv-assist-answer", text: "Your reply" }),
      el("p", {
        class: "field__help",
        id: "iv-assist-answer-help",
        text: "Answer in your own words. This goes back to your assistant, not into a file.",
      }),
      box,
      el("div", { class: "btn-row" }, [
        send,
        el("button", {
          class: "btn btn--ghost",
          type: "button",
          text: "Stop the interview",
          on: {
            click: function () {
              abandonAssist(ctx, "Stopped." + UNTOUCHED);
            },
          },
        }),
      ]),
    ]);
  }

  function assistDraftPanel(ctx) {
    var use = el("button", {
      class: "btn btn--secondary",
      type: "button",
      text: "Use the draft instead",
    });
    use.addEventListener("click", function () {
      takeDraft(ctx, assist.draft);
    });
    return assistShell([
      note("warn", "alert", [
        el("strong", { text: "You have already written an answer here. " }),
        "Using the draft replaces it. Nothing is saved either way until you review it.",
      ]),
      el("p", { class: "assist__meta", text: "What " + assistRuntimeName() + " drafted" }),
      // Model text again, and again only ever a text node.
      scrollRegion("div", "assist__draft", "The drafted answer", [
        el("p", {}, [document.createTextNode(assist.draft)]),
      ]),
      el("div", { class: "btn-row" }, [
        use,
        el("button", {
          class: "btn btn--ghost",
          type: "button",
          text: "Keep what I wrote",
          on: {
            click: function () {
              abandonAssist(ctx, "Kept your own words. The draft has been discarded.");
            },
          },
        }),
      ]),
    ]);
  }

  function assistTroublePanel(ctx) {
    var again = el("button", { class: "btn btn--secondary", type: "button", text: "Try again" });
    again.addEventListener("click", function () {
      assistTurn(ctx);
    });
    var result = assist.last;
    return assistShell([
      note("warn", "alert", [el("strong", { text: assist.trouble }), UNTOUCHED]),
      el("div", { class: "btn-row" }, [
        again,
        el("button", {
          class: "btn btn--ghost",
          type: "button",
          text: "Write it myself",
          on: {
            click: function () {
              abandonAssist(ctx, "Back to writing it yourself." + UNTOUCHED);
            },
          },
        }),
      ]),
      result
        ? tech(
            [
              terminal(result.commandLine, "The exact command this ran"),
              result.envelope ? rawPre(result.envelope) : null,
            ],
            "Show what came back"
          )
        : null,
    ]);
  }

  function openQuestions() {
    return iv.fields.filter(function (field) {
      return field.required && !field.complete;
    });
  }

  function openInterview(startField) {
    setView("interview");
    $("iv-eyebrow").textContent = "The interview";
    $("iv-title").textContent = "Reading the questions...";
    $("iv-hint").textContent = "";
    fill($("iv-rail"), []);
    fill($("iv-body"), [
      el("div", { class: "card" }, [
        note("accent", "info", [
          el("span", { class: "btn__spin", "aria-hidden": "true" }),
          " Asking this brain which questions are still open...",
        ]),
      ]),
    ]);
    announce("Opening the questions.");
    run("context show", { path: App.path }).then(function (result) {
      var envelope = result.envelope;
      if (!envelope || !envelope.ok) {
        $("iv-title").textContent = "The questions could not be read";
        $("iv-hint").textContent = "";
        fill($("iv-body"), [
          el("div", { class: "card" }, [resultCard(result, { title: "What came back" })]),
        ]);
        land($("iv-title"), resultSummary(result, "Reading the questions"));
        return;
      }
      iv.fields = (envelope.fields || []).slice();
      iv.index = startIndex(startField);
      renderInterview();
      // Find out whether an assistant could answer at all. This runs the runtime's
      // --version, not a model: it costs nothing and asks nobody anything. The screen
      // above is already complete without it, so the answer can only ever add a control.
      probeAssist().then(function () {
        if (iv.ctx && iv.ctx.host.parentNode) renderAssist(iv.ctx);
      });
    });
  }

  function startIndex(startField) {
    var wanted = -1;
    iv.fields.forEach(function (field, index) {
      if (field.name === startField) wanted = index;
    });
    if (wanted !== -1) return wanted;
    for (var i = 0; i < iv.fields.length; i += 1) {
      if (iv.fields[i].required && !iv.fields[i].complete) return i;
    }
    for (var j = 0; j < iv.fields.length; j += 1) {
      if (!iv.fields[j].complete) return j;
    }
    return iv.fields.length;
  }

  function leaveInterview() {
    setView("dashboard");
    land($("dash-title"), "Back on the dashboard.");
  }

  function renderRail() {
    fill(
      $("iv-rail"),
      iv.fields.map(function (field, index) {
        var current = index === iv.index;
        var state = field.complete ? "done" : current ? "current" : "todo";
        var word = field.complete
          ? "Answered: "
          : current
            ? "Current question: "
            : "Not answered yet: ";
        return el(
          "li",
          {
            class: "iv-rail__item",
            "data-state": state,
            "aria-current": current ? "step" : null,
          },
          [
            el("span", { class: "iv-rail__dot", "aria-hidden": "true" }, [
              field.complete ? icon("check") : null,
            ]),
            el("span", { class: "sr-only", text: word }),
            el("span", { class: "iv-rail__label", text: contextInfo(field.name).title }),
          ]
        );
      })
    );
  }

  function renderInterview() {
    if (iv.index >= iv.fields.length) {
      renderInterviewDone();
      return;
    }
    var field = iv.fields[iv.index];
    var info = contextInfo(field.name);
    var open = openQuestions().length;

    $("iv-eyebrow").textContent =
      info.title.toLowerCase() + " \u00b7 question " + (iv.index + 1) + " of " + iv.fields.length;
    $("iv-title").textContent = field.question;
    $("iv-hint").textContent = field.hint || info.body;
    renderRail();

    var area = el("textarea", {
      class: "textarea textarea--answer",
      id: "iv-answer",
      rows: "7",
      "aria-describedby": "iv-answer-help",
      placeholder: "Write it the way you would say it to a customer.",
    });
    area.value = field.body || "";

    var slugBox = null;
    if (field.name === "offer" && (field.files || []).length > 1) {
      slugBox = el("input", {
        class: "input input--mono",
        id: "iv-slug",
        type: "text",
        autocomplete: "off",
        placeholder: "core-offer",
        "aria-describedby": "iv-slug-help",
      });
    }

    var blockNote = el("p", { class: "field__help", id: "iv-block", text: "" });
    var previewHost = el("div", { id: "iv-preview" });
    var assistHost = el("div", { id: "iv-assist" });
    var actions = el("div", { class: "btn-row iv-actions" });

    /* One function decides whether there is an answer to review, so the typed path and
     * the assisted path can never leave the button and the note disagreeing. Setting a
     * textarea's value fires no input event, which is exactly how a drafted answer used
     * to arrive under a button that still said there was nothing to review. */
    function syncAnswer() {
      var empty = !area.value.trim();
      setBlocked(review, empty, "iv-block");
      blockNote.textContent = empty ? "Write an answer to review it." : "";
    }

    var review = el("button", {
      class: "btn btn--primary",
      type: "button",
      text: "Review this answer",
    });
    review.addEventListener("click", function () {
      if (blocked(review)) {
        announce("Write an answer first, then review it.");
        area.focus();
        return;
      }
      previewAnswer(field, area.value, slugBox ? slugBox.value.trim() : "", review, previewHost);
    });

    var skip = el("button", {
      class: "btn btn--ghost",
      type: "button",
      text: field.complete ? "Leave it as it is" : "Skip for now",
      on: {
        click: function () {
          step(1);
        },
      },
    });
    var back = el("button", { class: "btn btn--ghost", type: "button" });
    add(back, [icon("left"), "Previous question"]);
    back.addEventListener("click", function () {
      step(-1);
    });

    add(actions, [iv.index > 0 ? back : null, review, skip]);

    area.addEventListener("input", syncAnswer);
    syncAnswer();

    fill($("iv-body"), [
      el("section", { class: "card iv-card" }, [
        el("div", { class: "card__head" }, [
          el("div", {}, [
            el("h2", { class: "card__title", text: "Your answer" }),
            el("p", {
              class: "card__sub",
              text: field.required
                ? "This one is required before the brain counts as ready."
                : "This one is optional. Skipping it holds nothing up.",
            }),
          ]),
          el("span", { class: "card__end" }, [
            el("span", {
              class: field.complete ? "pill pill--ok" : field.required ? "pill pill--warn" : "pill",
              text: field.complete ? "Answered" : field.required ? "Required" : "Optional",
            }),
          ]),
        ]),
        assistHost,
        field.body
          ? el("div", { class: "iv-current" }, [
              el("p", { class: "iv-current__label eyebrow", text: "on file now" }),
              prose(field.body),
            ])
          : null,
        el("p", {
          class: "field__help",
          id: "iv-answer-help",
          text: "A few specific sentences is plenty. Nothing is saved until you have seen the preview.",
        }),
        area,
        slugBox
          ? el("div", { class: "field" }, [
              el("label", { class: "field__label", for: "iv-slug", text: "Which offer is this?" }),
              el("p", {
                class: "field__help",
                id: "iv-slug-help",
                text: "This brain has more than one offer, so name the one you are describing.",
              }),
              slugBox,
            ])
          : null,
        actions,
        blockNote,
        previewHost,
      ]),
    ]);

    iv.ctx = { field: field, area: area, host: assistHost, sync: syncAnswer };
    renderAssist(iv.ctx);

    land(
      $("iv-title"),
      "Question " +
        (iv.index + 1) +
        " of " +
        iv.fields.length +
        ". " +
        field.question +
        " " +
        plural(open, "required question") +
        " still open."
    );
  }

  function step(delta) {
    iv.index = Math.max(0, Math.min(iv.fields.length, iv.index + delta));
    renderInterview();
  }

  function previewAnswer(field, text, slug, button, host) {
    var args = { path: App.path, field: field.name, text: text, plan: true };
    if (slug) args.slug = slug;
    busy(button, true, "Checking it over");
    run("context set", args).then(function (result) {
      busy(button, false);
      fill(button, ["Review this answer"]);
      var envelope = result.envelope;
      if (!envelope || !envelope.ok) {
        fill(host, [
          el("div", { class: "readout" }, [
            el("div", { class: "card" }, [
              resultCard(result, { title: "That could not be prepared" }),
            ]),
          ]),
        ]);
        land(host.querySelector(".result__title"), resultSummary(result, "Preparing the answer"));
        return;
      }
      var short = bySeverity(envelope, "warning").filter(function (item) {
        return item.code === "answer-too-short";
      });
      // One accent object per surface: while the preview is up, saving is the primary
      // action and the review button steps back to secondary. "Keep editing" restores it.
      setClass(button, "btn--primary", false);
      setClass(button, "btn--secondary", true);
      var save = el("button", {
        class: "btn btn--primary",
        type: "button",
        text: "Save this answer",
      });
      save.addEventListener("click", function () {
        if (blocked(save)) return;
        applyAnswer(field, text, slug, save, host);
      });

      fill(host, [
        el("div", { class: "readout" }, [
          el("div", { class: "card card--preview" }, [
            el("h3", { class: "result__title", text: "Nothing has been written yet" }),
            note("accent", "info", [
              envelope.created
                ? "This creates the file behind "
                : "This replaces everything written under ",
              el("strong", { text: contextInfo(field.name).title.toLowerCase() }),
              envelope.created
                ? " and puts the words above in it."
                : // Not "everything else stays": render_answer keeps the frontmatter and
                  // the heading and replaces the whole body, other sections included. The
                  // diff directly below shows it, so the sentence above it must agree.
                  " with the words above, any other sections in it included. Its heading and the details at the top of the file stay as they are.",
            ]),
            short.length
              ? note("warn", "alert", [
                  el("strong", { text: "That is quite short. " }),
                  "You can save it, but the brain will still count this question as unanswered until there is more to go on.",
                ])
              : null,
            tech(
              [
                el("p", { class: "tech__line" }, [
                  "It writes to ",
                  el("code", { text: envelope.path, title: envelope.path }),
                  ".",
                ]),
                envelope.diff
                  ? scrollRegion("pre", "raw__pre", "The exact change", [
                      el("code", { text: envelope.diff }),
                    ])
                  : null,
                terminal(result.commandLine, "The exact command this ran"),
              ],
              "Show the exact change and the command line"
            ),
            el("div", { class: "btn-row applybar applybar--top" }, [
              save,
              el("button", {
                class: "btn btn--ghost",
                type: "button",
                text: "Keep editing",
                on: {
                  click: function () {
                    fill(host, []);
                    setClass(button, "btn--secondary", false);
                    setClass(button, "btn--primary", true);
                    var area = $("iv-answer");
                    if (area) area.focus();
                  },
                },
              }),
            ]),
          ]),
        ]),
      ]);
      land(
        host.querySelector(".result__title"),
        "Ready to save. Nothing has been written yet." +
          (short.length ? " Warning: that answer is quite short." : "")
      );
    });
  }

  function applyAnswer(field, text, slug, button, host) {
    if (iv.saving) return;
    iv.saving = true;
    var args = { path: App.path, field: field.name, text: text, yes: true };
    if (slug) args.slug = slug;
    busy(button, true, "Saving");
    run("context set", args).then(function (result) {
      iv.saving = false;
      busy(button, false);
      fill(button, ["Save this answer"]);
      var envelope = result.envelope;
      if (!envelope || !envelope.ok) {
        fill(host, [
          el("div", { class: "readout" }, [
            el("div", { class: "card" }, [resultCard(result, { title: "That did not save" })]),
          ]),
        ]);
        land(host.querySelector(".result__title"), resultSummary(result, "Saving the answer"));
        return;
      }
      // The dashboard has to move on its own: re-read status and doctor, then re-read the
      // questions so this screen and that one can never disagree about what is done.
      Promise.all([
        run("status", { path: App.path }),
        run("doctor", { path: App.path }),
        run("context show", { path: App.path }),
      ]).then(function (results) {
        if (results[0].envelope) App.status = results[0].envelope;
        if (results[1].envelope) App.doctor = results[1].envelope;
        if (results[2].envelope && results[2].envelope.fields) {
          iv.fields = results[2].envelope.fields.slice();
        }
        if (App.status) renderDashboard();
        var open = openQuestions().length;
        announce(
          "Saved. " +
            (open
              ? plural(open, "required question") + " still open."
              : "Every required question is answered.")
        );
        step(1);
      });
    });
  }

  function renderInterviewDone() {
    var open = openQuestions();
    var optional = iv.fields.filter(function (field) {
      return !field.required && !field.complete;
    });
    $("iv-eyebrow").textContent = "The interview";
    $("iv-title").textContent = open.length
      ? "That is the end of the list"
      : "It knows your business now";
    $("iv-hint").textContent = open.length
      ? "Some required questions were skipped. The brain works better once they have answers."
      : "Every required question has an answer on file. The assistants can write as you from here.";
    renderRail();

    var card = el("section", { class: "card" }, [
      open.length
        ? note("warn", "alert", [
            plural(open.length, "required question") + " still has no answer: ",
            el("strong", {
              text: open
                .map(function (field) {
                  return contextInfo(field.name).title;
                })
                .join(", "),
            }),
            ".",
          ])
        : note("ok", "check", [
            el("strong", { text: "All done. " }),
            "Every required question has an answer on file.",
          ]),
      optional.length
        ? el("p", {
            class: "card__sub",
            text:
              plural(optional.length, "optional question") +
              " still open. Worth doing, but nothing is waiting on them.",
          })
        : null,
    ]);

    var actions = el("div", { class: "btn-row applybar applybar--top" });
    if (open.length) {
      actions.appendChild(
        el("button", {
          class: "btn btn--primary",
          type: "button",
          text: "Go back to the first one",
          on: {
            click: function () {
              iv.index = startIndex();
              renderInterview();
            },
          },
        })
      );
    }
    actions.appendChild(
      el(
        "button",
        {
          class: open.length ? "btn btn--secondary" : "btn btn--primary",
          type: "button",
          on: { click: leaveInterview },
        },
        ["Open the dashboard", icon("right")]
      )
    );
    add(card, actions);
    fill($("iv-body"), [card]);
    land($("iv-title"), $("iv-title").textContent + ". " + $("iv-hint").textContent);
  }

  /* ============================================================== dashboard */

  function repoHealth(status) {
    var state = status.repo_state;
    if (state === "ready") return { kind: "ok", label: "Healthy" };
    if (state === "needs-context") return { kind: "warn", label: "Waiting on you" };
    if (state === "needs-runtime-sync") return { kind: "warn", label: "Skills out of sync" };
    if (state === "invalid") return { kind: "err", label: "Structure problems" };
    return { kind: "err", label: "No brain here" };
  }

  /* The order an operator meets the questions in, and nothing more. Which of them are
   * required is the server's answer, read from status.context.required — a question this
   * list has never heard of still appears, and still counts. */
  var CONTEXT_ORDER = ["brand", "voice", "audience", "offer", "strategy", "proof"];

  /* The three states one answer can be in: written at the path the schema names, found
   * somewhere else in the brain, or not answered at all.
   *
   * A current server sends `source` on every field. A response cached from an older one
   * carries only `complete`, so a field with no source is read the way that server meant
   * it — answered means answered at the canonical path — rather than throwing. */
  function fieldSource(field) {
    if (!field) return "missing";
    if (field.source === "canonical" || field.source === "discovered") return field.source;
    if (field.source === "missing") return "missing";
    return field.complete ? "canonical" : "missing";
  }

  function fieldAnswered(field) {
    return fieldSource(field) !== "missing";
  }

  /* One denominator everywhere. "Ready" is judged on the required questions, so that is
   * the number both the health tile and the checklist show; the optional ones are counted
   * separately and always carry the word optional. An answer found away from its canonical
   * path is answered — it is counted as done, and counted again as found so the badge can
   * say so out loud instead of quietly inflating the score. */
  function contextCounts(status) {
    var context = status.context || {};
    var fields = context.fields || {};
    var required = context.required || [];
    var known = CONTEXT_ORDER.filter(function (key) {
      return fields[key];
    });
    var order = known.concat(
      Object.keys(fields).filter(function (key) {
        return CONTEXT_ORDER.indexOf(key) === -1;
      })
    );
    var requiredKeys = order.filter(function (key) {
      return required.indexOf(key) !== -1;
    });
    var optionalKeys = order.filter(function (key) {
      return required.indexOf(key) === -1;
    });
    function done(keys) {
      return keys.filter(function (key) {
        return fieldAnswered(fields[key]);
      }).length;
    }
    function found(keys) {
      return keys.filter(function (key) {
        return fieldSource(fields[key]) === "discovered";
      }).length;
    }
    return {
      order: order,
      fields: fields,
      required: requiredKeys.length,
      requiredDone: done(requiredKeys),
      requiredFound: found(requiredKeys),
      optional: optionalKeys.length,
      optionalDone: done(optionalKeys),
      optionalFound: found(optionalKeys),
    };
  }

  function renderDashboard() {
    var status = App.status;
    if (!status) return;
    var counts = contextCounts(status);

    $("dash-eyebrow").textContent = (MODE_LABEL[status.mode] || "Business brain").toLowerCase();
    $("dash-title").textContent = (status.business && status.business.name) || "This brain";

    fill($("dash-meta"), [
      status.mode ? el("span", { class: "meta__item", text: MODE_SHORT[status.mode] || status.mode }) : null,
      el("span", {
        class: "meta__item",
        text: counts.requiredDone + " of " + counts.required + " required",
      }),
      el("span", {
        class: "meta__item",
        text: plural((status.installed_skills || []).length, "shared skill"),
      }),
      el("span", { class: "meta__item", text: "Folder: " + folderName(status.repo) }),
    ]);

    cards.open = null;
    var answers = answerCards(status);
    var checks = checkCards(status, App.doctor);
    fill($("dash-body"), [
      el("div", { class: "ledger" }, [nextRow(status)]),
      el("div", { class: "cards" }, answers.nodes.concat(checks.nodes)),
      el("div", { class: "ledger ledger--foot" }, [openRow(status)]),
    ]);
    fillAnswers(answers.entries, App.path);
    fillNavigation(checks.navigation, App.path);
  }

  /* ================================================================= cards */

  /* The dashboard: the next action, then one grid of ten peer cards, six answers and
   * four checks, each with a name, a state word and one line, opening in place to its
   * details. The answers are not in the state envelope, so they are read once per brain
   * through `mos context show`; the navigation check is read once through `mos index
   * status`. Both reach the page as text. */

  var ledger = { answers: {}, pending: {}, navigation: {}, navPending: {} };
  var cards = { open: null };

  function ledgerRow(label, body, end, extra) {
    return el("div", { class: "ledger__row" + (extra ? " " + extra : "") }, [
      el("p", { class: "ledger__label", text: label }),
      body,
      end ? el("div", { class: "ledger__end" }, end) : null,
    ]);
  }

  /* The operator's words, read as prose: frontmatter dropped, the document title
   * dropped, emphasis markers stripped, list items kept as their own lines. A heading
   * below the title is kept as a labelled paragraph so the first line of an answer is
   * always the operator's own sentence. Text only; nothing here is ever markup. */
  function proseParagraphs(text) {
    var raw = String(text || "").replace(/\r\n?/g, "\n");
    if (raw.indexOf("---") === 0) {
      var close = raw.indexOf("\n---", 3);
      if (close !== -1) raw = raw.slice(close + 4);
    }
    var paragraphs = [];
    raw.split(/\n[ \t]*\n/).forEach(function (block) {
      var current = [];
      block.split("\n").forEach(function (rawLine) {
        var line = rawLine.trim();
        if (!line) return;
        if (/^#\s+/.test(line)) return;
        var heading = /^#{2,6}\s+/.test(line);
        var item = /^(?:[-*+]|\d+[.)])\s+/.test(line);
        line = line
          .replace(/^#{2,6}\s+/, "")
          .replace(/^(?:[-*+]|\d+[.)])\s+/, "")
          .replace(/^>\s?/, "")
          .replace(/(\*\*|__)(.*?)\1/g, "$2")
          .replace(/(^|[^\w*])\*([^*\n]+)\*/g, "$1$2")
          .replace(/`([^`]*)`/g, "$1")
          .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
          .trim();
        if (!line) return;
        if (item || heading) {
          if (current.length) paragraphs.push({ text: current.join(" "), heading: false });
          current = [];
          paragraphs.push({ text: line, heading: heading });
        } else {
          current.push(line);
        }
      });
      if (current.length) paragraphs.push({ text: current.join(" "), heading: false });
    });
    return paragraphs;
  }

  function firstLine(text) {
    var first = proseParagraphs(text).filter(function (paragraph) {
      return !paragraph.heading;
    })[0];
    return first ? first.text : "";
  }

  function prose(text) {
    return el(
      "div",
      { class: "ledger__prose" },
      proseParagraphs(text).map(function (paragraph) {
        return el("p", {
          class: paragraph.heading ? "ledger__prose-heading" : null,
          text: paragraph.text,
        });
      })
    );
  }

  /* One card. The head is the button: name, then the state word. The line under it is
   * the closed state; opening swaps the line for the details, widens the card to the
   * full row and closes whichever card was open. Details are built on first open. */
  function card(id, name, state, lineText, buildBody) {
    var panelId = "card-" + String(id).replace(/[^a-z0-9-]/gi, "-");
    var api = {};
    var built = false;
    var stateWord = el("span", { class: "card-check__state" });
    var head = el(
      "button",
      {
        class: "card-check__head",
        type: "button",
        "aria-expanded": "false",
        "aria-controls": panelId,
      },
      [el("span", { class: "card-check__name", text: name }), stateWord]
    );
    var line = el("p", { class: "card-check__line", text: lineText });
    var body = el("div", { class: "card-check__body", id: panelId, hidden: true });
    var node = el("section", { class: "card-check", "aria-label": name }, [head, line, body]);

    function setState(word) {
      stateWord.textContent = word;
      stateWord.className =
        "card-check__state" +
        (word === "needs you" ? " card-check__state--needs" : "") +
        (word === "optional" ? " card-check__state--optional" : "");
    }
    function setOpen(on) {
      if (on && cards.open && cards.open !== api) cards.open.close();
      head.setAttribute("aria-expanded", on ? "true" : "false");
      show(body, on);
      show(line, !on);
      setClass(node, "card-check--open", on);
      if (on) {
        cards.open = api;
        if (!built) {
          built = true;
          fill(body, buildBody());
        }
      } else if (cards.open === api) {
        cards.open = null;
      }
    }
    head.addEventListener("click", function () {
      setOpen(head.getAttribute("aria-expanded") !== "true");
    });
    node.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || head.getAttribute("aria-expanded") !== "true") return;
      event.preventDefault();
      setOpen(false);
      head.focus();
    });

    api.node = node;
    api.line = line;
    api.head = head;
    api.setState = setState;
    api.setLine = function (text) {
      line.textContent = text;
    };
    api.close = function () {
      setOpen(false);
    };
    api.isOpen = function () {
      return head.getAttribute("aria-expanded") === "true";
    };
    /* Details built from fresh facts: used when an answer or a check arrives after the
     * card was already open. */
    api.rebuild = function () {
      built = false;
      if (api.isOpen()) {
        built = true;
        fill(body, buildBody());
      }
    };
    setState(state);
    return api;
  }

  /* ---- the six answers ---------------------------------------------------- */

  function answerCard(key, field, isRequired) {
    var info = contextInfo(key);
    var source = fieldSource(field);
    var answered = source !== "missing";
    var entry = { key: key, field: field, info: info, answered: answered, record: null };
    var change = function () {
      return el("button", {
        class: "btn btn--ghost btn--sm",
        type: "button",
        text: answered ? "Change" : "Answer",
        title:
          (answered ? "Change your answer about " : "Answer the question about ") +
          info.title.toLowerCase(),
        on: {
          click: function () {
            openInterview(key);
          },
        },
      });
    };
    entry.card = card(
      "answer-" + key,
      info.title,
      answered ? "ready" : isRequired ? "needs you" : "optional",
      info.body,
      function () {
        var record = entry.record;
        var body = record && record.body ? String(record.body) : "";
        var question = record && record.question ? String(record.question) : "";
        var where = source === "discovered" ? field.discovered_path || "" : "";
        if (body) {
          return [
            prose(body),
            where ? el("p", { class: "row__path", text: "Found in " + where }) : null,
            el("div", { class: "btn-row" }, [change()]),
          ];
        }
        return [
          el("div", { class: "ledger__prose" }, [
            question ? el("p", { text: question }) : null,
            el("p", { text: answered ? "The answer on file could not be read." : info.body }),
          ]),
          el("div", { class: "btn-row" }, [change()]),
        ];
      }
    );
    return entry;
  }

  function answerCards(status) {
    var counts = contextCounts(status);
    var required = (status.context || {}).required || [];
    var entries = counts.order.map(function (key) {
      return answerCard(key, counts.fields[key], required.indexOf(key) !== -1);
    });
    return {
      entries: entries,
      nodes: entries.map(function (entry) {
        return entry.card.node;
      }),
    };
  }

  /* The line is the operator's own first sentence once it has been read. */
  function fillAnswer(entry, record) {
    entry.record = record;
    var body = record && record.body ? String(record.body) : "";
    if (body) entry.card.setLine(firstLine(body) || entry.info.body);
    entry.card.rebuild();
  }

  /* One read per brain. A late answer for a brain no longer on screen is dropped. */
  function fillAnswers(entries, path) {
    var key = normPath(path);
    function apply(records) {
      var byName = {};
      (records || []).forEach(function (record) {
        if (record && record.name) byName[record.name] = record;
      });
      entries.forEach(function (entry) {
        fillAnswer(entry, byName[entry.key] || null);
      });
    }
    if (ledger.answers[key]) {
      apply(ledger.answers[key]);
      return;
    }
    if (!ledger.pending[key]) {
      ledger.pending[key] = run("context show", { path: path }).then(function (result) {
        delete ledger.pending[key];
        var envelope = result.envelope;
        if (envelope && envelope.ok && Array.isArray(envelope.fields)) {
          ledger.answers[key] = envelope.fields;
        }
        return envelope && envelope.ok ? envelope.fields : null;
      });
    }
    ledger.pending[key].then(function (records) {
      if (normPath(App.path) !== key) return;
      apply(records);
    });
  }

  function forgetAnswers(path) {
    delete ledger.answers[normPath(path)];
    delete ledger.navigation[normPath(path)];
  }

  /* The next action, built from heroPlan. Its primary button is the one Ember object on
   * the page. */
  function nextRow(status) {
    var plan = heroPlan(status);
    var actions = el("div", { class: "next__actions" });
    var body = el("div", { class: "ledger__body next" }, [
      el("h2", { class: "next__title", text: plan.title }),
      el("p", { class: "next__body", text: plan.body }),
      actions,
    ]);
    plan.actions.forEach(function (action, index) {
      actions.appendChild(heroButton(action, body, index === 0));
    });
    return ledgerRow("Do this next", body, null, "ledger__row--next");
  }

  function heroButton(action, card, primary) {
    if (action.kind === "copy") {
      return el("button", {
        class: primary ? "btn btn--primary" : "btn btn--secondary",
        type: "button",
        text: action.label,
        on: {
          click: function () {
            copy(action.value, "Copied");
          },
        },
      });
    }
    if (action.kind === "wizard") {
      return el("button", {
        class: "btn btn--primary",
        type: "button",
        text: action.label,
        on: {
          click: function () {
            startWizard(preferredStart(App.path));
          },
        },
      });
    }
    if (action.kind === "interview") {
      return el("button", {
        class: primary ? "btn btn--primary" : "btn btn--secondary",
        type: "button",
        text: action.label,
        on: {
          click: function () {
            openInterview(action.field);
          },
        },
      });
    }
    if (action.kind === "goto") {
      return el("button", {
        class: primary ? "btn btn--primary" : "btn btn--secondary",
        type: "button",
        text: action.label,
        on: {
          click: function () {
            setView("commands");
            selectCommand(action.command);
          },
        },
      });
    }

    var button = el("button", {
      class: primary && !action.subtle ? "btn btn--primary" : "btn btn--secondary",
      type: "button",
      text: action.label,
    });
    button.addEventListener("click", function () {
      if (blocked(button)) return;
      var args = { path: App.path };
      Object.keys(action.args || {}).forEach(function (key) {
        args[key] = action.args[key];
      });
      if (action.kind === "plan-apply") args.plan = true;
      busy(button, true, action.kind === "plan-apply" ? "Working out the changes" : "Running");
      run(action.command, args).then(function (result) {
        busy(button, false);
        fill(button, [action.label]);
        // The readout sits flat in the row under a hairline, not in a card of its own.
        var panel = el("div", { class: "readout" }, [
          el("div", { class: "readout__body" }, [
            resultCard(result, {
              emptyChanges: "Everything is already in place.",
              title: "What came back",
            }),
          ]),
        ]);
        var existing = card.querySelector(".readout");
        if (existing) card.removeChild(existing);
        card.appendChild(panel);
        if (
          action.kind === "plan-apply" &&
          result.envelope &&
          result.envelope.ok &&
          changesOf(result.envelope).length
        ) {
          // The apply follows the result it applies, and while it is offered it is the
          // one Ember object in the row: the button that asked for the preview steps back.
          panel.appendChild(applyBar(action, panel));
          if (hasClass(button, "btn--primary")) {
            setClass(button, "btn--primary", false);
            setClass(button, "btn--secondary", true);
          }
        }
        land(panel.querySelector(".result__title"), resultSummary(result, action.label));
      });
    });
    return button;
  }

  function applyBar(action, panel) {
    var apply = el("button", {
      class: "btn btn--primary",
      type: "button",
      text: action.applyLabel || "Apply these changes",
    });
    apply.addEventListener("click", function () {
      if (blocked(apply)) return;
      var args = { path: App.path, yes: true };
      Object.keys(action.args || {}).forEach(function (key) {
        args[key] = action.args[key];
      });
      busy(apply, true, "Applying");
      run(action.command, args).then(function (applied) {
        fill(panel, [
          el("div", { class: "readout__body" }, [resultCard(applied, { title: "What changed" })]),
        ]);
        refresh(false);
        // This button has just been removed from the DOM. Put the operator on the result
        // they asked for, and say what actually happened to their files.
        land(
          panel.querySelector(".result__title"),
          resultSummary(applied, action.applyLabel || "Apply")
        );
      });
    });
    return el("div", { class: "btn-row applybar" }, [apply]);
  }

  /* Authored copy, keyed off the envelope's next_action id. These sentences are ours, not
   * the server's — see the note at the top of this file. */
  function heroPlan(status) {
    var id = (status.next_action || {}).id || "none";
    var missing = (status.context && status.context.missing) || [];

    if (id === "run-setup") {
      return {
        title: "There is no brain in this folder yet.",
        body: "Setting one up takes about a minute, and writes nothing until you confirm.",
        actions: [{ kind: "wizard", label: "Set up a brain" }],
      };
    }
    if (id === "repair-structure") return repairPlan(status);
    if (id === "sync-skills") {
      return {
        title: "Your assistants cannot see the latest skills.",
        body:
          "Claude Code and Codex each keep their own copy of the shared skills, and yours are " +
          "missing or out of date. This previews the fix first, so nothing is written until you say so.",
        actions: [
          {
            kind: "plan-apply",
            label: "Preview the fix",
            command: "skills sync",
            applyLabel: "Apply the sync",
          },
        ],
      };
    }
    if (id.indexOf("complete-") === 0 || id === "run-interview") {
      var key = missing[0] || id.slice("complete-".length);
      var info = contextInfo(key);
      return {
        title: "It does not know your business yet.",
        body:
          "Answer " +
          plural(missing.length, "question") +
          " in your own words, starting with " +
          info.title.toLowerCase() +
          ". The app asks them one at a time, right here, and writes the answers for you.",
        actions: [
          { kind: "interview", label: "Answer the questions", field: key },
          { kind: "run", label: "Check again", command: "status", subtle: true },
        ],
      };
    }
    if (id === "follow-current-focus" || id === "run-start") {
      return {
        title: "Everything is in place.",
        body:
          "The brain holds your current priority and knows how you sound. Ask it a question, " +
          "or go back over your answers whenever the business moves on.",
        actions: [
          { kind: "goto", label: "Ask this brain a question", command: "query" },
          { kind: "interview", label: "Review your answers", field: null },
        ],
      };
    }
    return {
      title: "Next up",
      body: (status.next_action || {}).reason || "Nothing needs your attention.",
      actions: [{ kind: "run", label: "Re-check", command: "status", subtle: true }],
    };
  }

  /* The next_action id only says "repair"; what to repair is in the findings. The hero is
   * built from the worst one, so its title names the thing that is wrong and its button
   * does the thing that fixes it. Setting the brain up again is safe on an existing brain:
   * it creates only what is missing and never touches a file that exists. */
  function repairPlan(status) {
    var groups = groupFindings(findingsOf(status));
    var top =
      groups.filter(function (group) {
        return group.severity === "error";
      })[0] || groups[0];
    var code = top ? top.code : "";
    var n = top ? top.items.length : 0;
    var name = (status.business || {}).name || "";
    var mode = status.mode;
    var canScaffold = Boolean(name) && (mode === "in-house" || mode === "agency");
    var showAll = { kind: "run", label: "Show everything the check found", command: "validate" };

    if (code === "missing-file" || code === "missing-directory") {
      var what = plural(n, code === "missing-file" ? "required file" : "required folder");
      return {
        title: "The brain is missing " + what + ".",
        body:
          "Nothing else is affected. Setting it up again adds what is missing, plus any " +
          "housekeeping files a newer version brought, and leaves every answer as it is. You " +
          "see the full list before anything is written.",
        actions: canScaffold
          ? [
              {
                kind: "plan-apply",
                label: "Preview the missing pieces",
                command: "onboard",
                args: { name: name, mode: mode },
                applyLabel: "Add the missing pieces",
              },
              { kind: "run", label: showAll.label, command: "validate", subtle: true },
            ]
          : [showAll],
      };
    }
    if (code === "missing-frontmatter") {
      return {
        title: findingWords(top).title,
        body: FINDING_COPY["missing-frontmatter"].fix,
        actions: [{ kind: "run", label: "Show which documents", command: "validate" }],
      };
    }
    if (code === "unlinked-document") {
      return {
        title: findingWords(top).title,
        body: FINDING_COPY["unlinked-document"].fix,
        actions: [
          {
            kind: "plan-apply",
            label: "Preview the links",
            command: "related",
            applyLabel: "Add the links",
          },
          { kind: "run", label: showAll.label, command: "validate", subtle: true },
        ],
      };
    }
    if (top && FINDING_COPY[code]) {
      return {
        title: findingWords(top).title,
        body: FINDING_COPY[code].fix,
        actions: [showAll, { kind: "goto", label: "Open the migrate tool", command: "migrate" }],
      };
    }
    return {
      title: "Some files are out of place.",
      body: "Nothing is lost. Run the check to see exactly which, then move or rename them.",
      actions: [showAll, { kind: "goto", label: "Open the migrate tool", command: "migrate" }],
    };
  }

  /* ---- the four checks ---------------------------------------------------- */

  /* Findings the structure check owns: where files and folders are, and whether the
   * brain's own configuration reads. */
  var STRUCTURE_CODES = [
    "missing-file",
    "missing-directory",
    "unknown-top-level",
    "invalid-dated-artifact",
    "invalid-year",
    "invalid-quarter",
    "invalid-month",
    "invalid-report-month",
    "invalid-type",
    "invalid-status",
    "missing-or-invalid-config",
    "unsupported-schema",
    "missing-client-registry",
    "set-mode-agency",
    "unexpected-clients-folder",
  ];

  function planAction(action, container) {
    return el("div", { class: "btn-row" }, [heroButton(action, container, false)]);
  }

  function structureCard(status, doctor) {
    var checks = (doctor && doctor.checks) || {};
    var ok = checks.structure !== false;
    var errors = severityCount(status, "error");
    var findings = findingsOf(status).filter(function (item) {
      return item && STRUCTURE_CODES.indexOf(item.code) !== -1;
    });
    var body = el("div", {});
    return card(
      "structure",
      "Structure",
      ok ? "ready" : "needs you",
      ok ? "Every folder and file is where it should be." : plural(errors, "thing") + " out of place.",
      function () {
        var repair = repairPlan(status);
        var plan = repair.actions.filter(function (action) {
          return action.kind === "plan-apply" && action.command === "onboard";
        })[0];
        fill(body, [
          findings.length
            ? findingRows(findings)
            : el("p", { class: "card__sub", text: "The last check found nothing out of place." }),
          plan && !ok ? planAction(plan, body) : null,
        ]);
        return [body];
      }
    );
  }

  function assistantsCard(status) {
    var runtimes = status.runtimes || {};
    var keys = Object.keys(runtimes);
    var allReady = keys.every(function (key) {
      return runtimes[key].ready;
    });
    var notReady = keys.filter(function (key) {
      return !runtimes[key].ready;
    });
    var line = !keys.length
      ? "No assistants detected."
      : allReady
        ? keys
            .map(function (key) {
              return (RUNTIME_LABEL[key] || key) + " ready";
            })
            .join(" · ")
        : notReady
            .map(function (key) {
              return RUNTIME_LABEL[key] || key;
            })
            .join(" and ") + " cannot see the current skills.";
    var body = el("div", {});
    return card("assistants", "Assistants", keys.length && allReady ? "ready" : "needs you", line, function () {
      var rows = el(
        "ul",
        { class: "rows", role: "list" },
        keys.map(function (key) {
          var runtime = runtimes[key];
          var problems = (runtime.missing || []).length + (runtime.mismatched || []).length;
          return el("li", { class: "row" }, [
            icon(runtime.ready ? "check" : "alert", "row__icon " + (runtime.ready ? "row__icon--ok" : "row__icon--warn")),
            el("div", { class: "row__body" }, [
              el("p", { class: "row__msg", text: RUNTIME_LABEL[key] || key }),
              el("p", {
                class: "row__sub",
                text: runtime.ready
                  ? "Up to date with this version's skills."
                  : plural((runtime.missing || []).length, "skill") +
                    " missing, " +
                    (runtime.mismatched || []).length +
                    " out of date",
              }),
            ]),
            el("span", { class: "row__end" }, [
              el("span", {
                class: runtime.ready ? "pill pill--ok" : "pill pill--warn",
                text: runtime.ready ? "Ready" : plural(problems, "problem"),
              }),
            ]),
          ]);
        })
      );
      fill(body, [
        keys.length ? rows : emptyState("No assistants detected", "Nothing reported a skill folder here."),
        keys.length && !allReady
          ? planAction(
              {
                kind: "plan-apply",
                label: "Preview the fix",
                command: "skills sync",
                applyLabel: "Apply the sync",
              },
              body
            )
          : null,
        keys.length
          ? tech(
              [
                el(
                  "ul",
                  { class: "changes changes--static", role: "list" },
                  keys.map(function (key) {
                    return el("li", {
                      text: (RUNTIME_LABEL[key] || key) + " -> " + runtimes[key].skill_dir,
                    });
                  })
                ),
              ],
              "Show each assistant's skill folder"
            )
          : null,
      ]);
      return [body];
    });
  }

  function findingsCard(status) {
    var findings = findingsOf(status);
    var total = findingsTotal(status);
    var withheld = total - findings.length;
    return card(
      "findings",
      "Findings",
      total ? "needs you" : "ready",
      total ? plural(total, "thing") + " found, errors first" : "Nothing to fix",
      function () {
        var recheck = el("button", {
          class: "btn btn--ghost btn--sm",
          type: "button",
          title: "Re-check this brain",
          "aria-label": "Re-check this brain",
          on: {
            click: function () {
              refresh(true);
            },
          },
        });
        add(recheck, [icon("refresh"), el("span", { text: "Re-check" })]);
        var actions = [recheck];
        if (withheld) {
          actions.unshift(
            el("button", {
              class: "btn btn--ghost btn--sm",
              type: "button",
              text: "Open the checker",
              on: {
                click: function () {
                  selectCommand("validate");
                  setView("commands");
                },
              },
            })
          );
        }
        return [
          findings.length
            ? findingRows(findings)
            : el("p", {
                class: "card__sub",
                text: "The last check came back clean. Anything that needs doing is at the top of this page.",
              }),
          // The count is the checker's own, always. Only the rows are ever shortened,
          // and when they are this says so.
          withheld
            ? el("p", {
                class: "card__sub",
                text:
                  "It found " +
                  plural(total, "thing") +
                  "; the first " +
                  findings.length +
                  " are here, errors before warnings. " +
                  plural(withheld, "finding") +
                  " not listed.",
              })
            : null,
          el("div", { class: "btn-row" }, actions),
        ];
      }
    );
  }

  /* The navigation check is read once per brain through `mos index status`; until it
   * answers the card says so and carries no state word. */
  function navigationCard() {
    var entry = { envelope: null, failed: false };
    var body = el("div", {});
    entry.card = card("navigation", "Navigation", "", "Checking the navigation.", function () {
      var envelope = entry.envelope;
      var findings = envelope ? findingsOf(envelope) : [];
      fill(body, [
        !envelope
          ? el("p", {
              class: "card__sub",
              text: entry.failed ? "The navigation could not be checked." : "Still checking.",
            })
          : findings.length
            ? findingRows(findings)
            : el("p", { class: "card__sub", text: "The catalogue and the navigation map match what is on disk." }),
        findings.length
          ? planAction(
              {
                kind: "plan-apply",
                label: "Rebuild the navigation",
                command: "index sync",
                applyLabel: "Rebuild it",
              },
              body
            )
          : null,
      ]);
      return [body];
    });
    return entry;
  }

  function navigationLine(envelope) {
    var groups = groupFindings(findingsOf(envelope));
    if (!groups.length) return "Up to date";
    return findingWords(groups[0]).title;
  }

  function fillNavigation(entry, path) {
    var key = normPath(path);
    function apply(envelope) {
      if (envelope) {
        entry.envelope = envelope;
        entry.card.setLine(navigationLine(envelope));
        entry.card.setState(findingsTotal(envelope) ? "needs you" : "ready");
      } else {
        entry.failed = true;
        entry.card.setLine("The navigation could not be checked.");
        entry.card.setState("needs you");
      }
      entry.card.rebuild();
    }
    if (ledger.navigation[key]) {
      apply(ledger.navigation[key]);
      return;
    }
    if (!ledger.navPending[key]) {
      ledger.navPending[key] = run("index status", { path: path }).then(function (result) {
        delete ledger.navPending[key];
        var envelope = result.envelope;
        if (envelope && envelope.ok) ledger.navigation[key] = envelope;
        return envelope && envelope.ok ? envelope : null;
      });
    }
    ledger.navPending[key].then(function (envelope) {
      if (normPath(App.path) !== key) return;
      apply(envelope);
    });
  }

  function checkCards(status, doctor) {
    var navigation = navigationCard();
    return {
      navigation: navigation,
      nodes: [
        structureCard(status, doctor).node,
        assistantsCard(status).node,
        findingsCard(status).node,
        navigation.card.node,
      ],
    };
  }

  /* The closing row. No launcher is invented: the exact lines sit behind the technical
   * disclosure with a copy button each. */
  function openRow(status) {
    var repo = status.repo || App.path;
    var body = el("div", { class: "ledger__body" }, [
      el("p", { class: "ledger__line", text: "Open this brain in Claude Code" }),
      el("p", {
        class: "next__body",
        text: "Open a terminal in this folder and start Claude Code, then type /mos-start.",
      }),
      tech(
        [
          el("p", { class: "tech__line" }, [
            "This brain is at ",
            el("code", { text: repo, title: repo }),
            ".",
          ]),
          terminal('cd "' + repo + '"', "Go to the folder"),
          terminal("claude", "Start Claude Code"),
          el("p", { class: "tech__line" }, [
            "Then, inside Claude Code, type ",
            el("code", { text: "/mos-start" }),
            ".",
          ]),
          el("div", { class: "btn-row" }, [
            el("button", {
              class: "btn btn--secondary btn--sm",
              type: "button",
              text: "Copy that path",
              on: {
                click: function () {
                  copy(repo, "Folder path copied");
                },
              },
            }),
          ]),
        ],
        "Show the exact lines"
      ),
    ]);
    return ledgerRow("Claude Code", body, null, "ledger__row--open-brain");
  }

  /* =============================================================== commands */

  var cmd = { current: null, values: {}, previewSig: null, builtFor: null, buttons: [] };

  function renderCommandList() {
    fill(
      $("cmd-list"),
      GROUPS.map(function (group) {
        var names = App.specs
          .map(function (spec) {
            return spec.command;
          })
          .filter(function (name) {
            return commandInfo(name).group === group.id;
          })
          .sort(function (left, right) {
            var a = commandInfo(left).order;
            var b = commandInfo(right).order;
            return a === b ? (left < right ? -1 : 1) : a - b;
          });
        if (!names.length) return null;
        var list = el(
          "div",
          {},
          names.map(function (name) {
            var info = commandInfo(name);
            return el(
              "button",
              {
                class: "cmd-item",
                type: "button",
                "data-command": name,
                on: {
                  click: function () {
                    selectCommand(name);
                  },
                },
              },
              [
                el("span", { class: "cmd-item__name", text: info.title }),
                el("span", { class: "cmd-item__cli", text: "mos " + name }),
              ]
            );
          })
        );
        // The advanced tier folds away by default; its summary is the group label.
        if (group.folded) {
          return el("details", { class: "cmd-group cmd-adv" }, [
            el("summary", {}, [icon("down", "disc"), el("span", { text: group.label })]),
            list,
          ]);
        }
        return el("div", { class: "cmd-group" }, [
          el("h3", { class: "cmd-group__label", text: group.label }),
          list,
        ]);
      })
    );
  }

  function selectCommand(name) {
    var spec = App.specs.filter(function (item) {
      return item.command === name;
    })[0];
    if (!spec) return;
    cmd.current = spec;
    cmd.values = {};
    cmd.previewSig = null;
    cmd.builtFor = App.path;
    Array.prototype.forEach.call($("cmd-list").querySelectorAll(".cmd-item"), function (button) {
      if (button.getAttribute("data-command") === name) {
        button.setAttribute("aria-current", "true");
        // A command chosen from elsewhere in the app must be visible in the list.
        var folded = button.closest("details");
        if (folded) folded.setAttribute("open", "");
      } else button.removeAttribute("aria-current");
    });
    renderCommandPanel();
  }

  function initialValue(argName) {
    if (argName === "path") return App.path;
    return argInfo(argName).initial || "";
  }

  function fieldFor(spec, argName, kind) {
    var info = argInfo(argName);
    var id = "cmd-" + argName;
    var helpId = id + "-help";
    var required = (spec.required || []).indexOf(argName) !== -1;

    if (kind === "flag") {
      cmd.values[argName] = false;
      var box = el("input", { type: "checkbox", id: id });
      box.addEventListener("change", function () {
        cmd.values[argName] = box.checked;
        cmd.previewSig = null;
        updateRunButtons();
      });
      return el("label", { class: "check", for: id }, [box, el("span", { text: info.label })]);
    }

    var initial = initialValue(argName);
    var control;
    if (info.choices) {
      // A <select> must never display one thing while holding another. The empty option
      // is real, so an unchosen argument reads as unchosen instead of looking like the
      // first choice while being silently dropped on the way out.
      control = el(
        "select",
        { class: "select", id: id },
        [el("option", { value: "", text: info.empty || "Not set" })].concat(
          info.choices.map(function (choice) {
            return el("option", { value: choice, text: choice });
          })
        )
      );
      control.value = info.choices.indexOf(initial) === -1 ? "" : initial;
    } else {
      control = el("input", {
        class: info.mono ? "input input--mono" : "input",
        id: id,
        type: info.type || "text",
        autocomplete: "off",
        spellcheck: info.mono ? "false" : null,
        placeholder: info.placeholder || null,
      });
      control.value = initial;
    }
    if (required) {
      control.setAttribute("required", "");
      control.setAttribute("aria-required", "true");
    }
    if (info.help) control.setAttribute("aria-describedby", helpId);
    // Whatever the browser actually settled on is what we hold. No drift, ever.
    cmd.values[argName] = control.value;

    // Update the buttons in place, never rebuild them: `change` fires on blur, so
    // replacing the button row here would detach the very button being clicked and the
    // first click after typing would do nothing at all.
    function sync() {
      cmd.values[argName] = control.value;
      cmd.previewSig = null;
      updateRunButtons();
    }
    control.addEventListener("input", sync);
    control.addEventListener("change", sync);

    return el("div", { class: "field" }, [
      el("label", { class: "field__label", for: id }, [
        info.label,
        // Visible and readable: an aria-hidden asterisk tells assistive tech nothing.
        required ? el("span", { class: "field__req", text: "required" }) : null,
      ]),
      info.help ? el("p", { class: "field__help", id: helpId, text: info.help }) : null,
      control,
    ]);
  }

  /* The result region is reserved and labelled before the click, so nobody is left
   * staring at empty canvas wondering where the output will go. */
  function resultPlaceholder(command) {
    return el("section", { class: "card card--waiting" }, [
      el("h2", { class: "card__title", text: "Results appear here" }),
      el("p", {
        class: "card__sub",
        text:
          "Nothing has run yet. Start " +
          commandInfo(command).title.toLowerCase() +
          " above and what came back lands in this panel: anything wrong first, then anything that changed.",
      }),
      terminal("mos " + command, "The command behind this"),
    ]);
  }

  function renderCommandPanel() {
    var spec = cmd.current;
    if (!spec) {
      fill($("cmd-panel"), [
        el("div", { class: "card" }, [
          emptyState(
            "Pick a command",
            "Everything on the left runs the same code the terminal does.",
            "terminal"
          ),
        ]),
      ]);
      return;
    }
    var info = commandInfo(spec.command);

    var form = el("div", { class: "form-grid" });
    spec.positionals.forEach(function (name) {
      form.appendChild(fieldFor(spec, name, "positional"));
    });
    spec.options.forEach(function (name) {
      form.appendChild(fieldFor(spec, name, "option"));
    });
    var plainFlags = spec.flags.filter(function (name) {
      return name !== "plan" && name !== "yes";
    });
    if (plainFlags.length) {
      form.appendChild(
        el(
          "div",
          { class: "flags" },
          plainFlags.map(function (name) {
            return fieldFor(spec, name, "flag");
          })
        )
      );
    }

    fill($("cmd-panel"), [
      el("section", { class: "card" }, [
        el("div", { class: "card__head" }, [
          el("div", {}, [
            el("h2", { class: "card__title", text: info.title }),
            el("p", { class: "card__sub", text: info.blurb }),
          ]),
          el("span", { class: "card__end" }, [
            el("span", {
              class: spec.mutating ? "pill pill--warn" : "pill",
              text: spec.mutating ? "Writes files" : "Read only",
            }),
          ]),
        ]),
        form,
        el("div", { class: "btn-row applybar applybar--top", id: "cmd-buttons" }),
        el("p", { class: "field__help", id: "cmd-block", text: "" }),
      ]),
      el("div", { id: "cmd-result" }, [resultPlaceholder(spec.command)]),
    ]);
    buildRunButtons();
  }

  function argsFromForm() {
    var args = {};
    Object.keys(cmd.values).forEach(function (key) {
      var value = cmd.values[key];
      if (value === false || value === "" || value === null || value === undefined) return;
      args[key] = value;
    });
    return args;
  }

  function signature() {
    return JSON.stringify(argsFromForm());
  }

  function missingArgs() {
    return (cmd.current.required || []).filter(function (name) {
      return !cmd.values[name];
    });
  }

  /* Built once per panel. Afterwards only their state changes — see sync(). */
  function buildRunButtons() {
    var host = $("cmd-buttons");
    if (!host || !cmd.current) return;
    cmd.buttons = [];
    if (!cmd.current.mutating) {
      fill(host, [makeRunButton("Run it", "btn--primary", {})]);
    } else {
      fill(host, [
        makeRunButton("Preview the changes", "btn--primary", { plan: true }),
        makeRunButton("Apply them", "btn--secondary", { yes: true }),
      ]);
    }
    updateRunButtons();
  }

  function updateRunButtons() {
    if (!cmd.current || !$("cmd-block")) return;
    var missing = missingArgs();
    var previewed = cmd.previewSig === signature();
    var reason = missing.length
      ? "Fill in " +
        missing
          .map(function (name) {
            return argInfo(name).label.toLowerCase();
          })
          .join(" and ") +
        " first."
      : cmd.current.mutating
        ? previewed
          ? "You have seen the plan. Applying writes those files."
          : "Preview first. Nothing is written until you have seen the plan."
        : "";
    cmd.buttons.forEach(function (entry) {
      var stop = !!missing.length || (entry.extra.yes && !previewed);
      setBlocked(entry.node, stop, "cmd-block");
    });
    $("cmd-block").textContent = reason;
  }

  function makeRunButton(label, cls, extra) {
    var button = el("button", { class: "btn " + cls, type: "button", text: label });
    cmd.buttons.push({ node: button, extra: extra, label: label });
    // aria-disabled, not disabled: a button that vanishes from the tab order is a
    // keyboard dead end, and the reason it will not run is never heard.
    setBlocked(button, false, "cmd-block");
    button.addEventListener("click", function () {
      if (blocked(button)) {
        var missing = missingArgs();
        announce($("cmd-block").textContent || "That cannot run yet.");
        var field = missing.length ? $("cmd-" + missing[0]) : null;
        if (field) field.focus();
        return;
      }
      var spec = cmd.current;
      var args = argsFromForm();
      Object.keys(extra).forEach(function (key) {
        args[key] = extra[key];
      });
      var signatureNow = signature();
      busy(button, true, extra.plan ? "Working it out" : "Running");
      renderRunning(spec.command);
      run(spec.command, args).then(function (result) {
        busy(button, false);
        fill(button, [label]);
        if (extra.plan && result.envelope && result.envelope.ok) cmd.previewSig = signatureNow;
        if (extra.yes) cmd.previewSig = null;
        renderCommandResult(result, spec.command);
        updateRunButtons();
        if (extra.yes) refresh(false);
      });
    });
    return button;
  }

  var tickTimer = null;
  function renderRunning(command) {
    var started = Date.now();
    var elapsed = el("span", { class: "result__elapsed", text: "0.0s" });
    fill($("cmd-result"), [
      el("div", { class: "card", "aria-busy": "true" }, [
        el("div", { class: "progress" }, [el("div", { class: "progress__bar" })]),
        el("div", { class: "result__head" }, [
          el("h2", { class: "result__title", text: "Running" }),
          el("span", { class: "pill pill--accent" }, [
            el("span", { class: "btn__spin", "aria-hidden": "true" }),
            "mos " + command,
          ]),
          elapsed,
        ]),
        el("p", {
          class: "card__sub",
          text:
            "This runs the real command. A large brain takes longer, and the page stays live while it works.",
        }),
      ]),
    ]);
    window.clearInterval(tickTimer);
    tickTimer = window.setInterval(function () {
      elapsed.textContent = ((Date.now() - started) / 1000).toFixed(1) + "s";
    }, 100);
    announce("Running " + command + ".");
  }

  function renderCommandResult(result, command) {
    window.clearInterval(tickTimer);
    fill($("cmd-result"), [
      el("div", { class: "card" }, [
        resultCard(result, {
          emptyChanges: "Everything this command would do is already done.",
          title: "What came back from " + command,
        }),
      ]),
    ]);
    // Land on the output that was asked for, and say what it actually says.
    land($("cmd-result").querySelector(".result__title"), resultSummary(result, "mos " + command));
  }

  /* =================================================================== boot */

  function refresh(showBoot) {
    forgetAnswers(App.path);
    if (showBoot) {
      // Said before the focused element is hidden out from under the operator.
      announce("Re-reading the folder.");
      fill($("boot-actions"), []);
      $("boot-title").textContent = "Reading the folder";
      $("boot-body").textContent = "One moment.";
      setView("boot");
    }
    return Promise.all([run("status", { path: App.path }), run("doctor", { path: App.path })]).then(
      function (results) {
        var status = results[0].envelope;
        if (!status) {
          fatal(
            "Could not read that folder",
            "The local app did not answer. It may have been stopped; start it again from the terminal.",
            results[0].transport || ""
          );
          return;
        }
        App.status = status;
        App.doctor = results[1].envelope;
        if (cmd.current && cmd.builtFor !== App.path) selectCommand(cmd.current.command);
        renderSidebar();
        if (status.repo_state === "absent") {
          startWizard(preferredStart(App.path));
          return;
        }
        renderDashboard();
        if (App.view !== "commands" && App.view !== "interview") setView("dashboard");
        if (showBoot) {
          land(
            $("dash-title"),
            ($("dash-title").textContent || "This brain") +
              ". " +
              repoHealth(status).label +
              ". " +
              plural(findingsTotal(status), "finding") +
              "."
          );
        }
      }
    );
  }

  function fatal(title, body, detail) {
    $("boot-title").textContent = title;
    $("boot-body").textContent = body;
    $("boot-detail").textContent = detail || "";
    fill($("boot-actions"), [
      el("button", {
        class: "btn btn--primary",
        type: "button",
        text: "Try again",
        on: { click: boot },
      }),
    ]);
    var spinner = document.querySelector("#boot .spinner");
    if (spinner) spinner.style.display = "none";
    setView("boot");
    // The whole page just became an error. Say so, and put focus on it.
    land($("boot-title"), title + ". " + body);
  }

  /* Find the operator's home folder through the CLI, which expands ~ for us. Only used
   * against a server too old to report `home` in /api/state: one subprocess per boot is
   * worth avoiding when the server already has the answer. */
  function findHome() {
    return run("status", { path: "~" }).then(function (result) {
      if (result.envelope && result.envelope.repo) App.home = result.envelope.repo;
      return App.home;
    });
  }

  function boot() {
    var spinner = document.querySelector("#boot .spinner");
    if (spinner) spinner.style.display = "";
    $("boot-title").textContent = "Getting ready";
    $("boot-body").textContent = "One moment.";
    setView("boot");
    request("/api/state")
      .then(function (res) {
        // Newer servers report the home folder with the rest of app state; older ones
        // need the round trip. Either way the page waits for one answer, not two.
        if (res.ok && res.data && res.data.home) {
          App.home = res.data.home;
          return res;
        }
        return findHome().then(function () {
          return res;
        });
      })
      .then(
      function (res) {
        if (!res.ok || !res.data || !res.data.schema) {
          fatal(
            "This page cannot talk to the app",
            "The session token was refused. Close this tab and open the address the app printed when it started."
          );
          return;
        }
        App.state = res.data;
        App.specs = res.data.command_specs || [];
        App.brains = Array.isArray(res.data.brains) ? res.data.brains : [];
        var stored = remembered();
        App.path = stored || res.data.root;
        renderCommandList();
        selectCommand("status");
        renderSidebar();

        // The answer just read is this brain's whenever the stored path is the folder the
        // app was started in, which is the usual case for anyone with one brain. Asking
        // for status and doctor again then threw away a full reading of the brain and
        // paid for a second one; the only reason left to ask is a stored brain that is
        // not this root, and that is a different question rather than the same one twice.
        if (res.data.is_brain && res.data.status && normPath(App.path) === normPath(res.data.root)) {
          App.status = res.data.status;
          App.doctor = res.data.doctor;
          renderDashboard();
          setView("dashboard");
          return;
        }
        refresh(false);
      },
      function (error) {
        fatal(
          "The local app is not answering",
          "Nothing is lost: your files are on disk. Go back to the terminal you started this " +
            "from, start it again, then reload this page.",
          String(error)
        );
      }
    );
  }

  wireTabs();
  wireSidebar();
  wireWizard();
  boot();
})();
