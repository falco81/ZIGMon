#!/usr/bin/env python3
"""5.43.3: a hunt through the messages, out and in - the SMS gateway, the
notifications, quiet hours and the Events log. Each check fails on 5.43.2.

  * An automatic alert cut to one part ended in "…", which is outside the
    GSM alphabet: the plain text turned wide and went out as three parts (a
    critical one's two as five).
  * After an alert's send timed out, the next send was not held off: only a
    reply's "no answer" set the half-minute hold, an alert's "timed out" did
    not.
  * With debug on, a push by GET wrote the agreed word into the log in full,
    in the request line and the modem's own URI.
  * Testing the gateway with the webhook on read the modem's inbox and acted
    on what the webhook had already handled.
  * A search of the Events log for a device's name found none of that
    device's rows whose words did not repeat the name.
  * One phone named twice (a person and their number) was texted twice.
  * "sleep off" let new texts through but left the ones it held waiting for
    the morning.
  * The clock's USSD question went to the modem beside a text being sent.
  * Somebody ticked for alerts and not commands, writing in, was texted
    their own words back.

    python3 test/hunt5433_msg.py
"""
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(os.environ.get('ZIGMON_HERE') or Path(__file__).resolve().parent.parent)
W = Path(tempfile.mkdtemp(prefix='zigmon-hunt5433-msg-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 0, 'token_file': str(W / 'run' / 'api-token'),
                      'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '',
                      'state_dir': str(W / 'state')})
(W / 'state').mkdir()
d = zigmon.Daemon()

# 1. an alert cut to its parts stays in its parts
plain = ('The boiler reported a fault code and stopped heating the house water; check the '
         'pressure gauge in the cellar and restart it from the panel by the door. ') * 3
for parts in (1, 2):
    cut = d._sms_cut(plain, parts)
    check(d.sms_parts(cut) <= parts,
          'a plain alert cut to %d part(s) is %d part(s): its ending "%s" turned it wide'
          % (parts, d.sms_parts(cut), cut[-3:]))
cut = d._sms_cut('Boiler \U0001f525 fault ' * 20, 1)
check(d.sms_parts(cut) <= 1, 'an alert with emoji cut to one part is %d parts' % d.sms_parts(cut))
cut = d._sms_cut('Kotel hlásí poruchu ' * 20, 1)
check(d.sms_parts(cut) <= 1, 'a Czech alert cut to one part is %d parts' % d.sms_parts(cut))

# 2. after an alert's send timed out, the next send is held off
zigmon.CONFIG.update({'sms_send_gap_s': 0})
d._sms_send_now = lambda number, text, why='alert', queue=True: (False, 'timed out')
d._sms_hold_until = 0
d.sms_send('+420777123456', 'x', why='alert')
check(d._sms_hold_until > time.time(),
      'an alert that timed out did not hold the next send off the wedged gateway')
d._sms_hold_until = 0
del d._sms_send_now

# 3. the agreed word never in the debug log of a push by GET
said = []
real_log = zigmon.log
zigmon.log = lambda msg, level='info': said.append(str(msg))
zigmon.CONFIG.update({'debug': True, 'sms_push': 1, 'sms_push_secret': 'Wordy-Secret-77'})


class FakeHeaders(dict):
    def items(self):
        return list(dict.items(self))


class Fake(object):
    command = 'GET'
    path = '/api/sms/incoming?secret=Wordy-Secret-77&number=%2B420777123456&text=hi'
    client_address = ('127.0.0.1', 1)
    headers = FakeHeaders({'Host': 'x'})

    def _error(self, code, words):
        return code

    def _send(self, code, obj):
        return code


d.sms_handle = lambda *a, **k: False
body = {'__came': {'from': '10.0.0.9', 'method': 'GET',
                   'uri': '/index.php?api=sms-incoming&secret=Wordy-Secret-77&number=1', 'headers': {}}}
q = {'secret': 'Wordy-Secret-77', 'number': '+420777123456', 'text': 'hi'}
zigmon.ApiHandler._sms_incoming(Fake(), d, body, q)
zigmon.log = real_log
leaked = [x for x in said if 'Wordy-Secret-77' in x]
check(not leaked, 'the push\'s agreed word went into the debug log in full: %s' % (leaked[:1],))
zigmon.CONFIG.update({'debug': False})
del d.sms_handle

# 4. testing the gateway with the webhook on does not read and act on the inbox
polled = []
d.sms_ready = lambda: True
d._sms_rest = lambda: True
d._sms_drop_token = lambda: None
d._sms_token = lambda: 'tok'
d.sms_modem_id = lambda: '1-1'
d.sms_modem_status = lambda: {}
d.sms_poll = lambda force=False: polled.append(force) or {'read': 0, 'acted': 0}
ok, words = d.sms_test()
check(ok and not polled, 'a test of the gateway with the webhook on read (and acted on) the modem\'s inbox')
del d.sms_poll

# 5. the Events log searched by a device's name
d.store.upsert_device({'id': '0x00124b0001', 'name': 'Kitchen-Sensor', 'source': 'zigbee',
                       'last_seen': int(time.time())})
d.store.add_event('device', 'went quiet for 2 h', 'warn', '0x00124b0001')
d.store.add_event('device', 'something else', 'info', '0x00999')
d.store.flush(5.0)
found = d.store.events(50, text='kitchen')
check(any(r.get('device') == '0x00124b0001' for r in found),
      'a search of the events for "kitchen" did not find the Kitchen-Sensor\'s own row')
check(d.store.events_count('kitchen') >= 1, 'the count of a search by a device\'s name was 0')

# 6. one phone, one text
zigmon.CONFIG.update({'sms_enabled': 1, 'sms_host': '127.0.0.1', 'notify_ntfy': '',
                      'notify_telegram_token': '', 'sms_quiet_from': '', 'sms_quiet_to': ''})
d.people = lambda: [{'id': 'p1', 'name': 'Alice', 'phone': '+420 777 123 456', 'sms_alerts': True}]
texts = []
d._sms_alert_add = lambda items: texts.extend(items)
threading.Thread(target=d.notify_loop, daemon=True).start()
d.notify_queue.append({'message': 'hello', 'level': 'warn', 'sms': True, 'ntfy': False, 'telegram': False,
                       'about_number': '', 'sms_to': 'Alice,+420777123456,777 123 456', 'title': None,
                       'image': None, 'queued': time.time()})
d._notify_kick.set()
deadline = time.time() + 5
while time.time() < deadline and not texts:
    time.sleep(0.05)
time.sleep(0.2)
check(len(texts) == 1, 'one phone named three ways was sent %d texts' % len(texts))

# 7. "sleep off" lets the held texts go as well
d.store.set_meta('sms_outbox', '[]')
d.system_action('sleep', 'on', 'a test')
d.sms_queue_add('+420777123456', 'held', 'quiet hours', send_after=time.time() + 8 * 3600)
d.system_action('sleep', 'off', 'a test')
held = [x for x in d.sms_outbox() if float(x.get('after') or 0) > time.time() + 1]
check(not held, '"sleep off" left %d held text(s) waiting for the morning' % len(held))
d.store.set_meta('sms_outbox', '[]')

# 8. USSD asks the box only while no text is being handed over
zigmon.CONFIG.update({'sms_sim': 'prepaid', 'sms_credit_code': '*101#'})
d.sim_prepaid = lambda: True
free = []


def gateway(path, method='GET', payload=None, retry=True, timeout=None):
    got = []

    def peek():
        # taken and given back by the same thread: an RLock is its owner's
        if d._sms_send_lock.acquire(blocking=False):
            d._sms_send_lock.release()
            got.append(True)
        else:
            got.append(False)
    t = threading.Thread(target=peek)
    t.start()
    t.join()
    free.append(bool(got and got[0]))
    return {'message': 'Credit 120 CZK'}


d._rest = gateway
d.modem_ussd()
check(free and not free[0], 'the USSD question went to the gateway without the lock the sending holds')
del d._rest

# 9. a person not ticked for commands is not texted their own words back
told = []
real_notify = d.notify
d.notify = lambda *a, **k: told.append(k)
d.people = lambda: [{'id': 'p1', 'name': 'Alice', 'phone': '+420777123456', 'sms_alerts': True,
                     'sms_commands': False}]
zigmon.CONFIG.update({'sms_stranger_alert': 'ntfy,sms', 'sms_reply': False, 'sms_allow': ''})
d.sms_handle('+420777123456', 'status')
mine = [k for k in told if k.get('about') == 'sms_in']
check(mine and mine[0].get('about_number'),
      'a text from somebody not ticked for commands was told without its number - texted back at them')
d.notify = real_notify

# 10. a message whose delete the box accepted and did not do is not acted on twice
zigmon.CONFIG.update({'sms_push': 0, 'sms_clear_inbox': True})
acted = []
d.sms_handle = lambda sender, text, key='', road='modem': acted.append(text) or True
d._sms_first_look = False
d._sms_seen.clear()


def inbox(path, method='GET', payload=None, retry=True, timeout=None):
    if path == '/messages/status':
        return [{'id': '3', 'sender': '+420777123456', 'message': 'heating toggle',
                 'date': '2026-11-06 07:01:02', 'status': 'read'}]
    return {}                                   # the delete: "yes" - and nothing happens


d._rest = inbox
d._sms_rest = lambda: True
d._sms_poll_now()
d._sms_poll_now()
check(len(acted) == 1, 'a message the modem did not really delete was acted on %d times' % len(acted))
del d._rest, d.sms_handle

# 11. the daily digest counts the whole day, not the newest thousand events
for i in range(1200):
    d.store.add_event('rule', 'rule "hall" fired', 'info')
d.store.flush(10.0)
told = []
d.notify = lambda text, *a, **k: told.append(text)
text = d.daily_digest(force=True) or ''
check('1200 rule(s) fired' in text, 'the daily digest counted the newest thousand events only: %r'
      % text.split('\n')[-1][:80])
d.notify = real_notify

# 12. the Events log can be narrowed to the messages' own kinds
import re                                               # noqa: E402
page = (HERE / 'web' / 'index.php').read_text(encoding='utf-8')
kinds = re.search(r"mk\('evf-kind', \[([^\]]*)\]", page)
listed = re.findall(r"'([a-z]+)'", kinds.group(1)) if kinds else []
for kind in ('sms', 'alert', 'notify'):
    check(kind in listed, 'the Events log\'s kind filter has no "%s", so texts and alerts could not be picked out'
          % kind)

# 13. the ntfy server's token is not in the status, and a save of what the page
#     was shown keeps it
import json                                             # noqa: E402
for url, secret in (('https://:tk_Abc123SecretToken@ntfy.example.org/house', 'tk_Abc123SecretToken'),
                    ('https://falco:Pa55word-x@ntfy.example.org/house', 'Pa55word-x')):
    zigmon.CONFIG['notify_ntfy'] = url
    shown = d.runtime_config()['notify_ntfy']['value']
    check(secret not in json.dumps(d.runtime_config()),
          'the status carried the ntfy server\'s credentials whole: %s' % shown)
    if hasattr(d, 'TUNABLE_URL_SECRETS'):
        d.save_config_overrides({'notify_ntfy': shown})
        check(zigmon.CONFIG['notify_ntfy'] == url,
              'saving the ntfy address as the page was shown it lost its credentials: %s'
              % zigmon.CONFIG['notify_ntfy'])
        where, auth = zigmon.ntfy_address(zigmon.CONFIG['notify_ntfy'])
        check(auth and where == 'https://ntfy.example.org/house', 'the kept address no longer logs in')
zigmon.CONFIG['notify_ntfy'] = ''

# 14. presence over a private ntfy logs in, and the log never carries its token
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer   # noqa: E402
heard = []


class Ntfy(BaseHTTPRequestHandler):
    def do_GET(self):
        heard.append((self.path, self.headers.get('Authorization') or ''))
        raw = b'{"event":"open"}\n'
        self.send_response(200)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(('127.0.0.1', 19521), Ntfy)
threading.Thread(target=srv.serve_forever, daemon=True).start()
said = []
zigmon.log = lambda msg, level='info': said.append(str(msg))
zigmon.CONFIG['presence_ntfy'] = 'http://:tk_PresenceTok99@127.0.0.1:19521/where'
d._stop.clear()
loop = threading.Thread(target=d.presence_ntfy_loop, daemon=True)
loop.start()
deadline = time.time() + 6
while time.time() < deadline and not heard:
    time.sleep(0.1)
d._stop.set()
loop.join(5)
zigmon.log = real_log
srv.shutdown()
srv.server_close()
zigmon.CONFIG['presence_ntfy'] = ''
check(heard and heard[0][1] == 'Bearer tk_PresenceTok99',
      'the presence listener never reached a private ntfy with its token (%s)' % (heard[:1],))
check(not [x for x in said if 'tk_PresenceTok99' in x],
      'the presence listener wrote the ntfy token into the log')

# 15. a long message waits as several before the next, as the setting says
zigmon.CONFIG.update({'sms_send_gap_s': 0.6})
d._sms_send_now = lambda number, text, why='alert', queue=True: (True, 'sent')
d._sms_hold_until = 0
d._sms_sent_at = 0
d.sms_send('+420777123456', 'x' * 300, why='alert')            # two parts
t0 = time.time()
d.sms_send('+420777123456', 'y', why='alert')
waited = time.time() - t0
check(waited >= 1.0, 'after a message of two parts the next waited %.2f s, one gap of 0.6 s - not two'
      % waited)
del d._sms_send_now
zigmon.CONFIG.update({'sms_send_gap_s': 0})

# 16. a login that timed out is not a send that timed out: the alert is kept
import socket                                           # noqa: E402
d.store.set_meta('sms_outbox', '[]')
zigmon.CONFIG.update({'sms_queue': True, 'sms_daily_cap': 0})


def slow_login():
    raise socket.timeout('timed out')


d._sms_tok = None
d._sms_token = slow_login
d._sms_hold_until = 0
d._sms_sent_at = 0
ok, words = d.sms_send('+420777123456', 'The boiler stopped', why='alert')
kept = d.sms_outbox()
check(not ok and len(kept) == 1, 'an alert whose login to the gateway timed out was not kept to try '
      'again (%s; %d kept)' % (words, len(kept)))
check(not kept or 'timed out' not in str(words).lower(),
      'a failed login is worded as a send that timed out, and the flush throws it away: %s' % words)
d.store.set_meta('sms_outbox', '[]')
del d._sms_token

# 17. the events saved as text say when they are only the newest of a search
save = re.search(r'function saveEventsAsText\(\) \{(.*?)\n\}', page, re.S)
check(save and 'EVENTS.matched' in save.group(1),
      'the events saved as text called the newest few hundred of a bigger search the whole of it')

shutil.rmtree(str(W), ignore_errors=True)
print('hunt5433_msg: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
os._exit(1 if bad else 0)
