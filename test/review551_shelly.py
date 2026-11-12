#!/usr/bin/env python3
"""5.51: the Shelly Gen2+ side read against Shelly's own API description.

Fixes (each check fails on 5.49.1):
  1. the digest nonce count (nc) of a shared challenge is stepped once per
     request, never handed to two (Authentication: "rejects requests with an
     nc value that is not strictly greater");
  2. a socket that protects itself (errors: ["overpower"]) and says so in its
     MQTT push is alerted on, and so is its all-clear (errors: null - a key
     that goes away is sent as null, Notifications) - before, the push wrote
     it into the reading and the poll then saw nothing new;
  3. `zigmon shelly NAME watch` answers a websocket ping with a masked pong
     carrying the ping's payload, as a client must (RFC 6455).
New (5.51): a box's firmware (Shelly.CheckForUpdate / Shelly.Update) and its
relay's own settings (Switch.GetConfig / SetConfig: power-on, auto-off,
auto-on, overpower limit) - on the daemon (/api/plug/shelly, administrator),
the page (asked first), the command line (asked first; --yes; refused with
no terminal) and the console.

    python3 test/review551_shelly.py < /dev/null

A fake box on 127.0.0.1:20051 with SHA-256 digest; nothing else is needed.
"""
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review551-'))
PORT = 20051
PASSWORD = 'box-pass'
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


# ---- a fake box: digest with nc strictly rising, firmware, switch config ------------
BOX = {'offer': {'stable': {'version': '1.8.0', 'build_id': 'b1'},
                 'alt': {'Zb': {'name': 'Zigbee', 'stable': {'version': '9.9.9'}}}},
       'cfg': {'id': 0, 'name': None, 'in_mode': 'flip', 'initial_state': 'restore_last', 'auto_on': False,
               'auto_on_delay': 60.0, 'auto_off': False, 'auto_off_delay': 60.0, 'power_limit': 2500},
       'ignore': set(), 'calls': [], 'nc': {}}


class Box(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _digest_ok(self):
        header = self.headers.get('Authorization', '')
        if not header.startswith('Digest '):
            return False
        f = dict(re.findall(r'(\w+)="?([^",]+)"?', header))

        def h(t):
            return hashlib.sha256(t.encode()).hexdigest()
        ha1 = h('admin:%s:%s' % (f.get('realm'), PASSWORD))
        ha2 = h('POST:%s' % f.get('uri'))
        if f.get('response') != h('%s:%s:%s:%s:auth:%s' % (ha1, f.get('nonce'), f.get('nc'), f.get('cnonce'), ha2)):
            return False
        nc = int(f.get('nc') or '0', 16)
        if nc <= BOX['nc'].get(f.get('nonce'), 0):
            return False                    # as firmware 2.0.0: an nc seen already is refused
        BOX['nc'][f.get('nonce')] = nc
        return True

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        if not self._digest_ok():
            self.send_response(401)
            # a fresh nonce for every challenge, as a real box gives
            self.send_header('WWW-Authenticate', 'Digest qop="auth", realm="shellyplugsg3-aabbcc", '
                                                 'nonce="%s", algorithm=SHA-256' % secrets.token_hex(8))
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        m, p = body.get('method'), body.get('params') or {}
        BOX['calls'].append((m, p))
        if m == 'Shelly.GetDeviceInfo':
            r = {'id': 'shellyplugsg3-aabbcc', 'model': 'S3PL-00112EU', 'app': 'PlugSG3', 'ver': '1.7.1', 'gen': 3}
        elif m == 'Shelly.CheckForUpdate':
            r = BOX['offer']
        elif m == 'Shelly.Update':
            r = None
        elif m == 'Switch.GetConfig':
            r = dict(BOX['cfg'])
        elif m == 'Switch.SetConfig':
            for k, v in (p.get('config') or {}).items():
                if k not in BOX['ignore']:
                    BOX['cfg'][k] = v
            r = {'restart_required': False}
        elif m == 'Switch.GetStatus':
            r = {'id': 0, 'output': False, 'apower': 0.0}
        else:
            r = None
        out = json.dumps({'id': body.get('id'), 'src': 'shellyplugsg3-aabbcc', 'result': r}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        self.wfile.write(out)


server = ThreadingHTTPServer(('127.0.0.1', PORT), Box)
threading.Thread(target=server.serve_forever, daemon=True).start()

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'zigmon.db'), 'api_port': 20052, 'token_file': str(W / 'token'),
                      'plugs': [{'name': 'Lamp', 'host': '127.0.0.1:%d' % PORT, 'password': PASSWORD},
                                {'name': 'Watched', 'host': '127.0.0.1:%d' % PORT, 'password': PASSWORD,
                                 'monitor_only': True}],
                      'sensors': [], 'backup_dir': str(W / 'backups'), 'weather': False, 'state_dir': str(W)})
d = zigmon.Daemon()

try:
    # -- 1. the nonce count is never handed out twice --------------------------------
    class SlowFields(dict):
        def get(self, key, default=None):
            value = dict.get(self, key, default)
            if key == 'nc':
                time.sleep(0.01)              # a thread switch at the worst moment: read, not yet written
            return value
    fields = SlowFields({'realm': 'r', 'nonce': 'n', 'nc': 0})
    rpc = zigmon.ShellyRPC('127.0.0.1:1', 'pw')
    said = []
    threads = [threading.Thread(target=lambda: said.append(rpc._digest_header(fields, 'POST', '/rpc')))
               for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    counts = sorted(re.search(r'nc=([0-9a-f]{8})', x).group(1) for x in said)
    check(counts == ['00000001', '00000002', '00000003', '00000004'],
          'four requests on one challenge were given the nonce counts %r - a repeated nc is refused by the box' % counts)
    print('the nonce count of a shared challenge steps once per request')

    # -- 2. a socket's push that it is protecting itself is alerted on ---------------
    told = []
    d.say_event = lambda kind, detail, level='warn', device=None, **kw: told.append((detail, level))
    lamp = d.plugs['Lamp']
    lamp.cfg['mqtt'] = True
    d._record_plug(lamp, {'id': 0, 'output': True, 'apower': 2900.0}, {}, time.time())
    d._record_plug(lamp, {'id': 0, 'output': True, 'apower': 2950.0}, {}, time.time())
    told[:] = []
    d.handle_plug_push([lamp], ['events', 'rpc'], json.dumps({'method': 'NotifyStatus', 'params': {
        'ts': time.time(), 'switch:0': {'id': 0, 'output': False, 'errors': ['overpower']}}}).encode())
    check(any('protecting itself' in t[0] and 'overpower' in t[0] and t[1] == 'crit' for t in told),
          'a push saying the socket protected itself (overpower) raised no alert: %r' % told)
    told[:] = []
    d._record_plug(lamp, {'id': 0, 'output': False, 'apower': 0.0, 'errors': ['overpower']}, {}, time.time())
    check(not any('protecting itself' in t[0] for t in told), 'the overpower was alerted twice: %r' % told)
    d.handle_plug_push([lamp], ['events', 'rpc'], json.dumps({'method': 'NotifyStatus', 'params': {
        'ts': time.time(), 'switch:0': {'id': 0, 'errors': None}}}).encode())
    check(any('no longer' in t[0] for t in told), 'a push saying the overpower cleared (errors: null) was not told: %r' % told)
    told[:] = []
    d.handle_plug_push([lamp], ['events', 'rpc'], json.dumps({'method': 'NotifyStatus', 'params': {
        'ts': time.time(), 'switch:0': {'id': 0, 'apower': 12.0}}}).encode())
    check(not told, 'a push of watts alone said something about errors: %r' % told)
    del d.say_event
    print('a socket protecting itself is alerted on from its push, and its all-clear too')

    # -- 3. a websocket ping gets a masked pong with its payload ---------------------
    class FakeSock:
        def __init__(self, data):
            self.data, self.sent = data, b''

        def recv(self, n):
            chunk, self.data = self.data[:n], self.data[n:]
            return chunk

        def sendall(self, b):
            self.sent += b
    sock = FakeSock(bytes([0x89, 4]) + b'ping' + bytes([0x88, 0]))
    list(zigmon._ws_frames(sock))
    pong = sock.sent
    ok = len(pong) == 2 + 4 + 4 and pong[0] == 0x8A and pong[1] == 0x80 | 4 and \
        bytes(b ^ pong[2 + i % 4] for i, b in enumerate(pong[6:])) == b'ping'
    check(ok, 'the pong to a websocket ping was not a masked frame with the ping\'s payload: %r' % pong)
    print('a websocket ping is answered as a client must')

    # -- 4. firmware: what is offered, and an update only to what is ---------------
    box = zigmon.ShellyRPC('127.0.0.1:%d' % PORT, PASSWORD)
    found = zigmon.shelly_firmware_check(box)
    check(found == {'current': '1.7.1', 'model': 'S3PL-00112EU', 'stable': '1.8.0', 'beta': None},
          'the firmware check said %r' % found)
    BOX['calls'][:] = []
    try:
        zigmon.shelly_firmware_update(box, 'beta')
        check(False, 'an update to a beta that is not offered was sent')
    except zigmon.PlugError:
        pass
    check(not [c for c in BOX['calls'] if c[0] == 'Shelly.Update'], 'Shelly.Update went out with nothing offered')
    zigmon.shelly_firmware_update(box, 'stable')
    check(('Shelly.Update', {'stage': 'stable'}) in BOX['calls'], 'Shelly.Update {stage: stable} was not sent: %r'
          % BOX['calls'])
    print('firmware: what is offered is said, and only that is put in (never an "alt" firmware)')

    # -- 5. the relay's own settings ---------------------------------------------------
    got = zigmon.shelly_switch_settings(box, 0)
    check(got == {'initial_state': 'restore_last', 'auto_on': False, 'auto_on_delay': 60.0, 'auto_off': False,
                  'auto_off_delay': 60.0, 'power_limit': 2500}, 'the settings read were %r' % got)
    for wrong in ({'in_mode': 'detached'}, {'initial_state': 'sometimes'}, {'auto_off': 'yes'},
                  {'auto_off_delay': 0}, {'power_limit': -5}):
        try:
            zigmon.shelly_switch_settings_clean(wrong, got)
            check(False, 'a setting that is not right was let through: %r' % wrong)
        except ValueError:
            pass
    try:
        zigmon.shelly_switch_settings_clean({'power_limit': 100}, {'auto_off': False})
        check(False, 'power_limit was let through for a box that has none')
    except ValueError:
        pass
    now, missed, restart = zigmon.shelly_switch_settings_write(box, 0, {'auto_off': True, 'auto_off_delay': 600,
                                                                       'power_limit': None})
    check(BOX['cfg']['auto_off'] is True and BOX['cfg']['auto_off_delay'] == 600 and BOX['cfg']['power_limit'] is None
          and not missed, 'the settings were not written as asked: %r %r' % (BOX['cfg'], missed))
    BOX['ignore'].add('initial_state')
    now, missed, restart = zigmon.shelly_switch_settings_write(box, 0, {'initial_state': 'off'})
    check(missed == ['initial_state'], 'a setting the box quietly kept was not reported: %r' % missed)
    BOX['ignore'].clear()
    print('settings: read, checked, written and read back')

    # -- 6. the daemon: the road, an administrator's, monitor-only refused ----------
    check('/api/plug/shelly' not in zigmon.OPERATOR_ROADS, 'an operator could change a box\'s firmware')
    ok, answer = d.plug_shelly(lamp, 'firmware')
    check(ok and answer['firmware']['stable'] == '1.8.0', 'the daemon\'s firmware check: %r' % (answer,))
    ok, answer = d.plug_shelly(d.plugs['Watched'], 'settings-save', {'settings': {'auto_off': False}})
    check(not ok and 'monitor-only' in str(answer), 'a monitor-only socket\'s box was changed: %r' % (answer,))
    ok, answer = d.plug_shelly(d.plugs['Watched'], 'settings')
    check(ok and 'auto_off' in answer['settings'], 'a monitor-only socket\'s settings could not be read')
    ok, answer = d.plug_shelly(lamp, 'settings-save', {'settings': {'auto_on': True, 'auto_on_delay': 30}})
    check(ok and BOX['cfg']['auto_on'] is True and BOX['cfg']['auto_on_delay'] == 30, 'the daemon\'s save: %r' % (answer,))
    ok, answer = d.plug_shelly(lamp, 'settings-save', {'settings': {'reverse': True}})
    check(not ok, 'a setting outside the list was written: %r' % (answer,))
    ok, answer = d.plug_shelly(lamp, 'nonsense')
    check(not ok, 'an unknown action was taken')
    src = (HERE / 'zigmon.py').read_text()
    check("if path == '/api/plug/shelly':" in src, 'the daemon does not serve /api/plug/shelly')
    php = (HERE / 'web' / 'index.php').read_text()
    check("$what === 'plug-shelly'" in php and "zigmon_relay('/api/plug/shelly'" in php,
          'the page\'s relay does not carry plug-shelly')
    js = php[php.index('function plugFirmware'):php.index('// The Smart Plugs card')]
    check(js.count('zconfirm(') == 2, 'a change to a box from the page is not asked about first')
    print('the daemon: an administrator\'s road, monitor-only boxes left alone')

    # -- 7. the command line: asked first, refused without a terminal, --yes ---------
    cfgfile = W / 'cli.json'
    cfgfile.write_text(json.dumps({'db_file': str(W / 'cli.db'), 'plugs': [
        {'name': 'Lamp', 'host': '127.0.0.1:%d' % PORT, 'password': PASSWORD}]}))

    def cli(*args):
        got = subprocess.run([sys.executable, str(HERE / 'zigmon.py'), 'shelly', '--config', str(cfgfile)]
                             + list(args) + ['--no-color'],
                             capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        return got.returncode, got.stdout + got.stderr
    rc, out = cli('Lamp', 'firmware', '--json')
    check(rc == 0 and json.loads(out).get('stable') == '1.8.0', 'firmware --json: %d %s' % (rc, out))
    BOX['calls'][:] = []
    rc, out = cli('Lamp', 'firmware', 'update')
    check(rc != 0 and 'not done' in out and not [c for c in BOX['calls'] if c[0] == 'Shelly.Update'],
          'firmware update went ahead with nobody to ask: %d %s' % (rc, out))
    rc, out = cli('Lamp', 'firmware', 'update', '--yes')
    check(rc == 0 and [c for c in BOX['calls'] if c[0] == 'Shelly.Update'], 'firmware update --yes: %d %s' % (rc, out))
    rc, out = cli('Lamp', 'switch-settings')
    check(rc == 0 and 'switches itself off' in out, 'switch-settings shows: %d %s' % (rc, out))
    rc, out = cli('Lamp', 'switch-settings', '--auto-off', '120')
    check(rc != 0 and BOX['cfg']['auto_off_delay'] == 600, 'switch-settings changed the box unasked: %d %s' % (rc, out))
    rc, out = cli('Lamp', 'switch-settings', '--auto-off', '120', '--power-on', 'off', '--yes')
    check(rc == 0 and BOX['cfg']['auto_off_delay'] == 120 and BOX['cfg']['initial_state'] == 'off',
          'switch-settings --yes: %d %s %r' % (rc, out, BOX['cfg']))
    rc, out = cli('Lamp', 'switch-settings', '--auto-off', 'off', '--power-limit', 'default', '--yes')
    check(rc == 0 and BOX['cfg']['auto_off'] is False and BOX['cfg']['power_limit'] is None,
          'switch-settings off/default: %d %s' % (rc, out))
    rc, out = cli('Lamp', 'switch-settings', '--power-limit', 'lots', '--yes')
    check(rc != 0, 'a power limit that is not a number was taken: %s' % out)
    help_block = src[src.index('HELP_LINES = ['):src.index('\n]\n\n\ndef help_text')]
    check('shelly Lednice firmware' in help_block and 'shelly Lednice switch-settings' in help_block,
          'the help does not name the new commands')
    console = src[src.index('    def plug_do(self, p):'):src.index('    # ---- 4 accounts of the dashboard')]
    check("'firmware'" in console and "'settings'" in console and console.count('self.confirm(') >= 3,
          'the console offers no firmware or settings, or does not ask first')
    print('the command line: asked first, nothing done without a terminal, --yes to go ahead')

    # -- 8. the page: the box's fold, asked first (the real page, php -S, Chromium) --
    ui = r'''
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({viewport: {width: 1300, height: 900}});
  p.on('pageerror', e => {});
  await p.goto('http://127.0.0.1:%(port)d/index.php');
  await p.waitForTimeout(800);
  const r = await p.evaluate(async () => {
    const calls = [];
    const answers = {firmware: {ok: true, firmware: {current: '1.7.1', model: 'S3PL', stable: '1.8.0', beta: null}},
                     'firmware-update': {ok: true, message: 'started'},
                     settings: {ok: true, settings: {initial_state: 'restore_last', auto_off: false, auto_off_delay: 60, power_limit: 2500}},
                     'settings-save': {ok: true, message: 'saved'}};
    window.signedIn = () => true;
    window.post = (what, body) => { calls.push([what, body]); return Promise.resolve(what === 'plug-shelly' ? answers[body.action] : {ok: true}); };
    const wait = ms => new Promise(ok => setTimeout(ok, ms));
    const st = {plugs: [{name: 'Lamp', online: true, output: 1, host: '10.0.0.5', info: {}, counters: []},
                        {name: 'Watched', online: true, output: 0, host: '10.0.0.6', info: {}, counters: [], monitor_only: true}],
                pulse_ms: {default: 5000}};
    PLUGCTL_OPEN = {Lamp: true, Watched: true};
    renderPlugControls(st);
    const out = {};
    const inLamp = document.querySelector('[data-plug="Lamp"] [data-plug-shelly="firmware"]');
    out.watched = !!document.querySelector('[data-plug="Watched"] [data-plug-shelly]');
    out.lamp = !!inLamp && !!document.querySelector('[data-plug="Lamp"] [data-plug-shelly="settings"]');
    if (!inLamp) return out;
    inLamp.click(); await wait(150);
    const btn = words => Array.from(document.querySelectorAll('#zmodal-foot button')).find(x => x.textContent.indexOf(words) >= 0);
    out.fwTitle = document.getElementById('zmodal-title').textContent;
    const up = btn('Update to 1.8.0');
    out.offered = !!up;
    if (up) { up.click(); await wait(100); }
    out.askTitle = document.getElementById('zmodal-title').textContent;
    out.beforeYes = calls.filter(c => c[1] && c[1].action === 'firmware-update').length;
    const yes = btn('Update it'); if (yes) { yes.click(); await wait(100); }
    out.afterYes = calls.filter(c => c[1] && c[1].action === 'firmware-update').map(c => c[1].stage);
    document.querySelector('[data-plug="Lamp"] [data-plug-shelly="settings"]').click(); await wait(150);
    const sel = document.querySelector('#zmodal-body select');
    out.select = !!sel;
    if (sel) { sel.value = 'off'; }
    const change = btn('Change'); if (change) { change.click(); await wait(100); }
    out.askChange = document.getElementById('zmodal-title').textContent;
    out.saveBefore = calls.filter(c => c[1] && c[1].action === 'settings-save').length;
    const yes2 = btn('Change it'); if (yes2) { yes2.click(); await wait(100); }
    out.saved = calls.filter(c => c[1] && c[1].action === 'settings-save').map(c => c[1].settings);
    return out;
  });
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
''' % {'port': PORT + 2}
    if shutil.which('php') and shutil.which('node'):
        (W / 'ui.js').write_text(ui)
        php_srv = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % (PORT + 2), '-t', str(HERE / 'web')],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    socket.create_connection(('127.0.0.1', PORT + 2), 0.2).close()
                    break
                except OSError:
                    time.sleep(0.1)
            root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
            got = subprocess.run(['node', str(W / 'ui.js')], capture_output=True, text=True, timeout=120,
                                 stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=root))
        finally:
            php_srv.kill()
            php_srv.wait()
        try:
            r = json.loads(got.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            r = {'error': (got.stdout + got.stderr)[-300:]}
        if r.get('error'):
            print('  SKIPPED the page (no browser here): %s' % r['error'][:200])
        else:
            check(r.get('lamp') and not r.get('watched'),
                  'the box\'s buttons: on the socket %r, on the monitor-only one %r' % (r.get('lamp'), r.get('watched')))
            check(r.get('offered') and r.get('askTitle') == 'Update Lamp' and r.get('beforeYes') == 0
                  and r.get('afterYes') == ['stable'], 'the page\'s firmware update was not asked first: %r' % r)
            check(r.get('select') and r.get('askChange') == 'Change Lamp' and r.get('saveBefore') == 0
                  and r.get('saved') == [{'initial_state': 'off'}],
                  'the page\'s settings change was not asked first, or sent more than changed: %r' % r)
            print('the page: the box\'s fold offers both, and asks before either changes the box')

    # -- 9. the console: what it asks the command line to do, after a yes ------------
    class Seen(object):
        def __init__(self, answer, form=None, yes=True):
            self.answer, self.form_answer, self.yes, self.acts, self.notes = answer, form, yes, [], []

        def working(self, words):
            pass

        def out(self, *args):
            return self.answer

        def note(self, title, text, tone=''):
            self.notes.append(text)

        def confirm(self, *a, **kw):
            return self.yes

        def form(self, title, fields, words='', check=None, ok='OK'):
            self.fields = fields
            return self.form_answer

        def act(self, *args, **kw):
            self.acts.append(args)
    c = Seen({'current': '1.7.1', 'stable': '1.8.0', 'beta': None})
    zigmon.Console.plug_firmware(c, 'Lamp')
    check(c.acts == [('shelly', 'Lamp', 'firmware', 'update', '--yes')], 'the console\'s update: %r' % c.acts)
    c = Seen({'current': '1.7.1', 'stable': '1.8.0', 'beta': None}, yes=False)
    zigmon.Console.plug_firmware(c, 'Lamp')
    check(c.acts == [], 'the console updated a box after a no: %r' % c.acts)
    known = {'initial_state': 'restore_last', 'auto_off': True, 'auto_off_delay': 600.0, 'power_limit': None}
    c = Seen(known, {'power_on': 'restore_last', 'auto_off': '', 'power_limit': '2000'})
    zigmon.Console.plug_switch_settings(c, 'Lamp')
    check(c.acts == [('shelly', 'Lamp', 'switch-settings', '--auto-off', 'off', '--power-limit', '2000', '--yes')],
          'the console\'s settings change: %r' % c.acts)
    c = Seen(known, {'power_on': 'restore_last', 'auto_off': '600', 'power_limit': ''})
    zigmon.Console.plug_switch_settings(c, 'Lamp')
    check(c.acts == [] and c.notes == ['Nothing changed.'], 'the console sent an unchanged form: %r' % c.acts)
    print('the console: an update or a change only after a yes, and only what changed')
finally:
    server.shutdown()
    try:
        d.store.close()
    except Exception:
        pass
    shutil.rmtree(W, ignore_errors=True)

if bad:
    print('%d FAILED' % len(bad))
    sys.exit(1)
print('all good')
