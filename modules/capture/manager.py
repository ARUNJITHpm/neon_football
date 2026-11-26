"""Independent camera supervisors; source PTS remains distinct from exposure time."""
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import subprocess
from threading import Event, RLock, Thread
import time
from uuid import uuid4

from core.capture import (CalibrationRecord, CameraRecord, ClipRequest, EncodedFrame,
                          FrameMetadata, RecordingManifest, TimingEnvelope)
from core.clock import SourceClockTracker
from core.ports import DomainError
from .backend import FFmpegReader
from .buffers import ClipBuffer, LatestFrames
from .clips import Clips
from .recording import IndexedWriter, StorageGuard, atomic_json


class CameraWorker:
    def __init__(self, config, settings, manager):
        self.config, self.settings, self.manager = config, settings, manager
        self.lock = RLock()
        self.live = LatestFrames(settings.live_queue_capacity)
        self.buffer = ClipBuffer(settings.buffer_seconds, settings.buffer_max_bytes)
        self.record = CameraRecord(camera_id=config.id, kind=config.kind, width=config.width,
                                   height=config.height, expected_fps=config.expected_fps)
        self.health = "starting"
        self.last_frame = None
        self.started = time.monotonic()
        self.reader = None
        self.writer = None
        self.recording_failed = False
        self.first_frame = None
        self.source_last = None
        self.source_intervals = self.source_span = 0
        self.epoch_receipt_origin = self.epoch_source_origin = None
        self.delivery_lag_growth = None
        self.peak_delivery_lag_growth = 0.0
        self.peak_buffer_bytes = 0
        self.segment_number = 0
        self.sequence = 0
        self.stop = Event()
        self.tracker = SourceClockTracker()
        self.thread = Thread(target=self._run, daemon=True, name=f"camera-{config.id}")
        self._calibration()

    def _calibration(self):
        if not self.config.calibration_path:
            self.record.calibration_error = "No calibration record configured"
            return
        try:
            value = CalibrationRecord.model_validate_json(Path(self.config.calibration_path).read_text(encoding="utf-8"))
            if value.camera_id != self.config.id or (value.width, value.height) != (self.config.width, self.config.height):
                raise ValueError("Camera identity or image resolution mismatch")
            self.record.calibration = value
            self.record.calibration_valid = value.status == "measured"
            if not self.record.calibration_valid:
                self.record.calibration_error = "Draft calibration; physical measurements missing"
        except (ValueError, OSError):
            self.record.calibration_error = "Calibration missing, invalid or mismatched"

    def _end_segment(self, complete=True):
        if self.writer:
            writer, self.writer = self.writer, None
            try:
                segment = writer.close(complete=complete)
                self.record.segments.append(segment)
                self.record.write_seconds += writer.write_seconds
            except OSError:
                self.recording_failed = True
                self.manager.incident(self.config.id, "recording_finalize_failed")

    def _feed(self, packet, boot_id):
        now = time.monotonic()
        with self.lock:
            reset = self.tracker.observe(boot_id, packet.source_seconds, packet.source_sequence)
            if reset or self.epoch_receipt_origin is None:
                self.epoch_receipt_origin = now
                self.epoch_source_origin = packet.source_seconds
            if packet.source_seconds is not None and self.epoch_source_origin is not None:
                self.delivery_lag_growth = now - self.epoch_receipt_origin - (packet.source_seconds - self.epoch_source_origin)
                self.peak_delivery_lag_growth = max(self.peak_delivery_lag_growth, self.delivery_lag_growth)
            self.record.clock_resets += int(reset)
            if reset:
                self.manager.incident(self.config.id, "clock_reset", sequence=self.sequence)
            if self.last_frame is not None and now - self.last_frame > 2.5 / self.config.expected_fps:
                self.record.gaps += 1
                self.manager.incident(self.config.id, "receipt_gap", duration_seconds=now - self.last_frame)
            if packet.source_seconds is not None:
                if not reset and self.source_last is not None:
                    delta = packet.source_seconds - self.source_last
                    if delta > 0:
                        self.source_span += delta
                        self.source_intervals += 1
                    if delta > 2.5 / self.config.expected_fps:
                        self.manager.incident(self.config.id, "source_gap", duration_seconds=delta)
                        self.record.gaps += 1
                self.source_last = packet.source_seconds
            timing = TimingEnvelope(source_id=self.config.id, boot_id=boot_id, sequence=self.sequence,
                                    source_sequence=packet.source_sequence, source_seconds=packet.source_seconds,
                                    source_clock_domain=f"media:{self.config.id}:{boot_id}",
                                    host_clock_domain=self.manager.host_domain, host_monotonic_seconds=now,
                                    received_at=datetime.now(timezone.utc),
                                    quality="media_pts" if packet.source_seconds is not None else "receipt_only", clock_reset=reset)
            frame = EncodedFrame(FrameMetadata(camera_id=self.config.id, timing=timing, width=packet.width, height=packet.height), packet.jpeg)
            self.sequence += 1
            self.last_frame = now
            self.first_frame = self.first_frame or now
            self.record.frames += 1
            self.record.encoded_bytes += len(packet.jpeg)
            previous_size = (self.record.observed_width, self.record.observed_height)
            self.record.observed_width, self.record.observed_height = packet.width, packet.height
            mismatch = (packet.width, packet.height) != (self.config.width, self.config.height)
            if mismatch:
                self.record.calibration_valid = False
                self.record.calibration_error = "Actual source resolution differs from calibration/configuration"
                if previous_size != (packet.width, packet.height):
                    self.manager.incident(self.config.id, "resolution_mismatch", width=packet.width, height=packet.height)
            if packet.source_seconds is None:
                self.record.timestamp_quality = "receipt_only"
            lagging = self.delivery_lag_growth is not None and self.delivery_lag_growth > self.settings.stale_seconds
            self.health = "invalid_resolution" if mismatch else "lagging" if lagging else "healthy"
            self.live.put(frame)
            self.buffer.put(frame)
            self.peak_buffer_bytes = max(self.peak_buffer_bytes, self.buffer.bytes)
            self.manager.clips.feed(frame)
            if not self.recording_failed:
                try:
                    if self.writer and (reset or now - self.writer.first.host_monotonic_seconds >= self.settings.segment_seconds):
                        self._end_segment()
                    if not self.writer:
                        self.segment_number += 1
                        directory = hashlib.sha256(self.config.id.encode()).hexdigest()[:24]
                        self.writer = IndexedWriter(self.manager.root, f"cameras/{directory}/{self.segment_number:06d}.mjpeg", boot_id, self.manager.guard)
                    self.writer.append(frame)
                except OSError:
                    self.recording_failed = True
                    self.manager.incident(self.config.id, "recording_storage_failed")
                    self._end_segment(complete=False)

    def _run(self):
        attempts = 0
        while not self.stop.is_set():
            reader = None
            try:
                with self.lock:
                    self.started = time.monotonic()
                    self.health = "starting" if attempts == 0 else "reconnecting"
                    if attempts:
                        self.record.reconnects += 1
                    # Discard stale evidence at a new stream epoch, not clip requests.
                    self.buffer.clear()
                    self.live.clear()
                reader = FFmpegReader(self.config, self.settings)
                with self.lock:
                    self.reader = reader
                boot_id = uuid4().hex
                while not self.stop.is_set():
                    packet = reader.read()
                    if packet is None:
                        break
                    self._feed(packet, boot_id)
                outcome = "stream_ended"
            except Exception:
                outcome = "capture_failed"  # Never persist exception text or credential-bearing process args.
            finally:
                if reader:
                    reader.release()
                with self.lock:
                    self.reader = None
                    self._end_segment()
                    self.health = "stopped" if self.stop.is_set() else "disconnected"
                if not self.stop.is_set():
                    self.manager.incident(self.config.id, outcome)
            attempts += 1
            if not self.config.reconnect or self.stop.wait(self.settings.reconnect_seconds):
                break

    def supervise(self, now):
        with self.lock:
            anchor = self.last_frame if self.last_frame is not None and self.last_frame >= self.started else self.started
            timeout = self.settings.stale_seconds if self.last_frame is not None and self.last_frame >= self.started else self.settings.startup_timeout_seconds
            reader = self.reader
            stale = reader is not None and now - anchor > timeout
            if stale:
                self.health = "stale"
        if stale:
            self.manager.incident(self.config.id, "stale_reader", age_seconds=now - anchor)
            reader.close()  # Cancels only this camera's owned subprocess/read.

    def status(self):
        with self.lock:
            now = time.monotonic()
            duration = (self.last_frame - self.first_frame) if self.first_frame is not None else 0
            writes = self.record.write_seconds + (self.writer.write_seconds if self.writer else 0)
            return dict(camera_id=self.config.id, health=self.health, frames=self.record.frames,
                        observed_width=self.record.observed_width, observed_height=self.record.observed_height,
                        frame_age_seconds=now - self.last_frame if self.last_frame is not None else None,
                        receipt_fps=(self.record.frames - 1) / duration if duration else None,
                        source_fps=self.source_intervals / self.source_span if self.source_span else None,
                        source_span_seconds=self.source_span, receipt_span_seconds=duration,
                        delivery_lag_growth_seconds=self.delivery_lag_growth,
                        peak_delivery_lag_growth_seconds=self.peak_delivery_lag_growth,
                        encoded_bytes=self.record.encoded_bytes,
                        encoded_mbps=self.record.encoded_bytes * 8 / duration / 1e6 if duration else None,
                        source_encoded_mbps=self.record.encoded_bytes * 8 / self.source_span / 1e6 if self.source_span else None,
                        write_seconds=writes, encoded_write_mbps=self.record.encoded_bytes / writes / 1e6 if writes else None,
                        live_dropped_frames=self.live.dropped, buffer_bytes=self.buffer.bytes,
                        peak_buffer_bytes=self.peak_buffer_bytes, byte_evictions=self.buffer.byte_evictions,
                        gaps=self.record.gaps, clock_resets=self.record.clock_resets, reconnects=self.record.reconnects,
                        recording="failed" if self.recording_failed else "active" if self.writer else "idle",
                        calibration_valid=self.record.calibration_valid, calibration_error=self.record.calibration_error,
                        timestamp_quality=self.record.timestamp_quality, alignment_verified=False)

    def close(self):
        self.stop.set()
        with self.lock:
            reader = self.reader
        if reader:
            reader.close()
        if self.thread.ident is not None:
            self.thread.join(timeout=10)
        if self.thread.is_alive():
            self.manager.incident(self.config.id, "shutdown_timeout")
        self.health = "stopped"


class CaptureManager:
    def __init__(self, cameras, settings):
        if not cameras or len({c.id for c in cameras}) != len(cameras):
            raise ValueError("Capture needs unique camera IDs and at least one camera")
        self.settings = settings
        self.session_id = uuid4().hex
        self.host_domain = uuid4().hex
        self.root = Path(settings.root) / self.session_id
        self.root.mkdir(parents=True, exist_ok=False)
        version = subprocess.run([settings.ffmpeg, "-version"], capture_output=True, timeout=10, check=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.version = version.stdout.decode(errors="replace").splitlines()[0]
        self.started = datetime.now(timezone.utc)
        self.ended = None
        self.guard = StorageGuard(self.root, settings.max_session_bytes, settings.min_free_bytes)
        self.incident_lock = RLock()
        self.manifest_lock = RLock()
        self.incident_failure = False
        self.clips = Clips(self.root, settings, self.guard)
        self.clips.fps = {c.id: c.expected_fps for c in cameras}
        self.workers = {c.id: CameraWorker(c, settings, self) for c in cameras}
        self.stop = Event()
        self.monitor = Thread(target=self._monitor, daemon=True, name="capture-supervisor")
        self.closed = False
        self.save_manifest()

    def start(self):
        for worker in self.workers.values():
            worker.thread.start()
        self.monitor.start()

    def incident(self, camera_id, kind, **details):
        row = dict(camera_id=camera_id, type=kind, host_monotonic_seconds=time.monotonic(),
                   received_at=datetime.now(timezone.utc).isoformat(), **details)
        with self.incident_lock:
            try:
                encoded = json.dumps(row) + "\n"
                self.guard.claim(len(encoded.encode()))
                with (self.root / "incidents.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(encoded)
            except OSError:
                self.incident_failure = True

    def _monitor(self):
        while not self.stop.wait(0.2):
            now = time.monotonic()
            for worker in self.workers.values():
                worker.supervise(now)
            self.clips.expire(now)
            if not hasattr(self, "_last_manifest") or now - self._last_manifest > 2:
                self.save_manifest()
                self._last_manifest = now

    def save_manifest(self):
        with self.manifest_lock:
            records = []
            for worker in self.workers.values():
                with worker.lock:
                    record = worker.record.model_copy(deep=True)
                    record.live_dropped_frames = worker.live.dropped
                    records.append(record)
            failed = any(w.recording_failed for w in self.workers.values()) or self.incident_failure
            manifest = RecordingManifest(session_id=self.session_id, host_clock_domain=self.host_domain,
                                         started_at=self.started, ended_at=self.ended,
                                         status="failed" if failed else "closed" if self.ended else "recording",
                                         backend_version=self.version, capture_settings=self.settings, cameras=records,
                                         error="Recording or incident storage failed" if failed else None)
            try:
                atomic_json(self.root / "manifest.json", manifest.model_dump(mode="json"))
                atomic_json(self.root / "metrics.json", self.status())
            except OSError:
                self.incident_failure = True

    def status(self):
        return dict(enabled=True, session_id=self.session_id, host_clock_domain=self.host_domain,
                    storage_bytes_claimed=self.guard.used, storage_error=self.incident_failure,
                    cameras=[w.status() for w in self.workers.values()], alignment_verified=False)

    def request_clip(self, request: ClipRequest):
        worker = self.workers.get(request.camera_id)
        if not worker:
            raise DomainError("Unknown camera", 404)
        with worker.lock:
            return self.clips.request(request, worker.buffer, time.monotonic())

    def clip_status(self, clip_id):
        return self.clips.status(clip_id)

    def clip_file(self, clip_id):
        import hashlib
        from core.ports import DomainError
        status=self.clips.status(clip_id)
        if status["status"]!="ready":
            raise DomainError("Clip is not ready",409)
        recording=status["recording"]
        root=self.clips.root.resolve()
        target=(root/recording["path"]).resolve()
        if not target.is_relative_to(root) or target.suffix!=".mjpeg":
            raise DomainError("Invalid registered clip path",422)
        try:
            hasher=hashlib.sha256()
            with target.open("rb") as handle:
                for chunk in iter(lambda:handle.read(1024*1024),b""):
                    hasher.update(chunk)
        except OSError as exc:
            raise DomainError("Clip file unavailable",410) from exc
        if hasher.hexdigest()!=recording["sha256"]:
            raise DomainError("Clip checksum changed",410)
        return target

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop.set()
        if self.monitor.is_alive():
            self.monitor.join(timeout=10)
        for worker in self.workers.values():
            worker.close()
        self.clips.close()
        self.ended = datetime.now(timezone.utc)
        self.save_manifest()
