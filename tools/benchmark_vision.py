"""Two-worker offline JPEG decode + ONNX + net-motion profile; never live-capacity acceptance."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import sys
from threading import Barrier
from time import perf_counter

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
import numpy
import onnxruntime
from core.capture import RecordingManifest, TimingEnvelope
from core.dataset import relative_path
from core.vision import ModelDescriptor, VisionSettings
from modules.replay.dataset import asset_path, digest
from modules.replay.statistics import distribution
from modules.vision.detector import OnnxDetector
from modules.vision.motion import NetMotion


def benchmark(capture, descriptor_path, settings_path, max_frames=75):
    if not 1 <= max_frames <= 20000:
        raise ValueError("Benchmark frame cap must be 1..20000 per feed")
    capture, descriptor_path, settings_path = map(Path, (capture, descriptor_path, settings_path))
    manifest_path = capture / "manifest.json"
    manifest = RecordingManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    settings = VisionSettings.model_validate_json(settings_path.read_text(encoding="utf-8"))
    descriptor = ModelDescriptor.model_validate_json(descriptor_path.read_text(encoding="utf-8"))
    if manifest.status != "closed" or len(manifest.cameras) != 2:
        raise ValueError("Use a cleanly closed two-camera recording")
    inputs, inventory = [], {}
    for camera in manifest.cameras:
        view = next((v for v in settings.views if v.camera_id == camera.camera_id), None)
        if view is None or (view.calibration.width, view.calibration.height) != (camera.width, camera.height):
            raise ValueError("Camera/motion ROI resolution differs from benchmark settings")
        rows = []
        seen = set()
        for segment in camera.segments:
            if not segment.complete:
                raise ValueError("Partial recording segment")
            for relative, expected in [(segment.path, segment.sha256), (segment.index_path, segment.index_sha256)]:
                relative_path(relative)
                if digest(asset_path(capture, relative)) != expected:
                    raise ValueError("Recording checksum differs")
                inputs.append(dict(path=relative, sha256=expected))
            position, local = 0, []
            for line in asset_path(capture, segment.index_path).read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                timing = TimingEnvelope.model_validate(row["timing"])
                if (row["camera_id"] != camera.camera_id or timing.source_id != camera.camera_id or
                    timing.host_clock_domain != manifest.host_clock_domain or timing.boot_id != segment.boot_id or
                    row["byte_offset"] != position or not 0 < row["byte_length"] <= 16*1024*1024 or timing.sequence in seen):
                    raise ValueError("Invalid recording index identity/bytes")
                seen.add(timing.sequence)
                position += row["byte_length"]
                local.append((segment.path, row))
            if len(local) != segment.frames or position != segment.bytes or position != asset_path(capture, segment.path).stat().st_size:
                raise ValueError("Recording frame/byte counts differ")
            rows.extend(local)
        inventory[camera.camera_id] = (camera, view, rows[:max_frames])
        if not rows:
            raise ValueError("Empty camera recording")
    barrier = Barrier(2)

    def worker(camera_id):
        camera, view, rows = inventory[camera_id]
        model_start = perf_counter()
        detector = OnnxDetector(descriptor, descriptor_path.parent)
        model_load_seconds = perf_counter()-model_start
        motion = NetMotion(view.calibration.net_roi, (camera.width, camera.height))
        barrier.wait(timeout=30)
        start = perf_counter()
        timings, detections_count, motion_counts = [], 0, {}
        for relative, row in rows:
            frame_start = perf_counter()
            with asset_path(capture, relative).open("rb") as handle:
                handle.seek(row["byte_offset"])
                jpeg = handle.read(row["byte_length"])
            loaded = perf_counter()
            with Image.open(BytesIO(jpeg)) as source:
                source.load()
                image = source.convert("RGB")
            if image.size != (camera.width, camera.height):
                raise ValueError("Decoded image differs from recording metadata")
            decoded = perf_counter()
            detections, profile = detector.detect(image)
            inferred = perf_counter()
            cue = motion.update(image, detections)
            end = perf_counter()
            for flag in cue.flags:
                motion_counts[flag] = motion_counts.get(flag, 0)+1
            detections_count += len(detections)
            timings.append(dict(read_seconds=loaded-frame_start, decode_seconds=decoded-loaded, **profile,
                motion_seconds=end-inferred, pipeline_seconds=end-frame_start))
        elapsed = perf_counter()-start
        return dict(camera_id=camera_id, frames=len(rows), offline_frames_per_second=len(rows)/elapsed,
            elapsed_seconds=elapsed, model_load_seconds=model_load_seconds, raw_detections=detections_count,
            source_expected_fps=camera.expected_fps, timings={key: distribution([r[key] for r in timings]) for key in timings[0]},
            motion_quality_counts=motion_counts, live_queue_age_seconds=None, live_dropped_frames=None)

    start = perf_counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, camera.camera_id) for camera in manifest.cameras]
        streams = [future.result() for future in futures]
    elapsed = perf_counter()-start
    return dict(schema_version=1, benchmark="offline-two-worker-vision-v1", session_id=manifest.session_id,
        recording_manifest_sha256=digest(manifest_path), settings_sha256=digest(settings_path), model=descriptor.model_dump(mode="json"),
        hardware=dict(platform=platform.platform(), python=platform.python_version(), logical_cpus=os.cpu_count(),
            cpu=os.environ.get("PROCESSOR_IDENTIFIER", platform.processor()), provider="CPUExecutionProvider"),
        packages=dict(numpy=numpy.__version__, Pillow=Image.__version__, onnxruntime=onnxruntime.__version__),
        inputs=inputs, streams=streams, wall_seconds_including_model_load_and_motion_setup=elapsed,
        aggregate_offline_frames_per_second=sum(s["frames"] for s in streams)/elapsed,
        field_capacity_passed=False, detector_accuracy_measured=False,
        limitations=["File replay, no live capture contention or bounded live queue",
            "Short run includes filesystem caching; no sustained temperature/RAM measurement",
            "Model purpose and source recorded; Constant fixture ignores image pixels",
            "Net ROI settings may be synthetic; no field geometry/lighting acceptance"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--max-frames", type=int, default=75)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = benchmark(args.capture, args.model, args.settings, args.max_frames)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(f"Processed {sum(s['frames'] for s in result['streams'])} frames on two offline workers; live gate pending")
