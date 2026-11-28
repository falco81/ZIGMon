#!/usr/bin/env python3
"""A mock of the gateway's web UI API (/api/*) serving esp32/ZigmonGateway/web/, for looking at
the UI in a browser and for the screenshots. Every name, serial number and key here is made up.

    python3 esp32/tests/webmock.py 8099 [state]

state: "app" (logged in, default), "login", "setup", "empty" (logged in, no locks), "pairing".
Plain HTTP on 127.0.0.1 only; the real gateway serves the same files over HTTPS.
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import os
WEB = Path(os.environ.get('WEB_DIR') or Path(__file__).resolve().parent.parent / 'ZigmonGateway' / 'web').resolve()
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
MODE = sys.argv[2] if len(sys.argv) > 2 else 'app'
NOW = lambda: int(time.time())

LOCKS = [
    {'id': 'front', 'name': 'Front drawer', 'sn': 'TEST0001', 'key': 'set (..3f)', 'entity': 'yeelock.front', 'problem': '', 'in_range': True},
    {'id': 'cabinet', 'name': 'Medicine cabinet', 'sn': 'TEST0002', 'key': 'set (..a1)', 'entity': 'yeelock.cabinet', 'problem': 'wrong_key', 'in_range': True},
    {'id': 'garage', 'name': 'Garage tool box', 'sn': 'TEST0003', 'key': 'set (..07)', 'entity': 'yeelock.garage', 'problem': '', 'in_range': False},
]
if MODE == 'empty':
    LOCKS = []


def entity(l):
    return {'id': l['entity'], 'module': 'yeelock', 'type': 'lock', 'name': l['name'],
            'actions': ['open', 'unlock', 'lock', 'refresh'],
            'attrs': [{'key': 'battery', 'label': 'Battery', 'type': 'number', 'unit': '%', 'min': 0, 'max': 100},
                      {'key': 'rssi', 'label': 'Signal', 'type': 'number', 'unit': 'dBm'}],
            'confirm': ['open', 'unlock']}


STATES = {
    'yeelock.front': {'available': True, 'value': 'locked', 'busy': False, 'attrs': {'battery': 87, 'rssi': -61},
                      'last': {'action': 'open', 'ok': True, 'at': NOW() - 240, 'msg': 'opened, locked again [UNLOCK_START UNLOCK_CMP LOCK_CMP]'}},
    'yeelock.cabinet': {'available': True, 'value': 'unknown', 'busy': False, 'problem': 'wrong_key', 'attrs': {'battery': 34, 'rssi': -72},
                        'last': {'action': 'check', 'ok': False, 'at': NOW() - 60, 'msg': 'reachable, but the sign key is WRONG (TX_SIGN_INVALID)', 'problem': 'wrong_key'}},
    'yeelock.garage': {'available': False, 'value': 'unknown', 'busy': False, 'attrs': {'battery': 12},
                       'last': {'action': 'refresh', 'ok': False, 'at': NOW() - 5400, 'msg': 'lock not found (in range? right serial number?)', 'problem': 'not_found'}},
}
JOBS = [
    {'id': 'j1a2b3c4', 'entity': 'yeelock.cabinet', 'action': 'check', 'status': 'done', 'ok': False, 'msg': 'reachable, but the sign key is WRONG (TX_SIGN_INVALID)', 'at': NOW() - 60},
    {'id': 'j5d6e7f8', 'entity': 'yeelock.front', 'action': 'open', 'status': 'done', 'ok': True, 'msg': 'opened, locked again', 'at': NOW() - 240},
    {'id': 'j9a0b1c2', 'entity': 'yeelock.garage', 'action': 'refresh', 'status': 'done', 'ok': False, 'msg': 'lock not found (in range? right serial number?)', 'at': NOW() - 5400},
]

SCHEMA = {
    'settings': [
        {'key': 'scan_s', 'label': 'Scan time', 'type': 'number', 'help': 'How long to look for a lock whose address is not known yet.', 'min': 2, 'max': 30, 'unit': 's'},
        {'key': 'conn_s', 'label': 'Connect timeout', 'type': 'number', 'help': 'Give up connecting after this long.', 'min': 3, 'max': 30, 'unit': 's'},
        {'key': 'battery_h', 'label': 'Battery check', 'type': 'number', 'help': "Read every lock's battery this often when idle (0 = never).", 'min': 0, 'max': 168, 'unit': 'h'}],
    'collection': {
        'key': 'locks', 'title': 'Locks', 'item': 'lock', 'max': 10, 'entity_prefix': 'yeelock.',
        'fields': [
            {'key': 'name', 'label': 'Name', 'type': 'text', 'required': True, 'max': 40, 'placeholder': 'Front drawer'},
            {'key': 'id', 'label': 'ID', 'type': 'slug', 'max': 20, 'create_only': True, 'help': 'Part of the entity id yeelock.<id>. Leave empty to derive it from the name.'},
            {'key': 'sn', 'label': 'Serial number', 'type': 'text', 'required': True, 'max': 20, 'pattern': '^(EL_)?[A-Za-z0-9]{4,20}$', 'help': "As on the lock's label, or the BLE name EL_<SN> without EL_."},
            {'key': 'key', 'label': 'BLE sign key', 'type': 'secret', 'required': True, 'max': 100, 'pattern': '^[0-9A-Fa-f :-]{16,100}$', 'help': 'ble_sign_key in hex (8-32 bytes), from yeehack fetch. Leave empty to keep the stored key.'}],
        'discover': {'label': 'Scan for locks', 'hint': 'Nearby Yeelocks (EL_...) appear here; pick one to fill the serial number.'},
        'check': {'call': 'check', 'label': 'Check', 'hint': 'Connects, reads the battery and sends only a time sync: never unlocks.'},
        'import': {'call': 'cloud', 'label': 'Import from my Yeelock account',
                   'help': 'The gateway asks the Yeelock cloud (api.yeeloc.com, verified HTTPS) once for your locks and their sign keys. Your password is used for this one request and never stored. Adding a lock by hand (S/N + key) works without it.',
                   'fields': [
                       {'key': 'zone', 'label': 'Country code', 'type': 'text', 'required': True, 'max': 4, 'pattern': '^[0-9]{1,4}$', 'placeholder': '420', 'help': "Your phone's country calling code without +."},
                       {'key': 'username', 'label': 'Phone number', 'type': 'text', 'required': True, 'max': 64, 'placeholder': '123456789', 'help': 'Without the country code.'},
                       {'key': 'password', 'label': 'Yeelock password', 'type': 'password', 'required': True, 'max': 128}]}},
}
FOUND = [
    {'sn': 'TEST0001', 'label': 'EL_TEST0001', 'detail': '-61 dBm', 'rssi': -61, 'known': True, 'known_as': 'Front drawer'},
    {'sn': 'TEST0004', 'label': 'EL_TEST0004', 'detail': '-58 dBm', 'rssi': -58, 'known': False, 'in_account': 'Bedside table'},
    {'sn': 'TEST0005', 'label': 'EL_TEST0005', 'detail': '-83 dBm', 'rssi': -83, 'known': False},
]
CLOUD = [
    {'sn': 'TEST0004', 'name': 'Bedside table', 'key': 'set (..9c)', 'has_key': True, 'known': False, 'in_range': True, 'rssi': -58},
    {'sn': 'TEST0006', 'name': 'Office desk', 'key': 'set (..e2)', 'has_key': True, 'known': False, 'in_range': False},
    {'sn': 'TEST0001', 'name': 'Front drawer', 'key': 'set (..3f)', 'has_key': True, 'known': True, 'in_range': True, 'rssi': -61},
]
LOG = ['     2.1 I boot: ZIGMon Gateway 1.0.0 on esp32s3 (PSRAM found)', '     2.4 I cert: certificate loaded',
       '     2.9 I modules: yeelock 1.0.0 started', '     3.0 I ble: NimBLE ready', '     4.8 I wifi: connected to "Home Wi-Fi", IP 192.168.1.50, RSSI -58 dBm',
       '     4.9 I mdns: zigmon-gw-d4e5f6.local', '    12.3 I auth: web login', '   340.2 I job: j5d6e7f8 yeelock.front open: ok - opened, locked again',
       '   902.7 W job: j1a2b3c4 yeelock.cabinet check: FAILED - reachable, but the sign key is WRONG (TX_SIGN_INVALID)',
       '   950.0 E yeelock: lock garage not found']


def overview():
    n = len(LOCKS)
    return {'text': '%d locks, wrong sign key' % n if n else 'No locks yet', 'level': 'crit' if n else 'info', 'count': n}


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype='application/json'):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = self.path.split('?')[0]
        if not p.startswith('/api/'):
            f = WEB / ('index.html' if p == '/' else p.lstrip('/'))
            if f.is_file() and WEB in f.resolve().parents:
                t = {'.html': 'text/html; charset=utf-8', '.js': 'application/javascript', '.css': 'text/css', '.svg': 'image/svg+xml'}[f.suffix]
                return self.send(200, f.read_bytes(), t)
            return self.send(404, b'nope', 'text/plain')
        return self.api(p[4:], None)

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        body = json.loads(self.rfile.read(n) or b'{}')
        return self.api(self.path[4:], body)

    def api(self, p, body):
        if p == '/session':
            return self.send(200, {'ok': True, 'v': 1, 'password_set': MODE != 'setup', 'setup_open': True, 'setup_left': 540,
                                   'logged_in': MODE not in ('login', 'setup'), 'csrf': 'c' * 32, 'lockout': 0,
                                   'name': 'Hall gateway', 'fw': '1.0.0'})
        if p in ('/login', '/setup'):
            return self.send(200, {'ok': True, 'csrf': 'c' * 32})
        if p == '/modules':
            return self.send(200, {'ok': True, 'modules': [{'id': 'yeelock', 'name': 'Yeelock locks', 'version': '1.0.0', 'icon': 'lock', 'overview': overview()}]})
        if p == '/overview':
            return self.send(200, {'ok': True, 'gateway': {'name': 'Hall gateway', 'id': 'a1b2c3d4e5f6', 'fw': '1.0.0', 'model': 'esp32s3', 'uptime': 93784, 'heap': 187392, 'psram': True},
                                   'wifi': {'configured': True, 'ssid': 'Home Wi-Fi', 'connected': True, 'ip': '192.168.1.50', 'rssi': -58, 'hostname': 'zigmon-gw-d4e5f6', 'dhcp': True},
                                   'time': {'set': True, 'now': NOW()}, 'zigmon': {'paired': MODE != 'pairing', 'name': 'ZIGMon (home)'},
                                   'modules': [{'id': 'yeelock', 'name': 'Yeelock locks', 'version': '1.0.0', 'icon': 'lock', 'overview': overview()}],
                                   'jobs': JOBS if LOCKS else []})
        if p == '/state':
            return self.send(200, {'ok': True, 'seq': 42, 'entities': {k: v for k, v in STATES.items() if any(l['entity'] == k for l in LOCKS)}, 'jobs': JOBS})
        if p == '/m/yeelock':
            return self.send(200, {'ok': True, 'module': {'id': 'yeelock', 'name': 'Yeelock locks', 'version': '1.0.0', 'icon': 'lock'},
                                   'schema': SCHEMA, 'settings': {'scan_s': 5, 'conn_s': 10, 'battery_h': 12}, 'items': LOCKS,
                                   'entities': [entity(l) for l in LOCKS], 'states': {l['entity']: STATES[l['entity']] for l in LOCKS},
                                   'discover': {'running': False, 'at': 0, 'results': []}})
        if p == '/m/yeelock/discover':
            return self.send(200, {'ok': True, 'running': False, 'at': NOW(), 'results': FOUND})
        if p == '/m/yeelock/x/cloud':
            return self.send(200 if body is None else 202, {'ok': True, 'running': False, 'age': 3, 'keep': 600, 'results': CLOUD})
        if p == '/wifi':
            return self.send(200, {'ok': True, 'configured': True, 'ssid': 'Home Wi-Fi', 'connected': True, 'ip': '192.168.1.50', 'rssi': -58,
                                   'hostname': 'zigmon-gw-d4e5f6', 'dhcp': True, 'password': 'set (..42)',
                                   'static': {'ip': '0.0.0.0', 'mask': '0.0.0.0', 'gw': '0.0.0.0', 'dns': '0.0.0.0'}})
        if p == '/wifi/scan':
            return self.send(200, {'ok': True, 'running': False, 'networks': [
                {'ssid': 'Home Wi-Fi', 'rssi': -58, 'secure': True, 'ch': 6}, {'ssid': 'Home Wi-Fi 5G-less IoT', 'rssi': -63, 'secure': True, 'ch': 11},
                {'ssid': 'Neighbour', 'rssi': -81, 'secure': True, 'ch': 1}, {'ssid': 'Cafe guest', 'rssi': -88, 'secure': False, 'ch': 3}]})
        fp = 'ab:cd:ef:01:23:45:67:89:ab:cd:ef:01:23:45:67:89:ab:cd:ef:01:23:45:67:89:ab:cd:ef:01:23:45:67:89'.upper()
        if p.startswith('/zigmon'):
            active = MODE == 'pairing'
            return self.send(200, {'ok': True, 'paired': not active, 'zigmon': 'ZIGMon (home)', 'fingerprint': fp.replace(':', '').lower(), 'fingerprint_pretty': fp,
                                   'id': 'a1b2c3d4e5f6', 'ip': '192.168.1.50', 'hostname': 'zigmon-gw-d4e5f6',
                                   'pairing': {'active': active, 'code': '482913', 'expires_in': 512, 'locked_for': 0} if active else {'active': False, 'locked_for': 0}})
        if p == '/system':
            return self.send(200, {'ok': True, 'fw': '1.0.0', 'model': 'esp32s3', 'cores': 2, 'revision': 2, 'flash': 16777216, 'psram': 8388608,
                                   'heap': 187392, 'heap_min': 151000, 'uptime': 93784, 'hostname': 'zigmon-gw-d4e5f6', 'name': 'Hall gateway', 'id': 'a1b2c3d4e5f6',
                                   'fingerprint': fp.replace(':', '').lower(), 'fingerprint_pretty': fp, 'time_set': True, 'now': NOW(), 'log_level': 'info',
                                   'sdk': 'v5.3.2', 'log': LOG})
        if body is not None:
            return self.send(200 if '/x/check' not in p and p != '/command' else 202, {'ok': True, 'job': 'jdeadbeef', 'added': 1, 'id': 'new'})
        return self.send(404, {'ok': False, 'error': 'not found'})


if __name__ == '__main__':
    print('web UI mock on http://127.0.0.1:%d (%s)' % (PORT, MODE), flush=True)
    ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
