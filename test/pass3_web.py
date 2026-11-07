#!/usr/bin/env python3
"""Pass 3: the dashboard from the realtime point of view, in a realistic house
(test/pass3_house.py: 60 Zigbee devices, 30 sockets on six Shelly lookalikes,
200 rules, 3,000 long events), the real page through php -S, in Chromium.
Each check here fails on 5.46.0's page:

  * a socket pressed: the long poll's wake brought the new state, and the
    answer to the press asked for the whole status again - two status
    fetches and two redraws within 50 ms of every press. One now; and with
    no wake coming (the long poll stuck), the press still ends in a status
    showing the socket as asked;
  * a page put out of sight: the wait it had already asked for answered with
    the next change and the hidden page fetched the status, drew its tab and
    asked for the Overview's charts; nothing now, and back in sight the
    change is drawn at once;
  * Public API -> Every request at the server in front: asked for (up to a
    hundred requests with every header) with every status the page drew,
    once a second in a reporting house, rather than once on opening and
    every half minute; and an address typed and Enter pressed while a look
    was on its way did nothing - the table went on showing every address
    under a box that named one.

    python3 test/pass3_web.py           (PASS3_PAGE=<an index.php>: the same
                                         checks on another page - 5.46.0's
                                         must fail every one; PASS3_DUMP=1
                                         prints what was measured)

Ports 19750 (the daemon), 19751 (php -S), 19752 (the test's own handle on
the house), 19760-19765 (the boxes). Made-up names, 127.0.0.1 only.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pass3_house as H                                     # noqa: E402

W = Path(tempfile.mkdtemp(prefix='zigmon-pass3-web-'))
API_PORT, PHP_PORT, CTL_PORT = 19750, 19751, 19752
BOX_PORTS = list(range(19760, 19766))
DUMP = bool(os.environ.get('PASS3_DUMP'))
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
        except Exception:                                   # noqa: BLE001
            try:
                p.kill()
            except Exception:                               # noqa: BLE001
                pass
    shutil.rmtree(W, ignore_errors=True)
    print('pass3_web: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
    os._exit(1 if bad else 0)


if not shutil.which('php') or not shutil.which('node'):
    print('  SKIPPED: no php or no node here')
    finish()

print('the house')
zigmon, d, api, names = H.build(W, API_PORT, BOX_PORTS)
check(all(p.flat for p in d.plugs.values()), 'not every socket was read: %r'
      % [p.name for p in d.plugs.values() if not p.flat])
S_ADMIN = H.login(API_PORT, d.token)
(W / 'token').write_text(d.token)
folder = H.web(W, API_PORT, page=os.environ.get('PASS3_PAGE'))
if not H.serve(folder, PHP_PORT, workers='4', procs=PROCS):
    check(False, 'php -S could not serve the page')
    finish()


class Ctl(BaseHTTPRequestHandler):
    """The test's own hand on the house: a door opened or closed."""
    def log_message(self, *a):
        pass

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        if self.path.startswith('/door'):
            i = int(q['i'][0])
            d.handle_zigbee(names[i][0], json.dumps({'contact': q['v'][0] == '1', 'battery': 80}).encode())
        out = json.dumps({'t': time.time() * 1000, 'seq': d.seq}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        self.wfile.write(out)


ctl = ThreadingHTTPServer(('127.0.0.1', CTL_PORT), Ctl)
ctl.daemon_threads = True
threading.Thread(target=ctl.serve_forever, daemon=True).start()

PAGE_JS = r'''
const { chromium } = require('playwright');
const http = require('http');
const cfg = JSON.parse(process.env.P3_CFG);
const wait = ms => new Promise(r => setTimeout(r, ms));
const ctl = path => new Promise((res, rej) => http.get('http://127.0.0.1:' + cfg.ctl + path, r => {
  let b = ''; r.on('data', c => b += c); r.on('end', () => res(JSON.parse(b)));
}).on('error', rej));
const out = {errors: []};
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({viewport: {width: 1194, height: 834}});
  await ctx.addCookies([{name: 'zigmon_session', value: cfg.s, url: cfg.base + '/'}]);
  const p = await ctx.newPage();
  const reqs = [];
  p.on('pageerror', e => out.errors.push(String(e)));
  p.on('console', m => { if (m.type() === 'error') out.errors.push(m.text()); });
  p.on('request', r => { const q = r.url().split('?api=')[1]; if (q) reqs.push([Date.now(), q.split('&')[0], q]); });
  const since = (t, what) => reqs.filter(r => r[0] >= t && (!what || r[1] === what));
  await p.goto(cfg.base + '/#plugs');
  await p.waitForFunction(() => STATE.status && document.querySelector('[data-plug="Socket-0-0"] .socket-toggle:not([disabled])'),
                          null, {timeout: 30000});
  await wait(1500);

  // ---- a press: one status, and the socket as asked --------------------------------------
  out.press = [];
  for (let k = 0; k < 6; k++) {
    const name = 'Socket-' + (k % 6) + '-' + ((k + 1) % 5);
    const want = await p.evaluate(n => STATE.status.plugs.find(x => x.name === n).output === 1 ? 0 : 1, name);
    const t0 = await p.evaluate(n => { const t = Date.now(); document.querySelector('[data-plug="' + n + '"] .socket-toggle').click(); return t; }, name);
    const seen = await p.waitForFunction(([n, w]) => STATE.status.plugs.find(x => x.name === n).output === w ? Date.now() : false,
      [name, want], {polling: 10, timeout: 8000}).then(h => h.jsonValue()).catch(() => null);
    await wait(1000);
    out.press.push({shown: seen ? seen - t0 : -1, statuses: since(t0, 'status').filter(r => r[0] - t0 < 800).length,
                    sent: since(t0, 'plug-switch').length});
    await wait(800);
  }

  // ---- a press with the long poll stuck: still ends in the truth ------------------------------
  await p.route(/\?api=wait/, () => {});                     // every new wait hangs
  await ctl('/door?i=41&v=1');                               // the wait in flight answers once
  await wait(1500);
  {
    const name = 'Socket-5-4';
    const want = await p.evaluate(n => STATE.status.plugs.find(x => x.name === n).output === 1 ? 0 : 1, name);
    const t0 = await p.evaluate(n => { const t = Date.now(); document.querySelector('[data-plug="' + n + '"] .socket-toggle').click(); return t; }, name);
    const seen = await p.waitForFunction(([n, w]) => STATE.status.plugs.find(x => x.name === n).output === w ? Date.now() : false,
      [name, want], {polling: 10, timeout: 5000}).then(h => h.jsonValue()).catch(() => null);
    out.stuck = {shown: seen ? seen - t0 : -1};
  }
  await p.unroute(/\?api=wait/);
  await p.evaluate(() => { WAIT.running = false; waitLoop(); });
  await wait(1500);

  // ---- out of sight -------------------------------------------------------------------------
  await p.evaluate(() => showTab('overview'));
  await wait(2500);
  await p.evaluate(() => {
    Object.defineProperty(document, 'hidden', {value: true, configurable: true});
    Object.defineProperty(document, 'visibilityState', {value: 'hidden', configurable: true});
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await wait(300);
  let th = Date.now();
  await ctl('/door?i=42&v=1');
  await wait(600);
  await ctl('/door?i=43&v=1');
  await wait(2500);
  out.hidden = since(th).map(r => r[1]).filter(x => x !== 'wait');
  th = Date.now();
  await p.evaluate(() => {
    Object.defineProperty(document, 'hidden', {value: false, configurable: true});
    Object.defineProperty(document, 'visibilityState', {value: 'visible', configurable: true});
    document.dispatchEvent(new Event('visibilitychange'));
  });
  out.back = await p.waitForFunction(id => { const x = STATE.status.devices.find(v => v.id === id);
    return x && x.values.contact && x.values.contact.value === true ? Date.now() : false; },
    '0x' + (44).toString(16).padStart(16, '0'), {polling: 20, timeout: 5000}).then(h => h.jsonValue()).then(v => v - th).catch(() => -1);

  // ---- Public API: the requests at the server in front -----------------------------------------
  const to = Date.now();
  await p.evaluate(() => showTab('approvals'));
  await wait(2000);
  out.preqOpen = since(to, 'proxy-requests').length;
  const ta = Date.now();
  const before = since(ta, 'status').length;
  for (let k = 0; k < 6; k++) { await ctl('/door?i=' + (45 + k % 3) + '&v=' + (k % 2)); await wait(700); }
  await wait(800);
  out.preq = {statuses: since(ta, 'status').length - before, asked: since(ta, 'proxy-requests').length,
              card: await p.evaluate(() => !$('preq-card').hidden)};
  // a look on its way, and an address asked for meanwhile
  await p.route(/\?api=proxy-requests/, async route => { await wait(1500); await route.continue(); });
  const tb = Date.now();
  await p.evaluate(() => { PREQ.at = 0; loadProxyRequests(false); });
  await wait(300);
  await p.fill('#preq-ip', '198.51.100.7');
  await p.press('#preq-ip', 'Enter');
  await wait(4500);
  out.preqTyped = {asked: since(tb, 'proxy-requests').map(r => r[2]),
                   key: await p.evaluate(() => PREQ.key)};
  await p.unroute(/\?api=proxy-requests/);
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { out.error = String(e); console.log(JSON.stringify(out)); process.exit(0); });
'''
(W / 'page.js').write_text(PAGE_JS)
print('the page')
root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()
try:
    got = subprocess.run(['node', str(W / 'page.js')], capture_output=True, text=True, timeout=400,
                         stdin=subprocess.DEVNULL,
                         env=dict(os.environ, NODE_PATH=root, P3_CFG=json.dumps({
                             'base': 'http://127.0.0.1:%d' % PHP_PORT, 'ctl': CTL_PORT, 's': S_ADMIN})))
    lines = [x for x in got.stdout.splitlines() if x.startswith('{')]
    o = json.loads(lines[-1]) if lines else {'error': (got.stdout + got.stderr)[-600:]}
except subprocess.TimeoutExpired:
    o = {'error': 'the browser did not finish in 400 s'}
if DUMP:
    print(json.dumps(o, indent=1))
if o.get('error') and ('Executable doesn' in o['error'] or 'Cannot find module' in o['error']):
    print('  SKIPPED (no browser here): %s' % o['error'][:200])
    finish()
check(not o.get('error'), 'the page: %s' % o.get('error'))

presses = o.get('press') or []
check(len(presses) == 6 and all(x['sent'] == 1 and 0 <= x['shown'] < 3000 for x in presses),
      'a press did not switch the socket, or the page did not show it: %r' % presses)
# one fetch per press; a report from the house now and then may add one, so
# most presses, not all of them
once = sum(1 for x in presses if x['statuses'] == 1)
check(once >= 4, 'a press fetched the status more than once (fetches within 0.8 s of each press: %r)'
      % [x['statuses'] for x in presses])
check(0 <= (o.get('stuck') or {}).get('shown', -1) < 3000,
      'with the long poll stuck, a press never showed the socket as asked: %r' % o.get('stuck'))

check(o.get('hidden') == [], 'a page out of sight fetched %r when the house changed' % o.get('hidden'))
check(0 <= (o.get('back') if isinstance(o.get('back'), (int, float)) else -1) < 3000,
      'back in sight, the change was not drawn at once: %r' % o.get('back'))

pq = o.get('preq') or {}
check(pq.get('card') and pq.get('statuses', 0) >= 3, 'the Public API tab did not follow the house: %r' % pq)
check(o.get('preqOpen') == 1, 'opening Public API asked for the requests at the server in front %r times'
      % o.get('preqOpen'))
check(pq.get('asked', 99) <= 1, 'the requests at the server in front were asked for %r times in %r redraws'
      % (pq.get('asked'), pq.get('statuses')))
pt = o.get('preqTyped') or {}
check(any('ip=198.51.100.7' in x for x in pt.get('asked') or []) and str(pt.get('key', '')).startswith('198.51.100.7'),
      'an address asked for while a look was on its way was dropped: %r' % pt)
check(not o.get('errors'), 'errors on the page: %r' % o.get('errors'))
finish()
