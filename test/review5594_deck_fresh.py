#!/usr/bin/env python3
"""A change that comes a moment after another still reaches the Stream Deck (5.59.4).

Seen on a deck: a socket switched on showed "0 W" and stayed so. Its watts came a few
hundredths of a second after the switching, inside the fifth of a second in which the deck's
states are not looked at twice - and that look was dropped, not put off, so nothing told the
deck until the house changed again.

  * a look asked for inside the fifth of a second is made once it is over;
  * many asked for in that time are one look, not many;
  * a look asked for later is made at once, as before.

    python3 test/review5594_deck_fresh.py < /dev/null

No broker, no web server. Every name here is made up.
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.log = lambda *a, **k: None

d = zigmon.Daemon.__new__(zigmon.Daemon)
d._deck_cond = None
d._deck_setup()
watts = {'v': 0}
looks = {'n': 0}


def items(fresh=False):
    looks['n'] += 1
    return [{'id': 'Plug-Test', 'state': {'on': True, 'value': watts['v'], 'value_text': '%s W' % watts['v'], 'attrs': {}}}]


d.deck_items = items

print('switched on: 0 W, seen at once')
d._deck_refresh(force=True)
check(d._deck_states['Plug-Test'][1]['value'] == 0, 'the first look was not made')
seq0 = d._deck_seq

print('the watts a moment later, inside the fifth of a second')
watts['v'] = 42
d._deck_refresh()
d._deck_refresh()
d._deck_refresh()
time.sleep(0.6)
check(d._deck_states['Plug-Test'][1]['value'] == 42, 'the watts never reached the deck: %r' % d._deck_states['Plug-Test'][1])
check(d._deck_seq == seq0 + 1, 'the change was not told once: %d' % (d._deck_seq - seq0))
check(looks['n'] == 2, 'three asks inside the fifth of a second were not one look: %d' % looks['n'])

print('later: at once')
time.sleep(0.3)
watts['v'] = 7
d._deck_refresh()
check(d._deck_states['Plug-Test'][1]['value'] == 7, 'a look asked for later was not made at once')

print('FAILED: %d' % len(bad) if bad else 'all good')
sys.exit(1 if bad else 0)
