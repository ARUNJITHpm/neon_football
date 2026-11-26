# Neon Score

A locally operated manual scoreboard for one neon football cage. Parts 01–10 of [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) provide durable scoring, optional capture/clips, offline vision candidates, dummy sensor/fusion evidence, operator review/reports, integrity monitoring, checked recovery/retention tools, dummy player-attribution suggestions and generated contact analytics. No trained football detector, installed sensors or venue accuracy is available. Real input integration, automatic scoring and automatic player recognition remain gated later work.

## Run on Windows

Use Python 3.11–3.13. The current workspace was tested on Python 3.12.4.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.lock
.venv/Scripts/python.exe -m app
```

If `uv` is installed, it can create and install into an environment without needing `ensurepip`:

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.lock
.venv/Scripts/python.exe -m app
```

In this sandbox the `ensurepip` step was denied. The existing `.venv` uses the host's already-installed packages through `--system-site-packages`; it runs the prototype and tests, but is not an isolated installation. The lock files capture the versions exercised here. A fresh, isolated install from the lock still needs verification in an environment with package-download access.

- Operator: <http://127.0.0.1:8000/operator>
- Read-only display: <http://127.0.0.1:8000/scoreboard>
- API reference: <http://127.0.0.1:8000/docs> (Swagger UI assets require internet).

On first launch, the application creates `data/operator.key`. Read it locally and enter it in the operator page:

```powershell
Get-Content data/operator.key
```

Alternatively set `NEON_OPERATOR_KEY` to a secret of at least 16 characters before launch. The page keeps it in tab-scoped session storage; Lock console removes it. This is a shared prototype key; staff-specific identities remain future work. Public snapshots contain scoreboard fields only. Operator snapshots, evidence, clips, history, reports and exports require the key.

## Play a match

1. Unlock the console; enter team names, duration and optional rosters. Each roster line is `bib number, player name`; append `, bench` for a substitute.
2. Create the match, then Start match. The default is a 20-minute count-up clock; the operator decides when to end.
3. Record a goal using the appropriate team button. Team scores change only after the server commits the event.
4. Edit players to attach a scorer, assist or own-goal flag. Unknown players are allowed; own-goal scorers must belong to the opposing team, and own goals have no assist. Optional generated player suggestions require Apply or Reject; they do not read video or change team score. Record substitutions through Players on the pitch. [Attribution guide and limits](docs/attribution.md).
5. Pause/resume the clock as needed. Change ends while ready or paused, with no unresolved candidates.
6. Undo a mistaken goal. Its original event is retained, and a correction is appended. Corrections and player edits remain available after the match ends.
7. Export the JSON match record before setting the next match. Previous records remain accessible by match ID through the API.

If a command's response is lost, use Retry last action. The request retains its original command ID and revision across page reloads. A conflict requires reviewing refreshed state rather than silently retrying a new edit.

After a live-match host restart, the saved score returns in Interrupted state. The clock shows its last committed boundary, not an invented estimate across downtime. Enter the actual elapsed time, save it, then explicitly Resume. A paused match restores without reconciliation. An interrupted match may also be ended, preserving its uncertainty flag in the audit record.

## Configuration and data

The default configuration is `app/config/cage.example.yaml`. Set `NEON_CONFIG` to another YAML path to use a venue configuration. Relative data paths are resolved from the server's working directory. Start the server from this project directory.

Automatic scoring must remain false; setting it true rejects startup. Field measurements in the example are null. Complete [docs/venue-survey.md](docs/venue-survey.md), [docs/requirements.md](docs/requirements.md), [docs/hardware.md](docs/hardware.md) and [docs/data-policy.md](docs/data-policy.md) before treating Part 00 as complete.

Bind defaults to localhost. For a tablet on the venue network, use a separate configuration with `host: 0.0.0.0` and visit the host's LAN address. Use a trusted isolated LAN for the prototype; staff sessions, production TLS, firewall configuration and deployment recovery are later milestones. Keep the operator key private. All browser assets and the bundled licensed DejaVu font are local; normal scoreboard operation has no internet dependency.

Run exactly one server worker per database. An OS file lock rejects a second owner, since the live monotonic clock belongs to one process. Enabled capture uses one independently supervised FFmpeg process per camera. See [capture setup, timing and capacity](docs/capture.md), including fixture commands and remaining field gates.

Data lives in `data/` and is excluded from Git. SQLite WAL and full synchronization are enabled; events cannot be updated or deleted through SQL. Use the [checked live backup and new-path restore runbook](docs/runbook.md) to preserve the event log, roster and attribution evidence. Do not place a live database in a concurrently synchronized deployment folder; use a host-local database path at the venue. This workspace itself is in OneDrive, so local development is not the deployment storage configuration.

## Verify

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-test.lock
.venv/Scripts/python.exe -m pytest
```

Tests cover match lifecycle, monotonic timing, retries, stale revisions, simultaneous writes, injected persistence failures, restart recovery, immutable events, candidate review, goal-end mapping, attribution, authenticated writes, exports and WebSocket reconnection. Capture tests exercise FFmpeg fixtures, frame indexes/hashes, bounded buffers, clips, drift/holdout, quota failures, stale camera restart and independent reconnect. FFmpeg tests skip explicitly if the executable is absent. See [docs/implementation-progress.md](docs/implementation-progress.md) for recorded evidence.

Optional browser smoke testing requires Playwright and installed Edge:

```powershell
.venv/Scripts/python.exe tools/verify_browser.py
```

The browser test uses a disposable database and synthetic players under `local_scratch/`, never the venue database. It was blocked here by the Windows sandbox's Playwright driver pipe permission. There is no connected browser in this session, so screenshots and end-to-end browser behavior have not been verified.

## Architecture

For offline data work, see the [annotation, splits and replay guide](docs/annotation-guide.md) and [synthetic baseline results](docs/baseline-results.md). `tools/replay.py` replays recorded/injected decisions; it does not run a goal detector or change live scores. `tools/import_capture_session.py` registers Part 02 recordings without inventing goal labels.

For Part 04, see the [vision guide](docs/vision.md) and [vision validation/benchmarks](docs/vision-baseline.md). `tools/vision_replay.py` turns registered detection/depth observations into review candidates. `tools/benchmark_vision.py` runs local ONNX inference on recorded JPEGs with two workers. The bundled model is a Constant graph that ignores images; use it only for adapter checks. Optional packages are pinned in `requirements-vision.lock`. Neither tool writes scores or activates live vision.

For Part 05, see the [sensor protocol and dummy replay](docs/sensor-protocol.md), [sensor results](docs/sensor-baseline.md) and [ESP32 scaffold](firmware/esp32/README.md). Run `.venv/Scripts/python.exe tools/sensor_replay.py tests/sensors/fixtures/dataset.json --output local_scratch/sensor-replay.json` to inspect generated impact evidence and faults. No hardware port is opened; firmware compilation/field sampling remain pending. Sensor evidence cannot confirm or veto a goal.

For Part 06, see the [fusion rules, lifecycle and restart policy](docs/fusion.md) and [dummy fusion results](docs/fusion-baseline.md). Run `.venv/Scripts/python.exe tools/fusion_replay.py tests/fusion/fixtures/dataset.json --output local_scratch/fusion-replay.json`. Its shadow score records hypothetical decisions independently of the official scoreboard. Weak or ambiguous evidence requires review; unanswered reviews expire unresolved.

For Part 07, see the [operator review guide](docs/operator-review.md) and [verified dummy workflow](docs/operator-baseline.md). Select **Dummy review** while ready or paused, start play, then add a dummy incident. Confirm or reject it, or link it to a manual goal. Each saved goal requires **Restart play** in dummy review. A ready clip is a generated two-second test pattern, independent of the numerical incident; it is not football footage. Manual scoring remains the default. Run `.venv/Scripts/python.exe tools/operator_fixture.py local_scratch/operator-example` with a new destination directory to reproduce the API workflow. Browser rendering and physical HDMI acceptance remain pending.

For Part 08, see the [operation/recovery runbook](docs/runbook.md), [software recovery baseline](docs/recovery-baseline.md) and [release gates](docs/release-evaluation.md). `tools/score_backup.py` makes consistent SQLite backups and restores only to new paths. `tools/retention.py` defaults to planning registered closed-session media with training holds and retained audit logs. `/api/v1/operations/status` requires the operator key. `tools/package_release.py` builds a checksummed source candidate; dependencies and hardware are not bundled. `tools/recovery_fixture.py` demonstrates backup/reopen/clock reconciliation in a new dummy directory. Automatic scoring remains unavailable; real installation, physical power recovery, venue shadow evaluation and browser/HDMI gates are pending.

For Part 09, see the [attribution workflow/rules](docs/attribution.md) and [generated attribution baseline](docs/attribution-baseline.md). Bench players and substitutions preserve goal-time rosters. Generated scorer/assist/own-goal suggestions require explicit operator approval; they do not read bibs or detect touches from pixels.

For Part 10, see [contact analytics and corrected reports](docs/analytics.md) and the [generated baseline](docs/analytics-baseline.md). Run `.venv/Scripts/python.exe tools/analytics_fixture.py local_scratch/analytics-example` with a new destination and read its `report.txt`. Reports separate approved active-goal statistics from generated passes/interceptions/possession windows, including unknown, paused and dead-ball time. Generate/correct examples via the authenticated command API; existing Download report returns enriched text. Distance, heatmaps, shots, narratives and real overhead tracking remain unavailable.

- `core/`: versioned command/event contracts, clock interface, persistence port and bounded notification bus.
- `modules/storage/`: serialized SQLite scoring transactions, audit log, idempotency and recovery.
- `modules/api/`: FastAPI endpoints and locally served operator/display pages.
- `modules/capture/`: FFmpeg capture, indexed recordings, bounded buffers and asynchronous clips.
- `modules/replay/`: checksum/split validation, deterministic virtual replay and offline event evaluation.
- `modules/vision/`: local ONNX adapter, observed/predicted ball tracking, conservative crossing candidates and rolling net-motion cues.
- `modules/sensors/`: CRC-framed packets, bounded reconnectable readers, source/clock health and causal impact evidence.
- `modules/goal_engine/`: time/uncertainty correlation, independent incidents, shadow decisions, candidate lifecycle, corrections and operator restart gating.
- `modules/stats/`: injected identity aggregation, conservative attribution and bounded contact analytics with explicit unknown time.
- `firmware/esp32/`: uncompiled ADXL345 FIFO/interrupt bench scaffold.
- `app/`: configuration and composition; modules import only `core`.
- `tools/`: dependency capture, fixture benchmark, calibration/synchronization/schema tools and optional browser verification.
- `tests/`: hardware-free behavior and API checks.

High-volume video and durable score changes use separate paths. The notification bus is not the score authority. The WebSocket currently sends committed current-state snapshots every 500 ms; reconnect clients receive a complete snapshot. Candidate workflow primitives require explicit operator commands and do not constitute goal detection.

Implementation references: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/), [Python SQLite transactions](https://docs.python.org/3.12/library/sqlite3.html), [Pydantic model validation](https://docs.pydantic.dev/latest/concepts/models/). Font license: `modules/api/static/fonts/LICENSE_DEJAVU`.
