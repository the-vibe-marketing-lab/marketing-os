import datetime
import json
import shutil
from pathlib import Path

import pytest

from marketing_os.ui import registry
from marketing_os.ui import state as ui_state


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    directory = tmp_path / "mos-home"
    monkeypatch.setenv(ui_state.HOME_ENV, str(directory))
    return directory


def _brain(root: Path, name: str, mode: str = "solo") -> Path:
    (root / ".mos").mkdir(parents=True, exist_ok=True)
    (root / ".mos" / "config.yaml").write_text(
        json.dumps({"business_name": name, "mode": mode}), encoding="utf-8"
    )
    return root


def _legacy_brain(root: Path, name: str) -> Path:
    (root / ".mos").mkdir(parents=True, exist_ok=True)
    (root / ".mos" / "config.yaml").write_text(f"mode: agency\nname: {name}\n", encoding="utf-8")
    (root / "BRAIN.md").write_text("# Mine\n", encoding="utf-8")
    (root / "business").mkdir(exist_ok=True)
    return root


def _seed(home: Path, brains: list[dict]) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    path = home / registry.REGISTRY_FILE
    path.write_text(json.dumps({"schema": registry.REGISTRY_SCHEMA, "brains": brains}))
    return path


def _paths(brains: list[dict]) -> list[str]:
    return [brain["path"] for brain in brains]


# --- location and loading ------------------------------------------------------------


def test_registry_lives_beside_the_state_file(home: Path) -> None:
    assert registry.registry_path() == home / "brains.json"
    assert registry.registry_path().parent == ui_state.state_path().parent


def test_missing_file_loads_as_an_empty_registry(home: Path) -> None:
    assert registry.load() == {"schema": registry.REGISTRY_SCHEMA, "brains": []}
    assert not home.exists()


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        "[]",
        '"a string"',
        '{"schema": "mos.brains.v1", "brains": "nope"}',
        b"\xff\xfe".decode("latin-1"),
    ],
)
def test_malformed_file_loads_as_an_empty_registry(home: Path, text: str) -> None:
    home.mkdir(parents=True)
    (home / "brains.json").write_text(text, encoding="utf-8")
    assert registry.load()["brains"] == []


def test_load_drops_junk_entries_and_duplicate_spellings(home: Path, tmp_path: Path) -> None:
    folder = tmp_path / "one"
    _seed(
        home,
        [
            {"path": str(folder), "name": "One", "mode": "solo", "last_opened": "x"},
            {"path": str(tmp_path / "sub" / ".." / "one"), "name": "Dup"},
            {"path": "", "name": "Empty"},
            {"name": "No path"},
            "not a mapping",
            {"path": str(tmp_path / "two"), "name": 42, "mode": 7, "last_opened": 1},
        ],
    )
    brains = registry.load()["brains"]
    assert _paths(brains) == [str(folder), str(tmp_path / "two")]
    assert brains[0]["name"] == "One"
    # Wrong types are coerced, and a nameless entry is named after its folder.
    assert brains[1] == {
        "path": str(tmp_path / "two"),
        "name": "two",
        "mode": None,
        "last_opened": None,
    }


# --- remember and forget ---------------------------------------------------------------


def test_remember_then_forget_round_trips(home: Path, tmp_path: Path) -> None:
    brain = _brain(tmp_path / "acme", "Acme", "agency")
    before = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)

    written = registry.remember(brain)

    assert written["schema"] == registry.REGISTRY_SCHEMA
    assert len(written["brains"]) == 1
    entry = written["brains"][0]
    assert entry["path"] == str(brain)
    assert entry["name"] == "Acme"
    assert entry["mode"] == "agency"
    opened = datetime.datetime.fromisoformat(entry["last_opened"])
    assert opened.tzinfo is not None and opened.utcoffset() == datetime.timedelta(0)
    assert opened >= before
    assert registry.load() == written
    on_disk = json.loads((home / "brains.json").read_text(encoding="utf-8"))
    assert on_disk == written

    after = registry.forget(brain)

    assert after["brains"] == []
    assert registry.load()["brains"] == []


def test_forgetting_an_unknown_path_writes_nothing(home: Path, tmp_path: Path) -> None:
    assert registry.forget(tmp_path / "never")["brains"] == []
    assert not (home / "brains.json").exists()


def test_remember_dedupes_every_spelling_of_one_folder(
    home: Path, tmp_path: Path, monkeypatch
) -> None:
    _brain(tmp_path / "a", "A")
    monkeypatch.chdir(tmp_path)

    registry.remember("./a")
    registry.remember("a")
    registry.remember(tmp_path / "a")
    registry.remember(str(tmp_path / "other" / ".." / "a") + "/")

    brains = registry.load()["brains"]
    assert _paths(brains) == [str(tmp_path / "a")]
    assert len(registry.known_brains([])) == 1


def test_remember_refreshes_name_and_mode_from_the_folder_when_not_given(
    home: Path, tmp_path: Path
) -> None:
    brain = _brain(tmp_path / "acme", "Acme", "solo")

    registry.remember(brain, name="Custom", mode="agency")
    assert registry.load()["brains"][0]["name"] == "Custom"
    assert registry.load()["brains"][0]["mode"] == "agency"

    registry.remember(brain)
    entry = registry.load()["brains"][0]
    assert entry["name"] == "Acme"
    assert entry["mode"] == "solo"


def test_remember_keeps_the_stored_identity_when_the_folder_is_gone(
    home: Path, tmp_path: Path
) -> None:
    brain = _brain(tmp_path / "acme", "Acme", "agency")
    registry.remember(brain)
    shutil.rmtree(brain)

    entry = registry.remember(brain)["brains"][0]

    assert entry["name"] == "Acme"
    assert entry["mode"] == "agency"


def test_remember_names_a_plain_folder_after_itself(home: Path, tmp_path: Path) -> None:
    folder = tmp_path / "not-a-brain"
    folder.mkdir()
    entry = registry.remember(folder)["brains"][0]
    assert entry["name"] == "not-a-brain"
    assert entry["mode"] is None


def test_remember_rejects_an_empty_path(home: Path) -> None:
    with pytest.raises(ValueError):
        registry.remember("   ")


def test_remember_updates_last_opened_on_every_call(home: Path, tmp_path: Path) -> None:
    brain = _brain(tmp_path / "acme", "Acme")
    _seed(
        home,
        [
            {
                "path": str(brain),
                "name": "Acme",
                "mode": "solo",
                "last_opened": "2020-01-01T00:00:00+00:00",
            }
        ],
    )
    entry = registry.remember(brain)["brains"][0]
    assert entry["last_opened"] > "2020-01-01T00:00:00+00:00"


# --- known_brains ------------------------------------------------------------------


def test_missing_folder_stays_listed_as_not_found(home: Path, tmp_path: Path) -> None:
    brain = _brain(tmp_path / "acme", "Acme", "agency")
    registry.remember(brain)
    shutil.rmtree(brain)

    brains = registry.known_brains([])

    assert len(brains) == 1
    assert brains[0]["exists"] is False
    assert brains[0]["name"] == "Acme"
    assert brains[0]["mode"] == "agency"
    assert brains[0]["legacy"] is False
    assert brains[0]["attachable"] is False
    assert brains[0]["is_brain"] is False
    assert brains[0]["last_opened"] is not None
    assert registry.load()["brains"], "a missing brain is never auto-forgotten"


def test_a_folder_that_lost_its_brain_is_listed_as_not_a_brain(home: Path, tmp_path: Path) -> None:
    """The folder is still there, so it is not "not found"; but its config is gone, so the
    page must not draw it as a healthy brain the operator can open."""
    brain = _brain(tmp_path / "acme", "Acme", "agency")
    registry.remember(brain)
    shutil.rmtree(brain / ".mos")

    [entry] = registry.known_brains([])

    assert entry["exists"] is True
    assert entry["is_brain"] is False
    assert entry["attachable"] is False
    assert entry["name"] == "Acme" and entry["mode"] == "agency", "the stored identity stays"


def test_known_brains_carries_the_documented_fields(home: Path, tmp_path: Path) -> None:
    brain = _brain(tmp_path / "acme", "Acme", "agency")
    registry.remember(brain)
    (brain / ".mos" / "config.yaml").write_text(
        json.dumps({"business_name": "Acme Renamed", "mode": "solo"}), encoding="utf-8"
    )

    [entry] = registry.known_brains([])

    assert set(entry) == {
        "path",
        "name",
        "mode",
        "legacy",
        "attachable",
        "is_brain",
        "exists",
        "last_opened",
    }
    assert entry["is_brain"] is True
    # Name and mode are re-read from the folder, not served from the stored record.
    assert entry["name"] == "Acme Renamed"
    assert entry["mode"] == "solo"
    assert entry["exists"] is True


def test_scan_of_the_first_place_merges_with_the_registry(home: Path, tmp_path: Path) -> None:
    desktop = tmp_path / "Desktop"
    opened = _brain(desktop / "opened", "Opened")
    _brain(desktop / "fresh", "Fresh")
    _legacy_brain(desktop / "old", "Legacy Lab")
    (desktop / "plain").mkdir()
    _brain(desktop / "fresh" / "nested", "Too Deep")
    registry.remember(opened)
    places = [{"path": str(desktop), "kind": "desktop"}]

    brains = {brain["path"]: brain for brain in registry.known_brains(places)}

    assert set(brains) == {str(opened), str(desktop / "fresh"), str(desktop / "old")}
    assert brains[str(opened)]["last_opened"] is not None
    assert brains[str(desktop / "fresh")]["last_opened"] is None
    assert brains[str(desktop / "fresh")]["exists"] is True
    assert brains[str(desktop / "old")]["legacy"] is True
    assert brains[str(desktop / "old")]["attachable"] is True
    assert brains[str(desktop / "old")]["name"] == "Legacy Lab"


def test_only_the_first_place_is_scanned(home: Path, tmp_path: Path) -> None:
    desktop = tmp_path / "Desktop"
    operator_home = tmp_path / "home"
    _brain(desktop / "seen", "Seen")
    _brain(operator_home / "unseen", "Unseen")
    places = [
        {"path": str(desktop), "kind": "desktop"},
        {"path": str(operator_home), "kind": "home"},
    ]

    assert _paths(registry.known_brains(places)) == [str(desktop / "seen")]
    assert registry.known_brains([]) == []


def test_known_brains_survives_a_broken_places_seam(home: Path, tmp_path: Path) -> None:
    brain = _brain(tmp_path / "acme", "Acme")
    registry.remember(brain)

    def exploding():
        raise RuntimeError("no places today")
        yield  # makes this a generator, so the error surfaces inside known_brains

    assert _paths(registry.known_brains(exploding())) == [str(brain)]
    assert _paths(registry.known_brains([None, "junk"])) == [str(brain)]
    assert _paths(registry.known_brains([{"path": str(tmp_path / "nowhere")}])) == [str(brain)]


def test_known_brains_orders_existing_then_by_name_never_by_recency(
    home: Path, tmp_path: Path
) -> None:
    for name in ("Bravo", "alpha", "Charlie", "Delta", "Echo"):
        _brain(tmp_path / name.lower(), name)
    _seed(
        home,
        [
            {
                "path": str(tmp_path / "echo"),
                "name": "Echo",
                "last_opened": "2026-01-01T00:00:00+00:00",
            },
            {
                "path": str(tmp_path / "delta"),
                "name": "Delta",
                "last_opened": "2026-06-01T00:00:00+00:00",
            },
            {
                "path": str(tmp_path / "gone"),
                "name": "Gone",
                "last_opened": "2026-12-01T00:00:00+00:00",
            },
            {"path": str(tmp_path / "charlie"), "name": "Charlie"},
            {"path": str(tmp_path / "bravo"), "name": "Bravo"},
            {"path": str(tmp_path / "alpha"), "name": "alpha"},
        ],
    )

    names = [brain["name"] for brain in registry.known_brains([])]

    # By name regardless of when each was opened, so pressing one never moves it, and the
    # missing one last even though it was opened most recently of all.
    assert names == ["alpha", "Bravo", "Charlie", "Delta", "Echo", "Gone"]


# --- durability ------------------------------------------------------------------------


def test_registry_is_capped_by_dropping_the_oldest(home: Path, tmp_path: Path) -> None:
    seeded = [
        {
            "path": str(tmp_path / f"brain-{index:03d}"),
            "name": f"Brain {index}",
            "last_opened": f"2026-01-01T00:{index // 60:02d}:{index % 60:02d}+00:00",
        }
        for index in range(registry.MAX_ENTRIES)
    ]
    _seed(home, seeded)
    newest = _brain(tmp_path / "newest", "Newest")

    written = registry.remember(newest)

    paths = _paths(written["brains"])
    assert len(paths) == registry.MAX_ENTRIES
    assert paths[0] == str(newest)
    assert str(tmp_path / "brain-000") not in paths, "the oldest last_opened is dropped"
    assert str(tmp_path / "brain-001") in paths
    assert len(registry.load()["brains"]) == registry.MAX_ENTRIES


def test_a_failed_write_leaves_the_old_file_intact_and_no_partial_file(
    home: Path, tmp_path: Path, monkeypatch
) -> None:
    first = _brain(tmp_path / "first", "First")
    registry.remember(first)
    original = (home / "brains.json").read_bytes()

    def refuse(src, dst):
        raise OSError("disk full")

    # atomic_write's last step is the rename; failing it is what a crash mid-write looks like.
    monkeypatch.setattr("marketing_os.core.atomic.os.replace", refuse)

    with pytest.raises(OSError):
        registry.remember(_brain(tmp_path / "second", "Second"))

    assert (home / "brains.json").read_bytes() == original
    assert [p.name for p in home.iterdir()] == ["brains.json"], "no temporary file is left"
    assert _paths(registry.load()["brains"]) == [str(first)]


def test_registry_file_is_valid_pretty_json(home: Path, tmp_path: Path) -> None:
    registry.remember(_brain(tmp_path / "acme", "Acme"))
    text = (home / "brains.json").read_text(encoding="utf-8")
    assert text.endswith("\n")
    payload = json.loads(text)
    assert payload["schema"] == "mos.brains.v1"
    assert list(payload["brains"][0]) == ["last_opened", "mode", "name", "path"]
