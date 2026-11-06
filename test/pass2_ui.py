#!/usr/bin/env python3
"""5.44.1, pass 2: the panes root looks after, driven in Chromium with root's
answers stubbed. Fails on 5.44.0's page.

    python3 test/pass2_ui.py        (PASS2_PAGE=old: the same checks on
                                     5.44.0's page - every one must fail;
                                     PASS2_DUMP=1 prints what was measured)

The real page (php -S, a daemon behind it for the sign-in and the status),
root's answers stubbed in the browser - every state it can report:
  * Time, Network: a box focused, nothing typed yet, lost the focus at the
    pane's next look (10 s, 6 s) - an iPad's keyboard went down, an open list
    closed; "Time servers NOT set" and a backup's error were not red;
  * Network: Change it and restart refused - the popup closed, the refusal
    in a toast only; the new network on trial counted down only at each
    look, and at the end said "0 s left to keep it";
  * Upgrades: one asked and not taken by root yet - Upgrade pressable again,
    Forget there; a version chosen from the list of newer ones put back to
    the newest at the next look;
  * Backup: root busy with a whole backup (after a reload, or the nightly
    one) - "Back up the whole installation now" and Download pressable; a
    backup to other machines followed by two watches at once, and one look
    lost on the way ended the watch for good;
  * Firewall: a save refused (it would shut the page out) left "Unsaved
    changes" beside Save, the refusal in a toast; a rule refused, in a toast;
  * Restart at a time, a self-signed certificate (and the other popups of
    Certificates, a destination, a whole backup's download): refused, said
    only in a toast;
  * the database: Optimise (Back up, Check) pressed again while one ran - a
    second VACUUM beside the first;
  * Automatic certificates: an order begun elsewhere never shown;
  * and, holding already: every pane with much in it at 1600, 1194, 834 and
    420 wide - nothing wider than the screen or out of its card; the popups
    with a box over an iPad's keyboard (a fake visualViewport) - the box and
    the button in what it leaves; no error on the page.

Ports 19330 (the daemon), 19331 (php -S).
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-pass2-ui-'))
API_PORT, PHP_PORT = 19330, 19331
AGAINST_OLD = os.environ.get('PASS2_PAGE') == 'old'
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def finish():
    for p in PROCS:
        try:
            p.terminate()
            p.wait(5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    shutil.rmtree(str(W), ignore_errors=True)
    print('pass2_ui: %s' % ('%d failed' % len(bad) if bad else 'all good'))
    os._exit(1 if bad else 0)


__import__('atexit').register(lambda: [p.kill() for p in PROCS if p.poll() is None])

STATE, ETC = W / 'state', W / 'etc'
for p in (STATE / 'root', STATE / 'upgrade', ETC):
    p.mkdir(parents=True, exist_ok=True)
(ETC / 'config.json').write_text(json.dumps({'db_file': str(W / 'z.db')}))
os.environ.update(ZIGMON_STATE=str(STATE), ZIGMON_CONFIG=str(ETC / 'config.json'), ZIGMON_NO_SERVICES='1',
                  ZIGMON_SERVICE_LOG=str(W / 'services.log'), ZIGMON_FS_ROOT=str(W), ZIGMON_USER='root',
                  ZIGMON_ROOT_RUN='true', ZIGMON_UPGRADE_RUN='true')
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'sensors': [], 'mqtt_host': '', 'plugs': [],
                      'log_file': str(W / 'zigmon.log'), 'log_to_journal': False, 'state_dir': str(STATE),
                      'login_tries': 50, 'login_wait_min': 1, 'session_idle_min': 240, 'session_hours': 720,
                      'public_view': True, 'weather': False})
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)
d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
# what is to be done by hand: one on Upgrades with a long command, one on Certificates, two done lately
LONG = ('cd /root && curl -fLO https://github.com/falco81/ZIGMon/raw/main/release/zigmon-5.46.0.tar.gz && tar xzf '
        'zigmon-5.46.0.tar.gz && cd zigmon-5.46.0 && sudo ./install.sh --upgrade --with-the-units-of-5.46')
d.notice_raise('up.cli', 'warn', 'zigmon 5.46.0 must be put in from the command line', 'its units change', command=LONG,
               link='#control/sys-upgrade')
d.notice_raise('tls.parts', 'crit', 'root\'s part for certificates is older than the program', 'install.sh left it',
               command='sudo ./install.sh --upgrade', link='#control/sys-certs')
for k in ('old.one', 'old.two'):
    d.notice_raise(k, 'info', 'A step left by the installer of 5.43.%s' % k[-1], 'done', link='#control/sys-upgrade')
    d.notice_done(k, 'owner')

# what the daemon answers for each pane with nothing going on: the stubs start from it
BASE = {}
for name, f in [('net', d.net_view), ('ntp', d.ntp_view), ('power', d.power_view), ('about', d.about_view),
                ('fullbackup', d.full_state), ('upgrade', d.upgrade_state), ('tls', d.tls_state),
                ('firewall', lambda: d.firewall_state('owner')), ('rbackup', lambda: zigmon.rb_page(d)),
                ('acme', lambda: zigmon.acme_view(d)), ('acmepush', lambda: zigmon.push_view(d)),
                ('osup', lambda: zigmon.osup_view(d)), ('webproxy', zigmon.webproxy_view)]:
    try:
        BASE[name] = json.loads(json.dumps(f(), default=str))
    except Exception as e:                              # noqa: BLE001
        check(False, 'the daemon could not say what %s is: %r' % (name, e))
        BASE[name] = {}

# ---- the page (this one, or 5.44.0's) relaying to the daemon above ------------------------
NOW = W / 'web'
shutil.copytree(str(HERE / 'web'), str(NOW))
if AGAINST_OLD:
    pack = HERE / 'release' / 'zigmon-5.44.0.tar.gz'
    if not pack.exists():
        check(False, 'no release package of 5.44.0 to compare with')
        finish()
    with tarfile.open(str(pack)) as tar:
        for name in ('index.php', 'zigmon-api.php'):
            (NOW / name).write_bytes(tar.extractfile('zigmon-5.44.0/web/' + name).read())
text = (NOW / 'zigmon-api.php').read_text()
text = text.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
text = text.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
(NOW / 'zigmon-api.php').write_text(text)
(W / 'token').write_text(d.token)


def serve(folder, port):
    for _ in range(3):
        p = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % port, '-t', str(folder)], cwd=str(folder),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                             env=dict(os.environ, PHP_CLI_SERVER_WORKERS='16'))
        for _ in range(50):
            try:
                socket.create_connection(('127.0.0.1', port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        time.sleep(0.3)
        if p.poll() is None:
            PROCS.append(p)
            return p
        time.sleep(3)
    return None


if not shutil.which('php') or not serve(NOW, PHP_PORT):
    check(False, 'php -S could not serve the page')
    finish()

PRELUDE = r'''
const { chromium, devices } = require('playwright');
const cfg = JSON.parse(require('fs').readFileSync(process.env.H_CFG, 'utf8'));
const out = {errors: []};
const wait = ms => new Promise(r => setTimeout(r, ms));
const clone = x => JSON.parse(JSON.stringify(x));
// root's answers, stubbed: S[api] is what a read answers, R[api] what a POST answers
const S = clone(cfg.base), R = {}, posts = [];
const STUBBED = /^(net|ntp|power|about|fullbackup|upgrade|tls|firewall|rbackup|acme|acmepush|osup|webproxy|db-optimize|db-backup)(-do|-upload|\/[a-z-]+)?$/;
async function stub(ctx) {
  await ctx.route(/\?api=/, (route, req) => {
    const what = new URL(req.url()).searchParams.get('api');
    if (!STUBBED.test(what)) return route.continue();
    let body;
    if (req.method() === 'POST') {
      let b = {}; try { b = JSON.parse(req.postData() || '{}'); } catch (e) {}
      posts.push([what, b, Date.now()]);
      const r = R[what];
      body = typeof r === 'function' ? r(b) : (r || {ok: true, message: 'asked'});
    } else body = typeof S[what] === 'function' ? S[what]() : S[what];
    const send = () => (body && body.__status)
      ? route.fulfill({status: body.__status, contentType: 'application/json', body: JSON.stringify({error: body.error})})
      : route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body || {ok: true})});
    if (body && body.__delay) setTimeout(() => send().catch(() => {}), body.__delay); else return send();
  });
}
const IPAD = devices['iPad Pro 11'];
function ctxOpts(kind, w, h) {
  if (kind === 'ipad') return Object.assign({}, IPAD, {viewport: {width: w, height: h}, screen: {width: w, height: h}});
  return {viewport: {width: w, height: h}};
}
const fakeVV = () => {
  const t = new EventTarget(); let h = window.innerHeight || 834; let top = 0;
  Object.defineProperty(t, 'height', {get: () => h}); Object.defineProperty(t, 'offsetTop', {get: () => top});
  t.offsetLeft = 0; t.scale = 1; t.pageTop = 0;
  Object.defineProperty(t, 'width', {get: () => window.innerWidth});
  window.__vv = (v, o) => { h = v; top = o || 0; t.dispatchEvent(new Event('resize')); };
  Object.defineProperty(window, 'visualViewport', {value: t, configurable: true});
};
async function open(b, sec, kind, w, h, init) {
  const ctx = await b.newContext(ctxOpts(kind || 'desk', w || 1600, h || 1000));
  if (init) await ctx.addInitScript(init);
  await stub(ctx);
  const p = await ctx.newPage();
  p.setDefaultTimeout(8000);
  p.on('pageerror', e => out.errors.push(sec + ': ' + String(e).slice(0, 300)));
  await p.goto(cfg.base_url + '/', {timeout: 30000});
  await p.evaluate(async () => fetch('?api=login', {method: 'POST', credentials: 'same-origin',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: 'owner', password: 'owner pass 12'})}));
  await p.goto(cfg.base_url + '/#control/' + sec);
  await p.reload();
  await wait(1800);
  return [ctx, p];
}
async function show(p, sec) { await p.evaluate(s => { showTab('control'); showControlSection(s); }, sec); await wait(900); }
const T = s => (s && s.textContent || '').replace(/\s+/g, ' ').trim();
'''


def browser(js):
    node_path = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
    if not node_path or not (Path(node_path) / 'playwright').exists():
        check(False, 'no playwright here')
        return {}
    (W / 'page.js').write_text(PRELUDE + js)
    (W / 'cfg.json').write_text(json.dumps({'base_url': 'http://127.0.0.1:%d' % PHP_PORT, 'base': BASE,
                                            'now': time.time()}))
    got = subprocess.run(['node', str(W / 'page.js')], capture_output=True, text=True, timeout=1500, cwd=str(W),
                         stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=node_path, H_CFG=str(W / 'cfg.json')))
    try:
        return json.loads((got.stdout.strip().splitlines() or ['{}'])[-1])
    except ValueError:
        return {'error': (got.stdout + got.stderr)[-1500:]}


if os.environ.get('PASS2_EXPLORE'):
    o = browser(Path(os.environ['PASS2_EXPLORE']).read_text())
    print(json.dumps(o, indent=1))
    finish()

PAGE_JS = r'''
const now = cfg.now;
const kept = (id) => !!document.activeElement && document.activeElement.isConnected
  && !!document.getElementById(id) && document.getElementById(id).contains(document.activeElement);
const crit = () => { const p = document.createElement('span'); p.style.color = 'var(--crit)'; document.body.appendChild(p);
  const c = getComputedStyle(p).color; p.remove(); return c; };
const said = () => { const p = document.querySelector('#zmodal-body .note.bad');
  return {open: !document.getElementById('zmodal').hidden, said: p ? p.textContent : ''}; };
const cert = (cn) => ({cn: cn, subject: 'CN=' + cn, issuer: 'CN=R11,O=Let\'s Encrypt,C=US', not_before: now - 86400 * 30,
  not_after: now + 86400 * 60, key: 'RSA 2048', san: [cn, 'www.' + cn], chain: 1});
const layout = () => {
  const o = {iw: innerWidth, sw: document.documentElement.scrollWidth, out: []};
  const cards = Array.from(document.querySelectorAll('#tab-control [data-sec="' + CONTROL_SEC + '"]'))
    .filter(c => !c.hidden && c.getClientRects().length);
  cards.forEach(c => {
    const r = c.getBoundingClientRect();
    c.querySelectorAll('*').forEach(e => {
      if (!e.getClientRects().length || e.closest('.obj-mark')) return;
      const q = e.getBoundingClientRect();
      if (!q.width || q.right <= r.right + 2) return;
      for (let s = e.parentElement; s && s !== c; s = s.parentElement)
        if (/auto|scroll|hidden/.test(getComputedStyle(s).overflowX)) return;
      o.out.push((e.id || String(e.className) || e.tagName) + ' +' + Math.round(q.right - r.right));
    });
  });
  o.out = o.out.slice(0, 4);
  return o;
};
// every pane with much in it, as root reports it at a busy moment
const RICH = {
  'sec-firewall': () => {},
  'sys-network': () => { S.net = Object.assign(clone(cfg.base.net), {job: {state: 'failed', pct: 100, steps: [{ok: false,
      what: 'nmcli said: Error: unknown connection "eth9" - nothing was changed', at: now - 5}]}}); },
  'sys-time': () => { S.ntp = Object.assign(clone(cfg.base.ntp), {now: {at: now - 4, data: {time: now, chrony: true, timezone: 'Europe/Prague',
      tracking: {ref: 'tik.cesnet.cz', stratum: 2, offset: 0.0003, leap: 'Normal'},
      sources: [{state: '?', name: 'a-very-long-ntp-server-name.time.example.cz', stratum: 0, poll: 10, reach: 0, last_rx: null, offset: 0, error: 0}]}},
      applied: {at: now - 60, ok: false, said: 'chronyd did not start: Job for chronyd.service failed because the control process exited'}}); },
  'sys-certs': () => { S.tls = Object.assign(clone(cfg.base.tls), {server_name: 'zigmon.a-rather-long-house-name.example.cz',
      now: {info: cert('zigmon.a-rather-long-house-name.example.cz'), alt_info: {key: 'ECDSA P-256', not_after: now + 86400 * 60}, verify: 'ok',
            files: {cert: '/etc/pki/tls/certs/zigmon-a-rather-long-house-name.crt', key: '/etc/pki/tls/private/zigmon.key'}},
      conf: Object.assign(clone(cfg.base.tls.conf), {managed: true}), node: {name: 'vm', me: true, state: 'failed', current: false,
        said: ['nginx -t said: [emerg] cannot load certificate "/etc/pki/tls/certs/zigmon.crt": PEM_read_bio_X509_AUX() failed']},
      proxy: {host: 'front.example.cz', key_way: true, look: {info: cert('front.example.cz'), blocks: 2}, conf: {}, node: {}},
      proxy_ntfy: {host: 'front.example.cz', key_way: true, look: {info: cert('ntfy.example.cz')}, conf: {}, node: {}}});
    S.acmepush = Object.assign(clone(cfg.base.acmepush), {on: true, pairing: {until: now + 800, tries: 1},
      keys: [{name: 'acme-in-the-cellar', key_id: 'k_0123456789abcdef0123', at: now - 3600, how: 'pasted'}]}); },
  'sys-acme': () => { S.acme = Object.assign(clone(cfg.base.acme), {on: true, challenge: 'dns-01', work: {busy: true, says: 'waiting for the CA', target: 'web'},
      manual: {rr: '_acme-challenge.zigmon.a-rather-long-house-name.example.cz', txt: 'gfj9Xq0U3cLGgBXX1Qz8kBk9ujl8eKJe2zq0k3uYHdQ'},
      dns_guide: {challenge: 'dns-01', dns: 'desec', rows: [{target: 'web', record: '_acme-challenge.zigmon.a-rather-long-house-name.example.cz',
        type: 'CNAME', value: '_acme-challenge.myhouse.dedyn.io', check: true}]}}); },
  'sys-power': () => { S.power = Object.assign(clone(cfg.base.power), {plan: {id: 'p1', how: 'reboot', by: 'owner', at: now - 50, done: true},
      row: {id: 'p1', state: 'failed', said: 'systemctl reboot said: Failed to talk to init daemon: Connection timed out'}}); },
  'sys-backup': () => { S.rbackup = Object.assign(clone(cfg.base.rbackup), {locked: true,
      targets: [{id: 't1', name: 'The NAS in the cellar', kind: 'smb', kind_words: 'SMB', enabled: true, host: 'nas-in-the-cellar.home.arpa',
                 share: 'backups', path: 'zigmon/nightly/the-whole-installation'}],
      runs: [{at: now - 3600, host: 'vm', file: 'zigmon-full-vm-20261106-0315.tar.gz.enc', bytes: 734003200, ok: false,
              error: 'Offsite: ssh: connect to host backup.offsite-provider.example.org port 2222: Connection timed out', targets: [{name: 'Offsite', ok: false}]}]});
    S.fullbackup = Object.assign(clone(cfg.base.fullbackup), {list: [{file: 'zigmon-full-vm-20261105-before-upgrade-5.44.0.tar.gz',
      ts: now - 136000, bytes: 734003200, why: 'before an upgrade'}]}); },
  'sys-upgrade': () => { const u = clone(cfg.base.upgrade);
    u.web.online = {at: now - 10, newer: true, newest: {version: '5.46.0'}, here: '5.44.0', url: 'https://x/', newer_list: [{version: '5.46.0'}, {version: '5.45.1'}]};
    u.status = {state: 'failed', rolled_back: true, said: 'the new version did not answer on /api/health within 90 s: the old one was put back',
                version: '5.46.0', at: now - 30, id: 'x', tail: ['==> a']};
    S.upgrade = u; },
  'sys-osup': () => { S.osup = Object.assign(clone(cfg.base.osup), {reboot: true, check: {checked: now - 100, count: 112, security: 12, state: 'failed',
      error: 'dnf said: Curl error (6): Could not resolve host: mirrors.almalinux.org'}, run: {id: 'r1', state: 'failed', by: 'owner', began: now - 60, at: now - 2,
      said: 'Error: Transaction test error: file /usr/lib64/libssl.so.3 conflicts between attempted installs', lines: ['Error: Transaction test error']}}); },
  'sys-proxy': () => {},
  'sys-data': () => {},
  'sys-about': () => {},
};
(async () => {
  const b = await chromium.launch();
  try {
    // (1) the clock and the network: a box focused, nothing typed yet, through the pane's next look
    S.ntp = Object.assign(clone(cfg.base.ntp), {now: {at: now - 4, data: {time: now, chrony: true, timezone: 'Europe/Prague',
      tracking: {ref: 'x', stratum: 2, offset: 0.0003, leap: 'Normal'}, sources: []}}, zones: ['Europe/Prague', 'UTC'],
      applied: {at: now - 60, ok: false, said: 'chronyd did not start'},
      conf: {manage: true, servers: [{host: 'tik.cesnet.cz', iburst: true}], allow: [], makestep: [1, 3], minsources: 1, timezone: 'Europe/Prague'}});
    S.net = Object.assign(clone(cfg.base.net), {now: {at: now - 4, data: {hostname: 'zig.example.cz', con: 'eth0', dev: 'eth0', nm: true,
      conf: {ipv4_method: 'manual', ipv4_addresses: ['192.168.1.20/24'], ipv4_gateway: '192.168.1.1'}, live: {},
      devices: [{con: 'eth0', dev: 'eth0', type: 'ethernet'}]}}});
    {
      const [ctx, p] = await open(b, 'sys-time');
      await show(p, 'sys-time');
      await p.focus('#ntp-conf input[type=text]');
      out.ntp = {before: await p.evaluate(kept, 'ntp-conf')};
      await wait(11500);
      out.ntp.after = await p.evaluate(kept, 'ntp-conf');
      out.ntp.notSet = await p.evaluate(c => { const n = document.querySelector('#ntp-now .ntp-set');
        return n ? getComputedStyle(n).color === c : null; }, await p.evaluate(crit));
      await show(p, 'sys-network');
      await wait(800);
      await p.focus('#net-form input[type=text]');
      out.net = {before: await p.evaluate(kept, 'net-form')};
      await wait(7000);
      out.net.after = await p.evaluate(kept, 'net-form');
      // the change refused by the daemon: said in the popup, which stays
      R['net-do'] = q => q.action === 'plan' ? {ok: true, plan: ['the address set', 'the machine restarted'], want: {new_ip: '192.168.1.21'}}
        : {__status: 400, error: 'the system is being updated - change the network when that is done'};
      await p.evaluate(() => { document.activeElement.blur();
        Array.from(document.querySelectorAll('#net-form button')).filter(x => /restart/.test(x.textContent))[0].click(); });
      await wait(700);
      await p.evaluate(() => Array.from(document.querySelectorAll('#zmodal-foot button')).filter(x => /Change it/.test(x.textContent))[0].click());
      await wait(700);
      out.net.refused = await p.evaluate(said);
      await p.evaluate(() => closeZModal());
      // the new network on trial: counted down each second, and said when the time is up
      S.net = Object.assign(clone(cfg.base.net), {job: {state: 'trial', pct: 90, trial_until: now + 600, steps: [{ok: true, what: 'restarted', at: now - 5}]}});
      await p.evaluate(() => loadNet(true));
      await wait(600);
      const left = () => p.evaluate(() => { const n = document.querySelector('#net-job .says'); return n ? n.textContent : ''; });
      out.trial = {a: await left()};
      await wait(2200);
      out.trial.b = await left();
      S.net.job.trial_until = Date.now() / 1000 + 2;
      await p.evaluate(() => loadNet(true));
      await wait(4500);
      out.trial.up = await left();
      await ctx.close();
    }
    // (2) Upgrades: one asked, not taken yet; a version chosen from the list
    {
      S.upgrade = Object.assign(clone(cfg.base.upgrade), {asked: true, ready: true,
        package: {version: '5.45.0', signed_by: 'k', bytes: 100, by: 'owner', at: now - 60, newer: true}});
      const [ctx, p] = await open(b, 'sys-upgrade');
      await show(p, 'sys-upgrade');
      out.asked = await p.evaluate(() => ({start: document.getElementById('up-start').disabled, forget: document.getElementById('up-forget').hidden}));
      const u = clone(cfg.base.upgrade);
      u.web.online = {at: now - 10, newer: true, newest: {version: '5.46.0', url: 'https://x/'}, here: '5.44.0', url: 'https://x/',
                      newer_list: [{version: '5.46.0'}, {version: '5.45.1'}, {version: '5.45.0'}]};
      S.upgrade = u;
      await p.evaluate(() => loadUpgrade(true));
      await wait(800);
      await p.selectOption('#up-web select', '5.45.0');
      await p.evaluate(() => document.activeElement.blur());
      await wait(9500);
      out.pick = await p.evaluate(() => ({value: (document.querySelector('#up-web select') || {}).value,
        buttons: Array.from(document.querySelectorAll('#up-web .btnrow button')).map(x => x.textContent.trim())}));
      await ctx.close();
    }
    // (3) the backups: root busy with a whole one; one look at a backup to other machines lost
    {
      S.fullbackup = Object.assign(clone(cfg.base.fullbackup), {busy: {since: 5, working: true},
        progress: {id: 'x', words: 'packing the database', step: 2, total: 5, at: now - 5, expect_s: 60},
        list: [{file: 'zigmon-full-vm-20261106-0300.tar.gz', ts: now - 36000, bytes: 1234567, why: 'nightly'}]});
      S.rbackup = Object.assign(clone(cfg.base.rbackup), {job: {running: true, what: 'backup', says: 'sending', done: 1, whole: 4, began: now - 5}});
      const asks = [];
      R['rbackup-do'] = q => { if (q.action !== 'job') return {ok: true};
        asks.push(Date.now()); return asks.length === 2 ? {__status: 502, error: 'bad gateway'}
          : {ok: true, job: {running: true, what: 'backup', says: 'sending ' + asks.length, done: 1, whole: 4}}; };
      const [ctx, p] = await open(b, 'sys-backup');
      const t0 = Date.now();
      await show(p, 'sys-backup');
      out.full = await p.evaluate(() => ({make: document.getElementById('full-make').disabled,
        acts: Array.from(document.querySelectorAll('#full-list td.acts button')).map(x => x.disabled)}));
      await wait(9000);
      out.rb = {asks: asks.length, after: asks.filter(t => t > asks[1] + 500).length, secs: (Date.now() - t0) / 1000};
      // the error of a run said in red in What was sent
      S.rbackup = Object.assign(clone(cfg.base.rbackup), {runs: [{at: now - 60, host: 'vm', file: 'f.enc', ok: false, error: 'it timed out', targets: []}]});
      R['rbackup-do'] = {ok: true, job: {running: false}};
      await p.evaluate(() => loadRb(true));
      await wait(800);
      out.rbRed = await p.evaluate(c => { const n = document.querySelector('#rb-runs .small.bad');
        return n ? getComputedStyle(n).color === c : null; }, await p.evaluate(crit));
      await ctx.close();
    }
    // (4) the firewall: a save refused, a rule refused
    {
      R['firewall-do'] = q => q.action === 'save' ? {__status: 400, error: 'this would shut out 10.0.0.5, the address you are on - refused'}
        : (q.action === 'rule_check' ? {__status: 400, error: 'the port is a number from 1 to 65535'} : {ok: true});
      const [ctx, p] = await open(b, 'sec-firewall');
      await show(p, 'sec-firewall');
      await p.evaluate(() => { FW.draft.rules.push({id: 'n1', family: 0, proto: 'tcp', port: '22', source: '', action: 'drop', note: ''}); fwDirty(); });
      await p.click('#fw-save');
      await wait(800);
      out.fw = await p.evaluate(c => { const n = document.getElementById('fw-note');
        return {note: n.textContent, red: getComputedStyle(n).color === c}; }, await p.evaluate(crit));
      await p.evaluate(() => fwRuleEdit(FW.last, null));
      await wait(300);
      await p.evaluate(() => document.querySelector('#zmodal-foot .btn.primary').click());
      await wait(700);
      out.rule = await p.evaluate(said);
      await ctx.close();
    }
    // (5) a restart at a time refused; a self-signed certificate refused
    {
      R['power-do'] = q => q.when ? {__status: 400, error: 'that is gone by - a time from now on, a month ahead at the most'} : {ok: true};
      R['tls-do'] = q => q.action === 'tls_selfsigned' ? {__status: 400, error: 'the name is not a DNS name: zig mon'} : {ok: true};
      const [ctx, p] = await open(b, 'sys-power');
      await show(p, 'sys-power');
      await p.evaluate(() => powerAt());
      await wait(300);
      await p.evaluate(() => document.querySelector('#zmodal-foot .btn.primary').click());
      await wait(700);
      out.powerAt = await p.evaluate(said);
      await p.evaluate(() => closeZModal());
      await show(p, 'sys-certs');
      await p.evaluate(() => certSelf({server_name: 'zig mon'}, true));
      await wait(300);
      await p.evaluate(() => document.querySelector('#zmodal-foot .btn.primary').click());
      await wait(700);
      out.selfSigned = await p.evaluate(said);
      await p.evaluate(() => closeZModal());
      // (6) the database: Optimise pressed twice while the first one runs
      R['db-optimize'] = {__delay: 2500, ok: true, before_bytes: 1000, after_bytes: 900, seconds: 1};
      await show(p, 'sys-data');
      const n0 = posts.filter(x => x[0] === 'db-optimize').length;
      await p.evaluate(() => { document.getElementById('db-optimize').click(); });
      await wait(300);
      out.db = {during: await p.evaluate(() => ['db-check', 'db-optimize', 'db-backup'].map(id => document.getElementById(id).disabled))};
      await p.evaluate(() => { document.getElementById('db-optimize').click(); document.getElementById('db-backup').click(); });
      await wait(3500);
      out.db.optimize = posts.filter(x => x[0] === 'db-optimize').length - n0;
      out.db.backup = posts.filter(x => x[0] === 'db-backup').length;
      out.db.after = await p.evaluate(() => ['db-check', 'db-optimize', 'db-backup'].map(id => document.getElementById(id).disabled));
      // (9) Automatic certificates open, and an order begun elsewhere (a renewal by itself)
      await show(p, 'sys-acme');
      out.acme = {before: await p.evaluate(() => !!document.querySelector('#ac-host .going'))};
      S.acme = Object.assign(clone(cfg.base.acme), {on: true, work: {busy: true, says: 'renewing it by itself', target: 'web', began: now}});
      await wait(16500);
      out.acme.after = await p.evaluate(() => !!document.querySelector('#ac-host .going'));
      await ctx.close();
    }
    // (7) every pane as root reports it at a busy moment: nothing wider than the screen
    out.layout = {};
    for (const [kind, w, h] of [['desk', 1600, 1000], ['ipad', 1194, 834], ['ipad', 834, 1194], ['desk', 420, 900]]) {
      Object.assign(S, clone(cfg.base));
      Object.keys(RICH).forEach(k => RICH[k]());
      const [ctx, p] = await open(b, 'sys-about', kind, w, h);
      for (const sec of Object.keys(RICH)) {
        await show(p, sec);
        const m = await p.evaluate(layout);
        if (m.sw > m.iw + 1 || m.out.length) out.layout[sec + ' ' + w] = m;
      }
      await ctx.close();
    }
    // (8) an iPad's keyboard over the popups with a box: the box and the button in what it leaves
    out.kb = {};
    const DIALOGS = {powerAt: ['sys-power', 'powerAt()'], rule: ['sec-firewall', 'fwRuleEdit(FW.last || {may: true}, null)'],
      sftp: ['sys-backup', "rbEdit({kind: 'sftp', kind_words: 'SFTP'})"], smb: ['sys-backup', "rbEdit({kind: 'smb', kind_words: 'SMB'})"],
      pfx: ['sys-certs', "certDownload({now: {info: {cn: 'x'}}, server_name: 'x'}); document.querySelectorAll('#zmodal .fmt-card')[4].click()"],
      selfsigned: ['sys-certs', "certSelf({server_name: 'x'}, true)"], full: ['sys-backup', "fullDownload('zigmon-full-x.tar.gz')"],
      maintenance: ['sys-upgrade', 'maintenanceAsk(true)'], acme: ['sys-acme', "acmeNameAsk({target: 'web', name: '', server_name: 'a'})"],
      paste: ['sys-certs', 'pushPaste()']};
    Object.assign(S, clone(cfg.base));
    for (const [w, h] of [[1194, 834], [834, 1194]]) {
      const [ctx, p] = await open(b, 'sys-power', 'ipad', w, h, fakeVV);
      for (const k of Object.keys(DIALOGS)) {
        await show(p, DIALOGS[k][0]);
        await p.evaluate(c => { eval(c); }, DIALOGS[k][1]);
        await wait(400);
        const fields = [];
        for (const f of await p.$$('#zmodal-body input:not([type=hidden]):not([type=checkbox]):not([disabled]), #zmodal-body textarea, #zmodal-body select'))
          if (await f.isVisible()) fields.push(f);
        if (!fields.length) { out.kb[k + ' ' + w] = 'no box'; await p.evaluate(() => closeZModal()); continue; }
        await fields[fields.length - 1].focus();
        await p.evaluate(v => window.__vv(v), Math.round(h * 0.55));
        await wait(500);
        const r = await p.evaluate(() => {
          const vv = window.visualViewport, bot = vv.offsetTop + vv.height;
          return [document.activeElement, document.querySelector('#zmodal-foot .btn.primary') || document.querySelector('#zmodal-foot .btn:last-child')].map(e => {
            const q = e.getBoundingClientRect(), at = document.elementFromPoint(q.left + q.width / 2, q.top + q.height / 2);
            return q.height > 0 && q.top >= vv.offsetTop - 0.5 && q.bottom <= bot + 0.5 && !!at && (at === e || e.contains(at));
          });
        });
        if (!r[0] || !r[1]) out.kb[k + ' ' + w] = r;
        await p.evaluate(() => { window.__vv(window.innerHeight); if (document.activeElement) document.activeElement.blur(); closeZModal(); });
        await wait(250);
      }
      await ctx.close();
    }
  } catch (e) {
    out.error = String(e && e.stack || e).slice(0, 800);
  }
  console.log(JSON.stringify(out));
  await b.close();
})();
'''

o = browser(PAGE_JS)
check(not o.get('error'), 'the page could not be driven: %s' % o.get('error'))
if os.environ.get('PASS2_DUMP'):
    print(json.dumps(o, indent=1))

n = o.get('ntp') or {}
check(n.get('before') and n.get('after'),
      'Time: a box of the time servers focused, nothing typed yet, lost the focus at the pane\'s next look (every 10 s) - '
      'the keyboard of an iPad went down, an open list of zones closed: %r' % n)
check(n.get('notSet') is True, 'Time: "Time servers NOT set ... chronyd did not start" is not said in red: %r' % n.get('notSet'))
nt = o.get('net') or {}
check(nt.get('before') and nt.get('after'),
      'Network: a box of New settings focused, nothing typed yet, lost the focus at the pane\'s next look (every 6 s): %r' % nt)
check((nt.get('refused') or {}).get('open') and 'being updated' in (nt.get('refused') or {}).get('said', ''),
      'Network: Change it and restart refused by the daemon - the popup closed, the refusal only in a toast: %r' % nt.get('refused'))
print('Time and Network: a box focused through the next look; a refusal in the popup')

tr = o.get('trial') or {}
check(tr.get('a') and tr.get('b') and tr.get('a') != tr.get('b'),
      'Network: the time left to keep a new network does not count down between two looks: %r' % tr)
check('not kept in time' in (tr.get('up') or ''),
      'Network: the time to keep a new network over, its card says %r - not that the old network comes back' % tr.get('up'))
print('Network: the trial counted down, and its end said')

a = o.get('asked') or {}
check(a.get('start') is True and a.get('forget') is True,
      'Upgrades: an upgrade asked and not taken by root yet - Upgrade this server pressable again, Forget the package '
      'there to take it from under root: %r' % a)
pk = o.get('pick') or {}
check(pk.get('value') == '5.45.0' and 'Upgrade to 5.45.0 now' in (pk.get('buttons') or []),
      'Upgrades: 5.45.0 chosen from the list of newer versions - the next look put the newest back: %r' % pk)
print('Upgrades: asked and not taken; a version chosen')

f = o.get('full') or {}
check(f.get('make') is True and f.get('acts') == [True, True, True],
      'Backup: root busy making a whole backup - "Back up the whole installation now" or a Download still pressable: %r' % f)
rb = o.get('rb') or {}
check(rb.get('after', 0) >= 2 and rb.get('asks', 99) <= rb.get('secs', 9) / 1.5 + 2,
      'Backup: a backup to other machines followed - one look lost on the way ended the watch, or two watches asked '
      'side by side: %r' % rb)
check(o.get('rbRed') is True, 'Backup: the error of a backup sent is not said in red: %r' % o.get('rbRed'))
print('Backup: root busy; a look lost on the way')

fw = o.get('fw') or {}
check('shut out' in (fw.get('note') or '') and fw.get('red'),
      'Firewall: a save refused (it would shut the page out) - beside Save it still says %r' % fw.get('note'))
ru = o.get('rule') or {}
check(ru.get('open') and '65535' in (ru.get('said') or ''), 'Firewall: a rule refused - not said in its popup: %r' % ru)
pa = o.get('powerAt') or {}
check(pa.get('open') and 'gone by' in (pa.get('said') or ''),
      'Restart and power off: a time refused - the popup closed, the refusal only in a toast: %r' % pa)
ss = o.get('selfSigned') or {}
check(ss.get('open') and 'DNS name' in (ss.get('said') or ''),
      'Certificates: a self-signed one refused - not said in its popup: %r' % ss)
print('refusals said where they were asked for')

db = o.get('db') or {}
check(db.get('during') == [True, True, True] and db.get('optimize') == 1 and db.get('backup') == 0
      and db.get('after') == [False, False, False],
      'The database: Optimise pressed twice (and Back up) while the first one ran: %r' % db)
print('The database: one job at a time')
ac = o.get('acme') or {}
check(ac.get('before') is False and ac.get('after') is True,
      'Automatic certificates: an order begun elsewhere while the pane was open is never shown there: %r' % ac)
print('Automatic certificates: an order begun elsewhere')

check(not o.get('layout'), 'a pane wider than the screen, or a part of one out of its card: %r' % o.get('layout'))
check(not o.get('kb'), 'an iPad\'s keyboard over a popup: the box typed in, or its button, under it: %r' % o.get('kb'))
print('every pane at 1600, 1194, 834 and 420; the popups over an iPad\'s keyboard')

check(not o.get('errors'), 'errors on the page: %r' % (o.get('errors') or [])[:5])
finish()
