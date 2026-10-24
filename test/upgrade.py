#!/usr/bin/env python3
"""A new version put in from the dashboard (5.18): deploy/zigmon_upgrade.py
against a folder that stands in for the machine, with a release key of the
test's own.

  * a package signed by a trusted key is taken, and says what it is and what
    changed in it;
  * one changed after it was signed, one not signed, one signed by a key the
    machine does not know, one with a file nobody signed for, a link or a path
    outside its folder, and one older than what runs - each refused;
  * put in: install.sh runs, the new version is asked whether it answers;
  * the new version does not answer, or install.sh fails: the program as it
    was is put back, and the dashboard is told why;
  * the backup before an upgrade fails: nothing is changed at all.

    python3 test/upgrade.py
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
HELPER = HERE / 'deploy' / 'zigmon_upgrade.py'
W = Path(tempfile.mkdtemp(prefix='zigmon-upgrade-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ---- the machine, with zigmon 5.17.0 on it --------------------------------------
LIB, WEB, KEYS = W / 'lib' / 'zigmon', W / 'www' / 'zigmon', W / 'lib' / 'zigmon' / 'release-keys'
STATE, UNITS = W / 'state', W / 'units'
for d in (KEYS, WEB, STATE / 'upgrade', UNITS):
    d.mkdir(parents=True)
OLD_PY = "#!/usr/bin/python3\n__version__ = '5.17.0'\nprint('the old one')\n"
(LIB / 'zigmon.py').write_text(OLD_PY)
(WEB / 'index.php').write_text('<?php // the old page\n')
(UNITS / 'zigmon.service').write_text('[Service]\nExecStart=old\n')
key = W / 'release.key'
sh(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', str(key)])
sh(['openssl', 'pkey', '-in', str(key), '-pubout', '-out', str(KEYS / 'zigmon-release-test.pub')])
stranger = W / 'stranger.key'
sh(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', str(stranger)])
OLD_SUM = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (LIB / 'zigmon.py', WEB / 'index.php',
                                                                   UNITS / 'zigmon.service')}

# the version the stand-in for the daemon says it is, as /api/health would
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
ENV = dict(os.environ, ZIGMON_STATE=str(STATE), ZIGMON_LIB=str(LIB), ZIGMON_WEB=str(WEB),
           ZIGMON_RELEASE_KEYS=str(KEYS), ZIGMON_ROOT_OWN=str(W / 'own'),
           ZIGMON_UNITS=str(UNITS), ZIGMON_NO_SERVICES='1', ZIGMON_HEALTH_WAIT_S='3',
           ZIGMON_HEALTH_URL='http://127.0.0.1:%d/api/health' % srv.server_address[1],
           ZIGMON_UPGRADE_TEST='1', ZIGMON_USER='root', ZIGMON_CONFIG=str(W / 'config.json'))


def package(version, install='ok', sign_with=None, tamper=None, extra=None, member=None,
            name=None, unsigned=False):
    """A release folder: zigmon.py of `version`, a README with its entry, an
    install.sh that puts the new zigmon.py in (or fails), signed."""
    top = 'zigmon-%s' % version
    d = W / 'build' / (name or top) / top
    if d.parent.exists():
        shutil.rmtree(d.parent)
    d.mkdir(parents=True)
    (d / 'zigmon.py').write_text("#!/usr/bin/python3\n__version__ = '%s'\n" % version)
    (d / 'README.md').write_text('Current version: **%s**\n\n%s — a test release.\n\nIt changed '
                                 'this.\n\n5.17.0 — the one before.\n\nOlder words.\n' % (version, version))
    script = {'ok': 'install -m 755 zigmon.py %s/zigmon.py && echo "==> Program files"\n'
                    'echo "<?php // the new page" > %s/index.php\n' % (LIB, WEB),
              'fail': 'echo "==> Program files"; echo "half done" > %s/zigmon.py; exit 3\n' % LIB}[install]
    (d / 'install.sh').write_text('#!/bin/bash\nset -e\ncd "$(dirname "$0")"\n' + script)
    (d / 'deploy').mkdir()
    (d / 'deploy' / 'zigmon.service').write_text('[Service]\nExecStart=new\n')
    lines = []
    for p in sorted(x for x in d.rglob('*') if x.is_file()):
        rel = p.relative_to(d).as_posix()
        lines.append('%s  %s' % (hashlib.sha256(p.read_bytes()).hexdigest(), rel))
    (d / 'MANIFEST').write_text('\n'.join(lines) + '\n')
    if not unsigned:
        sh(['openssl', 'pkeyutl', '-sign', '-inkey', str(sign_with or key), '-rawin',
            '-in', str(d / 'MANIFEST'), '-out', str(d / 'MANIFEST.sig')])
    if tamper:
        (d / tamper).write_text((d / tamper).read_text() + '# changed after signing\n')
    if extra:
        (d / extra).write_text('not signed for\n')
    out = W / 'build' / ('%s.tar.gz' % (name or top))
    with tarfile.open(out, 'w:gz') as t:
        t.add(d, arcname=top)
        if member:
            t.addfile(member[0], io.BytesIO(member[1]) if member[1] is not None else None)
    return out


def inspect(path):
    got = sh([sys.executable, '-I', str(HELPER), '--inspect', str(path)], env=ENV)
    return json.loads(got.stdout or '{}')


# ---- the checks of a package ---------------------------------------------------
print('checking a package')
good = package('5.18.0')
got = inspect(good)
check(got.get('ok') and got.get('version') == '5.18.0' and got.get('signed_by') == 'zigmon-release-test'
      and got.get('newer') is True, 'a good package was not taken: %r' % got)
check('a test release' in (got.get('changelog') or '') and 'Older words' not in (got.get('changelog') or ''),
      'what changed in the version is not its own entry: %r' % got.get('changelog'))
for what, kw, words in (
        ('changed after signing', {'tamper': 'install.sh', 'name': 't1'}, 'not the file that was signed'),
        ('not signed', {'unsigned': True, 'name': 't2'}, 'not signed'),
        ('signed by a stranger', {'sign_with': stranger, 'name': 't3'}, 'not by any release key'),
        ('with a file nobody signed for', {'extra': 'extra.sh', 'name': 't4'}, 'not signed: extra.sh'),
        ('with a link', {'member': (tarfile.TarInfo('zigmon-5.18.0/evil'), None), 'name': 't5'}, 'not a plain file'),
        ('with a path outside it', {'member': (tarfile.TarInfo('zigmon-5.18.0/../../etc/x'), b''), 'name': 't6'},
         'outside its folder')):
    if kw.get('member') and 'link' in what:
        kw['member'][0].type, kw['member'][0].linkname = tarfile.SYMTYPE, '/etc/shadow'
    got = inspect(package('5.18.0', **kw))
    check(got.get('ok') is False and words in (got.get('said') or ''),
          'a package %s was not refused as it should be: %r' % (what, got))
older = package('5.16.0', name='older')
got = sh([sys.executable, '-I', str(HELPER), '--run', str(older)], env=ENV)
check(got.returncode != 0 and 'older than 5.17.0' in got.stdout, 'an older version was put in: %s' % got.stdout)
check(all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in OLD_SUM.items()),
      'a refused package changed the program')

# ---- put in, through the request the dashboard makes ------------------------------
print('putting it in')


def serve(pkg, version):
    shutil.copy(pkg, STATE / 'upgrade' / ('zigmon-%s.tar.gz' % version))
    sha = hashlib.sha256(pkg.read_bytes()).hexdigest()
    (STATE / 'upgrade' / 'request.json').write_text(json.dumps(
        {'id': 'u1', 'file': 'zigmon-%s.tar.gz' % version, 'version': version, 'sha': sha, 'by': 'a test'}))
    sh([sys.executable, '-I', str(HELPER)], env=ENV)
    return json.loads((STATE / 'upgrade' / 'status.json').read_text())


# the new version never answers: the old program comes back
SAYS['version'] = '5.17.0'
st = serve(good, '5.18.0')
check(st.get('state') == 'failed' and st.get('rolled_back') is True,
      'a version that did not answer was left in: %r' % st)
check(all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in OLD_SUM.items()),
      'after a version that did not answer, the program is not as it was')
check('answers as 5.17.0' in ' '.join(st.get('tail') or []) or 'did not answer' in st.get('said', ''),
      'the dashboard is not told why it went back: %r' % st.get('said'))
log = (STATE / 'upgrade' / 'last.log').read_text()
check('the program put back as it was' in log, 'the log does not say the program was put back')

# install.sh fails half way: the old program comes back
st = serve(package('5.18.0', install='fail', name='failing'), '5.18.0')
check(st.get('state') == 'failed' and st.get('rolled_back') is True, 'a failed install.sh was left as it was: %r' % st)
check((LIB / 'zigmon.py').read_text() == OLD_PY, 'a failed install.sh left the program half done')

# a package swapped after the dashboard checked it
shutil.copy(good, STATE / 'upgrade' / 'zigmon-5.18.0.tar.gz')
(STATE / 'upgrade' / 'request.json').write_text(json.dumps(
    {'id': 'u2', 'file': 'zigmon-5.18.0.tar.gz', 'version': '5.18.0', 'sha': '0' * 64}))
sh([sys.executable, '-I', str(HELPER)], env=ENV)
st = json.loads((STATE / 'upgrade' / 'status.json').read_text())
check(st.get('state') == 'failed' and 'SHA-256 differs' in st.get('said', ''),
      'a package other than the one checked was put in: %r' % st)

# the backup before it fails: nothing changes
(LIB / 'zigmon_root.py').write_text('import sys\nprint("the disk is full", file=sys.stderr)\nsys.exit(1)\n')
st = serve(good, '5.18.0')
check(st.get('state') == 'failed' and 'backup before the upgrade failed' in st.get('said', ''),
      'an upgrade went on without its backup: %r' % st)
check((LIB / 'zigmon.py').read_text() == OLD_PY, 'an upgrade without its backup changed the program')
(LIB / 'zigmon_root.py').write_text('print("zigmon-full-x.tar.gz (1 MB): database")\n')

# and the one that answers
SAYS['version'] = '5.18.0'
st = serve(good, '5.18.0')
check(st.get('state') == 'done' and st.get('version') == '5.18.0', 'a good upgrade did not go through: %r' % st)
check("__version__ = '5.18.0'" in (LIB / 'zigmon.py').read_text() and 'new page' in (WEB / 'index.php').read_text(),
      'the new version is not in place')
log = (STATE / 'upgrade' / 'last.log').read_text()
check('a backup of the whole installation first' in log and 'zigmon 5.18.0 answers' in log,
      'the log does not say the backup was made and the new version answers:\n' + log)
check(not list((W / 'own').glob('zigmon-upgrade-*')), 'the work folder was left behind')

# the request itself as a link: not followed
(STATE / 'upgrade' / 'request.json').unlink(missing_ok=True)
os.symlink(W / 'build', STATE / 'upgrade' / 'request.json')
sh([sys.executable, '-I', str(HELPER)], env=ENV)
st = json.loads((STATE / 'upgrade' / 'status.json').read_text())
check(st.get('state') == 'failed', 'a request that is a link was followed')

srv.shutdown()
shutil.rmtree(W, ignore_errors=True)
if bad:
    print('\n%d check(s) failed' % len(bad))
    sys.exit(1)
print('a new version goes in only signed, and comes out again when it does not answer')
