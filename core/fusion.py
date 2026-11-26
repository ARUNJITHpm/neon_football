"""Fusion contracts. Shadow confirmations are never official scoring commands."""
from typing import Literal
from pydantic import Field, model_validator

from core.capture import CaptureContract, Seconds
from core.schemas import GoalEnd, Identifier, TeamID
from core.sensors import SensorAsset, SensorImpact
from core.dataset import Split
from core.vision import VisionCandidate

CandidateState = Literal["COLLECTING", "PENDING_REVIEW", "CONFIRMED", "REJECTED", "UNRESOLVED"]


class FusionCamera(CaptureContract):
    goal_end: GoalEnd
    calibration_version: Identifier
    model_version: Identifier
    configuration_version: Identifier


class FusionSettings(CaptureContract):
    schema_version: Literal[1] = 1
    version: Identifier = "fusion-rules-v1"
    cameras: dict[Identifier, FusionCamera]
    devices: dict[int, GoalEnd]
    sensor_configuration_version: Identifier = "impact-rules-v1"
    correlation_seconds: float = Field(default=.2, gt=0, le=1)
    collection_seconds: float = Field(default=.3, gt=0, le=2)
    maximum_evidence_age_seconds: float = Field(default=.5, gt=0, le=5)
    maximum_uncertainty_seconds: float = Field(default=.02, gt=0, le=.1)
    repeat_seconds: float = Field(default=.6, gt=0, le=2)
    review_seconds: float = Field(default=15, gt=0, le=300)
    max_candidates: int = Field(default=10000, ge=1, le=100000)
    max_inputs: int = Field(default=100000, ge=1, le=1000000)
    max_events: int = Field(default=250000, ge=20, le=3000000)
    mode: Literal["shadow"] = "shadow"
    automatic_score_mutation_allowed: Literal[False] = False

    @model_validator(mode="after")
    def limits(self):
        if not self.cameras or not self.devices or any(d < 1 for d in self.devices):
            raise ValueError("Register cameras and positive device IDs")
        if self.collection_seconds < self.correlation_seconds + 2*self.maximum_uncertainty_seconds:
            raise ValueError("Collection must cover the correlation window and timing bounds")
        return self


class FusionEvidence(CaptureContract):
    """Composition supplies the registered session, host clock and play epoch."""
    session_id: Identifier
    match_id: Identifier
    clock_domain: Identifier
    play_epoch: int = Field(ge=0)
    observation: VisionCandidate | SensorImpact = Field(discriminator="type")

    @model_validator(mode="after")
    def bounded_record(self):
        if len(self.observation.model_dump_json().encode("utf-8")) > 65536:
            raise ValueError("Fusion observation exceeds 64 KiB capacity")
        return self


class FusionCommand(CaptureContract):
    command_id: Identifier
    match_id: Identifier
    expected_revision: int = Field(ge=0)
    action: Literal["start", "pause", "resume", "end", "swap_ends", "restart", "confirm", "reject", "undo"]
    candidate_id: Identifier | None = None
    actor: Identifier

    @model_validator(mode="after")
    def target(self):
        if (self.action in ("confirm", "reject", "undo")) != (self.candidate_id is not None):
            raise ValueError("Candidate actions require exactly one candidate ID")
        return self


class FusedCandidate(CaptureContract):
    schema_version: Literal[1] = 1
    candidate_id: Identifier
    session_id: Identifier
    match_id: Identifier
    play_epoch: int
    goal_end: GoalEnd
    team: TeamID
    occurred_seconds: Seconds | None
    created_seconds: Seconds
    collect_until_seconds: Seconds
    review_until_seconds: Seconds | None = None
    status: CandidateState = "COLLECTING"
    evidence_ids: list[Identifier] = Field(default_factory=list)
    track_ids: list[Identifier] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    rule_label: Literal["collecting", "observed_and_corroborated", "review_required", "unresolved", "operator_decision"] = "collecting"
    confirmation: Literal["shadow_rule", "operator"] | None = None
    confirmed_seconds: Seconds | None = None
    corrected: bool = False
    configuration_version: Identifier
    automatic_score_mutation_allowed: Literal[False] = False


class FusionEvent(CaptureContract):
    schema_version: Literal[1] = 1
    event_id: Identifier
    revision: int = Field(ge=1)
    recorded_seconds: Seconds
    match_id: Identifier
    type: Identifier
    candidate_id: Identifier | None = None
    actor: Identifier = "fusion"
    details: dict = Field(default_factory=dict)


class FusionReference(CaptureContract):
    label_id: Identifier
    goal_end: GoalEnd
    team: TeamID
    occurred_seconds: Seconds
    validity: Literal["valid", "invalid", "uncertain"]


class FusionReplayStep(CaptureContract):
    at_seconds: Seconds
    kind: Literal["evidence", "command", "tick"]
    evidence: FusionEvidence | None = None
    action: Literal["start", "pause", "resume", "end", "swap_ends", "restart", "confirm", "reject", "undo"] | None = None
    command_id: Identifier | None = None
    candidate_evidence_id: Identifier | None = None
    expected_revision: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def layout(self):
        if (self.kind == "evidence") != (self.evidence is not None):
            raise ValueError("Evidence step needs its envelope")
        if self.kind == "command":
            if self.action is None or self.command_id is None:
                raise ValueError("Command step needs action and ID")
            if (self.action in ("confirm", "reject", "undo")) != (self.candidate_evidence_id is not None):
                raise ValueError("Candidate command needs its originating evidence ID")
        elif any(v is not None for v in (self.action, self.command_id, self.candidate_evidence_id, self.expected_revision)):
            raise ValueError("Command fields on a non-command step")
        return self


class FusionSession(CaptureContract):
    session_id: Identifier
    match_id: Identifier
    source_group_id: Identifier
    split: Split
    clock_domain: Identifier
    evidence: Literal["synthetic", "venue"]
    duration_seconds: float = Field(gt=0)
    goal_a_defending: TeamID = "orange"
    steps: SensorAsset
    labels: list[FusionReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def references(self):
        if any(l.occurred_seconds >= self.duration_seconds for l in self.labels):
            raise ValueError("Reference outside session")
        return self


class FusionDataset(CaptureContract):
    schema_version: Literal[1] = 1
    dataset_id: Identifier
    split_assignment_version: Identifier
    settings: FusionSettings
    provenance_assets: list[SensorAsset] = Field(default_factory=list)
    sessions: list[FusionSession]

    @model_validator(mode="after")
    def splits(self):
        if (not self.sessions or len({s.session_id for s in self.sessions}) != len(self.sessions) or
            len({s.match_id for s in self.sessions}) != len(self.sessions)):
            raise ValueError("Unique session/match IDs required")
        groups, hashes, labels = {}, {}, set()
        for s in self.sessions:
            if groups.get(s.source_group_id, s.split) != s.split or hashes.get(s.steps.sha256,s.split) != s.split:
                raise ValueError("Fusion source group/content leaks across splits")
            groups[s.source_group_id], hashes[s.steps.sha256] = s.split, s.split
            for label in s.labels:
                if label.label_id in labels:
                    raise ValueError("Incident label reused across sessions")
                labels.add(label.label_id)
        return self

