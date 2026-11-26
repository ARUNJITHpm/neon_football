"""Bounded contact analytics contracts; no pitch tracking or camera claims."""
from typing import Literal, Protocol
from copy import deepcopy

from pydantic import Field, model_validator

from core.attribution import AttributionRoster
from core.capture import CaptureContract, Seconds
from core.dataset import Digest, Split, relative_path
from core.schemas import Identifier


class AnalyticsSettings(CaptureContract):
    schema_version: Literal[1] = 1
    rule_version: Identifier = "contact-analytics-v1"
    maximum_chain_gap_seconds: float = Field(default=3, gt=0, le=10)
    possession_hold_seconds: float = Field(default=3, gt=0, le=10)
    maximum_uncertainty_seconds: float = Field(default=.02, ge=0, le=1)
    automatic_write_allowed: Literal[False] = False


class AnalyticsPeriod(CaptureContract):
    start_seconds: Seconds
    end_seconds: Seconds
    state: Literal["in_play", "paused", "dead_ball", "unknown"]
    touch_coverage: Literal["complete", "partial", "unknown"] = "unknown"

    @model_validator(mode="after")
    def duration(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Period must have positive duration")
        return self


class AnalyticsRosterEpoch(CaptureContract):
    start_seconds: Seconds
    roster: AttributionRoster


class AnalyticsContact(CaptureContract):
    touch_id: Identifier
    occurred_seconds: Seconds
    uncertainty_seconds: float | None = Field(default=None, ge=0)
    player_id: Identifier | None = None
    kind: Literal["control", "controlled_pass", "interception", "shot", "deflection", "frame_rebound", "proximity", "unknown"]
    certainty: Literal["certain", "uncertain"] = "uncertain"
    source_id: Identifier
    boot_id: Identifier
    play_epoch: int = Field(ge=0)
    roster_revision: int = Field(ge=0)


class AnalyticsSession(CaptureContract):
    schema_version: Literal[1] = 1
    session_id: Identifier
    match_id: Identifier
    duration_seconds: float = Field(gt=0, le=14400)
    evidence: Literal["synthetic", "venue"]
    timing_quality: Literal["synthetic_aligned", "measured", "unverified"] = "unverified"
    periods: list[AnalyticsPeriod] = Field(min_length=1, max_length=1000)
    rosters: list[AnalyticsRosterEpoch] = Field(min_length=1, max_length=1000)
    contacts: list[AnalyticsContact] = Field(default_factory=list, max_length=10000)
    conditions: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def consistent(self):
        boundary = 0
        for period in self.periods:
            if abs(period.start_seconds - boundary) > 1e-9:
                raise ValueError("Periods must partition the complete window without gaps or overlaps")
            boundary = period.end_seconds
        if abs(boundary - self.duration_seconds) > 1e-9:
            raise ValueError("Periods must end at session duration")
        if self.rosters[0].start_seconds != 0:
            raise ValueError("First roster epoch must start at zero")
        registered = self.rosters[0].roster.players
        for index, epoch in enumerate(self.rosters):
            if epoch.roster.match_id != self.match_id or epoch.roster.players != registered or epoch.start_seconds >= self.duration_seconds:
                raise ValueError("Roster epoch match/registered players/window differs")
            if index and (epoch.start_seconds <= self.rosters[index-1].start_seconds or epoch.roster.revision <= self.rosters[index-1].roster.revision):
                raise ValueError("Roster epochs must increase in time and revision")
        if len({c.touch_id for c in self.contacts}) != len(self.contacts):
            raise ValueError("Contact IDs must be unique")
        epochs = self.rosters
        for contact in self.contacts:
            if contact.occurred_seconds >= self.duration_seconds:
                raise ValueError("Contact must be inside the session window")
            epoch = next(e for e in reversed(epochs) if e.start_seconds <= contact.occurred_seconds)
            if contact.roster_revision != epoch.roster.revision:
                raise ValueError("Contact roster revision differs from time-local epoch")
            if contact.player_id is not None and contact.player_id not in {p.id for p in registered}:
                raise ValueError("Contact player is not registered")
        if self.evidence == "venue" and self.timing_quality == "synthetic_aligned":
            raise ValueError("Venue time cannot use synthetic alignment")
        return self


class AnalyticsSubmission(CaptureContract):
    session: AnalyticsSession

    @model_validator(mode="after")
    def dummy_only(self):
        if self.session.evidence != "synthetic":
            raise ValueError("Live analytics prototype accepts generated sessions only")
        return self


class AnalyticsEventReference(CaptureContract):
    kind: Literal["pass", "interception"]
    previous_touch_id: Identifier
    touch_id: Identifier
    team: Literal["orange", "green"]
    from_player_id: Identifier
    to_player_id: Identifier


class AnalyticsReference(CaptureContract):
    passes: int = Field(ge=0)
    interceptions: int = Field(ge=0)
    possession_seconds: dict[Literal["orange", "green", "unknown"], Seconds]
    adjudication: Literal["generated_reference", "independent_review"]
    events: list[AnalyticsEventReference] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def fields(self):
        if set(self.possession_seconds) != {"orange", "green", "unknown"}:
            raise ValueError("Possession reference needs both teams and unknown")
        if len({(e.kind,e.previous_touch_id,e.touch_id) for e in self.events})!=len(self.events) or sum(e.kind=="pass" for e in self.events)!=self.passes or sum(e.kind=="interception" for e in self.events)!=self.interceptions:
            raise ValueError("Reference event identities/counts differ")
        return self


class AnalyticsAsset(CaptureContract):
    session_id: Identifier
    match_id: Identifier
    source_group_id: Identifier
    split: Split
    path: str
    sha256: Digest
    reference: AnalyticsReference

    @model_validator(mode="after")
    def safe_path(self):
        relative_path(self.path)
        return self


class AnalyticsDataset(CaptureContract):
    schema_version: Literal[1] = 1
    dataset_id: Identifier
    evidence: Literal["synthetic", "venue"]
    settings: AnalyticsSettings = Field(default_factory=AnalyticsSettings)
    sessions: list[AnalyticsAsset] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def isolation(self):
        mappings = ({}, {}, {})
        if len({s.session_id for s in self.sessions}) != len(self.sessions) or len({s.path for s in self.sessions}) != len(self.sessions):
            raise ValueError("Analytics sessions/assets must be unique")
        for session in self.sessions:
            for mapping, key in zip(mappings, (session.match_id, session.source_group_id, session.sha256)):
                if key in mapping and mapping[key] != session.split:
                    raise ValueError("Analytics split leakage")
                mapping[key] = session.split
            if self.evidence == "venue" and session.reference.adjudication != "independent_review":
                raise ValueError("Venue analytics requires independent reference review")
        return self


class AnalyticsService(Protocol):
    def prepare(self, match_id, command, snapshot) -> AnalyticsSubmission: ...


def apply_corrections(session, corrections=()):
    """Rebuild effective contacts without rewriting the original evidence."""
    data = deepcopy(session.model_dump() if isinstance(session, AnalyticsSession) else session)
    voided = set()
    by_id = {contact["touch_id"]: contact for contact in data["contacts"]}
    for correction in corrections:
        change = correction["change"]
        if change["session_id"] != data["session_id"] or change["touch_id"] not in by_id:
            raise ValueError("Analytics correction references no source contact")
        by_id[change["touch_id"]].update({key: change[key] for key in ("player_id", "kind", "certainty")})
        if change["void"]: voided.add(change["touch_id"])
        else: voided.discard(change["touch_id"])
    data["contacts"] = [contact for contact in data["contacts"] if contact["touch_id"] not in voided]
    return AnalyticsSession.model_validate(data)
