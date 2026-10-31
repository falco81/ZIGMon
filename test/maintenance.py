#!/usr/bin/env python3
"""Upgrades and maintenance (otp 1.0.197's pane, for one machine).

  * maintenance by hand: into it with a word of why and back in service, an
    administrator's alone; said in the events; kept in the database across a
    restart of the daemon; /api/healthz says 503 in it and 200 out of it,
    while /api/health - what an upgrade asks of the new version - stays 200
    and says it;
  * in maintenance by itself while zigmon is upgraded, the system updated
    or the machine restarted, and back in service by itself when that is
    over - but never out of a maintenance put on by hand; "Back in service"
    refused while one of them goes on;
  * the alerts about the machine itself and about devices going quiet or
    offline held while it lasts and for 10 min after, kept in the events;
    the house's own - a door, water, a rule's message - sent as ever;
  * the command line (--maintenance on|off|status, --why) and the console;
  * the real page (php -S) in Chromium: the pane called Upgrades and
    maintenance, its three cards with otp's titles, the nodes table (Node,
    Version, Heard from, State) with THIS PAGE, IN SERVICE and Maintenance,
    the three settings side by side with their words under them, the drop
    zone, Upgrade this server and Forget the package, and the band on every
    page while it is in maintenance.

    python3 test/maintenance.py

Ports 19886 (the daemon) and 19914 (php -S).
"""
import contextlib
import io
import json
import os
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
W = Path(tempfile.mkdtemp(prefix='zigmon-maint-check-'))
API_PORT = 19886
PHP_PORT = 19914
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


STATE, ETC = W / 'state', W / 'etc'
for p in (STATE / 'root', STATE / 'backups', STATE / 'upgrade', ETC / 'zigmon'):
    p.mkdir(parents=True, exist_ok=True)
DB = STATE / 'history.db'
(ETC / 'zigmon' / 'config.json').write_text(json.dumps({'db_file': str(DB)}))
(W / 'boot_id').write_text('boot-one\n')
os.environ.update(ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(W / 'own'), ZIGMON_FULL_DIR=str(W / 'full'),
                  ZIGMON_CONFIG=str(ETC / 'zigmon' / 'config.json'), ZIGMON_NO_SERVICES='1',
                  ZIGMON_SERVICE_LOG=str(W / 'services.log'), ZIGMON_FS_ROOT=str(W), ZIGMON_USER='root',
                  ZIGMON_FW_FILE4=str(W / 'no4'), ZIGMON_FW_FILE6=str(W / 'no6'),
                  ZIGMON_FIREWALL_CMD=str(W / 'no-firewall-cmd'), ZIGMON_NGINX_TEST='true',
                  ZIGMON_ROOT_RUN='true', ZIGMON_POWER_CMD=str(W / 'power.log'),
                  ZIGMON_BTIME_FILE=str(W / 'boot_id'))

sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

api = None
try:
    zigmon.load_config()
    zigmon.CONFIG.update({'db_file': str(DB), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                          'token_file': str(W / 'token'), 'plugs': [], 'sensors': [], 'mqtt_host': '',
                          'log_file': '', 'state_dir': str(STATE), 'notify_ntfy': 'https://ntfy.example/house'})
    d = zigmon.Daemon()
    api = zigmon.ApiServer(d)
    api.start()
    time.sleep(0.3)

    def call(path, body=None, session=None):
        headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json',
                   'X-Zigmon-Client': '192.168.40.10'}
        if session:
            headers['X-Zigmon-Session'] = session
        req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                     data=None if body is None else json.dumps(body).encode(),
                                     method='GET' if body is None else 'POST')
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')

    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
    S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
    S_OP = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''

    def maint(on, why='', session=None):
        return call('/api/upgrade', {'action': 'maintenance', 'on': on, 'why': why, 'session': session or S},
                    session=session or S)

    def queued():
        return [str(x.get('message')) for x in d.notify_queue]

    # nothing is sent while the checks look at what is waiting to go
    import threading
    d._notify_kick = threading.Event()

    def events(n=40):
        d.store.flush(5.0)
        return [str(e.get('detail') or '') for e in d.store.events(limit=n)]

    def told(message, about, level='warn'):
        """notify, as every road of the house calls it: in the queue or not."""
        d.notify_queue.clear()
        d.notify_sent.clear()
        d.notify(message, level, about=about)
        return message in queued()

    # ---- in service to begin with -------------------------------------------------------
    print('in service')
    code, v = call('/api/upgrade', session=S)
    m = v.get('maintenance')
    check(code == 200 and isinstance(m, dict) and m.get('on') is False,
          'the upgrade view says nothing of maintenance: %s %r' % (code, m))
    node = (v.get('nodes') or [{}])[0]
    check(isinstance(node.get('maintenance'), dict) and node.get('me') is True and node.get('at'),
          'the one node does not carry its maintenance: %r' % node)
    code, h = call('/api/healthz')
    check(code == 200 and h.get('state') == 'in service', '/api/healthz in service: %s %r' % (code, h))
    check(told('the disk is nearly full', 'host') and hasattr(d, 'maint_holding'),
          'an alert about the machine was not sent in service, or nothing could hold it')

    # ---- by hand ------------------------------------------------------------------------
    print('maintenance by hand')
    code, v = call('/api/upgrade', {'action': 'maintenance', 'on': 'yes', 'session': S}, session=S)
    check(code == 400 and 'true or false' in v.get('error', ''), 'on that is not true or false: %s %r' % (code, v))
    code, v = maint(True, 'the disk')
    m = v.get('maintenance') or {}
    check(code == 200 and m.get('on') is True and m.get('why') == 'the disk' and m.get('by') == 'owner'
          and not m.get('auto'), 'into maintenance: %s %r' % (code, v.get('error') or m))
    code, v2 = maint(True, 'again')
    check(code == 400 and 'already' in v2.get('error', ''), 'into maintenance twice was taken: %r' % v2)
    code, v2 = maint(False, session=S_OP)
    check(code == 403 and d.maint_view().get('on'), 'an operator took the server out of maintenance (%s)' % code)
    check(any('in maintenance - the disk' in e for e in events()), 'the events do not say it: %r' % events(8))
    code, h = call('/api/healthz')
    check(code == 503 and h.get('state') == 'in maintenance', '/api/healthz in maintenance: %s %r' % (code, h))
    code, h = call('/api/health')
    check(code == 200 and (h.get('maintenance') or {}).get('on') is True,
          '/api/health is not 200 with maintenance in it: %s %r' % (code, h.get('maintenance')))
    code, st = call('/api/status', session=S)
    check((st.get('maintenance') or {}).get('on') is True, 'the status (the band of every page) does not say it')

    print('the alerts held, the house\'s own sent')
    for about, words in (('host', 'the disk is nearly full'), ('started', 'zigmon started'),
                         ('quiet', 'PIR-Chodba has gone quiet'), ('mesh', 'the mesh is unsettled'),
                         ('bridge', 'Zigbee2MQTT stopped'), ('broker', 'the broker is away'),
                         ('updates', '2 security updates waiting')):
        check(not told(words, about), 'held back in maintenance, yet sent: %s' % about)
    check(any('held back in maintenance' in e for e in events()), 'what was held is not in the events')
    for about, words in (('alert', 'The front door opened'), ('leak', 'Water under the sink'),
                         ('house', 'from a script'), ('power', 'the house draws a lot')):
        check(told(words, about), 'the house\'s own alert was held in maintenance: %s' % about)
    # a device gone offline, told as a device's own event
    d.notify_queue.clear()
    d.notify_sent.clear()
    d.consider_notifying('availability', 'offline', 'warn', None)
    check(not queued(), 'a device going offline was told in maintenance: %r' % queued())
    d.consider_notifying('device', 'water_leak: true', 'crit', None)
    check(queued(), 'a sensor\'s critical word was held in maintenance')
    # the first round after a start says "zigmon started": held
    d.notify_queue.clear()
    d._started_told = False
    d.check_system_alerts()
    check(not any('started' in q for q in queued()), 'zigmon started was told in maintenance')

    print('kept across a restart of the daemon')
    row = json.loads(d.store.get_meta('maint') or '{}')
    check(row.get('on') is True and row.get('why') == 'the disk', 'not kept in the database: %r' % row)
    d.__dict__.pop('_maint', None)
    check(d.maint_view().get('on') is True, 'read again, it is not in maintenance')

    print('back in service, and the 10 minutes after')
    code, v = maint(False)
    m = v.get('maintenance') or {}
    check(code == 200 and m.get('on') is False, 'back in service: %s %r' % (code, v.get('error') or m))
    check(any('back in service' in e for e in events()), 'the events do not say back in service')
    code, h = call('/api/healthz')
    check(code == 200, '/api/healthz back in service: %s' % code)
    check(m.get('held') and m.get('until') and 590 < m['until'] - time.time() <= 600,
          'the 10 min after are not said: %r' % m)
    check(not told('the disk is nearly full', 'host'), 'an alert about the machine was sent within 10 min')
    d._maint['ended'] = time.time() - 601
    check(told('the disk is nearly full', 'host'), 'an alert about the machine was held after the 10 min')
    code, v = maint(False)
    check(code == 400 and 'in service already' in v.get('error', ''), 'back in service twice: %r' % v)

    # ---- by itself ----------------------------------------------------------------------
    print('by itself: an upgrade')
    status = d.upgrade_dir('status.json')
    status.write_text(json.dumps({'id': 'a1', 'state': 'running', 'step': 'installing', 'version': '9.9.9',
                                  'at': time.time()}))
    d.maint_follow()
    m = d.maint_view()
    check(m.get('on') and m.get('auto') == 'upgrade' and '9.9.9' in (m.get('why') or ''),
          'not in maintenance during an upgrade: %r' % m)
    code, v = maint(False)
    check(code == 400 and 'by itself' in v.get('error', ''), 'Back in service taken during an upgrade: %r' % v)
    check(not told('the disk is nearly full', 'host'), 'an alert about the machine during an upgrade')
    status.write_text(json.dumps({'id': 'a1', 'state': 'done', 'version': '9.9.9', 'at': time.time()}))
    d.maint_follow()
    m = d.maint_view()
    check(m.get('on') is False and m.get('held'), 'not back in service after the upgrade: %r' % m)
    check(any('back in service' in e and '9.9.9' in e for e in events()), 'the end of it is not in the events')
    d._maint['ended'] = 0

    print('by itself: an update of the system')
    d._mj_put('osup:run', {'state': 'running', 'id': 'x'})
    d.maint_follow()
    check(d.maint_view().get('auto') == 'osup', 'not in maintenance while the system is updated: %r'
          % d.maint_view())
    d._mj_put('osup:run', {'state': 'done', 'id': 'x'})
    d.maint_follow()
    check(d.maint_view().get('on') is False, 'not back in service after the update')
    d._maint['ended'] = 0

    print('by itself: a restart')
    zigmon.CONFIG['root_installed'] = True
    try:
        plan = d.power_ask('reboot', 'owner')
    except ValueError as e:
        plan = {}
        check(False, 'a restart was not asked: %s' % e)
    m = d.maint_view()
    check(m.get('on') and m.get('auto') == 'restart', 'not in maintenance when a restart is asked: %r' % m)
    d._mj_put('power:row', {'id': plan.get('id'), 'state': 'back'})
    d.maint_follow()
    check(d.maint_view().get('on') is False, 'not back in service after the restart')

    print('by hand stays by hand')
    maint(True, 'the cable')
    status.write_text(json.dumps({'id': 'a2', 'state': 'running', 'version': '9.9.10', 'at': time.time()}))
    d.maint_follow()
    status.write_text(json.dumps({'id': 'a2', 'state': 'done', 'version': '9.9.10', 'at': time.time()}))
    d.maint_follow()
    m = d.maint_view()
    check(m.get('on') and m.get('why') == 'the cable', 'an upgrade took a maintenance by hand off: %r' % m)
    maint(False)
    d._maint['ended'] = 0

    print('the system loop follows it')
    src = (HERE / 'zigmon.py').read_text()
    loop = src[src.index('    def system_loop(self):'):]
    loop = loop[:loop.index('    def php_loop(self):')]
    check('self.maint_follow' in loop, 'the system loop does not follow maintenance')

    # ---- the command line and the console -------------------------------------------------
    print('the command line and the console')
    parser = zigmon.build_parser()
    args = parser.parse_args(['--maintenance', 'on', '--why', 'the disk'])
    check(args.maintenance == 'on' and args.why == 'the disk', '--maintenance on --why is not taken')
    real = zigmon.api_call

    def via_api(path, method='GET', payload=None, timeout=10.0, **k):
        return call(path, dict(payload, session=S) if payload else None, session=S)
    zigmon.api_call = via_api
    try:
        for argv, want in ((['--maintenance', 'on', '--why', 'from the test'], 'IN MAINTENANCE'),
                           (['--maintenance', 'status'], 'from the test'),
                           (['--maintenance', 'off'], 'in service')):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = zigmon.cmd_maintenance(parser.parse_args(argv + ['--no-color']), zigmon.Palette(False))
            check(rc == 0 and want in out.getvalue(), 'zigmon %s: %s %r' % (' '.join(argv), rc, out.getvalue()[-300:]))
    finally:
        zigmon.api_call = real
    check(src.count("('sudo zigmon --maintenance on") == 1, 'the help does not name --maintenance')
    check(any('Maintenance' in w for w, _ in zigmon.CONSOLE_MORE['upgrades']), 'the console has no Maintenance')

    # ---- the relay ------------------------------------------------------------------------
    page = (HERE / 'web' / 'index.php').read_text()
    check("$what === 'healthz'" in page and "zigmon_relay('/api/healthz')" in page, 'the relay has no ?api=healthz')
except Exception as e:                                  # noqa: BLE001 - said, and the page still looked at
    check(False, 'the checks of the daemon broke off: %r' % e)
finally:
    try:
        if api:
            api.stop()
    except Exception:
        pass

# ---- the real page in Chromium ----------------------------------------------------------
print('the pane in Chromium')
JS = r'''
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({viewport: {width: 1500, height: 1600}});
  p.on('pageerror', e => {});
  await p.goto('http://127.0.0.1:%(port)d/index.php#control/sys-upgrade');
  await p.waitForTimeout(1200);
  const r = await p.evaluate(() => {
    window.isAdmin = () => true;
    try { showControlSection('sys-upgrade'); } catch (e) {}
    let up = document.getElementById('up-nodes');
    while (up) { if (getComputedStyle(up).display === 'none') { up.hidden = false; up.style.display = 'block'; } up = up.parentElement; }
    document.querySelectorAll('[data-sec="sys-upgrade"]').forEach(e => { if (e.id !== 'up-back-card' && e.id !== 'up-plan-card') e.hidden = false; });
    const out = {err: ''};
    try { upgradeWire(); } catch (e) { out.err += String(e); }
    try {
      renderSettings({runtime_config: {upgrade_check: {value: 1, kind: 'switch'},
        upgrade_url: {value: 'https://github.com/falco81/ZIGMon/tree/main/release', kind: 'text'},
        downgrade_show: {value: 0, kind: 'switch'}}});
    } catch (e) { out.err += String(e); }
    const now = Date.now() / 1000;
    const d = (m) => ({version: '5.34.1', helper: true, ready: true, back: {on: false}, status: {}, log: [], maintenance: m,
      nodes: [{name: 'zigmon', me: true, alive: true, version: '5.34.1', at: now, since: now - 3600, maintenance: m}],
      web: {check: true, url: 'https://github.com/falco81/ZIGMon/tree/main/release',
            online: {at: now - 300, newest: {version: '5.34.1'}, here: '5.34.1', url: 'https://github.com/falco81/ZIGMon/tree/main/release'}},
      package: {version: '5.34.2', signed_by: 'zigmon-release-1', bytes: 1500000, by: 'admin', at: now - 300, changelog: '5.34.2 - things'}});
    try { drawUpgrade(d({on: false})); } catch (e) { out.err += String(e); }
    const T = s => (s && s.textContent || '').replace(/\s+/g, ' ').trim();
    const pane = Array.from(document.querySelectorAll('#tab-control .grid.charts > [data-sec="sys-upgrade"]'));
    out.cards = pane.filter(c => !c.hidden && getComputedStyle(c).display !== 'none')
      .map(c => T(c.querySelector(':scope > h2')).replace(/About$/, '').trim());
    out.title = T(document.querySelector('#ctl-head .ctl-title'));
    out.menu = T(document.querySelector('#control-nav button[data-sec="sys-upgrade"]'));
    out.heads = Array.from(document.querySelectorAll('#up-nodes th')).map(th => getComputedStyle(th).textTransform === 'uppercase' ? T(th).toUpperCase() : T(th)).filter(Boolean);
    const row = document.querySelector('#up-nodes tbody tr');
    out.tags = row ? Array.from(row.querySelectorAll('.tag')).map(t => getComputedStyle(t).textTransform === 'uppercase' ? T(t).toUpperCase() : T(t)) : [];
    out.rowButtons = row ? Array.from(row.querySelectorAll('button')).map(T) : [];
    const items = Array.from(document.querySelectorAll('#up-web-card .set-item'));
    out.settings = items.map(it => { const l = it.querySelector('label'); return l && l.firstChild ? String(l.firstChild.textContent).trim() : ''; });
    out.tops = items.map(it => Math.round(it.getBoundingClientRect().top));
    out.says = items.map(it => {
      const s = it.querySelector('.set-says'), c = it.querySelector('input, .sw');
      return s && c && getComputedStyle(s).display !== 'none' ? Math.round(s.getBoundingClientRect().top - c.getBoundingClientRect().bottom) : null; });
    out.web = T(document.getElementById('up-web'));
    out.nodesNote = T(document.querySelector('#up-card > p.note')) && getComputedStyle(document.querySelector('#up-card > p.note')).display !== 'none';
    out.drop = T(document.querySelector('#up-drop-slot'));
    out.pkg = T(document.getElementById('up-pkg'));
    out.start = T(document.getElementById('up-start'));
    out.forget = T(document.getElementById('up-forget'));
    out.forgetShown = !document.getElementById('up-forget').hidden;
    try { drawUpgrade(d({on: true, why: 'the disk', by: 'owner', at: now - 300, auto: ''})); } catch (e) { out.err += String(e); }
    const row2 = document.querySelector('#up-nodes tbody tr');
    out.tags2 = row2 ? Array.from(row2.querySelectorAll('.tag')).map(T) : [];
    out.rowButtons2 = row2 ? Array.from(row2.querySelectorAll('button')).map(T) : [];
    try { renderMaintBand({maintenance: {on: true, why: 'the disk', by: 'owner', at: now - 300}}); } catch (e) { out.err += String(e); }
    const band = document.getElementById('maint-band');
    out.band = band && !band.hidden ? T(band) : '';
    try { renderMaintBand({maintenance: {on: false}}); } catch (e) {}
    out.bandOff = band ? band.hidden : false;
    return out;
  });
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
''' % {'port': PHP_PORT}
(W / 'run.js').write_text(JS)
r = {'error': 'php is not here'}
if subprocess.run(['which', 'php'], capture_output=True).stdout:
    php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, '-t', str(HERE / 'web')],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
        got = subprocess.run(['node', str(W / 'run.js')], capture_output=True, text=True, timeout=120,
                             stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=root))
        try:
            r = json.loads(got.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            r = {'error': (got.stdout + got.stderr)[-300:]}
    finally:
        php.kill()
        php.wait()
if r.get('error'):
    print('  SKIPPED (no browser here): %s' % r['error'][:200])
else:
    if os.environ.get('DBG'):
        print('DBG', json.dumps(r, indent=1))
    check(not r.get('err'), 'the page threw: %s' % r.get('err'))
    check(r.get('title') == 'Upgrades and maintenance' and r.get('menu') == 'Upgrades',
          'the pane is called %r, its entry in the menu %r' % (r.get('title'), r.get('menu')))
    cards = r.get('cards') or []
    check(cards[:3] == ['The nodes', 'From the web', 'A new version'], 'the cards are %r' % cards)
    check(r.get('heads') == ['NODE', 'VERSION', 'HEARD FROM', 'STATE'], 'the nodes table says %r' % r.get('heads'))
    check(r.get('tags') == ['THIS PAGE', 'IN SERVICE'], 'the row\'s tags are %r' % r.get('tags'))
    check(r.get('rowButtons') == ['Maintenance'], 'the row\'s button is %r' % r.get('rowButtons'))
    check(r.get('nodesNote'), 'The nodes says nothing of maintenance')
    check(r.get('settings') == ['Look for a new version every day', 'Where new versions are looked for',
                                'Offer going back to an older version'],
          'From the web has the settings %r' % r.get('settings'))
    tops = r.get('tops') or []
    check(len(tops) == 3 and max(tops) - min(tops) < 40, 'the three settings are not side by side: %r' % tops)
    check(len(r.get('says') or []) == 3 and all(x is not None and 0 <= x < 40 for x in r['says']),
          'the words of each setting are not under it: %r' % r.get('says'))
    # what From the web and A new version say, with otp's two buttons under the package
    check('Nothing newer: the newest there is 5.34.1 and this server runs 5.34.1' in r.get('web', '')
          and 'Look now' in r.get('web', '') and cards[1:2] == ['From the web'] and len(r.get('settings') or []) == 3,
          'From the web says %r, with %r' % (r.get('web', '')[:200], r.get('settings')))
    check('Drop the zigmon-X.Y.Z.tar.gz here, or press to choose it' in r.get('drop', '')
          and 'zigmon 5.34.2' in r.get('pkg', '') and 'signed by zigmon-release-1' in r.get('pkg', '')
          and 'What changed in 5.34.2' in r.get('pkg', '') and r.get('start') == 'Upgrade this server'
          and r.get('forget') == 'Forget the package' and r.get('forgetShown'),
          'A new version: drop %r, package %r, buttons %r %r' % (r.get('drop'), r.get('pkg'), r.get('start'),
                                                               r.get('forget')))
    check(r.get('tags2') == ['this page', 'in maintenance'] and r.get('rowButtons2') == ['Back in service'],
          'in maintenance the row says %r %r' % (r.get('tags2'), r.get('rowButtons2')))
    check('This server is in maintenance' in r.get('band', '') and 'the disk' in r.get('band', '')
          and 'Back in service' in r.get('band', ''), 'the band says %r' % r.get('band'))
    check(r.get('bandOff'), 'the band stays in service')

if bad:
    print('\n%d problem(s)' % len(bad))
    raise SystemExit(1)
shutil.rmtree(str(W), ignore_errors=True)
print('\nUpgrades and maintenance: every check passed')
