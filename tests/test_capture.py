from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.settings import Settings
from core.capture import (CalibrationRecord, CameraConfig, CaptureSettings, ClipRequest,
                          EncodedFrame, FrameMetadata, RecordingManifest, TimingEnvelope)
from core.clock import SourceClockTracker, VirtualClock
from core.ports import DomainError
from modules.capture.backend import read_jpeg
from modules.capture.buffers import ClipBuffer, LatestFrames
from modules.capture.clips import Clips
from modules.capture.manager import CaptureManager
from modules.capture.recording import IndexedWriter, StorageGuard
from tools.capture_fixture import generate
from tools.check_sync import MarkerSet, evaluate


def frame(sequence, seconds, boot="boot", payload=b"\xff\xd8\xff\xd9"):
    return EncodedFrame(FrameMetadata(camera_id="a", width=32, height=32,
        timing=TimingEnvelope(source_id="a", boot_id=boot, sequence=sequence,
            source_sequence=sequence, source_seconds=seconds, source_clock_domain="media:a",
            host_clock_domain="host", host_monotonic_seconds=seconds,
            received_at=datetime.now(timezone.utc), quality="media_pts")), payload)


def wait_until(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for capture state")


def test_jpeg_parser_metadata_escaped_entropy_and_frame_boundaries():
    jpeg = b"\xff\xd8\xff\xe0\x00\x06\xff\xd9ab\xff\xda\x00\x02abc\xff\x00z\xff\xd0x\xff\xd9"
    stream = io.BufferedReader(io.BytesIO(jpeg + jpeg))
    assert read_jpeg(stream, 100) == jpeg
    assert read_jpeg(stream, 100) == jpeg
    assert read_jpeg(stream, 100) is None
    with pytest.raises(ValueError):
        read_jpeg(io.BytesIO(jpeg), len(jpeg) - 1)
    with pytest.raises(EOFError):
        read_jpeg(io.BytesIO(jpeg[:-1]), 100)
    with pytest.raises(ValueError):
        read_jpeg(io.BytesIO(b"invalid"), 100)


def test_live_and_history_are_bounded_with_explicit_drops():
    live = LatestFrames(2)
    buffer = ClipBuffer(2, 8)
    for n in range(4):
        live.put(frame(n, n))
        buffer.put(frame(n, n))
    assert live.dropped == 2
    assert live.take().metadata.timing.sequence == 2
    assert buffer.bytes == 8
    assert [f.metadata.timing.sequence for f in buffer.window(0, 10)] == [2, 3]
    assert buffer.byte_evictions == 2
    buffer.clear()
    assert buffer.bytes == 0


def test_source_clock_resets_and_nonfinite_replay_time():
    tracker = SourceClockTracker()
    assert not tracker.observe("first", 5, 1)
    assert not tracker.observe("first", 6, 2)
    assert tracker.observe("first", 4, 3)
    assert tracker.observe("second", 0, 0)
    assert tracker.observe("second", 1, 0)
    with pytest.raises(ValueError):
        VirtualClock().advance(float("nan"))


def markers(error=0, uncertainty=0.001):
    return MarkerSet(evidence="synthetic", procedure="Known 100 ppm clock with held-out markers", markers=[
        dict(source_id="camera", boot_id="boot", source_clock_domain="media", host_clock_domain="host",
             marker_id=str(n), source_seconds=n*10, reference_host_seconds=100 + n*10*1.0001 + (error if n >= 3 else 0),
             uncertainty_seconds=uncertainty, split="fit" if n < 3 else "validation") for n in range(6)])


def test_sync_holdout_drift_uncertainty_and_failure():
    report = evaluate(markers())
    assert report["timing_target_met"]
    assert not report["field_alignment_evidence"]
    assert report["groups"][0]["drift_ppm"] == pytest.approx(100)
    assert report["groups"][0]["p95_bound_ms"] == pytest.approx(2)
    assert not evaluate(markers(error=0.030))["timing_target_met"]
    assert not evaluate(markers(uncertainty=0.020))["timing_target_met"]
    data = markers()
    data.markers[4].source_seconds = 0
    with pytest.raises(ValueError, match="reset"):
        evaluate(data)


def test_calibration_draft_measured_validation_and_dimensions():
    base = dict(camera_id="a", version="v1", width=32, height=32)
    assert CalibrationRecord(**base).status == "draft"
    with pytest.raises(ValidationError):
        CalibrationRecord(**base, status="measured")
    with pytest.raises(ValidationError):
        CalibrationRecord(**base, goal_roi=[(0, 0), (32, 0), (10, 10)])
    with pytest.raises(ValidationError):
        CalibrationRecord(**base, goal_roi=[(0, 0), (10, 10), (20, 20)])
    measured = CalibrationRecord(**base, status="measured", intrinsics=[[20, 0, 16], [0, 20, 16], [0, 0, 1]],
                                 distortion=[0, 0, 0, 0, 0], reprojection_error_px=0.5,
                                 goal_roi=[(1, 1), (20, 1), (20, 20), (1, 20)])
    assert measured.status == "measured"
    with pytest.raises(ValidationError):
        CalibrationRecord(**base, floor_homography=[[0, 0, 0]] * 3)
    with pytest.raises(ValidationError):
        CalibrationRecord(**base, goal_geometry={"depth": [float("nan")]})
    with pytest.raises(ValidationError):
        CalibrationRecord(**base, goal_roi=[(1, 1), (25, 20), (1, 25), (20, 1)])


def test_record_index_hashes_and_quota(tmp_path):
    guard = StorageGuard(tmp_path, 10000, 0)
    writer = IndexedWriter(tmp_path, "camera/segment.mjpeg", "boot", guard)
    writer.append(frame(0, 0))
    writer.append(frame(1, 1))
    record = writer.close()
    content = (tmp_path / record.path).read_bytes()
    rows = [json.loads(row) for row in (tmp_path / record.index_path).read_text().splitlines()]
    assert [r["byte_offset"] for r in rows] == [0, 4]
    assert record.sha256 == hashlib.sha256(content).hexdigest()
    assert record.index_sha256 == hashlib.sha256((tmp_path / record.index_path).read_bytes()).hexdigest()
    for row in rows:
        assert content[row["byte_offset"]:row["byte_offset"] + row["byte_length"]] == frame(0, 0).jpeg
    with pytest.raises(OSError, match="quota"):
        StorageGuard(tmp_path, 3, 0).claim(4)
    with pytest.raises(OSError, match="reserve"):
        StorageGuard(tmp_path, 10000, shutil.disk_usage(tmp_path).free + 1).claim(1)


def test_clip_pre_post_partial_overflow_and_safe_paths(tmp_path):
    settings = CaptureSettings(clip_pre_seconds=1, clip_post_seconds=1, max_pending_clips=1)
    buffer = ClipBuffer(6, 10000)
    for n in range(3):
        buffer.put(frame(n, n))
    clips = Clips(tmp_path, settings, StorageGuard(tmp_path, 100000, 0))
    clips.fps = {"a": 1}
    try:
        request = ClipRequest(camera_id="a", clip_id="..:unsafe", event_monotonic_seconds=2)
        assert clips.request(request, buffer, 2)["status"] == "collecting"
        assert clips.request(request, buffer, 2)["status"] == "collecting"
        with pytest.raises(DomainError, match="capacity"):
            clips.request(ClipRequest(camera_id="a", clip_id="second"), buffer, 2)
        clips.feed(frame(3, 3))
        wait_until(lambda: clips.status("..:unsafe")["status"] == "ready")
        ready = clips.status("..:unsafe")
        assert ready["coverage"] == "complete"
        assert ready["recording"]["frames"] == 3
        assert (tmp_path / ready["recording"]["path"]).resolve().is_relative_to(tmp_path.resolve())
        clips.request(ClipRequest(camera_id="a", clip_id="shutdown"), buffer, 2)
    finally:
        clips.close()
    assert clips.status("shutdown")["coverage"] == "partial"


def test_clip_storage_failure_is_reported(tmp_path):
    buffer = ClipBuffer(6, 10000)
    buffer.put(frame(0, 1))
    clips = Clips(tmp_path, CaptureSettings(clip_pre_seconds=0, clip_post_seconds=0), StorageGuard(tmp_path, 1, 0))
    try:
        clips.request(ClipRequest(camera_id="a", clip_id="full"), buffer, 1)
        wait_until(lambda: clips.status("full")["status"] == "failed")
    finally:
        clips.close()


@pytest.fixture
def video(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg executable required for actual capture integration")
    path = tmp_path / "fixture.mkv"
    generate(path, ffmpeg, seconds=4, fps=10, size="160x96")
    return path


def test_two_camera_capture_clips_and_independent_reconnect(video, tmp_path):
    settings = CaptureSettings(enabled=True, root=str(tmp_path / "recordings"), min_free_bytes=0,
                               clip_pre_seconds=0.2, clip_post_seconds=0.2, reconnect_seconds=0.1,
                               segment_seconds=1, stale_seconds=1)
    cameras = [CameraConfig(id=name, source=str(video), width=160, height=96, expected_fps=10,
                            reconnect=name == "a") for name in ("a", "b")]
    manager = CaptureManager(cameras, settings)
    try:
        manager.start()
        wait_until(lambda: all(w.record.frames >= 12 for w in manager.workers.values()))
        manager.request_clip(ClipRequest(camera_id="b", clip_id="test-clip"))
        wait_until(lambda: manager.clip_status("test-clip")["status"] == "ready")
        assert manager.clip_status("test-clip")["recording"]["frames"] >= 2
        clip_path = manager.clip_file("test-clip")
        auth = {"Authorization": "Bearer capture-file-test-key"}
        with TestClient(create_app(Settings(database_path=tmp_path / "clip-api.db"), operator_key="capture-file-test-key")) as client:
            client.app.state.capture = manager
            endpoint = "/api/v1/capture/clips/test-clip/file"
            assert client.get(endpoint).status_code == 401
            response = client.get(endpoint, headers=auth)
            assert response.status_code == 200 and response.content == clip_path.read_bytes()
        unaffected = manager.workers["b"].record.frames
        manager.workers["a"].reader.process.terminate()
        wait_until(lambda: manager.workers["a"].record.clock_resets >= 1)
        assert manager.workers["a"].record.reconnects >= 1
        wait_until(lambda: manager.workers["b"].record.frames == 40)
        assert manager.workers["b"].record.frames > unaffected
        assert manager.workers["b"].record.reconnects == 0
    finally:
        manager.close()
    assert not any(w.thread.is_alive() for w in manager.workers.values())
    manifest = RecordingManifest.model_validate_json((manager.root / "manifest.json").read_text())
    assert manifest.status == "closed"
    assert not manifest.timing_alignment_verified
    assert all(not c.calibration_valid for c in manifest.cameras)
    assert str(video) not in manifest.model_dump_json()
    for camera in manifest.cameras:
        assert sum(s.frames for s in camera.segments) == camera.frames
        for segment in camera.segments:
            assert hashlib.sha256((manager.root / segment.path).read_bytes()).hexdigest() == segment.sha256


def test_recording_quota_failure_keeps_live_capture_running(video, tmp_path):
    config = CameraConfig(id="a", source=str(video), width=160, height=96, expected_fps=10, realtime=False, reconnect=False)
    manager = CaptureManager([config], CaptureSettings(enabled=True, root=str(tmp_path / "quota"), min_free_bytes=0, max_session_bytes=1024))
    try:
        manager.start()
        wait_until(lambda: manager.workers["a"].record.frames == 40)
        assert manager.workers["a"].recording_failed
        assert manager.workers["a"].live.take() is not None
    finally:
        manager.close()
    assert json.loads((manager.root / "manifest.json").read_text())["status"] == "failed"


def test_resolution_change_invalidates_measured_calibration_and_preserves_pixels(video, tmp_path):
    path = tmp_path / "calibration.json"
    record = CalibrationRecord(camera_id="a", version="v1", width=32, height=32, status="measured",
        intrinsics=[[20, 0, 16], [0, 20, 16], [0, 0, 1]], distortion=[0, 0, 0, 0],
        reprojection_error_px=0.5, goal_roi=[(1, 1), (20, 1), (20, 20), (1, 20)])
    path.write_text(record.model_dump_json())
    manager = CaptureManager([CameraConfig(id="a", source=str(video), width=32, height=32, expected_fps=10,
        realtime=False, reconnect=False, calibration_path=str(path))],
        CaptureSettings(root=str(tmp_path / "resolution"), min_free_bytes=0))
    try:
        assert manager.workers["a"].record.calibration_valid
        manager.start()
        wait_until(lambda: manager.workers["a"].record.frames == 40)
        camera = manager.status()["cameras"][0]
        assert (camera["observed_width"], camera["observed_height"]) == (160, 96)
        assert not camera["calibration_valid"]
    finally:
        manager.close()
    path.write_text("{}"); manifest = json.loads((manager.root / "manifest.json").read_text())
    assert manifest["cameras"][0]["calibration"]["version"] == "v1"  # Immutable session snapshot.


def test_floor_map_matches_measured_corners():
    np = pytest.importorskip("numpy")
    from tools.calibrate_camera import floor_mapping
    corners = [(10, 10), (110, 10), (110, 60), (10, 60)]
    matrix = np.array(floor_mapping(corners, 15, 10))
    for point, target in zip(corners, [(0, 0), (15, 0), (15, 10), (0, 10)]):
        projected = matrix @ np.array([*point, 1])
        assert projected[:2] / projected[2] == pytest.approx(target)


def test_capture_api_disabled_and_startup_failure_leave_scoring_usable(tmp_path):
    key = "capture-test-key-at-least-16"
    auth = {"Authorization": f"Bearer {key}"}
    for enabled in (False, True):
        settings = Settings(database_path=tmp_path / f"{enabled}.db", capture=CaptureSettings(enabled=enabled,
                            root=str(tmp_path / "bad"), ffmpeg="nonexistent-neon-ffmpeg"),
                            cameras=[CameraConfig(id="a", source="credential://user:secret@camera")])
        with TestClient(create_app(settings, operator_key=key)) as client:
            assert client.get("/api/v1/capture/status").status_code == 401
            status = client.get("/api/v1/capture/status", headers=auth).json()
            assert status["enabled"] is False
            assert bool(status["error"]) == enabled
            assert "secret" not in json.dumps(status)
            assert client.post("/api/v1/capture/clips", headers=auth, json={"camera_id": "a", "clip_id": "test"}).status_code == 503
            assert client.post("/api/v1/matches", headers=auth,
                json={"command_id": "create", "expected_revision": 0, "action": "create", "payload": {}}).status_code == 201
