"""Versioned offline dataset, annotation and injected replay contracts."""
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from core.capture import CaptureContract, Seconds, TimingEnvelope
from core.schemas import GoalEnd, Identifier, TeamID

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Split = Literal["train", "validation", "blind_test"]


def relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or "\\" in value or ":" in value or ".." in path.parts or str(path) == ".":
        raise ValueError("Asset paths must be relative POSIX paths inside the media root")
    return value


class Asset(CaptureContract):
    path: str
    sha256: Digest
    kind: Literal["video", "frame_index", "recording_manifest", "replay_events", "vision_observations", "clip"]

    @model_validator(mode="after")
    def safe_path(self):
        relative_path(self.path)
        return self


class Window(CaptureContract):
    start_seconds: Seconds
    end_seconds: Seconds

    @model_validator(mode="after")
    def increasing(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Window end must follow start")
        return self


class MatchWindow(Window):
    match_id: Identifier
    active_auto_windows: list[Window] = Field(default_factory=list)

    @model_validator(mode="after")
    def active_windows(self):
        previous = self.start_seconds
        for window in self.active_auto_windows:
            if window.start_seconds < previous or window.end_seconds > self.end_seconds:
                raise ValueError("Active-auto windows must be ordered, disjoint and inside the match")
            previous = window.end_seconds
        return self


class DatasetSession(CaptureContract):
    session_id: Identifier
    source_group_id: Identifier
    split: Split
    evidence: Literal["synthetic", "venue"]
    duration_seconds: Seconds
    host_clock_domain: Identifier
    configuration_version: Identifier
    model_version: Identifier
    calibration_versions: dict[Identifier, Identifier | None] = Field(default_factory=dict)
    matches: list[MatchWindow]
    assets: list[Asset]
    conditions: list[str] = Field(default_factory=list)
    physical_alignment_verified: bool = False

    @model_validator(mode="after")
    def boundaries(self):
        if self.duration_seconds <= 0 or not self.matches:
            raise ValueError("A session needs a duration and at least one scheduled match")
        previous = 0
        for window in self.matches:
            if window.start_seconds < previous or window.end_seconds > self.duration_seconds:
                raise ValueError("Scheduled matches must be ordered, disjoint and inside the session")
            previous = window.end_seconds
        if len({a.path for a in self.assets}) != len(self.assets):
            raise ValueError("Repeated asset path within a session")
        if sum(a.kind == "replay_events" for a in self.assets) != 1:
            raise ValueError("Each session needs exactly one replay event asset")
        return self


class DatasetManifest(CaptureContract):
    schema_version: Literal[1] = 1
    dataset_id: Identifier
    annotation_policy_version: Identifier
    split_assignment_version: Identifier
    split_frozen_at: AwareDatetime
    sessions: list[DatasetSession]

    @model_validator(mode="after")
    def isolation(self):
        if not self.sessions or len({s.session_id for s in self.sessions}) != len(self.sessions):
            raise ValueError("Dataset needs unique session IDs")
        groups, contents, matches = {}, {}, set()
        for session in self.sessions:
            if session.source_group_id in groups and groups[session.source_group_id] != session.split:
                raise ValueError("Source group leaks across dataset splits")
            groups[session.source_group_id] = session.split
            for match in session.matches:
                if match.match_id in matches:
                    raise ValueError("Match identity reused in multiple sessions/windows")
                matches.add(match.match_id)
            for asset in session.assets:
                if asset.kind in ("video", "frame_index", "replay_events", "vision_observations", "clip"):
                    if asset.sha256 in contents and contents[asset.sha256] != session.split:
                        raise ValueError("Media/event content checksum leaks across splits")
                    contents[asset.sha256] = session.split
        return self


class Annotation(CaptureContract):
    label_id: Identifier
    session_id: Identifier
    match_id: Identifier
    crossing_start_seconds: Seconds
    crossing_end_seconds: Seconds
    goal_end: GoalEnd
    team: TeamID | None = None
    validity: Literal["valid", "invalid", "uncertain"]
    visibility: Literal["clear", "partial", "occluded", "unobservable"]
    uncertainty_seconds: Seconds
    challenge: Literal["ordinary", "partial_crossing", "post_and_out", "post_and_in", "outside_net",
                       "player_impact", "loose_net", "ball_retrieval", "glare", "paused_play", "other"] = "ordinary"
    clip_path: str | None = None
    adjudicator: str = Field(min_length=1, max_length=100)
    notes: str = ""

    @model_validator(mode="after")
    def crossing(self):
        if self.crossing_end_seconds < self.crossing_start_seconds:
            raise ValueError("Crossing interval regresses")
        if self.validity == "valid" and self.team is None:
            raise ValueError("Valid goal requires adjudicated scoring team")
        if self.clip_path is not None:
            relative_path(self.clip_path)
        return self

    @property
    def crossing_seconds(self):
        return (self.crossing_start_seconds + self.crossing_end_seconds) / 2

    @property
    def timing_uncertainty(self):
        return self.uncertainty_seconds + (self.crossing_end_seconds - self.crossing_start_seconds) / 2


class SessionAudit(CaptureContract):
    session_id: Identifier
    continuous_footage_reviewed: bool
    reviewer: str = Field(min_length=1, max_length=100)
    notes: str = ""


class AnnotationSet(CaptureContract):
    schema_version: Literal[1] = 1
    dataset_id: Identifier
    version: Identifier
    split: Split
    annotation_policy_version: Identifier
    audits: list[SessionAudit]
    labels: list[Annotation]

    @model_validator(mode="after")
    def unique(self):
        if len({l.label_id for l in self.labels}) != len(self.labels):
            raise ValueError("Duplicate label ID")
        if len({a.session_id for a in self.audits}) != len(self.audits):
            raise ValueError("Duplicate session audit")
        return self


class ReplayEvent(CaptureContract):
    event_id: Identifier
    session_id: Identifier
    match_id: Identifier
    sequence: int = Field(ge=0)
    occurred_seconds: Seconds
    delivered_seconds: Seconds
    kind: Literal["observation", "decision"]
    goal_end: GoalEnd | None = None
    team: TeamID | None = None
    outcome: Literal["automatic", "manual", "operator_confirmed", "pending", "expired", "rejected"] | None = None
    shadow: bool = False
    review_required: bool = False
    corrected: bool = False
    displayed_seconds: Seconds | None = None
    display_uncertainty_seconds: Seconds | None = None
    timing_uncertainty_seconds: Seconds = 0
    clip_path: str | None = None
    source_timing: TimingEnvelope | None = None
    payload: dict[str, str | float | bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def causal(self):
        if self.delivered_seconds < self.occurred_seconds:
            raise ValueError("Delivery must not precede occurrence")
        if self.displayed_seconds is not None and self.displayed_seconds < self.delivered_seconds:
            raise ValueError("Display must not precede decision delivery")
        if self.kind == "decision" and self.outcome is None:
            raise ValueError("Decision needs an outcome")
        if self.kind == "decision" and self.goal_end is None:
            raise ValueError("Decision needs a mapped goal end")
        if self.kind == "observation" and self.outcome is not None:
            raise ValueError("Observation cannot be a goal decision")
        if self.outcome in ("automatic", "manual", "operator_confirmed") and self.team is None:
            raise ValueError("Confirmed/injected automatic decisions need a team")
        if self.clip_path is not None:
            relative_path(self.clip_path)
        return self


class ReplayOutput(CaptureContract):
    schema_version: Literal[1] = 1
    engine: Literal["injected-decisions-v1"] = "injected-decisions-v1"
    event_limit: int = Field(default=250000, ge=1, le=2000000)
    dataset_id: Identifier
    split: Split
    manifest_sha256: Digest
    input_fingerprint: Digest
    sessions: list[Identifier]
    configuration_versions: dict[Identifier, Identifier]
    model_versions: dict[Identifier, Identifier]
    trace: list[dict]
    decisions: list[ReplayEvent]
    final_virtual_seconds: Seconds
