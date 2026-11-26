import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// Exercises the actual operator script against a small DOM model. No paint/media claim.
test('operator preserves review nodes and focus, and invalidates disconnected health', async (t) => {
  const roots = new Map(), sockets = [], objects = [], saved = new Map();
  let snapshot = null, delayedHealth = null;
  const commands = [];
  class Element {
    constructor(tag) {this.tagName = tag; this.children = []; this.listeners = {}; this.dataset = {}; this.value = ''; this.id = ''; this.disabled = false;
      this.classList = {add() {}, remove() {}, toggle() {}}; this.content = '';}
    set textContent(value) {this.content = String(value); this.replaceChildren();}
    get textContent() {return this.content + this.children.map((c) => c.textContent).join('');}
    append(...children) {for (const child of children) this.insertBefore(child, null);}
    insertBefore(child, before) {child.remove(); child.parent = this; this.children.splice(before ? this.children.indexOf(before) : this.children.length, 0, child);}
    replaceChildren(...children) {for (const child of [...this.children]) child.remove(); this.append(...children);}
    remove() {if (this.parent) {this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null;}}
    contains(element) {return this === element || this.children.some((child) => child.contains(element));}
    addEventListener(name, callback) {this.listeners[name] = callback;}
    setAttribute(name, value) {this[name] = value;}
    focus() {document.activeElement = this;}
    querySelector(selector) {return this.children.find((c) => selector.startsWith('.') ? c.className === selector.slice(1) : c.tagName === selector) || this.children.map((c) => c.querySelector(selector)).find(Boolean) || null;}
    click() {this.focus(); this.listeners.click?.({target: this, preventDefault() {}});}
  }
  const all = () => {const result = []; const visit = (element) => {result.push(element); element.children.forEach(visit);}; roots.forEach(visit); return result;};
  for (const id of readFileSync(new URL('../../modules/api/static/operator.html', import.meta.url), 'utf8').matchAll(/\bid="([^"]+)"/g)) {const element = new Element('div'); element.id = id[1]; roots.set(element.id, element);}
  for (const id of ['login', 'create-match', 'reconcile']) roots.get(id).append(new Element('button'));
  const option = new Element('option'); roots.get('review-mode').append(option);
  roots.get('review-mode').querySelector = () => option;
  const storage = new Map([['neon.key', 'dummy-key']]);
  class Socket {
    static OPEN = 1;
    constructor(url) {this.url = url; this.readyState = 0; sockets.push(this);}
    send() {}
    close() {this.readyState = 3; this.onclose?.();}
    open() {this.readyState = 1; this.onopen?.();}
    receive(match) {this.onmessage?.({data: JSON.stringify({type: 'snapshot', match})});}
  }
  const response = (data) => ({ok: true, status: 200, json: async () => data, blob: async () => new Blob(['dummy'])});
  const globals = {
    document: {activeElement: null, createElement: (tag) => new Element(tag), getElementById: (id) => all().find((e) => e.id === id) || null,
      querySelectorAll: () => all().filter((e) => e.dataset.deadline !== undefined)},
    location: {protocol: 'http:', host: 'local.test'}, window: {addEventListener() {}}, performance: {now: () => 0},
    sessionStorage: {getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key)},
    WebSocket: Socket, requestAnimationFrame() {}, confirm: () => true,
    URL: {createObjectURL: () => {const url = `blob:dummy-${objects.length}`; objects.push(url); return url;}, revokeObjectURL() {}},
    fetch: async (url, options) => {
      if (url.endsWith('/check')) return response({});
      if (url.endsWith('/config')) return response({venue_name: 'Dummy', default_duration_seconds: 1200, demo_review_enabled: true});
      if (url.endsWith('/current')) return response({match: snapshot});
      if (url.endsWith('/capture/status')) return delayedHealth ? await delayedHealth : response({enabled: false});
      if (url.endsWith('/displays/status')) return response({connected: 1, connections: [{state: 'rendering'}]});
      if (url.endsWith('/file')) return response({});
      if (url.endsWith('/commands')) {
        const command = JSON.parse(options.body);
        commands.push(command);
        const goalId = command.payload.goal_id;
        if (command.action === 'substitute_player') {
          snapshot = {...snapshot, revision: snapshot.revision + 1, roster_revision: snapshot.roster_revision + 1,
            active_player_ids: [...snapshot.active_player_ids.filter((id) => id !== command.payload.outgoing_id), command.payload.incoming_id]};
          return response({snapshot, event: {type: 'player_substituted'}});
        }
        if (command.action === 'demo_attribution') {
          const suggestion = {suggestion_id: 'dummy-suggestion', scorer_id: null, assist_id: null, own_goal: null, assist_status: 'unknown', reasons: ['Uncertain contact'], evidence: 'synthetic'};
          snapshot = {...snapshot, revision: snapshot.revision + 1,
            attribution_suggestions: [{goal_id: goalId, suggestion_id: suggestion.suggestion_id, status: 'pending', submission: {suggestion, sequence: {evidence: 'synthetic'}}}]};
          return response({snapshot, event: {type: 'attribution_suggested'}});
        }
        if (['accept_attribution', 'reject_attribution', 'attribute_goal'].includes(command.action)) {
          snapshot = {...snapshot, revision: snapshot.revision + 1,
            attribution_suggestions: snapshot.attribution_suggestions.map((s) => ({...s, status: command.action === 'accept_attribution' ? 'accepted' : command.action === 'reject_attribution' ? 'rejected' : 'superseded'}))};
          return response({snapshot, event: {type: command.action === 'reject_attribution' ? 'attribution_rejected' : 'attribution_changed', payload: {goal_id: goalId}}});
        }
        snapshot = {...snapshot, revision: snapshot.revision + 1, restart_required: true,
          candidates: snapshot.candidates.map((c) => c.candidate_id === command.payload.candidate_id ? {...c, status: 'confirmed'} : c)};
        return response({snapshot, event: {type: 'goal_confirmed'}});
      }
      throw new Error(`Unexpected ${url}`);
    }
  };
  for (const [name, value] of Object.entries(globals)) {saved.set(name, Object.getOwnPropertyDescriptor(globalThis, name)); Object.defineProperty(globalThis, name, {configurable: true, writable: true, value});}
  t.mock.timers.enable({apis: ['setTimeout', 'setInterval']});
  t.after(() => {t.mock.timers.reset(); for (const [name, descriptor] of saved) {if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name];}});
  const flush = async () => {for (let i = 0; i < 20; i++) await Promise.resolve();};
  await import('../../modules/api/static/operator.js?dom-case=1'); await flush();
  const candidate = (id) => ({candidate_id: id, status: 'pending_review', team: 'green', goal_end: 'goal_a', reason: 'Dummy',
    review_until: '2026-01-01T00:00:15Z', review: {candidate: {rule_label: 'review', reasons: ['dummy']}, evidence: [{observation: {evidence: 'synthetic'}}],
      clips: [{status: 'ready', detail: 'Generated test pattern'}]}});
  snapshot = {match_id: 'm', revision: 1, status: 'live', review_mode: 'demo_review', teams: {orange: 'Orange', green: 'Green'}, score: {orange: 0, green: 0},
    duration_seconds: 1200, elapsed_seconds: 0, server_time: '2026-01-01T00:00:00Z', goal_mapping: {goal_a: 'orange', goal_b: 'green'},
    candidates: [candidate('first'), candidate('second')], goals: [], players: []};
  const socket = sockets[0]; socket.open(); socket.receive(snapshot); await flush();
  const byId = (id) => document.getElementById(id);
  const row = byId('first-record'), detail = row.querySelector('details'); detail.open = true;
  byId('first-clip').click(); await flush();
  const video = byId('first-video'); video.currentTime = 1.25;
  assert.equal(detail.open, true); assert.equal(byId('first-record'), row);
  snapshot = {...snapshot, revision: 2, candidates: [snapshot.candidates[0], {...snapshot.candidates[1], status: 'unresolved'}]};
  byId('first-evidence').focus(); socket.receive(snapshot);
  assert.equal(byId('first-video'), video); assert.equal(video.currentTime, 1.25); assert.equal(detail.open, true);
  assert.equal(document.activeElement, byId('first-evidence'));
  byId('first-confirm').click(); await flush();
  assert.equal(byId('first-video'), video); assert.equal(document.activeElement, row);
  assert.equal(row.dataset.status, 'confirmed');
  snapshot = {...snapshot, revision: snapshot.revision + 1, roster_revision: 0, active_player_ids: ['g7', 'g11', 'o9'],
    players: [{id: 'g7', team: 'green', bib: 7, name: 'Seven'}, {id: 'g11', team: 'green', bib: 11, name: 'Eleven'},
      {id: 'o9', team: 'orange', bib: 9, name: 'Nine'}, {id: 'g15', team: 'green', bib: 15, name: 'Bench'}],
    goals: [{goal_id: 'goal', team: 'green', elapsed_seconds: 10, active: true, scorer_id: null, assist_id: null, own_goal: false}], attribution_suggestions: []};
  socket.receive(snapshot);
  assert.equal(byId('incoming-player').value, 'g15');
  byId('substitution').listeners.submit({preventDefault() {}}); await flush();
  assert.equal(commands.at(-1).action, 'substitute_player');
  assert.equal(commands.at(-1).payload.incoming_id, 'g15');
  assert.equal(byId('incoming-player').value, 'g7');
  byId('goal-scenario').value = 'uncertain'; byId('goal-scenario').listeners.change();
  byId('goal-suggest').click(); await flush();
  assert.equal(commands.at(-1).payload.scenario, 'uncertain');
  assert.equal(byId('goal-scenario').value, 'uncertain');
  assert.equal(byId('goal-apply-suggestion').disabled, true);
  const attributionDetail = byId('goal-attribution-evidence').parent;
  attributionDetail.open = true; attributionDetail.listeners.toggle();
  snapshot = {...snapshot, revision: snapshot.revision + 1}; socket.receive(snapshot);
  assert.equal(byId('goal-attribution-evidence').parent.open, true);
  byId('goal-reject-suggestion').click(); await flush();
  assert.equal(commands.at(-1).action, 'reject_attribution');
  assert.equal(document.activeElement, byId('goal-edit'));
  const known = {...snapshot.attribution_suggestions[0], status: 'pending',
    submission: {suggestion: {...snapshot.attribution_suggestions[0].submission.suggestion, scorer_id: 'g7', own_goal: false, assist_status: 'none'}}};
  snapshot = {...snapshot, revision: snapshot.revision + 1, attribution_suggestions: [known]}; socket.receive(snapshot);
  assert.equal(byId('goal-apply-suggestion').disabled, false);
  byId('goal-apply-suggestion').click(); await flush();
  assert.equal(commands.at(-1).action, 'accept_attribution');
  assert.equal(document.activeElement, byId('goal-edit'));
  byId('goal-edit').click();
  byId('goal-scorer_id').value = 'g11'; byId('goal-scorer_id').listeners.change();
  snapshot = {...snapshot, revision: snapshot.revision + 1}; socket.receive(snapshot);
  assert.equal(byId('goal-scorer_id').value, 'g11');
  assert.equal(byId('goal-save').disabled, true);
  byId('goal-cancel').focus(); snapshot = {...snapshot, revision: snapshot.revision + 1}; socket.receive(snapshot);
  assert.equal(document.activeElement, byId('goal-cancel'));
  byId('goal-cancel').click();
  assert.equal(document.activeElement, byId('goal-edit'));
  assert.equal(byId('goal-scorer_id'), null);
  let resolveHealth; delayedHealth = new Promise((resolve) => {resolveHealth = resolve;});
  t.mock.timers.tick(2000); await flush(); socket.close();
  assert.match(byId('display-status').textContent, /console disconnected/);
  resolveHealth(response({enabled: true, cameras: [{camera_id: 'old', health: 'healthy'}]})); await flush();
  assert.match(byId('capture-status').textContent, /console disconnected/);
  assert.match(byId('display-status').textContent, /console disconnected/);
});
