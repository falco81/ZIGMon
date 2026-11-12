#!/usr/bin/env python3
"""A public certificate put in without its intermediate: nginx sends the leaf
alone. Browsers fetch the missing link themselves (AIA, CA Issuers) and say
nothing; Python, curl, openssl, phone apps and MQTT clients refuse it
("unable to get local issuer certificate"). Fails on 5.48.1: the chain was
left empty without a word, root's check verified the leaf against the trusted
file (which holds the chain) and the card said "the chain leads to the root".

  * a CA of the test's own (openssl): a root, an intermediate whose AIA
    names the root, leaves whose AIA names the intermediate - all served as
    DER by an http.server here; the system's roots stood in for by a bundle
    holding only the test's root (ZIGMON_TEST_CA_BUNDLE);
  * the daemon's tls_sort: a leaf with its key alone gets the intermediate
    fetched into its chain (and said); a leaf whose AIA serves a stranger
    is left as it was, with a warning; a self-signed one fetches nothing;
    a whole chain given fetches nothing; the words of the answer;
  * push_cert_in (acme push): an empty chain_pem made whole;
  * root's tls_now: chain_check says incomplete for a file holding only the
    leaf even with root and intermediate in the trusted file (the old
    'verify' says ok there), complete for leaf + intermediate;
  * check_certificate: told once for that certificate;
  * the card's words in index.php.

    python3 test/review549_chain.py

Needs openssl. Port 19977 (the stand-in for the CA's web server).
"""
import http.server
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ROOT_HELPER = HERE / 'deploy' / 'zigmon_root.py'
W = Path(tempfile.mkdtemp(prefix='zigmon-chain-check-'))
AIA_PORT = 19977
URL = 'http://127.0.0.1:%d' % AIA_PORT
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def sh(cmd, data=None):
    got = subprocess.run(cmd, input=data, capture_output=True, text=True,
                         stdin=None if data is not None else subprocess.DEVNULL)
    if got.returncode != 0:
        raise SystemExit('openssl: %s' % got.stderr)
    return got.stdout


# ---- the CA of the test's own -----------------------------------------------------------------
CA = W / 'ca'
SITE = W / 'site'
CA.mkdir()
SITE.mkdir()


def ext(name, text):
    (CA / name).write_text(text)
    return str(CA / name)


def make(n, subj, issuer=None, ca=False, aia=''):
    """A certificate n.pem with its key n.key: self-signed without an issuer."""
    lines = ['basicConstraints=critical,CA:TRUE' if ca else 'basicConstraints=CA:FALSE',
             'keyUsage=critical,keyCertSign,cRLSign' if ca else 'keyUsage=digitalSignature,keyEncipherment',
             'subjectKeyIdentifier=hash']
    if issuer:
        lines.append('authorityKeyIdentifier=keyid')
    if not ca:
        lines.append('subjectAltName=DNS:%s' % subj.split('=')[-1])
    if aia:
        lines.append('authorityInfoAccess=caIssuers;URI:%s' % aia)
    e = ext(n + '.ext', '\n'.join(lines) + '\n')
    sh(['openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(CA / (n + '.key')),
        '-out', str(CA / (n + '.csr')), '-subj', subj])
    if issuer:
        sh(['openssl', 'x509', '-req', '-in', str(CA / (n + '.csr')), '-CA', str(CA / (issuer + '.pem')),
            '-CAkey', str(CA / (issuer + '.key')), '-CAcreateserial', '-out', str(CA / (n + '.pem')),
            '-days', '30', '-extfile', e])
    else:
        sh(['openssl', 'x509', '-req', '-in', str(CA / (n + '.csr')), '-signkey', str(CA / (n + '.key')),
            '-out', str(CA / (n + '.pem')), '-days', '30', '-extfile', e])
    return (CA / (n + '.pem')).read_text(), (CA / (n + '.key')).read_text()


ROOT, _ = make('root', '/CN=Test Chain Root', ca=True)
INT, _ = make('int', '/CN=Test Chain Intermediate', issuer='root', ca=True, aia=URL + '/root.der')
OTHER, _ = make('other', '/CN=Test Chain Stranger', ca=True)
LEAF, LEAF_KEY = make('leaf', '/CN=mqtt.house.example', issuer='int', aia=URL + '/int.der')
LEAF2, LEAF2_KEY = make('leaf2', '/CN=mqtt2.house.example', issuer='int', aia=URL + '/other.der')
SELF, SELF_KEY = make('self', '/CN=self.house.example', aia=URL + '/int.der')
for n in ('root', 'int', 'other'):
    sh(['openssl', 'x509', '-in', str(CA / (n + '.pem')), '-outform', 'DER', '-out', str(SITE / (n + '.der'))])
BUNDLE = W / 'bundle.pem'
BUNDLE.write_text(ROOT)

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


httpd = http.server.ThreadingHTTPServer(('127.0.0.1', AIA_PORT), Serve)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

# nothing of the machine's own proxy for 127.0.0.1
for k in list(os.environ):
    if k.lower() in ('http_proxy', 'https_proxy', 'all_proxy'):
        del os.environ[k]
STATE = W / 'state'
(STATE / 'root').mkdir(parents=True)
os.environ.update(ZIGMON_TEST_CA_BUNDLE=str(BUNDLE), ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(W / 'own'),
                  ZIGMON_CONFIG=str(W / 'config.json'), ZIGMON_NO_SERVICES='1', ZIGMON_USER='root',
                  ZIGMON_NGINX_CONF=str(W / 'nginx.conf'), ZIGMON_CERT_DIR=str(W / 'certs'),
                  ZIGMON_MOSQ_DIR=str(W / 'mosquitto'))
(W / 'config.json').write_text('{}')

sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 19978, 'token_file': str(W / 'token'),
                      'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '',
                      'state_dir': str(STATE), 'acme': 0})
d = zigmon.Daemon()
TOLD = []
d.notify = lambda message, *a, **k: TOLD.append((message, k.get('dedup')))

try:
    # ---- tls_sort --------------------------------------------------------------------------------
    print('tls_sort: a leaf and its key alone')
    del ASKED[:]
    pem = d.tls_sort(LEAF + LEAF_KEY)
    check(INT.strip() in pem['chain'], 'the intermediate was not fetched into the chain: %r' % pem['chain'][:80])
    check(ROOT.strip() not in pem['chain'] + pem['cert'], 'the root was put into the chain sent')
    check(pem.get('fetched') == ['Test Chain Intermediate'], 'fetched: %r' % pem.get('fetched'))
    check('/int.der' in ASKED, 'the AIA address was not asked: %r' % ASKED)
    said = d.tls_chain_said(pem)
    check('fetched' not in pem and 'chain_warn' not in pem, 'what was found is left in what goes to root')
    check(any('came without its intermediate authority - zigmon fetched it (Test Chain Intermediate)' in w
              for w in said), 'the words: %r' % said)
    check(d.tls_chain_tell(said).startswith('mqtt.house.example came without'), 'tls_chain_tell')
    ev = d.store.events(limit=20, text='came without its intermediate')
    check(len(ev) == 1, 'the event: %r' % ev)

    print('tls_sort: the whole chain given')
    del ASKED[:]
    pem = d.tls_sort(LEAF + INT + LEAF_KEY)
    check(INT.strip() in pem['chain'] and not pem.get('fetched') and not pem.get('chain_warn'),
          'a whole chain: %r' % {k: v for k, v in pem.items() if k != 'key'})
    check(not ASKED, 'something was fetched for a whole chain: %r' % ASKED)

    print('tls_sort: the AIA serves a stranger')
    del ASKED[:]
    pem = d.tls_sort(LEAF2 + LEAF2_KEY)
    check(pem['chain'] == '', 'a stranger was put in the chain: %r' % pem['chain'][:80])
    check(not pem.get('fetched'), 'fetched: %r' % pem.get('fetched'))
    check(pem.get('chain_warn') and 'does not hold the issuer' in pem['chain_warn'][0],
          'no warning: %r' % pem.get('chain_warn'))
    check('/other.der' in ASKED, 'the stranger was not asked: %r' % ASKED)

    print('tls_sort: self-signed')
    del ASKED[:]
    pem = d.tls_sort(SELF + SELF_KEY)
    check(not ASKED and not pem.get('fetched') and not pem.get('chain_warn') and pem['chain'] == '',
          'a self-signed one: %r %r' % (ASKED, pem.get('chain_warn')))

    # ---- push_cert_in ----------------------------------------------------------------------------
    print('push_cert_in: an empty chain_pem')
    zigmon.push_open_key = lambda k, priv, app_id, fp: LEAF_KEY
    der = subprocess.run(['openssl', 'x509', '-outform', 'DER'], input=LEAF.encode(), capture_output=True).stdout
    import hashlib                                      # noqa: E402
    got = zigmon.push_cert_in(d, {'cert_pem': LEAF, 'chain_pem': '', 'fingerprint': hashlib.sha256(der).hexdigest(),
                                  'key': {}}, None, 'app', 'the certificate')
    check(INT.strip() in got['chain'], 'push_cert_in left the chain empty: %r' % got['chain'][:80])
    check(ROOT.strip() not in got['chain'], 'push_cert_in put the root in')

    # ---- root's tls_now ------------------------------------------------------------------------
    print("root's tls_now")
    spec = importlib.util.spec_from_file_location('zigmon_root', str(ROOT_HELPER))
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    certs = W / 'certs'
    certs.mkdir()
    (W / 'mosquitto').mkdir()
    (W / 'nginx.conf').write_text('server {\n    listen 443 ssl;\n    server_name mqtt.house.example;\n'
                                  '    ssl_certificate %s/server.pem;\n    ssl_certificate_key %s/server.key;\n'
                                  '    ssl_trusted_certificate %s/server.ca;\n}\n' % (certs, certs, certs))
    (certs / 'server.key').write_text(LEAF_KEY)
    (certs / 'server.ca').write_text(ROOT + INT)
    (certs / 'server.pem').write_text(LEAF)
    now = R.tls_now()
    cc = now.get('chain_check') or {}
    check(now.get('verify') == 'ok', "the old check changed: %r" % now.get('verify'))
    check(cc.get('ok') is False and cc.get('missing') == 'Test Chain Intermediate' and cc.get('sent') == 0,
          'the leaf alone: %r' % cc)
    (certs / 'server.pem').write_text(LEAF + INT)
    cc = R.tls_now().get('chain_check') or {}
    check(cc.get('ok') is True and cc.get('sent') == 1 and cc.get('up_to') == 'Test Chain Root'
          and not cc.get('self_signed'), 'leaf and intermediate: %r' % cc)
    # a company root: trusted from the trusted file, the self-signed ones only
    os.environ['ZIGMON_TEST_CA_BUNDLE'] = str(W / 'none.pem')
    cc = R.tls_now().get('chain_check') or {}
    check(cc.get('ok') is True, 'a company root in the trusted file: %r' % cc)
    (certs / 'server.ca').write_text(INT)
    cc = R.tls_now().get('chain_check') or {}
    check(cc.get('ok') is False, 'an intermediate in the trusted file was taken as a root: %r' % cc)
    os.environ['ZIGMON_TEST_CA_BUNDLE'] = str(BUNDLE)
    (certs / 'server.pem').write_text(SELF)
    (certs / 'server.key').write_text(SELF_KEY)
    cc = R.tls_now().get('chain_check') or {}
    check(cc.get('self_signed') is True and cc.get('ok') is True, 'self-signed: %r' % cc)

    # ---- told afterwards, once -----------------------------------------------------------------
    print('check_certificate')
    look = {'tls': {'info': {'cn': 'mqtt.house.example', 'subject': 'CN=mqtt.house.example',
                             'not_after': 2000000000.0 + 86400 * 400},
                    'chain_check': {'ok': False, 'sent': 0, 'missing': 'Test Chain Intermediate',
                                    'self_signed': False}}}
    d.root_read = lambda name: look if name == 'look.json' else {}
    del TOLD[:]
    d.check_certificate()
    d.check_certificate()
    hit = [m for m, _k in TOLD if 'does not send the intermediate authority (Test Chain Intermediate)' in m]
    check(len(hit) == 1, 'told %d times: %r' % (len(hit), TOLD))
    look['tls']['chain_check'] = {'ok': True, 'sent': 1}
    del TOLD[:]
    d.check_certificate()
    check(not [m for m, _k in TOLD if 'intermediate' in m], 'told of a whole chain: %r' % TOLD)

    # ---- the card ------------------------------------------------------------------------------
    print('the card')
    page = (HERE / 'web' / 'index.php').read_text()
    for words in ('now.chain_check', "'incomplete - the authority '", 'zigmon fetches the missing link itself',
                  "'self-signed - no chain;", "'complete ('"):
        check(words in page, 'the card has no %s' % words)
finally:
    httpd.shutdown()
    shutil.rmtree(str(W), ignore_errors=True)

if bad:
    print('%d FAILED' % len(bad))
    sys.exit(1)
print('all good')
