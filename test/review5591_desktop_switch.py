#!/usr/bin/env python3
"""Settings - Messages - Desktop app (5.59.1): the master switch and the number of keys.

  * a new server comes with the desktop app switched off: a key can be made, but hello,
    sensors, wait, update and download are 403 {off: true} - before the key is even looked at;
  * a server that had keys before the switch came starts with it on (nothing that worked stops),
    and the choice is kept, not worked out again;
  * switched on, the app works; switched off, a poll waiting now ends at once with 403 (not 401,
    which tells the app its key was taken away); on again, a new boot and an empty ring, so what
    happened while it was off is not brought up;
  * the switch is an administrator's (an operator gets 403) and goes into the events;
  * notifier_keys_most: 20 as it comes, 50, 100 or 0 = no limit, anything else refused; the
    keys view says it; the waiting polls allowed grow with the keys;
  * the page: the hero with the switch, the setting on a card in the desktop app's section.

    python3 test/review5591_desktop_switch.py < /dev/null

Ports 20290-20291. Every secret here is made up.
"""
import json
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-ntfswitch-'))
API_PORT = 20290
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                               # noqa: E402

zigmon.log = lambda *a, **k: None
zigmon.load_config()
(W / 'state').mkdir()
zigmon.CONFIG.update({
    'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1', 'token_file': str(W / 'token'),
    'pin': '', 'sensors': [], 'plugs': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(W / 'state'),
    'debug': 0, 'blacklist': 0, 'public_view': False})

# ---- a server from before the switch: keys kept, no word of the switch ----------------------
print('a server that had keys before starts with it on')
old_db = W / 'old.db'
zigmon.CONFIG['db_file'] = str(old_db)
d0 = zigmon.Daemon()
d0.store.set_meta('notifier_keys', json.dumps([{'id': 'abc123', 'name': 'Old PC', 'devices': [], 'created': 1.0,
                                                 'by': 'x', 'last_at': None, 'last_from': None, 'hint': 'zz',
                                                 'hash': '0' * 64}]))
d0.store.set_meta('notifier_enabled', '')
d0.__dict__.pop('_ntf_on', None)
check(d0.notifier_enabled() is True, 'a server with keys before the switch is off')
check(d0.store.get_meta('notifier_enabled') == '1', 'the choice is not kept')
d0.store.set_meta('notifier_keys', '[]')
d0.__dict__.pop('_ntf_on', None)
check(d0.notifier_enabled() is True, 'the choice was worked out again once the keys went')
try:
    d0.store.close()
except Exception:
    pass

# ---- a new server -------------------------------------------------------------------------
zigmon.CONFIG['db_file'] = str(W / 'z.db')
d = zigmon.Daemon()
d.notify = lambda message, *a, **k: None
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def call(path, body=None, session=None, key=None, client='192.168.40.10', timeout=30):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': client}
    if session:
        headers['X-Zigmon-Session'] = session
    if key is not None:
        headers['X-Zigmon-Notifier'] = key
    if body is not None and session:
        body = dict(body, session=session)
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                 data=None if body is None else json.dumps(body).encode(),
                                 method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


try:
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
    S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
    SO = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''
    check(S and SO, 'could not sign in')

    print('a new server: off')
    check(d.notifier_enabled() is False, 'a new server comes with the desktop app on')
    code, out = call('/api/notifier/keys', session=S)
    check(code == 200 and out.get('enabled') is False, 'the keys view does not say off: %s %r' % (code, out))
    check(out.get('most') == 20, 'the limit as it comes is not 20: %r' % out.get('most'))
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'Office PC', 'devices': []}, session=S)
    check(code == 200 and str(out.get('key', '')).startswith('zmn_'), 'a key cannot be made while off: %s %r' % (code, out))
    KEY = out.get('key') or ''
    check(out.get('enabled') is False, 'making a key switched it on')
    for road in ('hello', 'sensors', 'wait?after=0', 'update'):
        code, out = call('/api/notifier/' + road, key=KEY)
        check(code == 403 and out.get('off') is True and 'switched off' in str(out.get('error')),
              '%s while off is not 403 off: %s %r' % (road, code, out))
    code, out = call('/api/notifier/hello', key='zmn_' + 'x' * 40)
    check(code == 403 and out.get('off'), 'a wrong key while off is not simply told off: %s' % code)

    print('the switch is an administrator\'s')
    code, out = call('/api/notifier/keys', {'action': 'enable'}, session=SO)
    check(code == 403, 'an operator switched it on: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', {'action': 'enable'})
    check(code == 403, 'nobody switched it on: %s %r' % (code, out))
    check(d.notifier_enabled() is False, 'switched on by somebody not allowed')

    print('on')
    boot0 = d.notifier_boot
    code, out = call('/api/notifier/keys', {'action': 'enable'}, session=S)
    check(code == 200 and out.get('enabled') is True, 'not switched on: %s %r' % (code, out))
    check(d.store.get_meta('notifier_enabled') == '1', 'not kept')
    check(d.notifier_boot != boot0, 'no new boot on switching on')
    code, out = call('/api/notifier/hello', key=KEY)
    check(code == 200 and out.get('ok'), 'hello once on: %s %r' % (code, out))
    evs = json.dumps(d.store.events(limit=50), default=str)
    check('owner switched on the desktop app' in evs, 'not in the events: ' + evs[:300])

    print('off while a poll waits: 403 at once, not 401')
    boot = out.get('boot')
    seq = out.get('seq', 0)
    got = {}

    def waiter():
        got['r'] = call('/api/notifier/wait?after=%d&boot=%s' % (seq, boot), key=KEY)
        got['t'] = time.monotonic()
    th = threading.Thread(target=waiter)
    t0 = time.monotonic()
    th.start()
    time.sleep(1.0)
    code, out = call('/api/notifier/keys', {'action': 'disable'}, session=S)
    check(code == 200 and out.get('enabled') is False, 'not switched off: %s %r' % (code, out))
    th.join(10)
    code, out = got.get('r', (0, {}))
    check(code == 403 and out.get('off'), 'the waiting poll did not end refused as off: %s %r' % (code, out))
    check(got.get('t', 99e9) - t0 < 4, 'the waiting poll was not ended at once')

    print('on again: nothing from while it was off')
    with d._ntf_cond:
        d._ntf_seq += 1
        d._ntf_ring.append((d._ntf_seq, time.time(), 'x', 'motion', 'occupancy', True, 'motion'))
    code, out = call('/api/notifier/keys', {'action': 'enable'}, session=S)
    check(len(d._ntf_ring) == 0, 'the ring kept what came while off')
    code, out = call('/api/notifier/wait?after=%d&boot=%s' % (seq, boot), key=KEY)
    check(code == 200 and out.get('reset') is True and not out.get('events'),
          'the app is not told to start again: %s %r' % (code, out))

    print('how many keys')
    check(zigmon.CONFIG.get('notifier_keys_most') == '20', 'not 20 as it comes')
    check('notifier_keys_most' in zigmon.Daemon.TUNABLE, 'not a setting')
    check([c[0] for c in zigmon.Daemon.TUNABLE_CHOICES['notifier_keys_most']] == ['20', '50', '100', '0'],
          'the choices are not 20, 50, 100, no limit')
    for i in range(19):
        call('/api/notifier/keys', {'action': 'create', 'name': 'PC %d' % i}, session=S)
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'One too many'}, session=S)
    check(code == 400 and 'at most 20' in str(out.get('error')), 'a 21st key made at 20: %s %r' % (code, out))
    code, out = call('/api/config', {'notifier_keys_most': '7'}, session=S)
    check(code == 400, 'a limit of 7 was taken: %s %r' % (code, out))
    code, out = call('/api/config', {'notifier_keys_most': '0'}, session=S)
    check(code == 200, 'no limit not taken: %s %r' % (code, out))
    for i in range(6):
        code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'More %d' % i}, session=S)
        check(code == 200, 'no limit still refuses: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', session=S)
    check(out.get('most') == 0 and len(out.get('keys') or []) == 26, 'the view: %r %d' % (out.get('most'), len(out.get('keys') or [])))
    check(d.notifier_waiters_most() == 52, 'the waiting polls do not grow with the keys: %d' % d.notifier_waiters_most())
    code, out = call('/api/config', {'notifier_keys_most': '50'}, session=S)
    check(code == 200 and d.notifier_most() == 50, 'fifty not taken')

    print('the page')
    page = (HERE / 'web' / 'index.php').read_text()
    check('function ntfHero(' in page and "'Allow the desktop app'" in page, 'no switch on the page')
    check("ntfAsk({action: 'enable'}" in page and "ntfAsk({action: 'disable'}" in page, 'the switch does not ask')
    check("'The desktop app': 'msg-desktop'" in page and 'id="set-host-msg-desktop"' in page,
          'the setting is not in the desktop app\'s section')
    check("['notifier_keys_most'," in page, 'the setting is not drawn')
    check("no limit" in page, 'no limit is not said')
finally:
    try:
        api.stop()
    except Exception:
        pass

if bad:
    print('%d FAILED' % len(bad))
    sys.exit(1)
print('all good')
