"""Fit and validate explicit per-boot sensor markers, never serial receipt offsets."""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.clock import fit_alignment
from core.sensors import SensorAlignment


def evaluate(data):
    if data["evidence"] not in ("synthetic", "physical"):
        raise ValueError("Explicit timing evidence provenance required")
    mappings, reports, identities = [], [], set()
    for group in data["groups"]:
        identity = (group["device_id"], group["boot_id"])
        if identity in identities:
            raise ValueError("Duplicate device/boot marker group")
        identities.add(identity)
        markers = group["markers"]
        if any(not math.isfinite(m[k]) or m[k] < 0 for m in markers for k in ("device_seconds", "host_seconds", "uncertainty_seconds")):
            raise ValueError("Markers must be finite and nonnegative")
        if any(m["split"] not in ("fit", "validation") for m in markers):
            raise ValueError("Invalid marker split")
        fit = [m for m in markers if m["split"] == "fit"]
        validation = [m for m in markers if m["split"] == "validation"]
        if len(fit) < 3 or len(validation) < 3:
            raise ValueError("Each boot needs >=3 fit and >=3 later validation markers")
        x, y = [m["device_seconds"] for m in markers], [m["host_seconds"] for m in markers]
        if any(b <= a for a, b in zip(x, x[1:])) or any(b <= a for a, b in zip(y, y[1:])) or min(m["device_seconds"] for m in validation) <= max(m["device_seconds"] for m in fit):
            raise ValueError("Reset/non-increasing markers or validation overlaps fit")
        model = fit_alignment([m["device_seconds"] for m in fit], [m["host_seconds"] for m in fit], [m["uncertainty_seconds"] for m in fit])
        if any(not 0 <= m["uncertainty_seconds"] < float("inf") for m in validation):
            raise ValueError("Invalid validation uncertainty")
        errors = [abs(model.map(m["device_seconds"])-m["host_seconds"])+m["uncertainty_seconds"]+model.uncertainty_seconds for m in validation]
        bound = max(errors)
        mapping = SensorAlignment(version=data["version"], device_id=identity[0], boot_id=identity[1],
            host_clock_domain=group["host_clock_domain"], evidence=data["evidence"], **asdict(model),
            valid_from_device_seconds=min(x), valid_to_device_seconds=max(x))
        mapping.uncertainty_seconds = bound
        mappings.append(mapping)
        reports.append(dict(device_id=identity[0], boot_id=identity[1], drift_ppm=model.drift_ppm,
            fit_markers=len(fit), validation_markers=len(validation), maximum_validation_bound_ms=bound*1000,
            within_20ms=bound<=.02, valid_span=[min(x), max(x)]))
    if not mappings:
        raise ValueError("No marker groups")
    return dict(schema_version=1, evidence=data["evidence"], groups=reports,
                alignments=[a.model_dump(mode="json") for a in mappings], field_verified=False,
                physical_markers_supplied=data["evidence"]=="physical", timing_target_met=all(r["within_20ms"] for r in reports))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print("Fitted sensor boot mappings with holdout bounds; synthetic markers do not verify field timing")
