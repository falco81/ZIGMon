#!/usr/bin/env python3
"""The console and its start at login (5.21).

  * the login hook (deploy/zz-zigmon-console.sh, sourced from /etc/profile.d)
    starts `zigmon --console` for root's interactive login with the switch
    on - and in no other case: the flag missing, a link, "off"; a command
    run over SSH; ZIGMON_NO_CONSOLE; a shell opened from the console itself
    (ZIGMON_CONSOLE); somebody who is not root; no terminal. It is run in a
    real interactive bash on a pseudo-terminal, with its two paths pointed at
    a stub that only writes down that it was started;
  * `zigmon --console-at-login on|off` is root's alone, and replaces a link
    or a pipe planted where the flag goes rather than writing through it;
    the flag is read without following a link or waiting on a pipe;
  * `zigmon --console` without a terminal says so and does nothing;
  * the console's own parts that need no screen: the keys a terminal sends
    as raw escape sequences, the live view's grep taking a broken regular
    expression as plain words, a two-digit jump in a menu of eleven, and
    the menus that other parts of zigmon add themselves to;
  * the console itself on a pseudo-terminal: it starts on its menu, goes into
    a submenu and back with Esc, opens a shell that is told it came from the
    console, opens the live log and filters it, and q closes it.

Nothing is installed and nothing on the machine is touched.

    python3 test/console.py
"""
import os
import pty
import re
import select
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-console-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def plain(s):
    return re.sub(r'\x1b(\[[0-9;?]*[A-Za-z]|[()][0-9A-Za-z]|[=>78])', '', s)


def on_pty(argv, env, keys=(), wait_for=(), timeout=20.0, rows=30, cols=110):
    """`argv` on a pseudo-terminal of `rows` x `cols`. `keys` is a list of
    (text to wait for or None, bytes to type): each is typed once the
    text has been seen. Returns (everything it wrote, exit status or None)."""
    import fcntl
    import termios
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.execvpe(argv[0], argv, env)
        finally:
            os._exit(127)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
    got = b''
    keys = list(keys)
    end = time.time() + timeout
    status = None
    mark = 0
    while time.time() < end:
        if keys:
            want, send = keys[0]
            if want is None or want in plain(got[mark:].decode('utf-8', 'replace')):
                time.sleep(0.3)
                os.write(fd, send)
                mark = len(got)
                keys.pop(0)
                continue
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                chunk = b''
            if not chunk:
                break
            got += chunk
        done, st = os.waitpid(pid, os.WNOHANG)
        if done:
            status = st
            try:
                while True:
                    r, _, _ = select.select([fd], [], [], 0.2)
                    if not r:
                        break
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        break
                    got += chunk
            except OSError:
                pass
            break
    if status is None:
        try:
            done, st = os.waitpid(pid, os.WNOHANG)
            if done:
                status = st
            else:
                os.kill(pid, signal.SIGKILL)      # by its own PID, never by its name
                os.waitpid(pid, 0)
        except OSError:
            pass
    os.close(fd)
    return got.decode('utf-8', 'replace'), status


# ---- the login hook -------------------------------------------------------------
hook_src = (HERE / 'deploy' / 'zz-zigmon-console.sh').read_text()
check('/usr/local/bin/zigmon' in hook_src and '/etc/zigmon-console-login' in hook_src,
      'the hook no longer names /usr/local/bin/zigmon and /etc/zigmon-console-login, so '
      'pointing them elsewhere below proves nothing')
check('exec ' not in hook_src, 'the hook execs the console: q would end the login, not leave '
      'it for the shell')
install_sh = (HERE / 'install.sh').read_text()
check('/etc/profile.d/zz-zigmon-console.sh' in install_sh and 'install_console' in install_sh,
      'install.sh does not put the hook in /etc/profile.d')
check(re.search(r'rm -f[^\n]*/etc/profile\.d/zz-zigmon-console\.sh[^\n]*/etc/zigmon-console-login',
                install_sh), 'install.sh --uninstall leaves the hook or the flag behind')

stub = W / 'zigmon'
marker = W / 'started'
flag = W / 'zigmon-console-login'
stub.write_text('#!/bin/sh\necho "$* ZIGMON_CONSOLE=$ZIGMON_CONSOLE" > %s\n' % marker)
stub.chmod(0o755)
hook = W / 'hook.sh'
hook.write_text(hook_src.replace('/usr/local/bin/zigmon', str(stub))
                .replace('/etc/zigmon-console-login', str(flag)))
bin_dir = W / 'bin'
bin_dir.mkdir()
fake_id = bin_dir / 'id'


def as_uid(uid):
    # id is asked for the uid; a stub on PATH answers, so the check runs the
    # same whoever runs it
    fake_id.write_text('#!/bin/sh\necho %d\n' % uid)
    fake_id.chmod(0o755)


def login(env_extra=None, tty=True, uid=0):
    """The hook sourced by an interactive bash, as /etc/profile sources it."""
    as_uid(uid)
    if marker.exists():
        marker.unlink()
    env = {'PATH': '%s:/usr/bin:/bin' % bin_dir, 'HOME': str(W), 'TERM': 'dumb',
           'PS1': '$ '}
    env.update(env_extra or {})
    argv = ['bash', '--noprofile', '--norc', '-i', '-c', '. "%s"; exit 0' % hook]
    if tty:
        on_pty(argv, env, timeout=10)
    else:
        subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10)
    return marker.read_text().strip() if marker.exists() else None


def set_flag(what):
    if flag.is_symlink() or flag.exists():
        flag.unlink()
    if what is not None:
        flag.write_text(what)


set_flag(None)
check(login() is None, 'the console was started with no flag at all')
set_flag('off\n')
check(login() is None, 'the console was started with the flag saying off')
target = W / 'says-on'
target.write_text('on\n')
set_flag(None)
flag.symlink_to(target)
check(login() is None, 'the console was started through a link where the flag goes')
set_flag('on\n')
said = login()
check(said == '--console ZIGMON_CONSOLE=1', 'root\'s login with the flag on did not start '
      '`zigmon --console` with ZIGMON_CONSOLE=1 (it said %r)' % said)
check(login({'SSH_ORIGINAL_COMMAND': 'ls'}) is None, 'the console was started for a command '
      'run over SSH')
check(login({'ZIGMON_NO_CONSOLE': '1'}) is None, 'the console was started with ZIGMON_NO_CONSOLE')
check(login({'ZIGMON_CONSOLE': '1'}) is None, 'the console was started in a shell opened from '
      'the console')
check(login(uid=1000) is None, 'the console was started for somebody who is not root')
check(login(tty=False) is None, 'the console was started without a terminal')
stub.chmod(0o644)
check(login() is None, 'the console was started with no zigmon program to start')
stub.chmod(0o755)
check(login() is not None, 'the console was not started again once everything was in place')

# ---- the switch ------------------------------------------------------------------
os.environ['ZIGMON_CONSOLE_FLAG'] = str(W / 'flag2')
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon  # noqa: E402

flag2 = W / 'flag2'
real_euid = os.geteuid
try:
    os.geteuid = lambda: 1000
    try:
        zigmon.console_at_login_set(True)
        check(False, 'somebody who is not root switched the console at login on')
    except PermissionError as e:
        check('only root' in str(e), 'refused without saying why: %s' % e)
    check(not flag2.exists() and not list(W.glob('flag2.*')), 'refused, and a file was written '
          'all the same')
    os.geteuid = lambda: 0
    victim = W / 'victim'
    victim.write_text('victim\n')
    flag2.symlink_to(victim)
    check(zigmon.console_at_login() is False, 'a link where the flag goes was followed and read '
          'as on')
    victim.write_text('on\n')
    check(zigmon.console_at_login() is False, 'a link to a file saying on was taken for the flag')
    zigmon.console_at_login_set(False)
    check(victim.read_text() == 'on\n', 'the switch wrote through a planted link')
    check(not flag2.is_symlink() and flag2.read_text() == 'off\n',
          'the planted link was not replaced by the flag')
    check(stat.S_IMODE(flag2.stat().st_mode) == 0o644, 'the flag is not 0644')
    flag2.unlink()
    os.mkfifo(str(flag2))
    t0 = time.time()
    check(zigmon.console_at_login() is False and time.time() - t0 < 2,
          'a pipe where the flag goes was waited on, or read as on')
    leftover = Path('%s.%d.tmp' % (flag2, os.getpid()))
    leftover.write_text('stale')
    zigmon.console_at_login_set(True)
    check(stat.S_ISREG(os.lstat(str(flag2)).st_mode) and flag2.read_text() == 'on\n'
          and zigmon.console_at_login() is True, 'a planted pipe was not replaced by the flag')
    check(not leftover.exists(), 'a temporary file left by an earlier run stopped the switch')
finally:
    os.geteuid = real_euid

env = dict(os.environ, ZIGMON_CONSOLE_FLAG=str(W / 'flag3'))
if os.geteuid() == 0 and Path('/usr/bin/setpriv').exists():
    # and as a real user who is not root, where one can be had
    W.chmod(0o755)
    out = subprocess.run(['/usr/bin/setpriv', '--reuid=65534', '--regid=65534', '--clear-groups',
                          sys.executable, str(HERE / 'zigmon.py'), '--console-at-login', 'on'],
                         env=env, capture_output=True, text=True, timeout=60)
    if 'Permission denied' not in out.stderr or 'zigmon.py' not in out.stderr:
        check(out.returncode == 2 and 'only root' in out.stderr and not (W / 'flag3').exists(),
              'nobody switched the console at login: %s %s' % (out.returncode, out.stderr[-200:]))
out = subprocess.run([sys.executable, str(HERE / 'zigmon.py'), '--console-at-login', 'status'],
                     env=env, capture_output=True, text=True, timeout=60)
check(out.returncode == 0 and 'is off' in out.stdout, '--console-at-login status: %r' % out.stdout)
out = subprocess.run([sys.executable, str(HERE / 'zigmon.py'), '--console-at-login', 'maybe'],
                     env=env, capture_output=True, text=True, timeout=60)
check(out.returncode == 2, '--console-at-login took a word that is neither on nor off')

# ---- no terminal -----------------------------------------------------------------
out = subprocess.run([sys.executable, str(HERE / 'zigmon.py'), '--console'], env=env,
                     stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
check(out.returncode == 2 and 'zigmon: the console needs a terminal' in out.stderr,
      '--console without a terminal: %s %r' % (out.returncode, out.stderr))

# ---- the parts that need no screen ---------------------------------------------
K = zigmon.console_key
for raw, name in ((b'\x1b[A', 'up'), (b'\x1b[B', 'down'), (b'\x1b[C', 'right'),
                  (b'\x1b[D', 'left'), (b'\x1bOA', 'up'), (b'\x1bOB', 'down'),
                  (b'\x1b[5~', 'pgup'), (b'\x1b[6~', 'pgdn'), (b'\x1b[H', 'home'),
                  (b'\x1b[F', 'end'), (b'\x1b[1~', 'home'), (b'\x1b[4~', 'end'),
                  (b'\x1b[3~', 'del'), (b'\x1b[1;5C', 'right'), (b'\x1b', 'esc'),
                  (b'\x1b[Z', 'seq'), (b'\r', 'enter'), (b'\n', 'enter'), (b'\x7f', 'bs'),
                  (b'\x08', 'bs'), (b'\x03', 'ctrl-c'), (b'\x15', 'ctrl-u'), (b'\t', 'tab'),
                  (b'q', 'q'), (b'\xc3', ''), ('\u00e9'.encode('utf-8'), '\u00e9')):
    check(K(raw) == name, 'the key %r was read as %r, not %r' % (raw, K(raw), name))

g = zigmon.console_grep('[1')
check(g('a [1] b') and not g('a 1 b'), 'a broken regular expression was not looked for as '
      'plain words')
g = zigmon.console_grep('ERR|warn')
check(g('x error y') and g('WARN') and not g('info'), 'what is typed is not a case-blind regex')
check(zigmon.console_grep('')('anything'), 'nothing typed hides lines')

keys = [str(n) for n in range(1, 12)]
J = zigmon.console_jump
check(J('1', keys) == (0, False, '1'), 'with eleven items, 1 did not wait for a second digit: %r'
      % (J('1', keys),))
check(J('11', keys) == (10, True, ''), '1 then 1 is not the eleventh: %r' % (J('11', keys),))
check(J('10', keys) == (9, True, ''), '1 then 0 is not the tenth')
check(J('17', keys) == (6, True, ''), '1 then 7 is not the seventh: %r' % (J('17', keys),))
check(J('5', keys) == (4, True, ''), '5 is not chosen at once')
check(J('0', keys) == (None, False, ''), '0 chose something')
check(J('1', keys[:9]) == (0, True, ''), 'with nine items, 1 waits for a second digit')

s = zigmon.console_slice('\x1b[32mabcdef\x1b[0mghij', 2, 5)
check(zigmon.console_plain(s) == 'cdefg' and '\x1b[32m' in s, 'a line scrolled sideways lost '
      'its words or its colours: %r' % s)


class FakeWin(object):
    """What curses hands over for a key, one code at a time."""
    def __init__(self, codes):
        self.codes = list(codes)

    def getch(self):
        return self.codes.pop(0) if self.codes else -1

    def nodelay(self, _on):
        pass

    def getmaxyx(self):
        return (24, 80)


import curses  # noqa: E402
con = zigmon.Console(zigmon.Palette(False))
con.curses = curses
for codes, name in (([27, ord('['), ord('B')], 'down'), ([27, ord('O'), ord('A')], 'up'),
                    ([27, ord('['), ord('5'), ord('~')], 'pgup'),
                    ([27, ord('['), ord('6'), ord('~')], 'pgdn'), ([27], 'esc'),
                    ([curses.KEY_UP], 'up'), ([10], 'enter'), ([ord('x')], 'x')):
    con.scr = FakeWin(codes)
    got = con._getkey()
    check(got == name, 'curses gave %r, read as %r rather than %r' % (codes, got, name))

zigmon.CONSOLE_MORE['main'].append(('Network, time and power', lambda c: None))
zigmon.CONSOLE_MORE['main'].append(('Something else', lambda c: None))
rows = con._numbered([('One', None), ('Two', None)], 'main')
check([r[0] for r in rows] == ['1', '2', '3', '4'] and rows[2][1] == 'Network, time and power',
      'what another part adds to a menu is not numbered on from the console\'s own: %r'
      % [r[:2] for r in rows])
del zigmon.CONSOLE_MORE['main'][:]

# ---- the console itself, on a pseudo-terminal ----------------------------------
cfg = W / 'config.json'
log_file = W / 'zigmon.log'
log_file.write_text(''.join('2026-10-28 10:00:%02d  info  line number %d of the log\n' % (n, n)
                            for n in range(40)) +
                    '2026-10-28 10:01:00  warn  the broker said something odd\n')
cfg.write_text('{"db_file": "%s", "api_port": 19893, "api_host": "127.0.0.1", "mqtt_host": "", '
               '"log_file": "%s"}' % (W / 'h.db', log_file))
shell_seen = W / 'shell-env'
fake_shell = W / 'fake-shell'
fake_shell.write_text('#!/bin/sh\necho "ZIGMON_CONSOLE=$ZIGMON_CONSOLE" > %s\n' % shell_seen)
fake_shell.chmod(0o755)
env = dict(os.environ, ZIGMON_CONFIG=str(cfg), ZIGMON_CONSOLE_START='menu',
           TERM='xterm-256color', LANG='C.UTF-8', LC_ALL='C.UTF-8', SHELL=str(fake_shell),
           ZIGMON_CONSOLE_FLAG=str(W / 'flag4'))
env.pop('NO_COLOR', None)
env.pop('ZIGMON_CONSOLE', None)
text, status = on_pty([sys.executable, str(HERE / 'zigmon.py'), '--console'], env, keys=[
    ('not answering', b'9'),                 # the bar has been asked; The service
    ('console at login', b'\x1b'),           # Esc: back
    ('Main menu', b'!'),                     # a shell, and back from it
    ('Main menu', b'q'),
], timeout=90)
seen = plain(text)
check('Status and checks' in seen and 'The service' in seen and 'Accounts of the dashboard' in seen,
      'the console did not show its main menu: %r' % seen[-600:])
check('The console at login: on or off' in seen, '9 did not open The service')
check('not answering' in seen, 'the bar never said the daemon is not answering')
check(shell_seen.exists() and shell_seen.read_text().strip() == 'ZIGMON_CONSOLE=1',
      '! did not open a shell told it came from the console')
check(status is not None and os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0,
      'q did not close the console cleanly (%r)' % status)
check('The zigmon console is closed' in seen, 'nothing was said on the way out')

env['ZIGMON_CONSOLE_START'] = 'log'
text, status = on_pty([sys.executable, str(HERE / 'zigmon.py'), '--console', '--no-color'], env,
                      keys=[('broker said something odd', b'xyzzy'),
                            ('nothing with "xyzzy"', b'\x1b'),         # Esc clears the filter
                            ('line number 39', b'\x1b'),               # Esc: the menu
                            ('Main menu', b'q')], timeout=90)
seen = plain(text)
check('line number 39 of the log' in seen and 'following' in seen,
      'the console did not open on the live log: %r' % seen[-400:])
check('nothing with "xyzzy" yet' in seen, 'what was typed in the live view did not filter it')
check(status is not None and os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0,
      'the console did not leave the live log for the menu and close (%r): %r'
      % (status, seen[-300:]))

import shutil  # noqa: E402
shutil.rmtree(str(W), ignore_errors=True)
if bad:
    print('\n%d check(s) failed' % len(bad))
    sys.exit(1)
print('the console starts at root\'s login only when it should, its switch follows no link, '
      'and it runs on a terminal')
