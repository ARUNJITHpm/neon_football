"""Run an offline injected-decision replay without touching the live scoreboard."""
import argparse
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.replay.runner import replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--media-root", type=Path)
    parser.add_argument("--split", choices=["train", "validation", "blind_test"], default="validation")
    parser.add_argument("--allow-blind-test", action="store_true")
    parser.add_argument("--max-events", type=int, default=250000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.manifest, media_root=args.media_root, split=args.split, allow_blind_test=args.allow_blind_test, max_events=args.max_events)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(result.model_dump_json(indent=2) + "\n")
    print(f"Replayed {len(result.trace)} events / {len(result.decisions)} injected decisions; {result.engine}")


if __name__ == "__main__":
    main()
