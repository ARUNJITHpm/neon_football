"""Aggregate injected team/bib observations inside one track/boot/roster epoch."""
from core.attribution import AttributionSettings, AttributionRoster, IdentityDecision


class IdentityResolver:
    def __init__(self, roster: AttributionRoster, settings: AttributionSettings):
        self.roster, self.settings = roster, settings
        self.players = {(p.team, p.bib): p.id for p in roster.players if p.id in roster.active_player_ids}

    def resolve(self, touch, readings):
        if touch.track_id is None:
            return IdentityDecision(reason="No observed player track")
        relevant = sorted((r for r in readings if
            (r.camera_id, r.boot_id, r.track_id) == (touch.camera_id, touch.boot_id, touch.track_id) and
            touch.occurred_seconds - self.settings.identity_window_seconds <= r.occurred_seconds <= touch.occurred_seconds),
            key=lambda r: (r.occurred_seconds, r.frame_sequence, r.event_id))
        ids = [r.event_id for r in relevant]
        if not relevant:
            return IdentityDecision(reason="No fresh identity observations", reading_ids=ids)
        if relevant[-1].quality != "clear" or relevant[-1].team is None or relevant[-1].bib is None:
            return IdentityDecision(reason="Latest identity is uncertain or occluded", reading_ids=ids)
        clear = [r for r in relevant if r.quality == "clear" and r.team is not None and r.bib is not None]
        pairs = {(r.team, r.bib) for r in clear}
        if len(pairs) != 1:
            return IdentityDecision(reason="Identity switch/conflicting observations", reading_ids=ids)
        if len(clear) < self.settings.minimum_identity_reads:
            return IdentityDecision(reason="Insufficient distinct observed frames", reading_ids=ids)
        player_id = self.players.get(next(iter(pairs)))
        if player_id is None:
            return IdentityDecision(reason="Observed team/bib is not active in this roster", reading_ids=ids)
        return IdentityDecision(player_id=player_id, reason="Consistent observed team/bib support", reading_ids=ids)
