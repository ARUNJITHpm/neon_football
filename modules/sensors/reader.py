"""Reconnectable byte-source worker with bounded packet queue; injectable for bench tests."""
from queue import Empty, Full, Queue
from threading import Event, Thread
from time import monotonic
from .protocol import PacketDecoder


class SensorReader:
    def __init__(self, open_source, capacity=8, reconnect_seconds=.25, clock=monotonic, raw_sink=None):
        if not 1 <= capacity <= 128 or reconnect_seconds <= 0:
            raise ValueError("Invalid serial queue/reconnect settings")
        self.open_source, self.clock, self.raw_sink = open_source, clock, raw_sink
        self.reconnect_seconds = reconnect_seconds
        self.queue, self.stop_event = Queue(capacity), Event()
        self.decoder, self.thread, self.source = PacketDecoder(), None, None
        self.health = dict(state="stopped", opens=0, disconnects=0, queue_drops=0, last_packet_receipt=None, error=None)

    def start(self):
        if self.thread and self.thread.is_alive():
            raise RuntimeError("Reader already running")
        self.stop_event.clear()
        self.thread = Thread(target=self._run, daemon=True, name="sensor-reader")
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.source = self.open_source()  # Source must implement read(size), close(), bounded read timeout.
                self.health.update(state="connected", error=None)
                self.health["opens"] += 1
                while not self.stop_event.is_set():
                    chunk = self.source.read(4096)
                    if not chunk:  # A serial timeout is not EOF/disconnect; freshness is checked by SensorHost.
                        self.stop_event.wait(.005)
                        continue
                    now = self.clock()
                    if self.raw_sink:
                        self.raw_sink(chunk, now)
                    for packet in self.decoder.feed(chunk):
                        while True:
                            try:
                                self.queue.put_nowait((packet, now, self.health["opens"]))
                                break
                            except Full:
                                try:
                                    self.queue.get_nowait()
                                except Empty:
                                    continue
                                self.health["queue_drops"] += 1
                        self.health["last_packet_receipt"] = now
            except (OSError, ValueError) as error:
                self.health.update(state="disconnected", error=type(error).__name__)
                self.health["disconnects"] += 1
            finally:
                if self.source:
                    try:
                        self.source.close()
                    except OSError:
                        pass
                self.source = None
                self.decoder.reset()
                # Never stitch queued pre-disconnect packets into a new acquisition epoch.
                while True:
                    try:
                        self.queue.get_nowait()
                    except Empty:
                        break
            self.stop_event.wait(self.reconnect_seconds)
        self.health["state"] = "stopped"

    def stop(self):
        self.stop_event.set()
        if self.source:
            try:
                self.source.close()
            except OSError:
                pass
        if self.thread:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                raise RuntimeError("Sensor source did not honor its bounded read timeout/close")
