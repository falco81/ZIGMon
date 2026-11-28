#!/usr/bin/env python3
"""A room switched Off and then to Max (or Comfort) opens its valve again (5.59.3).

Seen in a house: the bedroom on Off at 09:00 (its head put in its "off" mode, which an
Immax TS0601 reports as force "close"), then Max from a Stream Deck a few minutes after a
mode that had opened it. The head took 35 °C but stayed off and shut: the ask to take it off
its own programme was the same as the one made minutes before, so it was not sent again, and
from then on only the number was looked at - and the number was right.

  * Off, then a heating mode within five minutes: system_mode and force are asked again at once;
  * a head that holds the right number but still says off / close is asked again (at most once
    in five minutes - a battery device);
  * a room that is meant to be off is still left off.

    python3 test/review5593_heat_reopen.py < /dev/null

No broker, no web server. Every name here is made up.
"""
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-heatreopen-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.log = lambda *a, **k: None
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 0, 'token_file': str(W / 'token'),
                      'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '',
                      'state_dir': str(W / 'state'), 'heating_enforce': 'never'})
(W / 'state').mkdir()
d = zigmon.Daemon()

HEAD = '0xtrv1'
d.store.upsert_device({'id': HEAD, 'name': 'TRV-Bedroom', 'source': 'zigbee', 'kind': 'EndDevice', 'exposes': {
    'current_heating_setpoint': {'access': 7, 'min': 5, 'max': 35},
    'system_mode': {'access': 7, 'values': ['off', 'heat', 'auto']},
    'preset': {'access': 7, 'values': ['manual', 'programming', 'holiday']},
    'force': {'access': 7, 'values': ['normal', 'open', 'close']}}})
payload = {'system_mode': 'off', 'preset': 'manual', 'force': 'close', 'current_heating_setpoint': 25.0}
d.live[HEAD] = {'payload': payload}
room = {'mode': 'comfort', 'wanted': 25.0, 'why': 'comfort'}
d.rooms = lambda: [{'id': 'r1', 'name': 'Bedroom'}]
d.heating_state = lambda: {'enabled': True, 'rooms': [{
    'id': 'r1', 'name': 'Bedroom', 'mode': room['mode'], 'wanted_c': room['wanted'], 'why': room['why'],
    'valves': [{'target': 'zb:%s:current_heating_setpoint' % HEAD, 'name': 'TRV-Bedroom',
                'setpoint': payload['current_heating_setpoint'], 'min': 5, 'max': 35}]}]}
sent = []


def switch(dev, key, act, origin=''):
    sent.append((key, act))
    return True, 'published'


d.zigbee_switch = switch


def report(**kw):
    """What the head says back."""
    payload.update(kw)


def asked(key):
    return [a for k, a in sent if k == key]


print('comfort, the head off and shut but already at 25: opened, the number left be')
d.heating_apply()
check(asked('system_mode') == ['set:auto'] and asked('force') == ['set:normal'],
      'not opened for comfort: %r' % sent)
check(asked('current_heating_setpoint') == [], 'a number it already holds was sent: %r' % sent)
report(system_mode='auto', force='normal', current_heating_setpoint=25.0)

print('off: put in its off mode')
sent.clear()
room.update(mode='off', wanted=5.0, why='off')
d.heating_apply()
check(asked('system_mode') == ['set:off'], 'not shut: %r' % sent)
report(system_mode='off', force='close')
sent.clear()
d.heating_apply()
check(not sent, 'a room meant to be off was touched again: %r' % sent)

print('max a minute later: opened again at once')
sent.clear()
room.update(mode='max', wanted=35.0, why='max')
d.heating_apply()
check(asked('system_mode') == ['set:auto'] and asked('force') == ['set:normal'],
      'Off then Max within five minutes left the head off and shut: %r' % sent)
check(asked('current_heating_setpoint') == ['set:35'], 'no 35: %r' % sent)

print('a head that took the number but stayed off is asked again')
report(current_heating_setpoint=35.0)          # it says 35, still off and shut (the ask was lost)
sent.clear()
d.heating_apply()
check(not asked('system_mode'), 'asked again within the five minutes - a battery head: %r' % sent)
was = d._valve_mode[HEAD]
d._valve_mode[HEAD] = (was[0] - 301, was[1])
sent.clear()
d.heating_apply()
check(asked('system_mode') == ['set:auto'] and asked('force') == ['set:normal'],
      'a head holding 35 but off and shut was left so: %r' % sent)
check(not asked('current_heating_setpoint'), 'the right number was sent again: %r' % sent)
report(system_mode='auto', force='normal')
sent.clear()
d._valve_mode.clear()
d.heating_apply()
check(not sent, 'a head that is open and holding its number was told something: %r' % sent)

try:
    d.store.flush(5)
except Exception:
    pass
print('FAILED: %d' % len(bad) if bad else 'all good')
sys.exit(1 if bad else 0)
