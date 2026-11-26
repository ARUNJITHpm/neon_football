import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.attribution import DummyAttribution
from app.main import create_app
from app.settings import Settings
from core.clock import VirtualClock
from core.ports import DomainError
from core.schemas import Command
from modules.storage.maintenance import backup_database, inspect_database, restore_database
from modules.storage.report import match_report
from modules.storage.store import SQLiteStore
from tests.operator.test_operator_api import AUTH, KEY, current, request
from tools.build_attribution_fixture import PLAYERS, ACTIVE


def send(store, action, payload=None, *, command_id=None, revision=None):
    state = store.current()
    cmd = Command(command_id=command_id or str(uuid4()), action=action, payload=payload or {},
        expected_revision=revision if revision is not None else state["revision"] if state else 0)
    prepared = DummyAttribution().prepare(state["match_id"], cmd, state) if action == "demo_attribution" else None
    return store.execute(state["match_id"] if state else None, cmd, "operator", prepared_attribution=prepared)


def begin(store):
    send(store, "create", dict(players=PLAYERS, active_player_ids=ACTIVE)); send(store, "start")


def proposal(store, goal, scenario="assist"):
    return send(store, "demo_attribution", dict(goal_id=goal, scenario=scenario))["snapshot"]["attribution_suggestions"][-1]


def reference(item): return dict(goal_id=item["goal_id"], suggestion_id=item["suggestion_id"])


def test_late_attribution_substitution_and_durable_backup(tmp_path):
    path = tmp_path / "score.db"
    store = SQLiteStore(path, VirtualClock())
    try:
        begin(store)
        goal = send(store, "manual_goal", dict(team="green"))["event"]["payload"]
        assert goal["scorer_id"] is None and store.current()["score"]["green"] == 1
        send(store, "substitute_player", dict(outgoing_id="green-7", incoming_id="green-15"))
        item = proposal(store, goal["goal_id"])
        assert item["submission"]["suggestion"]["scorer_id"] == "green-7"
        assert store.current()["goals"][0]["scorer_id"] is None
        assert item["submission"]["sequence"]["roster"]["revision"] == 0
        send(store, "accept_attribution", reference(item), command_id="apply-once")
        state = store.current()
        assert state["score"] == dict(orange=0, green=1)
        assert (state["goals"][0]["scorer_id"], state["goals"][0]["assist_id"]) == ("green-7", "green-11")
        assert state["goals"][0]["attribution_revision"] == 1
        next_goal = send(store, "manual_goal", dict(team="green"))["event"]["payload"]
        next_item = proposal(store, next_goal["goal_id"], "direct")
        assert next_item["submission"]["suggestion"]["scorer_id"] == "green-11"
        assert next_item["submission"]["sequence"]["roster"]["revision"] == 1
        report = match_report(store.export(state["match_id"]))
        assert report["contains_dummy_attribution"] and report["score"]["green"] == 2
        assert report["goals"][0]["scorer_name"] == "Green Seven"
        assert store.integrity()["events"] == store.current()["revision"]
        backup_database(path, tmp_path / "backup"); restore_database(tmp_path / "backup", tmp_path / "restored.db")
        recovered = SQLiteStore(tmp_path / "restored.db", VirtualClock())
        try:
            assert recovered.current()["status"] == "interrupted"
            assert recovered.current()["attribution_suggestions"][-1]["status"] == "pending"
            assert recovered.current()["active_player_ids"] == state["active_player_ids"]
            assert recovered.integrity()["events"] == recovered.current()["revision"]
        finally: recovered.close()
    finally: store.close()


@pytest.mark.parametrize("resolution", ["manual", "newer", "reject", "undo"])
def test_resolved_suggestion_cannot_overwrite_operator_decision(tmp_path, resolution):
    store = SQLiteStore(tmp_path / "score.db", VirtualClock())
    try:
        begin(store); gid = send(store, "manual_goal", dict(team="green"))["event"]["payload"]["goal_id"]
        item = proposal(store, gid)
        if resolution == "manual": send(store, "attribute_goal", dict(goal_id=gid, scorer_id="green-11"))
        if resolution == "newer": proposal(store, gid, "direct")
        if resolution == "reject": send(store, "reject_attribution", reference(item))
        if resolution == "undo": send(store, "undo_goal", dict(goal_id=gid))
        with pytest.raises(DomainError): send(store, "accept_attribution", reference(item))
        assert store.integrity()["events"] == store.current()["revision"]
        assert store.current()["score"]["green"] == (0 if resolution == "undo" else 1)
    finally: store.close()


def test_unknown_own_goal_and_exact_retries(tmp_path):
    store = SQLiteStore(tmp_path / "score.db", VirtualClock())
    try:
        begin(store); gid = send(store, "manual_goal", dict(team="green"))["event"]["payload"]["goal_id"]
        item = proposal(store, gid, "uncertain")
        with pytest.raises(DomainError, match="uncertain"): send(store, "accept_attribution", reference(item))
        item = proposal(store, gid, "own_goal")
        revision = store.current()["revision"]
        send(store, "accept_attribution", reference(item), command_id="accept-once", revision=revision)
        send(store, "undo_goal", dict(goal_id=gid))
        result = send(store, "accept_attribution", reference(item), command_id="accept-once", revision=revision)
        assert result["duplicate"] and store.current()["score"]["green"] == 0
        report = match_report(store.export(store.current()["match_id"]))
        assert report["goals"][0]["own_goal"] and report["goals"][0]["assist_id"] is None
        assert store.integrity()["events"] == store.current()["revision"]
    finally: store.close()


@pytest.mark.parametrize("outgoing,incoming", [("green-15", "green-7"), ("green-7", "orange-9"), ("green-7", "green-11"), ("missing", "green-15")])
def test_invalid_substitutions_are_atomic(tmp_path, outgoing, incoming):
    store = SQLiteStore(tmp_path / "score.db", VirtualClock())
    try:
        begin(store); before = store.export(store.current()["match_id"])
        with pytest.raises(DomainError): send(store, "substitute_player", dict(outgoing_id=outgoing, incoming_id=incoming))
        assert store.export(store.current()["match_id"]) == before
    finally: store.close()


def test_evidence_disk_failure_rolls_back_and_integrity_detects_roster_tamper(tmp_path):
    path = tmp_path / "score.db"; store = SQLiteStore(path, VirtualClock())
    try:
        begin(store); gid = send(store, "manual_goal", dict(team="green"))["event"]["payload"]["goal_id"]
        before = store.export(store.current()["match_id"])
        store.db.executescript("CREATE TRIGGER simulate_full BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'full'); END;")
        with pytest.raises(Exception, match="full"): proposal(store, gid)
        assert store.export(store.current()["match_id"]) == before
        state = store.current(); state["goals"][0]["active_player_ids"] = []
        store.db.execute("UPDATE matches SET state=? WHERE id=?", (json.dumps(state), state["match_id"]))
        with pytest.raises(ValueError, match="Goal projection"): inspect_database(path)
    finally: store.close()


def test_private_api_operator_approval_and_public_redaction(tmp_path):
    app = create_app(Settings(database_path=tmp_path / "api.db"), operator_key=KEY, clock=VirtualClock())
    with TestClient(app) as client:
        assert request(client, "create", dict(players=PLAYERS, active_player_ids=ACTIVE)).status_code == 201
        assert request(client, "start").status_code == 200
        gid = request(client, "manual_goal", dict(team="green")).json()["event"]["payload"]["goal_id"]
        result = request(client, "demo_attribution", dict(goal_id=gid, scenario="assist"))
        assert result.status_code == 200, result.text
        item = result.json()["snapshot"]["attribution_suggestions"][-1]
        assert current(client)["goals"][0]["scorer_id"] is None
        mid = current(client)["match_id"]
        for headers, status in (({}, 401), ({**AUTH, "Origin": "https://foreign.example"}, 403)):
            assert client.post(f"/api/v1/matches/{mid}/commands", headers=headers, json=dict(action="accept_attribution", expected_revision=current(client)["revision"], payload=reference(item))).status_code == status
        stale = current(client)["revision"]
        assert request(client, "substitute_player", dict(outgoing_id="green-7", incoming_id="green-15")).status_code == 200
        assert request(client, "accept_attribution", reference(item), revision=stale).status_code == 409
        assert request(client, "accept_attribution", reference(item)).status_code == 200
        state = current(client)
        assert state["score"]["green"] == 1 and state["goals"][0]["assist_id"] == "green-11"
        public = client.get("/api/v1/matches/current").json()["match"]
        assert not {"attribution_suggestions", "active_player_ids", "roster_revision", "players", "goals"}.intersection(public)
        with client.websocket_connect("/ws/matches/current") as ws:
            public_ws = ws.receive_json()["match"]
            assert "attribution_suggestions" not in public_ws and "players" not in public_ws
        assert client.get(f"/api/v1/matches/{mid}/report", headers=AUTH).json()["contains_dummy_attribution"]


def test_dummy_attribution_disabled_configuration(tmp_path):
    app = create_app(Settings(database_path=tmp_path / "api.db", demo_review_enabled=False), operator_key=KEY, clock=VirtualClock())
    with TestClient(app) as client:
        request(client, "create", dict(players=PLAYERS)); request(client, "start")
        gid = request(client, "manual_goal", dict(team="green")).json()["event"]["payload"]["goal_id"]
        assert request(client, "demo_attribution", dict(goal_id=gid)).status_code == 422
        assert current(client)["score"]["green"] == 1


def test_candidate_keeps_incident_roster_and_scoring_team_across_substitution_and_ends(tmp_path):
    store = SQLiteStore(tmp_path / "score.db", VirtualClock())
    try:
        begin(store)
        send(store, "create_candidate", dict(candidate_id="incident", goal_end="goal_a", reason="manual evidence"))
        send(store, "substitute_player", dict(outgoing_id="green-7", incoming_id="green-15"))
        goal = send(store, "confirm_candidate", dict(candidate_id="incident"))["event"]["payload"]
        assert goal["roster_revision"] == 0 and "green-7" in goal["active_player_ids"]
        send(store, "pause"); send(store, "swap_ends")
        item = proposal(store, goal["goal_id"], "direct")
        assert item["submission"]["suggestion"]["scorer_id"] == "green-7"
        send(store, "accept_attribution", reference(item))
        assert store.current()["score"] == dict(orange=0, green=1)
        assert store.integrity()["events"] == store.current()["revision"]
    finally: store.close()


def test_omitted_active_roster_preserves_existing_create_retry_fingerprint(tmp_path):
    store = SQLiteStore(tmp_path / "score.db", VirtualClock())
    try:
        original = Command(command_id="old-create", action="create", expected_revision=0, payload=dict(players=PLAYERS))
        store.execute(None, original)
        explicit_null = original.model_copy(update=dict(payload=dict(players=PLAYERS, active_player_ids=None)))
        assert store.execute(None, explicit_null)["duplicate"]
        assert store.current()["active_player_ids"] == [p["id"] for p in PLAYERS]
    finally: store.close()
