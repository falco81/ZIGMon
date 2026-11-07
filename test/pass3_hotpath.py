#!/usr/bin/env python3
"""The hot path, third pass: what a report still waited on between Zigbee2MQTT
and the light, with the database held by something slow.

    python3 test/pass3_hotpath.py < /dev/null          # the checks, about a minute
    ZIGMON_SRC=/path/to/old python3 test/pass3_hotpath.py   # against another zigmon.py

The first two passes took the database off the way of a report; what was left
were the copies in memory going cold and something on the way asking the
database again, behind whatever held it - a backup, a VACUUM, a sweep writing
thousands of rows of proxy_requests:

  * the device rows forgotten whole (an erase, a purge of stale devices)
    while a backup or a VACUUM held the database: emptied, and read back by
    a thread of their own that waited for the lock like anybody else. Every
    report then read its device's row on the broker's thread (its name, for
    an event it might have to say), a rule read its lamp's row for the words
    of its log line, and the Zigbee command read it for the topic: no report
    heard and no light for as long as the database was held
  * one row forgotten (a rename, a new description from the bridge): that
    lamp's next command read its row behind the database
  * a head saying its setpoint, with "put my setting back at once": the rooms
    were worked out on the broker's thread - the device list with them, read
    from the database after any change to any device row
  * a window that opens shut its room's heads only at the next half-minute
    round of the heating: up to thirty seconds of heating the garden
  * a one-tap link: the press's count was written under the database lock
    before the watch was answered

Each check fails on 5.46.0. The numbers at the end are the report -> command
times (p50/p95/p99) with a sweep, a backup and charts running together.

Ports 19600 (a Shelly) and 19601 (the API).
"""
import collections
import json
import os
import random
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, os.environ.get('ZIGMON_SRC') or str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

BOXPORT, APIPORT = 19600, 19601
W = Path(tempfile.mkdtemp(prefix='zigmon-pass3hp-'))
bad = []


def check(ok, what):
    print('  %s %s' % ('ok  ' if ok else 'FAILED:', what))
    if not ok:
        bad.append(what)


# ---- what went out, and when ---------------------------------------------------
OUT = collections.deque(maxlen=5000)          # (perf_counter, what, payload)
OUT_CV = threading.Condition()


def went(what, payload=None):
    with OUT_CV:
        OUT.append((time.perf_counter(), what, payload))
        OUT_CV.notify_all()


def wait_out(pred, since, limit):
    """The first thing that went out after `since` matching pred: its time, or None."""
    deadline = time.perf_counter() + limit
    with OUT_CV:
        while True:
            for at, what, payload in list(OUT):
                if at >= since and pred(what, payload):
                    return at
            left = deadline - time.perf_counter()
            if left <= 0:
                return None
            OUT_CV.wait(left)


BOX = {str(i): False for i in range(4)}


class Box(BaseHTTPRequestHandler):
    """A Shelly that answers at once and keeps the connection open."""
    protocol_version = 'HTTP/1.1'
    wbufsize = 65536

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        req = json.loads(body or b'{}')
        method, params = req.get('method'), req.get('params') or {}
        sid = str(params.get('id', 0))
        if method == 'Switch.Set':
            went('box:%s' % sid, bool(params.get('on')))
            out = {'was_on': BOX[sid]}
            BOX[sid] = bool(params.get('on'))
        elif method == 'Switch.Toggle':
            went('box:%s' % sid, 'toggle')
            out = {'was_on': BOX[sid]}
            BOX[sid] = not BOX[sid]
        elif method in ('Shelly.GetStatus', 'Switch.GetStatus'):
            out = {'switch:%s' % k: {'id': int(k), 'output': v, 'apower': 1.0, 'voltage': 230.0,
                                     'aenergy': {'total': 1.0}} for k, v in BOX.items()}
            if method == 'Switch.GetStatus':
                out = out['switch:%s' % sid]
        else:
            out = {'id': 'shellyplug-pass3', 'model': 'S3PL-00112EU', 'gen': 3, 'ver': '1.7.1'}
        raw = json.dumps({'id': req.get('id'), 'result': out}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


# ---- paho's network thread -------------------------------------------------------
class Info(object):
    rc = 0
    mid = 1

    def wait_for_publish(self, *a):
        return True

    def is_published(self):
        return True


class Msg(object):
    def __init__(self, topic, payload):
        self.topic, self.payload, self.retain = topic, payload, False


class FakePaho(object):
    """One thread, as loop_start() has it: a message read and handled, then
    whatever was published meanwhile written."""

    def __init__(self):
        self.cv = threading.Condition()
        self.inq = collections.deque()
        self.held = {}                      # tag -> ms its message held the thread
        threading.Thread(target=self.loop, name='paho', daemon=True).start()

    def publish(self, topic, payload=None, qos=0, retain=False):
        try:
            body = json.loads(payload)
        except (TypeError, ValueError):
            body = payload
        went('mqtt:' + topic, body)
        return Info()

    def subscribe(self, *a, **k):
        return (0, 1)

    def message_callback_add(self, *a, **k):
        pass

    def deliver(self, topic, payload, tag=None):
        with self.cv:
            self.inq.append((topic, json.dumps(payload).encode(), tag))
            self.cv.notify()

    def loop(self):
        while True:
            with self.cv:
                while not self.inq:
                    self.cv.wait()
                topic, payload, tag = self.inq.popleft()
            t0 = time.perf_counter()
            try:
                d._on_message(None, None, Msg(topic, payload))
            except Exception as e:
                print('  on_message raised: %r' % e)
            if tag:
                self.held[tag] = (time.perf_counter() - t0) * 1000


# ---- the house -------------------------------------------------------------------
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': APIPORT, 'token_file': str(W / 'api-token'),
                      'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': str(W / 'z.log'),
                      'state_dir': str(W / 'state'), 'log_to_journal': False, 'weather': False,
                      'plug_timeout': 3.0, 'binding_debounce_ms': 0, 'heating_enforce': 'now',
                      'tap_mode': 'both', 'sms_enabled': False})
(W / 'state').mkdir()
zigmon.open_log()
zigmon.start_log_writer()
BASE = zigmon.CONFIG['base_topic'].rstrip('/')

srv = ThreadingHTTPServer(('127.0.0.1', BOXPORT), Box)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()

d = zigmon.Daemon()
d.backup_dir = lambda: W / 'backups'
d.store.set_meta('managed', json.dumps({'plugs': [
    {'name': 'Light-A', 'host': '127.0.0.1:%d' % BOXPORT, 'switch_id': 0, 'kind': 'plug', 'host_state': 'enabled'},
    {'name': 'Light-B', 'host': '127.0.0.1:%d' % BOXPORT, 'switch_id': 1, 'kind': 'plug', 'host_state': 'enabled'},
    {'name': 'Light-T', 'host': '127.0.0.1:%d' % BOXPORT, 'switch_id': 2, 'kind': 'plug', 'host_state': 'enabled'},
], 'sensors': []}))
d.reload_devices()
paho = FakePaho()
d.client, d.connected = paho, True
d._verify_zigbee_set = lambda *a, **k: None

TRV_EXPOSES = {'current_heating_setpoint': {'type': 'numeric', 'access': 7},
               'system_mode': {'type': 'enum', 'values': ['off', 'heat'], 'access': 7},
               'local_temperature': {'type': 'numeric', 'access': 1}}
DEVICES = [('PIR-A', 'sensor', {'occupancy': {}}), ('PIR-Z', 'sensor', {'occupancy': {}}),
           ('Btn', 'button', {'action': {}}), ('Lamp-0', 'Router', {'state': {'access': 7}}),
           ('TRV', 'TRV', TRV_EXPOSES), ('Win', 'sensor', {'contact': {}})]
DEVICES += [('TH-%02d' % i, 'sensor', {'temperature': {}, 'humidity': {}}) for i in range(40)]
for _name, _kind, _exposes in DEVICES:
    d.store.upsert_device({'id': 'zigbee:' + _name, 'name': _name, 'source': 'zigbee', 'kind': _kind,
                           'exposes': _exposes})
    d.names[_name] = 'zigbee:' + _name


def rule(rid, dev, key, value, plug, do):
    return {'id': rid, 'device': 'zigbee:' + dev, 'key': key, 'op': '==', 'value': value, 'plug': plug,
            'do': do, 'enabled': True, 'cooldown_s': 0}


d.store.set_meta('rules', json.dumps([
    rule('a-on', 'PIR-A', 'occupancy', 1, 'Light-A', 'on'), rule('a-off', 'PIR-A', 'occupancy', 0, 'Light-A', 'off'),
    rule('z-on', 'PIR-Z', 'occupancy', 1, 'zb:zigbee:Lamp-0:state', 'on'),
    rule('z-off', 'PIR-Z', 'occupancy', 0, 'zb:zigbee:Lamp-0:state', 'off')]))
d.store.set_meta('bindings', json.dumps([{'device': 'zigbee:Btn', 'action': 'single', 'plug': 'Light-B',
                                          'do': 'toggle', 'enabled': True}]))
d.save_rooms([{'id': 'liv', 'name': 'Living'}])
d.save_room_map({'zigbee:TRV': 'liv', 'zigbee:Win': 'liv'})
d.save_heating({'enabled': True, 'rooms': {'liv': {'mode': 'plan', 'comfort_c': 21, 'eco_c': 18, 'night_c': 17,
                                                   'plan': [], 'window_stop': True}}})
d.save_taps([{'name': 'Lamp', 'target': 'Light-T', 'do': 'toggle'}])
TAP = d.taps()[0]['token']

# a database with something in it, so a backup and a chart take their while
with d.store.lock:
    d.store.db.executemany('INSERT OR REPLACE INTO samples (ts,device,key,value) VALUES (?,?,?,?)',
                           [(int(time.time()) - 300000 + i, 'zigbee:TH-%02d' % (i % 40), 'temperature',
                             20.0 + (i % 97) / 10.0) for i in range(150000)])

threading.Thread(target=d.rule_worker, name='rules', daemon=True).start()
threading.Thread(target=d.rule_worker, args=(True,), name='rules-presence', daemon=True).start()
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)
TOKEN = Path(zigmon.CONFIG['token_file']).read_text().strip()
d.gc_settle()

FLIP = collections.defaultdict(bool)


def report(name, payload, tag=None):
    paho.deliver('%s/%s' % (BASE, name), payload, tag)


def pir_lamp(limit=3.0, tag=None):
    """PIR-Z -> Lamp-0 over Zigbee: ms from the report to the publish, or None."""
    FLIP['Z'] = not FLIP['Z']
    want = 'ON' if FLIP['Z'] else 'OFF'
    t0 = time.perf_counter()
    report('PIR-Z', {'occupancy': FLIP['Z']}, tag)
    at = wait_out(lambda w, p: w == 'mqtt:%s/Lamp-0/set' % BASE and isinstance(p, dict)
                  and p.get('state') == want, t0, limit)
    return None if at is None else (at - t0) * 1000


def pir_box(limit=3.0):
    FLIP['A'] = not FLIP['A']
    t0 = time.perf_counter()
    report('PIR-A', {'occupancy': FLIP['A']})
    at = wait_out(lambda w, p: w == 'box:0' and p == FLIP['A'], t0, limit)
    return None if at is None else (at - t0) * 1000


def press(limit=3.0):
    t0 = time.perf_counter()
    report('Btn', {'action': 'single'})
    at = wait_out(lambda w, p: w == 'box:1', t0, limit)
    return None if at is None else (at - t0) * 1000


def tap(limit=10):
    req = urllib.request.Request('http://127.0.0.1:%d/api/tap' % APIPORT, data=b'{}',
                                 headers={'X-Zigmon-Tap': TAP, 'Content-Type': 'application/json',
                                          'X-Zigmon-Token': TOKEN})
    t0 = time.perf_counter()
    answer = json.loads(urllib.request.urlopen(req, timeout=limit).read())
    answered = (time.perf_counter() - t0) * 1000
    at = wait_out(lambda w, p: w == 'box:2', t0, 1.0)
    return answered, (None if at is None else (at - t0) * 1000), answer


def settle(n=3):
    for _ in range(n):
        pir_lamp()
        pir_box()
        press()
        time.sleep(0.05)
    d.store._wq_idle.wait(5)              # the writer caught up: nothing of the last round in its hands
    time.sleep(0.3)


HOLD_S = 1.5


def hold_db(seconds=HOLD_S, before=None):
    """Something slow holding the database (a VACUUM, a backup's copy), on a
    thread of its own; `before` is done on that thread just ahead of it."""
    started = threading.Event()

    def run():
        if before:
            before()
        with d.store.lock:
            started.set()
            time.sleep(seconds)
    t = threading.Thread(target=run, name='slow-db', daemon=True)
    t.start()
    started.wait(10)
    time.sleep(0.05)
    return t


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else float('nan')


def stats(xs):
    got = [x for x in xs if x is not None]
    if not got:
        return {'n': 0, 'lost': len(xs)}
    return {'n': len(got), 'lost': len(xs) - len(got), 'p50': round(pct(got, .5), 2),
            'p95': round(pct(got, .95), 2), 'p99': round(pct(got, .99), 2), 'max': round(max(got), 2)}


try:
    settle()

    print('the device rows forgotten whole (an erase) while a backup holds the database %.1f s' % HOLD_S)
    t = hold_db()
    eraser = threading.Thread(target=d.store._forget_device, name='erase', daemon=True)
    eraser.start()
    time.sleep(0.05)
    ms = pir_lamp(tag='cold-pir')
    report('TH-03', {'temperature': 22.5, 'humidity': 40}, tag='cold-th')
    time.sleep(0.2)
    held_pir, held_th = paho.held.get('cold-pir'), paho.held.get('cold-th')
    t.join()
    eraser.join()
    print('    PIR -> lamp %s ms; the broker thread held %s / %s ms' % (
        None if ms is None else round(ms, 1), held_pir and round(held_pir, 1), held_th and round(held_th, 1)))
    check(ms is not None and ms < 300, 'a PIR reached its lamp in %s ms while the database was held (limit 300)'
          % (None if ms is None else round(ms)))
    check(held_th is not None and held_th < 300, 'a thermometer\'s report held the broker thread %s ms (limit 300)'
          % (held_th and round(held_th)))
    check(d.store.device('zigbee:Lamp-0') is not None and d.store.device('zigbee:Nobody') is None,
          'the rows read back are the rows there are')

    print('one row changed (a lamp renamed), then the database held %.1f s' % HOLD_S)
    settle(1)
    d.store.set_alias('zigbee:Lamp-0', 'Kitchen lamp')
    t = hold_db()
    ms = pir_lamp()
    t.join()
    print('    PIR -> lamp %s ms' % (None if ms is None else round(ms, 1)))
    check(ms is not None and ms < 300, 'a renamed lamp\'s next command went out %s ms after its PIR (limit 300)'
          % (None if ms is None else round(ms)))
    check((d.store.device('zigbee:Lamp-0') or {}).get('alias') == 'Kitchen lamp',
          'the new name is the one in memory: %r' % (d.store.device('zigbee:Lamp-0') or {}).get('alias'))
    before = d.store.upsert_device({'id': 'zigbee:Lamp-0', 'name': 'Lamp-0', 'source': 'zigbee', 'kind': 'Router',
                                    'description': 'a new word from the bridge', 'exposes': {'state': {'access': 7}}})
    check((d.store.device('zigbee:Lamp-0') or {}).get('description') == 'a new word from the bridge',
          'an upsert is in memory at once (%s)' % before)
    d.store.upsert_device({'id': 'zigbee:New-1', 'name': 'New-1', 'source': 'zigbee', 'kind': 'sensor',
                           'exposes': {}})
    check((d.store.device('zigbee:New-1') or {}).get('name') == 'New-1', 'a new device is in memory at once')
    d.store.mark_removed('zigbee:New-1')
    check((d.store.device('zigbee:New-1') or {}).get('removed') == 1, 'a device marked removed is so in memory')

    print('a head says its setpoint (put it back at once), the device list cold, the database held %.1f s' % HOLD_S)
    settle(1)
    report('TRV', {'current_heating_setpoint': 18, 'system_mode': 'heat', 'local_temperature': 20})
    time.sleep(0.5)
    d.store.set_alias('zigbee:TH-00', 'Hall')            # any row changed: the list is read again
    t = hold_db()
    t0 = time.perf_counter()
    report('TRV', {'current_heating_setpoint': 25, 'system_mode': 'heat', 'local_temperature': 20}, tag='trv')
    ms = pir_lamp()
    time.sleep(0.1)
    held = paho.held.get('trv')
    t.join()
    print('    the broker thread held %s ms by the head; PIR -> lamp behind it %s ms'
          % (held and round(held, 1), None if ms is None else round(ms, 1)))
    check(held is not None and held < 300, 'a head\'s report held the broker thread %s ms (limit 300)'
          % (held and round(held)))
    check(ms is not None and ms < 300, 'a PIR behind it reached its lamp in %s ms (limit 300)'
          % (None if ms is None else round(ms)))
    at = wait_out(lambda w, p: w == 'mqtt:%s/TRV/set' % BASE and isinstance(p, dict)
                  and p.get('current_heating_setpoint') == 18, t0, 5.0)
    check(at is not None, 'the head turned to 25 by hand was put back to 18 at once')

    print('a window opens')
    settle(1)
    t0 = time.perf_counter()
    report('Win', {'contact': False})
    at = wait_out(lambda w, p: w == 'mqtt:%s/TRV/set' % BASE and isinstance(p, dict)
                  and p.get('system_mode') == 'off', t0, 3.0)
    print('    the head shut %s ms after' % (None if at is None else round((at - t0) * 1000)))
    check(at is not None, 'a window opened and its room\'s head was shut within 3 s (it waited for the '
          'half-minute round)')
    report('TRV', {'system_mode': 'off', 'current_heating_setpoint': 18})
    time.sleep(0.3)
    t0 = time.perf_counter()
    report('Win', {'contact': True})
    at = wait_out(lambda w, p: w == 'mqtt:%s/TRV/set' % BASE and isinstance(p, dict)
                  and p.get('system_mode') == 'heat', t0, 3.0)
    check(at is not None, 'the window shut again and the head was opened within 3 s')
    t0 = time.perf_counter()
    report('Win', {'contact': True, 'battery': 90})
    time.sleep(0.5)
    check(wait_out(lambda w, p: w == 'mqtt:%s/TRV/set' % BASE, t0, 0.01) is None,
          'a window that says it is still shut tells the head nothing')

    print('a one-tap link pressed while the database is held %.1f s' % HOLD_S)
    tap()
    t = hold_db()
    answered, sent, answer = tap()
    t.join()
    print('    answered in %d ms, the socket told %s ms after the press: %s'
          % (answered, None if sent is None else round(sent, 1), answer.get('message')))
    check(answer.get('ok') and sent is not None and sent < 300,
          'the tap reached its socket in %s ms (limit 300)' % (None if sent is None else round(sent)))
    check(answered < 500, 'the tap was answered %d ms after the press (limit 500)' % answered)
    time.sleep(0.5)
    check((next(x for x in d.taps() if x['token'] == TAP).get('uses') or 0) >= 2, 'the presses are counted')

    print('report -> command with a sweep, a backup and charts running')
    stop = threading.Event()

    def sweep():
        k = 0
        while not stop.is_set():
            k += 1
            now = int(time.time())
            rows = [(now, 'p3-%d-%d-%d' % (k, j, random.random() * 1e9), 'tap', '198.51.100.%d' % (j % 200),
                     'GET', '/x/%d' % j, 404, 'h', 'curl', '{}', '', '') for j in range(4000)]
            d.store.keep_proxy_requests(rows)
            stop.wait(0.05)

    def backup():
        while not stop.is_set():
            try:
                d.db_backup_now()
            except Exception as e:
                print('  backup: %s' % e)
            shutil.rmtree(str(W / 'backups'), ignore_errors=True)
            stop.wait(0.3)

    def charts():
        while not stop.is_set():
            d.store.history('zigbee:TH-%02d' % random.randint(0, 39), ['temperature'], 7 * 86400, 600)
            stop.wait(0.05)

    def chatter():
        i = 0
        while not stop.is_set():
            i += 1
            report('TH-%02d' % (i % 40), {'temperature': 20 + (i % 50) / 10.0, 'humidity': 40 + i % 7,
                                          'battery': 90, 'linkquality': 100 + i % 30})
            stop.wait(0.01)
    loads = [threading.Thread(target=f, name='load-' + f.__name__, daemon=True)
             for f in (sweep, backup, charts, charts, chatter)]
    for x in loads:
        x.start()
    time.sleep(0.5)
    got = {'PIR -> Zigbee lamp': [], 'PIR -> Shelly HTTP': [], 'button -> Shelly': []}
    t_end = time.time() + 10
    while time.time() < t_end:
        got['PIR -> Zigbee lamp'].append(pir_lamp())
        got['PIR -> Shelly HTTP'].append(pir_box())
        got['button -> Shelly'].append(press())
        time.sleep(0.03)
    stop.set()
    for x in loads:
        x.join(30)
    for road, xs in got.items():
        s = stats(xs)
        print('    %-22s %s' % (road, s))
        # a machine shared with other test runs: the p99 is a hiccup of its
        # scheduler as often as anything here - p95 under 15, p99 under 40
        check(not s['lost'] and s.get('p95', 1e9) < 15 and s.get('p99', 1e9) < 40,
              '%s under load: p95 %s / p99 %s ms (limits 15 / 40)' % (road, s.get('p95'), s.get('p99')))
finally:
    srv.shutdown()
    srv.server_close()
    api.stop()
    shutil.rmtree(str(W), ignore_errors=True)

if bad:
    print('%d check(s) failed' % len(bad))
    sys.exit(1)
print('all pass3_hotpath checks passed')
