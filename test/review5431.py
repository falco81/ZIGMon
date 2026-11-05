#!/usr/bin/env python3
"""5.43.1: the header on an iPad, the keyboard over the PIN, and a user button.
Fails on 5.43.0.

    python3 test/review5431.py      (SHOTS=dir also keeps the screenshots,
                                     before - 5.43.0's page - and after)

  * the header with the performance meter on and a PIN account unlocked, on
    an iPad (1366x1024, 1194x834, 1180x820, both ways round), on a desk at
    every width from 700 to 1600 and on a phone (420): Live and the clock on
    the title row, never on a row of their own under the chips; no chip over
    anything else; nothing wider than the screen;
  * the keyboard on the screen (a visualViewport that shrinks to 55 %): the
    dialogue asking for the PIN, and a popup with a box to type in, stay
    above it - the four boxes and Unlock (or the popup's buttons) inside
    what the keyboard leaves - and go back where they were once it is down;
  * a user button in the header for whoever is signed in or unlocked - a
    password account and a PIN account: it opens the account's popup with
    its passkeys (and the looks of the meter, while it is on), and a PIN
    account adds a passkey from there (a virtual authenticator).

Ports 19580 (the daemon), 19581 (php -S, this page), 19582 (php -S, 5.43.0's).
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review5431-check-'))
API_PORT, PHP_PORT, OLD_PORT = 19580, 19581, 19582
SHOTS = os.environ.get('SHOTS') or ''
# REVIEW5431_PAGE=old: the checks made on 5.43.0's page - every one must fail
AGAINST_OLD = os.environ.get('REVIEW5431_PAGE') == 'old'
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def finish():
    for p in PROCS:
        try:
            p.terminate()
            p.wait(5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    shutil.rmtree(str(W), ignore_errors=True)
    print('review5431: %s' % ('%d failed' % len(bad) if bad else 'all good'))
    os._exit(1 if bad else 0)


__import__('atexit').register(lambda: [p.kill() for p in PROCS if p.poll() is None])

sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [],
                      'mqtt_host': '', 'log_file': str(W / 'zigmon.log'), 'log_to_journal': False,
                      'state_dir': str(W / 'state'), 'login_tries': 50, 'login_wait_min': 1,
                      'session_idle_min': 240, 'session_hours': 720, 'public_view': True,
                      'passkeys': True, 'perf_meter': 1})
(W / 'state').mkdir()
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)
d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
d.account_add('pin', 'admin', '4826', kind='pin', quiet=True)

# ---- the page, this one and 5.43.0's, both relaying to the daemon above -------------------
NOW, OLD = W / 'web', W / 'old'
shutil.copytree(str(HERE / 'web'), str(NOW))
pack = HERE / 'release' / 'zigmon-5.43.0.tar.gz'
if not pack.exists():
    check(False, 'no release package of 5.43.0 to compare with')
    finish()
OLD.mkdir()
with tarfile.open(str(pack)) as tar:
    for name in ('index.php', 'zigmon-api.php', 'favicon.svg'):
        (OLD / name).write_bytes(tar.extractfile('zigmon-5.43.0/web/' + name).read())
for folder in (NOW, OLD):
    text = (folder / 'zigmon-api.php').read_text()
    text = text.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
    text = text.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
    (folder / 'zigmon-api.php').write_text(text)
(W / 'token').write_text(d.token)


def serve(folder, port):
    for _ in range(3):
        p = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % port, '-t', str(folder)], cwd=str(folder),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                             env=dict(os.environ, PHP_CLI_SERVER_WORKERS='6'))
        for _ in range(50):
            try:
                socket.create_connection(('127.0.0.1', port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        time.sleep(0.3)
        if p.poll() is None:
            PROCS.append(p)
            return p
        time.sleep(3)
    return None


if not shutil.which('php') or not serve(NOW, PHP_PORT) or not serve(OLD, OLD_PORT):
    check(False, 'php -S could not serve the page')
    finish()

PAGE_JS = r'''
const { chromium, devices } = require('playwright');
const cfg = JSON.parse(process.env.R_CFG);
const out = {layout: {}, kb: {}, user: {}, errors: []};
const wait = ms => new Promise(r => setTimeout(r, ms));
const IPAD = devices['iPad Pro 11'];
const PHONE = devices['iPhone 13'];
async function post(p, what, body) {
  return p.evaluate(async ([w, b]) => {
    const r = await fetch('?api=' + w, {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b)});
    let d = {}; try { d = await r.json(); } catch (e) {}
    return {status: r.status, body: d};
  }, [what, body]);
}
async function shot(p, name, clipHeader) {
  if (!cfg.shots) return;
  try {
    if (clipHeader) {
      const hb = await p.locator('header').boundingBox();
      await p.screenshot({path: cfg.shots + '/' + name, clip: {x: 0, y: 0, width: p.viewportSize().width,
        height: Math.ceil(hb.y + hb.height + 60)}});
    } else await p.screenshot({path: cfg.shots + '/' + name});
  } catch (e) {}
}
function ctxOpts(kind, w, h) {
  if (kind === 'ipad') return Object.assign({}, IPAD, {viewport: {width: w, height: h}, screen: {width: w, height: h}});
  if (kind === 'phone') return Object.assign({}, PHONE, {viewport: {width: w, height: h}, screen: {width: w, height: h}});
  return {viewport: {width: w, height: h}};
}
async function open(b, base, kind, w, h, as, init) {
  const ctx = await b.newContext(ctxOpts(kind, w, h));
  if (init) await ctx.addInitScript(init);
  const p = await ctx.newPage();
  p.setDefaultTimeout(15000);
  p.on('pageerror', e => out.errors.push(String(e).slice(0, 200)));
  await p.goto(base + '/');
  if (as === 'pin') await post(p, 'unlock', {pin: '4826', minutes: 60});
  if (as === 'owner') await post(p, 'login', {name: 'owner', password: 'owner pass 12'});
  if (as) { await p.reload(); }
  await wait(1200);
  return [ctx, p];
}
const meterUp = () => { const h = document.getElementById('hload');
  return !!h && !h.hidden && h.querySelectorAll('[data-k]').length > 0 && !!(window.HLOAD && HLOAD.last); };
// the meter drawn - a page that has not had its first reading in a while is loaded once more
async function waitMeter(p) {
  for (let i = 0; i < 2; i++) {
    if (await p.waitForFunction(meterUp, null, {timeout: 20000}).then(() => true, () => false)) return true;
    await p.reload(); await wait(1200);
  }
  return false;
}
// the header as drawn: the title row, Live and the clock, the chips, and what
// overlaps what
const measure = () => {
  const R = e => { const b = e.getBoundingClientRect(); return {x: b.left, y: b.top, r: b.right, b: b.bottom, w: b.width, h: b.height}; };
  const vis = e => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden' && R(e).w > 0;
  const hdr = document.querySelector('header');
  const title = ['header h1', '#pill', '#lockpill'].map(s => document.querySelector(s)).filter(vis).map(R);
  const row = {y: Math.min.apply(null, title.map(t => t.y)), b: Math.max.apply(null, title.map(t => t.b))};
  const upd = R(document.getElementById('updated'));
  const chips = Array.from(document.querySelectorAll('#hload [data-k]')).filter(vis);
  const others = Array.from(hdr.querySelectorAll(':scope > *, :scope > .hrow > *'))
    .filter(e => e.id !== 'hload' && e.id !== 'hrow' && vis(e) && !e.classList.contains('spacer'));
  const hit = (a, c) => a.x < c.r - 0.5 && c.x < a.r - 0.5 && a.y < c.b - 0.5 && c.y < a.b - 0.5;
  const overlaps = [];
  chips.forEach((c, i) => {
    const a = R(c);
    others.forEach(o => { if (hit(a, R(o))) overlaps.push(c.dataset.k + ' over ' + (o.id || o.tagName)); });
    chips.forEach((c2, j) => { if (j > i && hit(a, R(c2))) overlaps.push(c.dataset.k + ' over ' + c2.dataset.k); });
    if (a.r > R(hdr).r + 0.5) overlaps.push(c.dataset.k + ' out of the header');
  });
  const updEl = document.getElementById('updated');
  others.forEach(o => { if (o !== updEl && hit(upd, R(o))) overlaps.push('updated over ' + (o.id || o.tagName)); });
  const chipTop = chips.length ? Math.min.apply(null, chips.map(c => R(c).y)) : null;
  const ub = document.getElementById('userbtn');
  return {row: row, upd: {y: upd.y, b: upd.b}, onTitleRow: upd.y >= row.y - 4 && upd.y < row.b,
          underChips: chipTop !== null && upd.y >= Math.min.apply(null, chips.map(c => R(c).b)) - 1,
          chips: chips.map(c => c.dataset.k), overlaps: overlaps,
          scrollW: document.documentElement.scrollWidth, w: innerWidth,
          header: R(hdr), user: vis(ub) ? R(ub) : null, meter: !!(window.HLOAD && HLOAD.last)};
};
(async () => {
  const b = await chromium.launch();
  try {
    const base = cfg.now;
    // ---- (1) the header: iPads, the desk, a phone; the meter on, a PIN account unlocked ----
    const sizes = [['ipad', 1366, 1024], ['ipad', 1024, 1366], ['ipad', 1194, 834], ['ipad', 834, 1194],
                   ['ipad', 1180, 820], ['ipad', 820, 1180], ['phone', 420, 900]];
    for (let w = 700; w <= 1600; w += 50) sizes.push(['desk', w, 1000]);
    sizes.push(['desk', 1000, 1000], ['desk', 1280, 1000], ['desk', 1336, 1000]);
    for (const as of ['pin', 'owner']) {
      const [ctx, p] = await open(b, base, 'desk', 1600, 1000, as);
      await waitMeter(p);
      for (const [kind, w, h] of sizes) {
        if (as === 'owner' && kind !== 'desk' && kind !== 'phone' && w !== 1194) continue;
        let pg = p, c2 = null;
        if (kind !== 'desk') {
          [c2, pg] = await open(b, base, kind, w, h, as);
          await waitMeter(pg);
          await wait(400);
        } else { await p.setViewportSize({width: w, height: h}); await wait(250); }
        out.layout[as + ' ' + kind + ' ' + w + 'x' + h] = await pg.evaluate(measure);
        if (c2) await c2.close();
      }
      await ctx.close();
    }
    // the screenshots, before (5.43.0) and after
    for (const [which, url] of [['before', cfg.old], ['after', cfg.now]]) {
      for (const [kind, w, h, name] of [['ipad', 1366, 1024, 'ipad-1366-landscape'], ['ipad', 1024, 1366, 'ipad-1366-portrait'],
                                        ['ipad', 1194, 834, 'ipad-1194-landscape'], ['ipad', 834, 1194, 'ipad-1194-portrait'],
                                        ['ipad', 1180, 820, 'ipad-1180-landscape'],
                                        ['desk', 1600, 1000, 'desktop-1600'], ['phone', 420, 900, 'phone-420']]) {
        const [ctx, p] = await open(b, url, kind, w, h, 'pin');
        await waitMeter(p);
        await wait(3500);
        await shot(p, name + '-pin-' + which + '.png', true);
        if (name === 'desktop-1600' || name === 'ipad-1194-landscape') {
          const [c3, p3] = await open(b, url, kind, w, h, 'owner');
          await waitMeter(p3);
          await wait(3500);
          await shot(p3, name + '-password-' + which + '.png', true);
          await c3.close();
        }
        await ctx.close();
      }
    }
    // ---- (2) the keyboard on the screen ----
    const fakeVV = () => {
      const t = new EventTarget(); let h = window.innerHeight || 834; let top = 0;
      Object.defineProperty(t, 'height', {get: () => h}); Object.defineProperty(t, 'offsetTop', {get: () => top});
      t.offsetLeft = 0; t.scale = 1; t.pageTop = 0;
      Object.defineProperty(t, 'width', {get: () => window.innerWidth});
      window.__vv = (v, o) => { h = v; top = o || 0; t.dispatchEvent(new Event('resize')); };
      Object.defineProperty(window, 'visualViewport', {value: t, configurable: true});
    };
    // inside what the keyboard leaves, and what is there at its middle is it (not clipped away)
    const inside = (sels) => {
      const vv = window.visualViewport, top = vv.offsetTop, bot = vv.offsetTop + vv.height;
      return sels.map(s => {
        const e = document.querySelector(s); if (!e) return {s: s, ok: false, why: 'missing'};
        const r = e.getBoundingClientRect();
        const at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        const ok = r.height > 0 && r.top >= top - 0.5 && r.bottom <= bot + 0.5 && !!at && (at === e || e.contains(at));
        return {s: s, ok: ok, top: Math.round(r.top), bottom: Math.round(r.bottom), vvBottom: Math.round(bot)};
      });
    };
    for (const [w, h] of [[1366, 1024], [1180, 820], [1194, 834], [820, 1180]]) {
      for (const [which, url] of [['before', cfg.old], ['after', cfg.now]]) {
        if (which === 'before' && !(w === 1180 && cfg.shots)) continue;
        const [ctx, p] = await open(b, url, 'ipad', w, h, null, fakeVV);
        const res = {};
        await p.click('#lockpill');
        await p.waitForSelector('#pinback:not([hidden]) #pindigits:not([hidden]) input', {timeout: 8000});
        await wait(400);
        const sels = ['#pindigits input:nth-child(1)', '#pindigits input:nth-child(4)', '#pinok', '#pincancel'];
        res.boxBefore = await p.evaluate(() => { const r = document.querySelector('#pinback .pinbox').getBoundingClientRect(); return [Math.round(r.top), Math.round(r.height)]; });
        await p.focus('#pindigits input');
        await p.evaluate(v => window.__vv(v), Math.round(h * 0.55));
        await wait(500);
        res.up = await p.evaluate(inside, sels);
        if (w === 1180) await shot(p, 'ipad-1180-keyboard-pin-' + which + '.png');
        // Safari scrolled what is seen down the page a little
        await p.evaluate(v => window.__vv(v, 120), Math.round(h * 0.55));
        await wait(300);
        res.scrolled = await p.evaluate(inside, sels);
        await p.evaluate(() => window.__vv(window.innerHeight, 0));
        await p.evaluate(() => document.activeElement && document.activeElement.blur());
        await wait(500);
        res.down = await p.evaluate(() => { const r = document.querySelector('#pinback .pinbox').getBoundingClientRect();
          const bk = document.getElementById('pinback');
          return {box: [Math.round(r.top), Math.round(r.height)], top: bk.style.top, height: bk.style.height}; });
        // the name and the password, in the same dialogue
        if (await p.$('#pin-other:not([hidden]) a')) {
          await p.click('#pin-other-link').catch(() => {});
          await wait(300);
          await p.focus('#signin-pass').catch(() => {});
          await p.evaluate(v => window.__vv(v), Math.round(h * 0.55));
          await wait(400);
          res.pass = await p.evaluate(inside, ['#signin-name', '#signin-pass', '#pinok']);
        }
        await p.evaluate(() => window.__vv(window.innerHeight));
        await p.evaluate(() => document.activeElement && document.activeElement.blur());
        await wait(500);
        res.pdown = await p.evaluate(() => { const bk = document.getElementById('pinback'); return {top: bk.style.top, height: bk.style.height}; });
        await p.click('#pincancel').catch(() => {});
        await wait(300);
        // a popup with a box to type in: a password account changes its password
        if (which === 'after' || cfg.old === url) {
          await post(p, 'login', {name: 'owner', password: 'owner pass 12'});
          await p.reload(); await wait(1500);
          await p.evaluate(() => passwordChange(false));
          await wait(400);
          await p.focus('#zmodal-body input');
          await p.evaluate(v => window.__vv(v), Math.round(h * 0.55));
          await wait(500);
          res.zmodal = await p.evaluate(inside, ['#zmodal-body input', '#zmodal-foot .btn.primary']);
          if (w === 1180) await shot(p, 'ipad-1180-keyboard-popup-' + which + '.png');
          await p.evaluate(() => window.__vv(window.innerHeight));
          await p.evaluate(() => document.activeElement && document.activeElement.blur());
          await wait(500);
          res.zdown = await p.evaluate(() => { const m = document.getElementById('zmodal'); return {top: m.style.top, height: m.style.height}; });
        }
        out.kb[which + ' ' + w + 'x' + h] = res;
        await ctx.close();
      }
    }
    // the desk: nothing of this
    {
      const [ctx, p] = await open(b, base, 'desk', 1600, 1000, null, fakeVV);
      await p.click('#lockpill');
      await p.waitForSelector('#pinback:not([hidden]) #pindigits input', {timeout: 8000});
      await p.focus('#pindigits input');
      await p.evaluate(() => window.__vv(500));
      await wait(400);
      out.kb.desk = await p.evaluate(() => { const bk = document.getElementById('pinback');
        return {top: bk.style.top, height: bk.style.height, cls: document.documentElement.className}; });
      await ctx.close();
    }
    // ---- (3) the user button ----
    for (const as of ['pin', 'owner']) {
      for (const [kind, w, h] of [['desk', 1600, 1000], ['ipad', 1194, 834], ['phone', 420, 900]]) {
        const [ctx, p] = await open(b, base, kind, w, h, as);
        await waitMeter(p);
        const r = {};
        r.shown = await p.evaluate(() => { const u = document.getElementById('userbtn');
          return !!u && u.getClientRects().length > 0 ? {text: u.textContent.trim(), svg: !!u.querySelector('svg')} : null; });
        if (r.shown) {
          await p.click('#userbtn');
          await p.waitForSelector('#zmodal:not([hidden])', {timeout: 8000}).catch(() => {});
          await p.waitForSelector('#zmodal-body .pk-list[data-n]', {timeout: 10000}).catch(() => {});
          await wait(500);
          r.popup = await p.evaluate(() => ({open: !document.getElementById('zmodal').hidden,
            title: document.getElementById('zmodal-title').textContent,
            body: document.getElementById('zmodal-body').textContent.slice(0, 400),
            pk: !!document.querySelector('#zmodal-body .pk-list'), add: !!document.getElementById('pk-add'),
            pickers: !!document.querySelector('#zmodal-body #hl-pickers'),
            buttons: Array.from(document.querySelectorAll('#zmodal-foot .btn')).map(x => x.textContent.trim())}));
          if (kind !== 'phone' || as === 'pin') await shot(p, 'user-popup-' + as + '-' + kind + '-' + w + '.png');
          if (as === 'pin' && kind === 'desk') {
            const cdp = await ctx.newCDPSession(p);
            await cdp.send('WebAuthn.enable');
            await cdp.send('WebAuthn.addVirtualAuthenticator', {options: {protocol: 'ctap2', transport: 'internal',
              hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true}});
            const n = await p.evaluate(() => Number((document.querySelector('#zmodal-body .pk-list') || {dataset: {}}).dataset.n || 0));
            await p.click('#pk-add');
            await p.waitForFunction(n => Number((document.querySelector('#zmodal-body .pk-list') || {dataset: {}}).dataset.n || 0) > n, n, {timeout: 15000}).catch(() => {});
            r.added = await p.evaluate(() => ({n: Number((document.querySelector('#zmodal-body .pk-list') || {dataset: {}}).dataset.n || 0),
              rows: (document.querySelector('#zmodal-body .pk-list tbody') || {}).textContent || ''}));
            r.before = n;
            await shot(p, 'user-popup-pin-passkey-added.png');
          }
        }
        out.user[as + ' ' + kind + ' ' + w] = r;
        await ctx.close();
      }
    }
    // nobody signed in: no user button
    {
      const [ctx, p] = await open(b, base, 'desk', 1600, 1000, null);
      out.user.nobody = await p.evaluate(() => { const u = document.getElementById('userbtn'); return !!u && u.getClientRects().length > 0; });
      await ctx.close();
    }
  } catch (e) {
    out.error = String(e.stack || e).slice(0, 600);
  }
  console.log(JSON.stringify(out));
  await b.close();
})();
'''


def browser():
    node_path = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
    if not node_path or not (Path(node_path) / 'playwright').exists():
        check(False, 'no playwright here')
        return {}
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
    (W / 'page.js').write_text(PAGE_JS)
    now = 'http://localhost:%d' % (OLD_PORT if AGAINST_OLD else PHP_PORT)
    cfg = {'now': now, 'old': 'http://localhost:%d' % OLD_PORT, 'shots': '' if AGAINST_OLD else SHOTS}
    got = subprocess.run(['node', str(W / 'page.js')], capture_output=True, text=True, timeout=1200, cwd=str(W),
                         stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=node_path, R_CFG=json.dumps(cfg)))
    try:
        return json.loads((got.stdout.strip().splitlines() or ['{}'])[-1])
    except ValueError:
        return {'error': (got.stdout + got.stderr)[-800:]}


o = browser()
check(not o.get('error'), 'the page could not be driven: %s' % o.get('error'))
if os.environ.get('REVIEW5431_DUMP'):
    print(json.dumps(o, indent=1))

print('the header, with the meter on')
for k, m in sorted((o.get('layout') or {}).items()):
    check(m.get('meter') and m.get('chips'), '%s: the meter is not in the header' % k)
    # a phone: the title and the pills take a line each; Live stays above the chips' row, as it was
    phone = ' phone ' in k or int(k.split()[-1].split('x')[0]) <= 700
    check((m.get('onTitleRow') or phone) and not m.get('underChips'),
          '%s: Live and the clock are not on the title row (%r, the row %r)' % (k, m.get('upd'), m.get('row')))
    check(not m.get('overlaps'), '%s: a chip over something: %r' % (k, m.get('overlaps')))
    check(m.get('scrollW', 1) <= m.get('w', 0), '%s: wider than the screen (%s > %s)' % (k, m.get('scrollW'), m.get('w')))
    if phone:
        check(m.get('chips') == ['cpu', 'mem'], '%s: a phone has more than CPU and RAM: %r' % (k, m.get('chips')))
check(len(o.get('layout') or {}) >= 30, 'not every width was measured: %d' % len(o.get('layout') or {}))

print('the keyboard on the screen')
for k, r in sorted((o.get('kb') or {}).items()):
    if k == 'desk' or k.startswith('before'):
        continue
    for part in ('up', 'scrolled', 'pass', 'zmodal'):
        rows = r.get(part)
        check(rows and all(x.get('ok') for x in rows), '%s: %s - under the keyboard or out of sight: %r' % (k, part, rows))
    dn = r.get('down') or {}
    pd = r.get('pdown') or {}
    check(pd.get('top') == '' and pd.get('height') == '', '%s: the password dialogue does not go back: %r' % (k, pd))
    check(dn.get('top') == '' and dn.get('height') == '' and dn.get('box') == r.get('boxBefore'),
          '%s: the PIN dialogue does not go back once the keyboard is down: %r (before %r)' % (k, dn, r.get('boxBefore')))
    zd = r.get('zdown') or {}
    check(zd.get('top') == '' and zd.get('height') == '', '%s: the popup does not go back: %r' % (k, zd))
check(len([k for k in (o.get('kb') or {}) if k.startswith('after')]) == 4, 'not every iPad had the keyboard up')
dk = (o.get('kb') or {}).get('desk') or {}
check(dk and dk.get('top') == '' and dk.get('height') == '' and 'ios' not in dk.get('cls', '').split(),
      'the desk moves the PIN dialogue for a visualViewport: %r' % dk)

print('the user button')
for k in ('pin desk 1600', 'pin ipad 1194', 'pin phone 420', 'owner desk 1600', 'owner ipad 1194', 'owner phone 420'):
    r = (o.get('user') or {}).get(k) or {}
    who = 'pin' if k.startswith('pin') else 'owner'
    check(r.get('shown') and r['shown'].get('svg'), '%s: no user button in the header: %r' % (k, r.get('shown')))
    if ' phone ' not in k:
        check(r.get('shown') and who in r['shown'].get('text', ''), '%s: the user button does not name %s: %r' % (k, who, r.get('shown')))
    pp = r.get('popup') or {}
    check(pp.get('open') and pp.get('title') == who and pp.get('pk') and pp.get('add') and 'Administrator' in pp.get('body', ''),
          '%s: the user button does not open the account with its passkeys: %r' % (k, pp))
    check(pp.get('pickers'), '%s: the account popup has no looks of the meter: %r' % (k, pp))
    if who == 'pin':
        check('Lock now' in pp.get('buttons', []) and 'Change password' not in pp.get('buttons', []),
              '%s: the PIN account\'s popup has not Lock now (or offers a password): %r' % (k, pp.get('buttons')))
    else:
        check('Sign out' in pp.get('buttons', []) and 'Change password' in pp.get('buttons', []),
              '%s: the password account\'s popup is not as it was: %r' % (k, pp.get('buttons')))
ad = ((o.get('user') or {}).get('pin desk 1600') or {}).get('added') or {}
check(ad.get('n', 0) > ((o.get('user') or {}).get('pin desk 1600') or {}).get('before', 0) and 'localhost' in ad.get('rows', ''),
      'the PIN account could not add a passkey from the user button: %r' % ad)
check((o.get('user') or {}).get('nobody') is False, 'a user button with nobody signed in')
check(not o.get('errors'), 'the page threw: %r' % (o.get('errors') or [])[:5])

if SHOTS and not AGAINST_OLD:
    print('screenshots in ' + SHOTS)
finish()
