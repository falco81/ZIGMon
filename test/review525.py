#!/usr/bin/env python3
"""The faults found for 5.25, each one proved on its own: every check here
fails on 5.24.0 and passes since.

    python3 test/review525.py

No broker, gateway or web server: the daemon is built in this process and the
gateway, the heads and the clock are stood in for.
"""
import json
import os
import socket
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review525-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 0, 'token_file': str(W / 'run' / 'api-token'),
                      'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '',
                      'state_dir': str(W / 'state')})
(W / 'state').mkdir()
d = zigmon.Daemon()
real_time = time.time

# ---- the page's status -----------------------------------------------------------------
print('the status: the same JSON, the devices not written out again')
for i in range(40):
    d.store.upsert_device({'id': '0x%04x' % i, 'name': 'Dev %d' % i, 'source': 'zigbee', 'kind': 'sensor',
                           'exposes': {'temperature': {}}})
obj = d.status()
whole = json.loads(json.dumps(obj, ensure_ascii=False))
got = json.loads(d.status_body())
got_obj = json.loads(d._status_json(obj)) if hasattr(d, '_status_json') else None
check(got_obj == whole, 'the status written in parts is not the status')
if hasattr(d, '_status_json'):
    d._status_json(obj)
    calls = []
    was = d._json_out
    d._json_out = lambda o: calls.append(1) or was(o)
    d._status_json(obj)
    d._json_out = was
    check(len(calls) == 1, 'every device was written out again for a status nothing changed in (%d)' % len(calls))
else:
    check(False, 'every device is written out again for every page woken')

# ---- texts -------------------------------------------------------------------------------
print('texts: one that timed out is not sent again, one held is given up in time')
zigmon.CONFIG.update({'sms_send_gap_s': 0, 'sms_daily_cap': 0, 'sms_queue_hours': 6})
d.sms_ready = lambda: True
d.sms_modem_id = lambda: '1-1'
handed = []


def rest(path, method='GET', payload=None, retry=True, timeout=None):
    handed.append(payload['data']['message'])
    raise socket.timeout('timed out')                   # the box took it and did not answer


d._rest = rest
d.sms_send('+420111222333', 'Boiler fault', why='alert')
for _ in range(4):
    d._sms_hold_until = 0
    d.sms_flush()
check(len(handed) == 1, 'an alert the gateway did not answer for was sent %d times' % len(handed))
d.store.set_meta('sms_outbox', '[]')

calls = []
was_send = d.sms_send
d.sms_send = lambda n, t, why='alert', queue=True: calls.append(n) or (False, 'HTTP 500')
d.sms_queue_add('+420111', 'held', 'quiet hours', send_after=real_time() - 1)
for k in range(4):
    time.time = lambda o=k * 86400: real_time() + o
    d.sms_flush()
time.time = real_time
check(not d.sms_outbox(), 'a text held for the morning that keeps failing is tried for ever: %r'
      % [(x['number'], x['tries']) for x in d.sms_outbox()])
d.sms_send = was_send

# ---- who is home, across a restart --------------------------------------------------------
print('who is home outlives a restart')
d.store.set_meta('people', json.dumps([{'id': 'p1', 'name': 'Jana', 'macs': ['aa:bb:cc:dd:ee:01'],
                                        'enabled': True, 'grace_s': 60, 'notify': False}]))
d._apply_clients([{'mac': 'aa:bb:cc:dd:ee:01', 'name': 'phone'}])
d.presence['p1']['last_seen'] -= 120                    # last seen two minutes ago
if hasattr(d, 'presence_keep'):
    d._presence_kept = None
    d.presence_keep()
d.store.flush(3.0)
d2 = zigmon.Daemon()
fired = []
d2.fire_presence_triggers = lambda person, events: fired.append(events)
d2._apply_clients([])
check(fired and 'leave' in fired[0], 'somebody who left while the daemon restarted never left: %r' % fired)
d2.store.flush(3.0)
d.presence['p1'].update(home=True, last_seen=real_time())   # home again, then a restart
if hasattr(d, 'presence_keep'):
    d._presence_kept = None
    d.presence_keep()
d.store.flush(3.0)
d3 = zigmon.Daemon()
fired3 = []
d3.fire_presence_triggers = lambda person, events: fired3.append(events)
d3._apply_clients([])
d3._apply_clients([{'mac': 'aa:bb:cc:dd:ee:01', 'name': 'phone'}])
check(not fired3, 'a phone dozing at the first round after a restart made its owner arrive again: %r' % fired3)

# ---- a scene pressed again starts over ------------------------------------------------------
print('a scene pressed again starts over')
d.scenes = lambda: [{'id': 'sA', 'name': 'Porch', 'enabled': True, 'actions': [
    {'target': 'zb:lamp', 'do': 'on'}, {'target': 'zb:lamp', 'do': 'off', 'after_s': 0.6}]}]
seen = []
was_bt, was_ft = d._binding_targets, d._fire_target
d._binding_targets = lambda t: [('zb', 'lamp', 'state')]
t0 = real_time()
d._fire_target = lambda target, do, origin, *a, **k: seen.append((round(real_time() - t0, 1), do))
for _ in range(3):
    d.run_scene('sA')
    time.sleep(0.25)
time.sleep(1.0)
offs = [x for x in seen if x[1] == 'off']
check(len(offs) == 1 and offs[0][0] >= 1.0, 'a scene pressed three times went off after the first press, '
      'and again after each: %r' % seen)
d._binding_targets, d._fire_target = was_bt, was_ft
del d.scenes

# ---- a head that never took its setting ----------------------------------------------------
print('a radiator head that never took its setting is told again')
head = {'setpoint': 21.0}
d.rooms = lambda: [{'id': 'r1', 'name': 'Bedroom'}]
d.heating_state = lambda: {'enabled': True, 'rooms': [{'id': 'r1', 'name': 'Bedroom', 'mode': 'plan',
                                                        'wanted_c': 17.0, 'why': 'night', 'valves': [
    {'target': 'zb:trv1:current_heating_setpoint', 'name': 'TRV', 'setpoint': head['setpoint'],
     'min': 5, 'max': 30}]}]}
sent = []
d.valve_take_over = lambda dev: None
d.zigbee_switch = lambda dev, key, act, origin='': (sent.append(act) or (True, 'published'))
zigmon.CONFIG['heating_enforce'] = 'never'
d.heating_apply()
d._heat_told.clear()
d.heating_apply()
check(len(sent) >= 2, 'a head that kept saying 21 after being told 17 was never told again: %r' % sent)

# ---- schedules after the daemon was away ------------------------------------------------------
print('a schedule missed while the daemon was away is caught up the same morning')
fired_s = []
sch = [{'id': 's1', 'enabled': True, 'days': list(range(7)), 'at': '07:00', 'target': 'plug:x', 'do': 'on'},
       {'id': 's2', 'enabled': True, 'days': list(range(7)), 'at': '07:05', 'target': 'plug:y', 'do': 'toggle'}]
base = time.mktime((2026, 10, 29, 6, 58, 0, 0, 0, -1))


def wire(x):
    x.schedules = lambda: sch
    x._binding_targets = lambda t: [('plug', None)]
    x.target_label = lambda t: t
    x._trial_act = lambda *a, **k: False
    x._fire_target = lambda target, do, origin, *a, **k: fired_s.append((origin, do))


e1 = zigmon.Daemon()
wire(e1)
for when in (base, base + 60):
    time.time = lambda w=when: w
    e1.check_schedules()
e1.store.flush(3.0)
e2 = zigmon.Daemon()
wire(e2)
for k in range(12, 16):                                  # back at 07:10
    time.time = lambda w=base + k * 60: w
    e2.check_schedules()
time.time = real_time
check([x for x in fired_s if x[1] == 'on'], 'a 07:00 "on" missed while the daemon was away 06:59-07:10 '
      'never happened: %r' % fired_s)
check(not [x for x in fired_s if x[1] == 'toggle'], 'a toggle missed long ago was done late: %r' % fired_s)

# ---- the blocked list ----------------------------------------------------------------------
print('an address blocked is kept out at once, and a block does not read the whole list again')
import threading                                        # noqa: E402
st = d.store
now = real_time()
with st.lock:
    st.db.executemany('INSERT OR REPLACE INTO blocked (ip, since, until, why, hits, auto, by) '
                      'VALUES (?,?,?,?,1,1,"")',
                      [('10.%d.%d.%d' % (i >> 16 & 255, i >> 8 & 255, i & 255), now, now + 86400, 'x')
                       for i in range(5000)])
    st.db.commit()
st._block_changed()
st.blocked_until('1.1.1.1')                             # the list read whole once
reads = []
was_reload = st._block_reload
st._block_reload = lambda when: reads.append(1) or was_reload(when)
gate, let_in = threading.Event(), []


def hold():
    with st.lock:
        gate.set()
        time.sleep(0.8)                                 # a backup holding the database


st.block('203.0.113.9', now + 3600, 'test')
h = threading.Thread(target=hold)
h.start()
gate.wait()
end = real_time() + 0.6
while real_time() < end:
    if st.blocked_until('203.0.113.9', wait=False) is None:
        let_in.append(1)
h.join()
check(not let_in, 'an address blocked a moment before was let in %d times while the list was read again'
      % len(let_in))
for i in range(30):
    st.block('198.51.100.%d' % i, now + 3600, 'sweep')
    st.blocked_until('192.0.2.1')                        # the sweep asks about the next address
check(len(reads) <= 2, 'thirty blocks in a sweep read the whole blocked list %d times' % len(reads))
check(st.blocked_until('198.51.100.7') is not None and st.blocked_until('203.0.113.9', wait=False) is not None,
      'a block made is not on the list')
st.unblock('198.51.100.7')
check(st.blocked_until('198.51.100.7', wait=False) is None, 'an address let back in is still kept out')
st._block_reload = was_reload

# ---- the API ----------------------------------------------------------------------------------
print('the API: no endless connections, no unbounded history, no internals in an error')
check(getattr(zigmon.ApiHandler, 'timeout', None) and zigmon.ApiHandler.timeout <= 60,
      'a client that says nothing holds a thread of the API for good')
check(getattr(zigmon.ApiHandler, 'HISTORY_KEYS', 10 ** 6) <= 20,
      'one question for the history may ask for any number of readings')
src = (HERE / 'zigmon.py').read_text()
hist = src[src.index('    def history(self, device_id, keys, seconds'):src.index('    def reading_over(')]
check(hist.index('for key in keys:') < hist.index('with self.lock:'),
      'the history of many readings holds the database for all of them at once')
check("'internal error: %s' % e" not in src, 'an internal error tells the client what the database said')
one = {'timestamp': '2026-10-29T08:00:00.123456+0100'}
check(hasattr(d, '_eve_moment') and abs(d._eve_moment(one, 0) - 1793257200.12) < 1,
      'a TLS hello is counted at the moment it is read, not when it happened')

# ---- the page ------------------------------------------------------------------------------------
print('the console at login is changed on Save, not on the click')
page = (HERE / 'web' / 'index.php').read_text()
sw = page[page.index('function drawConsoleSwitch('):page.index('function rootPaneShown(')]
check('save.onclick' in sw and sw.index("post('about-do'") > sw.index('save.onclick'),
      'the switch of the console at login changes root\'s login the moment it is clicked')

sys.stdout.flush()
if bad:
    print('\n%d check(s) failed' % len(bad))
    os._exit(1)
print('every fault the 5.25 read found stays mended')
os._exit(0)
