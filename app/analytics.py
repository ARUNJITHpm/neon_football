"""Generate explicitly synthetic contact windows, independent of the match clock."""
import hashlib

from core.analytics import AnalyticsSession, AnalyticsPeriod, AnalyticsRosterEpoch, AnalyticsContact, AnalyticsSubmission
from core.attribution import AttributionRoster
from core.schemas import DemoAnalytics


def dummy_session(*, match_id, session_id, players, active_player_ids, roster_revision=0, scenario="passing", uncertainty=.005):
    roster = AttributionRoster(match_id=match_id, revision=roster_revision, players=players, active_player_ids=active_player_ids)
    active = [p for p in roster.players if p.id in active_player_ids]
    green = [p.id for p in active if p.team == "green"]
    orange = [p.id for p in active if p.team == "orange"]
    g1, g2 = green[0] if green else None, green[1] if len(green)>1 else None
    o1, o2 = orange[0] if orange else None, orange[1] if len(orange)>1 else None
    duration = 25 if scenario == "pauses" else 12
    periods = [AnalyticsPeriod(start_seconds=0, end_seconds=duration, state="in_play", touch_coverage="complete")]
    contacts = [(1,g1,"controlled_pass"),(3,g2,"control"),(5,g2,"controlled_pass"),(7,g1,"control"),(9,o1,"interception"),(11,o2,"control")]
    if scenario == "pauses":
        periods = [AnalyticsPeriod(start_seconds=a,end_seconds=b,state=state,touch_coverage="complete") for a,b,state in
                   [(0,10,"in_play"),(10,14,"paused"),(14,20,"in_play"),(20,22,"dead_ball"),(22,25,"in_play")]]
        contacts = [(1,g1,"controlled_pass"),(3,g2,"control"),(8,g2,"controlled_pass"),(14,g1,"control"),
                    (16,g1,"controlled_pass"),(18,o1,"interception"),(22,o1,"controlled_pass"),(24,o2,"control")]
    if scenario == "gaps":
        periods = [AnalyticsPeriod(start_seconds=a,end_seconds=b,state="in_play",touch_coverage=coverage) for a,b,coverage in
                   [(0,4,"complete"),(4,8,"partial"),(8,12,"complete")]]
        contacts[-1] = (11,g1,"control")
    observations = [AnalyticsContact(touch_id=f"touch-{index}",occurred_seconds=at,uncertainty_seconds=uncertainty,
        player_id=player,kind=kind,certainty="certain",source_id="generated-contacts",boot_id="dummy-boot",play_epoch=0,
        roster_revision=roster_revision) for index,(at,player,kind) in enumerate(contacts)]
    if scenario == "uncertain":
        observations[1].certainty="uncertain"
        observations[4].kind="deflection"; observations[4].certainty="uncertain"
    return AnalyticsSession(session_id=session_id,match_id=match_id,duration_seconds=duration,evidence="synthetic",
        timing_quality="synthetic_aligned",periods=periods,rosters=[AnalyticsRosterEpoch(start_seconds=0,roster=roster)],
        contacts=observations,conditions=["generated_numeric_contacts",scenario])


class DummyAnalytics:
    def prepare(self, match_id, command, snapshot):
        payload = DemoAnalytics.model_validate(command.payload)
        session = dummy_session(match_id=match_id,session_id="analytics-"+hashlib.sha256(command.command_id.encode()).hexdigest()[:24],
            players=snapshot["players"],active_player_ids=snapshot["active_player_ids"],roster_revision=snapshot["roster_revision"],scenario=payload.scenario)
        return AnalyticsSubmission(session=session)
