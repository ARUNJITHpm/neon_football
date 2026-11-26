# Neon Football Auto-Scoring — Part-by-Part Implementation Plan

Created: 8 October 2026  
Status: Parts 01–10 available prototype software implemented with generated capture/replay/vision, dummy sensor/fusion evidence, operator review, recovery, attribution and contact analytics. Real input/recognition/overhead integration, firmware compilation/hardware, independent evaluation/training, venue requirements, browser acceptance and field/release gates remain pending. See [implementation progress](docs/implementation-progress.md).
Inputs: [Original concept](neon-football-auto-scoring-build-plan.md) · [Review and improvements](PROJECT_REVIEW.md)

## How to use this plan

Work through the numbered parts and mark tasks complete only when their exit evidence exists. Suggested paths below are deliverables to create, not files already present. Maintain one short completion note per part with the code revision, configuration/model versions, tests, measured results, and remaining limitations.

The original venue facts are the starting assumptions: one 15 m × 10 m cage, 3v3, no goalkeeper, owner approval for recording, and an unknown existing scoreboard interface. Part 00 confirms the missing measurements and operating rules.

Recommended scope is automatic team scoring in v1, player attribution in v1.1, and broader analytics in v2. This sequencing changes the original v1 scope; if automatic scorer names are required for launch, move the Part 09 gate before production activation. No schedule or accuracy is guaranteed by this document.

## Work sequence and dependencies

| Part | Outcome | Depends on | Status |
| --- | --- | --- | --- |
| 00 | Venue requirements and camera feasibility | None | Worksheets created; venue evidence pending |
| 01 | Durable manual scoreboard and application core | 00 operating rules; scaffolding can start earlier | Software implemented; browser gate pending |
| 02 | Camera capture, calibration records, and timing | 00, 01 event contracts | Fixture-tested software; field/capacity gates pending |
| 03 | Ground-truthed dataset and replay harness | 01, 02 | Synthetic replay/evaluator verified; venue dataset pending |
| 04 | Offline vision and crossing candidates | 03 | Synthetic logic/ONNX adapter verified; model/field/live-budget gates pending |
| 05 | Instrumented goal sensors and impact classifier | 00, 01, 02 timing contract; bench work can overlap 03–04 | Dummy transport/timing/impact rules verified; firmware/hardware gates pending |
| 06 | Fusion and goal lifecycle | 03, 04, 05 | Dummy shadow rules/lifecycle verified; integration and field gates pending |
| 07 | Integrated operator workflow and reliable display | 01, 06 | Dummy software verified; browser/HDMI/field gate pending |
| 08 | Failure recovery, shadow evaluation, and v1 release | 02–07 | Recovery/operations software verified; deployment/field/release gate pending |
| 09 | Scorer, assist, and own-goal attribution | 03, 07; validated player coverage | Dummy software implemented; real recognition/coverage/venue gate pending |
| 10 | Overhead analytics and optional reporting features | 08, 09; calibrated overhead views | Dummy contact metrics/corrected reports implemented; overhead and metric field gates pending |

Parts 00–03 form the first useful milestone. Parts 04–07 turn recordings into reviewable goal decisions. Part 08 is the production gate. Parts 09–10 have independent quality gates.

Planning assumption: the original 18-week horizon may be retained as a provisional budget envelope, not a promise. Re-estimate after Part 00 hardware trials and Part 03 data collection. Allow at least 14 calendar days for the proposed shadow gate, and longer if the required goals and operating hours have not been observed. Assign a software owner, vision/data owner, and venue/operator owner; one person may cover several roles.

## Shared design decisions

- **Deployment:** One service per cage with supervised workers. Keep the modular monolith and local operation. Select the actual deployment OS/GPU in Part 00; pin Python, capture, GPU runtime, inference, and dependency versions against that choice.
- **Modules:** `core` contains contracts; `app` wires modules. Define storage commands/acknowledgements and interfaces in `core` so score durability does not require direct imports between modules.
- **Data paths:** Bounded queues/frame references for high-volume camera data; a transactional durable path for accepted scoring commands and corrections. Each subscriber must receive the events it needs.
- **Truth:** A confirmed score is a projection of committed events. Images, predicted tracks, and sensor impacts are evidence; they are not themselves confirmed goals.
- **Uncertainty:** Missing evidence produces an explicit unknown or pending result. No operator timeout confirms a goal. Scorer uncertainty never delays a confirmed team score.
- **Time:** Preserve acquisition/source time, receipt time, clock domain, source sequence, offset estimate, and uncertainty. Use monotonic elapsed time for live timing, UTC for audit records, and a virtual clock for replay.
- **Media:** Persist scoring decisions before broadcasting them. Save review clips asynchronously and emit clip-ready or clip-failed status later.

## Measurement and release contract

Freeze the evaluator, label policy, and thresholds before final testing. These are proposed product gates, not claims of achieved performance.

| Measure | Definition | Proposed gate |
| --- | --- | --- |
| Automatic goal recall | Correct automatically confirmed goals / all adjudicated valid goals in the scheduled evaluation period | At least 97% for v1 |
| False automatic goals/hour | Automatic confirmations with no matching valid goal / scheduled evaluation match-hours | Below 1/hour; also report per active-auto hour |
| Automatic precision | Matched automatic confirmations / all automatic confirmations | Report alongside recall; tighten the product target after baseline |
| Visible-score latency | Time from ground-truthed whole-ball crossing to rendered updated score, for correct automatic confirmations | p95 below 1 second; report p50, p99, maximum, and timing uncertainty |
| Review workload | Candidates requiring human action / adjudicated valid goals, plus prompts per hour | Proposed target at most 10% and at most 2 prompts/hour; tune with the operator |
| Score correction rate | Confirmed goals subsequently corrected for validity or team / all confirmed goals | Below 5%; attribution corrections reported separately |
| Availability | Time automatic mode is healthy and enabled / scheduled evaluation match time | Proposed target at least 99%; report all outages |
| Attribution quality | Correct named scorers / named scorers, and named scorers / all valid goals | Part 09 gate; never hide low coverage behind high accuracy |

Match predictions to ground truth one-to-one by match, goal end, and crossing timestamp. Start with a documented ±500 ms event matching tolerance, validate annotation uncertainty in Part 03, and freeze the tolerance before blind evaluation. Duplicates count as false positives; unmatched labels count as misses. Evaluate crossing timestamps for matching and separate display timestamps for latency so the tolerance cannot hide a slow update.

Pending, expired, manually added, and operator-confirmed goals do not count as automatic successes. Shadow-mode auto decisions are scored as if they had been committed, without changing the official scoreboard. Include outages in recall/availability; report healthy-only results additionally. Label uncertain cases separately with their count and reason rather than silently dropping difficult footage.

Suggested final evaluation floor: at least 300 adjudicated goals, 20 full-match hours, both goal ends, and 14 calendar days of representative shadow operation. These quantities can be increased and do not guarantee statistical certainty. Publish raw counts, 95% uncertainty intervals, and per-session/per-condition results; account for clustering within matches where practical. Treat this as a provisional pilot gate, not proof that future recall is at least 97%. Keep the test set blind until the release candidate is frozen; a failed test used for tuning requires a fresh final holdout.

## Part 00 — Confirm venue rules, measurements, and feasibility

**Purpose:** Establish what counts as a goal and whether the cameras can observe it.  
**Owner role:** Venue owner/operator with the vision implementer.  
**Addresses:** R01, R03, R12 and specification corrections.

- [ ] Measure goal width, height, depth, net geometry, ball diameter, roof height, and camera-to-goal distances.
- [ ] Confirm scoring rules, fouls/operator authority, side changes, kick-off/restart rules, match duration, pauses, and own-goal/assist conventions.
- [ ] Confirm display inputs, tablet access, power, cable routes, mounting, and actual lighting conditions.
- [ ] Trial a fixed camera under match lighting. Record slow and fast goals, partial crossings, high shots, rebounds, player occlusion, and outside-net impacts.
- [ ] Decide whether each view can support reliable goal-plane evidence. Record ambiguous regions; plan another view or revised placement if required.
- [ ] Separate required v1 hardware from attribution/analytics hardware. Build a complete bill of materials, obtain quotes, and select the host platform after a capture/inference trial.
- [ ] Document recording access, retention, training use, deletion handling, and the person responsible for venue data.

**Deliverables:** `docs/requirements.md`, `docs/venue-survey.md`, `docs/hardware.md`, `docs/data-policy.md`, annotated camera-layout images.

**Exit evidence:** Measured venue configuration, agreed rules, candidate views with visible challenge examples, and a costed prototype configuration. An unresolved crossing-visibility problem blocks automatic-scoring claims, but manual-score development can continue.

## Part 01 — Build the durable core and manual scoreboard

**Purpose:** Create a usable scoring tool and an event source for data collection.  
**Depends on:** Part 00 operating rules.  
**Addresses:** R05, R06, R10.

- [x] Create the repository skeleton from the original plan, a dependency lock, an example configuration without secrets, and setup instructions. (Part 01 modules exist; clean installation from lock remains to be verified.)
- [x] Define versioned commands/events: match created/started/paused/resumed/ended, candidate created, goal confirmed/rejected, attribution changed, correction applied, and health changed. (Health event type is reserved for later worker integration.)
- [x] Include event ID, command ID, match ID, sequence/revision, occurrence time, recorded time, actor/source, correlation ID, and schema version. Allow nullable scorer and assist IDs.
- [x] Implement a single-writer SQLite transaction for accepted commands, event append, and score projection. Acknowledge only committed changes.
- [x] Support idempotency keys, expected-revision conflict handling, stable goal IDs, candidate-linked confirmation, and immutable correction records.
- [x] Build match setup, roster/team-to-goal mapping, clock controls, manual goal, undo, current-state snapshot, and event export.
- [x] Provide a small operator page and read-only scoreboard. Keep manual scoring usable without cameras, sensors, or model files. (Browser acceptance pending.)
- [x] Define restart handling: restore committed state and mark an interrupted clock as needing operator reconciliation.

**Deliverables:** `core/`, `modules/storage/`, `modules/api/`, `app/main.py`, `app/config/cage.example.yaml`, `README.md`.

**Exit evidence:** A full simulated match can start, pause, score, undo, end, and export. Duplicate submissions count once; concurrent edits receive explicit outcomes; a restart restores the last committed score. Critical state and persistence tests run without hardware.

## Part 02 — Capture video and establish time alignment

**Purpose:** Produce trustworthy synchronized recordings and bounded live input.  
**Depends on:** Parts 00–01.  
**Addresses:** R01, R04, R10, R13.

- [x] Implement independently supervised camera readers and record camera ID, frame sequence, source timestamp when available, host receipt timestamp, resolution, and actual frame rate. (Two FFmpeg file feeds tested; real devices pending.)
- [ ] Document timestamp quality when exposure timestamps are unavailable. Estimate delay and offset with visible/physical synchronization events; measure drift over a session. (Quality documented; marker fitting/holdout tool and synthetic checks implemented. Physical delay/drift evidence pending.)
- [x] Define a common timing envelope for later sensor data and explicit clock-reset detection.
- [x] Keep a bounded live inference queue and a recording/clip path with measured capacity. Record dropped frames and gaps; do not let old frames accumulate silently. (Delivery-lag growth reported; 720p/60-fps fixture did not demonstrate live capacity.)
- [x] Store camera intrinsics/distortion, goal/pitch calibration, ROI versions, and camera placement with each recording manifest. (Validation/snapshot software exists; missing/draft/invalid calibration is explicit. Venue measurements pending.)
- [x] Implement the pre-event clip buffer, delayed post-event capture, and asynchronous clip status. Benchmark RAM, disk throughput, and actual bitrate. (Short synthetic benchmark measured RAM, encoded rate and buffered write-call throughput; sustained venue storage test pending.)
- [x] Add camera heartbeat, stale-feed detection, reconnection, and invalid-calibration handling.

**Deliverables:** `modules/capture/`, `core/clock.py`, `tools/calibrate_camera.py`, `tools/check_sync.py`, recording manifest schema.

Implementation details and commands: [capture guide](docs/capture.md). Results and remaining gates: [Part 02 progress](docs/implementation-progress.md#part-02--software-implemented-field-and-capacity-gates-pending).

**Exit evidence:** Both goal cameras record a complete session with a gap report and measured timing uncertainty. A temporary disconnect recovers cleanly. Proposed initial alignment target is p95 error at most 20 ms; if unmet, quantify the effect on crossing/fusion and revise the design before enabling auto mode.

## Part 03 — Collect labels and build deterministic replay

**Purpose:** Make every algorithm change measurable before deployment.  
**Depends on:** Parts 01–02.  
**Addresses:** R07–R09.

- [ ] Record an initial 10 representative matches with both ends visible; collect at least 100 labelled goals as a development milestone, then expand toward the final evaluation floor.
- [ ] Use the operator goal button as a rough marker. Review footage to mark exact crossing intervals, goal end, validity, visibility, and uncertainty; audit continuous sessions for unmarked goals.
- [ ] Capture hard negatives: partial crossings, post-and-out, post-and-in, outside net impacts, player impacts, loose net motion, ball retrieval, glare, and paused play.
- [x] Assign train, validation, and blind-test sessions before extracting frames or sensor windows. Keep adjacent frames and clips from one session in the same split. (Contracts/guards and synthetic assignments implemented; real-session assignment/leakage audit pending.)
- [ ] Bootstrap approximately 300 labelled frames and expand based on observed failures; treat original frame counts as budgets, not guaranteed sufficiency.
- [x] Build a replay runner using a virtual clock, stable event ordering, original timestamps, and stored configuration/model versions. Inject recorded detections when deterministic engine regression is needed. (Part 03 injected observations/decisions replayed deterministically; Part 04 adds separate vision-candidate replay. Goal fusion remains Part 06.)
- [x] Implement event matching and the shared metrics contract. Produce machine-readable results and an inspectable error list with clip references. (Synthetic challenge counts, uncertainty, outages and human rescues verified; no detector accuracy claimed.)
- [x] Keep large recordings outside Git; version manifests, labels, checksums, and small synthetic fixtures. Document how authorized developers obtain recordings. (Fixtures/schemas/docs exist; no Git repository or commit is claimed.)

**Deliverables:** `tools/replay.py`, `tools/evaluate.py`, dataset manifests, annotation guide, `tests/replay/` fixtures, `docs/baseline-results.md`.

Software evidence: [synthetic baseline](docs/baseline-results.md), [annotation guide](docs/annotation-guide.md), [Part 03 progress](docs/implementation-progress.md#part-03--replay-and-evaluator-verified-venue-dataset-pending). Real match/goal/frame collection tasks above remain unchecked.

**Exit evidence:** Replaying fixed inputs twice yields identical goal decisions. The evaluator correctly penalizes duplicate goals, wrong ends, misses, and operator rescues. Data splits have no session overlap. This closes the first milestone.

## Part 04 — Build vision and physically meaningful crossing candidates

**Purpose:** Establish an offline baseline before fusing extra evidence.  
**Depends on:** Part 03.  
**Addresses:** R01, R04, R08–R09.

- [ ] Benchmark a pretrained detector on venue footage before fine-tuning. Record model version, licence decision, input size, precision, and hardware.
- [ ] Train/adapt ball and player detection with blurred, partially occluded, and difficult lighting samples; retain ordinary negative frames.
- [x] Track the ball per view and retain observed versus predicted positions, uncertainty, track age, and evidence quality. (One bounded track per view; injected/synthetic evidence tested.)
- [x] Implement calibrated goal-opening checks, inward motion, whole-ball margin, and an uncertainty region. Never use a floor mapping as airborne depth truth. (Consumes externally supplied registered depth; physical camera/depth-rig calibration pending.)
- [x] Use prediction to bridge brief gaps for candidate generation; require sufficient observed evidence for automatic confirmation later. (Predicted candidates require review; all automatic confirmation is prohibited.)
- [x] Add net-motion evidence with a rolling baseline and quality flags; expose camera shake and player overlap as features. (Numeric image tests and recorded patterns; field quality pending.)
- [ ] Benchmark simultaneous streams, decode/preprocessing, inference, and queue age. Adjust ROI, resolution, scheduling, or hardware from measurements. (Two-worker offline profiles completed; HD image path under 60 fps even with Constant model. Real-model/live queue-age/sustained budget pending.)

**Deliverables:** `modules/vision/`, calibration validator, model evaluation report, `vision_candidate` events.

Software evidence and limits: [vision guide](docs/vision.md), [validation and model baseline](docs/vision-baseline.md). No pretrained model was available; a checksum-verified synthetic ONNX graph tests runtime execution only. The real detector/adaptation tasks above remain unchecked.

**Exit evidence:** On held-out development replay, candidate recall is at least 90% and false candidates are below 2/hour as an initial engineering target. Report this separately from confirmed-goal metrics. Partial crossings and depth ambiguity route to uncertainty; both camera feeds stay within the measured processing budget.

## Part 05 — Build sensor firmware and validate impact evidence

**Purpose:** Supply time-aligned net/frame evidence with known failure behavior.  
**Depends on:** Part 00 geometry and Part 02 timing contract; bench work may overlap Parts 03–04.  
**Addresses:** R02, R04 and the ADXL345 sampling correction.

- [ ] Fit one back-net and one frame accelerometer per goal and record their orientation and attachment method.
- [ ] Choose a supported output data rate, such as 800 Hz initially, and verify fresh-sample capture with FIFO/interrupt handling and adequate interface bandwidth. Do not label repeated reads as native 1 kHz samples. (800 Hz protocol and FIFO/IRQ/SPI scaffold exist; firmware build and actual sampling/bandwidth pending.)
- [x] Define framed packets with protocol version, device/boot ID, sample sequence, device timestamp, sample rate, sensor values, integrity check, and health status. (NFSP v1 byte order/CRC/fragmentation/limits verified.)
- [x] Implement host alignment, drift estimation, dropped-packet detection, serial reconnect, device reboot handling, and saturation detection. (Dummy sources/markers/faults verified; physical timing and serial trials pending.)
- [ ] Record raw signals for labelled goal, frame, wall, player, and noise events. Group train/test windows by match and physical incident. (Generated raw streams/grouped labels and split guards exist; no physical impact collection.)
- [x] Start with an inspectable feature baseline. Define a causal decision window, for example 400 ms before and 100 ms after an impact; validate its latency and accuracy rather than assuming a full future 0.5-second window. (Causal rules, coverage/quality/confusion/latency tested with dummy waveforms; field accuracy pending.)
- [x] Keep raw review samples for diagnosis even if firmware later emits summary events. Add a net/frame baseline check before each match. (Raw fixture/index retention and quiet/gravity/RMS checks verified; actual mounting/self-test/production recording pending.)

**Deliverables:** `firmware/esp32/`, `modules/sensors/`, protocol document, classifier evaluation and timing report.

Dummy-data software evidence: [sensor protocol](docs/sensor-protocol.md), [sensor baseline](docs/sensor-baseline.md), [firmware scaffold](firmware/esp32/README.md). All impacts remain possible-goal evidence and prohibit automatic confirmation; class labels cannot veto a crossing. Firmware has not been compiled or flashed.

**Exit evidence:** Every sensor has known sample rate and timing quality. Disconnect, packet loss, reboot, and loose/saturated sensors are observable. Post-and-in goals are retained as possible goals; classifier results include per-class confusion and impacts/hour, not only window accuracy.

## Part 06 — Implement fusion and candidate lifecycle

**Purpose:** Turn evidence into bounded, auditable decisions.  
**Depends on:** Parts 03–05.  
**Addresses:** R01–R02, R04–R07.

- [x] Maintain independent candidate identities per goal end and incident; keep match lifecycle separate from candidate lifecycle. (Offline engine and nearby-track ambiguity checks verified.)
- [x] Use occurrence timestamps and synchronization uncertainty when correlating evidence. Configure evidence age, late-arrival handling, and a measured fusion window. (Prototype 200 ms window/300 ms collection and age/deadline rules verified; physical window measurement remains pending.)
- [x] Start with explicit rules: valid observed crossing plus corroborating quality evidence may auto-confirm; net motion plus sensor impact without reliable crossing requires explicit operator review. (Shadow decisions only; official automatic mutation remains prohibited.)
- [x] Store supporting evidence, confidence inputs, model/configuration versions, and a human-readable decision reason. Rule labels such as high confidence are not calibrated probabilities. (Full offline export/journal; app evidence persistence is Part 07.)
- [x] Implement proposed candidate states: `COLLECTING`, `PENDING_REVIEW`, `CONFIRMED`, `REJECTED`, `UNRESOLVED`; keep corrections as new events. Define legal transitions and stale-command behavior.
- [x] Deduplicate net oscillation and repeated observations of one incident. Associate manual confirmation with the candidate to avoid manual/automatic double counting. (Optional durable manual-goal candidate link verified; unlinked clicks cannot be inferred as the same incident.)
- [x] Disable automatic score mutation during paused/ended matches. Define goal-end mapping changes and reject stale evidence from prior matches. (All official automatic mutation disabled; shadow lifecycle/epoch boundaries tested.)
- [x] Replace the unconditional five-second lock with the venue's restart policy. Keep later evidence logged; use operator restart when centre detection is unavailable. (Prototype explicit restart selected from prior operator-controlled defaults; venue ratification/UI pending.)

**Deliverables:** `modules/goal_engine/`, decision table, state-transition specification, replay regression cases.

Software evidence: [fusion rules and state transitions](docs/fusion.md), [dummy results](docs/fusion-baseline.md), and the [completion record](docs/implementation-progress.md#part-06--dummy-shadow-fusion-and-lifecycle-verified-integration-and-field-gates-pending). Live evidence/scoreboard composition remains Part 07; physical timing/window and release qualification remain pending.

**Exit evidence:** The challenge suite covers player-net contact, post-and-in, partial crossing, occluded ball, duplicates, late evidence, two nearby incidents, quick restart, pause/end, and side change. No unanswered prompt auto-confirms. Decisions reproduce under replay and satisfy the frozen transition rules.

## Part 07 — Integrate operator review, scoreboard, and reports

**Purpose:** Make automation understandable and correctable during a match.  
**Depends on:** Parts 01 and 06.  
**Addresses:** R02–R03, R05, R13–R14.

- [x] Extend the operator page with pending candidates, evidence/reason, replay clip status, confirm/reject, manual goal, undo, and attribution editing using authorized dummy evidence/media.
- [x] Keep score controls usable while a clip is pending or absent. Show unknown scorer, pending clip, stale feed, disconnected display, and manual mode explicitly; browser rendering remains pending.
- [x] Broadcast committed updates with match ID, revision, event ID, and server clock state. Implement reconnect snapshots and recovery from missed messages.
- [x] Add operator authentication and read-only display access; protect recordings and mutation endpoints. Validate allowed origins and concurrent command revisions. Prototype uses a shared key; individual staff identities remain future work.
- [x] Keep API command routes explicit and documented, including candidate rejection, review mode, restart, event export, and clip access/status. Automatic mode remains unavailable.
- [x] Provide deterministic JSON match export and a simple report reconstructed from corrected events. Do not require an LLM or internet connection.
- [ ] Run the display through the selected kiosk/HDMI path and measure physical or instrumented rendering latency, not just WebSocket send time.

**Deliverables:** Operator and scoreboard pages, API contract, reconnect protocol, deterministic match report.

**Status:** Software integration verified with generated incidents/media, 165 Python and five Node checks, and two byte-identical API workflow runs. [Operator guide](docs/operator-review.md), [baseline](docs/operator-baseline.md), [API contract](docs/api.md), and [completion record](docs/implementation-progress.md#part-07--operator-review-scoreboard-and-reports-verified-rendered-and-field-gates-pending) record scope. Real inputs remain separate; desktop/mobile rendering, actual media/keyboard behavior and physical HDMI/render latency are still pending. Client render-ack telemetry is implemented but its fake virtual timing does not satisfy the display measurement gate.

**Exit evidence:** An operator completes a scripted match, handles an uncertain goal, changes a scorer, undoes a goal, and reconnects both clients without divergence. Unauthorized writes fail. The display shows only committed scores, and the measured latency includes rendering.

## Part 08 — Validate recovery, shadow mode, and v1 release

**Purpose:** Enable automatic scoring only after field evidence supports it.  
**Depends on:** Parts 02–07; Part 09 too if named scorers remain a launch requirement.  
**Addresses:** R04–R15.

- [ ] Package the chosen hardware/runtime combination; define worker supervision, startup order, database migration, health reporting, model/configuration versioning, and update rollback.
- [ ] Instrument input freshness, dropped frames, queue age, sensor health, clock alignment, storage capacity, temperature/resource use, and pending-review age.
- [ ] Test failures: camera/serial loss, inference crash, API restart, disk full, network loss, host power interruption, and failed migration/update. Prevent stale evidence from changing the score on recovery.
- [ ] Keep a physical independent scoring method available for total host failure. Write a recovery procedure that reconciles manual changes and uncertain match time before resuming automation.
- [x] Implement explicit closed-session raw/clip retention (disabled proposed 30-day policy), retained audit logs/metadata, training-session holds and checked backup/restore to new paths. Restore demonstrated with generated data; venue ownership/periods/off-host backup decisions remain pending.
- [ ] Run shadow mode on frozen rules and models; compare against independently adjudicated match truth without allowing the model to set that truth.
- [ ] Accumulate the proposed 300-goal, 20-hour, 14-day evaluation floor and publish all shared metrics, intervals, conditions, outages, and operator feedback.
- [ ] If a gate fails, classify errors, fix using development data, and repeat evaluation with an untouched final set. Do not tune against the blind test and keep calling it blind.
- [ ] Activate a supervised pilot only after the gates pass and the venue operator accepts the workflow. Expand operating hours gradually while monitoring corrections and failures.

**Deliverables:** Deployment package, `docs/runbook.md`, `docs/release-evaluation.md`, recovery/restore evidence, operator checklist, versioned release candidate.

**Software checkpoint (11 October 2026):**

- [x] Build a checksummed source candidate with safe config/media templates, per-file manifest and deterministic archive; dependencies/service/hardware are not bundled.
- [x] Add bounded single-owner host supervision and periodic integrity quarantine; unsupported schema/startup failures stop without downgrade.
- [x] Report disk, capture freshness/drops/lag, clip worker, review age, display and process CPU telemetry; absent sensor/inference/memory/temperature measurements remain explicit/null.
- [x] Test live WAL backup, verified restore, abrupt process exit, transaction rollback/quarantine, unsupported schema, consumer cleanup, retention guards, prior capture/serial/stale-evidence and reconnect cases using disposable data.
- [x] Write independent physical tally/time, interrupted-match recovery, backup/restore, retention/holds and update rollback procedures in the runbook.
- [x] Freeze/replay the dummy shadow dataset and report intervals/counts without passing field gates or enabling automatic mode.

Evidence: **186 Python tests and five client checks**, byte-identical recovery/evaluation/source-package proofs, [runbook](docs/runbook.md), [software baseline](docs/recovery-baseline.md), [release evaluation](docs/release-evaluation.md), and [Part 08 record](docs/implementation-progress.md#part-08--recovery-and-operations-software-verified-fieldrelease-gates-pending). All original physical/deployment/venue gates above remain pending unless explicitly checked. No supervised automatic pilot is activated.

**Exit evidence:** The shared goal-recall, false-goal, latency, correction, workload, and availability gates pass; critical failure/recovery exercises pass; the backup restores. Automatically fall back to review/manual mode on stale or invalid inputs. Revert to the last verified release or manual mode when score integrity fails or measured pilot quality breaches its agreed thresholds.

## Part 09 — Add scorer, assist, and own-goal attribution

**Purpose:** Complete the original player-attribution objective with measured coverage.  
**Depends on:** Part 03 data infrastructure, Part 07 workflow, and camera views that observe relevant touches.  
**Addresses:** R03 and attribution-related scope corrections.

- [ ] Decide from recorded coverage whether an overhead camera is required now. Install/calibrate it before claiming full-pitch scorer attribution.
- [x] Capture match-specific rosters, unique team/bib mappings, substitutions, and side changes. Track identity separately from the displayed number. Goal/incident roster snapshots are retained; software-only validation.
- [ ] Build team/number recognition baselines and aggregate observations across tracks, with an explicit unknown class and identity-switch handling.
- [ ] Label touches and scoring sequences independently. Use temporal motion and visual evidence; treat simple nearest-player proximity as a candidate cue.
- [x] Implement the user-confirmed prototype scorer/assist/own-goal rules, including intervening opponents, ricochets, uncertain touches, and deflections. Assist may be null without implying an error. Venue rules remain pending.
- [x] Publish score immediately on goal confirmation; attach attribution later with its own versioned event and operator correction path.
- [ ] Evaluate each field separately by lighting, visibility, player overlap, and camera end; report attribution errors and abstentions.

**Deliverables:** Attribution pipeline in `modules/stats/`, roster/identity support, touch-labelled evaluation set, attribution report.

Available Part 09 software: aggregation of injected team/bib readings with unknown/identity-switch handling, conservative touch rules, captured active rosters/substitutions, durable private suggestions and operator accept/reject/manual corrections, bounded checksum/split-guarded replay and explicit generated references. The [attribution guide](docs/attribution.md), [baseline](docs/attribution-baseline.md) and [progress record](docs/implementation-progress.md) distinguish synthetic results from unmeasured pixel recognition, camera coverage and independent venue truth. Recognition, real touch labeling and field evaluation tasks above remain unchecked.

**Exit evidence:** Proposed initial gate: at least 98% scorer accuracy among automatically named scorers at at least 90% coverage across at least 100 held-out goals from multiple sessions. Report intervals and cases requiring review. Assists and own goals remain suggestions until separately adjudicated evaluation supports agreed gates; unknown outcomes remain editable and do not alter team scores. This is an independently gated release, not an assumed consequence of ball detection.

## Part 10 — Extend overhead analytics and optional reports

**Purpose:** Add broader features only after scoring and identity are dependable.  
**Depends on:** Parts 08–09 and calibrated overhead coverage.

- [ ] Validate whole-pitch visibility, distortion correction, multi-camera handoff if used, identity continuity, and ground-plane tracking uncertainty.
- [x] Specify prototype possession/pass/interception definitions with paused/dead-ball/unknown time and gaps; venue agreement remains pending. See [definitions](docs/analytics.md).
- [ ] Specify and validate shot, shot-on-target, distance, heatmap and aerial-ball definitions against calibrated trajectories.
- [ ] Build one metric at a time and compare it against manually annotated sequences. Report unavailable metrics instead of inventing values from missing tracks.
- [x] Generate deterministic reports from corrected events; official goal/player totals are separate from generated contact windows.
- [ ] Add an optional LLM narrative only from verified structured statistics and with offline fallback.
- [ ] Add highlight extraction and exportable player cards if desired. Treat sharing destinations and cross-match profiles as separate product choices.
- [x] Propose separate numeric pass/interception/possession quality gates; independent field data and venue agreement remain pending. Do not reuse goal-recall targets.
- [ ] Set distance/heatmap/shot quality gates before enabling those metrics.

**Deliverables:** Analytics definitions and validation report, overhead tracking extension, optional reports/highlight tools.

Available Part 10 software: bounded normalized-contact pass/interception/possession rules, explicit time/unknown accounting, captured roster/source/play boundaries, auditable source/corrections, corrected official team/player totals and enriched downloadable reports. Twelve generated windows with event/time references and checksum/split/work guards verify the dummy implementation. [Guide](docs/analytics.md), [baseline](docs/analytics-baseline.md) and [progress](docs/implementation-progress.md) leave actual overhead tracking, independent field metrics and optional sharing/narratives unchecked.

**Exit evidence:** Each enabled metric has its own reference labels, measured error/coverage, and accepted gate. Reported figures reconcile with the corrected match log; generated narrative cannot change stored facts. Features without validation stay disabled or clearly experimental.

## Immediate work queue

1. Complete the venue survey and score/restart rules in Part 00.
2. Complete Part 01 browser acceptance for the implemented manual scoreboard.
3. Trial both real goal cameras, measure calibration/timing, and resolve the Part 02 live-rate capacity shortfall on the selected host.
4. Collect/review venue data for Parts 03–04, compile/bench/label physical sensors against Part 05 gates, and validate Part 08 recovery/deployment/independent fallback on the selected host. Dummy review/recovery/operations/attribution/contact analytics are verified; browser/HDMI and automatic-release gates remain open. Parts 09–10 real recognition/metrics require measured camera coverage and independently labelled venue sequences. Calibrated overhead tracking and optional reports/highlights remain later work.
5. Revisit the hardware budget, rollout date, and scorer-at-launch requirement using that evidence.

## Completion record template

For each completed part, record:

```text
Part:
Owner and completion date:
Code revision / model / firmware / configuration versions:
Deliverables:
Validation commands or field procedure:
Dataset/session IDs and measured results:
Exit gate: passed / failed / pending field evidence
Known limitations and next dependency:
```

Checked tasks reflect implemented Parts 01–10 software and the evidence recorded in `docs/implementation-progress.md`. Firmware/hardware acceptance, browser/HDMI checks, real-camera timing/capacity, calibrated overhead metrics, pretrained/adapted detector/player-recognition validation, physical recovery/deployment and venue ground truth remain pending. No installed cameras/sensors, trained models, real detector/classifier accuracy, automatic pilot or completed field tests are claimed.
