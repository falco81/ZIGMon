#!/usr/bin/env python3
"""5.44.1, pass 2: the whole house, lived end to end with a clock of its own.

    python3 test/pass2_day.py

One daemon in-process, with everything it talks to standing in beside it:

  * a broker and a Zigbee2MQTT (a paho of our own: what is published to
    <name>/set comes back as the device's report, on the broker's thread, as
    on_message would bring it; a broker that goes away and comes back with
    its retained messages);
  * four Shelly sockets over HTTP, keep-alive (test/mockplug.py's own
    handler, one per socket, one of them pulled out for a while);
  * the TRB140 (test/mocksms.py) for the texts;
  * ntfy and Telegram, caught as they leave;
  * a clock: time.time, the local time and datetime.now, all of them the
    house's, Europe/Prague, moved on by the test - through the night the
    clocks go back (25 October 2026) and on to the 1st of November.

Sixty-five devices; schedules, the heating with a window, motion lights,
buttons, scenes, a socket pulled out, the broker restarting, a battery
sinking, a sensor going quiet in the night, texts in and out, the digest,
the backup, the fold of the hour, the monthly summary, a page polling the
status and the perf meter throughout, and restarts at noon and at 04:00.
Every command to a device is checked for what and when; what 5.44.0 got
wrong of it (each of these fails there):

  * two Shelly boxes behind one address (a port each) were one box to the
    "reading of the whole box": one pulled out went on showing the other's
    reading, online, and "lost contact" was never said;
  * "a device going quiet, unreachable or back": a socket's "contact
    restored" and a Zigbee device "online" again were never told;
  * the broker's retained copy, replayed at a restart, was taken for the
    device speaking: a thermometer dead since the evening was "seen" at
    04:00, and said to have gone quiet a second time (a second text);
  * ...and the watchdog forgot across a restart what it had already said;
  * the monthly summary on the 1st read the energy figures kept for the
    pages, worked out in the old month: "October: 0.0 kWh".

PASS2_DAEMON=dir: the daemon (zigmon.py) of that folder.
PASS2_ONLY=saturday,sunday,...: only those parts of the week.
PASS2_KEEP=1: the folder of the run is kept.
"""
import collections
import datetime as _dt
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time as _time
import types
from http.server import ThreadingHTTPServer
from pathlib import Path

os.environ['TZ'] = 'Europe/Prague'
_time.tzset()

HERE = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get('PASS2_DAEMON') or str(HERE))
W = Path(tempfile.mkdtemp(prefix='zigmon-pass2-day-'))
PORT_API, PORT_SMS = 19320, 19321
PLUG_PORTS = {'Coffee': 19322, 'Kettle': 19323, 'Fan': 19324, 'Heater': 19325}
VERBOSE = bool(os.environ.get('PASS2_VERBOSE'))
bad = []
notes = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def note(what):
    notes.append(what)
    if VERBOSE:
        print('  note: ' + what)


# ---------------------------------------------------------------------------
# the clock: one moment the whole daemon reads
# ---------------------------------------------------------------------------
class Clock(object):
    """The house's moment: real time flowing, plus every jump the test makes.
    The steady clock jumps with it - time that passed, not a clock stepped."""

    def __init__(self, start):
        self.start = float(start)
        self.real0 = _time.monotonic()
        self.jumped = 0.0

    def now(self):
        return self.start + (_time.monotonic() - self.real0) + self.jumped

    def mono(self):
        return _time.monotonic() + self.jumped

    def advance(self, s):
        self.jumped += float(s)

    def to(self, t):
        """On to that moment (never back)."""
        gap = float(t) - self.now()
        if gap > 0:
            self.advance(gap)


def moment(y, mo, d, h, mi, s=0, dst=-1):
    return _time.mktime((y, mo, d, h, mi, s, 0, 0, dst))


CLOCK = Clock(moment(2026, 10, 24, 4, 50))     # Saturday, before dawn


def _fake_time_module():
    m = types.ModuleType('time')
    for k in dir(_time):
        if not k.startswith('__'):
            setattr(m, k, getattr(_time, k))
    m.time = CLOCK.now
    m.time_ns = lambda: int(CLOCK.now() * 1e9)
    m.monotonic = CLOCK.mono
    m.monotonic_ns = lambda: int(CLOCK.mono() * 1e9)
    m.localtime = lambda t=None: _time.localtime(CLOCK.now() if t is None else t)
    m.gmtime = lambda t=None: _time.gmtime(CLOCK.now() if t is None else t)
    m.ctime = lambda t=None: _time.ctime(CLOCK.now() if t is None else t)
    m.asctime = lambda t=None: _time.asctime(_time.localtime(CLOCK.now()) if t is None else t)
    m.strftime = lambda fmt, t=None: _time.strftime(fmt, _time.localtime(CLOCK.now()) if t is None else t)
    return m


class FakeDatetime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return _dt.datetime.fromtimestamp(CLOCK.now(), tz).replace(tzinfo=tz) if tz else \
            _dt.datetime.fromtimestamp(CLOCK.now())

    @classmethod
    def today(cls):
        return _dt.datetime.fromtimestamp(CLOCK.now())


def hm(t=None):
    return _time.strftime('%a %d %H:%M:%S %Z', _time.localtime(CLOCK.now() if t is None else t))


# ---------------------------------------------------------------------------
# the daemon
# ---------------------------------------------------------------------------
sys.path.insert(0, str(SRC))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

zigmon.time = _fake_time_module()
zigmon.datetime = FakeDatetime


# -- a paho of our own, and a Zigbee2MQTT behind it -------------------------
class Info(object):
    def __init__(self, mid):
        self.mid = mid
        self.rc = 0

    def is_published(self):
        return True

    def wait_for_publish(self, timeout=None):
        return True


OUT = []        # (perf_counter, where, payload): every command, in real time, for the latencies


class Broker(object):
    """The broker and Zigbee2MQTT in one: retained messages, and a device's
    report for every /set it is given."""

    def __init__(self):
        self.up = True
        self.retained = {}
        self.sent = []                  # (clock, topic, payload) everything the daemon published
        self.client = None
        self.devices = {}               # friendly name -> its state (dict)
        self.echo = True
        self.q = collections.deque()
        self.kick = threading.Event()
        self.mid = 0
        threading.Thread(target=self._loop, name='paho-fake', daemon=True).start()

    def deliver(self, topic, payload, retain=False):
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        if retain or topic in self.retained:          # a retained topic keeps its newest
            self.retained[topic] = payload
        at = _time.perf_counter()
        self.q.append((topic, payload, False))
        self.kick.set()
        return at

    def _loop(self):
        while True:
            self.kick.wait(0.5)
            self.kick.clear()
            while self.q:
                topic, payload, retain = self.q.popleft()
                c = self.client
                if c is None or not self.up or not c.connected or c.on_message is None:
                    continue
                msg = types.SimpleNamespace(topic=topic, payload=payload.encode() if isinstance(payload, str)
                                            else payload, retain=retain, qos=0)
                try:
                    c.on_message(c, None, msg)
                except Exception as e:                  # noqa: BLE001
                    print('  on_message raised: %s' % e)

    def published(self, topic, payload, qos, retain):
        self.mid += 1
        self.sent.append((CLOCK.now(), topic, payload))
        OUT.append((_time.perf_counter(), topic, payload))
        if topic == 'zigmon/ping':
            self.q.append((topic, payload, False))
            self.kick.set()
        elif topic.startswith('zigbee2mqtt/') and topic.endswith('/set') and self.echo:
            name = topic[len('zigbee2mqtt/'):-len('/set')]
            if name in self.devices:
                try:
                    body = json.loads(payload)
                except ValueError:
                    body = {}
                st = self.devices[name]
                for k, v in body.items():
                    if v == 'TOGGLE':
                        v = 'OFF' if st.get(k) == 'ON' else 'ON'
                    st[k] = v
                    if k == 'occupied_heating_setpoint':
                        st['current_heating_setpoint'] = v
                self.q.append(('zigbee2mqtt/' + name, json.dumps(st), False))
                self.kick.set()
        if retain:
            if payload is None or payload == '':
                self.retained.pop(topic, None)
            else:
                self.retained[topic] = payload
        return Info(self.mid)

    def restart(self, away_s):
        """The broker goes, and comes back with what it keeps."""
        c = self.client
        self.up = False
        c.connected = False
        c.on_disconnect(c, None, {}, 7, None)
        CLOCK.advance(away_s)
        self.up = True
        c.connected = True
        c.on_connect(c, None, {}, 0, None)
        for topic, payload in list(self.retained.items()):
            self.q.append((topic, payload, True))
        self.kick.set()


BROKER = Broker()


class FakeClient(object):
    def __init__(self, *a, **k):
        self.connected = False
        self.on_message = self.on_connect = self.on_disconnect = None
        self.subscribed = []
        BROKER.client = self

    def username_pw_set(self, *a, **k):
        pass

    def tls_set(self, *a, **k):
        pass

    def tls_insecure_set(self, *a, **k):
        pass

    def reconnect_delay_set(self, *a, **k):
        pass

    def max_inflight_messages_set(self, *a):
        pass

    def max_queued_messages_set(self, *a):
        pass

    def will_set(self, *a, **k):
        pass

    def connect_async(self, *a, **k):
        pass

    def loop_start(self):
        self.connected = True
        self.on_connect(self, None, {}, 0, None)
        for topic, payload in list(BROKER.retained.items()):
            BROKER.q.append((topic, payload, True))
        BROKER.kick.set()

    def loop_stop(self):
        pass

    def disconnect(self):
        self.connected = False

    def subscribe(self, topics, *a, **k):
        self.subscribed = topics
        return (0, 1)

    def publish(self, topic, payload=None, qos=0, retain=False):
        return BROKER.published(topic, payload, qos, retain)

    def is_connected(self):
        return self.connected


zigmon.mqtt = types.SimpleNamespace(Client=FakeClient)


# -- the Shelly sockets: test/mockplug.py's handler, one per socket ------------
class Calls(list):
    def append(self, item):
        list.append(self, (CLOCK.now(),) + tuple(item))
        if item and item[0] == 'Switch.Set':
            OUT.append((_time.perf_counter(), 'plug:%s' % self.name, json.dumps(item[1])))


def mock_plug(name, port):
    src = (HERE / 'test' / 'mockplug.py').read_text().rsplit('ThreadingHTTPServer((', 1)[0]
    ns = {'__name__': 'mockplug_' + name}
    was = sys.argv
    sys.argv = ['mockplug', str(port)]
    try:
        exec(compile(src, 'mockplug.py', 'exec'), ns)
    finally:
        sys.argv = was
    ns['CALLS'] = Calls()
    ns['CALLS'].name = name
    ns['H'].protocol_version = 'HTTP/1.1'          # keep-alive, as a Shelly does
    plug = types.SimpleNamespace(name=name, port=port, ns=ns, server=None, dead=False)
    answer = ns['H'].do_POST

    def do_post(self):
        if plug.dead:                   # pulled out: a connection kept alive goes too
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return
        return answer(self)
    ns['H'].do_POST = do_post

    def up():
        plug.dead = False
        s = ThreadingHTTPServer(('127.0.0.1', port), ns['H'])
        s.daemon_threads = True
        plug.server = s
        threading.Thread(target=s.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()

    def down():
        plug.dead = True
        plug.server.shutdown()
        plug.server.server_close()
        plug.server = None

    plug.up, plug.down = up, down
    up()
    return plug


PLUGS = {n: mock_plug(n, p) for n, p in PLUG_PORTS.items()}


def plug_sets(name, since=0.0):
    """(clock, on) of each Switch.Set the socket was given since then."""
    return [(c[0], bool((c[2] or {}).get('on'))) for c in PLUGS[name].ns['CALLS']
            if c[1] == 'Switch.Set' and c[0] >= since]


# -- the TRB140 ---------------------------------------------------------------
sms_proc = subprocess.Popen([sys.executable, str(HERE / 'test' / 'mocksms.py'), str(PORT_SMS), 'admin', 'pw-sms'],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def sms_sent():
    try:
        c = http.client.HTTPConnection('127.0.0.1', PORT_SMS, timeout=3)
        c.request('GET', '/')
        return json.loads(c.getresponse().read() or b'{}').get('sent') or []
    except (OSError, ValueError):
        return []


# -- ntfy and Telegram, caught as they leave -------------------------------
PUSHED = []                       # (clock, road, title, text)


def fake_web_open(req, timeout=None, purpose='', **k):
    url = req.full_url if hasattr(req, 'full_url') else str(req)
    if purpose == 'alerts':
        body = req.data.decode() if getattr(req, 'data', None) else ''
        if 'api.telegram.org' in url:
            road = 'telegram'
            try:
                body = json.loads(body).get('text') or ''
            except ValueError:
                pass
            title = body.split('\n', 1)[0]
        else:
            road = 'ntfy'
            title = req.get_header('Title') or ''
            if title.startswith('=?UTF-8?B?'):
                import base64
                title = base64.b64decode(title[10:-2]).decode('utf-8')
        PUSHED.append((CLOCK.now(), road, title, body))
        return types.SimpleNamespace(read=lambda *a: b'{"ok":true}', status=200, close=lambda: None)
    raise OSError('no network here (%s)' % url[:60])


zigmon.web_open = fake_web_open

# ---------------------------------------------------------------------------
# the house's settings
# ---------------------------------------------------------------------------
zigmon.load_config()
zigmon.CONFIG.update({
    'db_file': str(W / 'zigmon.db'), 'api_port': PORT_API, 'api_host': '127.0.0.1',
    'token_file': str(W / 'api-token'), 'state_dir': str(W), 'backup_dir': str(W / 'backups'),
    'log_file': str(W / 'zigmon.log'), 'log_to_journal': False, 'mqtt_host': '127.0.0.1',
    'plugs': [{'name': n, 'host': '127.0.0.1:%d' % p} for n, p in PLUG_PORTS.items()],
    'sensors': [], 'latitude': 50.08, 'longitude': 14.42, 'weather': False,
    'plug_poll_interval': 2, 'backup_enabled': 1, 'backup_time': '03:15', 'backup_keep': 3,
    'digest_at': '21:30', 'monthly_summary': True, 'price_per_kwh': 6.0, 'currency': 'CZK',
    'notify_ntfy': 'http://127.0.0.1:19326/house', 'notify_telegram_token': '123:fake-token',
    'notify_telegram_chat': '42',
    'sms_enabled': 1, 'sms_host': '127.0.0.1:%d' % PORT_SMS, 'sms_user': 'admin', 'sms_password': 'pw-sms',
    'sms_quiet_from': '22:30', 'sms_quiet_to': '07:00', 'sms_send_gap_s': 0, 'sms_poll_s': 0,
    'sms_reply': True, 'perf_meter': 1,
    'networkmap_interval': 0, 'pin': '',
})
os.environ.pop('ZIGMON_ROOT_RUN', None)


zigmon.Daemon.php_loop = lambda self: None          # the machine's own PHP is not this house's
zigmon.Daemon.system_loop = lambda self: None


def start_daemon():
    d = zigmon.Daemon()
    d.backup_dir = lambda: W / 'backups'
    d.root_chores = lambda: None
    d.check_system_alerts = lambda: None
    return d


if __name__ != '__main__':
    raise SystemExit(0)


# ---------------------------------------------------------------------------
# sixty-five devices: 61 on Zigbee, four Shelly sockets
# ---------------------------------------------------------------------------
def _bin(prop, access=1):
    return {'type': 'binary', 'property': prop, 'name': prop, 'access': access,
            'value_on': True, 'value_off': False}


def _num(prop, access=1, lo=None, hi=None, unit=''):
    return {'type': 'numeric', 'property': prop, 'name': prop, 'access': access,
            'value_min': lo, 'value_max': hi, 'unit': unit}


BATT = _num('battery', unit='%')
KINDS = {
    'light': ([{'type': 'light', 'features': [
        {'type': 'binary', 'property': 'state', 'name': 'state', 'access': 7, 'value_on': 'ON', 'value_off': 'OFF'},
        _num('brightness', 7, 0, 254)]}], 'Router', {'state': 'OFF', 'brightness': 200, 'linkquality': 120}),
    'zplug': ([{'type': 'switch', 'features': [
        {'type': 'binary', 'property': 'state', 'name': 'state', 'access': 7, 'value_on': 'ON', 'value_off': 'OFF'}]},
        _num('power', unit='W')], 'Router', {'state': 'OFF', 'power': 0, 'linkquality': 140}),
    'pir': ([_bin('occupancy'), BATT, _num('illuminance', unit='lx')], 'EndDevice',
            {'occupancy': False, 'battery': 90, 'illuminance': 3, 'linkquality': 80}),
    'contact': ([_bin('contact'), BATT], 'EndDevice', {'contact': True, 'battery': 95, 'linkquality': 70}),
    'thermo': ([_num('temperature', unit='°C'), _num('humidity', unit='%'), BATT], 'EndDevice',
               {'temperature': 20.5, 'humidity': 48, 'battery': 88, 'linkquality': 60}),
    'trv': ([{'type': 'climate', 'features': [
        _num('current_heating_setpoint', 7, 5, 30, '°C'), _num('local_temperature', 1, unit='°C'),
        {'type': 'enum', 'property': 'system_mode', 'name': 'system_mode', 'access': 7,
         'values': ['off', 'heat', 'auto']}]}, BATT], 'EndDevice',
        {'current_heating_setpoint': 17, 'local_temperature': 19.5, 'system_mode': 'heat', 'battery': 80,
         'linkquality': 50}),
    'button': ([{'type': 'enum', 'property': 'action', 'name': 'action', 'access': 1,
                 'values': ['single', 'double', 'hold', 'release']}, BATT], 'EndDevice',
               {'battery': 100, 'linkquality': 90}),
}
HOUSE = []          # (name, kind, ieee)
n = 0
for kind, stem, many in (('light', 'Light', 14), ('zplug', 'ZPlug', 5), ('pir', 'PIR', 8),
                         ('contact', 'Window', 10), ('thermo', 'Thermo', 12), ('trv', 'TRV', 6),
                         ('button', 'Button', 4)):
    for i in range(1, many + 1):
        n += 1
        HOUSE.append(('%s-%d' % (stem, i), kind, '0x00158d00%08x' % n))
HOUSE += [('Garden-1', 'light', '0x00158d00000000f1'), ('Garden-2', 'light', '0x00158d00000000f2')]
NAMES = {name: ieee for name, kind, ieee in HOUSE}
KIND_OF = {name: kind for name, kind, ieee in HOUSE}
assert len(HOUSE) + len(PLUG_PORTS) == 65, len(HOUSE)


def bridge_devices():
    out = [{'ieee_address': '0x00124b0000000001', 'friendly_name': 'Coordinator', 'type': 'Coordinator'}]
    for name, kind, ieee in HOUSE:
        exposes, typ, _ = KINDS[kind]
        out.append({'ieee_address': ieee, 'friendly_name': name, 'type': typ, 'supported': True,
                    'power_source': 'Mains (single phase)' if typ == 'Router' else 'Battery',
                    'definition': {'model': kind.upper(), 'vendor': 'Test', 'description': kind,
                                   'exposes': exposes}})
    return out


for name, kind, ieee in HOUSE:
    BROKER.devices[name] = dict(KINDS[kind][2])
    if kind == 'thermo':
        BROKER.devices[name]['temperature'] = 20.0 + (sum(map(ord, name)) % 20) / 10.0


def report(name, **values):
    """The device says something, as Zigbee2MQTT says it (its whole state)."""
    st = BROKER.devices[name]
    st.update(values)
    at = BROKER.deliver('zigbee2mqtt/' + name, dict(st))
    if D is not None:
        quiesce()
    return at


def press(name, action):
    st = dict(BROKER.devices[name])
    st['action'] = action
    return BROKER.deliver('zigbee2mqtt/' + name, st)


LAT = []        # (what, ms)


def latency(what, t0, where, wait=3.0):
    """From a report handed to the broker thread to the first command to `where`."""
    deadline = _time.monotonic() + wait
    while _time.monotonic() < deadline:
        hit = [x for x in list(OUT) if x[0] >= t0 and x[1].startswith(where)]
        if hit:
            ms = (hit[0][0] - t0) * 1000
            LAT.append((what, round(ms, 1)))
            return ms
        _time.sleep(0.002)
    LAT.append((what, None))
    return None


def z2m_retained():
    """What the broker keeps for Zigbee2MQTT: its state, its device list,
    every device's last report and availability."""
    BROKER.retained['zigbee2mqtt/bridge/state'] = json.dumps({'state': 'online'})
    BROKER.retained['zigbee2mqtt/bridge/devices'] = json.dumps(bridge_devices())
    for name, kind, ieee in HOUSE:
        BROKER.retained['zigbee2mqtt/%s/availability' % name] = json.dumps({'state': 'online'})
        if kind != 'button':
            BROKER.retained['zigbee2mqtt/' + name] = json.dumps(BROKER.devices[name])


z2m_retained()


def zb_sets(name, key=None, since=0.0):
    """(clock, value) of what the daemon told that device since then."""
    out = []
    for c, topic, payload in list(BROKER.sent):
        if c < since or topic != 'zigbee2mqtt/%s/set' % name:
            continue
        body = json.loads(payload)
        if key is None:
            out.append((c, body))
        elif key in body:
            out.append((c, body[key]))
    return out


def zb_state(name, key='state'):
    return BROKER.devices[name].get(key)


# ---------------------------------------------------------------------------
# the daemon as run() runs it, with the clock's beat in the test's hands
# ---------------------------------------------------------------------------
H = {}
D = None
SERVER = None


POLL = {'n': 0, 'errors': [], 'ms': [], 'stop': False}


def dashboard():
    """A page open throughout: the status twice a second, the perf meter
    every few seconds, as the dashboard and the perf page ask."""
    i = 0
    while not POLL['stop']:
        if POLL.get('pause'):
            _time.sleep(0.1)
            continue
        i += 1
        path = '/api/perf' if i % 6 == 0 else '/api/status'
        t = _time.perf_counter()
        try:
            st, got = api(path)
            if st != 200:
                POLL['errors'].append((hm(), path, st, str(got)[:80]))
        except Exception as e:                       # noqa: BLE001
            if D is not None and not D._stop.is_set():
                POLL['errors'].append((hm(), path, str(e)[:80]))
        POLL['ms'].append((path, (_time.perf_counter() - t) * 1000))
        POLL['n'] += 1
        _time.sleep(0.5)


def boot():
    global D, SERVER
    d = start_daemon()
    d.follow_renames()
    SERVER = zigmon.ApiServer(d)
    d.prime_rules()
    d.connect()
    SERVER.start()
    d._running = True
    threading.Thread(target=d.rule_worker, name='rules', daemon=True).start()
    threading.Thread(target=d.rule_worker, args=(True,), name='rules-presence', daemon=True).start()
    if d.plugs:
        d._plug_thread = threading.Thread(target=d.plug_loop, name='plugs', daemon=True)
        d._plug_thread.start()
    D = d
    H['X-Zigmon-Token'] = (W / 'api-token').read_text().strip()
    settle(1.0)
    d.devices_settled(10)
    return d


def shutdown():
    """As the daemon stops: _stop, the broker let go, the queue landed."""
    d = D
    d._stop.set()
    BROKER.client = None
    try:
        d.store.flush(10.0)
    except Exception:
        pass
    try:
        SERVER.stop()
    except Exception:
        pass
    _time.sleep(0.6)


def quiesce(limit=2.0):
    """Until the broker's thread and the rule workers have nothing in hand."""
    deadline = _time.monotonic() + limit
    while _time.monotonic() < deadline:
        if not BROKER.q and not D._rule_queue and not getattr(D, '_rule_queue_gated', None):
            _time.sleep(0.004)
            if not BROKER.q and not D._rule_queue:
                return
        _time.sleep(0.002)


def settle(real_s=0.15):
    """Let the threads the daemon started do their work, in real time."""
    _time.sleep(real_s)
    while BROKER.q:
        _time.sleep(0.01)


STATE = {'windows': 0.0, 'half': 0.0, 'agg': 0.0, 'beats': 0, 'slow': []}


def beat():
    """One beat of timer_loop, with the half-minute chores and the run loop's
    hourly fold on the same clock (5.44.0's own steps, in its own order)."""
    d = D
    t0 = _time.perf_counter()
    now = zigmon.time.time()
    for name, step in (('the clock', d.clock_watch), ('the ways back', d.check_for_backs),
                       ('the timers kept', d.timers_keep)):
        d._beat_step(name, step)
    if now - STATE['windows'] >= 10:
        STATE['windows'] = now
        d._beat_step('the rule windows', d.check_rule_windows)
    if not d._for_queued:
        d._for_queued = True
        d._rule_queue.append(('__for__', None, None))
        d._rule_kick.set()
    d._beat_step('the schedules', d.check_schedules)
    d._beat_step('the rules waiting', d.check_rule_waiting)
    took = (_time.perf_counter() - t0) * 1000
    if took > 20:
        STATE['slow'].append((hm(), 'beat', round(took, 1)))
    if now - STATE['half'] >= 30:
        STATE['half'] = now
        t1 = _time.perf_counter()
        d._chores_busy = True
        d._half_minute()
        took = (_time.perf_counter() - t1) * 1000
        if took > 250:
            STATE['slow'].append((hm(), 'half-minute', round(took, 1)))
    # the backup loop's own look, which it takes at its nap (backup_nap)
    if now - STATE.get('backup_look', 0) >= 60:
        STATE['backup_look'] = now
        if d.backup_due():
            t2 = _time.perf_counter()
            d.run_backup()
            STATE.setdefault('backups', []).append((hm(), round((_time.perf_counter() - t2) * 1000)))
    if now - STATE['agg'] >= 3600:
        STATE['agg'] = now
        d.last_aggregate_at = now
        d.store.set_meta('last_aggregate_ts', str(int(now)))
        d.purge_per_device()
        d.store.aggregate()
        d.store.trim_wal()
    STATE['beats'] += 1


def live_until(t, step=15.0, real=0.0):
    """The house goes on until that moment, a beat every `step` seconds."""
    while CLOCK.now() < t:
        CLOCK.advance(min(step, max(0.0, t - CLOCK.now())))
        beat()
        if real:
            settle(real)
        else:
            while BROKER.q:
                _time.sleep(0.005)


def api(path, body=None):
    c = http.client.HTTPConnection('127.0.0.1', PORT_API, timeout=20)
    if body is None:
        c.request('GET', path, headers=H)
    else:
        c.request('POST', path, body=json.dumps(body), headers=dict(H, **{'Content-Type': 'application/json'}))
    r = c.getresponse()
    raw = r.read()
    try:
        return r.status, json.loads(raw)
    except ValueError:
        return r.status, {'raw': raw[:300]}


def events(since, kind=None):
    D.store.flush(5.0)
    with D.store.lock:
        rows = D.store.db.execute('SELECT ts, kind, level, device, detail FROM events WHERE ts>=? ORDER BY id',
                                  (int(since),)).fetchall()
    return [dict(r) for r in rows if kind is None or r['kind'] == kind]


IDS = {}


def zb(name, key='state'):
    return 'zb:%s:%s' % (NAMES[name], key)


def furnish():
    """The house as its owners set it up."""
    d = D
    d.save_rooms([{'id': 'liv', 'name': 'Living'}, {'id': 'bed', 'name': 'Bedroom'},
                          {'id': 'hall', 'name': 'Hall'}])
    d.save_room_map({NAMES['TRV-1']: 'liv', NAMES['TRV-2']: 'liv', NAMES['Window-1']: 'liv',
                     NAMES['Thermo-1']: 'liv', NAMES['TRV-3']: 'bed', NAMES['Window-2']: 'bed',
                     NAMES['Thermo-2']: 'bed', NAMES['PIR-1']: 'hall', NAMES['Light-1']: 'hall',
                     'Coffee': 'liv', 'Kettle': 'liv'})
    week = [1, 2, 3, 4, 5]
    weekend = [0, 6]
    plan = [{'at': '06:00', 'level': 'comfort', 'days': week}, {'at': '08:00', 'level': 'comfort', 'days': weekend},
            {'at': '22:00', 'level': 'night', 'days': [0, 1, 2, 3, 4, 5, 6]}]
    d.save_heating({'enabled': True, 'rooms': {
        'liv': {'mode': 'plan', 'comfort_c': 21, 'eco_c': 18, 'night_c': 17, 'plan': plan, 'window_stop': True},
        'bed': {'mode': 'plan', 'comfort_c': 20, 'eco_c': 18, 'night_c': 16, 'plan': plan, 'window_stop': True}}})
    d.save_people([{'id': 'alice', 'name': 'Alice', 'phone': '+420777000001', 'sms_alerts': True,
                    'sms_commands': True, 'phone_report': True, 'token': 'alice-phone-token-0001'},
                   {'id': 'bob', 'name': 'Bob', 'phone': '+420777000002', 'sms_alerts': False,
                    'sms_commands': True, 'phone_report': True, 'token': 'bob-phone-token-00002'}])
    d.save_scenes([{'id': 'eve', 'name': 'Evening', 'actions': [
        {'target': zb('Light-4'), 'do': 'on'}, {'target': zb('Light-5'), 'do': 'on'},
        {'target': 'Kettle', 'do': 'on'}, {'target': zb('ZPlug-1'), 'do': 'on'},
        {'target': 'Heater', 'do': 'off', 'after_s': 2}]}])
    d.save_bindings([
        {'device': NAMES['Button-1'], 'action': 'single', 'plug': zb('Light-2'), 'do': 'toggle'},
        {'device': NAMES['Button-1'], 'action': 'double', 'plug': 'scene:eve', 'do': 'on'},
        {'device': NAMES['Button-1'], 'action': 'hold', 'plug': zb('Light-3'), 'do': 'for:5m'}])
    d.save_rules([
        {'id': 'hall-on', 'device': NAMES['PIR-1'], 'key': 'occupancy', 'op': '==', 'value': 1,
         'plug': zb('Light-1'), 'do': 'on', 'cooldown_s': 0},
        {'id': 'hall-off', 'device': NAMES['PIR-1'], 'key': 'occupancy', 'op': '==', 'value': 0, 'for_s': 120,
         'plug': zb('Light-1'), 'do': 'off', 'cooldown_s': 0}])
    saved = d.save_schedules([
        {'id': 's-coffee-wk', 'target': 'Coffee', 'do': 'on', 'at': '06:30', 'days': 'mon,tue,wed,thu,fri'},
        {'id': 's-coffee-we', 'target': 'Coffee', 'do': 'on', 'at': '08:00', 'days': 'sat,sun'},
        {'id': 's-coffee-off', 'target': 'Coffee', 'do': 'off', 'at': '09:00', 'days': 'all'},
        {'id': 's-garden-on', 'target': zb('Garden-1'), 'do': 'on', 'at': 'sunset-15', 'days': 'all'},
        {'id': 's-garden-off', 'target': zb('Garden-1'), 'do': 'off', 'at': '23:00', 'days': 'all'},
        {'id': 's-fan', 'target': 'Fan', 'do': 'for:30m', 'at': '12:00', 'days': 'all'},
        {'id': 's-night', 'target': zb('ZPlug-5'), 'do': 'toggle', 'at': '02:30', 'days': 'all'}])
    check(len(saved) == 7, 'the schedules were not all saved: %r' % saved)
    d.save_presence_triggers([{'who': 'alice', 'event': 'arrive', 'plug': zb('Light-6'), 'do': 'on'}])
    d.store.set_meta('notify', json.dumps({'channels': {'ntfy': True, 'telegram': True, 'sms': False},
                                           'systems': {'quiet': {'roads': 'ntfy,sms'},
                                                       'battery': {'roads': 'ntfy'}}}))
    d.store.flush(5.0)


DRAW_W = {'Coffee': 1200.0, 'Kettle': 2000.0, 'Fan': 40.0, 'Heater': 1500.0}
METER = {'at': None, 'wh': collections.defaultdict(list)}     # name -> [(clock, Wh counted by then)]


def meter(now):
    """Each socket's own meter runs while it is on, whether the daemon is
    there to read it or not."""
    was = METER['at']
    METER['at'] = now
    if was is None:
        return
    for name, plug in PLUGS.items():
        st = plug.ns['STATE']
        if st['output']:
            st['apower'] = DRAW_W[name]
            st['aenergy']['total'] = round(st['aenergy']['total'] + DRAW_W[name] * (now - was) / 3600.0, 3)
        else:
            st['apower'] = 0.0
        METER['wh'][name].append((now, st['aenergy']['total']))


def counted(name, t0, t1):
    rows = METER['wh'][name]
    before = [wh for c, wh in rows if c <= t0] or [rows[0][1]]
    upto = [wh for c, wh in rows if c <= t1]
    return (upto[-1] if upto else before[-1]) - before[-1]


def world():
    """What the house says by itself: each thermometer every ten minutes, the
    heads every twenty, a socket's watts as the poll finds them."""
    now = CLOCK.now()
    meter(now)
    last = STATE.setdefault('world', {})
    for name, kind, ieee in HOUSE:
        if name in STATE.setdefault('silent', set()):
            continue
        every = {'thermo': 600, 'trv': 1200, 'contact': 3000, 'pir': 3000, 'light': 1800, 'zplug': 900}.get(kind)
        if not every:
            continue
        if now - last.get(name, 0) >= every:
            last[name] = now
            report(name)


def run_to(y, mo, d, h, mi, step=15.0):
    t = moment(y, mo, d, h, mi)
    while CLOCK.now() < t:
        CLOCK.advance(min(step, max(0.0, t - CLOCK.now())))
        world()
        beat()
        quiesce()


def saturday():
    print('Saturday 24 October: the weekend morning')
    t0 = CLOCK.now()
    run_to(2026, 10, 24, 7, 55)
    # nothing of the weekday's 06:30 on a Saturday; the weekend's 08:00 coffee
    check(not plug_sets('Coffee', t0), 'the coffee machine was switched before 08:00 on a Saturday: %r'
          % plug_sets('Coffee', t0))
    run_to(2026, 10, 24, 8, 3)
    settle(0.5)
    got = plug_sets('Coffee', t0)
    check([on for _, on in got] == [True] and got and moment(2026, 10, 24, 8, 0) <= got[0][0] < moment(2026, 10, 24, 8, 1),
          'the weekend coffee at 08:00: %r' % [(hm(c), on) for c, on in got])
    # the heating: night until 08:00 on a Saturday, then comfort
    sets = zb_sets('TRV-1', 'current_heating_setpoint', t0)
    check([v for _, v in sets] == [21] and moment(2026, 10, 24, 8, 0) <= sets[0][0] < moment(2026, 10, 24, 8, 1),
          'the living room\'s head on a Saturday morning: %r' % [(hm(c), v) for c, v in sets])

    print('  the hall: somebody walks through, the light follows')
    run_to(2026, 10, 24, 8, 30)
    t1 = CLOCK.now()
    at = report('PIR-1', occupancy=True)
    ms = latency('PIR -> hall light on', at, 'zigbee2mqtt/Light-1/set')
    check(ms is not None, 'movement in the hall did not switch its light on')
    run_to(2026, 10, 24, 8, 31)
    report('PIR-1', occupancy=False)
    run_to(2026, 10, 24, 8, 32)
    report('PIR-1', occupancy=True)          # back again before the two minutes are up
    run_to(2026, 10, 24, 8, 32, step=5)
    report('PIR-1', occupancy=False)
    run_to(2026, 10, 24, 8, 40, step=5)
    got = zb_sets('Light-1', 'state', t1)
    offs = [c for c, v in got if v == 'OFF']
    check(len(offs) == 1 and moment(2026, 10, 24, 8, 34) <= offs[0] <= moment(2026, 10, 24, 8, 34, 15),
          'the hall light went off at %r, not two minutes after the last movement (08:34)'
          % [hm(c) for c in offs])

    print('  the button by the door: single, double, hold')
    t2 = CLOCK.now()
    at = press('Button-1', 'single')
    latency('button single -> light', at, 'zigbee2mqtt/Light-2/set')
    settle(0.3)
    run_to(2026, 10, 24, 8, 41)
    at = press('Button-1', 'double')
    latency('button double -> scene (first step)', at, 'zigbee2mqtt/Light-4/set')
    settle(3.0)
    run_to(2026, 10, 24, 8, 42)
    press('Button-1', 'hold')
    settle(0.3)
    run_to(2026, 10, 24, 8, 50)
    check([v for _, v in zb_sets('Light-2', 'state', t2)] == ['ON'], 'a single press: %r'
          % zb_sets('Light-2', 'state', t2))
    for nm in ('Light-4', 'Light-5', 'ZPlug-1'):
        check([v for _, v in zb_sets(nm, 'state', t2)] == ['ON'], 'the scene left %s at %r' % (nm, zb_sets(nm, 'state', t2)))
    check([on for _, on in plug_sets('Kettle', t2)] == [True], 'the scene and the kettle: %r' % plug_sets('Kettle', t2))
    got = zb_sets('Light-3', 'state', t2)
    check([v for _, v in got] == ['ON', 'OFF'] and abs(got[1][0] - got[0][0] - 300) < 20,
          'a hold, "on for five minutes": %r' % [(hm(c), v) for c, v in got])

    print('  the living room window open for a quarter of an hour')
    run_to(2026, 10, 24, 9, 10)
    t3 = CLOCK.now()
    report('Window-1', contact=False)
    run_to(2026, 10, 24, 9, 25)
    report('Window-1', contact=True)
    run_to(2026, 10, 24, 9, 30)
    for nm in ('TRV-1', 'TRV-2'):
        got = zb_sets(nm, None, t3)
        check([v for _, v in got] == [{'system_mode': 'off'}, {'system_mode': 'heat'},
                                      {'current_heating_setpoint': 21}]
              and got[0][0] - t3 <= 31 and got[1][0] - moment(2026, 10, 24, 9, 25) <= 31,
              'the living room window open 09:10-09:25, %s was told %r' % (nm, [(hm(c), v) for c, v in got]))
        if got:
            # on the half-minute round of the heating, by design: a clock figure
            LAT.append(('window open -> %s shut (clock s)' % nm, round(got[0][0] - t3, 1)))
    check(not plug_sets('Coffee', t3) and [on for _, on in plug_sets('Coffee', t0)] == [True, False],
          'the coffee machine through the morning: %r' % [(hm(c), on) for c, on in plug_sets('Coffee', t0)])

    print('  the heater pulled out of the wall for twenty minutes')
    run_to(2026, 10, 24, 10, 0)
    t4 = CLOCK.now()
    PLUGS['Heater'].down()
    run_to(2026, 10, 24, 10, 10, step=15)
    settle(12.0)                   # the poll is in real time: three of them go unanswered
    check(D.plugs['Heater'].failures >= 3, 'the heater, pulled out, is still read as answering (it took the '
          'reading of another box behind the same address): failures=%d' % D.plugs['Heater'].failures)
    run_to(2026, 10, 24, 10, 20, step=15)
    run_to(2026, 10, 24, 10, 21)
    PLUGS['Heater'].up()
    run_to(2026, 10, 24, 10, 30)
    settle(6.0)
    run_to(2026, 10, 24, 10, 31)
    told = [b for c, r, t, b in PUSHED if c >= t4 and r == 'ntfy']
    check(len([b for b in told if 'Heater: lost contact' in b]) == 1,
          'the heater going: told %r' % told)
    check(len([b for b in told if 'Heater: contact restored' in b]) == 1,
          '"a device going quiet, unreachable or back": the heater coming back was never told (%r)' % told)
    hp = D.plugs['Heater']
    check(hp.failures == 0, 'the heater is back and still counted as failing: %d' % hp.failures)

    print('  the broker restarts')
    run_to(2026, 10, 24, 11, 0)
    before = len(BROKER.sent)
    BROKER.restart(40)
    settle(1.0)
    run_to(2026, 10, 24, 11, 5)
    cmds = [x for x in BROKER.sent[before:] if x[1].endswith('/set')]
    check(not cmds, 'the retained messages replayed at the reconnect switched things: %r' % cmds[:5])
    check(D.connected, 'not connected after the broker came back')

    print('  noon: the fan on for half an hour, and the daemon restarted in the middle of it')
    t6 = CLOCK.now()
    run_to(2026, 10, 24, 12, 5)
    report('PIR-1', occupancy=True)             # somebody in the hall as the daemon goes down
    run_to(2026, 10, 24, 12, 10)
    restart(60)
    run_to(2026, 10, 24, 12, 20)
    report('PIR-1', occupancy=False)
    run_to(2026, 10, 24, 12, 45)
    hall = zb_sets('Light-1', 'state', t6)
    check([v for _, v in hall] == ['ON', 'OFF'] and abs(hall[-1][0] - moment(2026, 10, 24, 12, 22)) < 20,
          'the hall light across a restart (on at 12:05, nobody from 12:20): %r' % [(hm(c), v) for c, v in hall])
    settle(0.5)
    got = plug_sets('Fan', t6)
    check([on for _, on in got] == [True, False] and got and abs(got[1][0] - moment(2026, 10, 24, 12, 30)) < 20,
          'the fan "on for 30 minutes" from 12:00, restarted at 12:10: %r' % [(hm(c), on) for c, on in got])
    check([on for _, on in plug_sets('Coffee', t6)] == [], 'the restart switched the coffee machine: %r'
          % plug_sets('Coffee', t6))
    st, status = api('/api/status')
    check(st == 200, 'the status after the restart answered %d' % st)

    print('  the afternoon: Alice goes out and comes back, a battery sinks, the sun sets')
    t7 = CLOCK.now()
    run_to(2026, 10, 24, 13, 0)
    st, got = api('/api/presence/report', {'token': 'alice-phone-token-0001', 'state': 'away'})
    check(st == 200, 'Alice\'s phone saying she left: %d %r' % (st, got))
    for hour, level in ((14, 35), (15, 28), (16, 22), (17, 14), (18, 13)):
        run_to(2026, 10, 24, hour, 0)
        report('Thermo-5', battery=level)
    settle(0.3)
    st, got = api('/api/presence/report', {'token': 'alice-phone-token-0001', 'state': 'home'})
    check(st == 200, 'Alice\'s phone saying she is back: %d %r' % (st, got))
    settle(0.5)
    run_to(2026, 10, 24, 18, 5)
    check([v for _, v in zb_sets('Light-6', 'state', t7)] == ['ON'],
          'Alice coming home did not light the hall: %r' % zb_sets('Light-6', 'state', t7))
    told = [(hm(c), t, b) for c, r, t, b in PUSHED if c >= t7 and r == 'ntfy' and 'Thermo-5' in (t + b)]
    check(len(told) == 2 and 'low' in told[0][1].lower() and 'flat' in told[1][1].lower(),
          'a battery going 35, 28, 22, 14, 13: told %r' % told)
    check(not [1 for c, r, t, b in PUSHED if c >= t7 and r == 'telegram' and 'Thermo-5' in (t + b)],
          'the battery alerts, set to go by ntfy only, went by Telegram too')
    garden = zb_sets('Garden-1', 'state', t7)
    sunset = zigmon.sun_minutes(50.08, 14.42, moment(2026, 10, 24, 12, 0), sunset=True)
    want = moment(2026, 10, 24, 0, 0) + (sunset - 15) * 60
    check([v for _, v in garden] == ['ON'] and abs(garden[0][0] - want) < 75,
          'the garden at sunset-15 (%s): %r' % (hm(want), [(hm(c), v) for c, v in garden]))


def saturday_night():
    print('Saturday night: the digest, a thermometer goes quiet, the clocks go back')
    t0 = CLOCK.now()
    run_to(2026, 10, 24, 21, 25)
    STATE['silent'].add('Thermo-7')            # its battery gives out at about half past nine
    run_to(2026, 10, 24, 21, 35)
    digests = [(hm(c), r) for c, r, t, b in PUSHED if c >= t0 and t == 'Today at home' or
               (r == 'telegram' and c >= t0 and b.startswith('Today at home'))]
    check(len(digests) == 2 and all(h.startswith('Sat 24 21:30') for h, _ in digests),
          'the digest at 21:30: %r' % digests)
    run_to(2026, 10, 25, 1, 30)
    quiet = [(hm(c), r, b) for c, r, t, b in PUSHED if c >= t0 and 'Thermo-7' in b]
    check(len([q for q in quiet if q[1] == 'ntfy']) == 1, 'Thermo-7 gone quiet: told %r' % quiet)
    outbox = [x for x in D.sms_outbox() if 'Thermo-7' in str(x.get('text'))]
    check(len(outbox) == 1, 'the text about Thermo-7 is not held for the morning once: %r' % outbox)
    garden = zb_sets('Garden-1', 'state', t0)
    check([v for _, v in garden] == ['OFF'] and garden and hm(garden[0][0]).startswith('Sat 24 23:00'),
          'the garden off at 23:00: %r' % [(hm(c), v) for c, v in garden])
    # the night the clocks go back: 02:30 happens twice, the schedule once
    t1 = CLOCK.now()
    run_to(2026, 10, 25, 4, 0)
    first = moment(2026, 10, 25, 2, 30, dst=1)
    second = moment(2026, 10, 25, 2, 30, dst=0)
    check(second - first == 3600, 'the test\'s own clock does not know the night')
    got = zb_sets('ZPlug-5', 'state', t1)
    check(len(got) == 1 and abs(got[0][0] - first) < 30,
          'the 02:30 toggle on the night 02:30 comes twice: %r' % [(hm(c), v) for c, v in got])
    nightly = [b for b in STATE.get('backups') or [] if b[0].startswith('Sun')]
    check(len(nightly) == 1 and nightly[0][0].startswith('Sun 25 03:15'),
          'the nightly backup at 03:15, the night the clocks go back: %r' % STATE.get('backups'))

    print('  the daemon restarted at four in the morning (an upgrade), Thermo-7 still quiet')
    t2 = CLOCK.now()
    restart(30)
    run_to(2026, 10, 25, 6, 0)
    seen = (D.store.device(NAMES['Thermo-7']) or {}).get('last_seen') or 0
    check(seen <= moment(2026, 10, 24, 21, 30), 'after the restart Thermo-7, silent since 21:25, was last '
          'seen at %s - the broker\'s retained copy taken for the device' % hm(seen))
    again =[(hm(c), r, b[:50]) for c, r, t, b in PUSHED if c >= t2 and ('Thermo-7' in b or 'Thermo-5' in b)]
    check(not again, 'after a restart the house said again what it had already said in the night: %r' % again)
    outbox = [x for x in D.sms_outbox() if 'Thermo-7' in str(x.get('text'))]
    check(len(outbox) == 1, 'after a restart the text about Thermo-7 is held %d time(s): %r' % (len(outbox), outbox))


def sunday():
    print('Sunday 25 October: the held text, the coffee, texts in, a link pressed')
    t0 = CLOCK.now()
    run_to(2026, 10, 25, 6, 58)
    before = [x for x in sms_sent() if 'Thermo-7' in x.get('text', '')]
    check(not before, 'the text about Thermo-7 went out in the quiet hours: %r' % before)
    run_to(2026, 10, 25, 7, 3)
    settle(1.5)
    after = [x for x in sms_sent() if 'Thermo-7' in x.get('text', '')]
    check(len(after) == 1 and after[0].get('number', '').endswith('777000001'),
          'the text about Thermo-7 held for the morning went out %d time(s): %r' % (len(after), after))
    told = [(hm(c), b[:60]) for c, r, t, b in PUSHED if r == 'ntfy' and 'Thermo-7' in b]
    check(len(told) == 1, 'Thermo-7, quiet since the evening, was said to have gone quiet %d times '
          '(the broker\'s retained copy taken for the device speaking at the restart): %r' % (len(told), told))
    run_to(2026, 10, 25, 8, 2)
    settle(0.5)
    got = plug_sets('Coffee', t0)
    check([on for _, on in got] == [True] and got and hm(got[0][0]).startswith('Sun 25 08:00'),
          'the Sunday coffee: %r' % [(hm(c), on) for c, on in got])
    sets = zb_sets('TRV-1', 'current_heating_setpoint', t0)
    check([v for _, v in sets][-1:] == [21] and hm(sets[-1][0]).startswith('Sun 25 08:00'),
          'the living room on a Sunday: %r' % [(hm(c), v) for c, v in sets])
    STATE['silent'].discard('Thermo-7')        # a new battery

    print('  texts: "status", "heating toggle" twice, a stranger')
    run_to(2026, 10, 25, 10, 0)
    n0 = len(sms_sent())
    D.sms_handle('+420777000001', 'status')
    settle(1.5)
    D.sms_handle('+420777000002', 'heating toggle')
    settle(1.0)
    check(D.heating_config().get('enabled') is False, 'Bob\'s "heating toggle" did not switch the heating off')
    run_to(2026, 10, 25, 10, 5)
    D.sms_handle('+420777000002', 'heating toggle')
    settle(1.0)
    check(D.heating_config().get('enabled') is True, 'the second "heating toggle" did not switch it back on')
    D.sms_handle('+420606999999', 'heating off')
    settle(1.5)
    check(D.heating_config().get('enabled') is True, 'a stranger switched the heating off')
    replies = sms_sent()[n0:]
    check(len([r for r in replies if r.get('number', '').endswith('777000001')]) == 1
          and len([r for r in replies if r.get('number', '').endswith('777000002')]) == 2
          and not [r for r in replies if '606999999' in r.get('number', '')],
          'the replies to three texts and a stranger: %r' % [(r.get('number'), r.get('text', '')[:40]) for r in replies])

    print('  a one-tap link: the kettle')
    taps = D.save_taps([{'name': 'Kettle on', 'target': 'Kettle', 'do': 'on'}])
    t1 = CLOCK.now()
    st, got = api('/api/tap/' + taps[0]['token'])
    check(st == 200 and got.get('ok'), 'the link answered %d %r' % (st, got))
    settle(0.5)
    check([on for _, on in plug_sets('Kettle', t1)] == [True], 'the link did not switch the kettle on: %r'
          % plug_sets('Kettle', t1))
    run_to(2026, 10, 25, 23, 0, step=30)


def monday():
    print('Monday 26 October: a weekday morning, the plan at 06:00')
    t0 = CLOCK.now()
    run_to(2026, 10, 26, 9, 5, step=20)
    settle(0.5)
    got = plug_sets('Coffee', t0)
    check([on for _, on in got] == [True, False] and hm(got[0][0]).startswith('Mon 26 06:30')
          and hm(got[1][0]).startswith('Mon 26 09:00'),
          'the weekday coffee: %r' % [(hm(c), on) for c, on in got])
    sets = zb_sets('TRV-1', 'current_heating_setpoint', t0)
    check([v for _, v in sets] == [21] and hm(sets[0][0]).startswith('Mon 26 06:00'),
          'the living room on a Monday: %r' % [(hm(c), v) for c, v in sets])
    st, status = api('/api/status')
    check(st == 200, '/api/status on Monday answered %d' % st)


def first_of_november():
    print('31 October to 1 November: the month turns')
    D.set_plug_output(D.plugs['Fan'], True, 'the test')   # the fan left running all week
    run_to(2026, 10, 26, 23, 0, step=60)
    restart(0)
    shutdown()
    CLOCK.to(moment(2026, 10, 31, 22, 0))
    STATE['half'] = STATE['windows'] = STATE['agg'] = 0.0
    STATE['world'] = {}
    POLL['pause'] = True                 # nobody has a page open overnight
    meter(CLOCK.now())                   # the meters ran on while the daemon was away
    boot()
    settle(6.0)                          # its figures worked out at once, on the evening of the 31st
    t0 = CLOCK.now()
    run_to(2026, 11, 1, 9, 10, step=30)
    settle(1.0)
    POLL['pause'] = False
    sums = [(hm(c), r, t, b) for c, r, t, b in PUSHED if c >= t0 and t.startswith('Energy')]
    check(len(sums) == 2 and all(h.startswith('Sun 01 09:00') for h, _, _, _ in sums),
          'the monthly summary on the 1st: %r' % [x[:3] for x in sums])
    # what October drew, by the sockets' own meters from the daemon's first reading
    first = moment(2026, 10, 24, 4, 51)
    want = sum(counted(n, first, moment(2026, 11, 1, 0, 0)) for n in PLUGS) / 1000.0
    said = sums[0][3] if sums else ''
    import re as _re
    m = _re.search(r'October 2026: ([0-9.]+) kWh', said)
    got = float(m.group(1)) if m else None
    check(got is not None and want > 1 and abs(got - want) <= max(0.2, want * 0.05),
          'the monthly summary said %r for October; the meters counted %.1f kWh' % (said.split('\n')[0], want))


def restart(down_s):
    """The daemon stopped, the house left alone for a while, the daemon back."""
    shutdown()
    CLOCK.advance(down_s)
    STATE['half'] = STATE['windows'] = 0.0
    boot()


try:
    print('pass 2: the house lived from %s' % hm())
    boot()
    st, status = api('/api/status')
    check(st == 200, '/api/status answered %d' % st)
    print('  up: %d devices, %d plugs, connected=%s' % (len(D.store.devices()), len(D.plugs), D.connected))
    furnish()
    threading.Thread(target=dashboard, name='page', daemon=True).start()
    only = [x for x in os.environ.get('PASS2_ONLY', '').split(',') if x]   # for working on one part
    for part in (saturday, saturday_night, sunday, monday, first_of_november):
        if not only or part.__name__ in only:
            part()
    POLL['stop'] = True
    print('  latencies (ms): %r' % LAT)
    worst = sorted(POLL['ms'], key=lambda x: -x[1])[:5]
    print('  the page: %d requests, worst %r, errors %r' % (POLL['n'], [(p, round(m)) for p, m in worst],
                                                            POLL['errors'][:5]))
    check(not [e for e in POLL['errors'] if len(e) == 4], 'the page open throughout was refused: %r' % POLL['errors'][:5])
    print('  slow beats: %r' % STATE['slow'][:10])
finally:
    try:
        shutdown()
    except Exception as e:
        print('shutdown: %s' % e)
    for p in PLUGS.values():
        if p.server:
            p.down()
    sms_proc.terminate()
    try:
        sms_proc.wait(5)
    except Exception:
        sms_proc.kill()
    if os.environ.get('PASS2_KEEP'):
        print('kept: %s' % W)
    else:
        shutil.rmtree(str(W), ignore_errors=True)

if bad:
    print('%d check(s) failed' % len(bad))
    sys.exit(1)
print('pass 2, the whole house: all good')
