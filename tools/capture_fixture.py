"""Generate two test videos and benchmark the actual capture/clip pipeline."""
import argparse
import ctypes
import os
import json
from pathlib import Path
import subprocess
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.capture import CameraConfig, CaptureSettings, ClipRequest
from modules.capture.manager import CaptureManager


def memory_bytes(manager):
    """Process working set, including owned FFmpeg children where available."""
    if os.name != "nt":
        return None
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    handles = [kernel.GetCurrentProcess()]
    for worker in manager.workers.values():
        with worker.lock:
            if worker.reader:
                handles.append(int(worker.reader.process._handle))
    total = 0
    for handle in handles:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        total += counters.WorkingSetSize
    return total


def generate(path: Path, ffmpeg="ffmpeg", seconds=6, fps=15, size="320x180", pattern="testsrc2"):
    path.parent.mkdir(parents=True, exist_ok=True)
    # No overwrite flag: an existing recording must never be replaced by a fixture.
    subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"{pattern}=size={size}:rate={fps}", "-t", str(seconds), "-c:v", "ffv1", "-threads", "1", str(path)],
                   capture_output=True, check=True, timeout=60)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("local_scratch/capture-fixture"))
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--seconds", type=float, default=8)
    parser.add_argument("--fps", type=float, default=15)
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=180)
    args = parser.parse_args()
    if args.seconds < 4:
        parser.error("--seconds must be at least four for the pre/post test")
    run = args.root / time.strftime("%Y%m%d-%H%M%S")
    run.mkdir(parents=True, exist_ok=False)
    cameras = []
    for name, pattern in [("goal-a", "testsrc2"), ("goal-b", "testsrc")]:
        path = run / f"{name}.mkv"
        generate(path, args.ffmpeg, args.seconds, args.fps, f"{args.width}x{args.height}", pattern)
        cameras.append(CameraConfig(id=name, source=str(path), width=args.width, height=args.height,
                                    expected_fps=args.fps, realtime=True, reconnect=False))
    settings = CaptureSettings(enabled=True, root=str(run / "recordings"), ffmpeg=args.ffmpeg,
                               min_free_bytes=0, clip_pre_seconds=1, clip_post_seconds=1, segment_seconds=3)
    manager = CaptureManager(cameras, settings)
    peak_memory = 0
    try:
        manager.start()
        deadline = time.monotonic() + args.seconds + 15
        requested = False
        while time.monotonic() < deadline:
            statuses = manager.status()["cameras"]
            measured = memory_bytes(manager)
            peak_memory = max(peak_memory, measured or 0)
            if not requested and all(s["frames"] >= args.fps * 2 for s in statuses):
                for camera in cameras:
                    manager.request_clip(ClipRequest(camera_id=camera.id, clip_id=f"fixture-{camera.id}"))
                requested = True
            if all(s["health"] == "disconnected" for s in statuses):
                break
            time.sleep(0.05)
        if not requested:
            raise RuntimeError("Fixture capture did not produce enough frames")
    finally:
        manager.close()
    result = manager.status()
    result["clips"] = [manager.clip_status(f"fixture-{c.id}") for c in cameras]
    result["fixture_only"] = True
    result["peak_sampled_python_plus_ffmpeg_working_set_bytes"] = peak_memory or None
    result["memory_sample_interval_seconds"] = 0.05
    result["expected_frames_per_camera"] = round(args.seconds * args.fps)
    (run / "benchmark.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"benchmark": str(run / "benchmark.json"), "manifest": str(manager.root / "manifest.json"),
                      "frames": [s["frames"] for s in result["cameras"]], "clips": [c["status"] for c in result["clips"]]}))


if __name__ == "__main__":
    main()
