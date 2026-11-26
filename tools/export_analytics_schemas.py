"""Export/check bounded contact analytics schema contracts."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from core.analytics import AnalyticsSettings, AnalyticsSession, AnalyticsSubmission, AnalyticsDataset


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--check",action="store_true");args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]/"docs/schemas"
    for name,model in {"analytics-settings-v1":AnalyticsSettings,"analytics-session-v1":AnalyticsSession,
                       "analytics-submission-v1":AnalyticsSubmission,"analytics-dataset-v1":AnalyticsDataset}.items():
        path=root/f"{name}.json";content=json.dumps(model.model_json_schema(),indent=2,sort_keys=True)+"\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8")!=content:raise SystemExit(f"Schema differs: {name}")
        else:path.write_text(content,encoding="utf-8")
    print(f"{'Checked' if args.check else 'Exported'} four analytics schemas")
