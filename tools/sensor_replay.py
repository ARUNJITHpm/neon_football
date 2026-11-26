"""Offline CRC packet replay, sensor health and impact-only evaluation on grouped splits."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from types import SimpleNamespace

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.sensors import SensorDataset
from modules.replay.dataset import asset_path, digest
from modules.replay.matching import match
from modules.replay.statistics import distribution, poisson_rate, proportion
from modules.sensors.host import SensorHost
from modules.sensors.impact import ImpactEngine
from modules.sensors.protocol import PacketDecoder, SENSOR_RESTART


def replay(manifest_path, split="validation", allow_blind_test=False, max_packets=100000, max_samples=2000000):
    if not 1 <= max_packets <= 1000000 or not 1 <= max_samples <= 10000000:
        raise ValueError("Set explicit bounded replay capacities")
    if split == "blind_test" and not allow_blind_test:
        raise ValueError("Blind-test access requires --allow-blind-test after freezing rules")
    manifest_path = Path(manifest_path)
    dataset = SensorDataset.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    sessions = sorted((s for s in dataset.sessions if s.split == split), key=lambda s:s.session_id)
    if not sessions:
        raise ValueError("No sessions for sensor split")
    results, inputs, packets_total, samples_total = [], [], 0, 0
    totals = Counter()
    confusion = defaultdict(Counter)
    latencies = []
    for session in sessions:
        for asset in (session.raw, session.receipts):
            if digest(asset_path(manifest_path.parent, asset.path)) != asset.sha256:
                raise ValueError("Sensor asset checksum differs")
            inputs.append(dict(session_id=session.session_id, **asset.model_dump()))
        host = SensorHost(dataset.settings, session.devices, session.alignments, session.host_clock_domain, session.evidence)
        engine, decoder, epochs = ImpactEngine(dataset.settings), PacketDecoder(), Counter()
        events, position, previous_receipt, read_count = [], 0, -1, 0
        transport = Counter()
        with asset_path(manifest_path.parent, session.raw.path).open("rb") as raw, asset_path(manifest_path.parent, session.receipts.path).open(encoding="utf-8") as index:
            for row in index:
                read_count += 1
                if read_count > max_packets*4+64:
                    raise ValueError("Sensor receipt capacity reached")
                record = json.loads(row)
                now = record["received_seconds"]
                if record["session_id"] != session.session_id or not previous_receipt <= now <= session.duration_seconds or record["byte_offset"] != position:
                    raise ValueError("Receipt timeline/index boundary mismatch")
                previous_receipt = now
                if record["kind"] == "disconnect":
                    device = record["device_id"]
                    if device not in session.devices or record["byte_length"] != 0:
                        raise ValueError("Invalid disconnect record")
                    epochs[device] += 1
                    engine.invalidate(device)
                    decoder.reset()
                    transport["disconnects"] += 1
                    continue
                if record["kind"] != "read" or not 1 <= record["byte_length"] <= 4096:
                    raise ValueError("Invalid bounded raw read")
                chunk = raw.read(record["byte_length"])
                if len(chunk) != record["byte_length"]:
                    raise ValueError("Truncated raw bytes")
                position += len(chunk)
                for packet in decoder.feed(chunk):
                    packets_total += 1
                    if packets_total > max_packets:
                        raise ValueError("Sensor packet capacity reached")
                    if packet.flags & SENSOR_RESTART:
                        engine.invalidate(packet.device_id)
                    samples = host.process(packet, now, epochs[packet.device_id])
                    samples_total += len(samples)
                    if samples_total > max_samples:
                        raise ValueError("Sensor sample capacity reached")
                    events.extend(engine.ingest(samples))
            if position != raw.seek(0, 2):
                raise ValueError("Receipt index does not cover complete raw stream")
        events.extend(engine.flush(session.duration_seconds))
        decoder.reset()
        predictions = [SimpleNamespace(event_id=e.event_id, match_id=session.match_id, goal_end=e.goal_end,
                        occurred_seconds=e.occurred_seconds, impact=e) for e in events if e.occurred_seconds is not None]
        labels = [SimpleNamespace(label_id=l.incident_id, match_id=l.match_id, goal_end=l.goal_end,
                    crossing_seconds=l.occurred_seconds, label=l) for l in session.labels]
        pairs = match(labels, predictions, .2, compatible=lambda l,p:l.match_id==p.match_id and l.goal_end==p.goal_end)
        assigned = {p.event_id for _,p in pairs}
        labelled = {l.label_id: p for l,p in pairs}
        for label in session.labels:
            prediction = labelled.get(label.incident_id)
            confusion[label.physical_class][prediction.impact.classification if prediction else "no_event"] += 1
        active_labels = [l for l in labels if l.label.physical_class != "noise"]
        found = sum(l.label.physical_class != "noise" for l,p in pairs)
        false = [p for p in predictions if p.event_id not in assigned or next(l for l,pair in pairs if pair.event_id==p.event_id).label.physical_class == "noise"]
        local_latencies = [p.impact.emitted_seconds-l.crossing_seconds for l,p in pairs if l.label.physical_class != "noise"]
        latencies += local_latencies
        counts = dict(impact_labels=len(active_labels), detected_labelled_impacts=found, misses=len(active_labels)-found,
            events=len(events), unknown=sum(e.classification=="unknown" for e in events), unmapped=sum(e.occurred_seconds is None for e in events),
            false_impacts=len(false), noise_labels=sum(l.physical_class=="noise" for l in session.labels))
        totals.update(counts)
        results.append(dict(session_id=session.session_id, evidence=session.evidence, duration_seconds=session.duration_seconds,
            counts=counts, impacts=[e.model_dump(mode="json") for e in events],
            decoder=dict(decoder.counters), transport=dict(transport), host=dict(host.counters), engine=dict(engine.counters),
            baseline=engine.baseline_report(), final_health=host.health(session.duration_seconds+.5),
            impact_detection_recall=proportion(found,len(active_labels)), false_impacts_per_hour=poisson_rate(len(false),session.duration_seconds/3600),
            latency_seconds=distribution(local_latencies), error_incidents=[l.label_id for l in active_labels if l.label_id not in labelled]))
    root = Path(__file__).resolve().parents[1]
    files = [Path(__file__), root/"core/sensors.py",root/"core/clock.py",root/"modules/replay/matching.py",root/"modules/replay/statistics.py",
             root/"modules/replay/dataset.py",*sorted((root/"modules/sensors").glob("*.py")),*sorted((root/"firmware/esp32/neon_sensors").glob("*.ino"))]
    seconds = sum(s.duration_seconds for s in sessions)
    return dict(schema_version=1, runner="sensor-evidence-v1", dataset_id=dataset.dataset_id, split=split,
        provenance=dict(manifest_sha256=digest(manifest_path), inputs=inputs,
            implementation={p.relative_to(root).as_posix():digest(p) for p in files}),
        packet_count=packets_total, sample_count=samples_total, counts=dict(totals), sessions=results,
        confusion={physical:dict(sorted(predictions.items())) for physical,predictions in sorted(confusion.items())},
        impact_detection_recall=proportion(totals["detected_labelled_impacts"],totals["impact_labels"]),
        false_impacts_per_hour=poisson_rate(totals["false_impacts"],seconds/3600), latency_seconds=distribution(latencies),
        firmware_compiled=False, hardware_tested=False, goal_accuracy_measured=False, release_qualified=False,
        limitations=["Dummy waveforms and markers do not validate field impacts or timing",
            "Fixed inspectable rules; no training or calibrated class probabilities",
            "Confusion rows are physical labels, columns are evidence classes; wall/frame are not separated",
            "Unmapped events are separately counted; missing timing retains reference misses",
            "Trigger/cooldown performance is not full goal recall; sensors never confirm or veto goals"])


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest",type=Path)
    parser.add_argument("--split",choices=["train","validation","blind_test"],default="validation")
    parser.add_argument("--allow-blind-test",action="store_true")
    parser.add_argument("--max-packets",type=int,default=100000)
    parser.add_argument("--max-samples",type=int,default=2000000)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=replay(args.manifest,args.split,args.allow_blind_test,args.max_packets,args.max_samples)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(f"Replayed {result['packet_count']} packets/{result['sample_count']} samples; {result['counts']['events']} evidence events")
