#!/usr/bin/env python3
"""Every fact the daemon fills must be offered in the page's picker, and every
fact the picker offers must exist.

The two lists drifted apart once: the picker advertised sunrise, sunset and
daylight for weeks while the daemon filled none of them, so a message quoting
them arrived with the words missing. Run this before a release.
"""
import re
import sys
from pathlib import Path

here = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(here))
import zigmon                                    # noqa: E402

zigmon.load_config()
zigmon.CONFIG['db_file'] = '/tmp/zigmon-facts-check.db'
# A stale journal beside a fresh database is not this run's data: SQLite
# replays it, and a check then fails over rows the run never wrote. Both
# sidecars go with the file.
import os as _dbclean
for _ext in ('', '-wal', '-shm'):
    try:
        _dbclean.remove(zigmon.CONFIG['db_file'] + _ext)
    except OSError:
        pass

zigmon.CONFIG['api_port'] = 19700
zigmon.CONFIG['token_file'] = '/tmp/zigmon-facts-token'
daemon = zigmon.Daemon()
have = set(daemon.message_facts('a check'))

page = (here / 'web' / 'index.php').read_text()
start = page.index('function factCatalogue')
block = page[start:page.index('\n}', start)]
offered = set(re.findall(r"\['([a-z_0-9]+)',", block))

missing = sorted(have - offered)
extra = sorted(offered - have)
if missing:
    print('filled by the daemon but not offered in the picker:')
    for k in missing:
        print('   {%s}' % k)
if extra:
    print('offered in the picker but never filled:')
    for k in extra:
        print('   {%s}' % k)
if missing or extra:
    sys.exit(1)
print('%d facts, all of them offered and all of them filled' % len(have))

# Turns of phrase: a fact may be followed by one, or several, and they have to
# work anywhere a fact does. An empty list is a word in this house - "nothing",
# "nobody" - so counting one of those as an item would have a message saying
# one socket is on when none is.
_list = 'Plug-UPS, Workshop-PC, Workshop-TV, Balcony'
_turns = {
    'nl': 'Plug-UPS\nWorkshop-PC\nWorkshop-TV\nBalcony',
    'count': '4',
    'first': 'Plug-UPS',
    'last': 'Balcony',
    'and': 'Plug-UPS, Workshop-PC, Workshop-TV and Balcony',
    'three': 'Plug-UPS, Workshop-PC, Workshop-TV and 1 more',
    'upper': _list.upper(),
}
for _name, _want in _turns.items():
    _got = zigmon.FACT_TURNS[_name](_list)
    assert _got == _want, '.%s gave %r, wanted %r' % (_name, _got, _want)
for _empty in ('nothing', 'nobody', 'none', ''):
    assert zigmon.FACT_TURNS['count'](_empty) == '0', '.count called %r one thing' % _empty
    assert zigmon.FACT_TURNS['nl'](_empty) == '', '.nl made a line out of %r' % _empty
assert zigmon.FACT_TURNS['round']('21.73') == '22'
assert zigmon.FACT_TURNS['round1']('21.73') == '21.7'
assert zigmon.FACT_TURNS['round']('not a number') == 'not a number'

# every turn the page offers must be one the daemon knows, and the other way
_php = (Path(__file__).resolve().parent.parent / 'web' / 'index.php').read_text()
_offered = set(re.findall(r"\n  \['([a-z0-9_]+)', '[^']*', '[^']*'\]", _php[_php.index('var FACT_TURN_LIST'):
                                                                      _php.index('function completerItems')]))
_known = set(zigmon.FACT_TURNS)
assert not (_offered - _known), 'the page offers turns the daemon does not know: %s' % (_offered - _known)
assert not (_known - _offered), 'the daemon knows turns the page never offers: %s' % (_known - _offered)
# a turn must never leave a message half-written, whatever it is given
for _name, _fn in sorted(zigmon.FACT_TURNS.items()):
    for _given in ('', 'nothing', 'one', 'a, b, c', '-4.25', 'not a number', 'P\u0159\u00edzem\u00ed'):
        try:
            _out = _fn(_given)
        except Exception as _e:
            raise AssertionError('.%s fell over on %r: %s' % (_name, _given, _e))
        assert isinstance(_out, str), '.%s gave back a %s' % (_name, type(_out).__name__)

# the one that pays for itself: a diacritic doubles what a text message costs
_cz = 'Venku je zima a pr\u0161\u00ed, m\u011b\u0159\u00edm teplotu v ob\u00fdvac\u00edm pokoji a v lo\u017enici. Z\u00e1suvky: Plug-UPS, Workshop-PC.'
assert zigmon.Daemon.sms_parts(_cz) == 2
assert zigmon.Daemon.sms_parts(zigmon.FACT_TURNS['ascii'](_cz)) == 1, \
    'stripping the diacritics did not bring it down to one message'

print('%d turn(s) of phrase, each working and each offered' % len(_known))

# A turn after a reading of a NAMED device, which is the case that was broken:
# {PIR-Chodba.model.nl} left the whole placeholder standing on the page. The
# daemon takes the turns off the end while it knows them and asks for the rest
# as a device fact, so every turn must survive a device name in front of it -
# including a key that holds a dot of its own (switch.apower).
import json as _json                                                    # noqa: E402
_B = 'zigbee2mqtt/'


def _send(_t, _p):
    daemon.handle(_t, _json.dumps(_p).encode())


_send(_B + 'bridge/state', {'state': 'online'})
_send(_B + 'bridge/devices', [
    {'ieee_address': '0x0000', 'type': 'Coordinator', 'friendly_name': 'Coordinator'},
    {'ieee_address': '0xc02cedfffe2c7248', 'type': 'EndDevice', 'friendly_name': 'PIR-Chodba',
     'definition': {'model': 'SBMO-003Z', 'vendor': 'Shelly', 'description': 'Motion sensor', 'exposes': [
         {'access': 5, 'label': 'Battery', 'name': 'battery', 'property': 'battery', 'type': 'numeric', 'unit': '%'},
         {'access': 5, 'label': 'Occupancy', 'name': 'occupancy', 'property': 'occupancy', 'type': 'binary'}]}}])
daemon.devices_settled(5.0)      # taken in on its own worker now
_send(_B + 'PIR-Chodba', {'occupancy': True, 'battery': 88, 'linkquality': 90})
_facts = daemon.message_facts('a check')

assert daemon.fill_message('{PIR-Chodba.model}', _facts) == 'SBMO-003Z'
_pairs = [('{PIR-Chodba.model.lower}', 'sbmo-003z'),
          ('{PIR-Chodba.model.nl}', 'SBMO-003Z'),
          ('{PIR-Chodba.name.upper}', 'PIR-CHODBA'),
          ('{PIR-Chodba.battery.percent}', '88%'),
          ('{PIR-Chodba.occupancy.yesno}', 'yes'),
          ('{PIR-Chodba.model.lower.upper}', 'SBMO-003Z')]
for _wrote, _want in _pairs:
    _got = daemon.fill_message(_wrote, _facts)
    assert _got == _want, '%s gave %r, wanted %r' % (_wrote, _got, _want)
# and none of them may leave the placeholder itself standing
for _name in sorted(_known):
    _out = daemon.fill_message('{PIR-Chodba.model.%s}' % _name, _facts)
    assert '{' not in _out, '{PIR-Chodba.model.%s} came back as %r' % (_name, _out)
print('%d turn(s) work after a named device\'s reading too' % len(_known))


# Asking a question and going round a list: {if …}{else}{end} and {for x in
# …}{end}, with and/or/not and comparisons. A message could quote a fact and
# turn it into other words, but it could not say something only when it was
# so - so every alert said the same thing whether or not anybody was home.
_F = dict(_facts)
_F.update({'who_home': 'Falco, Jana', 'anyone_home': 'yes', 'plugs_on': '3', 'nobody': '',
           'plugs_on_list': 'Plug-UPS, Plug-TV, Plug-PC', 'temp': '4.2', 'cost': '1284.5',
           'power_now': '7421', 'empty_list': 'nothing'})
_asks = [
    ('{if anyone_home}in{else}out{end}', 'in'),
    ('{if nobody}in{else}out{end}', 'out'),
    ('{if no_such_fact}yes{else}no{end}', 'no'),
    ('{if plugs_on > 5}many{else if plugs_on > 2}a few{else}none{end}', 'a few'),
    ('{if plugs_on > 5}many{else if plugs_on > 9}more{else}none{end}', 'none'),
    ('{if {temp} < 5}cold{end}', 'cold'),
    ('{if {temp} >= 5}warm{end}', ''),
    ('{if not anyone_home}away{else}home{end}', 'home'),
    ('{if plugs_on >= 3 and anyone_home}both{end}', 'both'),
    ('{if plugs_on > 9 or {temp} < 5}either{end}', 'either'),
    ('{if (plugs_on > 9 or {temp} < 5) and anyone_home}bracketed{end}', 'bracketed'),
    ('{if who_home contains Jana}Jana{end}', 'Jana'),
    ('{if who_home contains Karel}Karel{end}', ''),
    ('{if Plug-UPS in plugs_on_list}UPS is on{end}', 'UPS is on'),
    ('{if empty_list}something{else}nothing on{end}', 'nothing on'),
    ('{if PIR-Chodba.battery > 50}battery fine{end}', 'battery fine'),
    ('{for p in plugs_on_list}[{p}]{end}', '[Plug-UPS][Plug-TV][Plug-PC]'),
    ('{for p in {plugs_on_list}}{loop_i}/{loop_n} {p}. {end}',
     '1/3 Plug-UPS. 2/3 Plug-TV. 3/3 Plug-PC.'),
    ('{for p in plugs_on_list}{p}{if loop_last}.{else}, {end}{end}', 'Plug-UPS, Plug-TV, Plug-PC.'),
    ('{for p in empty_list}{p}{end}', ''),
    ('{for p in plugs_on_list}{if loop_first}on: {end}{p} {end}', 'on: Plug-UPS Plug-TV Plug-PC'),
    # what the moment holds is still put in around them
    ('{if anyone_home}{who_home.count} at home{end}', '2 at home'),
    # and a message that says nothing of the sort is untouched
    ('nothing to ask here', 'nothing to ask here'),
    ('{plugs_on} on', '3 on'),
]
for _wrote, _want in _asks:
    _got = daemon.fill_message(_wrote, _F)
    assert _got == _want, '%s gave %r, wanted %r' % (_wrote, _got, _want)
print('%d question(s) and loop(s) in a message, each answered as written' % len(_asks))

# The turns that carry something of their own, after a colon
_carry = [
    ('{nobody.default:nobody}', 'nobody'),
    ('{who_home.default:nobody}', 'Falco, Jana'),
    ('{anyone_home.say:the house is not empty}', 'the house is not empty'),
    ('{nobody.say:never said}', ''),
    ('{nobody.saynot:nobody is in}', 'nobody is in'),
    ('{plugs_on_list.join: + }', 'Plug-UPS + Plug-TV + Plug-PC'),
    ('{plugs_on_list.nth:2}', 'Plug-TV'),
    ('{plugs_on_list.head:2}', 'Plug-UPS, Plug-TV'),
    ('{plugs_on_list.has:plug-tv}', 'yes'),
    ('{plugs_on_list.without:Plug-TV}', 'Plug-UPS, Plug-PC'),
    ('{temp.add:1.8}', '6'),
    ('{temp.times:2}', '8.4'),
    ('{power_now.divide:1000}', '7.42'),
    ('{temp.decimals:1}', '4.2'),
    ('{who_home.left:5}', 'Falco'),
    ('{who_home.before:,}', 'Falco'),
    ('{temp.suffix: °C}', '4.2 °C'),
    ('{nobody.suffix: °C}', ''),
    ('{temp.unit:°C}', '4.2 °C'),
    # and the ones that stand on their own
    ('{power_now.kw}', '7.42 kW'),
    ('{plugs_on_list.count}', '3'),
    ('{temp.int}', '4'),
    ('{temp.ceil}', '5'),
    ('{nobody.not}', 'yes'),
    ('{anyone_home.not}', ''),
]
for _wrote, _want in _carry:
    _got = daemon.fill_message(_wrote, _F)
    assert _got == _want, '%s gave %r, wanted %r' % (_wrote, _got, _want)
# a number of them added up
assert daemon.fill_message('{list.sum}', {'list': '1, 2, 3.5'}) == '6.5'
assert daemon.fill_message('{list.max}', {'list': '1, 2, 3.5'}) == '3.5'
print('%d turn(s) that carry something of their own' % len(_carry))


# Time, in the shapes a fact arrives in: seconds since the epoch, an ISO
# stamp, a length in words. A message could say "it went quiet at
# 1789925769", which is not a thing anybody reads.
_when = 1789925769          # 2026-09-20 18:16:09 UTC
_T = {'stamp': str(_when), 'iso': '2026-09-20 18:42:07', 'long': '9312', 'words': '2 h 14 min',
      'clock': '18:42'}
_times = [
    ('{iso.time}', '18:42'),
    ('{iso.time_s}', '18:42:07'),
    ('{iso.date}', '2026-09-20'),
    ('{iso.date_cz}', '20.09.2026'),
    ('{iso.datetime}', '2026-09-20 18:42'),
    ('{iso.dayname}', 'Sunday'),
    ('{iso.monthname}', 'September'),
    ('{iso.year}', '2026'),
    ('{iso.hour}', '18'),
    ('{iso.daypart}', 'evening'),
    ('{iso.clock:%d.%m. %H:%M}', '20.09. 18:42'),
    ('{iso.plusdays:1}', '2026-09-21'),
    ('{iso.plusmins:25}', '19:07'),
    ('{iso.iso}', '2026-09-20T18:42:07'),
    ('{long.duration}', '2 h 35 min'),
    ('{long.hhmm}', '2:35'),
    ('{long.hours}', '2.6'),
    ('{long.minutes}', '155'),
    ('{words.minutes}', '134'),
    ('{words.hours}', '2.2'),
    # what is not a time at all comes back as it was, never half-written
    ('{nothing_here.time}', ''),
    ('{words.time}', '2 h 14 min'),
]
for _wrote, _want in _times:
    _got = daemon.fill_message(_wrote, _T)
    assert _got == _want, '%s gave %r, wanted %r' % (_wrote, _got, _want)
# a moment in seconds is read as a moment, and how long ago it was is said
import time as _time
_ago = daemon.fill_message('{stamp.ago}', {'stamp': str(int(_time.time()) - 7200)})
assert _ago.endswith('ago') and ('2 h' in _ago), 'how long ago gave %r' % _ago
_in = daemon.fill_message('{stamp.until}', {'stamp': str(int(_time.time()) + 3600)})
assert _in.startswith('in ') and ('59 min' in _in or '1 h' in _in), 'how long until gave %r' % _in
# and the letters a clock may be written with are only the ones that say a
# date or a time: nothing else is handed to strftime
assert daemon.fill_message('{iso.clock:%x}', _T) == _T['iso']
print('%d way(s) of writing a time, each read from whatever shape it came in' % len(_times))

# {unless}, {repeat} and a list written on the spot
_blocks = [
    ('{unless anyone_home}nobody{end}', {'anyone_home': ''}, 'nobody'),
    ('{unless anyone_home}nobody{else}somebody{end}', {'anyone_home': 'yes'}, 'somebody'),
    ('{repeat 3}[{loop_i}]{end}', {}, '[1][2][3]'),
    ('{repeat {n}}*{end}', {'n': '4'}, '****'),
    ('{for p in Plug-UPS, Plug-TV}<{p}>{end}', {}, '<Plug-UPS><Plug-TV>'),
]
for _wrote, _facts_now, _want in _blocks:
    _got = daemon.fill_message(_wrote, _facts_now)
    assert _got == _want, '%s gave %r, wanted %r' % (_wrote, _got, _want)
print('%d more block(s): unless, repeat, and a list written out on the spot' % len(_blocks))

# Everything the page offers must be something the daemon does, and the other
# way round: a turn offered and not written is a message that quietly keeps
# the braces, and one written and not offered is one nobody finds.
import re as _reT
_page = (Path(__file__).resolve().parent.parent / 'web' / 'index.php').read_text()
_plain = set(_reT.findall(r"^\s+\['([a-z0-9_]+)',", _reT.search(r'var FACT_TURN_LIST = \[(.*?)\n\];', _page, _reT.S).group(1), _reT.M))
_with = set(_reT.findall(r"^\s+\['([a-z0-9_]+)',", _reT.search(r'var FACT_TURN_ARGS = \[(.*?)\n\];', _page, _reT.S).group(1), _reT.M))
_missing = sorted(_plain - set(zigmon.FACT_TURNS)) + sorted(_with - set(zigmon.FACT_TURNS_WITH))
assert not _missing, 'the page offers turns the daemon does not do: %s' % ', '.join(_missing)
_unoffered = sorted((set(zigmon.FACT_TURNS) - _plain)) + sorted(set(zigmon.FACT_TURNS_WITH) - _with)
assert not _unoffered, 'the daemon does turns the page never offers: %s' % ', '.join(_unoffered)
print('%d turn(s) offered, %d of them carrying something, all of them done' % (len(_plain), len(_with)))


# Every kind of message the card offers a road for must be a kind something
# actually sends, and every kind something sends must be on the card. Five of
# them - a one-tap link, the router, heating, Wi-Fi, the text gateway - were
# offered for months with nothing ever sending them: anybody who routed one
# somewhere heard nothing for ever and had no way to tell.
import re as _re9
_src = (Path(__file__).resolve().parent.parent / 'zigmon.py').read_text()
_sent = set(_re9.findall(r"about='([a-z_]+)'", _src)) - {''}
# and the ones a table hands out: what a device reports that is a danger
_sent |= {_v[0] for _v in zigmon.Daemon.DANGER_KEYS.values()}
_offered = {_x[0] for _x in zigmon.Daemon.SYSTEM_ALERTS}
# these two mean "this one carries its own roads" and are not categories
_own_roads = {'device', 'message', 'test'}
_silent = sorted(_offered - _sent)
if _silent:
    print('kind(s) of message the card offers a road for that nothing ever sends:')
    for _k in _silent:
        print('   %s' % _k)
    raise SystemExit(1)
_unlisted = sorted(_sent - _offered - _own_roads)
if _unlisted:
    print('kind(s) of message sent that the card offers no road for:')
    for _k in _unlisted:
        print('   %s' % _k)
    raise SystemExit(1)
print('%d kinds of message, every one of them both sent and routable' % len(_offered))


# A road set for one kind of message has to actually take that road. The list
# of kinds being right is half of it; the other half is that choosing one
# changes where a message goes, and nothing checked that at all.
import json as _json9
_d9 = zigmon.Daemon()
_d9.store.set_meta('notify', _json9.dumps({
    'systems': {'taps': {'roads': 'telegram'}, 'router': {'off': True}}}))
zigmon.CONFIG.update({'notify_ntfy': 'https://ntfy.sh/x', 'notify_telegram_token': 't',
                      'notify_telegram_chat': '1', 'sms_enabled': 1})
_queue = _d9.notify_queue


def _roads_for(about):
    del _queue[:]
    _d9.notify('x', 'warn', about=about)
    return [{_k: _item[_k] for _k in ('ntfy', 'telegram', 'sms') if _k in _item}
            for _item in _queue]


_took = _roads_for('taps')
assert _took and _took[0] == {'ntfy': False, 'telegram': True, 'sms': False}, \
    'a kind sent down one road alone went %r instead' % _took
assert not _roads_for('router'), 'a kind switched off was still sent'
_other = _roads_for('wifi')
assert _other and _other[0]['ntfy'] and _other[0]['telegram'], \
    'a kind nobody has touched stopped taking the ordinary roads: %r' % _other
_d9.store.set_meta('notify', '{}')
print('a road set for one kind of message is the road that kind takes')



# ---------------------------------------------------------------------------
# What a loop may not do: one message, however deeply the loops in it nest.
# Each loop is capped at two hundred turns on its own, but nesting multiplies
# - three {repeat 200} inside one another is eight million turns and eight
# megabytes of text, four is the machine's memory - and /api/message-preview
# asks for none of it, so writing a nested loop hung the daemon from the
# editor. A whole rendering has a budget now.
import time as _t10
_d10 = zigmon.Daemon()
_f10 = _d10.message_facts('a test')
# Three deep, not four: without a budget three take seven seconds and make
# eight megabytes - enough to fail this in a moment - while four take twenty
# minutes and the machine's memory, which is a hang rather than a failure.
_start = _t10.perf_counter()
_deep = _d10.fill_message('{repeat 200}' * 3 + 'x' + '{end}' * 3, _f10)
_spent = _t10.perf_counter() - _start
assert _spent < 3, 'three nested loops took %.1f s' % _spent
assert len(_deep) <= zigmon.BLOCK_TEXT_MOST + len(zigmon.BLOCK_CUT) + 8, \
    'three nested loops made %d characters' % len(_deep)
assert 'cut' in _deep, 'the text was cut without saying so: %r' % _deep[-80:]
# ...and everything under the budget is untouched
assert _d10.fill_message('{repeat 3}{loop_i}/{loop_n} {end}', _f10) == '1/3 2/3 3/3', \
    'an ordinary loop was changed'
assert _d10.fill_message('{for x in a, b, c}{x}{end}', _f10) == 'abc', 'a list loop was changed'
assert len(_d10.fill_message('{repeat 200}x{end}', _f10)) == 200, 'one full loop was cut'
assert 'cut' not in _d10.fill_message('{repeat 200}{repeat 200}x{end}{end}', _f10), \
    'two nested loops, well inside the budget, were cut'
print('a message’s loops have a budget between them, and nothing under it is touched')

# A loop inside a loop keeps its own place. The four loop marks are shared
# with the outer loop through one set of names - which is what makes "let"
# carry from turn to turn - so an inner loop used to leave its own last turn
# behind: the outer loop then thought it was on its last turn, and a line
# asking for {loop_first} was skipped because the name stood for nothing.
_nested = _d10.fill_message(
    '{for a in one, two}[{loop_i}/{loop_n} {a}'
    '{for b in x, y}({loop_i}{b}){end}'
    ' after={loop_i} first={loop_first} last={loop_last}]{end}', _f10)
assert _nested == ('[1/2 one(1x)(2y) after=1 first=yes last=]'
                   '[2/2 two(1x)(2y) after=2 first= last=yes]'), \
    'an inner loop left its own place behind: %r' % _nested
print('a loop inside a loop leaves the outer loop where it was')

# A device whose name begins with a block word is a name, not a block. The
# word boundary alone made {If-Kitchen.state} an {if}, and the block it
# opened swallowed everything after it: the message came out empty.
for _name in ('If-Kitchen.state', 'For-Loznice.temperature', 'End-Of-Hall.battery',
              'Unless-Door.contact', 'Repeat-Box.power'):
    _said = _d10.fill_message('{%s} and the rest' % _name, _f10)
    assert _said.endswith('and the rest'), \
        '{%s} swallowed the message: %r' % (_name, _said)
assert _d10.fill_message('{if anyone_home}in{else}out{end}', _f10) in ('in', 'out'), 'an {if} stopped working'
assert _d10.fill_message('{for x in a, b}{x}{end}', _f10) == 'ab', 'a {for} stopped working'
assert _d10.fill_message('{repeat 2}z{end}', _f10) == 'zz', 'a {repeat} stopped working'
assert _d10.fill_message('{unless anyone_home}none{end}', _f10) in ('none', ''), 'an {unless} stopped working'
print('a name that begins with a block word is a name, and the blocks still work')

# Money keeps its hellers, and a short length is not read as a long one.
for _was, _want in (('1234.56', '1 234.56'), ('12.50', '12.5'), ('0.99', '0.99'),
                    ('1234', '1 234'), ('-1234.5', '-1 234.5')):
    _got = zigmon.apply_turn(_was, 'money')
    assert _got.startswith(_want), '{%s.money} came out %r, wanted %r' % (_was, _got, _want)
for _was, _want in (('45', '0:00'), ('90', '0:01'), ('2700', '0:45'), ('9300', '2:35')):
    assert zigmon.apply_turn(_was, 'hhmm') == _want, \
        '%s seconds as hours and minutes came out %r' % (_was, zigmon.apply_turn(_was, 'hhmm'))
assert zigmon.apply_turn('45', 'hhmm') != zigmon.apply_turn('2700', 'hhmm'), \
    '45 seconds and 45 minutes read the same'
print('money keeps its decimals, and a length under a minute is not read as three quarters of an hour')
