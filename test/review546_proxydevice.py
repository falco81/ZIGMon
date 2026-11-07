"""5.46: the server in front is a device like the others.

    python3 test/review546_proxydevice.py

Each of these fails on 5.45.0:

  * every look of the SSLProxy card is a reading of the device proxy:front -
    on Devices, with a headline, a history the charts draw, and its own kind
  * it is read whether or not its card is on the Overview (a graph with holes
    wherever nobody had the page open draws nothing)
  * renamed like any device that is not Zigbee (an alias): the card, the
    picker and the next look keep the new name
  * its object: its readings as properties, rename(), look()
  * its facts: {SSLProxy.px_requests_h} and the named ones ({proxy_state},
    {proxy_requests_hour}, ...)
  * the page: the card has its object mark and the way to its charts, which
    opens History on it; it is on Devices; the picker offers it once

Made-up names and addresses; nothing listens but 127.0.0.1:19294 (the daemon)
and 19295 (php -S).
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review546d-'))
API_PORT, PHP_PORT = 19294, 19295
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
    print('review546_proxydevice: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
    os._exit(1 if bad else 0)


sys.argv = ['zigmon']
sys.path.insert(0, os.environ.get('REVIEW546_DAEMON') or str(HERE))
import zigmon                                                # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'log_file': '', 'state_dir': str(W / 'state'), 'proxy_host': 'proxy.house.example',
                      'proxy_watch': 1, 'proxy_log': '/var/log/nginx/zigmon-tap.log',
                      'suricata_log': '/var/log/suricata/eve.json', 'proxy_auth': 'key'})
(W / 'state').mkdir()
RUNS = []
STATE = {'requests': 214}


def fake_run(command):
    """The server in front: the answer the card's one command gets, marked
    with the marker that command carries."""
    RUNS.append(command)
    found = re.search(r'echo "(ZTILE-[0-9a-f]+) \$1"', command)
    m = found.group(1) if found else 'ZTILE-x'
    return '\n'.join([
        m + ' up', '1047212.55 3340.79', m + ' load', '0.42 0.31 0.18 1/108 1429',
        m + ' mem', 'MemTotal:        4030000 kB', 'MemAvailable:    2520000 kB',
        m + ' disk', '/dev/vda1 41152736 12000000 27000000 31% /', m + ' host', 'edge-proxy',
        m + ' svc', 'nginx active', 'suricata active',
        m + ' nginx', 'N %d 12 30 1' % STATE['requests'], 'A 9 198.51.100.7',
        m + ' fast', 'N 37 2', 'S 30 2|ET DROP Spamhaus DROP Listed Traffic Inbound', 'A 30 45.1.2.3',
        m + ' stats', 'Date: 11/6/2026 -- 22:13:27 (uptime: 3d, 05h 12m 03s)',
        'capture.kernel_packets                        | Total                     | 1234567',
        'capture.kernel_drops                          | Total                     | 89',
        m + ' end', ''])


d = zigmon.Daemon()
d.notify = lambda *a, **k: None
d.proxy_run = fake_run
d.save_overview_layout([])                     # the card is NOT on the Overview


def look_now():
    n = int(d.__dict__.get('_proxy_tile_runs') or 0)
    d._proxy_tile_look = dict(d.__dict__.get('_proxy_tile_look') or {}, at=0, tried=0)
    d.__dict__.pop('_proxy_tile_started', None)
    zigmon.proxy_tile_look(d)
    end = time.time() + 10
    while time.time() < end and int(d.__dict__.get('_proxy_tile_runs') or 0) <= n:
        time.sleep(0.05)
    time.sleep(0.05)


print('a device')
check(hasattr(zigmon, 'proxy_device_record'), 'the server in front is no device (no proxy_device_record)')
check(zigmon.proxy_tile_wanted(d), 'the clock does not read the server in front while its card is not shown')
look_now()
row = d.store.device('proxy:front')
check(row is not None and row.get('source') == 'proxy', 'no device proxy:front after a look: %r' % row)
dev = next((x for x in d.status()['devices'] if x['id'] == 'proxy:front'), None)
check(dev is not None, 'proxy:front is not among the devices of the status')
if dev:
    keys = [h.get('key') for h in dev.get('headline') or []]
    check(keys[:4] == ['px_nginx', 'px_suricata', 'px_requests_h', 'px_alerts_24h'],
          'its headline: %r' % keys)
    check(dev['values'].get('px_requests_h', {}).get('value') == 214
          and dev['values'].get('px_mem_used', {}).get('unit') == '%',
          'its readings: %r' % {k: v for k, v in dev['values'].items()})
    check(dev.get('online') and dev.get('name') == 'edge-proxy', 'online, named by its host: %r'
          % {k: dev.get(k) for k in ('online', 'name', 'level', 'reasons')})
STATE['requests'] = 300
look_now()
hist = d.store.history('proxy:front', ['px_requests_h'], 3600, 100)
# two looks a second apart fall into one point of the chart; a minute apart
# (the clock's pace) they are two
check(hist and hist[-1].get('px_requests_h') == 300, 'the history does not hold the look: %s'
      % json.dumps(hist)[:300])

print('renamed')
d.rename_device('proxy:front', 'Edge')
look_now()
check(zigmon.proxy_tile_state(d).get('name') == 'Edge', 'the card is not named as renamed: %r'
      % zigmon.proxy_tile_state(d).get('name'))
dev = next((x for x in d.status()['devices'] if x['id'] == 'proxy:front'), {})
check(dev.get('name') == 'Edge', 'the device lost its new name at the next look: %r' % dev.get('name'))

print('its object and its facts')
one = d.object_detail('device:proxy:front', reveal=True) or {}
flat = json.dumps(one)
check('px_requests_h' in flat and '"look"' in flat and '"rename"' in flat,
      'the object has not its readings, look() and rename(): %s' % flat[:400])
said = d.object_call('device:proxy:front', 'look', '', 'a test')
check('being read now' in str(said), 'look() from the object: %r' % said)
time.sleep(0.5)
facts = d.message_facts('a test')
check(isinstance(facts, dict) and facts.get('proxy_requests_hour') == 300 and facts.get('proxy_nginx') == 'active'
      and facts.get('proxy_state') == 'online', 'the named facts: %r' % {k: v for k, v in (facts or {}).items()
                                                                      if k.startswith('proxy')})
try:
    text = d.fill_message('{Edge.px_requests_h} requests, {proxy_alerts_day} alerts', facts)
except Exception as e:                                       # noqa: BLE001
    text = 'error: %s' % e
check(text.startswith('300') and '37 alerts' in text, '{Edge.px_requests_h} and {proxy_alerts_day}: %r' % text)

# ---- the page ------------------------------------------------------------------
print('the page')
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


d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
S_ADMIN = login('owner', 'owner pass 12')
d.save_overview_layout(['proxy:front'])
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
const PORT = %(port)d, SH = %(shots)s, S = %(s)s;
(async () => {
  const b = await chromium.launch();
  const r = {};
  const ctx = await b.newContext({viewport: {width: 1400, height: 1000}});
  await ctx.addCookies([{name: 'zigmon_session', value: S, url: 'http://127.0.0.1:' + PORT + '/'}]);
  const p = await ctx.newPage();
  p.errors = [];
  p.on('pageerror', e => p.errors.push(String(e)));
  await p.goto('http://127.0.0.1:' + PORT + '/#overview');
  try { await p.waitForSelector('#overview-custom .proxy-tile .tag.ok', {timeout: 20000}); } catch (e) { r.wait = String(e); }
  r.card = await p.evaluate(() => { const c = document.querySelector('#overview-custom .proxy-tile');
    return c ? {name: c.querySelector('.name').innerText, mark: !!c.querySelector('.obj-mark'),
                hist: !!c.querySelector('.dev-hist')} : null; });
  r.picker = await p.evaluate(() => Array.from(document.querySelectorAll('#ov-add-select option'))
    .filter(o => o.value === 'proxy:front').length + (overviewLayoutIds(STATE.status).indexOf('proxy:front') >= 0 ? 1 : 0));
  r.options = await p.evaluate(() => overviewAvailableOptions(STATE.status).filter(o => o[0] === 'proxy:front').length);
  const card = await p.$('#overview-custom .proxy-tile');
  if (card) { await card.hover(); await p.screenshot({path: SH + '/proxy-card.png', clip: await card.boundingBox()}); }
  const h = await p.$('#overview-custom .proxy-tile .dev-hist');
  if (h) { await h.click({force: true}); await p.waitForTimeout(1500); }
  r.history = await p.evaluate(() => ({tab: STATE.tab, device: STATE.hDevice}));
  await p.waitForTimeout(1000);
  await p.screenshot({path: SH + '/proxy-history.png'});
  r.firstChart = await p.evaluate(() => { const t = document.querySelector('#h-charts .card h2, #h-charts .card .title, #history-charts .card h2');
    return t ? t.innerText : (document.querySelector('[id^="h-chart-"]') || {}).id || ''; });
  await p.goto('http://127.0.0.1:' + PORT + '/#devices');
  await p.waitForTimeout(2500);
  r.devices = await p.evaluate(() => document.body.innerText.indexOf('Edge') >= 0
    && !!Array.from(document.querySelectorAll('.card.dev .name')).find(n => n.innerText.indexOf('Edge') >= 0));
  r.errors = p.errors;
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
(W / 'page.js').write_text(js % {'port': PHP_PORT, 'shots': json.dumps(SHOTS), 's': json.dumps(S_ADMIN)})
root = sh(['npm', 'root', '-g']).stdout.strip()
got = sh(['node', str(W / 'page.js')], timeout=240, env=dict(os.environ, NODE_PATH=root))
try:
    r = json.loads(got.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    r = {'error': (got.stdout + got.stderr)[-400:]}
if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
    print('  SKIPPED (no browser here): %s' % r['error'][:200])
else:
    check(not r.get('error'), 'the page: %s' % r.get('error'))
    c = r.get('card') or {}
    check(c.get('name', '').strip().endswith('Edge') and c.get('name', '').startswith('\U0001f6e1') and c.get('mark') and c.get('hist'),
          'the card has not its name, its object mark and the way to its charts: %r (%s)' % (c, r.get('wait', '')))
    check(r.get('history') == {'tab': 'history', 'device': 'proxy:front'}, 'the charts: %r' % r.get('history'))
    check('Requests' in (r.get('firstChart') or '') or (r.get('firstChart') or '').endswith('px_requests_h'),
          'the charts do not start with the requests: %r' % r.get('firstChart'))
    check(r.get('options') == 1, 'the picker offers the server in front %r times' % r.get('options'))
    check(r.get('devices'), 'it is not on Devices under its name')
    check(not r.get('errors'), 'errors on the page: %r' % r.get('errors'))
finish()
