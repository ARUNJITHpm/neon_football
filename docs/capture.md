# Capture, calibration and timing (Part 02)

Capture is optional and disabled in the default configuration. It never changes the score. The user selected generated video fixtures for this milestone; no connected camera, sensor, measured lens calibration or physical synchronization is claimed.

## Run the fixture benchmark

Install FFmpeg separately and put `ffmpeg` and `ffprobe` on PATH. The tested binary is recorded in every session manifest. Python capture has no OpenCV dependency. The optional floor-mapping tool needs `numpy==1.26.4` (`pip install '.[calibration]'`).

From the project root:

```powershell
.venv/Scripts/python.exe tools/capture_fixture.py --root local_scratch/capture-demo --seconds 8
.venv/Scripts/python.exe tools/capture_fixture.py --root local_scratch/capture-hd --seconds 6 --width 1280 --height 720 --fps 60
```

Each invocation creates a new directory, generates two lossless FFV1 test patterns, captures them at real-time input pacing, requests one clip per feed and saves `benchmark.json`. Existing media is never overwritten. This measures the pipeline, not real camera exposure accuracy or live device capacity. Generated file readers can fall behind and eventually retain every frame; live devices may lose frames under the same load.

To use the fixture feeds with the scoreboard, select the generated MKV paths locally:

```powershell
$env:NEON_FIXTURE_A = 'C:\path\to\goal-a.mkv'
$env:NEON_FIXTURE_B = 'C:\path\to\goal-b.mkv'
$env:NEON_CONFIG = 'app/config/capture.fixture.yaml'
.venv/Scripts/python.exe -m app
```

The sample configuration expects 320x180 at 15 fps. Copy/edit it for a different fixture resolution/rate. Finite files stop at EOF (`reconnect: false`); device deployments normally reconnect. Keep recordings on a host-local protected volume and apply the venue data policy. No retention cleanup is implemented yet.

## Camera configuration and health

Each camera needs a unique `id`, `kind`, exactly one `source` or `source_env`, configured width/height and expected fps. Supported FFmpeg input options are file, RTSP over TCP, Windows DirectShow (`dshow`) and Linux `v4l2`. Only file inputs were exercised here. For DirectShow, use the device name as the source; the reader prepends `video=`. For RTSP, supply the URL through an environment variable to avoid storing credentials in configuration. Never paste passwords into project notes.

One FFmpeg child and Python reader thread run per camera, with an independent restart epoch. The supervisor terminates its own child on startup timeout or stale receipt, then reconnects if enabled. It does not terminate unrelated processes. Raw FFmpeg stderr, input addresses and exception strings are discarded; only parsed frame metadata and generic failure codes are persisted. Camera/clip identifiers are hashed into filesystem names to prevent path traversal and Windows filename failures.

Actual source dimensions are retained without scaling. A resolution mismatch invalidates calibration and reports `invalid_resolution`. Calibration errors permit recording/manual scoring, while remaining explicitly unverified. Health states include starting, healthy, lagging, stale, reconnecting, disconnected, invalid_resolution and stopped. Status reports last receipt age, observed dimensions, rates, gaps, reconnects, resets, storage failures and buffer counters. Capture startup failure leaves manual scoring usable and appears in authenticated status.

## Timing contract

`core/capture.py` defines schema 1 contracts. `TimingEnvelope` is also suitable for later sensor packets: source/boot identity, sequence, optional device sequence/time, clock domains, monotonic host receipt, UTC receipt, quality, optional measured offset/uncertainty and reset flag. No offset is inferred automatically.

FFmpeg `showinfo` reports the decoded frame's presentation timestamp (PTS). It is paired with the corresponding JPEG by decoded frame sequence. Metadata overflow, missing timestamps or sequence mismatch restart the reader rather than silently attaching the wrong time. PTS is **media timeline time**, not a verified exposure timestamp. Host receipt occurs after decode, JPEG encoding and pipe delivery. UTC is for audit; monotonic time is for live elapsed time. Process restarts have a new host clock-domain ID. Reconnect or regressing source time/sequence marks a source reset.

Source fps is positive source intervals divided by their total duration, excluding resets. Receipt fps is frame count minus one divided by the receipt span; it includes outages. Receipt/source gaps exceeding 2.5 expected frame periods are logged independently in `incidents.jsonl`; the aggregate gap counter may count both for one incident. Input loss before decoding cannot always be distinguished from encoder behavior. Device-level exposure/drop evidence remains a field task.

Delivery-lag growth compares elapsed receipt time with elapsed source time within the current boot, relative to its first paired frame. Growth exceeding the stale threshold reports `lagging` even when the last receipt is fresh. This detects growing backlog, not absolute exposure latency; initial decode delay, upstream buffering and unknown device clock rate remain unmeasured. Fast offline replay may have negative growth, which is expected. Status also reports peak growth and source-timeline encoded bitrate.

Portable JSON schemas are in `docs/schemas/`. Regenerate intentional contract changes with `python tools/export_capture_schemas.py`; verify consistency with `--check`.

## Recording and capacity

Each session has `manifest.json`, `metrics.json`, `incidents.jsonl`, camera segments and optional clips. The manifest freezes calibration contents/errors, capture settings, backend version, expected/observed dimensions, timing quality and finalized segment hashes. No camera input URL is included. Calibration is loaded once per session; a physical camera move requires a new version and session.

Camera segments are concatenated JPEG streams (`.mjpeg`) with `.jsonl` indexes. Each index row contains the complete frame metadata, byte offset and byte length. SHA-256 covers video and index bytes. The **index is authoritative for timing**; an MJPEG player's assumed fps is not. Segment boundaries preserve boot epochs and are configurable (60 seconds by default). Active segment checksums/counts are finalized on rotation or clean shutdown. Files are flushed on closure, without score-database durability guarantees; power-loss recovery and orphan scan belong to Part 08. Inspect file indexes after interruption rather than trusting a stale active manifest. `complete` on a segment means writer finalization; clip temporal completeness is a separate `coverage` field.

The inference queue retains the latest two frames by default, evicting oldest frames and counting drops. No vision consumer exists yet, so almost all frames are intentionally dropped from this queue in the benchmark; recording has a separate path. Encoded pre-event history is bounded by six receipt seconds and 64 MiB per camera. Buffers hold references to JPEG bytes, not uncompressed images. Clips have at most eight collecting/writing requests and a 128 MiB payload limit per clip. Live queues, buffers and clip references have separate bounds; account for their combined maximum plus FFmpeg/Python overhead when sizing RAM.

JPEGs have a 16 MiB parser limit. A shared session payload/index/incident quota and free-space reserve are checked before writes. Manifest/metrics/status JSON overhead is outside that byte counter. Recording disk failures stop that camera's recording and flag the manifest while leaving live capture/manual scoring available. Clip failures are explicit. No disk failure changes a committed score. Recording is synchronous within each reader, so slow storage causes receipt lag; source/receipt gaps and measured rate expose that limitation.

Metrics distinguish encoded bytes, observed receipt bitrate, source rate, time spent in write calls and peak encoded buffer bytes. Write-call MB/s is buffered filesystem service rate, not sustained physical disk throughput. The benchmark samples aggregate Python/owned-FFmpeg working set on Windows; it excludes the already-completed fixture-generation process and is a sampled peak. Synthetic patterns, short sessions and this OneDrive development folder cannot validate venue storage capacity.

## Clips and API

Authenticated operator endpoints (same bearer key/origin checks as scoring):

| Method and path | Result |
| --- | --- |
| `GET /api/v1/capture/status` | Capture health or disabled/startup failure |
| `POST /api/v1/capture/clips` | 202 with collecting/writing/ready/failed status |
| `GET /api/v1/capture/clips/{clip_id}` | Current session clip status; 404 if unknown |

Example request body:

```json
{"camera_id":"goal-a","clip_id":"review-001","event_id":null,"event_monotonic_seconds":null}
```

Null event time uses current host receipt time. An explicit time must be in recent available live history in this process clock domain. A clip ID retry returns the existing status; a different camera/time/event under the same ID is rejected. Requests beyond capacity return 503. Existing manifest/clip files remain on disk after the bounded 256-result memory cache evicts old results; API lookup covers the current cache only. The app does not expose recordings through an unauthenticated static mount. Local file review is available now; browser clip playback/access comes in Part 07.

Pre-event frames are retained immediately; later frames are collected through the configured post window (three seconds before/after by default), then written by a separate clip thread. Ready clips may have `coverage: partial` for missing boundary coverage, source/receipt gaps, clock reset/reconnect or shutdown. Zero frames or quota/write failure returns failed. A stalled feed times out pending post-event collection explicitly. Ready/failed status is polled; there is no clip-ready WebSocket event yet.

Committed manual goals request one clip per camera through the bounded notification bus, after the scoring transaction. `event_id` links the clip result to the immutable score event. Clip IDs are SHA-256 of `event_id:camera_id`. Duplicate scoring retries do not request duplicate clips. These windows surround processing of the **manual goal notification**, which includes operator reaction delay, not physical crossing time. Notification overflow is logged; clips are best-effort and missed media is never regenerated as evidence.

## Calibration records

```powershell
.venv/Scripts/python.exe tools/calibrate_camera.py --camera goal-a --version draft-1 --width 1280 --height 720 --output local_scratch/goal-a-draft.json
.venv/Scripts/python.exe tools/calibrate_camera.py --input measured-goal-a.json --output data/calibration/goal-a-v1.json
```

Output creation is exclusive. A draft has no invented lens parameters. For measured status provide intrinsics, lens-model distortion coefficients, reprojection error and ordered goal ROI. Record target/measurement procedure, physical mounting and goal geometry in placement/notes. Configure `calibration_path` on the corresponding camera. Validation checks identity, resolution, finite values, matrix shape, focal lengths, coefficient count, polygon bounds/crossed edges and invertible floor homography. Schema validity does not prove calibration accuracy; independently measure reprojection and physical coverage at the venue. Automated checkerboard extraction is not implemented.

Four ordered pitch corners optionally generate `--floor-map` using NumPy and measured `--pitch-length`/`--pitch-width` (defaults 15/10 m). This is a ground-plane mapping; it cannot prove an airborne whole-ball goal crossing.

## Physical synchronization procedure

Use a shared visible LED/flash and an independently timestamped host reference (and instrumented sensor event later). Annotate the same physical marker ID in both camera timelines. Include reference uncertainty, frame/exposure duration, marker annotation ambiguity and device delay. Receipt times alone are not a physical reference. Preserve separate boot/domain groups after reconnect/reset.

Create marker JSON matching `tools/check_sync.py`'s `MarkerSet`: schema_version 1, evidence `physical` or `synthetic`, procedure text, and markers containing source_id, boot_id, source_clock_domain, host_clock_domain, marker_id, source_seconds, reference_host_seconds, uncertainty_seconds and split (`fit`/`validation`). Use at least three well-separated fit markers early and three untouched validation markers later per boot/domain. More markers across a full representative session are necessary for field confidence. Input order must increase and all validation markers must follow fitting markers.

```powershell
.venv/Scripts/python.exe tools/check_sync.py markers.json --output sync-report.json
```

The tool estimates offset/drift, checks later residuals and reports conservative residual-plus-annotation-plus-fit bounds. Shared validation marker IDs in the same host domain additionally produce cross-source bounds. Missing pairs are explicitly reported as unavailable. `timing_target_met` only summarizes available groups/pairs; it does not certify complete source coverage or the field gate. Synthetic evidence can never certify physical synchronization. No report is automatically applied to live capture; alignment stays false until a later integration explicitly validates and loads the measured mapping.

Field exit remains pending: both mounted goal cameras, a complete representative session and gap report, measured calibration/visibility, temporary disconnect recovery and physical timing uncertainty. Proposed p95 bound is at most 20 ms. The 720p/60-fps fixture run failed to demonstrate sustained receipt capacity; resolve that on the selected host/storage before enabling automatic scoring.

Primary implementation references: [FFmpeg input devices](https://ffmpeg.org/ffmpeg-devices.html), [showinfo frame metadata](https://ffmpeg.org/ffmpeg-filters.html#showinfo), [image2pipe](https://ffmpeg.org/ffmpeg-formats.html#image2pipe), [RTSP transport](https://ffmpeg.org/ffmpeg-protocols.html#rtsp).
