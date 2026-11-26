from datetime import datetime, timezone, timedelta
import hashlib
import json

import pytest

from core.capture import RecordingManifest, CameraRecord, CaptureSettings, SegmentRecord
from core.operations import RetentionPolicy
from modules.capture.retention import apply_retention, plan_retention


def recording(root, name="session", *, status="closed"):
    session = root / name
    session.mkdir(parents=True)
    (session / "raw.mjpeg").write_bytes(b"dummy-media")
    (session / "raw.jsonl").write_bytes(b"dummy-index")
    segment = SegmentRecord(path="raw.mjpeg", index_path="raw.jsonl", boot_id="boot", frames=1, bytes=11,
        sha256=hashlib.sha256(b"dummy-media").hexdigest(), index_sha256=hashlib.sha256(b"dummy-index").hexdigest(), complete=True)
    end = datetime.now(timezone.utc) - timedelta(days=60)
    manifest = RecordingManifest(session_id=name, host_clock_domain="host", started_at=end-timedelta(seconds=5), ended_at=end,
        status=status, backend_version="dummy", capture_settings=CaptureSettings(),
        cameras=[CameraRecord(camera_id="a", kind="dummy", width=32, height=32, expected_fps=1, segments=[segment])])
    (session / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    (session / "incidents.jsonl").write_text("keep audit\n", encoding="utf-8")
    (session / "clips").mkdir()
    (session / "clips/clip.mjpeg").write_bytes(b"clip")
    (session / "clips/clip.jsonl").write_bytes(b"index")
    clip = segment.model_copy(update=dict(path="clips/clip.mjpeg", index_path="clips/clip.jsonl",
        sha256=hashlib.sha256(b"clip").hexdigest(), index_sha256=hashlib.sha256(b"index").hexdigest()))
    (session / "clips/clip.json").write_text(json.dumps(dict(status="ready", recording=clip.model_dump())))
    return session


def test_retention_is_disabled_by_default_and_preserves_audit_holds_and_active(tmp_path):
    root = tmp_path / "recordings"
    expired = recording(root)
    held = recording(root, "held")
    active = recording(root, "active", status="recording")
    policy = RetentionPolicy(holds={"held": "Approved training owner: fixture"})
    plan = plan_retention(root, policy)
    assert len(plan["files"]) == 4
    assert {s["reason"] for s in plan["skipped"]} == {"held", "not_closed"}
    with pytest.raises(ValueError, match="disabled"):
        apply_retention(plan)
    assert (expired / "raw.mjpeg").exists()
    policy.enabled = True
    result = apply_retention(plan_retention(root, policy))
    assert len(result["removed"]) == 4 and not result["audit_logs_deleted"]
    assert (expired / "manifest.json").exists() and (expired / "clips/clip.json").exists()
    assert (expired / "incidents.jsonl").read_text() == "keep audit\n"
    assert (held / "raw.mjpeg").exists() and (active / "raw.mjpeg").exists()
    assert len((root / "retention-events.jsonl").read_text().splitlines()) == 8
    assert plan_retention(root, policy)["files"] == []


def test_retention_rejects_tamper_and_changed_hold_before_deletion(tmp_path):
    root = tmp_path / "recordings"; session = recording(root)
    policy = RetentionPolicy(enabled=True)
    plan = plan_retention(root, policy)
    path = session / "manifest.json"
    manifest = json.loads(path.read_text()); manifest["status"] = "recording"; path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="changed"):
        apply_retention(plan)
    assert (session / "raw.mjpeg").exists()
    manifest["status"] = "closed"; path.write_text(json.dumps(manifest))
    (session / "raw.mjpeg").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        plan_retention(root, policy)


@pytest.mark.parametrize("bad_path", ["../outside.mjpeg", "/absolute.mjpeg", "manifest.json"])
def test_retention_never_deletes_unregistered_or_escaping_paths(tmp_path, bad_path):
    root = tmp_path / "recordings"; session = recording(root)
    path = session / "manifest.json"
    manifest = json.loads(path.read_text()); manifest["cameras"][0]["segments"][0]["path"] = bad_path
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        plan_retention(root, RetentionPolicy(enabled=True))
    assert (session / "raw.mjpeg").exists()
