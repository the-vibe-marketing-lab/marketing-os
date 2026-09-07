from __future__ import annotations

import contextlib
import re
from collections.abc import Iterator
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any

from marketing_os.core.catalog import parse_frontmatter
from marketing_os.core.parallel import gather
from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import load_schema, read_config, repo_mode
from marketing_os.core.skills import bundled_skills, inspect_runtimes
from marketing_os.core.validation import validation_findings

if TYPE_CHECKING:  # pragma: no cover - import cycle broken for type checkers only
    from marketing_os.core.discover import Resolution

#: The fields a brain must answer before it can do work, in the order an operator meets them.
#: They live here because ``context_status`` is what measures them; ``core.context`` imports
#: this tuple rather than keeping a second copy, so the two can never drift apart.
REQUIRED_FIELDS = ("brand", "voice", "audience", "offer")

#: The offer field has no single canonical file — an offer lives in its own folder and a brain
#: may hold several — so this is the path discovery reports against once the glob below has
#: found no answer. It names the canonical shape; it is not a file we expect to exist.
OFFER_PROBE = "business/offers/offer.md"

#: How status names the offer path for an operator: a shape, not a file.
OFFER_DISPLAY = "business/offers/<offer-slug>/offer.md"


#: The markers a line can wear before its own words start: a bullet, a numbered item, a
#: block quote, a task checkbox, or any nesting of those.
LINE_MARKER = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+|>\s*|\[[ xX]\]\s*)")


def _content_line(raw: str) -> str:
    """One line with its list, quote and checkbox markers taken off the front.

    A stub written as ``- TODO: describe the tone`` is the same stub as ``TODO: describe the
    tone``; the hyphen is how a template lists its prompts, not something the operator wrote.
    Stripping the markers before the ``TODO:`` test is what stops a page of unanswered
    prompts counting as an answer.
    """
    line = raw.strip()
    while True:
        stripped = LINE_MARKER.sub("", line).strip()
        if stripped == line:
            return line
        line = stripped


def substantive_body(body: str) -> bool:
    """Whether a document body — its frontmatter already off — holds real content.

    The one implementation of the completeness rule. ``substantive_text`` is this function
    with the parse in front of it, for the callers that hold whole documents; a caller that
    has already parsed one passes the body straight in rather than parsing it a second time.
    """
    useful: list[str] = []
    for raw in body.splitlines():
        line = _content_line(raw)
        if not line or line.startswith("#") or line.lower().startswith("todo:"):
            continue
        useful.append(line)
    return len(" ".join(useful)) >= 30


def substantive_text(text: str) -> bool:
    """Whether a context document's text holds real content rather than scaffolding.

    The frontmatter contract block is metadata about the document, not the operator's
    answer, so it is stripped before judging. Counting it would report an untouched
    template stub as complete.

    Callers that hold a proposed document in memory (``mos context set --plan``) judge it
    with the same function that judges one on disk, so a preview can never disagree with
    the status that follows the write.
    """
    _meta, body = parse_frontmatter(text)
    return substantive_body(body)


def read_document(path: Path) -> str | None:
    """A document's text, or ``None`` when it cannot be read as text.

    A byte-order mark is consumed rather than kept: a leading ``\ufeff`` would push the
    frontmatter fence off the first line, and the whole contract block would then be counted
    as the operator's answer.
    """
    try:
        with path.open(encoding="utf-8-sig") as handle:
            return handle.read()
    except (OSError, ValueError):
        return None


def substantive(path: Path) -> bool:
    """Whether the context file at ``path`` holds real content rather than scaffolding.

    A file that cannot be read answers no rather than raising. One offer file saved as UTF-16
    used to take down ``mos status``, ``mos doctor`` and both ``mos context`` commands with a
    ``UnicodeDecodeError``, which is a great deal of collateral for a file nobody can read.
    """
    if not path.is_file():
        return False
    text = read_document(path)
    return text is not None and substantive_text(text)


def _offer_files(root: Path) -> list[Path]:
    base = root / "business" / "offers"
    if not base.is_dir():
        return []
    return sorted(
        path
        for path in base.glob("*/offer.md")
        if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", path.parent.name)
    )


def _entry(root: Path, relative: str, resolution: Resolution) -> dict[str, Any]:
    """One context field, answered from its canonical path or from wherever it really lives.

    ``path`` stays the canonical path in every case. It is where ``mos context set`` writes and
    what ``mos validate`` measures, and neither of those changes because the answer happens to
    be filed somewhere else today. ``complete`` is the question the dashboard actually asks —
    has this been answered at all — so a discovered file closes it, ``source`` says which of
    the two kinds of answer it is, and ``discovered_path`` names the file that gave it. A
    consumer that wants the older, narrower reading of ``complete`` asks ``source ==
    "canonical"``, which is exactly what ``complete`` used to mean.
    """
    entry: dict[str, Any] = {
        "path": relative,
        "complete": resolution.source != "missing",
        "source": resolution.source,
    }
    if resolution.source == "discovered":
        entry["discovered_path"] = resolution.path.relative_to(root).as_posix()
    if resolution.truncated:
        # A partial scan reports itself as partial. Without this a caller cannot tell a brain
        # with no answer from a tree the scan gave up on halfway through.
        entry["truncated"] = True
    return entry


def _offer_entry(
    root: Path, offers: list[Path], answered: bool, resolution: Resolution | None
) -> dict[str, Any]:
    """The offer field, which is a folder of offers rather than one file.

    The canonical glob is asked first, and when any offer holds a real answer that is the end
    of it: this is the one field where the schema's shape, not a single path, is the exact hit.
    Only a brain with no answered offer anywhere is searched, which is what finds an answer
    filed in a singular ``business/offer/`` that the plural canonical folder never sees.
    """
    entry: dict[str, Any] = {
        "path": OFFER_DISPLAY,
        "complete": answered,
        "files": [path.relative_to(root).as_posix() for path in offers],
        "source": "canonical",
    }
    if answered or resolution is None:
        return entry
    entry["complete"] = resolution.source != "missing"
    entry["source"] = resolution.source
    if resolution.source == "discovered":
        entry["discovered_path"] = resolution.path.relative_to(root).as_posix()
    elif resolution.source == "canonical":
        # The probe path itself holds the answer: an offer written straight into
        # ``business/offers/`` rather than into a slug folder below it. Naming it here is what
        # stops ``mos context set --field offer`` writing a second offer beside the one status
        # is already reading.
        entry["files"] = [resolution.path.relative_to(root).as_posix()]
    if resolution.truncated:
        entry["truncated"] = True
    return entry


def context_status(root: Path) -> dict[str, Any]:
    """Every context field, measured in one pass of the brain.

    Discovery is asked for all the unanswered fields together. It walks the same two folders
    whichever field is being asked about, so asking once per field walked the identical tree
    six times over — on a real brain on a mounted filesystem that was the entire cost of
    ``mos status``.
    """
    # Imported here rather than at module scope: discovery is built on this module's
    # completeness predicate, so a top-level import would close a cycle between the two files.
    from marketing_os.core.discover import resolve_fields

    schema = load_schema()
    offers = _offer_files(root)
    offer_answered = any(substantive(path) for path in offers)
    canonical = {name: root / relative for name, relative in schema["context_files"].items()}
    if not offer_answered:
        canonical["offer"] = root / OFFER_PROBE
    resolutions = resolve_fields(root, canonical)

    fields = {
        name: _entry(root, relative, resolutions[name])
        for name, relative in schema["context_files"].items()
    }
    fields["offer"] = _offer_entry(root, offers, offer_answered, resolutions.get("offer"))
    missing = [name for name in REQUIRED_FIELDS if not fields[name]["complete"]]
    return {
        "ready": not missing,
        "required": list(REQUIRED_FIELDS),
        "missing": missing,
        "fields": fields,
    }


#: The status envelopes already computed inside the innermost open :func:`reuse` block,
#: by resolved root. ``None`` — the default — means no block is open and nothing is kept.
#: A context variable rather than a module global because the local app answers requests
#: on a thread each, and one request's block must never be visible to another's.
_REUSED: ContextVar[dict[str, dict[str, Any]] | None] = ContextVar(
    "marketing_os_status_reuse", default=None
)


@contextlib.contextmanager
def reuse() -> Iterator[None]:
    """Answer ``status_repo`` for a given brain at most once inside this block.

    ``doctor_repo`` is ``status_repo`` plus one finding and three booleans — its first
    line is the whole status computation — so anything that wants both pays for the
    catalogue, the validation pass, the context scan and the runtime hashes twice. That is
    half of what the local app's state request used to cost.

    This is deliberately not a cache. It is opened by a caller who is about to ask two
    questions about one unchanged brain in one breath, it lives for those microseconds,
    and it is closed on the way out — so there is no interval in which an edit on disk
    could be answered from memory, and no invalidation to get wrong. A caller that does
    not open one, which is every terminal ``mos status`` and ``mos doctor``, computes
    exactly what it computed before.
    """
    token = _REUSED.set({})
    try:
        yield
    finally:
        _REUSED.reset(token)


def status_repo(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    shared = _REUSED.get()
    if shared is None:
        return _status_repo(root)
    answer = shared.get(str(root))
    if answer is None:
        answer = shared[str(root)] = _status_repo(root)
    return answer


def _status_repo(root: Path) -> dict[str, Any]:
    config = read_config(root)
    if config is None:
        return envelope(
            "status",
            root,
            ok=False,
            findings=[
                finding("not-marketing-os", "This is not a marketing-os business repository.")
            ],
            action=next_action("run-setup", "Create a new business brain with the setup skill."),
            repo_state="absent",
            business={},
            # Measured, not assumed. This branch is the one moment onboarding needs the
            # answer — the folder an operator has just pointed at, before it is a brain — and
            # a literal here made a folder full of their own writing indistinguishable from an
            # empty one, so both doors asked again for what was already written down. The
            # verdict on the folder does not move: it is still not a marketing-os repository.
            context=context_status(root),
            runtimes=inspect_runtimes(root),
            installed_skills=list(bundled_skills()),
            mode=None,
        )

    mode, _ = repo_mode(config)
    # Three independent questions about three different parts of the tree: what does
    # validation say, what has been answered, are the runtimes wired. Asked at the same
    # time because each is almost entirely spent waiting on the filesystem, and asking
    # them one after another made a status check as slow as the sum of its parts.
    findings, context, runtimes = gather(
        lambda: validation_findings(root),
        lambda: context_status(root),
        lambda: inspect_runtimes(root),
    )
    findings = _reconcile_discovered(findings, context)
    errors = [item for item in findings if item["severity"] == "error"]
    runtime_ready = all(item["ready"] for item in runtimes.values())

    if errors:
        state = "invalid"
        action = next_action(
            "repair-structure", "Repair structural errors before doing business work."
        )
    elif not runtime_ready:
        state = "needs-runtime-sync"
        action = next_action("sync-skills", "Synchronize the shared skills for both runtimes.")
    elif not context["ready"]:
        state = "needs-context"
        first = context["missing"][0]
        action = next_action(f"complete-{first}", f"Complete the {first} context first.")
    else:
        state = "ready"
        action = next_action(
            "follow-current-focus", "Use CONTEXT.md to continue the current priority."
        )

    return envelope(
        "status",
        root,
        ok=not errors,
        findings=findings,
        action=action,
        repo_state=state,
        schema_version=config.get("schema_version"),
        business={"name": config.get("business_name", "")},
        context=context,
        runtimes=runtimes,
        installed_skills=list(bundled_skills()),
        mode=mode,
    )


def _reconcile_discovered(
    findings: list[dict[str, str]], context: dict[str, Any]
) -> list[dict[str, str]]:
    """Let the context scan correct the structure check where the two disagree.

    Validation reads directories only, so a required context file that is not at its
    canonical path is a ``missing-file`` error to it — while the context scan, one line
    earlier, may have found the very answer that file is for, filed under a name of the
    owner's choosing. Status then said the field was complete, and doctor said the same
    field's file was missing and that this was an error. Both were reading the same brain.

    Here the finding is downgraded to a ``file-discovered`` warning naming the canonical
    path it still expects and, as ``discovered_path``, the file that answered instead: the
    information is kept, and the verdict is right. Only a field discovery actually resolved
    qualifies; a required file that is not a context field, or a field nothing answered,
    stays the error it was. The scan is the one ``status`` has already paid for — it is
    passed in, never re-run.
    """
    discovered = {
        entry["path"]: entry["discovered_path"]
        for entry in context["fields"].values()
        if entry["source"] == "discovered"
    }
    if not discovered:
        return findings
    reconciled: list[dict[str, str]] = []
    for item in findings:
        where = discovered.get(item["path"]) if item["code"] == "missing-file" else None
        if where is None:
            reconciled.append(item)
            continue
        reconciled.append(
            {
                **finding(
                    "file-discovered",
                    f"Required file is missing at its canonical path; its answer was "
                    f"discovered at {where}.",
                    severity="warning",
                    path=item["path"],
                ),
                "discovered_path": where,
            }
        )
    return reconciled


def doctor_repo(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    status = status_repo(root)
    if status.get("repo_state") == "absent":
        return _doctor_install(root, status)
    runtimes = status.get("runtimes", {})
    runtime_ready = bool(runtimes) and all(item.get("ready", False) for item in runtimes.values())
    structural_errors = [item for item in status["findings"] if item.get("severity") == "error"]
    findings = list(status["findings"])
    if not runtime_ready:
        findings.append(
            finding(
                "runtime-not-ready", "Claude Code and Codex skill discovery are not both ready."
            )
        )
    ok = not structural_errors and runtime_ready
    return envelope(
        "doctor",
        root,
        ok=ok,
        findings=findings,
        action=next_action(
            "run-start" if ok else "repair-health",
            "The repository is healthy; continue with the start skill."
            if ok
            else "Repair structure or synchronize skills, then run doctor again.",
        ),
        checks={
            "structure": not structural_errors,
            "runtime_wiring": runtime_ready,
            "context_ready": status.get("context", {}).get("ready", False),
        },
        runtimes=runtimes,
        mode=status.get("mode"),
    )


def _doctor_install(root: Path, status: dict[str, Any]) -> dict[str, Any]:
    """Doctor on a folder with no brain answers for the install instead.

    Right after ``mos install`` there is no brain yet, and the only thing to check is the
    home wiring: the nine bundled skills under ``~/.claude/skills`` and ``~/.agents/skills``.
    Reading the folder's own ``.claude/skills`` here told a correctly installed operator
    their install was broken, on the one command the setup guide sends them to.
    """
    runtimes = inspect_runtimes(Path.home())
    ready = all(item["ready"] for item in runtimes.values())
    findings = []
    if not ready:
        findings.append(
            finding(
                "runtime-not-ready", "Claude Code and Codex skill discovery are not both ready."
            )
        )
    return envelope(
        "doctor",
        root,
        ok=ready,
        findings=findings,
        action=next_action(
            "run-onboard" if ready else "run-install",
            "The engine is installed and no brain is here; open a new session in the brain "
            "folder and run the onboard skill."
            if ready
            else "Run `mos install --runtime all --yes`, then run doctor again.",
        ),
        checks={
            "structure": False,
            "runtime_wiring": ready,
            "context_ready": status.get("context", {}).get("ready", False),
        },
        runtimes=runtimes,
        repo_state="absent",
        mode=None,
    )
