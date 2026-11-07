"""5.47.4: SMS in parts, and the other networks of WiFi now or ever, filtered from the top.

    python3 test/review5474_parts.py

  * SMS opens on Messages; "Write a message" is a part of its own, picked by
    its pill, kept in the address (#sms/write) and over a reload; Answer on a
    message goes to the form
  * WiFi's other networks: "On the air now" and "Everything ever heard" are two
    pills at the top of the card, one list at a time, each with how many; the
    filter beside them filters whichever is shown, and stays where it is
Each fails on 5.47.3. Ports 19288 (the daemon), 19289 (php -S).
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
W = Path(tempfile.mkdtemp(prefix='zigmon-review5474-'))
API_PORT, PHP_PORT = 19288, 19289
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
    print('review5474_parts: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
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

shutil.copytree(os.environ.get('REVIEW5474_WEB') or (HERE / 'web'), W / 'web')
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
  const ctx = await b.newContext({viewport: {width: 1400, height: 900}});
  await ctx.addCookies([{name: 'zigmon_session', value: S, url: 'http://127.0.0.1:' + PORT + '/'}]);
  const p = await ctx.newPage();
  p.errors = [];
  p.on('pageerror', e => p.errors.push(String(e)));
  const shown = () => p.evaluate(() => Array.from(document.querySelectorAll('#tab-sms > [data-sub]'))
    .filter(c => getComputedStyle(c).display !== 'none').map(c => c.getAttribute('data-sub')));
  await p.goto('http://127.0.0.1:' + PORT + '/?a=1#sms');
  await p.waitForTimeout(2500);
  out.smsFirst = await shown();
  out.smsPills = await p.evaluate(() => Array.from(document.querySelectorAll('#sms-parts button')).map(b => b.getAttribute('data-sub')));
  await p.click('#sms-parts button[data-sub="write"]');
  await p.waitForTimeout(300);
  out.smsWrite = await shown();
  out.smsHash = await p.evaluate(() => location.hash);
  await p.screenshot({path: SH + '/sms-write.png'});
  await p.reload();
  await p.waitForTimeout(2500);
  out.smsReloaded = await shown();
  await p.click('#sms-parts button[data-sub="log"]');
  await p.waitForTimeout(300);
  out.smsLog = await shown();
  await p.screenshot({path: SH + '/sms-log.png'});
  // WiFi: the others, drawn from a made-up controller's answer
  await p.goto('http://127.0.0.1:' + PORT + '/?b=1#wifi');
  await p.waitForTimeout(2500);
  out.wifi = await p.evaluate(() => {
    const st = Object.assign({}, STATE.status, {wifi_config: {enabled: true}, wifi_detail: {checked: Date.now() / 1000, aps: [],
      clients: Array.from({length: 70}, (_, i) => ({name: (i %% 2 ? 'Phone-' : 'Light-') + i, mac: 'aa:00:00:00:00:' + (10 + i),
      ip: '192.168.40.' + (10 + i), ssid: 'Home', ap_name: 'AP', band: '5'})), neighbours: Array.from({length: 60}, (_, i) => ({ssid: i %% 3 ? 'Neighbour-' + i : 'Vodafone-' + i,
      bssid: '00:11:22:33:44:' + (10 + i), band: '2.4', channel: 1 + (i %% 11), width: 20, signal: -50 - i,
      security: 'WPA2', seen_by: 'AP'}))}});
    STATE.status = st;
    renderWifiTab(st);
    showWifiSub('others');
    const r = {rows: document.querySelectorAll('#wifi-others .oth-row:not(.head)').length,
               now: document.getElementById('wifi-air-now').textContent,
               findLooks: getComputedStyle(document.getElementById('wifi-seen-find')).borderRadius,
               pagerNow: document.querySelectorAll('#wifi-air-pager button').length};
    const bar = document.querySelector('#wifi-others-card .air-bar'), find = document.getElementById('wifi-seen-find');
    r.findInBar = !!(bar && find && bar.contains(find));
    find.value = 'vodafone';
    find.oninput();
    r.filtered = document.querySelectorAll('#wifi-others .oth-row:not(.head)').length;
    r.count = document.getElementById('wifi-seen-count').textContent;
    const sc = document.querySelector('#wifi-others-card > .list-scroll');
    r.findTop = Math.round(find.getBoundingClientRect().top);
    find.value = ''; find.oninput();
    sc.scrollTop = 9999;
    r.findTopAfter = Math.round(find.getBoundingClientRect().top);
    r.headTop = Math.round(document.querySelector('#wifi-others .oth-row.head').getBoundingClientRect().top);
    r.scTop = Math.round(sc.getBoundingClientRect().top);
    return r;
  });
  await p.screenshot({path: SH + '/wifi-now.png'});
  await p.click('#wifi-air button[data-air="ever"]');
  await p.waitForTimeout(800);
  out.ever = await p.evaluate(() => {
    paintWifiSeen(Array.from({length: 120}, (_, i) => ({ssid: 'Heard-' + i, bssid: 'aa:bb:cc:00:00:' + i, band: '5',
      channel: 36, best: -40 - (i %% 50), times: i, first: Date.now() / 1000 - 86400, last: Date.now() / 1000})));
    const pagerEver = document.querySelector('#wifi-air-pager .pg-info');
    const next = Array.from(document.querySelectorAll('#wifi-air-pager button')).filter(b => /Next/.test(b.textContent))[0];
    if (next) next.click();
    const second = document.querySelector('#wifi-seen .oth-row:not(.head)');
    // On the network: found, and a page at a time
    showWifiSub('clients');
    const cl = {first: document.querySelectorAll('#wifi-client-table .wc-row:not(.head)').length,
                info: (document.querySelector('#wifi-client-pager .pg-info') || {}).textContent || ''};
    const f = document.getElementById('wifi-client-find');
    f.value = 'phone'; f.oninput();
    cl.found = document.querySelectorAll('#wifi-client-table .wc-row:not(.head)').length;
    cl.count = document.getElementById('wifi-client-count').textContent;
    f.value = 'phone 192.168.40.21'; f.oninput();
    cl.one = document.querySelectorAll('#wifi-client-table .wc-row:not(.head)').length;
    f.value = ''; f.oninput();
    showWifiSub('others');
    return {clients: cl, pagerEver: pagerEver ? pagerEver.textContent : '',
            secondPage: second ? second.textContent : '',
            nowHidden: document.getElementById('wifi-others').hidden, everShown: !document.getElementById('wifi-seen-wrap').hidden,
            rows: 50,
            n: document.getElementById('wifi-air-ever').textContent,
            on: Array.from(document.querySelectorAll('#wifi-air button.on')).map(b => b.getAttribute('data-air'))};
  });
  await p.screenshot({path: SH + '/wifi-ever.png'});
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

check(r.get('smsPills') == ['log', 'write'], 'the SMS pills: %r' % r.get('smsPills'))
check(r.get('smsFirst') == ['log'], 'SMS does not open on its messages alone: %r' % r.get('smsFirst'))
check(r.get('smsWrite') == ['write'] and r.get('smsHash') == '#sms/write', 'Write a message: %r %r'
      % (r.get('smsWrite'), r.get('smsHash')))
check(r.get('smsReloaded') == ['write'], 'the part was not kept over a reload: %r' % r.get('smsReloaded'))
check(r.get('smsLog') == ['log'], 'back to the messages: %r' % r.get('smsLog'))
w = r.get('wifi') or {}
check(w.get('rows') == 50 and w.get('now') == '60' and w.get('pagerNow', 0) >= 4,
      'on the air now, a page of 50 and its pages: %r' % w)
check(w.get('findLooks') == '9px', 'the filter is not drawn as the other find boxes are: %r' % w.get('findLooks'))
check(w.get('findInBar'), 'the filter is not in the row at the top of the card')
check(w.get('filtered') == 20 and w.get('count') == '20 of 60 shown', 'the filter over what is on the air now: %r' % w)
check(w.get('findTop') == w.get('findTopAfter'), 'the filter moved with the rows: %r' % w)
check(abs((w.get('headTop') or 0) - (w.get('scTop') or 0)) <= 2, 'the heading row went with the rows: %r' % w)
e = r.get('ever') or {}
check(e.get('pagerEver') == 'page 1 of 3' and 'Heard-50' in (e.get('secondPage') or ''),
      'everything ever heard, a page at a time: %r %r' % (e.get('pagerEver'), (e.get('secondPage') or '')[:40]))
cl = e.get('clients') or {}
check(cl.get('first') == 50 and cl.get('info') == 'page 1 of 2', 'on the network, a page at a time: %r' % cl)
check(cl.get('found') == 35 and cl.get('count') == '35 of 70 shown' and cl.get('one') == 1,
      'on the network, found by its name and its address: %r' % cl)
check(e.get('nowHidden') and e.get('everShown') and e.get('rows') == 50 and e.get('n') == '120'
      and e.get('on') == ['ever'], 'everything ever heard: %r' % e)
check(not r.get('errors'), 'errors on the page: %r' % r.get('errors'))
finish()
