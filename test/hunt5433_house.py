#!/usr/bin/env python3
"""5.43.3: what a hunt through the house itself found - the rules, the
sensor groups, the schedules, the batteries, the buttons and the meters -
each check failing on 5.43.2 and passing since.

    python3 test/hunt5433_house.py

No broker, box or web server: the daemon is driven in-process, with its
switching caught before anything is sent. The clock is Europe/Prague, the
house's own, so the nights the clocks change are the real ones.

HUNT_DAEMON=dir: the daemon (zigmon.py) of that folder, to see its checks
fail on 5.43.2's.
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ['TZ'] = 'Europe/Prague'
time.tzset()

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-hunt5433-house-'))
sys.path.insert(0, os.environ.get('HUNT_DAEMON') or str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'zigmon.db'), 'api_port': 19510, 'token_file': str(W / 'token'),
                      # two sockets on ports nothing listens on: boxes gone away
                      'plugs': [{'name': 'Lamp', 'host': '127.0.0.1:19512'},
                                {'name': 'Heater', 'host': '127.0.0.1:19513', 'host_state': 'optional'}],
                      'sensors': [], 'backup_dir': str(W / 'backups'),
                      'latitude': 50.08, 'longitude': 14.42, 'weather': False,
                      'binding_debounce_ms': 400, 'state_dir': str(W)})
d = zigmon.Daemon()
d.backup_dir = lambda: W / 'backups'

bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def dev(ident, name, **payload):
    d.store.upsert_device({'id': ident, 'name': name, 'source': 'zigbee', 'kind': 'EndDevice', 'exposes': {}})
    d.live[ident] = {'payload': dict(payload), 'ts': int(time.time()), 'availability': 'online'}


acted = []
d._rule_act = lambda r, origin, facts, device_id='': acted.append(r['id'])


def rule_ids():
    return [r['id'] for r in d.rules()]


# -- 1. a rule woken by its THIRD side reads what that side has just said ----
dev('0xa1', 'Hall-PIR', occupancy=0)
dev('0xa2', 'Loo-Door', contact=0)
dev('0xa3', 'Loo-PIR', occupancy=1)
d.save_rules([{'device': '0xa1', 'key': 'occupancy', 'op': '==', 'value': 0,
               'device2': '0xa2', 'key2': 'contact', 'op2': '==', 'value2': 0, 'combine': 'and',
               'device3': '0xa3', 'key3': 'occupancy', 'op3': '==', 'value3': 0, 'combine3': 'and',
               'plug': 'notify', 'do': 'on', 'cooldown_s': 0}])
rid = rule_ids()[0]
d.rule_runtime[rid] = {'holds': False, 'fired': 0.0, 'reading': 0}
del acted[:]
# the broker thread hands the reading over BEFORE it writes the memory of it:
# the rule worker sees the new report, the house still holds the old value
d.fire_rules('0xa3', 'Loo-PIR', {'occupancy': 0.0})
check(acted == [rid], 'a three-sided rule woken by its third sensor read that sensor\'s old value and did '
                      'not fire (%r)' % acted)
print('a rule woken by its third side reads what that side has just said')

# -- 2. ...and is primed with its third side after a restart -----------------
d.rule_runtime.clear()
d.live['0xa3']['payload'] = {'occupancy': 1}
d.prime_rules()
check(d.rule_runtime.get(rid, {}).get('holds') is False,
      'a three-sided rule with its third side false was primed as holding: %r' % d.rule_runtime.get(rid))
del acted[:]
d.live['0xa3']['payload'] = {'occupancy': 0}
d.fire_rules('0xa3', 'Loo-PIR', {'occupancy': 0.0})
check(acted == [rid], 'after a restart, the third side turning true did not fire the rule (%r)' % acted)
print('a three-sided rule is primed with all three sides after a restart')
d.save_rules([])

# -- 3. a sensor group hears the member that is speaking, however long it was quiet
dev('0xb1', 'PIR-One', occupancy=0)
dev('0xb2', 'PIR-Two', occupancy=0)
groups = d.save_sensor_groups([{'name': 'Hall PIRs', 'key': 'occupancy', 'mode': 'any',
                                'members': ['0xb1', '0xb2'], 'fresh_minutes': 30}])
gid = 'grp:' + groups[0]['id']
d.store.flush()
for ident, ago in (('0xb1', 3 * 3600), ('0xb2', 60)):
    d.store._write_touch(ident, int(time.time()) - ago)
d.store._dev_cache.pop('0xb1', None)
d.store._dev_cache.pop('0xb2', None)
d.store._dev_list = None
d._group_last[gid] = 0.0
# PIR-One has been quiet three hours and now sees somebody; its last_seen is
# written by the database's writer behind this, so the row still says 3 h ago
d.refresh_group('0xb1', 'PIR-One', {'occupancy': 1.0})
check(d._group_last.get(gid) == 1.0, 'a group member quiet for longer than "fresh" was left out of its own '
                                     'movement: the group read %r' % d._group_last.get(gid))
print('a sensor group hears the member speaking now, however long it had been quiet')

# -- 4. a "must hold for" rule starts counting when its window opens --------------
dev('0xc1', 'Landing-PIR', occupancy=0)
now_t = time.localtime()
start = (now_t.tm_hour * 60 + now_t.tm_min - 1) % 1440
end = (start + 120) % 1440
d.save_rules([{'device': '0xc1', 'key': 'occupancy', 'op': '==', 'value': 0, 'for_s': 600,
               'from': '%02d:%02d' % (start // 60, start % 60), 'to': '%02d:%02d' % (end // 60, end % 60),
               'plug': 'notify', 'do': 'off', 'cooldown_s': 0}])
rid = rule_ids()[0]
d.rule_runtime[rid] = {'holds': None, 'fired': 0.0, 'reading': None, 'window': False}
d.check_rule_windows()
rt = d.rule_runtime.get(rid) or {}
check(rt.get('holds') is True and 'since' in rt,
      'a quiet sensor\'s "no motion for ten minutes" rule did not start counting when its window opened: %r' % rt)
del acted[:]
if 'since' in rt:
    rt['since'] = time.time() - 601
d.check_rule_for()
check(acted == [rid], 'ten quiet minutes into its window the rule did not fire without a fresh report (%r)' % acted)
print('a "must hold for" rule counts from the moment its window opens, with no report needed')
d.save_rules([])

# -- 5. a Shelly on a battery is in every list of batteries --------------------------
d.store.upsert_device({'id': 'shellies:ht-bath', 'name': 'HT-Bath', 'source': 'shelly', 'kind': 'wifi',
                       'exposes': {}})
d.live['shellies:ht-bath'] = {'payload': {'battery.percent': 7, 'battery.V': 2.6, 'tC': 22.1},
                              'ts': int(time.time()), 'availability': 'online'}
with d.store.lock:
    for i, v in enumerate((30, 22, 15, 10, 7)):
        d.store.db.execute('INSERT OR REPLACE INTO samples (ts,device,key,value) VALUES (?,?,?,?)',
                           (int(time.time()) - (5 - i) * 86400, 'shellies:ht-bath', 'battery.percent', v))
listed = [x for x in d.battery_health(force=True) if x['id'] == 'shellies:ht-bath']
check(listed and listed[0]['percent'] == 7 and listed[0]['per_week'],
      'a Shelly H&T (battery.percent) was missing from the battery list, or had no rate: %r' % listed)
d._health_cache = None
check(d._house_health().get('battery') == 7, 'the lowest battery in the house left out a Shelly H&T at 7%%: %r'
      % d._house_health().get('battery'))
print('a Shelly on a battery is in the battery list and the lowest-battery figure')

# -- 6. a schedule moved to a later time fires at it the same day ----------------------
t = time.localtime()
here = '%02d:%02d' % (t.tm_hour, t.tm_min)
other = '%02d:%02d' % (((t.tm_hour + 3) % 24), t.tm_min)
saved = d.save_schedules([{'target': 'notify', 'do': 'on', 'at': other, 'days': 'all'}])
sid = saved[0]['id']
today = time.strftime('%Y-%m-%d', t)
d.schedule_runtime[sid] = {'last_day': today}            # it fired at the old time today
d.store.set_meta('schedule_day_%s' % sid, today)
d.save_schedules([dict(saved[0], at=here)])
fired = []
was_fire = d._fire_target
d._fire_target = lambda target, do, origin, *a, **k: fired.append((target, do))
try:
    d._sched_minute = None
    d.check_schedules()
finally:
    d._fire_target = was_fire
check(fired, 'a schedule that fired today and was moved to a later time did not fire at the new time')
print('a schedule moved to another time is a new moment, not "already done today"')
d.save_schedules([])

# -- 7. a clock stepped back does not swallow presses ------------------------------------
dev('0xd1', 'Button-Hall', action='')
d.store.set_meta('bindings', json.dumps([{'device': '0xd1', 'action': 'single', 'plug': 'notify', 'do': 'on',
                                          'enabled': True, 'id': 'b1'}]))
presses = []
d._fire_bindings_now = lambda hits, name, action: presses.append(action)
d.__dict__.setdefault('_press_seen', {})['0xd1|single'] = time.time() + 3600   # pressed "an hour from now"
d.fire_bindings('0xd1', 'Button-Hall', 'single')
time.sleep(0.4)
check(presses == ['single'], 'with the clock stepped back an hour, a press was taken for a repeat and dropped')
print('a clock stepped back does not turn every press into "the same press again"')

# -- 8. a window sensor that has said nothing yet is not an open window ------------------
dev('0xe1', 'Window-Bedroom', contact=None)           # just paired: Zigbee2MQTT says null
dev('0xe2', 'Door-Balcony', contact=True)
check(d.room_window_open('r-bed', {'windows': ['0xe1', '0xe2']}) is False,
      'a contact Zigbee2MQTT reports as null was taken for an open window, and the room\'s heating shut')
d.live['0xe2']['payload'] = {'contact': False}
check(d.room_window_open('r-bed', {'windows': ['0xe1', '0xe2']}) is True,
      'an open balcony door behind a sensor that had not spoken yet was missed')
print('a window sensor that has not said anything yet does not shut the heating')

# -- 9. "what if" asks a 24-hour-average rule about the difference, as the rule does ---
dev('0xf1', 'Lounge-Temp', temperature=20.0)
d.save_rules([{'device': '0xf1', 'key': 'temperature', 'op': '>', 'value': 2, 'mode': 'delta24',
               'plug': 'notify', 'do': 'on'}])
d.avg24 = lambda device_id, key: 20.0
d.live['0xf1']['payload'] = {}
said = d.what_would_happen('0xf1', 'temperature', 21)
check(said['rules'] and not said['rules'][0]['would_fire'],
      '"what if 21" on a rule for 2 degrees above the day\'s 20 said it would fire: %r' % said['rules'])
said = d.what_would_happen('0xf1', 'temperature', 23)
check(said['rules'] and said['rules'][0]['would_fire'],
      '"what if 23" on a rule for 2 degrees above the day\'s 20 said it would not fire: %r' % said['rules'])
print('"what if" compares a 24-hour-average rule by its difference, as the rule itself does')
d.save_rules([])
del d.avg24

# -- 10. the 25-hour day is not "over" at 23:00 -------------------------------------------
t0 = zigmon.local_moment(2026, 10, 25, 0)
t1 = t0 + 24 * 3600 + 1800                  # 23:30 on the day the clocks go back
check(time.localtime(t1).tm_hour == 23, 'the test clock is not Europe/Prague')
with d.store.lock:
    for ts, v in ((t0 + 60, 100.0), (t0 + 3600, 200.0)):
        d.store.db.execute('INSERT OR REPLACE INTO samples (ts,device,key,value) VALUES (?,?,?,?)',
                           (int(ts), 'plug:Kettle', 'switch.aenergy.total', v))
was_time = zigmon.time.time
zigmon.time.time = lambda: t1 + 1
try:
    first = d.day_energy('plug:Kettle', t0, t1)
    with d.store.lock:
        d.store.db.execute('INSERT OR REPLACE INTO samples (ts,device,key,value) VALUES (?,?,?,?)',
                           (int(t1 - 60), 'plug:Kettle', 'switch.aenergy.total', 900.0))
    second = d.day_energy('plug:Kettle', t0, t1)
finally:
    zigmon.time.time = was_time
check(first == 100.0 and second == 800.0,
      'at 23:30 on the 25-hour day, today\'s energy was taken as a finished day and kept: %r then %r'
      % (first, second))
print('the night the clocks go back, today is not counted as over an hour early')

# -- 11. a socket that stops answering is shown as not answering --------------------------
for name in ('Lamp', 'Heater'):
    p = d.plugs[name]
    d._record_plug(p, {'id': 0, 'output': True, 'apower': 5.0}, {}, time.time())    # it answered once
    for _ in range(3):
        d.poll_plug(p, force=True)                                                # ...and then never
lamp = d.describe(d.store.device('plug:Lamp'), d.live.get('plug:Lamp'))
check(not lamp['online'] and lamp['level'] == 'crit' and 'not answering' in lamp['reasons'],
      'a socket that stopped answering three readings ago was still "online" and "%s" in the status: %r'
      % (lamp['level'], lamp['reasons']))
heater = d.describe(d.store.device('plug:Heater'), d.live.get('plug:Heater'))
check(heater['unplugged'] and heater['level'] == 'ok',
      'an optional socket that stopped answering was never shown as unplugged: %r' % heater['reasons'])
d.handle_plug_push([d.plugs['Lamp']], ['status', 'switch:0'], json.dumps({'id': 0, 'output': False}).encode())
check((d.live.get('plug:Lamp') or {}).get('availability') == 'online',
      'a socket that pushed its state over MQTT stayed "not answering" until the next reading')
print('a socket that stops answering is "not answering" in the status, and back the moment it speaks')

# -- 12. a sequence's reset does not write over a press made while it ran -------------------
seqs = d.save_sequences([{'name': 'Hall sequence', 'steps': ['notify', 'notify'], 'reset_scene': 'notify|on'},
                         {'name': 'Desk sequence', 'steps': ['notify', 'notify', 'notify']}])
hall, desk = seqs[0]['id'], seqs[1]['id']
was_step = d._run_step


def step_and_press(step, origin, seq_name, hold_by=None, deep=0):
    if 'reset' in origin:
        d.advance_sequence(desk, 'the desk button')        # pressed while the reset scene runs
d._run_step = step_and_press
try:
    d.reset_sequence(hall, 'the hall button')
finally:
    d._run_step = was_step
check(d.sequence_positions().get(desk) == 1,
      'a press of one sequence while another was being reset was written over - it is back at step %r'
      % (d.sequence_positions().get(desk, 0) + 1))
print('resetting a sequence keeps every press made meanwhile')

# -- 13. a sunset window with the place taken away does not silence the rules after it -------
dev('0xg1', 'Porch-PIR', occupancy=0)
d.save_rules([{'device': '0xg1', 'key': 'occupancy', 'op': '==', 'value': 1, 'from': 'sunset', 'to': 'sunrise',
               'plug': 'notify', 'do': 'on', 'cooldown_s': 0},
              {'device': '0xg1', 'key': 'occupancy', 'op': '==', 'value': 1, 'plug': 'notify', 'do': 'on',
               'cooldown_s': 0}])
second = rule_ids()[1]
zigmon.CONFIG['latitude'] = zigmon.CONFIG['longitude'] = None          # taken out in Settings
del acted[:]
try:
    d.fire_rules('0xg1', 'Porch-PIR', {'occupancy': 1.0})
    raised = None
except Exception as e:                                                  # noqa: BLE001
    raised = e
check(raised is None and second in acted,
      'with the house\'s place taken out of the settings, a sunset-window rule raised %r and the rule after '
      'it never ran' % (raised,))
zigmon.CONFIG.update({'latitude': 50.08, 'longitude': 14.42})
d.save_rules([])
print('a sunset window without a place set stays open, and the rules after it still run')

# -- 14. an hour of the forecast without a figure does not lose the whole forecast -----------
hour0 = time.strftime('%Y-%m-%dT%H:00')
hour1 = time.strftime('%Y-%m-%dT%H:00', time.localtime(time.time() + 3600))
hour2 = time.strftime('%Y-%m-%dT%H:00', time.localtime(time.time() + 7200))
answer = json.dumps({'current': {'temperature_2m': 4.5, 'is_day': 0, 'weather_code': 3},
                     'hourly': {'time': [hour0, hour1, hour2], 'temperature_2m': [4.5, None, 3.0]},
                     'daily': {'sunrise': ['2026-11-06T07:01'], 'sunset': ['2026-11-06T16:24']}}).encode()


class _Answer(object):
    def read(self):
        return answer


was_open = zigmon.web_open
zigmon.web_open = lambda *a, **k: _Answer()
zigmon.CONFIG['weather'] = True
try:
    try:
        got = d.weather(force=True)
    except Exception as e:                                              # noqa: BLE001
        got = e
finally:
    zigmon.web_open = was_open
    zigmon.CONFIG['weather'] = False
check(isinstance(got, dict) and got.get('min_c') == 3.0,
      'an hour open-meteo had no temperature for (null) threw the forecast away: %r' % (got,))
print('a forecast with an hour missing is kept, with the hours it has')

shutil.rmtree(str(W), ignore_errors=True)
print('hunt5433_house: %s' % ('%d failed' % len(bad) if bad else 'all good'))
os._exit(1 if bad else 0)
