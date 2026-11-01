#!/usr/bin/env python3
"""Certificates from acme (5.40, acme push protocol 1): the receiver, the
whole way round, with the test playing acme.

  * the crypto of section 8 of the document, every vector, with the
    cryptography package and in plain Python (forced) - and the primitives
    against RFC 8032 (Ed25519 test 1), RFC 7748 5.2 and 6.1 (X25519) and
    RFC 5869 A.1 (HKDF);
  * the real daemon through the real relay (php -S on web/index.php), root
    run as root would run it (ZIGMON_ROOT_RUN): hello off and on, pairing by
    the code (a good proof, the confirm, wrong proofs counted - five and the
    code is gone - and one run out), pairing by acme's key pasted, the
    inventory (the dashboard, the broker reading its files, the server in
    front following it or with its own), every signature refusal, the nonces
    kept across a restart of the daemon, and install: one, two (ECDSA + RSA),
    auto with a wildcard, already there (root not asked), key_mismatch,
    bad_key, expired, not_yet_valid, names, other names allowed, no_slot,
    the front following (409) and the front with its own (proxy_tls_ask);
  * additive only (chapter 0): every certificate function there was - upload
    (PEM, PFX), a request and its answer, self-signed, the TLS settings, the
    download and the export, the own ACME's order and renewal, the server in
    front following and with its own, a backup and its restore - works with
    acme push off, and again with it on and paired; after a push an upload
    replaces it (manual) and Look after it gives it back to the own ACME;
    switched off, nothing is taken and the certificate stays;
  * the card on Certificates in Chromium (php -S + Playwright).

    python3 test/acmepush.py

Needs openssl and php; nginx for nginx -t where it is there; Chromium by
Playwright for the card (skipped without it). Ports 19631 (the daemon),
19632 (php -S).
"""
import base64
import hashlib
import json
import os
import re
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
ROOT_HELPER = HERE / 'deploy' / 'zigmon_root.py'
W = Path(tempfile.mkdtemp(prefix='zigmon-acmepush-check-'))
API_PORT, PHP_PORT = 19631, 19632
NAME = 'zigmon.house.example'
HOST = socket.gethostname().split('.')[0] or 'zigmon'
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


try:
    from cryptography.hazmat.primitives.asymmetric import ed25519 as c_ed
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False

sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

Z = zigmon.__dict__


def zf(name):
    """A function of the daemon's - or one that says it is not there (an
    older zigmon: every check of it fails)."""
    def missing(*a, **k):
        raise AttributeError('zigmon has no %s' % name)
    return Z.get(name) or missing


# ---- the signer (acme's half; the daemon only verifies) ------------------------------------
def ed_sign(seed, msg):
    if HAVE_CRYPTO and Z.get('PUSH_LIB'):
        return c_ed.Ed25519PrivateKey.from_private_bytes(seed).sign(msg)
    L = 2 ** 252 + 27742317777372353535851937790883648493
    a, prefix = zf('_push_ed_secret')(seed)
    B = Z.get('_PUSH_ED_B')
    enc, mul = zf('_push_ed_encode'), zf('_push_ed_mul')
    A = enc(mul(a, B))
    r = int.from_bytes(hashlib.sha512(prefix + msg).digest(), 'little') % L
    R = enc(mul(r, B))
    h = int.from_bytes(hashlib.sha512(R + A + msg).digest(), 'little') % L
    return R + ((r + h * a) % L).to_bytes(32, 'little')


def b64(b):
    return base64.b64encode(b).decode()


def canonical(op, app_id, kid, ts, nonce, body):
    return '\n'.join(['acme-push/1', op, app_id, kid, str(ts), nonce, hashlib.sha256(body).hexdigest()]).encode()


# ---- section 8, both ways ------------------------------------------------------------------
print('the crypto of section 8')
V = {'pub': 'A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg=', 'kid': '56475aa75463474c',
     'canon': 'acme-push/1\ninventory\n00112233445566778899aabbccddeeff\n56475aa75463474c\n1793534400\n'
              'n0nce-0123456789ab\nd3a920a683e4d42e6f5a6971cb03c2fd4361964436db5f7460c4a638836222d8',
     'sig': '7nqJW4/NR3Et6pZx3B8qS3rvQGaQR0UTlNdptpRs4lxaZtc3Cf2zBRkOWPB0tV/rmQNfwbcl2/FKJ3Pu2h/bDg==',
     'app': 'NYBy1jZYgNGu6jKa35EhODhR7SGijjt16WXQ0s0WYlQ=', 'epk': 'eaYx7t4b+cmPEgMs3q3Q56B5OY/HhriMyEbsia+FpRo=',
     'shared': '04c304fb1ca83cee75e206344231f33797e07d9929db670994b7c6fbeb1dc255',
     'aes': '14067e8e830df01ae120ce73359b5f01e9d26931fe6ecdfa4d1a00fb9fe2e7b0',
     'nonce': 'YGFiY2RlZmdoaWpr', 'ct': '2UbSrj9NwnCBu3qZW4U7MzxzlGw=',
     'proof': 'e8e1978c03896460ce7f6e1697d5a5220c8f3a1cd8a01d2fc2e838dbd9318b39'}
APP_ID0, FP0 = '00112233445566778899aabbccddeeff', 'ab' * 32
ways = (['cryptography'] if HAVE_CRYPTO and Z.get('PUSH_LIB_FOUND') == 'cryptography' else []) + ['']
if HAVE_CRYPTO and Z.get('PUSH_LIB_FOUND') != 'cryptography':
    check(False, 'the daemon did not take the cryptography package that is here')
for lib in ways:
    how = lib or 'plain Python'
    zigmon.__dict__['PUSH_LIB'] = lib
    try:
        seed, app, eph, gn = bytes(range(32)), bytes(range(32, 64)), bytes(range(64, 96)), bytes(range(96, 108))
        pub = zf('push_ed25519_public')(seed)
        check(b64(pub) == V['pub'], '%s: acme\'s public key from the seed' % how)
        check(zf('push_key_parse')('acme-push-ed25519 %s acme@acme1' % V['pub']) == (pub, 'acme@acme1'),
              '%s: the key as text does not read' % how)
        check(zf('push_key_id')(pub) == V['kid'], '%s: the key id' % how)
        body = b'{"slots": ["auto"]}'
        canon = zf('push_canonical')('inventory', APP_ID0, V['kid'], 1793534400, 'n0nce-0123456789ab', body)
        check(canon.decode() == V['canon'], '%s: the canonical string' % how)
        check(b64(ed_sign(seed, canon)) == V['sig'], '%s: the signature of the vector' % how)
        check(zf('push_ed25519_verify')(pub, base64.b64decode(V['sig']), canon), '%s: the signature does not verify' % how)
        check(not zf('push_ed25519_verify')(pub, base64.b64decode(V['sig']), canon + b'x'),
              '%s: a signature over something else verifies' % how)
        apub = zf('push_x25519')(app)
        check(b64(apub) == V['app'], '%s: the application\'s public key' % how)
        epk = zf('push_x25519')(eph)
        check(b64(epk) == V['epk'], '%s: epk' % how)
        shared = zf('push_x25519')(eph, apub)
        check(shared.hex() == V['shared'] and zf('push_x25519')(app, epk) == shared, '%s: shared' % how)
        aes = zf('push_hkdf')(shared, epk + apub, b'acme-push/1 key_pem')
        check(aes.hex() == V['aes'], '%s: aes_key' % how)
        aad = ('acme-push/1 key\n%s\n%s' % (APP_ID0, FP0)).encode()
        ct = zf('push_gcm_seal')(aes, gn, b'KEY\n', aad)
        check(b64(gn) == V['nonce'] and b64(ct) == V['ct'], '%s: key.ct %s' % (how, b64(ct)))
        sealed = {'alg': 'X25519-HKDF-SHA256-A256GCM', 'epk': V['epk'], 'nonce': V['nonce'], 'ct': V['ct']}
        check(zf('push_open_key')(sealed, app, APP_ID0, FP0) == 'KEY\n', '%s: the sealed key does not open' % how)
        try:
            zf('push_open_key')(sealed, app, APP_ID0, 'cd' * 32)
            check(False, '%s: a key sealed for another certificate opened' % how)
        except Exception as e:                           # noqa: BLE001
            check(getattr(e, 'code', '') == 'bad_key', '%s: another fingerprint is not bad_key: %r' % (how, e))
        check(zf('push_proof')('ABCD-EFGH-JKMN-PQRS', 'pair', APP_ID0, V['kid'], 'n0nce-0123456789ab') == V['proof'],
              '%s: the pair proof' % how)
        # the primitives themselves
        sk = bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
        pk = bytes.fromhex('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')
        sg = bytes.fromhex('e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bac'
                           'c61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b')
        check(zf('push_ed25519_public')(sk) == pk and ed_sign(sk, b'') == sg and
              zf('push_ed25519_verify')(pk, sg, b''), '%s: RFC 8032 test 1' % how)
        x = zf('push_x25519')
        check(x(bytes.fromhex('a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4'),
                bytes.fromhex('e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c')).hex() ==
              'c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552', '%s: RFC 7748 5.2 (1)' % how)
        check(x(bytes.fromhex('4b66e9d4d1b4673c5ad22691957d6af5c11b6421e0ea01d42ca4169e7918ba0d'),
                bytes.fromhex('e5210f12786811d3f4b7959d0538ae2c31dbe7106fc03c3efc4cd549c715a493')).hex() ==
              '95cbde9476e8907d7aade45cb4b873f88b595a68799fa152e6f8f7647aac7957', '%s: RFC 7748 5.2 (2)' % how)
        a_sk = bytes.fromhex('77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a')
        b_sk = bytes.fromhex('5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb')
        check(x(a_sk).hex() == '8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a' and
              x(b_sk).hex() == 'de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f' and
              x(a_sk, x(b_sk)).hex() == x(b_sk, x(a_sk)).hex() ==
              '4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742', '%s: RFC 7748 6.1' % how)
        check(zf('push_hkdf')(b'\x0b' * 22, bytes(range(13)), bytes(range(0xf0, 0xfa)), 42).hex() ==
              '3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865',
              '%s: RFC 5869 A.1' % how)
        big = os.urandom(3300)
        check(zf('push_gcm_open')(aes, gn, zf('push_gcm_seal')(aes, gn, big, aad), aad) == big,
              '%s: a key of 3300 bytes does not come back' % how)
    except Exception as e:                               # noqa: BLE001
        check(False, '%s: %s: %s' % (how, type(e).__name__, e))
if HAVE_CRYPTO and ways[0] == 'cryptography':
    try:
        zigmon.__dict__['PUSH_LIB'] = 'cryptography'
        k, n, aad = os.urandom(32), os.urandom(12), b'aad'
        one = zf('push_gcm_seal')(k, n, b'x' * 777, aad)
        zigmon.__dict__['PUSH_LIB'] = ''
        check(zf('push_gcm_seal')(k, n, b'x' * 777, aad) == one and zf('push_gcm_open')(k, n, one, aad) == b'x' * 777,
              'AES-256-GCM in plain Python is not the cryptography package\'s')
    except Exception as e:                               # noqa: BLE001
        check(False, 'AES-256-GCM both ways: %s' % e)
# the daemon below runs on the plain one when there is no cryptography; with it, on it
zigmon.__dict__['PUSH_LIB'] = Z.get('PUSH_LIB_FOUND', '')


# ---- a CA of the test's own, and its certificates ----------------------------------------------
CAD = W / 'ca'
CAD.mkdir()
sh(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes', '-keyout',
    str(CAD / 'ca.key'), '-out', str(CAD / 'ca.pem'), '-days', '60', '-subj', '/CN=Test Push Root',
    '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign'])
(CAD / 'index.txt').write_text('')
(CAD / 'serial').write_text('1000\n')
(CAD / 'ca.cnf').write_text('[ca]\ndefault_ca=c\n[c]\ndir=%s\ndatabase=$dir/index.txt\nnew_certs_dir=$dir\n'
                            'serial=$dir/serial\ndefault_md=sha256\npolicy=p\nunique_subject=no\n'
                            'copy_extensions=copy\n[p]\ncommonName=supplied\n' % CAD)
CA_PEM = (CAD / 'ca.pem').read_text()
SEQ = [0]


def issue(names, kind='rsa', start=None, end=None):
    """(certificate, key) for the names, from the test's CA."""
    SEQ[0] += 1
    t = W / ('c%d' % SEQ[0])
    t.mkdir()
    newkey = ['-newkey', 'rsa:2048'] if kind.startswith('rsa') else \
        ['-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:%s' % ('P-384' if kind == 'ec384' else 'P-256')]
    sh(['openssl', 'req', '-new', '-nodes', '-keyout', str(t / 'k.pem'), '-out', str(t / 'r.csr'),
        '-subj', '/CN=%s' % names[0], '-addext', 'subjectAltName=%s' % ','.join('DNS:' + n for n in names)] + newkey)
    when = ['-startdate', start or time.strftime('%Y%m%d%H%M%SZ', time.gmtime(time.time() - 3600)),
            '-enddate', end or time.strftime('%Y%m%d%H%M%SZ', time.gmtime(time.time() + 40 * 86400))]
    got = sh(['openssl', 'ca', '-batch', '-config', str(CAD / 'ca.cnf'), '-cert', str(CAD / 'ca.pem'), '-keyfile',
              str(CAD / 'ca.key'), '-in', str(t / 'r.csr'), '-out', str(t / 'c.pem'), '-notext'] + when)
    if got.returncode != 0:
        raise SystemExit('the test CA did not issue: %s' % got.stderr[-300:])
    cert = (t / 'c.pem').read_text()
    cert = re.search(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', cert, re.S).group(0) + '\n'
    return cert, (t / 'k.pem').read_text()


def der_fp(pem):
    m = re.search(r'-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----', pem, re.S)
    return hashlib.sha256(base64.b64decode(re.sub(r'\s+', '', m.group(1)))).hexdigest()


def file_fp(path):
    try:
        return der_fp(Path(path).read_text())
    except (OSError, AttributeError):
        return None


# ---- the machine, as test/acme.py stands it in ---------------------------------------------------
STATE, ETC = W / 'state', W / 'etc'
CERTS = ETC / 'nginx' / 'certs'
for p in (STATE / 'root', STATE / 'backups', ETC / 'zigmon', ETC / 'mosquitto', ETC / 'nginx' / 'conf.d', CERTS,
          W / 'logs', W / 'www', W / 'body'):
    p.mkdir(parents=True, exist_ok=True)
DB = STATE / 'history.db'
(ETC / 'zigmon' / 'config.json').write_text(json.dumps({'db_file': str(DB)}))
# the broker reads the dashboard's files (its TLS listener on 8883)
(ETC / 'mosquitto' / 'mosquitto.conf').write_text('listener 1883\nlistener 8883\ncertfile %s\nkeyfile %s\n' % (
    CERTS / 'server.pem', CERTS / 'server.key'))
sh(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(CERTS / 'server.key'), '-out',
    str(CERTS / 'server.pem'), '-days', '400', '-subj', '/CN=%s' % NAME, '-addext', 'subjectAltName=DNS:%s' % NAME])
shutil.copy(CERTS / 'server.pem', CERTS / 'server.ca')
conf = (HERE / 'deploy' / 'nginx-zigmon.conf').read_text()
for a, b in (('/etc/nginx/certs/', str(CERTS) + '/'), ('/var/www/zigmon', str(W / 'www')),
             ('unix:/run/php-fpm/www.sock', 'unix:' + str(W / 'fpm.sock')),
             ('/var/log/nginx/', str(W / 'logs') + '/'),
             ('include        fastcgi_params;', 'include        /etc/nginx/fastcgi_params;'),
             ('listen      443 ssl http2;', 'listen      127.0.0.1:19633 ssl;'),
             ('listen      [::]:443 ssl http2;', ''), ('listen      80;', 'listen 127.0.0.1:19634;'),
             ('listen      [::]:80;', ''), ('mqtt.falco81.net', NAME)):
    conf = conf.replace(a, b)
NGINX_CONF = ETC / 'nginx' / 'conf.d' / 'zigmon.conf'
NGINX_CONF.write_text(conf)
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
                  ZIGMON_ROOT_RUN='%s -I %s' % (sys.executable, ROOT_HELPER))

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(DB), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'log_file': '', 'state_dir': str(STATE), 'acme': 0})
HANDED = []
ASKED_FRONT = []


def fake_front_ask(d, source=None, pem=None, policy=None, why=''):
    """The server in front as proxycert.py stands it in: what root is asked
    to put there, kept - no SSH."""
    if not zigmon.proxy_tls_on():
        raise ValueError('there is no server in front (Front server & router)')
    zigmon.proxy_tls_ssh(d)                          # the key way, as the real one asks
    ASKED_FRONT.append({'source': source, 'pem': dict(pem) if pem else None, 'why': why})
    return 'front%d' % len(ASKED_FRONT)


zigmon.proxy_tls_ask = fake_front_ask


class FakeAcmeCA(object):
    """The own ACME's CA, stood in for at its last step: the order gives a
    certificate of the test's CA for the name (everything after it -
    tls_sort, tls_put, root, the state - is the daemon's own)."""
    orders = []

    def __init__(self, d):
        pass

    def order(self, names, say, key_kind=None):
        cert, key = issue(names, 'ec' if str(key_kind or '').startswith('ec') else 'rsa')
        FakeAcmeCA.orders.append((names, key_kind))
        return key, cert + CA_PEM

    def close(self):
        pass


zigmon.Acme = FakeAcmeCA


def start_daemon():
    d = zigmon.Daemon()
    d.notify = lambda message, *a, **k: None
    real = d.root_apply

    def root_apply(pem=None, quiet=False):
        HANDED.append(bool(pem))
        return real(pem=pem, quiet=quiet)
    d.root_apply = root_apply
    api = zigmon.ApiServer(d)
    api.start()
    time.sleep(0.3)
    return d, api


d, api = start_daemon()


def call(path, body=None, session=None, timeout=300):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': '192.168.40.10'}
    if session:
        headers['X-Zigmon-Session'] = session
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                 data=None if body is None else json.dumps(body).encode(),
                                 method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'{}')
        except ValueError:
            return e.code, {}


d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)


def login():
    return (call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or '',
            call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or '')


S, S_OP = login()


def card(body=None, session=None):
    if body is None:
        return call('/api/acmepush', session=session or S)
    return call('/api/acmepush', dict(body), session=session or S)


def tls(body):
    return call('/api/tls', dict(body), session=S)


def look():
    return d.root_look(fresh=True).get('tls') or {}


# the relay, as php-fpm runs it: index.php with the daemon's port and token of this test
shutil.copytree(HERE / 'web', W / 'web')
api_php = (W / 'web' / 'zigmon-api.php').read_text()
api_php = api_php.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
api_php = api_php.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
(W / 'web' / 'zigmon-api.php').write_text(api_php)
php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, str(W / 'web' / 'index.php')], cwd=str(W / 'web'),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                       env=dict(os.environ, PHP_CLI_SERVER_WORKERS='4'))   # the page asks several at once
PROCS.append(php)
for _ in range(50):
    try:
        socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
        break
    except OSError:
        time.sleep(0.1)


def relay(op, raw=None, headers=None, method=None):
    """A request of acme's, as it reaches the page: (status, answer)."""
    url = 'http://127.0.0.1:%d/?api=acme-push-%s' % (PHP_PORT, op)
    h = {'Content-Type': 'application/json', 'User-Agent': 'acme/1.0.5 (acme push)'}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h, data=raw, method=method or ('GET' if raw is None else 'POST'))
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'{}')
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError) as e:
        return 0, {'error': str(e)}


class Acme(object):
    """The test playing acme: its key, its signed requests, its seal."""
    def __init__(self, seed, name='acme 1.0.5 on acme1'):
        self.seed, self.name = seed, name
        self.pub = zf('push_ed25519_public')(seed) if Z.get('push_ed25519_public') else b'\x00' * 32
        self.kid = hashlib.sha256(self.pub).hexdigest()[:16]
        self.text = 'acme-push-ed25519 %s acme@acme1' % b64(self.pub)
        self.app_id, self.enc = '', ''

    def hello(self):
        code, out = relay('hello')
        if code == 200 and out.get('app_id'):
            self.app_id, self.enc = out['app_id'], out['enc_key']
        return code, out

    def heads(self, op, raw, ts=None, nonce=None, version='1', kid=None, sign_over=None, app_id=None):
        ts = int(time.time()) if ts is None else ts
        nonce = nonce or os.urandom(16).hex()
        sig = ed_sign(self.seed, canonical(op, app_id or self.app_id, kid or self.kid, ts, nonce,
                                           raw if sign_over is None else sign_over))
        return {'X-Acme-Push-Version': version, 'X-Acme-Push-Key': kid or self.kid, 'X-Acme-Push-Time': str(ts),
                'X-Acme-Push-Nonce': nonce, 'X-Acme-Push-Signature': b64(sig)}

    def send(self, op, body, **kw):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        return relay(op, raw, self.heads(op, raw, **kw))

    def pair(self, code, nonce=None, bad_proof=False):
        nonce = nonce or os.urandom(16).hex()
        proof = zf('push_proof')(code if not bad_proof else 'ZZZZ-ZZZZ-ZZZZ-ZZZZ', 'pair', self.app_id, self.kid, nonce)
        got = self.send('pair', {'acme_key': self.text, 'acme_name': self.name, 'proof': proof}, nonce=nonce)
        return got + (nonce,)

    def seal(self, pem, fp):
        eph = os.urandom(32)
        x = zf('push_x25519')
        epk = x(eph)
        app = base64.b64decode(self.enc)
        aes = zf('push_hkdf')(x(eph, app), epk + app, b'acme-push/1 key_pem')
        n = os.urandom(12)
        aad = ('acme-push/1 key\n%s\n%s' % (self.app_id, fp)).encode()
        return {'alg': 'X25519-HKDF-SHA256-A256GCM', 'epk': b64(epk), 'nonce': b64(n),
                'ct': b64(zf('push_gcm_seal')(aes, n, pem.encode(), aad))}

    def body(self, cert, key, slots=('auto',), alt=None, seal_fp=None, **kw):
        fp = der_fp(cert)
        b = {'slots': list(slots), 'cert_pem': cert, 'chain_pem': CA_PEM, 'fingerprint': fp,
             'key': self.seal(key, seal_fp or fp), 'key_type': 'x', 'names': [], 'not_after': 0,
             'check_names': True, 'force': False}
        if alt:
            afp = der_fp(alt[0])
            b['alt'] = {'cert_pem': alt[0], 'chain_pem': CA_PEM, 'fingerprint': afp, 'key': self.seal(alt[1], afp),
                        'key_type': 'y'}
        b.update(kw)
        return b

    def install(self, *a, **kw):
        return self.send('install', self.body(*a, **kw))


def slots_of(out):
    return {s.get('id'): s for s in (out.get('slots') or [])}


def managed(acme_):
    code, out = acme_.send('inventory', {})
    return slots_of(out).get('node:' + HOST, {}).get('managed_by'), out


# ---- additive only: every certificate function there was -----------------------------------------
def regress(when):
    """Each existing way of putting a certificate in - and what goes with it -
    as an administrator does it on Certificates: it works, and the
    dashboard serves what it put in."""
    print('every certificate function there was, %s' % when)
    pfx_dir = W / ('pfx-%s' % when.split()[0])
    pfx_dir.mkdir(exist_ok=True)
    try:
        cert, key = issue([NAME])
        code, out = tls({'action': 'tls_upload', 'cert': cert + CA_PEM + key})
        check(code == 200 and file_fp(CERTS / 'server.pem') == der_fp(cert) and d.tls_conf().get('how') == 'uploaded',
              '%s: an upload of PEM: %s %s' % (when, code, out.get('error')))
        check(not zigmon.acme_care(d), '%s: after an upload the own ACME still renews it' % when)
        cert, key = issue([NAME], 'ec')
        (pfx_dir / 'c.pem').write_text(cert)
        (pfx_dir / 'k.pem').write_text(key)
        sh(['openssl', 'pkcs12', '-export', '-in', str(pfx_dir / 'c.pem'), '-inkey', str(pfx_dir / 'k.pem'),
            '-out', str(pfx_dir / 'x.pfx'), '-passout', 'pass:pfx pass'])
        code, out = tls({'action': 'tls_upload', 'pfx': b64((pfx_dir / 'x.pfx').read_bytes()), 'password': 'pfx pass'})
        check(code == 200 and file_fp(CERTS / 'server.pem') == der_fp(cert),
              '%s: an upload of a PFX: %s %s' % (when, code, out.get('error')))
        code, out = tls({'action': 'tls_csr', 'cn': NAME})
        csr = out.get('csr') or ''
        check(code == 200 and 'CERTIFICATE REQUEST' in csr, '%s: a request: %s %s' % (when, code, out.get('error')))
        (pfx_dir / 'r.csr').write_text(csr)
        sh(['openssl', 'ca', '-batch', '-config', str(CAD / 'ca.cnf'), '-cert', str(CAD / 'ca.pem'), '-keyfile',
            str(CAD / 'ca.key'), '-in', str(pfx_dir / 'r.csr'), '-out', str(pfx_dir / 'a.pem'), '-notext',
            '-days', '30'])
        answer = (pfx_dir / 'a.pem').read_text()
        code, out = tls({'action': 'tls_upload', 'cert': answer})
        check(code == 200 and file_fp(CERTS / 'server.pem') == der_fp(answer) and
              d.tls_conf().get('how') == 'answered to a request',
              '%s: the answer to the request: %s %s %s' % (when, code, out.get('error'), d.tls_conf().get('how')))
        code, out = tls({'action': 'tls_selfsigned', 'cn': NAME, 'days': 30})
        check(code == 200 and d.tls_conf().get('how') == 'self-signed, made here' and
              (look().get('info') or {}).get('self_signed'), '%s: self-signed: %s %s' % (when, code, out.get('error')))
        code, out = tls({'action': 'tls_policy', 'preset': 'modern'})
        check(code == 200 and look().get('protocols') == ['TLSv1.3'], '%s: the TLS settings: %s %s %r'
              % (when, code, out.get('error'), look().get('protocols')))
        tls({'action': 'tls_policy', 'preset': 'standard'})
        code, out = tls({'action': 'tls_get', 'format': 'pem_cert'})
        check(code == 200 and der_fp(out.get('text') or '') == file_fp(CERTS / 'server.pem'),
              '%s: the download without the key: %s %s' % (when, code, out.get('error')))
        code, out = tls({'action': 'tls_export', 'format': 'pem_key'})
        st = d.root_read('status.json')
        check(code == 200 and st.get('kind') == 'tls_export' and st.get('state') == 'done',
              '%s: the export with the key: %s %s %r' % (when, code, out.get('error'), st.get('said')))
        # the own ACME: ordered, and renewed
        code, out = call('/api/acme', {'action': 'care', 'on': True}, session=S)
        check(code == 200 and zigmon.acme_care(d), '%s: Look after it: %s %s' % (when, code, out.get('error')))
        for n in (1, 2):
            try:
                zigmon.acme_order(d, NAME, 'test')
                ok = d.tls_conf().get('how') == 'ACME' and look().get('dual')
            except Exception as e:                       # noqa: BLE001
                ok = False
                print('   ', e)
            check(ok, '%s: the own ACME\'s %s' % (when, 'order' if n == 1 else 'renewal'))
        # the server in front: the same certificate, and one of its own
        zigmon.CONFIG.update(proxy_host='proxy.house.example', proxy_auth='key')
        d.store.set_meta('proxy_key', '-----BEGIN OPENSSH PRIVATE KEY-----\nstand-in\n-----END OPENSSH PRIVATE KEY-----\n')
        d._proxy_tls_look = {'at': int(time.time()), 'ok': True, 'info': {}}
        del ASKED_FRONT[:]
        out = zigmon.proxy_tls_post(d, 'proxy_follow', {'on': True}, 'test')
        check(ASKED_FRONT and ASKED_FRONT[-1]['source'] == 'here', '%s: the front following: %r' % (when, out))
        try:
            zigmon.proxy_tls_post(d, 'tls_upload', {'cert': cert + key}, 'test')
            check(False, '%s: the front took one of its own while following' % when)
        except ValueError:
            pass
        zigmon.proxy_tls_post(d, 'proxy_follow', {'on': False}, 'test')
        own, okey = issue(['home.house.example'])
        zigmon.proxy_tls_post(d, 'tls_upload', {'cert': own + okey}, 'test')
        check(ASKED_FRONT[-1]['pem'] and der_fp(ASKED_FRONT[-1]['pem']['cert']) == der_fp(own) and
              zigmon.proxy_tls_conf(d).get('how') == 'uploaded', '%s: the front\'s own upload' % when)
        zigmon.CONFIG.update(proxy_host='')
        # a backup of the database and its restore
        b = d.db_backup_now('-check')
        had = d.store.get_meta('tls')
        d.store.set_meta('tls', '{}')
        d.db_restore(b['file'])
        check(d.store.get_meta('tls') == had, '%s: a backup and its restore lost the TLS settings' % when)
    except Exception as e:                               # noqa: BLE001
        check(False, '%s: %s: %s' % (when, type(e).__name__, e))


try:
    regress('with acme push off')

    # ---- off -------------------------------------------------------------------------------------
    print('hello, off')
    A = Acme(bytes(range(32)))
    code, out = A.hello()
    check(code == 200 and out.get('on') is False and out.get('app') == 'zigmon' and out.get('protocol') == [1] and
          set(out) == {'ok', 'protocol', 'app', 'version', 'on'}, 'hello off says more than it should: %s %r' % (code, out))
    code, out = A.send('inventory', {}, app_id='0' * 32)
    check(code == 403 and out.get('code') == 'off', 'inventory with push off: %s %r' % (code, out))
    code, out = card({'action': 'code'})
    check(code == 400, 'a pairing code was made with push off: %s' % code)
    code, out = card(session=S_OP)
    check(code == 403, 'an operator reads the card: %s' % code)
    check(d.store.get_meta('acme_push:app_id') in (None, ''), 'push off made keys already')

    # ---- on --------------------------------------------------------------------------------------
    d.save_config_overrides({'cert_push': 1})
    code, out = A.hello()
    check(code == 200 and out.get('on') is True and re.match(r'^[0-9a-f]{32}$', out.get('app_id') or '') and
          len(base64.b64decode(out.get('enc_key') or '')) == 32 and out.get('enc_alg') == 'X25519-HKDF-SHA256-A256GCM'
          and 'node:' + HOST in (out.get('slots') or []) and out.get('paired') == 0 and out.get('pairing') is False,
          'hello on: %s %r' % (code, out))
    app_id = A.app_id
    code, out = A.send('inventory', {})
    check(code == 401 and out.get('code') == 'not_paired', 'inventory before pairing: %s %r' % (code, out))

    print('pairing by the code')
    code, out = card({'action': 'code'})
    pc = out.get('code') or ''
    check(code == 200 and re.match(r'^[A-HJ-NP-Z2-9]{4}(-[A-HJ-NP-Z2-9]{4}){3}$', pc) and
          (out.get('pairing') or {}).get('until', 0) > time.time() + 800, 'Pair with an acme: %s %r' % (code, out))
    check(pc not in json.dumps(card()[1]), 'the code is shown again')
    check(A.hello()[1].get('pairing') is True, 'hello does not say a code waits')
    for n in range(1, 6):
        code, out, _n = A.pair(pc, bad_proof=True)
        check(code == 403 and out.get('code') == 'bad_code', 'a wrong proof (%d): %s %r' % (n, code, out))
        pg = card()[1].get('pairing') or {}
        left = pg.get('tries_left')
        check(left == (5 - n if n < 5 else None), 'tries left after %d wrong: %r' % (n, left))
        # the wrong tries so far, which the card says as ai's does (5.40.2)
        check(n == 5 or pg.get('tries') == n, 'the wrong tries so far after %d wrong: %r' % (n, pg.get('tries')))
    code, out, _n = A.pair(pc)
    check(code == 403 and out.get('code') == 'pairing_closed', 'the code lived on after five wrong: %s %r' % (code, out))
    code, out = card({'action': 'code'})
    pc = out.get('code') or ''
    raw = json.loads(d.store.get_meta('acme_push:code') or '{}')
    raw['until'] = int(time.time()) - 1
    d.store.set_meta('acme_push:code', json.dumps(raw))
    code, out, _n = A.pair(pc)
    check(code == 403 and out.get('code') == 'pairing_closed', 'a code run out paired: %s %r' % (code, out))
    pc = card({'action': 'code'})[1].get('code') or ''
    code, out = card({'action': 'code_drop'})
    check(code == 200 and not out.get('pairing'), 'Take it back: %s %r' % (code, out))
    code, out, _n = A.pair(pc)
    check(code == 403 and out.get('code') == 'pairing_closed', 'a code taken back paired: %s' % code)
    pc = card({'action': 'code'})[1].get('code') or ''
    code, out, nonce = A.pair(pc)
    check(code == 200 and out.get('app_id') == app_id and out.get('enc_key') == A.enc and out.get('key_id') == A.kid and
          out.get('confirm') == zf('push_proof')(pc, 'paired', app_id, A.kid, nonce, A.enc),
          'pairing with the code: %s %r' % (code, out))
    view = card()[1]
    check([k.get('key_id') for k in view.get('keys') or []] == [A.kid] and not view.get('pairing') and
          (view['keys'][0].get('name') == 'acme 1.0.5 on acme1'), 'the card after pairing: %r' % view.get('keys'))
    code, out, _n = A.pair(pc)
    check(code == 403 and out.get('code') == 'pairing_closed', 'the code paired twice: %s' % code)

    print('pairing by acme\'s key pasted')
    B = Acme(bytes(range(100, 132)), name='acme two')
    B.app_id, B.enc = A.app_id, A.enc
    code, out = card({'action': 'paste', 'key': 'acme-push-ed25519 nonsense'})
    check(code == 400, 'a key that is not one was taken: %s' % code)
    code, out = card({'action': 'paste', 'key': B.text, 'name': ''})
    check(code == 200 and B.kid in [k.get('key_id') for k in out.get('keys') or []], 'the key pasted: %s %r' % (code, out))
    code, out = B.send('inventory', {})
    check(code == 200 and out.get('app_id') == app_id, 'inventory by the pasted key: %s %r' % (code, out))

    # ---- the signature, refused in every way -------------------------------------------------------
    print('the signature')
    raw = b'{}'
    good = A.heads('inventory', raw)
    for drop in ('X-Acme-Push-Key', 'X-Acme-Push-Time', 'X-Acme-Push-Nonce', 'X-Acme-Push-Signature'):
        h = dict(good)
        h.pop(drop)
        code, out = relay('inventory', raw, h)
        check(code == 401 and out.get('code') == 'unsigned', 'without %s: %s %r' % (drop, code, out))
    h = dict(good, **{'X-Acme-Push-Nonce': 'short'})
    check(relay('inventory', raw, h)[1].get('code') == 'unsigned', 'a nonce of the wrong shape')
    stranger = Acme(bytes(range(200, 232)))
    stranger.app_id = app_id
    code, out = stranger.send('inventory', {})
    check(code == 401 and out.get('code') == 'unknown_key', 'an unknown key: %s %r' % (code, out))
    code, out = A.send('inventory', {}, ts=int(time.time()) - 400)
    check(code == 401 and out.get('code') == 'stale' and '400' in (out.get('error') or '')[:60] or
          code == 401 and out.get('code') == 'stale', 'a stale request: %s %r' % (code, out))
    code, out = A.send('inventory', {}, sign_over=b'{"other": 1}')
    check(code == 401 and out.get('code') == 'bad_signature', 'a bad signature: %s %r' % (code, out))
    code, out = A.send('inventory', {}, app_id='f' * 32)
    check(code == 401 and out.get('code') == 'bad_signature', 'signed for another application: %s %r' % (code, out))
    h = A.heads('install', raw)                   # signed as another request
    code, out = relay('inventory', raw, h)
    check(code == 401 and out.get('code') == 'bad_signature', 'install replayed as inventory: %s' % code)
    h = A.heads('inventory', raw)
    check(relay('inventory', raw, h)[0] == 200, 'the first of a nonce')
    code, out = relay('inventory', raw, h)
    check(code == 401 and out.get('code') == 'replay', 'a replay: %s %r' % (code, out))
    REPLAYED = h
    code, out = A.send('inventory', {}, version='2')
    check(code == 400 and out.get('code') == 'version', 'version 2: %s %r' % (code, out))
    big = b'{"x": "' + b'a' * (1024 * 1024) + b'"}'
    code, out = relay('install', big, A.heads('install', big))
    check(code == 413 and out.get('code') == 'too_big', 'over 1 MiB: %s %r' % (code, out))
    code, out = A.send('inventory', b'[1, NaN]')
    check(code == 400 and out.get('code') == 'bad_request', 'a body that is not an object: %s %r' % (code, out))
    code, out = relay('inventory', None, method='GET')
    check(code == 405 and out.get('code') == 'bad_request', 'inventory by GET: %s' % code)

    print('the nonces, across a restart')
    api.stop()
    d, api = start_daemon()
    S, S_OP = login()
    code, out = relay('inventory', raw, REPLAYED)
    check(code == 401 and out.get('code') == 'replay', 'a nonce forgotten by a restart: %s %r' % (code, out))
    seen = json.loads(d.store.get_meta('acme_push:nonces') or '{}')
    check('%s:%s' % (A.kid, REPLAYED['X-Acme-Push-Nonce']) in seen and len(seen) <= 20000,
          'the nonces are not in the database')

    # ---- the slots ----------------------------------------------------------------------------------
    print('the inventory')
    code, out = A.send('inventory', {})
    sl = slots_of(out)
    node = sl.get('node:' + HOST) or {}
    now_fp = file_fp(CERTS / 'server.pem')
    check(code == 200 and out.get('app') == 'zigmon' and out.get('cluster', {}).get('nodes') == [HOST] and
          out.get('other_names') is False, 'inventory: %s %r' % (code, out))
    check(node.get('kind') == 'node' and node.get('node') == HOST and node.get('names') == [NAME] and
          node.get('key_types') == ['ec', 'rsa'] and node.get('dual') is True and node.get('installable') is True and
          (node.get('current') or {}).get('fingerprint') == now_fp and (node.get('current') or {}).get('alt') and
          node.get('managed_by') == 'own-acme', 'the dashboard\'s slot: %r' % node)
    br = sl.get('broker') or {}
    check(br.get('managed_by') == 'follows:node:' + HOST and br.get('installable') is False and br.get('why_not') and
          br.get('names') == [NAME], 'the broker\'s slot: %r' % br)
    check('front' not in sl, 'a front slot with no server in front')
    zigmon.CONFIG.update(proxy_host='proxy.house.example', proxy_auth='key')
    d.store.set_meta('proxy_key', '-----BEGIN OPENSSH PRIVATE KEY-----\nstand-in\n-----END OPENSSH PRIVATE KEY-----\n')
    FRONT_NOW, _k = issue(['home.house.example'])
    d._proxy_tls_look = {'at': int(time.time()), 'ok': True, 'info': zigmon.cert_info_pem(d, FRONT_NOW)}
    zigmon.proxy_tls_post(d, 'proxy_follow', {'on': True}, 'test')
    fr = slots_of(A.send('inventory', {})[1]).get('front') or {}
    check(fr.get('kind') == 'front' and fr.get('managed_by') == 'follows:node:' + HOST and fr.get('names') == [NAME]
          and fr.get('installable') is False and 'proxy.house.example' in fr.get('title', ''),
          'the front following: %r' % fr)
    zigmon.proxy_tls_post(d, 'proxy_follow', {'on': False}, 'test')
    c = zigmon.proxy_tls_conf(d)
    c['name'] = 'home.house.example'
    zigmon.proxy_tls_save(d, c)
    d._proxy_tls_look = {'at': int(time.time()), 'ok': True, 'info': zigmon.cert_info_pem(d, FRONT_NOW)}
    fr = slots_of(A.send('inventory', {})[1]).get('front') or {}
    check(fr.get('names') == ['home.house.example'] and fr.get('managed_by') == 'manual' and fr.get('installable')
          is True and (fr.get('current') or {}).get('fingerprint') == der_fp(FRONT_NOW), 'the front with its own: %r' % fr)
    zigmon.CONFIG['proxy_auth'] = 'password'
    fr = slots_of(A.send('inventory', {})[1]).get('front') or {}
    check(fr.get('installable') is False and 'password' in (fr.get('why_not') or ''), 'the front by password: %r' % fr)
    zigmon.CONFIG['proxy_auth'] = 'key'

    # ---- install ----------------------------------------------------------------------------------
    print('install')
    events_before = len(d.store.events(limit=1000, text='acme push'))
    rsa, rsa_key = issue([NAME])
    n0 = len(HANDED)
    code, out = A.install(rsa, rsa_key)
    row = (out.get('installed') or [{}])[0]
    check(code == 200 and row.get('slot') == 'node:' + HOST and row.get('state') == 'installed' and
          row.get('fingerprint') == der_fp(rsa) and file_fp(CERTS / 'server.pem') == der_fp(rsa),
          'one certificate, auto: %s %r' % (code, out))
    check(d.tls_conf().get('how') == 'acme push: acme 1.0.5 on acme1', 'how: %r' % d.tls_conf().get('how'))
    check(not zigmon.acme_care(d), 'the own ACME still looks after it after a push')
    check(managed(A)[0] == 'acme-push', 'managed_by after a push')
    check(len(HANDED) == n0 + 1, 'root was not asked once')
    code, out = A.install(rsa, rsa_key)
    check(code == 200 and (out.get('installed') or [{}])[0].get('state') == 'already' and len(HANDED) == n0 + 1,
          'the same again was not already, or root was asked: %s %r %d' % (code, out, len(HANDED) - n0))
    code, out = A.install(rsa, rsa_key, force=True)
    check(code == 200 and (out.get('installed') or [{}])[0].get('state') == 'installed' and len(HANDED) == n0 + 2,
          'force: %s %r' % (code, out))
    ec, ec_key = issue([NAME], 'ec')
    rsa2, rsa2_key = issue([NAME])
    code, out = A.install(ec, ec_key, slots=['node:' + HOST], alt=(rsa2, rsa2_key))
    check(code == 200 and file_fp(CERTS / 'server.pem') == der_fp(rsa2) and
          file_fp(CERTS / 'server-ecdsa.pem') == der_fp(ec) and
          len(re.findall(r'(?m)^\s*ssl_certificate\s', NGINX_CONF.read_text())) == 2,
          'two certificates (the RSA one first, the broker\'s file): %s %r' % (code, out))
    cur = (slots_of(A.send('inventory', {})[1]).get('node:' + HOST) or {}).get('current') or {}
    check(cur.get('fingerprint') == der_fp(rsa2) and (cur.get('alt') or {}).get('fingerprint') == der_fp(ec) and
          (cur.get('alt') or {}).get('key_type') == 'ec-256' and cur.get('key_type') == 'rsa-2048',
          'current after two: %r' % cur)
    n1 = len(HANDED)
    code, out = A.install(ec, ec_key, slots=['this'], alt=(rsa2, rsa2_key))
    check(code == 200 and (out.get('installed') or [{}])[0].get('state') == 'already' and len(HANDED) == n1,
          'two again was not already: %s %r' % (code, out))
    code, out = A.install(ec, ec_key, slots=[HOST], alt=(ec, ec_key))
    check(code == 400 and out.get('code') == 'bad_request', 'a twin of the same key type: %s %r' % (code, out))
    wild, wild_key = issue(['*.house.example'], 'ec')
    code, out = A.install(wild, wild_key)
    # *.house.example holds the dashboard's name and the front's own: auto takes both
    check(code == 200 and [r.get('slot') for r in out.get('installed') or []] == ['node:' + HOST, 'front'] and
          file_fp(CERTS / 'server.pem') == der_fp(wild) and der_fp(ASKED_FRONT[-1]['pem']['cert']) == der_fp(wild),
          'a wildcard to auto: %s %r' % (code, out))
    other, other_key = issue([NAME])
    code, out = A.install(rsa, other_key)
    check(code == 422 and out.get('code') == 'key_mismatch', 'a key not of the certificate: %s %r' % (code, out))
    code, out = A.install(rsa, rsa_key, seal_fp=der_fp(other))
    check(code == 400 and out.get('code') == 'bad_key', 'a key sealed for another certificate: %s %r' % (code, out))
    b = A.body(rsa, rsa_key)
    b['key']['ct'] = b64(b'\x00' * 40)
    code, out = A.send('install', b)
    check(code == 400 and out.get('code') == 'bad_key', 'a seal that does not open: %s %r' % (code, out))
    b = A.body(rsa, rsa_key, fingerprint='0' * 64)
    code, out = A.send('install', b)
    check(code == 400 and out.get('code') == 'bad_request', 'a fingerprint not the certificate\'s: %s %r' % (code, out))
    old, old_key = issue([NAME], start='20200101000000Z', end='20210101000000Z')
    code, out = A.install(old, old_key)
    check(code == 422 and out.get('code') == 'expired', 'one run out: %s %r' % (code, out))
    later, later_key = issue([NAME], start=time.strftime('%Y%m%d%H%M%SZ', time.gmtime(time.time() + 86400 * 5)))
    code, out = A.install(later, later_key)
    check(code == 422 and out.get('code') == 'not_yet_valid', 'one not valid yet: %s %r' % (code, out))
    code, out = A.install(other.replace('MI', 'XX', 3), other_key)
    check(code in (400, 422) and out.get('code') in ('bad_cert', 'bad_request'), 'a certificate that does not read: %s %r'
          % (code, out))
    stray, stray_key = issue(['other.example'])
    code, out = A.install(stray, stray_key, slots=['node:' + HOST])
    check(code == 422 and out.get('code') == 'names', 'another name to the dashboard: %s %r' % (code, out))
    code, out = A.install(stray, stray_key)
    check(code == 422 and out.get('code') == 'names', 'another name to auto: %s %r' % (code, out))
    code, out = A.install(stray, stray_key, slots=['node:' + HOST], check_names=False)
    check(code == 422 and out.get('code') == 'names', 'check_names false taken with other names off: %s' % code)
    d.save_config_overrides({'cert_push_other_names': 1})
    code, out = A.install(stray, stray_key, slots=['node:' + HOST], check_names=False)
    check(code == 200 and file_fp(CERTS / 'server.pem') == der_fp(stray), 'other names allowed: %s %r' % (code, out))
    check(A.send('inventory', {})[1].get('other_names') is True, 'inventory does not say other names')
    d.save_config_overrides({'cert_push_other_names': 0})
    code, out = A.install(rsa, rsa_key, slots=['vip'])
    check(code == 404 and out.get('code') == 'no_slot', 'no such slot: %s %r' % (code, out))
    code, out = A.install(rsa, rsa_key, slots=['broker'])
    check(code == 409 and out.get('code') == 'not_installable', 'the broker: %s %r' % (code, out))
    zigmon.proxy_tls_post(d, 'proxy_follow', {'on': True}, 'test')
    code, out = A.install(rsa, rsa_key, slots=['front'])
    check(code == 409 and out.get('code') == 'not_installable' and 'node:' + HOST in (out.get('error') or ''),
          'the front following: %s %r' % (code, out))
    zigmon.proxy_tls_post(d, 'proxy_follow', {'on': False}, 'test')
    home, home_key = issue(['home.house.example'])
    del ASKED_FRONT[:]
    code, out = A.install(home, home_key, slots=['front'])
    check(code == 200 and ASKED_FRONT and (ASKED_FRONT[-1]['pem'] or {}).get('key', '').strip() and
          der_fp(ASKED_FRONT[-1]['pem']['cert']) == der_fp(home) and
          zigmon.proxy_tls_conf(d).get('how') == 'acme push: acme 1.0.5 on acme1',
          'the front with its own: %s %r %r' % (code, out, zigmon.proxy_tls_conf(d).get('how')))
    d._proxy_tls_look = {'at': int(time.time()), 'ok': True, 'info': zigmon.cert_info_pem(d, home)}
    code, out = A.install(home, home_key, slots=['front'])
    check(code == 200 and (out.get('installed') or [{}])[0].get('state') == 'already' and len(ASKED_FRONT) == 1,
          'the front again: %s %r' % (code, out))
    check(slots_of(A.send('inventory', {})[1]).get('front', {}).get('managed_by') == 'acme-push', 'the front pushed')
    zigmon.CONFIG['proxy_host'] = ''
    evs = d.store.events(limit=1000, text='acme push')
    text = json.dumps(evs)
    check(len(evs) > events_before and 'PRIVATE KEY' not in text and 'BEGIN CERTIFICATE' not in text and
          A.kid in text, 'the events of the installs: %d, keys in them: %s' % (len(evs), 'PRIVATE KEY' in text))
    words = ' '.join(str(e) for e in evs)
    check('paired with acme 1.0.5 on acme1' in words and 'wrong code' in words and 'pasted' in words,
          'the events of the pairings')
    check('PRIVATE KEY' not in json.dumps(d.store.events(limit=2000)), 'a private key went into the events')

    # ---- after a push: the other ways take it back -------------------------------------------------
    print('after a push')
    A.install(rsa, rsa_key, force=True)
    cert, key = issue([NAME])
    tls({'action': 'tls_upload', 'cert': cert + key})
    check(managed(A)[0] == 'manual' and file_fp(CERTS / 'server.pem') == der_fp(cert), 'an upload after a push')
    A.install(rsa, rsa_key, force=True)
    call('/api/acme', {'action': 'care', 'on': True}, session=S)
    try:
        zigmon.acme_order(d, NAME, 'test')
    except Exception as e:                               # noqa: BLE001
        print('   ', e)
    check(managed(A)[0] == 'own-acme' and zigmon.acme_care(d), 'Look after it and the own ACME after a push')
    A.install(rsa, rsa_key)
    check(managed(A)[0] == 'acme-push', 'a push after the own ACME')

    regress('with acme push on and paired')
    check(card()[1].get('keys') and A.send('inventory', {})[0] == 200, 'the pairing did not live through it all')

    # ---- forgetting, switching off - no lock-in ---------------------------------------------------
    print('forgetting and switching off')
    code, out = card({'action': 'forget', 'key_id': B.kid})
    check(code == 200 and B.kid not in [k.get('key_id') for k in out.get('keys') or []], 'Forget it: %s' % code)
    code, out = B.send('inventory', {})
    check(code == 401 and out.get('code') == 'unknown_key', 'a forgotten key is taken: %s %r' % (code, out))
    check('forgotten' in json.dumps(d.store.events(limit=200, text='acme push')), 'no event of forgetting')
    A.install(rsa, rsa_key, force=True)
    there = file_fp(CERTS / 'server.pem')
    b = d.db_backup_now('-push')
    d.save_config_overrides({'cert_push': 0})
    code, out = A.install(wild, wild_key)
    check(code == 403 and out.get('code') == 'off', 'switched off, an install: %s %r' % (code, out))
    check(file_fp(CERTS / 'server.pem') == there and d.tls_conf().get('how', '').startswith('acme push'),
          'switched off, the certificate did not stay')
    check(card()[1].get('keys'), 'switched off, the pairings went')
    code, out = tls({'action': 'tls_selfsigned', 'cn': NAME, 'days': 10})
    check(code == 200, 'switched off, a self-signed one: %s' % code)
    d.save_config_overrides({'cert_push': 1})
    check(A.hello()[1].get('app_id') == app_id and A.send('inventory', {})[0] == 200, 'switched on again')
    # the backup holds the push state: the pairing, the keys and the switch
    card({'action': 'forget', 'key_id': A.kid})
    d.save_config_overrides({'cert_push': 0})
    d.db_restore(b['file'])
    check(A.kid in [k.get('key_id') for k in card()[1].get('keys') or []] and zigmon.push_on() and
          d.store.get_meta('acme_push:app_id') == app_id, 'the restore did not bring the pairing back')
    check(A.send('inventory', {})[0] == 200, 'after the restore acme is not taken')
    ex = d.export_settings()
    check(json.dumps(ex).find('cert_push') >= 0, 'the settings export does not hold cert_push')

    # ---- the command line ---------------------------------------------------------------------------
    print('the command line')
    pal = zigmon.Palette(False) if hasattr(zigmon, 'Palette') else None
    try:
        import io
        import contextlib
        buf = io.StringIO()
        old_call = zigmon.api_call
        zigmon.api_call = lambda path, **kw: call(path, session=S)
        try:
            with contextlib.redirect_stdout(buf):
                rc = zf('cmd_acme_push')(type('A', (), {'json': False})(), pal or zigmon.Pal(False))
        finally:
            zigmon.api_call = old_call
        check(rc == 0 and 'node:' + HOST in buf.getvalue() and A.kid in buf.getvalue(),
              'zigmon --acme-push: %r' % buf.getvalue()[:300])
    except Exception as e:                               # noqa: BLE001
        check(False, 'zigmon --acme-push: %s: %s' % (type(e).__name__, e))
    helped = zigmon.build_parser().parse_args(['--acme-push']) if hasattr(zigmon, 'build_parser') else None
    check(helped is None or getattr(helped, 'acme_push', False), '--acme-push is not a flag')

    # ---- the relay ----------------------------------------------------------------------------------
    print('the relay')
    page = (HERE / 'web' / 'index.php').read_text()
    at = page.find("preg_match('/^acme-push-(hello|pair|inventory|install)$/'")
    check(0 < at < page.find('// ---- cross-site requests') < page.find("if (isset($_GET['api'])) {"),
          'the acme-push block is not before the sign-in and the cross-site check')
    allowed = page[page.index("if (in_array($what, ['scenes-save'"):]
    allowed = allowed[:allowed.index('], true)')]
    check("'acmepush-do'" in allowed and "'acmepush-do' => '/api/acmepush'" in page and
          "zigmon_relay('/api/acmepush')" in page, 'the card\'s roads are not in the relay')
    check('/api/acmepush' in zigmon.ApiHandler.ALWAYS_LOCKED, 'the card is not an administrator\'s read')
    code, out = call('/api/acmepush', {'action': 'view'}, session=S_OP)
    check(code == 403, 'an operator uses the card: %s' % code)
    req = urllib.request.Request('http://127.0.0.1:%d/api/acme-push/inventory' % API_PORT, method='POST',
                                 data=b'{"body": "e30=", "headers": {}}', headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req, timeout=10)
        st = 200
    except urllib.error.HTTPError as e:
        st = e.code
    check(st == 403, 'the daemon\'s road answered without the API token: %s' % st)

    # ---- the card in Chromium -----------------------------------------------------------------------
    print('the card')
    d.save_config_overrides({'cert_push': 1})
    root = sh(['npm', 'root', '-g']).stdout.strip()
    js = r'''
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({viewport: {width: 1400, height: 1000}});
  await ctx.addCookies([{name: 'zigmon_session', value: %(s)s, url: 'http://127.0.0.1:%(port)d/'}]);
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.goto('http://127.0.0.1:%(port)d/#control/sys-certs');
  await p.waitForTimeout(2500);
  try { await p.evaluate(() => showControlSection('sys-certs')); } catch (e) {}
  try { await p.waitForSelector('#push-box', {timeout: 15000}); } catch (e) {
    await p.screenshot({path: %(shot)s + '.fail.png'});
    const why = await p.evaluate(() => ({tab: STATE.tab, sec: CONTROL_SEC, admin: isAdmin(), who: LOCK.who,
      host: ($('acme-push') || {}).innerHTML, shown: !!($('push-card') && $('push-card').offsetParent)}));
    throw new Error('no card: ' + JSON.stringify(why) + ' ' + errors.join(' | '));
  }
  const r = {};
  r.title = await p.textContent('#push-card h2');
  r.sw = await p.evaluate(() => document.getElementById('set-host-sys-certs').textContent);
  r.sw_on = await p.evaluate(() => { const b = document.querySelector('#set-host-sys-certs input[data-k="cert_push"]');
                                     return b ? b.checked : null; });
  /* Take certificates of other names: switched on here and saved with the card's own Save settings */
  await p.evaluate(() => { const b = document.querySelector('#set-host-sys-certs input[data-k="cert_push_other_names"]');
                           b.click(); });
  await p.click('#push-card .set-save-alt');
  await p.waitForTimeout(2000);
  r.state = await p.textContent('#push-state');
  r.slots = await p.evaluate(() => Array.from(document.querySelectorAll('#push-box tr[data-slot]')).map(t => t.dataset.slot));
  r.keys = await p.evaluate(() => Array.from(document.querySelectorAll('#push-box .push-forget')).map(t => t.dataset.key));
  r.last = await p.textContent('#push-last');
  r.tiles = await p.evaluate(() => Array.from(document.querySelectorAll('#push-box .fact .k')).map(t => t.textContent));
  r.heads = await p.evaluate(() => Array.from(document.querySelectorAll('#push-box h4')).map(t => t.textContent));
  await p.click('#push-pair');
  await p.waitForSelector('#push-code', {timeout: 10000});
  r.code = await p.textContent('#push-code');
  await p.screenshot({path: %(shot)s, fullPage: false});
  await p.click('#zmodal-x');
  await p.waitForTimeout(1500);
  r.waiting = await p.evaluate(() => !!document.getElementById('push-waiting'));
  await p.click('#push-drop');
  await p.waitForTimeout(1500);
  r.after_drop = await p.evaluate(() => !!document.getElementById('push-waiting'));
  await p.click('#push-paste');
  await p.waitForSelector('#push-key');
  await p.fill('#push-key', %(key)s);
  await p.fill('#push-key-name', 'acme three');
  await p.click('#zmodal-foot .btn.primary');
  await p.waitForTimeout(1500);
  r.keys2 = await p.evaluate(() => Array.from(document.querySelectorAll('#push-box .push-forget')).map(t => t.dataset.key));
  const card = await p.$('#push-card');
  await card.screenshot({path: %(shot2)s});
  r.errors = errors;
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
    C = Acme(bytes(range(150, 182)))
    (W / 'card.js').write_text(js % {'s': json.dumps(S), 'port': PHP_PORT, 'key': json.dumps(C.text),
                                     'shot': json.dumps(str(W / 'card.png')), 'shot2': json.dumps(str(W / 'card2.png'))})
    got = sh(['node', str(W / 'card.js')], timeout=180, env=dict(os.environ, NODE_PATH=root))
    try:
        r = json.loads(got.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        r = {'error': (got.stdout + got.stderr)[-300:]}
    if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
        print('  SKIPPED (no browser here): %s' % r['error'][:200])
    else:
        check(not r.get('error'), 'the card in Chromium: %s' % r.get('error'))
        check((r.get('title') or '').startswith('Certificates from acme'), 'the card\'s title: %r' % r.get('title'))
        check(r.get('sw_on') is True, 'the switch Take certificates from acme is not on: %r' % r.get('sw_on'))
        check(zigmon.push_other_names(), 'Take certificates of other names, switched on the card, was not saved')
        check('Take certificates from acme' in (r.get('sw') or '') and 'Take certificates of other names' in (r.get('sw') or ''),
              'the switches are not on the card: %r' % (r.get('sw') or '')[:200])
        check((r.get('state') or '') == 'on - paired', 'the card\'s tag does not say on - paired: %r' % r.get('state'))
        check(r.get('tiles') == ['The address for acme', 'This server\u2019s id', 'Its sealing key (X25519)'],
              'the card\'s tiles (as ai 1.0.60): %r' % r.get('tiles'))
        check(r.get('heads') == ['Paired with', 'What acme sees here'], 'the card\'s parts (as ai 1.0.60): %r' % r.get('heads'))
        check(r.get('slots') == ['node:' + HOST, 'broker'], 'the card\'s slots: %r' % r.get('slots'))
        check(r.get('keys') == [A.kid], 'the card\'s paired acmes: %r' % r.get('keys'))
        check('acme 1.0.5 on acme1' in (r.get('last') or ''), 'the last push: %r' % r.get('last'))
        check(re.match(r'^[A-HJ-NP-Z2-9]{4}(-[A-HJ-NP-Z2-9]{4}){3}$', r.get('code') or ''), 'the code: %r' % r.get('code'))
        check(r.get('waiting') is True and r.get('after_drop') is False, 'the code waiting, and taken back: %r' % r)
        check(r.get('keys2') == [A.kid, C.kid], 'the key pasted on the card: %r' % r.get('keys2'))
        check(not r.get('errors'), 'the page threw: %r' % r.get('errors'))
        if os.environ.get('SHOT'):
            shutil.copy(W / 'card2.png', os.environ['SHOT'])
finally:
    for p in PROCS:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    try:
        api.stop()
    except Exception:                                    # noqa: BLE001
        pass

if bad:
    print('\n%d problem(s)' % len(bad))
    raise SystemExit(1)
shutil.rmtree(str(W), ignore_errors=True)
print('\nCertificates from acme (acme push): every check passed')
