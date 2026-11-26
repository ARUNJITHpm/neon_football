"""Export/check portable vision input, candidate, settings and model schemas."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.vision import ModelDescriptor, VisionCandidate, VisionFrame, VisionSettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "docs/schemas"
    root.mkdir(parents=True, exist_ok=True)
    for name, model in {"vision-frame-v1": VisionFrame, "vision-candidate-v1": VisionCandidate,
                        "vision-settings-v1": VisionSettings, "vision-model-v1": ModelDescriptor}.items():
        path = root / f"{name}.json"
        content = json.dumps(model.model_json_schema(), indent=2, sort_keys=True)+"\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                raise SystemExit(f"Schema differs: {name}")
        else:
            path.write_text(content, encoding="utf-8")
    print(f"{'Checked' if args.check else 'Exported'} four vision schemas")


if __name__ == "__main__":
    main()
