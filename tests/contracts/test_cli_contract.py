import io
import json
from pathlib import Path

import pytest

from marketing_os.cli import main as cli_main
from marketing_os.cli.main import main, run_argv
from marketing_os.core.results import envelope, next_action

REQUIRED_KEYS = {"schema", "command", "ok", "repo", "changes", "findings", "next_action"}


def _onboard(target: Path, *extra: str) -> None:
    main(
        [
            "onboard",
            str(target),
            "--name",
            "Example Business",
            "--mode",
            "in-house",
            *extra,
            "--json",
        ]
    )


def _make_repo(tmp_path: Path, capsys) -> Path:
    target = tmp_path / "brain"
    _onboard(target, "--yes")
    capsys.readouterr()
    return target


def test_onboard_json_envelope_and_plan(tmp_path: Path, capsys) -> None:
    target = tmp_path / "brain"
    code = main(
        [
            "onboard",
            str(target),
            "--name",
            "Example Business",
            "--mode",
            "in-house",
            "--runtime",
            "all",
            "--plan",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload.keys() >= REQUIRED_KEYS
    assert payload["schema"] == "mos.onboard.v1"
    assert payload["mode"] == "in-house"
    assert not target.exists()


def test_onboard_without_mode_returns_choose_mode(tmp_path: Path, capsys) -> None:
    target = tmp_path / "brain"
    code = main(["onboard", str(target), "--name", "Example Business", "--yes", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert payload["next_action"]["id"] == "choose-mode"
    assert "--mode <choice>" in payload["next_action"]["reason"]
    assert not target.exists()


def test_failure_is_json_without_human_output(tmp_path: Path, capsys) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    (target / "notes.txt").write_text("existing", encoding="utf-8")
    code = main(
        [
            "onboard",
            str(target),
            "--name",
            "Example Business",
            "--runtime",
            "all",
            "--yes",
            "--json",
        ]
    )
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert code == 1
    assert payload["ok"] is False
    assert output.lstrip().startswith("{")


def test_read_commands_share_envelope(tmp_path: Path, capsys) -> None:
    target = tmp_path / "brain"
    _onboard(target, "--yes")
    capsys.readouterr()
    for command in ("status", "validate", "doctor"):
        code = main([command, str(target), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload.keys() >= REQUIRED_KEYS


def test_help_lists_all_commands(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    for command in (
        "install",
        "status",
        "validate",
        "doctor",
        "skills",
        "ingest",
        "query",
        "think",
        "onboard",
        "attach",
        "migrate",
        "update",
        "statusline",
        "context",
        "fix",
    ):
        assert command in output


def test_ingest_envelope_and_pending(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(["ingest", "a short captured note about pricing", str(target), "--yes", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema"] == "mos.ingest.v1"
    assert payload.keys() >= REQUIRED_KEYS
    assert payload["applied"] is True

    code = main(["ingest", "--pending", str(target), "--json"])
    pending = json.loads(capsys.readouterr().out)
    assert code == 0
    assert pending["schema"] == "mos.ingest-pending.v1"
    assert pending["command"] == "ingest-pending"
    assert pending["pending"]  # the fresh capture is not yet compiled


def test_ingest_plan_does_not_write(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(["ingest", "literal planning text", str(target), "--plan", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["planned"] is True
    # The scaffold already contains knowledge/sources/; --plan must not write a capture.
    assert list((target / "knowledge" / "sources").rglob("source.md")) == []


def test_ingest_requires_source_or_pending(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(["ingest", str(target), "--json"])
    payload = json.loads(capsys.readouterr().out)
    # With a single positional, it is read as SOURCE; without a mutation flag it fails.
    assert code == 1
    assert payload["ok"] is False


def test_ingest_missing_mutation_flag_is_rejected(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(["ingest", "some text", str(target), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert payload["findings"][0]["code"] == "command-error"


def test_ingest_pending_rejects_source(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(["ingest", "--pending", "unexpected", str(target), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False


def test_ingest_pending_with_yes_is_rejected(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(["ingest", "--pending", str(target), "--yes", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert payload["findings"][0]["code"] == "command-error"


def test_ingest_pending_with_plan_is_rejected(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(["ingest", "--pending", str(target), "--plan", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert payload["findings"][0]["code"] == "command-error"


def test_query_envelope(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(["query", "what is the brand strategy", str(target), "--limit", "3", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema"] == "mos.query.v1"
    assert payload["question"] == "what is the brand strategy"
    assert "candidates" in payload


def test_think_envelope(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(["think", "pricing model", str(target), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema"] == "mos.think.v1"
    assert payload["prompt"]["context_paths"]


def test_onboard_envelope_and_mutation_enforcement(tmp_path: Path, capsys) -> None:
    target = tmp_path / "fresh"
    code = main(
        ["onboard", str(target), "--name", "Fresh Co", "--mode", "in-house", "--yes", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema"] == "mos.onboard.v1"
    assert "interview" in payload
    assert payload["mode"] == "in-house"

    with pytest.raises(SystemExit) as exc:
        main(["onboard", str(target), "--name", "Fresh Co", "--mode", "in-house", "--json"])
    assert exc.value.code == 2


def test_attach_plans_then_applies_a_legacy_folder(tmp_path: Path, capsys) -> None:
    target = tmp_path / "legacy"
    (target / ".mos").mkdir(parents=True)
    (target / ".mos" / "config.yaml").write_text(
        "mode: agency\nname: Legacy Lab\n", encoding="utf-8"
    )
    (target / "BRAIN.md").write_text("# Mine\n", encoding="utf-8")
    (target / "business").mkdir()

    code = main(["attach", str(target), "--plan", "--json"])
    planned = json.loads(capsys.readouterr().out)
    assert code == 0
    assert planned.keys() >= REQUIRED_KEYS
    assert planned["schema"] == "mos.attach.v1"
    assert planned["planned"] is True
    assert planned["name"] == "Legacy Lab"
    assert planned["mode"] == "agency"
    assert "config .mos/config.yaml" in planned["changes"]
    assert (target / ".mos" / "config.yaml").read_text(encoding="utf-8").startswith("mode:")

    code = main(["attach", str(target), "--yes", "--json"])
    applied = json.loads(capsys.readouterr().out)
    assert code == 0
    assert applied["applied"] is True
    assert applied["next_action"]["id"] == "run-status"

    code = main(["status", str(target), "--json"])
    status = json.loads(capsys.readouterr().out)
    assert status["repo_state"] != "absent"

    with pytest.raises(SystemExit) as exc:
        main(["attach", str(target), "--json"])
    assert exc.value.code == 2


def test_help_lists_mode_flag(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["onboard", "--help"])
    output = capsys.readouterr().out
    assert "--mode" in output
    assert "--agency" in output


def test_update_envelope_is_monkeypatched(monkeypatch, capsys) -> None:
    def fake_update(*, apply: bool) -> dict:
        return envelope(
            "update",
            Path.cwd(),
            ok=True,
            changes=["noop"],
            action=next_action("run-doctor", "Verify the engine."),
            mode="pipx",
            run_command="noop",
            applied=apply,
            planned=not apply,
        )

    monkeypatch.setattr(cli_main, "update_engine", fake_update)
    code = main(["update", "--plan", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema"] == "mos.update.v1"
    assert payload["mode"] == "pipx"


def test_update_missing_mutation_flag_is_rejected() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["update", "--json"])
    assert exc.value.code == 2


def test_statusline_outside_repo_is_silent_and_zero(tmp_path: Path, capsys) -> None:
    code = main(["statusline", str(tmp_path)])
    output = capsys.readouterr().out
    assert code == 0
    assert output == ""


def test_statusline_active_prints_line(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(["statusline", str(target)])
    output = capsys.readouterr().out
    assert code == 0
    assert output.startswith("mos")
    assert output.endswith("\n")


def test_statusline_json_envelope(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(["statusline", str(target), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema"] == "mos.statusline.v1"
    assert payload["active"] is True


def _seed_corpus(root: Path, count: int) -> None:
    for number in range(count):
        target = root / "knowledge" / "wiki" / f"page-{number:03d}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"---\ntitle: Page {number}\ntype: knowledge\n"
            f"description: Channel notes for page {number}.\n"
            f"date: 2026-08-20\nstatus: active\nproduced_by: test\n---\n\n"
            f"# Page {number}\n\nChannel notes for page {number}.\n",
            encoding="utf-8",
        )


def test_index_build_emits_the_envelope(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(["index", "build", str(target), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload.keys() >= REQUIRED_KEYS
    assert payload["schema"] == "mos.index-build.v1"
    assert (target / ".mos" / "local" / "catalog.json").is_file()


def test_index_sync_requires_plan_or_apply(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    with pytest.raises(SystemExit):
        main(["index", "sync", str(target), "--json"])


def test_index_sync_plans_then_applies(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    _seed_corpus(target, 30)
    main(["index", "sync", str(target), "--plan", "--json"])
    planned = json.loads(capsys.readouterr().out)
    assert planned["planned"] is True
    assert planned["changes"]
    assert not (target / "_index.md").exists()

    main(["index", "sync", str(target), "--yes", "--json"])
    applied = json.loads(capsys.readouterr().out)
    assert applied["schema"] == "mos.index-sync.v1"
    assert "_index.md" in applied["applied"]
    assert (target / "_index.md").is_file()


def test_index_status_reports_coverage(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(["index", "status", str(target), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema"] == "mos.index-status.v1"
    assert payload["coverage"]["documents"] > 0
    assert set(payload["percent"]) == {"frontmatter", "description", "outgoing_links"}


def test_related_plans_then_applies(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    _seed_corpus(target, 30)
    main(["related", str(target), "--plan", "--json"])
    planned = json.loads(capsys.readouterr().out)
    assert planned["schema"] == "mos.related.v1"
    assert planned["planned"] is True
    assert planned["applied"] == []

    main(["related", str(target), "--yes", "--limit", "2", "--json"])
    applied = json.loads(capsys.readouterr().out)
    assert len(applied["applied"]) <= 2


def test_validate_strict_promotes_contract_gaps(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    (target / "knowledge" / "wiki" / "loose.md").write_text(
        "# Loose\n\nNo contract block at all.\n", encoding="utf-8"
    )
    main(["validate", str(target), "--json"])
    relaxed = json.loads(capsys.readouterr().out)
    assert relaxed["ok"] is True
    assert relaxed["strict"] is False
    assert relaxed["summary"]["contract_gaps"] > 0

    code = main(["validate", str(target), "--strict", "--json"])
    strict = json.loads(capsys.readouterr().out)
    assert code == 1
    assert strict["ok"] is False


def test_query_grep_returns_literal_matches(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    (target / "knowledge" / "wiki" / "links.md").write_text(
        "# Links\n\nSee https://example.com/pricing\n", encoding="utf-8"
    )
    code = main(["query", "https://example.com/pricing", str(target), "--grep", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["mode"] == "grep"
    assert payload["matches"][0]["path"] == "knowledge/wiki/links.md"


ANSWER = (
    "We are the boxing gym for people who were never picked for the team. Beginners "
    "first, no egos, no shouting, and every class starts on time."
)


def test_context_show_envelope(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(["context", "show", str(target), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload.keys() >= REQUIRED_KEYS
    assert payload["schema"] == "mos.context.v1"
    assert payload["operation"] == "show"
    assert payload["missing"] == ["brand", "voice", "audience", "offer"]
    assert all(item["question"] for item in payload["fields"])


def test_context_set_plans_then_applies_and_status_agrees(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(
        ["context", "set", str(target), "--field", "brand", "--text", ANSWER, "--plan", "--json"]
    )
    planned = json.loads(capsys.readouterr().out)
    assert code == 0
    assert planned["schema"] == "mos.context.v1"
    assert planned["planned"] is True
    assert planned["diff"]
    assert "TODO:" in (target / "business" / "brand" / "brand.md").read_text(encoding="utf-8")

    code = main(
        ["context", "set", str(target), "--field", "brand", "--text", ANSWER, "--yes", "--json"]
    )
    applied = json.loads(capsys.readouterr().out)
    assert code == 0
    assert applied["applied"] is True

    main(["status", str(target), "--json"])
    status = json.loads(capsys.readouterr().out)
    assert status["context"]["missing"] == ["voice", "audience", "offer"]
    assert status["context"]["fields"]["brand"]["complete"] is True


def test_context_set_requires_a_mutation_flag(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    with pytest.raises(SystemExit) as exc:
        main(["context", "set", str(target), "--field", "brand", "--text", ANSWER, "--json"])
    assert exc.value.code == 2


def test_context_set_reads_the_answer_from_stdin(tmp_path: Path, capsys, monkeypatch) -> None:
    target = _make_repo(tmp_path, capsys)
    monkeypatch.setattr("sys.stdin", io.StringIO(ANSWER))
    code = main(
        ["context", "set", str(target), "--field", "voice", "--text", "-", "--yes", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["field_complete"] is True
    assert ANSWER in (target / "business" / "brand" / "voice.md").read_text(encoding="utf-8")


def test_context_stdin_sentinel_never_reaches_a_server_thread(tmp_path: Path, capsys) -> None:
    """run_argv is the local app's seam; reading stdin there would hang the request."""
    target = _make_repo(tmp_path, capsys)
    result = run_argv(["context", "set", str(target), "--field", "brand", "--text", "-", "--yes"])
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "command-error"
    assert "stdin" in result["findings"][0]["message"]


def test_context_set_unknown_field_is_a_finding_not_a_crash(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(
        ["context", "set", str(target), "--field", "vibe", "--text", ANSWER, "--yes", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["findings"][0]["code"] == "unknown-field"
    assert "brand" in payload["findings"][0]["message"]


def test_context_plan_prints_the_diff_for_a_human(tmp_path: Path, capsys) -> None:
    target = _make_repo(tmp_path, capsys)
    code = main(["context", "set", str(target), "--field", "brand", "--text", ANSWER, "--plan"])
    output = capsys.readouterr().out
    assert code == 0
    assert "Diff:" in output
    assert f"+{ANSWER}" in output


# --- assist: the one seam that may invoke an agent runtime ---------------------------


def _no_runtimes(monkeypatch, tmp_path: Path) -> None:
    """A PATH with nothing on it, so the contract tests never touch a real runtime."""
    empty = tmp_path / "empty-path"
    empty.mkdir(exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", str(empty))


def test_assist_status_is_an_envelope_and_reports_nothing_when_nothing_answers(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    _no_runtimes(monkeypatch, tmp_path)
    code = main(["assist", "status", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload.keys() >= REQUIRED_KEYS
    assert payload["schema"] == "mos.assist.v1"
    assert payload["command"] == "assist"
    assert payload["operation"] == "status"
    assert payload["ok"] is True
    assert payload["ready"] is False
    assert payload["runtimes"] == []
    assert payload["changes"] == []


def test_assist_ask_fails_clearly_with_no_runtime_and_writes_nothing(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    target = _make_repo(tmp_path, capsys)
    _no_runtimes(monkeypatch, tmp_path)
    code = main(["assist", "ask", str(target), "--field", "brand", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload.keys() >= REQUIRED_KEYS
    assert payload["schema"] == "mos.assist.v1"
    assert payload["operation"] == "ask"
    assert payload["ok"] is False
    assert payload["findings"][0]["code"] == "no-runtime"
    assert payload["question"] == ""
    assert payload["draft"] == ""
    assert payload["changes"] == []


def test_assist_ask_refuses_a_field_that_is_not_a_context_field(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """A field that looks like a flag is stopped twice: by argparse, then by the field set."""
    target = _make_repo(tmp_path, capsys)
    _no_runtimes(monkeypatch, tmp_path)

    # Written as two tokens, our own parser refuses it as a usage error.
    usage = run_argv(["assist", "ask", str(target), "--field", "--print"])
    assert usage["ok"] is False
    assert usage["findings"][0]["code"] == "command-error"

    # Forced through as one token, the closed set of context fields refuses it, and no
    # child is ever reached with it.
    code = main(["assist", "ask", str(target), "--field=--print", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["findings"][0]["code"] == "unknown-field"
    assert payload["question"] == ""


def test_assist_ask_refuses_a_transcript_that_is_not_json(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    target = _make_repo(tmp_path, capsys)
    _no_runtimes(monkeypatch, tmp_path)
    result = run_argv(
        ["assist", "ask", str(target), "--field", "brand", "--transcript-json", "nonsense"]
    )
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "bad-transcript"
