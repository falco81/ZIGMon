#!/usr/bin/env python3
"""PIN accounts (5.19.1): an account that signs in with a PIN alone, the way
the dashboard unlocked before 5.19 - boxes for the digits, a while to unlock
for, "Editing 14:25" in the header - and that has a role like any other.

  * coming straight from before 5.19, the PIN in config.json becomes a PIN
    account, an administrator as it was; a house already on 5.19.0 does not
    have it opened again behind its back;
  * an administrator makes a PIN account with any role; a PIN must be 4-12
    digits or letters and differ from every other PIN;
  * /api/unlock (and ?api=unlock on the page) takes the PIN and the minutes,
    and the sign-in ends when they are up; the role holds - an operator
    unlocked with a PIN switches a socket and saves no settings;
  * a PIN account cannot sign in by name and password, and a new PIN ends
    the sign-ins of the old one;
  * a wrong PIN is counted, and five from one address make it wait;
  * root makes one with `zigmon --account-add NAME ROLE --with-pin`, and
    `--account-password` gives it a new PIN;
  * root putting a database back keeps the PIN accounts as PIN accounts;
  * the page has the digit boxes and the minutes again, and the sign-in page
    of a house that is not public asks for the PIN when there are PIN accounts.

    python3 test/pins.py
"""
import http.cookiejar
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-pins-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

PORT = 19988
zigmon.load_config()
BASE = {'api_port': PORT, 'api_host': '127.0.0.1', 'token_file': str(W / 'run' / 'api-token'), 'pin': '1234',
        'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '', 'login_tries': 5, 'login_wait_min': 15,
        'session_idle_min': 240, 'session_hours': 720, 'public_view': True}

# ---- a house on 5.19.0 already: the PIN stays shut ------------------------------------------
print('a house already on 5.19.0 keeps the PIN shut')
zigmon.CONFIG.update(BASE, db_file=str(W / 'was519.db'), state_dir=str(W / 'state519'))
(W / 'state519').mkdir()
zigmon.CONFIG['pin'] = ''
d0 = zigmon.Daemon()                     # 5.19.0's first start: admin, no PIN in config at that time
zigmon.CONFIG['pin'] = '1234'
d0 = zigmon.Daemon()                     # the next start, the PIN still in config.json
check(not d0.pin_accounts(), 'a house on 5.19.0 has the PIN of before opened again: %r'
      % [a['name'] for a in d0.pin_accounts()])
check(d0.pin_shape() == {'pin': False, 'pin_length': 0}, 'a house without PIN accounts is drawn with the '
      'PIN boxes: %r' % (d0.pin_shape(),))

# ---- straight from before 5.19: the PIN becomes an account ---------------------------------
print('the PIN of before 5.19 becomes a PIN account')
zigmon.CONFIG.update(BASE, db_file=str(W / 'z.db'), state_dir=str(W / 'state'))
(W / 'state').mkdir()
d = zigmon.Daemon()
pins = d.pin_accounts()
check(len(pins) == 1 and pins[0]['role'] == 'admin' and pins[0].get('kind') == 'pin',
      'the PIN of before is not an administrator\'s PIN account: %r'
      % [(a['name'], a['role'], a.get('kind')) for a in pins])
check('admin' in d.accounts and d.accounts['admin'].get('kind', 'password') == 'password',
      'the first admin with a password was not made beside it')
check(d.pin_shape() == {'pin': True, 'pin_length': 4}, 'the page is not told to draw four boxes: %r'
      % (d.pin_shape(),))
check(all('1234' not in str(v) for v in pins[0].values()), 'the PIN is kept as it was typed')
d = zigmon.Daemon()
check(len(d.pin_accounts()) == 1, 'the PIN of before is made into an account again at every start')
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def call(path, body=None, sess=None, client='192.168.40.10', cli=False):
    h = {'Content-Type': 'application/json', 'X-Zigmon-Token': d.token}
    if client:
        h['X-Zigmon-Client'] = client
    if sess:
        h['X-Zigmon-Session'] = sess
    if cli:
        h['X-Zigmon-Cli'] = d.cli_key
    r = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path), headers=h,
                               data=None if body is None else json.dumps(body).encode(),
                               method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(r, timeout=60) as x:
            return x.status, json.loads(x.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'{}')
        except ValueError:
            return e.code, {}


c, r = call('/api/unlock', {'pin': '1234', 'minutes': 15})
check(c == 200 and r.get('token') and r['who'].get('kind') == 'pin' and r['who']['role'] == 'admin',
      'the PIN of before does not unlock: %s %r' % (c, r))
TA = r.get('token')
left = (r.get('who') or {}).get('until', 0) - time.time()
check(14 * 60 < left <= 15 * 60 + 2, 'fifteen minutes asked for, %r given' % left)
c, r = call('/api/config', {'battery_warn': 26}, TA)
check(c == 200, 'unlocked with the administrator\'s PIN, the settings cannot be saved: %s %r' % (c, r))

# ---- an administrator makes PIN accounts -------------------------------------------------------
print('PIN accounts with a role')
c, r = call('/api/accounts', {'action': 'add', 'kind': 'pin', 'name': 'kitchen', 'role': 'operator',
                              'pin': '5678'}, TA)
check(c == 200 and any(a['name'] == 'kitchen' and a.get('kind') == 'pin' for a in r.get('accounts', [])),
      'a PIN account could not be made: %s %r' % (c, r))
c, r = call('/api/accounts', {'action': 'add', 'kind': 'pin', 'name': 'hall', 'role': 'viewer', 'pin': '5678'}, TA)
check(c == 400, 'two accounts were given the same PIN: %s %r' % (c, r))
for wrong in ('12', '12 34', '1234567890123'):
    c, r = call('/api/accounts', {'action': 'add', 'kind': 'pin', 'name': 'hall', 'role': 'viewer',
                                  'pin': wrong}, TA)
    check(c == 400, 'the PIN %r was taken' % wrong)
c, r = call('/api/accounts', {'action': 'add', 'kind': 'pin', 'name': 'hall', 'role': 'viewer', 'pin': '2468'}, TA)
check(c == 200, 'a read-only PIN account could not be made: %r' % r)

c, r = call('/api/unlock', {'pin': '5678', 'minutes': 5}, client='192.168.40.11')
check(c == 200 and r['who']['name'] == 'kitchen' and r['who']['role'] == 'operator',
      'the operator\'s PIN does not unlock as the operator: %s %r' % (c, r))
TK = r.get('token')
left = (r.get('who') or {}).get('until', 0) - time.time()
check(4 * 60 < left <= 5 * 60 + 2, 'five minutes asked for, %r given' % left)
c, r = call('/api/scene/run', {'name': 'nothing such'}, TK)
check(c != 403, 'an operator unlocked with a PIN may not run a scene: %s %r' % (c, r))
c, r = call('/api/config', {'battery_warn': 27}, TK)
check(c == 403, 'an operator unlocked with a PIN saves the settings: %s %r' % (c, r))
c, r = call('/api/unlock', {'pin': '2468', 'minutes': 5}, client='192.168.40.12')
c2, _ = call('/api/scene/run', {'name': 'nothing such'}, r.get('token'))
check(c == 200 and c2 == 403, 'a read-only PIN account runs a scene: %s %s' % (c, c2))
c, r = call('/api/auth/whoami', None, TK)
check(c == 200 and r.get('pin') is True and r.get('pin_length') == 4 and r['who'].get('until'),
      'whoami does not say how the page asks, or when the unlock ends: %r' % r)
# the page's sign-in road, with a PIN and no name, is the same unlock
c, r = call('/api/auth/login', {'pin': '5678', 'minutes': 30}, client='192.168.40.13')
check(c == 200 and r['who']['name'] == 'kitchen', 'a sign-in that carries a PIN is not taken: %s %r' % (c, r))
c, r = call('/api/auth/login', {'name': 'kitchen', 'password': '5678'}, client='192.168.40.14')
check(c == 401, 'a PIN account signs in with its name and its PIN as a password: %s %r' % (c, r))

# the while is up: the sign-in ends
d.signins[d._token_hash(TK)]['expires'] = int(time.time()) - 1
check(d.session_get(TK) is None, 'an unlock with a PIN goes on when its minutes are up')
c, _ = call('/api/scene/run', {'name': 'nothing such'}, TK)
check(c == 403, 'an unlock whose minutes are up still runs a scene')

# a new PIN ends the sign-ins of the old one
c, r = call('/api/unlock', {'pin': '5678', 'minutes': 60}, client='192.168.40.15')
TK2 = r.get('token')
c, r = call('/api/accounts', {'action': 'pin', 'name': 'kitchen', 'pin': '9753'}, TA)
check(c == 200, 'a new PIN could not be given: %s %r' % (c, r))
check(d.session_get(TK2) is None, 'the sign-in of the old PIN goes on after a new one was given')
check(call('/api/unlock', {'pin': '5678'}, client='192.168.40.16')[0] == 403, 'the old PIN still unlocks')
check(call('/api/unlock', {'pin': '9753'}, client='192.168.40.16')[0] == 200, 'the new PIN does not unlock')
c, r = call('/api/accounts', {'action': 'disable', 'name': 'kitchen'}, TA)
check(call('/api/unlock', {'pin': '9753'}, client='192.168.40.17')[0] == 403, 'a PIN account switched off unlocks')
call('/api/accounts', {'action': 'enable', 'name': 'kitchen'}, TA)

# ---- guessing ------------------------------------------------------------------------------------
print('a wrong PIN is counted')
for n in range(5):
    c, r = call('/api/unlock', {'pin': '00%02d' % n}, client='192.168.40.66')
    check(c == 403 and 'wrong PIN' in r.get('error', ''), 'a wrong PIN is answered %s %r' % (c, r))
c, r = call('/api/unlock', {'pin': '9753'}, client='192.168.40.66')
check(c == 429 and 'too many' in r.get('error', ''), 'five wrong PINs and the address does not wait: %s %r'
      % (c, r))
check(call('/api/unlock', {'pin': '9753'}, client='192.168.40.67')[0] == 200,
      'another address waits for the one that guessed')

# ---- the root command line ---------------------------------------------------------------------------
print('the root command line')
import contextlib, io                                    # noqa: E401,E402
out = io.StringIO()
with contextlib.redirect_stdout(out):
    rc = zigmon.accounts_main(['--account-add', 'porch', 'viewer', '--with-pin'])
said = out.getvalue()
made = [l.split(':', 1)[1].strip() for l in said.splitlines() if l.strip().startswith('PIN:')]
check(rc == 0 and made and len(made[0]) == 6 and d.accounts.get('porch', {}).get('kind') == 'pin',
      'zigmon --account-add NAME ROLE --with-pin makes no PIN account: %s' % said)
if made:
    check(call('/api/unlock', {'pin': made[0]}, client='192.168.40.70')[0] == 200, 'the PIN printed does not unlock')
out = io.StringIO()
with contextlib.redirect_stdout(out):
    rc = zigmon.accounts_main(['--account-password', 'porch'])
again = [l.split(':', 1)[1].strip() for l in out.getvalue().splitlines() if l.strip().startswith('PIN:')]
check(rc == 0 and again and again != made and call('/api/unlock', {'pin': again[0]}, client='192.168.40.71')[0] == 200,
      'zigmon --account-password on a PIN account gives no new PIN: %s' % out.getvalue())

# ---- root putting a database back ---------------------------------------------------------------
print('root putting a database back keeps the PIN accounts')
sys.path.insert(0, str(HERE / 'deploy'))
import zigmon_root                                       # noqa: E402
kept = zigmon_root.accounts_of(str(W / 'z.db'))
old = W / 'old.db'
con = sqlite3.connect(str(old))
con.executescript('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);'
                  'CREATE TABLE accounts (name TEXT PRIMARY KEY COLLATE NOCASE, role TEXT, pw TEXT,'
                  ' disabled INTEGER DEFAULT 0, must_change INTEGER DEFAULT 0, note TEXT, created INTEGER,'
                  ' last_in INTEGER, last_from TEXT);')
con.close()
zigmon_root.accounts_into(str(old), kept, (os.getuid(), os.getgid()))
con = sqlite3.connect(str(old))
kinds = dict(con.execute('SELECT name, kind FROM accounts'))
con.close()
check(kinds.get('kitchen') == 'pin' and kinds.get('admin') == 'password',
      'root putting a 5.19.0 database back loses which accounts have a PIN: %r' % kinds)

# ---- the page ----------------------------------------------------------------------------------------
print('the page')
src = (HERE / 'web' / 'index.php').read_text()
check('id="pindigits"' in src and 'id="unlock-minutes"' in src and 'function buildPinBoxes' in src,
      'the page has no digit boxes and no while to unlock for')
check("'Editing <span class=\"lockpill-time\">'" in src, 'the header does not count the unlock down')
php = shutil.which('php')
if not php:
    print('  (no php here: the relay is not checked)')
else:
    web = W / 'web'
    shutil.copytree(str(HERE / 'web'), str(web))
    api_php = web / 'zigmon-api.php'
    api_php.write_text(api_php.read_text().replace('const ZIGMON_PORT  = 9849;', 'const ZIGMON_PORT  = %d;' % PORT)
                       .replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';",
                                "const ZIGMON_TOKEN = '%s';" % (W / 'run' / 'api-token')))
    srv = subprocess.Popen([php, '-S', '127.0.0.1:18099', '-t', str(web)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    B = 'http://127.0.0.1:18099/index.php'
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def page(path, body=None):
        r = urllib.request.Request(B + path, data=None if body is None else json.dumps(body).encode(),
                                   headers={'Content-Type': 'application/json'},
                                   method='GET' if body is None else 'POST')
        try:
            with op.open(r, timeout=30) as x:
                return x.status, x.read().decode('utf-8', 'replace'), x.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode('utf-8', 'replace'), e.headers
    try:
        c, text, h = page('?api=unlock', {'pin': '9753', 'minutes': 10})
        cookie = h.get('Set-Cookie') or ''
        check(c == 200 and 'zigmon_session=' in cookie and 'HttpOnly' in cookie and 'token' not in json.loads(text),
              'the page\'s unlock with a PIN is not kept in the cookie: %s %s %s' % (c, cookie, text[:200]))
        c, text, _ = page('?api=whoami')
        who = json.loads(text).get('who') or {}
        check(who.get('name') == 'kitchen' and who.get('kind') == 'pin', 'the page is not signed in by its '
              'PIN: %s' % text[:200])
        c, text, _ = page('?api=unlock', {'pin': '1111'})
        check(c == 403 and 'wrong PIN' in text, 'a wrong PIN on the page: %s %s' % (c, text[:200]))
        zigmon.CONFIG['public_view'] = 0
        with urllib.request.urlopen(B, timeout=30) as x:
            html = x.read().decode('utf-8', 'replace')
        check('id="pin-form"' in html and 'id="in-pin"' in html and 'var INITIAL' not in html
              and 'id="pin-form" autocomplete="off" hidden' not in html,
              'a house that is not public does not ask for the PIN first')
        zigmon.CONFIG['public_view'] = True
    finally:
        srv.terminate()
        srv.wait()

shutil.rmtree(str(W), ignore_errors=True)
if bad:
    print('\n%d check(s) failed' % len(bad))
    sys.exit(1)
print('PIN accounts unlock as the PIN always did, each with its own role')
