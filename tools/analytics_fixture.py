"""Exercise Part 10 generated analytics and corrected official reports through the API."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

if __package__ in (None, ""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from core.clock import VirtualClock
from tools.build_attribution_fixture import PLAYERS, ACTIVE

ROOT=Path(__file__).resolve().parents[1]


def run(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    sequence=0
    def identity():
        nonlocal sequence
        sequence+=1
        return uuid5(NAMESPACE_URL,f"neon-analytics-fixture-v1:{sequence}")
    auth={"Authorization":"Bearer disposable-fixture-key-only","X-Operator-Name":"Fixture operator"}
    app=create_app(Settings(database_path=destination/"match.db"),operator_key="disposable-fixture-key-only",clock=VirtualClock())
    with patch("modules.storage.store.uuid4",identity),TestClient(app) as client:
        def current():return client.get("/api/v1/operator/matches/current",headers=auth).json()["match"]
        commands=0;original=None
        def command(action,payload=None):
            nonlocal commands,original
            commands+=1;state=current()
            body=dict(command_id=f"fixture-command-{commands}",expected_revision=state["revision"] if state else 0,action=action,payload=payload or {})
            url=f"/api/v1/matches/{state['match_id']}/commands" if state else "/api/v1/matches"
            response=client.post(url,headers=auth,json=body)
            if response.status_code not in (200,201):raise RuntimeError(f"Fixture {action} failed: {response.status_code}")
            if action=="demo_analytics" and original is None:original=(url,body)
            return response.json()
        command("create",dict(players=PLAYERS,active_player_ids=ACTIVE));command("start")
        first=command("manual_goal",dict(team="green",scorer_id="green-7",assist_id="green-11"))["event"]["payload"]["goal_id"]
        own=command("manual_goal",dict(team="green",scorer_id="orange-9",own_goal=True))["event"]["payload"]["goal_id"]
        item=command("demo_analytics",dict(scenario="passing"))["snapshot"]["analytics_sessions"][0]
        sid=item["session"]["session_id"]
        def correction(player,void=False):return dict(session_id=sid,touch_id="touch-1",player_id=player,kind="control",certainty="certain",void=void)
        command("correct_analytics_touch",correction("green-7"))
        command("demo_analytics",dict(scenario="gaps"));command("demo_analytics",dict(scenario="pauses"))
        command("attribute_goal",dict(goal_id=first,scorer_id="green-11"));command("undo_goal",dict(goal_id=own))
        command("manual_goal",dict(team="orange"));command("pause");command("swap_ends");command("resume");command("end")
        command("correct_analytics_touch",correction("green-11",True));command("correct_analytics_touch",correction("green-11"))
        command("demo_analytics",dict(scenario="uncertain"))
        state=current();mid=state["match_id"]
        retry=client.post(original[0],headers=auth,json=original[1])
        assert retry.status_code==200 and retry.json()["duplicate"] and current()["revision"]==state["revision"]
        assert current()["score"]==dict(orange=1,green=1) and app.state.store.integrity()["events"]==commands
        with client.websocket_connect("/ws/matches/current") as ws:
            public=ws.receive_json()["match"]
            assert "analytics_sessions" not in public and public["score"]==state["score"]
        with client.websocket_connect("/ws/operator/current") as ws:
            ws.send_json({"operator_key":"disposable-fixture-key-only"})
            assert ws.receive_json()["match"]["analytics_sessions"]==state["analytics_sessions"]
        outputs={}
        for name,suffix in (("export.json","export"),("report.json","report"),("report.txt","report.txt")):
            response=client.get(f"/api/v1/matches/{mid}/{suffix}",headers=auth);assert response.status_code==200
            data=response.content;app.state.store.clock.advance(100)
            assert data==client.get(f"/api/v1/matches/{mid}/{suffix}",headers=auth).content
            (destination/name).write_bytes(data);outputs[name]=hashlib.sha256(data).hexdigest()
        report=json.loads((destination/"report.json").read_bytes())
        assert report["official_statistics"]["teams"]["orange"]["unknown_scorer_goals"]==1
        assert {p["id"]:p["goals"] for p in report["official_statistics"]["players"]}["green-11"]==1
        assert len(report["contact_analytics"]["sessions"])==4
        assert report["contact_analytics"]["sessions"][0]["teams"]["green"]["passes"]==2
        paths=[p for folder in ("app","core","modules") for p in (ROOT/folder).rglob("*.py")]
        paths += [Path(__file__).resolve(),ROOT/"tools/build_analytics_fixture.py",ROOT/"tools/analytics_replay.py",ROOT/"tools/build_attribution_fixture.py"]
        baseline=dict(schema_version=1,fixture="contact-analytics-api-v1",evidence="synthetic",commands=commands,event_count=commands,
            duplicate_requests=1,score=state["score"],official_statistics=report["official_statistics"],
            contact_sessions=len(report["contact_analytics"]["sessions"]),corrections=[s["correction_count"] for s in report["contact_analytics"]["sessions"]],
            outputs=outputs,source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)},
            actual_touch_detection=False,browser_render_verified=False,field_qualified=False,automatic_scoring_enabled=False)
        (destination/"baseline.json").write_text(json.dumps(baseline,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return baseline


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("destination",type=Path);args=parser.parse_args()
    result=run(args.destination)
    print(json.dumps({key:result[key] for key in ("fixture","commands","score","contact_sessions","corrections","outputs")},sort_keys=True))
