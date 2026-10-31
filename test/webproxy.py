#!/usr/bin/env python3
"""Control - Proxy (5.35, ported from otp 1.0.166 - 1.0.169): the way out to
the web through an HTTP proxy, for one machine.

  * a proxy of its own (CONNECT and plain forwarding, Basic auth) and a
    target over HTTP and over HTTPS (a CA of the test's own), all started
    here and stopped here;
  * what zigmon asks of the web goes through the proxy when it is on - with
    the user name and password, over a tunnel for https - and straight when
    it is off, when the address is in the list, and when the address is one
    of this network's own; a wrong password is said as such;
  * Try it: every step, each with its time, the way it went (this machine,
    the proxy, the address), the step where it stopped and why;
  * dnf handed the proxy: in root's ask, kept by root in a file only root
    reads (0600), given to dnf in its environment - never on its command
    line, never in osup.json or osup.log; the file gone when the proxy is;
  * the settings checked; the password never in the page's view, the API's
    answers, the events or the log; the API an administrator's; the relay,
    the command line (--webproxy-test) and the console;
  * the real page (php -S) in Chromium: Proxy right after Network, its two
    cards, the settings drawn into the first, the way drawn in the second.

    python3 test/webproxy.py

Ports 19965 (the proxy), 19966 (the target over HTTP), 19967 (over HTTPS),
19968 (the daemon), 19969 (php -S).
"""
import base64
import contextlib
import io
import json
import os
import re
import shutil
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ROOT_HELPER = HERE / 'deploy' / 'zigmon_root.py'
W = Path(tempfile.mkdtemp(prefix='zigmon-webproxy-check-'))
PROXY_PORT, HTTP_PORT, HTTPS_PORT, API_PORT, PHP_PORT = 19965, 19966, 19967, 19968, 19969
USER, PASSWORD = 'house', 'Sn0w:fl@ke/9 x'          # a password with what an address must quote
WRONG = 'not-the-password-77'
PROXY_URL = 'http://127.0.0.1:%d' % PROXY_PORT
# names only the proxy knows: zigmon cannot look them up, the proxy sends them home
WEB = '.zigmon.invalid'
bad = []

# the proxy of the environment (the machine the checks run on may have one)
# is not this test's: what goes straight must go straight
for _k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'no_proxy', 'NO_PROXY',
           'all_proxy', 'ALL_PROXY'):
    os.environ.pop(_k, None)


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


# ---- a CA and the target's certificate --------------------------------------------------
HAVE_TLS = bool(shutil.which('openssl'))
CA, CERT, KEY = W / 'ca.pem', W / 'cert.pem', W / 'key.pem'
if HAVE_TLS:
    def ossl(*a):
        subprocess.run(['openssl'] + list(a), cwd=str(W), check=True, capture_output=True,
                       stdin=subprocess.DEVNULL)
    ossl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'ca.key', '-out', 'ca.pem',
         '-days', '2', '-subj', '/CN=zigmon webproxy test CA/O=The test CA',
         '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
    ossl('req', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'key.pem', '-out', 'req.csr',
         '-subj', '/CN=versions.zigmon.invalid')
    (W / 'ext.cnf').write_text('subjectAltName=DNS:versions.zigmon.invalid,IP:127.0.0.1\n'
                               'keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n'
                               'subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n')
    ossl('x509', '-req', '-in', 'req.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key', '-CAcreateserial',
         '-out', 'cert.pem', '-days', '2', '-extfile', 'ext.cnf')

# ---- the target ---------------------------------------------------------------------------
SEEN = []          # (port, method, path, came through the proxy)
PROXIED = []       # (method, target, auth as sent or None)


class Target(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class TargetHandler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            line = self.rfile.readline(4096).decode('latin-1').strip()
            heads = {}
            while True:
                h = self.rfile.readline(4096).decode('latin-1')
                if h in ('\r\n', '\n', ''):
                    break
                k, _, v = h.partition(':')
                heads[k.strip().lower()] = v.strip()
            parts = line.split()
            if len(parts) < 2:
                return
            n = int(heads.get('content-length') or 0)
            if n:
                self.rfile.read(n)
            SEEN.append((self.server.server_address[1], parts[0], parts[1], heads.get('via') == 'test-proxy'))
            body = b'hello from the target'
            self.wfile.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: %d\r\n'
                             b'Connection: close\r\n\r\n' % len(body) + (b'' if parts[0] == 'HEAD' else body))
        except (OSError, ValueError):
            pass


class TlsTarget(Target):
    def get_request(self):
        sock, addr = super().get_request()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(CERT), str(KEY))
        return ctx.wrap_socket(sock, server_side=True), addr


# ---- the proxy ----------------------------------------------------------------------------
def home(host):
    """Where the proxy sends a name: every name of the test's own web to here."""
    return '127.0.0.1' if host.endswith(WEB) or host == '127.0.0.1' else None


class ProxyHandler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            line = self.rfile.readline(8192).decode('latin-1').strip()
            raw_heads = []
            heads = {}
            while True:
                h = self.rfile.readline(8192).decode('latin-1')
                if h in ('\r\n', '\n', ''):
                    break
                raw_heads.append(h)
                k, _, v = h.partition(':')
                heads[k.strip().lower()] = v.strip()
            parts = line.split()
            if len(parts) < 3:
                return
            method, target = parts[0], parts[1]
            auth = heads.get('proxy-authorization')
            PROXIED.append((method, target, auth))
            want = 'Basic ' + base64.b64encode(('%s:%s' % (USER, PASSWORD)).encode()).decode()
            if auth != want:
                self.wfile.write(b'HTTP/1.1 407 Proxy Authentication Required\r\n'
                                 b'Proxy-Authenticate: Basic realm="test"\r\nContent-Length: 0\r\n'
                                 b'Connection: close\r\n\r\n')
                return
            if method == 'CONNECT':
                host, _, port = target.rpartition(':')
                to = home(host)
                if not to:
                    self.wfile.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n')
                    return
                up = socket.create_connection((to, int(port)), timeout=10)
                self.wfile.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
                self.wfile.flush()
                self.pump(self.connection, up)
                return
            m = re.match(r'^http://([^/:]+)(?::(\d+))?(/.*)?$', target)
            if not m or not home(m.group(1)):
                self.wfile.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                return
            up = socket.create_connection((home(m.group(1)), int(m.group(2) or 80)), timeout=10)
            keep = ''.join(h for h in raw_heads if not h.lower().startswith(('proxy-', 'connection')))
            up.sendall(('%s %s HTTP/1.1\r\n%sVia: test-proxy\r\nConnection: close\r\n\r\n'
                        % (method, m.group(3) or '/', keep)).encode('latin-1'))
            n = int(heads.get('content-length') or 0)
            if n:
                up.sendall(self.rfile.read(n))
            while True:
                chunk = up.recv(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
            up.close()
        except (OSError, ValueError):
            pass

    def pump(self, a, b):
        def one(x, y):
            try:
                while True:
                    chunk = x.recv(65536)
                    if not chunk:
                        break
                    y.sendall(chunk)
            except OSError:
                pass
            finally:
                for s in (x, y):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
        t = threading.Thread(target=one, args=(b, a), daemon=True)
        t.start()
        one(a, b)
        t.join(5)


servers = []
php = None
api = None
try:
    for cls, port, handler in ((Target, PROXY_PORT, ProxyHandler), (Target, HTTP_PORT, TargetHandler)) + \
            (((TlsTarget, HTTPS_PORT, TargetHandler),) if HAVE_TLS else ()):
        srv = cls(('127.0.0.1', port), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)

    # ---- the daemon, over a folder that stands in for the machine -------------------------
    STATE, ETC = W / 'state', W / 'etc'
    for p in (STATE / 'root', STATE / 'backups', STATE / 'upgrade', ETC / 'zigmon'):
        p.mkdir(parents=True, exist_ok=True)
    DB = STATE / 'history.db'
    (ETC / 'zigmon' / 'config.json').write_text(json.dumps({'db_file': str(DB)}))
    BIN = W / 'bin'
    BIN.mkdir()
    DNF_SAW = W / 'dnf-saw.json'
    (BIN / 'dnf').write_text('''#!%(py)s
import json, os, sys
saw = json.load(open(%(saw)r)) if os.path.exists(%(saw)r) else []
saw.append({'argv': sys.argv, 'env': {k: os.environ.get(k) for k in
            ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'no_proxy', 'NO_PROXY')}})
json.dump(saw, open(%(saw)r, 'w'))
if 'check-update' in sys.argv:
    sys.exit(0)
if 'needs-restarting' in sys.argv:
    sys.exit(0)
print('Complete!')
''' % {'py': sys.executable, 'saw': str(DNF_SAW)})
    (BIN / 'dnf').chmod(0o755)
    PROXY_FILE = W / 'run' / 'zigmon-osup-proxy.json'
    PROXY_FILE.parent.mkdir()
    LOG = W / 'zigmon.log'
    os.environ.update(ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(W / 'own'), ZIGMON_FULL_DIR=str(W / 'full'),
                      ZIGMON_CONFIG=str(ETC / 'zigmon' / 'config.json'), ZIGMON_NO_SERVICES='1',
                      ZIGMON_SERVICE_LOG=str(W / 'services.log'), ZIGMON_FS_ROOT=str(W), ZIGMON_USER='root',
                      ZIGMON_FW_FILE4=str(W / 'no4'), ZIGMON_FW_FILE6=str(W / 'no6'),
                      ZIGMON_FIREWALL_CMD=str(W / 'no-firewall-cmd'), ZIGMON_NGINX_TEST='true',
                      ZIGMON_ROOT_RUN='%s -I %s' % (sys.executable, ROOT_HELPER),
                      ZIGMON_OSUP_PATH='%s:/usr/bin:/bin' % BIN, ZIGMON_OSUP_LOCK=str(W / 'osup.lock'),
                      ZIGMON_OSUP_PROXY=str(PROXY_FILE), ZIGMON_POWER_CMD=str(W / 'power.log'))
    ROOT_DIR = STATE / 'root'

    sys.path.insert(0, str(HERE))
    sys.argv = ['zigmon']
    import zigmon                                       # noqa: E402

    zigmon.load_config()
    zigmon.CONFIG.update({'db_file': str(DB), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                          'token_file': str(W / 'token'), 'plugs': [], 'sensors': [], 'mqtt_host': '',
                          'log_file': str(LOG), 'state_dir': str(STATE)})
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
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')

    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
    S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
    S_OP = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''

    TLS_CTX = ssl.create_default_context(cafile=str(CA)) if HAVE_TLS else None

    def fetch(url, ctx=None):
        """(status or the error, the target's body) of one address the way
        zigmon asks the web."""
        try:
            with zigmon.web_open(url, timeout=10, context=ctx) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, ''
        except Exception as e:                          # noqa: BLE001
            return str(getattr(e, 'reason', '') or e), ''

    def settings(**kw):
        d.save_config_overrides(kw)

    # ---- the settings --------------------------------------------------------------------
    print('the settings')
    for k in ('webproxy', 'webproxy_url', 'webproxy_user', 'webproxy_password', 'webproxy_no', 'webproxy_os'):
        check(k in zigmon.DEFAULTS and k in zigmon.Daemon.TUNABLE, '%s is not a setting' % k)
    check(zigmon.DEFAULTS.get('webproxy') == 0, 'the proxy is not off until switched on')
    for key, value in (('webproxy_url', 'http://user:pw@proxy.example.cz:3128'),
                       ('webproxy_url', 'https://proxy.example.cz:3128'),
                       ('webproxy_url', 'proxy.example.cz:3128'), ('webproxy_url', 'http://a b:1'),
                       ('webproxy_user', 'me@there'), ('webproxy_user', 'a:b'),
                       ('webproxy_password', 'one\nline'), ('webproxy_no', 'a.cz; $(reboot)')):
        try:
            settings(**{key: value})
            check(False, '%s=%r was taken' % (key, value))
        except ValueError:
            pass
    settings(webproxy_url='http://proxy.example.cz:3128/', webproxy_no='localhost; .example.cz 10.0.0.0/8')
    check(zigmon.CONFIG['webproxy_no'] == 'localhost, .example.cz, 10.0.0.0/8',
          'the list reached straight is not kept as a list: %r' % zigmon.CONFIG['webproxy_no'])
    rc = d.runtime_config()
    check(rc['webproxy_password']['kind'] == 'secret' and rc['webproxy']['kind'] == 'switch'
          and rc['webproxy_os']['kind'] == 'switch' and rc['webproxy_url']['kind'] == 'text',
          'the settings are not drawn as what they are: %r' % {k: rc[k]['kind'] for k in rc if k.startswith('webproxy')})

    # ---- off: as it always was -----------------------------------------------------------
    print('off: straight')
    PROXIED.clear()
    settings(webproxy=0, webproxy_url=PROXY_URL, webproxy_user=USER, webproxy_password=PASSWORD,
             webproxy_no='localhost, 127.0.0.1, ::1')
    check(not zigmon.webproxy_on() and zigmon.webproxy_full() == '', 'the proxy is used while it is off')
    got = fetch('http://127.0.0.1:%d/off' % HTTP_PORT)
    check(got[0] == 200 and not PROXIED, 'with the proxy off it went through it: %r %r' % (got, PROXIED))
    got = fetch('http://plain%s:%d/off' % (WEB, HTTP_PORT))
    check(got[0] != 200 and not PROXIED, 'with the proxy off a name only the proxy knows was reached: %r' % (got,))
    x = zigmon.webproxy_try('http://127.0.0.1:%d/off' % HTTP_PORT)
    check(x['mode'] == 'direct' and x['why_direct'] == 'no proxy is set' and x['ok'],
          'Try it with the proxy off: %r' % {k: x.get(k) for k in ('mode', 'why_direct', 'ok')})

    # ---- on --------------------------------------------------------------------------------
    print('on: through the proxy, with the user name and password')
    settings(webproxy=1, webproxy_no='localhost')
    check(zigmon.webproxy_on(), 'the proxy is not on')
    PROXIED.clear()
    SEEN.clear()
    got = fetch('http://plain%s:%d/through' % (WEB, HTTP_PORT))
    want_auth = 'Basic ' + base64.b64encode(('%s:%s' % (USER, PASSWORD)).encode()).decode()
    check(got == (200, 'hello from the target'), 'over http through the proxy: %r' % (got,))
    check(PROXIED and PROXIED[0][0] == 'GET' and PROXIED[0][1].startswith('http://plain' + WEB)
          and PROXIED[0][2] == want_auth, 'the proxy was not asked, or not with the password: %r' % PROXIED)
    check(any(s[2] == '/through' and s[3] for s in SEEN), 'the target was not reached through the proxy: %r' % SEEN)
    if HAVE_TLS:
        PROXIED.clear()
        got = fetch('https://versions%s:%d/tunnel' % (WEB, HTTPS_PORT), TLS_CTX)
        check(got == (200, 'hello from the target'), 'over https through the proxy: %r' % (got,))
        check(PROXIED and PROXIED[0][0] == 'CONNECT' and PROXIED[0][1] == 'versions%s:%d' % (WEB, HTTPS_PORT)
              and PROXIED[0][2] == want_auth, 'no tunnel with the password: %r' % PROXIED)

    print('straight: listed, or this network\'s own')
    PROXIED.clear()
    SEEN.clear()
    got = fetch('http://127.0.0.1:%d/home' % HTTP_PORT)
    check(got[0] == 200 and not PROXIED and SEEN and not SEEN[-1][3],
          'an address of this machine went through the proxy: %r %r' % (got, PROXIED))
    for host in ('192.168.1.20', '10.1.2.3', '172.20.0.1', '127.0.0.1', 'fe80::1', 'fd00::5', 'router',
                 'gw.lan', 'nas.local', 'localhost'):
        check(zigmon.webproxy_straight(host), '%s would go through the proxy' % host)
    for host in ('8.8.8.8', '2a00:1450::1', 'github.com' + '.zigmon.invalid'):
        check(not zigmon.webproxy_straight(host), '%s would go straight' % host)
    settings(webproxy_no='.zigmon.invalid, 203.0.113.0/24, api.example.net')
    check('in the list' in zigmon.webproxy_straight('versions.zigmon.invalid'), 'a .domain listed is not straight')
    check('in the list' in zigmon.webproxy_straight('zigmon.invalid'), 'the domain itself of a .domain is not straight')
    check('in the list' in zigmon.webproxy_straight('203.0.113.9'), 'an address in a listed net is not straight')
    check('in the list' in zigmon.webproxy_straight('api.example.net'), 'a listed name is not straight')
    check(not zigmon.webproxy_straight('www.api.example.net'), 'a name under a listed name (not .domain) is straight')
    PROXIED.clear()
    got = fetch('http://plain%s:%d/listed' % (WEB, HTTP_PORT))
    check(got[0] != 200 and not PROXIED, 'a listed name went through the proxy: %r %r' % (got, PROXIED))
    x = zigmon.webproxy_try('http://plain%s:%d/listed' % (WEB, HTTP_PORT))
    check(x['mode'] == 'direct' and 'in the list' in x['why_direct'] and not x['ok']
          and x['steps'] and x['steps'][0]['what'].endswith('looked up') and not x['steps'][0]['ok'],
          'Try it of a listed name: %r' % x)
    settings(webproxy_no='localhost')

    print('a wrong password')
    settings(webproxy_password=WRONG)
    got = fetch('http://plain%s:%d/wrong' % (WEB, HTTP_PORT))
    check(got[0] == 407, 'a wrong password over http: %r' % (got,))
    if HAVE_TLS:
        got = fetch('https://versions%s:%d/wrong' % (WEB, HTTPS_PORT), TLS_CTX)
        check('407' in str(got[0]), 'a wrong password over https: %r' % (got,))
        x = zigmon.webproxy_try('https://versions%s:%d/wrong' % (WEB, HTTPS_PORT))
        last = (x.get('steps') or [{}])[-1]
        check(not x['ok'] and last.get('what', '').startswith('a tunnel through the proxy') and not last.get('ok')
              and '407' in last.get('said', '') and 'wrong' in last.get('said', ''),
              'Try it does not say the password is wrong: %r' % last)
    settings(webproxy_password=PASSWORD)

    # ---- Try it ------------------------------------------------------------------------------
    print('Try it: the way, step by step')
    if HAVE_TLS:
        os.environ['SSL_CERT_FILE'] = str(CA)       # the test's CA, for the check of the certificate
        x = zigmon.webproxy_try('https://versions%s:%d/try' % (WEB, HTTPS_PORT))
        os.environ.pop('SSL_CERT_FILE', None)
        whats = [s['what'] for s in x.get('steps') or []]
        check(x['ok'] and x['mode'] == 'proxy' and x['proxy'] == '127.0.0.1:%d' % PROXY_PORT and x['proxy_auth'],
              'Try it through the proxy: %r' % {k: x.get(k) for k in ('ok', 'mode', 'proxy', 'proxy_auth')})
        check(len(whats) == 5 and whats[0].startswith('the proxy looked up') and whats[1] == 'connected to the proxy'
              and whats[2].startswith('a tunnel through the proxy') and whats[3].startswith('TLS')
              and whats[4].startswith('asked for'), 'the steps through the proxy: %r' % whats)
        check(all(isinstance(s['ms'], int) and s['ok'] for s in x['steps']) and isinstance(x['ms'], int),
              'a step without its time')
        check(x.get('status') == 200 and (x.get('tls') or {}).get('issuer') == 'The test CA',
              'the answer or the certificate is not said: %r' % {k: x.get(k) for k in ('status', 'tls')})
    x = zigmon.webproxy_try('http://plain%s:%d/try' % (WEB, HTTP_PORT))
    whats = [s['what'] for s in x.get('steps') or []]
    check(x['ok'] and x['mode'] == 'proxy' and len(whats) == 3 and whats[2].startswith('asked for'),
          'Try it over http through the proxy: %r' % whats)
    x = zigmon.webproxy_try('http://127.0.0.1:%d/try' % HTTP_PORT)
    check(x['ok'] and x['mode'] == 'direct' and 'this network' in x['why_direct'],
          'Try it of this machine\'s own address: %r' % {k: x.get(k) for k in ('ok', 'mode', 'why_direct')})
    settings(webproxy_url='http://127.0.0.1:%d' % (PROXY_PORT + 9))      # nobody there
    x = zigmon.webproxy_try('https://versions%s:%d/' % (WEB, HTTPS_PORT))
    fail = [s for s in x['steps'] if not s['ok']]
    check(not x['ok'] and fail and fail[0]['what'] == 'connected to the proxy' and fail[0]['said'],
          'a proxy that is not there is not said where: %r' % x['steps'])
    settings(webproxy_url=PROXY_URL)
    try:
        zigmon.webproxy_try('https://me:pw@github.com/')
        check(False, 'Try it took an address with a name and a password in it')
    except ValueError:
        pass
    check(zigmon.webproxy_try.__doc__ and 'never by the broker' in zigmon.webproxy_try.__doc__, 'Try it says where it runs')

    # ---- the API ------------------------------------------------------------------------------
    print('the API: an administrator\'s, and nothing secret in it')
    code, v = call('/api/webproxy', session=S)
    check(code == 200 and v.get('on') and v.get('proxy') == '127.0.0.1:%d' % PROXY_PORT and v.get('password') is True,
          'GET /api/webproxy: %s %r' % (code, v))
    code, v = call('/api/webproxy', session=S_OP)
    check(code == 403, 'an operator read /api/webproxy: %s' % code)
    code, v = call('/api/webproxy', {'action': 'try', 'url': 'http://plain%s:%d/api' % (WEB, HTTP_PORT),
                                     'session': S_OP}, session=S_OP)
    check(code == 403, 'an operator could Try it: %s %r' % (code, v))
    code, v = call('/api/webproxy', {'action': 'try', 'url': 'http://plain%s:%d/api' % (WEB, HTTP_PORT),
                                     'session': S}, session=S)
    check(code == 200 and v.get('ok') and v.get('mode') == 'proxy' and len(v.get('steps') or []) == 3,
          'POST /api/webproxy try: %s %r' % (code, v))
    code, v2 = call('/api/webproxy', {'action': 'try', 'url': 'ftp://x', 'session': S}, session=S)
    check(code == 400, 'an address that is not http(s) was tried: %s' % code)
    settings(webproxy_password=WRONG)
    code, v3 = call('/api/webproxy', {'action': 'try', 'url': 'http://plain%s:%d/api' % (WEB, HTTP_PORT),
                                      'session': S}, session=S)
    settings(webproxy_password=PASSWORD)
    check(code == 200 and not v3.get('ok') and '407' in json.dumps(v3), 'the wrong password through the API: %r' % v3)
    code, cfg = call('/api/config', session=S)
    shown = json.dumps([call('/api/webproxy', session=S)[1], v, v3, cfg, d.runtime_config(),
                        call('/api/status', session=S)[1]])
    check(PASSWORD not in shown and zigmon.quote(PASSWORD, safe='') not in shown,
          'the password is in what the page is shown')
    check(base64.b64encode(('%s:%s' % (USER, PASSWORD)).encode()).decode() not in shown,
          'the password (as Basic) is in what the page is shown')

    # ---- dnf ----------------------------------------------------------------------------------
    print('dnf: handed the proxy in a file only root reads, never on its command line')
    asked = []
    real_call = d.root_call

    def spy(ask, answer, data, wait=60):
        asked.append((ask, dict(data)))
        return real_call(ask, answer, data, wait)
    d.root_call = spy
    zigmon.osup_check_ask(d, 'owner')
    end = time.time() + 30
    while time.time() < end and not (DNF_SAW.exists() and json.loads(DNF_SAW.read_text())):
        time.sleep(0.1)
    time.sleep(1.0)
    full = zigmon.webproxy_full('os')
    check(asked and asked[0][0] == 'osup.ask' and asked[0][1].get('proxy') == full and USER in full,
          'root was not handed the proxy in its ask: %r' % [a[0] for a in asked])
    check(PROXY_FILE.exists() and (PROXY_FILE.stat().st_mode & 0o777) == 0o600,
          'root did not keep the proxy in a file only it reads (0600)')
    kept = json.loads(PROXY_FILE.read_text()) if PROXY_FILE.exists() else {}
    check(kept.get('url') == full and 'localhost' in kept.get('no', ''), 'the file does not hold the proxy: %r' % kept)
    saw = json.loads(DNF_SAW.read_text()) if DNF_SAW.exists() else []
    check(saw and all(s['env'].get('https_proxy') == full and s['env'].get('http_proxy') == full for s in saw),
          'dnf was not given the proxy in its environment: %r' % [s['env'] for s in saw][:1])
    check(saw and all(not any(PASSWORD in a or zigmon.quote(PASSWORD, safe='') in a or 'proxy' in a.lower()
                              for a in s['argv'][1:]) for s in saw),
          'the proxy is on dnf\'s command line: %r' % [s['argv'] for s in saw])
    words = ''.join(p.read_text() for p in (ROOT_DIR / 'osup.json', ROOT_DIR / 'osup-check.log') if p.exists())
    check('127.0.0.1:%d' % PROXY_PORT in words, 'the job does not say it went through the proxy')
    check(PASSWORD not in words and zigmon.quote(PASSWORD, safe='') not in words,
          'the password is in osup.json or osup-check.log')
    # the job reads the file only when it is root's alone
    PROXY_FILE.chmod(0o644)
    env = {}
    sys.path.insert(0, str(ROOT_HELPER.parent))
    import importlib.util as _iu
    _spec = _iu.spec_from_file_location('zigmon_root_check', str(ROOT_HELPER))
    rootmod = _iu.module_from_spec(_spec)
    _spec.loader.exec_module(rootmod)
    check(rootmod.osup_proxy_env(env) == '' and 'https_proxy' not in env,
          'a proxy file others may read was believed')
    PROXY_FILE.chmod(0o600)
    # the proxy off, or the system updates not through it: the file goes
    DNF_SAW.unlink()
    asked.clear()
    zigmon.osup_follow(d)
    while (d._mj('osup:check') or {}).get('state') in ('asking', 'running'):
        zigmon.osup_follow(d)
        time.sleep(0.1)
    settings(webproxy_os=0)
    zigmon.osup_check_ask(d, 'owner')
    end = time.time() + 30
    while time.time() < end and not (DNF_SAW.exists() and json.loads(DNF_SAW.read_text())):
        time.sleep(0.1)
    time.sleep(1.0)
    saw = json.loads(DNF_SAW.read_text()) if DNF_SAW.exists() else []
    check(asked and asked[0][1].get('proxy') == '', 'the proxy was handed over with the system updates left out')
    check(not PROXY_FILE.exists(), 'the proxy file was left behind once dnf was not to use it')
    check(saw and all(not s['env'].get('https_proxy') for s in saw), 'dnf still went through the proxy')
    settings(webproxy_os=1)
    d.root_call = real_call

    # ---- every call site ------------------------------------------------------------------------
    print('what goes through it, and what never does')
    src = (HERE / 'zigmon.py').read_text()

    def body_of(name):
        at = src.index('def %s(' % name)
        nxt = re.search(r'\n(    )?def ', src[at + 10:])
        return src[at:at + 10 + (nxt.start() if nxt else len(src))]
    for fn in ('_online_get', 'acme_urlopen', 'weather', 'geo_fetch', 'shodan_ask', '_duo_once', '_feed_fetch',
               'presence_ntfy_loop', 'notify_loop'):
        check('web_open(' in body_of(fn), '%s does not go the proxy\'s way' % fn)
    check("web_opener('https://www.snort.org/'" in body_of('_snort_fetch'), 'snort.org does not go the proxy\'s way')
    for fn in ('_rest_once', '_sms_open', '_sms_login', 'gateway_fetch', '_unifi_opener', 'api_call'):
        check('web_open' not in body_of(fn), '%s (the house\'s own) goes the proxy\'s way' % fn)

    # ---- nothing secret written down --------------------------------------------------------------
    print('nothing secret written down')
    rows = d.store.db.execute('SELECT * FROM events').fetchall() if hasattr(d.store, 'db') else []
    events = json.dumps([list(r) for r in rows], default=str)
    logged = LOG.read_text() if LOG.exists() else ''
    for where, text in (('the events', events), ('the log', logged)):
        check(PASSWORD not in text and zigmon.quote(PASSWORD, safe='') not in text, 'the password is in %s' % where)

    # ---- the relay, the command line, the console --------------------------------------------------
    print('the relay, the command line and the console')
    page = (HERE / 'web' / 'index.php').read_text()
    allowed = page[page.index("if (in_array($what, ['scenes-save'"):]
    allowed = allowed[:allowed.index('], true)')]
    check("'webproxy-do'" in allowed, 'webproxy-do is not let through by the relay')
    check("'webproxy-do' => '/api/webproxy'" in page, 'webproxy-do is not mapped to /api/webproxy')
    check("$what === 'webproxy'" in page and "zigmon_relay('/api/webproxy')" in page,
          'the relay does not read /api/webproxy')
    check("'/api/webproxy'" in src[src.index('ALWAYS_LOCKED = ('):src.index('ALWAYS_LOCKED = (') + 3000],
          '/api/webproxy is not behind the sign-in')
    parser = zigmon.build_parser()
    check(parser.parse_args(['--webproxy-test']).webproxy_test == '' and
          parser.parse_args(['--webproxy-test', 'https://x.cz/']).webproxy_test == 'https://x.cz/',
          '--webproxy-test is not taken')
    check(parser.parse_args(['--proxy']).proxy is True and parser.parse_args(['--proxy']).webproxy_test is None,
          '--proxy (the server in front) is taken for --webproxy-test')
    check("('sudo zigmon --webproxy-test'" in src, 'the help does not name --webproxy-test')
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = zigmon.cmd_webproxy_test(parser.parse_args(['--webproxy-test', 'http://plain%s:%d/cli' % (WEB, HTTP_PORT),
                                                         '--no-color']), zigmon.Palette(False))
    said = out.getvalue()
    check(rc == 0 and 'the proxy 127.0.0.1:%d' % PROXY_PORT in said and 'connected to the proxy' in said
          and 'through the proxy' in said, 'zigmon --webproxy-test: %s %r' % (rc, said[-400:]))
    check(PASSWORD not in said, 'the command line shows the password')
    machine = [f for w, f in zigmon.CONSOLE_MORE['main'] if w == 'Network, time and power']
    console = src[src.index('def _console_machine('):src.index('def _console_upgrade_online(')]
    check(machine and "lambda: _console_webproxy(c)" in console and "c.act('--webproxy-test'" in console,
          'the console has no Try it for the proxy')

    # ---- the real page in Chromium ---------------------------------------------------------------
    print('the page: Proxy after Network, its cards, the way drawn')
    menu = page[page.index('<div class="ctl-group">Server</div>'):]
    menu = menu[:menu.index('<div class="ctl-group">', 10)]
    check('data-sec="sys-proxy"' in menu and menu.index('sys-network') < menu.index('sys-proxy') < menu.index('sys-time'),
          'Proxy is not right after Network in Server')
    have_php = bool(shutil.which('php')) and bool(shutil.which('node'))
    if not have_php:
        print('  SKIPPED the browser: no php or node here')
    else:
        rc_page = d.runtime_config()
        sample = zigmon.webproxy_try('http://plain%s:%d/page' % (WEB, HTTP_PORT))
        settings(webproxy_password=WRONG)
        failed = zigmon.webproxy_try('http://plain%s:%d/page' % (WEB, HTTP_PORT))
        settings(webproxy_password=PASSWORD)
        js = r'''
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({viewport: {width: 1500, height: 1000}});
  p.on('pageerror', e => {});
  await p.goto('http://127.0.0.1:%(port)d/index.php#control/sys-proxy');
  await p.waitForTimeout(1200);
  const r = await p.evaluate((a) => {
    const out = {};
    const btns = Array.from(document.querySelectorAll('nav [data-sec]')).map(x => x.dataset.sec);
    out.order = btns;
    const btn = document.querySelector('nav [data-sec="sys-proxy"]');
    out.label = btn ? btn.textContent.trim() : '';
    out.icon = btn ? !!btn.querySelector('svg path') : false;
    try { showControlSection('sys-proxy'); } catch (e) { out.err = String(e); }
    out.head = (document.getElementById('ctl-head') || {}).textContent || '';
    out.cards = Array.from(document.querySelectorAll('#tab-control .grid.charts > [data-sec="sys-proxy"]')).map(c => c.id);
    out.setTitle = ((document.querySelector('#px-set-card > h2') || {}).textContent || '').trim();
    try { renderSettings({runtime_config: a.rc}); } catch (e) { out.err2 = String(e); }
    const sh = document.getElementById('set-host-sys-proxy');
    out.boxes = Array.from(sh.querySelectorAll('[data-k]')).map(x => x.dataset.k);
    const pw = sh.querySelector('[data-k="webproxy_password"]');
    out.pw = pw ? {type: pw.type, value: pw.value, ph: pw.placeholder} : null;
    out.setHtml = sh.innerHTML;
    window.isUnlocked = function () { return true; };
    drawProxy();
    const host = document.getElementById('px-host');
    out.tryTitle = ((host.querySelector('h2') || {}).textContent || '').trim();
    out.input = !!document.getElementById('px-url') && !!document.getElementById('px-go');
    const said = document.getElementById('px-said');
    const show = (x) => {
      said.innerHTML = '';
      const cd = pxCard(x.node, x.ok ? 'ok' : 'bad', x.ok ? 'through the proxy' : 'not reached', x.ok ? 'ok' : 'crit');
      cd.appendChild(pxPath(x)); cd.appendChild(pxSteps(x)); said.appendChild(cd);
      return {stops: Array.from(said.querySelectorAll('.px-stop b')).map(e => e.textContent),
              links: Array.from(said.querySelectorAll('.px-link')).map(e => e.className),
              steps: Array.from(said.querySelectorAll('.px-step')).map(e => e.className + ' | ' + e.textContent),
              verdict: (said.querySelector('.px-verdict') || {}).textContent || '',
              wire: getComputedStyle(said.querySelector('.px-wire')).height,
              stopW: Math.round(said.querySelector('.px-stop').getBoundingClientRect().width)};
    };
    out.good = show(a.sample);
    out.bad = show(a.failed);
    const going = pxPath(null, 'zig');
    out.going = going.querySelectorAll('.px-link.going').length;
    out.html = document.getElementById('tab-control') ? document.getElementById('tab-control').innerHTML.length : 0;
    return out;
  }, %(args)s);
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
''' % {'port': PHP_PORT, 'args': json.dumps({'rc': rc_page, 'sample': sample, 'failed': failed})}
        (W / 'run.js').write_text(js)
        php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, '-t', str(HERE / 'web')],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        for _ in range(50):
            try:
                socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
        got = subprocess.run(['node', str(W / 'run.js')], capture_output=True, text=True, timeout=120,
                             stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=root))
        php.kill()
        php.wait()
        php = None
        try:
            r = json.loads(got.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            r = {'error': (got.stdout + got.stderr)[-300:]}
        if r.get('error'):
            print('  SKIPPED the browser (none here): %s' % r['error'][:200])
        else:
            order = r.get('order') or []
            check('sys-proxy' in order and order.index('sys-proxy') == order.index('sys-network') + 1,
                  'Proxy is not right after Network on the page: %r' % order)
            check(r.get('label') == 'Proxy' and r.get('icon'), 'the menu has no Proxy with its icon: %r' % r.get('label'))
            check(r.get('head', '').startswith('Proxy') and 'HTTP proxy' in r.get('head', ''),
                  'the pane has no title and lede: %r' % r.get('head', '')[:120])
            check(r.get('cards') == ['px-set-card', 'px-card'], 'the pane\'s cards: %r' % r.get('cards'))
            check(r.get('setTitle') == 'Settings' and r.get('tryTitle') == 'Try it' and r.get('input'),
                  'the cards are not Settings and Try it: %r %r' % (r.get('setTitle'), r.get('tryTitle')))
            want = ['webproxy', 'webproxy_url', 'webproxy_user', 'webproxy_password', 'webproxy_no', 'webproxy_os']
            check(r.get('boxes') == want, 'the settings card does not hold the proxy\'s settings: %r %s'
                  % (r.get('boxes'), r.get('err2', '')))
            check(r.get('pw') and r['pw']['type'] == 'password' and r['pw']['value'] == '' and r['pw']['ph'] == '(kept)',
                  'the password box: %r' % r.get('pw'))
            check(PASSWORD not in r.get('setHtml', ''), 'the password is in the settings card')
            g, b2 = r.get('good') or {}, r.get('bad') or {}
            check(g.get('stops') == [sample['node'], '127.0.0.1:%d' % PROXY_PORT, 'plain%s:%d' % (WEB, HTTP_PORT)],
                  'the way is not this machine, the proxy, the address: %r' % g.get('stops'))
            check(len(g.get('links') or []) == 2 and all(' ok' in c for c in g['links']),
                  'the links of a way that went are not green: %r' % g.get('links'))
            check(len(g.get('steps') or []) == 3 and all(s.startswith('px-step ok') and ' ms' in s for s in g['steps']),
                  'the steps are not shown each with its time: %r' % g.get('steps'))
            check('Reached through the proxy' in g.get('verdict', ''), 'no verdict: %r' % g.get('verdict'))
            check(g.get('wire') == '3px' and (g.get('stopW') or 0) >= 150, 'the way is not drawn as otp draws it '
                  '(no CSS?): %r %r' % (g.get('wire'), g.get('stopW')))
            check('Not reached' in b2.get('verdict', '') and '407' in b2.get('verdict', '')
                  and any(s.startswith('px-step bad') for s in b2.get('steps') or [])
                  and any('stopped here' in c or ' bad' in c for c in b2.get('links') or []),
                  'a way that stopped is not drawn so: %r' % b2)
            check(r.get('going') == 1, 'nothing is drawn while it is being tried')
finally:
    if php is not None:
        php.kill()
        php.wait()
    try:
        if api is not None:
            api.stop()
    except Exception:                                   # noqa: BLE001
        pass
    for srv in servers:
        srv.shutdown()
        srv.server_close()

if bad:
    print('\n%d problem(s)' % len(bad))
    raise SystemExit(1)
shutil.rmtree(str(W), ignore_errors=True)
print('\nProxy: every check passed')
