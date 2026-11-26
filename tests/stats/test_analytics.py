import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.analytics import AnalyticsSession, AnalyticsDataset, AnalyticsSubmission, AnalyticsSettings
from modules.stats.analytics import analyze, corrected_session
from tools.build_analytics_fixture import build, cases
from tools.analytics_replay import replay

FIXTURES=Path(__file__).parent/"analytics-fixtures"


@pytest.mark.parametrize("name", list(cases()))
def test_reference_events_and_time_conservation(name):
    session,reference=cases()[name]
    before=session.model_dump()
    result=analyze(session)
    assert sum(t["passes"] for t in result["teams"].values())==reference.passes
    assert sum(t["interceptions"] for t in result["teams"].values())==reference.interceptions
    for team in ("orange","green"):
        assert result["teams"][team]["possession_seconds"]==pytest.approx(reference.possession_seconds[team])
        assert sum(p["passes"] for pid,p in result["players"].items() if next(x for x in session.rosters[0].roster.players if x.id==pid).team==team)==result["teams"][team]["passes"]
    time=result["time_accounting"]
    assert time["unknown_possession_seconds"]==pytest.approx(reference.possession_seconds["unknown"])
    assert sum(time[k] for k in ("in_play_seconds","paused_seconds","dead_ball_seconds","unknown_state_seconds"))==pytest.approx(session.duration_seconds)
    assert sum(t["possession_seconds"] for t in result["teams"].values())+time["unknown_possession_seconds"]==pytest.approx(time["in_play_seconds"])
    expected={(e.kind,e.previous_touch_id,e.touch_id,e.team,e.from_player_id,e.to_player_id) for e in reference.events}
    actual={tuple(e[k] for k in ("kind","previous_touch_id","touch_id","team","from_player_id","to_player_id")) for e in result["events"]}
    assert actual==expected
    assert session.model_dump()==before and result==analyze(session)
    assert not result["field_qualified"] and not result["automatic_write_allowed"]


def test_possession_uses_all_in_play_as_denominator_not_only_known_time():
    session,_=cases()["gaps"];result=analyze(session)
    assert result["metric_status"]=="partial"
    assert result["teams"]["green"]["possession_percent_of_in_play"]==pytest.approx(100/3)
    assert result["time_accounting"]["unknown_possession_percent_of_in_play"]==50
    session,_=cases()["no_play"];result=analyze(session)
    assert result["metric_status"]=="unavailable"
    assert result["teams"]["green"]["possession_percent_of_in_play"] is None


def test_uncertainty_is_unknown_time_and_long_gap_expires():
    session,_=cases()["passing"]
    for contact in session.contacts:contact.uncertainty_seconds=.005
    result=analyze(session)
    assert result["teams"]["green"]["possession_seconds"]==pytest.approx(7.96)
    assert result["teams"]["orange"]["possession_seconds"]==pytest.approx(2.985)
    assert result["time_accounting"]["unknown_possession_seconds"]==pytest.approx(1.055)
    result=analyze(session,AnalyticsSettings(possession_hold_seconds=1))
    assert sum(t["possession_seconds"] for t in result["teams"].values())==pytest.approx(5.97)


def test_missing_clock_bound_and_nested_overlaps_never_guess():
    session,_=cases()["passing"];session.contacts[2].uncertainty_seconds=None
    result=analyze(session)
    assert result["time_accounting"]["unknown_possession_seconds"]==12
    assert result["events"]==[] and result["metric_status"]=="unavailable"
    session,_=cases()["passing"]
    session.contacts[0].uncertainty_seconds=1
    session.contacts[1].occurred_seconds=1.1
    session.contacts[2].occurred_seconds=1.2
    result=analyze(session)
    assert not any(e["touch_id"] in {"touch-1","touch-2"} for e in result["events"])
    assert result["players"]["green-11"]["passes"]==0


def test_contact_bounds_from_pause_do_not_claim_pre_pause_possession():
    session,_=cases()["pauses"]
    paused=session.contacts[-1].model_copy(update=dict(touch_id="pause-contact",occurred_seconds=10.001,uncertainty_seconds=.01))
    session.contacts.append(paused)
    result=analyze(session)
    assert result["time_accounting"]["covered_in_play_seconds"]==9
    assert not any(e["touch_id"]=="touch-1" for e in result["events"])


@pytest.mark.parametrize("damage", ["period_gap","period_overlap","roster_epoch","roster_revision","duplicate","outside","unknown_player","nonfinite","venue_clock"])
def test_contract_rejects_unsafe_time_identity_and_provenance(damage):
    session,_=cases()["passing"]
    if damage=="period_gap":session.periods[0].start_seconds=1
    if damage=="period_overlap":session.periods.append(session.periods[0])
    if damage=="roster_epoch":session.rosters[0].start_seconds=1
    if damage=="roster_revision":session.contacts[0].roster_revision=1
    if damage=="duplicate":session.contacts[1].touch_id=session.contacts[0].touch_id
    if damage=="outside":session.contacts[-1].occurred_seconds=12
    if damage=="unknown_player":session.contacts[0].player_id="not-registered"
    if damage=="nonfinite":session.contacts[0].occurred_seconds=float("nan")
    if damage=="venue_clock":session.evidence="venue"
    with pytest.raises(ValidationError):AnalyticsSession.model_validate(session.model_dump())


def test_inactive_bibs_do_not_gain_possession_and_epochs_break_chains():
    session,_=cases()["passing"];session.contacts[1].player_id="green-15"
    result=analyze(session)
    assert result["players"]["green-15"]["possession_seconds"]==0
    assert result["teams"]["green"]["passes"]==1
    session,_=cases()["passing"];session.contacts[1].play_epoch=1
    assert analyze(session)["teams"]["green"]["passes"]==1


def test_corrections_recompute_and_restore_without_mutating_source():
    session,_=cases()["passing"];original=session.model_dump()
    change=dict(session_id=session.session_id,touch_id="touch-1",player_id="green-7",kind="control",certainty="certain",void=False)
    corrections=[dict(change=change,revision=1)]
    assert analyze(corrected_session(session,corrections))["teams"]["green"]["passes"]==1
    change2={**change,"player_id":"green-11"};corrections.append(dict(change=change2,revision=2))
    assert analyze(corrected_session(session,corrections))["teams"]["green"]["passes"]==2
    corrections.append(dict(change={**change2,"void":True},revision=3))
    assert len(corrected_session(session,corrections).contacts)==5
    assert session.model_dump()==original
    with pytest.raises(ValueError):corrected_session(session,[dict(change={**change,"touch_id":"missing"},revision=1)])


def test_replay_hash_split_capacity_and_metric_reference_guards(tmp_path):
    build(tmp_path/"generated")
    assert (tmp_path/"generated/dataset.json").read_bytes()==(FIXTURES/"dataset.json").read_bytes()
    result=replay(FIXTURES/"dataset.json")
    assert result==replay(FIXTURES/"dataset.json")
    assert result["windows"]==10
    assert result["event_totals"]=={"pass":dict(matched=7,false=0,missed=0),"interception":dict(matched=4,false=0,missed=0)}
    assert set(result["possession_mean_absolute_error_seconds"].values())=={0}
    assert not result["field_qualified"] and not result["score_database_opened"]
    assert {g["state"] for g in result["field_gates"]}=={"pending"}
    with pytest.raises(ValueError,match="Blind-test"):replay(FIXTURES/"dataset.json","blind_test")
    assert replay(FIXTURES/"dataset.json","blind_test",True)["windows"]==1
    with pytest.raises(ValueError,match="capacity"):replay(FIXTURES/"dataset.json",max_contacts=1)
    (tmp_path/"generated/pauses.json").write_text("{}")
    with pytest.raises(ValueError,match="checksum"):replay(tmp_path/"generated/dataset.json")


@pytest.mark.parametrize("damage", ["match","group","hash","path","venue_labels"])
def test_dataset_isolation_and_independent_field_truth(damage):
    data=json.loads((FIXTURES/"dataset.json").read_text())
    a,b=data["sessions"][:2]
    if damage=="match":b["match_id"]=a["match_id"]
    if damage=="group":b["source_group_id"]=a["source_group_id"]
    if damage=="hash":b["sha256"]=a["sha256"]
    if damage=="path":b["path"]="../escape.json"
    if damage=="venue_labels":data["evidence"]="venue"
    with pytest.raises(ValidationError):AnalyticsDataset.model_validate(data)


def test_live_submission_refuses_venue_evidence():
    session,_=cases()["passing"];session.evidence="venue";session.timing_quality="measured"
    with pytest.raises(ValidationError,match="generated"):AnalyticsSubmission(session=session)
