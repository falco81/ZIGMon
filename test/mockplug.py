"""A Shelly Plug M Gen3 lookalike: /rpc with SHA-256 digest auth, a switch, counters."""
import json, hashlib, secrets, re, sys, time, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PASSWORD = sys.argv[2] if len(sys.argv) > 2 else ''
MQTTCFG = {'enable': False, 'client_id': 'shellyplugsg3-48f6eeb664cc'}
STATE = {'output': False, 'apower': 0.0, 'voltage': 231.4, 'current': 0.0, 'pf': 1.0, 'freq': 50.0,
         'aenergy': {'total': 1234.567, 'by_minute': [0, 0, 0], 'minute_ts': 1}, 'temperature': {'tC': 41.2, 'tF': 106.2},
         'counts': {'on_time': 3600, 'switch_on': 12, 'on_above_thr': 100}}
CALLS = []
CONF = {'switch': {'name': None, 'auto_off': False, 'auto_off_delay': 60.0, 'power_limit': 2800, 'initial_state': 'restore_last'},
        'ble': {'enable': False, 'rpc': {'enable': False}}, 'matter': {'enable': True}}
NONCE = secrets.token_hex(8)

def ok_digest(header, method):
    if not PASSWORD: return True
    if not header.startswith('Digest '): return False
    f = dict(re.findall(r'(\w+)="?([^",]+)"?', header))
    h = lambda t: hashlib.sha256(t.encode()).hexdigest()
    ha1 = h('admin:%s:%s' % (f.get('realm'), PASSWORD)); ha2 = h('%s:%s' % (method, f.get('uri')))
    return f.get('response') == h('%s:%s:%s:%s:auth:%s' % (ha1, f.get('nonce'), f.get('nc'), f.get('cnonce'), ha2))

CHANNELS = int(sys.argv[3]) if len(sys.argv) > 3 else 1   # sockets on this box (argv[2] is the password)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        if PASSWORD and not ok_digest(self.headers.get('Authorization', ''), 'POST'):
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Digest qop="auth", realm="shellyplugsg3-aabbcc", nonce="%s", algorithm=SHA-256' % NONCE)
            self.end_headers(); return
        m, p = body.get('method'), body.get('params') or {}
        CALLS.append((m, p))
        if m == 'Switch.GetStatus': r = dict(STATE, id=0)
        elif m == 'Shelly.GetStatus':
            # a box may carry several sockets; CHANNELS says how many, so a
            # four-socket box can be tested the way a real one behaves
            r = {'switch:%d' % n: dict(STATE, id=n) for n in range(CHANNELS)}
            r.update({'temperature:0': {'id': 0, 'tC': 22.5, 'tF': 72.5}, 'humidity:0': {'id': 0, 'rh': 48.0}, 'devicepower:0': {'id': 0, 'battery': {'V': 2.95, 'percent': 88}, 'external': {'present': False}}, 'wifi': {'rssi': -58, 'sta_ip': '172.16.16.12', 'ssid': 'iot'}, 'sys': {'uptime': 4242, 'ram_free': 100000}, 'cloud': {'connected': False}, 'mqtt': {'connected': True}})
        elif m == 'Shelly.ListMethods': r = {'methods': ['Shelly.GetStatus','Shelly.GetConfig','Shelly.GetDeviceInfo','Shelly.ListMethods','Shelly.Reboot','Switch.GetStatus','Switch.GetConfig','Switch.SetConfig','Switch.Set','Switch.Toggle','Switch.ResetCounters','BLE.GetConfig','BLE.SetConfig','BLE.GetStatus','Matter.GetConfig','Matter.SetConfig','Matter.GetStatus','Sys.GetStatus','Sys.GetConfig','Wifi.GetStatus','Wifi.GetConfig','Cloud.GetStatus','MQTT.GetStatus','Webhook.List']}
        elif m == 'MQTT.SetConfig':
            cfgin = (p.get('config') or {})
            # a real Shelly keeps the old client id while MQTT is enabled
            if 'client_id' in cfgin and (MQTTCFG.get('enable') and cfgin.get('enable', True)):
                cfgin = dict(cfgin); cfgin.pop('client_id')
            MQTTCFG.update(cfgin); r = {'restart_required': True}
        elif m == 'MQTT.GetConfig': r = dict(MQTTCFG)
        elif m == 'Shelly.Reboot': r = {}
        elif m == 'Shelly.GetConfig': r = {'switch:0': CONF['switch'], 'ble': CONF['ble'], 'matter': CONF['matter'], 'sys': {'device': {'name': 'Lednice'}}}
        elif m == 'Switch.GetConfig': r = dict(CONF['switch'], id=0)
        elif m == 'Switch.SetConfig':
            for k, v in (p.get('config') or {}).items():
                if k in CONF['switch']: CONF['switch'][k] = v
            r = {'restart_required': False}
        elif m == 'BLE.GetConfig': r = CONF['ble']
        elif m == 'BLE.SetConfig':
            c = p.get('config') or {}
            if 'enable' in c: CONF['ble']['enable'] = c['enable']
            if 'rpc' in c: CONF['ble']['rpc']['enable'] = c['rpc'].get('enable', CONF['ble']['rpc']['enable'])
            r = {'restart_required': True}
        elif m == 'BLE.GetStatus': r = {}
        elif m == 'Matter.GetConfig': r = CONF['matter']
        elif m == 'Matter.SetConfig': CONF['matter']['enable'] = (p.get('config') or {}).get('enable', CONF['matter']['enable']); r = {'restart_required': True}
        elif m == 'Matter.GetStatus': r = {'commissionable': True, 'num_fabrics': 0, 'setup_code': '3497-011-2332', 'qr_code': 'MT:XYZ'}
        elif m == 'Sys.GetStatus': r = {'uptime': 4242, 'ram_free': 100000, 'mac': 'AABBCC'}
        elif m == 'Wifi.GetStatus': r = {'sta_ip': '172.16.16.12', 'rssi': -58, 'ssid': 'iot'}
        elif m == 'Cloud.GetStatus': r = {'connected': False}
        elif m == 'MQTT.GetStatus': r = {'connected': True}
        elif m == 'Switch.Toggle':
            STATE['output'] = not STATE['output']; STATE['apower'] = 85.2 if STATE['output'] else 0.0; r = {'was_on': not STATE['output']}
        elif m == 'Shelly.Reboot': r = {}
        elif m == 'Shelly.GetDeviceInfo': r = {'id': 'shellyplugsg3-aabbcc', 'model': 'S3PL-00112EU', 'app': 'PlugSG3', 'ver': '1.7.1', 'gen': 3, 'name': 'Plug-TST'}
        elif m == 'Switch.Set':
            was = STATE['output']; STATE['output'] = bool(p.get('on')); STATE['apower'] = 85.2 if STATE['output'] else 0.0
            r = {'was_on': was}
        elif m == 'Switch.ResetCounters':
            for t in p.get('type') or ['aenergy', 'on_time', 'switch_on', 'on_above_thr']:
                if t == 'aenergy': STATE['aenergy']['total'] = 0; STATE['aenergy']['total_rst_ts'] = int(time.time())
                elif t in STATE['counts']: STATE['counts'][t] = 0
            r = {}
        else:
            r = None
        out = json.dumps({'id': body.get('id'), 'src': 'shellyplugsg3-aabbcc', 'result': r} if r is not None else {'id': 1, 'error': {'code': 404, 'message': 'no such method'}}).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(out))); self.end_headers(); self.wfile.write(out)
    def do_GET(self):
        out = json.dumps(CALLS).encode(); self.send_response(200); self.send_header('Content-Length', str(len(out))); self.end_headers(); self.wfile.write(out)

ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), H).serve_forever()
