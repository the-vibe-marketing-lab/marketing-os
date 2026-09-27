# Troubleshooting

Start with deterministic facts:

```bash
mos status . --json
mos doctor . --json
```

`mos status` reports a `repo_state` and a `next_action`; work through the state you are in.

Both commands read `.mos/config.yaml` at exactly the path you give them, and neither walks
up the tree, so run them from the repository root or pass the root explicitly:
`mos status /path/to/brain --json`. `mos validate` reads the path the same way. Only
`mos statusline`, `mos ingest`, `mos think`, `mos context`, and `mos assist` — and the local
app's server — search upward for a root. Run `mos status` one folder in and it reports
`absent`, which is a wrong answer about the right repository.

`mos doctor` gives a verdict over structure and runtime wiring only. It reports context
readiness beside them under `checks.context_ready`, but that check does not feed the
verdict, so doctor returns ok on a brain with no context filled in at all. When you are
chasing a context problem, `mos status`'s `repo_state` is the gate, not doctor's `ok`.

## By repo state

### absent

`config` could not be read, so the folder is not a marketing-os business repository. This is
also what you see outside a repository, when `.mos/config.yaml` is missing, and when it is
present but does not parse as JSON. Run the onboard skill (or `mos onboard`) to scaffold a
new brain, or point the command at the right folder.

If the folder already holds a brain the engine does not recognise — a `.mos/config.yaml`
written as YAML, or a `BRAIN.md` beside a `business/` tree — use `mos attach . --plan` and
then `--yes` instead. Onboard is not the tool for that job: it refuses any non-empty folder
it does not already recognise as a brain, with an `unsupported-directory` finding and a
`choose-empty-destination` next action. A non-empty folder that is neither closes both
doors — attach returns `not-a-brain` — so scaffold into a new empty folder and route the
old material in with `mos migrate`.

One wrinkle to read past. The envelope's `next_action` for this state is still `run-setup`,
and its reason names a setup skill that was retired when `setup` merged into `mos onboard`.
Read it as `mos onboard`.

### invalid

Structure has one or more error-severity findings and must be repaired before business work.
Read the findings and fix each path (see common findings below), then re-run `mos validate`.

`mos onboard` and `mos attach` never overwrite an existing file — the scaffold skips any
destination that already exists — so it is safe to re-run either to recreate anything
genuinely missing. Attach has one deliberate exception: it rewrites `.mos/config.yaml` into
canonical JSON, keeping the previous text as `.mos/config.legacy.yaml` when the two differ.

A freshly attached brain is the common way to land here. Attach refuses to write a
`business/` or `knowledge/` document, so every required one you did not already have comes
back as a `missing-content-file` warning from attach and a `missing-file` error from status.
Run `mos onboard <path> --name "<name>" --mode <mode> --plan`, then `--yes`, to scaffold
exactly those; the folder is a recognised brain by then, so onboard no longer refuses it,
and your own documents are left untouched.

### needs-runtime-sync

Structure is sound but the Claude Code and Codex skill copies are missing or out of date.
Preview and apply a sync:

```bash
mos skills sync . --runtime all --plan --json
mos skills sync . --runtime all --yes --json
```

This state only ever covers the project-local copies under `<repo>/.claude/skills` and
`<repo>/.agents/skills`, hashed against the packaged source. The globally installed copies
in `~/.claude/skills` and `~/.agents/skills`, recorded in
`~/.marketing-os/runtime-manifest.json`, belong to no `repo_state` at all. Refresh those
after an engine update with `mos install --runtime all --plan` then `--yes`, or run
`/mos-update`.

### needs-context

The repository is wired but the required context is incomplete. `mos status` lists the
missing fields under `context.missing` and points `next_action` at the first one. The
required fields are brand, voice, audience, and offer. Strategy and proof are reported and
settable the same way, but neither blocks readiness.

A field is complete when a document that answers it carries real content, and "real
content" is measured rather than judged. The frontmatter contract block is stripped first,
so an untouched template stub never reads as complete; then blank lines, markdown headings,
and lines starting `TODO:` are discarded; what remains must join to at least thirty
characters. HTML comments are not stripped and do count toward that total.

#### The file that counts is not always the file named

Two things to know before you go and fill in the path that status printed.

**The offer path is a shape, not a file.** `mos status` reports `offer` as
`business/offers/<offer-slug>/offer.md`. No file by that name is expected to exist. The
field's `files` key lists the offers that counted canonically — `business/offers/*/offer.md`
where the folder name is a lowercase, hyphen-separated slug — and any other folder name is
left out of `files`.

**Left out of `files` is not the same as ignored.** When no canonical answer is found,
status looks for one. It searches `business/` and `reference/` for a markdown document whose
own name is one of the words the field is known by, and that passes the same completeness
test. That is what closes a field filed somewhere the schema never named:
`business/positioning/brand.md` completes brand, `business/audience/persona.md` completes
audience, and an offer under a folder whose name is not a valid slug completes offer even
though `files` stays empty. A field answered that way reports `"source": "discovered"` and a
`discovered_path`; `path` stays the canonical file throughout.

Being named for the field is necessary, not sufficient — the evidence has to be strong
enough to win. A document whose name is only a loose synonym, sitting in a folder that says
nothing about the field (`business/pricing.md`, `business/style.md`), does not clear the
bar and the field stays missing. Nor does the folder alone ever answer: a `README.md`
describing what belongs in `business/proof/`, or the `_index.md` that `mos index sync`
writes there, is navigation and is refused outright. Read `source` rather than inferring it
from the filename.

The consequence is worth understanding before you write anything. A field can report
complete while the file that status names is still a stub. `mos context show` reads the
answer from wherever it really is, so you see the words and `answered_in` names their file,
but `writes_to` stays the canonical path — writing there produces a second copy of the same
business truth in a different file. If you want the canonical file to hold the answer, move
the discovered document rather than retyping it.

A document that exists to record an absence — a testimonials file whose content is "none
collected yet, here is the plan" — is a real document by every mechanical test there is, and
will report the field answered. Nothing model-free can tell it from an answer. Give it
`status: gap` in its frontmatter and discovery will take it at its word and leave the field
missing.

One more overlap to know about: `reference/` is one of the two trees discovery searches, but
it is not an allowed top-level path, so a brain that keeps answers there resolves them
correctly and collects an `unknown-top-level` warning for the folder at the same time.

#### Closing the gaps

```bash
mos context show .
mos context set . --field <name> --text "<answer>" --plan
mos context set . --field <name> --text "<answer>" --yes
```

`context show` turns every field into a question with its hint and backing file.
`context set --plan` prints a real unified diff of the change; `--yes` writes it atomically,
so a failed write leaves the original byte for byte. The same text test judges both, so a
preview never over- or under-reads the file it is about to write.

It can still disagree with `mos status`, and this section is where you will meet that.
`context set` reports `field_complete` for the canonical file it is writing, while `mos status`
reports a field complete when discovery finds the answer anywhere. On a brain whose brand is
answered at `business/positioning/brand.md`, a short `context set --field brand --plan`
returns `field_complete: false` and an `answer-too-short` warning saying status will still
report the field missing — while status reports it complete, and the same envelope's own
`missing` list does not contain brand. Trust `mos status` for whether a field is answered;
trust `field_complete` for whether the text you just supplied is substantial.

For `--field offer` there are three cases, all with no `--slug`: a brain with no canonical
offer gets `business/offers/core-offer/offer.md`; a brain with exactly one gets that offer's
own file; a brain with more than one is refused with a `choose-offer` action until `--slug`
names which one.

To be interviewed rather than write cold, `mos assist status` reports whether an installed
runtime can conduct the interview, and `mos assist ask . --field <name>` runs one stateless
turn and writes nothing.

### ready

Structure, runtime wiring, and context all pass. Follow `CONTEXT.md` to continue the current
priority.

## Local app

`mos ui` reports its own failures as findings on the `ui` envelope.

- `ui-port-unavailable` — nothing free to bind. With no `--port` the walk covers 4321 to
  4370; retry with `mos ui --port <n>`.
- `ui-already-running` — a warning, not a failure: the existing server was reused. Check it
  with `mos ui status`, and `mos ui stop` if you wanted a fresh one.
- `ui-start-failed` — the port was bound but the server never came up on it. Run `mos ui`
  again, and read `~/.marketing-os/ui.log` if it repeats.
- `ui-foreground` — this platform has no `os.fork`, so there was nothing to detach to. The
  app runs in the window you started it in until you close it.
- `ui-needs-foreground` — the same platform limit, reported by the one-time open that
  follows a first `mos install --yes`. That path refuses to occupy your terminal, so start
  the app yourself with `mos ui`.
- `browser-not-opened` — the server is running but no browser could be launched. Open the
  printed URL yourself.
- `stale-ui-state` — the recorded server was gone and `~/.marketing-os/ui.json` was cleared.
  Nothing is wrong; run `mos ui` again.
- `ui-not-running` — `mos ui stop` found nothing to stop.
- `ui-stop-failed` / `ui-stop-timeout` — the recorded pid could not be signalled, or still
  held the port ten seconds after SIGTERM. End the process by hand, then retry.

## Skills sync scenarios

- **Missing** — a runtime skill has never been generated. It appears under a runtime's
  `missing` list; a plan shows a `create` action. Apply with `--yes`.
- **Stale** — a generated copy no longer matches the packaged source hash. It appears under
  `mismatched`; the plan shows a `replace` action, valid only when the previous install was
  recorded in the manifest.
- **Unrecognized** — a skill directory the tooling did not generate. Sync never overwrites
  it; the plan returns a `skill-conflict` finding instead. Review the directory, then remove
  or relocate it yourself and run the sync again.

## Common validation findings

- `missing-or-invalid-config` — `.mos/config.yaml` is absent or does not parse as JSON.
  Run `mos attach . --plan` then `--yes`: it is the only command that rewrites the marker in
  place, keeping the old text as `.mos/config.legacy.yaml`. Onboard is not the remedy. With
  the config unreadable the folder is not a recognised brain, so onboard sees a non-empty
  destination it does not know and refuses it with `unsupported-directory` and a
  `choose-empty-destination` action pointing at a different, empty folder. See the `absent`
  section above, which covers the same folder shape.
- `unsupported-schema` — the config's `schema` or `schema_version` does not match the
  packaged schema. Confirm you are on a compatible marketing-os version.
- `missing-directory` / `missing-file` — a required path from `schema.json` is absent. Re-run
  onboard to recreate scaffolded files without touching existing ones.
- `file-discovered` — a warning, not an error: a required context file is absent from its
  canonical path, but `status` found the answer in another document, named as
  `discovered_path`. Nothing needs repairing to work; `mos validate` still reports the
  canonical path as `missing-file` because it measures structure alone.
- `unknown-top-level` — a warning, not an error: a top-level path sits outside the canonical
  architecture. Move the work under an allowed tree (`business/`, `knowledge/`, `content/`,
  `campaigns/`, `reporting/`, `outputs/`, or `archive/`) or remove it. `mos migrate . --plan`
  lists the same entries as `off-schema-entry` findings with a `build-migrate-plan` next
  action; `/mos-migrate` has an agent write the `mos.migrate-plan.v1` routing plan, and
  `mos migrate . --plan-file <plan> --yes` applies the moves as a set — nothing is written if
  any move is invalid, and an existing path is never overwritten. Note the check only
  inspects direct children of the repository root and skips dot-entries, so an off-schema
  folder nested inside an allowed tree is never reported.
- `invalid-year` / `invalid-month` / `invalid-dated-artifact` — a folder under an execution
  tree breaks the `YYYY/MM-Mon/YYYY-MM-DD-slug` grammar. Month folders must read `09-Sep`
  (number and English three-letter name agreeing, exact case) unless the brain sets
  `"month_folder": "MM"`; the message names the expected folder. A bare `09` left from before
  0.5.0 is renamed, with every link to it, by `mos fix invalid-month --plan` then `--yes`.
  Anything else (`09-Sept`, `9`) is renamed by hand.
- `month-folder-exists` — `mos fix invalid-month` found `09-Sep` already beside `09` in the
  same year and refused to merge them. Move the contents into one folder by hand, then run
  it again.
- `invalid-month-folder` — an error: `.mos/config.yaml` has a `month_folder` value other than
  `MM` or `MM-Mon`. Fix the value (or remove the key for the `MM-Mon` default). Until then month folder
  names are not judged.
- `invalid-quarter` / `invalid-report-month` — a folder under `reporting/` breaks the
  `YYYY/QN/YYYY-MM` grammar. Rename it to match.

### Mode findings

- `missing-mode` — a warning: the config has no `mode`, so the repository is read as
  in-house. Add `"mode"` to `.mos/config.yaml`.
- `invalid-mode` — an error. The mode must be `in-house`, `agency`, or `client`. Validation
  fails closed here and stops judging structure against a mode it does not understand.
- `missing-client-registry` — an error in agency mode: `business/clients/clients.md` is the
  registry, and agency mode requires it. Restore it.
- `set-mode-agency` — a warning: no mode is set but a client registry exists. That is almost
  certainly an agency HQ; add `"mode": "agency"` rather than leaving it to the default.
- `unexpected-clients-folder` — a warning: a `business/clients/` folder in a mode that
  should not hold one.

### Contract findings

`missing-frontmatter`, `missing-connective-key`, `output-without-sources`,
`unlinked-document`, `invalid-type`, and `invalid-status` are the frontmatter-contract
sensors. All six are warnings by default, so an early-stage brain is never blocked, and
`mos validate . --strict` promotes exactly those six to errors — which is what continuous
integration should run. `mos related . --yes` proposes the links that close
`unlinked-document`, and `mos index sync . --yes` regenerates the navigation layer.

Only error-severity findings block a repository; warnings are reported but leave `ok` true.
