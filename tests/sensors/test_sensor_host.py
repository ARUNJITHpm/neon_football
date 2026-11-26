import pytest
from core.sensors import SensorAlignment, SensorSettings
from modules.sensors.host import SensorHost


def test_alignment_sequence_units_and_saturation(aligned_host,packet_factory):
    packet=packet_factory(samples=[(4000,0,256)]*32)
    samples=aligned_host.process(packet,.05)
    assert samples[-1].aligned_seconds==pytest.approx(.03875*1.0001)
    assert samples[-1].timing_uncertainty_seconds==pytest.approx(.001+.00125*1.0001)
    assert samples[0].xyz_g==(15.6,0,.9984) and "saturated" in samples[0].flags
    assert aligned_host.counters["saturated_samples"]==32
    assert aligned_host.health(.06)[0]["state"]=="degraded"


def test_packet_and_sample_loss_duplicates_and_retired_boot(aligned_host,packet_factory):
    aligned_host.process(packet_factory(),.05)
    assert aligned_host.process(packet_factory(),.06)==[]
    p=packet_factory(packet_sequence=2,first_sample_sequence=64,first_device_us=80000)
    result=aligned_host.process(p,.13)
    assert {"packet_gap","sample_gap"}<=set(result[0].flags)
    assert aligned_host.counters["missing_packets"]==1 and aligned_host.counters["missing_samples"]==32
    result=aligned_host.process(packet_factory(boot_id=101),.2)
    assert "boot_reset" in result[0].flags and result[0].aligned_seconds is None
    assert aligned_host.process(p,.3)==[] and aligned_host.counters["retired_boot_packets"]==1


def test_clock_regression_quarantines_boot_even_after_reconnect(aligned_host,packet_factory):
    aligned_host.process(packet_factory(),.05)
    regression=packet_factory(packet_sequence=1,first_sample_sequence=32,first_device_us=20000)
    assert aligned_host.process(regression,.08)==[]
    newer=packet_factory(packet_sequence=2,first_sample_sequence=64,first_device_us=80000)
    assert aligned_host.process(newer,.13,transport_epoch=1)==[]
    assert "clock_reset_requires_new_boot" in aligned_host.health(.14)[0]["flags"]
    assert aligned_host.process(packet_factory(boot_id=101),.2)


def test_heartbeat_does_not_hide_missing_samples(aligned_host,packet_factory):
    aligned_host.process(packet_factory(),.05)
    assert aligned_host.process(packet_factory(kind="health",samples=[],packet_sequence=1,first_sample_sequence=32,first_device_us=300000),.3)==[]
    health=aligned_host.health(.5)[0]
    assert health["state"]=="stale" and health["last_sample_receipt"]==.05


def test_mapping_expiry_delay_future_and_wrong_identity(packet_factory,alignment):
    alignment.valid_to_device_seconds=.02
    host=SensorHost(SensorSettings(),{1:"goal_a"},[alignment],"test-host","synthetic")
    result=host.process(packet_factory(),.5)
    assert "stale_delivery" in result[0].flags and result[-1].aligned_seconds is None
    assert "alignment_unavailable_or_expired" in result[-1].flags
    future=SensorHost(SensorSettings(),{1:"goal_a"},[alignment],"test-host","synthetic")
    assert "mapping_in_future" in future.process(packet_factory(),0)[10].flags
    with pytest.raises(ValueError,match="Unknown device"):
        future.process(packet_factory(goal_end="goal_b"),.1)
    with pytest.raises(ValueError,match="Synthetic"):
        SensorHost(SensorSettings(),{1:"goal_a"},[alignment],"test-host","venue")


def test_transport_epoch_drops_queued_old_connection(aligned_host,packet_factory):
    aligned_host.process(packet_factory(),.05,1)
    p=packet_factory(packet_sequence=1,first_sample_sequence=32,first_device_us=40000)
    assert aligned_host.process(p,.1,2)[0].transport_epoch==2
    assert aligned_host.process(p,.2,1)==[]
    assert aligned_host.counters["transport_resets"]==1
