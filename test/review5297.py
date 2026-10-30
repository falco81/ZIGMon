#!/usr/bin/env python3
"""5.29.7: the command line and the console know the SMS gateway's AT+CMMS.
Every check fails on 5.29.6 and passes since.

    python3 test/review5297.py
"""
import contextlib
import io
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

print('zigmon --sms status says how long texts are sent')
status = {'sms': {'ready': True, 'sent_today': 3, 'cmms': 'always'},
          'devices': [{'id': 'sms:gateway', 'values': {'rssi': -71, 'cmms': 0}}], 'sms_outbox': []}
zigmon._need_daemon = lambda pal, path='/api/status': status


class Args:
    sms = 'status'
    number = None
    text = None
    json = False


pal = zigmon.Palette(False)
out = io.StringIO()
with contextlib.redirect_stdout(out):
    try:
        zigmon.cmd_sms(Args(), pal)
    except Exception as e:                              # noqa: BLE001
        print('crashed: %s' % e)
text = out.getvalue()
check('AT+CMMS' in text and 'the modem says 0' in text,
      '--sms status says nothing of AT+CMMS, or of what the modem says: %r' % text[-300:])

print('the console has the SMS gateway, and its AT+CMMS switch saves the setting')
names = [n for n, _f in zigmon.CONSOLE_MORE.get('main', [])]
check('SMS gateway' in names, 'the console has no SMS gateway: %r' % names)
fn = dict(zigmon.CONSOLE_MORE.get('main', [])).get('SMS gateway')
if fn:
    ran = []

    class FakeConsole:
        def sub(self, title, items, key):
            self.items = items
            return items

        def act(self, *a):
            ran.append(a)
            return 0

        def ask_one(self, title, label, value='', help_='', need=True, secret=False, check=None):
            return 'per_message'
    c = FakeConsole()
    items = dict(fn(c))
    act = next((f for n, f in items.items() if 'AT+CMMS' in n and 'How' not in n), None)
    if act:
        act()
    check(('--settings', 'sms_cmms=per_message') in ran, 'the console\'s AT+CMMS switch saved nothing: %r' % ran)
    items[next(n for n in items if n.startswith('How it is'))]()
    check(('--sms', 'status') in ran, 'the console does not show the gateway\'s state')

sys.stdout.flush()
if bad:
    print('\n%d check(s) failed' % len(bad))
    os._exit(1)
print('the command line and the console know AT+CMMS')
os._exit(0)
