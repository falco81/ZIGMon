#!/usr/bin/env python3
"""5.52: a battery's time left is read from its history since it was put in.

The old reading took the last 30 days' first and last point: a cell that sat on
one whole percent for a month said "not falling yet" for ever, with no time at
all, and one odd reading at either end decided the rest.

    python3 test/review5522_battery.py < /dev/null
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review5522-'))
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 20230, 'token_file': str(W / 'token'),
                      'plugs': [], 'sensors': [], 'weather': False, 'state_dir': str(W)})
d = zigmon.Daemon()
DAY = 86400
now = int(time.time())


def lay(dev, series):
    """(days ago, percent) - written as the store keeps them, the old ones hourly."""
    d.store.upsert_device({'id': dev, 'name': dev, 'source': 'zigbee', 'kind': 'sensor', 'exposes': {}})
    with d.store.lock:
        for ago, v in series:
            ts = now - int(ago * DAY)
            table = 'samples_hourly' if ago > int(zigmon.CONFIG.get('retain_full_days', 14)) else 'samples'
            if table == 'samples':
                d.store.db.execute('INSERT OR REPLACE INTO samples (device, ts, key, value) VALUES (?,?,?,?)', (dev, ts, 'battery', v))
            else:
                d.store.db.execute('INSERT OR REPLACE INTO samples_hourly (device, ts, key, avg, min, max, n) VALUES (?,?,?,?,?,?,?)',
                                   (dev, ts - ts % 3600, 'battery', v, v, v, 1))
        d.store.db.commit()
    d.live[dev] = {'payload': {'battery': series[-1][1]}, 'ts': now}


try:
    # 100 % for months, then down a step at a time: 100 -> 84 over 160 days, the last 40 on 84
    lay('pir', [(200 - i * 10, max(84, 100 - i)) for i in range(20)] + [(30, 84), (10, 84), (1, 84)])
    # stayed at 100 % for 90 days
    lay('fresh', [(90 - i * 10, 100) for i in range(9)] + [(0.5, 100)])
    # a new cell 20 days ago (52 -> 100), falling 1 % a week since
    lay('swap', [(120, 60), (60, 55), (21, 52), (20, 100), (13, 99), (6, 98), (0.2, 97)])
    d._battery_cache = None
    got = {b['id']: b for b in d.battery_health(force=True)}
    pir, fresh, swap = got.get('pir') or {}, got.get('fresh') or {}, got.get('swap') or {}
    check(pir.get('days_left') and pir.get('per_week'),
          'a cell that sat on 84 %% for the last month has no time left: %r' % pir)
    check(fresh.get('days_left') is None and (fresh.get('seen_days') or 0) >= 80,
          'a cell at 100 %% for 90 days does not say how long it has been watched: %r' % fresh)
    check(swap.get('per_week') and 0.5 <= swap['per_week'] <= 1.6 and swap.get('days_left') and swap['days_left'] > 300,
          'the old cell before a new one was counted: %r' % swap)
    check(zigmon.battery_span(40) == '40 days' and zigmon.battery_span(200) == '7 months'
          and zigmon.battery_span(1392) == '3.8 years', 'days said as a person says them')
    page = (HERE / 'web' / 'index.php').read_text()
    check("'no drop in ' + battSpan" in page and 'function battSpan' in page, 'the page says it the old way')
finally:
    try:
        d.store.close()
    except Exception:                                    # noqa: BLE001
        pass
    shutil.rmtree(W, ignore_errors=True)
print('review5522_battery: ' + ('all good' if not bad else '%d FAILED' % len(bad)))
sys.exit(1 if bad else 0)
