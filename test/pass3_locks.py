#!/usr/bin/env python3
"""5.46.1, pass 3: the store's one lock, and the long jobs that held it. Each
check fails on 5.46.0.

    python3 test/pass3_locks.py          # about a minute

The work done under the lock is counted in SQLite's own steps (a progress
handler, as pass1_storage), not timed, wherever that can say it; where the
thing found is a wait, the wait is timed, with room for a busy machine.

  * the searches (events, the blocked story, the presses, the full proxy
    logs) read every row with LIKE: on a reader of their own now, and do not
    wait for - or hold - the lock;
  * the proxy logs' retention: the cap of the kept requests found from the
    ids (it walked 200 000 entries of the index under the lock after every
    reading of the log), what goes over or out of date goes in pieces;
  * a long job cut into short turns of the lock still starved everybody
    else - the thread letting go took it straight back: the hourly fold, a
    retention, now breathe between turns;
  * the fold of a series never folded before is done a few thousand
    readings at a time, not a fortnight in one turn;
  * the hourly tidy-up of what is kept about addresses asks the index per
    address instead of reading every address of the whole story;
  * a device's rows (a group of sensors taken away, a device's own shorter
    retention, Erase one device, the stale ones) go in pieces;
  * the dry run of "prune" reads on a reader of its own, and the repeats it
    drops are dropped in pieces;
  * reset() ran its VACUUM on the shared connection without the lock;
  * the story of one address is read by the address, not by a text search
    (which also put 11.2.3.45's lines under 1.2.3.4);
  * a router that is slow piled up one waiting sync per change.

And, measured rather than mended: with the lock held for 1.5 s, a reading
recorded, the rules' state and the status the page asks for do not wait.

Ports 19700, 19701 (configured, never opened).
"""
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-pass3-locks-'))
sys.path.insert(0, os.environ.get('PASS3_DAEMON') or str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'zigmon.db'), 'api_port': 19700, 'token_file': str(W / 'token'),
                      'plugs': [{'name': 'Lamp', 'host': '127.0.0.1:19701'}],
                      'sensors': [], 'weather': False, 'state_dir': str(W), 'retain_full_days': 14})
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


d = zigmon.Daemon()
s = d.store
s.flush()
NOW = int(time.time())
REAL_LOCK = s.lock


class Counted(object):
    """The store's lock, counting SQLite's steps (1000 VM instructions
    each) taken while it is held - the most of any one hold."""

    def __init__(self, real):
        self.real, self.depth, self.ticks, self.most = real, 0, 0, 0
        self.owner = None

    def _in(self):
        self.depth += 1
        if self.depth == 1:
            self.ticks = 0
            self.owner = threading.get_ident()

    def _out(self):
        self.depth -= 1
        if self.depth == 0:
            self.most = max(self.most, self.ticks)
            self.owner = None

    def acquire(self, *a, **k):
        got = self.real.acquire(*a, **k)
        if got:
            self._in()
        return got

    def release(self):
        self._out()
        self.real.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *a):
        self.release()


def tick():
    lock = s.lock
    if isinstance(lock, Counted) and lock.owner is not None:
        lock.ticks += 1
    return 0


def most_steps(fn, *a, **k):
    """(result, the most steps any one hold of the lock took)."""
    s.flush()
    s.lock = Counted(REAL_LOCK)
    s.db.set_progress_handler(tick, 1000)
    try:
        out = fn(*a, **k)
        s.flush()
    finally:
        s.db.set_progress_handler(None, 0)
        most = s.lock.most
        s.lock = REAL_LOCK
    return out, most


def put(sql, rows):
    with s.lock:
        s.db.execute('BEGIN')
        s.db.executemany(sql, rows)
        s.db.execute('COMMIT')


def count(sql, args=()):
    with s.lock:
        return s.db.execute(sql, args).fetchone()[0]


def traced(fn, *a, **k):
    said = []
    s.db.set_trace_callback(said.append)
    try:
        out = fn(*a, **k)
    finally:
        s.db.set_trace_callback(None)
    return out, said


holding = threading.Event()


def held_for(seconds, call):
    """call() while another thread holds the lock: (result, seconds it took)."""
    holding.clear()

    def hold():
        with REAL_LOCK:
            holding.set()
            time.sleep(seconds)
    th = threading.Thread(target=hold)
    th.start()
    holding.wait(5)
    t0 = time.time()
    try:
        out = call()
    finally:
        took = time.time() - t0
        th.join()
    return out, took


def worst_wait(job, *a):
    """Run job(*a) while another thread takes the lock every 2 ms:
    (the longest that thread waited, how long the job took)."""
    waits, stop = [], threading.Event()

    def other():
        while not stop.is_set():
            t0 = time.perf_counter()
            with REAL_LOCK:
                pass
            waits.append(time.perf_counter() - t0)
            time.sleep(0.002)
    th = threading.Thread(target=other)
    th.start()
    t0 = time.perf_counter()
    try:
        job(*a)
    finally:
        took = time.perf_counter() - t0
        stop.set()
        th.join()
    return max(waits or [0.0]), took


try:
    # -- the searches -----------------------------------------------------------
    print('the searches read on a reader of their own')
    put('INSERT INTO events (ts, device, kind, level, detail) VALUES (?,?,?,?,?)',
        ((NOW - i, '0xev%d' % (i % 9), 'state', 'info', 'went to %d' % i) for i in range(30000)))
    put('INSERT INTO events (ts, device, kind, level, detail) VALUES (?,?,?,?,?)',
        [(NOW, '0xev1', 'state', 'info', 'the needle in it')])
    put('INSERT INTO block_events (ts, ip, what, why, auto, by) VALUES (?,?,?,?,?,?)',
        ((NOW - i, '10.9.%d.%d' % (i % 250, i % 200), 'blocked', 'scanning', 1, '') for i in range(30000)))
    put('INSERT INTO block_events (ts, ip, what, why, auto, by) VALUES (?,?,?,?,?,?)',
        [(NOW, '1.2.3.4', 'blocked', 'the needle', 1, ''), (NOW - 1, '11.2.3.45', 'blocked', 'the other one', 1, ''),
         (NOW - 2, '1.2.3.4/32', 'blocked', 'as a subnet', 1, '')])
    put('INSERT INTO taps_log (ts, link, what, who, way, factor, state, message) VALUES (?,?,?,?,?,?,?,?)',
        ((NOW - i, 'l%d' % (i % 9), 'press', 'someone', 'web', 'pin', 'done', 'ok') for i in range(20000)))
    put('INSERT INTO taps_log (ts, link, what, who, way, factor, state, message) VALUES (?,?,?,?,?,?,?,?)',
        [(NOW, 'lx', 'press', 'the needle', 'web', 'pin', 'done', 'ok')])
    body = 'b' * 200
    put('INSERT INTO proxy_requests (ts, h, which, ip, method, uri, status, host, ua, fields, body, kinds) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        ((NOW - 30000 + i, 'h%d' % i, 'tap', '10.1.0.%d' % (i % 200), 'GET', '/x/%d' % i, 200, 'h.example',
          'agent', '{}', body if i != 777 else 'the needle', '') for i in range(30000)))
    searches = (('events(text)', lambda: s.events(50, text='needle'),
                 lambda r: [x['detail'] for x in r] == ['the needle in it']),
                ('events_count(text)', lambda: s.events_count(text='needle'), lambda r: r == 1),
                ('block_events(text)', lambda: s.block_events(50, text='needle'),
                 lambda r: [x['why'] for x in r[0]] == ['the needle'] and r[1] == 1 and r[2] == 30003),
                ('tap_log(text)', lambda: s.tap_log(50, text='needle'),
                 lambda r: [x['who'] for x in r[0]] == ['the needle'] and r[1] == 1),
                ('proxy_requests_list(q)', lambda: s.proxy_requests_list(q='needle'),
                 lambda r: [x['uri'] for x in r[0]] == ['/x/777'] and r[2] == 30000))
    for name, call, right in searches:
        got, took = held_for(1.5, call)
        check(took < 1.0, 'the search %s waited %.1f s for the lock' % (name, took))
        check(right(got), 'the search %s found %r' % (name, got))
        _, steps = most_steps(call)
        check(steps < 5, 'the search %s read under the lock: %d steps' % (name, steps))
    # the same answers through the lock where no reader can be opened
    real_reader = s._reader
    s._reader = lambda timeout=15: None
    try:
        for name, call, right in searches:
            check(right(call()), 'without a reader, %s found something else' % name)
    finally:
        s._reader = real_reader

    # -- the story of one address -------------------------------------------------
    print('the story of one address, by the address')
    if check(hasattr(s, 'block_events_of'), 'the story of one address is only ever a text search'):
        story = s.block_events_of(['1.2.3.4'], 50, prefix='1.2.3.4')
        check(sorted(x['why'] for x in story) == ['as a subnet', 'the needle'],
              'the story of 1.2.3.4: %r' % [x['why'] for x in story])
        _, steps = most_steps(s.block_events_of, ['1.2.3.4'], 50, '1.2.3.4')
        check(steps < 5, 'the story of one address read the whole story: %d steps' % steps)
    s.block('1.2.3.4', why='kept out')
    s.block('11.2.3.45', why='kept out too')
    s.flush()
    d.mikrotik_entries = lambda remember=True: []
    picture = d.router_picture()
    mine = [x for x in picture['not_carried'] if x['address'] == '1.2.3.4']
    whys = [h['why'] for h in (mine[0]['story'] if mine else [])]
    check(mine and 'the other one' not in whys and 'kept out too' not in whys and 'kept out' in whys,
          "the router's page put 11.2.3.45's story under 1.2.3.4: %r" % whys)
    del d.mikrotik_entries
    s.unblock('1.2.3.4')
    s.unblock('11.2.3.45')
    s.flush()

    # -- the proxy logs' retention ------------------------------------------------
    print("the proxy logs' retention: the cap from the ids, the rest in pieces")
    s.PROXY_REQUESTS_MOST = 30000
    gone, steps = most_steps(s.proxy_requests_forget, 0)
    check(gone == 0, 'with exactly as many as may be kept, %d went' % gone)
    check(steps < 3, 'the cap was found by walking the kept requests under the lock: %d steps' % steps)
    s.PROXY_REQUESTS_MOST = 12000
    (gone, steps), said = traced(most_steps, s.proxy_requests_forget, 0)
    left = count('SELECT COUNT(*) FROM proxy_requests')
    newest = count('SELECT MAX(id) FROM proxy_requests')
    oldest = count('SELECT MIN(id) FROM proxy_requests')
    check(gone == 18000 and left == 12000 and newest - oldest + 1 == 12000,
          'the cap took %d and left %d (%r..%r)' % (gone, left, oldest, newest))
    deletes = [x for x in said if x.startswith('DELETE FROM proxy_requests')]
    check(len(deletes) >= 10, '18 000 requests over the cap went in %d statement(s)' % len(deletes))
    s.PROXY_REQUESTS_MOST = 200000
    # the newest 12 000 are the last 12 000 seconds; keep two hours of them
    (gone, said) = traced(s.proxy_requests_forget, 2 / 24.0)
    deletes = [x for x in said if x.startswith('DELETE FROM proxy_requests')]
    check(abs(gone - (12000 - 7200)) < 60 and len(deletes) >= 4,
          'out of date: %d requests went in %d statement(s)' % (gone, len(deletes)))
    put('INSERT INTO proxy_lines (ts, src, ip, method, path, status, kind) VALUES (?,?,?,?,?,?,?)',
        ((NOW - 40 * 86400 + i, 'access', '10.0.0.1', 'GET', '/', 200, '') for i in range(24000)))
    put('INSERT INTO proxy_lines (ts, src, ip, method, path, status, kind) VALUES (?,?,?,?,?,?,?)',
        ((NOW - i, 'access', '10.0.0.1', 'GET', '/', 200, '') for i in range(100)))
    gone, said = traced(s.proxy_lines_forget, 30)
    deletes = [x for x in said if x.startswith('DELETE FROM proxy_lines')]
    check(gone == 24000 and count('SELECT COUNT(*) FROM proxy_lines') == 100,
          'the old proxy lines: %d went, %d left' % (gone, count('SELECT COUNT(*) FROM proxy_lines')))
    check(len(deletes) >= 4, '24 000 old proxy lines went in %d statement(s)' % len(deletes))

    # -- the hourly fold ----------------------------------------------------------
    print('the hourly fold: a series never folded, in pieces; and room for others between turns')
    hour = (NOW // 3600) * 3600
    cutoff = hour - 7200
    begin = hour - 3 * 86400
    put('INSERT INTO samples (ts, device, key, value) VALUES (?,?,?,?)',
        ((t, '0xbig', 'power', float(t % 7)) for t in range(begin, NOW, 10)))
    s.set_meta('aggregated_to', '0')
    done, steps = most_steps(s.aggregate)
    hours = (cutoff - begin) // 3600
    check(done == hours, 'the fold of a series never folded made %d hourly rows, not %d' % (done, hours))
    with s.lock:
        h = s.db.execute("SELECT n, avg, min, max FROM samples_hourly WHERE device='0xbig' AND ts=?",
                         (begin + 7200,)).fetchone()
    want = [float(t % 7) for t in range(begin + 7200, begin + 10800, 10)]
    check(h is not None and h[0] == len(want) and abs(h[1] - sum(want) / len(want)) < 1e-9
          and h[2] == min(want) and h[3] == max(want), 'an hour folded in pieces: %r' % (tuple(h) if h else None,))
    check(steps < 400, 'a series never folded was folded in one turn of the lock: %d steps' % steps)
    # interrupted half way: what is left folds into the same hours
    zigmon.CONFIG['retain_full_days'] = 1
    s.set_meta('aggregated_to', '0')
    s.aggregate()
    zigmon.CONFIG['retain_full_days'] = 14
    with s.lock:
        h2 = s.db.execute("SELECT n, avg FROM samples_hourly WHERE device='0xbig' AND ts=?",
                          (begin + 7200,)).fetchone()
        oldest = s.db.execute("SELECT MIN(ts) FROM samples WHERE device='0xbig' AND key='power'").fetchone()[0]
    check(h2 is not None and tuple(h2) == (h[0], h[1]),
          'folded again after its readings went, an hour changed: %r -> %r' % (tuple(h), tuple(h2) if h2 else None))
    drop = ((NOW - 86400) // 3600) * 3600
    check(oldest is not None and drop <= oldest < drop + 20, 'a day kept: the oldest is %r, not %r' % (oldest, drop))
    # many series, each a short turn: the others still get the lock
    put('INSERT INTO samples (ts, device, key, value) VALUES (?,?,?,?)',
        ((t, '0xmany%03d' % i, 'temperature', float(i)) for i in range(500)
         for t in range(cutoff - 3 * 3600, cutoff, 10)))
    s.set_meta('aggregated_to', str(cutoff - 3 * 3600))
    waited, took = worst_wait(s.aggregate)
    print('  the fold of 500 series: %.0f ms, the most another thread waited %.0f ms' % (took * 1000, waited * 1000))
    check(waited < max(0.15, took / 4), 'during the fold (%.0f ms) another thread waited %.0f ms for the lock'
          % (took * 1000, waited * 1000))
    # a retention, likewise
    put('INSERT INTO events (ts, device, kind, level, detail) VALUES (?,?,?,?,?)',
        ((NOW - 900 * 86400 + i, None, 'rule', 'info', 'very old') for i in range(150000)))
    waited, took = worst_wait(s._drop_older, 'events', NOW - 800 * 86400)
    print('  150 000 old events: %.0f ms, the most another thread waited %.0f ms' % (took * 1000, waited * 1000))
    check(waited < max(0.15, took / 4), 'during a retention (%.0f ms) another thread waited %.0f ms for the lock'
          % (took * 1000, waited * 1000))

    print('what is kept about addresses, tidied by the index')
    put('INSERT INTO block_events (ts, ip, what, why, auto, by) VALUES (?,?,?,?,?,?)',
        ((NOW - i, '10.8.%d.%d' % (i % 250, i % 233), 'blocked', 'x', 1, '') for i in range(60000)))
    s.set_meta('blocked_proof_10.8.1.1', '[]')      # in the story
    s.set_meta('blocked_proof_9.9.9.9', '[]')       # nowhere
    s.set_meta('ids_about_9.9.9.8', '{}')           # nowhere
    s.block('7.7.7.7', why='on the list')
    s.set_meta('blocked_proof_7.7.7.7', '[]')       # on the list
    s.flush()
    s.set_meta('aggregated_to', str(cutoff - 3600))
    _, steps = most_steps(s.aggregate)
    check(s.get_meta('blocked_proof_9.9.9.9') is None and s.get_meta('ids_about_9.9.9.8') is None,
          'what was kept about an address nobody remembers stayed')
    check(s.get_meta('blocked_proof_10.8.1.1') == '[]' and s.get_meta('blocked_proof_7.7.7.7') == '[]',
          'what was kept about an address still remembered went')
    check(steps < 60, 'the tidy-up read every address of the story under the lock: %d steps' % steps)
    s.unblock('7.7.7.7')

    # -- a device's rows ----------------------------------------------------------
    print("a device's rows go in pieces")
    put('INSERT INTO samples (ts, device, key, value) VALUES (?,?,?,?)',
        ((NOW - i * 10, 'grp:gone', k, 1.0) for k in ('temperature', 'humidity') for i in range(15000)))
    put('INSERT INTO events (ts, device, kind, level, detail) VALUES (?,?,?,?,?)',
        ((NOW - i, 'grp:gone', 'state', 'info', 'x') for i in range(12000)))
    s.upsert_device({'id': 'grp:gone', 'name': 'Gone group', 'source': 'group'})
    (n, steps), said = traced(most_steps, s.forget_devices, ['grp:gone'])
    deletes = [x for x in said if x.startswith('DELETE FROM samples') or x.startswith('DELETE FROM events')]
    check(count("SELECT COUNT(*) FROM samples WHERE device='grp:gone'") == 0
          and count("SELECT COUNT(*) FROM events WHERE device='grp:gone'") == 0
          and count("SELECT COUNT(*) FROM devices WHERE id='grp:gone'") == 0, 'the group was not all taken away')
    check(len(deletes) >= 8, "a group's 42 000 rows went in %d statement(s)" % len(deletes))
    # a device's own shorter retention
    plug = d.plugs['Lamp']
    plug.cfg['retain_full_days'] = 1
    put('INSERT OR REPLACE INTO samples (ts, device, key, value) VALUES (?,?,?,?)',
        ((NOW - i * 20, plug.device_id, k, 2.0) for k in ('switch.apower', 'switch.voltage')
         for i in range(13000)))
    keep = count('SELECT COUNT(*) FROM samples WHERE device=? AND ts>=?', (plug.device_id, NOW - 86400 + 60))
    _, said = traced(d.purge_per_device)
    deletes = [x for x in said if x.startswith('DELETE FROM samples')]
    check(0 <= count('SELECT COUNT(*) FROM samples WHERE device=?', (plug.device_id,)) - keep <= 2 * 6,
          "the socket's own retention kept %d of %d" % (count('SELECT COUNT(*) FROM samples WHERE device=?',
                                                             (plug.device_id,)), keep))
    check(len(deletes) >= 4, "a socket's own retention went in %d statement(s)" % len(deletes))
    plug.cfg.pop('retain_full_days', None)

    # -- prune ----------------------------------------------------------------------
    print('prune reads on a reader of its own')
    put('INSERT INTO samples (ts, device, key, value) VALUES (?,?,?,?)',
        ((NOW - 5000 + i * 10, '0xflat', 'linkquality', 5.0 if i < 200 else 6.0) for i in range(400)))
    put('INSERT INTO samples (ts, device, key, value) VALUES (?,?,?,?)',
        ((NOW - 5000 + i * 10, '0xflat', 'sys.uptime_ts', 1.0) for i in range(300)))
    dry, took = held_for(1.5, lambda: s.prune(False))
    check(took < 1.0, 'the dry run of prune waited %.1f s for the lock' % took)
    flats = dry.get('repeated_rows')
    check((dry.get('bookkeeping_rows') or 0) >= 300, 'the dry run of prune counted %r bookkeeping rows'
          % dry.get('bookkeeping_rows'))
    _, steps = most_steps(s.prune, False)
    check(steps < 3, 'the dry run of prune read every reading under the lock: %d steps' % steps)
    before = count("SELECT COUNT(*) FROM samples WHERE device='0xflat' AND key='linkquality'")
    done = s.prune(True)
    after = count("SELECT COUNT(*) FROM samples WHERE device='0xflat' AND key='linkquality'")
    # 5.0 x200 then 6.0 x200, 10 s apart: each run keeps its first and one every GATEWAY_ANCHOR_S
    check(done['repeated_rows'] == flats and before - after >= 390 and after <= 10,
          'prune dropped %d of the flat series (%d -> %d; dry run said %r)' % (before - after, before, after, flats))
    got = count("SELECT COUNT(*) FROM samples WHERE device='0xflat' AND key='linkquality' AND ts=?",
                (NOW - 5000 + 200 * 10,))
    check(got == 1, 'the first reading of a new value went with the repeats')
    check(count("SELECT COUNT(*) FROM samples WHERE device='0xflat' AND key='sys.uptime_ts'") == 0,
          'prune left the bookkeeping rows')

    # -- reset ----------------------------------------------------------------------
    print("reset's VACUUM takes the lock, as every use of the shared connection")
    owned = []

    def watch(sql):
        if sql.strip().upper().startswith('VACUUM'):
            owned.append(REAL_LOCK._is_owned())
    s.db.set_trace_callback(watch)
    try:
        s.reset('device', '0xflat')
    finally:
        s.db.set_trace_callback(None)
    check(owned == [True], "reset's VACUUM ran without the lock (held: %r)" % owned)
    check(count("SELECT COUNT(*) FROM samples WHERE device='0xflat'") == 0, 'reset left the device')

    # -- a router that is slow --------------------------------------------------
    print('a slow router: one sync waiting, not one per change')
    calls, gate = [], threading.Event()

    def slow_sync(why='', progress=None):
        calls.append(why)
        gate.wait(10)
    d.mikrotik_sync = slow_sync
    before = threading.active_count()
    threads = [threading.Thread(target=d._mikrotik_quietly) for _ in range(12)]
    for t in threads:
        t.start()
        time.sleep(0.01)
    time.sleep(0.3)
    waiting = sum(1 for t in threads if t.is_alive())
    gate.set()
    for t in threads:
        t.join(10)
    del d.mikrotik_sync
    check(waiting <= 2, '%d syncs with the router were running or waiting at once' % waiting)
    check(len(calls) == 2, 'twelve changes while the router was slow made %d syncs, not 2' % len(calls))

    # -- the hot path, measured -------------------------------------------------
    print('with the lock held, the light path does not wait (measured)')
    s.upsert_device({'id': '0xhot', 'name': 'Hot sensor', 'source': 'zigbee'})
    d.record('0xhot', 'Hot sensor', {'temperature': 20.0})
    s.flush()
    d.status()
    _, took = held_for(1.5, lambda: d.record('0xhot', 'Hot sensor', {'temperature': 21.0, 'occupancy': True}))
    print('  a reading recorded: %.1f ms' % (took * 1000))
    check(took < 0.5, 'a reading waited %.0f ms for the lock' % (took * 1000))
    _, took = held_for(1.5, lambda: d.status())
    print('  the status: %.1f ms' % (took * 1000))
    check(took < 0.5, 'the status waited %.0f ms for the lock' % (took * 1000))
    s.blocked_until('10.0.0.9')
    _, took = held_for(1.5, lambda: (s.get_meta('rules'), s.device('0xhot'),
                                     s.blocked_until('10.0.0.9', wait=False)))
    print("  the rules' reads: %.1f ms" % (took * 1000))
    check(took < 0.5, "the rules' reads waited %.0f ms for the lock" % (took * 1000))
finally:
    try:
        s.db.set_progress_handler(None, 0)
        s.db.set_trace_callback(None)
        s.lock = REAL_LOCK
        s.flush(5)
    except Exception:
        pass
    shutil.rmtree(str(W), ignore_errors=True)

print('pass3_locks: %s' % ('%d failed' % len(bad) if bad else 'all good'))
os._exit(1 if bad else 0)
