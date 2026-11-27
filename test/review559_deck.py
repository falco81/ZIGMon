#!/usr/bin/env python3
"""5.59: the ZIGMon side of ZIGMon for Stream Deck, the Elgato plugin for Windows.

  * the master switch (meta deck_enabled) is off by default: every road - pairing too - is
    403 {"off": true}; an administrator switches it on (the PIN), an operator and nobody 403;
  * pairing: a request (install, computer, plugin, decks) is given a code XXX-XXX from the
    32 letters, a pairing secret zsp_... and a pair id of 24 hex; at most 5 wait (the oldest
    goes), each 15 minutes, at most 10 requests an hour from one address (429); pair_wait by
    the secret alone (a wrong one 401 and counted), pending / denied / expired, and approved:
    the token zsd_ + 40 once, then never again; only its sha256 and last two characters kept;
  * a wrong token, a token with another installation's id: 401, counted as a wrong one-tap
    secret and noted as an anomaly, past ten a minute 429; revoked: 401 {"revoked": true};
  * the decks one by one: approved with the request (the administrator may untick one), a new
    one named in deck_info waits ("deck_pending" on a command), approved or removed by hand;
  * every capability allowed and refused by its scope (off, only these, every), view and
    status only looked at, a light's brightness under "dim", the hold (409 under 1500 ms);
  * the values: a range, a choice, a delta added, clamped and rounded to the step;
  * 10 commands a second and 300 a minute per installation (429);
  * each command goes through the one-tap links' executor (_fire_target) with the origin
    "Stream Deck '<name>'" and is an event "Stream Deck 'OFFICE-PC' (XL) turned on Lampa";
    approvals, refusals, permissions and revocations are events naming who - never a secret;
  * hello, catalog, state and wait in the shapes of the contract; wait coalesces the latest
    state of each item, holds and wakes on a change, says reset for another boot;
  * update / download: the manifest's exact bytes and its Ed25519 signature (a throwaway key
    made with openssl), the file byte for byte; a file of another SHA-256 is not offered;
  * the administrator's roads (ALWAYS_LOCKED) and the relay (php -S): api=deck&do=..., its
    headers cut down to [A-Za-z0-9_-], a bad do 400, api=deck-admin, api=deck-plugin;
  * install.sh copies streamdeck/dist into LIB_DIR/streamdeck (dry run and real); make-release
    signs streamdeck/dist/plugin.json and says to commit the signature;
  * the page (Playwright): Settings - Messages - Stream Deck at desktop and phone width.
    Screenshots into $ZIGMON_SHOTS or the scratch folder of this work.

    python3 test/review559_deck.py < /dev/null

Ports 20260-20269. Every key, token and secret here is made up.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-deck-'))
API_PORT, PHP_PORT = 20260, 20261
SHOTS = Path(os.environ.get('ZIGMON_SHOTS') or tempfile.mkdtemp(prefix='zigmon-deck-shots-'))
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


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


for _p in (API_PORT, PHP_PORT):
    if not port_free(_p):
        print('port %d stays busy' % _p)
        sys.exit(2)

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
    'debug': 1, 'blacklist': 0, 'public_view': False, 'deck_dir': str(W / 'nodeck')})
d = zigmon.Daemon()
d.notify = lambda message, *a, **k: None
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)

# what the executor reached, one step below it: the socket and Zigbee switching
RAN = []


def _run_binding(p, do, origin, pulse_ms=None, stagger=0.0):
    p.output_at = time.time()
    RAN.append(('plug', getattr(p, 'name', p), do, origin))


d._run_binding = _run_binding
d._run_zigbee_switch = lambda dev, key, do, origin, pulse_ms=None: RAN.append(('zb', dev, key, do, origin))
d.run_scene = lambda sid, origin='', *a, **k: RAN.append(('scene', sid, origin))
d.system_action = lambda what, do='on', origin='': RAN.append(('sys', what, do, origin))
d._tell_out = lambda what, origin='': RAN.append(('tell', what, origin))


def call(path, body=None, session=None, token=None, install=None, pair=None, client='192.168.40.10', timeout=60,
         raw=False, method=None):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': client}
    if session:
        headers['X-Zigmon-Session'] = session
    if token is not None:
        headers['X-Zigmon-Deck'] = token
    if install is not None:
        headers['X-Zigmon-Deck-Install'] = install
    if pair is not None:
        headers['X-Zigmon-Deck-Pair'] = pair
    if body is not None and session:
        body = dict(body, session=session)
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                 data=None if body is None else json.dumps(body).encode(),
                                 method=method or ('GET' if body is None else 'POST'))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            if raw:
                return r.status, data, dict(r.headers)
            return r.status, json.loads(data or b'{}')
    except urllib.error.HTTPError as e:
        data = e.read()
        if raw:
            return e.code, data, dict(e.headers)
        return e.code, json.loads(data or b'{}')


def report(name, payload):
    d.handle_zigbee(name, json.dumps(payload).encode())


def events():
    with d.store.lock:
        return [r[0] for r in d.store.db.execute('SELECT detail FROM events ORDER BY id').fetchall()]


def b64u(obj):
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip('=')


INSTALL = 'a1b2c3d4e5f60718293a4b5c6d7e8f90'
XL = {'id': 'C0FFEE00XL01', 'type': 2, 'name': 'Stream Deck XL', 'cols': 8, 'rows': 4}
PLUS = {'id': 'C0FFEE00PL02', 'type': 7, 'name': 'Stream Deck +', 'cols': 4, 'rows': 2}
NEO = {'id': 'C0FFEE00NE03', 'type': 9, 'name': 'Neo', 'cols': 4, 'rows': 2}
TOKENS = []
SECRETS = []

try:
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
    S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
    SO = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''
    check(S and SO, 'could not sign in')

    # ---- the house -------------------------------------------------------------------------
    d.store.set_meta('managed', json.dumps({'plugs': [
        {'name': 'Lampa', 'host': '127.0.0.1:1', 'switch_id': 0, 'kind': 'plug', 'role': 'light', 'host_state': 'enabled'},
        {'name': 'Zasuvka', 'host': '127.0.0.1:2', 'switch_id': 0, 'kind': 'plug', 'host_state': 'enabled'}],
        'sensors': []}))
    d.reload_devices()
    d.plugs['Lampa'].flat = {'switch.output': False, 'switch.apower': 0.0}
    d.plugs['Zasuvka'].flat = {'switch.output': True, 'switch.apower': 35.25, 'switch.aenergy.total': 1200.5}
    for p in d.plugs.values():
        p.error = None
    BULB, THERMO, BLIND, TEMP = '0x00158d0002000001', '0x00158d0002000002', '0x00158d0002000003', '0x00158d0002000004'
    for ident, name, exposes in (
            (BULB, 'Zarovka', {'state': {'access': 7, 'type': 'binary'},
                               'brightness': {'access': 7, 'type': 'numeric', 'min': 0, 'max': 254},
                               'color_temp': {'access': 7, 'type': 'numeric', 'min': 153, 'max': 500}}),
            (THERMO, 'Hlavice', {'current_heating_setpoint': {'access': 7, 'type': 'numeric', 'min': 5, 'max': 30,
                                                             'unit': '°C'},
                                 'system_mode': {'access': 7, 'type': 'enum', 'values': ['off', 'heat', 'auto']},
                                 'local_temperature': {'access': 1, 'type': 'numeric', 'unit': '°C'}}),
            (BLIND, 'Roleta', {'state': {'access': 7, 'type': 'enum', 'values': ['OPEN', 'CLOSE', 'STOP']},
                               'position': {'access': 7, 'type': 'numeric', 'min': 0, 'max': 100, 'unit': '%'}}),
            (TEMP, 'Teplomer', {'temperature': {'access': 1, 'type': 'numeric', 'unit': '°C'},
                                'humidity': {'access': 1, 'type': 'numeric', 'unit': '%'}})):
        d.store.upsert_device({'id': ident, 'name': name, 'source': 'zigbee', 'kind': 'EndDevice', 'exposes': exposes})
        d.names[name] = ident
    report('Zarovka', {'state': 'ON', 'brightness': 120, 'color_temp': 300, 'linkquality': 120})
    report('Hlavice', {'current_heating_setpoint': 21, 'system_mode': 'heat', 'local_temperature': 20.5, 'battery': 77})
    report('Roleta', {'state': 'OPEN', 'position': 40})
    report('Teplomer', {'temperature': 21.5, 'humidity': 40, 'battery': 90})
    d.store.set_meta('rooms', json.dumps([{'id': 'r1', 'name': 'Obývák'}, {'id': 'r2', 'name': 'Ložnice'}]))
    d.store.set_meta('room_of', json.dumps({'Lampa': 'r1', BULB: 'r1', TEMP: 'r2', THERMO: 'r2'}))
    d.store.set_meta('scenes', json.dumps([{'id': 'sc1', 'name': 'Večer', 'actions': [
        {'target': 'Lampa', 'do': 'on'}]}]))
    d.store.set_meta('rules', json.dumps([{'id': 'ru1', 'name': 'Noc', 'device': TEMP, 'key': 'temperature', 'op': '>',
                                           'value': 25, 'target': 'Zasuvka', 'do': 'off', 'enabled': True}]))
    d.store.set_meta('active_alerts', json.dumps([{'id': 'a1', 'ts': int(time.time()), 'text': 'Leak in the bathroom'}]))
    if hasattr(d.rules, 'cache_clear'):
        d.rules.cache_clear()

    # ---- the switch --------------------------------------------------------------------------
    print('the master switch')
    check('/api/deck/admin' in zigmon.ApiHandler.ALWAYS_LOCKED and '/api/deck/plugin' in zigmon.ApiHandler.ALWAYS_LOCKED,
          'the admin roads are not among the locked reads')
    check('x-zigmon-deck' in zigmon.SECRET_HEADER_NAMES and 'x-zigmon-deck-pair' in zigmon.SECRET_HEADER_NAMES,
          'the headers are not among the secret ones')
    check(d.deck_enabled() is False, 'the switch is on by default')
    PAIR_BODY = {'install': INSTALL, 'computer': 'OFFICE-PC', 'plugin': '1.0.0', 'decks': [XL, PLUS]}
    code, out = call('/api/deck/pair', PAIR_BODY)
    check(code == 403 and out == {'ok': False, 'error': 'Stream Deck control is switched off in ZIGMon', 'off': True},
          'pairing while off: %s %r' % (code, out))
    for road in ('hello', 'catalog', 'state', 'wait', 'update', 'download', 'pair_wait'):
        code, out = call('/api/deck/' + road, token='zsd_x', install=INSTALL)
        check(code == 403 and out.get('off') is True, '%s while off: %s %r' % (road, code, out))
    code, out = call('/api/deck/admin')
    check(code == 403, 'nobody reads the admin view: %s %r' % (code, out))
    code, out = call('/api/deck/admin', session=SO)
    check(code == 403, 'an operator reads the admin view: %s %r' % (code, out))
    code, out = call('/api/deck/admin', {'action': 'enable'}, session=SO)
    check(code == 403 and not d.deck_enabled(), 'an operator switches it on: %s %r' % (code, out))
    code, out = call('/api/deck/admin', {'action': 'enable'})
    check(code == 403 and not d.deck_enabled(), 'nobody switches it on: %s %r' % (code, out))
    code, out = call('/api/deck/admin', session=S)
    check(code == 200 and out.get('enabled') is False and out.get('installs') == [] and out.get('pairs') == []
          and out.get('plugin') is None and out.get('most') == {'installs': 10, 'decks': 8, 'pairs': 5},
          'the admin view: %s %r' % (code, {k: v for k, v in out.items() if k != 'items'}))
    code, out = call('/api/deck/admin', {'action': 'enable'}, session=S)
    check(code == 200 and out.get('enabled') is True and d.deck_enabled(), 'the admin switches it on: %s %r' % (code, out))
    check(any('owner switched on Stream Deck control' in e for e in events()), 'no event of the switch')

    # ---- pairing ------------------------------------------------------------------------------
    print('pairing')
    code, out = call('/api/deck/pair', method='GET')
    check(code == 405, 'pairing by GET: %s %r' % (code, out))
    code, out = call('/api/deck/pair', dict(PAIR_BODY, install='not-hex'), client='192.168.40.20')
    check(code == 400, 'a bad install id: %s %r' % (code, out))
    code, out = call('/api/deck/pair', PAIR_BODY, client='192.168.40.20')
    check(code == 200 and re.match(r'^[0-9a-f]{24}$', out.get('pair') or '')
          and re.match(r'^zsp_[A-Za-z0-9_-]{40}$', out.get('secret') or '')
          and re.match(r'^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{3}-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{3}$', out.get('code') or '')
          and abs(out.get('expires', 0) - (time.time() + 900)) < 5 and set(out) == {'ok', 'pair', 'secret', 'code', 'expires'},
          'the request: %s %r' % (code, out))
    P1 = out
    SECRETS.append(P1.get('secret'))
    code, out = call('/api/deck/admin', session=S)
    pr = (out.get('pairs') or [{}])[0]
    check(len(out.get('pairs') or []) == 1 and pr.get('code') == P1['code'] and pr.get('computer') == 'OFFICE-PC'
          and pr.get('from') == '192.168.40.20' and [x['id'] for x in pr.get('decks') or []] == [XL['id'], PLUS['id']]
          and pr['decks'][0].get('type_name') == 'Stream Deck XL' and pr['decks'][0].get('cols') == 8
          and 'secret' not in json.dumps(out) and P1['secret'] not in json.dumps(out),
          'the request in the admin view: %r' % out.get('pairs'))
    check(any("the Stream Deck plugin on 'OFFICE-PC' asks to be paired (code %s" % P1['code'] in e for e in events()),
          'no event of the request')
    # a wrong pairing secret is refused and counted
    WHO = '198.51.100.9'
    tries = len((getattr(d, '_tap_tries', None) or {}).get(WHO, []))
    code, out = call('/api/deck/pair_wait', pair='zsp_' + 'B' * 40, client=WHO)
    check(code == 401 and len(d._tap_tries.get(WHO, [])) == tries + 1, 'a wrong pairing secret: %s %r' % (code, out))
    # pending, held and answered at once when approved
    pair = d.deck_pair_find(P1['secret'])
    check(pair is not None and d.deck_pair_wait(pair, timeout=0.2) == {'ok': True, 'state': 'pending',
                                                                        'expires': P1['expires']},
          'pending: %r' % (pair and d.deck_pair_wait(pair, timeout=0.2)))
    # at most five wait: the oldest goes
    others = []
    for i in range(5):
        code, out = call('/api/deck/pair', dict(PAIR_BODY, install='%032x' % (i + 1), computer='PC-%d' % i),
                         client='192.168.40.%d' % (30 + i))
        others.append(out)
        SECRETS.append(out.get('secret'))
    code, out = call('/api/deck/admin', session=S)
    check(len(out.get('pairs') or []) == 5 and P1['code'] not in [p['code'] for p in out.get('pairs') or []],
          'five waiting, the oldest gone: %r' % [p['computer'] for p in out.get('pairs') or []])
    code, out = call('/api/deck/pair_wait', pair=P1['secret'], client='192.168.40.20')
    check(code == 401, 'the dropped request still answers: %s %r' % (code, out))
    # ten an hour from one address
    for i in range(10):
        code, out = call('/api/deck/pair', dict(PAIR_BODY, computer='Flood'), client='192.168.40.99')
    check(code == 200, 'the tenth request in the hour: %s %r' % (code, out))
    code, out = call('/api/deck/pair', dict(PAIR_BODY, computer='Flood'), client='192.168.40.99')
    check(code == 429, 'the eleventh request in the hour: %s %r' % (code, out))
    # deny
    code, out = call('/api/deck/pair', dict(PAIR_BODY, install='%032x' % 77, computer='DENY-ME'), client='192.168.40.21')
    PD = out
    SECRETS.append(PD.get('secret'))
    code, out = call('/api/deck/admin', {'action': 'deny', 'pair': PD['pair']}, session=SO)
    check(code == 403, 'an operator denies: %s %r' % (code, out))
    code, out = call('/api/deck/admin', {'action': 'deny', 'pair': PD['pair']}, session=S)
    check(code == 200 and PD['pair'] not in [p['pair'] for p in out.get('pairs') or []], 'deny: %s %r' % (code, out))
    code, out = call('/api/deck/pair_wait', pair=PD['secret'], client='192.168.40.21')
    check(code == 200 and out == {'ok': True, 'state': 'denied'}, 'denied: %s %r' % (code, out))
    check(any("owner refused the Stream Deck plugin on 'DENY-ME'" in e for e in events()), 'no event of the refusal')
    code, out = call('/api/deck/admin', {'action': 'approve', 'pair': PD['pair']}, session=S)
    check(code == 400, 'approving a refused request: %s %r' % (code, out))
    # expired
    code, out = call('/api/deck/pair', dict(PAIR_BODY, install='%032x' % 78, computer='LATE'), client='192.168.40.22')
    PE = out
    SECRETS.append(PE.get('secret'))
    d._deck_pairs[PE['pair']]['expires'] = time.time() - 1
    code, out = call('/api/deck/pair_wait', pair=PE['secret'], client='192.168.40.22')
    check(code == 200 and out == {'ok': True, 'state': 'expired'}, 'expired: %s %r' % (code, out))
    code, out = call('/api/deck/admin', {'action': 'approve', 'pair': PE['pair']}, session=S)
    check(code == 400, 'approving an expired request: %s %r' % (code, out))
    # approve, the XL ticked and the + not; the plugin waiting is answered at once, once
    code, out = call('/api/deck/pair', PAIR_BODY, client='192.168.40.20')
    P1 = out
    SECRETS.append(P1.get('secret'))
    box = {}

    def waiter():
        box['r'] = call('/api/deck/pair_wait', pair=P1['secret'], client='192.168.40.20')
        box['at'] = time.time()

    th = threading.Thread(target=waiter)
    th.start()
    time.sleep(0.8)
    t0 = time.time()
    code, out = call('/api/deck/admin', {'action': 'approve', 'pair': P1['pair'], 'decks': [XL['id']]}, session=SO)
    check(code == 403, 'an operator approves: %s %r' % (code, out))
    code, out = call('/api/deck/admin', {'action': 'approve', 'pair': P1['pair'], 'decks': [XL['id']]}, session=S)
    check(code == 200 and len(out.get('installs') or []) == 1, 'approve: %s %r' % (code, out))
    th.join(30)
    code, out = box.get('r') or (0, {})
    TOKEN = out.get('token') or ''
    TOKENS.append(TOKEN)
    check(code == 200 and out.get('state') == 'approved' and re.match(r'^zsd_[A-Za-z0-9_-]{40}$', TOKEN)
          and box.get('at', 99) - t0 < 3, 'the token, at once: %s %r' % (code, out))
    check(out.get('install') == {'id': INSTALL, 'name': 'OFFICE-PC', 'caps': zigmon.Daemon.deck_default_caps(),
                                 'hint': TOKEN[-2:]}, 'the install with the token: %r' % out.get('install'))
    code, out = call('/api/deck/pair_wait', pair=P1['secret'], client='192.168.40.20')
    check(code == 200 and out.get('state') == 'approved' and 'token' not in out and out.get('taken') is True,
          'the token a second time: %s %r' % (code, out))
    raw = d.store.get_meta('deck_installs') or ''
    check(TOKEN not in raw and hashlib.sha256(TOKEN.encode()).hexdigest() in raw, 'what is kept: %r' % raw[:300])
    code, out = call('/api/deck/admin', session=S)
    inst = (out.get('installs') or [{}])[0]
    check(inst.get('name') == 'OFFICE-PC' and inst.get('approved_by') == 'owner' and inst.get('hint') == TOKEN[-2:]
          and [(x['id'], x['approved']) for x in inst.get('decks') or []] == [(XL['id'], True), (PLUS['id'], False)]
          and 'hash' not in inst and TOKEN not in json.dumps(out), 'the installation: %r' % inst)
    check(any("owner approved the Stream Deck installation 'OFFICE-PC' (1 deck; view, status)" in e for e in events()),
          'no event of the approval: %r' % events()[-3:])

    # ---- the token ----------------------------------------------------------------------------
    print('the token and the installation')

    def deck(road, body=None, token=None, install=INSTALL, client='192.168.40.50', timeout=60, rate=False):
        if road == 'do' and not rate:
            d._deck_rates.clear()          # the rate is tried by itself, below
        return call('/api/deck/' + road, body, token=TOKEN if token is None else token, install=install,
                    client=client, timeout=timeout)

    code, out = deck('hello')
    check(code == 200 and out.get('ok') and out.get('api') == 1 and out.get('server') == 'zigmon'
          and out.get('version') == zigmon.__version__ and out.get('house') and re.match(r'^[0-9a-f]{12}$', out.get('boot', ''))
          and isinstance(out.get('seq'), int) and out.get('plugin') is None
          and out.get('install') == {'id': INSTALL, 'name': 'OFFICE-PC', 'caps': zigmon.Daemon.deck_default_caps(),
                                     'hint': TOKEN[-2:]}, 'hello: %s %r' % (code, out))
    check([(x['id'], x['type'], x['name'], x['approved']) for x in out.get('decks') or []]
          == [(XL['id'], 2, 'Stream Deck XL', True), (PLUS['id'], 7, 'Stream Deck +', False)],
          'hello decks: %r' % out.get('decks'))
    BOOT = out.get('boot')
    WHO = '198.51.100.10'
    code, out = deck('hello', token='zsd_' + 'C' * 40, client=WHO)
    check(code == 401 and len(d._tap_tries.get(WHO, [])) == 1 and 'revoked' not in out, 'a wrong token: %s %r' % (code, out))
    check(any('bad-secret' in str(a) for a in d._anomaly.get(WHO, [])), 'not noted as an anomaly: %r' % d._anomaly.get(WHO))
    code, out = deck('hello', install='%032x' % 5, client=WHO)
    check(code == 401 and len(d._tap_tries.get(WHO, [])) == 2, 'another installation\'s id: %s %r' % (code, out))
    code, out = deck('hello', install='', client=WHO)
    check(code == 401, 'no installation id: %s %r' % (code, out))
    for _ in range(9):
        code, out = deck('hello', token='zsd_wrong', client=WHO)
    check(code == 429, 'past ten wrong a minute: %s %r' % (code, out))
    code, out = deck('hello', client=WHO)
    check(code == 429, 'the right token from a guessing address: %s %r' % (code, out))
    code, out = deck('other')
    check(code == 400, 'another road: %s %r' % (code, out))
    code, out = call('/api/status', token=TOKEN, install=INSTALL)
    check(code == 403, 'the token opens the status (view locked): %s %r' % (code, out))
    code, out = call('/api/deck/admin', token=TOKEN, install=INSTALL)
    check(code == 403, 'the token reads the admin view: %s %r' % (code, out))
    # ---- the catalogue, the states --------------------------------------------------------
    print('the catalogue and the states')
    code, out = deck('catalog')
    items = {it['id']: it for it in out.get('items') or []}
    check(code == 200 and set(out) == {'ok', 'boot', 'seq', 'rooms', 'items'} and out.get('boot') == BOOT
          and out.get('rooms') == [{'id': 'r1', 'name': 'Obývák'}, {'id': 'r2', 'name': 'Ložnice'}],
          'the catalogue: %s %r' % (code, {k: v for k, v in out.items() if k != 'items'}))
    for it in items.values():
        check(set(it) == {'id', 'name', 'room', 'kind', 'icon', 'cap', 'actions', 'attrs', 'allowed', 'hold', 'state'}
              and set(it['state']) == {'on', 'value', 'value_text', 'attrs', 'online', 'battery', 'at'}
              and it['kind'] in ('socket', 'light', 'switch', 'dimmer', 'thermostat', 'cover', 'scene', 'sequence',
                                 'group', 'rule', 'schedule', 'message', 'system', 'sensor', 'reading', 'status')
              and it['cap'] in zigmon.Daemon.DECK_CAPS, 'the shape of %s: %r' % (it['id'], it))
    lamp = items.get('Lampa') or {}
    check(lamp.get('kind') == 'light' and lamp.get('cap') == 'switch' and lamp.get('actions') == ['toggle', 'on', 'off']
          and lamp.get('allowed') is False and lamp.get('room') == 'Obývák' and lamp['state']['on'] is False,
          'Lampa (looked at only): %r' % lamp)
    sock = items.get('Zasuvka') or {}
    check(sock.get('kind') == 'socket' and sock['state']['value'] == 35.25 and sock['state']['value_text'] == '35.25 W'
          and sock['state']['on'] is True, 'the socket: %r' % sock)
    bulb = items.get('zb:%s:state' % BULB) or {}
    check(bulb.get('kind') == 'light' and bulb['state']['on'] is True and bulb['state']['attrs'] == {'brightness': 120, 'color_temp': 300}
          and [a.get('via') for a in bulb.get('attrs') or []] == ['zb:%s:brightness' % BULB, 'zb:%s:color_temp' % BULB],
          'the bulb: %r' % bulb)
    dim = items.get('zb:%s:brightness' % BULB) or {}
    check(dim.get('kind') == 'dimmer' and dim.get('cap') == 'dim' and dim.get('actions') == ['set', 'step']
          and dim['attrs'][0] == {'key': 'brightness', 'label': 'Brightness', 'type': 'number', 'unit': None, 'min': 0,
                                  'max': 254, 'step': 1} and dim['state']['value'] == 120, 'the dimmer: %r' % dim)
    sp = items.get('zb:%s:current_heating_setpoint' % THERMO) or {}
    check(sp.get('kind') == 'thermostat' and sp.get('cap') == 'climate' and sp['attrs'][0]['step'] == 0.5
          and sp['attrs'][0]['min'] == 5 and sp['attrs'][0]['max'] == 30 and sp['state']['value'] == 21
          and sp['state']['battery'] == 77 and sp['state']['attrs'].get('local_temperature') == 20.5,
          'the set point: %r' % sp)
    mode = items.get('zb:%s:system_mode' % THERMO) or {}
    check(mode.get('actions') == ['set'] and mode['attrs'][0]['type'] == 'enum'
          and mode['attrs'][0]['values'] == ['off', 'heat', 'auto'], 'the mode: %r' % mode)
    blind = items.get('zb:%s:state' % BLIND) or {}
    check(blind.get('kind') == 'cover' and blind.get('cap') == 'cover' and blind.get('actions') == ['open', 'close', 'stop', 'set', 'step']
          and blind['state']['value'] == 40, 'the blind: %r' % blind)
    check(items.get('scene:sc1', {}).get('cap') == 'scenes' and items['scene:sc1']['actions'] == ['run']
          and items.get('rule:ru1', {}).get('cap') == 'automations' and items['rule:ru1']['state']['on'] is True
          and items.get('tell:house', {}).get('cap') == 'messages' and items.get('sys:refresh', {}).get('cap') == 'system'
          and items['sys:refresh']['hold'] is True and items.get('heat:temp:r1', {}).get('cap') == 'climate',
          'the scene, rule, message, system and heating items: %r' % [items.get(k) for k in ('scene:sc1', 'rule:ru1')])
    rd = items.get('read:%s:temperature' % TEMP) or {}
    check(rd.get('kind') == 'reading' and rd.get('cap') == 'view' and rd.get('actions') == [] and rd.get('allowed') is True
          and rd['state']['value'] == 21.5 and rd['state']['value_text'] == '21.5 °C' and rd['state']['battery'] == 90
          and rd.get('room') == 'Ložnice' and rd['attrs'][0]['type'] == 'number', 'a reading: %r' % rd)
    st = {k: items.get('status:' + k) for k in ('alerts', 'blocked', 'proxy', 'health', 'gateway')}
    check(all(v and v['cap'] == 'status' and v['allowed'] is True for v in st.values())
          and st['alerts']['state']['value'] == 1 and st['alerts']['state']['on'] is False
          and st['alerts']['state']['attrs'] == {'latest': 'Leak in the bathroom', 'level': 'crit'},
          'the status items: %r' % st)
    code, out = deck('state?ids=Lampa,read:%s:temperature,status:alerts,nothing' % TEMP)
    check(code == 200 and set(out) == {'ok', 'boot', 'seq', 'items'}
          and set(out['items']) == {'Lampa', 'read:%s:temperature' % TEMP, 'status:alerts'}
          and out['items']['Lampa'] == lamp['state'], 'state?ids: %s %r' % (code, out))
    code, out = deck('state')
    check(code == 200 and set(out['items']) == set(items), 'state of every visible: %r' % len(out.get('items') or {}))

    # ---- the decks one by one ------------------------------------------------------------------
    print('the decks one by one')
    code, out = deck('do', {'deck': PLUS['id'], 'id': 'Lampa', 'action': 'on'})
    check(code == 403 and out == {'ok': False, 'error': 'This Stream Deck is not approved in ZIGMon yet',
                                  'deck_pending': True}, 'the + unticked: %s %r' % (code, out))
    code, out = call('/api/deck/hello?decks=%s,%s&deck_info=%s' % (XL['id'], NEO['id'], b64u([NEO])), token=TOKEN,
                     install=INSTALL)
    check(code == 200 and [(x['id'], x['approved']) for x in out.get('decks') or []]
          == [(XL['id'], True), (PLUS['id'], False), (NEO['id'], False)]
          and out['decks'][2]['name'] == 'Neo' and out['decks'][2]['type'] == 9, 'a new deck named: %r' % out.get('decks'))
    check(any("a new Stream Deck (Stream Deck Neo 'Neo') is waiting for approval under the Stream Deck installation "
              "'OFFICE-PC'" in e for e in events()), 'no event of the new deck')
    code, out = deck('hello?deck_info=' + 'A' * 3000)
    check(code == 400, 'deck_info past 2 KB: %s %r' % (code, out))
    code, out = deck('hello?deck_info=bm90IGpzb24')
    check(code == 400, 'deck_info not JSON: %s %r' % (code, out))
    code, out = deck('do', {'deck': 'UNKNOWN99', 'id': 'Lampa', 'action': 'on'})
    check(code == 403 and out.get('deck_pending') is True, 'a deck never named: %s %r' % (code, out))
    code, out = call('/api/deck/admin', session=S)
    decks_now = [(x['id'], x['approved']) for x in out['installs'][0]['decks']]
    check(decks_now == [(XL['id'], True), (PLUS['id'], False), (NEO['id'], False), ('UNKNOWN99', False)],
          'the decks waiting: %r' % decks_now)
    code, out = call('/api/deck/admin', {'action': 'deck_approve', 'install': INSTALL, 'deck': PLUS['id']}, session=SO)
    check(code == 403, 'an operator approves a deck: %s %r' % (code, out))
    code, out = call('/api/deck/admin', {'action': 'deck_approve', 'install': INSTALL, 'deck': PLUS['id']}, session=S)
    check(code == 200, 'approve the +: %s %r' % (code, out))
    code, out = call('/api/deck/admin', {'action': 'deck_remove', 'install': INSTALL, 'deck': 'UNKNOWN99'}, session=S)
    check(code == 200 and [x['id'] for x in out['installs'][0]['decks']] == [XL['id'], PLUS['id'], NEO['id']],
          'remove a deck: %s %r' % (code, out))
    check(any("owner approved the Stream Deck + 'Stream Deck +' of the Stream Deck installation 'OFFICE-PC'" in e
              for e in events()) and any("owner removed the Stream Deck 'UNKNOWN99'" in e for e in events()),
          'no events of the decks: %r' % events()[-4:])
    code, out = deck('do', {'deck': PLUS['id'], 'id': 'Lampa', 'action': 'on'})
    check(code == 403 and out.get('allowed') is False and 'deck_pending' not in out,
          'the + approved, the switch not granted: %s %r' % (code, out))

    # ---- every capability by its scope -----------------------------------------------------
    print('every capability by its scope')

    def caps(**given):
        c = zigmon.Daemon.deck_default_caps()
        for k, v in given.items():
            c[k] = dict(c[k], **v)
        code, out = call('/api/deck/admin', {'action': 'caps', 'install': INSTALL, 'caps': c}, session=S)
        assert code == 200, (code, out)
        return out

    cases = [('switch', 'Lampa', {'action': 'on'}, ('plug', 'Lampa', 'on'), 'Zasuvka'),
             ('dim', 'zb:%s:brightness' % BULB, {'action': 'set', 'value': 128}, ('zb', BULB, 'brightness', 'set:128'),
              'zb:%s:color_temp' % BULB),
             ('climate', 'zb:%s:current_heating_setpoint' % THERMO, {'action': 'set', 'value': 22.5},
              ('zb', THERMO, 'current_heating_setpoint', 'set:22.5'), 'zb:%s:system_mode' % THERMO),
             ('cover', 'zb:%s:state' % BLIND, {'action': 'close'}, ('zb', BLIND, 'state', 'set:CLOSE'), None),
             ('scenes', 'scene:sc1', {'action': 'run'}, ('scene', 'sc1'), None),
             ('automations', 'rule:ru1', {'action': 'off'}, None, None),
             ('messages', 'tell:house', {'action': 'run'}, ('tell', 'house'), 'tell:who'),
             ('system', 'sys:refresh', {'action': 'run', 'held_ms': 1600}, ('sys', 'refresh', 'on'), 'sys:backup')]
    for cap, iid, body, want, other in cases:
        caps()
        RAN.clear()
        code, out = deck('do', dict(body, deck=XL['id'], id=iid))
        check(code == 403 and out.get('allowed') is False and out.get('cap') == cap and not RAN,
              '%s off: %s %r %r' % (cap, code, out, RAN))
        if other:
            caps(**{cap: {'on': True, 'all': False, 'targets': [other]}})
            code, out = deck('do', dict(body, deck=XL['id'], id=iid))
            check(code == 403 and out.get('allowed') is False and not RAN, '%s only another: %s %r' % (cap, code, out))
        caps(**{cap: {'on': True, 'all': False, 'targets': [iid]}})
        code, out = deck('do', dict(body, deck=XL['id'], id=iid))
        time.sleep(0.3)
        check(code == 200 and out.get('ok') is True and isinstance(out.get('said'), str)
              and set(out['state']) == {'on', 'value', 'value_text', 'attrs', 'online', 'battery', 'at'},
              '%s only this: %s %r' % (cap, code, out))
        if want:
            check(any(r[:len(want)] == want and r[-1] == "Stream Deck 'OFFICE-PC'" for r in RAN),
                  '%s did not reach the executor: %r' % (cap, RAN))
        caps(**{cap: {'on': True, 'all': True, 'targets': []}})
        code, out = deck('do', dict(body, deck=XL['id'], id=iid))
        check(code == 200, '%s every: %s %r' % (cap, code, out))
        if cap == 'automations':
            check(d.rules()[0].get('enabled') is False, 'the rule was not switched off: %r' % d.rules())
        code, out = deck('catalog')
        got = {it['id']: it for it in out['items']}
        check(got[iid]['allowed'] is True, '%s: the catalogue does not say allowed: %r' % (cap, got[iid]))
    check(any("Stream Deck 'OFFICE-PC' (XL) turned on Lampa" == e for e in events()),
          'no event of the command: %r' % [e for e in events() if 'Stream Deck' in e][-5:])
    check(any("Stream Deck 'OFFICE-PC' (XL) set Zarovka · Brightness to 128" == e for e in events())
          and any("Stream Deck 'OFFICE-PC' (XL) closed Roleta" == e for e in events())
          and any("Stream Deck 'OFFICE-PC' (XL) ran Večer" == e for e in events()),
          'the words of the commands: %r' % [e for e in events() if e.startswith('Stream Deck')][-12:])
    check(any("owner changed what the Stream Deck installation 'OFFICE-PC' may do (view, system (hold), status)" in e
              for e in events()), 'no event of the permissions: %r' % [e for e in events() if 'may do' in e][-3:])
    # view and status are only looked at
    caps(switch={'on': True, 'all': True})
    for iid in ('read:%s:temperature' % TEMP, 'status:alerts'):
        code, out = deck('do', {'deck': XL['id'], 'id': iid, 'action': 'on'})
        check(code == 403 and 'only be looked at' in out.get('error', ''), '%s commanded: %s %r' % (iid, code, out))
    code, out = deck('do', {'deck': XL['id'], 'id': 'no such thing', 'action': 'on'})
    check(code == 404, 'an unknown item: %s %r' % (code, out))
    code, out = deck('do', {'deck': XL['id'], 'id': 'Lampa', 'action': 'run'})
    check(code == 400, 'an action the item does not take: %s %r' % (code, out))
    code, out = deck('do', {'id': 'Lampa', 'action': 'on'})
    check(code == 400, 'no deck: %s %r' % (code, out))
    code, out = call('/api/deck/do', token=TOKEN, install=INSTALL)
    check(code == 405, 'a command by GET: %s %r' % (code, out))
    # a light's brightness is "dim", whichever key asks for it
    RAN.clear()
    code, out = deck('do', {'deck': XL['id'], 'id': 'zb:%s:state' % BULB, 'action': 'set', 'attr': 'brightness', 'value': 50})
    check(code == 403 and out.get('cap') == 'dim' and not RAN, 'brightness through the light, dim off: %s %r' % (code, out))
    caps(switch={'on': True, 'all': True}, dim={'on': True, 'all': True})
    code, out = deck('do', {'deck': XL['id'], 'id': 'zb:%s:state' % BULB, 'action': 'set', 'attr': 'brightness', 'value': 50})
    time.sleep(0.2)
    check(code == 200 and ('zb', BULB, 'brightness', 'set:50', "Stream Deck 'OFFICE-PC'") in RAN,
          'brightness through the light: %s %r %r' % (code, out, RAN))
    code, out = deck('do', {'deck': XL['id'], 'id': 'Lampa', 'action': 'set', 'attr': 'nothing', 'value': 50})
    check(code == 400, 'an attribute the item has not: %s %r' % (code, out))
    # visibility: view off, one socket granted - only it and the status are seen
    caps(view={'on': False}, switch={'on': True, 'all': False, 'targets': ['Zasuvka']})
    code, out = deck('catalog')
    check(code == 200 and sorted(it['id'] for it in out['items']) == ['Zasuvka'] + sorted('status:' + k for k in st),
          'what is seen with view off: %r' % [it['id'] for it in out['items']])
    code, out = deck('state?ids=Lampa,Zasuvka')
    check(list(out.get('items') or {}) == ['Zasuvka'], 'state of what is not seen: %r' % out)
    code, out = deck('do', {'deck': XL['id'], 'id': 'Lampa', 'action': 'on'})
    check(code == 404, 'a command on what is not seen: %s %r' % (code, out))
    caps(view={'on': True, 'all': False, 'targets': ['read:%s:humidity' % TEMP]}, status={'on': False})
    code, out = deck('catalog')
    check(sorted(it['id'] for it in out['items']) == ['read:%s:humidity' % TEMP], 'view of one reading: %r'
          % [it['id'] for it in out['items']])
    code, out = call('/api/deck/admin', {'action': 'caps', 'install': INSTALL, 'caps': {'switch': {'on': True, 'all': False,
                                                                                                   'targets': ['scene:sc1']}}},
                     session=S)
    check(code == 400 and 'is not a thing of switch' in out.get('error', ''), 'a scene granted as a switch: %s %r' % (code, out))
    code, out = call('/api/deck/admin', {'action': 'caps', 'install': INSTALL, 'caps': {'switch': {'on': 'yes'}}}, session=S)
    check(code == 400, 'on that is not true or false: %s %r' % (code, out))
    code, out = call('/api/deck/admin', {'action': 'caps', 'install': INSTALL, 'caps': {'everything': {'on': True}}}, session=S)
    check(code == 400, 'a capability that does not exist: %s %r' % (code, out))
    code, out = call('/api/deck/admin', {'action': 'caps', 'install': INSTALL, 'caps': {'switch': {'on': True, 'all': True}}},
                     session=SO)
    check(code == 403, 'an operator changes the permissions: %s %r' % (code, out))

    # ---- the hold, the values ----------------------------------------------------------------
    print('the hold and the values')
    caps(switch={'on': True, 'all': True, 'hold': True}, climate={'on': True, 'all': True}, dim={'on': True, 'all': True},
         cover={'on': True, 'all': True}, system={'on': True, 'all': True})
    for held in (None, 0, 1499, '2000', True):
        body = {'deck': XL['id'], 'id': 'Lampa', 'action': 'toggle'}
        if held is not None:
            body['held_ms'] = held
        code, out = deck('do', body)
        check(code == 409 and out == {'ok': False, 'error': 'Hold the key to confirm', 'hold': True},
              'held %r: %s %r' % (held, code, out))
    code, out = deck('do', {'deck': XL['id'], 'id': 'Lampa', 'action': 'toggle', 'held_ms': 1500})
    check(code == 200, 'held 1500 ms: %s %r' % (code, out))
    code, out = deck('do', {'deck': XL['id'], 'id': 'sys:backup', 'action': 'run'})
    check(code == 409 and out.get('hold') is True, 'system holds by default: %s %r' % (code, out))
    code, out = deck('catalog')
    got = {it['id']: it for it in out['items']}
    check(got['Lampa']['hold'] is True and got['sys:backup']['hold'] is True and got['scene:sc1']['hold'] is False,
          'the catalogue\'s hold: %r' % [(k, got[k]['hold']) for k in ('Lampa', 'sys:backup', 'scene:sc1')])
    SP = 'zb:%s:current_heating_setpoint' % THERMO
    for body, want in (({'action': 'set', 'value': 31}, 400), ({'action': 'set', 'value': 4.5}, 400),
                       ({'action': 'set', 'value': '22'}, 400), ({'action': 'set'}, 400),
                       ({'action': 'set', 'value': True}, 400), ({'action': 'step'}, 400),
                       ({'action': 'step', 'delta': 'up'}, 400)):
        code, out = deck('do', dict(body, deck=XL['id'], id=SP))
        check(code == want, 'the set point %r: %s %r' % (body, code, out))
    for body, sent in (({'action': 'set', 'value': 21.3}, 'set:21.5'), ({'action': 'set', 'value': 30}, 'set:30'),
                       ({'action': 'step', 'delta': 0.5}, 'set:21.5'), ({'action': 'set', 'delta': 100}, 'set:30'),
                       ({'action': 'step', 'delta': -100}, 'set:5'), ({'action': 'step', 'delta': 0.3}, 'set:21.5')):
        RAN.clear()
        d._pending_set.pop((THERMO, 'current_heating_setpoint'), None)
        code, out = deck('do', dict(body, deck=XL['id'], id=SP))
        time.sleep(0.15)
        check(code == 200 and [r[3] for r in RAN if r[0] == 'zb'] == [sent], 'the set point %r: %s %r %r'
              % (body, code, out, RAN))
    MODE = 'zb:%s:system_mode' % THERMO
    for body, sent in (({'action': 'set', 'value': 'auto'}, 'set:auto'), ({'action': 'set', 'value': 'HEAT'}, 'set:heat'),
                       ({'action': 'set', 'delta': 1}, 'set:auto'), ({'action': 'set', 'delta': -1}, 'set:off')):
        RAN.clear()
        code, out = deck('do', dict(body, deck=XL['id'], id=MODE))
        time.sleep(0.15)
        check(code == 200 and [r[3] for r in RAN if r[0] == 'zb'] == [sent], 'the mode %r: %s %r %r' % (body, code, out, RAN))
    for body in ({'action': 'set', 'value': 'cool'}, {'action': 'set', 'value': 3}, {'action': 'set', 'delta': 0.5}):
        code, out = deck('do', dict(body, deck=XL['id'], id=MODE))
        check(code == 400, 'the mode %r: %s %r' % (body, code, out))
    RAN.clear()
    code, out = deck('do', {'deck': XL['id'], 'id': 'zb:%s:state' % BLIND, 'action': 'set', 'value': 75})
    code2, out2 = deck('do', {'deck': XL['id'], 'id': 'zb:%s:state' % BLIND, 'action': 'step', 'delta': -50})
    time.sleep(0.2)
    check(code == 200 and code2 == 200 and [r[2:4] for r in RAN] == [('position', 'set:75'), ('position', 'set:0')],
          'the blind\'s position: %s %s %r' % (code, code2, RAN))
    code, out = deck('do', {'deck': XL['id'], 'id': 'heat:temp:r1', 'action': 'set', 'value': 22.4})
    check(code == 200 and out.get('said') == 'set Temperature in Obývák to 22.5 °C', 'a room\'s temperature: %s %r' % (code, out))

    # ---- the rate -----------------------------------------------------------------------------
    print('the rate')
    caps(switch={'on': True, 'all': True})
    d._deck_rates.clear()
    got = []
    for i in range(11):
        got.append(deck('do', {'deck': XL['id'], 'id': 'Zasuvka', 'action': 'toggle'}, rate=True)[0])
    check(got[:10] == [200] * 10 and got[10] == 429, 'ten a second: %r' % got)
    d._deck_rates[INSTALL] = [time.time() - 30] * 300
    code, out = deck('do', {'deck': XL['id'], 'id': 'Zasuvka', 'action': 'toggle'}, rate=True)
    check(code == 429, '300 a minute: %s %r' % (code, out))
    d._deck_rates.clear()

    # ---- the long wait ------------------------------------------------------------------------
    print('the long wait')
    caps(switch={'on': True, 'all': True})
    code, out = deck('hello')
    SEQ = out['seq']
    code, out = deck('wait?after=0&boot=%s' % BOOT)
    check(code == 200 and set(out) == {'ok', 'boot', 'seq', 'reset', 'changes'} and out['reset'] is False
          and out['changes'] and all(set(c) == {'seq', 'id', 'state'} for c in out['changes'])
          and len({c['id'] for c in out['changes']}) == len(out['changes']), 'everything since 0: %r' % str(out)[:300])
    code, out = deck('wait?after=0&boot=0000&ids=Lampa')
    check(code == 200 and out['reset'] is True and out['changes'] == [], 'another boot: %r' % out)
    code, out = deck('wait?after=%d&boot=%s' % (SEQ + 1000, BOOT))
    check(out.get('reset') is True, 'a number from the future: %r' % out)
    code, out = deck('wait?after=x&boot=%s' % BOOT)
    check(code == 400, 'after not a number: %s %r' % (code, out))
    d.DECK_WAIT_S = 1.5
    t0 = time.time()
    code, out = deck('wait?after=%d&boot=%s&ids=Lampa' % (d._deck_seq, BOOT))
    check(code == 200 and out['changes'] == [] and 1.2 < time.time() - t0 < 6, 'an empty wait: %r in %.1f s'
          % (out, time.time() - t0))
    d.DECK_WAIT_S = 25.0
    SEQ = d._deck_seq
    box = {}

    def waiter():
        box['r'] = deck('wait?after=%d&boot=%s&ids=Lampa,read:%s:temperature' % (SEQ, BOOT, TEMP))
        box['at'] = time.time()

    th = threading.Thread(target=waiter)
    th.start()
    time.sleep(0.8)
    t0 = time.time()
    report('Teplomer', {'temperature': 22.0})
    report('Teplomer', {'temperature': 22.5})
    d.plugs['Lampa'].flat = {'switch.output': True, 'switch.apower': 41.0}
    d.bump()
    th.join(30)
    code, out = box.get('r') or (0, {})
    ids = [c['id'] for c in out.get('changes') or []]
    check(code == 200 and box.get('at', 99) - t0 < 5 and set(ids) <= {'Lampa', 'read:%s:temperature' % TEMP} and ids
          and len(ids) == len(set(ids)), 'the wait woken: %s %r in %.1f s' % (code, out, box.get('at', 99) - t0))
    time.sleep(0.5)
    code, out = deck('wait?after=%d&boot=%s&ids=Lampa,read:%s:temperature' % (SEQ, BOOT, TEMP))
    ch = {c['id']: c for c in out.get('changes') or []}
    check(set(ch) == {'Lampa', 'read:%s:temperature' % TEMP} and ch['read:%s:temperature' % TEMP]['state']['value'] == 22.5
          and ch['Lampa']['state']['on'] is True and ch['Lampa']['state']['value'] == 41.0
          and out['seq'] >= max(c['seq'] for c in ch.values()), 'the latest state of each: %r' % out)
    d.DECK_BATCH = 2
    code, out = deck('wait?after=0&boot=%s' % BOOT)
    check(len(out['changes']) == 2 and out['seq'] == out['changes'][-1]['seq'] < d._deck_seq, 'at most a batch: %r' % out)
    d.DECK_BATCH = 200

    # ---- revoking -----------------------------------------------------------------------------
    print('revoking')
    box = {}

    def waiter2():
        box['r'] = deck('wait?after=%d&boot=%s&ids=Lampa' % (d._deck_seq, BOOT))
        box['at'] = time.time()

    th = threading.Thread(target=waiter2)
    th.start()
    time.sleep(0.8)
    code, out = call('/api/deck/admin', {'action': 'rename', 'install': INSTALL, 'name': 'Kancelář'}, session=S)
    check(code == 200 and out['installs'][0]['name'] == 'Kancelář', 'rename: %s %r' % (code, out))
    code, out = call('/api/deck/admin', {'action': 'rename', 'install': INSTALL, 'name': ' '}, session=S)
    check(code == 400, 'an empty name: %s %r' % (code, out))
    code, out = deck('do', {'deck': XL['id'], 'id': 'Lampa', 'action': 'off'})
    check(code == 200 and any("Stream Deck 'Kancelář' (XL) turned off Lampa" == e for e in events()),
          'the new name in the events: %s %r' % (code, [e for e in events() if e.startswith('Stream Deck')][-2:]))
    t0 = time.time()
    code, out = call('/api/deck/admin', {'action': 'revoke', 'install': INSTALL}, session=SO)
    check(code == 403, 'an operator revokes: %s %r' % (code, out))
    code, out = call('/api/deck/admin', {'action': 'revoke', 'install': INSTALL}, session=S)
    check(code == 200 and out.get('installs') == [], 'revoke: %s %r' % (code, out))
    th.join(10)
    check((box.get('r') or (0, {}))[0] == 401 and box['r'][1].get('revoked') is True and box.get('at', 99) - t0 < 3.0,
          'the waiting poll after: %r' % box)
    WHO = '198.51.100.11'
    for road in ('hello', 'catalog', 'state'):
        code, out = deck(road, client=WHO)
        check(code == 401 and out.get('revoked') is True, '%s after revoking: %s %r' % (road, code, out))
    code, out = deck('do', {'deck': XL['id'], 'id': 'Lampa', 'action': 'on'}, client=WHO)
    check(code == 401 and out.get('revoked') is True, 'a command after revoking: %s %r' % (code, out))
    check(not (getattr(d, '_tap_tries', None) or {}).get(WHO), 'a revoked token is counted as a guess')
    check(any("owner revoked the Stream Deck installation 'Kancelář'" in e for e in events()), 'no event of revoking')
    code, out = call('/api/deck/admin', {'action': 'revoke', 'install': INSTALL}, session=S)
    check(code == 400, 'revoked twice: %s %r' % (code, out))
    # paired again: the same installation, a new token; the old one stays refused
    code, out = call('/api/deck/pair', PAIR_BODY, client='192.168.40.23')
    SECRETS.append(out.get('secret'))
    code, out2 = call('/api/deck/admin', {'action': 'approve', 'pair': out['pair'], 'name': 'OFFICE-PC',
                                          'caps': dict(zigmon.Daemon.deck_default_caps(),
                                                       switch={'on': True, 'all': True, 'targets': [], 'hold': False})},
                      session=S)
    check(code == 200, 'approved again: %s %r' % (code, out2))
    code, out = call('/api/deck/pair_wait', pair=out['secret'], client='192.168.40.23')
    TOKEN2 = out.get('token') or ''
    TOKENS.append(TOKEN2)
    check(TOKEN2 and TOKEN2 != TOKEN and out['install']['caps']['switch']['on'] is True, 'the new token: %r' % out)
    code, out = deck('hello', token=TOKEN2)
    check(code == 200 and [x['approved'] for x in out['decks']] == [True, True], 'with the new token: %s %r' % (code, out))
    code, out = deck('hello', client='192.168.40.24')
    check(code == 401 and out.get('revoked') is True, 'the old token after pairing again: %s %r' % (code, out))
    TOKEN = TOKEN2
    # ten installations at most
    rows = d.deck_installs()
    for i in range(9):
        rows.append(dict(rows[0], id='%032x' % (900 + i), hash='%064x' % (900 + i), name='Spare %d' % i))
    d._deck_put(rows)
    code, out = call('/api/deck/pair', dict(PAIR_BODY, install='%032x' % 999), client='192.168.40.25')
    check(code == 403 and '10' in out.get('error', ''), 'the eleventh installation: %s %r' % (code, out))
    d._deck_put(rows[:1])
finally:
    pass
