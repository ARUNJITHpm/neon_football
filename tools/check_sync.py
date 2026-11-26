"""Fit marker-based clock offset/drift and measure a later untouched holdout."""
import argparse
from collections import defaultdict
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import Field
from typing import Literal
from core.capture import CaptureContract, Seconds
from core.clock import fit_alignment
from core.schemas import Identifier


class Marker(CaptureContract):
    source_id: Identifier
    boot_id: Identifier
    source_clock_domain: str
    host_clock_domain: Identifier
    marker_id: Identifier
    source_seconds: float
    reference_host_seconds: Seconds
    uncertainty_seconds: Seconds
    split: Literal["fit", "validation"]


class MarkerSet(CaptureContract):
    schema_version: Literal[1] = 1
    evidence: Literal["synthetic", "physical"]
    procedure: str = Field(min_length=1)
    markers: list[Marker]


def percentile(values, percent=0.95):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percent * len(ordered)) - 1)]


def evaluate(data: MarkerSet):
    groups = defaultdict(list)
    for marker in data.markers:
        groups[(marker.source_id, marker.boot_id, marker.source_clock_domain, marker.host_clock_domain)].append(marker)
    if not groups:
        raise ValueError("No synchronization markers")
    reports = []
    validation_errors = {}
    for identity, markers in sorted(groups.items()):
        fit = [m for m in markers if m.split == "fit"]
        validation = [m for m in markers if m.split == "validation"]
        if len(fit) < 3 or len(validation) < 3:
            raise ValueError("Each boot/domain needs at least three fit and three later validation markers")
        if len({m.marker_id for m in markers}) != len(markers):
            raise ValueError("Duplicate marker ID within a clock group")
        # Input order is deliberate; sorting would conceal resets or reused timelines.
        all_source = [m.source_seconds for m in markers]
        all_host = [m.reference_host_seconds for m in markers]
        if any(b <= a for a, b in zip(all_source, all_source[1:])) or any(b <= a for a, b in zip(all_host, all_host[1:])):
            raise ValueError("Clock reset or non-increasing markers; use a separate boot/domain")
        if min(m.source_seconds for m in validation) <= max(m.source_seconds for m in fit):
            raise ValueError("Validation markers must occur after all fitted markers")
        model = fit_alignment([m.source_seconds for m in fit], [m.reference_host_seconds for m in fit],
                              [m.uncertainty_seconds for m in fit])
        residuals = [abs(model.map(m.source_seconds) - m.reference_host_seconds) for m in validation]
        bounds = [r + m.uncertainty_seconds + model.uncertainty_seconds for r, m in zip(residuals, validation)]
        p95 = percentile(bounds)
        validation_errors[identity] = {m.marker_id: (model.map(m.source_seconds), b) for m, b in zip(validation, bounds)}
        reports.append(dict(source_id=identity[0], boot_id=identity[1], source_clock_domain=identity[2], host_clock_domain=identity[3],
                            model=asdict(model), drift_ppm=model.drift_ppm, fit_markers=len(fit), validation_markers=len(validation),
                            observed_span_seconds=all_source[-1] - all_source[0], p95_residual_ms=percentile(residuals)*1000,
                            p95_bound_ms=p95*1000, maximum_bound_ms=max(bounds)*1000, within_20ms=p95 <= 0.020))
    pairs = []
    identities = list(validation_errors)
    for i, first in enumerate(identities):
        for second in identities[i + 1:]:
            if first[0] == second[0] or first[3] != second[3]:
                continue
            common = set(validation_errors[first]) & set(validation_errors[second])
            if len(common) < 3:
                continue
            bounds = [abs(validation_errors[first][marker][0] - validation_errors[second][marker][0]) +
                      validation_errors[first][marker][1] + validation_errors[second][marker][1] for marker in common]
            p95 = percentile(bounds)
            pairs.append(dict(first_source=first[0], first_boot=first[1], second_source=second[0], second_boot=second[1],
                              shared_validation_markers=len(common), p95_bound_ms=p95 * 1000, within_20ms=p95 <= 0.020))
    return dict(schema_version=1, evidence=data.evidence, procedure=data.procedure, groups=reports, pairs=pairs,
                timing_target_met=all(g["within_20ms"] for g in reports) and all(p["within_20ms"] for p in pairs),
                cross_source_evidence_available=bool(pairs),
                field_alignment_evidence=data.evidence == "physical",
                note="Pairwise bounds require shared physical marker IDs and a common host reference. Missing pairs or synthetic results do not close the venue gate.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(MarkerSet.model_validate_json(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"timing_target_met": report["timing_target_met"], "evidence": report["evidence"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
