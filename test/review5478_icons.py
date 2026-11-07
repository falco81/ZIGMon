"""5.47.8: the head of a Settings section scrolls with it; every device card
wears the drawing of its kind before its name.

    python3 test/review5478_icons.py

Each fails on 5.47.7. Ports 19284 (the daemon), 19285 (php -S).
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
W = Path(tempfile.mkdtemp(prefix='zigmon-review5478-'))
API_PORT, PHP_PORT = 19284, 19285
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
    print('review5478_icons: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
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

shutil.copytree(os.environ.get('REVIEW5478_WEB') or (HERE / 'web'), W / 'web')
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
(async () => {
  const b = await chromium.launch();
  const out = {};
  const ctx = await b.newContext({viewport: {width: 1600, height: 900}});
  await ctx.addCookies([{name: 'zigmon_session', value: S, url: 'http://127.0.0.1:' + PORT + '/'}]);
  const p = await ctx.newPage();
  p.errors = [];
  p.on('pageerror', e => p.errors.push(String(e)));
  await p.goto('http://127.0.0.1:' + PORT + '/#overview');
  await p.waitForTimeout(2500);
  out.cards = await p.evaluate(() => Array.from(document.querySelectorAll('#overview-custom .card.dev:not(.proxy-tile)')).map(c => ({
    name: (c.querySelector('.name') || {}).innerText || '', icon: ((c.querySelector('.name .dev-ic') || {}).textContent || '') === deviceIcon(deviceById(c.dataset.id || '') || {})
      || !!((c.querySelector('.name .dev-ic') || {}).textContent)})));
  await p.screenshot({path: SH + '/overview.png'});
  await p.goto('http://127.0.0.1:' + PORT + '/?b=1#control/sys-upgrade');
  await p.waitForTimeout(2500);
  out.head = await p.evaluate(() => {
    const h = document.getElementById('ctl-head'), m = document.querySelector('.ctl-main');
    const before = Math.round(h.getBoundingClientRect().top);
    m.scrollTop = 400;
    return {before: before, after: Math.round(h.getBoundingClientRect().top), scrolled: m.scrollTop};
  });
  out.errors = p.errors;
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
cards = r.get('cards') or []
check(len(cards) >= 20 and all(c.get('icon') for c in cards),
      'a device card without the mark of its kind: %r' % [c.get('name') for c in cards if not c.get('icon')][:5])
h = r.get('head') or {}
check(h.get('scrolled', 0) > 100 and h.get('after', 0) < h.get('before', 0) - 100,
      'the head of a Settings section stayed where it was: %r' % h)
check(not r.get('errors'), 'errors on the page: %r' % r.get('errors'))
finish()
