"""Export or check versioned capture JSON schemas from their Python contracts."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.capture import CalibrationRecord, RecordingManifest, TimingEnvelope
from tools.check_sync import MarkerSet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "docs/schemas"
    root.mkdir(parents=True, exist_ok=True)
    models = {"recording-manifest-v1": RecordingManifest, "calibration-v1": CalibrationRecord,
              "timing-envelope-v1": TimingEnvelope, "sync-markers-v1": MarkerSet}
    for name, model in models.items():
        content = json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        path = root / f"{name}.json"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                raise SystemExit(f"Schema differs: {name}; regenerate after an intentional contract change")
        else:
            path.write_text(content, encoding="utf-8")
    print(f"{'Checked' if args.check else 'Exported'} {len(models)} capture schemas")


if __name__ == "__main__":
    main()
