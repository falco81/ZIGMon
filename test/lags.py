#!/usr/bin/env python3
"""The things that stood between a sensor and its light without being on the
way: a database somebody else held, a thread somebody else kept busy, a road
that was known to be dead and was tried anyway. 5.16.0, each one measured on
5.15.0 first and checked here to stay mended.

    PYTHONPATH=. python3 test/lags.py

A fake Shelly on a port of its own, no broker, no web server.
"""
import base64
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

BOX = {'output': False, 'sets': [], 'calls': [], 'busy_times': 0, 'poll_delay': 0.0}


class Box(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        method, params = body.get('method'), body.get('params') or {}
        BOX['calls'].append((time.time(), method))
        if BOX['busy_times'] > 0:
            BOX['busy_times'] -= 1
            raw = b'{"error":"too many requests"}'
            self.send_response(429)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if method == 'Switch.Set':
            BOX['sets'].append((time.time(), bool(params.get('on'))))
            out = {'was_on': BOX['output']}
            BOX['output'] = bool(params.get('on'))
        elif method in ('Shelly.GetStatus', 'Switch.GetStatus'):
            seen = BOX['output']                  # what the relay is as the request arrives
            if BOX['poll_delay']:
                time.sleep(BOX['poll_delay'])
            out = {'switch:0': {'id': 0, 'output': seen, 'apower': 12.0, 'voltage': 231.0,
                                'aenergy': {'total': 1.0}}, 'id': 0, 'output': seen,
                   'apower': 12.0, 'mqtt': {'connected': False}}
        elif method == 'Shelly.GetDeviceInfo':
            out = {'id': 'shellyplug-test', 'model': 'S3PL-00112EU', 'gen': 3, 'ver': '1.7.1'}
        else:
            out = {}
        raw = json.dumps({'id': body.get('id'), 'result': out}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


server = ThreadingHTTPServer(('127.0.0.1', 19961), Box)
threading.Thread(target=server.serve_forever, daemon=True).start()

zigmon.load_config()
DB = '/tmp/zigmon-lags-check.db'
for _ext in ('', '-wal', '-shm'):
    try:
        os.remove(DB + _ext)
    except OSError:
        pass
zigmon.CONFIG.update({'db_file': DB, 'api_port': 19962, 'token_file': '/tmp/zigmon-lags-token',
                      'pin': '1234', 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'backup_dir': '/tmp/zigmon-lags-backups'})
import shutil                                            # noqa: E402
shutil.rmtree('/tmp/zigmon-lags-backups', ignore_errors=True)
d = zigmon.Daemon()
d.backup_dir = lambda: Path('/tmp/zigmon-lags-backups')
d.notify = lambda *a, **k: None
threading.Thread(target=d.rule_worker, name='rules', daemon=True).start()
threading.Thread(target=d.rule_worker, args=(True,), name='rules-presence', daemon=True).start()


def check(ok, what):
    if not ok:
        raise AssertionError(what)


def plug(**extra):
    entry = dict({'name': 'Light-Test', 'host': '127.0.0.1:19961', 'switch_id': 0, 'kind': 'plug',
                  'host_state': 'enabled'}, **extra)
    d.store.set_meta('managed', json.dumps({'plugs': [entry], 'sensors': []}))
    d.reload_devices()
    return d.plugs['Light-Test']


def busy_database(seconds=1.5):
    """Somebody else holding the database: a backup, an optimise."""
    def held():
        with d.store.lock:
            time.sleep(seconds)
    t = threading.Thread(target=held, daemon=True)
    t.start()
    time.sleep(0.05)
    return t


def settle(quiet=0.8, limit=8.0):
    """Until the box has heard nothing for a moment: a confirming read, a
    late fallback, whatever the last switch set going."""
    t0 = time.time()
    while time.time() - t0 < limit:
        last = BOX['calls'][-1][0] if BOX['calls'] else 0
        if time.time() - last >= quiet:
            return
        time.sleep(0.05)


def light_after(report, device='PIR-Test', limit=5.0):
    BOX['sets'] = []
    t0 = time.time()
    d.handle_zigbee(device, json.dumps(report).encode())
    while not BOX['sets'] and time.time() - t0 < limit:
        time.sleep(0.001)
    return (BOX['sets'][0][0] - t0) * 1000 if BOX['sets'] else None


plug()
for _name in ('PIR-Test', 'PIR-B'):
    d.store.upsert_device({'id': 'zigbee:' + _name, 'name': _name, 'source': 'zigbee', 'kind': 'sensor',
                           'exposes': {'occupancy': {}}})
    d.names[_name] = 'zigbee:' + _name


# -- the bridge's big answers are not read on the broker's own thread ---------
# All of them are retained, so they arrive again on every reconnect, and while
# the broker's thread is busy no report is heard and no Zigbee command leaves.
# Measured on 5.15.0: bridge/definitions (4.7 MB, read and thrown away) 137 ms;
# the coordinator's backup 20 ms; the network map 1,436 ms while a backup held
# the database, because its answer was written into the settings under the
# lock right there.
_defs = json.dumps({'clusters': {('c%d' % i): {'ID': i, 'attributes': {('a%d' % j): {'ID': j}
                                                                        for j in range(40)}}
                                 for i in range(3000)}}).encode()
_t0 = time.perf_counter()
d.handle('zigbee2mqtt/bridge/definitions', _defs)
_took = (time.perf_counter() - _t0) * 1000
check(_took < 20, 'the broker thread spent %.0f ms on bridge/definitions (%d KB), which nothing '
                  'reads' % (_took, len(_defs) // 1024))
_nodes = [{'ieeeAddr': '0x%016x' % i, 'friendlyName': 'D%d' % i,
           'type': 'Router' if i % 3 else 'EndDevice'} for i in range(60)]
_links = [{'source': {'ieeeAddr': '0x%016x' % i}, 'target': {'ieeeAddr': '0x%016x' % (i // 3)},
           'lqi': 100, 'depth': 1, 'relationship': 1} for i in range(1, 60)]
_map = json.dumps({'data': {'type': 'raw', 'value': {'nodes': _nodes, 'links': _links}},
                   'status': 'ok'}).encode()
_holder = busy_database(1.5)
_t0 = time.perf_counter()
d.handle('zigbee2mqtt/bridge/response/networkmap', _map)
_took = (time.perf_counter() - _t0) * 1000
_holder.join()
check(_took < 50, 'with a backup holding the database, the network map held the broker thread '
                  '%.0f ms' % _took)
_zip = json.dumps({'data': {'zip': base64.b64encode(os.urandom(2 * 1024 * 1024)).decode()},
                   'status': 'ok'}).encode()
_t0 = time.perf_counter()
d.handle('zigbee2mqtt/bridge/response/backup', _zip)
_took_backup = (time.perf_counter() - _t0) * 1000
check(_took_backup < 10, 'the coordinator backup was decoded and written on the broker thread '
                         '(%.0f ms)' % _took_backup)
check(getattr(d, 'bridge_settled', lambda t: True)(10.0), 'the bridge\'s answers were never acted on')
check(list(Path('/tmp/zigmon-lags-backups').glob('zigbee2mqtt-*.zip')),
      'the coordinator backup was handed over and then never written')
check(len(json.loads(d.store.get_meta('parents') or '{}')) >= 50,
      'the network map was handed over and then never kept')
print('the bridge\'s big answers leave the broker thread at once and are still acted on '
      '(network map under a busy database: %.1f ms)' % _took)

# -- a rule on a sensor group does not wait on the database ------------------
# A group re-states its own device row every time it moves, and that was a
# SELECT under the database lock on the rule worker: every light behind a group
# of PIRs waited for whatever held the lock. 1,485 ms behind a backup on 5.15.0,
# every time.
d.store.set_meta('sensor_groups', json.dumps([{'id': 'g1', 'name': 'Downstairs', 'key': 'occupancy',
                                               'mode': 'any',
                                               'members': ['zigbee:PIR-Test', 'zigbee:PIR-B'],
                                               'enabled': True}]))
d.store.set_meta('rules', json.dumps([
    {'id': 'g-on', 'device': 'grp:g1', 'key': 'occupancy', 'op': '==', 'value': 1,
     'plug': 'Light-Test', 'do': 'on', 'enabled': True, 'cooldown_s': 0},
    {'id': 'g-off', 'device': 'grp:g1', 'key': 'occupancy', 'op': '==', 'value': 0,
     'plug': 'Light-Test', 'do': 'off', 'enabled': True, 'cooldown_s': 0}]))
for _round in range(3):
    light_after({'occupancy': False})
    time.sleep(0.3)
    _holder = busy_database(1.5)
    _took = light_after({'occupancy': True})
    _holder.join()
    check(_took is not None and _took < 150,
          'a rule on a group of PIRs waited %s ms for the database' % (_took and round(_took)))
# ...and after a restore or a sweep of devices has emptied the rows held in
# memory, they are read back by themselves rather than by the next sensor
d.store._forget_device()
time.sleep(0.5)
light_after({'occupancy': False})
time.sleep(0.3)
_holder = busy_database(1.5)
_took = light_after({'occupancy': True})
_holder.join()
check(_took is not None and _took < 150,
      'after the devices were forgotten, a group rule waited %s ms for the database'
      % (_took and round(_took)))
d.store.set_meta('sensor_groups', json.dumps([]))
d.store.set_meta('rules', json.dumps([]))
print('a rule on a group of PIRs reaches its light with the database busy: %.0f ms' % _took)

# -- a box that does not answer over the broker is not waited on every time ---
# The answer to a command over MQTT is waited for two seconds before HTTP is
# tried. That was paid on EVERY command to a box whose RPC over MQTT does not
# answer, for as long as it stayed that way: 2,004 ms a light on 5.15.0.
d.store.set_meta('rules', json.dumps([
    {'id': 'm-on', 'device': 'zigbee:PIR-Test', 'key': 'occupancy', 'op': '==', 'value': 1,
     'plug': 'Light-Test', 'do': 'on', 'enabled': True, 'cooldown_s': 0},
    {'id': 'm-off', 'device': 'zigbee:PIR-Test', 'key': 'occupancy', 'op': '==', 'value': 0,
     'plug': 'Light-Test', 'do': 'off', 'enabled': True, 'cooldown_s': 0}]))
_p = plug(mqtt=True, mqtt_name='light-test')
_was_connected, _was_say = d.connected, d.say


class _Published(object):
    rc = 0


d.connected = True
d.say = lambda *a, **k: _Published()                     # out it goes; nothing ever answers
try:
    _first = light_after({'occupancy': False})           # this one finds out
    settle()
    _second = light_after({'occupancy': True})
    settle()
    check(_second is not None and _second < 300,
          'a box that stayed silent over MQTT made the next light wait %s ms again'
          % (_second and round(_second)))
    # ...and a box that says itself it is off the broker is not asked over it at all
    d._mqtt_road_off.clear() if hasattr(d, '_mqtt_road_off') else None
    _p.flat = dict(_p.flat or {}, **{'mqtt.connected': False})
    light_after({'occupancy': False})
    settle()
    _third = light_after({'occupancy': True})
    settle()
    check(_third is not None and _third < 300,
          'a box that says it is not on the broker was asked over it, and the light waited %s ms'
          % (_third and round(_third)))
finally:
    d.connected, d.say = _was_connected, _was_say
plug()
d.store.set_meta('rules', json.dumps([]))
print('a box silent over MQTT: the first command waits %.0f ms, the next %.0f ms; one off the '
      'broker by its own word: %.0f ms' % (_first or -1, _second, _third))

# -- a reading asked for before a switch does not undo it ---------------------
# Found while measuring the above: after the fallback to HTTP, the read that
# follows a switch had gone out while the command was still lost on the broker,
# found the relay as it was, and was written down as fresh once it came back -
# after the relay had moved. The house believed a light was on that had just
# been switched off, and the next rule asking for it on was skipped as "already
# on": a dark room until the next round of readings. What a switch says stands
# until a reading asked for after it.
_p = plug()
_asked = time.time()                                      # the reading goes out...
time.sleep(0.05)
d._plug_switched(_p, False, 'a test')                     # ...the relay is switched off...
d._record_plug(_p, {'id': 0, 'output': True, 'apower': 12.0}, {}, _asked)   # ...and it comes back
check(_p.output == 0, 'a reading asked for before the switch put the light back to "on" in the '
                      'house\'s mind, with the relay off')
_later = time.time() + 0.01                               # a reading asked for after it does count
d._record_plug(_p, {'id': 0, 'output': True, 'apower': 12.0}, {}, _later)
check(_p.output == 1, 'a reading asked for after the switch was not believed')
print('a reading asked for before a switch does not put the light back in the house\'s mind')

# -- "too many requests" to a reading is not a box gone missing ---------------
# Three readings answered 429 put a working box on the way to "lost contact":
# shown offline, and its next command given one short try instead of the
# patient ladder a command somebody is waiting on gets.
_p = plug()
_p.failures = 0
for _i in range(3):
    BOX['busy_times'] = 50                                # every try of this reading refused
    _p.backoff_until = 0
    zigmon.ShellyRPC._crowded.clear()
    d.poll_plug(_p, force=True)
check(_p.failures == 0, 'three readings answered "too many requests" counted as %d failure(s)'
      % _p.failures)
check(not _p.rpc().known_down, 'a box answering "too many requests" was treated as one that is off')
BOX['busy_times'] = 0
print('a box answering "too many requests" to a reading is busy, not gone')

# -- a reading's second request does not go out while somebody is switching --
# The check that a command is under way was made once, before the first request
# of a poll; the one after it goes out a second later, by when a person may well
# have pressed, and the box answers one of the two "too many requests".
_p = plug()
_p.device_status = None
_p.last_device_status = 0
_was_commanding = zigmon.ShellyRPC.commanding
BOX['calls'] = []
zigmon.ShellyRPC.commanding = classmethod(lambda cls, host, within: True)
try:
    d.poll_plug(_p, force=True)
finally:
    zigmon.ShellyRPC.commanding = _was_commanding
_asked = [m for _t, m in BOX['calls']]
check('Shelly.GetStatus' not in _asked[1:] and len(_asked) <= 1,
      'a reading sent %d request(s) to a box while it was being switched: %r' % (len(_asked), _asked))
print('a reading asks a box being switched once, not three times')

# -- the door of the API does not read the blocked list under the lock -------
# Every click, every press of a link and every text from the gateway is asked
# about the blocked list before anything else happens to it, and the list was
# read again from the table whenever it was two seconds old - 27,000 rows on
# this house, under the database lock - by whichever request came first.
d.store.blocked_until('8.8.8.8')                          # read once, as at the start
d.store._block_cache_at = 0                               # ...and changed since
_holder = busy_database(1.5)
_t0 = time.perf_counter()
_door = d.store.blocked_until('8.8.4.4', wait=False) if 'wait' in \
    d.store.blocked_until.__code__.co_varnames else d.store.blocked_until('8.8.4.4')
_took = (time.perf_counter() - _t0) * 1000
_holder.join()
check(_took < 50, 'a click at the door waited %.0f ms for the blocked list' % _took)
d.store.block('203.0.113.250', None, 'a test', auto=False)
_t0 = time.time()
while d.store.blocked_until('203.0.113.250', wait=False) is None and time.time() - _t0 < 3:
    time.sleep(0.01)
check(d.store.blocked_until('203.0.113.250', wait=False) is not None,
      'an address blocked a moment ago is still let in at the door')
d.store.unblock('203.0.113.250')
print('the door answers from the list in hand (%.1f ms with the database busy), and a new '
      'block reaches it' % _took)

# -- the half-minute chores are not done on the quarter-second beat ----------
# The beat finishes "off after fifteen seconds" and starts a schedule on its
# minute; the chores read the database (the alerts about the house, the digest,
# the blocks that ran out), and a backup holds it a second and a half.
_beats = []
_was_waiting = d.check_rule_waiting
d.check_rule_waiting = lambda: _beats.append(time.time())
_clock = threading.Thread(target=d.timer_loop, name='clock', daemon=True)
_clock.start()
time.sleep(0.6)
d._heat_at = 0                                            # the chores are due now
_holder = busy_database(1.5)
_beats[:] = []
time.sleep(1.6)
_holder.join()
_gaps = [b - a for a, b in zip(_beats, _beats[1:])] or [9.9]
check(max(_gaps) < 0.6, 'the quarter-second beat stood still %.2f s while the half-minute chores '
                        'waited on the database' % max(_gaps))
print('the quarter-second beat keeps its time while the chores wait on the database '
      '(longest gap %.2f s)' % max(_gaps))

# -- a rule that wants somebody home does not ask the controller again --------
# The fresh look at the Wi-Fi is there for "nobody home": somebody walks in and
# the sensor trips before the phone is seen. A rule that wants somebody HOME and
# already has that answer gains nothing from asking, and paid a TLS handshake
# and a request to the controller on nearly every firing.
_looked = []
_was_poll = d.wifi_poll_once
d.wifi_poll_once = lambda cfg, force=False: _looked.append(time.time())
_was_cfg, _was_state = d.wifi_config, d.presence_state
d.wifi_config = lambda: {'enabled': True, 'host': 'controller.test'}
d.wifi['checked'] = time.time() - 60
d.presence_state = lambda: {'known': True, 'anyone_home': True,
                            'people': [{'id': 'p1', 'name': 'A', 'home': True, 'enabled': True}]}
try:
    check(d.presence_allows({'when': 'home'}) is True, 'somebody is home and the rule was refused')
    check(not _looked, 'a rule wanting somebody home, with somebody home, asked the controller again')
    check(d.presence_allows({'when': 'person:p1:home'}) is True and not _looked,
          'a rule wanting one person home, who is, asked the controller again')
    # ...and "nobody home" still looks before it believes it
    d.presence_allows({'when': 'away'})
    check(_looked, 'a rule wanting nobody home no longer looks before it fires')
finally:
    d.wifi_poll_once, d.wifi_config, d.presence_state = _was_poll, _was_cfg, _was_state
print('a rule wanting somebody home, with somebody home, fires without asking the controller; '
      '"nobody home" still asks')

# -- a day average ten minutes old does not hold the rule worker -------------
d._avg24 = {('zigbee:PIR-Test', 'occupancy'): (0.5, time.time() - 700)}
_holder = busy_database(1.5)
_t0 = time.perf_counter()
_avg = d.avg24('zigbee:PIR-Test', 'occupancy')
_took = (time.perf_counter() - _t0) * 1000
_holder.join()
check(_took < 50 and _avg == 0.5, 'a stale day average was worked out again on the rule worker, '
                                  'under a busy database: %.0f ms' % _took)
print('a day average gone stale answers at once and is worked out again behind it')

# -- one status for everybody asking about the same moment -------------------
# Every open tab, the watch and the phone are woken by the same change and ask
# at once; each built its own status - a walk over every device and a third of
# a megabyte of JSON - in the milliseconds after the change that turned a
# light on.
check(hasattr(d, 'status_body'), 'there is no shared status to answer with')
_built = []
_was_status = d.status
d.status = lambda: (_built.append(1), time.sleep(0.05), _was_status())[2]
d.seq += 1
_askers = [threading.Thread(target=d.status_body) for _ in range(6)]
for _a in _askers:
    _a.start()
for _a in _askers:
    _a.join()
d.status = _was_status
check(len(_built) == 1, 'six pages asking about the same moment built the status %d times'
      % len(_built))
d.seq += 1
check(json.loads(d.status_body().decode())['ok'] is True, 'the shared status is not a status')
print('six pages woken by one change: the status is built once')

# -- a sequence step is not written to the database before it is taken -------
d.store.set_meta('scenes', json.dumps([]))
d.store.set_meta('sequences', json.dumps([{'id': 'sq1', 'name': 'Lamp', 'enabled': True,
                                           'steps': ['Light-Test|on', 'Light-Test|off']}]))
_holder = busy_database(1.5)
BOX['sets'] = []
_t0 = time.time()
threading.Thread(target=d.advance_sequence, args=('sq1', 'a test'), daemon=True).start()
while not BOX['sets'] and time.time() - _t0 < 4:
    time.sleep(0.001)
_took = (BOX['sets'][0][0] - _t0) * 1000 if BOX['sets'] else None
_holder.join()
check(_took is not None and _took < 200,
      'a sequence step waited %s ms to write down where it was' % (_took and round(_took)))
print('a sequence step switches first and writes down where it is behind (%.0f ms)' % _took)

d.store.flush(5.0)
zigmon.log_drain(3.0) if hasattr(zigmon, 'log_drain') else None
sys.stdout.flush()
os._exit(0)
