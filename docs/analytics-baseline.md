# Part 10 generated contact analytics baseline

Dummy pass/interception/possession rules and corrected team/player reports are verified. Real overhead tracking, pixel/contact recognition, independent field accuracy and rendered display acceptance remain pending. See the [analytics guide](analytics.md), [machine-readable proof](analytics-baseline.json) and [progress log](implementation-progress.md).

## Software verification

Python 3.12.4/Windows in the existing host-inherited environment; app 0.1.0, SQLite/analytics contracts 1, rules `contact-analytics-v1`, dataset `dummy-contact-analytics-v1`, replay `contact-analytics-replay-v1`, API fixture `contact-analytics-api-v1`, source candidate `neon-score-0.1.0-part10-prototype`. No new dependencies, trained model, installed hardware or Git revision.

Full Python suite: **282 passed in 41.04 seconds**, including all previous 239 and 43 Part 10 tests. After adding named-player contact rows to the final report, nine analytics workflow checks passed in 5.77 seconds. Existing five actual-script client/DOM checks passed in 501.673 ms. No frontend markup, styles or behavior was changed for this part; reports use the existing protected download route. No browser rendering is claimed.

Checks cover exact event identities, sender/receiver credit, source/boot/play/roster boundaries, same-player contacts, unknown/inactive IDs, proximity, uncertainty clusters, missing clock bounds, adjacent paused contacts, possession expiry, time/percentage conservation, null zero-duration percentages, complete/partial coverage, contracts/split/hash/holdout/capacity guards, corrections/void/restoration without source mutation, atomic disk failure, stale/exact retries, goal corrections/undo/own-goal separation, immutable audit consistency, backup/recovery, authentication/origin/private/public socket redaction, multiple separately scoped sessions and disabled/absent analytics. Four new and all prior schema exports pass.

## Generated replay

The supplied twelve windows include one train, ten validation and one public dummy blind-test guard. They are explicitly authored numeric contact/time challenges. Expected event pairs, team/player identities and possession totals are specified separately from the analytics implementation. Label creation does not invoke the rule engine. Source/match/hash isolation and explicit blind opt-in are enforced; public dummy cases are not an untouched independent holdout.

| Validation metric | Result |
| --- | --- |
| Windows | 10 |
| Completed passes | 7 reference events matched; 0 false, 0 missed |
| Interceptions | 4 reference events matched; 0 false, 0 missed |
| Orange possession mean absolute error | 0 generated seconds |
| Green possession mean absolute error | 0 generated seconds |
| Unknown possession mean absolute error | 0 generated seconds |

The zero errors verify these rule/reference examples. They do not measure physical recognition or real possession accuracy. Fixtures deliberately use zero declared uncertainty for exact reference arithmetic; separate unit/API checks use nonzero/missing/overlapping bounds. Unknown, paused and dead-ball time remains explicit. Condition tags for lighting/overlap describe numerical categories, not actual images. Field precision/recall/coverage/share gates remain pending with field qualification false.

`local_scratch/part10-replay-a.json` and `part10-replay-b.json` are byte-identical; their checksum and current implementation/manifest hashes are in the baseline JSON. Offline replay never opens a score database. `local_scratch/verify_part10.py` verifies paired API/replay bytes, current source/asset hashes, module boundaries and local document links, then records this checkpoint. Earlier Part 06–09 proofs remain historical.

## API and corrected report proof

Fresh `local_scratch/part10-proof-c` / `part10-proof-d` produce identical exports, JSON/text reports and baseline. Eighteen committed commands/events and one exact duplicate retry include three goals, approved player changes, an own-goal undo, four generated analytics windows, three appended contact corrections including void/restoration, pause/end changes/resume/end, retrospective generation, private evidence and public redaction. Final score is **Orange 1–Green 1**. Green Eleven has the one active approved ordinary goal; Orange's active scorer is unknown. The undone own goal contributes no current player own-goal tally. Generated window counts are separate from these official totals and are not summed as official match possession.

| Artifact | SHA-256 |
| --- | --- |
| Event export | `8b73d1d63c09b75d6103fe15ad7de51f6da5789e9faa92644fbbf38235dc1193` |
| JSON report | `6d0fa185dfbdc969e2ffbf611420d4e5e1cc1b2a1e752f7c00291598303869d5` |
| Text report | `84f41fe84e9ee129a01a180142806685a5e02e5a1d54a70d74fc485ecde6cfb0` |

Fixture UUID generation is scoped to reproduction; production UUIDs are unchanged. Repeated report downloads remain identical after virtual-clock advancement once ended. Backup/recovery tests preserve analytics evidence and corrections while interrupting the actual live match clock. No existing database, operator key, recording or server was modified.

## Limits and next dependency

Analytics generation/corrections currently use the authenticated command API or disposable proof tool. Download report is already available in the console. There is no new dashboard, narrative service or external publishing/sharing action. Real camera/overhead coverage and calibration, independently reviewed contact/ownership labels, source timing/identity continuity and metric-specific field acceptance must precede real analytics.

Distance, heatmaps, shot statistics, aerial tracking, LLM narrative, highlights and player cards remain unavailable or unimplemented. A contact's shot cue is not a validated shot count. Browser/keyboard/media/HDMI, actual firmware/sensors, detector training, real sustained HD capacity, isolated deployment and automatic scoring/release gates also remain open.
