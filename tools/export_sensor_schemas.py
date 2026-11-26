"""Export/check sensor packets, alignment, impacts, settings and dataset contracts."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.sensors import SensorAlignment, SensorDataset, SensorImpact, SensorPacket, SensorSettings


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check",action="store_true")
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]/"docs/schemas"
    root.mkdir(parents=True,exist_ok=True)
    for name,model in {"sensor-packet-v1":SensorPacket,"sensor-alignment-v1":SensorAlignment,
                       "sensor-impact-v1":SensorImpact,"sensor-settings-v1":SensorSettings,"sensor-dataset-v1":SensorDataset}.items():
        path=root/f"{name}.json"
        text=json.dumps(model.model_json_schema(),indent=2,sort_keys=True)+"\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8")!=text:
                raise SystemExit(f"Schema differs: {name}")
        else:
            path.write_text(text,encoding="utf-8")
    print(f"{'Checked' if args.check else 'Exported'} five sensor schemas")
