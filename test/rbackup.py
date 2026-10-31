#!/usr/bin/env python3
"""Backups to other machines (5.21), the whole way round.

  * what is typed for a destination is refused when a tool on the way would
    read it as more than a value: ; and " in a folder, a leading -, .., a
    line break, an account that begins with -;
  * the old ones at a destination are taken away with their companions -
    never the newest, never another machine's, never a file somebody put
    there by hand (a transport of the test's own, in memory);
  * the schedule, with a clock of the test's own: not before the time, the
    right day of the week, once a day - and not again after a restart;
  * nothing is sent without the password;
  * no password, key or passphrase in what GET /api/rbackup answers, in the
    log or in the events;
  * a whole run against an FTP server started here: root (deploy/zigmon_root.py
    run as root would run it) makes the backup and locks it, it is sent with
    its .sha256 and RESTORE.txt, opens with openssl and the password, nothing
    is left behind here, the old ones there are taken away;
  * Backups there, Download, Delete, and Put this back - fetched and handed to
    root's full_put, which looks into it as it does an uploaded one;
  * SFTP against an sshd started here, when this machine has one.

    python3 test/rbackup.py
"""
import hashlib
import json
import os
import shutil
import socket
import socketserver
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ROOT_HELPER = HERE / 'deploy' / 'zigmon_root.py'
W = Path(tempfile.mkdtemp(prefix='zigmon-rbackup-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---- a small FTP server, in this process -------------------------------------------
# Enough of RFC 959 (and MLSD) for what ftplib asks: a folder of its own,
# one account, passive mode only.
class FtpHandler(socketserver.StreamRequestHandler):
    def say(self, line):
        self.wfile.write((line + '\r\n').encode())

    def here(self, name=''):
        p = (self.cwd / name).resolve() if name else self.cwd
        if not str(p).startswith(str(self.server.top)):
            raise PermissionError(name)
        return p

    def data(self):
        conn, _ = self.pasv.accept()
        self.pasv.close()
        self.pasv = None
        return conn

    def handle(self):
        self.cwd = self.server.top
        self.pasv = None
        self.user = ''
        self.authed = False
        rnfr = None
        self.say('220 zigmon check FTP')
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode('utf-8', 'replace').rstrip('\r\n')
            self.server.seen.append(line if not line.upper().startswith('PASS') else 'PASS ***')
            cmd, _, arg = line.partition(' ')
            cmd = cmd.upper()
            try:
                if cmd == 'USER':
                    self.user = arg
                    self.say('331 password please')
                elif cmd == 'PASS':
                    self.authed = (self.user, arg) == self.server.account
                    self.say('230 in' if self.authed else '530 Login incorrect.')
                elif cmd == 'QUIT':
                    self.say('221 bye')
                    return
                elif not self.authed:
                    self.say('530 sign in first')
                elif cmd in ('TYPE', 'OPTS'):
                    self.say('200 ok')
                elif cmd == 'PWD':
                    self.say('257 "/%s"' % self.cwd.relative_to(self.server.top))
                elif cmd == 'CWD':
                    p = self.server.top if arg == '/' else self.here(arg)
                    if p.is_dir():
                        self.cwd = p
                        self.say('250 ok')
                    else:
                        self.say('550 no such folder')
                elif cmd == 'MKD':
                    self.here(arg).mkdir()
                    self.say('257 made')
                elif cmd == 'PASV':
                    self.pasv = socket.socket()
                    self.pasv.bind(('127.0.0.1', 0))
                    self.pasv.listen(1)
                    port = self.pasv.getsockname()[1]
                    self.say('227 Entering Passive Mode (127,0,0,1,%d,%d)' % (port // 256, port % 256))
                elif cmd == 'STOR':
                    self.say('150 go')
                    conn = self.data()
                    with open(self.here(arg), 'wb') as f:
                        while True:
                            chunk = conn.recv(65536)
                            if not chunk:
                                break
                            f.write(chunk)
                    conn.close()
                    self.say('226 stored')
                elif cmd == 'RETR':
                    p = self.here(arg)
                    if not p.is_file():
                        self.say('550 no such file')
                        continue
                    self.say('150 go')
                    conn = self.data()
                    conn.sendall(p.read_bytes())
                    conn.close()
                    self.say('226 sent')
                elif cmd == 'MLSD':
                    self.say('150 go')
                    conn = self.data()
                    for p in sorted(self.cwd.iterdir()):
                        st = p.stat()
                        conn.sendall(('type=%s;size=%d;modify=%s; %s\r\n' % (
                            'file' if p.is_file() else 'dir', st.st_size,
                            time.strftime('%Y%m%d%H%M%S', time.gmtime(st.st_mtime)), p.name)).encode())
                    conn.close()
                    self.say('226 listed')
                elif cmd == 'DELE':
                    p = self.here(arg)
                    if p.is_file():
                        p.unlink()
                        self.say('250 deleted')
                    else:
                        self.say('550 no such file')
                elif cmd == 'RNFR':
                    rnfr = self.here(arg)
                    self.say('350 and to?' if rnfr.exists() else '550 no such file')
                elif cmd == 'RNTO':
                    os.replace(str(rnfr), str(self.here(arg)))
                    self.say('250 renamed')
                else:
                    self.say('502 not here')
            except (OSError, ValueError) as e:
                self.say('550 %s' % e.__class__.__name__)


class FtpServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


FTP_TOP = W / 'ftp-top'
FTP_TOP.mkdir()
ftpd = FtpServer(('127.0.0.1', 0), FtpHandler)
ftpd.top = FTP_TOP.resolve()
ftpd.account = ('backup', 'Ftp-Pa55word-x')
ftpd.seen = []
threading.Thread(target=ftpd.serve_forever, daemon=True).start()
FTP_PORT = ftpd.server_address[1]


# ---- the machine, as test/admin.py stands it in -------------------------------------
STATE, ETC = W / 'state', W / 'etc'
for d in (STATE / 'root', STATE / 'backups', ETC / 'zigmon', ETC / 'mosquitto', ETC / 'nginx' / 'conf.d'):
    d.mkdir(parents=True, exist_ok=True)
DB = STATE / 'history.db'
(ETC / 'zigmon' / 'config.json').write_text(json.dumps({'db_file': str(DB)}))
(ETC / 'mosquitto' / 'mosquitto.conf').write_text('listener 1883\n')
os.environ.update(ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(W / 'own'), ZIGMON_FULL_DIR=str(W / 'full'),
                  ZIGMON_CONFIG=str(ETC / 'zigmon' / 'config.json'),
                  ZIGMON_NGINX_CONF=str(ETC / 'nginx' / 'conf.d' / 'zigmon.conf'),
                  ZIGMON_CERT_DIR=str(ETC / 'certs'), ZIGMON_MOSQ_DIR=str(ETC / 'mosquitto'),
                  ZIGMON_NO_SERVICES='1', ZIGMON_SERVICE_LOG=str(W / 'services.log'), ZIGMON_FS_ROOT=str(W),
                  ZIGMON_USER='root', ZIGMON_FW_FILE4=str(W / 'no4'), ZIGMON_FW_FILE6=str(W / 'no6'),
                  ZIGMON_FIREWALL_CMD=str(W / 'no-firewall-cmd'),
                  ZIGMON_ROOT_RUN='%s -I %s' % (sys.executable, ROOT_HELPER))

sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

PORT = free_port()
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(DB), 'api_port': PORT, 'token_file': str(W / 'token'),
                      'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(STATE),
                      'rbackup': 0, 'rbackup_password': '', 'rbackup_keep': 30, 'rbackup_keep_days': 0})
# every line the daemon writes into its log, and every message it would send
LOGGED = []
_log = zigmon.log


def logged(msg, level='info'):
    LOGGED.append(str(msg))
    _log(msg, level)


zigmon.log = logged
d = zigmon.Daemon()
TOLD = []
d.notify = lambda message, *a, **k: TOLD.append((str(message), k.get('dedup')))
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def call(path, body=None, session=None, raw=False):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': '192.168.40.10'}
    if session:
        headers['X-Zigmon-Session'] = session
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path), headers=headers,
                                 data=None if body is None else json.dumps(body).encode(),
                                 method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
            return r.status, (data if raw else json.loads(data or b'{}'))
    except urllib.error.HTTPError as e:
        data = e.read() or b'{}'
        return e.code, (data if raw else json.loads(data))


d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
S_OP = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''


def post(body, session=None):
    return call('/api/rbackup', dict(body, session=session or S), session=session or S)


def job_end(most=300):
    until = time.time() + most
    while time.time() < until:
        code, got = post({'action': 'job'})
        if not (got.get('job') or {}).get('running'):
            return got.get('job') or {}
        time.sleep(0.3)
    raise AssertionError('the job did not end')


# ---- an administrator's ---------------------------------------------------------------
print('an administrator\'s')
code, _ = call('/api/rbackup')
check(code == 403, 'GET /api/rbackup answered without a sign-in (%s)' % code)
code, _ = call('/api/rbackup', session=S_OP)
check(code == 403, 'GET /api/rbackup answered an operator (%s)' % code)
code, _ = call('/api/rbackup', {'action': 'job'})
check(code == 403, 'POST /api/rbackup went through without a sign-in (%s)' % code)
code, _ = call('/api/rbackup', {'action': 'job', 'session': S_OP}, session=S_OP)
check(code == 403, 'POST /api/rbackup went through for an operator (%s)' % code)
code, _ = call('/api/rbackup/download?id=x&name=y', session=S_OP)
check(code == 403, 'a download went to an operator (%s)' % code)
check('/api/rbackup' in zigmon.ApiHandler.ALWAYS_LOCKED and '/api/rbackup/download' in zigmon.ApiHandler.ALWAYS_LOCKED,
      'the reads are not in ALWAYS_LOCKED')
code, page = call('/api/rbackup', session=S)
check(code == 200 and page.get('targets') == [] and page.get('locked') is False,
      'the page of an empty house: %s %s' % (code, page))


# ---- what is typed, checked ---------------------------------------------------------
print('what a tool on the way would read as more is refused')
good = {'kind': 'sftp', 'host': 'nas.example.org', 'user': 'backup', 'path': '/srv/backup/zigmon'}
zigmon.rb_checked(good)
for field, value, why in (
        ('path', '/srv/a;rm -rf x', 'a ; in the folder'),
        ('path', '/srv/"a', 'a " in the folder'),
        ('path', '-oProxyCommand=x', 'a folder that begins with -'),
        ('path', '/srv/../etc', '.. in the folder'),
        ('path', '..', 'the folder ..'),
        ('path', 'a\r\nDELE x', 'a line break in the folder'),
        ('path', 'a\nb', 'a new line in the folder'),
        ('user', '-oProxyCommand=x', 'an account that begins with -'),
        ('user', 'a;b', 'a ; in the account'),
        ('user', 'a b', 'a space in the account'),
        ('host', '-oProxyCommand=x', 'a server that begins with -'),
        ('host', 'a b', 'a space in the server'),
        ('host', 'a;b', 'a ; in the server'),
        ('password', 'one\ntwo', 'a line break in the password'),
        ('port', '70000', 'a port past 65535'),
        ('kind', 'folder', 'a folder on this machine'),
        ('kind', 'webdav', 'a kind there is not')):
    try:
        zigmon.rb_checked(dict(good, **{field: value}))
        check(False, '%s was taken' % why)
    except ValueError:
        pass
for t, why in (({'kind': 'smb', 'host': 'nas', 'share': 'a;b'}, 'a ; in the share'),
               ({'kind': 'smb', 'host': 'nas', 'share': '-x'}, 'a share that begins with -'),
               ({'kind': 'smb', 'host': 'nas', 'share': 'b', 'path': 'x\\..\\y'}, '.. in an SMB folder'),
               ({'kind': 'scp', 'host': 'nas', 'path': '/srv/a b'}, 'a space in an SCP folder'),
               ({'kind': 'scp', 'host': 'nas', 'path': '/srv/$(id)'}, 'a $( in an SCP folder'),
               ({'kind': 'ftps', 'host': 'nas', 'tls_check': 'pin', 'pin': 'abc'}, 'a pin that is not SHA-256'),
               ({'kind': 'ftps', 'host': 'nas', 'tls_check': 'ca'}, 'checked against no authority')):
    try:
        zigmon.rb_checked(t)
        check(False, '%s was taken' % why)
    except ValueError:
        pass
for name in ('../x', '-rf', 'a;b', 'a b', '.hidden', 'a"b', 'a\nb'):
    try:
        zigmon.rb_safe_name(name)
        check(False, 'the file name %r was taken' % name)
    except zigmon.RbError:
        pass
kept = zigmon.rb_checked({'kind': 'ftp', 'host': 'h', 'password': ''}, {'id': 'x', 'kind': 'ftp', 'password': 'old'})
check(kept['password'] == 'old', 'an empty password box did not keep the one there was')


# ---- taking the old ones away ---------------------------------------------------------
print('the old ones taken away: never the newest, never anybody else\'s')


class FakeTransport(object):
    files = {}
    log = []

    def __init__(self, t=None):
        self.t = t

    def open(self):
        FakeTransport.log.append('open')

    def put(self, local, name):
        with open(local, 'rb') as f:
            FakeTransport.files[name] = f.read()

    def get(self, name, local):
        with open(local, 'wb') as f:
            f.write(FakeTransport.files[name])

    def list(self):
        return [{'name': n, 'size': len(b), 'mtime': 0} for n, b in FakeTransport.files.items()]

    def delete(self, name):
        del FakeTransport.files[name]

    def close(self):
        pass


me = zigmon.rb_host()
stamps = ['2026-10-%02d-041500' % day for day in (20, 21, 22, 23, 24)]
ours = ['zigmon-full-%s-%s.tar.gz.enc' % (me, s) for s in stamps]
theirs = ['zigmon-full-otherhouse-%s.tar.gz.enc' % s for s in stamps[:2]]
FakeTransport.files = {}
for n in ours + theirs:
    FakeTransport.files[n] = b'Salted__x'
    for c in zigmon.rb_companions(n):
        FakeTransport.files[c] = b'c'
for n in ('notes.txt', 'zigmon-full-%s-2026-10-01-000000.tar.gz' % me, 'zigmon-full-%s.tar.gz.enc' % me):
    FakeTransport.files[n] = b'mine, by hand'
gone = zigmon.rb_retain(FakeTransport(), 2, 0)
check(sorted(gone) == sorted(ours[:3]), 'kept two: took away %s' % gone)
left = set(FakeTransport.files)
check(ours[4] in left and ours[3] in left, 'the newest two are not there')
check(not any(c in left for n in ours[:3] for c in zigmon.rb_companions(n)), 'a companion was left behind')
check(all(c in left for n in ours[3:] for c in zigmon.rb_companions(n)), 'a companion of one kept went')
check(all(n in left for n in theirs) and all(c in left for n in theirs for c in zigmon.rb_companions(n)),
      'another machine\'s backup was taken away')
check('notes.txt' in left and 'zigmon-full-%s.tar.gz.enc' % me in left
      and 'zigmon-full-%s-2026-10-01-000000.tar.gz' % me in left, 'a file put there by hand was taken away')
gone = zigmon.rb_retain(FakeTransport(), 0, 1, now=time.time())
check(gone == [ours[3]] and ours[4] in FakeTransport.files,
      'by age: the newest has to stay however old it is (%s)' % gone)
gone = zigmon.rb_retain(FakeTransport(), 1, 0)
check(gone == [] and ours[4] in FakeTransport.files, 'the last one was taken away')


# ---- the schedule ----------------------------------------------------------------------
print('the schedule, with a clock of the test\'s own')
started = []
_job_start = zigmon.rb_job_start
zigmon.rb_job_start = lambda dd, by, what, work: started.append((by, what)) or {}
zigmon.CONFIG.update(rbackup=0, rbackup_at='04:15', rbackup_every='daily', rbackup_day=7)
monday_early, monday = datetime(2026, 10, 26, 4, 14), datetime(2026, 10, 26, 4, 15)
sunday = datetime(2026, 11, 1, 4, 20)
check(zigmon.rb_due(monday) is None, 'due while switched off')
zigmon.CONFIG['rbackup'] = 1
check(zigmon.rb_due(monday_early) is None, 'due a minute early')
check(zigmon.rb_due(monday) == '2026-10-26', 'not due at the time')
check(zigmon.rb_due(datetime(2026, 10, 26, 23, 59)) == '2026-10-26', 'not due later the same day (a missed one)')
zigmon.CONFIG['rbackup_every'] = 'weekly'
check(zigmon.rb_due(monday) is None, 'weekly on Sunday, and due on a Monday')
check(zigmon.rb_due(sunday) == '2026-11-01', 'weekly on Sunday, and not due on a Sunday')
check(zigmon.rb_next(datetime(2026, 10, 28, 12, 0)) == '2026-11-01T04:15', 'the next one: %s'
      % zigmon.rb_next(datetime(2026, 10, 28, 12, 0)))
zigmon.CONFIG['rbackup_every'] = 'daily'
check(zigmon.rb_tick(d, monday) is None and not started, 'started with no destination switched on')
d.store.set_meta('rbackup:day', '')
zigmon.rb_put_targets(d, [{'id': 'aaaa', 'kind': 'ftp', 'name': 'x', 'host': 'h', 'port': 21, 'enabled': 1}])
check(zigmon.rb_tick(d, monday) == '2026-10-26' and len(started) == 1, 'not started when due')
zigmon.rb_tick(d, datetime(2026, 10, 26, 4, 16))
check(len(started) == 1, 'started twice the same day')
d2 = zigmon.Daemon.__new__(zigmon.Daemon)              # a restart: what it knows is the database
d2.store = d.store
zigmon.rb_tick(d2, datetime(2026, 10, 26, 9, 0))
check(len(started) == 1, 'started again the same day after a restart')
zigmon.rb_tick(d, datetime(2026, 10, 27, 4, 15))
check(len(started) == 2, 'not started the next day')
zigmon.rb_job_start = _job_start
zigmon.CONFIG['rbackup'] = 0
zigmon.rb_put_targets(d, [])


# ---- never without the password -------------------------------------------------------
print('nothing sent without the password')
code, got = post({'action': 'save', 'target': {'kind': 'ftp', 'name': 'the cellar', 'host': '127.0.0.1',
                                                 'port': FTP_PORT, 'user': 'backup', 'password': 'Ftp-Pa55word-x',
                                                 'path': 'zigmon/nightly'}})
check(code == 200 and got.get('target', {}).get('has_password') and 'password' not in got.get('target', {}),
      'saving a destination: %s %s' % (code, got))
FTP_ID = (got.get('target') or {}).get('id')
code, got = post({'action': 'run'})
check(code == 400 and 'password' in got.get('error', ''), 'a run without a password went: %s %s' % (code, got))
try:
    zigmon.rb_run(d, 'test')
    check(False, 'rb_run ran without a password')
except zigmon.RbError:
    pass
check(not any(FTP_TOP.rglob('zigmon-full-*')), 'something reached the server without a password')
code, got = call('/api/config', {'rbackup_password': 'short', 'session': S}, session=S)
check(code == 400, 'a password of five letters was taken for the backups (%s)' % code)


# ---- Try it, saved and not --------------------------------------------------------------
print('Try it')
code, got = post({'action': 'try', 'id': FTP_ID})
check(code == 200 and got.get('ok') and len(got.get('steps') or []) == 4, 'Try it: %s %s' % (code, got))
check((FTP_TOP / 'zigmon' / 'nightly').is_dir() and not list((FTP_TOP / 'zigmon' / 'nightly').iterdir()),
      'Try it made no folder there, or left its file behind')
code, got = post({'action': 'try', 'target': {'kind': 'ftp', 'host': '127.0.0.1', 'port': FTP_PORT,
                                                'user': 'backup', 'password': 'Wrong-Pa55word', 'path': 'x'}})
check(code == 200 and not got.get('ok') and '530' in (got.get('error') or ''), 'a wrong password: %s' % got)
check('Wrong-Pa55word' not in json.dumps(got), 'a wrong password was said back')


# ---- the whole run ----------------------------------------------------------------------
print('a whole run: root makes it, locks it, it is sent')
PASSWORD = 'correct horse battery staple 42'
code, got = call('/api/config', {'rbackup_password': PASSWORD, 'rbackup_keep': 2, 'session': S}, session=S)
check(code == 200, 'the password of the backups was not saved: %s %s' % (code, got))
there = FTP_TOP / 'zigmon' / 'nightly'
older = ['zigmon-full-%s-2026-01-%02d-041500.tar.gz.enc' % (me, n) for n in (1, 2)]
for n in older:
    (there / n).write_bytes(b'Salted__old')
    for c in zigmon.rb_companions(n):
        (there / c).write_text('old')
(there / 'somebody-elses.txt').write_text('keep me')
code, got = post({'action': 'run'})
check(code == 200, 'Back up now: %s %s' % (code, got))
job = job_end()
res = job.get('result') or {}
check(not job.get('error') and res.get('ok'), 'the run: %s' % json.dumps(job)[:600])
name = res.get('file') or ''
check(zigmon.RB_NAME_RE.match(name) is not None, 'the file sent is named %r' % name)
sent = there / name
check(sent.is_file() and sent.read_bytes()[:8] == b'Salted__', 'what reached the server is not locked')
if sent.is_file():
    check(sent.stat().st_size == res.get('bytes'), 'the server holds another size than was sent')
    sha = (there / (name + '.sha256')).read_text().split()
    check(sha == [hashlib.sha256(sent.read_bytes()).hexdigest(), name], 'the .sha256 is not the file\'s: %s' % sha)
    restore = there / (name[:-len('.tar.gz.enc')] + '-RESTORE.txt')
    check(restore.is_file() and name in restore.read_text() and 'openssl enc -d' in restore.read_text(),
          'RESTORE.txt is missing or says nothing of this file')
    plain = W / 'plain.tar.gz'
    opened = subprocess.run(['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-iter', '600000', '-in', str(sent),
                             '-out', str(plain), '-pass', 'env:P'], env=dict(os.environ, P=PASSWORD),
                            capture_output=True)
    check(opened.returncode == 0 and plain.read_bytes()[:2] == b'\x1f\x8b', 'it does not open with openssl')
    import tarfile
    with tarfile.open(str(plain)) as tf:
        members = tf.getnames()
    check(any(m.endswith('/MANIFEST.json') for m in members) and any('/database/' in m for m in members),
          'what was sent is not a backup of the whole installation: %s' % members[:5])
check(not any(p.name.startswith('.') for p in there.iterdir()), 'a .part was left on the server')
check(not (there / older[0]).exists() and (there / older[1]).exists(),
      'kept 2: the oldest was not taken away, or more than that was')
check(not any((there / c).exists() for c in zigmon.rb_companions(older[0])), 'a companion of an old one was left')
check(all((there / c).exists() for c in zigmon.rb_companions(older[1])), 'a companion of one kept went')
check((there / 'somebody-elses.txt').read_text() == 'keep me', 'a file somebody put there was touched')
work_left = [p for p in Path(zigmon.rb_work_root()).iterdir()]
check(not work_left, 'the copy was left here: %s' % work_left)
check(not [p for p in (STATE / 'root' / 'out').iterdir()] if (STATE / 'root' / 'out').is_dir() else True,
      'the hand-over was left in root/out')
code, page = call('/api/rbackup', session=S)
runs = page.get('runs') or []
check(runs and runs[0].get('ok') and runs[0].get('file') == name, 'the history has no line of it')
check((page['targets'][0].get('last') or {}).get('ok'), 'the destination does not say it was sent')
check(page.get('locked') is True, 'the page does not say the backups are locked')

# Try the newest (5.36.2): fetched back, its .sha256, opened with the password,
# every file against MANIFEST.json, the database read through - and kept
print('Try the newest, and Download one here')
code, got = post({'action': 'verify'})
check(code == 200, 'Try the newest: %s %s' % (code, got))
job = job_end()
res = job.get('result') or {}
check(job.get('what') == 'verify' and res.get('ok') and res.get('file') == name,
      'the newest was not tried, or not good: %s' % json.dumps(job)[:800])
whats = [c.get('what') for c in res.get('checks') or []]
for want in ('the same as its .sha256', 'opened with the password', 'every file as MANIFEST.json says',
             'the database reads through (SQLite)'):
    check(want in whats, 'the try did not check %r: %r' % (want, whats))
code, page = call('/api/rbackup', session=S)
check((page.get('verified') or [{}])[0].get('ok') and (page.get('verified') or [{}])[0].get('file') == name,
      'the try is not on the page: %s' % (page.get('verified') or [])[:1])
check(PASSWORD not in json.dumps(page), 'the password is in what the page is told')
# a damaged copy there: said NOT GOOD, never put back
good = sent.read_bytes()
sent.write_bytes(good[:-40] + b'x' * 40)
post({'action': 'verify'})
res = job_end().get('result') or {}
check(not res.get('ok'), 'a damaged backup was tried as good: %s' % json.dumps(res)[:400])
sent.write_bytes(good)
code, got = post({'action': 'verified_forget', 'all': 1})
check(code == 200 and got.get('verified') == [], 'the list of tries was not cleared: %s %s' % (code, got))
# Download one here: made by root now, locked, handed over to be fetched once
code, got = post({'action': 'here'})
check(code == 200, 'Download one here: %s %s' % (code, got))
job = job_end()
ready = (job.get('result') or {}).get('ready') or ''
check(zigmon.RB_NAME_RE.match(ready) is not None, 'nothing was made to download: %s' % json.dumps(job)[:600])
if ready:
    there_out = STATE / 'root' / 'out' / ready
    check(there_out.is_file() and there_out.read_bytes()[:8] == b'Salted__', 'the copy to download is not locked')
    code, data = call('/api/fullbackup/download?file=%s' % ready, session=S, raw=True)
    check(code == 200 and data[:8] == b'Salted__', 'the copy was not handed over: %s' % code)
    try:
        there_out.unlink()
    except OSError:
        pass

# a failing destination: said, in the history and once by message
zigmon.rb_put_targets(d, zigmon.rb_targets(d) + [dict(zigmon.rb_targets(d)[0], id='bbbbbbbbbbbb', name='gone',
                                                       port=free_port())])
TOLD.clear()
post({'action': 'run'})
job = job_end()
res = job.get('result') or {}
check(not res.get('ok') and [x['ok'] for x in res.get('targets') or []] == [True, False],
      'one destination down: %s' % json.dumps(res)[:400])
check(any(dedup == 'rbackup-failed' for _m, dedup in TOLD), 'a failed backup was not told: %s' % TOLD)
zigmon.rb_delete(d, 'bbbbbbbbbbbb', 'test')
check(not (there / older[1]).exists(), 'the next run did not take the next old one away')


# ---- Backups there, Download, Delete, Put this back ----------------------------------------
print('backups there, download, put back')
code, got = post({'action': 'list', 'id': FTP_ID})
files = got.get('files') or []
check(code == 200 and len(files) == 2 and all(f['mine'] and f['sha256'] for f in files)
      and files[0]['when'] >= files[1]['when'], 'Backups there: %s %s' % (code, got))
newest = files[0]['name'] if files else ''
code, data = call('/api/rbackup/download?id=%s&name=%s' % (FTP_ID, newest), session=S, raw=True)
check(code == 200 and data == (there / newest).read_bytes(), 'the download is not the file there (%s)' % code)
code, _ = call('/api/rbackup/download?id=%s&name=%s' % (FTP_ID, '../../etc/passwd'), session=S, raw=True)
check(code == 404, 'a download of a name that is not a backup: %s' % code)
check(not list(Path(zigmon.rb_work_root()).iterdir()), 'the download left its copy here')

code, got = post({'action': 'restore', 'id': FTP_ID, 'name': newest})
check(code == 200, 'Put this back: %s %s' % (code, got))
job = job_end()
asked = (job.get('result') or {}).get('asked')
check(asked and not job.get('error'), 'it was not handed to root: %s' % job)
st = zigmon.rb_root_wait(d, asked, 60) if asked else {}
check(st.get('kind') == 'full_put' and st.get('state') == 'done', 'root did not take it in: %s' % st)
info = st.get('inspected') or {}
check(info.get('trusted') and str(info.get('file', '')).endswith('-uploaded.tar.gz'),
      'root did not look into it as an uploaded backup: %s' % info)
check(not [p for p in (STATE / 'root' / 'in').iterdir()], 'the fetched copy was left in root\'s in-tray')
code, got = post({'action': 'restore', 'id': FTP_ID, 'name': newest, 'password': 'not the password at all'})
job = job_end()
asked = (job.get('result') or {}).get('asked')
st = zigmon.rb_root_wait(d, asked, 60) if asked else {}
check(st.get('state') == 'failed' and 'password' in ' '.join(st.get('said') or []),
      'a wrong password opened it: %s' % st)
code, got = post({'action': 'restore', 'id': FTP_ID, 'name': '../etc/shadow'})
check(code == 400, 'a restore of a name that is not a backup: %s' % code)

code, got = post({'action': 'delete_file', 'id': FTP_ID, 'name': files[1]['name'] if len(files) > 1 else 'x'})
check(code == 200 and not any(n.startswith(files[1]['name'][:-len('.tar.gz.enc')]) for n in
                              (p.name for p in there.iterdir())) if len(files) > 1 else False,
      'Delete left the backup or a companion: %s' % [p.name for p in there.iterdir()])
code, got = post({'action': 'runs_forget', 'all': 1})
check(code == 200 and got.get('runs') == [] and (there / newest).exists(),
      'Clear the list: %s, or it took a backup with it' % got)


# ---- secrets: never shown back, never in the log ---------------------------------------------
print('no secret shown back or written down')
KEY = '-----BEGIN OPENSSH PRIVATE KEY-----\nS3CRETKEYMATERIALxyz\n-----END OPENSSH PRIVATE KEY-----\n'
code, got = post({'action': 'save', 'target': {'kind': 'sftp', 'name': 'ssh box', 'host': '127.0.0.1', 'port': 2,
                                                 'user': 'b', 'password': 'Ssh-Pa55word-q', 'path': 'x'}})
SSH_ID = (got.get('target') or {}).get('id')
zigmon.rb_set_fields(d, SSH_ID, 'test', '', key=KEY, key_pass='Key-Pa55phrase-k', pub='ssh-ed25519 AAAAC3 x',
                     hostkey='127.0.0.1 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n')
zigmon.rb_set_fields(d, FTP_ID, 'test', '', client_key='-----BEGIN PRIVATE KEY-----\nCLIENTKEYSECRETabc\n-----END PRIVATE KEY-----\n')
post({'action': 'try', 'id': SSH_ID})                    # fails one way or another
code, raw = call('/api/rbackup', session=S, raw=True)
text = raw.decode()
page = json.loads(text)
secrets_ = ('Ftp-Pa55word-x', 'Ssh-Pa55word-q', 'Key-Pa55phrase-k', 'S3CRETKEYMATERIAL', 'CLIENTKEYSECRET', PASSWORD)
check(code == 200 and not [s for s in secrets_ if s in text], 'a secret is in GET /api/rbackup: %s'
      % [s for s in secrets_ if s in text])
ssh = next((t for t in page.get('targets') or [] if t['id'] == SSH_ID), {})
check(ssh.get('has_password') and ssh.get('has_key') and ssh.get('has_key_pass') and ssh.get('hostkey_fp'),
      'the page is not told what is set: %s' % ssh)
check(ssh.get('hostkey_fp', [''])[0].startswith('SHA256:'), 'the host key fingerprint: %s' % ssh.get('hostkey_fp'))
rc = d.runtime_config()
check(rc.get('rbackup_password', {}).get('kind') == 'secret' and rc['rbackup_password'].get('value') is True,
      'the password of the backups is not a secret setting: %s' % rc.get('rbackup_password'))
events = sqlite3.connect(str(DB)).execute('SELECT detail FROM events').fetchall()
written = '\n'.join(LOGGED) + '\n'.join(str(e[0]) for e in events) + '\n'.join(m for m, _ in TOLD)
check(not [s for s in secrets_ if s in written], 'a secret was written into the log or the events: %s'
      % [s for s in secrets_ if s in written])


# ---- SFTP, when this machine has an sshd ----------------------------------------------------
SSHD = shutil.which('sshd') or ('/usr/sbin/sshd' if os.path.exists('/usr/sbin/sshd') else '')
TOOLS = all(shutil.which(x) for x in ('ssh', 'sftp', 'scp', 'ssh-keygen', 'ssh-keyscan'))
if not (SSHD and TOOLS) or os.geteuid() != 0:
    print('SFTP: skipped - no sshd or OpenSSH client here (or not root)')
else:
    print('SFTP against an sshd started here')
    sd = W / 'sshd'
    sd.mkdir()
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(sd / 'host')], check=True)
    sport = free_port()
    (sd / 'cfg').write_text('Port %d\nListenAddress 127.0.0.1\nHostKey %s\nAuthorizedKeysFile %s\n'
                            'PasswordAuthentication no\nPubkeyAuthentication yes\nUsePAM no\nStrictModes no\n'
                            'PidFile %s\nSubsystem sftp internal-sftp\n'
                            % (sport, sd / 'host', sd / 'authorized_keys', sd / 'pid'))
    (sd / 'authorized_keys').write_text('')
    server = subprocess.Popen([SSHD, '-D', '-e', '-f', str(sd / 'cfg')], stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        code, got = post({'action': 'save', 'target': {'kind': 'sftp', 'name': 'sshd here', 'host': '127.0.0.1',
                                                         'port': sport, 'user': 'root',
                                                         'path': str(W / 'sftp-there')}})
        sid = got['target']['id']
        code, got = post({'action': 'keygen', 'id': sid})
        check(code == 200 and got.get('pub', '').startswith('ssh-ed25519'), 'Make a key: %s' % got)
        (sd / 'authorized_keys').write_text(got.get('pub', '') + '\n')
        code, got = post({'action': 'try', 'id': sid})
        check(got.get('hostkey_needed') and got.get('fingerprints'), 'no host key was shown to trust: %s' % got)
        code, got = post({'action': 'hostkey_trust', 'id': sid, 'hostkey': got.get('hostkey', '')})
        check(code == 200, 'Trust it: %s' % got)
        code, got = post({'action': 'try', 'id': sid})
        check(got.get('ok'), 'Try it over SFTP: %s' % got)
        code, got = post({'action': 'run', 'ids': [sid]})
        job = job_end()
        check((job.get('result') or {}).get('ok'), 'a run over SFTP: %s' % job)
        check(any(zigmon.RB_NAME_RE.match(p.name) for p in (W / 'sftp-there').iterdir()), 'nothing arrived over SFTP')
    finally:
        server.terminate()
        server.wait(timeout=10)


api.stop()
ftpd.shutdown()
shutil.rmtree(str(W), ignore_errors=True)
if bad:
    print('\n%d check(s) failed' % len(bad))
    sys.exit(1)
print('\nbackups to other machines: every check passed')
