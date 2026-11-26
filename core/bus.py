from queue import Full, Queue
from threading import Lock
from typing import Any


class EventBus:
    """Bounded broadcast for notifications, never for durable scoring commands.

    Overflow disconnects a slow subscriber instead of silently dropping events.
    Reconnect consumers from a committed snapshot. No raw camera frames here.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._subscribers: set[Queue] = set()

    def subscribe(self, capacity: int = 64) -> Queue:
        channel: Queue = Queue(maxsize=capacity)
        with self._lock:
            self._subscribers.add(channel)
        return channel

    def unsubscribe(self, channel: Queue) -> None:
        with self._lock:
            self._subscribers.discard(channel)

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            for channel in tuple(self._subscribers):
                try:
                    channel.put_nowait(event)
                except Full:
                    self._subscribers.remove(channel)
                    while not channel.empty():
                        channel.get_nowait()
                    channel.put_nowait({"type": "resync_required"})
