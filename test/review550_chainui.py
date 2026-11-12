#!/usr/bin/env python3
"""The chain of the certificate in place, on its card: Complete / Check the
chain, Upload the missing authority, and the check after a change as a
client that fetches nothing - here and on the server in front. Fails on
5.49.0: there were no such actions, root had no step that changes the chain
alone, the look held no PEMs and the front's look no chain_check.

  * a CA of the test's own (openssl): a root (the system's, stood in for by
    ZIGMON_TEST_CA_BUNDLE), an intermediate served as DER by an http.server
    here, leaves whose AIA names it; a private CA (a root not in the bundle,
    no AIA) and a self-signed one;
  * here (root run for real over a folder laid out as /etc): the leaf alone
    in place -> tls_chain fetches the intermediate, root's tls_chain writes
    leaf + intermediate into the cert file and the intermediate into the
    trusted file, the key untouched, the broker told; the AIA server stopped
    -> incomplete with the reason, tls_chain_add with the intermediate ->
    complete; a key -> 400, a stranger -> 400 naming the authority wanted;
    the private CA -> red, its root added -> complete with private_root (in
    the answer and in root's chain_check); a fingerprint that is not the one
    in place -> refused by root, the files as they were; a root in the chain
    -> refused; no answer has ok:false; events written;
  * the check after a change: a TLS server here (ZIGMON_TEST_SELF_CHECK)
    sending the leaf alone -> the verify error and a warning event; with its
    chain -> ok;
  * the server in front (fake ssh, fake nginx, as test/dualcert.py): its
    look has chain_check and the PEMs; tls_chain with target 'proxy' fetches
    and root writes the chain there over "ssh", the key there untouched; a
    fingerprint mismatch there refused; check_chain tells it once;
  * an operator may not ask for it (403);
  * the card's words and buttons in index.php, and the page in Chromium
    (php -S + Playwright): screenshots of complete, incomplete, the dialog,
    a private root, self-signed and the front's card into
    $ZIGMON_SHOTS (default: a folder under /tmp).

    python3 test/review550_chainui.py

Needs openssl. Ports 20000-20004.
"""
import http.server
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
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ROOT_HELPER = HERE / 'deploy' / 'zigmon_root.py'
W = Path(tempfile.mkdtemp(prefix='zigmon-chainui-check-'))
AIA_PORT, API_PORT, PHP_PORT, TLS_PORT = 20000, 20001, 20002, 20003
URL = 'http://127.0.0.1:%d' % AIA_PORT
NAME = 'mqtt.house.example'
SHOTS = Path(os.environ.get('ZIGMON_SHOTS') or (W / 'shots'))
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def sh(cmd, data=None, **kw):
    got = subprocess.run(cmd, input=data, capture_output=True, text=True,
                         stdin=None if data is not None else subprocess.DEVNULL, **kw)
    return got


# ---- the CAs of the test's own ----------------------------------------------------------------
CA = W / 'ca'
SITE = W / 'site'
CA.mkdir()
SITE.mkdir()


def make(n, subj, issuer=None, ca=False, aia=''):
    lines = ['basicConstraints=critical,CA:TRUE' if ca else 'basicConstraints=CA:FALSE',
             'keyUsage=critical,keyCertSign,cRLSign' if ca else 'keyUsage=digitalSignature,keyEncipherment',
             'subjectKeyIdentifier=hash']
    if issuer:
        lines.append('authorityKeyIdentifier=keyid')
    if not ca:
        lines.append('subjectAltName=DNS:%s' % subj.split('=')[-1])
    if aia:
        lines.append('authorityInfoAccess=caIssuers;URI:%s' % aia)
    (CA / (n + '.ext')).write_text('\n'.join(lines) + '\n')
    r = sh(['openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(CA / (n + '.key')),
            '-out', str(CA / (n + '.csr')), '-subj', subj])
    if r.returncode:
        raise SystemExit(r.stderr)
    if issuer:
        cmd = ['-CA', str(CA / (issuer + '.pem')), '-CAkey', str(CA / (issuer + '.key')), '-CAcreateserial']
    else:
        cmd = ['-signkey', str(CA / (n + '.key'))]
    r = sh(['openssl', 'x509', '-req', '-in', str(CA / (n + '.csr')), '-out', str(CA / (n + '.pem')),
            '-days', '30', '-extfile', str(CA / (n + '.ext'))] + cmd)
    if r.returncode:
        raise SystemExit(r.stderr)
    return (CA / (n + '.pem')).read_text().strip() + '\n', (CA / (n + '.key')).read_text()


ROOT, _ = make('root', '/CN=Test Chain Root', ca=True)
INT, _ = make('int', '/CN=Test Chain Intermediate', issuer='root', ca=True, aia=URL + '/root.der')
STRANGER, _ = make('stranger', '/CN=Test Chain Stranger', ca=True)
LEAF, LEAF_KEY = make('leaf', '/CN=%s' % NAME, issuer='int', aia=URL + '/int.der')
LEAF2, LEAF2_KEY = make('leaf2', '/CN=%s' % NAME, issuer='int', aia=URL + '/int.der')
FRONT, FRONT_KEY = make('front', '/CN=%s' % NAME, issuer='int', aia=URL + '/int.der')
PROOT, _ = make('proot', '/CN=House Private Root', ca=True)
PLEAF, PLEAF_KEY = make('pleaf', '/CN=%s' % NAME, issuer='proot')
SELF, SELF_KEY = make('self', '/CN=%s' % NAME)
for n in ('root', 'int'):
    sh(['openssl', 'x509', '-in', str(CA / (n + '.pem')), '-outform', 'DER', '-out', str(SITE / (n + '.der'))])
BUNDLE = W / 'bundle.pem'
BUNDLE.write_text(ROOT)


def fp(pem):
    out = sh(['openssl', 'x509', '-noout', '-fingerprint', '-sha256'], pem).stdout
    return out.strip().split('=', 1)[-1].replace(':', '').lower()


def certs_of(text):
    return re.findall(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', text or '', re.S)


# ---- the CA's web server ----------------------------------------------------------------------
ASKED = []


class Serve(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(SITE), **k)

    def do_GET(self):
        ASKED.append(self.path)
        return super().do_GET()

    def log_message(self, *a):
        pass


AIA = {}


def aia_up():
    AIA['httpd'] = http.server.ThreadingHTTPServer(('127.0.0.1', AIA_PORT), Serve)
    threading.Thread(target=AIA['httpd'].serve_forever, daemon=True).start()


def aia_down():
    AIA['httpd'].shutdown()
    AIA['httpd'].server_close()


aia_up()

# ---- a TLS server standing in for nginx, for the check after a change ----------------------------
SERVE = {'cert': None, 'key': None}
tls_sock = socket.socket()
tls_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
tls_sock.bind(('127.0.0.1', TLS_PORT))
tls_sock.listen(8)


def tls_serve():
    while True:
        try:
            c, _ = tls_sock.accept()
        except OSError:
            return
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(SERVE['cert'], SERVE['key'])
            with ctx.wrap_socket(c, server_side=True) as s:
                s.settimeout(5)
                try:
                    s.recv(1)
                except (OSError, ssl.SSLError):
                    pass
        except (OSError, ssl.SSLError):
            try:
                c.close()
            except OSError:
                pass


threading.Thread(target=tls_serve, daemon=True).start()

# ---- this machine, laid out as /etc, and the server in front --------------------------------------
STATE, ETC = W / 'state', W / 'etc'
CERTS = ETC / 'nginx' / 'certs'
for p in (STATE / 'root', ETC / 'zigmon', ETC / 'mosquitto' / 'conf.d', ETC / 'nginx' / 'conf.d', CERTS):
    p.mkdir(parents=True, exist_ok=True)
DB = STATE / 'history.db'
(ETC / 'zigmon' / 'config.json').write_text(json.dumps({'db_file': str(DB)}))
(ETC / 'mosquitto' / 'mosquitto.conf').write_text('listener 1883\n')
(ETC / 'mosquitto' / 'conf.d' / 'zigmon.conf').write_text('listener 8883\ncertfile %s\nkeyfile %s\n' % (
    CERTS / 'server.pem', CERTS / 'server.key'))
NGINX_CONF = ETC / 'nginx' / 'conf.d' / 'zigmon.conf'
NGINX_CONF.write_text('''server {
    listen      80;
    server_name %(n)s;
    return 301 https://$host$request_uri;
}

server {
    listen      443 ssl http2;
    server_name %(n)s;
    ssl_certificate           %(c)s/server.pem;
    ssl_certificate_key       %(c)s/server.key;
    ssl_trusted_certificate   %(c)s/server.ca;
    ssl_protocols             TLSv1.2 TLSv1.3;
    location / {
        root /var/www/zigmon;
    }
}
''' % {'n': NAME, 'c': CERTS})


def lay_here(cert, key, trust=''):
    (CERTS / 'server.pem').write_text(cert)
    (CERTS / 'server.key').write_text(key)
    os.chmod(CERTS / 'server.key', 0o600)
    if trust:
        (CERTS / 'server.ca').write_text(trust)
    elif (CERTS / 'server.ca').exists():
        (CERTS / 'server.ca').unlink()


P = W / 'proxy'
PCERTS = P / 'etc' / 'nginx' / 'certs'
CONFD = P / 'etc' / 'nginx' / 'conf.d'
PCERTS.mkdir(parents=True)
CONFD.mkdir(parents=True)
(CONFD / 'nginx-tap-front.conf').write_text('''server {
    listen      443 ssl http2;
    server_name %(n)s;
    ssl_certificate           %(c)s/server.pem;
    ssl_certificate_key       %(c)s/server.key;
    ssl_protocols             TLSv1.2 TLSv1.3;
    location / {
        proxy_pass https://192.0.2.10;
    }
}
''' % {'n': NAME, 'c': PCERTS})
(PCERTS / 'server.pem').write_text(FRONT)
(PCERTS / 'server.key').write_text(FRONT_KEY)
os.chmod(PCERTS / 'server.key', 0o600)
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
  -t) echo "nginx -t" >> %(log)s; exit 0 ;;
  -s) echo "nginx -s $2" >> %(log)s ;;
esac
''' % {'confd': CONFD, 'log': LOG})
(FAKES / 'systemctl').write_text('#!/bin/sh\necho "systemctl $*" >> %s\n' % LOG)
for f in FAKES.iterdir():
    f.chmod(0o755)

for k in list(os.environ):
    if k.lower() in ('http_proxy', 'https_proxy', 'all_proxy'):
        del os.environ[k]
PATH_HERE = os.environ['PATH']
os.environ.update(ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(W / 'own'), ZIGMON_FULL_DIR=str(W / 'full'),
                  ZIGMON_CONFIG=str(ETC / 'zigmon' / 'config.json'), ZIGMON_NGINX_CONF=str(NGINX_CONF),
                  ZIGMON_CERT_DIR=str(CERTS), ZIGMON_MOSQ_DIR=str(ETC / 'mosquitto'),
                  ZIGMON_NO_SERVICES='1', ZIGMON_SERVICE_LOG=str(W / 'services.log'), ZIGMON_FS_ROOT=str(W),
                  ZIGMON_USER='root', ZIGMON_FW_FILE4=str(W / 'no4'), ZIGMON_FW_FILE6=str(W / 'no6'),
                  ZIGMON_FIREWALL_CMD=str(W / 'no-firewall-cmd'), ZIGMON_SSH_BIN=str(FAKES / 'ssh'),
                  ZIGMON_NGINX_TEST='true', ZIGMON_TEST_CA_BUNDLE=str(BUNDLE),
                  ZIGMON_TEST_SELF_CHECK='127.0.0.1:%d' % TLS_PORT,
                  ZIGMON_ROOT_RUN='%s -I %s' % (sys.executable, ROOT_HELPER),
                  PATH='%s:%s' % (FAKES, PATH_HERE))

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
TOLD = []
d.notify = lambda message, *a, **k: TOLD.append((message, k.get('dedup')))
d.store.set_meta('proxy_key', SSH_KEY)
d.proxy_run = lambda command: subprocess.run(['sh', '-c', command], capture_output=True, text=True,
                                             stdin=subprocess.DEVNULL).stdout
d._proxy_tls_looking = d._proxy_ntfy_looking = True          # looks are made by the test, not a thread
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
SO = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''
ANSWERS = []


def tls(body, target='', session=None):
    s = session or S
    b = dict(body, session=s)
    if target:
        b['target'] = target
    code, out = call('/api/tls', b, session=s)
    if code == 200:
        ANSWERS.append(out)
    return code, out


def self_check_after(since, key='tls_self_check', wait=20):
    end = time.time() + wait
    while time.time() < end:
        got = json.loads(d.store.get_meta(key) or 'null')
        if got and got.get('at', 0) >= since:
            return got
        time.sleep(0.2)
    return None


def events(text):
    return d.store.events(limit=50, text=text)


try:
    # ---- the leaf alone in place: Complete the chain ---------------------------------------
    print('here: the leaf alone, Complete the chain')
    lay_here(LEAF, LEAF_KEY)
    SERVE.update(cert=str(CERTS / 'server.pem'), key=str(CERTS / 'server.key'))
    key_before = (CERTS / 'server.key').read_bytes()
    look = d.root_look(fresh=True).get('tls') or {}
    cc = look.get('chain_check') or {}
    check(cc.get('ok') is False and cc.get('missing') == 'Test Chain Intermediate', 'the leaf alone: %r' % cc)
    pems = look.get('pems') or {}
    check(pems.get('cert', '').strip() == LEAF.strip() and pems.get('chain') == [] and look.get('fp') == fp(LEAF),
          'the look has no PEMs of what nginx sends: %r' % {k: v for k, v in look.items() if k == 'pems'})
    check('PRIVATE KEY' not in json.dumps(look), 'the look has a key in it')
    check(look.get('port') == 443, 'the port nginx listens on: %r' % look.get('port'))
    del ASKED[:]
    t0 = int(time.time())
    code, out = tls({'action': 'tls_chain'})
    check(code == 200 and out.get('complete') is True and 'fetched: Test Chain Intermediate' in out.get('message', ''),
          'Complete the chain did not fetch the intermediate: %s %s' % (code, out))
    check('/int.der' in ASKED, 'the AIA address was not asked: %r' % ASKED)
    st = d.root_read('status.json')
    check(st.get('kind') == 'tls_chain' and st.get('state') == 'done', "root's tls_chain: %r" % st)
    pem_now = (CERTS / 'server.pem').read_text()
    check(certs_of(pem_now) == [LEAF.strip(), INT.strip()], 'the cert file is not the leaf and the intermediate: %r'
          % [c[30:60] for c in certs_of(pem_now)])
    check(certs_of((CERTS / 'server.ca').read_text()) == [INT.strip()], 'the trusted file is not the intermediate')
    check((CERTS / 'server.key').read_bytes() == key_before, 'the key was touched')
    check('mosquitto' in (W / 'services.log').read_text() and 'reload nginx' in (W / 'services.log').read_text(),
          'nginx not reloaded, or the broker not told: %r' % (W / 'services.log').read_text())
    cc = (d.root_look(fresh=True).get('tls') or {}).get('chain_check') or {}
    check(cc.get('ok') is True and cc.get('sent') == 1 and not cc.get('private_root'), 'after: %r' % cc)
    sc = self_check_after(t0)
    check(sc and sc.get('ok') is True and 'the whole chain is sent' in sc.get('words', ''),
          'the check after the change: %r' % sc)
    check(events('checked the chain of %s' % NAME), 'no event of the chain checked')
    code, out = call('/api/tls', None, session=S)
    check(code == 200 and (out.get('chain_state') or {}).get('fetched') == ['Test Chain Intermediate']
          and (out.get('self_check') or {}).get('ok') is True and 'pems' not in (out.get('now') or {}),
          'the card\'s state: %r' % {k: out.get(k) for k in ('chain_state', 'self_check')})
    code, out = tls({'action': 'tls_chain'})
    check(code == 200 and out.get('complete') is True and 'root is putting' not in out.get('message', ''),
          'Check the chain of a whole one asked root again: %s' % out)

    # ---- the check after a change, by itself -----------------------------------------------
    print('the check as a client that fetches nothing')
    (W / 'only-leaf.pem').write_text(LEAF)
    SERVE.update(cert=str(W / 'only-leaf.pem'))
    got = d.tls_self_check(NAME, 443)
    check(got.get('ok') is False and 'refuses what nginx sends' in got['words'] and
          'unable to get local issuer certificate' in got['words'], 'the leaf alone: %r' % got)
    check(events('refuses what nginx sends'), 'no warning event of the check')
    SERVE.update(cert=str(CERTS / 'server.pem'))
    got = d.tls_self_check(NAME, 443)
    check(got.get('ok') is True, 'leaf and chain: %r' % got)

    # ---- the AIA server stopped; the authority by hand -----------------------------------------
    print('here: the AIA server stopped, then the authority uploaded')
    lay_here(LEAF2, LEAF2_KEY)
    d._tls_aia_cache = {}
    aia_down()
    code, out = tls({'action': 'tls_chain'})
    check(code == 200 and out.get('complete') is False and 'incomplete - the authority Test Chain Intermediate is '
          'not sent' in out.get('message', '') and 'could not be fetched from %s/int.der' % URL in out['message'],
          'with the CA away: %s %s' % (code, out))
    check(certs_of((CERTS / 'server.pem').read_text()) == [LEAF2.strip()], 'something was put in with the CA away')
    code, out = tls({'action': 'tls_chain_add', 'text': LEAF2_KEY})
    check(code == 400 and 'private key' in out.get('error', ''), 'a key was taken: %s %s' % (code, out))
    code, out = tls({'action': 'tls_chain_add', 'text': STRANGER})
    check(code == 400 and "none of these is the authority that signed the chain's last certificate "
          "(Test Chain Intermediate)" in out.get('error', ''), 'a stranger: %s %s' % (code, out))
    t0 = int(time.time())
    code, out = tls({'action': 'tls_chain_add', 'text': INT + ROOT})
    check(code == 200 and out.get('complete') is True and out.get('added') == ['Test Chain Intermediate'],
          'the intermediate uploaded: %s %s' % (code, out))
    check(certs_of((CERTS / 'server.pem').read_text()) == [LEAF2.strip(), INT.strip()],
          'the uploaded intermediate is not in the cert file')
    check(ROOT.strip() not in (CERTS / 'server.pem').read_text(), 'the root was sent')
    check(events('added Test Chain Intermediate to the chain of'), 'no event of the authority added')
    aia_up()

    # ---- a private CA ----------------------------------------------------------------------------
    print('here: a private CA without its root, then its root')
    lay_here(PLEAF, PLEAF_KEY)
    code, out = tls({'action': 'tls_chain'})
    check(code == 200 and out.get('complete') is False and 'names no CA Issuers address' in out.get('message', '')
          and (out.get('chain_state') or {}).get('missing') == 'House Private Root', 'the private CA: %s' % out)
    code, out = tls({'action': 'tls_chain_add', 'text': PROOT})
    cs = out.get('chain_state') or {}
    check(code == 200 and out.get('complete') is True and cs.get('private_root') == 'House Private Root' and
          'a private root: only clients that trust it take it' in out.get('message', ''),
          'its root added: %s %s' % (code, out))
    check(certs_of((CERTS / 'server.pem').read_text()) == [PLEAF.strip()] and
          certs_of((CERTS / 'server.ca').read_text()) == [PROOT.strip()], 'the private root is not in the trusted file')
    look = d.root_look(fresh=True).get('tls') or {}
    cc = look.get('chain_check') or {}
    check(cc.get('ok') is True and cc.get('private_root') == 'House Private Root' and
          look.get('roots_given') == ['House Private Root'], 'root\'s check of a private root: %r' % cc)

    # ---- what root refuses ---------------------------------------------------------------------
    print("root's tls_chain refuses")
    lay_here(LEAF, LEAF_KEY)
    before = {n: (CERTS / n).read_bytes() for n in ('server.pem', 'server.key')}
    for ask, words in (({'fp': fp(LEAF2), 'chain': [INT.strip()], 'root': ''}, 'not the one the chain was made for'),
                       ({'fp': fp(LEAF), 'chain': [ROOT.strip()], 'root': ''}, 'a root is never sent'),
                       ({'fp': fp(LEAF), 'chain': [LEAF2.strip()], 'root': ''}, 'does not go up from it'),
                       ({'fp': fp(LEAF), 'chain': [INT.strip() + '\n' + LEAF_KEY], 'root': ''}, 'certificates, one by one'),
                       ({'fp': fp(LEAF), 'chain': [INT.strip()], 'root': INT}, 'is not a root')):
        d.root_ask('tls_chain', ask)
        st = d.root_read('status.json')
        check(st.get('state') == 'failed' and words in ' '.join(st.get('said') or []),
              'root took %s: %r' % (words, st.get('said')))
    check(all((CERTS / n).read_bytes() == v for n, v in before.items()), 'a refused request changed the files')

    # ---- an operator ---------------------------------------------------------------------------
    code, out = tls({'action': 'tls_chain'}, session=SO)
    check(code == 403, 'an operator asked for the chain: %s %s' % (code, out))

    # ---- the server in front ---------------------------------------------------------------------
    print('the server in front: its look, Complete the chain there')
    look = zigmon.proxy_tls_read(d)
    d._proxy_tls_look = look
    cc = look.get('chain_check') or {}
    check(cc.get('ok') is False and cc.get('missing') == 'Test Chain Intermediate' and look.get('port') == 443,
          'the front\'s look: %r' % cc)
    del TOLD[:]
    d.check_certificate()
    d.check_certificate()
    hit = [m for m, _k in TOLD if 'the server in front does not send the intermediate authority' in m]
    check(len(hit) == 1, 'the front\'s chain told %d times: %r' % (len(hit), TOLD))
    front_key = (PCERTS / 'server.key').read_bytes()
    t0 = int(time.time())
    code, out = tls({'action': 'tls_chain'}, 'proxy')
    st = d.root_read('status.json')
    check(code == 200 and out.get('complete') is True and st.get('kind') == 'tls_proxy' and st.get('state') == 'done',
          'Complete the chain there: %s %s %r' % (code, out, st.get('said')))
    check(certs_of((PCERTS / 'server.pem').read_text()) == [FRONT.strip(), INT.strip()],
          'the front\'s cert file is not the leaf and the intermediate')
    check((PCERTS / 'server.key').read_bytes() == front_key, 'the key there was touched')
    check('nginx -t' in LOG.read_text(), 'nginx -t was not asked there')
    look = zigmon.proxy_tls_read(d)
    check((look.get('chain_check') or {}).get('ok') is True, 'the front\'s look after: %r' % look.get('chain_check'))
    sc = self_check_after(t0, 'tls_self_check_front')
    check(sc and 'words' in sc, 'no check after the change there: %r' % sc)
    st0 = zigmon.proxy_tls_state(d)
    check('pem' not in st0['look'] and 'roots' not in st0['look'] and (st0.get('chain_state') or {}).get('ok') is True,
          'the front card\'s state: %r' % st0.get('chain_state'))
    d.root_ask('tls_proxy', {'ssh': zigmon.proxy_tls_ssh(d), 'name': NAME, 'op': 'chain', 'fp': fp(LEAF),
                             'chain': [INT.strip()], 'root': ''})
    st = d.root_read('status.json')
    check(st.get('state') == 'failed' and 'not the one the chain was made for' in ' '.join(st.get('said') or []),
          'a fingerprint that is not the front\'s was taken: %r' % st.get('said'))
    (PCERTS / 'server.pem').write_text(FRONT)                # for the page: incomplete there

    check(not [a for a in ANSWERS if a.get('ok') is False], 'an answer had ok:false: %r'
          % [a for a in ANSWERS if a.get('ok') is False][:1])

    # ---- the card ----------------------------------------------------------------------------------
    print('the card')
    page = (HERE / 'web' / 'index.php').read_text()
    for words in ("'Complete the chain'", "'Check the chain'", "'Upload the missing authority'", "'Add it to the chain'",
                  "'Missing in the chain: '", "action: 'tls_chain'", "action: 'tls_chain_add'",
                  'a private root: only clients that trust it take it', "'.pem,.crt,.cer,.der,.cert,.ca-bundle'",
                  'f.size > 262144', '.ot .cert-self.bad', 'chain_check: lk.chain_check'):
        check(words in page, 'the card has no %s' % words)

    # ---- the page in Chromium ---------------------------------------------------------------------
    print('the page')
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
    SHOTS.mkdir(parents=True, exist_ok=True)
    js = r'''
const { chromium } = require('playwright');
const job = %(job)s;
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({viewport: {width: 1500, height: 1200}, colorScheme: 'dark'});
  await ctx.addCookies([{name: 'zigmon_session', value: job.s, url: 'http://127.0.0.1:' + job.port + '/'}]);
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.goto('http://127.0.0.1:' + job.port + '/#control/sys-certs');
  await p.waitForTimeout(2000);
  try { await p.evaluate(() => showControlSection('sys-certs')); } catch (e) {}
  await p.waitForSelector('#web-certs .cert-card .cert-kv', {timeout: 15000});
  await p.waitForTimeout(800);
  const card = '#web-certs .cert-grid > .cert-card:nth-child(' + job.card + ')';
  const r = {};
  const read = async () => p.evaluate((card) => {
    const c = document.querySelector(card);
    const dts = Array.from(c.querySelectorAll('.cert-kv dt'));
    const line = n => { const t = dts.find(x => x.textContent === n); return t ? t.nextElementSibling : null; };
    const ch = line('Chain'), root = line('Root');
    return {chain: ch ? ch.textContent : null, cls: ch ? ch.className : null,
            color: ch ? getComputedStyle(ch).color : null, root: root ? root.textContent : null,
            buttons: Array.from(c.querySelectorAll('.cert-tools button')).map(x => x.textContent.trim()),
            primary: Array.from(c.querySelectorAll('.cert-tools button.primary')).map(x => x.textContent.trim()),
            self: (c.querySelector('.cert-self') || {}).textContent || ''};
  }, card);
  r.before = await read();
  if (job.act) await (await p.$(card)).screenshot({path: job.dir + '/' + job.shot + (job.act === 'dialog' ? '' : '-before') + '.png'});
  if (job.act === 'dialog') {
    await p.click(card + ' .cert-tools button:has-text("Upload the missing authority")');
    await p.waitForSelector('#zmodal:not([hidden]) textarea.cert-chain-text', {timeout: 10000});
    if (job.text) await p.fill('#zmodal textarea.cert-chain-text', job.text);
    r.dialog = await p.evaluate(() => document.querySelector('#zmodal-body').textContent);
    r.missing = await p.evaluate(() => (document.querySelector('#zmodal .cert-missing') || {}).textContent);
    r.foot = await p.evaluate(() => Array.from(document.querySelectorAll('#zmodal-foot button')).map(x => x.textContent.trim()));
    await p.screenshot({path: job.dir + '/' + job.shot + '-dialog.png'});
    if (job.go) {
      await p.click('#zmodal-foot .btn.primary');
      await p.waitForSelector('#zmodal', {state: 'hidden', timeout: 60000});
      r.toast = await p.evaluate(() => [document.getElementById('toast').textContent, document.getElementById('toast').className]);
      await p.waitForTimeout(2500);
      r.after = await read();
    }
  } else if (job.act === 'complete') {
    await p.click(card + ' .cert-tools button:has-text("Complete the chain")');
    await p.waitForFunction(() => /show/.test(document.getElementById('toast').className), null, {timeout: 60000});
    r.toast = await p.evaluate(() => [document.getElementById('toast').textContent, document.getElementById('toast').className]);
    await p.waitForTimeout(2500);
    r.after = await read();
  }
  if (job.act !== 'dialog') await (await p.$(card)).screenshot({path: job.dir + '/' + job.shot + '.png'});
  // 5.49.1: a button of the front's card left the page's target at the front,
  // and the next drawing made this machine's card the front's as well
  r.first = await p.evaluate(() => (document.querySelector('#web-certs .cert-grid > .cert-card:nth-child(1) .cert-target') || {}).textContent);
  r.errors = errors;
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
    npm_root = sh(['npm', 'root', '-g']).stdout.strip()

    def page(shot, card=1, act='', text='', go=False):
        job = {'s': S, 'port': PHP_PORT, 'card': card, 'act': act, 'text': text, 'go': go, 'dir': str(SHOTS),
               'shot': shot}
        (W / 'page.js').write_text(js % {'job': json.dumps(job)})
        got = sh(['node', str(W / 'page.js')], timeout=240, env=dict(os.environ, NODE_PATH=npm_root))
        try:
            return json.loads(got.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return {'error': (got.stdout + got.stderr)[-300:]}

    GREEN, RED = 'rgb(63, 185, 80)', 'rgb(248, 81, 73)'
    lay_here(LEAF2, LEAF2_KEY)
    d.store.forget_meta('tls_chain_state')
    r = page('incomplete', act='dialog')
    if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
        print('  SKIPPED (no browser here): %s' % r['error'][:200])
    else:
        b0 = r.get('before') or {}
        check(not r.get('error') and b0.get('cls') == 'bad' and 'incomplete - the authority Test Chain '
              'Intermediate is not sent' in (b0.get('chain') or ''), 'the incomplete card: %r' % r)
        check(b0.get('color') == RED, 'the Chain line is not red: %r' % b0.get('color'))
        check(b0.get('primary') == ['Complete the chain'] and 'Upload the missing authority' in b0.get('buttons', []),
              'the buttons of an incomplete chain: %r' % b0.get('buttons'))
        check(b0.get('root') == 'not given', 'the Root line: %r' % b0.get('root'))
        check(r.get('missing') == 'Test Chain Intermediate' and 'never a key' in (r.get('dialog') or '') and
              'Read a file' in (r.get('dialog') or '') and 'Add it to the chain' in (r.get('foot') or []),
              'the dialog: %r' % {k: r.get(k) for k in ('missing', 'foot')})
        r = page('complete', act='complete')
        a = r.get('after') or {}
        check(not r.get('error') and 'ok' in (r.get('toast') or ['', ''])[1] and 'HTTP 200' not in str(r.get('toast'))
              and a.get('cls') == 'good' and a.get('color') == GREEN and 'fetched: Test Chain Intermediate' in a.get('chain', '')
              and a.get('buttons', []).count('Check the chain') == 1 and 'Upload the missing authority' not in a.get('buttons', []),
              'Complete the chain on the page: %r' % r)
        check('the whole chain is sent' in a.get('self', ''), 'the card has no line of the check: %r' % a.get('self'))
        lay_here(PLEAF, PLEAF_KEY)
        r = page('private-root-missing', act='dialog', text=PROOT, go=True)
        a = r.get('after') or {}
        check(not r.get('error') and r.get('missing') == 'House Private Root' and a.get('cls') == 'good' and
              'a private root' in a.get('chain', '') and a.get('root') == 'House Private Root',
              'the private root by the dialog: %r' % r)
        page('private-root')
        lay_here(SELF, SELF_KEY)
        r = page('self-signed')
        b0 = r.get('before') or {}
        check(not r.get('error') and (b0.get('chain') or '').startswith('self-signed - no chain') and
              not [x for x in b0.get('buttons', []) if 'chain' in x or 'authority' in x],
              'the self-signed card: %r' % b0)
        lay_here(LEAF2, LEAF2_KEY, INT)
        (CERTS / 'server.pem').write_text(LEAF2 + INT)
        d._proxy_tls_look = zigmon.proxy_tls_read(d)
        SERVE.update(cert=str(PCERTS / 'server.pem'), key=str(PCERTS / 'server.key'))
        r = page('front', card=2, act='complete')
        a = r.get('after') or {}
        check(not r.get('error') and (r.get('before') or {}).get('cls') == 'bad' and a.get('cls') == 'good'
              and 'the whole chain is sent' in a.get('self', ''), 'the front\'s card: %r' % r)
        check(r.get('first') == 'The dashboard and the broker',
              'after a button of the front\'s card the first card is not this machine\'s: %r' % r.get('first'))
        check(not r.get('errors'), 'the page threw: %r' % r.get('errors'))
        print('  screenshots: %s' % SHOTS)
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
    try:
        aia_down()
    except Exception:                                        # noqa: BLE001
        pass
    tls_sock.close()

shutil.rmtree(W, ignore_errors=True)
if bad:
    print('%d FAILED' % len(bad))
    sys.exit(1)
print('all good')
