import json, time, threading, sys
from pathlib import Path
sys.argv=['zigmon']
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # run from anywhere
import zigmon
zigmon.load_config()
# A house of its own: its own database, its own port and the PIN every check
# below types. Without them the replay ran against whatever config the machine
# had - with no PIN set every PIN check passed, "the hidden values were handed
# over" for an empty request, and with the dashboard's daemon running the
# port was taken before a single guard could run.
zigmon.CONFIG['db_file'] = '/tmp/zigmon-replay-check.db'
# A stale journal beside a fresh database is not this run's data: SQLite
# replays it, and a check then fails over rows the run never wrote. Both
# sidecars go with the file.
import os as _dbclean
for _ext in ('', '-wal', '-shm'):
    try:
        _dbclean.remove(zigmon.CONFIG['db_file'] + _ext)
    except OSError:
        pass

zigmon.CONFIG['api_port'] = 19741
zigmon.CONFIG['token_file'] = '/tmp/zigmon-replay-token'
zigmon.CONFIG['pin'] = '1234'
for _old in ('/tmp/zigmon-replay-check.db', '/tmp/zigmon-replay-check.db-wal', '/tmp/zigmon-replay-check.db-shm'):
    Path(_old).unlink(missing_ok=True)
d = zigmon.Daemon()
B = 'zigbee2mqtt/'
def send(t, p): d.handle(t, json.dumps(p).encode() if not isinstance(p, str) else p.encode())
send(B+'Temp-Balkon', {"battery":100,"humidity":45.48,"last_seen":"2026-09-01T11:16:21.138Z","linkquality":68,"temperature":24.77})
send(B+'bridge/state', {"state":"online"})
send(B+'bridge/info', {"version":"2.13.0","coordinator":{"type":"EmberZNet","ieee_address":"0x00","meta":{"revision":"8.0.2"}},"network":{"channel":25,"pan_id":40435},"permit_join":False})
devices = [
 {"ieee_address":"0x0000","type":"Coordinator","friendly_name":"Coordinator"},
 {"ieee_address":"0xc02cedfffe2c7248","type":"EndDevice","friendly_name":"Temp-Balkon","power_source":"Battery","model_id":"SBHT-203C","manufacturer":"Shelly",
  "definition":{"model":"SBHT-203C","vendor":"Shelly","description":"Humidity & temperature sensor","exposes":[
    {"access":5,"category":"diagnostic","label":"Battery","name":"battery","property":"battery","type":"numeric","unit":"%"},
    {"access":5,"label":"Temperature","name":"temperature","property":"temperature","type":"numeric","unit":"°C","description":"Measured temperature value"},
    {"access":5,"label":"Humidity","name":"humidity","property":"humidity","type":"numeric","unit":"%"},
    {"access":1,"label":"Linkquality","name":"linkquality","property":"linkquality","type":"numeric","unit":"lqi"}]}},
 {"ieee_address":"0xc02cedfffe4979aa","type":"EndDevice","friendly_name":"Button","definition":{"model":"SBBT-102C","vendor":"Shelly","description":"BLU Button Tough 1 ZB","exposes":[{"type":"enum","name":"action","property":"action","values":["single","double","long"]},{"property":"battery","type":"numeric","unit":"%","label":"Battery"}]}},
]
send(B+'bridge/devices', devices)
d.devices_settled(5.0)      # the list is taken in on its own worker now
send(B+'Button', {"action":"single","battery":100,"linkquality":112})
send(B+'Button/availability', {"state":"online"})
send(B+'Temp-Balkon/availability', "offline")
send(B+'Temp-Balkon', {"temperature":25.1,"humidity":40.0,"battery":12,"linkquality":30})
send('shellies/ht-temp/status/temperature:0', {"id":0,"tC":22.4,"tF":72.3})
send('shellies/ht-temp/status/humidity:0', {"id":0,"rh":47.5})
send('shellies/ht-temp/status/devicepower:0', {"id":0,"battery":{"V":2.9,"percent":85},"external":{"present":False}})
send('shellies/plug-lednice/status/switch:0', {"id":0,"output":True,"apower":85.2,"voltage":231.1,"current":0.38,"aenergy":{"total":1234.5,"by_minute":[1,2,3],"minute_ts":1}})
send(B+'bridge/event', {"type":"device_joined","data":{"friendly_name":"X","ieee_address":"0xabc"}})
devices[1]['friendly_name']='Temp-Venek'
send(B+'bridge/devices', devices)
d.devices_settled(5.0)
send(B+'Temp-Venek', {"temperature":26.0})
st = d.status()
print(json.dumps({k:v for k,v in st.items() if k!='devices'}, indent=1)[:700])
for dev in st['devices']:
    print(dev['name'], dev['id'], dev['level'], dev['reasons'], [ (h['key'], h['value'], h['unit']) for h in dev['headline']], dev['battery'], dev['availability'])
print(d.store.keys_for('0xc02cedfffe2c7248'))
print(d.store.history('0xc02cedfffe2c7248', ['temperature','humidity'], 3600))
for e in d.store.events(20): print(e)
print(d.store.stats())
print('aggregate', d.store.aggregate())
srv = zigmon.ApiServer(d); srv.start(); time.sleep(0.3)
for p in ['/api/status','/api/health','/api/devices','/api/device?name=Temp-Venek','/api/history?device=Temp-Venek&range=6h','/api/events','/api/nope','/api/history?device=zz']:
    c, r = zigmon.api_call(p); print(p, c, str(r)[:160])
# Every range a chart offers must be readable, not just the ones under a day.
# parse_while - which reads "on for ten minutes" and refuses anything longer
# than a day - once replaced parse_span here, and every chart past 24h came
# back 500. It was mended in one of the three places that had it, and the
# other two went on failing, so the guard names them all.
for _span in ('1h', '6h', '24h', '7d', '30d', '1y', '90m', '2w'):
    c, r = zigmon.api_call('/api/history?device=Temp-Venek&range=%s' % _span, token=d.token)
    assert c == 200 and r.get('range_s'), 'a chart range of %s was refused: %s %r' % (_span, c, r)
    c, r = zigmon.api_call('/api/history-multi?items=Temp-Venek|temperature&range=%s' % _span, token=d.token)
    assert c == 200 and r.get('range_s'), 'the Overview charts refused %s: %s %r' % (_span, c, r)
c, r = zigmon.api_call('/api/history?device=Temp-Venek&range=nonsense', token=d.token)
assert c == 400, 'a range that is not one said %s rather than asking for a better one' % c
print('guard: every chart range reads, from an hour to a year, and nonsense is refused not crashed')

c, r = zigmon.api_call('/api/reset','POST',{'scope':'events','pin':'0000'}, token=d.token, cli=False); print('wrongpin', c, r)
assert c == 403, 'erasing was let through without a sign-in'
c, r = zigmon.api_call('/api/reset','POST',{'scope':'events','pin':'1234'}, token='bad'); print('badtoken', c, r)
c, r = zigmon.api_call('/api/permit-join','POST',{'enable':True,'pin':'1234'}, token=d.token); print('pj', c, r)
c, r = zigmon.api_call('/api/reset','POST',{'scope':'device','device':'Button','pin':'1234'}, token=d.token); print('reset', c, r)
c, r = zigmon.api_call('/api/devices'); print([x['name'] for x in r['devices']])

# A save whose list is missing or is not a list must be refused, never taken
# as "save nothing": that once emptied every rule in the database.
d.save_rules([{'device': 'Temp-Venek', 'key': 'temperature', 'op': '>=', 'value': 20,
               'plug': 'notify', 'do': 'on', 'enabled': True}])
before = len(d.rules())
# A list of things that are not records is the same accident wearing a list:
# every validator skips what it does not recognise, so [1, 2, 3] cleaned
# itself down to nothing and that nothing was saved over everything.
for body in ({'pin': '1234'}, {'pin': '1234', 'rules': 'nope'}, {'pin': '1234', 'rules': None},
             {'pin': '1234', 'rules': [1, 2, 3]}, {'pin': '1234', 'rules': ['a', 'b']},
             {'pin': '1234', 'rules': [{'device': 'Temp-Venek', 'key': 'temperature', 'op': '>=',
                                        'value': 20, 'plug': 'notify', 'do': 'on'}, 7]}):
    c, r = zigmon.api_call('/api/rules', 'POST', body, token=d.token)
    assert c == 400 and not r.get('ok'), ('a bad save was taken: %r -> %s %r' % (body.get('rules'), c, r))
assert len(d.rules()) == before, 'a refused save changed the rules'
# and emptying it on purpose is still allowed
c, r = zigmon.api_call('/api/rules', 'POST', {'pin': '1234', 'rules': []}, token=d.token)
assert c == 200 and r.get('ok'), 'deleting the last rule was refused'
assert len(d.rules()) == 0
d.save_rules([{'device': 'Temp-Venek', 'key': 'temperature', 'op': '>=', 'value': 20,
               'plug': 'notify', 'do': 'on', 'enabled': True}])
print('guard: a save of anything that is not a list of records is refused, %d rule(s) untouched' % before)

# Neither rule queue may grow without bound. The gated one asks the Wi-Fi
# controller who is in, and a controller that accepts a connection and then
# says nothing holds that worker a whole timeout at a time - the readings
# behind it piled up for as long as that lasted, one tuple per reading, with
# nothing to stop them. The deferred writes have had a ceiling for years.
_was = d.RULE_BACKLOG
d.RULE_BACKLOG = 50
for _i in range(500):
    d.queue_rules('0xnosuchdevice', 'Nothing', {'temperature': _i})
assert len(d._rule_queue) <= 50 and len(d._rule_queue_gated) <= 50, \
    'the rule queues grew past their ceiling: %d / %d' % (len(d._rule_queue), len(d._rule_queue_gated))
assert d._rule_queue[-1][2]['temperature'] == 499, 'the newest reading was dropped rather than the oldest'
d._rule_queue.clear(); d._rule_queue_gated.clear()
d.RULE_BACKLOG = _was
print('guard: a rule queue nothing is draining drops the oldest, not the house')

def _reading(name, key):
    dev = [x for x in d.status()['devices'] if x['name'] == name][0]
    return next((h['value'] for h in dev['headline'] if h['key'] == key), None)


# Two readings inside one wall-clock second are two readings. describe() is
# worked out once per report and kept, and it knew a report by its timestamp,
# which is whole seconds: the second of the pair never reached the page at
# all - not on the next status, and not when the second turned over either,
# because the timestamp it was compared against had not changed. It waited
# for the cache to grow half a minute old. A button pressed twice, a socket
# answering right after it was switched, a sensor going on and off again.
send(B + 'Temp-Venek', {'temperature': 11.5})
_first = _reading('Temp-Venek', 'temperature')
send(B + 'Temp-Venek', {'temperature': 12.5})
_second = _reading('Temp-Venek', 'temperature')
assert _first == 11.5 and _second == 12.5, \
    'a second reading inside one second was lost: %r then %r' % (_first, _second)
print('guard: two readings inside one second both reach the page')

# And nothing that is not a finite number gets in. Python's JSON reader takes
# NaN, Infinity and 1e400 without a word - a firmware saying NaN for a reading
# it has not got is a real thing - and one of those in the status makes the
# whole answer something no JSON reader will take, so every dashboard stops
# updating until it goes away, and it does not go away.
send(B + 'Temp-Venek', {'temperature': 13.5})
for _bad in ('{"temperature": NaN}', '{"temperature": 1e400}', '{"temperature": -1e400}'):
    d.handle(B + 'Temp-Venek', _bad.encode())
assert _reading('Temp-Venek', 'temperature') == 13.5, 'a reading that is not a number was taken'
_text = json.dumps(d.status())
assert 'NaN' not in _text and 'Infinity' not in _text, 'the status is not valid JSON any more'
json.loads(_text, parse_constant=lambda c: (_ for _ in ()).throw(ValueError('bare ' + c)))
print('guard: NaN and infinity are refused at the door, and the status stays valid JSON')

# Not every editor saves records: the Overview saves the names of the cards it
# shows, which are plain text. Guarding them as records refused every add and
# every remove - the guard against losing everything took the Overview with it.
_cards = [x['id'] for x in d.store.devices()][:2]
assert len(_cards) == 2, 'the check needs two devices to put on the Overview'
c, r = zigmon.api_call('/api/overview-layout', 'POST', {'pin': '1234', 'items': _cards}, token=d.token)
assert c == 200 and r.get('ok'), 'a card could not be added to the Overview: %s %r' % (c, r)
assert d.overview_layout() == _cards, 'the cards were not kept: %r' % (d.overview_layout(),)
c, r = zigmon.api_call('/api/overview-layout', 'POST', {'pin': '1234', 'items': _cards[:1]}, token=d.token)
assert c == 200 and len(d.overview_layout()) == 1, 'a card could not be removed'
c, r = zigmon.api_call('/api/overview-layout', 'POST', {'pin': '1234', 'items': [1, 2, 3]}, token=d.token)
assert c == 400 and not r.get('ok'), 'the Overview took a list of numbers'
assert len(d.overview_layout()) == 1, 'a refused save changed the Overview'
print('guard: cards can be added to and taken off the Overview, and nonsense still cannot')

# --secret hands over passwords, so it must not hand them to anybody who asks.
for body in ({}, {'pin': ''}, {'pin': 'nope'}, {'pin': '0000'}):
    # without a sign-in or the root command line's key (5.19): the PIN that
    # used to stand here opens nothing
    c, r = zigmon.api_call('/api/secrets', 'POST', body, token=d.token, cli=False)
    assert c == 403 and not r.get('ok'), 'the hidden values were handed over for %r: %s' % (body, c)
c, r = zigmon.api_call('/api/secrets', 'POST', {'pin': '1234'}, token=d.token)
assert c == 200 and r.get('ok'), 'the right PIN was refused: %s %r' % (c, r)
groups = r.get('secrets')
assert isinstance(groups, list) and groups, 'the hidden values came back in no sections: %r' % (groups,)
for _g in groups:
    assert _g.get('title') and _g.get('why'), 'a section with no name or no reason: %r' % (_g,)
    for _item in _g['items']:
        assert _item.get('what'), '%s says nothing about what it is for' % _item.get('name')
# a wide enough window that another guard's own events cannot push this out -
# and the event written down first: it goes through the writer's queue, and
# read at once it was now and then not there yet
d.store.flush(3.0)
assert any('hidden values' in (e.get('detail') or '') for e in d.store.events(200)), \
    'showing the hidden values was not written down'
print('guard: the hidden values need the PIN, and showing them is written down')

# A one-tap link is a secret in a URL, so: it must do its one thing, must not
# do anything else, must be withdrawable, and its token must never leave with
# the ordinary state - a watch is lost more often than a password is guessed.
# a real configured socket, since a link is only allowed to name one of those
_was = d.managed()
d.save_managed((_was.get('plugs') or []) + [{'name': 'Tap-Lamp', 'host': '127.0.0.1:19989'}],
               _was.get('sensors') or [])
c, r = zigmon.api_call('/api/taps', 'POST', {'pin': '1234', 'taps': [
    {'name': 'Probe lamp', 'target': 'Tap-Lamp', 'do': 'toggle'}]}, token=d.token)
assert c == 200 and r.get('ok'), (c, r)
_token = r['taps'][0]['token']
assert len(_token) > 20, 'the link secret is too short to be one'
c, r = zigmon.api_call('/api/status', 'GET', None, token=d.token)
assert 'token' not in zigmon.json.dumps(r.get('taps') or []), 'a link token went out with the state'
_fired = []
_keep = d._run_binding
d._run_binding = lambda p, do, origin, pulse_ms=None, stagger=0.0: _fired.append((p.name, do, origin))
c, r = zigmon.api_call('/api/tap/' + _token, 'GET', None)
assert c == 200 and r.get('ok'), 'the link did not work: %s %r' % (c, r)
time.sleep(0.4)
assert _fired and _fired[0][0] == 'Tap-Lamp', 'the link acted on the wrong thing: %r' % (_fired,)
assert 'link' in _fired[0][2], 'the events will not say a link did it: %r' % (_fired[0][2],)
c, r = zigmon.api_call('/api/tap/' + 'x' * 30, 'GET', None)
assert c == 404, 'a made-up link was accepted'
c, r = zigmon.api_call('/api/taps', 'POST', {'pin': '1234', 'taps': []}, token=d.token)
assert c == 200 and not d.taps(), 'a link could not be withdrawn'
_fired[:] = []
c, r = zigmon.api_call('/api/tap/' + _token, 'GET', None)
assert c == 404 and not _fired, 'a withdrawn link still works'
d._run_binding = _keep
# and a link seen by the wrong person is replaced rather than withdrawn: the
# same one thing, a new address, the old one dead at once
c, r = zigmon.api_call('/api/taps', 'POST', {'pin': '1234', 'taps': [
    {'name': 'Probe lamp', 'target': 'Tap-Lamp', 'do': 'toggle'}]}, token=d.token)
_id = r['taps'][0]['id']
_old = r['taps'][0]['token']
c, r = zigmon.api_call('/api/taps/address', 'POST', {'pin': '1234', 'id': _id, 'roll': True}, token=d.token)
assert c == 200 and r.get('ok'), (c, r)
# the address may be /tap/<token> or ?t=<token>, so take the last piece
_new = r['url'].replace('?t=', '/').rsplit('/', 1)[1]
assert _new != _old, 'rolling gave the same address back'
c, r = zigmon.api_call('/api/tap/' + _old, 'GET', None)
assert c == 404, 'the old address still works after rolling'
c, r = zigmon.api_call('/api/tap/' + _new, 'GET', None)
assert c == 200 and r.get('ok'), 'the new address does not work'
c, r = zigmon.api_call('/api/taps/address', 'POST', {'id': _id, 'roll': True}, token=d.token, cli=False)
assert c == 403, 'an address was rolled without the PIN'
c, r = zigmon.api_call('/api/taps', 'POST', {'pin': '1234', 'taps': []}, token=d.token)
# switched off keeps the link and its address and refuses to act on it
c, r = zigmon.api_call('/api/taps', 'POST', {'pin': '1234', 'groups': ['Upstairs'], 'taps': [
    {'name': 'Quiet one', 'target': 'Tap-Lamp', 'do': 'toggle', 'enabled': False, 'group': 'Upstairs'}]},
    token=d.token)
assert c == 200 and r['taps'][0]['enabled'] is False, r
assert r['taps'][0]['group'] == 'Upstairs', 'the section was not kept on the link'
_off = r['taps'][0]['token']
_fired[:] = []
c, r = zigmon.api_call('/api/tap/' + _off, 'GET', None)
assert c == 404 and not _fired, 'a switched-off link still acted: %s %r' % (c, _fired)
assert 'switched off' in (r.get('error') or ''), r
assert (d.editor_groups().get('taps') or []) == ['Upstairs'], 'the section order was not kept'
# a link may be asked how things stand, and asking must not switch anything
c, r = zigmon.api_call('/api/taps', 'POST', {'pin': '1234', 'taps': [
    {'name': 'Ask me', 'target': 'Tap-Lamp', 'do': 'toggle'}]}, token=d.token)
_ask = r['taps'][0]['token']
_again = d._run_binding                      # the stub is put back further up
d._run_binding = lambda p, do, origin, pulse_ms=None, stagger=0.0: _fired.append((p.name, do, origin))
_fired[:] = []
c, r = zigmon.api_call('/api/tap/' + _ask + '?ask', 'GET', None)
assert c == 200 and r.get('ok'), (c, r)
assert not _fired, 'asking switched something: %r' % (_fired,)
assert r.get('state') in ('on', 'off', 'mixed', ''), r
assert ' is ' in (r.get('message') or ''), 'asking said nothing about the state: %r' % (r,)
# _run_binding is stubbed above, so the press is caught there; the daemon
# waits a third of a second before reading the state back
c, r = zigmon.api_call('/api/tap/' + _ask, 'GET', None)
assert c == 200 and r.get('ok'), (c, r)
assert _fired, 'pressing it did nothing'
assert 'is now' in (r.get('message') or ''), 'pressing said nothing about the state: %r' % (r,)
d._run_binding = _again
# A scene is not one thing, so "is it on" means "is the house as it leaves
# it". Where every step says plainly on or off that can be answered; where
# they toggle it cannot be, and the sockets are counted instead.
d.save_scenes([{'name': 'Tap scene', 'actions': [{'target': 'Tap-Lamp', 'do': 'off', 'after_s': 0}]}])
_sid = 'scene:' + d.scenes()[0]['id']
c, r = zigmon.api_call('/api/taps', 'POST', {'pin': '1234', 'taps': [
    {'name': 'Scene link', 'target': _sid, 'do': 'toggle'}]}, token=d.token)
_stoken = r['taps'][0]['token']
d.plugs['Tap-Lamp'].output = False
c, r = zigmon.api_call('/api/tap/' + _stoken + '?ask', 'GET', None)
assert r.get('state') == 'on' and 'set' in (r.get('message') or ''), \
    'a scene whose steps are all done reads as: %r' % (r,)
d.plugs['Tap-Lamp'].output = True
c, r = zigmon.api_call('/api/tap/' + _stoken + '?ask', 'GET', None)
assert r.get('state') == 'off' and 'not set' in (r.get('message') or ''), \
    'a scene whose steps are undone reads as: %r' % (r,)
assert r.get('state') != '', 'a scene has no state at all'
# The battery figures walk a month of history for every cell, so nobody may
# be made to wait for them: a stale answer goes back at once and the work
# happens on a thread of its own, once however many ask.
_first = d.battery_health()
d._battery_cache = (time.time() - 400, _first)
_made = []
_keep_refresh = d._battery_refresh
d._battery_refresh = lambda: (_made.append(1), _keep_refresh())[1]
_worst = 0
for _ in range(20):
    _t0 = time.time()
    d.battery_health()
    _worst = max(_worst, (time.time() - _t0) * 1000)
assert _worst < 250, 'a caller waited %.0f ms for the battery figures' % _worst
time.sleep(1.5)
assert len(_made) == 1, 'the refresh was started %d times, not once' % len(_made)
d._battery_refresh = _keep_refresh
# A device as the API says it is worked out once per report, not once per
# request - a status is asked for several times a second with a page open.
# The saving is only safe if a new reading still comes straight through.
_dev = [x for x in d.store.devices() if x.get('source') == 'zigbee']
if _dev:
    _one = _dev[0]
    d.status()
    d.record(_one['id'], _one['name'], {'temperature': 39.5})
    time.sleep(0.25)
    _shown = {x['id']: x for x in d.status()['devices']}[_one['id']]
    _val = (_shown.get('values') or {}).get('temperature') or {}
    assert str(_val.get('value')) == '39.5', \
        'the status held a stale reading: %r' % (_val.get('value'),)
    d.record(_one['id'], _one['name'], {'temperature': 21.0})
print('guard: a new reading is in the status at once, however much is remembered')
print('guard: nobody waits for the battery figures, and they are worked out once')
# A telling link answers and switches nothing, and every prepared report has
# to come out as a sentence - a missing figure must close its own clause
# rather than leave "peaked at  W" to be read aloud.
_fired[:] = []
_said = {}
d._tap_tries = {}                  # the earlier guards used up this address's tries
for _key, _title, _tpl in zigmon.Daemon.TELL_PRESETS:
    d._tap_tries = {}
    _shape = {'name': 'Tells ' + _key, 'target': 'tell', 'do': _key}
    if not _tpl:
        continue
    c, r = zigmon.api_call('/api/taps', 'POST', {'pin': '1234', 'taps': [_shape]}, token=d.token)
    assert c == 200 and r.get('ok'), 'a telling link was refused: %s %r' % (_key, r)
    c, r = zigmon.api_call('/api/tap/' + r['taps'][0]['token'], 'GET', None)
    assert c == 200 and r.get('ok'), (_key, c, r)
    _text = r.get('message') or ''
    _said[_key] = _text
    assert _text, '%s said nothing at all' % _key
    assert '{' not in _text, '%s left a fact unfilled: %r' % (_key, _text)
    assert '  ' not in _text, '%s has a gap where a figure was missing: %r' % (_key, _text)
    assert ' .' not in _text and ' ,' not in _text, '%s reads badly: %r' % (_key, _text)
assert not _fired, 'a telling link switched something: %r' % (_fired,)
# A row just added and not filled in must not refuse the whole list: after
# pressing Add there is always one, and refusing everything for it reads as
# "saving is broken".
c, r = zigmon.api_call('/api/taps', 'POST', {'pin': '1234', 'taps': [
    {'name': 'Keeper', 'target': 'Tap-Lamp', 'do': 'toggle'},
    {'name': '', 'target': '', 'do': 'toggle'}]}, token=d.token)
assert c == 200 and r.get('ok'), 'an unfinished row refused the whole list: %s %r' % (c, r)
assert len(r['taps']) == 1, 'the unfinished row was kept: %r' % (r['taps'],)
c, r = zigmon.api_call('/api/taps', 'POST', {'pin': '1234', 'taps': [
    {'name': 'Half done', 'target': '', 'do': 'toggle'}]}, token=d.token)
assert c == 400 and 'row 1' in (r.get('error') or ''), \
    'a half-filled row must say which row it is: %r' % (r,)
print('guard: an unfinished link is passed over, a half-filled one says which row it is')
# a link saved by an older version carried the report in a field of its own;
# it must come back as a target of "tell" with the report as its action
c, r = zigmon.api_call('/api/taps', 'POST', {'pin': '1234', 'taps': [
    {'name': 'From before', 'target': '', 'do': 'tell', 'say': 'weather'}]}, token=d.token)
assert c == 200 and r.get('ok'), r
assert r['taps'][0]['target'] == 'tell' and r['taps'][0]['do'] == 'weather', \
    'an older telling link did not come across: %r' % (r['taps'][0],)
print('guard: a telling link saved by an older version is carried over')
print('guard: %d prepared report(s), each a whole sentence, and none of them switch anything'
      % len(_said))
print('guard: a link on a scene says whether the house is as that scene leaves it')
print('guard: a link says how things stand, and asking changes nothing')
print('guard: a switched-off link keeps its address and does nothing with it')
# Pressing a link is not guessing at one: counting every use meant ten presses
# in a minute locked the address out, and the answer read as though the link
# were broken.
d._tap_tries = {}
c, r = zigmon.api_call('/api/taps', 'POST', {'pin': '1234', 'taps': [
    {'name': 'Pressed often', 'target': 'tell', 'do': 'house'}]}, token=d.token)
_often = r['taps'][0]['token']
for _ in range(15):
    c, r = zigmon.api_call('/api/tap/' + _often, 'GET', None)
    assert c == 200, 'a link refused after being pressed a few times: %s %r' % (c, r)
for _ in range(11):
    zigmon.api_call('/api/tap/' + 'q' * 30, 'GET', None)
c, r = zigmon.api_call('/api/tap/' + 'q' * 30, 'GET', None)
assert c == 429, 'a guesser was not stopped: %s' % c
d._tap_tries = {}
# A gateway that does not answer in time has not refused: it sends one message
# at a time, and three questions in a row leave the later ones waiting past our
# patience while the replies go out perfectly well. Writing "failed" about a
# message that arrives is worse than writing nothing.
import socket as _socket
_keep_open = getattr(d, '_sms_open', None)
zigmon.CONFIG.update({'sms_enabled': True, 'sms_api': 'cgi', 'sms_host': '127.0.0.1',
                      'sms_port': 9, 'sms_timeout_s': 1, 'sms_send_gap_s': 0})
d._sms_open = lambda url, timeout: (_ for _ in ()).throw(_socket.timeout('timed out'))
d.sms_send('+420777123456', 'a reply', why='reply')
d._sms_open = lambda url, timeout: (_ for _ in ()).throw(OSError('connection refused'))
d.sms_send('+420777123456', 'another', why='reply')
_notes = zigmon.json.loads(d.store.get_meta('sms_log') or '[]')
assert _notes[1]['ok'] is None, 'a message that timed out was written down as failed: %r' % (_notes[1],)
assert _notes[0]['ok'] is False, 'a refusal was not written down as one: %r' % (_notes[0],)
assert any('may still have gone out' in (e.get('detail') or '') for e in d.store.events(10)), \
    'nothing said that the message may have gone out anyway'
if _keep_open is not None:
    d._sms_open = _keep_open
print('guard: a gateway that does not answer is not a message that failed')
# A long message is several messages, and one patience for all of them meant a
# status reply listing nine sockets got the same fifteen seconds as "on".
assert zigmon.Daemon.sms_parts('on') == 1
assert zigmon.Daemon.sms_parts('x' * 161) == 2
assert zigmon.Daemon.sms_parts('\u011b' * 71) == 2, 'a diacritic halves what fits in a part'
_long = ('Doma jsou: Falco ON Plugs: Plug-UPS, Plug-WorkshopPC, Plug-WorkshopTV, '
         'PlugX4-TVLoznice-SamsungTV, PlugX4-TVLoznice-Switch, PlugX4-TVObyvak-1, '
         'PlugX4-TVObyvak-2, PlugX4-TVObyvak-3, PlugX4-TVObyvak-4 ON Lights: none')
assert zigmon.Daemon.sms_parts(_long) == 2, 'the reply that timed out is %d part(s)' % zigmon.Daemon.sms_parts(_long)
# and the inbox is not asked for while something is going out
d._sms_sending = time.time()
d._sms_last_poll = 0
assert d.sms_poll() is None, 'the inbox was polled in the middle of a send'
d._sms_sending = 0
# Throwing the history away must stick: the next read of the device's inbox
# used to write every one of them straight back, so "forget all" looked as
# though it had done nothing at all.
d.sms_note('in', '+420111', 'home', True, 'was already here', key='fk1')
d.sms_note('in', '+420111', 'status', True, 'was already here', key='fk2')
d._sms_seen['fk1'] = 0
d._sms_seen['fk2'] = 0
_ok, _msg = d.sms_forget()
assert _ok, _msg
assert not zigmon.json.loads(d.store.get_meta('sms_log') or '[]'), 'the history was not cleared'
assert 'fk1' in d._sms_binned and 'fk2' in d._sms_binned, \
    'forgotten messages are not remembered as forgotten, so they come back'
# and a fresh daemon must remember it too
assert 'fk1' in set(zigmon.json.loads(d.store.get_meta('sms_binned') or '[]')), \
    'what was forgotten is not written down, so a restart brings it back'
print('guard: what is forgotten stays forgotten, restart or not')
print('guard: patience grows with the message, and nothing else talks to the gateway while it sends')
# "By hand" on a link takes the target over the way a button press does: rules
# and schedules leave it alone until it is switched off again.
_was_holds = d.store.get_meta('manual_holds')
for _hold, _want in ((True, True), (False, False)):
    d.store.set_meta('manual_holds', '{}')
    c, r = zigmon.api_call('/api/taps', 'POST', {'pin': '1234', 'taps': [
        {'name': 'Handy', 'target': 'Tap-Lamp', 'do': 'on', 'hold': _hold}]}, token=d.token)
    assert c == 200 and r['taps'][0]['hold'] is _hold, r
    d._tap_tries = {}
    zigmon.api_call('/api/tap/' + r['taps'][0]['token'], 'GET', None)
    time.sleep(1.3)
    _held = bool(d.manual_holds())
    assert _held is _want, ('a link with "by hand" on did not take the target over'
                            if _want else 'a link without it took the target over anyway')
d.store.set_meta('manual_holds', _was_holds or '{}')
print('guard: a link set to act by hand takes the target over, and one that is not leaves it')
print('guard: a link may be pressed as often as one likes, and a guesser is stopped')
print('guard: a link can be given a new address, and the old one dies with it')
d.save_managed(_was.get('plugs') or [], _was.get('sensors') or [])
print('guard: a one-tap link does its one thing, and stops the moment it is withdrawn')

# A sensor whose bindings have gone is found by comparing it with its own kind,
# and a Tuya or an alarm contact with nothing configured is right to have
# nothing - saying otherwise often enough teaches somebody to ignore the lot.
def _sensor(name, ieee, binds=True, model='SBHT-003C', maker='Shelly', clusters=('genBasic',)):
    ep = {'bindings': [], 'configured_reportings': [],
          'clusters': {'input': list(clusters), 'output': []}}
    if binds:
        ep['bindings'] = [{'cluster': {'name': 'msTemperatureMeasurement'}},
                          {'cluster': {'name': 'genPowerCfg'}}]
        ep['configured_reportings'] = [{'cluster': {'name': 'msTemperatureMeasurement'},
                                        'attribute': 'measuredValue',
                                        'maximum_report_interval': 3600}]
    return {'friendly_name': name, 'ieee_address': ieee, 'type': 'EndDevice',
            'power_source': 'Battery', 'manufacturer': maker, 'model_id': model,
            'definition': {'model': model}, 'endpoints': {'1': ep}}


_list = [_sensor('Probe-A', '0xaa1'), _sensor('Probe-B', '0xaa2'), _sensor('Probe-C', '0xaa3'),
         _sensor('Probe-Broken', '0xaa4', binds=False),
         _sensor('Probe-Tuya', '0xaa5', binds=False, model='TS0601', maker='_TZE200_zz'),
         _sensor('Probe-Door', '0xaa6', binds=False, model='MCCGQ11LM', maker='Aqara',
                 clusters=('ssIasZone',))]
for _x in _list:
    d.store.upsert_device({'id': _x['ieee_address'], 'name': _x['friendly_name'], 'source': 'zigbee',
                           'kind': 'EndDevice', 'vendor': 'x', 'model': _x['model_id'],
                           'last_seen': int(time.time()), 'exposes': {}})
d.note_bindings(_list)
_found = {x['name']: x for x in d.binding_check()}
assert 'Probe-Broken' in _found, 'the one with nothing configured was not noticed'
assert not _found['Probe-Broken']['excused']
assert 'Probe-Tuya' not in _found or _found['Probe-Tuya']['excused'], \
    'a Tuya with nothing configured was called broken'
assert 'Probe-Door' not in _found or _found['Probe-Door']['excused'], \
    'an alarm contact with nothing configured was called broken'
for _ok in ('Probe-A', 'Probe-B', 'Probe-C'):
    assert _ok not in _found, '%s is configured like its fellows and was still flagged' % _ok
print('guard: a sensor that has lost its bindings is found, and Tuya and alarm contacts are not')

# Mending has to leave a trail: what was asked for, why, and what came of it.
import types as _types


class _Broker(object):
    def publish(self, topic, payload, qos=0, retain=False):
        return _types.SimpleNamespace(rc=0)


_keep_client = d.client
d.client = _Broker()
d.connected = True
d._binding_waiting['0xaa4'] = 0
d.maybe_reconfigure('0xaa4')
time.sleep(0.3)
d.configure_answer({'status': 'error', 'error': 'Timeout', 'data': {'id': 'Probe-Broken'}})
d.maybe_reconfigure('0xaa4')
time.sleep(0.3)
d.configure_answer({'status': 'ok', 'data': {'id': 'Probe-Broken'}})
time.sleep(0.3)
_said = [e['detail'] for e in d.store.events(40) if e['kind'] == 'device']
assert any('set it up again' in x and 'try 1' in x for x in _said), 'the asking was not written down: %r' % _said[:4]
assert any('would not be set up again' in x for x in _said), 'the refusal was not written down'
assert any('says it took' in x for x in _said), 'the success was not written down'
assert '0xaa4' not in d._binding_waiting, 'it is still on the waiting list after it took'
d.client = _keep_client
print('guard: setting a device up again is written down, and so is what came of it')

# Forgetting a row is a way out of a stale one, so it must take the PIN, must
# drop only what was asked for, and must say so when there is nothing to drop.
for _body in ({'device': 'Probe-Broken'}, {'device': 'Probe-Broken', 'pin': 'nope'}):
    c, r = zigmon.api_call('/api/zigbee/bindings/forget', 'POST', _body, token=d.token, cli=False)
    assert c == 403, 'a row was forgotten without the PIN: %s %r' % (c, r)
_before = len(d.bindings_known())
c, r = zigmon.api_call('/api/zigbee/bindings/forget', 'POST',
                       {'pin': '1234', 'device': 'Probe-Broken'}, token=d.token)
assert c == 200 and r.get('ok'), (c, r)
assert len(d.bindings_known()) == _before - 1, 'forgetting took the wrong number of rows'
assert not any(x.get('name') == 'Probe-Broken' for x in d.bindings_known().values())
c, r = zigmon.api_call('/api/zigbee/bindings/forget', 'POST',
                       {'pin': '1234', 'device': 'Probe-Broken'}, token=d.token)
assert c == 400 and 'nothing is remembered' in (r.get('error') or ''), r
d.note_bindings(_list)                       # the bridge's next list brings it back
assert len(d.bindings_known()) == _before, 'it did not come back with the list'
print('guard: a remembered row can be forgotten, needs the PIN, and comes back with the list')

# Remembering the right shape, and the two ways that could go wrong.
_healthy = [_sensor('Keep-%d' % i, '0xbb%d' % i) for i in range(3)]
d.note_bindings(_healthy)
_out = d.commit_baselines(origin='the check')
assert _out['kept'] and not _out['refused'], 'a healthy model was not remembered: %r' % (_out,)
# every one of them replaced by a single empty newcomer
d.note_bindings([_sensor('Keep-new', '0xbb9', binds=False)])
d.store.upsert_device({'id': '0xbb9', 'name': 'Keep-new', 'source': 'zigbee', 'kind': 'EndDevice',
                       'vendor': 'x', 'model': 'SBHT-003C', 'last_seen': int(time.time()), 'exposes': {}})
_found = {x['name']: x for x in d.binding_check()}
assert 'Keep-new' in _found, 'a lone replacement with nothing configured was not noticed'
assert any('remembered' in w for w in _found['Keep-new']['why']), _found['Keep-new']['why']
# a model where nothing is configured anywhere must not be remembered: doing so
# would bless the very fault this looks for
d.note_bindings([_sensor('Bad-1', '0xcc1', binds=False, model='ZZ1'),
                 _sensor('Bad-2', '0xcc2', binds=False, model='ZZ1')])
_out = d.commit_baselines(origin='the check')
assert not _out['kept'] and _out['refused'], 'a model with nothing configured was remembered'
# nor one whose devices disagree
d.note_bindings([_sensor('Mix-1', '0xdd1', model='ZZ2'), _sensor('Mix-2', '0xdd2', binds=False, model='ZZ2')])
_out = d.commit_baselines(origin='the check')
assert not _out['kept'] and 'not configured alike' in _out['refused'][0]['why'], _out
print('guard: the right shape can be remembered, and a broken or muddled one cannot')

# A sensor group leaves a device behind it; removing the group must remove
# that too, or the lists and every status grow for ever.
probe = d.save_sensor_groups([{'name': 'probe', 'key': 'temperature', 'mode': 'average',
                               'members': ['Temp-Venek']}])[0]
d.refresh_group(probe['members'][0], 'Temp-Venek', {'temperature': 21.0})
made = [x for x in d.store.devices() if str(x['id']).startswith('grp:')]
d.save_sensor_groups([])
left = [x for x in d.store.devices() if str(x['id']).startswith('grp:')]
assert made and not left, ('group device not swept', made, left)
print('guard: a removed sensor group takes its device with it')


# A target has to be worked out before it can be fired. Twice a caller handed
# _fire_target the name that was written down instead: the answer went out,
# the event said it had been done, and nothing moved.
if not d.plugs:                      # the replay has no sockets of its own
    d.plugs['Probe-Plug'] = zigmon.PlugState('Probe-Plug', {'name': 'Probe-Plug', 'host': '127.0.0.1:19999'})
probe_plug = next(iter(d.plugs.values()), None)
if probe_plug is not None:
    hit = []
    keep_run = d._run_binding
    d._run_binding = lambda p, do, origin, pulse_ms=None, stagger=0.0: hit.append((p.name, do))
    d.save_sms_commands([{'phrase': 'probe', 'target': '*', 'do': 'toggle'}])
    zigmon.CONFIG['sms_allow'] = '+420000000000'
    zigmon.CONFIG['sms_reply'] = False
    d.sms_handle('+420000000000', 'probe')
    time.sleep(0.6)
    d._run_binding = keep_run
    d.save_sms_commands([])
    assert hit, 'an SMS command matched but switched nothing'
    print('guard: an SMS command actually switches its target')

    # The same words from the same number twice: the second lands in the slot
    # the first has just left, and was taken for it and thrown away.
    box, seen_calls = [], []
    def fake_rest(path, method='GET', payload=None, retry=True):
        if path == '/messages/status':
            return list(box)
        if path == '/modems/status':
            return [{'id': '3-1'}]
        if path == '/messages/actions/remove_messages':
            for one in payload['data']['sms_id']:
                for m in list(box):
                    if m['id'] == one:
                        box.remove(m)
        return {}
    keep_rest, keep_ready = getattr(d, '_rest', None), d.sms_ready
    d._rest = fake_rest
    d.sms_ready = lambda: True
    zigmon.CONFIG['sms_api'] = 'rest'
    zigmon.CONFIG['sms_clear_inbox'] = True
    d._sms_first_look = False
    d._run_binding = lambda p, do, origin, pulse_ms=None, stagger=0.0: seen_calls.append(do)
    d.save_sms_commands([{'phrase': 'probe', 'target': '*', 'do': 'toggle'}])
    for _ in range(2):
        box.append({'id': '1', 'sender': '+420000000000', 'message': 'probe', 'status': 'read'})
        d.sms_poll(force=True)
        time.sleep(0.4)
    d._run_binding = keep_run
    d.sms_ready = keep_ready
    if keep_rest is not None:
        d._rest = keep_rest
    d.save_sms_commands([])
    assert len(seen_calls) == 2, 'the same text twice was acted on %d time(s)' % len(seen_calls)
    print('guard: the same text sent twice is acted on twice')

    # Saying "home" and then "away" used to leave and arrive again: the grace
    # window from the arrival outlived the departure.
    d.save_people([{'name': 'Probe-Person', 'macs': ['aa:bb:cc:dd:ee:ff'], 'enabled': True}])
    who = [p for p in d.people() if p['name'] == 'Probe-Person'][0]
    moves = []
    keep_changed = d._presence_changed
    d._presence_changed = lambda p, home, evs: moves.append('arrive' if home else 'leave')
    def round_without_them():
        with d._wifi_lock:
            moved = d._settle_presence(who, set(), {}, time.time())
        if moved:
            d._presence_changed(who, moved == 'arrive', [moved])
    round_without_them()
    moves[:] = []
    d.presence_report('', 'home', origin='a test', person=who)
    round_without_them(); round_without_them()
    d.presence_report('', 'away', origin='a test', person=who)
    round_without_them(); round_without_them(); round_without_them()
    d._presence_changed = keep_changed
    d.save_people([p for p in d.people() if p['name'] != 'Probe-Person'])
    assert moves == ['arrive', 'leave'], 'home then away gave %r' % (moves,)
    print('guard: saying home then away arrives once and leaves once')

    # Four sockets on one box used to click in a different order every time:
    # each went off on a thread of its own and a Python lock hands itself to
    # whoever happens to wake, not to whoever waited longest.
    for i in range(4):
        d.plugs['Strip-%d' % i] = zigmon.PlugState('Strip-%d' % i,
                                                   {'name': 'Strip-%d' % i, 'host': '127.0.0.1:19998', 'switch_id': i})
    seen = []
    def slow(p, do, origin, pulse_ms=None, stagger=0.0):
        # What has to be in order is the sending: the box acts on them as they
        # arrive. So this notes the moment the command is handed over, then
        # takes its time answering - the last of the strip answering fastest,
        # which is exactly what used to shuffle the order.
        seen.append(p.name)
        n = int(p.name[-1]) if p.name.startswith('Strip-') else 0
        time.sleep(0.04 * max(0, 4 - n))
    d._run_binding = slow
    keep_scenes = d.scenes
    d.scenes = lambda: [{'id': 'strip', 'name': 'Strip', 'actions':
                         [{'target': 'Strip-%d' % i, 'do': 'off', 'after_s': 0} for i in range(4)]}]
    for _ in range(3):
        seen[:] = []
        d.run_scene('strip', 'a test')
        time.sleep(1.1)
        assert seen == ['Strip-0', 'Strip-1', 'Strip-2', 'Strip-3'], 'a strip clicked in the order %r' % (seen,)
    print('guard: the sockets on one box switch in the order they are written')

    # And every other shape of scene: a lone socket beside a strip, a step
    # with a delay of its own, four steps sharing one delay. Grouping the
    # sockets by box once broke the delayed ones altogether - they were put
    # in a list nobody read again.
    d.plugs['Lone'] = zigmon.PlugState('Lone', {'name': 'Lone', 'host': '127.0.0.1:19996'})
    def shape(name, actions, want):
        seen[:] = []
        d.scenes = lambda: [{'id': 'x', 'name': name, 'actions': actions}]
        d.run_scene('x', 'a test')
        time.sleep(2.0)
        got = [n for n in seen]
        assert sorted(got) == sorted(want), '%s: switched %r, wanted %r' % (name, got, want)
        strip = [n for n in got if n.startswith('Strip-')]
        assert strip == sorted(strip), '%s: the strip went %r' % (name, strip)
    shape('a lone socket beside a strip',
          [{'target': 'Strip-%d' % i, 'do': 'on', 'after_s': 0} for i in range(4)]
          + [{'target': 'Lone', 'do': 'on', 'after_s': 0}],
          ['Strip-0', 'Strip-1', 'Strip-2', 'Strip-3', 'Lone'])
    shape('one now and one later',
          [{'target': 'Strip-0', 'do': 'on', 'after_s': 0}, {'target': 'Strip-1', 'do': 'off', 'after_s': 0.3}],
          ['Strip-0', 'Strip-1'])
    shape('four sharing one delay',
          [{'target': 'Strip-%d' % i, 'do': 'off', 'after_s': 0.3} for i in range(4)],
          ['Strip-0', 'Strip-1', 'Strip-2', 'Strip-3'])
    # Four sockets told to toggle used to flip one by one, so once they were
    # out of step they stayed out of step for ever.
    for i in range(4):
        d.plugs['Strip-%d' % i].output = (i == 0)          # one on, three off
    seen[:] = []
    told = []
    d._run_binding = lambda p, do, origin, pulse_ms=None, stagger=0.0: told.append((p.name, do))
    d.scenes = lambda: [{'id': 'flip', 'name': 'Flip',
                         'actions': [{'target': 'Strip-%d' % i, 'do': 'toggle', 'after_s': 0} for i in range(4)]}]
    d.run_scene('flip', 'a button')
    time.sleep(0.8)
    assert told and all(do == 'off' for _, do in told), 'a mixed strip toggled to %r' % (told,)
    for i in range(4):
        d.plugs['Strip-%d' % i].output = False
    told[:] = []
    d.run_scene('flip', 'a button')
    time.sleep(0.8)
    assert told and all(do == 'on' for _, do in told), 'a strip all off toggled to %r' % (told,)
    d.scenes = keep_scenes
    d._run_binding = keep_run
    print('guard: every shape of scene switches everything it names, in order')
    print('guard: toggling a strip moves all of it the same way')

    # And a scene that mixes them: sockets from one box, sockets of their own,
    # and a Zigbee light, all toggling. Whatever is on decides for the rest.
    d.plugs['Lone-B'] = zigmon.PlugState('Lone-B', {'name': 'Lone-B', 'host': '127.0.0.1:19995'})
    # a light of our own, so this does not depend on what the database holds
    d.store.upsert_device({'id': '0xfeedface', 'name': 'Probe-Light', 'source': 'zigbee', 'kind': 'Light',
                           'vendor': 'test', 'model': 'probe', 'last_seen': int(time.time()),
                           'exposes': {'state': {'access': 3, 'type': 'binary', 'values': ['ON', 'OFF'],
                                                 'label': 'State', 'unit': '', 'category': '',
                                                 'min': None, 'max': None}}})
    light = next((t['value'] for t in d.zigbee_targets() if t['value'].endswith(':state')), None)
    assert light, 'the probe light was not offered as a target'
    if light:
        head = light.split(':')[1]
        d.live.setdefault(head, {})['payload'] = {'state': 'ON'}
        for i in range(4):
            d.plugs['Strip-%d' % i].output = False
        d.plugs['Lone'].output = False
        d.plugs['Lone-B'].output = False
        told[:] = []
        d._run_binding = lambda p, do, origin, pulse_ms=None, stagger=0.0: told.append((p.name, do))
        keep_zb = d._run_zigbee_switch
        d._run_zigbee_switch = lambda dev, key, do, origin, pulse_ms=None: told.append(('light', do))
        d.scenes = lambda: [{'id': 'mix', 'name': 'Mixed', 'actions':
                             [{'target': 'Strip-%d' % i, 'do': 'toggle', 'after_s': 0} for i in (0, 1, 2)]
                             + [{'target': 'Lone', 'do': 'toggle', 'after_s': 0},
                                {'target': 'Lone-B', 'do': 'toggle', 'after_s': 0},
                                {'target': light, 'do': 'toggle', 'after_s': 0}]}]
        d.run_scene('mix', 'a button')
        time.sleep(1.0)
        d._run_zigbee_switch = keep_zb
        d.scenes = keep_scenes
        d._run_binding = keep_run
        assert len(told) == 6, 'six things were named, %d moved: %r' % (len(told), told)
        assert all(do == 'off' for _, do in told), 'a mixed scene went %r' % (told,)
        print('guard: a scene mixing boxes, lone sockets and a light moves as one')

    # A small box answers 429 when asked too often, and a command that then
    # slept two seconds - logged only at debug - was the lag nobody could see.
    # Four sockets switched together must not need more than one confirming
    # read of the box, and a command told 429 must not sleep for long.
    told = []
    class Limited(object):
        def __init__(self):
            self.hits = []
        def call(self, method, params=None):
            now = time.time()
            self.hits[:] = [h for h in self.hits if now - h < 1.0]
            self.hits.append(now)
            told.append(method)
            return {}
    box = Limited()
    reads = []
    keep_poll = d.poll_plug
    d.poll_plug = lambda p, force=False: reads.append(time.time())
    for i in range(4):
        d.plugs['Strip-%d' % i].rpc = lambda box=box: box
    d._run_binding = keep_run
    d.plugs['Strip-0'].output = True
    keep_set = d.set_plug_output
    d.set_plug_output = lambda p, on, origin='the dashboard': (d._plug_switched(p, on, origin), (True, 'ok'))[1]
    d.scenes = lambda: [{'id': 'lim', 'name': 'Limited',
                         'actions': [{'target': 'Strip-%d' % i, 'do': 'toggle', 'after_s': 0} for i in range(4)]}]
    reads[:] = []
    d.run_scene('lim', 'a button')
    time.sleep(1.2)
    d.set_plug_output = keep_set
    d.poll_plug = keep_poll
    d.scenes = keep_scenes
    assert len(reads) <= 1, 'four switches led to %d confirming reads of one box' % len(reads)
    print('guard: four sockets switched together are confirmed with one read of the box')

    # ...and a command refused with 429 must end up landing. A box counts per
    # second, the four commands of a strip go out inside 125 ms, and the
    # fourth was refused every time. With one retry allowed, half a second
    # later - inside that same second - it was refused again and the command
    # raised: the socket never moved, while the first three did. That reads as
    # a lag rather than a miss, which is why it went unnoticed for so long.
    _at = time.time()
    _rpc = zigmon.ShellyRPC('127.0.0.1:1', label='Strip-3')
    _sent = []
    _keep_post = zigmon.ShellyRPC._post

    def _refusing(self, body, auth=None):
        """Refused twice, as a whole second of a box's limit does, then taken."""
        _sent.append(time.time())
        if len(_sent) <= 2:
            return 429, b'Too Many Requests', {}
        return 200, json.dumps({'id': 1, 'result': {'was_on': False}}).encode(), {}

    zigmon.ShellyRPC._post = _refusing
    try:
        _rpc.call('Switch.Set', {'id': 3, 'on': True})
        _landed = True
    except zigmon.PlugError:
        _landed = False
    finally:
        zigmon.ShellyRPC._post = _keep_post
    _took = time.time() - _at
    assert _landed, ('a command refused twice gave up and the socket never moved - '
                     'it needs more than one retry, and long enough to clear the '
                     'second the box counts in')
    assert len(_sent) == 3, 'a command refused twice was sent %d time(s)' % len(_sent)
    assert _took < 3.0, 'a command refused twice took %.1fs to land' % _took
    print('guard: a command refused with 429 is retried until it lands, inside %.1fs' % _took)

    # "all sockets" must not take the lights with it, nor the other way round.
    d.plugs['Lamp-1'] = zigmon.PlugState('Lamp-1', {'name': 'Lamp-1', 'host': '127.0.0.1:19994', 'role': 'light'})
    d.plugs['Lamp-2'] = zigmon.PlugState('Lamp-2', {'name': 'Lamp-2', 'host': '127.0.0.1:19993', 'role': 'light'})
    sockets = [t[1].name for t in d._binding_targets('*')]
    lamps = [t[1].name for t in d._binding_targets('*lights')]
    assert 'Lamp-1' in lamps and 'Lamp-2' in lamps, 'the lights were not found: %r' % (lamps,)
    assert not [n for n in sockets if n.startswith('Lamp-')], '"all sockets" took a light: %r' % (sockets,)
    assert not [n for n in lamps if not n.startswith('Lamp-')], '"all lights" took a socket: %r' % (lamps,)
    assert sockets, '"all sockets" found nothing'
    print('guard: all sockets and all lights keep to their own')

    # Neither star may reach a socket that is watched but not switched, nor
    # one that has been turned off in Devices. The two are excluded by
    # different means - monitor-only here, disabled by never entering the
    # list at all - so a change to either could quietly undo one of them.
    d.plugs['Watch-Only'] = zigmon.PlugState('Watch-Only', {'name': 'Watch-Only', 'host': '127.0.0.1:19992',
                                                            'monitor_only': True})
    d.plugs['Lamp-Watched'] = zigmon.PlugState('Lamp-Watched', {'name': 'Lamp-Watched', 'host': '127.0.0.1:19991',
                                                                'role': 'light', 'monitor_only': True})
    for spec in ('*', '*lights'):
        names = [t[1].name for t in d._binding_targets(spec)]
        assert 'Watch-Only' not in names, '%s took a monitor-only socket' % spec
        assert 'Lamp-Watched' not in names, '%s took a monitor-only light' % spec
    assert [t[1].name for t in d._binding_targets('*')], '"all sockets" found nothing at all'
    # and one turned off in Devices never reaches the list the daemon keeps
    _kept = d.managed()
    _saved = zigmon.json.loads(zigmon.json.dumps(_kept))
    _saved['plugs'] = (_saved.get('plugs') or []) + [{'name': 'Turned-Off', 'host': '127.0.0.1:19990',
                                                      'enabled': False}]
    d.save_managed(_saved['plugs'], _saved.get('sensors') or [])
    assert 'Turned-Off' not in d.plugs, 'a socket turned off in Devices is still being driven'
    assert 'Turned-Off' not in [t[1].name for t in d._binding_targets('*')]
    d.save_managed(_kept.get('plugs') or [], _kept.get('sensors') or [])
    print('guard: neither star reaches a monitor-only socket or one turned off')

srv.stop()
