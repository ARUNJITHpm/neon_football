"""Build generated identity/touch challenges and explicit reference labels; no OCR/video."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app.attribution import dummy_sequence
from core.attribution import AttributionDataset, AttributionAsset, AttributionLabel, AttributionSettings, IdentityReading, TouchObservation

PLAYERS=[dict(id="green-7",team="green",bib=7,name="Green Seven"),dict(id="green-11",team="green",bib=11,name="Green Eleven"),
         dict(id="orange-9",team="orange",bib=9,name="Orange Nine"),dict(id="orange-13",team="orange",bib=13,name="Orange Thirteen"),
         dict(id="green-15",team="green",bib=15,name="Green Fifteen")]
ACTIVE=["green-7","green-11","orange-9","orange-13"]


def cases():
    result={}
    names=["direct","assist","own_goal","deflection","uncertain","identity_switch","partial_coverage","occluded",
        "few_reads","stale_reads","proximity_only","opponent_breaks_assist","same_player_dribble","no_contact",
        "ambiguous_order","clock_unknown","future_reads","inactive_bib","unknown_bib","touch_uncertainty",
        "frame_rebound","source_reset","orange_goal","unclear_assist","substituted_roster"]
    for index,name in enumerate(names):
        scenario=name if name in ("direct","assist","own_goal","deflection","uncertain","identity_switch") else "assist" if name in ("opponent_breaks_assist","same_player_dribble","ambiguous_order","unclear_assist") else "direct"
        scoring="orange" if name=="orange_goal" else "green"
        seq=dummy_sequence(match_id=f"match-{name}",goal_id=f"goal-{name}",session_id=f"session-{name}",players=PLAYERS,
            active_player_ids=ACTIVE,scoring_team=scoring,scenario=scenario,goal_end="goal_b" if index%2 else "goal_a")
        label=AttributionLabel(goal_id=seq.goal.goal_id,scorer_id="orange-9" if scoring=="orange" or name=="own_goal" else "green-7",
            assist_id="green-11" if name in ("assist","same_player_dribble","ambiguous_order","unclear_assist") else None,
            own_goal=name=="own_goal",adjudication="generated_reference")
        def add_contact(player_id,at,kind):
            p=next(p for p in seq.roster.players if p.id==player_id)
            common=dict(match_id=seq.goal.match_id,session_id=seq.goal.session_id,roster_revision=seq.roster.revision,evidence="synthetic")
            track=f"added-{len(seq.touches)}"
            for frame in range(3):
                seq.readings.append(IdentityReading(**common,event_id=f"{track}-read-{frame}",camera_id="dummy-camera",boot_id="dummy-boot",track_id=track,
                    frame_sequence=frame,occurred_seconds=at-.3+frame*.1,team=p.team,bib=p.bib,quality="clear"))
            seq.touches.append(TouchObservation(**common,event_id=f"{track}-touch",camera_id="dummy-camera",boot_id="dummy-boot",track_id=track,
                occurred_seconds=at,uncertainty_seconds=.005,kind=kind,certainty="certain"))
        if name=="partial_coverage": seq.goal.touch_coverage="partial"
        if name=="occluded": seq.readings[-1].quality="occluded"
        if name=="few_reads": seq.readings=seq.readings[:2]
        if name=="stale_reads":
            for r in seq.readings: r.occurred_seconds-=3
        if name=="proximity_only": seq.touches[-1].kind="proximity"
        if name=="opponent_breaks_assist": add_contact("orange-9",8.5,"interception")
        if name=="same_player_dribble": add_contact("green-7",8.5,"control")
        if name=="no_contact": seq.touches=[]
        if name=="ambiguous_order": seq.touches[0].occurred_seconds=8.997
        if name=="clock_unknown": seq.goal.timing_quality="unverified"
        if name=="future_reads":
            for r in seq.readings:r.occurred_seconds+=2
        if name=="inactive_bib":
            for r in seq.readings:r.bib=15
            label.scorer_id="green-15"
        if name=="unknown_bib":
            for r in seq.readings:r.bib=None
        if name=="touch_uncertainty":seq.touches[-1].uncertainty_seconds=.1
        if name=="frame_rebound":
            extra=seq.touches[-1].model_copy(update=dict(event_id="rebound",track_id=None,kind="frame_rebound",occurred_seconds=9.5))
            seq.touches.append(extra)
        if name=="source_reset": seq.touches[-1].boot_id="new-boot"
        if name=="unclear_assist":
            for r in seq.readings[:3]:r.quality="uncertain"
        if name=="substituted_roster":
            seq.roster.revision=1;seq.roster.active_player_ids=["green-15","green-11","orange-9","orange-13"]
            for r in seq.readings:r.roster_revision=1;r.bib=15
            for t in seq.touches:t.roster_revision=1
            label.scorer_id="green-15"
        seq.conditions=["generated_numeric",name,"low_light" if index%3==0 else "normal_light", "overlap" if index%4==0 else "clear_view"]
        result[name]=(type(seq).model_validate(seq.model_dump()),label)
    return result


def build(destination):
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=False)
    sessions=[]
    for name,(sequence,label) in cases().items():
        content=(json.dumps(sequence.model_dump(mode="json"),indent=2,sort_keys=True)+"\n").encode()
        (destination/f"{name}.json").write_bytes(content)
        split="train" if name=="direct" else "blind_test" if name=="source_reset" else "validation"
        sessions.append(AttributionAsset(session_id=sequence.goal.session_id,source_group_id=f"dummy-group-{name}",match_id=sequence.goal.match_id,
            split=split,path=f"{name}.json",sha256=hashlib.sha256(content).hexdigest(),label=label))
    dataset=AttributionDataset(dataset_id="dummy-attribution-v1",annotation_policy="explicit-generated-touch-references-v1",
        evidence="synthetic",settings=AttributionSettings(),sessions=sessions)
    (destination/"dataset.json").write_text(json.dumps(dataset.model_dump(mode="json"),indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return len(sessions)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination",type=Path)
    args=parser.parse_args()
    print(f"Built {build(args.destination)} generated attribution windows; no image recognition or score mutation")
