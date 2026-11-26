from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


TeamID = Literal["orange", "green"]
GoalEnd = Literal["goal_a", "goal_b"]
Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.:-]+$")]
Name = Annotated[str, Field(min_length=1, max_length=60)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Player(Contract):
    id: Identifier
    name: Name
    team: TeamID
    bib: int = Field(ge=0, le=99)


class MatchSetup(Contract):
    orange_name: Name = "Orange"
    green_name: Name = "Green"
    duration_seconds: int = Field(default=1200, ge=60, le=14400)
    players: list[Player] = Field(default_factory=list, max_length=50)
    goal_a_defending: TeamID = "orange"
    active_player_ids: list[Identifier] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def unique_roster(self):
        if len({p.id for p in self.players}) != len(self.players):
            raise ValueError("Player IDs must be unique within the match")
        if len({(p.team, p.bib) for p in self.players}) != len(self.players):
            raise ValueError("Bib numbers must be unique within each team")
        if self.active_player_ids is not None and (len(set(self.active_player_ids)) != len(self.active_player_ids) or
            not set(self.active_player_ids).issubset({p.id for p in self.players})):
            raise ValueError("Active players must be unique registered roster IDs")
        return self


class Action(StrEnum):
    CREATE = "create"
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    END = "end"
    RECONCILE_CLOCK = "reconcile_clock"
    SWAP_ENDS = "swap_ends"
    MANUAL_GOAL = "manual_goal"
    UNDO_GOAL = "undo_goal"
    ATTRIBUTE_GOAL = "attribute_goal"
    CREATE_CANDIDATE = "create_candidate"
    CONFIRM_CANDIDATE = "confirm_candidate"
    REJECT_CANDIDATE = "reject_candidate"
    SET_REVIEW_MODE = "set_review_mode"
    DEMO_INCIDENT = "demo_incident"
    RESTART_PLAY = "restart_play"
    SUBSTITUTE_PLAYER = "substitute_player"
    DEMO_ATTRIBUTION = "demo_attribution"
    ACCEPT_ATTRIBUTION = "accept_attribution"
    REJECT_ATTRIBUTION = "reject_attribution"
    DEMO_ANALYTICS = "demo_analytics"
    CORRECT_ANALYTICS_TOUCH = "correct_analytics_touch"


class Command(Contract):
    schema_version: Literal[1] = 1
    command_id: Identifier = Field(default_factory=lambda: str(uuid4()))
    expected_revision: int = Field(ge=0)
    action: Action
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: AwareDatetime | None = None


class EmptyPayload(Contract):
    pass


class Attribution(Contract):
    scorer_id: Identifier | None = None
    assist_id: Identifier | None = None
    own_goal: bool = False


class ManualGoal(Attribution):
    team: TeamID
    candidate_id: Identifier | None = None


class GoalReference(Contract):
    goal_id: Identifier


class GoalAttribution(Attribution):
    goal_id: Identifier


class CandidateInput(Contract):
    candidate_id: Identifier
    goal_end: GoalEnd
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class CandidateReference(Contract):
    candidate_id: Identifier


class ReviewMode(Contract):
    mode: Literal["manual", "demo_review"]


class DemoIncident(Contract):
    goal_end: GoalEnd
    scenario: Literal["observed", "partial", "net_contact", "missing_clip", "pending_clip", "failed_clip"]


class SubstitutePlayer(Contract):
    outgoing_id: Identifier
    incoming_id: Identifier


class DemoAttribution(Contract):
    goal_id: Identifier
    scenario: Literal["direct", "assist", "own_goal", "uncertain", "deflection", "identity_switch"] = "direct"


class AttributionReference(Contract):
    goal_id: Identifier
    suggestion_id: Identifier


class DemoAnalytics(Contract):
    scenario: Literal["passing", "pauses", "gaps", "uncertain"] = "passing"


class AnalyticsTouchCorrection(Contract):
    session_id: Identifier
    touch_id: Identifier
    player_id: Identifier | None = None
    kind: Literal["control", "controlled_pass", "interception", "shot", "deflection", "frame_rebound", "proximity", "unknown"]
    certainty: Literal["certain", "uncertain"] = "uncertain"
    void: bool = False


class ReconcileClock(Contract):
    elapsed_seconds: float = Field(ge=0, le=86400, allow_inf_nan=False)


PAYLOADS: dict[Action, type[Contract]] = {
    Action.CREATE: MatchSetup,
    Action.MANUAL_GOAL: ManualGoal,
    Action.UNDO_GOAL: GoalReference,
    Action.ATTRIBUTE_GOAL: GoalAttribution,
    Action.CREATE_CANDIDATE: CandidateInput,
    Action.CONFIRM_CANDIDATE: CandidateReference,
    Action.REJECT_CANDIDATE: CandidateReference,
    Action.RECONCILE_CLOCK: ReconcileClock,
    Action.SET_REVIEW_MODE: ReviewMode,
    Action.DEMO_INCIDENT: DemoIncident,
    Action.SUBSTITUTE_PLAYER: SubstitutePlayer,
    Action.DEMO_ATTRIBUTION: DemoAttribution,
    Action.ACCEPT_ATTRIBUTION: AttributionReference,
    Action.REJECT_ATTRIBUTION: AttributionReference,
    Action.DEMO_ANALYTICS: DemoAnalytics,
    Action.CORRECT_ANALYTICS_TOUCH: AnalyticsTouchCorrection,
}


class Event(Contract):
    schema_version: Literal[1] = 1
    event_id: str
    command_id: str
    match_id: str
    revision: int
    type: Literal["match_created", "match_started", "match_paused", "match_resumed", "match_ended",
                  "candidate_created", "goal_confirmed", "goal_rejected", "attribution_changed",
                  "correction_applied", "health_changed", "clock_interrupted", "clock_reconciled", "ends_changed",
                  "review_mode_changed", "play_restarted", "candidate_expired", "player_substituted",
                  "attribution_suggested", "attribution_rejected", "analytics_session_added", "analytics_touch_corrected"]
    occurred_at: datetime
    recorded_at: datetime
    actor: str
    source: Literal["operator", "system"]
    correlation_id: str
    payload: dict[str, Any]
