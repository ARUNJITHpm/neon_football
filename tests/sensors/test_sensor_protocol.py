import random
import struct
import zlib
import pytest
from pydantic import ValidationError
from core.sensors import SensorPacket
from modules.sensors.protocol import HEADER, MAX_PAYLOAD, PacketDecoder, decode, encode


def packet(**changes):
    values=dict(kind="samples",goal_end="goal_a",role="net",device_id=1,boot_id=100,packet_sequence=0,
        first_sample_sequence=0,first_device_us=0,samples=[(-4096,0,4095)]*32)
    values.update(changes)
    return SensorPacket(**values)


def test_golden_little_endian_crc_and_fragmented_roundtrip():
    p=packet()
    wire=encode(p)
    assert HEADER.size==46 and MAX_PAYLOAD==238 and len(wire)==248
    assert wire[:10]==b"NFSP\xee\x00\x01\x01\x00\x00"
    assert struct.unpack_from("<I",wire,12)[0]==1
    assert struct.unpack_from("<Q",wire,16)[0]==100
    assert struct.unpack_from("<I",wire,len(wire)-4)[0]==zlib.crc32(wire[4:-4])
    for chunk_size in (1,3,7,45,248):
        decoder=PacketDecoder(); results=[]
        for start in range(0,len(wire),chunk_size):
            results += decoder.feed(wire[start:start+chunk_size])
        assert results==[p] and not decoder.buffer


def test_crc_layout_noise_resync_and_bounded_memory():
    wire=encode(packet()); damaged=bytearray(wire); damaged[70]^=1
    bad_length=b"NFSP"+struct.pack("<H",65535)
    decoder=PacketDecoder()
    assert decoder.feed(b"noise-NF"+bad_length+damaged+wire)==[packet()]
    assert decoder.counters["crc_errors"]==1 and decoder.counters["layout_errors"]>=1
    randomizer=random.Random(15)
    for _ in range(50):
        decoder.feed(randomizer.randbytes(4096))
        assert len(decoder.buffer)<=MAX_PAYLOAD+10
    with pytest.raises(ValueError,match="bounded"):
        decoder.feed(b"x"*4097)
    decoder.feed(wire[:30]); decoder.reset()
    assert decoder.counters["truncated_on_disconnect"]==1 and not decoder.buffer


@pytest.mark.parametrize("bad", [dict(rate_hz=1000),dict(samples=[]),dict(samples=[(5000,0,0)]),dict(flags=128),dict(first_sample_sequence=2**64-2)])
def test_packet_contract_rejects_unknown_odr_and_counter_wrap(bad):
    with pytest.raises(ValidationError):
        packet(**bad)


def test_unknown_version_or_body_count_rejected_even_with_valid_crc():
    body=bytearray(encode(packet())[6:-4]); body[0]=2
    with pytest.raises(ValueError,match="Unsupported"):
        decode(body)
    checked=struct.pack("<H",len(body))+body
    decoder=PacketDecoder()
    assert decoder.feed(b"NFSP"+checked+struct.pack("<I",zlib.crc32(checked)))==[]
    assert decoder.counters["layout_errors"]==1
    health=packet(kind="health",samples=[])
    assert PacketDecoder().feed(encode(health))==[health]
