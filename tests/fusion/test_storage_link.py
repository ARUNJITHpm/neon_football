import pytest

from core.clock import VirtualClock
from core.ports import DomainError
from core.schemas import Command
from modules.storage.store import SQLiteStore


def test_linked_manual_goal_one_confirmation_and_durable_correction(tmp_path):
    with_store = SQLiteStore(tmp_path/"linked.db",VirtualClock())
    try:
        def send(action,payload=None,command_id=None):
            state=with_store.current()
            return with_store.execute(state["match_id"] if state else None,
                Command(command_id=command_id or f"cmd-{state['revision'] if state else 0}",
                    expected_revision=state["revision"] if state else 0,action=action,payload=payload or {}),"operator")
        send("create"); send("start")
        send("create_candidate",dict(candidate_id="incident1",goal_end="goal_a",reason="fusion review"))
        before=with_store.current()
        with pytest.raises(DomainError,match="disagrees"):
            send("manual_goal",dict(team="orange",candidate_id="incident1"))
        assert with_store.current()==before
        result=send("manual_goal",dict(team="green",candidate_id="incident1"))
        assert result["snapshot"]["candidates"][0]["status"]=="confirmed"
        with pytest.raises(DomainError,match="resolved"):
            send("confirm_candidate",dict(candidate_id="incident1"))
        with pytest.raises(DomainError,match="resolved"):
            send("manual_goal",dict(team="green",candidate_id="incident1"))
        assert with_store.current()["score"]==dict(orange=0,green=1)
        send("undo_goal",dict(goal_id=result["event"]["payload"]["goal_id"]))
        assert with_store.current()["score"]==dict(orange=0,green=0)
        assert result["event"]["payload"]["active"] is True
    finally:
        with_store.close()
