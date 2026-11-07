"""5.47.1: Public API in parts, and the marks on the requests at the server in front.

    python3 test/review5471_apisubs.py

Each of these fails on 5.47.0:

  * the tab opens on one part, picked by a row of pills at its top (Waiting,
    Presses, At the server in front, Blocked addresses), each with how many it
    holds; only that part's card is drawn
  * the part is in the address (#approvals/blocked) and comes back after a
    reload; a viewer has no "At the server in front" pill
  * the requests are not asked for while another part is shown
  * each request's address wears the marks the blocked list wears: its flag,
    kept out now, a list that knows it, Suricata, the house's own - and the
    buttons that ask Shodan and Talos

Made-up addresses; ports 19296 (the daemon) and 19297 (php -S).
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
W = Path(tempfile.mkdtemp(prefix='zigmon-review5471-'))
API_PORT, PHP_PORT = 19296, 19297
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
    print('review5471_apisubs: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
    os._exit(1 if bad else 0)


sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                                # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'log_file': '', 'state_dir': str(W / 'state'), 'never_block': '198.51.100.20',
                      'proxy_full_watch': 1, 'blacklist': 1, 'feeds_ban': 0, 'intel_shodan': 1})
(W / 'state').mkdir()
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
d.mikrotik_after_change = lambda *a, **k: None
d.proxy_run = lambda command: ''
d.feed_wanted = lambda: ['made-up-list']
d.feed_says = lambda ip: 'made-up-list' if ip == '203.0.113.12' else None

now = time.time()


def line(ip, ago, u='/', s=444):
    return json.dumps({'ip': ip, 't': time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime(now - ago)),
                       'm': 'GET', 'u': u, 's': s, 'host': 'x', 'ua': 'curl/8'})


d.full_weigh([line('203.0.113.11', 50), line('203.0.113.12', 40), line('203.0.113.13', 30),
              line('198.51.100.20', 20, '/tap', 200)])
d.store.block('203.0.113.11', until=now + 3600, why='a test', auto=False, by='test')
d.store.set_meta('ids_about_203.0.113.13', json.dumps({'sid': 2400015, 'msg': 'ET DROP'}))

print('the API')
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def login(name, password):
    req = urllib.request.Request('http://127.0.0.1:%d/api/auth/login' % API_PORT,
                                 data=json.dumps({'name': name, 'password': password}).encode(),
                                 headers={'X-Zigmon-Token': d.token, 'Content-Type': 'application/json',
                                          'X-Zigmon-Client': '192.168.40.10'}, method='POST')
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read()).get('token') or ''


def get(path, session):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path),
                                 headers={'X-Zigmon-Token': d.token, 'X-Zigmon-Session': session,
                                          'X-Zigmon-Client': '192.168.40.10'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
d.account_add('watcher', 'viewer', 'watcher pass 12', must_change=False, quiet=True)
S_ADMIN = login('owner', 'owner pass 12')
S_VIEW = login('watcher', 'watcher pass 12')
rows = {r['ip']: r for r in get('/api/proxy/requests', S_ADMIN)['rows']}
check(rows.get('203.0.113.11', {}).get('blocked') is True, 'a blocked address is not marked: %r' % rows.get('203.0.113.11'))
check(rows.get('203.0.113.12', {}).get('listed') == 'made-up-list', 'a listed one: %r' % rows.get('203.0.113.12'))
check(rows.get('203.0.113.13', {}).get('ids') is True, 'one Suricata spoke of: %r' % rows.get('203.0.113.13'))
check(rows.get('198.51.100.20', {}).get('spared') is True, 'the house\'s own: %r' % rows.get('198.51.100.20'))
check(all('country' in r for r in rows.values()), 'no country on the rows')

print('the page')
shutil.copytree(HERE / 'web', W / 'web')
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
const PORT = %(port)d, SH = %(shots)s, S = %(s)s, V = %(v)s;
async function open(b, session, hash) {
  const ctx = await b.newContext({viewport: {width: 1400, height: 1000}});
  await ctx.addCookies([{name: 'zigmon_session', value: session, url: 'http://127.0.0.1:' + PORT + '/'}]);
  const p = await ctx.newPage();
  p.errors = []; p.asked = [];
  p.on('pageerror', e => p.errors.push(String(e.stack || e).split('\n').slice(0, 3).join(' | ')));
  p.on('request', r => { if (r.url().indexOf('proxy-requests') >= 0) p.asked.push(r.url()); });
  await p.goto('http://127.0.0.1:' + PORT + '/' + hash);
  await p.waitForTimeout(2500);
  return p;
}
const state = p => p.evaluate(() => ({
  pills: Array.from(document.querySelectorAll('#api-subs button')).filter(b => !b.hidden && getComputedStyle(b).display !== 'none')
    .map(b => [b.getAttribute('data-sub'), b.classList.contains('on'), (b.querySelector('.n') || {}).textContent || '']),
  cards: Array.from(document.querySelectorAll('#tab-approvals > .card[data-sub]'))
    .filter(c => getComputedStyle(c).display !== 'none').map(c => c.getAttribute('data-sub')),
  hash: location.hash}));
(async () => {
  const b = await chromium.launch();
  const r = {};
  const p = await open(b, S, '#approvals');
  r.first = await state(p); console.error(JSON.stringify(r.first));
  r.askedOnPresses = p.asked.length;
  await p.click('#api-subs button[data-sub="requests"]', {timeout: 8000}).catch(e => { r.clickErr = String(e).slice(0, 300); });
  try { await p.waitForSelector('#preq-table tbody tr.preq-row', {timeout: 15000}); } catch (e) { r.wait = String(e); }
  await p.waitForTimeout(500);
  r.requests = await state(p);
  r.marks = await p.evaluate(() => Array.from(document.querySelectorAll('#preq-table tbody tr.preq-row')).map(tr => ({
    ip: (tr.querySelector('.preq-ip') || {}).textContent, marks: tr.querySelector('.story-marks') ? tr.querySelector('.story-marks').textContent : null,
    flag: !!tr.querySelector('.cflag'), ask: !!tr.querySelector('.story-ask .intel-btns, .story-ask button'),
    obj: !!tr.querySelector('.obj-mark')})));
  const card = await p.$('#tab-approvals');
  await p.screenshot({path: SH + '/public-api-requests.png'});
  await p.click('#api-subs button[data-sub="blocked"]', {timeout: 8000}).catch(e => { r.clickErr2 = String(e).slice(0, 300); });
  await p.waitForTimeout(400);
  r.blocked = await state(p);
  await p.screenshot({path: SH + '/public-api-blocked.png'});
  await p.reload();
  await p.waitForTimeout(2500);
  r.reloaded = await state(p);
  r.errors = p.errors;
  const v = await open(b, V, '#approvals/requests');
  r.viewer = await state(v);
  r.viewerAsked = v.asked.length;
  r.verrors = v.errors;
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
(W / 'page.js').write_text(js % {'port': PHP_PORT, 'shots': json.dumps(SHOTS), 's': json.dumps(S_ADMIN),
                                 'v': json.dumps(S_VIEW)})
root = sh(['npm', 'root', '-g']).stdout.strip()
try:
    got = sh(['node', str(W / 'page.js')], timeout=240, env=dict(os.environ, NODE_PATH=root))
except subprocess.TimeoutExpired:
    check(False, 'the page did not answer in 240 s')
    finish()                       # php -S goes with it, or it serves this copy to the next run
try:
    r = json.loads(got.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    r = {'error': (got.stdout + got.stderr)[-400:]}
if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
    print('  SKIPPED (no browser here): %s' % r['error'][:200])
    finish()
check(not r.get('error'), 'the page: %s' % r.get('error'))
first = r.get('first') or {}
check([x[0] for x in first.get('pills') or []] == ['waiting', 'presses', 'requests', 'blocked'],
      'the pills: %r' % first.get('pills'))
check(len(first.get('cards') or []) == 1, 'more than one part is drawn at once: %r' % first.get('cards'))
check(r.get('askedOnPresses') == 0, 'the requests were asked for %r times with another part shown'
      % r.get('askedOnPresses'))
req = r.get('requests') or {}
check(req.get('cards') == ['requests'] and req.get('hash') == '#approvals/requests',
      'picking "At the server in front": %r' % req)
pill = dict((x[0], x[2]) for x in req.get('pills') or [])
check(pill.get('requests') == '4' and pill.get('blocked') == '1', 'the counts on the pills: %r' % pill)
marks = {m['ip']: m for m in r.get('marks') or []}
check(len(marks) == 4, 'the rows: %r (%s)' % (list(marks), r.get('wait', '')))
check('⛔' in (marks.get('203.0.113.11') or {}).get('marks', ''), 'kept out now has no mark: %r'
      % marks.get('203.0.113.11'))
check('\U0001f4d5' in (marks.get('203.0.113.12') or {}).get('marks', ''), 'a listed one has no mark')
check('\U0001f4e1' in (marks.get('203.0.113.13') or {}).get('marks', ''), 'Suricata\'s has no mark')
check('\U0001f3e0' in (marks.get('198.51.100.20') or {}).get('marks', ''), 'the house\'s own has no mark')
check(all(m['flag'] and m['ask'] and m['obj'] for m in marks.values()),
      'a row without its flag, its Shodan/Talos buttons or its object mark: %r' % list(marks.values()))
check((r.get('blocked') or {}).get('cards') == ['blocked'], 'the blocked part: %r' % r.get('blocked'))
check((r.get('reloaded') or {}).get('cards') == ['blocked'] and (r.get('reloaded') or {}).get('hash') == '#approvals/blocked',
      'after a reload: %r' % r.get('reloaded'))
vw = r.get('viewer') or {}
check('requests' not in [x[0] for x in vw.get('pills') or []] and vw.get('cards') == ['presses']
      and r.get('viewerAsked') == 0, 'a viewer: %r, asked %r' % (vw, r.get('viewerAsked')))
check(not r.get('errors') and not r.get('verrors'), 'errors: %r %r' % (r.get('errors'), r.get('verrors')))
finish()
