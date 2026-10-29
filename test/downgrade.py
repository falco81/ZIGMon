#!/usr/bin/env python3
"""Going back to an older version (5.22): the older program put in, the
database left as it is - and only where that is safe.

  * root's helper (deploy/zigmon_upgrade.py) goes back only when asked to: an
    older package sent as an upgrade is refused as before;
  * going back across a version that changed how the database is read
    (DB_EPOCHS) is refused and says why - judged by the highest version that
    ever ran on the database, which the daemon keeps in it, not only by the
    one installed;
  * going back makes no backup of the database and puts none back: the file
    is the same, byte for byte, afterwards - however big it is;
  * what the older version does not know of is taken away (the console at
    login, below 5.21), and only once it answers;
  * the older version does not answer: the program it replaced is put back,
    and nothing is taken away;
  * the daemon offers only what root will do, refuses while a change waits
    to be kept, writes the highest version run, and the page, the command
    line and the console each have a way in.

    python3 test/downgrade.py
"""
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
HELPER = HERE / 'deploy' / 'zigmon_upgrade.py'
W = Path(tempfile.mkdtemp(prefix='zigmon-downgrade-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ---- the machine, with zigmon 5.22.0 on it and a database it has written ------------
LIB, WEB, KEYS = W / 'lib' / 'zigmon', W / 'www' / 'zigmon', W / 'lib' / 'zigmon' / 'release-keys'
STATE, UNITS = W / 'state', W / 'units'
for d in (KEYS, WEB, STATE / 'upgrade', UNITS, W / 'etc' / 'profile.d'):
    d.mkdir(parents=True)
NEW_PY = "#!/usr/bin/python3\n__version__ = '5.22.0'\nprint('the new one')\n"
(LIB / 'zigmon.py').write_text(NEW_PY)
(WEB / 'index.php').write_text('<?php // the new page\n')
(UNITS / 'zigmon.service').write_text('[Service]\nExecStart=new\n')
HOOK = W / 'etc' / 'profile.d' / 'zz-zigmon-console.sh'
HOOK.write_text('# the console at login\n')
DB = STATE / 'history.db'
con = sqlite3.connect(str(DB))
con.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
                  "CREATE TABLE samples (ts INTEGER, device TEXT, key TEXT, value REAL);"
                  "INSERT INTO meta VALUES ('version_high', '5.22.0');")
con.executemany('INSERT INTO samples VALUES (?, ?, ?, ?)', [(i, 'Temp', 'temperature', 20.5)
                                                          for i in range(5000)])
con.commit()
con.close()
DB_SUM = hashlib.sha256(DB.read_bytes()).hexdigest()
(W / 'config.json').write_text(json.dumps({'db_file': str(DB)}))
key = W / 'release.key'
sh(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', str(key)])
sh(['openssl', 'pkey', '-in', str(key), '-pubout', '-out', str(KEYS / 'zigmon-release-test.pub')])
SAYS = {'version': '5.22.0'}


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
           ZIGMON_UPGRADE_TEST='1', ZIGMON_USER='root', ZIGMON_CONFIG=str(W / 'config.json'),
           ZIGMON_FS_ROOT=str(W))


def package(version):
    top = 'zigmon-%s' % version
    d = W / 'build' / top / top
    if d.parent.exists():
        shutil.rmtree(d.parent)
    d.mkdir(parents=True)
    (d / 'zigmon.py').write_text("#!/usr/bin/python3\n__version__ = '%s'\n" % version)
    (d / 'README.md').write_text('Current version: **%s**\n\n%s — an older release.\n' % (version, version))
    (d / 'install.sh').write_text('#!/bin/bash\nset -e\ncd "$(dirname "$0")"\n'
                                  'install -m 755 zigmon.py %s/zigmon.py && echo "==> Program files"\n'
                                  'echo "<?php // the older page" > %s/index.php\n' % (LIB, WEB))
    lines = ['%s  %s' % (hashlib.sha256(p.read_bytes()).hexdigest(), p.relative_to(d).as_posix())
             for p in sorted(x for x in d.rglob('*') if x.is_file())]
    (d / 'MANIFEST').write_text('\n'.join(lines) + '\n')
    sh(['openssl', 'pkeyutl', '-sign', '-inkey', str(key), '-rawin', '-in', str(d / 'MANIFEST'),
        '-out', str(d / 'MANIFEST.sig')])
    out = W / 'build' / ('%s.tar.gz' % top)
    with tarfile.open(out, 'w:gz') as t:
        t.add(d, arcname=top)
    return out


def run(pkg, *extra):
    return sh([sys.executable, '-I', str(HELPER), '--run', str(pkg)] + list(extra), env=ENV)


# ---- the table ------------------------------------------------------------------------
print('what is safe to go back to')
os.environ.update({k: v for k, v in ENV.items() if k.startswith('ZIGMON_')})
spec = importlib.util.spec_from_file_location('zigmon_upgrade_t', str(HELPER))
U = importlib.util.module_from_spec(spec)
spec.loader.exec_module(U)
check(U.db_version_high() == '5.22.0', 'the highest version run is not read from the database: %r'
      % U.db_version_high())
ok = U.downgrade_check('5.20.0', '5.22.0', '5.22.0')
check(ok['ok'] and ok['floor'] == '5.19.1' and [a['below'] for a in ok['away']] == ['5.21.0'],
      'going back to 5.20.0 is not safe, or the console at login is not taken away: %r' % ok)
check(not U.downgrade_check('5.21.0', '5.22.0', '5.22.0')['away'], 'going back to 5.21.0 takes the console away')
for target in ('5.19.0', '5.18.2'):
    no = U.downgrade_check(target, '5.22.0', '5.22.0')
    check(not no['ok'] and 'database' in no['why'], 'going back to %s across the accounts is taken: %r'
          % (target, no))
check(not U.downgrade_check('5.22.0', '5.22.0')['ok'] and not U.downgrade_check('5.23.0', '5.22.0')['ok'],
      'the same version or a newer one is called going back')
U.DB_EPOCHS = U.DB_EPOCHS + (('5.21.5', 'a column read differently'),)
no = U.downgrade_check('5.20.0', '5.22.0', '5.22.0')
check(not no['ok'] and '5.21.5' in no['why'], 'a version that changed the database is crossed: %r' % no)
check(U.downgrade_check('5.21.5', '5.22.0', '5.22.0')['ok'], 'the version that made the change cannot be gone back to')
# the highest version that ran counts: a newer one wrote to it, then went
no = U.downgrade_check('5.20.0', '5.21.0', '5.23.0')
check(not no['ok'], 'a database a newer version wrote is judged only by the version installed')

# ---- root goes back ------------------------------------------------------------------
print('root puts the older version in, and leaves the database alone')
older = package('5.20.0')
got = sh([sys.executable, '-I', str(HELPER), '--inspect', str(older)], env=ENV)
info = json.loads(got.stdout or '{}')
check(info.get('older') and (info.get('back') or {}).get('ok'), 'the check does not say it is safe: %r' % info)
r = run(older)
check(r.returncode != 0 and 'going back' in r.stdout and (LIB / 'zigmon.py').read_text() == NEW_PY,
      'an older package was put in as an upgrade: %s' % r.stdout[-300:])
SAYS['version'] = '5.20.0'
r = run(older, '--downgrade')
check(r.returncode == 0 and "__version__ = '5.20.0'" in (LIB / 'zigmon.py').read_text(),
      'going back did not put 5.20.0 in: %s' % r.stdout[-400:])
check('no backup of it is made' in r.stdout and 'backup of the whole installation first' not in r.stdout,
      'going back made a backup of the database')
check(hashlib.sha256(DB.read_bytes()).hexdigest() == DB_SUM, 'the database was changed by going back')
check(not HOOK.exists() and 'taken away' in r.stdout, 'the console at login was left for a version without one')
# the older one does not answer: the newer program comes back, nothing is taken away
(LIB / 'zigmon.py').write_text(NEW_PY)
HOOK.write_text('# the console at login\n')
SAYS['version'] = '5.22.0'
r = run(older, '--downgrade')
check(r.returncode != 0 and (LIB / 'zigmon.py').read_text() == NEW_PY and HOOK.exists(),
      'an older version that did not answer was left in, or the hook went: %s' % r.stdout[-300:])
check(hashlib.sha256(DB.read_bytes()).hexdigest() == DB_SUM, 'the database was changed by a failed going back')
r = run(package('5.19.0'), '--downgrade')
check(r.returncode != 0 and 'database changed at 5.19.1' in r.stdout and (LIB / 'zigmon.py').read_text() == NEW_PY,
      'going back across the PIN accounts was done: %s' % r.stdout[-300:])

# ---- the daemon ------------------------------------------------------------------------
print('the daemon offers what root will do, and writes the highest version run')
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

(LIB / 'zigmon.py').write_text("__version__ = '%s'\n" % zigmon.__version__)
os.environ['ZIGMON_LIB'] = str(LIB)
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 19863, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'run' / 'api-token'), 'pin': '', 'plugs': [],
                      'sensors': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(STATE),
                      'public_view': True})
os.environ['ZIGMON_CONFIG'] = str(W / 'config-d.json')
(W / 'config-d.json').write_text(json.dumps({'db_file': str(W / 'z.db')}))
d = zigmon.Daemon()
d._stop.set()
check(d.store.get_meta('version_high') == zigmon.__version__, 'the daemon did not write the highest version run')
d.store.set_meta('version_high', '9.9.9')
d.note_version_high()
check(d.store.get_meta('version_high') == '9.9.9', 'a lower version wrote over the highest one run')
d.store.set_meta('version_high', zigmon.__version__)
cur = zigmon._online_ver(zigmon.__version__)
older_v = '%d.%d.%d' % (cur[0], cur[1] - 1, 0)
chk = d.downgrade_check(older_v)
check(chk.get('ok'), 'the daemon does not offer going back one version: %r' % chk)
check(not d.downgrade_check('5.18.0').get('ok'), 'the daemon offers going back across the accounts')
# an older package, sent with back, is the one waiting; sent without, refused
(W / 'build').mkdir(exist_ok=True)
pkg = package(older_v)
tmp = d.upgrade_dir('.upload-x.part')
d.root_folders()
shutil.copy(str(pkg), str(tmp))
try:
    d.upgrade_take(tmp, 'jana')
    check(False, 'an older package sent as an upgrade was taken')
except ValueError as e:
    check('Going back' in str(e), 'the refusal does not say where going back is: %s' % e)
shutil.copy(str(pkg), str(tmp))
got = d.upgrade_take(tmp, 'jana', back=True)
st = d.upgrade_state()
check(got['older'] and st['back'].get('package', {}).get('version') == older_v and st['back'].get('ready')
      is not None and not st['ready'], 'the older package is not waiting to go back to, or is offered as an upgrade')
# not while a change waits to be kept
d.store.set_meta('firewall', json.dumps({'on': False, 'off': [], 'rules': []}))
d.root_apply = lambda *a, **k: None
zigmon.CONFIG['fw_confirm_min'] = 5
d.firewall_save({'on': False, 'rules': []}, '192.168.1.5')
try:
    d.downgrade_start('jana')
    check(False, 'going back was started while a firewall change waited to be kept')
except ValueError as e:
    check('kept' in str(e), 'the refusal does not say a change waits: %s' % e)
d.fw_trial_answer('keep', 'jana')
os.environ['ZIGMON_UPGRADE_RUN'] = 'true'
ident = d.downgrade_start('jana')
req = json.loads(d.upgrade_dir('request.json').read_text())
check(req.get('downgrade') is True and req.get('version') == older_v, 'the request does not ask for going back: %r' % req)
d.upgrade_dir('request.json').unlink()

# ---- the ways in -----------------------------------------------------------------------------
page = (HERE / 'web' / 'index.php').read_text()
check('id="up-back-card"' in page and "back: true" in page and "action: 'downgrade_start'" in page,
      'the page has no way to go back')
src = (HERE / 'zigmon.py').read_text()
check("'--downgrade'" in src and "'--downgrade-check'" in src and 'Going back to an older version' in src,
      'the command line or the console has no way to go back')

d.store.flush(3.0)
srv.shutdown()
shutil.rmtree(W, ignore_errors=True)
sys.stdout.flush()
if bad:
    print('\n%d check(s) failed' % len(bad))
    os._exit(1)
print('going back puts the older program in and leaves the database alone - only where it is safe')
os._exit(0)
