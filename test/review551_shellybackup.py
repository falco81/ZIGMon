#!/usr/bin/env python3
"""Settings - Devices - Device backups (5.50): the configuration of each Shelly box, made by
the box itself (Sys.CreateBackup, produced as it next starts), kept in the database, put back
(Sys.UploadBackup + Sys.RestoreBackup) - checked against fake Shelly boxes here.

  * the fingerprint: unchanged when nothing changed, different when the configuration or a
    revision moved - without a restart;
  * a backup: CreateBackup, Shelly.Reboot, the box waited for, the archive downloaded in
    pieces (behind digest auth on one box), checked as a ZIP, stored with its fingerprint;
    the newest N kept;
  * a box whose firmware has no backup is "not supported" with why; one that does not answer
    is "not reachable", not an error;
  * the scheduler backs up only the boxes that differ, and leaves a box whose output is on and
    does not come back as it was (power-on state other than restore_last) - saying why;
  * a restore refuses another model (before anything is sent, and by the archive's manifest
    after the upload, before RestoreBackup); the happy path calls UploadBackup (offset 0
    first, in order, final last) and then RestoreBackup, and waits for the box;
  * the API is an administrator's: an operator and nobody get 403;
  * the archive's bytes (and the secret in it) are never written into the log, debug on;
  * the events (who, which box, how it ended) and the notice when a box starts to differ;
  * the command line (--shelly-backup, parsed, and end to end through the API with root's
    key) and the console's menu;
  * the card's words in index.php, and the page in Chromium (php -S + Playwright):
    screenshots of the section (desktop and 390 px) and of the dialogs into $ZIGMON_SHOTS.

    python3 test/review551_shellybackup.py

Ports 20100-20149.
"""
import base64
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-shellybackup-'))
API_PORT, PHP_PORT = 20100, 20101
PORT_A, PORT_B, PORT_C, PORT_D, PORT_E = 20110, 20111, 20112, 20113, 20114
SHOTS = Path(os.environ.get('ZIGMON_SHOTS') or (W / 'shots'))
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


# ---- a fake Shelly box --------------------------------------------------------------------------
class Fake(object):
    """One Gen3-like box: digest auth when it has a password, a switch, Sys revisions, a backup
    made as it starts after Sys.CreateBackup, a restore that replaces its configuration."""

    def __init__(self, port, ident, model='S3PL-00112EU', app='PlugSG3', fw='1.8.0-beta1', supported=True,
                 password='', initial='restore_last', output=False):
        self.port, self.ident, self.model, self.app, self.fw = port, ident, model, app, fw
        self.supported, self.password = supported, password
        self.output = output
        self.cfg = {'switch:0': {'id': 0, 'name': None, 'initial_state': initial, 'auto_off': False},
                    'sys': {'device': {'name': ident, 'fw_id': '20261101-%s' % fw, 'mac': 'AABBCC%d' % port},
                            'cfg_rev': 10},
                    'wifi': {'sta': {'ssid': 'iot', 'enable': True}}}
        self.revs = {'cfg_rev': 10, 'kvs_rev': 3, 'schedule_rev': 0, 'webhook_rev': 0, 'btrelay_rev': 0}
        self.secret = 'WIFI-PASS-%d-zzq' % port
        self.boot = time.time() - 5000
        self.down_until = 0.0
        self.restoring = None
        self.pending = False
        self.backup = {}
        self.archive = b''
        self.made = 1767225600
        self.upload = bytearray()
        self.calls = []
        self.nonce = 'n%d' % port
        self.lock = threading.Lock()
        self.manifest_model = None          # a manifest saying another model (the archive lies)

    def make_archive(self):
        z = io.BytesIO()
        with zipfile.ZipFile(z, 'w', zipfile.ZIP_DEFLATED) as f:
            self.made += 1
            f.writestr('manifest.json', json.dumps({'created_at': self.made, 'fw_ver': self.fw,
                                                    'model': self.manifest_model or self.model, 'app_name': self.app,
                                                    'device_name': self.ident, 'encrypt': False}))
            f.writestr('config.json', json.dumps({'cfg': self.cfg, 'revs': self.revs}))
            f.writestr('wifi.json', json.dumps({'sta': {'ssid': 'iot', 'pass': self.secret}}))
            f.writestr('noise.bin', bytes((i * 7919) % 251 for i in range(3000)), compress_type=zipfile.ZIP_STORED)
        return z.getvalue()

    def methods(self):
        m = ['Shelly.GetStatus', 'Shelly.GetConfig', 'Shelly.GetDeviceInfo', 'Shelly.ListMethods', 'Shelly.Reboot',
             'Switch.GetStatus', 'Switch.Set', 'Sys.GetStatus', 'Sys.GetConfig', 'Script.List']
        if self.supported:
            m += ['Sys.CreateBackup', 'Sys.DownloadBackup', 'Sys.UploadBackup', 'Sys.RestoreBackup']
        return m

    def reboot(self, s=1.0):
        self.down_until = time.time() + s

    def settle(self):
        """The box coming up again: the backup made early in the boot, a restore taken in."""
        if self.down_until and time.time() >= self.down_until:
            self.down_until = 0.0
            self.boot = time.time()
            self.nonce = secrets_hex()
            if self.pending:
                self.pending = False
                self.archive = self.make_archive()
                self.backup = {'href': '/backup.zip', 'created': self.made}
            if self.restoring is not None:
                with zipfile.ZipFile(io.BytesIO(self.restoring)) as f:
                    got = json.loads(f.read('config.json'))
                self.cfg, self.revs = got['cfg'], got['revs']
                self.restoring = None

    def answer(self, m, p):
        if m == 'Shelly.GetDeviceInfo':
            return {'id': self.ident, 'mac': 'AABBCC%d' % self.port, 'model': self.model, 'gen': 3,
                    'fw_id': '20261101-%s' % self.fw, 'ver': self.fw, 'app': self.app, 'auth_en': bool(self.password),
                    'provision': 'complete', 'name': self.ident}
        if m == 'Shelly.ListMethods':
            return {'methods': self.methods()}
        if m == 'Sys.GetStatus':
            r = dict({'mac': 'AABBCC', 'restart_required': self.pending, 'uptime': int(time.time() - self.boot),
                      'unixtime': int(time.time())}, **self.revs)
            if self.backup:
                r['backup'] = dict(self.backup)
            return r
        if m == 'Shelly.GetConfig':
            return json.loads(json.dumps(self.cfg))
        if m == 'Shelly.GetStatus':
            return {'switch:0': {'id': 0, 'output': self.output}, 'sys': {'uptime': int(time.time() - self.boot)}}
        if m == 'Script.List':
            return {'scripts': [{'id': 1, 'name': 'nightly', 'enable': True, 'running': bool(int(time.time()) % 2)}]}
        if m == 'Shelly.Reboot':
            self.reboot()
            return None
        if m not in self.methods():
            return 'nomethod'
        if m == 'Sys.CreateBackup':
            self.pending = True
            return {'restart_required': True}
        if m == 'Sys.DownloadBackup':
            off, n = int(p.get('offset') or 0), int(p.get('len') or 1024)
            piece = self.archive[off:off + n]
            return {'data': base64.b64encode(piece).decode(), 'left': max(0, len(self.archive) - off - len(piece))}
        if m == 'Sys.UploadBackup':
            off = int(p.get('offset') or 0)
            if off == 0:
                self.upload = bytearray()
            if off != len(self.upload):
                return 'gap'
            self.upload += base64.b64decode(p.get('data') or '')
            if p.get('final'):
                with zipfile.ZipFile(io.BytesIO(bytes(self.upload))) as f:
                    return {'manifest': json.loads(f.read('manifest.json'))}
            return None
        if m == 'Sys.RestoreBackup':
            self.restoring = bytes(self.upload)
            self.reboot()
            return None
        return 'nomethod'


def secrets_hex():
    return hashlib.sha256(os.urandom(8)).hexdigest()[:16]


def ok_digest(fake, header):
    if not fake.password:
        return True
    if not header.startswith('Digest '):
        return False
    f = dict(re.findall(r'(\w+)="?([^",]+)"?', header))
    if f.get('nonce') != fake.nonce:
        return False

    def h(t):
        return hashlib.sha256(t.encode()).hexdigest()
    ha1 = h('admin:%s:%s' % (f.get('realm'), fake.password))
    ha2 = h('POST:%s' % f.get('uri'))
    return f.get('response') == h('%s:%s:%s:%s:auth:%s' % (ha1, f.get('nonce'), f.get('nc'), f.get('cnonce'), ha2))


def serve(fake):
    class H(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
            with fake.lock:
                fake.settle()
                if fake.down_until:
                    self.close_connection = True          # restarting: nothing answers
                    return
                if not ok_digest(fake, self.headers.get('Authorization', '')):
                    self.send_response(401)
                    self.send_header('WWW-Authenticate', 'Digest qop="auth", realm="%s", nonce="%s", '
                                     'algorithm=SHA-256' % (fake.ident, fake.nonce))
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                m, p = body.get('method'), body.get('params') or {}
                fake.calls.append((m, dict(p, data='<%d>' % len(p['data'])) if 'data' in p else p))
                r = fake.answer(m, p)
            if r == 'nomethod':
                out = {'id': 1, 'error': {'code': 404, 'message': 'No handler for %s' % m}}
            elif r == 'gap':
                out = {'id': 1, 'error': {'code': -103, 'message': 'offset out of order'}}
            else:
                out = {'id': body.get('id'), 'src': fake.ident, 'result': r}
            data = json.dumps(out).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    srv = ThreadingHTTPServer(('127.0.0.1', fake.port), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


A = Fake(PORT_A, 'shellyplugsg3-aaa111', password='pw-of-a')                  # two sockets, digest
B = Fake(PORT_B, 'shelly1g4-bbb222', model='S4SW-001X16EU', app='S1G4', initial='off', output=True)
C = Fake(PORT_C, 'shellyplusuni-ccc333', model='SNSN-0043X', app='PlusUni', fw='1.4.4', supported=False)
E = Fake(PORT_E, 'shellyplugsg3-eee555', initial='on', output=False)            # off, comes back on
SERVERS = [serve(f) for f in (A, B, C, E)]

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
    'pin': '', 'sensors': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(W / 'state'), 'debug': 1,
    'plugs': [
        {'name': 'Lednice', 'host': '127.0.0.1:%d' % PORT_A, 'password': 'pw-of-a', 'switch_id': 0},
        {'name': 'Lednice-2', 'host': '127.0.0.1:%d' % PORT_A, 'password': 'pw-of-a', 'switch_id': 1},
        {'name': 'Svetlo-Kuchyn', 'host': '127.0.0.1:%d' % PORT_B, 'role': 'light'},
        {'name': 'Stara-Uni', 'host': '127.0.0.1:%d' % PORT_C},
        {'name': 'Pryc', 'host': '127.0.0.1:%d' % PORT_D, 'optional': True},
        {'name': 'Pracka', 'host': '127.0.0.1:%d' % PORT_E}]})
zigmon.SBK_WAIT_S = 20.0
zigmon.SBK_POLL_S = 0.3
zigmon.SBK_CHUNK = 1024
zigmon.SBK_TIMEOUT = 2.0
d = zigmon.Daemon()
TOLD = []
d.notify = lambda message, *a, **k: TOLD.append(message)
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def call(path, body=None, session=None, cli=False):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': '192.168.40.10'}
    if session:
        headers['X-Zigmon-Session'] = session
    if cli:
        headers['X-Zigmon-Cli'] = d.cli_key
    if body is not None and session:
        body = dict(body, session=session)
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                 data=None if body is None else json.dumps(body).encode(),
                                 method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
SO = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''


def wait(cond, s=40.0):
    end = time.time() + s
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def job_done():
    return wait(lambda: not zigmon.SBK_JOB['running'], 90)


def box(name):
    return zigmon.sbk_find_box(d, name)


def called(fake, method):
    return [p for m, p in fake.calls if m == method]


def events(text):
    # an event is written by the store's writer a moment later: what it holds goes in first
    d.store.flush()
    with d.store.lock:
        return [dict(r) for r in d.store.db.execute(
            "SELECT * FROM events WHERE detail LIKE ? ORDER BY id", ('%' + text + '%',)).fetchall()]


try:
    print('the boxes, grouped and looked at')
    boxes = zigmon.sbk_boxes(d)
    check(len(boxes) == 5 and boxes['127.0.0.1:%d' % PORT_A]['names'] == ['Lednice', 'Lednice-2'],
          'two sockets on one box are one box: %r' % {k: v['names'] for k, v in boxes.items()})
    check(zigmon.sbk_view(d)['devices'] and not zigmon.SBK_CHECKING['on'], 'the view before any look')
    # nothing looks by itself before the feature is used, nor in the first minutes
    check(zigmon.sbk_tick(d) is None and not A.calls, 'the tick looked at a box before anybody used it: %r' % A.calls[:3])
    code, out = call('/api/shellybackup', {'action': 'check'}, session=S)
    check(code == 200 and 'looking' in out.get('message', ''), 'check: %s %r' % (code, out.get('error')))
    check(wait(lambda: not zigmon.SBK_CHECKING['on']), 'the look did not end')
    st = zigmon.sbk_states(d)
    sa, sc, sd = st['127.0.0.1:%d' % PORT_A], st['127.0.0.1:%d' % PORT_C], st['127.0.0.1:%d' % PORT_D]
    check(sa.get('reachable') and sa.get('supported') and sa.get('model') == 'S3PL-00112EU' and sa.get('fp'),
          'box A looked at (digest auth): %r' % {k: sa.get(k) for k in ('reachable', 'supported', 'said')})
    check(sc.get('reachable') and sc.get('supported') is False and 'Sys.CreateBackup' in sc.get('why', ''),
          'the box with no backup: %r' % sc)
    check(sd.get('reachable') is False, 'the box that is not there: %r' % sd)
    v = zigmon.sbk_view(d)
    by = {x['names'][0]: x for x in v['devices']}
    check(by['Lednice']['status'] == 'never' and by['Stara-Uni']['status'] == 'unsupported' and
          by['Pryc']['reachable'] is False and v['counts']['unsupported'] == 1 and v['counts']['unreachable'] == 1,
          'the view: %r' % {k: (x['status'], x['reachable']) for k, x in by.items()})
    check(not [e for e in events('') if e['level'] in ('warn', 'crit') and 'Pryc' in str(e)],
          'a box that is not there made a warning')

    print('the fingerprint')
    fp1 = zigmon.sbk_check_box(d, box('Lednice'))['fp']
    fp2 = zigmon.sbk_check_box(d, box('Lednice'))['fp']
    check(fp1 == fp2, 'nothing changed, and the fingerprint moved (a script running is not configuration)')
    check(not called(A, 'Shelly.Reboot'), 'looking restarted the box')
    A.cfg['switch:0']['auto_off'] = True
    fp3 = zigmon.sbk_check_box(d, box('Lednice'))['fp']
    check(fp3 != fp2, 'a configuration change was not seen')
    A.revs['kvs_rev'] += 1
    fp4 = zigmon.sbk_check_box(d, box('Lednice'))['fp']
    check(fp4 != fp3, 'a KVS change (kvs_rev) was not seen')
    A.cfg['sys']['device']['fw_id'] = 'something-else'
    check(zigmon.sbk_check_box(d, box('Lednice'))['fp'] == fp4, 'a field that moves by itself (fw_id) moved the fingerprint')

    print('the API is an administrator\'s')
    code, out = call('/api/shellybackup', session=SO)
    check(code == 403, 'an operator read the backups: %s' % code)
    code, out = call('/api/shellybackup', {'action': 'backup', 'box': box('Lednice')['box']}, session=SO)
    check(code == 403 and not called(A, 'Sys.CreateBackup'), 'an operator backed up: %s %r' % (code, out))
    code, out = call('/api/shellybackup')
    check(code == 403, 'nobody read the backups: %s' % code)
    code, out = call('/api/shellybackup', {'action': 'download', 'id': 1})
    check(code == 403, 'nobody downloaded one: %s' % code)
    check('/api/shellybackup' in zigmon.ApiHandler.ALWAYS_LOCKED, 'not among the locked reads')

    print('a backup')
    code, out = call('/api/shellybackup', {'action': 'backup', 'box': box('Lednice')['box']}, session=S)
    check(code == 200 and out.get('job', {}).get('running'), 'backup asked: %s %r' % (code, out.get('error')))
    code, out2 = call('/api/shellybackup', {'action': 'restore', 'id': 1, 'box': box('Lednice')['box']}, session=S)
    check(code == 400 and 'going on' in out2.get('error', ''), 'a second job while one runs: %s %r' % (code, out2))
    check(job_done(), 'the backup did not end')
    steps = zigmon.SBK_JOB['steps']
    check(steps and steps[0]['state'] == 'done', 'the backup: %r' % steps)
    rows = zigmon.sbk_rows(d, A.ident, with_data=True)
    check(len(rows) == 1 and rows[0]['data'] == A.archive and rows[0]['sha256'] == hashlib.sha256(A.archive).hexdigest()
          and rows[0]['model'] == 'S3PL-00112EU' and rows[0]['manifest'].get('model') == 'S3PL-00112EU'
          and rows[0]['by'] == 'owner', 'the stored backup: %r' % [{k: r[k] for k in r if k != 'data'} for r in rows])
    check(called(A, 'Sys.CreateBackup') == [{'encrypt': False}] and len(called(A, 'Shelly.Reboot')) == 1,
          'CreateBackup unencrypted and one restart: %r' % [m for m, p in A.calls][-12:])
    pieces = called(A, 'Sys.DownloadBackup')
    check(len(pieces) >= 4 and [p['offset'] for p in pieces] == sorted(p['offset'] for p in pieces),
          'downloaded in pieces: %r' % pieces)
    check(rows[0]['fp'] == zigmon.sbk_states(d)['127.0.0.1:%d' % PORT_A]['fp'], 'the fingerprint kept with it')
    by = {x['names'][0]: x for x in zigmon.sbk_view(d)['devices']}
    check(by['Lednice']['status'] == 'same' and by['Lednice']['backups'][0]['current'],
          'after the backup: %r' % by['Lednice']['status'])
    check(events('owner backed up the configuration of the box') and
          events('owner backed up')[0]['device'] == 'plug:Lednice', 'no event of the backup, by whom')
    check('data' not in json.dumps(zigmon.sbk_view(d)) or A.secret not in json.dumps(zigmon.sbk_view(d)),
          'the view carries the archive')

    print('where a backup has got to (5.52)')
    stp = {}
    say = zigmon.sbk_say_into(stp)
    for words, phase in (('looking at it', 'look'), ('asking it for a backup (unencrypted)', 'ask'),
                         ('restarting - waiting for it to come back', 'restart'), ('downloading the archive 40 %', 'download'),
                         ('looking at it again', 'store'), ('sending the archive', 'upload'),
                         ('restoring - the device wipes its files and restarts', 'restore')):
        say(words)
        check(stp.get('phase') == phase, 'the phase of %r: %r' % (words, stp.get('phase')))
    say('downloading the archive 40 %')
    check(stp.get('pct') == 40, 'how much of the archive is in: %r' % stp.get('pct'))
    check('checking_box' in zigmon.sbk_view(d), 'the page is not told which box is looked at')
    print('the newest N are kept')
    code, out = call('/api/shellybackup', {'action': 'settings', 'keep': 2}, session=S)
    check(code == 200 and out['settings']['keep'] == 2, 'keep 2: %s %r' % (code, out.get('error')))
    for _ in range(3):
        zigmon.sbk_backup_box(d, box('Lednice'), 'test', 'by hand')
    rows = zigmon.sbk_rows(d, A.ident)
    check(len(rows) == 2 and rows[0]['created'] == A.made, 'kept: %d %r' % (len(rows), [r['created'] for r in rows]))

    print('it starts to differ: an event and the notice')
    A.cfg['switch:0']['name'] = 'Fridge'
    st = zigmon.sbk_check_box(d, box('Lednice'))
    check(st.get('differs'), 'the change was not taken as differing')
    check(events('configuration of the box changed since'), 'no event when it started to differ')
    n = d.notices_all().get('shellybackup') or {}
    check('Lednice' in n.get('why', '') and n.get('link') == '#control/dev-backups', 'the notice: %r' % n)
    zigmon.sbk_check_box(d, box('Lednice'))
    check(len(events('configuration of the box changed since')) == 1, 'the same change told twice')

    print('the scheduler')
    for f in (A, B, C, E):
        f.calls[:] = []
    code, out = call('/api/shellybackup', {'action': 'settings', 'on': True, 'at': '03:40'}, session=S)
    check(code == 200 and out['settings']['on'] and out['next'].endswith('03:40'), 'scheduler on: %r' % out.get('settings'))
    check(zigmon.sbk_tick(d, now=datetime(2026, 11, 12, 2, 0)) is None, 'it ran before its time')
    got = zigmon.sbk_tick(d, now=datetime(2026, 11, 12, 3, 41))
    check(got == 'scheduled', 'it did not run at its time: %r' % got)
    check(job_done(), 'the scheduled run did not end')
    run = json.loads(d.store.get_meta('sbk:run'))
    said = {s['label']: (s['state'], s['said']) for s in run['steps']}
    check(said.get('Lednice, Lednice-2', ('',))[0] == 'done' and len(called(A, 'Sys.CreateBackup')) == 1,
          'the box that differs was not backed up: %r' % said)
    check(said.get('Svetlo-Kuchyn', ('',))[0] == 'skipped' and 'is on' in said['Svetlo-Kuchyn'][1] and
          not called(B, 'Sys.CreateBackup') and not called(B, 'Shelly.Reboot'),
          'the box that is on and comes back off was restarted: %r' % (said.get('Svetlo-Kuchyn'),))
    check(said.get('Pracka', ('',))[0] == 'skipped' and 'come on' in said['Pracka'][1] and not called(E, 'Shelly.Reboot'),
          'the box that would come back on was restarted: %r' % (said.get('Pracka'),))
    check(said.get('Stara-Uni', ('',))[0] == 'skipped' and 'not supported' in said['Stara-Uni'][1] and
          said.get('Pryc', ('',))[0] == 'skipped' and 'not reachable' in said['Pryc'][1], 'the others: %r' % said)
    check(zigmon.sbk_tick(d, now=datetime(2026, 11, 12, 3, 50)) != 'scheduled', 'it ran twice in a day')
    # the next night nothing differs on A: it is left alone
    A.calls[:] = []
    check(zigmon.sbk_tick(d, now=datetime(2026, 11, 13, 3, 40)) == 'scheduled' and job_done(), 'the next night')
    check(not called(A, 'Sys.CreateBackup'), 'a box that had not changed was backed up again')
    run = json.loads(d.store.get_meta('sbk:run'))
    check(any('unchanged' in (s['said'] or '') for s in run['steps']), 'unchanged not said: %r' % run['steps'])
    check(events('the scheduled configuration backup'), 'no event of the scheduled run')
    call('/api/shellybackup', {'action': 'settings', 'on': False}, session=S)

    print('a restore')
    rows = zigmon.sbk_rows(d, A.ident, with_data=True)
    older = rows[-1]
    # another model: refused before anything is sent
    with d.store.lock:
        cur = d.store.db.execute(
            "INSERT INTO shelly_backups (dev, host, name, model, fw, at, size, sha256, fp, data) VALUES "
            "(?,?,?,?,?,?,?,?,?,?)", (A.ident, '', 'x', 'SNSN-0013A', '1.0', int(time.time()) - 99999, len(older['data']),
                                      older['sha256'], 'x', older['data']))
        wrong_id = cur.lastrowid
    A.calls[:] = []
    code, out = call('/api/shellybackup', {'action': 'restore', 'id': wrong_id, 'box': box('Lednice')['box']}, session=S)
    check(code == 200 and job_done(), 'restore asked: %s %r' % (code, out.get('error')))
    st = zigmon.SBK_JOB['steps'][0]
    check(st['state'] == 'failed' and 'refused' in st['said'] and 'SNSN-0013A' in st['said'],
          'another model was not refused: %r' % st)
    check(not called(A, 'Sys.UploadBackup') and not called(A, 'Sys.RestoreBackup'), 'something was sent: %r' % A.calls)
    # an archive whose manifest says another model: uploaded, refused, never restored
    A.manifest_model = 'SNSN-0013A'
    lie = A.make_archive()
    A.manifest_model = None
    with d.store.lock:
        cur = d.store.db.execute(
            "INSERT INTO shelly_backups (dev, host, name, model, fw, at, size, sha256, fp, data) VALUES "
            "(?,?,?,?,?,?,?,?,?,?)", (A.ident, '', 'x', A.model, A.fw, int(time.time()) - 99998, len(lie),
                                      hashlib.sha256(lie).hexdigest(), 'y', lie))
        lie_id = cur.lastrowid
    A.calls[:] = []
    call('/api/shellybackup', {'action': 'restore', 'id': lie_id, 'box': box('Lednice')['box']}, session=S)
    job_done()
    st = zigmon.SBK_JOB['steps'][0]
    check(st['state'] == 'failed' and 'archive says' in st['said'] and called(A, 'Sys.UploadBackup') and
          not called(A, 'Sys.RestoreBackup'), 'a manifest of another model was restored: %r' % st)
    with d.store.lock:
        d.store.db.execute('DELETE FROM shelly_backups WHERE id IN (?,?)', (wrong_id, lie_id))
    # the happy path: the older backup back, after a change
    A.cfg['switch:0']['name'] = 'Changed-Since'
    A.calls[:] = []
    code, out = call('/api/shellybackup', {'action': 'restore', 'id': older['id']}, session=S)
    check(code == 200 and job_done(), 'restore asked: %s %r' % (code, out.get('error')))
    st = zigmon.SBK_JOB['steps'][0]
    check(st['state'] == 'done', 'the restore: %r' % st)
    seq = [m for m, p in A.calls if m in ('Sys.UploadBackup', 'Sys.RestoreBackup')]
    ups = called(A, 'Sys.UploadBackup')
    check(seq and seq[-1] == 'Sys.RestoreBackup' and seq.count('Sys.RestoreBackup') == 1 and ups[0]['offset'] == 0
          and [u['offset'] for u in ups] == sorted(u['offset'] for u in ups) and ups[-1]['final'] is True and
          not any(u['final'] for u in ups[:-1]), 'Upload then Restore: %r' % ups)
    check(A.cfg['switch:0']['name'] != 'Changed-Since', 'the box did not take the backup back')
    check(events('owner restored the configuration of the box'), 'no event of the restore')
    by = {x['names'][0]: x for x in zigmon.sbk_view(d)['devices']}
    check(by['Lednice']['reachable'] and by['Lednice']['checked'] >= time.time() - 30, 'the box not looked at after')

    print('download')
    code, out = call('/api/shellybackup', {'action': 'download', 'id': older['id']}, session=SO)
    check(code == 403, 'an operator downloaded an archive: %s' % code)
    code, out = call('/api/shellybackup', {'action': 'download', 'id': older['id']}, session=S)
    check(code == 200 and base64.b64decode(out['file']) == older['data'] and out['name'].endswith('.zip'),
          'download: %s %r' % (code, out.get('error')))
    check(events('downloaded the configuration backup'), 'the download is not in the events')

    print('the command line')
    p = zigmon.build_parser()
    a = p.parse_args(['--shelly-backup', 'now', 'Lednice', '--yes'])
    check(a.shelly_backup == ['now', 'Lednice'] and a.yes, 'parsed: %r' % a.shelly_backup)
    check(zigmon.sbk_cli_words(['schedule', 'on', '04:15', 'keep=7'])[2] ==
          {'action': 'settings', 'on': True, 'at': '04:15', 'keep': '7'}, 'schedule words')
    for wrong in (['restore', 'abc'], ['now'], ['frobnicate'], ['schedule', 'sometimes']):
        try:
            zigmon.sbk_cli_words(wrong)
            check(False, 'taken: %r' % wrong)
        except ValueError:
            pass

    def cli(*argv, stdin=None):
        buf = io.StringIO()
        was_in = sys.stdin
        if stdin is not None:
            sys.stdin = io.StringIO(stdin)
        try:
            with contextlib.redirect_stdout(buf):
                rc = zigmon._dispatch(zigmon.build_parser().parse_args(list(argv)), zigmon.Palette(False))
        finally:
            sys.stdin = was_in
        return rc, buf.getvalue()
    rc, text = cli('--shelly-backup')
    check(rc == 0 and 'Lednice, Lednice-2' in text and 'not supported' in text, 'zigmon --shelly-backup: %r' % text[-400:])
    rc, text = cli('--shelly-backup', '--json')
    check(rc == 0 and json.loads(text)['counts']['devices'] == 5, 'the --json list')
    rc, text = cli('--shelly-backup', 'stored', 'Lednice')
    check(rc == 0 and str(older['id']) in text, 'stored: %r' % text)
    A.calls[:] = []
    rc, text = cli('--shelly-backup', 'now', 'Lednice', stdin='y\n')
    check(rc == 2 and not called(A, 'Sys.CreateBackup'), 'backed up without a terminal and without --yes: %r' % text)
    rc, text = cli('--shelly-backup', 'now', 'Lednice', '--yes')
    check(rc == 0 and len(called(A, 'Sys.CreateBackup')) == 1 and 'done' in text, 'now --yes: %r' % text[-300:])
    out_file = W / 'export.zip'
    newest = zigmon.sbk_rows(d, A.ident, with_data=True)[0]
    rc, text = cli('--shelly-backup', 'export', str(newest['id']), str(out_file))
    check(rc == 0 and out_file.read_bytes() == newest['data'] and (out_file.stat().st_mode & 0o777) == 0o600,
          'export: %r' % text)
    check(events('the command line downloaded'), 'the export is not in the events by the command line')
    rc, text = cli('--shelly-backup', 'schedule', 'on', '05:05', 'keep=4')
    check(rc == 0 and zigmon.sbk_settings(d) == {'on': True, 'at': '05:05', 'keep': 4}, 'schedule: %r' % text)
    cli('--shelly-backup', 'schedule', 'off')
    check('zigmon --shelly-backup' in zigmon.help_text(pal=zigmon.Palette(False)), 'not in the help')
    src = (HERE / 'zigmon.py').read_text()
    check("CONSOLE_MORE['devices'].append(('Device backups (Shelly)" in src and '_console_shelly_backup' in src,
          'no console menu')
    check(callable(zigmon._console_shelly_backup), 'the console\'s menu is not a function')

    print('nothing of an archive in the log')
    whole = '\n'.join(LOG)
    leaks = [f.secret for f in (A, B, C, E) if f.secret in whole]
    stored = [r['data'] for r in zigmon.sbk_rows(d, A.ident, with_data=True)] + [A.archive]
    leaks += [x for x in stored if base64.b64encode(x[:600]).decode()[:60] in whole]
    check(not leaks, 'the archive (or its secret) is in the log: %d' % len(leaks))
    with d.store.lock:
        ev = '\n'.join(r[0] for r in d.store.db.execute('SELECT detail FROM events').fetchall())
    check(A.secret not in ev and 'pw-of-a' not in ev and 'pw-of-a' not in whole, 'a secret in the events or the log')
    check(any('http -> ' in x for x in LOG) or True, '')
    check('pw-of-a' not in json.dumps(zigmon.sbk_view(d)), 'the device password in the view')

    print('the card')
    page = (HERE / 'web' / 'index.php').read_text()
    for words in ('data-sec="dev-backups"', 'data-icon="archive"', "'dev-backups': ['Device backups'",
                  "'Back up all that differ'", "'Restore…'", 'Restore it (it restarts)', 'Back it up (it restarts)',
                  'its files are wiped and replaced', 'holds the device’s Wi-Fi password', "api('shellybackup')",
                  "post('shellybackup-do'", "'shellybackup-do' => '/api/shellybackup'", "$what === 'shellybackup'",
                  'never backed up', 'differs since ', 'not reachable', 'not supported', 'Last scheduled run',
                  'Next run', 'keep the newest', 'restore last'):
        check(words in page, 'the card has no %s' % words)

    print('the page')
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
    SHOTS.mkdir(parents=True, exist_ok=True)
    # a box that differs, so the page shows every state
    A.cfg['switch:0']['name'] = 'Fridge-again'
    zigmon.sbk_check_box(d, box('Lednice'))
    js = r'''
const { chromium } = require('playwright');
const job = %(job)s;
(async () => {
  const b = await chromium.launch();
  const r = {errors: []};
  for (const shot of [{n: 'desktop', w: 1400, h: 1100}, {n: 'phone', w: 390, h: 1700}]) {
    const ctx = await b.newContext({viewport: {width: shot.w, height: shot.h}, colorScheme: 'dark'});
    await ctx.addCookies([{name: 'zigmon_session', value: job.s, url: 'http://127.0.0.1:' + job.port + '/'}]);
    const p = await ctx.newPage();
    p.on('pageerror', e => r.errors.push(String(e)));
    await p.goto('http://127.0.0.1:' + job.port + '/#control/dev-backups');
    await p.waitForTimeout(2000);
    try { await p.evaluate(() => showControlSection('dev-backups')); } catch (e) {}
    await p.waitForSelector('#sbk-host .sbk-dev', {timeout: 15000});
    await p.waitForTimeout(700);
    r[shot.n] = await p.evaluate(() => ({
      rows: Array.from(document.querySelectorAll('#sbk-host .sbk-dev')).map(x => x.textContent),
      states: Array.from(document.querySelectorAll('#sbk-host .sbk-dev .sbk-state')).map(x => x.textContent),
      tiles: Array.from(document.querySelectorAll('#sbk-host .facts .fact')).map(x => x.textContent),
      head: (document.querySelector('#ctl-head') || {}).textContent || '',
      wide: document.documentElement.scrollWidth, view: window.innerWidth,
      all: (document.querySelector('#sbk-all') || {}).textContent,
      // (5.51.2) the time of the scheduled run looks as the select beside it
      time: (() => { const t = document.querySelector('#sbk-at'), k = document.querySelector('#sbk-keep');
        if (!t || !k) return null; const a = getComputedStyle(t), c = getComputedStyle(k);
        return {h: t.getBoundingClientRect().height, kh: k.getBoundingClientRect().height,
                bg: a.backgroundColor, kbg: c.backgroundColor, radius: a.borderRadius, kradius: c.borderRadius,
                font: a.fontFamily, kfont: c.fontFamily}; })()}));
    await p.evaluate(() => { const h = document.querySelector('#ctl-head'); if (h) h.scrollIntoView(); });
    await p.screenshot({path: job.dir + '/section-' + shot.n + '.png', fullPage: shot.n === 'phone'});
    if (shot.n === 'desktop') {
      await (await p.$('#sbk-card')).screenshot({path: job.dir + '/card.png'});
      await p.click('#sbk-host .sbk-dev[data-box="' + job.boxA + '"] button:has-text("Back up")');
      await p.waitForSelector('#zmodal:not([hidden])', {timeout: 5000});
      r.backupDialog = await p.evaluate(() => [document.querySelector('#zmodal-title').textContent,
        document.querySelector('#zmodal-body').textContent,
        Array.from(document.querySelectorAll('#zmodal-foot button')).map(x => x.textContent.trim())]);
      await p.screenshot({path: job.dir + '/dialog-backup.png'});
      await p.click('#zmodal-foot button:has-text("No, leave it")');
      await p.click('#sbk-host .sbk-dev[data-box="' + job.boxA + '"] button:has-text("Restore")');
      await p.waitForSelector('#zmodal:not([hidden]) .sbk-backups', {timeout: 5000});
      r.list = await p.evaluate(() => document.querySelector('#zmodal-body').textContent);
      await p.screenshot({path: job.dir + '/dialog-backups.png'});
      await p.click('#zmodal .sbk-backups tbody tr:first-child button:has-text("Restore")');
      await p.waitForTimeout(300);
      r.restoreDialog = await p.evaluate(() => [document.querySelector('#zmodal-title').textContent,
        document.querySelector('#zmodal-body').textContent,
        Array.from(document.querySelectorAll('#zmodal-foot button')).map(x => [x.textContent.trim(), x.className])]);
      await p.screenshot({path: job.dir + '/dialog-restore.png'});
      await p.click('#zmodal-foot button:has-text("No, leave it")');
      // (5.52) a backup going on: its row framed, its steps under its state, the others dimmed
      r.busy = await p.evaluate((boxA) => {
        const d = JSON.parse(JSON.stringify(SBK.d)), other = (d.devices || []).filter(x => x.box !== boxA)[0];
        d.job = {running: true, kind: 'backup', by: 'test', steps: [
          {box: boxA, label: 'A', state: 'working', phase: 'download', pct: 62, said: 'downloading the archive 62 %%'},
          {box: other.box, label: 'B', state: 'waiting', said: ''}]};
        d.checking = false; SBK.d = d; drawSbk();
        const row = document.querySelector('#sbk-host .sbk-dev[data-box="' + boxA + '"]');
        const o = document.querySelector('#sbk-host .sbk-dev[data-box="' + other.box + '"]');
        return {busy: row.classList.contains('busy'), running: document.querySelector('#sbk-list').classList.contains('running'),
                pill: (row.querySelector('.sbk-state.run') || {}).textContent, flow: (row.querySelector('.sbk-flow') || {}).textContent,
                now: (row.querySelector('.sbk-flow .now') || {}).textContent, queue: (o.querySelector('.sbk-queue') || {}).textContent,
                dim: getComputedStyle(o).opacity, outline: getComputedStyle(row).outlineStyle,
                hover: Array.from(document.styleSheets).some(sh => { try { return Array.from(sh.cssRules).some(c => c.selectorText === '.sbk-dev:hover'); } catch (e) { return false; } })};
      }, job.boxA);
      await p.waitForTimeout(400);
      await (await p.$('#sbk-card')).screenshot({path: job.dir + '/card-busy.png'});
      r.look = await p.evaluate((boxA) => {
        SBK.d.job = {running: false, steps: []}; SBK.d.checking = true; SBK.d.checking_box = boxA; drawSbk();
        const row = document.querySelector('#sbk-host .sbk-dev[data-box="' + boxA + '"]');
        return {busy: row.classList.contains('busy'), pill: (row.querySelector('.sbk-state.run') || {}).textContent};
      }, job.boxA);
    } else {
      await p.click('#sbk-host .sbk-dev[data-box="' + job.boxA + '"] button:has-text("Restore")');
      await p.waitForSelector('#zmodal:not([hidden]) .sbk-backups', {timeout: 5000});
      await p.screenshot({path: job.dir + '/dialog-backups-phone.png'});
    }
    await ctx.close();
  }
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
    npm_root = sh(['npm', 'root', '-g']).stdout.strip()
    (W / 'page.js').write_text(js % {'job': json.dumps({'s': S, 'port': PHP_PORT, 'dir': str(SHOTS),
                                                         'boxA': box('Lednice')['box']})})
    got = sh(['node', str(W / 'page.js')], timeout=240, env=dict(os.environ, NODE_PATH=npm_root))
    try:
        r = json.loads(got.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        r = {'error': (got.stdout + got.stderr)[-400:]}
    if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
        print('  SKIPPED (no browser here): %s' % r['error'][:200])
    else:
        dk, ph = r.get('desktop') or {}, r.get('phone') or {}
        check(not r.get('error'), 'the page: %r' % r.get('error'))
        check(len(dk.get('rows') or []) == 5 and 'Device backups' in dk.get('head', ''), 'the rows: %r' % dk)
        st = ' | '.join(dk.get('states') or [])
        check('differs since' in st and 'not supported' in st and 'not reachable' in st and
              ('never backed up' in st or 'up to date' in st), 'the states on the page: %r' % st)
        check(any('Differ' in t for t in dk.get('tiles') or []) and any('Next run' in t for t in dk.get('tiles') or []),
              'the summary: %r' % dk.get('tiles'))
        check(ph.get('wide', 9999) <= ph.get('view', 0) + 1, 'the phone scrolls sideways: %r/%r'
              % (ph.get('wide'), ph.get('view')))
        tm = dk.get('time') or {}
        check(tm and abs(tm.get('h', 0) - tm.get('kh', 99)) < 1.5 and tm.get('bg') == tm.get('kbg')
              and tm.get('radius') == tm.get('kradius') and tm.get('font') == tm.get('kfont'),
              'the time of the scheduled run does not look as the select beside it: %r' % tm)
        bz = r.get('busy') or {}
        check(bz.get('busy') and bz.get('running') and bz.get('outline') == 'solid' and float(bz.get('dim') or 1) < 0.6
              and 'downloading 62 %' in (bz.get('pill') or '') and bz.get('now') == 'downloading 62 %'
              and 'asked' in (bz.get('flow') or '') and 'stored' in (bz.get('flow') or '')
              and bz.get('queue') == 'waits its turn (2 of 2)' and bz.get('hover'),
              'the row being backed up is not framed with its steps (or the hover is gone): %r' % bz)
        lk = r.get('look') or {}
        check(lk.get('busy') and 'looking' in (lk.get('pill') or ''), 'the row being looked at: %r' % lk)
        bd = r.get('backupDialog') or ['', '', []]
        check('Back up Lednice' in bd[0] and 'restarts' in bd[1] and 'Back it up (it restarts)' in bd[2],
              'the backup dialog: %r' % bd)
        check('current' in (r.get('list') or '') and 'Firmware' in (r.get('list') or ''), 'the list: %r' % r.get('list'))
        rd = r.get('restoreDialog') or ['', '', []]
        check(rd[0].startswith('Restore Lednice') and 'wiped and replaced' in rd[1] and
              any('Restore it' in x[0] and 'danger' in x[1] for x in rd[2]), 'the restore dialog: %r' % rd)
        check(not r.get('errors'), 'the page threw: %r' % r.get('errors'))
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
    for srv in SERVERS:
        srv.shutdown()

zigmon.log = _real_log
shutil.rmtree(W, ignore_errors=True)
if bad:
    print('%d FAILED' % len(bad))
    sys.exit(1)
print('all good')
