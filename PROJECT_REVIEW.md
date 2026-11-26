# Neon Football Auto-Scoring — Project Review

Reviewed: 8 October 2026  
Source: [Original build plan](neon-football-auto-scoring-build-plan.md)  
Next steps: [Part-by-part implementation plan](IMPLEMENTATION_PLAN.md)

## Assessment

The plan is a useful concept and prototype roadmap, but it is not yet a reliable implementation specification. Keep the modular monolith, local operation, replay evaluation, operator corrections, and shadow-mode rollout. Resolve the goal-decision rules, camera coverage, timing, and durable score updates before enabling automatic scoring.

The workspace contained only the original Markdown plan at review time. There is no application, firmware, dataset, or benchmark here to verify. Its venue facts are accepted as supplied; hardware suitability, accuracy, budget, and schedule remain unverified. Findings below review the design, not running code. Source line numbers refer to the original file as reviewed.

## Recommended release scope

| Release | Deliverable | Reason |
| --- | --- | --- |
| Prototype | Manual scoreboard, match log, synchronized recording, replay runner | Produces something usable and creates trustworthy test data. |
| v1 | Automatic team score, explicit review of uncertain goals, correction history, recovery | Prove scoring reliability independently of player recognition. |
| v1.1 | Scorer suggestions and confirmed attribution; assists and own goals under agreed venue rules | Identification needs its own camera coverage and accuracy evidence. |
| v2 | Overhead analytics, reports, highlights, optional generated narratives | These depend on tracking quality and should not delay core scoring. |

This is a proposed scope change: the original v1 includes scorer, assist, and own-goal attribution. Preserve those requirements as v1.1 work rather than silently claiming the first scoring release completes them. If named scorers are mandatory on day one, complete Part 09 before launch and budget overhead coverage from the start.

## P0 — Resolve before automatic scoring

### R01. A projected ball-centre crossing does not establish a goal

**Source:** Goal decision engine, lines 132–147; Stats engine, lines 191–208.

The proposed segment intersection ignores ball radius, crossbar height, depth, and uncertainty. Standard football's goal definition requires the entire ball to cross within the goal opening; record whether this cage follows that definition and what local rules differ. [IFAB Law 10](https://www.theifab.com/laws/latest/determining-the-outcome-of-a-match/)

A homography maps a plane. Applying a floor homography to an airborne ball does not recover its true floor position or prove a goal-plane crossing. [OpenCV homography explanation](https://docs.opencv.org/4.x/d9/dab/tutorial_homography.html)

**Improve:** Calibrate lens distortion, goal dimensions, goal plane, and ball size. Test slow rolls, partial crossings, rebounds, high balls, and shots outside the posts. Establish an uncertainty band and require review where depth or visibility is insufficient. A single oblique view may require repositioning or an additional view; calibration alone does not remove depth ambiguity. Predicted positions may propose a candidate but must not independently prove a crossing. The operator retains decisions about fouls or other invalidating play.

**Acceptance:** Ground-truthed challenge footage separates whole-ball goals from near misses, or explicitly returns uncertain; unobservable cases cannot auto-score.

### R02. The timeout can turn an ambiguous net impact into a false score

**Source:** Goal decision engine, lines 132–147.

Net motion and a net accelerometer can respond to the same player collision or external impact. They are correlated evidence, not independent proof of a goal. Auto-accepting `S + N` after three seconds makes operator absence equivalent to confirmation.

**Improve:** Keep `S + N` without reliable crossing evidence pending until an operator confirms or rejects it. A timeout may mark it unresolved, never confirmed. Treat frame-versus-net amplitude as a feature rather than a universal veto: a goal can enter after striking the post. Likewise, player overlap does not rule out a simultaneous goal.

**Acceptance:** Unanswered prompts, tablet disconnection, player-net collisions, and net shaking never change the official score by themselves.

### R03. Scorer attribution is not supported by the proposed coverage

**Source:** Goals and scope, lines 7–17; Stats engine, lines 193–208.

The nearest visible player is not necessarily the last player to touch the ball. Goal cameras may miss the shooter, earlier assist, or a deflection. The plan both includes overhead hardware early and defers its use until phase 4.

**Improve:** Separate goal confirmation from attribution. Store nullable player IDs, attribution confidence, and operator decisions. Use match-specific rosters and stable player IDs; bib numbers are observations. Validate whole-pitch coverage before promising automatic attribution. Agree on assist windows, intervening touches, and how to distinguish an own goal from a deflection under venue rules.

**Acceptance:** A confirmed goal updates the correct team score even when the scorer is unknown. Wrong or missing attribution is measured separately from goal detection.

### R04. Time and latency assumptions need measurement

**Source:** Architecture, lines 57–62; Sensors, lines 95–98; Training, lines 109 and 128.

USB transport does not give the ESP32 and cameras one acquisition clock. Receipt times include buffering and transmission delays. A 0.5-second sensor window is also underspecified: its post-event portion affects the 300 ms fusion decision.

At the assumed 8 ms inference time, two cameras at 60 processed frames/s consume 960 ms of serial GPU inference per second; at 120 frames/s they need 1,920 ms. Neither figure includes overhead inference, preprocessing, copying, or postprocessing. These are capacity calculations, not measured performance. Published YOLO11 speed figures use specified hardware and input sizes and cannot establish this venue's 1280-pixel performance. [Ultralytics YOLO11 benchmarks](https://docs.ultralytics.com/models/yolo11/)

**Improve:** Keep source timestamps, sequence numbers, host receipt times, clock-offset estimates, and synchronization uncertainty. Define causal windows and maximum evidence age. Benchmark all streams concurrently and measure crossing-to-visible-score latency. Publish the score before completing the three-second post-event clip; clip status starts as pending.

**Acceptance:** Fusion tests cover drift, delayed packets, device resets, and out-of-order input. Hardware sustains the chosen rates without an increasing queue backlog; latency is reported at p50, p95, and p99.

### R05. Score updates must survive retries and crashes

**Source:** Architecture, lines 56–58; API, lines 164–186; Risks, line 287.

An asynchronous storage subscriber does not guarantee that a displayed score has been committed. Retried manual commands, replayed messages, or simultaneous automatic and manual goals could count twice. Restart and correction behavior are not defined.

**Improve:** Commit accepted commands, immutable events, and the score projection in one transaction before acknowledging or broadcasting. Assign event IDs, goal IDs, match revisions, and command idempotency keys. Link manual confirmation to an existing candidate where possible. Provide reconnect snapshots and append-only corrections. Persist a reliable restart boundary for the match clock and require operator resolution of uncertain downtime.

**Acceptance:** Duplicate requests, worker restart, server restart, concurrent corrections, and WebSocket reconnection produce one consistent score and audit history.

### R06. The state machine can lose goals or count echoes

**Source:** State machine, lines 151–156.

The five-second unlock and kick-off-only unlock conflict. One match-wide `EVALUATING` state can also suppress another incident. Pauses, ended matches, changing ends, unresolved candidates, and sensor echoes are unspecified.

**Improve:** Separate match lifecycle from per-goal candidate lifecycle. Deduplicate evidence for the same physical incident, retain candidates from either end, and use an explicit restart rule. If centre detection is unavailable, use an operator restart command; a timer alone should not assert kick-off.

**Acceptance:** Quick restarts, late evidence, repeated impacts from one goal, paused play, and side changes produce the intended score exactly once.

## P1 — Make the project measurable and operable

| ID | Source area | Finding and recommended change | Verification |
| --- | --- | --- | --- |
| R07 | Fine-tuning; roadmap | Define event-level recall, false automatic scores/hour, precision, review rate, and availability. Window-level sensor false-positive rate is not a goal-level rate. The 97% target must exclude operator-rescued goals from automatic recall. | Publish matched events and denominators, not just percentages; follow the metric contract in the implementation plan. |
| R08 | Data collection; validation | A repeatedly inspected validation set becomes a tuning set. Adjacent video frames can leak across splits. An operator button provides an approximate marker, not exact crossing truth. | Split by match/session before sampling, reserve a blind test set, refine timestamps from footage, and audit full sessions for goals the operator missed. |
| R09 | Training sample strategy | Goal-heavy samples help learning but do not represent hours of normal play or difficult negatives. One camera at one goal cannot measure two-goal recall. | Collect continuous footage of both ends, plus net collisions, outside-net hits, blocks, glare, slow goals, and occlusions. Track per-condition performance. |
| R10 | Monolith and bus | “One process” contradicts worker processes. A queue is not automatically a broadcast bus. Raw frames should not be persisted as ordinary events. | Specify one deployable service with supervised processes, explicit per-subscriber delivery, bounded queues, frame references, and a separate durable decision path. |
| R11 | Manual fallback | A tablet served by the failed GPU box is not an independent fallback. | Keep a physical/manual scoring method available; define score reconciliation and test total host failure as well as worker failure. |
| R12 | Hardware budget | Retail ranges omit lenses, mounts, cable runs, USB/PoE equipment, storage, cooling, power backup, installation, and spares. | Create a complete bill of materials from site measurements and current quotes. Existing prices remain unverified; prototype before bulk buying. |
| R13 | Storage and clips | Retention lacks a disk-capacity budget and deletion implementation. A six-second uncompressed buffer can be expensive. | Measure stream bitrate and memory use, use appropriate encoded clip buffering, set quotas, test low disk, and retain small audit records independently of video. |
| R14 | API and deployment | “LAN + API key” leaves operator identity, read-only display access, clip access, and recovery unspecified. | Use authenticated operator sessions, read-only scoreboard access, input validation, explicit allowed origins, secret handling, backups, health checks, and a tested update/rollback runbook. |
| R15 | Data governance | Owner recording approval is recorded, but player notice, access, deletion, and training-retention exceptions are not operationally defined. | Name a venue data owner and document approved uses, retention periods, access, and deletion handling, including copied training clips and exports. This review does not assess legal compliance. |

## P2 — Correct and clarify the written specification

1. **ADXL345 sampling:** Replace native “1 kHz” with a supported output data rate selected by experiment, such as 800 Hz or 1,600 Hz. Document bus bandwidth, FIFO/interrupt handling, and any explicit resampling. The datasheet lists those rates, not 1,000 Hz; higher rates also have interface requirements. [Analog Devices ADXL345 datasheet, Tables 7 and serial communications guidance](https://www.analog.com/media/en/technical-documentation/data-sheets/ADXL345.pdf)
2. **Training guidance:** Remove generic “smaller anchors” advice for the proposed YOLOv8 option, whose head is anchor-free. Tune resolution, crops, augmentation, sampling, and model size against measured results. [Ultralytics YOLOv8 architecture](https://docs.ultralytics.com/models/yolov8/)
3. **Model count:** “Four models are trained” conflicts with the no-training team classifier row. Call this four perception components, with training only where evidence supports it.
4. **Pretraining:** Venue footage is necessary for validation and adaptation; the statement that only venue data may be used is unnecessarily restrictive. Benchmark pretrained weights before deciding how much fine-tuning is required.
5. **Camera coverage:** The field-of-view table is a geometric starting point. State the assumed projection, sensor aspect ratio, distortion, and usable crop. The 240 px/m figure is a horizontal approximation, not uniform floor resolution after fisheye correction. Validate both axes and field edges on site.
6. **Scope diagram and report API:** Mark possession, full analytics, LLM narratives, and sharing as optional v2 modules. The v1 report should be deterministic and should work offline.
7. **Model/dependency selection:** Freeze a tested runtime and hardware matrix instead of leaving several interchangeable trackers, UI stacks, and GPU platforms unspecified. Record dependency and model licence decisions before product distribution; Ultralytics documents AGPL-3.0 and Enterprise options. [Ultralytics licensing](https://www.ultralytics.com/license)
8. **Schedule:** Treat the 18-week roadmap as a hypothesis. Data availability, camera feasibility, attribution coverage, staffing, and hardware lead times determine the real schedule. Release by evidence gates.

## What to retain

- One locally operated deployable service per cage, with clear module boundaries.
- The venue's own scoreboard display while the existing controller remains unknown.
- Recorded replay as the main regression asset.
- Append-only operator corrections and evidence clips.
- Fixed-camera venue footage, progressive labelling, and a supervised shadow period.

## Recommended next action

Start Parts 00 and 01 of the [implementation plan](IMPLEMENTATION_PLAN.md): establish the venue rules and measurements, then build a durable manual scoreboard and event logger. Do not begin by training all perception components. The next useful evidence is whether the proposed camera views can observe valid crossings under actual lighting.
