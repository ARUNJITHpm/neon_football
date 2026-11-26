"""Checksum/split-guarded offline fusion challenge replay; never writes scoreboard data."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from types import SimpleNamespace

if __package__ in (None, ""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from core.fusion import FusionCommand, FusionDataset, FusionReplayStep
from core.ports import DomainError
from modules.goal_engine.engine import GoalEngine
from modules.replay.dataset import asset_path, digest
from modules.replay.matching import match
from modules.replay.statistics import distribution, poisson_rate, proportion


def replay(path, split="validation", allow_blind_test=False, max_steps=100000):
    path = Path(path)
    if split == "blind_test" and not allow_blind_test:
        raise ValueError("Blind-test access requires explicit opt-in; public fixtures are not an untouched holdout")
    if split not in ("train", "validation", "blind_test") or not 1 <= max_steps <= 1000000:
        raise ValueError("Invalid split or step capacity")
    if path.stat().st_size > 16*1024*1024:
        raise ValueError("Manifest capacity reached")
    dataset = FusionDataset.model_validate_json(path.read_text(encoding="utf-8"))
    selected = [s for s in dataset.sessions if s.split == split]
    if not selected:
        raise ValueError("No sessions in selected split")
    sessions, total_steps, totals, latency, inputs = [], 0, Counter(), [], []
    for asset in dataset.provenance_assets:
        source=asset_path(path.parent,asset.path)
        if source.stat().st_size > 128*1024*1024 or digest(source)!=asset.sha256:
            raise ValueError("Upstream provenance checksum/capacity differs")
        inputs.append(dict(upstream=True, **asset.model_dump()))
    for session in selected:
        steps_path = asset_path(path.parent,session.steps.path)
        if steps_path.stat().st_size > 128*1024*1024:
            raise ValueError("Replay asset capacity reached")
        if digest(steps_path) != session.steps.sha256:
            raise ValueError("Replay asset checksum differs")
        inputs.append(dict(session_id=session.session_id, **session.steps.model_dump()))
        engine = GoalEngine(dataset.settings,session_id=session.session_id,match_id=session.match_id,
            clock_domain=session.clock_domain,evidence=session.evidence,goal_a_defending=session.goal_a_defending)
        trace, references, last = [], {}, 0.
        with steps_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                total_steps += 1
                if total_steps > max_steps or len(line) > 1000000:
                    raise ValueError("Replay step capacity reached")
                step = FusionReplayStep.model_validate_json(line)
                if step.at_seconds < last or step.at_seconds > session.duration_seconds:
                    raise ValueError("Step outside monotonic session timeline")
                last = step.at_seconds
                if step.kind == "evidence":
                    # Intentionally wrong match/epoch records are retained as ignored engine diagnostics.
                    result = engine.ingest(step.evidence,step.at_seconds)
                    references[step.evidence.observation.event_id] = result["candidate_id"]
                elif step.kind == "command":
                    engine.advance(step.at_seconds,snapshot=False)
                    target = references.get(step.candidate_evidence_id) if step.candidate_evidence_id else None
                    if step.candidate_evidence_id and target is None:
                        raise ValueError("Command references no accepted candidate")
                    cmd = FusionCommand(command_id=step.command_id,match_id=session.match_id,
                        expected_revision=engine.revision if step.expected_revision is None else step.expected_revision,
                        action=step.action,candidate_id=target,actor="fixture-operator")
                    try:
                        result = engine.command(cmd,step.at_seconds)
                    except DomainError as error:
                        result = dict(command_rejected=True,reason=error.message)
                else:
                    engine.advance(step.at_seconds,snapshot=False)
                    result = dict(tick=True)
                trace.append(dict(at_seconds=step.at_seconds,kind=step.kind,result=result))
        engine.advance(session.duration_seconds,snapshot=False)
        snapshot=engine.snapshot()
        decisions=[SimpleNamespace(event_id=c.candidate_id,goal_end=c.goal_end,team=c.team,
                    occurred_seconds=c.occurred_seconds,candidate=c) for c in engine.candidates.values()
                   if c.status=="CONFIRMED" and not c.corrected and c.confirmation=="shadow_rule"]
        valid=[SimpleNamespace(label_id=l.label_id,goal_end=l.goal_end,team=l.team,crossing_seconds=l.occurred_seconds)
               for l in session.labels if l.validity=="valid"]
        uncertain=[l for l in session.labels if l.validity=="uncertain"]
        compatible=lambda l,c:(l.goal_end,l.team)==(c.goal_end,c.team)
        pairs=match(valid,decisions,.5,compatible=compatible)
        matched={c.event_id for _,c in pairs}
        unknown=[c for c in decisions if c.event_id not in matched and any(compatible(l,c) and
            abs(l.occurred_seconds-c.occurred_seconds)<=.5 for l in uncertain)]
        latency.extend(c.candidate.confirmed_seconds-l.crossing_seconds for l,c in pairs)
        counts=dict(valid_references=len(valid),shadow_confirmations=len(decisions),matched_shadow=len(pairs),
            shadow_misses=len(valid)-len(pairs),false_shadow=len(decisions)-len(pairs)-len(unknown),
            unadjudicated_shadow=len(unknown),candidates=len(engine.candidates),
            operator_confirmations=sum(c.confirmation=="operator" and not c.corrected for c in engine.candidates.values()),
            ignored_evidence=sum(not r["result"]["accepted"] for r in engine.inputs.values()),
            rejected_commands=sum(bool(t["result"].get("command_rejected")) for t in trace))
        totals.update(counts)
        sessions.append(dict(session_id=session.session_id,counts=counts,snapshot=snapshot,trace=trace,
            matched_pairs=[dict(label_id=l.label_id,candidate_id=c.event_id) for l,c in pairs],
            missed_label_ids=[l.label_id for l in valid if l.label_id not in {p.label_id for p,_ in pairs}]))
    root=Path(__file__).resolve().parents[1]
    implementation=[Path(__file__),root/"core/fusion.py",root/"core/schemas.py",root/"core/vision.py",root/"core/sensors.py",
        root/"core/capture.py",root/"core/ports.py",root/"modules/storage/store.py",
        root/"modules/replay/matching.py",root/"modules/replay/statistics.py",root/"modules/replay/dataset.py",
        *sorted((root/"modules/goal_engine").glob("*.py"))]
    seconds=sum(s.duration_seconds for s in selected)
    return dict(schema_version=1,runner="fusion-shadow-v1",dataset_id=dataset.dataset_id,split=split,
        provenance=dict(manifest_sha256=digest(path),inputs=inputs,
            implementation={p.relative_to(root).as_posix():digest(p) for p in implementation}),
        counts=dict(totals),sessions=sessions,scheduled_seconds=seconds,matching_tolerance_seconds=.5,
        shadow_recall=proportion(totals["matched_shadow"],totals["valid_references"]),
        false_shadow_per_hour=poisson_rate(totals["false_shadow"],seconds/3600),
        virtual_decision_latency_seconds=distribution(latency),official_score_mutated=False,release_qualified=False,
        field_accuracy_measured=False,configuration=dataset.settings.model_dump(mode="json"),
        limitations=["Injected challenge evidence does not measure venue accuracy or physical synchronization",
            "Rule labels are not probabilities; shadow score is separate from the official scoreboard",
            "Occurrence/uncertainty window defaults are unmeasured; live integration and release remain pending",
            "Public synthetic split guards do not constitute independent blind evaluation"])


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest",type=Path)
    parser.add_argument("--split",choices=["train","validation","blind_test"],default="validation")
    parser.add_argument("--allow-blind-test",action="store_true")
    parser.add_argument("--max-steps",type=int,default=100000)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=replay(args.manifest,args.split,args.allow_blind_test,args.max_steps)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(f"Replayed {len(result['sessions'])} sessions; {result['counts']['shadow_confirmations']} shadow confirmations, official score unchanged")
