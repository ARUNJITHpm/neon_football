export const byId = (id) => document.getElementById(id);
export const timeText = (seconds) => {
  const whole = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(whole / 60)).padStart(2, '0')}:${String(whole % 60).padStart(2, '0')}`;
};
export const uid = () => {
  if (crypto.randomUUID) return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (n) => n.toString(16).padStart(2, '0')).join('');
};
export function node(tag, content, className) {
  const element = document.createElement(tag);
  if (content !== undefined) element.textContent = content;
  if (className) element.className = className;
  return element;
}
export function button(label, callback, disabled = false) {
  const element = node('button', label);
  element.type = 'button';
  element.disabled = disabled;
  element.addEventListener('click', callback);
  return element;
}
export function scoreText(id, value) {
  const element = byId(id);
  if (element.textContent !== String(value)) {
    element.textContent = value;
    element.classList.remove('changed');
    void element.offsetWidth;
    element.classList.add('changed');
  }
}
export function connect(onMatch, onConnection, options = {}) {
  let socket;
  let timer;
  let stopped = false;
  let lastReceived = performance.now();
  const open = () => {
    if (stopped) return;
    const authorization = options.authorization?.();
    if (options.authorization && !authorization) {
      onConnection(false); timer = setTimeout(open, 1500); return;
    }
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${options.path || '/ws/matches/current'}`);
    lastReceived = performance.now();
    socket.onopen = () => {
      if (authorization) socket.send(JSON.stringify({operator_key: authorization}));
    };
    socket.onmessage = (event) => {
      try {
        if (options.authorization && options.authorization() !== authorization) {socket.close(); return;}
        const payload = JSON.parse(event.data);
        if (payload.type === 'snapshot') {
          lastReceived = performance.now();
          onConnection(true);
          const accepted = onMatch(payload.match);
          if (options.reportRendering && accepted !== false && payload.match && payload.event_id) {
            const target = socket;
            requestAnimationFrame(() => requestAnimationFrame(() => {
              if (target.readyState === WebSocket.OPEN) target.send(JSON.stringify({type: 'rendered', match_id: payload.match_id,
                revision: payload.revision, event_id: payload.event_id}));
            }));
          }
        }
      } catch {
        onConnection(false);
        socket.close();
      }
    };
    socket.onclose = () => {
      onConnection(false);
      clearTimeout(timer);
      if (!stopped) timer = setTimeout(open, 1500);
    };
    socket.onerror = () => socket.close();
  };
  open();
  const watchdog = setInterval(() => {
    if (socket && performance.now() - lastReceived > 3000) {onConnection(false); socket.close();}
  }, 1000);
  window.addEventListener('pagehide', () => {
    stopped = true;
    clearTimeout(timer);
    clearInterval(watchdog);
    if (socket) {socket.onclose = null; socket.close();}
  });
}
export function connectionLabel(connected) {
  const element = byId('connection');
  element.textContent = connected ? 'Connected' : 'Disconnected · last saved view';
  element.classList.toggle('offline', !connected);
}
