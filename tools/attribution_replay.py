"""Checksum/split-guarded identity/touch replay and separately adjudicated field summaries."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from core.attribution import AttributionDataset, AttributionSequence
from modules.stats.attribution import suggest
from modules.replay.dataset import asset_path, digest
from modules.replay.statistics import proportion


def field_summary(rows,field):
    known=lambda row: row["label"][f"{field}_known"]
    value=lambda row,side: row[side]["own_goal" if field=="own_goal" else f"{field}_id"]
    named=lambda row: value(row,"suggestion") is not None if field!="assist" else row["suggestion"]["assist_status"]!="unknown"
    predicted=[r for r in rows if named(r)]
    evaluated=[r for r in predicted if known(r)]
    correct=sum(value(r,"label")==value(r,"suggestion") for r in evaluated)
    return dict(goals=len(rows),reference_known=sum(known(r) for r in rows),suggested=len(predicted),evaluated=len(evaluated),
        errors=len(evaluated)-correct,abstentions=len(rows)-len(predicted),unadjudicated_suggestions=len(predicted)-len(evaluated),
        accuracy=proportion(correct,len(evaluated)),coverage=proportion(len(predicted),len(rows)))


def replay(path,split="validation",allow_blind_test=False,max_observations=100000):
    path=Path(path)
    if path.stat().st_size>16*1024*1024 or not 1<=max_observations<=1000000:
        raise ValueError("Attribution replay capacity exceeded")
    if split=="blind_test" and not allow_blind_test:
        raise ValueError("Blind-test access needs explicit opt-in; public dummy fixtures are not a real holdout")
    if split not in ("train","validation","blind_test"):
        raise ValueError("Invalid split")
    dataset=AttributionDataset.model_validate_json(path.read_text(encoding="utf-8"))
    selected=[s for s in dataset.sessions if s.split==split]
    if not selected:raise ValueError("No selected attribution sessions")
    rows,observations=[],0
    for session in selected:
        source=asset_path(path.parent,session.path)
        if source.stat().st_size>4*1024*1024 or digest(source)!=session.sha256:
            raise ValueError("Attribution asset checksum/capacity differs")
        sequence=AttributionSequence.model_validate_json(source.read_text(encoding="utf-8"))
        if (sequence.goal.session_id,sequence.goal.match_id,sequence.goal.goal_id,sequence.goal.evidence)!=(session.session_id,session.match_id,session.label.goal_id,dataset.evidence):
            raise ValueError("Attribution asset/manifest identity differs")
        observations+=len(sequence.readings)+len(sequence.touches)
        if observations>max_observations:raise ValueError("Attribution observation capacity exceeded")
        # Keep worst-case identity resolution work bounded as well as file/row counts.
        if len(sequence.readings)*len(sequence.touches)>1000000:raise ValueError("Attribution resolution-work capacity exceeded")
        suggestion=suggest(sequence,dataset.settings)
        rows.append(dict(session_id=session.session_id,match_id=session.match_id,goal_end=sequence.goal.goal_end,conditions=sequence.conditions,
            asset_sha256=session.sha256,label=session.label.model_dump(mode="json"),suggestion=suggestion.model_dump(mode="json")))
    groups=defaultdict(list)
    for row in rows:
        groups[f"end:{row['goal_end']}"].append(row)
        for condition in row["conditions"]:groups[f"condition:{condition}"].append(row)
    root=Path(__file__).resolve().parents[1]
    sources=[Path(__file__),root/"core/attribution.py",root/"core/schemas.py",root/"modules/replay/statistics.py",
        root/"modules/replay/dataset.py",*sorted((root/"modules/stats").glob("*.py"))]
    return dict(schema_version=1,runner="attribution-replay-v1",dataset_id=dataset.dataset_id,evidence=dataset.evidence,split=split,
        model="injected-team-bib-readings-no-ocr-v1",settings=dataset.settings.model_dump(mode="json"),
        manifest_sha256=digest(path),implementation_sha256={p.relative_to(root).as_posix():digest(p) for p in sources},
        goals=len(rows),observations=observations,fields={f:field_summary(rows,f) for f in ("scorer","assist","own_goal")},
        grouped_fields={key:{f:field_summary(group,f) for f in ("scorer","assist","own_goal")} for key,group in sorted(groups.items())},
        sessions=rows,automatic_attribution_enabled=False,official_score_mutated=False,release_qualified=False,
        field_accuracy_measured=False,gate=dict(required_accuracy=.98,required_coverage=.90,required_heldout_goals=100,state="pending"),
        limitations=["Injected identities and generated references do not test pixel recognition or physical touch detection",
            "No measured full-pitch/overhead coverage or real identity handoff is available",
            "Temporal windows and uncertainty limits are unmeasured prototype defaults",
            "Suggestions need operator approval; independent attribution/release gates remain pending",
            "Intervals are descriptive Wilson intervals without match-clustering adjustment"])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest",type=Path)
    parser.add_argument("--split",choices=["train","validation","blind_test"],default="validation")
    parser.add_argument("--allow-blind-test",action="store_true")
    parser.add_argument("--max-observations",type=int,default=100000)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=replay(args.manifest,args.split,args.allow_blind_test,args.max_observations)
    with args.output.open("x",encoding="utf-8") as handle:handle.write(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(f"Replayed {result['goals']} attribution windows; operator review required, no official mutation")
