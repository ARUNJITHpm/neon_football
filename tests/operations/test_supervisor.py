from types import SimpleNamespace

from tools.run_supervised import supervise


def test_supervisor_restarts_crashed_owner_with_bound_and_stops_startup_failure():
    exits, sleeps = iter([-9, -9, -9, -9]), []
    result = supervise(["fixture-server"], run=lambda *a, **kw: SimpleNamespace(returncode=next(exits)), sleep=sleeps.append)
    assert result["attempts"] == [-9] * 4 and sleeps == [2, 4, 8]
    assert result["state"] == "operator_attention_required"
    calls = []
    result = supervise(["fixture-server"], run=lambda command, **kw: (calls.append(command) or SimpleNamespace(returncode=1)), sleep=sleeps.append)
    assert calls == [["fixture-server"]] and result["attempts"] == [1]


def test_supervisor_graceful_stop_and_restart_budget_zero():
    result = supervise(["fixture-server"], run=lambda *a, **kw: SimpleNamespace(returncode=0))
    assert result["state"] == "stopped"
    result = supervise(["fixture-server"], max_restarts=0, run=lambda *a, **kw: SimpleNamespace(returncode=-9))
    assert len(result["attempts"]) == 1
