from copy import deepcopy

import pytest
from pydantic import ValidationError

from core.fusion import FusionCommand, FusionSettings
from core.ports import DomainError
from conftest import command, engine, ingest, sensor, settings, vision


def first(e):
    return next(iter(e.candidates.values()))


def test_causal_shadow_decision_and_no_official_mutation(live):
    ingest(live, vision())
    ingest(live, sensor())
    assert first(live).status == "COLLECTING"
    live.advance(1.319)
    assert first(live).status == "COLLECTING"
    output = live.advance(1.32)
    assert first(live).status == "CONFIRMED" and first(live).confirmation == "shadow_rule"
    assert output["shadow_score"] == {"orange":0,"green":1}
    assert not output["official_score_mutated"] and output["restart_required"]
    assert all(not c["automatic_score_mutation_allowed"] for c in output["candidates"])


@pytest.mark.parametrize("quality", ["net_motion_only", "depth_ambiguous", "predicted_crossing", "boundary_uncertain"])
def test_weak_crossing_with_good_sensor_always_review(live, quality):
    ingest(live, vision(quality=quality))
    ingest(live, sensor())
    live.advance(1.4)
    assert first(live).status == "PENDING_REVIEW"
    live.advance(20)
    assert first(live).status == "UNRESOLVED"
    assert sum(live.snapshot()["shadow_score"].values()) == 0


@pytest.mark.parametrize("classification,flags", [("unknown", []), ("slow_impact", []), ("net_impact", ["saturated"])])
def test_sensor_quality_cannot_veto_crossing_or_confirm(live, classification, flags):
    ingest(live, vision())
    ingest(live, sensor(classification=classification, flags=flags))
    live.advance(1.4)
    c = first(live)
    assert c.status == "PENDING_REVIEW"
    command(live,"confirm",1.4,c.candidate_id)
    assert c.status == "CONFIRMED" and c.confirmation == "operator"


def test_post_and_in_frame_or_mixed_can_corroborate():
    for kind in ("frame_impact", "mixed_impact"):
        e=engine(); command(e,"start")
        ingest(e,vision()); ingest(e,sensor(classification=kind)); e.advance(1.4)
        assert first(e).confirmation == "shadow_rule"


def test_partial_crossing_player_contact_unmapped_and_uncertain(live):
    ingest(live, vision(quality="boundary_uncertain"))
    ingest(live, sensor(classification="slow_impact"))
    live.advance(1.4)
    assert first(live).status == "PENDING_REVIEW"
    command(live,"reject",1.4,first(live).candidate_id)
    ingest(live,sensor("unmapped",2,occurred_seconds=None,timing_uncertainty_seconds=None))
    live.advance(2.5)
    assert list(live.candidates.values())[-1].status == "PENDING_REVIEW"
    assert list(live.candidates.values())[-1].occurred_seconds is None


def test_wrong_end_and_clock_and_model_provenance(live):
    assert not ingest(live,vision(model_version="wrong"))["accepted"]
    assert not ingest(live,sensor(host_clock_domain="other"))["accepted"]
    assert not ingest(live,vision("v2"), now=1.13, match_id="old")["accepted"]
    assert not ingest(live,vision("v3",evidence="venue"), now=1.13)["accepted"]
    assert len(live.candidates)==0


def test_occurrence_window_not_receipt_similarity(live):
    ingest(live,vision())
    # Receipt almost identical but occurrence outside correlation window.
    ingest(live,sensor(t=.7,emitted_seconds=1.13))
    live.advance(1.5)
    assert len(live.candidates)==2
    assert all(c.status=="PENDING_REVIEW" for c in live.candidates.values())


def test_uncertainty_interval_boundary_and_unknown_bounds():
    e=engine(); command(e,"start")
    ingest(e,vision(timing_uncertainty_seconds=.02))
    ingest(e,sensor(t=1.239,timing_uncertainty_seconds=.02,emitted_seconds=1.3))
    e.advance(1.4)
    assert first(e).confirmation=="shadow_rule"
    e=engine(); command(e,"start")
    ingest(e,vision(timing_uncertainty_seconds=.021)); ingest(e,sensor()); e.advance(1.5)
    assert all(c.status=="PENDING_REVIEW" for c in e.candidates.values())


def test_duplicates_terminal_repeat_and_collision(live):
    v=vision(); result=ingest(live,v)
    assert ingest(live,v)==result
    with pytest.raises(DomainError,match="different content"):
        ingest(live,vision(quality="net_motion_only"))
    ingest(live,sensor()); live.advance(1.4)
    ingest(live,vision("repeat",1.4))
    assert len(live.candidates)==1 and first(live).occurred_seconds==1
    assert sum(live.snapshot()["shadow_score"].values())==1
    assert live.events[-1]["details"]["late"]


def test_late_evidence_is_logged_never_promotes_review(live):
    ingest(live,vision()); live.advance(1.32)
    ingest(live,sensor(emitted_seconds=1.34))
    assert first(live).status=="PENDING_REVIEW"
    live.advance(1.4)
    assert first(live).status=="PENDING_REVIEW"
    assert live.events[-1]["details"]["late"]
    assert not ingest(live,sensor("old",t=.5,emitted_seconds=1.5))["accepted"]


def test_independent_ends_and_two_nearby_incidents_ambiguous_sensor(live):
    ingest(live,vision("v1",track="one"))
    ingest(live,vision("v2",t=1.05,track="two"))
    ingest(live,sensor(t=1.07))
    assert len(live.candidates)==3
    assert list(live.candidates.values())[-1].reasons==["ambiguous_incident_association"]
    ingest(live,vision("v3",t=1.1,end="goal_b"), now=1.2)
    assert len(live.candidates)==4
    live.advance(1.5)
    assert all(c.status!="CONFIRMED" for c in live.candidates.values())


def test_second_track_retroactively_makes_attached_impact_ambiguous(live):
    ingest(live,vision())
    ingest(live,sensor())
    ingest(live,vision("other",t=1.14,track="different"))
    live.advance(1.5)
    assert len(live.candidates)==2
    assert all(c.status=="PENDING_REVIEW" for c in live.candidates.values())
    assert "impact_could_support_multiple_incidents" in first(live).reasons


def test_sensor_first_and_net_oscillation_dedup(live):
    ingest(live,sensor(t=.95))
    ingest(live,vision(emitted_seconds=1.1))
    ingest(live,vision("net",1.12,quality="net_motion_only",track=None))
    live.advance(1.5)
    assert len(live.candidates)==1 and first(live).occurred_seconds==1
    assert first(live).confirmation=="shadow_rule"


def test_restart_gating_quick_restart_and_old_evidence(live):
    ingest(live,vision()); ingest(live,sensor()); live.advance(1.4)
    ingest(live,vision("dead-ball",1.5,track="new"))
    assert list(live.candidates.values())[-1].status=="UNRESOLVED"
    epoch=live.play_epoch
    command(live,"restart",1.6)
    assert not ingest(live,vision("old-epoch",1.65),play_epoch=epoch)["accepted"]
    assert not ingest(live,vision("old-time",1.59),now=1.7)["accepted"]
    ingest(live,vision("quick",1.8,track="next"))
    ingest(live,sensor("next-impact",1.81)); live.advance(2.2)
    assert live.snapshot()["shadow_score"]["green"]==2


def test_pause_end_swap_and_stale_command(live):
    ingest(live,vision()); live.advance(1.4)
    c=first(live)
    command(live,"pause",1.4)
    assert c.status=="UNRESOLVED"
    ingest(live,vision("paused",1.5))
    assert list(live.candidates.values())[-1].reasons==["match_not_live"]
    command(live,"swap_ends",1.6); command(live,"resume",1.7)
    ingest(live,vision("new-side",2)); ingest(live,sensor("new-sensor",2.01)); live.advance(2.4)
    assert live.snapshot()["shadow_score"]["orange"]==1
    with pytest.raises(DomainError):
        command(live,"confirm",2.4,c.candidate_id)
    command(live,"end",2.4)
    ingest(live,vision("ended",2.5))
    assert list(live.candidates.values())[-1].status=="UNRESOLVED"


def test_commands_idempotency_revision_and_append_correction(live):
    ingest(live,vision()); live.advance(1.4)
    c=first(live)
    cmd=FusionCommand(command_id="confirm-once",match_id="match",expected_revision=live.revision,
        action="confirm",candidate_id=c.candidate_id,actor="operator")
    result=live.command(cmd,1.4)
    assert live.command(cmd,1.5)==result
    assert sum(live.snapshot()["shadow_score"].values())==1
    frozen=deepcopy(live.events)
    command(live,"undo",1.5,c.candidate_id)
    assert live.events[:len(frozen)]==frozen and c.status=="CONFIRMED" and c.corrected
    assert sum(live.snapshot()["shadow_score"].values())==0
    with pytest.raises(DomainError):
        command(live,"undo",1.5,c.candidate_id)
    with pytest.raises(DomainError,match="reused"):
        live.command(cmd.model_copy(update={"actor":"different"}),1.5)
    with pytest.raises(DomainError,match="Stale"):
        live.command(cmd.model_copy(update={"command_id":"stale"}),1.5)


def test_deadline_tie_rejects_stale_operator_and_future_evidence(live):
    ingest(live,vision()); live.advance(1.32)
    c=first(live)
    cmd=FusionCommand(command_id="timeout",match_id="match",expected_revision=live.revision,
        action="confirm",candidate_id=c.candidate_id,actor="operator")
    with pytest.raises(DomainError,match="Stale"):
        live.command(cmd,c.review_until_seconds)
    assert c.status=="UNRESOLVED"
    assert not ingest(live,vision("future",t=20),now=19)["accepted"]


def test_capacity_settings_and_detached_snapshot(live):
    config=settings().model_dump(); config["collection_seconds"]=.1
    with pytest.raises(ValidationError):
        FusionSettings(**config)
    config=settings(); config.max_candidates=1
    e=engine(); e.settings=config; command(e,"start")
    ingest(e,vision()); before=e.snapshot()
    with pytest.raises(ValueError,match="capacity"):
        ingest(e,sensor(end="goal_b"))
    assert e.snapshot()==before
    before["goal_mapping"]["goal_a"]="green"
    assert e.mapping["goal_a"]=="orange"
    with pytest.raises(ValueError,match="monotonic"):
        e.advance(0)


def test_evidence_must_still_be_fresh_at_decision(live):
    ingest(live,vision(),now=1.4)
    ingest(live,sensor(),now=1.41)
    live.advance(1.7)
    assert first(live).status=="PENDING_REVIEW"
    assert "reliable_observed_whole_ball_crossing_missing" in first(live).reasons


def test_record_and_event_identity_bounds(live):
    with pytest.raises(ValidationError,match="64 KiB"):
        ingest(live,vision(reasons=["x"*65536]))
    live.match_id="m"*128
    command(live,"pause")
    assert len(live.events[-1]["event_id"]) <= 128
