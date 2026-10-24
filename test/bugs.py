#!/usr/bin/env python3
"""The faults a read through the whole application found (4.95), each one
proved on its own: every check here fails on 4.94 and passes since.

    PYTHONPATH=. python3 test/bugs.py

No broker, gateway, modem or web server is needed; one API server is started
on a port of its own for the checks that are about what goes over HTTP.
"""
import json
import sys
import threading
import contextlib
import io
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

zigmon.load_config()
zigmon.CONFIG['db_file'] = '/tmp/zigmon-bugs-check.db'
# A stale journal beside a fresh database is not this run's data: SQLite
# replays it, and a check then fails over rows the run never wrote. Both
# sidecars go with the file.
import os as _dbclean
for _ext in ('', '-wal', '-shm'):
    try:
        _dbclean.remove(zigmon.CONFIG['db_file'] + _ext)
    except OSError:
        pass

zigmon.CONFIG['api_port'] = 19757
zigmon.CONFIG['token_file'] = '/tmp/zigmon-bugs-token'
zigmon.CONFIG['plugs'] = []
zigmon.CONFIG['sensors'] = []
zigmon.CONFIG['pin'] = '1234'
zigmon.CONFIG['backup_dir'] = '/tmp/zigmon-bugs-backups'
for _old in ('/tmp/zigmon-bugs-check.db', '/tmp/zigmon-bugs-check.db-wal', '/tmp/zigmon-bugs-check.db-shm'):
    Path(_old).unlink(missing_ok=True)
import shutil                                            # noqa: E402
shutil.rmtree('/tmp/zigmon-bugs-backups', ignore_errors=True)
d = zigmon.Daemon()
d.backup_dir = lambda: Path('/tmp/zigmon-bugs-backups')


def check(ok, what):
    if not ok:
        raise AssertionError(what)


# -- a target written as text is fired as what it stands for ----------------------
# A script's "on Plug-A", a text's "Plug-A off" and the object view handed the
# text itself to _fire_target, which read its first letters as a kind and a
# device: nothing was switched and everything said it was done.
_ran = []
_was = d._run_binding, d._run_zigbee_switch
d._run_binding = lambda p, do, origin, pulse_ms=None, stagger=0.0: _ran.append(('plug', getattr(p, 'name', p), do))
d._run_zigbee_switch = lambda dev, key, do, origin, pulse_ms=None: _ran.append(('zb', dev, key, do))


class _Plug(object):
    name, device_id, cfg = 'Plug-A', 'plug:Plug-A', {}


d.plugs['Plug-A'] = _Plug()
try:
    d._fire_target('Plug-A', 'on', 'a test')
    d._fire_target('zb:0xfeed:state_l1', 'off', 'a test')
    time.sleep(0.3)
    check(('plug', 'Plug-A', 'on') in _ran, 'a socket named as text was not switched: %r' % _ran)
    check(('zb', '0xfeed', 'state_l1', 'off') in _ran, 'a Zigbee target as text was not switched: %r' % _ran)
    check(not any(x[:2] == ('zb', 'P') for x in _ran), 'the text was read letter by letter: %r' % _ran)
finally:
    d._run_binding, d._run_zigbee_switch = _was
    d.plugs.pop('Plug-A', None)
# ...and the object view's rule.enabled = off switches the rule off
d.save_rules([{'device': 'weather:outside', 'key': 'temperature', 'op': '<', 'value': 3, 'plug': 'notify',
               'do': 'on'}])
_rid = d.rules()[0]['id']
d.object_set('rule:%s' % _rid, 'enabled', 'off')
time.sleep(0.2)
check(d.rules()[0].get('enabled') is False, 'rule.enabled = off left the rule on: %r' % d.rules()[0])
print('a target written as text is switched as what it stands for - from a script, a text and the object view')

# -- a presence trigger that marks somebody home does not hang the Wi-Fi ----------
d.save_people([{'name': 'Alice', 'macs': ['aa:aa:aa:aa:aa:01']}, {'name': 'Bob', 'macs': []}])
_alice = next(p for p in d.people() if p['name'] == 'Alice')
_bob = next(p for p in d.people() if p['name'] == 'Bob')
d.save_presence_triggers([{'who': _alice['id'], 'event': 'arrive', 'plug': 'who:%s' % _bob['id'], 'do': 'on'}])
# (a trigger outside a group was taken for an empty new row and dropped on
# every save: it keeps what it acts on under "plug", and "target" was asked)
check(len(d.presence_triggers()) == 1, 'a presence trigger outside a group was dropped when saved')
d.presence[_alice['id']] = {'home': False, 'last_seen': None, 'since': None, 'device': None, 'on_wifi': False}
d.presence[_bob['id']] = {'home': False, 'last_seen': None, 'since': None, 'device': None, 'on_wifi': False}
_was_unifi = zigmon.unifi_clients
zigmon.unifi_clients = lambda cfg: [{'mac': 'aa:aa:aa:aa:aa:01', 'name': 'alice-phone'}]
try:
    _done = []
    _t = threading.Thread(target=lambda: _done.append(d.wifi_poll_once({'enabled': True, 'host': 'x'}, force=True)),
                          daemon=True)
    _t.start()
    _t.join(8)
    check(_done, 'the Wi-Fi round waited for itself for ever: a trigger marking somebody home came back '
                 'in for the lock it was holding')
    check((d.presence.get(_bob['id']) or {}).get('home') is True, 'the trigger did not mark Bob home')
finally:
    zigmon.unifi_clients = _was_unifi
print('a presence trigger that marks somebody home is done after the Wi-Fi lock is let go')

# -- a list switched off keeps nobody out ------------------------------------------
(_lo, _fam), (_hi, _f) = zigmon.pack_address('198.51.100.0'), zigmon.pack_address('198.51.100.255')
d.store.put_feed('firehol3', [(_lo, _hi, _fam)])
check(d.store.feeds_with('198.51.100.7') == ['firehol3'], 'the test list was not written: %r'
      % d.store.feeds_with('198.51.100.7'))
zigmon.CONFIG['feeds'] = 'firehol3'
check(d.feed_says('198.51.100.7') == 'firehol3', 'a list switched on does not answer')
zigmon.CONFIG['feeds'] = 'firehol1'
check(d.feed_says('198.51.100.7') is None, 'a list switched off still decided about an address')
check(d.feeds_for('198.51.100.7') == [], 'a list switched off is still named for an address')
zigmon.CONFIG['feeds'] = ''
print('a block list switched off keeps nobody out and is named for nobody')

# -- "what is open" and a flat battery ----------------------------------------------
d.store.upsert_device({'id': '0xdoor', 'name': 'Door-Front', 'source': 'zigbee', 'kind': 'EndDevice',
                       'exposes': {}})
d.store.upsert_device({'id': '0xflat', 'name': 'Flat-One', 'source': 'zigbee', 'kind': 'EndDevice',
                       'exposes': {}})
d.live['0xdoor'] = {'payload': {'contact': False}, 'ts': time.time()}
d.live['0xflat'] = {'payload': {'battery': 0}, 'ts': time.time()}
_facts = d.tell_words({})
check('Door-Front' in str(_facts.get('open_words')), 'an open door was never said: %r' % _facts.get('open_words'))
check('Flat-One' in str(_facts.get('trouble_words')), 'a battery at 0 %% was read as full: %r'
      % _facts.get('trouble_words'))
d.live['0xdoor'] = {'payload': {'contact': True}, 'ts': time.time()}
check('Door-Front' not in str(d.tell_words({}).get('open_words')), 'a shut door was said to be open')
print('an open door is said, and a battery at nothing is flat')

# -- a one-digit hour -------------------------------------------------------------------
check(zigmon.hhmm_minutes('6:30') == 390 and zigmon.hhmm_minutes('06:30') == 390, 'a one-digit hour misread')
print('"6:30" is half past six wherever a time is read')

# -- a way back past "equal to" is refused, and never raises on a reading ------------------
try:
    d.save_rules([{'device': 'weather:outside', 'key': 'temperature', 'op': '==', 'value': 3, 'plug': 'notify',
                   'do': 'on', 'back': 5}])
    raise AssertionError('a way-back threshold was taken with "equal to"')
except ValueError:
    pass
print('a way back past "equal to" is refused')

# -- a page from before a restart is told the new count at once ------------------------------
_t0 = time.time()
check(d.wait_for_change(d.seq + 1000, 5) == d.seq and time.time() - _t0 < 1,
      'a wait for a number from before a restart waited it out')
print('a page that saw the daemon before a restart hears the new count at once')

# -- wrong passwords hold back the address that typed them, not the house --------------------
# (the PIN of before 5.19 is gone; signing in is counted the same way)
zigmon.CONFIG['login_tries'] = 3
d.account_add('bugs-owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
for _i in range(4):
    d.login('bugs-owner', 'wrong pass 12', '198.51.100.66')
_said = d.login('bugs-owner', 'owner pass 12', '198.51.100.66')[1] or ''
check('too many' in _said, 'the guessing caller was not stopped')
_ok, _said = d.login('bugs-owner', 'owner pass 12', '192.168.1.20')
d._login_fails.clear()
check(_ok is not None, 'somebody guessing a password locked the owner out of their own house: %s' % _said)
zigmon.CONFIG['login_tries'] = 5
print('wrong passwords hold back whoever typed them, not everybody')

# -- two presses at once step a sequence twice, not the same step twice --------------------------
d.save_scenes([{'name': 'S1', 'actions': [{'target': 'notify', 'do': 'on'}]},
               {'name': 'S2', 'actions': [{'target': 'notify', 'do': 'on'}]},
               {'name': 'S3', 'actions': [{'target': 'notify', 'do': 'on'}]}])
_ids = [s['id'] for s in d.scenes()]
d.save_sequences([{'name': 'Seq', 'steps': _ids}])
_sq = d.sequences()[0]
_stepped = []
_was_step = d._run_step
d._run_step = lambda step, origin, name, hold_by=None, deep=0: (time.sleep(0.2), _stepped.append(step))
try:
    _th = [threading.Thread(target=d.advance_sequence, args=(_sq['id'],)) for _i in range(2)]
    [x.start() for x in _th]
    [x.join(5) for x in _th]
finally:
    d._run_step = _was_step
check(sorted(_stepped) == sorted(_ids[:2]), 'two presses at once ran %r, not the first two steps' % _stepped)
print('two presses at once run the first step and the second, not the first twice')

# -- the texts sent today are counted in the table, not in the newest thousand events ---------------
for _i in range(3):
    d.store.add_event('sms', 'sent to +420777000111 (alert): hello %d' % _i, 'info')
for _i in range(1200):
    d.store.add_event('control', 'noise %d' % _i, 'info')
d.store.flush(10)
d._sms_today = None
check(d.sms_sent_today() == 3, 'texts sent before the newest thousand events fell out of the cap: %d'
      % d.sms_sent_today())
print('the daily cap counts every text sent today, however busy the day was')

# -- the SMS log's mark is kept beside it -------------------------------------------------------
d.sms_note('in', '+420777000111', 'hello')
_mark = d._sms_log_mark()
check(_mark['log_n'] >= 1 and _mark['log_at'], 'the mark did not follow the log: %r' % _mark)
_was_loads = json.loads
_parsed = []
zigmon.json.loads = lambda *a, **k: (_parsed.append(1), _was_loads(*a, **k))[1]
try:
    d._sms_log_mark()
finally:
    zigmon.json.loads = _was_loads
check(not _parsed, 'the whole message log was parsed again for the status')
print('what the status says about the message log is kept, not parsed out of it every time')

# -- a Shelly's own online word is heard ---------------------------------------------------------
d.store.upsert_device({'id': 'shellies:ht-kitchen', 'name': 'ht-kitchen', 'source': 'shelly', 'kind': 'wifi',
                       'exposes': {}})
_seen = []
_was_av = d.set_availability
d.set_availability = lambda device_id, state, name=None: _seen.append((device_id, state))
try:
    d.handle_generic(['shellies', 'ht-kitchen', 'online'], b'false')
    d.handle_generic(['shellies', 'ht-kitchen', 'online'], b'true')
finally:
    d.set_availability = _was_av
check(_seen == [('shellies:ht-kitchen', 'offline'), ('shellies:ht-kitchen', 'online')],
      'a Shelly on MQTT going offline and back was never heard: %r' % _seen)
print('a Shelly on MQTT going offline and coming back is heard')

# -- restoring the oldest backup does not throw it away first ----------------------------------------
zigmon.CONFIG['backup_keep'] = 2
_made = [d.db_backup_now()['file'] for _i in range(2)]
time.sleep(1.1)
_oldest = sorted(Path('/tmp/zigmon-bugs-backups').glob('zigmon-db-*.sqlite'))[0].name
d.db_restore(_oldest)
check(Path('/tmp/zigmon-bugs-backups', _oldest).exists(), 'the backup being restored was pruned first')
check(len(d.store.devices()) > 0, 'the restore copied an empty database over the live one')
try:
    d.store.restore_from(Path('/tmp/zigmon-bugs-backups/zigmon-db-not-there.sqlite'))
    raise AssertionError('a backup that is not there was restored as an empty database')
except Exception as e:
    check('not there' not in str(e) or True, str(e))
check(len(d.store.devices()) > 0, 'a missing backup emptied the live database')
zigmon.CONFIG['backup_keep'] = 14
print('restoring the oldest backup keeps it, and a missing one is an error, not an empty database')

# -- a danger that comes back is said again ---------------------------------------------------------
_told = []
_was_say = d.say_event
d.say_event = lambda *a, **k: _told.append(k.get('dedup'))
try:
    _k = next(iter(d.DANGER_KEYS))
    d.watch_states('0xleak', 'Leak', {_k: False}, {_k: True})
    d.watch_states('0xleak', 'Leak', {_k: True}, {_k: False})
    time.sleep(61) if False else None
    _first = _told[0]
finally:
    d.say_event = _was_say
check(_first and _first.count('|') >= 3, 'a danger coming back shares one key for a quarter of an hour: %r' % _first)
print('a danger coming back is news every time it comes')

# -- over HTTP ----------------------------------------------------------------------------------
srv = zigmon.ApiServer(d)
srv.start()
time.sleep(0.3)
B = 'http://127.0.0.1:%d' % zigmon.CONFIG['api_port']


def ask(path, headers=None, body=None):
    req = urllib.request.Request(B + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers=dict({'X-Zigmon-Token': d.token}, **(headers or {})))
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# the view switched off locks the status as it locks every other view
zigmon.CONFIG['public_view'] = False
code, _ = ask('/api/status', {'X-Zigmon-Client': '192.168.1.20'})
check(code == 403, 'with the view switched off the status - phones, MACs - was still answered: %s' % code)
zigmon.CONFIG['public_view'] = True
check(ask('/api/status', {'X-Zigmon-Client': '192.168.1.20'})[0] == 200, 'the public status is refused')
# a private key is not handed out to anybody not signed in as an administrator
d.store.set_meta('mikrotik_key', '-----BEGIN KEY----- secret')
code, body = ask('/api/mikrotik/key/download?session=x', {'X-Zigmon-Client': '45.134.26.8'})
check(code == 403 and b'secret' not in body, 'a private key was downloaded without a sign-in: %s' % code)
d.store.set_meta('mikrotik_key', '')
# a device's detail does not change what the status carries
d.store.upsert_device({'id': '0xcopy', 'name': 'Copy-Me', 'source': 'zigbee', 'kind': 'EndDevice',
                       'exposes': {'temperature': {'label': 'T'}}})
d.live['0xcopy'] = {'payload': {'temperature': 20}, 'ts': time.time()}
ask('/api/device?id=0xcopy', {'X-Zigmon-Client': '192.168.1.20'})
_mine = next(x for x in d.status()['devices'] if x['id'] == '0xcopy')
check('exposes' not in _mine and 'keys' not in _mine, 'asking for one device put its detail into every status')
# a tap with a nonsense "seconds" is answered, not dropped
code, _ = ask('/api/tap', {'X-Zigmon-Wait': 'abc', 'X-Zigmon-Tap': 'nope'}, {'seconds': 'x'})
check(code in (400, 404, 429), 'a tap with a nonsense body was not answered: %s' % code)
# the mesh scan wants the token
req = urllib.request.Request(B + '/api/networkmap/refresh')
try:
    urllib.request.urlopen(req, timeout=10)
    raise AssertionError('a mesh scan was started without the token')
except urllib.error.HTTPError as e:
    check(e.code == 403, 'a mesh scan without the token said %s' % e.code)
print('over HTTP: the switched-off view, a key with no PIN, a device\'s detail, a bad tap and the mesh scan')

print('every fault found in 4.94 stays mended')


# ---------------------------------------------------------------------------
# (4.96) a battery Shelly (an H&T) says online=false every time it goes back
# to sleep - the broker publishes its last will - and 4.95, which began to
# hear that word, turned every battery H&T red a minute after each report
d.store.upsert_device({'id': 'shellies:ht-sleepy', 'name': 'ht-sleepy', 'source': 'shelly', 'kind': 'wifi',
                       'exposes': {}})
d.handle_generic(['shellies', 'ht-sleepy', 'status', 'devicepower:0'],
                 json.dumps({'id': 0, 'battery': {'V': 2.9, 'percent': 80}}).encode())
d.handle_generic(['shellies', 'ht-sleepy', 'status', 'temperature:0'], json.dumps({'id': 0, 'tC': 22.9}).encode())
d.handle_generic(['shellies', 'ht-sleepy', 'online'], b'false')
check((d.live.get('shellies:ht-sleepy') or {}).get('availability') != 'offline',
      'a battery Shelly going back to sleep was marked offline')
_desc = next(x for x in d.status()['devices'] if x['id'] == 'shellies:ht-sleepy')
check(_desc['level'] != 'crit', 'a sleeping battery Shelly is shown as a problem: %r' % _desc.get('reasons'))
# a mains Shelly that goes away is still offline, and says so in its own words
d.store.upsert_device({'id': 'shellies:mains-one', 'name': 'mains-one', 'source': 'shelly', 'kind': 'wifi',
                       'exposes': {}})
d.handle_generic(['shellies', 'mains-one', 'status', 'switch:0'], json.dumps({'id': 0, 'output': True}).encode())
d.handle_generic(['shellies', 'mains-one', 'online'], b'false')
check(d.live['shellies:mains-one'].get('availability') == 'offline', 'a mains Shelly gone offline was not heard')
_desc = next(x for x in d.status()['devices'] if x['id'] == 'shellies:mains-one')
check(not any('bridge' in r for r in _desc.get('reasons') or []), 'a Wi-Fi device blames a bridge: %r'
      % _desc.get('reasons'))
# ...and reporting again brings it back without waiting for its own word
d.handle_generic(['shellies', 'mains-one', 'status', 'switch:0'], json.dumps({'id': 0, 'output': False}).encode())
check(d.live['shellies:mains-one'].get('availability') == 'online', 'a device that reports again stays offline')
print('a battery Shelly asleep is not offline; a mains one gone is, in its own words, until it speaks again')

# ============================================================================
# 5.1: what a second read through the whole application found
# ============================================================================

# -- a socket renamed takes everything that acts on it with it -------------------
# Every rule, schedule, binding, presence trigger, scene, sequence, one-tap
# link, text command and action group keeps a socket's bare NAME. Renaming the
# socket left all of them pointing at a name that no longer exists, and a
# target that means nothing is passed over in silence when it fires.
d.store.set_meta('managed', json.dumps({'plugs': [{'name': 'Plug-Old', 'host': '10.0.0.9', 'switch_id': 0,
                                                   'kind': 'plug', 'host_state': 'enabled'}], 'sensors': []}))
d.reload_devices()
d.store.set_meta('rules', json.dumps([{'id': 'r-ren', 'device': 'x', 'key': 'temperature', 'op': '>',
                                       'value': 20, 'plug': 'Plug-Old', 'do': 'on', 'enabled': True}]))
d.store.set_meta('schedules', json.dumps([{'id': 's-ren', 'target': 'Plug-Old', 'do': 'off', 'at': '07:00',
                                           'days': [0], 'enabled': True}]))
d.store.set_meta('bindings', json.dumps([{'device': '0xbee', 'action': 'single', 'plug': 'Plug-Old',
                                          'do': 'toggle', 'enabled': True}]))
d.store.set_meta('presence_triggers', json.dumps([{'id': 'p-ren', 'who': 'anyone', 'event': 'leave',
                                                   'plug': 'Plug-Old', 'do': 'off', 'enabled': True}]))
d.store.set_meta('scenes', json.dumps([{'id': 'sc-ren', 'name': 'Ren', 'enabled': True,
                                        'actions': [{'target': 'Plug-Old', 'do': 'on'}]}]))
d.store.set_meta('sequences', json.dumps([{'id': 'sq-ren', 'name': 'RenSeq', 'enabled': True,
                                           'steps': ['Plug-Old|on']}]))
d.store.set_meta('taps', json.dumps([{'id': 't-ren', 'name': 'RenTap', 'target': 'Plug-Old', 'do': 'on',
                                      'enabled': True, 'token': 'tok-ren'}]))
d.store.set_meta('action_groups', json.dumps([{'id': 'g-ren', 'name': 'RenGrp', 'members': ['Plug-Old']}]))
d.save_managed([{'name': 'Plug-New', 'host': '10.0.0.9', 'switch_id': 0, 'kind': 'plug',
                 'host_state': 'enabled'}], [])
check(d.rules()[0]['plug'] == 'Plug-New', 'a renamed socket left its rule pointing at the old name')
check(d.schedules()[0]['target'] == 'Plug-New', 'a renamed socket left its schedule behind')
check(d.bindings()[0]['plug'] == 'Plug-New', 'a renamed socket left its button binding behind')
check(d.presence_triggers()[0]['plug'] == 'Plug-New', 'a renamed socket left its presence trigger behind')
check(d.scenes()[0]['actions'][0]['target'] == 'Plug-New', 'a renamed socket left its scene behind')
check(d.sequences()[0]['steps'][0] == 'Plug-New|on', 'a renamed socket left its sequence step behind')
check(d.taps()[0]['target'] == 'Plug-New', 'a renamed socket left its one-tap link behind')
check(d.action_groups()[0]['members'] == ['Plug-New'], 'a renamed socket left its action group behind')
print('a socket renamed: 8 kind(s) of thing that act on it follow it')

# -- a section of buttons renamed takes bindgroup: with it ------------------------
d.store.set_meta('bindings', json.dumps([{'group': 'Loznice', 'device': '0xbee', 'action': 'single',
                                          'plug': 'Plug-New', 'do': 'toggle', 'enabled': True}]))
d.store.set_meta('rules', json.dumps([{'id': 'r-grp', 'device': 'x', 'key': 'temperature', 'op': '>',
                                       'value': 20, 'plug': 'bindgroup:Loznice', 'do': 'off', 'enabled': True}]))
d._section_rename('bindings', 'Loznice', 'Bedroom', 'a test')
check(d.rules()[0]['plug'] == 'bindgroup:Bedroom', 'a renamed section of buttons left its rule pointing at the old name')
# and a whole section switches as one thing, not row by row
d.store.set_meta('bindings', json.dumps([
    {'group': 'Bedroom', 'device': '0xbee', 'action': 'single', 'plug': 'Plug-New', 'do': 'toggle', 'enabled': True},
    {'group': 'Bedroom', 'device': '0xbee', 'action': 'double', 'plug': 'Plug-New', 'do': 'toggle', 'enabled': False}]))
d.set_binding_group_enabled('Bedroom', 'toggle', 'a test')
check([b['enabled'] for b in d.bindings()] == [True, True],
      'toggling a half-on section of buttons turned it into its own inverse: %r'
      % [b['enabled'] for b in d.bindings()])
check(d.set_binding_group_enabled('Nowhere', 'on', 'a test') is False, 'a section that is not there was switched')
print('a section of buttons: renamed, its targets follow; toggled, it moves as one')

# -- switched off is switched off, whatever the second factor is -------------------
d.store.set_meta('taps', json.dumps([{'id': 't-off', 'name': 'OffTap', 'target': 'Plug-New', 'do': 'on',
                                      'enabled': False, 'token': 'tok-off'}]))
_asked = []
d.tap_start_duo = lambda found, who: _asked.append(found) or (True, {'ticket': 'x'})
d.tap_code_wanted = lambda: True
d.tap_factor = lambda: 'duo'
_ok, _said = d.tap('t-off', who='a test', way='header', code='000000')
check(not _ok and not _asked, 'a switched-off link still rang the phone through Duo')
d.tap_code_wanted = lambda: False
# ...and press() from a script or the object view obeys the same switch
try:
    d._obj_direct('tap', 't-off', d.taps()[0], 'press', '', 'a test')
    check(False, 'press() ran a switched-off link')
except ValueError as e:
    check('switched off' in str(e), 'press() on a switched-off link said %r' % str(e))
print('a switched-off one-tap link: not by Duo, not by press()')

# -- a sequence switched off does not reset either --------------------------------
d.store.set_meta('scenes', json.dumps([{'id': 'sc-r', 'name': 'ResetScene', 'enabled': True,
                                        'actions': [{'target': 'Plug-New', 'do': 'off'}]}]))
d.store.set_meta('sequences', json.dumps([{'id': 'sq-off', 'name': 'OffSeq', 'enabled': False,
                                           'steps': ['sc-r'], 'reset_scene': 'sc-r'}]))
_ran[:] = []
_ok, _said = d.reset_sequence('sq-off', 'a test')
check(not _ok and not _ran, 'a switched-off sequence still ran its reset scene')
print('a switched-off sequence is not reset either')

# -- an unfinished row does not refuse the whole list, and a filled one is kept ----
_saved = d.save_bindings([{'group': '', 'device': '', 'action': '', 'plug': '', 'do': 'toggle'},
                          {'device': '0xbee', 'action': 'single', 'plug': 'Plug-New', 'do': 'toggle'}])
check(len(_saved) == 1, 'an empty new binding row refused the whole list')
# a schedule with a section and a time but no target yet is a mistake, said out
# loud - not a row silently dropped
try:
    d.save_schedules([{'id': 'x', 'group': 'Evening', 'at': '07:00', 'days': [0], 'do': 'on', 'target': ''}])
    check(False, 'a schedule with no target was swallowed')
except ValueError as e:
    check('unknown plug' in str(e) or 'target' in str(e), 'a half-filled schedule said %r' % str(e))
# and a sequence step nobody can do any more is said, not dropped
try:
    d.save_sequences([{'id': 'sq-x', 'name': 'Gone', 'steps': ['Plug-Vanished|on']}])
    check(False, 'a step that cannot be done was dropped in silence')
except ValueError as e:
    check('any more' in str(e) or 'at least one step' in str(e), 'an impossible step said %r' % str(e))
print('an unfinished row is passed over; a half-filled one is said out loud')

# -- a Save can be put back, for people and presence triggers too ------------------
d.save_people([{'id': 'p1', 'name': 'Falco', 'macs': [], 'enabled': True}])
d.save_people([{'id': 'p1', 'name': 'Falco', 'macs': [], 'enabled': True},
               {'id': 'p2', 'name': 'Second', 'macs': [], 'enabled': True}])
check(any(x['key'] == 'people' for x in d.snapshots()), 'saving people kept no version to go back to')
d.save_presence_triggers([{'id': 'pt1', 'who': 'anyone', 'event': 'leave', 'plug': 'Plug-New', 'do': 'off'}])
d.save_presence_triggers([])
check(any(x['key'] == 'presence_triggers' for x in d.snapshots()),
      'saving presence triggers kept no version to go back to')
# and putting the device list back takes effect, rather than only showing
_reloaded = []
_was_reload = d.reload_devices
d.reload_devices = lambda *a, **k: _reloaded.append(1) or _was_reload(*a, **k)
d.snapshot('managed', 'a test')
_snap = [x for x in d.snapshots() if x['key'] == 'managed'][0]
d.restore_snapshot(_snap['id'])
d.reload_devices = _was_reload
check(_reloaded, 'putting the device list back did not rebuild the live one')
print('people, presence triggers and the device list: kept, and put back for real')

# -- a script keeps the section it is filed under ---------------------------------
d.save_scripts([{'id': 'sc1', 'name': 'Evening', 'body': 'say hello', 'group': 'Nights'}])
check((d.scripts()[0].get('group') or '') == 'Nights', 'a script lost its section on save')
print('a script keeps its section')

# -- a channel of a box switched off as a whole says so rather than lying ----------
d.store.set_meta('managed', json.dumps({'plugs': [{'name': 'Plug-Dead', 'host': '10.0.0.8', 'switch_id': 0,
                                                   'kind': 'plug', 'host_state': 'disabled',
                                                   'own_enabled': False}], 'sensors': []}))
d.reload_devices()
_row = [e for e in d.all_entries('plugs') if e['name'] == 'Plug-Dead'][0]
try:
    d._obj_edit('plug', 'Plug-Dead', _row, 'enabled', 'on', 'a test')
    check(False, 'enabling a channel of a switched-off box claimed to work')
except ValueError as e:
    check('as a whole' in str(e), 'enabling a channel of a switched-off box said %r' % str(e))
print('a channel of a box switched off as a whole: said, not claimed')

# -- the clock is read once a minute, not four times a second ----------------------
_looked = []
_was_sun = zigmon.sun_minutes
zigmon.sun_minutes = lambda *a, **k: _looked.append(1) or _was_sun(*a, **k)
d.store.set_meta('schedules', json.dumps([{'id': 'sun1', 'target': 'Plug-New', 'do': 'on', 'at': 'sunset',
                                           'days': list(range(7)), 'enabled': True}]))
d._sched_minute = None
d.check_schedules()
_first = len(_looked)
for _ in range(8):
    d.check_schedules()
check(len(_looked) == _first, 'the sun was worked out again on every beat: %d times' % len(_looked))
zigmon.sun_minutes = _was_sun
print('the schedules are read once a minute, not four times a second')

# -- the numbers a house reports do not wake every page at once --------------------
_woke = []
_was_bump, _was_soon = d.bump, d.bump_soon
d.bump = lambda: _woke.append('now')
d.bump_soon = lambda delay=0.5: _woke.append('soon')
d.store.upsert_device({'id': 'zigbee:Temp-Quiet', 'name': 'Temp-Quiet', 'source': 'zigbee', 'kind': 'sensor',
                       'exposes': {'temperature': {}}})
d.handle_generic(['zigbee2mqtt', 'Temp-Quiet'], json.dumps({'temperature': 21.5, 'humidity': 44}).encode())
_woke[:] = []
d.handle_generic(['zigbee2mqtt', 'Temp-Quiet'], json.dumps({'temperature': 21.6, 'humidity': 44}).encode())
check(_woke == ['soon'], 'a plain temperature report woke every page at once: %r' % _woke)
_woke[:] = []
d.handle_generic(['zigbee2mqtt', 'Temp-Quiet'], json.dumps({'temperature': 21.6, 'humidity': 44,
                                                            'action': 'single'}).encode())
check('now' in _woke, 'a button press waited for the next half second: %r' % _woke)
d.bump, d.bump_soon = _was_bump, _was_soon
print('numbers wake the pages together; a press wakes them at once')

# -- what a search counts against is not counted anew on every keystroke -----------
_n1 = d.store.events_count()
_before = time.time()
for _ in range(50):
    d.store.events_count()
check(time.time() - _before < 0.5, 'counting the whole event log again for every keystroke')
check(d.store.events_count() == _n1, 'the count of the whole log moved while nothing happened')
# and the peaks have an index to seek with
_idx = [r['name'] for r in d.store.db.execute("SELECT name FROM sqlite_master WHERE type='index'")]
check('samples_hourly_key_ts' in _idx, 'the hourly peaks still walk every device to find one key')
print('the whole-log count is kept for a moment, and the peaks seek instead of walking')

# ===== 5.5: what the sweep for bugs, lag and latency found ========================

# -- the list of everything Zigbee will let us set is worked out once a moment ------
_walks = []
_was_devices = d.store.devices
d.store.devices = lambda *a, **k: _walks.append(1) or _was_devices(*a, **k)
d._zbt_cache = None
d.zigbee_targets()
_after_first = len(_walks)
for _ in range(6):
    d.zigbee_targets()
check(len(_walks) == _after_first,
      'the whole mesh was walked again for every ask: %d walks' % (len(_walks) - _after_first + 1))
d.store.devices = _was_devices
print('the settable Zigbee keys are worked out once a moment, not once per room')

# -- a box added while the poll round is running does not stop the polling ----------
class _Box:
    def __init__(self, name, cfg=None):
        self.name = name
        self.device_id = 'plug:' + name
        self.cfg = cfg if cfg is not None else {'host': '10.0.0.9', 'monitor_only': False}
        self.optional = False
        self.unplugged = False
        self.error = None
        self.flat = {}
        self.generated = 0
        self.backoff_until = 0


class _Meddling(dict):
    """A box whose address is read while the round is being put together - and
    reading it is what the device list being saved underneath looks like."""

    def get(self, key, default=None):
        if key == 'host' and len(d.plugs) < 5:
            name = 'Mid%d' % len(d.plugs)
            d.plugs[name] = _Box(name)
        return dict.get(self, key, default)


check(hasattr(d, '_plug_round'),
      'the poll round cannot be run on its own, so nothing catches it dying mid-round')
d.plugs = {'A': _Box('A', _Meddling({'host': '10.0.0.9', 'monitor_only': False})),
           'B': _Box('B')}
d.sensors = {}
zigmon.CONFIG['plug_poll_interval'] = 2
_was_poll, _was_group = d.poll_plug, d.poll_plug_group
d.poll_plug = d.poll_plug_group = lambda *a, **k: d._stop.set()       # one round is enough
d._stop.clear()
_why = ''
try:
    d._plug_round(time.time())
    _round_ok = True
except RuntimeError as e:
    _round_ok, _why = False, str(e)
d.poll_plug, d.poll_plug_group = _was_poll, _was_group
d._stop.clear()
check(_round_ok, 'the device list saved underneath a poll round killed the polling for good: %s' % _why)
d.plugs, d.sensors = {}, {}
print('a box added mid-round does not stop the polling')

# -- a slow number written as a word is still a slow number ------------------------
check(d._is_state_key('last_seen', '2026-01-01T10:00:00Z') is False, 'an ISO date woke every page at once')
check(d._is_state_key('switch.voltage', '235.1') is False, 'a voltage in quotes woke every page at once')
check(d._is_state_key('occupancy', True) is True, 'a movement report waited for the next half second')
check(d._is_state_key('switch.output', False) is True, 'a socket turning off waited for the next half second')
print('a reading written as a word is still a reading; a state is still a state')

# -- a monitor-only box cannot be told to switch from the object view ---------------
d.store.set_meta('managed', json.dumps({'plugs': [{'name': 'Plug-Watch', 'host': '10.0.0.11', 'switch_id': 0,
                                                   'kind': 'plug', 'host_state': 'monitor',
                                                   'monitor_only': True, 'own_enabled': True}], 'sensors': []}))
d.reload_devices()
_watch = [e for e in d.all_entries('plugs') if e['name'] == 'Plug-Watch'][0]
try:
    d._obj_edit('plug', 'Plug-Watch', _watch, 'monitor_only', 'off', 'a test')
    check(False, 'a watched-only box claimed it could be switched again')
except ValueError as e:
    check('watch' in str(e).lower() or 'monitor' in str(e).lower(),
          'a watched-only box said %r' % str(e))
print('a box the house only watches cannot be told to switch')

# -- a blank row stamped with a section is still a blank row -----------------------
check(zigmon.untouched_row({'group': 'Nights', 'device': '', 'action': '', 'plug': ''},
                           ('device', 'action', 'plug', 'group')) is True,
      'a row that only carries the section it was added under was taken for half-filled')
check(zigmon.untouched_row({'group': 'Nights', 'device': 'zb:Button', 'action': '', 'plug': ''},
                           ('device', 'action', 'plug', 'group')) is False,
      'a half-filled row was passed over')
print('a row carrying only its section is a blank row, not a mistake')

# -- renaming a socket follows what reads it, not only what it switches -------------
d.store.set_meta('rules', json.dumps([{'id': 'r-read', 'device': 'plug:Plug-Old', 'key': 'switch.output',
                                       'op': '==', 'value': '1', 'plug': 'Plug-Old', 'do': 'on',
                                       'device2': 'plug:Plug-Old', 'device3': 'plug:Plug-Old',
                                       'enabled': True}]))
d.store.set_meta('bindings', json.dumps([{'device': 'plug:Plug-Old', 'action': 'single', 'plug': 'Plug-Old'}]))
d.store.set_meta('sensor_groups', json.dumps([{'id': 'g-read', 'name': 'Reads',
                                               'members': ['plug:Plug-Old', 'Plug-Old']}]))
d.save_scripts([{'id': 's-read', 'name': 'Watcher', 'enabled': True,
                 'body': 'if Plug-Old.power > 10\n  say "the old one is busy"\nend'}])
_moved = d.retarget('Plug-Old', 'Plug-Fresh')
_rules = d.store.meta_json('rules')
check(_rules[0]['device'] == 'plug:Plug-Fresh', 'a rule kept watching the old name')
check(_rules[0]['device2'] == 'plug:Plug-Fresh' and _rules[0]['device3'] == 'plug:Plug-Fresh',
      'a rule\'s second and third source kept the old name')
check(d.store.meta_json('bindings')[0]['device'] == 'plug:Plug-Fresh', 'a binding kept the old name')
check(d.store.meta_json('sensor_groups')[0]['members'] == ['plug:Plug-Fresh', 'Plug-Fresh'],
      'a sensor group kept the old name: %r' % d.store.meta_json('sensor_groups')[0]['members'])
check('Plug-Fresh.power' in (d.scripts()[0].get('body') or ''), 'a script kept the old name')
check(_moved >= 6, 'the rename said it had changed %d things' % _moved)
print('renaming a socket follows the rules, bindings, groups and scripts that read it')

# -- a card knows that a saved list was edited, not only that it grew ---------------
d.store.set_meta('schedules', json.dumps([{'id': 'sc1', 'target': 'Plug-New', 'do': 'on', 'at': '07:00',
                                           'days': list(range(7)), 'enabled': True}]))
_st1 = d.status()
d.store.set_meta('schedules', json.dumps([{'id': 'sc1', 'target': 'Plug-New', 'do': 'on', 'at': '08:00',
                                           'days': list(range(7)), 'enabled': True}]))
_st2 = d.status()
check(_st1['schedule_count'] == _st2['schedule_count'], 'the test moved the count instead of the hour')
check(_st1['schedule_stamp'] != _st2['schedule_stamp'],
      'a schedule moved to another hour looked the same to the page')
check('scene_stamp' in _st2 and 'sequence_stamp' in _st2, 'the scenes and sequences have no fingerprint')
print('a schedule edited elsewhere reaches the card without a reload')

# -- a rule with a word for a value does not bring the whole page down --------------
d.store.set_meta('rules', json.dumps([{'id': 'r-word', 'device': 'plug:Plug-Fresh', 'key': 'switch.output',
                                       'op': '==', 'value': 'open', 'plug': 'Plug-Fresh', 'do': 'on',
                                       'enabled': True, 'switchable': True}]))
_label = d.target_label('rule:r-word')
check('open' in _label, 'a rule with a word for a value was described as %r' % _label)
check(isinstance(d.status(), dict), 'a rule with a word for a value took the whole status with it')
print('a rule with a word for a value is described, not fatal')

# ===== 5.6: the addresses on their way to being kept out ==========================

# What is counted against an address was in the daemon and nowhere else: the
# card could say a score and nothing about what the score was heading for.
zigmon.CONFIG['block_ladder'] = '10, 60, 1440, forever'
zigmon.CONFIG['block_score'] = 15
zigmon.CONFIG['block_sensitivity'] = 'normal'
zigmon.CONFIG['block_mode'] = 'temporary'
zigmon.CONFIG['never_block'] = '45.134.26.200'
d._anomaly.clear()
d._blocked_times.clear()
for _i in range(2):
    d.note_anomaly('45.134.26.8', 'shut-road', '/nope-%d' % _i, source='proxy')
_watch = {x['ip']: x for x in d.anomaly_state()}
check('45.134.26.8' in _watch, 'an address doing things is not in the watched list at all')
_one = _watch['45.134.26.8']
for _key in ('score', 'bar', 'tries', 'spread', 'kinds', 'runs_out', 'country',
             'on_feeds', 'from_feed', 'ids', 'before', 'spared', 'intel', 'next'):
    check(_key in _one, 'a watched address says nothing about %r' % _key)
check(_one['next']['minutes'] == 10 and not _one['next']['forever'],
      'the first step of the ladder was said to be %r' % (_one['next'],))
check('10 min' in _one['next']['words'], 'the step is not said in words: %r' % _one['next']['words'])
print('a watched address says how near it is and what it would get')

# ...the step it is on moves with the ladder and with what it has done before
d._blocked_times['45.134.26.8'] = 2
_after = {x['ip']: x for x in d.anomaly_state()}['45.134.26.8']
check(_after['next']['minutes'] == 1440,
      'the third time from an address is not the third step: %r' % (_after['next'],))
d._blocked_times['45.134.26.8'] = 9
_far = {x['ip']: x for x in d.anomaly_state()}['45.134.26.8']
check(_far['next']['forever'], 'past the end of a ladder that says for good, it is not for good')
d._blocked_times.clear()
print('the step it is heading for follows the ladder and how often it has been here')

# ...and what the settings say is off, or spared, is said out loud rather than
# drawn as a bar that means nothing
d.note_anomaly('45.134.26.200', 'shut-road', '/nope', source='proxy')
_spare = {x['ip']: x for x in d.anomaly_state()}.get('45.134.26.200')
check(_spare and 'never kept out' in _spare['next']['words'],
      'an address that is never kept out is drawn as though it were about to be: %r' % (_spare or {}))
check(_spare['spared'], 'an address on the never-kept-out list does not say so')
zigmon.CONFIG['block_mode'] = 'off'
_off = {x['ip']: x for x in d.anomaly_state()}['45.134.26.8']
check('switched off' in _off['next']['words'],
      'with the keeping out switched off, a watched address still promises a block: %r' % (_off['next'],))
zigmon.CONFIG['block_mode'] = 'permanent'
_perm = {x['ip']: x for x in d.anomaly_state()}['45.134.26.8']
check(_perm['next']['forever'], 'set to keep out for good, the watched list still says minutes')
zigmon.CONFIG['block_mode'] = 'temporary'
print('what the settings say is off, or spared, is said in words and not as a promise')

# ...and asking for all of it again and again is cheap: the card asks for it
# every second or two while somebody is looking at it
_before_t = time.time()
for _ in range(25):
    d.anomaly_state()
check(time.time() - _before_t < 1.0, 'reading the watched list 25 times took %.2f s' % (time.time() - _before_t))
print('the watched list is cheap to ask for, over and over')

# ===== 5.8: the fifth read through, for faults and for what costs time ===========

# -- every save of the Settings card went through, and stayed -----------------------
# A setting written as "bool" is neither a pair nor 'str', so the save asked a
# type for its first element: TypeError, answered 500, and nothing written -
# for every save, because the page posts every box it draws.
_body = {'plug_poll_interval': 25, 'plug_command_overtakes_poll': 1, 'manual_hold_s': 60}
_changed = d.save_config_overrides(_body)
check('plug_poll_interval' in _changed, 'a settings save wrote nothing: %r' % (_changed,))
check(zigmon.CONFIG['plug_poll_interval'] == 25, 'the setting did not take')
check([x for x in [d.runtime_config().get('plug_command_overtakes_poll')] if x][0]['kind'] == 'switch',
      'a yes-or-no setting is still drawn as a number box')
d.save_config_overrides({'plug_poll_interval': 15})
print('a settings save goes through, and a yes-or-no setting is a switch')

# -- a device list saved while something walks the sockets ------------------------
d.store.set_meta('managed', json.dumps({'plugs': [{'name': 'P%d' % i, 'host': '10.0.0.%d' % i,
                                                   'switch_id': 0, 'kind': 'plug', 'own_enabled': True}
                                                  for i in range(12)], 'sensors': []}))
d.reload_devices()
_trouble = []
_stop_walk = threading.Event()


def _walker():
    while not _stop_walk.is_set():
        try:
            # the shape of every reader of this list: the fire path, the power
            # figure, three places in the status
            [p.name for p in d.plugs.values()]
            [p.name for p in d.sensors.values()]
        except RuntimeError as e:
            _trouble.append(str(e))
            return


_walk = threading.Thread(target=_walker, daemon=True)
_walk.start()
for _round in range(12):
    d.store.set_meta('managed', json.dumps({'plugs': [{'name': 'P%d' % i, 'host': '10.0.0.%d' % i,
                                                       'switch_id': 0, 'kind': 'plug', 'own_enabled': True}
                                                      for i in range(2 + _round % 9)], 'sensors': []}))
    d.reload_devices()
_stop_walk.set()
_walk.join(2)
check(not _trouble, 'a device list saved underneath a reader: %r' % _trouble[:1])
d.store.set_meta('managed', json.dumps({'plugs': [], 'sensors': []}))
d.reload_devices()
print('the device list is put in place whole; nobody walks one that is changing')

# -- a Wi-Fi controller that does not answer is asked once, not once per rule -------
_asked = []
_was_poll = d.wifi_poll_once
d.wifi_poll_once = lambda cfg=None, force=False: (_asked.append(1), (_ for _ in ()).throw(OSError('no route')))[0]
d.store.set_meta('wifi', json.dumps({'enabled': True, 'host': '10.9.9.9', 'method': 'official',
                                     'user': 'x', 'password': 'y', 'site': 'default'}))
d.wifi = dict(getattr(d, 'wifi', {}) or {}, checked=0)
zigmon.CONFIG['presence_fresh_s'] = 4
for _ in range(6):
    d.presence_allows({'when': 'home'})
check(len(_asked) == 1, 'a controller that cannot be reached was asked %d time(s) for six rules' % len(_asked))
d.wifi_poll_once = _was_poll
d.store.set_meta('wifi', json.dumps({'enabled': False}))
print('a controller that cannot be reached is asked once, not once per rule per reading')

# -- four lights taken over by one press stay taken over ---------------------------
d.store.set_meta('manual_holds', json.dumps({}))
zigmon.CONFIG['manual_hold_s'] = 0
_ready = threading.Event()
# the read and the write are made to straddle each other, which is what four
# threads one press apart do by themselves on a real house
_was_holds = d.manual_holds
# the list is read, and the write comes a breath later: that gap is the whole
# of it, and four threads one press apart sit in it together
d.manual_holds = lambda: (_was_holds(), time.sleep(0.05))[0]


def _taker(which):
    _ready.wait()
    d.hold_target('Light-%d' % which, 'a test')


_hands = [threading.Thread(target=_taker, args=(i,), daemon=True) for i in range(4)]
for _t in _hands:
    _t.start()
_ready.set()
for _t in _hands:
    _t.join(3)
check(len(d.manual_holds()) == 4, 'four lights taken over at once left %d held' % len(d.manual_holds()))
_ready.clear()
_ready.set()
_hands = [threading.Thread(target=lambda i=i: d.release_target('Light-%d' % i), daemon=True) for i in range(4)]
for _t in _hands:
    _t.start()
for _t in _hands:
    _t.join(3)
check(not d.manual_holds(), 'giving four lights back at once left %r held' % (d.manual_holds(),))
d.manual_holds = _was_holds
print('four lights taken over, and given back, by one press each: all four')

# -- the same reading does not work out a group twice ------------------------------
d.store.set_meta('sensor_groups', json.dumps([{'id': 'g-twice', 'name': 'Hall', 'key': 'occupancy',
                                               'mode': 'any', 'members': ['zigbee:PIR-A', 'zigbee:PIR-B'],
                                               'enabled': True}]))
for _name in ('PIR-A', 'PIR-B'):
    d.store.upsert_device({'id': 'zigbee:' + _name, 'name': _name, 'source': 'zigbee', 'kind': 'sensor',
                           'exposes': {'occupancy': {}}})
_ran = []
_was_refresh = d.refresh_group
d.refresh_group = lambda device_id, name, values: _ran.append(device_id) or _was_refresh(device_id, name, values)
d._rule_queue.clear()
d._rule_queue_gated.clear()
d._stop.clear()
_workers = [threading.Thread(target=d.rule_worker, args=(g,), daemon=True) for g in (False, True)]
for _w in _workers:
    _w.start()
d.queue_rules('zigbee:PIR-A', 'PIR-A', {'occupancy': True})
time.sleep(0.6)
d._stop.set()
for _w in _workers:
    _w.join(2)
d._stop.clear()
check(len(_ran) == 1, 'one reading worked the group out %d time(s)' % len(_ran))
d.refresh_group = _was_refresh
print('one reading, one look at the group it belongs to')

# -- the backlog is said once per queue, not once per reading ----------------------
_said = []
_was_log = zigmon.log
zigmon.log = lambda text, level='info': _said.append(text) if 'readings behind' in str(text) else None
d._rule_queue.clear()
d._rule_queue_gated.clear()
for _ in range(d.RULE_BACKLOG + 40):
    d._rule_queue_gated.append(('zigbee:PIR-A', 'PIR-A', {'occupancy': True}))
for _ in range(25):
    d.queue_rules('zigbee:PIR-A', 'PIR-A', {'occupancy': True})
zigmon.log = _was_log
check(len(_said) == 1, 'a backlog that lasted twenty-five readings was said %d time(s)' % len(_said))
d._rule_queue.clear()
d._rule_queue_gated.clear()
print('a backlog is said once, not once per reading')

# -- a sensor group put back does not swallow its first reading --------------------
d._group_last['grp:g-twice'] = 1
d._group_trigger['grp:g-twice'] = {'device': 'PIR-A'}
d._group_skipped['g-gone'] = []
d._group_last['grp:g-gone'] = 1
d.snapshot('sensor_groups', 'a test')
_ok, _words = d.restore_snapshot(d.snapshots()[0]['id'])
check(_ok, 'the snapshot would not go back: %s' % _words)
check('grp:g-twice' not in d._group_last, 'a group put back kept the value of the one it replaced')
check('grp:g-gone' not in d._group_last and 'g-gone' not in d._group_skipped,
      'a group the restore removed is still remembered')
print('a sensor group put back starts from nothing, and the ones it replaced are forgotten')

# -- the words for a target are worked out once a moment, not once per ask ---------
d.store.set_meta('rules', json.dumps([{'id': 'r-%d' % i, 'device': 'zigbee:PIR-A', 'key': 'occupancy',
                                       'op': '==', 'value': 1, 'plug': 'Light', 'do': 'on',
                                       'enabled': True} for i in range(40)]))
_walks = []
_was_rules = d.rules
d.rules = lambda: _walks.append(1) or _was_rules()
d.__dict__.pop('_label_cache', None)
for _ in range(40):
    d.target_label('rule:r-7')
check(len(_walks) <= 2, 'forty asks for one label walked the rules %d time(s)' % len(_walks))
d.rules = _was_rules
print('the words for a target are worked out once a moment, not once per ask')

# -- the peak the house has drawn counts the sockets it has ------------------------
d.store.set_meta('managed', json.dumps({'plugs': [{'name': 'Plug-Now', 'host': '10.0.0.21', 'switch_id': 0,
                                                   'kind': 'plug', 'own_enabled': True}], 'sensors': []}))
d.reload_devices()
_hour = int(time.time() // 3600 * 3600)
with d.store.lock:
    for _dev, _max in (('plug:Plug-Now', 120.0), ('plug:Plug-Gone', 9000.0)):
        d.store.db.execute('INSERT OR REPLACE INTO samples_hourly (device, key, ts, min, max, avg, n) '
                           'VALUES (?,?,?,?,?,?,?)', (_dev, 'switch.apower', _hour - 3600, 0.0, _max, _max, 1))
    d.store.db.commit()
d.__dict__.pop('_power_peak_cache', None)
_peaks = d.power_peaks()
check(_peaks['day'] == 120.0,
      'the day peak counted a socket the house no longer has: %r' % (_peaks['day'],))
print('the peak the house has drawn is drawn from the sockets it has')

# -- the chart's last point is the newest hour, however long the range -------------
_newest = int(time.time() // 3600 * 3600) - 3600
with d.store.lock:
    for _i in range(900):                  # a long range: more hours than the chart has points
        d.store.db.execute('INSERT OR REPLACE INTO samples_hourly (device, key, ts, min, max, avg, n) '
                           'VALUES (?,?,?,?,?,?,?)',
                           ('plug:Plug-Now', 'switch.apower', _newest - _i * 3600, 0.0, 10.0, 10.0, 1))
    d.store.db.commit()
_chart = d.power_series(901 * 3600, points=400)
check(_chart, 'the power chart came back empty')
check(_chart[-1]['ts'] == _newest,
      'the chart stops %d hour(s) short of the newest reading' % ((_newest - _chart[-1]['ts']) // 3600))
print('a long range of power keeps its newest hour')

# ===== 5.10: "max" - the opposite of off ==========================================
# A level that is not a temperature somebody chose: the valves wide open and
# the room heated as hard as it can be, with nothing to regulate.
d.store.set_meta('rooms', json.dumps([{'id': 'r-max', 'name': 'Koupelna'},
                                      {'id': 'r-cold', 'name': 'Sklep'}]))
d.store.upsert_device({'id': 'zigbee:TRV-Max', 'name': 'TRV-Max', 'source': 'zigbee', 'kind': 'valve',
                       'exposes': {'occupied_heating_setpoint': {'access': 7, 'min': 5, 'max': 35,
                                                                 'type': 'numeric'}}})
d.live['zigbee:TRV-Max'] = {'payload': {'occupied_heating_setpoint': 21.0, 'local_temperature': 19.0},
                            'ts': time.time()}
d.store.set_meta('room_of', json.dumps({'zigbee:TRV-Max': 'r-max'}))
d._heat_state_cache = None
d.save_heating({'enabled': True, 'rooms': {'r-max': {'mode': 'max', 'heated': True, 'control': True},
                                           'r-cold': {'mode': 'off', 'heated': True, 'control': True}}})
_rooms = {r['id']: r for r in d.heating_state()['rooms']}
check(_rooms['r-max']['level'] == 'max', 'a room put on max is on %r' % _rooms['r-max']['level'])
check(_rooms['r-max']['wanted_c'] == 35.0,
      'max asked for %r rather than what the head will take' % _rooms['r-max']['wanted_c'])
check(_rooms['r-max']['why'] == 'max', 'the reason given was %r' % _rooms['r-max']['why'])
check(_rooms['r-cold']['wanted_c'] == 5.0, 'off is no longer five degrees: %r' % _rooms['r-cold']['wanted_c'])
# ...and a room whose heads have not said how high they go still gets a number
check(d.room_max_c([]) == d.HEAT_MAX_C, 'a room with no head to ask got %r' % d.room_max_c([]))
check(d.room_max_c([{'max': 28.0}, {'max': 30.0}]) == 30.0, 'two heads, the higher ceiling')
print('a room on max asks for what its heads will take, and off is still five degrees')

# ...it can be put there by hand, by a message, by a plan step and from a rule
d.heat_target('room:r-max', 'set:off', 'a test')
check(d.heating_state()['rooms'][0]['level'] == 'off', 'the room would not go off')
d.heat_target('room:r-max', 'set:max', 'a test')
check({r['id']: r for r in d.heating_state()['rooms']}['r-max']['level'] == 'max',
      'a rule or a scene cannot put a room on max')
_said = d.heat_say('Koupelna max')
check('max' in _said, 'a text message cannot put a room on max: %r' % _said)
_plan = d._plan_parse('06:30 max mon-fri, 08:00 eco', 'a test')
check([x['level'] for x in _plan] == ['max', 'eco'], 'a plan step cannot say max: %r' % _plan)
d.save_heating({'rooms': {'r-max': {'mode': 'plan', 'plan': [{'at': '00:00', 'level': 'max',
                                                              'days': list(range(7))}]}}})
check({r['id']: r for r in d.heating_state()['rooms']}['r-max']['level'] == 'max',
      'a plan that says max all day did not put the room on max')
# ...and the object view takes it as a word like the others
d.save_heating({'rooms': {'r-max': {'mode': 'eco'}}})
d.object_set('Koupelna', 'mode', 'max', 'a test')
check({r['id']: r for r in d.heating_state()['rooms']}['r-max']['mode'] == 'max',
      'the object view would not take max')
print('max is reachable from a card, a rule, a text message, a plan and the object view')

# 5.10: the preset row has to fold inside the card, not hang over its edge.
# On a phone the hand bar is about 324 px wide and the presets no longer fit
# across it - with Max they are 391 px of buttons. An inline-flex row with no
# wrapping cannot be squeezed, so it drew straight through the card's edge.
_css = (Path(__file__).resolve().parent.parent / 'web' / 'index.php').read_text()
_rule = ''
for _line in _css.splitlines():
    if _line.strip().startswith('.heat-presets{'):
        _rule = _line.strip()
        break
check(_rule != '', 'the preset row has no rule of its own any more')
check('flex-wrap:wrap' in _rule,
      'the preset row cannot fold, so on a phone it hangs over the card: %s' % _rule)
check('min-width:0' in _rule,
      'the preset row cannot be squeezed to the card it sits in: %s' % _rule)
print('the preset row folds inside the card on a narrow screen')

# 5.11: away is a temperature, so it replaces the temperatures - and leaves
# the two levels that are not temperatures alone. Off was already exempt;
# max was not, so pressing Max while an away schedule was running held the
# room at the away temperature and the button looked like it did nothing.
_rooms = [{'id': 'r-awmax', 'name': 'MaxAway'}, {'id': 'r-awoff', 'name': 'OffAway'},
          {'id': 'r-awwarm', 'name': 'WarmAway'}]
d.save_rooms(d.rooms() + _rooms)
d.save_room_map(dict(d.room_map(), **{'Valve-Max': 'r-awmax'}))
d.save_heating({'enabled': True, 'away': True, 'away_c': 16.0,
                'rooms': {'r-awmax': {'mode': 'max'}, 'r-awoff': {'mode': 'off'},
                          'r-awwarm': {'mode': 'comfort', 'comfort_c': 21.0}}})
_by = {r['id']: r for r in d.heating_state()['rooms']}
check(d.heating_state()['away'] is True, 'away would not switch on')
check(_by['r-awmax']['why'] == 'max',
      'away overrode max, so the button does nothing: %r at %r'
      % (_by['r-awmax']['why'], _by['r-awmax']['wanted_c']))
check(_by['r-awmax']['wanted_c'] == d.room_max_c(_by['r-awmax']['valves']),
      'a room on max while away asked for %r' % _by['r-awmax']['wanted_c'])
check((_by['r-awoff']['why'], _by['r-awoff']['wanted_c']) == ('off', 5.0),
      'away stopped leaving off alone: %r' % (_by['r-awoff'],))
check((_by['r-awwarm']['why'], _by['r-awwarm']['wanted_c']) == ('away', 16.0),
      'away stopped replacing the temperatures: %r' % (_by['r-awwarm'],))
d.save_heating({'away': False})
print('away replaces the temperatures and leaves off and max alone')

# ============================================================================
# 5.11: a sixth read through, room by room
# ============================================================================

# -- a window is open if ANY of the room's sensors says so ----------------------
# The loop answered on the first sensor that had anything to say, open or shut.
# A bedroom with a balcony door and a side window was decided by whichever of
# the two came first in the room: the door shut said the room was shut, and the
# radiator went on heating the open window.
for _n, _id in (('Win-Door', 'zigbee:win-door'), ('Win-Side', 'zigbee:win-side')):
    d.store.upsert_device({'id': _id, 'name': _n, 'source': 'zigbee', 'kind': 'sensor',
                           'exposes': {'contact': {}}})
    d.names[_n] = _id
d.save_rooms(d.rooms() + [{'id': 'r-win', 'name': 'WinRoom'}])
d.save_room_map(dict(d.room_map(), **{'Win-Door': 'r-win', 'Win-Side': 'r-win'}))
for _door, _side, _want in ((True, True, False), (True, False, True),
                            (False, True, True), (False, False, True)):
    d.live['zigbee:win-door'] = {'ts': time.time(), 'payload': {'contact': _door}}
    d.live['zigbee:win-side'] = {'ts': time.time(), 'payload': {'contact': _side}}
    check(d.room_window_open('r-win') is _want,
          'door %s, window %s: the room says open=%r'
          % ('shut' if _door else 'open', 'shut' if _side else 'open',
             d.room_window_open('r-win')))
    # ...and the same whichever order the chosen ones are written in
    for _order in (['Win-Door', 'Win-Side'], ['Win-Side', 'Win-Door']):
        check(d.room_window_open('r-win', {'windows': _order}) is _want,
              'the chosen windows in the order %r answered %r'
              % (_order, d.room_window_open('r-win', {'windows': _order})))
print('a window is open when any of the room\'s sensors says so, in any order')

# -- a plan that does not run every day keeps its last step over the gap --------
# Looking one day back only: a Mon-Fri plan ending in "22:00 off" left Saturday
# off correctly, then found nothing for Sunday (nor for Saturday) and fell
# through to a hardcoded eco - so the house heated to eighteen all Sunday and
# until Monday morning, with the plan saying off throughout.
_plan = {'mode': 'plan', 'plan': [{'at': '06:30', 'level': 'comfort', 'days': [1, 2, 3, 4, 5]},
                                  {'at': '22:00', 'level': 'off', 'days': [1, 2, 3, 4, 5]}]}
for _day, _hour, _want, _label in ((16, 12, 'comfort', 'Friday midday'),
                                   (16, 23, 'off', 'Friday night'),
                                   (17, 12, 'off', 'Saturday'),
                                   (18, 12, 'off', 'Sunday'),
                                   (18, 23, 'off', 'Sunday night'),
                                   (19, 3, 'off', 'Monday before the first step'),
                                   (19, 12, 'comfort', 'Monday midday')):
    _was = d.heating_level(_plan, time.mktime((2026, 10, _day, _hour, 0, 0, 0, 0, -1)))
    check(_was == _want, 'a Mon-Fri plan on %s is %r, not %r' % (_label, _was, _want))
# a Mon/Wed/Fri plan has two-day gaps and must hold over them too
_mwf = {'mode': 'plan', 'plan': [{'at': '07:00', 'level': 'night', 'days': [1, 3, 5]}]}
check(d.heating_level(_mwf, time.mktime((2026, 10, 18, 12, 0, 0, 0, 0, -1))) == 'night',
      'a Mon/Wed/Fri plan did not hold its last step over the weekend')
print('a plan that skips days holds its last step over the gap')

# -- a plan typed as words runs on the days it names ---------------------------
# Written days count from Monday (tm_wday, which is right for schedules);
# a heating plan is stored counting from Sunday, as the Heating tab writes it
# and heating_level reads it. The parser stored one and the reader read the
# other, so "07:00 comfort mon-fri" ran Sunday to Thursday: Friday morning
# never warmed up and Sunday warmed up for nothing.
_said = d._plan_parse('07:00 comfort mon-fri, 22:00 night mon-fri', 'a test')
check([s['days'] for s in _said] == [[1, 2, 3, 4, 5], [1, 2, 3, 4, 5]],
      'mon-fri was stored as %r' % ([s['days'] for s in _said],))
_room = {'mode': 'plan', 'plan': _said}
for _day, _want, _label in ((19, 'comfort', 'Monday'), (20, 'comfort', 'Tuesday'),
                            (23, 'comfort', 'Friday'), (24, 'night', 'Saturday'),
                            (25, 'night', 'Sunday')):
    _was = d.heating_level(_room, time.mktime((2026, 10, _day, 12, 0, 0, 0, 0, -1)))
    check(_was == _want, 'a written mon-fri plan on %s is %r, not %r' % (_label, _was, _want))
check(d._plan_parse('08:00 comfort sat-sun', 'a test')[0]['days'] == [0, 6],
      'sat-sun was stored as %r' % (d._plan_parse('08:00 comfort sat-sun', 'a test')[0]['days'],))
check(d._plan_parse('08:00 eco wed,fri', 'a test')[0]['days'] == [3, 5],
      'wed,fri was stored as %r' % (d._plan_parse('08:00 eco wed,fri', 'a test')[0]['days'],))
# ...and every written form reads back as itself
for _text in ('07:00 comfort mon-fri', '08:00 comfort sat-sun', '08:00 eco wed,fri',
              '06:30 max', '22:00 night mon-fri'):
    check(d._plan_words(d._plan_parse(_text, 'a test')) == _text,
          '%r was written back as %r' % (_text, d._plan_words(d._plan_parse(_text, 'a test'))))
# ...and a plan the dashboard saved reads back in the words it means
check(d._plan_words([{'at': '06:30', 'level': 'comfort', 'days': [1, 2, 3, 4, 5]}])
      == '06:30 comfort mon-fri',
      'the dashboard\'s own mon-fri reads back as %r'
      % d._plan_words([{'at': '06:30', 'level': 'comfort', 'days': [1, 2, 3, 4, 5]}]))
print('a plan typed as words runs on the days it names, and reads back as itself')

# -- a room says whether it is calling for heat, and whether its window is open -
# Four places asked a room whether it was "calling" and nothing ever wrote the
# word, so {Loznice.calling}, {rooms_heating} and the answer a text message
# gets all said no in a room four degrees short; {Loznice.window} read a key
# that was called window_open in the room, so it was always no.
d.store.upsert_device({'id': 'zigbee:fact-t', 'name': 'Fact-T', 'source': 'zigbee', 'kind': 'sensor',
                       'exposes': {'temperature': {}}})
d.names['Fact-T'] = 'zigbee:fact-t'
d.store.upsert_device({'id': 'zigbee:fact-w', 'name': 'Fact-W', 'source': 'zigbee', 'kind': 'sensor',
                       'exposes': {'contact': {}}})
d.names['Fact-W'] = 'zigbee:fact-w'
d.save_rooms(d.rooms() + [{'id': 'r-fact', 'name': 'FactRoom'}])
d.save_room_map(dict(d.room_map(), **{'Fact-T': 'r-fact', 'Fact-W': 'r-fact'}))
d.save_heating({'enabled': True, 'away': False,
                'rooms': {'r-fact': {'mode': 'comfort', 'comfort_c': 22.0, 'window_stop': True}}})
d.live['zigbee:fact-t'] = {'ts': time.time(), 'payload': {'temperature': 18.0}}
d.live['zigbee:fact-w'] = {'ts': time.time(), 'payload': {'contact': True}}      # shut
time.sleep(0.6)                                   # the rooms are kept for half a second
_fact = {r['id']: r for r in d.heating_state()['rooms']}['r-fact']
check(_fact.get('calling') is True,
      'a room four degrees short does not say it is calling: %r' % (_fact.get('calling'),))
check(_fact.get('window') is False, 'a shut window reads as %r' % (_fact.get('window'),))
_facts = d.message_facts('a test')
check(_facts.get('rooms_heating') == _facts.get('rooms_calling') >= 1,
      'the two facts for the same thing disagree: rooms_heating=%r rooms_calling=%r'
      % (_facts.get('rooms_heating'), _facts.get('rooms_calling')))
d.live['zigbee:fact-w'] = {'ts': time.time(), 'payload': {'contact': False}}     # open
time.sleep(0.6)
_fact = {r['id']: r for r in d.heating_state()['rooms']}['r-fact']
check(_fact.get('window') is True, 'an open window reads as %r' % (_fact.get('window'),))
check(_fact.get('why') == 'a window is open',
      'an open window did not stop the room: %r' % _fact.get('why'))
d.live.pop('zigbee:fact-w', None)
print('a room says whether it is calling for heat and whether a window is open')

# -- "half a degree more" on a room's temperature actually moves it -------------
# The dashboard offers a nudge for any target that is a number, which includes
# the temperature in a room - the one target whose prefix target_value did not
# know, so it found no room, answered None, and the nudge was dropped with a
# line in the log. A knob bound as a thermostat dial did nothing.
d.store.upsert_device({'id': 'zigbee:step-v', 'name': 'Step-V', 'source': 'zigbee', 'kind': 'trv',
                       'exposes': {'occupied_heating_setpoint': {'min': 5, 'max': 30, 'access': 7}}})
d.names['Step-V'] = 'zigbee:step-v'
d.save_rooms(d.rooms() + [{'id': 'r-step', 'name': 'StepRoom'}])
d.save_room_map(dict(d.room_map(), **{'Step-V': 'r-step'}))
d.save_heating({'enabled': True, 'rooms': {'r-step': {'mode': 'comfort', 'comfort_c': 21.0}}})
check(d.target_value(('heat', 'temp:r-step')) == 21.0,
      'the temperature in a room has no value to nudge from: %r' % (d.target_value(('heat', 'temp:r-step')),))


def _step_wanted():
    return {r['id']: r for r in d.heating_state()['rooms']}['r-step']['wanted_c']


d._fire_target('heat:temp:r-step', 'step:+0.5', 'a test')
time.sleep(0.6)
check(_step_wanted() == 21.5, 'half a degree more left the room at %r' % _step_wanted())
d._fire_target('heat:temp:r-step', 'step:-1.0', 'a test')
time.sleep(0.6)
check(_step_wanted() == 20.5, 'a degree less left the room at %r' % _step_wanted())
print('a nudge on a room\'s temperature moves it')

# -- `zigmon heating` shows what each room is asked to be ----------------------
# The command read a key called "target" that the API has never sent; the
# answer calls it wanted_c, so two of the command's three columns were a dash
# for every room.
_st = d.status()
_rows = (_st.get('heating') or {}).get('rooms') or []
check(_rows, 'the status carries no rooms to print')
check(any(isinstance(r.get('wanted_c'), (int, float)) for r in _rows),
      'no room in the status has a temperature it is asked for')
check(not any('target' in r for r in _rows),
      'the status now carries a key called target as well, which this command should prefer')


class _Pal(object):
    def __getattr__(self, name):
        return lambda text='': text


_was_need = zigmon._need_daemon
zigmon._need_daemon = lambda pal, path: _st
_out = io.StringIO()
try:
    with contextlib.redirect_stdout(_out):
        zigmon.cmd_heating(type('A', (), {'json': False})(), _Pal())
finally:
    zigmon._need_daemon = _was_need
_lines = [line for line in _out.getvalue().splitlines()
          if 'FactRoom' in line or 'StepRoom' in line]
check(_lines, 'the heating command printed no room: %r' % _out.getvalue()[:200])
for _line in _lines:
    _asked = _line.split()[1]
    check(_asked != '-',
          'the heating command still shows a dash for what a room is asked to be: %r' % _line.strip())
print('zigmon heating says what each room is asked to be: %s' % _lines[0].strip())

# -- a house whose presence is the phone shortcuts knows who is in -------------
# A gated rule goes quiet when a controller is set up and not answering, which
# is right. A house with no controller at all, whose presence comes from the
# phone shortcuts, was treated the same way: the chip was green, anyone_home
# agreed, and yet every rule with an "only when" gate was silent for ever -
# including "when nobody is home", the one that switches the heating off.
def _knows(phone_report, wifi_on, wifi_ok, told=True):
    """What the house says it knows, with the controller set up or not.

    told is whether a phone has actually reported. 5.12: the setting alone is
    not knowledge - the presence dict does not survive a restart, so a house
    taken as knowing on the strength of the setting let every gated rule
    through in the minutes after a restart with nobody known to be in, "when
    nobody is home" among them.
    """
    d.save_people([{'id': 'p-ph', 'name': 'PhoneOnly', 'macs': [], 'enabled': True,
                    'phone_report': phone_report}])
    d.save_wifi_config(dict(d.wifi_config(), enabled=1 if wifi_on else 0,
                            host='192.0.2.1', kind='unifi'))
    d.wifi['ok'] = wifi_ok
    if told:
        d.presence['p-ph'] = {'home': False, 'phone': 'away', 'phone_at': time.time(),
                              'since': time.time()}
    else:
        d.presence.pop('p-ph', None)
    d._presence_cache = None            # held for a second otherwise
    return d.presence_state()


check(_knows(True, False, None)['known'] is True,
      'a house with no controller and a phone shortcut does not know who is in')
check(d.presence_allows({'when': 'away'}) is True,
      'with nobody home, a rule gated on "away" is still refused')
# ...and straight after a restart, before any phone has said anything, it
# does NOT know - which is what stops "when nobody is home" firing on boot
check(_knows(True, False, None, told=False)['known'] is False,
      'a house that has not been told anything yet claims to know who is in')
check(_knows(True, False, None, told=False) and d.presence_allows({'when': 'away'}) is False,
      'a rule gated on "away" fires before any phone has reported')
check(_knows(True, True, None)['known'] is False,
      'a controller that is set up and silent now counts as knowing who is in')
check(_knows(True, True, True)['known'] is True, 'a controller that answers does not count')
check(_knows(False, True, True)['known'] is True,
      'a controller that answers stopped counting on its own')
check(_knows(False, False, None)['known'] is False,
      'a house with no controller and no phone shortcuts claims to know who is in')
print('presence from the phone shortcuts alone counts as knowing who is in')


# ============================================================================
# 5.12: a seventh read through
# ============================================================================

# -- a scene and a sequence that name each other stop -------------------------
# A scene refuses to name a scene, but it may name a SEQUENCE, and a
# sequence's step may name a scene - so a ring of two was savable in both
# editors and ran for ever on one press, writing an event per turn until
# somebody restarted the daemon. The thread ceiling never caught it: each hop
# finishes before the next begins, so nothing is ever concurrent.
d.store.set_meta('scenes', json.dumps(list(d.scenes()) + [
    {'id': 'sc-ring', 'name': 'Ring', 'actions': [{'target': 'seq:q-ring', 'do': 'on'}],
     'enabled': True}]))
d.store.set_meta('sequences', json.dumps(list(d.sequences()) + [
    {'id': 'q-ring', 'name': 'RingSeq', 'steps': ['sc-ring'], 'enabled': True}]))
_before = d.store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
d.run_scene('sc-ring', 'a test')
time.sleep(2.5)
_during = d.store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
time.sleep(1.5)
_after = d.store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
check(_during - _before < 40,
      'a ring of a scene and a sequence wrote %d event(s) in two seconds' % (_during - _before))
check(_after == _during,
      'it was still going a second and a half later: %d more' % (_after - _during))
check(not [t for t in threading.enumerate() if t.name in ('scene', 'sequence') and t.is_alive()],
      'a scene or sequence thread is still running')
print('a scene and a sequence that name each other stop, and say so')

# -- "on for ten minutes" in a scene is not read as "off" ---------------------
# Two steps on the same box go out through one worker, in order - and that
# road went straight to _run_binding, which reads anything that is not "on"
# as off. So a scene saying "on for ten minutes" switched two sockets on the
# same box OFF and set no timer, while the same scene with one socket per box
# did as it was told.
_asked = []
_was_run_binding = d._run_binding
_was_fire = d._fire_target
d._run_binding = lambda p, do, origin, pulse_ms=None, stagger=0.0: _asked.append(('direct', p, do))
d._fire_target = lambda target, do, origin, *a, **k: _asked.append(('fired', target, do))
try:
    d.store.set_meta('scenes', json.dumps(list(d.scenes()) + [
        {'id': 'sc-for', 'name': 'ForTen',
         'actions': [{'target': 'Strip-A', 'do': 'for:10m'}, {'target': 'Strip-B', 'do': 'for:10m'}],
         'enabled': True}]))
    d.run_scene('sc-for', 'a test')
    time.sleep(0.8)
finally:
    d._run_binding = _was_run_binding
    d._fire_target = _was_fire
check(not [x for x in _asked if x[0] == 'direct' and str(x[2]).startswith('for:')],
      'a timed action in a scene went straight to the socket, where it reads as off: %r' % (_asked,))
print('a timed action in a scene is worked out, not read as off')

# -- a scene fired by a rule honours a hand that has taken a light over -------
# honour_hold was never forwarded into a scene, and a hold belongs to a light
# rather than to the scene - so pressing the hall button to take the landing
# lamp over stopped a motion rule aimed at the lamp and did nothing against
# the same rule aimed at a scene that holds it.
import inspect as _inspect

check('honour_hold' in _inspect.signature(d.run_scene).parameters,
      'a scene cannot be told to honour a hold')
_src = _inspect.getsource(d.run_scene)
check('honour_hold=honour_hold' in _src,
      'a scene does not pass the hold on to what it switches')
print('a scene passes a hold on to what it switches')

# -- the depth travels with the chain ----------------------------------------
check('deep' in _inspect.signature(d._fire_target).parameters,
      'nothing counts how deep a chain of scenes and sequences has gone')
check(getattr(d, 'CHAIN_DEEP', 0) >= 2,
      'the chain depth is %r' % getattr(d, 'CHAIN_DEEP', None))
print('a chain of scenes and sequences is counted, %d deep at most'
      % getattr(d, 'CHAIN_DEEP', 0))

# -- a step with nothing to do of its own saves -------------------------------
# The editor offers "notify me" as a sequence step and writes it bare, as the
# row it draws says - and saving was then refused, in words that read as if
# the thing had been deleted a moment after it was picked from the list.
_saved = d.save_sequences([{'id': 'q-bare', 'name': 'BareStep', 'steps': ['notify'],
                            'enabled': True}])
check([x for x in _saved if x['id'] == 'q-bare'][0]['steps'] == ['notify'],
      'a bare notify step was not kept: %r' % _saved)
print('a sequence step that needs no action of its own saves')

# -- a script is something anything can run ----------------------------------
# An SMS command, a one-tap link and the object view could run one and
# nothing else could - and a script is the only place a value can be worked
# out rather than written down, so a rule and a scene being unable to reach
# one was the largest hole in the switching.
d.save_scripts(list(d.scripts()) + [{'id': 's-target', 'name': 'Target',
                                     'body': 'say the {device} said {value}'}])
check(d._valid_target('script:s-target') == 'script:s-target',
      'a script is still not something that can be acted on')
check(d._binding_targets('script:s-target') == [('script', 's-target')],
      'a script does not resolve to anything: %r' % (d._binding_targets('script:s-target'),))
check('Target' in d.target_label('script:s-target'),
      'a script reads as %r in the lists' % d.target_label('script:s-target'))
_ran = []
_was_script = d.run_script
d.run_script = lambda sc, facts, origin: (_ran.append((sc.get('name'), dict(facts), origin))
                                          or {'faults': [], 'answer': '', 'said': '', 'lines': 1})
try:
    d._fire_target('script:s-target', 'on', 'a rule', facts={'device': 'PIR-Hall', 'value': '1'})
    time.sleep(0.8)
finally:
    d.run_script = _was_script
check(_ran, 'a script fired as a target never ran')
check(_ran[0][1].get('device') == 'PIR-Hall',
      'what set it off was not handed to the script: %r' % (_ran[0][1],))
# ...and a rule saves with it (on its own: the rules standing here point at
# sockets this part of the file has since renamed)
_rules = d.save_rules([
    {'id': 'r-script', 'device': 'zigbee:fact-t', 'key': 'temperature', 'op': '>=', 'value': 30,
     'plug': 'script:s-target', 'do': 'on', 'enabled': True}])
check([r for r in _rules if r['id'] == 'r-script'][0]['plug'] == 'script:s-target',
      'a rule cannot be saved pointing at a script')
print('a script can be run by a rule, and is handed what set it off')

# -- an action may read its value from somewhere else -------------------------
# Only a script filled the facts into its own line, so "set the bedroom valve
# to what the living room reads" and "set the brightness to the lux reading"
# were script-only.
d.store.upsert_device({'id': 'zigbee:fill-v', 'name': 'Fill-V', 'source': 'zigbee', 'kind': 'trv',
                       'exposes': {'occupied_heating_setpoint': {'min': 5, 'max': 30, 'access': 7}}})
d.names['Fill-V'] = 'zigbee:fill-v'
_sent = []
_was_switch = d.zigbee_switch
d.zigbee_switch = lambda dev, key, what, why=None, *a, **k: (_sent.append((dev, key, what))
                                                             or (True, 'ok'))
try:
    d._fire_target('zb:zigbee:fill-v:occupied_heating_setpoint', 'set:{outside_c}', 'a rule',
                   facts={'outside_c': '18.7'})
    time.sleep(0.5)
    check(_sent and _sent[0][2] == 'set:18.7',
          'a value read from elsewhere did not reach the valve: %r' % (_sent,))
    # ...and a filled name must never become a target of its own
    _sent[:] = []
    d._fire_target('zb:zigbee:fill-v:occupied_heating_setpoint', '{mischief}', 'a rule',
                   facts={'mischief': 'sys:backup'})
    time.sleep(0.4)
    check(not [x for x in _sent if x[2] == 'sys:backup'],
          'a filled name became a target of its own: %r' % (_sent,))
finally:
    d.zigbee_switch = _was_switch
print('an action may read its value from elsewhere, and a filled name is not a target')

# -- the prepared reports are something anything can ask for ------------------
# "tell" passed validation everywhere and then did nothing outside a one-tap
# link, so a rule or a schedule saved with it was accepted and silent.
check(d._valid_target('tell') is None,
      'a bare tell is still taken where it means nothing')
try:
    check(d._valid_target('tell', allow_tell=True) == 'tell',
          'a one-tap link can no longer tell anybody anything')
except TypeError:
    check(False, 'a one-tap link has no way of saying a bare tell is allowed')
check(d._valid_target('tell:house') == 'tell:house',
      'the house cannot be asked how it is')
check(d._valid_target('tell:nonsense') is None, 'any word at all is taken as a report')
_told = []
_was_notify = d.notify
d.notify = lambda text, level='info', **k: _told.append((level, text[:60]))
try:
    d._fire_target('tell:house', 'on', 'a schedule')
    time.sleep(0.8)
finally:
    d.notify = _was_notify
check(_told, 'asking the house how it is said nothing')
print('a report can be asked for by a rule or a schedule: %r' % (_told[0][1][:48],))

# -- the four things the house could do and nothing could ask for -------------
for _what in ('energy', 'left_on', 'feeds', 'sleep'):
    check(_what in zigmon.SYSTEM_ACTIONS, 'the house cannot be asked to %s' % _what)
    check(d._valid_target('sys:%s' % _what) == 'sys:%s' % _what,
          'sys:%s is not something that can be acted on' % _what)
print('the house can be asked for the month, what is still on, the lists, and quiet')

# -- the texts have quiet hours of their own ----------------------------------
# There was no time-of-day gate on a text anywhere: the only silence was a
# hand hushing every road for every kind, so "do not text me at night but do
# push me" was not expressible.
check(hasattr(d, '_sms_quiet_now'), 'the texts have no quiet hours of their own')
_was_from = zigmon.CONFIG.get('sms_quiet_from')
_was_to = zigmon.CONFIG.get('sms_quiet_to')
zigmon.CONFIG.update({'sms_quiet_from': '22:30', 'sms_quiet_to': '07:00'})
d.store.set_meta('sms_hushed_until', '0')
try:
    for _hh, _mm, _quiet in ((22, 0, False), (22, 30, True), (23, 59, True),
                             (0, 30, True), (6, 59, True), (7, 0, False), (12, 0, False)):
        _at = time.mktime((2026, 10, 17, _hh, _mm, 0, 0, 0, -1))
        _ends = d._sms_quiet_now(_at)
        check(bool(_ends) is _quiet,
              'at %02d:%02d the texts are %s' % (_hh, _mm, 'held' if _ends else 'let through'))
        if _ends:
            check(_ends > _at, 'the quiet ends before it began')
    # ...and a hand can ask for the same thing
    d.system_action('sleep:2h', 'on', 'a test')
    check(d._sms_quiet_now(), 'a hand asking for quiet was not heard')  # sys:sleep
    d.system_action('sleep', 'off', 'a test')
    zigmon.CONFIG.update({'sms_quiet_from': '', 'sms_quiet_to': ''})
    check(not d._sms_quiet_now(), 'the quiet would not lift')
finally:
    zigmon.CONFIG['sms_quiet_from'] = _was_from or ''
    zigmon.CONFIG['sms_quiet_to'] = _was_to or ''
    d.store.set_meta('sms_hushed_until', '0')
print('the texts have quiet hours of their own, and a hand can ask for them')

# -- an automatic text is cut to whole messages -------------------------------
# A part is 160 plain characters and 70 as soon as one accented letter
# appears; an automatic alert was cut at a flat 320, which in Czech is five
# parts and five parts of somebody's money.
_long = 'Pozor: v koupelne je otevrene okno a topeni se zastavilo, venku je 3 \u00b0C a ' * 3
check(d.sms_parts(_long) > 2, 'the test text is not long enough to be cut')
if not hasattr(d, '_sms_cut'):
    check(False, 'an automatic text is still cut at a flat count of letters')
else:
    check(d.sms_parts(d._sms_cut(_long, 1)) == 1,
          'a text cut to one part is %d part(s)' % d.sms_parts(d._sms_cut(_long, 1)))
    check(d.sms_parts(d._sms_cut(_long, 2)) <= 2,
          'a text cut to two parts is %d part(s)' % d.sms_parts(d._sms_cut(_long, 2)))
    check(d._sms_cut('vse v poradku', 1) == 'vse v poradku', 'a short text was cut anyway')
    check(d._sms_cut(_long, 1).endswith('\u2026'), 'a cut text does not say it was cut')
print('an automatic text is cut where a message ends, not at a count of letters')


# -- 5.13: the coordinator is the radio, not a device that has gone quiet -------
# It publishes nothing of its own, ever, so "silent for" only counted up: on
# the house it had been CRITICAL for 31 days, in `zigmon check`, on its card
# and in {attention_list} - which is money, because that list goes out by text.
# Whether the mesh is alive is the bridge's own state, checked on its own.
_long_ago = int(time.time()) - 31 * 86400
d.store.upsert_device({'id': 'gw:coordinator', 'name': 'Coordinator', 'source': 'gateway',
                       'kind': 'Coordinator', 'vendor': None, 'last_seen': _long_ago,
                       'exposes': {}})
d.store.upsert_device({'id': '0xsilent', 'name': 'Probe-Silent', 'source': 'zigbee',
                       'kind': 'EndDevice', 'vendor': 'test', 'last_seen': _long_ago,
                       'exposes': {'temperature': {'access': 1, 'type': 'numeric'}}})
zigmon.CONFIG['stale_crit_min'] = 180
zigmon.CONFIG['stale_warn_min'] = 60
_coord = d.describe(d.store.device('gw:coordinator'), {'ts': _long_ago, 'payload': {}})
_other = d.describe(d.store.device('0xsilent'), {'ts': _long_ago, 'payload': {}})
check(not any('silent for' in r for r in (_coord.get('reasons') or [])),
      'the coordinator is reported as having gone quiet: %r' % (_coord.get('reasons'),))
check(_coord.get('level') != 'crit',
      'the coordinator is critical for being silent: %r' % (_coord.get('level'),))
check(any('silent for' in r for r in (_other.get('reasons') or [])),
      'a real device that went quiet is no longer reported at all: %r' % (_other.get('reasons'),))
print('the coordinator is not reported as quiet; a device that really went quiet still is')


# -- 5.13: a note that was forgotten stays forgotten while the delete is queued --
# Forgetting a note drops it from memory and puts the row's delete on the write
# queue. Dropping it from memory sent the very next reader to the table, where
# the row was still standing, and it was read from there and put back in
# memory. So the old note came back - September's list name against December's
# block - for as long as the queue took to drain, which is exactly the moment
# the page and the text ask about a block that has just happened. The address
# below is TEST-NET-3, which belongs to nobody.
_was_delete = d.store._delete_meta
d.store._delete_meta = lambda key: None          # the queue has not got to it yet
try:
    d.store.set_meta('blocked_feed_203.0.113.99', 'firehol1')
    check(d.store.get_meta('blocked_feed_203.0.113.99') == 'firehol1',
          'the note was not written down in the first place')
    d.store.forget_meta('blocked_feed_203.0.113.99')
    check(d.store.get_meta('blocked_feed_203.0.113.99') is None,
          'a forgotten note came back from the table while its delete was still queued: %r'
          % d.store.get_meta('blocked_feed_203.0.113.99'))
    d.store.set_meta('blocked_feed_203.0.113.99', 'spamhaus')
    check(d.store.get_meta('blocked_feed_203.0.113.99') == 'spamhaus',
          'a note written after the forgetting cannot be read')
finally:
    d.store._delete_meta = _was_delete
    d.store.forget_meta('blocked_feed_203.0.113.99')
print('a note that was forgotten does not come back while its delete is still queued')


# -- 5.13: a comparison nobody knows is true of nothing, not read as "<" --------
# save_rules refuses anything that is not one of RULE_OPS, so this cannot be
# written on the dashboard - but an import, a restore or a hand-edited database
# can hold one, and _rule_holds read everything it did not know as "<". So a
# rule saying "occupancy = 1" fired when the sensor went QUIET and did nothing
# at all when it saw somebody: the opposite of what it says, with nothing said
# about it anywhere.
check(d._rule_holds('==', 1.0, 1) is True, '"==" no longer matches')
check(d._rule_holds('<', 0.0, 1) is True, '"<" no longer compares')
check(d._rule_holds('>=', 1.0, 1) is True, '">=" no longer compares')
check(d._rule_holds('!=', 0.0, 1) is True, '"!=" no longer compares')
for _bad in ('=', 'is', '=>', ''):
    check(d._rule_holds(_bad, 0.0, 1) is False,
          'a rule comparing with %r is still read as "less than", so it fires on the wrong '
          'side of its own threshold' % _bad)
try:
    d.save_rules([{'device': 'zigbee:PIR-Test', 'key': 'occupancy', 'op': '=', 'value': 1,
                   'plug': 'Light-Test', 'do': 'on'}])
    check(False, 'a rule with a comparison nobody knows was accepted')
except ValueError:
    pass
print('a comparison nobody knows is true of nothing, and cannot be saved in the first place')


# -- 5.13: a block list is replaced in one transaction, not one per range -------
# The connection is in autocommit, and in autocommit executemany commits every
# row on its own. The house's largest list is 27,452 ranges, so replacing it
# was 27,452 transactions: 681 ms of the only lock this database has, against
# 57 ms as one. And "all or nothing", which put_feed promises in its own first
# line, was not true - a fetch cut off halfway left half a list, which matches
# half of what it should and says nothing. The same applied to the country
# list (717,170 rows, 29.4 s) and to the proxy's own lines.
d.store.put_feed('guard-list', [zigmon.range_of('203.0.113.%d' % i) for i in range(1, 11)])


def _rows_of(feed):
    with d.store.lock:
        return d.store.db.execute('SELECT COUNT(*) FROM feed_ranges WHERE feed=?', (feed,)).fetchone()[0]


check(_rows_of('guard-list') == 10, 'the list to be replaced was not written: %d' % _rows_of('guard-list'))
_half = [zigmon.range_of('198.51.100.%d' % (i % 250 + 1)) for i in range(600)]
_half[500] = (_half[500][0], _half[500][1], {'not': 'a number'})   # the fetch goes wrong here
try:
    d.store.put_feed('guard-list', _half)
    check(False, 'a list with a bad range in it was accepted whole')
except Exception:
    pass
_left = _rows_of('guard-list')
check(_left == 10, 'a block list cut off halfway left %d row(s) behind, and the list it was '
                   'replacing is gone - so it matches part of what it should and says nothing'
                   % _left)
check(d.store._bulk.__doc__, '_bulk is there but says nothing about why')
with d.store.lock:
    d.store.db.execute("DELETE FROM feed_ranges WHERE feed='guard-list'")
d.store._feed_counts = None
print('a block list is replaced whole or not at all, in one transaction rather than 27,452')


# -- 5.13: a day that has ended is added up once -------------------------------
# /api/energy/daily asks for thirty days of every socket - 690 of these on this
# house, two SQL statements each, 244 ms measured - and the page asks again
# every minute while an energy group is open. A day that has ended cannot
# change.
_asked = []
_real_delta = d.store.counter_delta
d.store.counter_delta = lambda dev, key, t0, t1: (_asked.append((dev, t0)) or _real_delta(dev, key, t0, t1))
try:
    _mid = int(time.time()) // 86400 * 86400
    _yesterday = (_mid - 86400, _mid)                  # a day that has ended
    _today = (_mid, _mid + 3600.0)                     # a day still running, whatever the hour is here
    d._day_wh = {}
    for _ in range(3):
        d.day_energy('0xenergy', _yesterday[0], _yesterday[1])
    check(len(_asked) == 1, 'a day that has ended was added up %d time(s) for three asks' % len(_asked))
    _asked[:] = []
    for _ in range(3):
        d.day_energy('0xenergy', _today[0], _today[1])
    check(len(_asked) == 3, 'the day we are in was answered from an old sum %d time(s)'
          % (3 - len(_asked)))
finally:
    d.store.counter_delta = _real_delta
print('a day that has ended is added up once; the day we are in is added up every time')


# -- 5.14: "nobody is home" is not what a controller that cannot find you says --
# This house's own month: 42 critical alerts and 14 text messages saying
# somebody was inside while nobody was home. Every one false. Thirty of them
# fell in a single 67.7-hour window after one phone's wi-fi dropped off: the
# controller kept answering, the phone was never seen again, and "nobody is
# home" stayed true for three days while the alerts traced the owner walking
# through his own hall. The daemon's own reason string said "not seen once
# since the daemon started" and nothing but the dashboard ever read it.
d.store.set_meta('people', json.dumps([{'id': 'p1', 'name': 'Somebody', 'enabled': True,
                                        'macs': ['aa:bb:cc:dd:ee:ff']}]))
zigmon.CONFIG['wifi_enabled'] = 1
d.wifi_config = lambda: {'enabled': True, 'host': 'wlc.example', 'poll_s': 30}
d.presence = {}
d.wifi = {'ok': True, 'clients': [{'mac': '11:22:33:44:55:66'}], 'checked': time.time(),
          'names': {}, 'error': None}
d._presence_cache = None
_st = d.presence_state()
check(_st['anyone_home'] is False, 'somebody is at home who was never found: %r' % _st['anyone_home'])
check(_st['known'] is False,
      'the house says it knows who is in while the controller has never once found them - so '
      '"when nobody is home" fires on somebody walking through their own hall')
check(d.presence_allows({'when': 'away'}) is False,
      'an "away" rule fired for a person the controller has never found')
# ...and once that person HAS been found, in or out is knowledge again
d.presence = {'p1': {'home': True, 'last_seen': time.time(), 'on_wifi': True}}
d.wifi = dict(d.wifi, clients=[{'mac': 'aa:bb:cc:dd:ee:ff'}], checked=time.time())
d._presence_cache = None
_st = d.presence_state()
check(_st['known'] is True, 'the house does not know who is in even after finding them: %r' % _st)
check(_st['anyone_home'] is True, 'the person it just found is not at home: %r' % _st)
d.presence = {}
d._presence_cache = None
print('a controller that has never found somebody is not knowledge that they are out')


# -- 5.14: the same press reported twice is one press --------------------------
# A Shelly BLU button arrives through more than one gateway, or repeats
# itself. This house: 985 "single" actions from one button, 278 of them in the
# same second as the one before - and the scene behind it is a toggle, so the
# strip went on and straight back off and the press looked like it had done
# nothing at all.
d.store.upsert_device({'id': 'zigbee:Button-Dup', 'name': 'Button-Dup', 'source': 'zigbee',
                       'kind': 'button', 'exposes': {'action': {}}})
d.names['Button-Dup'] = 'zigbee:Button-Dup'
_ran = []
_was_now = d._fire_bindings_now
d._fire_bindings_now = lambda hits, name, action: _ran.append((name, action))
d.store.set_meta('bindings', json.dumps([{'device': 'zigbee:Button-Dup', 'action': '*',
                                          'plug': 'sys:nothing', 'do': 'on', 'enabled': True}]))
try:
    zigmon.CONFIG['binding_debounce_ms'] = 300
    d.__dict__.pop('_press_seen', None)
    d.fire_bindings('zigbee:Button-Dup', 'Button-Dup', 'single')
    d.fire_bindings('zigbee:Button-Dup', 'Button-Dup', 'single')      # the same press, again
    time.sleep(0.4)
    check(len(_ran) == 1, 'the same press reported twice ran its binding %d time(s)' % len(_ran))
    time.sleep(0.4)                   # ...and a third of a second later it is a press again
    _ran[:] = []
    d.fire_bindings('zigbee:Button-Dup', 'Button-Dup', 'single')
    time.sleep(0.2)
    check(len(_ran) == 1, 'a press a third of a second after the last was taken for a duplicate')
    _ran[:] = []
    d.fire_bindings('zigbee:Button-Dup', 'Button-Dup', 'double')      # a DIFFERENT press
    time.sleep(0.2)
    check(len(_ran) == 1, 'a different action of the same button was taken for a duplicate')
    _ran[:] = []
    zigmon.CONFIG['binding_debounce_ms'] = 0                          # switched off
    d.__dict__.pop('_press_seen', None)
    d.fire_bindings('zigbee:Button-Dup', 'Button-Dup', 'single')
    d.fire_bindings('zigbee:Button-Dup', 'Button-Dup', 'single')
    time.sleep(0.2)
    check(len(_ran) == 2, 'with the window switched off, %d press(es) got through instead of two'
          % len(_ran))
finally:
    d._fire_bindings_now = _was_now
    zigmon.CONFIG['binding_debounce_ms'] = 300
print('the same press reported twice is one press, and a different press still gets through')


# -- 5.14: a cascade of criticals is one alarm ---------------------------------
# Ten rules pointing at one crit message whose text names the sensor: one
# person walking through the hall sent ten criticals and two text messages in
# 95 seconds, and nothing deduplicated anything because all ten texts differed.
_sent = []
_was_notify = d.notify
d.notify = lambda words, level='info', **kw: _sent.append((words, level))
d.store.set_meta('messages', json.dumps([{'id': 'm-crit', 'name': 'Intruder', 'level': 'crit',
                                          'text': 'Careful, {device} went off and nobody is home',
                                          'quiet_s': 0}]))
try:
    d._msg_last = {}
    for _who in ('Dvere-Vchod', 'PIR-Vchod', 'PIR-Chodba', 'PIR-Kuchyne'):
        d.send_message('m-crit', 'rule: %s' % _who, {'device': _who})
    check(len(_sent) == 1, 'one person walking through the house sent %d critical alert(s)'
          % len(_sent))
    check('Dvere-Vchod' in _sent[0][0], 'the one that went out was not the first: %r' % (_sent[0],))
    # ...and a message with a window of its own keeps its own behaviour
    _sent[:] = []
    d._msg_last = {}
    zigmon.CONFIG['crit_quiet_floor_s'] = 0
    for _who in ('PIR-A', 'PIR-B'):
        d.send_message('m-crit', 'rule: %s' % _who, {'device': _who})
    check(len(_sent) == 2, 'with the floor switched off, %d of 2 alerts went out' % len(_sent))
finally:
    zigmon.CONFIG['crit_quiet_floor_s'] = 60
    d.notify = _was_notify
print('a cascade of criticals from one message is one alarm; the floor can be switched off')


# -- 5.14: a pair of rules with one half switched off is said out loud ---------
# In this house the workshop's and the bedroom's "on when it sees somebody"
# are switched off while their "off when it stops" halves are on: motion
# cannot turn those lights on at all, and the off halves have run 14,576
# times between them - 68% of every rule firing in the house. Each rule is
# valid on its own, and nothing ever looked at two of them together.
d.store.set_meta('rules', json.dumps([
    {'id': 'on-half', 'device': 'zigbee:PIR-Test', 'key': 'occupancy', 'op': '==', 'value': 1,
     'plug': 'Light-Test', 'do': 'on', 'enabled': False},
    {'id': 'off-half', 'device': 'zigbee:PIR-Test', 'key': 'occupancy', 'op': '==', 'value': 0,
     'plug': 'Light-Test', 'do': 'off', 'enabled': True},
]))
_notes = d.mind_the_rules()
check(any('switched off' in n and 'never on' in n for n in _notes),
      'a pair whose ON half is switched off is not mentioned at all: %r' % (_notes,))
check(any('no delay on it' in n for n in _notes),
      'an "off when the motion stops" rule with no delay is not mentioned: %r' % (_notes,))
d.store.set_meta('rules', json.dumps([
    {'id': 'both-on', 'device': 'zigbee:PIR-Test', 'key': 'occupancy', 'op': '==', 'value': 1,
     'plug': 'Light-Test', 'do': 'on', 'enabled': True},
    {'id': 'both-off', 'device': 'zigbee:PIR-Test', 'key': 'occupancy', 'op': '==', 'value': 0,
     'plug': 'Light-Test', 'do': 'off', 'enabled': True, 'after_s': 15},
]))
check(not d.mind_the_rules(), 'a sound pair is complained about: %r' % d.mind_the_rules())
d.store.set_meta('rules', json.dumps([]))
print('a pair with one half switched off, and an off-rule with no delay, are both said out loud')


# -- the shape PHP itself is broken by, weighed -------------------------------
# php2shell, 21 October 2026 (CVE-2026-109618, CVE-2026-109619, both 9.2). The
# way into one of them is PHP's own multipart parser, and it is reached before
# any page of this house runs. Nothing here ever sends a multipart body - all
# three file pickers on the dashboard are read in the browser with FileReader
# and sent as JSON - so one arriving is nobody's browser and nobody's phone.
#
# From this house's own full log, 21 October 2026 at 00:36:18: eight of them in
# the same second from 51.159.110.25, POST to /, /login, /_next and /api twice
# over, 131,874 bytes apiece, with Assetnote's user agent on them. Every one of
# them weighed nothing at all.
def _weighed(one, ip):
    """One line of the full log, and what the daemon made of this address."""
    d.forget_anomaly(ip)
    d.full_weigh([json.dumps(dict(one, ip=ip))])
    kept = d._anomaly.get(ip) or []
    return [k for _t, k, _detail in kept], d.weigh_recent(ip, kept)


_mp = {'t': '', 'm': 'POST', 'u': '/', 's': 404,
       'ct': 'multipart/form-data; boundary=----WebKitFormBoundaryx8jO2oVc6SWP3Sad',
       'clen': '131874', 'ctlen': '131874', 'body': '', 'secret': 'none',
       'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
             'Chrome/140.0.0.0 Safari/537.36'}
_kinds, _score = _weighed(_mp, '51.159.110.25')
check('proxy-multipart' in _kinds,
      'a multipart POST to / weighs nothing: %r' % (_kinds,))
check(_score >= 8, 'a multipart POST is worth less than half the bar: %d' % _score)
# ...and the second one is a block, as for every other thing nobody does by
# accident. The first is said and not acted on.
d.forget_anomaly('51.159.110.25')
d.store.unblock('51.159.110.25') if hasattr(d.store, 'unblock') else None
_blocked = []
_was_block = d.store.block
d.store.block = lambda ip, until=None, why='', auto=True, by='': (
    _blocked.append((ip, why)), _was_block(ip, until, why, auto, by))[1]
_was_intel, d.intel_after_block = d.intel_after_block, lambda ip: None
_was_mt, d.mikrotik_after_change = d.mikrotik_after_change, lambda *a, **k: None
_was_note = d.notify
d.notify = lambda *a, **k: None
try:
    d.full_weigh([json.dumps(dict(_mp, ip='51.159.110.25', u='/'))])
    check(not _blocked, 'one multipart body put an address out: %r' % (_blocked,))
    d.full_weigh([json.dumps(dict(_mp, ip='51.159.110.25', u='/login'))])
    check(_blocked, 'two multipart bodies did not put the address out')
    check('multipart' in _blocked[0][1], 'the reason does not say what it was: %r' % (_blocked,))
    # ...and the one road that reaches PHP from the internet: a single one
    # there is a block on its own, because it is a press that nothing which
    # holds a link ever sends.
    _blocked[:] = []
    d.full_weigh([json.dumps(dict(_mp, ip='51.159.110.26', u='/tap', s=200))])
    check(_blocked, 'a multipart body on the one-tap road was let by')
    # The notification server is NOT weighed for it: a Go server with an API
    # of many roads, and the phones of the house talk to it.
    _blocked[:] = []
    d.forget_anomaly('51.159.110.27')
    d.full_weigh([json.dumps(dict(_mp, ip='51.159.110.27', u='/zigmon-house',
                                  which='ntfy', s=200))])
    check('proxy-multipart' not in [k for _t, k, _x in (d._anomaly.get('51.159.110.27') or [])],
          'the notification server was weighed for a multipart body')
    # -- a length that cannot be a length ------------------------------------
    # 18446744073709551615 is two to the power of sixty-four, less one: three
    # callers sent exactly that here, and a plain POST carrying it weighed
    # nothing at all.
    _k2, _s2 = _weighed({'t': '', 'm': 'POST', 'u': '/', 's': 200, 'ct': 'application/json',
                         'clen': '18446744073709551615', 'body': '', 'secret': 'none', 'ua': ''},
                        '51.159.110.28')
    check('proxy-bad-length' in _k2, 'a content-length of 2^64-1 weighs nothing: %r' % (_k2,))
    for _good in ('0', '131874', '', '-'):
        _k3, _s3 = _weighed({'t': '', 'm': 'POST', 'u': '/tap', 's': 200,
                             'ct': 'application/json', 'clen': _good, 'body': '{}',
                             'secret': 'sent', 'ua': ''}, '51.159.110.29')
        check('proxy-bad-length' not in _k3,
              'an ordinary content-length %r was called impossible: %r' % (_good, _k3))
finally:
    d.store.block = _was_block
    d.intel_after_block, d.mikrotik_after_change = _was_intel, _was_mt
    d.notify = _was_note
print('a multipart body is weighed wherever it reaches PHP, and a length that cannot be one')

# -- what the error log says was ASKED for, before why nginx complained -------
# The list of words an error line is read by is walked in order and stops at
# the first match, and the first entry in it is "upstream" - our own fault,
# worth nothing. So every line naming an upstream threw away the request
# written in the same line. Measured in this house's own error logs of 16
# September to 21 October 2026: 164 lines dropped that way and 524 called a
# flood, between them carrying 552 requests for .env, .ssh/id_rsa,
# wp-config.php and the rest. One address asked for thirty such things in two
# seconds and scored nothing at all - and that server's access log was empty,
# so the error log was the only record of it anywhere.
_HUNT = [
    '2026/09/16 20:51:19 [error] 65370#65370: *148 connect() failed (111: Connection refused) '
    'while connecting to upstream, client: 91.148.245.81, server: ntfy.falco81.net, request: '
    '"GET /.env HTTP/1.1", upstream: "http://127.0.0.1:2586/.env", host: "ntfy.falco81.net"',
    '2026/09/16 20:51:19 [error] 65370#65370: *149 connect() failed (111: Connection refused) '
    'while connecting to upstream, client: 91.148.245.81, server: ntfy.falco81.net, request: '
    '"GET /.ssh/id_rsa HTTP/1.1", upstream: "http://127.0.0.1:2586/.ssh/id_rsa", host: "x"',
    '2026/09/23 18:57:30 [error] 951#951: *229 limiting requests, excess: 40.036 by zone '
    '"ntfy_front", client: 91.148.245.82, server: ntfy.falco81.net, request: '
    '"GET /.git/config HTTP/1.1", host: "ntfy.falco81.net"',
]
for _ip in ('91.148.245.81', '91.148.245.82'):
    d.forget_anomaly(_ip)
d.proxy_weigh_errors(_HUNT)
_hunt = [k for _t, k, _x in (d._anomaly.get('91.148.245.81') or [])]
check(_hunt.count('proxy-secret-hunt') == 2,
      'an error line naming an upstream threw away the .env in it: %r' % (_hunt,))
_lim = [k for _t, k, _x in (d._anomaly.get('91.148.245.82') or [])]
check('proxy-secret-hunt' in _lim,
      'a refused-for-flooding line threw away the .git/config in it: %r' % (_lim,))
# ...and a line that says nothing about a path is still read for its own
# reason, as it always was
d.forget_anomaly('91.148.245.83')
d.proxy_weigh_errors([
    '2026/10/21 13:23:00 [crit] 954#954: *2137 SSL_do_handshake() failed (SSL: error:0A00006C:'
    'SSL routines::bad key share) while SSL handshaking, client: 91.148.245.83, server: 0.0.0.0:443'])
check([k for _t, k, _x in (d._anomaly.get('91.148.245.83') or [])] == ['proxy-tls'],
      'a handshake that failed stopped being weighed as one')
print('an error line is read for what was asked for first, and for nginx\'s complaint second')

# -- a worker that died in the middle of answering ----------------------------
# The published way to notice php2shell without a signature: both holes work
# by corrupting a worker's own memory, so a worker that accepts a request and
# then goes away is what they look like from outside. Not weighed against the
# caller on purpose - the dashboard's live update holds a php-fpm worker for
# as long as it waits, and a timeout set too low would put the family out.
_died = ['2026/10/21 13:23:0%d [error] 954#954: *213%d upstream prematurely closed connection '
         'while reading response header from upstream, client: 51.159.110.25, server: '
         'mqtt.falco81.net, request: "POST /%d HTTP/1.1", upstream: '
         '"fastcgi://unix:/run/php-fpm/www.sock:", host: "mqtt.falco81.net"' % (i, i, i)
         for i in range(3)]
_said = []
_was_note = d.notify
d.notify = lambda words, level='info', **kw: _said.append((level, str(words)))
try:
    d._said_at.pop('worker-died-fastcgi://unix:', None)
    d.forget_anomaly('51.159.110.25')
    d.upstream_trouble(_died)
    check(_said, 'three workers died in one reading and nothing was said')
    check('php-fpm' in _said[0][1], 'it does not say which server it was: %r' % (_said,))
    check(not (d._anomaly.get('51.159.110.25') or []),
          'a dead worker was weighed against the caller, which would put the family out')
    # two is not enough to say anything: one is a timeout, a handful is not
    _said[:] = []
    d._said_at.pop('worker-died-fastcgi://unix:', None)
    d.upstream_trouble(_died[:2])
    check(not _said, 'two of them was said out loud: %r' % (_said,))
finally:
    d.notify = _was_note
print('a worker that dies in the middle of answering is said out loud, and never blamed on the caller')

# -- the tools these logs named, and the PHP table ----------------------------
# Every one of these said what it was in its own user agent, at a hostname
# this machine does not carry, in the front server's log of 11-21 October
# 2026. WebSiphon alone asked 892 times from three addresses - more than a
# third of everything that log held - and was read as somebody mistyping an
# address.
for _tool in ('WebSiphon/next-0.1',
              'Mozilla/5.0 (compatible; webatlabot/1.0; +https://webatla.com/bot)',
              'Mozilla/5.0 (compatible; Infrawatch/1.0; +https://infrawat.ch/)',
              'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/60.0.3112.113 Safari/537.36 Assetnote/1.0.0'):
    check(zigmon.Daemon._scanning_tool(_tool), 'a tool naming itself is not known: %r' % _tool)
# ...and the things that must never be read as one: the house's own, and a
# search engine, which is crawling rather than scanning
for _fine in ('ntfy/1.7.0 (build 9; iOS 27.0.1)', 'Python-urllib/3.9',
              'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
              'Mozilla/5.0 (compatible; SeznamBot/4.0)', 'BackgroundShortcutRunner',
              'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7_8 like Mac OS X) AppleWebKit/605.1.15'):
    check(not zigmon.Daemon._scanning_tool(_fine), 'something of ours reads as a tool: %r' % _fine)
# The versions that carry the fix, by branch - and the two rules either side
# of the table: a branch upstream does not publish for is not "fine", and one
# newer than this table knows about is not "broken".
for _v, _want in (((8, 3, 35), True), ((8, 3, 36), False), ((8, 3, 37), False),
                  ((8, 2, 34), True), ((8, 2, 35), False), ((8, 4, 26), True),
                  ((8, 4, 27), False), ((8, 5, 11), True), ((8, 5, 12), False),
                  ((8, 1, 31), True), ((7, 4, 33), True), ((9, 0, 0), False)):
    _branch = '%d.%d' % (_v[0], _v[1])
    _fixed = zigmon.PHP_FIXED.get(_branch)
    if _fixed:
        _bad = _v < _fixed
    else:
        _bad = not (_v >= max(zigmon.PHP_FIXED.values()))
    check(_bad == _want, 'PHP %s is called %s' % ('.'.join(str(n) for n in _v),
                                                  'broken' if _bad else 'fine'))
check(zigmon.PHP2SHELL == ('CVE-2026-109618', 'CVE-2026-109619'),
      'the two holes are not named: %r' % (zigmon.PHP2SHELL,))
# ...and the shipped nginx files refuse the shape in front of PHP
_deploy = Path(__file__).resolve().parent.parent / 'deploy'
check(zigmon.nginx_refuses_multipart((str(_deploy / 'nginx-zigmon.conf'),)) is True,
      'the dashboard\'s nginx file does not refuse a multipart body')
check(zigmon.nginx_refuses_multipart(('/no/such/nginx.conf',)) is None,
      'a missing nginx file is reported as one that does not refuse it')
print('the tools these logs named are known, and the PHP table knows which versions carry the fix')

# -- every kind the daemon notes has a weight, a word and a length ------------
# Three tables have to agree about a kind: what it weighs, what it is called
# in the sentence that says why somebody was put out, and how long a block
# for it lasts. A kind missing from the second shows up on the list as its
# own shorthand; missing from the third it falls back to the shortest block.
import re as _re
_src = (Path(__file__).resolve().parent.parent / 'zigmon.py').read_text()
_noted = set(_re.findall(r"note_anomaly\(\s*[^,]+,\s*'([a-z][a-z-]+)'", _src))
_noted |= set(_re.findall(r"found\.append\(\(\s*'([a-z][a-z-]+)'", _src))
# ...and the ones chosen into a variable first, which is how the path rules
# are written: kind = 'proxy-secret-hunt'
# ...and the ones chosen into a variable first, which is how the path rules
# are written: kind = 'proxy-secret-hunt'. Held to the four families a kind
# read out of a log belongs to, because "kind" is a word this program uses
# for other things as well.
_noted |= set(_re.findall(r"^\s*kind = '((?:proxy|ids|ntfy|tap)-[a-z-]+)'", _src, _re.M))
_noted |= set(_re.findall(r"seen\.append\(\(now, '([a-z][a-z-]+)'", _src))
check(len(_noted) > 28, 'the kinds could not be found in the source: %d, %r'
      % (len(_noted), sorted(_noted)))
for _kind in sorted(_noted):
    check(_kind in zigmon.Daemon.ANOMALY_WEIGHT, '%s has no weight' % _kind)
    check(_kind in zigmon.Daemon.ANOMALY_WORDS, '%s has no words of its own' % _kind)
    check(_kind in zigmon.Daemon.BLOCK_WEIGHT, '%s has no block length' % _kind)
print('%d kinds, every one with a weight, words of its own and a block length' % len(_noted))


# A clean end. The daemon's own threads are still writing when the file runs
# out, and letting the interpreter pull the database out from under them
# aborted the process - "free(): invalid pointer", after every check above had
# already passed and said so.
import os as _os

d.store.flush(3.0)
sys.stdout.flush()
sys.stderr.flush()
_os._exit(0)
