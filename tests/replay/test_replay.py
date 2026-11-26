import hashlib
import json
import itertools
import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.dataset import Annotation, AnnotationSet, Asset, DatasetManifest, ReplayEvent
from modules.replay.evaluator import evaluate
from modules.replay.matching import match
from modules.replay.runner import replay
from modules.replay.statistics import poisson_rate, proportion
from tools.build_replay_fixture import build


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "dataset"
    manifest, annotations = build(root)
    return root, manifest, annotations


def test_identical_replay_bytes_virtual_clock_and_provenance(bundle):
    root, manifest, annotations = bundle
    first, second = replay(root / "dataset.json"), replay(root / "dataset.json")
    assert first.model_dump_json() == second.model_dump_json()
    assert first.final_virtual_seconds == 60
    assert first.trace[0]["virtual_seconds"] == 5.1
    assert len(first.decisions) == 9
    assert first.model_versions == {"synthetic-validation": "injected-no-detector-1"}
    assert first.manifest_sha256 == hashlib.sha256((root / "dataset.json").read_bytes()).hexdigest()
    assert len(first.input_fingerprint) == 64
    with pytest.raises(ValueError, match="capacity"):
        replay(root / "dataset.json", max_events=8)


def test_evaluator_penalizes_duplicates_wrong_ends_misses_and_operator_rescue(bundle):
    root, manifest, annotations = bundle
    report = evaluate(manifest, annotations, replay(root / "dataset.json"))
    counts = report["counts"]
    assert (counts["valid_goals"], counts["true_positives"], counts["false_positives"], counts["false_negatives"]) == (6, 2, 4, 4)
    assert counts["human_rescued_goals"] == 1
    assert counts["operator_confirmed"] == 1
    assert counts["unadjudicated_automatic"] == 1
    assert counts["shadow_automatic_decisions"] == 7
    assert counts["automatic_outside_active_window"] == 1
    assert counts["review_prompts"] == 2
    assert report["metrics"]["automatic_recall"]["value"] == pytest.approx(1/3)
    assert report["metrics"]["automatic_precision"]["value"] == pytest.approx(1/3)
    assert report["metrics"]["availability"]["value"] == pytest.approx(5/6)
    assert report["metrics"]["false_automatic_per_scheduled_hour"]["value"] == 240
    assert report["metrics"]["visible_latency_seconds"]["p95"] == pytest.approx(0.4)
    assert report["metrics"]["visible_latency_upper_bound_seconds"]["p95"] == pytest.approx(0.42)
    assert report["metrics"]["display_measurement_coverage"]["value"] == 0.5
    assert {e["type"] for e in report["errors"]} >= {"duplicate", "wrong_goal_end", "automatic_while_inactive", "missed_valid_goal", "unadjudicated_automatic"}
    assert not report["release_qualified"]
    assert report["conditions"]["challenge"]["true_positives"] == 2


def test_manual_rescue_cannot_improve_auto_recall_and_wrong_team_is_false(bundle):
    root, manifest, annotations = bundle
    original = replay(root / "dataset.json")
    manual = original.decisions[3].model_copy(update={"event_id": "manual-rescue", "sequence": 100,
        "occurred_seconds": 20, "delivered_seconds": 20.1, "outcome": "manual", "review_required": False})
    wrong_team = original.decisions[0].model_copy(update={"event_id": "wrong-team", "sequence": 101,
        "team": "green", "occurred_seconds": 20, "delivered_seconds": 20.1, "displayed_seconds": 20.4})
    report = evaluate(manifest, annotations, original.model_copy(update={"decisions": original.decisions+[manual, wrong_team]}))
    assert report["counts"]["true_positives"] == 2
    assert report["counts"]["false_negatives"] == 4
    assert report["counts"]["false_positives"] == 5
    assert report["counts"]["manual_goals"] == 1
    assert report["counts"]["human_rescued_goals"] == 2
    assert any(e["type"] == "wrong_team" for e in report["errors"])


def test_match_reassigns_nearby_events_and_has_stable_ties():
    def label(identifier, seconds):
        return Annotation(label_id=identifier, session_id="s", match_id="m", crossing_start_seconds=seconds,
            crossing_end_seconds=seconds, goal_end="goal_a", team="orange", validity="valid", visibility="clear",
            uncertainty_seconds=0, adjudicator="test")
    def prediction(identifier, seconds):
        return ReplayEvent(event_id=identifier, session_id="s", match_id="m", sequence=0, occurred_seconds=seconds,
            delivered_seconds=seconds, kind="decision", goal_end="goal_a", team="orange", outcome="automatic")
    labels, predictions = [label("a", 10), label("b", 10.8)], [prediction("a", 10.4), prediction("b", 10)]
    pairs = match(labels, predictions, .5)
    assert {(l.label_id, p.event_id) for l, p in pairs} == {("a", "b"), ("b", "a")}
    assert [(l.label_id, p.event_id) for l, p in pairs] == [(l.label_id, p.event_id) for l, p in match(labels[::-1], predictions[::-1], .5)]


def test_match_agrees_with_exhaustive_small_assignments():
    rng = random.Random(303)
    for _ in range(20):
        labels = [Annotation(label_id=f"l{n}", session_id="s", match_id="m", crossing_start_seconds=t,
            crossing_end_seconds=t, goal_end="goal_a", team="orange", validity="valid", visibility="clear",
            uncertainty_seconds=0, adjudicator="test") for n, t in enumerate(rng.choices([1, 1.3, 1.8, 2.2], k=4))]
        predictions = [ReplayEvent(event_id=f"p{n}", session_id="s", match_id="m", sequence=n,
            occurred_seconds=t, delivered_seconds=t, kind="decision", goal_end="goal_a", team="orange", outcome="automatic")
            for n, t in enumerate(rng.choices([1, 1.2, 1.5, 2], k=4))]
        optimum = (0, 0)
        for count in range(1, 5):
            for subset in itertools.combinations(labels, count):
                for ordering in itertools.permutations(predictions, count):
                    distances = [abs(l.crossing_seconds-p.occurred_seconds) for l, p in zip(subset, ordering)]
                    if all(d <= .5 for d in distances):
                        optimum = min(optimum, (-count, sum(round(d*1e6) for d in distances)))
        pairs = match(labels, predictions, .5)
        assert (-len(pairs), sum(round(abs(l.crossing_seconds-p.occurred_seconds)*1e6) for l, p in pairs)) == optimum


def test_tolerance_does_not_hide_late_display_and_interval_is_preserved(bundle):
    root, manifest, annotations = bundle
    original = replay(root / "dataset.json")
    late = original.decisions[0].model_copy(update={"displayed_seconds": 12.0})
    report = evaluate(manifest, annotations, original.model_copy(update={"decisions": [late]+original.decisions[1:]}))
    assert report["counts"]["true_positives"] == 2
    assert report["metrics"]["visible_latency_seconds"]["p95"] == 7
    label = annotations.labels[0]
    label.crossing_start_seconds, label.crossing_end_seconds = 4.8, 5.2
    report = evaluate(manifest, annotations, original)
    assert report["matches"][0]["crossing_uncertainty_seconds"] == pytest.approx(.21)


def test_empty_predictions_count_outage_goals_and_undefined_precision(bundle):
    root, manifest, annotations = bundle
    original = replay(root / "dataset.json")
    report = evaluate(manifest, annotations, original.model_copy(update={"decisions": []}))
    assert report["counts"]["false_negatives"] == 6
    assert report["metrics"]["automatic_recall"]["value"] == 0
    assert report["metrics"]["automatic_precision"]["value"] is None
    assert report["metrics"]["visible_latency_seconds"]["p95"] is None


def test_split_session_group_and_content_isolation(bundle):
    root, manifest, annotations = bundle
    value = manifest.model_dump()
    value["sessions"][1]["source_group_id"] = value["sessions"][0]["source_group_id"]
    with pytest.raises(ValidationError, match="leaks"):
        DatasetManifest.model_validate(value)
    value = manifest.model_dump()
    value["sessions"][1]["assets"][0]["sha256"] = value["sessions"][0]["assets"][0]["sha256"]
    with pytest.raises(ValidationError, match="leaks"):
        DatasetManifest.model_validate(value)
    value = manifest.model_dump()
    value["sessions"][1]["session_id"] = value["sessions"][0]["session_id"]
    with pytest.raises(ValidationError, match="unique"):
        DatasetManifest.model_validate(value)


def test_blind_split_needs_explicit_flag_and_matching_label_file(bundle):
    root, manifest, annotations = bundle
    with pytest.raises(ValueError, match="Blind-test"):
        replay(root / "dataset.json", split="blind_test")
    recorded = replay(root / "dataset.json", split="blind_test", allow_blind_test=True)
    with pytest.raises(ValueError):
        evaluate(manifest, annotations, recorded, allow_blind_test=True)
    blind = AnnotationSet.model_validate_json((root / "annotations-blind_test.json").read_text())
    assert evaluate(manifest, blind, recorded, allow_blind_test=True)["counts"]["valid_goals"] == 2


def test_tampered_assets_duplicate_sequences_and_path_escape(bundle):
    root, manifest, annotations = bundle
    path = root / "synthetic-validation.jsonl"
    path.write_text(path.read_text()+"\n")
    with pytest.raises(ValueError, match="checksum"):
        replay(root / "dataset.json")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
    rows[1]["sequence"] = rows[0]["sequence"]
    encoded = "".join(json.dumps(row)+"\n" for row in rows).encode()
    path.write_bytes(encoded)
    manifest.sessions[1].assets[0].sha256 = hashlib.sha256(encoded).hexdigest()
    (root / "dataset.json").write_text(manifest.model_dump_json())
    with pytest.raises(ValueError, match="duplicate"):
        replay(root / "dataset.json")
    for invalid in ("../private.mp4", "C:/private.mp4", "/private.mp4", "file:stream", "..\\private.mp4"):
        with pytest.raises(ValidationError):
            Asset(path=invalid, sha256="0"*64, kind="video")


def test_late_arrival_replay_order_keeps_original_occurrence(bundle):
    root, manifest, annotations = bundle
    path = root / "synthetic-validation.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0].update(delivered_seconds=8, displayed_seconds=8.4)
    encoded = "".join(json.dumps(row)+"\n" for row in reversed(rows)).encode()
    path.write_bytes(encoded)
    manifest.sessions[1].assets[0].sha256 = hashlib.sha256(encoded).hexdigest()
    (root / "dataset.json").write_text(manifest.model_dump_json())
    output = replay(root / "dataset.json")
    assert [row["event_id"] for row in output.trace[:2]] == ["duplicate-a", "true-a"]
    assert output.trace[1]["occurred_seconds"] == 5
    assert output.trace[1]["virtual_seconds"] == 8


def test_interval_methods_known_values_and_zero_exposure():
    assert proportion(0, 0)["value"] is None
    assert proportion(0, 10)["ci95"][1] == pytest.approx(.2775327998628892)
    assert proportion(10, 10)["ci95"][0] == pytest.approx(.7224672001371107)
    assert poisson_rate(0, 1)["ci95"][1] == pytest.approx(3.688879454113936)
    assert poisson_rate(1, 1)["ci95"] == pytest.approx([.02531780798429, 5.5716433909389])
    assert poisson_rate(1, 0)["value"] is None


def test_annotations_and_decisions_require_valid_boundaries_and_identity(bundle):
    root, manifest, annotations = bundle
    original = replay(root / "dataset.json")
    with pytest.raises(ValueError, match="duplicate"):
        evaluate(manifest, annotations, original.model_copy(update={"decisions": original.decisions+[original.decisions[0]]}))
    annotations.labels[0].crossing_end_seconds = 61
    with pytest.raises(ValueError, match="outside"):
        evaluate(manifest, annotations, original)
    with pytest.raises(ValidationError):
        ReplayEvent(event_id="test", session_id="s", match_id="m", sequence=0, occurred_seconds=3,
                    delivered_seconds=2, kind="decision", outcome="automatic", goal_end="goal_a", team="orange")
