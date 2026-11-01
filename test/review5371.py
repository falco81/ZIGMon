#!/usr/bin/env python3
"""5.37.1: a backup of the whole installation handed over for a download
cleared root's hand-over folder - a certificate with its key, made for a
download and not fetched yet, went with it. Fails on 5.37.0.

    python3 test/review5371.py
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review5371-check-'))
(W / 'state' / 'root' / 'out').mkdir(parents=True)
(W / 'full').mkdir()
os.environ.update(ZIGMON_STATE=str(W / 'state'), ZIGMON_ROOT_OWN=str(W / 'own'), ZIGMON_FULL_DIR=str(W / 'full'),
                  ZIGMON_NO_SERVICES='1', ZIGMON_USER='root')
sys.path.insert(0, str(HERE / 'deploy'))
import zigmon_root as R                                       # noqa: E402

bad = []
out = W / 'state' / 'root' / 'out'
(out / 'zigmon-cert-mqtt.house.example.pfx').write_bytes(b'a certificate waiting to be fetched')
(out / 'zigmon-full-old.tar.gz').write_bytes(b'an old hand-over')
name = 'zigmon-full-house-2026-11-01-040000.tar.gz'
if not R.FULL_FILE.match(name):
    print('  FAILED: the test\'s backup name is not one root takes: %s' % name)
    sys.exit(1)
(W / 'full' / name).write_bytes(b'a backup')
R.handle({'kind': 'full_get', 'file': name})
left = sorted(os.listdir(out))
if 'zigmon-cert-mqtt.house.example.pfx' not in left:
    bad.append('a certificate waiting to be downloaded was cleared by a backup\'s hand-over: %r' % left)
if 'zigmon-full-old.tar.gz' in left or name not in left:
    bad.append('the backup was not handed over in place of the old one: %r' % left)
for b in bad:
    print('  FAILED: ' + b)
print('review5371: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
sys.exit(1 if bad else 0)
