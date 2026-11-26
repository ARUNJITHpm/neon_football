"""Export/check offline fusion contracts."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.fusion import FusedCandidate, FusionCommand, FusionDataset, FusionEvent, FusionEvidence, FusionReplayStep, FusionSettings


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check",action="store_true")
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]/"docs/schemas"
    root.mkdir(parents=True,exist_ok=True)
    models={"fusion-settings-v1":FusionSettings,"fusion-evidence-v1":FusionEvidence,"fused-candidate-v1":FusedCandidate,
        "fusion-command-v1":FusionCommand,"fusion-event-v1":FusionEvent,"fusion-dataset-v1":FusionDataset,
        "fusion-replay-step-v1":FusionReplayStep}
    for name,model in models.items():
        path=root/f"{name}.json"
        content=json.dumps(model.model_json_schema(),indent=2,sort_keys=True)+"\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8")!=content:
                raise SystemExit(f"Schema differs: {name}")
        else:
            path.write_text(content,encoding="utf-8")
    print(f"{'Checked' if args.check else 'Exported'} seven fusion schemas")
