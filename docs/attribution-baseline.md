# Part 09 generated attribution baseline

The dummy attribution software is verified. Real image recognition, touch detection, camera coverage, field accuracy and rendered operator acceptance remain unmeasured. No automatic mode is qualified. See [rules and reproduction](attribution.md), [machine-readable results](attribution-baseline.json) and [progress record](implementation-progress.md).

## Software evidence

Python 3.12.4 in the existing host-inherited Windows environment; app 0.1.0, SQLite/attribution contracts 1, rules `conservative-attribution-v1`, numeric observations `injected-team-bib-readings-no-ocr-v1`, dataset `dummy-attribution-v1`, API proof `attribution-api-v1`. No new dependencies, model weights or Git revision.

Full suite: **237 passed in 28.36 seconds**. After adding two incident-roster/legacy-create compatibility checks and updating the current package label, focused attribution/release tests: **58 passed in 6.14 seconds**. Thus **239 distinct Python tests passed**, including all prior 186 and 53 Part 09 tests. Five actual-script Node transport/DOM-model checks passed in 328.924 ms after the UI review fixes. There is no browser paint claim.

Checks cover scorer/assist/own-goal rules, opponent interruption, repeated scorer contacts, certain/uncertain deflections/rebounds, missing contact/proximity, occlusion/conflicting identities, source resets/cross-camera isolation, stale/future/insufficient reads, inactive/unknown bibs, ambiguous ordering/timing and declared partial coverage; output consistency, dataset hashes/split leakage/holdout/capacities; score-first pending suggestions, explicit approval/rejection/manual override/undo, stale revisions/exact retries, captured incident/goal rosters across substitutions/ends, invalid substitutions, evidence transaction rollback, backup/recovery/integrity tamper detection, private auth/origin/public redaction and disabled dummy configuration. Console assertions cover substitution commands, scenario retention, unknown Apply gating, Apply/Reject focus, disclosure retention, stale manual drafts and Cancel focus across revisions.

Five attribution schema exports and all prior schema checks pass. `local_scratch/verify_part09.py` verifies paired proof bytes, current source hashes, module import boundaries and documentation links, then writes the baseline JSON. Earlier Part 06–08 hashes remain historical and were not rewritten for the new source.

## Generated replay

Twenty-five explicit generated contact/identity windows have one train case, 23 validation cases and one publicly supplied dummy blind guard. Each case has an explicit generated reference label, independent of the suggestion computation. The blind opt-in demonstrates access control, not a real untouched holdout.

| Field | Correct / evaluated suggestions | Errors | Abstentions | Coverage |
| --- | --- | --- | --- | --- |
| Scorer | 9 / 9 | 0 | 14 / 23 | 39.13% |
| Assist (including explicit none) | 8 / 8 | 0 | 15 / 23 | 34.78% |
| Own goal (true/false) | 9 / 9 | 0 | 14 / 23 | 39.13% |

The 100% fixture accuracy among suggestions has a descriptive Wilson 95% interval of about 70.09–100% for scorer/own goal and 67.56–100% for assist. Scorer/own-goal coverage interval is about 22.16–59.21%; assist coverage 18.81–55.11%. These small challenge cases measure rule behavior, not real recognition accuracy. Lighting, clear-view and overlap tags categorize numerical fixtures; no tagged venue pixels or measured visibility were processed. No clustering adjustment is applied.

The named scorer gate of 98% accuracy / 90% coverage / 100 independent held-out goals remains pending. Scorer coverage here is below that threshold, and synthetic references cannot qualify it regardless of counts. Assist and own-goal venue gates are separately unconfirmed. Unknown predictions are retained as abstentions, never counted as correct names or silently removed from coverage.

Two fresh replays, `local_scratch/part09-replay-a.json` and `part09-replay-b.json`, are byte-identical. Their checksum and manifest/implementation hashes are in the baseline JSON. The runner never opens the official scoring database.

## API proof

Fresh proof directories `local_scratch/part09-proof-c` and `part09-proof-d` produce byte-identical export, JSON/text report and baseline. Sixteen commands/events record two Green goals, one substitution, an accepted goal-time scorer/assist despite the later substitution, an uncertain suggestion rejection, a possible own-goal acceptance followed by manual correction/undo, pause/change ends/end. Final score is Orange 0–Green 1; suggestion statuses are accepted, rejected, accepted. Private/public socket checks preserve attribution evidence and public redaction respectively.

| Artifact | SHA-256 |
| --- | --- |
| Event export | `0b1079ac7631ac35c0067f4aa283c833a1548c206f2d6e4035823634cdf4f718` |
| JSON report | `3c42e546e7c1a79e0df3cde93bfdbee5ac5529ab6fa518d21ab317d6c1408677` |
| Text report | `224450a3210688f69bf33ec986237e2c38894661fea4b5fc17d167d79b0af78e` |

Proof UUIDs are scoped deterministic test identities. Production UUID generation is unchanged. These disposable runs do not modify existing score databases, keys, recordings or servers.

## UI and field limits

Impeccable preserved the incumbent console and ran one mechanical detector pass. Existing font-label and size advisories remain documented. A fresh source reviewer requested stable Cancel focus and shrinkable mobile attribution columns; both were fixed/tested and scored resolved, with disposition **ship at source/test scope**. The [UI documenter record](operator-ui-review.md) preserves the design files. No screenshots, measured contrast, actual keyboard/media or physical HDMI timing were supplied; rendered desktop 1440/mobile 390 acceptance remains pending.

Overhead need/installation/calibration, whole-pitch coverage, OCR/team recognition, physical touch detection, cross-camera handoff, measured temporal uncertainty and independent venue reference adjudication remain dependencies. Goal scoring is still operator controlled. Generated data cannot establish the Part 09 field exit gate.
