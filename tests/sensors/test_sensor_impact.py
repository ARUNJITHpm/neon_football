from pathlib import Path
import json
import pytest
from core.sensors import SensorDataset, SensorSettings
from modules.sensors.impact import ImpactEngine
from tools.sensor_replay import replay
from tools.check_sensor_sync import evaluate

ROOT=Path(__file__).parent/"fixtures"


def test_dummy_replay_is_deterministic_quality_failures_and_post_in():
    a=replay(ROOT/"dataset.json"); b=replay(ROOT/"dataset.json")
    assert json.dumps(a,sort_keys=True)==json.dumps(b,sort_keys=True)
    assert a["packet_count"]==998 and a["sample_count"]==31936
    assert a["counts"]==dict(impact_labels=8,detected_labelled_impacts=7,misses=1,events=8,unknown=3,unmapped=1,false_impacts=0,noise_labels=1)
    session=a["sessions"][0]
    assert session["decoder"]["crc_errors"]==1 and session["host"]["missing_samples"]==64
    assert session["host"]["reboots"]==1 and session["transport"]["disconnects"]==1
    post=[e for e in session["impacts"] if e["classification"]=="mixed_impact"][0]
    assert post["possible_goal"] and not post["automatic_confirmation_allowed"]
    assert all(e["possible_goal"] for e in session["impacts"])
    assert {"saturated","fifo_overrun","alignment_unavailable_or_expired"}<= {f for e in session["impacts"] for f in e["flags"]}
    assert a["latency_seconds"]["maximum"] < .2
    assert not a["release_qualified"] and not a["firmware_compiled"] and not a["hardware_tested"]


def test_holdout_markers_drift_and_reset_guard():
    data=json.loads((ROOT/"sync-markers.json").read_text())
    result=evaluate(data)
    assert result["groups"][1]["drift_ppm"]==pytest.approx(100)
    assert result["groups"][1]["maximum_validation_bound_ms"]==pytest.approx(1)
    assert result["timing_target_met"] and not result["field_verified"]
    data["groups"][0]["markers"][-1]["device_seconds"]=1
    with pytest.raises(ValueError,match="Reset"):
        evaluate(data)
    data=json.loads((ROOT/"sync-markers.json").read_text())
    data["groups"][0]["markers"][-1]["host_seconds"]=float("nan")
    with pytest.raises(ValueError,match="finite"):
        evaluate(data)


def test_sensor_split_leak_and_incident_reuse():
    base=json.loads((ROOT/"dataset.json").read_text())
    for kind in ("group","raw","incident"):
        data=json.loads(json.dumps(base))
        if kind=="group": data["sessions"][1]["source_group_id"]=data["sessions"][0]["source_group_id"]
        elif kind=="raw": data["sessions"][1]["raw"]=data["sessions"][0]["raw"]
        else: data["sessions"][1]["labels"][0]["incident_id"]=data["sessions"][0]["labels"][0]["incident_id"]
        with pytest.raises(ValueError): SensorDataset.model_validate(data)


def test_impact_waits_for_future_samples_and_invalidates_pending(aligned_host,packet_factory):
    engine=ImpactEngine(SensorSettings())
    for start in range(0,800,32):
        for role in ("net","frame"):
            xyz=[(0,0,256)]*32
            if start==416 and role=="net": xyz=[(300,0,256)]*32
            packet=packet_factory(role=role,packet_sequence=start//32,first_sample_sequence=start,first_device_us=start*1250,samples=xyz)
            events=engine.ingest(aligned_host.process(packet,(start+31)/800+.01))
            if 416<=start<480: assert not events
            if start==448 and role=="frame":
                assert engine.units[1].pending is not None
                engine.invalidate(1)
                assert engine.counters["cancelled_windows"]==1
                return
    raise AssertionError("Did not establish a pending window")


def test_bad_baseline_reports_loose_sensor_then_recovers(aligned_host,packet_factory):
    engine=ImpactEngine(SensorSettings())
    for start in range(0,800,32):
        for role in ("net","frame"):
            xyz=[((200 if i%2 else -200) if start<320 else 0,0,256) for i in range(32)]
            packet=packet_factory(role=role,packet_sequence=start//32,first_sample_sequence=start,first_device_us=start*1250,samples=xyz)
            engine.ingest(aligned_host.process(packet,(start+31)/800+.01))
        if start==288:
            report=engine.baseline_report()[0]
            assert not report["ready"] and "baseline_unstable_or_loose" in report["sensors"]["net"]["flags"]
    assert engine.baseline_report()[0]["ready"]


def test_replay_blind_guard_cap_and_checksum(tmp_path):
    with pytest.raises(ValueError,match="Blind-test"):
        replay(ROOT/"dataset.json","blind_test")
    with pytest.raises(ValueError,match="capacity"):
        replay(ROOT/"dataset.json",max_packets=5)
    data=json.loads((ROOT/"dataset.json").read_text())
    data["sessions"][1]["raw"]["sha256"]="f"*64
    manifest=tmp_path/"dataset.json"; manifest.write_text(json.dumps(data))
    # Use a symlink-free absolute asset root by copying only the selected files.
    for name in ("validation.nfsp","validation-receipts.jsonl"):
        (tmp_path/name).write_bytes((ROOT/name).read_bytes())
    with pytest.raises(ValueError,match="checksum"):
        replay(manifest)
