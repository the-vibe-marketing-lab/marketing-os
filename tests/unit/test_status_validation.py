import json
from pathlib import Path

from marketing_os.core.setup import setup_repo
from marketing_os.core.status import doctor_repo, status_repo
from marketing_os.core.validation import validate_repo


def _rewrite_config(root: Path, **changes: object) -> None:
    config_path = root / ".mos" / "config.yaml"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            config.pop(key, None)
        else:
            config[key] = value
    config_path.write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _complete_context(root: Path) -> None:
    (root / "business/brand/brand.md").write_text(
        "# Brand\n\nWe make operational marketing systems understandable and durable.\n",
        encoding="utf-8",
    )
    (root / "business/brand/voice.md").write_text(
        "# Voice\n\nClear, direct, warm, specific, and free from inflated claims.\n",
        encoding="utf-8",
    )
    (root / "business/audience/primary.md").write_text(
        "# Audience\n\nSmall marketing teams that need reliable context across agent sessions.\n",
        encoding="utf-8",
    )
    offer = root / "business/offers/marketing-brain/offer.md"
    offer.parent.mkdir(parents=True)
    offer.write_text(
        "# Marketing Brain\n\n"
        "A file-based operating system that keeps agent work grounded and reusable.\n",
        encoding="utf-8",
    )


def _non_canonical_context(root: Path) -> None:
    """Answer every required field the way a working brain does: nowhere the schema names.

    This is the shape of a real repository — voice and audience in a reference folder with no
    frontmatter at all, positioning marking itself canonical, and the offer content in a
    singular ``business/offer/`` while the canonical plural folder sits empty.
    """
    positioning = root / "business/offer"
    positioning.mkdir(parents=True)
    (positioning / "core-offer.md").write_text(
        "# Core offer\n\n"
        "A six week build-along for marketers who want the system installed rather than "
        "explained, at one fixed price.\n",
        encoding="utf-8",
    )
    brand = root / "business/brand/positioning"
    brand.mkdir(parents=True)
    (brand / "positioning.md").write_text(
        "---\ncanonical: true\n---\n\n# Positioning\n\n"
        "The brain for marketers who would rather install a working system than read another "
        "explanation of one.\n",
        encoding="utf-8",
    )
    core = root / "reference/core"
    core.mkdir(parents=True)
    (core / "voice.md").write_text(
        "# Voice\n\n"
        "Precision-led and evidence-based. Every sentence earns its place, and nothing is "
        "claimed that cannot be shown.\n",
        encoding="utf-8",
    )
    (core / "audience.md").write_text(
        "# Audience\n\n"
        "Marketers running their own delivery who have tried the tools, kept none of them, "
        "and want one system that holds.\n",
        encoding="utf-8",
    )


def test_fresh_repo_validates_but_requires_context(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    validation = validate_repo(root)
    status = status_repo(root)
    assert validation["ok"] is True
    assert status["repo_state"] == "needs-context"
    assert status["context"]["missing"] == ["brand", "voice", "audience", "offer"]
    # The scaffold is all TODO stubs, so discovery must find nothing to promote.
    fields = status["context"]["fields"]
    assert [fields[name]["source"] for name in status["context"]["required"]] == ["missing"] * 4


def test_completed_context_becomes_ready(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    _complete_context(root)
    status = status_repo(root)
    assert status["ok"] is True
    assert status["repo_state"] == "ready"
    assert status["context"]["ready"] is True
    fields = status["context"]["fields"]
    assert [fields[name]["source"] for name in status["context"]["required"]] == ["canonical"] * 4
    assert all("discovered_path" not in fields[name] for name in fields)
    assert fields["brand"]["path"] == "business/brand/brand.md"


def test_non_canonical_context_reports_ready_without_moving_the_canonical_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    _non_canonical_context(root)
    status = status_repo(root)
    fields = status["context"]["fields"]

    assert status["context"]["ready"] is True
    assert status["context"]["missing"] == []
    assert status["repo_state"] == "ready"
    assert [fields[name]["source"] for name in status["context"]["required"]] == ["discovered"] * 4
    assert fields["voice"]["discovered_path"] == "reference/core/voice.md"
    assert fields["audience"]["discovered_path"] == "reference/core/audience.md"
    assert fields["brand"]["discovered_path"] == "business/brand/positioning/positioning.md"
    assert fields["offer"]["discovered_path"] == "business/offer/core-offer.md"
    # The canonical paths keep their meaning: they are still where an answer gets written.
    assert fields["voice"]["path"] == "business/brand/voice.md"
    assert fields["offer"]["path"] == "business/offers/<offer-slug>/offer.md"
    # An unanswered field is still unanswered; discovery does not manufacture proof.
    assert fields["proof"]["source"] == "missing"


def test_validate_still_flags_a_non_canonical_layout_that_status_can_read(
    tmp_path: Path,
) -> None:
    """Structural conformance and content detection are separate questions.

    Status now finds the content in ``reference/``; validate still says ``reference/`` is not
    part of the architecture. Both are true, and neither answer is allowed to soften the other.
    """
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    _non_canonical_context(root)
    validation = validate_repo(root)
    flagged = [item for item in validation["findings"] if item["code"] == "unknown-top-level"]
    assert validation["ok"] is True
    assert [item["path"] for item in flagged] == ["reference"]
    assert status_repo(root)["context"]["ready"] is True


def test_invalid_dated_artifact_is_reported(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    invalid = root / "content" / "loose-file.md"
    invalid.write_text("wrong place", encoding="utf-8")
    validation = validate_repo(root)
    assert validation["ok"] is False
    assert any(item["code"] == "invalid-year" for item in validation["findings"])


def test_agency_repo_validates_with_registry(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Example Agency", "all", mode="agency", apply=True)
    validation = validate_repo(root)
    assert validation["ok"] is True
    assert status_repo(root)["mode"] == "agency"


def test_agency_repo_without_registry_fails(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Example Agency", "all", mode="agency", apply=True)
    (root / "business" / "clients" / "clients.md").unlink()
    validation = validate_repo(root)
    assert validation["ok"] is False
    assert any(item["code"] == "missing-client-registry" for item in validation["findings"])


def test_in_house_repo_warns_on_unexpected_clients_folder(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    (root / "business" / "clients").mkdir()
    validation = validate_repo(root)
    assert validation["ok"] is True
    assert any(item["code"] == "unexpected-clients-folder" for item in validation["findings"])


def test_missing_mode_warns_but_stays_ok(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    _rewrite_config(root, mode=None)
    validation = validate_repo(root)
    assert validation["ok"] is True
    assert any(item["code"] == "missing-mode" for item in validation["findings"])
    assert status_repo(root)["mode"] == "in-house"


def test_legacy_repo_with_registry_suggests_agency(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    # Agency scaffold creates the client registry; stripping mode makes it a
    # legacy repo (implied in-house) that still carries the registry.
    setup_repo(root, "Example Agency", "all", mode="agency", apply=True)
    _rewrite_config(root, mode=None)
    validation = validate_repo(root)
    codes = [item["code"] for item in validation["findings"]]
    assert validation["ok"] is True
    assert "set-mode-agency" in codes
    assert "unexpected-clients-folder" not in codes


def test_invalid_mode_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    _rewrite_config(root, mode="franchise")
    validation = validate_repo(root)
    assert validation["ok"] is False
    assert any(item["code"] == "invalid-mode" for item in validation["findings"])


def test_doctor_reports_mode(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    setup_repo(root, "Example Agency", "all", mode="agency", apply=True)
    assert doctor_repo(root)["mode"] == "agency"


def test_navigation_files_never_answer_for_a_brain_that_is_still_stubs(tmp_path: Path) -> None:
    """The end-to-end form of the cheapest false positive there is.

    ``/mos-end`` tells the operator to run ``mos index sync`` at the end of every session, and
    that writes an ``_index.md`` into every folder holding documents. A folder README is the
    same shape by hand. Neither is anybody's answer, and a brain whose context files are all
    untouched TODO stubs must still report all four required fields missing after both exist.
    """
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    for folder in ("audience", "brand", "offers", "proof", "strategy"):
        (root / "business" / folder).mkdir(parents=True, exist_ok=True)
        (root / "business" / folder / "_index.md").write_text(
            f"# business/{folder}/ — index\n\n"
            "*Generated by `mos index sync` — do not hand-edit.*\n\n"
            "- [[business/log/2026-08-01-session]] — what happened in the last session\n",
            encoding="utf-8",
        )
        (root / "business" / folder / "README.md").write_text(
            f"# {folder}\n\nOne file per topic in here. Nothing has been written yet — this "
            "folder is a map, not an answer, and it stays that way until someone fills it.\n",
            encoding="utf-8",
        )

    context = status_repo(root)["context"]

    assert context["missing"] == ["brand", "voice", "audience", "offer"]
    assert context["ready"] is False
    assert [entry["source"] for entry in context["fields"].values()] == ["missing"] * 6


def test_an_offer_file_that_cannot_be_read_does_not_take_down_status(tmp_path: Path) -> None:
    """One file saved as UTF-16 used to raise out of ``mos status``, ``doctor`` and ``context``.

    Every other completeness check already treated an unreadable file as an unanswered one.
    The offer glob was the single place that still called straight through to ``read_text``.
    """
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    offer = root / "business/offers/my-offer/offer.md"
    offer.parent.mkdir(parents=True, exist_ok=True)
    offer.write_bytes(b"\xff\xfe# O\x00f\x00f\x00e\x00r\x00 not valid utf-8 at all\n")

    context = status_repo(root)["context"]

    assert context["fields"]["offer"]["complete"] is False
    assert "offer" in context["missing"]


def test_an_offer_written_straight_into_the_offers_folder_is_named(tmp_path: Path) -> None:
    """``files`` must name the file that answered, or ``context set`` writes a second one.

    The glob only matches ``offers/<slug>/offer.md``. An offer written one level up answers
    through the probe path instead, and reporting it complete with an empty ``files`` list
    sent the next answer to ``business/offers/core-offer/offer.md`` — a second offer document
    beside the one status was reading, with no ambiguity warning.
    """
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    (root / "business/offers").mkdir(parents=True, exist_ok=True)
    (root / "business/offers/offer.md").write_text(
        "# What we sell\n\nA six week build-along for marketers who want the system "
        "installed rather than explained, at a fixed price.\n",
        encoding="utf-8",
    )

    entry = status_repo(root)["context"]["fields"]["offer"]

    assert entry["complete"] is True
    assert entry["source"] == "canonical"
    assert entry["files"] == ["business/offers/offer.md"]


def test_a_scan_cut_short_by_its_budget_says_so_in_the_envelope(
    tmp_path: Path, monkeypatch
) -> None:
    """A partial scan reports itself as partial, so ``missing`` can be read for what it is."""
    from marketing_os.core import discover

    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    (root / "reference/core").mkdir(parents=True, exist_ok=True)
    for name in ("voice.md", "brand.md", "audience.md"):
        (root / "reference/core" / name).write_text(
            "# Heading\n\nEnough real writing here to clear the completeness bar without "
            "any trouble at all.\n",
            encoding="utf-8",
        )
    monkeypatch.setattr(discover, "FILE_BUDGET", 1)

    fields = status_repo(root)["context"]["fields"]

    assert any(entry.get("truncated") for entry in fields.values())


def _material_only(root: Path) -> None:
    """A folder that is nobody's brain yet and already holds the answers.

    The shape an operator points onboarding at on day one: real writing, filed the way they
    file things, with no ``.mos/config.yaml`` anywhere near it. Brand lands on its canonical
    path and voice and audience do not, so one folder exercises both kinds of answer.
    """
    (root / "business/brand").mkdir(parents=True)
    (root / "business/brand/brand.md").write_text(
        "# Brand\n\n"
        "The brain for marketers who would rather install a working system than read another "
        "explanation of one.\n",
        encoding="utf-8",
    )
    (root / "reference/core").mkdir(parents=True)
    (root / "reference/core/voice.md").write_text(
        "# Voice\n\n"
        "Precision-led and evidence-based. Every sentence earns its place, and nothing is "
        "claimed that cannot be shown.\n",
        encoding="utf-8",
    )
    (root / "reference/core/audience.md").write_text(
        "# Audience\n\n"
        "Marketers running their own delivery who have tried the tools, kept none of them, "
        "and want one system that holds.\n",
        encoding="utf-8",
    )


def test_a_folder_that_is_not_a_brain_reports_the_context_it_already_holds(
    tmp_path: Path,
) -> None:
    """Discovery has to answer before the folder is a brain, which is when onboarding asks.

    ``status_repo`` used to answer the config-less case from a literal, so a folder full of
    the operator's own writing reported the same four missing fields as an empty one — and
    onboarding then asked, from scratch, for what was already written down.
    """
    root = tmp_path / "material"
    root.mkdir()
    _material_only(root)

    status = status_repo(root)

    # Nothing about the verdict on the folder itself moves: it is still not a brain.
    assert status["repo_state"] == "absent"
    assert status["ok"] is False
    assert status["next_action"]["id"] == "run-setup"
    # What moves is that the answers it already holds are now reported.
    assert status["context"]["missing"] == ["offer"]
    fields = status["context"]["fields"]
    assert fields["brand"]["source"] == "canonical"
    assert fields["voice"]["source"] == "discovered"
    assert fields["voice"]["discovered_path"] == "reference/core/voice.md"
    assert fields["audience"]["discovered_path"] == "reference/core/audience.md"
    # The canonical path keeps its meaning even here: it is where an answer would be written.
    assert fields["voice"]["path"] == "business/brand/voice.md"


def test_an_empty_folder_that_is_not_a_brain_still_reports_nothing_found(tmp_path: Path) -> None:
    """The case that must not change. An empty folder had no answers and still has none."""
    root = tmp_path / "blank"
    root.mkdir()

    status = status_repo(root)

    assert status["repo_state"] == "absent"
    assert status["ok"] is False
    assert status["next_action"]["id"] == "run-setup"
    assert status["context"]["ready"] is False
    assert status["context"]["missing"] == ["brand", "voice", "audience", "offer"]
    assert [entry["source"] for entry in status["context"]["fields"].values()] == ["missing"] * 6


def test_a_placeholder_in_a_folder_that_is_not_a_brain_never_answers_for_a_field(
    tmp_path: Path,
) -> None:
    """Reporting a stub as an answer is worse than the question it saves.

    Telling an operator their brand is documented when the file says ``TODO`` is the failure
    this whole path exists to avoid, and it has shipped once already. Both shapes it takes
    are here: a file of unanswered prompts, and a folder map that says the folder is empty.
    """
    root = tmp_path / "material"
    (root / "business/brand").mkdir(parents=True)
    (root / "business/brand/brand.md").write_text(
        "# Brand\n\n- TODO: what we stand for\n- TODO: who we are not for\n",
        encoding="utf-8",
    )
    (root / "business/brand/voice.md").write_text(
        "# Voice\n\nTODO: describe the tone, then list the words we never use.\n",
        encoding="utf-8",
    )
    (root / "business/audience").mkdir(parents=True)
    (root / "business/audience/README.md").write_text(
        "# audience\n\nOne file per segment in here. Nothing has been written yet — this "
        "folder is a map, not an answer, and it stays that way until someone fills it.\n",
        encoding="utf-8",
    )

    context = status_repo(root)["context"]

    assert context["ready"] is False
    assert context["missing"] == ["brand", "voice", "audience", "offer"]
    assert [entry["source"] for entry in context["fields"].values()] == ["missing"] * 6


def test_doctor_on_a_folder_that_is_not_a_brain_checks_the_home_install(
    tmp_path: Path, monkeypatch
) -> None:
    """No brain here means doctor answers for ``mos install``, not for the folder.

    It reads the home runtime directories, not ``<folder>/.claude/skills``: a fresh install
    with the nine skills wired at home is healthy and points at onboarding, and one without
    them is not and points back at install. ``context_ready`` still reports what the folder
    holds; ``ok`` does not read it.
    """
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    root = tmp_path / "material"
    root.mkdir()
    _material_only(root)

    report = doctor_repo(root)
    assert report["ok"] is False
    assert report["next_action"]["id"] == "run-install"
    assert [item["code"] for item in report["findings"]] == ["runtime-not-ready"]

    from marketing_os.core.skills import RUNTIME_DIRS, apply_sync, global_manifest, plan_sync

    for runtime in RUNTIME_DIRS:
        actions, findings = plan_sync(home, runtime, manifest_path=global_manifest(home))
        assert not findings
        apply_sync(actions, global_manifest(home))

    report = doctor_repo(root)
    assert report["ok"] is True
    assert report["findings"] == []
    assert report["next_action"]["id"] == "run-onboard"
    assert report["checks"]["structure"] is False
    assert report["checks"]["runtime_wiring"] is True
    assert report["repo_state"] == "absent"
    assert report["runtimes"]["claude"]["skill_dir"].startswith(str(home.resolve()))


def test_a_discovered_answer_downgrades_its_missing_canonical_file_to_a_warning(
    tmp_path: Path,
) -> None:
    """Doctor and status read one brain and must give one verdict on it.

    Validation reads directories, so a canonical context file that is not there is a
    ``missing-file`` error to it, while the context scan beside it has just found the answer
    that file is for. The finding is downgraded to a ``file-discovered`` warning that keeps
    both paths. A required file that is not a context field (``goals.md``) is nobody's
    discovery and stays the error it was.
    """
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    _non_canonical_context(root)
    for relative in (
        "business/brand/brand.md",
        "business/brand/voice.md",
        "business/audience/primary.md",
        "business/strategy/goals.md",
    ):
        (root / relative).unlink()

    status = status_repo(root)
    doctor = doctor_repo(root)
    assert doctor["findings"] == status["findings"]
    assert status["context"]["ready"] is True
    downgraded = [item for item in status["findings"] if item["code"] == "file-discovered"]
    assert [(item["severity"], item["path"], item["discovered_path"]) for item in downgraded] == [
        ("warning", "business/brand/brand.md", "business/brand/positioning/positioning.md"),
        ("warning", "business/brand/voice.md", "reference/core/voice.md"),
        ("warning", "business/audience/primary.md", "reference/core/audience.md"),
    ]
    assert all("reference/core/voice.md" in item["message"] for item in downgraded[1:2])
    still_missing = [item for item in status["findings"] if item["code"] == "missing-file"]
    assert [(item["severity"], item["path"]) for item in still_missing] == [
        ("error", "business/strategy/goals.md")
    ]
    assert doctor["checks"]["structure"] is False
    assert doctor["ok"] is False

    # Put the one genuine error right and the verdicts line up: the three discovered
    # answers no longer count against the structure they were never a fault of.
    (root / "business/strategy/goals.md").write_text("# Goals\n", encoding="utf-8")
    status = status_repo(root)
    doctor = doctor_repo(root)
    assert not any(item["code"] == "missing-file" for item in status["findings"])
    assert status["ok"] is True
    assert status["repo_state"] == "ready"
    assert doctor["checks"] == {
        "structure": True,
        "runtime_wiring": True,
        "context_ready": True,
    }
    assert doctor["ok"] is True
    # Validate is the narrower, canonical-path measure and keeps saying the files are absent.
    validation = validate_repo(root)
    assert sorted(
        item["path"] for item in validation["findings"] if item["code"] == "missing-file"
    ) == ["business/audience/primary.md", "business/brand/brand.md", "business/brand/voice.md"]


def test_a_canonical_brain_reports_nothing_discovered_and_the_findings_are_validate_s(
    tmp_path: Path,
) -> None:
    """Nothing was discovered, so nothing is downgraded: the findings are validate's, verbatim."""
    root = tmp_path / "brain"
    setup_repo(root, "Example Business", "all", mode="in-house", apply=True)
    _complete_context(root)
    status = status_repo(root)
    doctor = doctor_repo(root)
    assert status["context"]["ready"] is True
    assert not any(
        entry["source"] == "discovered" for entry in status["context"]["fields"].values()
    )
    assert doctor["findings"] == status["findings"] == validate_repo(root)["findings"]
    assert not any(item["code"] == "file-discovered" for item in doctor["findings"])
    assert not any("discovered_path" in item for item in doctor["findings"])
    assert doctor["checks"]["structure"] is True
