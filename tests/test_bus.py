from core.bus import EventBus


def test_broadcast_and_slow_subscriber_recovery():
    bus = EventBus()
    fast = bus.subscribe(2)
    slow = bus.subscribe(1)
    bus.publish({"revision": 1})
    assert fast.get_nowait()["revision"] == 1
    bus.publish({"revision": 2})
    assert fast.get_nowait()["revision"] == 2
    assert slow.get_nowait() == {"type": "resync_required"}
    bus.publish({"revision": 3})
    assert slow.empty()
    bus.unsubscribe(fast)
