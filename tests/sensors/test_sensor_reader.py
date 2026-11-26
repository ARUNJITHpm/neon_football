from collections import deque
from threading import Event
from time import monotonic,sleep
from modules.sensors.protocol import encode
from modules.sensors.reader import SensorReader


def wait_until(predicate):
    deadline=monotonic()+2
    while not predicate():
        assert monotonic()<deadline,"Reader condition timed out"
        sleep(.005)


class Port:
    def __init__(self,items): self.items=deque(items); self.closed=Event()
    def read(self,size):
        if self.closed.is_set(): raise OSError("closed")
        if not self.items: self.closed.wait(.01); return b""
        item=self.items.popleft()
        if isinstance(item,Exception): raise item
        assert len(item)<=size
        return item
    def close(self): self.closed.set()


def test_reader_reconnect_partial_reset_and_bounded_queue(packet_factory):
    wire=encode(packet_factory())
    first=Port([wire[:20],OSError("disconnect")])
    second=Port([encode(packet_factory(packet_sequence=i,first_sample_sequence=i*32,first_device_us=i*40000)) for i in range(10)])
    ports=deque([first,second]); retained=[]
    reader=SensorReader(lambda:ports.popleft(),capacity=2,reconnect_seconds=.01,raw_sink=lambda data,time:retained.append(data))
    reader.start()
    try:
        wait_until(lambda:reader.health["queue_drops"]>=8)
        assert reader.health["opens"]==2 and reader.health["disconnects"]==1
        assert reader.decoder.counters["truncated_on_disconnect"]==1
        latest=[reader.queue.get_nowait(),reader.queue.get_nowait()]
        assert [item[0].packet_sequence for item in latest]==[8,9] and all(item[2]==2 for item in latest)
        assert retained[0]==wire[:20] and len(retained)==11
    finally: reader.stop()
    assert not reader.thread.is_alive() and first.closed.is_set() and second.closed.is_set()


def test_one_bad_source_does_not_stop_other_reader(packet_factory):
    good_port=Port([encode(packet_factory())])
    good=SensorReader(lambda:good_port)
    def missing(): raise OSError("device absent")
    bad=SensorReader(missing,reconnect_seconds=.02)
    good.start();bad.start()
    try:
        wait_until(lambda:good.health["last_packet_receipt"] is not None and bad.health["disconnects"]>=2)
        assert good.health["state"]=="connected" and good.queue.get_nowait()[0].device_id==1
    finally: good.stop();bad.stop()
