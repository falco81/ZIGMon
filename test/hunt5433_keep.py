#!/usr/bin/env python3
"""5.43.3: keeping the machine - backups, restores, root's requests, the
schedules and the command line. Each check fails on 5.43.2.

    python3 test/hunt5433_keep.py

  * a database put back from an older version gets the tables added since
    at once, not at the next restart of the daemon;
  * the nightly backup is claimed for its day in the database: a restart of
    the daemon after its time does not make it again;
  * the backups of the whole installation are pruned newest first by when
    they were made, not by name - a renamed machine kept its old ones and
    deleted the new; and the archive is on the disk before it is named;
  * two requests laid down for root at once: the second is refused, never
    put over the first;
  * going back to an older version is called so in maintenance after root
    took the request;
  * zigmon --backup lists the files by their names and times;
  * test/osupdates.py: its schedule is not run on the real clock by the
    daemon's own system loop at the same time ("looked twice on one day").

No daemon, no port: the parts are called as the daemon calls them.
"""
import contextlib
import importlib.util
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-hunt5433-keep-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

try:
    print('a database from an older version put back')
    s = zigmon.Storage(W / 'live.db')
    s.backup_to(W / 'old.db')
    c = sqlite3.connect(str(W / 'old.db'))
    c.execute('DROP TABLE blocked_log')
    c.execute('DROP TABLE wifi_seen')
    c.commit()
    c.close()
    s.restore_from(W / 'old.db')
    have = {r[0] for r in s.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    check({'blocked_log', 'wifi_seen'} <= have,
          'a database from an older version was put back without the tables added since (%s missing) - '
          'every write to them failed until the next restart'
          % ', '.join(sorted({'blocked_log', 'wifi_seen'} - have)))
    try:
        with s.lock:
            s.db.execute("INSERT INTO blocked_log (ts, ip) VALUES (1, '192.0.2.1')")
        wrote = True
    except sqlite3.Error as e:
        wrote = False
        print('  (%s)' % e)
    check(wrote, 'a write to a table added since failed after the restore')

    print('the nightly backup, once a day across restarts')
    zigmon.CONFIG['backup_time'] = '03:30'
    lt = time.localtime()
    at = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 14, 0, 0, 0, 0, -1))
    early = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 2, 0, 0, 0, 0, -1))
    due = getattr(zigmon.Daemon, 'backup_due', None)
    got = []
    if due:
        got.append(due(types.SimpleNamespace(store=s), early))
        got.append(due(types.SimpleNamespace(store=s), at))
        got.append(due(types.SimpleNamespace(store=s), at + 60))     # the daemon restarted meanwhile
        got.append(due(types.SimpleNamespace(store=s), at + 86400))
    check(got == [False, True, False, True],
          'the nightly backup is not claimed for its day (before, due, after a restart, the next day): '
          '%r - a restart after its time made the whole backup again' % got)

    print('the backups of the whole installation pruned by when they were made')
    os.environ['ZIGMON_FULL_DIR'] = str(W / 'full')
    spec = importlib.util.spec_from_file_location('zigmon_root_k', str(HERE / 'deploy' / 'zigmon_root.py'))
    zr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(zr)
    zr.FULL_DIR = str(W / 'full')
    os.makedirs(zr.FULL_DIR)
    names = []
    for n in range(4):                      # the machine was called zeta
        names.append('zigmon-full-zeta-2026-10-0%d-033000.tar.gz' % (n + 1))
    for n in range(3):                      # and is alpha since
        names.append('zigmon-full-alpha-2026-11-0%d-033000.tar.gz' % (n + 1))
    for i, n in enumerate(names):
        p = os.path.join(zr.FULL_DIR, n)
        with open(p, 'wb') as f:
            f.write(b'x')
        os.utime(p, (1790000000 + i * 86400, 1790000000 + i * 86400))
    zr.full_prune(3, spare=names[-1])
    left = sorted(os.listdir(zr.FULL_DIR))
    want = sorted(names[-3:])
    check(left == want, 'a renamed machine: the newest three were not the ones kept: %r (wanted %r)'
          % (left, want))
    src = (HERE / 'deploy' / 'zigmon_root.py').read_text()
    body = src[src.index('def full_make('):src.index('RESTORE_TXT = ')]
    check('os.fsync(' in body and body.index('os.fsync(') < body.index('os.replace(tmp_path, path)'),
          'the backup of the whole installation is named before it is on the disk (no fsync before '
          'the rename): a power cut left a cut-off file under a backup\'s name')

    print('an update\'s job and the look whether one is running')
    import fcntl
    import threading
    zr.OSUP_LOCK = str(W / 'osup.lock')
    held = os.open(zr.OSUP_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(held, fcntl.LOCK_EX)            # osup_running() looking, for a moment

    def let_go():
        time.sleep(0.3)
        fcntl.flock(held, fcntl.LOCK_UN)
    threading.Thread(target=let_go, daemon=True).start()
    take = getattr(zr, 'osup_lock_take', None)
    got = take() if take else None
    check(got is not None, 'the job of an update gave up at once when osup_running() held its lock '
          'for a moment to look - the update asked for never ran')
    if got is not None:
        os.close(got)
    os.close(held)

    print('two requests for root at once')
    rd = W / 'root'
    rd.mkdir()
    fake = types.SimpleNamespace(root_installed=lambda: True, root_folders=lambda: None,
                                 root_dir=lambda *n: rd.joinpath(*n),
                                 root_busy=lambda: None)       # both found root free
    os.environ.pop('ZIGMON_ROOT_RUN', None)
    first = zigmon.Daemon.root_ask(fake, 'full_make', {'why': 'to other machines'}, quiet=True)
    second = None
    try:
        second = zigmon.Daemon.root_ask(fake, 'apply', {}, quiet=True)
    except ValueError:
        pass
    import json
    laid = json.loads((rd / 'request.json').read_text())
    check(second is None and laid.get('id') == first,
          'a second request for root was put over the first, which root then never saw: %r'
          % laid.get('kind'))
    check(not [p for p in rd.iterdir() if p.name.startswith('.request.')],
          'a request\'s temporary file was left behind')

    print('going back, in maintenance')
    now = time.time()
    asked = {'id': 'abc123', 'version': '5.40.0', 'from': '5.43.2', 'downgrade': True}
    fake = types.SimpleNamespace(
        upgrade_status=lambda: {'id': 'abc123', 'state': 'running', 'step': 'installing',
                                'version': '5.40.0', 'at': now},
        upgrade_asked=lambda: False, _mj=lambda k: asked if k == 'upgrade_asked' else None)
    kind, why = zigmon.Daemon.maint_work(fake)
    check(why == 'going back to zigmon 5.40.0',
          'going back was called an upgrade once root took the request: %r' % why)
    asked2 = dict(asked, downgrade=False)
    fake._mj = lambda k: asked2 if k == 'upgrade_asked' else None
    kind, why = zigmon.Daemon.maint_work(fake)
    check(why == 'the upgrade to zigmon 5.40.0', 'an upgrade was called going back: %r' % why)

    print('zigmon --backup')
    ts = time.mktime((2026, 11, 2, 4, 5, 0, 0, 0, -1))
    real = zigmon._need_daemon
    zigmon._need_daemon = lambda pal, path='': {'ok': True, 'backups': [
        {'file': 'zigmon-db-2026-11-02-040500.sqlite', 'bytes': 2500000, 'ts': int(ts)}]}
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            zigmon.cmd_backup(types.SimpleNamespace(backup='', json=False, pin=''), zigmon.Palette(False))
    finally:
        zigmon._need_daemon = real
    text = out.getvalue()
    check('zigmon-db-2026-11-02-040500.sqlite' in text and '2026-11-02 04:05' in text and 'None' not in text,
          'zigmon --backup does not list the backups by name and time: %r' % text)

    print('test/osupdates.py and the daemon\'s own loop')
    t = (HERE / 'test' / 'osupdates.py').read_text()
    part = t[t.index("print('the schedule')"):t.index("print('the regular restart waits for an update')")]
    check('zigmon.osup_tick = ' in part,
          'test/osupdates.py runs its schedule on a clock of its own while the daemon\'s system loop '
          'runs the same schedule on the real one - "looked twice on one day" when the loop came round')
finally:
    shutil.rmtree(str(W), ignore_errors=True)

if bad:
    print('%d check(s) FAILED' % len(bad))
    sys.exit(1)
print('all checks passed')
