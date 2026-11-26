from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest
from pydantic import ValidationError

from core.clock import VirtualClock
from core.ports import DomainError
from core.schemas import Command
from modules.storage.store import SQLiteStore


@pytest.fixture
def store(tmp_path):
    instance = SQLiteStore(tmp_path / "match.db", VirtualClock())
    yield instance
    instance.close()


def send(store, action, payload=None, *, command_id=None, revision=None):
    current = store.current()
    command = Command(action=action, payload=payload or {},
                      expected_revision=revision if revision is not None else (current["revision"] if current else 0),
                      **({"command_id": command_id} if command_id else {}))
    return store.execute(None if action == "create" else current["match_id"], command, "test-operator")


def start(store, **setup):
    send(store, "create", setup)
    return send(store, "start")


def test_full_match_clock_corrections_and_export(store):
    start(store)
    store.clock.advance(70)
    goal = send(store, "manual_goal", {"team": "orange"})["event"]["payload"]["goal_id"]
    send(store, "pause")
    store.clock.advance(200)
    assert store.current()["elapsed_seconds"] == 70
    send(store, "resume")
    store.clock.advance(10)
    send(store, "manual_goal", {"team": "green"})
    send(store, "end")
    send(store, "undo_goal", {"goal_id": goal})
    snapshot = store.current()
    assert snapshot["score"] == {"orange": 0, "green": 1}
    assert snapshot["elapsed_seconds"] == 80
    export = store.export(snapshot["match_id"])
    assert export == store.export(snapshot["match_id"])
    assert [e["revision"] for e in export["events"]] == list(range(1, 9))
    assert export["events"][-1]["payload"]["correction"] == "goal_undone"
    assert export["events"][2]["payload"]["active"] is True
    assert snapshot["goals"][0]["active"] is False


def test_retry_survives_later_edits_without_recounting(store):
    start(store)
    revision = store.current()["revision"]
    result = send(store, "manual_goal", {"team": "orange"}, command_id="retry-me", revision=revision)
    send(store, "manual_goal", {"team": "green"})
    duplicate = send(store, "manual_goal", {"team": "orange"}, command_id="retry-me", revision=revision)
    assert duplicate["duplicate"] is True
    assert duplicate["event"] == result["event"]
    assert store.current()["score"] == {"orange": 1, "green": 1}
    with pytest.raises(DomainError, match="different request"):
        send(store, "manual_goal", {"team": "green"}, command_id="retry-me", revision=revision)


def test_concurrent_commands_have_one_winner(store):
    start(store)
    revision = store.current()["revision"]

    def attempt(team):
        try:
            return send(store, "manual_goal", {"team": team}, revision=revision)
        except DomainError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ["orange", "green"]))
    assert sum(isinstance(r, DomainError) for r in results) == 1
    assert sum(store.current()["score"].values()) == 1


def test_event_failure_rolls_back_score_and_command(store):
    start(store)
    before = store.export(store.current()["match_id"])
    store.db.executescript("CREATE TRIGGER simulate_full_disk BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'disk full'); END;")
    with pytest.raises(sqlite3.IntegrityError):
        send(store, "manual_goal", {"team": "orange"}, command_id="failed")
    assert before == store.export(store.current()["match_id"])
    assert store.db.execute("SELECT COUNT(*) FROM commands WHERE command_id='failed'").fetchone()[0] == 0
    store.db.execute("DROP TRIGGER simulate_full_disk")
    send(store, "manual_goal", {"team": "orange"}, command_id="failed")
    assert store.current()["score"]["orange"] == 1


def test_restart_requires_clock_reconciliation_and_keeps_idempotency(tmp_path):
    path = tmp_path / "restart.db"
    original = SQLiteStore(path, VirtualClock())
    start(original)
    original.clock.advance(40)
    revision = original.current()["revision"]
    send(original, "manual_goal", {"team": "orange"}, command_id="saved", revision=revision)
    original.clock.advance(25)
    original.close()
    restored = SQLiteStore(path, VirtualClock())
    try:
        state = restored.current()
        assert state["score"]["orange"] == 1
        assert state["elapsed_seconds"] == 40
        assert state["status"] == "interrupted"
        assert state["clock_reconciliation_required"] is True
        with pytest.raises(DomainError):
            send(restored, "resume")
        assert send(restored, "manual_goal", {"team": "orange"}, command_id="saved", revision=revision)["duplicate"]
        send(restored, "reconcile_clock", {"elapsed_seconds": 65})
        assert restored.current()["status"] == "paused"
        send(restored, "resume")
        restored.clock.advance(5)
        assert restored.current()["elapsed_seconds"] == 70
    finally:
        restored.close()


def test_paused_clock_survives_restart(tmp_path):
    path = tmp_path / "paused.db"
    first = SQLiteStore(path, VirtualClock())
    start(first)
    first.clock.advance(12)
    send(first, "pause")
    first.close()
    second = SQLiteStore(path, VirtualClock())
    try:
        assert second.current()["status"] == "paused"
        assert second.current()["elapsed_seconds"] == 12
        assert not second.current()["clock_reconciliation_required"]
    finally:
        second.close()


def test_second_process_owner_is_rejected(store, tmp_path):
    with pytest.raises(RuntimeError, match="already has an owner"):
        SQLiteStore(tmp_path / "match.db", VirtualClock())


def test_event_records_are_immutable(store):
    start(store)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.db.execute("DELETE FROM events")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.db.execute("UPDATE events SET body='{}'")


def test_pending_candidates_never_time_out_to_goals(store):
    start(store)
    send(store, "create_candidate", {"candidate_id": "impact-1", "goal_end": "goal_b", "reason": "Uncertain impact"})
    store.clock.advance(60)
    assert store.current()["score"] == {"orange": 0, "green": 0}
    assert store.current()["candidates"][0]["status"] == "pending_review"
    send(store, "confirm_candidate", {"candidate_id": "impact-1"})
    assert store.current()["score"]["orange"] == 1
    with pytest.raises(DomainError):
        send(store, "confirm_candidate", {"candidate_id": "impact-1"})


def test_side_changes_and_end_resolve_candidate_boundaries(store):
    start(store)
    send(store, "pause")
    send(store, "swap_ends")
    send(store, "resume")
    send(store, "create_candidate", {"candidate_id": "c1", "goal_end": "goal_b", "reason": "Test"})
    assert store.current()["candidates"][0]["team"] == "green"
    send(store, "pause")
    with pytest.raises(DomainError):
        send(store, "swap_ends")
    with pytest.raises(DomainError):
        send(store, "confirm_candidate", {"candidate_id": "c1"})
    send(store, "end")
    assert store.current()["candidates"][0]["status"] == "unresolved"


def test_roster_attribution_and_own_goals(store):
    start(store, players=[{"id": "a", "name": "A", "team": "orange", "bib": 9},
                          {"id": "b", "name": "B", "team": "green", "bib": 9}])
    with pytest.raises(DomainError, match="Scorer team"):
        send(store, "manual_goal", {"team": "orange", "scorer_id": "b"})
    result = send(store, "manual_goal", {"team": "orange", "scorer_id": "b", "own_goal": True})
    goal_id = result["event"]["payload"]["goal_id"]
    send(store, "attribute_goal", {"goal_id": goal_id, "scorer_id": "a"})
    assert store.current()["score"]["orange"] == 1
    assert store.current()["goals"][0]["scorer_id"] == "a"
    with pytest.raises(DomainError):
        send(store, "attribute_goal", {"goal_id": goal_id, "scorer_id": "a", "assist_id": "a"})


@pytest.mark.parametrize("action", ["manual_goal", "pause", "resume"])
def test_invalid_lifecycle_never_changes_score(store, action):
    send(store, "create")
    with pytest.raises(DomainError):
        send(store, action, {"team": "orange"} if action == "manual_goal" else {})
    assert store.current()["revision"] == 1


def test_new_match_requires_previous_match_end(store):
    start(store)
    with pytest.raises(DomainError):
        send(store, "create", revision=0)
    send(store, "end")
    old_id = store.current()["match_id"]
    send(store, "create", revision=0)
    assert store.current()["match_id"] != old_id
    assert store.export(old_id)["snapshot"]["status"] == "ended"


def test_invalid_payload_and_duplicate_bibs(store):
    with pytest.raises(ValidationError):
        send(store, "create", {"players": [
            {"id": "a", "name": "A", "team": "orange", "bib": 1},
            {"id": "b", "name": "B", "team": "orange", "bib": 1}]})
    assert store.current() is None
    start(store)
    with pytest.raises(ValidationError):
        send(store, "pause", {"ignored": "not allowed"})


def test_duration_reached_does_not_silently_end_match(store):
    start(store)
    store.clock.advance(1201)
    assert store.current()["duration_reached"]
    assert store.current()["status"] == "live"


def test_live_clock_includes_transaction_processing_time(store, monkeypatch):
    start(store)
    store.clock.advance(10)
    original_save = store._save

    def slow_save(state, event):
        original_save(state, event)
        store.clock.advance(0.5)

    monkeypatch.setattr(store, "_save", slow_save)
    send(store, "manual_goal", {"team": "orange"})
    assert store.current()["elapsed_seconds"] == 10.5
    store.clock.advance(10)
    send(store, "manual_goal", {"team": "green"})
    assert store.current()["elapsed_seconds"] == 21
