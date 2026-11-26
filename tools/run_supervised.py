"""Bounded single-worker host restarts; startup/configuration failure stops for an operator."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import load_settings
from modules.storage.maintenance import inspect_database


def supervise(command, *, max_restarts=3, run=subprocess.run, sleep=time.sleep, env=None):
    if not 0 <= max_restarts <= 10:
        raise ValueError("Restart budget must be 0–10")
    attempts = []
    while True:
        # Own child only; no discovery/killing of other applications or server instances.
        result = run(command, env=env)
        attempts.append(result.returncode)
        if result.returncode in (0, 1, 2) or len(attempts) > max_restarts:
            return dict(exit_code=result.returncode, attempts=attempts,
                        state="stopped" if result.returncode == 0 else "operator_attention_required")
        sleep(min(30, 2 ** len(attempts)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("app/config/cage.example.yaml"))
    parser.add_argument("--max-restarts", type=int, default=3)
    args = parser.parse_args()
    settings = load_settings(args.config)
    if settings.database_path.exists():
        inspect_database(settings.database_path)
    environment = dict(os.environ, NEON_CONFIG=str(args.config.resolve()))
    try:
        result = supervise([sys.executable, "-m", "app"], max_restarts=args.max_restarts, env=environment)
    except KeyboardInterrupt:
        raise SystemExit(0)
    print(json.dumps(result))
    raise SystemExit(result["exit_code"])
