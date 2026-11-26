---
name: Neon Score
description: A local courtside console and read-only match scoreboard.
colors:
  ground: "#101412"
  surface: "#1b211d"
  rule: "#3a453e"
  ink: "#f1f5ef"
  muted: "#b5c2b8"
  orange: "#ffae70"
  green: "#b9ee79"
  error: "#ffb6ab"
  button-hover: "#2c372f"
  primary-hover: "#d1ffa2"
typography:
  display:
    fontFamily: "'Neon Numerals', 'Segoe UI', sans-serif"
    fontSize: "96px"
    fontWeight: 600
    lineHeight: 1.05
    letterSpacing: "-.02em"
  clock:
    fontFamily: "'Neon Numerals', 'Segoe UI', sans-serif"
    fontSize: "48px"
    lineHeight: 1.1
    letterSpacing: "-.01em"
  headline:
    fontSize: "clamp(26px, 3vw, 38px)"
    lineHeight: 1.15
    letterSpacing: "-.025em"
  title:
    fontSize: "23px"
    lineHeight: 1.25
  body:
    fontFamily: "'Segoe UI', Arial, sans-serif"
    fontSize: "16px"
    lineHeight: 1.5
  label:
    fontSize: "14px"
    fontWeight: 600
  button:
    fontSize: "16px"
    fontWeight: 600
rounded:
  control: "8px"
  surface: "12px"
spacing:
  small: "8px"
  control-gap: "12px"
  compact: "16px"
  regular: "24px"
  section: "32px"
  wide: "48px"
components:
  button-default:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "10px 18px"
  button-default-hover:
    backgroundColor: "{colors.button-hover}"
  button-primary:
    backgroundColor: "{colors.green}"
    textColor: "{colors.ground}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "10px 18px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-danger:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.error}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "10px 18px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "10px 18px"
  goal-button-orange:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.orange}"
    rounded: "{rounded.control}"
    padding: "10px 18px"
    width: "100%"
  goal-button-green:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.green}"
    rounded: "{rounded.control}"
    padding: "10px 18px"
    width: "100%"
  input:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
    width: "100%"
  notice:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.error}"
    rounded: "{rounded.surface}"
    padding: "24px"
  score-orange:
    textColor: "{colors.orange}"
    typography: "{typography.display}"
  score-green:
    textColor: "{colors.green}"
    typography: "{typography.display}"
---

# Design System: Neon Score

## Overview

**Creative North Star: "Courtside match console"**

The prototype uses a dark, quiet reading surface with orange and lime team identity. Strong alignment, prominent scores and an adjacent count-up clock support the operator's next action. History uses ruled records rather than a grid of metric cards. The separate spectator surface gives the score and clock more room.

This document merges the prototype's own provisional direction with the implemented system in `modules/api/static/style.css`, `operator.html`, `scoreboard.html` and their JavaScript modules. The direction and descriptive language are implementation choices, not a user-selected aesthetic or standing preference. Evidence is code-led: no rendered browser or screenshot inspection is available, visual acceptance is pending, and contrast has not been measured. The scope is the authorized Part 01 manual scoreboard; this document makes no camera, model or automatic-scoring capability claim.

The original seed considered referee sheets, stadium displays, broadcast desks, fixture boards, club noticeboards and substitution boards. Its retained disciplines are explicit conflicts, consistent team colors, distinct state vocabulary, restraint and readable measurement. Those explorations explain the prototype direction; they do not establish user-approved visual rejections.

**Key Characteristics:**

- Dark reading surface with restrained tonal layering.
- Team-colored scores, clearly named actions and written lifecycle states.
- Locally served assets and a dedicated numeral face.
- Ruled match history that preserves corrections.
- Responsive operator controls and a read-only spectator display.

## Colors

The palette combines dark green-tinted neutrals with warm orange, lime and a soft error accent. Frontmatter contains the normative values extracted from the stylesheet.

### Primary

- **Lime team and action accent** (`green`): Green team names, scores and goal controls; primary actions, live state, selection, caret and keyboard focus. Primary action hover uses `primary-hover`.

### Secondary

- **Warm orange team accent** (`orange`): Orange team names, scores and goal controls, plus the duration warning.
- **Soft error accent** (`error`): Error notices, disconnected/interrupted state and end-match action text.

### Neutral

- **Dark ground** (`ground`): Page and input background; dark text on primary actions.
- **Raised green-black surface** (`surface`): Default buttons, notices and recovery blocks.
- **Quiet rule** (`rule`): Dividers, fieldset boundaries, input and button borders, and scrollbar thumb.
- **Pale main ink** (`ink`): Body text, headings, links and default controls.
- **Muted supporting ink** (`muted`): Explanations, timestamps, connection text and historical secondary information.
- **Hover surface** (`button-hover`): Default and danger button hover.

**The Written State Rule.** Pair lifecycle, connectivity and correction color with explicit words; color alone must not carry match state.

## Typography

**Display Font:** `Neon Numerals`, the locally served `DejaVuSans-Bold.ttf` registered at weight 600, with Segoe UI and sans-serif fallbacks.

**Body Font:** Segoe UI, Arial and sans-serif. There is no external font dependency.

**Character:** Large, steady numerals carry the match reading. Familiar system text handles labels, explanations and records with little ornament.

### Hierarchy

- **Display:** The frontmatter display role is the operator score. At the narrow breakpoint it becomes 80 px. Spectator scores retain 96 px font size and use scale transforms of 1.8 on wide layouts and 1.3 on narrow layouts.
- **Clock:** The operator uses the frontmatter clock role. The spectator clock scales with `clamp(30px, 5vw, 72px)` on wide layouts and becomes 48 px on narrow layouts. Clock weight is inherited, rather than specified as the score's weight.
- **Headline:** The default heading role is in frontmatter. Access headings use `clamp(36px, 4vw, 52px)`; waiting headings use `clamp(30px, 5vw, 64px)`; spectator team headings use `clamp(26px, 3.5vw, 58px)`. Heading weight follows the browser's heading default.
- **Title:** Section headings use the frontmatter title role. Record titles use 18 px.
- **Body:** The frontmatter body role applies globally; general paragraph width is capped at 70 characters. Supporting text commonly uses 14 px, with 13 px helper and footer text.
- **Label:** Labels use the frontmatter label role; buttons use its separate button role. Labels remain sentence case.

**The Steady Numeral Rule.** Use tabular numerals for score, clock and event timestamps. Preserve the local numeral font and keep clock text on one line.

## Layout

The operator container has a 1200 px maximum width and desktop padding of 48 px 32 px 64 px. The header and footer use 5 vw horizontal padding. Access is a two-column grid with an 80 px gap; setup uses two equally sized team columns with a 32 px gap. Setup options use three columns.

The operator score strip uses `minmax(0, 1fr) minmax(150px, .6fr) minmax(0, 1fr)`, with a 32 px gap. Lifecycle actions wrap with a 12 px gap. The record aligns timestamps, detail and actions in three columns, separated by horizontal rules. Long team names and record headings may wrap.

At a maximum width of 760 px, the access layout becomes one column. The score pair stays side by side and the clock moves below both teams. Console padding becomes 32 px 24 px 48 px; record actions move below details. Setup options become two columns and their submit action spans both. At 480 px, team setup becomes one column, console side padding becomes 20 px, inline reconciliation controls wrap, and the footer stacks. These are implemented breakpoints, with rendered fit still pending inspection.

The spectator surface fills the viewport with a flex column. Its central display is capped at 1500 px and padded horizontally by 5 vw. Score and clock hierarchy is larger than the operator surface. Its narrow layout preserves the opposed pair and places the clock underneath.

The reusable spacing steps are in frontmatter. Some composition-specific sizes, including the access gap and score margins, remain local CSS values rather than global scale tokens.

## Elevation & Depth

The implementation has no box shadows, gradients or blur. Depth comes from the raised surface tone, borders and whitespace. Notices and interrupted-clock recovery use a filled surface; match history uses rules. Focus is a 3 px lime outline with a 4 px offset, independent of elevation.

**The Tonal Depth Rule.** Continue the existing flat and tonal surface language when extending this prototype; use boundaries and spacing to clarify groups.

## Shapes

Controls have gently curved corners using the `control` radius; fieldsets, notices and recovery blocks use the `surface` radius. Buttons, inputs and fieldsets have 1 px rules. The score strip and record are open layouts rather than enclosing cards. There are no implemented chips, pill controls or decorative clipping motifs.

## Components

### Buttons

Direct, readable actions use the frontmatter button variants, 1 px borders and a minimum height of 46 px. Primary actions are lime with dark text. Default actions use the raised surface; danger actions retain that surface with error-colored text; quiet actions have a transparent background. Default and danger hover use the hover surface; primary hover uses its brighter accent. Quiet buttons remain transparent on hover because their variant overrides the general hover background.

Background changes transition over 150 ms with `ease-out`. Keyboard focus uses the shared outline. Disabled buttons have opacity .58 and a disabled cursor; the default disabled-hover rule returns the background to the raised surface. No distinct pressed treatment is defined.

### Inputs / Fields

Ground-filled inputs, textareas and selects use a minimum height of 48 px, a 1 px rule and the frontmatter control padding and radius. Placeholder text uses muted ink; the caret is lime. Labels sit above fields. Focus uses the shared outline. Textareas resize vertically. Validation messages use the notice pattern and written text; no separate invalid-field border token is implemented.

### Navigation

The header uses a brand link and text actions rather than a tab bar. Main links use pale ink with a 4 px underline offset and turn lime on hover. The brand itself has no underline. At 760 px the brand subtitle moves underneath and header actions form a right-aligned column. No selected-navigation variant is implemented.

### Notices / Recovery

These rounded, raised-surface blocks use 24 px padding and a 32 px bottom margin. Notices use error text, while recovery uses a main-ink heading and muted explanation. Retry uncertainty stays visible with a named retry action. Interrupted-clock recovery asks for elapsed time before play resumes. At the narrow breakpoint, a notice action moves below its message.

### Score and Clock

Team names, scores and goal controls share the same team accent. Goal buttons occupy the team's width, with a minimum height of 60 px and 17 px text; narrow text becomes 15 px. Clock and score dimensions follow Typography and Layout.

A committed score change briefly brightens the numeral over 400 ms with `ease-out`; it does not move or scale as part of this animation. The spectator's resting scale is a separate layout treatment. Reduced-motion preference disables animation and transitions. Scores update from accepted server snapshots, not optimistic local increments. The spectator markup contains no write controls.

### Match Record

Each goal keeps a timestamp, title, attribution summary and applicable actions. Unknown scorer text is an explicit supported state. An undone goal remains visible with a struck-through, muted title and written undone status. Attribution editors expand in place; conflicting revisions show a written explanation. Empty records use supporting text above a rule. Pending incidents, when present, have confirm/reject actions and do not count without confirmation; this UI pattern does not imply automatic detection exists in Part 01.

## Do's and Don'ts

### Do:

- **Do** keep team identity consistent across names, numerals and goal actions.
- **Do** pair colors with written match, connection and correction states.
- **Do** preserve the committed-score update and visible correction history.
- **Do** keep fonts and runtime assets locally served so the interface can operate without internet.
- **Do** preserve the visible focus outline and reduced-motion behavior.
- **Do** inspect empty, connecting, disconnected, ready, live, paused, ended, interrupted, invalid-input, unknown-scorer and undone-goal states before visual acceptance.

### Don't:

- **Don't** display an uncertain action as a locally confirmed goal.
- **Don't** conceal undone records or require known player attribution to show a team goal.
- **Don't** add operator write controls to the spectator display.
- **Don't** treat this implementation direction as a user-approved aesthetic, verified contrast or completed visual review.
- **Don't** imply camera or automatic-scoring capability through decorative live indicators or fabricated match content.
