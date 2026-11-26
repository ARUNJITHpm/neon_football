import {byId, button, connect, connectionLabel, node, scoreText, timeText, uid} from './common.js';

let match = null;
let connected = false;
let unlocked = false;
let busy = false;
let receivedAt = performance.now();
let renderedKey = '';
let settingNext = false;
const drafts = new Map();
const clipUrls = new Map();
const clipRequests = new Set();
const candidateRows = new Map();
const attributionScenarios = new Map();
const attributionDisclosures = new Set();
let healthGeneration = 0;
let demoEnabled = true;
let linkedCandidate = '';
let modeDraft = null;
let pending = null;
let retryReadError = false;
try {pending = JSON.parse(sessionStorage.getItem('neon.pending') || 'null');}
catch {sessionStorage.removeItem('neon.pending'); retryReadError = true;}
const initialKey = sessionStorage.getItem('neon.key') || '';
byId('operator-key').value = initialKey;
byId('operator-name').value = sessionStorage.getItem('neon.actor') || 'Operator';

function notice(message = '') {
  byId('notice').textContent = message;
  byId('notice').hidden = !message;
}
function headers() {
  return {'Content-Type': 'application/json', Authorization: `Bearer ${sessionStorage.getItem('neon.key') || ''}`, 'X-Operator-Name': encodeURIComponent(sessionStorage.getItem('neon.actor') || 'Operator')};
}
function controlsDisabled() { return !unlocked || !connected || busy || Boolean(pending); }
function render(force = false) {
  byId('access').hidden = unlocked;
  byId('setup').hidden = !unlocked || Boolean(match && match.status !== 'ended') || Boolean(match && !settingNext);
  byId('match').hidden = !match || settingNext;
  byId('retry-panel').hidden = !pending || !unlocked;
  byId('retry').disabled = !connected || busy;
  byId('login').querySelector('button').disabled = busy;
  byId('create-match').querySelector('button').disabled = controlsDisabled();
  if (!match) return;
  tick();
  const disabled = controlsDisabled();
  const key = `${match.match_id}:${match.revision}:${unlocked}:${disabled}`;
  for (const team of ['orange', 'green']) {
    byId(`${team}-label`).textContent = match.teams[team];
    scoreText(`${team}-score`, match.score[team]);
    byId(`${team}-goal`).textContent = `Record ${match.teams[team]} goal`;
    const linked = match.candidates.find((c) => c.candidate_id === linkedCandidate && c.status === 'pending_review');
    byId(`${team}-goal`).disabled = disabled || match.status !== 'live' || match.restart_required || (linked && linked.team !== team);
  }
  byId('match-status').textContent = match.status.charAt(0).toUpperCase() + match.status.slice(1);
  byId('match-status').className = `state ${match.status}`;
  byId('match-reference').textContent = `· ${match.match_id.slice(0, 8)}`;
  byId('clock-description').textContent = `${match.duration_seconds / 60}-minute match`;
  byId('start').hidden = match.status !== 'ready';
  byId('pause').hidden = match.status !== 'live';
  byId('resume').hidden = match.status !== 'paused';
  byId('next-match').hidden = match.status !== 'ended';
  byId('end').hidden = match.status === 'ended';
  byId('recovery').hidden = match.status !== 'interrupted';
  byId('end-mapping').textContent = `Goal A defended by ${match.teams[match.goal_mapping.goal_a]} · Goal B defended by ${match.teams[match.goal_mapping.goal_b]}`;
  for (const id of ['start', 'pause', 'resume', 'end', 'next-match']) byId(id).disabled = disabled;
  byId('export').disabled = !unlocked || busy || !connected;
  byId('report').disabled = !unlocked || busy || !connected;
  byId('review-mode').disabled = disabled || !['ready', 'paused'].includes(match.status);
  if (modeDraft === null) byId('review-mode').value = match.review_mode || 'manual';
  byId('apply-mode').disabled = disabled || !['ready', 'paused'].includes(match.status) || byId('review-mode').value === match.review_mode;
  byId('review-mode-status').textContent = match.review_mode === 'demo_review' ? 'Dummy review · each goal needs your confirmation.' : 'Manual scoring · pause to change review mode.';
  byId('dummy-evidence').hidden = match.review_mode !== 'demo_review' || !unlocked;
  byId('add-demo').disabled = disabled || match.status !== 'live' || match.restart_required;
  byId('restart-play').hidden = match.review_mode !== 'demo_review';
  byId('restart-play').disabled = disabled || match.status !== 'live';
  byId('restart-help').hidden = !match.restart_required;
  byId('sensor-status').textContent = match.review_mode === 'demo_review' ? 'Sensors: generated impact evidence only' : 'Sensors: not connected';
  byId('swap').disabled = disabled || !['ready', 'paused'].includes(match.status) || match.candidates.some((c) => c.status === 'pending_review');
  byId('reconcile').querySelector('button').disabled = disabled;
  if (key === renderedKey && !force) return;
  renderedKey = key;
  if (match.status === 'interrupted' && !byId('reconcile-time').value) byId('reconcile-time').value = timeText(match.elapsed_seconds);
  const focused = document.activeElement?.id;
  renderRoster(disabled);
  renderGoals(disabled);
  renderCandidates(disabled);
  if (focused) document.getElementById(focused)?.focus({preventScroll: true});
}
function renderRoster(disabled) {
  const activeIds = match.active_player_ids || match.players.map((p) => p.id);
  const active = match.players.filter((p) => activeIds.includes(p.id));
  const bench = match.players.filter((p) => !activeIds.includes(p.id));
  const label = (p) => `${match.teams[p.team]} · ${p.bib} · ${p.name}`;
  byId('active-roster').textContent = active.length ? active.map(label).join(' / ') : 'No active players registered. Manual player editing remains available.';
  const outgoing = byId('outgoing-player'), incoming = byId('incoming-player');
  const previousOut = outgoing.value, previousIn = incoming.value;
  outgoing.replaceChildren(); incoming.replaceChildren();
  for (const p of active) {const option = node('option', label(p)); option.value = p.id; outgoing.append(option);}
  outgoing.value = active.some((p) => p.id === previousOut) ? previousOut : active[0]?.id || '';
  const team = active.find((p) => p.id === outgoing.value)?.team;
  const eligible = bench.filter((p) => p.team === team);
  for (const p of eligible) {const option = node('option', label(p)); option.value = p.id; incoming.append(option);}
  incoming.value = eligible.some((p) => p.id === previousIn) ? previousIn : eligible[0]?.id || '';
  const unavailable = disabled || !['ready', 'live', 'paused'].includes(match.status);
  outgoing.disabled = unavailable || !active.length;
  incoming.disabled = unavailable || !eligible.length;
  byId('substitute').disabled = unavailable || !outgoing.value || !incoming.value;
  byId('substitution-help').textContent = eligible.length ? 'Earlier goals keep their original active roster. Confirm these players before recording the substitution.' : 'No substitute is available for this team. Register bench players when creating the next match.';
}
function renderGoals(disabled) {
  const list = byId('goal-list');
  list.replaceChildren();
  const active = match.goals.filter((g) => g.active).length;
  byId('record-count').textContent = `${active} confirmed ${active === 1 ? 'goal' : 'goals'} · ${match.goals.length - active} undone`;
  if (!match.goals.length) {list.append(node('p', 'Goals will appear here once play starts.', 'empty')); return;}
  const players = new Map(match.players.map((p) => [p.id, p]));
  for (const goal of [...match.goals].reverse()) {
    const row = node('article', undefined, `goal-row${goal.active ? '' : ' undone'}`);
    row.dataset.goalId = goal.goal_id;
    row.append(node('time', timeText(goal.elapsed_seconds)));
    const details = node('div');
    details.append(node('h3', `${match.teams[goal.team]} goal${goal.active ? '' : ' · undone'}`));
    let summary = goal.scorer_id ? `${players.get(goal.scorer_id)?.name || 'Unknown player'}` : 'Scorer unknown';
    if (goal.own_goal) summary += ' · own goal';
    if (goal.assist_id) summary += ` · assist: ${players.get(goal.assist_id)?.name || 'Unknown'}`;
    details.append(node('p', summary));
    row.append(details);
    if (goal.active) {
      const actions = node('div', undefined, 'row-actions');
      const edit = button('Edit players', () => editAttribution(row, goal), disabled);
      edit.id = `${goal.goal_id}-edit`;
      edit.setAttribute('aria-label', `Edit players for ${match.teams[goal.team]} goal at ${timeText(goal.elapsed_seconds)}`);
      const undo = button('Undo goal', () => {
        if (confirm(`Undo ${match.teams[goal.team]}'s goal at ${timeText(goal.elapsed_seconds)}? The original record will be kept.`)) send('undo_goal', {goal_id: goal.goal_id});
      }, disabled);
      undo.setAttribute('aria-label', `Undo ${match.teams[goal.team]} goal at ${timeText(goal.elapsed_seconds)}`);
      actions.append(edit, undo);
      row.append(actions);
      if (demoEnabled && unlocked) renderAttributionSuggestion(row, goal, players, disabled);
    }
    list.append(row);
    if (goal.active && drafts.has(goal.goal_id)) editAttribution(row, goal, false);
    if (!goal.active) drafts.delete(goal.goal_id);
  }
}
function renderAttributionSuggestion(row, goal, players, disabled) {
  const wrapper = node('div', undefined, 'suggestion-review');
  const label = node('label', 'Dummy attribution example');
  const scenario = node('select'); scenario.id = `${goal.goal_id}-scenario`; label.htmlFor = scenario.id;
  for (const [value, title] of [['direct', 'Direct shot'], ['assist', 'Controlled teammate pass'], ['own_goal', 'Possible own goal'], ['uncertain', 'Uncertain contact'], ['deflection', 'Certain incidental deflection'], ['identity_switch', 'Conflicting bib readings']]) {
    const option = node('option', title); option.value = value; scenario.append(option);
  }
  scenario.value = attributionScenarios.get(goal.goal_id) || 'direct'; scenario.disabled = disabled;
  scenario.addEventListener('change', () => attributionScenarios.set(goal.goal_id, scenario.value));
  const load = button('Generate player suggestion', () => send('demo_attribution', {goal_id: goal.goal_id, scenario: scenario.value}), disabled);
  load.id = `${goal.goal_id}-suggest`;
  wrapper.append(label, scenario, load, node('p', 'Generated team/bib and contact observations. No camera recognition; applying names never changes the team score.', 'muted'));
  const item = [...(match.attribution_suggestions || [])].reverse().find((s) => s.goal_id === goal.goal_id);
  if (item) {
    const suggestion = item.submission.suggestion;
    const name = (id) => players.get(id)?.name || 'Unknown';
    wrapper.append(node('p', `Dummy suggestion · ${item.status}. Scorer: ${name(suggestion.scorer_id)}. Assist: ${suggestion.assist_status === 'unknown' ? 'Unknown' : suggestion.assist_id ? name(suggestion.assist_id) : 'None suggested'}. Own goal: ${suggestion.own_goal === null ? 'Unknown' : suggestion.own_goal ? 'Possible' : 'No'}.`));
    const detail = node('details', undefined, 'evidence-details'); detail.open = attributionDisclosures.has(item.suggestion_id);
    const summary = node('summary', 'Attribution observations and reasons'); summary.id = `${goal.goal_id}-attribution-evidence`;
    detail.append(summary, node('pre', JSON.stringify(item.submission, null, 2)));
    detail.addEventListener('toggle', () => {if (detail.open) attributionDisclosures.add(item.suggestion_id); else attributionDisclosures.delete(item.suggestion_id);});
    wrapper.append(detail);
    if (item.status === 'pending') {
      const reference = {goal_id: goal.goal_id, suggestion_id: item.suggestion_id};
      const actions = node('div', undefined, 'row-actions');
      const apply = button('Apply suggested players', () => send('accept_attribution', reference), disabled || suggestion.own_goal === null);
      apply.id = `${goal.goal_id}-apply-suggestion`;
      const reject = button('Reject player suggestion', () => send('reject_attribution', reference), disabled); reject.id = `${goal.goal_id}-reject-suggestion`;
      actions.append(apply, reject); wrapper.append(actions);
      if (suggestion.own_goal === null) wrapper.append(node('p', 'Outcome uncertain. Use Edit players to record your decision, or reject this suggestion.', 'muted'));
      else if (suggestion.assist_status === 'unknown') wrapper.append(node('p', 'Assist is unresolved. Applying this suggestion leaves the assist blank; you can edit it manually.', 'muted'));
    }
  }
  row.append(wrapper);
}
function editAttribution(row, goal, focus = true) {
  row.querySelector('.attribution-form')?.remove();
  if (!drafts.has(goal.goal_id)) drafts.set(goal.goal_id, {scorer_id: goal.scorer_id, assist_id: goal.assist_id, own_goal: goal.own_goal, revision: match.revision});
  const draft = drafts.get(goal.goal_id);
  const form = node('form', undefined, 'attribution-form');
  const select = (field, title) => {
    const wrapper = node('div');
    const label = node('label', title);
    const input = node('select');
    input.id = `${goal.goal_id}-${field}`;
    label.htmlFor = input.id;
    const unknown = node('option', 'Unknown / none'); unknown.value = ''; input.append(unknown);
    for (const player of match.players) {
      const option = node('option', `${match.teams[player.team]} · ${player.bib} · ${player.name}`); option.value = player.id; input.append(option);
    }
    input.value = draft[field] || '';
    input.addEventListener('change', () => {draft[field] = input.value || null;});
    wrapper.append(label, input); form.append(wrapper); return input;
  };
  const scorer = select('scorer_id', 'Scorer');
  const assist = select('assist_id', 'Assist');
  const check = node('div', undefined, 'check');
  const ownGoal = node('input'); ownGoal.type = 'checkbox'; ownGoal.id = `${goal.goal_id}-own`; ownGoal.checked = draft.own_goal;
  ownGoal.addEventListener('change', () => {draft.own_goal = ownGoal.checked;});
  const ownLabel = node('label', 'Own goal'); ownLabel.htmlFor = ownGoal.id; check.append(ownGoal, ownLabel); form.append(check);
  const actions = node('div', undefined, 'form-controls');
  const save = node('button', 'Save players', 'primary'); save.type = 'submit';
  save.id = `${goal.goal_id}-save`;
  save.disabled = controlsDisabled() || draft.revision !== match.revision;
  if (draft.revision !== match.revision) form.append(node('p', 'The match changed while you were editing. Cancel and reopen to review the latest record.', 'muted'));
  const cancel = button('Cancel', () => {
    drafts.delete(goal.goal_id); form.remove();
    const edit = document.getElementById(`${goal.goal_id}-edit`); if (edit && !edit.disabled) edit.focus({preventScroll: true});
  });
  cancel.id = `${goal.goal_id}-cancel`;
  actions.append(save, cancel); form.append(actions);
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    send('attribute_goal', {goal_id: goal.goal_id, scorer_id: scorer.value || null, assist_id: assist.value || null, own_goal: ownGoal.checked}, draft.revision);
  });
  row.append(form); if (focus) scorer.focus();
}
function renderCandidates(disabled) {
  const candidates = match.candidates;
  byId('review').hidden = !unlocked || !candidates.length;
  const choices = byId('manual-candidate');
  if (!candidates.some((c) => c.candidate_id === linkedCandidate && c.status === 'pending_review')) linkedCandidate = '';
  choices.replaceChildren();
  const fresh = node('option', 'New manual goal, no incident link'); fresh.value = ''; choices.append(fresh);
  for (const c of candidates.filter((item) => item.status === 'pending_review')) {
    const option = node('option', `${match.teams[c.team]} · ${c.goal_end === 'goal_a' ? 'Goal A' : 'Goal B'} · ${c.candidate_id.slice(-8)}`);
    option.value = c.candidate_id; choices.append(option);
  }
  choices.value = linkedCandidate; choices.disabled = disabled;
  const list = byId('candidate-list');
  const ids = new Set(candidates.map((c) => c.candidate_id));
  for (const [id, parts] of candidateRows) if (!ids.has(id)) {parts.row.remove(); candidateRows.delete(id);}
  for (const [index, candidate] of [...candidates].reverse().entries()) {
    let parts = candidateRows.get(candidate.candidate_id);
    if (!parts) {
      const row = node('article', undefined, 'candidate-row'); row.id = `${candidate.candidate_id}-record`; row.tabIndex = -1;
      const title = node('h3'), reason = node('p'), meta = node('p', '', 'candidate-meta');
      const resolution = node('p', '', 'candidate-meta'), actions = node('div', undefined, 'row-actions'), media = node('div');
      row.append(title, reason, meta, resolution, actions);
      if (candidate.review) {
        const detail = node('details', undefined, 'evidence-details');
        const summary = node('summary', 'Evidence and rule reason'); summary.id = `${candidate.candidate_id}-evidence`;
        detail.append(summary, node('pre', JSON.stringify({rule_suggestion: candidate.review.candidate.rule_label,
          reasons: candidate.review.candidate.reasons, evidence: candidate.review.evidence.map((e) => e.observation)}, null, 2)));
        row.append(detail);
      }
      row.append(media);
      parts = {row, title, reason, meta, resolution, actions, media, status: null, mediaKey: null};
      candidateRows.set(candidate.candidate_id, parts);
    }
    const {row, title, reason, meta, resolution, actions, media} = parts;
    if (list.children[index] !== row) list.insertBefore(row, list.children[index] || null);
    row.dataset.status = candidate.status;
    title.textContent = `${match.teams[candidate.team]} · ${candidate.goal_end === 'goal_a' ? 'Goal A' : 'Goal B'}`;
    reason.textContent = candidate.reason;
    meta.textContent = `${candidate.status.replaceAll('_', ' ')}${candidate.review ? ' · generated dummy evidence' : ''}`;
    meta.dataset.deadline = candidate.review_until || ''; meta.dataset.status = candidate.status;
    resolution.textContent = candidate.resolution_reason || ''; resolution.hidden = !candidate.resolution_reason;
    if (parts.status !== candidate.status) {
      const hadActionFocus = actions.contains(document.activeElement);
      actions.replaceChildren(); parts.status = candidate.status;
      if (candidate.status === 'pending_review') {
      const confirmGoal = button('Confirm goal', () => send('confirm_candidate', {candidate_id: candidate.candidate_id}), disabled || match.status !== 'live' || match.restart_required);
      confirmGoal.id = `${candidate.candidate_id}-confirm`;
      confirmGoal.setAttribute('aria-label', `Confirm ${match.teams[candidate.team]} goal for incident ${candidate.candidate_id.slice(-8)}`);
      const reject = button('Reject incident', () => send('reject_candidate', {candidate_id: candidate.candidate_id}), disabled || !['live', 'paused'].includes(match.status));
      reject.id = `${candidate.candidate_id}-reject`; actions.append(confirmGoal, reject);
      }
      if (hadActionFocus) row.focus({preventScroll: true});
    }
    const confirmControl = document.getElementById(`${candidate.candidate_id}-confirm`);
    const rejectControl = document.getElementById(`${candidate.candidate_id}-reject`);
    if (confirmControl) confirmControl.disabled = disabled || match.status !== 'live' || match.restart_required;
    if (rejectControl) rejectControl.disabled = disabled || !['live', 'paused'].includes(match.status);
    const url = clipUrls.get(candidate.candidate_id);
    const mediaKey = JSON.stringify([candidate.review?.clips, url || null, clipRequests.has(candidate.candidate_id)]);
    if (parts.mediaKey !== mediaKey) {
      const hadMediaFocus = media.contains(document.activeElement);
      media.replaceChildren(); parts.mediaKey = mediaKey;
      if (candidate.review) {
      const review = candidate.review;
      for (const clip of review.clips) {
        media.append(node('p', `Clip ${clip.status}: ${clip.detail}`, 'clip-state'));
        if (clip.status === 'ready') {
          if (url) {
            const video = node('video', undefined, 'review-video'); video.controls = true; video.playsInline = true; video.preload = 'metadata'; video.src = url;
            video.id = `${candidate.candidate_id}-video`;
            video.setAttribute('aria-label', 'Generated review test pattern, not footage of this incident'); media.append(video);
          } else {
            const load = button(clipRequests.has(candidate.candidate_id) ? 'Loading clip…' : 'Load generated clip', () => loadClip(candidate), false);
            load.id = `${candidate.candidate_id}-clip`; media.append(load);
          }
        }
      }
      } else media.append(node('p', 'Clip missing: no media was attached to this incident.', 'clip-state'));
      if (hadMediaFocus) (document.getElementById(`${candidate.candidate_id}-video`) || row).focus({preventScroll: true});
    }
    const loadControl = document.getElementById(`${candidate.candidate_id}-clip`);
    if (loadControl) loadControl.disabled = !unlocked || !connected || clipRequests.has(candidate.candidate_id);
  }
  tick();
}
function tick() {
  if (!match) return;
  const elapsed = match.elapsed_seconds + (connected && match.status === 'live' ? (performance.now() - receivedAt) / 1000 : 0);
  byId('clock').textContent = timeText(elapsed);
  byId('duration-warning').hidden = elapsed < match.duration_seconds;
  for (const element of document.querySelectorAll('[data-deadline]')) {
    if (element.dataset.status !== 'pending_review' || !element.dataset.deadline) continue;
    const serverNow = Date.parse(match.server_time) + (connected ? performance.now() - receivedAt : 0);
    const left = Math.max(0, Math.ceil((Date.parse(element.dataset.deadline) - serverNow) / 1000));
    element.textContent = `Pending review · generated evidence · ${left ? `${left}s left` : 'awaiting committed expiry'}`;
  }
}
function accept(snapshot) {
  if (match && snapshot && match.match_id === snapshot.match_id && snapshot.revision < match.revision) return;
  if (match && snapshot && match.match_id === snapshot.match_id && (match.score.orange !== snapshot.score.orange || match.score.green !== snapshot.score.green)) {
    byId('announcement').textContent = `Score updated. ${snapshot.teams.orange} ${snapshot.score.orange}, ${snapshot.teams.green} ${snapshot.score.green}.`;
  }
  if (match?.match_id !== snapshot?.match_id) {drafts.clear(); attributionScenarios.clear(); attributionDisclosures.clear(); clearClips(); linkedCandidate = ''; modeDraft = null; byId('reconcile-time').value = '';}
  if (match?.review_mode !== snapshot?.review_mode) modeDraft = null;
  match = snapshot;
  receivedAt = performance.now();
  if (match && match.status !== 'ended') settingNext = false;
  render();
}
async function refresh() {
  const response = await fetch('/api/v1/operator/matches/current', {headers: headers()});
  if (response.ok && unlocked) accept((await response.json()).match);
}
async function dispatch() {
  if (!pending || busy || !unlocked || !connected) return;
  const focusToRestore = document.activeElement?.id;
  const submittedGoal = pending.command.payload.goal_id;
  const submittedCandidate = pending.command.payload.candidate_id;
  busy = true; notice(); render();
  let definitive = false;
  try {
    const response = await fetch(pending.url, {method: 'POST', headers: {...headers(), 'X-Operator-Name': encodeURIComponent(pending.actor)}, body: JSON.stringify(pending.command)});
    if (response.status >= 500) throw new Error('Server could not finish the request. Retry the same action.');
    const result = await response.json();
    definitive = true;
    pending = null; sessionStorage.removeItem('neon.pending');
    if (!response.ok) {
      if (response.status === 401) {unlocked = false; sessionStorage.removeItem('neon.key');}
      const message = typeof result.detail === 'string' ? result.detail : result.detail?.map((e) => e.msg).join('; ') || 'Check the match details and try again.';
      notice(message);
    } else if (result.snapshot) {
      if (result.event.type === 'attribution_changed') drafts.delete(result.event.payload.goal_id);
      settingNext = false; accept(result.snapshot);
    }
  } catch (error) {
    notice(`${error.message || 'Connection lost.'} The action has not been counted locally.`);
  } finally {
    busy = false;
    if (definitive) {
      try {await refresh();} catch {connected = false; connectionLabel(false);}
    }
    render(true);
    const target = [(focusToRestore && document.getElementById(focusToRestore)),
      (submittedGoal && document.getElementById(`${submittedGoal}-edit`))].find((element) => element && !element.disabled);
    if (target) target.focus({preventScroll: true});
    else if (submittedCandidate) document.getElementById(`${submittedCandidate}-record`)?.focus({preventScroll: true});
    else if (pending && connected) byId('retry').focus({preventScroll: true});
  }
}
function send(action, payload = {}, revision = null) {
  if (controlsDisabled()) return;
  const create = action === 'create';
  if (!create && !match) return;
  pending = {url: create ? '/api/v1/matches' : `/api/v1/matches/${match.match_id}/commands`, actor: sessionStorage.getItem('neon.actor') || 'Operator',
    command: {command_id: uid(), expected_revision: create ? 0 : (revision ?? match.revision), action, payload}};
  sessionStorage.setItem('neon.pending', JSON.stringify(pending));
  dispatch();
}
async function login(event) {
  event?.preventDefault();
  if (busy) return;
  busy = true; notice(); render();
  const token = byId('operator-key').value.trim();
  const actor = byId('operator-name').value.trim();
  try {
    const response = await fetch('/api/v1/operator/check', {method: 'POST', headers: {Authorization: `Bearer ${token}`, 'X-Operator-Name': encodeURIComponent(actor)}});
    if (!response.ok) throw new Error('The operator key was not accepted. Check the local key file.');
    sessionStorage.setItem('neon.key', token); sessionStorage.setItem('neon.actor', actor);
    unlocked = true;
    await refresh();
  } catch (error) {unlocked = false; sessionStorage.removeItem('neon.key'); notice(error.message);}
  finally {busy = false; render(true);}
}
byId('login').addEventListener('submit', login);
byId('lock').addEventListener('click', () => {unlocked = false; sessionStorage.removeItem('neon.key'); byId('operator-key').value = ''; clearClips(); drafts.clear(); match = null; byId('goal-list').replaceChildren(); byId('candidate-list').replaceChildren(); render(true);});
byId('create-match').addEventListener('submit', (event) => {
  event.preventDefault();
  try {
    const players = [], active_player_ids = [];
    for (const team of ['orange', 'green']) {
      const bibs = new Set();
      for (const line of byId(`${team}-roster`).value.split('\n').filter((value) => value.trim())) {
        const separator = line.indexOf(',');
        const bibText = line.slice(0, separator).trim();
        const rawName = line.slice(separator + 1).trim();
        const benched = /,\s*bench$/i.test(rawName);
        const name = benched ? rawName.replace(/,\s*bench$/i, '').trim() : rawName;
        if (separator < 0 || !/^\d{1,2}$/.test(bibText) || !name || name.length > 60) throw new Error(`Check ${team}'s roster: use a bib from 0 to 99, followed by a comma and a name.`);
        const bib = Number(bibText);
        if (bibs.has(bib)) throw new Error(`Bib ${bib} appears twice on the ${team} team.`);
        bibs.add(bib); const id = uid(); players.push({id, team, bib, name}); if (!benched) active_player_ids.push(id);
      }
    }
    send('create', {orange_name: byId('orange-name').value.trim(), green_name: byId('green-name').value.trim(), duration_seconds: Number(byId('duration').value) * 60, goal_a_defending: byId('goal-a').value, players, active_player_ids});
  } catch (error) {notice(error.message);}
});
for (const action of ['start', 'pause', 'resume']) byId(action).addEventListener('click', () => send(action));
for (const team of ['orange', 'green']) byId(`${team}-goal`).addEventListener('click', () => send('manual_goal', {team, ...(linkedCandidate ? {candidate_id: linkedCandidate} : {})}));
byId('manual-candidate').addEventListener('change', (event) => {linkedCandidate = event.target.value; render(true);});
byId('review-mode').addEventListener('change', (event) => {modeDraft = event.target.value; render(true);});
byId('apply-mode').addEventListener('click', () => send('set_review_mode', {mode: byId('review-mode').value}));
byId('restart-play').addEventListener('click', () => send('restart_play'));
byId('demo-incident').addEventListener('submit', (event) => {event.preventDefault(); send('demo_incident', {goal_end: byId('demo-end').value, scenario: byId('demo-scenario').value});});
byId('outgoing-player').addEventListener('change', () => renderRoster(controlsDisabled()));
byId('substitution').addEventListener('submit', (event) => {event.preventDefault(); send('substitute_player', {outgoing_id: byId('outgoing-player').value, incoming_id: byId('incoming-player').value});});
byId('swap').addEventListener('click', () => send('swap_ends'));
byId('end').addEventListener('click', () => {if (confirm('End this match? The final score and corrections will remain available.')) send('end');});
byId('next-match').addEventListener('click', () => {settingNext = true; notice(); render(); byId('orange-name').focus();});
byId('retry').addEventListener('click', dispatch);
byId('reconcile').addEventListener('submit', (event) => {
  event.preventDefault();
  const value = byId('reconcile-time').value.trim();
  if (!/^\d{1,4}:[0-5]\d$/.test(value)) return notice('Enter elapsed time as minutes:seconds, for example 05:30.');
  const [minutes, seconds] = value.split(':').map(Number);
  send('reconcile_clock', {elapsed_seconds: minutes * 60 + seconds});
});
byId('export').addEventListener('click', async () => {
  if (!match || !unlocked || busy) return;
  try {
    const response = await fetch(`/api/v1/matches/${match.match_id}/export`, {headers: headers()});
    if (!response.ok) throw new Error('Match export failed. Unlock the console and try again.');
    const url = URL.createObjectURL(await response.blob());
    const link = node('a'); link.href = url; link.download = `match-${match.match_id}.json`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {notice(error.message);}
});
function clearClips() {for (const url of clipUrls.values()) URL.revokeObjectURL(url); clipUrls.clear(); candidateRows.clear(); byId('candidate-list').replaceChildren();}
async function loadClip(candidate) {
  const matchId = match.match_id;
  clipRequests.add(candidate.candidate_id); render(true);
  try {
    const response = await fetch(`/api/v1/matches/${matchId}/candidates/${candidate.candidate_id}/clip/file`, {headers: headers()});
    if (!response.ok) throw new Error('Clip is unavailable. You can still confirm or reject the incident.');
    const blob = await response.blob();
    if (unlocked && match?.match_id === matchId) {
      if (clipUrls.size >= 8) {const oldest = clipUrls.keys().next().value; URL.revokeObjectURL(clipUrls.get(oldest)); clipUrls.delete(oldest);}
      clipUrls.set(candidate.candidate_id, URL.createObjectURL(blob));
    }
  } catch (error) {notice(error.message);}
  finally {clipRequests.delete(candidate.candidate_id); render(true);}
}
byId('report').addEventListener('click', async () => {
  if (!match || !unlocked || busy || !connected) return;
  try {
    const response = await fetch(`/api/v1/matches/${match.match_id}/report.txt`, {headers: headers()});
    if (!response.ok) throw new Error('Report download failed. Unlock the console and retry.');
    const url = URL.createObjectURL(await response.blob());
    const link = node('a'); link.href = url; link.download = `match-${match.match_id}-report.txt`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {notice(error.message);}
});
async function inputHealth() {
  if (!unlocked || !connected) return;
  const generation = ++healthGeneration;
  try {
    const [captureResponse, displayResponse] = await Promise.all([fetch('/api/v1/capture/status', {headers: headers()}), fetch('/api/v1/displays/status', {headers: headers()})]);
    if (!unlocked || !connected || generation !== healthGeneration) return;
    if (!captureResponse.ok || !displayResponse.ok) throw new Error('Input status unavailable; reconnect the console.');
    const capture = await captureResponse.json();
    if (!unlocked || !connected || generation !== healthGeneration) return;
    byId('capture-status').textContent = capture.enabled ? `Cameras: ${(capture.cameras || []).map((c) => `${c.camera_id} ${c.health}`).join(' · ')}` : `Cameras: ${capture.error ? 'unavailable' : 'not connected'} · manual scoring available`;
    const displays = await displayResponse.json();
    if (!unlocked || !connected || generation !== healthGeneration) return;
    const ready = displays.connections.filter((c) => c.state === 'rendering').length;
    byId('display-status').textContent = !displays.connected ? 'Scoreboard: disconnected · open the read-only display' : `Scoreboard: ${ready} rendering, ${displays.connected - ready} awaiting a fresh render`;
  } catch (error) {if (unlocked && connected && generation === healthGeneration) {byId('capture-status').textContent = error.message; byId('display-status').textContent = 'Scoreboard status unavailable';}}
}
connect((snapshot) => {if (unlocked) accept(snapshot);}, (online) => {const changed = connected !== online; connected = online; connectionLabel(online); if (changed) {render(); if (online) inputHealth(); else {healthGeneration++; byId('capture-status').textContent = 'Cameras: unavailable · console disconnected'; byId('display-status').textContent = 'Scoreboard: unavailable · console disconnected';}}},
  {path: '/ws/operator/current', authorization: () => sessionStorage.getItem('neon.key')});
setInterval(tick, 250);
setInterval(inputHealth, 2000);
fetch('/api/v1/config').then((r) => r.json()).then((config) => {byId('venue').textContent = config.venue_name; byId('duration').value = config.default_duration_seconds / 60; demoEnabled = config.demo_review_enabled;
  byId('review-mode').querySelector('option[value="demo_review"]').disabled = !demoEnabled;}).catch(() => {});
render();
if (retryReadError) notice('Saved retry could not be read. Check the match record before scoring again.');
if (initialKey) login();
