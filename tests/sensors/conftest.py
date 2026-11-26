import pytest
from core.sensors import SensorAlignment, SensorPacket, SensorSettings
from modules.sensors.host import SensorHost


@pytest.fixture
def packet_factory():
    def create(**changes):
        values=dict(kind="samples",goal_end="goal_a",role="net",device_id=1,boot_id=100,packet_sequence=0,
                    first_sample_sequence=0,first_device_us=0,samples=[(0,0,256)]*32)
        values.update(changes)
        return SensorPacket(**values)
    return create


@pytest.fixture
def alignment():
    return SensorAlignment(version="test-alignment",device_id=1,boot_id=100,host_clock_domain="test-host",evidence="synthetic",
        source_origin_seconds=0,host_origin_seconds=0,scale=1.0001,uncertainty_seconds=.001,
        valid_from_device_seconds=0,valid_to_device_seconds=100)


@pytest.fixture
def aligned_host(alignment):
    return SensorHost(SensorSettings(),{1:"goal_a"},[alignment],"test-host","synthetic")
