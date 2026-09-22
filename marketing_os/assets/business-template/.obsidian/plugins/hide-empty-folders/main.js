'use strict';
const { Plugin, TFolder, TFile } = require('obsidian');

// Same hide rules as .obsidian/snippets/hide-machinery.css — keep in sync.
const HIDDEN_NAMES = new Set(['README.md', 'CLAUDE.md', 'AGENTS.md', 'scripts', 'runs', 'node_modules']);
const HIDDEN_ROOT = new Set(['CONTEXT.md', 'CONTRACT.md']);

function isHiddenNode(f) {
  if (f.name.startsWith('_')) return true;
  if (HIDDEN_NAMES.has(f.name)) return true;
  if (f.name.endsWith('.code-workspace')) return true;
  if (!f.path.includes('/') && HIDDEN_ROOT.has(f.name)) return true;
  return false;
}

class HideEmptyFolders extends Plugin {
  async onload() {
    this.schedule = this.debounce(() => this.apply(), 150);
    this.app.workspace.onLayoutReady(() => {
      this.apply();
      this.registerEvent(this.app.vault.on('create', this.schedule));
      this.registerEvent(this.app.vault.on('delete', this.schedule));
      this.registerEvent(this.app.vault.on('rename', this.schedule));
      // explorer re-renders children on expand; re-tag then
      this.registerDomEvent(document, 'click', (e) => {
        if (e.target.closest && e.target.closest('.nav-folder-title')) this.schedule();
      });
    });
  }
  onunload() {
    document.querySelectorAll('.hef-empty').forEach(el => el.classList.remove('hef-empty'));
  }
  debounce(fn, ms) { let t; return () => { clearTimeout(t); t = setTimeout(fn, ms); }; }

  // true if folder has at least one visible file anywhere beneath it
  hasVisible(folder, memo) {
    if (memo.has(folder.path)) return memo.get(folder.path);
    let v = false;
    for (const c of folder.children) {
      if (isHiddenNode(c)) continue;
      if (c instanceof TFile) { v = true; break; }
      if (c instanceof TFolder && this.hasVisible(c, memo)) { v = true; break; }
    }
    memo.set(folder.path, v);
    return v;
  }

  apply() {
    const memo = new Map();
    const empties = new Set();
    const walk = (folder) => {
      for (const c of folder.children) {
        if (!(c instanceof TFolder)) continue;
        if (!this.hasVisible(c, memo)) empties.add(c.path);
        walk(c);
      }
    };
    walk(this.app.vault.getRoot());
    for (const leaf of this.app.workspace.getLeavesOfType('file-explorer')) {
      const items = leaf.view.fileItems || {};
      for (const [path, item] of Object.entries(items)) {
        if (!item.el) continue;
        item.el.classList.toggle('hef-empty', empties.has(path));
      }
    }
  }
}
module.exports = HideEmptyFolders;
