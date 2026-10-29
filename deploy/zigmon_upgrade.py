#!/usr/bin/python3 -I
"""zigmon_upgrade.py - a new version of zigmon, put in by root (5.18).

The dashboard cannot upgrade anything itself: the daemon runs as `zigmon`,
which may not write a byte of the program. What it may do is lay a package
down in /var/lib/zigmon/upgrade/ and ask for it with request.json; systemd
(zigmon-upgrade.path) sees the request and starts zigmon-upgrade.service,
which runs this as root. This then trusts nothing it was handed:

  * the package is copied to a folder of root's own before anything is read
    from it, so it cannot be changed under the check;
  * it must be signed: MANIFEST lists the SHA-256 of every file, and
    MANIFEST.sig is the Ed25519 signature of MANIFEST by one of the keys in
    /usr/local/lib/zigmon/release-keys/ - which only root can write, and
    which only a package installed by root (install.sh, or this) puts there;
  * every file in it is listed in MANIFEST with the right hash, nothing more,
    no links, no device, no path outside its one folder;
  * it is not older than the version installed (the same one again is a
    retry and is allowed) - unless going back was asked for (5.22), and it is
    safe: see DB_EPOCHS below.

Then, before anything is changed: a backup of the whole installation
(zigmon_root.py --backup) and a copy of the program as it is. Its own
install.sh --upgrade --yes is run, exactly as somebody would on the command
line, and the new version is asked whether it answers - running, its API up,
saying it is the version just put in. When it does not, the program it
replaced is put back and started again, and the dashboard is told why.

  zigmon_upgrade.py                 serve request.json (root, from systemd)
  zigmon_upgrade.py --inspect FILE  check a package and say what it is (JSON);
                                    any user - the daemon asks this way
  zigmon_upgrade.py --run FILE      check and put in a package by hand (root)
  zigmon_upgrade.py --run FILE --downgrade
                                    go back to an older version by hand (root)
"""
import grp
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request

STATE_DIR = os.environ.get('ZIGMON_STATE', '/var/lib/zigmon')
UPGRADE_DIR = os.path.join(STATE_DIR, 'upgrade')
LIB_DIR = os.environ.get('ZIGMON_LIB', '/usr/local/lib/zigmon')
WEB_DIR = os.environ.get('ZIGMON_WEB', '/var/www/zigmon')
KEYS_DIR = os.environ.get('ZIGMON_RELEASE_KEYS', os.path.join(LIB_DIR, 'release-keys'))
OWN_DIR = os.environ.get('ZIGMON_ROOT_OWN', '/var/lib/zigmon-root')
CONFIG_FILE = os.environ.get('ZIGMON_CONFIG', '/etc/zigmon/config.json')
UNITS = os.environ.get('ZIGMON_UNITS', '/etc/systemd/system')
NO_SERVICES = bool(os.environ.get('ZIGMON_NO_SERVICES'))
HEALTH_WAIT_S = float(os.environ.get('ZIGMON_HEALTH_WAIT_S', '90'))
SERVICE_USER = os.environ.get('ZIGMON_USER', 'zigmon')
FS_ROOT = os.environ.get('ZIGMON_FS_ROOT', '').rstrip('/')      # the checks: where / is
MOST_PACKED = 64 * 1024 * 1024
MOST_UNPACKED = 256 * 1024 * 1024
MOST_FILES = 5000
INSTALL_LIMIT_S = 20 * 60      # under TimeoutStartSec=25min
TOP = re.compile(r'^zigmon-([0-9]+(?:\.[0-9]+){2,3})$')
# what an upgrade replaces, and what goes back when the new one does not answer
PROGRAM = (LIB_DIR, WEB_DIR)
PROGRAM_UNITS = ('zigmon.service', 'zigmon-root.path', 'zigmon-root.service',
                 'zigmon-upgrade.path', 'zigmon-upgrade.service')


class Refused(Exception):
    pass


# The upgrade folder, opened once and used by its descriptor from then on:
# the zigmon account owns /var/lib/zigmon, and could otherwise swap the
# folder for a link to anywhere between two steps of root's.
UP_FD = [None]


def up_fd():
    if UP_FD[0] is not None:
        return UP_FD[0]
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    top = os.open(STATE_DIR, flags)
    try:
        fd = os.open('upgrade', flags, dir_fd=top)
    finally:
        os.close(top)
    UP_FD[0] = fd
    return fd


def _where(path):
    """(dir_fd, name) for a path in the upgrade folder, (None, path) else."""
    if os.path.dirname(path) == UPGRADE_DIR:
        return up_fd(), os.path.basename(path)
    return None, path


def version_tuple(v):
    return tuple(int(x) for x in str(v).split('.'))


def installed_version():
    try:
        with open(os.path.join(LIB_DIR, 'zigmon.py'), encoding='utf-8') as f:
            for line in f:
                m = re.match(r"^__version__ = '([0-9.]+)'", line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return ''


# ---- going back to an older version (5.22) ------------------------------------------
# Going back puts the older program in and leaves the database as it is: it can
# be terabytes of readings, and copying it or putting a copy back is not what
# anybody wants for "the new version misbehaves, give me last week's". That is
# safe only while the older version reads the database as this one left it.
# zigmon's database only ever grows - tables and columns added, nothing taken
# away or read differently - except at the versions below, where an older one
# would read it wrongly. Going back across one of them is refused; a version
# that changes the database so must be added here, with the reason in words.
#
# The highest version that ever ran on the database counts, not only the one
# installed: a database a newer zigmon wrote to, run since by an older one,
# still holds what the newer one put there. The daemon keeps it in its meta
# table (version_high).
DB_EPOCHS = (
    ('5.19.0', 'the accounts of the dashboard: an older version has no sign-in by name and '
               'password, and would open the house to anybody holding the old PIN'),
    ('5.19.1', 'PIN accounts: an older version would take an account\'s short PIN as its password'),
)
# What an install of a newer version puts on the machine that an older one
# does not know of, and which would be in the way once it runs: taken away
# when going back below the version that brought it. (What the older
# install.sh puts in itself - its units, its helpers - it puts in over these.)
AWAY_BELOW = (
    ('5.21.0', ('/etc/profile.d/zz-zigmon-console.sh',),
     'the console at login - an older zigmon has no console, and root\'s login would '
     'say so every time'),
)


def db_file_path():
    p = str(config_values().get('db_file') or '').strip()
    return p if p.startswith('/') else os.path.join(STATE_DIR, 'history.db')


def db_version_high():
    """The highest version that has run on the database, as it says itself:
    one row read, the database opened read-only - its size does not matter."""
    import sqlite3
    try:
        con = sqlite3.connect('file:%s?mode=ro' % db_file_path(), uri=True, timeout=10)
        try:
            row = con.execute("SELECT value FROM meta WHERE key = 'version_high'").fetchone()
        finally:
            con.close()
        v = str(row[0] if row else '').strip()
        return v if re.match(r'^[0-9]+(\.[0-9]+){2,3}$', v) else ''
    except Exception:                                    # noqa: BLE001 - no row is no answer
        return ''


def downgrade_check(target, installed, high=''):
    """Whether going back from `installed` to `target` is safe, and why not.
    Returns {'ok', 'why', 'floor', 'high', 'away'}."""
    high = max([v for v in (installed, high) if v] or ['0.0.0'], key=version_tuple)
    out = {'ok': False, 'why': '', 'floor': '', 'high': high, 'away': []}
    if not installed or version_tuple(target) >= version_tuple(installed):
        out['why'] = '%s is not older than %s, which is installed' % (target, installed or '?')
        return out
    crossed = [(v, why) for v, why in DB_EPOCHS
               if version_tuple(target) < version_tuple(v) <= version_tuple(high)]
    floors = [v for v, _w in DB_EPOCHS if version_tuple(v) <= version_tuple(high)]
    out['floor'] = max(floors, key=version_tuple) if floors else ''
    if crossed:
        v, why = crossed[-1]
        out['why'] = ('the database changed at %s (%s): %s would read it wrongly - %s is as far '
                      'back as it goes without putting a backup of the database back'
                      % (v, why, target, out['floor']))
        return out
    out['away'] = [{'below': v, 'paths': list(paths), 'what': what} for v, paths, what in AWAY_BELOW
                   if version_tuple(target) < version_tuple(v)]
    out['ok'] = True
    return out


def put_away(away, say):
    """What the older version does not know of, taken away once it answers."""
    for one in away:
        for path in one['paths']:
            path = FS_ROOT + path
            try:
                st = os.lstat(path)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
                os.unlink(path)
                say('taken away: %s (%s)' % (path, one['what']))


def trusted_keys():
    try:
        names = sorted(n for n in os.listdir(KEYS_DIR) if n.endswith('.pub'))
    except OSError:
        names = []
    return [os.path.join(KEYS_DIR, n) for n in names]


def signed_by(manifest, signature):
    """The name of the trusted key that signed MANIFEST, or None."""
    for key in trusted_keys():
        try:
            r = subprocess.run(['openssl', 'pkeyutl', '-verify', '-pubin', '-inkey', key,
                                '-rawin', '-in', manifest, '-sigfile', signature],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        except (OSError, subprocess.SubprocessError):
            raise Refused('openssl is needed to check the signature, and it did not run')
        if r.returncode == 0:
            return os.path.basename(key)[:-4]
    return None


def inspect(path, extract_to=None):
    """Everything about a package that can be said without trusting it - and
    with extract_to, the package unpacked there once it has passed."""
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise Refused('the package cannot be read: %s' % e)
    if size > MOST_PACKED:
        raise Refused('the package is bigger than 64 MB, which no version of zigmon is')
    try:
        tar = tarfile.open(path, 'r:gz')
    except (tarfile.TarError, OSError, EOFError) as e:
        raise Refused('that is not a .tar.gz: %s' % e)
    with tar:
        members = []
        try:
            while True:
                one = tar.next()
                if one is None:
                    break
                members.append(one)
                if len(members) > MOST_FILES:
                    break
        except (tarfile.TarError, OSError, EOFError) as e:
            raise Refused('the package is damaged: %s' % e)
        if not members or len(members) > MOST_FILES:
            raise Refused('the package holds no files, or far too many')
        top = members[0].name.split('/')[0]
        m = TOP.match(top)
        if not m:
            raise Refused('the package is not a zigmon release: its folder is "%s", not zigmon-X.Y.Z'
                          % top[:80])
        version = m.group(1)
        files, total = {}, 0
        for one in members:
            name = one.name
            parts = name.split('/')
            if name.startswith('/') or '..' in parts or parts[0] != top or '\\' in name:
                raise Refused('the package has a path outside its folder: %s' % name[:120])
            if one.isdir():
                continue
            if not one.isreg():
                raise Refused('the package holds something that is not a plain file: %s'
                              % name[:120])
            total += one.size
            if total > MOST_UNPACKED:
                raise Refused('the package unpacks to more than 256 MB')
            rel = '/'.join(parts[1:])
            if rel in files:
                raise Refused('the package holds %s twice' % rel)
            files[rel] = one
        for need in ('MANIFEST', 'MANIFEST.sig', 'zigmon.py', 'install.sh'):
            if need not in files:
                raise Refused('the package has no %s%s' % (
                    need, ' - it is not signed' if need.startswith('MANIFEST') else ''))
        work = tempfile.mkdtemp(prefix='zigmon-inspect-')
        try:
            man = os.path.join(work, 'MANIFEST')
            sig = os.path.join(work, 'MANIFEST.sig')
            for rel, dest in (('MANIFEST', man), ('MANIFEST.sig', sig)):
                if files[rel].size > 4 * 1024 * 1024:
                    raise Refused('%s is far too big' % rel)
                with tar.extractfile(files[rel]) as src, open(dest, 'wb') as out:
                    out.write(src.read())
            if not trusted_keys():
                raise Refused('no release key is installed on this machine (%s): upgrade once '
                              'on the command line with install.sh --upgrade' % KEYS_DIR)
            who = signed_by(man, sig)
            if not who:
                raise Refused('the signature is not by any release key this machine trusts - '
                              'a package that was changed, or signed by an unknown key. Put it '
                              'in on the command line (install.sh --upgrade) if you trust it.')
            listed = {}
            with open(man, encoding='utf-8') as f:
                for line in f:
                    line = line.rstrip('\n')
                    if not line.strip():
                        continue
                    mm = re.match(r'^([0-9a-f]{64})  (.+)$', line)
                    if not mm:
                        raise Refused('MANIFEST has a line that does not read')
                    listed[mm.group(2)] = mm.group(1)
            have = set(files) - {'MANIFEST', 'MANIFEST.sig'}
            if set(listed) != have:
                extra = sorted(have - set(listed))[:3]
                missing = sorted(set(listed) - have)[:3]
                raise Refused('the files are not the ones signed for%s%s' % (
                    (' - not signed: ' + ', '.join(extra)) if extra else '',
                    (' - missing: ' + ', '.join(missing)) if missing else ''))
            changelog = ''
            zig_version = ''
            for rel in sorted(have):
                h = hashlib.sha256()
                keep = rel in ('README.md', 'zigmon.py')
                body = []
                with tar.extractfile(files[rel]) as src:
                    while True:
                        lump = src.read(1 << 20)
                        if not lump:
                            break
                        h.update(lump)
                        if keep:
                            body.append(lump)
                if h.hexdigest() != listed[rel]:
                    raise Refused('%s is not the file that was signed' % rel)
                if rel == 'zigmon.py':
                    mm = re.search(rb"^__version__ = '([0-9.]+)'", b''.join(body), re.M)
                    zig_version = mm.group(1).decode() if mm else ''
                if rel == 'README.md':
                    text = b''.join(body).decode('utf-8', 'replace')
                    mm = re.search(r'^%s\s+—.*?(?=^\d+\.\d+\.\d+\s+—|\Z)' % re.escape(version),
                                   text, re.M | re.S)
                    changelog = mm.group(0).strip()[:20000] if mm else ''
            if zig_version != version:
                raise Refused('the folder says %s and zigmon.py says %s' % (version, zig_version))
            if extract_to:
                for one in members:
                    target = os.path.join(extract_to, one.name)
                    if one.isdir():
                        os.makedirs(target, mode=0o755, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(target), mode=0o755, exist_ok=True)
                    with tar.extractfile(one) as src, open(target, 'xb') as out:
                        shutil.copyfileobj(src, out)
                    os.chmod(target, 0o755 if one.mode & 0o111 else 0o644)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    have_v = installed_version()
    out = {'version': version, 'top': top, 'files': len(have), 'signed_by': who,
           'bytes': size, 'changelog': changelog, 'installed': have_v,
           'newer': not have_v or version_tuple(version) > version_tuple(have_v),
           'older': bool(have_v) and version_tuple(version) < version_tuple(have_v)}
    if out['older']:
        # whether going back to it is safe, said before anybody asks
        out['back'] = downgrade_check(version, have_v, db_version_high())
    return out


# ---- writing where zigmon may also write: never through a link ---------------
def write_safely(path, data, mode=0o640):
    dfd, name = _where(path)
    folder = os.path.dirname(path)
    for n in range(50):
        tmpname = '.%s.%d.%d' % (os.path.basename(path), os.getpid(), n)
        tmp = tmpname if dfd is not None else os.path.join(folder, tmpname)
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode,
                         dir_fd=dfd)
        except FileExistsError:
            continue
        with os.fdopen(fd, 'wb') as out:
            out.write(data if isinstance(data, bytes) else data.encode('utf-8'))
            try:
                os.fchown(out.fileno(), 0, grp.getgrnam(SERVICE_USER).gr_gid)
            except (OSError, KeyError):
                pass
        os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
        return
    raise OSError('could not write %s' % path)


def read_small(path, most=65536):
    dfd, name = _where(path)
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise Refused('%s is not a file' % path)
    with os.fdopen(fd, 'rb') as f:
        return f.read(most + 1)[:most]


def status(**fields):
    fields['at'] = time.time()
    write_safely(os.path.join(UPGRADE_DIR, 'status.json'), json.dumps(fields))


# ---- the program as it is, to go back to ----------------------------------------
def keep_program(work):
    """A copy of the program as it is now - the library, the dashboard and the
    units - for when the new one does not answer."""
    out = os.path.join(work, 'previous.tar')
    with tarfile.open(out, 'w') as tar:
        for d in PROGRAM:
            if os.path.isdir(d):
                tar.add(d, arcname=d.lstrip('/'))
        for u in PROGRAM_UNITS:
            p = os.path.join(UNITS, u)
            if os.path.isfile(p):
                tar.add(p, arcname=p.lstrip('/'))
    return out


def put_program_back(saved, say):
    """The program as it was before the upgrade: what install.sh put in is
    taken away and the copy unpacked in its place."""
    for d in PROGRAM:
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    with tarfile.open(saved) as tar:
        for m in tar.getmembers():
            # only what keep_program put in, and only where it came from: a
            # plain file or a folder under the program's own folders or a unit
            if m.name.startswith('/') or '..' in m.name.split('/'):
                continue
            dest = '/' + m.name
            if not (any(dest == d or dest.startswith(d + '/') for d in PROGRAM) or
                    os.path.dirname(dest) == UNITS):
                continue
            if m.isdir():
                os.makedirs(dest, mode=0o755, exist_ok=True)
                os.chmod(dest, m.mode & 0o755)
            elif m.isreg():
                os.makedirs(os.path.dirname(dest), mode=0o755, exist_ok=True)
                with tar.extractfile(m) as src, open(dest + '.zigmon-back', 'wb') as out:
                    shutil.copyfileobj(src, out)
                os.chmod(dest + '.zigmon-back', m.mode & 0o755)
                os.replace(dest + '.zigmon-back', dest)
    say('the program put back as it was before the upgrade')
    if not NO_SERVICES:
        subprocess.run(['systemctl', 'daemon-reload'], capture_output=True)
        subprocess.run(['systemctl', 'restart', 'zigmon'], capture_output=True)
        if shutil.which('restorecon'):
            for d in PROGRAM:
                subprocess.run(['restorecon', '-R', d], capture_output=True)
    say('zigmon restarted on the version it had')


def config_values():
    try:
        with open(CONFIG_FILE) as f:
            got = json.load(f)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def answers(version, say):
    """Does the version just put in answer: running, its API up, saying it is
    `version`? Asked for up to HEALTH_WAIT_S - the daemon reads its database
    and its configuration at start, which on a big house takes a while."""
    if NO_SERVICES and not os.environ.get('ZIGMON_HEALTH_URL'):
        return True, 'not asked (tests)'
    cfg = config_values()
    url = os.environ.get('ZIGMON_HEALTH_URL') or 'http://%s:%s/api/health' % (
        cfg.get('api_host') or '127.0.0.1', int(cfg.get('api_port') or 9849))
    token_file = cfg.get('token_file') or '/run/zigmon/api-token'
    deadline = time.time() + HEALTH_WAIT_S
    last = 'it did not answer'
    while time.time() < deadline:
        if not NO_SERVICES:
            if subprocess.run(['systemctl', 'is-active', '--quiet', 'zigmon']).returncode != 0:
                last = 'zigmon is not running'
                time.sleep(2)
                continue
        try:
            token = open(token_file).read().strip()
        except OSError:
            token = ''
        try:
            req = urllib.request.Request(url, headers={'X-Zigmon-Token': token})
            with urllib.request.urlopen(req, timeout=5) as r:
                got = json.loads(r.read().decode('utf-8'))
            if str(got.get('version')) == version:
                return True, 'zigmon %s answers' % version
            last = 'it answers as %s, not %s' % (got.get('version'), version)
        except Exception as e:                       # noqa: BLE001 - said in the end
            last = 'its API does not answer (%s)' % str(e)[:120]
        time.sleep(2)
    return False, last


def before_backup(version, say):
    """A backup of the whole installation, before anything is changed."""
    helper = os.path.join(LIB_DIR, 'zigmon_root.py')
    if not os.path.isfile(helper):
        say('no backup of the whole installation first: %s is not there yet' % helper)
        return
    got = subprocess.run([sys.executable, '-I', helper, '--backup', '--why',
                          'before the upgrade to %s' % version], capture_output=True, text=True)
    if got.returncode != 0:
        raise Refused('the backup before the upgrade failed, so nothing was changed: %s'
                      % (got.stderr or got.stdout).strip()[-300:])
    say('a backup of the whole installation first: %s' % got.stdout.strip()[:200])


def put_in(package, ident='', want_sha='', by='the command line', log_to=None, step=None,
           downgrade=False):
    """Check the package, keep what is there, run its install.sh --upgrade,
    and go back when the new one does not answer. Returns (rc, info, lines).
    `downgrade`: an older version asked for on purpose - checked against
    DB_EPOCHS here again, whatever the daemon said, and without a backup of
    the whole installation: the database is not touched, and what is kept to
    put back is the program."""
    if os.geteuid() != 0 and not os.environ.get('ZIGMON_UPGRADE_TEST'):
        raise Refused('putting a version in takes root')
    os.makedirs(OWN_DIR, mode=0o700, exist_ok=True)
    work = tempfile.mkdtemp(prefix='zigmon-upgrade-', dir=OWN_DIR)
    os.chmod(work, 0o700)
    lines = []

    def say(text):
        lines.append(text)
        if log_to:
            log_to(text)

    def at(name):
        if step:
            step(name)
    try:
        copy = os.path.join(work, 'package.tar.gz')
        pfd, pname = _where(package)
        fd = os.open(pname, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=pfd)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise Refused('the package is not a plain file')
        with os.fdopen(fd, 'rb') as src, open(copy, 'xb') as out:
            n = 0
            h = hashlib.sha256()
            while True:
                lump = src.read(1 << 20)
                if not lump:
                    break
                n += len(lump)
                if n > MOST_PACKED:
                    raise Refused('the package is bigger than 64 MB')
                h.update(lump)
                out.write(lump)
        if want_sha and h.hexdigest() != want_sha:
            raise Refused('the package is not the one that was checked on the dashboard '
                          '(its SHA-256 differs)')
        unpacked = os.path.join(work, 'x')
        os.makedirs(unpacked, mode=0o700)
        info = inspect(copy, extract_to=unpacked)
        back = None
        if info['older'] and not downgrade:
            raise Refused('%s is older than %s, which is installed: that is going back, asked for '
                          'as such (Upgrades - Going back, or --downgrade)'
                          % (info['version'], info['installed']))
        if downgrade:
            back = downgrade_check(info['version'], info['installed'], db_version_high())
            if not back['ok']:
                raise Refused('not going back: %s' % back['why'])
        say('zigmon %s, signed by %s, %d files - checked' % (info['version'], info['signed_by'],
                                                            info['files']))
        at('backup')
        if back:
            say('going back from %s to %s: the database is left as it is (the highest version '
                'it has seen is %s, and nothing between changed how it is read) - no backup of '
                'it is made, and none is put back' % (info['installed'], info['version'], back['high']))
        else:
            before_backup(info['version'], say)
        saved = keep_program(work)
        say('the program as it is kept, to go back to (%d MB)' % (os.path.getsize(saved) // 1048576))
        src = os.path.join(unpacked, info['top'])
        env = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
               'LANG': 'C.UTF-8', 'ZIGMON_UPGRADE_FROM_PAGES': '1', 'TERM': 'dumb',
               'ZIGMON_UPGRADE_BY': str(by)[:100]}
        at('installing')
        say('running %s/install.sh --upgrade --yes' % info['top'])
        p = subprocess.Popen(['bash', os.path.join(src, 'install.sh'), '--upgrade', '--yes'],
                             cwd=src, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        late = []

        def too_long():
            late.append(1)
            try:
                p.kill()
            except OSError:
                pass
        dog = threading.Timer(INSTALL_LIMIT_S, too_long)
        dog.daemon = True
        dog.start()

        def stopped(_sig, _frame):
            too_long()
            raise Refused('zigmon-upgrade.service was stopped while install.sh ran')
        signal.signal(signal.SIGTERM, stopped)
        try:
            for raw in p.stdout:
                say(re.sub(r'\x1b\[[0-9;]*m', '', raw.decode('utf-8', 'replace').rstrip('\n')))
            rc = p.wait()
        finally:
            dog.cancel()
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
        if late:
            say('install.sh did not finish in %d min and was stopped' % (INSTALL_LIMIT_S // 60))
            rc = rc or -9
        say('install.sh ended with %d' % rc)
        at('checking')
        ok, why = (False, 'install.sh failed') if rc != 0 else answers(info['version'], say)
        say(why)
        if ok and back:
            put_away(back['away'], say)
        if not ok:
            at('rolling back')
            put_program_back(saved, say)
            back, why_back = answers(info['installed'], say) if info['installed'] else (False, '')
            if info['installed']:
                say(why_back if back else 'the version put back does not answer either: %s' % why_back)
            return (rc or 1), dict(info, rolled_back=True, why=why), lines
        return 0, info, lines
    finally:
        shutil.rmtree(work, ignore_errors=True)


def serve_request():
    """What systemd starts when request.json appears."""
    taken = os.path.join(UPGRADE_DIR, 'request.taken')
    try:
        dfd = up_fd()
        os.replace('request.json', 'request.taken', src_dir_fd=dfd, dst_dir_fd=dfd)
    except FileNotFoundError:
        return 0
    ident = ''
    log_path = os.path.join(UPGRADE_DIR, 'last.log')
    log_lines = []
    last_flush = [0.0]
    now = {'step': 'checking the package', 'version': ''}

    def log_to(text):
        log_lines.append(text)
        if time.time() - last_flush[0] > 2:
            last_flush[0] = time.time()
            try:
                write_safely(log_path, '\n'.join(log_lines[-4000:]) + '\n')
                status(id=ident, state='running', step=now['step'], version=now['version'],
                       pid=os.getpid(), tail=log_lines[-12:])
            except OSError:
                pass

    def step(name):
        now['step'] = name
        try:
            status(id=ident, state='running', step=name, version=now['version'], pid=os.getpid(),
                   tail=log_lines[-12:])
        except OSError:
            pass
    try:
        try:
            r = json.loads(read_small(taken).decode('utf-8'))
        except (ValueError, OSError) as e:
            raise Refused('the request does not read: %s' % e)
        if not isinstance(r, dict):
            raise Refused('the request is not an object')
        ident = re.sub(r'[^A-Za-z0-9]', '', str(r.get('id') or ''))[:64]
        name = os.path.basename(str(r.get('file') or ''))
        if not re.match(r'^zigmon-[0-9.]+\.tar\.gz$', name):
            raise Refused('the request names no package')
        now['version'] = re.sub(r'[^0-9.]', '', str(r.get('version') or ''))[:20]
        status(id=ident, state='running', step='checking the package', version=now['version'],
               pid=os.getpid())
        rc, info, _ = put_in(os.path.join(UPGRADE_DIR, name), ident,
                             re.sub(r'[^0-9a-f]', '', str(r.get('sha') or ''))[:64],
                             str(r.get('by') or 'the dashboard')[:100], log_to, step,
                             downgrade=r.get('downgrade') is True)
        if info.get('rolled_back'):
            status(id=ident, state='failed', rc=rc, version=info['version'], rolled_back=True,
                   said='zigmon %s was put in but %s - the version before it is back'
                        % (info['version'], info.get('why') or 'did not answer'),
                   tail=log_lines[-40:])
        else:
            status(id=ident, state='done' if rc == 0 else 'failed', rc=rc,
                   version=info['version'], tail=log_lines[-40:])
    except Refused as e:
        log_to('refused: %s' % e)
        status(id=ident, state='failed', rc=-1, said=str(e), tail=log_lines[-40:])
    except Exception as e:                       # noqa: BLE001 - said, never lost
        log_to('broke: %s' % e)
        status(id=ident, state='failed', rc=-2, said='the upgrade broke: %s' % e,
               tail=log_lines[-40:])
    finally:
        last_flush[0] = 0
        try:
            write_safely(log_path, '\n'.join(log_lines[-4000:]) + '\n')
        except OSError:
            pass
        try:
            os.unlink('request.taken', dir_fd=up_fd())
        except (OSError, Refused):
            pass
    return 0


def main(argv):
    if len(argv) >= 2 and argv[0] == '--inspect':
        try:
            print(json.dumps(dict(inspect(argv[1]), ok=True)))
        except Refused as e:
            print(json.dumps({'ok': False, 'said': str(e)}))
        return 0
    if len(argv) >= 2 and argv[0] == '--run':
        try:
            rc, info, _ = put_in(os.path.abspath(argv[1]), log_to=print,
                                 downgrade='--downgrade' in argv[2:])
        except Refused as e:
            print('refused: %s' % e)
            return 1
        return rc
    if not argv:
        return serve_request()
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
