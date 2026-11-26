import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.vision import Detection, VisionFrame
from modules.vision.engine import VisionEngine
from tools.build_vision_fixture import fixture_frame as frame, fixture_settings as settings


def engine():
    return VisionEngine(settings(), "test-detector")


def test_observed_whole_ball_not_center_crossing():
    e = engine()
    e.process(frame(0, 1, -.2))
    assert e.process(frame(1, 1.03, .01))["candidates"] == []
    c = e.process(frame(2, 1.1, .2))["candidates"][0]
    assert c["quality"] == "observed_crossing"
    assert c["occurred_seconds"] == pytest.approx(1.08)
    assert c["crossing_interval_seconds"] == [1, 1.1]
    assert c["timing_uncertainty_seconds"] >= .1
    assert c["requires_review"] and not c["automatic_confirmation_allowed"]
    assert e.process(frame(3, 1.12, .3))["candidates"] == []


@pytest.mark.parametrize("start,end,x", [(-.2, .05, 1.5), (.2, -.2, 1.5), (-.2, .2, -.5), (-.2, .2, 3.5)])
def test_partial_outward_and_outside_are_not_crossings(start, end, x):
    e = engine()
    e.process(frame(0, 1, start, x=x))
    assert e.process(frame(1, 1.1, end, x=x))["candidates"] == []


def test_uncertain_post_and_prediction_remain_review():
    e = engine()
    e.process(frame(0, 1, -.2, x=.12))
    assert e.process(frame(1, 1.1, .2, x=.12))["candidates"][0]["quality"] == "boundary_uncertain"
    e = engine()
    e.process(frame(0, 2, -.3))
    e.process(frame(1, 2.05, -.15))
    assert not e.process(frame(2, 2.1, missing=True))["candidates"]
    c = e.process(frame(3, 2.15, missing=True))["candidates"][0]
    assert c["quality"] == "predicted_crossing" and "prediction_only" in c["flags"]
    result = e.process(frame(4, 2.3, missing=True))
    assert result["track"] is None and result["candidates"] == []


@pytest.mark.parametrize("flag", ["timing_unverified", "camera_shake_or_global_motion", "player_overlap", "association_ambiguous"])
def test_bad_front_evidence_survives_into_candidate(flag):
    e = engine()
    a = frame(0, 1, -.2)
    if flag == "timing_unverified":
        a.timing_uncertainty_seconds = None
    elif flag == "association_ambiguous":
        a.detections.append(Detection(kind="ball", bbox=(165, 87, 171, 93), score=.8))
    else:
        a.motion.flags = [flag]
    e.process(a)
    c = e.process(frame(1, 1.1, .2))["candidates"][0]
    assert c["quality"] == "boundary_uncertain" and flag in c["flags"]


def test_no_depth_fabricated_from_floor_homography():
    s = settings()
    s.views[0].calibration.floor_homography = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    e = VisionEngine(s, "test")
    e.process(frame(0, 1, center=(80, 90)))
    result = e.process(frame(1, 1.1, center=(120, 90)))
    assert result["track"]["depth"] is None
    assert result["candidates"][0]["quality"] == "depth_ambiguous"


@pytest.mark.parametrize("failure", ["draft", "resize", "reprojection", "stale"])
def test_invalid_calibration_or_stale_clears_crossing_history(failure):
    s = settings()
    if failure == "draft":
        s.views[0].calibration.status = "draft"
    if failure == "reprojection":
        s.views[0].calibration.reprojection_error_px = 3
    e = VisionEngine(s, "test")
    e.process(frame(0, 1, -.2))
    b = frame(1, 1.1, .2)
    if failure == "resize":
        b.width = 640
    if failure == "stale":
        b.received_seconds = 2
    result = e.process(b)
    assert result["track"] is None and result["candidates"] == [] and result["flags"]
    assert e.process(frame(2, 2.1, .3))["candidates"] == []


@pytest.mark.parametrize("change", ["boot_id", "match_id", "clock_domain", "evidence"])
def test_epoch_changes_cannot_complete_old_crossing(change):
    e = engine()
    e.process(frame(0, 1, -.2))
    b = frame(1, 1.1, .2)
    setattr(b, change, "venue" if change == "evidence" else "new-identity")
    if change == "evidence":
        b.detections[0].depth.method = "external_depth"
    result = e.process(b)
    assert not result["candidates"] and "stream_epoch_reset" in result["flags"]


def test_clock_depth_mismatch_and_regression_rejected():
    e = engine()
    e.process(frame(0, 1, -.2))
    b = frame(1, 1.1, .2)
    b.detections[0].depth.clock_domain = "wrong"
    assert not e.process(b)["candidates"]
    with pytest.raises(ValueError, match="regressed"):
        e.process(frame(1, 1.2, .2))


def test_config_is_copied_and_frame_contract_rejects_unsafe_evidence():
    s = settings()
    e = VisionEngine(s, "test")
    s.views[0].opening_width_m = 100
    assert e.views["goal-a"].opening_width_m == 3
    for updates in [dict(evidence="venue"), dict(clip_path="../outside.mjpeg"), dict(occurred_seconds=float("nan")), dict(width=100)]:
        with pytest.raises(ValidationError):
            VisionFrame.model_validate({**frame(0, 1, -.2).model_dump(), **updates})
    # A valid-looking external depth stream must still reject synthetic/unverified calibration.
    for evidence in ("synthetic", "unverified"):
        config = settings()
        config.views[0].calibration_evidence = evidence
        guard = VisionEngine(config, "test")
        for sequence, time, z in [(0, 3, -.2), (1, 3.1, .2)]:
            observation = frame(sequence, time, z)
            observation.evidence = "venue"
            observation.detections[0].depth.method = "external_depth"
            result = guard.process(observation)
            assert not result["candidates"] and "calibration_evidence_not_venue" in result["flags"]


def test_net_cue_is_rising_edge_and_players_suppress_it():
    e = engine()
    a = frame(0, 1, missing=True)
    a.motion.net_changed_fraction = .8
    assert e.process(a)["candidates"][0]["quality"] == "net_motion_only"
    a.sequence, a.occurred_seconds, a.received_seconds = 1, 1.1, 1.105
    assert not e.process(a)["candidates"]
    a.boot_id, a.sequence = "new", 0
    a.detections = [Detection(kind="player", bbox=(120, 20, 200, 150), score=.9)]
    assert not e.process(a)["candidates"]
