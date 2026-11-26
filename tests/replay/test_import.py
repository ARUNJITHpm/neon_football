from datetime import datetime, timezone
import json

import pytest

from core.capture import (CameraRecord, EncodedFrame, FrameMetadata, RecordingManifest, CaptureSettings, TimingEnvelope)
from modules.capture.recording import IndexedWriter, StorageGuard
from modules.replay.runner import replay
from tools.import_capture_session import register


def recording(root):
    root.mkdir()
    writer = IndexedWriter(root, "camera/test.mjpeg", "boot", StorageGuard(root, 100000, 0))
    for n in range(2):
        timing = TimingEnvelope(source_id="a", boot_id="boot", sequence=n, source_sequence=n, source_seconds=18+n,
            source_clock_domain="media:a", host_clock_domain="host", host_monotonic_seconds=10+n,
            received_at=datetime.now(timezone.utc), quality="media_pts")
        writer.append(EncodedFrame(FrameMetadata(camera_id="a", width=32, height=32, timing=timing), b"\xff\xd8\xff\xd9"))
    segment = writer.close()
    manifest = RecordingManifest(session_id="capture-fixture", host_clock_domain="host", started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc), status="closed", backend_version="synthetic-index-fixture",
        capture_settings=CaptureSettings(), cameras=[CameraRecord(camera_id="a", kind="file", width=32, height=32,
            expected_fps=10, frames=2, encoded_bytes=8, segments=[segment])])
    (root / "manifest.json").write_text(manifest.model_dump_json())
    return manifest


def test_capture_import_preserves_source_timing_without_inventing_crossing(tmp_path):
    capture = tmp_path / "capture"
    recording(capture)
    output = tmp_path / "registered"
    result = register(capture, output, tmp_path, dataset_id="d", source_group_id="source", match_id="m",
                      split="validation", evidence="synthetic")
    registered = replay(output / "dataset.json", media_root=tmp_path)
    assert len(registered.trace) == 2 and registered.decisions == []
    assert registered.trace[0]["virtual_seconds"] == 0
    assert registered.trace[1]["virtual_seconds"] == 1
    assert not result.sessions[0].physical_alignment_verified
    rows = [json.loads(line) for line in (output / "frames.jsonl").read_text().splitlines()]
    assert rows[0]["source_timing"]["source_seconds"] == 18
    assert rows[0]["source_timing"]["host_monotonic_seconds"] == 10
    assert rows[0]["goal_end"] is None
    annotations = json.loads((output / "annotations.json").read_text())
    assert annotations["labels"] == []
    assert not annotations["audits"][0]["continuous_footage_reviewed"]


def test_capture_import_rejects_tampering_partial_segments_and_escaping_paths(tmp_path):
    capture = tmp_path / "capture"
    original = recording(capture)
    def run():
        return register(capture, tmp_path / "out", tmp_path, dataset_id="d", source_group_id="source", match_id="m",
                        split="validation", evidence="synthetic")
    path = capture / original.cameras[0].segments[0].path
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        run()
    path.write_bytes(b"\xff\xd8\xff\xd9" * 2)
    original.cameras[0].segments[0].complete = False
    (capture / "manifest.json").write_text(original.model_dump_json())
    with pytest.raises(ValueError, match="Incomplete"):
        run()
    original.cameras[0].segments[0].complete = True
    original.cameras[0].segments[0].path = "../private.mp4"
    (capture / "manifest.json").write_text(original.model_dump_json())
    with pytest.raises(ValueError, match="relative"):
        run()
