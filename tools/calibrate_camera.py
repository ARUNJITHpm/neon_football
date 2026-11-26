"""Create a calibration draft or validate measured values; no invented intrinsics."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.capture import CalibrationRecord


def floor_mapping(points, length_m, width_m):
    """Map four ordered *ground* corners; this cannot locate an airborne ball."""
    import numpy as np
    if length_m <= 0 or width_m <= 0:
        raise ValueError("Pitch dimensions must be positive")
    target = [(0, 0), (length_m, 0), (length_m, width_m), (0, width_m)]
    matrix, values = [], []
    for (x, y), (u, v) in zip(points, target):
        matrix.extend([[x, y, 1, 0, 0, 0, -u*x, -u*y], [0, 0, 0, x, y, 1, -v*x, -v*y]])
        values.extend([u, v])
    result = np.append(np.linalg.solve(matrix, values), 1).reshape(3, 3)
    if not np.isfinite(result).all() or abs(np.linalg.det(result)) < 1e-12:
        raise ValueError("Degenerate ground-plane geometry")
    return result.tolist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Measured calibration JSON to validate")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--camera", default="goal-a")
    parser.add_argument("--version", default="draft-1")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--floor-map", action="store_true")
    parser.add_argument("--pitch-length", type=float, default=15)
    parser.add_argument("--pitch-width", type=float, default=10)
    args = parser.parse_args()
    if args.input:
        record = CalibrationRecord.model_validate_json(args.input.read_text(encoding="utf-8"))
    else:
        record = CalibrationRecord(camera_id=args.camera, version=args.version, width=args.width, height=args.height,
                                   notes="DRAFT: measure intrinsics/distortion with a calibration target, goal ROI and physical placement before use.")
    if args.floor_map:
        if len(record.pitch_corners) != 4:
            parser.error("--floor-map requires four ordered measured pitch_corners")
        record = CalibrationRecord.model_validate({**record.model_dump(),
                "floor_homography": floor_mapping(record.pitch_corners, args.pitch_length, args.pitch_width)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(record.model_dump_json(indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "status": record.status, "version": record.version}))


if __name__ == "__main__":
    main()
