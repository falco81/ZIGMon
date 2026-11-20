#!/usr/bin/env python3
"""Bug hunt D (5.55.x): the Settings panes that are drawn again by themselves.

Upgrades (every 8 s), Automatic certificates (every 15 s) and SELinux (every
30 s, every 2 s while root is at it) are built anew each time their timer
asks. A fold in them opened to be read - "What changed in <the version
waiting>", "N older version(s) it may not go back to", "What the last order
did", "What was refused (N)" - snapped shut under the reader at the next
draw, as install.sh's lines once did (UP.tailOpen). Each fold is opened here,
the pane drawn again as its timer draws it, and the fold must still be open;
closed again, it must stay closed; and a fold nobody touched stays as it is
drawn (shut).

The panes' answers are made up in the browser (the daemon's own roads are not
what is tested): the page is the real one, through php -S and the daemon.

    python3 test/review556_hunt_d.py < /dev/null

Ports 20510 (the daemon), 20511 (php -S).
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
W = Path(tempfile.mkdtemp(prefix='zigmon-review556d-'))
API_PORT, PHP_PORT = 20510, 20511
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
            os.killpg(p.pid, 15)
        except OSError:
            pass
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    try:
        api.stop()
    except Exception:                                        # noqa: BLE001
        pass
    shutil.rmtree(W, ignore_errors=True)
    print('review556_hunt_d: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
    sys.stdout.flush()
    os._exit(1 if bad else 0)


sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                                # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'log_file': '', 'state_dir': str(W / 'state'), 'preheat': False})
(W / 'state').mkdir()
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)

d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
req = urllib.request.Request('http://127.0.0.1:%d/api/auth/login' % API_PORT,
                             data=json.dumps({'name': 'owner', 'password': 'owner pass 12'}).encode(),
                             headers={'X-Zigmon-Token': d.token, 'Content-Type': 'application/json',
                                      'X-Zigmon-Client': '192.168.40.10'}, method='POST')
with urllib.request.urlopen(req, timeout=30) as r:
    S_ADMIN = json.loads(r.read()).get('token') or ''
check(S_ADMIN, 'the administrator could not sign in')

npm_root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()
if not (Path(npm_root) / 'playwright').exists() or not shutil.which('php'):
    print('  SKIPPED (no browser or php here)')
    finish()
try:
    socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
    check(False, 'port %d is taken by something else' % PHP_PORT)
    finish()
except OSError:
    pass
shutil.copytree(HERE / 'web', W / 'web')
api_php = (W / 'web' / 'zigmon-api.php').read_text()
api_php = api_php.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
api_php = api_php.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
(W / 'web' / 'zigmon-api.php').write_text(api_php)
php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, str(W / 'web' / 'index.php')], cwd=str(W / 'web'),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                       env=dict(os.environ, PHP_CLI_SERVER_WORKERS='4'), start_new_session=True)
PROCS.append(php)
for _ in range(50):
    try:
        socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
        break
    except OSError:
        time.sleep(0.1)

NOW = int(time.time())
ANSWERS = {
    'upgrade': {'ok': True, 'helper': True, 'version': '5.55.1', 'node': 'vm',
                'nodes': [{'name': 'vm', 'me': True, 'version': '5.55.1', 'at': NOW}],
                'package': {'version': '5.56.0', 'signed_by': 'zigmon', 'bytes': 900000, 'by': 'owner',
                            'at': NOW - 60, 'changelog': '5.56.0\n  * one thing\n  * another'},
                'web': {'url': 'https://example.invalid/zigmon/', 'online': {
                    'at': NOW - 30, 'here': '5.55.1',
                    'older_list': [{'version': '5.54.0', 'ok': True},
                                   {'version': '5.20.0', 'ok': False, 'why': 'older than the database'}]}},
                'back': {'on': True, 'floor': '5.21.0'}, 'status': {}, 'log': []},
    'acme': {'ok': True, 'helper': True, 'on': True, 'challenge': 'http-01', 'node': 'vm',
             'targets': [{'target': 'web', 'how': 'ACME', 'wanted': True, 'care': True, 'name': 'house.example',
                          'not_after': NOW + 60 * 86400,
                          'state': {'ok': True, 'ordered_at': NOW - 3600,
                                    'steps': [[NOW - 3700, 'asked the CA'], [NOW - 3690, 'the CA said yes']]}}]},
    'selinux': {'ok': True, 'helper': True, 'node': 'vm', 'at': NOW,
                'state': {'mode': 'Permissive', 'config': 'permissive', 'module': True,
                          'denials': {'tool': True, 'total': 2, 'groups': [
                              {'count': 2, 'source': 'httpd_t', 'target': 'var_t', 'class': 'file',
                               'perms': 'read', 'what': '/var/x'}]}}},
}

js = r'''
const { chromium } = require('playwright');
const job = __JOB__;
(async () => {
  const b = await chromium.launch();
  const out = {errors: [], panes: {}};
  const ctx = await b.newContext({viewport: {width: 1200, height: 1000}});
  await ctx.addCookies([{name: 'zigmon_session', value: job.admin, url: 'http://127.0.0.1:' + job.port + '/'}]);
  const p = await ctx.newPage();
  p.setDefaultTimeout(10000);
  p.on('pageerror', e => out.errors.push(String(e)));
  p.on('dialog', dl => { out.errors.push('dialog: ' + dl.message()); dl.dismiss().catch(() => {}); });
  await p.route(/\?api=/, route => {
    const u = new URL(route.request().url());
    const what = u.searchParams.get('api');
    if (route.request().method() === 'GET' && job.answers[what])
      return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(job.answers[what])});
    return route.continue();
  });
  await p.goto('http://127.0.0.1:' + job.port + '/#control');
  await p.waitForTimeout(1500);
  // sec: the pane; sel: the fold; again: the pane drawn again, as its timer does it
  const panes = [
    {name: 'upgrade changelog', sec: 'sys-upgrade', sel: '#up-pkg details.zfold', again: 'loadUpgrade(true)'},
    {name: 'versions it may not go back to', sec: 'sys-upgrade', sel: '#up-back details.zfold', again: 'loadUpgrade(true)'},
    {name: 'what the last order did', sec: 'sys-acme', sel: '#ac-host details.acme-steps-done', again: 'loadAcme(true)'},
    {name: 'what SELinux refused', sec: 'sec-selinux', sel: '#se-avc', again: 'loadSelinux(true)'},
  ];
  const isOpen = sel => p.evaluate(s => { const e = document.querySelector(s); return e ? e.open : null; }, sel);
  for (const x of panes) {
    const r = {};
    await p.evaluate(s => { showTab('control'); showControlSection(s); }, x.sec);
    await p.waitForSelector(x.sel, {state: 'attached'});
    r.drawn = await isOpen(x.sel);
    await p.evaluate(a => eval(a), x.again); await p.waitForTimeout(700);
    r.untouched = await isOpen(x.sel);
    await p.locator(x.sel + ' > summary').first().scrollIntoViewIfNeeded();
    await p.locator(x.sel + ' > summary').first().click();
    await p.waitForTimeout(200);
    r.clicked = await isOpen(x.sel);
    await p.evaluate(a => eval(a), x.again); await p.waitForTimeout(700);
    r.again = await isOpen(x.sel);
    await p.evaluate(a => eval(a), x.again); await p.waitForTimeout(700);
    r.twice = await isOpen(x.sel);
    await p.locator(x.sel + ' > summary').first().click();
    await p.waitForTimeout(200);
    await p.evaluate(a => eval(a), x.again); await p.waitForTimeout(700);
    r.shutAgain = await isOpen(x.sel);
    out.panes[x.name] = r;
  }
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { console.log(JSON.stringify({fatal: String(e)})); process.exit(0); });
'''
(W / 'page.js').write_text(js.replace('__JOB__', json.dumps({'port': PHP_PORT, 'admin': S_ADMIN,
                                                               'answers': ANSWERS})))
print('folds of the panes drawn again by themselves stay as they were left')
try:
    run = subprocess.run(['node', str(W / 'page.js')], capture_output=True, text=True, timeout=300,
                         env=dict(os.environ, NODE_PATH=npm_root), stdin=subprocess.DEVNULL)
except subprocess.TimeoutExpired:
    check(False, 'the browser did not finish')
    finish()
lines = [x for x in run.stdout.splitlines() if x.startswith('{')]
out = json.loads(lines[-1]) if lines else {'fatal': run.stdout[-500:] + run.stderr[-1500:]}
check('fatal' not in out, 'the browser stopped: %s' % out.get('fatal'))
check(not out.get('errors'), 'the page threw: %s' % out.get('errors'))
for name in ('upgrade changelog', 'versions it may not go back to', 'what the last order did',
             'what SELinux refused'):
    r = (out.get('panes') or {}).get(name)
    if not check(r, '%s: not measured' % name):
        continue
    check(r['drawn'] is False and r['untouched'] is False,
          '%s: not drawn shut, or opened by itself: %s' % (name, r))
    check(r['clicked'] is True, '%s: a click did not open it: %s' % (name, r))
    check(r['again'] is True and r['twice'] is True,
          '%s: opened, it snapped shut when the pane was drawn again: %s' % (name, r))
    check(r['shutAgain'] is False, '%s: shut again, it came back open: %s' % (name, r))
finish()
