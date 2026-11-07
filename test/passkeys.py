#!/usr/bin/env python3
"""5.43: signing in with a passkey (Touch ID, Face ID, Windows Hello) in place
of the name and the password - and unlocking with one in place of the PIN -
and the dashboard made at home on an iPad. Fails on 5.42.1, which has none of
it.

  * off by default: no options given, nothing taken, the sign-in page has no
    button; switched on in Settings - Signing in, as an administrator;
  * a software authenticator (an EC P-256 key made by openssl, the
    authenticatorData, clientDataJSON and attestationObject built here, CBOR
    and all) makes a passkey for a password account and for a PIN account,
    signs the one in (a sign-in as a password makes) and unlocks the other
    (for the while asked for, as the PIN does);
  * refused: another page (origin), another name (rpId), a challenge used
    twice, one run out, one given to another account, no user verification,
    a bad signature, a counter going back, a passkey of another account, one
    removed, an address in place of a name;
  * the rules of the password hold for it: an address kept out is kept out,
    wrong passwords from an address hold its passkeys back and a passkey's
    refusals count against the address, an account switched off opens
    nothing, a password still to be changed is changed first;
  * nothing of a key, a challenge or a sign-in in the log or the events;
  * the real page (php -S and Chromium with a virtual authenticator): a
    passkey added in Your account, then signing in with it on the sign-in
    page, and a PIN account unlocking with one; and on an iPad (Playwright's
    iPad Pro 11, both ways round) the icon, the manifest and the home-screen
    meta, with the desktop page measured the same as before.

    python3 test/passkeys.py
"""
import hashlib
import http.cookiejar
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-passkeys-check-'))
API_PORT, PHP_PORT, OLD_PORT = 19621, 19622, 19623
SHOTS = os.environ.get('ZIGMON_SHOTS', '')
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def tidy():
    for p in PROCS:
        try:
            p.terminate()
            p.wait(5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    shutil.rmtree(str(W), ignore_errors=True)


__import__('atexit').register(tidy)              # a check that throws leaves nothing running either


def finish():
    for p in PROCS:
        try:
            p.terminate()
            p.wait(5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    shutil.rmtree(str(W), ignore_errors=True)
    print('passkeys: %s' % ('%d failed' % len(bad) if bad else 'all good'))
    os._exit(1 if bad else 0)


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

if not hasattr(zigmon, 'pk_cbor'):
    check(False, 'zigmon has no passkeys at all')
    finish()

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [],
                      'mqtt_host': '', 'log_file': str(W / 'zigmon.log'), 'log_to_journal': False,
                      'state_dir': str(W / 'state'), 'login_tries': 5, 'login_wait_min': 15,
                      'session_idle_min': 240, 'session_hours': 720, 'public_view': True})
(W / 'state').mkdir()
d = zigmon.Daemon()
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)
d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
d.account_add('petr', 'viewer', 'petr pass 12', must_change=False, quiet=True)
d.account_add('kuchyn', 'operator', '4826', kind='pin', quiet=True)
HOST = 'house.example.org'
ORIGIN = 'https://' + HOST


def call(path, body=None, sess=None, client='192.168.40.10', host=HOST, method=None):
    h = {'Content-Type': 'application/json', 'X-Zigmon-Token': d.token, 'X-Zigmon-Client': client}
    if host:
        h['X-Zigmon-Host'] = host
    if sess:
        h['X-Zigmon-Session'] = sess
    r = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=h,
                               data=None if body is None else json.dumps(body).encode(),
                               method=method or ('GET' if body is None else 'POST'))
    try:
        with urllib.request.urlopen(r, timeout=60) as x:
            return x.status, json.loads(x.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'{}')
        except ValueError:
            return e.code, {}


def login(name, pw, client='192.168.40.10'):
    return call('/api/auth/login', {'name': name, 'password': pw}, client=client)


# ---- a software authenticator -------------------------------------------------------------
def b64e(data):
    import base64
    return base64.urlsafe_b64encode(bytes(data)).decode('ascii').rstrip('=')


def cbor(v):
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | info]) + n.to_bytes(size, 'big')
    if isinstance(v, bool):
        return bytes([0xf5 if v else 0xf4])
    if isinstance(v, int):
        return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, bytes):
        return head(2, len(v)) + v
    if isinstance(v, str):
        raw = v.encode()
        return head(3, len(raw)) + raw
    if isinstance(v, list):
        return head(4, len(v)) + b''.join(cbor(x) for x in v)
    if isinstance(v, dict):
        return head(5, len(v)) + b''.join(cbor(k) + cbor(x) for k, x in v.items())
    raise TypeError(v)


class Device(object):
    """A passkey on a made-up device: its own P-256 key, made by openssl."""
    n = 0

    def __init__(self, rp=HOST, counting=False):
        Device.n += 1
        self.key = str(W / ('dev%d.pem' % Device.n))
        subprocess.run(['openssl', 'ecparam', '-name', 'prime256v1', '-genkey', '-noout', '-out', self.key],
                       check=True, capture_output=True)
        der = subprocess.run(['openssl', 'ec', '-in', self.key, '-pubout', '-outform', 'DER'],
                             check=True, capture_output=True).stdout
        point = der[-65:]
        self.x, self.y = point[1:33], point[33:]
        self.cred = os.urandom(16)
        self.rp, self.count, self.counting, self.handle = rp, 0, counting, b''

    def sign(self, data):
        return subprocess.run(['openssl', 'dgst', '-sha256', '-sign', self.key], input=data, check=True,
                              capture_output=True).stdout

    def make(self, opts, origin=ORIGIN, flags=0x45, rp=None, name='this device', fmt='none',
             challenge=None, kind='webauthn.create', self_sign=False):
        pk = opts['publicKey']
        self.handle = zigmon.pk_b64d(pk['user']['id'])
        client = json.dumps({'type': kind, 'challenge': challenge or pk['challenge'], 'origin': origin,
                             'crossOrigin': False}).encode()
        cose = cbor({1: 2, 3: -7, -1: 1, -2: self.x, -3: self.y})
        ad = (hashlib.sha256((rp or self.rp).encode()).digest() + bytes([flags]) + struct.pack('>I', self.count)
              + b'\0' * 16 + struct.pack('>H', len(self.cred)) + self.cred + cose)
        stmt = {}
        if self_sign:
            stmt = {'alg': -7, 'sig': self.sign(ad + hashlib.sha256(client).digest())}
        att = cbor({'fmt': fmt, 'attStmt': stmt, 'authData': ad})
        return {'step': 'finish', 'name': name, 'clientDataJSON': b64e(client), 'attestationObject': b64e(att)}

    def get(self, opts, origin=ORIGIN, flags=0x05, rp=None, count=None, handle=None, spoil=False,
            challenge=None, minutes=None):
        pk = opts['publicKey']
        if count is None:
            if self.counting:
                self.count += 1
            count = self.count
        client = json.dumps({'type': 'webauthn.get', 'challenge': challenge or pk['challenge'],
                             'origin': origin, 'crossOrigin': False}).encode()
        ad = hashlib.sha256((rp or self.rp).encode()).digest() + bytes([flags]) + struct.pack('>I', count)
        sig = self.sign(ad + hashlib.sha256(client).digest())
        if spoil:
            sig = sig[:-3] + bytes([sig[-3] ^ 1]) + sig[-2:]
        out = {'id': b64e(self.cred), 'clientDataJSON': b64e(client), 'authenticatorData': b64e(ad),
               'signature': b64e(sig), 'userHandle': b64e(self.handle if handle is None else handle)}
        if minutes:
            out['minutes'] = minutes
        return out


def begin(client='192.168.40.10', host=HOST):
    return call('/api/auth/passkey/begin', {}, client=client, host=host)


def use(dev, client='192.168.40.10', host=HOST, **kw):
    c, o = begin(client, host)
    if c != 200:
        return c, o
    return call('/api/auth/passkey/login', dev.get(o, **kw), client=client, host=host)


def register(dev, sess, host=HOST, **kw):
    c, o = call('/api/auth/passkey/register', {'step': 'begin'}, sess, host=host)
    if c != 200:
        return c, o
    return call('/api/auth/passkey/register', dev.make(o, **kw), sess, host=host)


T_OWNER = login('owner', 'owner pass 12')[1].get('token', '')
T_JANA = login('jana', 'jana pass 12')[1].get('token', '')
T_PETR = login('petr', 'petr pass 12')[1].get('token', '')
T_PIN = call('/api/auth/login', {'pin': '4826', 'minutes': 15})[1].get('token', '')
check(T_OWNER and T_JANA and T_PIN, 'the accounts of the test could not sign in')

# ---- off by default ------------------------------------------------------------------------
print('off by default')
check(zigmon.DEFAULTS.get('passkeys') is False, 'passkeys are not off by default')
c, r = call('/api/auth/whoami')
check(c == 200 and r.get('passkeys') is False, 'whoami does not say passkeys are off: %r' % r)
c, r = begin()
check(c == 403 and 'switched off' in r.get('error', ''), 'options for a sign-in were given while off: %s %r' % (c, r))
c, r = call('/api/auth/passkey/register', {'step': 'begin'}, T_JANA)
check(c == 403 and 'switched off' in r.get('error', ''), 'a passkey could be begun while off: %s %r' % (c, r))
dev_off = Device()
d._pk_waiting['made-up'] = {'kind': 'login', 'name': '', 'rp': HOST, 'at': time.time()}
c, r = call('/api/auth/passkey/login', dev_off.get({'publicKey': {'challenge': 'made-up'}}))
check(c == 403 and 'switched off' in r.get('error', ''), 'a passkey was weighed while off: %s %r' % (c, r))
c, r = call('/api/auth/passkeys', sess=T_JANA)
check(c == 200 and r.get('on') is False and r.get('passkeys') == [], 'the list does not say off: %r' % r)
rc = d.runtime_config()
check(rc.get('passkeys', {}).get('kind') == 'switch', 'passkeys is not a switch in the settings')
check(bool(zigmon.Daemon.SETTINGS_LOCKED.search('passkeys')), 'passkeys may be set by a script')

# ---- switched on by an administrator ------------------------------------------------------
print('switched on')
c, r = call('/api/config', {'passkeys': 1}, T_JANA)
check(c == 403, 'an operator switched passkeys on: %s %r' % (c, r))
c, r = call('/api/config', {'passkeys': 1}, T_OWNER)
check(c == 200 and zigmon.CONFIG.get('passkeys'), 'an administrator could not switch passkeys on: %s %r' % (c, r))

# ---- making passkeys ------------------------------------------------------------------------
print('making passkeys')
c, r = call('/api/auth/passkey/register', {'step': 'begin'})
check(c == 403, 'a passkey was begun without a sign-in: %s %r' % (c, r))
c, o = call('/api/auth/passkey/register', {'step': 'begin'}, T_JANA)
pk = o.get('publicKey') or {}
check(c == 200 and pk.get('rp', {}).get('id') == HOST and pk.get('attestation') == 'none'
      and pk.get('authenticatorSelection', {}).get('userVerification') == 'required'
      and {-7, -257} <= {x['alg'] for x in pk.get('pubKeyCredParams', [])}
      and len(zigmon.pk_b64d(pk.get('challenge', ''))) == 32, 'the options to make one are not right: %r' % o)
check(zigmon.pk_b64d(pk.get('user', {}).get('id', '')) != b'jana' and pk.get('user', {}).get('name') == 'jana',
      'the user handle is the name itself')
for host in ('192.168.40.2', '192.168.40.2:443', '[fd00::1]', '[fd00::1]:8443'):
    c, r = call('/api/auth/passkey/register', {'step': 'begin'}, T_JANA, host=host)
    check(c == 400 and 'by its name' in r.get('error', ''), 'a passkey was begun on the address %s: %s %r'
          % (host, c, r))
c, r = begin(host='10.0.0.5')
check(c == 400 and 'not by an address' in r.get('error', ''), 'a sign-in was begun on an address: %r' % r)

JANA = Device()
c, r = register(JANA, T_JANA, name='iPad')
check(c == 200 and r.get('passkey', {}).get('name') == 'jana' and r['passkey'].get('host') == HOST
      and 'pem' not in r['passkey'], 'the passkey of a password account was not made: %s %r' % (c, r))
check(len(d.passkeys) == 1 and list(d.passkeys.values())[0]['pem'].startswith('-----BEGIN PUBLIC KEY-----'),
      'the public key was not kept as a PEM')
db = __import__('sqlite3').connect(str(W / 'z.db'))
check(db.execute('SELECT COUNT(*) FROM passkeys').fetchone()[0] == 1, 'the passkey is not in the database')
KITCHEN = Device()
c, r = register(KITCHEN, T_PIN, name='kitchen iPad')
check(c == 200 and r.get('passkey', {}).get('name') == 'kuchyn', 'the passkey of a PIN account was not made: %s %r'
      % (c, r))
OWNER = Device()
c, r = register(OWNER, T_OWNER, fmt='packed', self_sign=True, name='Mac')
check(c == 200, 'a passkey with packed self attestation was refused: %s %r' % (c, r))
c, r = register(Device(), T_OWNER, fmt='packed', name='bad self')
check(c == 400, 'a packed self attestation without a signature was taken: %s %r' % (c, r))
c, r = register(Device(), T_OWNER, fmt='tpm', name='tpm')
check(c == 400, 'an attestation of a kind not asked for was taken: %s %r' % (c, r))
c, r = register(JANA, T_JANA, name='again')
check(c == 400 and 'already' in r.get('error', ''), 'the same passkey was made twice: %s %r' % (c, r))

# what a making is refused for
c, o = call('/api/auth/passkey/register', {'step': 'begin'}, T_JANA)
c, r = call('/api/auth/passkey/register', Device().make(o), T_PETR)
check(c == 400 and 'another account' in r.get('error', ''), 'a challenge given to jana made a passkey for petr: '
      '%s %r' % (c, r))
c, r = call('/api/auth/passkey/register', Device().make(o), T_JANA)
check(c == 400 and 'waiting for' in r.get('error', ''), 'the challenge was there for a second try: %s %r' % (c, r))
c, o = call('/api/auth/passkey/register', {'step': 'begin'}, T_JANA)
c, r = call('/api/auth/passkey/register', Device().make(o, flags=0x41), T_JANA)
check(c == 400 and 'check who you are' in r.get('error', ''), 'a passkey without user verification was made: %r' % r)
c, o = call('/api/auth/passkey/register', {'step': 'begin'}, T_JANA)
c, r = call('/api/auth/passkey/register', Device().make(o, origin='https://evil.example.net'), T_JANA)
check(c == 400 and 'another page' in r.get('error', ''), 'a passkey made on another page was taken: %r' % r)
c, o = call('/api/auth/passkey/register', {'step': 'begin'}, T_JANA)
c, r = call('/api/auth/passkey/register', Device(rp='evil.example.net').make(o), T_JANA)
check(c == 400 and 'another name' in r.get('error', ''), 'a passkey for another rpId was taken: %r' % r)
c, o = call('/api/auth/passkey/register', {'step': 'begin'}, T_JANA)
c, r = call('/api/auth/passkey/register', Device().make(o, kind='webauthn.get'), T_JANA)
check(c == 400, 'a get answer was taken as a create: %r' % r)
d.account_add('newbie', 'operator', 'newbie pass 1', must_change=True, quiet=True)
T_NEW = login('newbie', 'newbie pass 1')[1].get('token', '')
c, r = call('/api/auth/passkey/register', {'step': 'begin'}, T_NEW)
check(c == 403 and 'change your password' in r.get('error', ''), 'a password still to be changed made a passkey: '
      '%s %r' % (c, r))

# ---- signing in with one ----------------------------------------------------------------------
print('signing in with one')
c, o = begin()
check(c == 200 and o['publicKey'].get('rpId') == HOST and o['publicKey'].get('allowCredentials') == []
      and o['publicKey'].get('userVerification') == 'required', 'the options of a sign-in are not right: %r' % o)
c, r = call('/api/auth/passkey/login', JANA.get(o))
check(c == 200 and r.get('token') and r.get('who', {}).get('name') == 'jana'
      and r['who'].get('kind') == 'password' and r.get('must_change') is False,
      'a password account was not signed in with its passkey: %s %r' % (c, r))
T_PK = r.get('token', '')
pw_keys = set(login('jana', 'jana pass 12')[1]) - {'passkey'}
check(set(r) - {'passkey'} == pw_keys, 'a passkey sign-in answers otherwise than a password: %r vs %r'
      % (sorted(r), sorted(pw_keys)))
row = d.signins.get(d._token_hash(T_PK)) or {}
check(row and row['expires'] - row['created'] == 720 * 3600, 'the passkey sign-in does not last as a password\'s')
c, r = call('/api/auth/whoami', sess=T_PK)
check(c == 200 and (r.get('who') or {}).get('name') == 'jana', 'the passkey sign-in is not a sign-in: %r' % r)
c, r = call('/api/plug/switch', {'name': 'nothing'}, T_PK)
check(c == 404, 'the passkey sign-in may not do what an operator does: %s %r' % (c, r))
c, r = call('/api/config', {'battery_warn': 25}, T_PK)
check(c == 403, 'the passkey sign-in of an operator changed a setting: %s %r' % (c, r))
check(d.passkeys[b64e(JANA.cred)].get('last_used'), 'the passkey\'s last use is not kept')

print('unlocking with one')
c, o = begin()
c, r = call('/api/auth/passkey/login', KITCHEN.get(o, minutes=30))
check(c == 200 and r.get('who', {}).get('kind') == 'pin' and r.get('who', {}).get('name') == 'kuchyn'
      and r.get('minutes') == 30 and abs(r.get('until', 0) - time.time() - 1800) < 10,
      'a PIN account was not unlocked with its passkey for the while asked: %s %r' % (c, r))
T_KPK = r.get('token', '')
c, r = call('/api/auth/whoami', sess=T_KPK)
check((r.get('who') or {}).get('kind') == 'pin' and 0 < (r.get('who') or {}).get('left', 0) <= 1800,
      'the unlock does not count down as the PIN\'s does: %r' % r)
pin_keys = set(call('/api/auth/login', {'pin': '4826', 'minutes': 5})[1]) - {'passkey'}
c, o = begin()
c, r = call('/api/auth/passkey/login', KITCHEN.get(o))
check(c == 200 and r.get('minutes') == 15 and set(r) - {'passkey'} == pin_keys,
      'an unlock with a passkey answers otherwise than the PIN: %r' % r)

# ---- what a sign-in is refused for ------------------------------------------------------------------
print('what is refused')
n = [0]


def addr():
    n[0] += 1
    return '192.168.41.%d' % n[0]


def refused(code_body, words, what):
    c, r = code_body
    check(c in (400, 401, 403) and words in r.get('error', '') and not r.get('token'),
          '%s was not refused as it should be: %s %r' % (what, c, r))


refused(use(JANA, addr(), origin='https://evil.example.net'), 'another page', 'another origin')
refused(use(JANA, addr(), origin='http://' + HOST), 'another page', 'plain http')
refused(use(JANA, addr(), rp='evil.example.net'), 'another name', 'another rpId')
ip = addr()
c, o = begin(ip)
refused(call('/api/auth/passkey/login', JANA.get(o), client=ip, host='other.example.org'),
        'another name', 'a challenge given for another name')
c, o = begin(ip)
first = JANA.get(o)
c, r = call('/api/auth/passkey/login', first, client=ip)
check(c == 200, 'a good sign-in failed: %r' % r)
refused(call('/api/auth/passkey/login', first, client=ip), 'waiting for', 'a replayed answer')
c, o = begin(ip)
d._pk_waiting[o['publicKey']['challenge']]['at'] -= 301
refused(call('/api/auth/passkey/login', JANA.get(o), client=ip), 'run out', 'a challenge five minutes old')
refused(use(JANA, addr(), flags=0x01), 'check who you are', 'no user verification')
refused(use(JANA, addr(), flags=0x04), 'anybody there', 'no user presence')
refused(use(JANA, addr(), spoil=True), 'signature', 'a bad signature')
c, o = begin(ip)
c, r = call('/api/auth/passkey/login', dict(JANA.get(o), id=b64e(KITCHEN.cred)), client=ip)
refused((c, r), 'another account', 'the answer of one passkey under the id of another')
c, o = begin(ip)
fake = JANA.get(o)
fake['userHandle'] = b64e(d._pk_user_id('owner'))
refused(call('/api/auth/passkey/login', fake, client=ip), 'another account', 'a passkey of jana saying owner')
STRANGER = Device()
refused(use(STRANGER, addr()), 'not known here', 'a passkey never made here')
ip = addr()
c, r = call('/api/auth/passkey/login', {'id': b64e(JANA.cred), 'clientDataJSON': '!!', 'authenticatorData': '',
                                        'signature': ''}, client=ip)
check(c in (400, 401), 'garbage was not refused: %s %r' % (c, r))

COUNTER = Device(counting=True)
c, r = register(COUNTER, T_OWNER, name='security key')
check(c == 200, 'a counting passkey could not be made: %r' % r)
c, r = use(COUNTER, addr())
check(c == 200, 'a counting passkey did not sign in: %r' % r)
c, r = use(COUNTER, addr())
check(c == 200, 'a counting passkey did not sign in twice: %r' % r)
refused(use(COUNTER, addr(), count=1), 'counter went back', 'a counter going back')
refused(use(COUNTER, addr(), count=COUNTER.count), 'counter went back', 'a counter standing still')
check(any('counter went back' in e['detail'] and e['level'] == 'crit'
          for e in d.store.events(limit=50, kind='security')), 'a counter going back is not said as bad')

# removed, by its owner; one of another account by somebody who is not an administrator
c, r = call('/api/auth/passkeys', {'do': 'delete', 'id': b64e(OWNER.cred)}, T_JANA)
check(c == 403, 'jana removed a passkey of the owner: %s %r' % (c, r))
c, r = call('/api/auth/passkeys', {'do': 'rename', 'id': b64e(OWNER.cred), 'name': 'mine'}, T_JANA)
check(c == 403, 'jana renamed a passkey of the owner: %s %r' % (c, r))
c, r = call('/api/auth/passkeys?name=owner', sess=T_JANA)
check(c == 403, 'jana read the passkeys of the owner: %s %r' % (c, r))
c, r = call('/api/auth/passkeys?all=1', sess=T_OWNER)
check(c == 200 and {x['name'] for x in r.get('passkeys', [])} >= {'jana', 'kuchyn', 'owner'}
      and not any('pem' in x for x in r['passkeys']), 'an administrator does not see every passkey: %r' % r)
c, r = call('/api/auth/passkeys', {'do': 'rename', 'id': b64e(JANA.cred), 'name': 'iPad of Jana'}, T_JANA)
check(c == 200 and d.passkeys[b64e(JANA.cred)]['label'] == 'iPad of Jana', 'a passkey could not be renamed: %r' % r)
SPARE = Device()
check(register(SPARE, T_JANA, name='spare')[0] == 200, 'a second passkey of jana was not made')
c, r = call('/api/auth/passkeys', {'do': 'delete', 'id': b64e(SPARE.cred)}, T_JANA)
check(c == 200 and b64e(SPARE.cred) not in d.passkeys, 'jana could not remove her own passkey: %r' % r)
refused(use(SPARE, addr()), 'not known here', 'a removed passkey')
c, r = call('/api/auth/passkeys', {'do': 'delete', 'id': b64e(COUNTER.cred), 'owner': 'owner'}, T_OWNER)
check(c == 200 and b64e(COUNTER.cred) not in d.passkeys, 'an administrator could not remove a passkey: %r' % r)

# ---- the rules of the password hold for it ------------------------------------------------------------
print('the rules of the password')
d.account_change('jana', by='test', disabled=True)
refused(use(JANA, addr()), 'switched off', 'the passkey of an account switched off')
d.account_change('jana', by='test', disabled=False)
check(use(JANA, addr())[0] == 200, 'the passkey did not sign in once the account was on again')
d.account_change('jana', by='test', must_change=True)
c, r = use(JANA, addr())
check(c == 200 and r.get('must_change') is True, 'a password to be changed was not said at a passkey sign-in: %r' % r)
c, r2 = call('/api/plug/switch', {'name': 'nothing'}, r.get('token'))
check(c == 403 and 'change your password' in r2.get('error', ''), 'a passkey went round the password to change: '
      '%s %r' % (c, r2))
d.account_change('jana', by='test', must_change=False)
# wrong passwords from an address hold its passkeys back
ip = '203.0.113.9'
for _ in range(5):
    login('jana', 'not the password', client=ip)
c, r = use(JANA, ip)
check(c == 429 and not r.get('token'), 'a passkey went round the wait of wrong passwords: %s %r' % (c, r))
# ...and wrong PINs
ip = '203.0.113.10'
for _ in range(5):
    call('/api/auth/login', {'pin': '0000', 'minutes': 5}, client=ip)
c, r = use(KITCHEN, ip)
check(c == 429, 'a passkey went round the wait of wrong PINs: %s %r' % (c, r))
# ...and a passkey's own refusals count against the address
ip = '203.0.113.11'
for _ in range(5):
    use(JANA, ip, spoil=True)
c, r = login('jana', 'jana pass 12', client=ip)
check(c == 429, 'refused passkeys do not count against the address: %s %r' % (c, r))
c, r = use(JANA, ip)
check(c == 429, 'an address past its tries still signs in with a passkey: %s %r' % (c, r))
# an address kept out is kept out
d.store.block('203.0.113.12', until=time.time() + 3600, why='test', auto=False)
c, r = begin('203.0.113.12')
check(c == 403 and 'blocked' in r.get('error', ''), 'a blocked address was given a challenge: %s %r' % (c, r))
c, r = use(JANA, '203.0.113.12')
check(c == 403 and not r.get('token'), 'a blocked address signed in with a passkey: %s %r' % (c, r))
# an account removed takes its passkeys with it
d.account_drop('petr', by='test')
c, r = register(Device(), T_PETR)
check(c == 403, 'a removed account made a passkey: %s %r' % (c, r))
# twenty at the most
d.account_add('many', 'viewer', 'many pass 12', must_change=False, quiet=True)
T_MANY = login('many', 'many pass 12')[1].get('token', '')
for i in range(zigmon.PASSKEY_MOST):
    register(Device(), T_MANY, name='n%d' % i)
c, r = register(Device(), T_MANY)
check(c == 400 and 'most' in r.get('error', ''), 'more than %d passkeys were made: %s %r'
      % (zigmon.PASSKEY_MOST, c, r))
d.account_drop('many', by='test')
check(not any(x['name'] == 'many' for x in d.passkeys.values())
      and not db.execute("SELECT COUNT(*) FROM passkeys WHERE name='many'").fetchone()[0],
      'an account removed left its passkeys behind')
check(len(d.store.passkeys_all()) == len(d.passkeys), 'the database and the memory disagree about the passkeys')
# switched off again: nothing taken, the passkeys kept
call('/api/config', {'passkeys': 0}, T_OWNER)
c, r = use(JANA, addr())
check(c == 403 and 'switched off' in r.get('error', ''), 'a passkey was taken once switched off again: %r' % r)
check(b64e(JANA.cred) in d.passkeys, 'switching passkeys off removed them')
call('/api/config', {'passkeys': 1}, T_OWNER)

# ---- nothing of a key or a sign-in written down ---------------------------------------------------
print('nothing written down')
time.sleep(1.5)
logged = (W / 'zigmon.log').read_text() if (W / 'zigmon.log').exists() else ''
events = json.dumps(d.store.events(limit=1000))
secret_bits = [T_PK, T_KPK, T_JANA, b64e(JANA.cred), b64e(KITCHEN.cred), JANA.x.hex(), b64e(JANA.x)]
for pem in [r['pem'] for r in d.passkeys.values()]:
    secret_bits.append(pem.splitlines()[1])
for bit in secret_bits:
    check(bit not in logged, 'the log holds a key, an id or a sign-in: %s...' % bit[:12])
    check(bit not in events, 'the events hold a key, an id or a sign-in: %s...' % bit[:12])
check('added a passkey (iPad) for house.example.org' in events, 'making a passkey is not in the events')
check('signed in with a passkey' in events and 'unlocked with a passkey' in events,
      'signing in with a passkey is not in the events')
check('removed the passkey' in events, 'removing a passkey is not in the events')

# ---- through the relay: the page's names, the cookie, the cross-site check ------------------------------
print('through the relay')
shutil.copytree(str(HERE / 'web'), str(W / 'web'))
api_php = (W / 'web' / 'zigmon-api.php').read_text()
api_php = api_php.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
api_php = api_php.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
(W / 'web' / 'zigmon-api.php').write_text(api_php)
(W / 'token').write_text(d.token)
have_php = bool(shutil.which('php'))


def serve(folder, port):
    for _ in range(3):
        p = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % port, '-t', str(folder)], cwd=str(folder),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                             env=dict(os.environ, PHP_CLI_SERVER_WORKERS='4'))
        for _ in range(50):
            try:
                socket.create_connection(('127.0.0.1', port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        time.sleep(0.3)
        if p.poll() is None:
            PROCS.append(p)
            return p
        time.sleep(3)                           # the port is somebody else's for a moment
    return None


if have_php and serve(W / 'web', PHP_PORT):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def page(what, body=None, headers=None, host='localhost:%d' % PHP_PORT):
        h = {'Content-Type': 'application/json', 'Host': host, 'Origin': 'http://' + host}
        h.update(headers or {})
        r = urllib.request.Request('http://127.0.0.1:%d/?api=%s' % (PHP_PORT, what), headers=h,
                                   data=None if body is None else json.dumps(body).encode(),
                                   method='GET' if body is None else 'POST')
        try:
            with opener.open(r, timeout=60) as x:
                return x.status, json.loads(x.read() or b'{}')
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b'{}')
            except ValueError:
                return e.code, {}
    LOCAL = Device(rp='localhost')
    c, r = page('login', {'name': 'owner', 'password': 'owner pass 12'})
    check(c == 200 and 'token' not in r, 'the relay did not sign in, or handed out the token: %r' % r)
    c, o = page('passkey-register', {'step': 'begin'})
    check(c == 200 and o.get('publicKey', {}).get('rp', {}).get('id') == 'localhost',
          'the relay does not say which name the page is on: %s %r' % (c, o))
    c, r = page('passkey-register', LOCAL.make(o, origin='http://localhost:%d' % PHP_PORT, rp='localhost'))
    check(c == 200, 'a passkey could not be made through the relay: %s %r' % (c, r))
    c, r = page('passkeys')
    check(c == 200 and any(x['host'] == 'localhost' for x in r.get('passkeys', [])), 'the relay does not list them')
    page('logout', {})
    c, o = page('passkey-begin', {})
    check(c == 200 and o.get('publicKey', {}).get('rpId') == 'localhost', 'no sign-in options through the relay')
    c, r = page('passkey-login', LOCAL.get(o, origin='http://localhost:%d' % PHP_PORT, rp='localhost'))
    check(c == 200 and r.get('who', {}).get('name') == 'owner' and 'token' not in r,
          'no sign-in with a passkey through the relay, or the token handed to the page: %s %r' % (c, r))
    check(any(ck.name == 'zigmon_session' and ck.has_nonstandard_attr('HttpOnly') for ck in jar),
          'the passkey sign-in is not kept in the HttpOnly cookie')
    c, r = page('whoami')
    check((r.get('who') or {}).get('name') == 'owner', 'the cookie of a passkey sign-in signs nobody in')
    for what in ('passkey-begin', 'passkey-login', 'passkey-register', 'passkeys-do'):
        c, r = page(what, {}, headers={'Origin': 'https://evil.example.net', 'Sec-Fetch-Site': 'cross-site'})
        check(c == 403 and 'another site' in r.get('error', ''), '%s was let in from another site: %s %r'
              % (what, c, r))
    c, o = page('passkey-begin', {}, host='127.0.0.1:%d' % PHP_PORT)
    check(c == 400 and 'by its name' in o.get('error', ''), 'a sign-in was begun on an address through the relay')
    c, r = page('manifest')
    icons = {i.get('sizes'): i for i in r.get('icons', [])}
    check(r.get('display') == 'standalone' and r.get('orientation') == 'any' and '192x192' in icons
          and '512x512' in icons and icons['512x512'].get('type') == 'image/png',
          'the manifest has no PNG icons, or is not standalone: %r' % r)
    for size in ('180', '192', '512'):
        raw = urllib.request.urlopen('http://127.0.0.1:%d/?api=icon&size=%s' % (PHP_PORT, size), timeout=20).read()
        ok = raw[:8] == b'\x89PNG\r\n\x1a\n' and struct.unpack('>II', raw[16:24]) == (int(size), int(size)) \
            and raw[25] == 2                                      # colour type 2: RGB, nothing see-through
        check(ok, 'the %s icon is not an opaque PNG of that size' % size)
    html = urllib.request.urlopen('http://127.0.0.1:%d/' % PHP_PORT, timeout=20).read().decode()
    for bit in ('rel="apple-touch-icon"', 'name="apple-mobile-web-app-capable"', 'name="mobile-web-app-capable"',
                'name="apple-mobile-web-app-title"', 'name="apple-mobile-web-app-status-bar-style"',
                'rel="manifest"'):
        check(bit in html, 'the page has no %s' % bit)
else:
    print('  SKIPPED: the relay (no php here)')

# ---- the real page, in Chromium ----------------------------------------------------------------
# The page as 5.42.1 shipped it (the release package) beside this one, both
# relaying to the daemon above: the desk is measured on both and must come
# out the same.
PAGE_JS = r'''
const { chromium, devices } = require('playwright');
const cfg = JSON.parse(process.env.PK_CFG);
const out = {};
const wait = ms => new Promise(r => setTimeout(r, ms));
async function shot(p, name) { if (cfg.shots) { try { await p.screenshot({path: cfg.shots + '/' + name}); } catch (e) {} } }
async function vauth(ctx, page) {
  const cdp = await ctx.newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  await cdp.send('WebAuthn.addVirtualAuthenticator', {options: {protocol: 'ctap2', transport: 'internal',
    hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true}});
  return cdp;
}
async function post(p, what, body) {
  return p.evaluate(async ([w, b]) => {
    const r = await fetch('?api=' + w, {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b)});
    let d = {}; try { d = await r.json(); } catch (e) {}
    return {status: r.status, body: d};
  }, [what, body]);
}
const measure = () => {
  const r = s => { const e = document.querySelector(s); if (!e) return null; const b = e.getBoundingClientRect();
    const cs = getComputedStyle(e);
    return [Math.round(b.x), Math.round(b.y), Math.round(b.width), Math.round(b.height), cs.paddingLeft, cs.paddingRight,
            cs.paddingTop, cs.paddingBottom, cs.fontSize, cs.display, cs.overflowY]; };
  return {body: r('body'), wrap: r('.wrap'), header: r('header'), tabs: r('.tabs'), lock: r('#lockpill'),
          panel: r('section.panel:not([hidden])'), card: r('section.panel:not([hidden]) .card'),
          lockcard: r('#lock-card'), nav: r('#control-nav'), main: r('.ctl-main'), toggle: r('#lock-toggle'),
          html: document.documentElement.className.replace(/\bbooting\b/, '').trim().split(/\s+/).sort().join(' ')};
};
async function page(b, url, opts, init) {
  const ctx = await b.newContext(opts || {viewport: {width: 1600, height: 1000}});
  if (init) await ctx.addInitScript(init);
  const p = await ctx.newPage();
  p.setDefaultTimeout(15000);
  p.errors = [];
  p.on('pageerror', e => p.errors.push(String(e).slice(0, 200)));
  await p.goto(url);
  await wait(1500);
  return [ctx, p];
}
(async () => {
  const b = await chromium.launch();
  try {
    // ---- the desk, before and after ----
    for (const [which, base] of [['before', cfg.old], ['after', cfg.now]]) {
      const [ctx, p] = await page(b, base + '/');
      out['desk_' + which] = await p.evaluate(measure);
      await shot(p, 'desktop-1600-overview-' + which + '.png');
      await p.goto(base + '/#control/sec-access'); await p.reload(); await wait(1800);
      out['deskctl_' + which] = await p.evaluate(measure);
      await shot(p, 'desktop-1600-control-' + which + '.png');
      await ctx.close();
    }
    // ---- an iPad, both ways round, before and after ----
    for (const [orient, dev] of [['portrait', devices['iPad Pro 11']], ['landscape', devices['iPad Pro 11 landscape']]]) {
      for (const [which, base] of [['before', cfg.old], ['after', cfg.now]]) {
        const [ctx, p] = await page(b, base + '/', dev);
        out['ipad_' + orient + '_' + which] = await p.evaluate(() => {
          const ib = document.querySelector('.btn.iconbtn');
          return {ios: document.documentElement.classList.contains('ios'),
                  touch: !!document.querySelector('link[rel="apple-touch-icon"]'),
                  capable: !!document.querySelector('meta[name="apple-mobile-web-app-capable"][content="yes"]'),
                  title: (document.querySelector('meta[name="apple-mobile-web-app-title"]') || {}).content || '',
                  coarse: matchMedia('(pointer: coarse)').matches,
                  ibh: ib ? getComputedStyle(ib).minHeight : null,
                  wide: document.documentElement.classList.contains('app-shell-root'),
                  scrollW: document.documentElement.scrollWidth, w: innerWidth};
        });
        await shot(p, 'ipad-' + orient + '-overview-' + which + '.png');
        await ctx.close();
      }
    }
    // ...turned round while open: the layout follows
    {
      const dev = devices['iPad Pro 11'];
      const [ctx, p] = await page(b, cfg.now + '/', dev);
      await p.setViewportSize({width: 1194, height: 834});
      await p.evaluate(() => window.dispatchEvent(new Event('orientationchange')));
      await wait(1200);
      out.turned = await p.evaluate(() => ({wide: document.documentElement.classList.contains('app-shell-root'),
                                            scrollW: document.documentElement.scrollWidth, w: innerWidth}));
      await shot(p, 'ipad-turned-to-landscape-after.png');
      await ctx.close();
    }
    // ---- the keyboard on the screen (a visualViewport that shrinks) ----
    const fakeVV = () => {
      const t = new EventTarget(); let h = window.innerHeight || 834;
      Object.defineProperty(t, 'height', {get: () => h}); t.offsetTop = 0; t.offsetLeft = 0; t.scale = 1;
      Object.defineProperty(t, 'width', {get: () => window.innerWidth});
      window.__vv = (v) => { h = v; t.dispatchEvent(new Event('resize')); };
      Object.defineProperty(window, 'visualViewport', {value: t, configurable: true});
    };
    for (const [which, base] of [['before', cfg.old], ['after', cfg.now]]) {
      const [ctx, p] = await page(b, base + '/#control/sec-access', devices['iPad Pro 11 landscape'], fakeVV);
      await p.focus('#ctl-find');
      await p.evaluate(() => window.__vv(420));
      await wait(300);
      const up = await p.evaluate(() => ({kb: document.body.classList.contains('kb-up'), h: document.body.style.height,
        header: getComputedStyle(document.querySelector('header')).display}));
      if (which === 'after') await shot(p, 'ipad-landscape-keyboard-after.png');
      await p.evaluate(() => window.__vv(window.innerHeight));
      await p.evaluate(() => document.activeElement.blur());
      await wait(400);
      const down = await p.evaluate(() => ({kb: document.body.classList.contains('kb-up'), h: document.body.style.height,
        header: getComputedStyle(document.querySelector('header')).display}));
      out['kb_' + which] = {up: up, down: down};
      await ctx.close();
    }
    // ---- a passkey of a password account, added in Your account ----
    const [A, pa] = await page(b, cfg.now + '/');
    await vauth(A, pa);
    out.loginA = (await post(pa, 'login', {name: 'owner', password: 'owner pass 12'})).status;
    await pa.reload(); await wait(1500);
    await pa.click('#lockpill');
    await pa.waitForSelector('#pk-add');
    await wait(900);
    // the list as the server has it, drawn - not counted while it is still on its way
    await pa.waitForSelector('#zmodal-body .pk-list[data-n]');
    const rowsA = await pa.evaluate(() => Number(document.querySelector('#zmodal-body .pk-list').dataset.n));
    await pa.click('#pk-add');
    await pa.waitForFunction(n => Number((document.querySelector('#zmodal-body .pk-list') || {dataset: {}}).dataset.n || 0) > n, rowsA, {timeout: 15000});
    out.addedA = await pa.evaluate(() => Array.from(document.querySelectorAll('#zmodal-body .pk-list tbody tr'))
      .map(t => t.textContent));
    await shot(pa, 'desktop-account-passkey-added.png');
    await pa.evaluate(() => closeZModal());
    // ---- a passkey of a PIN account, added once it is unlocked ----
    const [B, pb] = await page(b, cfg.now + '/');
    await vauth(B, pb);
    out.unlockB = (await post(pb, 'unlock', {pin: '4826', minutes: 15})).status;
    await pb.goto(cfg.now + '/#control'); await pb.reload(); await wait(1800);
    // (5.47.7) the passkeys of a PIN account, from the account button: the
    // strip across Settings that had a Passkeys button of its own is gone
    out.manageB = await pb.evaluate(() => !!LOCK.who && pkShape().on);
    await pb.evaluate(() => accountMenu());
    await pb.waitForSelector('#pk-add'); await wait(900);
    // the list as the server has it, drawn - not counted while it is still on its way
    await pb.waitForSelector('#zmodal-body .pk-list[data-n]');
    const rowsB = await pb.evaluate(() => Number(document.querySelector('#zmodal-body .pk-list').dataset.n));
    await pb.click('#pk-add');
    await pb.waitForFunction(n => Number((document.querySelector('#zmodal-body .pk-list') || {dataset: {}}).dataset.n || 0) > n, rowsB, {timeout: 15000});
    out.addedB = await pb.evaluate(() => document.querySelector('#zmodal-body .pk-list tbody').textContent);
    await shot(pb, 'desktop-pin-account-passkey-added.png');
    await pb.evaluate(() => closeZModal());
    // locked again, and unlocked with the passkey in the dialogue that asks for the PIN
    await post(pb, 'lock', {});
    await pb.reload(); await wait(1800);
    await pb.click('#lockpill');
    await pb.waitForSelector('#pin-passkey:not([hidden])', {timeout: 8000});
    out.dialogB = await pb.evaluate(() => ({mode: PIN.mode, words: document.getElementById('pin-pk-go').textContent}));
    await shot(pb, 'desktop-unlock-dialog-passkey.png');
    await pb.click('#pin-pk-go');
    await pb.waitForSelector('#pinback', {state: 'hidden', timeout: 15000});
    await wait(500);
    out.unlockedB = await pb.evaluate(() => ({who: LOCK.who && LOCK.who.name, kind: LOCK.who && LOCK.who.kind,
      pill: document.getElementById('lockpill').textContent}));
    // ---- the sign-in page (a house that does not show itself): a password account signs in with its passkey ----
    out.closeView = (await post(pa, 'config-save', {public_view: 0})).status;
    await post(pa, 'logout', {});
    await pa.reload(); await wait(1500);
    out.signinPin = await pa.evaluate(() => { const o = document.getElementById('pk-or');
      return o ? {shown: !o.hidden, words: document.getElementById('pk-go').textContent} : null; });
    await pa.click('#in-other');
    out.signinName = await pa.evaluate(() => { const o = document.getElementById('pk-or');
      return o ? {shown: !o.hidden, words: document.getElementById('pk-go').textContent} : null; });
    await shot(pa, 'desktop-signin-page-passkey.png');
    await Promise.all([pa.waitForNavigation({timeout: 15000}).catch(() => {}), pa.click('#pk-go')]);
    await wait(1800);
    out.signedA = await pa.evaluate(() => (window.LOCK && LOCK.who) ? LOCK.who.name : null);
    // the same page on an iPad, and opened by an address
    {
      const [ctx, p] = await page(b, cfg.now + '/', devices['iPad Pro 11 landscape']);
      await p.click('#in-other').catch(() => {});
      await shot(p, 'ipad-landscape-signin-after.png');
      await ctx.close();
      const [ctx2, p2] = await page(b, cfg.now.replace('localhost', '127.0.0.1') + '/');
      await p2.click('#in-other').catch(() => {});
      out.byAddress = await p2.evaluate(() => { const o = document.getElementById('pk-or'), h = document.getElementById('pk-here');
        return {button: !!o && !o.hidden, why: h && !h.hidden ? h.textContent : ''}; });
      await shot(p2, 'desktop-signin-by-address.png');
      await ctx2.close();
    }
    // ---- the setting, and switched off again ----
    await pa.goto(cfg.now + '/#control/sec-access'); await pa.reload(); await wait(2200);
    out.setting = await pa.evaluate(() => { const i = document.querySelector('input[data-k="passkeys"]');
      return i ? {checked: i.checked, label: (i.closest('.set-item') || {}).textContent || ''} : null; });
    await shot(pa, 'desktop-settings-signing-in.png');
    out.off = (await post(pa, 'config-save', {passkeys: 0})).status;
    await pa.reload(); await wait(1500);
    await pa.click('#lockpill');
    await pa.waitForSelector('#pk-add'); await wait(800);
    out.offAdd = await pa.evaluate(() => ({disabled: document.getElementById('pk-add').disabled,
      why: (document.querySelector('#zmodal-body .pk-why') || {}).textContent || ''}));
    await shot(pa, 'desktop-account-passkeys-off.png');
    await pa.evaluate(() => closeZModal());
    await post(pa, 'logout', {});
    await pa.reload(); await wait(1200);
    out.offSignin = await pa.evaluate(() => ({form: !!document.getElementById('signin-form'), button: !!document.getElementById('pk-or')}));
    out.errors = pa.errors.concat(pb.errors);
  } catch (e) {
    out.error = String(e).slice(0, 400);
  }
  console.log(JSON.stringify(out));
  await b.close();
})();
'''


def browser_part():
    print('the page, in Chromium')
    node_path = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
    if not node_path or not (Path(node_path) / 'playwright').exists():
        print('  SKIPPED: no playwright here')
        return
    old = W / 'old'
    pack = sorted((HERE / 'release').glob('zigmon-5.42.1.tar.gz'))
    if not pack:
        print('  SKIPPED: the comparison with 5.42.1 (no release package of it here)')
        return
    import tarfile
    with tarfile.open(str(pack[0])) as tar:
        for name in ('index.php', 'zigmon-api.php', 'favicon.svg'):
            got = tar.extractfile('zigmon-5.42.1/web/' + name)
            old.mkdir(exist_ok=True)
            (old / name).write_bytes(got.read())
    text = (old / 'zigmon-api.php').read_text()
    text = text.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
    text = text.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
    (old / 'zigmon-api.php').write_text(text)
    if not serve(old, OLD_PORT):
        check(False, 'the page of 5.42.1 could not be served for the comparison')
        return
    (W / 'page.js').write_text(PAGE_JS)
    cfg = {'now': 'http://localhost:%d' % PHP_PORT, 'old': 'http://localhost:%d' % OLD_PORT, 'shots': SHOTS}
    got = subprocess.run(['node', str(W / 'page.js')], capture_output=True, text=True, timeout=600, cwd=str(W),
                         stdin=subprocess.DEVNULL,
                         env=dict(os.environ, NODE_PATH=node_path, PK_CFG=json.dumps(cfg)))
    try:
        o = json.loads((got.stdout.strip().splitlines() or ['{}'])[-1])
    except ValueError:
        o = {'error': (got.stdout + got.stderr)[-600:]}
    check(not o.get('error'), 'the page could not be driven: %s' % o.get('error'))
    # the desk, exactly as it was
    # (5.47.7) ...but for the strip across Settings, taken away on purpose: it
    # and what moved up into its room (the first card, the menu, the section)
    # are measured by test/review5477_lockstrip.py instead
    gone = {'desk': ('lockcard', 'toggle'), 'deskctl': ('lockcard', 'toggle', 'card', 'nav', 'main')}
    for k in ('desk', 'deskctl'):
        a, z = o.get(k + '_before'), o.get(k + '_after')
        for one in (a, z):
            for x in gone[k]:
                (one or {}).pop(x, None)
        check(a and a == z, 'the desk at 1600 is not drawn as 5.42.1 drew it (%s): %s' % (
            k, json.dumps({x: [a.get(x), z.get(x)] for x in (a or {}) if z and a.get(x) != z.get(x)})
            if a and z else 'nothing measured'))
    for orient in ('portrait', 'landscape'):
        z = o.get('ipad_%s_after' % orient) or {}
        check(z.get('ios') and z.get('touch') and z.get('capable') and z.get('title') == 'zigmon',
              'an iPad (%s) has no home-screen icon or meta: %r' % (orient, z))
        check(z.get('coarse') and (z.get('ibh') in (None, '32px')), 'an iPad\'s buttons are not sized for a finger: %r' % z)
        check(z.get('scrollW', 1) <= z.get('w', 0), 'the page is wider than an iPad %s' % orient)
        check(z.get('wide') == (orient == 'landscape'), 'the whole-width layout is %s on an iPad %s'
              % ('off' if orient == 'landscape' else 'on', orient))
    t = o.get('turned') or {}
    check(t.get('wide') and t.get('scrollW', 1) <= t.get('w', 0), 'an iPad turned onto its side keeps the narrow layout')
    kb = o.get('kb_after') or {}
    check((kb.get('up') or {}).get('kb') and (kb.get('up') or {}).get('h') == '420px'
          and (kb.get('up') or {}).get('header') == 'none',
          'the keyboard on an iPad does not make room for the box typed in: %r' % kb)
    check(kb.get('down') and not kb['down'].get('kb') and kb['down'].get('h') == '' and kb['down'].get('header') != 'none',
          'the page does not come back once the keyboard is down: %r' % kb)
    # passkeys through the real page
    check(o.get('loginA') == 200 and any('localhost' in r and '\u00b7' in r for r in (o.get('addedA') or [])),
          'a passkey was not added in Your account: %r' % o.get('addedA'))
    check(o.get('unlockB') == 200 and o.get('manageB') and 'localhost' in (o.get('addedB') or ''),
          'a PIN account could not add a passkey: %r' % [o.get('unlockB'), o.get('manageB'), o.get('addedB')])
    check((o.get('dialogB') or {}).get('mode') == 'pin' and 'Unlock with a passkey' in (o.get('dialogB') or {}).get('words', ''),
          'the dialogue asking for the PIN offers no passkey: %r' % o.get('dialogB'))
    check((o.get('unlockedB') or {}).get('who') == 'kuchyn' and (o.get('unlockedB') or {}).get('kind') == 'pin'
          and 'Editing' in (o.get('unlockedB') or {}).get('pill', ''),
          'the PIN account was not unlocked with its passkey: %r' % o.get('unlockedB'))
    check((o.get('signinPin') or {}).get('shown') and 'Unlock with a passkey' in (o.get('signinPin') or {}).get('words', ''),
          'the sign-in page offers no passkey under the PIN: %r' % o.get('signinPin'))
    check((o.get('signinName') or {}).get('shown') and 'Sign in with a passkey' in (o.get('signinName') or {}).get('words', ''),
          'the sign-in page offers no passkey under the password: %r' % o.get('signinName'))
    check(o.get('signedA') == 'owner', 'the sign-in page did not sign in with the passkey: %r' % o.get('signedA'))
    check(o.get('byAddress') and not o['byAddress'].get('button') and 'not by its address' in o['byAddress'].get('why', ''),
          'the page opened by an address does not say why there is no passkey: %r' % o.get('byAddress'))
    check(o.get('setting') and o['setting'].get('checked') and 'passkey' in o['setting'].get('label', ''),
          'Settings - Signing in has no switch for passkeys: %r' % o.get('setting'))
    check(o.get('offAdd') and o['offAdd'].get('disabled') and 'switched off' in o['offAdd'].get('why', ''),
          'with passkeys off, Add is not disabled with the reason: %r' % o.get('offAdd'))
    check(o.get('offSignin') and o['offSignin'].get('form') and not o['offSignin'].get('button'),
          'with passkeys off, the sign-in page still offers one: %r' % o.get('offSignin'))
    check(not o.get('errors'), 'the page threw: %r' % o.get('errors'))


if have_php and os.environ.get('ZIGMON_PK_NO_BROWSER') != '1':
    browser_part()
finish()
