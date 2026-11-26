import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.review import DummyReview
from core.clock import VirtualClock
from core.ports import DomainError
from core.schemas import Command
from modules.storage.report import match_report
from modules.storage.store import SQLiteStore


def send(store,action,payload=None,*,command_id=None,revision=None):
    state=store.current()
    cmd=Command(command_id=command_id or str(uuid4()),action=action,payload=payload or {},
        expected_revision=revision if revision is not None else state["revision"] if state else 0)
    prepared=DummyReview().prepare(state["match_id"],cmd,state) if action=="demo_incident" else None
    return store.execute(state["match_id"] if state else None,cmd,"operator",prepared_review=prepared)


def begin(store):
    send(store,"create"); send(store,"set_review_mode",dict(mode="demo_review")); send(store,"start")


def test_review_persistence_restart_retires_pending_and_keeps_score(tmp_path):
    path=tmp_path/"durable.db"; clock=VirtualClock()
    store=SQLiteStore(path,clock)
    begin(store)
    confirmed=send(store,"demo_incident",dict(goal_end="goal_a",scenario="observed"))["snapshot"]["candidates"][0]
    send(store,"confirm_candidate",dict(candidate_id=confirmed["candidate_id"]))
    send(store,"restart_play")
    pending=send(store,"demo_incident",dict(goal_end="goal_b",scenario="partial"))["snapshot"]["candidates"][-1]
    before=store.export(store.current()["match_id"])
    store.close()
    recovered=SQLiteStore(path,clock)
    try:
        state=recovered.current()
        assert state["score"]==dict(orange=0,green=1) and state["status"]=="interrupted"
        assert state["candidates"][-1]["status"]=="unresolved"
        assert state["candidates"][-1]["review"]==pending["review"]
        assert recovered.export(state["match_id"])["events"][:len(before["events"])]==before["events"]
        send(recovered,"reconcile_clock",dict(elapsed_seconds=10)); send(recovered,"resume")
        with pytest.raises(DomainError):
            send(recovered,"confirm_candidate",dict(candidate_id=pending["candidate_id"]))
    finally:
        recovered.close()


def test_expiry_commit_is_atomic_and_blocks_stale_revision(tmp_path):
    store=SQLiteStore(tmp_path/"expiry.db",VirtualClock())
    try:
        begin(store)
        result=send(store,"demo_incident",dict(goal_end="goal_a",scenario="observed"))
        candidate=result["snapshot"]["candidates"][0]
        old_revision=result["snapshot"]["revision"]
        store.clock.advance(15)
        with pytest.raises(DomainError):
            store.execute(result["snapshot"]["match_id"],Command(action="confirm_candidate",expected_revision=old_revision,
                payload=dict(candidate_id=candidate["candidate_id"])),"operator")
        state=store.current()
        assert state["revision"]==old_revision+1 and state["candidates"][0]["status"]=="unresolved"
        assert state["score"]==dict(orange=0,green=0)
        assert state["last_event"]["type"]=="candidate_expired"
    finally:
        store.close()


def test_candidate_evidence_write_failure_rolls_back_entire_submission(tmp_path):
    store=SQLiteStore(tmp_path/"full.db",VirtualClock())
    try:
        begin(store); before=store.export(store.current()["match_id"])
        store.db.executescript("CREATE TRIGGER simulate_full BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'full'); END;")
        with pytest.raises(Exception,match="full"):
            send(store,"demo_incident",dict(goal_end="goal_a",scenario="observed"),command_id="must-not-ack")
        assert store.export(store.current()["match_id"])==before
        assert store.db.execute("SELECT 1 FROM commands WHERE command_id='must-not-ack'").fetchone() is None
    finally:
        store.close()


def test_existing_json_state_gets_defaults_and_latest_event_without_migration(tmp_path):
    store=SQLiteStore(tmp_path/"old.db",VirtualClock())
    try:
        result=send(store,"create")
        state=result["snapshot"]
        for name in ("review_mode","play_epoch","restart_required","last_event","server_time","duration_reached"):
            state.pop(name,None)
        store.db.execute("UPDATE matches SET state=? WHERE id=?",(json.dumps(state),state["match_id"]))
        restored=store.current()
        assert restored["review_mode"]=="manual" and not restored["restart_required"]
        assert restored["last_event"]["event_id"]==result["event"]["event_id"]
        assert store.db.execute("PRAGMA user_version").fetchone()[0]==1
    finally:
        store.close()


def test_report_refuses_projection_disagreement(tmp_path):
    store=SQLiteStore(tmp_path/"report.db",VirtualClock())
    try:
        send(store,"create"); exported=store.export(store.current()["match_id"])
        exported["snapshot"]["score"]["orange"]=1
        with pytest.raises(DomainError,match="reconcile"):
            match_report(exported)
    finally:
        store.close()
