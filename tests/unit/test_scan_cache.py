"""What the catalogue cache is allowed to save, and what it is never allowed to decide.

The cache exists because reading fifteen hundred documents on a mounted filesystem takes
tens of seconds and almost none of them have changed since the last look. It earns that
only while it is invisible: the moment it answers a question about a file the operator has
just edited with what that file used to say, it is worse than the slowness it replaced,
because someone fills in an answer, sees nothing move, and stops believing the dashboard.

So these tests are mostly about staleness rather than speed. Every way a document can
change — its text, its length, its existence, the schema it is read against, the cache file
itself going bad — has a test here saying the next answer is the true one. The two speed
tests count how many documents were opened, because "it was not read" is the only
observable difference between a cache that worked and one that quietly did nothing.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from marketing_os.core import catalog
from marketing_os.core.catalog import build_catalog, docs_iter, scan_cache_path
from marketing_os.core.setup import setup_repo
from marketing_os.core.status import status_repo
from marketing_os.ui import state as ui_state
from marketing_os.ui.server import TOKEN_HEADER, _state_findings, create_server

TOKEN = "scan-cache-token"


@pytest.fixture(autouse=True)
def _own_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the app's registry and pid file out of the operator's real home folder."""
    monkeypatch.setenv(ui_state.HOME_ENV, str(tmp_path / "mos-home"))


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    setup_repo(root, "Cache Co", "all", mode="in-house", apply=True)
    return root


def _write(root: Path, relative: str, text: str) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def _document(title: str, body: str) -> str:
    return (
        "---\n"
        f"title: {title}\n"
        "type: note\nstatus: current\ndate: 2026-01-01\nsources: [a/b.md]\n"
        "---\n\n"
        f"# {title}\n\n{body}\n"
    )


@contextlib.contextmanager
def _counting_reads(monkeypatch: pytest.MonkeyPatch):
    """Every document opened while this is held, in the order they were opened."""
    opened: list[str] = []
    real = catalog._read_document

    def counted(path: Path) -> str | None:
        opened.append(Path(path).name)
        return real(path)

    monkeypatch.setattr(catalog, "_read_document", counted)
    yield opened


@contextlib.contextmanager
def _serving(root: Path):
    server = create_server(root, port=0, token=TOKEN)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _state(server, path: Path) -> dict:
    url = f"http://127.0.0.1:{server.port}/api/state?path={urllib.parse.quote(str(path))}"
    request = urllib.request.Request(url)
    request.add_header(TOKEN_HEADER, TOKEN)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


# --- what the cache saves ---------------------------------------------------------------


def test_a_second_catalogue_opens_nothing_and_answers_the_same(
    brain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(brain, "knowledge/one.md", _document("One", "The first document, with real words."))
    first = build_catalog(brain)
    assert scan_cache_path(brain).is_file()

    with _counting_reads(monkeypatch) as opened:
        second = build_catalog(brain)

    assert second == first
    assert opened == [], "an unchanged brain must not be opened a second time"


def test_only_the_edited_document_is_opened_again(
    brain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(brain, "knowledge/one.md", _document("One", "The first document, with real words."))
    _write(brain, "knowledge/two.md", _document("Two", "The second document, also with words."))
    build_catalog(brain)

    _write(brain, "knowledge/two.md", _document("Two", "Rewritten, and rather longer than it was."))
    with _counting_reads(monkeypatch) as opened:
        docs = build_catalog(brain)

    assert opened == ["two.md"]
    assert "rather longer" in docs["knowledge/two.md"]["description"]


# --- what the cache must never decide ----------------------------------------------------


def test_an_edited_document_is_read_again(brain: Path) -> None:
    _write(brain, "knowledge/one.md", _document("One", "Before the edit, at some length."))
    assert "Before the edit" in build_catalog(brain)["knowledge/one.md"]["description"]

    _write(brain, "knowledge/one.md", _document("One", "After the edit, at some length. "))
    assert "After the edit" in build_catalog(brain)["knowledge/one.md"]["description"]


def test_an_edit_that_keeps_the_length_is_still_read_again(brain: Path) -> None:
    """Size alone is not evidence. The modification time is the other half of the stamp."""
    before = _document("One", "aaaa bbbb cccc dddd eeee ffff gggg hhhh")
    after = _document("One", "zzzz yyyy xxxx wwww vvvv uuuu tttt ssss")
    assert len(before) == len(after)

    _write(brain, "knowledge/one.md", before)
    assert "aaaa" in build_catalog(brain)["knowledge/one.md"]["description"]
    _write(brain, "knowledge/one.md", after)
    assert "zzzz" in build_catalog(brain)["knowledge/one.md"]["description"]


def test_a_new_document_and_a_removed_one_both_land(brain: Path) -> None:
    _write(brain, "knowledge/one.md", _document("One", "The first document, with real words."))
    assert set(build_catalog(brain)) >= {"knowledge/one.md"}

    _write(brain, "knowledge/two.md", _document("Two", "The second document, also with words."))
    docs = build_catalog(brain)
    assert "knowledge/two.md" in docs

    (brain / "knowledge/one.md").unlink()
    assert "knowledge/one.md" not in build_catalog(brain)


def test_a_cache_read_against_another_schema_is_ignored(brain: Path) -> None:
    """A catalogue entry is a reading of a document against a schema, not the document."""
    _write(brain, "knowledge/one.md", _document("One", "The first document, with real words."))
    build_catalog(brain)

    payload = json.loads(scan_cache_path(brain).read_text(encoding="utf-8"))
    payload["fingerprint"] = "not the schema this run is using"
    payload["docs"]["knowledge/one.md"]["doc"]["description"] = "a stale reading"
    scan_cache_path(brain).write_text(json.dumps(payload), encoding="utf-8")

    assert build_catalog(brain)["knowledge/one.md"]["description"] != "a stale reading"


@pytest.mark.parametrize(
    "text",
    ["", "{", "[]", '{"schema": "mos.scan-cache.v9", "docs": {}}', '{"docs": "not a mapping"}'],
)
def test_a_cache_that_cannot_be_trusted_costs_nothing(brain: Path, text: str) -> None:
    _write(brain, "knowledge/one.md", _document("One", "The first document, with real words."))
    expected = build_catalog(brain)

    scan_cache_path(brain).write_text(text, encoding="utf-8")
    assert build_catalog(brain) == expected


def test_a_brain_that_cannot_be_written_to_still_answers(
    brain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(brain, "knowledge/one.md", _document("One", "The first document, with real words."))

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError("read-only")

    monkeypatch.setattr(catalog, "atomic_write", refuse)
    assert "knowledge/one.md" in build_catalog(brain)


# --- the answer the operator is actually watching ----------------------------------------


def test_answering_a_question_changes_the_next_state_request(
    brain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole reason the cache is per-file: fill in a field, see the dashboard move.

    Two state requests over the real route, with one context answer written between them.
    The second must report the field answered — and must have opened that file and no other,
    because a cache that re-read everything would prove nothing and one that re-read nothing
    would be the bug this test exists to catch.
    """
    with _serving(brain) as server:
        first = _state(server, brain)
        assert first["status"]["context"]["fields"]["brand"]["complete"] is False
        assert "brand" in first["status"]["context"]["missing"]

        _write(
            brain,
            "business/brand/brand.md",
            "# Brand\n\nWe build marketing systems that outlive the campaigns they were "
            "written for, and we show the work.\n",
        )

        with _counting_reads(monkeypatch) as opened:
            second = _state(server, brain)

    assert second["status"]["context"]["fields"]["brand"]["complete"] is True
    assert "brand" not in second["status"]["context"]["missing"]
    assert opened == ["brand.md"], f"only the edited document should be reopened, saw {opened}"


def test_a_document_added_outside_the_app_reaches_the_next_status(brain: Path) -> None:
    """The other half: something appearing on disk that the app never wrote."""
    before = status_repo(brain)
    _write(brain, "knowledge/loose.md", "# Loose\n\nA document with no contract block at all.\n")
    after = status_repo(brain)

    was = {item["code"] for item in before["findings"]}
    codes = {item["code"] for item in after["findings"]} - was
    paths = {item.get("path") for item in after["findings"]}
    assert "missing-frontmatter" in codes or "knowledge/loose.md" in paths
    assert len(after["findings"]) > len(before["findings"])


# --- the walk the cache is built on ------------------------------------------------------


def _reference_docs(root: Path) -> list[str]:
    """What ``rglob`` plus a filter found, which is what the pruning walk replaced."""
    skipped = catalog.excluded_roots()
    found: list[str] = []
    for path in root.rglob("*.md"):
        relative = path.relative_to(root)
        if path.suffix != ".md":  # rglob matches case-insensitively on Windows; the walk does not
            continue
        if any(part in catalog.SKIP_DIRS for part in relative.parts):
            continue
        if relative.parts and relative.parts[0] in skipped:
            continue
        if not path.is_file():
            continue
        found.append(relative.as_posix())
    # The walk orders by the posix relative path; sorting ``Path`` objects would order by
    # the host's spelling instead, which on Windows folds case and puts ``business`` ahead
    # of ``CLAUDE.md``.
    return sorted(found)


def test_the_pruning_walk_finds_exactly_what_the_filtered_one_found(brain: Path) -> None:
    _write(brain, "knowledge/one.md", _document("One", "A document."))
    _write(brain, "knowledge/deep/deeper/two.md", _document("Two", "A deeper document."))
    _write(brain, "archive/old.md", _document("Old", "Excluded by the schema."))
    _write(brain, ".git/objects/note.md", "not a document")
    _write(brain, "node_modules/pkg/readme.md", "not a document")
    _write(brain, "knowledge/node_modules/nested/skip.md", "not a document")
    _write(brain, "knowledge/__pycache__/skip.md", "not a document")

    assert [relative for _path, relative in docs_iter(brain)] == _reference_docs(brain)


def test_the_walk_does_not_follow_a_linked_folder(brain: Path, tmp_path: Path) -> None:
    """``rglob`` refuses to descend through a symlink, and so must this."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "elsewhere.md").write_text("# Elsewhere\n\nOutside the brain.\n", encoding="utf-8")
    try:
        os.symlink(outside, brain / "knowledge" / "linked")
    except (OSError, NotImplementedError):  # pragma: no cover - platform without symlinks
        pytest.skip("this filesystem does not make symbolic links")

    found = [relative for _path, relative in docs_iter(brain)]
    assert "knowledge/linked/elsewhere.md" not in found
    assert found == _reference_docs(brain)


# --- what the page is sent ---------------------------------------------------------------


def test_the_page_is_sent_a_short_list_and_the_true_numbers() -> None:
    findings = [{"code": "w", "severity": "warning", "message": str(i)} for i in range(10)]
    findings.append({"code": "e", "severity": "error", "message": "the one that matters"})

    trimmed = _state_findings({"findings": findings}, 3)

    assert trimmed["findings_total"] == 11
    assert trimmed["findings_counts"] == {"warning": 10, "error": 1}
    assert trimmed["findings_capped"] is True
    assert len(trimmed["findings"]) == 3
    assert trimmed["findings"][0]["severity"] == "error", "an error is never cut away"


def test_a_list_that_fits_is_sent_whole_and_says_so() -> None:
    findings = [{"code": "w", "severity": "warning", "message": "one"}]
    trimmed = _state_findings({"findings": findings}, 200)
    assert trimmed["findings"] == findings
    assert trimmed["findings_total"] == 1 and trimmed["findings_capped"] is False


def test_state_carries_the_checks_without_the_duplicated_findings(brain: Path) -> None:
    _write(brain, "knowledge/one.md", "# One\n\nA document with no contract block.\n")
    with _serving(brain) as server:
        payload = _state(server, brain)

    assert set(payload["doctor"]["checks"]) == {"structure", "runtime_wiring", "context_ready"}
    assert payload["doctor"]["findings"] == []
    assert payload["doctor"]["findings_total"] >= payload["status"]["findings_total"]
    assert payload["status"]["findings_total"] == len(payload["status"]["findings"])


# --- asking one brain two questions ------------------------------------------------------


def test_doctor_inside_a_reuse_block_does_not_walk_the_brain_again(
    brain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``mos doctor`` is ``mos status`` plus a finding, and used to pay for it twice."""
    from marketing_os.core import status as core_status

    walks: list[str] = []
    real = core_status._status_repo

    def counted(root: Path) -> dict:
        walks.append(str(root))
        return real(root)

    monkeypatch.setattr(core_status, "_status_repo", counted)

    with core_status.reuse():
        status = core_status.status_repo(brain)
        doctor = core_status.doctor_repo(brain)

    assert len(walks) == 1, "one brain, one walk"
    assert doctor["findings"][: len(status["findings"])] == status["findings"]
    assert doctor["checks"]["structure"] is (
        not [item for item in status["findings"] if item["severity"] == "error"]
    )


def test_outside_a_reuse_block_nothing_is_kept(
    brain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No block, no memory: the terminal's two commands behave exactly as they always did."""
    from marketing_os.core import status as core_status

    walks: list[str] = []
    real = core_status._status_repo
    monkeypatch.setattr(
        core_status, "_status_repo", lambda root: (walks.append(str(root)), real(root))[1]
    )

    core_status.status_repo(brain)
    core_status.doctor_repo(brain)

    assert len(walks) == 2


def test_an_edited_answer_shows_up_without_rereading_the_brain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both halves of the bargain, in one test, over the real route.

    A cache is worth having only if it saves work, and worth trusting only if it never
    answers for a file that has moved on. So this asserts the edit is visible on the very
    next state request AND that noticing it did not cost a second reading of the other
    forty documents. Run against the code before this change, the first assertion passed
    and the second failed with 110 documents read again — fifty-five of them twice, once
    for status and once for doctor.
    """
    root = tmp_path / "wide"
    setup_repo(root, "Probe Co", "all", mode="in-house", apply=True)
    for index in range(40):
        _write(
            root,
            f"knowledge/note-{index:02d}.md",
            f"# Note {index}\n\nA document with a reasonable amount of prose in it.\n",
        )

    with _serving(root) as server:
        first = _state(server, root)
        assert first["status"]["context"]["fields"]["brand"]["complete"] is False

        _write(
            root,
            "business/brand/brand.md",
            "# Brand\n\nWe build marketing systems that outlive the campaigns they were "
            "written for, and we show the work.\n",
        )

        described: list[str] = []
        real = catalog.describe
        monkeypatch.setattr(
            catalog,
            "describe",
            lambda path, relative, text: (
                described.append(relative),
                real(path, relative, text),
            )[1],
        )
        second = _state(server, root)

    assert second["status"]["context"]["fields"]["brand"]["complete"] is True
    assert len(described) == 1, f"{len(described)} documents were read again, not 1"
