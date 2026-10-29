#!/usr/bin/env python3
"""A new version from the web (5.21): upgrade_url looked at, a package fetched
and taken exactly as one sent by hand is. Nothing leaves the machine - the
one function that asks the network, _online_get, is replaced by fixtures, and
where its own checks are what is being tested, urllib's urlopen is.

  * a GitHub folder through GitHub's contents API, and through the folder's
    own page when the API refuses; an nginx folder listing; a JSON list; one
    package's own address, and a GitHub page of one read as the raw file -
    each newest first, a link that is not https never offered;
  * http:// refused, and so is an https:// address that sends the request on
    to plain http; an answer bigger than allowed refused, a package streamed
    to disk rather than read into memory;
  * the look kept, and a newer version said once - not again on the next look;
  * a package signed by the test's own release key fetched and left in the
    very state an uploaded one is in: the same package.json, the same check
    by zigmon_upgrade.py --inspect; an unsigned one, one older than what
    runs, and one holding another version than it was offered as - refused,
    with nothing left behind;
  * the API: Look now and Fetch as an administrator, not as an operator,
    and the state of the page carrying what was found; fetch-and-upgrade
    asks root for the upgrade; nothing while an upgrade is going on;
  * the daily look: off when switched off, not again within the day, again
    when the address changed; and the address must be https.

    python3 test/online.py
"""
import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-online-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ---- a release key of the test's own, and packages signed by it ---------------------
STATE, ETC, KEYS = W / 'state', W / 'etc', W / 'release-keys'
for d in (STATE, ETC, KEYS):
    d.mkdir(parents=True)
rel_key = W / 'release.key'
sh(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', str(rel_key)])
sh(['openssl', 'pkey', '-in', str(rel_key), '-pubout', '-out', str(KEYS / 'zigmon-release-test.pub')])
(ETC / 'config.json').write_text(json.dumps({'db_file': str(STATE / 'history.db')}))
# ZIGMON_LIB is this folder: the version "installed" is the one being tested
os.environ.update(ZIGMON_RELEASE_KEYS=str(KEYS), ZIGMON_LIB=str(HERE), ZIGMON_STATE=str(STATE),
                  ZIGMON_CONFIG=str(ETC / 'config.json'), ZIGMON_NO_SERVICES='1',
                  ZIGMON_UPGRADE_RUN='true')


def package(version, unsigned=False, says=None):
    """zigmon-VERSION.tar.gz as a release is made: a MANIFEST of every file
    and its Ed25519 signature. `says` is the version its zigmon.py claims."""
    top = 'zigmon-%s' % (says or version)
    d = W / 'build' / ('%s-%s' % (version, 'u' if unsigned else 's')) / top
    d.mkdir(parents=True)
    (d / 'zigmon.py').write_text("#!/usr/bin/python3\n__version__ = '%s'\n" % (says or version))
    (d / 'README.md').write_text('Current version: **%s**\n\n%s — fetched from the web.\n\n'
                                 'It changed this.\n' % (says or version, says or version))
    (d / 'install.sh').write_text('#!/bin/bash\necho "==> Program files"\n')
    lines = ['%s  %s' % (hashlib.sha256(p.read_bytes()).hexdigest(), p.relative_to(d).as_posix())
             for p in sorted(x for x in d.rglob('*') if x.is_file())]
    (d / 'MANIFEST').write_text('\n'.join(lines) + '\n')
    if not unsigned:
        sh(['openssl', 'pkeyutl', '-sign', '-inkey', str(rel_key), '-rawin',
            '-in', str(d / 'MANIFEST'), '-out', str(d / 'MANIFEST.sig')])
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as t:
        t.add(d, arcname=top)
    return buf.getvalue()


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(STATE / 'history.db'), 'api_port': 19974, 'token_file': str(W / 'token'),
                      'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(STATE)})
HAVE = zigmon.__version__
MAJOR = int(HAVE.split('.')[0])
NEWER, NEWEST, OLDER = '%d.0.0' % (MAJOR + 1), '%d.1.0' % (MAJOR + 1), '1.0.0'

# ---- the network, stood in for -------------------------------------------------------
REAL_GET = zigmon._online_get
WEB = {}      # address -> (bytes, content type, final address) or an exception
ASKED = []


def fake_get(url, limit=zigmon.ONLINE_PAGE_MOST, accept='*/*', timeout=30, into=None):
    ASKED.append((url, accept))
    if not str(url).startswith('https://'):
        raise ValueError('only https:// addresses are asked: %s' % url)
    if url not in WEB:
        raise urllib.error.URLError('nothing at %s' % url)
    got = WEB[url]
    if isinstance(got, Exception):
        raise got
    data, ct, final = got
    if into is not None:
        Path(into).write_bytes(data)
        return None, ct, final
    return data, ct, final


zigmon._online_get = fake_get
GH = 'https://github.com/falco81/ZIGMon/tree/main/release'
API = 'https://api.github.com/repos/falco81/ZIGMon/contents/release?ref=main'
RAW = 'https://raw.githubusercontent.com/falco81/ZIGMon/main/release/'

print('reading what is published')
WEB[API] = (json.dumps([
    {'type': 'file', 'name': 'zigmon-%s.tar.gz' % NEWER, 'download_url': RAW + 'zigmon-%s.tar.gz' % NEWER, 'size': 1234},
    {'type': 'file', 'name': 'zigmon-%s.tar.gz' % OLDER, 'download_url': RAW + 'zigmon-%s.tar.gz' % OLDER},
    {'type': 'file', 'name': 'zigmon-%s.tar.gz' % NEWEST, 'download_url': RAW + 'zigmon-%s.tar.gz' % NEWEST},
    {'type': 'file', 'name': 'README.md', 'download_url': RAW + 'README.md'},
    {'type': 'dir', 'name': 'zigmon-8.8.8.tar.gz', 'download_url': None},
    {'type': 'file', 'name': 'zigmon-77.0.0.tar.gz', 'download_url': 'http://evil.example/zigmon-77.0.0.tar.gz'},
]).encode(), 'application/json', API)
got = zigmon.online_list(GH)
check([p['version'] for p in got] == [NEWEST, NEWER, OLDER],
      'a GitHub folder did not read as its packages, newest first: %r' % got)
check(got and got[0]['url'] == RAW + 'zigmon-%s.tar.gz' % NEWEST and got[1]['bytes'] == 1234,
      'a GitHub folder gave the wrong address or size: %r' % got[:2])
check((API, 'application/vnd.github+json') in ASKED, 'GitHub\'s API was not asked as its API: %r' % ASKED)
check(not any('evil' in p['url'] for p in got), 'a package on a plain http address was offered')

# GitHub's API refusing (sixty questions an hour): the folder's own page
WEB[API] = urllib.error.HTTPError(API, 403, 'rate limit exceeded', {}, None)
WEB[GH] = ((('<html><a href="/falco81/ZIGMon/blob/main/release/zigmon-%s.tar.gz">zigmon-%s.tar.gz</a>'
            '<a href="x">zigmon-%s.tar.gz</a></html>') % (NEWER, NEWER, NEWEST)).encode(), 'text/html', GH)
got = zigmon.online_list(GH)
check([p['version'] for p in got] == [NEWEST, NEWER] and got[0]['url'] == RAW + 'zigmon-%s.tar.gz' % NEWEST,
      'with GitHub\'s API refusing, the folder\'s page was not read: %r' % got)
del WEB[GH]
try:
    zigmon.online_list(GH)
    check(False, 'neither GitHub\'s API nor its page answering was not said')
except ValueError as e:
    check('GitHub did not answer' in str(e), 'GitHub not answering said the wrong thing: %s' % e)

# a folder listing of nginx's own
NG = 'https://dl.example.org/zigmon/'
WEB[NG] = ((('<html><head><title>Index of /zigmon/</title></head><body><h1>Index of /zigmon/</h1><hr><pre>'
            '<a href="../">../</a>\n'
            '<a href="zigmon-%s.tar.gz">zigmon-%s.tar.gz</a>   28-Oct-2026 10:00   812345\n'
            '<a href="zigmon-%s.tar.gz">zigmon-%s.tar.gz</a>   29-Oct-2026 10:00   812999\n'
            '<a href="zigmon-%s.tar.gz.sig">zigmon-%s.tar.gz.sig</a>\n'
            '<a href="http://plain.example.org/zigmon-66.0.0.tar.gz">elsewhere</a>\n'
            '<a href="notes.txt">notes.txt</a>\n</pre><hr></body></html>')
           % (NEWER, NEWER, NEWEST, NEWEST, NEWEST, NEWEST)).encode(), 'text/html', NG)
got = zigmon.online_list(NG)
check([(p['version'], p['url']) for p in got] == [(NEWEST, NG + 'zigmon-%s.tar.gz' % NEWEST),
                                                  (NEWER, NG + 'zigmon-%s.tar.gz' % NEWER)],
      'an nginx folder listing did not read as its packages, newest first: %r' % got)

# a JSON list of a server of somebody's own
JS = 'https://updates.example.org/zigmon.json'
WEB[JS] = (json.dumps([{'name': 'zigmon-%s.tar.gz' % NEWER, 'url': 'files/zigmon-%s.tar.gz' % NEWER, 'size': 5}])
           .encode(), 'application/json', JS)
got = zigmon.online_list(JS)
check(len(got) == 1 and got[0]['url'] == 'https://updates.example.org/files/zigmon-%s.tar.gz' % NEWER,
      'a JSON list was not read: %r' % got)

# one package's own address, and a GitHub page of one read as the raw file
ONE = 'https://dl.example.org/zigmon/zigmon-%s.tar.gz' % NEWER
got = zigmon.online_list(ONE)
check(len(got) == 1 and got[0]['url'] == ONE and got[0]['version'] == NEWER,
      'one package\'s own address was not taken as it is: %r' % got)
BLOB = 'https://github.com/falco81/ZIGMon/blob/main/release/zigmon-%s.tar.gz' % NEWER
got = zigmon.online_list(BLOB)
check(len(got) == 1 and got[0]['url'] == RAW + 'zigmon-%s.tar.gz' % NEWER,
      'a GitHub page of a package was not read as the raw file: %r' % got)

# ---- https, the whole way ---------------------------------------------------------
print('https only')
for what, call in (('online_list', lambda: zigmon.online_list('http://dl.example.org/zigmon/')),
                   ('_online_get', lambda: REAL_GET('http://dl.example.org/zigmon/'))):
    try:
        call()
        check(False, '%s asked a plain http address' % what)
    except ValueError as e:
        check('https' in str(e), '%s refused http for the wrong reason: %s' % (what, e))


class Answer(object):
    """What urlopen hands back, for a final address and a body."""
    def __init__(self, final, body):
        self.final, self.body, self.headers = final, io.BytesIO(body), {'Content-Type': 'text/html'}

    def geturl(self):
        return self.final

    def read(self, n=-1):
        return self.body.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


SENT = {}
real_urlopen = urllib.request.urlopen


def fake_urlopen(req, timeout=None, context=None):
    SENT['ua'] = req.get_header('User-agent')
    return SENT['answer']


urllib.request.urlopen = fake_urlopen
try:
    SENT['answer'] = Answer('http://dl.example.org/zigmon/', b'<a href="zigmon-9.9.9.tar.gz">x</a>')
    try:
        REAL_GET('https://dl.example.org/zigmon/')
        check(False, 'a redirect to plain http was followed')
    except ValueError as e:
        check('not https' in str(e), 'a redirect to http was refused for the wrong reason: %s' % e)
    check(SENT.get('ua') == 'zigmon/%s (+upgrade check)' % HAVE, 'the user agent is %r' % SENT.get('ua'))
    SENT['answer'] = Answer('https://dl.example.org/zigmon/', b'x' * 2048)
    try:
        REAL_GET('https://dl.example.org/zigmon/', limit=1024)
        check(False, 'an answer bigger than allowed was taken')
    except ValueError as e:
        check('bigger' in str(e), 'an answer too big was refused for the wrong reason: %s' % e)
    SENT['answer'] = Answer('https://dl.example.org/zigmon/x.tar.gz', b'y' * (600 * 1024))
    into = W / 'streamed'
    data, _ct, final = REAL_GET('https://dl.example.org/zigmon/x.tar.gz', limit=1024 * 1024, into=into)
    check(data is None and into.stat().st_size == 600 * 1024 and final.startswith('https://'),
          'a package was not streamed to disk: %r %s' % (data, into.stat().st_size if into.exists() else None))
    SENT['answer'] = Answer('https://dl.example.org/zigmon/x.tar.gz', b'y' * (600 * 1024))
    try:
        REAL_GET('https://dl.example.org/zigmon/x.tar.gz', limit=512 * 1024, into=into)
        check(False, 'a package bigger than allowed was written to disk whole')
    except ValueError:
        pass
finally:
    urllib.request.urlopen = real_urlopen

# ---- the daemon: the look, said once ----------------------------------------------
print('looking, and saying it once')
d = zigmon.Daemon()
WEB[API] = (json.dumps([
    {'type': 'file', 'name': 'zigmon-%s.tar.gz' % NEWER, 'download_url': RAW + 'zigmon-%s.tar.gz' % NEWER},
    {'type': 'file', 'name': 'zigmon-%s.tar.gz' % OLDER, 'download_url': RAW + 'zigmon-%s.tar.gz' % OLDER},
]).encode(), 'application/json', API)
zigmon.CONFIG['upgrade_url'] = GH


def outs():
    d.store.flush()
    return [e for e in d.store.events(limit=200) if 'is out' in str(e.get('detail'))]


row = d.online_look('a test')
check(row.get('newer') and row['newest']['version'] == NEWER and not row.get('error'),
      'the look did not find the newer version: %r' % row)
check(len(outs()) == 1, 'a newer version was not said as an event: %r' % outs())
d.online_look('a test')
check(len(outs()) == 1, 'the same newer version was said again on the next look')
view = d.online_view()
check(view['online'].get('newer') and view['url'] == GH and view['check'] is True,
      'what the page is given is not what was found: %r' % view)
check('web' in d.upgrade_state() and d.upgrade_state()['web']['online'].get('newest'),
      'the upgrade state does not carry what the web had')
WEB[API] = urllib.error.HTTPError(API, 500, 'down', {}, None)
row = d.online_look('a test')
check(row.get('error') and 'GitHub did not answer' in row['error'], 'a failed look was not kept: %r' % row)

# ---- fetched: the road of a package sent by hand ----------------------------------
print('fetching')
zigmon.CONFIG['upgrade_url'] = NG
WEB[NG] = ((('<a href="zigmon-%s.tar.gz">a</a><a href="zigmon-%s.tar.gz">b</a><a href="zigmon-%s.tar.gz">c</a>'
            '<a href="zigmon-%s.tar.gz">d</a>') % (NEWER, OLDER, NEWEST, HAVE)).encode(), 'text/html', NG)
WEB[NG + 'zigmon-%s.tar.gz' % NEWEST] = (package(NEWEST, unsigned=True), 'application/gzip',
                                          NG + 'zigmon-%s.tar.gz' % NEWEST)
WEB[NG + 'zigmon-%s.tar.gz' % NEWER] = (package(NEWER, says='%d.0.1' % (MAJOR + 1)), 'application/gzip',
                                         NG + 'zigmon-%s.tar.gz' % NEWER)
WEB[NG + 'zigmon-%s.tar.gz' % OLDER] = (package(OLDER), 'application/gzip', NG + 'zigmon-%s.tar.gz' % OLDER)


def leftovers():
    return sorted(p.name for p in (STATE / 'upgrade').glob('*') if p.name.startswith('.online-')
                  or p.name.endswith('.tar.gz'))


for version, words, why in ((NEWEST, 'not signed', 'an unsigned package'),
                            (NEWER, 'holds', 'a package holding another version than it was offered as'),
                            (OLDER, 'not newer', 'an older version'),
                            (HAVE, 'not newer', 'the version that runs here'),
                            ('99.99.99', 'is not at', 'a version that is not there')):
    try:
        d.online_fetch(version, 'a test')
        check(False, '%s was taken' % why)
    except ValueError as e:
        check(words in str(e), '%s was refused for the wrong reason: %s' % (why, e))
    check(not leftovers() and d.upgrade_package() is None, '%s left something behind: %r' % (why, leftovers()))
d.store.flush()
check(any('was refused' in str(e.get('detail')) for e in d.store.events(limit=200)),
      'a refused package was not written down as an event')

good = package(NEWEST)
WEB[NG + 'zigmon-%s.tar.gz' % NEWEST] = (good, 'application/gzip', NG + 'zigmon-%s.tar.gz' % NEWEST)
pkg = d.online_fetch(NEWEST, 'a test')
check(pkg.get('version') == NEWEST and pkg.get('signed_by') == 'zigmon-release-test'
      and pkg.get('source') == NG + 'zigmon-%s.tar.gz' % NEWEST,
      'a signed package was not taken: %r' % pkg)
check(leftovers() == ['zigmon-%s.tar.gz' % NEWEST], 'what is left in the folder: %r' % leftovers())
check(pkg.get('sha') == hashlib.sha256(good).hexdigest(), 'the package kept is not the one fetched')
fetched = d.upgrade_package()
st = d.upgrade_state()
check(st['ready'] and fetched == pkg, 'a fetched package is not ready to be put in: %r' % st.get('not_ready'))

# the same package sent by hand: the same state, but for where it came from
d.upgrade_forget()
data = base64.b64encode(good).decode()
half = len(data) // 2 // 4 * 4
d.upgrade_upload(1, 2, data[:half], 'u1', 'a test')
d.upgrade_upload(2, 2, data[half:], 'u1', 'a test')
sent = d.upgrade_package()
same = {k: v for k, v in (sent or {}).items() if k not in ('at', 'source')}
check(same == {k: v for k, v in fetched.items() if k not in ('at', 'source')},
      'a fetched package is not in the state of one sent by hand:\n  %r\n  %r' % (fetched, sent))
d.upgrade_forget()

# ---- the API: an administrator's, and never during an upgrade ---------------------
print('the API')
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def call(path, body=None, session=None):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': '192.168.40.10'}
    if session:
        headers['X-Zigmon-Session'] = session
    req = urllib.request.Request('http://127.0.0.1:19974' + path, headers=headers,
                                 data=None if body is None else json.dumps(body).encode(),
                                 method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
S_OP = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''
for who, sess in (('nobody', None), ('an operator', S_OP)):
    for body in ({'action': 'online_look'}, {'action': 'online_get', 'version': NEWEST}):
        code, _ = call('/api/upgrade', dict(body, session=sess) if sess else body)
        check(code == 403, '%s asked %s and was answered %s' % (who, body['action'], code))
code, out = call('/api/upgrade', {'action': 'online_look', 'session': S})
check(code == 200 and out.get('web', {}).get('online', {}).get('newest', {}).get('version') == NEWEST,
      'Look now did not answer with what it found: %s %r' % (code, out.get('message') or out.get('error')))
check('%s is there' % NEWEST in str(out.get('message')), 'Look now said: %r' % out.get('message'))
# the command line asks the same road with root's own key, and says it in words
if zigmon.read_cli_key():
    import argparse
    import contextlib
    said = io.StringIO()
    with contextlib.redirect_stdout(said):
        rc = zigmon.cmd_upgrade_check(argparse.Namespace(json=False), zigmon.Palette(False))
    check(rc == 0 and 'zigmon %s is there' % NEWEST in said.getvalue() and 'not newer' in said.getvalue(),
          'zigmon --upgrade-check said: %r' % said.getvalue())
else:
    print('  (no command-line key here: zigmon --upgrade-check not run)')
code, out = call('/api/upgrade', {'action': 'online_get', 'version': NEWEST, 'session': S})
check(code == 200 and (out.get('package') or {}).get('version') == NEWEST and not (STATE / 'upgrade' / 'request.json').exists(),
      'Only fetch it did not fetch, or asked for the upgrade: %s %r' % (code, out.get('error')))
code, out = call('/api/upgrade', {'action': 'online_get', 'version': NEWEST, 'start': True, 'session': S})
req = json.loads((STATE / 'upgrade' / 'request.json').read_text()) if (STATE / 'upgrade' / 'request.json').exists() else {}
check(code == 200 and req.get('version') == NEWEST and req.get('sha') == hashlib.sha256(good).hexdigest(),
      'Upgrade now did not ask root for the fetched package: %s %r %r' % (code, out.get('error'), req))
code, out = call('/api/upgrade', {'action': 'online_look', 'session': S})
check(code == 400 and 'upgrade is going on' in str(out.get('error')),
      'a look was asked while an upgrade is going on: %s %r' % (code, out))
code, out = call('/api/upgrade', {'action': 'online_get', 'version': NEWEST, 'session': S})
check(code == 400, 'a fetch was asked while an upgrade is going on: %s' % code)
api.stop()

# ---- the daily look ----------------------------------------------------------------
print('the daily look')
(STATE / 'upgrade' / 'request.json').unlink()
(STATE / 'upgrade' / 'status.json').unlink()
looks = []
real_look = d.online_look
d.online_look = lambda by='': looks.append(by)


def tick():
    zigmon.ONLINE_WORK['at'] = 0.0
    d.online_tick()
    for _ in range(50):
        if not zigmon.ONLINE_WORK['busy']:
            break
        time.sleep(0.05)


zigmon.CONFIG['upgrade_check'] = 0
tick()
check(not looks, 'the daily look went on while it is switched off')
zigmon.CONFIG['upgrade_check'] = 1
tick()
check(not looks, 'the address was asked again within the day')
d.online_tick()
zigmon.CONFIG['upgrade_url'] = 'https://dl.example.org/other/'
tick()
check(len(looks) == 1, 'a changed address was not looked at: %r' % looks)
ZIGMON_ROW = d.online_row()
ZIGMON_ROW['url'], ZIGMON_ROW['at'] = zigmon.CONFIG['upgrade_url'], time.time() - zigmon.ONLINE_EVERY_S - 5
d.store.set_meta('upgrade_online', json.dumps(ZIGMON_ROW))
tick()
check(len(looks) == 2, 'a day after the last look, it was not looked at again: %r' % looks)
zigmon.ONLINE_WORK['at'] = time.time()
d.store.set_meta('upgrade_online', '{}')
d.online_tick()
check(len(looks) == 2, 'the look was asked again within five minutes')
d.online_look = real_look

# ---- the setting itself ------------------------------------------------------------
print('the setting')
for value, words in (('http://dl.example.org/', 'https://'), ('ftp://x/', 'https://'),
                     ('https://me:secret@dl.example.org/', 'no name or password')):
    try:
        d.save_config_overrides({'upgrade_url': value})
        check(False, 'upgrade_url took %s' % value)
    except ValueError as e:
        check(words in str(e), 'upgrade_url %s refused for the wrong reason: %s' % (value, e))
d.save_config_overrides({'upgrade_url': 'https://dl.example.org/zigmon/', 'upgrade_check': 0})
check(zigmon.CONFIG['upgrade_url'] == 'https://dl.example.org/zigmon/' and int(zigmon.CONFIG['upgrade_check']) == 0,
      'the two settings were not saved')
check(zigmon.DEFAULTS['upgrade_url'].startswith('https://github.com/') and zigmon.DEFAULTS['upgrade_check'] == 1,
      'the defaults are not where the releases are, looked at every day')

# ---- more than one newer version: which one is chosen -----------------------------
print('more than one newer version can be chosen from; one is offered as it was')
_now = zigmon._online_ver(zigmon.__version__)
_v = lambda add: '%d.%d.%d' % (_now[0], _now[1] + add, 0)
d.store.set_meta('upgrade_online', json.dumps({'at': time.time(), 'url': 'https://dl.example.org/',
    'newest': {'version': _v(2)}, 'packages': [{'version': _v(2), 'url': 'https://dl.example.org/a'},
                                               {'version': _v(1), 'url': 'https://dl.example.org/b'},
                                               {'version': zigmon.__version__, 'url': 'https://dl.example.org/c'}]}))
_row = d.online_view()['online']
check([x['version'] for x in _row.get('newer_list', [])] == [_v(2), _v(1)],
      'the newer versions are not all offered, newest first: %r' % _row.get('newer_list'))
d.store.set_meta('upgrade_online', '{}')
_page = (HERE / 'web' / 'index.php').read_text()
_draw = _page[_page.index('function drawUpWeb('):_page.index('function drawUpgrade(')]
check('many.length > 1' in _draw and 'zSelect(' in _draw,
      'the page offers no choice when more than one newer version is there')

shutil.rmtree(W, ignore_errors=True)
if bad:
    print('\n%d check(s) failed' % len(bad))
    sys.exit(1)
print('a new version is found on the web, fetched over https only, and taken only as a signed package '
      'sent by hand would be')
