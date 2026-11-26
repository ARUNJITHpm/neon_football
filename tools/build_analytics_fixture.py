"""Create explicit generated contact-event/time references; no pixels or learned model."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app.analytics import dummy_session
from core.analytics import AnalyticsDataset, AnalyticsAsset, AnalyticsReference, AnalyticsEventReference, AnalyticsRosterEpoch, AnalyticsPeriod
from tools.build_attribution_fixture import PLAYERS, ACTIVE


def cases():
    result={}
    # Explicit intended source-contact pairs and team possession durations.
    references={
        "passing": ([(0,1),(2,3)],[(3,4)],(3,8,1)),
        "pauses": ([(0,1),(6,7)],[(4,5)],(5,11,3)),
        "gaps": ([(0,1)],[],(2,4,6)),
        "uncertain": ([(2,3)],[],(1,6,5)),
        "unknown_identity": ([(2,3)],[(3,4)],(3,6,3)),
        "proximity_only": ([],[],(0,0,12)),
        "same_player": ([],[],(0,11,1)),
        "source_reset": ([(0,1)],[(3,4)],(3,8,1)),
        "ambiguous_order": ([(2,3)],[(3,4)],(3,4,5)),
        "roster_change": ([(0,1)],[(3,4)],(3,7,2)),
        "no_play": ([],[],(0,0,0)),
        "unknown_clock": ([],[],(0,0,12)),
    }
    for index,(name,(passes,interceptions,possession)) in enumerate(references.items()):
        scenario=name if name in ("passing","pauses","gaps","uncertain") else "passing"
        session=dummy_session(match_id=f"match-{name}",session_id=f"session-{name}",players=PLAYERS,
            active_player_ids=ACTIVE,scenario=scenario,uncertainty=0)
        if name=="unknown_identity": session.contacts[1].player_id=None
        if name=="proximity_only":
            for c in session.contacts:c.kind="proximity"
        if name=="same_player":
            for c in session.contacts:c.player_id="green-7"
        if name=="source_reset":session.contacts[2].boot_id="new-boot"
        if name=="ambiguous_order":session.contacts[1].occurred_seconds=1
        if name=="roster_change":
            roster=session.rosters[0].roster.model_copy(deep=True)
            roster.revision=1;roster.active_player_ids=[pid for pid in ACTIVE if pid!="green-7"]+["green-15"]
            session.rosters.append(AnalyticsRosterEpoch(start_seconds=6,roster=roster))
            for c in session.contacts:
                if c.occurred_seconds>=6:
                    c.roster_revision=1
                    if c.player_id=="green-7":c.player_id="green-15"
        if name=="no_play":
            session.periods=[AnalyticsPeriod(start_seconds=a,end_seconds=b,state=state) for a,b,state in [(0,4,"paused"),(4,8,"dead_ball"),(8,12,"unknown")]]
        if name=="unknown_clock":session.timing_quality="unverified"
        session.conditions=["generated_numeric",name,"overlap" if index%2 else "clear_view", "low_light" if index%3==0 else "normal_light"]
        session=type(session).model_validate(session.model_dump())
        by_player={p.id:p for p in session.rosters[0].roster.players}
        labels=[]
        # Labels reference fixture intent; no analytics implementation is invoked here.
        for kind,pairs in (("pass",passes),("interception",interceptions)):
            for a,b in pairs:
                first,second=session.contacts[a],session.contacts[b]
                labels.append(AnalyticsEventReference(kind=kind,previous_touch_id=first.touch_id,touch_id=second.touch_id,
                    team=by_player[second.player_id].team,from_player_id=first.player_id,to_player_id=second.player_id))
        reference=AnalyticsReference(passes=len(passes),interceptions=len(interceptions),
            possession_seconds=dict(zip(("orange","green","unknown"),possession)),adjudication="generated_reference",events=labels)
        result[name]=(session,reference)
    return result


def build(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    assets=[]
    for name,(session,reference) in cases().items():
        content=(json.dumps(session.model_dump(mode="json"),indent=2,sort_keys=True)+"\n").encode()
        (destination/f"{name}.json").write_bytes(content)
        assets.append(AnalyticsAsset(session_id=session.session_id,match_id=session.match_id,source_group_id=f"group-{name}",
            split="train" if name=="passing" else "blind_test" if name=="source_reset" else "validation",path=f"{name}.json",
            sha256=hashlib.sha256(content).hexdigest(),reference=reference))
    dataset=AnalyticsDataset(dataset_id="dummy-contact-analytics-v1",evidence="synthetic",sessions=assets)
    (destination/"dataset.json").write_text(json.dumps(dataset.model_dump(mode="json"),indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return len(assets)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("destination",type=Path);args=parser.parse_args()
    print(f"Built {build(args.destination)} generated analytics windows")
