# Part 08 software recovery baseline

Date: 11 October 2026. Candidate `neon-score-0.1.0-part08-prototype`; application 0.1.0; operations/retention/backup manifests 1; SQLite schema 1. Python 3.12.4 on Windows in the existing host-inherited environment. No new dependencies, no Git revision, no deployment or purchase.

## Validation

Full regression: `.venv/Scripts/python.exe -m pytest --basetemp local_scratch/pytest-part08-final-01 -p no:cacheprovider --tb=short` — **186 passed in 21.79 seconds**, including the previous 165 plus 21 operations tests. The final evaluator's additional synthetic-provenance guard received a focused passing rerun. Five unchanged client checks passed in 291.49 ms using `node --test --test-isolation=none tests/operator/client.test.mjs tests/operator/operator-dom.test.mjs`. No browser rendering was performed.

New checks cover live WAL backup without source mutation, checksum/incomplete/tampered bundle rejection, new-path restore, retained idempotency/score/evidence, retired reviews and interrupted clock, wrong projection/quarantine, unsupported schema unchanged/released lock, abrupt child exit with committed versus uncommitted state, disabled retention/holds/active sessions/audit preservation, traversal/tamper/replanning guards, authenticated operational status/low disk/null measurements, stopped capture/clip consumer/manual availability, real clip-consumer exception cleanup, package allowlist/hash determinism, dummy release disqualification and bounded supervisor exits.

`tools/recovery_fixture.py` runs in two fresh directories (`local_scratch/part08-proof-g` and `part08-proof-h`). Source match has six commands/events, one committed Green goal and one pending dummy review. A live backup contains those committed records without modifying the source. Restored startup records interruption and unresolved evidence; an exact goal retry is duplicate, followed by clock reconciliation to 42 seconds, resume and end. Final score is Orange 0–Green 1. Restored export and proof metadata are byte-identical across the two runs; creation timestamps in backup completion manifests intentionally differ.

| Artifact | SHA-256 |
| --- | --- |
| Standalone backup database | `50bf2ef79e6399725daec6929346a370b4c784865af4c8eb8453f11510e15abd` |
| Recovered export | `8f462c8a97d486565777cc1726878dbd3265e746e5caaee0f6a0aa752c2e6e23` |

[Recovery JSON](recovery-baseline.json) freezes source/config checksums and result counts. Historical Part 06/07 proof hashes remain historical and are not rewritten. The abrupt-exit test launches only its own disposable child and verifies SQLite recovery, not physical power loss. Existing servers/databases/media were not changed. A sandbox permission issue with restrictive temporary directories was avoided by checked staging to an explicitly owned file; restore performs no recursive deletion.

## Shadow and packaging

Two runs of `tools/release_evaluation.py` produce identical [evaluation JSON](release-evaluation.json) and freeze the input/config/evaluator/source hashes. Nineteen dummy validation sessions span 93.1 synthetic seconds, with 37 candidates, 15 valid references, seven matched shadow confirmations, eight misses, zero false shadow confirmations, one operator confirmation, four ignored evidence inputs and one rejected command. Dummy recall is 7/15 (46.67%, Wilson interval roughly 24.81–69.88%). Zero false goals has an exact central Poisson 95% upper rate around 142.64/hour over this short simulated duration. Seven virtual decisions have p95 0.32 seconds. These are challenge results and cannot establish venue accuracy or rendered latency; field metrics are null and all release gates pending.

The source candidate builder produces two byte-identical ZIPs with fixed archive timestamps, per-file hashes, an internal/detached manifest and archive checksum. It excludes live/private files and includes code, safe config templates, generated review pattern and established public prototype guides/results. Tests verify every archive member against its manifest. Dependency wheels, real model weights, compiled firmware and selected hardware are absent. Clean installation, service/HDMI operation and release qualification are false/pending; the package is reviewable prototype source only.

Two operations schema checks, prior contract schema checks, module boundaries, current source hashes and documentation links are checked at completion. The [runbook](runbook.md) records startup/supervision, physical scoring fallback, interrupted-clock reconciliation, integrity quarantine, backup/restore, proposed retention with training holds, and compatible update rollback. [Release evaluation](release-evaluation.md) preserves the independent field/pilot gates.

Exit: **available software recovery/operations verified; hardware deployment, physical recovery and automatic-release gates pending**. Default media retention is disabled; audit log/metadata are retained indefinitely pending venue decisions. Capture freshness/drop/lag and process CPU telemetry exist; physical serial/inference queue health, memory/temperature, sustained HD capacity, independent fallback practice, backup off-host/retention policy and browser/HDMI acceptance remain open. No automatic pilot or real footage collection occurred.
