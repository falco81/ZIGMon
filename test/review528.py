#!/usr/bin/env python3
"""5.28: a sensor or a button does what it means, at once, and only once.
Every check fails on 5.27.0 and passes since.

    python3 test/review528.py

A fake Shelly on a port of its own and messages handed to the daemon as the
broker would; no broker, no web server.
"""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review528-check-'))
BOXPORT = 19851
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


BOX = {'output': False, 'sets': [], 'poll_delay': 0.0, 'methods': []}


class Box(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        method, params = body.get('method'), body.get('params') or {}
        BOX['methods'].append(method)
        if method == 'Switch.Set':
            BOX['sets'].append(bool(params.get('on')))
            was, BOX['output'] = BOX['output'], bool(params.get('on'))
            out = {'was_on': was}
        elif method == 'Switch.Toggle':
            was, BOX['output'] = BOX['output'], not BOX['output']
            BOX['sets'].append(BOX['output'])
            out = {'was_on': was}
        elif method in ('Shelly.GetStatus', 'Switch.GetStatus'):
            snap = BOX['output'] if BOX.get('stale') is None else BOX['stale']
            if BOX['poll_delay']:
                time.sleep(BOX['poll_delay'])
            out = {'switch:%d' % i: {'id': i, 'output': snap, 'apower': 12.0, 'voltage': 231.0,
                                     'aenergy': {'total': 1.0}} for i in range(4)}
            if method == 'Switch.GetStatus':
                out = out['switch:0']
        elif method == 'Shelly.GetDeviceInfo':
            out = {'id': 'x', 'model': 'S3PL', 'gen': 3, 'ver': '1.7.1'}
        else:
            out = {}
        raw = json.dumps({'id': body.get('id'), 'result': out}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


srv = ThreadingHTTPServer(('127.0.0.1', BOXPORT), Box)
threading.Thread(target=srv.serve_forever, daemon=True).start()

sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 0, 'token_file': str(W / 'run' / 'api-token'),
                      'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '',
                      'state_dir': str(W / 'state')})
(W / 'state').mkdir()
BASE = zigmon.CONFIG['base_topic'].rstrip('/')


class Msg:
    def __init__(self, topic, payload, retain=False):
        self.topic, self.payload, self.retain = topic, payload, retain


def daemon(extra=None):
    x = zigmon.Daemon()
    plug = {'name': 'Light-Test', 'host': '127.0.0.1:%d' % BOXPORT, 'switch_id': 0, 'kind': 'plug',
            'host_state': 'enabled'}
    plug.update(extra or {})
    x.store.set_meta('managed', json.dumps({'plugs': [plug], 'sensors': []}))
    x.reload_devices()
    for gated in (False, True):
        threading.Thread(target=x.rule_worker, args=(gated,), daemon=True).start()
    return x


d = daemon()

# ---- a retained message is what was said last, not a press now ---------------------------
print('a retained press replayed by the broker is not a press')
d.store.upsert_device({'id': 'zigbee:Btn', 'name': 'Btn', 'source': 'zigbee', 'kind': 'button',
                       'exposes': {'action': {}}})
d.names['Btn'] = 'zigbee:Btn'
d.store.set_meta('bindings', json.dumps([{'device': 'zigbee:Btn', 'action': 'single', 'plug': 'Light-Test',
                                          'do': 'toggle', 'enabled': True}]))
BOX['sets'].clear()
d._on_message(None, None, Msg(BASE + '/Btn', json.dumps({'action': 'single', 'battery': 90}).encode(), retain=True))
time.sleep(1.0)
check(not BOX['sets'], 'a retained "single" replayed at a reconnect switched the light: %r' % BOX['sets'])
d._on_message(None, None, Msg(BASE + '/Btn', json.dumps({'action': 'single'}).encode()))
time.sleep(1.0)
check(len(BOX['sets']) == 1, 'a real press after it did not switch the light: %r' % BOX['sets'])
d.store.set_meta('bindings', '[]')

# ---- a rule after a restart: a state that held before is not news ----------------------------
print('after a restart a door open for hours is not a door opening')
d.store.upsert_device({'id': '0xdoor', 'name': 'Door', 'source': 'zigbee', 'kind': 'EndDevice',
                       'exposes': {'contact': {}}})
d.names['Door'] = '0xdoor'
d.store.set_meta('rules', json.dumps([{'id': 'rd', 'device': '0xdoor', 'key': 'contact', 'op': '==', 'value': 0,
                                       'plug': 'Light-Test', 'do': 'toggle', 'enabled': True}]))
d.handle_zigbee('Door', json.dumps({'contact': False}).encode())           # opened, before the restart
time.sleep(0.8)
d.store.flush(3.0)
d2 = daemon()
d2.names['Door'] = '0xdoor'
if hasattr(d2, 'prime_rules'):
    d2.prime_rules()                                                       # as run() does
BOX['sets'].clear()
d2._on_message(None, None, Msg(BASE + '/Door', json.dumps({'contact': False, 'battery': 80}).encode(), retain=True))
d2.handle_zigbee('Door', json.dumps({'contact': False, 'battery': 80}).encode())   # its periodic report
time.sleep(1.0)
check(not BOX['sets'], 'a door open since before the restart flipped the light at the first report: %r' % BOX['sets'])
d2.handle_zigbee('Door', json.dumps({'contact': True}).encode())
time.sleep(0.3)
d2.handle_zigbee('Door', json.dumps({'contact': False}).encode())
time.sleep(1.0)
check(len(BOX['sets']) == 1, 'the door really opening after the restart did nothing: %r' % BOX['sets'])
d2.store.set_meta('rules', '[]')
d.store.set_meta('rules', '[]')

# ---- a push from the box is newer than a poll already on its way ------------------------------
print('the wall button on the box is not undone by an older poll')
dm = daemon({'mqtt': True, 'mqtt_name': 'shelly-test'})
p = dm.plugs['Light-Test']
BOX['output'] = True
dm.poll_plug(p, force=True)
time.sleep(1.2)
BOX['poll_delay'] = 0.5
BOX['stale'] = True                                     # the answer to a poll asked before the button
t = threading.Thread(target=dm.poll_plug, args=(p,), kwargs={'force': True})
t.start()
time.sleep(0.1)
BOX['output'] = False                                   # the wall button
dm.handle_plug_push([p], ['events', 'rpc'], json.dumps({'method': 'NotifyStatus', 'params': {
    'ts': time.time(), 'switch:0': {'id': 0, 'output': False, 'source': 'button'}}}).encode())
t.join()
BOX['poll_delay'] = 0
BOX['stale'] = None
check(p.output == 0, 'an older poll put the socket back to on after the wall button switched it off')

# ---- a quick second press on a Zigbee toggle ---------------------------------------------------
print('a second quick press on a Zigbee toggle undoes the first')
sent = []


class Info:
    rc = 0


class C:
    def publish(self, topic, payload, qos=0, retain=False):
        sent.append(payload)
        return Info()


d.client, d.connected = C(), True
d._verify_zigbee_set = lambda *a, **k: None
d.store.upsert_device({'id': '0xlamp', 'name': 'Lamp', 'source': 'zigbee', 'kind': 'Router', 'exposes': {'state': {}}})
d.names['Lamp'] = '0xlamp'
d.handle_zigbee('Lamp', json.dumps({'state': 'ON'}).encode())
time.sleep(0.1)
d.zigbee_switch('0xlamp', 'state', 'toggle', 'a button')
time.sleep(0.4)
d.zigbee_switch('0xlamp', 'state', 'toggle', 'a button')
states = [json.loads(x).get('state') for x in sent if isinstance(x, (str, bytes)) and b'state' in
          (x if isinstance(x, bytes) else x.encode())]
check(states[-2:] == ['OFF', 'ON'], 'two quick toggles before the lamp reported sent %r' % states)
d.client, d.connected = None, False

# ---- a step of the clock --------------------------------------------------------------------------
print('a step of the clock does not end a wait')
d.store.upsert_device({'id': 'zigbee:PIR', 'name': 'PIR', 'source': 'zigbee', 'kind': 'sensor',
                       'exposes': {'occupancy': {}}})
d.names['PIR'] = 'zigbee:PIR'
d.store.set_meta('rules', json.dumps([{'id': 'r1', 'device': 'zigbee:PIR', 'key': 'occupancy', 'op': '==',
                                       'value': 0, 'plug': 'Light-Test', 'do': 'off', 'after_s': 600,
                                       'enabled': True}]))
BOX['output'] = True
d.poll_plug(d.plugs['Light-Test'], force=True)
d.handle_zigbee('PIR', json.dumps({'occupancy': True}).encode())
time.sleep(0.2)
d.handle_zigbee('PIR', json.dumps({'occupancy': False}).encode())
time.sleep(0.4)
watch = getattr(d, 'clock_watch', lambda: None)
watch()
real = time.time
time.time = lambda: real() + 3 * 3600                    # NTP steps the clock at boot
try:
    BOX['sets'].clear()
    watch()                                              # the beat that sees it
    d.check_rule_waiting()
    time.sleep(0.5)
finally:
    time.time = real
check(not BOX['sets'], '"off in ten minutes" went off at once when the clock was stepped forward: %r' % BOX['sets'])

# ---- an MQTT toggle is a Set ----------------------------------------------------------------------
src = (HERE / 'zigmon.py').read_text()
tp = src[src.index('    def toggle_plug('):src.index('    def read_plug_counters(')]
check("'Switch.Toggle'" not in tp, 'a toggle over the broker falls back to HTTP with a Set that can undo it')

sys.stdout.flush()
if bad:
    print('\n%d check(s) failed' % len(bad))
    os._exit(1)
print('a sensor or a button does what it means, once')
os._exit(0)
