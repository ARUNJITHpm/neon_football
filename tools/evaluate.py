"""Evaluate verified offline replay decisions against independently reviewed labels."""
import argparse
import json
import hashlib
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dataset import AnnotationSet, DatasetManifest, ReplayOutput
from modules.replay.evaluator import evaluate
from modules.replay.runner import replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("annotations", type=Path)
    parser.add_argument("replay", type=Path)
    parser.add_argument("--media-root", type=Path)
    parser.add_argument("--allow-blind-test", action="store_true")
    parser.add_argument("--tolerance", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = DatasetManifest.model_validate_json(args.manifest.read_text(encoding="utf-8"))
    annotations = AnnotationSet.model_validate_json(args.annotations.read_text(encoding="utf-8"))
    recorded = ReplayOutput.model_validate_json(args.replay.read_text(encoding="utf-8"))
    expected = replay(args.manifest, media_root=args.media_root, split=recorded.split,
                      allow_blind_test=args.allow_blind_test, max_events=recorded.event_limit)
    if recorded != expected:
        parser.error("Replay differs from verified source events/manifests; rerun replay with the frozen inputs")
    report = evaluate(manifest, annotations, recorded, args.tolerance, args.allow_blind_test)
    report["annotation_sha256"] = hashlib.sha256(args.annotations.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"counts": report["counts"], "release_qualified": False}))


if __name__ == "__main__":
    main()
