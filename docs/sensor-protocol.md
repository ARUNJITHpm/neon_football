# Sensor transport and impact evidence (Part 05)

Part 05 runs with **dummy data**: raw binary packets for four accelerometer streams, clock markers, grouped labels and deliberate failures. It provides CRC framing, a reconnectable byte-source reader, boot-scoped clock mapping, freshness/gap diagnostics, pre-match baselines and an inspectable impact classifier. No COM port was opened, no sensor was installed and no score was changed. [Results](sensor-baseline.md) and [progress](implementation-progress.md) record what passed.

## Run the dummy replay

From the project root:

```powershell
.venv/Scripts/python.exe tools/sensor_replay.py tests/sensors/fixtures/dataset.json --output local_scratch/sensor-replay.json
.venv/Scripts/python.exe tools/check_sensor_sync.py tests/sensors/fixtures/sync-markers.json --output local_scratch/sensor-sync.json
.venv/Scripts/python.exe tools/export_sensor_schemas.py --check
```

Rebuild the deterministic bundle with `tools/build_sensor_fixture.py NEW_DIRECTORY`. The manifest contains separate train, validation and public synthetic blind-test sessions, raw `.nfsp` files, receipt-index JSONL, physical-incident labels and per-boot marker mappings. Data shapes and thresholds are artificial acceptance cases. No training occurred. The public blind fixture tests access behavior; it is not an independent untouched field holdout.

Select `--split train`; blind access additionally requires `--split blind_test --allow-blind-test`. Real field splits must be assigned by match/physical incident before extracting windows and independently protected. Dataset contracts reject repeated session/match/incident IDs, source groups assigned across splits and repeated asset content across splits. Raw bytes and index hashes are verified before processing. Relative POSIX paths, safe root resolution and receipt/byte/identity boundaries are checked. Transformations still require a human leakage audit. The receipt index records `session_id`, `kind`, `received_seconds`, `byte_offset` and `byte_length`; disconnect rows additionally identify the board. Times use a common host monotonic domain. Fixture receipts multiplex two dummy boards into one file; actual boards require independent sources/readers.

The runner defaults to 100,000 packets and 2,000,000 samples, with explicit larger bounded options; receipt-record count is also bounded. Raw files are streamed. Impact histories retain at most 1,600 samples per channel by default, baseline size 320. The application does not import sensor workers or connect them to live capture/scoring yet.

## Wire format: NFSP v1

All integers are unsigned little-endian except acceleration codes. Each frame is:

| Field | Bytes | Meaning |
| --- | ---: | --- |
| Magic | 4 | ASCII `NFSP` |
| Payload length | 2 | 46–238 bytes |
| Payload | Variable | Header below, then 0–32 XYZ samples |
| CRC-32 | 4 | IEEE CRC-32 over length bytes plus payload; standard zlib result |

The 46-byte payload header has no C-struct padding:

| Field | Bytes | Values |
| --- | ---: | --- |
| Protocol version | 1 | 1 |
| Kind | 1 | 1 samples, 2 health |
| Goal end | 1 | 0 goal_a, 1 goal_b |
| Sensor role | 1 | 0 back net, 1 goal frame |
| Status flags | 2 | Defined bits below |
| Device ID | 4 | Nonzero, configured board-to-end binding |
| Boot ID | 8 | Nonzero, changes at each board boot |
| Packet sequence | 4 | Independent increasing counter per sensor role |
| First sample sequence | 8 | Increasing drained-sample counter per sensor role |
| First device timestamp | 8 | Microseconds since boot, estimated oldest FIFO sample |
| Nominal sample period | 2 | 1,250 µs for this 800 Hz prototype |
| Sample count | 2 | 1–32 for samples, 0 for health |
| Timestamp uncertainty | 4 | Microseconds; zero is not justified by this firmware |

Each XYZ sample is three signed int16 raw full-resolution codes. Expected range is -4096..4095. Host conversion uses an **approximate, uncalibrated** 0.0039 g/LSB; field scale/orientation need measurement. Near-rail codes (absolute value ≥3900) carry conservative saturation flags. Health frames have no samples and cannot refresh sample freshness. Unsupported versions, rates, counts, flags, raw ranges or layouts are rejected.

Flag bits: `0x01 fifo_overrun`, `0x02 sensor_missing`, `0x04 saturated`, `0x08 tx_overflow`, `0x10 timestamp_estimated`, `0x20 sensor_restart`, `0x40 self_test_failed`. The firmware does not implement the physical self-test yet. Overrun reveals loss but cannot count discarded ADC conversions; sample sequence counts FIFO reads, not unknowable overwritten measurements. Lost transmitted batches are separately observable through packet/sample counters. Counter wrap requires a new boot epoch.

The decoder accepts reads up to 4096 bytes, tolerates arbitrary packet fragmentation, resynchronizes after garbage/invalid lengths/CRCs and keeps bounded pending bytes. Disconnect drops incomplete frames; it never stitches two connections. CRC checks transmission integrity, not sender authenticity.

## Timing, delivery and reconnects

`SensorHost` requires configured device-to-goal bindings and one alignment per device/boot/host domain. Unknown devices or wrong ends fail. It rejects duplicate/reordered packets, counts missing packets/samples and marks irregular sample times. Source-time regression quarantines that boot even across reconnect; a new boot needs new synchronization evidence. Retired boot/transport packets are discarded.

Serial receipt is never substituted for acquisition time. `tools/check_sensor_sync.py` fits at least three explicit source/reference markers and validates at least three later markers. It reports drift, maximum held-out residual/uncertainty bound and the verified sample-clock span. Device-to-host mapping applies only within that span. Packet timestamp uncertainty is added after scaling. Unknown/expired mapping remains null; venue inputs cannot use synthetic mapping. Physical marker provenance alone does not certify field acceptance or cross-camera alignment.

The firmware's FIFO phase/read timestamp is an estimate, not an ADXL345 hardware timestamp. Its 2.5 ms declared budget is a **bench assumption** requiring measurement, including FIFO phase, sampling oscillator behavior, SPI service jitter and overflow. Marker residuals alone do not validate that assumption. Default host timing budget is 20 ms; delivery age above 250 ms is flagged stale. No healthy automatic-scoring state is derived from byte arrivals.

`SensorReader` accepts a factory returning a byte source with `read(size)` and `close()`. Sources must honor a bounded read timeout; empty reads mean timeout, while I/O errors cause close/reopen. It records open/disconnect/error counters, exposes a bounded latest-packet queue and drops oldest entries under pressure. Queue entries are `(packet, receipt_seconds, connection_epoch)`; pass the epoch into `host.process(...)` and the returned samples to `ImpactEngine.ingest(...)`. New transport/boot epochs reset classifier history and pre-match baselines. Status restarts must invalidate the engine even if the packet is health-only. A `raw_sink(chunk, receipt)` callback can retain original bytes; storage failures disconnect the source and must remain visible. No production raw recorder or actual serial-library adapter is configured here.

Each board needs its own reader. Tests demonstrate a missing source reconnecting while another source continues. Stale detection uses **last fresh sample receipt**, not heartbeat time. `host.health(now)` reports both roles, current flags and mapping registration; `receiving` means fresh usable packet input, not validated goal evidence. Baseline and clock quality must be checked separately. The classifier must be recreated or invalidated before each actual match; application match wiring is Part 06.

## Causal impact rules

The default rules collect a quiet 400 ms baseline per role, check RMS stability and gravity magnitude, and subtract each axis mean. An unstable/noisy baseline is reported and retried with a fresh quiet window. This can expose a moving/loose sensor but cannot certify mechanical attachment, axis orientation or ADXL self-test. `field_self_test_passed` always remains false in these software reports.

Residual magnitude crossing 0.6 g triggers a window of **400 ms before and 100 ms after** the trigger. The follow-up is awaited on both independent sensor streams; history is already buffered. Features are peak, RMS, sample coverage and a first-difference roughness/RMS ratio for each role. There is a 600 ms cooldown and one pending window per board. The classifier does not pair independent ADC conversions as if they shared exact exposure timestamps.

| Rule result | Meaning |
| --- | --- |
| `net_impact` | Net peak dominates frame peak by the configured factor |
| `frame_impact` | Frame peak dominates net peak |
| `mixed_impact` | Both channels are substantial; retains post-and-in evidence |
| `slow_impact` | Dominant channel has low temporal roughness |
| `unknown` | Incomplete/gapped/stale/saturated/unsynchronized/poor-baseline evidence or a weak trigger |

These are inspectable heuristic labels, not calibrated probabilities or physical goal/player/wall recognition. Wall and frame impacts may share a result. All impacts preserve `possible_goal: true` and `automatic_confirmation_allowed: false`: the sensor classifier cannot confirm or veto a goal. Vision and Part 06 fusion must assess actual crossing evidence. An unfinished window can only flush as incomplete/unknown; a reboot/disconnect cancels pending history with a diagnostic count.

Replay keeps original raw packets/indexes for diagnosis and exports event features/flags. It matches timed impacts one-to-one to labels by match/end within ±200 ms, reports physical-label versus evidence-class confusion, scheduled-hour false impacts, uncertainty intervals, unknowns, unmapped events, misses and reference-to-evidence latency. Unknown events count as detected impacts when matched; **that is coverage, not a correct class or goal decision**. Unmapped events stay separate and do not erase the reference miss. Noise without a trigger appears as `no_event`; it is not a classified noise window. Reports never measure scoreboard/display latency or goal accuracy.

## Firmware and field work

[ESP32 bench firmware and wiring](../firmware/esp32/README.md) specify FIFO acquisition and the packet serializer. The scaffold uses ADXL345 normal-power 800 Hz, SPI mode 3 at 1 MHz, a stream FIFO/watermark interrupt and six-byte XYZ burst reads, with FIFO-pop delay. These choices follow the primary [ADXL345 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/adxl345.pdf). Device-clock context: [Espressif high-resolution timer](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/esp_timer.html).

Before field acceptance: choose/pin and compile the actual ESP32 toolchain, verify packet bytes against host tests, mount/record all four sensors, measure fresh-sample rate/overflow and signal rails, validate per-boot physical clock mappings and FIFO timestamp uncertainty, trial actual serial disconnect/reboot/disk failure, capture independently labelled continuous impacts and hard negatives, freeze rules against held-out match groups and report per-class errors/impacts per hour. No physical quality gate has been passed by the dummy data.
