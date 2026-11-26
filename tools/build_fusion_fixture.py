"""Build explicit dummy lifecycle challenges and replay actual Part 04/05 fixture outputs."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from core.fusion import FusionCamera, FusionDataset, FusionEvidence, FusionReference, FusionReplayStep, FusionSession, FusionSettings
from core.sensors import SensorAsset, SensorImpact
from core.vision import VisionCandidate
from modules.replay.dataset import digest
from tools.sensor_replay import replay as sensors
from tools.vision_replay import run as visions


def visual(event="v1",t=1,end="goal_a",quality="observed_crossing",track="ball1",**changes):
    values=dict(event_id=event,session_id="placeholder",match_id="placeholder",camera_id=f"camera-{end}",
        goal_end=end,track_id=track,occurred_seconds=t,emitted_seconds=t+.02,timing_uncertainty_seconds=.002,
        calibration_version="cal-v1",model_version="injected-v1",configuration_version="vision-v1",
        quality=quality,evidence="synthetic",reasons=["explicit dummy crossing"],flags=[],
        supporting_sequences=[1,2],crossing_interval_seconds=(t-.005,t+.005))
    values.update(changes)
    return VisionCandidate(**values)


def impact(event="s1",t=1.01,end="goal_a",classification="net_impact",**changes):
    values=dict(event_id=event,goal_end=end,device_id=1 if end=="goal_a" else 2,boot_id=1,
        occurred_device_seconds=t,occurred_seconds=t,emitted_seconds=t+.12,timing_uncertainty_seconds=.003,
        host_clock_domain="host",evidence="synthetic",classification=classification,
        features={"net_peak_g":2.},flags=[],configuration_version="impact-rules-v1")
    values.update(changes)
    return SensorImpact(**values)


def tick(t):
    return dict(kind="tick",at_seconds=t)


def cmd(action,t=0,ref=None):
    return dict(kind="command",at_seconds=t,action=action,command_id=f"{action}:{t}",candidate_evidence_id=ref)


def obs(value,epoch=1,at=None):
    return dict(kind="evidence",at_seconds=value.emitted_seconds if at is None else at,
                observation=value,epoch=epoch)


def build(destination,include_upstream=True):
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    cameras={f"camera-{end}":FusionCamera(goal_end=end,calibration_version="cal-v1",model_version="injected-v1",
        configuration_version="vision-v1") for end in ("goal_a","goal_b")}
    for end,camera in (("goal_a","goal-a"),("goal_b","goal-b")):
        cameras[camera]=FusionCamera(goal_end=end,calibration_version="synthetic-geometry-v1",
            model_version="injected-trajectories-no-detector-v1",configuration_version="synthetic-vision-v1")
    settings=FusionSettings(cameras=cameras,devices={1:"goal_a",2:"goal_b"})
    sessions=[]

    def add(name,steps,goals=(),duration=3,split="validation",session_id=None,match_id=None,domain="host",preserve=False):
        sid,mid=session_id or f"fusion-{name}",match_id or f"match-{name}"
        rows=[]
        for step in [cmd("start"),*steps]:
            step=step.copy()
            if step["kind"]=="evidence":
                o,epoch=step.pop("observation"),step.pop("epoch")
                if not preserve and isinstance(o,VisionCandidate):
                    o=o.model_copy(update=dict(session_id=sid,match_id=mid))
                step["evidence"]=FusionEvidence(session_id=sid,match_id=mid,clock_domain=domain,play_epoch=epoch,observation=o)
            rows.append(FusionReplayStep(**step).model_dump(mode="json"))
        target=destination/f"{name}.jsonl"
        target.write_text("".join(json.dumps(r,sort_keys=True,separators=(",",":"))+"\n" for r in rows),encoding="utf-8")
        labels=[FusionReference(label_id=f"{name}:label:{i}",goal_end=end,team=team,occurred_seconds=t,validity=validity)
                for i,(t,end,team,validity) in enumerate(goals)]
        sessions.append(FusionSession(session_id=sid,match_id=mid,source_group_id=f"dummy-group-{name}",split=split,
            clock_domain=domain,evidence="synthetic",duration_seconds=duration,
            steps=SensorAsset(path=target.name,sha256=digest(target)),labels=labels))

    goal=(1,"goal_a","green","valid")
    add("observed",[obs(visual()),obs(impact())],[goal])
    add("post-and-in",[obs(visual()),obs(impact(classification="mixed_impact"))],[goal])
    add("player-net",[obs(visual(quality="net_motion_only",track=None)),obs(impact(classification="slow_impact")),
        tick(1.4),cmd("reject",1.4,"v1")],[(1,"goal_a","green","invalid")])
    add("partial",[obs(visual(quality="boundary_uncertain")),obs(impact())],[(1,"goal_a","green","invalid")])
    add("occluded",[obs(visual(quality="predicted_crossing")),obs(impact()),tick(1.4),cmd("confirm",1.4,"v1")],[goal])
    add("duplicates",[obs(visual()),obs(visual(),at=1.03),obs(impact()),tick(1.4),obs(visual("repeat",1.4))],[goal])
    add("late",[obs(visual()),tick(1.32),obs(impact(emitted_seconds=1.34))],[goal])
    nearby=[goal,(1.05,"goal_a","green","valid")]
    add("nearby",[obs(visual()),obs(visual("v2",1.05,track="second")),obs(impact(t=1.07))],nearby)
    add("early-impact-nearby",[obs(visual()),obs(impact()),obs(visual("v2",1.14,track="second"))],
        [goal,(1.14,"goal_a","green","valid")])
    add("quick-restart",[obs(visual()),obs(impact()),tick(1.4),cmd("restart",1.6),
        obs(visual("next",1.8,track="next"),epoch=2),obs(impact("next-impact",1.81),epoch=2)],
        [goal,(1.8,"goal_a","green","valid")])
    add("dead-ball",[obs(visual()),obs(impact()),tick(1.4),obs(visual("retrieval",1.5,track="another"))],
        [goal,(1.5,"goal_a","green","invalid")])
    add("pause",[obs(visual()),cmd("pause",1.1),obs(impact()),obs(visual("paused",1.5),epoch=2)],
        [(1,"goal_a","green","invalid")])
    add("side-change",[cmd("pause",.5),cmd("swap_ends",.6),cmd("resume",.7),
        obs(visual(),epoch=4),obs(impact(),epoch=4)],[(1,"goal_a","orange","valid")])
    add("stale-and-future",[obs(visual(),epoch=0),obs(visual("old",.2),at=1.1),obs(visual("future",2),at=1.2)])
    add("review-expiry",[obs(visual()),tick(17),cmd("confirm",17,"v1")],[goal],duration=20)
    add("correction",[obs(visual()),tick(1.4),cmd("confirm",1.4,"v1"),cmd("undo",1.5,"v1")],[goal])
    add("unmapped",[obs(impact(occurred_seconds=None,timing_uncertainty_seconds=None))])
    add("train-guard",[obs(visual(t=2)),obs(impact(t=2.01))],[(2,"goal_a","green","valid")],duration=4,split="train")
    add("blind-guard",[obs(visual(t=2,quality="net_motion_only",track=None))],duration=4,split="blind_test")
    provenance=[]
    if include_upstream:
        root=Path(__file__).resolve().parents[1]
        sr=sensors(root/"tests/sensors/fixtures/dataset.json")
        vr=visions(root/"tests/vision/fixtures/replay/dataset.json",root/"tests/vision/fixtures/replay/settings.json",
            root/"tests/vision/fixtures/replay/annotations.json")
        for name,report in (("upstream-sensors",sr),("upstream-vision",vr)):
            target=destination/f"{name}.json"
            target.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
            provenance.append(SensorAsset(path=target.name,sha256=digest(target)))
        source=sr["sessions"][0]
        impacts=[SensorImpact.model_validate(i) for i in source["impacts"]]
        sensor_dataset=json.loads((root/"tests/sensors/fixtures/dataset.json").read_text(encoding="utf-8"))
        registered=next(s for s in sensor_dataset["sessions"] if s["session_id"]==source["session_id"])
        add("upstream-sensors",[obs(o) for o in sorted(impacts,key=lambda o:o.emitted_seconds)],duration=source["duration_seconds"],
            session_id=source["session_id"],match_id=registered["match_id"],domain=registered["host_clock_domain"],preserve=True)
        candidates=[VisionCandidate.model_validate(c) for c in vr["candidates"]]
        manifest=json.loads((root/"tests/vision/fixtures/replay/dataset.json").read_text(encoding="utf-8"))
        registered=next(s for s in manifest["sessions"] if s["session_id"]==candidates[0].session_id)
        add("upstream-vision",[obs(o) for o in sorted(candidates,key=lambda o:o.emitted_seconds)],
            duration=registered["duration_seconds"],session_id=candidates[0].session_id,match_id=candidates[0].match_id,
            domain=registered["host_clock_domain"],preserve=True)
    dataset=FusionDataset(dataset_id="dummy-fusion-v1",split_assignment_version="dummy-fusion-groups-v1",
        settings=settings,sessions=sessions,provenance_assets=provenance)
    (destination/"dataset.json").write_text(dataset.model_dump_json(indent=2)+"\n",encoding="utf-8")
    return dataset


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination",type=Path)
    args=parser.parse_args()
    dataset=build(args.destination)
    print(f"Built {len(dataset.sessions)} dummy sessions; numerical scenarios plus unmodified upstream candidate/impact outputs")
