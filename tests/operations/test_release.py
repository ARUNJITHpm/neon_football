import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

from app.main import create_app
from app.settings import Settings
from core.clock import VirtualClock
from fastapi.testclient import TestClient
from tests.operator.test_operator_api import AUTH, KEY, current, request
from tools.package_release import build, release_files, ROOT
from tools.release_evaluation import evaluate
from core.capture import CameraConfig, CaptureSettings
from modules.storage.store import SQLiteStore
from tests.test_capture import wait_until


def test_dummy_shadow_never_qualifies_even_when_false_goal_count_is_zero():
    report = evaluate(ROOT / "tests/fusion/fixtures/dataset.json")
    assert report["dummy_counts"]["false_shadow"] == 0
    assert report["dummy_counts"]["valid_references"] == 15
    assert not report["release_qualified"] and not report["automatic_scoring_enabled"]
    assert report["field_metrics"] is None
    assert {gate["state"] for gate in report["gates"]} == {"pending"}


def test_package_allowlist_excludes_private_data_and_freezes_content(tmp_path):
    files = [p.relative_to(ROOT).as_posix() for p in release_files()]
    assert not any(name.startswith(("data/", "local_scratch/", ".venv/")) or name.endswith(".key") for name in files)
    assert "app/fixtures/review-pattern.mp4" in files
    first, second = build(tmp_path / "a"), build(tmp_path / "b")
    assert first["sha256"] == second["sha256"]
    with zipfile.ZipFile(tmp_path / "a" / first["archive"]) as archive:
        manifest = json.loads(archive.read("candidate-manifest.json"))
        assert not manifest["field_qualified"] and not manifest["dependencies_bundled"]
        for name, record in manifest["files"].items():
            raw = archive.read(name)
            assert len(raw) == record["bytes"] and hashlib.sha256(raw).hexdigest() == record["sha256"]


def test_failed_clip_worker_and_capture_health_leave_manual_scoring_available(tmp_path):
    app = create_app(Settings(database_path=tmp_path / "score.db"), operator_key=KEY, clock=VirtualClock())
    with TestClient(app) as client:
        app.state.operations.clip_task = lambda: SimpleNamespace(done=lambda: True)
        app.state.capture = SimpleNamespace(status=lambda: dict(enabled=True, cameras=[dict(camera_id="a", health="stale", live_dropped_frames=9,
            frame_age_seconds=4, delivery_lag_growth_seconds=3)], alignment_verified=False))
        health = client.get("/api/v1/operations/status", headers=AUTH).json()
        assert health["state"] == "degraded" and health["scoring_available"]
        assert health["clip_worker"] == "stopped" and health["capture"]["cameras"][0]["live_dropped_frames"] == 9
        request(client, "create"); request(client, "start")
        assert request(client, "manual_goal", dict(team="green")).status_code == 200
        assert current(client)["score"]["green"] == 1


def test_failed_capture_and_automatic_activation_are_explicit(tmp_path):
    app = create_app(Settings(database_path=tmp_path / "score.db"), operator_key=KEY, clock=VirtualClock())
    with TestClient(app) as client:
        def broken_status():
            raise RuntimeError("fixture failure")
        app.state.capture = SimpleNamespace(status=broken_status)
        health = client.get("/api/v1/operations/status", headers=AUTH).json()
        assert health["state"] == "degraded" and health["scoring_available"]
    import pytest
    with pytest.raises(ValueError, match="Automatic scoring is unavailable"):
        create_app(Settings(automatic_scoring_enabled=True))


def test_actual_clip_consumer_failure_does_not_leak_database_owner(tmp_path, monkeypatch):
    closed = []
    class Manager:
        def __init__(self, *args):
            pass
        def start(self):
            pass
        def request_clip(self, *args):
            raise RuntimeError("fixture clip failure")
        def incident(self, *args, **kwargs):
            raise RuntimeError("fixture consumer failure")
        def status(self):
            return dict(enabled=True, cameras=[], alignment_verified=False)
        def close(self):
            closed.append(True)
    monkeypatch.setattr("app.main.CaptureManager", Manager)
    path = tmp_path / "score.db"
    settings = Settings(database_path=path, capture=CaptureSettings(enabled=True), cameras=[CameraConfig(id="a", source="dummy")])
    with TestClient(create_app(settings, operator_key=KEY, clock=VirtualClock())) as client:
        request(client, "create"); request(client, "start"); request(client, "manual_goal", dict(team="green"))
        wait_until(lambda: client.get("/api/v1/operations/status", headers=AUTH).json()["clip_worker"] == "stopped")
        assert current(client)["score"]["green"] == 1
    assert closed == [True]
    recovered = SQLiteStore(path, VirtualClock())
    try:
        assert recovered.current()["score"]["green"] == 1
    finally:
        recovered.close()
