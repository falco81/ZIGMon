#!/usr/bin/env python3
"""Change one field in each editor, save it, read it back.

A control can be wired to a record, the record can be saved, and the field
can still be dropped on the way - by a validator that does not know it, or a
reader that never looks. This writes something distinctive into each editor,
saves through the same path the page uses, and asks the daemon for it again.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = 'http://127.0.0.1:%s' % (sys.argv[1] if len(sys.argv) > 1 else '9849')
TOKEN = Path(sys.argv[2] if len(sys.argv) > 2 else '/tmp/prod4-token').read_text().strip()
PIN = sys.argv[3] if len(sys.argv) > 3 else '1234'


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=25).read())


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(dict(body, pin=PIN)).encode(),
                                 headers={'X-Zigmon-Token': TOKEN, 'Content-Type': 'application/json'},
                                 method='POST')
    try:
        return json.loads(urllib.request.urlopen(req, timeout=25).read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


status = get('/api/status')
# the overview sums some editors up - a scene there carries how many steps it
# has, not the steps - so those are read from their own endpoint, as the page
# does when it opens the editor
for extra, path, key in (('scenes', '/api/scenes', 'scenes'),
                         ('sequences', '/api/sequences', 'sequences')):
    try:
        status[key] = get(path).get(key) or status.get(key) or []
    except Exception:
        pass
bad = []
mark = 'checked %d' % int(time.time())

# a field a person actually fills in, for each editor
CASES = [
    ('rules', '/api/rules', 'rules', 'group', mark),
    ('bindings', '/api/bindings', 'bindings', 'group', mark),
    ('scenes', '/api/scenes', 'scenes', 'name', 'Lo\u017enice ve\u010der'),
    ('schedules', '/api/schedules', 'schedules', 'group', mark),
    ('messages', '/api/messages', 'messages', 'text', None),
    ('sms commands', '/api/sms/commands', 'commands', 'reply', mark),
    ('people', '/api/people', 'people', 'name', None),
    ('rooms', '/api/rooms', 'rooms', 'name', None),
    ('sensor groups', '/api/sensor-groups', 'sensor_groups', 'name', 'Teplom\u011bry'),
    ('action groups', '/api/action-groups', 'action_groups', 'name', 'Sv\u011btla dole'),
]

for label, path, key, field, value in CASES:
    rows = status.get(key) or []
    if not rows:
        print('  %-14s nothing to change' % label)
        continue
    keep = json.loads(json.dumps(rows))
    was = rows[0].get(field)
    rows[0][field] = value if value is not None else ((was or 'x') + ' \u2713')
    wanted = rows[0][field]
    answer = post(path, {key: rows})
    if not answer.get('ok'):
        bad.append('%s: the save was refused (%s)' % (label, answer.get('error')))
        continue
    back = (get('/api/status').get(key) or [{}])[0].get(field)
    if back != wanted:
        bad.append('%s: wrote %r, read back %r' % (label, wanted, back))
        print('  %-14s <-- LOST ON THE WAY' % label)
    else:
        print('  %-14s kept what was written' % label)
    post(path, {key: keep})                      # put it back as it was

print('')
if bad:
    print('fields that did not survive a save:')
    for line in bad:
        print('   ' + line)
    raise SystemExit(1)
print('every editor kept what was written into it')

# What the status reports and what an editor saves must not be the same word
# for two different shapes. A scene's "actions" is the steps in the editor and
# how many there are in the status, and handing one back where the other was
# expected is refused - which is right, but the refusal is the only thing that
# stopped it, so the plain name has to be there as well.
import json as _json
import urllib.request as _rq
_st = _json.loads(_rq.urlopen(BASE + '/api/status', timeout=20).read())
for _sc in _st.get('scenes') or []:
    assert 'action_count' in _sc, 'a scene in the status has no plain count of its steps'
    assert isinstance(_sc['action_count'], int)
print('the status says how many steps a scene has in a word that means only that')

# Pressing Add leaves an untouched row in every editor, and refusing the whole
# list for it means that from that moment nothing saves at all - which reads as
# "saving is broken" rather than "finish this row". A half-filled row is still
# refused: that is a mistake rather than a blank.
_blank_trials = [
    ('SMS commands', '/api/sms/commands', 'commands'),
    ('scenes', '/api/scenes', 'scenes'),
    ('sequences', '/api/sequences', 'sequences'),
    ('schedules', '/api/schedules', 'schedules'),
    ('messages', '/api/messages', 'messages'),
    ('sensor groups', '/api/sensor-groups', 'groups'),
    ('action groups', '/api/action-groups', 'groups'),
    ('one-tap links', '/api/taps', 'taps'),
]
# add the blank to what is already there rather than replacing the list with
# it - saving a list of one blank row empties the editor, which is what this
# check is meant to prevent, not to cause
for _label, _path, _key in _blank_trials:
    # from the editor's own list where it can be read, else from the status -
    # two of them have no plain read, and a scene's steps are the steps here
    # but a count in the status, so the two must not be confused
    try:
        _have = (get(_path) or {}).get(_key) or []
    except Exception:
        _have = (get('/api/status') or {}).get(
            {'messages': 'messages', 'taps': 'taps'}.get(_key, _key)) or []
    _answer = post(_path, {_key: list(_have) + [{}]})
    assert (_answer or {}).get('ok'), \
        '%s refuses to save while an untouched row is on the page: %s' % (_label, (_answer or {}).get('error'))
    _kept = (_answer or {}).get(_key) or (_answer or {}).get('commands') or []
    assert len(_kept) >= len(_have), \
        '%s lost %d row(s) when the blank one was passed over' % (_label, len(_have) - len(_kept))
_answer = post('/api/sms/commands', {'commands': [{'phrase': '', 'target': 'Light-Loznice-Main',
                                                          'do': 'off'}]})
assert not (_answer or {}).get('ok'), 'a half-filled row was accepted, so a mistake would be saved as one'
print('%d editor(s) save with an untouched row on the page, and still refuse a half-filled one'
      % len(_blank_trials))

# An answer to a text message used to be cut at one message's worth - 160
# characters - without saying so, so anything longer came back missing its
# tail. A long answer is not wrong; it is several messages.
_long_reply = ('Doma jsou: {people_home}\n--------------------\nON Plugs\n--------------------\n'
               '{plugs_on_list.nl}\n--------------------\nON Lights\n--------------------\n'
               '{lights_on_list}')
_was_cmds = (get('/api/sms/commands') or {}).get('commands') or []
_answer = post('/api/sms/commands', {'commands': [{'phrase': 'lengthcheck', 'target': '',
                                                   'do': 'on', 'reply': _long_reply, 'answer': True}]})
assert (_answer or {}).get('ok'), 'a long answer was refused: %s' % (_answer or {}).get('error')
_kept = ((_answer.get('commands') or [{}])[0]).get('reply') or ''
assert _kept == _long_reply, \
    'an answer of %d characters came back as %d' % (len(_long_reply), len(_kept))
post('/api/sms/commands', {'commands': _was_cmds})
print('an answer of %d characters survives a save whole' % len(_long_reply))
