# Part 06 — Dummy fusion baseline

Recorded 11 October 2026. Runner `fusion-shadow-v1`, rules `fusion-rules-v1`, dataset `dummy-fusion-v1`, split assignment `dummy-fusion-groups-v1`, fusion contracts schema 1. Python 3.12.4; no new runtime dependencies. The environment still inherits host packages; this workspace has no Git revision. [Decision table and lifecycle](fusion.md) describe the frozen prototype behavior; [JSON report](fusion-baseline.json) contains all source/input checksums, observations, transitions, corrections, command outcomes, matches and misses.

## Verification

```powershell
.venv/Scripts/python.exe -m pytest --basetemp local_scratch/pytest-part06-final -p no:cacheprovider --tb=short
.venv/Scripts/python.exe tools/export_fusion_schemas.py --check
.venv/Scripts/python.exe tools/fusion_replay.py tests/fusion/fixtures/dataset.json --output local_scratch/part06-proof-a.json
.venv/Scripts/python.exe tools/fusion_replay.py tests/fusion/fixtures/dataset.json --output local_scratch/part06-proof-b.json
.venv/Scripts/python.exe local_scratch/verify_part06.py
```

**146 tests passed in 15.54 seconds**, including the previous 116 and 30 new fusion/storage checks. Tests exercise causal deadlines, clean and uncertain crossings, post-and-in, player-net contact, sensor quality without veto, occurrence versus receipt alignment, unknown/excessive uncertainty, late/stale/future data, duplicate identities, nearby independent tracks and retrospective ambiguity, two ends, sensor-first inputs, net oscillation, operator restart and quick play, old epochs/matches, pause/end/side change, illegal/stale commands, expiry, idempotency, append-only corrections, detached snapshots, record/candidate capacities, split/hash/holdout guards, module boundaries and transactional manual association. Seven exported schemas pass `--check`.

The two CLI reports are byte-identical, SHA-256 **`6bc35eb65aa78bb777f0c7e274cdc4ee01e0c7883255c3498ec49b6bcf1aa0a2`**. The verifier checked every current implementation hash before writing this report. This is deterministic software evidence, not a measured physical detection rate.

## Challenge results

The fixture includes 21 sessions: 19 validation sessions and two public synthetic train/blind guard sessions. Validation contains 17 explicit numerical scenarios plus actual outputs from the existing sensor and vision fixture runners. Scheduled synthetic duration is **93.1 seconds**. Reference matching is one-to-one by session, end, team and crossing occurrence with the existing ±500 ms tolerance.

| Measure | Dummy result |
| --- | --- |
| Candidates | 37 |
| Explicit valid references | 15 |
| Shadow confirmations / matched shadow confirmations | 7 / 7 |
| Shadow misses | 8 |
| Unmatched or unadjudicated shadow confirmations | 0 / 0 |
| Active operator confirmations | 1, reported separately |
| Ignored evidence | 4 |
| Rejected operator commands | 1 |
| Virtual decision latency p50 / p95 / maximum | 320 / 320 / 320 ms, seven matched shadow decisions |
| Official score changes | 0 |

Misses intentionally include occluded/late/ambiguous/expired cases and the correction scenario. The occluded goal rescued by an operator remains a shadow miss. An undone confirmation remains in the journal but is excluded from the active tally. Zero false shadow confirmations on this short, constructed input does not establish a venue false-goal rate; descriptive intervals are in the JSON. Virtual decision latency includes 20 ms fixture emission plus the 300 ms collection deadline. No video processing, live scheduling, persistence, browser rendering or physical score latency was measured.

| Scenario | Result |
| --- | --- |
| Observed crossing with net impact | One shadow confirmation |
| Post-and-in with mixed impact | One shadow confirmation |
| Player-net contact | Review, explicit rejection |
| Partial crossing | Review |
| Occluded/predicted crossing | Review, explicit operator confirmation |
| Repeated observation and late repeat | One candidate and one shadow tally |
| Corroboration after collection deadline | Logged late, remains review |
| Two nearby tracks, impact after both | Two reviews plus unresolved ambiguous impact candidate |
| Second track after initial impact attachment | Both reviews; ambiguous impact cannot corroborate either |
| Explicit quick restart | Two distinct confirmations without a five-second delay |
| Ball retrieval after a goal | Evidence retained unresolved while awaiting restart |
| Pause | Open candidate unresolved; old-epoch sensor ignored; paused evidence retained unresolved |
| Side change | New candidate scores for the updated attacking team |
| Stale epoch, stale occurrence and future emission | Three ignored inputs |
| Review expiry followed by confirmation request | Unresolved; command rejected |
| Operator confirmation followed by undo | Original confirmation retained, tally zero |
| Unmapped impact | Unknown host occurrence retained for review |

## Upstream compatibility

The builder actually runs Part 05's raw dummy packet/receipt replay and Part 04's injected frame replay. Their reports are checksum-registered provenance assets. Fusion consumes **eight original sensor impacts and seven original vision candidates**, preserving source identities, versions, flags and timing. These are separate source sessions, not a newly synchronized paired capture.

All 15 upstream records produce review candidates without shadow confirmations. Sensors alone cannot establish a crossing. Existing Part 04 observed candidates have broad synthetic crossing/timing bounds and no paired sensor evidence; the fusion engine does not improve or replace those bounds. These compatibility cases have no new goal-reference labels and do not contribute to the 15 explicit valid references. Numerical positive scenarios explicitly inject 2/3 ms vision/sensor bounds and narrow crossing intervals solely to exercise the decision path.

## Remaining gates

The Part 06 **dummy software gate passes**. Physical synchronization, localization/depth uncertainty, trained vision quality, sensor firmware compilation/bench qualification, real continuous labels, sustained processing/resource budgets, browser acceptance and the release evaluation remain open. No automatic recall/precision/false-goal/availability target has passed on venue data. These public synthetic guard splits are not independent holdout evidence.

The engine journal is exported in memory, with no restart restoration/live supervisor. The default app remains manual and is not wired to this engine. Part 07 must integrate evidence persistence, review/restart UI and the durable scoreboard writer; Part 08 must qualify recovery and field performance before any automatic mode can be enabled.
