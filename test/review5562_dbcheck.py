#!/usr/bin/env python3
"""5.56.2: the integrity check of a large file on a slow disk no longer ends in a 504.

The check ran inside the request: 500 MB on a slow virtual disk took longer than the
web server's two minutes, the page showed "HTTP 504 Gateway Time-out", and a second
click started a second check beside the first. Now the check runs on a thread of
its own, the request answers "still running" after a while, the page asks again,
and asking again joins the check that is running.

    python3 test/review5562_dbcheck.py < /dev/null
"""
import re
import sys
import threading
import time
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


check(hasattr(zigmon.Daemon, 'db_check_job'), 'the daemon has no background integrity check')
if not hasattr(zigmon.Daemon, 'db_check_job'):
    print('review5562_dbcheck: %d FAILED' % len(bad))
    sys.exit(1)

zigmon.log = lambda *a, **k: None
release = threading.Event()
runs = []


class Store(object):
    def stats(self):
        return {'bytes': 500 << 20}

    def integrity_check(self):
        runs.append(threading.current_thread().name)
        release.wait(10)
        return {'ok': True, 'lines': ['ok'], 'foreign_key_problems': 0}


class D(object):
    store = Store()
    cleared = []
    notice_clear = lambda self, key, *a, **k: self.cleared.append(key)
    notice_raise = lambda self, *a, **k: None


D.db_check_job = zigmon.Daemon.db_check_job
D._db_check_notice = zigmon.Daemon._db_check_notice
d = D()

t0 = time.time()
first = d.db_check_job(wait=0.3)
check(time.time() - t0 < 2, 'the request waited for the whole check')
check(first.get('running') is True and first.get('ok') is True, 'a long check does not say running: %r' % first)
again = d.db_check_job(wait=0.2)
check(again.get('running') is True, 'asking again does not say running: %r' % again)
time.sleep(0.2)
check(len(runs) == 1, 'asking again started a second check (%d running)' % len(runs))
release.set()
done = d.db_check_job(wait=5)
check(done.get('running') is False and done.get('lines') == ['ok'], 'the outcome is not handed out: %r' % done)
check(len(runs) == 1 and runs[0] == 'db-check', 'the check did not run once on its own thread: %r' % runs)
check(d.cleared == ['db-integrity'], 'a passing check does not clear the notice')
# a quick one answers at once with the outcome, within the same request
d._db_check = None
quick = d.db_check_job(wait=5)
check(quick.get('running') is False and quick.get('lines') == ['ok'], 'a quick check is not answered at once: %r' % quick)

src = (HERE / 'zigmon.py').read_text()
block = src[src.index("if path == '/api/db/check':"):src.index("if path == '/api/mqtt/ghosts':")]
check('d.db_check_job(' in block and 'integrity_check()' not in block,
      'the API still checks inside the request')
check(zigmon.DB_CHECK_WAIT < 60, 'the request may wait longer than a web server would')
page = (HERE / 'web' / 'index.php').read_text()
check(re.search(r"r\.running\)[\s\S]{0,200}dbCheckPost\(what, body\)", page) is not None,
      'the page does not ask again while the check runs')
check("'db-check',\n    function (r)" in page and 'undefined, dbCheckPost);' in page,
      'the check button does not use the asking-again post')

# the header's row counts walk the whole samples table: not every half a minute
check(getattr(zigmon, 'STATS_KEEP', 30) >= 300, 'the row counts are counted again every half a minute')
counted = []
st = zigmon.Storage.__new__(zigmon.Storage)
st._stats_cache = (time.time() - 120, {'samples': 1})
st._stats_guard = threading.Lock()
st._stats_count_now = lambda: counted.append(1)
got = st.stats()
time.sleep(0.2)
check(got.get('samples') == 1 and not counted, 'two-minute-old row counts are counted again')

print('review5562_dbcheck: ' + ('all good' if not bad else '%d FAILED' % len(bad)))
sys.exit(1 if bad else 0)
