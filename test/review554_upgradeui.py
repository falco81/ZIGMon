#!/usr/bin/env python3
"""5.54: the pages follow an upgrade while the things that serve them restart.

Whoever runs an upgrade - root's helper (deploy/zigmon_upgrade.py) and
install.sh --upgrade, also by hand - writes how far it is into one small file
beside the pages, .upgrade.json, which PHP reads straight from the disk. While
zigmon answers it is merged into the status; while it does not, every relayed
call answers 503 {"upgrading": ...} instead of "not responding", and
?api=upgrade-state answers without zigmon at all. The page shows a band, says
"In maintenance", keeps asking every two seconds and loads the new version
once at the end.

  * PHP's reader: no file, fresh and stale states, a time in the future, a
    state that is none of the three, not JSON, too big, a link, the version
    digits and dots only, every text stripped of control and format
    characters and cut, invalid UTF-8, the parts clamped, read once per
    request; who asked and why it failed only to somebody signed in;
  * install.sh's writer, run in isolation: written whole (no temporary file
    left), 0644, valid JSON whatever the words; a part per step; "done" at the
    end by hand; "failed" with the exit code from the EXIT trap; Ctrl-C, HUP and
    SIGTERM end as failed (130, 129, 143), never "running"; under root's helper
    the end is the helper's; --dry-run writes nothing; a folder that is not
    there or not a folder costs the upgrade nothing; the count of its steps is
    the steps do_upgrade takes;
  * root's helper: taking the request, a bad signature (failed, with why), a
    good one (install.sh gets the numbering, done at the end), install.sh
    failing (failed, the version before runs again), no pages folder at all
    (the upgrade goes through all the same), the command line (--run);
  * the relay: 503 "being upgraded" only while zigmon does not answer AND the
    file is fresh; otherwise exactly what it said before; the status merged;
    /healthz says maintenance; ?api=upgrade-state with and without a sign-in;
  * the page in Chromium (as the kit's sim.js): running - the band, the pill;
    zigmon killed - "not answering for", nothing red; PHP killed and started
    again; zigmon back; done - loaded again once, and only once; failed - a
    red band, its x remembered for that upgrade; signed out in the middle -
    the sign-in page with the band drawn by PHP, loaded again once zigmon
    answers; something not saved - no reload, "Load it again"; no markup from
    the file ever becomes markup.

    python3 test/review554_upgradeui.py

Screenshots into $UPGUI_SHOTS (default: a temporary directory).
Ports 20350 (the daemon), 20351 (php -S), 20352 (the browser's control).
"""
import hashlib
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-upgui-'))
API_PORT, PHP_PORT, CTL_PORT = 20350, 20351, 20352
SHOTS = Path(os.environ.get('UPGUI_SHOTS') or (W / 'shots'))
bad = []
PROCS = {}


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def finish():
    for name in list(PROCS):
        stop(name)
    shutil.rmtree(W, ignore_errors=True)
    print('review554_upgradeui: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
    os._exit(1 if bad else 0)


def stop(name):
    p = PROCS.pop(name, None)
    if p is None:
        return
    # by its own id - the process, or (php -S and its workers) its group
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        p.wait(10)
    except subprocess.TimeoutExpired:
        pass


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


if not shutil.which('php'):
    print('  SKIPPED (no php here)')
    finish()

# ---------------------------------------------------------------------------------------
# 1. PHP's reader
# ---------------------------------------------------------------------------------------
print("PHP reads the file: fresh, stale, odd, stripped")
WEB = W / 'web'
shutil.copytree(HERE / 'web', WEB)
api_php = (WEB / 'zigmon-api.php').read_text()
check("const ZIGMON_PORT  = 9849;" in api_php, 'the port line of zigmon-api.php is not where it was')
api_php = api_php.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
api_php = api_php.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
(WEB / 'zigmon-api.php').write_text(api_php)
UPG = WEB / '.upgrade.json'


def put(obj=None, raw=None):
    if UPG.is_symlink() or UPG.exists():
        UPG.unlink()
    tmp = WEB / '.upgrade.json.writing'
    tmp.write_bytes(raw if raw is not None else json.dumps(obj).encode())
    os.replace(tmp, UPG)


def upg(state='running', ago=5, **kw):
    now = int(time.time())
    row = {'state': state, 'id': 'k1', 'version': '5.99.0', 'from': '5.98.0', 'by': 'owner on the dashboard',
           'part': 3, 'parts': 16, 'words': 'Program files', 'started': now - ago - 60, 'at': now - ago,
           'said': '', 'downgrade': False}
    row.update(kw)
    return row


def php(code):
    script = W / 'probe.php'
    script.write_text("<?php\ndeclare(strict_types=1);\nrequire %s;\n%s\n" % (json.dumps(str(WEB / 'zigmon-api.php')), code))
    got = sh(['php', str(script)])
    try:
        return json.loads(got.stdout)
    except ValueError:
        check(False, 'php said no JSON: %r %r' % (got.stdout[-300:], got.stderr[-300:]))
        return 'broken'


read = "echo json_encode(zigmon_upgrading());"
if UPG.exists():
    UPG.unlink()
check(php(read) is None, 'no file was read as an upgrade')
put(upg())
got = php(read)
check(isinstance(got, dict) and got.get('state') == 'running' and got.get('version') == '5.99.0'
      and got.get('from') == '5.98.0' and got.get('part') == 3 and got.get('parts') == 16
      and got.get('words') == 'Program files' and got.get('by') == 'owner on the dashboard'
      and len(got.get('key') or '') == 16 and got.get('id') == 'k1', 'a fresh running file was not read: %r' % got)
for what, row, believed in (
        ('running 29 min old', upg(ago=1740), True),
        ('running 31 min old', upg(ago=1860), False),
        ('done 9 min old', upg('done', ago=540), True),
        ('done 11 min old', upg('done', ago=660), False),
        ('failed 9 min old', upg('failed', ago=540), True),
        ('failed 11 min old', upg('failed', ago=660), False),
        ('written a minute from now', upg(ago=-60), False),
        ('paused', upg('paused'), False),
        ('no state', dict(upg(), state=None), False),
        ('a state that is a list', dict(upg(), state=['running']), False),
        ('at as a string', dict(upg(), at=str(int(time.time()))), False),
        ('no at', {k: v for k, v in upg().items() if k != 'at'}, False)):
    put(row)
    got = php(read)
    check((isinstance(got, dict)) == believed, '%s: %s' % (what, 'not believed' if believed else 'believed: %r' % got))
for what, raw in (('not JSON', b'{"state": "running", '), ('a list', b'["running"]'), ('empty', b''),
                  ('too big', json.dumps(dict(upg(), words='x' * 9000)).encode()),
                  ('nested too deep', json.dumps(dict(upg(), by={'a': {'b': {'c': {'d': 1}}}})).encode())):
    put(raw=raw)
    got = php(read)
    check(got is None, '%s was read as an upgrade: %r' % (what, got))
# a link to a file that says running: not followed
real = W / 'elsewhere.json'
real.write_text(json.dumps(upg()))
UPG.unlink()
os.symlink(real, UPG)
check(php(read) is None, 'a link was followed')
UPG.unlink()
# every field checked
put(upg(version='5.99.0; rm -rf /', **{'from': '<b>5</b>'}, id='k1<script>', part=40, parts=16,
        words='step\x00one\x1b[31m red‮ evil line' + 'w' * 300, by='b' * 300, said='s\n' * 500,
        started=int(time.time()) + 999, downgrade='yes'))
got = php(read)
check(isinstance(got, dict) and got.get('version') == '' and got.get('from') == '' and got.get('id') == 'k1script'
      and got.get('part') == 16 and got.get('started') == 0 and got.get('downgrade') is False,
      'the fields were not checked: %r' % got)
w = (got or {}).get('words', '')
check(not any(ord(c) < 32 or c in '‮ \x7f' for c in w) and len(w) <= 160 and w.startswith('step one'),
      'words were not stripped and cut: %r' % w)
check(len((got or {}).get('by', '')) <= 100 and len((got or {}).get('said', '')) <= 400
      and '\n' not in (got or {}).get('said', ''), 'by and said were not cut and stripped')
put(raw=json.dumps(upg()).replace('Program files', 'Prog\\u00e9').encode().replace(b'Prog', b'Pr\xff\xfeog'))
got = php(read)
check(isinstance(got, dict) and got.get('state') == 'running', 'a word not in UTF-8 lost the whole file: %r' % got)
put(upg(part=-3, parts='16'))
got = php(read)
check(isinstance(got, dict) and got.get('part') == 0 and got.get('parts') == 0, 'odd parts were taken: %r' % got)
# who asked and why: only to somebody signed in
put(upg('failed', said='install.sh --upgrade stopped (exit 1)'))
got = php("echo json_encode([zigmon_upgrade_shown(zigmon_upgrading(), false), zigmon_upgrade_shown(zigmon_upgrading(), true)]);")
check(isinstance(got, list) and not ({'by', 'said', 'id'} & set(got[0])) and got[1].get('said', '').startswith('install.sh')
      and got[1].get('by') and got[0].get('key') == got[1].get('key'), 'by, said and id were shown to anybody: %r' % got)
# read once per request
put(upg())
got = php("$a = zigmon_upgrading(); unlink(ZIGMON_UPGRADE_FILE); $b = zigmon_upgrading(); echo json_encode([$a !== null, $b !== null]);")
check(got == [True, True], 'the file was read more than once in one request: %r' % got)
# the sign-in page's band escapes what it draws
put(upg(words='<img src=x onerror=alert(1)>', version='5.99.0'))
got = php("function h($v): string { return htmlspecialchars((string) $v, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'); }\n"
          + "$src = file_get_contents(%s);\n" % json.dumps(str(WEB / 'index.php'))
          + "preg_match('/function zigmon_signin_upband.*?\\n}\\n/s', $src, $m);\n"
          + "eval(str_replace('function zigmon_signin_upband', 'function band_probe', $m[0]));\n"
          + "echo json_encode(band_probe(zigmon_upgrading()));")
check(isinstance(got, str) and '<img' not in got and '&lt;img src=x' in got and 'being upgraded to 5.99.0' in got,
      'the sign-in band does not escape the words: %r' % got)
UPG.unlink()

# ---------------------------------------------------------------------------------------
# 2. install.sh's writer, run in isolation
# ---------------------------------------------------------------------------------------
print("install.sh writes it: whole, 0644, a part per step, failed when it stops")
setup = (HERE / 'install.sh').read_text()
start = setup.index('# ---- (5.54) how far an upgrade is, for the pages')
end = setup.index('# ---- (5.54) end', start)
(W / 'block.sh').write_text(setup[start:end])
check("step()  { printf '\\n%s==> %s%s\\n' \"$C_HEAD\" \"$1\" \"$C_OFF\"; [[ -z \"${UPG_ON:-}\" ]] || upgrade_step \"$1\"; }"
      in setup, 'step() does not tell the pages (or needs more than itself: tests run it with the head of install.sh alone)')
DRIVE = W / 'drive.sh'
DRIVE.write_text(r'''set -euo pipefail
VERSION=5.99.1; WEB_DIR="$1"; DRY_RUN="${DRY:-}"; WITH_WEB=yes; SELINUX_ETC=/nonexistent-selinux
C_HEAD=""; C_OFF=""
step()  { printf '\n%s==> %s%s\n' "$C_HEAD" "$1" "$C_OFF"; [[ -z "${UPG_ON:-}" ]] || upgrade_step "$1"; }
source "$(dirname "$0")/block.sh"
upgrade_watch 5.98.0
step "Checking the machine"
[[ ! -f "$WEB_DIR/.upgrade.json" ]] || cp "$WEB_DIR/.upgrade.json" "$WEB_DIR/../first.json"
step 'Odd "words" \ with	a tab'
[[ ! -f "$WEB_DIR/.upgrade.json" ]] || cp "$WEB_DIR/.upgrade.json" "$WEB_DIR/../mid.json"
case "${MODE:-ok}" in
    fail)  false ;;
    sleep) touch "$WEB_DIR/../sleeping"; sleep 30 & wait $! ;;
esac
step "Starting the daemon"
upgrade_finish
echo "the end"
''')
BASE_PARTS = 12 + (1 if shutil.which('getenforce') else 0) + 1 + (1 if os.path.isfile('/etc/php-fpm.d/www.conf') else 0)


def drive(mode='ok', env=None, folder=None, signal_it=None):
    box = W / ('sh-%s-%d' % (mode, int(time.time() * 1000)))
    www = folder or (box / 'www')
    box.mkdir()
    if folder is None:
        www.mkdir()
    e = {k: v for k, v in os.environ.items() if not k.startswith('ZIGMON_UPGRADE') and k != 'SUDO_USER'}
    e.update(env or {}, MODE=mode)
    p = subprocess.Popen(['bash', str(DRIVE), str(www)], env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         stdin=subprocess.DEVNULL, text=True)
    if signal_it:
        for _ in range(100):
            if (box / 'sleeping').exists():
                break
            time.sleep(0.05)
        time.sleep(0.2)
        p.send_signal(signal_it)
    out, err = p.communicate(timeout=60)
    f = www / '.upgrade.json'
    got = json.loads(f.read_text()) if f.is_file() else None
    return p.returncode, got, f, box, out


rc, got, f, box, out = drive()
first = json.loads((box / 'first.json').read_text())
mid = json.loads((box / 'mid.json').read_text())
check(rc == 0 and 'the end' in out, 'the run by hand did not end as it should: %d' % rc)
check(first['state'] == 'running' and first['part'] == 1 and first['words'] == 'Checking the machine'
      and first['parts'] == BASE_PARTS and first['version'] == '5.99.1' and first['from'] == '5.98.0'
      and first['by'] == 'root on the command line' and first['id'].startswith('cli') and first['downgrade'] is False,
      'the first step was not written as it should: %r (parts %d)' % (first, BASE_PARTS))
check(mid['part'] == 2 and mid['words'] == 'Odd "words" \\ with a tab', 'odd words were not written right: %r' % mid)
check(got and got['state'] == 'done' and got['part'] == 3 and got['words'] == 'zigmon 5.99.1 runs'
      and abs(got['at'] - time.time()) < 30 and got['started'] <= got['at'], 'done was not written at the end: %r' % got)
check(stat.S_IMODE(f.stat().st_mode) == 0o644, 'the file is not 0644: %o' % stat.S_IMODE(f.stat().st_mode))
check(sorted(x.name for x in f.parent.iterdir()) == ['.upgrade.json'], 'a temporary file was left: %r'
      % sorted(x.name for x in f.parent.iterdir()))
check('\n==> Checking the machine\n' in out, 'step() does not print as it did')
rc, got, f, box, out = drive('fail')
check(rc == 1 and got and got['state'] == 'failed' and 'exit 1' in got['said'] and 'Odd' in got['said']
      and got['part'] == 2, 'a run that failed did not say so: %d %r' % (rc, got))
for sig, code, words in ((signal.SIGTERM, 143, 'SIGTERM'), (signal.SIGINT, 130, 'Ctrl-C'), (signal.SIGHUP, 129, 'terminal')):
    rc, got, f, box, out = drive('sleep', signal_it=sig)
    check(rc == code and got and got['state'] == 'failed' and words in got['said'],
          'a run stopped by %s did not end as failed: %d %r' % (sig.name, rc, got))
# under root's helper: its numbering, its words; the end is the helper's
HELPED = {'ZIGMON_UPGRADE_ID': 'abc123', 'ZIGMON_UPGRADE_STARTED': str(int(time.time()) - 30),
          'ZIGMON_UPGRADE_FROM': '5.98.0', 'ZIGMON_UPGRADE_PRE': '3', 'ZIGMON_UPGRADE_POST': '1',
          'ZIGMON_UPGRADE_PAGES_BY': 'olga on the dashboard', 'ZIGMON_UPGRADE_FROM_PAGES': '1'}
rc, got, f, box, out = drive(env=HELPED)
first = json.loads((box / 'first.json').read_text())
check(rc == 0 and first['part'] == 4 and first['parts'] == 3 + BASE_PARTS + 1 and first['id'] == 'abc123'
      and first['by'] == 'olga on the dashboard', 'install.sh under the helper did not go on with its numbering: %r' % first)
check(got and got['state'] == 'running' and got['part'] == 6, 'install.sh said done where the helper says it: %r' % got)
rc, got, f, box, out = drive('fail', env=HELPED)
check(rc == 1 and got and got['state'] == 'running' and 'root puts 5.98.0 back' in got['words'],
      'a failure under the helper was not left to the helper to end: %r' % got)
rc, got, f, box, out = drive('sleep', env=HELPED, signal_it=signal.SIGTERM)
check(rc == 143 and got and got['state'] == 'failed', 'a helper-run install.sh stopped by SIGTERM stayed running: %r' % got)
rc, got, f, box, out = drive(env=dict(HELPED, ZIGMON_UPGRADE_DOWNGRADE='1', ZIGMON_UPGRADE_ID='x;y"z'))
check(got and got['downgrade'] is True and got['id'] == 'xyz', 'downgrade or the id were not written right: %r' % got)
# --dry-run writes nothing; a folder that is not there, or not a folder, costs nothing
rc, got, f, box, out = drive(env={'DRY': 'yes'})
check(rc == 0 and got is None, 'a dry run wrote the file')
missing = W / 'no-such-folder'
rc, got, f, box, out = drive(folder=missing)
check(rc == 0 and 'the end' in out and not missing.exists(), 'a missing pages folder stopped the upgrade: %d' % rc)
notdir = W / 'a-file'
notdir.write_text('x')
rc, got, f, box, out = drive(folder=notdir)
check(rc == 0 and 'the end' in out and notdir.read_text() == 'x', 'a pages "folder" that is a file stopped it: %d' % rc)
blocked = W / 'blocked'
(blocked / '.upgrade.json').mkdir(parents=True)
rc, got, f, box, out = drive(folder=blocked)
check(rc == 0 and 'the end' in out, 'a .upgrade.json that is a folder stopped the upgrade: %d' % rc)
# the count is the steps do_upgrade takes: every function it calls that says a
# step, and the steps in its own body
body = setup[setup.index('\ndo_upgrade() {'):setup.index('\ndo_uninstall() {')]
funcs = {}
for name in ('preflight', 'install_program', 'ensure_python', 'install_service', 'install_helpers',
             'configure_selinux', 'install_time_tools', 'install_console', 'console_quiet', 'install_backup_tools',
             'ensure_php', 'start_service', 'verify', 'report_deploy_changes', 'cli_gate', 'allow_broker_reload',
             'write_system_stamp', 'upgrade_watch', 'upgrade_finish'):
    at = setup.index('\n%s() {' % name)
    fbody = setup[at:setup.index('\n}\n', at)]
    funcs[name] = fbody.count('\n    step "') + fbody.count('\n        step "')
called = [n for n in funcs if ('\n    %s' % n) in body or ('\n        %s' % n) in body]
says = sum(funcs[n] for n in called if n != 'cli_gate') + body.count('step "Dashboard files"')
check(says == 15 and 'cli_gate' in called and funcs['cli_gate'] == 1,
      'do_upgrade takes %d steps besides cli_gate (%r) - upgrade_parts_count counts 12 + SELinux + the pages + PHP'
      % (says, {n: funcs[n] for n in called}))
check('[[ -z "${UPG_ON:-}" ]] || UPG_PARTS=$((UPG_PARTS + 1))' in setup, 'cli_gate does not count its own step')

# ---------------------------------------------------------------------------------------
# 3. root's helper
# ---------------------------------------------------------------------------------------
print("root's helper writes it: the request, the signature, install.sh, the end")
HELPER = HERE / 'deploy' / 'zigmon_upgrade.py'
M = W / 'machine'
LIB, MWEB, KEYS = M / 'lib' / 'zigmon', M / 'www' / 'zigmon', M / 'lib' / 'zigmon' / 'release-keys'
STATE, UNITS = M / 'state', M / 'units'
for d in (KEYS, MWEB, STATE / 'upgrade', UNITS):
    d.mkdir(parents=True)
OLD_PY = "#!/usr/bin/python3\n__version__ = '5.17.0'\n"
(LIB / 'zigmon.py').write_text(OLD_PY)
(LIB / 'zigmon_root.py').write_text('print("zigmon-full-x.tar.gz (1 MB): database")\n')
(MWEB / 'index.php').write_text('<?php // the old page\n')
key = W / 'release.key'
sh(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', str(key)])
sh(['openssl', 'pkey', '-in', str(key), '-pubout', '-out', str(KEYS / 'zigmon-release-test.pub')])
stranger = W / 'stranger.key'
sh(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', str(stranger)])
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


hsrv = ThreadingHTTPServer(('127.0.0.1', 0), Health)
threading.Thread(target=hsrv.serve_forever, daemon=True).start()
HENV = dict(os.environ, ZIGMON_STATE=str(STATE), ZIGMON_LIB=str(LIB), ZIGMON_WEB=str(MWEB),
            ZIGMON_RELEASE_KEYS=str(KEYS), ZIGMON_ROOT_OWN=str(M / 'own'), ZIGMON_UNITS=str(UNITS),
            ZIGMON_NO_SERVICES='1', ZIGMON_HEALTH_WAIT_S='3',
            ZIGMON_HEALTH_URL='http://127.0.0.1:%d/api/health' % hsrv.server_address[1],
            ZIGMON_UPGRADE_TEST='1', ZIGMON_USER='root', ZIGMON_CONFIG=str(M / 'config.json'))
HENV.pop('SUDO_USER', None)
SEEN = W / 'seen-by-install.json'


def package(version, install='ok', sign_with=None, name=None):
    top = 'zigmon-%s' % version
    d = W / 'build' / (name or top) / top
    if d.parent.exists():
        shutil.rmtree(d.parent)
    d.mkdir(parents=True)
    (d / 'zigmon.py').write_text("#!/usr/bin/python3\n__version__ = '%s'\n" % version)
    (d / 'README.md').write_text('%s — a test release.\n' % version)
    look = ('cp "%s/.upgrade.json" "%s" 2>/dev/null || true; env | grep ^ZIGMON_UPGRADE_ > "%s.env" || true\n'
            % (MWEB, SEEN, SEEN))
    script = {'ok': look + 'install -m 755 zigmon.py %s/zigmon.py && echo "==> Program files"\n'
                           'echo "<?php // the new page" > %s/index.php\n' % (LIB, MWEB),
              'fail': look + 'echo "==> Program files"; echo "half done" > %s/zigmon.py; exit 3\n' % LIB}[install]
    (d / 'install.sh').write_text('#!/bin/bash\nset -e\ncd "$(dirname "$0")"\n' + script)
    lines = []
    for p in sorted(x for x in d.rglob('*') if x.is_file()):
        lines.append('%s  %s' % (hashlib.sha256(p.read_bytes()).hexdigest(), p.relative_to(d).as_posix()))
    (d / 'MANIFEST').write_text('\n'.join(lines) + '\n')
    sh(['openssl', 'pkeyutl', '-sign', '-inkey', str(sign_with or key), '-rawin',
        '-in', str(d / 'MANIFEST'), '-out', str(d / 'MANIFEST.sig')])
    out = W / 'build' / ('%s.tar.gz' % (name or top))
    with tarfile.open(out, 'w:gz') as t:
        t.add(d, arcname=top)
    return out


def serve(pkg, version, ident, env=None):
    for p in (SEEN, Path(str(SEEN) + '.env')):
        if p.exists():
            p.unlink()
    shutil.copy(pkg, STATE / 'upgrade' / ('zigmon-%s.tar.gz' % version))
    sha = hashlib.sha256(pkg.read_bytes()).hexdigest()
    (STATE / 'upgrade' / 'request.json').write_text(json.dumps(
        {'id': ident, 'file': 'zigmon-%s.tar.gz' % version, 'version': version, 'sha': sha, 'by': 'olga'}))
    got = sh([sys.executable, '-I', str(HELPER)], env=env or HENV)
    st = json.loads((STATE / 'upgrade' / 'status.json').read_text())
    f = MWEB / '.upgrade.json'
    return st, (json.loads(f.read_text()) if f.is_file() else None), got


st, pg, _ = serve(package('5.18.0', sign_with=stranger, name='stranger'), '5.18.0', 'r1')
check(st.get('state') == 'failed' and pg and pg['state'] == 'failed' and pg['id'] == 'r1'
      and 'not by any release key' in pg['said'] and pg['by'] == 'olga on the dashboard' and pg['version'] == '5.18.0'
      and pg['part'] == 1, 'a bad signature was not written as failed: %r' % pg)
f = MWEB / '.upgrade.json'
check(stat.S_IMODE(f.stat().st_mode) == 0o644 and sorted(x.name for x in MWEB.iterdir()) == ['.upgrade.json', 'index.php'],
      'the helper left the file not 0644, or a temporary one beside it: %r' % sorted(x.name for x in MWEB.iterdir()))
SAYS['version'] = '5.18.0'
good = package('5.18.0')
st, pg, _ = serve(good, '5.18.0', 'r2')
seen = json.loads(SEEN.read_text()) if SEEN.exists() else {}
env_seen = Path(str(SEEN) + '.env').read_text() if Path(str(SEEN) + '.env').exists() else ''
check(seen.get('state') == 'running' and seen.get('part') == 3 and seen.get('id') == 'r2'
      and 'install.sh' in seen.get('words', '') and seen.get('from') == '5.17.0',
      'while install.sh ran the file did not say so: %r' % seen)
check('ZIGMON_UPGRADE_PRE=3' in env_seen and 'ZIGMON_UPGRADE_POST=1' in env_seen and 'ZIGMON_UPGRADE_ID=r2' in env_seen
      and 'ZIGMON_UPGRADE_FROM=5.17.0' in env_seen, 'install.sh was not handed the numbering: %r' % env_seen)
check(st.get('state') == 'done' and pg and pg['state'] == 'done' and pg['words'] == 'zigmon 5.18.0 runs'
      and pg['part'] == pg['parts'] and pg['parts'] >= 4, 'a good upgrade was not written as done: %r' % pg)
(LIB / 'zigmon.py').write_text(OLD_PY)
(MWEB / 'index.php').write_text('<?php // the old page\n')
SAYS['version'] = '5.17.0'
st, pg, _ = serve(package('5.18.0', install='fail', name='failing'), '5.18.0', 'r3')
check(st.get('state') == 'failed' and pg and pg['state'] == 'failed' and 'did not go in' in pg['said']
      and '5.17.0 runs again' in pg['said'], 'install.sh failing was not written as failed, taken back: %r' % pg)
check((MWEB / 'index.php').read_text() == '<?php // the old page\n', 'the old page is not back after the failure')
# no pages folder at all: the upgrade goes through as it always did
SAYS['version'] = '5.18.0'
nowhere = dict(HENV, ZIGMON_WEB=str(M / 'www' / 'not-there'))
st, pg, got = serve(good, '5.18.0', 'r4', env=nowhere)
check(st.get('state') == 'done' and not (M / 'www' / 'not-there').exists(),
      'with no pages folder the upgrade did not go through: %r %s' % (st, got.stderr[-300:]))
# the command line
(LIB / 'zigmon.py').write_text(OLD_PY)
got = sh([sys.executable, '-I', str(HELPER), '--run', str(good)], env=HENV)
pg = json.loads((MWEB / '.upgrade.json').read_text())
check(got.returncode == 0 and pg['state'] == 'done' and pg['by'] == 'root on the command line' and pg['id'],
      'the command line did not write done: %d %r' % (got.returncode, pg))
got = sh([sys.executable, '-I', str(HELPER), '--run', str(package('5.18.0', sign_with=stranger, name='s2'))], env=HENV)
pg = json.loads((MWEB / '.upgrade.json').read_text())
check(got.returncode == 1 and pg['state'] == 'failed' and 'release key' in pg['said'],
      'a refused package on the command line was not written as failed: %r' % pg)
hsrv.shutdown()

# ---------------------------------------------------------------------------------------
# 4. the relay, with zigmon and php -S
# ---------------------------------------------------------------------------------------
print('the relay: "being upgraded" only while zigmon does not answer and the file is fresh')
for port in (API_PORT, PHP_PORT, CTL_PORT):
    try:
        socket.create_connection(('127.0.0.1', port), 0.2).close()
        check(False, 'port %d is taken by something else' % port)
        finish()
    except OSError:
        pass
(W / 'state').mkdir()
LAUNCH = W / 'daemon.py'
LAUNCH.write_text('''import sys, time
sys.argv = ['zigmon']
sys.path.insert(0, %(here)r)
import zigmon
zigmon.load_config()
zigmon.CONFIG.update({'db_file': %(db)r, 'api_port': %(port)d, 'api_host': '127.0.0.1', 'token_file': %(token)r,
                      'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '', 'state_dir': %(state)r,
                      'preheat': False, 'public_view': False})
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
if 'owner' not in d.accounts:
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
api = zigmon.ApiServer(d)
api.start()
print('READY', flush=True)
while True:
    time.sleep(3600)
''' % {'here': str(HERE), 'db': str(W / 'z.db'), 'port': API_PORT, 'token': str(W / 'token'),
       'state': str(W / 'state')})


def wait_port(port, up=True, most=40.0):
    until = time.time() + most
    while time.time() < until:
        try:
            socket.create_connection(('127.0.0.1', port), 0.3).close()
            if up:
                return True
        except OSError:
            if not up:
                return True
        time.sleep(0.1)
    return False


def start_api():
    PROCS['api'] = subprocess.Popen([sys.executable, str(LAUNCH)], stdout=open(W / 'daemon.log', 'a'),
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    return check(wait_port(API_PORT), 'the daemon did not start')


def start_php():
    PROCS['php'] = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, str(WEB / 'index.php')], cwd=str(WEB),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                    env=dict(os.environ, PHP_CLI_SERVER_WORKERS='4'), start_new_session=True)
    return check(wait_port(PHP_PORT), 'php -S did not start')


def kill(name, port):
    stop(name)
    wait_port(port, up=False)


start_api()
start_php()


def login():
    token = (W / 'token').read_text().strip()
    req = urllib.request.Request('http://127.0.0.1:%d/api/auth/login' % API_PORT,
                                 data=json.dumps({'name': 'owner', 'password': 'owner pass 12'}).encode(),
                                 headers={'X-Zigmon-Token': token, 'Content-Type': 'application/json',
                                          'X-Zigmon-Client': '192.168.40.10'}, method='POST')
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read()).get('token') or ''


SESSION = login()
check(bool(SESSION), 'could not sign in')


def page(query, session=None, method='GET'):
    req = urllib.request.Request('http://127.0.0.1:%d/%s' % (PHP_PORT, query), method=method,
                                 data=b'{}' if method == 'POST' else None,
                                 headers={'Cookie': 'zigmon_session=%s' % session} if session else {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')


def js(body):
    try:
        return json.loads(body)
    except ValueError:
        return {'not json': body[:200]}


if UPG.exists():
    UPG.unlink()
code, body = page('?api=status', SESSION)
check(code == 200 and '"upgrading"' not in body, 'with no file the status changed: %d %s' % (code, body[:200]))
code, body = page('?api=health')
plain_health = (code, body)
put(upg())
code, body = page('?api=status', SESSION)
st = js(body)
check(code == 200 and isinstance(st.get('upgrading'), dict) and st['upgrading'].get('by') == 'owner on the dashboard'
      and 'devices' in st and body.startswith('{"upgrading":'), 'the status did not carry the upgrade: %s' % body[:300])
code, body = page('?api=status', 'made-up-session-token-that-is-long-enough')
check(code == 403 and '"upgrading"' not in body, 'a status refused carried the upgrade: %d %s' % (code, body[:200]))
code, body = page('?api=upgrade-state', SESSION)
got = js(body)
check(code == 200 and got.get('api') is True and got['upgrading'].get('by') == 'owner on the dashboard'
      and len(got.get('pages') or '') == 12, 'upgrade-state with a sign-in: %s' % body[:300])
code, body = page('?api=upgrade-state', 'made-up-session-token-that-is-long-enough')
got = js(body)
check(code == 200 and got.get('upgrading') and not ({'by', 'said', 'id'} & set(got['upgrading'])),
      'upgrade-state told a made-up sign-in who asked: %s' % body[:300])
code, body = page('?api=upgrade-state', method='POST')
check(code in (403, 405), 'upgrade-state took a POST: %d' % code)
code, body = page('?api=healthz')
check(code == 503 and js(body).get('state') == 'in maintenance', 'healthz did not say maintenance: %d %s' % (code, body))
# zigmon away
kill('api', API_PORT)
for q in ('?api=status', '?api=events&limit=5', '?api=wait&seq=1'):
    code, body = page(q, SESSION)
    got = js(body)
    check(code == 503 and got.get('upgrading', {}).get('state') == 'running' and 'being upgraded' in got.get('error', '')
          and 'by' not in got['upgrading'], '%s while zigmon is away in an upgrade: %d %s' % (q, code, body[:300]))
code, body = page('?api=upgrade-state', SESSION)
got = js(body)
check(code == 200 and got.get('api') is False and got['upgrading']['state'] == 'running' and 'by' not in got['upgrading'],
      'upgrade-state without zigmon: %s' % body[:300])
code, body = page('?api=healthz')
check(code == 503 and js(body).get('state') == 'in maintenance', 'healthz without zigmon: %d %s' % (code, body))
code, body = page('?api=status', SESSION)
put(upg(ago=1900))
code, body = page('?api=status', SESSION)
check(code == 503 and 'upgrading' not in js(body) and 'not responding' in js(body).get('error', ''),
      'a stale file changed what the page is told: %s' % body[:300])
UPG.unlink()
code, body = page('?api=status', SESSION)
check(code == 503 and 'upgrading' not in js(body) and 'not responding' in js(body).get('error', ''),
      'with no file the answer changed: %s' % body[:300])
code, body = page('?api=healthz')
check(code == 503 and 'upgrading' not in js(body), 'healthz with no file changed: %s' % body[:300])
start_api()
code, body = page('?api=health')
check((code, js(body).get('ok')) == (plain_health[0], js(plain_health[1]).get('ok')), 'health changed')

# ---------------------------------------------------------------------------------------
# 5. the page in Chromium
# ---------------------------------------------------------------------------------------
npm_root = sh(['npm', 'root', '-g']).stdout.strip()
if not (Path(npm_root) / 'playwright').exists():
    print('  SKIPPED the browser (no playwright here)')
    finish()
print('the page follows it: the band, zigmon and PHP away, done, failed, signed out, not saved')
SHOTS.mkdir(parents=True, exist_ok=True)
STARTED = [int(time.time())]


class Control(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        out = {'ok': True}
        try:
            if u.path == '/tell':
                if q.get('fresh'):
                    STARTED[0] = int(time.time()) - int(q.get('fresh'))
                now = int(time.time())
                row = {'state': q.get('state', 'running'), 'id': q.get('id', 'k1'), 'version': '5.99.0',
                       'from': '5.98.0', 'by': 'owner on the dashboard', 'part': int(q.get('part', 1)),
                       'parts': int(q.get('parts', 16)), 'words': q.get('words', ''), 'started': STARTED[0],
                       'at': now, 'said': q.get('said', ''), 'downgrade': q.get('downgrade') == '1'}
                put(row)
            elif u.path == '/rm':
                if UPG.exists():
                    UPG.unlink()
            elif u.path == '/kill-api':
                kill('api', API_PORT)
            elif u.path == '/start-api':
                start_api()
            elif u.path == '/kill-php':
                kill('php', PHP_PORT)
            elif u.path == '/start-php':
                start_php()
        except Exception as e:                       # noqa: BLE001
            out = {'ok': False, 'error': str(e)}
        body = json.dumps(out).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


ctl = ThreadingHTTPServer(('127.0.0.1', CTL_PORT), Control)
threading.Thread(target=ctl.serve_forever, daemon=True).start()

PAGE_JS = r'''
const { chromium } = require('playwright');
const job = JSON.parse(process.argv[2]);
const base = 'http://127.0.0.1:' + job.port + '/';
const ctl = (what, q) => fetch('http://127.0.0.1:' + job.ctl + '/' + what + '?' + new URLSearchParams(q || {})).then(r => r.json());
const out = {errors: [], seen: {}};
const say = (k, v) => { out.seen[k] = v; };
(async () => {
  const b = await chromium.launch();
  async function newPage(session) {
    const ctx = await b.newContext({viewport: {width: 1600, height: 900}, deviceScaleFactor: 1, colorScheme: 'dark'});
    if (session) await ctx.addCookies([{name: 'zigmon_session', value: session, url: base}]);
    const p = await ctx.newPage();
    p.setDefaultTimeout(15000);
    p.on('pageerror', e => out.errors.push(String(e)));
    p.on('dialog', d => { out.errors.push('dialog: ' + d.message()); d.dismiss().catch(() => {}); });
    p._loads = 0;
    p.on('load', () => { p._loads++; });
    return p;
  }
  // what the page shows, and whatever red it showed meanwhile
  const watch = p => p.evaluate(() => {
    window.__red = window.__red || [];
    if (window.__watching) return;
    window.__watching = setInterval(() => {
      const t = document.getElementById('toast'), pill = document.getElementById('pill-text');
      if (t && /show/.test(t.className) && /bad/.test(t.className)) window.__red.push('toast: ' + t.textContent);
      if (pill && /offline/i.test(pill.textContent)) window.__red.push('pill: ' + pill.textContent);
    }, 150);
  });
  const look = p => p.evaluate(() => {
    const b = document.getElementById('upband');
    return {band: !!b && !b.hidden, cls: b ? b.className : '', text: b ? b.innerText : '',
            html: b ? b.innerHTML : '', pill: (document.getElementById('pill-text') || {}).textContent || '',
            pillCls: (document.getElementById('pill') || {}).className || '',
            red: (window.__red || []).slice(), xss: !!window.__xss,
            maint: !!document.getElementById('maint-band') && getComputedStyle(document.getElementById('maint-band')).display,
            // (5.54.0) blue while it runs, as the kit has it
            headColor: b && b.querySelector('.upband-head') ? getComputedStyle(b.querySelector('.upband-head')).color : '',
            border: b ? getComputedStyle(b).borderTopColor : ''};
  });
  const shot = (p, n) => p.screenshot({path: job.shots + '/' + n + '.png'});
  try {
    // ---- A: the whole of it, signed in -------------------------------------------
    let p = await newPage(job.session);
    await ctl('rm');
    await p.goto(base + '#overview');
    await p.waitForSelector('#pill');
    await p.waitForTimeout(2500);
    await watch(p);
    say('a0', await look(p));
    await ctl('tell', {state: 'running', part: 1, words: "root takes the request and checks the package's signature", fresh: 4});
    // what pressing Upgrade does: the page looks for the band at once
    await p.evaluate(() => upgradeWatchFor(120000));
    await p.waitForTimeout(5000);
    say('a1', await look(p));
    await shot(p, '01-running-overview');
    await p.evaluate(() => upgradeOpenPane());
    await p.waitForTimeout(2500);
    await ctl('tell', {state: 'running', part: 7, words: 'Starting the daemon'});
    await ctl('kill-api');
    await p.waitForTimeout(8000);
    say('a2', await look(p));
    say('a2plan', await p.evaluate(() => { const c = document.getElementById('up-plan-card'); return c && !c.hidden ? document.getElementById('up-plan').innerText : ''; }));
    await p.evaluate(() => { const c = document.getElementById('up-plan-card'); if (c && !c.hidden) c.scrollIntoView({block: 'center'}); });
    await p.waitForTimeout(400);
    await shot(p, '02-running-upgrades-pane');
    await p.evaluate(() => showTab('overview'));
    await p.waitForTimeout(2500);
    say('a3', await look(p));
    await shot(p, '03-api-down');
    await ctl('tell', {state: 'running', part: 13, words: 'PHP 8.3.36'});
    await ctl('kill-php');
    await p.waitForTimeout(7000);
    say('a4', await look(p));
    await shot(p, '04-nginx-php-restarting');
    await ctl('start-php');
    await p.waitForTimeout(5000);
    say('a5', await look(p));
    await shot(p, '05-php-back-api-down');
    await ctl('tell', {state: 'running', part: 16, words: 'asking zigmon 5.99.0 whether it answers'});
    await ctl('start-api');
    await p.waitForTimeout(6000);
    say('a6', await look(p));
    await shot(p, '06-api-back');
    say('a6loads', p._loads);
    await p.evaluate(() => { window.__before = 1; });
    await ctl('tell', {state: 'done', part: 16, words: 'zigmon 5.99.0 runs'});
    await p.waitForTimeout(9000);
    say('a7', await look(p));
    say('a7loads', p._loads);
    say('a7marker', await p.evaluate(() => !!window.__before));
    say('a7guard', await p.evaluate(() => sessionStorage.getItem('zigmon-upgrade-reloaded')));
    await shot(p, '07-done-reloaded');
    await p.waitForTimeout(7000);
    say('a8loads', p._loads);
    await p.context().close();

    // ---- B: failed, and its x remembered ---------------------------------------
    p = await newPage(job.session);
    await ctl('tell', {state: 'failed', id: 'k2', part: 9, words: 'Starting the daemon', fresh: 95,
                       said: 'zigmon 5.99.0 did not go in (install.sh --upgrade ended with 1) - 5.98.0 runs again'});
    await p.goto(base + '#overview');
    await p.waitForSelector('#pill');
    await p.waitForTimeout(4000);
    say('b1', await look(p));
    await shot(p, '08-failed');
    await p.click('#upband .upband-x');
    await p.waitForTimeout(500);
    say('b2', await look(p));
    await p.reload();
    await p.waitForTimeout(3500);
    say('b3', await look(p));
    await ctl('tell', {state: 'failed', id: 'k3', part: 9, words: '<img src=x onerror="window.__xss=1">',
                       said: '<script>window.__xss=1</script><b>bold</b>'});
    await p.reload();
    await p.waitForTimeout(3500);
    say('b4', await look(p));
    await p.context().close();

    // ---- C: signed out in the middle of it -------------------------------------
    p = await newPage('');
    await ctl('tell', {state: 'running', id: 'k5', part: 7, words: 'Starting the daemon <i onmouseover=x>', fresh: 30});
    await ctl('kill-api');
    await p.goto(base);
    await p.waitForTimeout(5000);
    say('c1', await p.evaluate(() => {
      const b = document.getElementById('upband');
      return {band: !!b && !b.hidden, text: b ? b.innerText : '', html: b ? b.innerHTML : '',
              signin: !!document.getElementById('signin-form'), italic: !!document.querySelector('#upband i'),
              loads: 0};
    }));
    await shot(p, '09-signin-during-upgrade');
    const before = p._loads;
    await ctl('start-api');
    await p.waitForTimeout(6000);
    say('c2loads', p._loads - before);
    say('c2', await p.evaluate(() => ({signin: !!document.getElementById('signin-form'),
                                       band: !!document.getElementById('upband') && !document.getElementById('upband').hidden})));
    const before2 = p._loads;
    await ctl('tell', {state: 'done', id: 'k5', part: 16, words: 'zigmon 5.99.0 runs'});
    await p.waitForTimeout(6000);
    say('c3loads', p._loads - before2);
    say('c3', await p.evaluate(() => ({band: !!document.getElementById('upband') && !document.getElementById('upband').hidden})));
    await p.context().close();

    // ---- D: something not saved: no reload, a link --------------------------------
    p = await newPage(job.session);
    await ctl('rm');
    await p.goto(base + '#overview');
    await p.waitForSelector('#pill');
    await p.waitForTimeout(2500);
    await ctl('tell', {state: 'running', id: 'k6', part: 5, words: 'Python', fresh: 10});
    await p.evaluate(() => upgradeWatchFor(120000));
    await p.waitForTimeout(4500);
    say('d1', await look(p));
    await p.evaluate(() => { HEAT.dirty = true; window.__before = 1; });
    const loadsD = p._loads;
    await ctl('tell', {state: 'done', id: 'k6', part: 16, words: 'zigmon 5.99.0 runs'});
    await p.waitForTimeout(7000);
    say('d2', await look(p));
    say('d2loads', p._loads - loadsD);
    await shot(p, '10-done-not-saved');
    await p.click('#upband .upband-again');
    await p.waitForTimeout(3500);
    say('d3loads', p._loads - loadsD);
    say('d3marker', await p.evaluate(() => !!window.__before));
    await p.context().close();
  } catch (e) {
    out.errors.push('script: ' + (e && e.stack || e));
  }
  await ctl('rm');
  await b.close();
  console.log(JSON.stringify(out));
})();
'''
(W / 'page.js').write_text(PAGE_JS)
job = {'port': PHP_PORT, 'ctl': CTL_PORT, 'session': SESSION, 'shots': str(SHOTS)}
got = subprocess.run(['node', str(W / 'page.js'), json.dumps(job)], capture_output=True, text=True, timeout=600,
                     stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=npm_root))
try:
    res = json.loads(got.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    check(False, 'the browser script said nothing: %s %s' % (got.stdout[-800:], got.stderr[-1500:]))
    finish()
s = res['seen']
for e in res['errors']:
    check(False, 'in the page: %s' % e[:400])


def seen(k):
    return s.get(k) or {}


check(not seen('a0').get('band'), 'a band with no upgrade: %r' % seen('a0'))
a1 = seen('a1')
check(a1.get('headColor') == 'rgb(88, 166, 255)' and a1.get('border') == 'rgb(88, 166, 255)',
      'the running band is not blue as in the kit: %r / %r' % (a1.get('headColor'), a1.get('border')))
check(a1.get('band') and 'zigmon is being upgraded to 5.99.0' in a1.get('text', '') and 'from 5.98.0' in a1['text']
      and 'asked by owner on the dashboard' in a1['text'] and 'step 1 of 16' in a1['text']
      and a1.get('pill') == 'In maintenance' and 'warn' in a1.get('pillCls', ''),
      'running: no band, or not as it should be: %r' % a1)
a2 = seen('a2')
check(a2.get('band') and 'not answering for' in a2.get('text', '') and 'step 7 of 16' in a2['text']
      and a2.get('pill') == 'In maintenance', 'zigmon away: the band does not say so: %r' % a2)
check('Starting the daemon' in (s.get('a2plan') or '') and '7 of 16' in (s.get('a2plan') or ''),
      'Settings - Upgrades did not show the upgrade from the file while zigmon was away: %r' % s.get('a2plan'))
check(seen('a3').get('band') and 'not answering for' in seen('a3').get('text', ''), 'the overview with zigmon away: %r' % seen('a3'))
check('These pages cannot be reached' in seen('a4').get('text', ''), 'PHP away: the band does not say so: %r' % seen('a4'))
a5 = seen('a5')
check('not answering for' in a5.get('text', '') and 'step 13 of 16' in a5['text'] and 'PHP 8.3.36' in a5['text'],
      'PHP back, zigmon not: the band did not go on: %r' % a5)
a6 = seen('a6')
check(a6.get('band') and 'not answering' not in a6.get('text', '') and 'step 16 of 16' in a6['text']
      and a6.get('pill') == 'In maintenance', 'zigmon back: %r' % a6)
for k in ('a1', 'a2', 'a3', 'a4', 'a5', 'a6'):
    check(not seen(k).get('red'), 'something red while the upgrade went on (%s): %r' % (k, seen(k).get('red')))
check(s.get('a6loads') == 1, 'the page was loaded again before the end: %r' % s.get('a6loads'))
check(s.get('a7loads') == 2 and s.get('a7marker') is False and s.get('a7guard'),
      'done: the page was not loaded again once: loads %r, marker %r, guard %r' % (s.get('a7loads'), s.get('a7marker'), s.get('a7guard')))
check(not seen('a7').get('band'), 'after the reload the band is still there: %r' % seen('a7'))
check(s.get('a8loads') == 2, 'the page was loaded again more than once: %r' % s.get('a8loads'))
b1 = seen('b1')
check(b1.get('band') and 'bad' in b1.get('cls', '') and 'The upgrade to zigmon 5.99.0 failed' in b1['text']
      and '5.98.0 runs again' in b1['text'] and 'Open Upgrades' in b1['text'], 'failed: no red band: %r' % b1)
check(not seen('b2').get('band') and not seen('b3').get('band'), 'the x of a failed upgrade was not remembered: %r %r'
      % (seen('b2'), seen('b3')))
b4 = seen('b4')
check(b4.get('band') and '<script>window.__xss=1</script><b>bold</b>' in b4.get('text', '') and not b4.get('xss')
      and '<b>' not in b4.get('html', '') and '<script' not in b4.get('html', ''),
      'another failed upgrade not shown, or its words became markup: %r' % b4)
c1 = seen('c1')
check(c1.get('band') and c1.get('signin') and 'zigmon is being upgraded to 5.99.0' in c1.get('text', '')
      and '<i onmouseover=x>' in c1['text'] and not c1.get('italic'),
      'signed out in the middle of it: no sign-in page with the band: %r' % c1)
check('owner' not in c1.get('text', ''), 'the sign-in page said who asked: %r' % c1.get('text'))
check((s.get('c2loads') or 0) >= 1 and seen('c2').get('signin'), 'the sign-in page was not loaded again when zigmon answered: %r %r'
      % (s.get('c2loads'), seen('c2')))
check((s.get('c3loads') or 0) >= 1 and not seen('c3').get('band'), 'the sign-in page did not follow the end: %r %r'
      % (s.get('c3loads'), seen('c3')))
check(seen('d1').get('band'), 'not saved: no band to begin with: %r' % seen('d1'))
d2 = seen('d2')
check(s.get('d2loads') == 0 and d2.get('band') and 'Load it again' in d2.get('text', ''),
      'something not saved: the page was loaded again under it, or no link: %r %r' % (s.get('d2loads'), d2))
check(s.get('d3loads') == 1 and s.get('d3marker') is False, 'Load it again did not load it: %r' % s.get('d3loads'))
print('  screenshots in %s' % SHOTS)
ctl.shutdown()
finish()
