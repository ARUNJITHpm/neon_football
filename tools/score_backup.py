"""Local consistent backup, checked restore to a NEW path, or read-only audit check."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.storage.maintenance import backup_database, inspect_database, restore_database


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("source", type=Path)
    backup.add_argument("destination", type=Path, help="New backup directory")
    restore = sub.add_parser("restore")
    restore.add_argument("bundle", type=Path)
    restore.add_argument("destination", type=Path, help="New database path")
    check = sub.add_parser("check")
    check.add_argument("source", type=Path)
    args = parser.parse_args()
    try:
        result = backup_database(args.source, args.destination) if args.action == "backup" else restore_database(args.bundle, args.destination) if args.action == "restore" else inspect_database(args.source)
    except Exception as error:
        raise SystemExit(f"Maintenance failed: {type(error).__name__}: {error}") from error
    print(json.dumps(result, sort_keys=True))
