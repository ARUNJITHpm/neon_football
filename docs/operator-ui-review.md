# Part 07 operator UI review

Reviewed 2026-10-11. This is a bounded, code-led record of the Part 07 operator extension. The authorized direction is to preserve the incumbent courtside console. It does not refresh `PRODUCT.md`, `DESIGN.md` or `.impeccable/design.json`, change the visual identity, or repair earlier token drift.

The Impeccable documenter pass read those three context files and `modules/api/static/operator.html`, `operator.js`, `style.css`, `common.js` and `scoreboard.js`. The existing design direction remains an implementation choice; it is not a user-selected aesthetic or a completed visual approval.

## Implemented behavior

- The operator can select manual scoring or dummy evidence review and apply that choice while the match is ready or paused. The dummy option is disabled when server configuration disables it. Camera, sensor and scoreboard status use written descriptions, including disconnected and unavailable states.
- Dummy review offers six named examples: observed crossing/impact, uncertain partial crossing, net contact, and missing, encoding or failed clips. The form explicitly says generated evidence does not detect a real goal. Pending incidents show the team, goal end, reason, status and remaining review time; reaching zero says “awaiting committed expiry” rather than declaring a local outcome.
- Confirm/reject actions operate on the selected incident. The team goal buttons can link a manual goal to a pending incident; the opposite team's button is disabled for that link. Confirming requires live play without a restart requirement, while rejecting is available during live or paused play. A saved goal shows a written restart prompt, and further scoring stays gated until restart. Changing ends is disabled while an incident remains pending.
- Evidence and rule reasons expand using native disclosure controls. Clip state stays visible whether media is missing, pending, failed or ready. Ready media loads on request through the authenticated operator route. The video has native controls and identifies itself as a generated test pattern, not incident footage. A clip load failure leaves incident resolution available. Download report supplements the existing match export.
- Commands continue to show committed server scores. An uncertain request retains its command for explicit retry and does not increment the score locally. Match history retains undone goals and supports unknown player attribution. The spectator page remains read-only and shows written restart/disconnection messages.

## Consistency with the incumbent design

This extension retains the dark ground, raised surface, rules, pale/muted ink, orange/green team identity and error accent. Review sections use ruled records and existing button/input treatments rather than a replacement card system. The score/clock hierarchy, local numeral face, Segoe UI body stack, rounded controls and flat tonal depth remain in use. No new typeface, external font dependency, shadow, gradient or decorative motion was introduced.

The new review settings use the existing 32 px grouping gap and 24 px section padding. Candidate actions wrap, evidence text wraps, and video width is bounded. At 760 px, review settings become one column, the dummy form becomes two columns with a full-width action, and incident actions wrap with minimum widths. At 480 px, the dummy form becomes one column. These are implemented CSS rules; their rendered fit has not been verified.

Earlier analyzer findings were supplied to this pass; the detector was not rerun. Existing advisories involving 80/15/28/12/17/20 px values remain recorded as incumbent exceptions, not newly approved global tokens. Evidence text reuses the existing 13 px helper size. The reported font label `ui` differs from the declared SegoeUI token, while the actual stylesheet uses `'Segoe UI', Arial, sans-serif` for body text and the incumbent local numeral stack for scores/clock. This analyzer label mismatch does not establish a new runtime font. Its classification remains unresolved; this extension does not rename the font or rewrite the token declarations.

## Accessibility and update stability

The markup uses labeled native selects/forms, named sections, buttons, disclosure controls and video controls. Shared keyboard focus remains a 3 px lime outline with a 4 px offset; reduced-motion preference disables animations/transitions. Notices use alert semantics, connection/input health and restart prompts use status semantics, and committed score changes have a polite, atomic announcement. Incident confirmation includes the team and incident identifier in its accessible name. Written statuses supplement color.

Candidate rows are retained by candidate ID. Unrelated snapshot updates retain the evidence disclosure and loaded video nodes, preserving their open/playback state. Actions are replaced when incident status changes; focus moves to the incident record if the focused action disappears. A clip-control replacement moves focus to the video or record. Command completion restores a surviving control or the affected incident record. This addresses the reviewer's update/focus concern without rebuilding unchanged review media on every revision.

On transport disconnection, camera and scoreboard labels immediately become unavailable. Health requests carry a generation guard and check connected/unlocked state after awaits, preventing an older response from overwriting those disconnected labels. The client closes silent transports, reconnects, and cancels subsequent opens on page exit. Scoreboard render acknowledgments are scheduled after two animation-frame callbacks; that scheduling is not proof that pixels appeared on the venue display.

## Verification and remaining evidence

The implementation owner reports five passing Node tests in `tests/operator/client.test.mjs` and `tests/operator/operator-dom.test.mjs`. The tests exercise the actual client scripts using mocked transport/timers and a small DOM model. They cover render-ack scheduling, private socket credentials and lock behavior, reconnect/page-exit handling, stale scoreboard revision rejection and disconnected-clock behavior, plus candidate node/focus retention and stale health-response invalidation. This pass inspected those tests; it did not rerun them.

No browser or screenshot evidence was available for this pass. There was no rendered desktop/mobile inspection, native media playback verification, contrast measurement, assistive-technology trial, physical display timing measurement or visual acceptance. Rendering and accessibility acceptance remain pending; passing DOM-model tests do not supply paint evidence.

The root design artifacts still describe their original Part 01 extraction and do not catalog every Part 07 component. Existing analyzer/token mismatches and spacing exceptions remain outside this task. A later explicit design-context refresh can decide whether to document those incumbent exceptions, normalize them, or retain the current declarations; no such system-wide choice was made here.

## Part 09 operator attribution extension

Reviewed 2026-10-11. This appendix records the authorized Part 09 extension at source and test scope and preserves the historical Part 07 review above. The surface remains an Operate console: precise provenance, explicit operator approval and conservative handling of uncertainty guide the new controls. The user confirmed the dummy attribution rules and operator approval workflow; no new visual world or approved comparison image was supplied.

### Implemented behavior

- Match setup retains one player per line using `bib number, name`; appending `, bench` registers a substitute. Bibs remain unique within each team. The active-roster section lists team, bib and player name. Substitution selectors pair an active outgoing player with a bench player from the same team, preserve still-valid selections across updates and disable unavailable substitutions. Earlier goals retain their captured active roster and roster revision.
- Each active goal offers six labeled dummy attribution examples: Direct shot, Controlled teammate pass, Possible own goal, Uncertain contact, Certain incidental deflection and Conflicting bib readings. Generate player suggestion submits the chosen example; written copy identifies generated team/bib and contact observations, states that camera recognition is absent and explains that applying players does not change the team score.
- The latest suggestion shows its status, scorer, assist and own-goal outcome in words, with observations and reasons in a native disclosure. Pending suggestions require Apply suggested players or Reject player suggestion. An unknown own-goal outcome disables Apply and directs the operator to Edit players or reject. An unresolved assist remains explicitly unknown; applying an otherwise eligible suggestion leaves the assist blank for manual editing.
- Edit players retains nullable scorer/assist and an own-goal checkbox. Draft values survive snapshot updates. A draft keeps its starting match revision; if the match changes, Save is disabled and a written message asks the operator to cancel and reopen against the current record. Successful attribution changes clear the completed draft. Scenario selection and the open attribution disclosure state survive unrelated revisions and reset for another match.

### Consistency, responsive rules and focus

The extension preserves the existing dark courtside palette, orange/green identity, ruled records, native form/disclosure controls, local numeral face and Segoe UI body stack. It reuses the shared focus outline, reduced-motion behavior and existing control treatments. No new palette, typography scale or global design token was introduced. `PRODUCT.md`, `DESIGN.md` and `.impeccable/design.json` remain preserved; this appendix does not refresh their Part 01 extraction or classify incumbent drift as approved.

Suggestion actions and goal-row actions wrap. Attribution columns use `minmax(0, 1fr)` and their field wrappers allow zero minimum width; suggestion content also allows zero minimum width. Roster and goal supporting text can wrap long names. At 760 px, suggestions span the record, the attribution form uses two flexible columns, the substitution action spans those columns and suggestion actions wrap with minimum widths. These are inspected CSS rules, with rendered fit pending.

Cancel now has a stable goal-specific ID, allowing focus restoration after a revision rebuild; canceling removes the draft and returns focus to the surviving enabled Edit players button. Apply/reject command completion also falls back to that goal's Edit players control when the submitted action disappears. The bounded finish review found the stable Cancel target and flexible-column/text-wrap changes sufficient to ship at source/test scope. It did not grant rendered or accessibility acceptance.

### Verification and remaining evidence

The implementation owner reports five passing Node tests in `tests/operator/client.test.mjs` and `tests/operator/operator-dom.test.mjs` (328.924 ms), after the final UI fixes. This documenter inspected the actual-script DOM-model assertions for substitution commands, retained scenario choice, disabled Apply for an unknown outcome, disclosure state across revisions, apply/reject focus fallback, draft retention, revision-conflict gating and stable Cancel focus/return. These tests establish scripted behavior under mocked transport and a small DOM model. They do not establish browser paint, layout, native keyboard behavior or media playback. The backend was verified separately by the implementation owner, including the additional compatibility and candidate-roster checks.

The Part 09 detector ran once in the implementation pass and was not rerun here. The supplied findings retain the incumbent `ui` font-label mismatch and 80/15/28/12/17/20/13 px advisories. The runtime body stack remains Segoe UI with its existing fallbacks; these findings do not establish a new font or authorize system-wide token changes.

No fresh browser screenshots were available: the earlier browser inventory was empty, sandbox approval for the Playwright attempt was denied and native computer control was unavailable. Rendered inspection at 1440 px and 390 px, keyboard traversal/focus acceptance, native media behavior, measured contrast and HDMI/venue-display acceptance remain pending. No screenshot comparison or approved visual comp supports this handoff. The incumbent direction contract and conservative provenance copy are documented from source only.
