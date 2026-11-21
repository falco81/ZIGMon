#!/usr/bin/env python3
"""Device backups (5.56): the backups of a device no longer configured, and the same device
configured again - checked against fake Shelly boxes (as in review551_shellybackup.py).

  * the backups are kept under the box's own id (Shelly.GetDeviceInfo `id`); a box taken out
    of the configuration leaves them behind: listed as "not configured now" (the view, the
    count, the notice), never deleted by themselves;
  * deleted by hand only - one, or all of a device's (an administrator's: an operator and
    nobody get 403; a configured device's are not deleted wholesale);
  * the same box configured again under another name and address: its backups listed under
    it, an event, the notice gone, a restore works, the newest N kept of them and the new ones;
  * a backup kept under 'host:ADDRESS' is moved to the box's id once that address answers with
    one - never when it does not answer, nor when it answers with none; a box whose id is
    spelled otherwise but ends with the same MAC has them back too;
  * the command line (orphans, delete-device, help) and the console's menu;
  * the page in Chromium: the group at the bottom with its buttons and dialogs - screenshots
    into $ZIGMON_SHOTS.

    python3 test/review557_sbkorphans.py < /dev/null

Ports 20550-20569.
"""
import base64
import contextlib
import hashlib
import io
import json
import os
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-sbkorphans-'))
API_PORT, PHP_PORT = 20550, 20551
PORT_K, PORT_H, PORT_K2, PORT_P, PORT_NONE, PORT_NOID, PORT_M = 20552, 20553, 20554, 20555, 20556, 20557, 20558
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


class Fake(object):
    """A Gen3-like box, no password: its id and MAC as given, a backup made as it starts."""

    def __init__(self, port, ident, mac, model='S3PL-00112EU', app='PlugSG3', fw='2.2.0'):
        self.port, self.ident, self.mac, self.model, self.app, self.fw = port, ident, mac, model, app, fw
        self.cfg = {'switch:0': {'id': 0, 'name': None, 'initial_state': 'restore_last'},
                    'sys': {'device': {'name': ident, 'mac': mac}}}
        self.revs = {'cfg_rev': 10, 'kvs_rev': 3}
        self.boot = time.time() - 5000
        self.down_until = 0.0
        self.pending = False
        self.restoring = None
        self.backup = {}
        self.archive = b''
        self.made = 1767225600
        self.upload = bytearray()
        self.calls = []
        self.lock = threading.Lock()

    def make_archive(self):
        z = io.BytesIO()
        with zipfile.ZipFile(z, 'w', zipfile.ZIP_DEFLATED) as f:
            self.made += 1
            f.writestr('manifest.json', json.dumps({'created_at': self.made, 'fw_ver': self.fw, 'model': self.model,
                                                    'app_name': self.app, 'encrypt': False}))
            f.writestr('config.json', json.dumps({'cfg': self.cfg, 'revs': self.revs}))
        return z.getvalue()

    def settle(self):
        if self.down_until and time.time() >= self.down_until:
            self.down_until = 0.0
            self.boot = time.time()
            if self.pending:
                self.pending = False
                self.archive = self.make_archive()
                self.backup = {'created': self.made}
            if self.restoring is not None:
                with zipfile.ZipFile(io.BytesIO(self.restoring)) as f:
                    got = json.loads(f.read('config.json'))
                self.cfg, self.revs = got['cfg'], got['revs']
                self.restoring = None

    def answer(self, m, p):
        if m == 'Shelly.GetDeviceInfo':
            return {'id': self.ident, 'mac': self.mac, 'model': self.model, 'gen': 3, 'ver': self.fw,
                    'app': self.app, 'provision': 'complete'}
        if m == 'Shelly.ListMethods':
            return {'methods': ['Shelly.GetStatus', 'Shelly.GetConfig', 'Shelly.GetDeviceInfo', 'Sys.GetStatus',
                                'Shelly.Reboot', 'Sys.CreateBackup', 'Sys.DownloadBackup', 'Sys.UploadBackup',
                                'Sys.RestoreBackup']}
        if m == 'Sys.GetStatus':
            r = dict({'uptime': int(time.time() - self.boot)}, **self.revs)
            if self.backup:
                r['backup'] = dict(self.backup)
            return r
        if m == 'Shelly.GetConfig':
            return json.loads(json.dumps(self.cfg))
        if m == 'Shelly.GetStatus':
            return {'switch:0': {'id': 0, 'output': False}}
        if m == 'Shelly.Reboot':
            self.down_until = time.time() + 0.6
            return None
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
            self.upload += base64.b64decode(p.get('data') or '')
            if p.get('final'):
                with zipfile.ZipFile(io.BytesIO(bytes(self.upload))) as f:
                    return {'manifest': json.loads(f.read('manifest.json'))}
            return None
        if m == 'Sys.RestoreBackup':
            self.restoring = bytes(self.upload)
            self.down_until = time.time() + 0.6
            return None
        return 'nomethod'


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
                    self.close_connection = True
                    return
                m, p = body.get('method'), body.get('params') or {}
                fake.calls.append(m)
                r = fake.answer(m, p)
            out = ({'id': 1, 'error': {'code': 404, 'message': 'No handler for %s' % m}} if r == 'nomethod'
                   else {'id': body.get('id'), 'src': fake.ident, 'result': r})
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


K = Fake(PORT_K, 'shellyplugsg3-a1b2c3d4e5f6', 'A1B2C3D4E5F6')                   # the kitchen's plug
H = Fake(PORT_H, 'shelly1g4-0a0b0c0d0e0f', '0A0B0C0D0E0F', model='S4SW-001X16EU', app='S1G4')
K2 = Fake(PORT_K2, K.ident, K.mac)                  # the same plug, moved to another address
P = Fake(PORT_P, 'shellyplugsg3-c0ffee000001', 'C0FFEE000001')                   # backups under host: before
NOID = Fake(PORT_NOID, '', '')                                                    # answers with no id
M = Fake(PORT_M, 'shellyplugsg3-112233445566', '112233445566')                   # its id spelled otherwise once
SERVERS = []

sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                               # noqa: E402

LOG = []
_real_log = zigmon.log
zigmon.log = lambda msg, level='info', *a, **k: LOG.append('%s %s' % (level, msg))
zigmon.load_config()
(W / 'state').mkdir()
PLUG_K = {'name': 'Kuchyn', 'host': '127.0.0.1:%d' % PORT_K}
PLUG_H = {'name': 'Chodba', 'host': '127.0.0.1:%d' % PORT_H}
zigmon.CONFIG.update({
    'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1', 'token_file': str(W / 'token'),
    'pin': '', 'sensors': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(W / 'state'), 'debug': 0,
    'plugs': [PLUG_K, PLUG_H]})
zigmon.SBK_WAIT_S = 20.0
zigmon.SBK_POLL_S = 0.3
zigmon.SBK_CHUNK = 1024
zigmon.SBK_TIMEOUT = 2.0
d = zigmon.Daemon()
d.notify = lambda message, *a, **k: None
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def call(path, body=None, session=None):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': '192.168.40.10'}
    if session:
        headers['X-Zigmon-Session'] = session
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


def wait(cond, s=60.0):
    end = time.time() + s
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def box(name):
    return zigmon.sbk_find_box(d, name)


def configure(*plugs):
    zigmon.CONFIG['plugs'] = [dict(p) for p in plugs]
    d.reload_devices()


def rows(dev=None):
    with d.store.lock:
        if dev is None:
            return [dict(r) for r in d.store.db.execute('SELECT id, dev FROM shelly_backups ORDER BY id').fetchall()]
        return [dict(r) for r in d.store.db.execute('SELECT id, dev FROM shelly_backups WHERE dev=? ORDER BY id',
                                                    (dev,)).fetchall()]


def events(text):
    d.store.flush()
    with d.store.lock:
        return [dict(r) for r in d.store.db.execute(
            "SELECT * FROM events WHERE detail LIKE ? ORDER BY id", ('%' + text + '%',)).fetchall()]


def notice():
    return d.notices_all().get('shellybackup-orphans')


def insert(dev, host='', name='x', model='S3PL-00112EU', at=None):
    raw = K.make_archive()
    with d.store.lock:
        return d.store.db.execute(
            "INSERT INTO shelly_backups (dev, host, name, model, fw, at, size, sha256, fp, data) VALUES "
            "(?,?,?,?,?,?,?,?,?,?)", (dev, host, name, model, '2.2.0', at or int(time.time()) - 5000, len(raw),
                                      hashlib.sha256(raw).hexdigest(), 'old', raw)).lastrowid


def view(session=None):
    return call('/api/shellybackup', session=session or S)


try:
    for f in (K, H, K2, P, NOID, M):
        SERVERS.append(serve(f))

    print('how the backups are keyed')
    zigmon.sbk_check_box(d, box('Kuchyn'))
    zigmon.sbk_check_box(d, box('Chodba'))
    check(box('Kuchyn')['dev'] == K.ident and box('Chodba')['dev'] == H.ident,
          'a box looked at is keyed by its own id: %r' % [box('Kuchyn')['dev'], box('Chodba')['dev']])
    for _ in range(2):
        zigmon.sbk_backup_box(d, box('Kuchyn'), 'owner', 'by hand')
    zigmon.sbk_backup_box(d, box('Chodba'), 'owner', 'by hand')
    check([r['dev'] for r in rows()] == [K.ident, K.ident, H.ident], 'stored under the ids: %r' % rows())
    zigmon.sbk_tick(d)
    check(notice() is None, 'a notice with every device configured: %r' % notice())
    code, v = view()
    check(code == 200 and v['orphans'] == [] and v['counts']['orphaned'] == 0, 'orphans with none: %r' % v.get('orphans'))

    print('a device taken out of the configuration')
    configure(PLUG_H)
    zigmon.sbk_tick(d)
    check(len(rows(K.ident)) == 2, 'its backups were deleted: %r' % rows())
    code, v = view()
    o = (v.get('orphans') or [{}])[0]
    check(code == 200 and len(v['orphans']) == 1 and o.get('dev') == K.ident and o.get('count') == 2 and
          o.get('mac') == 'a1b2c3d4e5f6' and o.get('model') == 'S3PL-00112EU' and o.get('fw') == '2.2.0' and
          o.get('name') == 'Kuchyn' and o.get('size', 0) > 0 and o.get('newest') and len(o.get('backups') or []) == 2,
          'the orphan in the view: %r' % {k: o.get(k) for k in o if k != 'backups'})
    check(v['counts']['orphaned'] == 2 and v['counts']['orphan_devices'] == 1 and v['counts']['devices'] == 1,
          'the counts: %r' % v['counts'])
    check('data' not in json.dumps(v['orphans']), 'an archive in the view')
    n = notice() or {}
    check(n.get('level') == 'info' and '2 backup(s) belong to devices no longer configured' in n.get('why', '') and
          'Device backups' in n.get('why', '') and n.get('link') == '#control/dev-backups', 'the notice: %r' % n)
    stamp = n.get('stamp')
    zigmon.sbk_tick(d)
    zigmon.sbk_orphans_sync(d, force=True)
    check((notice() or {}).get('stamp') == stamp, 'the notice was told again with nothing new')
    # restoring a backup of a device not configured: refused, it has no box
    code, out = call('/api/shellybackup', {'action': 'restore', 'id': o['backups'][0]['id']}, session=S)
    check(code == 400 and 'not configured here now' in out.get('error', ''), 'an orphan restored: %s %r' % (code, out))
    # ...nor into another box
    code, out = call('/api/shellybackup', {'action': 'restore', 'id': o['backups'][0]['id'], 'box': box('Chodba')['box']},
                     session=S)
    check(code == 200 and wait(lambda: not zigmon.SBK_JOB['running']) and
          zigmon.SBK_JOB['steps'][0]['state'] == 'failed' and 'Sys.UploadBackup' not in H.calls,
          'an orphan restored into another box: %r' % zigmon.SBK_JOB['steps'])

    print('deleted by hand, an administrator\'s')
    one = o['backups'][-1]['id']
    for who, sess in (('an operator', SO), ('nobody', None)):
        code, _ = call('/api/shellybackup', {'action': 'delete', 'id': one}, session=sess)
        check(code == 403, '%s deleted a backup: %s' % (who, code))
        code, _ = call('/api/shellybackup', {'action': 'delete_device', 'dev': K.ident}, session=sess)
        check(code == 403, '%s deleted a device\'s backups: %s' % (who, code))
    check(len(rows(K.ident)) == 2, 'deleted all the same: %r' % rows())
    code, out = call('/api/shellybackup', {'action': 'delete', 'id': one}, session=S)
    check(code == 200 and len(rows(K.ident)) == 1 and out['counts']['orphaned'] == 1, 'delete one: %s %r' % (code, out.get('error')))
    check(events('deleted the stored configuration backup %d' % one), 'no event of the delete')
    check('1 backup(s) belong' in (notice() or {}).get('why', ''), 'the notice after one deleted: %r' % notice())
    code, out = call('/api/shellybackup', {'action': 'delete_device', 'dev': H.ident}, session=S)
    check(code == 400 and 'configured here' in out.get('error', '') and len(rows(H.ident)) == 1,
          'a configured device\'s backups deleted wholesale: %s %r' % (code, out))
    code, out = call('/api/shellybackup', {'action': 'delete_device', 'dev': 'shellynothing-000000000000'}, session=S)
    check(code == 400, 'deleting the backups of nothing: %s' % code)

    print('the same device configured again, another name, another address')
    configure(PLUG_H, {'name': 'Lednice-Nova', 'host': '127.0.0.1:%d' % PORT_K2})
    zigmon.sbk_tick(d)
    check(notice() is not None and box('Lednice-Nova')['dev'] == 'host:127.0.0.1:%d' % PORT_K2,
          'before it was looked at: %r' % box('Lednice-Nova')['dev'])
    zigmon.sbk_check_box(d, box('Lednice-Nova'))
    check(box('Lednice-Nova')['dev'] == K.ident, 'not keyed by its id: %r' % box('Lednice-Nova')['dev'])
    ev = events('belong to Lednice-Nova again')
    check(len(ev) == 1 and K.ident in ev[0]['detail'] and '1 configuration backup' in ev[0]['detail'] and
          ev[0]['device'] == 'plug:Lednice-Nova', 'the event of the re-pairing: %r' % ev)
    check(notice() is None, 'the notice stayed: %r' % notice())
    code, v = view()
    by = {x['names'][0]: x for x in v['devices']}
    x = by.get('Lednice-Nova') or {}
    check(not v['orphans'] and x.get('count') == 1 and x.get('status') == 'same' and x['backups'][0]['current'],
          'its backups listed under it: %r' % {k: x.get(k) for k in ('count', 'status', 'dev')})
    zigmon.sbk_tick(d)
    check(len(events('belong to Lednice-Nova again')) == 1, 'the re-pairing told twice')
    # it differs from its (old) newest backup
    K2.cfg['switch:0']['name'] = 'Fridge'
    check(zigmon.sbk_check_box(d, box('Lednice-Nova')).get('differs'), 'the comparison does not use its old backup')
    # a restore works
    old_id = x['backups'][0]['id']
    code, out = call('/api/shellybackup', {'action': 'restore', 'id': old_id}, session=S)
    check(code == 200 and wait(lambda: not zigmon.SBK_JOB['running']) and
          zigmon.SBK_JOB['steps'][0]['state'] == 'done' and K2.cfg['switch:0']['name'] is None,
          'the restore of a re-paired device: %s %r %r' % (code, out.get('error'), zigmon.SBK_JOB['steps']))
    # a backup of another model is still refused
    wrong = insert(K.ident, model='SNSN-0013A', at=int(time.time()) - 9999)
    call('/api/shellybackup', {'action': 'restore', 'id': wrong}, session=S)
    wait(lambda: not zigmon.SBK_JOB['running'])
    st = zigmon.SBK_JOB['steps'][0]
    check(st['state'] == 'failed' and 'SNSN-0013A' in st['said'], 'another model restored: %r' % st)
    with d.store.lock:
        d.store.db.execute('DELETE FROM shelly_backups WHERE id=?', (wrong,))
    # the newest N: of its old ones and its new ones together
    call('/api/shellybackup', {'action': 'settings', 'keep': 2}, session=S)
    zigmon.sbk_backup_box(d, box('Lednice-Nova'), 'owner', 'by hand')
    check(old_id in [r['id'] for r in rows(K.ident)] and len(rows(K.ident)) == 2, 'kept: %r' % rows(K.ident))
    zigmon.sbk_backup_box(d, box('Lednice-Nova'), 'owner', 'by hand')
    check(old_id not in [r['id'] for r in rows(K.ident)] and len(rows(K.ident)) == 2,
          'the re-paired backup is outside the newest 2: %r' % rows(K.ident))

    print('a backup kept under its address, before its id was known')
    hp = insert('host:127.0.0.1:%d' % PORT_P, host='127.0.0.1:%d' % PORT_P, name='Spajz')
    hn = insert('host:127.0.0.1:%d' % PORT_NONE, host='127.0.0.1:%d' % PORT_NONE, name='Nikde')
    hi = insert('host:127.0.0.1:%d' % PORT_NOID, host='127.0.0.1:%d' % PORT_NOID, name='Bezid')
    configure(PLUG_H, {'name': 'Lednice-Nova', 'host': '127.0.0.1:%d' % PORT_K2},
              {'name': 'Spajz', 'host': '127.0.0.1:%d' % PORT_P}, {'name': 'Nikde', 'host': '127.0.0.1:%d' % PORT_NONE},
              {'name': 'Bezid', 'host': '127.0.0.1:%d' % PORT_NOID})
    zigmon.sbk_tick(d)
    code, v = view()
    by = {x['names'][0]: x for x in v['devices']}
    check(not v['orphans'] and by['Spajz']['count'] == 1, 'a host: backup of a configured box is not its own: %r'
          % v['orphans'])
    for name in ('Spajz', 'Nikde', 'Bezid'):
        zigmon.sbk_check_box(d, box(name))
    check([r['dev'] for r in rows() if r['id'] == hp] == [P.ident], 'not moved to its id: %r' % rows())
    check([r['dev'] for r in rows() if r['id'] == hn] == ['host:127.0.0.1:%d' % PORT_NONE],
          'moved although the box did not answer: %r' % rows())
    check([r['dev'] for r in rows() if r['id'] == hi] == ['host:127.0.0.1:%d' % PORT_NOID],
          'moved although the box answered with no id: %r' % rows())
    check(events('kept under its address 127.0.0.1:%d now belong to Spajz' % PORT_P), 'no event of the move')
    code, v = view()
    by = {x['names'][0]: x for x in v['devices']}
    check(by['Spajz']['dev'] == P.ident and by['Spajz']['count'] == 1 and not v['orphans'],
          'after the move: %r %r' % (by['Spajz'].get('dev'), v['orphans']))

    print('its id spelled otherwise, the same MAC')
    mo = insert('shellyplusplugs-112233445566', name='Garaz-stara', model=M.model)
    zigmon.sbk_tick(d)
    check(any(o['dev'] == 'shellyplusplugs-112233445566' for o in view()[1]['orphans']), 'not an orphan first')
    configure(PLUG_H, {'name': 'Lednice-Nova', 'host': '127.0.0.1:%d' % PORT_K2},
              {'name': 'Spajz', 'host': '127.0.0.1:%d' % PORT_P}, {'name': 'Garaz', 'host': '127.0.0.1:%d' % PORT_M})
    zigmon.sbk_check_box(d, box('Garaz'))
    check([r['dev'] for r in rows() if r['id'] == mo] == [M.ident], 'the same MAC not re-paired: %r' % rows())
    check(events('(the same MAC) now belong to Garaz'), 'no event of the MAC re-pairing')

    print('all of a device\'s')
    configure({'name': 'Lednice-Nova', 'host': '127.0.0.1:%d' % PORT_K2}, {'name': 'Spajz', 'host': '127.0.0.1:%d' % PORT_P},
              {'name': 'Garaz', 'host': '127.0.0.1:%d' % PORT_M})
    zigmon.sbk_tick(d)
    code, v = view()
    devs = sorted(o['dev'] for o in v['orphans'])
    check(H.ident in devs and notice() is not None, 'Chodba not an orphan: %r' % devs)

    print('the command line')

    def cli(*argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = zigmon._dispatch(zigmon.build_parser().parse_args(list(argv)), zigmon.Palette(False))
        return rc, buf.getvalue()
    rc, text = cli('--shelly-backup', 'orphans', '--json')
    got = json.loads(text) if rc == 0 else []
    check(rc == 0 and [o['dev'] for o in got] == [o['dev'] for o in v['orphans']], 'orphans --json: %r' % text[-300:])
    rc, text = cli('--shelly-backup', 'orphans')
    check(rc == 0 and H.ident in text and 'not configured now' in text and 'delete-device' in text,
          'orphans: %r' % text[-400:])
    rc, text = cli('--shelly-backup')
    check(rc == 0 and 'not configured now' in text and 'zigmon --shelly-backup orphans' in text, 'the list: %r' % text[-300:])
    hb = rows(H.ident)[0]['id']
    rc, text = cli('--shelly-backup', 'restore', str(hb), '--yes')
    check(rc == 1 and 'not configured now' in text, 'an orphan restored from the command line: %r' % text)
    rc, text = cli('--shelly-backup', 'export', str(hb), str(W / 'gone.zip'))
    check(rc == 0 and (W / 'gone.zip').stat().st_size > 0, 'an orphan exported: %r' % text)
    rc, text = cli('--shelly-backup', 'delete-device', H.ident)
    check(rc == 2 and len(rows(H.ident)) == 1, 'deleted without asking: %r' % text)
    rc, text = cli('--shelly-backup', 'delete-device', K.ident, '--yes')
    check(rc == 1 and len(rows(K.ident)) == 2, 'a configured device\'s deleted from the command line: %r' % text)
    try:
        zigmon.sbk_cli_words(['delete-device'])
        check(False, 'delete-device with no id taken')
    except ValueError:
        pass
    check('zigmon --shelly-backup orphans' in zigmon.help_text(pal=zigmon.Palette(False)), 'not in the help')
    src = (HERE / 'zigmon.py').read_text()
    check("('Backups of devices not configured now: export, delete', _sbkn_orphans)" in src, 'no console item')

    print('the page')
    page = (HERE / 'web' / 'index.php').read_text()
    for words in ('Backups of devices that are not configured now (', "'Orphaned'", "action: 'delete_device'",
                  'It cannot be undone', 'not configured now', "'Delete…'", "cmdButton('Download'"):
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
    SHOTS.mkdir(parents=True, exist_ok=True)
    insert(H.ident, name='Chodba', model=H.model, at=int(time.time()) - 86400 * 3)
    js = r'''
const { chromium } = require('playwright');
const job = %(job)s;
const r = {errors: [], step: ''};
(async () => {
  const b = await chromium.launch();
  for (const shot of [{n: 'desktop', w: 1400, h: 1300}, {n: 'phone', w: 390, h: 2200}]) {
    const ctx = await b.newContext({viewport: {width: shot.w, height: shot.h}, colorScheme: 'dark'});
    await ctx.addCookies([{name: 'zigmon_session', value: job.s, url: 'http://127.0.0.1:' + job.port + '/'}]);
    const p = await ctx.newPage();
    p.setDefaultTimeout(10000);
    p.on('pageerror', e => r.errors.push(String(e)));
    r.step = shot.n + ' open';
    await p.goto('http://127.0.0.1:' + job.port + '/#control/dev-backups');
    await p.waitForTimeout(2000);
    try { await p.evaluate(() => showControlSection('dev-backups')); } catch (e) {}
    await p.waitForSelector('#sbk-orphans .sbk-dev', {timeout: 20000});
    await p.waitForTimeout(600);
    r[shot.n] = await p.evaluate(() => ({
      head: (document.querySelector('#sbk-orphans h3') || {}).textContent || '',
      rows: Array.from(document.querySelectorAll('#sbk-orphans .sbk-dev')).map(x => [x.dataset.dev, x.textContent,
        Array.from(x.querySelectorAll('button')).map(b => b.textContent.trim())]),
      last: (() => { const o = document.querySelector('#sbk-orphans'); return !!o && !o.nextElementSibling; })(),
      tiles: Array.from(document.querySelectorAll('#sbk-host .facts .fact')).map(x => x.textContent),
      wide: document.documentElement.scrollWidth, view: window.innerWidth}));
    await (await p.$('#sbk-orphans')).scrollIntoViewIfNeeded();
    await p.screenshot({path: job.dir + '/section-' + shot.n + '.png', fullPage: shot.n === 'phone'});
    if (shot.n === 'desktop') {
      await (await p.$('#sbk-card')).screenshot({path: job.dir + '/card.png'});
      const row = '#sbk-orphans .sbk-dev[data-dev="' + job.dev + '"]';
      r.step = 'click 1';
      await p.click(row + ' button:has-text("Download")');
      await p.waitForSelector('#zmodal:not([hidden])', {timeout: 5000});
      r.download = await p.evaluate(() => [document.querySelector('#zmodal-title').textContent,
        document.querySelector('#zmodal-body').textContent]);
      await p.screenshot({path: job.dir + '/dialog-download.png'});
      r.step = 'click 2';
      await p.click('#zmodal-foot button:has-text("No, leave it")');
      r.step = 'click 3';
      await p.click(row + ' button:has-text("Delete")');
      await p.waitForSelector('#zmodal:not([hidden]) .sbk-backups', {timeout: 5000});
      r.list = await p.evaluate(() => [document.querySelector('#zmodal-title').textContent,
        document.querySelector('#zmodal-body').textContent,
        Array.from(document.querySelectorAll('#zmodal-foot button')).map(x => x.textContent.trim()),
        document.querySelectorAll('#zmodal .sbk-backups tbody tr').length]);
      await p.screenshot({path: job.dir + '/dialog-orphan-list.png'});
      r.step = 'click 4';
      await p.click('#zmodal .sbk-backups tbody tr:first-child .sbk-del');
      await p.waitForTimeout(300);
      r.one = await p.evaluate(() => [document.querySelector('#zmodal-title').textContent,
        document.querySelector('#zmodal-body').textContent,
        Array.from(document.querySelectorAll('#zmodal-foot button')).map(x => [x.textContent.trim(), x.className])]);
      await p.screenshot({path: job.dir + '/dialog-delete-one.png'});
      r.step = 'click 5';
      await p.click('#zmodal-foot button:has-text("Delete it")');
      await p.waitForSelector('#zmodal:not([hidden]) .sbk-backups', {timeout: 8000});
      await p.waitForTimeout(400);
      r.after = await p.evaluate(() => document.querySelectorAll('#zmodal .sbk-backups tbody tr').length);
      r.step = 'click 6';
      await p.click('#zmodal-foot button:has-text("Delete all")');
      await p.waitForTimeout(300);
      r.all = await p.evaluate(() => [document.querySelector('#zmodal-title').textContent,
        document.querySelector('#zmodal-body').textContent,
        Array.from(document.querySelectorAll('#zmodal-foot button')).map(x => [x.textContent.trim(), x.className])]);
      await p.screenshot({path: job.dir + '/dialog-delete-all.png'});
      r.step = 'click 7';
      await p.click('#zmodal-foot button:has-text("Delete them all")');
      await p.waitForTimeout(1500);
      r.gone = await p.evaluate((dev) => ({row: !!document.querySelector('#sbk-orphans .sbk-dev[data-dev="' + dev + '"]'),
        group: !!document.querySelector('#sbk-orphans')}), job.dev);
      await (await p.$('#sbk-card')).screenshot({path: job.dir + '/card-after.png'});
    }
    await ctx.close();
  }
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e) + ' at ' + r.step, r: r})); process.exit(0); });
'''
    npm_root = sh(['npm', 'root', '-g']).stdout.strip()
    (W / 'page.js').write_text(js % {'job': json.dumps({'s': S, 'port': PHP_PORT, 'dir': str(SHOTS), 'dev': H.ident})})
    got = sh(['node', str(W / 'page.js')], timeout=300, env=dict(os.environ, NODE_PATH=npm_root))
    try:
        r = json.loads(got.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        r = {'error': (got.stdout + got.stderr)[-400:]}
    r.update({k: v for k, v in (r.get('r') or {}).items() if k not in r})
    if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
        print('  SKIPPED (no browser here): %s' % r['error'][:200])
    else:
        dk, ph = r.get('desktop') or {}, r.get('phone') or {}
        check(not r.get('error'), 'the page: %r' % r.get('error'))
        check(dk.get('head', '').startswith('Backups of devices that are not configured now (') and dk.get('last'),
              'the group at the bottom: %r' % dk.get('head'))
        hrow = [x for x in dk.get('rows') or [] if x[0] == H.ident]
        check(hrow and 'not configured now' in hrow[0][1] and '2 kept' in hrow[0][1] and 'S4SW-001X16EU' in hrow[0][1]
              and 'MAC 0A:0B:0C:0D:0E:0F' in hrow[0][1] and hrow[0][2] == ['Download', 'Delete…'],
              'the orphan row: %r' % hrow)
        check(any('Orphaned' in t for t in dk.get('tiles') or []), 'no orphaned tile: %r' % dk.get('tiles'))
        check(ph.get('wide', 9999) <= ph.get('view', 0) + 1, 'the phone scrolls sideways: %r/%r'
              % (ph.get('wide'), ph.get('view')))
        dl = r.get('download') or ['', '']
        check('Download the backup of Chodba' in dl[0] and 'Wi-Fi password' in dl[1], 'the download dialog: %r' % dl)
        ls = r.get('list') or ['', '', [], 0]
        check('Backups of Chodba' in ls[0] and ls[3] == 2 and any('Delete all 2' in x for x in ls[2]),
              'the list dialog: %r' % ls)
        one = r.get('one') or ['', '', []]
        check('Delete this backup of Chodba' in one[0] and 'cannot be undone' in one[1] and
              any('Delete it' in x[0] and 'danger' in x[1] for x in one[2]), 'the delete-one dialog: %r' % one)
        check(r.get('after') == 1, 'one deleted, the list after: %r' % r.get('after'))
        al = r.get('all') or ['', '', []]
        check('Delete every backup of Chodba (1)' in al[0] and 'cannot be undone' in al[1] and
              any('Delete them all' in x[0] and 'danger' in x[1] for x in al[2]), 'the delete-all dialog: %r' % al)
        check(not (r.get('gone') or {}).get('row') and not rows(H.ident), 'not deleted from the page: %r %r'
              % (r.get('gone'), rows(H.ident)))
        check(not r.get('errors'), 'the page threw: %r' % r.get('errors'))
        print('  screenshots: %s' % SHOTS)
    zigmon.sbk_tick(d)
    left = [o['dev'] for o in view()[1]['orphans']]
    check(notice() is not None if left else notice() is None, 'the notice with %r left: %r' % (left, notice()))
    # the last one deleted: the notice goes
    for dev in left:
        call('/api/shellybackup', {'action': 'delete_device', 'dev': dev}, session=S)
    check(notice() is None and not view()[1]['orphans'], 'the notice stayed with none left: %r' % notice())
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
