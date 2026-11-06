#!/usr/bin/env python3
"""(5.44.1) The status read while the house changes under it.

During a long load run /api/status answered 500 once with "RuntimeError:
dictionary changed size during iteration": something the status walks was
written by another thread in the middle of the walk. This builds the status
(and the other things the page polls) on several threads in a tight loop
while others play a busy house - 65 devices reporting, new keys turning up in
a payload, availability coming and going, the bridge's list re-sent with
devices added and taken away, sockets polled, people coming and going,
notices raised and cleared, the performance meter on, rules saved, devices
renamed, a socket's own MQTT pushing, a box saying "too many requests" -
with the interpreter told to switch threads as often as it can. Every
exception any of them meets is a failure, and so is an error the daemon
caught and wrote down (an API handler's 500).

  1. free running: every thread as fast as it goes (ZIGMON_RACE_S, 22 s)
  2. provoked: the readers stopped between two of their lines while a
     writer takes one step (ZIGMON_RACE_PROVOKE_S, 18 s)
  3. each race found, made to happen at the one moment that matters

What 5.44.1 found and mended: the socket's reading written into in place by
its MQTT push while describe() walked it (the 500 of the load run), the
boxes' "too many requests" table walked while a box was added, the device
list read a second time after another thread had forgotten it, a command's
tidy-up in say() and a message's in send_message().

    python3 test/pass2_race.py            # about 45 s
    ZIGMON_RACE_S=120 ZIGMON_RACE_PROVOKE_S=120 python3 test/pass2_race.py

Ports 19370 (the API) and 19371 (a Shelly).
"""
import collections
import json
import os
import random
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

APIPORT, BOXPORT = 19370, 19371
RUN_S = float(os.environ.get('ZIGMON_RACE_S') or 22)
W = Path(tempfile.mkdtemp(prefix='zigmon-pass2race-'))
bad = []
FAULTS = collections.OrderedDict()      # where -> (count, first traceback)
FAULT_LOCK = threading.Lock()


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def fault(where, text):
    with FAULT_LOCK:
        n, first = FAULTS.get(where, (0, text))
        FAULTS[where] = (n + 1, first)


# ---- a Shelly that answers ------------------------------------------------------
BOX = {str(i): False for i in range(4)}


class Box(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    wbufsize = 65536

    def log_message(self, *a):
        pass

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        method, params = req.get('method'), req.get('params') or {}
        sid = str(params.get('id', 0))
        if method in ('Switch.Set', 'Switch.Toggle'):
            was = BOX.get(sid)
            BOX[sid] = (not was) if method == 'Switch.Toggle' else bool(params.get('on'))
            out = {'was_on': was}
        elif method in ('Shelly.GetStatus', 'Switch.GetStatus'):
            # a field that comes and goes, as a firmware update brings one
            out = {'switch:%s' % k: dict({'id': int(k), 'output': v, 'apower': random.random() * 50,
                                          'voltage': 231.0, 'aenergy': {'total': random.random()}},
                                         **({'temperature': {'tC': 40.0}} if random.random() < 0.5 else {}))
                   for k, v in BOX.items()}
            out['mqtt'] = {'connected': True}
            if method == 'Switch.GetStatus':
                out = out['switch:%s' % sid]
        elif method == 'Shelly.GetDeviceInfo':
            out = {'id': 'shellyplug-race', 'model': 'S3PL-00112EU', 'gen': 3, 'ver': '1.7.1'}
        else:
            out = {}
        raw = json.dumps({'id': req.get('id'), 'result': out}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class Info(object):
    rc = 0
    mid = 1

    def wait_for_publish(self, *a):
        return True

    def is_published(self):
        return True


class Msg(object):
    def __init__(self, topic, payload, retain=False):
        self.topic, self.payload, self.retain = topic, payload, retain


class Client(object):
    """The broker, as far as the daemon writes to it: everything accepted."""

    def publish(self, *a, **k):
        return Info()

    def subscribe(self, *a, **k):
        return (0, 1)

    def message_callback_add(self, *a, **k):
        pass


# ---- the house ------------------------------------------------------------------
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': APIPORT, 'token_file': str(W / 'api-token'),
                      'pin': '1234', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': str(W / 'z.log'),
                      'state_dir': str(W / 'state'), 'log_to_journal': False, 'weather': False,
                      'plug_timeout': 3.0, 'plug_poll_s': 1, 'binding_debounce_ms': 0, 'perf_meter': 1})
(W / 'state').mkdir()
zigmon.open_log()
zigmon.start_log_writer()
BASE = zigmon.CONFIG['base_topic'].rstrip('/')

_srv = ThreadingHTTPServer(('127.0.0.1', BOXPORT), Box)
_srv.daemon_threads = True
threading.Thread(target=_srv.serve_forever, daemon=True).start()

d = zigmon.Daemon()
d.backup_dir = lambda: W / 'backups'
d.store.set_meta('managed', json.dumps({'plugs': [
    {'name': 'Sock-%d' % i, 'host': '127.0.0.1:%d' % BOXPORT, 'switch_id': i, 'kind': 'plug',
     'host_state': 'enabled', 'mqtt': True, 'mqtt_name': 'shellyrace'} for i in range(4)], 'sensors': []}))
d.reload_devices()
d.client, d.connected = Client(), True
d._verify_zigbee_set = lambda *a, **k: None

NAMES = ['TH-%02d' % i for i in range(60)] + ['PIR-%d' % i for i in range(3)] + ['Btn-0', 'Lamp-0']


def ieee(name):
    return '0x00158d00%08x' % (abs(hash(name)) % (1 << 32))


def bridge_list(skip=()):
    out = [{'ieee_address': '0x00124b0000000000', 'friendly_name': 'Coordinator', 'type': 'Coordinator'}]
    for n in NAMES:
        if n in skip:
            continue
        if n.startswith('PIR'):
            exp = [{'type': 'binary', 'name': 'occupancy', 'property': 'occupancy'}]
        elif n.startswith('Btn'):
            exp = [{'type': 'enum', 'name': 'action', 'property': 'action', 'values': ['single', 'double']}]
        elif n.startswith('Lamp'):
            exp = [{'type': 'binary', 'name': 'state', 'property': 'state'}]
        else:
            exp = [{'type': 'numeric', 'name': 'temperature', 'property': 'temperature', 'unit': 'C'},
                   {'type': 'numeric', 'name': 'humidity', 'property': 'humidity', 'unit': '%'}]
        out.append({'ieee_address': ieee(n), 'friendly_name': n, 'type': 'Router' if n.startswith('Lamp')
                    else 'EndDevice', 'definition': {'model': 'M-' + n[:3], 'vendor': 'V', 'exposes': exp}})
    return out


def deliver(topic, payload):
    d._on_message(None, None, Msg(topic, json.dumps(payload).encode() if not isinstance(payload, bytes)
                                  else payload))


deliver(BASE + '/bridge/devices', bridge_list())
deliver(BASE + '/bridge/state', {'state': 'online'})
for _n in NAMES:
    deliver('%s/%s' % (BASE, _n), {'temperature': 21.0, 'linkquality': 120, 'battery': 90})

d.store.set_meta('rules', json.dumps([
    {'id': 'r-%d' % i, 'device': ieee('PIR-%d' % i), 'key': 'occupancy', 'op': '==', 'value': 1,
     'plug': 'Sock-%d' % i, 'do': 'on', 'enabled': True, 'cooldown_s': 0} for i in range(3)]))
d.save_people([{'name': 'Person-%d' % i, 'macs': ['aa:bb:cc:dd:ee:%02x' % i], 'enabled': True}
               for i in range(3)])

# a log() of level error is a failure somewhere the harness cannot see: a
# handler that caught what went wrong and wrote it down
_real_log = zigmon.log


def _watched_log(msg, level='info', *a, **k):
    if level == 'error' and ('during iteration' in str(msg) or sys.exc_info()[0] is not None):
        # said inside the handler that caught it: the traceback is still there
        fault('log: ' + re.sub(r'\[[0-9a-f]{6}\]', '[..]', str(msg))[:120],
              str(msg) + '\n' + (traceback.format_exc() if sys.exc_info()[0] is not None else ''))
    return _real_log(msg, level, *a, **k)


zigmon.log = _watched_log

threading.Thread(target=d.rule_worker, name='rules', daemon=True).start()
threading.Thread(target=d.timer_loop, name='timers', daemon=True).start()
threading.Thread(target=d.plug_loop, name='plugs', daemon=True).start()
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)
TOKEN = Path(zigmon.CONFIG['token_file']).read_text().strip()
d.account_add('race-op', 'admin', 'race pass 5441', must_change=False, quiet=True)
SESSION = d.login('race-op', 'race pass 5441', '192.0.2.44')[0]['token']


def ask(path):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (APIPORT, path),
                                 headers={'X-Zigmon-Token': TOKEN, 'X-Zigmon-Session': SESSION})
    try:
        return urllib.request.urlopen(req, timeout=30).read()
    except urllib.error.HTTPError as e:
        if e.code >= 500:
            fault('HTTP %d %s' % (e.code, path.split('?')[0]), e.read().decode('utf-8', 'replace')[:2000])
        return b''


STOP = threading.Event()
DONE = collections.Counter()


NAP = [True]


def nap(seconds):
    """A writer's pause between two of its steps - none when the steps are
    handed to it one at a time (part 2)."""
    if NAP[0]:
        time.sleep(seconds)


def loop(name, fn):
    def run():
        rnd = random.Random(hash(name))
        while not STOP.is_set():
            try:
                fn(rnd)
                DONE[name] += 1
            except Exception as e:                           # noqa: BLE001 - every one of them counted
                fault('%s: %s: %s' % (name, type(e).__name__, str(e)[:80]), traceback.format_exc())
    t = threading.Thread(target=run, name=name, daemon=True)
    t.start()
    return t


# ---- the house changing ------------------------------------------------------------
def reports(rnd):
    n = rnd.choice(NAMES)
    body = {'temperature': round(rnd.uniform(15, 30), 1), 'linkquality': rnd.randint(1, 255)}
    if rnd.random() < 0.3:
        body['new_field_%d' % rnd.randint(0, 400)] = rnd.random()       # a key never seen before
    if n.startswith('PIR'):
        body = {'occupancy': rnd.random() < 0.5}
    elif n.startswith('Btn'):
        body = {'action': rnd.choice(['single', 'double', 'hold_%d' % rnd.randint(0, 50)])}
    deliver('%s/%s' % (BASE, n), body)


def availability(rnd):
    deliver('%s/%s/availability' % (BASE, rnd.choice(NAMES)), {'state': rnd.choice(['online', 'offline'])})
    nap(0.002)


def resync(rnd):
    deliver(BASE + '/bridge/devices', bridge_list(skip=set(rnd.sample(NAMES, 3))))
    deliver(BASE + '/bridge/info', {'version': '1.40.%d' % rnd.randint(0, 9), 'permit_join': rnd.random() < 0.5,
                                    'coordinator': {'type': 'zStack3x0', 'meta': {'revision': rnd.randint(1, 9)}},
                                    'config': {'advanced': {'channel': 15}}})
    nap(0.05)


def presence(rnd):
    who = rnd.choice(d.people())
    d.presence_report('', rnd.choice(['home', 'away']), origin='the race', person=who)
    d._presence_cache = None
    nap(0.005)


def notices(rnd):
    key = 'race-%d' % rnd.randint(0, 5)
    if rnd.random() < 0.6:
        d.notice_raise(key, rnd.choice(['info', 'warn']), 'Race %s' % key, 'because %d' % rnd.randint(0, 9),
                       stamp=str(rnd.randint(0, 3)))
    else:
        d.notice_clear(key)
    nap(0.005)


def rules(rnd):
    d.save_rules([{'id': 'r-%d' % i, 'device': ieee('PIR-%d' % i), 'key': 'occupancy', 'op': '==', 'value': 1,
                   'plug': 'Sock-%d' % i, 'do': rnd.choice(['on', 'off']), 'enabled': True, 'cooldown_s': 0}
                  for i in range(3)])
    nap(0.02)


def renames(rnd):
    dev = d.store.device(ieee(rnd.choice(NAMES)))
    if dev:
        d.store.set_alias(dev['id'], rnd.choice([None, 'Alias %d' % rnd.randint(0, 99)]))
    nap(0.01)


def plugs(rnd):
    p = d.plug_by_name('Sock-%d' % rnd.randint(0, 3))
    d.poll_plug(p, force=True)


def pushes(rnd):
    # the box's own MQTT: what its relay and meter did, as it says it at once -
    # with what the poll leaves out (the minute's figures), and now and then a
    # field never heard before
    sid = rnd.randint(0, 3)
    part = {'id': sid, 'apower': round(rnd.random() * 50, 1),
            'aenergy': {'total': rnd.random() * 100, 'by_minute': [1.0, 2.0, 3.0], 'minute_ts': int(time.time())}}
    if rnd.random() < 0.3:
        part['field_%d' % rnd.randint(0, 300)] = rnd.random()
    if rnd.random() < 0.2:
        part['output'] = rnd.random() < 0.5
    deliver('shellyrace/events/rpc', {'method': 'NotifyStatus', 'params': {'ts': time.time(), 'switch:%d' % sid: part}})
    nap(0.001)


# ---- the page asking ---------------------------------------------------------------
def status_direct(rnd):
    d._status_json(d.status())


def status_shared(rnd):
    d.status_with_notices(d.status_body())


def status_http(rnd):
    ask('/api/status')


def others_http(rnd):
    ask(rnd.choice(['/api/events?limit=50', '/api/perf', '/api/plug?name=Sock-1', '/api/plugs',
                    '/api/history?device=%s&range=1h' % ieee('TH-01'), '/api/health']))


def rate_limited(rnd):
    # a box answering 429: what a socket's poll or command does on its own thread
    zigmon.ShellyRPC('192.0.2.%d:%d' % (rnd.randint(1, 254), rnd.randint(1, 60000)))._note_429()
    if len(zigmon.ShellyRPC._rate_limited) > 300:
        with zigmon.ShellyRPC._gates_guard:
            zigmon.ShellyRPC._rate_limited = {}


# ---- 1. free running: every thread as fast as it goes ----------------------------------
sys.setswitchinterval(1e-6)
print('1. the house changing under the status for %.0f s...' % RUN_S)
writers = [('reports-a', reports), ('reports-b', reports), ('availability', availability), ('resync', resync),
           ('presence', presence), ('notices', notices), ('rules', rules), ('renames', renames), ('plugs', plugs),
           ('pushes', pushes), ('rate-limited', lambda rnd: (rate_limited(rnd), nap(0.01)))]
readers = [('status-1', status_direct), ('status-2', status_direct), ('status-3', status_shared),
           ('status-http', status_http), ('others-http', others_http)]
threads = [loop(n, f) for n, f in writers + readers]
t_end = time.time() + RUN_S
while time.time() < t_end and not FAULTS:
    time.sleep(0.2)
if FAULTS:
    time.sleep(min(3.0, max(0.0, t_end - time.time())))   # a moment more, for the siblings
STOP.set()
for t in threads:
    t.join(10)
sys.setswitchinterval(0.005)
print('   ' + ', '.join('%s %d' % kv for kv in sorted(DONE.items())))
check(DONE['status-1'] > 20 and DONE['status-http'] > 5, 'the status was hardly built at all: %r' % dict(DONE))
free_faults = len(FAULTS)

# ---- 2. provoked: the reader stopped between two of its lines -----------------------------
# A thread switch lands between two lines of Python; the free run above has to
# be lucky for one to land inside the few lines of a walk while a writer has
# something to write. Here a tracer on the readers' threads stops the reader
# at one line in PROVOKE_EVERY of the daemon's own, hands one writer's step to
# a writer thread of its own and waits for it (a moment at most: a writer that
# needs a lock the reader holds waits for the reader, as it would for real) -
# the switch, made to happen everywhere in turn.
PROVOKE_S = float(os.environ.get('ZIGMON_RACE_PROVOKE_S') or 18)
PROVOKE_EVERY = int(os.environ.get('ZIGMON_RACE_EVERY') or 300)
STEPS = [reports, reports, reports, availability, presence, notices, renames, rate_limited, rate_limited,
         pushes, pushes, pushes, lambda rnd: (rnd.random() < 0.05 and resync(rnd)),
         lambda rnd: (rnd.random() < 0.2 and rules(rnd))]
ZFILE = zigmon.__file__
HAND = {'cv': threading.Condition(), 'want': 0, 'done': 0}
WRITER = 'provoked-writer'


def provoked_writer():
    rnd = random.Random(5441)
    while not STOP.is_set():
        with HAND['cv']:
            while HAND['want'] == HAND['done'] and not STOP.is_set():
                HAND['cv'].wait(0.2)
            if STOP.is_set():
                return
            step = HAND['want']
        try:
            rnd.choice(STEPS)(rnd)
            DONE['provoked steps'] += 1
        except Exception as e:                           # noqa: BLE001
            fault('provoked step: %s: %s' % (type(e).__name__, str(e)[:80]), traceback.format_exc())
        with HAND['cv']:
            HAND['done'] = step
            HAND['cv'].notify_all()


WAITED = threading.local()


def hold_still():
    """Wait for the step under way - once per step on each thread: a reader
    holding a lock the step needs goes on after a moment, as it would."""
    with HAND['cv']:
        step = HAND['want']
        if step == HAND['done'] or getattr(WAITED, 'step', None) == step:
            return
        WAITED.step = step
        HAND['cv'].wait_for(lambda: HAND['done'] >= step or STOP.is_set(), 0.05)


def tracer(frame, event, arg):
    if event != 'call' or frame.f_code.co_filename != ZFILE:
        return None
    if threading.current_thread().name == WRITER or STOP.is_set():
        return None

    def lines(frame, event, arg):
        if event != 'line' or STOP.is_set():
            return lines
        if HAND['want'] != HAND['done']:
            hold_still()                  # a step under way: every reader holds still while it runs
        elif random.random() < 1.0 / PROVOKE_EVERY:
            with HAND['cv']:
                if HAND['want'] == HAND['done']:
                    HAND['want'] += 1
                    HAND['cv'].notify_all()
            hold_still()
        return lines
    return lines


STOP.clear()
DONE.clear()
NAP[0] = False
sys.setswitchinterval(1e-5)
threading.Thread(target=provoked_writer, name=WRITER, daemon=True).start()
print('2. the readers stopped between their lines, a writer stepping in, for %.0f s...' % PROVOKE_S)


def traced(name, fn):
    def run(rnd):
        sys.settrace(tracer)
        try:
            fn(rnd)
        finally:
            sys.settrace(None)
    return loop(name, run)


def traced_api(rnd):
    # the API's own handlers, traced on the thread that answers: the server's
    # threads are started per request, so the tracer is set for new threads
    ask(rnd.choice(['/api/status', '/api/status', '/api/events?limit=50', '/api/perf', '/api/plug?name=Sock-2',
                    '/api/plugs', '/api/history?device=%s&range=1h' % ieee('TH-02')]))


threading.settrace(tracer)
threads = [traced('t-status', status_direct), traced('t-shared', status_shared),
           traced('t-notices', lambda rnd: (d.notices_view(), time.sleep(0.01))),
           traced('t-plugs', lambda rnd: ([d.plug_snapshot(p) for p in d.plugs.values()], time.sleep(0.01))),
           loop('t-api', traced_api)]
t_end = time.time() + PROVOKE_S
while time.time() < t_end and len(FAULTS) == free_faults:
    time.sleep(0.2)
if len(FAULTS) > free_faults:
    time.sleep(min(3.0, max(0.0, t_end - time.time())))
STOP.set()
threading.settrace(None)
with HAND['cv']:
    HAND['cv'].notify_all()
for t in threads:
    t.join(10)
print('   ' + ', '.join('%s %d' % kv for kv in sorted(DONE.items())))
for where, (n, first) in FAULTS.items():
    print('\n=== %s  (x%d)\n%s' % (where, n, first))
check(not FAULTS, '%d kinds of failure under the race' % len(FAULTS))
check(DONE['t-status'] > 3 and DONE['provoked steps'] > 200, 'the provoked readers hardly ran: %r' % dict(DONE))

# ---- 3. the ones found, each made to happen at the one moment that matters ------------
print('3. each race found, at its moment...')
time.sleep(0.5)                                   # the threads of part 2 gone quiet


class WalkedWhileWritten(dict):
    """A dict that is written to by "another thread" the moment somebody walks
    its items or values - the switch landing inside the walk, every time. A
    copy taken first (dict(x), C-level, one step) is not walked, and passes."""

    def __init__(self, *a, **k):
        dict.__init__(self, *a, **k)
        self.n = 0

    def _poke(self):
        self.n += 1
        dict.__setitem__(self, 'written-meanwhile-%d' % self.n, (time.time(), 1))

    def items(self):
        for i, kv in enumerate(dict.items(self)):
            if i == 0:
                self._poke()
            yield kv

    def values(self):
        for i, v in enumerate(dict.values(self)):
            if i == 0:
                self._poke()
            yield v


# a. a box's first "too many requests" lands while the status lists them
_keep = zigmon.ShellyRPC._rate_limited
zigmon.ShellyRPC._rate_limited = WalkedWhileWritten({'192.0.2.1': (time.time(), 1), '192.0.2.2': (time.time(), 2)})
try:
    d.latency_report()
except RuntimeError as e:
    check(False, 'the status walked the boxes that said "too many requests" while one was added: %s' % e)
finally:
    zigmon.ShellyRPC._rate_limited = _keep

# b. a socket's push lands while the status walks its reading: what a reader
# holds must never change under it (the push writes a new dict)
_p = d.plug_by_name('Sock-1')
d.poll_plug(_p, force=True)
_held = (d.live.get(_p.device_id) or {}).get('payload')
check(_held is not None and _held is _p.flat, 'after a poll the socket\'s reading is not the one in memory')
_before = dict(_held or {})
deliver('shellyrace/events/rpc', {'method': 'NotifyStatus', 'params': {
    'switch:1': {'id': 1, 'apower': 7.5, 'aenergy': {'by_minute': [1.0], 'minute_ts': 1, 'total': 3.0},
                 'race_field_new': 1}}})
check(_held == _before, 'a push from the socket wrote into the reading a status may be walking: %r'
      % sorted(set(_held or {}) - set(_before)))
_now = (d.live.get(_p.device_id) or {}).get('payload') or {}
check(_now.get('switch.race_field_new') == 1 and _p.flat.get('switch.race_field_new') == 1
      and _now is _p.flat, 'the push did not reach the reading the status shows')
check(_p.flat.get('switch.apower') == 7.5, 'the push\'s watts are not in the socket\'s reading')
# ...and so with a switching's own "it is on now"
_held = _p.flat
_before = dict(_held)
d._plug_switched(_p, not bool(_p.output), 'the race test')
check(_held == _before, 'a switching wrote into the reading a status may be walking')
check((d.live.get(_p.device_id) or {}).get('payload') is _p.flat, 'the switching left the house\'s memory behind')

# c. the device list forgotten (a rename, a device leaving) while it is read back
_store = d.store
_store._forget_device('nothing')
_real_loads = zigmon.json.loads
_poked = []


def _loads_and_forget(*a, **k):
    if not _poked and threading.current_thread() is threading.main_thread():
        _poked.append(1)
        _store._forget_device(ieee('TH-03'))          # "another thread" renames one meanwhile
    return _real_loads(*a, **k)


zigmon.json.loads = _loads_and_forget
try:
    _listed = _store.devices()
    check(len(_listed) >= 60, 'the device list read back while forgotten is short: %d' % len(_listed))
except TypeError as e:
    check(False, 'the device list was forgotten while it was read back, and the read failed: %s' % e)
finally:
    zigmon.json.loads = _real_loads
check(bool(_poked), 'the device list was not read back at all')
check(_store._dev_list is None, 'a device list read before a change was kept after it')
check(len(_store.devices()) >= 60 and _store._dev_list is not None, 'the device list is not kept again afterwards')

# d. a command said while another thread's tidies the table of commands said
_old = time.monotonic() - 600
d._cmd_mids = WalkedWhileWritten({1000 + i: _old for i in range(2001)})
try:
    _info = d.say(BASE + '/Lamp-0/set', json.dumps({'state': 'ON'}), qos=1)
    check(_info is not None, 'a command said came back with nothing')
    check(len(d._cmd_mids) < 100, 'the old commands were not tidied away: %d' % len(d._cmd_mids))
except RuntimeError as e:
    check(False, 'a command said while another was added to the table failed: %s' % e)

# e. a message sent while another rule's is written down as sent
d.store.set_meta('messages', json.dumps([{'id': 'race-msg', 'name': 'Race', 'text': 'race words %d',
                                          'level': 'info', 'quiet_s': 60, 'enabled': True,
                                          'sms': False, 'ntfy': False, 'telegram': False}]))
d._msg_last = WalkedWhileWritten({'old-%d' % i: time.time() - 90000 for i in range(501)})
try:
    d.send_message('race-msg', 'the race test')
    check(len(d._msg_last) < 10, 'the messages sent long ago were not tidied away: %d' % len(d._msg_last))
except RuntimeError as e:
    check(False, 'a message sent while another was written down failed: %s' % e)

api.stop() if hasattr(api, 'stop') else None
_srv.shutdown()
shutil.rmtree(W, ignore_errors=True)
if bad:
    print('\n%d FAILED' % len(bad))
    os._exit(1)
print('\nall race checks passed')
os._exit(0)
