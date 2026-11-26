"""Versioned capture/timing contracts shared by acquisition and future vision."""
from dataclasses import dataclass
import math
from typing import Annotated, Literal, Protocol

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from core.schemas import Contract, Identifier


Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Point = tuple[float, float]


class CaptureContract(Contract):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class CameraConfig(CaptureContract):
    id: Identifier
    kind: Literal["file", "rtsp", "dshow", "v4l2"] = "file"
    source: str | None = None
    source_env: Identifier | None = None
    width: int = Field(default=1280, ge=16, le=8192)
    height: int = Field(default=720, ge=16, le=8192)
    expected_fps: float = Field(default=60, gt=0, le=240)
    realtime: bool = True
    reconnect: bool = True
    calibration_path: str | None = None

    @model_validator(mode="after")
    def one_source(self):
        if bool(self.source) == bool(self.source_env):
            raise ValueError("Provide exactly one of source or source_env")
        return self


class CaptureSettings(CaptureContract):
    enabled: bool = False
    root: str = "data/recordings"
    ffmpeg: str = "ffmpeg"
    jpeg_quality: int = Field(default=3, ge=2, le=31)
    max_frame_bytes: int = Field(default=16 * 1024 * 1024, ge=1024)
    live_queue_capacity: int = Field(default=2, ge=1, le=64)
    buffer_seconds: float = Field(default=6, gt=0, le=30)
    buffer_max_bytes: int = Field(default=64 * 1024 * 1024, ge=1024)
    clip_pre_seconds: float = Field(default=3, ge=0, le=10)
    clip_post_seconds: float = Field(default=3, ge=0, le=10)
    clip_max_bytes: int = Field(default=128 * 1024 * 1024, ge=1024)
    max_pending_clips: int = Field(default=8, ge=1, le=64)
    stale_seconds: float = Field(default=3, gt=0, le=60)
    startup_timeout_seconds: float = Field(default=15, gt=0, le=120)
    reconnect_seconds: float = Field(default=1, gt=0, le=60)
    segment_seconds: float = Field(default=60, gt=0, le=3600)
    max_session_bytes: int = Field(default=50 * 1024**3, ge=1024)
    min_free_bytes: int = Field(default=1024**3, ge=0)

    @model_validator(mode="after")
    def sufficient_history(self):
        if self.buffer_seconds < self.clip_pre_seconds:
            raise ValueError("buffer_seconds must cover clip_pre_seconds")
        return self


class TimingEnvelope(CaptureContract):
    schema_version: Literal[1] = 1
    source_id: Identifier
    boot_id: Identifier
    sequence: int = Field(ge=0)
    source_sequence: int | None = Field(default=None, ge=0)
    source_seconds: float | None = None
    source_clock_domain: str
    host_clock_domain: Identifier
    host_monotonic_seconds: Seconds
    received_at: AwareDatetime
    quality: Literal["media_pts", "exposure", "receipt_only"]
    offset_seconds: float | None = None
    uncertainty_seconds: Seconds | None = None
    clock_reset: bool = False


class FrameMetadata(CaptureContract):
    camera_id: Identifier
    timing: TimingEnvelope
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    encoding: Literal["jpeg"] = "jpeg"


@dataclass(frozen=True)
class EncodedFrame:
    metadata: FrameMetadata
    jpeg: bytes


class CalibrationRecord(CaptureContract):
    schema_version: Literal[1] = 1
    camera_id: Identifier
    version: Identifier
    status: Literal["draft", "measured"] = "draft"
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    lens_model: Literal["pinhole", "fisheye"] = "pinhole"
    intrinsics: list[list[float]] | None = None
    distortion: list[float] | None = None
    reprojection_error_px: Seconds | None = None
    goal_roi: list[Point] = Field(default_factory=list)
    net_roi: list[Point] = Field(default_factory=list)
    pitch_corners: list[Point] = Field(default_factory=list)
    floor_homography: list[list[float]] | None = None
    placement: dict[str, str | float | None] = Field(default_factory=dict)
    goal_geometry: dict[str, str | float | list | None] = Field(default_factory=dict)
    notes: str = ""

    @model_validator(mode="after")
    def geometry(self):
        def finite_nested(value):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Calibration geometry must be finite")
            if isinstance(value, dict):
                for child in value.values():
                    finite_nested(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    finite_nested(child)
        finite_nested(self.goal_geometry)
        for name in ("goal_roi", "net_roi", "pitch_corners"):
            points = getattr(self, name)
            if points and len(points) < 3:
                raise ValueError(f"{name} needs at least three points")
            if name == "pitch_corners" and points and len(points) != 4:
                raise ValueError("pitch_corners needs four ordered corners")
            for x, y in points:
                if not (0 <= x < self.width and 0 <= y < self.height):
                    raise ValueError(f"{name} point lies outside the configured image")
            if points:
                area = sum(points[i][0] * points[(i + 1) % len(points)][1] -
                           points[(i + 1) % len(points)][0] * points[i][1] for i in range(len(points)))
                if abs(area) < 1:
                    raise ValueError(f"{name} is degenerate or has crossed edges")
                def orientation(a, b, c):
                    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
                if len(set(points)) != len(points):
                    raise ValueError(f"{name} has duplicate vertices")
                for i in range(len(points)):
                    a, b = points[i], points[(i + 1) % len(points)]
                    for j in range(i + 1, len(points)):
                        if j == i + 1 or (i == 0 and j == len(points) - 1):
                            continue
                        c, d = points[j], points[(j + 1) % len(points)]
                        if orientation(a, b, c) * orientation(a, b, d) <= 0 and orientation(c, d, a) * orientation(c, d, b) <= 0:
                            if (max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0])) and
                                    max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1]))):
                                raise ValueError(f"{name} has crossed or touching edges")
        for name in ("intrinsics", "floor_homography"):
            matrix = getattr(self, name)
            if matrix is not None and (len(matrix) != 3 or any(len(row) != 3 for row in matrix)):
                raise ValueError(f"{name} must be a 3 by 3 matrix")
        if self.intrinsics is not None:
            k = self.intrinsics
            if k[0][0] <= 0 or k[1][1] <= 0 or k[2] != [0, 0, 1]:
                raise ValueError("Intrinsics need positive focal lengths and last row [0, 0, 1]")
        if self.floor_homography is not None:
            h = self.floor_homography
            determinant = (h[0][0]*(h[1][1]*h[2][2] - h[1][2]*h[2][1]) -
                           h[0][1]*(h[1][0]*h[2][2] - h[1][2]*h[2][0]) +
                           h[0][2]*(h[1][0]*h[2][1] - h[1][1]*h[2][0]))
            if abs(determinant) < 1e-12:
                raise ValueError("floor_homography must be invertible")
        if self.distortion is not None:
            lengths = (4,) if self.lens_model == "fisheye" else (4, 5, 8, 12, 14)
            if len(self.distortion) not in lengths:
                raise ValueError("Distortion coefficients do not match the lens model")
        if self.status == "measured" and (self.intrinsics is None or self.distortion is None or
                                          self.reprojection_error_px is None or not self.goal_roi):
            raise ValueError("Measured calibration requires intrinsics, distortion, reprojection error and goal ROI")
        return self


class SegmentRecord(CaptureContract):
    path: str
    index_path: str
    boot_id: Identifier
    frames: int = Field(ge=0)
    bytes: int = Field(ge=0)
    sha256: str
    index_sha256: str
    first_host_seconds: Seconds | None = None
    last_host_seconds: Seconds | None = None
    first_source_seconds: float | None = None
    last_source_seconds: float | None = None
    complete: bool


class CameraRecord(CaptureContract):
    camera_id: Identifier
    kind: str
    width: int
    height: int
    expected_fps: float
    observed_width: int | None = None
    observed_height: int | None = None
    timestamp_quality: Literal["media_pts", "receipt_only"] = "media_pts"
    calibration: CalibrationRecord | None = None
    calibration_valid: bool = False
    calibration_error: str | None = None
    frames: int = 0
    encoded_bytes: int = 0
    live_dropped_frames: int = 0
    gaps: int = 0
    clock_resets: int = 0
    reconnects: int = 0
    write_seconds: float = 0
    segments: list[SegmentRecord] = Field(default_factory=list)


class RecordingManifest(CaptureContract):
    schema_version: Literal[1] = 1
    session_id: Identifier
    host_clock_domain: Identifier
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    status: Literal["recording", "closed", "failed"]
    backend: Literal["ffmpeg-mjpeg"] = "ffmpeg-mjpeg"
    backend_version: str
    capture_settings: CaptureSettings
    cameras: list[CameraRecord]
    incidents_path: str = "incidents.jsonl"
    timing_alignment_verified: bool = False
    error: str | None = None


class ClipRequest(CaptureContract):
    camera_id: Identifier
    clip_id: Identifier
    event_monotonic_seconds: Seconds | None = None
    event_id: Identifier | None = None


class CaptureService(Protocol):
    def status(self) -> dict: ...

    def request_clip(self, request: ClipRequest) -> dict: ...

    def clip_status(self, clip_id: str) -> dict: ...

    def clip_file(self, clip_id: str): ...

    def close(self) -> None: ...
