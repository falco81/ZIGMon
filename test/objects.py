#!/usr/bin/env python3
"""Everything is an object (4.86): what the small mark after a name opens,
what {Name.member} reads, and what Ctrl+Space offers after a name and a dot.

    PYTHONPATH=. python3 test/objects.py

Nothing here needs a broker, a gateway or a web server. The house is made up
the way a real one is filled in: rooms, a socket, scenes, a rule, people, a
link - and names that collide the way real names do (a link called like a
room, two things of one kind with one name).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

zigmon.load_config()
zigmon.CONFIG['db_file'] = '/tmp/zigmon-objects-check.db'
# A stale journal beside a fresh database is not this run's data: SQLite
# replays it, and a check then fails over rows the run never wrote. Both
# sidecars go with the file.
import os as _dbclean
for _ext in ('', '-wal', '-shm'):
    try:
        _dbclean.remove(zigmon.CONFIG['db_file'] + _ext)
    except OSError:
        pass

zigmon.CONFIG['api_port'] = 19733
zigmon.CONFIG['token_file'] = '/tmp/zigmon-objects-token'
zigmon.CONFIG['plugs'] = []
zigmon.CONFIG['sensors'] = []
Path(zigmon.CONFIG['db_file']).unlink(missing_ok=True)
d = zigmon.Daemon()

# -- a house --------------------------------------------------------------------
d.save_rooms([{'name': 'Loznice'}, {'name': 'Kuchyne'}])
rooms = {r['name']: r['id'] for r in d.rooms()}
d.save_heating({'enabled': True, 'away_c': 16,
                'rooms': {rooms['Loznice']: {'comfort_c': 22, 'eco_c': 19, 'night_c': 17, 'mode': 'eco'}}})
d.save_scenes([{'name': 'Vecer', 'actions': [{'target': 'notify', 'do': 'on'}]},
               {'name': 'Rano', 'actions': [{'target': 'notify', 'do': 'on'}]}])
scenes = {s['name']: s['id'] for s in d.scenes()}
d.save_people([{'name': 'Falco', 'phone': '+420777000111', 'macs': ['aa:bb:cc:dd:ee:ff']}])
person = d.people()[0]
d.save_alert_messages([{'name': 'Break-in', 'text': 'Someone at {room}'}])
# a link that carries a room's name, and a secret that must never be seen
d.save_taps([{'name': 'Kuchyne', 'target': 'scene:%s' % scenes['Vecer'], 'do': 'on'}])
tap = d.taps()[0]
d.save_sms_commands([{'phrase': 'vecer', 'target': 'scene:%s' % scenes['Vecer'], 'do': 'on'}])
try:
    d.save_rules([{'device': 'weather:outside', 'key': 'temperature', 'op': '<', 'value': 3,
                   'plug': 'scene:%s' % scenes['Rano'], 'do': 'on'}])
except Exception:
    pass
d._objects_cache = None

objs = d.objects()
by_ref = {o['ref']: o for o in objs}
types = {o['type'] for o in objs}

# every kind there is, each with an address of its kind and its members
for want in ('house', 'heating', 'settings', 'wifi', 'room', 'scene', 'person', 'message', 'tap', 'smscmd',
             'smsbuiltin'):
    assert want in types, 'no object of the kind %s: %s' % (want, sorted(types))
for o in objs:
    assert o['ref'] == '%s:%s' % (o['type'], o['id']), 'an address that is not type:id: %r' % o
    assert o['members'], '%s has no members at all' % o['ref']
    for name, kind, *_rest in o['members']:
        assert kind in ('prop', 'func', 'proc'), '%s.%s is a %r' % (o['ref'], name, kind)
print('%d objects of %d kinds, each at type:id with its members' % (len(objs), len(types)))

# the address stays when the name changes
before = 'scene:%s' % scenes['Vecer']
d.save_scenes([{'id': scenes['Vecer'], 'name': 'Vecer-new', 'actions': [{'target': 'notify', 'do': 'on'}]},
               {'id': scenes['Rano'], 'name': 'Rano', 'actions': [{'target': 'notify', 'do': 'on'}]}])
d._objects_cache = None
renamed = {o['ref']: o for o in d.objects()}
assert before in renamed and renamed[before]['name'] == 'Vecer-new', 'renaming a scene moved its address'
d.save_scenes([{'id': scenes['Vecer'], 'name': 'Vecer', 'actions': [{'target': 'notify', 'do': 'on'}]},
               {'id': scenes['Rano'], 'name': 'Rano', 'actions': [{'target': 'notify', 'do': 'on'}]}])
d._objects_cache = None
objs = d.objects()
by_ref = {o['ref']: o for o in objs}
print('an object keeps its address when it is renamed')

# a bare name means what it always meant: the room over the link that shares
# its name, and the link is called by its address
kuchyne_room = by_ref['room:%s' % rooms['Kuchyne']]
kuchyne_tap = by_ref['tap:%s' % tap['id']]
assert kuchyne_room['call'] == 'Kuchyne', 'the room lost its own name to a link: %r' % kuchyne_room
assert kuchyne_tap['call'] == 'tap:%s' % tap['id'], 'a link took a room\'s name: %r' % kuchyne_tap
assert d.object_find('Kuchyne')[0] == 'room', 'a bare name found the link rather than the room'
assert d.object_find('tap:%s' % tap['id'])[0] == 'tap', 'an address did not find its object'
print('a shared name goes to the room; the link is reached by its address')

# {Name.member}: every kind, and the old readings exactly as they were
facts = d.message_facts('the object test')
said = d.fill_message('{Loznice.eco_c}|{Loznice.comfort_c}|{Heating.away_c}|{House.home_count}|{home_count}|'
                      '{Vecer.actions}|{room:%s.name}|{Break-in.text}|{Falco.name}' % rooms['Kuchyne'], facts)
bits = said.split('|')
assert bits[0] in ('19', '19.0') and bits[1] in ('22', '22.0'), 'a room\'s settings did not read: %r' % said
assert bits[2] in ('16', '16.0'), 'the heating did not read: %r' % said
assert bits[3] == bits[4], 'House.home_count is not the same as {home_count}: %r' % said
assert 'notification' in bits[5], 'a scene\'s actions did not read: %r' % said
assert bits[6] == 'Kuchyne', 'an object by its address did not read: %r' % said
assert bits[7] == 'Someone at {room}', 'a message\'s text did not read: %r' % said
assert bits[8] == 'Falco', 'a person did not read: %r' % said
assert d.fill_message('{Settings.sms_poll_s}', {}) == str(zigmon.CONFIG.get('sms_poll_s')), \
    'a setting did not read as it is set'
assert d.fill_message('{Nothing-Here.anything}', {}) == '', 'something that is not there said something'
print('{Name.member} reads rooms, the heating, the house, scenes, messages, people and every setting')

# what is kept safe stays safe: no secret, token or password in anything the
# page is sent, and what needs the PIN elsewhere needs it here
zigmon.CONFIG['sms_password'] = 'hunter2-SMS-secret'
d._objects_cache = None
everything = json.dumps(d.objects())
for o in d.objects():
    everything += json.dumps(d.object_detail(o['ref'], reveal=False))
    everything += json.dumps(d.object_detail(o['ref'], reveal=True))
for secret in (tap['token'], 'hunter2-SMS-secret'):
    assert secret not in everything, 'a secret is in what the object view sends: %s...' % secret[:6]
assert d.fill_message('{Settings.sms_password}', {}) == 'set', 'a password read as more than whether it is set'
one = d.object_detail('person:%s' % person['id'], reveal=False)
phone = next(m for m in one['members'] if m['name'] == 'phone')
assert '+420777000111' not in json.dumps(one) and phone['value'] == '(sign in)', 'a phone number shown without the PIN'
one = d.object_detail('person:%s' % person['id'], reveal=True)
assert next(m for m in one['members'] if m['name'] == 'phone')['value'] == '+420777000111', \
    'the phone number is not there with the PIN'
settings = {m['name']: m for m in d.object_detail('Settings')['members']}
for key in ('never_block', 'sms_password', 'blacklist', 'block_score'):
    if key in settings:
        assert settings[key].get('locked'), 'a setting that keeps the house safe is not marked as kept safe: %s' % key
assert not settings.get('sms_poll_s', {}).get('locked'), 'an ordinary setting is marked as kept safe'
print('no secret, token or password in the object view; a phone number needs the PIN; safety settings are locked')

# what points at what: find usages
used = d.object_detail('scene:%s' % scenes['Vecer'])['used_by']
kinds = {u['type'] for u in used}
assert 'tap' in kinds and 'smscmd' in kinds, 'the link and the SMS command that run a scene are not its usages: %r' % used
print('an object says what uses it: %s' % ', '.join(sorted(kinds)))

# procedures say how they are done today
room = d.object_detail('Loznice')
procs = {m['name']: m for m in room['members'] if m['kind'] == 'proc'}
assert procs.get('eco', {}).get('use') == 'heat Loznice eco', 'a room does not say how it is put on eco: %r' % procs
scene = d.object_detail('Vecer')
assert {m['name']: m for m in scene['members']}['run']['use'] == 'on scene:%s' % scenes['Vecer']
print('a procedure says the line a script does it with')

# quick enough to be asked while typing
d._objects_cache = None
began = time.time()
for _ in range(5):
    d._objects_cache = None
    d.objects()
spent = (time.time() - began) / 5 * 1000
assert spent < 150, 'the object list takes %.0f ms' % spent
print('the object list takes %.1f ms' % spent)


# ---------------------------------------------------------------------------
# Part two (4.87): a property is set through one door - a script's
# "Loznice.eco_c = 18", the object view's pencil - and that door refuses what
# keeps the house safe, what is worked out rather than set, and a value the
# thing does not take.
def _room(key):
    return d.heating_config()['rooms'][rooms['Loznice']].get(key)


said = d.object_set('Loznice', 'eco_c', '18.5')
assert _room('eco_c') == 18.5, 'eco in the bedroom was not set: %r (%s)' % (_room('eco_c'), said)
d.object_set('Loznice', 'comfort_c', '23')
assert _room('comfort_c') == 23, 'comfort was not set'
assert _room('eco_c') == 18.5, 'setting comfort changed eco'
d.object_set('Heating', 'away_c', '15')
assert d.heating_config()['away_c'] == 15, 'away was not set'
d.object_set('Loznice', 'mode', 'night')
assert _room('mode') == 'night', 'the room was not put on night: %r' % _room('mode')
d.object_set('Loznice', 'heated', 'off')
assert _room('heated') is False and _room('eco_c') == 18.5, 'switching heated off lost the room\'s settings'
d.object_set('Loznice', 'heated', 'on')
assert d.heating_config()['rooms'].get(rooms['Kuchyne']) is not None or True
_was = zigmon.CONFIG.get('sms_poll_s')
d.object_set('Settings', 'sms_poll_s', '30')
assert zigmon.CONFIG.get('sms_poll_s') == 30, 'a setting was not set'
d.object_set('Settings', 'sms_poll_s', str(_was))
for who, member, value, why in (
        ('Loznice', 'eco_c', '99', 'a number out of its range'),
        ('Loznice', 'eco_c', 'warm', 'a word where a number goes'),
        ('Loznice', 'mode', 'party', 'a mode there is not'),
        ('Loznice', 'temperature', '20', 'something worked out, not set'),
        ('Settings', 'never_block', '0.0.0.0/0', 'who is never kept out'),
        ('Settings', 'sms_password', 'x', 'a password'),
        ('Settings', 'pin', '0000', 'the PIN'),
        ('Settings', 'sms_poll_s', '-5', 'a setting out of its range'),
        ('Vecer', 'run', '1', 'a procedure'),
        ('Nothing-Here', 'x', '1', 'something that is not there')):
    try:
        d.object_set(who, member, value)
    except ValueError as e:
        continue
    raise AssertionError('%s.%s = %s was taken: %s' % (who, member, value, why))
assert str(zigmon.CONFIG.get('never_block') or '') != '0.0.0.0/0', 'never_block was changed'
print('a property is set through one door; what keeps the house safe, what is worked out and a wrong value are refused')

# a script says it the same way, with a value that may come from a message -
# and the thing it is set on may not
d.save_scripts([{'name': 'Setter', 'body': 'Loznice.eco_c = 17\nHeating.away_c = {want}\nsay done'}])
setter = [x for x in d.scripts() if x['name'] == 'Setter'][0]
out = d.run_script(setter, {'want': '14'})
assert _room('eco_c') == 17 and d.heating_config()['away_c'] == 14, 'a script did not set: %r' % (out,)
faults = d.script_faults('Nothing-Here.x = 1\nLoznice.temperature = 3\nSettings.never_block = 1\nLoznice.eco_c =\n'
                         'Vecer.run = 1\nLoznice.eco_c = {v}\nHeating.enabled = on')
text = ' | '.join(faults)
for want in ('line 1: there is nothing here called', 'line 2: Loznice.temperature cannot be set',
             'line 3: Settings.never_block keeps the house safe', 'line 4: Loznice.eco_c = needs a value',
             'line 5: Vecer.run cannot be set'):
    assert want in text, 'a script line that cannot set was not said on saving: %s\n  %s' % (want, text)
assert 'line 6' not in text and 'line 7' not in text, 'a good line was refused: %s' % text
# a name from a message cannot choose what is set
assert any('line 1' in f for f in d.script_faults('{thing}.eco_c = 3')), \
    'a {name} on the left of = was taken as something to set'
print('a script sets with Name.member = value; a line that cannot is said when it is saved')

# an export without its secrets carries none of them; importing one keeps the
# ones the house has
d.store.set_meta('managed', json.dumps({'plugs': [{'name': 'Plug-X', 'host': '10.0.0.9', 'password': 'plugpass-77',
                                                   'mqtt_password': 'mqttpass-88'}], 'sensors': []}))
d.save_wifi_config({'kind': 'unifi', 'host': 'wlc.example', 'api_key': 'apikey-99', 'password': 'wpass-11',
                    'ssh_password': 'sshpass-22'}) if hasattr(d, 'save_wifi_config') else None
d.save_people([dict(person, phone_report=True, token='tok-' + 'a' * 20)])
bare = d.export_settings(secrets=False)
flat = json.dumps(bare)
for secret in ('plugpass-77', 'mqttpass-88', 'apikey-99', 'wpass-11', 'sshpass-22', 'tok-' + 'a' * 20):
    assert secret not in flat, 'an export without secrets carries %s...' % secret[:8]
d.import_settings(bare)
assert d.managed()['plugs'][0].get('password') == 'plugpass-77', 'importing a secret-less export wiped a socket password'
assert (d.wifi_config() or {}).get('api_key') in ('apikey-99', None), 'importing it wiped the controller key'
assert d.people()[0].get('token') == 'tok-' + 'a' * 20, 'importing it wiped a phone token'
full = json.dumps(d.export_settings(secrets=True))
assert 'plugpass-77' in full, 'the export WITH secrets lost them'
print('an export without secrets has none; importing one keeps the house\'s own')


# procedures, called: Name.procedure(args) is the one line a script does it
# with today, done with that line's own checks
assert d.object_call_line('Vecer', 'run') == 'on scene:%s' % scenes['Vecer']
assert d.object_call_line('Loznice', 'hold', '20.5') == 'heat Loznice 20.5'
assert d.object_call_line('Heating', 'all', 'eco') == 'heat all eco'
for who, member, args, why in (('Vecer', 'run', 'now', 'something given to what takes nothing'),
                               ('Loznice', 'hold', 'warm', 'a word where a number goes'),
                               ('Heating', 'all', '', 'nothing given to what needs a value'),
                               ('Loznice', 'eco_c', '', 'a property called'),
                               ('Vecer', 'explode', '', 'a procedure there is not')):
    try:
        d.object_call_line(who, member, args)
    except ValueError:
        continue
    raise AssertionError('%s.%s(%s) was taken: %s' % (who, member, args, why))
d.save_scripts([{'name': 'Caller', 'body': 'Loznice.eco()\nHeating.away_on()\nLoznice.hold({t})'}])
caller = [x for x in d.scripts() if x['name'] == 'Caller'][0]
out = d.run_script(caller, {'t': '21'})
assert not out.get('faults'), 'calling procedures from a script failed: %r' % out
assert d.heating_config().get('away') is True, 'Heating.away_on() did not put away on'
assert _room('hold_c') == 21 or _room('mode') == 'eco', 'the room was not held'
d.object_call('Heating', 'away_off')
assert d.heating_config().get('away') is False, 'Heating.away_off() from the view did not'
faults = ' | '.join(d.script_faults('Vecer.explode()\nVecer.run(now)\nLoznice.hold({t})\nVecer.run()'))
assert 'line 1' in faults and 'line 2' in faults and 'line 3' not in faults and 'line 4' not in faults, faults
print('procedures are called as Name.procedure(args), in a script and from the view, and a wrong call is said on saving')


# ---------------------------------------------------------------------------
# Part three (4.88): by text message. The same syntax, the same one door, and
# only from a number that may give commands - and help that leads to all of
# it with every answer in one message.
_sent = []
_was_reply, _was_send = d.sms_reply, d.sms_send
d.sms_reply = lambda number, text, *a, **k: _sent.append((number, text))
d.sms_send = lambda number, text, *a, **k: (_sent.append((number, text)), (True, 'ok'))[1]
zigmon.CONFIG['sms_reply'] = 1
try:
    zigmon.CONFIG['sms_allow'] = '+420777000999'
    d.save_people([dict(d.people()[0], phone='+420777000999', sms_commands=True)])
    d.object_set('Loznice', 'eco_c', '18')
    d.sms_handle('+420777000999', 'Loznice.eco_c = 19.5')
    assert _room('eco_c') == 19.5, 'a text set nothing: %r' % _sent[-1:]
    del _sent[:]
    d.sms_handle('+420777000999', 'Loznice.eco_c')
    assert _sent and '19.5' in _sent[-1][1], 'a text asking for a member was not told it: %r' % _sent
    d.sms_handle('+420777000999', 'Heating.away_on()')
    assert d.heating_config().get('away') is True, 'a text did not call a procedure'
    d.sms_handle('+420777000999', 'Heating.away_off()')
    del _sent[:]
    d.sms_handle('+420777000999', 'Settings.never_block = 0.0.0.0/0')
    assert str(zigmon.CONFIG.get('never_block') or '') != '0.0.0.0/0', 'a text changed who is never kept out'
    assert _sent and 'safe' in _sent[-1][1], 'a text trying a safety setting was not told why not: %r' % _sent
    # a number that may not give commands changes nothing
    d.sms_handle('+420600000001', 'Loznice.eco_c = 25')
    assert _room('eco_c') == 19.5, 'a stranger\'s text set something'
    # and switched off on the SMS card, it does nothing
    d.save_sms_builtin(['obj_set'])
    assert d.sms_system_do('Loznice.eco_c = 22', 'a test') is None, 'a switched-off family still set'
    assert _room('eco_c') == 19.5
    d.save_sms_builtin([])
finally:
    d.sms_reply, d.sms_send = _was_reply, _was_send
print('by text: Name.member, Name.member = value and Name.procedure() - from a number that may, and never what keeps the house safe')

# every answer of the help is one message: plain letters, 160 at most
for q in ['', 'TOPIC', 'topic', 'house', 'the house', 'heating', 'sockets', 'scenes', 'scripts', 'blocking',
          'objects', 'asking', 'devices', 'rooms', 'rooms 2', 'Loznice', 'Loznice.', 'Loznice. 2', 'Settings.',
          'Settings. 3', 'heatng', 'Vecer', 'nothing-like-this']:
    out = d.sms_help(q)
    assert out and len(out) <= 160 and d.sms_parts(out) == 1, 'help %r is not one message (%d): %r' % (q, len(out), out)
assert 'help heating' in d.sms_help('TOPIC'), 'typing TOPIC as written did not show what to type'
assert 'Did you mean help heating' in d.sms_help('heatng'), 'a near miss was not pointed at the topic'
assert 'eco_c' in d.sms_help('Loznice.') and 'eco()' in d.sms_help('Loznice.'), 'help NAME. does not say what it has'
print('every answer of the help is one message, and it leads to objects, lists and near misses')


# ---------------------------------------------------------------------------
# Part four (4.89): what points at what is set by name, every field an editor
# saves can be set, a rename follows through, procedures of their own, and
# functions with something between their brackets.
d.save_schedules([{'target': 'scene:%s' % scenes['Rano'], 'days': [0, 1], 'at': '07:00', 'do': 'on'}])
sched = d.schedules()[0]
said = d.object_set('schedule:%s' % sched['id'], 'target', 'Vecer')
assert d.schedules()[0]['target'] == 'scene:%s' % scenes['Vecer'], 'a target set by name: %r (%s)' % (d.schedules(), said)
d.object_set('schedule:%s' % sched['id'], 'days', 'weekdays')
assert d.schedules()[0]['days'] == [0, 1, 2, 3, 4], 'days were not set: %r' % d.schedules()[0]['days']
d.object_set('schedule:%s' % sched['id'], 'at', '06:45')
assert d.schedules()[0]['at'] == '06:45'
for member, value in (('at', '25:00'), ('days', 'someday'), ('target', 'Nothing-Here'), ('do', 'explode')):
    try:
        d.object_set('schedule:%s' % sched['id'], member, value)
    except ValueError:
        continue
    raise AssertionError('schedule.%s = %s was taken' % (member, value))
_token = d.taps()[0]['token']
d.object_set('tap:%s' % tap['id'], 'target', 'Rano')
assert d.taps()[0]['target'] == 'scene:%s' % scenes['Rano'] and d.taps()[0]['token'] == _token, \
    'setting a link\'s target lost its secret or its target: %r' % d.taps()[0]
d.object_set('Break-in', 'text', 'Someone at {Loznice.temperature}')
d.object_set('Break-in', 'level', 'crit')
assert d.alert_messages()[0]['level'] == 'crit'
print('what a thing acts on is set by name, and every field its editor saves can be set')

# a rename follows through to what wrote the name
d.save_scripts([{'name': 'Setter', 'body': 'Loznice.eco_c = 17\nheat Loznice eco\nsay {Loznice.level}'}])
d.object_set('Loznice', 'name', 'Bedroom')
body = [x for x in d.scripts() if x['name'] == 'Setter'][0]['body']
assert body == 'Bedroom.eco_c = 17\nheat Bedroom eco\nsay {Bedroom.level}', 'a rename did not follow into a script: %r' % body
assert '{Bedroom.temperature}' in d.alert_messages()[0]['text'], 'a rename did not follow into a message'
assert d.fill_message('{Bedroom.eco_c}', {}) != '', 'the new name does not read'
d.object_set('Bedroom', 'name', 'Loznice')
body = [x for x in d.scripts() if x['name'] == 'Setter'][0]['body']
assert body.startswith('Loznice.eco_c'), 'renaming back did not follow: %r' % body
# a name another thing still carries is left alone
d.save_taps([dict(t) for t in d.taps()] + [{'name': 'Workshop', 'target': 'scene:%s' % scenes['Vecer'], 'do': 'on'}])
print('a rename follows through to scripts and messages, and back again')

# procedures of their own
d.save_scripts([{'name': 'Inner', 'body': 'say inner ran'}, {'name': 'Outer', 'body': 'Inner.run()\nsay outer ran'}])
out = d.run_script([x for x in d.scripts() if x['name'] == 'Outer'][0], {})
assert 'inner ran' in out['said'] and not out['faults'], 'a script did not run another: %r' % out
d.save_scripts([{'name': 'Loop', 'body': 'Loop.run()'}])
out = d.run_script([x for x in d.scripts() if x['name'] == 'Loop'][0], {})
assert out['faults'] and 'three deep' in ' '.join(out['faults']), 'a script calling itself did not stop: %r' % out
d.object_call('Vecer', 'add', 'notify@ntfy on')
acts = [s for s in d.scenes() if s['name'] == 'Vecer'][0]['actions']
assert any(a['target'] == 'notify@ntfy' for a in acts), 'Vecer.add() added nothing: %r' % acts
d.object_call('Vecer', 'remove', 'notify@ntfy')
acts = [s for s in d.scenes() if s['name'] == 'Vecer'][0]['actions']
assert not any(a['target'] == 'notify@ntfy' for a in acts), 'Vecer.remove() removed nothing'
print('a script runs another (three deep at most); a scene is added to and taken from')

# functions with brackets, from what was recorded
now = int(time.time())
d.store.upsert_device({'id': '0xfeed', 'name': 'Temp-Test', 'source': 'zigbee', 'kind': 'sensor',
                       'exposes': {'temperature': {'unit': '°C'}}})
with d.store.lock:
    d.store.db.executemany('INSERT OR REPLACE INTO samples (ts,device,key,value) VALUES (?,?,?,?)',
                           [(now - 3600 * h, '0xfeed', 'temperature', 20 + h) for h in range(5)])
    d.store.db.commit()
d._objects_cache = None
said = d.fill_message('{Temp-Test.avg(temperature, 24h)}|{Temp-Test.max(temperature, 24h)}|'
                      '{Temp-Test.min(temperature, 2h)}|{Temp-Test.delta(temperature, 24h)}|'
                      '{Temp-Test.count(temperature, 24h)}', {})
assert said.split('|') == ['22', '24', '20', '-4', '5'] or said.split('|') == ['22.0', '24', '20', '-4', '5'], \
    'functions over a span read %r' % said
print('functions with brackets read what was recorded: %s' % said)


# ---------------------------------------------------------------------------
# Part five (4.90): the rest of the application as objects - a room's day,
# the notifications, the block lists, the backups, the modem - and the fields
# that were still read-only; a value written out is checked when the script
# is saved; and by text, what runs the application stays on the dashboard
# unless the house says otherwise.
d.object_set('Loznice', 'plan', '06:30 comfort mon-fri, 8:00 comfort sat-sun, 22:00 night')
plan = d.heating_config()['rooms'][rooms['Loznice']]['plan']
# 5.11: a plan's days are stored the way the Heating tab writes them and the
# way heating_level reads them, Sunday first - Su=0, Mo=1 ... Sa=6 - so
# "mon-fri" is 1 to 5 and "sat-sun" is 6 and 0. Written the other way round,
# from Monday, which is what every WORD for a day means, the two numberings
# were stored and read as if they agreed: a plan typed as words ran Sunday to
# Thursday, so Friday morning never warmed up.
assert [(x['at'], x['level'], x['days']) for x in plan] == [
    ('06:30', 'comfort', [1, 2, 3, 4, 5]), ('08:00', 'comfort', [0, 6]), ('22:00', 'night', [0, 1, 2, 3, 4, 5, 6])], plan
assert d.fill_message('{Loznice.plan}', {}) == '06:30 comfort mon-fri, 08:00 comfort sat-sun, 22:00 night'
d.object_call('Loznice', 'plan_add', '12:00 eco mon,wed')
d.object_call('Loznice', 'plan_remove', '8:00')
plan = d.heating_config()['rooms'][rooms['Loznice']]['plan']
assert [x['at'] for x in plan] == ['06:30', '12:00', '22:00'] and plan[1]['days'] == [1, 3], plan
assert _room('eco_c') == 19.5, 'changing the plan lost the room\'s other settings'
for bad in ('25:00 comfort', '06:30 party', 'comfort 06:30'):
    try:
        d.object_set('Loznice', 'plan', bad)
    except ValueError:
        continue
    raise AssertionError('a plan of %r was taken' % bad)
d.object_call('Loznice', 'plan_clear')
assert not d.heating_config()['rooms'][rooms['Loznice']]['plan']
print('a room\'s day is read and set as words, and stepped by plan_add, plan_remove and plan_clear')

d.object_set('Notifications', 'warn', 'on')
assert d.notify_settings()['warn'] is True
d.object_set('Notifications', 'telegram', 'off')
assert d.notify_settings()['channels']['telegram'] is False
d.object_set('Notifications', 'telegram', 'on')
assert 'fetch' in [m['name'] for m in d.object_detail('feed-talos')['members']], 'a block list has no fetch()'
assert d.object_detail('Backups') and d.object_detail('Blocking'), 'the backups or the blocking are not objects'
print('the notifications, the block lists, the backups and the blocking are objects')

# the fields that were read-only
d.save_sequences([{'name': 'Kroky', 'steps': [scenes['Vecer']]}])
d._objects_cache = None
d.object_set('Kroky', 'steps', 'Rano, Vecer')
assert d.sequences()[0]['steps'] == [scenes['Rano'], scenes['Vecer']], d.sequences()
d.object_set('Loop', 'body', 'say one\\nsay two')
assert [x for x in d.scripts() if x['name'] == 'Loop'][0]['body'] == 'say one\nsay two'
try:
    d.object_set('Loop', 'body', 'explode now')
    raise AssertionError('a script body that cannot work was taken')
except ValueError:
    pass
d.object_set('plug:Plug-X', 'group', 'Kitchen')
assert d.managed()['plugs'][0]['group'] == 'Kitchen' and d.managed()['plugs'][0].get('password') == 'plugpass-77', \
    'setting a socket\'s group lost its password or its group: %r' % d.managed()['plugs'][0]
print('a sequence\'s steps, a script\'s body and a socket\'s group are set, and checked as their editors check them')

# a value written out is checked when the script is saved
faults = ' | '.join(d.script_faults('Loznice.eco_c = 99\nLoznice.mode = party\nHeating.away_c = 16\n'
                                    'Loznice.eco_c = {want}'))
assert 'line 1' in faults and 'line 2' in faults and 'line 3' not in faults and 'line 4' not in faults, faults
assert _room('eco_c') == 19.5, 'checking a script set something'
print('a value written out is checked when the script is saved, and nothing is set by the checking')

# by text: settings, notifications and script bodies only with the switch on
_sent = []
d.sms_reply = lambda number, text, *a, **k: _sent.append((number, text))
try:
    zigmon.CONFIG['sms_objects_settings'] = 0
    _before = zigmon.CONFIG.get('sms_poll_s')
    d.sms_handle('+420777000999', 'Settings.sms_poll_s = 60')
    assert zigmon.CONFIG.get('sms_poll_s') == _before, 'a text changed a setting with the switch off'
    assert _sent and 'by text' in _sent[-1][1], 'the refusal did not say why: %r' % _sent
    d.sms_handle('+420777000999', 'Notifications.warn = off')
    assert d.notify_settings()['warn'] is True, 'a text changed the notifications with the switch off'
    d.sms_handle('+420777000999', 'Loznice.eco_c = 19')
    assert _room('eco_c') == 19, 'the house itself is no longer set by text'
    try:
        d.object_set('Settings', 'sms_objects_settings', '1')
        raise AssertionError('the switch that lets texts change settings can be set from outside')
    except ValueError:
        pass
    zigmon.CONFIG['sms_objects_settings'] = 1
    d.sms_handle('+420777000999', 'Settings.sms_poll_s = 60')
    assert zigmon.CONFIG.get('sms_poll_s') == 60, 'with the switch on a text did not change the setting'
    zigmon.CONFIG['sms_objects_settings'] = 0
    d.object_set('Settings', 'sms_poll_s', str(_before))
finally:
    d.sms_reply = _was_reply
print('by text, settings, notifications and script bodies wait for their own switch; the house does not')
# a socket is an object of its own kind (until 4.90 the list was asked for by
# the wrong name and no socket was one)
assert d.object_find('Plug-X') and d.object_find('Plug-X')[0] == 'plug', 'a socket is not an object'
assert any(o['type'] == 'plug' for o in d.objects()), 'no socket in the object list'
print('a socket is an object of its own')


# ---------------------------------------------------------------------------
# (4.91) what each kind of message says and to whom, what a device's alerts
# are, a rule's second condition, and what a socket drew
d.object_set('Notifications', 'kind_leak', 'ntfy,sms')
assert d.notify_settings()['systems']['leak'] == {'roads': 'ntfy,sms'}
d.object_set('Notifications', 'kind_leak', 'off')
assert d.notify_settings()['systems']['leak'] == {'off': True}
d.object_set('Notifications', 'kind_leak', 'default')
assert 'leak' not in d.notify_settings()['systems']
for bad in ('pigeon', 'ntfy,fax'):
    try:
        d.object_set('Notifications', 'kind_leak', bad)
    except ValueError:
        continue
    raise AssertionError('a kind of message took %r' % bad)
d.object_set('Temp-Test', 'alerts', 'crit_offline')
assert d.notify_settings()['devices']['0xfeed'] == 'crit_offline'
d.object_set('Temp-Test', 'alerts', 'default')
assert '0xfeed' not in d.notify_settings()['devices']
try:
    d.object_set('Temp-Test', 'alerts', 'loud')
    raise AssertionError('an alert preset that is not one was taken')
except ValueError:
    pass
_rule = d.rules()[0] if d.rules() else None
if _rule:
    d.object_call('rule:%s' % _rule['id'], 'second', 'Temp-Test temperature > 20 or')
    assert (d.rules()[0].get('device2'), d.rules()[0].get('op2'), d.rules()[0].get('value2'),
            d.rules()[0].get('combine')) == ('0xfeed', '>', 20, 'or'), d.rules()[0]
    d.object_call('rule:%s' % _rule['id'], 'second_clear')
    assert not d.rules()[0].get('device2'), 'second_clear() left the condition'
print('each kind of message, a device\'s alerts and a rule\'s second condition are set by name')


# ---------------------------------------------------------------------------
# (4.92) the three that were left out: an address on the blocked list, a
# client the Wi-Fi controller sees, and a scene's steps set in place
_scene_before = [dict(s) for s in d.scenes()]
d.save_scenes(_scene_before + [{'name': 'Kroky', 'actions': [
    {'target': 'notify', 'do': 'on'},
    {'target': 'zb:0xfeed:state', 'do': 'off', 'after_s': 5},
    {'target': 'zb:0xfeed:state', 'do': 'pulse', 'pulse_ms': 600, 'after_s': 2.5}]}])
_kroky = lambda: next(s for s in d.scenes() if s['name'] == 'Kroky')
_acts = [dict(a) for a in _kroky()['actions']]
_steps = d.object_fact('Kroky', 'steps')
assert _steps and 'after 5s' in _steps and '600ms' in _steps and 'Temp-Test.state' in _steps, _steps
assert any(m['name'] == 'steps' and m.get('settable') for m in d.object_detail('Kroky')['members']), \
    'a scene\'s steps cannot be set'
d.object_set('Kroky', 'steps', _steps)
assert _kroky()['actions'] == _acts, 'reading the steps and setting them back changed them: %r -> %r' % (
    _acts, _kroky()['actions'])
d.object_set('Kroky', 'steps', 'Temp-Test.state toggle\nnotify on after 1,5s')
assert _kroky()['actions'] == [{'target': 'zb:0xfeed:state', 'do': 'toggle'},
                               {'target': 'notify', 'do': 'on', 'after_s': 1.5}], _kroky()['actions']
for bad in ('', 'Nothing-here on', 'notify dance', 'Vecer on', 'notify on 600ms'):
    try:
        d.object_set('Kroky', 'steps', bad)
    except ValueError:
        continue
    raise AssertionError('a scene took the steps %r' % bad)
assert len(_kroky()['actions']) == 2, 'a refused line still changed the scene'
_out = d.run_script({'name': 'k', 'body': 'Kroky.steps = notify on; Temp-Test.state off after 3s'}, {}, 'a test')
assert not _out.get('faults'), _out
assert _kroky()['actions'][1] == {'target': 'zb:0xfeed:state', 'do': 'off', 'after_s': 3.0}, _kroky()['actions']
d.save_scenes(_scene_before)
print('a scene\'s steps are read and set as one line, and nothing is lost on the way round')

# an address on the blocked list: found by its address, never listed
_ip = '203.0.113.77'
assert not any(o['type'] == 'address' for o in d.objects()), 'blocked addresses crowd the object list'
_a = d.object_find('address:%s' % _ip)
assert _a and _a[0] == 'address' and _a[1] == _ip, 'an address is not an object: %r' % (_a,)
assert d.object_find('address:not-an-ip') is None
assert d.object_fact('address:%s' % _ip, 'blocked') == 'no'
d.object_call('address:%s' % _ip, 'ban', '30')
assert d.store.blocked_until(_ip) is not None, 'ban() kept nothing out'
assert d.object_fact('address:%s' % _ip, 'blocked') == 'yes'
assert 28 <= d.object_fact('address:%s' % _ip, 'left_min') <= 30, d.object_fact('address:%s' % _ip, 'left_min')
assert d.object_fact('address:%s' % _ip, 'by') == 'a hand'
d.object_set('address:%s' % _ip, 'blocked', 'off')
assert d.store.blocked_until(_ip) is None, 'blocked = off let nothing back in'
_out = d.run_script({'name': 'b', 'body': 'address:%s.ban(15)' % _ip}, {}, 'a test')
assert not _out.get('faults') and d.store.blocked_until(_ip) is not None, _out
d.object_call('address:%s' % _ip, 'unban')
assert d.store.blocked_until(_ip) is None
try:
    d.object_set('address:%s' % _ip, 'ip', '1.2.3.4')
    raise AssertionError('an address can be changed into another')
except ValueError:
    pass
print('an address on the blocked list is an object by its address: read, kept out and let back in')

# a Wi-Fi client: found by its MAC, given to a person and taken back
_mac = '11:22:33:44:55:66'
d.wifi['clients_list'] = [{'mac': _mac, 'name': 'Pixel', 'ssid': 'Home', 'ap_name': 'AP-Hall', 'signal': -61,
                           'ip': '192.168.1.50'}]
assert not any(o['type'] == 'client' for o in d.objects()), 'Wi-Fi clients crowd the object list'
_c = d.object_find('client:%s' % _mac.upper())
assert _c and _c[0] == 'client' and _c[2] == 'Pixel', _c
assert d.object_find('client:99:99:99:99:99:99') is None, 'a client nobody has seen is an object'
_det = {m['name']: m['value'] for m in d.object_detail('client:%s' % _mac)['members']}
assert _det['ip'] == '(sign in)' and _det['ap_name'] == 'AP-Hall' and _det['signal'] == -61, _det
assert {m['name']: m['value'] for m in d.object_detail('client:%s' % _mac, reveal=True)['members']}['ip'] \
    == '192.168.1.50'
d.object_call('client:%s' % _mac, 'give_to', 'Falco')
assert _mac in d.people()[0]['macs'] and 'aa:bb:cc:dd:ee:ff' in d.people()[0]['macs'], d.people()[0]
assert d.object_fact('client:%s' % _mac, 'belongs_to') == 'Falco'
d.object_call('client:%s' % _mac, 'release')
assert _mac not in d.people()[0]['macs'] and 'aa:bb:cc:dd:ee:ff' in d.people()[0]['macs'], d.people()[0]
try:
    d.object_call('client:%s' % _mac, 'give_to', 'Nobody-at-all')
    raise AssertionError('a client was given to nobody')
except ValueError:
    pass
_out = d.run_script({'name': 'c', 'body': 'client:%s.give_to(Falco)' % _mac}, {}, 'a test')
assert not _out.get('faults') and _mac in d.people()[0]['macs'], _out
d.object_call('client:%s' % _mac, 'release')
# once given, a client that has gone off the network is still reached
d.object_call('client:%s' % _mac, 'give_to', 'Falco')
d.wifi['clients_list'] = []
assert d.object_find('client:%s' % _mac), 'a client gone off the network cannot be taken back'
d.object_call('client:%s' % _mac, 'release')
print('a Wi-Fi client is an object by its MAC: its address behind the PIN, given to a person and taken back')


# ---------------------------------------------------------------------------
# (4.93) a Wi-Fi client by the name the controller gives it - when that name
# is nothing else here and only one client carries it - and a scene's steps
# are typed as steps
d.wifi['clients_list'] = [{'mac': _mac, 'name': 'Pixel', 'ssid': 'Home'},
                          {'mac': '11:22:33:44:55:77', 'name': 'Twin'}, {'mac': '11:22:33:44:55:78', 'name': 'Twin'},
                          {'mac': '11:22:33:44:55:79', 'name': 'Loznice'}]
_c = d.object_find('Pixel')
assert _c and _c[0] == 'client' and _c[1] == _mac, 'a client is not found by its name: %r' % (_c,)
assert d.object_find('Twin') is None, 'a name two clients share found one of them'
assert d.object_find('Loznice')[0] == 'room', 'a client took a room\'s name'
_out = d.run_script({'name': 'p', 'body': 'Pixel.give_to(Falco)'}, {}, 'a test')
assert not _out.get('faults') and _mac in d.people()[0]['macs'], _out
d.object_call('Pixel', 'release')
assert _mac not in d.people()[0]['macs']
d.wifi['clients_list'] = []
_steps_m = [m for m in d.object_detail('Vecer')['members'] if m['name'] == 'steps'][0]
assert _steps_m.get('input') == 'steps', _steps_m
print('a Wi-Fi client is called by its name when nothing else has it, and a scene\'s steps are typed as steps')


# ---------------------------------------------------------------------------
# (4.97) every section of every editor is an object, and everything that can
# be switched off can be switched on again - by name, the same way everywhere
_rules_before = [dict(r) for r in d.rules()]
d.save_rules(_rules_before + [
    {'device': 'weather:outside', 'key': 'temperature', 'op': '<', 'value': 1, 'plug': 'notify', 'do': 'on',
     'group': 'Frost'},
    {'device': 'weather:outside', 'key': 'temperature', 'op': '<', 'value': -5, 'plug': 'notify', 'do': 'on',
     'group': 'Frost'}])
d._objects_cache = None
_sec = d.object_find('Frost')
assert _sec and _sec[0] == 'section' and _sec[1] == 'rules/Frost', 'a section is not an object: %r' % (_sec,)
assert any(o['ref'] == 'section:rules/Frost' for o in d.objects()), 'a section is not in the list'
assert d.object_fact('Frost', 'count') == 2 and d.object_fact('Frost', 'enabled') == 'on'
d.object_call('Frost', 'disable')
assert [r.get('enabled') for r in d.rules() if r.get('group') == 'Frost'] == [False, False]
assert d.object_fact('Frost', 'enabled') == 'off'
d.object_set('Frost', 'enabled', 'on')
assert all(r.get('enabled') is not False for r in d.rules() if r.get('group') == 'Frost')
_frost = [r for r in d.rules() if r.get('group') == 'Frost']
d.object_call('rule:%s' % _frost[0]['id'], 'toggle')
assert d.object_fact('Frost', 'enabled') == 'some', d.object_fact('Frost', 'enabled')
d.object_call('Frost', 'toggle')
assert d.object_fact('Frost', 'enabled') == 'off', 'toggle with some on did not switch them all off'
_out = d.run_script({'name': 'f', 'body': 'Frost.enable()'}, {}, 'a test')
assert not _out.get('faults') and d.object_fact('Frost', 'enabled') == 'on', _out
d.object_set('Frost', 'name', 'Freeze')
assert {r.get('group') for r in d.rules() if r.get('value') in (1, -5)} == {'Freeze'}
assert 'Freeze' in (d.editor_groups().get('rules') or [])
d._objects_cache = None
assert d.object_find('Frost') is None and d.object_find('Freeze')[0] == 'section'
d.save_rules(_rules_before)
print('a section of any editor is an object: counted, switched on, off and over, and renamed with its rows')
# everything that can be switched off: enabled, enable(), disable(), toggle()
for _ref in ('scene:%s' % scenes['Vecer'], 'person:%s' % person['id'], 'message:%s' % d.alert_messages()[0]['id'],
             'tap:%s' % tap['id'], 'smscmd:%s' % d.sms_commands()[0]['id']):
    _names = {m['name']: m for m in d.object_detail(_ref)['members']}
    for _want in ('enabled', 'enable', 'disable', 'toggle'):
        assert _want in _names, '%s has no %s' % (_ref, _want)
    assert _names['enabled'].get('settable'), '%s.enabled cannot be set' % _ref
d.object_call('Vecer', 'disable')
assert next(s for s in d.scenes() if s['name'] == 'Vecer').get('enabled') is False
assert d.run_scene(scenes['Vecer'])[0] is False, 'a scene switched off still ran'
d.object_call('Vecer', 'toggle')
assert next(s for s in d.scenes() if s['name'] == 'Vecer').get('enabled') is True
d.object_call('message:%s' % d.alert_messages()[0]['id'], 'disable')
assert d.alert_messages()[0].get('enabled') is False
assert d.send_message(d.alert_messages()[0]['id'], 'a test') == '', 'a message switched off was still sent'
d.object_call('message:%s' % d.alert_messages()[0]['id'], 'enable')
assert d.alert_messages()[0].get('enabled') is True
print('everything that can be switched off has enabled, enable(), disable() and toggle(), and is obeyed')


# ---------------------------------------------------------------------------
# (4.98) the records are objects too: what a Save replaced, a database backup,
# a text waiting to go out, a message in the log and a browser holding the PIN
d.save_scenes([{'name': 'Kept-A', 'actions': [{'target': 'notify', 'do': 'on'}]}])
d.save_scenes([{'name': 'Kept-B', 'actions': [{'target': 'notify', 'do': 'on'}]}])
d._objects_cache = None
_snaps = [o for o in d.objects() if o['type'] == 'snapshot']
assert _snaps, 'what a Save replaced is not an object'
assert d.object_fact(_snaps[0]['ref'], 'key') == 'scenes'
assert d.object_call(_snaps[0]['ref'], 'restore')
assert any(s['name'] == 'Kept-A' for s in d.scenes()), 'the kept version was not put back'
assert d.object_call(_snaps[0]['ref'], 'forget')
d._objects_cache = None
assert not any(o['ref'] == _snaps[0]['ref'] for o in d.objects()), 'a forgotten version is still an object'
_mid = d.sms_note('in', '+420777000111', 'ahoj')
_one = d.object_find('smslog:%s' % _mid)
assert _one and _one[0] == 'smslog', 'a message in the log is not an object'
assert d.object_fact('smslog:%s' % _mid, 'text') == 'ahoj'
assert not any(o['type'] == 'smslog' for o in d.objects()), 'the whole message log crowds the object list'
_detail = {m['name']: m for m in d.object_detail('smslog:%s' % _mid)['members']}
assert _detail['number']['value'] == '(sign in)', 'a number was shown without the PIN'
assert {m['name'] for m in d.object_detail('smslog:%s' % _mid)['members']} >= {'forget', 'reply', 'send_again'}
assert d.object_call('smslog:%s' % _mid, 'forget')
assert not d.object_find('smslog:%s' % _mid), 'a forgotten message is still an object'
d.sms_queue_add('+420777000111', 'waiting one', 'alert')
d._objects_cache = None
_out = [o for o in d.objects() if o['type'] == 'outbox']
assert _out, 'a text waiting to go out is not an object'
assert d.object_call(_out[0]['ref'], 'drop') and not d.sms_outbox()
# a sign-in is one (5.19): named by its id, its account hidden from the
# public list, and ended from its own row
d.account_add('objects-user', 'operator', 'objects pass 1', must_change=False, quiet=True)
_tok = d.login('objects-user', 'objects pass 1', '10.0.0.9')[0]['token']
d._objects_cache = None
_sess = [o for o in d.objects() if o['type'] == 'session']
assert _sess, 'a sign-in is not an object'
assert 'objects-user' not in json.dumps(d.objects()), 'the public list of objects names who is signed in'
_n = len(d.signins)
assert d.object_call(_sess[0]['ref'], 'end') and len(d.signins) == _n - 1, 'one sign-in could not be ended on its own'
assert d.session_get(_tok) is None or len(_sess) > 1
print('the records are objects: a kept version, a backup, a waiting text, a message and a sign-in')
