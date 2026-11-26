from datetime import datetime, timedelta, timezone
from typing import Protocol
import time
import math
from dataclasses import dataclass
from statistics import fmean


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def utcnow(self) -> datetime: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def utcnow(self) -> datetime:
        return datetime.now(timezone.utc)


class VirtualClock:
    """Advance explicitly: hardware-free clock tests and future replay."""

    def __init__(self) -> None:
        self.elapsed = 0.0
        self.origin = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def monotonic(self) -> float:
        return self.elapsed

    def utcnow(self) -> datetime:
        return self.origin + timedelta(seconds=self.elapsed)

    def advance(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("A replay clock cannot move backwards")
        self.elapsed += seconds


@dataclass(frozen=True)
class AlignmentModel:
    """An explicit measured mapping, never inferred from receipt times alone."""

    source_origin_seconds: float
    host_origin_seconds: float
    scale: float
    uncertainty_seconds: float

    def map(self, source_seconds: float) -> float:
        return self.host_origin_seconds + self.scale * (source_seconds - self.source_origin_seconds)

    @property
    def drift_ppm(self) -> float:
        return (self.scale - 1) * 1_000_000


def fit_alignment(source: list[float], host: list[float], uncertainties: list[float]) -> AlignmentModel:
    if len(source) < 3 or len(source) != len(host) or len(source) != len(uncertainties):
        raise ValueError("At least three paired synchronization markers are required")
    if not all(math.isfinite(v) for v in source + host + uncertainties) or any(u < 0 for u in uncertainties):
        raise ValueError("Synchronization markers must be finite; uncertainties must be nonnegative")
    if any(b <= a for a, b in zip(source, source[1:])) or any(b <= a for a, b in zip(host, host[1:])):
        raise ValueError("Marker clocks must increase within one boot/domain; split resets into separate groups")
    sx, hy = fmean(source), fmean(host)
    spread = sum((x - sx)**2 for x in source)
    if spread <= 1e-12:
        raise ValueError("Synchronization markers need time separation")
    scale = sum((x - sx) * (y - hy) for x, y in zip(source, host)) / spread
    if scale <= 0:
        raise ValueError("Clock mapping must be increasing")
    residual = max(abs(hy + scale * (x - sx) - y) + u for x, y, u in zip(source, host, uncertainties))
    return AlignmentModel(sx, hy, scale, residual)


class SourceClockTracker:
    """Mark media/device timeline resets without silently aligning clock domains."""

    def __init__(self):
        self.last_boot = None
        self.last_seconds = None
        self.last_sequence = None

    def observe(self, boot_id: str, seconds: float | None, sequence: int | None) -> bool:
        reset = self.last_boot is not None and boot_id != self.last_boot
        if boot_id == self.last_boot:
            reset = ((seconds is not None and self.last_seconds is not None and seconds < self.last_seconds) or
                     (sequence is not None and self.last_sequence is not None and sequence <= self.last_sequence))
        self.last_boot = boot_id
        self.last_seconds = seconds
        self.last_sequence = sequence
        return reset
