"""Export/check portable version 1 dataset, label and replay schemas."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dataset import AnnotationSet, DatasetManifest, ReplayEvent, ReplayOutput


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "docs/schemas"
    root.mkdir(parents=True, exist_ok=True)
    for name, model in {"dataset-v1": DatasetManifest, "annotations-v1": AnnotationSet,
                        "replay-event-v1": ReplayEvent, "replay-output-v1": ReplayOutput}.items():
        path = root / f"{name}.json"
        content = json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                raise SystemExit(f"Schema differs: {name}")
        else:
            path.write_text(content, encoding="utf-8")
    print(f"{'Checked' if args.check else 'Exported'} four dataset/replay schemas")


if __name__ == "__main__":
    main()
