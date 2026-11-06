(() => {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const HOLD_MS = 450;
  const TOKEN_STORAGE = 'hisense-remote.token';
  const STATUS_LABELS = {
    connected: 'Connected',
    connecting: 'Connecting…',
    reconnecting: 'Reconnecting…',
    disconnected: 'Disconnected',
    unreachable: 'Unreachable',
    needs_pairing: 'Needs pairing',
    pairing: 'Pairing…',
  };
  const KEYMAP = {
    ArrowUp: 'DPAD_UP', ArrowDown: 'DPAD_DOWN', ArrowLeft: 'DPAD_LEFT', ArrowRight: 'DPAD_RIGHT',
    Enter: 'DPAD_CENTER', Backspace: 'BACK', Escape: 'BACK', ' ': 'MEDIA_PLAY_PAUSE',
    '+': 'VOLUME_UP', '=': 'VOLUME_UP', '-': 'VOLUME_DOWN', '_': 'VOLUME_DOWN',
    h: 'HOME', m: 'MENU', i: 'INFO', g: 'GUIDE', s: 'SEARCH',
    0: '0', 1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8', 9: '9',
  };

  const app = { token: '', ws: null, wsOpen: false, state: null, apps: [], seq: 0, pollTimer: null, reconnectTimer: null, toastTimer: null, installPrompt: null };
  try { app.token = localStorage.getItem(TOKEN_STORAGE) || ''; } catch (e) { app.token = ''; }

  // A token embedded in the URL (from the QR code) is saved once and removed from the address bar.
  try {
    const params = new URLSearchParams(location.search);
    if (params.has('token')) {
      app.token = params.get('token') || '';
      try { localStorage.setItem(TOKEN_STORAGE, app.token); } catch (e) { /* ignore */ }
      params.delete('token');
      const rest = params.toString();
      history.replaceState(null, '', location.pathname + (rest ? '?' + rest : '') + location.hash);
    }
  } catch (e) { /* ignore */ }

  // ---- HTTP -----------------------------------------------------------------

  function headers() {
    const h = { 'Content-Type': 'application/json' };
    if (app.token) h['X-Auth-Token'] = app.token;
    return h;
  }

  async function api(path, opts = {}) {
    let res;
    try {
      res = await fetch(path, { headers: headers(), ...opts });
    } catch (e) {
      throw Object.assign(new Error('Cannot reach the remote server'), { code: 'network' });
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      const err = new Error(data.message || res.statusText || 'Request failed');
      err.code = data.error || ('http_' + res.status);
      err.state = data.state;
      throw err;
    }
    return data;
  }

  const post = (path, body) => api(path, { method: 'POST', body: JSON.stringify(body || {}) });

  function handleError(err) {
    if (err && err.state) render(err.state);
    if (err && err.code === 'unauthorized') { toast('Access token required: open the settings panel'); openDrawer(); return; }
    if (err && err.code === 'needs_pairing') { toast('The TV needs to be paired first'); openDrawer(); return; }
    toast((err && err.message) || String(err));
  }

  // ---- live updates ----------------------------------------------------------

  function wsUrl() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const q = app.token ? '?token=' + encodeURIComponent(app.token) : '';
    return `${proto}//${location.host}/ws${q}`;
  }

  function connectWS() {
    clearTimeout(app.reconnectTimer);
    if (app.ws) { try { app.ws.close(); } catch (e) { /* ignore */ } }
    let ws;
    try { ws = new WebSocket(wsUrl()); } catch (e) { startPolling(); return; }
    app.ws = ws;
    ws.onopen = () => { app.wsOpen = true; stopPolling(); setConnMode('live'); };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if ((msg.type === 'state' || msg.type === 'ack' || msg.type === 'pong') && msg.state) render(msg.state);
      else if (msg.type === 'error') handleError(Object.assign(new Error(msg.message), { code: msg.error }));
    };
    ws.onclose = () => {
      if (app.ws !== ws) return;
      app.wsOpen = false; app.ws = null;
      setConnMode('polling');
      startPolling();
      app.reconnectTimer = setTimeout(connectWS, 2500);
    };
    ws.onerror = () => { /* onclose follows */ };
  }

  function startPolling() {
    if (app.pollTimer) return;
    const tick = () => api('/api/state').then((d) => render(d.state)).catch((err) => { if (err.code === 'unauthorized') { stopPolling(); handleError(err); } });
    tick();
    app.pollTimer = setInterval(tick, 5000);
  }
  function stopPolling() { clearInterval(app.pollTimer); app.pollTimer = null; }
  function setConnMode(mode) { $('#conn-mode').textContent = mode; }

  // ---- commands --------------------------------------------------------------

  function vibrate() { if (navigator.vibrate) { try { navigator.vibrate(8); } catch (e) { /* ignore */ } } }

  function sendKey(key, direction = 'SHORT') {
    vibrate();
    if (app.ws && app.wsOpen) {
      app.ws.send(JSON.stringify({ type: 'key', key, direction, id: ++app.seq }));
      return;
    }
    post('/api/key', { key, direction }).then((d) => d.state && render(d.state)).catch(handleError);
  }
  const sendText = (text) => post('/api/text', { text }).then(() => toast('Sent to the TV')).catch(handleError);
  const launchApp = (id, name) => post('/api/app', { app: id }).then(() => toast('Opening ' + (name || id))).catch(handleError);
  const wake = () => post('/api/wake').then(() => toast('Wake-on-LAN packet sent')).catch(handleError);

  // ---- buttons: tap = SHORT, hold = START_LONG … END_LONG -----------------------

  function bindKeyButtons(root = document) {
    root.querySelectorAll('[data-key]').forEach((btn) => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = '1';
      let timer = null; let held = false; let active = false;
      const start = (ev) => {
        if (ev.button !== undefined && ev.button !== 0) return;
        active = true; held = false;
        try { btn.setPointerCapture(ev.pointerId); } catch (e) { /* ignore */ }
        timer = setTimeout(() => { held = true; btn.classList.add('holding'); sendKey(btn.dataset.key, 'START_LONG'); }, HOLD_MS);
      };
      const finish = (cancelled) => {
        if (!active) return;
        active = false; clearTimeout(timer); timer = null;
        if (held) { held = false; btn.classList.remove('holding'); sendKey(btn.dataset.key, 'END_LONG'); }
        else if (!cancelled) sendKey(btn.dataset.key, 'SHORT');
        btn.blur();
      };
      btn.addEventListener('pointerdown', start);
      btn.addEventListener('pointerup', () => finish(false));
      btn.addEventListener('pointercancel', () => finish(true));
      btn.addEventListener('contextmenu', (ev) => ev.preventDefault());
      btn.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); sendKey(btn.dataset.key); } });
    });
  }

  function onKeyboard(ev) {
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    const t = ev.target;
    if (t && t.matches && t.matches('input, textarea, select, [contenteditable]')) return;
    if (!$('#drawer').classList.contains('hidden')) { if (ev.key === 'Escape') closeDrawer(); return; }
    if (t && t.matches && t.matches('button') && (ev.key === 'Enter' || ev.key === ' ')) return;
    const key = KEYMAP[ev.key];
    if (!key) return;
    ev.preventDefault();
    if (ev.repeat) return;
    sendKey(key);
  }

  // ---- rendering --------------------------------------------------------------

  function prettyApp(pkg) {
    if (!pkg) return null;
    const known = app.apps.find((a) => a.id === pkg);
    if (known) return known.name;
    if (pkg === 'com.google.android.tvlauncher' || pkg === 'com.google.android.apps.tv.launcherx') return 'Home screen';
    return pkg;
  }

  function render(state) {
    if (!state) return;
    app.state = state;
    $('#tv-name').textContent = state.name || state.host || 'No TV configured';
    $('#status-dot').className = 'dot ' + (state.status || 'disconnected');
    $('#status-text').textContent = STATUS_LABELS[state.status] || state.status || '—';
    const power = state.is_on === true ? 'On' : state.is_on === false ? 'Standby' : '';
    $('#power-text').textContent = power ? '· ' + power : '';
    $('#current-app').textContent = state.current_app_name || prettyApp(state.current_app) || '—';
    const vol = state.volume;
    const fill = $('#vol-fill');
    if (vol) {
      const pct = vol.max ? Math.round((100 * vol.level) / vol.max) : 0;
      fill.style.width = pct + '%';
      fill.classList.toggle('muted', !!vol.muted);
      $('#vol-text').textContent = vol.muted ? 'Muted' : String(vol.level);
    } else {
      fill.style.width = '0%';
      $('#vol-text').textContent = '—';
    }
    $('#btn-mute').classList.toggle('active', !!(vol && vol.muted));
    document.body.classList.toggle('tv-off', state.is_on === false);
    renderBanner(state);

    const hostInput = $('#host-input');
    if (document.activeElement !== hostInput && !hostInput.dataset.dirty) hostInput.value = state.host || '';
    const dev = state.device;
    $('#device-info').textContent = [
      dev ? `${dev.manufacturer || ''} ${dev.model || ''}`.trim() : null,
      dev && dev.sw_version ? `Software ${dev.sw_version}` : null,
      `Address ${state.host || '-'}`,
      `MAC ${state.mac || 'unknown (learned during pairing)'}`,
    ].filter(Boolean).join('\n');
    $('#btn-wake').disabled = !state.mac;
    if (state.status === 'pairing') showPairBox(true);
    else if (state.status === 'connected') showPairBox(false);
  }

  function renderBanner(state) {
    let msg = null; let label = null; let handler = null;
    if (!state.host) { msg = 'No TV configured yet.'; label = 'Set up'; handler = () => { openDrawer(); discover(); }; }
    else if (state.status === 'needs_pairing') { msg = state.error || 'This TV needs to be paired.'; label = 'Pair now'; handler = () => startPairing(state.host); }
    else if (state.status === 'pairing') { msg = 'A code is showing on the TV.'; label = 'Enter code'; handler = () => { openDrawer(); showPairBox(true); $('#pair-code').focus(); }; }
    else if (state.status === 'unreachable') { msg = state.error || 'The TV is unreachable.'; label = state.mac ? 'Wake on LAN' : 'Retry'; handler = state.mac ? wake : () => connectTo(state.host); }
    else if (state.status === 'reconnecting') { msg = 'Connection lost, reconnecting…'; }
    else if (state.status === 'connecting') { msg = 'Connecting to the TV…'; }
    else if (state.status === 'disconnected') { msg = 'Not connected.'; label = 'Connect'; handler = () => connectTo(state.host); }
    $('#banner').classList.toggle('hidden', !msg);
    $('#banner-text').textContent = msg || '';
    const action = $('#banner-action');
    action.classList.toggle('hidden', !label);
    action.textContent = label || '';
    action.onclick = handler;
  }

  function toast(message) {
    const el = $('#toast');
    el.textContent = message;
    el.classList.remove('hidden');
    clearTimeout(app.toastTimer);
    app.toastTimer = setTimeout(() => el.classList.add('hidden'), 2800);
  }

  // ---- settings drawer ----------------------------------------------------------

  function openDrawer() { $('#drawer').classList.remove('hidden'); $('#scrim').classList.remove('hidden'); }
  function closeDrawer() { $('#drawer').classList.add('hidden'); $('#scrim').classList.add('hidden'); }
  function showPairBox(show) { $('#pair-box').classList.toggle('hidden', !show); }
  function busy(sel, on) { const b = $(sel); b.disabled = on; }

  async function connectTo(host) {
    host = (host || $('#host-input').value || '').trim();
    if (!host) { toast('Enter the TV address first'); openDrawer(); return; }
    busy('#btn-connect', true);
    try {
      const d = await post('/api/connect', { host });
      render(d.state);
      if (d.state.status === 'needs_pairing') await startPairing(host);
      else { toast('Connected to ' + (d.state.name || host)); closeDrawer(); }
    } catch (err) { handleError(err); } finally { busy('#btn-connect', false); }
  }

  async function startPairing(host) {
    host = (host || $('#host-input').value || (app.state && app.state.host) || '').trim();
    if (!host) { toast('Enter the TV address first'); openDrawer(); return; }
    openDrawer();
    busy('#btn-pair', true);
    try {
      const d = await post('/api/pair/start', { host });
      render(d.state);
      showPairBox(true);
      $('#pair-code').value = '';
      $('#pair-code').focus();
      toast('Look at the TV for the pairing code');
    } catch (err) { handleError(err); } finally { busy('#btn-pair', false); }
  }

  async function finishPairing(code) {
    code = (code || '').trim();
    if (code.length !== 6) { toast('The code has 6 characters'); return; }
    try {
      const d = await post('/api/pair/finish', { code });
      render(d.state);
      showPairBox(false);
      toast('Paired. You can control the TV now.');
      closeDrawer();
    } catch (err) { handleError(err); }
  }

  async function discover() {
    const list = $('#found-list');
    list.innerHTML = '<li class="muted">Searching the network for 4 seconds…</li>';
    busy('#btn-discover', true);
    try {
      const d = await api('/api/discover?timeout=4');
      list.innerHTML = '';
      if (!d.tvs.length) {
        list.innerHTML = '<li class="muted">No TVs found. Check the TV is on and on the same Wi-Fi, or type its IP address (Settings › Network &amp; Internet on the TV).</li>';
        return;
      }
      d.tvs.forEach((tv) => {
        const li = document.createElement('li');
        const b = document.createElement('button');
        b.className = 'found-item';
        const strong = document.createElement('strong');
        strong.textContent = tv.name + (tv.model ? ' · ' + tv.model : '');
        const span = document.createElement('span');
        span.textContent = tv.host + (tv.remote_service ? '' : ' · remote service not advertised');
        b.append(strong, span);
        b.onclick = () => { $('#host-input').value = tv.host; connectTo(tv.host); };
        li.appendChild(b);
        list.appendChild(li);
      });
    } catch (err) { list.innerHTML = ''; handleError(err); } finally { busy('#btn-discover', false); }
  }

  async function loadApps() {
    try {
      const d = await api('/api/apps');
      app.apps = d.apps;
      const box = $('#apps');
      box.innerHTML = '';
      d.apps.slice(0, 8).forEach((a) => {
        const b = document.createElement('button');
        b.className = 'app-chip';
        b.style.setProperty('--app', a.color);
        b.appendChild(document.createElement('i'));
        b.append(a.name);
        b.onclick = () => launchApp(a.id, a.name);
        box.appendChild(b);
      });
      const rest = d.apps.slice(8);
      if (rest.length) {
        const sel = document.createElement('select');
        sel.className = 'app-more';
        sel.setAttribute('aria-label', 'More apps');
        const first = document.createElement('option');
        first.value = ''; first.textContent = 'More…';
        sel.appendChild(first);
        rest.forEach((a) => { const o = document.createElement('option'); o.value = a.id; o.textContent = a.name; sel.appendChild(o); });
        sel.onchange = () => { if (sel.value) { const a = rest.find((x) => x.id === sel.value); launchApp(sel.value, a && a.name); sel.value = ''; } };
        box.appendChild(sel);
      }
      if (app.state) render(app.state);
    } catch (err) { if (err.code === 'unauthorized') handleError(err); }
  }

  // ---- phone / install helpers ---------------------------------------------------

  function isStandalone() {
    return (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) || navigator.standalone === true;
  }
  function isIOS() {
    return /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  }

  async function loadInfo() {
    try {
      const d = await api('/api/info');
      const img = $('#qr-img');
      if (d.phone_url && !isStandalone()) {
        img.src = '/api/qr.svg' + (app.token ? '?token=' + encodeURIComponent(app.token) : '');
        img.classList.remove('hidden');
        $('#phone-hint').classList.remove('hidden');
      } else {
        img.classList.add('hidden');
        $('#phone-hint').classList.add('hidden');
      }
    } catch (e) { /* the QR code is optional */ }
  }

  function setupInstall() {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').catch(() => { /* offline shell is optional */ });
    }
    window.addEventListener('beforeinstallprompt', (ev) => {
      ev.preventDefault();
      app.installPrompt = ev;
      $('#btn-install').classList.remove('hidden');
      $('#android-hint').classList.add('hidden');
    });
    window.addEventListener('appinstalled', () => {
      app.installPrompt = null;
      $('#btn-install').classList.add('hidden');
      toast('Installed. Open it from your home screen.');
    });
    $('#btn-install').addEventListener('click', async () => {
      if (!app.installPrompt) return;
      app.installPrompt.prompt();
      try { await app.installPrompt.userChoice; } catch (e) { /* ignore */ }
      app.installPrompt = null;
      $('#btn-install').classList.add('hidden');
    });
    if (!isStandalone()) {
      if (isIOS()) $('#ios-hint').classList.remove('hidden');
      else if (/Android/.test(navigator.userAgent)) $('#android-hint').classList.remove('hidden');
    }
  }

  // ---- wiring ------------------------------------------------------------------

  function init() {
    setupInstall();
    bindKeyButtons();
    document.addEventListener('keydown', onKeyboard);

    document.querySelectorAll('.tab').forEach((tab) => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t === tab));
        document.querySelectorAll('.panel').forEach((p) => p.classList.toggle('hidden', p.id !== tab.dataset.panel));
      });
    });

    $('#text-form').addEventListener('submit', (ev) => {
      ev.preventDefault();
      const input = $('#text-input');
      if (!input.value) return;
      sendText(input.value).then(() => { input.value = ''; });
    });

    $('#btn-settings').addEventListener('click', openDrawer);
    $('#btn-close-drawer').addEventListener('click', closeDrawer);
    $('#scrim').addEventListener('click', closeDrawer);
    $('#host-input').addEventListener('input', (ev) => { ev.target.dataset.dirty = '1'; });
    $('#btn-connect').addEventListener('click', () => connectTo());
    $('#btn-pair').addEventListener('click', () => startPairing());
    $('#btn-discover').addEventListener('click', discover);
    $('#btn-wake').addEventListener('click', wake);
    $('#pair-form').addEventListener('submit', (ev) => { ev.preventDefault(); finishPairing($('#pair-code').value); });
    $('#token-input').value = app.token;
    $('#btn-save-token').addEventListener('click', () => {
      app.token = $('#token-input').value.trim();
      try { localStorage.setItem(TOKEN_STORAGE, app.token); } catch (e) { /* ignore */ }
      toast(app.token ? 'Token saved' : 'Token cleared');
      connectWS();
      loadApps();
      loadInfo();
    });

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && !app.wsOpen) connectWS();
    });

    loadApps();
    loadInfo();
    connectWS();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
