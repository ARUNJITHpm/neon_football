"""Checksum/split-guarded offline vision observations -> candidates and candidate-only metrics."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dataset import AnnotationSet, DatasetManifest
from core.vision import VisionCandidate, VisionFrame, VisionSettings
from modules.replay.dataset import asset_path, digest, select, validate_annotations
from modules.replay.matching import match
from modules.replay.statistics import poisson_rate, proportion
from modules.vision.engine import VisionEngine


def candidate_metrics(labels, candidates, seconds, tolerance=.5):
    if not 0 < tolerance <= 5 or seconds <= 0:
        raise ValueError("Invalid tolerance or scheduled exposure")
    if len({c.event_id for c in candidates}) != len(candidates):
        raise ValueError("Duplicate candidate event identity")
    same = lambda l, c: (l.session_id, l.match_id, l.goal_end) == (c.session_id, c.match_id, c.goal_end)
    valid = [l for l in labels if l.validity == "valid"]
    uncertain = [l for l in labels if l.validity == "uncertain"]
    pairs = match(valid, candidates, tolerance, compatible=same)
    assigned = {c.event_id for _, c in pairs}
    unknown = [c for c in candidates if c.event_id not in assigned and any(same(l, c) and
               abs(l.crossing_seconds-c.occurred_seconds) <= tolerance for l in uncertain)]
    false_count = len(candidates)-len(pairs)-len(unknown)
    unknown_ids = {c.event_id for c in unknown}
    matched_labels = {l.label_id for l, _ in pairs}
    return dict(counts=dict(valid_references=len(valid), candidates=len(candidates), true_positives=len(pairs),
                false_candidates=false_count, misses=len(valid)-len(pairs), unadjudicated=len(unknown)),
        candidate_recall=proportion(len(pairs), len(valid)), false_candidates_per_hour=poisson_rate(false_count, seconds/3600),
        scheduled_seconds=seconds, matching_tolerance_seconds=tolerance,
        qualities=dict(sorted(Counter(c.quality for c in candidates).items())),
        errors=dict(missed_label_ids=[l.label_id for l in valid if l.label_id not in matched_labels],
            false_candidates=[dict(event_id=c.event_id, camera_id=c.camera_id, quality=c.quality, clip_path=c.clip_path)
                for c in candidates if c.event_id not in assigned and c.event_id not in unknown_ids],
            unadjudicated_candidate_ids=sorted(unknown_ids)),
        matched_pairs=[dict(label_id=l.label_id, event_id=c.event_id,
            error_seconds=c.occurred_seconds-l.crossing_seconds) for l, c in pairs],
        scoring_accuracy_measured=False, automatic_confirmation_allowed=False,
        interpretation="One-to-one goal-end candidate matching; team attribution and cross-view fusion are not evaluated")


def run(manifest_path, settings_path, annotations_path, split="validation", media_root=None, allow_blind_test=False):
    manifest_path, settings_path, annotations_path = map(Path, (manifest_path, settings_path, annotations_path))
    manifest = DatasetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    settings = VisionSettings.model_validate_json(settings_path.read_text(encoding="utf-8"))
    annotations = AnnotationSet.model_validate_json(annotations_path.read_text(encoding="utf-8"))
    sessions = select(manifest, split, allow_blind_test)
    labels = validate_annotations(manifest, annotations, sessions)
    root = Path(media_root) if media_root else manifest_path.parent
    frames, inputs = [], []
    for session in sessions:
        for asset in session.assets:
            path = asset_path(root, asset.path)
            if digest(path) != asset.sha256:
                raise ValueError(f"Asset checksum differs: {asset.path}")
            inputs.append(dict(session_id=session.session_id, path=asset.path, sha256=asset.sha256))
        assets = [a for a in session.assets if a.kind == "vision_observations"]
        if len(assets) != 1:
            raise ValueError("Register exactly one vision_observations JSONL asset per selected session")
        if session.configuration_version != settings.version:
            raise ValueError("Vision configuration differs from session registration")
        with asset_path(root, assets[0].path).open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                if len(frames) >= settings.max_frame_count:
                    raise ValueError("Vision frame capacity reached; partition the dataset")
                frame = VisionFrame.model_validate_json(line)
                window = next((m for m in session.matches if m.match_id == frame.match_id), None)
                if (frame.session_id != session.session_id or frame.evidence != session.evidence or
                    frame.clock_domain != session.host_clock_domain or window is None or
                    not window.start_seconds <= frame.occurred_seconds < window.end_seconds or
                    frame.received_seconds > session.duration_seconds):
                    raise ValueError("Vision observation exceeds registered identity/clock/match boundary")
                view = next((v for v in settings.views if v.camera_id == frame.camera_id), None)
                if view is None or session.calibration_versions.get(frame.camera_id) != view.calibration.version:
                    raise ValueError("Unregistered vision calibration/camera")
                if frame.clip_path and not any(a.path == frame.clip_path and a.kind in ("video", "clip") for a in session.assets):
                    raise ValueError("Vision clip is not a registered media asset")
                frames.append((session.model_version, frame))
    frames.sort(key=lambda item: (item[1].session_id, item[1].received_seconds, item[1].camera_id, item[1].sequence))
    engines, candidates, trace = {}, [], []
    for model_version, frame in frames:
        engine = engines.setdefault(frame.session_id, None)
        if engine is None:
            engine = engines[frame.session_id] = VisionEngine(settings, model_version)
        result = engine.process(frame)
        candidates.extend(VisionCandidate.model_validate(c) for c in result["candidates"])
        trace.append(dict(session_id=frame.session_id, camera_id=frame.camera_id, sequence=frame.sequence, **result))
    seconds = sum(m.end_seconds-m.start_seconds for s in sessions for m in s.matches)
    implementation = {str(path.relative_to(Path(__file__).resolve().parents[1])): digest(path) for path in
        [Path(__file__), *sorted((Path(__file__).resolve().parents[1]/"modules/vision").glob("*.py")),
         Path(__file__).resolve().parents[1]/"core/vision.py", Path(__file__).resolve().parents[1]/"core/dataset.py",
         Path(__file__).resolve().parents[1]/"modules/replay/matching.py",
         Path(__file__).resolve().parents[1]/"modules/replay/statistics.py",
         Path(__file__).resolve().parents[1]/"modules/replay/dataset.py"]}
    per_session = [dict(session_id=s.session_id, conditions=s.conditions, evidence=s.evidence,
        **candidate_metrics([l for l in labels if l.session_id == s.session_id],
            [c for c in candidates if c.session_id == s.session_id], sum(m.end_seconds-m.start_seconds for m in s.matches))) for s in sessions]
    return dict(schema_version=1, engine="vision-candidates-v1", dataset_id=manifest.dataset_id, split=split,
        provenance=dict(manifest_sha256=digest(manifest_path), settings_sha256=digest(settings_path),
            annotations_sha256=digest(annotations_path), inputs=inputs, implementation=implementation,
            model_versions={s.session_id: s.model_version for s in sessions},
            detector_inference=False, observations="Injected/imported detection and depth observations"),
        evidence=sorted({s.evidence for s in sessions}), frame_count=len(frames), trace=trace,
        candidates=[c.model_dump(mode="json") for c in candidates], metrics=candidate_metrics(labels, candidates, seconds), per_session=per_session,
        release_qualified=False, field_gate="pending real detector, held-out venue labels, calibration and two-stream live capacity")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--split", choices=["train", "validation", "blind_test"], default="validation")
    parser.add_argument("--allow-blind-test", action="store_true")
    parser.add_argument("--media-root", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.manifest, args.settings, args.annotations, args.split, args.media_root, args.allow_blind_test)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(f"Replayed {result['frame_count']} observations; {len(result['candidates'])} review-only candidates")


if __name__ == "__main__":
    main()
