# Part 07 operator review

The implemented integration uses generated evidence. Official scoring is operator controlled; automatic scoring remains disabled. This part connects the Part 06 rules to durable reviews, protected media, the operator console, read-only scoreboard and reports. It does not connect real camera detections or serial sensor packets to the live scoring loop.

Part 09 extends the console with active/bench rosters, substitutions and generated scorer/assist/own-goal suggestions after goal confirmation. See the [attribution workflow and rules](attribution.md). These suggestions also require an explicit operator decision and do not perform image recognition.

## Play and review

1. Unlock `/operator` using the local key and create a match. Default duration is a 20-minute count-up clock.
2. While ready or paused, select **Dummy review** and apply. Manual mode is the default; mode changes require no pending incident. Server setting `demo_review_enabled: false` disables new dummy operation.
3. Start/resume and add a dummy incident for Goal A or B. Observed, partial and net-contact scenarios exercise different rule suggestions. Missing/pending/failed clip scenarios exercise written media states.
4. Expand the evidence and rule reason. The stored suggestion may say shadow confirmation; the official score stays unchanged. Confirm/reject explicitly, or select the incident link before recording the corresponding team's manual goal. Wrong-team and second confirmations fail.
5. Reviews have a 15-second window. Silence expires unresolved, never scores. Missing/pending/failed media does not block an operator decision. A ready video loads on request using the key.
6. After every saved goal in dummy review, press **Restart play** when play actually restarts. Further incidents/scoring are gated until then; there is no fixed five-second lockout. Restart retires pending incidents. Pause/end/side-change and host recovery invalidate stale dummy reviews.
7. Edit scorer/assist/own-goal attribution or undo from the goal record. Unknown scorer/assist remain valid. Corrections preserve the original event and goal; they do not erase history. Download the event export and corrected report.

The clip is FFmpeg `testsrc2`, two seconds at 640×360/15 fps, H.264 MP4. It demonstrates media transport only; it is independent of the numerical incident and shows no football. It is registered and checksum checked before serving. The browser fetches it with bearer authentication, then uses a bounded local blob cache of eight clips. Clips are not public static files. Capture MJPEG downloads also require authentication and registered paths within the owned recording root.

## State and recovery

`review_mode` is separate from `mode: manual`. Composition prepares synthetic `ReviewSubmission` evidence; SQLite validates identity, persists it alongside the candidate/event/command acknowledgment and never trusts a rule prediction to score. Candidate review data is bounded to 16 evidence observations and two clips; dummy incidents are bounded to 1,000 per match. Events include review mode changes, explicit restarts and unresolved expiry.

Expiry runs under the store lock before current/snapshot/export/command reads. Connected WebSockets request state every 500 ms. Without a reader, expiry is committed at the next access; no unattended background timer or claim of exact physical expiry timing is made. A due expiry advances revision, so a concurrent stale operator command fails safely. Clock interpolation continues from the host monotonic anchor; expiry does not invent an elapsed-time boundary. Host restart preserves score/evidence and retires pending incidents. An interrupted live match still needs explicit elapsed-time reconciliation before resume.

Schema version and SQLite `user_version` remain 1. Additive JSON defaults hydrate old matches and last-event metadata without changing existing command fingerprints. Legacy bare candidates have no media/deadline and retain prior pause behavior; end/restart/recovery retires them. Dummy source epochs remain part of the synthetic provenance; the official store has its own play epoch, checked at confirmation.

## Clients, privacy and reports

The scoreboard receives only public scoreboard fields. The authenticated operator socket receives full state. Every nonempty envelope identifies match, revision, last event and server clock; reconnect recovers current state. Older same-match revisions cannot replace newer state. Operators retain uncertain command identity for retry rather than locally incrementing scores. Silent transport closes/reconnects, freezes interpolated clocks, and invalidates camera/display health. Candidate rows retain disclosure/video nodes; a resolved action moves keyboard focus to its record.

Display presence and double-animation-frame acknowledgment telemetry are available on the console. They distinguish waiting, stale, disconnected and rendering acknowledgments. This milestone has only simulated acknowledgment timing tests. Real browser paint, native media behavior, venue HDMI output and rendering latency remain unverified.

Reports rebuild goals, attribution and undo corrections from immutable events, reconcile active counts with the stored score, and fail on disagreement. JSON and plain text need no LLM or internet. Elapsed time is the last committed time; repeat output is stable after due transitions are committed. [API contract](api.md) specifies commands/authentication/envelopes; [baseline](operator-baseline.md) records evidence and limitations; [UI review](operator-ui-review.md) records the incumbent design and pending rendered checks.

## Reproduce

```powershell
.venv/Scripts/python.exe tools/operator_fixture.py local_scratch/operator-example
.venv/Scripts/python.exe tools/export_review_schemas.py --check
.venv/Scripts/python.exe -m pytest --basetemp local_scratch/pytest-operator-example -p no:cacheprovider --tb=short
node --test --test-isolation=none tests/operator/client.test.mjs tests/operator/operator-dom.test.mjs
```

Use new output/test directories. The fixture creates a disposable database, scoped deterministic UUIDs, virtual clock, API commands and two reconnects per socket type. Production keeps random UUIDs. It writes export/report/baseline files and verifies repeated downloads; it opens no camera, serial device, browser, running server or physical display. Regenerate the review MP4 only to a new path with `tools/build_review_clip.py`; byte hashes can vary with FFmpeg versions, so registration uses the actual bundled asset checksum.
