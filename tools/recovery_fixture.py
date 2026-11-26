"""Disposable dummy live-backup/restore/reconciliation proof; never touches existing data."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.review import DummyReview
from core.clock import VirtualClock
from core.schemas import Command
from modules.storage.maintenance import backup_database, inspect_database, restore_database
from modules.storage.store import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]


def run(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    identifiers = 0
    def identity():
        nonlocal identifiers
        identifiers += 1
        return uuid5(NAMESPACE_URL, f"neon-recovery-fixture-v1:{identifiers}")
    with patch("modules.storage.store.uuid4", identity):
        original = SQLiteStore(destination / "source.db", VirtualClock())
        counter = 0
        def send(store, action, payload=None):
            nonlocal counter
            counter += 1
            state = store.current()
            command = Command(command_id=f"recovery-command-{counter}", expected_revision=state["revision"] if state else 0,
                              action=action, payload=payload or {})
            review = DummyReview().prepare(state["match_id"], command, state) if action == "demo_incident" else None
            return store.execute(state["match_id"] if state else None, command, "Fixture operator", prepared_review=review)
        try:
            send(original, "create"); send(original, "set_review_mode", dict(mode="demo_review")); send(original, "start")
            goal = send(original, "manual_goal", dict(team="green"))
            send(original, "restart_play"); send(original, "demo_incident", dict(goal_end="goal_a", scenario="observed"))
            mid = original.current()["match_id"]
            before = original.export(mid)
            bundle = backup_database(destination / "source.db", destination / "backup")
            assert original.export(mid) == before
            restored_path = destination / "restored.db"
            inspection = restore_database(destination / "backup", restored_path)
            recovered = SQLiteStore(restored_path, VirtualClock())
            try:
                restored = recovered.current()
                assert restored["status"] == "interrupted" and restored["candidates"][0]["status"] == "unresolved"
                retry = Command(command_id="recovery-command-4", expected_revision=3, action="manual_goal", payload=dict(team="green"))
                assert recovered.execute(mid, retry, "Fixture operator")["duplicate"]
                assert recovered.current()["score"] == before["snapshot"]["score"]
                send(recovered, "reconcile_clock", dict(elapsed_seconds=42)); send(recovered, "resume"); send(recovered, "end")
                exported = recovered.export(mid)
                (destination / "recovered-export.json").write_text(json.dumps(exported, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                paths = sorted(p for folder in ("app", "core", "modules", "tools") for p in (ROOT / folder).rglob("*.py"))
                paths += [ROOT / "app/config/cage.example.yaml", ROOT / "app/config/retention.example.json"]
                result = dict(schema_version=1, fixture="dummy-recovery-v1", source_unchanged=True,
                    backup_sha256=bundle["sha256"], backup_inspection=inspection,
                    restored_pending_status=restored["candidates"][0]["status"], restored_status=restored["status"],
                    duplicate_goal_not_recounted=True, reconciled_elapsed_seconds=exported["snapshot"]["elapsed_seconds"],
                    final_score=exported["snapshot"]["score"], final_status=exported["snapshot"]["status"],
                    recovery_events=[e["type"] for e in exported["events"][len(before["events"]):]],
                    recovered_export_sha256=hashlib.sha256((destination / "recovered-export.json").read_bytes()).hexdigest(),
                    source_sha256={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                    automatic_scoring_enabled=False, physical_power_failure_verified=False, field_qualified=False)
                (destination / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            finally:
                recovered.close()
        finally:
            original.close()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="New directory only")
    args = parser.parse_args()
    result = run(args.destination)
    print(json.dumps({k: result[k] for k in ("fixture", "final_score", "recovery_events", "recovered_export_sha256")}))
