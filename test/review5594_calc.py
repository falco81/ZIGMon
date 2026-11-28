#!/usr/bin/env python3
"""5.59.4: computed values for the Stream Deck (streamdeck/PROTOCOL-CALC.md).

  * the values against hand-computed ones, over made-up plugs, lights, relays, sensors, contacts,
    a thermostat head that is offline, the weather and three rooms (one of them a garden);
  * every fn (sum, avg, min, max, count, on, off, pct_on, spread) and every metric family;
  * the scopes: all, a kind, a room, a kind in a room, inside and outside;
  * members / known, online false when nothing is known; min_of / max_of;
  * no nonsense: no sum of a temperature, on/off only for what switches, no extremes of one, no
    kind in a room that is the whole room;
  * the cap (600), the house first; extended only; hello names "calc";
  * permissions: view on every thing, view on only these (by the calc id), view off;
  * the history: house power from the stored samples, the lights' from the hourly figures, a ring
    for another item (a minute apart, the 300 cap, the 7 days);
  * ids with a comma of their own (room=…,kind=…) through the comma-separated ids;
  * speed: deck_items with the computed values, about sixty devices.

    python3 test/review5594_calc.py < /dev/null

Port 20331 (never opened). Every name, number and address here is made up.
"""
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-calc-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                               # noqa: E402

LOG = []
zigmon.log = lambda msg, level='info', *a, **k: LOG.append('%s %s' % (level, msg))
zigmon.load_config()
(W / 'state').mkdir()
zigmon.CONFIG.update({
    'db_file': str(W / 'z.db'), 'api_port': 20331, 'api_host': '127.0.0.1', 'token_file': str(W / 'token'),
    'pin': '', 'sensors': [], 'plugs': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(W / 'state'),
    'debug': 0, 'blacklist': 0, 'public_view': False, 'deck_dir': str(W / 'nodeck'), 'heating_enforce': 'never',
    'battery_warn': 30})

d = zigmon.Daemon()
d.notify = lambda message, *a, **k: None
d.heating_apply = lambda *a, **k: None
d._deck_calc_no_thread = True              # the ring is sampled by hand here

LIV, BED, GARDEN = 'r1', 'r2', 'r3'
BULB, RELAY, T1, T2, TOUT, DOOR, WIN, TRV = ('0x00158d0004000001', '0x00158d0004000002', '0x00158d0004000003',
                                             '0x00158d0004000004', '0x00158d0004000005', '0x00158d0004000006',
                                             '0x00158d0004000007', '0x00158d0004000008')


def report(name, payload):
    d.handle_zigbee(name, json.dumps(payload).encode())


PLUGS = (('Lampa', 'light', False, 10.0, 1000.0), ('Lampa2', 'light', True, 20.0, 2000.0),
         ('Zasuvka', 'plug', True, 35.2, 3000.0), ('TV', 'plug', True, 50.0, 4500.0))
d.store.set_meta('managed', json.dumps({'plugs': [
    {'name': n, 'host': '127.0.0.1:%d' % (i + 1), 'switch_id': 0, 'kind': 'plug', 'role': role, 'host_state': 'enabled'}
    for i, (n, role, _, _, _) in enumerate(PLUGS)], 'sensors': []}))
d.reload_devices()
for n, role, on, w, wh in PLUGS:
    p = d.plugs[n]
    p.flat = {'switch.output': on, 'switch.apower': w, 'switch.aenergy.total': wh}
    p.output = 1 if on else 0
    p.error = None
    d.live['plug:' + n] = {'payload': {'switch.output': on, 'switch.apower': w, 'switch.aenergy.total': wh},
                           'ts': time.time()}
d._energy_summary = (time.time(), {'plugs': [{'name': 'Lampa', 'today_wh': 200}, {'name': 'Lampa2', 'today_wh': 300},
                                             {'name': 'Zasuvka', 'today_wh': 1000}, {'name': 'TV', 'today_wh': 500}]})
for ident, name, exposes in (
        (BULB, 'Zarovka', {'state': {'access': 7, 'type': 'binary'},
                           'brightness': {'access': 7, 'type': 'numeric', 'min': 0, 'max': 254}}),
        (RELAY, 'Rele', {'state': {'access': 7, 'type': 'binary'}}),
        (T1, 'Teplomer obyvak', {'temperature': {'access': 1, 'type': 'numeric', 'unit': '°C'},
                                 'humidity': {'access': 1, 'type': 'numeric', 'unit': '%'}}),
        (T2, 'Teplomer loznice', {'temperature': {'access': 1, 'type': 'numeric', 'unit': '°C'},
                                  'humidity': {'access': 1, 'type': 'numeric', 'unit': '%'},
                                  'co2': {'access': 1, 'type': 'numeric', 'unit': 'ppm'}}),
        (TOUT, 'Teplomer zahrada', {'temperature': {'access': 1, 'type': 'numeric', 'unit': '°C'},
                                    'illuminance_lux': {'access': 1, 'type': 'numeric', 'unit': 'lx'}}),
        (DOOR, 'Dvere', {'contact': {'access': 1, 'type': 'binary'}}),
        (WIN, 'Okno', {'contact': {'access': 1, 'type': 'binary'}}),
        (TRV, 'Hlavice', {'local_temperature': {'access': 1, 'type': 'numeric', 'unit': '°C'},
                          'current_heating_setpoint': {'access': 7, 'type': 'numeric', 'unit': '°C'}})):
    d.store.upsert_device({'id': ident, 'name': name, 'source': 'zigbee', 'kind': 'EndDevice', 'exposes': exposes})
    d.names[name] = ident
report('Zarovka', {'state': 'ON', 'brightness': 120, 'linkquality': 120})
report('Rele', {'state': 'OFF', 'linkquality': 60})
report('Teplomer obyvak', {'temperature': 21.0, 'humidity': 40, 'battery': 15})
report('Teplomer loznice', {'temperature': 18.0, 'humidity': 60, 'battery': 90, 'co2': 800})
report('Teplomer zahrada', {'temperature': 5.0, 'battery': 50, 'illuminance_lux': 300})
report('Dvere', {'contact': False, 'battery': 5})
report('Okno', {'contact': True, 'battery': 70})
report('Hlavice', {'local_temperature': 19.0, 'current_heating_setpoint': 20, 'battery': 80})
d.set_availability(TRV, 'online', 'Hlavice')
d.set_availability(TRV, 'offline', 'Hlavice')
d.store.upsert_device({'id': 'weather:outside', 'name': 'Outside', 'source': 'weather', 'kind': 'weather',
                       'last_seen': int(time.time())})
d.live['weather:outside'] = {'payload': {'temperature': 2.0, 'humidity': 90, 'pressure': 1013.0}, 'ts': time.time()}
d.store.set_meta('rooms', json.dumps([{'id': LIV, 'name': 'Obývák'}, {'id': BED, 'name': 'Ložnice'},
                                      {'id': GARDEN, 'name': 'Zahrada'}]))
d.store.set_meta('room_of', json.dumps({'Lampa': LIV, 'Lampa2': LIV, 'TV': LIV, BULB: LIV, T1: LIV, DOOR: LIV,
                                        'Zasuvka': BED, RELAY: BED, T2: BED, WIN: BED, TRV: BED, TOUT: GARDEN}))

INSTALL = 'c1b2c3d4e5f60718293a4b5c6d7e8f90'
XL = {'id': 'C0FFEE00XL0C', 'type': 2, 'name': 'Stream Deck XL', 'cols': 8, 'rows': 4, 'approved': True}
TOKEN = 'zsd_' + 'C' * 40


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


def catalog(extended=True, **over):
    d._deck_items_kept = None
    return {it['id']: it for it in d.deck_catalog(inst(**over), extended)['items']}


def calc_of(cat):
    return {k: v for k, v in cat.items() if k.startswith('calc:')}


def val(cat, iid):
    it = cat.get(iid)
    check(it is not None, '%s is not in the catalogue' % iid)
    return (it or {}).get('state', {}).get('value')


try:
    print('extended only')
    old = catalog(False)
    check(not calc_of(old), 'computed values in an older catalogue: %r' % sorted(calc_of(old))[:5])
    st = d.deck_state(inst(), [], None)
    check(not any(k.startswith('calc:') for k in st['items']), 'computed values in an older state')
    st = d.deck_state(inst(), ['calc:sum:power:all'], None)
    check(list(st['items']) == ['calc:sum:power:all'], 'a computed value asked by name: %r' % list(st['items']))
    check('calc' in d.deck_hello(inst())['features'], 'hello does not name calc')

    cat = catalog()
    calc = calc_of(cat)
    print('  %d computed values' % len(calc))
    one = cat['calc:sum:power:all']
    check(one['kind'] == 'calc' and one['cap'] == 'view' and one['actions'] == [] and one['icon'] == 'bolt'
          and one['room'] is None and one['name'] == 'Power · all', 'the item: %r' % one)
    check(one['calc'] == {'fn': 'sum', 'metric': 'power', 'scope': 'all', 'members': 4, 'unit': 'W'},
          'its calc: %r' % one.get('calc'))
    check(one['attrs'] == [{'key': 'value', 'label': 'Power', 'type': 'number', 'unit': 'W', 'min': 0, 'max': None}],
          'its attrs: %r' % one['attrs'])
    s = one['state']
    check(s['value'] == 115.2 and s['value_text'] == '115.2 W' and s['online'] is True and s['on'] is None
          and s['attrs'] == {'value': 115.2, 'members': 4, 'known': 4, 'min_of': None, 'max_of': None},
          'its state: %r' % s)
    check(s['value'] == d.power_now()['total'] == cat['house:power']['state']['value'],
          'not the dashboard total: %r %r' % (s['value'], d.power_now()))

    print('power and energy')
    for iid, want in (('calc:sum:power:kind=light', 30.0), ('calc:sum:power:kind=socket', 85.2),
                      ('calc:sum:power:room=r1', 80.0), ('calc:sum:power:room=r1,kind=light', 30.0),
                      ('calc:sum:power:room=r1,kind=socket', 50.0), ('calc:sum:power:room=r2', 35.2),
                      ('calc:avg:power:all', 28.8), ('calc:max:power:all', 50.0), ('calc:min:power:all', 10.0),
                      ('calc:count:power:all', 4), ('calc:sum:energy_today:all', 2.0),
                      ('calc:sum:energy_today:kind=light', 0.5), ('calc:max:energy_today:all', 1.0),
                      ('calc:avg:energy_today:all', 0.5), ('calc:min:energy_today:kind=socket', 0.5),
                      ('calc:sum:energy_total:all', 10.5), ('calc:max:energy_total:kind=light', 2.0)):
        check(val(cat, iid) == want, '%s is %r, not %r' % (iid, val(cat, iid), want))
    check(cat['calc:max:power:all']['state']['attrs']['max_of'] == 'TV'
          and cat['calc:min:power:all']['state']['attrs']['min_of'] == 'Lampa', 'min_of / max_of of the power')
    check(cat['calc:sum:power:room=r1,kind=light']['name'] == 'Power · lights in Obývák'
          and cat['calc:sum:power:kind=light']['name'] == 'Power · lights'
          and cat['calc:sum:power:room=r1']['name'] == 'Power · Obývák'
          and cat['calc:sum:power:room=r1']['room'] == 'Obývák', 'the names of the power')
    check('calc:sum:power:room=r2,kind=socket' not in cat, 'a kind that is the whole room, again')
    check(cat['calc:sum:energy_today:all']['attrs'][0]['unit'] == 'kWh', 'kWh')

    print('what switches')
    # Lampa off, Lampa2 on, TV on, the bulb on (Obývák); Zasuvka on, the relay off (Ložnice)
    for iid, want in (('calc:on:state:all', 4), ('calc:off:state:all', 2), ('calc:pct_on:state:all', 67),
                      ('calc:count:state:all', 6), ('calc:on:state:kind=light', 2), ('calc:off:state:kind=light', 1),
                      ('calc:on:state:room=r1,kind=light', 2), ('calc:on:state:room=r1', 3),
                      ('calc:on:state:kind=switch', 0), ('calc:on:state:room=r2', 1),
                      ('calc:pct_on:state:kind=socket', 100)):
        check(val(cat, iid) == want, '%s is %r, not %r' % (iid, val(cat, iid), want))
    lo = cat['calc:on:state:room=r1,kind=light']
    check(lo['name'] == 'Lights on · Obývák' and lo['attrs'][0]['min'] == 0 and lo['attrs'][0]['max'] == 3
          and lo['attrs'][0]['unit'] is None and lo['state']['value_text'] == '2', 'Lights on · Obývák: %r' % lo)
    check(cat['calc:pct_on:state:all']['attrs'][0]['unit'] == '%' and cat['calc:pct_on:state:all']['attrs'][0]['max'] == 100,
          'the % of them on')
    check(cat['calc:on:state:kind=light']['name'] == 'Lights on · all'
          and cat['calc:on:state:all']['name'] == 'Things on · all', 'the names of what is on')

    print('the readings, inside and outside')
    # thermometers: Obývák 21, Ložnice 18, the garden 5, the weather 2; the head is offline (19, not known)
    for iid, want in (('calc:avg:temperature:all', 11.5), ('calc:avg:temperature:inside', 19.5),
                      ('calc:avg:temperature:outside', 3.5), ('calc:min:temperature:inside', 18.0),
                      ('calc:max:temperature:inside', 21.0), ('calc:spread:temperature:inside', 3.0),
                      ('calc:min:temperature:outside', 2.0), ('calc:count:temperature:all', 5),
                      ('calc:avg:temperature:room=r2', 18.0), ('calc:avg:humidity:inside', 50.0),
                      ('calc:avg:humidity:outside', 90.0), ('calc:avg:pressure:outside', 1013.0),
                      ('calc:avg:co2:inside', 800), ('calc:avg:illuminance:outside', 300),
                      ('calc:avg:linkquality:all', 90), ('calc:min:linkquality:all', 60)):
        check(val(cat, iid) == want, '%s is %r, not %r' % (iid, val(cat, iid), want))
    ins = cat['calc:avg:temperature:inside']
    check(ins['name'] == 'Average temperature · inside' and ins['icon'] == 'thermo'
          and ins['state']['attrs']['members'] == 3 and ins['state']['attrs']['known'] == 2
          and ins['state']['value_text'] == '19.5 °C', 'inside: %r' % ins)
    check(cat['calc:min:temperature:outside']['state']['attrs']['min_of'] == 'Outside'
          and cat['calc:min:temperature:inside']['state']['attrs']['min_of'] == 'Teplomer loznice'
          and cat['calc:spread:temperature:inside']['state']['attrs']['min_of'] == 'Teplomer loznice'
          and cat['calc:spread:temperature:inside']['state']['attrs']['max_of'] == 'Teplomer obyvak',
          'min_of / max_of of the temperature')
    th = cat.get('calc:avg:temperature:kind=thermostat') or {}
    check(th.get('state', {}).get('online') is False and th['state']['value'] is None
          and th['state']['attrs']['known'] == 0 and th['state']['attrs']['members'] == 1,
          'none known is offline: %r' % th)
    check(cat['calc:avg:humidity:all']['attrs'][0]['min'] == 0 and cat['calc:avg:humidity:all']['attrs'][0]['max'] == 100,
          'the humidity scale')
    check(cat['calc:avg:linkquality:all']['attrs'][0]['max'] == 255, 'the signal scale')
    rooms_t = {r: cat['room:' + r]['state']['value'] for r in (LIV, BED)}
    cold = cat['calc:min:room_temperature:inside']
    check(cold['name'] == 'Coldest room' and cold['state']['value'] == min(rooms_t.values()) == 18.0
          and cold['state']['attrs']['min_of'] == 'Ložnice', 'the coldest room: %r %r' % (cold, rooms_t))
    warm = cat['calc:max:room_temperature:inside']
    check(warm['name'] == 'Warmest room' and warm['state']['value'] == 21.0
          and warm['state']['attrs']['max_of'] == 'Obývák', 'the warmest room: %r' % warm)
    check(cat['calc:avg:room_temperature:inside']['state']['attrs']['members'] == 2, 'the garden is a room inside')

    print('contacts, batteries, devices')
    for iid, want in (('calc:on:open:all', 1), ('calc:count:open:all', 2), ('calc:on:open:room=r1', 1),
                      ('calc:on:open:room=r2', 0), ('calc:on:open:inside', 1),
                      ('calc:min:battery:all', 5), ('calc:avg:battery:all', 52), ('calc:count:battery:all', 6),
                      ('calc:on:battery_low:all', 2), ('calc:pct_on:battery_low:all', 33),
                      ('calc:off:online:kind=thermostat', 1), ('calc:on:online:kind=thermostat', 0)):
        check(val(cat, iid) == want, '%s is %r, not %r' % (iid, val(cat, iid), want))
    check(cat['calc:on:open:all']['name'] == 'Windows open · all', 'Windows open')
    check(cat['calc:on:battery_low:all']['name'] == 'Low batteries · all', 'Low batteries')
    check(cat['calc:min:battery:all']['state']['attrs']['min_of'] == 'Dvere', 'the flattest')
    off = cat['calc:off:online:all']
    zb_off = sum(1 for dv in d.store.devices() if dv.get('source') in ('zigbee', 'plug')
                 and not d.describe(dv, d.live.get(dv['id'])).get('online'))
    check(off['name'] == 'Devices offline · all' and off['state']['value'] == zb_off >= 1,
          'Devices offline: %r (%d)' % (off['state'], zb_off))
    check(cat['calc:off:online:kind=thermostat']['name'] == 'Thermostats offline · all', 'Thermostats offline')
    check('calc:off:online:outside' not in cat and 'calc:avg:battery:outside' not in cat, 'the weather as a device')

    print('no nonsense')
    allowed = {m: set(spec[2]) for m, spec in zigmon.Daemon.DECK_CALC_METRICS.items()}
    for iid, it in calc.items():
        fn, metric, scope = iid.split(':', 3)[1:]
        check(fn in allowed.get(metric, ()), 'a fn %s of %s: %s' % (fn, metric, iid))
        check(it['calc'] == dict(it['calc'], fn=fn, metric=metric, scope=scope), 'calc of %s: %r' % (iid, it['calc']))
        check(it['state']['attrs']['members'] >= 1, 'no members: %s' % iid)
        if fn in ('min', 'max', 'spread'):
            check(it['state']['attrs']['members'] >= 2, 'the extremes of one: %s' % iid)
        check(it['name'] and '·' in it['name'] or metric == 'room_temperature', 'a name: %r' % it['name'])
    for nonsense in ('calc:sum:temperature:all', 'calc:on:power:all', 'calc:sum:humidity:all', 'calc:avg:state:all',
                     'calc:sum:battery:all', 'calc:on:temperature:all', 'calc:min:temperature:kind=thermostat',
                     'calc:sum:power:kind=switch', 'calc:sum:power:outside', 'calc:avg:temperature:room=r3,kind=sensor'):
        check(nonsense not in cat, 'nonsense in the catalogue: %s' % nonsense)
    check(len(set(it['name'] for it in calc.values())) == len(calc),
          'two computed values with one name: %r' % sorted(
              n for n in [it['name'] for it in calc.values()] if [i['name'] for i in calc.values()].count(n) > 1)[:4])

    print('ids with a comma of their own')
    got = d._deck_ids('house:power,calc:sum:power:room=r1,kind=light,calc:on:state:all,Lampa')
    check(got == ['house:power', 'calc:sum:power:room=r1,kind=light', 'calc:on:state:all', 'Lampa'], 'the ids: %r' % got)
    st = d.deck_state(inst(), got, None, True)
    check(st['items'].get('calc:sum:power:room=r1,kind=light', {}).get('value') == 30.0, 'asked through ids: %r'
          % list(st['items']))

    print('permissions')
    check(calc_of(catalog(view={'on': True, 'all': True})).keys() == calc.keys(), 'every thing sees every one')
    some = catalog(view={'on': True, 'all': False, 'targets': ['calc:on:state:room=r1,kind=light', 'Lampa']})
    check(sorted(calc_of(some)) == ['calc:on:state:room=r1,kind=light'], 'only these: %r' % sorted(calc_of(some)))
    check(some['calc:on:state:room=r1,kind=light']['state']['value'] == 2
          and some['calc:on:state:room=r1,kind=light']['allowed'] is True,
          'the total over all its members, though the deck sees Lampa alone')
    check(not calc_of(catalog(view={'on': False})), 'view off sees computed values')
    st = d.deck_state(inst(view={'on': True, 'all': False, 'targets': ['Lampa']}), ['calc:sum:power:all'], None, True)
    check(st['items'] == {}, 'a computed value not granted, asked by name: %r' % st['items'])
    d._deck_setup()
    d._deck_rates.clear()
    code, out = d.deck_do(inst(view={'on': True, 'all': True}),
                          {'deck': XL['id'], 'id': 'calc:sum:power:all', 'action': 'toggle'})
    check(code == 403, 'a computed value acted on: %s %r' % (code, out))
    try:
        got = d._deck_clean_caps({'view': {'on': True, 'all': False, 'targets': ['calc:sum:power:room=r1,kind=light']}})
        check(got['view']['targets'] == ['calc:sum:power:room=r1,kind=light'], 'the admin grant: %r' % got['view'])
    except ValueError as e:
        check(False, 'the admin may not grant a computed value: %s' % e)
    try:
        d._deck_clean_caps({'switch': {'on': True, 'all': False, 'targets': ['calc:sum:power:all']}})
        check(False, 'a computed value granted under switch')
    except ValueError:
        pass
    adm = {it['id']: it for it in d.deck_admin_view()['items']}
    check(adm.get('calc:sum:power:all', {}).get('kind') == 'calc' and adm['calc:sum:power:all']['cap'] == 'view',
          'the admin list: %r' % adm.get('calc:sum:power:all'))

    print('history')
    minute = int(time.time() // 60)
    d._power_minutes[:] = [[minute - 70, 1.0], [minute - 30, 40.0], [minute - 1, 50.5]]
    h = d.deck_state(inst(), ['calc:sum:power:all', 'house:power'], {'span': 3600, 'points': 48}, True)['history']
    check(h['calc:sum:power:all'] == h['house:power'] == {'span': 3600, 'points': [[(minute - 30) * 60, 40.0],
                                                                                   [(minute - 1) * 60, 50.5]]},
          'the house power history: %r' % h)
    hour = int(time.time() // 3600) * 3600
    with d.store.lock:
        for k in range(1, 5):
            d.store.db.execute('INSERT OR REPLACE INTO samples (ts, device, key, value) VALUES (?, ?, ?, ?)',
                               (hour - k * 3600 + 60, 'plug:Lampa', 'switch.apower', 7.0 * k))
            d.store.db.execute('INSERT OR REPLACE INTO samples (ts, device, key, value) VALUES (?, ?, ?, ?)',
                               (hour - k * 3600 + 60, 'plug:TV', 'switch.apower', 100.0))
    h = d.deck_state(inst(), ['calc:sum:power:kind=light', 'calc:sum:power:kind=socket'],
                     {'span': 86400, 'points': 48}, True)['history']
    lights = h.get('calc:sum:power:kind=light', {}).get('points')
    check(lights == [[hour - k * 3600, 7.0 * k] for k in (4, 3, 2, 1)], 'the lights from the samples: %r' % lights)
    check([p[1] for p in h['calc:sum:power:kind=socket']['points']] == [100.0] * 4, 'the sockets: %r' % h)

    check('calc:sum:power:kind=light' in d._deck_calc_watch and 'house:power' not in d._deck_calc_watch,
          'a state that named it did not watch it: %r' % sorted(d._deck_calc_watch))
    iid = 'calc:avg:temperature:inside'
    d._deck_calc_rings.clear()
    t0 = (int(time.time() // 3600) - 2) * 3600
    d.deck_calc_watch([iid])
    for k in range(120):
        d.deck_calc_sample(now=t0 + k * 60, items=[{'id': iid, 'state': {'value': 20.0 + k / 10.0}}])
    pts = d._deck_calc_ring_history(iid, 3600, 48, now=t0 + 119 * 60 + 30)
    check(len(pts) <= 48 and len(pts) >= 40 and pts[-1][1] == 31.9 and pts[0][0] >= t0 + 59 * 60,
          'the ring, an hour: %d %r' % (len(pts), pts[-3:]))
    pts6 = d._deck_calc_ring_history(iid, 6 * 3600, 48, now=t0 + 119 * 60 + 30)
    check(t0 <= pts6[0][0] <= t0 + 300 and len(pts6) <= 48 and pts6[-1] == [t0 + 119 * 60, 31.9], 'the ring, six hours: %r' % pts6[:2])
    pts24 = d._deck_calc_ring_history(iid, 86400, 48, now=t0 + 119 * 60 + 30)
    check(len(pts24) == 4 and pts24[0] == [t0, round(sum(20.0 + k / 10.0 for k in range(30)) / 30, 3)],
          'the ring, by the half hour: %r' % pts24)
    d._deck_calc_watch[iid] = t0 + 119 * 60
    real = d.deck_calc_sample
    d.deck_calc_sample = lambda now=None, items=None: real(now=t0 + 119 * 60 + 30, items=items)
    hist = d.deck_history([cat[iid]], [iid], 3600, 48)
    d.deck_calc_sample = real
    check(hist.get(iid, {}).get('span') == 3600 and len(hist[iid]['points']) >= 1, 'served by deck_history: %r' % hist)
    for k in range(305):
        d.deck_calc_watch(['calc:x:%d' % k], now=t0 + 119 * 60 + k)
    check(len(d._deck_calc_watch) == 300 and 'calc:x:304' in d._deck_calc_watch and iid not in d._deck_calc_watch,
          'the watch cap: %d' % len(d._deck_calc_watch))
    check(iid not in d._deck_calc_rings, 'a ring kept for an item no longer watched')
    check(d.deck_calc_sample(now=t0 + 119 * 60 + 8 * 86400, items=[]) is False and not d._deck_calc_watch,
          'a watch outlived 7 days')

    print('the cap and the order')
    rows = [{'id': LIV, 'name': 'Obývák'}, {'id': BED, 'name': 'Ložnice'}, {'id': GARDEN, 'name': 'Zahrada'}]
    room_of = json.loads(d.store.get_meta('room_of'))
    for k in range(50):
        rid = 'x%02d' % k
        rows.append({'id': rid, 'name': 'Room %02d' % k})
        ident = '0x00158d00050000%02x' % k
        name = 'Sensor %02d' % k
        d.store.upsert_device({'id': ident, 'name': name, 'source': 'zigbee', 'kind': 'EndDevice', 'exposes': {
            'temperature': {'access': 1, 'type': 'numeric'}, 'humidity': {'access': 1, 'type': 'numeric'},
            'state': {'access': 7, 'type': 'binary'}}})
        d.names[name] = ident
        report(name, {'temperature': 20 + k / 10.0, 'humidity': 50, 'battery': 60, 'linkquality': 100, 'state': 'ON'})
        room_of[ident] = rid
    d.store.set_meta('rooms', json.dumps(rows))
    d.store.set_meta('room_of', json.dumps(room_of))
    d._deck_items_kept = None
    items = d.deck_items(fresh=True)
    ids = [it['id'] for it in items if it['id'].startswith('calc:')]
    check(len(ids) == 600, 'the cap: %d' % len(ids))
    scopes = [i.split(':', 3)[3] for i in ids]
    first_kind = next(n for n, s in enumerate(scopes) if s.startswith('kind='))
    first_room = next(n for n, s in enumerate(scopes) if s.startswith('room='))
    check(all(s in ('all', 'inside', 'outside') for s in scopes[:first_kind])
          and all(not s.startswith('room=') for s in scopes[:first_room]) and first_kind < first_room,
          'not the house first, then the kinds, then the rooms')
    check(scopes[0] == 'all' and ids[0] == 'calc:sum:power:all', 'the first: %s' % ids[0])
    check('calc:avg:temperature:inside' in ids and 'calc:min:room_temperature:inside' in ids, 'inside lost to the cap')

    print('speed')
    devs = len([x for x in d.store.devices()])
    t = time.perf_counter()
    for _ in range(10):
        d.deck_items(fresh=True)
    each = (time.perf_counter() - t) / 10
    t = time.perf_counter()
    for _ in range(10):
        d._deck_calc_items(items, d._ntf_rooms())
    calc_each = (time.perf_counter() - t) / 10
    print('  %d devices: deck_items %.1f ms a pass, of it the computed values %.1f ms' % (devs, each * 1000,
                                                                                         calc_each * 1000))
    check(devs >= 60 and calc_each < 0.1 and each < 0.4, 'too slow: %.3f s (computed %.3f s)' % (each, calc_each))
    d._deck_setup()
    t = time.perf_counter()
    for _ in range(5):
        d._deck_refresh(force=True)          # the states compared for the long poll, 600 more of them
    refresh = (time.perf_counter() - t) / 5
    print('  a refresh of the states: %.1f ms' % (refresh * 1000))
    check(refresh < 0.5, 'the refresh too slow: %.3f s' % refresh)
    check(not [x for x in LOG if x.startswith('warn the Stream Deck catalogue')], 'a part failed: %r'
          % [x for x in LOG if x.startswith('warn the Stream Deck')][:3])
finally:
    try:
        d._stop.set()
    except Exception:                                           # noqa: BLE001
        pass

print('%d FAILED' % len(bad) if bad else 'all good')
sys.exit(1 if bad else 0)
