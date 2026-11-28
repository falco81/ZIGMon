#!/usr/bin/env python3
"""5.59.4: ESP32 Gateways (esp32/PROTOCOL.md, protocol v1), ZIGMon's side, against a fake gateway.

  * the contract's section-7 vectors (the request signature, the pairing proof, the Yeelock packets);
  * pairing: the right code, a wrong one (spent either way), the lockout after five, a certificate
    that is not the one confirmed refused before anything is sent, no confirmation refused;
  * detect: the modules and entities become devices, generically by type; which are used;
  * the long poll: the state into the house (live, history, events), the offline gateway and its
    return, a restart (a new boot) described again with its new entity, a changed certificate
    refused, an answer signed wrong refused, an old answer replayed refused, a nonce never reused;
  * commands from the dashboard (the confirm step), a scene, a rule's target, the result as an event;
  * the Stream Deck: lock items under "locks", off by default, held by default and always held for
    what the entity names as sensitive; the other types under switch and view;
  * permissions: an administrator's settings, an operator's commands, a viewer neither;
  * the device key nowhere: not in the log, the events, the status, /api/esp, the export, a deck.

    python3 test/review5594_esp32.py < /dev/null

Ports 20360 (the API) and 20361 (the fake gateway). Every name and number here is made up.
"""
import hashlib
import hmac
import json
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / 'test'))
W = Path(tempfile.mkdtemp(prefix='zigmon-esp-'))
API_PORT, GW_PORT = 20360, 20361
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def port_free(port):
    for _ in range(60):
        s = socket.socket()
        try:
            s.bind(('127.0.0.1', port))
            s.close()
            return True
        except OSError:
            s.close()
            time.sleep(2)
    return False


def until(fn, secs=10.0, step=0.05):
    end = time.time() + secs
    while time.time() < end:
        try:
            got = fn()
        except Exception:                                   # noqa: BLE001
            got = None
        if got:
            return got
        time.sleep(step)
    return None


for p in (API_PORT, GW_PORT):
    if not port_free(p):
        print('port %d stays busy' % p)
        sys.exit(2)

sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                               # noqa: E402
import mockesp                                              # noqa: E402

LOG = []
zigmon.log = lambda msg, level='info', *a, **k: LOG.append('%s %s' % (level, msg))
zigmon.load_config()
(W / 'state').mkdir()
zigmon.CONFIG.update({
    'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1', 'token_file': str(W / 'token'),
    'pin': '', 'sensors': [], 'plugs': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(W / 'state'),
    'debug': 0, 'blacklist': 0, 'public_view': False, 'deck_dir': str(W / 'nodeck'), 'heating_enforce': 'never'})

# ---- 1. the contract's vectors -------------------------------------------------------------
print('the section-7 vectors')
body = b'{"action":"unlock","entity":"yeelock.front"}'
check(zigmon.esp_hash(body) == '718db82c79edadd8a8b3967f1c4d93a9075fc9f46fb21626c56bacd21c1b6ca4', 'the body hash')
check(zigmon.esp_sign(bytes(range(32)), 'POST', '/zigmon/v1/command', '1764340000',
                      '00112233445566778899aabbccddeeff', body)
      == '9477fb4d74063d5884e02f074529b34194f46ebaa6559387c286c87c182ca83b', 'the request signature')
check(zigmon.esp_pair_proof('482913', 'ab' * 32, '0f' * 16)
      == '268cac3700bba1a1cc76025483c59235fd45de76a55bad403a3d66a597bdd59a', 'the pairing proof')
# json.dumps as ZIGMon sends a command body: the vector's own bytes
check(json.dumps({'entity': 'yeelock.front', 'action': 'unlock'}, separators=(',', ':'), sort_keys=True).encode() == body,
      'a command body is not the vector\'s bytes')
sk = bytes.fromhex('00112233445566778899aabbccddeeff')
t = bytes.fromhex('08405c84ff2f')
check((t + hmac.new(sk, t, hashlib.sha1).digest()[:14]).hex() == '08405c84ff2f55748c652e3c83fc10a7cddc7c9f', 'yeelock time')
a = bytes.fromhex('01505c84ff2f01')
check((a + hmac.new(sk, a, hashlib.sha1).digest()[:13]).hex() == '01505c84ff2f01674720aeda9918f538e1471bca', 'yeelock unlock')
for given, want in (('192.168.1.40', ('192.168.1.40', 443, '192.168.1.40')),
                    ('https://GW.local:8443/', ('gw.local', 8443, 'gw.local:8443')),
                    ('[fd00::5]:444', ('fd00::5', 444, '[fd00::5]:444'))):
    check(zigmon.esp_address(given) == want, 'the address %r: %r' % (given, zigmon.esp_address(given)))
for wrong in ('http://1.2.3.4', 'a b', '', 'x:99999', '-bad-.lan'):
    try:
        zigmon.esp_address(wrong)
        check(False, 'the address %r was taken' % wrong)
    except ValueError:
        pass

d = zigmon.Daemon()
d.notify = lambda *a, **k: None
d.ESP_WAIT_S = 1
d.ESP_BACKOFF_S = (0.2, 0.5)
d.ESP_CERT_BACKOFF_S = 0.5
d.ESP_HELLO_S = 2
d.ESP_RESULT_S = 6
gw = mockesp.FakeGateway(GW_PORT).start()
ADDR = '127.0.0.1:%d' % GW_PORT
GWID = mockesp.GW_ID
FRONT, CAB, BOX = ('esp:%s:yeelock.front' % GWID, 'esp:%s:yeelock.cabinet' % GWID, 'esp:%s:climate.box' % GWID)
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def call(path, body=None, session=None):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': '192.168.40.10'}
    if session:
        headers['X-Zigmon-Session'] = session
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                 data=None if body is None else json.dumps(body).encode(),
                                 method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def events():
    d.store.flush(10)
    with d.store.lock:
        return [r[0] for r in d.store.db.execute('SELECT detail FROM events ORDER BY id').fetchall()]


def row():
    return d.esp_row(GWID)


def admin_gw(session):
    code, out = call('/api/esp', session=session)
    return next((g for g in out.get('gateways') or [] if g['id'] == GWID), None)


ANSWERS = []          # every answer of the API, for the secret check at the end


def say(path, body=None, session=None):
    code, out = call(path, body, session)
    ANSWERS.append(json.dumps(out))
    return code, out


try:
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
    d.account_add('eva', 'viewer', 'eva pass 1234', must_change=False, quiet=True)
    S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
    SO = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''
    SV = call('/api/auth/login', {'name': 'eva', 'password': 'eva pass 1234'})[1].get('token') or ''
    check(S and SO and SV, 'the sign-ins')

    # ---- 2. permissions ----------------------------------------------------------------------
    print('permissions')
    for who in (SO, SV, None):
        code, _ = call('/api/esp', session=who)
        check(code == 403, 'GET /api/esp for %s: %s' % (who and who[:4], code))
        code, _ = call('/api/esp', {'action': 'probe', 'address': ADDR}, session=who)
        check(code == 403, 'probe for %s: %s' % (who and who[:4], code))
    check(gw.requests == [], 'the gateway was asked by somebody refused: %r' % gw.requests)

    # ---- 3. probing, pairing -----------------------------------------------------------------
    print('pairing')
    code, out = say('/api/esp', {'action': 'probe', 'address': ADDR}, S)
    check(code == 200 and out.get('fingerprint') == gw.fingerprint and len(out.get('groups') or []) == 16,
          'probe: %s %r' % (code, out))
    code, out = say('/api/esp', {'action': 'probe', 'address': '127.0.0.1:1'}, S)
    check(code == 502 and 'nothing listens' in out.get('error', ''), 'a probe of nothing: %s %r' % (code, out))
    # not confirmed, a fingerprint that is not the gateway's: refused before anything is sent
    gw.new_code()
    code, out = say('/api/esp', {'action': 'pair', 'address': ADDR, 'code': gw.code[0], 'fingerprint': gw.fingerprint,
                                 'confirmed': False}, S)
    check(code == 400 and 'confirm' in out.get('error', ''), 'unconfirmed: %s %r' % (code, out))
    code, out = say('/api/esp', {'action': 'pair', 'address': ADDR, 'code': gw.code[0], 'fingerprint': 'ab' * 32,
                                 'confirmed': True}, S)
    check(code == 409 and 'different certificate' in out.get('error', ''), 'a fingerprint mismatch: %s %r' % (code, out))
    check(not any(p.endswith('/pair') for _m, p in gw.requests) and gw.code is not None,
          'something was sent on a mismatch: %r' % gw.requests)
    code, out = say('/api/esp', {'action': 'pair', 'address': ADDR, 'code': '12345', 'fingerprint': gw.fingerprint,
                                 'confirmed': True}, S)
    check(code == 400, 'a 5-digit code: %s' % code)
    right = gw.code[0]
    wrong = '%06d' % ((int(right) + 1) % 1000000)
    code, out = say('/api/esp', {'action': 'pair', 'address': ADDR, 'code': wrong, 'fingerprint': gw.fingerprint,
                                 'confirmed': True}, S)
    check(code == 409 and 'did not take the code' in out.get('error', ''), 'a wrong code: %s %r' % (code, out))
    code, out = say('/api/esp', {'action': 'pair', 'address': ADDR, 'code': right, 'fingerprint': gw.fingerprint,
                                 'confirmed': True}, S)
    check(code == 409 and gw.key is None, 'the code was not spent by the wrong try: %s %r' % (code, out))
    for _ in range(3):
        say('/api/esp', {'action': 'pair', 'address': ADDR, 'code': gw.new_code() and wrong,
                         'fingerprint': gw.fingerprint, 'confirmed': True}, S)
    code, out = say('/api/esp', {'action': 'pair', 'address': ADDR, 'code': gw.new_code(), 'fingerprint': gw.fingerprint,
                                 'confirmed': True}, S)
    check(code == 409 and 'locked' in out.get('error', '') and gw.key is None, 'the lockout: %s %r' % (code, out))
    check(row() is None, 'something kept after refusals')
    gw.locked_until = 0
    code, out = say('/api/esp', {'action': 'pair', 'address': ADDR, 'code': gw.new_code(), 'fingerprint': gw.fingerprint,
                                 'confirmed': True, 'name': 'Hall'}, S)
    check(code == 200 and out.get('id') == GWID and gw.key is not None, 'pairing: %s %r' % (code, out))
    KEY = (row() or {}).get('key') or ''
    check(len(KEY) == 64 and bytes.fromhex(KEY) == gw.key, 'the key kept is not the one handed over')
    check(gw.zigmon and gw.zigmon.startswith('ZIGMon on '), 'the name it was told: %r' % gw.zigmon)
    g = admin_gw(S)
    check(g and g['key_set'] is True and g['key_hint'] == KEY[-2:] and 'key' not in g and g['name'] == 'Hall'
          and g['fingerprint'] == gw.fingerprint, 'the admin view: %r' % g)
    check(until(lambda: (admin_gw(S) or {}).get('online') is True, 8), 'not online after pairing')

    # ---- 4. detect ---------------------------------------------------------------------------
    print('detect')
    code, out = say('/api/esp', {'action': 'detect', 'id': GWID}, S)
    check(code == 200 and [m['id'] for m in out.get('modules') or []] == ['yeelock', 'climate']
          and out.get('entities') == 3, 'detect: %s %r' % (code, out))
    for dev_id, kind in ((FRONT, 'Lock'), (CAB, 'Lock'), (BOX, 'Sensor')):
        dev = d.store.device(dev_id) or {}
        check(dev.get('source') == 'esp' and dev.get('kind') == kind, '%s: %r' % (dev_id, dev))
    check(until(lambda: ((d.live.get(FRONT) or {}).get('payload') or {}).get('state') == 'locked'), 'the state into live')
    check(((d.live.get(FRONT) or {}).get('payload') or {}).get('battery') == 87, 'the battery: %r' % d.live.get(FRONT))
    check(until(lambda: ((d.live.get(BOX) or {}).get('payload') or {}).get('state') == 21.5), 'the sensor into live')
    st = d.status()
    ents = {e['id']: e for e in st['esp']['entities']}
    check(set(ents) == {FRONT, CAB, BOX} and ents[FRONT]['confirm'] == ['open', 'unlock']
          and ents[FRONT]['values'].get('battery') == 87, 'the dashboard: %r' % ents.get(FRONT))
    devs = {x['id']: x for x in st['devices']}
    check(FRONT in devs and devs[FRONT]['online'] and devs[FRONT]['battery'] == 87, 'the device row: %r' % devs.get(FRONT))
    check(any(t['value'] == FRONT for t in st['switch_targets']) and not any(t['value'] == BOX for t in st['switch_targets']),
          'the targets offered')
    # which are used
    code, out = say('/api/esp', {'action': 'use', 'id': GWID, 'use': {'climate.box': False}}, S)
    check(code == 200 and out.get('used') == 2 and (d.store.device(BOX) is None or d.store.device(BOX).get('removed')),
          'not using the sensor: %s %r %r' % (code, out, d.store.device(BOX)))
    check(BOX not in {e['id'] for e in d.status()['esp']['entities']}, 'an unused entity on the dashboard')
    say('/api/esp', {'action': 'use', 'id': GWID, 'use': {'climate.box': True}}, S)
    check(until(lambda: d.store.device(BOX) and not d.store.device(BOX).get('removed')), 'the sensor back')

    # ---- 5. commands ---------------------------------------------------------------------------
    print('commands')
    code, out = say('/api/esp/command', {'id': FRONT, 'action': 'unlock'}, SO)
    check(code == 409 and out.get('confirm') is True, 'unlock without the confirm step: %s %r' % (code, out))
    code, out = say('/api/esp/command', {'id': FRONT, 'action': 'unlock'}, SV)
    check(code == 403, 'a viewer unlocking: %s' % code)
    code, out = say('/api/esp/command', {'id': FRONT, 'action': 'explode', 'confirmed': True}, SO)
    check(code == 502 and 'takes' in out.get('error', ''), 'an unknown action: %s %r' % (code, out))
    n = len(gw.requests)
    code, out = say('/api/esp/command', {'id': FRONT, 'action': 'unlock', 'confirmed': True}, SO)
    check(code == 202 and out.get('ok'), 'unlock: %s %r' % (code, out))
    check(until(lambda: ((d.live.get(FRONT) or {}).get('payload') or {}).get('state') == 'unlocked', 6), 'unlocked in live')
    check(until(lambda: 'Front drawer: unlocked from the dashboard (jana)' in events(), 6),
          'the event: %r' % events()[-5:])
    check(('POST', '/zigmon/v1/command') in gw.requests[n:], 'the command sent: %r' % gw.requests[n:])
    code, out = say('/api/esp/command', {'id': FRONT, 'action': 'lock'}, SO)
    check(code == 202, 'lock needs no confirm: %s %r' % (code, out))
    check(until(lambda: ((d.live.get(FRONT) or {}).get('payload') or {}).get('state') == 'locked', 6), 'locked again')
    # a failure, said as such
    gw.fail_next.add('open')
    say('/api/esp/command', {'id': CAB, 'action': 'open', 'confirmed': True}, S)
    check(until(lambda: any('Medicine cabinet: could not open (no answer from the lock) from the dashboard (owner)' in e
                            for e in events()), 6), 'the failed result: %r' % events()[-4:])
    # a scene and a rule's target
    check(d._valid_target(FRONT) == FRONT and d._valid_target(BOX) is None
          and d._valid_target('esp:%s:nothing' % GWID) is None, 'the targets checked')
    check(zigmon.valid_action('unlock') == 'unlock' and zigmon.valid_action('explode') is None, 'valid_action')
    code, out = say('/api/scenes', {'scenes': [{'name': 'Leaving', 'actions': [{'target': CAB, 'do': 'lock'}]}]}, S)
    check(code == 200, 'a scene with a lock: %s %r' % (code, out))
    sid = (d.scenes() or [{}])[0].get('id')
    code, out = say('/api/scene/run', {'id': sid}, SO)
    check(code == 200 and until(lambda: (d.status()['esp']['entities'] and
                                         next(e for e in d.status()['esp']['entities'] if e['id'] == CAB)['value'] == 'locked'), 6),
          'the scene locked the cabinet: %s %r' % (code, out))
    check(until(lambda: any(e.startswith('Medicine cabinet: locked by ') or e.startswith('Medicine cabinet: locked from ')
                            for e in events()), 6), 'the scene\'s event: %r' % events()[-4:])
    n = len(gw.requests)
    d._fire_spec(FRONT, 'open', 'rule: the drawer test')
    check(until(lambda: 'Front drawer: opened by rule: the drawer test' in events(), 6), 'a rule\'s fire: %r' % events()[-3:])

    # ---- 6. events: a sensor's new value -----------------------------------------------------
    print('events into the house')
    gw.push('climate.box', 'reading', value=23.25)
    check(until(lambda: ((d.live.get(BOX) or {}).get('payload') or {}).get('state') == 23.25, 5), 'the pushed value')
    d.store.flush(10)
    check('state' in d.store.keys_for(BOX), 'no history of the sensor: %r' % d.store.keys_for(BOX))
    gw.push('yeelock.front', 'out of reach', available=False)
    check(until(lambda: (d.live.get(FRONT) or {}).get('availability') == 'offline', 5), 'an unavailable lock')
    gw.push('yeelock.front', 'back', available=True)
    check(until(lambda: (d.live.get(FRONT) or {}).get('availability') == 'online', 5), 'the lock in reach again')

    # ---- 7. the Stream Deck -------------------------------------------------------------------
    print('the Stream Deck')
    caps = zigmon.Daemon.deck_default_caps()
    check(caps['locks'] == {'on': False, 'all': False, 'targets': [], 'hold': True}, 'the default locks: %r' % caps['locks'])
    items = {it['id']: it for it in d.deck_items(fresh=True)}
    check(items.get(FRONT, {}).get('cap') == 'locks' and items[FRONT]['kind'] == 'lock'
          and items[FRONT]['actions'] == ['open', 'unlock', 'lock', 'refresh'] and items[FRONT]['state']['battery'],
          'the lock item: %r' % items.get(FRONT))
    check(items.get(BOX, {}).get('cap') == 'view' and items[BOX]['actions'] == [], 'the sensor item: %r' % items.get(BOX))
    XL = {'id': 'C0FFEE00XL09', 'type': 2, 'name': 'Stream Deck XL', 'cols': 8, 'rows': 4, 'approved': True}

    def deck(c, body):
        d._deck_setup()
        d._deck_rates.clear()
        return d.deck_do({'id': 'b1' * 16, 'name': 'DESK', 'decks': [XL], 'caps': c}, dict(body, deck=XL['id']))
    code, out = deck(caps, {'id': FRONT, 'action': 'unlock', 'held_ms': 2000})
    check(code == 403 and out.get('cap') == 'locks', 'locks off by default: %s %r' % (code, out))
    loose = zigmon.Daemon.deck_default_caps()
    loose['locks'] = {'on': True, 'all': True, 'targets': [], 'hold': False}
    code, out = deck(loose, {'id': FRONT, 'action': 'unlock'})
    check(code == 409 and out.get('hold') is True, 'unlock not held, the hold off: %s %r' % (code, out))
    n = len(gw.requests)
    code, out = deck(loose, {'id': FRONT, 'action': 'lock'})
    check(code == 200, 'lock not held, the hold off: %s %r' % (code, out))
    check(until(lambda: "Front drawer: locked by Stream Deck 'DESK'" in events(), 6), 'the deck\'s lock')
    code, out = deck(loose, {'id': FRONT, 'action': 'unlock', 'held_ms': 1600})
    check(code == 200, 'unlock held: %s %r' % (code, out))
    check(until(lambda: "Front drawer: unlocked by Stream Deck 'DESK'" in events(), 6), 'the deck\'s event: %r' % events()[-3:])
    out_item = d.deck_item_out(loose, items[FRONT])
    check(out_item['hold'] is True and out_item['allowed'] is True, 'the item as a deck sees it: %r' % out_item)
    held = zigmon.Daemon.deck_default_caps()
    held['locks'] = {'on': True, 'all': True, 'targets': [], 'hold': True}
    code, out = deck(held, {'id': FRONT, 'action': 'lock'})
    check(code == 409, 'lock with the hold on, not held: %s' % code)
    cat = {it['id']: it for it in d.deck_catalog({'id': 'b1' * 16, 'name': 'DESK', 'decks': [XL], 'caps': held}, True)['items']}
    check(cat.get(FRONT, {}).get('hold') is True and cat[FRONT]['cap'] == 'locks', 'the catalogue: %r' % cat.get(FRONT))
    try:
        d._deck_clean_caps({'locks': {'on': True, 'all': False, 'targets': [FRONT], 'hold': True}})
    except ValueError as e:
        check(False, 'granting one lock: %s' % e)

    # ---- 8. a bad signature, a replayed answer, the nonces ------------------------------------
    print('signatures and replays')
    check(len(gw.seen_nonces) == len(set(gw.seen_nonces)) and len(gw.seen_nonces) > 10,
          'a nonce used twice: %d of %d' % (len(set(gw.seen_nonces)), len(gw.seen_nonces)))
    gw.bad_sig = True
    check(until(lambda: (admin_gw(S) or {}).get('online') is False, 8), 'an answer signed wrong taken')
    check('not signed with the device key' in (admin_gw(S) or {}).get('error', ''), 'the words: %r' % admin_gw(S))
    code, out = say('/api/esp/command', {'id': FRONT, 'action': 'lock'}, SO)
    check(code == 502 and 'not signed' in out.get('error', ''), 'a command answered with a bad signature: %s %r' % (code, out))
    gw.bad_sig = False
    check(until(lambda: (admin_gw(S) or {}).get('online') is True, 8), 'back after the bad signatures')
    gw.replay = True
    check(until(lambda: (admin_gw(S) or {}).get('online') is False, 8), 'a replayed answer taken')
    gw.replay = False
    gw.last_answer = None
    check(until(lambda: (admin_gw(S) or {}).get('online') is True, 8), 'back after the replays')
    # the gateway's side: a request sent twice is refused the second time
    host, port, _ = zigmon.esp_address(ADDR)
    ts, nonce = str(int(time.time())), 'ff' * 16
    heads = {'X-Zigmon-Ts': ts, 'X-Zigmon-Nonce': nonce,
             'X-Zigmon-Sig': zigmon.esp_sign(gw.key, 'GET', '/zigmon/v1/hello', ts, nonce, b'')}
    first = zigmon.esp_https(host, port, 'GET', '/zigmon/v1/hello', b'', heads, pin=gw.fingerprint)[0]
    second = zigmon.esp_https(host, port, 'GET', '/zigmon/v1/hello', b'', heads, pin=gw.fingerprint)[0]
    check(first == 200 and second == 401, 'the fake\'s own replay guard: %s %s' % (first, second))

    # ---- 9. offline and back, a restart, a changed certificate ---------------------------------
    print('offline, a restart, another certificate')
    gw.stop()
    check(until(lambda: (admin_gw(S) or {}).get('online') is False, 8), 'not offline')
    check(until(lambda: (d.live.get(FRONT) or {}).get('availability') == 'offline', 3), 'its locks not offline')
    check(any('ESP32 gateway Hall is offline' in e for e in events()), 'the offline event: %r' % events()[-3:])
    code, out = say('/api/esp/command', {'id': FRONT, 'action': 'lock'}, SO)
    check(code == 502, 'a command to an offline gateway: %s' % code)
    gw.start()
    check(until(lambda: (admin_gw(S) or {}).get('online') is True, 8), 'not back')
    check(until(lambda: (d.live.get(FRONT) or {}).get('availability') == 'online', 3), 'its locks not back')
    check('ESP32 gateway Hall is back' in events(), 'the back event')
    before_boot = (row() or {}).get('boot')
    gw.reboot(add=({'id': 'yeelock.garage', 'module': 'yeelock', 'type': 'lock', 'name': 'Garage box',
                    'actions': ['open', 'unlock', 'lock'], 'attrs': [], 'confirm': ['open', 'unlock']},
                   {'available': True, 'value': 'locked', 'busy': False, 'attrs': {}, 'last': None}))
    GAR = 'esp:%s:yeelock.garage' % GWID
    check(until(lambda: d.store.device(GAR), 8), 'the new entity after a restart: %r' % events()[-3:])
    check((row() or {}).get('boot') not in (None, '', before_boot), 'the boot kept')
    check(any('Hall restarted' in e for e in events()), 'the restart event')
    check(until(lambda: ((d.live.get(GAR) or {}).get('payload') or {}).get('state') == 'locked', 5), 'its state')
    gw.stop()
    gw.start(new_cert=True)
    gw.requests[:] = []
    check(until(lambda: (admin_gw(S) or {}).get('cert_bad') is True, 8), 'a changed certificate taken: %r' % admin_gw(S))
    time.sleep(1.0)
    check(gw.requests == [], 'a request sent to a changed certificate: %r' % gw.requests)
    check(any('certificate is not the one paired with' in e for e in events()), 'the certificate event')
    # pairing it again with the new one
    code, out = say('/api/esp', {'action': 'probe', 'address': ADDR}, S)
    check(out.get('fingerprint') == gw.fingerprint and (out.get('known') or {}) == {}, 'the new probe: %r' % out)
    gw.key = None
    code, out = say('/api/esp', {'action': 'pair', 'address': ADDR, 'code': gw.new_code(), 'fingerprint': gw.fingerprint,
                                 'confirmed': True}, S)
    check(code == 200 and out.get('again') is True, 'paired again: %s %r' % (code, out))
    check(until(lambda: (admin_gw(S) or {}).get('online') is True and not admin_gw(S)['cert_bad'], 8), 'online again')
    KEY2 = (row() or {}).get('key') or ''
    check(KEY2 != KEY and (row() or {}).get('name') == 'Hall', 'a new key, the old name: %r' % row())

    # ---- 10. rename, off and on, unpair, forget ------------------------------------------------
    print('rename, switch off, unpair, forget')
    code, out = say('/api/esp', {'action': 'rename', 'id': GWID, 'name': 'Hallway'}, S)
    check(code == 200 and (row() or {}).get('name') == 'Hallway', 'rename: %s %r' % (code, out))
    code, out = say('/api/esp', {'action': 'rename', 'id': GWID, 'name': 'x'}, SO)
    check(code == 403, 'an operator renaming: %s' % code)
    code, out = say('/api/esp', {'action': 'disable', 'id': GWID}, S)
    check(code == 200 and (row() or {}).get('enabled') is False, 'disable: %s %r' % (code, out))
    time.sleep(1.5)
    gw.requests[:] = []
    time.sleep(1.5)
    check(gw.requests == [], 'asked while switched off: %r' % gw.requests)
    code, out = say('/api/esp/command', {'id': FRONT, 'action': 'lock'}, SO)
    check(code in (404, 502), 'a command while switched off: %s %r' % (code, out))
    say('/api/esp', {'action': 'enable', 'id': GWID}, S)
    check(until(lambda: (admin_gw(S) or {}).get('online') is True, 8), 'on again')
    # every secret, nowhere
    print('no secret anywhere')
    d.store.flush(10)
    texts = {'the log': '\n'.join(LOG), 'the events': '\n'.join(events()),
             'the status': json.dumps(d.status()), '/api/esp': json.dumps(call('/api/esp', session=S)[1]),
             'the export': json.dumps(d.export_settings(secrets=False)),
             'the export with secrets': json.dumps(d.export_settings(secrets=True)),
             'the deck catalogue': json.dumps(d.deck_catalog({'id': 'b1' * 16, 'name': 'D', 'decks': [XL], 'caps': held}, True)),
             'the answers': '\n'.join(ANSWERS)}
    for name, text in texts.items():
        for k in (KEY, KEY2):
            check(k and k not in text and k.upper() not in text, 'the device key in %s' % name)
    code, out = say('/api/esp', {'action': 'unpair', 'id': GWID}, S)
    check(code == 200 and gw.key is None and row() is None, 'unpair: %s %r' % (code, out))
    check(d.store.device(FRONT) is None or d.store.device(FRONT).get('removed'), 'its devices kept')
    check(FRONT not in d.live, 'its live state kept')
    # paired again, then forgotten here without the gateway told
    say('/api/esp', {'action': 'pair', 'address': ADDR, 'code': gw.new_code(), 'fingerprint': gw.fingerprint,
                     'confirmed': True}, S)
    check(row() is not None, 'paired for the forget')
    gw.stop()
    code, out = say('/api/esp', {'action': 'unpair', 'id': GWID}, S)
    check(code == 400 and 'Forget it' in out.get('error', '') and row() is not None, 'unpair offline: %s %r' % (code, out))
    code, out = say('/api/esp', {'action': 'delete', 'id': GWID}, S)
    check(code == 200 and row() is None, 'forget: %s %r' % (code, out))
    check(not any(t.startswith('esp:') for t in [x['value'] for x in d.status()['switch_targets']]), 'targets kept')
finally:
    try:
        gw.close()
    except Exception:
        pass
    try:
        d.store.flush(5)
    except Exception:
        pass

print('FAILED: %d' % len(bad) if bad else 'all good')
sys.exit(1 if bad else 0)
