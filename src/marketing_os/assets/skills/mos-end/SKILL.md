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
  save only after the operator approves. After saving, stay on the session
  branch so the work stays visible until the pull request is merged.
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

The default save is a pull request. The session's work goes on a session branch, the branch is
pushed, and a pull request is opened against the default branch. Merging it is the operator's
call, so nothing reaches the default branch until they finalise it.

**Stay on the session branch afterwards.** The working folder shows one branch at a time. Files
committed on the session branch are not on the default branch until the pull request merges, so
switching back before then removes them from disk and they vanish from the operator's editor or
Obsidian vault. Staying put keeps every file visible, and new work keeps landing in the same
open pull request, so one pull request holds everything until the operator merges it.

Find the default branch with `git symbolic-ref --short refs/remotes/origin/HEAD` (strip
`origin/`); do not assume `main`. Run `git fetch origin`, then check where the session stands
before proposing anything:

```bash
git branch --show-current
gh auth status                                  # first; a failure means "pull request not possible"
gh pr view --json number,state,url,headRefOid   # only when on a non-default branch
```

Only a "no pull requests found" message means the branch has no pull request. Any other `gh`
error (signed out, offline, wrong remote) goes to "When a pull request is not possible" below.

- **On the default branch:** start a new `session/YYYY-MM-DD-<slug>` branch from here.
- **On a branch whose pull request is open:** keep using it. The new commit joins that pull
  request, so there is no new branch and no new pull request.
- **On a branch whose pull request is merged:** compare `headRefOid` with `git rev-parse HEAD`.
  If they differ, the branch holds commits the merge never included, so stop and ask. If they
  match, the work has landed: `git switch <default-branch>`, `git pull --ff-only`, then start a
  new session branch. If the pull refuses, show the operator `git status` and stop; never reset.
- **On a branch whose pull request was closed without merging:** its files exist only on this
  branch, so switching away would hide them. Tell the operator, then offer to reopen it
  (`gh pr reopen`), open a new pull request from this branch, or abandon it. Switch only if they
  choose to abandon.
- **On a non-default branch with no pull request:** ask whether to open one from it or start a
  fresh session branch. A fresh branch starts from the current HEAD (`git switch -c ...`) so no
  committed file leaves the folder; branch from the default branch only if the operator confirms
  that work can be dropped.

If `git switch` refuses, list every blocking file (session files as well as editor settings,
which apps like Obsidian rewrite while open) and ask before discarding or stashing anything.
Closing the editor during the switch avoids most of these.

Preview the changed files, then propose, in one message: the commit message (business
language), the full file list, the branch, and whether this opens a new pull request or adds to
the open one (give its title or URL). After approval:

```bash
git switch -c session/YYYY-MM-DD-<slug>   # only when starting a new session branch
git add <the approved files>
git commit -m "<business-readable summary of the session>"
git push -u origin HEAD
gh pr create --fill --base <default-branch>   # only when no pull request is open for this branch
```

Right before `git push`, re-check `gh pr view --json state`: if the pull request merged or closed
since you looked, create a new session branch from HEAD and open a new pull request instead.

Report the pull request URL and say plainly that the operator is still on the session branch,
which is why their files stay visible. Once they merge on GitHub, the next `mos-start` or
`mos-end` switches to the default branch and pulls; by then the default branch has the files, so
nothing disappears.

Stage only the files you showed; leave unrelated untracked files alone rather than sweeping them
in with `git add -A`. Never use `git add -f`: it pulls in files the repository deliberately
ignores (caches, renders, local settings, secrets).

**When the operator says otherwise:**

- "commit only" (or "don't push"): commit on the current branch and stop. No branch, no push,
  no pull request.
- "push directly" (or "push to <branch>"): commit on the current branch and `git push` to it.
  No pull request.

**When a pull request is not possible:** if there is no `origin` remote, or `gh` is missing or
not signed in (`gh auth status` fails), commit on the session branch, say which prerequisite is
missing, and give the exact handoff command (`gh auth login`, then `git push -u origin HEAD`
and `gh pr create --fill`). Never create a remote or change the operator's accounts on their
behalf.

## Document contract

Every file you write under `business/`, `knowledge/`, `content/`, `campaigns/`, `reporting/`,
or `outputs/` opens with the frontmatter block defined in the repository's `CONTRACT.md`:
`title`, `type`, `description`, `date`, `status`, plus at least one of `sources`, `related`,
or `produced_by`. Deliverables must carry `sources:` — an output with no sources is not
finished. Emit the block as you write the file; never leave it for a later pass.
