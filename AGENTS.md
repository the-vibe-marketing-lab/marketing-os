# Agent Contract

This is the marketing-os engine repository, not a business repository.

- Keep the CLI deterministic and model-free. `core/assist.py` is the single documented
  exception and stays that way: no other module may invoke a model or a runtime.
- The local app under `src/marketing_os/ui/` is a client of the CLI, never a second
  implementation: every action builds a real argv and goes through
  `marketing_os.cli.main.run_argv`, the same parser and handlers the terminal runs. It also
  stays dependency-free and build-free — stdlib `http.server`, vanilla JavaScript files under
  `ui/static/`, no framework, no bundler, no CDN, no web fonts, and no inline `<script>`,
  because the Content-Security-Policy the server sets is `script-src 'self'`.
- Treat `src/marketing_os/assets/skills/` as the only skill source, and register every new
  skill in `assets/skills/manifest.json`. `bundled_skills()` reads that manifest rather than
  listing the directory, so an unregistered skill is never installed, counted, or reported —
  the install path stays silent about it, and only the wheel smoke's ten-skill count notices.
- Never add tracked runtime copies under `.claude/skills/` or `.agents/skills/`.
- Do not copy files from predecessor implementations; implement from this repository's contracts.
- Run `ruff check .`, `pytest`, `python scripts/check_clean_language.py`, `python -m build`,
  and `python scripts/smoke_wheel.py` before handoff — the smoke reads the wheel `build` just
  produced, so without it a clean checkout crashes on an empty `dist/` and a stale tree
  silently validates yesterday's wheel. CI runs those same five, with `pytest` under
  `--cov=marketing_os --cov-report=term-missing`, so skipping one locally only moves the
  failure.
- Keep credentials, customer data, provider exports, and machine-local state out of git.
- Start from [the documentation index](docs/README.md) for architecture, contracts, and references.
