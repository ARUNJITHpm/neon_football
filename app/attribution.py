"""Compose generated identity/touch evidence for a committed goal. No image recognition."""
import hashlib

from core.attribution import AttributionGoal, AttributionRoster, AttributionSequence, AttributionSubmission, IdentityReading, TouchObservation
from core.schemas import DemoAttribution
from core.ports import DomainError
from modules.stats.attribution import suggest


def dummy_sequence(*, match_id, goal_id, players, active_player_ids, roster_revision=0, scoring_team="green",
                   scenario="direct", session_id="dummy-attribution", goal_end="goal_a"):
    roster = AttributionRoster(match_id=match_id, revision=roster_revision, players=players, active_player_ids=active_player_ids)
    common = dict(match_id=match_id, session_id=session_id, roster_revision=roster_revision, evidence="synthetic")
    active = [p for p in roster.players if p.id in active_player_ids]
    attackers = [p for p in active if p.team == scoring_team]
    opponents = [p for p in active if p.team != scoring_team]
    readings, touches = [], []
    def touch(player, at, kind, *, certainty="certain", uncertain_id=False, switch=False):
        track = f"track-{len(touches)}"
        if player is not None:
            for index in range(3):
                readings.append(IdentityReading(**common, event_id=f"identity-{track}-{index}", camera_id="dummy-camera", boot_id="dummy-boot",
                    track_id=track, frame_sequence=index, occurred_seconds=at-.3+index*.1, team=player.team, bib=player.bib,
                    quality="uncertain" if uncertain_id else "clear"))
            if switch:
                other = next((p for p in active if p.id != player.id),None)
                readings[-1] = readings[-1].model_copy(update=dict(bib=other.bib if other else (player.bib+1)%100, team=other.team if other else player.team))
        touches.append(TouchObservation(**common, event_id=f"touch-{track}", occurred_seconds=at, uncertainty_seconds=.005,
            camera_id="dummy-camera", boot_id="dummy-boot", track_id=track if player else None, kind=kind, certainty=certainty))
    if scenario == "own_goal":
        touch(opponents[0] if opponents else None, 9, "control")
    else:
        if scenario == "assist" and len(attackers)>1:
            touch(attackers[1], 8, "controlled_pass")
        touch(attackers[0] if attackers else None, 9, "shot", certainty="uncertain" if scenario=="uncertain" else "certain", switch=scenario=="identity_switch")
        if scenario == "deflection":
            touch(opponents[0] if opponents else None, 9.5, "deflection")
    return AttributionSequence(goal=AttributionGoal(match_id=match_id, session_id=session_id, goal_id=goal_id,
        scoring_team=scoring_team, goal_end=goal_end, occurred_seconds=10, uncertainty_seconds=.005,
        timing_quality="synthetic_aligned", touch_coverage="complete", evidence="synthetic"),
        roster=roster, readings=readings, touches=touches, conditions=["generated_numeric_identity_and_touches", scenario])


class DummyAttribution:
    def prepare(self, match_id, command, snapshot):
        payload = DemoAttribution.model_validate(command.payload)
        goal = next((g for g in snapshot["goals"] if g["goal_id"]==payload.goal_id),None)
        if goal is None:
            raise DomainError("Goal not found",404)
        sequence = dummy_sequence(match_id=match_id, goal_id=goal["goal_id"], players=snapshot["players"],
            active_player_ids=goal.get("active_player_ids",[p["id"] for p in snapshot["players"]]),
            roster_revision=goal.get("roster_revision",0), scoring_team=goal["team"], scenario=payload.scenario,
            session_id="dummy-"+hashlib.sha256(command.command_id.encode()).hexdigest()[:24])
        return AttributionSubmission(suggestion=suggest(sequence), sequence=sequence)
