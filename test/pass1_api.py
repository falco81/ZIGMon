#!/usr/bin/env python3
"""5.44, pass 1: the API, the command line and the daemon's background loops.
Each check fails on 5.43.4.

    python3 test/pass1_api.py

The loops, called as the daemon calls them on an object that stands in for
it (no daemon, no port):

  * the clock's quarter-second beat: a step that raises (the ways back of
    "on for ten minutes") skipped every step after it - the schedules and the
    rules waiting to act - on every beat while it kept raising, and wrote a
    line of the log four times a second;
  * the half-minute chores: the heating raising skipped the digest, the
    watchdogs and root's chores;
  * the gateways' loop and the Wi-Fi presence loop ended for good on one
    exception while reading their settings;
  * a text with no SMS gateway set up waited the five seconds between two
    sends before saying there is no gateway.

A daemon of its own on port 19454 (in-process, no broker):

  * wrong types answered 500 rather than 400: /api/groups, /api/order,
    /api/wifi/order, /api/rule/dryrun, the three uploads' part numbers, an
    address with a space for /api/managed/test;
  * /api/reset with a device that is not a string erased the history and
    then answered 500, with no event of it;
  * /api/rule/dryrun read as many days as it was asked for, under the
    database's lock: a month at most;
  * /api/sms/send with no gateway took five seconds a number;
  * `zigmon --switch SOCKET on` (the help's own example, and what --targets
    lists first) answered "unknown target" for every socket.
"""
import http.client
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PORT = 19454
W = Path(tempfile.mkdtemp(prefix='zigmon-pass1-api-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.CONFIG['log_file'] = str(W / 'unit.log')
zigmon.CONFIG['log_to_journal'] = False


class Stop(object):
    """A _stop that lets a loop go round `rounds` times."""

    def __init__(self, rounds):
        self.left = rounds

    def wait(self, _t=None):
        self.left -= 1
        return self.left < 0

    def is_set(self):
        self.left -= 1
        return self.left < 0


def fake(**kw):
    f = types.SimpleNamespace(**kw)
    for name in ('_beat_step', '_beat_said'):
        if hasattr(zigmon.Daemon, name):
            setattr(f, name, types.MethodType(getattr(zigmon.Daemon, name), f))
    return f


def boom(*_a, **_k):
    raise RuntimeError('a way back whose plug went away')


daemon = None
try:
    print('the clock: one step raising does not stop the others')
    ran = []
    f = fake(_stop=Stop(3), _lat={}, ping_broker=lambda: None, clock_watch=lambda: None,
             check_for_backs=boom, timers_keep=lambda: None,
             check_rule_windows=lambda: ran.append('windows'),
             _for_queued=True, _rule_queue=[], _rule_kick=threading.Event(),
             check_schedules=lambda: ran.append('schedules'),
             check_rule_waiting=lambda: ran.append('waiting'),
             _heat_at=time.time() + 3600, _chores_busy=True, sms_ready=lambda: False,
             _next_beat=lambda longest: 0.001)
    lines = []
    real_log = zigmon.log
    zigmon.log = lambda msg, level='info': lines.append((level, msg))
    try:
        zigmon.Daemon.timer_loop(f)
    finally:
        zigmon.log = real_log
    check('schedules' in ran and 'waiting' in ran,
          'a raising "way back" stopped the schedules and the waiting rules on every beat (ran: %s)' % ran)
    check(len([1 for lv, m in lines if 'way back' in m]) <= 1,
          'the same error of the beat was written %d times in three beats'
          % len([1 for lv, m in lines if 'way back' in m]))

    print('the half-minute chores: the heating raising does not stop the rest')
    ran = []
    zigmon.CONFIG['weather'] = False
    f = fake(heating_apply=boom, monthly_summary=lambda: ran.append('monthly'),
             daily_digest=lambda: ran.append('digest'), check_watchdogs=lambda: ran.append('watchdogs'),
             root_chores=lambda: ran.append('root'), check_system_alerts=lambda: None,
             _intel_fill_at=time.time(), _binding_at=time.time(), forget_old_waiting=lambda: None,
             store=types.SimpleNamespace(sweep_expired=lambda: False), _lists_busy=True,
             proxy_ready=lambda: False, mikrotik_ready=lambda: False, sim_prepaid=lambda: False,
             sms_ready=lambda: False, sms_outbox=lambda: [], _chores_busy=True)
    zigmon.log = lambda msg, level='info': None
    try:
        zigmon.Daemon._half_minute(f)
    finally:
        zigmon.log = real_log
    check({'digest', 'watchdogs', 'root'} <= set(ran),
          'the heating raising skipped the other half-minute chores (ran: %s)' % ran)
    check(f._chores_busy is False, 'the chores stayed marked busy')

    print('the gateways loop goes on after its list could not be read')
    polled = []
    calls = {'n': 0}

    def configs():
        calls['n'] += 1
        if calls['n'] == 1:
            raise RuntimeError('database is locked')
        return [{'name': 'g1'}]

    f = fake(_stop=Stop(2), gateway_configs=configs, poll_gateway=lambda g: polled.append(g['name']))
    zigmon.log = lambda msg, level='info': None
    try:
        zigmon.Daemon.gateway_loop(f)
        ended = None
    except Exception as e:                              # noqa: BLE001
        ended = e
    finally:
        zigmon.log = real_log
    check(ended is None and polled == ['g1'],
          'the gateways loop ended on one unreadable list (%s, polled %s)' % (ended, polled))

    print('the Wi-Fi presence loop goes on after its settings could not be read')
    calls = {'n': 0}

    def wifi_config():
        calls['n'] += 1
        if calls['n'] == 1:
            raise RuntimeError('database is locked')
        return {'enabled': False}

    class Kick(object):
        def wait(self, _t=None):
            return True

        def clear(self):
            pass

    f = fake(_stop=Stop(3), wifi_config=wifi_config, _wifi_kick=Kick(), wifi={},
             _mind_the_unfound=lambda: None, _presence_moved_at=0)
    zigmon.log = lambda msg, level='info': None
    try:
        zigmon.Daemon.wifi_loop(f)
        ended = None
    except Exception as e:                              # noqa: BLE001
        ended = e
    finally:
        zigmon.log = real_log
    check(ended is None and calls['n'] >= 2,
          'the Wi-Fi loop ended on one unreadable setting (%s; read %d times)' % (ended, calls['n']))

    print('the schedules after the clock is stepped forward')

    def schedules_after_step(wall_now_min, seen_min, rows):
        lt = time.localtime()
        now = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, wall_now_min // 60, wall_now_min % 60, 5, 0, 0, -1))
        fired = []
        f = fake(schedules=lambda: rows, store=types.SimpleNamespace(get_meta=lambda *a, **k: None,
                                                                     set_meta=lambda *a, **k: None,
                                                                     add_event=lambda *a, **k: None),
                 _binding_targets=lambda t: [t], target_label=lambda t: t, _trial_act=lambda *a, **k: False,
                 _fire_target=lambda target, do, *a, **k: fired.append((target, do)), schedule_runtime={},
                 WEEKDAY_NAMES=zigmon.Daemon.WEEKDAY_NAMES,
                 SCHED_CATCH_UP_MAX_MIN=zigmon.Daemon.SCHED_CATCH_UP_MAX_MIN,
                 _sched_seen=(now - 60, time.strftime('%Y-%m-%d', time.localtime(now)), seen_min))
        real_time = time.time
        time.time = lambda: now
        zigmon.log = lambda msg, level='info': None
        try:
            zigmon.Daemon.check_schedules(f)
        finally:
            time.time = real_time
            zigmon.log = real_log
        return fired

    every = list(range(7))
    rows = [{'id': 'a', 'target': 'Lamp', 'at': '08:00', 'do': 'off', 'days': every, 'enabled': True},
            {'id': 'b', 'target': 'Lamp', 'at': '07:00', 'do': 'on', 'days': every, 'enabled': True},
            {'id': 'c', 'target': 'Fan', 'at': '07:30', 'do': 'toggle', 'days': every, 'enabled': True}]
    # the clock said 06:59 a minute ago and says 10:00 now: stepped three hours
    fired = schedules_after_step(600, 419, rows)
    check(('Fan', 'toggle') not in fired and fired[-1:] != [('Lamp', 'on')],
          'a clock stepped forward three hours fired the schedules of those hours, in the order of '
          'the list: %s' % fired)
    # the night the clocks go forward: 01:59, and a minute later 03:00
    rows = [{'id': 'a', 'target': 'Lamp', 'at': '02:40', 'do': 'off', 'days': every, 'enabled': True},
            {'id': 'b', 'target': 'Lamp', 'at': '02:10', 'do': 'on', 'days': every, 'enabled': True}]
    fired = schedules_after_step(180, 119, rows)
    check(fired == [('Lamp', 'on'), ('Lamp', 'off')],
          'the hour the clocks skip: a 02:10 on and a 02:40 off fired as %s (the off is the last)' % fired)

    print('a nightly backup set for 23:58 is made')
    lt = time.localtime()
    clock = [time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 23, 51, 30, 0, 0, -1))]
    end = clock[0] + 2 * 86400
    made = []

    class ClockStop(object):
        def wait(self, t=None):
            clock[0] += float(t)
            return clock[0] > end

    meta = {}
    f = fake(_stop=ClockStop(), store=types.SimpleNamespace(get_meta=lambda k, d=None: meta.get(k, d),
                                                            set_meta=lambda k, v, **kw: meta.__setitem__(k, v),
                                                            add_event=lambda *a, **k: None),
             run_backup=lambda: made.append(time.strftime('%Y-%m-%d %H:%M', time.localtime(clock[0]))),
             root_installed=lambda: False, notify=lambda *a, **k: None)
    for name in ('backup_due', 'backup_nap'):
        if hasattr(zigmon.Daemon, name):
            setattr(f, name, types.MethodType(getattr(zigmon.Daemon, name), f))
    saved_cfg = {k: zigmon.CONFIG.get(k) for k in ('backup_enabled', 'backup_time', 'full_backup_nightly')}
    zigmon.CONFIG.update(backup_enabled=1, backup_time='23:58', full_backup_nightly=0)
    real_time = time.time
    time.time = lambda: clock[0]
    try:
        zigmon.Daemon.backup_loop(f)
    finally:
        time.time = real_time
        zigmon.CONFIG.update(saved_cfg)
    check(len(made) == 2 and all(m.endswith('23:58') for m in made),
          'a nightly backup at 23:58, followed over two days, was made at %s' % (made or 'no time at all'))

    print('a page\'s wait and a held press end on time when the clock is stepped back')
    real_time = time.time
    first = [None]

    def stepped_back():
        now = real_time()
        if first[0] is None:
            first[0] = now
            return now
        return now - 3600                  # an hour back, after the first look

    f = fake(seq=5, _change=threading.Condition(), _stop=threading.Event())
    done = []
    t = threading.Thread(target=lambda: done.append(zigmon.Daemon.wait_for_change(f, 5, 1.0)), daemon=True)
    time.time = stepped_back
    try:
        t.start()
        t.join(4)
    finally:
        time.time = real_time
    check(bool(done), "a page's wait of one second was still waiting after four once the clock "
                      "stepped back an hour")
    if not done:
        f._stop.set()
        t.join(3)
    first[0] = None
    entry = {'state': 'waiting', 'deadline': real_time() + 86400, 'message': 'waiting for you'}
    f = fake(_waiting={'tk': entry}, _waiting_cond=threading.Condition())
    done = []
    t = threading.Thread(target=lambda: done.append(zigmon.Daemon.tap_waiting(f, 'tk', 1)), daemon=True)
    time.time = stepped_back
    try:
        t.start()
        t.join(4)
    finally:
        time.time = real_time
    check(bool(done), 'a press held for one second was still held after four once the clock stepped back')
    if not done:
        with f._waiting_cond:
            entry['state'] = 'done'
            f._waiting_cond.notify_all()
        t.join(3)

    print('no SMS gateway: said at once')
    f = fake(_sms_send_lock=threading.Lock(), sms_ready=lambda: False, _sms_sent_at=time.time(),
             _sms_sent_parts=1, sms_parts=zigmon.Daemon.sms_parts)
    f._sms_send_now = types.MethodType(zigmon.Daemon._sms_send_now, f)
    t = time.time()
    ok, said = zigmon.Daemon.sms_send(f, '+420123456789', 'hello')
    took = time.time() - t
    check(not ok and took < 1, 'a text with no gateway took %.1f s to say so (%s)' % (took, said))

    # ---- a daemon of its own ---------------------------------------------
    print('a daemon on port %d' % PORT)
    cfg = W / 'config.json'
    cfg.write_text(json.dumps({
        'db_file': str(W / 'h.db'), 'api_port': PORT, 'api_host': '127.0.0.1', 'mqtt_host': '',
        'log_file': str(W / 'zigmon.log'), 'log_to_journal': False, 'backup_dir': str(W / 'backups'),
        'token_file': str(W / 'api-token'), 'state_dir': str(W / 'state'), 'weather': False,
        'plugs': [{'name': 'Lamp', 'host': '127.0.0.1:19455'}]}))
    env = dict(os.environ, ZIGMON_CONFIG=str(cfg), PYTHONPATH=str(HERE), HOME=str(W),
               ZIGMON_CONSOLE_FLAG=str(W / 'console-flag'))
    starter = W / 'start.py'
    starter.write_text('import sys, time\nsys.path.insert(0, %r)\nsys.argv = ["zigmon"]\nimport zigmon\n'
                       'zigmon.load_config()\nd = zigmon.Daemon()\nzigmon.ApiServer(d).start()\n'
                       'while True:\n    time.sleep(1)\n' % str(HERE))
    out = open(str(W / 'start.log'), 'w')
    daemon = subprocess.Popen([sys.executable, str(starter)], env=env, stdout=out,
                              stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    up = False
    for _ in range(120):
        time.sleep(0.5)
        try:
            c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=3)
            c.request('GET', '/api/health')
            c.getresponse().read()
            up = True
            break
        except OSError:
            if daemon.poll() is not None:
                break
    if not check(up, 'the daemon did not come up: %s' % (W / 'start.log').read_text()[-600:]):
        raise SystemExit(1)
    H = {'X-Zigmon-Token': (W / 'api-token').read_text().strip(),
         'X-Zigmon-Cli': (W / 'cli-key').read_text().strip(), 'Content-Type': 'application/json'}

    def post(path, body=None, raw=None):
        c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=30)
        c.request('POST', path, body=raw if raw is not None else json.dumps(body or {}), headers=H)
        r = c.getresponse()
        got = r.read()
        try:
            return r.status, json.loads(got)
        except ValueError:
            return r.status, {'raw': got[:200]}

    print('wrong types are a 400, not a 500')
    for path, body, raw in (
            ('/api/groups', {'editor': 'rules', 'groups': 5}, None),
            ('/api/order', {'plugs': 5}, None),
            ('/api/order', {'groups': {'a': 5}}, None),
            ('/api/wifi/order', {'order': 5}, None),
            ('/api/rule/dryrun', {'rule': 5}, None),
            ('/api/db/backup/upload', {'name': 'x', 'part': [1], 'of': 1, 'upload_id': 'abc', 'data': ''}, None),
            ('/api/db/backup/upload', {'name': 'x', 'part': 1, 'of': 1, 'upload_id': 'abc', 'data': True}, None),
            ('/api/fullbackup/upload', None, '{"part": Infinity, "of": 1, "upload_id": "abc", "data": ""}'),
            ('/api/upgrade/upload', {'part': {}, 'of': 1, 'upload_id': 'abc', 'data': ''}, None),
            ('/api/managed/test', {'host': '192.168.1.5 x'}, None)):
        status, got = post(path, body, raw)
        check(status == 400, '%s %s answered %d %s (a 400 is what the page shows)'
              % (path, raw or json.dumps(body), status, got.get('error')))

    print('erasing with a device that is not a name')
    status, got = post('/api/reset', {'scope': 'history', 'device': 5})
    check(status == 200, '/api/reset {"scope": "history", "device": 5} answered %d %s after erasing the history'
          % (status, got.get('error')))

    print('a dry run reads a month at most')
    status, got = post('/api/rule/dryrun', {'rule': {'device': 'plug:Lamp', 'key': 'apower', 'op': '>',
                                                     'value': 5, 'plug': 'Lamp', 'do': 'on'},
                                            'days': 100000})
    check(status == 200 and got.get('days') is not None and got['days'] <= 31,
          'a dry run was asked for 100000 days and read %s (%d %s)' % (got.get('days'), status, got.get('error')))

    print('a text with no gateway')
    t = time.time()
    status, got = post('/api/sms/send', {'to': ['+420123456789', '+420987654321'], 'text': 'x'})
    took = time.time() - t
    check(took < 3, '/api/sms/send with no gateway took %.1f s for two numbers' % took)
    check(status == 200 and got.get('ok') is False, 'the answer was %d %s' % (status, got))

    print('zigmon --switch SOCKET on')
    r = subprocess.run([sys.executable, str(HERE / 'zigmon.py'), '--switch', 'Lamp', 'on', '--no-color'],
                       env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    said = r.stdout + r.stderr
    check('unknown target' not in said and 'Lamp' in said,
          '`zigmon --switch Lamp on` with a socket called Lamp said: %s' % said.strip()[:200])
    print('zigmon --sms with a word it does not know')
    r = subprocess.run([sys.executable, str(HERE / 'zigmon.py'), '--sms', 'sned', '--no-color'],
                       env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    check(r.returncode == 2 and 'sned' in r.stderr,
          '`zigmon --sms sned` answered %d with %r' % (r.returncode, (r.stdout + r.stderr).strip()[:120]))
    status, got = post('/api/target/set', {'target': 'lamp', 'do': 'bogus'})
    check(status == 400, 'a socket asked to do "bogus" answered %d %s' % (status, got))

    print('two settings saved at once are both kept')
    (W / 'in').mkdir()
    zigmon.CONFIG.update(db_file=str(W / 'in' / 'h.db'), token_file=str(W / 'in' / 'api-token'),
                         state_dir=str(W / 'in' / 'state'), mqtt_host='', backup_dir=str(W / 'in' / 'b'),
                         api_port=PORT + 1, weather=False, plugs=[], sensors=[])
    me = zigmon.Daemon()
    real_set = me.store.set_meta

    def slow_set(key, value, *a, **k):
        if key == 'config_overrides':
            time.sleep(0.2)                 # the read, the change and the write, slowly
        return real_set(key, value, *a, **k)

    me.store.set_meta = slow_set
    zigmon.log = lambda msg, level='info': None
    try:
        both = [threading.Thread(target=me.save_config_overrides, args=({'block_minutes': 77},)),
                threading.Thread(target=me.save_config_overrides, args=({'sms_poll_s': 33},))]
        for t in both:
            t.start()
            time.sleep(0.05)
        for t in both:
            t.join(10)
    finally:
        zigmon.log = real_log
        me.store.set_meta = real_set
    kept = me.config_overrides()
    check(kept.get('block_minutes') == 77 and kept.get('sms_poll_s') == 33,
          'two settings saved at the same moment: only %s was kept' % kept)
    me._stop.set()

    log = (W / 'zigmon.log').read_text(errors='replace') if (W / 'zigmon.log').exists() else ''
    check(' error api ' not in log, 'the daemon wrote errors of the API: %s'
          % [l for l in log.splitlines() if ' error api ' in l][:3])
finally:
    if daemon is not None:
        daemon.send_signal(signal.SIGTERM)
        try:
            daemon.wait(timeout=10)
        except subprocess.TimeoutExpired:
            daemon.kill()
            daemon.wait()
    shutil.rmtree(str(W), ignore_errors=True)

if bad:
    print('%d check(s) failed' % len(bad))
    sys.exit(1)
print('all well')
