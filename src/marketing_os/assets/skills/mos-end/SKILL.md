---
name: mos-end
description: Close a marketing-os session by recording the current focus, logging what changed, and opening a pull request the operator merges.
---

# End

Close the session from deterministic facts, capture durable memory, and offer a reviewed save.
There is no checkpoint command; git is the mechanism and this skill narrates it.

## How to run this skill (interaction contract)

Ending a session records memory and can commit to git, so keep it interactive:

- Propose the exact `CONTEXT.md` and log edits and wait for approval before writing them.
- Show the commit message, the full file list, the branch name, and the pull request title, and
  save only after the operator approves.
- By default the save lands as a pull request, never directly on the default branch: the
  operator finalises it by merging. Commit only, or push straight to the current branch, only
  when the operator explicitly asks for that.
- Never merge the pull request, force, or rewrite history, and never commit secrets or raw
  customer data.

## Inspect

Run:

```bash
mos status . --json
mos validate . --json
```

Use status for the current business state and validate for unresolved structural gaps. Report
what business truth or deliverables changed this session, and anything left incomplete.

## Record

Propose the exact edits before writing, then after approval:

- update `CONTEXT.md` with the current focus and any open loops to resume;
- append one dated session entry to `knowledge/wiki/_log.md` summarizing what changed and why.

Keep both edits short and business-readable. Never invent tomorrow's priority; `mos-start`
opens the next session.

## Refresh the map

Documents written this session are invisible to navigation until the map catches up. After
the records above are approved, run:

```bash
mos index build .
mos index sync . --plan --json
```

Review the planned index files, then apply with `mos index sync . --yes`. If
`mos validate . --json` reports `unlinked-document`, propose links with
`mos related . --plan --json` and apply the ones that read correctly. Generated `_index.md`
files carry a do-not-hand-edit marker; the generator leaves any hand-written index alone.

## Save

The default save is a pull request. The session's work goes on its own branch, the branch is
pushed, and a pull request is opened against the default branch. Merging it is the operator's
call, so nothing reaches the default branch until they finalise it.

Preview the changed files, then propose, in one message: the commit message (business
language), the full file list, the branch name (`session/YYYY-MM-DD-<slug>`), and the pull
request title. After approval:

```bash
git switch -c session/YYYY-MM-DD-<slug>   # skip if already on a non-default branch
git add <the approved files>
git commit -m "<business-readable summary of the session>"
git push -u origin HEAD
gh pr create --fill --base <default-branch>
```

Find the default branch with `git symbolic-ref --short refs/remotes/origin/HEAD` (strip
`origin/`); do not assume `main`. Report the pull request URL. After it opens, switch back to the
default branch so the next session starts from it; once the operator merges, `git pull` brings
the work in.

Stage only the files you showed; leave unrelated untracked files alone rather than sweeping them
in with `git add -A`.

**When the operator says otherwise:**

- "commit only" (or "don't push"): commit on the current branch and stop. No branch, no push,
  no pull request.
- "push directly" (or "push to <branch>"): commit on the current branch and `git push` to it.
  No pull request.

**When a pull request is not possible:** if there is no `origin` remote, or `gh` is missing or
not signed in (`gh auth status` fails), commit on the new branch, say which prerequisite is
missing, and give the exact handoff command (`gh auth login`, then `git push -u origin HEAD`
and `gh pr create --fill`). Never create a remote or change the operator's accounts on their
behalf.

## Document contract

Every file you write under `business/`, `knowledge/`, `content/`, `campaigns/`, `reporting/`,
or `outputs/` opens with the frontmatter block defined in the repository's `CONTRACT.md`:
`title`, `type`, `description`, `date`, `status`, plus at least one of `sources`, `related`,
or `produced_by`. Deliverables must carry `sources:` — an output with no sources is not
finished. Emit the block as you write the file; never leave it for a later pass.
