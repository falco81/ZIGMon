#!/usr/bin/env python3
"""5.59.4: the ZIGMon side of ten new Stream Deck actions (streamdeck/PROTOCOL-5.59.4.md).

  * the summaries are shown only to a plugin that asks ("extended"): an older plugin's catalogue,
    state and wait are exactly what they were;
  * house:power (the dashboard's total, today's kWh, a history for 1 h / 6 h / 24 h / 7 d);
  * status:security (alerts and blocked addresses, the latest alert without an IP, MAC or host
    name) and its "ack" - under "system", always held - which clears the latest alert only;
  * heat:group:all - every heated room set to one mode down heat:room:<id>'s road;
  * house:away - the heating's away switch, with the lights, sockets and rooms heating;
  * house:openings - the contacts open, their names, heating_loss in a heating room;
  * house:batteries, status:zigbee (who dropped off, when);
  * the timer on a switch: on now, off after N minutes (the due check with a moved clock), off_at
    in the state, replaced by a second, called off by off and by a toggle that turns it off,
    by hand held for its length, kept over a restart (a new Daemon on the same store: the
    overdue goes off at once, the rest wait);
  * room:<id> - temperature, humidity, switches on, the heating, members a deck may see;
  * status:sms - ZIGMon's own log only, the sender as …123, the text cut to 80 and scrubbed,
    today's count, the modem; mute / unmute (the house's hush) under "system", always held;
  * permissions: a deck without the capability neither sees nor acts; one failing part hides
    nothing else.

    python3 test/review5594_deck_new.py < /dev/null

Port 20301. Every name, number and address here is made up.
"""
import hashlib
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
W = Path(tempfile.mkdtemp(prefix='zigmon-decknew-'))
API_PORT = 20301
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


if not port_free(API_PORT):
    print('port %d stays busy' % API_PORT)
    sys.exit(2)

sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                               # noqa: E402

LOG = []
zigmon.log = lambda msg, level='info', *a, **k: LOG.append('%s %s' % (level, msg))
zigmon.load_config()
(W / 'state').mkdir()
zigmon.CONFIG.update({
    'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1', 'token_file': str(W / 'token'),
    'pin': '', 'sensors': [], 'plugs': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(W / 'state'),
    'debug': 0, 'blacklist': 0, 'public_view': False, 'deck_dir': str(W / 'nodeck'),
    'sms_enabled': 1, 'sms_host': '192.0.2.1', 'heating_enforce': 'never'})

RAN = []


def fake(d):
    d.notify = lambda message, *a, **k: None

    def _run_binding(p, do, origin, pulse_ms=None, stagger=0.0):
        p.output_at = time.time()
        RAN.append(('plug', getattr(p, 'name', p), do, origin))
    d._run_binding = _run_binding
    d._run_zigbee_switch = lambda dev, key, do, origin, pulse_ms=None: RAN.append(('zb', dev, key, do, origin))
    d.heating_apply = lambda *a, **k: None          # no valves to drive here
    d.sms_status_poll = lambda *a, **k: None


d = zigmon.Daemon()
fake(d)

LAMP_ROOM, BED = 'r1', 'r2'
BULB, TEMP, DOOR, WIN, REMOTE, TRV = ('0x00158d0003000001', '0x00158d0003000002', '0x00158d0003000003',
                                      '0x00158d0003000004', '0x00158d0003000005', '0x00158d0003000006')


def report(name, payload):
    d.handle_zigbee(name, json.dumps(payload).encode())


def events():
    d.store.flush(10)
    with d.store.lock:
        return [r[0] for r in d.store.db.execute('SELECT detail FROM events ORDER BY id').fetchall()]


def house(dm):
    dm.store.set_meta('managed', json.dumps({'plugs': [
        {'name': 'Lampa', 'host': '127.0.0.1:1', 'switch_id': 0, 'kind': 'plug', 'role': 'light', 'host_state': 'enabled'},
        {'name': 'Zasuvka', 'host': '127.0.0.1:2', 'switch_id': 0, 'kind': 'plug', 'host_state': 'enabled'}],
        'sensors': []}))
    dm.reload_devices()
    dm.plugs['Lampa'].flat = {'switch.output': False, 'switch.apower': 0.0}
    dm.plugs['Zasuvka'].flat = {'switch.output': True, 'switch.apower': 35.25}
    for p in dm.plugs.values():
        p.error = None


house(d)
for ident, name, exposes in (
        (BULB, 'Zarovka', {'state': {'access': 7, 'type': 'binary'},
                           'brightness': {'access': 7, 'type': 'numeric', 'min': 0, 'max': 254}}),
        (TEMP, 'Teplomer', {'temperature': {'access': 1, 'type': 'numeric', 'unit': '°C'},
                            'humidity': {'access': 1, 'type': 'numeric', 'unit': '%'}}),
        (DOOR, 'Dvere', {'contact': {'access': 1, 'type': 'binary'}}),
        (WIN, 'Okno loznice', {'contact': {'access': 1, 'type': 'binary'}}),
        (REMOTE, 'Ovladac', {'action': {'access': 1, 'type': 'enum', 'values': ['on', 'off']}}),
        (TRV, 'Hlavice', {'local_temperature': {'access': 1, 'type': 'numeric', 'unit': '°C'}})):
    d.store.upsert_device({'id': ident, 'name': name, 'source': 'zigbee', 'kind': 'EndDevice', 'exposes': exposes})
    d.names[name] = ident
report('Zarovka', {'state': 'ON', 'brightness': 120, 'linkquality': 120})
report('Teplomer', {'temperature': 15.5, 'humidity': 48, 'battery': 15})
report('Dvere', {'contact': True, 'battery': 5})
report('Okno loznice', {'contact': False, 'battery': 90})
report('Ovladac', {'action': 'on', 'battery': 60})
report('Hlavice', {'local_temperature': 19.0, 'battery': 80})
d.set_availability(TRV, 'online', 'Hlavice')
d.set_availability(TRV, 'offline', 'Hlavice')
OFF_AT = int(time.time())
d.store.set_meta('rooms', json.dumps([{'id': LAMP_ROOM, 'name': 'Obývák'}, {'id': BED, 'name': 'Ložnice'}]))
d.store.set_meta('room_of', json.dumps({'Lampa': LAMP_ROOM, BULB: LAMP_ROOM, DOOR: LAMP_ROOM,
                                        TEMP: BED, WIN: BED, 'Zasuvka': BED}))
d.store.set_meta('heating', json.dumps({'enabled': True, 'rooms': {
    LAMP_ROOM: {'mode': 'eco'}, BED: {'mode': 'comfort', 'window_stop': False}}}))
d.live['plug:Zasuvka'] = {'payload': {'switch.apower': 35.25}, 'ts': time.time()}
d.live['plug:Lampa'] = {'payload': {'switch.apower': 10.0}, 'ts': time.time()}
d._energy_summary = (time.time(), {'plugs': [{'today_wh': 1000}, {'today_wh': 500}]})
d.store.set_meta('active_alerts', json.dumps([
    {'id': 'a1', 'ts': int(time.time()) - 3 * 86400, 'text': 'an old one'},
    {'id': 'a2', 'ts': int(time.time()) - 60,
     'text': 'Suricata: 203.0.113.77:443 scanned 2001:db8::5 from aa:bb:cc:dd:ee:ff (evil.example.com), '
             'call +420 777 123 456 at 12:30:45 - Obyvak.temperature'}]))
d.store.upsert_device({'id': 'sms:gateway', 'name': 'SMS-Gateway', 'source': 'sms', 'kind': 'SMS gateway',
                       'last_seen': int(time.time())})
d.live['sms:gateway'] = {'payload': {'rssi': -70}, 'ts': time.time(), 'availability': None}

INSTALL = 'b1b2c3d4e5f60718293a4b5c6d7e8f90'
XL = {'id': 'C0FFEE00XL09', 'type': 2, 'name': 'Stream Deck XL', 'cols': 8, 'rows': 4, 'approved': True}
TOKEN = 'zsd_' + 'Q' * 40


def caps(**over):
    c = zigmon.Daemon.deck_default_caps()
    for k, v in over.items():
        c[k] = dict(c[k], **v)
    return c


INST = {'id': INSTALL, 'name': 'DESK', 'decks': [XL], 'caps': caps(), 'hash': hashlib.sha256(TOKEN.encode()).hexdigest()}
d.store.set_meta('deck_installs', json.dumps([INST]))
d.store.set_meta('deck_enabled', '1')


def inst(**over):
    return dict(INST, caps=caps(**over))


def do(body, **over):
    d._deck_setup()
    d._deck_rates.clear()
    return d.deck_do(inst(**over), dict(body, deck=XL['id']))


def catalog(extended=True, **over):
    return {it['id']: it for it in d.deck_catalog(inst(**over), extended)['items']}


EVERY = dict(switch={'on': True, 'all': True}, climate={'on': True, 'all': True},
             system={'on': True, 'all': True, 'hold': True})
NEW = ('house:power', 'status:security', 'heat:group:all', 'house:away', 'house:openings', 'house:batteries',
       'status:zigbee', 'room:r1', 'room:r2', 'status:sms')

try:
    d.sms_note('in', '+420777000111', 'an older one', road='push')
    rows = json.loads(d.store.get_meta('sms_log'))
    rows[0]['at'] = int(time.time()) - 3 * 86400
    with d._sms_lock():
        d._sms_log_write(rows)
    d.sms_note('out', '+420777000999', 'sent away')
    d.sms_note('in', '+420 603 555 123', 'Ahoj, router 192.168.1.1 is down, see fd12:3456::9 and call me back '
               'later please, this text is longer than eighty characters for sure', road='push')

    # ---- an older plugin sees what it always saw ------------------------------------------------
    print('an older plugin')
    old = catalog(False, **EVERY)
    check(not any(i in old for i in NEW), 'the summaries in an older catalogue: %r' % [i for i in NEW if i in old])
    check(old['Lampa']['actions'] == ['toggle', 'on', 'off'] and 'act' not in old.get('status:alerts', {}),
          'an older catalogue changed: %r' % old['Lampa'])
    st = d.deck_state(inst(**EVERY), [], None)
    check(not any(i in st['items'] for i in NEW), 'the summaries in an older state')
    st = d.deck_state(inst(**EVERY), ['house:power'], None)
    check(list(st['items']) == ['house:power'], 'a summary asked by name: %r' % list(st['items']))
    check(d.deck_hello(inst())['features'] == ['extended', 'timer', 'summaries-5.59.4'], 'hello features')

    print('the extended catalogue')
    cat = catalog(**EVERY)
    for i in NEW:
        check(i in cat, '%s is not in the extended catalogue' % i)
    check('timer' in cat['Lampa']['actions'] and 'timer' in cat['zb:%s:state' % BULB]['actions']
          and 'timer' not in cat['zb:%s:brightness' % BULB]['actions'], 'timer on the switches only')
    kinds = {i: cat[i]['kind'] for i in NEW if i in cat}
    check(kinds == {'house:power': 'power', 'status:security': 'security', 'heat:group:all': 'heatgroup',
                    'house:away': 'away', 'house:openings': 'openings', 'house:batteries': 'batteries',
                    'status:zigbee': 'zigbee', 'room:r1': 'room', 'room:r2': 'room', 'status:sms': 'sms'},
          'the kinds: %r' % kinds)
    capsof = {i: cat[i]['cap'] for i in NEW if i in cat}
    check(capsof == {'house:power': 'view', 'status:security': 'status', 'heat:group:all': 'climate',
                     'house:away': 'climate', 'house:openings': 'view', 'house:batteries': 'view',
                     'status:zigbee': 'status', 'room:r1': 'view', 'room:r2': 'view', 'status:sms': 'status'},
          'the caps: %r' % capsof)

    print('house power')
    pw = cat['house:power']['state']
    check(pw['value'] == 45.2 and pw['attrs']['power'] == 45.2 and pw['attrs']['kwh_today'] == 1.5
          and pw['attrs']['sockets_w'] == 35.2 and pw['attrs']['lights_w'] == 10.0 and pw['value_text'] == '45.2 W',
          'the power: %r' % pw)
    minute = int(time.time() // 60)
    d._power_minutes[:] = [[minute - 70, 1.0], [minute - 30, 40.0], [minute - 1, 50.5]]
    for span in (3600, 6 * 3600, 86400, 7 * 86400):
        h = d.deck_state(inst(), ['house:power'], {'span': span, 'points': 48}, True).get('history') or {}
        one = h.get('house:power') or {}
        check(one.get('span') == span and isinstance(one.get('points'), list), 'power history %d: %r' % (span, h))
        if span == 3600:
            check(one['points'] == [[(minute - 30) * 60, 40.0], [(minute - 1) * 60, 50.5]], 'the last hour: %r' % one)

    print('network security and its masks')
    sec = cat['status:security']
    s = sec['state']['attrs']
    check(s['alerts'] == 2 and s['alerts_24h'] == 1 and s['blocked'] == 0 and sec['state']['on'] is False,
          'the counts: %r' % s)
    latest = s['latest'] or ''
    for bit in ('203.0.113', '2001:db8', 'aa:bb', 'evil.example', '777 123 456', '777123456'):
        check(bit not in latest, '%r is in the alert text: %r' % (bit, latest))
    check('…456' in latest and '12:30:45' in latest and 'Obyvak.temperature' in latest and 'Suricata' in latest,
          'the alert text lost too much: %r' % latest)
    for raw, gone in (('from 10.0.0.1', '10.0.0.1'), ('[fe80::1%eth0]:80 x', 'fe80'), ('::ffff:192.0.2.9 x', '192.0.2'),
                      ('0x00158d0003000001 left', '0x00158d'), ('host nas.lan down', 'nas.lan'),
                      ('a.b.c.example down', 'example'), ('mac 00-11-22-33-44-55', '00-11'),
                      ('to 00420777123456 now', '777123')):
        out = zigmon.Daemon.deck_scrub(raw)
        check(gone not in out and '…' in out, 'scrub %r: %r' % (raw, out))
    for kept in ('at 12:30:45 today', 'version 5.59.4', 'Obyvak.temperature > 25', '2026-11-28 08:00'):
        check(zigmon.Daemon.deck_scrub(kept) == kept, 'scrub took from %r: %r' % (kept, zigmon.Daemon.deck_scrub(kept)))
    check(zigmon.Daemon.deck_mask_phone('+420 777 123 456') == '…456' and zigmon.Daemon.deck_mask_phone('O2') == 'O2'
          and zigmon.Daemon.deck_mask_phone('Vodafone') == 'Vodafone' and zigmon.Daemon.deck_mask_phone('') is None,
          'the phone mask')
    check(sec['act'] == {'ack': {'cap': 'system', 'allowed': True, 'hold': True}}, 'ack in the catalogue: %r' % sec.get('act'))
    check(catalog(**dict(EVERY, system={'on': False}))['status:security']['act']['ack']['allowed'] is False,
          'ack allowed without system')
    code, out = do({'id': 'status:security', 'action': 'ack'}, system={'on': False})
    check(code == 403 and out.get('cap') == 'system', 'ack without system: %s %r' % (code, out))
    code, out = do({'id': 'status:security', 'action': 'ack'}, system={'on': True, 'all': True, 'hold': False})
    check(code == 409 and out.get('hold') is True, 'ack without the hold (hold switched off): %s %r' % (code, out))
    code, out = do({'id': 'status:security', 'action': 'ack', 'held_ms': 900}, **EVERY)
    check(code == 409, 'ack held too short: %s %r' % (code, out))
    check(len(d.active_alerts()) == 2, 'an alert went without the hold')
    code, out = do({'id': 'status:security', 'action': 'ack'}, status={'on': False}, **EVERY)
    check(code == 404, 'ack on what is not seen: %s %r' % (code, out))
    code, out = do({'id': 'status:security', 'action': 'ack', 'held_ms': 1500},
                   system={'on': True, 'all': False, 'targets': ['status:security'], 'hold': True})
    check(code == 200 and [a['id'] for a in d.active_alerts()] == ['a1'] and out['state']['attrs']['alerts'] == 1,
          'ack, granted by name: %s %r %r' % (code, out, d.active_alerts()))
    check(any("Stream Deck 'DESK' (XL) acknowledged the latest alert" == e for e in events()), 'no event of ack')
    try:
        got = d._deck_clean_caps({'system': {'on': True, 'all': False, 'targets': ['status:security', 'status:sms']}})
        check(got['system']['targets'] == ['status:security', 'status:sms'], 'the admin grant: %r' % got['system'])
    except ValueError as e:
        check(False, 'the admin may not grant ack by name: %s' % e)
    try:
        d._deck_clean_caps({'system': {'on': True, 'all': False, 'targets': ['house:power']}})
        check(False, 'house:power granted under system')
    except ValueError:
        pass

    print('the heating of every room')
    hg = cat['heat:group:all']['state']
    check(hg['value'] == 'mixed' and hg['attrs']['rooms'] == 2 and hg['attrs']['calling'] == 1
          and hg['attrs']['min_temperature'] == 15.5 and hg['attrs']['max_temperature'] == 15.5, 'the group: %r' % hg)
    code, out = do({'id': 'heat:group:all', 'action': 'set', 'attr': 'mode', 'value': 'night'})
    check(code == 403 and out.get('cap') == 'climate', 'the group without climate: %s %r' % (code, out))
    code, out = do({'id': 'heat:group:all', 'action': 'set', 'attr': 'mode', 'value': 'warm'}, **EVERY)
    check(code == 400, 'a mode that is none: %s %r' % (code, out))
    code, out = do({'id': 'heat:group:all', 'action': 'set', 'attr': 'mode', 'value': 'night'}, **EVERY)
    for _ in range(50):
        if all(r.get('mode') == 'night' for r in d.heating_config()['rooms'].values()):
            break
        time.sleep(0.05)
    check(code == 200 and {k: v['mode'] for k, v in d.heating_config()['rooms'].items()} == {'r1': 'night', 'r2': 'night'},
          'every room on night: %s %r %r' % (code, out, d.heating_config()['rooms']))
    for _ in range(50):
        ev = events()
        if any('Ložnice set to night' in e for e in ev) and any('Obývák set to night' in e for e in ev):
            break
        time.sleep(0.05)
    check(any('Ložnice set to night' in e for e in ev) and any('Obývák set to night' in e for e in ev),
          'not the room road: %r' % ev[-5:])
    time.sleep(0.6)
    d._deck_items_kept = None
    check(catalog(**EVERY)['heat:group:all']['state']['attrs']['mode'] == 'night', 'the common mode')
    code, out = do({'id': 'heat:group:all', 'action': 'set', 'attr': 'mode', 'value': 'comfort', 'held_ms': 0},
                   climate={'on': True, 'all': True, 'hold': True})
    check(code == 409, 'the group under a held climate: %s %r' % (code, out))

    print('away / home')
    aw = cat['house:away']['state']
    check(aw['on'] is False and aw['attrs']['lights_on'] == 1 and aw['attrs']['sockets_on'] == 1
          and aw['attrs']['rooms_heating'] == 1, 'away: %r' % aw)
    code, out = do({'id': 'house:away', 'action': 'toggle'}, **EVERY)
    for _ in range(50):
        if d.heating_config().get('away'):
            break
        time.sleep(0.05)
    check(code == 200 and d.heating_config().get('away') is True, 'away not switched: %s %r' % (code, out))
    code, out = do({'id': 'house:away', 'action': 'off'}, **EVERY)
    for _ in range(50):
        if not d.heating_config().get('away'):
            break
        time.sleep(0.05)
    check(d.heating_config().get('away') is False, 'home again')
    d.store.set_meta('heating', json.dumps({'enabled': True, 'rooms': {
        LAMP_ROOM: {'mode': 'eco'}, BED: {'mode': 'comfort', 'window_stop': False}}}))
    time.sleep(0.6)

    print('windows and doors, batteries, the Zigbee network')
    d._deck_items_kept = None
    cat = catalog(**EVERY)
    op = cat['house:openings']['state']
    check(op['value'] == 1 and op['attrs']['names'] == ['Okno loznice'] and op['attrs']['sensors'] == 2
          and op['attrs']['heating_loss'] is True, 'openings: %r' % op)
    bt = cat['house:batteries']['state']['attrs']
    check(bt['below_20'] == 2 and bt['below_10'] == 1 and bt['lowest_name'] == 'Dvere' and bt['lowest_pct'] == 5,
          'batteries: %r' % bt)
    zb = cat['status:zigbee']['state']['attrs']
    check(zb['offline_n'] >= 1 and zb['dropped_name'] == 'Hlavice' and abs((zb['dropped_at'] or 0) - OFF_AT) <= 2
          and zb['online_n'] >= 4, 'zigbee: %r' % zb)

    print('a room')
    r1, r2 = cat['room:r1']['state'], cat['room:r2']['state']
    check(r2['value'] == 15.5 and r2['attrs']['humidity'] == 48 and r2['attrs']['heat_mode'] == 'comfort'
          and r2['attrs']['heat_target'] == 21.0 and r2['attrs']['switches'] == 1 and r2['attrs']['switches_on'] == 1,
          'the bedroom: %r' % r2)
    m1 = cat['room:r1'].get('members') or []
    check('Lampa' in m1 and 'zb:%s:state' % BULB in m1 and 'heat:room:r1' in m1 and 'Zasuvka' not in m1
          and r1['attrs']['members_n'] == len(m1) and r1['attrs']['switches'] == 2 and r1['attrs']['switches_on'] == 1
          and r1['attrs']['lights_on'] == 1, 'the living room: %r %r' % (m1, r1))
    check(not any('0x' in json.dumps(cat[i]['state']) for i in NEW), 'a Zigbee address in a summary\'s state')
    few = catalog(view={'on': True, 'all': False, 'targets': ['room:r1', 'Lampa']}, status={'on': False})
    check(sorted(few) == ['Lampa', 'room:r1'] and few['room:r1']['members'] == ['Lampa']
          and few['room:r1']['state']['attrs']['members_n'] == 1,
          'members a deck may not see: %r' % few.get('room:r1'))
    st = d.deck_state(inst(view={'on': True, 'all': False, 'targets': ['room:r1', 'Lampa']}), ['room:r1'], None)
    check(st['items']['room:r1']['attrs']['members_n'] == 1 and '_members' not in st['items']['room:r1']['attrs']
          and 'members' not in st['items']['room:r1']['attrs'], 'members in the state: %r' % st['items'])
    old_room = {it['id']: it for it in d.deck_catalog(inst(), False)['items']}
    check('room:r1' not in old_room, 'a room in an older catalogue')
    none = catalog(view={'on': False}, status={'on': False})
    check(not any(i in none for i in NEW), 'the summaries without view and status: %r' % sorted(none))

    print('text messages')
    sm = cat['status:sms']['state']['attrs']
    check(sm['last_from'] == '…123' and sm['today'] == 1 and sm['modem_online'] is True
          and len(sm['last_text']) <= 80 and '192.168' not in sm['last_text'] and 'fd12' not in sm['last_text']
          and sm['last_text'].startswith('Ahoj, router …') and isinstance(sm['last_at'], int)
          and sm['muted_until'] is None, 'sms: %r' % sm)
    check('603' not in json.dumps(cat['status:sms']) and '555' not in json.dumps(cat['status:sms']),
          'the number in the sms item: %r' % cat['status:sms'])
    code, out = do({'id': 'status:sms', 'action': 'mute', 'minutes': 30, 'held_ms': 1500})
    check(code == 403, 'mute without system: %s %r' % (code, out))
    code, out = do({'id': 'status:sms', 'action': 'mute', 'minutes': 30}, system={'on': True, 'all': True, 'hold': False})
    check(code == 409, 'mute without the hold: %s %r' % (code, out))
    for bad_min in (10, 241, '30', True, None):
        code, out = do({'id': 'status:sms', 'action': 'mute', 'minutes': bad_min, 'held_ms': 1500}, **EVERY)
        check(code == 400, 'mute %r: %s %r' % (bad_min, code, out))
    check(not d.alerts_hushed(), 'hushed by a refused mute')
    code, out = do({'id': 'status:sms', 'action': 'mute', 'minutes': 30, 'held_ms': 1500}, **EVERY)
    mu = (out.get('state') or {}).get('attrs', {}).get('muted_until') or 0
    check(code == 200 and d.alerts_hushed() and abs(mu - (time.time() + 1800)) < 5, 'mute: %s %r' % (code, out))
    code, out = do({'id': 'status:sms', 'action': 'unmute', 'held_ms': 1500}, **EVERY)
    check(code == 200 and not d.alerts_hushed() and out['state']['attrs']['muted_until'] is None,
          'unmute: %s %r' % (code, out))

    # ---- the timer --------------------------------------------------------------------------------
    print('the timer')
    RAN.clear()
    code, out = do({'id': 'Lampa', 'action': 'timer', 'minutes': 5})
    check(code == 403 and not RAN, 'a timer without switch: %s %r' % (code, out))
    for m in (0, 721, 2.5, '5', None, True):
        code, out = do({'id': 'Lampa', 'action': 'timer', 'minutes': m}, **EVERY)
        check(code == 400, 'a timer of %r: %s %r' % (m, code, out))
    code, out = do({'id': 'zb:%s:brightness' % BULB, 'action': 'timer', 'minutes': 5}, dim={'on': True, 'all': True})
    check(code == 400, 'a timer on a dimmer: %s %r' % (code, out))
    code, out = do({'id': 'Lampa', 'action': 'timer', 'minutes': 5}, switch={'on': True, 'all': True, 'hold': True})
    check(code == 409, 'a timer under a held switch: %s %r' % (code, out))
    t0 = time.time()
    code, out = do({'id': 'Lampa', 'action': 'timer', 'minutes': 5}, **EVERY)
    time.sleep(0.2)
    off_at = (out.get('state') or {}).get('attrs', {}).get('off_at')
    check(code == 200 and ('plug', 'Lampa', 'on', "Stream Deck 'DESK'") in RAN
          and isinstance(off_at, int) and abs(off_at - (t0 + 300)) < 3, 'the timer: %s %r %r' % (code, out, RAN))
    check(any("Stream Deck 'DESK' (XL) turned on Lampa for 5 min" == e for e in events()), 'no event of the timer')
    code, out = do({'id': 'Lampa', 'action': 'timer', 'minutes': 20}, **EVERY)
    off_at = out['state']['attrs'].get('off_at')
    check(abs(off_at - (time.time() + 1200)) < 3 and len([k for k in d._for_backs if 'Lampa' in k]) == 1,
          'a second timer does not replace the first: %r %r' % (off_at, d._for_backs))
    st = d.deck_state(inst(**EVERY), ['Lampa'], None)
    check(st['items']['Lampa']['attrs'].get('off_at') == off_at, 'off_at in an older plugin\'s state')
    # the due check, the clock moved past it
    RAN.clear()
    d._for_backs['plug:Lampa']['due'] = time.time() - 1
    d.check_for_backs()
    time.sleep(0.2)
    check([r[2] for r in RAN] == ['off'] and 'plug:Lampa' not in d._for_backs, 'the timer did not fire: %r' % RAN)
    d._deck_items_kept = None
    check('off_at' not in catalog(**EVERY)['Lampa']['state']['attrs'], 'off_at after it fired')
    # called off: by off, and by a toggle that turns it off
    do({'id': 'Lampa', 'action': 'timer', 'minutes': 5}, **EVERY)
    code, out = do({'id': 'Lampa', 'action': 'off'}, **EVERY)
    check(code == 200 and 'plug:Lampa' not in d._for_backs and 'off_at' not in out['state']['attrs'],
          'off did not call the timer off: %r' % d._for_backs)
    do({'id': 'Lampa', 'action': 'timer', 'minutes': 5}, **EVERY)
    d.plugs['Lampa'].flat['switch.output'] = True
    d._deck_items_kept = None
    code, out = do({'id': 'Lampa', 'action': 'toggle'}, **EVERY)
    check(code == 200 and 'plug:Lampa' not in d._for_backs, 'a toggle off did not call the timer off')
    d.plugs['Lampa'].flat['switch.output'] = False
    d._deck_items_kept = None
    do({'id': 'Lampa', 'action': 'timer', 'minutes': 5}, **EVERY)
    code, out = do({'id': 'Lampa', 'action': 'toggle'}, **EVERY)
    check('plug:Lampa' in d._for_backs, 'a toggle on called the timer off')
    # a rule's "off for N" (its way back is on) is not a deck timer: off leaves it be
    d._fire_target(('plug', d.plugs['Zasuvka']), 'off-for:10m', 'a rule')
    do({'id': 'Zasuvka', 'action': 'off'}, **EVERY)
    check(d._for_backs.get('plug:Zasuvka', {}).get('back') == 'on', 'off called off a way back to on')
    d._for_backs.pop('plug:Zasuvka', None)
    # by hand: held for the timer's length
    d.release_target()
    do({'id': 'zb:%s:state' % BULB, 'action': 'timer', 'minutes': 3, 'by_hand': True}, **EVERY)
    for _ in range(40):
        if d.manual_holds():
            break
        time.sleep(0.05)
    held = d.manual_holds().get('zb:%s:state' % BULB) or {}
    check(abs((held.get('until') or 0) - (time.time() + 181)) < 4, 'by hand, not held for the timer: %r' % held)
    check(any(r[:4] == ('zb', BULB, 'state', 'on') for r in RAN), 'the bulb was not turned on: %r' % RAN)

    print('the timers over a restart')
    d._fire_target(('plug', d.plugs['Zasuvka']), 'for:30m', "Stream Deck 'DESK'")
    d._for_backs['plug:Zasuvka']['due'] = time.time() - 5           # overdue by the time it starts again
    d._deck_timers_write()
    lamp_due = d._for_backs['plug:Lampa']['due']
    d.store.flush(10)
    d2 = zigmon.Daemon()
    fake(d2)
    house(d2)
    RAN.clear()
    d2.timers_keep()
    check('plug:Lampa' in d2._for_backs and abs(d2._for_backs['plug:Lampa']['due'] - lamp_due) < 1,
          'the timer did not come back: %r' % d2._for_backs)
    d2.check_for_backs()
    time.sleep(0.3)
    check(('Zasuvka', 'off') in [(r[1], r[2]) for r in RAN] and 'plug:Zasuvka' not in d2._for_backs,
          'the overdue did not go off at once: %r' % RAN)
    check('plug:Lampa' in d2._for_backs and not any(r[1] == 'Lampa' for r in RAN), 'the one not due fired')
    d2._deck_setup()
    check(d2.deck_state(inst(**EVERY), ['Lampa'], None)['items']['Lampa']['attrs'].get('off_at') == int(
        __import__('math').ceil(lamp_due)), 'off_at after the restart')

    # ---- one part failing hides none of the rest --------------------------------------------------
    print('one part failing')
    d._deck_power_item = lambda *a: 1 / 0
    d._deck_items_kept = None
    cat = catalog(**EVERY)
    check('house:power' not in cat and 'status:security' in cat and 'room:r1' in cat and 'Lampa' in cat,
          'a failing part hid others: %r' % sorted(cat)[:10])
    del d._deck_power_item
    t = time.time()
    for _ in range(10):
        d.deck_items(fresh=True)
    check((time.time() - t) / 10 < 0.25, 'the catalogue is slow: %.3f s' % ((time.time() - t) / 10))

    # ---- over HTTP: extended through the API, and nothing secret anywhere -------------------------
    print('over HTTP')
    d.store.set_meta('deck_installs', json.dumps([dict(INST, caps=caps(**EVERY))]))
    api = zigmon.ApiServer(d)
    api.start()
    time.sleep(0.3)

    def call(path, body=None):
        headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': '192.168.40.10',
                   'X-Zigmon-Deck': TOKEN, 'X-Zigmon-Deck-Install': INSTALL}
        req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                     data=None if body is None else json.dumps(body).encode(),
                                     method='GET' if body is None else 'POST')
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.status, json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')

    code, out = call('/api/deck/catalog')
    ids = [it['id'] for it in out.get('items') or []]
    check(code == 200 and not any(i in ids for i in NEW), 'GET catalog shows summaries: %s' % code)
    code, out = call('/api/deck/catalog?extended=1')
    ids = [it['id'] for it in out.get('items') or []]
    check(code == 200 and all(i in ids for i in NEW), 'GET catalog?extended=1: %s %r' % (code, ids[-12:]))
    code, out = call('/api/deck/catalog', {'extended': True, 'decks': XL['id']})
    check(code == 200 and all(i in [it['id'] for it in out['items']] for i in NEW), 'POST catalog extended')
    code, out = call('/api/deck/state', {'extended': True})
    check(code == 200 and all(i in out['items'] for i in NEW), 'POST state extended: %s' % code)
    seq = out['seq']
    box = {}
    th = threading.Thread(target=lambda: box.update(r=call('/api/deck/wait', {'extended': True, 'after': seq,
                                                                            'boot': d.deck_boot_for(dict(INST, caps=caps(**EVERY)))})))
    th.start()
    time.sleep(0.5)
    d.raise_alert('Port scan from 198.51.100.4')
    d._deck_refresh(force=True)
    th.join(30)
    code, out = box.get('r') or (0, {})
    ch = {c['id']: c['state'] for c in out.get('changes') or []}
    check(code == 200 and 'status:security' in ch and '198.51' not in json.dumps(ch)
          and ch['status:security']['attrs']['latest'] == 'Port scan from …', 'the wait: %s %r' % (code, out))
    code, out = call('/api/deck/do', {'deck': XL['id'], 'id': 'status:security', 'action': 'ack', 'held_ms': 1600})
    check(code == 200 and out['state']['attrs']['alerts'] == 1, 'ack over HTTP: %s %r' % (code, out))
    dump = json.dumps(d.deck_catalog(inst(**EVERY), True))
    for secret in ('203.0.113', '198.51.100', '192.168.1.1', '+420', '603 555', 'aa:bb:cc', TOKEN):
        check(secret not in dump, '%r in the catalogue' % secret)
finally:
    try:
        d.store.flush(5)
    except Exception:
        pass

print('FAILED: %d' % len(bad) if bad else 'all good')
sys.exit(1 if bad else 0)
