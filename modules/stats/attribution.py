"""Conservative temporal touch rules with explicit unknowns and review-only output."""
import hashlib

from core.attribution import AttributionSequence, AttributionSettings, AttributionSuggestion
from .identity import IdentityResolver


def suggest(sequence: AttributionSequence, settings=None):
    sequence = AttributionSequence.model_validate(sequence.model_dump())
    settings = settings or AttributionSettings()
    goal, roster = sequence.goal, sequence.roster
    identifier = hashlib.sha256((sequence.model_dump_json() + settings.model_dump_json()).encode()).hexdigest()
    result = AttributionSuggestion(suggestion_id=f"attribution:{identifier}", goal_id=goal.goal_id, match_id=goal.match_id,
        roster_revision=roster.revision, scoring_team=goal.scoring_team, evidence=goal.evidence,
        rule_version=settings.rule_version, reasons=["Conservative prototype; operator approval required"])
    if goal.touch_coverage != "complete":
        result.reasons.append("Touch coverage is partial or unknown; no full-pitch assumption")
        return result
    if goal.timing_quality == "unverified" or goal.uncertainty_seconds is None or goal.uncertainty_seconds > settings.max_uncertainty_seconds:
        result.reasons.append("Goal timing is unverified or too uncertain")
        return result
    contacts = sorted((t for t in sequence.touches if
        goal.occurred_seconds-settings.touch_lookback_seconds <= t.occurred_seconds <= goal.occurred_seconds and t.kind != "proximity"),
        key=lambda t: (t.occurred_seconds, t.event_id))
    if not contacts:
        result.reasons.append("No observed contact; proximity cannot identify a scorer")
        return result
    latest = contacts[-1]
    if latest.uncertainty_seconds is None or latest.occurred_seconds + latest.uncertainty_seconds >= goal.occurred_seconds - goal.uncertainty_seconds:
        result.reasons.append("Last observed contact overlaps crossing timing")
        return result
    # Overlapping uncertainty intervals do not establish last-touch order.
    for first, second in zip(contacts, contacts[1:]):
        if first.uncertainty_seconds is None or second.uncertainty_seconds is None or first.occurred_seconds + first.uncertainty_seconds >= second.occurred_seconds - second.uncertainty_seconds:
            result.reasons.append("Contact order is temporally ambiguous")
            return result
    resolver = IdentityResolver(roster, settings)
    players = {p.id: p for p in roster.players}
    for touch in contacts:
        if touch.kind != "frame_rebound":
            result.identities[touch.event_id] = resolver.resolve(touch, sequence.readings)
    def certain(touch):
        return touch.certainty == "certain" and touch.uncertainty_seconds is not None and touch.uncertainty_seconds <= settings.max_uncertainty_seconds and touch.kind != "unknown"
    last = len(contacts)-1
    while last >= 0 and contacts[last].kind in ("frame_rebound", "deflection"):
        touch = contacts[last]
        if not certain(touch) or (touch.kind == "deflection" and result.identities[touch.event_id].player_id is None):
            result.reasons.append("Uncertain deflection/rebound; scorer and own-goal outcome remain unknown")
            return result
        result.reasons.append("Certain incidental deflection/rebound preserves prior intentional touch")
        last -= 1
    if last < 0 or not certain(contacts[last]):
        result.reasons.append("No certain intentional last contact")
        return result
    final = contacts[last]
    # The final contact must precede the crossing by non-overlapping intervals.
    if final.occurred_seconds + final.uncertainty_seconds >= goal.occurred_seconds - goal.uncertainty_seconds:
        result.reasons.append("Last contact overlaps goal timing")
        return result
    identity = result.identities[final.event_id]
    if identity.player_id is None:
        result.reasons.append(identity.reason)
        return result
    result.scorer_id = identity.player_id
    result.own_goal = players[identity.player_id].team != goal.scoring_team
    result.assist_status = "none"
    if result.own_goal:
        result.reasons.append("Certain opposing intentional last touch: possible own goal; no assist")
        return result
    result.reasons.append("Last certain scoring-team contact supplies the scorer suggestion")
    for preceding in reversed(contacts[:last]):
        if preceding.kind in ("frame_rebound", "deflection", "unknown") or not certain(preceding):
            result.assist_status = "unknown"
            result.reasons.append("Uncertain/incidental contact interrupts assist evidence")
            break
        previous = result.identities[preceding.event_id].player_id
        if previous is None:
            result.assist_status = "unknown"
            result.reasons.append("Preceding player's identity is unknown")
            break
        if players[previous].team != goal.scoring_team:
            result.reasons.append("Opponent controlled contact breaks the assist chain")
            break
        if previous == result.scorer_id:
            continue
        if preceding.kind in ("controlled_pass", "control"):
            result.assist_id, result.assist_status = previous, "suggested"
            result.reasons.append("Preceding controlled teammate contact supplies possible assist")
        else:
            result.assist_status = "unknown"
            result.reasons.append("Prior teammate contact is not a controlled assist cue")
        break
    return result
