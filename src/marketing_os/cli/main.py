from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from marketing_os import __version__
from marketing_os.core.assist import ask_turn, runtime_status
from marketing_os.core.attach import attach_repo
from marketing_os.core.catalog import build_repo as index_build_repo
from marketing_os.core.context import STDIN_SENTINEL, set_context, show_context
from marketing_os.core.index import status_repo as index_status_repo
from marketing_os.core.index import sync_repo as index_sync_repo
from marketing_os.core.ingest import ingest_repo, pending_sources
from marketing_os.core.migrate import migrate_repo
from marketing_os.core.onboard import onboard_repo
from marketing_os.core.query import query_repo
from marketing_os.core.related import related_repo
from marketing_os.core.rename import rename_repo
from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.skills import (
    apply_sync,
    global_manifest,
    plan_sync,
    project_manifest,
)
from marketing_os.core.status import doctor_repo, status_repo
from marketing_os.core.statusline import statusline_repo
from marketing_os.core.think import think_repo
from marketing_os.core.update import update_engine
from marketing_os.core.validation import validate_repo

RUNTIMES = ("claude", "codex", "all")
MODES = ("in-house", "agency", "client")
UI_OPERATIONS = ("stop", "status")


class _ParseError(ValueError):
    """A usage error raised instead of exiting, for in-process callers."""


class _QuietParser(argparse.ArgumentParser):
    """An argument parser that reports usage errors instead of writing and exiting.

    The terminal wants argparse's own exit-and-print behaviour; the local app server
    wants an envelope. Same parser definition, two exit policies.
    """

    def error(self, message: str) -> Any:
        raise _ParseError(message)

    def exit(self, status: int = 0, message: str | None = None) -> Any:
        raise _ParseError((message or "").strip() or "invalid arguments")


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _mutation_mode(args: argparse.Namespace) -> bool:
    if bool(args.plan) == bool(args.yes):
        raise ValueError("choose exactly one of --plan or --yes")
    return bool(args.yes)


def _add_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", dest="json_out", help="Emit JSON only.")


def _add_mutation(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    group = parser.add_mutually_exclusive_group(required=required)
    group.add_argument("--plan", action="store_true", help="Preview changes without writing.")
    group.add_argument("--yes", action="store_true", help="Apply the reviewed changes.")


def build_parser(
    parser_class: type[argparse.ArgumentParser] = argparse.ArgumentParser,
) -> argparse.ArgumentParser:
    parser = parser_class(
        prog="mos", description="Manage a file-based marketing brain."
    )
    parser.add_argument("--version", action="version", version=f"mos {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    install = commands.add_parser("install", help="Install the three bootstrap skills globally.")
    install.add_argument("--runtime", choices=RUNTIMES, default="all")
    install.add_argument(
        "--no-ui",
        action="store_true",
        dest="no_ui",
        help="Do not open the local app after a first install.",
    )
    _add_mutation(install)
    _add_output(install)

    status = commands.add_parser(
        "status", help="Inspect structure, context, and runtime readiness."
    )
    status.add_argument("path", nargs="?", default=".")
    _add_output(status)

    validate = commands.add_parser("validate", help="Validate the canonical schema and routing.")
    validate.add_argument("path", nargs="?", default=".")
    validate.add_argument(
        "--strict",
        action="store_true",
        help="Promote frontmatter-contract warnings to errors.",
    )
    _add_output(validate)

    doctor = commands.add_parser("doctor", help="Check structure and both runtime adapters.")
    doctor.add_argument("path", nargs="?", default=".")
    _add_output(doctor)

    skills = commands.add_parser("skills", help="Manage generated runtime skill copies.")
    skill_commands = skills.add_subparsers(dest="skills_command", required=True)
    sync = skill_commands.add_parser("sync", help="Plan or synchronize project-local skills.")
    sync.add_argument("path", nargs="?", default=".")
    sync.add_argument("--runtime", choices=RUNTIMES, default="all")
    _add_mutation(sync)
    _add_output(sync)

    ingest = commands.add_parser("ingest", help="Capture raw material into knowledge/sources.")
    ingest.add_argument(
        "source",
        nargs="?",
        default=None,
        help="File, directory, URL, or text; requires --plan or --yes.",
    )
    ingest.add_argument("path", nargs="?", default=".")
    ingest.add_argument("--topic", default=None, help="Metadata-only topic label for the capture.")
    ingest.add_argument("--slug", default=None, help="Override the derived slug.")
    ingest.add_argument("--date", default=None, help="Capture date as YYYY-MM-DD (defaults today).")
    ingest.add_argument(
        "--pending",
        action="store_true",
        help="List captured sources not yet compiled "
        "(read-only; omit SOURCE and --plan/--yes; optional positional is the repo path).",
    )
    _add_mutation(ingest, required=False)
    _add_output(ingest)

    index = commands.add_parser("index", help="Manage the navigation layer.")
    index_commands = index.add_subparsers(dest="index_command", required=True)
    index_build = index_commands.add_parser(
        "build", help="Catalogue every document into machine-local state."
    )
    index_build.add_argument("path", nargs="?", default=".")
    _add_output(index_build)
    index_sync = index_commands.add_parser(
        "sync", help="Regenerate the _index.md navigation hierarchy."
    )
    index_sync.add_argument("path", nargs="?", default=".")
    _add_mutation(index_sync)
    _add_output(index_sync)
    index_status = index_commands.add_parser(
        "status", help="Report catalogue freshness and navigation coverage."
    )
    index_status.add_argument("path", nargs="?", default=".")
    _add_output(index_status)

    rename = commands.add_parser("rename", help="Rename the business a brain belongs to.")
    rename.add_argument("path", nargs="?", default=".")
    rename.add_argument("--name", required=True, help="The new business name.")
    _add_mutation(rename)
    _add_output(rename)

    related = commands.add_parser(
        "related", help="Propose ## Related blocks for documents that link to nothing."
    )
    related.add_argument("path", nargs="?", default=".")
    related.add_argument("--limit", type=int, default=None, help="Cap the documents touched.")
    _add_mutation(related)
    _add_output(related)

    query = commands.add_parser("query", help="Plan deterministic retrieval for a question.")
    query.add_argument("question", help="The question to answer from the brain.")
    query.add_argument("path", nargs="?", default=".")
    query.add_argument("--limit", type=int, default=5, help="Maximum candidate documents.")
    query.add_argument(
        "--grep",
        action="store_true",
        help="Literal substring lookup instead of term scoring.",
    )
    _add_output(query)

    think = commands.add_parser("think", help="Emit a grounded thinking handoff for a topic.")
    think.add_argument("topic", help="The topic to reason about.")
    think.add_argument("path", nargs="?", default=".")
    _add_output(think)

    context = commands.add_parser(
        "context", help="Ask the business questions in place, and record the answers."
    )
    context_commands = context.add_subparsers(dest="context_command", required=True)
    context_show = context_commands.add_parser(
        "show", help="Report every context field, its question, and the answer on file."
    )
    context_show.add_argument("path", nargs="?", default=".")
    _add_output(context_show)
    context_set = context_commands.add_parser(
        "set", help="Write one answer into the file that backs a context field."
    )
    context_set.add_argument("path", nargs="?", default=".")
    context_set.add_argument(
        "--field", required=True, help="Which context field the answer belongs to."
    )
    context_set.add_argument(
        "--text",
        required=True,
        help="The answer in the operator's own words; '-' reads it from stdin.",
    )
    context_set.add_argument(
        "--slug", default=None, help="Which offer to write; only used by --field offer."
    )
    _add_mutation(context_set)
    _add_output(context_set)

    assist = commands.add_parser(
        "assist",
        help="Ask an agent runtime you already have to interview you for one field.",
    )
    assist_commands = assist.add_subparsers(dest="assist_command", required=True)
    assist_status = assist_commands.add_parser(
        "status", help="Report which agent runtimes on this machine can actually answer."
    )
    _add_output(assist_status)
    assist_ask = assist_commands.add_parser(
        "ask", help="Run one stateless interview turn: the next question, or the draft."
    )
    assist_ask.add_argument("path", nargs="?", default=".")
    assist_ask.add_argument(
        "--field", required=True, help="Which context field the interview is filling."
    )
    assist_ask.add_argument(
        "--transcript-json",
        dest="transcript_json",
        default="[]",
        help='The conversation so far as JSON: [{"question": "...", "answer": "..."}].',
    )
    _add_output(assist_ask)

    onboard = commands.add_parser(
        "onboard", help="Create or complete a business brain: scaffold, git, and the interview."
    )
    onboard.add_argument("path", nargs="?", default=".")
    onboard.add_argument("--name", required=True, help="Business display name.")
    onboard.add_argument(
        "--mode",
        choices=MODES,
        default=None,
        help="Repository mode: in-house, agency, or client. Required.",
    )
    onboard.add_argument(
        "--agency",
        default=None,
        help="Agency business name; required for --mode client, ignored otherwise.",
    )
    onboard.add_argument(
        "--hq",
        default=None,
        help="Path to the agency HQ repo; in client mode appends a registry row there.",
    )
    onboard.add_argument("--runtime", choices=RUNTIMES, default="all")
    _add_mutation(onboard)
    _add_output(onboard)

    attach = commands.add_parser(
        "attach",
        help="Adopt an existing brain-shaped folder as a marketing-os brain without "
        "rewriting its content.",
    )
    attach.add_argument("path", nargs="?", default=".")
    attach.add_argument(
        "--name",
        default=None,
        help="Business display name; defaults to the legacy config, then the folder name.",
    )
    attach.add_argument(
        "--mode",
        choices=MODES,
        default=None,
        help="Repository mode; defaults to the legacy config, then in-house.",
    )
    attach.add_argument("--runtime", choices=RUNTIMES, default="all")
    _add_mutation(attach)
    _add_output(attach)

    migrate = commands.add_parser(
        "migrate", help="Diagnose off-schema files or apply a deterministic routing plan."
    )
    migrate.add_argument("path", nargs="?", default=".")
    migrate.add_argument(
        "--plan-file",
        default=None,
        help="A mos.migrate-plan.v1 routing plan to preview or apply.",
    )
    _add_mutation(migrate)
    _add_output(migrate)

    update = commands.add_parser("update", help="Update the marketing-os engine itself.")
    _add_mutation(update)
    _add_output(update)

    statusline = commands.add_parser("statusline", help="Print a one-line ambient status badge.")
    statusline.add_argument("path", nargs="?", default=".")
    _add_output(statusline)

    ui = commands.add_parser(
        "ui", help="Open the local app in a browser, or stop and inspect it."
    )
    ui.add_argument(
        "target",
        nargs="?",
        default=".",
        help="'stop', 'status', or the folder to open (default: the current folder).",
    )
    ui.add_argument("--port", type=int, default=None, help="Bind this port instead of 4321.")
    ui.add_argument(
        "--no-open",
        action="store_true",
        dest="no_open",
        help="Start the server without opening a browser.",
    )
    _add_output(ui)
    return parser


def _sync_result(root: Path, runtime: str, *, apply: bool, global_install: bool) -> dict[str, Any]:
    if global_install:
        manifest = global_manifest(root)
        target = root
        command = "install"
    else:
        manifest = project_manifest(root)
        target = root
        command = "skills-sync"
    actions, findings = plan_sync(target, runtime, manifest_path=manifest)
    if apply and not findings:
        apply_sync(actions, manifest)
    changes = [
        f"{item['action']} {Path(item['destination']).relative_to(target).as_posix()}"
        for item in actions
    ]
    if findings:
        action = next_action("resolve-skill-conflict", "Review the conflicting skill directories.")
    elif actions and not apply:
        action = next_action("apply-skill-sync", "Apply the reviewed skill synchronization plan.")
    else:
        action = next_action("run-start", "The shared skills are ready.")
    return envelope(
        command,
        root,
        ok=not findings,
        changes=changes,
        findings=findings,
        action=action,
        applied=apply and not findings,
        planned=not apply,
        runtime=runtime,
    )


def _dispatch_ingest(args: argparse.Namespace) -> dict[str, Any]:
    """The ingest branch: its own function so ``dispatch`` stays under the ceiling."""
    if args.pending:
        if args.plan or args.yes:
            raise ValueError("--pending is read-only; do not combine it with --plan or --yes")
        # --pending takes only an optional [path]; argparse fills `source` first,
        # so a lone positional is the path. Two positionals is ambiguous.
        if args.path != ".":
            raise ValueError("--pending takes only an optional PATH argument")
        where = args.source if args.source is not None else args.path
        return pending_sources(_path(where))
    if args.source is None:
        raise ValueError("ingest requires a SOURCE (or --pending to list captures)")
    return ingest_repo(
        _path(args.path),
        args.source,
        topic=args.topic,
        slug=args.slug,
        date=args.date,
        apply=_mutation_mode(args),
    )


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "install":
        applied = _mutation_mode(args)
        result = _sync_result(Path.home(), args.runtime, apply=applied, global_install=True)
        if applied and result["ok"] and not getattr(args, "no_ui", False):
            result["ui"] = _open_on_first_install()
        return result
    if args.command == "status":
        return status_repo(_path(args.path))
    if args.command == "validate":
        return validate_repo(_path(args.path), strict=bool(args.strict))
    if args.command == "doctor":
        return doctor_repo(_path(args.path))
    if args.command == "skills" and args.skills_command == "sync":
        return _sync_result(
            _path(args.path), args.runtime, apply=_mutation_mode(args), global_install=False
        )
    if args.command == "ingest":
        return _dispatch_ingest(args)
    if args.command == "index":
        if args.index_command == "build":
            return index_build_repo(_path(args.path))
        if args.index_command == "sync":
            return index_sync_repo(_path(args.path), apply=_mutation_mode(args))
        if args.index_command == "status":
            return index_status_repo(_path(args.path))
    if args.command == "rename":
        return rename_repo(_path(args.path), args.name, apply=_mutation_mode(args))
    if args.command == "related":
        return related_repo(
            _path(args.path), apply=_mutation_mode(args), limit=args.limit
        )
    if args.command == "query":
        return query_repo(
            _path(args.path), args.question, limit=args.limit, literal=bool(args.grep)
        )
    if args.command == "think":
        return think_repo(_path(args.path), args.topic)
    if args.command == "context":
        if args.context_command == "show":
            return show_context(_path(args.path))
        if args.context_command == "set":
            if args.text == STDIN_SENTINEL:
                raise ValueError(
                    "--text - reads the answer from stdin and only works in the terminal; "
                    "send the answer text itself"
                )
            return set_context(
                _path(args.path),
                args.field,
                args.text,
                slug=args.slug,
                apply=_mutation_mode(args),
            )
    if args.command == "assist":
        if args.assist_command == "status":
            return runtime_status(Path.cwd())
        if args.assist_command == "ask":
            return ask_turn(_path(args.path), args.field, args.transcript_json)
    if args.command == "onboard":
        return onboard_repo(
            _path(args.path),
            args.name,
            args.runtime,
            mode=args.mode,
            agency=args.agency,
            hq=_path(args.hq) if args.hq else None,
            apply=_mutation_mode(args),
        )
    if args.command == "attach":
        return attach_repo(
            _path(args.path),
            name=args.name,
            mode=args.mode,
            runtime=args.runtime,
            apply=_mutation_mode(args),
        )
    if args.command == "migrate":
        return migrate_repo(
            _path(args.path), plan_file=args.plan_file, apply=_mutation_mode(args)
        )
    if args.command == "update":
        return update_engine(apply=_mutation_mode(args))
    if args.command == "statusline":
        return statusline_repo(_path(args.path))
    if args.command == "ui":
        return _dispatch_ui(args)
    raise ValueError("unsupported command")


def _open_on_first_install() -> dict[str, Any]:
    """Open the app on a first install. Installing must never fail over a browser."""
    try:
        from marketing_os.ui.lifecycle import first_install_open

        return first_install_open(Path.cwd())
    except Exception as exc:  # the local app is a convenience, never a dependency
        return {"opened": False, "reason": f"unavailable: {type(exc).__name__}"}


def _dispatch_ui(args: argparse.Namespace) -> dict[str, Any]:
    from marketing_os.ui.lifecycle import start_ui, status_ui, stop_ui

    target = args.target
    if target == "stop":
        return stop_ui()
    if target == "status":
        return status_ui()
    return start_ui(
        _path(target), port=args.port, open_browser=not args.no_open
    )


def _error_result(command: str, message: str) -> dict[str, Any]:
    return envelope(
        command or "error",
        Path.cwd(),
        ok=False,
        findings=[finding("command-error", message)],
        action=next_action("review-command", "Review the command and try again."),
    )


def _dispatch_result(args: argparse.Namespace) -> dict[str, Any]:
    try:
        return dispatch(args)
    except (OSError, ValueError) as exc:
        return _error_result(getattr(args, "command", "") or "error", str(exc))


def run_argv(argv: Sequence[str]) -> dict[str, Any]:
    """Parse and dispatch an argv list in-process, returning the envelope.

    This is the seam the local app server uses. It is the same parser and the same
    handlers the terminal runs, so the browser can never drift into a second
    implementation; nothing is written to stdout or stderr.
    """
    parser = build_parser(_QuietParser)
    try:
        args = parser.parse_args(list(argv))
    except _ParseError as exc:
        return _error_result(argv[0] if argv else "error", str(exc))
    return _dispatch_result(args)


def _render_human(result: dict[str, Any]) -> str:
    state = "OK" if result["ok"] else "NEEDS ATTENTION"
    lines = [f"{state}: {result['command']}", f"Repository: {result['repo']}"]
    if result.get("mode"):
        lines.append(f"Mode: {result['mode']}")
    if result.get("url"):
        lines.append(f"URL: {result['url']}")
    if result["changes"]:
        lines.append("Changes:")
        lines.extend(f"  - {change}" for change in result["changes"])
    if result["findings"]:
        lines.append("Findings:")
        lines.extend(
            f"  - [{item['severity']}] {item['message']}"
            + (f" ({item['path']})" if item.get("path") else "")
            for item in result["findings"]
        )
    if result.get("diff"):
        lines.append("Diff:")
        lines.extend(f"  {line}" for line in str(result["diff"]).splitlines())
    if result["command"] == "assist":
        # The assistant's turn is the whole point of the command, so a terminal user sees
        # it rather than only the next action. Both are plain text and are printed, never
        # interpreted: this is a model's output and it is data here as everywhere else.
        if result.get("question"):
            lines.append(f"Question: {result['question']}")
        if result.get("draft"):
            lines.append("Draft:")
            lines.extend(f"  {line}" for line in str(result["draft"]).splitlines())
    lines.append(f"Next: {result['next_action']['reason']}")
    return "\n".join(lines)


def _resolve_stdin_text(args: argparse.Namespace) -> None:
    """Replace ``--text -`` with stdin, in the terminal only.

    ``run_argv`` deliberately never calls this: the local app server dispatches on a
    request thread with no console attached, where reading stdin would hang it.
    """
    if getattr(args, "command", "") != "context":
        return
    if getattr(args, "text", None) != STDIN_SENTINEL:
        return
    args.text = sys.stdin.read()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _resolve_stdin_text(args)
    result = _dispatch_result(args)
    if getattr(args, "json_out", False):
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    elif args.command == "statusline":
        line = result.get("line", "")
        if line:
            sys.stdout.write(line + "\n")
    else:
        sys.stdout.write(_render_human(result) + "\n")
    if args.command == "statusline":
        return 0
    return 0 if result["ok"] else 1


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
