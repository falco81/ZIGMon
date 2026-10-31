#!/usr/bin/env python3
"""5.33: the certificate on the server in front - the second card on
Certificates, the same as the first. Fails on 5.32.0 (no such thing).

  * root (deploy/zigmon_root.py) over SSH - ssh and nginx stood in for by
    scripts working on a folder laid out like the proxy's /etc/nginx: the
    certificate, its key and its chain put in every server { } that serves
    the dashboard's certificate (the default one too, the one of ntfy not);
    protocols, ciphers, DH parameters and HSTS set there; files kept as they
    were when nginx -t says no; a password-only server refused; a path that
    is not a plain one refused; the key the certificate's own;
  * the daemon: what the card shows read from nginx -T and the certificate
    there; "the same certificate as this machine" asks root to put the one
    of here there when it differs, and not when it is the same; every button
    of the card goes to the server in front with target=proxy; the
    certificate's key never passes through the daemon for it;
  * the page: the second card, the dialogs saying which machine, the
    download fitting without a scroll bar, the CA's certificate box styled.

    python3 test/proxycert.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-proxycert-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def sh(cmd, data=None):
    return subprocess.run(cmd, input=data, capture_output=True, text=True, stdin=None if data else subprocess.DEVNULL)


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


def leaf(name, cn):
    sh(['openssl', 'req', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(CA / (name + '.key')),
        '-out', str(CA / (name + '.csr')), '-subj', '/CN=%s' % cn])
    (CA / (name + '.ext')).write_text('subjectAltName=DNS:%s\n' % cn)
    sh(['openssl', 'x509', '-req', '-in', str(CA / (name + '.csr')), '-CA', str(CA / 'int.pem'),
        '-CAkey', str(CA / 'int.key'), '-CAcreateserial', '-out', str(CA / (name + '.pem')), '-days', '20',
        '-extfile', str(CA / (name + '.ext'))])
    return (CA / (name + '.pem')).read_text(), (CA / (name + '.key')).read_text()


NAME = 'mqtt.house.example'
OLD_CERT, OLD_KEY = leaf('old', NAME)
NEW_CERT, NEW_KEY = leaf('new', NAME)
NTFY_CERT, NTFY_KEY = leaf('ntfy', 'ntfy.house.example')
INT = (CA / 'int.pem').read_text()
ROOT = (CA / 'ca.pem').read_text()


def fp(pem):
    out = sh(['openssl', 'x509', '-noout', '-fingerprint', '-sha256'], pem).stdout
    return out.strip().split('=', 1)[-1].replace(':', '').lower()


# ---- the server in front, as a folder ------------------------------------------
P = W / 'proxy'
CERTS = P / 'etc' / 'nginx' / 'certs'
CONFD = P / 'etc' / 'nginx' / 'conf.d'
CERTS.mkdir(parents=True)
CONFD.mkdir(parents=True)


def lay_proxy():
    (CERTS / 'server.pem').write_text(OLD_CERT + INT)
    (CERTS / 'server.key').write_text(OLD_KEY)
    os.chmod(CERTS / 'server.key', 0o600)
    (CERTS / 'server.ca').write_text(INT)
    (CERTS / 'ntfy.pem').write_text(NTFY_CERT + INT)
    (CERTS / 'ntfy.key').write_text(NTFY_KEY)
    c = str(CERTS)
    (CONFD / 'tap-front.conf').write_text('''# the one-tap links in front
server {
    listen      443 ssl default_server;
    server_name _;
    ssl_certificate           %(c)s/server.pem;
    ssl_certificate_key       %(c)s/server.key;
    ssl_protocols             TLSv1.2 TLSv1.3;
    return 444;
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
''' % {'c': c, 'n': NAME})
    (CONFD / 'ntfy-front.conf').write_text('''server {
    listen      443 ssl http2;
    server_name ntfy.house.example;
    ssl_certificate           %(c)s/ntfy.pem;
    ssl_certificate_key       %(c)s/ntfy.key;
    ssl_protocols             TLSv1.2 TLSv1.3;
}
''' % {'c': c})
    for f in P.rglob('*.zigmon-before'):
        f.unlink()


lay_proxy()
FAKES = W / 'bin'
FAKES.mkdir()
LOG = W / 'proxy.log'
# ssh: the command run here, its standard input passed on; who it was asked of written down
(FAKES / 'ssh').write_text('''#!/bin/sh
for a; do last="$a"; done
echo "ssh $*" | sed 's/-i [^ ]*/-i KEY/' >> %(log)s
case " $* " in *" -i "*) ;; *) echo "no key" >&2; exit 255;; esac
exec sh -c "$last"
''' % {'log': LOG})
# nginx: -T lays the folder's files out as nginx does; -t says yes unless told no
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


def ask(**kw):
    req = dict({'kind': 'tls_proxy', 'ssh': dict(SSH), 'name': NAME, 'op': 'apply'}, **kw)
    try:
        return R.handle(req), None
    except R.Refused as e:
        return None, str(e)


TLS = {'protocols': ['TLSv1.3'], 'ciphers': '', 'prefer': False, 'dh': 'ffdhe2048', 'hsts': 31536000}
got, err = ask(source='given', cert=NEW_CERT, key=NEW_KEY, chain=INT, root=ROOT, tls=TLS)
check(err is None, 'root refused a good certificate for the server in front: %s' % err)
if got:
    fields, said = got
    check(fields['proxy']['fingerprint'] == fp(NEW_CERT), 'root did not say which certificate went there')
    check(fields['proxy'].get('dh') == 'ffdhe2048', 'root did not say which DH parameters went there')
pem_there = (CERTS / 'server.pem').read_text()
check(fp(pem_there) == fp(NEW_CERT) and INT.strip() in pem_there,
      'the certificate and its chain are not in the file nginx there serves')
check((CERTS / 'server.key').read_text().strip() == NEW_KEY.strip(), 'the key is not the new certificate\'s')
check(oct((CERTS / 'server.key').stat().st_mode & 0o777) == '0o600', 'the key there lost its 0600')
check(ROOT.strip() in (CERTS / 'server.ca').read_text(), 'the chain for OCSP stapling was not put there')
check(fp((CERTS / 'ntfy.pem').read_text()) == fp(NTFY_CERT), 'the certificate of ntfy was replaced')
tap = (CONFD / 'tap-front.conf').read_text()
check(tap.count('ssl_protocols             TLSv1.3;') == 2,
      'TLS 1.3 only is not in both server blocks that serve the certificate:\n' + tap)
check(tap.count('ssl_dhparam') == 2 and (CERTS / 'zigmon-dh.pem').is_file(),
      'the DH parameters were not put there')
check(tap.count('Strict-Transport-Security') == 2, 'HSTS was not put in both server blocks')
check('proxy_pass https://192.0.2.10;' in tap and '# <- your hostname' in tap,
      'what else the file holds was not kept')
check('TLSv1.2 TLSv1.3' in (CONFD / 'ntfy-front.conf').read_text(), 'the server of ntfy was changed')
log = LOG.read_text()
check('systemctl reload nginx' in log, 'nginx there was not reloaded')
check('proxy.house.example' in log and 'root@' in log, 'ssh was not asked of the server in front')
check(not list(P.rglob('*.zigmon-before')), 'the copies of the files were left behind')

# DH asked for again, the same: not made and sent again
LOG.write_text('')
before = (CERTS / 'zigmon-dh.pem').stat().st_mtime_ns
got, err = ask(tls=dict(TLS, hsts=0), dh_had='ffdhe2048')
check(err is None and (CERTS / 'zigmon-dh.pem').stat().st_mtime_ns == before,
      'the same DH parameters were made and sent again: %s' % err)
check('Strict-Transport-Security' not in (CONFD / 'tap-front.conf').read_text(), 'HSTS off was not taken out')

# nginx -t says no: every file as it was
(W / 'nginx-says-no').write_text('')
was = {f: f.read_bytes() for f in P.rglob('*') if f.is_file()}
got, err = ask(source='given', cert=OLD_CERT, key=OLD_KEY, chain=INT, tls=dict(TLS, protocols=['TLSv1.2', 'TLSv1.3']))
check(err and 'would not take it' in err, 'a configuration nginx refused was not said: %r' % err)
now = {f: f.read_bytes() for f in P.rglob('*') if f.is_file()}
check(was == now, 'a configuration nginx refused was left in place: %s' % sorted(
    str(f) for f in set(was) | set(now) if was.get(f) != now.get(f)))
(W / 'nginx-says-no').unlink()

# refused before anything is sent
for kw, why in ((dict(ssh=dict(SSH, key='')), 'password'),
                (dict(ssh=dict(SSH, host='proxy;rm -rf /')), 'address'),
                (dict(source='given', cert=NEW_CERT, key=OLD_KEY), 'not the one of this certificate'),
                (dict(source='given', cert=NEW_CERT, key=NEW_KEY, tls=dict(TLS, dh='gen1')), 'DH'),
                (dict(name='other.example', tls=TLS), 'no HTTPS server')):
    LOG.write_text('')
    got, err = ask(**kw)
    check(err and why.lower() in err.lower(), 'not refused (%s): %r' % (why, err))
# a server { } that names a file that is not a plain path
tap = (CONFD / 'tap-front.conf').read_text()
(CONFD / 'tap-front.conf').write_text(tap.replace('%s/server.key;' % CERTS, '%s/../x/server.key;' % CERTS, 1))
got, err = ask(source='given', cert=NEW_CERT, key=NEW_KEY)
check(err and 'plain path' in err, 'a key file of ../ was written to: %r' % err)
lay_proxy()

# the key and its certificate for a download, read there by root
got, err = ask(op='export', format='pem_key', password='', with_root=False)
check(err is None, 'the certificate there was not handed over for a download: %s' % err)

# ---- the daemon ----------------------------------------------------------------
sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                                # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 0, 'token_file': str(W / 'run' / 'api-token'),
                      'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '',
                      'state_dir': str(W / 'dstate'), 'proxy_host': 'proxy.house.example',
                      'proxy_auth': 'key'})
(W / 'dstate').mkdir()
d = zigmon.Daemon()
d.store.set_meta('proxy_key', SSH_KEY)
d.root_look = lambda fresh=False: {'tls': {'server_name': NAME}}
d.proxy_run = lambda command: subprocess.run(['sh', '-c', command], capture_output=True, text=True).stdout
HERE_PEM = NEW_CERT + INT
d.tls_pem_now = lambda: HERE_PEM
asked = []


def root_ask(kind, body=None, quiet=False):
    asked.append((kind, body))
    return 'x%d' % len(asked)


d.root_ask = root_ask
d.root_busy = lambda: False

look = zigmon.proxy_tls_read(d)
check(look['info'] and look['info']['fingerprint'] == fp(OLD_CERT), 'the card does not read the certificate there')
check(look['blocks'] == 2, 'the card does not count the server blocks serving it: %r' % look['blocks'])
check(look['stapling'] and look['protocols'] == ['TLSv1.2', 'TLSv1.3'], 'how it speaks TLS there was not read')
check(look['files']['key'].endswith('server.key'), 'the files there were not read')
d._proxy_tls_look = look

# every button of the card goes there
st = zigmon.proxy_tls_post(d, 'tls_policy', {'preset': 'modern', 'dh': 'ffdhe3072', 'hsts': 31536000}, 'test')
k, body = asked[-1]
check(k == 'tls_proxy' and body['tls']['dh'] == 'ffdhe3072' and body['tls']['protocols'] == ['TLSv1.3'],
      'the TLS settings of the server in front did not go to root: %r' % (body,))
check(zigmon.proxy_tls_conf(d)['managed'] and not d.tls_conf()['managed'],
      'the TLS settings of the server in front were taken for this machine\'s')
zigmon.proxy_tls_post(d, 'tls_upload', {'cert': OLD_CERT + INT + OLD_KEY}, 'test')
k, body = asked[-1]
check(body.get('source') == 'given' and fp(body['cert']) == fp(OLD_CERT), 'an upload for it did not go there')
csr = zigmon.proxy_tls_post(d, 'tls_csr', {'cn': NAME}, 'test')['csr']
check('CERTIFICATE REQUEST' in csr and zigmon.proxy_tls_conf(d).get('pending') and not d.tls_conf().get('pending'),
      'a request for the server in front was kept as this machine\'s')
check((W / 'dstate' / 'tls' / 'proxy-pending.key').is_file(), 'the request\'s key was not kept apart')
plain = zigmon.proxy_tls_post(d, 'tls_get', {'format': 'pem_cert'}, 'test')
check(fp(plain['text']) == fp(OLD_CERT) and plain['name'].endswith('-proxy'),
      'the certificate there is not what is downloaded')

# the same certificate as here
asked.clear()
zigmon.proxy_tls_post(d, 'proxy_follow', {'on': True}, 'test')
check(asked and asked[-1][1].get('source') == 'here' and 'key' not in asked[-1][1],
      'switching it on did not ask root to put the one of here there (or the key came through here)')
check(zigmon.proxy_tls_conf(d)['follow'], 'the switch was not kept')
try:
    zigmon.proxy_tls_post(d, 'tls_upload', {'cert': OLD_CERT + OLD_KEY}, 'test')
    check(False, 'an upload for it was taken while it follows this machine')
except ValueError:
    pass
# the half-minute chore: different there - asked; the same - not
asked.clear()
c = zigmon.proxy_tls_conf(d)
c['pushed'] = ''
zigmon.proxy_tls_save(d, c)
d._proxy_tls_look = dict(look, at=int(__import__('time').time()))
zigmon.proxy_tls_tick(d)
check(asked and asked[-1][1].get('source') == 'here', 'a different certificate there was not replaced by itself')
asked.clear()
d._proxy_tls_look = dict(look, at=int(__import__('time').time()),
                         info=dict(look['info'], fingerprint=fp(NEW_CERT)))
c = zigmon.proxy_tls_conf(d)
c['pushed'] = fp(NEW_CERT)
zigmon.proxy_tls_save(d, c)
zigmon.proxy_tls_tick(d)
check(not asked, 'the same certificate was put there again')
# a renewal here: put there again by itself
HERE_PEM = OLD_CERT + INT
d.tls_pem_now = lambda: HERE_PEM
zigmon.proxy_tls_tick(d)
check(asked and asked[-1][1].get('source') == 'here', 'a certificate renewed here was not put there')
# a failure: not again for an hour
asked.clear()
c = zigmon.proxy_tls_conf(d)
c['failed_at'] = int(__import__('time').time())
zigmon.proxy_tls_save(d, c)
zigmon.proxy_tls_tick(d)
check(not asked, 'a failed putting-in was tried again at once')

# a password only: said, nothing sent
zigmon.CONFIG['proxy_auth'] = 'password'
try:
    zigmon.proxy_tls_ssh(d)
    check(False, 'a server reached with a password was taken for the key way')
except ValueError:
    pass
zigmon.CONFIG['proxy_auth'] = 'key'
st = zigmon.proxy_tls_state(d)
check(st and st['host'] == 'proxy.house.example' and st['key_way'], 'the card\'s state is not given')
zigmon.CONFIG['proxy_host'] = ''
check(zigmon.proxy_tls_state(d) is None, 'a card for a server in front there is not')

# ---- the page ----------------------------------------------------------------
page = (HERE / 'web' / 'index.php').read_text()
check('grid.appendChild(certCard(proxyView(d)))' in page, 'the page has no second card')
check("target: 'proxy'" in page and page.count('tlsDo(') >= 9, 'the dialogs do not say which machine')
check("'proxy_follow'" in page and 'The same certificate as this machine' in page, 'the page has no switch')
check("'medium cert-dl'" in page and 'repeat(4,minmax(0,1fr))' in page,
      'the download does not lay its formats out four a line')
check(re.search(r'\.set-item textarea\{[^}]*background:var\(--panel2\)', page),
      'the CA\'s certificate box is still the browser\'s grey')

shutil.rmtree(W, ignore_errors=True)
print('proxycert: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
os._exit(1 if bad else 0)
