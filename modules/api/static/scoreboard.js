import {byId, connect, connectionLabel, scoreText, timeText} from './common.js';

let match = null;
let connected = false;
let receivedAt = performance.now();
const messages = {
  ready: 'Waiting for kick-off', live: 'Match in play', paused: 'Clock paused',
  ended: 'Final score', interrupted: 'Clock interrupted · operator review needed',
};

function render() {
  byId('waiting').hidden = Boolean(match);
  byId('match').hidden = !match;
  if (!match) return;
  byId('orange-label').textContent = match.teams.orange;
  byId('green-label').textContent = match.teams.green;
  scoreText('orange-score', match.score.orange);
  scoreText('green-score', match.score.green);
  byId('match-status').textContent = match.status === 'interrupted' ? 'Interrupted' : match.status === 'live' ? 'Live' : match.status.charAt(0).toUpperCase() + match.status.slice(1);
  byId('match-status').className = `state ${match.status}`;
  byId('clock-description').textContent = `${match.duration_seconds / 60}-minute match`;
  const liveMessage = match.restart_required && match.status === 'live' ? 'Goal recorded · waiting for operator restart' : messages[match.status];
  byId('match-message').textContent = connected ? liveMessage : 'Connection lost · score and clock may be out of date';
  tick();
}
function tick() {
  if (!match) return;
  const elapsed = match.elapsed_seconds + (connected && match.status === 'live' ? (performance.now() - receivedAt) / 1000 : 0);
  byId('clock').textContent = timeText(elapsed);
}
connect((snapshot) => {
  if (match && snapshot && match.match_id === snapshot.match_id && snapshot.revision < match.revision) return false;
  if (match && snapshot && match.match_id === snapshot.match_id && (match.score.orange !== snapshot.score.orange || match.score.green !== snapshot.score.green)) {
    byId('announcement').textContent = `Score updated. ${snapshot.teams.orange} ${snapshot.score.orange}, ${snapshot.teams.green} ${snapshot.score.green}.`;
  }
  match = snapshot;
  receivedAt = performance.now();
  render();
}, (online) => {
  connected = online;
  connectionLabel(online);
  render();
}, {reportRendering: true});
setInterval(tick, 250);
fetch('/api/v1/config').then((r) => r.json()).then((config) => {byId('venue').textContent = config.venue_name;}).catch(() => {});
