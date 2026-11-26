"""Versioned sensor evidence contracts; impacts are never scoring commands."""
from typing import Literal
from pydantic import Field, model_validator

from core.capture import CaptureContract, Seconds
from core.dataset import Digest, Split, relative_path
from core.schemas import GoalEnd, Identifier

Role = Literal["net", "frame"]
ImpactKind = Literal["net_impact", "frame_impact", "mixed_impact", "slow_impact", "unknown"]


class SensorPacket(CaptureContract):
    protocol_version: Literal[1] = 1
    kind: Literal["samples", "health"]
    goal_end: GoalEnd
    role: Role
    flags: int = Field(default=0, ge=0, le=127)
    device_id: int = Field(ge=1, le=2**32-1)
    boot_id: int = Field(ge=1, le=2**64-1)
    packet_sequence: int = Field(ge=0, le=2**32-1)
    first_sample_sequence: int = Field(ge=0, le=2**64-1)
    first_device_us: int = Field(ge=0, le=2**64-1)
    rate_hz: Literal[800] = 800
    timestamp_uncertainty_us: int = Field(default=1250, ge=0, le=1000000)
    samples: list[tuple[int, int, int]] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def batch(self):
        if (self.kind == "samples") != bool(self.samples):
            raise ValueError("Sample packets need 1..32 samples; health packets need none")
        if any(not -4096 <= value <= 4095 for sample in self.samples for value in sample):
            raise ValueError("Expected full-resolution ADXL345 +/-16g raw codes")
        if self.first_sample_sequence+len(self.samples) > 2**64-1 or self.first_device_us+len(self.samples)*1250 > 2**64-1:
            raise ValueError("Counter wrap needs a new boot epoch")
        return self


class SensorAlignment(CaptureContract):
    version: Identifier
    device_id: int = Field(ge=1)
    boot_id: int = Field(ge=1)
    host_clock_domain: Identifier
    evidence: Literal["synthetic", "physical"]
    source_origin_seconds: Seconds
    host_origin_seconds: Seconds
    scale: float = Field(gt=0, le=2)
    uncertainty_seconds: Seconds
    valid_from_device_seconds: Seconds
    valid_to_device_seconds: Seconds

    @model_validator(mode="after")
    def span(self):
        if self.valid_to_device_seconds <= self.valid_from_device_seconds:
            raise ValueError("Alignment needs a validated device-clock span")
        return self


class SensorSample(CaptureContract):
    goal_end: GoalEnd
    role: Role
    device_id: int
    boot_id: int
    sequence: int
    transport_epoch: int = Field(default=0, ge=0)
    device_seconds: Seconds
    received_seconds: Seconds
    aligned_seconds: Seconds | None
    timing_uncertainty_seconds: Seconds | None
    host_clock_domain: Identifier
    evidence: Literal["synthetic", "venue", "unverified"]
    xyz_g: tuple[float, float, float]
    flags: list[str]


class SensorSettings(CaptureContract):
    version: Identifier = "impact-rules-v1"
    pre_seconds: float = Field(default=.4, gt=0, le=1)
    post_seconds: float = Field(default=.1, gt=0, le=.5)
    cooldown_seconds: float = Field(default=.6, gt=0, le=2)
    baseline_samples: int = Field(default=320, ge=80, le=800)
    baseline_max_rms_g: float = Field(default=.08, gt=0)
    trigger_g: float = Field(default=.6, gt=0)
    minimum_peak_g: float = Field(default=.6, gt=0)
    dominance_ratio: float = Field(default=1.8, gt=1)
    slow_roughness_ratio: float = Field(default=.12, gt=0, lt=1)
    max_timing_uncertainty_seconds: float = Field(default=.02, gt=0)
    max_delivery_age_seconds: float = Field(default=.25, gt=0)
    stale_seconds: float = Field(default=.3, gt=0)
    scale_g_per_lsb: float = Field(default=.0039, gt=0, le=.01)
    max_history_samples: int = Field(default=1600, ge=800, le=8000)

    @model_validator(mode="after")
    def capacity(self):
        if self.max_history_samples < (self.pre_seconds+self.post_seconds)*800+64:
            raise ValueError("History must cover a complete impact window plus one packet")
        if self.cooldown_seconds <= self.post_seconds:
            raise ValueError("Cooldown must exceed the follow-up window")
        return self


class SensorImpact(CaptureContract):
    schema_version: Literal[1] = 1
    type: Literal["sensor_impact"] = "sensor_impact"
    event_id: Identifier
    goal_end: GoalEnd
    device_id: int
    boot_id: int
    occurred_device_seconds: Seconds
    occurred_seconds: Seconds | None
    emitted_seconds: Seconds
    timing_uncertainty_seconds: Seconds | None
    host_clock_domain: Identifier
    evidence: Literal["synthetic", "venue", "unverified"]
    classification: ImpactKind
    features: dict[str, float]
    flags: list[str]
    configuration_version: Identifier
    possible_goal: Literal[True] = True
    automatic_confirmation_allowed: Literal[False] = False


class SensorAsset(CaptureContract):
    path: str
    sha256: Digest

    @model_validator(mode="after")
    def safe(self):
        relative_path(self.path)
        return self


class ImpactLabel(CaptureContract):
    incident_id: Identifier
    match_id: Identifier
    goal_end: GoalEnd
    occurred_seconds: Seconds
    physical_class: Literal["goal", "frame", "wall", "player", "noise", "post_and_in"]


class SensorSession(CaptureContract):
    session_id: Identifier
    match_id: Identifier
    source_group_id: Identifier
    split: Split
    evidence: Literal["synthetic", "venue"]
    duration_seconds: float = Field(gt=0)
    host_clock_domain: Identifier
    raw: SensorAsset
    devices: dict[int, GoalEnd]
    receipts: SensorAsset
    labels: list[ImpactLabel]
    alignments: list[SensorAlignment]

    @model_validator(mode="after")
    def boundaries(self):
        if any(l.match_id != self.match_id or l.occurred_seconds >= self.duration_seconds for l in self.labels):
            raise ValueError("Impact labels must belong to the scheduled match")
        identities = [(a.device_id, a.boot_id) for a in self.alignments]
        if len(identities) != len(set(identities)):
            raise ValueError("Duplicate device/boot alignment")
        if any(a.host_clock_domain != self.host_clock_domain or (self.evidence == "venue" and a.evidence != "physical") for a in self.alignments):
            raise ValueError("Alignment evidence/domain mismatch")
        if not self.devices or len(set(self.devices.values())) != len(self.devices) or any(a.device_id not in self.devices for a in self.alignments):
            raise ValueError("Register one board per end and each alignment's device")
        return self


class SensorDataset(CaptureContract):
    schema_version: Literal[1] = 1
    dataset_id: Identifier
    split_assignment_version: Identifier
    settings: SensorSettings
    sessions: list[SensorSession]

    @model_validator(mode="after")
    def splits(self):
        if not self.sessions or len({s.session_id for s in self.sessions}) != len(self.sessions) or len({s.match_id for s in self.sessions}) != len(self.sessions):
            raise ValueError("Unique sensor session/match identities required")
        groups, hashes, incidents = {}, {}, set()
        for session in self.sessions:
            if groups.get(session.source_group_id, session.split) != session.split:
                raise ValueError("Sensor source group leaks across splits")
            groups[session.source_group_id] = session.split
            for asset in (session.raw, session.receipts):
                if hashes.get(asset.sha256, session.split) != session.split:
                    raise ValueError("Sensor asset content leaks across splits")
                hashes[asset.sha256] = session.split
            for label in session.labels:
                if label.incident_id in incidents:
                    raise ValueError("Physical incident reused; keep all derived windows in one split")
                incidents.add(label.incident_id)
        return self
