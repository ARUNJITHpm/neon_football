import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from core.clock import VirtualClock
from core.operations import OperationsSettings
from tests.operator.test_operator_api import AUTH, KEY, begin, current, incident, request


def test_operations_health_auth_age_unknown_resources_and_low_space(tmp_path):
    app = create_app(Settings(database_path=tmp_path/"score.db", operations=OperationsSettings(min_free_bytes=10**20)), operator_key=KEY, clock=VirtualClock())
    with TestClient(app) as client:
        assert client.get("/api/v1/operations/status").status_code == 401
        assert client.get("/api/v1/operations/status", headers={**AUTH, "Origin":"https://other.test"}).status_code == 403
        begin(client); incident(client)
        app.state.store.clock.advance(2)
        health = client.get("/api/v1/operations/status", headers=AUTH).json()
        assert health["integrity"]["ok"] and health["disk"]["low_space"] and health["state"] == "degraded"
        assert health["review"]["oldest_age_seconds"] == 2
        assert health["resource"]["temperature_celsius"] is None and not health["resource"]["temperature_memory_measured"]
        assert not health["automatic_scoring_enabled"] and health["scoring_available"]
        assert health["sensors"]["state"] == "not_connected" and len(health["config_sha256"]) == 64
        assert KEY not in json.dumps(health)


def test_detected_integrity_fault_quarantines_reads_and_writes(tmp_path):
    app = create_app(Settings(database_path=tmp_path/"score.db"), operator_key=KEY, clock=VirtualClock())
    with TestClient(app) as client:
        request(client, "create")
        state = current(client)
        state["score"]["orange"] = 99
        app.state.store.db.execute("UPDATE matches SET state=?", (json.dumps(state),))
        app.state.operations.last_check = float("-inf")
        health = client.get("/api/v1/operations/status", headers=AUTH).json()
        assert health["state"] == "quarantined" and not health["scoring_available"]
        assert not health["integrity"]["ok"]
        assert client.get("/api/v1/matches/current").status_code == 503
        command = dict(command_id="blocked", expected_revision=1, action="start", payload={})
        assert client.post(f"/api/v1/matches/{state['match_id']}/commands", headers=AUTH, json=command).status_code == 503
        # Repairing arbitrary JSON doesn't clear the latch within this running host.
        state["score"]["orange"] = 0
        app.state.store.db.execute("UPDATE matches SET state=?", (json.dumps(state),))
        assert client.get("/api/v1/operations/status", headers=AUTH).json()["state"] == "quarantined"
