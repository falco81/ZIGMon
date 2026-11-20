#!/usr/bin/env python3
"""5.56 hunt (b): the Shelly code of 5.50-5.52 - what a realistic input made
misbehave.

  1. A config.json box written "https://10.0.0.5" (or "http://..."): the warm
     spares split it at its colon into a port, the ValueError ended every round
     of the warmer - no box in the house had a spare any more - and the poll
     asked "is it being switched?" by the whole word, so it never was, and its
     reading went on talking over a press.
  2. A box restarted (a firmware update) while its device info was not read
     that round (a command on it, or the read failed as it came up): the
     restart was seen once and forgotten, the old firmware stayed six hours.
  3. Scheduled backups at a late evening time: the three hours they may run
     late in did not cross midnight - 23:30 was missed at 00:20.
  4. The scheduler marked the night's run as made before it started it; a
     backup by hand begun in between made it fail, and the night was lost.
  5. A switch command asked again after its answer was lost carried the same
     digest nc: the box takes an nc once, answered 401, one round trip more.
  6. A box showing a refused certificate rewrote the settings row on every
     poll, warm spare and command, with nothing changed in it.

    python3 test/review556_hunt_b.py < /dev/null
"""
import json
import re
import socket
import sys
import threading
import time
import types
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402
from zigmon import ShellyRPC, Daemon                     # noqa: E402

bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


# ---- 1. an https:// (or http://) address from config.json ---------------------
ShellyRPC._cmd_at['127.0.0.1:20470'] = time.time()
check(ShellyRPC.commanding('https://127.0.0.1:20470', 3.0),
      'a box written https://.. is never seen being switched - its poll talks over the press')
ShellyRPC._rate_limited['127.0.0.1:20470'] = (time.time(), 1)
check(ShellyRPC.cooling('http://127.0.0.1:20470'), 'a box written http://.. is never seen cooling after a 429')
ShellyRPC._cmd_at.pop('127.0.0.1:20470', None)
ShellyRPC._rate_limited.pop('127.0.0.1:20470', None)

listener = socket.socket()
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(('127.0.0.1', 20471))
listener.listen(8)
accepted = []
threading.Thread(target=lambda: [accepted.append(listener.accept()) for _ in range(8)], daemon=True).start()


class Store(object):
    def __init__(self, meta=None):
        self.meta = dict(meta or {})
        self.writes = 0

    def meta_json(self, key):
        return [{'plug': 'Lamp'}] if key == 'rules' else None

    def get_meta(self, key):
        return self.meta.get(key)

    def set_meta(self, key, value):
        self.writes += 1
        self.meta[key] = value


class Warm(object):
    WARM_LIST_S = Daemon.WARM_LIST_S
    WARM_RECENT_S = Daemon.WARM_RECENT_S
    _warm_hosts = Daemon._warm_hosts
    _warm_round = Daemon._warm_round
    _warm_tls = Daemon._warm_tls


zigmon.CONFIG.update(plug_keepalive_s=2, plug_warm_spare=1, plug_commands_at_once=1)
w = Warm()
w._stop = threading.Event()
w.store = Store()
w.plugs = {'Lamp': types.SimpleNamespace(name='Lamp', known_down=False,
                                         cfg={'host': 'http://127.0.0.1:20471', 'switch_id': 0})}
try:
    w._warm_round({}, {}, -1e9)
    held = ShellyRPC.warm_state('127.0.0.1:20471')[0]
    check(held == 1, 'the box written http://.. got no warm spare (%d held)' % held)
except ValueError as e:
    check(False, 'a box written http://.. ends the warm round for every box: ValueError %s' % e)
ShellyRPC.warm_drop('127.0.0.1:20471')
listener.close()
print('an http(s):// address: seen switched, seen cooling, given its warm spare')

# ---- 2. a restart seen while the device info was not read ----------------------
d = types.SimpleNamespace(PLUG_INFO_EVERY_S=Daemon.PLUG_INFO_EVERY_S)
now = time.time()
p = types.SimpleNamespace(info={'ver': '1.4.4'}, info_at=now, uptime_seen=None)
due = lambda up: Daemon._plug_info_due(d, p, {'sys': {'uptime': up}}, now)   # noqa: E731
check(due(5000) is False, 'a box read a moment ago is due again')
check(due(6000) is False, 'a box whose uptime went on is due again')
check(due(12) is True, 'a restarted box is not due its device info')
# that read did not happen (a command on the box, or it failed): the next round
check(due(27) is True, 'a restart is forgotten when its read was skipped - the old firmware stays six hours')
p.info_at = now                                   # read now
check(due(42) is False, 'a box read after its restart is still due')
print('a restart: the device info stays due until it is read')

# ---- 3. a scheduled time whose three hours cross midnight ----------------------
store = Store({'sbk:settings': json.dumps({'on': True, 'at': '23:30'})})
sd = types.SimpleNamespace(store=store, plugs={'Lamp': object()})
check(zigmon.sbk_due(sd, datetime(2026, 11, 20, 23, 45)) == '2026-11-20', '23:30 not due at 23:45')
check(zigmon.sbk_due(sd, datetime(2026, 11, 21, 0, 20)) == '2026-11-20',
      'the 23:30 run, let go at 00:20, is not due (missed though fifty minutes late)')
check(zigmon.sbk_due(sd, datetime(2026, 11, 21, 2, 31)) is None, 'the 23:30 run is due more than three hours late')
check(zigmon.sbk_due(sd, datetime(2026, 11, 21, 22, 0)) is None, '23:30 due at 22:00')
store.meta['sbk:day'] = '2026-11-20'
check(zigmon.sbk_due(sd, datetime(2026, 11, 21, 0, 20)) is None, 'the 23:30 run made yesterday is due again at 00:20')
check(zigmon.sbk_due(sd, datetime(2026, 11, 21, 23, 31)) == '2026-11-21', 'the next night\'s 23:30 run is not due')
store.meta['sbk:settings'] = json.dumps({'on': True, 'at': '03:40'})
store.meta.pop('sbk:day')
check(zigmon.sbk_due(sd, datetime(2026, 11, 21, 0, 20)) is None, '03:40 due at 00:20')
check(zigmon.sbk_due(sd, datetime(2026, 11, 21, 3, 41)) == '2026-11-21', '03:40 not due at 03:41')
print('the scheduled time: its three hours run past midnight')

# ---- 4. a backup by hand begun as the scheduler starts its run ------------------
store.meta.pop('sbk:day', None)
real_start = zigmon.sbk_job_start


def busy_start(*a, **k):
    raise ValueError('a backup or a restore is going on - wait for it to end')


zigmon.sbk_job_start = busy_start
try:
    try:
        got = zigmon.sbk_tick(sd, datetime(2026, 11, 21, 3, 41))
    except ValueError as e:
        got = 'raised %s' % e
    check(got is None, 'the scheduler with a job begun meanwhile: %r' % (got,))
    check(not store.meta.get('sbk:day'), 'the night\'s run is marked made although it never started')
finally:
    zigmon.sbk_job_start = real_start
print('the scheduler: the night is marked only once its run has started')

# ---- 5. a command asked again carries a new nc ---------------------------------
seen = []
lock = threading.Lock()


class Box(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length') or 0))
        auth = self.headers.get('Authorization') or ''
        m = re.search(r'nc=([0-9a-f]+)', auth)
        n = re.search(r'nonce="([^"]*)"', auth)
        nc = (n.group(1), int(m.group(1), 16)) if m and n else None
        with lock:
            first = not seen
            repeat = nc is not None and nc in seen          # a box takes each nc of a nonce once
            seen.append(nc)
        if nc is None or repeat:
            body = b'{}'
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Digest qop="auth", realm="shellyplug", nonce="%d", '
                             'algorithm=SHA-256' % (len(seen) + 100))
        else:
            if first:
                time.sleep(0.9)           # the answer to the first is lost: the client gave up at 0.5 s
            body = json.dumps({'id': 1, 'result': {'was_on': False}}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass


srv = ThreadingHTTPServer(('127.0.0.1', 20472), Box)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
zigmon.CONFIG.update(plug_keepalive_s=0)
host = '127.0.0.1:20472'
ShellyRPC._challenges[host] = ShellyRPC._parse_challenge(
    'Digest qop="auth", realm="shellyplug", nonce="1", algorithm=SHA-256')
rpc = ShellyRPC(host, 'secret', 0, label='the lamp')
try:
    rpc.set_output(True)
    ok = True
except zigmon.PlugError as e:
    ok = 'failed: %s' % e
time.sleep(1.0)
check(ok is True, 'the command asked again did not go through: %s' % ok)
check(len(seen) == 2 and seen[0] != seen[1], 'the command asked again carried the same nc: %r (a 401 and a '
      'challenge more on the way of the press)' % seen)
srv.shutdown()
srv.server_close()
print('a command asked again: signed with the next nc, no 401')

# ---- 6. a refused certificate, told once -----------------------------------------
calls = []
t = types.SimpleNamespace(shelly_tls_settings=lambda: {'10.0.0.9': {'on': True, 'pin': 'aa', 'seen': 'bb'}},
                          _shelly_tls_change=lambda host, change: calls.append(host) or False)
Daemon._shelly_tls_refused(t, '10.0.0.9', 'bb', 'aa')
check(not calls, 'a certificate refused again rewrites the settings row with nothing changed')
Daemon._shelly_tls_refused(t, '10.0.0.9', 'cc', 'aa')
check(calls == ['10.0.0.9'], 'a certificate not seen before is not kept: %r' % calls)
print('a refused certificate: the settings row written once')

# ---- 7. an HTTPS connection kept from before the box's CA or certificate changed --
H7 = '127.0.0.1:20473'                    # nothing listens: a fresh connection is refused at once
ShellyRPC._tls[H7] = {'ca': '', 'pin': 'bb' * 32}


def old_conn():
    """An HTTPS connection made and checked under the setting before: pin aa..."""
    a, b = socket.socketpair()
    conn = zigmon.ShellyHTTPS('127.0.0.1', 20473, 1.0, H7, '127.0.0.1', {'ca': '', 'pin': 'aa' * 32})
    conn.sock = a
    conn.box_fp = 'aa' * 32
    return conn, b


zigmon.CONFIG.update(plug_keepalive_s=5)
conn, far = old_conn()
ShellyRPC.warm_put(H7, conn, 1)
try:
    spare = ShellyRPC._take_warm(H7, 5, True, ShellyRPC(H7)._tls_conf())
except TypeError as e:
    spare = 'TypeError %s' % e
check(spare is None, 'a warm spare checked under the certificate trusted before is handed to a command: %r'
      % (spare,))
ShellyRPC.warm_drop(H7)
far.close()

conn, far = old_conn()
with ShellyRPC._conn_guard:
    ShellyRPC._conns[H7] = [(conn, time.time())]
rpc = ShellyRPC(H7, '', 0, label='the safe')
rpc.timeout = 0.3
try:
    rpc.call('Switch.GetStatus', {'id': 0})
except zigmon.PlugError:
    pass
far.settimeout(0.2)
try:
    sent = far.recv(4096)
except OSError:
    sent = b''
check(b'POST /rpc' not in sent, 'a request went out on a connection held to the certificate trusted before')
far.close()
ShellyRPC.forget_connections(H7)
if hasattr(ShellyRPC, '_conn_trusted'):
    good, far = old_conn()
    plain = zigmon.http.client.HTTPConnection('127.0.0.1', 80)
    check(ShellyRPC._conn_trusted(good, {'ca': '', 'pin': 'aa' * 32})
          and ShellyRPC._conn_trusted(good, {'ca': '', 'pin': ''})
          and not ShellyRPC._conn_trusted(good, {'ca': 'PEM', 'pin': 'aa' * 32})
          and ShellyRPC._conn_trusted(plain, None), 'a kept connection judged wrongly')
    plain.close()
    good.close()
    far.close()
ShellyRPC._tls.pop(H7, None)
print("a kept or warm HTTPS connection: used only while the box's setting still accepts it")

print('review556_hunt_b: ' + ('all good' if not bad else '%d FAILED' % len(bad)))
sys.exit(1 if bad else 0)
