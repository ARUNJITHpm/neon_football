# Offline vision and crossing candidates (Part 04)

Part 04 supplies a local ONNX adapter, one bounded ball track per camera, goal-opening checks, rolling net-motion evidence and deterministic candidate replay. Every `vision_candidate` requires review and prohibits automatic confirmation. These tools do not open cameras, send scoring commands or write the scoreboard database. [Measured software results](vision-baseline.md) and [remaining field gates](implementation-progress.md) distinguish tests from venue acceptance.

## Run the numerical replay

From the project root, with the existing runtime:

```powershell
.venv/Scripts/python.exe tools/vision_replay.py tests/vision/fixtures/replay/dataset.json --settings tests/vision/fixtures/replay/settings.json --annotations tests/vision/fixtures/replay/annotations.json --output local_scratch/vision-replay.json
.venv/Scripts/python.exe tools/validate_vision_calibration.py tests/vision/fixtures/replay/settings.json --output local_scratch/vision-calibration.json
.venv/Scripts/python.exe tools/export_vision_schemas.py --check
```

Replay consumes **injected detection/depth observations**, not image inference. The numerical fixtures have synthetic intrinsics, goal geometry and depth, and include no football imagery. Rebuild them with `tools/build_vision_fixture.py NEW_DIRECTORY`. The report records inputs, source hashes, split, model/configuration versions, traces, candidates, error lists and descriptive Wilson/Poisson intervals. No report qualifies a release.

Register exactly one `vision_observations` JSONL asset per selected Part 03 dataset session, alongside its existing `replay_events` asset. Exported [frame](schemas/vision-frame-v1.json) and [settings](schemas/vision-settings-v1.json) schemas define the records. All asset hashes are checked; the Part 03 source-group/content split and blind-access guards apply. Frames must fit the registered session, clock, scheduled match, resolution and calibration version. Media references must be declared assets. Duplicate/regressing source sequences or times fail within a stream epoch. Session/match/boot/clock/resolution/evidence changes discard prior tracks. The default in-memory limit is 250,000 frames, configurable up to 2,000,000; full-match RAM remains unmeasured. Session duration bounds receipt time, while occurrence stays inside the match window.

Candidate metrics match one-to-one by session, match, goal end and crossing time, with the frozen default ±500 ms tolerance. They measure review-candidate coverage, not team attribution, confirmed goals or display latency. Duplicate and wrong-end candidates incur false-candidate penalties. Candidates near uncertain references remain unadjudicated. Aggregate matching penalizes duplicate views of the same incident; cross-camera fusion is Part 06. Scheduled exposure includes stale-input misses. Reports never substitute healthy-only exposure to hide outages. Match pause/dead-ball handling is also later fusion work: this offline tool can generate review evidence anywhere within a registered scheduled match.

## Local detector adapter

Optional dependencies are in `requirements-vision.lock` and the `vision` project extra. Tested versions: NumPy 1.26.4, Pillow 11.0.0 and ONNX Runtime 1.19.2 on Python 3.12.4 / Windows. The current environment inherits host packages; fresh isolated installation is unverified. The manual application does not import these optional modules.

Create a `ModelDescriptor` JSON next to your authorized local model: version, relative path, SHA-256, source, licence and offline-use decision, purpose, input width/height, class count and class-ID mapping. The [model schema](schemas/vision-model-v1.json) is the complete contract. No model downloads or training occur. `not_reviewed` licence decisions block execution. Pretrained/adapted weights cannot use the synthetic-fixture decision. A decision records the project owner's assessment; this software does not verify licensing rights.

`modules.vision.detector.OnnxDetector(descriptor, model_root).detect(pillow_image)` returns detections and stage timings. The implemented format is explicit:

- One float32 NCHW RGB input, batch 1, normalized to `[0,1]`, letterboxed with 114 padding and bilinear resize. Fixed input dimensions must agree with the descriptor; symbolic dimensions use the declared input size.
- Exactly one finite raw output `[1, 4 + class_count, N]`: pixel-space `cx, cy, width, height`, then class probabilities. No separate objectness, embedded NMS, transposed output, logits or end-to-end export layout is accepted.
- Argmax across all class channels, then retain mapped ball/player classes. Reverse letterboxing using actual rounded resize dimensions, clip boxes, reject empty boxes, apply deterministic class-wise NMS and bounded pre-NMS/output counts.
- CPU provider only, one intra/inter-op thread per session; two offline benchmark workers have separate sessions. Score is an uncalibrated detector score. The default two-pixel positional uncertainty is a placeholder requiring empirical calibration.

Export details vary by model generation and configuration; inspect the actual output before registering it. See the primary [Ultralytics export reference](https://docs.ultralytics.com/modes/export/) and [ONNX Runtime Python API](https://onnxruntime.ai/docs/api/python/api_summary.html). Only the synthetic adapter model has been exercised here; compatibility with real pretrained weights remains pending.

`tools/build_vision_model_fixture.py NEW_DIRECTORY` constructs an IR8/opset13 Constant graph without requiring the ONNX authoring package. Its output is always two objects after NMS, regardless of pixels. The checked-in 245-byte graph is an adapter test, not a detector, and supplies no accuracy evidence. See the descriptor for its exact hash, shape, provenance and fixture licence.

## Geometry and evidence

The goal frame uses metres: `x` from the left post to right post, `y` from ground upward, `z` normal to the plane and positive inward. Goal width/height and ball radius must be measured. Whole-ball clearance uses **radius plus configured margin plus positional uncertainty**, not ball-centre crossing. Inward speed and a bounded observation gap are required. The image ROI is not a substitute for three-dimensional depth.

Measured calibration records need valid intrinsics/distortion, image ROI and reprojection error below the configured budget. Draft records, wrong resolution, stale frames and poor reprojection suppress candidates and reset crossing history. Calibration provenance is separate (`synthetic`, `venue`, `unverified`); venue observations reject synthetic/unverified calibration. The validator checks recorded geometry only and never certifies an actual camera/depth rig.

Verified depth observations require the configured depth calibration ID, common clock and synchronization flag. Their method is stereo, external depth or explicitly synthetic; synthetic depth cannot be represented as venue observations. **There is no stereo reconstruction, pose solver or depth-device driver in this part.** A later provider must transform measured positions and uncertainty into the goal frame and demonstrate its physical timing/calibration. Floor homography is retained for floor work and is never used for an airborne ball. Projective calibration context: [OpenCV calibration reference](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html).

| Candidate quality | Evidence |
| --- | --- |
| `observed_crossing` | Two observed pitch-side/inward samples, whole sphere inside the opening and beyond the plane, acceptable geometry/timing/association cues |
| `predicted_crossing` | Short-gap constant-velocity prediction supports a possible crossing; predicted depth/uncertainty is explicit |
| `boundary_uncertain` | Possible crossing with uncertain margin, association, observation quality or timing |
| `depth_ambiguous` | Image-only opening entry without verified airborne depth |
| `net_motion_only` | Rising net-motion cue without sufficient crossing evidence |

All five require review. Partial crossings below the whole-ball threshold, outward motion and intervals entirely outside the opening do not produce depth-crossing candidates. Conservative opening checks apply at both endpoints; curved paths or exits before the next sample can be missed. Crossing time is a linear interpolation estimate, accompanied by the sample interval and a conservative uncertainty at least that interval width plus source timing uncertainty; unknown source timing stays unknown. The interval is not proof of constant acceleration or camera calibration accuracy.

Tracking keeps one ball per view, marks multiple eligible associations, grows uncertainty during gaps and expires prediction after 200 ms by default. It does not provide robust multi-ball identity tracking. An association/player/global-motion/timing problem in the pitch-side sample remains attached to the candidate even if the next sample is clear. A rebound fully back to the pitch side rearms the track. A depth-method change cannot complete the old crossing.

Net motion compares a 96×64 grayscale image with a bounded rolling median (20 frames, five-frame warmup). Whole-image change and conservative player-box/ROI overlap suppress motion-only candidates. Unstable/occluded frames are excluded from baseline updates. A permanently changed view may require a fresh baseline; this implementation has no exposure normalization or camera-motion compensation. Image quality flags are cues, not a learned impact classifier.

## Profile the recorded image path

```powershell
.venv/Scripts/python.exe tools/benchmark_vision.py local_scratch/part02-first/20261011-005518/recordings/22a2ad5857e64d59b710ddeb37348b04 --model tests/vision/fixtures/model/model.json --settings tests/vision/fixtures/replay/settings.json --output local_scratch/vision-benchmark.json
```

The benchmark verifies recording segment/index hashes and byte/identity boundaries, then runs read, JPEG decode, preprocess, ONNX, postprocess and net motion on two concurrent workers. It reports p50/p95/p99/max and source expected rate. Live queue age/drop counts are null because files are processed without live producers. Captured receipt age, exposure latency and capture contention are not reconstructed from offline speed. [Small](vision-benchmark.json) and [HD](vision-hd-benchmark.json) results show that even the Constant-model HD path fell below 60 fps per feed on this host. Full-model inference, live integration, sustained resource use and field performance remain required before Parts 06/08 enable scoring.

## Next field work

Evaluate authorized pretrained weights on the Part 03 held-out venue development data before adaptation. Record detector precision/recall, ball pixel size, blur/occlusion/lighting failures, ordinary negatives, model licence/export version, hardware and stage timings. Calibrate localization/depth/timing uncertainty; obtain goal-plane evidence with the mounted cameras. Then adapt using training data only and rerun unchanged validation/holdout procedures. The Part 04 target remains at least 90% candidate recall and below two false candidates/hour with both streams inside their measured budget. No such gate has passed here.
