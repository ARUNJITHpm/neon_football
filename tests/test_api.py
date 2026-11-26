from uuid import uuid4
from urllib.parse import quote

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.settings import Settings
from core.clock import VirtualClock


KEY = "test-operator-key-at-least-16"
AUTH = {"Authorization": f"Bearer {KEY}", "X-Operator-Name": "test"}


@pytest.fixture
def client(tmp_path):
    application = create_app(Settings(database_path=tmp_path / "api.db"), operator_key=KEY, clock=VirtualClock())
    with TestClient(application) as instance:
        yield instance


def body(action, revision=0, payload=None):
    return {"command_id": str(uuid4()), "expected_revision": revision, "action": action, "payload": payload or {}}


def test_authentication_and_origins(client):
    assert client.post("/api/v1/matches", json=body("create")).status_code == 401
    assert client.post("/api/v1/operator/check", headers=AUTH).status_code == 200
    assert client.post("/api/v1/operator/check", headers={**AUTH, "Origin": "https://elsewhere.example"}).status_code == 403
    assert client.post("/api/v1/operator/check", headers={**AUTH, "Origin": "http://testserver"}).status_code == 200


def test_match_http_lifecycle_retries_conflicts_and_export(client):
    creation = body("create")
    result = client.post("/api/v1/matches", json=creation, headers=AUTH)
    assert result.status_code == 201
    match = result.json()["snapshot"]
    match_id = match["match_id"]
    endpoint = f"/api/v1/matches/{match_id}/commands"
    assert client.post(endpoint, json=body("start", 1), headers=AUTH).status_code == 200
    goal = body("manual_goal", 2, {"team": "orange"})
    assert client.post(endpoint, json=goal, headers=AUTH).json()["snapshot"]["score"]["orange"] == 1
    assert client.post(endpoint, json=goal, headers=AUTH).json()["duplicate"]
    assert client.post(endpoint, json=body("manual_goal", 2, {"team": "green"}), headers=AUTH).status_code == 409
    assert client.get(f"/api/v1/matches/{match_id}/export").status_code == 401
    export = client.get(f"/api/v1/matches/{match_id}/export", headers=AUTH)
    assert export.status_code == 200
    assert len(export.json()["events"]) == 3
    assert "attachment" in export.headers["content-disposition"]


def test_validation_and_unknown_matches(client):
    assert client.post("/api/v1/matches", json=body("create", payload={"duration_seconds": -1}), headers=AUTH).status_code == 422
    assert client.get("/api/v1/matches/unknown").status_code == 404
    assert client.post("/api/v1/matches", json=body("start"), headers=AUTH).status_code == 422


def test_websocket_snapshot_and_reconnect(client):
    with client.websocket_connect("/ws/matches/current") as websocket:
        assert websocket.receive_json() == {"type": "snapshot", "match": None}
        result = client.post("/api/v1/matches", json=body("create"), headers=AUTH)
        websocket.send_text("refresh")
        assert websocket.receive_json()["match"]["match_id"] == result.json()["snapshot"]["match_id"]
    with client.websocket_connect("/ws/matches/current") as websocket:
        assert websocket.receive_json()["match"]["revision"] == 1


def test_app_lifespan_can_restart_same_instance(tmp_path):
    application = create_app(Settings(database_path=tmp_path / "restart.db"), operator_key=KEY)
    with TestClient(application) as first:
        first.post("/api/v1/matches", json=body("create"), headers=AUTH)
    with TestClient(application) as second:
        assert second.get("/api/v1/matches/current").json()["match"]["revision"] == 1


def test_browser_headers(client):
    response = client.get("/health")
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_unicode_operator_audit_label(client):
    name = "അരുൺ"
    response = client.post("/api/v1/matches", json=body("create"), headers={**AUTH, "X-Operator-Name": quote(name)})
    assert response.status_code == 201
    assert response.json()["event"]["actor"] == name


def test_local_browser_assets_are_served(client):
    for path in ("/operator", "/scoreboard", "/static/operator.js", "/static/common.js", "/static/style.css", "/static/fonts/DejaVuSans-Bold.ttf"):
        assert client.get(path).status_code == 200
