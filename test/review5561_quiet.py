#!/usr/bin/env python3
"""5.56.1: --diag keeps every secret off the screen; a closed page is not an error.

`zigmon --diag` printed the Duo secret and integration keys and the password inside
the ntfy address in full. And a page that gave up waiting broke the pipe while the
headers went out: two tracebacks in the log for one closed tab.

    python3 test/review5561_quiet.py < /dev/null
"""
import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


sv = zigmon.shown_value
for key, val in (('duo_skey', 'FAKE-skey-0000111122223333'), ('duo_ikey', 'FAKEIKEY00001111'),
                 ('intel_shodan_key', 'fake-shodan-0123'), ('mqtt_password', 'fake-pw-1')):
    check(val not in str(sv(key, val)), '%s is printed in full' % key)
got = sv('notify_ntfy', 'https://someone:fakepass@ntfy.example.net/a-topic')
check('fakepass' not in got and 'ntfy.example.net/a-topic' in got and 'someone:' in got,
      'the password in an address is printed: %r' % got)
check(sv('acme_key', 'dual') == 'dual' and sv('mqtt_host', 'mqtt.example.net') == 'mqtt.example.net'
      and sv('public_url', 'https://mqtt.example.net/index.php') == 'https://mqtt.example.net/index.php',
      'settings that are no secret are starred')


class Gone(io.RawIOBase):
    def write(self, b):
        raise BrokenPipeError(32, 'Broken pipe')


h = zigmon.ApiHandler.__new__(zigmon.ApiHandler)
h.request_version = 'HTTP/1.1'
h.requestline = 'GET /api/energy HTTP/1.1'
h.command = 'GET'
h.client_address = ('127.0.0.1', 1)
h.wfile = Gone()
h.log_request = lambda *a, **k: None
try:
    h._send(200, {'ok': True, 'big': 'x' * 1000})
    raised = None
except Exception as e:                                    # noqa: BLE001
    raised = e
check(raised is None, 'a page gone before the headers raised %r' % raised)

print('review5561_quiet: ' + ('all good' if not bad else '%d FAILED' % len(bad)))
sys.exit(1 if bad else 0)
