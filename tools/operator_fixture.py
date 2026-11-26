"""Run the Part 07 dummy operator/API workflow in a fresh disposable database."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import create_app
from app.review import MEDIA
from app.settings import Settings
from core.clock import VirtualClock

ROOT = Path(__file__).resolve().parents[1]


def run(destination):
    destination.mkdir(parents=True, exist_ok=False)
    clock = VirtualClock()
    # Scoped deterministic identities for fixture reproduction only. Production uses uuid4.
    sequence = 0
    def identity():
        nonlocal sequence
        sequence += 1
        return uuid5(NAMESPACE_URL, f"neon-operator-fixture-v1:{sequence}")
    auth = {"Authorization": "Bearer disposable-fixture-key-only", "X-Operator-Name": "Fixture operator"}
    app = create_app(Settings(database_path=destination / "match.db"), operator_key="disposable-fixture-key-only", clock=clock)
    with patch("modules.storage.store.uuid4", identity), TestClient(app) as client:
        def current():
            return client.get("/api/v1/operator/matches/current", headers=auth).json()["match"]
        commands = 0
        def command(action, payload=None):
            nonlocal commands
            commands += 1
            state = current()
            url = f"/api/v1/matches/{state['match_id']}/commands" if state else "/api/v1/matches"
            result = client.post(url, headers=auth, json=dict(command_id=f"fixture-command-{commands}",
                expected_revision=state["revision"] if state else 0, action=action, payload=payload or {}))
            if result.status_code not in (200, 201):
                raise RuntimeError(f"Fixture {action} failed: {result.status_code}")
            return result.json()
        command("create", dict(players=[dict(id="green-7", team="green", bib=7, name="Fixture scorer")]))
        command("set_review_mode", dict(mode="demo_review")); command("start")
        def incident(scenario="observed"):
            return command("demo_incident", dict(goal_end="goal_a", scenario=scenario))["snapshot"]["candidates"][-1]
        first = incident()
        assert current()["score"] == dict(orange=0, green=0)
        mid = current()["match_id"]
        clip = client.get(f"/api/v1/matches/{mid}/candidates/{first['candidate_id']}/clip/file", headers=auth)
        assert clip.status_code == 200 and clip.content == MEDIA.read_bytes()
        assert client.get("/api/v1/operator/matches/current").status_code == 401
        goal = command("confirm_candidate", dict(candidate_id=first["candidate_id"]))["event"]["payload"]
        command("attribute_goal", dict(goal_id=goal["goal_id"], scorer_id="green-7"))
        command("undo_goal", dict(goal_id=goal["goal_id"])); command("restart_play")
        rejected = incident("net_contact")
        command("reject_candidate", dict(candidate_id=rejected["candidate_id"]))
        incident("pending_clip"); clock.advance(15)
        assert current()["candidates"][-1]["status"] == "unresolved"
        uncertain = incident("partial")
        command("manual_goal", dict(team="green", candidate_id=uncertain["candidate_id"]))
        command("restart_play"); command("end")
        private_reconnects, public_reconnects = 0, 0
        for _ in range(2):
            with client.websocket_connect("/ws/operator/current") as socket:
                socket.send_json({"operator_key": "disposable-fixture-key-only"})
                assert socket.receive_json()["match"]["revision"] == current()["revision"]
                private_reconnects += 1
            with client.websocket_connect("/ws/matches/current") as socket:
                public = socket.receive_json()
                assert public["match"]["score"] == current()["score"] and "candidates" not in public["match"]
                public_reconnects += 1
        root = f"/api/v1/matches/{mid}"
        outputs = {}
        for name, suffix in (("export.json", "export"), ("report.json", "report"), ("report.txt", "report.txt")):
            data = client.get(f"{root}/{suffix}", headers=auth).content
            clock.advance(100)
            assert data == client.get(f"{root}/{suffix}", headers=auth).content
            (destination / name).write_bytes(data)
            outputs[name] = hashlib.sha256(data).hexdigest()
        report = json.loads((destination / "report.json").read_bytes())
        paths = [p for folder in ("app", "core", "modules") for p in (ROOT / folder).rglob("*.py")]
        paths += list((ROOT / "modules/api/static").glob("*.js")) + list((ROOT / "modules/api/static").glob("*.html"))
        paths += [ROOT / "modules/api/static/style.css", Path(__file__).resolve(), MEDIA, MEDIA.with_suffix(".json")]
        baseline = dict(schema_version=1, fixture="operator-api-v1", evidence="synthetic",
            commands=commands, score=report["score"], event_count=report["event_count"], review_counts=report["review_counts"],
            goals=len(report["goals"]), corrections=len(report["corrections"]), public_reconnects=public_reconnects,
            private_reconnects=private_reconnects, outputs=outputs,
            source_sha256={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)},
            browser_render_verified=False, physical_display_verified=False, measured_render_latency_seconds=None,
            automatic_scoring_enabled=False, clip_represents_football=False)
        (destination / "baseline.json").write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return baseline


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="New directory only; existing fixtures are never overwritten")
    args = parser.parse_args()
    result = run(args.destination)
    print(json.dumps({k: result[k] for k in ("fixture", "score", "event_count", "review_counts", "outputs")}))
