import json
from pathlib import Path

import pytest

from core.dataset import Annotation, DatasetManifest
from core.vision import VisionCandidate
from tools.build_vision_fixture import build
from tools.vision_replay import candidate_metrics, run


def replay(root):
    return run(root/"dataset.json", root/"settings.json", root/"annotations.json")


def test_replay_repeatable_expected_errors_and_review_only(tmp_path):
    build(tmp_path)
    a, b = replay(tmp_path), replay(tmp_path)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["frame_count"] == 24 and len(a["candidates"]) == 7
    assert a["metrics"]["counts"] == dict(valid_references=6, candidates=7, true_positives=5,
                                          false_candidates=1, misses=1, unadjudicated=1)
    assert a["metrics"]["qualities"] == dict(observed_crossing=2, boundary_uncertain=2, predicted_crossing=1,
                                            depth_ambiguous=1, net_motion_only=1)
    assert not a["release_qualified"] and a["evidence"] == ["synthetic"]
    assert all(c["requires_review"] and not c["automatic_confirmation_allowed"] for c in a["candidates"])


def test_replay_hash_guard_blind_access_and_frame_cap(tmp_path):
    build(tmp_path)
    with pytest.raises(ValueError, match="Blind-test"):
        run(tmp_path/"dataset.json", tmp_path/"settings.json", tmp_path/"annotations.json", "blind_test")
    observations = tmp_path/"observations.jsonl"
    observations.write_text(observations.read_text()+"\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        replay(tmp_path)
    build(tmp_path)
    config = json.loads((tmp_path/"settings.json").read_text())
    config["max_frame_count"] = 3
    (tmp_path/"settings.json").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="capacity"):
        replay(tmp_path)


def test_vision_content_split_leakage_rejected(tmp_path):
    manifest = build(tmp_path).model_dump()
    second = json.loads(json.dumps(manifest["sessions"][0]))
    second.update(session_id="train", source_group_id="different", split="train")
    second["matches"][0]["match_id"] = "train-match"
    # Empty replay asset hash differs; vision observations are the shared leaked content.
    second["assets"][1]["sha256"] = "a"*64
    manifest["sessions"].append(second)
    with pytest.raises(ValueError, match="leaks"):
        DatasetManifest.model_validate(manifest)


def test_duplicate_and_wrong_end_candidates_and_unknown_labels(tmp_path):
    build(tmp_path)
    output = replay(tmp_path)
    first = VisionCandidate.model_validate(output["candidates"][0])
    label = Annotation.model_validate(json.loads((tmp_path/"annotations.json").read_text())["labels"][0])
    duplicate = first.model_copy(update={"event_id": "duplicate"})
    wrong = first.model_copy(update={"event_id": "wrong-end", "goal_end": "goal_b"})
    metrics = candidate_metrics([label], [first, duplicate, wrong], 3600)
    assert metrics["counts"]["true_positives"] == 1 and metrics["counts"]["false_candidates"] == 2
    with pytest.raises(ValueError, match="Duplicate"):
        candidate_metrics([label], [first, first], 3600)
