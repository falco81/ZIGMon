#!/usr/bin/env python3
"""5.57: ZIGMon Notifier shipped with ZIGMon - the server side of getting the app and of the
app updating itself from the server it is connected to.

  * the daemon finds the files (CONFIG['notifier_dir'] here): the exe, notifier.json and its
    Ed25519 signature; reads the 50 MB at most once for each change of the files;
  * GET /api/notifier/update (the key alone): available, version, size, sha256, the manifest's
    exact bytes and the signature in base64 - the signature verifies with the key it was made by;
  * GET /api/notifier/download: the exe, byte for byte, octet-stream, attachment, its length;
  * a wrong key on either is 401 and counted as a wrong one-tap secret;
  * an exe of another size or another SHA-256 than notifier.json says, or no signature: not
    available (update says so, download is 404, hello.app is null), with one warning in the log;
  * hello carries app.version; GET /api/notifier/keys carries app {version, size, sha256};
  * GET /api/notifier/app: the exe for an administrator (ALWAYS_LOCKED); an operator and nobody 403;
  * the relay (php -S): do=update and do=download (the same bytes, the same headers), a wrong key
    401 through it; api=notifier-app with the administrator's cookie, 403 without, 403 for an operator;
  * the page (Playwright): Settings - Messages - Desktop app has "Get the app" - the download
    button with the version, the SHA-256, the runtime; the button downloads the exe; without the
    app "The app is not in this package."; desktop and 390 px, no sideways scroll. Screenshots
    into $ZIGMON_SHOTS (or a temporary folder that is kept);
  * install.sh's install_notifier_app copies the three files into LIB_DIR/notifier (644, 755),
    changes nothing in a dry run, and takes them away when the package has none;
  * tools/make-release.sh signs windows/dist/notifier.json with the key given (missing or wrong
    signature), checks it against deploy/release-keys, puts it into the package and says to
    commit it; with no windows/dist the release is made as before. Run against a copy of the
    tree with a throwaway key (never the real one).

    python3 test/review557_notifier_app.py < /dev/null

Ports 20170-20179. Every key and secret here is made up.
"""
import base64
import hashlib
import json
import os
import re
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
W = Path(tempfile.mkdtemp(prefix='zigmon-ntfapp-'))
API_PORT, PHP_PORT = 20170, 20171
SHOTS = Path(os.environ.get('ZIGMON_SHOTS') or tempfile.mkdtemp(prefix='zigmon-ntfapp-shots-'))
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


# ---- a throwaway release key and a fake app --------------------------------------------------
KEYDIR = W / 'keys'
KEYDIR.mkdir()
TKEY, TPUB = KEYDIR / 'throwaway.key', KEYDIR / 'throwaway.pub'
OKEY, OPUB = KEYDIR / 'other.key', KEYDIR / 'other.pub'
for k, p in ((TKEY, TPUB), (OKEY, OPUB)):
    r = sh(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', str(k)])
    if r.returncode != 0:
        print('SKIPPED: openssl has no Ed25519 here: %s' % r.stderr[-200:])
        sys.exit(0)
    sh(['openssl', 'pkey', '-in', str(k), '-pubout', '-out', str(p)])

EXE = b'MZ\x90\x00' + os.urandom(300 * 1024 + 17) + b'fake ZIGMon Notifier, not a program'


def manifest(exe, version='1.1.0', size=None, sha=None):
    return (json.dumps({'product': 'ZIGMon Notifier', 'file': 'ZigmonNotifier.exe', 'version': version,
                        'size': len(exe) if size is None else size,
                        'sha256': sha or hashlib.sha256(exe).hexdigest(),
                        'runtime': 'Microsoft.WindowsDesktop.App 10.0'}, separators=(',', ':')) + '\n').encode()


def sign(path_json, path_sig, key=TKEY):
    r = sh(['openssl', 'pkeyutl', '-sign', '-inkey', str(key), '-rawin', '-in', str(path_json), '-out', str(path_sig)])
    assert r.returncode == 0, r.stderr


def verifies(path_json, path_sig, pub=TPUB):
    return sh(['openssl', 'pkeyutl', '-verify', '-pubin', '-inkey', str(pub), '-rawin', '-in', str(path_json),
               '-sigfile', str(path_sig)]).returncode == 0


def dist(where, exe=EXE, man=None, with_sig=True):
    where.mkdir(parents=True, exist_ok=True)
    for n in ('ZigmonNotifier.exe', 'notifier.json', 'notifier.json.sig'):
        if (where / n).exists():
            (where / n).unlink()
    (where / 'ZigmonNotifier.exe').write_bytes(exe)
    (where / 'notifier.json').write_bytes(man if man is not None else manifest(exe))
    if with_sig:
        sign(where / 'notifier.json', where / 'notifier.json.sig')


DIST = W / 'dist'
dist(DIST)
MAN = (DIST / 'notifier.json').read_bytes()
SIG = (DIST / 'notifier.json.sig').read_bytes()
SHA = hashlib.sha256(EXE).hexdigest()

# ---- the daemon --------------------------------------------------------------------------------
sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                               # noqa: E402

LOG = []
_real_log = zigmon.log


def _log(msg, level='info', *a, **k):
    LOG.append('%s %s' % (level, msg))


zigmon.log = _log
zigmon.load_config()
(W / 'state').mkdir()
zigmon.CONFIG.update({
    'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1', 'token_file': str(W / 'token'),
    'pin': '', 'sensors': [], 'plugs': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(W / 'state'),
    'debug': 0, 'blacklist': 0, 'public_view': False, 'notifier_dir': str(DIST)})
d = zigmon.Daemon()
d.notify = lambda message, *a, **k: None
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)

CHECKS = [0]
_real_check = getattr(zigmon.Daemon, '_notifier_app_check', None)


def _counted_check(self, *a, **k):
    CHECKS[0] += 1
    return _real_check(self, *a, **k)


if _real_check is not None:
    zigmon.Daemon._notifier_app_check = _counted_check


def raw(path, session=None, key=None, client='192.168.40.10', token=True, timeout=30):
    headers = {'X-Zigmon-Client': client}
    if token:
        headers['X-Zigmon-Token'] = d.token
    if session:
        headers['X-Zigmon-Session'] = session
    if key is not None:
        headers['X-Zigmon-Notifier'] = key
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def call(path, body=None, session=None, key=None, client='192.168.40.10'):
    if body is None:
        code, _h, b = raw(path, session=session, key=key, client=client)
        try:
            return code, json.loads(b or b'{}')
        except ValueError:
            return code, {'raw': b[:80]}
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': client}
    if session:
        headers['X-Zigmon-Session'] = session
        body = dict(body, session=session)
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                 data=json.dumps(body).encode(), method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def warnings():
    return [x for x in LOG if x.startswith('warn ') and 'desktop notifier' in x]


def file_ok(headers, body, want=EXE):
    h = {k.lower(): v for k, v in headers.items()}
    return (body == want and h.get('content-type', '').startswith('application/octet-stream')
            and h.get('content-disposition') == 'attachment; filename="ZigmonNotifier.exe"'
            and h.get('content-length') == str(len(want)))


try:
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
    S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
    SO = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''
    check(S and SO, 'could not sign in')
    d.store.upsert_device({'id': '0x00158d0001a2b3c4', 'name': 'PIR-Chodba', 'source': 'zigbee', 'kind': 'EndDevice',
                           'exposes': {'occupancy': {}}})
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'Office PC', 'devices': []}, session=S)
    KEY = out.get('key') or ''
    check(code == 200 and KEY.startswith('zmn_'), 'the key: %s %r' % (code, out))

    print('update and download, by the key')
    code, out = call('/api/notifier/update', key=KEY)
    check(code == 200 and out.get('ok') is True and out.get('available') is True and out.get('version') == '1.1.0'
          and out.get('size') == len(EXE) and out.get('sha256') == SHA, 'update: %s %r' % (code, out))
    check(set(out) == {'ok', 'available', 'version', 'size', 'sha256', 'manifest', 'sig'}, 'update keys: %r' % sorted(out))
    check(base64.b64decode(out.get('manifest') or '') == MAN, 'the manifest is not the exact bytes signed')
    check(base64.b64decode(out.get('sig') or '') == SIG and len(SIG) == 64, 'the signature is not the one made')
    (W / 'got.json').write_bytes(base64.b64decode(out.get('manifest') or ''))
    (W / 'got.sig').write_bytes(base64.b64decode(out.get('sig') or ''))
    check(verifies(W / 'got.json', W / 'got.sig'), 'what update says does not verify with the key it was made by')
    code, h, body = raw('/api/notifier/download', key=KEY)
    check(code == 200 and file_ok(h, body), 'download: %s %r %d bytes' % (code, h, len(body)))
    code, out = call('/api/notifier/hello', key=KEY)
    check(code == 200 and out.get('app') == {'version': '1.1.0'}, 'hello.app: %r' % out.get('app'))
    code, out = call('/api/notifier/keys', session=S)
    check(code == 200 and out.get('app') == {'version': '1.1.0', 'size': len(EXE), 'sha256': SHA},
          'keys.app: %r' % out.get('app'))
    for _ in range(5):
        call('/api/notifier/update', key=KEY)
        raw('/api/notifier/download', key=KEY)
    check(CHECKS[0] == 1, 'the exe was read %d times for one state of the files' % CHECKS[0])
    check(not warnings(), 'a warning for files that agree: %r' % warnings())

    print('a wrong key is refused and counted')
    WHO = '198.51.100.9'
    before = len(d._tap_tries.get(WHO, [])) if getattr(d, '_tap_tries', None) else 0
    code, out = call('/api/notifier/update', key='zmn_' + 'B' * 40, client=WHO)
    check(code == 401 and out.get('ok') is False and 'available' not in out, 'update with a wrong key: %s %r' % (code, out))
    code, h, body = raw('/api/notifier/download', key='zmn_' + 'C' * 40, client=WHO)
    check(code == 401 and EXE[:100] not in body and b'not known' in body, 'download with a wrong key: %s %r' % (code, body[:120]))
    code, h, body = raw('/api/notifier/download', client=WHO)
    check(code == 401, 'download with no key: %s' % code)
    check(len(d._tap_tries.get(WHO, [])) == before + 3, 'the wrong keys are not counted: %r' % d._tap_tries.get(WHO))
    code, out = call('/api/notifier/app', key=KEY)
    check(code == 403, 'the key fetches the admin road: %s %r' % (code, out))

    print('the admin download')
    check('/api/notifier/app' in zigmon.ApiHandler.ALWAYS_LOCKED, 'not among the locked reads')
    code, h, body = raw('/api/notifier/app', session=S)
    check(code == 200 and file_ok(h, body), 'admin download: %s %r' % (code, h))
    code, h, body = raw('/api/notifier/app', session=SO)
    check(code == 403 and EXE[:100] not in body, 'operator download: %s' % code)
    code, h, body = raw('/api/notifier/app')
    check(code == 403 and EXE[:100] not in body, 'nobody downloads: %s' % code)

    def unavailable(what):
        code, out = call('/api/notifier/update', key=KEY)
        check(code == 200 and out == {'ok': True, 'available': False}, '%s: update %s %r' % (what, code, out))
        code, h, body = raw('/api/notifier/download', key=KEY)
        check(code == 404 and b'not in this package' in body, '%s: download %s %r' % (what, code, body[:100]))
        code, out = call('/api/notifier/hello', key=KEY)
        check(code == 200 and 'app' in out and out['app'] is None, '%s: hello.app %r' % (what, out.get('app')))
        code, out = call('/api/notifier/keys', session=S)
        check('app' in out and out['app'] is None, '%s: keys.app %r' % (what, out.get('app')))
        code, h, body = raw('/api/notifier/app', session=S)
        check(code == 404, '%s: admin download %s' % (what, code))

    print('an exe of another size')
    LOG.clear()
    dist(DIST, man=manifest(EXE, size=len(EXE) + 1))
    unavailable('size')
    check(len(warnings()) == 1 and 'bytes' in warnings()[0], 'the warning for the size: %r' % warnings())
    print('an exe of another SHA-256')
    LOG.clear()
    dist(DIST, man=manifest(EXE, sha='0' * 64))
    unavailable('sha')
    check(len(warnings()) == 1 and 'SHA-256' in warnings()[0], 'the warning for the hash: %r' % warnings())
    print('no signature')
    LOG.clear()
    dist(DIST, with_sig=False)
    unavailable('no sig')
    check(not warnings(), 'a missing file is not a warning: %r' % warnings())
    (DIST / 'notifier.json.sig').write_bytes(b'short')
    unavailable('a short sig')
    print('nothing there at all')
    zigmon.CONFIG['notifier_dir'] = str(W / 'empty')
    unavailable('empty')
    zigmon.CONFIG['notifier_dir'] = str(DIST)
    print('the files again (a new version)')
    EXE2 = EXE + b'-1.2.0'
    dist(DIST, exe=EXE2, man=manifest(EXE2, version='1.2.0'))
    code, out = call('/api/notifier/update', key=KEY)
    check(out.get('available') is True and out.get('version') == '1.2.0' and out.get('size') == len(EXE2),
          'the new files are not seen: %r' % out)
    dist(DIST)                                            # back to 1.1.0 for the rest
    code, out = call('/api/notifier/hello', key=KEY)
    check(out.get('app') == {'version': '1.1.0'}, 'back to 1.1.0: %r' % out.get('app'))

    print('where the daemon looks')
    if not check(hasattr(d, 'notifier_app_dir'), 'the daemon does not look for the app'):
        raise SystemExit(1)
    zigmon.CONFIG['notifier_dir'] = ''
    fake_here = W / 'tree'
    (fake_here / 'windows' / 'dist').mkdir(parents=True)
    real_realpath = zigmon.os.path.realpath
    zigmon.os.path.realpath = lambda p, *a, **k: str(fake_here / 'zigmon.py') if p == zigmon.__file__ else real_realpath(p, *a, **k)
    try:
        check(d.notifier_app_dir() == fake_here / 'notifier', 'nothing anywhere: %s' % d.notifier_app_dir())
        dist(fake_here / 'windows' / 'dist')
        check(d.notifier_app_dir() == fake_here / 'windows' / 'dist', 'the source tree: %s' % d.notifier_app_dir())
        dist(fake_here / 'notifier')
        check(d.notifier_app_dir() == fake_here / 'notifier', 'as installed: %s' % d.notifier_app_dir())
    finally:
        zigmon.os.path.realpath = real_realpath
    zigmon.CONFIG['notifier_dir'] = str(DIST)

    print('the relay')
    page = (HERE / 'web' / 'index.php').read_text()
    for words in ("'update', 'download'", "$what === 'notifier-app'", 'zigmon_relay_download', 'Get the app',
                  'The app is not in this package.', 'dotnet.microsoft.com/download/dotnet/10.0'):
        check(words in page, 'the page has no %s' % words)
    shutil.copytree(HERE / 'web', W / 'web')
    api_php = (W / 'web' / 'zigmon-api.php').read_text()
    api_php = api_php.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
    api_php = api_php.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
    (W / 'web' / 'zigmon-api.php').write_text(api_php)
    php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, str(W / 'web' / 'index.php')], cwd=str(W / 'web'),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                           env=dict(os.environ, PHP_CLI_SERVER_WORKERS='4'))
    PROCS.append(php)
    for _ in range(50):
        try:
            socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)

    def relay(query, key=None, cookie=None):
        headers = {'User-Agent': 'ZigmonNotifier/1.1.0 (Windows)'}
        if key is not None:
            headers['X-Zigmon-Notifier'] = key
        if cookie:
            headers['Cookie'] = 'zigmon_session=' + cookie
        req = urllib.request.Request('http://127.0.0.1:%d/index.php?%s' % (PHP_PORT, query), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    code, h, body = relay('api=notifier&do=update', key=KEY)
    out = json.loads(body or b'{}')
    check(code == 200 and out.get('available') is True and base64.b64decode(out.get('manifest') or '') == MAN
          and base64.b64decode(out.get('sig') or '') == SIG, 'update through the relay: %s %r' % (code, body[:200]))
    code, h, body = relay('api=notifier&do=download', key=KEY)
    check(code == 200 and file_ok(h, body), 'download through the relay: %s %r %d' % (code, h, len(body)))
    code, h, body = relay('api=notifier&do=download', key='zmn_' + 'D' * 40)
    check(code == 401 and EXE[:100] not in body and json.loads(body or b'{}').get('ok') is False
          and 'json' in h.get('Content-Type', ''), 'a wrong key through the relay: %s %r %r' % (code, h, body[:120]))
    code, h, body = relay('api=notifier&do=upgrade', key=KEY)
    check(code == 400, 'another do: %s' % code)
    code, h, body = relay('api=notifier-app', cookie=S)
    check(code == 200 and file_ok(h, body), 'the admin download through the relay: %s %r' % (code, h))
    code, h, body = relay('api=notifier-app', cookie=SO)
    check(code == 403 and EXE[:100] not in body, 'an operator through the relay: %s' % code)
    code, h, body = relay('api=notifier-app')
    check(code == 403 and EXE[:100] not in body and 'json' in h.get('Content-Type', ''),
          'signed out through the relay: %s %r' % (code, body[:100]))
    req = urllib.request.Request('http://127.0.0.1:%d/index.php?api=notifier-app' % PHP_PORT,
                                 headers={'Cookie': 'zigmon_session=' + S, 'Sec-Fetch-Site': 'same-site'})
    try:
        urllib.request.urlopen(req, timeout=20)
        check(False, 'another site\'s page fetched the app with the cookie')
    except urllib.error.HTTPError as e:
        check(e.code == 403, 'another site: %s' % e.code)

    print('the page')
    SHOTS.mkdir(parents=True, exist_ok=True)
    js = r'''
const { chromium } = require('playwright');
const job = %(job)s;
(async () => {
  const b = await chromium.launch();
  const r = {errors: []};
  for (const shot of job.shots) {
    const ctx = await b.newContext({viewport: {width: shot.w, height: shot.h}, colorScheme: 'dark', acceptDownloads: true});
    await ctx.addCookies([{name: 'zigmon_session', value: job.s, url: 'http://127.0.0.1:' + job.port + '/'}]);
    const p = await ctx.newPage();
    p.on('pageerror', e => r.errors.push(String(e)));
    await p.goto('http://127.0.0.1:' + job.port + '/#control/msg-desktop');
    await p.waitForTimeout(2000);
    try { await p.evaluate(() => showControlSection('msg-desktop')); } catch (e) {}
    await p.waitForSelector('#ntf-host #ntf-get', {timeout: 15000});
    await p.waitForTimeout(400);
    const x = r[shot.n] = await p.evaluate(() => ({
      text: document.querySelector('#ntf-get').textContent,
      button: (document.querySelector('#ntf-download') || {}).textContent || '',
      primary: !!document.querySelector('#ntf-download.btn.primary svg'),
      sha: (document.querySelector('#ntf-sha .v') || {}).textContent || '',
      link: (document.querySelector('#ntf-get a') || {}).href || '',
      foot: (document.querySelector('#ntf-host .ntf-foot') || {}).textContent || '',
      wide: document.documentElement.scrollWidth, view: window.innerWidth,
      boxw: document.querySelector('#ntf-get').getBoundingClientRect().right}));
    await (await p.$('#ntf-get')).scrollIntoViewIfNeeded();
    await p.screenshot({path: job.dir + '/' + shot.n + '.png', fullPage: shot.full});
    await (await p.$('#ntf-card')).screenshot({path: job.dir + '/' + shot.n + '-card.png'});
    if (shot.dl) {
      const [dl] = await Promise.all([p.waitForEvent('download', {timeout: 15000}), p.click('#ntf-download')]);
      x.dlname = dl.suggestedFilename();
      const fs = require('fs');
      x.dlsize = fs.statSync(await dl.path()).size;
    }
    await ctx.close();
  }
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
    npm_root = sh(['npm', 'root', '-g']).stdout.strip()

    def browse(shots):
        (W / 'page.js').write_text(js % {'job': json.dumps({'s': S, 'port': PHP_PORT, 'dir': str(SHOTS), 'shots': shots})})
        got = sh(['node', str(W / 'page.js')], timeout=240, env=dict(os.environ, NODE_PATH=npm_root))
        try:
            return json.loads(got.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return {'error': (got.stdout + got.stderr)[-400:]}

    r = browse([{'n': 'desktop', 'w': 1400, 'h': 1000, 'full': False, 'dl': True},
                {'n': 'phone', 'w': 390, 'h': 1600, 'full': True, 'dl': False}])
    if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
        print('  SKIPPED (no browser here): %s' % r['error'][:200])
    else:
        check(not r.get('error'), 'the page: %r' % r.get('error'))
        for n in ('desktop', 'phone'):
            x = r.get(n) or {}
            check(x.get('button', '').strip() == 'Download ZIGMon Notifier 1.1.0 for Windows' and x.get('primary'),
                  '%s: the button: %r' % (n, x.get('button')))
            check(x.get('sha') == SHA, '%s: the SHA-256: %r' % (n, x.get('sha')))
            check('Get the app' in x.get('text', '') and '.NET 10 Desktop Runtime' in x.get('text', '')
                  and 'updates itself from this server' in x.get('text', '') and '300.' in x.get('text', ''),
                  '%s: the words: %r' % (n, x.get('text')))
            check(x.get('link') == 'https://dotnet.microsoft.com/download/dotnet/10.0', '%s: the link %r' % (n, x.get('link')))
            check('Download the app above' in x.get('foot', ''), '%s: the foot: %r' % (n, x.get('foot')))
            check(x.get('wide', 9999) <= x.get('view', 0) + 1 and x.get('boxw', 9999) <= x.get('view', 0) + 1,
                  '%s: scrolls sideways: %r' % (n, x))
        dk = r.get('desktop') or {}
        check(dk.get('dlname') == 'ZigmonNotifier.exe' and dk.get('dlsize') == len(EXE),
              'the button\'s download: %r %r' % (dk.get('dlname'), dk.get('dlsize')))
        check(not r.get('errors'), 'the page threw: %r' % r.get('errors'))
        zigmon.CONFIG['notifier_dir'] = str(W / 'empty')
        r = browse([{'n': 'none-desktop', 'w': 1400, 'h': 1000, 'full': False, 'dl': False},
                    {'n': 'none-phone', 'w': 390, 'h': 1600, 'full': True, 'dl': False}])
        zigmon.CONFIG['notifier_dir'] = str(DIST)
        for n in ('none-desktop', 'none-phone'):
            x = r.get(n) or {}
            check('The app is not in this package.' in x.get('text', '') and not x.get('button'),
                  '%s: without the app: %r' % (n, x.get('text')))
            check(x.get('wide', 9999) <= x.get('view', 0) + 1, '%s: scrolls sideways' % n)
            check(x.get('foot', '').startswith('In the app: right-click'), '%s: the foot: %r' % (n, x.get('foot')))
        check(not r.get('errors'), 'the page threw without the app: %r' % r.get('errors'))
        print('  screenshots: %s' % SHOTS)
finally:
    for p in PROCS:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    try:
        api.stop()
    except Exception:                                       # noqa: BLE001
        pass
zigmon.log = _real_log

# ---- install.sh ---------------------------------------------------------------------------------
print('install.sh')
src_text = (HERE / 'install.sh').read_text()
check(re.search(r'install_program\(\) \{[^}]*install_notifier_app', src_text, re.S),
      'install_program does not put the app in (install and --upgrade both run it)')
inst = W / 'install-functions.sh'
inst.write_text('\n'.join(src_text.splitlines()[:-1]) + '\n')
ISRC, ILIB = W / 'isrc', W / 'ilib'
dist(ISRC / 'windows' / 'dist')


def installer(fn, dry=False):
    script = 'source %s\nSOURCE_DIR=%s\nLIB_DIR=%s\nDRY_RUN=%s\n%s\n' % (inst, ISRC, ILIB, 'yes' if dry else '""', fn)
    return sh(['bash', '-c', script], timeout=60)


got = installer('install_notifier_app', dry=True)
check(got.returncode == 0 and not ILIB.exists() and '[would run] install -m 644' in got.stdout
      and 'notifier.json.sig' in got.stdout, 'the dry run: %s %s' % (got.stdout[-300:], got.stderr[-300:]))
got = installer('install_notifier_app')
nd = ILIB / 'notifier'
check(got.returncode == 0 and all((nd / n).read_bytes() == (ISRC / 'windows' / 'dist' / n).read_bytes()
                                  for n in ('ZigmonNotifier.exe', 'notifier.json', 'notifier.json.sig')),
      'the files were not copied: %s %s' % (got.stdout[-300:], got.stderr[-300:]))
check(nd.is_dir() and (nd.stat().st_mode & 0o777) == 0o755
      and all(((nd / n).stat().st_mode & 0o777) == 0o644 for n in ('ZigmonNotifier.exe', 'notifier.json', 'notifier.json.sig')),
      'the modes: %o %r' % (nd.stat().st_mode & 0o777, [oct((nd / n).stat().st_mode & 0o777) for n in os.listdir(nd)]))
check('ZIGMon Notifier 1.1.0' in got.stdout, 'it does not say which: %s' % got.stdout[-200:])
# a newer one replaces it
EXE3 = EXE + b'-1.3.0'
dist(ISRC / 'windows' / 'dist', exe=EXE3, man=manifest(EXE3, version='1.3.0'))
got = installer('install_notifier_app')
check((nd / 'ZigmonNotifier.exe').read_bytes() == EXE3, 'the newer one did not replace the old')
# the daemon, pointed at it, offers it
zigmon.CONFIG['notifier_dir'] = str(nd)
check((d.notifier_app_short() or {}).get('version') == '1.3.0', 'the daemon does not read what install.sh put')
# the package without one (or without its signature): the old files go
(ISRC / 'windows' / 'dist' / 'notifier.json.sig').unlink()
got = installer('install_notifier_app', dry=True)
check(got.returncode == 0 and (nd / 'ZigmonNotifier.exe').exists() and '[would run] rm -f' in got.stdout,
      'the dry run of taking it away: %s' % got.stdout[-300:])
got = installer('install_notifier_app')
check(got.returncode == 0 and not any(nd.iterdir()), 'a stale app is left: %r %s' % (os.listdir(nd), got.stdout[-200:]))
check(d.notifier_app_short() is None, 'the daemon still offers what is gone')
shutil.rmtree(ISRC / 'windows')
got = installer('install_notifier_app')
check(got.returncode == 0, 'no windows/dist at all: %s %s' % (got.stdout[-200:], got.stderr[-200:]))

# ---- tools/make-release.sh ------------------------------------------------------------------------
print('tools/make-release.sh')
if not shutil.which('git'):
    print('  SKIPPED (no git)')
else:
    def tree(name, files=None, sig=None):
        """A copy of the files git has (not release/), with the throwaway key among the release
        keys, committed - and windows/dist as given."""
        t = W / name
        t.mkdir()
        listed = sh(['git', 'ls-files', '-z'], cwd=str(HERE)).stdout.split('\0')
        for f in listed:
            if not f or f.startswith('release/') or not (HERE / f).is_file():
                continue
            (t / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(HERE / f, t / f)
        if (t / 'windows' / 'dist').exists():
            shutil.rmtree(t / 'windows' / 'dist')
        shutil.copy(TPUB, t / 'deploy' / 'release-keys' / 'zigmon-test-throwaway.pub')
        if files:
            dist(t / 'windows' / 'dist', with_sig=False)
            if sig is not None:
                (t / 'windows' / 'dist' / 'notifier.json.sig').write_bytes(sig)
        env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid', GIT_COMMITTER_NAME='t',
                   GIT_COMMITTER_EMAIL='t@example.invalid')
        for cmd in (['git', 'init', '-q'], ['git', 'add', '-A'], ['git', 'commit', '-q', '-m', 'test']):
            r = sh(cmd, cwd=str(t), env=env)
            assert r.returncode == 0, r.stderr
        return t

    def release(t):
        return sh(['bash', str(t / 'tools' / 'make-release.sh'), str(TKEY)], cwd=str(t), timeout=300)

    V = zigmon.__version__

    def package_has(t, rel):
        with tarfile.open(t / 'release' / ('zigmon-%s.tar.gz' % V)) as tar:
            names = tar.getnames()
            man = tar.extractfile('zigmon-%s/MANIFEST' % V).read().decode()
            body = tar.extractfile('zigmon-%s/%s' % (V, rel)).read() if 'zigmon-%s/%s' % (V, rel) in names else None
        return body, ('  ' + rel + '\n') in man

    # no windows/dist: as before
    t = tree('rel-none')
    got = release(t)
    check(got.returncode == 0 and 'signed by' in got.stdout and 'notifier' not in got.stdout,
          'a release without the app: %s %s' % (got.stdout[-500:], got.stderr[-500:]))
    # no signature yet: made, verified, in the package, and to be committed
    t = tree('rel-unsigned', files=True)
    got = release(t)
    out = got.stdout
    sigf = t / 'windows' / 'dist' / 'notifier.json.sig'
    check(got.returncode == 0 and sigf.is_file() and verifies(t / 'windows' / 'dist' / 'notifier.json', sigf),
          'the manifest was not signed: %s %s' % (out[-600:], got.stderr[-400:]))
    check('notifier.json signed by zigmon-test-throwaway' in out and 'must be committed' in out
          and re.search(r'now: .*git add .* windows/dist/notifier\.json\.sig', out), 'what it says: %s' % out[-600:])
    body, listed = package_has(t, 'windows/dist/notifier.json.sig')
    check(body == sigf.read_bytes() and listed, 'the signature is not in the package or its MANIFEST')
    body, listed = package_has(t, 'windows/dist/ZigmonNotifier.exe')
    check(body == EXE and listed, 'the exe is not in the package')
    # a signature by another key: made again
    (W / 'o.json').write_bytes(MAN)
    sign(W / 'o.json', W / 'o.sig', key=OKEY)
    t = tree('rel-other', files=True, sig=(W / 'o.sig').read_bytes())
    got = release(t)
    sigf = t / 'windows' / 'dist' / 'notifier.json.sig'
    check(got.returncode == 0 and verifies(t / 'windows' / 'dist' / 'notifier.json', sigf)
          and 'windows/dist/notifier.json.sig' in got.stdout.splitlines()[-1],
          'a signature by another key is not made again: %s %s' % (got.stdout[-500:], got.stderr[-300:]))
    # signed already by this key: left as it is, nothing to commit
    sign(W / 'o.json', W / 't.sig')
    t = tree('rel-signed', files=True, sig=(W / 't.sig').read_bytes())
    got = release(t)
    check(got.returncode == 0 and (t / 'windows' / 'dist' / 'notifier.json.sig').read_bytes() == (W / 't.sig').read_bytes()
          and 'must be committed' not in got.stdout and 'notifier.json.sig' not in got.stdout.splitlines()[-1]
          and 'notifier.json signed by zigmon-test-throwaway' in got.stdout,
          'a good signature: %s %s' % (got.stdout[-500:], got.stderr[-300:]))
    # an exe that is not the one described: refused
    t = tree('rel-bad', files=True)
    (t / 'windows' / 'dist' / 'ZigmonNotifier.exe').write_bytes(EXE + b'x')
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid', GIT_COMMITTER_NAME='t',
               GIT_COMMITTER_EMAIL='t@example.invalid')
    sh(['git', 'commit', '-q', '-am', 'bad'], cwd=str(t), env=env)
    got = release(t)
    check(got.returncode != 0 and 'does not describe' in (got.stdout + got.stderr)
          and not (t / 'release' / ('zigmon-%s.tar.gz' % V)).exists(), 'a wrong exe was released: %s' % got.stdout[-300:])

shutil.rmtree(W, ignore_errors=True)
if bad:
    print('%d FAILED' % len(bad))
    sys.exit(1)
print('all good')
