#!/usr/bin/env python3
"""5.44, pass 2: staying up and coming back - the house keeps switching
whatever else fails. Each check fails on 5.44.0.

    python3 test/pass2_robust.py

  * the database refusing writes (a full disk, a file another program
    holds): /api/health still answers, at once, and says so - it raised on
    a full disk and waited 15 s and then raised on a held file;
  * every queued write failing is said once and then once a minute with a
    count, not a line of the log for each - and the health answer, the
    machine's own alerts and the page carry it until a write lands again,
    which is said too;
  * the main loop of run() outlives what it calls: a full disk ended the
    daemon half a minute after every start;
  * one box answering a byte at a time does not hold the readings of the
    others: the round waited a minute for each box;
  * one rule that raises does not stop the rules after it for that report;
  * root's helper killed in the middle of a request: the next run says it
    failed and lets the next request in, instead of the daemon waiting half
    an hour for it; one that is still working is left to it;
  * an upgrade whose helper went away is not "running" for half an hour;
  * install.sh puts the program files in whole (beside, on the disk, then
    renamed over) - a power cut after `install` left zigmon.py empty.

Fault injection is deterministic: the store's connection is wrapped to
raise "database or disk is full", or held by a second connection with
BEGIN EXCLUSIVE; the slow box is an HTTP server on a port of its own
(19340-19342); run() itself listens on 19343.
"""
import fcntl
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-pass2-robust-'))
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


# ---- the boxes: A answers a byte at a time, B and L at once ----------------------
SEEN = {'A': 0, 'B': 0, 'L': 0, 'sets': []}


def box(name, trickle):
    class Box(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
            method, params = body.get('method'), body.get('params') or {}
            if method == 'Switch.Set':
                SEEN['sets'].append((name, time.time(), bool(params.get('on'))))
                out = {'was_on': False}
            elif method in ('Shelly.GetStatus', 'Switch.GetStatus'):
                SEEN[name] += 1
                out = {'switch:0': {'id': 0, 'output': False, 'apower': 1.0, 'aenergy': {'total': 1.0}}}
            elif method == 'Shelly.GetDeviceInfo':
                out = {'id': 'shelly-' + name, 'model': 'S3PL-00112EU', 'gen': 3, 'ver': '1.7.1'}
            else:
                out = {}
            raw = json.dumps({'id': body.get('id'), 'result': out}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            if not trickle or method == 'Switch.Set':
                self.wfile.write(raw)
                return
            for ch in raw:                     # each byte inside the timeout, the whole far past it
                try:
                    self.wfile.write(bytes([ch]))
                    self.wfile.flush()
                except OSError:
                    return
                time.sleep(trickle)
    return Box


for _name, _port, _tr in (('A', 19340, 0.5), ('B', 19341, 0), ('L', 19342, 0)):
    _srv = ThreadingHTTPServer(('127.0.0.1', _port), box(_name, _tr))
    _srv.daemon_threads = True
    threading.Thread(target=_srv.serve_forever, daemon=True).start()

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'zigmon.db'), 'api_port': 19343, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'log_file': str(W / 'zigmon.log'), 'plugs': [],
                      'sensors': [], 'mqtt_host': '', 'weather': False, 'state_dir': str(W),
                      'backup_dir': str(W / 'backups')})
LINES = []
_log = zigmon.log


def caught(msg, level='info', *a, **k):
    LINES.append((level, str(msg)))
    return _log(msg, level, *a, **k)


zigmon.log = caught
d = zigmon.Daemon()
s = d.store
REAL = s.db


class Full(object):
    """The store's connection on a full disk: every write refused."""

    def __getattr__(self, k):
        return getattr(REAL, k)

    def execute(self, sql, *a):
        if sql.lstrip().split()[0].upper() in ('INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'COMMIT'):
            raise sqlite3.OperationalError('database or disk is full')
        return REAL.execute(sql, *a)

    def executemany(self, sql, *a):
        raise sqlite3.OperationalError('database or disk is full')


def health():
    s._latency_cache = (0.0, None)
    t0 = time.time()
    try:
        got = d.health()
    except Exception as e:                              # noqa: BLE001
        got = e
    return got, time.time() - t0


try:
    d.store.set_meta('managed', json.dumps({'plugs': [
        {'name': 'L', 'host': '127.0.0.1:19342', 'switch_id': 0, 'kind': 'plug', 'host_state': 'enabled'}],
        'sensors': []}))
    d.reload_devices()
    s.flush()

    # -- the health answer while the database refuses writes --------------------------
    print('the health answer on a full disk, and with the file held by another program')
    s.db = Full()
    got, took = health()
    check(isinstance(got, dict) and 'full' in str((got.get('db') or {}).get('write_error')),
          'on a full disk /api/health said %r, not that the database refuses writes' % (got,))
    s.db = REAL
    held = sqlite3.connect(str(W / 'zigmon.db'), isolation_level=None)
    held.execute('BEGIN EXCLUSIVE')
    try:
        got, took = health()
        # the store's lock busy for 50 ms with something else (a loaded machine:
        # the whole suite at once) gives the last figures, here none - by design;
        # asked again until the probe ran, each answer still timed on its own
        for _ in range(20):
            if not isinstance(got, dict) or (got.get('db') or {}).get('read_ms') is not None or \
                    (got.get('db') or {}).get('write_error'):
                break
            time.sleep(0.1)
            got, took = health()
    finally:
        held.execute('ROLLBACK')
        held.close()
    check(isinstance(got, dict) and took < 3,
          'with the file held by another program /api/health took %.1f s and said %r' % (took, got))
    check(isinstance(got, dict) and 'locked' in str((got.get('db') or {}).get('write_error')),
          'with the file held, the health answer did not say so: %r' % (got,))

    # -- every queued write failing ---------------------------------------------------
    print('three hundred queued writes refused')
    LINES[:] = []
    s.db = Full()
    for i in range(300):
        s.store_sample('0xfull', int(time.time()) + i, {'temperature': float(i)})
    s.flush()
    errors = [m for lv, m in LINES if lv == 'error']
    check(len(errors) <= 2, 'every refused write was a line of the log: %d lines' % len(errors))
    trouble = getattr(s, 'write_trouble', None)
    check(bool(trouble) and trouble.get('lost') == 300 and 'full' in trouble.get('error', ''),
          'the store does not know its writes are refused: %r' % (trouble,))
    got, _took = health()
    check(isinstance(got, dict) and ((got.get('db') or {}).get('writes_failing') or {}).get('lost') == 300,
          'the health answer does not carry the refused writes: %r' % ((got.get('db') if isinstance(got, dict)
                                                                         else got),))
    said = [w for k, w in d.host_trouble() if k == 'database']
    check(bool(said) and '300 lost' in said[0], "the machine's own alerts do not say it: %r" % (said,))
    page = (HERE / 'web' / 'index.php').read_text()
    check('writes_failing' in page, 'the page does not show the refused writes')
    s.db = REAL
    LINES[:] = []
    s.store_sample('0xfull', int(time.time()) + 999, {'temperature': 1.0})
    s.flush()
    check(getattr(s, 'write_trouble', 'missing') is None, 'a write that landed did not end the trouble')
    check(any('takes writes again' in m for _lv, m in LINES), 'the database taking writes again was not said')

    # -- run() on a full disk -----------------------------------------------------------
    print('the main loop on a full disk')

    class Quick(threading.Event):
        def wait(self, timeout=None):
            return super(Quick, self).wait(min(timeout if timeout is not None else 0.05, 0.05))

    class NoBroker(object):
        def __getattr__(self, k):
            return lambda *a, **kw: None

    d._stop = Quick()
    d.connect = lambda: setattr(d, 'client', NoBroker())
    d.last_aggregate_at = 0.0
    zigmon.CONFIG['aggregate_interval'] = 1
    turns = []
    _elc = zigmon.ensure_log_current

    def counting():
        turns.append(1)
        if len(turns) == 2:
            raise OSError('the log file went away')     # anything at all, once
        return _elc()
    zigmon.ensure_log_current = counting
    s.db = Full()
    ended = []
    runner = threading.Thread(target=lambda: ended.append(d.run()), name='run', daemon=True)
    runner.start()
    for _ in range(100):
        if len(turns) >= 6 or not runner.is_alive():
            break
        time.sleep(0.05)
    alive = runner.is_alive()
    d._stop.set()
    runner.join(15)
    s.db = REAL
    zigmon.ensure_log_current = _elc
    zigmon.CONFIG.pop('aggregate_interval', None)
    check(alive and len(turns) >= 6,
          'the main loop ended on a full disk after %d turn(s) - the daemon with it' % len(turns))
    d._stop = threading.Event()

    # -- one slow box, and the others ---------------------------------------------------
    print('a box answering a byte at a time, beside one that answers')
    d.store.set_meta('managed', json.dumps({'plugs': [
        {'name': 'A', 'host': '127.0.0.1:19340', 'switch_id': 0, 'kind': 'plug', 'host_state': 'enabled'},
        {'name': 'B', 'host': '127.0.0.1:19341', 'switch_id': 0, 'kind': 'plug', 'host_state': 'enabled'}],
        'sensors': []}))
    d.reload_devices()
    zigmon.CONFIG['plug_poll_interval'] = 2
    SEEN['A'] = SEEN['B'] = 0
    poller = threading.Thread(target=d.plug_loop, name='plugs', daemon=True)
    poller.start()
    time.sleep(13)
    b_polls, a_polls = SEEN['B'], SEEN['A']
    stuck = sum(1 for t in threading.enumerate() if t.name == 'poll-A')
    d._stop.set()
    poller.join(10)
    d._stop = threading.Event()
    zigmon.CONFIG.pop('plug_poll_interval', None)
    check(b_polls >= 4, 'with one box answering slowly the other was read %d time(s) in 13 s, every 2 s asked'
          % b_polls)
    check(a_polls == 1 and stuck <= 1, 'the slow box was asked again while still answering: %d asks, %d threads'
          % (a_polls, stuck))

    # -- one rule that raises -----------------------------------------------------------
    print('a rule that raises, before one that does not')
    d.store.set_meta('managed', json.dumps({'plugs': [
        {'name': 'L', 'host': '127.0.0.1:19342', 'switch_id': 0, 'kind': 'plug', 'host_state': 'enabled'}],
        'sensors': []}))
    d.reload_devices()
    d.store.upsert_device({'id': 'zigbee:PIR', 'name': 'PIR', 'source': 'zigbee', 'kind': 'sensor',
                           'exposes': {'occupancy': {}}})
    d.names['PIR'] = 'zigbee:PIR'
    d.store.set_meta('rules', json.dumps([
        {'id': 'odd', 'device': 'zigbee:PIR', 'key': 'occupancy', 'op': '==', 'value': 'yes', 'plug': 'L',
         'do': 'on', 'enabled': True},
        {'id': 'good', 'device': 'zigbee:PIR', 'key': 'occupancy', 'op': '==', 'value': 1, 'plug': 'L',
         'do': 'on', 'enabled': True, 'cooldown_s': 0}]))
    d.rule_runtime.clear()
    SEEN['sets'][:] = []
    try:
        d.fire_rules('zigbee:PIR', 'PIR', {'occupancy': 0})
        d.fire_rules('zigbee:PIR', 'PIR', {'occupancy': 1})
        raised = None
    except Exception as e:                              # noqa: BLE001
        raised = e
    for _ in range(100):
        if SEEN['sets']:
            break
        time.sleep(0.02)
    check(raised is None and SEEN['sets'] and SEEN['sets'][0][0] == 'L',
          'a rule that raised (%r) stopped the motion rule after it: the light was told %r'
          % (raised, SEEN['sets']))

    print('a schedule that does not read, before one that does')
    lt = time.localtime()
    d.store.set_meta('schedules', json.dumps([
        {'id': 'odd', 'at': 'half past', 'days': list(range(7)), 'target': 'L', 'do': 'on', 'enabled': True},
        {'id': 'good', 'at': '%02d:%02d' % (lt.tm_hour, lt.tm_min), 'days': list(range(7)), 'target': 'L',
         'do': 'on', 'enabled': True}]))
    fired = []
    _fire = d._fire_target
    d._fire_target = lambda *a, **k: fired.append(a[:2])
    d.__dict__.pop('_sched_minute', None)
    d.schedule_runtime.clear()
    try:
        d.check_schedules()
        raised = None
    except Exception as e:                              # noqa: BLE001
        raised = e
    finally:
        d._fire_target = _fire
    check(raised is None and len(fired) == 1,
          'a schedule that did not read (%r) stopped the one after it: %r' % (raised, fired))

    # -- root's helper killed in the middle ----------------------------------------------
    print("root's helper killed in the middle of a request")
    spec = importlib.util.spec_from_file_location('zigmon_root_p2', str(HERE / 'deploy' / 'zigmon_root.py'))
    zr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(zr)
    state = W / 'rootstate'
    (state / 'root').mkdir(parents=True)
    zr.STATE_DIR = str(state)
    zr.FD.clear()
    taken = state / 'root' / 'request.taken'
    taken.write_text(json.dumps({'id': 'abc123', 'kind': 'apply', 'hash': 'ab' * 32}))
    (state / 'root' / 'progress.json').write_text(json.dumps({'id': 'abc123', 'words': 'half way'}))
    os.utime(str(taken), (time.time() - 600, time.time() - 600))     # taken ten minutes ago
    left = getattr(zr, 'taken_left', None)
    check(left is not None, "root's helper never looks for a request a run took and did not finish")
    if left is not None:
        working = os.open(str(taken), os.O_RDONLY)
        fcntl.flock(working, fcntl.LOCK_EX)        # a run that is still on it
        try:
            check(left(zr.root_fd()) is False and taken.exists(),
                  "a request a run is still working on was taken away from it")
        finally:
            os.close(working)
        check(left(zr.root_fd()) is True and not taken.exists()
              and not (state / 'root' / 'progress.json').exists(),
              'a request no run holds was left behind')
        st = json.loads((state / 'root' / 'status.json').read_text())
        check(st.get('state') == 'failed' and st.get('id') == 'abc123' and st.get('failed_hash') == 'ab' * 32
              and 'stopped before' in ' '.join(st.get('said') or []),
              'the request left behind is not said as failed: %r' % (st,))
    src = (HERE / 'deploy' / 'zigmon_root.py').read_text()
    serve = src[src.index('\ndef serve():'):src.index('\ndef passphrase_from(')]
    check('taken_left(d)' in serve and 'fcntl.flock(held' in serve,
          "a run of root's helper does not hold the request it works on, or never looks for one left")

    # -- an upgrade whose helper went away ------------------------------------------------
    print('an upgrade whose helper went away')
    (W / 'upgrade').mkdir(exist_ok=True)
    gone = subprocess.Popen([sys.executable, '-c', 'pass'])
    gone.wait()
    (W / 'upgrade' / 'status.json').write_text(json.dumps({'id': 'u1', 'state': 'running', 'step': 'installing',
                                                           'version': '9.9.9', 'pid': gone.pid,
                                                           'at': time.time()}))
    st = d.upgrade_status()
    check(st.get('state') == 'failed' and 'stopped half way' in str(st.get('said')),
          'an upgrade whose helper is gone is still %r' % (st.get('state'),))
    (W / 'upgrade' / 'status.json').write_text(json.dumps({'id': 'u1', 'state': 'running', 'step': 'installing',
                                                           'version': '9.9.9', 'pid': os.getpid(),
                                                           'at': time.time()}))
    check(d.upgrade_status().get('state') == 'running', 'an upgrade whose helper is there was called ended')

    # -- install.sh: whole files ----------------------------------------------------------
    print('install.sh puts the program in whole')
    sh = (HERE / 'install.sh').read_text()
    check('put_whole 755 "$SOURCE_DIR/zigmon.py" "$LIB_DIR/zigmon.py"' in sh
          and 'run install -m 755 "$SOURCE_DIR/zigmon.py"' not in sh,
          'install.sh writes zigmon.py in place')
    if 'put_whole() {' in sh:
        fn = sh[sh.index('put_whole() {'):]
        fn = fn[:fn.index('\n}\n') + 3]
        (W / 'src').write_text('new program\n')
        (W / 'dst').write_text('old program\n')
        got = subprocess.run(['bash', '-c', 'set -euo pipefail; DRY_RUN=; note() { :; }\n' + fn +
                              'put_whole 755 "$1" "$2"', '-', str(W / 'src'), str(W / 'dst')],
                             capture_output=True, text=True)
        check(got.returncode == 0 and (W / 'dst').read_text() == 'new program\n'
              and not (W / 'dst.zigmon-new').exists() and os.stat(str(W / 'dst')).st_mode & 0o777 == 0o755,
              'put_whole did not put the file in whole: %r %r' % (got.returncode, got.stderr))
finally:
    try:
        s.db = REAL
        d._stop.set()
        s.flush(5)
    except Exception:                                   # noqa: BLE001
        pass
    shutil.rmtree(str(W), ignore_errors=True)

print('pass2_robust: %s' % ('%d failed' % len(bad) if bad else 'all good'))
os._exit(1 if bad else 0)
