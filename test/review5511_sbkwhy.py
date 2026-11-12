#!/usr/bin/env python3
"""5.51.1: a box without the backup says why in plain words.

The configuration backup (Sys.CreateBackup and the rest) came with Shelly
firmware 2.2.0. A Mini 1PM Gen4 on 2.1.1 was "not supported" with a reason
naming whole models; it is a firmware too old, and the way out is an update.

    python3 test/review5511_sbkwhy.py < /dev/null
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


class Box(object):
    def __init__(self, ver, methods):
        self.ver, self.methods = ver, methods

    def call(self, method, params=None):
        if method == 'Shelly.GetDeviceInfo':
            return {'id': 'shelly1pmminig4-aabbcc', 'model': 'S4SW-001P8EU', 'app': 'Mini1PMG4', 'ver': self.ver, 'gen': 4}
        if method == 'Shelly.ListMethods':
            return {'methods': self.methods}
        if method == 'Sys.GetStatus':
            return {'cfg_rev': 3, 'uptime': 100}
        if method == 'Shelly.GetConfig':
            return {'switch:0': {'id': 0, 'initial_state': 'restore_last'}}
        return {}


OLD = ['Shelly.GetDeviceInfo', 'Shelly.ListMethods', 'Shelly.GetConfig', 'Sys.GetStatus', 'Shelly.Reboot']
got = zigmon.sbk_look(Box('2.1.1', OLD))
check(got['supported'] is False and '2.1.1 is older than 2.2.0' in got['why'] and 'Firmware' in got['why'],
      'a box on 2.1.1 does not say its firmware is too old: %r' % got['why'])
got = zigmon.sbk_look(Box('2.2.0', OLD))
check(got['supported'] is False and 'not among its methods' in got['why'],
      'a 2.2.0 box without the methods (Plus Uni and the like): %r' % got['why'])
got = zigmon.sbk_look(Box('2.2.0', OLD + list(zigmon.SBK_NEEDS) + list(zigmon.SBK_NEEDS_RESTORE)))
check(got['supported'] is True and not got['why'], 'a box that can: %r' % got)
check(zigmon.sbk_older_than('1.7.1-beta2', '2.2.0') and not zigmon.sbk_older_than('2.10.0', '2.2.0')
      and not zigmon.sbk_older_than('?', '2.2.0'), 'versions compared wrongly')
print('review5511_sbkwhy: ' + ('all good' if not bad else '%d FAILED' % len(bad)))
sys.exit(1 if bad else 0)
