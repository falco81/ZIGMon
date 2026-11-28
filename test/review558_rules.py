#!/usr/bin/env python3
"""Settings - Messages - Desktop app (5.58): conditions ("rules") on any sensor for a notifier key.

  * an administrator gives a key conditions on any device's attribute (not the texts, groups,
    the server in front): temperature >= 25, a preset changed, a socket's power, a state...;
    every bad operator, value, attribute, device, label, hysteresis and the 51st is 400 in words;
  * every family of operators (numbers, between/outside, text, enum, on/off, changed);
  * an alert when a condition BECOMES true and when it clears; a hysteresis that keeps it from
    flapping; `changed` on every new value (not the first ever, not the same again); a
    retained replay is nothing;
  * a restart (a second daemon on the same database) seeds the truth from what was known:
    a condition already true does not fire again; one becoming true does;
  * a condition's event is its owner key's only (an "every sensor" key does not see it);
  * the 1.1.0 fields of the ordinary sensors and events are as they were; hello says how many
    conditions; sensors lists them (kind "rule") with the condition and the value now; wait
    carries what/value/value_text/rule_text;
  * GET /api/notifier/attrs (admin, ALWAYS_LOCKED): types, enum values, units, ranges, values;
  * rule_add / rule_update / rule_delete and the events' words (no secret anywhere); taking a
    key away takes its conditions; an operator and nobody get 403;
  * the relay: index.php?api=notifier-attrs, signed in and signed out;
  * the page in Chromium (Playwright), when there is one: a condition added in the editor,
    listed on the key's card, desktop and 390 px. Screenshots into $ZIGMON_SHOTS (or a kept
    temporary folder).

    python3 test/review558_rules.py < /dev/null

Ports 20190-20199. Every secret here is made up.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-rules-'))
API_PORT, PHP_PORT = 20190, 20191
SHOTS = Path(os.environ.get('ZIGMON_SHOTS') or tempfile.mkdtemp(prefix='zigmon-rules-shots-'))
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
if not hasattr(d, 'notifier_rules_heard'):
    print('FAILED: there are no conditions on any sensor here (notifier_rules_heard is missing)')
    sys.exit(1)
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def call(path, body=None, session=None, key=None, client='192.168.41.10', timeout=60, raw=None):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': client}
    if session:
        headers['X-Zigmon-Session'] = session
    if key is not None:
        headers['X-Zigmon-Notifier'] = key
    if body is not None and session:
        body = dict(body, session=session)
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers, data=data,
                                 method='GET' if data is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def report(name, payload, dm=None):
    (dm or d).handle_zigbee(name, json.dumps(payload).encode())


def events_since(seq, dm=None):
    return [e for e in list((dm or d)._ntf_ring) if e[0] > seq]


try:
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
    S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
    SO = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''
    check(S and SO, 'could not sign in')

    # ---- the house: a thermometer, a radiator head, a door, a socket, a text gateway --------
    THERMO, TRV, DOOR, SMS = '0x00158d0002a1b2c1', '0x00158d0002a1b2c2', '0x00158d0002a1b2c3', 'sms:modem'
    for ident, name, exposes in (
            (THERMO, 'Obyvak-Teplomer', {'temperature': {'label': 'Temperature', 'unit': '°C', 'type': 'numeric'},
                                         'humidity': {'label': 'Humidity', 'unit': '%', 'type': 'numeric',
                                                      'min': 0, 'max': 100},
                                         'battery': {'label': 'Battery', 'unit': '%', 'type': 'numeric'}}),
            (TRV, 'Hlavice-Loznice', {'preset': {'label': 'Preset', 'type': 'enum',
                                                 'values': ['eco', 'comfort', 'boost', 'away']},
                                      'system_mode': {'label': 'System mode', 'type': 'enum',
                                                      'values': ['off', 'heat', 'auto']},
                                      'child_lock': {'label': 'Child lock', 'type': 'binary'},
                                      'current_heating_setpoint': {'label': 'Setpoint', 'unit': '°C',
                                                                   'type': 'numeric', 'min': 5, 'max': 30},
                                      'identify': {'label': 'Identify', 'type': 'enum', 'access': 2,
                                                   'values': ['identify']},
                                      'battery': {'label': 'Battery', 'unit': '%', 'type': 'numeric'}}),
            (DOOR, 'Dvere-Vchod', {'contact': {'type': 'binary'}})):
        d.store.upsert_device({'id': ident, 'name': name, 'source': 'zigbee', 'kind': 'EndDevice', 'exposes': exposes})
        d.names[name] = ident
    d.store.upsert_device({'id': SMS, 'name': 'Modem', 'source': 'sms', 'kind': 'Modem'})
    PLUG = zigmon.PlugState('Konvice', {'name': 'Konvice', 'host': '127.0.0.1:20199'})
    d.plugs['Konvice'] = PLUG
    d.store.upsert_device({'id': PLUG.device_id, 'name': 'Konvice', 'source': 'plug', 'kind': 'wifi'})
    PLUG.flat = {'switch.output': False, 'switch.apower': 0.0, 'switch.aenergy.total': 12.5}
    d.live[PLUG.device_id] = {'payload': PLUG.flat, 'ts': int(time.time()), 'availability': 'online'}
    d.store.set_meta('rooms', json.dumps([{'id': 'r1', 'name': 'Living room'}, {'id': 'r2', 'name': 'Bedroom'}]))
    d.store.set_meta('room_of', json.dumps({THERMO: 'r1', TRV: 'r2'}))
    report('Obyvak-Teplomer', {'temperature': 21.5, 'humidity': 40, 'battery': 88, 'linkquality': 90})
    report('Hlavice-Loznice', {'preset': 'comfort', 'system_mode': 'heat', 'child_lock': 'UNLOCK',
                               'current_heating_setpoint': 21, 'battery': 70})
    report('Dvere-Vchod', {'contact': True, 'battery': 64})

    # (5.59.1) the desktop app comes switched off: an administrator switches it on first
    call('/api/notifier/keys', {'action': 'enable'}, session=S)
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'Office PC', 'devices': []}, session=S)
    KEY, KID = out.get('key') or '', out.get('id')
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'Hall tablet', 'devices': []}, session=S)
    KEY2, KID2 = out.get('key') or '', out.get('id')
    check(KEY and KEY2, 'the keys were not made: %r' % out)

    def add(rule, kid=None, session=None):
        return call('/api/notifier/keys', {'action': 'rule_add', 'id': kid or KID, 'rule': rule}, session=session or S)

    print('the management is an administrator\'s')
    check('/api/notifier/attrs' in zigmon.ApiHandler.ALWAYS_LOCKED, '/api/notifier/attrs is not among the locked reads')
    code, out = add({'device': THERMO, 'attr': 'temperature', 'op': 'ge', 'value': 25}, session=SO)
    check(code == 403, 'an operator adds a condition: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', {'action': 'rule_add', 'id': KID,
                                            'rule': {'device': THERMO, 'attr': 'temperature', 'op': 'ge', 'value': 25}})
    check(code == 403, 'nobody adds a condition: %s %r' % (code, out))
    code, out = call('/api/notifier/attrs?device=' + THERMO, session=SO)
    check(code == 403, 'an operator reads the attributes: %s %r' % (code, out))
    code, out = call('/api/notifier/attrs?device=' + THERMO)
    check(code == 403, 'nobody reads the attributes: %s %r' % (code, out))
    code, out = call('/api/notifier/attrs?device=' + THERMO, key=KEY)
    check(code == 403, 'a notifier key reads the attributes: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', session=S)
    devs = {x['id']: x for x in out.get('rule_devices') or []}
    check(THERMO in devs and TRV in devs and PLUG.device_id in devs and DOOR in devs and SMS not in devs,
          'the devices a condition may watch: %r' % sorted(devs))
    check(devs.get(THERMO, {}).get('room') == 'Living room' and devs.get(THERMO, {}).get('kind') == 'thermo'
          and devs.get(TRV, {}).get('kind') == 'valve' and devs.get(PLUG.device_id, {}).get('kind') == 'plug'
          and devs.get(PLUG.device_id, {}).get('source') == 'plug', 'what they are: %r' % devs)
    check(out.get('rules_most') == 50 and all('rules' not in k for k in out.get('keys') or []),
          'a key without conditions: %r' % out.get('keys'))

    print('the attributes of a device')
    code, out = call('/api/notifier/attrs?device=' + THERMO, session=S)
    at = {a['key']: a for a in out.get('attrs') or []}
    check(code == 200 and out.get('ok') and out.get('device', {}).get('name') == 'Obyvak-Teplomer'
          and out['device'].get('room') == 'Living room', 'the attrs: %s %r' % (code, out))
    t = at.get('temperature') or {}
    check(t.get('type') == 'number' and t.get('unit') == '°C' and t.get('value') == 21.5
          and t.get('value_text') == '21.5 °C' and t.get('label') == 'Temperature', 'temperature: %r' % t)
    check((at.get('humidity') or {}).get('min') == 0 and (at.get('humidity') or {}).get('max') == 100
          and (at.get('humidity') or {}).get('unit') == '%', 'humidity: %r' % at.get('humidity'))
    keys = [a['key'] for a in out.get('attrs') or []]
    check(keys and keys[0] == 'temperature' and keys.index('humidity') < keys.index('battery'),
          'the main readings first: %r' % keys)
    check('last_seen' not in keys, 'bookkeeping offered: %r' % keys)
    code, out = call('/api/notifier/attrs?device=' + TRV, session=S)
    at = {a['key']: a for a in out.get('attrs') or []}
    check((at.get('preset') or {}).get('type') == 'enum'
          and (at.get('preset') or {}).get('values') == ['eco', 'comfort', 'boost', 'away']
          and (at.get('preset') or {}).get('value') == 'comfort', 'the preset: %r' % at.get('preset'))
    check((at.get('child_lock') or {}).get('type') == 'bool', 'the child lock: %r' % at.get('child_lock'))
    check((at.get('current_heating_setpoint') or {}).get('min') == 5
          and (at.get('current_heating_setpoint') or {}).get('max') == 30, 'the setpoint: %r'
          % at.get('current_heating_setpoint'))
    check('identify' not in at, 'a write-only attribute offered: %r' % sorted(at))
    code, out = call('/api/notifier/attrs?device=' + PLUG.device_id, session=S)
    at = {a['key']: a for a in out.get('attrs') or []}
    check((at.get('switch.apower') or {}).get('type') == 'number' and (at.get('switch.apower') or {}).get('unit') == 'W'
          and (at.get('switch.output') or {}).get('type') == 'bool'
          and [a['key'] for a in out.get('attrs') or []][0] == 'switch.apower', 'the socket: %r' % out.get('attrs'))
    code, out = call('/api/notifier/attrs?device=' + SMS, session=S)
    check(code == 400, 'the texts are no device for a condition: %s %r' % (code, out))
    code, out = call('/api/notifier/attrs?device=nothing-here', session=S)
    check(code == 400 and out.get('error'), 'an unknown device: %s %r' % (code, out))

    print('a bad condition is refused, in words')
    for rule, what in (
            ({'device': THERMO, 'attr': 'temperature', 'op': 'gte', 'value': 25}, 'an unknown op'),
            ({'device': THERMO, 'attr': 'temperature', 'op': 'ge', 'value': '25'}, 'a number as a text'),
            ({'device': THERMO, 'attr': 'temperature', 'op': 'ge', 'value': True}, 'a bool for a number'),
            ({'device': THERMO, 'attr': 'temperature', 'op': 'ge'}, 'no value'),
            ({'device': THERMO, 'attr': 'temperature', 'op': 'between', 'value': 18}, 'between without its second'),
            ({'device': THERMO, 'attr': 'temperature', 'op': 'between', 'value': 24, 'value2': 18}, 'between upside down'),
            ({'device': THERMO, 'attr': 'temperature', 'op': 'outside', 'value': 18, 'value2': 'x'}, 'outside, a text'),
            ({'device': THERMO, 'attr': 'temp erature', 'op': 'ge', 'value': 25}, 'a space in the attribute'),
            ({'device': THERMO, 'attr': 'a' * 65, 'op': 'ge', 'value': 25}, 'an attribute of 65'),
            ({'device': THERMO, 'attr': '', 'op': 'ge', 'value': 25}, 'no attribute'),
            ({'device': 'nothing-here', 'attr': 'temperature', 'op': 'ge', 'value': 25}, 'an unknown device'),
            ({'device': SMS, 'attr': 'credit', 'op': 'lt', 'value': 50}, 'the texts'),
            ({'device': TRV, 'attr': 'preset', 'op': 'contains', 'value': 5}, 'contains a number'),
            ({'device': TRV, 'attr': 'preset', 'op': 'contains', 'value': '  '}, 'contains nothing'),
            ({'device': TRV, 'attr': 'preset', 'op': 'eq', 'value': 'x' * 101}, 'a text of 101'),
            ({'device': TRV, 'attr': 'preset', 'op': 'eq', 'value': None}, 'eq nothing'),
            ({'device': THERMO, 'attr': 'temperature', 'op': 'eq', 'value': 25, 'hyst': 1}, 'a hysteresis on eq'),
            ({'device': THERMO, 'attr': 'temperature', 'op': 'ge', 'value': 25, 'hyst': -1}, 'a hysteresis below zero'),
            ({'device': THERMO, 'attr': 'temperature', 'op': 'ge', 'value': 25, 'hyst': 'x'}, 'a hysteresis of words'),
            ({'device': THERMO, 'attr': 'temperature', 'op': 'ge', 'value': 25, 'label': 'L' * 61}, 'a label of 61'),
            ('temperature >= 25', 'a rule that is not an object')):
        code, out = add(rule)
        check(code == 400 and out.get('ok') is False and len(out.get('error') or '') > 8, '%s: %s %r' % (what, code, out))
    code, out = call('/api/notifier/keys', raw=('{"action": "rule_add", "id": "%s", "session": "%s", "rule": {"device": '
                                                '"%s", "attr": "temperature", "op": "ge", "value": NaN}}'
                                                % (KID, S, THERMO)).encode(), session=S)
    check(code == 400, 'NaN for a value: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', {'action': 'rule_add', 'id': 'nokey', 'rule': {
        'device': THERMO, 'attr': 'temperature', 'op': 'ge', 'value': 25}}, session=S)
    check(code == 400, 'a condition for no key: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', {'action': 'rule_update', 'id': KID, 'rule_id': 'abcdeabcde',
                                            'rule': {'op': 'gt', 'value': 1}}, session=S)
    check(code == 400 and 'no such condition' in out.get('error', ''), 'an update of nothing: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', {'action': 'rule_delete', 'id': KID, 'rule_id': 'abcdeabcde'}, session=S)
    check(code == 400, 'a delete of nothing: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', session=S)
    check(all('rules' not in k for k in out.get('keys') or []), 'a refused condition was kept: %r' % out.get('keys'))

    print('the operators, one by one')
    T = zigmon.Daemon.notifier_rule_truth
    for rule, x, want in (
            ({'op': 'gt', 'value': 25}, 25, False), ({'op': 'gt', 'value': 25}, 25.1, True),
            ({'op': 'ge', 'value': 25}, 25, True), ({'op': 'lt', 'value': 30}, 29.9, True),
            ({'op': 'le', 'value': 30}, 30.5, False), ({'op': 'eq', 'value': 3}, '3', True),
            ({'op': 'ne', 'value': 3}, 3.0, False), ({'op': 'between', 'value': 18, 'value2': 24}, 24, True),
            ({'op': 'between', 'value': 18, 'value2': 24}, 17.9, False),
            ({'op': 'outside', 'value': 18, 'value2': 24}, 24.1, True),
            ({'op': 'outside', 'value': 18, 'value2': 24}, 18, False),
            ({'op': 'eq', 'value': 'eco'}, ' ECO ', True), ({'op': 'ne', 'value': 'eco'}, 'comfort', True),
            ({'op': 'contains', 'value': 'eco'}, 'Eco-mode', True),
            ({'op': 'not_contains', 'value': 'eco'}, 'Eco-mode', False),
            ({'op': 'is_true'}, 'ON', True), ({'op': 'is_true'}, False, False), ({'op': 'is_false'}, 'off', True),
            ({'op': 'eq', 'value': True}, 'ON', True), ({'op': 'changed'}, 'x', True),
            ({'op': 'gt', 'value': 25}, None, None), ({'op': 'gt', 'value': 25}, 'warm', None),
            ({'op': 'ge', 'value': 25, 'hyst': 0.5}, 24.6, False)):
        check(T(rule, x, None) is want, '%r on %r: %r, not %r' % (rule, x, T(rule, x, None), want))
    check(T({'op': 'ge', 'value': 25, 'hyst': 0.5}, 24.6, True) is True
          and T({'op': 'ge', 'value': 25, 'hyst': 0.5}, 24.4, True) is False
          and T({'op': 'le', 'value': 10, 'hyst': 2}, 11.5, True) is True
          and T({'op': 'le', 'value': 10, 'hyst': 2}, 12.5, True) is False, 'the hysteresis held as true')

    print('conditions on the keys')
    code, out = add({'device': THERMO, 'attr': 'temperature', 'op': 'ge', 'value': 25, 'hyst': 0.5,
                     'label': '  Living room\x07 too warm '})
    R_T = (out.get('rule') or {})
    check(code == 200 and re.match(r'^[0-9a-f]{10}$', R_T.get('id') or '') and R_T.get('text') == 'temperature ≥ 25 °C'
          and R_T.get('unit') == '°C' and R_T.get('label') == 'Living room too warm' and R_T.get('missing') is False
          and R_T.get('active') is False and R_T.get('value_text') == '21.5 °C' and R_T.get('device_name') == 'Obyvak-Teplomer'
          and R_T.get('room') == 'Living room' and R_T.get('hyst') == 0.5, 'the temperature rule: %s %r' % (code, out))
    listed = [k for k in out.get('keys') or [] if k['id'] == KID][0]
    check([r['id'] for r in listed.get('rules') or []] == [R_T.get('id')], 'the key lists it: %r' % listed)
    code, out = add({'device': TRV, 'attr': 'preset', 'op': 'changed', 'value': 'ignored', 'value2': 3})
    R_P = out.get('rule') or {}
    check(code == 200 and R_P.get('text') == 'preset changes' and R_P.get('value') is None and R_P.get('value2') is None,
          'the preset rule: %s %r' % (code, out))
    code, out = add({'device': TRV, 'attr': 'system_mode', 'op': 'eq', 'value': 'off'})
    R_M = out.get('rule') or {}
    check(code == 200 and R_M.get('text') == 'system mode = off' and R_M.get('active') is False,
          'the mode rule: %s %r' % (code, out))
    code, out = add({'device': PLUG.device_id, 'attr': 'switch.apower', 'op': 'gt', 'value': 2000})
    R_W = out.get('rule') or {}
    check(code == 200 and R_W.get('text') == 'power > 2000 W', 'the socket rule: %s %r' % (code, out))
    code, out = add({'device': THERMO, 'attr': 'humidity', 'op': 'outside', 'value': 30, 'value2': 60})
    R_H = out.get('rule') or {}
    check(code == 200 and R_H.get('text') == 'humidity outside 30–60 %', 'the humidity rule: %s %r' % (code, out))
    code, out = add({'device': TRV, 'attr': 'child_lock', 'op': 'is_true'})
    R_L = out.get('rule') or {}
    check(code == 200 and R_L.get('text') == 'child lock is on' and R_L.get('active') is False,
          'the bool rule: %s %r' % (code, out))
    code, out = add({'device': THERMO, 'attr': 'battery', 'op': 'between', 'value': 0, 'value2': 15}, kid=KID2)
    R_B = out.get('rule') or {}
    check(code == 200 and R_B.get('text') == 'battery between 0 and 15 %', 'the second key\'s rule: %s %r' % (code, out))
    with d.store.lock:
        ev = [r[0] for r in d.store.db.execute('SELECT detail FROM events').fetchall()]
    check(any("owner added the desktop alert condition 'Obyvak-Teplomer: temperature ≥ 25 °C' to key 'Office PC'" in e
              for e in ev), 'the event of adding it: %r' % ev[-4:])

    print('hello, sensors: additive')
    code, out = call('/api/notifier/hello', key=KEY)
    check(code == 200 and out['key'].get('rules') == 6 and out['key'].get('devices') == 1, 'hello: %r' % out.get('key'))
    BOOT = out.get('boot')
    code, out = call('/api/notifier/hello', key=KEY2)
    check(out['key'].get('rules') == 1, 'hello of the second: %r' % out.get('key'))
    code, out = call('/api/notifier/sensors', key=KEY)
    ss = out.get('sensors') or []
    plain = [s for s in ss if s.get('kind') != 'rule']
    rules = [s for s in ss if s.get('kind') == 'rule']
    check([s['id'] for s in plain] == [DOOR] and set(plain[0]) == {'id', 'name', 'room', 'kind', 'active', 'at', 'battery',
                                                                   'online'}, 'the ordinary sensor: %r' % plain)
    check(ss.index(plain[0]) == 0 and len(rules) == 6, 'the rules after the sensors: %r' % [s['id'] for s in ss])
    names = [s['name'] for s in rules]
    check(names == sorted(names, key=str.lower), 'the rules are not sorted by name: %r' % names)
    rt = [s for s in rules if s['id'] == 'rule:' + R_T['id']][0]
    check(rt == {'id': 'rule:' + R_T['id'], 'name': 'Living room too warm', 'room': 'Living room', 'kind': 'rule',
                 'active': False, 'at': None, 'battery': 88, 'online': True, 'device': THERMO,
                 'device_name': 'Obyvak-Teplomer',
                 'rule': {'attr': 'temperature', 'op': 'ge', 'value': 25, 'value2': None, 'hyst': 0.5, 'unit': '°C',
                          'text': 'temperature ≥ 25 °C'},
                 'value': 21.5, 'value_text': '21.5 °C'}, 'the rule as a sensor: %r' % rt)
    rp = [s for s in rules if s['id'] == 'rule:' + R_P['id']][0]
    check(rp['name'] == 'Hlavice-Loznice' and rp['active'] is True and rp['value_text'] == 'comfort'
          and rp['rule']['text'] == 'preset changes', 'the changed rule as a sensor: %r' % rp)
    code, out = call('/api/notifier/sensors', key=KEY2)
    check([s['id'] for s in out.get('sensors') or [] if s['kind'] == 'rule'] == ['rule:' + R_B['id']],
          'the second key sees its own rule only: %r' % out.get('sensors'))

    print('the edges')
    SEQ = d._ntf_seq
    report('Obyvak-Teplomer', {'temperature': 24.9, 'humidity': 45})
    check(events_since(SEQ) == [], 'nothing met, nothing said: %r' % events_since(SEQ))
    report('Obyvak-Teplomer', {'temperature': 25.3})                  # met
    report('Obyvak-Teplomer', {'temperature': 26.0})                  # still
    report('Obyvak-Teplomer', {'temperature': 24.7})                  # within the hysteresis: still
    report('Obyvak-Teplomer', {'temperature': 24.2})                  # cleared
    report('Obyvak-Teplomer', {'temperature': 24.6})                  # nothing
    report('Hlavice-Loznice', {'preset': 'eco'})                      # a change
    report('Hlavice-Loznice', {'preset': 'eco'})                      # the same: nothing
    report('Hlavice-Loznice', {'preset': 'boost', 'system_mode': 'off'})
    report('Hlavice-Loznice', {'child_lock': 'LOCK'})                  # not "on": nothing
    report('Hlavice-Loznice', {'child_lock': 'ON'})
    report('Obyvak-Teplomer', {'humidity': 72})
    report('Obyvak-Teplomer', {'battery': 12})                         # the second key's
    d._plug_flat_put(PLUG, {'switch.apower': 2400.0, 'switch.output': True})   # the socket's push
    d._plug_flat_put(PLUG, {'switch.apower': 2300.0})
    report('Dvere-Vchod', {'contact': False})                          # an ordinary edge between them
    got = [(e[2], e[5], e[6]) for e in events_since(SEQ)]
    want = [('rule:' + R_T['id'], True, 'temperature 25.3 °C (≥ 25 °C)'),
            ('rule:' + R_T['id'], False, 'back to normal: temperature 24.2 °C'),
            ('rule:' + R_P['id'], True, 'preset: eco (was comfort)'),
            ('rule:' + R_P['id'], True, 'preset: boost (was eco)'),
            ('rule:' + R_M['id'], True, 'system mode off (= off)'),
            ('rule:' + R_L['id'], True, 'child lock ON (is on)'),
            ('rule:' + R_H['id'], True, 'humidity 72 % (outside 30–60 %)'),
            ('rule:' + R_B['id'], True, 'battery 12 % (between 0 and 15 %)'),
            ('rule:' + R_W['id'], True, 'power 2400 W (> 2000 W)'),
            (DOOR, True, 'opened')]
    check(got == want, 'the edges:\n    %r\n  not\n    %r' % (got, want))
    code, out = call('/api/notifier/wait?after=%d&boot=%s' % (SEQ, BOOT), key=KEY)
    ev = out.get('events') or []
    check([e['device'] for e in ev] == [w[0] for w in want if w[0] != 'rule:' + R_B['id']],
          'the owner key\'s wait: %r' % [e['device'] for e in ev])
    e0 = ev[0] if ev else {}
    check(set(e0) == {'seq', 'at', 'device', 'name', 'room', 'kind', 'key', 'active', 'what', 'value', 'value_text',
                      'rule_text'} and e0.get('kind') == 'rule' and e0.get('key') == 'temperature'
          and e0.get('name') == 'Living room too warm' and e0.get('room') == 'Living room' and e0.get('value') == 25.3
          and e0.get('value_text') == '25.3 °C' and e0.get('rule_text') == 'temperature ≥ 25 °C', 'a rule event: %r' % e0)
    door = [e for e in ev if e['device'] == DOOR]
    check(door and set(door[0]) == {'seq', 'at', 'device', 'name', 'room', 'kind', 'key', 'active', 'what'},
          'the ordinary event is as it was: %r' % door)
    check(all(len(e['what']) <= 120 for e in ev), 'a what over 120')
    code, out = call('/api/notifier/wait?after=%d&boot=%s' % (SEQ, BOOT), key=KEY2)
    check([e['device'] for e in out.get('events') or []] == ['rule:' + R_B['id'], DOOR],
          'the other key ("every sensor") sees its rule and the door, nothing of the first key\'s: %r'
          % [e['device'] for e in out.get('events') or []])
    code, out = call('/api/notifier/sensors', key=KEY)
    rt = [s for s in out.get('sensors') or [] if s['id'] == 'rule:' + R_T['id']][0]
    rw = [s for s in out.get('sensors') or [] if s['id'] == 'rule:' + R_W['id']][0]
    check(rt['active'] is False and isinstance(rt['at'], float) and rt['value'] == 24.6, 'the rule after: %r' % rt)
    check(rw['active'] is True and rw['value_text'] == '2300 W' and rw['online'] is True, 'the socket rule: %r' % rw)
    # a retained replay is nothing
    s0 = d._ntf_seq
    d._retained_msg = True
    report('Obyvak-Teplomer', {'temperature': 30})
    d._retained_msg = False
    check(d._ntf_seq == s0, 'a retained replay fired: %r' % events_since(s0))
    report('Obyvak-Teplomer', {'temperature': 31})
    check(d._ntf_seq == s0, 'after a replay that was met, still met is no edge: %r' % events_since(s0))
    report('Obyvak-Teplomer', {'temperature': 22})
    check([e[5] for e in events_since(s0)] == [False], 'cleared after the replay: %r' % events_since(s0))

    print('changed, edited, taken away')
    code, out = call('/api/notifier/keys', {'action': 'rule_update', 'id': KID, 'rule_id': R_T['id'],
                                            'rule': {'op': 'lt', 'value': 18, 'hyst': None, 'label': ''}}, session=S)
    check(code == 200 and out.get('rule', {}).get('id') == R_T['id'] and out['rule'].get('text') == 'temperature < 18 °C'
          and out['rule'].get('device') == THERMO and out['rule'].get('label') == '' and out['rule'].get('hyst') is None,
          'the update: %s %r' % (code, out))
    s0 = d._ntf_seq
    report('Obyvak-Teplomer', {'temperature': 17.5})
    check([(e[2], e[5]) for e in events_since(s0)] == [('rule:' + R_T['id'], True)], 'the updated rule: %r'
          % events_since(s0))
    code, out = call('/api/notifier/keys', {'action': 'rule_update', 'id': KID, 'rule_id': R_T['id'],
                                            'rule': {'op': 'between', 'value': 5}}, session=S)
    check(code == 400, 'an update made bad: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', {'action': 'rule_delete', 'id': KID, 'rule_id': R_H['id']}, session=S)
    check(code == 200 and R_H['id'] not in json.dumps(out.get('keys')), 'the delete: %s %r' % (code, out))
    with d.store.lock:
        ev = [r[0] for r in d.store.db.execute('SELECT detail FROM events').fetchall()]
    check(any("owner changed the desktop alert condition 'Obyvak-Teplomer: temperature < 18 °C' on key 'Office PC'" in e
              for e in ev) and any("owner took away the desktop alert condition 'Obyvak-Teplomer: humidity outside 30–60 %' "
                                   "from key 'Office PC'" in e for e in ev), 'the events: %r' % ev[-4:])
    # the device gone: kept, shown as missing, never fires
    code, out = add({'device': DOOR, 'attr': 'battery', 'op': 'lt', 'value': 10})
    R_D = out.get('rule') or {}
    with d.store.lock:
        d.store.db.execute("DELETE FROM devices WHERE id=?", (DOOR,))
    d.store._dev_cache.pop(DOOR, None) if hasattr(d.store, '_dev_cache') else None
    try:
        d.store._reload_device(DOOR)
    except Exception:                                       # noqa: BLE001
        pass
    if d.store.device(DOOR) is None:
        d._ntf_index = None
        code, out = call('/api/notifier/keys', session=S)
        gone = [r for k in out.get('keys') or [] for r in k.get('rules') or [] if r['id'] == R_D.get('id')]
        check(gone and gone[0]['missing'] is True and gone[0]['active'] is None, 'a rule of a gone device: %r' % gone)
        s0 = d._ntf_seq
        d.notifier_rules_heard(DOOR, {'battery': 64}, {'battery': 5})
        check(d._ntf_seq == s0, 'a rule of a gone device fired')
    else:
        print('  (the device row could not be taken away here - the missing case is not checked)')

    print('at most 50 a key')
    code, out = call('/api/notifier/keys', session=S)
    have = len([k for k in out['keys'] if k['id'] == KID][0].get('rules') or [])
    for i in range(50 - have):
        code, out = add({'device': THERMO, 'attr': 'humidity', 'op': 'gt', 'value': 50 + i})
        if code != 200:
            check(False, 'a rule under fifty refused: %s %r' % (code, out))
            break
    code, out = add({'device': THERMO, 'attr': 'humidity', 'op': 'gt', 'value': 99})
    check(code == 400 and 'at most 50 conditions per key' in out.get('error', ''), 'the 51st: %s %r' % (code, out))

    print('a restart: what was known is where it stands')
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'Restart PC'}, session=S)
    KID3 = out.get('id')
    report('Obyvak-Teplomer', {'temperature': 27.0})
    code, out = add({'device': THERMO, 'attr': 'temperature', 'op': 'gt', 'value': 26}, kid=KID3)
    R_HOT = out.get('rule') or {}
    code, out = add({'device': THERMO, 'attr': 'temperature', 'op': 'gt', 'value': 28}, kid=KID3)
    R_HOTTER = out.get('rule') or {}
    code, out = add({'device': TRV, 'attr': 'preset', 'op': 'changed'}, kid=KID3)
    R_CH = out.get('rule') or {}
    d.store.flush()
    d2 = zigmon.Daemon()
    d2.notify = lambda message, *a, **k: None
    report('Obyvak-Teplomer', {'temperature': 27.5}, dm=d2)          # true before, true now: nothing
    mine = [e for e in events_since(0, d2) if e[2] in ('rule:' + R_HOT.get('id', ''), 'rule:' + R_HOTTER.get('id', ''))]
    check(mine == [], 'the restart fired a condition already true: %r' % mine)
    report('Obyvak-Teplomer', {'temperature': 28.5}, dm=d2)          # the second becomes true
    mine = [(e[2], e[5]) for e in events_since(0, d2) if e[2] in ('rule:' + R_HOT.get('id', ''),
                                                                  'rule:' + R_HOTTER.get('id', ''))]
    check(mine == [('rule:' + R_HOTTER.get('id', ''), True)], 'after the restart: %r' % mine)
    report('Hlavice-Loznice', {'preset': 'boost'}, dm=d2)            # as it was before the restart: no change
    report('Hlavice-Loznice', {'preset': 'away'}, dm=d2)
    mine = [e[6] for e in events_since(0, d2) if e[2] == 'rule:' + R_CH.get('id', '')]
    check(mine == ['preset: away (was boost)'], 'changed after the restart: %r' % mine)
    # unknown before, true now: fires
    s0 = d2._ntf_seq
    d2.store.upsert_device({'id': '0x00158d0002a1b2c9', 'name': 'Novy', 'source': 'zigbee', 'kind': 'EndDevice'})
    d2.names['Novy'] = '0x00158d0002a1b2c9'
    out = d2.notifier_post({'action': 'rule_add', 'id': KID3, 'rule': {
        'device': '0x00158d0002a1b2c9', 'attr': 'temperature', 'op': 'gt', 'value': 0}}, 'owner')
    check((out.get('rule') or {}).get('active') is None, 'a rule of a device never heard: %r' % out)
    report('Novy', {'temperature': 5}, dm=d2)
    check([(e[3], e[5]) for e in events_since(s0, d2)] == [('rule', True)], 'unknown before, true now: %r'
          % events_since(s0, d2))

    print('a key taken away takes its conditions')
    code, out = call('/api/notifier/keys', {'action': 'delete', 'id': KID3}, session=S)
    raw = d.store.get_meta('notifier_keys') or ''
    check(code == 200 and R_HOT.get('id', 'x') not in raw and R_CH.get('id', 'x') not in raw,
          'the conditions of a key taken away are still kept')
    s0 = d._ntf_seq
    report('Obyvak-Teplomer', {'temperature': 29.5})
    check(not any(e[2] in ('rule:' + R_HOT.get('id', ''), 'rule:' + R_HOTTER.get('id', '')) for e in events_since(s0)),
          'a condition of a key taken away fired')

    print('the relay')
    page = (HERE / 'web' / 'index.php').read_text()
    for words in ("$what === 'notifier-attrs' && $_SERVER['REQUEST_METHOD'] === 'GET'", "/api/notifier/attrs?device=",
                  "api('notifier-attrs&device='", "action: 'rule_add'", "action: 'rule_update'", "action: 'rule_delete'",
                  'Add condition', 'ntf-conds'):
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

    def relay(query, session=None, key=None, timeout=60):
        headers = {}
        if session:
            headers['Cookie'] = 'zigmon_session=' + session
        if key is not None:
            headers['X-Zigmon-Notifier'] = key
        req = urllib.request.Request('http://127.0.0.1:%d/index.php?%s' % (PHP_PORT, query), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')

    code, out = relay('api=notifier-attrs&device=' + THERMO, session=S)
    check(code == 200 and any(a['key'] == 'temperature' and a['unit'] == '°C' for a in out.get('attrs') or []),
          'the attributes through the relay: %s %r' % (code, str(out)[:300]))
    code, out = relay('api=notifier-attrs&device=' + THERMO)
    check(code == 403, 'the attributes through the relay, signed out: %s %r' % (code, out))
    code, out = relay('api=notifier-attrs&device=' + THERMO, session=SO)
    check(code == 403, 'the attributes through the relay, an operator: %s %r' % (code, out))
    code, out = relay('api=notifier-attrs&device=' + THERMO + '%26x%3D1', session=S)
    check(code == 400, 'a device id with more in it: %s %r' % (code, out))
    code, out = relay('api=notifier&do=sensors', key=KEY)
    check(code == 200 and any(s.get('kind') == 'rule' for s in out.get('sensors') or []),
          'the rules through the notifier relay: %s %r' % (code, str(out)[:200]))

    print('the page')
    SHOTS.mkdir(parents=True, exist_ok=True)
    js = r'''
const { chromium } = require('playwright');
const job = %(job)s;
(async () => {
  const b = await chromium.launch();
  const r = {errors: []};
  for (const shot of [{n: 'desktop', w: 1400, h: 1100}, {n: 'phone', w: 390, h: 1600}]) {
    const ctx = await b.newContext({viewport: {width: shot.w, height: shot.h}, colorScheme: 'dark'});
    await ctx.addCookies([{name: 'zigmon_session', value: job.s, url: 'http://127.0.0.1:' + job.port + '/'}]);
    const p = await ctx.newPage();
    p.on('pageerror', e => r.errors.push(String(e)));
    await p.goto('http://127.0.0.1:' + job.port + '/#control/msg-desktop');
    await p.waitForTimeout(2000);
    try { await p.evaluate(() => showControlSection('msg-desktop')); } catch (e) {}
    await p.waitForSelector('#ntf-host .ntf-key .ntf-conds', {timeout: 15000});
    await p.waitForTimeout(400);
    const row = '#ntf-host .ntf-key[data-id="' + job.kid2 + '"]';
    r[shot.n] = await p.evaluate((row) => ({
      conds: Array.from(document.querySelectorAll(row + ' .ntf-cond')).map(x => x.textContent),
      pills: Array.from(document.querySelectorAll(row + ' .ntf-cpill')).map(x => x.textContent),
      wide: document.documentElement.scrollWidth, view: window.innerWidth}), row);
    await (await p.$(row)).screenshot({path: job.dir + '/key-' + shot.n + '.png'});
    await p.click(row + ' .ntf-cond-add');
    await p.waitForSelector('#zmodal:not([hidden]) #ntf-dev-find', {timeout: 5000});
    await p.fill('#ntf-dev-find', 'hlavice');
    r[shot.n].found = await p.evaluate(() => Array.from(document.querySelectorAll('#ntf-devs .ntf-dev')).filter(o => !o.hidden).map(o => o.dataset.id));
    await p.screenshot({path: job.dir + '/editor-device-' + shot.n + '.png'});
    await p.click('#ntf-devs .ntf-dev[data-id="' + job.trv + '"]');
    await p.waitForSelector('#ntf-attrs .ntf-attr[data-key="current_heating_setpoint"]', {timeout: 8000});
    await p.click('#ntf-attrs .ntf-attr[data-key="current_heating_setpoint"]');
    await p.waitForSelector('#ntf-ops .ntf-chip[data-op="ge"]', {timeout: 5000});
    r[shot.n].ops = await p.evaluate(() => Array.from(document.querySelectorAll('#ntf-ops .ntf-chip')).map(x => x.textContent));
    await p.click('#ntf-ops .ntf-chip[data-op="ge"]');
    await p.fill('#ntf-v1', '24');
    await p.fill('#ntf-hy', '0.5');
    await p.fill('#ntf-label', 'Bedroom heating ' + shot.n);
    await p.waitForTimeout(200);
    r[shot.n].preview = await p.evaluate(() => document.querySelector('#ntf-preview').textContent);
    r[shot.n].dlgwide = await p.evaluate(() => document.documentElement.scrollWidth);
    await p.screenshot({path: job.dir + '/editor-' + shot.n + '.png'});
    /* the enum's operators, looked at and left */
    await p.click('#ntf-attrs .ntf-attr[data-key="preset"]');
    await p.waitForTimeout(150);
    r[shot.n].enumops = await p.evaluate(() => Array.from(document.querySelectorAll('#ntf-ops .ntf-chip')).map(x => x.textContent));
    r[shot.n].enumvals = await p.evaluate(() => Array.from(document.querySelectorAll('#ntf-sel option')).map(x => x.textContent));
    await p.click('#ntf-attrs .ntf-attr[data-key="current_heating_setpoint"]');
    await p.click('#ntf-ops .ntf-chip[data-op="ge"]');
    await p.fill('#ntf-v1', '24');
    await p.fill('#ntf-hy', '0.5');
    await p.click('#zmodal-foot button:has-text("Add the condition")');
    await p.waitForSelector('#zmodal[hidden]', {state: 'attached', timeout: 8000});
    await p.waitForTimeout(500);
    r[shot.n].after = await p.evaluate((row) => Array.from(document.querySelectorAll(row + ' .ntf-cpill')).map(x => x.textContent), row);
    await (await p.$(row)).screenshot({path: job.dir + '/key-after-' + shot.n + '.png'});
    if (shot.n === 'desktop') {
      await p.click(row + ' .ntf-cond .ntf-cond-edit');
      await p.waitForSelector('#zmodal:not([hidden]) #ntf-preview', {timeout: 8000});
      await p.waitForTimeout(800);
      r.edit = await p.evaluate(() => ({title: document.querySelector('#zmodal-title').textContent,
        on: (document.querySelector('#ntf-attrs .ntf-attr.on') || {}).dataset ? document.querySelector('#ntf-attrs .ntf-attr.on').dataset.key : null,
        preview: document.querySelector('#ntf-preview').textContent}));
      await p.screenshot({path: job.dir + '/editor-edit.png'});
      await p.click('#zmodal-foot button:has-text("Cancel")');
    }
    await ctx.close();
  }
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
    npm_root = sh(['npm', 'root', '-g']).stdout.strip()
    (W / 'page.js').write_text(js % {'job': json.dumps({'s': S, 'port': PHP_PORT, 'dir': str(SHOTS), 'kid2': KID2,
                                                        'trv': TRV})})
    got = sh(['node', str(W / 'page.js')], timeout=240, env=dict(os.environ, NODE_PATH=npm_root))
    try:
        r = json.loads(got.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        r = {'error': (got.stdout + got.stderr)[-400:]}
    if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
        print('  SKIPPED (no browser here): %s' % r['error'][:200])
    else:
        check(not r.get('error'), 'the page: %r' % r.get('error'))
        for n in ('desktop', 'phone'):
            x = r.get(n) or {}
            check(x.get('pills') and x['pills'][0] == 'battery between 0 and 15 %', '%s: the pills: %r' % (n, x.get('pills')))
            check(any('Obyvak-Teplomer' in c and 'met now' in c for c in x.get('conds') or []),
                  '%s: the condition row: %r' % (n, x.get('conds')))
            check(x.get('found') == [TRV], '%s: the device search: %r' % (n, x.get('found')))
            check(x.get('ops') == ['>', '≥', '<', '≤', '=', '≠', 'between', 'outside', 'changes'],
                  '%s: the number operators: %r' % (n, x.get('ops')))
            check(x.get('enumops') == ['is', 'is not', 'changes'] and x.get('enumvals') == ['eco', 'comfort', 'boost', 'away'],
                  '%s: the enum operators: %r %r' % (n, x.get('enumops'), x.get('enumvals')))
            pv = x.get('preview') or ''
            check('Alert when' in pv and 'Hlavice-Loznice' in pv and 'setpoint ≥ 24 °C' in pv and 'Now 21 °C' in pv
                  and 'not met' in pv and '23.5 °C' in pv, '%s: the preview: %r' % (n, pv))
            check(any(p_ == 'setpoint ≥ 24 °C±0.5' for p_ in x.get('after') or []), '%s: the added rule: %r'
                  % (n, x.get('after')))
            check(x.get('wide', 9999) <= x.get('view', 0) + 1 and x.get('dlgwide', 9999) <= x.get('view', 0) + 1,
                  '%s: scrolls sideways: %r/%r/%r' % (n, x.get('wide'), x.get('dlgwide'), x.get('view')))
        ed = r.get('edit') or {}
        check(ed.get('title') == 'Edit the condition' and ed.get('on') in ('battery', 'current_heating_setpoint'),
              'the editor of a rule: %r' % ed)
        check(not r.get('errors'), 'the page threw: %r' % r.get('errors'))
        code, out = call('/api/notifier/keys', session=S)
        mine = [x for k in out.get('keys') or [] if k['id'] == KID2 for x in k.get('rules') or []]
        check(any(x['attr'] == 'current_heating_setpoint' and x['op'] == 'ge' and x['value'] == 24 and x['hyst'] == 0.5
                  and x['label'] == 'Bedroom heating desktop' for x in mine), 'the rule made in the browser: %r' % mine)
        print('  screenshots: %s' % SHOTS)

    print('never a key in the log, the events or the meta')
    whole = '\n'.join(LOG)
    with d.store.lock:
        evs = '\n'.join(str(x[0]) for x in d.store.db.execute('SELECT detail FROM events').fetchall())
    for k in (KEY, KEY2):
        check(k not in whole and k not in evs and k not in (d.store.get_meta('notifier_keys') or ''), 'a key is kept')
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
