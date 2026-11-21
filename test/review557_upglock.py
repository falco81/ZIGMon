#!/usr/bin/env python3
"""One upgrade at a time (review 5.57): root's upgrade helper holds an flock on
one lock file of root's for the whole of an upgrade or a downgrade, and
install.sh --upgrade run by hand takes the same one.

  * two helper runs at once: the second - a --run by hand, or a request of the
    dashboard's - is refused at once with why ("another upgrade is running
    (to X, started HH:MM by Y) - this one was not started"), touches neither
    the pages' file nor the running one's status.json or log, its request is
    taken out of the way (not served again and again); the first ends as it
    should;
  * install.sh --upgrade by hand: refused while the helper holds the lock,
    before it tells the pages anything; it goes on once the helper is done;
    while it holds the lock itself, the helper is refused (and a request is
    answered as its own, with the same words);
  * the install.sh the helper runs takes no lock: it is not refused;
  * a holder killed with SIGKILL leaves nothing behind: the next one goes on
    (the install.sh the helper started does not hold it either);
  * no flock on the machine: install.sh goes on as it always did, and says so;
  * the daemon says the same words when it refuses a second one itself.

    python3 test/review557_upglock.py < /dev/null
"""
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
HELPER = HERE / 'deploy' / 'zigmon_upgrade.py'
W = Path(tempfile.mkdtemp(prefix='zigmon-upglock-'))
bad = []
CHILDREN = []           # every process started here, killed by its PID at the end


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


# ---- the machine, with zigmon 5.17.0 on it ----------------------------------------------
LIB, WEB, KEYS = W / 'lib' / 'zigmon', W / 'www' / 'zigmon', W / 'lib' / 'zigmon' / 'release-keys'
STATE, UNITS, OWN = W / 'state', W / 'units', W / 'own'
for d in (KEYS, WEB, STATE / 'upgrade', UNITS):
    d.mkdir(parents=True)
OLD_PY = "#!/usr/bin/python3\n__version__ = '5.17.0'\n"
(LIB / 'zigmon.py').write_text(OLD_PY)
(WEB / 'index.php').write_text('<?php // the old page\n')
(UNITS / 'zigmon.service').write_text('[Service]\nExecStart=old\n')
key = W / 'release.key'
sh(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', str(key)])
sh(['openssl', 'pkey', '-in', str(key), '-pubout', '-out', str(KEYS / 'zigmon-release-test.pub')])
SAYS = {'version': '5.17.0'}


class Health(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({'ok': True, 'version': SAYS['version']}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = ThreadingHTTPServer(('127.0.0.1', 0), Health)
threading.Thread(target=srv.serve_forever, daemon=True).start()
LOCKFILE = OWN / 'upgrade.lock'
ENV = {k: v for k, v in os.environ.items() if not k.startswith('ZIGMON_') and k != 'SUDO_USER'}
ENV.update(ZIGMON_STATE=str(STATE), ZIGMON_LIB=str(LIB), ZIGMON_WEB=str(WEB),
           ZIGMON_RELEASE_KEYS=str(KEYS), ZIGMON_ROOT_OWN=str(OWN),
           ZIGMON_UNITS=str(UNITS), ZIGMON_NO_SERVICES='1', ZIGMON_HEALTH_WAIT_S='3',
           ZIGMON_HEALTH_URL='http://127.0.0.1:%d/api/health' % srv.server_address[1],
           ZIGMON_UPGRADE_TEST='1', ZIGMON_USER='root', ZIGMON_CONFIG=str(W / 'config.json'))

# install.sh's own blocks: how far it is for the pages (5.54), and the lock
SETUP = (HERE / 'install.sh').read_text()
a = SETUP.index('# ---- (5.54) how far an upgrade is, for the pages')
b = SETUP.index('# ---- one upgrade at a time: end', a)
BLOCKS = SETUP[a:b]
check('upgrade_lock "$had"      # one upgrade at a time' in SETUP
      and SETUP.index('upgrade_lock "$had"') < SETUP.index('upgrade_watch "$had"     # 5.54'),
      'do_upgrade does not take the lock first, before the pages are told')
HEAD = r'''set -euo pipefail
C_HEAD=""; C_OFF=""; C_DIM=""; C_OK=""; C_WARN=""; C_BAD=""
step()  { printf '\n%s==> %s%s\n' "$C_HEAD" "$1" "$C_OFF"; [[ -z "${UPG_ON:-}" ]] || upgrade_step "$1"; }
note()  { printf '    %s%s%s\n' "$C_DIM" "$1" "$C_OFF"; }
good()  { printf '    %s%s%s\n' "$C_OK" "$1" "$C_OFF"; }
warn()  { printf '    %s%s%s\n' "$C_WARN" "$1" "$C_OFF"; }
fail()  { printf '\n%sERROR: %s%s\n' "$C_BAD" "$1" "$C_OFF" >&2; exit 1; }
'''
(W / 'blocks.sh').write_text(BLOCKS)

# a stand-in for install.sh --upgrade run by hand: its lock, then the pages, then
# (HOLD) it waits until it is let go
DRIVE = W / 'drive.sh'
DRIVE.write_text(HEAD + r'''VERSION=5.18.0; WEB_DIR="$1"; DRY_RUN=""; WITH_WEB=yes; SELINUX_ETC=/nonexistent-selinux
source "$(dirname "$0")/blocks.sh"
upgrade_lock 5.17.0
upgrade_watch 5.17.0
echo "GOT-LOCK"
if [[ -n "${HOLD:-}" ]]; then
    echo $$ > "$HOLD.pid"
    while [[ ! -f "$HOLD" ]]; do sleep 0.05; done
fi
upgrade_finish
''')


def package(version, name):
    """A signed release whose install.sh takes install.sh's own lock as the
    real one does (it must not be refused under the helper), writes down what
    it was handed, and waits for GATE when it is there to wait on."""
    top = 'zigmon-%s' % version
    d = W / 'build' / name / top
    if d.parent.exists():
        shutil.rmtree(d.parent)
    d.mkdir(parents=True)
    (d / 'zigmon.py').write_text("#!/usr/bin/python3\n__version__ = '%s'\n" % version)
    (d / 'README.md').write_text('%s — a test release.\n' % version)
    (d / 'blocks.sh').write_text(BLOCKS)
    (d / 'install.sh').write_text(HEAD + r'''cd "$(dirname "$0")"
VERSION=%(v)s; WEB_DIR=%(web)s; DRY_RUN=""; WITH_WEB=yes; SELINUX_ETC=/nonexistent-selinux
source ./blocks.sh
upgrade_lock 5.17.0
echo "LOCK-PASSED held=${ZIGMON_UPGRADE_LOCK_HELD:-}"
upgrade_watch 5.17.0
step "Program files"
echo $$ > %(w)s/install.pid
if [[ -f %(w)s/gate ]]; then
    touch %(w)s/sleeping
    while [[ -f %(w)s/gate ]]; do sleep 0.05; done
fi
install -m 755 zigmon.py %(lib)s/zigmon.py
upgrade_finish
''' % {'v': version, 'web': WEB, 'w': W, 'lib': LIB})
    lines = []
    for p in sorted(x for x in d.rglob('*') if x.is_file()):
        lines.append('%s  %s' % (hashlib.sha256(p.read_bytes()).hexdigest(), p.relative_to(d).as_posix()))
    (d / 'MANIFEST').write_text('\n'.join(lines) + '\n')
    sh(['openssl', 'pkeyutl', '-sign', '-inkey', str(key), '-rawin', '-in', str(d / 'MANIFEST'),
        '-out', str(d / 'MANIFEST.sig')])
    out = W / 'build' / ('%s.tar.gz' % name)
    sh(['tar', 'czf', str(out), '-C', str(d.parent), top])
    return out


def helper(*args, request=None):
    p = subprocess.Popen([sys.executable, '-I', str(HELPER)] + list(args), env=ENV, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    CHILDREN.append(p)
    return p


def ask(pkg, version, ident, by='olga'):
    shutil.copy(pkg, STATE / 'upgrade' / ('zigmon-%s.tar.gz' % version))
    (STATE / 'upgrade' / 'request.json').write_text(json.dumps(
        {'id': ident, 'file': 'zigmon-%s.tar.gz' % version, 'version': version,
         'sha': hashlib.sha256(pkg.read_bytes()).hexdigest(), 'by': by}))


def wait_for(path, most=30):
    end = time.time() + most
    while time.time() < end:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


def gate_shut():
    (W / 'gate').write_text('')
    for f in ('sleeping', 'install.pid'):
        (W / f).unlink(missing_ok=True)


def gate_open():
    (W / 'gate').unlink(missing_ok=True)


def files():
    """The running upgrade's files, as they are."""
    out = {}
    for p in (WEB / '.upgrade.json', STATE / 'upgrade' / 'status.json', STATE / 'upgrade' / 'last.log',
              STATE / 'upgrade' / 'request.taken'):
        try:
            out[p.name] = (p.read_bytes(), p.stat().st_mtime_ns)
        except OSError:
            out[p.name] = None
    return out


def drive(hold=None, env=None):
    e = dict(ENV, **(env or {}))
    if hold:
        e['HOLD'] = str(hold)
    p = subprocess.Popen(['bash', str(DRIVE), str(WEB)], env=e, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    CHILDREN.append(p)
    if hold:
        return p
    out, err = p.communicate(timeout=60)
    return p.returncode, out, err


def lock_free():
    fd = os.open(str(LOCKFILE), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    finally:
        os.close(fd)


def pages():
    try:
        return json.loads((WEB / '.upgrade.json').read_text())
    except (OSError, ValueError):
        return {}


def status():
    try:
        return json.loads((STATE / 'upgrade' / 'status.json').read_text())
    except (OSError, ValueError):
        return {}


try:
    P18 = package('5.18.0', 'p18')
    P19 = package('5.19.0', 'p19')

    # ==== 1. a dashboard upgrade runs; a --run and a request beside it ====================
    print('a dashboard upgrade runs: a --run by hand and a second request are refused, the first ends well')
    gate_shut()
    SAYS['version'] = '5.18.0'
    ask(P18, '5.18.0', 'first1')
    first = helper()
    check(wait_for(W / 'sleeping'), 'the first upgrade never reached its install.sh')
    time.sleep(0.3)
    check(not lock_free(), 'the helper does not hold the lock while install.sh runs')
    holder = json.loads(LOCKFILE.read_text())
    check(holder.get('what') == 'request' and holder.get('version') == '5.18.0'
          and holder.get('by') == 'olga on the dashboard' and holder.get('pid') == first.pid,
          'the lock does not say who holds it: %r' % holder)
    before = files()
    check(before['.upgrade.json'] and json.loads(before['.upgrade.json'][0]).get('id') == 'first1',
          'the first upgrade wrote no file for the pages: %r' % (before['.upgrade.json'],))
    hhmm = time.strftime('%H:%M', time.localtime(holder['started']))
    t0 = time.time()
    second = helper('--run', str(P19))
    out, err = second.communicate(timeout=30)
    took = time.time() - t0
    words = 'another upgrade is running (to 5.18.0, started %s by olga on the dashboard) - this one was not started' % hhmm
    check(second.returncode == 1 and words in err, 'a second --run was not refused with why: %d %r %r'
          % (second.returncode, out[-300:], err[-300:]))
    check(took < 10, 'the second one was not refused at once (%.1f s)' % took)
    check(files() == before, 'a refused --run touched the running upgrade\'s files')
    check((LIB / 'zigmon.py').read_text() == OLD_PY, 'a refused --run changed the program')
    # a second request of the dashboard's while a request runs: taken out of the way
    # (the path unit would start the helper again and again), the running one's
    # status.json, log and request.taken untouched
    ask(P19, '5.19.0', 'second2')
    before = files()
    third = helper()
    out, err = third.communicate(timeout=30)
    check(third.returncode == 0 and words in err, 'a second request was not refused with why: %r' % err[-300:])
    check(not (STATE / 'upgrade' / 'request.json').exists(),
          'the refused request was left to be served again and again')
    check(not (STATE / 'upgrade' / 'request.refused').exists(), 'the refused request was left aside')
    check(files() == before, 'a refused request touched the running upgrade\'s files')
    # install.sh --upgrade by hand, while the helper holds it: refused before the pages hear of it
    rc, out, err = drive()
    check(rc == 1 and words in err and 'GOT-LOCK' not in out,
          'install.sh --upgrade by hand was not refused while the helper ran: %d %r %r' % (rc, out[-200:], err[-300:]))
    check(files() == before, 'a refused install.sh touched the running upgrade\'s files')
    # the first goes on and ends as it should
    gate_open()
    out, err = first.communicate(timeout=60)
    st, pg = status(), pages()
    check(first.returncode == 0 and st.get('id') == 'first1' and st.get('state') == 'done'
          and pg.get('id') == 'first1' and pg.get('state') == 'done',
          'the first upgrade did not end well: %r %r %r' % (st, pg, err[-300:]))
    check((LIB / 'zigmon.py').read_text().count("'5.18.0'") == 1, 'the first upgrade did not put 5.18.0 in')
    log = (STATE / 'upgrade' / 'last.log').read_text()
    check('LOCK-PASSED held=1' in log, 'the helper\'s own install.sh was refused, or not told the lock is held:\n'
          + log[-600:])
    check(st.get('by') == 'olga on the dashboard' and isinstance(st.get('started'), int) and st.get('downgrade') is False,
          'status.json does not say who and since when: %r' % st)
    check(lock_free(), 'the lock was still held after the upgrade ended')
    # afterwards, install.sh by hand goes on
    rc, out, err = drive()
    check(rc == 0 and 'GOT-LOCK' in out and pages().get('state') == 'done',
          'install.sh by hand was refused after the helper had ended: %d %r' % (rc, err[-300:]))
    check(lock_free(), 'install.sh by hand left the lock held')

    # ==== 2. a --run by hand runs; a request of the dashboard's beside it ==================
    print('a --run by hand runs: a request is answered as its own, refused')
    (LIB / 'zigmon.py').write_text(OLD_PY)
    gate_shut()
    SAYS['version'] = '5.19.0'
    run = helper('--run', str(P19))
    check(wait_for(W / 'sleeping'), 'the --run never reached its install.sh')
    time.sleep(0.3)
    hold = json.loads(LOCKFILE.read_text())
    check(hold.get('what') == 'run' and hold.get('version') == '5.19.0' and hold.get('by') == 'root on the command line',
          'the --run does not say who holds the lock: %r' % hold)
    ask(P18, '5.18.0', 'dash3')
    pg_before = (WEB / '.upgrade.json').read_bytes()
    req = helper()
    out, err = req.communicate(timeout=30)
    words = 'another upgrade is running (to 5.19.0, started %s by root on the command line) - this one was not started' \
        % time.strftime('%H:%M', time.localtime(hold['started']))
    st = status()
    check(st.get('id') == 'dash3' and st.get('state') == 'failed' and st.get('said') == words,
          'the refused request was not answered as its own: %r' % st)
    check((WEB / '.upgrade.json').read_bytes() == pg_before, 'a refused request touched the pages\' file')
    check(not (STATE / 'upgrade' / 'request.json').exists(), 'the refused request was left to be served again')
    gate_open()
    out, err = run.communicate(timeout=60)
    check(run.returncode == 0 and pages().get('state') == 'done' and pages().get('version') == '5.19.0',
          'the --run did not end well: %d %r %r' % (run.returncode, pages(), err[-300:]))

    # ==== 3. install.sh by hand holds it: the helper is refused ============================
    print('install.sh --upgrade by hand runs: the helper is refused, and goes on afterwards')
    SAYS['version'] = '5.18.0'
    (LIB / 'zigmon.py').write_text(OLD_PY)
    go = W / 'hand-go'
    hand = drive(hold=go)
    check(wait_for(Path(str(go) + '.pid')), 'install.sh by hand did not get the lock')
    time.sleep(0.2)
    hold = json.loads(LOCKFILE.read_text())
    check(hold.get('what') == 'install.sh' and hold.get('version') == '5.18.0'
          and 'install.sh --upgrade' in hold.get('by', ''), 'install.sh does not say it holds the lock: %r' % hold)
    pg_before = (WEB / '.upgrade.json').read_bytes()
    r = helper('--run', str(P18))
    out, err = r.communicate(timeout=30)
    check(r.returncode == 1 and 'another upgrade is running (to 5.18.0, started' in err
          and 'by root on the command line (install.sh --upgrade)) - this one was not started' in err,
          'a --run was not refused while install.sh ran by hand: %r' % err[-300:])
    check((WEB / '.upgrade.json').read_bytes() == pg_before and (LIB / 'zigmon.py').read_text() == OLD_PY,
          'a refused --run changed something')
    rc2, out2, err2 = drive()
    check(rc2 == 1 and 'another upgrade is running' in err2, 'a second install.sh by hand was not refused: %r' % err2)
    go.write_text('')
    hand.communicate(timeout=30)
    check(hand.returncode == 0 and lock_free(), 'install.sh by hand did not end, or left the lock held')
    gate_open()
    r = helper('--run', str(P18))
    out, err = r.communicate(timeout=60)
    check(r.returncode == 0 and 'another upgrade' not in err, 'a --run after install.sh was refused: %r' % err[-300:])

    # ==== 4. a holder killed with SIGKILL leaves nothing behind ============================
    print('a holder killed with SIGKILL: the next one goes on')
    SAYS['version'] = '5.19.0'
    (LIB / 'zigmon.py').write_text(OLD_PY)
    gate_shut()
    k = helper('--run', str(P19))
    check(wait_for(W / 'sleeping'), 'the --run to kill never reached its install.sh')
    orphan = int((W / 'install.pid').read_text())
    os.kill(k.pid, signal.SIGKILL)
    k.communicate(timeout=30)
    time.sleep(0.2)
    check(lock_free(), 'a helper killed with SIGKILL left the lock held (also while its install.sh lives on)')
    try:
        os.kill(orphan, signal.SIGKILL)                  # its install.sh, by its PID
    except ProcessLookupError:
        pass
    gate_open()
    r = helper('--run', str(P19))
    out, err = r.communicate(timeout=60)
    check(r.returncode == 0 and 'another upgrade' not in err, 'the run after a killed one was refused: %r' % err[-300:])
    hand = drive(hold=W / 'never')
    check(wait_for(Path(str(W / 'never') + '.pid')), 'install.sh by hand to kill did not start')
    os.kill(hand.pid, signal.SIGKILL)
    hand.communicate(timeout=30)
    time.sleep(0.4)                                      # its last `sleep 0.05` gone too
    rc, out, err = drive()
    check(rc == 0 and 'GOT-LOCK' in out, 'install.sh after one killed with SIGKILL was refused: %r' % err[-300:])
    check(not list(OWN.glob('*.pid')) and sorted(x.name for x in OWN.iterdir() if not x.name.startswith('zigmon-upgrade-'))
          == ['upgrade.lock'], 'something besides the lock file was left in root\'s folder: %r'
          % sorted(x.name for x in OWN.iterdir()))

    # ==== 5. no flock on the machine ====================================================
    print('no flock: install.sh goes on as it always did, and says so')
    nobin = W / 'nobin'
    nobin.mkdir()
    for tool in ('dirname', 'install', 'python3', 'date', 'sort', 'head', 'tr', 'mktemp', 'chmod', 'mv', 'rm',
                 'cat', 'sed', 'sleep', 'bash', 'printf'):
        found = shutil.which(tool)
        if found:
            os.symlink(found, nobin / tool)
    rc, out, err = drive(env={'PATH': str(nobin)})
    check(rc == 0 and 'GOT-LOCK' in out and 'flock (util-linux) is not on this machine' in out,
          'without flock install.sh did not go on with a warning: %d %r %r' % (rc, out[-300:], err[-300:]))
    # --dry-run takes nothing; root's helper running it takes nothing
    rc, out, err = drive(env={'ZIGMON_UPGRADE_FROM_PAGES': '1'})
    check(rc == 0 and 'GOT-LOCK' in out, 'install.sh under an older helper (no lock of its own) was refused')

    # ==== 6. the daemon's words ==========================================================
    print('the daemon refuses a second one with the same words')
    sys.path.insert(0, str(HERE))
    sys.argv = ['zigmon']
    import zigmon                                        # noqa: E402
    at = time.time() - 60
    got = zigmon.Daemon.upgrade_busy_words(None, {'running': True, 'status': {
        'state': 'running', 'version': '5.18.0', 'started': int(at), 'at': time.time(), 'by': 'olga on the dashboard'}})
    check(got == 'another upgrade is running (to 5.18.0, started %s by olga on the dashboard) - this one was not started'
          % time.strftime('%H:%M', time.localtime(int(at))), 'the daemon\'s words: %r' % got)
    got = zigmon.Daemon.upgrade_busy_words(None, {'running': True, 'status': {
        'state': 'running', 'version': '5.16.0', 'at': at, 'downgrade': True}})
    check(got.startswith('another downgrade is running (back to 5.16.0, started ') and got.endswith(
        ') - this one was not started'), 'the daemon\'s words for going back: %r' % got)
    got = zigmon.Daemon.upgrade_busy_words(None, {'running': False, 'asked': True, 'status': {}})
    check(got == 'an upgrade is asked for already and root has not taken it yet - this one was not started',
          'the daemon\'s words for one asked for: %r' % got)
    src = (HERE / 'zigmon.py').read_text()
    check(src.count('raise ValueError(self.upgrade_busy_words(st))') == 2,
          'upgrade_start and downgrade_start do not both say why')
finally:
    gate_open()
    (W / 'never').write_text('')
    for p in CHILDREN:
        if p.poll() is None:
            try:
                os.kill(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    srv.shutdown()

if bad:
    print('review557_upglock: %d FAILED' % len(bad))
    sys.exit(1)
shutil.rmtree(W, ignore_errors=True)
print('review557_upglock: ok')
