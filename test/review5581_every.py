#!/usr/bin/env python3
"""5.58.1: the proxy's logs may be read every half a minute.

  * "every half a minute" is offered (and the rest stay);
  * a reading asked for every 30 s comes on the half-minute beat, even when the
    beat is a hair early - it used to come every other beat, a minute apart;
  * nothing shorter than half a minute, whatever the settings file says, and
    rubbish there means the two minutes it comes as.

    python3 test/review5581_every.py
"""
import sys
from pathlib import Path

sys.argv = ['zigmon']
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import zigmon  # noqa: E402

bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


choices = [c[0] for c in zigmon.Daemon.TUNABLE_CHOICES['proxy_every']]
check(choices[:1] == ['0.5'] and {'1', '2', '5', '15'} <= set(choices), 'the choices: %r' % choices)
check(zigmon.DEFAULTS['proxy_every'] == '2' if hasattr(zigmon, 'DEFAULTS') else True, 'the default changed')


class D:
    pass


due = getattr(zigmon.Daemon, 'proxy_due', None)
check(due is not None, 'no proxy_due')
if due:
    d = D()
    saved = zigmon.CONFIG.get('proxy_every')
    try:
        zigmon.CONFIG['proxy_every'] = '0.5'
        d._proxy_at_clock = 1000.0
        check(due(d, 1029.0), 'a beat a second early is on time')
        check(not due(d, 1020.0), 'ten seconds early is not')
        zigmon.CONFIG['proxy_every'] = '1'
        check(not due(d, 1030.0) and due(d, 1059.5), 'every minute')
        zigmon.CONFIG['proxy_every'] = '0.01'
        check(not due(d, 1010.0), 'nothing under half a minute')
        zigmon.CONFIG['proxy_every'] = 'often'
        check(not due(d, 1090.0) and due(d, 1119.0), 'rubbish is two minutes')
        d2 = D()
        check(due(d2, 1.7e9), 'never read yet: read now')
    finally:
        zigmon.CONFIG['proxy_every'] = saved

print('review5581_every: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
sys.exit(1 if bad else 0)
