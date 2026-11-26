import json
from threading import Event
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from core.capture import CameraConfig, CaptureSettings
from modules.capture.backend import Packet
from modules.capture.manager import CaptureManager
from modules.capture.manager import CameraWorker
from modules.capture.recording import StorageGuard
from types import SimpleNamespace
from tests.test_capture import frame, markers, wait_until
from tools.check_sync import evaluate


def test_stuck_camera_is_restarted_without_stopping_second_camera(tmp_path, monkeypatch):
    class Reader:
        def __init__(self, config, settings):
            self.config = config
            self.stop = Event()
            self.n = 0
        def read(self):
            if self.config.id == "stuck":
                self.stop.wait()
                return None
            if self.stop.wait(0.02):
                return None
            self.n += 1
            return Packet(frame(0, 0).jpeg, self.n - 1, (self.n - 1) * 0.02, 32, 32)
        def close(self):
            self.stop.set()
        def release(self):
            self.close()
    monkeypatch.setattr("modules.capture.manager.FFmpegReader", Reader)
    manager = CaptureManager([CameraConfig(id=name, source="fixture", width=32, height=32, expected_fps=50)
                              for name in ("stuck", "flowing")],
                             CaptureSettings(root=str(tmp_path), min_free_bytes=0, startup_timeout_seconds=0.2,
                                             stale_seconds=0.2, reconnect_seconds=0.05))
    try:
        manager.start()
        wait_until(lambda: manager.workers["stuck"].record.reconnects >= 1)
        assert manager.workers["flowing"].record.frames >= 5
        assert manager.workers["flowing"].record.reconnects == 0
    finally:
        manager.close()
    incidents = [json.loads(line) for line in (manager.root / "incidents.jsonl").read_text().splitlines()]
    assert any(i["type"] == "stale_reader" and i["camera_id"] == "stuck" for i in incidents)


def test_sync_pairwise_shared_markers_and_missing_pair_evidence():
    data = markers()
    data.markers += [m.model_copy(update={"source_id": "other", "source_seconds": m.source_seconds + 4}) for m in data.markers]
    result = evaluate(data)
    assert result["cross_source_evidence_available"]
    assert result["pairs"][0]["p95_bound_ms"] == pytest.approx(4)
    assert not evaluate(markers())["cross_source_evidence_available"]


def test_frequent_receipts_do_not_hide_source_delivery_lag(tmp_path, monkeypatch):
    instant = [100.0]
    monkeypatch.setattr("modules.capture.manager.time.monotonic", lambda: instant[0])
    manager = SimpleNamespace(root=tmp_path, host_domain="host", guard=StorageGuard(tmp_path, 100000, 0),
                              clips=SimpleNamespace(feed=lambda frame: None), incident=lambda *args, **kw: None)
    worker = CameraWorker(CameraConfig(id="a", source="fixture", width=32, height=32, expected_fps=10),
                          CaptureSettings(stale_seconds=1), manager)
    try:
        worker._feed(Packet(frame(0, 0).jpeg, 0, 0, 32, 32), "boot")
        instant[0] += 4
        worker._feed(Packet(frame(0, 0).jpeg, 1, 0.1, 32, 32), "boot")
        assert worker.status()["health"] == "lagging"
        assert worker.status()["frame_age_seconds"] == 0
        assert worker.status()["delivery_lag_growth_seconds"] == pytest.approx(3.9)
    finally:
        worker._end_segment()


def test_committed_goals_request_clips_once_outside_score_transaction(tmp_path, monkeypatch):
    class Manager:
        requests = []
        def __init__(self, cameras, settings):
            pass
        def start(self):
            pass
        def close(self):
            pass
        def request_clip(self, request):
            self.requests.append(request)
            return {"status": "collecting"}
        def status(self):
            return {"enabled": True}
        def incident(self, *args, **kwargs):
            pass
    monkeypatch.setattr("app.main.CaptureManager", Manager)
    settings = Settings(database_path=tmp_path / "scores.db", cameras=[CameraConfig(id="a", source="fixture")],
                        capture=CaptureSettings(enabled=True))
    key = "test-capture-key-at-least-16"
    auth = {"Authorization": f"Bearer {key}"}
    def command(action, revision, payload=None):
        return {"command_id": str(uuid4()), "expected_revision": revision, "action": action, "payload": payload or {}}
    with TestClient(create_app(settings, operator_key=key)) as client:
        assert client.get("/api/v1/capture/status", headers=auth).json()["enabled"]
        creation = client.post("/api/v1/matches", json=command("create", 0), headers=auth).json()
        path = f"/api/v1/matches/{creation['snapshot']['match_id']}/commands"
        client.post(path, json=command("start", 1), headers=auth)
        goal = command("manual_goal", 2, {"team": "orange"})
        result = client.post(path, json=goal, headers=auth)
        assert result.status_code == 200
        event_id = result.json()["event"]["event_id"]
        wait_until(lambda: len(Manager.requests) == 1)
        assert Manager.requests[0].event_id == event_id
        assert Manager.requests[0].event_monotonic_seconds is None
        assert client.post(path, json=goal, headers=auth).json()["duplicate"]
        time.sleep(0.15)
        assert len(Manager.requests) == 1
