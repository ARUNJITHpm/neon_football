import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("onnxruntime")
Image = pytest.importorskip("PIL.Image")

from core.vision import Detection, ModelDescriptor
from modules.vision.detector import OnnxDetector
from modules.vision.motion import NetMotion
from tools.build_vision_model_fixture import build


def test_real_onnx_session_letterbox_nms_and_no_depth(tmp_path):
    descriptor = build(tmp_path)
    detector = OnnxDetector(descriptor, tmp_path)
    results, timings = detector.detect(Image.new("RGB", (320, 180)))
    assert [d.kind for d in results] == ["ball", "player"]
    assert results[0].bbox == pytest.approx((50, 60, 110, 120))
    assert all(d.depth is None for d in results) and all(t >= 0 for t in timings.values())
    assert descriptor.purpose == "synthetic_adapter_test"


@pytest.mark.parametrize("failure", ["checksum", "input", "output", "licence"])
def test_model_registration_and_layout_fail_closed(tmp_path, failure):
    descriptor = build(tmp_path)
    if failure == "checksum":
        (tmp_path/"constant.onnx").write_bytes(b"changed")
    if failure == "input":
        descriptor.input_width = 64
    if failure == "output":
        descriptor.class_count = 3
    if failure == "licence":
        descriptor.purpose, descriptor.licence_decision = "pretrained", "not_reviewed"
    with pytest.raises(ValueError):
        detector = OnnxDetector(descriptor, tmp_path)
        detector.detect(Image.new("RGB", (32, 32)))


@pytest.mark.parametrize("failure", ["logits", "nonfinite", "transposed"])
def test_detector_rejects_unknown_score_and_output_formats(tmp_path, monkeypatch, failure):
    detector = OnnxDetector(build(tmp_path), tmp_path)
    output = np.zeros((1, 6, 1), dtype=np.float32)
    if failure == "logits":
        output[0, 4, 0] = 2
    elif failure == "nonfinite":
        output[0, 0, 0] = np.nan
    else:
        output = output.transpose(0, 2, 1)
    monkeypatch.setattr(detector.session, "run", lambda *args: [output])
    with pytest.raises(ValueError):
        detector.detect(Image.new("RGB", (32, 32)))


def test_motion_warmup_net_change_global_and_player_quality():
    polygon = [(100, 20), (220, 20), (220, 160), (100, 160)]
    motion = NetMotion(polygon, (320, 180))
    stable = Image.new("L", (320, 180), 50)
    for _ in range(5):
        assert "baseline_warming" in motion.update(stable).flags
    assert not motion.update(stable).flags
    pixels = np.full((180, 320), 50, dtype=np.uint8)
    pixels[30:150, 110:210] = 150
    changed = Image.fromarray(pixels)
    cue = motion.update(changed)
    assert cue.net_changed_fraction > .5 and cue.global_changed_fraction < .4
    assert not cue.flags
    assert "camera_shake_or_global_motion" in motion.update(Image.new("L", (320, 180), 200)).flags
    player = Detection(kind="player", bbox=(110, 30, 150, 140), score=.9)
    assert "player_overlap" in motion.update(changed, [player]).flags
    assert "roi_unavailable" in NetMotion([], (320, 180)).update(stable).flags
    with pytest.raises(ValueError, match="resolution"):
        motion.update(Image.new("L", (640, 360)))
