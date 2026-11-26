"""Deterministic observed contact metrics with explicit time and coverage accounting."""
from core.analytics import AnalyticsSession, AnalyticsSettings, apply_corrections as corrected_session

CONTROLLED = {"control", "controlled_pass", "interception", "shot"}


def analyze(session: AnalyticsSession, settings=None):
    session = AnalyticsSession.model_validate(session.model_dump())
    settings = settings or AnalyticsSettings()
    players = {p.id: p for p in session.rosters[0].roster.players}
    teams = {team: dict(passes=0, interceptions=0, possession_seconds=0.0) for team in ("orange", "green")}
    individuals = {pid: dict(passes=0, received_passes=0, interceptions=0, possession_seconds=0.0) for pid in players}
    time = dict(in_play_seconds=0.0, paused_seconds=0.0, dead_ball_seconds=0.0, unknown_state_seconds=0.0,
                covered_in_play_seconds=0.0, unknown_possession_seconds=0.0)
    events, decisions = [], []
    ordered = sorted(session.contacts, key=lambda c: (c.occurred_seconds, c.touch_id))
    decision_ids = set()
    def decision(contact, reason):
        if contact.touch_id not in decision_ids:
            decisions.append(dict(touch_id=contact.touch_id, reason=reason)); decision_ids.add(contact.touch_id)
    for period in session.periods:
        duration = period.end_seconds - period.start_seconds
        key = "unknown_state_seconds" if period.state == "unknown" else f"{period.state}_seconds"
        time[key] += duration
        contacts = [c for c in ordered if period.start_seconds <= c.occurred_seconds < period.end_seconds]
        if period.state != "in_play":
            for contact in contacts: decision(contact, f"Excluded during {period.state}")
            continue
        if period.touch_coverage != "complete" or session.timing_quality == "unverified":
            for contact in contacts: decision(contact, "Coverage/timing unverified")
            continue
        # Proximity is not a contact and does not interrupt a proven contact chain.
        contacts = [c for c in contacts if c.kind != "proximity"]
        if any(c.uncertainty_seconds is None for c in contacts):
            for contact in contacts: decision(contact, "Contact clock bound missing; window remains unknown")
            continue
        if any(c.kind != "proximity" and c.uncertainty_seconds is not None and
               not period.start_seconds <= c.occurred_seconds < period.end_seconds and
               c.occurred_seconds-c.uncertainty_seconds < period.end_seconds and
               c.occurred_seconds+c.uncertainty_seconds >= period.start_seconds for c in ordered):
            for contact in contacts: decision(contact, "Adjacent contact uncertainty crosses play boundary")
            continue
        time["covered_in_play_seconds"] += duration
        ambiguous = set()
        cluster=[];cluster_end=-1
        for contact in contacts:
            if contact.occurred_seconds-contact.uncertainty_seconds <= cluster_end:
                ambiguous.update(c.touch_id for c in cluster);ambiguous.add(contact.touch_id)
                cluster.append(contact);cluster_end=max(cluster_end,contact.occurred_seconds+contact.uncertainty_seconds)
            else:
                cluster=[contact];cluster_end=contact.occurred_seconds+contact.uncertainty_seconds
        previous = None
        for index, contact in enumerate(contacts):
            epoch_index = max(i for i, e in enumerate(session.rosters) if e.start_seconds <= contact.occurred_seconds)
            epoch = session.rosters[epoch_index]
            roster_end = session.rosters[epoch_index+1].start_seconds if epoch_index+1 < len(session.rosters) else session.duration_seconds
            uncertainty = contact.uncertainty_seconds
            reason = None
            if uncertainty is None or uncertainty > settings.maximum_uncertainty_seconds: reason = "Unbounded/excessive contact uncertainty"
            elif contact.touch_id in ambiguous: reason = "Overlapping contact order"
            elif contact.occurred_seconds - uncertainty < max(period.start_seconds, epoch.start_seconds) or contact.occurred_seconds + uncertainty >= min(period.end_seconds, roster_end): reason = "Contact uncertainty crosses play/roster boundary"
            elif contact.certainty != "certain" or contact.kind not in CONTROLLED: reason = "Uncertain/incidental contact"
            elif contact.player_id is None or contact.player_id not in epoch.roster.active_player_ids: reason = "Unknown/inactive player identity"
            if reason:
                decision(contact, reason); previous = None; continue
            team = players[contact.player_id].team
            decision(contact, "Certain controlled contact")
            if previous is not None and (
                contact.occurred_seconds - previous.occurred_seconds <= settings.maximum_chain_gap_seconds and
                (contact.source_id, contact.boot_id, contact.play_epoch, contact.roster_revision) ==
                (previous.source_id, previous.boot_id, previous.play_epoch, previous.roster_revision)):
                prior_team = players[previous.player_id].team
                kind = None
                if team == prior_team and contact.player_id != previous.player_id and previous.kind == "controlled_pass" and contact.kind != "interception":
                    kind = "pass"
                    teams[team]["passes"] += 1; individuals[previous.player_id]["passes"] += 1; individuals[contact.player_id]["received_passes"] += 1
                elif team != prior_team and contact.kind == "interception":
                    kind = "interception"
                    teams[team]["interceptions"] += 1; individuals[contact.player_id]["interceptions"] += 1
                if kind:
                    events.append(dict(kind=kind, team=team, from_player_id=previous.player_id, to_player_id=contact.player_id,
                        previous_touch_id=previous.touch_id, touch_id=contact.touch_id, occurred_seconds=contact.occurred_seconds))
            start = contact.occurred_seconds + uncertainty
            end = min(period.end_seconds, roster_end, contact.occurred_seconds + settings.possession_hold_seconds)
            if index + 1 < len(contacts):
                following = contacts[index+1]
                end = min(end, following.occurred_seconds - following.uncertainty_seconds if following.uncertainty_seconds is not None else period.start_seconds)
            seconds = max(0.0, end-start)
            teams[team]["possession_seconds"] += seconds
            individuals[contact.player_id]["possession_seconds"] += seconds
            previous = contact
    for contact in ordered:
        if contact.kind == "proximity": decision(contact, "Proximity is not observed contact")
    known = sum(team["possession_seconds"] for team in teams.values())
    time["unknown_possession_seconds"] = max(0.0, time["in_play_seconds"] - known)
    status = "unavailable" if not time["covered_in_play_seconds"] else "partial" if time["covered_in_play_seconds"] < time["in_play_seconds"] or any(d["reason"] not in ("Certain controlled contact", "Proximity is not observed contact") and not d["reason"].startswith("Excluded") for d in decisions) else "available"
    for team in teams.values():
        team["possession_percent_of_in_play"] = 100 * team["possession_seconds"] / time["in_play_seconds"] if time["in_play_seconds"] else None
    time["unknown_possession_percent_of_in_play"] = 100 * time["unknown_possession_seconds"] / time["in_play_seconds"] if time["in_play_seconds"] else None
    return dict(schema_version=1, session_id=session.session_id, match_id=session.match_id, evidence=session.evidence,
        scope="generated_example_window" if session.evidence == "synthetic" else "observed_session_window",
        metric_status=status, settings=settings.model_dump(mode="json"), time_accounting=time,
        teams=teams, players=individuals, events=events, touch_decisions=decisions,
        field_qualified=False, automatic_write_allowed=False,
        unavailable_metrics=["distance", "heatmaps", "shots", "shots_on_target"],
        limitations=["Normalized contacts are supplied, not detected from pixels", "Possession is a bounded last-control estimate with unknown time",
                     "No full-pitch or cross-camera identity tracking is established", "Field metric gates remain pending"])
