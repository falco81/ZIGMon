#!/usr/bin/env python3
"""5.57: ZIGMon Notifier end to end - the Windows app's own client (windows/ZigmonNotifier.Core,
run through windows/tools/Probe on .NET) against a running daemon behind the PHP relay:

  * a key made by an administrator; the app says hello and reads the sensors as the house has them;
  * the app in its long poll hears a door opening and a PIR seeing motion, with the room;
  * the key is in neither the app's output nor the daemon's log (debug on).

Skipped (passes) where dotnet is not installed.

    python3 test/review557_e2e.py < /dev/null

Ports 20160-20161. Every secret here is made up.
"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-notifier-'))
API_PORT, PHP_PORT = 20160, 20161
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                               # noqa: E402

LOG = []
_real_log = zigmon.log


def _log(msg, level='info', *a, **k):
    LOG.append('%s %s' % (level, msg))


zigmon.log = _log
zigmon.load_config()
(W / 'state').mkdir()
zigmon.CONFIG.update({
    'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1', 'token_file': str(W / 'token'),
    'pin': '', 'sensors': [], 'plugs': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(W / 'state'),
    'debug': 1, 'blacklist': 0, 'public_view': False})
d = zigmon.Daemon()
d.notify = lambda message, *a, **k: None
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def call(path, body=None, session=None, key=None, client='192.168.40.10', timeout=60):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': client}
    if session:
        headers['X-Zigmon-Session'] = session
    if key is not None:
        headers['X-Zigmon-Notifier'] = key
    if body is not None and session:
        body = dict(body, session=session)
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                 data=None if body is None else json.dumps(body).encode(),
                                 method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def report(name, payload):
    d.handle_zigbee(name, json.dumps(payload).encode())



PROBE = HERE / 'windows' / 'tools' / 'Probe'
OUT = W / 'probe'
try:
    if not shutil.which('dotnet'):
        print('review557_e2e: dotnet is not here - the Windows app\'s client is checked where it is')
        sys.exit(0)
    built = sh(['dotnet', 'build', str(PROBE), '-c', 'Release', '-o', str(OUT), '-nologo', '-v', 'q'], timeout=900)
    if not check(built.returncode == 0, 'the probe does not build: %s' % built.stdout[-800:]):
        raise SystemExit
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
    PIR, DOOR = '0x00158d0001a2b3c4', '0x00158d0001a2b3c5'
    for ident, name, exposes in ((PIR, 'PIR-Chodba', {'occupancy': {}}), (DOOR, 'Dvere-Vchod', {'contact': {}})):
        d.store.upsert_device({'id': ident, 'name': name, 'source': 'zigbee', 'kind': 'EndDevice', 'exposes': exposes})
        d.names[name] = ident
    d.store.set_meta('rooms', json.dumps([{'id': 'r1', 'name': 'Hallway'}]))
    d.store.set_meta('room_of', json.dumps({PIR: 'r1'}))
    report('PIR-Chodba', {'occupancy': False, 'battery': 87})
    report('Dvere-Vchod', {'contact': True, 'battery': 64})
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'Office PC', 'devices': []}, session=S)
    KEY = out.get('key') or ''
    check(code == 200 and KEY.startswith('zmn_'), 'no key made: %s %r' % (code, out))
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
    probe = subprocess.Popen(['dotnet', str(OUT / 'Probe.dll'), 'PIR-Chodba'], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    PROCS.append(probe)
    probe.stdin.write('http://127.0.0.1:%d\n%s\n' % (PHP_PORT, KEY))
    probe.stdin.close()
    lines = []
    reader = threading.Thread(target=lambda: lines.extend(iter(probe.stdout.readline, '')), daemon=True)
    reader.start()
    end = time.time() + 60
    while time.time() < end and not any(x.startswith('STATUS Connected') for x in lines):
        time.sleep(0.2)
    check(any(x.startswith('HELLO api=1 server=zigmon key=Office PC') for x in lines), 'no hello: %r' % lines)
    check(any(x.startswith('SENSORS') and 'PIR-Chodba:motion:False' in x and 'Dvere-Vchod:contact:False' in x
              for x in lines), 'the sensors are not as the house has them: %r' % lines)
    time.sleep(1.5)                                 # the app is in its long poll now
    report('Dvere-Vchod', {'contact': False})        # the door opens
    report('PIR-Chodba', {'occupancy': True})
    try:
        probe.wait(60)
    except subprocess.TimeoutExpired:
        pass
    reader.join(5)
    text = ''.join(lines)
    check(probe.returncode == 0 and 'DONE' in text, 'the app never heard the PIR: %r' % text[-1500:])
    check('EVENT Dvere-Vchod contact contact True opened' in text, 'the door opening was not heard: %r' % text)
    check('EVENT PIR-Chodba motion occupancy True motion room=Hallway' in text, 'the motion was not heard: %r' % text)
    check(KEY not in text, 'the app printed its key')
    check(not any(KEY in x for x in LOG), 'the daemon wrote the key into its log')
finally:
    for p in PROCS:
        try:
            p.kill()
        except Exception:
            pass
    api.stop() if hasattr(api, 'stop') else None
    shutil.rmtree(str(W), ignore_errors=True)

print('review557_e2e: ' + ('all good' if not bad else '%d FAILED' % len(bad)))
sys.exit(1 if bad else 0)
