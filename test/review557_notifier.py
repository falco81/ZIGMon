#!/usr/bin/env python3
"""Settings - Messages - Desktop app (5.57): the server side of ZIGMon Notifier, the Windows
tray app that brings an alert to the front when a sensor is triggered.

  * a key made by an administrator is shown once (zmn_ + 40 characters) and only its sha256
    and its last two characters are kept - never in the log (debug on), the events, the meta;
  * the key in X-Zigmon-Notifier is the whole of the authority of hello / sensors / wait: a
    wrong one is 401 and counted as a wrong one-tap secret (and noted as an anomaly), past ten
    a minute 429; taken away, the next question - and a long poll waiting - is 401;
  * a key limited to some sensors sees only those, in hello, sensors and wait;
  * the edges: occupancy, contact (False = open = active), water_leak, and every press of a
    button (the same action twice is two); an unchanged repeat is nothing; a retained replay
    is nothing;
  * wait answers at once with what is pending, holds and wakes on a new edge, says reset for
    another boot, a number too old for the ring or one from the future, and gives at most 50;
  * the last use is kept in memory and written down at most once a minute;
  * the management is an administrator's: an operator and nobody get 403;
  * the relay (php -S): api=notifier&do=..., the header cut down to [A-Za-z0-9_-], a bad do
    is 400, the wait through it; api=notifier-keys;
  * the page in Chromium (Playwright): Settings - Messages - Desktop app, desktop and 390 px,
    a key made in the browser shown once, with the address, and then nowhere on the page.
    Screenshots into $ZIGMON_SHOTS (or a temporary folder that is kept).

    python3 test/review557_notifier.py < /dev/null

Ports 20150-20199. Every secret here is made up.
"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-notifier-'))
API_PORT, PHP_PORT = 20150, 20151
SHOTS = Path(os.environ.get('ZIGMON_SHOTS') or tempfile.mkdtemp(prefix='zigmon-notifier-shots-'))
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                               # noqa: E402

LOG = []
_real_log = zigmon.log


def _log(msg, level='info', *a, **k):
    LOG.append('%s %s' % (level, msg))


zigmon.log = _log
zigmon.load_config()
(W / 'state').mkdir()
zigmon.CONFIG.update({
    'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1', 'token_file': str(W / 'token'),
    'pin': '', 'sensors': [], 'plugs': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(W / 'state'),
    'debug': 1, 'blacklist': 0, 'public_view': False})
d = zigmon.Daemon()
d.notify = lambda message, *a, **k: None
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def call(path, body=None, session=None, key=None, client='192.168.40.10', timeout=60):
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


def report(name, payload):
    d.handle_zigbee(name, json.dumps(payload).encode())


try:
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
    S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
    SO = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''
    check(S and SO, 'could not sign in')

    # ---- the house: a PIR, a door, a leak sensor, a button, and a thermometer (no trigger) --
    for ident, name, exposes in (('0x00158d0001a2b3c4', 'PIR-Chodba', {'occupancy': {}}),
                                 ('0x00158d0001a2b3c5', 'Dvere-Vchod', {'contact': {}}),
                                 ('0x00158d0001a2b3c6', 'Voda-Koupelna', {'water_leak': {}}),
                                 ('0x00158d0001a2b3c7', 'Tlacitko', {'action': {'values': ['single', 'double']}}),
                                 ('0x00158d0001a2b3c8', 'Teplomer', {'temperature': {}})):
        d.store.upsert_device({'id': ident, 'name': name, 'source': 'zigbee', 'kind': 'EndDevice',
                               'exposes': exposes})
        d.names[name] = ident
    PIR, DOOR, LEAK, BTN, THERMO = ('0x00158d0001a2b3c4', '0x00158d0001a2b3c5', '0x00158d0001a2b3c6',
                                    '0x00158d0001a2b3c7', '0x00158d0001a2b3c8')
    d.store.set_meta('rooms', json.dumps([{'id': 'r1', 'name': 'Hallway'}, {'id': 'r2', 'name': 'Bathroom'}]))
    d.store.set_meta('room_of', json.dumps({PIR: 'r1', 'Dvere-Vchod': 'r1', LEAK: 'r2'}))
    report('PIR-Chodba', {'occupancy': False, 'battery': 87, 'linkquality': 120})
    report('Dvere-Vchod', {'contact': True, 'battery': 64})
    report('Voda-Koupelna', {'water_leak': False, 'battery': 100})
    report('Teplomer', {'temperature': 21.5, 'humidity': 40})

    print('the management is an administrator\'s')
    check('/api/notifier/keys' in zigmon.ApiHandler.ALWAYS_LOCKED, 'not among the locked reads')
    check('x-zigmon-notifier' in zigmon.SECRET_HEADER_NAMES, 'the header is not among the secret ones')
    code, out = call('/api/notifier/keys')
    check(code == 403, 'nobody reads the keys: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', session=SO)
    check(code == 403, 'an operator reads the keys: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'Sneaky'}, session=SO)
    check(code == 403, 'an operator makes a key: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'Sneaky'})
    check(code == 403, 'nobody makes a key: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', session=S)
    check(code == 200 and out.get('keys') == [], 'the admin reads the keys: %s %r' % (code, out))
    kinds = {s['id']: s['kind'] for s in out.get('sensors') or []}
    check(kinds == {PIR: 'motion', DOOR: 'contact', LEAK: 'leak', BTN: 'button'},
          'the sensors to choose from: %r' % kinds)
    names = [s['name'] for s in out.get('sensors') or []]
    check(names == sorted(names, key=str.lower), 'the sensors are not sorted by name: %r' % names)
    check(any(s.get('room') == 'Hallway' for s in out.get('sensors') or [] if s['id'] == DOOR),
          'the room of a device assigned by name: %r' % out.get('sensors'))

    print('a key is shown once and only its hash is kept')
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'Office PC', 'devices': []}, session=S)
    KEY = out.get('key') or ''
    check(code == 200 and re.match(r'^zmn_[A-Za-z0-9_-]{40}$', KEY), 'the key made: %s %r' % (code, out))
    KID = out.get('id')
    listed = out.get('keys') or []
    check(len(listed) == 1 and listed[0]['name'] == 'Office PC' and listed[0]['hint'] == KEY[-2:]
          and 'hash' not in listed[0] and KEY not in json.dumps(listed), 'the list after making it: %r' % listed)
    raw = d.store.get_meta('notifier_keys') or ''
    check(KEY not in raw and hashlib.sha256(KEY.encode()).hexdigest() in raw, 'what is kept: %r' % raw[:200])
    code, out = call('/api/notifier/keys', session=S)
    check(KEY not in json.dumps(out) and set(out['keys'][0]) == {'id', 'name', 'devices', 'created', 'by', 'last_at',
                                                                 'last_from', 'hint'}, 'the read: %r' % out)
    check(out['keys'][0]['by'] == 'owner', 'who made it: %r' % out['keys'][0])
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'Door only', 'devices': [DOOR]}, session=S)
    KEY2, KID2 = out.get('key') or '', out.get('id')
    check(code == 200 and KEY2 and KEY2 != KEY, 'the second key: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': '   '}, session=S)
    check(code == 400, 'a key with no name: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'x' * 61}, session=S)
    check(code == 400, 'a name of 61 characters: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'T', 'devices': [THERMO]}, session=S)
    check(code == 400, 'a thermometer is no sensor that triggers: %s %r' % (code, out))
    made = []
    for i in range(18):
        code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'Spare %d' % i}, session=S)
        made.append(out.get('id'))
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'One too many'}, session=S)
    check(code == 400 and '20' in out.get('error', ''), 'the 21st key: %s %r' % (code, out))
    for kid in made:
        call('/api/notifier/keys', {'action': 'delete', 'id': kid}, session=S)
    code, out = call('/api/notifier/keys', session=S)
    check(len(out.get('keys') or []) == 2, 'the spares taken away: %r' % [k['name'] for k in out.get('keys') or []])
    with d.store.lock:
        ev = [r[0] for r in d.store.db.execute('SELECT detail FROM events').fetchall()]
    check(any("owner made the desktop notifier key 'Office PC' (every sensor)" in e for e in ev)
          and any("'Door only' (1 sensor)" in e for e in ev) and any("took away the desktop notifier key 'Spare 0'" in e
                                                                    for e in ev), 'the events: %r' % ev[-5:])

    print('hello and the sensors, by the key alone (the view is locked)')
    code, out = call('/api/notifier/hello', key=KEY)
    check(code == 200 and out.get('ok') and out.get('api') == 1 and out.get('server') == 'zigmon'
          and out.get('version') == zigmon.__version__ and out.get('house') and out['key'] == {
              'name': 'Office PC', 'devices': 4, 'hint': KEY[-2:]} and re.match(r'^[0-9a-f]{12}$', out.get('boot') or '')
          and isinstance(out.get('seq'), int), 'hello: %s %r' % (code, out))
    BOOT, SEQ = out.get('boot'), out.get('seq')
    code, out = call('/api/notifier/hello', key=KEY2)
    check(code == 200 and out['key']['devices'] == 1 and out['key']['name'] == 'Door only', 'hello of the second: %r' % out)
    code, out = call('/api/notifier/sensors', key=KEY)
    ss = {s['id']: s for s in out.get('sensors') or []}
    check(code == 200 and set(ss) == {PIR, DOOR, LEAK, BTN} and out.get('boot') == BOOT, 'sensors: %s %r' % (code, out))
    p = ss.get(PIR) or {}
    check(p.get('name') == 'PIR-Chodba' and p.get('room') == 'Hallway' and p.get('kind') == 'motion'
          and p.get('active') is False and p.get('battery') == 87 and p.get('online') is True and 'at' in p,
          'the PIR: %r' % p)
    dr = ss.get(DOOR) or {}
    check(dr.get('active') is False and dr.get('kind') == 'contact' and dr.get('room') == 'Hallway', 'the door: %r' % dr)
    bt = ss.get(BTN) or {}
    check(bt.get('kind') == 'button' and bt.get('active') is None and bt.get('online') is False and bt.get('room') is None,
          'the button (never heard): %r' % bt)
    check(set(p) == {'id', 'name', 'room', 'kind', 'active', 'at', 'battery', 'online'}, 'the fields: %r' % sorted(p))
    code, out = call('/api/notifier/sensors', key=KEY2)
    check(code == 200 and [s['id'] for s in out.get('sensors') or []] == [DOOR], 'the second sees only the door: %r' % out)
    code, out = call('/api/notifier/other', key=KEY)
    check(code == 400, 'another road: %s %r' % (code, out))
    code, out = call('/api/status', key=KEY)
    check(code == 403, 'the key opens the status (view locked): %s %r' % (code, out))
    code, out = call('/api/notifier/keys', key=KEY)
    check(code == 403, 'the key reads the keys: %s %r' % (code, out))

    print('a wrong key is refused and counted')
    WHO = '198.51.100.7'
    before_tries = len(d._tap_tries.get(WHO, [])) if getattr(d, '_tap_tries', None) else 0
    code, out = call('/api/notifier/hello', key='zmn_' + 'A' * 40, client=WHO)
    check(code == 401 and out.get('ok') is False and out.get('error'), 'a wrong key: %s %r' % (code, out))
    check(len(d._tap_tries.get(WHO, [])) == before_tries + 1, 'the wrong key is not counted')
    check(any(a.get('kind') == 'bad-secret' if isinstance(a, dict) else 'bad-secret' in str(a)
              for a in d._anomaly.get(WHO, [])), 'not noted as an anomaly: %r' % d._anomaly.get(WHO))
    code, out = call('/api/notifier/hello', key='', client=WHO)
    check(code == 401, 'no key: %s %r' % (code, out))
    code, out = call('/api/notifier/wait?after=0&boot=' + BOOT, key=KEY[:-1] + ('a' if KEY[-1] != 'a' else 'b'),
                     client=WHO)
    check(code == 401, 'a key one letter off: %s %r' % (code, out))
    for _ in range(10):
        code, out = call('/api/notifier/hello', key='zmn_wrong', client=WHO)
    check(code == 429, 'past ten wrong a minute: %s %r' % (code, out))
    code, out = call('/api/notifier/hello', key=KEY, client=WHO)
    check(code == 429, 'the right key from a guessing address: %s %r' % (code, out))
    code, out = call('/api/notifier/hello', key=KEY, client='192.168.40.11')
    check(code == 200, 'another address is not held: %s %r' % (code, out))

    print('the edges')

    def wait(after, key=KEY, boot=None, client='192.168.40.12', timeout=60):
        return call('/api/notifier/wait?after=%s&boot=%s' % (after, boot or BOOT), key=key, client=client,
                    timeout=timeout)

    code, out = wait(SEQ)
    t0 = time.time()
    # nothing pending: it holds - a short wait for the test
    d.NOTIFIER_WAIT_S = 1.5
    code, out = wait(SEQ)
    check(code == 200 and out.get('events') == [] and out.get('reset') is False and 1.2 < time.time() - t0 < 6,
          'an empty wait: %s %r in %.1f s' % (code, out, time.time() - t0))
    d.NOTIFIER_WAIT_S = 25.0
    report('PIR-Chodba', {'occupancy': True, 'battery': 87})
    report('PIR-Chodba', {'occupancy': True, 'battery': 86})          # the same again: nothing
    report('PIR-Chodba', {'occupancy': False})
    report('Dvere-Vchod', {'contact': False})                        # open
    report('Dvere-Vchod', {'contact': False})
    report('Dvere-Vchod', {'contact': True})                         # closed
    report('Voda-Koupelna', {'water_leak': True})
    report('Tlacitko', {'action': 'single'})
    report('Tlacitko', {'action': 'single'})                         # a second press
    report('Tlacitko', {'action': ''})                               # nothing
    report('Teplomer', {'temperature': 22.0})
    t0 = time.time()
    code, out = wait(SEQ)
    ev = out.get('events') or []
    got = [(e['device'], e['kind'], e['key'], e['active'], e['what']) for e in ev]
    check(time.time() - t0 < 1.0, 'pending events did not come at once (%.1f s)' % (time.time() - t0))
    check(got == [(PIR, 'motion', 'occupancy', True, 'motion'), (PIR, 'motion', 'occupancy', False, 'no motion'),
                  (DOOR, 'contact', 'contact', True, 'opened'), (DOOR, 'contact', 'contact', False, 'closed'),
                  (LEAK, 'leak', 'water_leak', True, 'water leak'), (BTN, 'button', 'action', True, 'pressed: single'),
                  (BTN, 'button', 'action', True, 'pressed: single')], 'the edges: %r' % got)
    check(ev and ev[0]['name'] == 'PIR-Chodba' and ev[0]['room'] == 'Hallway' and isinstance(ev[0]['at'], float)
          and set(ev[0]) == {'seq', 'at', 'device', 'name', 'room', 'kind', 'key', 'active', 'what'}
          and [e['seq'] for e in ev] == list(range(SEQ + 1, SEQ + 8)) and out.get('seq') == SEQ + 7,
          'an event: %r / seq %r' % (ev[:1], out.get('seq')))
    code, out = wait(SEQ, key=KEY2)
    check([(e['device'], e['what']) for e in out.get('events') or []] == [(DOOR, 'opened'), (DOOR, 'closed')]
          and out.get('seq') == SEQ + 7, 'the door-only key: %r' % out)
    code, out = call('/api/notifier/sensors', key=KEY)
    ss = {s['id']: s for s in out.get('sensors') or []}
    check(ss[LEAK]['active'] is True and isinstance(ss[LEAK]['at'], float) and ss[DOOR]['active'] is False
          and isinstance(ss[BTN]['at'], float), 'the sensors after the edges: %r' % ss)
    # first heard and already active is an edge; first heard and quiet is not; a retained replay is nothing
    s0 = d._ntf_seq
    d.notifier_edges('dev-x', {}, {'occupancy': True, 'contact': True, 'smoke': False, 'gas': 'ON',
                                   'carbon_monoxide': 1, 'tamper': True, 'vibration': True})
    whats = [e[6] for e in list(d._ntf_ring) if e[0] > s0]
    check(whats == ['motion', 'gas', 'carbon monoxide', 'tampered', 'vibration'], 'first heard: %r' % whats)
    s0 = d._ntf_seq
    d.notifier_edges('dev-x', {'smoke': False, 'tamper': True, 'vibration': True}, {'smoke': True, 'tamper': False,
                                                                                    'vibration': False})
    whats = [e[6] for e in list(d._ntf_ring) if e[0] > s0]
    check(whats == ['smoke', 'closed again', 'still'], 'the other words: %r' % whats)
    s0 = d._ntf_seq
    d._retained_msg = True
    d.notifier_edges('dev-x', {}, {'action': 'single', 'occupancy': True})
    d._retained_msg = False
    check(d._ntf_seq == s0, 'a retained replay made an event')

    print('the long wait')
    SEQ = d._ntf_seq
    box = {}

    def waiter():
        box['t'] = time.time()
        box['r'] = wait(SEQ)
        box['done'] = time.time()

    th = threading.Thread(target=waiter)
    th.start()
    time.sleep(1.0)
    check('r' not in box, 'the wait did not hold')
    report('Voda-Koupelna', {'water_leak': False})
    th.join(10)
    r = box.get('r') or (0, {})
    check(r[0] == 200 and [e['what'] for e in r[1].get('events') or []] == ['dry']
          and box.get('done', 99) - box.get('t', 0) < 3.0, 'the wait woken by an edge: %r' % (r,))
    code, out = wait(0, boot='0123456789ab')
    check(code == 200 and out.get('reset') is True and out.get('events') == [] and out.get('boot') == BOOT
          and out.get('seq') == d._ntf_seq, 'another boot: %r' % out)
    code, out = wait(d._ntf_seq + 5)
    check(out.get('reset') is True, 'a number from the future: %r' % out)
    code, out = call('/api/notifier/wait?after=x1&boot=' + BOOT, key=KEY, client='192.168.40.12')
    check(code == 400, 'after that is no number: %s %r' % (code, out))
    # at most 50, and the number goes only as far as they do
    SEQ = d._ntf_seq
    for i in range(120):
        d.notifier_edges(PIR, {'occupancy': i % 2 == 0}, {'occupancy': i % 2 == 1})
    code, out = wait(SEQ)
    check(len(out.get('events') or []) == 50 and out.get('seq') == SEQ + 50 and out['events'][0]['seq'] == SEQ + 1,
          'the first fifty: %r / %r' % (len(out.get('events') or []), out.get('seq')))
    code, out = wait(out.get('seq'))
    check(len(out.get('events') or []) == 50 and out.get('seq') == SEQ + 100, 'the next fifty: %r' % out.get('seq'))
    code, out = wait(out.get('seq'))
    check(len(out.get('events') or []) == 20 and out.get('seq') == SEQ + 120, 'the last twenty: %r' % out.get('seq'))
    for i in range(500):
        d.notifier_edges(PIR, {'occupancy': i % 2 == 0}, {'occupancy': i % 2 == 1})
    code, out = wait(SEQ)
    check(out.get('reset') is True and out.get('events') == [], 'a number older than the ring: %r' % out)
    check(len(d._ntf_ring) == 500, 'the ring holds %d' % len(d._ntf_ring))

    print('the last use, written down at most once a minute')
    writes = []
    _set_meta = d.store.set_meta

    def counting(key, value, deferred=False):
        if key == 'notifier_keys':
            writes.append(value)
        return _set_meta(key, value, deferred=deferred)

    d.store.set_meta = counting
    for _ in range(5):
        call('/api/notifier/hello', key=KEY, client='192.168.40.20')
    d.store.set_meta = _set_meta
    check(len(writes) <= 1, 'the keys were written %d times for 5 questions' % len(writes))
    code, out = call('/api/notifier/keys', session=S)
    mine = [k for k in out.get('keys') or [] if k['id'] == KID][0]
    check(mine.get('last_from') == '192.168.40.20' and time.time() - (mine.get('last_at') or 0) < 30,
          'the last use: %r' % mine)

    print('edited, and taken away')
    code, out = call('/api/notifier/keys', {'action': 'update', 'id': KID2, 'name': 'Door and leak',
                                            'devices': [DOOR, LEAK]}, session=S)
    check(code == 200, 'edit: %s %r' % (code, out))
    code, out = call('/api/notifier/hello', key=KEY2)
    check(code == 200 and out['key'] == {'name': 'Door and leak', 'devices': 2, 'hint': KEY2[-2:]}, 'edited: %r' % out)
    SEQ = d._ntf_seq
    box = {}

    def waiter2():
        box['r'] = wait(SEQ, key=KEY2)
        box['done'] = time.time()

    th = threading.Thread(target=waiter2)
    th.start()
    time.sleep(0.8)
    t0 = time.time()
    code, out = call('/api/notifier/keys', {'action': 'delete', 'id': KID2}, session=S)
    check(code == 200 and all(k['id'] != KID2 for k in out.get('keys') or []), 'taken away: %s %r' % (code, out))
    th.join(10)
    check((box.get('r') or (0,))[0] == 401 and box.get('done', 99) - t0 < 3.0, 'the waiting poll after: %r' % box)
    code, out = call('/api/notifier/hello', key=KEY2)
    check(code == 401, 'the key taken away: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', {'action': 'delete', 'id': KID2}, session=S)
    check(code == 400, 'taken away twice: %s %r' % (code, out))

    print('the relay')
    page = (HERE / 'web' / 'index.php').read_text()
    for words in ('data-sec="msg-desktop"', "'msg-desktop': ['Desktop app'", "api('notifier-keys')",
                  "post('notifier-keys'", "'notifier-keys' => '/api/notifier/keys'", "$what === 'notifier'",
                  "$what === 'notifier-keys' && $_SERVER['REQUEST_METHOD'] === 'GET'", 'it is not shown again',
                  'HTTP_X_ZIGMON_NOTIFIER'):
        check(words in page, 'the page has no %s' % words)
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

    def relay(query, key=None, timeout=60):
        headers = {'User-Agent': 'ZigmonNotifier/1.0.0 (Windows)'}
        if key is not None:
            headers['X-Zigmon-Notifier'] = key
        req = urllib.request.Request('http://127.0.0.1:%d/index.php?%s' % (PHP_PORT, query), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')

    code, out = relay('api=notifier&do=hello', key=KEY)
    check(code == 200 and out.get('key', {}).get('name') == 'Office PC', 'hello through the relay: %s %r' % (code, out))
    code, out = relay('api=notifier&do=hello', key=KEY + '!*"<>')
    check(code == 200, 'the header is not cut down to its letters: %s %r' % (code, out))
    code, out = relay('api=notifier&do=keys', key=KEY)
    check(code == 400, 'a do that is not one of the three: %s %r' % (code, out))
    code, out = relay('api=notifier&do=sensors', key=KEY)
    check(code == 200 and len(out.get('sensors') or []) == 4, 'sensors through the relay: %s %r' % (code, out))
    SEQ = d._ntf_seq
    report('Tlacitko', {'action': 'double'})
    code, out = relay('api=notifier&do=wait&after=%dzz&boot=%s;x' % (SEQ, BOOT), key=KEY)
    check(code == 200 and [e['what'] for e in out.get('events') or []] == ['pressed: double'],
          'the wait through the relay: %s %r' % (code, out))
    code, out = relay('api=notifier&do=hello', key='zmn_not-a-real-key-0000')
    check(code == 401, 'a wrong key through the relay: %s %r' % (code, out))
    code, out = relay('api=notifier-keys')
    check(code == 403, 'the keys through the relay, signed out: %s %r' % (code, out))

    print('the page')
    SHOTS.mkdir(parents=True, exist_ok=True)
    js = r'''
const { chromium } = require('playwright');
const job = %(job)s;
(async () => {
  const b = await chromium.launch();
  const r = {errors: []};
  for (const shot of [{n: 'desktop', w: 1400, h: 1000}, {n: 'phone', w: 390, h: 1500}]) {
    const ctx = await b.newContext({viewport: {width: shot.w, height: shot.h}, colorScheme: 'dark'});
    await ctx.addCookies([{name: 'zigmon_session', value: job.s, url: 'http://127.0.0.1:' + job.port + '/'}]);
    const p = await ctx.newPage();
    p.on('pageerror', e => r.errors.push(String(e)));
    await p.goto('http://127.0.0.1:' + job.port + '/#control/msg-desktop');
    await p.waitForTimeout(2000);
    try { await p.evaluate(() => showControlSection('msg-desktop')); } catch (e) {}
    await p.waitForSelector('#ntf-host .ntf-key', {timeout: 15000});
    await p.waitForTimeout(500);
    r[shot.n] = await p.evaluate(() => ({
      rows: Array.from(document.querySelectorAll('#ntf-host .ntf-key')).map(x => x.textContent),
      tiles: Array.from(document.querySelectorAll('#ntf-host .facts .fact')).map(x => x.textContent),
      head: (document.querySelector('#ctl-head') || {}).textContent || '',
      nav: (document.querySelector('#control-nav button[data-sec="msg-desktop"]') || {}).textContent || '',
      note: (document.querySelector('#ntf-host .ntf-lede') || {}).textContent || '',
      wide: document.documentElement.scrollWidth, view: window.innerWidth}));
    await p.evaluate(() => { const h = document.querySelector('#ctl-head'); if (h) h.scrollIntoView(); });
    await p.screenshot({path: job.dir + '/section-' + shot.n + '.png', fullPage: shot.n === 'phone'});
    await p.click('#ntf-new');
    await p.waitForSelector('#zmodal:not([hidden]) #ntf-name', {timeout: 5000});
    await p.fill('#ntf-name', 'Laptop ' + shot.n);
    await p.check('#zmodal input[name="ntf-mode"][value="some"]');
    await p.fill('#ntf-find', 'hallway');
    r[shot.n].shown = await p.evaluate(() => Array.from(document.querySelectorAll('#ntf-opts .ntf-opt')).filter(o => !o.hidden).map(o => o.dataset.id));
    await p.check('#ntf-opts .ntf-opt[data-id="' + job.pir + '"] input');
    await p.screenshot({path: job.dir + '/dialog-new-' + shot.n + '.png'});
    await p.click('#zmodal-foot button:has-text("Make the key")');
    await p.waitForSelector('#zmodal:not([hidden]) #ntf-secret', {timeout: 8000});
    r[shot.n].key = await p.evaluate(() => document.querySelector('#ntf-secret').textContent);
    r[shot.n].shown_body = await p.evaluate(() => document.querySelector('#zmodal-body').textContent);
    r[shot.n].title = await p.evaluate(() => document.querySelector('#zmodal-title').textContent);
    r[shot.n].dlgwide = await p.evaluate(() => document.documentElement.scrollWidth);
    await p.screenshot({path: job.dir + '/dialog-key-' + shot.n + '.png'});
    await p.click('#zmodal-foot button:has-text("I have copied it")');
    await p.waitForTimeout(600);
    r[shot.n].after = await p.evaluate((k) => ({inpage: document.documentElement.outerHTML.indexOf(k) >= 0,
      rows: Array.from(document.querySelectorAll('#ntf-host .ntf-key b')).map(x => x.textContent)}), r[shot.n].key);
    if (shot.n === 'desktop') {
      await (await p.$('#ntf-card')).screenshot({path: job.dir + '/card.png'});
      await p.click('#ntf-host .ntf-key:last-child .ntf-drop');
      await p.waitForSelector('#zmodal:not([hidden])', {timeout: 5000});
      r.drop = await p.evaluate(() => [document.querySelector('#zmodal-title').textContent,
        document.querySelector('#zmodal-body').textContent]);
      await p.screenshot({path: job.dir + '/dialog-take-away.png'});
      await p.click('#zmodal-foot button:has-text("No, leave it")');
    }
    await ctx.close();
  }
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
    npm_root = sh(['npm', 'root', '-g']).stdout.strip()
    (W / 'page.js').write_text(js % {'job': json.dumps({'s': S, 'port': PHP_PORT, 'dir': str(SHOTS), 'pir': PIR})})
    got = sh(['node', str(W / 'page.js')], timeout=240, env=dict(os.environ, NODE_PATH=npm_root))
    try:
        r = json.loads(got.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        r = {'error': (got.stdout + got.stderr)[-400:]}
    if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
        print('  SKIPPED (no browser here): %s' % r['error'][:200])
    else:
        check(not r.get('error'), 'the page: %r' % r.get('error'))
        dk, ph = r.get('desktop') or {}, r.get('phone') or {}
        check(len(dk.get('rows') or []) == 1 and 'Office PC' in dk['rows'][0] and 'every sensor' in dk['rows'][0]
              and '…' + KEY[-2:] in dk['rows'][0] and 'owner' in dk['rows'][0], 'the row: %r' % dk.get('rows'))
        check('Desktop app' in dk.get('head', '') and dk.get('nav') == 'Desktop app' and 'read-only' in dk.get('note', ''),
              'the head and the words: %r' % [dk.get('head'), dk.get('nav'), dk.get('note')])
        check(any('Keys' in t and '1 of 20' in t for t in dk.get('tiles') or []) and
              any('The address for the app' in t and '127.0.0.1:%d' % PHP_PORT in t for t in dk.get('tiles') or []),
              'the tiles: %r' % dk.get('tiles'))
        check(dk.get('shown') == [PIR, DOOR] or sorted(dk.get('shown') or []) == sorted([PIR, DOOR]),
              'the search of the list: %r' % dk.get('shown'))
        for n, x in (('desktop', dk), ('phone', ph)):
            check(re.match(r'^zmn_[A-Za-z0-9_-]{40}$', x.get('key') or ''), '%s: the key shown: %r' % (n, x.get('key')))
            check('not shown again' in (x.get('shown_body') or '') and 'http://127.0.0.1:%d' % PHP_PORT
                  in (x.get('shown_body') or ''), '%s: the dialog of the key: %r' % (n, x.get('shown_body')))
            check(not (x.get('after') or {}).get('inpage', True), '%s: the key is still on the page after closing' % n)
            check('Laptop ' + n in ((x.get('after') or {}).get('rows') or []), '%s: the new row: %r' % (n, x.get('after')))
            check(x.get('wide', 9999) <= x.get('view', 0) + 1 and x.get('dlgwide', 9999) <= x.get('view', 0) + 1,
                  '%s: scrolls sideways: %r/%r/%r' % (n, x.get('wide'), x.get('dlgwide'), x.get('view')))
        check(ph.get('rows') and len(ph['rows']) == 2, 'the phone sees the desktop\'s new key: %r' % ph.get('rows'))
        dr = r.get('drop') or ['', '']
        check('Take away the key' in dr[0] and 'refused' in dr[1], 'the take-away question: %r' % dr)
        check(not r.get('errors'), 'the page threw: %r' % r.get('errors'))
        # the key made in the browser works, and sees only the PIR
        code, out = call('/api/notifier/hello', key=dk.get('key') or 'zmn_x')
        check(code == 200 and out['key']['devices'] == 1 and out['key']['name'] == 'Laptop desktop',
              'the key made in the browser: %s %r' % (code, out))
        print('  screenshots: %s' % SHOTS)

    print('never in the log, the events or the meta')
    keys_seen = [k for k in (KEY, KEY2, (r.get('desktop') or {}).get('key'), (r.get('phone') or {}).get('key')) if k]
    whole = '\n'.join(LOG)
    with d.store.lock:
        evs = '\n'.join(str(x[0]) for x in d.store.db.execute('SELECT detail FROM events').fetchall())
        meta = '\n'.join(str(x[0]) for x in d.store.db.execute('SELECT value FROM meta').fetchall())
    for k in keys_seen:
        check(k not in whole, 'a key is in the log')
        check(k not in evs, 'a key is in the events')
        check(k not in meta, 'a key is in the meta')
    check(any('api' in x and '/api/notifier/hello' in x for x in LOG), 'the debug log wrote nothing of the notifier')
    check(any('x-zigmon-notifier' in x.lower() for x in LOG), 'the debug log wrote no header line: %r'
          % [x for x in LOG if 'headers' in x][:2])
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
    except Exception:                                       # noqa: BLE001
        pass

zigmon.log = _real_log
shutil.rmtree(W, ignore_errors=True)
if bad:
    print('%d FAILED' % len(bad))
    sys.exit(1)
print('all good')
