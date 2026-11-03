#!/usr/bin/env python3
"""5.42: two certificates side by side - an RSA and an EC one of the same
names, as Automatic certificates' "Both" puts them in - uploaded and
downloaded by hand, on all three cards of Certificates. Fails on 5.41.1
(an upload took the first key and its certificate, the second was dropped;
a download handed over the RSA one only).

  * a CA of the test's own (openssl): one root, an RSA intermediate and an
    EC one (as Let's Encrypt's R- and E-series), an RSA 2048 and an EC P-384
    leaf of the same names;
  * this machine (root run for real over a folder laid out as /etc, as
    test/acme.py does it): one PEM with both pairs in a shuffled order, their
    keys in the old RSA / EC forms - nginx gets two ssl_certificate pairs,
    the RSA one first (the broker's files stay the RSA one's), each file the
    right certificate with its own chain, each key 0600 and its
    certificate's, the trusted chain both intermediates; the card says
    "And: EC 384"; two PFX files, and a PFX with a PEM, the same; a PFX
    holding both keys is not tried: openssl pkcs12 -export takes one
    -inkey, so openssl cannot make one; names that differ and two RSA keys
    refused with words that say so, nothing put in; one pair after two puts
    one in, the second taken out of nginx;
  * the server in front and ntfy there (root over the stand-in SSH, as
    test/proxycert.py and test/proxyntfy.py do it): both pairs in the
    block(s) of each and nowhere else, nginx -t saying no leaves every file
    as it was; the card reads the second one;
  * downloads, RSA and EC, every format (PEM with and without chain,
    certificate only, CA chain, DER, PFX, legacy PFX, PEM with key, key
    alone, with the root): the certificate inside the one chosen, its key
    the one that belongs to it, the other key never in the file; the
    second asked of a card without one refused;
  * no private key left in the daemon's folder;
  * the page in Chromium (php -S + Playwright): the download dialog offers
    "RSA 2048" / "EC 384" on a card with a second certificate only, and
    hands over the EC one when it is chosen; the upload dialog says that
    one pair replaces both.

    python3 test/dualcert.py

Ports 19617 (the daemon) and 19618 (php -S).
"""
import base64
import json
import os
import random
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
W = Path(tempfile.mkdtemp(prefix='zigmon-dualcert-check-'))
API_PORT, PHP_PORT = 19617, 19618
NAME = 'mqtt.house.example'
NTFY = 'ntfy.house.example'
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def sh(cmd, data=None, **kw):
    return subprocess.run(cmd, input=data, capture_output=True, text=True,
                          stdin=None if data is not None else subprocess.DEVNULL, **kw)


# ---- a CA of the test's own: one root, an RSA and an EC intermediate ------------------
CA = W / 'ca'
CA.mkdir()
sh(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(CA / 'root.key'), '-out',
    str(CA / 'root.pem'), '-days', '30', '-subj', '/CN=Test Root'])
(CA / 'ext').write_text('basicConstraints=critical,CA:TRUE\nkeyUsage=keyCertSign,cRLSign\n')
for name, newkey in (('rint', ['-newkey', 'rsa:2048']),
                     ('eint', ['-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-384'])):
    sh(['openssl', 'req', '-nodes', '-keyout', str(CA / (name + '.key')), '-out', str(CA / (name + '.csr')),
        '-subj', '/CN=Test %s' % ('R-Intermediate' if name == 'rint' else 'E-Intermediate')] + newkey)
    sh(['openssl', 'x509', '-req', '-in', str(CA / (name + '.csr')), '-CA', str(CA / 'root.pem'),
        '-CAkey', str(CA / 'root.key'), '-CAcreateserial', '-out', str(CA / (name + '.pem')), '-days', '30',
        '-extfile', str(CA / 'ext')])
ROOT = (CA / 'root.pem').read_text()
RINT = (CA / 'rint.pem').read_text()
EINT = (CA / 'eint.pem').read_text()
N = [0]


def leaf(cn, kind, extra=''):
    """(certificate, key) - RSA 2048 from the R one, EC P-384 from the E one."""
    N[0] += 1
    n = 'leaf%d' % N[0]
    newkey = ['-newkey', 'rsa:2048'] if kind == 'rsa' else ['-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-384']
    sh(['openssl', 'req', '-nodes', '-keyout', str(CA / (n + '.key')), '-out', str(CA / (n + '.csr')),
        '-subj', '/CN=%s' % cn] + newkey)
    (CA / (n + '.ext')).write_text('subjectAltName=DNS:%s%s\n' % (cn, extra))
    i = 'rint' if kind == 'rsa' else 'eint'
    sh(['openssl', 'x509', '-req', '-in', str(CA / (n + '.csr')), '-CA', str(CA / (i + '.pem')),
        '-CAkey', str(CA / (i + '.key')), '-CAcreateserial', '-out', str(CA / (n + '.pem')), '-days', '20',
        '-extfile', str(CA / (n + '.ext'))])
    return (CA / (n + '.pem')).read_text(), (CA / (n + '.key')).read_text()


def fp(pem):
    out = sh(['openssl', 'x509', '-noout', '-fingerprint', '-sha256'], pem).stdout
    return out.strip().split('=', 1)[-1].replace(':', '').lower()


def pub_cert(pem):
    return sh(['openssl', 'x509', '-noout', '-pubkey'], pem).stdout.strip()


def pub_key(pem):
    return sh(['openssl', 'pkey', '-pubout'], pem).stdout.strip()


def blocks(text, kind='CERTIFICATE'):
    return re.findall(r'-----BEGIN %s-----.*?-----END %s-----' % (kind, kind), text or '', re.S)


def keys_in(text):
    return re.findall(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----', text or '', re.S)


def pfx_of(cert, key, chain, pw):
    for n, t in (('p.crt', cert), ('p.key', key), ('p.chain', chain)):
        (CA / n).write_text(t)
    sh(['openssl', 'pkcs12', '-export', '-inkey', str(CA / 'p.key'), '-in', str(CA / 'p.crt'), '-certfile',
        str(CA / 'p.chain'), '-out', str(CA / 'p.pfx'), '-passout', 'pass:' + pw])
    return base64.b64encode((CA / 'p.pfx').read_bytes()).decode()


SANS = ',DNS:www.house.example'
RSA_C, RSA_K = leaf(NAME, 'rsa', SANS)
EC_C, EC_K = leaf(NAME, 'ec', SANS)
RSA2_C, RSA2_K = leaf(NAME, 'rsa', SANS)
EC2_C, EC2_K = leaf(NAME, 'ec', SANS)
ODD_C, ODD_K = leaf('other.house.example', 'ec')
ONE_C, ONE_K = leaf(NAME, 'rsa', SANS)
NT_RSA_C, NT_RSA_K = leaf(NTFY, 'rsa')
NT_EC_C, NT_EC_K = leaf(NTFY, 'ec')
NT_OLD_C, NT_OLD_K = leaf(NTFY, 'rsa')
FRONT_OLD_C, FRONT_OLD_K = leaf(NAME, 'rsa', SANS)
# the keys in the old forms as well: RSA PRIVATE KEY, EC PRIVATE KEY
RSA_K_OLD = sh(['openssl', 'rsa', '-traditional'], RSA_K).stdout
EC_K_OLD = sh(['openssl', 'ec'], EC_K).stdout
check('BEGIN RSA PRIVATE KEY' in RSA_K_OLD and 'BEGIN EC PRIVATE KEY' in EC_K_OLD, 'the test\'s keys in their old forms')


def both_pem(seed=7, rsa=(RSA_C, RSA_K_OLD), ec=(EC_C, EC_K_OLD)):
    parts = [rsa[0], rsa[1], ec[0], ec[1], RINT, EINT, ROOT]
    random.Random(seed).shuffle(parts)
    return '\n'.join(p.strip() for p in parts) + '\n'


# ---- this machine, as test/acme.py stands it in ---------------------------------------
STATE, ETC = W / 'state', W / 'etc'
CERTS = ETC / 'nginx' / 'certs'
for p in (STATE / 'root', ETC / 'zigmon', ETC / 'mosquitto' / 'conf.d', ETC / 'nginx' / 'conf.d', CERTS,
          W / 'logs', W / 'www', W / 'body'):
    p.mkdir(parents=True, exist_ok=True)
DB = STATE / 'history.db'
(ETC / 'zigmon' / 'config.json').write_text(json.dumps({'db_file': str(DB)}))
(ETC / 'mosquitto' / 'mosquitto.conf').write_text('listener 1883\n')
# the broker reads the same files - it takes one certificate: the RSA one
MOSQ = 'listener 8883\ncertfile %s\nkeyfile %s\n' % (CERTS / 'server.pem', CERTS / 'server.key')
(ETC / 'mosquitto' / 'conf.d' / 'zigmon.conf').write_text(MOSQ)
sh(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(CERTS / 'server.key'), '-out',
    str(CERTS / 'server.pem'), '-days', '400', '-subj', '/CN=%s' % NAME, '-addext', 'subjectAltName=DNS:%s' % NAME])
shutil.copy(CERTS / 'server.pem', CERTS / 'server.ca')
conf = (HERE / 'deploy' / 'nginx-zigmon.conf').read_text()
for a, b in (('/etc/nginx/certs/', str(CERTS) + '/'), ('/var/www/zigmon', str(W / 'www')),
             ('unix:/run/php-fpm/www.sock', 'unix:' + str(W / 'fpm.sock')),
             ('/var/log/nginx/', str(W / 'logs') + '/'),
             ('include        fastcgi_params;', 'include        /etc/nginx/fastcgi_params;'),
             ('listen      443 ssl http2;', 'listen      127.0.0.1:19619 ssl;'),
             ('listen      [::]:443 ssl http2;', ''), ('listen      80;', 'listen 127.0.0.1:19620;'),
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


def nginx_ok():
    return not NGINX or sh(['nginx', '-t', '-p', str(W), '-c', str(W / 'nginx.conf')]).returncode == 0


# ---- the server in front, as a folder laid out as the real one --------------------------
P = W / 'proxy'
PCERTS = P / 'etc' / 'nginx' / 'certs'
CONFD = P / 'etc' / 'nginx' / 'conf.d'
PCERTS.mkdir(parents=True)
CONFD.mkdir(parents=True)
TAP = '''server {
    listen      443 ssl default_server;
    server_name _;
    ssl_certificate           %(c)s/server.pem;
    ssl_certificate_key       %(c)s/server.key;
    ssl_protocols             TLSv1.2 TLSv1.3;
    return 444;
}

server {
    listen      80;
    server_name %(n)s;
    return 301 https://$host$request_uri;
}

server {
    listen      443 ssl http2;
    server_name %(n)s;                 # <- your hostname
    ssl_certificate           %(c)s/server.pem;
    ssl_certificate_key       %(c)s/server.key;
    ssl_protocols             TLSv1.2 TLSv1.3;
    ssl_stapling              on;
    ssl_trusted_certificate   %(c)s/server.ca;
    location / {
        proxy_pass https://192.0.2.10;
    }
}
'''
NTFY_CONF = '''server {
    listen      443 ssl http2;
    server_name %(t)s;                 # <- the ntfy name
    ssl_certificate           %(c)s/ntfy.pem;
    ssl_certificate_key       %(c)s/ntfy.key;
    ssl_protocols             TLSv1.2 TLSv1.3;
    location / {
        proxy_pass http://127.0.0.1:2586;
    }
}
'''


def lay_proxy():
    for f in list(PCERTS.iterdir()) + list(CONFD.iterdir()):
        f.unlink()
    (PCERTS / 'server.pem').write_text(FRONT_OLD_C + RINT)
    (PCERTS / 'server.key').write_text(FRONT_OLD_K)
    (PCERTS / 'server.ca').write_text(RINT)
    (PCERTS / 'ntfy.pem').write_text(NT_OLD_C + RINT)
    (PCERTS / 'ntfy.key').write_text(NT_OLD_K)
    for k in ('server.key', 'ntfy.key'):
        os.chmod(PCERTS / k, 0o600)
    v = {'c': str(PCERTS), 'n': NAME, 't': NTFY}
    (CONFD / 'nginx-tap-front.conf').write_text(TAP % v)
    (CONFD / 'nginx-ntfy-front.conf').write_text(NTFY_CONF % v)


def snap(which):
    """The files of one card there: its conf and its certificate files."""
    if which == 'front':
        names = ['nginx-tap-front.conf', 'server.pem', 'server.key', 'server.ca', 'server-ecdsa.pem', 'server-ecdsa.key']
    else:
        names = ['nginx-ntfy-front.conf', 'ntfy.pem', 'ntfy.key', 'ntfy-ecdsa.pem', 'ntfy-ecdsa.key', 'ntfy.ca']
    out = {}
    for n in names:
        f = (CONFD if n.endswith('.conf') else PCERTS) / n
        out[n] = f.read_bytes() if f.exists() else None
    return out


lay_proxy()
FAKES = W / 'bin'
FAKES.mkdir()
LOG = W / 'proxy.log'
(FAKES / 'ssh').write_text('''#!/bin/sh
for a; do last="$a"; done
echo "ssh $*" | sed 's/-i [^ ]*/-i KEY/' >> %(log)s
case " $* " in *" -i "*) ;; *) echo "no key" >&2; exit 255;; esac
exec sh -c "$last"
''' % {'log': LOG})
(FAKES / 'nginx').write_text('''#!/bin/sh
case "$1" in
  -T) for f in %(confd)s/*.conf; do echo "# configuration file $f:"; cat "$f"; done ;;
  -t) echo "nginx -t" >> %(log)s; [ -e %(w)s/nginx-says-no ] && { echo "nginx: [emerg] no" >&2; exit 1; }; exit 0 ;;
  -s) echo "nginx -s $2" >> %(log)s ;;
esac
''' % {'confd': CONFD, 'log': LOG, 'w': W})
(FAKES / 'systemctl').write_text('#!/bin/sh\necho "systemctl $*" >> %s\n' % LOG)
for f in FAKES.iterdir():
    f.chmod(0o755)
os.environ.update(ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(W / 'own'), ZIGMON_FULL_DIR=str(W / 'full'),
                  ZIGMON_CONFIG=str(ETC / 'zigmon' / 'config.json'), ZIGMON_NGINX_CONF=str(NGINX_CONF),
                  ZIGMON_CERT_DIR=str(CERTS), ZIGMON_MOSQ_DIR=str(ETC / 'mosquitto'),
                  ZIGMON_NO_SERVICES='1', ZIGMON_SERVICE_LOG=str(W / 'services.log'), ZIGMON_FS_ROOT=str(W),
                  ZIGMON_USER='root', ZIGMON_FW_FILE4=str(W / 'no4'), ZIGMON_FW_FILE6=str(W / 'no6'),
                  ZIGMON_FIREWALL_CMD=str(W / 'no-firewall-cmd'), ZIGMON_SSH_BIN=str(FAKES / 'ssh'),
                  ZIGMON_NGINX_TEST=('nginx -t -p %s -c %s' % (W, W / 'nginx.conf')) if NGINX else 'true',
                  ZIGMON_ROOT_RUN='%s -I %s' % (sys.executable, ROOT_HELPER))
check(nginx_ok(), 'the test machine\'s nginx does not take the shipped file to begin with')
# the stand-in nginx of the server in front is found by root's ssh only, not by this machine's check
PATH_HERE = os.environ['PATH']
os.environ['PATH'] = '%s:%s' % (FAKES, PATH_HERE)
if NGINX:
    os.environ['ZIGMON_NGINX_TEST'] = 'env PATH=%s nginx -t -p %s -c %s' % (PATH_HERE, W, W / 'nginx.conf')

sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

SSH_KEY = '-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----\n'
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(DB), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'log_file': '', 'state_dir': str(STATE), 'acme': 0,
                      'proxy_host': 'proxy.house.example', 'proxy_auth': 'key'})
d = zigmon.Daemon()
d.notify = lambda message, *a, **k: None
d.store.set_meta('proxy_key', SSH_KEY)
d.proxy_run = lambda command: subprocess.run(['sh', '-c', command], capture_output=True, text=True,
                                             stdin=subprocess.DEVNULL).stdout
d._proxy_tls_looking = d._proxy_ntfy_looking = True          # looks are made by the test, not a thread
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def relook():
    d._proxy_tls_look = zigmon.proxy_tls_read(d)
    d._proxy_ntfy_look = zigmon.proxy_tls_read(d, 'ntfy')


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
S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''


def tls(body, target=''):
    b = dict(body, session=S)
    if target:
        b['target'] = target
    return call('/api/tls', b, session=S)


def nginx_pairs():
    text = NGINX_CONF.read_text()
    https = text[text.index('# HTTPS: the dashboard'):]
    return (re.findall(r'(?m)^\s*ssl_certificate\s+(\S+);', https),
            re.findall(r'(?m)^\s*ssl_certificate_key\s+(\S+);', https))


def keys_left():
    """Any private key in the daemon's own folder outside its database."""
    out = []
    for p in STATE.rglob('*'):
        if p.is_file() and not p.name.startswith('history.db') and 'PRIVATE KEY' in p.read_text(errors='replace'):
            out.append(str(p))
    return out


def is_dual_here():
    c, k = nginx_pairs()
    return len(c) == 2 and len(k) == 2


def pairs_right(certs, keys, rsa, ec, rint=RINT, eint=EINT, where='here'):
    """Both pairs named in order and each file what it should be."""
    if len(certs) != 2 or len(keys) != 2:
        check(False, '%s: nginx is not given two certificate pairs: %r %r' % (where, certs, keys))
        return False
    c0, c1 = Path(certs[0]).read_text(), Path(certs[1]).read_text()
    k0, k1 = Path(keys[0]).read_text(), Path(keys[1]).read_text()
    check(fp(c0) == fp(rsa[0]) and rint.strip() in c0 and EINT.strip() not in c0,
          '%s: the first file is not the RSA certificate with its own chain' % where)
    check(fp(c1) == fp(ec[0]) and eint.strip() in c1 and RINT.strip() not in c1,
          '%s: the second file is not the EC certificate with its own chain' % where)
    check(pub_key(k0) == pub_cert(rsa[0]) and pub_key(k1) == pub_cert(ec[0]),
          '%s: the keys are not each their certificate\'s' % where)
    check(oct(Path(keys[0]).stat().st_mode & 0o777) == '0o600' and oct(Path(keys[1]).stat().st_mode & 0o777) == '0o600',
          '%s: a key file is not 0600' % where)
    return True


DOWN_PLAIN = ('pem_chain', 'pem_cert', 'chain', 'der')
DOWN_KEYED = ('pem_key', 'key', 'pfx', 'pfx_legacy')


def export_file():
    st = d.root_read('status.json')
    name = st.get('out')
    if st.get('state') != 'done' or not name:
        return None, st
    p = STATE / 'root' / 'out' / name
    data = p.read_bytes() if p.is_file() else None
    try:
        p.unlink()
    except OSError:
        pass
    return data, st


def downloads(target, chosen, other, chosen_int, other_int, label):
    """Every format of the chosen one: its certificate, its key, never the other's."""
    pair = 'alt' if label == 'EC' else 'main'
    body = {'pair': pair} if pair == 'alt' else {}
    # two side by side on the card to begin with - every check below is of that
    if not target:
        dual = is_dual_here()
    else:
        relook()
        dual = bool(((d._proxy_ntfy_look if target == 'proxy-ntfy' else d._proxy_tls_look) or {}).get('alt_info'))
    check(dual, '%s %s: there are not two to download from' % (target or 'here', label))
    for fmt in DOWN_PLAIN:
        code, out = tls(dict(body, action='tls_get', format=fmt), target)
        if code != 200:
            check(False, '%s %s %s: not given: %s' % (target or 'here', label, fmt, out))
            continue
        if fmt == 'der':
            der = base64.b64decode(out.get('b64') or '')
            got = subprocess.run(['openssl', 'x509', '-inform', 'DER'], input=der, capture_output=True).stdout.decode()
            check(dual and fp(got) == fp(chosen[0]), '%s %s DER: another certificate' % (target or 'here', label))
            continue
        text = out.get('text') or ''
        bl = blocks(text)
        if fmt == 'chain':
            check(dual and chosen_int.strip() in text and other_int.strip() not in text and fp(chosen[0]) not in
                  [fp(b + '\n') for b in bl], '%s %s CA chain: not its own chain' % (target or 'here', label))
        else:
            check(dual and bl and fp(bl[0] + '\n') == fp(chosen[0]) and other_int.strip() not in text and
                  not keys_in(text), '%s %s %s: another certificate in it' % (target or 'here', label, fmt))
        if label == 'EC':
            check(dual and out.get('name', '').endswith('-ecdsa'), '%s EC: the file is not named apart: %r'
                  % (target or 'here', out.get('name')))
    for fmt in DOWN_KEYED:
        for with_root in ((False, True) if fmt == 'pem_key' else (False,)):
            pw = 'p4ss-word' if fmt.startswith('pfx') else ''
            code, out = tls(dict(body, action='tls_export', format=fmt, password=pw, password2=pw,
                                 with_root=with_root), target)
            data, st = export_file()
            if code != 200 or data is None:
                check(False, '%s %s %s: not handed over: %s %s' % (target or 'here', label, fmt, out, st.get('said')))
                continue
            if fmt.startswith('pfx'):
                (W / 'got.pfx').write_bytes(data)
                args = ['openssl', 'pkcs12', '-in', str(W / 'got.pfx'), '-nodes', '-passin', 'pass:' + pw]
                text = sh(args).stdout or sh(args + ['-legacy']).stdout
            else:
                text = data.decode('utf-8', 'replace')
            ks = keys_in(text)
            what = '%s %s %s%s' % (target or 'here', label, fmt, ' with the root' if with_root else '')
            check(dual and len(ks) == 1 and pub_key(ks[0] + '\n') == pub_cert(chosen[0]),
                  '%s: not its own one key: %d key(s)' % (what, len(ks)))
            check(dual and all(pub_key(k + '\n') != pub_cert(other[0]) for k in ks), '%s: the other key is in it' % what)
            if fmt != 'key':
                bl = blocks(text)
                check(dual and bl and fp(chosen[0]) in [fp(b + '\n') for b in bl] and fp(other[0]) not in
                      [fp(b + '\n') for b in bl] and other_int.strip() not in text,
                      '%s: not the chosen certificate and its chain alone' % what)
                if with_root:
                    check(dual and ROOT.strip() in text and chosen_int.strip() in text, '%s: the root is not with it' % what)
            else:
                check(dual and not blocks(text), '%s: the key alone has a certificate with it' % what)


try:
    # ---- this machine: one PEM with both pairs ---------------------------------------------
    print('this machine: both pairs in one PEM, shuffled')
    code, out = tls({'action': 'tls_upload', 'cert': both_pem()})
    st = d.root_read('status.json')
    check(code == 200 and st.get('state') == 'done' and is_dual_here(),
          'both pairs in one PEM were not put in: %s %r' % (out, st.get('said')))
    certs, keys = nginx_pairs()
    if pairs_right(certs, keys, (RSA_C, RSA_K), (EC_C, EC_K)):
        check(certs[0] == str(CERTS / 'server.pem') and keys[0] == str(CERTS / 'server.key'),
              'the RSA one is not in the files the broker reads')
        trust = (CERTS / 'server.ca').read_text()
        check(ROOT.strip() in trust and RINT.strip() in trust and EINT.strip() in trust and
              trust.count('BEGIN CERTIFICATE') == 3, 'the chain nginx trusts is not the root and both intermediates')
    check((ETC / 'mosquitto' / 'conf.d' / 'zigmon.conf').read_text() == MOSQ and
          fp((CERTS / 'server.pem').read_text()) == fp(RSA_C) and is_dual_here(),
          'the broker does not read the RSA one beside two')
    check(is_dual_here() and nginx_ok(), 'nginx does not take the two certificates as root wrote them')
    look = d.root_look(fresh=True).get('tls') or {}
    check((look.get('alt_info') or {}).get('key') == 'EC 384' and (look.get('info') or {}).get('key') == 'RSA 2048',
          'the card does not say "And: EC 384" beside RSA 2048: %r' % look.get('alt_info'))
    check(is_dual_here() and not keys_left(), 'a key was left in the daemon\'s folder: %r' % keys_left())

    print('this machine: downloads, RSA and EC')
    downloads('', (RSA_C, RSA_K), (EC_C, EC_K), RINT, EINT, 'RSA')
    downloads('', (EC_C, EC_K), (RSA_C, RSA_K), EINT, RINT, 'EC')
    check(is_dual_here() and not keys_left(), 'a key was left in the daemon\'s folder after the downloads: %r'
          % keys_left())

    print('this machine: PFX files')
    # A PFX holding both keys is not made here: openssl pkcs12 -export takes
    # one -inkey, so openssl cannot make one. Two PFX files, and a PFX with
    # the other pair in PEM, are what can be given.
    tls({'action': 'tls_upload', 'cert': ONE_C + RINT + ONE_K})
    code, out = tls({'action': 'tls_upload', 'pfx': pfx_of(RSA2_C, RSA2_K, RINT + ROOT, 'pfx-pass'),
                     'pfx2': pfx_of(EC2_C, EC2_K, EINT + ROOT, 'pfx-pass'), 'password': 'pfx-pass'})
    certs, keys = nginx_pairs()
    check(code == 200 and len(certs) == 2, 'two PFX files were not put in side by side: %s' % out)
    if code == 200:
        pairs_right(certs, keys, (RSA2_C, RSA2_K), (EC2_C, EC2_K), where='two PFX files')
    tls({'action': 'tls_upload', 'cert': ONE_C + RINT + ONE_K})
    code, out = tls({'action': 'tls_upload', 'pfx': pfx_of(EC_C, EC_K, EINT, 'pfx-pass'),
                     'cert': RSA_C + RINT + RSA_K, 'password': 'pfx-pass'})
    certs, keys = nginx_pairs()
    check(code == 200 and len(certs) == 2, 'a PFX with a PEM were not put in side by side: %s' % out)
    if code == 200:
        pairs_right(certs, keys, (RSA_C, RSA_K), (EC_C, EC_K), where='a PFX and a PEM')

    print('this machine: refused')
    was = NGINX_CONF.read_text()
    files0 = {f: f.read_bytes() for f in CERTS.iterdir()}
    for text, why, words in ((RSA_C + RSA_K + ODD_C + ODD_K + RINT + EINT, 'names that differ', 'same names'),
                             (RSA_C + RSA_K + RSA2_C + RSA2_K + RINT, 'two RSA keys', 'two RSA keys'),
                             (EC_C + EC_K + EC2_C + EC2_K + EINT, 'two EC keys', 'two EC keys'),
                             (RSA_C + RSA_K + EC_K + RINT, 'an EC key without its certificate', 'EC key')):
        code, out = tls({'action': 'tls_upload', 'cert': text})
        check(code == 400 and words in (out.get('error') or ''), '%s were not refused with words that say so: %s %s'
              % (why, code, out))
    check(NGINX_CONF.read_text() == was and files0 == {f: f.read_bytes() for f in CERTS.iterdir()},
          'something was put in for a refused upload')

    # ---- the server in front -------------------------------------------------------------
    print('the server in front: both pairs over SSH')
    lay_proxy()
    relook()
    nt0 = snap('ntfy')
    LOG.write_text('')
    code, out = tls({'action': 'tls_upload', 'cert': both_pem(11)}, 'proxy')
    st = d.root_read('status.json')
    check(code == 200 and st.get('state') == 'done' and (PCERTS / 'server-ecdsa.pem').is_file(),
          'both pairs were not put on the server in front: %s %r'
          % (out, st.get('said')))
    tap = (CONFD / 'nginx-tap-front.conf').read_text()
    for blk in re.findall(r'server \{.*?\n\}', tap, re.S):
        if 'listen      443' not in blk:
            continue
        c = re.findall(r'(?m)^\s*ssl_certificate\s+(\S+);', blk)
        k = re.findall(r'(?m)^\s*ssl_certificate_key\s+(\S+);', blk)
        pairs_right(c, k, (RSA_C, RSA_K), (EC_C, EC_K), where='the server in front')
    front_two = len(re.findall(r'(?m)^\s*ssl_certificate\s', tap)) == 4
    check(front_two and 'systemctl reload nginx' in LOG.read_text() and 'nginx -t' in LOG.read_text(),
          'nginx there was not checked and reloaded')
    check(front_two and snap('ntfy') == nt0, 'both for the front touched ntfy\'s files')
    check(EINT.strip() in (PCERTS / 'server.ca').read_text(), 'the EC chain is not in the chain trusted there')
    relook()
    check(((d._proxy_tls_look or {}).get('alt_info') or {}).get('key') == 'EC 384',
          'the card of the server in front does not read the second one: %r' % (d._proxy_tls_look or {}).get('alt_info'))
    view = (call('/api/tls', session=S)[1].get('proxy') or {}).get('look') or {}
    check((view.get('alt_info') or {}).get('key') == 'EC 384' and 'alt_pem' not in view and 'pem' not in view,
          'the page is not told of the second one there, or is given its file: %r' % sorted(view))
    print('the server in front: downloads, RSA and EC')
    downloads('proxy', (RSA_C, RSA_K), (EC_C, EC_K), RINT, EINT, 'RSA')
    downloads('proxy', (EC_C, EC_K), (RSA_C, RSA_K), EINT, RINT, 'EC')
    # nginx -t says no: every file as it was, the new ones gone again
    lay_proxy()
    (W / 'nginx-says-no').write_text('')
    was = {f: f.read_bytes() for f in P.rglob('*') if f.is_file()}
    code, out = tls({'action': 'tls_upload', 'cert': both_pem(13)}, 'proxy')
    (W / 'nginx-says-no').unlink()
    st = d.root_read('status.json')
    check(front_two and st.get('state') == 'failed' and 'would not take it' in ' '.join(st.get('said') or []) and
          was == {f: f.read_bytes() for f in P.rglob('*') if f.is_file()},
          'both pairs nginx there refused were left in place: %r' % st.get('said'))
    # one pair after two: the second taken out of the block
    lay_proxy()
    tls({'action': 'tls_upload', 'cert': both_pem(17)}, 'proxy')
    two = len(re.findall(r'(?m)^\s*ssl_certificate\s', (CONFD / 'nginx-tap-front.conf').read_text()))
    code, out = tls({'action': 'tls_upload', 'cert': ONE_C + RINT + ONE_K}, 'proxy')
    tap = (CONFD / 'nginx-tap-front.conf').read_text()
    check(two == 4 and code == 200 and len(re.findall(r'(?m)^\s*ssl_certificate\s', tap)) == 2 and
          fp((PCERTS / 'server.pem').read_text()) == fp(ONE_C),
          'one pair after two on the server in front did not leave one: %d / %s' % (two, out))
    relook()
    code, out = tls({'action': 'tls_get', 'format': 'pem_cert', 'pair': 'alt'}, 'proxy')
    check(two == 4 and code == 400, 'the second one there was handed over though there is none: %s' % out)

    # ---- ntfy on the server in front -----------------------------------------------------------
    print('ntfy on the server in front: both pairs over SSH')
    lay_proxy()
    relook()
    fr0 = snap('front')
    code, out = tls({'action': 'tls_upload', 'cert': both_pem(19, (NT_RSA_C, NT_RSA_K), (NT_EC_C, NT_EC_K))},
                    'proxy-ntfy')
    st = d.root_read('status.json')
    check(code == 200 and st.get('state') == 'done' and (PCERTS / 'ntfy-ecdsa.pem').is_file(),
          'both pairs were not put in ntfy\'s block there: %s %r'
          % (out, st.get('said')))
    nconf = (CONFD / 'nginx-ntfy-front.conf').read_text()
    c = re.findall(r'(?m)^\s*ssl_certificate\s+(\S+);', nconf)
    k = re.findall(r'(?m)^\s*ssl_certificate_key\s+(\S+);', nconf)
    pairs_right(c, k, (NT_RSA_C, NT_RSA_K), (NT_EC_C, NT_EC_K), where='ntfy there')
    check(len(c) == 2 and snap('front') == fr0, 'both for ntfy touched the front\'s files')
    relook()
    check(((d._proxy_ntfy_look or {}).get('alt_info') or {}).get('key') == 'EC 384',
          'ntfy\'s card does not read the second one: %r' % (d._proxy_ntfy_look or {}).get('alt_info'))
    print('ntfy on the server in front: downloads, RSA and EC')
    downloads('proxy-ntfy', (NT_RSA_C, NT_RSA_K), (NT_EC_C, NT_EC_K), RINT, EINT, 'RSA')
    downloads('proxy-ntfy', (NT_EC_C, NT_EC_K), (NT_RSA_C, NT_RSA_K), EINT, RINT, 'EC')
    code, out = tls({'action': 'tls_upload', 'cert': NT_RSA_C + NT_RSA_K + ODD_C + ODD_K}, 'proxy-ntfy')
    check(code == 400 and 'same names' in (out.get('error') or ''), 'names that differ were taken for ntfy: %s' % out)
    check(is_dual_here() and not keys_left(), 'a key was left in the daemon\'s folder: %r' % keys_left())

    # ---- the page -------------------------------------------------------------------------
    print('the page')
    # here: both; the front there: one; ntfy there: both
    lay_proxy()
    tls({'action': 'tls_upload', 'cert': both_pem(23, (NT_RSA_C, NT_RSA_K), (NT_EC_C, NT_EC_K))}, 'proxy-ntfy')
    relook()
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
    js = r'''
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({viewport: {width: 1500, height: 1100}, acceptDownloads: true});
  await ctx.addCookies([{name: 'zigmon_session', value: %(s)s, url: 'http://127.0.0.1:%(port)d/'}]);
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.goto('http://127.0.0.1:%(port)d/#control/sys-certs');
  await p.waitForTimeout(2500);
  try { await p.evaluate(() => showControlSection('sys-certs')); } catch (e) {}
  await p.waitForSelector('#web-certs .cert-card', {timeout: 15000});
  await p.waitForTimeout(1500);
  const r = {dialogs: [], uploads: []};
  r.ands = await p.evaluate(() => Array.from(document.querySelectorAll('#web-certs .cert-grid > .cert-card')).map(c =>
    Array.from(c.querySelectorAll('.cert-kv dt')).some(t => t.textContent === 'And') ?
      c.querySelector('.cert-kv').textContent : ''));
  for (let i = 1; i <= 3; i++) {
    const card = '#web-certs .cert-grid > .cert-card:nth-child(' + i + ')';
    await p.click(card + ' .cert-tools button:has-text("Download")');
    await p.waitForSelector('#zmodal:not([hidden]) .fmt-grid', {timeout: 10000});
    r.dialogs.push(await p.evaluate(() => Array.from(document.querySelectorAll('#zmodal .cert-pair button')).map(x => x.textContent)));
    if (i === 1) {
      try {
        await p.click('#zmodal .cert-pair button:has-text("EC")');
        r.forEc = await p.evaluate(() => document.querySelector('#zmodal .note').textContent);
        await p.click('#zmodal .fmt-card:has-text("Certificate only")');
        const [dl] = await Promise.all([p.waitForEvent('download', {timeout: 20000}),
                                        p.click('#zmodal-foot .btn.primary')]);
        r.dlName = dl.suggestedFilename();
        await dl.saveAs(%(dl)s);
      } catch (e) { r.dlErr = String(e); }
    }
    await p.evaluate(() => { try { closeZModal(); } catch (e) {} });
    await p.waitForTimeout(300);
    await p.click(card + ' .cert-tools button:has-text("Upload")');
    try {
      await p.waitForSelector('#zmodal:not([hidden]) textarea.cert-paste', {timeout: 10000});
    } catch (e) {
      // this machine's asks first whether to keep Automatic certificates out of it
      const go = await p.$('#zmodal-foot .btn.primary');
      if (go) await go.click();
      await p.waitForSelector('#zmodal:not([hidden]) textarea.cert-paste', {timeout: 10000});
    }
    r.uploads.push(await p.evaluate(() => Array.from(document.querySelectorAll('#zmodal .note.warn')).map(x => x.textContent).join(' ')));
    await p.evaluate(() => { try { closeZModal(); } catch (e) {} });
    await p.waitForTimeout(300);
  }
  r.errors = errors;
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
    (W / 'page.js').write_text(js % {'s': json.dumps(S), 'port': PHP_PORT, 'dl': json.dumps(str(W / 'dl.crt'))})
    npm_root = sh(['npm', 'root', '-g']).stdout.strip()
    got = sh(['node', str(W / 'page.js')], timeout=240, env=dict(os.environ, NODE_PATH=npm_root))
    try:
        r = json.loads(got.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        r = {'error': (got.stdout + got.stderr)[-300:]}
    if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
        print('  SKIPPED (no browser here): %s' % r['error'][:200])
    else:
        check(not r.get('error'), 'the page in Chromium: %s' % r.get('error'))
        ands = r.get('ands') or []
        check(len(ands) == 3 and 'EC 384 - sent to clients that take ECDSA' in ands[0] and not ands[1] and
              'EC 384' in ands[2], 'the cards do not say "And: EC 384" where there are two: %r' % ands)
        check(r.get('dialogs') == [['RSA 2048', 'EC 384'], [], ['RSA 2048', 'EC 384']],
              'the download dialog does not offer RSA 2048 / EC 384 on the cards with two only: %r' % r.get('dialogs'))
        dl = (W / 'dl.crt').read_text() if (W / 'dl.crt').exists() else ''
        check(dl and fp(dl) == fp(EC_C) and str(r.get('dlName', '')).endswith('-ecdsa.crt'),
              'EC chosen in the dialog, the EC certificate was not downloaded: %r %r' % (r.get('dlName'), r.get('dlErr')))
        ups = r.get('uploads') or []
        check(len(ups) == 3 and 'replaces both' in ups[0] and 'replaces both' not in ups[1] and 'replaces both' in ups[2],
              'the upload dialog does not say one pair replaces both where there are two: %r' % ups)
        check(len(ands) == 3 and ands[0] and not r.get('errors'), 'the page threw: %r' % r.get('errors'))

    # ---- one pair after two, here: the second taken out ---------------------------------------
    print('this machine: one pair after two')
    was_two = is_dual_here()
    code, out = tls({'action': 'tls_upload', 'cert': ONE_C + RINT + ONE_K})
    certs, keys = nginx_pairs()
    check(was_two and code == 200 and len(certs) == 1 and len(keys) == 1 and
          fp((CERTS / 'server.pem').read_text()) == fp(ONE_C),
          'one pair uploaded over two did not leave one: %r %s' % (certs, out))
    check(was_two and nginx_ok(), 'nginx does not take one certificate after two')
    look = d.root_look(fresh=True).get('tls') or {}
    code, out = tls({'action': 'tls_export', 'format': 'pem_key', 'pair': 'alt'})
    st = d.root_read('status.json')
    check(was_two and not look.get('alt_info') and st.get('state') == 'failed' and 'no second' in
          ' '.join(st.get('said') or []), 'the second one was handed over though nginx serves none: %r' % st.get('said'))
    check(was_two and not keys_left(), 'a key was left in the daemon\'s folder: %r' % keys_left())
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
    except Exception:                                        # noqa: BLE001
        pass

shutil.rmtree(W, ignore_errors=True)
print('dualcert: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
os._exit(1 if bad else 0)
