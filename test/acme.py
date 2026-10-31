#!/usr/bin/env python3
"""Automatic certificates (5.30, ported from otp 1.0.169 - 1.0.187), the whole
way round, against an ACME CA started in this process (RFC 8555, the part an
order uses): its directory, nonces, accounts, orders, authorizations,
challenges, finalize and the certificate - every request's JWS (ES256)
checked against the account's key, every nonce used once, and a certificate
issued from the request by a CA of the test's own (openssl).

  * the settings: every acme_* one taken in its shape, the wrong ones refused,
    the secrets kept off the page;
  * HTTP-01: root (deploy/zigmon_root.py, run as root would run it, over a
    folder that stands in for the machine) gives port 80 a location for
    /.well-known/acme-challenge/ between marks, nginx -t takes it, the same
    file twice is the same file, and it comes out again as it was; the CA's
    question answered through index.php (php -S) by the daemon - only a
    token of an order going;
  * an order end to end: the certificate and its key put in by root exactly
    as an uploaded one is (tls_put), the key the certificate's own, no key
    left behind anywhere in the daemon's folder, the event written;
  * renewal: due at acme_days, or a third of a short life; a failed try not
    again for six hours, and then again; the half-minute chore orders it;
  * an account the CA no longer knows made anew, and the order asked again;
  * who looks after it: a certificate put in by hand on Certificates is kept
    (out of ACME's care); Order it now takes it back, root keeps the one it
    had, and Back to the one before puts it back, its key as it was;
  * DNS-01 by hand (the record shown, It is in DNS) and by RFC 2136 - nsupdate
    given the TSIG key in a file of its own (0600), never on its command line;
  * the relay: the endpoints let through, the challenge's own road.

    python3 test/acme.py

Needs openssl, nginx (for nginx -t) and php (for the relay's road; skipped
without it). Ports 19801 (the CA), 19802 (the daemon), 19803 (php -S).
"""
import base64
import hashlib
import json
import os
import re
import shutil
import socket
import ssl
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
ROOT_HELPER = HERE / 'deploy' / 'zigmon_root.py'
W = Path(tempfile.mkdtemp(prefix='zigmon-acme-check-'))
CA_PORT, API_PORT, PHP_PORT = 19801, 19802, 19803
NAME = 'zigmon.house.example'
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def b64u(data):
    if isinstance(data, str):
        data = data.encode()
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def b64d(s):
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


# ---- the test's own CA -----------------------------------------------------------------
CAD = W / 'ca'
CAD.mkdir()
sh(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes',
    '-keyout', str(CAD / 'ca.key'), '-out', str(CAD / 'ca.pem'), '-days', '30', '-subj', '/CN=Test ACME Root',
    '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign'])
CA_PEM = (CAD / 'ca.pem').read_text()
# the CA's own server: HTTPS on 127.0.0.1, as an ACME CA must be
sh(['openssl', 'req', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes', '-keyout',
    str(CAD / 'srv.key'), '-out', str(CAD / 'srv.csr'), '-subj', '/CN=127.0.0.1'])
(CAD / 'srv.ext').write_text('subjectAltName=IP:127.0.0.1\nbasicConstraints=CA:FALSE\n')
sh(['openssl', 'x509', '-req', '-in', str(CAD / 'srv.csr'), '-CA', str(CAD / 'ca.pem'), '-CAkey',
    str(CAD / 'ca.key'), '-CAcreateserial', '-days', '5', '-out', str(CAD / 'srv.pem'), '-extfile',
    str(CAD / 'srv.ext')])


def thumb(jwk):
    need = ('e', 'kty', 'n') if jwk.get('kty') == 'RSA' else ('crv', 'kty', 'x', 'y')
    return b64u(hashlib.sha256(json.dumps({k: jwk[k] for k in need},
                                          separators=(',', ':'), sort_keys=True).encode()).digest())


def jws_ok(alg, jwk, signing_input, sig):
    """ES256, ES384 or RS256 (5.33.3), checked with the cryptography package
    against the public key in the JWK - the account's key kind decides."""
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    except ImportError:
        return alg == 'ES256' and es256_ok(jwk, signing_input, sig)
    try:
        if alg == 'RS256' and jwk.get('kty') == 'RSA':
            pub = rsa.RSAPublicNumbers(int.from_bytes(b64d(jwk['e']), 'big'),
                                       int.from_bytes(b64d(jwk['n']), 'big')).public_key()
            pub.verify(sig, signing_input, padding.PKCS1v15(), hashes.SHA256())
            return True
        size, curve, h = {'ES256': (32, ec.SECP256R1(), hashes.SHA256()),
                          'ES384': (48, ec.SECP384R1(), hashes.SHA384())}[alg]
        if jwk.get('kty') != 'EC' or jwk.get('crv') != {'ES256': 'P-256', 'ES384': 'P-384'}[alg] \
                or len(sig) != 2 * size:
            return False
        pub = ec.EllipticCurvePublicNumbers(int.from_bytes(b64d(jwk['x']), 'big'),
                                            int.from_bytes(b64d(jwk['y']), 'big'), curve).public_key()
        pub.verify(encode_dss_signature(int.from_bytes(sig[:size], 'big'), int.from_bytes(sig[size:], 'big')),
                   signing_input, ec.ECDSA(h))
        return True
    except Exception:                                   # noqa: BLE001 - a bad signature, said
        return False


def es256_ok(jwk, signing_input, sig):
    """The signature checked with openssl against the public key in the JWK."""
    if jwk.get('kty') != 'EC' or jwk.get('crv') != 'P-256' or len(sig) != 64:
        return False
    spki = bytes.fromhex('3059301306072a8648ce3d020106082a8648ce3d030107034200') + b'\x04' + \
        b64d(jwk['x']) + b64d(jwk['y'])

    def integer(b):
        b = b.lstrip(b'\x00') or b'\x00'
        if b[0] & 0x80:
            b = b'\x00' + b
        return b'\x02' + bytes([len(b)]) + b
    seq = integer(sig[:32]) + integer(sig[32:])
    der = b'\x30' + bytes([len(seq)]) + seq
    with tempfile.TemporaryDirectory(dir=str(W)) as t:
        Path(t, 'pub.der').write_bytes(spki)
        Path(t, 'sig').write_bytes(der)
        Path(t, 'data').write_bytes(signing_input)
        got = sh(['openssl', 'dgst', '-sha256', '-verify', str(Path(t, 'pub.der')), '-keyform', 'DER',
                  '-signature', str(Path(t, 'sig')), str(Path(t, 'data'))])
        if got.returncode != 0:      # older openssl: the key as PEM
            pem = '-----BEGIN PUBLIC KEY-----\n%s-----END PUBLIC KEY-----\n' % base64.encodebytes(spki).decode()
            Path(t, 'pub.pem').write_text(pem)
            got = sh(['openssl', 'dgst', '-sha256', '-verify', str(Path(t, 'pub.pem')), '-signature',
                      str(Path(t, 'sig')), str(Path(t, 'data'))])
        return got.returncode == 0


class CA(object):
    """What the CA knows, and what the test tells it to do."""
    def __init__(self):
        self.lock = threading.Lock()
        self.nonces = set()
        self.algs = []
        self.accounts = {}          # kid -> jwk
        self.made = 0               # accounts made
        self.orders = {}
        self.authz = {}
        self.certs = {}
        self.seq = 0
        self.bad = []               # every request that was not as RFC 8555 has it
        self.signed = 0             # requests whose signature was checked and good
        self.forget = False         # the next request by kid: accountDoesNotExist, and the account gone
        self.fail_next = False      # the next challenge: invalid
        self.days = 90
        self.dns = {}               # name -> [TXT values], the DNS the test stands in for
        self.seen = []              # (how, name) of every challenge looked at


CAS = CA()
BASE = 'https://127.0.0.1:%d' % CA_PORT


def ca_issue(csr_der, days):
    """A certificate for the request: its subject's name, its key."""
    with tempfile.TemporaryDirectory(dir=str(W)) as t:
        Path(t, 'r.der').write_bytes(csr_der)
        txt = sh(['openssl', 'req', '-inform', 'DER', '-in', str(Path(t, 'r.der')), '-noout', '-subject',
                  '-verify', '-nameopt', 'RFC2253'])
        if txt.returncode != 0:
            return None, 'the request does not verify: %s' % txt.stderr[-200:]
        m = re.search(r'CN=([^,\s]+)', txt.stdout)
        if not m:
            return None, 'the request has no name'
        Path(t, 'ext').write_text('subjectAltName=DNS:%s\nbasicConstraints=CA:FALSE\n'
                                  'extendedKeyUsage=serverAuth\n' % m.group(1))
        sh(['openssl', 'req', '-inform', 'DER', '-in', str(Path(t, 'r.der')), '-out', str(Path(t, 'r.pem'))])
        got = sh(['openssl', 'x509', '-req', '-in', str(Path(t, 'r.pem')), '-CA', str(CAD / 'ca.pem'),
                  '-CAkey', str(CAD / 'ca.key'), '-CAcreateserial', '-days', str(days), '-out',
                  str(Path(t, 'c.pem')), '-extfile', str(Path(t, 'ext'))])
        if got.returncode != 0:
            return None, got.stderr[-200:]
        return Path(t, 'c.pem').read_text() + CA_PEM, ''


def key_auth_fetched(token):
    """What the daemon answers for the token on port 80 - through index.php
    where php is there, as nginx hands it over; else the daemon's own road."""
    if PHP:
        url = 'http://127.0.0.1:%d/.well-known/acme-challenge/%s' % (PHP_PORT, token)
        how = 'php'
    else:
        url = 'http://127.0.0.1:%d/api/acme/challenge?token=%s' % (API_PORT, token)
        how = 'api'
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'test-ca'}),
                                    timeout=10) as r:
            body = r.read().decode()
    except (urllib.error.URLError, OSError) as e:
        return how, None, str(e)
    if how == 'api':
        body = json.loads(body).get('auth')
    return how, body, ''


class CAHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def nonce(self):
        n = b64u(os.urandom(12))
        with CAS.lock:
            CAS.nonces.add(n)
        return n

    def send(self, code, obj=None, headers=None, raw=None, ctype='application/json'):
        body = raw if raw is not None else (json.dumps(obj).encode() if obj is not None else b'')
        self.send_response(code)
        self.send_header('Replay-Nonce', self.nonce())
        self.send_header('Content-Type', ctype if obj is not None or raw is not None else 'text/plain')
        self.send_header('Content-Length', str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body and self.command != 'HEAD':
            self.wfile.write(body)

    def err(self, code, kind, detail):
        self.send(code, {'type': 'urn:ietf:params:acme:error:' + kind, 'detail': detail},
                  ctype='application/problem+json')

    def do_HEAD(self):
        if self.path == '/new-nonce':
            return self.send(200)
        self.send(404)

    def do_GET(self):
        if self.path == '/directory':
            return self.send(200, {'newNonce': BASE + '/new-nonce', 'newAccount': BASE + '/new-account',
                                   'newOrder': BASE + '/new-order', 'revokeCert': BASE + '/revoke',
                                   'keyChange': BASE + '/key-change'})
        if self.path == '/new-nonce':
            return self.send(204)
        self.send(404)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        if self.headers.get('Content-Type') != 'application/jose+json':
            CAS.bad.append('a POST to %s not as application/jose+json' % self.path)
        try:
            jws = json.loads(raw)
            prot = json.loads(b64d(jws['protected']))
            payload = json.loads(b64d(jws['payload'])) if jws['payload'] else None
            sig = b64d(jws['signature'])
        except (ValueError, KeyError) as e:
            CAS.bad.append('a JWS that does not read (%s)' % e)
            return self.err(400, 'malformed', 'not a JWS')
        with CAS.lock:
            fresh = prot.get('nonce') in CAS.nonces
            CAS.nonces.discard(prot.get('nonce'))
        if not fresh:
            return self.err(400, 'badNonce', 'that nonce is not one of mine')
        if prot.get('alg') not in ('ES256', 'ES384', 'RS256'):
            CAS.bad.append('alg %r' % prot.get('alg'))
        CAS.algs.append(prot.get('alg'))
        if prot.get('url') != BASE + self.path:
            CAS.bad.append('url %r for %s' % (prot.get('url'), self.path))
        if ('jwk' in prot) == ('kid' in prot):
            CAS.bad.append('jwk and kid both or neither at %s' % self.path)
        if 'jwk' in prot:
            if self.path != '/new-account':
                CAS.bad.append('a jwk where the kid belongs (%s)' % self.path)
            jwk = prot['jwk']
        else:
            kid = prot.get('kid')
            if CAS.forget and kid in CAS.accounts:
                CAS.forget = False
                CAS.accounts.pop(kid)
            if kid not in CAS.accounts:
                return self.err(400, 'accountDoesNotExist', 'no account at %s' % kid)
            jwk = CAS.accounts[kid]
        if not jws_ok(prot.get('alg'), jwk, ('%s.%s' % (jws['protected'], jws['payload'])).encode(), sig):
            CAS.bad.append('a signature that does not verify at %s' % self.path)
            return self.err(400, 'malformed', 'bad signature')
        CAS.signed += 1
        if 'User-Agent' not in self.headers or not self.headers['User-Agent'].startswith('zigmon/'):
            CAS.bad.append('User-Agent %r' % self.headers.get('User-Agent'))
        return self.route(jwk, payload)

    def route(self, jwk, payload):
        p = self.path
        if p == '/new-account':
            if not (payload or {}).get('termsOfServiceAgreed'):
                CAS.bad.append('the terms were not agreed to')
            for kid, k in CAS.accounts.items():
                if thumb(k) == thumb(jwk):
                    return self.send(200, {'status': 'valid'}, {'Location': kid})
            CAS.made += 1
            kid = BASE + '/acct/%d' % CAS.made
            CAS.accounts[kid] = jwk
            return self.send(201, {'status': 'valid', 'contact': (payload or {}).get('contact')},
                             {'Location': kid})
        if p == '/new-order':
            CAS.seq += 1
            oid = str(CAS.seq)
            names = [i['value'] for i in (payload or {}).get('identifiers') or []]
            azs = []
            for n in names:
                CAS.seq += 1
                aid = str(CAS.seq)
                tok = b64u(os.urandom(24))
                CAS.authz[aid] = {'status': 'pending', 'identifier': {'type': 'dns', 'value': n},
                                  'token': tok, 'order': oid, 'thumb': thumb(jwk), 'challenges': [
                                      {'type': 'http-01', 'url': BASE + '/chal/%s/http' % aid, 'token': tok,
                                       'status': 'pending'},
                                      {'type': 'dns-01', 'url': BASE + '/chal/%s/dns' % aid, 'token': tok,
                                       'status': 'pending'}]}
                azs.append(BASE + '/authz/' + aid)
            CAS.orders[oid] = {'status': 'pending', 'identifiers': [{'type': 'dns', 'value': n} for n in names],
                               'authorizations': azs, 'finalize': BASE + '/finalize/' + oid}
            return self.send(201, CAS.orders[oid], {'Location': BASE + '/order/' + oid})
        m = re.match(r'^/authz/(\d+)$', p)
        if m and m.group(1) in CAS.authz:
            a = CAS.authz[m.group(1)]
            return self.send(200, {k: v for k, v in a.items() if k in ('status', 'identifier', 'challenges')})
        m = re.match(r'^/chal/(\d+)/(http|dns)$', p)
        if m and m.group(1) in CAS.authz:
            a = CAS.authz[m.group(1)]
            name = a['identifier']['value']
            want = a['token'] + '.' + a['thumb']
            ch = [c for c in a['challenges'] if c['type'].startswith(m.group(2))][0]
            if CAS.fail_next:
                CAS.fail_next = False
                ok, said = False, 'Invalid response from http://%s/.well-known/acme-challenge/%s: 404' % (
                    name, a['token'])
            elif m.group(2) == 'http':
                how, got, said = key_auth_fetched(a['token'])
                CAS.seen.append((how, name))
                ok = got == want
                said = said or ('the key authorization did not match: %r' % got)
            else:
                txt = b64u(hashlib.sha256(want.encode()).digest())
                CAS.seen.append(('dns', name))
                ok = txt in CAS.dns.get('_acme-challenge.' + name, [])
                said = 'NXDOMAIN looking up TXT for _acme-challenge.%s' % name
            a['status'] = 'valid' if ok else 'invalid'
            ch['status'] = a['status']
            if not ok:
                ch['error'] = {'type': 'urn:ietf:params:acme:error:unauthorized', 'detail': said}
            return self.send(200, ch)
        m = re.match(r'^/finalize/(\d+)$', p)
        if m and m.group(1) in CAS.orders:
            o = CAS.orders[m.group(1)]
            if any(CAS.authz[u.rsplit('/', 1)[1]]['status'] != 'valid' for u in o['authorizations']):
                return self.err(403, 'orderNotReady', 'not every name was shown')
            pem, said = ca_issue(b64d((payload or {}).get('csr') or ''), CAS.days)
            if not pem:
                CAS.bad.append(said)
                return self.err(400, 'badCSR', said)
            CAS.certs[m.group(1)] = pem
            o.update(status='valid', certificate=BASE + '/cert/' + m.group(1))
            return self.send(200, o, {'Location': BASE + '/order/' + m.group(1)})
        m = re.match(r'^/order/(\d+)$', p)
        if m and m.group(1) in CAS.orders:
            return self.send(200, CAS.orders[m.group(1)])
        m = re.match(r'^/cert/(\d+)$', p)
        if m and m.group(1) in CAS.certs:
            if payload is not None:
                CAS.bad.append('the certificate fetched with a payload, not POST-as-GET')
            return self.send(200, raw=CAS.certs[m.group(1)].encode(), ctype='application/pem-certificate-chain')
        self.send(404)


ca_srv = ThreadingHTTPServer(('127.0.0.1', CA_PORT), CAHandler)
ca_srv.daemon_threads = True
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(str(CAD / 'srv.pem'), str(CAD / 'srv.key'))
ca_srv.socket = ctx.wrap_socket(ca_srv.socket, server_side=True)
threading.Thread(target=ca_srv.serve_forever, daemon=True).start()


# ---- the machine, as test/root.py stands it in -----------------------------------------
STATE, ETC = W / 'state', W / 'etc'
CERTS = ETC / 'nginx' / 'certs'
for p in (STATE / 'root', STATE / 'backups', ETC / 'zigmon', ETC / 'mosquitto', ETC / 'nginx' / 'conf.d', CERTS,
          W / 'logs', W / 'www', W / 'body'):
    p.mkdir(parents=True, exist_ok=True)
DB = STATE / 'history.db'
(ETC / 'zigmon' / 'config.json').write_text(json.dumps({'db_file': str(DB)}))
(ETC / 'mosquitto' / 'mosquitto.conf').write_text('listener 1883\n')
# the certificate install.sh left: self-signed, made with the machine
sh(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(CERTS / 'server.key'), '-out',
    str(CERTS / 'server.pem'), '-days', '400', '-subj', '/CN=%s' % NAME, '-addext', 'subjectAltName=DNS:%s' % NAME])
shutil.copy(CERTS / 'server.pem', CERTS / 'server.ca')
conf = (HERE / 'deploy' / 'nginx-zigmon.conf').read_text()
for a, b in (('/etc/nginx/certs/', str(CERTS) + '/'), ('/var/www/zigmon', str(W / 'www')),
             ('unix:/run/php-fpm/www.sock', 'unix:' + str(W / 'fpm.sock')),
             ('/var/log/nginx/', str(W / 'logs') + '/'),
             ('include        fastcgi_params;', 'include        /etc/nginx/fastcgi_params;'),
             ('listen      443 ssl http2;', 'listen      127.0.0.1:19804 ssl;'),
             ('listen      [::]:443 ssl http2;', ''), ('listen      80;', 'listen 127.0.0.1:19805;'),
             ('listen      [::]:80;', ''), ('mqtt.falco81.net', NAME)):
    conf = conf.replace(a, b)
NGINX_CONF = ETC / 'nginx' / 'conf.d' / 'zigmon.conf'
NGINX_CONF.write_text(conf)
ORIGINAL_CONF = conf
(W / 'nginx.conf').write_text(('user root;\n' if os.geteuid() == 0 else '') + '''daemon off;
pid %(w)s/nginx.pid;
error_log %(w)s/logs/main.log;
events { worker_connections 64; }
http {
    include /etc/nginx/mime.types;
    client_body_temp_path %(w)s/body;
    include %(c)s;
}
''' % {'w': W, 'c': NGINX_CONF})
NGINX = shutil.which('nginx') and os.path.exists('/etc/nginx/fastcgi_params')
os.environ.update(ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(W / 'own'), ZIGMON_FULL_DIR=str(W / 'full'),
                  ZIGMON_CONFIG=str(ETC / 'zigmon' / 'config.json'), ZIGMON_NGINX_CONF=str(NGINX_CONF),
                  ZIGMON_CERT_DIR=str(CERTS), ZIGMON_MOSQ_DIR=str(ETC / 'mosquitto'),
                  ZIGMON_NO_SERVICES='1', ZIGMON_SERVICE_LOG=str(W / 'services.log'), ZIGMON_FS_ROOT=str(W),
                  ZIGMON_USER='root', ZIGMON_FW_FILE4=str(W / 'no4'), ZIGMON_FW_FILE6=str(W / 'no6'),
                  ZIGMON_FIREWALL_CMD=str(W / 'no-firewall-cmd'),
                  ZIGMON_NGINX_TEST=('nginx -t -p %s -c %s' % (W, W / 'nginx.conf')) if NGINX else 'true',
                  ZIGMON_ROOT_RUN='%s -I %s' % (sys.executable, ROOT_HELPER),
                  ZIGMON_ACME_SETTLE='0', ZIGMON_ACME_POLL='0.2', ZIGMON_ACME_SEEN_WAIT='0',
                  ZIGMON_ACME_MANUAL_WAIT='120')


def plain80(text):
    """The plain-HTTP server's part of the file (the HTTPS one changes with
    every certificate put in)."""
    return text[:text.index('# HTTPS: the dashboard')]


def nginx_ok():
    return not NGINX or sh(['nginx', '-t', '-p', str(W), '-c', str(W / 'nginx.conf')]).returncode == 0


check(nginx_ok(), 'the test machine\'s nginx does not take the shipped file to begin with')

sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(DB), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'log_file': '', 'state_dir': str(STATE), 'acme': 0})
d = zigmon.Daemon()
TOLD = []
d.notify = lambda message, *a, **k: TOLD.append((str(message), k.get('about')))
# what root is handed, kept to look at - and handed on: root runs for real
HANDED = []
_root_apply = d.root_apply


def root_apply(pem=None, quiet=False):
    HANDED.append(dict(pem or {}))
    return _root_apply(pem=pem, quiet=quiet)


d.root_apply = root_apply
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def call(path, body=None, session=None):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': '192.168.40.10'}
    if session:
        headers['X-Zigmon-Session'] = session
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                 data=None if body is None else json.dumps(body).encode(),
                                 method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
S_OP = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''


def acme(body, session=None):
    return call('/api/acme', dict(body, session=session or S), session=session or S)


# the relay, as php-fpm runs it: index.php with the daemon's port and token of this test
PHP = bool(shutil.which('php'))
if PHP:
    shutil.copytree(HERE / 'web', W / 'web')
    api_php = (W / 'web' / 'zigmon-api.php').read_text()
    api_php = api_php.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
    api_php = api_php.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';",
                              "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
    (W / 'web' / 'zigmon-api.php').write_text(api_php)
    php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, str(W / 'web' / 'index.php')],
                           cwd=str(W / 'web'), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    PROCS.append(php)
    for _ in range(50):
        try:
            socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
else:
    print('  (no php - the CA asks the daemon\'s own road instead of index.php)')


def wait_idle(secs=120):
    end = time.time() + secs
    time.sleep(0.2)
    while zigmon.ACME_WORK['busy'] and time.time() < end:
        time.sleep(0.2)
    return not zigmon.ACME_WORK['busy']


def pubkey_of_cert(path):
    return sh(['openssl', 'x509', '-in', str(path), '-noout', '-pubkey']).stdout.strip()


def pubkey_of_key(path):
    return sh(['openssl', 'pkey', '-in', str(path), '-pubout']).stdout.strip()


def keys_left():
    """Any private key in the daemon's own folder outside its database (the
    account's key at the CA lives there, and is not the certificate's)."""
    out = []
    for p in STATE.rglob('*'):
        if p.is_file() and not p.name.startswith('history.db') and \
                'PRIVATE KEY' in p.read_text(errors='replace'):
            out.append(str(p))
    return out


try:
    # ---- the settings ------------------------------------------------------------------
    print('the settings')
    rc = d.runtime_config()
    for k in [k for k in zigmon.DEFAULTS if k.startswith('acme')]:
        check(k in zigmon.Daemon.TUNABLE, '%s is not a setting the dashboard can change' % k)
    for k in ('acme_dns_tsig_secret', 'acme_dns_token', 'acme_dns_key', 'acme_desec_token'):
        check(rc[k]['kind'] == 'secret', '%s is not kept off the page (%s)' % (k, rc[k]['kind']))
        check(zigmon.secret_key(k), '%s is not starred on the command line' % k)
    check(rc['acme']['kind'] == 'switch' and rc['acme_ca']['kind'] == 'choice'
          and rc['acme_challenge']['kind'] == 'choice' and rc['acme_dns']['kind'] == 'choice',
          'the switch and the choices of ACME are not drawn as such')
    for k, v in (('acme_email', 'nobody'), ('acme_url', 'http://ca.example.cz/dir'), ('acme_ca', 'another'),
                 ('acme_name', 'not a name'), ('acme_dns_tsig_secret', 'not base64!'), ('acme_days', 3),
                 ('acme_ca_pem', 'hello'), ('acme_resolvers', 'dns.google'), ('acme_dns', 'route53'),
                 ('acme_dns_server', 'ns1;rm -rf /')):
        try:
            d.save_config_overrides({k: v})
            check(False, '%s=%r was taken' % (k, v))
        except ValueError:
            pass
    long_pem = CA_PEM * 3
    got = d.save_config_overrides({
        'acme': 1, 'acme_email': 'owner@house.example', 'acme_ca': 'custom',
        'acme_url': BASE + '/directory', 'acme_ca_pem': long_pem, 'acme_name': NAME.upper() + '.',
        'acme_days': 30, 'acme_key': 'ec', 'acme_challenge': 'http-01', 'acme_dns_wait': 0,
        'acme_resolvers': '127.0.0.1', 'acme_dns_tsig_secret': 'c2VjcmV0LXRzaWctMTIzNA=='})
    check('acme' in got and zigmon.CONFIG['acme_name'] == NAME, 'the settings were not taken: %r %r'
          % (got, zigmon.CONFIG.get('acme_name')))
    check(zigmon.CONFIG['acme_ca_pem'] == long_pem.strip(), 'a CA certificate longer than 200 characters was cut')
    check(d.runtime_config()['acme_dns_tsig_secret']['value'] is True, 'the TSIG secret is shown to the page')

    # ---- port 80 answers the CA (root) -------------------------------------------------
    print('HTTP-01: port 80 answers the CA, between marks')
    text = NGINX_CONF.read_text()
    st = d.root_read('status.json')
    check(st.get('state') == 'done', 'root did not take port 80: %r' % st.get('said'))
    port80 = text[:text.index('# HTTPS: the dashboard')]
    check('location ^~ /.well-known/acme-challenge/ {' in port80 and port80.count('#zigmon# ACME-BEGIN') == 1,
          'the location for the CA is not in the port-80 server once')
    check('QUERY_STRING    api=acme-challenge;' in port80 and 'SCRIPT_FILENAME %s/index.php;' % (W / 'www') in port80
          and 'unix:%s' % (W / 'fpm.sock') in port80, 'the location does not reach PHP as the HTTPS server does')
    check('#zigmon# return 301 https://$host$request_uri;' in port80
          and re.search(r'location / \{\s*return 301 https://\$host\$request_uri;\s*\}', port80),
          'the redirect was not set aside into a location / of its own')
    check(nginx_ok(), 'nginx does not take the location for the CA')
    https = text[text.index('# HTTPS: the dashboard'):]
    check(https == ORIGINAL_CONF[ORIGINAL_CONF.index('# HTTPS: the dashboard'):] or 'acme-challenge' not in https,
          'the HTTPS server was changed for the CA')
    import importlib.util
    spec = importlib.util.spec_from_file_location('zroot', str(ROOT_HELPER))
    zroot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(zroot)
    twice, _w = zroot.acme_http_into(text, True)
    check(twice == text, 'the same file twice is not the same file')
    off, _w = zroot.acme_http_into(text, False)
    check(off == ORIGINAL_CONF, 'taken out, the port-80 server is not as it was')
    look = d.root_look(fresh=True)
    check((look.get('acme') or {}).get('http') is True, 'root\'s look does not say port 80 answers the CA')

    # ---- the challenge's own road ------------------------------------------------------
    print('the CA\'s question: only a token of an order going')
    code, _ = call('/api/acme/challenge?token=' + 'x' * 43)
    check(code == 404, 'a token nobody asked for was answered (%s)' % code)
    code, _ = call('/api/acme/challenge?token=../../etc')
    check(code == 404, 'something that is not a token was answered (%s)' % code)
    with zigmon.ACME_LOCK:
        zigmon.ACME_CHAL['T' * 43] = ('T' * 43 + '.thumb', time.time(), NAME, False)
    req = urllib.request.Request('http://127.0.0.1:%d/api/acme/challenge?token=%s' % (API_PORT, 'T' * 43))
    with urllib.request.urlopen(req, timeout=10) as r:
        check(json.loads(r.read()).get('auth') == 'T' * 43 + '.thumb',
              'the daemon does not answer a token without an account')
    if PHP:
        with urllib.request.urlopen('http://127.0.0.1:%d/.well-known/acme-challenge/%s' % (PHP_PORT, 'T' * 43),
                                    timeout=10) as r:
            check(r.read().decode() == 'T' * 43 + '.thumb', 'index.php does not give the CA the answer')
        for path in ('/.well-known/acme-challenge/' + 'U' * 43, '/.well-known/acme-challenge/a?api=status',
                     '/.well-known/acme-challenge/../index.php'):
            try:
                urllib.request.urlopen('http://127.0.0.1:%d%s' % (PHP_PORT, path), timeout=10)
                check(False, '%s was answered' % path)
            except urllib.error.HTTPError as e:
                check(e.code == 404, '%s: %s' % (path, e.code))
    zigmon.ACME_CHAL.clear()
    code, _ = call('/api/acme')
    check(code == 403, 'GET /api/acme answered without a sign-in (%s)' % code)
    code, _ = acme({'action': 'care', 'on': True}, session=S_OP)
    check(code == 403, 'an operator changed who looks after the certificate (%s)' % code)

    # ---- who looks after it, unsaid -------------------------------------------------------
    check(zigmon.acme_care(d), 'the self-signed certificate install.sh made is not ACME\'s to replace')
    check(zigmon.acme_targets(d) == [('web', NAME)], 'not ordered: %r' % zigmon.acme_targets(d))
    check(zigmon.acme_due(d, NAME).startswith('not ordered yet'), 'a certificate never ordered is not due')

    # ---- an order, from the half-minute chore --------------------------------------------
    print('an order: HTTP-01, end to end')
    zigmon.ACME_WORK['at'] = 0
    started = zigmon.acme_tick(d)
    check(started, 'the chore did not order the certificate that was due')
    check(not zigmon.acme_tick(d), 'the chore looked again at once')
    check(wait_idle(), 'the order did not end')
    v = acme({'action': 'care', 'on': True})[1]
    t = (v.get('targets') or [{}])[0]
    st = t.get('state') or {}
    check(st.get('ok') is True, 'the order failed: %s' % st.get('said'))
    check(CAS.seen and CAS.seen[-1] == ('php' if PHP else 'api', NAME), 'the CA did not see the answer: %r' % CAS.seen)
    check(not CAS.bad, 'requests not as RFC 8555 has them: %r' % CAS.bad[:5])
    check(CAS.signed >= 6 and CAS.made == 1, 'signed %d, accounts %d' % (CAS.signed, CAS.made))
    given = [h for h in HANDED if h.get('cert')]
    check(given and given[-1].get('key') and 'PRIVATE KEY' in given[-1]['key'],
          'root was not handed the certificate with its key')
    check(given and given[-1].get('keep_before') is True, 'the self-signed one it had was not kept to go back to')
    pem = (CERTS / 'server.pem').read_text()
    check(pubkey_of_cert(CERTS / 'server.pem') == pubkey_of_key(CERTS / 'server.key'),
          'the key root put in is not the certificate\'s')
    issuer = sh(['openssl', 'x509', '-in', str(CERTS / 'server.pem'), '-noout', '-issuer']).stdout
    check('Test ACME Root' in issuer, 'the certificate in place is not the CA\'s: %s' % issuer)
    san = sh(['openssl', 'x509', '-in', str(CERTS / 'server.pem'), '-noout', '-ext', 'subjectAltName']).stdout
    check('DNS:' + NAME in san, 'the certificate is not for %s: %s' % (NAME, san))
    key_kind = sh(['openssl', 'pkey', '-in', str(CERTS / 'server.key'), '-noout', '-text']).stdout
    check('P-256' in key_kind or 'prime256v1' in key_kind, 'the key is not ECDSA P-256 (acme_key=ec)')
    check(d.tls_conf().get('how') == 'ACME', 'the certificate is not known to have come by ACME')
    check(not keys_left(), 'a key was left in the daemon\'s folder: %r' % keys_left())
    check(not list(STATE.glob('zigmon-acme-*')) and not list(STATE.glob('zigmon-dns-*')),
          'a folder of the order was left behind')
    acc = json.loads(d.store.get_meta('acme_account') or '{}')
    check(acc.get('kid', '').startswith(BASE) and 'PRIVATE KEY' in acc.get('key', ''),
          'the account and its key are not kept')
    check(t.get('care') is True and v.get('account', {}).get('key') is True and 'PRIVATE' not in json.dumps(v),
          'the view says the account\'s key, or not who looks after it')
    check(any('came from the ACME CA' in m and a == 'acme' for m, a in TOLD), 'nothing was told of it: %r' % TOLD)
    events = json.dumps(d.store.events(limit=50)) if hasattr(d.store, 'events') else ''
    check(not events or 'came from the ACME CA' in events, 'the event was not written')
    check((v.get('targets') or [{}])[0].get('before') is not None, 'the certificate from before is not offered back')

    # ---- renewal ----------------------------------------------------------------------
    print('renewal: at acme_days, or a third of a short life')
    check(zigmon.acme_due(d, NAME) == '', 'a 90-day certificate is due at once: %r' % zigmon.acme_due(d, NAME))
    now = time.time()
    st = zigmon.acme_state(d)

    def with_life(before_days, after_days):
        d.store.set_meta('acme_state', json.dumps(dict(st, not_before=now - before_days * 86400,
                                                       not_after=now + after_days * 86400)))
        return zigmon.acme_due(d, NAME)
    check(with_life(70, 20).startswith('19') or with_life(70, 20).startswith('20'),
          '20 days left of 90 is not due (acme_days 30)')
    check(with_life(50, 40) == '', '40 days left of 90 is due')
    check(with_life(6, 2.5) != '', '2.5 days left of a 9-day certificate is not due (a third of its life)')
    check(with_life(5, 4) == '', '4 days left of a 9-day certificate is due - a short-lived certificate '
          'would be ordered again every hour')
    check(zigmon.acme_due(d, 'other.house.example').startswith('not ordered yet'),
          'a new name is not ordered for')
    d.store.set_meta('acme_state', json.dumps(st))

    # ---- an account the CA forgot ------------------------------------------------------
    print('an account the CA no longer knows: made anew')
    CAS.forget = True
    CAS.days = 9
    kid_was = acc.get('kid')
    try:
        zigmon.acme_order(d, NAME, 'test')
    except zigmon.AcmeError as e:
        check(False, 'the order with a forgotten account failed: %s' % e)
    check(CAS.made == 2, 'no new account was made (%d)' % CAS.made)
    check(json.loads(d.store.get_meta('acme_account'))['kid'] != kid_was, 'the new account was not kept')
    check(zigmon.acme_due(d, NAME) == '', 'a fresh 9-day certificate is due at once (acme_days 30)')

    # ---- a failed try ------------------------------------------------------------------
    print('a failed try: said, and not again for six hours')
    CAS.fail_next = True
    try:
        zigmon.acme_order(d, NAME, 'test')
        check(False, 'a challenge the CA called invalid was taken')
    except zigmon.AcmeError as e:
        check('Invalid response' in str(e), 'the CA\'s words are not said: %s' % e)
    st = zigmon.acme_state(d)
    check(st.get('ok') is False and 'Invalid response' in (st.get('said') or '') and st.get('not_after'),
          'the failure is not kept with what came before: %r' % st)
    check(any('no certificate for' in m and 'Invalid response' in m for m, a in TOLD), 'the failure was not told')
    d.store.set_meta('acme_state', json.dumps(dict(st, not_after=time.time() + 86400,
                                                   not_before=time.time() - 89 * 86400)))
    check(zigmon.acme_due(d, NAME) == '', 'a failed try is tried again before six hours')
    zigmon.ACME_WORK['at'] = 0
    check(not zigmon.acme_tick(d), 'the chore ordered again right after a failure')
    d.store.set_meta('acme_state', json.dumps(dict(st, not_after=time.time() + 86400,
                                                   not_before=time.time() - 89 * 86400,
                                                   failed_at=time.time() - 7 * 3600)))
    check(zigmon.acme_due(d, NAME) != '', 'a failed try is not tried again after six hours')
    zigmon.ACME_WORK['at'] = 0
    check(zigmon.acme_tick(d), 'the chore did not try again after six hours')
    check(wait_idle(), 'the renewal did not end')
    check(zigmon.acme_state(d).get('ok') is True, 'the renewal failed: %s' % zigmon.acme_state(d).get('said'))
    CAS.days = 90

    # ---- the command line ----------------------------------------------------------------
    print('the command line: --acme, --acme-order followed')
    import argparse
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = zigmon.cmd_acme(argparse.Namespace(acme=True, acme_order=None, json=False), zigmon.Palette(False))
    said = out.getvalue()
    check(rc == 0 and NAME in said and 'by ACME' in said and 'ok ' in said, 'zigmon --acme says: %s' % said)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = zigmon.cmd_acme(argparse.Namespace(acme=False, acme_order='all', json=False), zigmon.Palette(False))
    said = out.getvalue()
    check(rc == 0 and 'being ordered' in said and 'the CA looks at http://' in said and 'is made' in said,
          'zigmon --acme-order did not follow the order: %s' % said)

    # ---- one put in by hand is kept --------------------------------------------------------
    print('a certificate put in by hand is kept; Order it now; Back to the one before')
    sh(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(W / 'own.key'), '-out',
        str(W / 'own.pem'), '-days', '200', '-subj', '/CN=%s/O=House CA' % NAME])
    code, out = call('/api/tls', {'action': 'tls_upload', 'cert': (W / 'own.pem').read_text()
                                  + (W / 'own.key').read_text(), 'session': S}, session=S)
    check(code == 200, 'the upload was refused: %s' % out)
    check(not zigmon.acme_care(d) and zigmon.acme_targets(d) == [],
          'a certificate put in by hand is still ACME\'s to replace')
    check(d.tls_conf().get('how') == 'uploaded', 'the upload is not known as one: %r' % d.tls_conf().get('how'))
    code, tls = call('/api/tls', session=S)
    check(tls.get('acme', {}).get('on') and tls['acme'].get('care') is False,
          'Certificates does not say its own certificate is kept: %r' % tls.get('acme'))
    zigmon.ACME_WORK['at'] = 0
    check(not zigmon.acme_tick(d), 'the chore ordered over a certificate put in by hand')
    code, out = acme({'action': 'order', 'target': 'web'})
    check(code == 200 and out.get('mine') == ['web'], 'Order it now was refused, or did not give it back to '
          'ACME: %s %r' % (code, out.get('mine') or out.get('error')))
    check(wait_idle(), 'the order did not end')
    check(zigmon.acme_state(d).get('ok') is True, 'Order it now failed: %s' % zigmon.acme_state(d).get('said'))
    own_kept = W / 'own' / 'acme-before.json'
    check(own_kept.exists() and oct(own_kept.stat().st_mode & 0o777) == '0o600',
          'root did not keep the uploaded one (0600, its own folder)')
    v = call('/api/acme', session=S)[1]
    before = (v.get('targets') or [{}])[0].get('before') or {}
    check(before.get('how') == 'uploaded' and not before.get('ran_out'), 'the one before is not offered: %r' % before)
    check('PRIVATE' not in json.dumps(v) and 'PRIVATE' not in (d.store.get_meta('acme_before') or ''),
          'the key of the one before is on the daemon\'s side')
    code, out = acme({'action': 'put_back', 'target': 'web'})
    check(code == 200, 'Back to the one before was refused: %s' % out)
    check(pubkey_of_cert(CERTS / 'server.pem') == pubkey_of_cert(W / 'own.pem')
          and pubkey_of_key(CERTS / 'server.key') == pubkey_of_key(W / 'own.key'),
          'the uploaded certificate and its key are not back')
    check(not own_kept.exists(), 'the one before is still kept after it was put back')
    check(not zigmon.acme_care(d) and d.tls_conf().get('how') == 'uploaded',
          'after Back to the one before ACME still renews it')
    code, out = acme({'action': 'care', 'on': True})
    check(code == 200 and out['targets'][0]['care'] is True, 'Look after it did not give it to ACME')

    # ---- DNS-01 by hand ------------------------------------------------------------------
    print('DNS-01 by hand: the record shown, It is in DNS')
    d.save_config_overrides({'acme_challenge': 'dns-01', 'acme_dns': 'manual'})
    check(plain80(NGINX_CONF.read_text()) == plain80(ORIGINAL_CONF), 'port 80 was not given back as it was for DNS-01')
    check(nginx_ok(), 'nginx does not take port 80 given back')
    code, out = acme({'action': 'order', 'target': 'web'})
    check(code == 200, 'the order was refused: %s' % out)
    end = time.time() + 60
    while not zigmon.ACME_MANUAL.get('txt') and time.time() < end:
        time.sleep(0.2)
    v = call('/api/acme', session=S)[1]
    m = v.get('manual') or {}
    check(m.get('rr') == '_acme-challenge.' + NAME and m.get('txt'), 'the record to put in is not shown: %r' % m)
    check(v.get('dns_guide', {}).get('rows', [{}])[0].get('type') == 'TXT', 'In your DNS does not say the TXT record')
    CAS.dns['_acme-challenge.' + NAME] = [m.get('txt')]
    code, out = acme({'action': 'manual_done'})
    check(code == 200, 'It is in DNS was refused: %s' % out)
    check(wait_idle(), 'the order did not end')
    check(zigmon.acme_state(d).get('ok') is True, 'DNS-01 by hand failed: %s' % zigmon.acme_state(d).get('said'))
    check(CAS.seen[-1] == ('dns', NAME), 'the CA did not look in DNS')
    code, out = acme({'action': 'manual_done'})
    check(code == 400, 'It is in DNS was taken with no order waiting')

    # ---- DNS-01 by RFC 2136 -------------------------------------------------------------
    print('DNS-01 by RFC 2136: nsupdate, the TSIG key never on its command line')
    LOGF = W / 'nsupdate.log'
    fake = W / 'nsupdate'
    fake.write_text('''#!%s
import json, os, re, stat, sys
args = sys.argv[1:]
script = sys.stdin.read()
key = args[args.index('-k') + 1] if '-k' in args else ''
row = {'argv': args, 'script': script, 'key': open(key).read() if key else '',
       'mode': oct(os.stat(key).st_mode & 0o777) if key else ''}
with open(%r, 'a') as f:
    f.write(json.dumps(row) + '\\n')
zone = %r
recs = json.load(open(zone)) if os.path.exists(zone) else {}
for op, name, txt in re.findall(r'update (add|delete) (\\S+)(?: 60)? TXT "([^"]+)"', script):
    if op == 'add':
        recs.setdefault(name, []).append(txt)
    else:
        recs[name] = [x for x in recs.get(name, []) if x != txt]
json.dump(recs, open(zone, 'w'))
''' % (sys.executable, str(LOGF), str(W / 'zone.json')))
    fake.chmod(0o755)
    os.environ['ZIGMON_NSUPDATE'] = str(fake)
    SECRET = 'c2VjcmV0LXRzaWctMTIzNA=='
    d.save_config_overrides({'acme_dns': 'rfc2136', 'acme_dns_server': '127.0.0.1:5353',
                             'acme_dns_zone': 'house.example', 'acme_dns_tsig_name': 'zigmon-acme.',
                             'acme_dns_tsig_alg': 'hmac-sha256'})
    CAS.dns.clear()
    _put = zigmon._dns_rfc2136

    def put_seen(rr, txt):
        undo = _put(rr, txt)
        CAS.dns.update(json.loads((W / 'zone.json').read_text()))      # the zone, as the CA reads it
        return undo
    zigmon._dns_rfc2136 = put_seen
    try:
        zigmon.acme_order(d, NAME, 'test')
    except zigmon.AcmeError as e:
        check(False, 'DNS-01 by RFC 2136 failed: %s' % e)
    zigmon._dns_rfc2136 = _put
    rows = [json.loads(x) for x in LOGF.read_text().splitlines()] if LOGF.exists() else []
    check(len(rows) == 2 and 'update add _acme-challenge.%s 60 TXT' % NAME in rows[0]['script']
          and 'update delete' in rows[1]['script'], 'nsupdate was not asked to add and then take away: %r' % rows)
    check(all(SECRET not in ' '.join(r['argv']) for r in rows), 'the TSIG secret was on nsupdate\'s command line')
    check(all(r['mode'] == '0o600' and 'secret "%s"' % SECRET in r['key'] and 'zigmon-acme.' in r['key']
              and 'hmac-sha256' in r['key'] for r in rows), 'the key file was not the key, or not 0600: %r'
          % [(r['mode'], r['key'][:40]) for r in rows])
    check(all(r['script'].startswith('server 127.0.0.1 5353\nzone house.example\n') for r in rows),
          'the server and the zone were not said to nsupdate')
    check(all(not os.path.exists(r['argv'][r['argv'].index('-k') + 1]) for r in rows),
          'the key file was left behind')
    check(json.loads((W / 'zone.json').read_text()).get('_acme-challenge.' + NAME) == [],
          'the TXT record was not taken away again')
    check(not keys_left(), 'a key was left in the daemon\'s folder: %r' % keys_left())

    # ---- what goes into your DNS ----------------------------------------------------------
    print('In your DNS: a CNAME to the zone the records go into')
    d.save_config_overrides({'acme_dns_alias': 'acme.other.example'})
    g = zigmon.acme_dns_guide(d)
    check(g['rows'][0]['type'] == 'CNAME' and g['rows'][0]['record'] == '_acme-challenge.' + NAME
          and g['rows'][0]['value'] == '_acme-challenge.zigmon.acme.other.example.',
          'the CNAME your DNS needs is not said: %r' % g['rows'])
    check(zigmon.acme_dns_where(NAME) == ('_acme-challenge.zigmon.acme.other.example',
                                          '_acme-challenge.zigmon.acme.other.example'),
          'the record does not go into the alias zone')
    d.save_config_overrides({'acme_dns': 'desec', 'acme_desec_domain': 'acme.house.example'})
    g = zigmon.acme_dns_guide(d)
    check([r['type'] for r in g['rows']] == ['NS', 'CNAME'], 'a domain of your own at deSEC: the NS records '
          'are not said: %r' % g['rows'])

    # ---- the keys Let's Encrypt takes, and both at once (5.33.2) -------------------------
    print('the key: RSA 2048 / 3072 / 4096, ECDSA P-256 / P-384, or both')
    d.save_config_overrides({'acme_dns': 'manual', 'acme_challenge': 'http-01', 'acme_dns_alias': ''})
    for bad_kind in ('rsa1024', 'ec521', 'dsa'):
        try:
            d.save_config_overrides({'acme_key': bad_kind})
            check(zigmon.CONFIG.get('acme_key') != bad_kind, 'a key Let\'s Encrypt does not take was saved: %s' % bad_kind)
        except ValueError:
            pass

    def key_text(path):
        return sh(['openssl', 'pkey', '-in', str(path), '-noout', '-text']).stdout

    for kind, words in (('rsa3072', 'Private-Key: (3072 bit'), ('ec384', 'P-384')):
        d.save_config_overrides({'acme_key': kind})
        try:
            zigmon.acme_order(d, NAME, 'test')
        except zigmon.AcmeError as e:
            check(False, 'an order with a %s key failed: %s' % (kind, e))
        check(words in key_text(CERTS / 'server.key') or (kind == 'ec384' and 'secp384r1' in key_text(CERTS / 'server.key')),
              'the key put in is not %s' % kind)
        check(len(re.findall(r'(?m)^\s*ssl_certificate\s', NGINX_CONF.read_text())) == 1,
              'one key, but two certificates named (%s)' % kind)
    check(zigmon.DEFAULTS.get('acme_key') == 'dual', 'both is not what a house that never chose gets')
    d.save_config_overrides({'acme_key': 'dual-strong'})
    try:
        zigmon.acme_order(d, NAME, 'test')
    except zigmon.AcmeError as e:
        check(False, 'an order of RSA 4096 + ECDSA P-384 failed: %s' % e)
    strong = re.findall(r'(?m)^\s*ssl_certificate_key\s+(\S+);', NGINX_CONF.read_text())
    check(len(strong) == 2 and 'Private-Key: (4096 bit' in key_text(strong[0])
          and ('P-384' in key_text(strong[1]) or 'secp384r1' in key_text(strong[1])),
          'RSA 4096 + ECDSA P-384 is not what was put in')
    # the account's own key: ES384, then RS256 - each a new account at the CA
    for akind, alg in (('ec384', 'ES384'), ('rsa2048', 'RS256')):
        made = CAS.made
        del CAS.algs[:]
        d.save_config_overrides({'acme_account_key': akind, 'acme_key': 'ec'})
        try:
            zigmon.acme_order(d, NAME, 'test')
        except zigmon.AcmeError as e:
            check(False, 'an order with an %s account failed: %s' % (akind, e))
        check(CAS.made == made + 1, 'a new account was not made for an %s key' % akind)
        check(CAS.algs and set(CAS.algs) == {alg}, 'the account did not sign with %s: %r' % (alg, sorted(set(CAS.algs))))
        acc = json.loads(d.store.get_meta('acme_account') or '{}')
        check(acc.get('kind') == akind, 'the account\'s key kind is not kept: %r' % acc.get('kind'))
        v = acme({'action': 'care', 'on': True})[1]
        check((v.get('account') or {}).get('kind', '').startswith(zigmon.ACME_KEYS[akind][0]),
              'the card does not say the account\'s key: %r' % (v.get('account') or {}))
        made = CAS.made
        try:
            zigmon.acme_order(d, NAME, 'test')
        except zigmon.AcmeError as e:
            check(False, 'a second order with an %s account failed: %s' % (akind, e))
        check(CAS.made == made, 'the account was made again though its key did not change (%s)' % akind)
    certkey = key_text(CERTS / 'server.key')
    check('P-256' in certkey or 'prime256v1' in certkey, 'the certificate\'s key followed the account\'s')
    d.save_config_overrides({'acme_account_key': 'ec', 'acme_key': 'dual'})
    try:
        zigmon.acme_order(d, NAME, 'test')
    except zigmon.AcmeError as e:
        check(False, 'an order of both failed: %s' % e)
    conf = NGINX_CONF.read_text()
    certs = re.findall(r'(?m)^\s*ssl_certificate\s+(\S+);', conf)
    keys = re.findall(r'(?m)^\s*ssl_certificate_key\s+(\S+);', conf)
    check(len(certs) == 2 and len(keys) == 2, 'both certificates are not named to nginx: %r %r' % (certs, keys))
    if len(certs) == 2 and len(keys) == 2:
        check('rsaEncryption' in sh(['openssl', 'x509', '-in', certs[0], '-noout', '-text']).stdout,
              'the first certificate - the one sent by default - is not RSA')
        check('id-ecPublicKey' in sh(['openssl', 'x509', '-in', certs[1], '-noout', '-text']).stdout,
              'the second certificate is not ECDSA')
        check(pubkey_of_cert(Path(certs[1])) == pubkey_of_key(Path(keys[1])), 'the ECDSA key is not its certificate\'s')
        check(pubkey_of_cert(Path(certs[0])) == pubkey_of_key(Path(keys[0])), 'the RSA key is not its certificate\'s')
        check(certs[0] == str(CERTS / 'server.pem'), 'the broker\'s file is not the RSA one')
    check(nginx_ok(), 'nginx does not take two certificates as root wrote them')
    look = d.root_look(fresh=True).get('tls') or {}
    check((look.get('alt_info') or {}).get('key', '').startswith('EC'), 'the card is not told of the second one: %r'
          % look.get('alt_info'))
    t = (acme({'action': 'care', 'on': True})[1].get('targets') or [{}])[0]
    check(t.get('keys') == 'RSA 2048 + ECDSA P-256' and t.get('keys_asked') == 'RSA 2048 + ECDSA P-256',
          'the card does not say the keys: %r / %r' % (t.get('keys'), t.get('keys_asked')))
    check(not keys_left(), 'a key was left in the daemon\'s folder: %r' % keys_left())
    # back to one: the second goes from nginx
    d.save_config_overrides({'acme_key': 'ec'})
    try:
        zigmon.acme_order(d, NAME, 'test')
    except zigmon.AcmeError as e:
        check(False, 'an order of one after both failed: %s' % e)
    check(len(re.findall(r'(?m)^\s*ssl_certificate\s', NGINX_CONF.read_text())) == 1,
          'the second certificate stayed named after one was ordered')
    check(nginx_ok(), 'nginx does not take one certificate after two')

    # ---- Check DNS kept, for the card after a reload (5.34.2) -----------------------------
    zigmon.dns_ask_rc = lambda name, kind: (0, [('NS', 'ns1.desec.io.')] if kind == 2 else [])
    code, out = acme({'action': 'dns_check'})
    check(code == 200 and out.get('rows') is not None, 'Check DNS did not answer: %s %s' % (code, out))
    view = acme({'action': 'care', 'on': True})[1]
    kept = view.get('dns_checked') or {}
    check(kept.get('at') and kept.get('rows') and len(kept['rows']) == len(out.get('rows') or []),
          'the last Check DNS is not kept for the card after a reload: %r' % kept)

    # ---- switched off -------------------------------------------------------------------
    d.save_config_overrides({'acme': 0, 'acme_challenge': 'http-01', 'acme_dns_alias': ''})
    check(plain80(NGINX_CONF.read_text()) == plain80(ORIGINAL_CONF), 'switched off, port 80 is not as it was')
    check(zigmon.acme_targets(d) == [], 'switched off, ACME still orders')
    code, out = acme({'action': 'order'})
    check(code == 400 and 'off' in out.get('error', ''), 'an order was taken with ACME off: %s' % out)

    # ---- the relay ------------------------------------------------------------------------
    print('the relay')
    page = (HERE / 'web' / 'index.php').read_text()
    allowed = page[page.index("if (in_array($what, ['scenes-save'"):]
    allowed = allowed[:allowed.index('], true)')]
    check("'acme-do'" in allowed, 'acme-do is not let through by the relay')
    check("'acme-do' => '/api/acme'" in page, 'acme-do is not mapped to /api/acme')
    check("$what === 'acme'" in page and "zigmon_relay('/api/acme')" in page, 'the relay does not read /api/acme')
    check("'/api/acme/challenge?token='" in page, 'the relay has no road for the CA\'s question')
    check('/api/acme' in zigmon.ApiHandler.ALWAYS_LOCKED, '/api/acme is not an administrator\'s read')
finally:
    for p in PROCS:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
    try:
        api.stop()
    except Exception:
        pass
    ca_srv.shutdown()

if bad:
    print('\n%d problem(s)' % len(bad))
    raise SystemExit(1)
shutil.rmtree(str(W), ignore_errors=True)
print('\nAutomatic certificates: every check passed')
