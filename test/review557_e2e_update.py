#!/usr/bin/env python3
"""5.57: ZIGMon Notifier's self-update end to end - the app's own client (windows/tools/Probe
--update-check) against a running daemon behind the PHP relay, with the app in the package:

  * hello says which app version the server carries;
  * /update hands over the signed description; signed by a key the app trusts it is VERIFIED,
    then downloaded through the relay and its sha256 checked;
  * with only the app's embedded release keys, a description signed by another key is REJECTED;
  * the key is never in the app's output.

Skipped (passes) where dotnet or openssl is not installed. A throwaway Ed25519 key only.

    python3 test/review557_e2e_update.py < /dev/null

Ports 20186-20187.
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
API_PORT, PHP_PORT = 20186, 20187
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
DIST = W / 'dist'
KEYS = W / 'keys'
try:
    if not (shutil.which('dotnet') and shutil.which('openssl')):
        print('review557_e2e_update: dotnet or openssl is not here - checked where they are')
        raise SystemExit(0)
    DIST.mkdir(); KEYS.mkdir()
    VER = json.loads((HERE / 'windows' / 'dist' / 'notifier.json').read_text())['version']
    exe = (HERE / 'windows' / 'dist' / 'ZigmonNotifier.exe').read_bytes()
    (DIST / 'ZigmonNotifier.exe').write_bytes(exe)
    (DIST / 'notifier.json').write_bytes((HERE / 'windows' / 'dist' / 'notifier.json').read_bytes())
    sh(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', str(W / 'tk.key')])
    sh(['openssl', 'pkey', '-in', str(W / 'tk.key'), '-pubout', '-out', str(KEYS / 'throwaway.pub')])
    r = sh(['openssl', 'pkeyutl', '-sign', '-inkey', str(W / 'tk.key'), '-rawin', '-in', str(DIST / 'notifier.json'), '-out', str(DIST / 'notifier.json.sig')])
    check(r.returncode == 0, r.stderr)
    zigmon.CONFIG['notifier_dir'] = str(DIST)
    built = sh(['dotnet', 'build', str(PROBE), '-c', 'Release', '-o', str(OUT), '-nologo', '-v', 'q'], timeout=900)
    check(built.returncode == 0, built.stdout[-800:])
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
    # (5.59.1) the desktop app comes switched off: an administrator switches it on first
    call('/api/notifier/keys', {'action': 'enable'}, session=S)
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'Office PC', 'devices': []}, session=S)
    KEY = out.get('key') or ''
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
            socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close(); break
        except OSError:
            time.sleep(0.1)
    def probe(env_keys):
        env = dict(os.environ)
        if env_keys: env['ZIGMON_PROBE_KEYS'] = str(KEYS)
        else: env.pop('ZIGMON_PROBE_KEYS', None)
        p = subprocess.run(['dotnet', str(OUT / 'Probe.dll'), '--update-check'], input='http://127.0.0.1:%d\n%s\n' % (PHP_PORT, KEY),
                           capture_output=True, text=True, timeout=120, env=env)
        return p
    p = probe(True)
    sha = hashlib.sha256(exe).hexdigest()
    check(p.returncode == 0 and 'UPDATE %s VERIFIED' % VER in p.stdout and ('DOWNLOADED ' + sha) in p.stdout, 'throwaway key')
    check('app=%s' % VER in p.stdout, 'hello app')
    p = probe(False)
    check(p.returncode == 1 and 'UPDATE REJECTED' in p.stdout, 'embedded key must reject the throwaway signature')
    check(KEY not in p.stdout, 'key printed')
finally:
    for p in PROCS:
        try: p.kill()
        except Exception: pass
    api.stop() if hasattr(api, 'stop') else None
    shutil.rmtree(str(W), ignore_errors=True)
print('review557_e2e_update: ' + ('all good' if not bad else '%d FAILED' % len(bad)))
sys.exit(1 if bad else 0)
