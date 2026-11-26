from app.display import DisplayMonitor
from core.clock import VirtualClock


def test_duplicate_acks_keep_presence_fresh_without_duplicate_latency():
    clock=VirtualClock(); monitor=DisplayMonitor(clock); connection=monitor.open()
    snapshot=dict(match_id="match",revision=1,last_event=dict(event_id="goal",revision=1,type="goal_confirmed",recorded_at=clock.utcnow().isoformat()))
    monitor.sent(connection,snapshot)
    message=dict(type="rendered",match_id="match",revision=1,event_id="goal")
    clock.advance(.1); monitor.acknowledge(connection,message)
    for _ in range(5):
        clock.advance(2); monitor.acknowledge(connection,message)
        assert monitor.status()["connections"][0]["state"]=="rendering"
    assert len(monitor.status()["rendered_samples"])==1
    clock.advance(4)
    assert monitor.status()["connections"][0]["state"]=="stale"


def test_wrong_identity_old_revision_and_reconnect_snapshots_are_not_latency():
    clock=VirtualClock(); clock.advance(10); monitor=DisplayMonitor(clock); connection=monitor.open()
    first=dict(match_id="m",revision=1,last_event=dict(event_id="old",revision=1,type="goal_confirmed",recorded_at=clock.origin.isoformat()))
    monitor.sent(connection,first)
    monitor.acknowledge(connection,dict(type="rendered",match_id="m",revision=1,event_id="wrong"))
    assert monitor.status()["connections"][0]["state"]=="waiting_for_render"
    monitor.acknowledge(connection,dict(type="rendered",match_id="m",revision=1,event_id="old"))
    assert not monitor.status()["rendered_samples"]
    second=dict(match_id="m",revision=2,last_event=dict(event_id="new",revision=2,type="goal_confirmed",recorded_at=clock.utcnow().isoformat()))
    monitor.sent(connection,second)
    assert monitor.status()["connections"][0]["state"]=="awaiting_update"
    monitor.acknowledge(connection,dict(type="rendered",match_id="m",revision=2,event_id="new"))
    monitor.acknowledge(connection,dict(type="rendered",match_id="m",revision=1,event_id="old"))
    monitor.acknowledge(connection,dict(type="rendered",match_id=[],revision=2,event_id="new"))
    assert monitor.status()["connections"][0]["revision"]==2
