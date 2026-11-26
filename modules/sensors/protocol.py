"""Little-endian NFSP v1, bounded CRC-framed raw accelerometer packets."""
import struct
import zlib
from core.sensors import SensorPacket

MAGIC = b"NFSP"
HEADER = struct.Struct("<BBBBHIQIQQHHI")
XYZ = struct.Struct("<hhh")
MAX_PAYLOAD = HEADER.size+32*XYZ.size
FIFO_OVERRUN, SENSOR_MISSING, SATURATED, TX_OVERFLOW, TIMESTAMP_ESTIMATED, SENSOR_RESTART, SELF_TEST_FAILED = (1, 2, 4, 8, 16, 32, 64)
FLAG_NAMES = {1: "fifo_overrun", 2: "sensor_missing", 4: "saturated", 8: "tx_overflow", 16: "timestamp_estimated", 32: "sensor_restart", 64: "self_test_failed"}


def encode(packet):
    packet = SensorPacket.model_validate(packet.model_dump())
    body = HEADER.pack(1, 1 if packet.kind == "samples" else 2, 0 if packet.goal_end == "goal_a" else 1,
        0 if packet.role == "net" else 1, packet.flags, packet.device_id, packet.boot_id, packet.packet_sequence,
        packet.first_sample_sequence, packet.first_device_us, 1250, len(packet.samples), packet.timestamp_uncertainty_us)
    body += b"".join(XYZ.pack(*sample) for sample in packet.samples)
    checked = struct.pack("<H", len(body))+body
    return MAGIC+checked+struct.pack("<I", zlib.crc32(checked))


def decode(body):
    if len(body) < HEADER.size:
        raise ValueError("Truncated sensor header")
    version, kind, end, role, flags, device, boot, seq, first, time_us, period, count, uncertainty = HEADER.unpack_from(body)
    if version != 1 or kind not in (1, 2) or end not in (0, 1) or role not in (0, 1) or period != 1250 or count > 32 or len(body) != HEADER.size+count*6:
        raise ValueError("Unsupported protocol/layout/ODR/count")
    return SensorPacket(kind="samples" if kind == 1 else "health", goal_end="goal_a" if end == 0 else "goal_b",
        role="net" if role == 0 else "frame", flags=flags, device_id=device, boot_id=boot, packet_sequence=seq,
        first_sample_sequence=first, first_device_us=time_us, timestamp_uncertainty_us=uncertainty,
        samples=[XYZ.unpack_from(body, HEADER.size+i*6) for i in range(count)])


class PacketDecoder:
    def __init__(self):
        self.buffer = bytearray()
        self.counters = dict(bytes_discarded=0, crc_errors=0, layout_errors=0, packets=0, truncated_on_disconnect=0)

    def reset(self):
        if self.buffer:
            self.counters["truncated_on_disconnect"] += 1
            self.buffer.clear()

    def feed(self, chunk):
        if len(chunk) > 4096:
            raise ValueError("Read chunks must be bounded to 4096 bytes")
        self.buffer.extend(chunk)
        packets = []
        while True:
            index = self.buffer.find(MAGIC)
            if index < 0:
                discard = max(0, len(self.buffer)-3)
                self.counters["bytes_discarded"] += discard
                del self.buffer[:discard]
                break
            if index:
                self.counters["bytes_discarded"] += index
                del self.buffer[:index]
            if len(self.buffer) < 6:
                break
            size = struct.unpack_from("<H", self.buffer, 4)[0]
            if not HEADER.size <= size <= MAX_PAYLOAD:
                self.counters["layout_errors"] += 1
                del self.buffer[0]
                continue
            if len(self.buffer) < size+10:
                break
            checked = bytes(self.buffer[4:6+size])
            crc = struct.unpack_from("<I", self.buffer, 6+size)[0]
            if zlib.crc32(checked) != crc:
                self.counters["crc_errors"] += 1
                del self.buffer[0]
                continue
            body = bytes(self.buffer[6:6+size])
            del self.buffer[:size+10]
            try:
                packets.append(decode(body))
            except ValueError:
                self.counters["layout_errors"] += 1
            else:
                self.counters["packets"] += 1
        return packets
