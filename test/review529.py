#!/usr/bin/env python3
"""5.29: an answer by text is not sent into a gateway still busy with the
push it answers, and a slow gateway says what it was doing. Every check fails
on 5.28.0 and passes since.

    python3 test/review529.py

A Teltonika-lookalike REST API on a port of its own; no SIM card.
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
W = Path(tempfile.mkdtemp(prefix='zigmon-review529-check-'))
PORT = 19853
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


GW = {'sent': [], 'send_delay': 0.0, 'logins': 0, 'logouts': 0}


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
            return self._out({'success': True, 'data': [{'id': '1-1'}]})
        return self._out({'success': True, 'data': []})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        if self.path == '/api/login':
            GW['logins'] += 1
            return self._out({'success': True, 'data': {'token': 't0k3n%d' % GW['logins'], 'expires': 299}})
        if self.path == '/api/logout':
            GW['logouts'] += 1
            return self._out({'success': True, 'data': {}})
        if self.path == '/api/messages/actions/send':
            GW['sent'].append((time.time(), (body.get('data') or {}).get('message')))
            if GW['send_delay']:
                time.sleep(GW['send_delay'])
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

print('an answer to a pushed text waits until the push is answered')
pushed = time.time()
d._sms_push_at = pushed                                  # as the webhook does
d.sms_reply('+420777000111', 'Doma jsou: Falco')
end = time.time() + 6
while not GW['sent'] and time.time() < end:
    time.sleep(0.02)
check(GW['sent'] and GW['sent'][0][0] - pushed >= 1.8,
      'the answer was handed to the gateway %.2f s after the push, while it was still busy with it'
      % ((GW['sent'][0][0] - pushed) if GW['sent'] else -1))

print('a slow gateway says what else it was asked meanwhile')
said = []
was_log = zigmon.log
zigmon.log = lambda msg, level='info': said.append((level, str(msg))) or was_log(msg, level)
GW['send_delay'] = 5.5
try:
    d.sms_send('+420777000111', 'a slow one', why='alert', queue=False)
finally:
    zigmon.log = was_log
    GW['send_delay'] = 0
check([m for lv, m in said if 'took' in m and '/messages/actions/send' in m],
      'a send that took 5.5 s at the gateway was not said as slow, nor with what else was asked: %r'
      % [m for _lv, m in said][-3:])

print('the SMS tab sees a message settle, and tells "going" from "no answer"')
rid = d.sms_note('out', '+420777000111', 'on its way', None, 'reply')
m1 = d._sms_log_mark()
row = next(r for r in d.sms_log(10) if r.get('id') == rid)
check(row.get('going') is True, 'a message handed to the gateway and not answered yet is not told from one never answered')
d.sms_note_settled(rid, True)
m2 = d._sms_log_mark()
check(m1 != m2, 'a message settling from going to sent leaves the mark the page watches as it was: '
      'the tab showed it as not answered until it was reloaded (%r)' % m2)
row = next(r for r in d.sms_log(10) if r.get('id') == rid)
check(row.get('ok') is True and not row.get('going'), 'a settled message is still marked as going')
page = (HERE / 'web' / 'index.php').read_text()
log = page[page.index('function renderSmsLog('):page.index("var tools = $('sms-log-tools');")]
check('log_rev' in log, 'the SMS tab does not fetch the log again when a message settles')
check('sending\\u2026' in log and 'm.going' in log, 'a message on its way is drawn as "no answer from the gateway"')

print('one session on the gateway, not a new one every four minutes')
before = GW['logins']
real = time.time
try:
    for k in range(12):                                  # an hour of status questions, five minutes apart
        time.time = lambda k=k: real() + k * 300
        d._rest('/modems/status')
finally:
    time.time = real
check(GW['logins'] - before <= 1, 'an hour of questions logged in %d times: a session on the gateway each, '
      'never logged out' % (GW['logins'] - before))
outs = GW['logouts']
if hasattr(d, '_sms_drop_token'):
    d._sms_drop_token()
    time.sleep(0.5)
check(GW['logouts'] > outs, 'a token dropped (a new password, a test) is left as a session on the gateway')

sys.stdout.flush()
if bad:
    print('\n%d check(s) failed' % len(bad))
    os._exit(1)
print('an answer by text waits for its push, and a slow gateway says why')
os._exit(0)
