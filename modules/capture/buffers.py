from collections import deque
from threading import Lock

from core.capture import EncodedFrame


class LatestFrames:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.frames = deque()
        self.dropped = 0
        self._lock = Lock()

    def put(self, frame: EncodedFrame):
        with self._lock:
            if len(self.frames) == self.capacity:
                self.frames.popleft()
                self.dropped += 1
            self.frames.append(frame)

    def take(self):
        with self._lock:
            return self.frames.popleft() if self.frames else None

    def clear(self):
        with self._lock:
            self.dropped += len(self.frames)
            self.frames.clear()


class ClipBuffer:
    def __init__(self, seconds: float, max_bytes: int):
        self.seconds = seconds
        self.max_bytes = max_bytes
        self.frames = deque()
        self.bytes = 0
        self.byte_evictions = 0
        self._lock = Lock()

    def put(self, frame: EncodedFrame):
        with self._lock:
            self.frames.append(frame)
            self.bytes += len(frame.jpeg)
            now = frame.metadata.timing.host_monotonic_seconds
            while self.frames and (self.bytes > self.max_bytes or
                                    now - self.frames[0].metadata.timing.host_monotonic_seconds > self.seconds):
                self.byte_evictions += self.bytes > self.max_bytes
                self.bytes -= len(self.frames.popleft().jpeg)

    def window(self, start: float, end: float):
        with self._lock:
            return [f for f in self.frames if start <= f.metadata.timing.host_monotonic_seconds <= end]

    def clear(self):
        with self._lock:
            self.frames.clear()
            self.bytes = 0
