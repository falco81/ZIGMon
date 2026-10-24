#!/usr/bin/env python3
"""Every switch in Settings, tried both ways, watching what the daemon does.

The debug switch was saved, shown, and ignored for its whole life, because
nothing ever checked that turning it on changed anything. This does: it puts
the daemon in a state where the setting matters, flips it, and looks at the
behaviour rather than at the stored value.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import zigmon                                                    # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': '/tmp/zigmon-switch-check.db', 'api_port': 19049,
                      'token_file': '/tmp/zigmon-switch-token', 'log_file': '/tmp/zigmon-switch.log',
                      'log_to_journal': False, 'mqtt_host': '127.0.0.1', 'mqtt_port': 1883,
                      'mqtt_tls': False})

# A stale journal beside a fresh database is not this run's data: SQLite
# replays it, and a check then fails over rows the run never wrote. Both
# sidecars go with the file.
import os as _dbclean
for _ext in ('', '-wal', '-shm'):
    try:
        _dbclean.remove(zigmon.CONFIG['db_file'] + _ext)
    except OSError:
        pass
d = zigmon.Daemon()
time.sleep(1.0)
bad = []


def check(key, when_on, when_off, what):
    """when_on/when_off: a callable returning what the daemon did."""
    zigmon.CONFIG[key] = 1
    on = when_on()
    zigmon.CONFIG[key] = 0
    off = when_off()
    ok = on != off
    print('  %-24s %s' % (key, 'changes what happens' if ok else '<-- SAME EITHER WAY'))
    if not ok:
        bad.append('%s: %s' % (key, what))


def wrote_debug():
    before = Path(zigmon.CONFIG['log_file']).stat().st_size if Path(zigmon.CONFIG['log_file']).exists() else 0
    zigmon.log('a line written for the check', 'debug')
    # lines are written by a thread of their own since 5.16, so nothing on
    # its way to a light waits on the disk: wait for this one to land
    getattr(zigmon, 'log_drain', lambda *a: True)(3.0)
    after = Path(zigmon.CONFIG['log_file']).stat().st_size if Path(zigmon.CONFIG['log_file']).exists() else 0
    return after > before


print('switches, tried both ways:')
check('debug', wrote_debug, wrote_debug, 'the trace is meant to write every command to the log')

# the watchdog: with it off, nothing is ever reported as quiet
d.store.upsert_device({'id': '0xquiet', 'name': 'Probe-Thermo', 'source': 'zigbee', 'kind': 'Thermometer',
                       'vendor': 'test', 'model': 'probe', 'last_seen': int(time.time()) - 40 * 3600,
                       'exposes': {'temperature': {'access': 1, 'type': 'numeric', 'label': 'Temperature',
                                                   'unit': 'C', 'category': '', 'values': None,
                                                   'min': None, 'max': None}}})


def watchdog_ran():
    said = []
    keep = d.store.add_event
    d.store.add_event = lambda kind, detail='', level='info', device=None, ts=None: (
        said.append(kind) if kind == 'device' else None) or keep(kind, detail, level, device, ts)
    d._silent_since = {}
    d.check_watchdogs()
    d.store.add_event = keep
    return bool(said)


check('watchdog', watchdog_ran, watchdog_ran, 'with it off nothing should be reported as having gone quiet')

def queued_when_it_could_not_go():
    zigmon.CONFIG.update({'sms_enabled': True, 'sms_host': '127.0.0.1', 'sms_port': 1,
                          'sms_api': 'rest', 'sms_timeout_s': 1})
    d.store.set_meta('sms_outbox', '[]')
    d.sms_send('+420000000000', 'a line for the check', why='alert')
    return bool(d.sms_outbox())


check('sms_queue', queued_when_it_could_not_go, queued_when_it_could_not_go,
      'with it on, a message the gateway would not take is kept and tried again')


def told_about_a_stranger():
    # catch the call itself: the queue is drained by a worker, so looking at
    # it a moment later is a race and the check would pass or fail by luck
    caught = []
    keep = d.notify
    d.notify = lambda *a, **k: caught.append(a[0] if a else '')
    d.notify_sent = {}
    try:
        d.sms_handle('4603', 'a line from a number nobody knows %d' % time.time())
    finally:
        d.notify = keep
    return bool(caught)


zigmon.CONFIG['sms_reply'] = False
before = zigmon.CONFIG.get('sms_stranger_alert')
zigmon.CONFIG['sms_stranger_alert'] = 'notify'
said_on = told_about_a_stranger()
zigmon.CONFIG['sms_stranger_alert'] = 'event'
said_off = told_about_a_stranger()
zigmon.CONFIG['sms_stranger_alert'] = before
print('  %-24s %s' % ('sms_stranger_alert',
                      'changes what happens' if (said_on and not said_off) else '<-- SAME EITHER WAY'))
if not (said_on and not said_off):
    bad.append('sms_stranger_alert: notify should say something, event should only write it down')

# The switch that says which roads an automatic message takes. A device gone
# quiet used to text whatever it was set to, because only alerts about a
# device went past these switches on their way out.
import json as _json


class _Watched(list):
    def __init__(self, seen):
        list.__init__(self)
        self.seen = seen

    def append(self, item):
        self.seen.append(item)
        list.append(self, item)


def _roads(sms_on):
    saved = _json.loads(d.store.get_meta('notify') or '{}')
    saved['channels'] = dict(saved.get('channels') or {}, sms=bool(sms_on), ntfy=True, telegram=True)
    d.store.set_meta('notify', _json.dumps(saved))


def _texted():
    seen = []
    d.notify_queue = _Watched(seen)
    d.notify_sent = {}
    d._silent_since = {}
    d.check_watchdogs()
    time.sleep(0.2)
    return any(x.get('sms') for x in seen)


d.store.upsert_device({'id': '0xquiet', 'name': 'Probe-Thermo', 'source': 'zigbee', 'kind': 'Thermometer',
                       'vendor': 'test', 'model': 'probe', 'last_seen': int(time.time()) - 40 * 3600,
                       'exposes': {}})
zigmon.CONFIG['watchdog'] = 1
def _kind(offline):
    saved = _json.loads(d.store.get_meta('notify') or '{}')
    saved['offline'] = bool(offline)
    d.store.set_meta('notify', _json.dumps(saved))


def _told():
    seen = []
    d.notify_queue = _Watched(seen)
    d.notify_sent = {}
    d._silent_since = {}
    d.check_watchdogs()
    time.sleep(0.2)
    return bool(seen)


_kind(True)
_roads(True)
_on = _texted()
_roads(False)
_off = _texted()
print('  %-24s %s' % ('notify by text', 'changes what happens' if (_on and not _off) else '<-- SAME EITHER WAY'))
if not (_on and not _off):
    bad.append('the SMS road: a device gone quiet must go by text only when that road is on')

# and the switch that says which kinds are worth hearing about at all
_roads(True)
_kind(True)
_kind_on = _told()
_kind(False)
_kind_off = _told()
_kind(True)
print('  %-24s %s' % ('tell me about quiet ones',
                      'changes what happens' if (_kind_on and not _kind_off) else '<-- SAME EITHER WAY'))
if not (_kind_on and not _kind_off):
    bad.append('"a device going quiet": with it off nothing should be sent about one')

# Each kind of system message may take its own road, or stay in the events.
def _systems(mapping):
    saved = _json.loads(d.store.get_meta('notify') or '{}')
    saved['systems'] = mapping
    saved['channels'] = dict(saved.get('channels') or {}, ntfy=True, telegram=True, sms=False)
    d.store.set_meta('notify', _json.dumps(saved))


def _sent(about):
    seen = []
    d.notify_queue = _Watched(seen)
    d.notify_sent = {}
    d.notify('a line for the check %d' % time.time(), 'warn', about=about)
    time.sleep(0.15)
    return seen


_systems({})
_plain = _sent('quiet')
_systems({'quiet': {'roads': 'sms'}})
_by_text = _sent('quiet')
_systems({'quiet': {'off': True}})
_silent = _sent('quiet')
_systems({})
_ok = (_plain and not _plain[0].get('sms')
       and _by_text and _by_text[0].get('sms') and not _by_text[0].get('ntfy')
       and not _silent)
print('  %-24s %s' % ('an alert kind\'s own road', 'changes what happens' if _ok else '<-- SAME EITHER WAY'))
if not _ok:
    bad.append('a system alert given its own roads must take them, and "off" must send nothing')

# "Hush the alerts for an hour" has to mean every alert. It used to hush only
# the ones about a device, and the rest went on buzzing.
_systems({})
d.store.set_meta('quiet_until', '0')
_loud = _sent('quiet')
d.store.set_meta('quiet_until', str(int(time.time() + 600)))
_hushed = _sent('quiet')
d.store.set_meta('quiet_until', '0')
print('  %-24s %s' % ('hushing the house', 'changes what happens' if (_loud and not _hushed)
                      else '<-- SAME EITHER WAY'))
if not (_loud and not _hushed):
    bad.append('hushing the house must hold back the messages that are not about a device too')

print('')
if bad:
    print('switches that do nothing:')
    for line in bad:
        print('   ' + line)
    raise SystemExit(1)
print('every switch checked changes what the daemon does')
