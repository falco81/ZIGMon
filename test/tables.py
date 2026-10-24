#!/usr/bin/env python3
"""The tables the daemon keeps by hand must not say the same thing twice.

Python keeps the last of two entries with the same key, so an earlier one is
dead text: editing it changes nothing, which is a trap for whoever comes to
edit it. Three had crept into KEY_INFO before this test existed.
"""
import re
import sys
from collections import Counter
from pathlib import Path

source = (Path(__file__).resolve().parent.parent / 'zigmon.py').read_text()
bad = False

for name in ('KEY_INFO', 'WEATHER_WORDS', 'NOTIFY_PRESETS'):
    block = re.search(r'\n%s = \{(.*?)\n\}' % name, source, re.S)
    if not block:
        continue
    keys = re.findall(r"^\s*'?([\w.]+)'?\s*:", block.group(1), re.M)
    dupes = [k for k, c in Counter(keys).items() if c > 1]
    print('%-16s %3d entries%s' % (name, len(keys), '' if not dupes else '  <-- said twice: ' + ', '.join(dupes)))
    bad = bad or bool(dupes)

names = re.findall(r'^    def (\w+)\(', source, re.M)
inner = {'__init__', 'snapshots', 'reset', 'stop', 'value', 'paint'}   # each in a class of its own
dupes = [n for n, c in Counter(names).items() if c > 1 and n not in inner]
print('%-16s %3d methods%s' % ('classes', len(names), '' if not dupes else '  <-- defined twice: ' + ', '.join(dupes)))
if bad or dupes:
    # not sys.exit here: everything below this line used to be unreachable,
    # which is how two checks written weeks apart both quietly did nothing
    raise SystemExit(1)

# Every setting the daemon will accept must have a default, and every default
# must be one it will accept: one added to the checks but not to the defaults
# is invisible to the settings page and silently absent from config.json.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # run from anywhere
import zigmon as _z   # noqa: E402
_tun = set(_z.Daemon.TUNABLE)
_def = set(_z.DEFAULTS)
_no_default = sorted(_tun - _def)
_unchecked = sorted(k for k in _def - _tun
                    if k not in ('plugs', 'sensors', 'zigbee_gateways', 'db_file', 'token_file', 'log_file',
                                 'pin', 'mqtt_host', 'mqtt_port', 'mqtt_username', 'mqtt_password', 'mqtt_tls',
                                 'mqtt_ca', 'mqtt_client_id', 'mqtt_keepalive', 'api_host', 'api_port',
                                 'base_topic', 'extra_topics', 'log_to_journal', 'plug_mqtt_password'))
print('%-16s %3d settings the page may change' % ('tunable', len(_tun)))
if _no_default:
    print('   these can be changed but have no default:')
    for _k in _no_default:
        print('      ' + _k)
    raise SystemExit(1)


# A function defined twice at module level is not an error in Python: the
# later one quietly replaces the earlier, and every caller of the first gets
# the second. That is how every chart range longer than a day came back as
# nothing, for days, without a word anywhere.
import re as _re2
_src = (Path(__file__).resolve().parent.parent / 'zigmon.py').read_text()
_defs = _re2.findall(r'^def (\w+)\(', _src, _re2.M)
_twice = sorted({n for n in _defs if _defs.count(n) > 1})
if _twice:
    print('module-level functions defined more than once:')
    for _n in _twice:
        print('   ' + _n)
    raise SystemExit(1)
print('%d module-level function(s), each defined once' % len(_defs))


# The same thing again, one level down: a dictionary written out in the middle
# of a function. `message_facts` said 'uptime' and 'plugs_on' twice each, and
# the first of each pair was dead text - one of them worked the figure out a
# different way, from a different attribute, and nothing ever used it. The
# named tables above are checked by hand; this looks at every dictionary
# literal in the file.
import ast as _ast   # noqa: E402
_dupes = []
for _node in _ast.walk(_ast.parse(_src)):
    if not isinstance(_node, _ast.Dict):
        continue
    _keys = [k.value for k in _node.keys
             if isinstance(k, _ast.Constant) and isinstance(k.value, str)]
    _said_twice = sorted({k for k in _keys if _keys.count(k) > 1})
    if _said_twice:
        _dupes.append((_node.lineno, _said_twice))
if _dupes:
    print('a dictionary says the same key twice - the earlier one is dead text:')
    for _line, _keys in _dupes:
        print('   line %d: %s' % (_line, ', '.join(_keys)))
    raise SystemExit(1)
print('every dictionary literal in the file says each key once')


# A value stored again and again unchanged is most of what a house writes
# down: on a real one a fortnight old, eighteen per cent of every row was a
# value that never changed once, and sixty-two per cent was a row saying what
# the row before it said. Clearing that out must leave every chart the same
# shape, which is what keeping the first and the last of each flat run does.
import threading as _threading
from pathlib import Path as _Path
import sqlite3 as _sqlite3
import time as _time
_z.load_config()
_z.CONFIG['db_file'] = '/tmp/zt-prune.db'
import os as _os
# The journal and the shared-memory file go with it. Taking only the database
# left a six-megabyte write-ahead log from the last run beside a brand-new
# file, and SQLite replayed it: rows this run never wrote, an address in the
# block history that was supposed to be gone, and one check failing for a
# reason that had nothing to do with the code it was checking.
for _ext in ('', '-wal', '-shm'):
    if _os.path.exists('/tmp/zt-prune.db' + _ext):
        _os.remove('/tmp/zt-prune.db' + _ext)
_store = _z.Storage(_z.CONFIG['db_file'])
_now = _time.time()
for _i in range(300):
    # a flat stretch, then a change, then flat again
    _value = 21.0 if _i < 120 else (22.5 if _i < 240 else 21.0)
    _store.db.execute('INSERT INTO samples (ts, device, key, value) VALUES (?,?,?,?)',
                      (_now - (300 - _i) * 60, 'test:flat', 'temperature', _value))
_store.db.commit()
_before = _store.history('test:flat', ['temperature'], 6 * 3600, 400)
_out = _store.prune(apply=True)
_after = _store.history('test:flat', ['temperature'], 6 * 3600, 400)


def _shape(rows):
    _seen = [r.get('temperature') for r in rows if r.get('temperature') is not None]
    return (min(_seen), max(_seen), len(set(_seen))) if _seen else None


assert _out['repeated_rows'] > 200, 'a flat series of 300 points lost only %d' % _out['repeated_rows']
assert _shape(_before) == _shape(_after), \
    'the chart changed shape: %r became %r' % (_shape(_before), _shape(_after))
assert len(_after) >= 4, 'a flat run kept %d points; its ends and its anchors should remain' % len(_after)
print('clearing out values stored again unchanged leaves every chart the same shape')

# Better than clearing it out afterwards: not writing it down. A reading equal
# to the last one written is skipped until the anchor is due, so a flat line
# still has points and every hour still has rows to fold - and a reading that
# differs by any amount at all is written the moment it arrives.
_z.CONFIG['sample_interval'] = 0
_z.CONFIG['sample_anchor_s'] = 900
_when = int(_time.time())
for _i in range(120):                      # an hour of a sensor reporting every 30 s
    _store._write_sample('test:anchor', _when - (120 - _i) * 30,
                         {'temperature': 21.0 if _i < 60 else 22.5})
_store.db.commit()
_kept = _store.db.execute(
    "SELECT ts, value FROM samples WHERE device='test:anchor' ORDER BY ts").fetchall()
assert len(_kept) <= 8, '120 identical-ish readings wrote %d rows' % len(_kept)
assert {r['value'] for r in _kept} == {21.0, 22.5}, 'a value was lost: %r' % {r['value'] for r in _kept}
assert any(abs(r['ts'] - (_when - 60 * 30)) < 31 and r['value'] == 22.5 for r in _kept), \
    'the moment the reading changed was not written down'
_chart = _store.history('test:anchor', ['temperature'], 2 * 3600, 400)
_seen = [r['temperature'] for r in _chart if r.get('temperature') is not None]
assert min(_seen) == 21.0 and max(_seen) == 22.5, 'the chart lost its range'
# and with it off, everything is written as it always was
_z.CONFIG['sample_anchor_s'] = 0
for _i in range(30):
    _store._write_sample('test:every', _when - (30 - _i) * 30, {'temperature': 19.0})
_store.db.commit()
_all = _store.db.execute("SELECT COUNT(*) c FROM samples WHERE device='test:every'").fetchone()['c']
assert _all == 30, 'with the anchor off only %d of 30 readings were written' % _all
_z.CONFIG['sample_anchor_s'] = 900
# ...and with a sample_interval set, where a reading inside the gap replaces
# the row rather than adding one, the memory of what is stored has to follow
# it - or a later reading equal to the value that was replaced would be
# skipped as a repeat of something no longer in the database.
_z.CONFIG['sample_interval'] = 60
_z.CONFIG['sample_anchor_s'] = 900
for _i, _v in enumerate([21.0, 21.5, 22.0]):
    _store._write_sample('test:gap', _when - (300 - _i * 10), {'t': _v})
_store._write_sample('test:gap', _when, {'t': 21.0})       # after the gap, an old value again
_store.db.commit()
_gap = [r['value'] for r in _store.db.execute(
    "SELECT value FROM samples WHERE device='test:gap' ORDER BY ts")]
assert _gap[-1] == 21.0, 'a value seen before was skipped after the gap: %r' % _gap
assert 22.0 in _gap, 'the value that replaced the others inside the gap was lost: %r' % _gap
_z.CONFIG['sample_interval'] = 30
# The chart of what the house is drawing was built from the hourly table
# alone, which is written nightly - so it ended hours ago, often before the
# whole of today, while the card beside it said what the house was drawing a
# moment ago. The two disagreed about the lights all evening.
_z.CONFIG['sample_anchor_s'] = 0
_now = int(_time.time())
for _i in range(90):                       # an hour and a half of two sockets
    _store._write_sample('plug:Test-Lamp', _now - _i * 60, {'switch.apower': 30.0 + (_i % 3)})
    _store._write_sample('plug:Test-Fridge', _now - _i * 60, {'switch.apower': 80.0})
_store.db.commit()


class _Pretend(object):
    def __init__(self, name, role):
        self.name = name
        self.cfg = {'role': role}


_daemon = _z.Daemon.__new__(_z.Daemon)
_daemon.store = _store
_daemon.plugs = {'Test-Lamp': _Pretend('Test-Lamp', 'light'),
                 'Test-Fridge': _Pretend('Test-Fridge', 'plug')}
_series = _daemon.power_series(6 * 3600)
assert _series, 'the chart is empty although the sockets reported this hour'
assert _series[-1]['ts'] >= _now - 3600, \
    'the chart ends %d minute(s) ago while the readings are current' % ((_now - _series[-1]['ts']) // 60)
assert any(r['lights'] > 0 for r in _series), 'the lights are missing from the chart'
assert any(r['sockets'] > 0 for r in _series), 'the sockets are missing from the chart'
_z.CONFIG['sample_anchor_s'] = 900
# Seven hundred thousand country ranges in one transaction hold the only lock
# this database has for as long as it takes to write them, and everything else
# - the status the page asks for twice a second, the charts, the writing down
# of readings - waits behind it. The card went away for half a minute.
_geo_rows = [(_z.pack_address('1.%d.%d.0' % (_i // 256 % 256, _i % 256))[0],
              _z.pack_address('1.%d.%d.255' % (_i // 256 % 256, _i % 256))[0], 4, 'XX')
             for _i in range(60000)]
_worst = [0.0]
_stop = _threading.Event()


def _asker():
    while not _stop.is_set():
        _at = _time.time()
        _store.get_meta('a-thing-nobody-set')
        _worst[0] = max(_worst[0], _time.time() - _at)
        _time.sleep(0.005)


_watcher = _threading.Thread(target=_asker, daemon=True)
_watcher.start()
_store.put_geo(_geo_rows)
_stop.set()
_time.sleep(0.05)
assert _store.geo_size() == 60000, 'the country list was not written whole'
assert _worst[0] < 1.0, \
    'writing the country list held the database for %.1f s - everything else waited' % _worst[0]

# Counting those ranges is remembered, not walked. The page asks for the
# status twice a second, and each ask counted seven hundred thousand country
# rows and ninety thousand list rows while holding the one lock this database
# has - 26 ms of every status build, and every other thread queued behind it.
#
# Counted by what it asks the database, not by a clock: sixty thousand rows
# here are quick enough that a stopwatch cannot tell a walk from a memory,
# and seven hundred thousand at the house are not.
_queries = [0]
_store.db.set_trace_callback(lambda _sql: _queries.__setitem__(0, _queries[0] + 1))
_store.put_geo(_geo_rows)
assert _store.geo_size() == 60000, 'the remembered count is wrong'
_queries[0] = 0
for _i in range(50):
    assert _store.geo_size() == 60000, 'the remembered count changed by itself'
assert _queries[0] == 0, \
    'counting the country list asked the database %d times; it is not remembered' % _queries[0]
# ...and it must not go stale when the list is replaced
_store.put_geo(_geo_rows[:100])
assert _store.geo_size() == 100, 'the remembered count survived the list being replaced'
_store.put_geo([])
assert _store.geo_size() == 0, 'the count still says something after the list was emptied'

_store.put_feed('atest', [(b'\x01\x02\x03\x04', b'\x01\x02\x03\xff', 4)] * 7)
_store.put_feed('btest', [(b'\x05\x06\x07\x08', b'\x05\x06\x07\xff', 4)] * 3)
assert _store.feed_sizes().get('atest') == 7 and _store.feed_sizes().get('btest') == 3, \
    'the list sizes are wrong: %r' % (_store.feed_sizes(),)
_queries[0] = 0
for _i in range(50):
    _store.feed_sizes()
assert _queries[0] == 0, \
    'counting the lists asked the database %d times; it is not remembered' % _queries[0]
_store.put_feed('atest', [(b'\x01\x02\x03\x04', b'\x01\x02\x03\xff', 4)] * 2)
assert _store.feed_sizes().get('atest') == 2, 'the remembered size survived the list being replaced'
# what is handed out must not be the daemon's own copy to scribble on
_taken = _store.feed_sizes()
_taken['atest'] = 999
assert _store.feed_sizes().get('atest') == 2, 'feed_sizes hands out the kept copy'
_store.put_feed('atest', [])
_store.put_feed('btest', [])
_store.db.set_trace_callback(None)
print('the range counts are remembered, and forgotten when the lists change')

# The readings table is its own index. As an ordinary table SQLite kept the
# whole of it a second time in the index that enforces (device, key, ts) - on
# a real house, 94 MB of readings and 88 MB of index saying the same thing.
_shape = _store.db.execute(
    "SELECT sql FROM sqlite_master WHERE type='table' AND name='samples'").fetchone()[0]
assert 'WITHOUT ROWID' in _shape.upper(), 'the readings are stored twice over'
assert not _store.db.execute(
    "SELECT 1 FROM sqlite_master WHERE type='index' AND name='samples_ts'").fetchone(), \
    'the index on ts alone is back; it cost 29 MB and saved 6 ms once a night'
# ...and a table written the old way is rebuilt on opening, not left as it was
_old = _Path('/tmp/zigmon-old-shape.db')
if _old.exists():
    _old.unlink()
_plain = _sqlite3.connect(str(_old))
_plain.executescript('''
    CREATE TABLE samples (ts INTEGER NOT NULL, device TEXT NOT NULL, key TEXT NOT NULL,
                          value REAL, PRIMARY KEY (device, key, ts));
    CREATE INDEX samples_ts ON samples (ts);
''')
for _i in range(500):
    _plain.execute('INSERT INTO samples VALUES (?,?,?,?)', (_i, 'plug:X', 'switch.apower', float(_i)))
_plain.commit()
_plain.close()
_brought = _z.Storage(str(_old))
_shape = _brought.db.execute(
    "SELECT sql FROM sqlite_master WHERE type='table' AND name='samples'").fetchone()[0]
assert 'WITHOUT ROWID' in _shape.upper(), 'an old table was left storing everything twice'
assert _brought.db.execute('SELECT COUNT(*) FROM samples').fetchone()[0] == 500, \
    'rebuilding the readings table lost rows'
assert _brought.db.execute('SELECT value FROM samples WHERE device=? AND key=? AND ts=?',
                           ('plug:X', 'switch.apower', 499)).fetchone()[0] == 499.0, \
    'and what it kept is not what was in it'
_brought.db.close()
_old.unlink()
# ...and a rebuild that was killed part way through loses nothing. The schema
# makes an empty `samples` again on the next start, so the readings sit in
# samples_slim with nothing reading them unless they are brought back.
for _shape, _extra in (('WITHOUT ROWID', 0), ('', 1)):
    _half = _Path('/tmp/zigmon-half-done.db')
    if _half.exists():
        _half.unlink()
    _hdb = _sqlite3.connect(str(_half))
    _hdb.executescript(
        'CREATE TABLE samples_slim (ts INTEGER NOT NULL, device TEXT NOT NULL, key TEXT NOT NULL,'
        ' value REAL, PRIMARY KEY (device, key, ts)) %s;'
        'CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);' % _shape)
    if _extra:
        _hdb.execute('CREATE TABLE samples (ts INTEGER NOT NULL, device TEXT NOT NULL,'
                     ' key TEXT NOT NULL, value REAL, PRIMARY KEY (device, key, ts))')
        _hdb.execute("INSERT INTO samples VALUES (9999,'plug:X','switch.apower',1.0)")
    for _i in range(300):
        _hdb.execute('INSERT INTO samples_slim VALUES (?,?,?,?)',
                     (_i, 'plug:X', 'switch.apower', float(_i)))
    _hdb.commit()
    _hdb.close()
    _back = _z.Storage(str(_half))
    _n = _back.db.execute('SELECT COUNT(*) FROM samples').fetchone()[0]
    assert _n == 300 + _extra, 'a half-done rebuild lost rows: %d of %d' % (_n, 300 + _extra)
    assert not _back.db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='samples_slim'").fetchone(), \
        'the half-built table was left behind'
    assert 'WITHOUT ROWID' in _back.db.execute(
        "SELECT sql FROM sqlite_master WHERE name='samples'").fetchone()[0].upper(), \
        'and the table is still storing everything twice'
    _back.db.close()
    _half.unlink()
print('a rebuild killed part way through loses nothing on the next start')
# What is kept ABOUT an address - which list knew it, what Suricata said - is
# two rows apiece, written for every alert and not only for a block, and
# nothing took them away. A busy week is thousands, all held in memory too.
_store.set_meta('blocked_ids_51.0.0.1', 'ET something')
_store.set_meta('ids_about_51.0.0.1', '{"sid":1}')
_store.set_meta('blocked_feed_51.0.0.1', 'firehol1')
_store.set_meta('pin_tries', '3')
_store.block('51.0.0.1', None, 'x', auto=True)
_store.flush()
_fold = lambda: (_store.db.execute("DELETE FROM meta WHERE key='aggregated_to'"),
                 _store.db.commit(), _store.aggregate())[2]
_fold()
assert _store.get_meta('blocked_ids_51.0.0.1'), 'what was kept about an address still on the list went'
_store.unblock('51.0.0.1')
_fold()
assert _store.get_meta('blocked_ids_51.0.0.1'), \
    'it went while the history still names the address'
_store.db.execute('DELETE FROM block_events')
_store.db.commit()
_fold()
assert not _store.get_meta('blocked_ids_51.0.0.1'), \
    'nothing can ask about that address any more, and what was kept about it is still there'
assert not _store.get_meta('ids_about_51.0.0.1'), 'what Suricata said was left behind'
assert not _store.get_meta('blocked_feed_51.0.0.1'), 'which list knew it was left behind'
assert _store.get_meta('pin_tries') == '3', 'the fold took something that is not about an address'
print('what is kept about an address goes when nothing can ask about it again')
print('the readings are stored once, and a table written the old way is rebuilt on opening')
print('the country list is written in pieces, so nothing else waits on it')
print('the chart of what the house is drawing reaches the hour it is in')
print('a reading that has not changed is not written twice, and the one that changes is written at once')

