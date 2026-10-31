#!/usr/bin/env python3
"""The updates of the system (5.34, ported from otp 1.0.158 - 1.0.193): what
dnf has waiting, the update - every package or the security ones only - and
the restart it needs, offered or made by itself, on one machine.

  * root (deploy/zigmon_root.py, run as root would run it, over a folder that
    stands in for the machine): every value of osup.ask checked, a job
    started apart that writes osup.json and osup.log for the group to read,
    one at a time under its lock;
  * a look: the packages waiting, how many of them security, whether the
    update will need a restart (a kernel among them) and whether one is
    waiting already (needs-restarting -r);
  * an update of all, and of the security ones only (dnf --security), with
    its bar and its lines; the restart it needs offered, and made by itself
    when asked so - through Restart and power off, never by dnf or by
    systemctl here; looked at again after it, and after the machine is back;
  * refused while an update or a look goes on, while zigmon is being
    upgraded, while a restart is under way, while root makes a backup of the
    whole installation; a restart refused while dnf runs;
  * the window cleared for good, the update hidden, the log;
  * the schedule: a look every day at its time, the updates in their window
    on their day, each once; the regular restart waiting for an update;
  * the alerts and the daily summary; the settings checked;
  * the API, the relay's entries, the pane, the command line and the console.

    python3 test/osupdates.py

dnf, needs-restarting and systemctl are stood in for by scripts that keep the
machine's packages in a file. Port 19883 (the daemon).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ROOT_HELPER = HERE / 'deploy' / 'zigmon_root.py'
W = Path(tempfile.mkdtemp(prefix='zigmon-osup-check-'))
API_PORT = 19883
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


# ---- the machine's packages, and the tools that look after them ------------------------
FAKE_STATE = W / 'pm.json'
BIN = W / 'bin'
BIN.mkdir()
REBOOT_PKGS = ('kernel', 'kernel-core', 'glibc', 'systemd', 'linux-firmware')


def pm(**kw):
    st = json.loads(FAKE_STATE.read_text()) if FAKE_STATE.exists() else {}
    if kw:
        st.update(kw)
        FAKE_STATE.write_text(json.dumps(st))
    return st


pm(pending=[{'name': 'kernel-core.x86_64', 'ver': '5.14.0-570.el9', 'sec': True},
            {'name': 'openssh.x86_64', 'ver': '8.7p1-45.el9', 'sec': True},
            {'name': 'bash.x86_64', 'ver': '5.1.8-10.el9', 'sec': False}],
   reboot=False, calls=[], slow=0, fail=False)

DNF = r'''#!%(py)s
import json, sys, time
STATE = %(state)r
st = json.load(open(STATE))
st['calls'].append(sys.argv[1:])
json.dump(st, open(STATE, 'w'))
args = [a for a in sys.argv[1:] if a not in ('-q', '-y', '--refresh')]
def keep():
    json.dump(st, open(STATE, 'w'))
if args[:1] == ['check-update']:
    for p in st['pending']:
        print('%%-40s %%-30s %%s' %% (p['name'], p['ver'], 'baseos'))
    sys.exit(100 if st['pending'] else 0)
if args[:3] == ['updateinfo', 'list', '--security']:
    for n, p in enumerate(st['pending']):
        if p['sec']:
            print('ALSA-2026:%%04d Important/Sec. %%s-%%s' %% (n + 100, p['name'].rsplit('.', 1)[0], p['ver']))
    sys.exit(0)
if args[:1] == ['needs-restarting']:
    if st['reboot']:
        print('Core libraries or services have been updated since boot-up:')
        sys.exit(1)
    print('No core libraries or services have been updated since boot-up.')
    sys.exit(0)
if args[:1] == ['upgrade']:
    which = [p for p in st['pending'] if p['sec'] or '--security' not in args]
    print('Dependencies resolved.')
    sys.stdout.flush()
    if st.get('fail'):
        print('Error: Transaction test error: file /usr/bin/x conflicts')
        sys.exit(1)
    print('Downloading Packages:')
    total = len(which)
    for i, p in enumerate(which, 1):
        time.sleep(st.get('slow') or 0)
        print('  Upgrading        : %%-40s %%d/%%d' %% (p['name'] + '-' + p['ver'], i, total))
        sys.stdout.flush()
    for i, p in enumerate(which, 1):
        print('  Verifying        : %%-40s %%d/%%d' %% (p['name'] + '-' + p['ver'], i, total))
    print('Complete!')
    st = json.load(open(STATE))
    st['pending'] = [p for p in st['pending'] if p not in which]
    if any(p['name'].rsplit('.', 1)[0] in %(reboot)r for p in which):
        st['reboot'] = True
    keep()
    sys.exit(0)
print('fake dnf: no such command: %%s' %% ' '.join(args))
sys.exit(2)
''' % {'py': sys.executable, 'state': str(FAKE_STATE), 'reboot': REBOOT_PKGS}
(BIN / 'dnf').write_text(DNF)
(BIN / 'needs-restarting').write_text('''#!%(py)s
import json, sys
STATE = %(state)r
st = json.load(open(STATE))
st['calls'].append(['needs-restarting'] + sys.argv[1:])
json.dump(st, open(STATE, 'w'))
if st['reboot']:
    print('Core libraries or services have been updated since boot-up:\\n  * kernel')
    print('Reboot is required to fully utilize these updates.')
    sys.exit(1)
print('No core libraries or services have been updated since boot-up.')
''' % {'py': sys.executable, 'state': str(FAKE_STATE)})
SYSTEMCTL_LOG = W / 'systemctl.log'
(BIN / 'systemctl').write_text('#!/bin/sh\necho "$@" >> %s\n' % SYSTEMCTL_LOG)
for f in BIN.iterdir():
    f.chmod(0o755)

# ---- the machine, as test/root.py stands it in ------------------------------------------
STATE, ETC = W / 'state', W / 'etc'
for p in (STATE / 'root', STATE / 'backups', STATE / 'upgrade', ETC / 'zigmon'):
    p.mkdir(parents=True, exist_ok=True)
DB = STATE / 'history.db'
(ETC / 'zigmon' / 'config.json').write_text(json.dumps({'db_file': str(DB)}))
BOOT = W / 'boot_id'
BOOT.write_text('boot-one\n')
POWER = W / 'power.log'
os.environ.update(ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(W / 'own'), ZIGMON_FULL_DIR=str(W / 'full'),
                  ZIGMON_CONFIG=str(ETC / 'zigmon' / 'config.json'), ZIGMON_NO_SERVICES='1',
                  ZIGMON_SERVICE_LOG=str(W / 'services.log'), ZIGMON_FS_ROOT=str(W), ZIGMON_USER='root',
                  ZIGMON_FW_FILE4=str(W / 'no4'), ZIGMON_FW_FILE6=str(W / 'no6'),
                  ZIGMON_FIREWALL_CMD=str(W / 'no-firewall-cmd'), ZIGMON_NGINX_TEST='true',
                  ZIGMON_ROOT_RUN='%s -I %s' % (sys.executable, ROOT_HELPER),
                  ZIGMON_OSUP_PATH='%s:/usr/bin:/bin' % BIN, ZIGMON_OSUP_LOCK=str(W / 'osup.lock'),
                  ZIGMON_POWER_CMD=str(POWER), ZIGMON_BTIME_FILE=str(BOOT))
ROOT_DIR = STATE / 'root'


def root_run():
    return subprocess.run([sys.executable, '-I', str(ROOT_HELPER)], capture_output=True, text=True,
                          timeout=120)


def ask_root(body):
    (ROOT_DIR / 'osup.ask').write_text(json.dumps(body))
    root_run()
    try:
        return json.loads((ROOT_DIR / 'osup.ans').read_text())
    except (OSError, ValueError):
        return {}


def job_file():
    try:
        return json.loads((ROOT_DIR / 'osup.json').read_text())
    except (OSError, ValueError):
        return {}


def wait_job(job, secs=60):
    end = time.time() + secs
    while time.time() < end:
        got = job_file()
        if got.get('id') == job and got.get('state') in ('done', 'failed'):
            return got
        time.sleep(0.1)
    return job_file()


try:
    # ---- root on its own --------------------------------------------------------------------
    print('root: what osup.ask may hold')
    for body, why in (({'do': 'run', 'kind': 'remove', 'job': 'a' * 16}, 'a kind of its own'),
                      ({'do': 'shell', 'kind': 'check', 'job': 'a' * 16}, 'another do'),
                      ({'do': 'run', 'kind': 'check', 'job': '../../etc'}, 'a job of the wrong shape'),
                      ({'do': 'run', 'kind': 'check', 'job': 'a' * 16 + '; rm -rf /'}, 'words after the id'),
                      ({'do': 'run', 'kind': 'upgrade', 'job': 'b' * 16, 'security': 'yes'},
                       'security that is not yes or no')):
        got = ask_root(body)
        refused = got.get('ok') is False and bool(got.get('said'))
        check(refused, 'root took %s: %r' % (why, got))
    check(refused and not pm()['calls'], 'dnf was run for a request root refused: %r' % pm()['calls'])
    check(not (ROOT_DIR / 'osup.ask').exists(), 'osup.ask was left behind')

    print('root: a look for updates, as a job of its own')
    got = ask_root({'do': 'run', 'kind': 'check', 'job': 'c' * 16, 'id': 'x1'})
    check(got.get('ok') and (got.get('data') or {}).get('job') == 'c' * 16, 'the look did not start: %r' % got)
    job = wait_job('c' * 16)
    check(job.get('state') == 'done', 'the look did not end well: %r' % job)
    check(job.get('count') == 3 and job.get('security') == 2, 'the look counted %s, %s security'
          % (job.get('count'), job.get('security')))
    check(job.get('reboot_after') and job.get('reboot_why') == ['kernel-core'],
          'a kernel waiting is not said to need a restart after: %r' % job.get('reboot_why'))
    check(job.get('reboot_now') is False, 'a restart is said to be waiting already')
    check(any('check-update' in ln for ln in job.get('lines') or []), 'dnf\'s words are not in osup.json')
    log = (ROOT_DIR / 'osup-check.log').read_text() if (ROOT_DIR / 'osup-check.log').exists() else ''
    check('check-update' in log and 'kernel-core' in log, 'osup-check.log does not hold what dnf said')
    check((ROOT_DIR / 'osup.json').exists() and ((ROOT_DIR / 'osup.json').stat().st_mode & 0o777) == 0o640,
          'osup.json is not there for the group to read (0640)')
    check(['-q', '--refresh', 'check-update'] in pm()['calls'], 'dnf check-update was not run as it should be')

    print('root: one job at a time')
    pm(slow=0.4)
    got = ask_root({'do': 'run', 'kind': 'upgrade', 'job': 'd' * 16, 'security': True})
    check(got.get('ok'), 'the update did not start: %r' % got)
    got2 = ask_root({'do': 'run', 'kind': 'check', 'job': 'e' * 16})
    check(got2.get('ok') is False and 'going on' in (got2.get('said') or ''),
          'a second job was started beside the first: %r' % got2)
    job = wait_job('d' * 16)
    check(job.get('state') == 'done' and job.get('security_only') is True, 'the security update: %r' % job.get('state'))
    check(['-y', '--refresh', 'upgrade', '--security'] in pm()['calls'], 'dnf was not asked for --security')
    check([p['name'] for p in pm()['pending']] == ['bash.x86_64'], 'not only the security updates went in: %r'
          % pm()['pending'])
    check(job.get('reboot') is True, 'the kernel put in is not said to need a restart')
    check(job.get('pct') == 100 and job.get('n', 0) >= 6, 'no bar, or no lines: %r' % job.get('pct'))
    log = (ROOT_DIR / 'osup.log').read_text() if (ROOT_DIR / 'osup.log').exists() else ''
    check('--security' in log and 'Upgrading' in log and 'Complete!' in log, 'osup.log does not hold the update')
    check(job.get('state') == 'done' and not SYSTEMCTL_LOG.exists(), 'systemctl was run by the update: %s' % (
        SYSTEMCTL_LOG.read_text() if SYSTEMCTL_LOG.exists() else ''))
    pm(slow=0, reboot=False, calls=[],
       pending=[{'name': 'kernel-core.x86_64', 'ver': '5.14.0-570.el9', 'sec': True},
                {'name': 'openssh.x86_64', 'ver': '8.7p1-45.el9', 'sec': True},
                {'name': 'bash.x86_64', 'ver': '5.1.8-10.el9', 'sec': False}])

    # ---- the daemon ---------------------------------------------------------------------------
    sys.path.insert(0, str(HERE))
    sys.argv = ['zigmon']
    import zigmon                                       # noqa: E402

    zigmon.load_config()
    zigmon.CONFIG.update({'db_file': str(DB), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                          'token_file': str(W / 'token'), 'plugs': [], 'sensors': [], 'mqtt_host': '',
                          'log_file': '', 'state_dir': str(STATE)})
    d = zigmon.Daemon()
    TOLD = []
    d.notify = lambda message, *a, **k: TOLD.append((str(message), k.get('about')))
    api = zigmon.ApiServer(d)
    api.start()
    time.sleep(0.3)

    def call(path, body=None, session=None):
        headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json',
                   'X-Zigmon-Client': '192.168.40.10'}
        if session:
            headers['X-Zigmon-Session'] = session
        req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                     data=None if body is None else json.dumps(body).encode(),
                                     method='GET' if body is None else 'POST')
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')

    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
    S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
    S_OP = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''

    def osup(body=None, session=None):
        if body is None:
            return call('/api/osup', session=session or S)
        return call('/api/osup', dict(body, session=session or S), session=session or S)

    def settle(key, secs=60):
        """The system loop's part, until the job of `key` is over."""
        end = time.time() + secs
        while time.time() < end:
            zigmon.osup_follow(d)
            row = d._mj(key) or {}
            if row.get('state') not in ('asking', 'running', 'updating'):
                return row
            time.sleep(0.1)
        return d._mj(key) or {}

    print('the API')
    code, v = osup()
    served = code == 200 and v.get('helper') is True and v.get('check') == {}
    check(served, 'the first look at the pane: %s %r' % (code, v))
    code, _ = call('/api/osup')
    check(served and code == 403, 'GET /api/osup answered without a sign-in (%s)' % code)
    code, _ = osup({'action': 'check'}, session=S_OP)
    check(served and code == 403, 'an operator asked for a look for updates (%s)' % code)
    code, v = osup({'action': 'remove'})
    check(code == 400 and 'check, start' in v.get('error', ''), 'an action of its own was taken (%s %r)' % (code, v))
    code, v = osup({'action': 'start', 'security': 'yes'})
    check(code == 400 and 'yes or no' in v.get('error', ''), 'security that is not yes or no was taken: %r' % v)
    code, v = osup({'action': 'start', 'reboot': 'now'})
    check(code == 400 and 'ask or auto' in v.get('error', ''), 'a restart of a third kind was taken: %r' % v)
    check('/api/osup' in zigmon.ApiHandler.ALWAYS_LOCKED, '/api/osup is not an administrator\'s read')

    print('a look for updates, followed')
    code, v = osup({'action': 'check'})
    check(code == 200 and (v.get('check') or {}).get('state') in ('asking', 'running'),
          'the look did not start: %s %r' % (code, v.get('error') or v.get('check')))
    code, v2 = osup({'action': 'check'})
    check(code == 400 and 'going on' in v2.get('error', ''), 'a second look was started beside the first')
    chk = settle('osup:check')
    check(chk.get('state') == 'done', 'the look did not end: %r' % chk)
    code, v = osup()
    ck = v.get('check') or {}
    check(ck.get('count') == 3 and ck.get('security') == 2, 'the pane says %s waiting, %s security'
          % (ck.get('count'), ck.get('security')))
    check(ck.get('reboot_after') and 'kernel-core' in (ck.get('reboot_why') or []),
          'the pane does not say the update will need a restart')
    check(ck.get('checked') and v.get('reboot') is False, 'a restart is said to be waiting before any update')
    check(any('kernel-core.x86_64 5.14.0-570.el9' == p for p in ck.get('packages') or []),
          'the packages waiting are not listed: %r' % ck.get('packages'))
    check(ck.get('lines') and any('check-update' in ln for ln in ck['lines']), 'the look\'s log is not shown')
    check('2 security update(s) waiting' in zigmon.osup_trouble(d), 'the alerts do not see the security updates: %r'
          % zigmon.osup_trouble(d))

    print('the update: security only, the restart offered')
    pm(slow=1.2)
    code, v = osup({'action': 'start', 'security': True, 'reboot': 'ask'})
    check(code == 200 and (v.get('run') or {}).get('security') is True, 'the update did not start: %s %r'
          % (code, v.get('error')))
    time.sleep(0.3)
    zigmon.osup_follow(d)
    # refused while it goes on
    code, v2 = osup({'action': 'start'})
    check(code == 400 and 'going on' in v2.get('error', ''), 'a second update was taken: %r' % v2)
    code, v2 = osup({'action': 'check'})
    check(code == 400 and 'being updated' in v2.get('error', ''), 'a look was taken during the update: %r' % v2)
    try:
        d.power_ask('reboot', 'test')
        check(False, 'a restart was taken while dnf runs')
    except ValueError as e:
        check('being updated' in str(e), 'a restart refused for the wrong reason: %s' % e)
    try:
        d.upgrade_start('test')
        check(False, 'an upgrade of zigmon was taken while dnf runs')
    except ValueError as e:
        check('being updated' in str(e), 'an upgrade of zigmon refused for the wrong reason: %s' % e)
    seen_pct = []
    end = time.time() + 30
    while time.time() < end:
        zigmon.osup_follow(d)
        r = d._mj('osup:run') or {}
        seen_pct.append(r.get('pct'))
        if r.get('state') not in ('asking', 'updating'):
            break
        time.sleep(0.1)
    run = d._mj('osup:run') or {}
    check(run.get('state') == 'done' and run.get('needs_reboot'), 'the update ended %r' % run.get('state'))
    check(any(isinstance(p, int) and 1 < p < 100 for p in seen_pct), 'the bar never moved: %r' % seen_pct[:20])
    check(['-y', '--refresh', 'upgrade', '--security'] in pm()['calls'], 'not dnf --security')
    check([p['name'] for p in pm()['pending']] == ['bash.x86_64'], 'more than the security updates went in')
    check(run.get('state') == 'done' and not POWER.exists(), 'restarted by itself, though the restart was to be offered')
    code, v = osup()
    check(v.get('reboot') is True, 'the restart is not offered after the update')
    check(any('Upgrading' in ln for ln in (v.get('run') or {}).get('lines') or []), 'dnf\'s output is not on the page')
    # looked at again after it, by itself
    chk = settle('osup:check')
    check(chk.get('state') == 'done' and chk.get('count') == 1 and chk.get('reboot_now') is True,
          'not looked at again after the update: %r' % {k: chk.get(k) for k in ('state', 'count', 'reboot_now')})
    check(any('updated' in m and a == 'updates' for m, a in TOLD), 'the update is not told: %r' % TOLD[-3:])

    print('the restart, as Restart and power off makes it')
    code, v = osup({'action': 'reboot'})
    check(code == 200 and d.power_busy(), 'the restart offered was not asked: %s %r' % (code, v.get('error')))
    d.power_tick()
    check(POWER.exists() and 'reboot' in POWER.read_text(), 'root was not asked to restart the machine')
    check(POWER.exists() and not SYSTEMCTL_LOG.exists(), 'systemctl was called here rather than through root')
    BOOT.write_text('boot-two\n')
    pm(reboot=False)
    d.power_tick()
    zigmon.osup_follow(d)
    run = d._mj('osup:run') or {}
    check(run.get('rebooted') is True, 'the restart is not seen: %r' % run)
    chk = settle('osup:check')
    code, v = osup()
    check(code == 200 and v.get('reboot') is False, 'a restart is still said to be needed after it')

    print('the update: all of them, restarted by itself')
    POWER.unlink()
    pm(slow=0, pending=[{'name': 'bash.x86_64', 'ver': '5.1.8-10.el9', 'sec': False},
                        {'name': 'glibc.x86_64', 'ver': '2.34-200.el9', 'sec': False}])
    code, v = osup({'action': 'start', 'security': False, 'reboot': 'auto'})
    check(code == 200, 'the update did not start: %r' % v.get('error'))
    run = settle('osup:run')
    check(run.get('state') == 'rebooting', 'not restarting by itself: %r' % run.get('state'))
    check(['-y', '--refresh', 'upgrade'] in pm()['calls'], 'not dnf upgrade of all')
    check(pm()['pending'] == [], 'not every update went in: %r' % pm()['pending'])
    d.power_tick()
    check(POWER.exists() and 'reboot' in POWER.read_text(), 'the restart it needed was not made')
    BOOT.write_text('boot-three\n')
    pm(reboot=False)
    d.power_tick()
    zigmon.osup_follow(d)
    run = d._mj('osup:run') or {}
    check(run.get('state') == 'done' and 'up again' in (run.get('said') or ''), 'not over after the restart: %r' % run)
    settle('osup:check')
    check((d._mj('osup:check') or {}).get('count') == 0, 'not looked at again after the restart')

    print('refused while something else goes on')
    up = STATE / 'upgrade' / 'status.json'
    up.write_text(json.dumps({'state': 'running', 'at': time.time(), 'id': 'x'}))
    code, v = osup({'action': 'start'})
    check(code == 400 and 'upgrade of zigmon' in v.get('error', ''), 'taken during an upgrade of zigmon: %r' % v)
    up.unlink()
    d.power_ask('reboot', 'test', when=time.strftime('%Y-%m-%d %H:%M', time.localtime(time.time() + 400)))
    d._mj_put('power:plan', dict(d.power_plan(), when=None))           # under way now
    code, v = osup({'action': 'start'})
    check(code == 400 and 'restart' in v.get('error', ''), 'taken during a restart: %r' % v)
    d._mj_put('power:plan', dict(d.power_plan(), done='called off'))
    (ROOT_DIR / 'request.taken').write_text('{"kind": "full_make"}')
    code, v = osup({'action': 'start'})
    check(code == 400 and 'backup of the whole installation' in v.get('error', ''),
          'taken during a whole backup: %r' % v)
    (ROOT_DIR / 'request.taken').unlink()
    code, v = osup()
    check(code == 200 and v.get('blocked') == '', 'still refused when nothing goes on: %r' % v.get('blocked'))

    print('a failed update')
    pm(fail=True, pending=[{'name': 'bash.x86_64', 'ver': '5.1.8-11.el9', 'sec': False}])
    code, v = osup({'action': 'start'})
    run = settle('osup:run')
    check(run.get('state') == 'failed' and 'ended with 1' in (run.get('said') or ''), 'a failure is not said: %r' % run)
    check(any('failed' in m for m, a in TOLD if a == 'updates'), 'the failure is not told')
    settle('osup:check')
    pm(fail=False)

    print('the window cleared for good, the update hidden, the log')
    code, v = osup()
    check((v.get('run') or {}).get('lines'), 'nothing in the window to clear')
    code, v = osup({'action': 'clear'})
    check(code == 200 and (v.get('run') or {}).get('lines') == [] and (v.get('check') or {}).get('lines') == [],
          'the window was not emptied: %r' % (v.get('run') or {}).get('lines'))
    code, v = osup()
    check((v.get('run') or {}).get('lines') == [], 'the lines came back after the window was cleared')
    osup({'action': 'check'})
    settle('osup:check')
    code, v = osup()
    check((v.get('check') or {}).get('lines'), 'a new look after the window was cleared shows nothing')
    code, v = osup({'action': 'hide'})
    check(code == 200 and v.get('run') == {}, 'the update is not hidden: %r' % v.get('run'))
    code, v = osup({'action': 'log'})
    check(code == 200 and 'upgrade' in v.get('log', ''), 'the update\'s log is not given: %r' % v)
    code, v = osup({'action': 'log', 'which': 'check'})
    check(code == 200 and 'check-update' in v.get('log', ''), 'the look\'s log is not given: %r' % v)

    print('the schedule')
    lt = time.localtime()

    def at(days, hh, mm):
        return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + days, hh, mm, 0, 0, 0, -1))
    zigmon.CONFIG.update(osup_check=1, osup_check_at='06:15', osup_auto=0)
    asked = (d._mj('osup:check') or {}).get('job')
    zigmon.osup_sched_tick(d, now=at(1, 6, 0))
    early = (d._mj('osup:check') or {}).get('job') == asked
    zigmon.osup_sched_tick(d, now=at(1, 6, 20))
    chk = d._mj('osup:check') or {}
    came = chk.get('job') != asked and chk.get('by') == zigmon.OSUP_SCHED_BY
    check(came, 'the daily look did not come')
    check(came and early, 'looked before its time')
    settle('osup:check')
    asked = (d._mj('osup:check') or {}).get('job')
    zigmon.osup_sched_tick(d, now=at(1, 9, 0))
    check(came and (d._mj('osup:check') or {}).get('job') == asked, 'looked twice on one day')
    zigmon.CONFIG.update(osup_check=0, osup_auto=1, osup_auto_every='weekly', osup_auto_what='security',
                         osup_auto_at='04:45', osup_auto_reboot='ask')
    sunday = next(n for n in range(2, 9) if time.localtime(at(n, 12, 0)).tm_wday == 6)
    pm(pending=[{'name': 'openssl-libs.x86_64', 'ver': '3.2.2-7.el9', 'sec': True},
                {'name': 'bash.x86_64', 'ver': '5.1.8-12.el9', 'sec': False}], calls=[])
    began = (d._mj('osup:run') or {}).get('id')
    nots = []
    zigmon.osup_sched_tick(d, now=at(sunday - 1, 4, 50))
    nots.append(('the weekly update went on another day', (d._mj('osup:run') or {}).get('id') == began))
    zigmon.osup_sched_tick(d, now=at(sunday, 4, 30))
    nots.append(('the weekly update went before its time', (d._mj('osup:run') or {}).get('id') == began))
    zigmon.osup_sched_tick(d, now=at(sunday, 8, 0))
    nots.append(('the weekly update went long after its window', (d._mj('osup:run') or {}).get('id') == began))
    zigmon.osup_sched_tick(d, now=at(sunday, 4, 50))
    run = d._mj('osup:run') or {}
    went = run.get('id') != began and run.get('security') is True and run.get('by') == zigmon.OSUP_SCHED_BY
    check(went, 'the weekly update did not go in its window: %r' % {k: run.get(k) for k in ('id', 'security', 'by')})
    for words, ok in nots:
        check(went and ok, words)
    run = settle('osup:run')
    check([p['name'] for p in pm()['pending']] == ['bash.x86_64'], 'the update on a schedule was not the security ones')
    settle('osup:check')
    began = run.get('id')
    zigmon.osup_sched_tick(d, now=at(sunday, 5, 30))
    check(went and (d._mj('osup:run') or {}).get('id') == began, 'the weekly update went twice on one day')
    zigmon.CONFIG.update(osup_auto_every='monthly')
    first = next(n for n in range(1, 70) if time.localtime(at(n, 12, 0)).tm_mday == 1 and n != sunday)
    other = next(n for n in range(1, 70) if time.localtime(at(n, 12, 0)).tm_mday != 1 and n != sunday)
    zigmon.osup_sched_tick(d, now=at(other, 5, 0))
    early = (d._mj('osup:run') or {}).get('id') == began
    zigmon.osup_sched_tick(d, now=at(first, 5, 0))
    went = (d._mj('osup:run') or {}).get('id') != began
    check(went, 'the monthly update did not go on the 1st')
    check(went and early, 'the monthly update went on another day than the 1st')
    settle('osup:run')
    settle('osup:check')
    zigmon.CONFIG.update(osup_auto=0)

    print('the regular restart waits for an update')
    pm(slow=0.5, pending=[{'name': 'bash.x86_64', 'ver': '5.1.8-13.el9', 'sec': False}])
    osup({'action': 'start'})
    zigmon.CONFIG.update(reboot_auto='daily', reboot_at=time.strftime('%H:%M'))
    d.store.set_meta('power:auto_day', '')
    d.power_auto_tick()
    waited = bool((d._mj('power:auto_wait') or {}).get('day'))
    check(waited, 'the regular restart did not wait for the update')
    check(waited and (not d.power_plan().get('id') or d.power_plan().get('done')),
          'the regular restart cut the update off')
    zigmon.CONFIG.update(reboot_auto='off')
    settle('osup:run')
    settle('osup:check')
    pm(slow=0)

    print('the settings')
    for key, value in (('osup_auto_what', 'some'), ('osup_auto_every', 'hourly'), ('osup_auto_reboot', 'never'),
                       ('osup_check_at', '25:00'), ('osup_auto_at', 'dawn'), ('osup_auto_day', 9)):
        try:
            d.save_config_overrides({key: value})
            check(False, '%s=%r was taken' % (key, value))
        except ValueError:
            pass
    d.save_config_overrides({'osup_auto_what': 'all', 'osup_auto_every': 'daily', 'osup_check_at': '07:05'})
    check(zigmon.CONFIG['osup_auto_what'] == 'all' and zigmon.CONFIG['osup_check_at'] == '07:05',
          'good settings were not taken')
    for k in ('osup_check', 'osup_check_at', 'osup_auto', 'osup_auto_what', 'osup_auto_every', 'osup_auto_day',
              'osup_auto_at', 'osup_auto_reboot'):
        check(k in zigmon.DEFAULTS and k in zigmon.Daemon.TUNABLE, '%s is not a setting' % k)
    check(zigmon.DEFAULTS.get('osup_check') == 0 and zigmon.DEFAULTS.get('osup_auto') == 0,
          'the schedule is not off until switched on')

    print('the alerts and the daily summary')
    d._mj_put('osup:check', dict(d._mj('osup:check') or {}, security=2, count=3, checked=time.time()))
    TOLD.clear()
    d._host_at = 0
    d.store.set_meta('osup:told', '')
    d.check_system_alerts()
    check(any(a == 'updates' and 'security' in m for m, a in TOLD), 'no alert of the security updates: %r' % TOLD)
    said = any(a == 'updates' for m, a in TOLD)
    n = len(TOLD)
    d._host_at = 0
    d.check_system_alerts()
    check(said and len([1 for m, a in TOLD[n:] if a == 'updates']) == 0, 'the alert was said again the same day')
    text = d.daily_digest(force=True) or ''
    check('The system: 3 update(s) waiting, 2 of them security' in text, 'the daily summary does not say it: %r' % text)
    check('updates' in {k[0] for k in zigmon.Daemon.SYSTEM_ALERTS}, 'the alerts card has no kind for the updates')

    print('the command line and the console')
    parser = zigmon.build_parser()
    args = parser.parse_args(['--updates', 'update', '--security', '--reboot', 'auto'])
    check(args.updates == 'update' and args.security and args.reboot == 'auto', '--updates is not taken')
    check(parser.parse_args(['--updates']).updates == 'show', '--updates alone does not show')
    check(any(w == 'System updates' for w, _ in zigmon.CONSOLE_MORE['main']), 'the console has no System updates')
    src = (HERE / 'zigmon.py').read_text()
    check("('sudo zigmon --updates'" in src, 'the help does not name --updates')
    import io
    import contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = zigmon.cmd_updates(parser.parse_args(['--updates', '--no-color']), zigmon.Palette(False))
    check(rc == 0 and re.search(r'waiting +3', out.getvalue()) and re.search(r'security +2', out.getvalue()),
          '--updates did not show what is waiting: %r' % out.getvalue()[:300])
    # a look and an update from the command line, followed while the system
    # loop's part runs beside them
    import threading
    loop_on = threading.Event()
    loop_on.set()

    def loop():
        while loop_on.is_set():
            zigmon.osup_follow(d)
            time.sleep(0.2)
    threading.Thread(target=loop, daemon=True).start()
    pm(pending=[{'name': 'curl.x86_64', 'ver': '7.76.1-31.el9', 'sec': True}], calls=[])
    for argv, want in ((['--updates', 'look'], 'check-update'),
                       (['--updates', 'update', '--security', '--yes'], 'Upgrading'),
                       (['--updates', 'log'], 'Complete!')):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = zigmon.cmd_updates(parser.parse_args(argv + ['--no-color']), zigmon.Palette(False))
        check(rc == 0 and want in out.getvalue(), 'zigmon %s: %s %r' % (' '.join(argv), rc, out.getvalue()[-300:]))
    check(pm()['pending'] == [], 'zigmon --updates update did not update')
    loop_on.clear()
    time.sleep(0.3)
    settle('osup:check')

    print('the relay, the pane, the path unit')
    page = (HERE / 'web' / 'index.php').read_text()
    allowed = page[page.index("if (in_array($what, ['scenes-save'"):]
    allowed = allowed[:allowed.index('], true)')]
    check("'osup-do'" in allowed, 'osup-do is not let through by the relay')
    check("'osup-do' => '/api/osup'" in page, 'osup-do is not mapped to /api/osup')
    check("$what === 'osup'" in page and "zigmon_relay('/api/osup')" in page, 'the relay does not read /api/osup')
    menu = page[page.index('<div class="ctl-group">Monitoring and updates</div>'):]
    menu = menu[:menu.index('</nav>')]
    check('data-sec="sys-osup"' in menu and menu.index('sys-upgrade') < menu.index('sys-osup'),
          'System updates is not beside Upgrades in Monitoring and updates')
    for words in ('id="ou-host"', 'function drawOsup(', "'Look for updates'", "'Clear the window'",
                  "'Hide it'", "' waiting'", "' security'", "'restart needed'", "'restart after the update'",
                  "'pw-break'", "'Only the security updates'", "'Restart by itself when needed'",
                  "'On a schedule': 'sys-osup'", 'id="set-host-sys-osup"', "'sys-osup': ['System updates'"):
        check(words in page, 'the pane has no %s' % words)
    unit = (HERE / 'deploy' / 'zigmon-root.path').read_text()
    check('PathExists=/var/lib/zigmon/root/osup.ask' in unit, 'zigmon-root.path does not watch osup.ask')
    helper = ROOT_HELPER.read_text()
    check('osup_part' in helper[helper.index('def serve():'):], 'serve() does not answer osup.ask')
finally:
    try:
        api.stop()
    except Exception:
        pass

if bad:
    print('\n%d problem(s)' % len(bad))
    raise SystemExit(1)
shutil.rmtree(str(W), ignore_errors=True)
print('\nSystem updates: every check passed')
