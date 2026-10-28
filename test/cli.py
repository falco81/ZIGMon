#!/usr/bin/env python3
"""Every command the help offers, actually run.

The other checks read the source: that each flag exists, that the help names
it, that the help offers nothing the program lacks. None of them ever ran one,
which is how `--help` itself once went silent while every check passed - the
file was still valid Python, and nothing tried it.

This starts a daemon on a port of its own, against a database of its own, and
runs every command that only reads. A command that raises, that prints a
traceback, or that cannot reach the daemon is a failure. What a command says
about an empty house - "no rules", "nobody is blocked" - is a fine answer and
is not judged here.
"""

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PORT = 19891

folder = tempfile.mkdtemp(prefix='zigmon-cli-')
config = os.path.join(folder, 'config.json')
json.dump({
    'db_file': os.path.join(folder, 'history.db'),
    'api_port': PORT, 'api_host': '127.0.0.1',
    'mqtt_host': '', 'pin': '1234',
    'log_file': os.path.join(folder, 'zigmon.log'),
    'backup_dir': os.path.join(folder, 'backups'),
}, open(config, 'w'))

env = dict(os.environ, ZIGMON_CONFIG=config, PYTHONPATH=str(HERE))
# Started in-process rather than by running the daemon itself: the daemon
# refuses to start without the MQTT library, which a machine that only runs
# the checks has no reason to have - and what is being checked here is the
# command line, not the broker.
_starter = os.path.join(folder, 'start.py')
open(_starter, 'w').write(
    'import sys, time\n'
    'sys.path.insert(0, %r)\n'
    "sys.argv = ['zigmon']\n"
    'import zigmon\n'
    'zigmon.load_config()\n'
    'd = zigmon.Daemon()\n'
    'srv = zigmon.ApiServer(d)\n'
    'srv.start()\n'
    'while True:\n'
    '    time.sleep(1)\n' % str(HERE))
_out = open(os.path.join(folder, 'start.log'), 'w')
daemon = subprocess.Popen([sys.executable, _starter],
                          env=env, stdout=_out, stderr=subprocess.STDOUT)


def stop():
    try:
        daemon.send_signal(signal.SIGTERM)
        daemon.wait(timeout=10)
    except Exception:
        daemon.kill()


ready = False
for _ in range(60):
    time.sleep(0.5)
    try:
        import urllib.request
        urllib.request.urlopen('http://127.0.0.1:%d/api/health' % PORT, timeout=2)
        ready = True
        break
    except Exception:
        if daemon.poll() is not None:
            break
if not ready:
    stop()
    _out.close()
    print('the daemon would not start, so no command could be run:')
    print(open(os.path.join(folder, 'start.log')).read()[-800:])
    raise SystemExit(1)

# Every command in the help that only reads. The ones that switch something,
# erase something or talk to hardware that is not here are left out: this asks
# whether a command runs, not whether a house answers.
READS = [
    ['--status'], ['--devices'], ['--events', '--limit', '5'], ['--battery'],
    ['--heating'], ['--people'], ['--presence'], ['--weather'], ['--scenes'],
    ['--scripts'], ['--sessions'], ['--alerts'], ['--bindings'], ['--rules'],
    ['--targets'], ['--taps'], ['--presses'], ['--blocked'], ['--blocked', 'mikrotik'],
    ['--backup'], ['--proxy'], ['--diag'], ['--check'], ['--settings'],
    ['--settings', 'block'], ['--tell', 'house'], ['--monthly'], ['--sms'],
    ['--wifi'], ['--wifi-probe'], ['--acl', 'check'], ['--check-sms'],
    ['--mikrotik', 'show'], ['--what-if', 'Nothing', 'temperature', '20'],
    ['--run-script', 'no-such-script'], ['--diagnose', 'no-such-plug'],
    ['--status', '--json'], ['--devices', '--json'], ['--alerts', '--json'],
    ['--console-at-login', 'status'],
]

bad = []
for argv in READS:
    out = subprocess.run([sys.executable, str(HERE / 'zigmon.py')] + argv + ['--no-color'],
                         env=env, capture_output=True, text=True, timeout=60,
                         stdin=subprocess.DEVNULL)
    said = (out.stdout or '') + (out.stderr or '')
    name = 'zigmon ' + ' '.join(argv)
    if re.search(r'Traceback|NameError|TypeError|AttributeError|KeyError|is not defined', said):
        bad.append((name, [l for l in said.splitlines() if 'Error' in l][-1:] or ['raised']))
    elif 'not reachable' in said or 'Connection refused' in said:
        bad.append((name, ['could not reach the daemon it had just been given']))
    elif out.returncode not in (0, 1, 2):
        bad.append((name, ['exit %d' % out.returncode]))

# ...and the help itself, which is the one that went silent
out = subprocess.run([sys.executable, str(HERE / 'zigmon.py'), '--help'],
                     env=env, capture_output=True, text=True, timeout=30)
if len(out.stdout) < 2000:
    bad.append(('zigmon --help', ['printed %d characters' % len(out.stdout)]))
for heading in ('Looking at the house', 'Who may talk to it', 'Keeping it well'):
    if heading not in out.stdout:
        bad.append(('zigmon --help', ['no heading "%s"' % heading]))

stop()

# The ntfy tool beside it: it reads what ntfy prints, and ntfy's output is the
# only thing holding those two together. A change in either and the tool shows
# an empty list rather than an error, which is the worst way to be wrong.
import importlib.util as _iu
_spec = _iu.spec_from_file_location('ntfy_admin', str(HERE / 'tools' / 'ntfy-admin.py'))
_admin = _iu.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_admin)
except Exception as _e:
    bad.append(('tools/ntfy-admin.py', ['will not even load: %s' % _e]))
else:
    _fake = os.path.join(folder, 'ntfy')
    open(_fake, 'w').write(
        '#!/bin/bash\n'
        'case "$1 $2" in\n'
        '  "access ") printf "user falco (role: user, tier: none)\\n'
        '- read-only access to topic zigmon-*\\n'
        'user admin (role: admin, tier: none)\\n'
        '- read-write access to all topics (admin role)\\n" ;;\n'
        '  "token list") printf -- "user falco\\n'
        '- tk_abc123 (my phone), never expires\\n" ;;\n'
        '  *) echo "ran: $*" ;;\n'
        'esac\n')
    os.chmod(_fake, 0o755)
    _admin.NTFY = _fake
    _people, _err = _admin.users()
    if len(_people) != 2:
        bad.append(('tools/ntfy-admin.py', ['read %d users out of two' % len(_people)]))
    elif _people[0]['name'] != 'falco' or _people[1]['role'] != 'admin':
        bad.append(('tools/ntfy-admin.py', ['read the users wrongly: %r' % _people]))
    elif not _people[0]['grants']:
        bad.append(('tools/ntfy-admin.py', ['read no grants at all']))
    # Every key a terminal sends, judged without one. An arrow is three bytes
    # and the whole of it arrives at once; read through a buffered text stream
    # the escape came out alone and every arrow closed the screen it was
    # pressed on.
    for _raw, _want in ((b'\x1b[A', 'up'), (b'\x1b[B', 'down'), (b'\x1bOA', 'up'),
                        (b'\x1bOB', 'down'), (b'\x1b[C', 'right'), (b'\x1b[D', 'left'),
                        (b'\x1b[H', 'home'), (b'\x1b[F', 'end'), (b'\r', 'enter'),
                        (b'\n', 'enter'), (b'\x1b', 'esc'), (b'q', 'q'), (b'a', 'a'),
                        (b'\x7f', 'back'), (b'\x1b[5~', 'up'), (b'\x1b[6~', 'down')):
        _got = _admin.read_key_bytes(_raw)
        if _got != _want:
            bad.append(('tools/ntfy-admin.py', ['%r reads as %s, not %s' % (_raw, _got, _want)]))
    # and nothing waits on input(), which cannot be given up on with Esc and
    # swallows a keypress left over from the screen before - which is how the
    # log flashed past before anybody could read a word of it
    _source = (HERE / 'tools' / 'ntfy-admin.py').read_text()
    if re.search(r'^\s*(try:\s*)?input\(', _source, re.M):
        bad.append(('tools/ntfy-admin.py', ['something still waits on input()']))
    _held, _ = _admin.tokens('falco')
    # --proxy has to name every log it is set to read, or a house that has
    # switched one on has no way to see whether it is being read at all
    _cli = (HERE / 'zigmon.py').read_text()
    for _line, _why in (("'  the full log", 'the full log'),
                        ("'  ntfy in full", "the notification server's full log"),
                        ("ntfy\\'s own    ", "ntfy's own log"),
                        ("'  suricata     ", "Suricata's eve.json"),
                        ("'  its ban feed", 'the ban feed')):
        if _line not in _cli:
            bad.append(('zigmon --proxy', ['it never names %s' % _why]))
    if len(_held) != 1 or _held[0]['label'] != 'my phone':
        bad.append(('tools/ntfy-admin.py', ['read the tokens wrongly: %r' % _held]))

if bad:
    print('%d command(s) did not run:' % len(bad))
    for name, why in bad:
        print('   %-38s %s' % (name, why[0][:70]))
    raise SystemExit(1)
print('%d commands run, the help prints %d characters in its sections, and the ntfy tool '
      'reads what ntfy prints' % (len(READS), len(out.stdout)))


# -- 5.13: what the check makes of a socket that is deliberately unplugged ------
# The house has one optional socket pulled out of the wall. The daemon says so
# itself - "treated as unplugged (optional device)" - and leaves its level
# alone, but the check called it a failure, so every upgrade ended with "the
# check reported problems" and a non-zero exit over a socket nobody was
# worried about. And the wait for the first poll tested `online`, which is
# true from the moment the daemon starts, because the reading stored before
# the restart stands in until a fresh one lands - so it never waited, and
# seven sockets were reported as "not polled yet".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import zigmon as _z                                                   # noqa: E402

if not hasattr(_z, 'plug_check_line'):
    print('the check has no mind of its own about a socket that is not answering')
    raise SystemExit(1)
_cases = [
    ({'online': True, 'stale': False, 'error': None, 'unplugged': False}, 'ok'),
    ({'online': True, 'stale': True, 'error': 'waiting for the first reading',
      'unplugged': False}, 'first'),
    ({'online': False, 'stale': True, 'error': 'cannot reach plug X at 1.2.3.4 (timed out)',
      'unplugged': True, 'optional': True}, 'unplugged'),
    ({'online': False, 'stale': True, 'error': 'cannot reach plug Y at 1.2.3.5 (timed out)',
      'unplugged': False, 'optional': False}, 'bad'),
]
_wrong = [(snap, want, _z.plug_check_line(snap)) for snap, want in _cases
          if _z.plug_check_line(snap) != want]
if _wrong:
    print('the check reads a socket wrongly:')
    for snap, want, got in _wrong:
        print('   wanted %-10s got %-10s for %r' % (want, got, snap))
    raise SystemExit(1)
_src = __import__('inspect').getsource(_z.cmd_check)
if 'plug_check_line' not in _src:
    print('the check does not use what it was told about a socket')
    raise SystemExit(1)
if "not snap['online'] and snap['error'] == 'waiting for the first reading'" in _src:
    print('the wait for the first poll still tests online, so it never waits')
    raise SystemExit(1)
print('the check counts a deliberately unplugged optional socket as no fault, and waits '
      'for the first poll on the one thing that says so')
