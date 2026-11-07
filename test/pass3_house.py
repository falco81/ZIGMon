"""pass 3: a realistic house for the realtime tests of the page - 60 Zigbee
devices, 30 sockets on six Shelly lookalikes (five sockets each), 200 rules,
a few thousand events with long details. Imported by test/pass3_*.py.

    house = build(W, api_port, box_ports)   # the daemon, its API up, the boxes answering

Made-up names, 127.0.0.1 only.
"""
import json
import os
import random
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
BOXES = {}            # port -> {channel: output}
BOX_CALLS = []        # (t, port, method, params)


class _Box(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def do_POST(self):
        port = self.server.server_address[1]
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        m, p = body.get('method'), body.get('params') or {}
        BOX_CALLS.append((time.time(), port, m, p))
        st = BOXES.setdefault(port, {})

        def sw(n):
            on = bool(st.get(n))
            return {'id': n, 'output': on, 'apower': 40.0 + n if on else 0.0, 'voltage': 231.0,
                    'current': 0.2 if on else 0.0, 'aenergy': {'total': 1000.0 + n, 'by_minute': [0, 0, 0],
                                                                'minute_ts': int(time.time() // 60 * 60)},
                    'temperature': {'tC': 38.0, 'tF': 100.4}}
        if m == 'Switch.GetStatus':
            r = sw(int(p.get('id') or 0))
        elif m == 'Shelly.GetStatus':
            r = {'switch:%d' % n: sw(n) for n in range(5)}
            r.update({'wifi': {'rssi': -55, 'sta_ip': '127.0.0.1', 'ssid': 'iot'},
                      'sys': {'uptime': 4242, 'ram_free': 100000}, 'mqtt': {'connected': False},
                      'cloud': {'connected': False}})
        elif m == 'Switch.Set':
            n = int(p.get('id') or 0)
            was = bool(st.get(n))
            st[n] = bool(p.get('on'))
            r = {'was_on': was}
        elif m == 'Switch.Toggle':
            n = int(p.get('id') or 0)
            was = bool(st.get(n))
            st[n] = not was
            r = {'was_on': was}
        elif m == 'Shelly.GetDeviceInfo':
            r = {'id': 'shellypro4pm-%d' % port, 'model': 'SPSW-104PE16EU', 'gen': 2, 'ver': '1.4.4',
                 'app': 'Pro4PM', 'name': 'Box %d' % port}
        else:
            r = {}
        out = json.dumps({'id': body.get('id'), 'src': 'box', 'result': r}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def boxes(ports):
    for port in ports:
        srv = ThreadingHTTPServer(('127.0.0.1', port), _Box)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()


SENSOR_MODEL = {'model': 'WSDCGQ11LM', 'vendor': 'Aqara', 'description': 'thermometer',
                'exposes': [{'type': 'numeric', 'property': 'temperature', 'name': 'temperature', 'unit': '°C'},
                            {'type': 'numeric', 'property': 'humidity', 'name': 'humidity', 'unit': '%'},
                            {'type': 'numeric', 'property': 'battery', 'name': 'battery', 'unit': '%'},
                            {'type': 'numeric', 'property': 'linkquality', 'name': 'linkquality'}]}
CONTACT_MODEL = {'model': 'MCCGQ11LM', 'vendor': 'Aqara', 'description': 'door sensor',
                 'exposes': [{'type': 'binary', 'property': 'contact', 'name': 'contact', 'value_on': False,
                              'value_off': True},
                             {'type': 'numeric', 'property': 'battery', 'name': 'battery', 'unit': '%'}]}
BUTTON_MODEL = {'model': 'WXKG11LM', 'vendor': 'Aqara', 'description': 'button',
                'exposes': [{'type': 'enum', 'property': 'action', 'name': 'action',
                             'values': ['single', 'double', 'hold']},
                            {'type': 'numeric', 'property': 'battery', 'name': 'battery', 'unit': '%'}]}


def sensor_names():
    out = []
    for i in range(60):
        kind = 'T' if i < 40 else ('D' if i < 52 else 'B')
        out.append(('%s room %02d' % ({'T': 'Thermo', 'D': 'Door', 'B': 'Button'}[kind], i), kind))
    return out


def build(W, api_port, box_ports):
    """The daemon of a realistic house, its API on api_port, the boxes on
    box_ports (six ports, five sockets each)."""
    sys.argv = ['zigmon']
    sys.path.insert(0, os.environ.get('PASS3_DAEMON') or str(HERE))
    import zigmon                                               # noqa: E402
    boxes(box_ports)
    zigmon.load_config()
    zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': api_port, 'api_host': '127.0.0.1',
                          'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [],
                          'mqtt_host': '', 'log_file': '', 'log_to_journal': False,
                          'state_dir': str(W / 'state'), 'login_tries': 200, 'login_wait_min': 1,
                          'session_idle_min': 240, 'session_hours': 720, 'public_view': True})
    (W / 'state').mkdir(exist_ok=True)
    d = zigmon.Daemon()
    d.notify = lambda *a, **k: None
    plugs = []
    for b, port in enumerate(box_ports):
        for n in range(5):
            plugs.append({'name': 'Socket-%d-%d' % (b, n), 'host': '127.0.0.1:%d' % port, 'switch_id': n,
                          'kind': 'plug', 'host_state': 'enabled'})
    d.store.set_meta('managed', json.dumps({'plugs': plugs, 'sensors': []}))
    d.reload_devices()
    names = sensor_names()
    models = {'T': SENSOR_MODEL, 'D': CONTACT_MODEL, 'B': BUTTON_MODEL}
    devs = [{'ieee_address': '0x%016x' % (i + 1), 'friendly_name': n, 'type': 'EndDevice',
             'definition': models[k]} for i, (n, k) in enumerate(names)]
    d.handle_zigbee('bridge/devices', json.dumps(devs).encode())
    d.devices_settled(10)
    rnd = random.Random(7)
    for i, (n, k) in enumerate(names):
        if k == 'T':
            d.handle_zigbee(n, json.dumps({'temperature': round(20 + rnd.random() * 3, 1),
                                           'humidity': 40 + i % 10, 'battery': 90, 'linkquality': 120}).encode())
        elif k == 'D':
            d.handle_zigbee(n, json.dumps({'contact': True, 'battery': 80}).encode())
        else:
            d.handle_zigbee(n, json.dumps({'battery': 70}).encode())
    rules = []
    for i in range(200):
        n, k = names[i % 40]
        rules.append({'device': '0x%016x' % (i % 40 + 1), 'key': 'temperature', 'op': '>=' if i % 2 else '<=',
                      'value': 50 + i if i % 2 else -20 - i, 'plug': plugs[i % 30]['name'],
                      'do': 'on' if i % 2 else 'off', 'cooldown_s': 300, 'enabled': True})
    d.save_rules(rules)
    long_detail = 'a long detail of what happened, ' * 12
    for i in range(3000):
        d.store.add_event('sensor', '#%d %s' % (i, long_detail), 'info', '0x%016x' % (i % 60 + 1),
                          ts=time.time() - 86400 + i * 20)
    for target, args, name in ((d.rule_worker, (), 'rules'), (d.rule_worker, (True,), 'rules-presence'),
                               (d.timer_loop, (), 'timers'), (d.plug_loop, (), 'plugs')):
        threading.Thread(target=target, args=args, name=name, daemon=True).start()
    api = zigmon.ApiServer(d)
    api.start()
    time.sleep(0.3)
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    end = time.time() + 30                       # every socket read once
    while time.time() < end and not all(p.flat for p in d.plugs.values()):
        time.sleep(0.2)
    return zigmon, d, api, names


def login(api_port, token, name='owner', password='owner pass 12'):
    import urllib.request
    req = urllib.request.Request('http://127.0.0.1:%d/api/auth/login' % api_port,
                                 data=json.dumps({'name': name, 'password': password}).encode(),
                                 headers={'X-Zigmon-Token': token, 'Content-Type': 'application/json',
                                          'X-Zigmon-Client': '192.168.40.10'}, method='POST')
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read()).get('token') or ''


def web(W, api_port, workers='4', page=None):
    """A copy of web/ relaying to api_port; page: another index.php to use."""
    shutil.copytree(HERE / 'web', W / 'web')
    if page:
        (W / 'web' / 'index.php').write_bytes(Path(page).read_bytes())
    text = (W / 'web' / 'zigmon-api.php').read_text()
    text = text.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % api_port)
    text = text.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
    (W / 'web' / 'zigmon-api.php').write_text(text)
    return W / 'web'


def serve(folder, port, workers='4', procs=None):
    for _ in range(3):
        p = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % port, '-t', str(folder)], cwd=str(folder),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                             env=dict(os.environ, PHP_CLI_SERVER_WORKERS=str(workers)))
        for _ in range(50):
            try:
                socket.create_connection(('127.0.0.1', port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        time.sleep(0.3)
        if p.poll() is None:
            if procs is not None:
                procs.append(p)
            return p
        time.sleep(3)
    return None
