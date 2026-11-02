#!/usr/bin/env python3
"""5.41: ntfy's certificate on the server in front - the third card on
Certificates, beside the front's. The server in front holds two: the one of
the one-tap front (the dashboard's name, 5.33) and ntfy's, in a server
block and files of its own. Fails on 5.40 (no such thing).

  * root (deploy/zigmon_root.py) over SSH - ssh and nginx stood in for by
    scripts over a folder laid out as the real proxy's /etc/nginx
    (conf.d/nginx-tap-front.conf, conf.d/nginx-ntfy-front.conf): ntfy's
    certificate, key and TLS settings put in ntfy's server block and files
    only, the front's untouched - and the front's put in without touching
    ntfy's; following this machine never touches ntfy's; nginx -t saying no
    leaves every file as it was; a password-only server, a key of another
    certificate, ntfy's block serving the front's files, "the certificate of
    this machine" for ntfy - all refused; port 80 of ntfy's name handed to
    this machine for the CA's HTTP-01 question and put back byte for byte;
  * the daemon: ntfy's block told apart from nginx -T (no second HTTPS
    server: said; one serving the front's files: said); every button of the
    card goes to root as tls_proxy_ntfy, its key never kept here; no follow
    for it; Automatic certificates in both layouts - "the same certificate
    as this machine" off: three certificates (this machine with the broker,
    the front, ntfy), on: two (this machine with the broker and the front,
    and ntfy) - each ordered and kept apart, the broker always this
    machine's, after a renewal and after acme pushes to node:<this>;
  * acme push: an `ntfy` slot (kind front, never following), shown in What
    acme sees here, installed into ntfy's files only;
  * the page in Chromium (php -S + Playwright): the third card right after
    the front's, without the switch of following this machine.

    python3 test/proxyntfy.py

Ports 19615 (the daemon) and 19616 (php -S).
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-proxyntfy-check-'))
API_PORT, PHP_PORT = 19615, 19616
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def sh(cmd, data=None, **kw):
    return subprocess.run(cmd, input=data, capture_output=True, text=True,
                          stdin=None if data else subprocess.DEVNULL, **kw)


# ---- certificates of the test's own ------------------------------------------
CA = W / 'ca'
CA.mkdir()
sh(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(CA / 'ca.key'), '-out',
    str(CA / 'ca.pem'), '-days', '30', '-subj', '/CN=Test Root'])
sh(['openssl', 'req', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(CA / 'int.key'), '-out', str(CA / 'int.csr'),
    '-subj', '/CN=Test Intermediate'])
(CA / 'ext').write_text('basicConstraints=critical,CA:TRUE\nkeyUsage=keyCertSign,cRLSign\n')
sh(['openssl', 'x509', '-req', '-in', str(CA / 'int.csr'), '-CA', str(CA / 'ca.pem'), '-CAkey', str(CA / 'ca.key'),
    '-CAcreateserial', '-out', str(CA / 'int.pem'), '-days', '30', '-extfile', str(CA / 'ext')])
N_LEAF = [0]


def leaf(cn):
    N_LEAF[0] += 1
    name = 'leaf%d' % N_LEAF[0]
    sh(['openssl', 'req', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(CA / (name + '.key')),
        '-out', str(CA / (name + '.csr')), '-subj', '/CN=%s' % cn])
    (CA / (name + '.ext')).write_text('subjectAltName=DNS:%s\n' % cn)
    sh(['openssl', 'x509', '-req', '-in', str(CA / (name + '.csr')), '-CA', str(CA / 'int.pem'),
        '-CAkey', str(CA / 'int.key'), '-CAcreateserial', '-out', str(CA / (name + '.pem')), '-days', '20',
        '-extfile', str(CA / (name + '.ext'))])
    return (CA / (name + '.pem')).read_text(), (CA / (name + '.key')).read_text()


NAME = 'mqtt.house.example'
NTFY = 'ntfy.house.example'
FRONT_CERT, FRONT_KEY = leaf(NAME)
NTFY_CERT, NTFY_KEY = leaf(NTFY)
NTFY_NEW, NTFY_NEW_KEY = leaf(NTFY)
FRONT_NEW, FRONT_NEW_KEY = leaf(NAME)
HERE_CERT, HERE_KEY = leaf(NAME)
INT = (CA / 'int.pem').read_text()
ROOT = (CA / 'ca.pem').read_text()


def fp(pem):
    out = sh(['openssl', 'x509', '-noout', '-fingerprint', '-sha256'], pem).stdout
    return out.strip().split('=', 1)[-1].replace(':', '').lower()


# ---- the server in front, as a folder laid out as the real one ---------------------
P = W / 'proxy'
CERTS = P / 'etc' / 'nginx' / 'certs'
CONFD = P / 'etc' / 'nginx' / 'conf.d'
CERTS.mkdir(parents=True)
CONFD.mkdir(parents=True)
TAP = '''limit_req_zone $binary_remote_addr zone=tap_front:1m rate=60r/m;

server {
    listen      443 ssl default_server;
    listen      [::]:443 ssl default_server;
    server_name _;
    server_tokens off;
    ssl_certificate           %(c)s/server.pem;
    ssl_certificate_key       %(c)s/server.key;
    ssl_protocols             TLSv1.2 TLSv1.3;
    return 444;
}

server {
    listen      80 default_server;
    server_name _;
    return 444;                                   # close it without a word
}

server {
    listen      80;
    listen      [::]:80;
    server_name %(n)s;                 # <- your hostname
    server_tokens off;
    return 301 https://$host$request_uri;
}

server {
    listen      443 ssl http2;
    listen      [::]:443 ssl http2;
    server_name %(n)s;                 # <- your hostname
    ssl_certificate           %(c)s/server.pem;
    ssl_certificate_key       %(c)s/server.key;
    ssl_protocols             TLSv1.2 TLSv1.3;
    ssl_stapling              on;
    ssl_stapling_verify       on;
    ssl_trusted_certificate   %(c)s/server.ca;
    add_header Strict-Transport-Security "max-age=63072000" always;
    location / { return 404; }
    location = /tap {
        proxy_pass https://192.0.2.10/tap;               # <- the home server
        proxy_set_header Host             %(n)s;
    }
}
'''
NTFY_CONF = '''limit_req_zone $binary_remote_addr zone=ntfy_front:1m rate=120r/m;

server {
    listen      80;
    listen      [::]:80;
    server_name %(t)s;                 # <- the ntfy name
    server_tokens off;
    return 301 https://$host$request_uri;
}

server {
    listen      443 ssl http2;
    listen      [::]:443 ssl http2;
    server_name %(t)s;                 # <- the ntfy name
    server_tokens off;
    ssl_certificate           %(c)s/ntfy.pem;
    ssl_certificate_key       %(c)s/ntfy.key;
    ssl_protocols             TLSv1.2 TLSv1.3;
    ssl_session_cache         shared:NTFYFRONT:10m;
    add_header Strict-Transport-Security "max-age=63072000" always;
    location / {
        proxy_pass http://127.0.0.1:2586;
        proxy_http_version 1.1;
    }
}
'''


def lay_proxy(ntfy=True, ntfy_files='ntfy'):
    for f in list(CERTS.iterdir()) + list(CONFD.iterdir()):
        f.unlink()
    (CERTS / 'server.pem').write_text(FRONT_CERT + INT)
    (CERTS / 'server.key').write_text(FRONT_KEY)
    os.chmod(CERTS / 'server.key', 0o600)
    (CERTS / 'server.ca').write_text(INT)
    (CERTS / 'ntfy.pem').write_text(NTFY_CERT + INT)
    (CERTS / 'ntfy.key').write_text(NTFY_KEY)
    os.chmod(CERTS / 'ntfy.key', 0o600)
    v = {'c': str(CERTS), 'n': NAME, 't': NTFY}
    (CONFD / 'nginx-tap-front.conf').write_text(TAP % v)
    if ntfy:
        (CONFD / 'nginx-ntfy-front.conf').write_text(
            (NTFY_CONF % v).replace('/ntfy.pem;', '/%s.pem;' % ntfy_files).replace('/ntfy.key;', '/%s.key;' % (
                ntfy_files)))


def snap(which):
    """The files of one card there: its certificate, key, chain and DH, and its conf."""
    if which == 'front':
        names = ['server.pem', 'server.key', 'server.ca', 'zigmon-dh.pem', 'server-ecdsa.pem', 'server-ecdsa.key']
        conf = CONFD / 'nginx-tap-front.conf'
    else:
        names = ['ntfy.pem', 'ntfy.key', 'ntfy.ca', 'ntfy-dh.pem']
        conf = CONFD / 'nginx-ntfy-front.conf'
    out = {n: (CERTS / n).read_bytes() if (CERTS / n).exists() else None for n in names}
    out['conf'] = conf.read_bytes() if conf.exists() else None
    return out


lay_proxy()
FAKES = W / 'bin'
FAKES.mkdir()
LOG = W / 'proxy.log'
LOG.write_text('')
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
os.environ['PATH'] = '%s:%s' % (FAKES, os.environ['PATH'])

# ---- root -------------------------------------------------------------------
STATE = W / 'state'
(STATE / 'root').mkdir(parents=True)
os.environ.update(ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(W / 'own'), ZIGMON_SSH_BIN=str(FAKES / 'ssh'),
                  ZIGMON_NO_SERVICES='1', ZIGMON_USER='root', ZIGMON_NGINX_CONF=str(W / 'none.conf'))
sys.path.insert(0, str(HERE / 'deploy'))
import zigmon_root as R                                       # noqa: E402

SSH_KEY = '-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----\n'
SSH = {'host': 'proxy.house.example', 'port': 22, 'user': 'root', 'key': SSH_KEY, 'known_hosts': ''}
TLS = {'protocols': ['TLSv1.3'], 'ciphers': '', 'prefer': False, 'dh': 'ffdhe2048', 'hsts': 31536000}


def ask(kind='tls_proxy_ntfy', **kw):
    base = {'kind': kind, 'ssh': dict(SSH), 'op': 'apply'}
    base.update({'name': NTFY, 'front_name': NAME} if kind == 'tls_proxy_ntfy' else {'name': NAME})
    base.update(kw)
    try:
        return R.handle(base), None
    except R.Refused as e:
        return None, str(e)
    except Exception as e:                                   # noqa: BLE001 - an older root: said
        return None, 'broke: %r' % e


print('root: ntfy\'s certificate in ntfy\'s block only')
front0 = snap('front')
got, err = ask(source='given', cert=NTFY_NEW, key=NTFY_NEW_KEY, chain=INT, root=ROOT, tls=TLS)
check(err is None, 'root refused a good certificate for ntfy there: %s' % err)
if got:
    check(got[0]['proxy'].get('fingerprint') == fp(NTFY_NEW) and got[0]['proxy'].get('which') == 'ntfy',
          'root did not say which certificate went to ntfy: %r' % (got[0],))
check(fp((CERTS / 'ntfy.pem').read_text()) == fp(NTFY_NEW) and INT.strip() in (CERTS / 'ntfy.pem').read_text(),
      'ntfy\'s certificate and chain are not in its file')
check((CERTS / 'ntfy.key').read_text().strip() == NTFY_NEW_KEY.strip()
      and oct((CERTS / 'ntfy.key').stat().st_mode & 0o777) == '0o600', 'ntfy\'s key is not the new one (0600)')
check(snap('front') == front0, 'putting ntfy\'s certificate in touched the front\'s files')
nconf = (CONFD / 'nginx-ntfy-front.conf').read_text()
check('ssl_protocols             TLSv1.3;' in nconf and 'ssl_dhparam' in nconf and
      '%s/ntfy-dh.pem' % CERTS in nconf and (CERTS / 'ntfy-dh.pem').is_file(),
      'ntfy\'s TLS settings (TLS 1.3, its own DH file) were not put in its block:\n' + nconf)
check(not (CERTS / 'zigmon-dh.pem').exists(), 'ntfy\'s DH parameters went into the front\'s file')
check('proxy_pass http://127.0.0.1:2586;' in nconf and 'return 301 https://$host$request_uri;' in nconf,
      'what else ntfy\'s file holds was not kept')
check(not (CERTS / 'ntfy.ca').exists(), 'a chain file was written for ntfy, which neither staples nor names one')
check('systemctl reload nginx' in LOG.read_text(), 'nginx there was not reloaded')

print('root: the front\'s without touching ntfy\'s')
lay_proxy()
ntfy0 = snap('ntfy')
got, err = ask('tls_proxy', source='given', cert=FRONT_NEW, key=FRONT_NEW_KEY, chain=INT, root=ROOT, tls=TLS)
check(err is None and fp((CERTS / 'server.pem').read_text()) == fp(FRONT_NEW), 'the front\'s was not put in: %s' % err)
check(snap('ntfy') == ntfy0, 'putting the front\'s certificate in touched ntfy\'s files')

print('root: following this machine never touches ntfy\'s')
lay_proxy()
ntfy0 = snap('ntfy')
real_here, real_now = R.proxy_pem_here, R.tls_now
R.proxy_pem_here = lambda: (HERE_CERT + INT, HERE_KEY)
R.tls_now = lambda: {'files': {}}
got, err = ask('tls_proxy', source='here')
check(err is None and fp((CERTS / 'server.pem').read_text()) == fp(HERE_CERT),
      'the certificate of this machine did not go to the front: %s' % err)
check(snap('ntfy') == ntfy0, 'following this machine touched ntfy\'s files')
got, err = ask(source='here')
check(err and 'never' in err and snap('ntfy') == ntfy0, 'ntfy took the certificate of this machine: %r' % err)
R.proxy_pem_here, R.tls_now = real_here, real_now

print('root: refusals')
lay_proxy()
(W / 'nginx-says-no').write_text('')
was = {f: f.read_bytes() for f in P.rglob('*') if f.is_file()}
got, err = ask(source='given', cert=NTFY_NEW, key=NTFY_NEW_KEY, chain=INT, tls=TLS)
check(err and 'would not take it' in err, 'a configuration nginx refused was not said: %r' % err)
check(was == {f: f.read_bytes() for f in P.rglob('*') if f.is_file()},
      'a configuration nginx refused for ntfy was left in place')
(W / 'nginx-says-no').unlink()
for kw, why in ((dict(ssh=dict(SSH, key='')), 'password'),
                (dict(source='given', cert=NTFY_NEW, key=FRONT_KEY), 'not the one of this certificate'),
                (dict(front_name=''), 'both names'),
                (dict(name='nothere.house.example', tls=TLS), 'no HTTPS server')):
    got, err = ask(**kw)
    check(err and why.lower() in err.lower(), 'not refused for ntfy (%s): %r' % (why, err))
lay_proxy(ntfy_files='server')                 # ntfy's block serves the front's files
was = {f: f.read_bytes() for f in P.rglob('*') if f.is_file()}
got, err = ask(source='given', cert=NTFY_NEW, key=NTFY_NEW_KEY, chain=INT)
check(err and 'same certificate files as the front' in err and
      was == {f: f.read_bytes() for f in P.rglob('*') if f.is_file()},
      'ntfy\'s block serving the front\'s files was written to: %r' % err)
lay_proxy()
got, err = ask(op='export', format='pem_key', password='', with_root=False)
check(err is None, 'ntfy\'s certificate there was not handed over for a download: %s' % err)

print('root: port 80 of ntfy\'s name for the CA')
lay_proxy()
before = (CONFD / 'nginx-ntfy-front.conf').read_text()
front0 = snap('front')
got, err = ask(op='acme_http', on=True)
on = (CONFD / 'nginx-ntfy-front.conf').read_text()
check(err is None and 'location ^~ /.well-known/acme-challenge/' in on and 'proxy_pass http://192.0.2.10;' in on
      and '#zigmon# return 301' in on, 'port 80 of ntfy\'s name does not hand the CA\'s question here: %s\n%s'
      % (err, on))
check(snap('front') == front0, 'port 80 for ntfy changed the front\'s file')
got, err = ask(op='acme_http', on=False)
check(err is None and (CONFD / 'nginx-ntfy-front.conf').read_text() == before,
      'port 80 of ntfy\'s name was not put back as it was: %s' % err)

# ---- the daemon ----------------------------------------------------------------
print('the daemon')
lay_proxy()
LOG.write_text('')
sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                                # noqa: E402

Z = vars(zigmon)
zigmon.load_config()
DSTATE = W / 'dstate'
DSTATE.mkdir()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'log_file': '', 'state_dir': str(DSTATE), 'proxy_host': 'proxy.house.example',
                      'proxy_auth': 'key', 'acme': 0, 'acme_challenge': 'dns-01', 'cert_push': 1})
d = zigmon.Daemon()
d.notify = lambda message, *a, **k: None
d.store.set_meta('proxy_key', SSH_KEY)
HERE_PEM = [HERE_CERT + INT]


def here_info():
    return zigmon.cert_info_pem(d, HERE_PEM[0])


d.root_look = lambda fresh=False: {'tls': {'server_name': NAME, 'broker': ['/etc/mosquitto/conf.d/zigmon.conf'],
                                           'info': here_info(), 'files': {}}}
d.proxy_run = lambda command: subprocess.run(['sh', '-c', command], capture_output=True, text=True).stdout
d.tls_pem_now = lambda: HERE_PEM[0]
d.root_installed = lambda: True
d.root_busy = lambda: False
ASKED = []
STATUS = [{}]


def root_ask(kind, body=None, quiet=False):
    """Root, as it would answer: its own handler, over the folder."""
    ident = 'r%d' % (len(ASKED) + 1)
    ASKED.append((kind, dict(body or {})))
    d.__dict__.setdefault('_root_kinds', {})[ident] = kind
    if kind in ('tls_proxy', 'tls_proxy_ntfy'):
        try:
            fields, said = R.handle(dict(body or {}, kind=kind))
            STATUS[0] = dict(fields, id=ident, kind=kind, state='done', said=said)
        except R.Refused as e:
            STATUS[0] = {'id': ident, 'kind': kind, 'state': 'failed', 'said': [str(e)]}
    else:
        STATUS[0] = {'id': ident, 'kind': kind, 'state': 'done', 'said': []}
    return ident


d.root_ask = root_ask
d.root_read = lambda name: dict(STATUS[0]) if name == 'status.json' else {}
TLS_PUT = []


def tls_put(pem, why='', how=None, **kw):
    """This machine's certificate put in by root: the broker reads the same files."""
    TLS_PUT.append((why, how))
    HERE_PEM[0] = pem['cert'] + (pem.get('chain') or '')
    conf = d.tls_conf()
    if how:
        conf['how'] = how
    d.tls_save(conf)
    return root_ask('apply', {})


d.tls_put = tls_put
d._proxy_tls_looking = d._proxy_ntfy_looking = True          # looks are made by the test, not a thread


def relook():
    d._proxy_tls_look = zigmon.proxy_tls_read(d)
    d._proxy_ntfy_look = zigmon.proxy_tls_read(d, 'ntfy')


def kinds():
    return [k for k, _ in ASKED]


try:
    relook()
    nl = d._proxy_ntfy_look
except Exception as e:                                       # noqa: BLE001 - an older zigmon: said
    nl = {}
    check(False, 'the daemon does not read ntfy\'s block there: %r' % e)
check(nl.get('name') == NTFY and (nl.get('info') or {}).get('fingerprint') == fp(NTFY_CERT),
      'the ntfy card does not read ntfy\'s certificate from nginx -T: %r' % ({k: nl.get(k) for k in ('name', 'error')},))
check(nl.get('blocks') == 1 and str((nl.get('files') or {}).get('cert')).endswith('/ntfy.pem') and not nl.get('shared'),
      'ntfy\'s block and files were not read: %r' % ({k: nl.get(k) for k in ('blocks', 'files')},))
check(d._proxy_tls_look.get('info', {}).get('fingerprint') == fp(FRONT_CERT), 'the front\'s card reads another one')
st = d.tls_state() if hasattr(d, 'tls_state') else {}
pn = st.get('proxy_ntfy') or {}
check(pn.get('which') == 'ntfy' and pn.get('name') == NTFY and (pn.get('look') or {}).get('info'),
      'the page is not given the ntfy card: %r' % (sorted(pn) if pn else None,))
check('pem' not in (pn.get('look') or {}), 'the card\'s look carries the certificate file to the page')
# no second HTTPS server: said, nothing offered; one serving the front's files: said
lay_proxy(ntfy=False)
try:
    none = zigmon.proxy_tls_read(d, 'ntfy')
except Exception as e:                                       # noqa: BLE001
    none = {'error': repr(e)}
check(none.get('none') is True and not none.get('info'), 'no second HTTPS server there is not said: %r' % none)
lay_proxy(ntfy_files='server')
try:
    shared = zigmon.proxy_tls_read(d, 'ntfy')
except Exception as e:                                       # noqa: BLE001
    shared = {'error': repr(e)}
check(shared.get('shared') is True, 'ntfy served the front\'s files is not said: %r' % shared.get('error'))
lay_proxy()
relook()

# every button of the card goes there as ntfy's; its key never kept here
pf = Z.get('proxy_tls_post')
ASKED.clear()
try:
    pf(d, 'tls_upload', {'cert': NTFY_NEW + INT + NTFY_NEW_KEY}, 'test', w='ntfy')
except TypeError as e:
    check(False, 'the card\'s buttons cannot be for ntfy: %s' % e)
k, body = ASKED[-1] if ASKED else ('', {})
check(k == 'tls_proxy_ntfy' and body.get('name') == NTFY and body.get('front_name') == NAME
      and fp(body.get('cert') or '') == fp(NTFY_NEW), 'an upload for ntfy did not go to root as ntfy\'s: %r' % k)
check(fp((CERTS / 'ntfy.pem').read_text()) == fp(NTFY_NEW) and fp((CERTS / 'server.pem').read_text()) == fp(FRONT_CERT),
      'the upload for ntfy did not end in ntfy\'s file alone')
held = [f for f in DSTATE.rglob('*') if f.is_file() and b'PRIVATE KEY' in f.read_bytes() and 'pending' not in f.name]
meta = json.dumps({k2: d.store.get_meta(k2) for k2 in ('tls_proxy', 'tls_proxy_ntfy')})
check(not held and 'PRIVATE KEY' not in meta, 'ntfy\'s key was kept by the daemon: %r' % held)
check('PRIVATE KEY' not in d.store.get_meta('tls_proxy_ntfy') or '', 'the key is in ntfy\'s settings')
for act, b in (('tls_policy', {'preset': 'modern', 'dh': 'none', 'hsts': 0}), ('tls_export', {'format': 'pem_key'})):
    ASKED.clear()
    try:
        pf(d, act, b, 'test', w='ntfy')
    except (TypeError, ValueError) as e:
        check(False, '%s for ntfy: %s' % (act, e))
    check(ASKED and ASKED[-1][0] == 'tls_proxy_ntfy', '%s for ntfy did not go to root as ntfy\'s' % act)
check(zigmon.proxy_tls_conf(d, 'ntfy')['managed'] and not zigmon.proxy_tls_conf(d)['managed'],
      'ntfy\'s TLS settings were taken for the front\'s')
csr = pf(d, 'tls_csr', {'cn': NTFY}, 'test', w='ntfy')['csr']
check('CERTIFICATE REQUEST' in csr and (DSTATE / 'tls' / 'proxy-ntfy-pending.key').is_file()
      and not zigmon.proxy_tls_conf(d).get('pending'), 'ntfy\'s request was not kept apart')
pf(d, 'tls_csr_drop', {}, 'test', w='ntfy')
plain = pf(d, 'tls_get', {'format': 'pem_cert'}, 'test', w='ntfy')
check(fp(plain['text']) == fp(NTFY_CERT) and plain['name'].endswith('-ntfy'), 'ntfy\'s download is another one')
for act in ('proxy_follow', 'proxy_push'):
    try:
        pf(d, act, {'on': True}, 'test', w='ntfy')
        check(False, '%s was taken for ntfy' % act)
    except ValueError:
        pass
check(not zigmon.proxy_tls_conf(d, 'ntfy')['follow'], 'ntfy follows this machine')

# following this machine: the front only, by the half-minute chore too
relook()
ASKED.clear()
n0 = snap('ntfy')
pf(d, 'proxy_follow', {'on': True}, 'test')
c = zigmon.proxy_tls_conf(d)
c['pushed'] = ''
zigmon.proxy_tls_save(d, c)
relook()
d._proxy_tls_look['info']['fingerprint'] = 'f' * 64
zigmon.proxy_tls_tick(d)
check(ASKED and set(kinds()) == {'tls_proxy'} and all(b.get('source') == 'here' for _, b in ASKED),
      'following this machine asked for something else than the front: %r' % kinds())
check(snap('ntfy') == n0, 'following this machine touched ntfy\'s files')
pf(d, 'proxy_follow', {'on': False}, 'test')

# ---- Automatic certificates, both layouts -----------------------------------------
print('Automatic certificates')


class FakeAcme(object):
    """The CA at its last step: a certificate of the test's CA for the name."""
    orders = []
    port80 = []

    def __init__(self, d):
        pass

    def order(self, names, say, key_kind=None):
        FakeAcme.orders.append(list(names))
        FakeAcme.port80.append('acme-challenge' in (CONFD / 'nginx-ntfy-front.conf').read_text())
        cert, key = leaf(names[0])
        return key, cert + INT

    def close(self):
        pass


zigmon.Acme = FakeAcme
zigmon.CONFIG['acme'] = 1
d.store.set_meta('acme_care', json.dumps({'on': True, 'at': time.time(), 'by': 'test'}))
post = Z.get('acme_post')
for w, t in (('front', 'proxy'), ('ntfy', 'proxy-ntfy')):
    try:
        post(d, {'action': 'care', 'target': t, 'on': True}, 'test')
    except ValueError as e:
        check(False, 'Look after it for %s: %s' % (t, e))


def targets():
    return [t for t, _ in zigmon.acme_targets(d)]


def view_targets():
    return [t.get('target') for t in zigmon.acme_view(d).get('targets') or []]


def broker_follows(what):
    slots = {s['id']: s for s in zigmon.push_slots(d)}
    node, broker = slots.get('node:' + zigmon.push_node()) or {}, slots.get('broker') or {}
    check(broker.get('managed_by') == 'follows:node:' + zigmon.push_node() and
          (broker.get('current') or {}).get('fingerprint') == (node.get('current') or {}).get('fingerprint')
          == fp(HERE_PEM[0]), 'the broker does not have this machine\'s certificate %s' % what)
    return slots


for follow in (False, True):
    lay_proxy()
    zigmon.proxy_tls_save(d, dict(zigmon.proxy_tls_conf(d), follow=follow))
    relook()
    layout = 'with the front following this machine' if follow else 'with three of their own'
    want = ['web', 'proxy-ntfy'] if follow else ['web', 'proxy', 'proxy-ntfy']
    check(targets() == want and view_targets() == want,
          'Automatic certificates %s: %r / %r, not %r' % (layout, targets(), view_targets(), want))
    names = dict(zigmon.acme_targets(d))
    check(names.get('proxy-ntfy') == NTFY and names.get('web') == NAME and (follow or names.get('proxy') == NAME),
          'the names ordered for %s: %r' % (layout, names))
    # ntfy's ordered: its file there, nothing else
    f0, here0 = snap('front'), HERE_PEM[0]
    FakeAcme.orders[:] = []
    try:
        zigmon.acme_order(d, NTFY, 'test', target='proxy-ntfy')
    except Exception as e:                                   # noqa: BLE001
        check(False, 'ntfy\'s certificate was not ordered %s: %s' % (layout, e))
    relook()
    nst = zigmon.acme_state(d, 'proxy-ntfy')
    check(FakeAcme.orders == [[NTFY]] and nst.get('ok') and nst.get('name') == NTFY,
          'ntfy\'s order %s: %r %r' % (layout, FakeAcme.orders, nst.get('said')))
    check((d._proxy_ntfy_look.get('info') or {}).get('san') == [NTFY] and
          fp((CERTS / 'ntfy.pem').read_text()) != fp(NTFY_CERT), 'ntfy\'s ordered certificate is not there')
    check(snap('front') == f0 and HERE_PEM[0] == here0, 'ntfy\'s order touched the front or this machine')
    check(zigmon.proxy_tls_conf(d, 'ntfy').get('how') == 'ACME' and zigmon.acme_state(d).get('name') != NTFY,
          'ntfy\'s ACME state is not its own')
    # this machine's renewed: the broker with it, ntfy's untouched
    n0 = snap('ntfy')
    try:
        zigmon.acme_order(d, NAME, 'test')
    except Exception as e:                                   # noqa: BLE001
        check(False, 'this machine\'s certificate was not ordered %s: %s' % (layout, e))
    check(TLS_PUT and TLS_PUT[-1][1] == 'ACME' and snap('ntfy') == n0, 'this machine\'s renewal %s' % layout)
    broker_follows('after a renewal by ACME, %s' % layout)
    if not follow:
        n0 = snap('ntfy')
        try:
            zigmon.acme_order(d, NAME, 'test', target='proxy')
        except Exception as e:                               # noqa: BLE001
            check(False, 'the front\'s own certificate was not ordered: %s' % e)
        check(zigmon.acme_state(d, 'proxy').get('ok') and snap('ntfy') == n0 and
              fp((CERTS / 'server.pem').read_text()) != fp(FRONT_CERT), 'the front\'s own order touched ntfy\'s')
    else:
        try:
            post(d, {'action': 'order', 'target': 'proxy'}, 'test')
            check(False, 'an order for the front was taken while it follows this machine')
        except ValueError:
            pass

# by HTTP-01: port 80 of ntfy's name there for the order, and back after it
lay_proxy()
zigmon.proxy_tls_save(d, dict(zigmon.proxy_tls_conf(d), follow=False))
relook()
zigmon.CONFIG['acme_challenge'] = 'http-01'
before = (CONFD / 'nginx-ntfy-front.conf').read_text()
ASKED.clear()
FakeAcme.port80[:] = []
try:
    zigmon.acme_order(d, NTFY, 'test', target='proxy-ntfy')
except Exception as e:                                       # noqa: BLE001
    check(False, 'ntfy\'s order by HTTP-01: %s' % e)
ops = [(k, b.get('op'), b.get('on')) for k, b in ASKED]
check(FakeAcme.port80 == [True] and ops == [('tls_proxy_ntfy', 'acme_http', True), ('tls_proxy_ntfy', 'apply', None),
                                            ('tls_proxy_ntfy', 'acme_http', False)],
      'port 80 there was not opened for the order and closed after it: %r %r' % (FakeAcme.port80, ops))
after = (CONFD / 'nginx-ntfy-front.conf').read_text()
check(after.count('acme-challenge') == 0 and 'return 301 https://$host$request_uri;' in after,
      'port 80 of ntfy\'s name was left handing the CA\'s question here')
zigmon.CONFIG['acme_challenge'] = 'dns-01'

# ---- acme push: the ntfy slot ------------------------------------------------------
print('acme push')
lay_proxy()
relook()
zigmon.push_keys = lambda d: [{'key_id': '0123456789abcdef', 'name': 'acme', 'pub': ''}]
zigmon.push_signed = lambda d, op, raw, headers, app_id: {'key_id': '0123456789abcdef', 'nonce': 'n' * 16}
zigmon.push_open_key = lambda sealed, priv, app_id, fingerprint: sealed


def push(cert, key, slots):
    b = {'slots': slots, 'cert_pem': cert, 'chain_pem': INT, 'fingerprint': fp(cert), 'key': key,
         'check_names': True}
    try:
        return zigmon.push_install(d, json.dumps(b).encode(), {})
    except zigmon.PushRefused as e:
        return {'error': '%s %s' % (e.args[:2] if e.args else '', e)}


for follow in (False, True):
    zigmon.proxy_tls_save(d, dict(zigmon.proxy_tls_conf(d), follow=follow))
    relook()
    slots = {s['id']: s for s in zigmon.push_slots(d)}
    ns = slots.get('ntfy') or {}
    check(ns.get('kind') == 'front' and ns.get('names') == [NTFY] and ns.get('installable') and
          not str(ns.get('managed_by')).startswith('follows') and
          (ns.get('current') or {}).get('fingerprint') == fp((CERTS / 'ntfy.pem').read_text()),
          'the ntfy slot (front %s): %r' % ('following' if follow else 'its own', ns))
    check((slots.get('front') or {}).get('managed_by', '').startswith('follows') == follow,
          'the front slot changed its following: %r' % slots.get('front'))
    check('ntfy' in zigmon.push_hello(d).get('slots', []), 'hello does not name the ntfy slot')
    # a push to ntfy: its files only
    f0, here0 = snap('front'), HERE_PEM[0]
    cert, key = leaf(NTFY)
    out = push(cert, key, ['ntfy'])
    check([r.get('slot') for r in out.get('installed') or []] == ['ntfy'] and
          fp((CERTS / 'ntfy.pem').read_text()) == fp(cert), 'a push to the ntfy slot: %r' % out)
    check(snap('front') == f0 and HERE_PEM[0] == here0, 'a push to ntfy touched the front or this machine')
    check(zigmon.proxy_tls_conf(d, 'ntfy').get('how', '').startswith('acme push') and
          not zigmon.proxy_tls_conf(d).get('how', '').startswith('acme push'), 'the push was kept as the front\'s')
    # auto, a certificate of ntfy's name: the ntfy slot alone
    relook()
    cert, key = leaf(NTFY)
    out = push(cert, key, ['auto'])
    check([r.get('slot') for r in out.get('installed') or []] == ['ntfy'], 'auto with ntfy\'s name: %r' % out)
    # node:<this>: the broker with it, ntfy's untouched
    relook()
    n0 = snap('ntfy')
    cert, key = leaf(NAME)
    out = push(cert, key, ['node:' + zigmon.push_node()])
    check(not out.get('error') and snap('ntfy') == n0, 'a push to this machine: %r' % out)
    broker_follows('after a push to node:%s, %s' % (zigmon.push_node(), 'following' if follow else 'its own'))
zigmon.proxy_tls_save(d, dict(zigmon.proxy_tls_conf(d), follow=False))

# ---- the page ----------------------------------------------------------------
print('the page')
page = (HERE / 'web' / 'index.php').read_text()
check("proxyView(d, 'ntfy')" in page and "'proxy-ntfy'" in page, 'the page has no third card')
lay_proxy()
relook()
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)
try:
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    import urllib.request                                    # noqa: E402
    req = urllib.request.Request('http://127.0.0.1:%d/api/auth/login' % API_PORT,
                                 data=json.dumps({'name': 'owner', 'password': 'owner pass 12'}).encode(),
                                 headers={'X-Zigmon-Token': d.token, 'Content-Type': 'application/json',
                                          'X-Zigmon-Client': '192.168.40.10'}, method='POST')
    with urllib.request.urlopen(req, timeout=30) as r:
        S = json.loads(r.read()).get('token') or ''
    front_conf0 = (CONFD / 'nginx-tap-front.conf').read_text()
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
  const ctx = await b.newContext({viewport: {width: 1500, height: 1100}});
  await ctx.addCookies([{name: 'zigmon_session', value: %(s)s, url: 'http://127.0.0.1:%(port)d/'}]);
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.goto('http://127.0.0.1:%(port)d/#control/sys-certs');
  await p.waitForTimeout(2500);
  try { await p.evaluate(() => showControlSection('sys-certs')); } catch (e) {}
  await p.waitForSelector('#web-certs .cert-card', {timeout: 15000});
  await p.waitForTimeout(1500);
  const r = {};
  r.cards = await p.evaluate(() => Array.from(document.querySelectorAll('#web-certs .cert-grid > .cert-card')).map(c => ({
    cls: c.className, target: (c.querySelector('.cert-target') || {}).textContent, name: (c.querySelector('.cert-title b') || {}).textContent,
    follow: !!c.querySelector('.cert-follow'), tools: Array.from(c.querySelectorAll('.cert-tools button')).map(x => x.textContent.trim())})));
  // ntfy's TLS settings through its own card's dialog (5.41.0): its ciphers,
  // DH parameters, the server choosing and HSTS, as on every other card
  try {
    await p.click('#web-certs .cert-grid > .cert-card.cert-ntfy .cert-tools button:has-text("TLS settings")');
    await p.waitForSelector('#zmodal:not([hidden]) .tls-tiles', {timeout: 10000});
    r.polTitle = await p.textContent('#zmodal-title');
    await p.click('#zmodal .tls-tile[data-k="custom"]');
    await p.fill('#zmodal textarea.tls-ciphers', 'ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384');
    await p.selectOption('#zmodal .tls-rows select', 'ffdhe3072');
    await p.evaluate(() => { const i = document.querySelector('#zmodal .tls-rows input[type=checkbox]'); i.checked = true; i.dispatchEvent(new Event('change')); });
    await p.click('#zmodal .tls-rows .seg button:has-text("1 year")');
    await p.click('#zmodal-foot button:has-text("Save")');
    await p.waitForSelector('#zmodal', {state: 'hidden', timeout: 30000});
    await p.waitForTimeout(1500);
    r.polDone = true;
  } catch (e) { r.polErr = String(e); }
  try { await p.waitForSelector('#push-box tr[data-slot]', {timeout: 15000}); } catch (e) {}
  r.slots = await p.evaluate(() => Array.from(document.querySelectorAll('#push-box tr[data-slot]')).map(t => t.dataset.slot));
  await p.screenshot({path: %(shot)s, fullPage: false});
  try { await p.evaluate(() => showControlSection('sys-acme')); } catch (e) {}
  try { await p.waitForSelector('#ac-host .ac-node', {timeout: 15000}); } catch (e) {}
  await p.waitForTimeout(1000);
  r.acme = await p.evaluate(() => Array.from(document.querySelectorAll('#ac-host .ac-node .pw-head .ac-who')).map(t => t.textContent));
  r.errors = errors;
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
    (W / 'page.js').write_text(js % {'s': json.dumps(S), 'port': PHP_PORT, 'shot': json.dumps(str(W / 'page.png'))})
    root = sh(['npm', 'root', '-g']).stdout.strip()
    got = sh(['node', str(W / 'page.js')], timeout=180, env=dict(os.environ, NODE_PATH=root))
    try:
        r = json.loads(got.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        r = {'error': (got.stdout + got.stderr)[-300:]}
    if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
        print('  SKIPPED (no browser here): %s' % r['error'][:200])
    else:
        check(not r.get('error'), 'the page in Chromium: %s' % r.get('error'))
        cards = r.get('cards') or []
        check([c.get('target') for c in cards] == ['The dashboard and the broker', 'The server in front',
                                                   'ntfy on the server in front'],
              'the third card is not right after the front\'s: %r' % [c.get('target') for c in cards])
        if len(cards) == 3:
            check(cards[2]['name'] == NTFY and 'cert-ntfy' in cards[2]['cls'], 'the ntfy card: %r' % cards[2])
            check(cards[1]['follow'] and not cards[2]['follow'],
                  'the switch of following this machine is not on the front\'s card alone: %r' % cards)
            check({'Upload', 'TLS settings', 'Download', 'Look again'} <= set(cards[2]['tools']),
                  'the ntfy card lacks the options of the front\'s: %r' % cards[2]['tools'])
        check('ntfy' in (r.get('slots') or []), 'What acme sees here has no ntfy slot: %r' % r.get('slots'))
        nconf = (CONFD / 'nginx-ntfy-front.conf').read_text()
        check(r.get('polDone') and 'ntfy' in (r.get('polTitle') or ''),
              'ntfy\'s TLS settings could not be set from its card: %r %r' % (r.get('polTitle'), r.get('polErr')))
        check(re.search(r'ssl_ciphers\s+ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;', nconf)
              and re.search(r'ssl_prefer_server_ciphers\s+on;', nconf)
              and re.search(r'ssl_dhparam\s+%s/ntfy-dh\.pem;' % re.escape(str(CERTS)), nconf)
              and (CERTS / 'ntfy-dh.pem').is_file() and 'BEGIN DH PARAMETERS' in (CERTS / 'ntfy-dh.pem').read_text()
              and re.search(r'Strict-Transport-Security\s+"max-age=31536000"', nconf),
              'ntfy\'s ciphers, DH parameters, server choosing and HSTS set on its card are not in its block:\n' + nconf)
        check((CONFD / 'nginx-tap-front.conf').read_text() == front_conf0,
              'ntfy\'s TLS settings changed the front\'s block')
        check(r.get('acme') == ['this server', 'the server in front', 'ntfy on the server in front'],
              'Automatic certificates does not show the three certificates: %r' % r.get('acme'))
        check(not r.get('errors'), 'the page threw: %r' % r.get('errors'))
        if os.environ.get('SHOT'):
            shutil.copy(W / 'page.png', os.environ['SHOT'])
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
print('proxyntfy: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
os._exit(1 if bad else 0)
