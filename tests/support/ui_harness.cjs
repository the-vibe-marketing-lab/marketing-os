"use strict";
/* Run the shipped app.js against the small DOM in ui_dom.cjs and report what the
 * assisted interview actually does. Every scenario starts from a fresh evaluation of
 * app.js in a fresh context, so nothing leaks between them.
 *
 * Usage: node ui_harness.cjs <fixture.json>   -> one JSON object on stdout.
 */

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { makeDocument } = require("./ui_dom.cjs");

const fixture = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const STATIC = fixture.static;
const APP = fs.readFileSync(path.join(STATIC, "app.js"), "utf8");
const HTML = fs.readFileSync(path.join(STATIC, "index.html"), "utf8");
const IDS = Array.from(HTML.matchAll(/\bid="([^"]+)"/g)).map((m) => m[1]);

function drain() {
  // Let every already-resolved promise chain settle.
  return new Promise((resolve) => setImmediate(resolve));
}

async function settle(times) {
  for (let i = 0; i < (times || 12); i += 1) await drain();
}

/* One running app, with a scripted server behind it. */
function launch(plan) {
  const dom = makeDocument(IDS);
  // index.html ships the panel closed; the DOM here is built from ids alone.
  dom.document.getElementById("browse-panel").setAttribute("hidden", "");
  const calls = [];
  const picks = [];
  const browses = [];
  const asks = (plan.asks || []).slice();
  const state = Object.assign({}, fixture.state, plan.state || {});
  // The registry behind /api/brains, as the plan seeded it. remember/forget edit it;
  // every state answer carries a copy, the way the server's does.
  const brains = (state.brains || []).map((b) => Object.assign({}, b));
  const brainOps = [];
  const attached = new Set();
  // Folders the server has refused with a 400 (plan.missing): from then on the list it
  // sends back says they are gone, the way the real registry re-reads disk.
  const vanished = new Set();
  const clone = () =>
    brains.map((b) => Object.assign({}, b, vanished.has(b.path) ? { exists: false } : {}));

  /* One answer to "what is at `root`?", shared by /api/state?path= and the `status`
   * stub so the two can never disagree: the fixture brain and every listed brain are
   * brains named as the list names them; an older layout (plan.attachable, or listed
   * as such) is attachable until an attach --yes has run against it; plan.hollow names
   * folders the list still calls brains but disk no longer does; anything else is
   * empty ground. */
  function folderFacts(root) {
    const known = brains.filter((b) => b.path === root)[0];
    const older = (known && known.attachable) || (plan.attachable || []).indexOf(root) !== -1;
    const attachable = !!older && !attached.has(root);
    const hollow = (plan.hollow || []).indexOf(root) !== -1;
    const isBrain =
      !attachable && !hollow && (root === fixture.state.root || attached.has(root) || !!(known && known.is_brain !== false));
    const name = known ? known.name : path.basename(root);
    return { known: known, attachable: attachable, isBrain: isBrain, name: name };
  }

  function statusFor(root) {
    const facts = folderFacts(root);
    const base = fixture.envelopes.status;
    if (!facts.isBrain && !facts.attachable) {
      return Object.assign({}, base, { repo: root, repo_state: "absent" });
    }
    return Object.assign({}, base, {
      repo: root,
      business: Object.assign({}, base.business || {}, { name: facts.name }),
    });
  }

  function stateFor(root) {
    const facts = folderFacts(root);
    return Object.assign({}, state, {
      root: root,
      is_brain: facts.isBrain,
      attachable: facts.attachable,
      business_name: facts.name,
      status: statusFor(root),
      doctor: fixture.envelopes.doctor,
      brains: clone(),
    });
  }

  function refusal(code, message) {
    return {
      envelope: { schema: "mos.ui.v1", command: "ui", ok: false, findings: [{ code: code, message: message, severity: "error", path: "" }] },
      command_line: "",
    };
  }

  function reply(data, ok, status) {
    return Promise.resolve({
      ok: ok !== false,
      status: status || 200,
      json: () => Promise.resolve(data),
    });
  }

  function fetchStub(url, init) {
    if (url === "/api/state") return reply(Object.assign({}, state, { brains: clone() }));
    if (url.indexOf("/api/state?path=") === 0) {
      const root = decodeURIComponent(url.slice("/api/state?path=".length));
      if ((plan.missing || []).indexOf(root) !== -1) {
        vanished.add(root);
        return reply(refusal("bad-path", "path must be an existing folder."), false, 400);
      }
      return reply(stateFor(root));
    }
    const body = JSON.parse((init && init.body) || "{}");
    if (url === "/api/brains") {
      brainOps.push(body);
      const index = brains.map((b) => b.path).indexOf(body.path);
      if (body.op === "forget" && index !== -1) brains.splice(index, 1);
      if (body.op === "remember" && index === -1) {
        brains.unshift({ path: body.path, name: path.basename(body.path), mode: null, legacy: false, attachable: false, exists: true, last_opened: "now" });
      }
      return reply({ brains: clone() });
    }
    if (url === "/api/pick-folder") {
      // The folder window the operating system would open; the plan scripts its answer.
      picks.push(body);
      if (plan.pick && plan.pick.transport) return Promise.reject(new Error("connection lost"));
      return reply(plan.pick || { path: null, cancelled: true, available: true, error: null, backend: "wsl" });
    }
    if (url === "/api/browse") {
      // The panel's own requests and the found-brains look at the chosen place share one
      // route; whether the panel was open at the time is what tells them apart here.
      const panel = dom.document.getElementById("browse-panel");
      browses.push(Object.assign({ panelOpen: !panel.hasAttribute("hidden") }, body));
      const where = body.path || state.places[0].path;
      const canned = plan.browse && plan.browse[where];
      if (canned) return reply(canned);
      return reply({ path: where, parent: "/home/you", children: [], is_brain: false, attachable: false, brain: null, error: null });
    }
    calls.push({ command: body.command, args: body.args || {} });
    if (body.command === "attach") {
      if (body.args.yes) attached.add(body.args.path);
      const envelope = Object.assign({}, fixture.envelopes.status, {
        command: "attach",
        ok: true,
        repo: body.args.path,
        changes: ["backup .mos/config.legacy.yaml", "config .mos/config.yaml", "create BRAIN.md"],
        findings: [],
      });
      return reply({ envelope: envelope, command_line: "mos attach " + (body.args.yes ? "--yes" : "--plan") });
    }
    if (body.command === "assist status") return reply({ envelope: plan.probe, command_line: "mos assist status" });
    if (body.command === "assist ask") {
      const next = asks.shift();
      if (!next) return reply({ envelope: null, command_line: "" }, false, 500);
      if (next.transport) return Promise.reject(new Error("connection lost"));
      return reply({ envelope: next.envelope, command_line: "mos assist ask --field brand" });
    }
    if (body.command === "status" && body.args.path && body.args.path !== fixture.state.root) {
      // The same facts /api/state?path= answers from, so a probe and a switch agree.
      return reply({ envelope: statusFor(body.args.path), command_line: "mos status" });
    }
    const canned = fixture.envelopes[body.command];
    if (canned) return reply({ envelope: canned, command_line: "mos " + body.command });
    return reply({ envelope: null, command_line: "" }, false, 404);
  }

  const sandbox = {
    document: dom.document,
    navigator: {},
    console: console,
    fetch: fetchStub,
    window: {
      setTimeout: setTimeout,
      clearTimeout: clearTimeout,
      setInterval: setInterval,
      clearInterval: clearInterval,
      scrollTo: () => {},
      sessionStorage: {
        store: new Map(),
        getItem(key) {
          return this.store.has(key) ? this.store.get(key) : null;
        },
        setItem(key, value) {
          this.store.set(key, String(value));
        },
      },
    },
  };
  sandbox.window.document = dom.document;
  vm.createContext(sandbox);
  vm.runInContext(APP, sandbox, { filename: "app.js" });
  return { dom, calls, picks, browses, brainOps, sandbox, fetchStub };
}

function byText(dom, selector, text) {
  return dom.body.querySelectorAll(selector).filter((node) => node.textContent.trim() === text)[0] || null;
}

function assistHost(dom) {
  return dom.document.getElementById("iv-assist");
}

/* Boot, land on the dashboard, open the interview. Returns once it has rendered. */
async function openInterview(app) {
  await settle();
  const open = byText(app.dom, "button", "Answer the questions");
  if (!open) throw new Error("the dashboard offered no way into the interview");
  open.dispatch("click");
  await settle();
  return app;
}

const QUESTION = '<img src=x onerror="alert(1)"> [click me](javascript:alert(2)) & <b>bold</b>';
const DRAFT = "We coach beginners in <script>alert(3)</script> Marrickville, six days a week.";

function askEnvelope(extra) {
  return Object.assign(
    {
      schema: "mos.assist.v1",
      command: "assist",
      ok: true,
      repo: fixture.state.root,
      changes: [],
      findings: [],
      next_action: { id: "answer-the-question", reason: "Answer, then send the turn back." },
      operation: "ask",
      field: "brand",
      runtime: "claude",
      done: false,
      question: "",
      draft: "",
      turn: 1,
      turns_used: 0,
    },
    extra
  );
}

function failure(code, message) {
  return askEnvelope({
    ok: false,
    findings: [{ code: code, message: message, severity: "error", path: "" }],
  });
}

/* ---- the sidebar: every brain, one press each ------------------------------ */

function sidebarPlan(extra) {
  const desk = fixture.state.places[0].path;
  const root = fixture.state.root;
  const brain = (p, name, more) => Object.assign({ path: p, name: name, mode: "in-house", legacy: false, attachable: false, exists: true, last_opened: null }, more || {});
  return Object.assign(
    {
      probe: fixture.probe,
      state: {
        brains: [
          brain(root, "Test Gym", { last_opened: "2026-08-28T00:00:00+00:00" }),
          brain(desk + "/second", "Second Co", { mode: "agency" }),
          brain(desk + "/gone", "Gone Co", { exists: false }),
          brain(desk + "/old", "Old Co", { legacy: true, attachable: true, mode: null }),
        ],
      },
    },
    extra || {}
  );
}

function sidebarRows(dom) {
  return dom.document.getElementById("brains").querySelectorAll("li").map((li) => {
    const open = li.querySelector(".brain__open");
    return {
      name: open.querySelector(".brain__name span").textContent,
      text: open.textContent.trim().replace(/\s+/g, " "),
      title: open.getAttribute("title"),
      current: open.getAttribute("aria-current"),
      disabled: open.getAttribute("aria-disabled"),
      tags: open.querySelectorAll(".pill").map((p) => p.textContent),
      forget: li.querySelectorAll(".brain__forget").map((b) => [b.textContent, b.getAttribute("aria-label")]),
    };
  });
}

const scenarios = {
  /* No runtime answered: the control must not exist in any form. */
  async absence() {
    const app = await openInterview(
      launch({ probe: { schema: "mos.assist.v1", ok: true, ready: false, runtimes: [], findings: [] } })
    );
    const host = assistHost(app.dom);
    return {
      hostChildren: host ? host.childNodes.length : -1,
      hostText: host ? host.textContent : "",
      buttons: app.dom.body.querySelectorAll("button").map((b) => b.textContent.trim()),
      answered: !!app.dom.document.getElementById("iv-answer"),
      calls: app.calls.map((c) => c.command),
    };
  },

  /* A runtime answered: the offer, its cost line, and the divider. */
  async offer() {
    const app = await openInterview(launch({ probe: fixture.probe }));
    const host = assistHost(app.dom);
    const go = host.querySelector(".assist__go");
    const cost = host.querySelector(".assist__cost");
    return {
      label: go ? go.textContent.trim() : "",
      describedBy: go ? go.getAttribute("aria-describedby") : "",
      costId: cost ? cost.getAttribute("id") : "",
      cost: cost ? cost.textContent : "",
      divider: host.querySelector(".assist-or") ? host.querySelector(".assist-or").textContent : "",
      calls: app.calls.map((c) => c.command),
      askedBeforeClick: app.calls.filter((c) => c.command === "assist ask").length,
    };
  },

  /* The blocker: nothing asks a model until a person presses the button. */
  async onlyOnClick() {
    const app = await openInterview(launch({ probe: fixture.probe, asks: [{ envelope: askEnvelope({ question: "What do you sell?" }) }] }));
    const before = app.calls.map((c) => c.command);
    await settle(30); // any timer or speculative call would land in here
    const afterWaiting = app.calls.map((c) => c.command);
    assistHost(app.dom).querySelector(".assist__go").dispatch("click");
    await settle();
    return {
      before: before,
      afterWaiting: afterWaiting,
      afterClick: app.calls.map((c) => c.command),
      asked: app.calls.filter((c) => c.command === "assist ask").length,
    };
  },

  /* The assistant's words are data. A tag in them is characters, not an element. */
  async hostileQuestion() {
    const app = await openInterview(
      launch({ probe: fixture.probe, asks: [{ envelope: askEnvelope({ question: QUESTION }) }] })
    );
    const go = assistHost(app.dom).querySelector(".assist__go");
    go.focus();
    go.dispatch("click");
    await settle();
    const node = assistHost(app.dom).querySelector(".assist__q");
    const elements = node ? node.querySelectorAll("*").map((n) => n.localName) : [];
    return {
      text: node ? node.textContent : "",
      elements: elements,
      // Everything under the question, so a smuggled tag anywhere is visible.
      allTags: app.dom.body.querySelectorAll("*").map((n) => n.localName).filter((n) => n === "img" || n === "script" || n === "b" || n === "a"),
      answerBox: !!app.dom.document.getElementById("iv-assist-answer"),
      // The pressed button is gone by now; focus must not have fallen to nothing.
      focused: app.dom.document.activeElement
        ? app.dom.document.activeElement.getAttribute("id") ||
          app.dom.document.activeElement.localName
        : null,
    };
  },

  /* A failed turn: one plain sentence, and every character the operator typed intact. */
  async failureKeepsTypedText() {
    const app = await openInterview(
      launch({ probe: fixture.probe, asks: [{ envelope: failure("assist-timeout", "claude did not answer within 180 seconds.") }] })
    );
    const area = app.dom.document.getElementById("iv-answer");
    area.value = "We are a boxing gym in Marrickville and we only take beginners.";
    area.dispatch("input");
    assistHost(app.dom).querySelector(".assist__go").dispatch("click");
    await settle();
    const note = assistHost(app.dom).querySelector(".note__body");
    return {
      typed: area.value,
      said: note ? note.textContent : "",
      question: !!assistHost(app.dom).querySelector(".assist__q"),
      retry: !!byText(app.dom, "button", "Try again"),
    };
  },

  /* The app itself falling over is the same promise: nothing typed is lost. */
  async transportFailureKeepsTypedText() {
    const app = await openInterview(launch({ probe: fixture.probe, asks: [{ transport: true }] }));
    const area = app.dom.document.getElementById("iv-answer");
    area.value = "Typed before the app fell over.";
    area.dispatch("input");
    assistHost(app.dom).querySelector(".assist__go").dispatch("click");
    await settle();
    const note = assistHost(app.dom).querySelector(".note__body");
    return { typed: area.value, said: note ? note.textContent : "" };
  },

  /* Four questions, then a draft, into an empty box. */
  async fullInterview() {
    const app = await openInterview(
      launch({
        probe: fixture.probe,
        asks: [
          { envelope: askEnvelope({ question: "What do you sell?" }) },
          { envelope: askEnvelope({ question: "Who buys it?" }) },
          { envelope: askEnvelope({ question: "What makes you different?" }) },
          { envelope: askEnvelope({ question: "What do you never do?" }) },
          { envelope: askEnvelope({ done: true, draft: DRAFT, question: "", turn: 5, turns_used: 4 }) },
        ],
      })
    );
    const host = () => assistHost(app.dom);
    host().querySelector(".assist__go").dispatch("click");
    await settle();
    const metas = [];
    for (let i = 0; i < 4; i += 1) {
      metas.push(host().querySelector(".assist__meta").textContent);
      const box = app.dom.document.getElementById("iv-assist-answer");
      box.value = "answer " + (i + 1);
      box.dispatch("input");
      byText(app.dom, "button", "Send this answer").dispatch("click");
      await settle();
    }
    const area = app.dom.document.getElementById("iv-answer");
    const review = byText(app.dom, "button", "Review this answer");
    const sent = app.calls.filter((c) => c.command === "assist ask").map((c) => JSON.parse(c.args["transcript-json"]).length);
    return {
      metas: metas,
      draftInBox: area.value,
      reviewBlocked: review ? review.getAttribute("aria-disabled") : "",
      transcriptLengths: sent,
      offerBack: !!host().querySelector(".assist__go"),
      elementsInBox: 0,
    };
  },

  /* A draft never lands on top of words the operator wrote. */
  async draftNeverOverwritesSilently() {
    const app = await openInterview(
      launch({ probe: fixture.probe, asks: [{ envelope: askEnvelope({ done: true, draft: DRAFT, turn: 1, turns_used: 0 }) }] })
    );
    const area = app.dom.document.getElementById("iv-answer");
    area.value = "My own words, which I would like to keep.";
    area.dispatch("input");
    assistHost(app.dom).querySelector(".assist__go").dispatch("click");
    await settle();
    const afterAsk = area.value;
    const shown = assistHost(app.dom).querySelector(".assist__draft");
    byText(app.dom, "button", "Keep what I wrote").dispatch("click");
    await settle();
    const afterKeep = area.value;
    return {
      afterAsk: afterAsk,
      shownDraft: shown ? shown.textContent : "",
      shownElements: shown ? shown.querySelectorAll("*").map((n) => n.localName) : [],
      afterKeep: afterKeep,
      offerBack: !!assistHost(app.dom).querySelector(".assist__go"),
    };
  },

  /* The setup wizard: step 1 chooses a place, step 3 names the folder inside it. */
  async wizardNamesTheFolderAfterTheBusiness() {
    const app = launch({ probe: fixture.probe });
    await settle();
    app.dom.document.getElementById("btn-new-brain").dispatch("click");
    await settle();
    const doc = app.dom.document;
    const placeProbe = app.calls.filter((c) => c.command === "status").slice(-1)[0];
    const chips = doc.getElementById("path-chips").querySelectorAll("button");
    const readout = doc.getElementById("where-readout").textContent;
    const name = doc.getElementById("in-name");
    name.value = "  Cascade  Strength & Co.! ";
    name.dispatch("input");
    await new Promise((resolve) => setTimeout(resolve, 400));
    await settle();
    const nameProbe = app.calls.filter((c) => c.command === "status").slice(-1)[0];
    const nameReadout = doc.getElementById("name-readout").textContent;
    // An exact path typed with the slug already on the end is not doubled.
    const field = doc.getElementById("in-path");
    field.value = fixture.state.places[0].path + "/cascade-strength-co";
    field.dispatch("input");
    await new Promise((resolve) => setTimeout(resolve, 400));
    await settle();
    name.dispatch("input");
    await new Promise((resolve) => setTimeout(resolve, 400));
    await settle();
    const typedProbe = app.calls.filter((c) => c.command === "status").slice(-1)[0];
    return {
      placeProbed: placeProbe ? placeProbe.args.path : "",
      chips: chips.map((b) => [b.textContent.trim(), b.getAttribute("title")]),
      readout: readout,
      pathProbed: nameProbe ? nameProbe.args.path : "",
      nameReadout: nameReadout,
      typedProbed: typedProbe ? typedProbe.args.path : "",
    };
  },

  /* Step 1's "Choose a folder..." asks the server for the OS folder window when one can
   * open, and the answer becomes the place. */
  async nativePickerChoosesThePlace() {
    const app = launch({
      probe: fixture.probe,
      state: { picker: true },
      pick: { path: "/home/you/Projects", cancelled: false, available: true, error: null, backend: "wsl" },
    });
    await settle();
    app.dom.document.getElementById("btn-new-brain").dispatch("click");
    await settle();
    const doc = app.dom.document;
    const panel = doc.getElementById("browse-panel");
    panel.setAttribute("hidden", "");
    const before = doc.getElementById("where-readout").textContent;
    doc.getElementById("btn-browse").dispatch("click");
    const waiting = doc.getElementById("where-readout").textContent;
    await settle();
    const probe = app.calls.filter((c) => c.command === "status").slice(-1)[0];
    return {
      before: before,
      waiting: waiting,
      posted: app.picks.map((p) => p.start),
      place: doc.getElementById("in-path").value,
      probed: probe ? probe.args.path : "",
      live: doc.getElementById("where-live").textContent,
      panelHidden: panel.hasAttribute("hidden"),
      browsed: app.browses.filter((b) => b.panelOpen).length,
      pressed: doc.getElementById("path-chips").querySelectorAll('button[aria-pressed="true"]').map((b) => b.getAttribute("title")),
    };
  },

  /* A closed window changes nothing: the place, the readout, the panel all stay put. */
  async nativePickerCancelledLeavesEverything() {
    const app = launch({ probe: fixture.probe, state: { picker: true } });
    await settle();
    app.dom.document.getElementById("btn-new-brain").dispatch("click");
    await settle();
    const doc = app.dom.document;
    doc.getElementById("browse-panel").setAttribute("hidden", "");
    const before = doc.getElementById("where-readout").textContent;
    const placeBefore = doc.getElementById("in-path").value;
    const liveBefore = doc.getElementById("where-live").textContent;
    doc.getElementById("btn-browse").dispatch("click");
    await settle();
    return {
      before: before,
      after: doc.getElementById("where-readout").textContent,
      placeBefore: placeBefore,
      placeAfter: doc.getElementById("in-path").value,
      liveBefore: liveBefore,
      liveAfter: doc.getElementById("where-live").textContent,
      panelHidden: doc.getElementById("browse-panel").hasAttribute("hidden"),
      posted: app.picks.length,
    };
  },

  /* No window can open here: the same button opens the in-page browser instead. */
  async noPickerOpensThePanel() {
    const app = launch({ probe: fixture.probe, state: { picker: false } });
    await settle();
    app.dom.document.getElementById("btn-new-brain").dispatch("click");
    await settle();
    const doc = app.dom.document;
    const panel = doc.getElementById("browse-panel");
    panel.setAttribute("hidden", "");
    doc.getElementById("btn-browse").dispatch("click");
    await settle();
    return {
      posted: app.picks.length,
      browsed: app.browses.filter((b) => b.panelOpen).map((b) => b.path),
      panelHidden: panel.hasAttribute("hidden"),
      expanded: doc.getElementById("btn-browse").getAttribute("aria-expanded"),
      panelText: panel.textContent,
    };
  },

  /* The server said a window could open, then it could not: the panel stands in, and
   * one sentence says why. */
  async pickerFailureFallsBackToThePanel() {
    const app = launch({
      probe: fixture.probe,
      state: { picker: true },
      pick: { path: null, cancelled: false, available: false, error: "No folder window can open here.", backend: "none" },
    });
    await settle();
    app.dom.document.getElementById("btn-new-brain").dispatch("click");
    await settle();
    const doc = app.dom.document;
    const panel = doc.getElementById("browse-panel");
    panel.setAttribute("hidden", "");
    doc.getElementById("btn-browse").dispatch("click");
    await settle();
    return {
      posted: app.picks.length,
      browsed: app.browses.filter((b) => b.panelOpen).length,
      panelHidden: panel.hasAttribute("hidden"),
      panelText: panel.textContent,
      readout: doc.getElementById("where-readout").textContent,
    };
  },

  /* Step 1's found-brains note is about the chosen folder and nothing else: it lists the
   * brains the look at that place reported, twins told apart by folder name, older
   * layouts tagged, no path in anything read aloud; and it goes when the place changes. */
  async foundBrainsFollowThePlace() {
    const desk = fixture.state.places[0].path;
    const home = fixture.state.places[1].path;
    const child = (name, brain, attachable) => ({
      name: name,
      path: desk + "/" + name,
      is_brain: !attachable,
      attachable: attachable,
      brain: { name: brain, mode: "in-house", legacy: attachable },
    });
    const app = launch({
      probe: fixture.probe,
      attachable: [desk + "/cascade-old"],
      browse: {
        [desk]: {
          path: desk,
          parent: home,
          is_brain: false,
          attachable: false,
          brain: null,
          error: null,
          children: [
            { name: "plain", path: desk + "/plain", is_brain: false, attachable: false, brain: null },
            child("cascade", "Cascade Strength Co.", false),
            child("cascade-old", "Cascade Strength Co.", true),
          ],
        },
      },
    });
    await settle();
    app.dom.document.getElementById("btn-new-brain").dispatch("click");
    await settle();
    const doc = app.dom.document;
    const host = doc.getElementById("where-found");
    const label = (b) => [b.textContent.trim(), b.getAttribute("title"), b.getAttribute("aria-label")];
    const seen = {
      asked: app.browses.filter((b) => !b.panelOpen).map((b) => b.path),
      lede: host.querySelector("p") ? host.querySelector("p").textContent : "",
      text: host.textContent,
      buttons: host.querySelectorAll("button").map(label),
      tags: host.querySelectorAll(".pill").map((p) => p.textContent.trim()),
    };
    // Point at the home folder instead: the look happens there, and it holds nothing.
    const chip = doc.getElementById("path-chips").querySelectorAll("button").filter((b) => b.getAttribute("title") === home)[0];
    chip.dispatch("click");
    await settle();
    seen.askedAfter = app.browses.filter((b) => !b.panelOpen).map((b) => b.path);
    seen.afterChildren = host.childNodes.length;
    seen.afterText = host.textContent;
    // Back to the desktop, then press the older brain's button: it opens all the same.
    doc.getElementById("path-chips").querySelectorAll("button").filter((b) => b.getAttribute("title") === desk)[0].dispatch("click");
    await settle();
    const older = host.querySelectorAll("button").filter((b) => b.textContent.indexOf("cascade-old") !== -1)[0];
    older.dispatch("click");
    await settle();
    seen.opened = app.sandbox.window.sessionStorage.getItem("mos.path");
    const attachPlan = app.calls.filter((c) => c.command === "attach").slice(-1)[0];
    seen.attachPlanned = attachPlan ? attachPlan.args : null;
    seen.attachShown = !doc.getElementById("attach").hasAttribute("hidden");
    seen.attachTitle = doc.getElementById("attach-title").textContent;
    return seen;
  },

  /* Every known brain is listed by name, the open one marked in words, the missing one
   * greyed with Forget, the older one tagged; no path anywhere a reader sees. */
  async sidebarListsBrains() {
    const app = launch(sidebarPlan());
    await settle();
    const doc = app.dom.document;
    const sidebar = doc.getElementById("sidebar");
    return {
      hidden: sidebar.hasAttribute("hidden"),
      rows: sidebarRows(app.dom),
      visible: doc.getElementById("brains").textContent,
      topbar: doc.getElementById("topbar-brain").textContent,
      // The stub DOM carries ids, not markup: the static labels are the HTML contract's.
      tabs: ["tab-dashboard", "tab-commands"].map((id) => doc.getElementById(id).getAttribute("aria-selected")),
      tabsShown: !doc.getElementById("tabs").hasAttribute("hidden"),
    };
  },

  /* One press switches: the heading, the bar, the dashboard's folder, the marker, the
   * stored path and the registry all follow, and focus stays on the pressed brain. */
  async switchingBrains() {
    const app = launch(sidebarPlan());
    await settle();
    const doc = app.dom.document;
    const before = doc.getElementById("dash-title").textContent;
    const second = sidebarRows(app.dom).filter((r) => r.name === "Second Co")[0];
    const button = doc.getElementById("brains").querySelectorAll("button").filter((b) => b.getAttribute("title") === second.title)[0];
    button.focus();
    button.dispatch("click");
    await settle();
    const rows = sidebarRows(app.dom);
    return {
      before: before,
      title: doc.getElementById("dash-title").textContent,
      topbar: doc.getElementById("topbar-brain").textContent,
      meta: doc.getElementById("dash-meta").textContent,
      stored: app.sandbox.window.sessionStorage.getItem("mos.path"),
      ops: app.brainOps,
      current: rows.filter((r) => r.current === "true").map((r) => r.name),
      live: doc.getElementById("live").textContent,
      dashboardShown: !doc.getElementById("dashboard").hasAttribute("hidden"),
      focused: doc.activeElement ? doc.activeElement.getAttribute("title") : null,
    };
  },

  /* A missing folder is not a button that goes somewhere; Forget drops it. */
  async missingBrainForget() {
    const app = launch(sidebarPlan());
    await settle();
    const doc = app.dom.document;
    const gone = sidebarRows(app.dom).filter((r) => r.name === "Gone Co")[0];
    const open = doc.getElementById("brains").querySelectorAll(".brain__open").filter((b) => b.getAttribute("title") === gone.title)[0];
    open.dispatch("click");
    await settle();
    const stillHere = doc.getElementById("dash-title").textContent;
    const forget = doc.getElementById("brains").querySelectorAll(".brain__forget")[0];
    forget.dispatch("click");
    await settle();
    return {
      row: gone,
      stillHere: stillHere,
      ops: app.brainOps,
      names: sidebarRows(app.dom).map((r) => r.name),
      live: doc.getElementById("live").textContent,
      focusedInList: !!(doc.activeElement && doc.activeElement.closest("#brains")),
    };
  },

  /* An older layout: the plan first, nothing written, then one press attaches and the
   * brain opens. The brain that was open stays open until then. */
  async attachableBrainFlow() {
    const app = launch(sidebarPlan());
    await settle();
    const doc = app.dom.document;
    const old = sidebarRows(app.dom).filter((r) => r.name === "Old Co")[0];
    const open = doc.getElementById("brains").querySelectorAll(".brain__open").filter((b) => b.getAttribute("title") === old.title)[0];
    open.dispatch("click");
    await settle();
    const seen = {
      row: old,
      attachShown: !doc.getElementById("attach").hasAttribute("hidden"),
      dashboardHidden: doc.getElementById("dashboard").hasAttribute("hidden"),
      title: doc.getElementById("attach-title").textContent,
      planCalls: app.calls.filter((c) => c.command === "attach").map((c) => c.args),
      storedBefore: app.sandbox.window.sessionStorage.getItem("mos.path"),
      changes: doc.getElementById("attach-body").querySelectorAll("li").length,
      buttons: doc.getElementById("attach-body").querySelectorAll(".btn-row button").map((b) => b.textContent.trim()),
    };
    byText(app.dom, "button", "Attach this brain").dispatch("click");
    await settle();
    seen.calls = app.calls.filter((c) => c.command === "attach").map((c) => c.args);
    seen.afterTitle = doc.getElementById("dash-title").textContent;
    seen.afterShown = !doc.getElementById("dashboard").hasAttribute("hidden");
    seen.storedAfter = app.sandbox.window.sessionStorage.getItem("mos.path");
    seen.ops = app.brainOps.map((o) => [o.op, o.path]);
    return seen;
  },

  /* "Not now" on the attach screen goes back to the brain that stayed open. */
  async attachNotNow() {
    const app = launch(sidebarPlan());
    await settle();
    const doc = app.dom.document;
    const old = sidebarRows(app.dom).filter((r) => r.name === "Old Co")[0];
    doc.getElementById("brains").querySelectorAll(".brain__open").filter((b) => b.getAttribute("title") === old.title)[0].dispatch("click");
    await settle();
    byText(app.dom, "button", "Not now").dispatch("click");
    await settle();
    return {
      dashboardShown: !doc.getElementById("dashboard").hasAttribute("hidden"),
      title: doc.getElementById("dash-title").textContent,
      calls: app.calls.filter((c) => c.command === "attach").map((c) => c.args),
    };
  },

  /* The Menu button owns the drawer: expanded state, focus in on open, focus back on
   * Escape. The DOM here has no layout, so this is the wiring, not the width. */
  async drawerWiring() {
    const app = launch(sidebarPlan());
    await settle();
    const doc = app.dom.document;
    const menu = doc.getElementById("btn-menu");
    const sidebar = doc.getElementById("sidebar");
    const before = { expanded: menu.getAttribute("aria-expanded"), open: /sidebar--open/.test(sidebar.className) };
    menu.focus();
    menu.dispatch("click");
    await settle();
    const opened = {
      expanded: menu.getAttribute("aria-expanded"),
      open: /sidebar--open/.test(sidebar.className),
      focused: doc.activeElement ? doc.activeElement.getAttribute("id") : null,
    };
    sidebar.dispatch("keydown", { key: "Escape" });
    await settle();
    const closed = {
      expanded: menu.getAttribute("aria-expanded"),
      open: /sidebar--open/.test(sidebar.className),
      focused: doc.activeElement ? doc.activeElement.getAttribute("id") : null,
    };
    // Choosing a section from the open drawer closes it too.
    menu.dispatch("click");
    await settle();
    doc.getElementById("tab-commands").dispatch("click");
    await settle();
    const afterTab = { expanded: menu.getAttribute("aria-expanded"), view: doc.getElementById("commands").hasAttribute("hidden") ? "hidden" : "commands" };
    return { before: before, opened: opened, closed: closed, afterTab: afterTab };
  },

  /* A typed place that is not a full path is named as such and never probed: a relative
   * spelling would land wherever the app was started. A Windows spelling is a full path. */
  async typedRelativePathIsNotProbed() {
    const app = launch({ probe: fixture.probe });
    await settle();
    app.dom.document.getElementById("btn-new-brain").dispatch("click");
    await settle();
    const doc = app.dom.document;
    const type = async (value) => {
      const field = doc.getElementById("in-path");
      field.value = value;
      field.dispatch("input");
      await new Promise((resolve) => setTimeout(resolve, 400));
      await settle();
    };
    const probed = () => app.calls.filter((c) => c.command === "status").map((c) => c.args.path);
    await type("brains/foo");
    const relative = {
      readout: doc.getElementById("where-readout").textContent,
      live: doc.getElementById("where-live").textContent,
      probed: probed(),
      browsed: app.browses.map((b) => b.path),
    };
    // Continue asks the probe again and gets the same answer: nothing is sent.
    doc.getElementById("btn-next").dispatch("click");
    await settle();
    relative.probedAfterContinue = probed();
    relative.readoutAfterContinue = doc.getElementById("where-readout").textContent;
    await type("C:\\Users\\you\\Desktop");
    const windows = { readout: doc.getElementById("where-readout").textContent, probed: probed() };
    return { relative: relative, windows: windows };
  },

  /* A listed folder that is still there but no longer holds a brain is greyed like a
   * missing one: tagged "not a brain", not a button that goes anywhere, with a Forget. */
  async notABrainRow() {
    const desk = fixture.state.places[0].path;
    const plan = sidebarPlan();
    plan.state.brains.push({ path: desk + "/hollow", name: "Hollow Co", mode: "in-house", legacy: false, attachable: false, is_brain: false, exists: true, last_opened: null });
    const app = launch(plan);
    await settle();
    const doc = app.dom.document;
    const row = sidebarRows(app.dom).filter((r) => r.name === "Hollow Co")[0];
    const open = doc.getElementById("brains").querySelectorAll(".brain__open").filter((b) => b.getAttribute("title") === row.title)[0];
    open.dispatch("click");
    await settle();
    return {
      row: row,
      stillHere: doc.getElementById("dash-title").textContent,
      stateCalls: app.brainOps.length,
      others: sidebarRows(app.dom).filter((r) => r.name !== "Hollow Co").map((r) => [r.name, r.disabled]),
    };
  },

  /* The list called it a brain; the server, asked, says the folder holds none now. The
   * switch is committed (the folder is real) and the wizard opens on it. */
  async switchToHollowBrain() {
    const desk = fixture.state.places[0].path;
    const app = launch(sidebarPlan({ hollow: [desk + "/second"] }));
    await settle();
    const doc = app.dom.document;
    const second = sidebarRows(app.dom).filter((r) => r.name === "Second Co")[0];
    doc.getElementById("brains").querySelectorAll(".brain__open").filter((b) => b.getAttribute("title") === second.title)[0].dispatch("click");
    await settle();
    return {
      stored: app.sandbox.window.sessionStorage.getItem("mos.path"),
      wizardShown: !doc.getElementById("wizard").hasAttribute("hidden"),
      dashboardShown: !doc.getElementById("dashboard").hasAttribute("hidden"),
      ops: app.brainOps.map((o) => [o.op, o.path]),
    };
  },

  /* The server refuses the folder outright (400: gone since the list was drawn). Nothing
   * moves: the open brain stays open, nothing is stored, the row flips to "not found". */
  async switchToVanishedBrain() {
    const desk = fixture.state.places[0].path;
    const app = launch(sidebarPlan({ missing: [desk + "/second"] }));
    await settle();
    const doc = app.dom.document;
    const second = sidebarRows(app.dom).filter((r) => r.name === "Second Co")[0];
    doc.getElementById("brains").querySelectorAll(".brain__open").filter((b) => b.getAttribute("title") === second.title)[0].dispatch("click");
    await settle();
    const after = sidebarRows(app.dom).filter((r) => r.name === "Second Co")[0];
    return {
      before: second,
      after: after,
      stored: app.sandbox.window.sessionStorage.getItem("mos.path"),
      title: doc.getElementById("dash-title").textContent,
      dashboardShown: !doc.getElementById("dashboard").hasAttribute("hidden"),
      toast: doc.getElementById("toast").textContent,
      live: doc.getElementById("live").textContent,
      ops: app.brainOps,
      current: sidebarRows(app.dom).filter((r) => r.current === "true").map((r) => r.name),
    };
  },

  /* "Attach a folder..." while a window is already up: one sentence, and neither a
   * second window nor the in-page list. The wizard's own button shares the same guard. */
  async attachFolderWhileWindowOpen() {
    const app = launch(sidebarPlan({
      state: Object.assign({ picker: true }, sidebarPlan().state),
      pick: { path: null, cancelled: false, available: true, busy: true, error: "A folder window is already open. Finish with that one.", backend: "wsl" },
    }));
    await settle();
    const doc = app.dom.document;
    doc.getElementById("btn-attach-folder").dispatch("click");
    await settle();
    const served = {
      posted: app.picks.length,
      live: doc.getElementById("live").textContent,
      attachShown: !doc.getElementById("attach").hasAttribute("hidden"),
      wizardShown: !doc.getElementById("wizard").hasAttribute("hidden"),
      panelHidden: doc.getElementById("browse-panel").hasAttribute("hidden"),
      dashboardShown: !doc.getElementById("dashboard").hasAttribute("hidden"),
    };
    // A second press while the first request is still out asks for nothing more.
    let release;
    app.sandbox.fetch = (url, init) => {
      if (url !== "/api/pick-folder") return app.fetchStub(url, init);
      app.picks.push(JSON.parse(init.body));
      return new Promise((resolve) => { release = resolve; });
    };
    doc.getElementById("btn-attach-folder").dispatch("click");
    await settle();
    doc.getElementById("btn-attach-folder").dispatch("click");
    await settle();
    served.pending = app.picks.length;
    served.pendingLive = doc.getElementById("live").textContent;
    release({ ok: true, status: 200, json: () => Promise.resolve({ path: null, cancelled: true, available: true, busy: false, error: null, backend: "wsl" }) });
    await settle();
    served.afterCancel = doc.getElementById("live").textContent;
    return served;
  },

  /* Rename from the header: the title gives way to the form, the plan comes back with
   * the apply bar, and the apply closes the form, says so, and re-reads the brain. */
  async renameFromHeader() {
    const app = launch({ probe: fixture.probe });
    await settle();
    const doc = app.dom.document;
    doc.getElementById("btn-rename").dispatch("click");
    await settle();
    const input = doc.getElementById("in-rename");
    const seen = {
      opened: !!input,
      prefilled: input ? input.value : "",
      focused: doc.activeElement === input,
      headerPrimary: doc.getElementById("dash-actions").querySelectorAll(".btn--primary").length,
      titleHidden: doc.getElementById("dash-title-row").hasAttribute("hidden"),
    };
    input.value = "Test Gym Two";
    input.dispatch("input");
    doc.getElementById("rename-form").querySelector(".btn--primary").dispatch("click");
    await settle();
    seen.planned = app.calls.filter((c) => c.command === "rename").map((c) => c.args);
    const apply = byText(app.dom, "button", "Rename to Test Gym Two");
    seen.applyShown = !!apply;
    seen.readoutLabel = doc.getElementById("rename-form").querySelector(".pill")
      ? doc.getElementById("rename-form").querySelector(".pill").textContent
      : "";
    const before = app.calls.length;
    apply.dispatch("click");
    await settle();
    seen.calls = app.calls.filter((c) => c.command === "rename").map((c) => c.args);
    seen.afterApply = app.calls.slice(before).map((c) => c.command);
    seen.toast = doc.getElementById("toast").textContent;
    seen.closed = doc.getElementById("rename-host").childNodes.length === 0;
    seen.titleShown = !doc.getElementById("dash-title-row").hasAttribute("hidden");
    seen.focusedAfter = doc.activeElement ? doc.activeElement.getAttribute("id") : null;
    seen.headerPrimaryAfter = doc.getElementById("dash-actions").querySelectorAll(".btn--primary").length;
    return seen;
  },

  /* ...but it does replace them when the operator says so. */
  async draftReplacesOnRequest() {
    const app = await openInterview(
      launch({ probe: fixture.probe, asks: [{ envelope: askEnvelope({ done: true, draft: DRAFT, turn: 1, turns_used: 0 }) }] })
    );
    const area = app.dom.document.getElementById("iv-answer");
    area.value = "Rough notes.";
    area.dispatch("input");
    assistHost(app.dom).querySelector(".assist__go").dispatch("click");
    await settle();
    byText(app.dom, "button", "Use the draft instead").dispatch("click");
    await settle();
    const review = byText(app.dom, "button", "Review this answer");
    return {
      box: area.value,
      reviewBlocked: review ? review.getAttribute("aria-disabled") : "",
      note: app.dom.document.getElementById("iv-block").textContent,
    };
  },
};

(async () => {
  const out = {};
  for (const name of Object.keys(scenarios)) {
    try {
      out[name] = await scenarios[name]();
    } catch (error) {
      out[name] = { error: String(error && error.stack ? error.stack : error) };
    }
  }
  process.stdout.write(JSON.stringify(out, null, 1));
})();
