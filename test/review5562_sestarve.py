#!/usr/bin/env python3
"""5.56.2: SELinux's look is not starved on a busy disk, and says so when root is slow.

After an OS update and a restart the disk was busy for minutes (man-db, an integrity
check), and the card said "root did not answer in 180 s - is zigmon-root.path running?".
The path unit ran; root had the question and its tools (semodule, semanage, ausearch)
waited in the idle I/O class, which gets the disk only when nobody else wants it.

  * root runs the heavy tools as best effort at the lowest level, never the idle class;
  * a look waits ten minutes, as a step does;
  * a question root took and has not finished is said as that, not as a dead path unit;
    one nobody took still says to look at zigmon-root.path.

    python3 test/review5562_sestarve.py < /dev/null
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'deploy'))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402
import zigmon_root                                       # noqa: E402

bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


# root's tools: best effort at its lowest, not the idle class
ran = []
real_which, real_run, real_tool = shutil.which, subprocess.run, zigmon_root.se_tool
zigmon_root.se_tool = lambda name: '/usr/sbin/' + name
zigmon_root.shutil.which = lambda name: '/usr/bin/' + name if name in ('ionice', 'nice') else real_which(name)
zigmon_root.subprocess.run = lambda cmd, **k: ran.append(list(cmd)) or subprocess.CompletedProcess(cmd, 0, '', '')
zigmon_root.se_run(['semodule', '-l'], 120, light=True)
zigmon_root.shutil.which, zigmon_root.subprocess.run, zigmon_root.se_tool = real_which, real_run, real_tool
cmd = ran[0] if ran else []
i = cmd.index('/usr/bin/ionice') if '/usr/bin/ionice' in cmd else -1
check(i >= 0 and cmd[i + 1:i + 3] == ['-c', '2'] and cmd[i + 3:i + 5] == ['-n', '7'],
      'the heavy tools are not run as best effort at the lowest level: %r' % cmd)
check('3' not in cmd[i + 1:i + 3], 'the heavy tools still wait in the idle class: %r' % cmd)

# the look waits as long as a step
src = (HERE / 'zigmon.py').read_text()
work = src[src.index('def selinux_work('):src.index('def selinux_notice(')]
m = re.search(r"root_call\('selinux\.ask', 'selinux\.json', ask,\s*([^)]*)\)", work)
check(m is not None and m.group(1).strip() == '600', 'a look still waits less than ten minutes: %r'
      % (m.group(1) if m else None))

# what is said when root does not answer in time
W = Path(tempfile.mkdtemp(prefix='zigmon-sestarve-'))


class D(object):
    def root_dir(self, *names):
        return W.joinpath(*names)

    def root_read(self, name):
        try:
            return json.loads((W / name).read_text())
        except (OSError, ValueError):
            return {}

    def root_busy(self):
        return None


D._root_call = zigmon.Daemon._root_call
os.environ.pop('ZIGMON_ROOT_RUN', None)
d = D()


def taker():                                             # root takes the question and works on
    end = time.time() + 3
    while time.time() < end:
        if (W / 'selinux.ask').exists():
            os.unlink(str(W / 'selinux.ask'))
            return
        time.sleep(0.02)


th = threading.Thread(target=taker)
th.start()
try:
    d._root_call('selinux.ask', 'selinux.json', {'do': 'check'}, 0.8)
    said = ''
except ValueError as e:
    said = str(e)
th.join()
check('took the question' in said and 'zigmon-root.path running' not in said,
      'a question root took is said as a dead path unit: %r' % said)
try:
    d._root_call('selinux.ask', 'selinux.json', {'do': 'check'}, 0.5)
    said = ''
except ValueError as e:
    said = str(e)
check('zigmon-root.path' in said and not (W / 'selinux.ask').exists(),
      'a question nobody took does not point at the path unit, or is left behind: %r' % said)
shutil.rmtree(str(W), ignore_errors=True)

print('review5562_sestarve: ' + ('all good' if not bad else '%d FAILED' % len(bad)))
sys.exit(1 if bad else 0)
