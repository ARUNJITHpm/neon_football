# Part 03 synthetic harness baseline

Recorded: 11 October 2026. **This is evaluator/replay acceptance evidence, not goal-detector accuracy.** No venue footage, trained model, physical crossing annotation or live automatic-scoring result is included.

The hand-authored validation fixture has six certain valid goals, one invalid player-impact incident and one uncertain incident. Nine injected decision records include seven hypothetical automatic decisions, one operator confirmation and one pending review. It deliberately contains errors so their treatment can be verified.

| Expected behavior | Verified result |
| --- | --- |
| Certain automatic matches | 2 |
| False automatic decisions | 4: duplicate, wrong end, inactive-auto decision, player-impact false positive |
| Missed certain goals | 4, including the operator rescue and the outage goal |
| Operator rescue | 1; automatic recall stays 2/6 |
| Uncertain reference / automatic decision | 1 / 1, explicitly unadjudicated |
| Newly emitted review prompts | 2 |
| Scheduled / enabled-auto exposure | 60 / 50 synthetic seconds |
| Display timestamp coverage | 1/2 matches; missing measurement remains unknown |
| Measured synthetic display latency | 0.4 seconds; upper bound including specified uncertainty 0.42 seconds |
| Replaying fixed inputs twice | Identical bytes, nine events/decisions, final virtual time 60 seconds |

The resulting 2/6 recall and precision and 240 false decisions per synthetic scheduled hour are **intentional test outcomes**. They do not estimate football-system performance. Small event counts also produce wide statistical intervals. Reports identify the synthetic evidence, absent continuous-footage audit, missing physical alignment, uncertain labels and incomplete display coverage; `release_qualified` is false.

[Complete machine-readable report](baseline-results.json) includes raw counts, intervals, healthy-only recall, error identities/timestamps, session/condition results, annotation checksum and frozen configuration/implementation hashes. [Replay verification](replay-verification.json) records the repeated-output checksum and input fingerprint. See [annotation and evaluation policy](annotation-guide.md) for definitions and command examples.

Validation commands used:

```powershell
.venv/Scripts/python.exe tools/replay.py tests/replay/fixtures/dataset.json --output local_scratch/part03-proof-a.json
.venv/Scripts/python.exe tools/replay.py tests/replay/fixtures/dataset.json --output local_scratch/part03-proof-b.json
.venv/Scripts/python.exe tools/evaluate.py tests/replay/fixtures/dataset.json tests/replay/fixtures/annotations.json local_scratch/part03-proof-a.json --output docs/baseline-results.json
.venv/Scripts/python.exe local_scratch/verify_part03.py
.venv/Scripts/python.exe tools/export_dataset_schemas.py --check
.venv/Scripts/python.exe -m pytest --basetemp local_scratch/pytest-part03-final -p no:cacheprovider --tb=short
```

Result: **59 passed in 20.62 seconds**, including the previous 44 tests. New cases verify deterministic replay/provenance, matching against exhaustive small assignments, duplicates/wrong end/wrong team, human rescues, outage misses, late display independent of crossing tolerance, partial display coverage, uncertainty, known interval values, split/group/hash isolation, blind-split guards, annotation boundaries, asset tampering, causal timing, bounded replay capacity and capture import.

The earlier small Part 02 session `22a2ad5857e64d59b710ddeb37348b04` was also registered through the capture importer and replayed: **150 frame observations, zero goal decisions**, retaining original media PTS and receipt envelopes. Imported annotations are empty and the audit remains pending; observed camera frames do not manufacture ground truth. Metadata is in `local_scratch/part03-imported-small/`, media remains in the original recording directory, and replay is `local_scratch/part03-imported-replay.json`.

Venue baseline: **not available**. Pending work includes ten representative development matches, at least 100 independently adjudicated goals, roughly 300 detector-frame labels, hard negatives, continuous audits, physical time mapping, true blind-source isolation and evaluation of an actual detector/goal engine. Part 02 still has an unresolved live 720p/60-fps capacity shortfall. Software acceptance does not close those field gates.
