#!/usr/bin/env python3
"""A read through what 5.30 - 5.37 brought (automatic certificates, the server
in front, system updates, maintenance, the web proxy, the backups to other
machines), each fault proved on its own. Every check here fails on 5.37.0.

    python3 test/review538b.py < /dev/null

No CA, root, broker or web server is needed: the daemon is made in a folder
of its own, and what it would ask of the CA or root is stood in for.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review538b-check-'))
STATE = W / 'state'
STATE.mkdir()
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


os.environ.update(ZIGMON_STATE=str(STATE), ZIGMON_ACME_SETTLE='0', ZIGMON_ACME_POLL='0.1')
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'history.db'), 'api_port': 19671, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'log_file': '', 'state_dir': str(STATE), 'acme': 1, 'acme_ca': 'custom',
                      'acme_url': 'https://ca.test.invalid/directory'})
d = zigmon.Daemon()
d.notify = lambda *a, **k: None


def left_behind():
    return sorted(p.name for p in STATE.iterdir() if p.name.startswith('zigmon-acme-'))


# ---- 1. Acme(): the folder of a conversation that never began --------------------
# A CA that does not answer, or refuses the account, raised out of Acme()
# itself: acme_order never had an object to close, and the folder - with the
# new account's private key in it once a request was signed - stayed in the
# state folder at every try (every six hours, every press of Order it now).
print('ACME: a CA that does not answer, or refuses the account, leaves nothing behind')
real_req = zigmon.Acme._req


def no_ca(self, url, data=None, method=None, accept='application/json'):
    raise zigmon.AcmeError('the CA did not answer (ca.test.invalid): no route')


zigmon.Acme._req = no_ca
try:
    zigmon.Acme(d)
    check(False, 'Acme() did not say the CA was away')
except zigmon.AcmeError:
    pass
check(left_behind() == [], 'the CA away left its folder: %r' % left_behind())

DIRECTORY = {'newNonce': 'https://ca.test.invalid/nonce', 'newAccount': 'https://ca.test.invalid/acct',
             'newOrder': 'https://ca.test.invalid/order'}


class Headers(dict):
    pass


def refusing_ca(self, url, data=None, method=None, accept='application/json'):
    h = Headers({'Replay-Nonce': 'n%d' % time.time_ns()})
    if url.endswith('/directory'):
        return json.dumps(DIRECTORY).encode(), h, 200
    if method == 'HEAD':
        return b'', h, 200
    return (json.dumps({'type': 'urn:ietf:params:acme:error:invalidContact',
                        'detail': 'contact email has an invalid domain'}).encode(), h, 400)


zigmon.Acme._req = refusing_ca
try:
    zigmon.Acme(d)
    check(False, 'Acme() did not say the CA refused the account')
except zigmon.AcmeError as e:
    check('invalid' in str(e), 'the refusal was not said: %s' % e)
keys = [str(p) for p in STATE.rglob('account.pem')]
check(not keys, 'the new account\'s private key was left behind: %r' % keys)
check(left_behind() == [], 'the account refused left its folder: %r' % left_behind())
zigmon.Acme._req = real_req


# ---- 2. acme_order: root that never answers is not "ordered" -----------------------
# acme_wait_root gives up after ten minutes with {} - and acme_order took
# that for done: the state said ordered and good for 90 days, the event said
# a certificate came, and nothing was ordered again while the certificate in
# place (never replaced) ran out. And tls_put had already said the one in
# place came from ACME, so the next order kept no copy of the uploaded one
# to go back to, and ACME looked after a certificate it never put in.
print('ACME: a certificate root never put in is not taken for ordered')


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)


sh(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes',
    '-keyout', str(W / 'k.pem'), '-out', str(W / 'c.pem'), '-days', '90', '-subj', '/CN=mqtt.house.example',
    '-addext', 'subjectAltName=DNS:mqtt.house.example'])
CERT, KEY = (W / 'c.pem').read_text(), (W / 'k.pem').read_text()


class FakeAcme(object):
    def __init__(self, dd):
        pass

    def order(self, names, say, kind=None):
        return KEY, CERT

    def close(self):
        pass


zigmon.Acme = FakeAcme
zigmon.CONFIG['acme_key'] = 'ec'
UPLOADED = {'tls': {'info': {'subject': 'CN=mqtt.house.example', 'cn': 'mqtt.house.example',
                             'issuer': 'CN=House CA', 'not_after': time.time() + 20 * 86400}}}
d.root_look = lambda fresh=False: UPLOADED
d.root_installed = lambda: True
d.root_busy = lambda: False
d.root_apply = lambda pem=None, quiet=False: 'abc123'
conf = d.tls_conf()
conf.update(managed=True, how='uploaded')
d.tls_save(conf)
zigmon.acme_wait_root = lambda dd, ident, secs=600: {}         # ten minutes, and nothing
try:
    zigmon.acme_order(d, 'mqtt.house.example', 'owner')
    raised = False
except zigmon.AcmeError:
    raised = True
st = zigmon.acme_state(d)
check(raised, 'root not answering was taken for a certificate put in')
check(st.get('ok') is False, 'the state says ordered though root never put it in: %r'
      % {k: st.get(k) for k in ('ok', 'not_after', 'said')})
check(zigmon.acme_due(d, 'mqtt.house.example') == '' and st.get('failed_at'),
      'a failed order is not tried again later (failed_at)')
check(d.tls_conf().get('how') == 'uploaded',
      'the uploaded certificate still in place is said to have come from ACME: %r' % d.tls_conf().get('how'))
check(zigmon.acme_before(d) is None, 'a copy to go back to is said to be kept')

# root refusing it outright: the same - the one in place is the uploaded one
zigmon.acme_wait_root = lambda dd, ident, secs=600: {'id': ident, 'state': 'failed', 'said': ['nginx said no']}
try:
    zigmon.acme_order(d, 'mqtt.house.example', 'owner')
except zigmon.AcmeError:
    pass
check(d.tls_conf().get('how') == 'uploaded', 'a refusal by root left how=%r' % d.tls_conf().get('how'))

# and root putting it in: ACME's from then on
zigmon.acme_wait_root = lambda dd, ident, secs=600: {'id': ident, 'state': 'done'}
zigmon.acme_order(d, 'mqtt.house.example', 'owner')
check(zigmon.acme_state(d).get('ok') is True and d.tls_conf().get('how') == 'ACME',
      'a certificate root put in is not said to be ACME\'s')


# ---- 3. Back to the one before: root refusing it changes nothing -------------------
# acme_put_back said ACME no longer renews it, the certificate in place was
# "uploaded" and forgot the one before - all before root had answered. Root
# refusing it (nginx said no, the one before had run out meanwhile) left the
# CA's certificate in place, renewed by nobody, and no button to try again.
print('Back to the one before: root refusing it leaves the CA\'s certificate in ACME\'s care')
os.environ['ZIGMON_ACME_PUT_BACK_WAIT'] = '3'
d.store.set_meta('acme_care', json.dumps({'on': True, 'at': time.time(), 'by': 'owner'}))
d.store.set_meta('acme_before', json.dumps({'how': 'uploaded', 'subject': 'CN=mqtt.house.example',
                                            'issuer': 'CN=House CA', 'not_after': time.time() + 20 * 86400,
                                            'at': time.time()}))
LOOK = {'tls': {'info': {'subject': 'CN=mqtt.house.example', 'issuer': 'CN=Test CA',
                         'not_after': time.time() + 80 * 86400}},
        'acme': {'http': False, 'port80': True, 'before': {'not_after': time.time() + 20 * 86400}}}
d.root_look = lambda fresh=False: LOOK
conf = d.tls_conf()
conf['how'] = 'ACME'
d.tls_save(conf)
ASKED = []
d.root_apply = lambda pem=None, quiet=False: ASKED.append(pem) or 'pb%d' % len(ASKED)
d.root_read = lambda name: {'id': 'pb%d' % len(ASKED), 'kind': 'apply', 'state': 'failed',
                            'said': ['nginx does not take it, so it is as it was']}
try:
    zigmon.acme_put_back(d, 'owner')
    check(False, 'root refusing the put-back was not said')
except ValueError as e:
    check('nginx' in str(e), 'root\'s words are not said: %s' % e)
check(d.tls_conf().get('how') == 'ACME', 'the CA\'s certificate in place is said to be %r' % d.tls_conf().get('how'))
check(zigmon.acme_care(d), 'ACME no longer renews the CA\'s certificate still in place')
check(zigmon.acme_before(d) is not None, 'the one before is forgotten: no button to try again')
# root putting it back: ACME leaves it alone from then on
d.root_read = lambda name: {'id': 'pb%d' % len(ASKED), 'kind': 'apply', 'state': 'done'}
zigmon.acme_put_back(d, 'owner')
check(d.tls_conf().get('how') == 'uploaded' and not zigmon.acme_care(d) and not d.store.get_meta('acme_before'),
      'a put-back root did is not taken as done')

if bad:
    print('\n%d check(s) failed' % len(bad))
    os._exit(1)
print('all well')
os._exit(0)
