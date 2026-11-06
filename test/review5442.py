#!/usr/bin/env python3
"""5.44.2: install.sh read /etc/os-release into its own variables. That file
has a VERSION of its own ("9.8 (Olive Jaguar)" on AlmaLinux 9.8), which took
the place of the installer's, so /etc/zigmon-system.json said the root parts
were "zigmon 9.8 (Olive Jaguar)"'s and the dashboard said, after every
install.sh --upgrade, that they were from before the version running.

Run here: the installer's machine check (preflight) with this machine's own
/etc/os-release, its main left out, then what VERSION says. Fails on 5.44.1.

    python3 test/review5442.py
"""
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


src = (HERE / 'install.sh').read_text()
want = re.search(r'^VERSION="([^"]+)"', src, re.M).group(1)
osr = Path('/etc/os-release')
if not osr.exists() or 'VERSION=' not in osr.read_text():
    # a machine without one: a stand-in, as AlmaLinux writes it
    print('  (no /etc/os-release with a VERSION here: the check reads the script)')
    check(not re.search(r'^\s*(\.|source)\s+/etc/os-release\s*$', src, re.M),
          'install.sh sources /etc/os-release into its own variables')
else:
    # the script without its last line (main), its preflight run as root would
    # be - EUID faked, nothing else of it done; resolve_nginx_conf stubbed
    body = src[:src.rstrip().rfind('\nmain')]
    with tempfile.TemporaryDirectory(prefix='zigmon-review5442-') as t:
        script = Path(t) / 'probe.sh'
        script.write_text(body + '\nresolve_nginx_conf() { :; }\nfail() { return 1; }\n'
                          'preflight >/dev/null 2>&1 || true\nprintf "VERSION=%s\\n" "$VERSION"\n')
        got = subprocess.run(['bash', str(script)], capture_output=True, text=True, timeout=60,
                             stdin=subprocess.DEVNULL, cwd=str(HERE),
                             env=dict(os.environ, SOURCE_DIR=str(HERE)))
        line = [x for x in got.stdout.splitlines() if x.startswith('VERSION=')]
        check(line and line[-1] == 'VERSION=' + want,
              'after the machine check install.sh\'s VERSION is %r, not %r (the system\'s own, from '
              '/etc/os-release)' % (line[-1] if line else got.stdout[-200:] + got.stderr[-200:], want))

# ---- the band says only what differs ----------------------------------------
# With the record's version off and every part as install.sh left it, the band
# listed every part as "not as this version ships them".
os.environ['ZIGMON_ROOT_PARTS_CHECK'] = '1'
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import hashlib                                           # noqa: E402
import types                                             # noqa: E402
import zigmon                                            # noqa: E402
with tempfile.TemporaryDirectory(prefix='zigmon-review5442-parts-') as t:
    part = Path(t) / 'zigmon-root.path'
    part.write_text('[Path]\n')
    good = hashlib.sha256(part.read_bytes()).hexdigest()
    helper = types.SimpleNamespace(FS_ROOT='', SYSTEM_STAMP='/etc/zigmon-system.json',
                                   system_level_here=lambda: (1, {'version': '9.8 (Olive Jaguar)',
                                                                  'parts': {str(part): good}}))
    me = types.SimpleNamespace(upgrade_helper=lambda: helper, _some_names=zigmon.Daemon._some_names)
    got = zigmon.Daemon.root_parts_check(me) or {}
    check(got.get('stale') and 'Not as this version ships them' not in got.get('why', '')
          and 'install.sh last ran for zigmon 9.8' in got.get('why', ''),
          'with only the version off the band named every part as not shipped: %r' % got.get('why'))
    part.write_text('changed\n')
    got = zigmon.Daemon.root_parts_check(me) or {}
    check('Not as this version ships them: zigmon-root.path' in got.get('why', ''),
          'a part that differs is not named: %r' % got.get('why'))

# ---- after the upgrade: the old version's item goes at once, Look again looks -------
import shutil                                            # noqa: E402
W2 = Path(tempfile.mkdtemp(prefix='zigmon-review5442-d-'))
try:
    zigmon.load_config()
    zigmon.CONFIG.update({'db_file': str(W2 / 'z.db'), 'api_port': 0, 'token_file': str(W2 / 'tok'),
                          'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '',
                          'state_dir': str(W2)})
    d = zigmon.Daemon()
    d.started = time.time()                              # the first minute after a start
    d.notice_raise('root-parts', 'warn', 'zigmon 5.44.1 is running, but the parts root installs are from before it',
                   'install.sh last ran for zigmon 9.8 (Olive Jaguar)', stamp='5.44.1|9.8 (Olive Jaguar)|1')
    d.upgrade_state_light = lambda: False
    looked = []
    d.root_parts_check = lambda: looked.append(1) or {'stale': False, 'parts': []}
    d.notices_tick()
    check('root-parts' not in d.notices_all(),
          'the item raised by 5.44.1 still stands over %s in the minutes after the start' % zigmon.__version__)
    check(not looked, 'the parts were looked at in the first minutes after a start, unasked')
    # Look again: at once, those minutes too
    d.notice_raise('root-parts', 'warn', 'zigmon %s is running, but ...' % zigmon.__version__, 'why',
                   stamp='%s|9.8 (Olive Jaguar)|1' % zigmon.__version__)
    d._parts_force = True
    d.notices_tick()
    check(looked and 'root-parts' not in d.notices_all(),
          'Look again did not look in the first minutes after a start: %r' % (looked,))
    # ---- "Done lately" cleared (5.44.3): of one pane, or all; what is to do stays ----
    d.notice_raise('backup-failed', 'warn', 'Backups fail', 'why', link='#control/sys-backup')
    d.notice_clear('backup-failed', 'went by itself')
    d.notice_raise('still-open', 'warn', 'Still to do', 'why', link='#control/sys-upgrade')
    before = d.notices_done_view()
    shown = [[x['key'], x['at']] for x in before if x.get('key') != 'backup-failed']   # a pane's own
    gone = d.notices_done_clear(shown, 'owner')
    after = d.notices_done_view()
    check(before and gone == len(shown) and [x.get('key') for x in after] == ['backup-failed'],
          'Done lately: the entries one pane showed were not cleared alone: %r -> %r' % (before, after))
    check('still-open' in d.notices_all(), 'clearing Done lately took away what is still to be done')
    d.notices_done_clear(None, 'owner')
    check(d.notices_done_view() == [], 'Done lately was not cleared whole: %r' % d.notices_done_view())
    page = (HERE / 'web' / 'index.php').read_text()
    fn = page[page.index('function noticeDoneTable('):page.index('function renderNoticeBands(')]
    check("cmdButton('Clear'" in fn and "action: 'clear_done'" in fn, 'Done lately has no Clear on the page')
    src = (HERE / 'zigmon.py').read_text()
    check("if act == 'clear_done':" in src, '/api/notices takes no clear_done')
finally:
    shutil.rmtree(str(W2), ignore_errors=True)

print('review5442: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
sys.exit(1 if bad else 0)
