# Scorer, assist and own-goal prototype

Part 09 adds late, operator-approved player attribution to an already confirmed goal. Team scores are committed first. A suggestion, its rejection, or a later player correction cannot change the team score. The current implementation uses generated numeric identity/contact observations; it does not read bibs or detect touches in video.

## Operator workflow

At match creation, enter `7, Player name` for an active player or `15, Player name, bench` for a substitute. Bibs are unique within each team; match-specific player IDs stay independent of bib numbers. The Players on the pitch section records a same-team substitution while ready, live or paused. It cannot introduce an unregistered player or replace an active player with another active player.

Each goal captures a roster revision and active IDs. A goal confirmed from an incident uses the roster at incident creation. Later substitutions or end changes cannot rewrite that snapshot. A legacy goal without a snapshot uses the original registered roster. Manual editing remains available for every registered player, including when an operator needs to correct missing substitution evidence.

Record or confirm the goal, then select a Dummy attribution example beside its record and Generate player suggestion. Review the scorer, possible assist, own-goal outcome, observations and reasons. Apply suggested players requires an explicit operator command. Reject player suggestion records a rejection. When the own-goal outcome is unknown, Apply is disabled: use Edit players or reject the suggestion. Applying a certain scorer with an unknown assist leaves the assist blank; uncertainty remains in the retained suggestion evidence.

Examples are direct shot, controlled teammate pass, possible own goal, uncertain contact, certain incidental deflection and conflicting bib readings. They are generated independently of cameras and the review test-pattern clip. They do not describe what happened in a real goal. The example timing and `goal_end` are synthetic labels, not measured incident timestamps or camera coverage.

## Conservative rules

The user approved these prototype defaults; venue competition rules still need confirmation.

| Evidence | Suggestion |
| --- | --- |
| Certain intentional last contact by a known scoring-team player | That player as scorer |
| Prior controlled pass/control by a different known teammate | Possible assist |
| Repeated controlled contact by the scorer | Look back to the preceding different teammate |
| Intervening controlled opponent contact | Break the assist chain |
| Certain intentional last contact by an opposing player | Possible own goal; no assist |
| Certain incidental deflection or frame rebound | Preserve the preceding intentional touch |
| Uncertain deflection, unknown deflector, contact order, identity or coverage | Leave affected fields unknown |
| Proximity alone | No contact or scorer inference |

Default bounds are three clear, distinct observed frames within 1.5 seconds before a contact, ten seconds of touch history and at most 20 ms declared source uncertainty. All clear readings in that window must agree on team/bib; the most recent reading must be clear. Identity support is isolated by camera, boot and track. No cross-camera handoff or inferred identity during occlusion is implemented. Future/stale readings, boot resets, conflicting bibs and inactive roster mappings abstain. Contact/crossing uncertainty intervals must not overlap, and declared touch coverage must be complete. These are unmeasured software defaults, not physical calibration results or confidence probabilities.

An unknown previous contact can leave the assist unknown while retaining a certain scorer. A possible own goal is awarded to the already confirmed scoring team; applying its opposing-team scorer does not transfer the goal. The manual attribution command validates roster membership, scorer team, distinct same-team assist and no assist on own goals.

## Contracts, persistence and recovery

`core/attribution.py` defines version-1 settings, roster, observed identities, touches, goal context, suggestion, private submission and dataset contracts. `modules/stats/identity.py` aggregates injected identity readings; `modules/stats/attribution.py` applies temporal rules. These modules import only core/their own module. App composition creates synthetic observations and invokes the actual rules. Storage never imports the stats implementation.

Suggestions have deterministic evidence/settings-derived IDs and retain the full immutable submission. They are separate from approved goal attribution. Each stores the goal's attribution revision; accept/reject require an exact pending goal/suggestion pair and current match revision. A new suggestion, manual player edit or undo supersedes pending suggestions. Accepted/rejected history remains auditable. Retrying an identical committed command returns its original acknowledgment without applying a second correction. Evidence writes and event/command acknowledgments share the score transaction; failed writes leave no partial submission.

Pending attribution for a committed goal survives host restart and backup/restore because its frozen evidence remains usable for retrospective review. This differs from time-sensitive pending goal incidents, which recovery retires. A live match still requires clock reconciliation. Startup/periodic audit checks compare roster, suggestion evidence/statuses and goal metadata against immutable events. Reports reconstruct corrections and include a dummy-attribution provenance flag. Full rosters, goal records and suggestions remain protected by operator authentication; public scoreboard snapshots/socket omit them.

Capacity limits: 50 roster players, 10,000 identity readings and 1,000 touches per offline window, 64 KiB per live dummy submission, and 1,000 submissions per match. Replay also limits manifest/asset bytes, total observations and identity-resolution work. No production ingestion or trained recognition adapter is enabled.

## Labels, coverage and evaluation

The supplied dataset has 25 checksum-registered generated windows: one train, 23 validation and one public dummy blind-test guard. Reference labels are explicit fixture intentions, not copies of the engine output. Source-group, match and content hashes cannot cross splits. Blind-test access needs explicit opt-in; public dummy fixtures are not an independent holdout. Scorer, assist and own-goal accuracy, coverage, errors and abstentions are evaluated separately, grouped by camera end and condition tags. Lighting/overlap tags are numerical fixture categories, not evidence from actual low-light images. [Recorded results](attribution-baseline.md) explain the denominators.

For venue data, freeze the roster/substitution timeline and source boot/track identities; retain contact/crossing timestamps with measured uncertainty and camera coverage. Independent reviewers must label intentional contacts versus incidental deflections, contact order, scorer/assist/own-goal truth, and whether each field is adjudicable. Set `*_known=false` for unresolved reference fields rather than treating them as a known negative. Do not infer touches from nearest-player distance. Use match/source-group isolated splits, independently reviewed labels and declared gaps. Do not tune against the held-out set. Review disagreements before scoring named predictions.

Before real attribution, survey the visibility of the last shot and preceding pass from both goal cameras across the whole pitch, including occlusion, folded/back-facing bibs, low light, blur and overlapping players. Decide whether overhead coverage is required; install/calibrate it and measure handoff/ground-plane uncertainty before claiming full-pitch coverage. No such decision or measurement is supplied by dummy data.

The proposed scorer release gate remains at least 98% accuracy among named scorers, at least 90% coverage, and at least 100 independently held-out goals from multiple sessions, with intervals and reviewed failures. Assist and own-goal suggestions need their own venue-rule adjudication and gates. Real OCR/team recognition, touch detection, camera handoff, measured temporal bounds, independent venue labels and rendered console acceptance are pending. Automatic attribution and scoring remain disabled.

## Reproduce

From the project root in the existing test environment:

```powershell
.venv/Scripts/python.exe tools/export_attribution_schemas.py --check
.venv/Scripts/python.exe tools/build_attribution_fixture.py local_scratch/attribution-new-fixtures
.venv/Scripts/python.exe tools/attribution_replay.py tests/stats/fixtures/dataset.json --output local_scratch/attribution-new-replay.json
.venv/Scripts/python.exe tools/attribution_fixture.py local_scratch/attribution-new-api-proof
.venv/Scripts/python.exe -m pytest tests/stats --basetemp local_scratch/pytest-attribution-new -p no:cacheprovider --tb=short
node --test --test-isolation=none tests/operator/client.test.mjs tests/operator/operator-dom.test.mjs
```

Builders/proof runners require a new destination and replay output uses exclusive creation. Existing data is never overwritten. Do not enable automatic modes on the basis of these results.
