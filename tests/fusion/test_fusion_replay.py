"""Offline fusion challenge and guarded dataset regressions."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.fusion import FusionDataset, FusionReplayStep
from tools.build_fusion_fixture import build
from tools.fusion_replay import replay


ROOT=Path(__file__).resolve().parent/"fixtures"


def session(report,name):
    return next(s for s in report["sessions"] if s["session_id"]==f"fusion-{name}")


def test_fixed_challenge_replay_deterministic_and_expected_transitions():
    first,second=replay(ROOT/"dataset.json"),replay(ROOT/"dataset.json")
    assert json.dumps(first,sort_keys=True)==json.dumps(second,sort_keys=True)
    assert not first["official_score_mutated"] and not first["release_qualified"]
    assert len(first["sessions"])==19
    for name in ("observed","post-and-in","duplicates","side-change"):
        assert session(first,name)["counts"]["shadow_confirmations"]==1
    assert session(first,"quick-restart")["counts"]["shadow_confirmations"]==2
    for name in ("partial","player-net","occluded","late","nearby","early-impact-nearby","pause","review-expiry","unmapped"):
        assert session(first,name)["counts"]["shadow_confirmations"]==0
    assert session(first,"occluded")["counts"]["operator_confirmations"]==1
    assert session(first,"review-expiry")["counts"]["rejected_commands"]==1
    assert session(first,"correction")["snapshot"]["shadow_score"]==dict(orange=0,green=0)
    assert session(first,"stale-and-future")["counts"]["ignored_evidence"]==3
    assert first["counts"]["false_shadow"]==0
    assert all(not c["automatic_score_mutation_allowed"] for s in first["sessions"] for c in s["snapshot"]["candidates"])
    upstream=[s for s in first["sessions"] if s["session_id"] in ("sensor-validation","vision-validation")]
    assert len(upstream)==2 and all(s["counts"]["shadow_confirmations"]==0 for s in upstream)
    assert sum(len(s["snapshot"]["evidence"]) for s in upstream)==15


def test_replay_split_group_hash_and_capacity_guards(tmp_path):
    dataset=build(tmp_path,include_upstream=False)
    with pytest.raises(ValueError,match="Blind-test"):
        replay(tmp_path/"dataset.json","blind_test")
    assert replay(tmp_path/"dataset.json","blind_test",True)["counts"]["shadow_confirmations"]==0
    with pytest.raises(ValueError,match="capacity"):
        replay(tmp_path/"dataset.json",max_steps=2)
    data=dataset.model_dump(mode="json")
    data["sessions"][-1]["source_group_id"]=data["sessions"][0]["source_group_id"]
    with pytest.raises(ValidationError,match="leaks"):
        FusionDataset.model_validate(data)
    data=dataset.model_dump(mode="json")
    data["sessions"][-1]["steps"]["sha256"]=data["sessions"][0]["steps"]["sha256"]
    with pytest.raises(ValidationError,match="leaks"):
        FusionDataset.model_validate(data)
    target=tmp_path/dataset.sessions[0].steps.path
    target.write_text(target.read_text(encoding="utf-8")+"\n",encoding="utf-8")
    with pytest.raises(ValueError,match="checksum"):
        replay(tmp_path/"dataset.json")


def test_contract_layout_rejects_untyped_commands_and_unknown_fields():
    with pytest.raises(ValidationError):
        FusionReplayStep(kind="tick",at_seconds=1,action="confirm")
    with pytest.raises(ValidationError):
        FusionReplayStep(kind="command",at_seconds=1,action="confirm",command_id="c")
    with pytest.raises(ValidationError):
        FusionReplayStep(kind="tick",at_seconds=float("nan"))


def test_goal_engine_only_imports_core_or_own_module():
    import ast
    directory=Path(__file__).resolve().parents[2]/"modules/goal_engine"
    for path in directory.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            imported=[node.module] if isinstance(node,ast.ImportFrom) and node.level==0 else [n.name for n in node.names] if isinstance(node,ast.Import) else []
            assert not any(n and (n.startswith("app.") or n.startswith("modules.") and not n.startswith("modules.goal_engine")) for n in imported)
