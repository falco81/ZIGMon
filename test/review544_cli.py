#!/usr/bin/env python3
"""5.44: a release that must be put in on the command line, and the notices
for an administrator it is the first user of.

  * tools/make-release.sh KEY --needs-cli "why" (a test key, a stand-in git,
    a copy of the folder - never the real release key, never a real
    release): release.json in the package, listed in MANIFEST so the
    signature covers it, and beside the package with a signature of its own;
    without the flag no release.json, as before;
  * root (deploy/zigmon_upgrade.py): such a package is checked as any other,
    says so (cli.needed, why), and an upgrade asked from the dashboard is
    refused with that message, nothing changed; the flag stripped, changed or
    not signed is refused like any tampered package; a package without it,
    and the old releases in release/, behave as before; a higher SYSTEM_LEVEL
    than the machine's stamp needs the command line too; only_from_below;
  * install.sh: cli_gate stops a run from the dashboard before anything is
    changed and lets the command line go on; write_system_stamp records the
    system level and the hash of each part root installs;
  * the daemon: notice_raise / notice_clear / notice_hide (idempotent, told
    once, a crit never hidden, a hidden one back when what it is about
    changes); /api/status carries them for an administrator and root's
    command line only; a package that needs the command line is not ready
    and not started; a version found on the web with a signed release.json
    beside it is marked; the notices 'upgrade-cli' and 'root-parts' (zigmon X
    is running, but the parts root installs are from before it) raised and
    cleared by themselves;
  * the console, zigmon --status, --notices, --upgrade-check and
    --upgrade-online say it;
  * the page (php -S + Chromium): the card "To be done by hand" always first
    in Settings - Upgrades (upsmon's look: a band per item - icon, title,
    words, the command in a mono box with Copy, the hint, the time, Look
    again and Done; Done lately under them; a green strip when nothing is
    pending), a crit item in its own pane, a badge on the pane's button in
    the rail, an item in Needs attention leading to the pane - for an
    administrator only, and no band outside Settings; From the web: the band,
    Upgrade disabled, the dropdown's "(command line)"; a package sent: the
    band instead of Upgrade; going back: the band, Go back disabled.

Every check fails on 5.43.4. Ports 19460-19469 only.

    python3 test/review544_cli.py

Screenshots in $ZIGMON_SHOTS (default the scratchpad's cli-shots/).
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
HELPER = HERE / 'deploy' / 'zigmon_upgrade.py'
W = Path(tempfile.mkdtemp(prefix='zigmon-review544-'))
SHOTS = Path(os.environ.get('ZIGMON_SHOTS') or
             '/tmp/claude-0/-home-user-ZIGMon/65a687e3-67ca-5ac1-bf11-9a8cad22f228/scratchpad/cli-shots')
PHP_PORT, API_PORT = 19460, 19461
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


# ---- the machine: zigmon 5.17.0, a release key of the test's own ------------------
LIB, WEB, KEYS = W / 'lib' / 'zigmon', W / 'www' / 'zigmon', W / 'keys'
STATE, UNITS, ETC = W / 'state', W / 'units', W / 'etc'
for d in (LIB, KEYS, WEB, STATE / 'upgrade', UNITS, ETC):
    d.mkdir(parents=True)
STAMP = ETC / 'zigmon-system.json'
OLD_PY = "#!/usr/bin/python3\n__version__ = '5.17.0'\n"
(LIB / 'zigmon.py').write_text(OLD_PY)
(WEB / 'index.php').write_text('<?php // the old page\n')
key, stranger = W / 'release.key', W / 'stranger.key'
for k in (key, stranger):
    sh(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', str(k)])
sh(['openssl', 'pkey', '-in', str(key), '-pubout', '-out', str(KEYS / 'zigmon-release-test.pub')])
ENV = dict(os.environ, ZIGMON_STATE=str(STATE), ZIGMON_LIB=str(LIB), ZIGMON_WEB=str(WEB),
           ZIGMON_RELEASE_KEYS=str(KEYS), ZIGMON_ROOT_OWN=str(W / 'own'), ZIGMON_UNITS=str(UNITS),
           ZIGMON_NO_SERVICES='1', ZIGMON_HEALTH_WAIT_S='1', ZIGMON_UPGRADE_TEST='1', ZIGMON_USER='root',
           ZIGMON_CONFIG=str(W / 'config.json'), ZIGMON_SYSTEM_STAMP=str(STAMP))
WHY = 'PHP moves to 8.4 and php-fpm has to be watched while it does'


def package(version, notes=None, level=None, name=None, tamper=None, strip=False, unsigned=False):
    """A release folder signed with the test key: zigmon.py of `version` (with
    SYSTEM_LEVEL when given), the helper of this checkout, an install.sh that
    puts zigmon.py in, and release.json when `notes` is given."""
    top = 'zigmon-%s' % version
    d = W / 'build' / (name or top) / top
    if d.parent.exists():
        shutil.rmtree(d.parent)
    (d / 'deploy').mkdir(parents=True)
    (d / 'zigmon.py').write_text("#!/usr/bin/python3\n__version__ = '%s'\n%s" % (
        version, ('SYSTEM_LEVEL = %d\n' % level) if level is not None else ''))
    (d / 'README.md').write_text('%s — a test release.\n' % version)
    (d / 'install.sh').write_text('#!/bin/bash\nset -e\ncd "$(dirname "$0")"\ninstall -m 755 zigmon.py %s/zigmon.py\n' % LIB)
    shutil.copy(HELPER, d / 'deploy' / 'zigmon_upgrade.py')
    if notes is not None:
        (d / 'release.json').write_text(json.dumps(notes))
    lines = ['%s  %s' % (hashlib.sha256(p.read_bytes()).hexdigest(), p.relative_to(d).as_posix())
             for p in sorted(x for x in d.rglob('*') if x.is_file())]
    (d / 'MANIFEST').write_text('\n'.join(lines) + '\n')
    if not unsigned:
        sh(['openssl', 'pkeyutl', '-sign', '-inkey', str(key), '-rawin', '-in', str(d / 'MANIFEST'),
            '-out', str(d / 'MANIFEST.sig')])
    if tamper:
        (d / 'release.json').write_text(json.dumps(tamper))
    if strip:
        (d / 'release.json').unlink()
    out = W / 'build' / ('%s.tar.gz' % (name or top))
    with tarfile.open(out, 'w:gz') as t:
        t.add(d, arcname=top)
    return out


def inspect(path, env=None):
    got = sh([sys.executable, '-I', str(HELPER), '--inspect', str(path)], env=env or ENV)
    try:
        return json.loads(got.stdout or '{}')
    except ValueError:
        return {'said': got.stdout + got.stderr}


# ==== 1. tools/make-release.sh --needs-cli ===========================================
print('make-release.sh --needs-cli (a copy, a test key, a stand-in git)')
R = W / 'repo'
for rel in ('zigmon.py', 'install.sh', 'README.md', 'tools/snort-debug.py', 'tools/make-release.sh',
            'deploy/zigmon_upgrade.py'):
    (R / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(HERE / rel, R / rel)
(R / 'deploy' / 'release-keys').mkdir()
shutil.copy(KEYS / 'zigmon-release-test.pub', R / 'deploy' / 'release-keys' / 'zigmon-release-test.pub')
GITBIN = W / 'gitbin'
GITBIN.mkdir()
(GITBIN / 'git').write_text('#!/bin/bash\n# a stand-in: the files there are, and nothing uncommitted\n'
                            'case "$1" in\n  ls-files) find . -type f ! -path "./release/*" -printf "%P\\n" | LC_ALL=C sort ;;\n'
                            '  status) : ;;\n  *) exit 0 ;;\nesac\n')
(GITBIN / 'git').chmod(0o755)
MR_ENV = dict(ENV, PATH='%s:%s' % (GITBIN, os.environ.get('PATH', '')))
V = sh([sys.executable, '-c', 'import re,sys;print(re.search(r"^__version__ = \'(.*)\'", open(sys.argv[1]).read(), re.M).group(1))',
        str(HERE / 'zigmon.py')]).stdout.strip()
got = sh(['bash', str(R / 'tools' / 'make-release.sh'), str(key), '--needs-cli', WHY], cwd=str(R), env=MR_ENV,
         timeout=300)
pkgfile = R / 'release' / ('zigmon-%s.tar.gz' % V)
check(got.returncode == 0 and pkgfile.is_file(), 'make-release.sh --needs-cli did not make the package: %s'
      % (got.stdout + got.stderr)[-500:])
names, man, notes_in = [], '', None
if pkgfile.is_file():
    with tarfile.open(pkgfile) as t:
        names = t.getnames()
        if 'zigmon-%s/MANIFEST' % V in names:
            man = t.extractfile('zigmon-%s/MANIFEST' % V).read().decode()
        if 'zigmon-%s/release.json' % V in names:
            notes_in = json.loads(t.extractfile('zigmon-%s/release.json' % V).read())
check(notes_in and notes_in.get('needs_cli') is True and notes_in.get('why') == WHY
      and notes_in.get('command') == 'sudo ./install.sh --upgrade' and notes_in.get('version') == V,
      'release.json in the package is %r' % notes_in)
check('  release.json\n' in man, 'release.json is not listed in MANIFEST, so the signature does not cover it')
side, side_sig = R / 'release' / ('zigmon-%s.release.json' % V), R / 'release' / ('zigmon-%s.release.json.sig' % V)
check(side.is_file() and side_sig.is_file() and sh(
    ['openssl', 'pkeyutl', '-verify', '-pubin', '-inkey', str(KEYS / 'zigmon-release-test.pub'), '-rawin',
     '-in', str(side), '-sigfile', str(side_sig)]).returncode == 0,
      'the notes beside the package are missing or not signed')
check((R / 'release.json').is_file(), 'release.json is not at the top of the folder as well')
got = inspect(pkgfile) if pkgfile.is_file() else {}
check((got.get('cli') or {}).get('needed') is True and WHY in (got.get('cli') or {}).get('why', ''),
      'root does not see that the package needs the command line: %r' % got.get('cli'))
# and without the flag: as before
if pkgfile.is_file():
    pkgfile.unlink()
got2 = sh(['bash', str(R / 'tools' / 'make-release.sh'), str(key)], cwd=str(R), env=MR_ENV, timeout=300)
names2 = []
if pkgfile.is_file():
    with tarfile.open(pkgfile) as t:
        names2 = t.getnames()
check(got2.returncode == 0 and names2 and 'zigmon-%s/release.json' % V not in names2
      and not (R / 'release.json').exists(),
      'without --needs-cli the package has a release.json, or was not made: %s' % (got2.stdout + got2.stderr)[-300:])
got = inspect(pkgfile) if pkgfile.is_file() else {}
check(got.get('ok') and got.get('cli', {}).get('needed') is False and got.get('release') is None,
      'a package without the flag does not go in as before: %r' % got)

# ==== 2. root ======================================================================
print('root: checked, refused from the dashboard, the flag cannot be stripped')
NOTES = {'format': 1, 'version': '5.18.0', 'needs_cli': True, 'why': WHY, 'command': 'sudo ./install.sh --upgrade'}
cli_pkg = package('5.18.0', NOTES, name='cli')
got = inspect(cli_pkg)
check(got.get('ok') and (got.get('cli') or {}).get('needed') is True and (got.get('release') or {}).get('why') == WHY,
      'a package that needs the command line does not say so: %r' % got)
plain = inspect(package('5.18.0', name='plain'))
check(plain.get('ok') and plain.get('cli', {}).get('needed') is False, 'a plain package says it needs the command line: %r' % plain)
for what, kw, words in (('stripped', {'strip': True}, 'missing: release.json'),
                        ('changed to say no', {'tamper': dict(NOTES, needs_cli=False)}, 'release.json is not the file that was signed'),
                        ('not signed', {'unsigned': True}, 'not signed')):
    g = inspect(package('5.18.0', NOTES, name='t-' + what.replace(' ', '-'), **kw))
    check(g.get('ok') is False and words in (g.get('said') or ''), 'a package whose release.json was %s was not refused: %r'
          % (what, g))
# the old releases in release/ still check, against the real public keys
for old in ('5.19.2', '5.43.4'):
    p = HERE / 'release' / ('zigmon-%s.tar.gz' % old)
    if p.is_file():
        g = inspect(p, dict(ENV, ZIGMON_RELEASE_KEYS=str(HERE / 'deploy' / 'release-keys')))
        check(g.get('ok') and g.get('version') == old and g.get('cli', {}).get('needed') is False,
              'release/zigmon-%s.tar.gz does not check as before: %r' % (old, {k: g.get(k) for k in ('ok', 'said', 'cli')}))
# the system level: higher than the stamp's needs the command line
g = inspect(package('5.18.0', None, level=2, name='level2'))
check(g.get('cli', {}).get('needed') is True and 'level 1' in g['cli'].get('why', ''),
      'a package at system level 2 on a machine at 1 goes in from the dashboard: %r' % g.get('cli'))
STAMP.write_text(json.dumps({'system_level': 2, 'version': '5.17.0'}))
g = inspect(package('5.18.0', None, level=2, name='level2b'))
check(g.get('cli', {}).get('needed') is False, 'a package at the stamp\'s level needs the command line: %r' % g.get('cli'))
STAMP.unlink()
g = inspect(package('5.18.0', dict(NOTES, only_from_below='5.17.0'), name='below-a'))
check(g.get('cli', {}).get('needed') is False, 'only_from_below 5.17.0 asks 5.17.0 for the command line')
g = inspect(package('5.18.0', dict(NOTES, only_from_below='5.18.0'), name='below-b'))
check(g.get('cli', {}).get('needed') is True, 'only_from_below 5.18.0 does not ask 5.17.0 for the command line')

# the dashboard's request: refused with the words, nothing changed
shutil.copy(cli_pkg, STATE / 'upgrade' / 'zigmon-5.18.0.tar.gz')
(STATE / 'upgrade' / 'request.json').write_text(json.dumps(
    {'id': 'c1', 'file': 'zigmon-5.18.0.tar.gz', 'version': '5.18.0',
     'sha': hashlib.sha256(cli_pkg.read_bytes()).hexdigest(), 'by': 'admin'}))
sh([sys.executable, '-I', str(HELPER)], env=ENV)
try:
    st = json.loads((STATE / 'upgrade' / 'status.json').read_text())
except (OSError, ValueError):
    st = {}
check(st.get('state') == 'failed' and 'must be put in from the command line' in st.get('said', '')
      and WHY in st.get('said', '') and 'install.sh --upgrade' in st.get('said', ''),
      'root did not refuse the dashboard\'s upgrade with the message: %r' % st)
check((LIB / 'zigmon.py').read_text() == OLD_PY, 'a refused package changed the program')
got = sh([sys.executable, '-I', str(HELPER), '--run', str(cli_pkg)], env=ENV)
check(got.returncode != 0 and 'command line' in got.stdout, 'zigmon_upgrade.py --run put it in: %s' % got.stdout[-200:])

# ==== 3. install.sh ===============================================================
print('install.sh: stops a run from the dashboard, goes on on the command line')
INSTALL = (HERE / 'install.sh').read_text()
unpacked = W / 'unpacked'
with tarfile.open(cli_pkg) as t:
    t.extractall(unpacked, **({'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}))


def fn(name):
    if (name + '() {') not in INSTALL:
        return ''
    body = INSTALL[INSTALL.index(name + '() {'):]
    return body[:body.index('\n}\n') + 3]


head = INSTALL[:INSTALL.index('ask() {')]
src = unpacked / 'zigmon-5.18.0'
script = head + fn('cli_gate') + fn('write_system_stamp') + (
    '\nSOURCE_DIR=%s\nLIB_DIR=%s\nSYSTEM_STAMP=%s\nUNIT_FILE=%s\nLOGROTATE_FILE=%s\n'
    'cli_gate\necho GATE-PASSED\n' % (src, LIB, STAMP, UNITS / 'zigmon.service', ETC / 'logrotate'))
benv = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'TERM': 'dumb', 'ZIGMON_SYSTEM_STAMP': str(STAMP)}
web = sh(['bash', '-c', script], env=dict(benv, ZIGMON_UPGRADE_FROM_PAGES='1'))
check(web.returncode != 0 and 'GATE-PASSED' not in web.stdout and 'refused from the dashboard' in web.stderr
      and WHY in web.stderr, 'install.sh from the dashboard went on: %r' % (web.stdout + web.stderr)[-300:])
cli = sh(['bash', '-c', script], env=benv)
check(cli.returncode == 0 and 'GATE-PASSED' in cli.stdout and 'this is the command line' in cli.stdout,
      'install.sh --upgrade on the command line did not go on: %r' % (cli.stdout + cli.stderr)[-300:])
(UNITS / 'zigmon.service').write_text('[Service]\nExecStart=x\n')
dry = sh(['bash', '-c', script.replace('cli_gate\necho GATE-PASSED\n', 'DRY_RUN=1\nwrite_system_stamp\n')], env=benv)
check('[would write]' in dry.stdout and not STAMP.exists(), 'the dry run wrote the stamp: %r' % dry.stdout)
wr = sh(['bash', '-c', script.replace('cli_gate\necho GATE-PASSED\n', 'write_system_stamp\n')], env=benv)
try:
    stamp = json.loads(STAMP.read_text())
except (OSError, ValueError):
    stamp = {}
check(stamp.get('system_level') == 1 and stamp.get('version') == V and stamp.get('by') == 'the command line'
      and stamp.get('parts', {}).get(str(UNITS / 'zigmon.service')) ==
      hashlib.sha256((UNITS / 'zigmon.service').read_bytes()).hexdigest(),
      'install.sh wrote no stamp of the system level and root\'s parts: %r %r' % (stamp, wr.stdout[-200:]))
STAMP.unlink(missing_ok=True)
check('cli_gate                 # 5.44: before anything is changed\n    preflight' in INSTALL,
      'do_upgrade does not ask cli_gate before anything else')

# ==== 4. the daemon ==============================================================
print('the daemon: the notices, the package, the web, root\'s parts')
DB = STATE / 'history.db'
(ETC / 'config.json').write_text(json.dumps({'db_file': str(DB)}))
os.environ.update(ENV)
os.environ.update(ZIGMON_CONFIG=str(ETC / 'config.json'), ZIGMON_FS_ROOT='', ZIGMON_ROOT_RUN='true',
                  ZIGMON_UPGRADE_RUN='true', ZIGMON_ROOT_PARTS_EVERY_S='0', ZIGMON_ROOT_PARTS_SETTLE_S='0')
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

admin_body = viewer_body = None
cli_status = {}
try:
    zigmon.load_config()
    zigmon.CONFIG.update({'db_file': str(DB), 'token_file': str(W / 'token'), 'plugs': [], 'sensors': [],
                          'mqtt_host': '', 'log_file': '', 'state_dir': str(STATE), 'api_port': API_PORT,
                          'upgrade_url': 'https://example.test/rel/', 'upgrade_check': 0})
    d = zigmon.Daemon()
    told = []
    d.notify = lambda message, level='info', **kw: told.append((message, level, kw.get('about')))
    # -- the registry
    check(d.notice_raise('t-one', 'warn', 'A test', 'Because.', command='true', link='#control/sys-upgrade', stamp='a'),
          'a new notice is not new')
    check(not d.notice_raise('t-one', 'warn', 'A test', 'Because.', command='true', link='#control/sys-upgrade', stamp='a'),
          'the same notice raised again is new again')
    check([t for t in told if t[2] == 'notice'] and len([t for t in told if t[2] == 'notice']) == 1,
          'a notice is not told once through the alerts (kind notice): %r' % told)
    check(any(k[0] == 'notice' for k in zigmon.Daemon.SYSTEM_ALERTS), 'there is no alert kind for the notices')
    d.notice_hide('t-one', 24, 'admin')
    check([n for n in d.notices_view() if n['key'] == 't-one'][0]['hidden'], 'notice_hide did not hide it')
    d.notice_raise('t-one', 'warn', 'A test', 'Because, again.', command='true', link='#control/sys-upgrade', stamp='a')
    check([n for n in d.notices_view() if n['key'] == 't-one'][0]['hidden'], 'new words for the same thing showed it again')
    d.notice_raise('t-one', 'warn', 'A test', 'Because.', command='true', link='#control/sys-upgrade', stamp='b')
    check(not [n for n in d.notices_view() if n['key'] == 't-one'][0]['hidden'],
          'a hidden notice did not come back when what it is about changed')
    d.notice_raise('t-crit', 'crit', 'A problem', 'Bad.')
    try:
        d.notice_hide('t-crit', 24)
        check(False, 'a crit notice was hidden')
    except ValueError:
        pass
    d.notice_clear('t-one')
    d.notice_done('t-crit', 'boss')
    check(not d.notices_view(), 'notice_clear left %r' % d.notices_view())
    dl = d.notices_done_view()
    check(dl[:2] and dl[0]['key'] == 't-crit' and dl[0]['how'] == 'done' and dl[0]['who'] == 'boss'
          and dl[1]['key'] == 't-one' and dl[1]['how'] == 'went by itself',
          'done lately does not say what was done by hand and what went by itself: %r' % dl[:2])
    # -- a package that needs the command line, sent to the dashboard
    shutil.copy(cli_pkg, STATE / 'upgrade' / '.upload-x.part')
    try:
        pkg = d.upgrade_take(STATE / 'upgrade' / '.upload-x.part', 'admin')
    except ValueError as e:
        pkg = {'error': str(e)}
    st = d.upgrade_state()
    check((pkg.get('release') or {}).get('needs_cli') is True, 'package.json does not keep release.json: %r' % pkg)
    check(st.get('cli') and st['cli'].get('needed') and not st.get('ready')
          and 'tar xzf' in st['cli'].get('command', '') and 'install.sh --upgrade' in st['cli']['command'],
          'the waiting package is ready from the dashboard, or says no command: %r' % st.get('cli'))
    try:
        d.upgrade_start('admin')
        check(False, 'the dashboard started an upgrade to a version that needs the command line')
    except ValueError as e:
        check('must be put in from the command line' in str(e), 'refused with the wrong words: %s' % e)
    d.notices_tick()
    n = {x['key']: x for x in d.notices_view()}
    check('upgrade-cli' in n and n['upgrade-cli']['link'] == '#control/sys-upgrade'
          and 'install.sh --upgrade' in n['upgrade-cli']['command'],
          'no notice says the waiting package needs the command line: %r' % n.get('upgrade-cli'))
    d.upgrade_forget()
    d.notices_tick()
    check('upgrade-cli' not in {x['key'] for x in d.notices_view()}, 'the notice stayed after the package was forgotten')
    # -- found on the web: the notes beside it, signed
    notes44 = json.dumps({'format': 1, 'version': '9.1.0', 'needs_cli': True, 'why': WHY}).encode()
    nf = W / 'n44.json'
    nf.write_bytes(notes44)
    for k, out in ((key, W / 'n44.sig'), (stranger, W / 'n45.sig')):
        sh(['openssl', 'pkeyutl', '-sign', '-inkey', str(k), '-rawin', '-in', str(nf), '-out', str(out)])
    PAGES = {'https://example.test/rel/': (
        '<a href="zigmon-9.2.0.tar.gz">x</a><a href="zigmon-9.2.0.release.json">x</a>'
        '<a href="zigmon-9.2.0.release.json.sig">x</a><a href="zigmon-9.1.0.tar.gz">x</a>'
        '<a href="zigmon-9.1.0.release.json">x</a><a href="zigmon-9.1.0.release.json.sig">x</a>'
        '<a href="zigmon-9.0.9.tar.gz">x</a>').encode(),
        'https://example.test/rel/zigmon-9.1.0.release.json': notes44,
        'https://example.test/rel/zigmon-9.1.0.release.json.sig': (W / 'n44.sig').read_bytes(),
        'https://example.test/rel/zigmon-9.2.0.release.json': notes44.replace(b"9.1.0", b"9.2.0"),
        'https://example.test/rel/zigmon-9.2.0.release.json.sig': (W / 'n45.sig').read_bytes()}

    def fake_get(url, limit=0, accept='', timeout=0, into=None):
        if url not in PAGES:
            raise ValueError('404 %s' % url)
        return PAGES[url], 'text/html', url
    zigmon._online_get = fake_get
    row = d.online_look('admin')
    nl = {x['version']: x for x in d.online_view()['online'].get('newer_list') or []}
    check(set(nl) == {'9.2.0', '9.1.0', '9.0.9'}, 'the versions found are %r (%s)' % (sorted(nl), row.get('error')))
    check((nl.get('9.1.0') or {}).get('cli') and WHY in nl['9.1.0']['cli']['why']
          and 'curl -fLO' in nl['9.1.0']['cli']['command'],
          'a version with signed notes needing the command line is not marked: %r' % nl.get('9.1.0'))
    check(not (nl.get('9.2.0') or {}).get('cli') and not (nl.get('9.0.9') or {}).get('cli'),
          'notes signed by a stranger, or none, were believed: %r' % nl)
    n = {x['key']: x for x in d.notices_view()}
    check('upgrade-cli' in n and '9.1.0' in n['upgrade-cli']['why'], 'the look raised no notice: %r' % n.get('upgrade-cli'))
    # -- the parts root installs
    os.environ['ZIGMON_ROOT_PARTS_CHECK'] = '1'
    part = UNITS / 'zigmon-upgrade.path'
    part.write_text('[Path]\n')
    STAMP.write_text(json.dumps({'system_level': 1, 'version': '5.40.0', 'by': 'the dashboard',
                                 'parts': {str(part): hashlib.sha256(part.read_bytes()).hexdigest()}}))
    d.notices_tick()
    n = {x['key']: x for x in d.notices_view()}
    rp = n.get('root-parts') or {}
    check(rp.get('title') == 'zigmon %s is running, but the parts root installs are from before it' % zigmon.__version__
          and 'zigmon 5.40.0' in rp.get('why', '') and rp.get('command') == './install.sh --upgrade'
          and 'unpacked in' in rp.get('action', '') and 'goes by itself' in rp.get('foot', '')
          and rp.get('link') == '#control/sys-upgrade', 'root\'s parts from before it are not said: %r' % rp)
    STAMP.write_text(json.dumps({'system_level': 1, 'version': zigmon.__version__,
                                 'parts': {str(part): hashlib.sha256(part.read_bytes()).hexdigest()}}))
    d.notices_tick()
    check('root-parts' not in {x['key'] for x in d.notices_view()}, 'the band did not go by itself once right')
    part.write_text('[Path]\nchanged\n')
    d.notices_tick()
    rp = {x['key']: x for x in d.notices_view()}.get('root-parts') or {}
    check('zigmon-upgrade.path' in rp.get('why', ''), 'a part changed since is not named: %r' % rp.get('why'))
    # -- /api/status: an administrator's and root's command line's only
    d.account_add('boss', 'admin', 'boss pass 12345', must_change=False, quiet=True)
    d.account_add('viewer', 'viewer', 'view pass 12345', must_change=False, quiet=True)
    sa, _ = d.login('boss', 'boss pass 12345', '192.0.2.1')
    sv, _ = d.login('viewer', 'view pass 12345', '192.0.2.2')
    server = zigmon.ApiServer(d)
    server.start()
    time.sleep(0.5)

    def status_as(session='', cli=False):
        h = {'X-Zigmon-Token': d.token, 'X-Zigmon-Client': '192.0.2.9'}
        if session:
            h['X-Zigmon-Session'] = session
        if cli:
            h['X-Zigmon-Cli'] = d.cli_key
        try:
            with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:%d/api/status' % API_PORT,
                                                               headers=h), timeout=20) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, ValueError, OSError) as e:
            return {'error': str(e)}
    admin_body, viewer_body, nobody_body = status_as(sa['token']), status_as(sv['token']), status_as()
    cli_status = status_as(cli=True)
    check({x.get('key') for x in admin_body.get('notices') or []} >= {'upgrade-cli', 'root-parts'},
          'an administrator\'s status has no notices: %r' % (admin_body.get('notices') or admin_body.get('error')))
    check('notices' not in viewer_body and 'notices' not in nobody_body and viewer_body.get('ok'),
          'somebody who is not an administrator gets the notices')
    check(cli_status.get('notices'), 'root\'s command line does not get the notices')
    check(admin_body.get('notices_done') and 'notices_done' not in viewer_body, 'done lately is not an administrator\'s')
    server.stop() if hasattr(server, 'stop') else None
except Exception as e:                                  # noqa: BLE001 - said, the rest still looked at
    import traceback
    traceback.print_exc()
    check(False, 'the checks of the daemon broke off: %r' % e)

# ==== 5. the console and the command line ==========================================
print('the console, --status, --notices, --upgrade-check, --upgrade-online')
NOTICES = [
    {'key': 'root-parts', 'level': 'warn', 'title': 'zigmon %s is running, but the parts root installs are from before it'
     % zigmon.__version__, 'why': 'Not as this version ships them: zigmon_root.py, zigmon-upgrade.path - install.sh last ran for zigmon 5.40.0.',
     'action': 'As root, in the folder the zigmon-%s package was unpacked in:' % zigmon.__version__,
     'command': './install.sh --upgrade', 'link': '#control/sys-upgrade',
     'foot': 'This band goes by itself within ten minutes once it is right.', 'at': int(time.time()) - 60},
    {'key': 'upgrade-cli', 'level': 'warn', 'title': 'Update needs the command line',
     'why': 'zigmon 9.2.0 must be put in from the command line - %s (fetched and waiting).' % WHY,
     'action': 'Put it in on the machine, as root, in the unpacked folder of the package',
     'command': 'cd /root && tar xzf /var/lib/zigmon/upgrade/zigmon-9.2.0.tar.gz && cd zigmon-9.2.0 && sudo ./install.sh --upgrade',
     'link': '#control/sys-upgrade', 'at': int(time.time()) - 30},
    {'key': 'db-integrity', 'level': 'crit', 'title': 'The database fails its integrity check',
     'why': 'SQLite says: row 12 missing from index.', 'link': '#control/sys-data', 'at': int(time.time())}]
pal = zigmon.Palette(False)
fake = {'ok': True, 'broker': '127.0.0.1:1883', 'connected': True, 'bridge': {'state': 'online'}, 'level': 'ok',
        'devices': [], 'counts': {'devices': 0}, 'notices': NOTICES}


def said(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            fn(*a)
        except SystemExit:
            pass
    return buf.getvalue()


class A(object):
    json = False
    yes = True
    upgrade_online = 'newest'


real_call, real_ask = zigmon.api_call, getattr(zigmon, '_upgrade_ask', None)
zigmon.api_call = lambda path, *a, **k: (200, {'notices': NOTICES}) if path == '/api/notices' else (200, fake)
out = said(zigmon.cmd_status, A(), pal)
check('parts root installs are from before it' in out and '$ ./install.sh --upgrade' in out
      and 'Update needs the command line' in out, 'zigmon --status does not say the notices:\n' + out[:600])
out = said(zigmon.cmd_notices, A(), pal) if hasattr(zigmon, 'cmd_notices') else ''
check('The database fails its integrity check' in out and 'sudo ./install.sh --upgrade' in out and '[root-parts]' in out,
      'zigmon --notices does not list them:\n' + out[:400])
posted = []
zigmon.api_call = lambda path, method='GET', payload=None, **k: (posted.append((path, method, payload)), (200, {'ok': True}))[1]
B = type('B', (A,), {'notice_done': 'root-parts', 'notices': False})
out = said(zigmon.cmd_notices, B(), pal) if hasattr(zigmon, 'cmd_notices') else ''
check(('/api/notices', 'POST', {'action': 'done', 'key': 'root-parts'}) in posted and 'marked done' in out,
      'zigmon --notice-done did not mark it done: %r %r' % (posted, out))
check('--notice-done' in (HERE / 'zigmon.py').read_text(), 'there is no --notice-done')
cli45 = {'needed': True, 'version': '9.2.0', 'why': WHY, 'command': 'cd /root && curl -fLO https://x/zigmon-9.2.0.tar.gz && sudo ./install.sh --upgrade',
         'words': 'zigmon 9.2.0 must be put in from the command line - %s' % WHY}
web_row = {'url': 'https://x/', 'at': 1, 'newer': True, 'newest': {'version': '9.2.0', 'url': 'https://x/zigmon-9.2.0.tar.gz'},
           'packages': [{'name': 'zigmon-9.2.0.tar.gz', 'version': '9.2.0', 'url': 'https://x/zigmon-9.2.0.tar.gz'}],
           'newer_list': [{'version': '9.2.0', 'url': 'https://x/zigmon-9.2.0.tar.gz', 'cli': cli45}]}
asked = []
zigmon._upgrade_ask = lambda pal, body=None, timeout=0: (asked.append(body), {'web': {'online': web_row}})[1]
out = said(zigmon.cmd_upgrade_check, A(), pal)
check('(command line)' in out and 'sudo ./install.sh --upgrade' in out, 'zigmon --upgrade-check does not mark it:\n' + out[:400])
import builtins  # noqa: E402
real_input = builtins.input
builtins.input = lambda *a: 'n'               # never on: an older one would go on and follow it for half an hour
C = type('C', (A,), {'yes': False})
out = said(zigmon.cmd_upgrade_online, C(), pal)
builtins.input = real_input
check('must be put in from the command line' in out and not [b for b in asked if (b or {}).get('action') == 'online_get'],
      'zigmon --upgrade-online went on with a version that needs the command line:\n' + out[:400])
zigmon.api_call = real_call
if real_ask:
    zigmon._upgrade_ask = real_ask


class Scr(object):
    def __init__(self):
        self.lines = {}

    def getmaxyx(self):
        return (30, 120)

    def erase(self):
        self.lines = {}

    def addnstr(self, y, x, text, n, attr=0):
        row = self.lines.get(y, '')
        row = row.ljust(x) + str(text)[:n]
        self.lines[y] = row

    def noutrefresh(self):
        pass


import curses  # noqa: E402
con = zigmon.Console(pal)
con.curses, con.scr = curses, Scr()
con.A = {k: 0 for k in ('head', 'sel', 'ok', 'warn', 'bad', 'dim', 'key', 'title')}
con.st = dict(fake, _active='active')
try:
    con.draw('The menu', [('1', 'Status', None)], 0, 0, '')
except Exception as e:                                  # noqa: BLE001
    check(False, 'the console broke drawing the notices: %r' % e)
screen = '\n'.join(con.scr.lines.get(i, '') for i in range(30))
check('parts root installs are from before it' in screen and '$ ./install.sh --upgrade' in screen
      and 'The database fails its integrity check' in screen, 'the console does not say the notices:\n' + screen[:800])

# ==== 6. the page in Chromium =====================================================
print('the page in Chromium')
SHOTS.mkdir(parents=True, exist_ok=True)
CLI45 = cli45
DONE = [{'key': 'upgrade-cli', 'title': 'Update needs the command line', 'how': 'went by itself', 'who': '',
         'at': int(time.time()) - 3600, 'link': '#control/sys-upgrade'},
        {'key': 'root-parts', 'title': 'zigmon 5.43.3 is running, but the parts root installs are from before it',
         'how': 'done', 'who': 'the command line', 'at': int(time.time()) - 7200, 'link': '#control/sys-upgrade'}]
CLI40 = dict(cli45, version='5.40.0', words='zigmon 5.40.0 must be put in from the command line - %s' % WHY,
             command='cd /root && tar xzf /var/lib/zigmon/upgrade/zigmon-5.40.0.tar.gz && cd zigmon-5.40.0 && sudo ./install.sh --upgrade')
JS = r'''
const { chromium } = require('playwright');
const SHOTS = %(shots)s, NOTICES = %(notices)s, CLI45 = %(cli45)s, CLI40 = %(cli40)s, DONE = %(done)s;
const now = Date.now() / 1000;
const url = 'https://github.com/falco81/ZIGMon/tree/main/release';
const m = {on: false};
const up = {ok: true, version: '5.43.4', node: 'zigmon', helper: true, path_unit: true, ready: false, not_ready: [],
  status: {}, running: false, asked: false, maintenance: m, log: ['done'], cli: CLI45,
  nodes: [{name: 'zigmon', me: true, alive: true, version: '5.43.4', at: now - 4, since: now - 3600, maintenance: m}],
  web: {check: true, url: url, online: {at: now - 360, here: '5.43.4', url: url, newer: true,
    newest: {version: '9.2.0', url: url + '/zigmon-9.2.0.tar.gz'}, newest_cli: CLI45,
    newer_list: [{version: '9.2.0', url: url + '/zigmon-9.2.0.tar.gz', cli: CLI45},
                 {version: '9.1.0', url: url + '/zigmon-9.1.0.tar.gz', cli: null}],
    older_list: [{version: '5.41.0', url: url + '/zigmon-5.41.0.tar.gz', ok: true, why: '', cli: Object.assign({}, CLI40, {version: '5.41.0'})},
                 {version: '5.42.0', url: url + '/zigmon-5.42.0.tar.gz', ok: true, why: '', cli: null}]}},
  package: {file: 'zigmon-9.2.0.tar.gz', version: '9.2.0', signed_by: 'zigmon-release-test', bytes: 1843200, by: 'admin',
            at: now - 300, newer: true, older: false, cli: CLI45, changelog: '9.2.0 - a test'},
  back: {on: true, high: '5.43.4', floor: '5.19.1', busy: '', epochs: [], ready: false,
         package: {file: 'zigmon-5.40.0.tar.gz', version: '5.40.0', signed_by: 'zigmon-release-test', older: true,
                   back: {ok: true}, cli: CLI40, by: 'admin', at: now - 100}}};
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({viewport: {width: 1500, height: 1000}});
  p.setDefaultTimeout(4000);
  const errs = [], posts = [];
  p.on('pageerror', e => errs.push(String(e)));
  await p.route(/\?api=/, (route, req) => {
    const what = new URL(req.url()).searchParams.get('api');
    if (req.method() === 'POST') posts.push([what, JSON.parse(req.postData() || '{}')]);
    let body = {ok: true};
    if (what === 'upgrade') body = up;
    else if (what === 'notices-do') body = {ok: true, message: 'marked done', notices: NOTICES, done: DONE};
    else if (what === 'status') { route.fulfill({status: 500, contentType: 'application/json', body: '{"error":"stub"}'}); return; }
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
  });
  await p.addInitScript(() => {
    window.__copied = [];
    try { Object.defineProperty(navigator, 'clipboard', {value: {writeText: t => { window.__copied.push(t); return Promise.resolve(); }}}); } catch (e) {}
  });
  await p.goto('http://127.0.0.1:%(port)d/index.php#control/sys-upgrade');
  await p.waitForTimeout(1200);
  const setup = async (role) => p.evaluate(([role, notices, done]) => {
    LOCK.who = {name: role === 'admin' ? 'admin' : 'somebody', role: role};
    try { renderSettings({runtime_config: {upgrade_check: {value: 1, kind: 'switch'},
      upgrade_url: {value: 'https://github.com/falco81/ZIGMon/tree/main/release', kind: 'text'}, downgrade_show: {value: 1, kind: 'switch'}}}); } catch (e) {}
    try { showTab('control'); } catch (e) {}
    try { showControlSection('sys-upgrade'); } catch (e) {}
    STATE.status = {connected: true, bridge: {state: 'online'}, devices: [], plugs: [], counts: {devices: 0}, level: 'ok',
                    notices: notices, notices_done: done};
    try { renderNoticeBands(STATE.status); } catch (e) { window.__err = String(e); }
  }, [role, NOTICES, DONE]);
  const look = () => p.evaluate(() => {
    const T = s => (s && s.textContent || '').replace(/\s+/g, ' ').trim();
    const shown = e => !!e && !e.hidden && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0;
    const out = {};
    const bands = Array.from(document.querySelectorAll('.nband')).filter(shown);
    out.outside = bands.filter(x => !x.closest('#tab-control')).length;
    const card = document.getElementById('todo-sys-upgrade');
    out.card = card ? {shown: shown(card), first: (() => { const all = Array.from(card.parentNode.children).filter(c => c.dataset.sec === 'sys-upgrade' && shown(c)); return all[0] === card; })(),
      h2: T(card.querySelector('h2')), note: T(card.querySelector(':scope > p.note')),
      done: Array.from(card.querySelectorAll('.todo-done-t tbody tr')).map(tr => Array.from(tr.children).map(T)),
      doneHead: T(card.querySelector('.todo-done-h')),
      bands: Array.from(card.querySelectorAll('.nband')).map(bd => ({
        lv: bd.className, title: T(bd.querySelector('.nb-title')), why: T(bd.querySelector('.nb-why')),
        act: T(bd.querySelector('.nb-act')), cmd: T(bd.querySelector('.nb-cmd code')),
        mono: /mono|Menlo|Consolas/.test(getComputedStyle(bd.querySelector('.nb-cmd code') || bd).fontFamily),
        copy: !!bd.querySelector('.nb-cmd .nb-copy'), foot: T(bd.querySelector('.nb-foot')), icon: !!bd.querySelector('.nb-icon svg'),
        done: !!bd.querySelector('.nb-done'), again: !!bd.querySelector('.nb-again'), when: T(bd.querySelector('.nb-when')),
        edge: getComputedStyle(bd).borderLeftWidth}))} : null;
    const crit = document.getElementById('todo-sys-data');
    out.crit = crit ? {shown: shown(crit), band: (crit.querySelector('.nband') || {}).className || '',
                       icon: (crit.querySelector('.nband .nb-icon svg') || {}).innerHTML || ''} : null;
    out.flag = ((card && card.querySelector('.nband .nb-icon svg')) || {}).innerHTML || '';
    const mark = s => { const b = document.querySelector('#control-nav button[data-sec="' + s + '"] .nav-nmark'); return b ? b.className + ' ' + T(b) : ''; };
    out.markUp = mark('sys-upgrade'); out.markData = mark('sys-data');
    const bm = document.querySelector('#control-nav button[data-sec="sys-upgrade"] .nav-nmark');
    out.markSeen = bm ? getComputedStyle(bm).opacity === '1' && bm.getBoundingClientRect().width > 8 : false;
    out.attn = attentionItems(STATE.status).filter(x => x.notice).map(x => x.who);
    // From the web
    const wb = document.getElementById('up-web');
    const upb = Array.from(wb.querySelectorAll('button')).filter(x => /Upgrade to/.test(x.textContent))[0];
    out.web = {band: T(wb.querySelector('.nband .nb-title')), cmd: T(wb.querySelector('.nband .nb-cmd code')),
      upDisabled: upb ? upb.disabled : null, upTitle: upb ? (upb.title || upb.dataset.said || '') : '',
      fetch: !!Array.from(wb.querySelectorAll('button')).filter(x => /Only fetch it/.test(x.textContent) && !x.disabled)[0],
      opts: Array.from(wb.querySelectorAll('select.up-pick option')).map(T)};
    // the package sent
    const pk = document.getElementById('up-pkg');
    out.pkg = {band: T(pk.querySelector('.nband .nb-title')), start: shown(document.getElementById('up-start'))};
    // going back
    const bk = document.getElementById('up-back');
    const gb = Array.from(bk.querySelectorAll('.btnrow button')).filter(x => /Go back to 5.40.0/.test(x.textContent))[0];
    out.back = {band: T(bk.querySelector('.nband .nb-title')), goDisabled: gb ? gb.disabled : null,
      tag: Array.from(bk.querySelectorAll('.up-cli-tag')).map(T),
      rowGo: Array.from(bk.querySelectorAll('.dg-row')).map(r => [T(r.querySelector('b')), !!Array.from(r.querySelectorAll('button')).filter(x => /Go back/.test(x.textContent))[0]])};
    out.err = window.__err || '';
    return out;
  });
  await setup('admin');
  try { await p.evaluate(() => rootPost('upgrade-do', {}).then(drawUpgrade)); } catch (e) { errs.push('drawUpgrade: ' + e); }
  await p.waitForTimeout(600);
  await setup('admin');
  await p.waitForTimeout(300);
  const r = {admin: await look()};
  await p.evaluate(() => window.scrollTo(0, 0));
  await p.screenshot({path: SHOTS + '/1-upgrades-to-be-done-by-hand.png', fullPage: false});
  try { await p.locator('#todo-sys-upgrade').screenshot({path: SHOTS + '/1b-to-be-done-card.png'}); } catch (e) {}
  try { await p.locator('#up-web').screenshot({path: SHOTS + '/2-from-the-web-command-line.png'}); } catch (e) {}
  try { await p.locator('#up-pkg').screenshot({path: SHOTS + '/3-package-sent-command-line.png'}); } catch (e) {}
  try { await p.locator('#up-back-card').screenshot({path: SHOTS + '/4-going-back-command-line.png'}); } catch (e) {}
  try {
    await p.evaluate(() => document.querySelector('#control-nav button[data-sec="sys-upgrade"]').scrollIntoView({block: 'center'}));
    await p.locator('#control-nav').screenshot({path: SHOTS + '/5-rail-badges.png'});
  } catch (e) {}
  // Copy, Look again, Done
  try { await p.click('#todo-sys-upgrade .nband .nb-copy'); } catch (e) { errs.push('no Copy'); }
  await p.waitForTimeout(200);
  r.copied = await p.evaluate(() => window.__copied);
  try { await p.click('#todo-sys-upgrade .nband .nb-again'); } catch (e) { errs.push('no Look again'); }
  await p.waitForTimeout(300);
  try { await p.click('#todo-sys-upgrade .nband .nb-done'); } catch (e) { errs.push('no Done'); }
  await p.waitForTimeout(300);
  // Needs attention, and its item to the pane
  await p.evaluate(() => { try { showControlSection('sys-time'); } catch (e) {} });
  await p.evaluate(() => { try { showAttention(); } catch (e) { window.__err = String(e); } });
  await p.waitForTimeout(300);
  r.attnText = await p.evaluate(() => (document.getElementById('attnbody') || {}).textContent || '');
  await p.screenshot({path: SHOTS + '/6-needs-attention.png'});
  await p.evaluate(() => { const w = Array.from(document.querySelectorAll('#attnbody .attn-item .who')).filter(x => /parts root installs/.test(x.textContent))[0]; if (w) w.click(); });
  await p.waitForTimeout(300);
  r.after = await p.evaluate(() => ({sec: CONTROL_SEC, closed: document.getElementById('attnback').hidden}));
  // a phone
  await p.setViewportSize({width: 390, height: 900});
  await p.evaluate(() => { showControlSection('sys-upgrade'); renderNoticeBands(STATE.status); window.scrollTo(0, 0); });
  await p.waitForTimeout(300);
  r.phone = await p.evaluate(() => ({scroll: document.documentElement.scrollWidth, width: window.innerWidth,
    over: Array.from(document.querySelectorAll('#todo-sys-upgrade .nband')).map(b => Math.round(b.getBoundingClientRect().right))}));
  try { await p.locator('#todo-sys-upgrade').screenshot({path: SHOTS + '/7-phone-to-be-done.png'}); } catch (e) {}
  await p.setViewportSize({width: 1500, height: 1000});
  // nothing pending: the card stays, with its green strip
  await p.evaluate(() => { STATE.status.notices = []; STATE.status.notices_done = []; renderNoticeBands(STATE.status); window.scrollTo(0, 0); });
  await p.waitForTimeout(200);
  r.empty = await p.evaluate(() => { const c = document.getElementById('todo-sys-upgrade');
    return c ? {shown: !c.hidden && c.getBoundingClientRect().height > 0, none: (c.querySelector('.todo-none') || {}).textContent || '',
                table: c.querySelectorAll('.todo-done-t').length, bands: c.querySelectorAll('.nband').length,
                first: c.nextElementSibling && c.nextElementSibling.id} : null; });
  try { await p.locator('#todo-sys-upgrade').screenshot({path: SHOTS + '/8-nothing-to-be-done.png'}); } catch (e) {}
  // somebody who is not an administrator
  await p.evaluate((n) => { STATE.status.notices = n; }, NOTICES);
  await setup('operator');
  await p.waitForTimeout(200);
  r.viewer = await p.evaluate(() => ({
    bands: Array.from(document.querySelectorAll('.todo-card')).filter(c => !c.hidden).length,
    marks: document.querySelectorAll('#control-nav .nav-nmark').length,
    attn: attentionItems(STATE.status).filter(x => x.notice).length}));
  r.posts = posts;
  r.errs = errs;
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); process.exit(0); });
''' % {'port': PHP_PORT, 'shots': json.dumps(str(SHOTS)), 'notices': json.dumps(NOTICES), 'cli45': json.dumps(CLI45),
       'cli40': json.dumps(CLI40), 'done': json.dumps(DONE)}
(W / 'run.js').write_text(JS)
r = {'error': 'php is not here'}
if shutil.which('php') and shutil.which('node'):
    php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, '-t', str(HERE / 'web')],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        root = sh(['npm', 'root', '-g']).stdout.strip()
        try:
            got = sh(['node', str(W / 'run.js')], timeout=180, env=dict(os.environ, NODE_PATH=root))
        except subprocess.TimeoutExpired:
            got = subprocess.CompletedProcess([], 1, '', 'the page did not answer in 180 s')
        try:
            r = json.loads(got.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            r = {'error': (got.stdout + got.stderr)[-300:]}
    finally:
        php.kill()
        php.wait()
if r.get('error'):
    check(False, 'the page could not be looked at: %s' % r['error'][:300])
else:
    if os.environ.get('DBG'):
        print('DBG', json.dumps(r, indent=1))
    a = r.get('admin') or {}
    check(not r.get('errs') and not a.get('err'), 'the page threw: %r %r' % (r.get('errs'), a.get('err')))
    check(a.get('outside') == 0, 'a notice band is drawn outside Settings: %r' % a.get('outside'))
    c = a.get('card') or {}
    bands = c.get('bands') or []
    check(c.get('shown') and c.get('first') and len(bands) == 2 and c.get('h2') == 'To be done by hand'
          and 'cannot do itself' in c.get('note', ''),
          'the card To be done by hand is not at the top of Settings - Upgrades: %r' % {k: c.get(k) for k in ('shown', 'first', 'h2')})
    if bands:
        b0 = bands[0]
        check('is running, but the parts root installs are from before it' in b0['title'] and b0['why']
              and 'unpacked in' in b0['act'] and b0['cmd'] == './install.sh --upgrade' and b0['mono'] and b0['copy']
              and 'goes by itself' in b0['foot'] and b0['icon'] and b0['done'] and b0['again'] and b0['when']
              and b0['edge'] == '4px' and 'warn' in b0['lv'], 'the band is not as upsmon draws it: %r' % b0)
    check('M5 4h11' in a.get('flag', ''), 'a warn band has no flag')
    cr = a.get('crit') or {}
    check(cr.get('shown') is False and 'crit' in cr.get('band', '') and 'M6 6l12 12' in cr.get('icon', ''),
          'the crit item is not in its own pane (Data and database) with an x: %r' % cr)
    check(c.get('doneHead') == 'Done lately' and [x[:3] for x in c.get('done') or []] == [
        ['Update needs the command line', 'went by itself', '\u2013'],
        ['zigmon 5.43.3 is running, but the parts root installs are from before it', 'done', 'the command line']],
          'Done lately is not under the bands: %r' % c.get('done'))
    check(r.get('copied') == ['./install.sh --upgrade'], 'Copy did not copy the command: %r' % r.get('copied'))
    nd = [x[1] for x in r.get('posts') or [] if x[0] == 'notices-do']
    check({'action': 'done', 'key': 'root-parts'} in nd and {'action': 'look'} in nd,
          'Done and Look again did not ask the daemon: %r' % nd)
    check('warn' in a.get('markUp', '') and a.get('markUp', '').endswith(' 2') and 'crit' in a.get('markData', ''),
          'the rail does not count the panes: %r %r' % (a.get('markUp'), a.get('markData')))
    check(a.get('markSeen'), 'the badge on Upgrades is not to be seen in the rail')
    check(len(a.get('attn') or []) == 3, 'Needs attention has not each notice: %r' % a.get('attn'))
    check('parts root installs are from before it' in r.get('attnText', '') and './install.sh --upgrade' in r.get('attnText', ''),
          'the Needs attention list does not say it')
    check((r.get('after') or {}) == {'sec': 'sys-upgrade', 'closed': True}, 'its item does not lead to the pane: %r' % r.get('after'))
    w = a.get('web') or {}
    check('zigmon 9.2.0 must be put in from the command line' in w.get('band', '') and 'install.sh --upgrade' in w.get('cmd', '')
          and w.get('upDisabled') is True and 'command line' in w.get('upTitle', '') and w.get('fetch'),
          'From the web does not draw the band and disable Upgrade: %r' % w)
    check('zigmon 9.2.0 (the newest) (command line)' in (w.get('opts') or []) and 'zigmon 9.1.0' in (w.get('opts') or []),
          'the versions in the list are not marked: %r' % w.get('opts'))
    pk = a.get('pkg') or {}
    check('must be put in from the command line' in pk.get('band', '') and pk.get('start') is False,
          'a package sent does not show the band instead of Upgrade: %r' % pk)
    bk = a.get('back') or {}
    check('zigmon 5.40.0 must be put in from the command line' in bk.get('band', '') and bk.get('goDisabled') is True,
          'going back does not show the band and disable Go back: %r' % bk)
    check(bk.get('tag') == ['command line'] and ['5.41.0', False] in (bk.get('rowGo') or [])
          and ['5.42.0', True] in (bk.get('rowGo') or []), 'the older versions are not marked: %r' % bk)
    ph = r.get('phone') or {}
    check(ph.get('scroll', 999) <= ph.get('width', 0) and all(x <= ph.get('width', 0) for x in ph.get('over') or [1e9]),
          'the bands do not fit a phone: %r' % ph)
    check(r.get('empty') == {'shown': True, 'none': 'Nothing is to be done by hand.', 'table': 0, 'bands': 0, 'first': 'up-card'},
          'with nothing pending the card is not there with its green strip, before The nodes: %r' % r.get('empty'))
    check(r.get('viewer') == {'bands': 0, 'marks': 0, 'attn': 0}, 'somebody not an administrator sees them: %r' % r.get('viewer'))

if bad:
    print('\n%d problem(s); the folder is kept: %s' % (len(bad), W))
    raise SystemExit(1)
shutil.rmtree(str(W), ignore_errors=True)
print('\na release that needs the command line is said everywhere and put in only there: every check passed')
