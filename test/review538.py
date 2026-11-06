#!/usr/bin/env python3
"""5.38: a sensor's report reaches its light at once, whatever else the house
is doing. A stopwatch on the whole real path, under load.

    python3 test/review538.py                    # the checks, about a minute
    ZIGMON_BENCH=1 python3 test/review538.py     # the stopwatch, load by load
    ZIGMON_BENCH=1 ZIGMON_BENCH_S=30 ZIGMON_BENCH_WHY=1 python3 test/review538.py

The real Daemon in this process: a broker thread of its own delivering the
messages as paho does (one thread, in order), the two rule workers, the
quarter-second clock, the plug poll, the alerts, the API on a port of its own
with pages open on it. The switching goes to a fake Shelly over HTTP and to a
Zigbee lamp over a fake MQTT client; the alerts to a fake ntfy (which is also
the proxy in front of the web). Meanwhile, as asked: a backup of the
database, a VACUUM, five hundred reports a second from other sensors, pages
asking for the status and waiting on it, a socket that takes every request
and never answers, and the chores of 5.30-5.37 (ACME, the certificate on the
server in front, the updates of the system, the backups to other machines,
maintenance) with every look over the network and at root made slow.

Measured from the moment a report is handed to the broker thread to the
moment the box (or the lamp, or ntfy) is told: p50, p99 and the worst.

Each of the four things mended in 5.38 is checked here and fails on 5.37.0:
  - erasing the history, the events or what is left of devices that are gone
    held every report and press behind its VACUUM (1.9 s of a 2 s one);
  - a rule on trial held the rule worker - and every rule behind it - while
    its import was being written down behind a backup (1.35 s of 1.5 s);
  - a socket that does not answer, asked again and again, queued every
    command for when it came back (49 after 12 s at four a second), and past
    200 of them every scene in the house was refused;
  - an alert with the proxy on for alerts asked DNS first, every time, on the
    one thread all alerts go out on (the whole resolver timeout per alert).
The rest - every road to a light with the database held, and the whole path
under all the load at once - passed on 5.37.0 already and is kept that way.
"""
import gc
import json
import os
import queue
import shutil
import socket
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

BOXPORT, DEADPORT, APIPORT, NTFYPORT = 19700, 19701, 19702, 19703
W = Path(tempfile.mkdtemp(prefix='zigmon-review538-'))
BENCH = bool(os.environ.get('ZIGMON_BENCH'))
WHY = bool(os.environ.get('ZIGMON_BENCH_WHY'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


# ---- the house around the daemon ----------------------------------------------
BOX = {'output': False, 'polls': 0}
SETS = queue.Queue()          # (when, on) for every switch command the box is given
ALERTS = queue.Queue()        # (when, path, body) for every alert that arrives
ZB = queue.Queue()            # (when, payload) for every command to the Zigbee lamp


class Box(BaseHTTPRequestHandler):
    """A Shelly that answers at once."""
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        method, params = body.get('method'), body.get('params') or {}
        if method == 'Switch.Set':
            SETS.put((time.perf_counter(), bool(params.get('on'))))
            was, BOX['output'] = BOX['output'], bool(params.get('on'))
            out = {'was_on': was}
        elif method == 'Switch.Toggle':
            was, BOX['output'] = BOX['output'], not BOX['output']
            SETS.put((time.perf_counter(), BOX['output']))
            out = {'was_on': was}
        elif method in ('Shelly.GetStatus', 'Switch.GetStatus'):
            BOX['polls'] += 1
            out = {'switch:0': {'id': 0, 'output': BOX['output'], 'apower': 12.0, 'voltage': 231.0,
                                'aenergy': {'total': 1.0}}}
            if method == 'Switch.GetStatus':
                out = out['switch:0']
        elif method == 'Shelly.GetDeviceInfo':
            out = {'id': 'shellyplug-bench', 'model': 'S3PL-00112EU', 'gen': 3, 'ver': '1.7.1'}
        else:
            out = {}
        raw = json.dumps({'id': body.get('id'), 'result': out}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class Ntfy(BaseHTTPRequestHandler):
    """ntfy, and the proxy in front of the web: whatever comes is an alert."""

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        ALERTS.put((time.perf_counter(), self.path, body))
        self.send_response(200)
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'{}')


class Info:
    rc = 0
    mid = 1

    def wait_for_publish(self, *a):
        return True

    def is_published(self):
        return True


class Client:
    """The broker, as far as publishing goes."""

    def publish(self, topic, payload=None, qos=0, retain=False):
        if topic.endswith('/Lamp-Bench/set'):
            ZB.put((time.perf_counter(), payload))
        return Info()

    def subscribe(self, *a, **k):
        return (0, 1)


class Msg:
    def __init__(self, topic, payload, retain=False):
        self.topic, self.payload, self.retain = topic, payload, retain


servers = []
for port, handler in ((BOXPORT, Box), (NTFYPORT, Ntfy)):
    srv = ThreadingHTTPServer(('127.0.0.1', port), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    servers.append(srv)
# a socket that is plugged in and dead: the kernel takes the connection and
# nothing ever answers
dead = socket.socket()
dead.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
dead.bind(('127.0.0.1', DEADPORT))
dead.listen(200)

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': APIPORT, 'token_file': str(W / 'api-token'),
                      'pin': '1234', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': str(W / 'z.log'),
                      'state_dir': str(W / 'state'), 'log_to_journal': False, 'weather': False,
                      'plug_timeout': 3.0, 'notify_ntfy': 'http://127.0.0.1:%d/house' % NTFYPORT})
(W / 'state').mkdir()
zigmon.open_log()
zigmon.start_log_writer()
BASE = zigmon.CONFIG['base_topic'].rstrip('/')

d = zigmon.Daemon()
d.backup_dir = lambda: W / 'backups'
d.store.set_meta('managed', json.dumps({'plugs': [
    {'name': 'Light-Bench', 'host': '127.0.0.1:%d' % BOXPORT, 'switch_id': 0, 'kind': 'plug',
     'host_state': 'enabled'},
    {'name': 'Dead-Bench', 'host': '127.0.0.1:%d' % DEADPORT, 'switch_id': 0, 'kind': 'plug',
     'host_state': 'enabled'}], 'sensors': []}))
d.reload_devices()
d.client, d.connected = Client(), True
d._verify_zigbee_set = lambda *a, **k: None

# the broker's one thread: everything paho hands over, in order
WIRE = queue.Queue()
BUSY = {'broker': None}
HELD = []                     # how long the broker's thread was held by each message, ms


def broker():
    while True:
        item = WIRE.get()
        if item is None:
            return
        topic, payload = item
        t0 = time.perf_counter()
        BUSY['broker'] = t0
        d._on_message(None, None, Msg(topic, payload))
        BUSY['broker'] = None
        HELD.append((time.perf_counter() - t0) * 1000)
        if len(HELD) > 100000:
            del HELD[:50000]


threading.Thread(target=broker, name='broker', daemon=True).start()
threading.Thread(target=d.rule_worker, name='rules', daemon=True).start()
threading.Thread(target=d.rule_worker, args=(True,), name='rules-presence', daemon=True).start()
threading.Thread(target=d.timer_loop, name='timers', daemon=True).start()
threading.Thread(target=d.notify_loop, name='notify', daemon=True).start()
threading.Thread(target=d.plug_loop, name='plugs', daemon=True).start()

for _name, _kind, _exposes in (('PIR-Bench', 'sensor', {'occupancy': {}}),
                               ('PIR-Alarm', 'sensor', {'occupancy': {}}),
                               ('Btn-Bench', 'button', {'action': {}}),
                               ('Lamp-Bench', 'Router', {'state': {}})):
    d.store.upsert_device({'id': 'zigbee:' + _name, 'name': _name, 'source': 'zigbee', 'kind': _kind,
                           'exposes': _exposes})
    d.names[_name] = 'zigbee:' + _name
OTHERS = ['TH-%02d' % i for i in range(50)]
for _name in OTHERS:
    d.store.upsert_device({'id': 'zigbee:' + _name, 'name': _name, 'source': 'zigbee', 'kind': 'sensor',
                           'exposes': {'temperature': {}, 'humidity': {}}})
    d.names[_name] = 'zigbee:' + _name
d.store.set_meta('rules', json.dumps([
    {'id': 'b-on', 'device': 'zigbee:PIR-Bench', 'key': 'occupancy', 'op': '==', 'value': 1,
     'plug': 'Light-Bench', 'do': 'on', 'enabled': True, 'cooldown_s': 0},
    {'id': 'b-off', 'device': 'zigbee:PIR-Bench', 'key': 'occupancy', 'op': '==', 'value': 0,
     'plug': 'Light-Bench', 'do': 'off', 'enabled': True, 'cooldown_s': 0},
    {'id': 'b-zb', 'device': 'zigbee:PIR-Bench', 'key': 'occupancy', 'op': '==', 'value': 1,
     'plug': 'zb:zigbee:Lamp-Bench:state', 'do': 'toggle', 'enabled': True, 'cooldown_s': 0},
    {'id': 'b-alert', 'device': 'zigbee:PIR-Alarm', 'key': 'occupancy', 'op': '==', 'value': 1,
     'plug': 'notify', 'do': 'on', 'enabled': True, 'cooldown_s': 0},
    # the same report also goes to a socket that is dead
    {'id': 'b-dead', 'device': 'zigbee:PIR-Bench', 'key': 'occupancy', 'op': '==', 'value': 1,
     'plug': 'Dead-Bench', 'do': 'on', 'enabled': True, 'cooldown_s': 0},
]))
d.store.set_meta('bindings', json.dumps([{'device': 'zigbee:Btn-Bench', 'action': 'single', 'plug': 'Light-Bench',
                                          'do': 'toggle', 'enabled': True}]))
d.store.set_meta('scenes', json.dumps([{'id': 'sc-bench', 'name': 'BenchScene', 'enabled': True,
                                        'actions': [{'target': 'Light-Bench', 'do': 'on'}]}]))
d.store.set_meta('taps', json.dumps([{'id': 't-bench', 'name': 'BenchTap', 'target': 'Light-Bench', 'do': 'on',
                                      'enabled': True, 'token': 'tok-bench-538'}]))

# a database with something in it, so a backup and a VACUUM take their while
with d.store.lock:
    d.store.db.executemany('INSERT OR REPLACE INTO samples (ts,device,key,value) VALUES (?,?,?,?)',
                           [(1700000000 + i, 'zigbee:TH-%02d' % (i % 50), 'temperature', 20.0 + (i % 97) / 10.0)
                            for i in range(400000)])
    d.store.db.executemany('INSERT INTO events (ts,device,kind,level,detail) VALUES (?,?,?,?,?)',
                           [(1700000000 + i, None, 'control', 'info', 'filler %d' % i) for i in range(50000)])
    d.store.db.commit()

api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)
TOKEN = Path(zigmon.CONFIG['token_file']).read_text().strip()
d.account_add('bench-op', 'admin', 'bench pass 538', must_change=False, quiet=True)
SESSION = d.login('bench-op', 'bench pass 538', '192.0.2.38')[0]['token']


def ask(path, body=None, timeout=30):
    req = urllib.request.Request('http://127.0.0.1:%d/%s' % (APIPORT, path),
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'X-Zigmon-Token': TOKEN, 'Content-Type': 'application/json',
                                          'X-Zigmon-Session': SESSION})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


# ---- who on the way to a light took the database lock, and waited for it ------
HOT = ('broker', 'rules', 'rules-presence', 'timers', 'binding', 'binding-zb', 'presses')


class SpyLock(object):
    def __init__(self, real):
        self.real = real
        self.taken = {}

    def acquire(self, blocking=True, timeout=-1):
        name = threading.current_thread().name
        if name not in HOT:
            return self.real.acquire(blocking, timeout)
        t0 = time.perf_counter()
        got = self.real.acquire(blocking, timeout)
        waited = (time.perf_counter() - t0) * 1000
        stack = traceback.extract_stack()[:-1]
        key = name + ': ' + ' <- '.join('%s:%d %s' % (Path(f.filename).name, f.lineno, f.name)
                                        for f in stack[::-1][:5] if 'review538' not in f.filename)
        n, worst = self.taken.get(key, (0, 0.0))
        self.taken[key] = (n + 1, max(worst, waited))
        return got

    def release(self):
        return self.real.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *a):
        self.release()

    def __getattr__(self, name):
        return getattr(self.real, name)


d.store.lock = SpyLock(d.store.lock)
d.gc_settle()                                   # as run() does a minute in
GC = {}
_gc_t = {}


def _gc_watch(phase, info):
    if phase == 'start':
        _gc_t['t'] = time.perf_counter()
        return
    ms = (time.perf_counter() - _gc_t.get('t', time.perf_counter())) * 1000
    n, worst = GC.get(info.get('generation'), (0, 0.0))
    GC[info.get('generation')] = (n + 1, max(worst, ms))


gc.callbacks.append(_gc_watch)

# ---- where the hot threads were while a probe was late (ZIGMON_BENCH_WHY) ------
SAMPLES = []
SLOW = []
sampling = threading.Event()


def sampler():
    while True:
        sampling.wait()
        names = {t.ident: t.name for t in threading.enumerate()}
        now = time.perf_counter()
        for ident, frame in sys._current_frames().items():
            if names.get(ident) in HOT:
                stack = traceback.extract_stack(frame)
                SAMPLES.append((now, names.get(ident),
                                ['%s:%d %s' % (Path(f.filename).name, f.lineno, f.name) for f in stack[-6:]]))
        if len(SAMPLES) > 200000:
            del SAMPLES[:100000]
        time.sleep(0.002)


threading.Thread(target=sampler, name='sampler', daemon=True).start()


def where_slow(window=20):
    seen = {}
    for t0, at, _ms in SLOW[-window:]:
        for now, name, where in SAMPLES:
            if t0 <= now <= at:
                key = (name, where[-1], where[-2] if len(where) > 1 else '')
                seen[key] = seen.get(key, 0) + 1
    return sorted(seen.items(), key=lambda kv: -kv[1])[:12]


# ---- the probes ------------------------------------------------------------------
def drain(q):
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return


def probe(occupied, limit=3.0):
    """One PIR report through the broker to the box: ms, or None if never."""
    drain(SETS)
    t0 = time.perf_counter()
    WIRE.put((BASE + '/PIR-Bench', json.dumps({'occupancy': occupied, 'battery': 90}).encode()))
    try:
        while True:
            at, on = SETS.get(timeout=limit)
            if on == occupied:
                ms = (at - t0) * 1000
                if ms > 40:
                    SLOW.append((t0, at, ms))
                return ms
    except queue.Empty:
        if WHY:
            p = d.plugs['Light-Bench']
            print('  LOST: wanted %s; plug output %r inflight %r wanted %r; box %r; rules %d; wire %d; rt %r'
                  % (occupied, p.output, getattr(p, 'inflight', None), getattr(p, 'wanted', None),
                     BOX['output'], len(d._rule_queue), WIRE.qsize(), d.rule_runtime.get('b-on')))
            os.system('tail -4 %s' % (W / 'z.log'))
        return None


def zb_probe(limit=3.0):
    """The same report, to the Zigbee lamp's command."""
    WIRE.put((BASE + '/PIR-Bench', json.dumps({'occupancy': False}).encode()))
    time.sleep(0.1)
    drain(ZB)
    t0 = time.perf_counter()
    WIRE.put((BASE + '/PIR-Bench', json.dumps({'occupancy': True}).encode()))
    try:
        return (ZB.get(timeout=limit)[0] - t0) * 1000
    except queue.Empty:
        return None


def press(on, limit=10.0):
    """A press on the page: the request, to the box being told."""
    drain(SETS)
    t0 = time.perf_counter()
    threading.Thread(target=lambda: ask('api/plug/switch', {'name': 'Light-Bench', 'on': on, 'pin': '1234'},
                                        timeout=limit), daemon=True).start()
    try:
        while True:
            at, got = SETS.get(timeout=limit)
            if got == on:
                return (at - t0) * 1000
    except queue.Empty:
        return None


def for_probe(span=1.0):
    """On for a second: how late the way back comes, ms."""
    p = d.plugs['Light-Bench']
    if BOX['output']:
        d.set_plug_output(p, False, 'bench')
        time.sleep(0.2)
    drain(SETS)
    d._fire_target(('plug', p), 'for:%gs' % span, 'bench')
    on_at = None
    try:
        while True:
            at, on = SETS.get(timeout=span + 5)
            if on and on_at is None:
                on_at = at
            elif not on and on_at is not None:
                return (at - on_at) * 1000 - span * 1000
    except queue.Empty:
        return None


def alert_probe(limit=15.0):
    """A burglar: the report, to the alert arriving at ntfy."""
    WIRE.put((BASE + '/PIR-Alarm', json.dumps({'occupancy': False}).encode()))
    time.sleep(0.1)
    d.notify_sent.clear()                        # the same story inside 15 min is told once
    drain(ALERTS)
    t0 = time.perf_counter()
    WIRE.put((BASE + '/PIR-Alarm', json.dumps({'occupancy': True}).encode()))
    deadline = time.time() + limit
    while True:
        try:
            got = ALERTS.get(timeout=max(0.01, deadline - time.time()))
        except queue.Empty:
            return None
        # (5.44.1) the burglar's alert, not another one that happened to go
        # out meanwhile (the dead socket's "not taking commands", from before)
        if b'PIR-Alarm' in got[2]:
            return (got[0] - t0) * 1000


def stats(xs):
    got = sorted(x for x in xs if x is not None)
    lost = len([x for x in xs if x is None])
    if not got:
        return {'n': 0, 'lost': lost}
    pick = lambda q: got[min(len(got) - 1, int(q * len(got)))]           # noqa: E731
    return {'n': len(got), 'lost': lost, 'p50': round(pick(0.5), 1), 'p99': round(pick(0.99), 1),
            'max': round(got[-1], 1)}


# ---- the load --------------------------------------------------------------------
STOP = threading.Event()
LOAD = {'burst': 0, 'backups': 0, 'vacuums': 0, 'pages': 0, 'chores': 0}


def burst(per_s=500):
    i = 0
    nxt = time.perf_counter()
    while not STOP.is_set():
        WIRE.put((BASE + '/' + OTHERS[i % len(OTHERS)], json.dumps({
            'temperature': 20 + (i % 50) / 10.0, 'humidity': 40 + i % 7, 'linkquality': 100 + i % 30,
            'battery': 90}).encode()))
        LOAD['burst'] += 1
        i += 1
        nxt += 1.0 / per_s
        pause = nxt - time.perf_counter()
        if pause > 0:
            time.sleep(pause)


def backups():
    while not STOP.is_set():
        try:
            d.db_backup_now()
            LOAD['backups'] += 1
        except Exception as e:
            print('  backup: %s' % e)
        shutil.rmtree(str(W / 'backups'), ignore_errors=True)
        STOP.wait(0.3)


def vacuums():
    while not STOP.is_set():
        try:
            d.store.optimize()
            LOAD['vacuums'] += 1
        except Exception as e:
            print('  vacuum: %s' % e)
        STOP.wait(0.3)


def page():
    seq = 0
    while not STOP.is_set():
        try:
            seq = ask('api/status').get('seq', seq)
            ask('api/wait?seq=%d' % seq, timeout=30)
            ask('api/events?limit=200')
            LOAD['pages'] += 1
        except Exception:
            STOP.wait(0.05)


REAL_GAI = socket.getaddrinfo
REAL_RUN = zigmon.subprocess.run
WORLD = {'dns_s': 0.4}


def slow_world(on=True):
    """Every look over the network, and every ask of root or a tool, takes its
    time: a name is answered after a while, and then not at all."""
    def slow_gai(host, *a, **k):
        if host not in ('127.0.0.1', 'localhost', '::1', None):
            time.sleep(WORLD['dns_s'])
            raise socket.gaierror('no such name (review538)')
        return REAL_GAI(host, *a, **k)

    def slow_run(args, *a, **k):
        time.sleep(0.4)
        return REAL_RUN(['true'], *a, **{x: y for x, y in k.items()
                                         if x in ('capture_output', 'timeout', 'text', 'stdout', 'stderr')})
    socket.getaddrinfo = slow_gai if on else REAL_GAI
    zigmon.subprocess.run = slow_run if on else REAL_RUN


def chores():
    jobs = [(n, (lambda fn=getattr(zigmon, n): fn(d))) for n in ('acme_tick', 'proxy_tls_tick', 'osup_tick', 'rb_tick')
            if getattr(zigmon, n, None)]
    jobs += [(n, getattr(d, n)) for n in ('root_chores', 'maint_follow', 'check_system_alerts', 'net_tick')
             if getattr(d, n, None)]
    jobs.append(('webproxy_try', lambda: zigmon.webproxy_try('https://example.invalid/')))
    while not STOP.is_set():
        for _name, fn in jobs:
            try:
                fn()
            except Exception:
                pass
            LOAD['chores'] += 1
        STOP.wait(0.2)


ALL = [(burst, 1), (backups, 1), (vacuums, 1), (page, 4), (chores, 1)]


def loaded(loads, seconds, what):
    """`what` called over and over for `seconds` with the load running."""
    STOP.clear()
    threads = [threading.Thread(target=fn, name='load-' + fn.__name__, daemon=True)
               for fn, n in loads for _ in range(n)]
    for t in threads:
        t.start()
    time.sleep(1.0)
    if WHY:
        sampling.set()
    out = []
    t_end = time.time() + seconds
    while time.time() < t_end:
        out.append(what())
    sampling.clear()
    STOP.set()
    for t in threads:
        t.join(40)
    return out


def quiet_pir():
    """The PIR clear and the light off, so the next report is an edge."""
    WIRE.put((BASE + '/PIR-Bench', json.dumps({'occupancy': False}).encode()))
    time.sleep(0.4)


def reports(gap=0.12):
    quiet_pir()
    state = {'flip': False}                   # so the first report is somebody coming in

    def one():
        state['flip'] = not state['flip']
        ms = probe(state['flip'])
        time.sleep(gap)
        return ms
    return one


def presses(gap=0.15):
    state = {'on': bool(BOX['output'])}

    def one():
        state['on'] = not state['on']
        ms = press(state['on'])
        time.sleep(gap)
        return ms
    return one


# ---- the database held, a VACUUM of a big file, a rule on trial -----------------
class SlowFile(object):
    """The database connection of a house with a quarter-gigabyte file: one
    statement at a time on it, as SQLite's own mutex has it, and a VACUUM
    that takes its seconds."""

    def __init__(self, real, vacuum_s):
        self.real, self.vacuum_s, self.mutex = real, vacuum_s, threading.RLock()

    def execute(self, sql, *a):
        with self.mutex:
            if str(sql).strip().upper().startswith('VACUUM'):
                time.sleep(self.vacuum_s)
            return self.real.execute(sql, *a)

    def __getattr__(self, name):
        got = getattr(self.real, name)
        if not callable(got):
            return got

        def under(*a, **k):
            with self.mutex:
                return got(*a, **k)
        return under


def while_erasing(scope, vacuum_s=2.0):
    """Erase the events or the history on the page, or what is left of devices
    that are gone - and while its VACUUM runs, every other sensor of the house
    reports once, then the PIR. How long the light took, and the longest any
    one message held the broker's thread."""
    quiet_pir()
    real = d.store.db
    d.store.db = SlowFile(real, vacuum_s)
    try:
        t = threading.Thread(target=(lambda: d.store.drop_stale()) if scope == 'stale'
                             else (lambda: d.reset(scope)), daemon=True)
        t.start()
        time.sleep(0.3)                             # the VACUUM is under way
        del HELD[:]
        for i, name in enumerate(OTHERS):
            WIRE.put((BASE + '/' + name, json.dumps({'temperature': 21 + i / 10.0}).encode()))
        ms = probe(True, limit=vacuum_s + 5)
        held = max(HELD or [0])
        t.join(30)
        return ms, held
    finally:
        d.store.db = real


def held_lock(seconds):
    """Somebody else holding the database: a backup, an optimise."""
    def hold():
        with d.store.lock:
            time.sleep(seconds)
    t = threading.Thread(target=hold, daemon=True)
    t.start()
    time.sleep(0.05)
    return t


def trial_while_held(seconds=1.5):
    """A rule on trial fires while somebody presses Test alerts on its import
    (which writes the list down) and a backup holds the database; then the
    PIR. How long the light took."""
    bid = d.trial_add({'rules': [{'id': 'r-trial', 'device': 'zigbee:PIR-Alarm', 'key': 'occupancy',
                                  'op': '==', 'value': 1, 'plug': 'Light-Bench', 'do': 'off'}]},
                      by='review538', name='trial.json')
    WIRE.put((BASE + '/PIR-Alarm', json.dumps({'occupancy': False}).encode()))
    quiet_pir()
    holder = held_lock(seconds)
    threading.Thread(target=d.trial_alerts, args=(bid, True), daemon=True).start()
    time.sleep(0.05)
    WIRE.put((BASE + '/PIR-Alarm', json.dumps({'occupancy': True}).encode()))
    time.sleep(0.05)
    ms = probe(True, limit=seconds + 5)
    holder.join()
    time.sleep(0.3)
    d.trial_rollback(bid, by='review538')
    return ms


def lit_by(how, limit=5.0):
    """The light off first, then asked on by one road: ms."""
    p = d.plugs['Light-Bench']
    if BOX['output']:
        d.set_plug_output(p, False, 'review538')
    time.sleep(0.1)
    drain(SETS)
    t0 = time.perf_counter()
    how()
    try:
        while True:
            at, on = SETS.get(timeout=limit)
            if on:
                return (at - t0) * 1000
    except queue.Empty:
        return None


ROADS = [
    ('a rule', lambda: WIRE.put((BASE + '/PIR-Bench', json.dumps({'occupancy': True}).encode())),
     lambda: WIRE.put((BASE + '/PIR-Bench', json.dumps({'occupancy': False}).encode()))),
    ('a button', lambda: (d.__dict__.pop('_press_seen', None),
                          WIRE.put((BASE + '/Btn-Bench', json.dumps({'action': 'single'}).encode()))), None),
    ('the page', lambda: threading.Thread(target=lambda: ask('api/plug/switch', {
        'name': 'Light-Bench', 'on': True, 'pin': '1234'}), daemon=True).start(), None),
    ('a link', lambda: threading.Thread(target=lambda: d.tap('tok-bench-538', who='review538'),
                                        daemon=True).start(), None),
    ('a scene', lambda: d._fire_target(('scene', 'sc-bench'), 'on', 'review538'), None),
]


def roads_while_held(seconds=1.5):
    out = {}
    for name, go, before in ROADS:
        if before:
            before()
            time.sleep(0.2)
        holder = held_lock(seconds)
        out[name] = lit_by(go)
        holder.join()
        time.sleep(0.3)
    return out


def alerts_by_proxy(n=4, dns_s=2.0):
    """The proxy on for alerts, ntfy named, and a resolver that takes dns_s
    to say it does not know the name."""
    zigmon.CONFIG.update({'notify_ntfy': 'http://ntfy.example.org/house', 'webproxy': 1,
                          'webproxy_url': 'http://127.0.0.1:%d' % NTFYPORT, 'webproxy_alerts': 1})
    WORLD['dns_s'] = dns_s
    slow_world(True)
    try:
        return [alert_probe() for _ in range(n)]
    finally:
        slow_world(False)
        WORLD['dns_s'] = 0.4
        zigmon.CONFIG.update({'notify_ntfy': 'http://127.0.0.1:%d/house' % NTFYPORT, 'webproxy': 0})


def dead_pileup(seconds=20.0, per_s=4.0):
    """A socket that is plugged in and dead, asked on and off by a rule four
    times a second: how many commands are waiting on it at the end (each
    of them to be sent in turn when it answers again), and
    whether a scene still runs."""
    p = d.plugs['Dead-Bench']
    t_end = time.time() + seconds
    on = False
    while time.time() < t_end:
        on = not on
        d._fire_target(('plug', p), 'on' if on else 'off', 'rule: review538', honour_hold=True)
        time.sleep(1.0 / per_s)
    waiting = sum(1 for t in threading.enumerate() if t.name == 'binding')
    return waiting, lit_by(lambda: d._fire_target(('scene', 'sc-bench'), 'on', 'review538'))


def ms(x):
    return 'never' if x is None else '%.1f ms' % x


try:
    for _flip in (True, False, True, False):           # everything warm
        probe(_flip)
        time.sleep(0.2)

    if BENCH:
        secs = float(os.environ.get('ZIGMON_BENCH_S') or 15)
        slow_world(True)
        for label, loads in (('quiet', []), ('burst 500/s', [(burst, 1)]),
                             ('backup + VACUUM', [(backups, 1), (vacuums, 1)]),
                             ('pages x4', [(page, 4)]), ('chores (slow world)', [(chores, 1)]),
                             ('everything', ALL)):
            del SLOW[:], SAMPLES[:], HELD[:]
            GC.clear()
            d.store.lock.taken.clear()
            for k in LOAD:
                LOAD[k] = 0
            print('%-20s report->plug %s' % (label, stats(loaded(loads, secs, reports()))))
            print('%-20s   broker held a message %s; collector %s; load %s'
                  % ('', stats(HELD), {g: (n, round(w, 1)) for g, (n, w) in sorted(GC.items())}, dict(LOAD)))
            for key, (n, worst) in sorted(d.store.lock.taken.items(), key=lambda kv: -kv[1][1])[:8]:
                print('%-20s   database lock taken %d times, waited up to %.1f ms: %s' % ('', n, worst, key))
            for (name, a, b), n in (where_slow() if WHY else []):
                print('      %4d  %-14s %s  <- %s' % (n, name, a, b))
        print('%-20s report->lamp %s' % ('zigbee, everything', stats(loaded(ALL, secs, zb_probe))))
        print('%-20s press->plug %s' % ('page, everything', stats(loaded(ALL, secs, presses()))))
        print('%-20s lateness %s' % ('on for 1 s, all', stats(loaded(ALL, min(secs, 10), for_probe))))
        print('%-20s report->ntfy %s' % ('alert, everything', stats(loaded(ALL, min(secs, 8), alert_probe))))
        slow_world(False)

    print('erasing on the page, while its VACUUM runs (2 s)')
    for scope in ('events', 'history', 'stale'):
        took, held = while_erasing(scope)
        print('  erase %-8s report->plug %s, the broker thread held %.0f ms at most' % (scope, ms(took), held))
        check(took is not None and took < 300,
              'with the %s being erased, a report reached the light in %s' % (scope, ms(took)))
        check(held < 200, 'with the %s being erased, one report held the broker\'s thread %.0f ms - no '
              'report and no press was heard meanwhile' % (scope, held))
    check(d.store.store_snapshot('zigbee:PIR-Bench', int(time.time()), {}).get('occupancy') is not None,
          'erasing the events and the history forgot what the PIR last said')

    print('a rule on trial, while its import is written behind a backup (1.5 s)')
    took = trial_while_held()
    print('  report->plug %s' % ms(took))
    check(took is not None and took < 300, 'a rule on trial held the rule worker, and the light, %s' % ms(took))

    print('every road to the light, with the database held (1.5 s)')
    for name, took in roads_while_held().items():
        print('  %-9s -> plug %s' % (name, ms(took)))
        check(took is not None and took < 300, 'with the database held, %s reached the light in %s'
              % (name, ms(took)))

    print('a dead socket asked on and off four times a second for 20 s')
    waiting, took = dead_pileup()
    print('  %d command(s) waiting on it; a scene on another socket -> plug %s' % (waiting, ms(took)))
    # one in flight, and what was asked while it was: four a second for at
    # most the five seconds a command to a silent box is given
    check(waiting <= 30, '%d commands piled up behind a dead socket, each to be sent when it answers '
          'again - and past %d of them every scene in the house is refused' % (waiting, d.BUSY_CEILING))
    check(took is not None and took < 300, 'with a dead socket being asked, a scene reached its light in %s'
          % ms(took))

    print('alerts through the proxy, with a resolver that takes 2 s to know nothing')
    got = alerts_by_proxy()
    print('  report->ntfy %s' % ', '.join(ms(x) for x in got))
    check(all(x is not None for x in got), 'an alert through the proxy never arrived: %r' % got)
    if all(x is not None for x in got):
        check(max(got) < 1600, 'an alert waited %s for DNS before it went' % ms(max(got)))
        check(max(got[2:]) < 300, 'every alert asked DNS again: %s' % ', '.join(ms(x) for x in got))

    print('under everything at once for 10 s')
    slow_world(True)
    d.store.lock.taken.clear()
    del HELD[:]
    got = stats(loaded(ALL, 10, reports()))
    held = stats(HELD)
    late = stats(loaded(ALL, 5, for_probe))
    slow_world(False)
    print('  report->plug %s' % got)
    print('  the broker thread, a message %s' % held)
    print('  on for 1 s: the way back late by %s' % late)
    check(not got.get('lost') and got.get('n'), 'a report never reached the light under load: %r' % got)
    check(got.get('p99', 1e9) < 250, 'under load a report reached the light in %r ms (p99)' % got.get('p99'))
    check(not late.get('lost') and late.get('max', 1e9) < 250,
          'under load "on for 1 s" came back late: %r' % late)
    waits = {k: v for k, v in d.store.lock.taken.items() if v[1] > 50}
    check(not waits, 'on the way to a light, the database lock was waited for: %r' % waits)
finally:
    STOP.set()
    slow_world(False)
    for srv in servers:
        srv.shutdown()
        srv.server_close()
    api.stop()
    dead.close()
    shutil.rmtree(str(W), ignore_errors=True)

if bad:
    print('%d check(s) failed' % len(bad))
    sys.exit(1)
print('all review538 checks passed')
