# Prototype requirements

Status: software defaults confirmed by the user on 10 October 2026; venue rules remain unverified.

## Confirmed prototype behavior

- One match at a time, two teams, 20 minutes by default; duration configurable at setup.
- Count-up clock, explicitly started, paused, resumed and ended by the operator. Reaching the scheduled duration does not automatically end a match.
- Manual goals during live play. Goal corrections and attribution edits remain available after ending.
- Empty roster is allowed: a goal may have an unknown scorer and assist.
- Goal A defaults to the end defended by Orange, with the other team defending Goal B. Setup and a paused-match side-change command can change this mapping.
- Persist an accepted command, immutable event and score projection in one transaction. Reusing an identical command ID returns its original result; changed content or stale revision returns a conflict.
- If a live match is interrupted by a host restart, recover the score and last committed elapsed time. The operator reconciles the clock, then explicitly resumes. No downtime is assumed to be active play.
- Manual scoring only. Candidate commands are workflow primitives for later integration, never automatic goal detection.

## Venue decisions pending

Whole-ball goal definition; fouls and invalidating play; kick-off procedure; changing ends; substitutions; assist and own-goal rules; whether automatic scorer names are required at launch; acceptance of read-only match roster information on the local display network.

See venue-survey.md for the field checklist. Part 00 remains incomplete until field evidence is recorded.
