#!/usr/bin/env python3
"""A Teltonika-lookalike SMS gateway, for testing without a SIM card.

    python3 test/mocksms.py 18110 [user] [password]

Speaks the CGI dialect a TRB140 does: /cgi-bin/sms_send, /cgi-bin/sms_list,
/cgi-bin/sms_delete. GET / returns what it has been asked to send, so a test
can check the message actually went out; POST /inbox puts a message in the
box for the daemon to find.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

SENT, INBOX = [], []
USER = sys.argv[2] if len(sys.argv) > 2 else 'admin'
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else 'secret'


SIGNAL = {'rssi': -71, 'rsrp': -101, 'rsrq': -11, 'sinr': 9, 'conn_type': 'LTE'}
INFO = {'operator': 'Vodafone CZ', 'net_mode': 'LTE', 'sim_state': 'ready',
        'imei': '350000000000001', 'cell_id': '1A2B3C', 'roaming': 'no', 'temperature': 372}
USAGE = {'month': {'total': 734003200}, 'today': {'total': 41943040}}


class Handler(BaseHTTPRequestHandler):
    def _ubus(self, body):
        """Just enough of RutOS's JSON-RPC to be worth testing against."""
        params = body.get('params') or []
        session, obj, method = (params + ['', '', ''])[:3]
        def out(result):
            self._text(json.dumps({'jsonrpc': '2.0', 'id': body.get('id'), 'result': [0, result]}))
        if obj == 'session' and method == 'login':
            given = params[3] if len(params) > 3 else {}
            if given.get('username') != USER or given.get('password') != PASSWORD:
                return self._text(json.dumps({'jsonrpc': '2.0', 'id': body.get('id'), 'error': 'wrong password'}), 200)
            return out({'ubus_rpc_session': 'abcdef0123456789'})
        if session != 'abcdef0123456789':
            return self._text(json.dumps({'jsonrpc': '2.0', 'id': body.get('id'), 'result': [6]}))
        if obj == 'gsm.modem0' and method == 'get_signal_query':
            return out(dict(SIGNAL))
        if obj == 'gsm.modem0' and method == 'info':
            return out(dict(INFO))
        if obj == 'gsm.modem0' and method == 'get_data_usage':
            return out(dict(USAGE))
        return self._text(json.dumps({'jsonrpc': '2.0', 'id': body.get('id'), 'result': [4]}))

    def log_message(self, *a):
        pass

    def _text(self, body, code=200):
        raw = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _auth(self, q):
        return (q.get('username', [''])[0] == USER and q.get('password', [''])[0] == PASSWORD)

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path.startswith('/api/'):
            return self._rest(url.path, {})
        if url.path == '/':
            return self._text(json.dumps({'sent': SENT, 'inbox': INBOX}))
        if not self._auth(q):
            return self._text('ERROR: wrong username or password', 403)
        if url.path == '/cgi-bin/sms_send':
            SENT.append({'number': q.get('number', [''])[0], 'text': q.get('text', [''])[0]})
            return self._text('OK')
        if url.path == '/cgi-bin/sms_list':
            if not INBOX:
                return self._text('No messages')
            out = []
            for i, m in enumerate(INBOX):
                out.append('Index: %d\nSender: %s\nText: %s\n' % (i, m['from'], m['text']))
            return self._text('\n'.join(out))
        if url.path == '/cgi-bin/status':
            return self._text('Operator: Vodafone CZ\nConnection type: LTE\nSignal strength: -71 dBm\n'
                              'RSRP: -101\nRSRQ: -11\nSINR: 9\nSIM state: ready\nIMEI: 350000000000001\n')
        if url.path == '/cgi-bin/sms_delete':
            INBOX.clear()
            return self._text('OK')
        return self._text('ERROR: no such path', 404)

    # ---- RutOS 7's own API, the one a TRB140 offers out of the box ----------
    def _rest(self, path, body):
        """/api/... : a Bearer token from /api/login, and the shapes the
        device's own OpenAPI description gives."""
        if path == '/api/login':
            if body.get('username') != USER or body.get('password') != PASSWORD:
                return self._json({'success': False, 'errors': [{'source': 'Authentication'}]}, 403)
            return self._json({'success': True, 'data': {'username': USER, 'group': 'root',
                                                         'token': 'tok-abcdef', 'expires': 299}})
        if self.headers.get('Authorization') != 'Bearer tok-abcdef':
            return self._json({'success': False, 'errors': [{'source': 'Authorization'}]}, 401)
        if path == '/api/modems/status':
            return self._json({'success': True, 'data': [{
                'id': '3-1', 'model': 'EG25-G', 'imei': '350000000000001', 'operator': 'T-Mobile CZ',
                'provider': 'T-Mobile', 'conntype': 'LTE', 'band': 'LTE B3', 'cellid': '1A2B3C',
                'lac': '2710', 'tac': '9C41', 'simstate': 'Inserted', 'pinstate': 'Disabled',
                'pinleft': 3, 'state': 'Connected', 'netstate': 'registered (home)',
                'operator_state': 'Registered', 'volte': 'enabled', 'active_sim': 'SIM 1',
                'iccid': '8942001340310250844F', 'imsi': '230015028826272', 'provider': 'T-Mobile CZ',
                'operator_state': 'Registered, home', 'ntype': '4G (LTE)', 'sim_count': 1,
                'signal_quality': 62, 'mimo_4g_max': '2', 'busy_state': 'no', 'version': 'EG25GGBR07A08M2G',
                'sms_center_address': '+420603052000', 'external_antenna_enabled': 'no',
                'rssi': -51, 'rsrp': -81, 'rsrq': -9, 'sinr': 14, 'ecio': -6, 'rscp': -70,
                'signal_quality': 82, 'temperature': 37,
                'txbytes': 41943040, 'rxbytes': 734003200}]})
        if path == '/api/modems/signal/status':
            return self._json({'success': True, 'data': [{'modem': '3-1', 'signal': [
                {'band': 'LTE B1', 'earfcn': 500, 'bandwidth': 20, 'pcid': 219,
                 'rssi': -51, 'rsrp': -81, 'rsrq': -9, 'sinr': 14}]}]})
        if path == '/api/messages/status':
            return self._json({'success': True, 'data': [
                {'id': str(i), 'sender': m['from'], 'message': m['text'], 'modem_id': '3-1',
                 'status': 'unread', 'date': 'Wed Sep 10 09:00:00 2026'} for i, m in enumerate(INBOX)]})
        if path == '/api/messages/actions/remove_messages':
            data = (body or {}).get('data') or {}
            if not data.get('modem_id') or not data.get('sms_id'):
                return self._json({'success': False, 'errors': [{'source': 'modem_id'}]}, 400)
            for one in sorted((int(x) for x in data['sms_id']), reverse=True):
                if 0 <= one < len(INBOX):
                    INBOX.pop(one)
            return self._json({'success': True, 'data': {}})
        if path.startswith('/api/modems/') and path.endswith('/actions/send_ussd'):
            code = ((body or {}).get('data') or {}).get('ussd') or ''
            if not code:
                return self._json({'success': False, 'errors': [{'source': 'ussd'}]}, 400)
            return self._json({'success': True, 'data': {
                'message': 'Na 734127811 je zustatek kreditu 400,00 Kc platny do 11.09.2027. '
                           'K tomu mate bonusovy kredit 94,90 Kc. T-Mobile #mezisvy'}})
        if path == '/api/messages/actions/send':
            data = (body or {}).get('data') or {}
            for need in ('number', 'message', 'modem'):
                if not data.get(need):
                    # exactly what the device says when a required field is missing
                    return self._json({'success': False, 'errors': [{'source': need, 'code': 400}]}, 400)
            if not str(data['number']).startswith('+'):
                return self._json({'success': False, 'errors': [{'source': 'number', 'reason': 'phonedigit'}]}, 400)
            SENT.append({'number': data['number'], 'text': data['message'], 'modem': data['modem']})
            return self._json({'success': True, 'data': {'sms_used': 1}})
        return self._json({'success': False, 'errors': [{'source': 'path'}]}, 404)

    def _json(self, obj, code=200):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        length = int(self.headers.get('Content-Length') or 0)
        body = json.loads(self.rfile.read(length) or b'{}')
        if urlparse(self.path).path == '/ubus':
            return self._ubus(body)
        path = urlparse(self.path).path
        if path.startswith('/api/'):
            return self._rest(path, body)
        if path == '/inbox':
            INBOX.append({'from': body.get('from', '+420777123456'), 'text': body.get('text', '')})
            return self._text('OK')
        if path == '/reset':
            SENT.clear(); INBOX.clear()
            return self._text('OK')
        return self._text('ERROR', 404)


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()
