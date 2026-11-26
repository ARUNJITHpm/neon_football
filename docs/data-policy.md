# Data policy worksheet

Status: venue approval and ownership details pending. This is an operational worksheet, not a compliance determination.

The source plan records owner approval to film and proposes 30-day raw-video retention with training exceptions. Player notice, access controls, deletion rules and exceptions still require the venue's decisions.

- Venue data owner: pending.
- Approved uses and participant notice: pending.
- Operator access and staff key rotation: pending.
- Raw recordings / review clips / event-log retention: pending.
- Training-data copies, exports and deletion responsibility: pending.
- Backup location, access and deletion propagation: pending.

The application records local match setup, rosters, commands and correction history in SQLite. Optional capture records video, timing indexes and review clips; data tools register checksummed datasets and annotation/replay reports. Generated fixtures were used here; no venue footage was collected. Part 08 provides explicit closed-session media retention with dry-run default, disabled example policy, owner/reason training holds and a deletion journal. Audit events/commands, incident logs and registry metadata are retained; their eventual retention period requires venue approval. No automatic deletion schedule or media upload is implemented. Backup bundles contain score/roster/audit data but exclude keys/media; off-host backup location, retention and deletion propagation remain pending. [Runbook](runbook.md#retention-and-training-holds) documents scope and procedures. Local files inherit host permissions on Windows; use a dedicated restricted venue account for deployment. Venue labels/manifests may still contain participant information and require access/commit review.

Part 10 generated analytics sessions include roster IDs, synthetic contact/time observations and immutable correction history in that same private audit/backup scope. Derived reports can contain player names and counts. No analytics upload, public player profiles, sharing destination or separate analytics deletion schedule is implemented. Participant export/deletion and eventual audit-retention decisions remain venue responsibilities. See [analytics scope](analytics.md).
