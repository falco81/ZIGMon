#!/usr/bin/env python3
"""5.45: the SSLProxy card - the server in front on the Overview. Fails on
5.44.3 (no such card).

  * the daemon: the card is offered only while the integration is set up and
    switched on (proxy_host, proxy_log, proxy_watch) - off, it is neither in
    the status nor answered by /api/proxy-tile; one batched command over the
    SSH session (stood in for here: the very command run by sh, over a folder
    holding /proc's files, an nginx access log, Suricata's fast.log and
    stats.log, with systemctl, hostname and df faked) parses to the uptime,
    the load, memory and disk, nginx's and Suricata's state, the requests of
    the last hour and how many were refused, the alerts of the last day, the
    worst priority, the packets and drops; a hostile remote string (a
    hostname of markup, a signature of markup, an address that is not one)
    is dropped or kept as plain text; the SSH runs once a minute at most,
    however many pages and threads ask; a failing SSH makes it offline;
    a viewer is answered the counts, never an address or a signature;
  * the page in Chromium (php -S + Playwright): the picker has an SSLProxy
    section naming the card with its icon; added, the card shows the uptime
    as "12 d 3 h", nginx and Suricata active, the counts, its own shield
    icon and ONLINE; removed with x; its detail opens on a click with the
    signatures as text (no markup run); a viewer's page names no address;
    switched off, the card and the option are gone.

    python3 test/review545_proxytile.py

Ports 19280 (the daemon) and 19281 (php -S). Screenshots, with SHOTS=<dir>,
into that folder.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-proxytile-check-'))
API_PORT, PHP_PORT = 19280, 19281
SHOTS = os.environ.get('SHOTS') or ''
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


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
    print('review545_proxytile: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
    os._exit(1 if bad else 0)


# ---- the server in front, as a folder ------------------------------------------
PROC = W / 'proc'
LOGS = W / 'logs'
FAKES = W / 'bin'
for f in (PROC, LOGS, FAKES):
    f.mkdir()
UPTIME = 12 * 86400 + 3 * 3600 + 212                  # 12 d 3 h
(PROC / 'uptime').write_text('%d.55 3340.79\n' % UPTIME)
(PROC / 'loadavg').write_text('0.42 0.31 0.18 1/108 1429\n')
(PROC / 'meminfo').write_text('MemTotal:        4030000 kB\nMemFree:  100 kB\nMemAvailable:    2520000 kB\n')
(W / 'host').write_text('edge-proxy\n')
(W / 'units').write_text('active\n')
(FAKES / 'systemctl').write_text('#!/bin/sh\n[ "$1" = is-active ] && cat %s\nexit 3\n' % (W / 'units'))
(FAKES / 'hostname').write_text('#!/bin/sh\ncat %s\n' % (W / 'host'))
(FAKES / 'df').write_text('#!/bin/sh\necho "Filesystem 1024-blocks Used Available Capacity Mounted on"\n'
                          'echo "/dev/vda1 41152736 12000000 27000000 31% /"\n')
for f in FAKES.iterdir():
    f.chmod(0o755)


def lt(fmt, ago=0):
    return time.strftime(fmt, time.localtime(time.time() - ago))


NOW_NGX = lt('%d/%b/%Y:%H:%M:%S ') + time.strftime('%z')
OLD_NGX = lt('%d/%b/%Y:%H:%M:%S ', 2 * 3600) + time.strftime('%z')
# five requests in the last hour - two closed with 444, one 404, one 200, one
# 502 - and one from two hours ago that is not counted
ACCESS = ''.join('%s - - [%s] "%s" %s 0 "-" "curl/8"\n' % (ip, when, req, code) for ip, when, req, code in (
    ('198.51.100.7', NOW_NGX, 'GET / HTTP/1.1', 444),
    ('198.51.100.7', NOW_NGX, 'GET /wp-login.php HTTP/1.1', 444),
    ('203.0.113.9', NOW_NGX, 'GET /a b HTTP/1.1', 404),
    ('192.0.2.50', NOW_NGX, 'GET /tap HTTP/1.1', 200),
    ('192.0.2.50', NOW_NGX, 'GET /tap HTTP/1.1', 502),
    ('198.51.100.7', OLD_NGX, 'GET / HTTP/1.1', 444)))
(LOGS / 'zigmon-tap.log').write_text(ACCESS)
HOSTILE = '<img src=x onerror="window.__pwn=1">ET EVIL'
NOW_FAST = lt('%m/%d/%Y-%H:%M:%S')
OLD_FAST = lt('%m/%d/%Y-%H:%M:%S', 2 * 86400)
FAST = ''.join('%s.123456  [**] [1:%d:3] %s [**] [Classification: Misc Attack] [Priority: %d] {TCP} %s:5555 -> 10.0.0.1:443\n'
               % (when, sid, msg, prio, src) for when, sid, msg, prio, src in (
                   (NOW_FAST, 2400015, 'ET DROP Spamhaus DROP Listed Traffic Inbound', 2, '45.1.2.3'),
                   (NOW_FAST, 2400015, 'ET DROP Spamhaus DROP Listed Traffic Inbound', 2, '45.1.2.3'),
                   (NOW_FAST, 2010935, 'ET SCAN Suspicious inbound to MSSQL port 1433', 3, '45.9.8.7'),
                   (NOW_FAST, 2999999, HOSTILE, 1, 'not;an-address'),
                   (OLD_FAST, 2100498, 'GPL ATTACK_RESPONSE old one', 1, '1.1.1.1')))
(LOGS / 'fast.log').write_text(FAST)
(LOGS / 'stats.log').write_text(
    '-' * 60 + '\nDate: 11/6/2026 -- 22:13:27 (uptime: 3d, 05h 12m 03s)\n' + '-' * 60 + '\n'
    'capture.kernel_packets                        | Total                     | 1234567\n'
    'capture.kernel_drops                          | Total                     | 89\n'
    'decoder.pkts                                  | Total                     | 1234560\n')
(LOGS / 'eve.json').write_text('')

CALLS = []
FAIL = [False]
SLOW = [0.0]


def fake_run(command):
    """The SSH session: the command as it would go, run by sh over the folder."""
    CALLS.append(command)
    if SLOW[0]:
        time.sleep(SLOW[0])
    if FAIL[0]:
        raise RuntimeError('proxy.house.example did not answer within 20 s')
    cmd = command.replace('/proc/', str(PROC) + '/')
    return subprocess.run(['sh', '-c', cmd], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          env=dict(os.environ, PATH='%s:%s' % (FAKES, os.environ['PATH']))).stdout


# ---- the daemon ----------------------------------------------------------------
print('the daemon')
sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                                # noqa: E402

if not hasattr(zigmon, 'proxy_tile_state'):
    check(False, 'there is no SSLProxy card in this version (no proxy_tile_state)')
    finish()
zigmon.load_config()
DSTATE = W / 'dstate'
DSTATE.mkdir()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'log_file': '', 'state_dir': str(DSTATE), 'proxy_host': '', 'proxy_watch': 0,
                      'proxy_log': str(LOGS / 'zigmon-tap.log'), 'suricata_log': str(LOGS / 'eve.json'),
                      'proxy_auth': 'key'})
d = zigmon.Daemon()
d.notify = lambda message, *a, **k: None
d.proxy_run = fake_run
for i in range(14):
    d.store.upsert_device({'id': '0x00%02d' % i, 'name': 'Temp-%02d' % i, 'source': 'zigbee', 'kind': 'EndDevice',
                           'model': 'SNZB-02', 'vendor': 'SONOFF', 'last_seen': int(time.time())})
d.save_overview_layout(['0x0000', '0x0001'])


def wait_runs(n, most=10.0):
    end = time.time() + most
    while time.time() < end and int(d.__dict__.get('_proxy_tile_runs') or 0) < n:
        time.sleep(0.05)
    time.sleep(0.05)
    return int(d.__dict__.get('_proxy_tile_runs') or 0)


print('  off: nothing offered, nothing asked')
check(zigmon.proxy_tile_state(d) == {'on': False} and not d.status()['proxy_tile']['on'],
      'the card is offered with no server in front set up')
zigmon.CONFIG['proxy_host'] = 'proxy.house.example'
check(zigmon.proxy_tile_state(d) == {'on': False} and not d.status()['proxy_tile']['on'],
      'the card is offered with the reading of the server in front switched off')
check(not CALLS, 'the server in front was asked with the integration off: %r' % CALLS[:1])
zigmon.CONFIG['proxy_watch'] = 1
check(d.status()['proxy_tile']['on'], 'the card is not offered with the integration on')

print('  one look, parsed')
first = zigmon.proxy_tile_state(d)
check(first.get('on') and first.get('state') in ('waiting', 'online'), 'the first answer: %r' % first)
wait_runs(1)
t = zigmon.proxy_tile_state(d, admin=True)
ngx, sur = t.get('nginx') or {}, t.get('suricata') or {}
check(len(CALLS) == 1, 'one look ran %d SSH commands, not one' % len(CALLS))
check(t.get('state') == 'online' and t.get('name') == 'edge-proxy', 'the look: %r' % t)
check(t.get('uptime_s') == UPTIME and t.get('load') == [0.42, 0.31, 0.18], 'uptime and load: %r %r'
      % (t.get('uptime_s'), t.get('load')))
check(t.get('mem_avail_kb') == 2520000 and t.get('mem_total_kb') == 4030000 and t.get('disk_avail_kb') == 27000000,
      'memory and disk: %r' % t)
check(ngx.get('state') == 'active' and ngx.get('hour') == 5 and ngx.get('refused') == 3 and ngx.get('closed') == 2
      and ngx.get('server_errors') == 1, 'nginx: %r' % ngx)
check(sur.get('state') == 'active' and sur.get('alerts') == 4 and sur.get('worst') == 1
      and sur.get('packets') == 1234567 and sur.get('drops') == 89 and sur.get('uptime_s') == 3 * 86400 + 5 * 3600 + 12 * 60 + 3,
      'suricata: %r' % sur)
tops = sur.get('top') or []
check(tops and tops[0].get('n') == 2 and 'Spamhaus' in tops[0].get('msg', '') and tops[0].get('priority') == 2,
      'the top signature: %r' % tops)
check(any(x.get('msg') == HOSTILE for x in tops), 'a signature of markup was not kept as text: %r' % tops)
check([x.get('ip') for x in sur.get('sources') or []] == ['45.1.2.3', '45.9.8.7'],
      'the sources alerted on (an address that is not one dropped): %r' % sur.get('sources'))
check([x.get('ip') for x in ngx.get('top') or []][:1] == ['198.51.100.7'], 'refused most: %r' % ngx.get('top'))
check(t.get('host') == 'proxy.house.example', 'an administrator is not told the address: %r' % t.get('host'))
cmd = CALLS[0]
check(cmd.count('ssh') == 0 and 'tail -c 2000000' in cmd and 'head -c 65536' in cmd and 'systemctl is-active' in cmd,
      'the command is not the one small bounded batch: %s' % cmd[:200])

print('  a viewer: counts, never an address or a signature')
v = zigmon.proxy_tile_state(d, admin=False)
vs = json.dumps(v)
check(v.get('nginx', {}).get('hour') == 5 and v.get('suricata', {}).get('alerts') == 4, 'a viewer has no counts: %r' % v)
check(not any(x in vs for x in ('proxy.house.example', '45.1.2.3', '198.51.100.7', 'Spamhaus', 'EVIL')),
      'a viewer is told addresses or signatures: %s' % vs)

print('  hostile remote text')
hostile = ('ZTILE-x up\n9e99 1\nZTILE-x load\n1e9 -1 x\nZTILE-x host\n<script>alert(1)</script>\n'
           'ZTILE-x svc\nnginx $(reboot)\nsuricata active\nZTILE-x nginx\nN 1 2 3\nA 5 1.2.3.4;rm\n'
           'ZTILE-x fast\nN -4 x\nS 3 1|\x1b[31m<b>red</b>' + 'y' * 900 + '\n' + 'ZTILE-x stats\n' * 900)
hp = zigmon.proxy_tile_parse(hostile, 'ZTILE-x')
check(hp['uptime_s'] is None and hp['load'] is None and hp['hostname'] == '' and hp['nginx']['state'] == 'unknown'
      and hp['nginx']['hour'] is None and hp['nginx']['top'] == [] and hp['suricata']['alerts'] is None,
      'hostile remote text was taken at its word: %r' % hp)
msg = (hp['suricata']['top'] or [{}])[0].get('msg', '')
check('\x1b' not in msg and len(msg) <= 160, 'a remote signature was not cut down and cleaned: %r' % msg[:60])
check(zigmon.proxy_tile_parse('ZTILE-y host\n10.0.0.5\n', 'ZTILE-y')['hostname'] == '',
      'a hostname that is an address would be shown to everybody')

print('  once a minute, however many ask')
threads = [threading.Thread(target=lambda: [zigmon.proxy_tile_state(d) for _ in range(20)]) for _ in range(10)]
[x.start() for x in threads]
[x.join() for x in threads]
time.sleep(0.3)
check(len(CALLS) == 1, '200 askings within the minute ran %d SSH commands' % len(CALLS))
SLOW[0] = 0.6
d._proxy_tile_look = dict(d._proxy_tile_look, at=time.time() - 61, tried=time.time() - 61)
d._proxy_tile_started = time.time() - 61
threads = [threading.Thread(target=lambda: [zigmon.proxy_tile_state(d) for _ in range(20)]) for _ in range(10)]
[x.start() for x in threads]
[x.join() for x in threads]
wait_runs(2)
SLOW[0] = 0.0
check(len(CALLS) == 2, 'a minute later, 200 askings ran %d SSH commands, not one' % len(CALLS))
# (5.46) a device with a history: read whenever it is set up, card or no card
check(zigmon.proxy_tile_wanted(d) is True, 'the clock would not read the server in front without its card')

print('  offline when SSH fails')
FAIL[0] = True
d._proxy_tile_look = dict(d._proxy_tile_look, at=time.time() - 61, tried=time.time() - 61)
d._proxy_tile_started = time.time() - 61
zigmon.proxy_tile_state(d)
wait_runs(3)
off_admin = zigmon.proxy_tile_state(d, admin=True)
off_view = zigmon.proxy_tile_state(d)
check(off_admin.get('state') == 'offline' and 'did not answer' in (off_admin.get('error') or '')
      and 'proxy.house.example' in off_admin.get('error', ''), 'a failing SSH is not offline: %r' % off_admin)
check(off_view.get('state') == 'offline' and 'proxy.house.example' not in json.dumps(off_view),
      'a viewer is told the address in the error: %r' % off_view)
check(len(CALLS) == 3, 'the failing look was retried at once: %d' % len(CALLS))
FAIL[0] = False
d._proxy_tile_look = dict(d._proxy_tile_look, at=time.time() - 61, tried=time.time() - 61)
d._proxy_tile_started = time.time() - 61
zigmon.proxy_tile_state(d)
wait_runs(4)
check(zigmon.proxy_tile_state(d).get('state') == 'online', 'it did not come back online')

print('  the layout keeps it, in its place')
got = d.save_overview_layout(['0x0000', 'proxy:front', '0x0001'])
check(got == ['0x0000', 'proxy:front', '0x0001'], 'the layout does not keep the card in its place: %r' % got)
check(zigmon.proxy_tile_wanted(d), 'the clock would not look for the card on the Overview')
d.save_overview_layout(['0x0000', '0x0001'])

# ---- over HTTP and in the page -------------------------------------------------
print('the API and the page')
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


def get(path, session=''):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path),
                                 headers={'X-Zigmon-Token': d.token, 'X-Zigmon-Session': session,
                                          'X-Zigmon-Client': '192.168.40.10'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


try:
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    d.account_add('watcher', 'viewer', 'watcher pass 12', must_change=False, quiet=True)
    S_ADMIN = login('owner', 'owner pass 12')
    S_VIEW = login('watcher', 'watcher pass 12')
    before = len(CALLS)
    answers = []
    ths = [threading.Thread(target=lambda: answers.append(get('/api/proxy-tile', S_VIEW))) for _ in range(20)]
    [x.start() for x in ths]
    [x.join() for x in ths]
    check(len(answers) == 20 and len(CALLS) == before, '20 pages asking at once ran %d SSH commands'
          % (len(CALLS) - before))
    va = json.dumps(answers[0])
    check(answers[0].get('state') == 'online' and '45.1.2.3' not in va and 'proxy.house.example' not in va
          and 'Spamhaus' not in va, 'a viewer over HTTP: %s' % va[:300])
    aa = get('/api/proxy-tile', S_ADMIN)
    check('45.1.2.3' in json.dumps(aa) and aa.get('host') == 'proxy.house.example',
          'an administrator over HTTP has no details: %r' % aa)

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
    shots = W / 'shots'
    shots.mkdir()
    js = r'''
const { chromium } = require('playwright');
const S = %(s)s, V = %(v)s, PORT = %(port)d, SH = %(shots)s;
async function open(b, session, width) {
  const ctx = await b.newContext({viewport: {width: width, height: 1000}});
  await ctx.addCookies([{name: 'zigmon_session', value: session, url: 'http://127.0.0.1:' + PORT + '/'}]);
  const p = await ctx.newPage();
  p.errors = [];
  p.on('pageerror', e => p.errors.push(String(e)));
  await p.goto('http://127.0.0.1:' + PORT + '/#overview');
  await p.waitForSelector('#overview-custom .card', {timeout: 20000});
  return p;
}
(async () => {
  const b = await chromium.launch();
  const r = {};
  const p = await open(b, S, 1600);
  await p.waitForTimeout(1500);
  r.groups = await p.evaluate(() => Array.from(document.querySelectorAll('#ov-add-select optgroup')).map(g => [g.label,
    Array.from(g.querySelectorAll('option')).map(o => [o.value, o.textContent])]));
  r.svg = await p.evaluate(() => (ICONS.sslproxy || '').length);
  // the list open on its SSLProxy section: a native list is not drawn in a
  // screenshot, so it is shown as a list box for the picture
  await p.evaluate(() => { const s = document.getElementById('ov-add-select'); s.size = 16; s.style.height = '330px';
    const o = s.querySelector('option[value="proxy:front"]'); if (o) { o.selected = true; o.scrollIntoView({block: 'center'}); } });
  await p.waitForTimeout(300);
  await p.screenshot({path: SH + '/picker-sslproxy.png', clip: {x: 0, y: 380, width: 1000, height: 420}});
  await p.evaluate(() => { const s = document.getElementById('ov-add-select'); s.size = 0; s.style.height = ''; });
  await p.selectOption('#ov-add-select', 'proxy:front');
  await p.click('#ov-add-btn');
  try { await p.waitForSelector('#overview-custom .proxy-tile .tag.ok', {timeout: 20000}); } catch (e) { r.waitErr = String(e); }
  await p.waitForTimeout(800);
  r.card = await p.evaluate(() => { const c = document.querySelector('#overview-custom .proxy-tile'); if (!c) return null;
    return {text: c.innerText, tag: (c.querySelector('.tag') || {}).textContent, icon: ((c.querySelector('.name .dev-ic') || {}).textContent || '').indexOf('\ud83d\udee1') === 0 ? 2 : 0,
            values: Array.from(c.querySelectorAll('.reading')).map(x => [x.querySelector('.l').textContent, x.querySelector('.v').textContent])}; });
  r.optionGone = await p.evaluate(() => !document.querySelector('#ov-add-select option[value="proxy:front"]'));
  const card = await p.$('#overview-custom .proxy-tile');
  if (card) { await card.scrollIntoViewIfNeeded(); await card.screenshot({path: SH + '/card-1600.png'}); }
  await p.screenshot({path: SH + '/overview-1600.png'});
  if (card) {
    await card.click({position: {x: 60, y: 140}});
    try { await p.waitForSelector('#zmodal:not([hidden]) .pt-detail', {timeout: 8000}); } catch (e) { r.modalErr = String(e); }
    r.modal = await p.evaluate(() => ({text: (document.getElementById('zmodal-body') || {}).innerText || '',
      imgs: document.querySelectorAll('#zmodal-body img').length, pwn: window.__pwn === 1}));
    await p.screenshot({path: SH + '/detail-admin.png'});
    await p.click('#zmodal-x');
  }
  // removed with its x, and back on the list
  try {
    await p.click('#overview-custom .proxy-tile .ov-remove');
    await p.waitForTimeout(1200);
    r.removed = await p.evaluate(() => !document.querySelector('#overview-custom .proxy-tile')
      && !!document.querySelector('#ov-add-select option[value="proxy:front"]'));
  } catch (e) { r.removeErr = String(e); }
  // ...and put back, for the viewer's Overview
  try { await p.selectOption('#ov-add-select', 'proxy:front'); await p.click('#ov-add-btn'); await p.waitForTimeout(1200); }
  catch (e) { r.readdErr = String(e); }
  r.errors = p.errors;
  // a phone, and a viewer
  const q = await open(b, V, 420);
  try { await q.waitForSelector('#overview-custom .proxy-tile .tag.ok', {timeout: 20000}); } catch (e) { r.viewWait = String(e); }
  await q.waitForTimeout(800);
  r.view = await q.evaluate(() => { const c = document.querySelector('#overview-custom .proxy-tile');
    return {card: c ? c.innerText : null, width: document.documentElement.scrollWidth, picker: !document.getElementById('ov-add-row').hidden}; });
  const qc = await q.$('#overview-custom .proxy-tile');
  if (qc) { await qc.scrollIntoViewIfNeeded(); await q.screenshot({path: SH + '/card-420.png'});
    await qc.click({position: {x: 40, y: 140}});
    try { await q.waitForSelector('#zmodal:not([hidden]) .pt-detail', {timeout: 8000}); } catch (e) { r.vmodalErr = String(e); }
    r.vmodal = await q.evaluate(() => (document.getElementById('zmodal-body') || {}).innerText || '');
    await q.screenshot({path: SH + '/detail-viewer-420.png'}); }
  r.verrors = q.errors;
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
    (W / 'page.js').write_text(js % {'s': json.dumps(S_ADMIN), 'v': json.dumps(S_VIEW), 'port': PHP_PORT,
                                     'shots': json.dumps(str(shots))})
    root = sh(['npm', 'root', '-g']).stdout.strip()
    node_env = dict(os.environ, NODE_PATH=root)

    def run_page(script):
        got = sh(['node', str(script)], timeout=240, env=node_env)
        try:
            return json.loads(got.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return {'error': (got.stdout + got.stderr)[-400:]}

    r = run_page(W / 'page.js')
    if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
        print('  SKIPPED (no browser here): %s' % r['error'][:200])
    else:
        check(not r.get('error'), 'the page in Chromium: %s' % r.get('error'))
        groups = dict((g[0], g[1]) for g in r.get('groups') or [])
        check('SSLProxy' in groups and [o[0] for o in groups['SSLProxy']] == ['proxy:front'],
              'the picker has no SSLProxy section with the card: %r' % list(groups))
        if 'SSLProxy' in groups:
            check(groups['SSLProxy'][0][1].startswith('\U0001f6e1') and 'edge-proxy' in groups['SSLProxy'][0][1],
                  'the SSLProxy option has not its icon and name: %r' % groups['SSLProxy'])
        check(r.get('svg', 0) > 40, 'there is no SSLProxy drawing among the icons')
        c = r.get('card') or {}
        vals = dict((k.lower(), v) for k, v in c.get('values') or [])
        check(c and c.get('tag') == 'online' and c.get('icon', 0) >= 2, 'the card on the Overview: %r %r' % (c, r.get('waitErr')))
        check(vals.get('uptime') == '12 d 3 h', 'the uptime on the card: %r' % vals)
        check(vals.get('nginx') == 'active' and vals.get('suricata') == 'active', 'nginx and Suricata on the card: %r' % vals)
        check(vals.get('requests, 1 h') == '5' and vals.get('refused, 1 h') == '3' and vals.get('alerts, 24 h') == '4',
              'the counts on the card: %r' % vals)
        check('proxy.house.example' in (c.get('text') or ''), 'an administrator\'s card does not name the server')
        check(r.get('optionGone'), 'the card stayed on the list once added')
        m = r.get('modal') or {}
        check('Spamhaus' in (m.get('text') or '') and '45.1.2.3' in (m.get('text') or '') and '<img' in (m.get('text') or ''),
              'the detail does not show the signatures and the sources as text: %r %r' % ((m.get('text') or '')[:300], r.get('modalErr')))
        check(m and not m.get('imgs') and not m.get('pwn'), 'a remote string ran as markup in the detail: %r' % m)
        check(r.get('removed'), 'the card is not removed by its x: %r' % r.get('removeErr'))
        check(not r.get('errors'), 'the administrator\'s page threw: %r' % r.get('errors'))
        vw = r.get('view') or {}
        vtext = (vw.get('card') or '') + (r.get('vmodal') or '')
        check(vw.get('card') and '12 d 3 h' in vw['card'], 'the viewer\'s card at 420: %r %r' % (vw, r.get('viewWait')))
        check(vw.get('width', 9999) <= 420, 'the phone\'s page is wider than the screen: %r' % vw.get('width'))
        check(not any(x in vtext for x in ('proxy.house.example', '45.1.2.3', '198.51.100.7', 'Spamhaus', 'EVIL')),
              'a viewer\'s page names an address or a signature: %r' % vtext[:400])
        check('4' in (r.get('vmodal') or '') and 'administrator' in (r.get('vmodal') or ''),
              'the viewer\'s detail has no counts: %r %r' % ((r.get('vmodal') or '')[:200], r.get('vmodalErr')))
        check(not r.get('verrors'), 'the viewer\'s page threw: %r' % r.get('verrors'))

        print('  switched off: gone from the Overview and the list')
        zigmon.CONFIG['proxy_watch'] = 0
        d.bump()
        js2 = r'''
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({viewport: {width: 1600, height: 1000}});
  await ctx.addCookies([{name: 'zigmon_session', value: %(s)s, url: 'http://127.0.0.1:%(port)d/'}]);
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.goto('http://127.0.0.1:%(port)d/#overview');
  await p.waitForSelector('#overview-custom .card', {timeout: 20000});
  await p.waitForTimeout(2500);
  const r = await p.evaluate(() => ({card: !!document.querySelector('#overview-custom .proxy-tile'),
    option: !!document.querySelector('#ov-add-select option[value="proxy:front"]'),
    group: Array.from(document.querySelectorAll('#ov-add-select optgroup')).some(g => g.label === 'SSLProxy'),
    cards: document.querySelectorAll('#overview-custom > .card').length}));
  r.errors = errors;
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
        (W / 'off.js').write_text(js2 % {'s': json.dumps(S_ADMIN), 'port': PHP_PORT})
        n0 = len(CALLS)
        o = run_page(W / 'off.js')
        check('proxy:front' in (d.overview_layout() or []), 'the layout lost the card\'s place while it was off')
        check(not o.get('error') and o.get('card') is False and o.get('option') is False and o.get('group') is False
              and o.get('cards', 0) >= 2, 'switched off, the card or its option is still there: %r' % o)
        check(len(CALLS) == n0, 'switched off, the server in front was still asked')
        check(not o.get('errors'), 'the page threw with the card switched off: %r' % o.get('errors'))
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            for f in shots.iterdir():
                shutil.copy(f, Path(SHOTS) / f.name)
finally:
    try:
        api.stop()
    except Exception:                                        # noqa: BLE001
        pass

finish()
