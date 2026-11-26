"""Offline observations and candidates; none of these contracts confirm a score."""
import math
from typing import Literal
from pydantic import Field, model_validator

from core.capture import CalibrationRecord, CaptureContract, Seconds
from core.dataset import Digest, relative_path
from core.schemas import GoalEnd, Identifier


class DepthPosition(CaptureContract):
    x_m: float
    y_m: float
    z_m: float
    uncertainty_m: tuple[Seconds, Seconds, Seconds]
    calibration_id: Identifier
    clock_domain: Identifier
    method: Literal["stereo", "external_depth", "synthetic"]
    observed: bool = True
    synchronized: bool = False


class Detection(CaptureContract):
    kind: Literal["ball", "player"]
    bbox: tuple[float, float, float, float]
    score: float = Field(ge=0, le=1)
    uncertainty_px: Seconds = 2
    depth: DepthPosition | None = None

    @model_validator(mode="after")
    def rectangle(self):
        x1, y1, x2, y2 = self.bbox
        if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
            raise ValueError("Detection needs a positive image-space box")
        if self.kind != "ball" and self.depth is not None:
            raise ValueError("Only ball detections carry crossing depth evidence")
        return self


class MotionEvidence(CaptureContract):
    net_changed_fraction: float | None = Field(default=None, ge=0, le=1)
    global_changed_fraction: float | None = Field(default=None, ge=0, le=1)
    flags: list[str] = Field(default_factory=list)
    baseline_frames: int = Field(default=0, ge=0)


class VisionFrame(CaptureContract):
    schema_version: Literal[1] = 1
    session_id: Identifier
    match_id: Identifier
    camera_id: Identifier
    boot_id: Identifier
    sequence: int = Field(ge=0)
    width: int = Field(ge=16, le=8192)
    height: int = Field(ge=16, le=8192)
    occurred_seconds: Seconds
    received_seconds: Seconds
    clock_domain: Identifier
    timing_uncertainty_seconds: Seconds | None = None
    evidence: Literal["synthetic", "venue"]
    detections: list[Detection] = Field(default_factory=list, max_length=100)
    motion: MotionEvidence = Field(default_factory=MotionEvidence)
    clip_path: str | None = None

    @model_validator(mode="after")
    def valid_frame(self):
        if self.received_seconds < self.occurred_seconds:
            raise ValueError("Receipt precedes occurrence")
        for detection in self.detections:
            if detection.bbox[2] > self.width or detection.bbox[3] > self.height:
                raise ValueError("Detection extends outside source image")
            if detection.depth and detection.depth.method == "synthetic" and self.evidence != "synthetic":
                raise ValueError("Synthetic depth cannot be represented as venue evidence")
        if self.clip_path is not None:
            relative_path(self.clip_path)
        return self


class GoalView(CaptureContract):
    camera_id: Identifier
    goal_end: GoalEnd
    calibration: CalibrationRecord
    calibration_evidence: Literal["synthetic", "venue", "unverified"] = "unverified"
    depth_calibration_id: Identifier | None = None
    opening_width_m: float = Field(gt=0)
    opening_height_m: float = Field(gt=0)
    ball_radius_m: float = Field(gt=0)
    plane_margin_m: Seconds = 0.01
    image_inward_direction: tuple[float, float] | None = None
    max_reprojection_error_px: float = Field(default=2, gt=0)

    @model_validator(mode="after")
    def geometry(self):
        if self.camera_id != self.calibration.camera_id:
            raise ValueError("Goal-view/camera identity mismatch")
        if 2*(self.ball_radius_m+self.plane_margin_m) >= min(self.opening_width_m, self.opening_height_m):
            raise ValueError("Ball/margin cannot fit inside the measured goal opening")
        if self.image_inward_direction is not None and math.hypot(*self.image_inward_direction) < 1e-9:
            raise ValueError("Image inward direction cannot be zero")
        return self


class VisionSettings(CaptureContract):
    schema_version: Literal[1] = 1
    version: Identifier
    views: list[GoalView]
    min_ball_score: float = Field(default=0.3, ge=0, le=1)
    max_prediction_seconds: float = Field(default=0.2, gt=0, le=1)
    max_crossing_gap_seconds: float = Field(default=0.15, gt=0, le=1)
    max_queue_age_seconds: float = Field(default=0.25, gt=0, le=5)
    max_timing_uncertainty_seconds: float = Field(default=0.02, gt=0, le=1)
    association_speed_px_per_second: float = Field(default=1500, gt=0)
    association_slack_px: float = Field(default=30, gt=0)
    prediction_uncertainty_px_per_second: float = Field(default=60, gt=0)
    prediction_uncertainty_m_per_second: float = Field(default=1, gt=0)
    min_inward_speed_m_per_second: float = Field(default=0.1, gt=0)
    min_image_inward_speed_px_per_second: float = Field(default=5, gt=0)
    net_motion_fraction: float = Field(default=0.15, gt=0, le=1)
    max_frame_count: int = Field(default=250000, ge=1, le=2000000)

    @model_validator(mode="after")
    def unique_views(self):
        if not self.views or len({v.camera_id for v in self.views}) != len(self.views):
            raise ValueError("Vision needs unique configured camera views")
        return self


class TrackPoint(CaptureContract):
    track_id: Identifier
    occurred_seconds: Seconds
    age_seconds: Seconds
    last_observed_seconds: Seconds
    observed: bool
    center_px: tuple[float, float]
    bbox: tuple[float, float, float, float]
    uncertainty_px: Seconds
    score: float = Field(ge=0, le=1)
    depth: DepthPosition | None = None
    flags: list[str] = Field(default_factory=list)


class VisionCandidate(CaptureContract):
    schema_version: Literal[1] = 1
    type: Literal["vision_candidate"] = "vision_candidate"
    event_id: Identifier
    session_id: Identifier
    match_id: Identifier
    camera_id: Identifier
    goal_end: GoalEnd
    track_id: Identifier | None
    occurred_seconds: Seconds
    emitted_seconds: Seconds
    timing_uncertainty_seconds: Seconds | None
    calibration_version: Identifier
    model_version: Identifier
    configuration_version: Identifier
    quality: Literal["observed_crossing", "predicted_crossing", "depth_ambiguous", "boundary_uncertain", "net_motion_only"]
    evidence: Literal["synthetic", "venue"]
    reasons: list[str]
    flags: list[str]
    requires_review: Literal[True] = True
    automatic_confirmation_allowed: Literal[False] = False
    clip_path: str | None = None
    supporting_sequences: list[int]
    crossing_interval_seconds: tuple[Seconds, Seconds] | None = None

    @model_validator(mode="after")
    def evidence_bounds(self):
        if self.emitted_seconds < self.occurred_seconds:
            raise ValueError("Candidate emission precedes its occurrence")
        if self.clip_path is not None:
            relative_path(self.clip_path)
        if self.crossing_interval_seconds is not None:
            a, b = self.crossing_interval_seconds
            if not a <= self.occurred_seconds <= b:
                raise ValueError("Crossing estimate lies outside its evidence interval")
        return self


class ModelDescriptor(CaptureContract):
    schema_version: Literal[1] = 1
    version: Identifier
    path: str
    sha256: Digest
    source: str = Field(min_length=1)
    licence: str = Field(min_length=1)
    licence_decision: Literal["not_reviewed", "approved_for_offline_use", "synthetic_fixture"]
    purpose: Literal["pretrained", "adapted", "synthetic_adapter_test"]
    input_width: int = Field(ge=32, le=2048)
    input_height: int = Field(ge=32, le=2048)
    class_count: int = Field(ge=1, le=1000)
    classes: dict[int, Literal["ball", "player"]]
    output_layout: Literal["raw_channels_first"] = "raw_channels_first"
    precision: Literal["float32"] = "float32"
    provider: Literal["CPUExecutionProvider"] = "CPUExecutionProvider"
    min_score: float = Field(default=0.25, ge=0, le=1)
    nms_iou: float = Field(default=0.45, gt=0, le=1)
    max_detections: int = Field(default=100, ge=1, le=100)
    pre_nms_limit: int = Field(default=1000, ge=1, le=5000)

    @model_validator(mode="after")
    def descriptor(self):
        relative_path(self.path)
        if not self.classes or any(i < 0 or i >= self.class_count for i in self.classes):
            raise ValueError("Class IDs do not fit the exported class-score channels")
        if self.purpose == "synthetic_adapter_test" and self.licence_decision != "synthetic_fixture":
            raise ValueError("Synthetic model must be identified as a synthetic fixture")
        if self.purpose != "synthetic_adapter_test" and self.licence_decision == "synthetic_fixture":
            raise ValueError("A pretrained/adapted model requires its own licence decision")
        return self
