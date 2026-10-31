#!/usr/bin/env python3
"""5.30: the certificate downloaded in the format asked - PEM, DER, the chain,
or with its private key as PEM or PFX / PKCS#12 with a password. Every check
fails on 5.29.7 and passes since.

    python3 test/review530.py

Root's helper is run straight away on a machine of its own in a temporary
folder (as test/root.py does); the key is read by root alone.
"""
import base64
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
HELPER = HERE / 'deploy' / 'zigmon_root.py'
W = Path(tempfile.mkdtemp(prefix='zigmon-review530-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


STATE = W / 'state'
(STATE / 'root').mkdir(parents=True)
CERTS = W / 'etc' / 'nginx' / 'certs'
CERTS.mkdir(parents=True)
(W / 'etc' / 'nginx' / 'conf.d').mkdir(parents=True)


def certificate(name, cn, ca=None):
    key, crt = W / (name + '.key'), W / (name + '.crt')
    sh(['openssl', 'genrsa', '-out', str(key), '2048'])
    if ca is None:
        sh(['openssl', 'req', '-x509', '-new', '-key', str(key), '-days', '400', '-subj', '/CN=%s' % cn,
            '-out', str(crt), '-addext', 'basicConstraints=critical,CA:TRUE'])
    else:
        csr = W / (name + '.csr')
        sh(['openssl', 'req', '-new', '-key', str(key), '-subj', '/CN=%s' % cn, '-out', str(csr)])
        ext = W / (name + '.ext')
        ext.write_text('subjectAltName=DNS:%s\nbasicConstraints=CA:%s\n' % (cn, 'TRUE' if name.endswith('ca') else 'FALSE'))
        sh(['openssl', 'x509', '-req', '-in', str(csr), '-CA', str(ca[1]), '-CAkey', str(ca[0]),
            '-CAcreateserial', '-days', '400', '-out', str(crt), '-extfile', str(ext)])
    p8 = W / (name + '.p8')
    sh(['openssl', 'pkey', '-in', str(key), '-out', str(p8)])
    return p8, crt


ca_key, ca_crt = certificate('rootca', 'House Root CA')
mid_key, mid_crt = certificate('midca', 'House Intermediate CA', ca=(ca_key, ca_crt))
leaf_key, leaf_crt = certificate('leaf', 'mqtt.falco81.net', ca=(mid_key, mid_crt))
(CERTS / 'server.pem').write_text(leaf_crt.read_text() + mid_crt.read_text())
shutil.copy(leaf_key, CERTS / 'server.key')
shutil.copy(ca_crt, CERTS / 'server.ca')
conf = (HERE / 'deploy' / 'nginx-zigmon.conf').read_text().replace('/etc/nginx/certs/', str(CERTS) + '/')
NGINX_CONF = W / 'etc' / 'nginx' / 'conf.d' / 'zigmon.conf'
NGINX_CONF.write_text(conf)
ENV = dict(os.environ, ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(W / 'own'), ZIGMON_FULL_DIR=str(W / 'full'),
           ZIGMON_NGINX_CONF=str(NGINX_CONF), ZIGMON_CERT_DIR=str(CERTS), ZIGMON_NO_SERVICES='1',
           ZIGMON_SERVICE_LOG=str(W / 'services.log'), ZIGMON_FS_ROOT=str(W), ZIGMON_USER='root',
           ZIGMON_NGINX_TEST='true')


def ask(req):
    (STATE / 'root' / 'request.json').write_text(json.dumps(req))
    sh([sys.executable, '-I', str(HELPER)], env=ENV)
    try:
        return json.loads((STATE / 'root' / 'status.json').read_text())
    except (OSError, ValueError):
        return {}


def handed(st):
    name = st.get('out') or ''
    p = STATE / 'root' / 'out' / name
    return p if name and p.is_file() else None


print('root hands the certificate over with its key, in the format asked')
st = ask({'kind': 'tls_export', 'id': 'e1', 'format': 'pfx', 'password': 'p4ss-word'})
f = handed(st)
check(st.get('state') == 'done' and f, 'no PFX was handed over: %r' % st.get('said'))
if f:
    out = sh(['openssl', 'pkcs12', '-in', str(f), '-nodes', '-passin', 'pass:p4ss-word'])
    check(out.returncode == 0 and 'PRIVATE KEY' in out.stdout and out.stdout.count('BEGIN CERTIFICATE') == 2,
          'the PFX does not open with its password, or lacks the key or the chain: %s' % out.stderr[-200:])
    check(sh(['openssl', 'pkcs12', '-in', str(f), '-nodes', '-passin', 'pass:wrong']).returncode != 0,
          'the PFX opens with a wrong password')
    check(stat.S_IMODE(os.stat(f).st_mode) == 0o640, 'the file handed over is %o, not 640' % stat.S_IMODE(os.stat(f).st_mode))
    check(f.name == 'zigmon-cert-mqtt.falco81.net.pfx', 'the file is called %s' % f.name)
st = ask({'kind': 'tls_export', 'id': 'e2', 'format': 'pfx', 'password': 'p4ss-word', 'with_root': True})
f = handed(st)
if f:
    out = sh(['openssl', 'pkcs12', '-in', str(f), '-nodes', '-passin', 'pass:p4ss-word'])
    check(out.stdout.count('BEGIN CERTIFICATE') == 3, 'with the root asked for, the PFX has %d certificates'
          % out.stdout.count('BEGIN CERTIFICATE'))
st = ask({'kind': 'tls_export', 'id': 'e3', 'format': 'pfx', 'password': ''})
check(st.get('state') == 'failed', 'a PFX with no password was made')
st = ask({'kind': 'tls_export', 'id': 'e4', 'format': 'pfx_legacy', 'password': 'p4ss-word'})
f = handed(st)
check(st.get('state') == 'done' and f, 'no legacy PFX: %r' % st.get('said'))
if f:
    opened = any(sh(['openssl', 'pkcs12', '-in', str(f), '-nodes', '-passin', 'pass:p4ss-word'] + x).returncode == 0
                 for x in ([], ['-legacy']))
    info = sh(['openssl', 'pkcs12', '-in', str(f), '-info', '-noout', '-passin', 'pass:p4ss-word', '-legacy'])
    check(opened and ('3DES' in (info.stdout + info.stderr) or 'TripleDES' in (info.stdout + info.stderr)), 'the legacy PFX is not 3DES: %s' % (info.stderr[-200:]))
st = ask({'kind': 'tls_export', 'id': 'e5', 'format': 'pem_key', 'password': 'k3y-pass'})
f = handed(st)
if f:
    text = f.read_text()
    check(text.count('BEGIN CERTIFICATE') == 2 and 'ENCRYPTED PRIVATE KEY' in text,
          'the PEM with its key is not the certificate, its chain and a locked key')
    check(sh(['openssl', 'pkey', '-passin', 'pass:k3y-pass'], input=text[text.index('-----BEGIN ENCRYPTED'):]).returncode == 0,
          'the locked key does not open with its password')
else:
    check(False, 'no PEM with its key: %r' % st.get('said'))
st = ask({'kind': 'tls_export', 'id': 'e6', 'format': 'key', 'password': ''})
f = handed(st)
check(f and 'BEGIN PRIVATE KEY' in f.read_text() and 'CERTIFICATE' not in f.read_text(),
      'the key alone was not handed over: %r' % st.get('said'))
outs = [p.name for p in (STATE / 'root' / 'out').iterdir() if p.name.startswith('zigmon-cert-')]
check(len(outs) == 1, 'more than one certificate file is left waiting: %r' % outs)
shutil.copy(W / 'midca.p8', CERTS / 'server.key')
st = ask({'kind': 'tls_export', 'id': 'e7', 'format': 'pfx', 'password': 'p4ss-word'})
check(st.get('state') == 'failed' and 'does not belong' in ' '.join(st.get('said') or []),
      'a key that is not the certificate\'s was handed over: %r' % st)
st = ask({'kind': 'tls_export', 'id': 'e8', 'format': 'tar', 'password': ''})
check(st.get('state') == 'failed', 'a format root does not know was taken')
shutil.copy(leaf_key, CERTS / 'server.key')

print('the daemon: without the key at once, with it through root, and the page')
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 0, 'token_file': str(W / 'run' / 'api-token'),
                      'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '',
                      'state_dir': str(W / 'dstate')})
(W / 'dstate').mkdir()
d = zigmon.Daemon()
d.tls_pem_now = lambda: (CERTS / 'server.pem').read_text()
plain = getattr(d, 'tls_export_plain', None)
if plain:
    der = base64.b64decode(plain('der')['b64'])
    got = subprocess.run(['openssl', 'x509', '-inform', 'DER', '-noout', '-subject'], input=der,
                         capture_output=True)
    check(got.returncode == 0 and b'mqtt.falco81.net' in got.stdout, 'the DER is not the certificate')
    check(plain('chain')['text'].count('BEGIN CERTIFICATE') == 1 and plain('pem_cert')['text'].count('BEGIN') == 1
          and plain('pem_chain')['text'].count('BEGIN CERTIFICATE') == 2, 'the PEM kinds are not what they say')
else:
    check(False, 'the certificate can only be downloaded as PEM with its chain')
asked = []
d.root_ask = lambda kind, body=None, quiet=False: asked.append((kind, body)) or 'id1'
try:
    d.tls_export({'format': 'pfx', 'password': 'p4ss-word', 'password2': 'p4ss-word'}, 'jana')
except Exception as e:                                  # noqa: BLE001
    print('   ', e)
check(asked and asked[0][0] == 'tls_export' and asked[0][1].get('format') == 'pfx',
      'the key is not asked of root: %r' % asked)
for body in ({'format': 'pfx', 'password': ''}, {'format': 'pfx', 'password': 'abcd', 'password2': 'abce'}):
    try:
        d.tls_export(body, 'jana')
        ok = False
    except (ValueError, AttributeError):
        ok = True
    check(ok, 'a PFX was asked for with %r' % body)
page = (HERE / 'web' / 'index.php').read_text()
check("$what === 'tls-download'" in page and 'function certDownload(' in page and "'pfx_legacy'" in page,
      'the page has no download of the certificate with its key')
check(getattr(zigmon.Daemon, 'TLS_EXPORT_FILE', None) is not None and
      zigmon.Daemon.TLS_EXPORT_FILE.match('zigmon-cert-mqtt.falco81.net.pfx') and
      not zigmon.Daemon.TLS_EXPORT_FILE.match('../etc/shadow'), 'the download takes names it should not')

sys.stdout.flush()
if bad:
    print('\n%d check(s) failed' % len(bad))
    os._exit(1)
print('the certificate is downloaded in the format asked, with its key from root alone')
os._exit(0)
