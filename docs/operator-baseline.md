# Part 07 dummy workflow validation

Date: 11 October 2026. Fixture `operator-api-v1`; review/clip contracts 1; application 0.1.0; SQLite schema 1. Python 3.12.4 on Windows, existing host-inherited environment, no new dependencies. No Git repository/commit exists.

The complete Python regression suite passed **165 tests in 18.84 seconds**, including the previous 146 and 19 new operator/display/storage/media checks. Five Node checks passed in 221.16 ms with test isolation disabled because the sandbox denies child-process spawning. These exercise actual client scripts against mocked transport/timers and a small DOM model; they do not render a browser.

Coverage includes synthetic fusion remaining review-only, atomic confirm/link and duplicate rejection, mode/restart/lifecycle gates, attribution/undo, timeout, disk-write rollback, reopen/recovery, additive old-state compatibility, corrected report reconciliation, public evidence redaction, private socket authentication, origin enforcement, reconnect metadata, authenticated generated MP4/range delivery, media tamper handling and owned MJPEG download guards. Client checks include older revision rejection, clock freeze/reconnect/page exit, private-key handshake/lock, two-frame acknowledgment scheduling, retained evidence/video nodes, resolved-action focus and stale health response invalidation.

Two fresh CLI runs at `local_scratch/part07-proof-a` and `part07-proof-b` produced byte-identical export, JSON report, text report and baseline metadata. Each run sends 15 operator commands plus one committed expiry, with two public and two private reconnects. Final score: **Orange 0 – Green 1**. Four reviews: two confirmed (one goal subsequently undone), one rejected and one unresolved. Report preserves two goal records, one attribution update and one undo correction. Sixteen committed events reconcile with the final score. Authentication failures and generated clip download are exercised without touching existing servers or scoring databases.

| Artifact | SHA-256 |
| --- | --- |
| Event export | `982503382e05b0c5f406c5d7f22a7c0542eb74ecd4771820913e1a4e86de5162` |
| JSON report | `3c82047b21124e30bca409907206aadf16353c43752267dc32baf312ed2264c2` |
| Text report | `ded9b7a78d5ca8e48142f7f5904862122e6340c1a5a6f9af3a46be484fefbab5` |
| Generated MP4 (88,688 bytes) | `336868a0a397a59443fe0c49f54df2f0aa0768eb8f4aece871e46078156a11dd` |

[Baseline JSON](operator-baseline.json) records the current source and fixture/media checksums. Earlier Part 06 source hashes describe that earlier implementation; Part 07 changes intentionally do not rewrite historical evidence. Reproduction commands and provenance are in the [operator guide](operator-review.md).

A fake public socket acknowledgment after a virtual 30 ms confirms instrumentation arithmetic and score independence. It is not measured browser or HDMI latency. The actual scoreboard schedules acknowledgments after two animation-frame callbacks; host samples include return transport time and trust the client statement. Real latency is **null/pending** in the baseline. Physical display verification is false.

The fresh Impeccable reviewer independently reran the five Node checks and passed the corrected source paths. Its initial findings (review-row/media/focus rebuilds and stale health after disconnect) were fixed and covered. The bounded [UI documenter record](operator-ui-review.md) preserves the incumbent design. No screenshot, computed-layout, actual browser keyboard/media, desktop/mobile or physical HDMI acceptance occurred.

Exit: **software integration verified; rendered and field gates pending**. Official scoring remains operator controlled. Numerical incidents and test-pattern media establish no football accuracy. Real capture/sensor-to-fusion composition, hardware freshness/clock/depth validation, HD capacity, physical latency, isolated installation and release recovery/shadow evaluation remain open. Part 08 has not started.
