#!/usr/bin/env python3
"""5.59: ZIGMon for Stream Deck against the real ZIGMon - the plugin's own core (streamdeck/src/core,
compiled with its tsc) driven by test/review559_deck_plugin.mjs through the real PHP relay to the
real daemon. Nothing of either side is faked but the house's devices: a socket and a Zigbee
command are answered as the device would answer (its new state reported back), one level below
the executor every one-tap link goes through.

  pairing (the code on the keys, the same in ZIGMon's request) -> approved by the administrator
  with permissions -> the key kept encrypted -> hello, catalogue, states -> a socket and a Zigbee
  light toggled -> dials: brightness, a room's temperature and a head's set point -> the head's
  mode cycled, its boost -> the blinds -> a scene -> the status keys -> the long poll redrawing a
  change -> a deck not approved (deck_pending, then approved in ZIGMon and used) -> a hold (409,
  then held_ms) -> permissions changed under a waiting plugin -> an update, signed with a
  throwaway key, downloaded and checked -> revoked: the plugin forgets its key.

The keys drawn for the real catalogue are rendered to PNG into $ZIGMON_SHOTS (or a temporary
folder). Skipped cleanly without node, the plugin's node_modules (npm ci is tried), openssl or
a browser for the PNGs (then the SVGs are still written).

    python3 test/review559_deck_plugin.py < /dev/null

Ports 20270-20279. Every key, token and secret here is made up.
"""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SD = HERE / 'streamdeck'
W = Path(tempfile.mkdtemp(prefix='zigmon-deckplug-'))
API_PORT, PHP_PORT, CTL_PORT = 20270, 20271, 20272
SHOTS = Path(os.environ.get('ZIGMON_SHOTS') or tempfile.mkdtemp(prefix='zigmon-deckplug-shots-'))


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


def skip(why):
    print('SKIPPED: ' + why)
    shutil.rmtree(W, ignore_errors=True)
    sys.exit(0)


if not shutil.which('node') or not shutil.which('php') or not (SD / 'package.json').is_file():
    skip('no node, no php or no streamdeck/ here')
if not shutil.which('openssl'):
    skip('no openssl')
# the plugin's core, compiled by its own tsc (as its build.sh does for its tests)
if not (SD / 'node_modules' / 'typescript').is_dir():
    r = sh(['npm', 'ci', '--no-audit', '--no-fund'], cwd=str(SD), timeout=600)
    if r.returncode != 0:
        skip('npm ci failed in streamdeck/: %s' % (r.stdout + r.stderr)[-300:])
r = sh(['npx', 'tsc', '-p', 'tsconfig.test.json'], cwd=str(SD), timeout=600)
if r.returncode != 0 or not (SD / 'out' / 'src' / 'core' / 'hub.js').is_file():
    print('the plugin does not compile:\n' + (r.stdout + r.stderr)[-2000:])
    sys.exit(1)

for _p in (API_PORT, PHP_PORT, CTL_PORT):
    for _ in range(60):
        _s = socket.socket()
        try:
            _s.bind(('127.0.0.1', _p))
            _s.close()
            break
        except OSError:
            _s.close()
            time.sleep(2)
    else:
        print('port %d stays busy' % _p)
        sys.exit(2)

# ---- a throwaway release key, and the plugin as ZIGMon offers it (1.0.1, newer than the plugin) ----
KEY, PUB = W / 'release.key', W / 'release.pub'
if sh(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', str(KEY)]).returncode != 0:
    skip('openssl has no Ed25519 here')
sh(['openssl', 'pkey', '-in', str(KEY), '-pubout', '-out', str(PUB)])
raw_pub = subprocess.run(['openssl', 'pkey', '-pubin', '-in', str(PUB), '-outform', 'DER'], capture_output=True,
                         stdin=subprocess.DEVNULL).stdout[-32:].hex()
DIST = W / 'dist'
DIST.mkdir()
PLUGIN = b'PK\x03\x04' + os.urandom(64 * 1024) + b'a made-up ZIGMon for Stream Deck 1.0.1'
(DIST / 'com.zigmon.streamdeck.streamDeckPlugin').write_bytes(PLUGIN)
(DIST / 'plugin.json').write_bytes((json.dumps({
    'product': 'ZIGMon for Stream Deck', 'file': 'com.zigmon.streamdeck.streamDeckPlugin', 'version': '1.0.1',
    'size': len(PLUGIN), 'sha256': hashlib.sha256(PLUGIN).hexdigest(), 'requires': 'Stream Deck 7.1, Windows 10/11'},
    separators=(',', ':')) + '\n').encode())
sh(['openssl', 'pkeyutl', '-sign', '-inkey', str(KEY), '-rawin', '-in', str(DIST / 'plugin.json'),
    '-out', str(DIST / 'plugin.json.sig')])

# ---- the real daemon -------------------------------------------------------------------------------
sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                               # noqa: E402

LOG = []
_real_log = zigmon.log
zigmon.log = lambda msg, level='info', *a, **k: LOG.append('%s %s' % (level, msg))
zigmon.load_config()
(W / 'state').mkdir()
zigmon.CONFIG.update({
    'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1', 'token_file': str(W / 'token'),
    'pin': '', 'sensors': [], 'plugs': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(W / 'state'),
    'debug': 0, 'blacklist': 0, 'public_view': False, 'deck_dir': str(DIST)})
d = zigmon.Daemon()
d.notify = lambda message, *a, **k: None
# php -S, the relay here, may let one worker take two connections that arrive together, and a
# long poll then holds the other behind it (php-fpm under nginx does not): short waits here, so a
# command that met a wait starting is late by seconds, not by the whole 25
d.DECK_WAIT_S = 3.0
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)

FIRED = []
BULB, THERMO, BLIND, TEMP = '0x00158d0003000001', '0x00158d0003000002', '0x00158d0003000003', '0x00158d0003000004'
NAMES = {BULB: 'Zarovka', THERMO: 'Hlavice', BLIND: 'Roleta', TEMP: 'Teplomer'}


def report(name, payload):
    d.handle_zigbee(name, json.dumps(payload).encode())


def _run_binding(p, do, origin, pulse_ms=None, stagger=0.0):
    """A socket answering as a Shelly does: switched, and polled at once."""
    FIRED.append(['plug', p.name, do, origin])
    was = bool((p.flat or {}).get('switch.output'))
    now = (not was) if do == 'toggle' else do == 'on'
    p.flat = dict(p.flat or {}, **{'switch.output': now, 'switch.apower': 41.0 if now else 0.0})
    p.output_at = time.time()
    d.bump()


def _run_zigbee_switch(dev, key, do, origin, pulse_ms=None):
    """Zigbee2MQTT and the device: the command, then the device's own report of its new state."""
    FIRED.append(['zb', dev, key, do, origin])
    now = (d.live.get(dev) or {}).get('payload') or {}
    if do in ('on', 'off', 'toggle'):
        cur = str(now.get(key) or 'OFF').upper()
        new = ('OFF' if cur == 'ON' else 'ON') if do == 'toggle' else do.upper()
    else:
        raw = str(do)[4:].lstrip('=')
        try:
            new = int(raw) if raw.lstrip('-').isdigit() else float(raw)
        except ValueError:
            new = raw
    extra = {}
    if key == 'state' and new in ('OPEN', 'CLOSE'):
        extra = {'position': 100 if new == 'OPEN' else 0}
    if key == 'state' and new == 'STOP':
        return
    report(NAMES[dev], dict({key: new}, **extra))


d._run_binding = _run_binding
d._run_zigbee_switch = _run_zigbee_switch
d.run_scene = lambda sid, origin='', *a, **k: FIRED.append(['scene', sid, origin])
d.system_action = lambda what, do='on', origin='': FIRED.append(['sys', what, do, origin])


class Control(BaseHTTPRequestHandler):
    """What the node script asks of the house: what was fired, a device reporting, a socket polled."""

    def log_message(self, *a):
        pass

    def _send(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/fired':
            return self._send(FIRED)
        if self.path == '/log':
            return self._send(LOG[-400:])
        if self.path == '/stacks':
            import traceback
            return self._send([''.join(traceback.format_stack(f)[-6:]) for f in sys._current_frames().values()])
        self._send({'error': 'what?'})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        if self.path == '/report':
            report(body['name'], body['payload'])
        elif self.path == '/plug':
            p = d.plugs[body['name']]
            p.flat = dict(p.flat or {}, **body['flat'])
            d.bump()
        elif self.path == '/alert':
            d.raise_alert(body['text'])
        self._send({'ok': True})


ctl = ThreadingHTTPServer(('127.0.0.1', CTL_PORT), Control)
threading.Thread(target=ctl.serve_forever, daemon=True).start()
php = None
code = 1
try:
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    req = urllib.request.Request('http://127.0.0.1:%d/api/auth/login' % API_PORT, method='POST',
                                 data=json.dumps({'name': 'owner', 'password': 'owner pass 12'}).encode(),
                                 headers={'X-Zigmon-Token': d.token, 'Content-Type': 'application/json',
                                          'X-Zigmon-Client': '192.168.40.10'})
    with urllib.request.urlopen(req, timeout=20) as r:
        SESSION = json.loads(r.read())['token']

    # ---- the house: two sockets, a bulb, a head, a blind, a thermometer, rooms, a scene ----
    d.store.set_meta('managed', json.dumps({'plugs': [
        {'name': 'Lampa', 'host': '127.0.0.1:1', 'switch_id': 0, 'kind': 'plug', 'role': 'light', 'host_state': 'enabled'},
        {'name': 'Zasuvka', 'host': '127.0.0.1:2', 'switch_id': 0, 'kind': 'plug', 'host_state': 'enabled'}],
        'sensors': []}))
    d.reload_devices()
    d.plugs['Lampa'].flat = {'switch.output': False, 'switch.apower': 0.0}
    d.plugs['Zasuvka'].flat = {'switch.output': True, 'switch.apower': 35.25}
    for p in d.plugs.values():
        p.error = None
    for ident, exposes in (
            (BULB, {'state': {'access': 7, 'type': 'binary'},
                    'brightness': {'access': 7, 'type': 'numeric', 'min': 0, 'max': 254},
                    'color_temp': {'access': 7, 'type': 'numeric', 'min': 153, 'max': 500}}),
            (THERMO, {'current_heating_setpoint': {'access': 7, 'type': 'numeric', 'min': 5, 'max': 30, 'unit': '°C'},
                      'system_mode': {'access': 7, 'type': 'enum', 'values': ['off', 'heat', 'auto']},
                      'preset': {'access': 7, 'type': 'enum', 'values': ['manual', 'schedule', 'holiday', 'boost']},
                      'boost_heating': {'access': 7, 'type': 'binary'},
                      'local_temperature': {'access': 1, 'type': 'numeric', 'unit': '°C'}}),
            (BLIND, {'state': {'access': 7, 'type': 'enum', 'values': ['OPEN', 'CLOSE', 'STOP']},
                     'position': {'access': 7, 'type': 'numeric', 'min': 0, 'max': 100, 'unit': '%'}}),
            (TEMP, {'temperature': {'access': 1, 'type': 'numeric', 'unit': '°C'},
                    'humidity': {'access': 1, 'type': 'numeric', 'unit': '%'}})):
        d.store.upsert_device({'id': ident, 'name': NAMES[ident], 'source': 'zigbee', 'kind': 'EndDevice',
                               'exposes': exposes})
        d.names[NAMES[ident]] = ident
    report('Zarovka', {'state': 'ON', 'brightness': 127, 'color_temp': 300})
    report('Hlavice', {'current_heating_setpoint': 21, 'system_mode': 'heat', 'preset': 'manual', 'boost_heating': 'OFF',
                       'local_temperature': 20.5, 'battery': 77})
    report('Roleta', {'state': 'OPEN', 'position': 40})
    report('Teplomer', {'temperature': 21.5, 'humidity': 40, 'battery': 90})
    d.store.set_meta('rooms', json.dumps([{'id': 'r1', 'name': 'Obývák'}, {'id': 'r2', 'name': 'Ložnice'}]))
    d.store.set_meta('room_of', json.dumps({'Lampa': 'r1', BULB: 'r1', TEMP: 'r2', THERMO: 'r2', BLIND: 'r1'}))
    d.store.set_meta('scenes', json.dumps([{'id': 'sc1', 'name': 'Večer', 'actions': [{'target': 'Lampa', 'do': 'on'}]}]))
    d.store.set_meta('active_alerts', json.dumps([{'id': 'a1', 'ts': int(time.time()), 'text': 'Leak in the bathroom'}]))
    d.store.set_meta('deck_enabled', '1')

    # ---- the real relay ------------------------------------------------------------------------
    shutil.copytree(HERE / 'web', W / 'web')
    api_php = (W / 'web' / 'zigmon-api.php').read_text()
    api_php = api_php.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
    api_php = api_php.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
    (W / 'web' / 'zigmon-api.php').write_text(api_php)
    php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, str(W / 'web' / 'index.php')], cwd=str(W / 'web'),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                           env=dict(os.environ, PHP_CLI_SERVER_WORKERS='8'))
    for _ in range(50):
        try:
            socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)

    SHOTS.mkdir(parents=True, exist_ok=True)
    job = {'relay': 'http://127.0.0.1:%d' % PHP_PORT, 'daemon': 'http://127.0.0.1:%d' % API_PORT, 'token': d.token,
           'session': SESSION, 'control': 'http://127.0.0.1:%d' % CTL_PORT, 'core': str(SD / 'out'), 'shots': str(SHOTS),
           'releaseKey': raw_pub, 'plugin_sha': hashlib.sha256(PLUGIN).hexdigest(), 'plugin_size': len(PLUGIN),
           'bulb': BULB, 'thermo': THERMO, 'blind': BLIND, 'temp': TEMP, 'tmp': str(W)}
    npm_root = sh(['npm', 'root', '-g']).stdout.strip()
    run = subprocess.run(['node', str(HERE / 'test' / 'review559_deck_plugin.mjs')], stdin=subprocess.DEVNULL,
                         env=dict(os.environ, DECK_JOB=json.dumps(job), NODE_PATH=npm_root), timeout=900)
    code = run.returncode
finally:
    if php is not None:
        php.terminate()
        try:
            php.wait(5)
        except subprocess.TimeoutExpired:
            php.kill()
    ctl.shutdown()
    try:
        api.stop()
    except Exception:                                       # noqa: BLE001
        pass
    zigmon.log = _real_log
    shutil.rmtree(W, ignore_errors=True)
print('all good' if code == 0 else 'FAILED (%s)' % code)
sys.exit(code)
