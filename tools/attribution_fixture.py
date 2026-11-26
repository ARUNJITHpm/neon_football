"""Run dummy late-attribution/substitution/correction through the actual private API."""
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
from app.settings import Settings
from core.clock import VirtualClock
from tools.build_attribution_fixture import PLAYERS, ACTIVE

ROOT = Path(__file__).resolve().parents[1]


def run(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    sequence = 0
    def identity():
        nonlocal sequence
        sequence += 1
        return uuid5(NAMESPACE_URL, f"neon-attribution-fixture-v1:{sequence}")
    auth = {"Authorization": "Bearer disposable-fixture-key-only", "X-Operator-Name": "Fixture operator"}
    app = create_app(Settings(database_path=destination / "match.db"), operator_key="disposable-fixture-key-only", clock=VirtualClock())
    with patch("modules.storage.store.uuid4", identity), TestClient(app) as client:
        def current(): return client.get("/api/v1/operator/matches/current", headers=auth).json()["match"]
        commands = 0
        def command(action, payload=None):
            nonlocal commands
            commands += 1
            state = current()
            url = f"/api/v1/matches/{state['match_id']}/commands" if state else "/api/v1/matches"
            result = client.post(url, headers=auth, json=dict(command_id=f"fixture-command-{commands}",
                expected_revision=state["revision"] if state else 0, action=action, payload=payload or {}))
            if result.status_code not in (200, 201): raise RuntimeError(f"Fixture {action} failed: {result.status_code}")
            return result.json()
        command("create", dict(players=PLAYERS, active_player_ids=ACTIVE)); command("start")
        first = command("manual_goal", dict(team="green"))["event"]["payload"]["goal_id"]
        assert current()["goals"][0]["scorer_id"] is None and current()["score"]["green"] == 1
        command("substitute_player", dict(outgoing_id="green-7", incoming_id="green-15"))
        def proposal(goal, scenario):
            return command("demo_attribution", dict(goal_id=goal, scenario=scenario))["snapshot"]["attribution_suggestions"][-1]
        def reference(item): return dict(goal_id=item["goal_id"], suggestion_id=item["suggestion_id"])
        item = proposal(first, "assist")
        assert item["submission"]["suggestion"]["scorer_id"] == "green-7" and current()["goals"][0]["scorer_id"] is None
        command("accept_attribution", reference(item))
        second = command("manual_goal", dict(team="green"))["event"]["payload"]["goal_id"]
        item = proposal(second, "uncertain"); command("reject_attribution", reference(item))
        item = proposal(second, "own_goal"); command("accept_attribution", reference(item))
        command("attribute_goal", dict(goal_id=second, scorer_id="green-15", assist_id=None, own_goal=False))
        command("undo_goal", dict(goal_id=second)); command("pause"); command("swap_ends"); command("end")
        state = current(); mid = state["match_id"]
        assert state["score"] == dict(orange=0, green=1)
        assert app.state.store.integrity()["events"] == commands
        with client.websocket_connect("/ws/operator/current") as socket:
            socket.send_json({"operator_key": "disposable-fixture-key-only"})
            assert socket.receive_json()["match"]["attribution_suggestions"] == state["attribution_suggestions"]
        with client.websocket_connect("/ws/matches/current") as socket:
            public = socket.receive_json()["match"]
            assert public["score"] == state["score"] and "attribution_suggestions" not in public and "players" not in public
        outputs = {}
        for name, suffix in (("export.json", "export"), ("report.json", "report"), ("report.txt", "report.txt")):
            data = client.get(f"/api/v1/matches/{mid}/{suffix}", headers=auth).content
            app.state.store.clock.advance(100)
            assert data == client.get(f"/api/v1/matches/{mid}/{suffix}", headers=auth).content
            (destination / name).write_bytes(data); outputs[name] = hashlib.sha256(data).hexdigest()
        paths = [p for folder in ("app", "core", "modules") for p in (ROOT / folder).rglob("*.py")]
        paths += [p for p in (ROOT / "modules/api/static").glob("*") if p.suffix in (".js", ".html", ".css")]
        paths += [Path(__file__).resolve(), ROOT / "tools/build_attribution_fixture.py", ROOT / "tools/attribution_replay.py"]
        baseline = dict(schema_version=1, fixture="attribution-api-v1", evidence="synthetic", commands=commands,
            event_count=commands, score=state["score"], goals=len(state["goals"]), roster_revision=state["roster_revision"],
            suggestion_statuses=[s["status"] for s in state["attribution_suggestions"]], outputs=outputs,
            source_sha256={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)},
            actual_image_recognition=False, field_accuracy_measured=False, browser_render_verified=False,
            automatic_attribution_enabled=False, automatic_scoring_enabled=False)
        (destination / "baseline.json").write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return baseline


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("destination", type=Path); args = parser.parse_args()
    print(json.dumps({k: v for k, v in run(args.destination).items() if k != "source_sha256"}, sort_keys=True))
