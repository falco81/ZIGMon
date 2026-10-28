#!/usr/bin/env python3
"""Every path the web relay forwards must be one the daemon actually serves.

Run before a release. It reads both files rather than the running daemon, so
it needs nothing set up, and it catches the mistake that shipped in 2.90.0:
an endpoint written into the daemon's read branch while the page posts to it.
"""
import re
import sys
from pathlib import Path

here = Path(__file__).resolve().parent.parent
php = (here / 'web' / 'index.php').read_text()
py = (here / 'zigmon.py').read_text()

relayed = set(re.findall(r"zigmon_relay\('(/api/[a-z0-9/_-]+)", php))
relayed |= set(re.findall(r"=> '(/api/[a-z0-9/_-]+)'", php))

served = set(re.findall(r"path == '(/api/[a-z0-9/_-]+)'", py))
for group in re.findall(r"path in \(([^)]+)\)", py):
    served |= set(re.findall(r"'(/api/[a-z0-9/_-]+)'", group))

# a path the daemon answers by its opening rather than in full, such as a
# one-tap link, where the rest of the path is the link's own secret
starts = re.findall(r"path\.startswith\('(/api/[a-z0-9/_-]+)'\)", py)
missing = sorted(p for p in relayed - served
                 if not any(p.startswith(x) for x in starts))
if missing:
    print('the relay forwards paths the daemon does not serve:')
    for p in missing:
        print('   ', p)
    sys.exit(1)
print('%d relayed path(s), all served' % len(relayed))


# Every name the page calls must be one the relay serves. It caught a save
# that used a button's id as a path and answered "unknown endpoint".
import re as _re
_src = (here / 'web' / 'index.php').read_text() if 'here' in dir() else open(str(__file__).rsplit('/', 2)[0] + '/web/index.php').read()
_js = _re.search(r'<script>(.*?)</script>', _src, _re.S).group(1)
_called = set(_re.findall(r"post\('([a-z0-9-]+)'", _js)) | set(_re.findall(r"api\('([a-z0-9-]+)", _js))
_allow = set(_re.findall(r"'([a-z0-9-]+)'", _re.search(r"if \(in_array\(\$what, \[(.*?)\], true\)", _src, _re.S).group(1)))
_gets = set(_re.findall(r"\$what === '([a-z0-9-]+)'", _src))
_paths = set(_re.findall(r"'([a-z0-9-]+)' => '/api", _src))
_missing = sorted(_called - _allow - _gets - _paths)
if _missing:
    print('the page calls names the relay does not serve:')
    for _name in _missing:
        print('   %s' % _name)
    raise SystemExit(1)
print('%d name(s) the page calls, all of them served' % len(_called))

# Every name the POST map forwards must be let through the list in front of
# it: the check above counts the map itself as serving a name, and in 5.21
# the network's, the clock's and the restart's names were in the map and not
# in the list - every press of theirs answered "unknown endpoint".
_post = _re.search(r"in_array\(\$what, \[([^\]]*)\], true\) && \$_SERVER\['REQUEST_METHOD'\] === 'POST'\)", _src, _re.S)
_map = _re.search(r"\$paths = \[(.*?)\];", _src, _re.S)
if _post and _map:
    _let = set(_re.findall(r"'([a-z0-9-]+)'", _post.group(1)))
    _mapped = set(_re.findall(r"'([a-z0-9-]+)' => '/api", _map.group(1)))
    _shut = sorted(_mapped - _let)
    if _shut:
        print('the relay maps names its POST list does not let through:')
        for _name in _shut:
            print('   %s' % _name)
        raise SystemExit(1)
    print('%d name(s) the POST map forwards, every one let through' % len(_mapped))

# ?ask has to survive every hop. It is dropped in two ways that look like
# nothing at all: an nginx rewrite whose replacement holds a ? throws the
# original query away, and a relay that rebuilds the path leaves it behind.
# Either way, asking how things stand quietly becomes switching them.
php = (Path(__file__).resolve().parent.parent / 'web' / 'index.php').read_text()
conf = (Path(__file__).resolve().parent.parent / 'deploy' / 'nginx-zigmon.conf').read_text()
lost = []
for line in php.split('\n'):
    if "'/api/tap/'" in line and 'relay' in line and 'ask' not in line:
        lost.append('the relay drops ?ask: %s' % line.strip()[:70])
for line in conf.split('\n'):
    if line.strip().startswith('rewrite') and '?' in line and '$args' not in line:
        lost.append('this rewrite throws the query away: %s' % line.strip()[:70])
if lost:
    print('?ask would not arrive:')
    for line in lost:
        print('   ' + line)
    sys.exit(1)
print('?ask survives the relay and the rewrite')


# Some answers are not a view of the house but the whole of how it is set up:
# the sockets' password, the router's password and its ssh key, every person's
# phone number and MAC address, a person's own token. Those went out to
# whoever could reach the page, because public_view means anybody may watch
# the house and was taken to mean anybody may read its keys. They ask for the
# PIN whatever public_view says, and this holds the daemon to that list.
sys.path.insert(0, str(here))
sys.argv = ['zigmon']
import zigmon                                             # noqa: E402
_locked = set(zigmon.ApiHandler.ALWAYS_LOCKED)
for _must in ('/api/export', '/api/log', '/api/managed', '/api/sms/log', '/api/mqtt/acl'):
    assert _must in _locked, '%s is readable by anybody' % _must
_words = (Path(__file__).resolve().parent.parent / 'zigmon.py').read_text()
_where = _words.index('if path in self.ALWAYS_LOCKED:')
_before = _words[:_where]
assert "if not CONFIG.get('public_view', True):" not in _before.rsplit('def do_GET', 1)[-1], \
    'the lock is applied after the public_view gate, so it never runs for a public view'
print('%d read(s) hold the PIN in front of them whatever the view is set to' % len(_locked))


# A name that is read with a GET and worked with by a POST is written twice in
# the relay: once as a branch of its own, once in the map of POST names. The
# branch stands first, so without a method on it every press went out as a GET
# - refused, because a GET of these wants the PIN in a session rather than in
# a body - and the page asked for the PIN again, and again.
_posted = set(re.findall(r"'([a-z0-9-]+)' => '/api/", php))
_branches = re.findall(r"if \(\$what === '([a-z0-9-]+)'([^)]*)\) \{", php)
_both = [(name, rest) for name, rest in _branches if name in _posted]
_loose = [name for name, rest in _both if 'REQUEST_METHOD' not in rest]
if _loose:
    print('these are read and written under one name, and the reading branch takes both:')
    for name in _loose:
        print('   %s' % name)
    raise SystemExit(1)
print('%d name(s) serve a GET and a POST, each branch saying which it takes' % len(_both))


# The reads that hold the PIN in front of them are let through to a tool on
# the machine itself - the command line, which can read the database directly
# anyway - and that has to mean a tool holding the API token. Without the
# token, anything able to open a socket to the daemon could read the export,
# passwords and all: the web server's own worker most of all, which is the
# very thing an attacker would be trying to subvert.
_daemon_src = open(str(__file__).rsplit('/', 2)[0] + '/zigmon.py').read()
# Since 5.19 that tool is the root command line, and holding the token is not
# enough: the web server holds it too. The command line is let in only from
# this machine, with the token AND the key the web server cannot read.
_where = _daemon_src.index('    def _is_cli(self):')
_lines = _daemon_src[_where:_where + 900]
if '_authorised()' not in _lines or 'cli_key' not in _lines or "'127.0.0.1'" not in _lines:
    print('the command line is let into the locked reads without the token, its key and this machine')
    raise SystemExit(1)
print('the locked reads open only to the root command line holding the token and its key')

# ...and the command line has to send both on a read, or the road it was opened
# for is a road it cannot take.
if "if token is None:\n        token = read_token()" not in _daemon_src or "X-Zigmon-Cli" not in _daemon_src:
    print('the command line does not send its token and its key on a read, so the locked reads refuse it')
    raise SystemExit(1)
print('the command line sends its token and its key on reads as well as on writes')

# The locked reads are an administrator's: asked of the sign-in, never
# opened because nothing is configured (the PIN that could be left empty is
# gone, and with it the house that left it empty and was open).
_lk = _daemon_src.index('            if path in self.ALWAYS_LOCKED:')
if "d.auth_refusal(token, 'admin')" not in _daemon_src[_lk:_lk + 900]:
    print('the locked reads are not asked of an administrator\'s sign-in')
    raise SystemExit(1)
print('the locked reads are an administrator\'s, whatever is configured')


# A secret travels in an address under more than one name, and the debug log
# writes addresses out. session was not among the names it blotted - and the
# page puts one on every request it makes, so with debug on the log filled
# with working keys; a PIN written into a query was written into the log
# beside it.
_at = _daemon_src.index('SECRET_IN_PATH = re.compile')
_pattern = _daemon_src[_at:_at + 400]
for _name in ('session', 'pin', 'token', 'secret', 'password', 'code'):
    if _name not in _pattern:
        print('a %s= in an address is written out in the log' % _name)
        raise SystemExit(1)
print('a secret in an address is blotted whatever name it travels under')


# A request that names no valid sign-in signs nobody out. /api/auth/logout
# asks for nothing - the page uses it to end its own sign-in - and its
# forerunner used to clear every session when handed a token it did not know,
# so one request with a made-up token from anything that could reach the
# relay logged every editor out.
import zigmon as _zz
_zz.load_config()
_dd = _zz.Daemon()
if 'phone-user' not in _dd.accounts:
    _dd.account_add('phone-user', 'operator', 'phone pass 1', must_change=False, quiet=True)
_one, _ = _dd.login('phone-user', 'phone pass 1', '192.0.2.1')
_two, _ = _dd.login('phone-user', 'phone pass 1', '192.0.2.2')
_n = len(_dd.signins)
_dd.logout('made-up-token')
assert len(_dd.signins) == _n, 'a token nobody issued signed %d out' % (_n - len(_dd.signins))
_dd.logout(_one['token'])
assert len(_dd.signins) == _n - 1 and _dd.session_get(_two['token']), 'signing one out touched the other'
print('a token nobody issued signs nobody out; a real one signs out only itself')

# ...and the proxy's read is configuration like the router's, behind the PIN
if "'/api/proxy'" not in _daemon_src[_daemon_src.index('ALWAYS_LOCKED = ('):_daemon_src.index('ALWAYS_LOCKED = (') + 900]:
    print('/api/proxy is open to every browser while /api/mikrotik is not')
    raise SystemExit(1)
print('the proxy and the router are behind the same sign-in')


# Every command the help offers has to exist, and every command that exists
# should be findable in the help: a flag nobody lists is a flag nobody uses,
# and a line in the help for a flag that is gone is worse.
import re as _re2
_flags = set(_re2.findall(r"a\.add_argument\('(--[a-z-]+)'", _daemon_src))
_listed = set(_re2.findall(r"'zigmon (--[a-z-]+)", _daemon_src))
_missing = sorted(f for f in _listed if f not in _flags)
if _missing:
    print('the help offers flag(s) the command line does not have: %s' % ', '.join(_missing))
    raise SystemExit(1)
# ...and every command is findable in it, whether as an example of its own or
# named in the words beside another. The modifiers - the ones that only make
# sense after a command - are in the option list above and not repeated here.
_modifiers = {'--bridge', '--count', '--keys', '--limit', '--ms', '--number', '--pin', '--points',
              '--range', '--raw', '--seconds', '--text', '--types', '--json', '--no-color',
              '--force', '--secret', '--test', '--version', '--config', '--debug', '--allow-root'}
_help_block = _daemon_src[_daemon_src.index('HELP_LINES = ['):_daemon_src.index("\n]\n\n\ndef help_text")]
_nowhere = sorted(f for f in _flags
                  if f not in _modifiers and f not in _listed and f not in _help_block)
if _nowhere:
    print('command(s) the help never names at all: %s' % ', '.join(_nowhere))
    raise SystemExit(1)
# and the help is in sections rather than one long list
if _daemon_src.count("('#', '") < 4:
    print('the help is one long list again, with no headings in it')
    raise SystemExit(1)
print('every command in the help exists, and the help is in sections')


# The daemon never sends a secret's value, only whether there is one - so the
# command line must not print that answer as though it were the secret. It
# printed the word True.
_at = _daemon_src.index('def cmd_settings')
_body = _daemon_src[_at:_at + 2000]
if "kind') == 'secret'" not in _body:
    print('zigmon --settings does not treat a secret as a secret')
    raise SystemExit(1)
if "'\\u2026' + str(value)" in _body:
    print('zigmon --settings prints the last letters of something that is not the secret')
    raise SystemExit(1)
print('the command line says whether a secret is set, never what it is')


# A private ntfy is the ordinary case for a server of one's own, and urllib
# does nothing with the user and password in a URL - it leaves them there, so
# the server sees a token in the address and no credentials at all.
_plain, _none = _zz.ntfy_address('https://ntfy.sh/a-topic')
assert _plain == 'https://ntfy.sh/a-topic' and _none is None, 'a plain topic URL was meddled with'
_where, _auth = _zz.ntfy_address('https://:tk_abc123@ntfy.example.net:8443/house')
assert _where == 'https://ntfy.example.net:8443/house', 'the token stayed in the address: %s' % _where
assert _auth == 'Bearer tk_abc123', 'a token is not sent as a bearer: %r' % _auth
_where, _auth = _zz.ntfy_address('https://falco:a%40b@ntfy.example.net/house')
assert _where == 'https://ntfy.example.net/house', 'the name stayed in the address: %s' % _where
import base64 as _b64
assert _auth == 'Basic ' + _b64.b64encode(b'falco:a@b').decode(), \
    'a password with an at-sign in it was not unescaped: %r' % _auth
print('a token or a name in an ntfy address is sent as credentials, not left in the address')

# ...and where such an address turns up in a log, the part in front of the
# host goes. A token is a secret; so is the name beside it, since knowing
# which account is half of guessing it.
_hidden = _zz.ApiHandler.hide_secrets(
    'POST https://:tk_7327tbrh4064fw8g8t8@ntfy.example.net/zigmon-house')
assert 'tk_7327' not in _hidden, 'a token in an address is written into the log: %s' % _hidden
assert 'ntfy.example.net/zigmon-house' in _hidden, 'the whole address went, not just the secret'
_hidden = _zz.ApiHandler.hide_secrets('https://falco:hunter2@ntfy.example.net/x')
assert 'hunter2' not in _hidden and 'falco' not in _hidden, \
    'a name and password in an address are written into the log: %s' % _hidden
assert _zz.ApiHandler.hide_secrets('https://ntfy.sh/a-topic') == 'https://ntfy.sh/a-topic', \
    'an address with no secret in it was meddled with'
print('an address that carries a name or a token is blotted where it is written down')


# No address is ever spared by the program itself. Who is let by is the
# house's business, written in never_block and nowhere else; the only thing
# the code may recognise on its own is the machine it is running on.
import re as _re4
_allowed = {'127.0.0.1', '::1', '0.0.0.0'}
_bad = []
for _m in _re4.finditer(r"in \((?:'[^']*',?\s*)+\)", _daemon_src):
    _addresses = _re4.findall(r"'((?:\d{1,3}\.){3}\d{1,3}(?:/\d+)?|::1|[0-9a-f:]{4,}(?:/\d+)?)'", _m.group(0))
    for _one in _addresses:
        if _one not in _allowed:
            _bad.append(_one)
if _bad:
    print('the program spares addresses of its own: %s' % ', '.join(sorted(set(_bad))))
    print('who is let by belongs in never_block, which is the house\'s to write')
    raise SystemExit(1)
print('no address is spared by the program; only the machine it runs on is recognised')


# Every road that ACTS asks for the PIN. The daemon is asked rather than the
# source read: a POST with no PIN must be refused. Locking a session is the
# one road allowed through, because taking your own key away is not an act
# anybody needs protecting from.
import json as _json5
import re as _re5
import threading as _th5
import urllib.error as _ue5
import urllib.request as _ur5

_zz.CONFIG.update({"pin": "1234", "api_port": 19931})
_ask_daemon = _zz.Daemon()
_server = _zz.ApiServer(_ask_daemon)
_server.start()
_time5 = __import__('time')
_time5.sleep(0.5)


def _post_raw(road, body):
    _req = _ur5.Request('http://127.0.0.1:19931' + road, data=_json5.dumps(body).encode(),
                        headers={'Content-Type': 'application/json',
                                 'X-Zigmon-Client': '1.2.3.4',
                                 'X-Zigmon-Token': _ask_daemon.token}, method='POST')
    try:
        return _ur5.urlopen(_req, timeout=8).status
    except _ue5.HTTPError as _e:
        return _e.code
    except Exception:
        return 0


_roads = sorted(set(_re5.findall(r"if path == '(/api/[a-z0-9/_-]+)':", _daemon_src)))
_open_by_design = {'/api/lock', '/api/auth/login', '/api/auth/logout', '/api/unlock'}
_acted = []
for _road in _roads:
    if _road in _open_by_design:
        continue
    _code = _post_raw(_road, {})
    if _code not in (0, 400, 403, 404, 405, 409, 500):
        _acted.append((_road, _code))
if _acted:
    print('%d POST road(s) answered without a sign-in:' % len(_acted))
    for _r, _c in _acted[:8]:
        print('   %-28s %s' % (_r, _c))
    raise SystemExit(1)
print('%d road(s) that act, every one of them behind a sign-in' % len(_roads))


# Instant delivery has a switch of its own. An empty word used to be the only
# way to shut it, which said nothing: somebody setting up the far end could
# not tell a road that is off from one that is on and misconfigured, and got
# the same silent refusal either way.
_zz.CONFIG.update({'sms_push': 0, 'sms_push_secret': '', 'sms_enabled': 1})
_zz.CONFIG['api_port'] = 19992
_push_daemon = _zz.Daemon()
_push_server = _zz.ApiServer(_push_daemon)
_push_server.start()
_time5.sleep(0.5)


def _push(body):
    _req = _ur5.Request('http://127.0.0.1:19992/api/sms/incoming',
                        data=_json5.dumps(body).encode(),
                        headers={'Content-Type': 'application/json',
                                 'X-Zigmon-Client': '1.2.3.4'}, method='POST')
    try:
        return 200, _ur5.urlopen(_req, timeout=8).read().decode()
    except _ue5.HTTPError as _e:
        return _e.code, _e.read().decode()
    except Exception:
        return 0, ''


_code, _said = _push({'secret': 'x', 'number': '+420', 'text': 'hi'})
assert _code == 403 and 'switched off' in _said, \
    'a push while the road is off was answered %s: %s' % (_code, _said[:80])
_zz.CONFIG['sms_push'] = 1
_code, _said = _push({'secret': 'x', 'number': '+420', 'text': 'hi'})
assert _code == 403 and 'no word is set' in _said, \
    'a push with no word agreed was answered %s: %s' % (_code, _said[:80])
_zz.CONFIG['sms_push_secret'] = 'sezame'
_code, _said = _push({'secret': 'x', 'number': '+420', 'text': 'hi'})
assert _code == 403 and 'word we agreed' in _said, \
    'a push with the wrong word was answered %s: %s' % (_code, _said[:80])
_code, _said = _push({'secret': 'sezame', 'number': '+420', 'text': 'hi'})
assert _code == 200, 'a push with the right word was refused: %s %s' % (_code, _said[:80])
# ...and whatever the modem's own form calls that field. Insisting on "secret"
# or "key" made a correctly-configured Teltonika, which calls it "password",
# look like a wrong word - and the refusal said so, which sent somebody
# looking at the word rather than at its name.
for _name in ('key', 'password', 'pass', 'token'):
    _code, _said = _push({_name: 'sezame', 'number': '+420', 'text': 'hi'})
    assert _code == 200, 'a push with the word under "%s" was refused: %s' % (_name, _said[:70])
_code, _said = _push({'password': 'nope', 'number': '+420', 'text': 'hi'})
assert _code == 403, 'a push with the wrong word under "password" was let through'
_zz.CONFIG.update({'sms_push': 0, 'sms_push_secret': ''})
# With debug on, the whole of what the modem sent - which is the only way to
# stop guessing what a box on the far side of a SIM card calls its fields.
# The agreed word is never written in full, because a pushed message is
# somebody's text and the word is in it.
import base64 as _b64
_said = []
_was_log = _zz.log
_zz.log = lambda msg, level='info', **kw: _said.append('%s %s' % (level, msg))
_zz.CONFIG.update({'debug': 1, 'sms_push': 1, 'sms_push_secret': 'sezameotevrise',
                   'sms_push_base64': 1, 'sms_push_number_field': 'number',
                   'sms_push_text_field': 'text'})
_push({'password': 'sezameotevrise', 'secret': 'sezameotevrise', 'from': '+420777123456',
       'text': _b64.b64encode('svetla off'.encode()).decode()})
_zz.log = _was_log
_whole = '\n'.join(_said)
for _want, _why in (
        ('SMS push from', 'it does not say a push arrived at all'),
        ('header  User-Agent', 'it does not write down the headers the modem sent'),
        ('body    from =', 'it does not write down the fields in the body'),
        ('this house expects', 'it does not say what it was looking for'),
        ('nothing under "number"', 'it does not say which field it could not find'),
        ('taken as: from', 'it does not say what it made of the request')):
    assert _want in _whole, 'the debug account is missing something: %s' % _why
assert 'sezameotevrise' not in _whole, 'the agreed word was written down in full'
# it is described either by its name or by being the word itself, and since
# 4.47.5 the second wins wherever the value IS the word
assert ('14 char(s) ending rise' in _whole
        or '<the word, 14 char(s)>' in _whole), 'the word was not described at all'
_zz.CONFIG.update({'debug': 0, 'sms_push': 0, 'sms_push_secret': '', 'sms_push_base64': 0})
# ...and the modem's OWN headers, which the relay has to carry across: the
# daemon's request is the relay's, so without that the account showed our Host
# and our Content-Type and none of the box's.
_said[:] = []
_zz.log = lambda msg, level='info', **kw: _said.append('%s %s' % (level, msg))
_zz.CONFIG.update({'debug': 1, 'sms_push': 1, 'sms_push_secret': 'sezame'})
_push({'password': 'sezame', 'number': '+420', 'text': 'aGk=',
       '__came': {'from': '192.168.47.254', 'method': 'POST', 'uri': '/api/sms/incoming',
                  'headers': {'user-agent': 'Teltonika TRB140', 'x-device-serial': '1234567'},
                  'raw': '{"password": "sezame", "number": "+420"}'}})
_zz.log = _was_log
_whole = '\n'.join(_said)
for _want, _why in (
        ('as the modem sent it', 'it does not separate what the modem sent from what we received'),
        ('user-agent: Teltonika', 'the modem\u2019s own headers are not written down'),
        ('x-device-serial', 'only some of the modem\u2019s headers are written down'),
        ('from    192.168.47.254', 'it does not say which box it came from')):
    assert _want in _whole, 'the debug account is missing something: %s' % _why
assert 'sezame' not in _whole, 'the word appeared in full in the raw body'
assert '__came' not in _whole.split('as it reached the daemon')[-1].split('taken as')[0] \
    or 'body    __came' not in _whole, 'the carried request was read as a field of the message'
_zz.CONFIG.update({'debug': 0, 'sms_push': 0, 'sms_push_secret': ''})
# ...and the token that opens this API, which the relay sends on every request
# as X-Zigmon-Token. The debug account hid a header only when its name was
# exactly "token" or "secret", so this one went into the log whole, every push
# - it is in a log from 18 September, in full. The helper above never sent it,
# which is why nothing here noticed.
_said[:] = []
_zz.log = lambda msg, level='info', **kw: _said.append('%s %s' % (level, msg))
_zz.CONFIG.update({'debug': 1, 'sms_push': 1, 'sms_push_secret': 'sezame'})
_tok = _push_daemon.token
_req = _ur5.Request('http://127.0.0.1:19992/api/sms/incoming',
                    data=_json5.dumps({'password': 'sezame', 'number': '+420', 'text': 'aGk='}).encode(),
                    headers={'Content-Type': 'application/json', 'X-Zigmon-Client': '1.2.3.4',
                             'X-Zigmon-Token': _tok, 'X-Api-Key': 'another-secret-value'},
                    method='POST')
try:
    _ur5.urlopen(_req, timeout=8).read()
except Exception:
    pass
_zz.log = _was_log
_whole = '\n'.join(_said)
assert 'SMS push from' in _whole, 'the push was not written down at all, so nothing was checked'
assert _tok not in _whole, 'the API token was written into the log in full'
assert 'another-secret-value' not in _whole, 'a header named like a key was written down in full'
_zz.CONFIG.update({'debug': 0, 'sms_push': 0, 'sms_push_secret': ''})
print('the token that opens the API is never written into the push account')
# Two ways in, and only ever one of them. Switched off, the inbox is read and
# emptied on the beat as it always was. Switched on, nothing here touches the
# inbox at all - so there is no second copy to tell apart, nothing to skip and
# nothing to duplicate. Trying to do both at once is what made a mess of it.
_asked = [0]
_push_daemon.sms_ready = lambda: True
_push_daemon._rest = lambda path, **kw: (_asked.__setitem__(0, _asked[0] + 1), [])[1]
_zz.CONFIG.update({'sms_poll_s': 1, 'sms_enabled': 1, 'sms_api': 'rest', 'sms_push': 0})
_push_daemon._sms_last_poll = 0
_push_daemon._sms_sending = 0
_push_daemon.sms_poll()
assert _asked[0] >= 1, 'with the webhook off, the inbox is not being read at all'
_asked[0] = 0
_zz.CONFIG['sms_push'] = 1
_push_daemon._sms_last_poll = 0
_push_daemon.sms_poll()
# With the webhook on the inbox is READ, once a minute, to be emptied - and
# nothing in it is acted on, because the webhook already did. Letting the
# modem delete its own messages was the stall: its urcd fights its forwarder
# over the slot and the modem sends nothing while it does.
_tidy_acted = []
_push_daemon.sms_handle = lambda *a, **kw: (_tidy_acted.append(a), True)[1]
_push_daemon.sms_listing = lambda: [{'id': '7', 'from': '+420', 'text': 'Status'}]
_tidy_cleared = []
_push_daemon.sms_clear = lambda ids: (_tidy_cleared.extend(ids), True)[1]
_push_daemon._sms_tidied = 0
_push_daemon._sms_last_poll = 0
_push_daemon.sms_poll()
assert _tidy_cleared == [], \
    'with the webhook on and tidying off, something was deleted from here: %r' % _tidy_cleared
_zz.CONFIG['sms_tidy'] = 1
_push_daemon._sms_tidied = 0
_push_daemon._sms_tidy_now = True
_push_daemon._sms_tidy(wanted=('+420', 'Status'))
assert _tidy_cleared and _tidy_cleared[0] == '7', \
    'with tidying on, a webhook did not take its message off: %r' % _tidy_cleared
# A webhook deletes THAT message, not whatever is in the inbox. Five arriving
# together means five webhooks; deleting the lot on the first would take away
# the four whose webhooks are still on their way, and those would never be
# acted on at all - worse than not deleting.
_many = [{'id': '0', 'date': '01', 'from': '+420603364754', 'text': 'Status'},
         {'id': '1', 'date': '02', 'from': '+420603364754', 'text': 'Status'},
         {'id': '2', 'date': '03', 'from': '+420603364754', 'text': 'Help'},
         {'id': '3', 'date': '04', 'from': '+420777000111', 'text': 'Status'}]
_push_daemon.sms_listing = lambda: list(_many)
_push_daemon.sms_clear = lambda ids: ([_many.remove(m) for m in list(_many) if m['id'] in ids],
                                      True)[1]
_push_daemon._sms_tidied = 0
_push_daemon._sms_tidy_now = True
_push_daemon._sms_tidy(wanted=('+420603364754', 'Status'))
assert [m['id'] for m in _many] == ['1', '2', '3'], \
    'a webhook took more than its own message off: %r' % [m['id'] for m in _many]
# the second webhook for the same words takes the next one, in order
_push_daemon._sms_tidied = 0
_push_daemon._sms_tidy_now = True
_push_daemon._sms_tidy(wanted=('+420603364754', 'Status'))
assert [m['id'] for m in _many] == ['2', '3'], \
    'the second of two identical messages was not paired up: %r' % [m['id'] for m in _many]
# and one that is not on the modem takes nothing
_push_daemon._sms_tidied = 0
_push_daemon._sms_tidy_now = True
_push_daemon._sms_tidy(wanted=('+420603364754', 'Topeni'))
assert [m['id'] for m in _many] == ['2', '3'], \
    'a webhook for a message not on the modem deleted something else: %r' % [m['id'] for m in _many]
# ...and the delete is CHECKED, not assumed. A box that accepts a delete and
# does not do it is exactly what hands the same message over again, so the
# inbox is read back and each stuck slot tried on its own.
_stuck = [{'id': '0', 'from': '+420', 'text': 'Status'}]
_tries = []
_push_daemon.sms_listing = lambda: list(_stuck)
_push_daemon.sms_clear = lambda ids: (_tries.append(list(ids)), True)[1]
_push_daemon._sms_tidied = 0
_push_daemon._sms_tidy()
assert len(_tries) >= 2, \
    'a delete the modem ignored was taken on trust: %r' % _tries
assert _tries[-1] == ['0'], 'the stuck slot was not tried on its own: %r' % _tries
# and a modem that does delete is not pestered a second time
_ok = [{'id': '1', 'from': '+420', 'text': 'Help'}]
_tries[:] = []
_push_daemon.sms_listing = lambda: list(_ok)
_push_daemon.sms_clear = lambda ids: ([_ok.remove(m) for m in list(_ok) if m['id'] in ids],
                                      _tries.append(list(ids)), True)[2]
_push_daemon._sms_tidied = 0
_push_daemon._sms_tidy()
assert _tries == [['1']], 'a modem that deletes properly was asked twice: %r' % _tries
_zz.CONFIG['sms_tidy'] = 0
assert not _tidy_acted, 'tidying the modem acted on a message the webhook already handled'
# ...but asking by hand still works, so zigmon --sms inbox is not taken away
_asked[0] = 0
_push_daemon.sms_poll(force=True)
assert _asked[0] >= 1, 'asking for the inbox by hand stopped working'
_zz.CONFIG.update({'sms_push': 0, 'sms_poll_s': 0})
# The key that tells one message from another is the slot, the date, the
# number and the words - and a modem hands the slot back when a message is
# deleted. With a gateway that gives no date, the SECOND "Status" from the
# same phone lands in the slot the first one left and has exactly the first's
# key: taken for one already dealt with, deleted without being acted on, and
# gone. One reply and then nothing.
_inbox = []
_acted = []
_push_daemon.sms_ready = lambda: True
_push_daemon._sms_sending = 0
_push_daemon._rest = lambda path, **kw: list(_inbox) if path == '/messages/status' else []
_push_daemon.sms_clear = lambda ids: False        # as on a gateway that is slow or busy
_push_daemon.sms_handle = lambda sender, text, key='': (_acted.append(text), True)[1]
_zz.CONFIG.update({'sms_poll_s': 1, 'sms_enabled': 1, 'sms_api': 'rest', 'sms_push': 0,
                   'sms_clear_inbox': 1})
_push_daemon._sms_seen.clear()
_push_daemon._sms_first_look = False
for _i in range(4):
    _inbox[:] = [{'id': '1', 'sender': '+420603364754', 'message': 'Status', 'date': ''}]
    _push_daemon._sms_last_poll = 0
    _push_daemon.sms_poll()
assert len(_acted) == 4, \
    'four messages in the same slot with no date: %d acted on, the rest swallowed' % len(_acted)
# ...but where the gateway does give a date, one message offered three times
# is still one message
_acted[:] = []
_push_daemon._sms_seen.clear()
_inbox[:] = [{'id': '1', 'sender': '+420603364754', 'message': 'Status',
              'date': '26/09/18,12:00:01'}]
for _i in range(3):
    _push_daemon._sms_last_poll = 0
    _push_daemon.sms_poll()
assert len(_acted) == 1, \
    'the same message, dated, was acted on %d times' % len(_acted)
_zz.CONFIG.update({'sms_poll_s': 0, 'sms_enabled': 0})
# ...and where there is no slot either, the message can never be deleted - so
# remembering is all there is, however thin the key. Without this a gateway
# that gives neither would have its one message acted on again every round,
# for ever.
_acted[:] = []
_push_daemon._sms_seen.clear()
# an empty memory means the daemon has never looked, and the first look leaves
# the inbox alone on purpose - which is not what is being checked here
_push_daemon._sms_seen['something|else'] = 1
_push_daemon._sms_first_look = False
# an earlier check turned the polling off again; this one needs it on
_zz.CONFIG.update({'sms_poll_s': 1, 'sms_enabled': 1})
_push_daemon.sms_clear = lambda ids: True
_inbox[:] = [{'id': '', 'sender': '+420603364754', 'message': 'Status', 'date': ''}]
for _i in range(5):
    _push_daemon._sms_last_poll = 0
    _push_daemon.sms_poll()
assert len(_acted) == 1, \
    'a message that can never be deleted was acted on %d times' % len(_acted)
print('a message that cannot be deleted is acted on once, not on every round')
print('a message with no date is never swallowed, and a dated one is never acted on twice')
# The page redraws the SMS tab when the sms block of the status changes, and
# nothing in it moved when a text arrived - so a reply that reached the phone
# at once took until the next thing changed to appear on screen, up to a
# minute later.
_before = _push_daemon.status()['sms']
_push_daemon.sms_note('in', '+420603364754', 'Status', True, 'received',
                      key='mark-check', road='push')
_after = _push_daemon.status()['sms']
assert _before != _after, 'a message arriving changes nothing the page watches'
assert _after.get('log_n') == _before.get('log_n', 0) + 1, \
    'the count of messages did not move: %r -> %r' % (_before.get('log_n'), _after.get('log_n'))
for _k in ('ready', 'sent_today', 'people', 'commands', 'poll_s'):
    assert _k in _after, 'the sms block lost %s on the way' % _k
# While a message is going out, the pollers are held off - a small gateway
# does one thing at a time. That hold came off only where a message was queued
# or where a reply timed out, so a reply that failed for any other reason left
# it set and NOTHING READ THE INBOX for the next two minutes. With the webhook
# off that is two minutes of no texts at all, which reads as "it stopped
# working" and is the worst of these faults by a distance.
import socket as _sock9
_zz.CONFIG.update({'sms_enabled': 1, 'sms_host': '10.0.0.1', 'sms_user': 'a',
                   'sms_password': 'b', 'sms_api': 'rest', 'sms_timeout_s': 15,
                   'sms_queue': 1, 'sms_daily_cap': 0})
_push_daemon.sms_ready = lambda: True
_push_daemon.sms_modem_id = lambda: '1-1'
for _what, _boom, _why in (
        ('a reply that times out', _sock9.timeout('timed out'), 'reply'),
        ('a reply that fails outright', OSError('connection refused'), 'reply'),
        ('an alert that times out', _sock9.timeout('timed out'), 'alert'),
        ('an alert that fails outright', OSError('connection refused'), 'alert')):
    _push_daemon._sms_sending = 0
    _push_daemon._rest = (lambda e: (lambda *a, **k: (_ for _ in ()).throw(e)))(_boom)
    _push_daemon._sms_send_now('+420603364754', 'x', why=_why)
    _held = _push_daemon._sms_sending and (_time5.time() - _push_daemon._sms_sending) < 120
    assert not _held, '%s left the pollers held off; no text would arrive for two minutes' % _what
# An outgoing message is written down when it is HANDED OVER, not when the
# gateway gets round to answering. That box takes up to a minute, and a reply
# that reached the phone at once was not on the screen until it did: the
# message looked lost while it was already in the recipient's hand.
import threading as _th7
_zz.CONFIG.update({'sms_enabled': 1, 'sms_host': '10.0.0.1', 'sms_user': 'a',
                   'sms_password': 'b', 'sms_api': 'rest', 'sms_timeout_s': 15,
                   'sms_daily_cap': 0})
_push_daemon.sms_ready = lambda: True
_push_daemon.sms_modem_id = lambda: '1-1'
_push_daemon.store.set_meta('sms_log', '[]')


def _slow_send(*a, **kw):
    _time5.sleep(2.0)
    return {'success': True}


_push_daemon._rest = _slow_send
_th7.Thread(target=lambda: _push_daemon._sms_send_now('+420603364754', 'Doma jsou: Falco',
                                                      why='reply'), daemon=True).start()
_time5.sleep(0.4)
_rows = _json5.loads(_push_daemon.store.get_meta('sms_log') or '[]')
assert len(_rows) == 1 and _rows[0]['ok'] is None, \
    'a message being sent is not in the table while the gateway thinks: %r' % _rows
_time5.sleep(2.4)
_rows = _json5.loads(_push_daemon.store.get_meta('sms_log') or '[]')
assert len(_rows) == 1, 'it was written down twice: %d rows' % len(_rows)
assert _rows[0]['ok'] is True, 'it never settled as sent: %r' % _rows[0].get('ok')
# An answer to a text is handed to a worker rather than sent where the command
# was worked out. The gateway does one thing at a time and takes up to a
# minute over it: sent inline, that minute is spent inside the round of
# polling - which then reads no inbox and acts on nothing - or inside the
# webhook request, which leaves the gateway waiting and makes it send the
# message again. Both ways it looks like the house has stopped.
_sent = []


def _slow_gateway(path, method='GET', payload=None, **kw):
    if 'send' in path:
        _time5.sleep(0.8)
        _sent.append(((payload or {}).get('data') or {}).get('message', '')[:18])
        return {'success': True}
    return []


_push_daemon._rest = _slow_gateway
_push_daemon._sms_sending = 0
# this check is about order and hand-off, not the spacing the gateway needs;
# the five-second gap between sends has a check of its own
_zz.CONFIG['sms_send_gap_s'] = 0
_began = _time5.time()
for _word in ('one', 'two', 'three'):
    _push_daemon.sms_reply('+420603364754', _word)
_handed = _time5.time() - _began
assert _handed < 0.4, \
    'three answers took %.1f s to hand over; whoever worked them out waits that long' % _handed
_time5.sleep(4.0)
assert _sent == ['one', 'two', 'three'], \
    'the answers went out as %r - one at a time, in order, is what the box can take' % _sent
# The worker used to go quiet after half a minute with nothing to do and be
# started again by the next answer - a race with a plain losing side. An
# answer queued in the moment between it deciding to stop and stopping is seen
# by a worker that is still alive, so nobody sends it, and nothing after it
# goes either because nothing starts the worker again. It works, and then from
# one message on it does not, for good.
assert _push_daemon._sms_reply_worker.is_alive(), 'the answer worker is not running'
_push_daemon._sms_reply_wake.clear()
_time5.sleep(0.2)
assert _push_daemon._sms_reply_worker.is_alive(), \
    'the answer worker stops when idle; an answer queued as it goes is lost for good'
_sent[:] = []
_push_daemon.sms_reply('+420603364754', 'after the quiet')
_time5.sleep(2.5)
assert _sent and _sent[-1].startswith('after'), \
    'an answer after a quiet spell never went: %r' % _sent
# A reply the box has not acknowledged in twenty seconds is not going to be:
# on a real day every stall was 55 to 63 seconds - our patience to the second
# - and the message had gone out regardless. The full minute only held the
# next reply. Alerts keep the full patience; nobody is waiting on them.
import socket as _sk9
_seen = []


def _stalling(path, method='GET', payload=None, timeout=None, **kw):
    if 'send' in path:
        _seen.append(timeout)
        raise _sk9.timeout('timed out')
    return []


_zz.CONFIG.update({'sms_timeout_s': 60, 'sms_send_gap_s': 0})
_push_daemon._rest = _stalling
_push_daemon._sms_sending = 0
_push_daemon._sms_send_now('+420603364754', 'Doma jsou: Falco', why='reply')
_push_daemon._sms_send_now('+420603364754', 'Heating is off', why='alert')
assert _seen[0] <= 20, 'a reply waits %ss on a box that will not answer' % _seen[0]
assert _seen[1] == 60, 'an alert lost its patience: %ss' % _seen[1]
# ...and that shorter patience is a setting, not a number in the source
for _patience, _want in ((45, 45.0), (0, 60.0)):
    _zz.CONFIG['sms_reply_timeout_s'] = _patience
    _seen[:] = []
    _push_daemon._sms_hold_until = 0
    _push_daemon._sms_send_now('+420603364754', 'x', why='reply')
    assert _seen and _seen[0] == _want, \
        'with the setting at %s a reply was given %ss, not %ss' % (_patience, _seen and _seen[0], _want)
_zz.CONFIG['sms_reply_timeout_s'] = 20
assert float(_zz.DEFAULTS.get('sms_send_gap_s', 0)) >= 5 if hasattr(_zz, 'DEFAULTS') else True
# A box that has just stopped answering is still wedged; the next send fired
# straight into it was answered no better, and each one cost the whole
# patience again. After a stall nothing is sent for half a minute.
_calls = []


def _wedged_once(path, method='GET', payload=None, timeout=None, **kw):
    if 'send' in path:
        _calls.append(_time5.time())
        if len(_calls) == 1:
            raise _sk9.timeout('timed out')
        return {'success': True}
    return []


_zz.CONFIG.update({'sms_timeout_s': 2, 'sms_send_gap_s': 0})
_push_daemon._rest = _wedged_once
_push_daemon._sms_sending = 0
_push_daemon._sms_hold_until = 0
_push_daemon.sms_send('+420603364754', 'one', why='reply')
assert _push_daemon._sms_hold_until - _time5.time() > 20, \
    'a stall did not set a hold on the next send'
_push_daemon._sms_hold_until = _time5.time() + 1.0        # shortened for the check
_push_daemon.sms_send('+420603364754', 'two', why='reply')
assert _calls[1] - _calls[0] >= 0.9, \
    'the next send went straight into the wedged box, %.1fs after the stall' % (_calls[1] - _calls[0])
assert _push_daemon._sms_hold_until == 0, 'the hold stayed on after a good send'
# The box is asked how it feels six times a minute - 13,665 times in a day's
# log - and every one is two questions to a thing that struggles to answer one
# while its radio is working. It waits while a message goes out, and for half
# a minute after.
_polled = [0]
_push_daemon._rest = lambda *a, **kw: (_polled.__setitem__(0, _polled[0] + 1), [])[1]
_push_daemon._sms_sending = 0
_push_daemon._sms_sent_at = 0
_push_daemon.sms_status_poll()
assert _polled[0] > 0, 'the gateway is never asked how it is at all'
_polled[0] = 0
_push_daemon._sms_sending = _time5.time()
_push_daemon.sms_status_poll()
assert _polled[0] == 0, 'the box was asked how it feels while a message was going out'
_push_daemon._sms_sending = 0
_push_daemon._sms_sent_at = _time5.time()
_polled[0] = 0
_push_daemon.sms_status_poll()
assert _polled[0] == 0, 'the box was asked how it feels moments after a send'
_push_daemon._sms_sent_at = _time5.time() - 31
_polled[0] = 0
_push_daemon.sms_status_poll()
assert _polled[0] > 0, 'the status poll never comes back after a send'
print('the gateway is not asked how it feels while its radio is busy')
print('after a stall the gateway is left alone for a while, and a good send lifts it')
# The spacing is on everything that goes out - an answer, an alert, one sent
# by hand - and has nothing to do with which way messages arrive. It lived on
# the webhook card by mistake.
_when = []
_zz.CONFIG.update({'sms_send_gap_s': 1, 'sms_timeout_s': 5, 'sms_push': 0})
_push_daemon._rest = lambda path, method='GET', payload=None, **kw: (
    (_when.append(_time5.time()), {'success': True})[1] if 'send' in path else [])
_push_daemon._sms_sending = 0
_push_daemon._sms_hold_until = 0
for _why in ('reply', 'alert', 'hand'):
    _push_daemon.sms_send('+420603364754', 'x', why=_why)
assert len(_when) == 3, 'not everything went out: %d of three' % len(_when)
for _i in range(1, 3):
    assert _when[_i] - _when[_i - 1] >= 0.9, \
        'the spacing did not apply to a %s: %.1fs' % (('alert', 'hand')[_i - 1],
                                                      _when[_i] - _when[_i - 1])
_zz.CONFIG['sms_send_gap_s'] = 0
# A failed send is tried again only where it CERTAINLY never arrived. A
# connection refused or reset means the box never saw it, so a fresh
# connection costs nothing. A read timing out means the box took it and went
# quiet - and that message is usually on its way, so trying again is a second
# text to somebody's phone.
import urllib.error as _ue7
for _what, _boom, _want in (
        ('refused', ConnectionRefusedError('refused'), 3),
        ('reset', ConnectionResetError('reset by peer'), 3),
        ('read timeout', _sk9.timeout('timed out'), 1),
        ('URLError(timeout)', _ue7.URLError(_sk9.timeout('timed out')), 1)):
    _tries = [0]

    def _boomer(path, method='GET', payload=None, timeout=None, _e=_boom, **kw):
        if 'send' in path:
            _tries[0] += 1
            raise _e
        return []

    _push_daemon._rest = _boomer
    _push_daemon._sms_hold_until = 0
    _push_daemon._sms_sending = 0
    _push_daemon._sms_send_now('+420603364754', 'x', why='alert')
    assert _tries[0] == _want, \
        'a send that failed with %s was tried %d time(s), wanted %d' % (_what, _tries[0], _want)
print('a send is tried again only where it certainly never reached the gateway')
print('the spacing is on everything that goes out, whichever way messages come in')
print('a reply gives up on a silent box in twenty seconds; an alert keeps the full minute')
print('the answer worker does not stop, so nothing queued is ever orphaned')
print('answers are handed to a worker and go out one at a time, in order')
print('a message going out is in the table before the gateway answers, and only once')
print('a send that fails never leaves the inbox unread')
print('a message arriving moves something the page is watching')
# The webhook on and the looking set to never: the once-a-minute sweep that
# takes off what a webhook failed to delete lived behind "how often to look",
# so with that at never it never ran and the switch quietly did half its job.
_zz.CONFIG.update({'sms_push': 1, 'sms_tidy': 1, 'sms_poll_s': 0})
_push_daemon._sms_busy = False
_left = [{'id': '8', 'date': '02', 'from': '+420603364754', 'text': 'Help'}]
_looks = [0]
_push_daemon.sms_listing = lambda: (_looks.__setitem__(0, _looks[0] + 1), list(_left))[1]
_push_daemon.sms_clear = lambda ids: ([_left.remove(m) for m in list(_left) if m['id'] in ids],
                                      True)[1]
_push_daemon._sms_tidied = 0
_push_daemon._sms_last_poll = 0
_push_daemon._sms_sent_at = 0
_looks[0] = 0
for _ in range(12):
    _push_daemon._sms_last_poll = 0
    _push_daemon.sms_poll()
for _ in range(12):
    _push_daemon.sms_status_poll()
assert _looks[0] == 0, \
    'the modem\u2019s inbox was read %d time(s) on a beat; 4.59.0 read it never and never ' \
    'stalled, which is the whole finding' % _looks[0]
# ...and it IS read where a webhook has its own message to take off
_left[:] = [{'id': '8', 'date': '02', 'from': '+420603364754', 'text': 'Help'}]
_push_daemon._sms_tidied = 0
_push_daemon._sms_tidy_now = True
_push_daemon._sms_tidy(wanted=('+420603364754', 'Help'))
assert not _left, 'a webhook did not take its own message off'
_zz.CONFIG.update({'sms_push': 0, 'sms_tidy': 0, 'sms_poll_s': 0})
# ...and with the webhook OFF, the beat must beat. Everything above is about
# not touching that box needlessly, and the way to get that wrong is to stop
# touching it when it IS needed - which is the whole of the polling road.
_zz.CONFIG.update({'sms_push': 0, 'sms_tidy': 0, 'sms_poll_s': 1, 'sms_clear_inbox': 1})
_pull_inbox = []
_pull_read = [0]
_pull_cleared = []
_pull_acted = []


def _pull_rest(path, method='GET', payload=None, **kw):
    if path == '/messages/status':
        _pull_read[0] += 1
        return list(_pull_inbox)
    return []


_push_daemon._rest = _pull_rest
_push_daemon.sms_clear = lambda ids: (
    _pull_cleared.extend(ids),
    [_pull_inbox.remove(m) for m in list(_pull_inbox)
     if str(m['id']) in [str(i) for i in ids]], True)[2]
_push_daemon.sms_handle = lambda sender, text, key='', road='modem': (
    _pull_acted.append(text), True)[1]
_push_daemon._sms_first_look = False
_push_daemon._sms_sending = 0
for _word in ('Status', 'Status', 'Help', 'Temp'):
    _pull_inbox.append({'id': '1', 'sender': '+420603364754', 'message': _word, 'date': ''})
    _push_daemon._sms_last_poll = 0
    _push_daemon.sms_poll()
assert _pull_read[0] >= 4, 'with the webhook off the inbox is not being read at all'
assert _pull_acted == ['Status', 'Status', 'Help', 'Temp'], \
    'the polling road lost or reordered messages: %r' % _pull_acted
assert len(_pull_cleared) == 4, 'the polling road stopped emptying the modem: %r' % _pull_cleared
assert not _pull_inbox, 'the modem was left with messages on it'
print('with the webhook off the inbox is read, acted on and emptied, as it always was')
print('the modem is read only where a webhook has a message to take off, never on a beat')
print('two ways in, and only ever one of them touching the modem')
print('the modem\u2019s own request is carried across and written down too')
print('a pushed message is written down whole under debug, with the word blotted')
print('instant delivery has a switch, and each refusal says which of the three it is')

