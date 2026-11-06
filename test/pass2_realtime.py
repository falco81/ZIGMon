#!/usr/bin/env python3
"""(5.44.1) Realtime, the second pass: the first press after a quiet spell.

    python3 test/pass2_realtime.py                 # the checks, about a minute
    ZIGMON_BENCH=1 python3 test/pass2_realtime.py  # the before/after table (several minutes)

The kept connection to a box is dropped after plug_keepalive_s (3 s), so the
first command after a quiet spell - walking into a room - used to open a new
TCP connection on the way of the command. Over the Wi-Fi of a house that is
5-30 ms before the relay is even asked. Here every connect to a box is charged
a handshake (HANDSHAKE_MS, 20 by default) on the thread that makes it, and the
checks say on which thread the connects happen and when the box has the
command.

Ports 19300 (a Shelly a rule switches), 19301 (the API), 19302 (a four-socket
strip a scene switches), 19303 (a box nobody switches), 19304 (a box that is
off: nothing listens).
"""
import collections
import gc
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, os.environ.get('ZIGMON_SRC') or str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

BOXPORT, APIPORT, STRIPPORT, IDLEPORT, OFFPORT = 19300, 19301, 19302, 19303, 19304
BOXPORTS = (BOXPORT, STRIPPORT, IDLEPORT, OFFPORT)
W = Path(tempfile.mkdtemp(prefix='zigmon-pass2rt-'))
BENCH = bool(os.environ.get('ZIGMON_BENCH'))
HANDSHAKE = float(os.environ.get('HANDSHAKE_MS') or 20) / 1000.0
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


# ---- a Wi-Fi handshake, charged to whoever connects --------------------------------
CONNECTS = []                       # (perf_counter, thread name, port)
_real_create = socket.create_connection


def _charged_create(address, *a, **k):
    port = address[1]
    if port in BOXPORTS:
        CONNECTS.append((time.perf_counter(), threading.current_thread().name, port))
        time.sleep(HANDSHAKE)       # SYN, SYN-ACK across the house
    return _real_create(address, *a, **k)


socket.create_connection = _charged_create


# ---- the boxes ---------------------------------------------------------------------
ARRIVED = collections.defaultdict(list)          # port -> [(perf_counter, method, socket id)]
BOOT = collections.Counter()                     # port -> how many times it rebooted
HANDLERS = collections.Counter()                 # port -> connections accepted
STATE = collections.defaultdict(lambda: [False] * 4)
CLOSE_AFTER = {}


class Box(BaseHTTPRequestHandler):
    """A Shelly Gen2+ that keeps the connection open, and can be rebooted:
    a connection from before the reboot is answered by a reset, as a box that
    has forgotten it does."""
    protocol_version = 'HTTP/1.1'
    wbufsize = 65536
    timeout = 60

    def log_message(self, *a):
        pass

    def setup(self):
        port = self.server.server_address[1]
        HANDLERS[port] += 1
        self.boot = BOOT[port]
        BaseHTTPRequestHandler.setup(self)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        port = self.server.server_address[1]
        if self.boot != BOOT[port]:
            # the box rebooted since this connection was made: a reset, no answer
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b'\x01\x00\x00\x00\x00\x00\x00\x00')
            self.close_connection = True
            self.connection.close()
            return
        req = json.loads(body or b'{}')
        method, params = req.get('method'), req.get('params') or {}
        sid = int(params.get('id', 0))
        ARRIVED[port].append((time.perf_counter(), method, sid))
        state = STATE[port]
        if method == 'Switch.Set':
            out = {'was_on': state[sid]}
            state[sid] = bool(params.get('on'))
        elif method == 'Switch.Toggle':
            out = {'was_on': state[sid]}
            state[sid] = not state[sid]
        elif method in ('Shelly.GetStatus', 'Switch.GetStatus'):
            out = {'switch:%d' % k: {'id': k, 'output': state[k], 'apower': 0.0, 'voltage': 231.0,
                                     'aenergy': {'total': 1.0}} for k in range(4)}
            if method == 'Switch.GetStatus':
                out = out['switch:%d' % sid]
        elif method == 'Shelly.GetDeviceInfo':
            out = {'id': 'shellyplug-pass2', 'model': 'S3PL-00112EU', 'gen': 3, 'ver': '1.7.1'}
        else:
            out = {}
        raw = json.dumps({'id': req.get('id'), 'result': out}).encode()
        if CLOSE_AFTER.get(port):
            # a firmware that closes the connection once it has answered,
            # with a FIN but without saying "Connection: close"
            self.close_connection = True
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


# ---- paho's network thread, as in pass1_realtime -------------------------------------
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


class FakePaho(object):
    def __init__(self):
        self.cv = threading.Condition()
        self.inq = collections.deque()
        self.published = []
        threading.Thread(target=self.loop, name='paho', daemon=True).start()

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append((time.perf_counter(), topic, payload))
        return Info()

    def subscribe(self, *a, **k):
        return (0, 1)

    def message_callback_add(self, *a, **k):
        pass

    def deliver(self, topic, payload):
        with self.cv:
            self.inq.append((topic, payload, time.perf_counter()))
            self.cv.notify()

    def loop(self):
        while True:
            with self.cv:
                while not self.inq:
                    self.cv.wait()
                topic, payload, _at = self.inq.popleft()
            try:
                d._on_message(None, None, Msg(topic, payload))
            except Exception as e:
                print('  on_message raised: %r' % e)


# ---- the house -------------------------------------------------------------------------
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': APIPORT, 'token_file': str(W / 'api-token'),
                      'pin': '1234', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': str(W / 'z.log'),
                      'state_dir': str(W / 'state'), 'log_to_journal': False, 'weather': False,
                      'plug_timeout': 3.0, 'binding_debounce_ms': 0, 'plug_poll_interval': 3600,
                      'networkmap_interval': 0})
(W / 'state').mkdir()
zigmon.open_log()
zigmon.start_log_writer()
BASE = zigmon.CONFIG['base_topic'].rstrip('/')

servers = {}


def serve(port):
    srv = ThreadingHTTPServer(('127.0.0.1', port), Box)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name='box%d' % port, daemon=True).start()
    servers[port] = srv


for _port in (BOXPORT, STRIPPORT, IDLEPORT):
    serve(_port)

d = zigmon.Daemon()
d.backup_dir = lambda: W / 'backups'
box = '127.0.0.1:%d'
plugs = [{'name': 'Light-A', 'host': box % BOXPORT, 'switch_id': 0, 'kind': 'plug', 'host_state': 'enabled'},
         {'name': 'Nobody', 'host': box % IDLEPORT, 'switch_id': 0, 'kind': 'plug', 'host_state': 'enabled'},
         {'name': 'Gone', 'host': box % OFFPORT, 'switch_id': 0, 'kind': 'plug', 'host_state': 'enabled'}]
plugs += [{'name': 'Strip-%d' % i, 'host': box % STRIPPORT, 'switch_id': i, 'kind': 'plug',
           'host_state': 'enabled'} for i in range(4)]
d.store.set_meta('managed', json.dumps({'plugs': plugs, 'sensors': []}))
d.reload_devices()
paho = FakePaho()
d.client, d.connected = paho, True
d._verify_zigbee_set = lambda *a, **k: None

for _name, _exposes in [('PIR-A', {'occupancy': {}}), ('PIR-G', {'occupancy': {}}), ('Door', {'contact': {}}),
                        ('Lamp', {'state': {}})]:
    d.store.upsert_device({'id': 'zigbee:' + _name, 'name': _name, 'source': 'zigbee',
                           'kind': 'Router' if _name == 'Lamp' else 'sensor', 'exposes': _exposes})
    d.names[_name] = 'zigbee:' + _name


def rule(rid, dev, key, value, plug, do):
    return {'id': rid, 'device': 'zigbee:' + dev, 'key': key, 'op': '==', 'value': value, 'plug': plug,
            'do': do, 'enabled': True, 'cooldown_s': 0}


d.store.set_meta('rules', json.dumps([
    rule('a-on', 'PIR-A', 'occupancy', 1, 'Light-A', 'on'), rule('a-off', 'PIR-A', 'occupancy', 0, 'Light-A', 'off'),
    rule('g-on', 'PIR-G', 'occupancy', 1, 'Gone', 'on'),
    rule('d-open', 'Door', 'contact', 0, 'scene:sc-strip', 'on'),
    rule('d-shut', 'Door', 'contact', 1, 'scene:sc-dark', 'on'),
]))
d.store.set_meta('scenes', json.dumps([
    {'id': 'sc-strip', 'name': 'Strip', 'enabled': True,
     'actions': [{'target': 'Strip-%d' % i, 'do': 'on'} for i in range(4)]},
    {'id': 'sc-dark', 'name': 'Dark', 'enabled': True,
     'actions': [{'target': 'Strip-%d' % i, 'do': 'off'} for i in range(4)]}]))
d._running = True
threading.Thread(target=d.rule_worker, name='rules', daemon=True).start()
threading.Thread(target=d.rule_worker, args=(True,), name='rules-presence', daemon=True).start()
threading.Thread(target=d.timer_loop, name='timers', daemon=True).start()
threading.Thread(target=d.plug_loop, name='plugs', daemon=True).start()
d.gc_settle()
FLIP = collections.defaultdict(bool)


def report(name, payload):
    paho.deliver('%s/%s' % (BASE, name), json.dumps(payload).encode())


def pir_to_box(port=BOXPORT, sensor='PIR-A', limit=4.0):
    """One PIR report -> the command at the box: (ms, connects on the way)."""
    FLIP[sensor] = not FLIP[sensor]
    n0, c0 = len(ARRIVED[port]), len(CONNECTS)
    t0 = time.perf_counter()
    report(sensor, {'occupancy': FLIP[sensor], 'battery': 90})
    deadline = time.time() + limit
    while time.time() < deadline:
        cmds = [a for a in ARRIVED[port][n0:] if a[1] in ('Switch.Set', 'Switch.Toggle')]
        if cmds:
            ms = (cmds[0][0] - t0) * 1000
            on_path = [c for c in CONNECTS[c0:] if c[2] == port and c[0] <= cmds[0][0]
                       and c[1] != 'plug-warmer']
            return ms, on_path
        time.sleep(0.0005)
    return None, []


def door(limit=4.0):
    FLIP['Door'] = not FLIP['Door']
    n0, c0 = len(ARRIVED[STRIPPORT]), len(CONNECTS)
    t0 = time.perf_counter()
    report('Door', {'contact': not FLIP['Door']})
    deadline = time.time() + limit
    while time.time() < deadline:
        cmds = [a for a in ARRIVED[STRIPPORT][n0:] if a[1] == 'Switch.Set']
        if len(cmds) >= 4:
            return [(a[0] - t0) * 1000 for a in cmds[:4]], [a[2] for a in cmds[:4]], \
                [c for c in CONNECTS[c0:] if c[2] == STRIPPORT and c[1] != 'plug-warmer']
        time.sleep(0.0005)
    return None, None, []


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else float('nan')


def quiet(seconds):
    """Nothing asked of the boxes for this long - the kept connections age out."""
    time.sleep(seconds)


WARM = hasattr(zigmon.ShellyRPC, '_warm')
# longer than the kept connection lives, counted from the confirming poll after a command too
QUIET = zigmon.CONFIG['plug_keepalive_s'] * 2 + 2

try:
    time.sleep(1.0)                          # the first poll round, the warmer's first list
    for _ in range(3):
        pir_to_box()
        time.sleep(0.1)

    if BENCH:
        print('PIR -> command at the box, after a quiet spell; handshake %d ms; warm spare %s'
              % (HANDSHAKE * 1000, 'on' if WARM else 'not in this build'))
        for warm in ((1, 4, 0) if WARM else (0,)):
            zigmon.CONFIG['plug_warm_spare'] = warm
            time.sleep(3.5)
            for spell, n in ((0.5, 10), (10, 6), (60, 4)):
                rows, conns = [], 0
                for _ in range(n):
                    quiet(spell)
                    ms, on_path = pir_to_box()
                    if ms is not None:
                        rows.append(ms)
                    conns += len(on_path)
                print('  warm %-5s quiet %5.1f s: n=%d p50 %.2f max %.2f ms; connects on the command path %d'
                      % (warm, spell, len(rows), pct(rows, .5), max(rows) if rows else -1, conns))
            rows, conns = [], 0
            for _ in range(4):
                quiet(10)
                times, _order, on_path = door()
                if times:
                    rows.append(max(times))
                conns += len(on_path)
            print('  warm %-5s strip of four, quiet 10 s: last socket p50 %.2f max %.2f ms; connects %d'
                  % (warm, pct(rows, .5), max(rows) if rows else -1, conns))
        zigmon.CONFIG['plug_warm_spare'] = 1
    else:
        # -- 1. no handshake on the way of the first press after a quiet spell -----------
        print('the first press after a quiet spell (> plug_keepalive_s), handshake %d ms' % (HANDSHAKE * 1000))
        rows, on_path_all = [], []
        for _ in range(3):
            quiet(QUIET)
            ms, on_path = pir_to_box()
            rows.append(ms)
            on_path_all += on_path
        print('  PIR -> command at the box: %s ms; connects on the command path: %d'
              % ([None if r is None else round(r, 2) for r in rows], len(on_path_all)))
        check(None not in rows, 'a press after a quiet spell never reached the box: %r' % rows)
        check(not on_path_all, 'the first press after a quiet spell opened %d TCP connection(s) on its way '
              '(threads %s) - a handshake before the relay is asked'
              % (len(on_path_all), sorted({c[1] for c in on_path_all})))
        check(None not in rows and max(rows) < HANDSHAKE * 1000 * 0.75,
              'the first press after a quiet spell reached the box %.1f ms after the report (a handshake is '
              '%.0f ms)' % (max(r for r in rows if r is not None) if any(rows) else -1, HANDSHAKE * 1000))

        # -- 2. a spare is held for the box a rule switches ------------------------------
        quiet(0.5)
        n_before = len(ARRIVED[BOXPORT])
        if WARM:
            check(bool(zigmon.ShellyRPC._warm.get(box % BOXPORT)),
                  'no warm spare held for a box a rule switches')
        # -- 2b. a kept connection the box has closed is not asked on -------------------
        print('a kept connection the box has closed (FIN, no "Connection: close") is not asked on')
        CLOSE_AFTER[BOXPORT] = True
        pir_to_box()
        time.sleep(0.4)
        rows, on_path_all = [], []
        for _ in range(3):
            ms, on_path = pir_to_box()
            rows.append(ms)
            on_path_all += on_path
            time.sleep(0.4)
        CLOSE_AFTER[BOXPORT] = False
        print('  %s ms; connects on the command path: %d' % ([None if r is None else round(r, 2) for r in rows],
                                                            len(on_path_all)))
        check(None not in rows and max(rows) < HANDSHAKE * 1000 * 0.75 and not on_path_all,
              'a kept connection the box had closed was asked on, failed, and the command went again on a new '
              'one: %r ms, %d connects on the way' % (rows, len(on_path_all)))
        n_before = len(ARRIVED[BOXPORT])

        # -- 3. a box rebooting while its spare (and a kept connection) is held ---------
        print('a box that reboots while its spare is held: the command still goes, once')
        quiet(0.3)
        BOOT[BOXPORT] += 1                         # every connection open now is forgotten by the box
        ms, _ = pir_to_box()
        sets = [a for a in ARRIVED[BOXPORT][n_before:] if a[1] in ('Switch.Set', 'Switch.Toggle')]
        print('  after the reboot: %s ms, %d command(s) at the box' % (None if ms is None else round(ms, 1),
                                                                      len(sets)))
        check(ms is not None and len(sets) == 1, 'after a reboot of the box with a spare held, the command '
              'did not arrive exactly once: %r ms, %d at the box' % (ms, len(sets)))
        check(ms is not None and ms < 500, 'after a reboot the command took %r ms - a stale connection waited '
              'out a timeout' % ms)
        # and the kept connection from that very command, rebooted under it
        time.sleep(0.2)
        n_before = len(ARRIVED[BOXPORT])
        BOOT[BOXPORT] += 1
        ms, _ = pir_to_box()
        sets = [a for a in ARRIVED[BOXPORT][n_before:] if a[1] in ('Switch.Set', 'Switch.Toggle')]
        check(ms is not None and len(sets) == 1 and ms < 500, 'a kept connection rebooted under it: %r ms, '
              '%d at the box' % (ms, len(sets)))
        print('  kept connection rebooted under it: %s ms, %d at the box' % (None if ms is None else round(ms, 1),
                                                                           len(sets)))

        # -- 4. a strip after a quiet spell: in order, the first without a handshake -----
        print('a scene of four sockets on one strip after a quiet spell')
        orders, firsts = [], []
        for _ in range(2):
            quiet(QUIET)
            times, order, on_path = door()
            check(times is not None, 'a scene of four after a quiet spell did not reach all four sockets')
            if times:
                orders.append(order)
                firsts.append(min(times))
        print('  sockets in the order the box had them: %r; first at %s ms'
              % (orders, [round(x, 1) for x in firsts]))
        check(firsts and max(firsts) < HANDSHAKE * 1000 * 0.75,
              'the first socket of a strip after a quiet spell waited for a handshake: %r ms' % firsts)
        check(all(sorted(o) == [0, 1, 2, 3] for o in orders), 'a socket of the strip was missed: %r' % orders)
        if WARM:
            # four kept ready for a strip a scene switches as one: none of the four waits
            zigmon.CONFIG['plug_warm_spare'] = 4
            lasts, conns = [], 0
            for _ in range(2):
                quiet(QUIET)
                times, order, on_path = door()
                if times:
                    lasts.append(max(times))
                conns += len(on_path)
            zigmon.CONFIG['plug_warm_spare'] = 1
            print('  with four kept ready: the last of four at %s ms, %d connects on the way'
                  % ([round(x, 1) for x in lasts], conns))
            check(len(lasts) == 2 and max(lasts) < HANDSHAKE * 1000 * 0.75 and not conns,
                  'four spares for a strip, yet a socket waited for a handshake: %r ms, %d connects'
                  % (lasts, conns))

        # -- 5. the warmer costs nothing for a box nobody switches, and makes no storm --
        print('the warmer leaves alone a box nobody switches, and backs off from one that is off')
        idle = [c for c in CONNECTS if c[2] == IDLEPORT and c[1] == 'plug-warmer']
        gone = [c for c in CONNECTS if c[2] == OFFPORT and c[1] == 'plug-warmer']
        span = time.perf_counter() - CONNECTS[0][0]
        print('  over %.0f s: %d connects to the box nobody switches, %d to the box that is off'
              % (span, len(idle), len(gone)))
        check(not idle, 'the warmer opened %d connection(s) to a box nobody switches' % len(idle))
        # 5, 10, 20, 40 s apart: a handful in a minute, not one every two seconds
        gaps = [b[0] - a[0] for a, b in zip(gone, gone[1:])]
        check(len(gone) <= 6 and all(b >= a * 1.5 for a, b in zip(gaps, gaps[1:])),
              'the warmer tried a box that is off %d times in %.0f s (gaps %r) - a storm'
              % (len(gone), span, [round(g, 1) for g in gaps]))
        if WARM:
            rot = [c for c in CONNECTS if c[2] == BOXPORT and c[1] == 'plug-warmer']
            print('  %d spares opened to the box a rule switches (%.1f a second)' % (len(rot), len(rot) / span))
            check(len(rot) <= span / (zigmon.CONFIG['plug_keepalive_s'] * 0.5) + 6,
                  'the warmer opened %d spares in %.0f s to one box - more than one per renewal' % (len(rot), span))

        # -- 6. turned off, the spares go ------------------------------------------------
        if WARM:
            zigmon.CONFIG['plug_warm_spare'] = 0
            time.sleep(0.5)
            zigmon.ShellyRPC._warm_wake.set()
            time.sleep(5.5)
            check(not any(zigmon.ShellyRPC._warm.values()), 'plug_warm_spare off, yet %d spare(s) still held'
                  % len(zigmon.ShellyRPC._warm))
            zigmon.CONFIG['plug_warm_spare'] = 1
finally:
    d._stop.set()
    zigmon.ShellyRPC._warm_wake.set() if WARM else None
    for srv in servers.values():
        srv.shutdown()
        srv.server_close()
    time.sleep(0.3)
    shutil.rmtree(str(W), ignore_errors=True)

if bad:
    print('%d check(s) failed' % len(bad))
    sys.exit(1)
print('all pass2_realtime checks passed')
