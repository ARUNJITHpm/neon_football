"""Validate goal-view records; this does not measure a camera or certify a depth rig."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.vision import VisionSettings
from modules.replay.dataset import digest
from modules.vision.geometry import valid_calibration


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("settings", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    settings = VisionSettings.model_validate_json(args.settings.read_text(encoding="utf-8"))
    views = []
    for view in settings.views:
        errors = valid_calibration(view, view.calibration.width, view.calibration.height)
        views.append(dict(camera_id=view.camera_id, goal_end=view.goal_end, evidence=view.calibration_evidence,
            image_record_valid=not errors, errors=errors, depth_calibration_reference=view.depth_calibration_id,
            depth_rig_independently_verified=False, airborne_depth_from_floor_mapping=False))
    result = dict(schema_version=1, settings_sha256=digest(args.settings), configuration_version=settings.version,
        views=views, field_acceptance=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print("Validated image records; depth-rig and field acceptance remain separate")
    if any(v["errors"] for v in views):
        raise SystemExit(1)
