"""Deterministic dummy raw accelerometer sessions and transport failures; no field data."""
import argparse
import json
import math
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.sensors import (ImpactLabel, SensorAlignment, SensorAsset, SensorDataset, SensorPacket, SensorSession, SensorSettings)
from modules.replay.dataset import digest
from modules.sensors.protocol import encode, FIFO_OVERRUN, TIMESTAMP_ESTIMATED
from tools.check_sensor_sync import evaluate


def build(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    sessions, syncs = [], []
    for split_index, split in enumerate(("train", "validation", "blind_test")):
        settings = SensorSettings()
        boot = 100+split_index
        gain = (1, .9, 1.1)[split_index]
        sync = dict(version=f"dummy-alignment-{split}-v1", evidence="synthetic", groups=[])
        for device in (1, 2):
            scale = 1 if device == 1 else 1.0001
            sync["groups"].append(dict(device_id=device, boot_id=boot, host_clock_domain="dummy-host",
                markers=[dict(device_seconds=t, host_seconds=scale*t, uncertainty_seconds=.0005,
                    split="fit" if i<3 else "validation") for i,t in enumerate((0, .5, 1, 2, 5, 9.998))]))
        timing = evaluate(sync)
        syncs.append(sync)
        raw, receipts, labels = bytearray(), [], []
        sequences = {(d,r): 0 for d in (1, 2) for r in ("net", "frame")}
        schedule = []
        # Wave shapes are artificial feature challenges, not biomechanical impact models.
        incidents = [(1, 1, "frame"), (2, 1, "goal"), (3, 2, "player"), (4, 2, "wall"),
                     (5, 1, "post_and_in"), (6, 2, "goal"), (7, 1, "goal"), (8.8, 1, "goal")]
        for time, device, physical in incidents:
            if split != "validation" and time >= 7:
                continue
            labels.append(ImpactLabel(incident_id=f"{split}-{time}", match_id=f"sensor-{split}-match",
                goal_end="goal_a" if device == 1 else "goal_b", occurred_seconds=time*(1 if device==1 else 1.0001), physical_class=physical))
        labels.append(ImpactLabel(incident_id=f"{split}-quiet", match_id=f"sensor-{split}-match", goal_end="goal_a", occurred_seconds=.7, physical_class="noise"))

        def signal(time, device, role, axis):
            background = .003*math.sin(time*53+axis+split_index)
            value = (1 if axis == 2 else 0)+background
            if axis != 0:
                return value
            for incident, target, physical in incidents:
                if device != target or (split != "validation" and incident>=7):
                    continue
                dt = time-incident
                if physical == "player":
                    value += gain*(1.2 if role=="net" else .08)*math.exp(-((dt-.025)/.04)**2)
                elif 0 <= dt < .16:
                    amplitude = {"goal": (2.5, .12), "frame": (.12, 3), "wall": (.1, 2), "post_and_in": (2.5, 2.4)}[physical]
                    value += gain*amplitude[0 if role=="net" else 1]*math.exp(-dt/ .07)*math.sin(2*math.pi*90*dt)
                if incident == 6 and role == "net" and 0 <= dt < .015:
                    value = 16  # clipping is deliberate, routes to unknown.
            return value

        for start in range(0, 8000, 32):
            for device in (1, 2):
                reset = split=="validation" and device==1 and start>=6400
                local_start = start-6400 if reset else start
                for role in ("net", "frame"):
                    key = device, role
                    sequence = local_start//32  # per sensor stream; no health packets in this dummy stream
                    samples = [tuple(max(-4096, min(4095, round(signal(i/800,device,role,axis)/settings.scale_g_per_lsb))) for axis in range(3)) for i in range(start,start+32)]
                    packet = SensorPacket(kind="samples", goal_end="goal_a" if device==1 else "goal_b", role=role,
                        device_id=device, boot_id=boot+1000 if reset else boot, packet_sequence=sequence,
                        first_sample_sequence=local_start, first_device_us=local_start*1250, samples=samples,
                        flags=TIMESTAMP_ESTIMATED | (FIFO_OVERRUN if split=="validation" and start==5600 and role=="frame" and device==1 else 0))
                    wire = encode(packet)
                    if split=="validation" and device==1 and start==5568 and role=="frame":
                        continue  # a lost packet; first_sample_sequence still exposes missing fresh samples
                    if split=="validation" and device==1 and start==5600 and role=="net":
                        damaged = bytearray(wire); damaged[60]^=0x10; wire=bytes(damaged)
                    received = (start+31)/800*(1 if device==1 else 1.0001)+.01
                    schedule.append((received, device, role, wire))
        schedule.sort(key=lambda row:(row[0],row[1],row[2]))
        disconnected = False
        for received, device, role, wire in schedule:
            if split=="validation" and device==1 and not disconnected and received>=8:
                receipts.append(dict(kind="disconnect", device_id=1, received_seconds=received, byte_offset=len(raw), byte_length=0))
                disconnected=True
            if split=="validation" and device==1 and 6.8<received<6.85 and role=="net":
                junk=b"dummy-garbage-NF"; offset=len(raw); raw+=junk
                receipts.append(dict(kind="read", received_seconds=received, byte_offset=offset, byte_length=len(junk)))
            offset=len(raw); raw+=wire
            receipts.append(dict(kind="read", received_seconds=received, byte_offset=offset, byte_length=len(wire)))
        raw_path, index_path = root/f"{split}.nfsp", root/f"{split}-receipts.jsonl"
        for row in receipts:
            row["session_id"] = f"sensor-{split}"
        raw_path.write_bytes(raw)
        index_path.write_text("".join(json.dumps(r, sort_keys=True)+"\n" for r in receipts), encoding="utf-8")
        sessions.append(SensorSession(session_id=f"sensor-{split}", match_id=f"sensor-{split}-match", source_group_id=f"dummy-match-{split}",
            split=split, evidence="synthetic", duration_seconds=10.1, host_clock_domain="dummy-host", devices={1:"goal_a",2:"goal_b"},
            raw=SensorAsset(path=raw_path.name,sha256=digest(raw_path)), receipts=SensorAsset(path=index_path.name,sha256=digest(index_path)),
            labels=labels, alignments=[SensorAlignment.model_validate(a) for a in timing["alignments"]]))
    dataset = SensorDataset(dataset_id="dummy-sensors-v1", split_assignment_version="dummy-groups-v1", settings=SensorSettings(), sessions=sessions)
    (root/"dataset.json").write_text(dataset.model_dump_json(indent=2)+"\n", encoding="utf-8")
    (root/"sync-markers.json").write_text(json.dumps(syncs[1],indent=2,sort_keys=True)+"\n", encoding="utf-8")
    return dataset


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    result=build(parser.parse_args().root)
    print(f"Created {len(result.sessions)} dummy sensor sessions with raw packets and grouped labels")
