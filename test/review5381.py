#!/usr/bin/env python3
"""5.38.1 (otp 1.0.210): the machine's console flooded with
"systemd-rc-local-generator: /etc/rc.d/rc.local is not marked executable,
skipping" at every daemon-reload, over the zigmon console at login on tty1.
install.sh keeps the console to errors (kernel.printk 4 4 1 7, in a file of
its own), leaves an administrator's own kernel.printk alone, writes it the
same on every run, and the uninstall takes it away. Fails on 5.38.0.

    python3 test/review5381.py
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
src = (HERE / 'install.sh').read_text()
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


start = src.find("# The machine's own screen")
end = src.find('install_console() {')
if start < 0 or end < 0 or start > end:
    print('  FAILED: install.sh does not keep the console to errors')
    sys.exit(1)
funcs = src[start:end]
W = Path(tempfile.mkdtemp(prefix='zigmon-review5381-check-'))
(W / 'bin').mkdir()
(W / 'bin' / 'sysctl').write_text('#!/bin/sh\necho "sysctl $*" >> %s/sysctl.log\n' % W)
(W / 'bin' / 'sysctl').chmod(0o755)


def run(extra=''):
    script = '''set -u
say() { echo "SAY $*"; }; good() { echo "GOOD $*"; }; note() { echo "NOTE $*"; }; step() { :; }
DRY_RUN=""
SYSCTL_DIR=%s/sysctl.d SYSCTL_CONF=%s/sysctl.conf
%s
%s
console_quiet
''' % (W, W, funcs, extra)
    return subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                          env=dict(os.environ, PATH='%s:%s' % (W / 'bin', os.environ['PATH'])),
                          stdin=subprocess.DEVNULL, timeout=30)


conf = W / 'sysctl.d' / '80-zigmon-console.conf'
got = run()
check(conf.exists() and re.search(r'(?m)^kernel\.printk = 4 4 1 7$', conf.read_text()),
      'kernel.printk 4 4 1 7 was not written: %s' % got.stdout)
check(oct(conf.stat().st_mode & 0o777) == '0o644' if conf.exists() else False, 'the file is not 0644')
check('-p %s' % conf in (W / 'sysctl.log').read_text() if (W / 'sysctl.log').exists() else False,
      'it was not put in force at once (sysctl -p)')
first = conf.read_text() if conf.exists() else ''
run()
check(conf.read_text() == first and conf.read_text().count('kernel.printk') == 1,
      'a second run (an upgrade) did not leave it as it was')
# the administrator's own
conf.unlink()
(W / 'sysctl.d' / '50-mine.conf').write_text('kernel.printk = 7 4 1 7\n')
got = run()
check(not conf.exists() and 'set by hand' in got.stdout, 'an administrator\'s own kernel.printk was not left alone')
(W / 'sysctl.d' / '50-mine.conf').unlink()
(W / 'sysctl.conf').write_text('  kernel.printk=3 4 1 3\n')
run()
check(not conf.exists(), 'one in /etc/sysctl.conf was not left alone')
(W / 'sysctl.conf').unlink()
# the uninstall takes it away
check('"$CONSOLE_SYSCTL"' in src[src.index('do_uninstall() {'):src.index('do_uninstall() {') + 1500],
      'the uninstall does not take the file away')
# both the install and the upgrade do it
check(src.count('    console_quiet\n') >= 2, 'not both the install and the upgrade keep the console quiet')
print('review5381: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
sys.exit(1 if bad else 0)
