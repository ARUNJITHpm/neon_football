# API contract

Version: 1. Mutation endpoints, operator snapshots, evidence, media, display health, reports and event/export reads require `Authorization: Bearer <operator key>`. `X-Operator-Name` is a UTF-8 percent-encoded audit label under a shared key, not an authenticated individual identity. Use `encodeURIComponent` in browser clients; plain ASCII names also work. Cross-origin operator requests are rejected. No CORS allowance is enabled.

Part 02 adds authenticated capture health and clip request/status endpoints. See [capture API and media/timing contracts](capture.md#clips-and-api). The scoring command/event schema remains version 1; media contracts have separate version 1 JSON schemas in `docs/schemas/`.

## Commands

Create with `POST /api/v1/matches`; all later commands use `POST /api/v1/matches/{match_id}/commands`.

```json
{
  "schema_version": 1,
  "command_id": "unique-client-command-id",
  "expected_revision": 0,
  "action": "create",
  "payload": {
    "orange_name": "Orange",
    "green_name": "Green",
    "duration_seconds": 1200,
    "players": [],
    "goal_a_defending": "orange"
  }
}
```

Create requires revision 0; other commands require the match's current revision. Successful commands return `{event, snapshot, duplicate}` after commit. Identical retries return their original committed result with `duplicate: true`, even if the current match has since advanced. Clients must fetch current state and must not replace newer snapshots with an older retry result. Reused IDs with different content return 409. Failed commands do not reserve the ID or advance revision.

| Action | Payload | Allowed state |
| --- | --- | --- |
| `create` | Team names, duration, players and Goal A defender | No unfinished match |
| `start` | `{}` | Ready |
| `pause` | `{}` | Live |
| `resume` | `{}` | Paused |
| `end` | `{}` | Ready, live, paused or interrupted |
| `reconcile_clock` | `elapsed_seconds` | Interrupted; changes state to paused |
| `swap_ends` | `{}` | Ready or paused, no pending candidate |
| `manual_goal` | `team`, optional `candidate_id`, `scorer_id`, `assist_id`, `own_goal` | Live; restart gate clear |
| `undo_goal` | `goal_id` | Any state, active goal only |
| `attribute_goal` | `goal_id`, optional scorer/assist IDs and own-goal flag | Any state, active goal only |
| `create_candidate` | `candidate_id`, `goal_end`, `reason` | Live |
| `confirm_candidate` | `candidate_id` | Live; pending candidate only |
| `reject_candidate` | `candidate_id` | Live or paused; pending candidate only |
| `set_review_mode` | `mode`: `manual` or `demo_review` | Ready or paused; no pending candidate |
| `demo_incident` | `goal_end`, `scenario` | Live, demo review enabled, restart gate clear |
| `restart_play` | `{}` | Live, demo review |
| `substitute_player` | `outgoing_id`, `incoming_id` | Ready, live or paused; same-team registered active → bench |
| `demo_attribution` | `goal_id`, optional `scenario` | Active goal, dummy examples enabled |
| `accept_attribution` | `goal_id`, `suggestion_id` | Active goal, exact pending suggestion and matching attribution revision |
| `reject_attribution` | `goal_id`, `suggestion_id` | Active goal, exact pending suggestion and matching attribution revision |
| `demo_analytics` | Optional `scenario`: `passing`, `pauses`, `gaps`, `uncertain` | Any match state; dummy examples enabled |
| `correct_analytics_touch` | `session_id`, `touch_id`, nullable `player_id`, `kind`, `certainty`, optional `void` | Existing generated session/contact; captured active player only |

Dummy incidents run synthetic evidence through the Part 06 fusion engine, then persist a pending operator review. Even a shadow rule confirmation cannot change the official score. Scenarios: `observed`, `partial`, `net_contact`, `missing_clip`, `pending_clip`, `failed_clip`. Every dummy review expires unresolved after 15 seconds unless explicitly resolved. Expiry is committed before reads/commands and advances revision. In demo review, confirmation or a manual goal requires an explicit `restart_play` before further scoring. Restart retires pending incidents; pause/resume, end, side changes and host recovery retire stale dummy reviews. Legacy `create_candidate` remains a bare manual contract without timed media; pending legacy candidates survive pause but retire on end/restart/recovery.

An unlinked `manual_goal` creates a separate incident. To score an existing candidate use `confirm_candidate` or include its `candidate_id` in `manual_goal`; resolution and goal append are atomic, and wrong-team/resolved links fail. Automatic mode is not accepted.

Teams have stable IDs `orange` / `green`, separate from display names. Players have stable match-specific IDs, names, team and bib. Nullable IDs mean unknown attribution. Attribution commands replace the three attribution fields, with omitted fields defaulting to unknown / false; they do not alter team score.

Part 09 adds optional `active_player_ids` to creation; omitted/null means every registered player is active, while an empty list means none. `player_substituted` stores the new roster revision/active IDs. Each new goal captures the active roster, using incident creation time for a linked candidate. The private snapshot includes `roster_revision`, `active_player_ids`, `attribution_suggestions`, and goal `attribution_revision` / `attribution_source`. Public views omit these fields.

`demo_attribution` scenarios are `direct` (default), `assist`, `own_goal`, `uncertain`, `deflection`, `identity_switch`; they generate numeric observations, not camera recognition. They need `demo_review_enabled=true` but can review a committed goal in manual mode or after ending. `attribution_suggested` retains a bounded private submission and base attribution revision; a new/manual/undone result supersedes pending suggestions. Rejection appends `attribution_rejected`; acceptance appends `attribution_changed`, increments the goal attribution revision and retains `evidence=synthetic`, `suggestion_id` and `assist_status`. Neither action changes score. Unknown own-goal outcomes return 422 on acceptance and require manual editing. Pending committed-goal suggestions survive recovery for retrospective review. See [attribution rules, contracts and evaluation](attribution.md).

## Reads and browser pages

Part 10 adds private `analytics_sessions` with immutable source and versioned corrections. `analytics_session_added` records a generated relative-time example; `analytics_touch_corrected` appends classification/void decisions. Neither changes score, live clock status, candidates or approved goal attribution. Omitted correction `player_id` means unknown, `certainty` defaults uncertain and `void` defaults false; `kind` is required. Corrections replace classification fields rather than merging omitted values. Session IDs are deterministic per generation command; duplicate commands retain their original result. All commands still require the current match revision. See [definitions and examples](analytics.md).

JSON/text reports now include corrected `official_statistics` plus separately scoped `contact_analytics` windows. Multiple generated sessions are not combined into official match possession; absent analytics is unavailable. Pending player suggestions and undone goals are excluded from official player totals. Public reads/socket omit analytics evidence. Existing Download report retrieves enriched text; generation/corrections currently use the command API/proof tool.

| Path | Result / authorization |
| --- | --- |
| `GET /health` | Process health and manual mode; public |
| `GET /api/v1/config` | Public venue label and prototype defaults; no secrets |
| `POST /api/v1/operator/check` | Checks bearer key |
| `GET /api/v1/matches/current` | `{match: snapshot or null}`; public scoreboard fields only |
| `GET /api/v1/matches/{id}` | Public scoreboard fields only |
| `GET /api/v1/operator/matches/current` | Full snapshot and private evidence; authenticated |
| `GET /api/v1/displays/status` | Connection freshness and render-ACK telemetry; authenticated |
| `GET /api/v1/operations/status` | Integrity latch, disk/capture/review/worker/display health and config checksum; authenticated |
| `GET /api/v1/matches/{id}/candidates/{candidate_id}/clip` | Registered clip states; authenticated |
| `GET /api/v1/matches/{id}/candidates/{candidate_id}/clip/file` | Ready generated MP4, checksum checked, HTTP ranges; authenticated |
| `GET /api/v1/capture/clips/{clip_id}/file` | Ready registered MJPEG download, owned path/checksum checked; authenticated |
| `GET /api/v1/matches/{id}/report` and `/report.txt` | Corrected deterministic JSON/plain text; authenticated |
| `GET /api/v1/matches/{id}/events` | Ordered immutable events; authenticated |
| `GET /api/v1/matches/{id}/export` | Deterministic committed snapshot plus events; authenticated |
| `WS /ws/matches/current` | Public snapshots every 500 ms; read-only |
| `WS /ws/operator/current` | Full snapshots after first-message key authentication |
| `/operator`, `/scoreboard` | Local operator and read-only display pages |

Event envelope: schema version, event ID, command ID, match ID, revision, event type, occurrence time, recorded UTC time, actor/source, correlation ID and event payload. Clock interruption is a system event. Exports freeze time at the last committed boundary so repeated exports without a new event are identical. Current-state reads include an advancing live clock and server time.

This milestone uses the generic typed command route instead of every action-specific route in the original concept. The definitive schema is also available at `/openapi.json`. Error statuses: 401 invalid key, 403 cross-origin operator request, 404 unknown match/goal/candidate, 409 stale revision or lifecycle/duplicate conflict, 422 invalid envelope/payload. Storage failures return 500 and should be retried with the same command identity after recovery.

## Reconnect and rendering protocol

The private WebSocket requires its first JSON message `{"operator_key":"<key>"}` within three seconds, checks origin, and closes with 1008 on invalid authentication. Credentials are not placed in URLs. Public snapshots omit candidates, player rosters, goal records and evidence. Nonempty snapshot envelopes include `match_id`, `revision`, `event_id`, and `server_clock` with status, elapsed time, server UTC and clock boundary. Empty current-match envelopes retain `{type:"snapshot",match:null}`. Reconnect always receives authoritative current state; clients reject older revisions within a match. A transport silent for three seconds reconnects and shows unavailable input status.

After two animation-frame callbacks the scoreboard returns `{"type":"rendered","match_id":"…","revision":1,"event_id":"…"}`. The host accepts only registered served identities. Duplicate acknowledgments refresh presence without duplicating samples; missed/current revision and stale/disconnected states are explicit. Live goal/correction samples measure committed UTC to host receipt of this acknowledgment, including the network return trip. This is untrusted client telemetry, not proof of browser paint or physical HDMI timing, and it has no scoring authority. [Operator validation](operator-baseline.md) distinguishes simulated tests from pending measurements.

Unavailable candidate media returns 404; changed/missing registered media returns 410; capture media not ready returns 409. Neither failure prevents explicit scoring/correction. Review contracts: [submission](schemas/review-submission-v1.json), [clip](schemas/review-clip-v1.json). Reports reconstruct corrected goals from immutable events, reject score projection disagreement, and freeze elapsed time at the last committed boundary. A read can first commit newly due review expiry; exports/reports are identical once no additional transition is due.

Part 08 periodic integrity checks latch quarantine on audit/projection failure. Scoring and current/export score reads return 503, public/operator sockets close with 1011, and authenticated operations status remains available with `state: quarantined` and `scoring_available: false`. Restoring arbitrary JSON in the running process does not clear the latch. [Runbook](runbook.md) describes checked recovery. Capture/clip/disk degradation leaves operator-controlled scoring available while transactions can commit; none of these statuses enable automatic mode. Resource/serial/inference measurements that do not exist are null/explicitly disconnected, not healthy. Operation settings and retention policies have [separate schemas](schemas/operations-settings-v1.json).
