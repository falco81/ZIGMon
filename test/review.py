#!/usr/bin/env python3
"""The faults a read through the whole application found for 5.20, each one
proved on its own: every check here fails on 5.19.2 and passes since.

    python3 test/review.py

No broker, gateway or web server is needed; one API server is started on a
port of its own for what goes over HTTP. Root's side of it - a backup made
elsewhere choosing where root writes - is in test/root.py.
"""
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

PORT = 19871
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'run' / 'api-token'), 'pin': '', 'plugs': [],
                      'sensors': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(W / 'state'),
                      'login_tries': 50, 'login_wait_min': 15, 'session_idle_min': 240,
                      'session_hours': 720, 'public_view': True})
(W / 'state').mkdir()

# ---- what the house reads and writes -------------------------------------------------
print('readings, money, lengths of time and numbers')
got = zigmon.normalise_shelly_status({'pm1:0.apower': 12.5, 'switch:0.apower': 4})
check(got.get('pm1.apower') == 12.5, 'a PM Mini (pm1) reading was dropped: %r' % got)
for text, want in (('Vas kredit je 1 247,50 Kc', 1247.5), ('kredit 1.247,50 Kč', 1247.5),
                   ('Kredit 247,50 Kc', 247.5), ('Tel 777 123 456 kredit 50,00 Kc', 50.0)):
    check(zigmon.credit_from(text) == want, 'the credit in "%s" read as %r, not %r'
          % (text, zigmon.credit_from(text), want))
parts = zigmon.credit_parts('Kredit 1 200,00 Kc, bonus kredit 300,00 Kc')
check(parts.get('credit') == 1200 and parts.get('credit_total') == 1500,
      'a grouped balance beside a bonus read wrong: %r' % parts)
for text, want in (('2h14m', 8040), ('1h30min', 5400), ('2 h 14 min', 8040)):
    check(zigmon._fact_seconds(text) == want, '"%s" read as %r seconds, not %r'
          % (text, zigmon._fact_seconds(text), want))
check(zigmon.apply_turn('1234,56', 'thousands') == '1 234,56',
      'the decimals of 1234,56 were dropped: %r' % zigmon.apply_turn('1234,56', 'thousands'))
check(zigmon._fact_round('-0.04', 1) == '0', 'a small negative rounds to "-0"')
check(zigmon.apply_turn('a, b, c', 'nth:0') == '', '{x.nth:0} said the first item')
_who = (lambda f: 'Jan N' if f == 'who' else '')
check(zigmon.condition_holds('{who} contains „Jan N“', _who),
      'a condition in Czech quotes, „like this“, was not read')
check(zigmon.unifi_generation('na') == 'WiFi 4', '802.11na was called %r' % zigmon.unifi_generation('na'))
check(zigmon.ntfy_address('https://:tk_x@[2001:db8::1]:8080/t')[0] == 'https://[2001:db8::1]:8080/t',
      'an IPv6 address lost its brackets: %r' % (zigmon.ntfy_address('https://:tk_x@[2001:db8::1]:8080/t')[0],))
check(zigmon.Daemon.sms_parts('\U0001F600' * 40) == 2, '40 emoji were counted as one message')
check(zigmon.Daemon.sms_parts('{}' * 81) == 3, '{}{}... was counted without its escapes')
zigmon.CONFIG['sms_api'] = 'cgi'
check(zigmon.Daemon.sms_number_for_gateway('777 123 456') == '777123456',
      'a national number was given a country code: %r' % zigmon.Daemon.sms_number_for_gateway('777 123 456'))
check(zigmon.Daemon.sms_number_for_gateway('+420 777 123 456') == '00420777123456', 'an international one changed')
zigmon.CONFIG['sms_api'] = 'rest'

d = zigmon.Daemon()
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)

said = d.fill_message('{repeat 300}{if loop_last}LAST{end}{end}', {})
check('LAST' in said, 'a loop of more than 200 never said its last turn')

# ---- the rules that must hold for a while ---------------------------------------------
print('a backlog of rules does not stop the rules that wait')
was = zigmon.Daemon.RULE_BACKLOG
zigmon.Daemon.RULE_BACKLOG = 5
d._rule_queue.clear()
d._for_queued = True
d._rule_queue.append(('__for__', None, None))
for _i in range(10):
    d.queue_rules('dev', 'x', {})
check('__for__' in [q[0] for q in d._rule_queue] or not d._for_queued,
      'the clock\'s marker was dropped with its flag still up: those rules never run again')
zigmon.Daemon.RULE_BACKLOG = was
d._rule_queue.clear()
d._for_queued = False


# ---- signing in ------------------------------------------------------------------------
def call(path, body=None, sess=None, client='192.168.40.10'):
    h = {'Content-Type': 'application/json', 'X-Zigmon-Token': d.token, 'X-Zigmon-Client': client}
    if sess:
        h['X-Zigmon-Session'] = sess
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


print('accounts, sign-ins and what a visitor reads')
pw0 = (W / 'state' / 'first-login.txt').read_text().split('password: ')[-1].strip()
T0 = call('/api/auth/login', {'name': 'admin', 'password': pw0})[1]['token']
call('/api/auth/password', {'old': pw0, 'new': 'the admin pass 1'}, T0)
T0 = call('/api/auth/login', {'name': 'admin', 'password': 'the admin pass 1'})[1]['token']
c, r = call('/api/accounts', {'action': 'add', 'name': 'tab', 'role': 'admin', 'kind': 'pin'}, T0)
c2, r2 = call('/api/unlock', {'pin': 'None'}, client='203.0.113.5')
check(c2 != 200 and 'tab' not in d.accounts, 'a PIN account made with no PIN can be unlocked with "None"')
d.account_add('kiosk', 'viewer', '482915', kind='pin', by='test')
c, r = call('/api/unlock', {'pin': '482915', 'minutes': 1e999})
check(c == 200, 'a minutes of infinity is an internal error: %r' % r)
# the blocked list, however its address is spelled, and the facts that tell it
d.store.block('198.51.100.7', time.time() + 3600, 'guessing passwords', auto=True)
zigmon.CONFIG['sms_to'] = '+420777123456'
for ref in ('address:198.51.100.7', 'address :198.51.100.7', 'ADDRESS:198.51.100.7'):
    c, r = call('/api/object?ref=' + urllib.parse.quote(ref))
    check(c == 403, 'the blocked list was read without signing in, as %r' % ref)
for ref in ('house', 'blocking'):
    c, r = call('/api/object?ref=' + ref)
    text = json.dumps(r)
    check(c == 200 and '198.51.100.7' not in text and 'guessing' not in text and '777123456' not in text,
          'the %s object told a visitor who is kept out, or the alert number' % ref)
c, r = call('/api/message-preview?text=' + urllib.parse.quote(
    '{blocked_list} {blocked_last_why} {sms_to} {Blocking.blocked_list} {address:198.51.100.7.why}'))
check('198.51.100.7' not in r.get('text', '') and 'guessing' not in r.get('text', '')
      and '777123456' not in r.get('text', ''), 'the preview told a visitor: %r' % r.get('text'))
c, r = call('/api/message-preview?text=' + urllib.parse.quote('{blocked_list}'), sess=T0)
check('198.51.100.7' in r.get('text', ''), 'the administrator\'s preview lost what it should show')
c, r = call('/api/object/set', {'ref': 'Settings', 'member': 'login_tries', 'value': '3'}, T0)
check(c != 200 and int(zigmon.CONFIG.get('login_tries') or 0) == 50,
      'how many wrong passwords are let try is open to a script or a text')
# ending one sign-in by an id of one letter ends nobody else
T1 = call('/api/auth/login', {'name': 'admin', 'password': 'the admin pass 1'})[1]['token']
before = len(d.signins)
for ch in '0123456789abcdef':
    call('/api/sessions', {'end': ch}, T0)
check(len(d.signins) == before, 'a prefix of one letter ended %d sign-ins' % (before - len(d.signins)))
# a PIN account's name is weighed against a password's hash, as long as any
# other name: the PIN's own hash is five times quicker, and told the name
weighed = []
_was_ok = zigmon.password_ok
zigmon.password_ok = lambda pw, stored: weighed.append(stored) or False
d.login('kiosk', 'wrong one', ip='192.168.40.11')
zigmon.password_ok = _was_ok
check(weighed and weighed[0] != d.accounts['kiosk']['pw'],
      'a PIN account\'s name is weighed against its quick PIN hash, and the time tells the name')

# ---- the page ---------------------------------------------------------------------------
print('the page')
page = (HERE / 'web' / 'index.php').read_text()
check("&& !isset($_GET['t'])\n" not in page and "!(isset($_GET['t']) && !isset($_GET['api']))" in page,
      'a request with &t= on the end skips the check for another site')
check("withPin('Back to the plan', room.name +" not in page, 'a room\'s name goes into the dialogue unescaped')
check("toISOString().slice(0, 10) + '.json'" not in page, 'the export is named by the UTC date')
check(len(re.findall(r"^\s*bell: '", page, re.M)) <= 1, 'the bell icon is there twice')
check("if (+s === 0) s = s.replace('-', '')" in page, 'fmt(-0.004) says "-0"')
check('LOCK.who.ends' in page and "who.until - Date.now()" not in page,
      'the PIN\'s countdown is by the browser\'s clock against the server\'s')
check("DBRUN.since" not in page, 'the two database jobs share one place in the log')
check("sensors: savedOrder('sensors'), buttons: savedOrder('buttons'), groups: savedGroupsAll() };" not in page,
      'every list is sent again from this page\'s old copy when one card is moved')

api.stop() if hasattr(api, 'stop') else None
d.store.flush(3.0)
sys.stdout.flush()
if bad:
    print('\n%d check(s) failed' % len(bad))
    os._exit(1)
print('every fault the 5.20 read found stays mended')
os._exit(0)
