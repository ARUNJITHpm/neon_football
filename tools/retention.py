"""Plan registered closed-session retention; deletion requires an enabled policy and --apply."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.operations import RetentionPolicy
from modules.capture.retention import apply_retention, plan_retention


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("policy", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    policy = RetentionPolicy.model_validate_json(args.policy.read_text(encoding="utf-8"))
    plan = plan_retention(args.root, policy)
    result = apply_retention(plan) if args.apply else plan
    content = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(content)
    else:
        print(content)
