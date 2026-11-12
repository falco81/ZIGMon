#!/usr/bin/env python3
"""5.49.2: a box's firmware, put in from the Shelly app, reaches the card.

The model and firmware (Shelly.GetDeviceInfo) were read once and remembered
for good, so the card kept the old version after an update. Read again when
the box has restarted (uptime went back) and every six hours at the latest -
for a single socket and for a strip's sockets alike.

    python3 test/review5492_plugfw.py < /dev/null
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review5492-'))
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


BOX = {'ver': '2.0.0', 'uptime': 5000, 'info_calls': 0}


class FakeRPC(object):
    switch_id = 0

    def call(self, method, params=None):
        if method == 'Shelly.GetStatus':
            return {'sys': {'uptime': BOX['uptime']},
                    'switch:0': {'id': 0, 'output': True, 'apower': 5.0, 'voltage': 230.0},
                    'switch:1': {'id': 1, 'output': False, 'apower': 0.0, 'voltage': 230.0}}
        if method == 'Shelly.GetDeviceInfo':
            BOX['info_calls'] += 1
            return {'model': 'S3PL-30110EU', 'app': 'PlugMG3', 'ver': BOX['ver'], 'gen': 3}
        if method == 'Switch.GetStatus':
            return {'id': 0, 'output': True, 'apower': 5.0, 'voltage': 230.0}
        return {}

    def device_status(self):
        return self.call('Shelly.GetStatus')

    def device_info(self):
        return self.call('Shelly.GetDeviceInfo')

    def switch_status(self):
        return self.call('Switch.GetStatus')


zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'zigmon.db'), 'api_port': 20200, 'token_file': str(W / 'token'),
                      'plugs': [{'name': 'Lamp', 'host': '127.0.0.1:1'}],
                      'sensors': [], 'backup_dir': str(W / 'backups'), 'weather': False, 'state_dir': str(W)})
d = zigmon.Daemon()
try:
    fake = FakeRPC()
    p = d.plugs['Lamp']
    p.rpc = lambda: fake
    # an old reading remembered from before, as a restart of zigmon brings back
    p.info = {'model': 'S3PL-30110EU', 'app': 'PlugMG3', 'ver': '1.7.1'}
    d.poll_plug(p, force=True)
    check((p.info or {}).get('ver') == '2.0.0', 'a remembered firmware is never read again: %r' % p.info)
    calls = BOX['info_calls']
    p.last_device_status = 0
    d.poll_plug(p, force=True)
    check(BOX['info_calls'] == calls, 'the firmware is read on every poll (%d)' % (BOX['info_calls'] - calls))
    # the update: the box restarts with the new firmware
    BOX.update(ver='2.1.0', uptime=30)
    p.last_device_status = 0
    d.poll_plug(p, force=True)
    check((p.info or {}).get('ver') == '2.1.0', 'after a restart of the box its new firmware is not read: %r' % p.info)
    dev = next((x for x in d.store.devices() if x['id'] == 'plug:Lamp'), {})
    check('2.1.0' in str(dev.get('description') or ''), 'the device list keeps the old firmware: %r' % dev.get('description'))
    # six hours on, read again even without a restart
    BOX.update(ver='2.1.1', uptime=40)
    p.info_at = time.time() - getattr(d, 'PLUG_INFO_EVERY_S', 21600) - 1
    p.last_device_status = 0
    d.poll_plug(p, force=True)
    check((p.info or {}).get('ver') == '2.1.1', 'six hours on the firmware is not read again: %r' % p.info)

    # a strip: the lead reads it, every socket takes it
    a = zigmon.PlugState('S-a', {'name': 'S-a', 'host': '127.0.0.1:2', 'switch_id': 0})
    b = zigmon.PlugState('S-b', {'name': 'S-b', 'host': '127.0.0.1:2', 'switch_id': 1})
    for x in (a, b):
        x.rpc = lambda: fake
        x.info = {'model': 'S4PL-00416EU', 'app': 'PowerStrip', 'ver': '1.7.1'}
    BOX.update(ver='2.0.0', uptime=50)
    d.poll_plug_group([a, b], force=True)
    check((a.info or {}).get('ver') == '2.0.0' and (b.info or {}).get('ver') == '2.0.0',
          'a strip keeps its old firmware: %r / %r' % ((a.info or {}).get('ver'), (b.info or {}).get('ver')))
finally:
    try:
        d.store.close()
    except Exception:                                    # noqa: BLE001
        pass
    shutil.rmtree(W, ignore_errors=True)

print('review5492_plugfw: ' + ('all good' if not bad else '%d FAILED' % len(bad)))
sys.exit(1 if bad else 0)
