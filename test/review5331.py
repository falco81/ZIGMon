#!/usr/bin/env python3
"""5.33.1: a backup to an SMB share. smbclient reads the machine's network
interfaces before anything else - getifaddrs(), over a netlink socket - and
zigmon.service allowed no netlink: every try ended in "Could not determine
network interfaces, you must use a interfaces config line". Fails on 5.33.0.

    python3 test/review5331.py
"""
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


unit = (HERE / 'deploy' / 'zigmon.service').read_text()
fams = re.search(r'(?m)^RestrictAddressFamilies=(.*)$', unit)
check(fams and 'AF_NETLINK' in fams.group(1).split(),
      'zigmon.service does not let smbclient read the network interfaces (no AF_NETLINK)')
check(fams and not fams.group(1).startswith('~'), 'the families are no longer a list of the allowed ones')
for f in ('AF_INET', 'AF_INET6', 'AF_UNIX'):
    check(fams and f in fams.group(1).split(), '%s went from the families' % f)

# and a service from before says what to do, not samba's words
W = Path(tempfile.mkdtemp(prefix='zigmon-review5331-check-'))
fake = W / 'smbclient'
fake.write_text('#!/bin/sh\necho "ERROR: Could not determine network interfaces, you must use a interfaces '
                'config line" >&2\nexit 1\n')
fake.chmod(0o755)
os.environ['PATH'] = '%s:%s' % (W, os.environ['PATH'])
sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                              # noqa: E402

zigmon.CONFIG['state_dir'] = str(W)
t = {'kind': 'smb', 'host': 'nas.house.example', 'share': 'backup', 'port': 445, 'user': 'u', 'password': 'p',
     'path': 'zigmon'}
s = zigmon.RbSmb(t)
try:
    s.open()
    check(False, 'smbclient failing was taken for working')
except zigmon.RbError as e:
    check('install.sh --upgrade' in str(e) and 'AF_NETLINK' in str(e),
          'the refusal does not say what to do: %s' % e)
    check('p' not in re.findall(r'password\S*', str(e)), 'the password is in the words')
finally:
    s.close()

print('review5331: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
os._exit(1 if bad else 0)
