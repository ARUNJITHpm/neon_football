"""Build small versioned challenge inputs; synthetic events are not detector output."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dataset import (Annotation, AnnotationSet, Asset, DatasetManifest, DatasetSession,
                          MatchWindow, ReplayEvent, SessionAudit, Window)


def build(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    sessions, labels, audits = [], [], []
    for split, name in [("train", "synthetic-train"), ("validation", "synthetic-validation"), ("blind_test", "synthetic-blind")]:
        match_id = f"{name}-match"
        def event(event_id, occurrence, outcome="automatic", end="goal_a", team="orange", **kwargs):
            delivered = occurrence + 0.1
            return ReplayEvent(event_id=event_id, session_id=name, match_id=match_id, sequence=0,
                               occurred_seconds=occurrence, delivered_seconds=delivered, goal_end=end, team=team,
                               kind="decision", outcome=outcome, shadow=outcome == "automatic", **kwargs)
        events = [event("true-a", 5, displayed_seconds=5.4, display_uncertainty_seconds=0.01),
                  event("duplicate-a", 5.2), event("wrong-end", 10, end="goal_a"),
                  event("operator-rescue", 15, outcome="operator_confirmed", review_required=True, corrected=True),
                  event("missed-pending", 20, outcome="pending", review_required=True),
                  event("inactive-auto", 30), event("uncertain-auto", 40),
                  event("false-impact", 45), event("true-b", 50, end="goal_b", team="green")]
        if split == "train":
            events = [event("train-ordinary", 3)]
        elif split == "blind_test":
            events = [event("blind-a", 8, end="goal_b"), event("blind-b", 55, team="green")]
        for sequence, item in enumerate(events):
            item.sequence = sequence
        encoded = "".join(e.model_dump_json() + "\n" for e in events).encode()
        path = root / f"{name}.jsonl"
        with path.open("xb") as handle:
            handle.write(encoded)
        sessions.append(DatasetSession(session_id=name, source_group_id=name, split=split, evidence="synthetic",
            duration_seconds=60, host_clock_domain=f"host-{name}", configuration_version="synthetic-config-1",
            model_version="injected-no-detector-1", conditions=["synthetic", "challenge"],
            matches=[MatchWindow(match_id=match_id, start_seconds=0, end_seconds=60,
                active_auto_windows=[Window(start_seconds=0, end_seconds=25), Window(start_seconds=35, end_seconds=60)])],
            assets=[Asset(path=path.name, sha256=hashlib.sha256(encoded).hexdigest(), kind="replay_events")]))
        times = [5, 10, 15, 20, 30, 40, 45, 50] if split == "validation" else [3] if split == "train" else [8, 55]
        for index, seconds in enumerate(times):
            validity = "uncertain" if seconds == 40 else "invalid" if seconds == 45 else "valid"
            labels.append(Annotation(label_id=f"{name}-label-{index}", session_id=name, match_id=match_id,
                crossing_start_seconds=seconds, crossing_end_seconds=seconds, goal_end="goal_b" if seconds in (8, 10, 50) else "goal_a",
                team="green" if seconds in (50, 55) else "orange", validity=validity,
                visibility="occluded" if seconds == 40 else "clear", uncertainty_seconds=0.01,
                challenge="player_impact" if seconds == 45 else "ordinary", adjudicator="synthetic-ground-truth-v1",
                notes="Hand-authored challenge event, not measured football footage"))
        audits.append(SessionAudit(session_id=name, continuous_footage_reviewed=False, reviewer="synthetic-fixture-builder",
                                   notes="There is no football footage to adjudicate"))
    manifest = DatasetManifest(dataset_id="synthetic-challenge-v1", annotation_policy_version="annotation-policy-v1",
        split_assignment_version="fixed-synthetic-splits-v1", split_frozen_at=datetime(2026, 10, 11, tzinfo=timezone.utc), sessions=sessions)
    annotations = []
    for split in ("train", "validation", "blind_test"):
        selected = {s.session_id for s in sessions if s.split == split}
        annotation = AnnotationSet(dataset_id=manifest.dataset_id, split=split, version="synthetic-labels-v1",
            annotation_policy_version=manifest.annotation_policy_version,
            audits=[a for a in audits if a.session_id in selected], labels=[l for l in labels if l.session_id in selected])
        annotations.append((root / f"annotations-{split}.json", annotation))
    annotation = next(value for path, value in annotations if value.split == "validation")
    for path, value in [(root / "dataset.json", manifest), (root / "annotations.json", annotation)] + annotations:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(value.model_dump_json(indent=2) + "\n")
    return manifest, annotation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.output)
    print(f"Created synthetic split manifest, labels and replay events in {args.output}")


if __name__ == "__main__":
    main()
