"""Generate labelled numerical trajectories for logic tests, never football accuracy."""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.capture import CalibrationRecord
from core.dataset import Annotation, AnnotationSet, Asset, DatasetManifest, DatasetSession, MatchWindow, SessionAudit
from core.vision import DepthPosition, Detection, GoalView, VisionFrame, VisionSettings
from modules.replay.dataset import digest


def fixture_settings():
    views = []
    for camera, end in [("goal-a", "goal_a"), ("goal-b", "goal_b")]:
        calibration = CalibrationRecord(camera_id=camera, version="synthetic-geometry-v1", status="measured",
            width=320, height=180, intrinsics=[[250, 0, 160], [0, 250, 90], [0, 0, 1]], distortion=[0]*5,
            reprojection_error_px=.1, goal_roi=[(100, 20), (250, 20), (250, 160), (100, 160)],
            net_roi=[(120, 30), (240, 30), (240, 150), (120, 150)], notes="Synthetic test coordinates; NOT a venue measurement")
        views.append(GoalView(camera_id=camera, goal_end=end, calibration=calibration,
            calibration_evidence="synthetic",
            depth_calibration_id="synthetic-rig-v1", opening_width_m=3, opening_height_m=2,
            ball_radius_m=.11, image_inward_direction=(1, 0)))
    return VisionSettings(version="synthetic-vision-v1", views=views)


def fixture_frame(sequence, time, z=None, *, camera="goal-a", boot="test-epoch", x=1.5, y=1,
                  center=(160, 90), missing=False, **kwargs):
    depth = None if z is None else DepthPosition(x_m=x, y_m=y, z_m=z, uncertainty_m=(.005, .005, .005),
        calibration_id="synthetic-rig-v1", clock_domain="fixture-clock", method="synthetic", synchronized=True)
    detections = [] if missing else [Detection(kind="ball", bbox=(center[0]-3, center[1]-3, center[0]+3, center[1]+3), score=.95, depth=depth)]
    return VisionFrame(session_id="vision-validation", match_id="vision-match", camera_id=camera, boot_id=boot,
        sequence=sequence, width=320, height=180, occurred_seconds=time, received_seconds=time+.005,
        clock_domain="fixture-clock", timing_uncertainty_seconds=.005, evidence="synthetic", detections=detections, **kwargs)


def build(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    frames, labels = [], []

    def reference(name, time, end="goal_a", validity="valid", challenge="ordinary"):
        labels.append(Annotation(label_id=name, session_id="vision-validation", match_id="vision-match",
            crossing_start_seconds=time-.002, crossing_end_seconds=time+.002, goal_end=end,
            team="orange" if validity == "valid" else None, validity=validity, visibility="clear",
            uncertainty_seconds=.003, challenge=challenge, adjudicator="synthetic-builder"))

    # Each independent case uses a fresh source boot. A/B observations are interleaved at replay.
    cases = [("ordinary-a", 1, "goal-a", 1.5), ("ordinary-b", 2, "goal-b", 1.5), ("post-in", 3, "goal-a", .12),
             ("partial", 4, "goal-a", 1.5), ("outside", 5, "goal-a", -.5), ("outward", 6, "goal-a", 1.5),
             ("ambiguous", 7, "goal-a", 1.5), ("occluded", 8, "goal-a", 1.5), ("stale", 9, "goal-a", 1.5),
             ("image-only", 10, "goal-a", 1.5), ("net-only", 11, "goal-a", 1.5), ("player-impact", 12, "goal-a", 1.5)]
    for name, base, camera, x in cases:
        if name == "occluded":
            frames += [fixture_frame(0, base, -.3, boot=name), fixture_frame(1, base+.05, -.15, boot=name),
                       fixture_frame(2, base+.1, missing=True, boot=name), fixture_frame(3, base+.15, missing=True, boot=name)]
            reference(name, base+.14)
            continue
        if name == "image-only":
            frames += [fixture_frame(0, base, center=(80, 90), boot=name), fixture_frame(1, base+.1, center=(120, 90), boot=name)]
            reference(name, base+.1, validity="uncertain")
            continue
        if name in ("net-only", "player-impact"):
            from core.vision import MotionEvidence
            frame = fixture_frame(0, base, missing=True, boot=name,
                motion=MotionEvidence(net_changed_fraction=.8, global_changed_fraction=.1, baseline_frames=10))
            if name == "player-impact":
                frame.detections = [Detection(kind="player", bbox=(120, 20, 200, 150), score=.9)]
            frames.append(frame)
            reference(name, base, validity="invalid", challenge="player_impact" if name == "player-impact" else "loose_net")
            continue
        first, last = (.2, -.2) if name == "outward" else (-.2, .05 if name == "partial" else .2)
        a, b = fixture_frame(0, base, first, camera=camera, boot=name, x=x), fixture_frame(1, base+.1, last, camera=camera, boot=name, x=x)
        if name == "ambiguous":
            a.detections.append(Detection(kind="ball", bbox=(165, 87, 171, 93), score=.8))
        if name == "stale":
            b.received_seconds = base+.5
        frames += [a, b]
        if name in ("ordinary-a", "ordinary-b", "post-in", "ambiguous", "stale"):
            reference(name, base+.08, end="goal_b" if camera == "goal-b" else "goal_a", challenge="post_and_in" if name == "post-in" else "ordinary")
        else:
            reference(name, base+.1, validity="invalid", challenge="partial_crossing" if name == "partial" else "outside_net" if name == "outside" else "ball_retrieval")
    observations = root / "observations.jsonl"
    observations.write_text("".join(f.model_dump_json()+"\n" for f in frames), encoding="utf-8")
    # Retain Part03 manifest interoperability without inventing injected score decisions.
    events = root / "events.jsonl"
    events.write_text("", encoding="utf-8")
    dataset = DatasetManifest(dataset_id="vision-numerical-fixture-v1", annotation_policy_version="annotation-policy-v1",
        split_assignment_version="synthetic-validation-v1", split_frozen_at=datetime(2026, 10, 11, tzinfo=timezone.utc),
        sessions=[DatasetSession(session_id="vision-validation", source_group_id="synthetic-trajectories", split="validation",
            evidence="synthetic", duration_seconds=15, host_clock_domain="fixture-clock", configuration_version="synthetic-vision-v1",
            model_version="injected-trajectories-no-detector-v1", matches=[MatchWindow(match_id="vision-match", start_seconds=0, end_seconds=15)],
            calibration_versions={v.camera_id: v.calibration.version for v in fixture_settings().views},
            conditions=["numerical-test-not-football"], assets=[Asset(path=observations.name, sha256=digest(observations), kind="vision_observations"),
                Asset(path=events.name, sha256=digest(events), kind="replay_events")])])
    annotations = AnnotationSet(dataset_id=dataset.dataset_id, version="synthetic-vision-labels-v1", split="validation",
        annotation_policy_version=dataset.annotation_policy_version, labels=labels,
        audits=[SessionAudit(session_id="vision-validation", continuous_footage_reviewed=False, reviewer="synthetic-builder",
            notes="Numerical acceptance cases; no video ground truth")])
    for name, contract in [("settings.json", fixture_settings()), ("dataset.json", dataset), ("annotations.json", annotations)]:
        (root/name).write_text(json.dumps(contract.model_dump(mode="json"), indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return dataset


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    build(parser.parse_args().root)
    print("Generated synthetic geometry/trajectory validation fixture")
