"use strict";
/* A DOM small enough to read and real enough to run the shipped app.js.
 *
 * The static contract test can prove app.js contains no markup sink. It cannot prove
 * what a hostile question actually renders as, or that a failed assist leaves a typed
 * answer alone. That needs the real code executing against real nodes, so this is the
 * smallest document that app.js will run against: text nodes that are text, attributes
 * that are attributes, and no HTML parser anywhere — which is the point, because a
 * shim that parsed markup could hide the very bug being tested for.
 */

function makeDocument(ids) {
  let activeElement = null;
  const registry = new Map();

  class TextNode {
    constructor(data) {
      this.nodeType = 3;
      this.data = String(data);
      this.parentNode = null;
      this.childNodes = [];
    }
    get textContent() {
      return this.data;
    }
  }

  function parseSimple(part) {
    const spec = { tag: "", id: "", classes: [], attrs: [] };
    const attrRe = /\[([A-Za-z_:][-A-Za-z0-9_:.]*)(?:=("([^"]*)"|'([^']*)'|[^\]]*))?\]/g;
    let rest = part.replace(attrRe, (m, name, raw, dq, sq) => {
      const value = dq !== undefined ? dq : sq !== undefined ? sq : raw;
      spec.attrs.push([name, value === undefined ? null : value]);
      return "";
    });
    const pieces = rest.split(/(?=[.#])/);
    pieces.forEach((piece) => {
      if (!piece) return;
      if (piece[0] === "#") spec.id = piece.slice(1);
      else if (piece[0] === ".") spec.classes.push(piece.slice(1));
      else spec.tag = piece.toLowerCase();
    });
    return spec;
  }

  function matches(node, spec) {
    if (node.nodeType !== 1) return false;
    if (spec.tag && node.localName !== spec.tag) return false;
    if (spec.id && node.getAttribute("id") !== spec.id) return false;
    const classes = (node.getAttribute("class") || "").split(/\s+/);
    for (const name of spec.classes) if (classes.indexOf(name) === -1) return false;
    for (const [name, value] of spec.attrs) {
      if (!node.hasAttribute(name)) return false;
      if (value !== null && node.getAttribute(name) !== value) return false;
    }
    return true;
  }

  function descendants(node, out) {
    node.childNodes.forEach((kid) => {
      if (kid.nodeType === 1) {
        out.push(kid);
        descendants(kid, out);
      }
    });
    return out;
  }

  function query(root, selector) {
    const parts = String(selector).trim().split(/\s+/).map(parseSimple);
    let pool = descendants(root, []);
    parts.forEach((spec, index) => {
      const hits = pool.filter((node) => matches(node, spec));
      pool = index === parts.length - 1 ? hits : hits.reduce((all, n) => all.concat(descendants(n, [])), []);
    });
    return pool;
  }

  class Element {
    constructor(tag, ns) {
      this.nodeType = 1;
      this.localName = String(tag).toLowerCase();
      this.tagName = this.localName.toUpperCase();
      this.namespaceURI = ns || null;
      this.attrs = new Map();
      this.childNodes = [];
      this.parentNode = null;
      this.listeners = new Map();
      this.style = {};
      this.value = "";
      this.tabIndex = 0;
    }
    get className() {
      return this.attrs.get("class") || "";
    }
    set className(value) {
      this.setAttribute("class", value);
    }
    get firstChild() {
      return this.childNodes[0] || null;
    }
    get hidden() {
      return this.attrs.has("hidden");
    }
    get children() {
      return this.childNodes.filter((kid) => kid.nodeType === 1);
    }
    get textContent() {
      return this.childNodes.map((kid) => kid.textContent).join("");
    }
    set textContent(value) {
      this.childNodes.forEach((kid) => (kid.parentNode = null));
      this.childNodes = [];
      if (value !== "" && value !== null && value !== undefined) {
        this.appendChild(new TextNode(value));
      }
    }
    appendChild(node) {
      if (node.parentNode) node.parentNode.removeChild(node);
      node.parentNode = this;
      this.childNodes.push(node);
      return node;
    }
    insertBefore(node, ref) {
      if (node.parentNode) node.parentNode.removeChild(node);
      const index = ref ? this.childNodes.indexOf(ref) : -1;
      node.parentNode = this;
      if (index === -1) this.childNodes.push(node);
      else this.childNodes.splice(index, 0, node);
      return node;
    }
    removeChild(node) {
      const index = this.childNodes.indexOf(node);
      if (index !== -1) {
        this.childNodes.splice(index, 1);
        node.parentNode = null;
      }
      return node;
    }
    setAttribute(name, value) {
      this.attrs.set(name, String(value));
      if (name === "id") registry.set(String(value), this);
    }
    getAttribute(name) {
      return this.attrs.has(name) ? this.attrs.get(name) : null;
    }
    removeAttribute(name) {
      this.attrs.delete(name);
    }
    hasAttribute(name) {
      return this.attrs.has(name);
    }
    addEventListener(type, fn) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(fn);
    }
    removeEventListener(type, fn) {
      const list = this.listeners.get(type) || [];
      const index = list.indexOf(fn);
      if (index !== -1) list.splice(index, 1);
    }
    dispatch(type, event) {
      const payload = Object.assign({ type: type, target: this, preventDefault() {} }, event || {});
      (this.listeners.get(type) || []).slice().forEach((fn) => fn(payload));
    }
    focus() {
      activeElement = this;
    }
    blur() {
      if (activeElement === this) activeElement = null;
    }
    select() {}
    closest(selector) {
      const spec = parseSimple(String(selector).trim());
      let node = this;
      while (node) {
        if (matches(node, spec)) return node;
        node = node.parentNode;
      }
      return null;
    }
    querySelector(selector) {
      return query(this, selector)[0] || null;
    }
    querySelectorAll(selector) {
      return query(this, selector);
    }
  }

  const body = new Element("body");
  const document = {
    // Document-level listeners (the drawer's Escape) register and are never fired here.
    addEventListener: () => {},
    createElement: (tag) => new Element(tag),
    createElementNS: (ns, tag) => new Element(tag, ns),
    createTextNode: (data) => new TextNode(data),
    getElementById: (id) => registry.get(id) || null,
    querySelector: (selector) => body.querySelector(selector),
    querySelectorAll: (selector) => body.querySelectorAll(selector),
    get activeElement() {
      return activeElement;
    },
    body: body,
    execCommand: () => true,
  };

  // Every id index.html ships, so $() finds the same nodes the real page has.
  ids.forEach((id) => {
    const node = new Element("div");
    node.setAttribute("id", id);
    body.appendChild(node);
  });

  return { document, body, Element, TextNode, query, registry };
}

module.exports = { makeDocument };
