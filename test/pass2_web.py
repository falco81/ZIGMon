#!/usr/bin/env python3
"""5.44.1, pass 2: the relay against other sites, and the logs. Each check
here failed on 5.44.0:

  * a download of a key or a backup (and a settings export) is a GET, and a
    GET was never asked where it came from: another app on the same domain
    (Sec-Fetch-Site: same-site - the Strict cookie goes with it) loaded
    ?api=proxy-key-download with the administrator's cookie, and each was an
    alarm and a hand-over taken away; the page's own fetch (same-origin) and
    a request that says nothing (curl, a shortcut) still get it;
  * with debug on, the body of a call to a Shelly was written down whole -
    MQTT.SetConfig carries the broker's password ("pass"); with debug_events
    on, an MQTT payload with a password in it was an event, shown in the page;
    a payload cut short in the middle of a password showed the first part;
  * install.sh wrote config.json (the broker password) under the default
    umask, 0644 until the chmod after it.

    python3 test/pass2_web.py

Ports 19360 (the daemon), 19361 (php -S), 19362 (a Shelly lookalike).
"""
import http.server
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

HERE = Path(os.environ.get('ZIGMON_HUNT_HERE') or Path(__file__).resolve().parent.parent)
W = Path(tempfile.mkdtemp(prefix='zigmon-pass2-web-'))
API_PORT, PHP_PORT, BOX_PORT = 19360, 19361, 19362
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
            p.terminate()
            p.wait(5)
        except Exception:                               # noqa: BLE001
            try:
                p.kill()
            except Exception:                           # noqa: BLE001
                pass
    shutil.rmtree(str(W), ignore_errors=True)
    print('pass2_web: %s' % ('%d failed' % len(bad) if bad else 'all good'))
    sys.stdout.flush()
    os._exit(1 if bad else 0)


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'run' / 'api-token'), 'pin': '', 'plugs': [], 'sensors': [],
                      'mqtt_host': '', 'log_file': str(W / 'zigmon.log'), 'log_to_journal': False,
                      'state_dir': str(W / 'state'), 'login_tries': 5, 'login_wait_min': 15,
                      'session_idle_min': 240, 'session_hours': 720, 'public_view': True})
(W / 'state').mkdir()
try:
    zigmon.open_log()
    d = zigmon.Daemon()
    api = zigmon.ApiServer(d)
    api.start()
    time.sleep(0.3)
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
except Exception as e:                                  # noqa: BLE001
    check(False, 'the daemon could not be started: %s' % e)
    finish()


def daemon_login():
    h = {'Content-Type': 'application/json', 'X-Zigmon-Token': d.token, 'X-Zigmon-Client': '192.168.40.10'}
    r = urllib.request.Request('http://127.0.0.1:%d/api/auth/login' % API_PORT, headers=h, method='POST',
                               data=json.dumps({'name': 'owner', 'password': 'owner pass 12'}).encode())
    with urllib.request.urlopen(r, timeout=30) as x:
        return json.loads(x.read()).get('token', '')


def get(path, headers=None):
    r = urllib.request.Request('http://127.0.0.1:%d/index.php%s' % (PHP_PORT, path), headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=30) as x:
            return x.status, x.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')


try:
    T_OWNER = daemon_login()
    check(T_OWNER, 'the administrator of the test could not sign in')

    # ---- the relay: a download asked for by another site ---------------------------------
    print('a download asked for by another app on the same domain')
    php = shutil.which('php')
    if not php:
        print('  (no php here: the relay is not checked)')
    else:
        web = W / 'web'
        shutil.copytree(str(HERE / 'web'), str(web))
        api_php = web / 'zigmon-api.php'
        api_php.write_text(api_php.read_text()
                           .replace('const ZIGMON_PORT  = 9849;', 'const ZIGMON_PORT  = %d;' % API_PORT)
                           .replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';",
                                    "const ZIGMON_TOKEN = '%s';" % (W / 'run' / 'api-token')))
        srv = subprocess.Popen([php, '-S', '127.0.0.1:%d' % PHP_PORT, '-t', str(web)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        PROCS.append(srv)
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        KEY = '-----BEGIN OPENSSH PRIVATE KEY-----\npass2web-private-half\n-----END OPENSSH PRIVATE KEY-----\n'
        d.store.set_meta('proxy_key', KEY)
        cookie = {'Cookie': 'zigmon_session=' + T_OWNER}
        for site in ('same-site', 'cross-site'):
            c, text = get('?api=proxy-key-download', dict(cookie, **{'Sec-Fetch-Site': site,
                                                                       'Sec-Fetch-Mode': 'no-cors',
                                                                       'Sec-Fetch-Dest': 'image'}))
            check(c == 403 and 'pass2web-private-half' not in text,
                  'a key download asked for %s was answered %s %r' % (site, c, text[:60]))
        c, text = get('?api=export&secrets=1', dict(cookie, **{'Sec-Fetch-Site': 'same-site'}))
        check(c == 403, 'a settings export with its secrets asked for same-site was answered %s' % c)
        c, text = get('?api=tls-download&file=zigmon-cert-house.pem', dict(cookie, Origin='https://red.example.org'))
        check(c == 403, 'a certificate download with another site\'s Origin was answered %s' % c)
        # the page's own fetch, and a request that says nothing, as before
        c, text = get('?api=proxy-key-download', dict(cookie, **{'Sec-Fetch-Site': 'same-origin'}))
        check(c == 200 and 'pass2web-private-half' in text,
              'the page\'s own key download (same-origin) was answered %s %r' % (c, text[:60]))
        c, text = get('?api=proxy-key-download', cookie)
        check(c == 200 and 'pass2web-private-half' in text,
              'a key download that says nothing of where it came from was answered %s %r' % (c, text[:60]))
        c, text = get('?api=export', dict(cookie, **{'Sec-Fetch-Site': 'same-origin'}))
        check(c == 200 and text.startswith('{'), 'the page\'s own settings export was answered %s' % c)
        c, text = get('?api=status', {'Sec-Fetch-Site': 'same-site'})
        check(c == 200, 'a status read from the same site (no download) was refused: %s' % c)

    # ---- the logs: a password in a body, under debug -------------------------------------
    print('a password in a body a debug line shows')
    seen = []

    class Box(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(self.rfile.read(int(self.headers.get('Content-Length') or 0)))
            body = b'{"id":1,"result":{"restart_required":false}}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    box = http.server.ThreadingHTTPServer(('127.0.0.1', BOX_PORT), Box)
    threading.Thread(target=box.serve_forever, daemon=True).start()
    zigmon.CONFIG.update({'debug': True, 'debug_events': True, 'debug_secrets': False})
    BROKER_PW = 'pass2web-broker-password'
    try:
        zigmon.ShellyRPC('127.0.0.1:%d' % BOX_PORT, '', 0, label='box').call(
            'MQTT.SetConfig', {'config': {'enable': True, 'user': 'plug', 'pass': BROKER_PW}})
    except Exception as e:                              # noqa: BLE001
        check(False, 'the call to the Shelly lookalike failed: %s' % e)
    check(seen and BROKER_PW.encode() in seen[0], 'the Shelly lookalike was not sent the password at all')
    d.debug('shelly: MQTT.SetConfig over MQTT', 'x/rpc %s'
            % json.dumps({'config': {'user': 'plug', 'pass': BROKER_PW}}))
    # a payload cut at 300 characters in the middle of a password
    d.debug('MQTT in  zigbee2mqtt/bridge/info', '{"config":{"mqtt":{"user":"z2m","password":"%s'
            % BROKER_PW[:16])
    zigmon.log_drain()
    text = (W / 'zigmon.log').read_text(encoding='utf-8', errors='replace')
    check('MQTT.SetConfig' in text, 'the debug log did not say the call at all')
    check(BROKER_PW not in text and BROKER_PW[:16] not in text,
          'the debug log carries the broker password: %r'
          % [x for x in text.splitlines() if BROKER_PW[:16] in x][:2])
    evs = json.dumps(d.store.events(limit=500, kind='debug'), default=str)
    check('MQTT.SetConfig' in evs, 'the debug event was not written at all')
    check(BROKER_PW[:16] not in evs, 'an event (shown in the page) carries the broker password')
    # debug_secrets: the owner asked for the log whole, and gets it; the events never
    zigmon.CONFIG['debug_secrets'] = True
    check(BROKER_PW in zigmon.debug_cut('{"pass":"%s"}' % BROKER_PW),
          'with debug_secrets on, a body is no longer shown whole')
    zigmon.CONFIG.update({'debug': False, 'debug_events': False, 'debug_secrets': False})
    box.shutdown()
    box.server_close()

    # ---- install.sh: config.json is never readable by everybody ---------------------------
    print('install.sh writes config.json under a tight umask')
    sh = (HERE / 'install.sh').read_text()
    at = sh.find('python3 - "$SOURCE_DIR/deploy/config.json" "$CONFIG_FILE"')
    check(at > 0 and re.search(r'umask 0?77\s*$', sh[max(0, at - 300):at].rstrip() + '\n', re.M)
          is not None, 'config.json (the broker password) is written under the default umask, 0644 '
                       'until the chmod after it')
except Exception as e:                                  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(False, 'the checks stopped on %s: %s' % (type(e).__name__, e))
finish()
