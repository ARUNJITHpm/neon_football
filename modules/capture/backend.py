"""One supervised FFmpeg subprocess per camera, emitting JPEG plus showinfo PTS."""
from dataclasses import dataclass
import math
import os
import queue
import re
import subprocess
from threading import Thread

from core.capture import CameraConfig, CaptureSettings


INFO = re.compile(r"\bn:\s*(\d+).*?pts_time:\s*([-+\deE.]+).*?\bs:(\d+)x(\d+)")


@dataclass(frozen=True)
class Packet:
    jpeg: bytes
    source_sequence: int
    source_seconds: float | None
    width: int
    height: int


def read_jpeg(stream, max_bytes: int) -> bytes | None:
    """Parse JPEG marker lengths; FF D9 inside a metadata segment is not EOI."""
    def exact(count):
        data = bytearray()
        while len(data) < count:
            piece = stream.read(count - len(data))
            if not piece:
                raise EOFError("Truncated JPEG frame")
            data.extend(piece)
        return bytes(data)
    first = stream.read(2)
    if not first:
        return None
    if first != b"\xff\xd8":
        raise ValueError("Invalid JPEG stream start")
    data = bytearray(first)
    entropy = False
    while True:
        if len(data) > max_bytes:
            raise ValueError("Frame exceeds configured byte limit")
        if entropy and hasattr(stream, "peek"):
            available = stream.peek(65536)
            if not available:
                raise EOFError("Truncated JPEG entropy data")
            marker_at = available.find(b"\xff")
            count = marker_at + 1 if marker_at >= 0 else len(available)
            if len(data) + count > max_bytes:
                raise ValueError("Frame exceeds configured byte limit")
            chunk = exact(count)
            data.extend(chunk[:-1])
            byte = chunk[-1:]
        else:
            byte = exact(1)
        data.extend(byte)
        if byte != b"\xff":
            if not entropy:
                raise ValueError("Invalid JPEG marker")
            continue
        marker = exact(1)
        data.extend(marker)
        while marker == b"\xff":
            marker = exact(1)
            data.extend(marker)
        code = marker[0]
        if code == 0xD9:
            if len(data) > max_bytes:
                raise ValueError("Frame exceeds configured byte limit")
            return bytes(data)
        if code == 0 or 0xD0 <= code <= 0xD7:
            if not entropy:
                raise ValueError("Unexpected JPEG entropy marker")
            continue
        if code in (0xD8, 0x01):
            raise ValueError("Unexpected standalone JPEG marker")
        length = exact(2)
        size = int.from_bytes(length, "big")
        if size < 2 or len(data) + size > max_bytes:
            raise ValueError("Invalid or oversized JPEG segment")
        data.extend(length)
        data.extend(exact(size - 2))
        if code == 0xDA:
            entropy = True


def command(config: CameraConfig, settings: CaptureSettings):
    source = config.source if config.source is not None else os.environ.get(config.source_env)
    if not source:
        raise ValueError("Camera input environment variable is missing")
    args = [settings.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "info", "-copyts"]
    if config.kind == "file" and config.realtime:
        args += ["-re"]
    elif config.kind == "rtsp":
        args += ["-rtsp_transport", "tcp", "-rw_timeout", "5000000"]
    elif config.kind in ("dshow", "v4l2"):
        args += ["-f", config.kind, "-framerate", str(config.expected_fps),
                 "-video_size", f"{config.width}x{config.height}"]
        if config.kind == "dshow" and not source.startswith("video="):
            source = "video=" + source
    args += ["-i", source, "-map", "0:v:0", "-an", "-sn", "-dn",
             "-vf", "showinfo", "-fps_mode", "passthrough",
             "-c:v", "mjpeg", "-q:v", str(settings.jpeg_quality), "-threads", "1", "-f", "image2pipe", "pipe:1"]
    return args


class FFmpegReader:
    def __init__(self, config: CameraConfig, settings: CaptureSettings):
        self.config = config
        self.settings = settings
        self.metadata = queue.Queue(maxsize=256)
        self.metadata_overflow = False
        self.sequence = 0
        self.process = subprocess.Popen(command(config, settings), stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1024 * 1024,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self._stderr = Thread(target=self._read_metadata, daemon=True, name=f"pts-{config.id}")
        self._stderr.start()

    def _read_metadata(self):
        for line in iter(self.process.stderr.readline, b""):
            match = INFO.search(line.decode("utf-8", errors="replace"))
            if match:
                n, pts, width, height = match.groups()
                pts = float(pts)
                try:
                    self.metadata.put_nowait((int(n), pts if math.isfinite(pts) else None, int(width), int(height)))
                except queue.Full:
                    self.metadata_overflow = True
        # Raw stderr is discarded: it can contain credential-bearing camera URLs.

    def read(self) -> Packet | None:
        jpeg = read_jpeg(self.process.stdout, self.settings.max_frame_bytes)
        if jpeg is None:
            return None
        if self.metadata_overflow:
            raise ValueError("Timestamp metadata overflow; frame correspondence is unsafe")
        try:
            n, pts, width, height = self.metadata.get(timeout=2)
        except queue.Empty:
            raise ValueError("Frame has no corresponding source timestamp metadata") from None
        if n != self.sequence:
            raise ValueError("Frame/timestamp sequence mismatch")
        self.sequence += 1
        return Packet(jpeg, n, pts, width, height)

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self._stderr.join(timeout=2)
        # The stdout owner finishes its read before closing the file handle.

    def release(self):
        self.close()
        self.process.stdout.close()
        self.process.stderr.close()
