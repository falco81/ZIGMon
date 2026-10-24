#!/usr/bin/env python3
"""Signing in to the dashboard (5.19): accounts with a name and a password, as
otp has them, in place of the PIN everybody shared.

  * the first start makes admin, its password in a file only root reads, to
    be changed before anything else is done;
  * a wrong password, a name nobody has, an account switched off: all three
    the same refusal; five from one address and that address waits;
  * the three roles: read only sees, an operator uses the house (a socket, a
    scene, a room), an administrator does everything else - and the old PIN
    opens nothing at all;
  * a new password ends every other sign-in; the last administrator can be
    neither demoted, switched off nor deleted;
  * a sign-in survives a restart of the daemon, and ends when it is not used;
  * the root command line is let in by its own key, which the web server
    cannot read - the API token alone is not enough;
  * the relay keeps the sign-in in a cookie the page's script cannot read,
    never hands the token to the page, ignores a session the page tries to
    send in a header, and shows only a sign-in page when the house is not
    public;
  * putting a database back - by the daemon or by root - keeps the accounts.

    python3 test/accounts.py
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
W = Path(tempfile.mkdtemp(prefix='zigmon-accounts-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

PORT = 19987
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'run' / 'api-token'), 'pin': '', 'plugs': [],
                      'sensors': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(W / 'state'),
                      'login_tries': 5, 'login_wait_min': 15, 'session_idle_min': 240,
                      'session_hours': 720, 'public_view': True})
(W / 'state').mkdir()
d = zigmon.Daemon()
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def call(path, body=None, sess=None, client='192.168.40.10', cli=False, token=True):
    h = {'Content-Type': 'application/json'}
    if token:
        h['X-Zigmon-Token'] = d.token
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


def login(name, pw, client='192.168.40.10'):
    return call('/api/auth/login', {'name': name, 'password': pw}, client=client)


# ---- the first administrator ------------------------------------------------------------
print('the first administrator')
first = W / 'state' / 'first-login.txt'
check(first.is_file() and (first.stat().st_mode & 0o777) == 0o600,
      'the first password is not in a file only its owner reads')
text = first.read_text() if first.is_file() else ''
check(text.startswith('name: admin\npassword: '), 'the first-login file does not say name and password')
pw0 = text.split('password: ')[-1].strip()
check(len(pw0) >= 12, 'the first password is short')
c, r = login('admin', pw0)
check(c == 200 and r.get('must_change') is True and 'token' in r, 'the first sign-in is not told to change '
      'the password: %s %r' % (c, r))
T0 = r.get('token', '')
c, r = call('/api/config', {'battery_warn': 25}, T0)
check(c == 403 and 'password' in r.get('error', ''), 'a first password not yet changed may change settings')
c, r = call('/api/auth/password', {'old': pw0, 'new': 'short'}, T0)
check(c == 400, 'a password of five letters was taken')
c, r = call('/api/auth/password', {'old': 'nope nope nope', 'new': 'the admin pass 1'}, T0)
check(c == 400, 'a password was changed without the one there is now')
c, r = call('/api/auth/password', {'old': pw0, 'new': 'the admin pass 1'}, T0)
check(c == 200 and r['who']['must_change'] is False, 'the password could not be changed: %r' % r)
check(not first.exists(), 'the first password stays on the disk after it was changed')
c, r = call('/api/config', {'battery_warn': 25}, T0)
check(c == 200, 'the sign-in that changed its password was ended with the others: %r' % r)

# ---- the PIN opens nothing ----------------------------------------------------------------
print('the PIN is gone')
for road, body in (('/api/config', {'battery_warn': 26, 'pin': '1234'}),
                   ('/api/reset', {'scope': 'events', 'pin': '1234'}),
                   ('/api/secrets', {'pin': '1234'})):
    c, r = call(road, body)
    check(c == 403, 'the old PIN still opens %s (%s)' % (road, c))
# (5.19.1: /api/unlock is back, for PIN accounts - with none made, no PIN opens it)
c, r = call('/api/unlock', {'pin': '1234', 'minutes': 15})
check(c == 403 and 'token' not in r, 'the PIN still unlocks: %s %r' % (c, r))
c, r = call('/api/export?pin=1234')
check(c == 403, 'the export is read with the PIN in the address')

# ---- wrong passwords ---------------------------------------------------------------------------
print('wrong passwords')
said = set()
for name, pw in (('admin', 'wrong one!'), ('nobody', 'wrong one!')):
    c, r = login(name, pw, client='10.1.1.1')
    said.add((c, r.get('error')))
c, r = call('/api/accounts', {'action': 'add', 'name': 'gone', 'role': 'admin', 'password': 'gone pass 1',
                              'must_change': False}, T0)
call('/api/accounts', {'action': 'disable', 'name': 'gone'}, T0)
c, r = login('gone', 'gone pass 1', client='10.1.1.1')
said.add((c, r.get('error')))
check(len(said) == 1 and list(said)[0][0] == 401,
      'a wrong password, an unknown name and an account switched off are told apart: %r' % said)
for _ in range(3):
    login('admin', 'wrong one!', client='10.1.1.1')
c, r = login('admin', 'the admin pass 1', client='10.1.1.1')
check(c == 429 and 'too many' in r.get('error', ''), 'five wrong passwords and the address does not wait '
      '(%s %r)' % (c, r))
c, r = login('admin', 'the admin pass 1', client='10.1.1.2')
check(c == 200, 'another address had to wait for one that guessed')
call('/api/accounts', {'action': 'delete', 'name': 'gone'}, T0)

# ---- the roles -------------------------------------------------------------------------------------
print('the three roles')
for name, role in (('jana', 'operator'), ('tablet', 'viewer')):
    c, r = call('/api/accounts', {'action': 'add', 'name': name, 'role': role, 'password': name + ' pass 12',
                                  'must_change': False}, T0)
    check(c == 200, 'the account %s could not be made: %r' % (name, r))
TO = login('jana', 'jana pass 12')[1].get('token', '')
TV = login('tablet', 'tablet pass 12')[1].get('token', '')
c, r = call('/api/scene/run', {'name': 'no such scene'}, TO)
check(c == 404, 'an operator may not run a scene: %s %r' % (c, r))
c, r = call('/api/hold/release', {'target': 'nothing'}, TO)
check(c != 403, 'an operator may not hand a light back to its rules: %r' % r)
for road, body in (('/api/config', {'battery_warn': 27}), ('/api/accounts', {'action': 'list'}),
                   ('/api/reset', {'scope': 'events'}), ('/api/firewall', {'action': 'look'}),
                   ('/api/secrets', {})):
    c, r = call(road, body, TO)
    check(c == 403 and 'administrator' in r.get('error', ''), 'an operator may take %s: %s %r' % (road, c, r))
c, r = call('/api/scene/run', {'name': 'no such scene'}, TV)
check(c == 403, 'a read-only account may run a scene')
for road in ('/api/export', '/api/accounts', '/api/people', '/api/sessions'):
    c, r = call(road, None, TO)
    check(c == 403, 'an operator may read %s' % road)
    c, r = call(road, None, T0)
    check(c == 200, 'an administrator may not read %s: %r' % (road, r))
c, r = call('/api/object?ref=address:192.0.2.1', None, TO)
check(c == 403, 'an operator reads a line of the blocked list')

# ---- what an operator may not switch -----------------------------------------------------
print('what an operator may not switch')
d.save_rules([{'device': 'Temp-X', 'key': 'temperature', 'op': '>=', 'value': 20, 'plug': 'notify',
               'do': 'on', 'enabled': True}])
_rule = d.rules()[0]['id']
c, r = call('/api/target/set', {'target': 'rule:%s' % _rule, 'do': 'off'}, TO)
check(c == 403 and d.rules()[0].get('enabled', True) is not False,
      'an operator switched a rule off: %s %r' % (c, r))
c, r = call('/api/target/set', {'target': 'rule:%s' % _rule, 'do': 'off'}, T0)
check(c == 200, 'an administrator could not switch a rule off: %s %r' % (c, r))

# ---- races and guessing ---------------------------------------------------------------------
print('signing in while the account changes, and guesses sent all at once')
# a password changed while a sign-in is weighing the old one: the sign-in fails,
# and the new password stays
_real_ok = zigmon.password_ok
_fired = []


def _slow_ok(pw, stored):
    got = _real_ok(pw, stored)
    if not _fired:
        _fired.append(1)
        d.account_change('tablet', by='test', password='tablet pass 34')
    return got


zigmon.password_ok = _slow_ok
c, r = login('tablet', 'tablet pass 12', client='192.168.40.30')
zigmon.password_ok = _real_ok
check(c == 401 and login('tablet', 'tablet pass 34', client='192.168.40.30')[0] == 200
      and login('tablet', 'tablet pass 12', client='192.168.40.31')[0] == 401,
      'a sign-in weighing the old password undid the new one (%s)' % c)
# thirty guesses sent at once are thirty, not one each
import threading                                         # noqa: E402
zigmon.CONFIG['login_tries'] = 3
_answers = []


def _guess():
    _answers.append(login('admin', 'a wrong guess!', client='203.0.113.77')[0])


_th = [threading.Thread(target=_guess) for _ in range(30)]
[t.start() for t in _th]
[t.join() for t in _th]
check(sum(1 for a in _answers if a == 401) <= 3, 'guesses sent all at once were each let try: %d weighed'
      % sum(1 for a in _answers if a == 401))
# guessing the name from outside does not keep the house's own people out
for _i in range(5):
    for _ip in ('203.0.113.%d' % (10 + _i), '198.51.100.%d' % (10 + _i), '192.0.2.%d' % (10 + _i)):
        login('admin', 'a wrong guess!', client=_ip)
check(login('admin', 'the admin pass 1', client='192.168.40.50')[0] == 200,
      'guessing from the internet kept the owner out at home')
zigmon.CONFIG['login_tries'] = 5
d._login_fails.clear()

TV = login('tablet', 'tablet pass 34', client='192.168.40.32')[1].get('token', '')

# ---- the command line's key stays where it is ------------------------------------------------
c, r = call('/api/secrets', {}, T0)
check(c == 200 and d.cli_key not in json.dumps(r), 'the page is shown the command line\'s key')
check('x-zigmon-cli' in zigmon.SECRET_HEADER_NAMES, 'the command line\'s key is written into the debug log')

# ---- the house shown or not ----------------------------------------------------------------------
print('who may see the house')
check(call('/api/status')[0] == 200, 'the public view does not show the house')
zigmon.CONFIG['public_view'] = 0
check(call('/api/status')[0] == 403, 'a house that is not public is shown to nobody signed in')
check(call('/api/status', None, TV)[0] == 200, 'a read-only account does not see a house that is not public')
c, r = call('/api/auth/whoami')
check(c == 200 and r.get('who') is None and r.get('public_view') is False,
      'who-am-I does not answer a page that is not signed in')
zigmon.CONFIG['public_view'] = True

# ---- the last administrator, a new password, ending sign-ins -------------------------------------
print('the accounts kept safe')
c, r = call('/api/accounts', {'action': 'role', 'name': 'admin', 'role': 'operator'}, T0)
check(c == 400 and 'last administrator' in r.get('error', ''), 'the last administrator was demoted')
c, r = call('/api/accounts', {'action': 'disable', 'name': 'admin'}, T0)
check(c == 400, 'the last administrator was switched off')
c, r = call('/api/accounts', {'action': 'delete', 'name': 'admin'}, T0)
check(c == 400, 'the last administrator was deleted')
TO2 = login('jana', 'jana pass 12', client='192.168.40.11')[1].get('token', '')
c, r = call('/api/accounts', {'action': 'password', 'name': 'jana', 'password': 'jana pass 99'}, T0)
check(c == 200, 'an administrator could not give a new password: %r' % r)
check(call('/api/scene/run', {'name': 'x'}, TO)[0] == 403 and call('/api/scene/run', {'name': 'x'}, TO2)[0] == 403,
      'the sign-ins of an account given a new password go on')
c, r = login('jana', 'jana pass 99')
check(c == 200 and r.get('must_change') is True, 'a password given by somebody else is not to be changed')
c, r = login('tablet', 'tablet pass 34', client='192.168.40.12')
TV2 = r.get('token', '')
c, r = call('/api/lock-all', {}, T0)
check(c == 200 and call('/api/auth/whoami', None, TV2)[1].get('who') is None
      and call('/api/auth/whoami', None, T0)[1].get('who') is not None,
      'signing everybody else out did not, or signed out the one asking')
c, r = call('/api/sessions', {}, T0)
check(c == 200 and all('token' not in x and 'token_hash' not in x for x in r.get('sessions', [])),
      'the list of sign-ins hands out what a sign-in is made of')

# ---- the root command line -------------------------------------------------------------------------
print('the root command line')
key_file = W / 'run' / 'cli-key'
check(key_file.is_file() and (key_file.stat().st_mode & 0o777) == 0o600, 'the command line\'s key is '
      'readable by more than its owner')
c, r = call('/api/config', {'battery_warn': 28}, client='', cli=True)
check(c == 200, 'the command line with its key is refused: %r' % r)
c, r = call('/api/config', {'battery_warn': 28}, client='')
check(c == 403, 'the API token alone - which the web server holds - changes settings')
c, r = call('/api/export', None, client='')
check(c == 403, 'the API token alone reads the export')
code, out = zigmon.api_call('/api/accounts')
check(code == 200 and any(a['name'] == 'admin' for a in out.get('accounts', [])),
      'zigmon on the command line does not read the accounts: %s' % code)

# ---- the relay ----------------------------------------------------------------------------------------
print('the relay and its cookie')
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
    srv = subprocess.Popen([php, '-S', '127.0.0.1:18098', '-t', str(web)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    B = 'http://127.0.0.1:18098/index.php'
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def page(path, body=None, headers=None):
        h = {'Content-Type': 'application/json'}
        h.update(headers or {})
        r = urllib.request.Request(B + path, data=None if body is None else json.dumps(body).encode(),
                                   headers=h, method='GET' if body is None else 'POST')
        try:
            with op.open(r, timeout=30) as x:
                return x.status, x.read().decode('utf-8', 'replace'), x.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode('utf-8', 'replace'), e.headers
    try:
        c, text, h = page('?api=login', {'name': 'admin', 'password': 'the admin pass 1'})
        cookie = h.get('Set-Cookie') or ''
        check(c == 200 and 'zigmon_session=' in cookie and 'HttpOnly' in cookie and 'SameSite=Strict' in cookie,
              'the sign-in is not kept in an HttpOnly, SameSite=Strict cookie: %s %s' % (c, cookie))
        check('token' not in json.loads(text or '{}'), 'the relay hands the sign-in\'s token to the page')
        c, text, _ = page('?api=whoami')
        check(c == 200 and json.loads(text).get('who', {}).get('name') == 'admin', 'the cookie does not sign '
              'the page in: %s' % text[:200])
        c, text, _ = page('?api=config-save', {'battery_warn': 31})
        check(c == 200, 'an administrator signed in on the page cannot save: %s' % text[:200])
        c, text, _ = page('?api=logout', {})
        c, text, _ = page('?api=whoami')
        check(json.loads(text).get('who') is None, 'signing out on the page leaves the sign-in')
        check(call('/api/config', {'battery_warn': 32}, T0)[0] == 200, 'signing out on one page ended another')
        # a session the page's script tries to send itself is not taken
        bare = urllib.request.Request(B + '?api=whoami', headers={'X-Zigmon-Session': T0})
        with urllib.request.urlopen(bare, timeout=30) as x:
            check(json.loads(x.read()).get('who') is None, 'the relay takes a sign-in from a header the page '
                  'sets: a script could carry one around')
        bare = urllib.request.Request(B + '?api=whoami&session=' + T0)
        with urllib.request.urlopen(bare, timeout=30) as x:
            check(json.loads(x.read()).get('who') is None, 'the relay takes a sign-in from the address')
        # a house that is not public: the page is a sign-in page and nothing else
        zigmon.CONFIG['public_view'] = 0
        with urllib.request.urlopen(B, timeout=30) as x:
            html = x.read().decode('utf-8', 'replace')
        check('id="signin-form"' in html and 'var INITIAL' not in html,
              'a house that is not public shows its page to somebody not signed in')
        zigmon.CONFIG['public_view'] = True
        with urllib.request.urlopen(B, timeout=30) as x:
            html = x.read().decode('utf-8', 'replace')
        check('var INITIAL' in html and 'id="pinback"' in html and 'id="signin-name"' in html,
              'the public page has no way to sign in')
    finally:
        srv.terminate()

# ---- a restart --------------------------------------------------------------------------------------
print('a restart keeps who is signed in')
d2 = zigmon.Daemon(d.store)
check(d2.session_get(T0) is not None, 'a restart of the daemon signs everybody out')
check(not first.exists(), 'a restart made a new first password although there are accounts')
zigmon.CONFIG['session_idle_min'] = 1
d2.signins[d2._token_hash(T0)]['last'] -= 120
check(d2.session_get(T0) is None, 'a sign-in not used for longer than may be goes on')
zigmon.CONFIG['session_idle_min'] = 240

# ---- a database put back -----------------------------------------------------------------------------
print('a database put back keeps the accounts')
old = W / 'old.db'
con = sqlite3.connect(str(old))
con.executescript('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);')
con.close()
before = sorted(a['name'] for a in d.store.accounts_all())
d.store.restore_from(old)
after = sorted(a['name'] for a in d.store.accounts_all())
check(before == after and before, 'a database from before 5.19 put back took the accounts away: %r' % after)
sys.path.insert(0, str(HERE / 'deploy'))
import zigmon_root                                       # noqa: E402
kept = zigmon_root.accounts_of(str(W / 'z.db'))
dest = W / 'restored.db'
shutil.copy(str(old), str(dest))
zigmon_root.accounts_into(str(dest), kept, (os.getuid(), os.getgid()))
con = sqlite3.connect(str(dest))
names = sorted(r[0] for r in con.execute('SELECT name FROM accounts'))
con.close()
check(kept and names == before, 'root putting a database back takes the accounts with it: %r' % names)

if bad:
    print('\n%d check(s) failed' % len(bad))
    sys.exit(1)
print('the dashboard signs people in by name and password, and the PIN opens nothing')
