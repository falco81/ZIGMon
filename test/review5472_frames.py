"""5.47.2: on a desk, a tab that is a list scrolls its rows and nothing else.

    python3 test/review5472_frames.py

For Events, each part of Public API (presses, the requests at the server in
front, the blocked addresses), Devices, History and WiFi, at 1400 x 900:
whatever there is to scroll is scrolled to its end, and then

  * the tab itself has not moved (its frame did not scroll);
  * its buttons, its filters and its pages are where they were;
  * the heading row of the table is still at the top of what scrolls;
  * what scrolls did scroll.

And on a phone (420 wide) the page scrolls as a page, as it did.
Each fails on 5.47.1. Made-up names; ports 19298 (the daemon), 19299 (php -S).
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review5472-'))
API_PORT, PHP_PORT = 19298, 19299
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


def finish():
    for p in PROCS:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    shutil.rmtree(W, ignore_errors=True)
    print('review5472_frames: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
    os._exit(1 if bad else 0)


sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                                # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'log_file': '', 'state_dir': str(W / 'state'), 'proxy_full_watch': 1, 'blacklist': 1})
(W / 'state').mkdir()
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
d.mikrotik_after_change = lambda *a, **k: None
d.proxy_run = lambda command: ''
now = time.time()
for i in range(300):
    d.store.add_event('control', 'a made-up event number %d' % i, 'info', None, ts=now - i * 60)
for i in range(120):
    d.store.log_tap({'ts': now - i * 300, 'ended': now - i * 300, 'ticket': 't%d' % i, 'link': 'Link-%d' % (i % 5),
                     'what': 'tell you something', 'who': '203.0.113.%d' % (i % 200), 'way': 'by a header',
                     'factor': '', 'state': 'done', 'message': 'done', 'device': ''})
for i in range(150):
    d.store.block('198.51.100.%d' % (i % 250), until=now + 3600, why='made up %d' % i, auto=True, by='')
lines = [json.dumps({'ip': '203.0.113.%d' % (i % 200), 'm': 'GET', 'u': '/p%d' % i, 's': 444, 'ua': 'curl/8',
                     't': time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime(now - i))}) for i in range(150)]
d.full_weigh(lines)
for i in range(60):
    d.store.upsert_device({'id': '0x%04x' % i, 'name': 'Temp-%02d' % i, 'source': 'zigbee', 'kind': 'EndDevice',
                           'model': 'SNZB-02', 'vendor': 'SONOFF', 'last_seen': int(now)})

api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)
req = urllib.request.Request('http://127.0.0.1:%d/api/auth/login' % API_PORT,
                             data=json.dumps({'name': 'owner', 'password': 'owner pass 12'}).encode(),
                             headers={'X-Zigmon-Token': d.token, 'Content-Type': 'application/json',
                                      'X-Zigmon-Client': '192.168.40.10'}, method='POST')
d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
with urllib.request.urlopen(req, timeout=30) as r:
    S_ADMIN = json.loads(r.read()).get('token') or ''

shutil.copytree(os.environ.get('REVIEW5472_WEB') or (HERE / 'web'), W / 'web')
api_php = (W / 'web' / 'zigmon-api.php').read_text()
api_php = api_php.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
api_php = api_php.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
(W / 'web' / 'zigmon-api.php').write_text(api_php)
php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, str(W / 'web' / 'index.php')], cwd=str(W / 'web'),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                       env=dict(os.environ, PHP_CLI_SERVER_WORKERS='4'))
PROCS.append(php)
for _ in range(50):
    try:
        socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
        break
    except OSError:
        time.sleep(0.1)
SHOTS = os.environ.get('SHOTS') or str(W / 'shots')
os.makedirs(SHOTS, exist_ok=True)
js = r'''
const { chromium } = require('playwright');
const PORT = %(port)d, SH = %(shots)s, S = %(s)s;
// [where, what stays (selectors), what scrolls (selector), a table head inside it or null]
const CASES = [
  ['#events', ['#evf-kind', '#events-pager', '#tab-events h2'], '#events-scroll', '#events-table thead th'],
  ['#approvals/presses', ['#api-subs', '#presses-filter', '#presses-pager'], '#tab-approvals > [data-sub="presses"] > .list-scroll', '#approvals-past thead th'],
  ['#approvals/requests', ['#api-subs', '#preq-ip', '#preq-more'], '#preq-card > .list-scroll', '#preq-table thead th'],
  ['#approvals/blocked', ['#api-subs', '#look-ip', '#blocked-add', '#blockstory-pager-slot'], '#blocked-card > .list-scroll', null],
  ['#devices', ['#tab-devices > .card'], '#tab-devices .list-scroll', '#devices-table thead th'],
  ['#history', ['#h-device'], '#tab-history > .frame-scroll', null],
  ['#wifi', ['#wifi-refresh'], '#tab-wifi > .frame-scroll', null],
];
(async () => {
  const b = await chromium.launch();
  const out = {cases: {}};
  const ctx = await b.newContext({viewport: {width: 1400, height: 900}});
  await ctx.addCookies([{name: 'zigmon_session', value: S, url: 'http://127.0.0.1:' + PORT + '/'}]);
  const p = await ctx.newPage();
  p.errors = [];
  p.on('pageerror', e => p.errors.push(String(e)));
  for (const [where, stays, scroller, head] of CASES) {
    await p.goto('http://127.0.0.1:' + PORT + '/?f=' + encodeURIComponent(where) + where);
    await p.waitForTimeout(2500);
    if (where === '#approvals/blocked') {     // the folds open, so there is something to scroll
      await p.evaluate(() => document.querySelectorAll('#blocked-list details').forEach(x => x.open = true));
      await p.waitForTimeout(300);
    }
    const r = await p.evaluate(([stays, scroller, head]) => {
      const panel = document.querySelector('section.panel:not([hidden])');
      const top = sel => { const e = document.querySelector(sel); return e ? Math.round(e.getBoundingClientRect().top) : null; };
      const sc = document.querySelector(scroller);
      const before = {stays: stays.map(top), panel: panel.scrollTop, head: head ? top(head) : null,
                      sc: sc ? [sc.scrollHeight, sc.clientHeight] : null};
      panel.scrollTop = 99999;
      if (sc) sc.scrollTop = 99999;
      const scTop = sc ? sc.getBoundingClientRect().top : null;
      return {before: before, after: {stays: stays.map(top), panel: panel.scrollTop, head: head ? top(head) : null,
              scTop: scTop === null ? null : Math.round(scTop), scrolled: sc ? sc.scrollTop : null}};
    }, [stays, scroller, head]);
    out.cases[where] = r;
    await p.screenshot({path: SH + '/' + where.replace(/[#\/]/g, '_') + '.png'});
  }
  out.errors = p.errors;
  const phone = await b.newContext({viewport: {width: 420, height: 800}});
  await phone.addCookies([{name: 'zigmon_session', value: S, url: 'http://127.0.0.1:' + PORT + '/'}]);
  const q = await phone.newPage();
  q.errors = [];
  q.on('pageerror', e => q.errors.push(String(e)));
  await q.goto('http://127.0.0.1:' + PORT + '/#devices');
  await q.waitForTimeout(2500);
  await q.screenshot({path: SH + '/phone-devices.png'});
  out.phoneErrors = q.errors;
  out.phone = await q.evaluate(() => ({doc: document.scrollingElement.scrollHeight, win: innerHeight,
    wide: document.documentElement.scrollWidth,
    inner: Array.from(document.querySelectorAll('*')).filter(e => e.scrollHeight > e.clientHeight + 4
      && /(auto|scroll)/.test(getComputedStyle(e).overflowY)).map(e => (e.id || e.className || e.tagName) + ':' + e.clientHeight).slice(0, 6)}));
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
(W / 'page.js').write_text(js % {'port': PHP_PORT, 'shots': json.dumps(SHOTS), 's': json.dumps(S_ADMIN)})
root = sh(['npm', 'root', '-g']).stdout.strip()
try:
    got = sh(['node', str(W / 'page.js')], timeout=300, env=dict(os.environ, NODE_PATH=root))
except subprocess.TimeoutExpired:
    check(False, 'the page did not answer in 300 s')
    finish()
try:
    r = json.loads(got.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    r = {'error': (got.stdout + got.stderr)[-400:]}
if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
    print('  SKIPPED (no browser here): %s' % r['error'][:200])
    finish()
check(not r.get('error'), 'the page: %s' % r.get('error'))
for where, c in sorted((r.get('cases') or {}).items()):
    b4, af = c.get('before') or {}, c.get('after') or {}
    print('  %-22s scroller %s, scrolled %s' % (where, b4.get('sc'), af.get('scrolled')))
    check(b4.get('sc') is not None and b4['sc'][1] > 100, '%s: there is nothing that scrolls on its own: %r'
          % (where, b4.get('sc')))
    check(af.get('panel') == 0, '%s: the whole tab scrolled (%s px)' % (where, af.get('panel')))
    check(None not in (b4.get('stays') or [None]) and b4.get('stays') == af.get('stays'),
          '%s: what should stay moved: %r -> %r' % (where, b4.get('stays'), af.get('stays')))
    if b4.get('sc') and b4['sc'][0] > b4['sc'][1] + 4:
        check((af.get('scrolled') or 0) > 0, '%s: the rows did not scroll' % where)
    if b4.get('head') is not None:
        check(af.get('head') is not None and abs(af['head'] - (af.get('scTop') or 0)) <= 2,
              '%s: the heading row went with the rows (%s, its frame at %s)' % (where, af.get('head'), af.get('scTop')))
ph = r.get('phone') or {}
check(ph.get('doc', 0) > ph.get('win', 0) and ph.get('wide', 999) <= 421,
      'a phone does not scroll the page as a page: %r' % ph)
check(not r.get('errors') and not r.get('phoneErrors'), 'errors on the page: %r %r'
      % (r.get('errors'), r.get('phoneErrors')))
finish()
