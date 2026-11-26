"""Read-only integrity inspection and SQLite snapshot backup/restore.

No constructor recovery is run by these tools. Restore never replaces a database.
"""
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from .report import match_report
from core.analytics import AnalyticsSession, apply_corrections


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def inspect_connection(db):
    if db.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise ValueError("Unsupported database schema; restore with the matching runtime")
    if any(row[0] != "ok" for row in db.execute("PRAGMA quick_check")):
        raise ValueError("Database integrity check failed")
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("Database foreign-key check failed")
    triggers = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    if not {"events_no_update", "events_no_delete"}.issubset(triggers):
        raise ValueError("Immutable audit-log triggers are missing")
    scores = {}
    events = 0
    for match_id, body in db.execute("SELECT id,state FROM matches ORDER BY id"):
        state = json.loads(body)
        history = []
        for event_id, revision, raw in db.execute("SELECT event_id,revision,body FROM events WHERE match_id=? ORDER BY revision", (match_id,)):
            event = json.loads(raw)
            if event["event_id"] != event_id or event["match_id"] != match_id or event["revision"] != revision or revision != len(history) + 1:
                raise ValueError("Event identity/revision chain differs")
            history.append(event)
        if state["match_id"] != match_id or state["revision"] != len(history):
            raise ValueError("Match projection revision differs from audit log")
        report = match_report(dict(snapshot=state, events=history))
        initial=next((e["payload"] for e in history if e["type"]=="match_created"),None)
        if initial is None or state["players"]!=initial["players"]:
            raise ValueError("Registered roster differs from match creation event")
        if state.get("roster_revision",0)!=report["roster_revision"] or state.get("active_player_ids",[p["id"] for p in state["players"]])!=report["active_player_ids"]:
            raise ValueError("Roster projection differs from audit log")
        if {s["suggestion_id"]:s["status"] for s in state.get("attribution_suggestions",[])}!=report["attribution_suggestion_statuses"]:
            raise ValueError("Attribution suggestion projection differs from audit log")
        inputs={e["payload"]["suggestion_id"]:e["payload"] for e in history if e["type"]=="attribution_suggested"}
        if any(item[key]!=inputs[item["suggestion_id"]][key] for item in state.get("attribution_suggestions",[])
               for key in ("goal_id","base_attribution_revision","created_at","submission")):
            raise ValueError("Attribution evidence differs from immutable submission event")
        if state.get("analytics_sessions",[])!=report["analytics_sessions"]:
            raise ValueError("Analytics evidence/corrections differ from immutable event log")
        for item in report["analytics_sessions"]:
            session=AnalyticsSession.model_validate(item["session"])
            if session.match_id!=match_id or session.rosters[0].roster.model_dump(mode="json")["players"]!=state["players"] or session.evidence!="synthetic":
                raise ValueError("Analytics match/roster/provenance differs")
            apply_corrections(session,item["corrections"])
        # Also validate stored goal attribution/active flags, not only score counts.
        projected = {goal["goal_id"]: goal for goal in state["goals"]}
        reconstructed = {goal["goal_id"]: goal for goal in report["goals"]}
        if projected.keys() != reconstructed.keys() or any(
            goal.get(key) != reconstructed[goal_id].get(key)
            for goal_id, goal in projected.items() for key in ("team", "active", "scorer_id", "assist_id", "own_goal", "candidate_id", "elapsed_seconds", "confirmation", "roster_revision", "active_player_ids")
        ):
            raise ValueError("Goal projection differs from audit log")
        if any(goal.get("attribution_revision",0)!=reconstructed[gid].get("attribution_revision",0) or
               goal.get("attribution_source","operator")!=reconstructed[gid].get("attribution_source","operator") for gid,goal in projected.items()):
            raise ValueError("Goal attribution metadata differs from audit log")
        scores[match_id] = report["score"]
        events += len(history)
    for command_id, fingerprint, result in db.execute("SELECT command_id,fingerprint,result FROM commands"):
        acknowledgment = json.loads(result)
        event = acknowledgment["event"]
        row = db.execute("SELECT body FROM events WHERE event_id=?", (event["event_id"],)).fetchone()
        if len(fingerprint) != 64 or row is None or json.loads(row[0]) != event or event["command_id"] != command_id:
            raise ValueError("Command acknowledgment differs from committed event")
    return dict(schema_version=1, matches=len(scores), events=events,
                commands=db.execute("SELECT COUNT(*) FROM commands").fetchone()[0], scores=scores)


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def inspect_database(path):
    with closing(readonly(path)) as db:
        db.execute("BEGIN")
        return inspect_connection(db)


def backup_database(source, destination):
    """SQLite backup captures a consistent committed WAL snapshot while the host runs."""
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    target = destination / "score.sqlite3"
    try:
        with closing(readonly(source)) as original, closing(sqlite3.connect(target)) as backup:
            original.backup(backup)
            # Bundle a standalone snapshot, never a database requiring WAL sidecars.
            backup.execute("PRAGMA journal_mode=DELETE")
        inspection = inspect_database(target)
        manifest = dict(schema_version=1, kind="neon-score-sqlite-backup", database="score.sqlite3",
                        sha256=digest(target), bytes=target.stat().st_size, inspection=inspection,
                        created_at=datetime.now(timezone.utc).isoformat(), media_included=False,
                        operator_key_included=False)
        # A missing manifest means an incomplete bundle and cannot be restored.
        with (destination / "manifest.json").open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return manifest
    except Exception:
        # Leave an incomplete bundle for diagnosis; never publish a completion marker.
        raise


def restore_database(bundle, destination):
    """Verify first, restore to a new path, and leave the original database untouched."""
    bundle, destination = Path(bundle).resolve(), Path(destination).resolve()
    if destination.exists() or any(Path(str(destination) + suffix).exists() for suffix in ("-wal", "-shm", ".lock")):
        raise ValueError("Restore requires a new database path without sidecars")
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("kind") != "neon-score-sqlite-backup" or manifest.get("database") != "score.sqlite3":
        raise ValueError("Unsupported backup manifest")
    source = bundle / "score.sqlite3"
    if source.is_symlink() or source.resolve().parent != bundle:
        raise ValueError("Backup database must be an owned bundle file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Verify the staged bytes, so a source change between verification and copy fails.
    staged = destination.parent / f".restore-{uuid4().hex}.sqlite3"
    try:
        with source.open("rb") as incoming, staged.open("xb") as outgoing:
            for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                outgoing.write(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if staged.stat().st_size != manifest["bytes"] or digest(staged) != manifest["sha256"]:
            raise ValueError("Backup bytes/checksum differ")
        inspection = inspect_database(staged)
        if inspection != manifest["inspection"]:
            raise ValueError("Backup audit inspection differs")
        # Hard-link publication is atomic and fails if destination appeared meanwhile.
        os.link(staged, destination)
    finally:
        # Delete only the explicitly owned staging file, never a directory tree.
        if staged.exists():
            staged.unlink()
    return inspection
