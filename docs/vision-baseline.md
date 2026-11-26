# Part 04 software evidence

Date: 11 October 2026. Offline candidate logic and the local ONNX adapter are implemented. **Venue detector accuracy, training, depth reconstruction and live two-camera capacity remain pending.** Automatic scoring remains disabled. No new football video was created; image benchmarks reused Part 02's generated test-pattern recordings.

## Validation

```powershell
.venv/Scripts/python.exe -m pytest --basetemp local_scratch/pytest-part04-final -p no:cacheprovider --tb=short
.venv/Scripts/python.exe tools/export_vision_schemas.py --check
.venv/Scripts/python.exe tools/export_dataset_schemas.py --check
.venv/Scripts/python.exe tools/vision_replay.py tests/vision/fixtures/replay/dataset.json --settings tests/vision/fixtures/replay/settings.json --annotations tests/vision/fixtures/replay/annotations.json --output local_scratch/part04-proof-a.json
.venv/Scripts/python.exe tools/vision_replay.py tests/vision/fixtures/replay/dataset.json --settings tests/vision/fixtures/replay/settings.json --annotations tests/vision/fixtures/replay/annotations.json --output local_scratch/part04-proof-b.json
.venv/Scripts/python.exe local_scratch/verify_part04.py
```

**94 tests passed in 16.72 seconds**, including the previous 59 and 35 new vision checks. New tests cover real ONNX execution of a constant graph, reverse letterboxing/NMS, model hash/input/layout/licence errors, nonfinite outputs/logits, partial/outward/outside crossings, observed versus predicted evidence, uncertainty at the posts, source resets, stale frames, bad calibration, front-sample quality propagation, safe media/evidence contracts, net warmup/player/global motion, deterministic replay, frame limits, split leakage and duplicate/wrong-end candidate penalties. Existing scoring/API/capture/replay tests remain green.

Two CLI replays were byte-identical: SHA-256 `ae702c8fd57ae0074fdaef6b14971232a704c4dcb32c9c2e7bceae3649eeeed1`. [Baseline JSON](vision-baseline.json) includes hashes for every input and relevant implementation file. [Calibration validation](vision-calibration-check.json) accepts synthetic image records while explicitly withholding depth-rig/field acceptance. Dataset schemas now include registered vision observations; the optional matcher compatibility predicate leaves existing team-aware Part 03 matching unchanged. Historical Part 03 reports retain their original source hashes; new evaluator runs record current hashes.

## Numerical candidate fixture

24 observations, two goal ends, 15 synthetic scheduled seconds, injected model version `injected-trajectories-no-detector-v1`, configuration `synthetic-vision-v1`:

| Count | Result |
| --- | ---: |
| Certain valid references | 6 |
| Review candidates | 7 |
| Matched candidates / misses | 5 / 1 |
| False / unadjudicated candidates | 1 / 1 |
| Observed / boundary / predicted | 2 / 2 / 1 |
| Image-only / net-only | 1 / 1 |

The stale-frame goal intentionally remains a miss. The loose-net candidate is an intentional false candidate; image-only evidence near the uncertain reference remains unadjudicated. Partial crossings, outward retrieval, shots entirely outside the opening and player net impacts do not create crossing/motion-only candidates. Every emitted candidate requires review and forbids automatic confirmation. The 5/6 recall and 240 false candidates/hour computed from this tiny artificial duration are acceptance-test arithmetic, **not football measurements**. They do not meet or qualify the field gate.

## Real runtime, synthetic model

No pretrained weights were available. `tests/vision/fixtures/model/constant.onnx` is a project-generated Constant graph (IR8/opset13), 32×32 float32 input, `[1,6,3]` output, CPU provider. It ignores input pixels and returns fixed person/ball boxes; NMS removes the duplicate ball. Its descriptor records its SHA, version, source and synthetic-fixture licence decision. No pretrained licence approval, trained weights or ball/player detection accuracy is claimed.

Host: Windows 11 build 26200, Python 3.12.4, AMD64 Family 23 Model 24, eight logical CPUs. NumPy 1.26.4, Pillow 11.0.0, ONNX Runtime 1.19.2. Two independent sessions/workers, one runtime thread per session. Dependencies are pinned in `requirements-vision.lock` and the optional project extra. Fresh isolated installation remains unverified.

| Recorded fixture | Frames A / B | Offline fps A / B | Pipeline p95 A / B | Decode p95 A / B | Constant inference p95 A / B |
| --- | --- | --- | --- | --- | --- |
| 320×180, nominal 15 fps | 75 / 75 | 101.62 / 101.81 | 15.06 / 13.29 ms | 2.65 / 2.65 ms | 0.95 / 1.02 ms |
| 1280×720, nominal 60 fps | 360 / 360 | 25.24 / 24.87 | 46.10 / 47.38 ms | 19.94 / 20.94 ms | 0.59 / 0.57 ms |

Sources: session `22a2ad5857e64d59b710ddeb37348b04` and session `879a56b3a74c4a65a80066178047871c`. Full stage distributions, checksums, metadata and explicit limits are in [small benchmark](vision-benchmark.json) and [HD benchmark](vision-hd-benchmark.json). Wall time including model initialization/ROI setup: 0.835 and 14.587 seconds, respectively. These are short offline file runs with filesystem caching, no live capture producer/queue, no sustained RAM/temperature sampling and no real inference load. Queue age/drops remain unknown. The HD image path itself was below 60 fps per camera; the Part 02 live-rate shortfall remains unresolved.

Commands:

```powershell
.venv/Scripts/python.exe tools/benchmark_vision.py local_scratch/part02-first/20261011-005518/recordings/22a2ad5857e64d59b710ddeb37348b04 --model tests/vision/fixtures/model/model.json --settings tests/vision/fixtures/replay/settings.json --output docs/vision-benchmark.json
.venv/Scripts/python.exe tools/benchmark_vision.py local_scratch/part02-hd/20261011-005931/recordings/879a56b3a74c4a65a80066178047871c --model tests/vision/fixtures/model/model.json --settings local_scratch/part04-hd-settings.json --max-frames 360 --output docs/vision-hd-benchmark.json
```

`local_scratch/verify_part04.py` prepares the HD settings by scaling synthetic image geometry fourfold. These are test ROIs, not measured camera calibration. Large pattern media and full replay traces stay under `local_scratch/`. The short measured runs are evidence of adapter execution and a processing bottleneck, not acceptance of the deployment host.

Next software part is Part 05 sensors/impact evidence. Required Part 04 field work is listed in the [vision guide](vision.md); the [implementation plan](../IMPLEMENTATION_PLAN.md) retains unchecked pretrained evaluation, adaptation and live-budget tasks.
