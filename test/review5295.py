#!/usr/bin/env python3
"""5.29.5: a long text does not stall the SMS gateway. Every check fails on
5.29.4 and passes since.

    python3 test/review5295.py

Measured on a TRB140 (TRB1_R_00.07.24.7, 29.10.2026): a text of two parts
handed to it a few seconds after it took one in held its modem 50-60 s; with
AT+CMMS=2 the same went in 0.8 s. A Teltonika-lookalike API here, with the
modem's command line (exec_at) as the box answers it.
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
W = Path(tempfile.mkdtemp(prefix='zigmon-review5295-check-'))
PORT = 19854
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


GW = {'calls': [], 'cmms': 0, 'at_fails': False}


class Gateway(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _out(self, obj):
        raw = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == '/api/modems/status':
            return self._out({'success': True, 'data': [{'id': '3-1'}]})
        return self._out({'success': True, 'data': []})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        data = body.get('data') or {}
        if self.path == '/api/login':
            return self._out({'success': True, 'data': {'token': 'tok', 'expires': 299}})
        if self.path == '/api/modems/3-1/actions/exec_at':
            cmd = data.get('command')
            GW['calls'].append(('at', cmd, time.time()))
            if GW['at_fails']:
                return self._out({'success': False, 'errors': [{'error': 'busy'}]})
            if cmd == 'AT+CMMS?':
                return self._out({'success': True, 'data': {'response': '+CMMS: %d\r\n\r\nOK' % GW['cmms']}})
            if cmd.startswith('AT+CMMS='):
                GW['cmms'] = int(cmd[-1])
                return self._out({'success': True, 'data': {'response': 'OK'}})
            return self._out({'success': True, 'data': {'response': 'ERROR'}})
        if self.path == '/api/messages/actions/send':
            GW['calls'].append(('send', data.get('message'), time.time()))
            return self._out({'success': True, 'data': {'sms_used': 1}})
        return self._out({'success': True, 'data': {}})


srv = ThreadingHTTPServer(('127.0.0.1', PORT), Gateway)
threading.Thread(target=srv.serve_forever, daemon=True).start()

sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 0, 'token_file': str(W / 'run' / 'api-token'),
                      'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '',
                      'state_dir': str(W / 'state'), 'sms_enabled': True, 'sms_host': '127.0.0.1',
                      'sms_port': PORT, 'sms_https': False, 'sms_api': 'rest', 'sms_user': 'admin',
                      'sms_password': 'x', 'sms_send_gap_s': 0, 'sms_timeout_s': 15, 'sms_daily_cap': 0})
(W / 'state').mkdir()
d = zigmon.Daemon()
LONG = 'Doma jsou: Falco\n' + '\n'.join('--------------------\nPlug number %d is on' % i for i in range(6))
SHORT = 'on'

print('AT+CMMS kept at 2, and set again when the modem forgot it')
check(zigmon.DEFAULTS.get('sms_cmms') == 'always', 'there is no AT+CMMS setting, on by default')
said = []
was_log = zigmon.log
zigmon.log = lambda msg, level='info': said.append(str(msg)) or was_log(msg, level)
try:
    GW['cmms'] = 0                                         # a modem just restarted
    getattr(d, 'sms_cmms_beat', lambda: None)()
finally:
    zigmon.log = was_log
check(GW['cmms'] == 2, 'the modem was left at AT+CMMS=%d' % GW['cmms'])
check([m for m in said if 'set again' in m], 'setting AT+CMMS again was not said')
d._sms_sent_at = 0
GW['calls'].clear()
getattr(d, 'sms_cmms_beat', lambda: None)()
check([c for c in GW['calls'] if c[1] == 'AT+CMMS?'] and not [c for c in GW['calls'] if c[1] == 'AT+CMMS=2'],
      'a modem that holds AT+CMMS=2 was told again: %r' % GW['calls'])

print('nothing but AT+CMMS ever reaches the modem')
try:
    d._sms_at('AT+CFUN=0')
    ok = False
except (ValueError, AttributeError):
    ok = True
check(ok, 'any AT command can be passed to the modem')

print('per message: AT+CMMS=1 just before a long text, and only then')
zigmon.CONFIG['sms_cmms'] = 'per_message'
GW['calls'].clear()
d.sms_send('+420777000111', SHORT, why='alert', queue=False)
check(not [c for c in GW['calls'] if c[0] == 'at'], 'a text of one part asked the modem for AT+CMMS')
GW['calls'].clear()
d.sms_send('+420777000111', LONG, why='alert', queue=False)
kinds = [(c[0], c[1] if c[0] == 'at' else 'text') for c in GW['calls']]
check(kinds[:2] == [('at', 'AT+CMMS=1'), ('send', 'text')], 'a long text went without AT+CMMS=1 before it: %r' % kinds)
GW['at_fails'] = True
GW['calls'].clear()
ok, _w = d.sms_send('+420777000111', LONG, why='alert', queue=False)
GW['at_fails'] = False
check(ok and [c for c in GW['calls'] if c[0] == 'send'], 'a modem refusing AT+CMMS stopped the text')

print('leaving "always" puts the modem back to 0')
zigmon.CONFIG['sms_cmms'] = 'always'
d._sms_sent_at = 0
d.sms_cmms_beat()
zigmon.CONFIG['sms_cmms'] = 'off'
d._sms_sent_at = 0
d.sms_cmms_beat()
check(GW['cmms'] == 0, 'AT+CMMS stayed %d after it was switched off' % GW['cmms'])

print('with it off, a long answer goes as short ones')
d._sms_push_at = 0
GW['calls'].clear()
d.sms_reply('+420777000111', LONG)
end = time.time() + 15
while time.time() < end:
    n = len([c for c in GW['calls'] if c[0] == 'send'])
    time.sleep(1.0)
    if n and n == len([c for c in GW['calls'] if c[0] == 'send']):
        break
sends = [c[1] for c in GW['calls'] if c[0] == 'send']
check(len(sends) > 1 and all(zigmon.Daemon.sms_parts(t) == 1 for t in sends),
      'a long answer with the link not held open went as %r part(s)' % [zigmon.Daemon.sms_parts(t) for t in sends])
zigmon.CONFIG['sms_cmms'] = 'always'

print('the help is one message, and a text pushed twice is answered once')
check(zigmon.Daemon.sms_parts(d.sms_help()) == 1 and '|' not in d.sms_help(),
      'the help is %d messages: %r' % (zigmon.Daemon.sms_parts(d.sms_help()), d.sms_help()))
seen = getattr(d, 'sms_push_seen', None)
check(seen and not seen('+420777000111', 'Status') and seen('+420 777 000 111', 'Status')
      and not seen('+420777000111', 'Help'), 'the same text pushed twice in a second is acted on twice')
# ...and the same command sent again on purpose, a few seconds later, is a
# command (5.29.5 swallowed it for fifteen seconds)
time.sleep(2.5)
check(seen and not seen('+420777000111', 'Status'), 'the same command sent again a few seconds later was ignored')
if seen:
    try:
        stamped = (not seen('+420777000111', 'on', 'date=2026-10-29 15:00:01')
                   and not seen('+420777000111', 'on', 'date=2026-10-29 15:00:04'))
        time.sleep(2.5)
        stamped = stamped and seen('+420777000111', 'on', 'date=2026-10-29 15:00:01')
    except TypeError:
        stamped = False
    check(stamped, 'the gateway\'s own stamp of a message is not what tells a double from a command sent again')

sys.stdout.flush()
if bad:
    print('\n%d check(s) failed' % len(bad))
    os._exit(1)
print('a long text does not stall the gateway')
os._exit(0)
