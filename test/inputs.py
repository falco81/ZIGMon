#!/usr/bin/env python3
"""Every setting drawn on the page must be the kind of box the daemon says it
is. The page used to keep its own idea of which settings were yes-or-no
questions, and it fell behind: two settings were drawn as number boxes asking
for a 1 or a 0, and a place could not be typed into the box asking for one.

This checks the two sides agree without a browser: the daemon's kinds against
the kinds the page's own code will draw.
"""
import re
import sys
from pathlib import Path

here = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(here))
import zigmon                                        # noqa: E402

zigmon.load_config()
zigmon.CONFIG['db_file'] = '/tmp/zigmon-inputs-check.db'
# A stale journal beside a fresh database is not this run's data: SQLite
# replays it, and a check then fails over rows the run never wrote. Both
# sidecars go with the file.
import os as _dbclean
for _ext in ('', '-wal', '-shm'):
    try:
        _dbclean.remove(zigmon.CONFIG['db_file'] + _ext)
    except OSError:
        pass

zigmon.CONFIG['api_port'] = 19599
zigmon.CONFIG['token_file'] = '/tmp/zigmon-inputs-token'
daemon = zigmon.Daemon()
kinds = {k: v['kind'] for k, v in daemon.runtime_config().items()}

page = (here / 'web' / 'index.php').read_text()
drawn = {}
block = re.search(r'var SMS_GROUPS = \[(.*?)\n\];', page, re.S)
if block:
    for key, kind in re.findall(r"\['(sms_[a-z_0-9]+)', '(?:[^']|\\')*', '(\w+)'", block.group(1)):
        drawn[key] = {'switch': 'switch', 'select': 'choice', 'password': 'secret',
                      'number': 'number', 'text': 'text',
                      # three switches over a value that is a list of roads;
                      # to the daemon it is still a piece of text
                      'roads': 'text'}.get(kind, kind)

wrong = []
for key, kind in sorted(drawn.items()):
    if key not in kinds:
        wrong.append('%s is drawn but the daemon has no such setting' % key)
        continue
    want = kinds[key]
    if want == 'phone' and kind == 'text':
        continue                                     # a number box for a phone is still words
    if want == 'decimal' and kind == 'number':
        continue
    if want != kind:
        wrong.append('%s: the daemon says %s, the page draws %s' % (key, want, kind))

if wrong:
    print('the page and the daemon disagree about:')
    for line in wrong:
        print('   %s' % line)
    raise SystemExit(1)
print('%d settings the SMS card draws, all of the kind the daemon says' % len(drawn))
print('%d settings in all, each with a kind' % len(kinds))

# A setting offered as a list is written out twice: once in the daemon, which
# is what the value is checked against, and once in the SMS card, which is
# what a person picks from. They can drift - a choice added to one and not the
# other either cannot be picked or cannot be saved - so the two lists must
# hold the same values, in the same order.
_drift = []
for _m in re.finditer(r"\['(sms_[a-z_0-9]+)', '(?:[^']|\\')*', 'select', \[(.*?)\]\]", page, re.S):
    _key, _body = _m.group(1), _m.group(2)
    _page_values = re.findall(r"\['([^']*)',", _body)
    _mine = daemon.TUNABLE_CHOICES.get(_key)
    if _mine is None:
        _drift.append('%s is a list on the page and not in the daemon' % _key)
        continue
    _daemon_values = [str(v) for v, _ in _mine]
    if _page_values != _daemon_values:
        _drift.append('%s: the daemon offers %s, the page offers %s'
                      % (_key, ', '.join(_daemon_values), ', '.join(_page_values)))
if _drift:
    print('a list of choices has drifted:')
    for _line in _drift:
        print('   %s' % _line)
    raise SystemExit(1)
print('every list the SMS card offers holds what the daemon will accept')


# A setting that takes 0 or 1 is a switch, whatever it is called. The kind was
# guessed from the name first, so debug_secrets - a yes-or-no - was drawn as a
# masked box to type a secret into.
_rc = daemon.runtime_config()
_odd = [(k, v['kind']) for k, v in _rc.items()
        if v['kind'] == 'secret' and isinstance(zigmon.Daemon.TUNABLE.get(k), tuple)]
if _odd:
    print('drawn as a secret but taking a number or a switch:')
    for _k, _kind in _odd:
        print('   %s' % _k)
    raise SystemExit(1)
if _rc.get('debug_secrets', {}).get('kind') != 'switch':
    print('debug_secrets is not drawn as a switch')
    raise SystemExit(1)
print('a setting that takes 0 or 1 is drawn as a switch, whatever its name says')


# A tunable the page draws nowhere can only be set by writing it into
# config.json by hand, which nobody discovers. heating_enforce_min was in that
# state from the day it was added.
import re as _re
_page = (DEPLOY.parent / 'web' / 'index.php').read_text() if 'DEPLOY' in dir() \
    else open(str(__file__).rsplit('/', 2)[0] + '/web/index.php').read()
_at = _page.index('var SETTINGS_LAYOUT = [')
_drawn = set(_re.findall(r"\['([a-z_0-9]+)',", _page[_at:_page.index('\n];', _at)]))
_sms = set(_re.findall(r"\['(sms_[a-z_0-9]+)'", _page))
_never = sorted(k for k in zigmon.Daemon.TUNABLE
                if k not in _drawn and k not in _sms and not k.startswith('sms_'))
if _never:
    print('setting(s) no card draws, so they can only be set by editing the file:')
    for _k in _never:
        print('   %s' % _k)
    raise SystemExit(1)
print('every setting the daemon takes is drawn on some card')


# The other way round: a setting a card draws that the daemon will not report
# is a box drawn empty, which cannot be filled in and cannot be saved. The
# whole of the lists and the newer blocking settings were in that state on the
# first try - seven boxes on the card, seven blanks, and no way to tell why.
_shown_only = {'geo_fetch_now'}        # a block that says how things stand, and a button
_unreported = sorted(k for k in _drawn if k not in zigmon.Daemon.TUNABLE and k not in _shown_only)
if _unreported:
    print('setting(s) drawn on a card that the daemon will neither report nor accept:')
    for _k in _unreported[:10]:
        print('   %s' % _k)
    raise SystemExit(1)
print('every setting a card draws is one the daemon reports and will accept')
