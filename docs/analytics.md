# Part 10 contact analytics and corrected reports

This prototype computes passes, interceptions and bounded possession estimates from generated numeric contacts. It does not detect players or touches from video, use overhead camera coordinates, or measure real match possession. Official score/player statistics are reconstructed from approved, corrected goal events. Generated contact windows are reported separately and are never summed as official match totals.

## Use the available workflow

The existing authenticated `/report` and `/report.txt` routes now include official team/player totals and any stored generated analytics windows. **Download report** in the operator console uses the enriched text report. No new dashboard, camera tracking, external sharing or narrative generator is enabled.

The quickest demonstration creates a disposable match/database and writes readable JSON/text reports:

```powershell
.venv/Scripts/python.exe tools/analytics_fixture.py local_scratch/analytics-new-proof
Get-Content local_scratch/analytics-new-proof/report.txt
```

Use a new destination; the fixture does not touch existing databases or keys. To attach an example to a match through the authorized command API, use its current match revision and a new command ID:

```json
{"schema_version":1,"command_id":"analytics-example-1","expected_revision":3,"action":"demo_analytics","payload":{"scenario":"passing"}}
```

Send to `POST /api/v1/matches/{match_id}/commands` with the operator bearer key. Replace revision 3 with the actual current revision; stale revisions fail. Available examples are `passing`, `pauses`, `gaps`, `uncertain`; default is `passing`. `demo_review_enabled` controls new generated analytics examples even in manual mode. A committed example can be reviewed after the match ends. Generation does not require live play, start/pause/reset the clock, or change score, candidates or goal attributions. Normal elapsed-time boundaries still commit with each command.

The private snapshot contains `analytics_sessions`. Each retains immutable source contacts, captured registered/active roster, relative time periods, revision and appended corrections. Example timestamps begin at zero in a synthetic 12- or 25-second window; they are independent of the official clock and goals. Missing players remain unknown; the generator never invents names or borrows goal-attribution windows as a match timeline.

To correct a contact, inspect its `session_id` / `touch_id`, then send all replacement classification fields with the current match revision:

```json
{"schema_version":1,"command_id":"analytics-correction-1","expected_revision":4,"action":"correct_analytics_touch","payload":{"session_id":"analytics-example-id","touch_id":"touch-1","player_id":"green-7","kind":"control","certainty":"certain","void":false}}
```

The player must be active in the source session's captured roster. Null means unknown. `void=true` records that this source contact is invalid and excludes it; a later `void=false` correction can restore it. Corrections replace player/kind/certainty, not source timestamp, uncertainty or play boundaries. A corrected report is recomputed from the original evidence plus ordered corrections. No original evidence is overwritten, and exact command retries do not append another correction.

## Definitions

These prototype definitions and numeric field gates require venue/operator agreement before real use.

| Metric | Prototype rule |
| --- | --- |
| Completed pass | Certain `controlled_pass`, followed within three seconds by a different known teammate's certain controlled contact |
| Interception | Certain controlled opponent change within three seconds, with an explicit `interception` cue on the receiving contact |
| Player pass/receipt | Credit the completed pass to its sender and receipt to its receiver |
| Possession | Known player's certain controlled contact supplies a bounded last-control estimate until the next contact, play/roster boundary or three-second expiry |
| Unknown possession | In-play duration not supported by a bounded, certain active-player control interval |
| Official goals/assists/own goals | Active confirmed goals with latest operator-approved attribution; undone goals contribute nothing |

Controlled kinds are `control`, `controlled_pass`, `interception`, `shot`. An opponent control without an interception cue changes ownership but is not automatically called an interception. Repeated same-player contacts are not passes. Incidental deflections/rebounds, uncertain/unknown contacts and inactive/unknown identities interrupt the event chain. Proximity is neither a contact nor a pass cue.

Contacts must be non-overlapping in their uncertainty intervals and share source, boot, play epoch and roster revision to form an event chain. Cross-camera/source handoff is not assumed. Time-local roster epochs preserve stable player identities through substitutions. Events never connect across paused, dead-ball, unknown-state or incomplete-coverage periods. Even adjacent complete periods reset the chain, allowing the caller to declare a restart/source boundary explicitly.

Possession begins at `contact time + uncertainty` and stops before `next contact time - uncertainty`. Unknown intervals remain in the denominator. Source uncertainty above 20 ms, overlapping contact groups, uncertain identity and contacts straddling a play/roster boundary do not acquire ownership. A missing clock bound in a playable period leaves that whole period unknown. An adjacent contact whose uncertainty overlaps the play boundary invalidates the affected playable period. These defaults are unmeasured; they are not calibrated physical confidence estimates.

Time accounting partitions the full window into in-play, paused, dead-ball and unknown-state seconds. Only in-play time enters possession percentages. Green + Orange + unknown possession equals in-play duration. If there is no in-play duration, percentages are null. Paused/dead-ball time cannot become possession, and possession is not extrapolated through a long gap. Player possession seconds reconcile with team possession seconds.

`metric_status` describes usable contact/count evidence: available, partial or unavailable. The report always shows unknown possession separately even when declared contact coverage is complete. Counts in a partial window are observed counts, not an estimate of missed events. No analytics session means analytics unavailable, not a measured zero-pass match.

## Reports, boundaries and recovery

`official_statistics` contains team score, attributed/unknown-scorer goal totals and registered player goals/assists/own goals. Player corrections move contributions to the latest approved player; undo removes contributions. An opposing player's own goal contributes to that player's own-goal tally and the already awarded scoring team's score. It never becomes an ordinary goal for the opposing team. Pending/unapproved attribution suggestions are excluded.

`contact_analytics` contains individual generated windows with team/player passes, received passes, interceptions, possession, unknown time, event identities and reasons. Multiple examples can overlap their relative clocks; therefore no combined official possession total is produced. Field qualification is false. Distance, heatmaps, shots and shots on target are explicitly unavailable. A contact kind called `shot` is only a controlled-contact cue here; it does not populate a shot statistic.

App composition calls the storage report reconstruction and stats module. Storage imports only core/its own module and retains evidence/correction events. Reports recompute analytics rather than persisting derived totals. Integrity inspection compares source and corrections against immutable events and validates session identity/roster/provenance. Backup/restore preserves both; host recovery still interrupts the official live clock without altering retrospective generated sessions. Transaction failures leave no partial evidence or acknowledgment.

Authentication/origin protections apply to analytics generation, correction, private snapshots, reports and exports. Public scoreboard snapshots/socket omit source contacts and analytics. Capacity limits are 100 live examples per match, 128 KiB per submission and 1,000 corrections per session. Offline contracts cap windows at four hours, 10,000 contacts, 1,000 time/roster periods; replay additionally checks bytes, aggregate contacts and resolution work. These are software bounds, not measured sustained venue performance.

## Evaluation and remaining gates

Twelve checksum-registered generated windows contain one train, ten validation and one public dummy blind guard. References specify expected event IDs, player/team identities and possession-time totals independently of the analytics implementation. Hash, match and source groups cannot leak across splits. The replay evaluates exact event identities and time error, not merely counts. [Recorded results](analytics-baseline.md) retain raw denominators and provenance. Light/overlap tags are numerical categories, not venue image evidence; the public dummy blind guard is not an independent holdout.

Proposed field gates, all pending:

| Metric | Proposed gate | Minimum independent held-out evidence |
| --- | --- | --- |
| Pass | Precision at least 95%, recall at least 90% | 200 reference passes across multiple matches |
| Interception | Precision at least 95%, recall at least 90% | 100 reference interceptions across multiple matches |
| Possession | Team share error at most 5 percentage points; known possession time at least 90% of in-play | 60 annotated in-play minutes across multiple matches |

Before evaluating field gates, agree metric/deflection/interception rules, establish camera coverage and identity continuity, calibrate pitch coordinates/source clocks, and independently annotate controls, event pairs and ownership intervals including unknown/dead-ball time. Split by match/source, freeze parameters before holdout access, measure errors/coverage by end, lighting, overlap and occlusion, and report confidence intervals with match clustering. Never normalize away unknown possession to improve a headline percentage.

Overhead installation/calibration, real team/bib recognition and contact detection, cross-camera handoff, tracking gaps, aerial-ball treatment, distance/heatmaps/shot validation, optional LLM narratives/highlights/cards/sharing and rendered browser acceptance remain future work. Real metric gates have not passed. Automatic scoring stays disabled.

## Reproduce offline checks

```powershell
.venv/Scripts/python.exe tools/export_analytics_schemas.py --check
.venv/Scripts/python.exe tools/build_analytics_fixture.py local_scratch/analytics-new-fixtures
.venv/Scripts/python.exe tools/analytics_replay.py tests/stats/analytics-fixtures/dataset.json --output local_scratch/analytics-new-replay.json
.venv/Scripts/python.exe -m pytest tests/stats/test_analytics.py tests/stats/test_analytics_workflow.py --basetemp local_scratch/pytest-analytics-new -p no:cacheprovider --tb=short
```

Fixture/proof builders require new directories; replay uses exclusive output creation. Offline replay never opens a scoring database. Historical Part 06–09 baselines remain unchanged; their source hashes describe earlier checkpoints.
