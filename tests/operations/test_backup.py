from contextlib import closing
import json
import sqlite3
import subprocess
import sys

import pytest

from core.clock import VirtualClock
from core.ports import DomainError
from core.schemas import Command
from modules.storage.maintenance import backup_database, digest, inspect_database, readonly, restore_database
from modules.storage.store import SQLiteStore
from tests.operator.test_review_storage import begin, send


def test_live_wal_backup_restore_retires_evidence_and_preserves_idempotency(tmp_path):
    source = tmp_path / "original.db"
    store = SQLiteStore(source, VirtualClock())
    try:
        begin(store)
        send(store, "manual_goal", dict(team="green"), command_id="goal-once")
        send(store, "restart_play")
        send(store, "demo_incident", dict(goal_end="goal_a", scenario="observed"))
        before = store.export(store.current()["match_id"])
        manifest = backup_database(source, tmp_path / "backup")
        assert store.export(store.current()["match_id"]) == before
        assert manifest["inspection"]["events"] == len(before["events"])
        assert not manifest["operator_key_included"] and not manifest["media_included"]
        restored = tmp_path / "restored.db"
        assert restore_database(tmp_path / "backup", restored) == manifest["inspection"]
        with pytest.raises(ValueError, match="new database"):
            restore_database(tmp_path / "backup", source)
        recovered = SQLiteStore(restored, VirtualClock())
        try:
            state = recovered.current()
            assert state["score"] == dict(orange=0, green=1) and state["status"] == "interrupted"
            assert state["candidates"][-1]["status"] == "unresolved"
            assert state["candidates"][-1]["review"] == before["snapshot"]["candidates"][-1]["review"]
            original_command = Command(command_id="goal-once", expected_revision=3, action="manual_goal", payload=dict(team="green"))
            assert recovered.execute(state["match_id"], original_command, "operator")["duplicate"]
            assert recovered.current()["score"]["green"] == 1
        finally:
            recovered.close()
    finally:
        store.close()


@pytest.mark.parametrize("damage", ["bytes", "manifest", "missing"])
def test_invalid_backup_never_publishes_restore(tmp_path, damage):
    source = tmp_path / "source.db"
    store = SQLiteStore(source, VirtualClock())
    send(store, "create")
    backup_database(source, tmp_path / "backup")
    store.close()
    if damage == "bytes":
        (tmp_path / "backup/score.sqlite3").write_bytes(b"changed")
    elif damage == "missing":
        (tmp_path / "backup/manifest.json").unlink()
    else:
        path = tmp_path / "backup/manifest.json"
        manifest = json.loads(path.read_text()); manifest["database"] = "../source.db"
        path.write_text(json.dumps(manifest))
    with pytest.raises((ValueError, OSError)):
        restore_database(tmp_path / "backup", tmp_path / "new.db")
    assert not (tmp_path / "new.db").exists()
    assert inspect_database(source)["matches"] == 1


def test_backup_existing_destination_and_projection_mismatch(tmp_path):
    source = tmp_path / "source.db"
    store = SQLiteStore(source, VirtualClock())
    try:
        state = send(store, "create")["snapshot"]
        backup_database(source, tmp_path / "backup")
        with pytest.raises(FileExistsError):
            backup_database(source, tmp_path / "backup")
        state["score"]["orange"] = 9
        store.db.execute("UPDATE matches SET state=?", (json.dumps(state),))
        with pytest.raises(DomainError, match="reconcile"):
            backup_database(source, tmp_path / "bad-backup")
        assert not (tmp_path / "bad-backup/manifest.json").exists()
        with pytest.raises(DomainError):
            store.integrity()
        with pytest.raises(DomainError) as error:
            store.execute(state["match_id"], Command(command_id="blocked", expected_revision=1, action="start"), "operator")
        assert error.value.status == 503
        with pytest.raises(DomainError):
            store.current()
    finally:
        store.close()


def test_unknown_schema_is_rejected_without_database_mutation_and_lock_released(tmp_path):
    path = tmp_path / "future.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA user_version=99")
    before = digest(path)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="Unsupported database schema"):
            SQLiteStore(path)
        assert digest(path) == before


def test_abrupt_process_exit_preserves_commit_and_discards_uncommitted_projection(tmp_path):
    source = tmp_path / "crash.db"
    code = '''
import json, os, sys
from pathlib import Path
from core.clock import VirtualClock
from modules.storage.store import SQLiteStore
from tests.operator.test_review_storage import send
store=SQLiteStore(Path(sys.argv[1]),VirtualClock())
send(store,"create");send(store,"start");send(store,"manual_goal",dict(team="green"))
state=store.current();state["score"]["green"]=99
store.db.execute("BEGIN IMMEDIATE")
store.db.execute("UPDATE matches SET state=?",(json.dumps(state),))
os._exit(0)
'''
    error_log = tmp_path / "child-error.txt"
    with error_log.open("w") as errors:
        result = subprocess.run([sys.executable, "-c", code, str(source)], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=errors, timeout=20)
    assert result.returncode == 0, error_log.read_text()
    assert inspect_database(source)["events"] == 3
    recovered = SQLiteStore(source, VirtualClock())
    try:
        assert recovered.current()["score"] == dict(orange=0, green=1)
        assert recovered.current()["status"] == "interrupted"
        assert recovered.current()["clock_reconciliation_required"]
    finally:
        recovered.close()
