#!/usr/bin/env python3
"""5.27: a few backups deleted one after another stopped root for good.
Every check fails on 5.26.0 and passes since.

    python3 test/review527.py

zigmon-root.service is started by its path unit for every request; systemd
lets a unit start five times in ten seconds and then refuses it - and the path
unit with it - until somebody runs systemctl reset-failed. Deleting backups
one after another, with the page asking what is in place between them,
reached that: every request after it waited for root for half an hour.
"""
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


print('root is never stopped by the limit on how often it starts')
for unit in ('zigmon-root.service', 'zigmon-root.path', 'zigmon-upgrade.service', 'zigmon-upgrade.path'):
    text = (HERE / 'deploy' / unit).read_text()
    unit_part = text.split('[Unit]', 1)[-1].split('\n[', 1)[0]
    check(re.search(r'^StartLimitIntervalSec=0$', unit_part, re.M),
          '%s is stopped by systemd after five starts in ten seconds' % unit)
sh = (HERE / 'install.sh').read_text()
check('reset-failed zigmon-root.service zigmon-root.path' in sh,
      'an upgrade leaves a root unit stopped by the old limit stopped')

print('the page says when root does not take what was asked, and asks one thing at a time')
page = (HERE / 'web' / 'index.php').read_text()
check('function rootStuck(' in page and 'systemctl reset-failed zigmon-root.service' in page,
      'a request root never takes says "waiting for root" for half an hour and nothing else')
full = page[page.index('function drawFull('):page.index('function fullDownload(')]
check('if (d.busy) [rs, rm].forEach' in full, 'delete and put back are offered while root works on the last one')

if bad:
    print('\n%d check(s) failed' % len(bad))
    os._exit(1)
print('root keeps taking what is asked of it')
os._exit(0)
