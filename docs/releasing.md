# Releasing

marketing-os publishes to PyPI when a version tag is pushed. The tag is the only trigger, and
the version comes from `pyproject.toml` — there is no release script, no bump tool, and no
changelog generator to run.

Everything after the tag is automated by [`.github/workflows/release.yml`](../.github/workflows/release.yml).
This document covers the part that is not: the one-time setup on PyPI that only the account
owner can do, and the commands that cut a release once it is done.

One fact shapes the whole procedure. **A PyPI version can never be replaced or re-uploaded.**
Delete `0.2.0` and the number is still burned; the next fix has to be `0.2.1`. That is why the
workflow runs the full CI matrix and the wheel smoke against the exact artifacts it is about to
upload, and why the steps below are worth reading before running them.

## What the workflow does

Three jobs, in order, on a push of a tag matching `v*`:

| Job | What it does |
| --- | --- |
| `ci` | Calls [`ci.yml`](../.github/workflows/ci.yml) rather than copying it: lint, tests under coverage, the clean-language gate, build, and the wheel smoke, on Linux, macOS and Windows across Python 3.10 and 3.13. |
| `build` | Builds the sdist and the wheel once, checks the tag names the version that came out, runs `scripts/smoke_wheel.py` against those exact bytes, and uploads them as an artifact. |
| `publish` | Downloads that artifact and hands it to PyPI. It runs no project code, so the OIDC token is never live alongside anything from the repository. |

`scripts/smoke_wheel.py` is the gate that matters. It installs the built wheel into a throwaway
virtual environment and scaffolds a real brain from it, then asserts what a `pip install` alone
would never catch: the ten bundled skills, the business template's dotfiles, the three Obsidian
plugins, the mode overlays, the local app's static assets, and that no `{{TODAY}}` placeholder
survived rendering. A wheel that installs cleanly and then cannot scaffold a brain is worse than
no release, and this is what stands between the two.

## Authentication: trusted publishing, not an API token

The workflow authenticates with [trusted publishing](https://docs.pypi.org/trusted-publishers/).
GitHub mints a short-lived OIDC token for the `publish` job, and PyPI exchanges it for an upload
token that expires in minutes. No API token is stored in the repository, none is held in a
password manager, and none is ever pasted by a person.

PyPI decides whether to trust that token by matching four facts from the workflow run against
what you register: the repository owner, the repository name, the workflow's **filename**, and
the GitHub environment the job declares. A mismatch in any one of them is the single most common
reason a first trusted publish fails, and the error PyPI returns does not say which field is
wrong. Get them right the first time.

## 1. Register the pending publisher on PyPI

`marketing-os` does not exist on PyPI yet, so use the **pending publisher** flow. A pending
publisher creates the project on first successful upload; you do not need to hand-upload a
release first to "prime" the name.

Confirm the name is still free before you start:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://pypi.org/pypi/marketing-os/json   # 404 = free
```

Then, signed in to PyPI, go to your **account** sidebar (not a project's — the project does not
exist yet) and click **Publishing**, or go straight to
<https://pypi.org/manage/account/publishing/>. Under **GitHub**, fill the form with exactly
these values:

| Field | Value | Why this exact value |
| --- | --- | --- |
| Project Name | `marketing-os` | The `name` in `pyproject.toml`. PyPI normalises `-` and `_`, so `marketing_os` resolves to the same project. |
| Owner | `the-vibe-marketing-lab` | The GitHub organisation that owns the repo since 2026-09-05 (it was the `reapzyau` user before). PyPI binds the publisher to owner + repo, so this row had to change when the repo moved. |
| Repository name | `marketing-os` | The repository's **current** name. `marketing-os-next` is an old name that GitHub 301-redirects; the OIDC claim carries `the-vibe-marketing-lab/marketing-os`, and entering the old name will fail. |
| Workflow name | `release.yml` | A bare filename. PyPI rejects anything containing `/`, so `.github/workflows/release.yml` is invalid, and this is the filename — not the `name: release` line inside it. |
| Environment name | `pypi` | Must match `environment: name: pypi` in the `publish` job. PyPI treats this field as optional, but the workflow declares an environment — leave it blank here and the claim will not match. |

Click **Add**. The pending publisher appears at the top of the page and converts itself into a
normal project-scoped publisher the moment the first upload succeeds.

A pending publisher does not reserve the name. If someone else registers `marketing-os` before
you publish, yours is invalidated — see [If the name gets taken](#if-the-name-gets-taken).

## 2. Create the GitHub environment

In the repository, go to **Settings → Environments → New environment** and name it `pypi`. The
name is case-insensitive on both sides but must otherwise match step 1 exactly.

Add yourself under **Required reviewers** while you are there. Every tag push then pauses at the
`publish` job until you click Approve, which puts one deliberate confirmation in front of an
action that cannot be undone. Skip it if you would rather tags publish unattended; the workflow
works either way.

## 3. Cut the release

The release builds the tag's commit, not your working tree, so anything still uncommitted is
not in it. Merge the branch you are on into `main` first, and confirm the tree is clean.

```bash
# The local remote still uses the old repository name. Point it at the canonical one.
git remote set-url origin https://github.com/the-vibe-marketing-lab/marketing-os.git

git status --short          # must be empty before you go on
git switch main
git pull --ff-only
```

Confirm the version that is about to be published, and that the name is still free:

```bash
grep '^version' pyproject.toml                                                     # version = "0.3.0"
curl -s -o /dev/null -w '%{http_code}\n' https://pypi.org/pypi/marketing-os/json   # still 404
```

Move the `## [Unreleased]` heading in `CHANGELOG.md` to `## [0.3.0] - YYYY-MM-DD` and commit
that. The `Changelog` URL in `pyproject.toml` points at that file on `main`, so it is what
anyone arriving from the PyPI sidebar reads.

Then tag and push:

```bash
git tag -a v0.3.0 -m "marketing-os 0.3.0"
git push origin main
git push origin v0.3.0
```

The tag must be `v` followed by the exact version in `pyproject.toml`. If they disagree, the
`build` job fails and says so before anything reaches PyPI — the version is read from
`pyproject.toml`, never from the tag, so without that check a `v0.3.1` tag would quietly
publish `0.3.0` and burn the wrong number.

## 4. Verify it worked

Watch the run, approving the `publish` job if you set a required reviewer:

```bash
gh run watch --repo the-vibe-marketing-lab/marketing-os
```

Then confirm PyPI has both files at the right version:

```bash
curl -s https://pypi.org/pypi/marketing-os/json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['info']['version'], *[u['filename'] for u in d['urls']], sep='\n')"
```

The green run is not the proof. Install it the way a stranger would, from a machine with no
source checkout on any path, and make it build a brain:

```bash
pipx install marketing-os
mos --version                                              # mos 0.3.0
mos onboard /tmp/release-check --name "Release Check" --mode in-house --yes
mos doctor /tmp/release-check --json
ls -a /tmp/release-check /tmp/release-check/.obsidian    # dotfiles and vault config present
```

If `mos --version` works but `mos onboard` cannot scaffold, the payload did not make it into the
wheel. That is unrecoverable for the published version: fix the packaging, bump to the next patch
version, and tag again.

Finally, check that the PyPI project page shows the sidebar links from `[project.urls]` and that
the release carries its attestations — `gh-action-pypi-publish` generates PEP 740 attestations by
default under trusted publishing, and they appear on the file listing at
<https://pypi.org/project/marketing-os/#files>.

## If the name gets taken

Both `marketing-os` and `marketing_os` are free today, and a pending publisher does not hold
either of them. Only a successful upload does. The shortest way to remove this risk is to cut the
first release soon rather than leaving the publisher pending for months.

If the name goes before you publish, PyPI invalidates the pending publisher and the release run
fails at the `publish` job. Recovering takes four edits and no code changes:

1. Pick a new distribution name and check it is free with the `curl` command above.
2. Change `name` in `pyproject.toml`. Leave the package directory, the import name
   `marketing_os`, and the `mos` console script alone — the distribution name is only what
   `pipx install` resolves, and none of the three has to match it.
3. On PyPI, delete the invalidated pending publisher and add a new one with the new project
   name. The other four fields do not change.
4. Update `environment.url` and the two `dist/marketing_os-…` filenames in the `build` job's
   tag check in `release.yml`, the step 1 table above, and the `pipx install` lines in
   [`README.md`](../README.md) and [`setup-guide.md`](setup-guide.md).

## What breaks a working publisher

Renaming the repository, renaming or moving `release.yml`, or renaming the `pypi` environment
each break the match, and each fails at upload with a permission error rather than at any earlier
point. Update the publisher on PyPI in the same change, not afterwards. Renaming the GitHub
account is the exception: PyPI stores the owner's numeric ID, so that keeps working.

To rehearse without spending a version number on PyPI, register a second pending publisher on
<https://test.pypi.org> and add `repository-url: https://test.pypi.org/legacy/` to the publish
step on a scratch branch. It is rarely worth it — the wheel smoke already proves the artifact,
and a TestPyPI upload burns the version number there too.
