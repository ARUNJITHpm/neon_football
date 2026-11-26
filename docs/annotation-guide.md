# Annotation, dataset splits and replay (Part 03)

The Part 03 harness is ready for synthetic checks and recording registration. Its replay uses injected events. Part 04 adds a separate [vision candidate runner and local model adapter](vision.md); neither changes live scores. Venue data collection, human ground truth and trained detector validation remain pending.

## Start with the synthetic challenge

From the project root:

```powershell
.venv/Scripts/python.exe tools/replay.py tests/replay/fixtures/dataset.json --output local_scratch/replay-run-a.json
.venv/Scripts/python.exe tools/replay.py tests/replay/fixtures/dataset.json --output local_scratch/replay-run-b.json
.venv/Scripts/python.exe tools/evaluate.py tests/replay/fixtures/dataset.json tests/replay/fixtures/annotations.json local_scratch/replay-run-a.json --output local_scratch/evaluation.json
```

Outputs are created exclusively; use a new filename for another run. The validation fixture deliberately includes correct automatic decisions, a duplicate, wrong goal end, a human rescue, a pending miss, an automatic decision during an outage, uncertain evidence and a player-impact false positive. Train and synthetic blind-test inputs have separate session IDs, source groups, match IDs, asset checksums and scenarios. `annotations.json` is the validation label file; each other split has its own annotation file. The public synthetic `blind_test` fixture exercises access checks; it is not an untouched model evaluation set.

Run a selected split with `--split train` or `--split blind_test`. Blind-test replay/evaluation requires explicit `--allow-blind-test`; this is a local guard, not access control. For venue work, physically restrict blind media and labels to an independent evaluator, freeze candidate/evaluator versions first, and store labels in separate split-specific files. Do not open the holdout to tune a model. A failed holdout used for development must be replaced.

Generate another small synthetic bundle with `python tools/build_replay_fixture.py --output local_scratch/new-fixture`. The JSON fixtures are hand-authored incident timelines, not simulated football imagery or detector predictions. Actual test-pattern videos from Part 02 remain separate.

## Register recorded media

`tools/import_capture_session.py` imports a cleanly closed Part 02 session, verifies segment/index hashes and byte/frame totals, registers original media without copying it and writes receipt-time frame observations plus an empty annotation draft. Both the capture folder and new metadata folder must be inside `--media-root`.

```powershell
.venv/Scripts/python.exe tools/import_capture_session.py data/recordings/SESSION_ID --media-root data --output data/datasets/session-001 --dataset-id venue-development-v1 --source-group physical-match-001 --match-id match-001 --split train --evidence venue
.venv/Scripts/python.exe tools/replay.py data/datasets/session-001/dataset.json --media-root data --split train --output local_scratch/registered-replay.json
```

Keep camera video, indexes and manifests protected under the venue's agreed data policy. Paths in dataset manifests are relative to the specified media root; absolute paths, `..`, Windows alternate streams and symlink escapes are rejected. Every registered asset is checked before replay. Include annotation clip references as declared/checksummed video or clip assets; missing media references fail validation. The importer registers camera recordings, not optional clip files; add a clip asset when an annotator uses one.

Registration is a draft: the entire receipt span becomes one provisional match window, active-auto windows are empty, observation goal ends are null, physical alignment is false and the audit is not reviewed. Original `TimingEnvelope` values are preserved, including media PTS, absolute host receipt, boot/domain identity and UTC. Session-relative frame times are host receipt minus the first receipt; this is not a physical crossing timeline. Camera payloads flag `goal_end_unmapped`. Configure actual match windows, goal-end mappings and measured timeline transformations before labeling or injecting physical goal decisions. No lens calibration or cross-camera mapping is invented by import.

Merge sessions into one versioned manifest **before** extracting samples. Use a shared `source_group_id` for all fragments, derived clips and views of one physical match/session. Assign every such group to one split. Dataset validation rejects duplicate session/match identities, a source group assigned to different splits, and repeated video/index/event/clip checksums across splits. It cannot detect transformed copies by pixels; source grouping and a human leakage audit remain necessary. Different matches from a common venue may still be correlated; record conditions and camera configuration.

Manifests include dataset and annotation-policy versions, a frozen split-assignment version/time, evidence type (`venue`/`synthetic`), duration, clock domain, calibration/configuration/model versions, scheduled match windows, healthy enabled-auto windows, condition tags and checksummed assets. Match windows are ordered, nonoverlapping half-open intervals `[start,end)`. Healthy windows must lie inside scheduled matches; outages remain in scheduled exposure. A source/domain reset requires explicit epoch mapping or a new session, not silent timestamp subtraction across incompatible clocks.

## Ground-truth procedure

1. Record the initial target of ten representative matches with both goal ends observable, then collect at least 100 adjudicated goals as development evidence. Expand toward the release evaluation floor; these targets are not guaranteed data sufficiency. Synthetic events do not count toward them.
2. Export manual scoring events as rough incident markers. Operator reaction and recording delay make those timestamps approximate. Use them to find footage; do not convert operator decisions directly into reference truth.
3. Independently review the continuous scheduled footage, including periods with no operator marker. Audit unmarked goals, camera gaps, stopped feeds and uncertain portions. A session audit needs reviewer identity and explicit `continuous_footage_reviewed`; no model prediction sets that flag.
4. For every physical incident, assign a stable label ID, session/match ID, goal end, scoring team (required for valid goals), validity (`valid`, `invalid`, `uncertain`), visibility, crossing-time interval, uncertainty, adjudicator, challenge tag, notes and optional registered clip path. Define a goal by the agreed whole-ball crossing rule. A rough marker is not a crossing interval.
5. For valid goals, bracket the whole-ball crossing using the available observations and physical calibration. Include annotation/frame/exposure/alignment uncertainty. Mark insufficient evidence as uncertain; a floor homography cannot resolve airborne depth. Record disagreements and adjudication in a new label version.
6. Label hard cases explicitly: partial crossing, post-and-out, post-and-in, outside-net impacts, player impacts, loose-net motion, ball retrieval, glare and paused play. Save enough context to distinguish a near miss from a valid goal. Do not select only successful goals.
7. Bootstrap around 300 annotated detector frames from the train split, with negatives and varied conditions. Keep adjacent frames and all incident-derived sensor/vision samples in their assigned source group. Expand based on observed errors. No detector-frame labeling tool or training pipeline is implemented in this part.
8. Preserve label versions and checksums; freeze annotation policy, matching tolerance, configuration/model versions and evaluator implementation hash before final evaluation. Never overwrite adjudication history to make a model appear correct.

An annotation file covers exactly one split. Labels must lie inside the declared scheduled match and refer to a known session. The temporal reference is the crossing interval midpoint; uncertainty is half the interval width plus the annotator's explicit uncertainty. Matching does not enlarge its tolerance by that uncertainty. Uncertain labels are counted separately and produce provisional results; they are not quietly treated as valid goals or ordinary negatives.

## Replay contract

`core/dataset.py` and `docs/schemas/{dataset,annotations,replay-event,replay-output}-v1.json` define portable contracts. Export/check schemas with `python tools/export_dataset_schemas.py [--check]`.

Replay event assets are JSONL observations or **injected recorded decisions**. Each event preserves occurrence and delivery seconds, source timing when available, session/match identity, original sequence, goal end, outcome, timing uncertainty and optional clip. Display timestamps require explicit measurement uncertainty. Outcomes distinguish automatic, manual, operator_confirmed, pending, expired and rejected; `shadow` marks hypothetical automatic decisions. `review_required` counts a newly emitted review prompt once; do not mark every repeated lifecycle event as a new prompt. `corrected` means a validity/team correction to that confirmed incident, not an attribution-only edit. Inject a single final decision record per automatic goal attempt; a duplicate goal confirmation has its own event identity and is evaluated as a duplicate.

Replay processes sessions in sorted identity order and events by `(delivered_seconds, sequence, event_id)`. The virtual clock advances without sleep and keeps original occurrence times separate from late receipt. Duplicate event IDs/sequences, causal regressions and invalid session/match bounds are rejected. Configuration/model versions, manifest checksum, asset fingerprint, event limit, original decisions and stable trace are emitted. Running unchanged inputs twice yields identical output bytes. No live SQLite writes, UI updates or automatic scoreboard mutations occur.

The current engine is `injected-decisions-v1`; reproducing those records tests ordering/transport/evaluation, not inference. Part 04 will supply observed candidates and Part 06 the decision engine. Replay loads a session's JSON events for sorting and retains the output trace; it has a 250,000-event total limit (explicit `--max-events`, maximum 2,000,000). Exceeding capacity fails rather than silently dropping events. Partition long recording sets or increase the limit only with measured RAM capacity. No full-match offline performance benchmark is claimed yet.

## Evaluation policy

The default crossing tolerance is **±500 ms**, versioned and fingerprinted in the report. Matching is maximum-cardinality one-to-one assignment, then minimum total absolute crossing-midpoint error (microsecond cost resolution), with stable identity ordering for ties. Match identity, goal end and scoring team must all agree. A greedy matcher could consume the only suitable reference for another nearby prediction; regression tests cover that case.

Automatic successes require an injected automatic decision (including shadow) while the occurrence **and decision delivery** lie in an enabled/healthy-auto interval. Valid goals during outages remain misses in scheduled recall. Any automatic decision while inactive is a false decision even if it resembles a reference goal. Duplicate confirmations, wrong ends/teams and unmatched automatic incidents are false positives. Manual/operator-confirmed decisions may rescue the official score but never improve automatic recall. Pending, expired and rejected incidents are not automatic successes. Shadow decisions are evaluated hypothetically and excluded from official correction-rate denominators.

After certain valid-goal matching, an otherwise unmatched automatic prediction near an uncertain reference at the same end is `unadjudicated_automatic`. These predictions are counted explicitly and excluded from precision/false-positive rates until adjudication, making those metrics provisional. Valid-goal recall excludes uncertain reference labels while publishing their counts. Invalid labels remain inspectable negative evidence. Missing continuous-footage audit also makes counts provisional; unmarked goals cannot be inferred from a curated label list.

Reports include raw counts, scheduled recall and healthy-only recall, precision, false automatic goals per scheduled/active hour, enabled-auto availability, review prompts per goal/hour, validity/team correction rate, display latency/uncertainty distributions and display-measurement coverage. An inspectable error list includes identities, timestamps, reasons, human rescues and clip references. Session and condition-group results are separate; overlapping condition tags are not mutually exclusive totals. Near matches cannot conceal slow display: visible latency uses measured display time minus reference crossing midpoint, independently of crossing matching. Missing display measurements produce null/partial coverage, not assumed zero latency. Negative latencies remain diagnostic clock/label errors.

Proportion intervals use [Wilson's method](https://itl.nist.gov/div898/handbook/prc/section2/prc241.htm); rate intervals use a central Poisson interval from CDF inversion, following the [exact-central rate definition](https://www.statsmodels.org/dev/generated/statsmodels.stats.rates.confint_poisson.html). These descriptive 95% intervals assume independent events; match clustering is not corrected in this prototype. Zero denominators yield null, and zero observed false goals still have a positive upper interval bound. Do not interpret a short synthetic run as a performance guarantee.

The evaluate CLI regenerates replay from checksummed source events and requires exact equality with the supplied replay, preventing edited outputs or stale versions from being evaluated as original evidence. Reports include the annotation checksum, input fingerprint, configuration hash and evaluator/matcher/statistics/contract implementation hash. `release_qualified` is always false for this milestone; Part 08 owns release validation, and no actual vision/goal engine has been evaluated.

## Authorized access and remaining gates

Keep large recordings in protected host-local storage outside Git. Version the small manifest, annotation policy/labels, hashes and synthetic JSON fixtures; venue manifests/labels also require review for participant information before committing. Authorized developers obtain media from the venue data owner under the agreed access/training/retention policy, then verify hashes locally. Do not share operator keys, camera credentials or raw recordings in project notes. No cloud upload or automatic retention job is added here.

Part 03 software acceptance covers deterministic injected replay, challenge accounting and schema split checks. The full field gate still needs representative venue recordings, independent continuous-footage ground truth, split/leakage audit and labeled detector frames. Parts 00–02 venue/browser/timing/capacity gaps remain open. See [baseline results](baseline-results.md) and [implementation progress](implementation-progress.md).
