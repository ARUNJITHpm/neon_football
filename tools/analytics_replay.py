"""Replay independently specified dummy events/time accounting without a score database."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from core.analytics import AnalyticsDataset, AnalyticsSession
from modules.stats.analytics import analyze
from modules.replay.dataset import asset_path, digest


def replay(path,split="validation",allow_blind_test=False,max_contacts=100000):
    path=Path(path)
    if path.stat().st_size>16*1024*1024 or not 1<=max_contacts<=1000000:raise ValueError("Analytics replay capacity exceeded")
    if split=="blind_test" and not allow_blind_test:raise ValueError("Blind-test needs explicit opt-in; dummy assets are public")
    if split not in ("train","validation","blind_test"):raise ValueError("Invalid analytics split")
    dataset=AnalyticsDataset.model_validate_json(path.read_text(encoding="utf-8"))
    assets=[a for a in dataset.sessions if a.split==split]
    if not assets:raise ValueError("No selected analytics sessions")
    rows=[];contacts=0
    keys=("kind","previous_touch_id","touch_id","team","from_player_id","to_player_id")
    for asset in assets:
        source=asset_path(path.parent,asset.path)
        if source.stat().st_size>4*1024*1024 or digest(source)!=asset.sha256:raise ValueError("Analytics asset checksum/capacity differs")
        session=AnalyticsSession.model_validate_json(source.read_text(encoding="utf-8"))
        if (session.session_id,session.match_id,session.evidence)!=(asset.session_id,asset.match_id,dataset.evidence):raise ValueError("Analytics asset identity/provenance differs")
        contacts+=len(session.contacts)
        if contacts>max_contacts or len(session.contacts)*(len(session.periods)+len(session.rosters))>1000000:raise ValueError("Analytics replay work/contact capacity exceeded")
        result=analyze(session,dataset.settings)
        errors={}
        for kind in ("pass","interception"):
            predicted={tuple(e[k] for k in keys) for e in result["events"] if e["kind"]==kind}
            expected={tuple(getattr(e,k) for k in keys) for e in asset.reference.events if e.kind==kind}
            errors[kind]=dict(matched=len(predicted&expected),false=len(predicted-expected),missed=len(expected-predicted))
        seconds={**{team:r["possession_seconds"] for team,r in result["teams"].items()},"unknown":result["time_accounting"]["unknown_possession_seconds"]}
        errors["possession_absolute_error_seconds"]={team:abs(seconds[team]-asset.reference.possession_seconds[team]) for team in seconds}
        rows.append(dict(session_id=session.session_id,conditions=session.conditions,reference=asset.reference.model_dump(mode="json"),result=result,errors=errors))
    totals={kind:{field:sum(row["errors"][kind][field] for row in rows) for field in ("matched","false","missed")} for kind in ("pass","interception")}
    possession_error={team:sum(row["errors"]["possession_absolute_error_seconds"][team] for row in rows)/len(rows) for team in ("orange","green","unknown")}
    root=Path(__file__).resolve().parents[1]
    sources=[Path(__file__).resolve(),root/"core/analytics.py",root/"core/schemas.py",root/"core/attribution.py",root/"modules/stats/analytics.py",root/"app/analytics.py",root/"tools/build_analytics_fixture.py"]
    return dict(schema_version=1,runner="contact-analytics-replay-v1",dataset_id=dataset.dataset_id,evidence=dataset.evidence,split=split,
        windows=len(rows),contacts=contacts,manifest_sha256=digest(path),implementation_sha256={p.relative_to(root).as_posix():digest(p) for p in sources},
        event_totals=totals,possession_mean_absolute_error_seconds=possession_error,sessions=rows,
        automatic_scoring_enabled=False,field_qualified=False,score_database_opened=False,
        field_gates=[dict(metric="pass",precision_min=.95,recall_min=.90,reference_events_min=200,state="pending"),
                    dict(metric="interception",precision_min=.95,recall_min=.90,reference_events_min=100,state="pending"),
                    dict(metric="possession",team_share_error_percentage_points_max=5,known_possession_time_coverage_min=.90,reference_minutes_min=60,state="pending")],
        limitations=["Generated numeric contacts/time references are not real match accuracy", "Proposed field gates require venue agreement and independent held-out labels",
                     "Condition tags do not measure real lighting/overlap", "Distance/heatmaps/shots remain unavailable"])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("manifest",type=Path);parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--split",choices=["train","validation","blind_test"],default="validation");parser.add_argument("--allow-blind-test",action="store_true")
    args=parser.parse_args();result=replay(args.manifest,args.split,args.allow_blind_test)
    with args.output.open("x",encoding="utf-8") as handle:handle.write(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(windows=result["windows"],events=result["event_totals"],possession_error=result["possession_mean_absolute_error_seconds"],field_qualified=False)))
