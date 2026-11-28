/* ZIGMon Gateway web UI: one page, hash routes, no external resources.
 * Module pages are drawn generically from each module's settings schema (see README.md). */
'use strict';
(function () {
  // ---- tiny DOM helpers ------------------------------------------------------------------
  const $ = (s, el) => (el || document).querySelector(s);
  function h(tag, attrs, ...kids) {
    const m = tag.match(/^([a-z0-9]+)((?:[.#][\w-]+)*)$/i);
    const el = document.createElement(m ? m[1] : 'div');
    if (m && m[2]) m[2].replace(/([.#])([\w-]+)/g, (_, k, v) => { if (k === '.') el.classList.add(v); else el.id = v; });
    if (attrs && (typeof attrs !== 'object' || attrs instanceof Node || Array.isArray(attrs))) { kids.unshift(attrs); attrs = null; }
    for (const k in attrs || {}) {
      const v = attrs[k];
      if (v === undefined || v === null || v === false) continue;
      if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'class') el.className += ' ' + v;
      else if (k === 'style') el.setAttribute('style', v);
      else if (k === 'value') el.value = v;
      else if (k === 'checked' || k === 'disabled' || k === 'hidden') el[k] = !!v;
      else el.setAttribute(k, v === true ? '' : v);
    }
    add(el, kids);
    return el;
  }
  function add(el, kids) {
    for (const k of [].concat(kids).flat(Infinity)) {
      if (k === null || k === undefined || k === false) continue;
      el.appendChild(k instanceof Node ? k : document.createTextNode(String(k)));
    }
    return el;
  }
  // Icons: constant SVG paths (never user data).
  const P = {
    home: 'M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z',
    wifi: 'M2 8.5a15 15 0 0 1 20 0M5 12a10 10 0 0 1 14 0M8.5 15.5a5 5 0 0 1 7 0M12 19h.01',
    link: 'M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1',
    lock: 'M6 10h12a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1zM8 10V7a4 4 0 0 1 8 0v3M12 14v3',
    unlock: 'M6 10h12a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1zM8 10V7a4 4 0 0 1 7.7-1.5M12 14v3',
    open: 'M4 21h16M6 21V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v17M14 12h.01M10 3v18',
    refresh: 'M20 11a8 8 0 0 0-14.6-4.5L3 9M3 4v5h5M4 13a8 8 0 0 0 14.6 4.5L21 15M21 20v-5h-5',
    cog: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
    box: 'M21 8 12 3 3 8v8l9 5 9-5zM3 8l9 5 9-5M12 13v8',
    bolt: 'M13 2 4 14h7l-1 8 9-12h-7z',
    sensor: 'M12 3v10M8 7a5 5 0 1 0 8 0',
    switch: 'M7 7h10a5 5 0 0 1 0 10H7A5 5 0 0 1 7 7zM7 12h.01',
    check: 'M20 6 9 17l-5-5',
    x: 'M18 6 6 18M6 6l12 12',
    alert: 'M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',
    info: 'M12 16v-4M12 8h.01M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z',
    plus: 'M12 5v14M5 12h14',
    search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3',
    edit: 'M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z',
    trash: 'M3 6h18M8 6V4h8v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6',
    cloud: 'M17.5 19a4.5 4.5 0 1 0-1.4-8.8A6 6 0 0 0 4.5 12 3.5 3.5 0 0 0 6 19z',
    key: 'M15 7a4 4 0 1 1-3.9 4.9L3 20v-3h3v-3h3l1.2-1.2A4 4 0 0 1 15 7zM16 10h.01',
    power: 'M12 2v10M18.4 6.6a9 9 0 1 1-12.8 0',
    clock: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2',
    logout: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9',
    shield: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z',
    chip: 'M9 3v2M15 3v2M9 19v2M15 19v2M3 9h2M3 15h2M19 9h2M19 15h2M7 5h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM9 9h6v6H9z',
  };
  function icon(name) {
    const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', '1.8');
    s.setAttribute('stroke-linecap', 'round');
    s.setAttribute('stroke-linejoin', 'round');
    s.setAttribute('aria-hidden', 'true');
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', P[name] || P.box);
    s.appendChild(p);
    return s;
  }

  // ---- state and API -----------------------------------------------------------------------
  const S = { session: null, csrf: '', modules: [], poll: null, jobs: {}, pageToken: 0 };

  class ApiError extends Error {
    constructor(status, body) { super((body && body.error) || ('HTTP ' + status)); this.status = status; this.body = body; }
  }
  async function api(path, body, method) {
    const opts = { method: method || (body === undefined ? 'GET' : 'POST'), credentials: 'same-origin', cache: 'no-store', headers: {} };
    if (opts.method === 'POST') {
      opts.headers['Content-Type'] = 'application/json';
      opts.headers['X-Gw-Csrf'] = S.csrf || '1';
      opts.body = JSON.stringify(body || {});
    }
    let r;
    try { r = await fetch('/api' + path, opts); } catch (e) { throw new ApiError(0, { error: 'the gateway does not answer' }); }
    let j = null;
    try { j = await r.json(); } catch (e) { j = null; }
    if (r.status === 401 && path !== '/login' && path !== '/session') { S.csrf = ''; setTimeout(boot, 0); }
    if (!r.ok) throw new ApiError(r.status, j);
    return j || {};
  }

  let toastTimer = null;
  function toast(msg, kind) {
    const t = $('#toast');
    t.className = 'toast ' + (kind || '');
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, kind === 'crit' ? 6000 : 3200);
  }
  function fail(e) { toast(e && e.message ? e.message : String(e), 'crit'); }

  async function withBusy(btn, fn) {
    if (btn) { btn.classList.add('busy'); btn.disabled = true; }
    try { return await fn(); } catch (e) { fail(e); } finally { if (btn) { btn.classList.remove('busy'); btn.disabled = false; } }
  }

  function ago(ts) {
    if (!ts) return '';
    const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (s < 45) return 'just now';
    if (s < 3600) return Math.round(s / 60) + ' min ago';
    if (s < 86400) return Math.round(s / 3600) + ' h ago';
    return Math.round(s / 86400) + ' d ago';
  }
  function dur(s) {
    s = s | 0;
    const d = Math.floor(s / 86400), hh = Math.floor(s / 3600) % 24, mm = Math.floor(s / 60) % 60;
    return d ? d + 'd ' + hh + 'h' : hh ? hh + 'h ' + mm + 'm' : mm + 'm ' + (s % 60) + 's';
  }
  function bytes(n) { return n >= 1048576 ? (n / 1048576).toFixed(n >= 10485760 ? 0 : 1) + ' MB' : Math.round(n / 1024) + ' KB'; }
  function bars(rssi) {
    const l = !rssi ? 0 : rssi > -60 ? 4 : rssi > -70 ? 3 : rssi > -80 ? 2 : 1;
    return h('span.bars.l' + l, { title: rssi ? rssi + ' dBm' : 'no signal' }, h('i'), h('i'), h('i'), h('i'));
  }
  function badge(text, kind) { return h('span.badge.' + (kind || 'plain'), text); }
  function banner(kind, ic, ...kids) { return h('div.banner.' + kind, icon(ic), h('div', kids)); }
  function section(title, ...right) { return h('div.section', h('h3', title), h('div.grow'), right); }
  function kv(pairs) {
    const dl = h('dl.kv');
    for (const [k, v] of pairs) if (v !== undefined && v !== null && v !== '') add(dl, [h('dt', k), h('dd', v)]);
    return dl;
  }

  // ---- sheet (dialog) ------------------------------------------------------------------------
  function openSheet(build) {
    const sh = $('#sheet');
    sh.textContent = '';
    const panel = h('div.panel', { role: 'dialog', 'aria-modal': 'true' });
    sh.appendChild(panel);
    sh.hidden = false;
    const close = () => { sh.hidden = true; sh.textContent = ''; document.removeEventListener('keydown', esc); };
    const esc = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', esc);
    sh.onclick = (e) => { if (e.target === sh) close(); };
    build(panel, close);
    const f = panel.querySelector('input:not([type=hidden]):not([type=checkbox]), button.primary');
    if (f && window.innerWidth > 820) setTimeout(() => f.focus(), 50);
    return close;
  }
  function confirmSheet(title, text, okText, kind) {
    return new Promise((resolve) => {
      openSheet((p, close) => {
        add(p, [h('h2', title), h('p.lead', text),
          h('div.actions',
            h('button', { onclick: () => { close(); resolve(false); } }, 'Cancel'),
            h('button.' + (kind || 'primary'), { onclick: () => { close(); resolve(true); } }, okText))]);
      });
    });
  }

  // ---- forms ----------------------------------------------------------------------------------
  // FIELD: {key,label,type:text|number|bool|select|secret|password|slug,required,min,max,unit,pattern,help,placeholder,options}
  function fieldEl(f, value, mode) {
    const id = 'f_' + f.key + '_' + Math.random().toString(36).slice(2, 7);
    let input;
    if (f.type === 'bool') {
      input = h('input', { type: 'checkbox', id, checked: !!value });
      return h('label.field.switch', { for: id }, input, h('span', f.label), f.help && h('div.help', f.help));
    }
    if (f.type === 'select') {
      input = h('select', { id }, (f.options || []).map((o) => {
        const v = typeof o === 'object' ? o.value : o;
        const opt = h('option', { value: v }, typeof o === 'object' ? (o.label || v) : v);
        if (String(v) === String(value)) opt.selected = true;
        return opt;
      }));
    } else {
      const secret = f.type === 'secret' || f.type === 'password';
      const attrs = {
        id, name: f.key,
        type: f.type === 'number' ? 'number' : secret ? 'password' : 'text',
        autocomplete: secret ? (f.type === 'password' ? 'current-password' : 'off') : 'off',
        autocapitalize: 'off', spellcheck: 'false',
      };
      if (f.type === 'number') { attrs.inputmode = 'numeric'; if (f.min !== undefined) attrs.min = f.min; if (f.max !== undefined) attrs.max = f.max; }
      if (f.max && f.type !== 'number') attrs.maxlength = f.max;
      if (f.placeholder) attrs.placeholder = f.placeholder;
      if (secret && mode === 'edit') attrs.placeholder = 'unchanged' + (value ? ' (' + value + ')' : '');
      else if (!secret && value !== undefined && value !== null) attrs.value = value;
      input = h('input', attrs);
    }
    input.dataset.key = f.key;
    input.dataset.type = f.type;
    const label = h('span', f.label, f.unit ? ' (' + f.unit + ')' : '', f.required && mode !== 'edit' ? h('span.req', '*') : null);
    return h('label.field', { for: id }, label, input, f.help && h('div.help', f.help));
  }
  function readForm(root, fields, mode) {
    const out = {};
    for (const f of fields) {
      const el = root.querySelector('[data-key="' + f.key + '"]');
      if (!el) continue;
      el.classList.remove('bad');
      let v;
      if (f.type === 'bool') v = el.checked;
      else if (f.type === 'number') v = el.value === '' ? null : Number(el.value);
      else v = el.value.trim();
      const secret = f.type === 'secret' || f.type === 'password';
      if (f.type === 'password') v = el.value;  // passwords are taken as typed
      if (f.required && (v === '' || v === null) && !(secret && mode === 'edit')) { el.classList.add('bad'); el.focus(); throw new Error(f.label + ': required'); }
      if (f.pattern && v && !new RegExp(f.pattern).test(v)) { el.classList.add('bad'); el.focus(); throw new Error(f.label + ': not valid'); }
      if (f.type === 'number' && v !== null && ((f.min !== undefined && v < f.min) || (f.max !== undefined && v > f.max))) {
        el.classList.add('bad'); el.focus(); throw new Error(f.label + ': ' + f.min + ' to ' + f.max);
      }
      if (secret && mode === 'edit' && v === '') continue;  // keep the stored secret
      if (v !== null) out[f.key] = v;
    }
    return out;
  }

  // ---- shell ------------------------------------------------------------------------------------
  function setTitle(t, ...right) {
    $('#title').textContent = t;
    document.title = t + ' - ZIGMon Gateway';
    const tr = $('#topRight');
    tr.textContent = '';
    add(tr, right);
  }
  function navLink(hash, ic, text, dot) {
    const a = h('a', { href: '#' + hash }, icon(ic), h('span', text), dot ? h('span.dot.' + dot) : null);
    a.dataset.route = hash;
    return a;
  }
  function drawNav() {
    const nav = $('#nav');
    nav.textContent = '';
    add(nav, [navLink('/', 'home', 'Overview'), navLink('/wifi', 'wifi', 'Wi-Fi'), navLink('/zigmon', 'link', 'ZIGMon'),
      h('div.sep'),
      S.modules.map((m) => navLink('/m/' + m.id, m.icon || 'box', shortName(m.name), (m.overview || {}).level)),
      h('div.sep'), navLink('/system', 'cog', 'System')]);
    const foot = $('#sideFoot');
    foot.textContent = '';
    add(foot, [h('div', S.session ? S.session.name : ''), h('div', 'Firmware ' + (S.session ? S.session.fw : '')),
      h('button.small.ghost', { onclick: logout }, icon('logout'), 'Log out')]);
    markNav();
  }
  function shortName(n) { return String(n || '').replace(/ locks$/i, ''); }
  function markNav() {
    const r = route();
    for (const a of document.querySelectorAll('#nav a')) a.classList.toggle('on', a.dataset.route === r.path);
  }
  function route() {
    const p = (location.hash || '#/').slice(1) || '/';
    return { path: p, parts: p.split('/').filter(Boolean) };
  }
  function stopPoll() { if (S.poll) { clearInterval(S.poll); S.poll = null; } }
  function startPoll(fn, ms) {
    stopPoll();
    S.poll = setInterval(() => { if (!document.hidden && $('#sheet').hidden) fn(); }, ms || 2500);
  }

  async function logout() {
    try { await api('/logout', {}); } catch (e) { /* gone anyway */ }
    S.csrf = '';
    boot();
  }

  // ---- gate: first run and login -------------------------------------------------------------------
  function gate(build) {
    stopPoll();
    $('#app').hidden = true;
    let g = $('#gate');
    if (!g) { g = h('div.gate#gate'); document.body.appendChild(g); }
    g.textContent = '';
    const card = h('div.card');
    g.appendChild(card);
    build(card);
  }
  function strength(pw) {
    let s = 0;
    if (pw.length >= 8) s++;
    if (pw.length >= 12) s++;
    if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) s++;
    if (/\d/.test(pw)) s++;
    if (/[^A-Za-z0-9]/.test(pw)) s++;
    return Math.min(4, s);
  }
  function setupView() {
    gate((c) => {
      const pw = h('input', { type: 'password', autocomplete: 'new-password', placeholder: 'At least 8 characters' });
      const pw2 = h('input', { type: 'password', autocomplete: 'new-password', placeholder: 'The same again' });
      const meter = h('i');
      pw.addEventListener('input', () => {
        const s = strength(pw.value);
        meter.style.width = (s * 25) + '%';
        meter.style.background = ['var(--crit)', 'var(--crit)', 'var(--warn)', 'var(--info)', 'var(--ok)'][s];
      });
      const btn = h('button.primary', { type: 'submit' }, 'Set the password');
      const form = h('form', h('label.field', h('span', 'Admin password'), pw), h('div.meter', meter),
        h('label.field', h('span', 'Repeat it'), pw2), btn);
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        if (pw.value.length < 8) return toast('At least 8 characters, please', 'crit');
        if (pw.value !== pw2.value) return toast('The two passwords differ', 'crit');
        withBusy(btn, async () => {
          const r = await api('/setup', { password: pw.value });
          S.csrf = r.csrf;
          pw.value = pw2.value = '';
          toast('Password set', 'ok');
          boot();
        });
      });
      add(c, [h('div.logo'), h('h1', 'Set the admin password'),
        h('p', 'This gateway is new. Choose the password that protects its web page. It is stored only as a PBKDF2 hash.'),
        form]);
    });
  }
  function closedView() {
    gate((c) => add(c, [h('div.logo'), h('h1', 'Set the admin password first'),
      h('p', 'No password is set, and the first-run page is closed (it is open for 10 minutes after a boot).'),
      banner('info', 'info', 'On the serial console (115200 baud) run ', h('code', 'password'), ' to set it, or ',
        h('code', 'webinit'), ' to open this page again for 10 minutes.'),
      h('div', { style: 'height:16px' }), h('button', { onclick: boot }, icon('refresh'), 'Try again')]));
  }
  function loginView(wait) {
    gate((c) => {
      const pw = h('input', { type: 'password', autocomplete: 'current-password', placeholder: 'Admin password' });
      const btn = h('button.primary', { type: 'submit' }, 'Log in');
      const note = h('div.help');
      let left = wait | 0;
      const tick = () => {
        btn.disabled = left > 0;
        note.textContent = left > 0 ? 'Too many attempts: try again in ' + left + ' s' : '';
        if (left > 0) { left--; setTimeout(tick, 1000); }
      };
      tick();
      const form = h('form', h('label.field', h('span', 'Password'), pw), btn, note);
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        withBusy(btn, async () => {
          try {
            const r = await api('/login', { password: pw.value });
            S.csrf = r.csrf;
            pw.value = '';
            boot();
          } catch (err) {
            pw.value = '';
            if (err.body && err.body.wait) { left = err.body.wait; setTimeout(tick, 0); }
            throw err;
          }
        });
      });
      add(c, [h('div.logo'), h('h1', S.session ? S.session.name : 'ZIGMon Gateway'), h('p', 'Log in to manage this gateway.'), form]);
      setTimeout(() => pw.focus(), 50);
    });
  }

  // ---- boot ---------------------------------------------------------------------------------------------
  async function boot() {
    let s;
    try { s = await api('/session'); } catch (e) {
      gate((c) => add(c, [h('div.logo'), h('h1', 'No answer'), h('p', e.message), h('button', { onclick: boot }, 'Retry')]));
      return;
    }
    S.session = s;
    if (!s.password_set) return s.setup_open ? setupView() : closedView();
    if (!s.logged_in) return loginView(s.lockout);
    S.csrf = s.csrf;
    const g = $('#gate');
    if (g) g.remove();
    $('#app').hidden = false;
    try { S.modules = (await api('/modules')).modules || []; } catch (e) { S.modules = []; }
    drawNav();
    render();
  }

  async function render() {
    stopPoll();
    markNav();
    const token = ++S.pageToken;
    const view = $('#view');
    const r = route();
    const page = h('div');
    try {
      if (r.path === '/') await overviewPage(page, token);
      else if (r.path === '/wifi') await wifiPage(page, token);
      else if (r.path === '/zigmon') await zigmonPage(page, token);
      else if (r.path === '/system') await systemPage(page, token);
      else if (r.parts[0] === 'm' && r.parts[1]) await modulePage(page, r.parts[1], token);
      else { location.hash = '#/'; return; }
    } catch (e) {
      if (e.status === 401) return;
      add(page, banner('crit', 'alert', e.message));
    }
    if (token !== S.pageToken) return;
    view.textContent = '';
    view.appendChild(page);
    view.style.animation = 'none';
    void view.offsetWidth;
    view.style.animation = '';
  }

  // ---- Overview -------------------------------------------------------------------------------------------
  async function overviewPage(page, token) {
    const o = await api('/overview');
    setTitle('Overview', badge(o.wifi.connected ? 'Online' : 'Offline', o.wifi.connected ? 'ok' : 'crit'));
    const g = o.gateway, w = o.wifi, z = o.zigmon;
    const cards = h('div.grid');
    add(cards, [
      h('div.card', h('h2', icon('chip'), g.name), kv([['Model', g.model.toUpperCase()], ['Firmware', g.fw], ['Up', dur(g.uptime)],
        ['Free heap', bytes(g.heap)], ['PSRAM', g.psram ? 'yes' : 'no'], ['ID', h('span.mono', g.id)]])),
      h('div.card.link', { onclick: () => { location.hash = '#/wifi'; } },
        h('h2', icon('wifi'), 'Wi-Fi', h('span.right', badge(w.connected ? 'Connected' : w.configured ? 'Connecting' : 'Not set', w.connected ? 'ok' : 'warn'))),
        w.connected ? h('div.row', h('div.big', w.ssid), h('div.spacer'), bars(w.rssi)) : h('div.dim', w.configured ? 'Joining "' + w.ssid + '"...' : 'Use the CLI: wifi set "<ssid>" <password>'),
        h('div', { style: 'height:10px' }),
        kv([['IP', w.ip && h('span.mono', w.ip)], ['Signal', w.connected ? w.rssi + ' dBm' : ''], ['Name', w.hostname + '.local'], ['Address', w.dhcp ? 'DHCP' : 'static']])),
      h('div.card.link', { onclick: () => { location.hash = '#/zigmon'; } },
        h('h2', icon('link'), 'ZIGMon', h('span.right', badge(z.paired ? 'Paired' : 'Not paired', z.paired ? 'ok' : 'warn'))),
        z.paired ? h('div', h('div.big', z.name || 'ZIGMon'), h('div.dim.small', 'controls this gateway')) :
          h('div', h('div.dim', 'Pair this gateway with ZIGMon to control its modules from your dashboard.'), h('div', { style: 'height:12px' }),
            h('button.primary', { onclick: (e) => { e.stopPropagation(); location.hash = '#/zigmon'; } }, icon('link'), 'Pair with ZIGMon'))),
      timeCard(o.time),
    ]);
    page.appendChild(cards);
    page.appendChild(section('Modules'));
    const mods = h('div.grid');
    for (const m of o.modules) {
      const ov = m.overview || {};
      add(mods, h('div.card.link', { onclick: () => { location.hash = '#/m/' + m.id; } },
        h('h2', icon(m.icon), m.name, h('span.right', badge(ov.level === 'ok' ? 'OK' : ov.level === 'crit' ? 'Attention' : ov.level === 'warn' ? 'Check' : 'Set up', ov.level || 'info'))),
        h('div', ov.text || ''), h('div.dim.small', 'version ' + m.version)));
    }
    if (!o.modules.length) mods.appendChild(h('div.empty', 'No modules in this firmware.'));
    page.appendChild(mods);
    if (o.jobs && o.jobs.length) {
      page.appendChild(section('Recent activity'));
      page.appendChild(jobList(o.jobs));
    }
    startPoll(() => { if (token === S.pageToken) render(); }, 10000);
  }
  function timeCard(t) {
    const c = h('div.card', h('h2', icon('clock'), 'Time', h('span.right', badge(t.set ? 'Set' : 'Not set', t.set ? 'ok' : 'warn'))));
    if (t.set) add(c, [h('div.big', new Date(t.now * 1000).toLocaleTimeString()), h('div.dim.small', new Date(t.now * 1000).toLocaleDateString() + ' (from NTP or ZIGMon)')]);
    else {
      const b = h('button', { onclick: () => withBusy(b, async () => { await api('/system/time', { unix: Math.floor(Date.now() / 1000) }); toast('Clock set', 'ok'); render(); }) }, icon('clock'), "Use this browser's time");
      add(c, [h('div.dim', 'Yeelock needs the time. NTP sets it when there is internet; ZIGMon sets it when it connects.'), h('div', { style: 'height:12px' }), b]);
    }
    return c;
  }
  function jobList(jobs) {
    const l = h('div.list');
    for (const j of jobs) {
      const state = j.status !== 'done' ? badge(j.status === 'running' ? 'Running' : 'Queued', 'info') : badge(j.ok ? 'OK' : 'Failed', j.ok ? 'ok' : 'crit');
      add(l, h('div.item', h('div', h('div.t', cap(j.action) + ' - ' + j.entity), h('div.s', j.msg || '')), h('div.spacer'), h('span.dim.small.hide-phone', ago(j.at)), state));
    }
    return l;
  }
  // "AB:CD:..." as four lines of eight bytes, so two screens are easy to compare.
  function fpLines(fp) { return String(fp || '').split(':').reduce((a, x, i) => a + (i ? (i % 8 ? ':' : '\n') : '') + x, ''); }
  function keyShort(k) { const m = /\(\.\.(\w+)\)/.exec(k || ''); return m ? '..' + m[1] : k; }
  function cap(s) { s = String(s || ''); return s.charAt(0).toUpperCase() + s.slice(1); }

  // ---- Wi-Fi ------------------------------------------------------------------------------------------------
  async function wifiPage(page) {
    const w = await api('/wifi');
    setTitle('Wi-Fi', badge(w.connected ? 'Connected' : 'Not connected', w.connected ? 'ok' : 'warn'));
    const ssid = h('input', { value: w.ssid || '', autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', maxlength: 32 });
    const pass = h('input', { type: 'password', autocomplete: 'new-password', placeholder: w.configured ? 'unchanged (' + w.password + ')' : 'Wi-Fi password', maxlength: 63 });
    const dhcp = h('input', { type: 'checkbox', checked: w.dhcp });
    const st = w.static || {};
    const ip = h('input', { value: st.ip !== '0.0.0.0' ? st.ip : '', placeholder: '192.168.1.50', inputmode: 'decimal' });
    const mask = h('input', { value: st.mask !== '0.0.0.0' ? st.mask : '255.255.255.0', inputmode: 'decimal' });
    const gw = h('input', { value: st.gw !== '0.0.0.0' ? st.gw : '', placeholder: '192.168.1.1', inputmode: 'decimal' });
    const dns = h('input', { value: st.dns !== '0.0.0.0' ? st.dns : '', placeholder: 'the gateway', inputmode: 'decimal' });
    const staticBox = h('div', h('div.inline', h('label.field', h('span', 'IP address'), ip), h('label.field', h('span', 'Mask'), mask)),
      h('div.inline', h('label.field', h('span', 'Gateway'), gw), h('label.field', h('span', 'DNS'), dns)));
    staticBox.hidden = w.dhcp;
    dhcp.addEventListener('change', () => { staticBox.hidden = dhcp.checked; });

    const nets = h('div.list');
    nets.hidden = true;
    const scanBtn = h('button', { onclick: () => scan() }, icon('search'), 'Scan');
    async function scan() {
      await withBusy(scanBtn, async () => {
        await api('/wifi/scan', {});
        for (let i = 0; i < 20; i++) {
          await new Promise((r) => setTimeout(r, 700));
          const r = await api('/wifi/scan');
          if (!r.running) { showNets(r.networks || []); return; }
        }
      });
    }
    function showNets(list) {
      nets.textContent = '';
      nets.hidden = false;
      if (!list.length) nets.appendChild(h('div.item', h('span.dim', 'No networks found')));
      for (const n of list) {
        add(nets, h('div.item.pick', { onclick: () => { ssid.value = n.ssid; pass.value = ''; pass.placeholder = n.secure ? 'Wi-Fi password' : 'open network'; pass.focus(); } },
          bars(n.rssi), h('div', h('div.t', n.ssid), h('div.s', (n.secure ? 'WPA' : 'Open') + ' - channel ' + n.ch + ' - ' + n.rssi + ' dBm')),
          h('div.spacer'), n.ssid === w.ssid ? badge('current', 'ok') : null));
      }
    }
    const save = h('button.primary', { type: 'submit' }, 'Save and connect');
    const form = h('form.card', h('h2', icon('wifi'), 'Network'),
      h('label.field', h('span', 'Network name (SSID)'), ssid), h('label.field', h('span', 'Password'), pass),
      h('label.field.switch', dhcp, h('span', 'Get the address automatically (DHCP)')), staticBox,
      h('div.row.end', save));
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const body = { ssid: ssid.value, password: pass.value, dhcp: dhcp.checked };
      if (!dhcp.checked) Object.assign(body, { ip: ip.value.trim(), mask: mask.value.trim(), gw: gw.value.trim(), dns: dns.value.trim() });
      withBusy(save, async () => {
        const ok = await confirmSheet('Change the Wi-Fi?', 'The gateway leaves its current network. If the new settings are wrong, fix them from the serial console.', 'Save and connect');
        if (!ok) return;
        await api('/wifi', body);
        pass.value = '';
        toast('Saved: the gateway reconnects now', 'ok');
      });
    });
    add(page, h('div.grid.two',
      h('div.card', h('h2', icon('wifi'), 'Now'), kv([['Network', w.ssid || 'not set'], ['Status', w.connected ? 'connected' : 'not connected'], ['IP', w.ip], ['Signal', w.connected ? w.rssi + ' dBm' : ''], ['Name', w.hostname + '.local'], ['Address', w.dhcp ? 'DHCP' : 'static']])),
      form));
    add(page, [section('Networks around', scanBtn), nets]);
  }

  // ---- ZIGMon -------------------------------------------------------------------------------------------------
  async function zigmonPage(page, token) {
    const z = await api('/zigmon');
    setTitle('ZIGMon', badge(z.paired ? 'Paired' : 'Not paired', z.paired ? 'ok' : 'warn'));
    const p = z.pairing || {};
    const fp = h('div.fp', fpLines(z.fingerprint_pretty));
    if (p.active) {
      const ring = h('i', { style: 'width:' + Math.round(p.expires_in / 6) + '%' });
      const left = h('span', '');
      let s = p.expires_in;
      const tick = () => {
        left.textContent = Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
        ring.style.width = Math.max(0, s / 6) + '%';
        if (s-- > 0 && token === S.pageToken) setTimeout(tick, 1000);
        else if (token === S.pageToken) render();
      };
      tick();
      add(page, h('div.grid.two',
        h('div.card', h('h2', icon('key'), 'Pairing code', h('span.right.dim.small', 'valid ', left)),
          h('div.code', p.code), h('div.ring', ring), h('div', { style: 'height:16px' }),
          h('ol.small', { style: 'padding-left:18px;margin:0;color:var(--dim)' },
            h('li', 'In ZIGMon: Settings > Devices > ESP32 gateways > Add.'),
            h('li', 'Enter the address ', h('b', z.ip || (z.hostname + '.local')), ' and this code.'),
            h('li', 'Check that ZIGMon shows the same fingerprint as below, then confirm.')),
          h('div', { style: 'height:14px' }),
          h('div.row.end', h('button', { onclick: (e) => withBusy(e.currentTarget, async () => { await api('/zigmon/cancel', {}); render(); }) }, 'Cancel'))),
        h('div.card', h('h2', icon('shield'), 'Certificate fingerprint (SHA-256)'), fp,
          h('div.help', 'The code is used once; a wrong one spends it. Five wrong codes lock pairing for 15 minutes.'))));
      return;
    }
    const pairBtn = h('button.primary', { onclick: () => withBusy(pairBtn, async () => { await api('/zigmon/pair', {}); render(); }) }, icon('link'), z.paired ? 'Pair again' : 'Pair with ZIGMon');
    const unpairBtn = h('button.danger', { onclick: async () => {
      if (!await confirmSheet('Forget ZIGMon?', 'ZIGMon loses control of this gateway until you pair again.', 'Forget', 'danger')) return;
      withBusy(unpairBtn, async () => { await api('/zigmon/unpair', {}); toast('ZIGMon forgotten', 'ok'); render(); });
    } }, 'Unpair');
    add(page, h('div.grid.two',
      h('div.card', h('h2', icon('link'), 'Pairing'),
        z.paired ? h('div', h('div.big', z.zigmon || 'ZIGMon'), h('div.dim', 'is paired and controls this gateway. Requests are signed with a key only the two of you know.'))
          : h('div.dim', 'ZIGMon finds the modules of this gateway and controls them. Pairing takes a 6-digit code from here.'),
        p.locked_for ? banner('warn', 'alert', 'Pairing is locked for ' + Math.ceil(p.locked_for / 60) + ' more minutes after 5 wrong codes.') : null,
        h('div', { style: 'height:16px' }), h('div.row', pairBtn, z.paired ? unpairBtn : null)),
      h('div.card', h('h2', icon('shield'), 'Certificate fingerprint (SHA-256)'), fp,
        h('div.help', 'This gateway made its own certificate. When your browser or ZIGMon asks, compare this fingerprint; the CLI command ', h('code', 'fingerprint'), ' shows it too.'))));
  }

  // ---- System ---------------------------------------------------------------------------------------------------
  async function systemPage(page, token) {
    const s = await api('/system');
    setTitle('System');
    const name = h('input', { value: s.name, maxlength: 40 });
    const host = h('input', { value: s.hostname, maxlength: 32, autocapitalize: 'off', spellcheck: 'false' });
    const saveNames = h('button', { type: 'submit' }, 'Save');
    const names = h('form.card', h('h2', icon('chip'), 'Names'), h('label.field', h('span', 'Name shown in ZIGMon'), name),
      h('label.field', h('span', 'Hostname (mDNS)'), host, h('div.help', host.value + '.local - a-z, 0-9 and -')), h('div.row.end', saveNames));
    names.addEventListener('submit', (e) => { e.preventDefault(); withBusy(saveNames, async () => { await api('/system/names', { name: name.value.trim(), hostname: host.value.trim().toLowerCase() }); toast('Saved', 'ok'); }); });

    const cur = h('input', { type: 'password', autocomplete: 'current-password' });
    const nw = h('input', { type: 'password', autocomplete: 'new-password', placeholder: '8+ characters' });
    const nw2 = h('input', { type: 'password', autocomplete: 'new-password' });
    const savePw = h('button', { type: 'submit' }, 'Change password');
    const pwForm = h('form.card', h('h2', icon('key'), 'Admin password'), h('label.field', h('span', 'Current password'), cur),
      h('div.inline', h('label.field', h('span', 'New password'), nw), h('label.field', h('span', 'Repeat'), nw2)), h('div.row.end', savePw));
    pwForm.addEventListener('submit', (e) => {
      e.preventDefault();
      if (nw.value !== nw2.value) return toast('The new passwords differ', 'crit');
      withBusy(savePw, async () => { const r = await api('/system/password', { current: cur.value, new: nw.value }); S.csrf = r.csrf; cur.value = nw.value = nw2.value = ''; toast('Password changed; other sessions were logged out', 'ok'); });
    });

    const lvl = h('select', ['error', 'warn', 'info', 'debug'].map((l) => { const o = h('option', { value: l }, l); if (l === s.log_level) o.selected = true; return o; }));
    lvl.addEventListener('change', () => api('/system/log', { level: lvl.value }).then(() => toast('Log level: ' + lvl.value, 'ok'), fail));
    const log = h('div.log');
    for (const line of s.log || []) {
      const m = line.match(/^\s*[\d.]+ ([EWID]) /);
      log.appendChild(h('div' + (m ? '.' + m[1] : ''), line));
    }
    const reboot = h('button', { onclick: async () => {
      if (!await confirmSheet('Reboot the gateway?', 'It is back in about 10 seconds. Running BLE jobs are dropped.', 'Reboot')) return;
      withBusy(reboot, async () => { await api('/system/reboot', {}); toast('Rebooting...', 'ok'); setTimeout(boot, 12000); });
    } }, icon('power'), 'Reboot');
    const reset = h('button.danger', { onclick: () => factoryReset() }, icon('trash'), 'Factory reset');

    add(page, h('div.grid.two',
      h('div.card', h('h2', icon('chip'), 'Gateway'), kv([['Firmware', s.fw], ['Model', s.model.toUpperCase() + ' rev ' + s.revision + ', ' + s.cores + ' core' + (s.cores > 1 ? 's' : '')],
        ['Flash', bytes(s.flash)], ['PSRAM', s.psram ? bytes(s.psram) : 'none'], ['Free heap', bytes(s.heap) + ' (min ' + bytes(s.heap_min) + ')'],
        ['Up', dur(s.uptime)], ['Clock', s.time_set ? new Date(s.now * 1000).toLocaleString() : 'not set'], ['ESP-IDF', s.sdk], ['ID', h('span.mono', s.id)]])),
      h('div.card', h('h2', icon('shield'), 'Certificate'), h('div.fp', fpLines(s.fingerprint_pretty)), h('div.help', 'SHA-256 of the HTTPS certificate this gateway made for itself.')),
      names, pwForm));
    add(page, [section('Log', lvl), log,
      section('Power and reset'), h('div.card', h('div.row', reboot, h('div.spacer'), reset),
        h('div.help', 'Factory reset erases Wi-Fi, the password, the ZIGMon pairing, every module\'s settings (locks and keys) and the certificate.'))]);
    setTimeout(() => { log.scrollTop = log.scrollHeight; }, 0);
  }
  function factoryReset() {
    openSheet((p, close) => {
      const typed = h('input', { placeholder: 'FACTORY RESET', autocapitalize: 'characters', spellcheck: 'false' });
      const pw = h('input', { type: 'password', autocomplete: 'current-password' });
      const go = h('button.danger', { disabled: true }, 'Erase everything');
      typed.addEventListener('input', () => { go.disabled = typed.value !== 'FACTORY RESET'; });
      go.addEventListener('click', () => withBusy(go, async () => {
        await api('/system/factory-reset', { confirm: typed.value, password: pw.value });
        close();
        toast('Erasing and rebooting...', 'ok');
      }));
      add(p, [h('h2', 'Factory reset'), h('p.lead', 'Everything on this gateway is erased and it restarts as new. This cannot be undone.'),
        h('label.field', h('span', 'Type FACTORY RESET'), typed), h('label.field', h('span', 'Admin password'), pw),
        h('div.actions', h('button', { onclick: close }, 'Cancel'), go)]);
    });
  }

  // ---- Module pages (generic) ---------------------------------------------------------------------------------------
  const ACT = {
    open: { icon: 'open', label: 'Open', verb: 'Opening' },
    unlock: { icon: 'unlock', label: 'Unlock', verb: 'Unlocking' },
    lock: { icon: 'lock', label: 'Lock', verb: 'Locking' },
    refresh: { icon: 'refresh', label: 'Refresh', verb: 'Refreshing' },
    on: { icon: 'power', label: 'On', verb: 'Switching on' },
    off: { icon: 'power', label: 'Off', verb: 'Switching off' },
    toggle: { icon: 'switch', label: 'Toggle', verb: 'Toggling' },
    press: { icon: 'bolt', label: 'Press', verb: 'Pressing' },
  };
  const PROBLEM = {
    wrong_key: 'Wrong sign key: the lock rejected it (TX_SIGN_INVALID). Edit the lock and paste its ble_sign_key again, or import it from your account.',
    not_found: 'Not found nearby: is the lock in range (5-10 m) and is the serial number right?',
    connect: 'Could not connect: out of range, or the Yeelock app on a phone holds the connection.',
    protocol: 'The lock answered unexpectedly. See the log on the System page.',
  };

  async function modulePage(page, id, token) {
    const d = await api('/m/' + encodeURIComponent(id));
    const m = d.module, sc = d.schema || {}, col = sc.collection;
    const mod = S.modules.find((x) => x.id === id) || {};
    const ov = mod.overview || {};
    setTitle(m.name, badge('v' + m.version, 'plain'));
    const ctx = { id, d, col, token, cards: h('div.grid') };

    if (col) {
      const addBtn = h('button.primary', { onclick: () => itemSheet(ctx, null, 'hand') }, icon('plus'), 'Add ' + (col.item || 'item'));
      const right = [addBtn];
      if (col.import) right.unshift(h('button.hide-phone', { onclick: () => itemSheet(ctx, null, 'import') }, icon('cloud'), 'Import'));
      add(page, section(col.title || 'Items', right));
      if (ov.text && d.items.length) add(page, h('div.dim.small', { style: 'margin:-4px 0 12px' }, ov.text));
      page.appendChild(ctx.cards);
      drawItems(ctx);
    } else {
      add(page, section('Entities'));
      page.appendChild(ctx.cards);
      drawEntities(ctx);
    }
    if (sc.settings && sc.settings.length) {
      add(page, section('Settings'));
      const form = h('form.card');
      const fg = h('div.form-grid');
      for (const f of sc.settings) fg.appendChild(fieldEl(f, d.settings[f.key], 'edit'));
      form.appendChild(fg);
      const save = h('button', { type: 'submit' }, 'Save settings');
      form.appendChild(h('div.row.end', save));
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        withBusy(save, async () => { await api('/m/' + id + '/settings', readForm(form, sc.settings, 'edit')); toast('Saved', 'ok'); });
      });
      page.appendChild(form);
    }
    startPoll(async () => {
      if (token !== S.pageToken) return;
      const st = await api('/state').catch(() => null);
      if (!st) return;
      for (const k in st.entities) if (k.startsWith(id + '.')) ctx.d.states[k] = st.entities[k];
      noteJobs(st.jobs || []);
      col ? drawItems(ctx) : drawEntities(ctx);
    }, 2000);
  }

  function drawEntities(ctx) {
    ctx.cards.textContent = '';
    if (!ctx.d.entities.length) ctx.cards.appendChild(h('div.empty', icon('box'), 'Nothing here yet.'));
    for (const e of ctx.d.entities) ctx.cards.appendChild(entityCard(ctx, e, null));
  }
  function drawItems(ctx) {
    const { d, col } = ctx;
    ctx.cards.textContent = '';
    if (!d.items.length) {
      ctx.cards.appendChild(h('div.empty', { style: 'grid-column:1/-1' }, icon(d.module.icon), h('div', { style: 'font-weight:600;color:var(--text);margin-bottom:4px' }, 'No ' + (col.item || 'item') + 's yet'),
        h('div', col.import ? 'Add one by hand, pick it from a BLE scan, or import your locks from your Yeelock account.' : 'Add the first one.'),
        h('div', { style: 'height:16px' }),
        h('div.row', { style: 'justify-content:center' }, h('button.primary', { onclick: () => itemSheet(ctx, null, 'hand') }, icon('plus'), 'Add ' + (col.item || 'item')),
          col.import ? h('button', { onclick: () => itemSheet(ctx, null, 'import') }, icon('cloud'), 'Import from account') : null)));
      return;
    }
    for (const it of d.items) {
      const e = d.entities.find((x) => x.id === it.entity) || { id: it.entity, name: it.name, type: 'unknown', actions: [], confirm: [] };
      ctx.cards.appendChild(entityCard(ctx, e, it));
    }
  }

  function entityCard(ctx, e, item) {
    const st = ctx.d.states[e.id] || {};
    const busy = !!st.busy;
    const isLock = e.type === 'lock';
    const value = st.value;
    const iconClass = busy ? 'busy' : st.available === false ? 'off' : value === 'locked' ? 'locked' : value === 'unlocked' ? 'unlocked' : '';
    const valueBadge = st.available === false ? badge('Unreachable', 'crit') : busy ? badge('Working', 'info')
      : value === 'locked' ? badge('Locked', 'ok') : value === 'unlocked' ? badge('Unlocked', 'warn') : badge(value === undefined || value === 'unknown' ? 'Unknown' : String(value), 'plain');
    const attrs = st.attrs || {};
    const meta = h('div.ent-meta');
    if (attrs.battery !== undefined && attrs.battery !== null) {
      const b = attrs.battery;
      add(meta, h('span', h('span.batt' + (b < 20 ? '.low' : b < 45 ? '.mid' : ''), h('i', { style: 'width:' + Math.max(2, Math.min(100, b)) * 0.2 + 'px' })), b + '%'));
    } else if (isLock) add(meta, h('span', h('span.batt'), 'battery ?'));
    if (attrs.rssi) add(meta, h('span', bars(attrs.rssi), attrs.rssi + ' dBm'));
    if (item && item.in_range) add(meta, h('span', badge('in range', 'ok')));
    for (const a of e.attrs || []) {
      if (a.key === 'battery' || a.key === 'rssi') continue;
      if (attrs[a.key] !== undefined) add(meta, h('span', a.label + ': ' + attrs[a.key] + (a.unit || '')));
    }

    const acts = h('div.acts');
    for (const a of e.actions || []) {
      const info = ACT[a] || { icon: 'bolt', label: cap(a), verb: cap(a) };
      const b = h('button' + (a === 'open' ? '.ok' : ''), { disabled: busy, title: info.label, onclick: () => runAction(ctx, e, a, b) }, icon(info.icon), info.label);
      acts.appendChild(b);
    }
    if (e.actions && e.actions.length && e.actions.length < 4) acts.style.gridTemplateColumns = 'repeat(' + e.actions.length + ',1fr)';

    const last = st.last;
    let lastEl = null;
    if (last) {
      lastEl = h('div.last.' + (last.ok ? 'ok' : 'bad'), h('span', { style: 'color:' + (last.ok ? 'var(--ok)' : 'var(--crit)') }, last.ok ? '✓' : '✕'),
        h('div', h('b', cap(last.action)), ' ', last.msg ? '- ' + last.msg : '', h('span.dim', last.at ? '  · ' + ago(last.at) : '')));
    }
    const problem = st.problem || (last && !last.ok && last.problem);
    const card = h('div.card.ent',
      h('div.ent-head', h('div.ent-icon.' + (iconClass || 'none'), icon(isLock ? (value === 'unlocked' ? 'unlock' : 'lock') : e.type === 'sensor' ? 'sensor' : e.type === 'switch' ? 'switch' : 'box')),
        h('div', { style: 'min-width:0' }, h('div.ent-name', e.name), h('div.ent-sub', item ? 'S/N ' + item.sn + ' · key ' + keyShort(item.key) : e.id)),
        h('div.spacer'), valueBadge),
      meta.childNodes.length ? meta : null,
      problem && PROBLEM[problem] ? banner(problem === 'wrong_key' ? 'crit' : 'warn', problem === 'wrong_key' ? 'key' : 'alert', PROBLEM[problem]) : null,
      e.actions && e.actions.length ? acts : null,
      lastEl,
      item ? h('div.ent-foot',
        ctx.col.check ? h('button.small.ghost', { disabled: busy, title: ctx.col.check.hint, onclick: (ev) => checkItem(ctx, item, ev.currentTarget) }, icon('check'), ctx.col.check.label || 'Check') : null,
        h('button.small.ghost', { onclick: () => itemSheet(ctx, item, 'hand') }, icon('edit'), 'Edit'),
        h('button.small.ghost', { onclick: () => deleteItem(ctx, item) }, icon('trash'), 'Delete')) : null);
    return card;
  }

  async function runAction(ctx, e, action, btn) {
    const info = ACT[action] || { label: cap(action), verb: cap(action) };
    if ((e.confirm || []).includes(action)) {
      const ok = await confirmSheet(info.label + ' ' + e.name + '?', action === 'open' ? 'The lock opens and locks itself again after a few seconds.' : 'The lock stays unlocked until you lock it.', info.label, 'primary');
      if (!ok) return;
    }
    await withBusy(btn, async () => {
      const r = await api('/command', { entity: e.id, action });
      S.jobs[r.job] = { label: info.label + ' ' + e.name };
      toast(info.verb + ' ' + e.name + '...');
      (ctx.d.states[e.id] = ctx.d.states[e.id] || {}).busy = true;
      drawItemsOrEntities(ctx);
    });
  }
  function drawItemsOrEntities(ctx) { ctx.col ? drawItems(ctx) : drawEntities(ctx); }
  function noteJobs(jobs) {
    for (const j of jobs) {
      const w = S.jobs[j.id];
      if (!w || j.status !== 'done') continue;
      delete S.jobs[j.id];
      toast(w.label + ': ' + (j.ok ? 'done' : 'failed') + (j.msg ? ' - ' + j.msg : ''), j.ok ? 'ok' : 'crit');
    }
  }
  async function checkItem(ctx, item, btn) {
    await withBusy(btn, async () => {
      const r = await api('/m/' + ctx.id + '/x/' + ctx.col.check.call, { id: item.id });
      S.jobs[r.job] = { label: 'Check ' + item.name };
      toast('Checking ' + item.name + '...');
    });
  }
  async function deleteItem(ctx, item) {
    if (!await confirmSheet('Delete ' + item.name + '?', 'Its settings and sign key are erased from the gateway. ZIGMon loses this entity.', 'Delete', 'danger')) return;
    try { await api('/m/' + ctx.id + '/items/' + encodeURIComponent(item.id) + '/delete', {}); toast('Deleted', 'ok'); render(); } catch (e) { fail(e); }
  }

  // Add / edit sheet: by hand, from a scan, or imported from the cloud.
  function itemSheet(ctx, item, tab) {
    const col = ctx.col, id = ctx.id;
    const editing = !!item;
    openSheet((p, close) => {
      const tabs = [['hand', editing ? 'Details' : 'By hand']];
      if (!editing && col.discover) tabs.push(['scan', 'Scan']);
      if (!editing && col.import) tabs.push(['import', 'Account']);
      const tabBar = h('div.tabs');
      const body = h('div');
      const show = (t) => {
        for (const b of tabBar.children) b.classList.toggle('on', b.dataset.t === t);
        body.textContent = '';
        if (t === 'hand') handTab(body, prefill);
        else if (t === 'scan') scanTab(body);
        else importTab(body);
      };
      let prefill = item ? Object.assign({}, item) : {};
      for (const [t, label] of tabs) {
        const b = h('button', { type: 'button', onclick: () => show(t) }, label);
        b.dataset.t = t;
        tabBar.appendChild(b);
      }
      add(p, [h('h2', editing ? 'Edit ' + item.name : 'Add ' + (col.item || 'item')),
        h('p.lead', editing ? 'Leave the key empty to keep the stored one.' : 'A new ' + (col.item || 'item') + ' is checked right after it is saved (it never unlocks).'),
        tabs.length > 1 ? tabBar : null, body]);
      show(tab && tabs.find((x) => x[0] === tab) ? tab : 'hand');

      function handTab(el, pre) {
        const form = h('form');
        for (const f of col.fields) {
          if (editing && f.create_only) continue;
          form.appendChild(fieldEl(f, editing && f.type === 'secret' ? item[f.key] : pre[f.key], editing ? 'edit' : 'new'));
        }
        const save = h('button.primary', { type: 'submit' }, editing ? 'Save' : 'Add');
        add(form, h('div.actions', h('button', { type: 'button', onclick: close }, 'Cancel'), save));
        form.addEventListener('submit', (e) => {
          e.preventDefault();
          let data;
          try { data = readForm(form, col.fields.filter((f) => !(editing && f.create_only)), editing ? 'edit' : 'new'); } catch (err) { return toast(err.message, 'crit'); }
          withBusy(save, async () => {
            await api('/m/' + id + '/items' + (editing ? '/' + encodeURIComponent(item.id) : ''), data);
            close();
            toast(editing ? 'Saved; checking the lock...' : 'Added; checking the lock...', 'ok');
            render();
          });
        });
        el.appendChild(form);
      }

      function scanTab(el) {
        const list = h('div.list');
        list.hidden = true;
        const hint = h('div.help', col.discover.hint || '');
        const btn = h('button.primary', { type: 'button', onclick: () => run() }, icon('search'), col.discover.label || 'Scan');
        add(el, [hint, h('div', { style: 'height:12px' }), btn, h('div', { style: 'height:14px' }), list]);
        async function run() {
          await withBusy(btn, async () => {
            let r = await api('/m/' + id + '/discover', {});
            for (let i = 0; i < 40 && r.running; i++) {
              await new Promise((res) => setTimeout(res, 800));
              r = await api('/m/' + id + '/discover');
            }
            draw(r.results || []);
          });
        }
        function draw(res) {
          list.textContent = '';
          list.hidden = false;
          if (!res.length) list.appendChild(h('div.item', h('span.dim', 'Nothing found. Wake the lock (touch it) and scan again.')));
          for (const x of res) {
            add(list, h('div.item' + (x.known ? '' : '.pick'), { onclick: x.known ? null : () => { prefill = { sn: x.sn, name: x.in_account || '' }; show('hand'); } },
              bars(x.rssi), h('div', h('div.t', x.label), h('div.s', x.detail + (x.in_account ? ' · "' + x.in_account + '" in your account' : ''))),
              h('div.spacer'), x.known ? badge('added: ' + x.known_as, 'ok') : badge('Add', 'info')));
          }
        }
        if (ctx.d.discover && ctx.d.discover.results && ctx.d.discover.results.length) draw(ctx.d.discover.results);
      }

      function importTab(el) {
        const im = col.import;
        const form = h('form');
        for (const f of im.fields) form.appendChild(fieldEl(f, '', 'new'));
        const go = h('button.primary', { type: 'submit' }, icon('cloud'), 'Fetch my locks');
        add(form, [h('div.help', { style: 'margin:-4px 0 14px' }, im.help), h('div.actions', h('button', { type: 'button', onclick: close }, 'Cancel'), go)]);
        el.appendChild(form);
        form.addEventListener('submit', (e) => {
          e.preventDefault();
          let data;
          try { data = readForm(form, im.fields, 'new'); } catch (err) { return toast(err.message, 'crit'); }
          withBusy(go, async () => {
            let r;
            try { r = await api('/m/' + id + '/x/' + im.call, data); } finally {
              for (const inp of form.querySelectorAll('input[type=password]')) inp.value = '';  // never kept
            }
            for (let i = 0; i < 40 && r.running; i++) {
              await new Promise((res) => setTimeout(res, 800));
              r = await api('/m/' + id + '/x/' + im.call);
            }
            if (r.error) throw new Error(r.error);
            pick(el, r.results || []);
          });
        });
      }
      function pick(el, res) {
        el.textContent = '';
        if (!res.length) { el.appendChild(banner('warn', 'info', 'The account has no locks.')); return; }
        const list = h('div.list');
        const boxes = [];
        for (const x of res) {
          const cb = h('input', { type: 'checkbox', checked: x.has_key && !x.known, disabled: !x.has_key });
          cb.dataset.sn = x.sn;
          boxes.push(cb);
          add(list, h('label.item.pick', cb, h('div', h('div.t', x.name), h('div.s', 'S/N ' + x.sn + ' · key ' + keyShort(x.key))), h('div.spacer'),
            h('div.row', { style: 'gap:6px;justify-content:flex-end' },
              x.in_range ? badge('in range', 'ok') : badge('not in range', 'plain'), x.known ? badge('added', 'info') : null)));
        }
        const go = h('button.primary', { type: 'button' }, 'Add selected');
        go.addEventListener('click', () => withBusy(go, async () => {
          const sns = boxes.filter((b) => b.checked).map((b) => b.dataset.sn);
          if (!sns.length) throw new Error('Choose at least one lock');
          const r = await api('/m/' + id + '/x/cloud_import', { sns });
          close();
          toast(r.added + ' lock' + (r.added === 1 ? '' : 's') + ' added; checking them now' + (r.warning ? ' (' + r.warning + ')' : ''), r.warning ? 'crit' : 'ok');
          render();
        }));
        add(el, [h('div.help', { style: 'margin-bottom:12px' }, 'Tick the locks to add. Their sign keys stay in the gateway\'s memory for 10 minutes at most; only the ones you add are saved.'),
          list, h('div.actions', h('button', { type: 'button', onclick: () => { api('/m/' + id + '/x/cloud_clear', {}).catch(() => {}); close(); } }, 'Cancel'), go)]);
      }
    });
  }

  window.addEventListener('hashchange', () => { if (!$('#app').hidden) render(); });
  boot();
})();
