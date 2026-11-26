import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.analytics import DummyAnalytics
from app.main import create_app
from app.reports import enriched_report, enriched_text
from app.settings import Settings
from core.clock import VirtualClock
from core.ports import DomainError
from core.schemas import Command
from modules.storage.maintenance import backup_database, inspect_database, restore_database
from modules.storage.store import SQLiteStore
from tests.operator.test_operator_api import AUTH, KEY, current, request
from tools.build_attribution_fixture import PLAYERS, ACTIVE


def send(store,action,payload=None,*,command_id=None,revision=None):
    state=store.current()
    command=Command(command_id=command_id or str(uuid4()),expected_revision=revision if revision is not None else state["revision"] if state else 0,
        action=action,payload=payload or {})
    prepared=DummyAnalytics().prepare(state["match_id"],command,state) if action=="demo_analytics" else None
    return store.execute(state["match_id"] if state else None,command,prepared_analytics=prepared)


def begin(store):
    send(store,"create",dict(players=PLAYERS,active_player_ids=ACTIVE));send(store,"start")


def correction(session,player="green-7",touch="touch-1",void=False):
    return dict(session_id=session,touch_id=touch,player_id=player,kind="control",certainty="certain",void=void)


def test_corrected_contact_reports_and_official_goal_stats_remain_separate(tmp_path):
    store=SQLiteStore(tmp_path/"score.db",VirtualClock())
    try:
        begin(store)
        first=send(store,"manual_goal",dict(team="green",scorer_id="green-7",assist_id="green-11"))["event"]["payload"]["goal_id"]
        second=send(store,"manual_goal",dict(team="green",scorer_id="orange-9",own_goal=True))["event"]["payload"]["goal_id"]
        item=send(store,"demo_analytics")["snapshot"]["analytics_sessions"][-1]
        sid=item["session"]["session_id"]
        report=lambda:enriched_report(store.export(store.current()["match_id"]))
        initial=report()
        assert initial["contact_analytics"]["sessions"][0]["teams"]["green"]["passes"]==2
        assert {p["id"]:p["own_goals"] for p in initial["official_statistics"]["players"]}["orange-9"]==1
        send(store,"correct_analytics_touch",correction(sid))
        assert report()["contact_analytics"]["sessions"][0]["teams"]["green"]["passes"]==1
        assert store.current()["score"]["green"]==2
        send(store,"attribute_goal",dict(goal_id=first,scorer_id="green-11"));send(store,"undo_goal",dict(goal_id=second))
        final=report();players={p["id"]:p for p in final["official_statistics"]["players"]}
        assert (players["green-7"]["goals"],players["green-11"]["goals"],players["green-11"]["assists"],players["orange-9"]["own_goals"])==(0,1,0,0)
        assert final["score"]==dict(orange=0,green=1)
        assert final["contact_analytics"]["sessions"][0]["teams"]["green"]["passes"]==1
        assert store.current()["analytics_sessions"][0]["session"]==item["session"]
        send(store,"end");text=enriched_text(report());store.clock.advance(100)
        assert enriched_text(report())==text and "Generated contact windows" in text
        assert "shots and shots on target: unavailable" in text
        assert "Generated player Green | 11 Green Eleven" in text
        assert store.integrity()["events"]==store.current()["revision"]
    finally:store.close()


def test_void_restore_exact_retry_and_stale_revision(tmp_path):
    store=SQLiteStore(tmp_path/"score.db",VirtualClock())
    try:
        begin(store);sid=send(store,"demo_analytics")["snapshot"]["analytics_sessions"][0]["session"]["session_id"]
        revision=store.current()["revision"]
        send(store,"correct_analytics_touch",correction(sid,void=True),command_id="void-once",revision=revision)
        assert send(store,"correct_analytics_touch",correction(sid,void=True),command_id="void-once",revision=revision)["duplicate"]
        assert store.current()["analytics_sessions"][0]["revision"]==1
        with pytest.raises(DomainError):send(store,"correct_analytics_touch",correction(sid,"green-11"),revision=revision)
        send(store,"correct_analytics_touch",correction(sid,"green-11"))
        report=enriched_report(store.export(store.current()["match_id"]))
        assert report["contact_analytics"]["sessions"][0]["teams"]["green"]["passes"]==2
        assert report["contact_analytics"]["sessions"][0]["correction_count"]==2
    finally:store.close()


@pytest.mark.parametrize("damage", ["missing_session","missing_contact","inactive_player"])
def test_invalid_corrections_are_atomic(tmp_path,damage):
    store=SQLiteStore(tmp_path/"score.db",VirtualClock())
    try:
        begin(store);sid=send(store,"demo_analytics")["snapshot"]["analytics_sessions"][0]["session"]["session_id"]
        before=store.export(store.current()["match_id"])
        change=correction(sid)
        if damage=="missing_session":change["session_id"]="missing"
        if damage=="missing_contact":change["touch_id"]="missing"
        if damage=="inactive_player":change["player_id"]="green-15"
        with pytest.raises(DomainError):send(store,"correct_analytics_touch",change)
        assert store.export(store.current()["match_id"])==before
    finally:store.close()


def test_backup_recovery_preserves_original_and_corrected_evidence(tmp_path):
    path=tmp_path/"original.db";store=SQLiteStore(path,VirtualClock())
    try:
        begin(store);sid=send(store,"demo_analytics")["snapshot"]["analytics_sessions"][0]["session"]["session_id"]
        send(store,"correct_analytics_touch",correction(sid))
        before=enriched_report(store.export(store.current()["match_id"]))["contact_analytics"]
        backup_database(path,tmp_path/"backup");restore_database(tmp_path/"backup",tmp_path/"restored.db")
        recovered=SQLiteStore(tmp_path/"restored.db",VirtualClock())
        try:
            assert recovered.current()["status"]=="interrupted"
            after=enriched_report(recovered.export(recovered.current()["match_id"]))["contact_analytics"]
            assert after==before and recovered.integrity()["events"]==recovered.current()["revision"]
        finally:recovered.close()
    finally:store.close()


def test_evidence_transaction_failure_and_runtime_projection_tamper(tmp_path):
    path=tmp_path/"score.db";store=SQLiteStore(path,VirtualClock())
    try:
        begin(store);before=store.export(store.current()["match_id"])
        store.db.executescript("CREATE TRIGGER simulate_full BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'full'); END;")
        with pytest.raises(Exception,match="full"):send(store,"demo_analytics",command_id="must-not-ack")
        assert store.export(store.current()["match_id"])==before
        assert store.db.execute("SELECT 1 FROM commands WHERE command_id='must-not-ack'").fetchone() is None
        store.db.execute("DROP TRIGGER simulate_full")
        send(store,"demo_analytics")
        state=store.current();state["analytics_sessions"][0]["session"]["contacts"][0]["player_id"]="green-11"
        store.db.execute("UPDATE matches SET state=? WHERE id=?",(json.dumps(state),state["match_id"]))
        with pytest.raises(ValueError,match="Analytics evidence"):inspect_database(path)
    finally:store.close()


def test_api_private_generated_reports_public_redaction_and_independent_sessions(tmp_path):
    app=create_app(Settings(database_path=tmp_path/"score.db"),operator_key=KEY,clock=VirtualClock())
    with TestClient(app) as client:
        request(client,"create",dict(players=PLAYERS,active_player_ids=ACTIVE));request(client,"start")
        goal=request(client,"manual_goal",dict(team="green")).json()["event"]["payload"]["goal_id"]
        added=request(client,"demo_analytics",dict(scenario="passing"));assert added.status_code==200,added.text
        item=added.json()["snapshot"]["analytics_sessions"][0];sid=item["session"]["session_id"]
        request(client,"demo_analytics",dict(scenario="gaps"))
        mid=current(client)["match_id"];root=f"/api/v1/matches/{mid}"
        assert client.get(root+"/report").status_code==401
        assert client.get(root+"/report",headers={**AUTH,"Origin":"https://foreign.example"}).status_code==403
        report=client.get(root+"/report",headers=AUTH).json()
        assert len(report["contact_analytics"]["sessions"])==2 and "totals" not in report["contact_analytics"]
        assert report["official_statistics"]["teams"]["green"]["unknown_scorer_goals"]==1
        assert request(client,"correct_analytics_touch",correction(sid)).status_code==200
        assert request(client,"attribute_goal",dict(goal_id=goal,scorer_id="green-11")).status_code==200
        assert current(client)["score"]["green"]==1
        public=client.get("/api/v1/matches/current").json()["match"]
        assert "analytics_sessions" not in public
        with client.websocket_connect("/ws/matches/current") as ws:assert "analytics_sessions" not in ws.receive_json()["match"]
        with client.websocket_connect("/ws/operator/current") as ws:
            ws.send_json({"operator_key":KEY});assert len(ws.receive_json()["match"]["analytics_sessions"])==2
        assert b"Generated contact windows" in client.get(root+"/report.txt",headers=AUTH).content
        assert app.state.store.integrity()["events"]==current(client)["revision"]


def test_absent_analytics_and_disabled_dummy_do_not_invent_zero_measurements(tmp_path):
    app=create_app(Settings(database_path=tmp_path/"score.db",demo_review_enabled=False),operator_key=KEY,clock=VirtualClock())
    with TestClient(app) as client:
        request(client,"create",dict(players=PLAYERS));request(client,"start")
        assert request(client,"demo_analytics").status_code==422
        report=client.get(f"/api/v1/matches/{current(client)['match_id']}/report",headers=AUTH).json()
        assert report["contact_analytics"]["status"]=="unavailable" and report["contact_analytics"]["sessions"]==[]
        assert "distance" in report["contact_analytics"]["unavailable_metrics"]
