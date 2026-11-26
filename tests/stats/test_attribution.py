import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.attribution import AttributionDataset, AttributionSequence, AttributionSubmission
from modules.stats.attribution import suggest
from tools.attribution_replay import replay
from tools.build_attribution_fixture import build, cases

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("case,scorer,assist,own", [
    ("direct", "green-7", None, False), ("assist", "green-7", "green-11", False),
    ("own_goal", "orange-9", None, True), ("deflection", "green-7", None, False),
    ("frame_rebound", "green-7", None, False), ("orange_goal", "orange-9", None, False),
    ("same_player_dribble", "green-7", "green-11", False),
    ("opponent_breaks_assist", "green-7", None, False), ("substituted_roster", "green-15", None, False),
])
def test_explicit_touch_rules(case, scorer, assist, own):
    sequence, _ = cases()[case]
    result = suggest(sequence)
    assert (result.scorer_id, result.assist_id, result.own_goal) == (scorer, assist, own)
    assert result.operator_review_required and not result.automatic_write_allowed
    assert result == suggest(sequence)
    AttributionSubmission(suggestion=result, sequence=sequence)


@pytest.mark.parametrize("case", ["uncertain", "identity_switch", "partial_coverage", "occluded", "few_reads",
    "stale_reads", "proximity_only", "no_contact", "ambiguous_order", "clock_unknown", "future_reads",
    "inactive_bib", "unknown_bib", "touch_uncertainty", "source_reset"])
def test_ambiguity_abstains_instead_of_guessing(case):
    sequence, _ = cases()[case]
    result = suggest(sequence)
    assert result.scorer_id is None and result.own_goal is None and result.assist_status == "unknown"
    assert len(result.reasons) > 1


def test_unknown_assist_does_not_hide_certain_scorer():
    sequence, _ = cases()["unclear_assist"]
    result = suggest(sequence)
    assert result.scorer_id == "green-7" and result.own_goal is False
    assert result.assist_id is None and result.assist_status == "unknown"


@pytest.mark.parametrize("damage", ["duplicate_frame", "reset", "roster", "provenance", "cross_match"])
def test_observation_epoch_and_duplicate_support_guards(damage):
    sequence, _ = cases()["direct"]
    if damage == "duplicate_frame": sequence.readings[1].frame_sequence = 0
    if damage == "reset": sequence.readings[2].frame_sequence = 0
    if damage == "roster": sequence.readings[0].roster_revision = 1
    if damage == "provenance": sequence.touches[0].evidence = "venue"
    if damage == "cross_match": sequence.readings[0].match_id = "another-match"
    with pytest.raises(ValidationError): AttributionSequence.model_validate(sequence.model_dump())


def test_cross_camera_and_unknown_deflections_are_not_handoffs():
    sequence, _ = cases()["direct"]
    sequence.touches[-1].camera_id = "other-camera"
    assert suggest(sequence).scorer_id is None
    sequence, _ = cases()["deflection"]
    sequence.touches[-1].certainty = "uncertain"
    assert suggest(sequence).own_goal is None
    sequence.touches[-1].certainty = "certain"
    sequence.readings[-1].quality = "occluded"
    assert suggest(sequence).scorer_id is None


def test_submission_rejects_inactive_and_inconsistent_output():
    sequence, _ = cases()["direct"]
    result = suggest(sequence)
    result.scorer_id = "green-15"
    with pytest.raises(ValidationError, match="active"): AttributionSubmission(suggestion=result, sequence=sequence)
    result.scorer_id = "orange-9"
    with pytest.raises(ValidationError, match="team"): AttributionSubmission(suggestion=result, sequence=sequence)


def test_replay_reproducible_with_abstention_and_separate_fields(tmp_path):
    build(tmp_path / "generated")
    assert (tmp_path / "generated/dataset.json").read_bytes() == (FIXTURES / "dataset.json").read_bytes()
    result = replay(FIXTURES / "dataset.json")
    assert result == replay(FIXTURES / "dataset.json")
    assert result["goals"] == 23
    assert result["fields"]["scorer"]["accuracy"]["numerator"] == 9
    assert result["fields"]["scorer"]["abstentions"] == 14
    assert result["fields"]["assist"]["abstentions"] == 15
    assert not result["field_accuracy_measured"] and not result["release_qualified"]
    assert not result["automatic_attribution_enabled"] and not result["official_score_mutated"]
    assert result["gate"]["state"] == "pending"
    with pytest.raises(ValueError, match="Blind-test"): replay(FIXTURES / "dataset.json", "blind_test")
    assert replay(FIXTURES / "dataset.json", "blind_test", True)["goals"] == 1
    with pytest.raises(ValueError, match="capacity"): replay(FIXTURES / "dataset.json", max_observations=1)
    (tmp_path / "generated/assist.json").write_text("{}")
    with pytest.raises(ValueError, match="checksum"): replay(tmp_path / "generated/dataset.json")


@pytest.mark.parametrize("damage", ["match", "source_group", "hash", "path", "venue_truth"])
def test_manifest_leakage_path_and_independent_truth(damage):
    data = json.loads((FIXTURES / "dataset.json").read_text())
    first, second = data["sessions"][:2]
    if damage == "match": second["match_id"] = first["match_id"]
    if damage == "source_group": second["source_group_id"] = first["source_group_id"]
    if damage == "hash": second["sha256"] = first["sha256"]
    if damage == "path": second["path"] = "../escape.json"
    if damage == "venue_truth": data["evidence"] = "venue"
    with pytest.raises(ValidationError): AttributionDataset.model_validate(data)
