# Part 06 — Fusion and goal lifecycle

The offline engine combines versioned vision and sensor evidence into auditable candidates. It runs in **shadow mode only**: a `CONFIRMED` shadow candidate changes its separate `shadow_score`, never the application's official score. The server still rejects automatic-scoring activation. The integrated operator workflow is Part 07, and field/release qualification is Part 08.

## Run the dummy replay

```powershell
.venv/Scripts/python.exe tools/fusion_replay.py tests/fusion/fixtures/dataset.json --output local_scratch/fusion-replay.json
.venv/Scripts/python.exe tools/export_fusion_schemas.py --check
```

The committed small fixtures contain 17 numerical lifecycle scenarios, two upstream-output scenarios, and separate train/blind guard fixtures. Default replay selects the 19 validation sessions. No cameras, serial ports or score database are opened. To rebuild these dummy fixtures, run `tools/build_fusion_fixture.py NEW_DIRECTORY`; it also runs the existing Part 04/05 offline fixture pipelines. This generates JSON evidence, not football video.

`core/fusion.py` defines settings, input envelopes, candidate states, commands, journal events and replay contracts. `modules/goal_engine/engine.py` imports shared contracts only. `tools/fusion_replay.py` composes it with the shared one-to-one matcher and descriptive intervals. See [results](fusion-baseline.md) and [machine-readable trace](fusion-baseline.json).

## Input registration and time

Composition must supply an authenticated source's session, match, host clock domain and current **play epoch**. Vision candidates do not independently carry a clock-domain field, so composition must retain the originating registered frame's domain; adding an arbitrary wrapper cannot establish physical synchronization. Sensor impacts retain their internal host domain, device/boot identity, device occurrence and nullable aligned occurrence. The engine verifies registered camera/end/calibration/model/configuration versions, board/end/configuration, wrapper identity, epoch and evidence provenance. Synthetic inputs cannot be represented as venue evidence.

Evidence event IDs are unique within an engine. Identical retries reuse the original candidate/result; the same ID with changed content is rejected. Ignored inputs remain in the exported evidence list with an explicit reason. The engine never uses receipt time as a substitute for a missing occurrence timestamp.

| Prototype setting | Default | Meaning |
| --- | --- | --- |
| Correlation window | 200 ms | Maximum gap between occurrence intervals expanded by each timing bound |
| Collection duration | 300 ms | From first accepted evidence receipt; no decision before this deadline |
| Maximum timing uncertainty | 20 ms per source | Unknown/larger bounds cannot support a shadow confirmation or timed association |
| Maximum evidence age | 500 ms | Checked at receipt and again for confirmation at the decision deadline |
| Repeat horizon | 600 ms | Bounded association from candidate creation; distinct tracks remain separate |
| Review timeout | 15 s | Becomes unresolved; silence never confirms |

These are **unmeasured prototype defaults**, not venue timing results. Collection must cover the correlation window plus two configured uncertainty bounds. A clean observed crossing must also have an explicit interval no wider than twice the uncertainty budget. Receipt order drives collection deadlines; correlation uses physical occurrence intervals. Arrival exactly at a collection/review deadline is processed after that timer. Timers execute at their original virtual deadlines even when replay jumps forward.

Evidence arriving after collection may be attached and marked late, but cannot promote a pending review into a shadow confirmation. Expired/unmapped timing remains review evidence; stale, future or prior-boundary occurrences are ignored with reasons. Additional evidence cannot move the first observed crossing timestamp after a candidate has been decided.

## Decision table

| Evidence at collection deadline | Result |
| --- | --- |
| Clean observed whole-ball crossing, bounded interval/time, fresh clean net/frame/mixed impact within the correlation window, unique incident, live current epoch, restart cleared | `CONFIRMED`, confirmation `shadow_rule`; separate shadow score only |
| Net motion plus impact, without reliable whole-ball crossing | `PENDING_REVIEW` |
| Predicted, occluded, image/depth ambiguous or boundary-uncertain crossing | `PENDING_REVIEW` |
| Reliable crossing with missing, slow, unknown, clipped or otherwise flagged sensor support | `PENDING_REVIEW`; an operator can still confirm |
| One impact compatible with multiple nearby visual incidents | Separate candidate identities; review, no shadow confirmation |
| New evidence during paused/ended play or while a restart is required | Logged candidate becomes `UNRESOLVED` |
| Wrong identity/domain/version/epoch, stale or future input | Logged as ignored; cannot affect a candidate or score |

All sensor classes remain possible goals. A frame or mixed impact can corroborate a post-and-in crossing. A classifier label cannot reject or veto a crossing. Flags exclude that particular input from shadow confirmation; useful clean inputs are retained. Rule label `observed_and_corroborated` is an inspectable condition, not a calibrated probability. Exported original observations preserve flags, uncertainty, feature values, source IDs, model/calibration/configuration versions, supporting sequences and clip references; transition events provide human-readable reasons.

## Candidate states and commands

Match states (`ready`, `live`, `paused`, `ended`) are independent of candidate states. Each candidate has a stable ID derived from session/match/play epoch/first evidence ID, one goal end, an occurrence timestamp (nullable) and its scoring team frozen from the defending-team mapping at creation.

| From | To | Trigger |
| --- | --- | --- |
| `COLLECTING` | `CONFIRMED` | Shadow rule at collection deadline |
| `COLLECTING` | `PENDING_REVIEW` | Evidence insufficient at deadline |
| `COLLECTING` | `UNRESOLVED` | Inactive/restart/ambiguous incident or lifecycle boundary |
| `PENDING_REVIEW` | `CONFIRMED` | Explicit operator confirm while live, current epoch, restart cleared |
| `PENDING_REVIEW` | `REJECTED` | Explicit operator reject |
| `PENDING_REVIEW` | `UNRESOLVED` | Review expiry or lifecycle boundary |
| Terminal states | Same terminal state | Later evidence is appended; it cannot reopen the decision |
| Active `CONFIRMED` | Same state, `corrected=true` | Explicit undo appends a correction and removes the shadow tally |

Commands carry command ID, actor, match ID and expected engine revision. Stale revisions, wrong matches, resolved targets and illegal transitions fail explicitly. Exact retries return the original acknowledgement while advancing due timers. A command ID cannot be reused for different content. Candidate confirmation links the tally to that candidate; a second confirmation fails. Undo is a new journal event, preserving the original confirmation. The journal contains deterministic increasing revisions and is exported with the snapshot.

The engine is single-owner, in memory and intended for offline evaluation. Export is the persistence artifact; this part does not implement an application recovery service. Defaults bound candidates to 10,000, inputs and command acknowledgements to 100,000 each, and journal events to 250,000. Each observation is limited to 64 KiB. Capacity errors require exporting/partitioning; these bounds have not been established as a sustained live memory budget. Callers must not share the engine across concurrent writers.

## Restart, pause and end changes

Every confirmation sets `restart_required`. There is no unconditional five-second lock. The operator explicitly issues `restart`; it creates a new play epoch, marks remaining open candidates unresolved and clears the gate. A quick restart allows a new incident immediately; previous-play evidence is rejected by both epoch and occurrence boundary. Evidence logged while waiting remains available for diagnosis.

Start, pause, resume, end and side change create boundaries. Pause conservatively makes open candidates unresolved; resume starts a fresh epoch. A goal whose play was interrupted must be reconciled explicitly using the existing manual scoring controls. Side changes require ready/paused state, update the defending-team mapping, and leave past candidate team assignments unchanged. Resume does not clear a goal's restart requirement. Ending makes open reviews unresolved; corrections remain separate events. A rejected/undone goal does not invent a restart signal.

## Durable manual association

The existing `manual_goal` storage command now accepts an optional `candidate_id`:

```json
{"action":"manual_goal","command_id":"operator-goal-1","expected_revision":4,
 "payload":{"team":"green","candidate_id":"incident-1"}}
```

The candidate must already exist in the official store and be pending. The team must agree with its frozen end mapping. Candidate resolution, goal append and score projection commit in the same SQLite transaction; subsequent manual or candidate confirmation against it fails. `confirm_candidate` remains available for a confirmation without attribution. Unlinked manual goals keep their existing retry fingerprints. An unlinked click cannot be safely deduplicated against an unknown physical incident; Part 07 must let the operator select the candidate.

Offline engine IDs are not automatically registered in SQLite. There is no worker-to-app connection in Part 06, and this new optional API field has no operator-page control yet. Part 07 must persist evidence/lifecycle changes, connect review commands through the durable writer, show restart/review reasons and preserve official command acknowledgements. Shadow results alone never authorize live automatic scoring.
