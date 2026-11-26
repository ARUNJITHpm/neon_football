# Local host recovery and operation

This runbook supports the **operator-controlled prototype**. Automatic scoring is disabled and cannot be activated with this candidate. Real camera/sensor, browser/HDMI and release evaluation gates remain open. Keep a paper tally and independent stopwatch at the court; nominate the venue operator before live use. That physical fallback has not been demonstrated here.

## Startup and supervision

Run one API worker from the project directory using the pinned environment. Configure a dedicated restricted host account, approved camera sources and protected operator key. Do not put secrets into command arguments or backup/source bundles. `app/config/cage.example.yaml` is a safe template; `automatic_scoring_enabled` must stay false. Validate deployment, key permissions, clock and free space on the selected host before accepting a match.

```powershell
.venv/Scripts/python.exe -m app
```

Startup obtains a single-owner database lock, checks schema/integrity/audit projection, initializes additive schema-1 fields, recovers match time/retires reviews, starts optional independent capture workers, then starts the clip consumer and periodic integrity monitor. The display/operator clients reconnect to authoritative snapshots. Capture reconnects remain bounded by its configured delays; failed/stale capture does not score. There is no live inference/serial worker to supervise yet.

Optional bounded host supervision:

```powershell
.venv/Scripts/python.exe tools/run_supervised.py --config app/config/cage.example.yaml --max-restarts 3
```

This supervises only its own single-worker child. Startup/configuration exits 1/2 stop immediately; abnormal process exits retry up to three times with 2/4/8-second delays. Graceful exit stops. It does not detect a live but hung process; operations polling and the independent tally are still required. An OS service/watchdog, physical power recovery and hidden unattended launch/logging must be trialled on the selected host. Starting a second owner fails; do not delete the lock or launch more workers to work around it.

Authenticated `GET /api/v1/operations/status` reports integrity timestamp/latch, DB-volume free space, capture age/gaps/drops/lag/calibration/alignment, clip-consumer status, review age, display presence and configuration checksum. CPU samples are process CPU time over wall time: 100% is one core and excludes FFmpeg children. Inference queue age, serial health, memory and temperature remain null/unmeasured. Basic `/health` reports only process liveness. Neither endpoint is field/release qualification.

## Interrupted match or missing inputs

1. Stop play if the official score/time is uncertain. Use the physical tally/stopwatch during total host failure. Record the last visible revision and any goals recorded on paper; do not invent missed camera evidence.
2. Restore host availability and unlock the console. A previously live match becomes interrupted and all pending review incidents retire unresolved. Scores and saved evidence remain. Review the event export against the physical record before retrying any uncertain command. Identical saved command IDs return original acknowledgments and must not be replaced with new IDs merely because the first reply was lost.
3. Enter reconciled elapsed time (`minutes:seconds`) in clock recovery. This moves the match to paused; review team/end mapping and existing records, then resume explicitly.
4. Record verified missed goals only through operator scoring and correct mistaken goals with undo. Attribution may stay unknown. In dummy review, acknowledge **Restart play** between saved goals; an old unresolved candidate cannot be confirmed after recovery.
5. For camera/serial/inference failure, keep manual scoring. Inspect capture health and restart only the owned failing component when possible. No sensor/inference feed exists in this live prototype. Never claim fresh/healthy automatic evidence from the generated fixtures.

## Integrity failure or disk pressure

The periodic audit check defaults to 30 seconds and serializes with score transactions. A detected mismatch latches quarantine: scoring and public/private score reads return 503, sockets close, and operations status reports unavailable scoring. The console/display connection checks must make the lost feed explicit. Detection is periodic, not a guarantee against arbitrary changes between checks. No automatic patch rewrites score history. Startup also rejects invalid projections, damaged audit triggers and unsupported future schemas before migration/recovery.

Stop scoring, preserve the damaged database **including WAL/SHM while investigating**, collect the independent tally, and use a verified backup restore below. Low disk space reports degraded health; capture already has storage bounds and scoring transactions roll back on write failure. Retry an uncertain action with its original ID only after space/integrity recovery. Do not delete audit data, live databases or capture files ad hoc. A media-retention dry run can identify eligible closed files; actual deletion requires approved policy and stopped capture.

## Backup and restore

Use a new backup directory on an approved protected volume:

```powershell
.venv/Scripts/python.exe tools/score_backup.py backup data/neon-score.sqlite3 data/backups/score-001
.venv/Scripts/python.exe tools/score_backup.py check data/backups/score-001/score.sqlite3
```

SQLite's backup API copies a consistent committed snapshot, including WAL commits, while the owner runs. A completion manifest records schema, size, checksum, inspection counts and creation time. Failed backup has no completed manifest. Keys, camera credentials and media are excluded. Protect backups as match/roster data. Schedule and verify copies to an independent volume; media backup, off-host transfer, backup retention and participant-deletion propagation require venue ownership decisions. No external upload is performed.

Restore to a **new database path** with no owner/sidecars:

```powershell
.venv/Scripts/python.exe tools/score_backup.py restore data/backups/score-001 data/restored-score.sqlite3
.venv/Scripts/python.exe tools/score_backup.py check data/restored-score.sqlite3
```

Restore verifies staged bytes and the audit projection before publishing the new database. It never overwrites the original and fails if the target exists. Stop the owned server, point a copied configuration's `database_path` at the restored file, start one owner, then reconcile the independent tally/time. Opening a restored live match performs normal interrupted-match recovery; a backup is a snapshot and cannot contain later goals. Pending evidence cannot survive as actionable review. Restore media separately only after validating its registry/checksums. The new backup tools do not run match recovery or modify the live score during inspection.

## Retention and training holds

The proposed default is 30 days for raw recordings and review clips; the example policy is disabled until the venue approves it. Event/command audit records, manifests, incident logs, clip metadata and retention journal are retained indefinitely by these tools. A `holds` entry maps capture session ID to responsible owner/reason and protects all its media, including training exceptions. Holds must be reviewed/released by that owner; no automatic expiry of approval is inferred.

```powershell
.venv/Scripts/python.exe tools/retention.py data/recordings app/config/retention.example.json --output local_scratch/retention-plan.json
```

Inspect the plan, stop capture and any labeling/copying work, and approve a copied policy with `enabled: true` and explicit holds before running the same command with `--apply`. This code deletes only checksum-registered MJPEG/index files in closed owned sessions. Active/failed/held sessions, path escapes and links/junctions are excluded/rejected. There is no recursive directory removal. Each file has a synced deletion intent followed by a deletion record; an interrupted operation may have an intent without completion and must be reconciled before retry. Remaining manifests honestly reference retained/deleted media; missing media is not silently replaced. Other training copies, exports, backups and MP4 fixture assets are outside this retention tool.

## Candidate update and rollback

Build/check a source candidate with `tools/package_release.py` and preserve the archive/hash/manifest. The package is source plus generated fixture/config templates, not a dependency installer, Windows service or qualified hardware release. Use a new application directory/environment, install pinned dependencies, verify packaged hashes, test startup with a restored backup, and check operator/display behavior before changing the active host configuration. A clean install is still unverified in this sandbox.

Back up before any future migration. This candidate supports schema 1 only; unsupported schemas stop unchanged. No migration or database downgrade is attempted. On failed update, stop its owned process and return to the previous application/configuration with a compatible verified backup, then reconcile goals/time since the backup. Preserve all originals and do not copy only a live `.sqlite3` file without its WAL. Automatic scoring remains unavailable after rollback.

Before any supervised automatic pilot, complete the [release gates](release-evaluation.md), physical fallback drill, operator acceptance, data ownership/retention and browser/HDMI checks. Record errors by session/condition, tune only development data, and freeze a fresh untouched final holdout after any failed evaluation used for tuning.
