# Neon Score

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

The implementation plan specifies Python, FastAPI, SQLite and locally served browser pages. This first milestone uses plain HTML/CSS/JavaScript to avoid a second build toolchain; this is an implementation choice, not a standing user preference.

## Users

The venue operator starts and pauses matches, records goals, resolves mistakes and exports the result. Players and spectators read a separate scoreboard on the venue display.

## Product Purpose

Keep one cage's team score and match history consistent. Build a trustworthy manual scoring tool and event logger before enabling automatic scoring.

## Operating Context

Supplied venue: 15 m by 10 m enclosed cage, 3v3, no goalkeeper. User confirmed prototype defaults: a 20-minute count-up clock; operator-controlled start, pause and resume; manual scoring; no automatic goal detection. The browser interface must operate without internet, cameras or models.

## Capabilities and Constraints

One active match; match-specific rosters and bibs; two teams; goal-end mapping; manual goals; append-only corrections; nullable attribution; transactional persistence; interrupted-clock reconciliation; read-only scoreboard. Hardware and goal geometry remain unknown. Automatic scorer attribution and analytics are later milestones.

## Evidence on Hand

IMPLEMENTATION_PLAN.md is the execution specification. PROJECT_REVIEW.md explains changes to the original concept. No venue footage, camera measurements, or accuracy evidence is present.

## Product Principles

- Display committed scores.
- Never turn silence into confirmation.
- Preserve correction history.
- Show interrupted or disconnected state clearly.
- Keep team scoring usable with unknown player attribution.
