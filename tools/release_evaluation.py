"""Reproduce frozen dummy shadow evaluation without qualifying an automatic release."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.fusion_replay import replay
from core.fusion import FusionDataset


def evaluate(manifest):
    manifest = Path(manifest)
    if manifest.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Manifest capacity reached")
    dataset = FusionDataset.model_validate_json(manifest.read_text(encoding="utf-8"))
    if any(session.evidence != "synthetic" for session in dataset.sessions if session.split == "validation"):
        raise ValueError("This release scaffold accepts synthetic validation evidence only")
    shadow = replay(manifest)
    # This runner accepts the existing synthetic development fixture only.
    # Independently adjudicated field evaluation is a separate unsatisfied gate.
    return dict(schema_version=1, candidate="neon-score-0.1.0-part08-prototype", evidence="dummy_shadow",
        automatic_scoring_enabled=False, release_qualified=False, field_metrics=None,
        frozen=dict(configuration=shadow["configuration"], provenance=shadow["provenance"], dataset_id=shadow["dataset_id"],
                    evaluator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),
        dummy_counts=shadow["counts"], dummy_scheduled_seconds=shadow["scheduled_seconds"],
        dummy_shadow_recall=shadow["shadow_recall"], dummy_false_per_hour=shadow["false_shadow_per_hour"],
        virtual_decision_latency_seconds=shadow["virtual_decision_latency_seconds"],
        gates=[dict(name=name, state="pending", required=value) for name,value in (
            ("independent_field_floor", "300 goals, 20 scheduled match hours, both ends, 14 representative days"),
            ("automatic_recall", "at least 97%"), ("false_automatic_goals", "below 1 per scheduled hour"),
            ("visible_score_latency", "p95 below 1 second, physical crossing to rendered score"),
            ("review_workload", "at most 10% plus at most 2 prompts/hour; venue approval pending"),
            ("score_corrections", "below 5%"), ("automatic_availability", "at least 99%"),
            ("physical_failure_recovery", "camera/serial/host-power/migration/update/restore acceptance on selected host"),
            ("browser_hdmi", "rendered desktop/mobile, media/keyboard and physical display measurement"),
            ("independent_scoring_and_operator_acceptance", "physical fallback and supervised venue workflow acceptance"),
            ("isolated_install", "fresh dependency install and startup/rollback on selected host"))],
        limitations=shadow["limitations"] + ["Source package and synthetic recovery checks cannot activate automatic scoring",
            "Dummy recall and rate intervals are descriptive, not release evidence; clustering is not estimated"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.manifest)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("Dummy shadow evaluation recorded; all field gates pending, automatic scoring disabled")
