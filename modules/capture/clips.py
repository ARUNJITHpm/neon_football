"""Bounded pre/post collection; disk work never runs in the scoring transaction."""
from collections import OrderedDict
import hashlib
from queue import Queue
from threading import Lock, Thread

from core.capture import ClipRequest
from core.ports import DomainError
from .recording import IndexedWriter, atomic_json


class Clips:
    def __init__(self, root, settings, guard):
        self.root, self.settings, self.guard = root, settings, guard
        self.lock = Lock()
        self.items = OrderedDict()
        self.queue = Queue(maxsize=settings.max_pending_clips)
        self.closed = False
        self.worker = Thread(target=self._write, daemon=True, name="clip-writer")
        self.worker.start()

    def request(self, request: ClipRequest, buffer, now):
        event = request.event_monotonic_seconds if request.event_monotonic_seconds is not None else now
        if event > now + 0.1 or event < now - self.settings.buffer_seconds:
            raise DomainError("Clip event is outside available live history", 422)
        with self.lock:
            if self.closed:
                raise DomainError("Capture is stopping", 503)
            if request.clip_id in self.items:
                existing = self.items[request.clip_id]
                if (existing["camera_id"] != request.camera_id or existing["requested_event"] != request.event_monotonic_seconds
                        or existing["event_id"] != request.event_id):
                    raise DomainError("Clip ID already has a different request")
                return self._public(existing)
            if sum(i["status"] in ("collecting", "writing") for i in self.items.values()) >= self.settings.max_pending_clips:
                raise DomainError("Clip capacity reached", 503)
            while len(self.items) >= 256:
                completed = next((key for key, item in self.items.items() if item["status"] not in ("collecting", "writing")), None)
                if completed is None:
                    break
                self.items.pop(completed)
            start, end = event - self.settings.clip_pre_seconds, event + self.settings.clip_post_seconds
            frames = buffer.window(start, min(now, end))
            size = sum(len(f.jpeg) for f in frames)
            item = dict(clip_id=request.clip_id, camera_id=request.camera_id, event_id=request.event_id, requested_event=request.event_monotonic_seconds,
                        event_monotonic_seconds=event, start=start, end=end, status="collecting", error=None,
                        frames=frames, size=size, partial_reason=None)
            self.items[request.clip_id] = item
            if size > self.settings.clip_max_bytes:
                self._fail(item, "Clip byte limit reached")
            elif now >= end:
                self._enqueue(item)
            return self._public(item)

    def feed(self, frame):
        now = frame.metadata.timing.host_monotonic_seconds
        with self.lock:
            for item in self.items.values():
                if item["status"] != "collecting" or item["camera_id"] != frame.metadata.camera_id:
                    continue
                if item["start"] <= now <= item["end"]:
                    # Initial buffer snapshot and this feed can overlap by one frame.
                    if not item["frames"] or frame.metadata.timing.sequence > item["frames"][-1].metadata.timing.sequence:
                        item["frames"].append(frame)
                        item["size"] += len(frame.jpeg)
                if item["size"] > self.settings.clip_max_bytes:
                    self._fail(item, "Clip byte limit reached")
                elif now >= item["end"]:
                    self._enqueue(item)

    def expire(self, now):
        with self.lock:
            for item in self.items.values():
                if item["status"] == "collecting" and now >= item["end"] + self.settings.stale_seconds:
                    item["partial_reason"] = "No frame arrived at the post-event boundary"
                    self._enqueue(item)

    def _fail(self, item, error):
        item.update(status="failed", error=error, frames=[])

    def _enqueue(self, item):
        item["status"] = "writing"
        self.queue.put_nowait(item)  # All collecting/writing items share the same bounded capacity.

    def _public(self, item):
        return {k: v for k, v in item.items() if k not in ("frames", "size", "start", "end", "requested_event")}

    def status(self, clip_id):
        with self.lock:
            if clip_id not in self.items:
                raise DomainError("Clip not found in this capture session", 404)
            return self._public(self.items[clip_id])

    def _write(self):
        while True:
            item = self.queue.get()
            if item is None:
                return
            writer = None
            try:
                frames = item["frames"]
                if not frames:
                    raise ValueError("No frames available for clip")
                filename = hashlib.sha256(item['clip_id'].encode()).hexdigest()
                writer = IndexedWriter(self.root, f"clips/{filename}.mjpeg", frames[0].metadata.timing.boot_id, self.guard)
                for frame in frames:
                    writer.append(frame)
                segment = writer.close().model_dump(mode="json")
                times = [f.metadata.timing.host_monotonic_seconds for f in frames]
                boot_ids = {f.metadata.timing.boot_id for f in frames}
                source_times = [f.metadata.timing.source_seconds for f in frames]
                # Coverage within one expected frame period; gaps/restarts are still explicit.
                frame_period = 1 / getattr(self, "fps", {}).get(item["camera_id"], 60)
                source_gaps = any(b <= a or b - a > frame_period * 2.5 for a, b in zip(source_times, source_times[1:])
                                  if a is not None and b is not None)
                complete = (times[0] <= item["start"] + frame_period and times[-1] >= item["end"] - frame_period
                            and len(boot_ids) == 1 and not any(f.metadata.timing.clock_reset for f in frames)
                            and all(b - a <= frame_period * 2.5 for a, b in zip(times, times[1:]))
                            and not source_gaps and item["partial_reason"] is None)
                result = self._public(item)
                result.update(status="ready", coverage="complete" if complete else "partial", recording=segment,
                              timestamp_quality="host_receipt_window", alignment_verified=False)
                atomic_json(self.root / f"clips/{filename}.json", result)
                with self.lock:
                    item.update(result, frames=[])
            except Exception:
                if writer and not writer.closed:
                    try:
                        writer.close(complete=False)
                    except OSError:
                        pass
                with self.lock:
                    self._fail(item, "Clip storage failed or frames unavailable")
                    try:
                        filename = hashlib.sha256(item['clip_id'].encode()).hexdigest()
                        target = self.root / f"clips/{filename}.json"
                        target.parent.mkdir(parents=True, exist_ok=True)
                        atomic_json(target, self._public(item))
                    except OSError:
                        pass

    def close(self):
        with self.lock:
            self.closed = True
            for item in self.items.values():
                if item["status"] == "collecting":
                    item["partial_reason"] = "Capture stopped before post-event completion"
                    self._enqueue(item)
        self.queue.put(None)
        self.worker.join()
