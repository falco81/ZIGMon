#!/usr/bin/env python3
"""(5.44.1) Pass 2: what pass 1's own fixes broke, each check failing on 5.44.0.

    python3 test/pass2_review.py

An in-process daemon, a fake Shelly on 19310 and 19312 (it counts every time its relay
goes from off to on, whoever asked), and a fake broker client as paho is to
the daemon: publish() with message ids, unacknowledged QoS 1 messages kept in
_out_messages, and the box's RPC over MQTT answered - or acted on and never
answered, as a box whose reply is lost on the way back.

  1. a pulse whose MQTT answer is lost presses once, not twice
  2. the retry after a stale kept connection is on a fresh one
  3. a message id paho reuses for something else is not dropped as a late command
  4. a toggle of a box with MQTT on but no prefix flips the relay over HTTP
  5. (verified, no change) install.sh's stamp is read back by the daemon as right
"""
import collections
import http.client
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

PORT = 19310
TMP = Path(tempfile.mkdtemp(prefix='zigmon-pass2-review-'))
BOX = {'output': False, 'calls': [], 'rises': 0}
BOX_LOCK = threading.Lock()
FAILED = []


def check(ok, what):
    if not ok:
        FAILED.append(what)
        print('  FAILED: ' + what)


def box_set(on, how):
    with BOX_LOCK:
        if on and not BOX['output']:
            BOX['rises'] += 1
        BOX['output'] = bool(on)
        BOX['calls'].append((time.time(), how, bool(on)))


class Box(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        method, params = body.get('method'), body.get('params') or {}
        if method == 'Switch.Set':
            out = {'was_on': BOX['output']}
            box_set(params.get('on'), 'http')
        elif method == 'Switch.Toggle':
            out = {'was_on': BOX['output']}
            box_set(not BOX['output'], 'http-toggle')
        elif method in ('Shelly.GetStatus', 'Switch.GetStatus'):
            out = {'switch:0': {'id': 0, 'output': BOX['output'], 'apower': 1.0}, 'id': 0,
                   'output': BOX['output'], 'apower': 1.0}
        else:
            out = {}
        raw = json.dumps({'id': body.get('id'), 'result': out}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


server = ThreadingHTTPServer(('127.0.0.1', PORT), Box)
threading.Thread(target=server.serve_forever, daemon=True).start()

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(TMP / 'z.db'), 'api_port': PORT + 1, 'token_file': str(TMP / 'token'),
                      'pin': '1234', 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'backup_dir': str(TMP / 'backups'), 'log_to_journal': False, 'mqtt_only': False})
d = zigmon.Daemon()
d.notify = lambda *a, **k: None


class Info(object):
    def __init__(self, mid):
        self.rc = 0
        self.mid = mid


class FakeBroker(object):
    def __init__(self):
        self.mid = 0
        self.sent = []
        self._out_messages = collections.OrderedDict()
        self._out_message_mutex = threading.Lock()
        self.acts = True              # the box does what it is told over MQTT
        self.answer = True            # ...and its answer comes back

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.mid = self.mid % 65535 + 1
        self.sent.append((time.time(), topic, payload))
        if qos:
            m = type('Msg', (), {})()
            m.topic, m.payload, m.qos, m.mid = topic, payload, qos, self.mid
            with self._out_message_mutex:
                self._out_messages[self.mid] = m
        if topic.endswith('/rpc'):
            body = json.loads(payload)
            if body.get('method') == 'Switch.Set' and self.acts:
                box_set(body['params'].get('on'), 'mqtt')
            if self.answer:
                def reply(rid=body['id']):
                    time.sleep(0.01)
                    msg = type('M', (), {})()
                    msg.topic, msg.retain = 'zigmon/rpc', False
                    msg.payload = json.dumps({'id': rid, 'src': 'box', 'result': {}}).encode()
                    d._on_message(None, None, msg)
                threading.Thread(target=reply, daemon=True).start()
        return Info(self.mid)

    def subscribe(self, *a, **k):
        return (0, 1)

    def acked(self):
        with self._out_message_mutex:
            self._out_messages.clear()


BROKER = FakeBroker()
d.client = BROKER
d.connected = True


def plug(**extra):
    entry = dict({'name': 'Gate', 'host': '127.0.0.1:%d' % PORT, 'switch_id': 0, 'kind': 'plug',
                  'host_state': 'enabled'}, **extra)
    d.store.set_meta('managed', json.dumps({'plugs': [entry], 'sensors': []}))
    d.reload_devices()
    p = d.plugs['Gate']
    p.output, p.flat, p.generated = (1 if BOX['output'] else 0), {'switch.output': BOX['output']}, time.time()
    p.failures = 0
    return p


try:
    # ========================================================================
    # 1. A pulse whose answer over the broker is lost presses once
    # ========================================================================
    # Pass 1 sent a pulse's two halves over the broker, each with the HTTP
    # fallback that runs two seconds later when no answer comes. A box that
    # did the "on" and the "off" (a gate, a garage door) but whose answers
    # were lost - RPC over MQTT answering to a topic the broker does not let
    # it publish to is the usual one - then had the "on" sent again over HTTP
    # at 2.0 s and the "off" at 2.2 s: pressed twice, the door started and
    # stopped, or opened and closed.
    BOX['output'] = False
    BROKER.acts, BROKER.answer = True, False
    d._mqtt_road_off.clear()
    p = plug(mqtt=True, mqtt_name='gate')
    rises0 = BOX['rises']
    ok, msg = d.pulse_plug(p, 200)
    time.sleep(2.8)                                       # every fallback there is has run
    check(ok, 'the pulse failed: %s' % msg)
    check(BOX['rises'] - rises0 == 1, 'a pulse whose MQTT answers were lost pressed %d times: %r'
          % (BOX['rises'] - rises0, [c[1:] for c in BOX['calls'][-6:]]))
    check(BOX['output'] is False, 'the pulse left the relay on')
    # ...and one whose answers come still goes over the broker alone
    BROKER.answer = True
    d._mqtt_road_off.clear()
    p = plug(mqtt=True, mqtt_name='gate')
    t0, rises0 = time.time(), BOX['rises']
    ok, msg = d.pulse_plug(p, 200)
    time.sleep(0.4)
    check(ok and BOX['rises'] - rises0 == 1 and BOX['output'] is False, 'a pulse over a broker that answers: %r %s'
          % (ok, msg))
    check(not [c for c in BOX['calls'] if c[0] >= t0 and c[1] == 'http'],
          'a pulse over a broker that answers went over HTTP as well')
    # ...and with MQTT only and no answer: said, and nothing over HTTP
    zigmon.CONFIG['mqtt_only'] = True
    BROKER.acts, BROKER.answer = False, False
    p = plug(mqtt=True, mqtt_name='gate')
    t0 = time.time()
    ok, msg = d.pulse_plug(p, 100)
    check(not ok, 'a pulse nobody answered with MQTT only was said to have worked: %s' % msg)
    check(not [c for c in BOX['calls'] if c[0] >= t0 and c[1] == 'http'], 'a pulse with MQTT only went over HTTP')
    zigmon.CONFIG['mqtt_only'] = False
    BROKER.acts, BROKER.answer = True, True
    print('1. a pulse whose answers are lost presses once (%d)' % (BOX['rises'] - rises0))

    # ========================================================================
    # 2. The retry after a stale kept connection is a fresh one
    # ========================================================================
    # Pass 1 kept a few connections per box (one per socket of a strip). The
    # retry after a kept one turned out dead took the next kept one - just as
    # dead, the box having rebooted or closed them all idle - and the command
    # failed with "cannot reach" for a box that was there.
    class Dead(object):
        def __init__(self):
            self.timeout, self.sock, self.closed = 1, None, False

        def request(self, *a, **k):
            raise http.client.RemoteDisconnected('Remote end closed connection without response')

        def close(self):
            self.closed = True

    zigmon.CONFIG['plug_keepalive_s'] = 3
    # a box of its own, which nothing else in the daemon reads meanwhile
    other = ThreadingHTTPServer(('127.0.0.1', PORT + 2), Box)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    host = '127.0.0.1:%d' % (PORT + 2)
    dead = [Dead() for _ in range(4)]
    with zigmon.ShellyRPC._conn_guard:
        zigmon.ShellyRPC._conns[host] = [(c, time.time()) for c in dead]
    try:
        got = zigmon.ShellyRPC(host, '', 0, label='plug Strip').switch_status()
        reached = True
    except zigmon.PlugError as e:
        got, reached = str(e), False
    check(reached, 'a box whose kept connections had all gone stale was not reached: %s' % got)
    check(all(c.closed for c in dead), 'the stale connections were not all closed: %r' % [c.closed for c in dead])
    with zigmon.ShellyRPC._conn_guard:
        kept = list(zigmon.ShellyRPC._conns.get(host) or [])
    check(not any(c in dead for c, _u in kept), 'a dead connection is still kept for the box')
    other.shutdown()
    other.server_close()
    print('2. the retry after a stale kept connection opens a fresh one')

    # ========================================================================
    # 3. A message id paho uses again is not a late command
    # ========================================================================
    # paho numbers its messages 1..65535 and starts again. The ids of commands
    # were kept (when each went out) and only thinned out past 2000 of them:
    # an id a command had days ago, given now to a message that is no command
    # (a ping, a retained state), was "late" at the next reconnect and taken
    # out of paho's hands, never to be sent.
    BROKER.acked()
    old = d.say('zigbee2mqtt/Lamp/set', json.dumps({'state': 'ON'}), qos=1)
    d._cmd_mids[old.mid] -= 3 * 86400                    # days ago; acknowledged long since
    BROKER.acked()
    BROKER.mid = old.mid - 1                             # the counter has come round
    ping = d.say('zigmon/ping', '1', qos=1)
    check(ping.mid == old.mid, 'the test did not reuse the id (%s, %s)' % (ping.mid, old.mid))
    d.connected = False
    d._on_connect(BROKER, None, {}, 0)
    check(ping.mid in BROKER._out_messages, 'a ping that had a command\'s old id was dropped at the reconnect')
    BROKER.acked()
    d.connected = True
    print('3. an id used again for something else is left to paho')

    # ========================================================================
    # 4. A toggle of a box with MQTT on and no prefix: the relay flips
    # ========================================================================
    # Pass 1 sent a toggle of a box set up for MQTT as a Set to the opposite
    # of what it last said - over HTTP when there is no prefix to publish to,
    # aimed at a state a poll old. Switched at the wall since, the press did
    # nothing; HTTP's Switch.Toggle, as before, flips what the relay is.
    BOX['output'] = True                                 # switched on at the wall
    p = plug(mqtt=True, mqtt_name='')
    p.output = 0                                         # the last poll said off
    ok, msg = d.toggle_plug(p)
    check(ok and BOX['output'] is False, 'a toggle of a box without an MQTT prefix left it %s (%s)'
          % ('on' if BOX['output'] else 'off', msg))
    print('4. a toggle without an MQTT prefix flips the relay (%s)' % msg)

    # ========================================================================
    # 5. install.sh's stamp, read back by the daemon (verified, no change)
    # ========================================================================
    # Every machine upgrading to 5.44 from the web runs the new install.sh
    # --upgrade (root's helper starts it), and do_upgrade writes the stamp
    # just before zigmon starts. Its own function, run here on a folder that
    # stands in for the machine, against the daemon's root_parts_check.
    m = TMP / 'machine'
    for sub in ('lib', 'etc/systemd/system', 'etc/logrotate.d', 'etc/profile.d'):
        (m / sub).mkdir(parents=True, exist_ok=True)
    for rel, text in (('lib/zigmon_root.py', 'root\n'), ('lib/zigmon_upgrade.py', 'up\n'),
                      ('etc/systemd/system/zigmon.service', '[Service]\n'), ('etc/logrotate.d/zigmon', 'lr\n')):
        (m / rel).write_text(text)
    src = (HERE / 'install.sh').read_text()
    fn = src[src.index('write_system_stamp() {'):src.index('# ---- (5.44) end')]
    script = '\n'.join([
        'set -euo pipefail', 'good(){ echo "good: $*"; }', 'warn(){ echo "warn: $*"; }', 'note(){ :; }',
        'DRY_RUN=""', 'LIB_DIR=%s' % (m / 'lib'), 'UNIT_FILE=%s' % (m / 'etc/systemd/system/zigmon.service'),
        'LOGROTATE_FILE=%s' % (m / 'etc/logrotate.d/zigmon'), 'SYSTEM_LEVEL=1', 'VERSION=%s' % zigmon.__version__,
        'SYSTEM_STAMP=%s' % (m / 'etc/zigmon-system.json'), 'ZIGMON_UPGRADE_FROM_PAGES=1', fn,
        'write_system_stamp'])
    run = subprocess.run(['bash', '-c', script], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    check(run.returncode == 0 and (m / 'etc/zigmon-system.json').is_file(),
          'install.sh did not write its stamp: %s' % (run.stdout + run.stderr)[-400:])
    os.environ['ZIGMON_SYSTEM_STAMP'] = str(m / 'etc/zigmon-system.json')
    os.environ['ZIGMON_ROOT_PARTS_CHECK'] = '1'
    spec = importlib.util.spec_from_file_location('zigmon_upgrade_pass2', str(HERE / 'deploy' / 'zigmon_upgrade.py'))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    d.upgrade_helper = lambda: helper
    got = d.root_parts_check() or {}
    check(got.get('stale') is False, 'the stamp install.sh just wrote reads as stale: %r' % got.get('why'))
    (m / 'lib/zigmon_root.py').write_text('changed by hand\n')
    got = d.root_parts_check() or {}
    check(got.get('stale') is True and 'zigmon_root.py' in str(got.get('why')),
          'a part changed after install.sh was not seen: %r' % got)
    stamp = json.loads((m / 'etc/zigmon-system.json').read_text())
    check(stamp.get('by') == 'the dashboard' and stamp.get('version') == zigmon.__version__,
          'the stamp of an upgrade from the dashboard says %r' % {k: stamp.get(k) for k in ('by', 'version')})
    print('5. install.sh\'s stamp is what the daemon reads as right (verified)')

    # 6. (5.44.1) the package is not forgotten while an upgrade asked for waits for root
    up = d.upgrade_dir()
    up.mkdir(parents=True, exist_ok=True)
    (up / 'zigmon-9.9.9.tar.gz').write_bytes(b'x')
    (up / 'request.json').write_text('{"op": "upgrade"}')
    real_asked = d.upgrade_asked
    d.upgrade_asked = lambda: {'version': '9.9.9', 'at': time.time()}
    try:
        d.upgrade_forget()
        refused = False
    except ValueError:
        refused = True
    finally:
        d.upgrade_asked = real_asked
    check(refused and (up / 'zigmon-9.9.9.tar.gz').exists(),
          'the package was forgotten from under an upgrade root had not taken yet')
    (up / 'request.json').unlink()
    d.upgrade_forget()
    check(not (up / 'zigmon-9.9.9.tar.gz').exists(), 'the package was not forgotten once nothing waited for it')
    print('6. a package waiting for root is not forgotten from under it')
finally:
    server.shutdown()
    server.server_close()
    try:
        d.store.close()
    except Exception:
        pass
    shutil.rmtree(str(TMP), ignore_errors=True)

if FAILED:
    print('pass2_review: %d failed' % len(FAILED))
    os._exit(1)
print('pass2_review: all good')
os._exit(0)
