"""Register a Part 02 recording as an unlabeled, receipt-time replay dataset."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.capture import RecordingManifest, TimingEnvelope
from core.dataset import (AnnotationSet, Asset, DatasetManifest, DatasetSession, MatchWindow, ReplayEvent, SessionAudit)
from modules.replay.dataset import asset_path, digest


def register(capture, output, media_root, *, dataset_id, source_group_id, match_id, split, evidence):
    capture, output, media_root = Path(capture).resolve(), Path(output).resolve(), Path(media_root).resolve()
    if not capture.is_relative_to(media_root) or not output.is_relative_to(media_root):
        raise ValueError("Recording and metadata output must both be inside media_root")
    manifest_path = capture / "manifest.json"
    original = RecordingManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if original.status != "closed":
        raise ValueError("Import requires a cleanly closed recording; review partial/orphan media separately")
    assets, frames = [], []
    seen_paths = set()
    for camera in original.cameras:
        for segment in camera.segments:
            if not segment.complete:
                raise ValueError("Incomplete camera segment cannot silently enter the dataset")
            for kind, relative, expected in [("video", segment.path, segment.sha256), ("frame_index", segment.index_path, segment.index_sha256)]:
                from core.dataset import relative_path
                relative_path(relative)
                target = asset_path(capture, relative)
                if relative in seen_paths or digest(target) != expected:
                    raise ValueError("Repeated segment path or capture checksum mismatch")
                seen_paths.add(relative)
                assets.append(Asset(path=target.relative_to(media_root).as_posix(), sha256=expected, kind=kind))
            index = asset_path(capture, segment.index_path)
            position = 0
            local = []
            with index.open(encoding="utf-8") as handle:
                for row in handle:
                    value = json.loads(row)
                    timing = TimingEnvelope.model_validate(value["timing"])
                    if (value["camera_id"] != camera.camera_id or timing.source_id != camera.camera_id or
                            timing.host_clock_domain != original.host_clock_domain or timing.boot_id != segment.boot_id or
                            value["byte_offset"] != position or value["byte_length"] <= 0):
                        raise ValueError("Recording index identity or byte boundary mismatch")
                    position += value["byte_length"]
                    local.append((camera.camera_id, timing))
            if len(local) != segment.frames or position != segment.bytes or position != asset_path(capture, segment.path).stat().st_size:
                raise ValueError("Recording segment frame/byte totals disagree with index")
            frames.extend(local)
    if not frames:
        raise ValueError("Recording has no indexed frames")
    frames.sort(key=lambda row: (row[1].host_monotonic_seconds, row[0], row[1].sequence))
    identity = [(camera, timing.sequence) for camera, timing in frames]
    if len(set(identity)) != len(identity):
        raise ValueError("Duplicate camera frame sequence in recording")
    origin = frames[0][1].host_monotonic_seconds
    duration = frames[-1][1].host_monotonic_seconds-origin + 1/min(c.expected_fps for c in original.cameras)
    # This is a receipt timeline only: no physical source->host mapping is invented.
    events = [ReplayEvent(event_id=f"frame-{sequence}", session_id=original.session_id, match_id=match_id,
                sequence=sequence, occurred_seconds=timing.host_monotonic_seconds-origin,
                delivered_seconds=timing.host_monotonic_seconds-origin, kind="observation",
                source_timing=timing, payload={"camera_id": camera, "camera_frame_sequence": timing.sequence,
                                             "timeline_quality": "receipt_only", "goal_end_unmapped": True})
              for sequence, (camera, timing) in enumerate(frames)]
    output.mkdir(parents=True, exist_ok=False)
    event_path = output / "frames.jsonl"
    with event_path.open("x", encoding="utf-8") as handle:
        for event in events:
            handle.write(event.model_dump_json() + "\n")
    assets += [Asset(path=event_path.relative_to(media_root).as_posix(), sha256=digest(event_path), kind="replay_events"),
               Asset(path=manifest_path.relative_to(media_root).as_posix(), sha256=digest(manifest_path), kind="recording_manifest")]
    dataset = DatasetManifest(dataset_id=dataset_id, annotation_policy_version="annotation-policy-v1",
        split_assignment_version="operator-assigned-v1", split_frozen_at=datetime.now(timezone.utc),
        sessions=[DatasetSession(session_id=original.session_id, source_group_id=source_group_id, split=split,
            evidence=evidence, duration_seconds=duration, host_clock_domain=original.host_clock_domain,
            configuration_version="capture-schema-1", model_version="none-frame-observations",
            calibration_versions={c.camera_id: c.calibration.version if c.calibration else None for c in original.cameras},
            matches=[MatchWindow(match_id=match_id, start_seconds=0, end_seconds=duration)], assets=assets,
            physical_alignment_verified=False, conditions=["imported-receipt-timeline"])])
    annotation = AnnotationSet(dataset_id=dataset_id, split=split, version="unlabelled-draft-1", annotation_policy_version=dataset.annotation_policy_version,
        labels=[], audits=[SessionAudit(session_id=original.session_id, continuous_footage_reviewed=False, reviewer="not-reviewed",
                    notes=f"Receipt origin {origin}; match window and goal ends are provisional. Assign actual match windows, camera ends and physical timeline before labeling.")])
    for filename, contract in [("dataset.json", dataset), ("annotations.json", annotation)]:
        (output / filename).write_text(contract.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--source-group", required=True)
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--split", choices=["train", "validation", "blind_test"], required=True)
    parser.add_argument("--evidence", choices=["synthetic", "venue"], required=True)
    args = parser.parse_args()
    result = register(args.capture, args.output, args.media_root, dataset_id=args.dataset_id, source_group_id=args.source_group,
                      match_id=args.match_id, split=args.split, evidence=args.evidence)
    print(f"Registered {result.sessions[0].session_id}; labels/audit and physical timing remain pending")


if __name__ == "__main__":
    main()
