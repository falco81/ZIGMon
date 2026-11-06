#!/usr/bin/env python3
"""5.44, pass 1: the database, measured on a house with history in it. Each
check fails on 5.43.4.

    python3 test/pass1_storage.py

The work a call does under the store's one lock is counted in SQLite's own
steps (a progress handler), not timed, so a busy machine does not change
the answer:

  * the hourly fold goes series by series by the readings' own key: it read
    every row of `samples` twice, in one transaction under the lock, every
    hour; and a retention shortened in Settings is dropped a few thousand
    rows at a time, not in one statement;
  * the keys of a device and the stale devices are found by seeking the
    index, not by reading every row;
  * the integrity check and the backup read on a connection of their own
    and do not wait for the lock (nor hold it: 8.9 s and 1.1 s on a year of
    a 65-device house);
  * the level filter of the events uses an index (added once, also to an
    old database), and the count of a device's search is of that device;
  * a month or a year of a socket's meter counts the hours before the
    fortnight of readings, from the hourly table (the year's figure was two
    weeks);
  * the peaks read the readings only from where the fold has got to;
  * the write-ahead log is folded back on a connection of its own, not in
    the COMMIT of whichever write filled it.

No port: the parts are called as the daemon calls them.
"""
import inspect
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-pass1-storage-'))
sys.path.insert(0, os.environ.get('PASS1_DAEMON') or str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'zigmon.db'), 'api_port': 19421, 'token_file': str(W / 'token'),
                      'plugs': [{'name': 'Lamp', 'host': '127.0.0.1:19422'},
                                {'name': 'Heater', 'host': '127.0.0.1:19423'}],
                      'sensors': [], 'backup_dir': str(W / 'backups'), 'weather': False,
                      'state_dir': str(W), 'retain_full_days': 14})
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


class Counted(object):
    """The store's lock, counting SQLite's steps (1000 VM instructions
    each) taken while it is held - the most of any one hold."""

    def __init__(self, real):
        self.real, self.depth, self.ticks, self.most = real, 0, 0, 0

    def _in(self):
        self.depth += 1
        if self.depth == 1:
            self.ticks = 0

    def _out(self):
        self.depth -= 1
        if self.depth == 0:
            self.most = max(self.most, self.ticks)

    def acquire(self, *a, **k):
        got = self.real.acquire(*a, **k)
        if got:
            self._in()
        return got

    def release(self):
        self._out()
        self.real.release()

    def __enter__(self):
        self.real.acquire()
        self._in()
        return self

    def __exit__(self, *a):
        self._out()
        self.real.release()


def tick():
    s.lock.ticks += 1
    return 0


REAL_LOCK = s.lock


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


try:
    # -- a house with a fortnight and a day of readings: 12 series a minute apart
    print('a fortnight of readings, folded hourly')
    series = [('0xfold%02d' % i, k) for i in range(4) for k in ('temperature', 'humidity', 'battery')]
    begin = NOW - 15 * 86400
    put('INSERT INTO samples (ts, device, key, value) VALUES (?,?,?,?)',
        ((t, dev, key, float((t // 60) % 97)) for dev, key in series for t in range(begin, NOW, 60)))
    hour = (NOW // 3600) * 3600
    cutoff = hour - 7200
    s.set_meta('aggregated_to', str(cutoff - 3 * 3600))
    done, steps = most_steps(s.aggregate)
    check(steps < 120, 'the hourly fold read the whole table under the lock: %d steps in one hold' % steps)
    check(done == len(series) * 3, 'the fold made %r hourly rows, not %d' % (done, len(series) * 3))
    with s.lock:
        h = s.db.execute('SELECT n, avg FROM samples_hourly WHERE device=? AND key=? AND ts=?',
                         ('0xfold01', 'humidity', cutoff - 3600)).fetchone()
        want = [float((t // 60) % 97) for t in range(cutoff - 3600, cutoff, 60) if t >= begin]
        oldest = s.db.execute('SELECT MIN(ts) FROM samples WHERE device=? AND key=?',
                              ('0xfold01', 'humidity')).fetchone()[0]
    check(h is not None and h[0] == len(want) and abs(h[1] - sum(want) / len(want)) < 1e-9,
          'an hour folded series by series is not the hour it was: %r' % (tuple(h) if h else None,))
    drop = ((NOW - 14 * 86400) // 3600) * 3600
    check(oldest is not None and drop <= oldest < drop + 120,
          'the readings older than the fortnight were not dropped on the hour: oldest %r, wanted %r'
          % (oldest, drop))
    check(s.get_meta('aggregated_to') == str(cutoff), 'the fold did not say how far it got')
    print('  the most one hold of the lock took: %d steps' % steps)

    print('a retention shortened in Settings is dropped in pieces')
    put('INSERT INTO events (ts, device, kind, level, detail) VALUES (?,?,?,?,?)',
        ((NOW - 60 * 86400 + i, None, 'rule', 'info', 'old %d' % i) for i in range(12000)))
    put('INSERT INTO events (ts, device, kind, level, detail) VALUES (?,?,?,?,?)',
        ((NOW - 86400 + i, None, 'rule', 'info', 'new %d' % i) for i in range(50)))
    zigmon.CONFIG['retain_events_days'] = 30
    said = []
    s.db.set_trace_callback(said.append)
    s.set_meta('aggregated_to', str(cutoff - 3600))
    try:
        s.aggregate()
    finally:
        s.db.set_trace_callback(None)
        zigmon.CONFIG.pop('retain_events_days', None)
    deletes = [x for x in said if x.startswith('DELETE FROM events')]
    with s.lock:
        left = s.db.execute('SELECT COUNT(*) FROM events WHERE detail LIKE ?', ('old %',)).fetchone()[0]
        kept = s.db.execute('SELECT COUNT(*) FROM events WHERE detail LIKE ?', ('new %',)).fetchone()[0]
    check(len(deletes) >= 3, '12 000 old events went in %d statement(s) under the lock' % len(deletes))
    check(left == 0 and kept == 50, 'the retention left %d old and kept %d new of 50' % (left, kept))

    # -- the keys of one device, and the devices nobody shows
    print('the keys of a device, the stale devices')
    put('INSERT INTO samples (ts, device, key, value) VALUES (?,?,?,?)',
        ((NOW - i * 10, '0xkeys', 'k%d' % j, 1.0) for j in range(5) for i in range(20000)))
    put('INSERT INTO samples_hourly (ts, device, key, n, avg, min, max) VALUES (?,?,?,?,?,?,?)',
        [(hour - 86400 * 20, '0xkeys', 'only_hourly', 1, 1.0, 1.0, 1.0)])
    keys, steps = most_steps(s.keys_for, '0xkeys')
    check(keys == ['k0', 'k1', 'k2', 'k3', 'k4', 'only_hourly'], 'the keys of a device: %r' % (keys,))
    check(steps < 30, 'the keys of a device were found by reading its 100 000 rows: %d steps' % steps)
    s.upsert_device({'id': '0xgone', 'name': 'Gone', 'source': 'zigbee'})
    s.mark_removed('0xgone')
    put('INSERT INTO samples (ts, device, key, value) VALUES (?,?,?,?)',
        ((NOW - i * 60, '0xgone', 'temperature', 2.0) for i in range(300)))
    put('INSERT INTO events (ts, device, kind, level, detail) VALUES (?,?,?,?,?)',
        ((NOW - i, '0xgone', 'availability', 'info', 'x') for i in range(7)))
    for ident in ['0xkeys'] + sorted({dev for dev, _ in series}):
        s.upsert_device({'id': ident, 'name': ident, 'source': 'zigbee'})
    put('INSERT INTO samples (ts, device, key, value) VALUES (?,?,?,?)',
        ((NOW - i * 60, '0xorphan', 'temperature', 2.0) for i in range(50)))
    stale, steps = most_steps(s.stale_data)
    byid = {x['device']: x for x in stale['devices']}
    gone = byid.get('0xgone') or {}
    check(gone.get('samples') == 300 and gone.get('events') == 7 and gone.get('rows') == 307,
          'the stale device was counted as %r' % (gone,))
    check('0xorphan' in byid and byid['0xorphan'].get('samples') == 50 and '0xkeys' not in byid,
          'a device with no row of its own was not counted: %r' % (stale,))
    check(steps < 60, 'the stale devices were found by counting every row of every table: %d steps' % steps)

    # -- the long reads, beside a lock somebody holds
    print('the integrity check and the backup do not wait for the lock')
    s.store_sample('0xlast', NOW, {'temperature': 21.5})
    s.flush()
    holding = threading.Event()

    def hold(seconds):
        with REAL_LOCK:
            holding.set()
            time.sleep(seconds)

    for name, call in (('integrity check', s.integrity_check),
                       ('backup', lambda: s.backup_to(W / 'copy.sqlite'))):
        holding.clear()
        th = threading.Thread(target=hold, args=(2.5,))
        th.start()
        holding.wait(5)
        t0 = time.time()
        got = call()
        took = time.time() - t0
        th.join()
        check(took < 1.5, 'the %s waited %.1f s for a lock it does not need' % (name, took))
        if name == 'integrity check':
            check(got.get('ok') is True, 'the integrity check said %r' % (got,))
    c = sqlite3.connect(str(W / 'copy.sqlite'))
    try:
        row = c.execute("SELECT value FROM samples WHERE device='0xlast'").fetchone()
    finally:
        c.close()
    check(row is not None and row[0] == 21.5, 'the backup lacks the last reading written: %r' % (row,))

    # -- events: the level filter, and a device's count
    print('events: by level through an index, a device counted as itself')
    put('INSERT INTO events (ts, device, kind, level, detail) VALUES (?,?,?,?,?)',
        [(NOW - 5, '0xev1', 'alert', 'warn', 'hot in here'), (NOW - 4, '0xev2', 'alert', 'warn', 'hot there'),
         (NOW - 3, '0xev1', 'alert', None, 'hot, no level'), (NOW - 2, '0xev1', 'alert', 'crit', 'very hot')])
    said = []
    s.db.set_trace_callback(said.append)
    try:
        warn = s.events(50, kind='alert', level='warn')
    finally:
        s.db.set_trace_callback(None)
    asked = [x for x in said if x.startswith('SELECT * FROM events')]
    with s.lock:
        plan = ' '.join(r[3] for r in s.db.execute('EXPLAIN QUERY PLAN ' + asked[-1])) if asked else ''
    check('events_level_ts' in plan, 'the level filter read the events from the newest back: %r' % plan)
    check(sorted(x['detail'] for x in warn) == ['hot in here', 'hot there'], 'warn: %r' % (warn,))
    info = [x['detail'] for x in s.events(2000, level='info')]
    check('hot, no level' in info, 'an event with no level is not info any more')
    check(s.events_count(level='crit') == 1, 'crit counted %r' % s.events_count(level='crit'))
    try:
        mine = s.events_count('hot', device='0xev1')
    except TypeError as e:
        mine = e
    check(mine == 3, "a device's search was counted over every device: %r" % (mine,))
    # an old database gets the index, once
    with s.lock:
        s.db.execute('DROP INDEX IF EXISTS events_level_ts')
    s.schema_up()
    s.schema_up()
    with s.lock:
        n = s.db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='events_level_ts'").fetchone()[0]
    check(n == 1, 'the level index is in an old database %d time(s)' % n)

    # -- a socket's meter over a month and a year
    print("a socket's meter over more than the fortnight of readings")
    meter = 'plug:Meter'
    first_h = hour - 40 * 86400
    raw_from = NOW - 14 * 86400
    put('INSERT INTO samples_hourly (ts, device, key, n, avg, min, max) VALUES (?,?,?,?,?,?,?)',
        ((t, meter, 'switch.aenergy.total', 60, (t - first_h) / 36.0 + 50, (t - first_h) / 36.0,
          (t - first_h) / 36.0 + 99) for t in range(first_h, raw_from - 3600, 3600)))
    put('INSERT INTO samples (ts, device, key, value) VALUES (?,?,?,?)',
        ((t, meter, 'switch.aenergy.total', (t - first_h) / 36.0) for t in range(raw_from, NOW, 300)))
    whole = (NOW - 300 - first_h) / 36.0
    delta = s.counter_delta(meter, 'switch.aenergy.total', first_h, NOW)
    check(abs(delta - whole) < 200, 'forty days of the meter came to %.0f Wh, not %.0f' % (delta, whole))
    span = s.counter_span_many([(meter, 'switch.aenergy.total')], first_h, NOW).get((meter, 'switch.aenergy.total'))
    check(span is not None and abs((span[1] - span[0]) - whole) < 200,
          'the money of forty days counted %r, not %.0f Wh' % (span and span[1] - span[0], whole))
    gone_month = s.counter_span(meter, 'switch.aenergy.total', first_h, first_h + 20 * 86400)
    check(gone_month is not None and abs((gone_month[1] - gone_month[0]) - 20 * 2400) < 200,
          'a month with no readings left counted %r' % (gone_month,))
    near = s.counter_delta(meter, 'switch.aenergy.total', NOW - 86400, NOW)
    check(abs(near - (2400 - 300 / 36.0)) < 1, 'a day within the readings changed: %.1f' % near)

    # -- the peaks of the house
    print('the peaks read the readings only from where the fold got to')
    put('INSERT INTO samples (ts, device, key, value) VALUES (?,?,?,?)',
        ((t, dev, 'switch.apower', 100.0) for dev in ('plug:Lamp', 'plug:Heater')
         for t in range(NOW - 7 * 86400, NOW, 30)))
    s.set_meta('aggregated_to', str(cutoff))
    put('INSERT OR REPLACE INTO samples_hourly (ts, device, key, n, avg, min, max) VALUES (?,?,?,?,?,?,?)',
        ((t, dev, 'switch.apower', 120, 100.0, 100.0, 100.0) for dev in ('plug:Lamp', 'plug:Heater')
         for t in range(hour - 7 * 86400, cutoff, 3600)))
    put('INSERT OR REPLACE INTO samples (ts, device, key, value) VALUES (?,?,?,?)',
        [(cutoff + 600, 'plug:Lamp', 'switch.apower', 900.0)])
    d._power_peak_cache = None
    peaks, steps = most_steps(d.power_peaks)
    check(peaks.get('day') == 1000.0 and peaks.get('week') == 1000.0,
          'the peak after the fold was not seen: %r' % (peaks,))
    check(steps < 150, 'the peaks read a week of every socket under the lock: %d steps' % steps)

    # -- the write-ahead log
    print('the write-ahead log is folded back off the lock')
    with s.lock:
        pages = s.db.execute('PRAGMA wal_autocheckpoint').fetchone()[0]
    check(pages >= 10000, 'the COMMIT of a write still folds the log back every %d pages' % pages)
    has = hasattr(s, 'checkpoint')
    check(has, 'there is no checkpoint off the lock')
    check('store.checkpoint()' in inspect.getsource(zigmon.Daemon.run),
          'the main loop never folds the log back')
    if has:
        for i in range(200):
            s.store_sample('0xwal', NOW + i, {'temperature': float(i)})
        s.flush()
        holding.clear()
        th = threading.Thread(target=hold, args=(2.0,))
        th.start()
        holding.wait(5)
        t0 = time.time()
        moved = s.checkpoint()
        took = time.time() - t0
        th.join()
        check(took < 1.0 and moved, 'the checkpoint waited %.1f s or moved nothing (%r)' % (took, moved))
finally:
    try:
        s.db.set_progress_handler(None, 0)
        s.lock = REAL_LOCK
        s.flush(5)
    except Exception:
        pass
    shutil.rmtree(str(W), ignore_errors=True)

print('pass1_storage: %s' % ('%d failed' % len(bad) if bad else 'all good'))
os._exit(1 if bad else 0)
