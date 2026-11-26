import test from 'node:test';
import assert from 'node:assert/strict';

let imports = 0;
function browser(t) {
  let now = 0;
  const frames = [], instances = [], listeners = {};
  const saved = new Map();
  for (const name of ['location', 'window', 'requestAnimationFrame', 'WebSocket', 'document', 'fetch', 'performance']) saved.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) {
      let content = '';
      elements.set(id, {get textContent() {return content;}, set textContent(value) {content = String(value);},
        hidden: false, className: '', offsetWidth: 0, classList: {add() {}, remove() {}, toggle() {}}});
    }
    return elements.get(id);
  };
  class Socket {
    static OPEN = 1;
    constructor(url) {this.url = url; this.sent = []; this.readyState = 0; instances.push(this);}
    open() {this.readyState = 1; this.onopen?.();}
    receive(payload) {this.onmessage?.({data: JSON.stringify(payload)});}
    send(payload) {this.sent.push(JSON.parse(payload));}
    close() {if (this.readyState === 3) return; this.readyState = 3; this.onclose?.();}
  }
  const globals = {location: {protocol: 'http:', host: 'local.test'}, window: {addEventListener: (name, callback) => {listeners[name] = callback;}},
    requestAnimationFrame: (callback) => {frames.push(callback);}, WebSocket: Socket, document: {getElementById: element},
    fetch: async () => ({json: async () => ({venue_name: 'Dummy venue'})}), performance: {now: () => now}};
  for (const [name, value] of Object.entries(globals)) Object.defineProperty(globalThis, name, {configurable: true, writable: true, value});
  t.mock.timers.enable({apis: ['setTimeout', 'setInterval']});
  t.after(() => {
    t.mock.timers.reset();
    for (const [name, descriptor] of saved) {if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name];}
  });
  return {frames, instances, listeners, element, time: (value) => {now = value;}};
}

test('display acknowledges only after two animation-frame callbacks', async (t) => {
  const b = browser(t), snapshots = [];
  const {connect} = await import(`../../modules/api/static/common.js?case=${++imports}`);
  connect((match) => {snapshots.push(match);}, () => {}, {reportRendering: true});
  const socket = b.instances[0]; socket.open();
  socket.receive({type: 'snapshot', match: {score: {orange: 0, green: 1}}, match_id: 'match', revision: 4, event_id: 'goal'});
  assert.equal(snapshots.length, 1); assert.equal(socket.sent.length, 0);
  b.frames.shift()(); assert.equal(socket.sent.length, 0);
  b.frames.shift()();
  assert.deepEqual(socket.sent[0], {type: 'rendered', match_id: 'match', revision: 4, event_id: 'goal'});
});

test('private socket sends credentials in its handshake and drops data after lock', async (t) => {
  const b = browser(t), snapshots = [], states = [];
  let key = 'operator-key';
  const {connect} = await import(`../../modules/api/static/common.js?case=${++imports}`);
  connect((m) => {snapshots.push(m);}, (online) => states.push(online), {path: '/ws/operator/current', authorization: () => key});
  const socket = b.instances[0]; socket.open();
  assert.equal(socket.url, 'ws://local.test/ws/operator/current');
  assert.deepEqual(socket.sent[0], {operator_key: key});
  socket.receive({type: 'snapshot', match: {revision: 1}});
  key = null;
  socket.receive({type: 'snapshot', match: {revision: 2, candidates: ['private']}});
  assert.equal(snapshots.length, 1); assert.equal(socket.readyState, 3);
  assert.equal(states.at(-1), false);
});

test('silent transport reconnects and pagehide cancels all subsequent opens', async (t) => {
  const b = browser(t), states = [];
  const {connect} = await import(`../../modules/api/static/common.js?case=${++imports}`);
  connect(() => {}, (online) => states.push(online));
  b.instances[0].open(); b.time(4000); t.mock.timers.tick(1000);
  assert.equal(b.instances[0].readyState, 3); assert.equal(states.at(-1), false);
  t.mock.timers.tick(1500); assert.equal(b.instances.length, 2);
  b.listeners.pagehide(); t.mock.timers.tick(10000);
  assert.equal(b.instances.length, 2);
});

test('actual scoreboard script refuses older revisions and freezes a disconnected clock', async (t) => {
  const b = browser(t);
  await import(`../../modules/api/static/scoreboard.js?case=${++imports}`);
  const socket = b.instances[0]; socket.open();
  const match = {match_id: 'match', revision: 5, status: 'live', teams: {orange: 'Orange', green: 'Green'},
    score: {orange: 2, green: 1}, duration_seconds: 1200, elapsed_seconds: 10, restart_required: false};
  socket.receive({type: 'snapshot', match, match_id: 'match', revision: 5, event_id: 'new'});
  assert.equal(b.element('orange-score').textContent, '2');
  socket.receive({type: 'snapshot', match: {...match, revision: 4, score: {orange: 1, green: 1}}, match_id: 'match', revision: 4, event_id: 'old'});
  assert.equal(b.element('orange-score').textContent, '2');
  assert.equal(b.frames.length, 1);
  socket.close(); b.time(2000); t.mock.timers.tick(250);
  assert.equal(b.element('clock').textContent, '00:10');
  assert.match(b.element('match-message').textContent, /out of date/);
});
