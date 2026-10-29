#!/usr/bin/env python3
"""The version must be the same in every place that states it.

They drifted apart once: a release script replaced a version string that was
no longer there, said nothing, and several releases went out carrying an old
number inside a differently named file. Nobody could tell what they were
running. Run this before packaging.
"""
import re
import sys
from pathlib import Path

here = Path(__file__).resolve().parent.parent
found = {}

m = re.search(r"__version__ = '([^']+)'", (here / 'zigmon.py').read_text())
found['zigmon.py'] = m.group(1) if m else None

m = re.search(r'^VERSION="([^"]+)"', (here / 'install.sh').read_text(), re.M)
found['install.sh'] = m.group(1) if m else None

m = re.search(r'Current version: \*\*([^*]+)\*\*', (here / 'README.md').read_text())
found['README.md'] = m.group(1) if m else None

for where, value in found.items():
    print('%-12s %s' % (where, value or '(not stated)'))
if len(set(found.values())) != 1 or None in found.values():
    print('\nthese do not agree')
    sys.exit(1)
print('\nall three agree')


# The help is built from a table of (command, words) pairs, so that a column
# cannot drift. Every command must have words beside it, and every word must
# fit the page.
import re as _re
import sys as _sys
_src = (Path(__file__).resolve().parent.parent / 'zigmon.py').read_text()
_rows = _re.search(r'\nHELP_LINES = \[(.*?)\n\]', _src, _re.S).group(1)
_pairs = _re.findall(r"^\s*\('(.*?)', '(.*?)'\),$", _rows, _re.M)
_bare = [c for c, w in _pairs if not w.strip()]
if _bare:
    print('examples with nothing said about them:')
    for _c in _bare:
        print('   ' + _c)
    raise SystemExit(1)
# The three agreeing is not the same as the three being right. A bump is made
# with sed, and sed says nothing when it matches nothing: a release stamped
# 3.55.5 went out as 3.56.0, and then as 3.56.1, 3.56.2, 3.56.3 and 3.57.0,
# because every one of those bumps looked for the version before it and the
# file had moved on by another route. All three agreed the whole time. What
# was not checked is that the version says the same as the newest thing
# written in the changelog, which is the one place a release is described.
_readme = (here / 'README.md').read_text()
_version = found['zigmon.py']
_top = re.search(r'^(\d+\.\d+\.\d+) \u2014 ', _readme, re.M)
if not _top:
    print('the changelog has no entry to check the version against')
    raise SystemExit(1)
if _top.group(1) != _version:
    print('the version says %s and the newest changelog entry is %s - one of them was not bumped'
          % (_version, _top.group(1)))
    raise SystemExit(1)
# and the entries must run downhill, so an entry put in the wrong place shows
_seen = [tuple(int(x) for x in m.split('.'))
         for m in re.findall(r'^(\d+\.\d+\.\d+) \u2014 ', _readme, re.M)]
_wrong = [('%d.%d.%d' % _seen[i], '%d.%d.%d' % _seen[i + 1])
          for i in range(len(_seen) - 1) if _seen[i] < _seen[i + 1]]
if _wrong:
    print('the changelog is out of order:')
    for _a, _b in _wrong[:5]:
        print('   %s is written above %s' % (_a, _b))
    raise SystemExit(1)
print('the version matches the newest of %d changelog entries, and they run downhill' % len(_seen))
print('%d example(s) in the help, every one of them worded' % len(_pairs))


# An upgrade must do everything a fresh install does that is not about first
# setup. The sudoers line that lets the daemon reload the broker was written
# only on a fresh install, so nobody who upgraded ever got it - the same shape
# of fault as a switch that is saved and never read.
_sh = (Path(__file__).resolve().parent.parent / 'install.sh').read_text()
_fresh = _re.search(r'\nmain\(\) \{(.*?)\n\}', _sh, _re.S).group(1)
_upgrade = _re.search(r'\ndo_upgrade\(\) \{(.*?)\n\}', _sh, _re.S).group(1)
_first_time_only = {'gather_answers', 'install_packages', 'create_user', 'write_config',
                    'create_mqtt_user', 'check_certificate', 'configure_nginx', 'configure_selinux',
                    'configure_firewall', 'summary', 'preflight', 'install_web', 'start_service',
                    'verify'}
_want = [c for c in _re.findall(r'^\s+([a-z_]+)$', _fresh, _re.M) if c not in _first_time_only]
_missing = [c for c in _want if c not in _upgrade]
if _missing:
    print('a fresh install does these and an upgrade does not:')
    for _c in _missing:
        print('   ' + _c)
    raise SystemExit(1)
print('%d step(s) an upgrade must repeat, all of them repeated' % len(_want))


# --secret must work behind every command that has one, and must not die on
# any of them. It once died on `zigmon sms --secret` because the helper it
# used was defined further down the same function than the branch that called
# it - which Python only notices when that branch runs.
_sh = (Path(__file__).resolve().parent.parent / 'zigmon.py').read_text()
_words = _re.findall(r"\n    '(\w+)': \[\n        '  zigmon ", _sh)
_missing = [w for w in _words if ("'%s'" % w) not in _sh.split('SECRET_GROUPS = {')[1].split('}')[0]]
if _missing:
    print('word commands with no secrets of their own:')
    for _w in _missing:
        print('   ' + _w)
    raise SystemExit(1)
print('%d word command(s), each with its own secrets' % len(_words))


# Anything that looks like a secret must be starred out in the ordinary
# output, and only --secret may show it. `--diag` used to star three keys by
# name, so the gateway password, the Telegram token and the controller's key
# were printed in full to whoever ran it.
_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import zigmon as _zz   # noqa: E402
_looks_secret = [k for k in _zz.DEFAULTS if _zz.secret_key(k)]
_zz.SHOW_SECRETS = False
_leaky = [k for k in _looks_secret if _zz.shown_value(k, 'abcdefgh') == 'abcdefgh']
_zz.SHOW_SECRETS = True
_stuck = [k for k in _looks_secret if _zz.shown_value(k, 'abcdefgh') != 'abcdefgh']
_zz.SHOW_SECRETS = False
if _leaky or _stuck:
    if _leaky:
        print('settings printed in the clear without --secret:')
        for _k in _leaky:
            print('   ' + _k)
    if _stuck:
        print('settings still starred out with --secret:')
        for _k in _stuck:
            print('   ' + _k)
    raise SystemExit(1)
print('%d secret setting(s), hidden by default and shown by --secret' % len(_looks_secret))


# A flag nobody can find is a flag nobody uses. Every one that is not a
# shorthand for a word command has to appear in the worded help, where a
# person looks - argparse's own list is long enough to hide in.
_blk = _sh[_sh.index('def build_parser()'):]
_flags = sorted(set(_re.findall(r"add_argument\('(--[a-z-]+)'", _blk[:18000])))
_worded = ' '.join(str(x) for x in _zz.HELP_LINES)
# these are shorthands the word commands cover, or arguments to other flags
_covered = {'--config', '--json', '--no-color', '--pin', '--allow-root', '--number', '--text',
            '--limit', '--range', '--keys', '--points', '--seconds', '--count', '--ms', '--types',
            '--raw', '--version', '--debug', '--bridge', '--force',
            '--sms', '--modem', '--wifi', '--map', '--check-sms', '--wifi-probe',
            '--wifi-order-reset'}
_hidden = [f for f in _flags if f not in _worded and f not in _covered]
if _hidden:
    print('flags a person could not find in the help:')
    for _f in _hidden:
        print('   ' + _f)
    raise SystemExit(1)
print('%d flag(s), every one of them findable' % len(_flags))


# The flags are pictures served from this house, one per country, so a
# country beside an address looks the same on every machine and needs no
# internet. Two hundred and fifty of them, and the licence they come under.
from pathlib import Path as _P
_flags = _P(__file__).resolve().parent.parent / 'web' / 'flags'
_have = sorted(_flags.glob('*.svg')) if _flags.is_dir() else []
if len(_have) < 240:
    print('only %d flag(s) in web/flags; the set is missing' % len(_have))
    raise SystemExit(1)
if not (_flags / 'LICENSE').is_file():
    print('the flags travel without their licence')
    raise SystemExit(1)
for _need in ('cz', 'de', 'us', 'nl', 'gb'):
    if not (_flags / (_need + '.svg')).is_file():
        print('the %s flag is missing' % _need)
        raise SystemExit(1)
print('%d flags travel with the page, under their licence' % len(_have))


# 5.11: --dry-run must not print a secret. It is the mode whose whole promise
# is that it changes nothing and only says what it would do, and people paste
# what it says into bug reports - so it printed the broker password.
import subprocess as _sub

_install = (Path(__file__).resolve().parent.parent / 'install.sh').read_text()
if 'run_quietly()' not in _install:
    print('the installer has no way of running a command without printing its secret')
    raise SystemExit(1)
for _line in _install.splitlines():
    _bare = _line.strip()
    if _bare.startswith('run ') and 'PASSWORD' in _bare:
        print('the installer prints a password in its dry run: %s' % _bare[:70])
        raise SystemExit(1)
# ...and prove it, by running that one step with a stub on the path
_head = _install[:_install.index('ask() {')]
_fn = _install[_install.index('create_mqtt_user() {'):]
_fn = _fn[:_fn.index('\n}\n') + 3]
_tmp = Path('/tmp/zigmon-dryrun-stub')
_tmp.mkdir(exist_ok=True)
(_tmp / 'mosquitto_passwd').write_text('#!/bin/bash\necho ran: "$*"\n')
(_tmp / 'mosquitto_passwd').chmod(0o755)
_secret = 'Br0kerS3cret-ThisMustNotAppear'
_said = _sub.run(['bash', '-c', _head + _fn + '\nDRY_RUN=1\nCREATE_MQTT_USER=1\n'
                  'MQTT_USER=zigmon\nMQTT_PASSWORD="%s"\ncreate_mqtt_user\n' % _secret],
                 capture_output=True, text=True,
                 env={'PATH': '%s:/usr/bin:/bin' % _tmp, 'TERM': 'dumb'})
if _secret in _said.stdout + _said.stderr:
    print('the installer\'s dry run printed the broker password')
    raise SystemExit(1)
if 'would run' not in _said.stdout:
    print('the installer\'s dry run said nothing about what it would do: %r' % _said.stdout[:120])
    raise SystemExit(1)
print('the installer\'s dry run says what it would do without saying the password')

# 5.11: the debug tool asks for everything it prints to be sent back, so it
# must not print a secret either. An own-address setting may carry a key in
# its query string; the daemon strips exactly that before showing the same
# setting, and this tool printed it whole.
import importlib.util as _iu

_spec = _iu.spec_from_file_location(
    '_snort_debug', Path(__file__).resolve().parent.parent / 'tools' / 'snort-debug.py')
_tool = _iu.module_from_spec(_spec)
_spec.loader.exec_module(_tool)
if not hasattr(_tool, 'shown_url'):
    print('the debug tool has no way of showing an address without its query string')
    raise SystemExit(1)
for _url, _never in (
        ('https://snort.org/downloads/ip-block-list?key=SECRET123', 'SECRET123'),
        ('https://user:hunter2@example.org/list.txt', 'hunter2'),
        ('https://example.org/list.txt?token=abc123', 'abc123')):
    _said = _tool.shown_url(_url)
    if _never in _said:
        print('the debug tool prints a secret in an address: %s' % _said)
        raise SystemExit(1)
if _tool.shown_url('file:///var/lib/zigmon/own.txt') != '/var/lib/zigmon/own.txt':
    print('the debug tool no longer shows a file by its path')
    raise SystemExit(1)
# ...and it waits on the ledger the daemon keeps, rather than spending the
# same five-a-minute budget behind its back
_src = (Path(__file__).resolve().parent.parent / 'tools' / 'snort-debug.py').read_text()
if 'snort_asked' not in _src.split('def main(')[1]:
    print('the debug tool does not count its own asking against what the daemon has sent')
    raise SystemExit(1)
print('the debug tool shows an address without its secret, and waits its turn')

# 5.12: the page's own JavaScript must parse. `php -l` reads the PHP and
# never looks inside the <script> block, so a stray comma in a megabyte of
# browser code ships as a page that serves its shell and then nothing at all -
# no tabs, no data, no buttons, for every browser that opens it.
import re as _re
import subprocess as _sub2
import tempfile as _tmp

_page = (Path(__file__).resolve().parent.parent / 'web' / 'index.php').read_text()
_blocks = _re.findall(r'<script>(.*?)</script>', _page, _re.S)
if not _blocks:
    print('the page carries no script at all')
    raise SystemExit(1)
_big = max(_blocks, key=len)
# the PHP holes are filled in when the page is served; stand something
# harmless in them so the rest can be read as the JavaScript it is
_js = _re.sub(r'<\?=.*?\?>', 'null', _big, flags=_re.S)
_js = _re.sub(r'<\?php.*?\?>', '', _js, flags=_re.S)
with _tmp.NamedTemporaryFile('w', suffix='.js', delete=False) as _fh:
    _fh.write(_js)
    _where = _fh.name
try:
    _said = _sub2.run(['node', '--check', _where], capture_output=True, text=True)
except FileNotFoundError:
    print('node is not here, so the page\'s script could not be read')
    raise SystemExit(1)
finally:
    Path(_where).unlink(missing_ok=True)
if _said.returncode != 0:
    print('the page\'s own script does not parse, so the dashboard would be dead:')
    for _line in (_said.stderr or _said.stdout).strip().splitlines()[:6]:
        print('   %s' % _line)
    raise SystemExit(1)
print('the page\'s script parses: %d bytes of it' % len(_js))

# The repository is the package unpacked: a dashboard at the top of it is a
# stray copy (web/index.php is the one installed) and went into every package
_top = Path(__file__).resolve().parent.parent
if (_top / 'index.php').exists():
    print('index.php at the top of the repository is an old copy, not the dashboard: web/index.php is')
    raise SystemExit(1)
if not (_top / 'tools' / 'make-release.sh').exists():
    print('tools/make-release.sh, which makes the signed package, is missing')
    raise SystemExit(1)
print('the repository holds the package\'s files and nothing beside them')
