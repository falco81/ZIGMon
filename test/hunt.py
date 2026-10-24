#!/usr/bin/env python3
"""The bugs, the holes and the delays found in 5.16.0 by going over the whole
of it again, one at a time. 5.17.0: every check here fails on 5.16.0.

    PYTHONPATH=. python3 test/hunt.py

A fake Shelly on a port of its own and the daemon's API on another; no broker,
no web server (test/edge.py puts nginx and php-fpm in front). Run in Prague
time, because two of these are about the nights the clocks change there.
"""
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ['TZ'] = 'Europe/Prague'
time.tzset()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

BOX = {'output': False, 'sets': [], 'first_set_delay': 0.0, 'status': 200}


class Box(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        method, params = body.get('method'), body.get('params') or {}
        if BOX['status'] != 200 and method != 'Switch.Set':
            self.send_response(BOX['status'])
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'{}')
            return
        if method == 'Switch.Set':
            if BOX['first_set_delay']:
                late, BOX['first_set_delay'] = BOX['first_set_delay'], 0.0
                time.sleep(late)                  # this packet went round the Wi-Fi twice
            was, BOX['output'] = BOX['output'], bool(params.get('on'))
            BOX['sets'].append((time.time(), bool(params.get('on'))))
            out = {'was_on': was}
        elif method in ('Shelly.GetStatus', 'Switch.GetStatus'):
            sw = {'id': 0, 'output': BOX['output'], 'apower': 12.0, 'voltage': 231.0,
                  'aenergy': {'total': 1.0}}
            out = sw if method == 'Switch.GetStatus' else {'switch:0': sw, 'mqtt': {'connected': True},
                                                          'sys': {'uptime': 10}}
        elif method == 'Shelly.GetDeviceInfo':
            out = {'id': 'shellyplug-test', 'model': 'S3PL-00112EU', 'gen': 3, 'ver': '1.7.1'}
        else:
            out = {}
        raw = json.dumps({'id': body.get('id'), 'result': out}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


server = ThreadingHTTPServer(('127.0.0.1', 19971), Box)
threading.Thread(target=server.serve_forever, daemon=True).start()

zigmon.load_config()
DB = '/tmp/zigmon-hunt-check.db'
for _ext in ('', '-wal', '-shm'):
    try:
        os.remove(DB + _ext)
    except OSError:
        pass
zigmon.CONFIG.update({'db_file': DB, 'api_port': 19972, 'token_file': '/tmp/zigmon-hunt-token',
                      'pin': '1234', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': ''})
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
threading.Thread(target=d.rule_worker, name='rules', daemon=True).start()
threading.Thread(target=d.rule_worker, args=(True,), name='rules-presence', daemon=True).start()
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def check(ok, what):
    if not ok:
        raise AssertionError(what)


def plug(**extra):
    entry = dict({'name': 'Light-Test', 'host': '127.0.0.1:19971', 'switch_id': 0, 'kind': 'plug',
                  'host_state': 'enabled'}, **extra)
    d.store.set_meta('managed', json.dumps({'plugs': [entry], 'sensors': []}))
    d.reload_devices()
    getattr(zigmon.ShellyRPC, '_crowded', {}).clear()     # nothing left over from a block before
    p = d.plugs['Light-Test']
    d.poll_plug(p, force=True)
    return p


def call(path, body=None, session=None):
    # as the web relay asks: it always says whose browser it is relaying for
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json',
               'X-Zigmon-Client': '192.0.2.50'}
    if session:
        headers['X-Zigmon-Session'] = session
    req = urllib.request.Request('http://127.0.0.1:19972' + path, headers=headers,
                                 data=None if body is None else json.dumps(body).encode(),
                                 method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, {}


class FakeClock(object):
    """time.time() standing still where it is put, for the nights the clocks
    change; everything else keeps the real one."""
    def __init__(self, at):
        self.at, self.real = at, time.time

    def __enter__(self):
        time.time = lambda: self.at
        return self

    def __exit__(self, *a):
        time.time = self.real


# -- phone numbers are not in the status, and nothing is lost for it ----------
# The status is answered without the PIN - with public_view on, which is the
# default, it is the page anybody on the house's network may open - and it
# carried every phone number in the house: each person's, the numbers alerts
# go to, the numbers allowed to command the house by text, and the numbers a
# message is sent to. The last three digits are enough to tell two apart.
d.save_people([{'id': 'p1', 'name': 'Jan', 'phone': '+420777123456', 'phone_report': True,
                'token': 'abcdefghijklmnopqrst', 'sms_alerts': True}])
zigmon.CONFIG.update({'sms_to': '+420606111222', 'sms_allow': '+420606333444'})
d.save_alert_messages([{'id': 'm1', 'name': 'Water', 'text': 'Water under the sink',
                        'sms_to': ['+420608555666', 'Jan']}])
d.sms_queue_add('+420609777888', 'held for the morning', 'alert', send_after=time.time() + 3600)
_raw = json.dumps(d.status())
for _n in ('777123456', '606111222', '606333444', '608555666', '609777888'):
    check(_n not in _raw, 'the status, answered without the PIN, carries the phone number ...%s' % _n[-3:])
_code, _objects = call('/api/objects')
for _n in ('777123456', '609777888'):
    check(_code == 200 and _n not in json.dumps(_objects),
          'the list of objects, answered without the PIN, carries the phone number ...%s' % _n[-3:])
d.sms_outbox_drop()
check('456' in json.dumps(d.status()['people']), 'the people in the status do not even say how their number ends')
# ...the page sends back what it was shown, and nothing it did not touch moves
_shown = d.status()
d.save_people(_shown['people'])
_after = d.people()[0]
check(_after['phone'] == '+420777123456', 'saving the people as shown changed a phone number to %r'
      % _after['phone'])
# A token the page never holds came back blank on every save, and blank with
# phone reports on was taken as "make me one": the phone's own link stopped
# working at every save of the people or the SMS tab, without a word.
check(_after['token'] == 'abcdefghijklmnopqrst', 'saving the people gave the phone a new token, and its '
      'own link stopped working')
_cfg = _shown['runtime_config']
d.save_config_overrides({'sms_to': _cfg['sms_to']['value'] + ', +420606999888',
                         'sms_allow': _cfg['sms_allow']['value']})
check(zigmon.CONFIG['sms_to'].replace(' ', '') == '+420606111222,+420606999888',
      'a number added beside a hidden one was saved as %r' % zigmon.CONFIG['sms_to'])
check(zigmon.CONFIG['sms_allow'] == '+420606333444', 'the numbers allowed to command were saved as %r'
      % zigmon.CONFIG['sms_allow'])
d.save_alert_messages(_shown['messages'])
check(d.alert_messages()[0]['sms_to'] == ['+420608555666', 'Jan'],
      'a message saved as shown is now sent to %r' % d.alert_messages()[0]['sms_to'])
# ...and an unlocked page reads the real ones, behind the PIN only
_code, _ = call('/api/people')
check(_code == 403, 'the people with their real numbers were answered without the PIN (%s)' % _code)
# (signed in as an administrator since 5.19; it was the PIN)
if 'tester' not in d.accounts:
    d.account_add('tester', 'admin', 'tester pass 12', must_change=False, quiet=True)
_code, _unlocked = call('/api/auth/login', {'name': 'tester', 'password': 'tester pass 12'})
_session = _unlocked.get('token') or ''
_code, _full = call('/api/people', session=_session)
check(_code == 200 and (_full.get('people') or [{}])[0].get('phone') == '+420777123456',
      'an unlocked page cannot read the numbers it is to edit (%s)' % _code)
check(all(not x.get('token') for x in _full.get('people') or []), 'the people road hands out the phone tokens')
print('no phone number in the status; the page saves what it was shown without losing one')

# -- a second factor asked for is asked for on the address road too ----------
# With both roads open, the address road went straight past the code and Duo:
# a link whose secret had leaked did what it does on a house that had switched
# the code on precisely so that a leaked secret would not be enough.
d.store.set_meta('taps', json.dumps([{'id': 'tp1', 'name': 'Hall', 'token': 'TapTokenForHunt-0001', 'target': 'Light-Test',
                                      'do': 'toggle', 'enabled': True}]))
zigmon.CONFIG.update({'tap_mode': 'both', 'tap_code': 1})
plug()
BOX['sets'] = []
_ok, _answer = d.tap('TapTokenForHunt-0001', who='198.51.100.9', way='link')
time.sleep(0.3)
check(not _ok and not BOX['sets'], 'a link opened by its address switched the light with the second factor on')
_ok, _answer = d.tap('TapTokenForHunt-0001', who='198.51.100.9', way='link', ask=True)
check(_ok, 'asking how a link stands by its address was refused as well: %r' % (_answer,))
zigmon.CONFIG.update({'tap_mode': 'link', 'tap_code': 0})
print('the address road of a link cannot act past a second factor')

# -- a pressed link answers as soon as its light has moved -------------------
# It waited a fixed 350 ms before saying how things stand, every press.
d.store.set_meta('taps', json.dumps([{'id': 'tp2', 'name': 'Hall', 'token': 'TapTokenForHunt-0002', 'target': 'Light-Test',
                                      'do': 'on', 'enabled': True}]))
_times = []
for _i in range(3):
    BOX['output'] = False
    plug()
    _t0 = time.perf_counter()
    _ok, _answer = d.tap('TapTokenForHunt-0002', who='198.51.100.9', way='link')
    _times.append((time.perf_counter() - _t0) * 1000)
    check(_ok and BOX['output'], 'the link did not switch the light on: %r' % (_answer,))
check(max(_times) < 200, 'a press of a link took %.0f ms to answer' % max(_times))
print('a press of a link answers in %.0f ms' % max(_times))

# -- the proxy's log cannot hold the reader up --------------------------------
# A request line nobody closed - one long word and no quote after it - took the
# reader 17.7 s per line, and anybody can write such a line into the log.
_line = '203.0.113.5 - - [21/Oct/2026:10:00:00 +0200] "GET ' + 'A' * 100000 + ' HTTP'
_t0 = time.perf_counter()
d.PROXY_LINE.match(_line)
_took = (time.perf_counter() - _t0) * 1000
check(_took < 200, 'one line of the proxy log held its reader %.0f ms' % _took)
_ok = d.PROXY_LINE.match('203.0.113.5 - - [21/Oct/2026:10:00:00 +0200] "GET /wp-login.php HTTP/1.1" 404 153 '
                         '"-" "curl/8"')
check(_ok and _ok.group('path') == '/wp-login.php', 'an ordinary line of the proxy log is not read any more')
print('a request line nobody closed is read in %.1f ms' % _took)

# -- a password is compared in constant time ----------------------------------
# (the PIN of before 5.19 is gone; the passwords are PBKDF2 hashes compared
# with hmac.compare_digest, and a name nobody has costs as long as one there is)
import inspect                                           # noqa: E402
check('compare_digest' in inspect.getsource(zigmon.password_ok), 'a password is compared with ==, which says how '
      'much of it was right by how long it takes')
check('DUMMY_PW_HASH' in inspect.getsource(d.login), 'a name nobody has is answered at once, which says which '
      'names there are')
print('a password is compared in constant time, and so is a name nobody has')

# -- a text from another country is not the owner -----------------------------
# Compared on the last nine digits alone, +421 777 123 456 - another phone, in
# another country, and a sender anybody can claim - had the run of the house.
for _a, _b, _same in (('+421777123456', '+420777123456', False),
                      ('00421777123456', '+420777123456', False),
                      ('777123456', '+420777123456', True),
                      ('+420 777 123 456', '00420777123456', True),
                      ('456', '+420777123456', False),
                      ('23456', '+420777123456', False)):
    check(bool(d._same_number(_a, _b)) == _same, '%s and %s were %s as one number'
          % (_a, _b, 'not taken' if _same else 'taken'))
print('numbers that both say their country are compared whole')

# -- a rule for an empty house fires again the next time it is empty ---------
# The owner walked in before the phone was seen: the rule fired, and its edge
# stayed "true" while the house was not empty - so the next day's intruder, in
# an empty house, was never reported.
_fired = []
_was = d._fire_target
d._fire_target = lambda target, do, origin, *a, **k: _fired.append((do, origin))
d.store.upsert_device({'id': 'zigbee:PIR', 'name': 'PIR', 'source': 'zigbee', 'kind': 'sensor',
                       'exposes': {'occupancy': {}}})
d.names['PIR'] = 'zigbee:PIR'
d.save_rules([{'device': 'zigbee:PIR', 'key': 'occupancy', 'op': '==', 'value': 1, 'plug': 'notify',
               'do': 'on', 'when': 'away', 'cooldown_s': 0}])   # the next day, in effect
_home = {'v': False}
_was_presence, _was_wifi = d.presence_state, d.wifi_config
d.presence_state = lambda: {'known': True, 'anyone_home': _home['v'], 'people': []}
d.wifi_config = lambda: {'enabled': False}
try:
    d.fire_rules('zigbee:PIR', 'PIR', {'occupancy': 1}, gated=True)
    _home['v'] = True
    d.fire_rules('zigbee:PIR', 'PIR', {'occupancy': 0}, gated=True)
    _home['v'] = False
    d.fire_rules('zigbee:PIR', 'PIR', {'occupancy': 1}, gated=True)
finally:
    d.presence_state, d.wifi_config, d._fire_target = _was_presence, _was_wifi, _was
check(len(_fired) == 2, 'motion in an empty house the second time fired the rule %d time(s) in all, '
      'not 2' % len(_fired))
d.save_rules([])
print('a rule for an empty house fires each time the house is empty and something moves')

# -- "on for a while" is one light, one way back ------------------------------
# Every trip started a thread of its own that slept out the span and switched
# the light off: pressed again two seconds in, the light went off at three
# seconds anyway - from the first press - and a contact bouncing open and
# closed left a thread a bounce.
_ran = []
_was = d._run_binding
d._run_binding = lambda p, do, origin, pulse_ms=None, stagger=0.0: _ran.append((time.time(), do))
_stop_beat = threading.Event()


def _beat():
    # the clock's own duty, without the rest of timer_loop
    while not _stop_beat.wait(0.02):
        d.check_for_backs()


threading.Thread(target=_beat, daemon=True).start()
try:
    _p = plug()
    _t0 = time.time()
    d._fire_target(('plug', _p), 'for:2s', 'rule: PIR (motion)')
    time.sleep(1.0)
    d._fire_target(('plug', _p), 'for:2s', 'rule: PIR (motion again)')
    time.sleep(3.0)
    _offs = [t - _t0 for t, do in _ran if do == 'off']
    check(len(_offs) == 1 and _offs[0] >= 2.8, 'pressed again a second in, "on for 2 s" went off at %s s'
          % [round(x, 1) for x in _offs])
    _base = threading.active_count()
    for _i in range(500):
        d._fire_target(('plug', _p), 'for:10m', 'rule: Door (bouncing)')
    time.sleep(0.5)
    check(threading.active_count() - _base < 20, 'a contact bouncing 500 times left %d threads asleep'
          % (threading.active_count() - _base))
    with d._for_lock if hasattr(d, '_for_lock') else threading.Lock():
        getattr(d, '_for_backs', {}).clear()
finally:
    _stop_beat.set()
    d._run_binding = _was
print('"on for a while" pressed again starts its time again, and keeps no thread per press')

# -- "for N s" counts only from inside the rule's hours -----------------------
# A rule for the night, "no motion for ten minutes, then off", counted the quiet
# from the small hours of the night before: the moment its window opened at
# 22:00 the light went off, with somebody in the room.
_fired = []
_was = d._fire_target
d._fire_target = lambda target, do, origin, *a, **k: _fired.append(time.strftime('%H:%M', time.localtime(time.time())))
d.store.set_meta('rules', json.dumps([{'id': 'r-night', 'enabled': True, 'device': 'zigbee:PIR',
                                       'key': 'occupancy', 'op': '==', 'value': 0, 'plug': 'Light-Test',
                                       'do': 'off', 'for_s': 600, 'from': '22:00', 'to': '06:00'}]))
d.rule_runtime.pop('r-night', None)


def _at(h, m):
    return time.mktime((2026, 10, 21 if h >= 5 else 22, h, m, 0, 0, 0, -1))


try:
    with FakeClock(_at(5, 55)) as _clock:
        d.check_rule_windows()
        d.fire_rules('zigbee:PIR', 'PIR', {'occupancy': 0}, gated=False)
        d.check_rule_for()
        _clock.at = _at(6, 0)
        d.check_rule_windows()
        d.check_rule_for()
        _clock.at = _at(6, 5)
        d.fire_rules('zigbee:PIR', 'PIR', {'occupancy': 1}, gated=False)
        _clock.at = _at(21, 59)
        d.fire_rules('zigbee:PIR', 'PIR', {'occupancy': 1}, gated=False)
        _clock.at = _at(22, 0)
        d.check_rule_windows()
        d.check_rule_for()
        _clock.at = _at(22, 1)
        d.fire_rules('zigbee:PIR', 'PIR', {'occupancy': 0}, gated=False)
        for _m in range(2, 13):
            _clock.at = _at(22, _m)
            d.check_rule_for()
finally:
    d._fire_target = _was
check(_fired == ['22:11'], 'a night rule "no motion for ten minutes" fired at %s, not at 22:11' % _fired)
d.store.set_meta('rules', json.dumps([]))
print('"no motion for ten minutes" counts from inside the rule\'s hours')

# -- a block reaches the door at once -----------------------------------------
# A reading of the list that started before a block and finished after it wrote
# its own stamp over the block's "read me again", and the door then trusted the
# list from before the block for its whole minute.
_s = d.store
with _s.lock:
    _s.db.executemany('INSERT INTO blocked (ip, since, until, why, hits, auto, by) VALUES (?,?,?,?,1,1,?)',
                      [('10.%d.%d.0/24' % (i // 250, i % 250), time.time(), None, 'feed', '')
                       for i in range(27000)])
    _s.db.commit()
_s.blocked_until('192.0.2.1')
_late = []
for _trial in range(5):
    _s.block('198.51.100.%d' % (_trial + 10), why='scanner')
    _s.blocked_until('192.0.2.2', wait=False)         # a request at the door: a reading starts behind it
    time.sleep(0.005)
    _ip = '203.0.113.%d' % (_trial + 10)
    _s.block(_ip, why='brute force')
    _t0 = time.time()
    while _s.blocked_until(_ip, wait=False) is None and time.time() - _t0 < 5:
        time.sleep(0.05)
    _late.append(time.time() - _t0)
check(max(_late) < 3, 'an address just blocked was let in at the door for %.0f s' % max(_late))
print('an address just blocked is kept out at the door within %.1f s' % max(_late))

# -- quiet hours keep their length on the night the clocks go back -----------
# On 25 October an alert held for the morning was let out at 06:00, an hour into
# the quiet, because the end was worked out as so many seconds from midnight.
zigmon.CONFIG.update({'sms_quiet_from': '22:00', 'sms_quiet_to': '07:00'})
for _y, _mo, _dd, _hh in ((2026, 10, 24, 23), (2026, 10, 25, 1), (2026, 10, 25, 5)):
    _t = time.mktime((_y, _mo, _dd, _hh, 30, 0, 0, 0, -1))
    _ends = d._sms_quiet_now(_t)
    _lt = time.localtime(_ends) if _ends else None
    check(_lt is not None and (_lt.tm_hour, _lt.tm_min) == (7, 0),
          'an alert at %s was held until %s, not 07:00' % (time.strftime('%m-%d %H:%M', time.localtime(_t)),
                                                          time.strftime('%H:%M', _lt) if _lt else 'never'))
zigmon.CONFIG.update({'sms_quiet_from': '', 'sms_quiet_to': ''})
print('quiet hours end at 07:00 on the night the clocks go back')

# -- a schedule in the hour the clocks skip still happens ---------------------
# On the last Sunday of March 02:00 becomes 03:00; a schedule at 02:30 found no
# such minute and did not happen that day at all.
_fired = []
_was = d._fire_target
d._fire_target = lambda target, do, origin, *a, **k: _fired.append((origin, time.time()))
d.store.set_meta('schedules', json.dumps([
    {'id': 's1', 'at': '02:30', 'days': list(range(7)), 'target': 'Light-Test', 'do': 'on', 'enabled': True},
    {'id': 's2', 'at': '02:58', 'days': list(range(7)), 'target': 'Light-Test', 'do': 'off', 'enabled': True}]))
try:
    for _label, _start in (('March', time.mktime((2027, 3, 28, 0, 0, 0, 0, 0, 0))),
                           ('October', time.mktime((2026, 10, 25, 0, 0, 0, 0, 0, 1)))):
        _fired = []
        d.__dict__.pop('_sched_seen', None)
        with FakeClock(_start) as _clock:
            while _clock.at < _start + 5 * 3600:
                d.check_schedules()
                _clock.at += 15
        check(len(_fired) == 2, 'on the %s night the clocks change, the 02:30 and 02:58 schedules ran %d '
              'time(s) between them, not twice' % (_label, len(_fired)))
finally:
    d._fire_target = _was
    d.store.set_meta('schedules', json.dumps([]))
print('a schedule in the hour the clocks skip runs as the clock jumps, and once in the hour that repeats')

# -- two alerts at once are not a crash ---------------------------------------
_errors = []
_hush, _set, _ch = d.alerts_hushed, d.alert_setting, d.notify_settings
d.alerts_hushed = lambda: False
d.alert_setting = lambda about: {}
d.notify_settings = lambda: {'channels': {}}
_real_notify = zigmon.Daemon.notify.__get__(d)


def _flood(tag):
    for _i in range(6000):
        try:
            _real_notify('x', dedup='%s-%d' % (tag, _i), about='blocked')
        except Exception as e:
            _errors.append(repr(e))
            return


_ts = [threading.Thread(target=_flood, args=(t,)) for t in ('a', 'b', 'c', 'd')]
[t.start() for t in _ts]
[t.join() for t in _ts]
d.alerts_hushed, d.alert_setting, d.notify_settings = _hush, _set, _ch
check(not _errors, 'alerts raised from several threads at once broke the notifier: %s' % _errors[:1])
print('alerts from several threads at once keep their bookkeeping')

# -- "too many requests" is the answer 429, not the number 429 anywhere ------
# Any "429" in the text of an error was taken as "busy": a box called
# Pokoj-429, or on port 4290, carried it in every error it had - and was never
# shown as gone, however long it was.
_p = plug()
_p.failures = 0
BOX['status'] = 429
try:
    for _i in range(4):
        _p.backoff_until = 0
        zigmon.ShellyRPC._crowded.clear()
        d.poll_plug(_p, force=True)
finally:
    BOX['status'] = 200
check(_p.failures == 0, 'a box answering 429 to its readings counted %d failure(s)' % _p.failures)
_p = plug(host='127.0.0.1:19429', name='Light-Test')     # nothing listens there: the box is gone
for _i in range(4):
    _p.backoff_until = 0
    d.poll_plug(_p, force=True)
check(_p.failures >= 3, 'a box gone from a port with 429 in it counted %d failure(s) in four readings'
      % _p.failures)
plug()
print('a box answering 429 to a reading is busy, not failing; a box on port 19429 that is gone is gone')

# -- a restore puts the restored rules in force -------------------------------
# A rule worker that read the rules in the moment between the restore emptying
# what is held in memory and the restore taking the lock put the OLD rules back
# in memory, where they stayed in force until the next save.
_s.set_meta('hunt_rules', json.dumps([{'id': 'NEW'}]))   # read as the rules are, acted on by nothing
_s.flush()
_bk = '/tmp/zigmon-hunt-restore.db'
_dst = sqlite3.connect(_bk)
with _s.lock:
    _s.db.backup(_dst)
_dst.close()
_stop_read = threading.Event()


def _reader():
    while not _stop_read.is_set():
        _s.meta_json('hunt_rules')
        time.sleep(0.005)


threading.Thread(target=_reader, daemon=True).start()
_bad = 0
for _i in range(60):
    _s.set_meta('hunt_rules', json.dumps([{'id': 'OLD'}]))
    _s.restore_from(_bk)
    time.sleep(0.03)
    if [r.get('id') for r in _s.meta_json('hunt_rules')] != ['NEW']:
        _bad += 1
_stop_read.set()
_s.set_meta('hunt_rules', json.dumps([]))
check(_bad == 0, '%d of 60 restores left the rules from before them in force' % _bad)
print('a restore puts the restored rules in force, with the rules being read all the while')

# -- a device paired a moment ago is heard the first time it speaks ----------
# The list of devices is taken in behind the broker's thread now (5.16); a
# report from a device that list has just brought was dropped as unknown.
_seen = []
_was_record = d.record
d.record = lambda dev, name, payload: (_seen.append(name), _was_record(dev, name, payload))[1]


def _devlist(extra=None):
    out = [{'ieee_address': '0x%016x' % i, 'friendly_name': 'Dev-%d' % i, 'type': 'EndDevice',
            'definition': {'model': 'M', 'vendor': 'V', 'description': 'x',
                           'exposes': [{'type': 'binary', 'property': 'occupancy', 'name': 'occupancy'}]}}
           for i in range(1, 80)]
    return out + ([extra] if extra else [])


try:
    d.handle_zigbee('bridge/devices', json.dumps(_devlist()).encode())
    d.devices_settled(10)
    _new = {'ieee_address': '0x00000000deadbeef', 'friendly_name': 'PIR-New', 'type': 'EndDevice',
            'definition': {'model': 'RTCGQ11LM', 'vendor': 'Aqara', 'description': 'PIR',
                           'exposes': [{'type': 'binary', 'property': 'occupancy', 'name': 'occupancy'}]}}
    d.handle_zigbee('bridge/devices', json.dumps(_devlist(_new)).encode())
    d.handle_zigbee('PIR-New', json.dumps({'occupancy': True}).encode())
    d.devices_settled(10)
    time.sleep(0.2)
finally:
    d.record = _was_record
check('PIR-New' in _seen, 'the first report of a device paired a moment ago was dropped')
print('the first report of a device just paired is heard')

# -- a light switched twice in a row ends as it was last asked ----------------
# On and straight away off: the "on" packet went round the Wi-Fi twice, the
# "off" overtook it, and the light stayed on - with the house sure it was off.
_wrong = []
for _trial in range(3):
    _p = plug()
    BOX['output'] = False
    BOX['sets'] = []
    BOX['first_set_delay'] = 0.08
    d._fire_target(('plug', _p), 'on', 'button A (single)')
    time.sleep(0.01)
    d._fire_target(('plug', _p), 'off', 'button B (single)')
    time.sleep(1.0)
    if BOX['output'] or _p.output:
        _wrong.append((BOX['output'], _p.output, [s[1] for s in BOX['sets']]))
check(not _wrong, 'on and straight away off left the light (box, house) %s' % _wrong)
print('on and straight away off ends off, at the box and in the house\'s mind')

# -- a rule's "wait five seconds" ends at five seconds ------------------------
# The clock beat every quarter second and a wait ended on the next beat: up to
# 250 ms late, and on average 125. The beat wakes for it now.
_ran = []
_was = d._fire_target
d._fire_target = lambda target, do, origin, *a, **k: _ran.append(time.time())
d.store.set_meta('rules', json.dumps([{'id': 'r-wait', 'enabled': True, 'device': 'zigbee:PIR',
                                       'key': 'occupancy', 'op': '==', 'value': 0, 'plug': 'Light-Test',
                                       'do': 'toggle', 'after_s': 1, 'cooldown_s': 0}]))
_clock_thread = threading.Thread(target=d.timer_loop, name='timers', daemon=True)
_clock_thread.start()
_lateness = []
try:
    for _trial in range(4):
        d.rule_runtime.pop('r-wait', None)
        _ran.clear()
        d.fire_rules('zigbee:PIR', 'PIR', {'occupancy': 1}, gated=False)
        time.sleep(0.05 + 0.06 * _trial)
        d.fire_rules('zigbee:PIR', 'PIR', {'occupancy': 0}, gated=False)
        _due = (d.rule_waiting.get('r-wait') or {}).get('due')
        time.sleep(1.5)
        if _due and _ran:
            _lateness.append((_ran[0] - _due) * 1000)
finally:
    d._fire_target = _was
    d.store.set_meta('rules', json.dumps([]))
check(len(_lateness) == 4 and max(_lateness) < 60, 'a rule\'s "wait 1 s" acted late by %s ms'
      % [round(x) for x in _lateness])
print('a rule\'s wait ends on time (%.0f ms late at most)' % max(_lateness))

# -- a light held by "on for a while" is let go when the while is over ------
# A press that holds its light against the rules ("hold") with "on for 2 s"
# kept the hold for its full four hours after the light had gone off: every
# motion rule for that light was refused all evening.
_p = plug()
BOX['output'] = False
d.store.upsert_device({'id': 'zigbee:Btn', 'name': 'Btn', 'source': 'zigbee', 'kind': 'button',
                       'exposes': {'action': {}}})
d.names['Btn'] = 'zigbee:Btn'
d.store.set_meta('bindings', json.dumps([{'device': 'zigbee:Btn', 'action': 'single', 'plug': 'Light-Test',
                                          'do': 'for:1s', 'hold': True, 'enabled': True}]))
d.fire_bindings('zigbee:Btn', 'Btn', 'single')
time.sleep(0.6)
check(BOX['output'] and d.target_held('Light-Test'), 'the press did not switch the light on and hold it')
time.sleep(1.5)
check(not BOX['output'], 'the light was still on after "on for 1 s"')
check(not d.target_held('Light-Test'), 'the light was still held after "on for 1 s" was over: %r'
      % (d.target_held('Light-Test'),))
BOX['sets'] = []
d._fire_target(('plug', _p), 'on', 'rule: PIR occupancy 1', honour_hold=True)
time.sleep(0.5)
check(BOX['sets'] and BOX['output'], 'a motion rule could not switch the light on after "on for 1 s" was over')
d.store.set_meta('bindings', json.dumps([]))
print('a light held by "on for a while" is let go when the while is over')

# -- each day of the energy chart is a day, across the change of the clocks --
# The days were counted back from midnight in steps of 86,400 s; across the
# night the clocks change a day is 23 or 25 hours long, and every day before
# it was labelled with the wrong date for a month.
with FakeClock(time.mktime((2026, 4, 10, 12, 0, 0, 0, 0, -1))):
    _code, _days = call('/api/energy/daily?plug=*', session=_session)
_wrong = [(x.get('day'), time.strftime('%m-%d %H:%M', time.localtime(x.get('ts') or 0)))
          for x in (_days.get('days') or [])
          if time.localtime(x.get('ts') or 0)[3:5] != (0, 0)
          or time.strftime('%m-%d', time.localtime(x.get('ts') or 0)) != x.get('day')]
check(_code == 200 and len(_days.get('days') or []) == 30 and not _wrong,
      'the energy chart\'s days across the change of the clocks: %s %r' % (_code, _wrong[:3]))
print('the energy chart\'s thirty days each start at their own midnight, across the change of the clocks')

# -- the page is woken a moment after each socket of a scene, not after all --
# A strip of four answers one command at a time, 200 ms apart, and every answer
# put the owed wake off again: the first lamp was on the page a second after
# it lit.
_woken = []
_t0 = time.time()
_seq0 = d.seq


def _watch():
    seen = _seq0
    while time.time() - _t0 < 2.0:
        now_seq = d.wait_for_change(seen, 0.5)
        if now_seq > seen:                     # woken, not a wait that ran out
            _woken.append(time.time() - _t0)
        seen = now_seq


threading.Thread(target=_watch, daemon=True).start()
time.sleep(0.05)
_t0 = time.time()
d.wake_together(2.0)
d.bump()                                       # the scene dispatched
for _i in range(4):
    time.sleep(0.2)
    d.bump()                                   # a socket answered
time.sleep(1.2)
_after_first_socket = [w for w in _woken if w > 0.19]
check(_after_first_socket and _after_first_socket[0] < 0.5,
      'the first socket of a scene answered at 0.2 s and the page heard of it at %s s'
      % (round(_after_first_socket[0], 2) if _after_first_socket else 'never'))
print('the page hears of a scene\'s first socket %.2f s after the press' % _after_first_socket[0])

d.store.flush(5.0)
zigmon.log_drain(3.0) if hasattr(zigmon, 'log_drain') else None
print('all checks passed')
sys.stdout.flush()
os._exit(0)
