#!/usr/bin/env python3
"""5.43.3: the bugs found going over the certificates again - this machine's,
the server in front's and ntfy's there, Automatic certificates and acme push.
Every check here fails on 5.43.2.

    python3 test/hunt5433_tls.py

  * a certificate put in while root is busy (or not there): nothing is put
    in, and nothing of the card's settings is changed either - "how" said
    "uploaded" of the CA's certificate still in place, so ACME stopped
    renewing it; an order that could not be handed to root left "a
    certificate from before" to go back to that root never kept; the same on
    the cards of the server in front, by hand and by ACME;
  * a name longer than 64 characters ordered: the request goes without a CN
    (openssl refused it: "string too long"), its name in the subjectAltName;
  * a name under an internationalised top-level domain (xn--p1ai) taken;
  * a look at the server in front that failed after one that worked is not
    tried again at every chore and page - only once its five minutes are up;
  * DH parameters made for the server in front last time, for a block that
    does not name them yet (another name chosen there): made and put there,
    not named in nginx without the file;
  * a work folder of Automatic certificates left by a daemon stopped in the
    middle of an order (the account's key in it) taken away by the next one.

No ports, no servers: the daemon's and root's functions called as they are,
root's SSH stood in for.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-hunt5433-tls-'))
STATE = W / 'state'
(STATE / 'root').mkdir(parents=True)
bad = []
NAME = 'zigmon.house.example'


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def finish():
    shutil.rmtree(str(W), ignore_errors=True)
    print('hunt5433_tls: %s' % ('%d failed' % len(bad) if bad else 'all good'))
    sys.exit(1 if bad else 0)


os.environ.update(ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(W / 'own'), ZIGMON_NO_SERVICES='1',
                  ZIGMON_CERT_DIR=str(W / 'certs'), ZIGMON_NGINX_CONF=str(W / 'none.conf'),
                  ZIGMON_MOSQ_DIR=str(W / 'mosq'))
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

spec = importlib.util.spec_from_file_location('zigmon_root_hunt', str(HERE / 'deploy' / 'zigmon_root.py'))
root = importlib.util.module_from_spec(spec)
spec.loader.exec_module(root)

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'h.db'), 'state_dir': str(STATE), 'plugs': [], 'sensors': [],
                      'mqtt_host': '', 'log_file': '', 'token_file': str(W / 'token'), 'acme': 1,
                      'acme_key': 'ec', 'acme_challenge': 'dns-01', 'proxy_host': ''})
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
LOOK = {'tls': {'server_name': NAME, 'files': {}, 'info': {'cn': NAME, 'san': [NAME], 'subject': 'CN=' + NAME,
                                                          'issuer': 'CN=Own CA', 'not_after': time.time() + 86400 * 40}},
        'acme': {'before': None}}
d.root_look = lambda fresh=False: LOOK
d.root_installed = lambda: True
d.root_busy = lambda: False


def busy(*a, **k):
    raise ValueError('root is still busy with what was asked a moment ago - try again when that is done')


d.root_ask = busy
PEM, _cn, _days = d.tls_selfsigned_pem({'cn': NAME, 'kind': 'ec'})
UPLOAD = PEM['cert'] + PEM['key']


# ---- 1. this machine: a certificate root was never asked to put in --------------------
print('this machine: put in while root is busy')
d.tls_save({'managed': True, 'how': 'ACME', 'protocols': ['TLSv1.2', 'TLSv1.3'], 'dh': 'none'})
try:
    d.tls_put(dict(PEM), 'one uploaded')
    check(False, 'tls_put did not say root was busy')
except ValueError:
    pass
check(d.tls_conf().get('how') == 'ACME',
      'an upload root never took left "how" as %r: the CA\'s certificate in place was taken for one '
      'uploaded by hand and ACME stopped renewing it' % d.tls_conf().get('how'))
check(zigmon.acme_care(d), 'ACME no longer looks after the certificate after an upload that never happened')

# the same for the API's upload: the error, and the settings as they were
d.tls_save({'managed': False})
try:
    d.tls_put(dict(PEM), 'one uploaded')
except ValueError:
    pass
check(not d.tls_conf().get('managed') and not d.tls_conf().get('how'),
      'an upload root never took switched zigmon\'s TLS on (managed) with "how" %r' % d.tls_conf().get('how'))


# ---- 2. an order of ACME root could not be handed -------------------------------------
print('Automatic certificates: an order root could not be handed')


class FakeAcme(object):
    def __init__(self, d):
        self.d = d

    def order(self, names, say, kind=None):
        pem, _c, _n = d.tls_selfsigned_pem({'cn': names[0], 'kind': 'ec'})
        return pem['key'], pem['cert']

    def close(self):
        pass


real_acme = zigmon.Acme
zigmon.Acme = FakeAcme
d.tls_save({'managed': True, 'how': 'uploaded', 'protocols': ['TLSv1.2', 'TLSv1.3'], 'dh': 'none'})
d.store.forget_meta('acme_before')
try:
    zigmon.acme_order(d, NAME, 'the test')
    check(False, 'an order root was never handed went through')
except zigmon.AcmeError:
    pass
check(not d.store.get_meta('acme_before'),
      'an order root was never handed left a certificate "from before" to go back to, which root never kept')
check(d.tls_conf().get('how') == 'uploaded',
      'an order root was never handed left "how" as %r - the next order kept nothing to go back to'
      % d.tls_conf().get('how'))


# ---- 3. the server in front: by hand and by ACME, root busy ---------------------------
print('the server in front: put there while root is busy')
zigmon.CONFIG['proxy_host'] = 'front.house.example'
zigmon.proxy_tls_ssh = lambda d: {'host': 'front.house.example', 'port': 22, 'user': 'root', 'key': 'k',
                                  'known_hosts': ''}
for w in ('front', 'ntfy'):
    meta = zigmon.PROXY_W[w]['meta']
    for act, body in (('tls_upload', {'cert': UPLOAD}), ('tls_selfsigned', {'cn': 'ntfy.house.example'
                                                                             if w == 'ntfy' else NAME})):
        d.store.set_meta(meta, json.dumps({'how': 'ACME', 'acme_care': True, 'name': 'ntfy.house.example'
                                           if w == 'ntfy' else ''}))
        try:
            zigmon.proxy_tls_post(d, act, dict(body), 'the test', w=w)
            check(False, '%s on %s went through with root busy' % (act, w))
        except ValueError:
            pass
        conf = zigmon.proxy_tls_conf(d, w)
        check(conf.get('how') == 'ACME' and conf.get('acme_care') is True,
              '%s on the card of %s, never handed to root, left how=%r acme_care=%r: its own Automatic '
              'certificates stopped renewing the one there' % (act, w, conf.get('how'), conf.get('acme_care')))

d.store.set_meta('tls_proxy', json.dumps({'how': 'uploaded'}))
zigmon.CONFIG['acme_challenge'] = 'dns-01'
try:
    zigmon.acme_order_proxy(d, 'proxy', 'front.house.example', 'the test')
    check(False, 'an order for the server in front went through with root busy')
except zigmon.AcmeError:
    pass
check(zigmon.proxy_tls_conf(d).get('how') == 'uploaded',
      'an order for the server in front root was never handed left "how" as %r: the uploaded one there '
      'was taken for the CA\'s' % zigmon.proxy_tls_conf(d).get('how'))
zigmon.Acme = real_acme
zigmon.CONFIG['proxy_host'] = ''


# ---- 4. a name longer than a CN holds -----------------------------------------------
print('Automatic certificates: a long name')
long_name = 'a' * 40 + '.' + 'b' * 30 + '.example.com'
work = zigmon.acme_workdir('zigmon-acme-')
try:
    key, der = zigmon.acme_make_request(work, [long_name], 'ec')
    txt = subprocess.run(['openssl', 'req', '-inform', 'DER', '-noout', '-text'], input=der,
                         capture_output=True).stdout.decode()
    check('DNS:' + long_name in txt, 'the request for a long name does not hold it in its subjectAltName')
    check('PRIVATE KEY' in key, 'no key came with the request for a long name')
except zigmon.AcmeError as e:
    check(False, 'a name of %d characters could not be ordered at all: %s' % (len(long_name), e))
shutil.rmtree(work, ignore_errors=True)

# ---- 5. an internationalised top-level domain ------------------------------------------
print('Automatic certificates: IDN names')
for n in ('zigmon.xn--p1ai', 'dum.xn--vermgensberater-ctb', 'xn--bcher-kva.example.cz'):
    check(bool(zigmon.ACME_NAME_RE.match(n)), '%s is refused as a name a CA gives a certificate for' % n)
for n in ('zigmon.xn--', 'zigmon.123', 'zigmon', '*.example.cz'):
    check(not zigmon.ACME_NAME_RE.match(n), '%s is taken as a full DNS name' % n)

# ---- 6. a failed look at the server in front, not asked again at once -------------------
print('the server in front: a look that failed')
zigmon.CONFIG['proxy_host'] = 'front.house.example'
calls = []
real_read = zigmon.proxy_tls_read


def read(d, w='front'):
    calls.append(w)
    raise ValueError('ssh: connect to host front.house.example port 22: No route to host')


zigmon.proxy_tls_read = read
now = time.time()
d._proxy_tls_look = {'at': int(now - 3000), 'ok': False, 'error': 'down', 'tried': int(now - 20),
                     'info': {'cn': NAME}}
d._proxy_tls_looking = False
for _ in range(3):
    zigmon.proxy_tls_look(d)
time.sleep(0.3)
check(not calls, 'the server in front was asked again %d time(s) 20 s after a look that failed, because '
      'the one before that had worked: over SSH at every chore and page while it is down' % len(calls))
d._proxy_tls_look = dict(d._proxy_tls_look, tried=int(now - 400))
zigmon.proxy_tls_look(d)
time.sleep(0.3)
check(len(calls) == 1, 'a look that failed five minutes ago is not tried again')
zigmon.proxy_tls_read = real_read
zigmon.CONFIG['proxy_host'] = ''

# ---- 7. root: DH parameters for a block there that does not name them ------------------
print('root: DH parameters for the server in front')
DUMP = '''# configuration file /etc/nginx/nginx.conf:
events {}
http { include /etc/nginx/conf.d/*.conf; }

# configuration file /etc/nginx/conf.d/front.conf:
server {
    listen 443 ssl;
    server_name other.house.example;
    ssl_certificate /etc/nginx/certs/other.pem;
    ssl_certificate_key /etc/nginx/certs/other.key;
    location / { proxy_pass https://192.168.1.10; }
}
'''
PUT = []
root.proxy_ssh = lambda ssh, command, data=b'': (0, DUMP, '')
root.proxy_put = lambda ssh, put, fp_of=None: PUT.append(list(put)) or 'ZIGMON-DONE'
raw = {'ssh': {'host': 'front.house.example', 'user': 'root', 'port': 22,
               'key': '-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----\n'},
       'name': 'other.house.example', 'op': 'apply', 'dh_had': 'ffdhe2048',
       'tls': {'protocols': ['TLSv1.2', 'TLSv1.3'], 'ciphers': '', 'prefer': False, 'dh': 'ffdhe2048', 'hsts': 0}}
try:
    root.tls_proxy(raw)
    paths = [p for one in PUT for _data, _m, p in one]
    conf = [data for one in PUT for data, _m, p in one if p.endswith('front.conf')]
    named = bool(conf) and 'ssl_dhparam' in conf[0] and '/etc/nginx/certs/zigmon-dh.pem' in conf[0]
    check(not named or '/etc/nginx/certs/zigmon-dh.pem' in paths,
          'a block there that did not name DH parameters got ssl_dhparam for a file never put there '
          '(made last time for another block): nginx -t refused every putting-in')
except root.Refused as e:
    check(False, 'root refused the DH parameters there: %s' % e)

# ---- 8. a work folder left by a daemon stopped in the middle of an order ----------------
print('Automatic certificates: a folder left behind')
old = STATE / 'zigmon-acme-leftover'
old.mkdir()
(old / 'account.pem').write_text('-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n')
os.utime(str(old), (time.time() - 86400, time.time() - 86400))
fresh = STATE / 'zigmon-acme-going'
fresh.mkdir()
new = zigmon.acme_workdir('zigmon-acme-')
check(not old.exists(), 'a work folder left by an order cut short (the account\'s key in it) stays for good')
check(fresh.exists(), 'a work folder of a moment ago was taken away')
shutil.rmtree(new, ignore_errors=True)
shutil.rmtree(str(fresh), ignore_errors=True)

# ---- 9. the page: a certificate in DER, chosen or in a CA's ZIP -------------------------
print('the page: a DER certificate among the files')
if shutil.which('node'):
    page = (HERE / 'web' / 'index.php').read_text()
    starts = [i for i in (page.find('function certDerPem('), page.find('function certFileOf(')) if i >= 0]
    code = page[min(starts):page.index('function readCertFiles(')]
    (W / 'c.pem').write_text(PEM['cert'])
    (W / 'k.pem').write_text(PEM['key'])
    subprocess.run(['openssl', 'x509', '-in', str(W / 'c.pem'), '-outform', 'DER', '-out', str(W / 'a.cer')],
                   capture_output=True, stdin=subprocess.DEVNULL)
    subprocess.run(['openssl', 'pkcs12', '-export', '-passout', 'pass:abcd', '-in', str(W / 'c.pem'),
                    '-inkey', str(W / 'k.pem'), '-out', str(W / 'b.pfx')], capture_output=True,
                   stdin=subprocess.DEVNULL)
    (W / 'files.js').write_text(code + '''
var fs = require('fs');
var der = new Uint8Array(fs.readFileSync(process.argv[2])), pfx = new Uint8Array(fs.readFileSync(process.argv[3]));
console.log(JSON.stringify([certFileOf('a.cer', der), certFileOf('b.pfx', pfx)]));
''')
    got = subprocess.run(['node', str(W / 'files.js'), str(W / 'a.cer'), str(W / 'b.pfx')],
                         capture_output=True, text=True, stdin=subprocess.DEVNULL)
    try:
        a, b = json.loads(got.stdout)
    except ValueError:
        a, b = {}, {}
        check(False, 'the page\'s file reading did not run: %s' % got.stderr[-300:])
    check('-----BEGIN CERTIFICATE-----' in (a.get('pem') or '') and not a.get('pfx'),
          'a certificate in DER (.cer) went to the daemon as a PFX: the upload was refused with "the PFX '
          'file does not open with that password"')
    if a.get('pem'):
        fp = [subprocess.run(['openssl', 'x509', '-noout', '-fingerprint', '-sha256'], input=x.encode(),
                             capture_output=True).stdout for x in (a['pem'], PEM['cert'])]
        check(fp[0] and fp[0] == fp[1], 'the DER certificate made into PEM on the page is not the same one')
    check(bool(b.get('pfx')) and not b.get('pem'), 'a PFX is no longer sent as a PFX')
else:
    print('  (no node - the page\'s part not tried)')

finish()
