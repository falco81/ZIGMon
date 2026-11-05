#!/usr/bin/env python3
"""5.43: the performance meter - how busy the machine is, in the header of an
administrator's page, as ai 1.0.72-1.0.76 has it. Fails on 5.42.1.

    python3 test/perfmeter.py           (SHOTS=dir also keeps the screenshots)

  * off by default: no thread, not one file read, /api/perf says only that it
    is off, the page draws nothing and asks nothing;
  * on: the numbers are what a /proc and a /sys of the test's own say (the
    processor, the memory, the disks, the network, each core, the sensors,
    the filesystems by a statvfs of the test's own), for whoever may see the
    dashboard - the processes and the filesystems an administrator's only
    (5.43.1) - through the daemon and through the relay (php -S on index.php);
  * the last two minutes are kept, so a page loaded again draws its graphs at
    once with the points it had;
  * a socket switched by a sensor is as quick with the meter reading flat out
    beside it, and while a reading is held up half way;
  * the page in Chromium (Playwright): the four looks, the five styles of the
    details, the pickers in the account's popup, nothing asked while the page
    is hidden or paused, the details asked only while a panel is open, and a
    phone's width with nothing wider than the screen.

Ports 19590 (the daemon), 19591 (php -S), 19592 (a Shelly box).
"""
import json
import math
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import http.cookiejar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-perfmeter-check-'))
API_PORT, PHP_PORT, BOX_PORT = 19590, 19591, 19592
SHOTS = os.environ.get('SHOTS') or ''
PKG_IMG = os.environ.get('PKG_IMG') or ''               # ai's pictures, put beside the screenshots
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

# ---- a /proc and a /sys of the test's own ------------------------------------
PROC, SYS = W / 'proc', W / 'sys'
GiB = 1024 ** 3


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.new')
    tmp.write_text(text)
    os.replace(str(tmp), str(path))


COUNT = {'cpu': [0] * 8, 'idle': [0] * 8, 'rd': {'nvme0n1': 0, 'sda': 0}, 'wr': {'nvme0n1': 0, 'sda': 0},
         'io': {'nvme0n1': 0, 'sda': 0}, 'rx': {'eno1': 812 * 10 ** 9, 'eno2': 0, 'lo': 0, 'veth1a2b': 0},
         'tx': {'eno1': 96 * 10 ** 9, 'eno2': 0, 'lo': 0, 'veth1a2b': 0},
         'proc': {1201: 0, 1302: 0, 812: 0, 701: 0, 640: 0}}
PROC_NAMES = {1201: 'node', 1302: 'zigmon', 812: 'mosquitto', 701: 'python3', 640: 'nginx'}
PROC_RSS = {1201: 2100 * 2 ** 20, 1302: 180 * 2 ** 20, 812: 24 * 2 ** 20, 701: 60 * 2 ** 20, 640: 12 * 2 ** 20}
PAGE = os.sysconf('SC_PAGE_SIZE')
TICK = os.sysconf('SC_CLK_TCK')


def write_proc():
    cores = []
    for n in range(8):
        busy, idle = COUNT['cpu'][n], COUNT['idle'][n]
        cores.append('cpu%d %d 0 %d %d 0 0 0 0 0 0' % (n, busy * 3 // 4, busy - busy * 3 // 4, idle))
    allb, alli = sum(COUNT['cpu']), sum(COUNT['idle'])
    put(PROC / 'stat', 'cpu  %d 0 %d %d 0 0 0 0 0 0\n' % (allb * 3 // 4, allb - allb * 3 // 4, alli)
        + '\n'.join(cores) + '\nintr 0\nctxt 0\n')
    disks = []
    for name, major in (('nvme0n1', 259), ('sda', 8)):
        disks.append('%4d 0 %s 100 0 %d 50 100 0 %d 40 0 %d 90' % (major, name, COUNT['rd'][name] // 512,
                                                                    COUNT['wr'][name] // 512, COUNT['io'][name]))
    # a partition, a loop device: neither counted
    disks.append(' 259 1 nvme0n1p2 100 0 999999 50 100 0 999999 40 0 999 90')
    disks.append('   7 0 loop0 100 0 999999 50 100 0 999999 40 0 999 90')
    put(PROC / 'diskstats', '\n'.join(disks) + '\n')
    lines = ['Inter-|   Receive                                                |  Transmit',
             ' face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed']
    for nic in ('lo', 'eno1', 'eno2', 'veth1a2b'):
        lines.append('%8s: %d 10 0 0 0 0 0 0 %d 10 0 0 0 0 0 0' % (nic, COUNT['rx'][nic], COUNT['tx'][nic]))
    put(PROC / 'net' / 'dev', '\n'.join(lines) + '\n')
    for pid, ticks in COUNT['proc'].items():
        rest = ['S', '1'] + ['0'] * 9 + [str(ticks * 2 // 3), str(ticks - ticks * 2 // 3)] + ['0'] * 8 \
            + [str(PROC_RSS[pid] // PAGE)] + ['0'] * 10
        put(PROC / str(pid) / 'stat', '%d (%s) %s\n' % (pid, PROC_NAMES[pid], ' '.join(rest)))


def write_static():
    kb = lambda b: '%d kB' % (b // 1024)                  # noqa: E731
    put(PROC / 'meminfo', '\n'.join([
        'MemTotal:       ' + kb(32 * GiB), 'MemFree:        ' + kb(4 * GiB),
        'MemAvailable:   ' + kb(22 * GiB), 'Buffers:        ' + kb(GiB // 4),
        'Cached:         ' + kb(6 * GiB), 'SwapCached:     0 kB', 'Shmem:          ' + kb(114 * 2 ** 20),
        'SwapTotal:      ' + kb(8 * GiB), 'SwapFree:       ' + kb(8 * GiB)]) + '\n')
    put(PROC / 'loadavg', '3.92 3.10 2.71 2/312 4242\n')
    put(PROC / 'uptime', '1051200.55 8000000.00\n')
    put(PROC / 'cpuinfo', ''.join('processor\t: %d\nmodel name\t: AMD Ryzen 7 5800X 8-Core Processor\n'
                                  'cpu MHz\t\t: 3400.000\n\n' % n for n in range(8)))
    put(PROC / 'mounts', '\n'.join([
        '/dev/nvme0n1p2 / ext4 rw,relatime 0 0', 'proc /proc proc rw 0 0', 'tmpfs /run tmpfs rw 0 0',
        '/dev/nvme0n1p1 /boot ext4 rw 0 0', '/dev/sda1 /srv xfs rw 0 0', 'overlay /var/lib/x overlay rw 0 0',
        '/dev/sda1 /srv/again xfs rw 0 0',
        # none of these is ever asked (plexmon 2.7.1): a network share may
        # hang, FUSE is a program, FAT may count its clusters off the disk
        'nas:/export /mnt/nfs nfs4 rw 0 0', '//nas/share /mnt/smb cifs rw 0 0', 'nas:/x /mnt/nfs3 nfs rw 0 0',
        'me@nas:/ /mnt/ssh fuse.sshfs rw 0 0', '/dev/sdb1 /mnt/win fuseblk rw 0 0',
        'pool /mnt/pool fuse.mergerfs rw 0 0', '/dev/sdc1 /mnt/usb vfat rw 0 0', '/dev/sdd1 /mnt/old msdos rw 0 0',
        '//nas/s3 /mnt/smb3 smb3 rw 0 0']) + '\n')
    for name, size, model in (('nvme0n1', 10 ** 12, 'Samsung SSD 980 PRO 1TB'), ('sda', 4 * 10 ** 12, 'WDC WD40EFRX'),
                              ('loop0', 50 * 2 ** 20, '')):
        put(SYS / 'block' / name / 'size', '%d\n' % (size // 512))
        if model:
            put(SYS / 'block' / name / 'device' / 'model', model + '\n')
    for nic, state, speed in (('eno1', 'up', '1000'), ('eno2', 'down', '-1'), ('lo', 'unknown', ''),
                              ('veth1a2b', 'up', '10000')):
        put(SYS / 'class' / 'net' / nic / 'operstate', state + '\n')
        if speed:
            put(SYS / 'class' / 'net' / nic / 'speed', speed + '\n')
    h0 = SYS / 'class' / 'hwmon' / 'hwmon0'
    put(h0 / 'name', 'k10temp\n')
    put(h0 / 'temp1_input', '73000\n')
    put(h0 / 'temp1_label', 'Tctl\n')
    h1 = SYS / 'class' / 'hwmon' / 'hwmon1'
    put(h1 / 'name', 'nvme\n')
    put(h1 / 'temp1_input', '44000\n')
    put(h1 / 'temp1_label', 'Composite\n')
    (h1 / 'device' / 'nvme0n1').mkdir(parents=True, exist_ok=True)
    h2 = SYS / 'class' / 'hwmon' / 'hwmon2'
    put(h2 / 'name', 'acpitz\n')
    put(h2 / 'temp1_input', '41000\n')
    h3 = SYS / 'class' / 'hwmon' / 'hwmon3'
    put(h3 / 'name', 'drivetemp\n')
    put(h3 / 'temp1_input', '36000\n')
    (h3 / 'device' / 'block' / 'sda').mkdir(parents=True, exist_ok=True)
    for n in range(8):
        put(SYS / 'devices' / 'system' / 'cpu' / ('cpu%d' % n) / 'cpufreq' / 'scaling_cur_freq',
            '%d\n' % (1200000 + n * 350000))


class FakeVfs(object):
    def __init__(self, total, used):
        self.f_frsize = 4096
        self.f_blocks = total // 4096
        self.f_bfree = (total - used) // 4096
        self.f_bavail = self.f_bfree


VFS = {'/': FakeVfs(984 * 10 ** 9, 212 * 10 ** 9), '/srv': FakeVfs(36 * 10 ** 11, 31 * 10 ** 11),
       '/boot': FakeVfs(10 ** 9, 312 * 10 ** 6)}
for _m in ('/mnt/nfs', '/mnt/smb', '/mnt/nfs3', '/mnt/ssh', '/mnt/win', '/mnt/pool', '/mnt/usb', '/mnt/old', '/mnt/smb3'):
    VFS[_m] = FakeVfs(10 ** 12, 10 ** 11)                 # there, if it were asked
VFS_HOLD = {'s': 0.0}
VFS_ASKED = []


def fake_statvfs(path):
    VFS_ASKED.append(path)
    if VFS_HOLD['s']:
        time.sleep(VFS_HOLD['s'])                         # a disk that answers slowly
    if path not in VFS:
        raise OSError(2, 'no such mount')
    return VFS[path]


write_static()
write_proc()
READS = []
_real_open = zigmon._perf_open


def counting_open(path):
    READS.append(path)
    return _real_open(path)


zigmon._perf_open = counting_open
zigmon.PERF_PROC, zigmon.PERF_SYS, zigmon.PERF_STATVFS = str(PROC), str(SYS), fake_statvfs

# Every touch of the test's /proc and /sys, by any road - open, listdir,
# scandir, stat, lstat (isdir, islink, realpath), readlink - whoever makes it:
# only the meter knows the way there. (The test writes its files through
# io.open, os.replace and os.mkdir, which are not counted.)
import builtins                                         # noqa: E402
TOUCHED = []
_FAKE = (str(PROC), str(SYS))


def _touch(path):
    try:
        path = os.fspath(path)
    except TypeError:
        return
    if isinstance(path, str) and path.startswith(_FAKE) and threading.current_thread().name != 'test-mover':
        # whether the meter was on at that very moment: the page switching it
        # on is seen by the test's own thread up to a poll later, and a read in
        # that gap was counted as one made while off (5.43)
        TOUCHED.append((time.time(), path, bool(zigmon.CONFIG.get('perf_meter'))))


def _counted(real):
    def one(path, *a, **k):
        _touch(path)
        return real(path, *a, **k)
    return one


builtins.open = _counted(builtins.open)
for _fn in ('listdir', 'scandir', 'stat', 'lstat', 'readlink'):
    setattr(os, _fn, _counted(getattr(os, _fn)))


def touched(since):
    return [p for t, p, _on in TOUCHED if t >= since]

MOVING = {'on': False}


def mover():
    """Numbers that move, every half second, as a busy machine's would."""
    t = 0
    while True:
        time.sleep(0.5)
        if not MOVING['on']:
            continue
        t += 1
        wave = lambda base, amp, ph: max(0.0, base + amp * math.sin(t / 6.0 + ph))   # noqa: E731
        for n in range(8):
            b = int(min(50, wave(12 + n * 4.5, 12, n)))
            COUNT['cpu'][n] += b
            COUNT['idle'][n] += 50 - b
        COUNT['rd']['nvme0n1'] += int(wave(45e6, 40e6, 2))
        COUNT['wr']['nvme0n1'] += int(wave(10e6, 10e6, 3))
        COUNT['io']['nvme0n1'] += int(wave(150, 140, 2))
        COUNT['rd']['sda'] += int(1.1e6)
        COUNT['io']['sda'] += 15
        COUNT['rx']['eno1'] += int(wave(3.5e6, 3e6, 4))
        COUNT['tx']['eno1'] += int(wave(4.5e5, 4e5, 5))
        COUNT['rx']['lo'] += 10 ** 9                       # never counted
        COUNT['rx']['veth1a2b'] += 10 ** 9
        for pid, share in ((1201, 0.9), (1302, 0.4), (812, 0.2), (701, 0.06), (640, 0.015)):
            COUNT['proc'][pid] += int(TICK * 0.5 * share * (0.6 + 0.4 * math.sin(t / 5.0 + pid)))
        write_proc()


threading.Thread(target=mover, daemon=True, name='test-mover').start()


# ---- a Shelly box, for the socket a sensor switches ---------------------------
BOX = {'output': False, 'sets': []}


class Box(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        method, params = body.get('method'), body.get('params') or {}
        if method == 'Switch.Set':
            BOX['sets'].append((time.time(), bool(params.get('on'))))
            out = {'was_on': BOX['output']}
            BOX['output'] = bool(params.get('on'))
        elif method in ('Shelly.GetStatus', 'Switch.GetStatus'):
            out = {'switch:0': {'id': 0, 'output': BOX['output'], 'apower': 12.0, 'voltage': 231.0,
                                'aenergy': {'total': 1.0}}, 'id': 0, 'output': BOX['output'], 'apower': 12.0,
                   'mqtt': {'connected': False}}
        elif method == 'Shelly.GetDeviceInfo':
            out = {'id': 'shellyplug-test', 'model': 'S3PL-00112EU', 'gen': 3, 'ver': '1.7.1'}
        else:
            out = {}
        raw = json.dumps({'id': body.get('id'), 'result': out}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


box = ThreadingHTTPServer(('127.0.0.1', BOX_PORT), Box)
threading.Thread(target=box.serve_forever, daemon=True).start()

# ---- the daemon ----------------------------------------------------------------
zigmon.load_config()
DB = W / 'zigmon.db'
zigmon.CONFIG.update({'db_file': str(DB), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'log_file': '', 'state_dir': str(W / 'state')})
zigmon.CONFIG.pop('perf_meter', None)                    # whatever this machine's file says: the default
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
d.backup_dir = lambda: W / 'backups'
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)
threading.Thread(target=d.rule_worker, name='rules', daemon=True).start()
threading.Thread(target=d.rule_worker, args=(True,), name='rules-presence', daemon=True).start()


def call(path, body=None, session=None):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': '192.168.40.10'}
    if session:
        headers['X-Zigmon-Session'] = session
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                 data=None if body is None else json.dumps(body).encode(),
                                 method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'{}')
        except ValueError:
            return e.code, {}


d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
d.account_add('vik', 'viewer', 'vik pass 1234', must_change=False, quiet=True)


def login(name, password):
    return call('/api/auth/login', {'name': name, 'password': password})[1].get('token') or ''


S_ADMIN, S_OP, S_VIEW = login('owner', 'owner pass 12'), login('jana', 'jana pass 12'), login('vik', 'vik pass 1234')
check(S_ADMIN and S_OP and S_VIEW, 'the three test accounts could not sign in')


PAGE_JS = r'''
const { chromium } = require('playwright');
const fs = require('fs');
const BASE = 'http://127.0.0.1:%PORT%/';
const SHOTS = '%SHOTS%', PKG = '%PKG%';
const out = {errors: []};
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const b = await chromium.launch();
  async function ctxAs(name, pass, opts) {
    const c = await b.newContext(Object.assign({viewport: {width: 1600, height: 1000}}, opts || {}));
    if (name) await c.request.post(BASE + '?api=login', {data: {name: name, password: pass}});
    return c;
  }
  function watch(p) {
    const asked = [];
    p.on('request', r => { const u = r.url(); if (/[?&]api=perf(&|$)/.test(u)) asked.push({at: Date.now(), u: u}); });
    p.on('pageerror', e => { const s = String(e.stack || e); if (/hload|hl[A-Z]|hp[A-Z]|perf/.test(s)) out.errors.push(s.slice(0, 300)); });
    return asked;
  }
  const since = (asked, t) => asked.filter(x => x.at >= t);
  const shown = () => { const h = document.getElementById('hload'); return !!h && !h.hidden && h.querySelectorAll('[data-k]').length > 0; };
  async function headerShot(p, name) {
    const box = await p.locator('header').boundingBox();
    await p.screenshot({path: SHOTS + '/' + name, clip: {x: 0, y: 0, width: p.viewportSize().width, height: Math.ceil(box.y + box.height + 10)}});
  }
  async function panelShot(p, name) {
    const hb = await p.locator('header').boundingBox();
    const pb = await p.locator('#hload-panel').boundingBox();
    const w = p.viewportSize().width;
    await p.screenshot({path: SHOTS + '/' + name, clip: {x: 0, y: 0, width: w, height: Math.min(p.viewportSize().height, Math.ceil(Math.max(hb.y + hb.height, pb.y + pb.height) + 12))}});
  }
  const looks = ['graphs', 'pills', 'line', 'rings', 'off'];

  // ---- off: an administrator's page draws nothing and asks nothing --------
  const admin = await ctxAs('owner', 'owner pass 12');
  let p = await admin.newPage();
  let asked = watch(p);
  await p.goto(BASE + 'index.php');
  await sleep(6000);
  out.off = {asked: asked.length, admin: await p.evaluate(() => isAdmin()),
             hidden: await p.evaluate(() => { const h = document.getElementById('hload'); return !!h && h.hidden && !h.children.length; })};

  // ---- switched on, from its card on About, with that pane's Save --------
  async function meterSwitch(page, on) {
    await page.evaluate(() => { showTab('control'); showControlSection('sys-about'); });
    await page.waitForSelector('#perf-card [data-k="perf_meter"]', {state: 'attached', timeout: 10000});
    await sleep(300);
    if (!out.about) out.about = await page.evaluate(() => {
      const b = document.querySelector('#perf-card [data-k="perf_meter"]');
      return {inAbout: !!b && b.closest('[data-sec]').dataset.sec === 'sys-about',
              shownCard: !!b && b.closest('.card').offsetParent !== null, off: !!b && !b.checked}; });
    if (!fs.existsSync(SHOTS + '/about-switch-1600.png')) await page.locator('#perf-card').screenshot({path: SHOTS + '/about-switch-1600.png'}).catch(() => {});
    const box = await page.$('#perf-card [data-k="perf_meter"]');
    const was = await box.evaluate(e => e.checked);
    if (was !== on) await (await box.evaluateHandle(e => e.closest('label') || e)).asElement().click();
    await page.click('#perf-card .set-save-alt');
    await sleep(300);
    await page.evaluate(() => showTab('overview'));
  }
  await meterSwitch(p, true);
  await p.waitForFunction(shown, null, {timeout: 20000}).catch(() => {});
  out.on = {shown: await p.evaluate(shown), chips: await p.evaluate(() => document.querySelectorAll('#hload [data-k]').length)};
  await sleep(9000);                                     // a few readings for the graphs
  await p.reload();                                      // ...and the two minutes kept, drawn
  await p.waitForFunction(shown, null, {timeout: 20000}).catch(() => {});
  await sleep(3500);

  // ---- the pickers in the account's popup ---------------------------------
  await p.click('#lockpill');
  await p.waitForSelector('#hl-pickers', {timeout: 5000}).catch(() => {});
  out.pickers = await p.evaluate(() => ({
    cards: Array.from(document.querySelectorAll('#hl-pickers .hl-pick')).map(x => x.querySelectorAll('.pal-card').length),
    drawn: Array.from(document.querySelectorAll('#hl-pickers .hl-sw')).filter(x => x.querySelector('.hload, .hl-panel, .hl-tipbox')).length}));
  await p.locator('#zmodal-box').screenshot({path: SHOTS + '/pickers-1600.png'}).catch(() => {});
  out.looks = {};
  for (const look of looks) {
    await p.click('#hl-pickers .hl-pick:not(.hl-pick-p) .pal-card[data-v="' + look + '"]');
    await sleep(400);
    out.looks[look] = await p.evaluate(() => {
      const h = document.getElementById('hload');
      let kept = null; try { kept = JSON.parse(localStorage.getItem('zigmon-perf-look')).hload; } catch (e) {}
      const marks = {'look-graphs': '.hl-g svg', 'look-rings': '.hl-ringbox', 'look-pills': '.hl-bar', 'look-line': '.hl-sep'};
      const sel = Object.keys(marks).filter(k => h.classList.contains(k))[0];
      return {cls: h.className, n: h.hidden ? 0 : h.querySelectorAll('[data-k]').length, hidden: h.hidden, kept: kept,
              marks: sel ? h.querySelectorAll(marks[sel]).length : 0};
    });
  }
  await p.click('#hl-pickers .hl-pick:not(.hl-pick-p) .pal-card[data-v="graphs"]');
  await p.keyboard.press('Escape');
  await p.evaluate(() => closeZModal());
  await sleep(300);
  for (const look of looks.slice(0, 4)) {
    await p.evaluate(l => { hlSavePrefs({hload: l}); HLOAD.look = l; hloadDraw(HLOAD.last); }, look);
    await sleep(200);
    await headerShot(p, 'look-' + look + '-1600.png');
  }
  await p.evaluate(() => { hlSavePrefs({hload: 'graphs'}); HLOAD.look = 'graphs'; hloadDraw(HLOAD.last); });

  // ---- the five styles of the details -------------------------------------
  const want = {tiles: ['.hp-core', 8], table: ['.hp-cores-t tr', 8], map: ['.hp-cell', 8], wide: ['.hp-col', 4]};
  out.panels = {};
  const tOpen = Date.now();
  for (const st of ['tiles', 'table', 'map', 'wide']) {
    await p.evaluate(s => { hlSavePrefs({hpanel: s}); hloadDraw(HLOAD.last); }, st);
    for (const k of (st === 'wide' ? ['cpu'] : ['cpu', 'mem', 'disk', 'net'])) {
      await p.mouse.move(5, 950);
      await sleep(500);
      await p.hover('#hload [data-k="' + k + '"]');
      await p.waitForFunction(() => HLOAD.detail && !document.getElementById('hload-panel').hidden, null, {timeout: 8000}).catch(() => {});
      await sleep(k === 'cpu' ? 3400 : 600);
      if (k === 'cpu') out.panels[st] = await p.evaluate(w => {
        const panel = document.getElementById('hload-panel');
        return {open: !!panel && !panel.hidden, cls: panel ? panel.className : '', marks: panel ? panel.querySelectorAll(w[0]).length : 0, want: w[1]};
      }, want[st]);
      await panelShot(p, 'panel-' + st + '-' + k + '-1600.png');
    }
  }
  await p.mouse.move(5, 950);
  await sleep(800);
  const tShut = Date.now();
  await sleep(7000);
  out.detail = {open: since(asked, tOpen).filter(x => x.at < tShut && /detail=1/.test(x.u)).length,
                after: since(asked, tShut + 400).filter(x => /detail=1/.test(x.u)).length,
                plain: since(asked, tShut + 400).length};
  await p.evaluate(() => { hlSavePrefs({hpanel: 'off'}); hloadDraw(HLOAD.last); });
  await p.hover('#hload [data-k="cpu"]');
  await sleep(900);
  out.panels.off = await p.evaluate(() => {
    const panel = document.getElementById('hload-panel'), c = document.querySelector('#hload [data-k="cpu"]');
    return {open: !!panel && !panel.hidden, title: c.title || c.dataset.said || ''};
  });
  await p.mouse.move(5, 950);
  await p.evaluate(() => { hlSavePrefs({hpanel: 'tiles'}); hloadDraw(HLOAD.last); });

  // ---- nothing at all: no bar, no ring, no dot (plexmon 2.7.2) -------------
  out.zero = await p.evaluate(() => {
    const bad = [];
    const widths = {w0: hlWidth(0), w049: hlWidth(0.49), w05: hlWidth(0.5), w140: hlWidth(140)};
    const keep = [HLOAD.last, HLOAD.detail, HLOAD.hist, HLOAD.open, HLOAD.chip, hlPrefs()];
    const zero = {at: 1, cores: 8, cpu: 0, mem_used: 0, mem_total: 32e9, swap_used: 0, disk_rd: 0, disk_wr: 0,
                  net_rx: 0, net_tx: 0, load: [0, 0, 0], over_s: 3};
    HLOAD.detail = {cores: [0, 1, 2, 3, 4, 5, 6, 7].map(n => ({n: n, busy: 0, mhz: 1200, temp: null})), model: 'x',
      temps: {cpu: [], cores: {}, other: []}, disks: [{name: 'sda', size: 4e12, model: 'm', rd: 0, wr: 0, util: 0, temp: null}],
      filesystems: [{mount: '/', kind: 'ext4', total: 1e12, used: 0}],
      nics: [{name: 'eno1', state: 'up', speed: 1000, rx: 0, tx: 0, rx_all: 0, tx_all: 0}],
      top_cpu: [{name: 'php-fpm', pid: 9, cpu: 0}, {name: 'idle', pid: 8, cpu: 0.3}],
      top_mem: [{name: 'tiny', pid: 9, rss: 0}], uptime: 0, procs: 2,
      mem: {total: 32e9, available: 32e9, cached: 0, buffers: 0, shared: 0, swap_total: 0, swap_free: 0}};
    let combos = 0;
    const look = () => {
      const panelShown = !document.getElementById('hload-panel').hidden;
      document.querySelectorAll('.hl-bar > span, .hp-bar > span').forEach(x => { if ((x.closest('#hload') || (panelShown && x.closest('#hload-panel'))) && x.style.width !== '0%') bad.push(x.parentNode.className + ' / ' + ((x.closest('tr,.hp-core,.hp-card,.hp-util,.hp-sec,.hl') || {}).className || '') + ' ' + x.style.width); });
      document.querySelectorAll('#hload .hl-ring-fg' + (panelShown ? ', #hload-panel .hp-ring-fg' : '')).forEach(x => { if (!/^0\.0 /.test(x.getAttribute('stroke-dasharray'))) bad.push('ring ' + x.getAttribute('stroke-dasharray')); });
    };
    try {
      for (const l of ['graphs', 'pills', 'line', 'rings']) {
        HLOAD.open = null; hlSavePrefs({hload: l}); HLOAD.look = l; hloadDraw(zero); look();
        for (const st of ['tiles', 'table', 'map', 'wide']) for (const k of ['cpu', 'mem', 'disk', 'net']) {
          hlSavePrefs({hpanel: st}); HLOAD.open = k; HLOAD.last = zero;
          document.getElementById('hload-panel').hidden = false; hloadPanelDraw(); look(); combos++;
          if (st === 'map' && k === 'cpu') widths.ringStroke = getComputedStyle(document.querySelector('#hload-panel .hp-ring-fg')).stroke;
        }
      }
    } finally {
      HLOAD.last = keep[0]; HLOAD.detail = keep[1]; HLOAD.hist = keep[2]; HLOAD.open = null; hloadPanelClose();
      localStorage.setItem('zigmon-perf-look', JSON.stringify(keep[5])); HLOAD.look = hlLook(); if (HLOAD.last) hloadDraw(HLOAD.last);
    }
    return {bad: bad.slice(0, 8), combos: combos, widths: widths};
  });

  // ---- hidden, and paused: nothing asked ----------------------------------
  await p.evaluate(() => {
    Object.defineProperty(document, 'hidden', {configurable: true, get: () => true});
    Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'});
    document.dispatchEvent(new Event('visibilitychange'));
  });
  let t = Date.now() + 300;
  await sleep(7500);
  const hiddenAsked = since(asked, t).length;
  await p.evaluate(() => {
    delete document.hidden; delete document.visibilityState;
    document.dispatchEvent(new Event('visibilitychange'));
  });
  t = Date.now();
  await sleep(1500);
  out.hidden = {asked: hiddenAsked, back: since(asked, t).length,
                state: await p.evaluate(() => ({timer: HLOAD.timer, busy: HLOAD.busy, hidden: document.hidden, paused: STATE.paused, wanted: perfWanted(), look: HLOAD.look}))};
  await p.click('#updated');
  const paused = await p.evaluate(() => !!STATE.paused);
  t = Date.now() + 300;
  await sleep(7500);
  out.paused = {asked: paused ? since(asked, t).length : -1};
  await p.click('#updated');

  // ---- F5: the graphs come back with the points they had -------------------
  let historyLen = -1;
  p.on('response', async r => { if (/api=perf.*history=1/.test(r.url())) { try { historyLen = ((await r.json()).history || []).length; } catch (e) {} } });
  await p.reload();
  const tLoad = Date.now();
  let points = 0;
  await p.waitForFunction(() => { const pl = document.querySelector('#hload .hl-cpu polyline');
    return pl && pl.getAttribute('points').trim().split(/\s+/).length > 1; }, null, {timeout: 1000, polling: 20}).catch(() => {});
  const ms = Date.now() - tLoad;
  points = await p.evaluate(() => { const pl = document.querySelector('#hload .hl-cpu polyline'); return pl ? pl.getAttribute('points').trim().split(/\s+/).length : 0; });
  out.f5 = {points: points, ms: ms, history: historyLen};
  await headerShot(p, 'after-f5-1600.png');
  // ...and off again with the switch on About: gone at once, nothing asked, no reload
  const before = await p.evaluate(() => (window.__pageId = window.__pageId || Math.random()));
  await meterSwitch(p, false);
  await p.waitForFunction(() => { const h = document.getElementById('hload'); return h.hidden && !h.children.length; }, null, {timeout: 6000}).catch(() => {});
  t = Date.now() + 500;
  await sleep(7000);
  out.aboutOff = {hidden: await p.evaluate(() => { const h = document.getElementById('hload'); return h.hidden && !h.children.length; }),
                  asked: since(asked, t).length, same: (await p.evaluate(() => window.__pageId)) === before};
  await meterSwitch(p, true);
  await p.waitForFunction(shown, null, {timeout: 15000}).catch(() => {});
  out.aboutOn = {shown: await p.evaluate(shown), same: (await p.evaluate(() => window.__pageId)) === before};
  await p.close();

  // ---- a viewer's page: the meter too (5.43.1), without the processes -------
  const viewer = await ctxAs('vik', 'vik pass 1234');
  p = await viewer.newPage();
  asked = watch(p);
  await p.goto(BASE + 'index.php');
  await p.waitForFunction(shown, null, {timeout: 20000}).catch(() => {});
  await sleep(1500);
  out.viewer = {asked: asked.length, shown: await p.evaluate(shown)};
  await viewer.close();

  // ---- a phone, 420 px wide -----------------------------------------------
  const phone = await ctxAs('owner', 'owner pass 12', {viewport: {width: 420, height: 900}, isMobile: true, hasTouch: true});
  p = await phone.newPage();
  asked = watch(p);
  await p.goto(BASE + 'index.php');
  await p.waitForFunction(shown, null, {timeout: 20000}).catch(() => {});
  await sleep(4000);
  out.phone = await p.evaluate(() => ({wide: document.documentElement.scrollWidth, shown: !!document.getElementById('hload') && !document.getElementById('hload').hidden,
    visible: Array.from(document.querySelectorAll('#hload [data-k]')).filter(x => x.offsetParent !== null && getComputedStyle(x).display !== 'none').map(x => x.dataset.k)}));
  for (const look of looks.slice(0, 4)) {
    await p.evaluate(l => { hlSavePrefs({hload: l}); HLOAD.look = l; hloadDraw(HLOAD.last); }, look);
    await sleep(200);
    const w = await p.evaluate(() => document.documentElement.scrollWidth);
    if (w > out.phone.wide) out.phone.wide = w;
    await headerShot(p, 'look-' + look + '-420.png');
  }
  await p.evaluate(() => { hlSavePrefs({hload: 'graphs'}); HLOAD.look = 'graphs'; hloadDraw(HLOAD.last); });
  await p.tap('#hload [data-k="cpu"]');
  await p.waitForFunction(() => HLOAD.detail && !document.getElementById('hload-panel').hidden, null, {timeout: 8000}).catch(() => {});
  await sleep(3400);
  out.phone.tap = await p.evaluate(() => !document.getElementById('hload-panel').hidden);
  out.phone.panelRight = await p.evaluate(() => document.getElementById('hload-panel').getBoundingClientRect().right);
  await p.screenshot({path: SHOTS + '/phone-tap-420.png'});
  for (const st of ['table', 'map', 'wide']) {
    await p.evaluate(s => { hlSavePrefs({hpanel: s}); hloadPanelDraw(); hloadPanelPlace(); }, st);
    await sleep(300);
    const r = await p.evaluate(() => document.getElementById('hload-panel').getBoundingClientRect().right);
    if (r > out.phone.panelRight) out.phone.panelRight = r;
    await p.screenshot({path: SHOTS + '/phone-' + st + '-420.png'});
  }
  await p.tap('header h1');
  await sleep(500);
  out.phone.shut = await p.evaluate(() => document.getElementById('hload-panel').hidden);
  await phone.close();
  await admin.close();

  // ---- side by side with ai's own pictures ---------------------------------
  if (PKG) {
    const pairs = [];
    for (const l of looks.slice(0, 4)) pairs.push(['cmp-look-' + l + '.png', ['look-' + l + '-1600.png', 'look-' + l + '-420.png'], 'look-' + l + '.png']);
    for (const st of ['tiles', 'table', 'map']) for (const k of ['cpu', 'mem', 'disk', 'net'])
      pairs.push(['cmp-panel-' + st + '-' + k + '.png', ['panel-' + st + '-' + k + '-1600.png'], 'panel-' + st + '-' + k + '.png']);
    pairs.push(['cmp-panel-wide-cpu.png', ['panel-wide-cpu-1600.png'], 'panel-wide-cpu.png']);
    pairs.push(['cmp-pickers.png', ['pickers-1600.png'], 'pickers.png']);
    pairs.push(['cmp-phone-tap.png', ['phone-tap-420.png'], 'ipad-tap.png']);
    const data = f => 'data:image/png;base64,' + fs.readFileSync(f).toString('base64');
    const cp = await (await b.newContext({viewport: {width: 1700, height: 400}})).newPage();
    for (const [name, mine, theirs] of pairs) {
      const have = mine.filter(m => fs.existsSync(SHOTS + '/' + m));
      if (!have.length || !fs.existsSync(PKG + '/' + theirs)) continue;
      await cp.setContent('<body style="margin:0;background:#05080c;color:#8b94a3;font:14px sans-serif;display:flex;gap:16px;padding:12px;align-items:flex-start;width:max-content">'
        + '<div><div>zigmon 5.43</div>' + have.map(m => '<img style="display:block;max-width:1600px;margin:6px 0 12px" src="' + data(SHOTS + '/' + m) + '">').join('') + '</div>'
        + '<div><div>ai (the package: ' + theirs + ')</div><img style="display:block;max-width:1600px;margin-top:6px" src="' + data(PKG + '/' + theirs) + '"></div></body>');
      await cp.screenshot({path: SHOTS + '/' + name, fullPage: true});
    }
  }
  await b.close();
  console.log(JSON.stringify(out));
})().catch(e => { out.errors.push(String(e.stack || e)); out.fatal = true; console.log(JSON.stringify(out)); process.exit(0); });
'''


def perf_threads():
    return [t.name for t in threading.enumerate() if re.search(r'perf|load|meter', t.name, re.I)]


try:
    # ---- off by default --------------------------------------------------------
    check(zigmon.DEFAULTS.get('perf_meter') == 0, 'the meter is not off by default: %r'
          % zigmon.DEFAULTS.get('perf_meter'))
    check(zigmon.Daemon.TUNABLE.get('perf_meter') == (0, 1), 'perf_meter is not a setting the page can change')
    rc = d.runtime_config().get('perf_meter') or {}
    check(rc.get('kind') == 'switch' and not rc.get('value'), 'perf_meter is not an off switch: %r' % rc)
    page = (HERE / 'web' / 'index.php').read_text()
    _where = re.search(r"var SETTINGS_WHERE = \{(.*?)\n\};", page, re.S).group(1)
    _group = re.search(r"\['([^']+)', \[\s*\['perf_meter'", page)
    check(_group and ("'%s': 'sys-about'" % _group.group(1)) in _where and 'id="set-host-sys-about"' in page,
          'the switch is not drawn on its card on About')
    READS[:] = []
    _off_from = time.time()
    st, out = call('/api/perf', session=S_ADMIN)
    st2, out2 = call('/api/perf?detail=1&history=1', session=S_ADMIN)
    check(st == 404 and st2 == 404 and set(out) == {'ok', 'error'} and 'off' in out.get('error', ''),
          'off, /api/perf answered %s %r' % (st, out))
    for _ in range(3):                                 # several of the page's intervals, asking each
        time.sleep(3.0)
        call('/api/perf', session=S_ADMIN)
    check(not READS and not touched(_off_from) and not VFS_ASKED,
          'off, the meter read %d file(s), touched %d path(s) and asked statvfs %d time(s): %s'
          % (len(READS), len(touched(_off_from)), len(VFS_ASKED), (READS + touched(_off_from))[:3]))
    check(not zigmon.PERF_RING and not zigmon.PERF_LAST['raw'], 'off, the meter keeps something')
    check(not perf_threads(), 'off, there is a thread for the meter: %s' % perf_threads())
    print('off by default: no thread, nothing read, /api/perf says only that it is off')

    # ---- on: an administrator's ----------------------------------------------------
    st, _ = call('/api/config', dict(perf_meter=1, session=S_ADMIN))
    check(st == 200 and zigmon.CONFIG.get('perf_meter') == 1, 'the meter could not be switched on (%s)' % st)
    # whoever may see the dashboard (5.43.1): the view's own rule, as /api/status
    zigmon.CONFIG['public_view'] = False
    st, out = call('/api/perf')
    check(st == 403 and 'cpu' not in out and 'mem_total' not in out,
          'the view not public, nobody signed in was answered %s %r' % (st, str(out)[:120]))
    for who, s in (('an operator', S_OP), ('a viewer', S_VIEW)):
        st, out = call('/api/perf?detail=1', session=s)
        x = out.get('detail') or {}
        check(st == 200 and out.get('mem_total') and x.get('cores') and x.get('disks') is not None
              and not set(x) & {'top_cpu', 'top_mem', 'procs', 'filesystems'},
              '%s was answered %s %r' % (who, st, sorted(x) if x else str(out)[:120]))
    zigmon.CONFIG['public_view'] = True
    st, out = call('/api/perf?detail=1')
    x = out.get('detail') or {}
    check(st == 200 and out.get('mem_total') and not set(x) & {'top_cpu', 'top_mem', 'procs', 'filesystems'},
          'with the view public, nobody was answered %s %r' % (st, sorted(x) if x else str(out)[:120]))
    st, out = call('/api/perf?detail=1', session=S_ADMIN)
    x = out.get('detail') or {}
    check(st == 200 and set(x) >= {'top_cpu', 'top_mem', 'procs', 'filesystems'},
          'an administrator was not answered the processes and the filesystems: %r' % sorted(x))
    print('on: the numbers for whoever may see the dashboard (nobody only with the view public), '
          'the processes and the filesystems an administrator\'s only')
    # the numbers below are the test's own readings, one after another: the
    # watcher the asks above started is ended first
    zigmon.perf_forget()
    _w = zigmon.PERF_WATCH['thread']
    if _w is not None:
        _w.join(10)

    # the numbers, against the counters of the test's own /proc
    for n in range(8):
        COUNT['cpu'][n], COUNT['idle'][n] = 1000, 9000
    write_proc()
    first = zigmon.perf_read()
    check('cpu' not in first, 'the first reading had a rate already: %r' % first)
    check(first.get('mem_total') == 32 * GiB and first.get('mem_used') == 10 * GiB,
          'memory: %r of %r (MemTotal - MemAvailable)' % (first.get('mem_used'), first.get('mem_total')))
    check(first.get('load') == [3.92, 3.1, 2.71], 'the load: %r' % first.get('load'))
    for n in range(8):
        COUNT['cpu'][n] += 300                         # 300 of 400 busy: 75 %
        COUNT['idle'][n] += 100
    COUNT['rd']['nvme0n1'] += 4 * 2 ** 20
    COUNT['wr']['sda'] += 2 ** 20
    COUNT['rx']['eno1'] += 3 * 10 ** 6
    COUNT['tx']['eno1'] += 10 ** 6
    COUNT['rx']['lo'] += 10 ** 10
    COUNT['rx']['veth1a2b'] += 10 ** 10
    write_proc()
    time.sleep(1.2)
    s2 = zigmon.perf_read()
    dt = s2.get('over_s') or 1
    check(s2.get('cpu') == 75.0, 'the processor: %r %% (75 wanted)' % s2.get('cpu'))
    check(0 <= (s2.get('cpu') or -1) <= 100, 'the processor out of 0-100: %r' % s2.get('cpu'))

    def near(got, want):
        return got is not None and abs(got - want) <= want * 0.12 + 1

    check(near(s2.get('disk_rd'), 4 * 2 ** 20 / dt) and near(s2.get('disk_wr'), 2 ** 20 / dt),
          'the disks: %r / %r B/s over %s s (partitions and loop devices left out)'
          % (s2.get('disk_rd'), s2.get('disk_wr'), dt))
    check(near(s2.get('net_rx'), 3e6 / dt) and near(s2.get('net_tx'), 1e6 / dt),
          'the network: %r / %r B/s (the loopback and the containers\' pairs left out)'
          % (s2.get('net_rx'), s2.get('net_tx')))
    print('the summary: cpu %s %%, memory %d of %d GiB, disks and network rates as the counters moved'
          % (s2.get('cpu'), s2['mem_used'] // GiB, s2['mem_total'] // GiB))
    # an ask reads nothing itself (5.43.1): the watcher's newest reading
    _seen = [call('/api/perf', session=S_ADMIN)[1].get('at') for _ in range(5)]
    check(len(set(_seen)) == 1 and zigmon.PERF_WATCH['thread'] is not None,
          'five asks in a row were %d readings: %r' % (len(set(_seen)), _seen))

    call('/api/perf?detail=1', session=S_ADMIN)        # the panel's first look
    for n in range(8):
        COUNT['cpu'][n] += 100 + 100 * n // 2
        COUNT['idle'][n] += 500 - 100 * n // 2
    write_proc()
    time.sleep(1.2)
    st, dd = call('/api/perf?detail=1', session=S_ADMIN)
    x = dd.get('detail') or {}
    check(st == 200 and len(x.get('cores') or []) == 8 and all(c.get('busy') is not None for c in x['cores']),
          'the cores: %r' % (x.get('cores') or [])[:2])
    check([c.get('mhz') for c in x.get('cores') or []][:2] == [1200, 1550], 'the frequencies: %r'
          % [c.get('mhz') for c in x.get('cores') or []])
    check((x.get('temps') or {}).get('cpu') == [['Tctl', 73.0]] and (x.get('temps') or {}).get('other') == [['acpitz', 41.0]],
          'the sensors: %r' % x.get('temps'))
    disks = {k['name']: k for k in x.get('disks') or []}
    check(set(disks) == {'nvme0n1', 'sda', 'loop0'} or set(disks) == {'nvme0n1', 'sda'},
          'the disks one by one: %s' % sorted(disks))
    check(disks.get('nvme0n1', {}).get('temp') == 44.0 and disks.get('sda', {}).get('temp') == 36.0
          and disks.get('nvme0n1', {}).get('model') == 'Samsung SSD 980 PRO 1TB',
          'a disk\'s temperature and model: %r' % disks.get('nvme0n1'))
    fss = [f['mount'] for f in x.get('filesystems') or []]
    check(fss == ['/', '/boot', '/srv'], 'the filesystems: %r (no proc, tmpfs, overlay, nor one twice)' % fss)
    check([n['name'] for n in x.get('nics') or []] == ['eno1', 'eno2'], 'the cards: %r'
          % [n['name'] for n in x.get('nics') or []])
    check((x.get('mem') or {}).get('available') == 22 * GiB and x.get('model', '').startswith('AMD Ryzen'),
          'the memory or the model: %r %r' % (x.get('mem'), x.get('model')))
    check([p['name'] for p in x.get('top_mem') or []][:2] == ['node', 'zigmon'], 'the processes by memory: %r'
          % [p['name'] for p in x.get('top_mem') or []])
    check(not set(VFS_ASKED) - {'/', '/boot', '/srv'}, 'statvfs asked of %s - a share, FUSE or FAT'
          % sorted(set(VFS_ASKED) - {'/', '/boot', '/srv'}))
    check(all(c.get('temp') is None for c in x.get('cores') or []),
          'AMD\'s k10temp says only the package\'s, and a core was given one: %r' % x.get('cores'))
    print('the details: 8 cores with frequencies, sensors, disks with models and temperatures (drivetemp '
          'too), filesystems (statvfs of ext4 and xfs only, never nfs, cifs, smb3, FUSE nor FAT), cards, processes')

    # ---- each logical processor its core's temperature, by topology ------------------
    def topo_sys(core_ids, labels, pkg_dirs=('coretemp.0',)):
        top = W / ('topo-%s' % '-'.join(map(str, core_ids)))
        mon = top / 'class' / 'hwmon' / 'hwmon1'
        put(mon / 'name', 'coretemp\n')
        real = top / 'devices' / 'platform' / pkg_dirs[0]
        real.mkdir(parents=True, exist_ok=True)
        os.symlink(str(real), str(mon / 'device'))
        put(mon / 'temp1_input', '60000\n')
        put(mon / 'temp1_label', 'Package id 0\n')
        for i, (lab, t) in enumerate(labels):
            put(mon / ('temp%d_input' % (i + 2)), '%d\n' % (t * 1000))
            put(mon / ('temp%d_label' % (i + 2)), lab + '\n')
        for n, cid in enumerate(core_ids):
            put(top / 'devices' / 'system' / 'cpu' / ('cpu%d' % n) / 'topology' / 'core_id', '%d\n' % cid)
            put(top / 'devices' / 'system' / 'cpu' / ('cpu%d' % n) / 'topology' / 'physical_package_id', '0\n')
        return top

    _was_sys = zigmon.PERF_SYS
    for ids, labels, want in (([0, 1, 0, 1], [('Core 0', 48), ('Core 1', 44)], [48.0, 44.0, 48.0, 44.0]),
                              ([0, 4, 0, 4], [('Core 0', 51), ('Core 4', 57)], [51.0, 57.0, 51.0, 57.0])):
        zigmon.PERF_SYS = str(topo_sys(ids, labels))
        _t = zigmon.perf_temps()
        got = [zigmon.perf_core_temp(n, _t) for n in range(4)]
        check(got == want and _t['cpu'] == [['Package id 0', 60.0]],
              'core ids %s: the four logical processors\' temperatures %r (%r wanted)' % (ids, got, want))
    zigmon.PERF_SYS = _was_sys
    print('each logical processor its physical core\'s temperature, by topology (hyperthreads, cores 0 and 4)')
    check(perf_threads() == ['perf-watch'], 'on, the meter has not its one thread: %s' % perf_threads())

    # ---- the last two minutes are kept ----------------------------------------------
    MOVING['on'] = True
    zigmon.PERF_RING.clear()
    _every = zigmon.PERF_SAMPLE_S
    zigmon.PERF_SAMPLE_S = 2.6                         # the watcher's readings, closer for the test
    for _ in range(5):
        call('/api/perf', session=S_ADMIN)
        time.sleep(2.7)
    zigmon.PERF_SAMPLE_S = _every
    st, h = call('/api/perf?history=1', session=S_ADMIN)
    hist = h.get('history') or []
    check(len(hist) >= 4 and all(set(e) >= {'at', 'cpu', 'mem', 'disk', 'net'} for e in hist),
          'the history kept %d reading(s): %r' % (len(hist), hist[:1]))
    check(all(b['at'] - a['at'] >= zigmon.PERF_STEP_S - 0.01 for a, b in zip(hist, hist[1:])),
          'the history kept readings closer than %s s apart' % zigmon.PERF_STEP_S)
    check(zigmon.PERF_RING.maxlen == 24, 'the history is not capped at the 24 a graph draws')
    print('the history: %d readings kept for a page loaded again, at most 24' % len(hist))

    # ---- off again: nothing kept, nothing read --------------------------------------
    check(touched(_off_from) and READS, 'on, the meter read nothing')
    MOVING['on'] = False
    d.save_config_overrides({'perf_meter': 0})
    check(not zigmon.PERF_RING and not zigmon.PERF_LAST['raw'] and not zigmon.PERF_DETAIL['raw'],
          'switched off, the history and the last readings were still kept')
    READS[:] = []
    VFS_ASKED[:] = []
    _off_again = time.time()
    st, out = call('/api/perf?history=1', session=S_ADMIN)
    time.sleep(3.5)                                    # the watcher sees it is off
    call('/api/perf?detail=1', session=S_ADMIN)
    time.sleep(1.5)
    check(st == 404 and not READS and not touched(_off_again) and not VFS_ASKED and not zigmon.PERF_RING
          and not perf_threads(), 'switched off again: %s, %d read(s), %d touched, %d kept, threads %s'
          % (st, len(READS), len(touched(_off_again)), len(zigmon.PERF_RING), perf_threads()))
    d.save_config_overrides({'perf_meter': 1})
    MOVING['on'] = True

    # ---- the socket a sensor switches does not wait for the meter -------------------
    entry = {'name': 'Light-Test', 'host': '127.0.0.1:%d' % BOX_PORT, 'switch_id': 0, 'kind': 'plug',
             'host_state': 'enabled'}
    d.store.set_meta('managed', json.dumps({'plugs': [entry], 'sensors': []}))
    d.reload_devices()
    d.store.upsert_device({'id': 'zigbee:PIR-Test', 'name': 'PIR-Test', 'source': 'zigbee', 'kind': 'sensor',
                           'exposes': {'occupancy': {}}})
    d.names['PIR-Test'] = 'zigbee:PIR-Test'
    d.store.set_meta('rules', json.dumps([
        {'id': 'p-on', 'device': 'zigbee:PIR-Test', 'key': 'occupancy', 'op': '==', 'value': 1,
         'plug': 'Light-Test', 'do': 'on', 'enabled': True, 'cooldown_s': 0},
        {'id': 'p-off', 'device': 'zigbee:PIR-Test', 'key': 'occupancy', 'op': '==', 'value': 0,
         'plug': 'Light-Test', 'do': 'off', 'enabled': True, 'cooldown_s': 0}]))

    def light_after(report, limit=5.0):
        BOX['sets'] = []
        t0 = time.time()
        d.handle_zigbee('PIR-Test', json.dumps(report).encode())
        while not BOX['sets'] and time.time() - t0 < limit:
            time.sleep(0.001)
        return (BOX['sets'][0][0] - t0) * 1000 if BOX['sets'] else None

    def presses(n=12):
        took = []
        for _ in range(n):
            light_after({'occupancy': False})
            time.sleep(0.15)
            t = light_after({'occupancy': True})
            took.append(t if t is not None else 9999)
            time.sleep(0.15)
        return statistics.median(took), max(took)

    presses(3)                                          # warmed up
    calm = presses()
    # the meter flat out beside it: the real /proc and /sys, every process,
    # no reading shared - far more than any number of pages could ask
    flat = {'on': True, 'n': 0}
    zigmon.PERF_PROC, zigmon.PERF_SYS, zigmon.PERF_STATVFS = '/proc', '/sys', os.statvfs
    zigmon._perf_open = _real_open
    share = zigmon.PERF_SHARE_S
    zigmon.PERF_SHARE_S = 0.0

    def flat_out():
        while flat['on']:
            zigmon.perf_api(detail=True, history=True)
            flat['n'] += 1
    loader = threading.Thread(target=flat_out, daemon=True)
    loader.start()
    time.sleep(0.3)
    busy = presses()
    flat['on'] = False
    loader.join(10)
    zigmon.PERF_SHARE_S = share
    check(flat['n'] > 20, 'the meter was read only %d times beside the presses' % flat['n'])
    check(busy[0] < max(150.0, calm[0] * 2 + 40), 'with the meter reading flat out, a sensor\'s light took %.0f ms '
          '(median; %.0f ms without it)' % (busy[0], calm[0]))
    print('a sensor\'s light: %.1f ms (median) alone, %.1f ms with the meter read %d times beside it'
          % (calm[0], busy[0], flat['n']))
    # ...and a reading held up half way, PERF_LOCK held: the socket does not wait
    zigmon.PERF_PROC, zigmon.PERF_SYS, zigmon.PERF_STATVFS = str(PROC), str(SYS), fake_statvfs
    zigmon._perf_open = counting_open
    zigmon.perf_forget()                               # what the real /proc said is not the test's
    VFS_HOLD['s'] = 2.5
    VFS_ASKED[:] = []
    holder = threading.Thread(target=lambda: zigmon.perf_detail(), daemon=True)
    zigmon.perf_load()                                 # the watcher running again (its first wait is its own)
    holder.start()
    time.sleep(0.9)                                    # past its first look's wait, into the statvfs
    check(holder.is_alive(), 'the reading held up was over before it could be looked at')
    _t0 = time.time()
    _quick = zigmon.perf_load()
    _quick_ms = (time.time() - _t0) * 1000
    check(not zigmon.PERF_LOCK.locked() and _quick_ms < 300 and VFS_ASKED,
          'a statvfs held up the meter\'s lock: another ask waited %.0f ms' % _quick_ms)
    held = presses(4)
    VFS_HOLD['s'] = 0.0
    holder.join(10)
    check(held[1] < 150, 'with a reading of the meter held up, a sensor\'s light took up to %.0f ms' % held[1])
    print('with a statvfs held up 2.5 s: the light in %.1f ms at the most, another ask of the meter in %.0f ms '
          '(no lock held over it)' % (held[1], _quick_ms))

    # ---- through the relay: index.php, as php-fpm runs it ------------------------
    shutil.copytree(str(HERE / 'web'), str(W / 'web'))
    _api_php = (W / 'web' / 'zigmon-api.php').read_text()
    _api_php = _api_php.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
    _api_php = _api_php.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';",
                                "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
    (W / 'web' / 'zigmon-api.php').write_text(_api_php)
    php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, str(W / 'web' / 'index.php')], cwd=str(W / 'web'),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                           env=dict(os.environ, PHP_CLI_SERVER_WORKERS='6'))
    PROCS.append(php)
    for _ in range(50):
        try:
            socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)

    def relay_as(name=None, password=None):
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

        def go(what, body=None):
            req = urllib.request.Request('http://127.0.0.1:%d/?api=%s' % (PHP_PORT, what),
                                         headers={'Content-Type': 'application/json'},
                                         data=None if body is None else json.dumps(body).encode())
            try:
                with opener.open(req, timeout=30) as r:
                    return r.status, json.loads(r.read() or b'{}')
            except urllib.error.HTTPError as e:
                try:
                    return e.code, json.loads(e.read() or b'{}')
                except ValueError:
                    return e.code, {}
        if name:
            go('login', {'name': name, 'password': password})
        return go

    _nobody, _admin, _op = relay_as(), relay_as('owner', 'owner pass 12'), relay_as('jana', 'jana pass 12')
    zigmon.CONFIG['public_view'] = False
    st, out = _nobody('perf')
    check(st == 403 and 'cpu' not in out, 'through the relay, the view not public, nobody was answered %s' % st)
    zigmon.CONFIG['public_view'] = True
    st, out = _op('perf&detail=1')
    check(st == 200 and 'mem_total' in out and 'cores' in (out.get('detail') or {})
          and not set(out.get('detail') or {}) & {'top_cpu', 'top_mem', 'procs', 'filesystems'},
          'through the relay, an operator was answered %s %r' % (st, sorted(out.get('detail') or {})))
    _admin('perf')                                    # a first reading, for the rates of the next
    time.sleep(1.2)
    st, out = _admin('perf&detail=1&history=1&what=else')
    check(st == 200 and 'cpu' in out and len((out.get('detail') or {}).get('cores') or []) == 8
          and isinstance(out.get('history'), list),
          'through the relay, an administrator was answered %s %r' % (st, {k: (v if k != 'detail' else sorted(v)) for k, v in out.items()}))
    st, _ = _admin('config-save', {'perf_meter': 0, 'pin': ''})
    st2, out = _admin('perf')
    check(st == 200 and st2 == 404 and 'cpu' not in out,
          'switched off through the relay (%s), /api/perf answered %s' % (st, st2))
    print('through the relay: the numbers for whoever may see the dashboard, the processes and the filesystems '
          'an administrator\'s, the details and the history on asking, nothing while off')

    # ---- the page, in Chromium ---------------------------------------------------
    root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
    if not (Path(root) / 'playwright').exists():
        print('  SKIPPED the page: no Playwright here')
    else:
        (W / 'shots').mkdir()
        BROWSER = {}

        def two_minutes_on():
            """The meter as it is after two minutes on: the moment the page
            switches it on, the history holds 39 readings, as a page shown all
            that while would have left (the pictures then look as ai's do)."""
            while zigmon.CONFIG.get('perf_meter'):
                time.sleep(0.02)
            while not zigmon.CONFIG.get('perf_meter'):
                time.sleep(0.02)
            BROWSER['on_at'] = now = time.time()
            with zigmon.PERF_LOCK:
                zigmon.PERF_RING.clear()
                for i in range(39):
                    zigmon.PERF_RING.append({'at': round(now - (39 - i) * 3.0, 3),
                                             'cpu': round(48 + 28 * math.sin(i / 4.0), 1), 'mem': 31.2 + i * 0.01,
                                             'disk': int((1 + math.sin(i / 4.0 + 1)) * 5e7),
                                             'net': int((1 + math.sin(i / 4.0 + 2)) * 4e6)})
        threading.Thread(target=two_minutes_on, daemon=True).start()
        (W / 'run.js').write_text(PAGE_JS.replace('%PORT%', str(PHP_PORT)).replace('%SHOTS%', str(W / 'shots'))
                                  .replace('%PKG%', PKG_IMG))
        BROWSER['from'] = time.time()
        got = subprocess.run(['node', str(W / 'run.js')], capture_output=True, text=True, timeout=900,
                             stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=root))
        lines = [x for x in got.stdout.splitlines() if x.startswith('{')]
        if not check(lines, 'the page did not run: %s %s' % (got.stdout[-600:], got.stderr[-1500:])):
            raise SystemExit(1)
        r = json.loads(lines[-1])
        if not check(not r.get('fatal'), 'the page script stopped: %s' % str(r)[:3000]):
            raise SystemExit(1)
        check(not r.get('errors'), 'the page threw: %r' % r.get('errors'))
        check(r['off']['asked'] == 0 and r['off']['hidden'],
              'off, the page asked %d time(s) or drew the meter (%r)' % (r['off']['asked'], r['off']))
        check(r['viewer']['asked'] >= 1 and r['viewer']['shown'],
              'a viewer\'s page has no meter (5.43.1): %r' % r['viewer'])
        check(r['on']['shown'] and r['on']['chips'] == 4, 'switched on, the meter was not drawn: %r' % r['on'])
        for look, seen in sorted(r['looks'].items()):
            check(seen['cls'].startswith('hload look-' + look if look != 'off' else 'hload')
                  and seen['n'] == (0 if look == 'off' else 4) and seen['hidden'] == (look == 'off')
                  and seen['kept'] == look, 'the look %s: %r' % (look, seen))
        check(r['looks']['graphs']['marks'] == 4 and r['looks']['rings']['marks'] == 2
              and r['looks']['pills']['marks'] == 2 and r['looks']['line']['marks'] == 3,
              'the graphs, rings, bars and dots: %r' % {k: v['marks'] for k, v in r['looks'].items()})
        check(r['pickers']['cards'] == [5, 5] and r['pickers']['drawn'] >= 8,
              'the pickers in the account\'s popup: %r' % r['pickers'])
        for style, seen in sorted(r['panels'].items()):
            if style == 'off':
                check(not seen['open'] and 'The processor' in (seen['title'] or ''),
                      'no details: the panel opened or there is no tip (%r)' % seen)
                continue
            check(seen['open'] and seen['cls'].startswith('hl-panel hp-' + style) and seen['marks'] >= seen['want'],
                  'the details as %s: %r' % (style, seen))
        check(r['detail']['open'] >= 1 and r['detail']['after'] == 0 and r['detail']['plain'] >= 1,
              'the details were asked for after the panel shut, or never: %r' % r['detail'])
        check(r['about']['inAbout'] and r['about']['shownCard'] and r['about']['off'],
              'the switch is not on the About pane, or not off: %r' % r['about'])
        check(r['aboutOff']['hidden'] and r['aboutOff']['asked'] == 0 and r['aboutOff']['same']
              and r['aboutOn']['shown'] and r['aboutOn']['same'],
              'switched off and on again on About, without a reload: %r %r' % (r['aboutOff'], r['aboutOn']))
        z = r['zero']
        check(not z['bad'] and z['combos'] == 64, 'with nothing at all, %d look and panel combinations drew: %r'
              % (z['combos'], z['bad']))
        check([z['widths'][k] for k in ('w0', 'w049', 'w05', 'w140')] == [0, 0, 1, 100],
              'hlWidth(0, 0.49, 0.5, 140): %r' % z['widths'])
        check(z['widths'].get('ringStroke') in ('transparent', 'rgba(0, 0, 0, 0)'),
              'a ring at 0 %% still has a stroke (a dot): %r' % z['widths'].get('ringStroke'))
        check(r['hidden']['asked'] == 0 and r['hidden']['back'] >= 1,
              'hidden, the page asked %d time(s); shown again, %d (%r)' % (r['hidden']['asked'], r['hidden']['back'], r['hidden'].get('state')))
        check(r['paused']['asked'] == 0, 'paused, the page asked %d time(s)' % r['paused']['asked'])
        _off_page = [p for t, p, on in TOUCHED if BROWSER['from'] <= t < (BROWSER.get('on_at') or 0) and not on]
        check(BROWSER.get('on_at') and not _off_page,
              'the page loaded with the meter off, and the meter touched %d path(s): %s'
              % (len(_off_page), _off_page[:3]))
        f5 = r['f5']
        check(f5['history'] >= 3 and f5['points'] >= 2 and f5['points'] in (f5['history'], f5['history'] + 1)
              and f5['ms'] < 1000, 'after F5 the graph had %d point(s) %d ms after the page loaded; the history %d'
              % (f5['points'], f5['ms'], f5['history']))
        ph = r['phone']
        check(ph['wide'] <= 420 and ph['shown'] and ph['visible'] == ['cpu', 'mem'], 'at 420 px: %r' % ph)
        check(ph['tap'] and ph['panelRight'] <= 420 and ph['shut'], 'a tap at 420 px: %r' % ph)
        print('the page: off nothing, a viewer the meter too; four looks, five styles, the pickers; nothing asked '
              'hidden or paused; details only while open; after F5 %d points at once; at 420 px no wider '
              'than the screen' % f5['points'])
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            for f in sorted((W / 'shots').iterdir()):
                shutil.copy(str(f), os.path.join(SHOTS, f.name))
finally:
    MOVING['on'] = False
    for p in PROCS:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    try:
        api.stop()
    except Exception:                                    # noqa: BLE001
        pass
    box.shutdown()
    box.server_close()
    shutil.rmtree(str(W), ignore_errors=True)

if bad:
    print('\n%d problem(s)' % len(bad))
    raise SystemExit(1)
print('\nthe performance meter: every check passed')
