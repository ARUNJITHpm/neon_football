from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from app.review import DummyReview, MEDIA
from app.settings import Settings
from core.clock import VirtualClock

KEY="operator-test-key-at-least-16"
AUTH={"Authorization":f"Bearer {KEY}","X-Operator-Name":"Test operator"}


@pytest.fixture
def client(tmp_path):
    app=create_app(Settings(database_path=tmp_path/"review.db"),operator_key=KEY,clock=VirtualClock())
    with TestClient(app) as client:
        yield client


def current(client):
    return client.get("/api/v1/operator/matches/current",headers=AUTH).json()["match"]


def request(client,action,payload=None,*,command_id=None,revision=None):
    snapshot=current(client)
    body=dict(command_id=command_id or str(uuid4()),action=action,payload=payload or {},
        expected_revision=revision if revision is not None else snapshot["revision"] if snapshot else 0)
    url=f"/api/v1/matches/{snapshot['match_id']}/commands" if snapshot else "/api/v1/matches"
    return client.post(url,json=body,headers=AUTH)


def begin(client):
    assert request(client,"create",dict(players=[dict(id="orange-9",name="Orange player",team="orange",bib=9),
        dict(id="green-7",name="Green player",team="green",bib=7)])).status_code==201
    assert request(client,"set_review_mode",dict(mode="demo_review")).status_code==200
    assert request(client,"start").status_code==200


def incident(client,scenario="observed",end="goal_a",**kwargs):
    result=request(client,"demo_incident",dict(goal_end=end,scenario=scenario),**kwargs)
    assert result.status_code==200,result.text
    return result.json()


def test_scripted_match_review_attribution_undo_expiry_export_and_report(client):
    begin(client)
    result=incident(client)
    candidate=result["snapshot"]["candidates"][0]
    assert candidate["status"]=="pending_review" and candidate["review"]["candidate"]["confirmation"]=="shadow_rule"
    assert current(client)["score"]==dict(orange=0,green=0)
    goal=request(client,"confirm_candidate",dict(candidate_id=candidate["candidate_id"])).json()["event"]["payload"]
    assert current(client)["score"]["green"]==1 and current(client)["restart_required"]
    assert request(client,"confirm_candidate",dict(candidate_id=candidate["candidate_id"])).status_code==409
    assert request(client,"attribute_goal",dict(goal_id=goal["goal_id"],scorer_id="green-7")).status_code==200
    assert request(client,"undo_goal",dict(goal_id=goal["goal_id"])).status_code==200
    assert current(client)["score"]==dict(orange=0,green=0)
    assert request(client,"restart_play").status_code==200
    second=incident(client,"net_contact","goal_b")["snapshot"]["candidates"][-1]
    assert request(client,"reject_candidate",dict(candidate_id=second["candidate_id"])).status_code==200
    expired=incident(client,"pending_clip")["snapshot"]["candidates"][-1]
    client.app.state.store.clock.advance(15)
    snapshot=current(client)
    assert snapshot["candidates"][-1]["status"]=="unresolved"
    assert snapshot["last_event"]["type"]=="candidate_expired"
    assert request(client,"confirm_candidate",dict(candidate_id=expired["candidate_id"])).status_code==409
    assert request(client,"end").status_code==200
    root=f"/api/v1/matches/{snapshot['match_id']}"
    report=client.get(root+"/report",headers=AUTH)
    assert report.status_code==200
    assert report.json()["goals"][0]["scorer_name"]=="Green player"
    assert not report.json()["goals"][0]["active"] and report.json()["contains_dummy_review"]
    text=client.get(root+"/report.txt",headers=AUTH).content
    client.app.state.store.clock.advance(100)
    assert client.get(root+"/report.txt",headers=AUTH).content==text
    assert report.content==client.get(root+"/report",headers=AUTH).content
    assert b"undone" in text
    exported=client.get(root+"/export",headers=AUTH).json()
    assert exported["snapshot"]["score"]==report.json()["score"]
    assert [e["revision"] for e in exported["events"]]==list(range(1,len(exported["events"])+1))


def test_public_snapshot_redaction_and_private_access(client):
    begin(client); result=incident(client)
    mid=result["snapshot"]["match_id"]
    public=client.get("/api/v1/matches/current").json()["match"]
    assert "candidates" not in public and "players" not in public and "goals" not in public
    assert public["last_event"]["event_id"]==result["event"]["event_id"]
    assert "candidates" not in client.get(f"/api/v1/matches/{mid}").json()
    for path in ("/api/v1/operator/matches/current","/api/v1/displays/status",f"/api/v1/matches/{mid}/report",f"/api/v1/matches/{mid}/events"):
        assert client.get(path).status_code==401
        assert client.get(path,headers={**AUTH,"Origin":"https://foreign.example"}).status_code==403
    assert len(current(client)["candidates"][0]["review"]["evidence"])==2


@pytest.mark.parametrize("scenario",["missing_clip","pending_clip","failed_clip"])
def test_clip_failure_never_blocks_explicit_confirmation(client,scenario):
    begin(client)
    result=incident(client,scenario)
    candidate=result["snapshot"]["candidates"][0]
    endpoint=f"/api/v1/matches/{result['snapshot']['match_id']}/candidates/{candidate['candidate_id']}/clip"
    assert client.get(endpoint,headers=AUTH).json()["clips"][0]["status"]==scenario.split("_")[0]
    assert client.get(endpoint+"/file",headers=AUTH).status_code==404
    assert request(client,"confirm_candidate",dict(candidate_id=candidate["candidate_id"])).status_code==200
    assert current(client)["score"]["green"]==1


def test_generated_clip_authentication_ranges_and_tamper(client,tmp_path):
    local=tmp_path/"fixture.mp4"
    local.write_bytes(MEDIA.read_bytes())
    client.app.state.review=DummyReview(media_path=local)
    begin(client); result=incident(client)
    candidate=result["snapshot"]["candidates"][0]
    endpoint=f"/api/v1/matches/{result['snapshot']['match_id']}/candidates/{candidate['candidate_id']}/clip/file"
    assert client.get(endpoint).status_code==401
    response=client.get(endpoint,headers=AUTH)
    assert response.status_code==200 and response.headers["content-type"]=="video/mp4"
    assert b"ftyp" in response.content[:32] and "blob:" in response.headers["content-security-policy"]
    ranged=client.get(endpoint,headers={**AUTH,"Range":"bytes=0-15"})
    assert ranged.status_code==206 and ranged.content==response.content[:16]
    local.write_bytes(b"tampered")
    assert client.get(endpoint,headers=AUTH).status_code==410
    assert request(client,"confirm_candidate",dict(candidate_id=candidate["candidate_id"])).status_code==200


def test_demo_command_retry_preserves_identity_after_later_changes(client):
    begin(client)
    revision=current(client)["revision"]
    first=incident(client,command_id="same-incident",revision=revision)
    candidate=first["snapshot"]["candidates"][0]
    request(client,"reject_candidate",dict(candidate_id=candidate["candidate_id"]))
    retry=incident(client,command_id="same-incident",revision=revision)
    assert retry["duplicate"] and retry["event"]==first["event"]
    assert len(current(client)["candidates"])==1
    assert request(client,"demo_incident",dict(goal_end="goal_b",scenario="observed"),command_id="same-incident",revision=revision).status_code==409


def test_pause_side_change_mode_and_restart_gate(client):
    begin(client); candidate=incident(client)["snapshot"]["candidates"][0]
    request(client,"pause")
    assert current(client)["candidates"][0]["status"]=="unresolved"
    assert request(client,"confirm_candidate",dict(candidate_id=candidate["candidate_id"])).status_code==409
    assert request(client,"swap_ends").status_code==200
    assert request(client,"resume").status_code==200
    candidate=incident(client)["snapshot"]["candidates"][-1]
    assert candidate["team"]=="orange"
    assert request(client,"manual_goal",dict(team="orange",candidate_id=candidate["candidate_id"])).status_code==200
    assert request(client,"demo_incident",dict(goal_end="goal_a",scenario="observed")).status_code==409
    assert request(client,"manual_goal",dict(team="green")).status_code==409
    assert request(client,"restart_play").status_code==200
    assert request(client,"pause").status_code==200
    assert request(client,"set_review_mode",dict(mode="manual")).status_code==200
    assert request(client,"resume").status_code==200
    assert request(client,"manual_goal",dict(team="green")).status_code==200
    assert not current(client)["restart_required"]


def test_dummy_disabled_and_invalid_payloads(tmp_path):
    app=create_app(Settings(database_path=tmp_path/"disabled.db",demo_review_enabled=False),operator_key=KEY,clock=VirtualClock())
    with TestClient(app) as client:
        request(client,"create")
        assert request(client,"set_review_mode",dict(mode="demo_review")).status_code==422
        request(client,"start")
        assert request(client,"demo_incident",dict(goal_end="goal_a",scenario="observed")).status_code==409
        assert request(client,"set_review_mode",dict(mode="automatic")).status_code==422
        assert request(client,"demo_incident",dict(goal_end="goal_a",scenario="observed",evidence=[])).status_code==422


def test_private_websocket_authentication_public_metadata_and_reconnect(client):
    begin(client); result=incident(client)
    with client.websocket_connect("/ws/operator/current") as ws:
        ws.send_json({"operator_key":KEY})
        snapshot=ws.receive_json()
        assert snapshot["event_id"]==result["event"]["event_id"] and "server_clock" in snapshot
        assert snapshot["match"]["candidates"][0]["review"]["origin"]=="dummy_fusion"
    with client.websocket_connect("/ws/operator/current") as ws:
        ws.send_json({"operator_key":"invalid"})
        with pytest.raises(WebSocketDisconnect) as error:
            ws.receive_json()
        assert error.value.code==1008
    for _ in range(2):
        with client.websocket_connect("/ws/matches/current") as ws:
            public=ws.receive_json()
            assert public["revision"]==current(client)["revision"] and "candidates" not in public["match"]


def test_display_presence_ack_latency_is_instrumentation_not_score_authority(client):
    begin(client)
    with client.websocket_connect("/ws/matches/current") as ws:
        ws.receive_json()
        client.app.state.store.clock.advance(.1)
        goal=request(client,"manual_goal",dict(team="green")).json()
        ws.send_text("refresh")
        snapshot=ws.receive_json()
        client.app.state.store.clock.advance(.03)
        ws.send_json(dict(type="rendered",match_id=snapshot["match_id"],revision=snapshot["revision"],event_id=snapshot["event_id"]))
        ws.receive_json()
        state=client.get("/api/v1/displays/status",headers=AUTH).json()
        assert state["connected"]==1 and state["connections"][0]["state"]=="rendering"
        assert state["rendered_samples"][0]["commit_to_render_ack_seconds"]==.03
        assert not state["physical_display_verified"]
        assert current(client)["score"]==goal["snapshot"]["score"]
    assert client.get("/api/v1/displays/status",headers=AUTH).json()["connections"][0]["state"]=="disconnected"
