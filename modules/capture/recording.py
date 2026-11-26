"""Indexed JPEG recordings with shared byte/disk quotas and explicit finalization."""
import hashlib
import json
from pathlib import Path
import shutil
from threading import Lock
import time

from core.capture import EncodedFrame, SegmentRecord


def atomic_json(path: Path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


class StorageGuard:
    def __init__(self, root: Path, limit: int, reserve: int):
        self.root, self.limit, self.reserve = root, limit, reserve
        self.used = 0
        self.lock = Lock()

    def claim(self, size: int):
        with self.lock:
            if self.used + size > self.limit:
                raise OSError("Session byte quota reached")
            if shutil.disk_usage(self.root).free < self.reserve + size:
                raise OSError("Free disk reserve reached")
            self.used += size


class IndexedWriter:
    def __init__(self, root: Path, relative: str, boot_id: str, guard: StorageGuard):
        self.root, self.relative, self.boot_id, self.guard = root, relative, boot_id, guard
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        self.video = target.open("xb")
        try:
            self.index = target.with_suffix(".jsonl").open("xb")
        except BaseException:
            self.video.close()
            raise
        self.frames = self.bytes = 0
        self.video_hash, self.index_hash = hashlib.sha256(), hashlib.sha256()
        self.first = self.last = None
        self.write_seconds = 0.0
        self.closed = False

    def append(self, frame: EncodedFrame):
        row = frame.metadata.model_dump(mode="json")
        row.update(byte_offset=self.bytes, byte_length=len(frame.jpeg))
        encoded = (json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n").encode()
        self.guard.claim(len(frame.jpeg) + len(encoded))
        start = time.perf_counter()
        self.video.write(frame.jpeg)
        self.index.write(encoded)
        self.write_seconds += time.perf_counter() - start
        self.video_hash.update(frame.jpeg)
        self.index_hash.update(encoded)
        self.frames += 1
        self.bytes += len(frame.jpeg)
        self.first = self.first or frame.metadata.timing
        self.last = frame.metadata.timing

    def close(self, complete=True) -> SegmentRecord:
        if not self.closed:
            try:
                self.video.flush()
                self.index.flush()
            finally:
                self.video.close()
                self.index.close()
                self.closed = True
        return SegmentRecord(path=self.relative, index_path=str(Path(self.relative).with_suffix(".jsonl")).replace("\\", "/"),
                             boot_id=self.boot_id, frames=self.frames, bytes=self.bytes,
                             sha256=self.video_hash.hexdigest(), index_sha256=self.index_hash.hexdigest(),
                             first_host_seconds=self.first.host_monotonic_seconds if self.first else None,
                             last_host_seconds=self.last.host_monotonic_seconds if self.last else None,
                             first_source_seconds=self.first.source_seconds if self.first else None,
                             last_source_seconds=self.last.source_seconds if self.last else None,
                             complete=complete)
