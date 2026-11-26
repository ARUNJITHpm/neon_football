"""Versioned observed-identity/touch contracts; suggestions never change team scores."""
from typing import Literal, Protocol

from pydantic import Field, model_validator

from core.capture import CaptureContract, Seconds
from core.dataset import Digest, Split, relative_path
from core.schemas import GoalEnd, Identifier, Player, TeamID


class AttributionSettings(CaptureContract):
    schema_version: Literal[1] = 1
    rule_version: Identifier = "conservative-attribution-v1"
    minimum_identity_reads: int = Field(default=3, ge=2, le=10)
    identity_window_seconds: float = Field(default=1.5, gt=0, le=10)
    touch_lookback_seconds: float = Field(default=10, gt=0, le=30)
    max_uncertainty_seconds: float = Field(default=.02, ge=0, le=1)
    automatic_write_allowed: Literal[False] = False


class AttributionRoster(CaptureContract):
    match_id: Identifier
    revision: int = Field(ge=0)
    players: list[Player] = Field(max_length=50)
    active_player_ids: list[Identifier] = Field(max_length=50)

    @model_validator(mode="after")
    def unique(self):
        ids = {p.id for p in self.players}
        if len(ids) != len(self.players) or len({(p.team, p.bib) for p in self.players}) != len(ids):
            raise ValueError("Roster IDs and team/bib pairs must be unique")
        if len(set(self.active_player_ids)) != len(self.active_player_ids) or not set(self.active_player_ids).issubset(ids):
            raise ValueError("Active roster must contain unique registered IDs")
        return self


class IdentityReading(CaptureContract):
    event_id: Identifier
    match_id: Identifier
    session_id: Identifier
    roster_revision: int = Field(ge=0)
    camera_id: Identifier
    boot_id: Identifier
    track_id: Identifier
    frame_sequence: int = Field(ge=0)
    occurred_seconds: Seconds
    team: TeamID | None = None
    bib: int | None = Field(default=None, ge=0, le=99)
    quality: Literal["clear", "uncertain", "occluded"] = "uncertain"
    evidence: Literal["synthetic", "venue"]


class TouchObservation(CaptureContract):
    event_id: Identifier
    match_id: Identifier
    session_id: Identifier
    roster_revision: int = Field(ge=0)
    occurred_seconds: Seconds
    uncertainty_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    camera_id: Identifier
    boot_id: Identifier
    track_id: Identifier | None = None
    kind: Literal["controlled_pass", "shot", "control", "interception", "deflection", "frame_rebound", "proximity", "unknown"]
    certainty: Literal["certain", "uncertain"] = "uncertain"
    evidence: Literal["synthetic", "venue"]


class AttributionGoal(CaptureContract):
    match_id: Identifier
    session_id: Identifier
    goal_id: Identifier
    scoring_team: TeamID
    goal_end: GoalEnd
    occurred_seconds: Seconds
    uncertainty_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    timing_quality: Literal["synthetic_aligned", "measured", "unverified"] = "unverified"
    touch_coverage: Literal["complete", "partial", "unknown"] = "unknown"
    evidence: Literal["synthetic", "venue"]


class AttributionSequence(CaptureContract):
    schema_version: Literal[1] = 1
    goal: AttributionGoal
    roster: AttributionRoster
    readings: list[IdentityReading] = Field(default_factory=list, max_length=10000)
    touches: list[TouchObservation] = Field(default_factory=list, max_length=1000)
    conditions: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def identity(self):
        if self.roster.match_id != self.goal.match_id:
            raise ValueError("Goal/roster match differs")
        observations = [*self.readings, *self.touches]
        if len({o.event_id for o in observations}) != len(observations):
            raise ValueError("Observation IDs must be unique")
        if any((o.match_id, o.session_id, o.roster_revision, o.evidence) !=
               (self.goal.match_id, self.goal.session_id, self.roster.revision, self.goal.evidence) for o in observations):
            raise ValueError("Observation match/session/roster/provenance differs")
        if len({(r.camera_id, r.boot_id, r.track_id, r.frame_sequence) for r in self.readings}) != len(self.readings):
            raise ValueError("A repeated track/frame cannot add identity support")
        tracks = {}
        for reading in sorted(self.readings, key=lambda r: (r.occurred_seconds, r.frame_sequence)):
            key = (reading.camera_id, reading.boot_id, reading.track_id)
            if key in tracks and reading.frame_sequence <= tracks[key]:
                raise ValueError("Frame sequence reset requires a new boot/track identity")
            tracks[key] = reading.frame_sequence
        if self.goal.evidence == "venue" and self.goal.timing_quality == "synthetic_aligned":
            raise ValueError("Venue timing cannot use synthetic alignment")
        return self


class IdentityDecision(CaptureContract):
    player_id: Identifier | None = None
    reason: str
    reading_ids: list[Identifier] = Field(default_factory=list, max_length=10000)


class AttributionSuggestion(CaptureContract):
    schema_version: Literal[1] = 1
    suggestion_id: Identifier
    goal_id: Identifier
    match_id: Identifier
    roster_revision: int = Field(ge=0)
    scoring_team: TeamID
    scorer_id: Identifier | None = None
    assist_id: Identifier | None = None
    assist_status: Literal["suggested", "none", "unknown"] = "unknown"
    own_goal: bool | None = None
    reasons: list[str] = Field(min_length=1, max_length=30)
    identities: dict[Identifier, IdentityDecision] = Field(default_factory=dict, max_length=1000)
    evidence: Literal["synthetic", "venue"]
    rule_version: Identifier
    automatic_write_allowed: Literal[False] = False
    operator_review_required: Literal[True] = True


class AttributionSubmission(CaptureContract):
    suggestion: AttributionSuggestion
    sequence: AttributionSequence

    @model_validator(mode="after")
    def consistent(self):
        s, g = self.suggestion, self.sequence.goal
        if (s.match_id, s.goal_id, s.scoring_team, s.roster_revision, s.evidence) != (
            g.match_id, g.goal_id, g.scoring_team, self.sequence.roster.revision, g.evidence):
            raise ValueError("Suggestion/sequence identity differs")
        if s.evidence != "synthetic":
            raise ValueError("This live prototype accepts dummy attribution submissions only")
        active = {p.id: p for p in self.sequence.roster.players if p.id in self.sequence.roster.active_player_ids}
        if any(player is not None and player not in active for player in (s.scorer_id, s.assist_id)):
            raise ValueError("Suggested players must be active in the captured roster")
        if s.scorer_id is not None and (s.own_goal is None or (active[s.scorer_id].team != s.scoring_team) != s.own_goal):
            raise ValueError("Scorer team/own-goal suggestion differs")
        if (s.assist_status == "suggested") != (s.assist_id is not None):
            raise ValueError("Assist status and player differ")
        if s.assist_id is not None and (s.own_goal is not False or active[s.assist_id].team != s.scoring_team or s.assist_id == s.scorer_id):
            raise ValueError("Assist must be a different scoring-team player without own goal")
        return self


class AttributionLabel(CaptureContract):
    goal_id: Identifier
    scorer_id: Identifier | None
    assist_id: Identifier | None
    own_goal: bool | None
    adjudication: Literal["generated_reference", "independent_review"]
    scorer_known: bool = True
    assist_known: bool = True
    own_goal_known: bool = True


class AttributionAsset(CaptureContract):
    session_id: Identifier
    source_group_id: Identifier
    match_id: Identifier
    split: Split
    path: str
    sha256: Digest
    label: AttributionLabel

    @model_validator(mode="after")
    def path_valid(self):
        relative_path(self.path)
        return self


class AttributionDataset(CaptureContract):
    schema_version: Literal[1] = 1
    dataset_id: Identifier
    annotation_policy: Identifier
    evidence: Literal["synthetic", "venue"]
    settings: AttributionSettings
    sessions: list[AttributionAsset] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def isolation(self):
        groups, hashes, matches = {}, {}, {}
        if len({s.session_id for s in self.sessions}) != len(self.sessions) or len({s.path for s in self.sessions}) != len(self.sessions):
            raise ValueError("Sessions and assets must be unique")
        for session in self.sessions:
            for mapping, key in ((groups, session.source_group_id), (hashes, session.sha256), (matches, session.match_id)):
                if key in mapping and mapping[key] != session.split:
                    raise ValueError("Attribution split leakage")
                mapping[key] = session.split
            if self.evidence == "venue" and session.label.adjudication != "independent_review":
                raise ValueError("Venue truth requires independent review")
        return self


class AttributionService(Protocol):
    def prepare(self, match_id, command, snapshot) -> AttributionSubmission: ...
