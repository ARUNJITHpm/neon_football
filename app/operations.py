"""Operational telemetry for the local host; absent field measurements stay null."""
from datetime import datetime
import hashlib
import json
import shutil
from threading import RLock
import time


class Operations:
    def __init__(self, settings, store, *, capture, displays, clip_task):
        self.settings, self.store = settings, store
        self.capture, self.displays, self.clip_task = capture, displays, clip_task
        self.lock = RLock()
        self.started = time.monotonic()
        self.integrity_at = None
        self.integrity_ok = None
        self.last_check = float("-inf")
        self.fault_latched = False
        self.cpu_clock = None
        self.cpu_time = None
        self.cpu_percent = None
        raw = settings.model_dump(mode="json")
        self.config_sha256 = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()

    def check_integrity(self):
        with self.lock:
            if self.fault_latched or time.monotonic() - self.last_check < self.settings.operations.integrity_interval_seconds:
                return
            self.last_check = time.monotonic()
            self.integrity_at = self.store.clock.utcnow().isoformat()
            try:
                self.store.integrity()
                self.integrity_ok = True
            except Exception:
                self.integrity_ok = False
                self.fault_latched = True

    def status(self):
        self.check_integrity()
        with self.lock:
            state = self.store.current() if not self.fault_latched else None
            service = self.capture()
            task = self.clip_task()
            try:
                capture = service.status() if service else dict(enabled=False, cameras=[], alignment_verified=False)
            except Exception:
                capture = dict(enabled=False, cameras=[], alignment_verified=False, error="Capture status unavailable")
            pending = [c for c in state["candidates"] if c["status"] == "pending_review"] if state else []
            now = self.store.clock.utcnow()
            ages = [max(0, (now - datetime.fromisoformat(c["created_at"])).total_seconds()) for c in pending if c.get("created_at")]
            oldest_missing = bool(pending) and len(ages) != len(pending)
            try:
                usage = shutil.disk_usage(self.settings.database_path.resolve().parent)
                disk = dict(total_bytes=usage.total, free_bytes=usage.free,
                            low_space=usage.free < self.settings.operations.min_free_bytes)
            except OSError:
                disk = dict(total_bytes=None, free_bytes=None, low_space=None)
            clip_worker = "not_started" if task is None else "stopped" if task.done() else "running"
            monotonic, cpu = time.monotonic(), time.process_time()
            if self.cpu_clock is not None and monotonic - self.cpu_clock >= 1:
                self.cpu_percent = round(100 * (cpu - self.cpu_time) / (monotonic - self.cpu_clock), 3)
                self.cpu_clock, self.cpu_time = monotonic, cpu
            elif self.cpu_clock is None:
                self.cpu_clock, self.cpu_time = monotonic, cpu
            camera_degraded = capture.get("enabled") and any(c.get("health") not in ("healthy", "live") for c in capture.get("cameras", []))
            degraded = bool(camera_degraded or capture.get("error") or
                            (self.settings.capture.enabled and not capture.get("enabled")) or
                            disk["low_space"] is not False or clip_worker == "stopped")
            return dict(schema_version=1, mode="manual", automatic_scoring_enabled=False,
                scoring_available=not self.fault_latched, state="quarantined" if self.fault_latched else "degraded" if degraded else "manual_ready",
                server_time=now.isoformat(), uptime_seconds=round(time.monotonic() - self.started, 3),
                config_sha256=self.config_sha256, database_schema=1,
                integrity=dict(ok=self.integrity_ok, checked_at=self.integrity_at, fault_latched=self.fault_latched),
                disk=disk, capture=capture, clip_worker=clip_worker,
                review=dict(pending=len(pending), oldest_age_seconds=max(ages) if ages and not oldest_missing else None,
                            age_unknown=oldest_missing),
                sensors=dict(state="not_connected", source_health=None, clock_alignment_verified=False),
                inference=dict(state="offline_only", queue_age_seconds=None, real_model_verified=False),
                resource=dict(temperature_celsius=None, cpu_percent=self.cpu_percent, process_memory_bytes=None,
                              cpu_scope="API process only; 100% is one core; excludes FFmpeg workers", temperature_memory_measured=False),
                displays=self.displays().status(), physical_release_qualified=False)
