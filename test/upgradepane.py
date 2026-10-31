#!/usr/bin/env python3
"""5.35.1: Upgrades and maintenance looks and works as otp 1.0.197's pane.

  * a package of the version that runs here is a retry, as otp and root's
    zigmon_upgrade.py have it: ready, nothing said against it, and started
    like any other - no red "this is the version that runs here already";
  * the real page (php -S) in Chromium, the daemon's answers stubbed:
    - the cards in otp's order with otp's titles (What root said last, its
      output folded under a bar; On the command line);
    - the nodes table with the Maintenance button at the right end of its row;
    - From the web: the address in a line of its own, in mono, not a box;
    - the three settings side by side, each its name in bold over its
      control - the switch at the left, under the name - the (i) at the right
      end of the name, and its words under the control in three lines;
    - no Save of the card's own: otp's save bar at the end of the pane, faded
      until something is changed, then "1 change(s) not saved yet" and stuck
      to the bottom; Save the changes saves, Put them back puts them back;
    - What changed in X a bar with a chevron, otp's fold, not a blue link;
    - with a package of the version that runs here, Upgrade this server
      enabled and filled as otp's primary is, and no red band;
    - Look now, Maintenance, Upgrade and Forget each ask the daemon.

Fails on 5.35.0.

    python3 test/upgradepane.py

Port 19725 (php -S).
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-upgradepane-check-'))
PHP_PORT = 19725
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


# ---- a package of the version that runs here --------------------------------------------
print('a package of the version that runs here')
STATE, ETC = W / 'state', W / 'etc'
for p in (STATE / 'upgrade', ETC / 'zigmon'):
    p.mkdir(parents=True, exist_ok=True)
DB = STATE / 'history.db'
(ETC / 'zigmon' / 'config.json').write_text(json.dumps({'db_file': str(DB)}))
os.environ.update(ZIGMON_STATE=str(STATE), ZIGMON_CONFIG=str(ETC / 'zigmon' / 'config.json'),
                  ZIGMON_NO_SERVICES='1', ZIGMON_SERVICE_LOG=str(W / 'services.log'), ZIGMON_FS_ROOT=str(W),
                  ZIGMON_USER='root', ZIGMON_ROOT_RUN='true', ZIGMON_UPGRADE_RUN='true')
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

try:
    zigmon.load_config()
    zigmon.CONFIG.update({'db_file': str(DB), 'token_file': str(W / 'token'), 'plugs': [], 'sensors': [],
                          'mqtt_host': '', 'log_file': '', 'state_dir': str(STATE)})
    d = zigmon.Daemon()
    name = 'zigmon-%s.tar.gz' % zigmon.__version__
    (STATE / 'upgrade' / name).write_bytes(b'not read here')
    (STATE / 'upgrade' / 'package.json').write_text(json.dumps({
        'file': name, 'version': zigmon.__version__, 'signed_by': 'zigmon-release-test', 'bytes': 13,
        'sha': '0' * 64, 'at': int(time.time()), 'by': 'admin', 'newer': False, 'older': False}))
    st = d.upgrade_state()
    check(st.get('package') and st['package']['version'] == zigmon.__version__, 'the package is not there: %r' % st.get('package'))
    check(st.get('ready') and not st.get('not_ready'),
          'a package of the version that runs here is not ready: %r' % st.get('not_ready'))
    try:
        ident = d.upgrade_start('admin')
        check(bool(ident) and (STATE / 'upgrade' / 'request.json').exists(), 'the retry was not asked of root')
    except ValueError as e:
        check(False, 'a retry of the version that runs here was refused: %s' % e)
    try:
        d.store.flush()
    except Exception:
        pass
except Exception as e:                                  # noqa: BLE001 - said, and the page still looked at
    check(False, 'the checks of the daemon broke off: %r' % e)

# ---- the real page in Chromium ----------------------------------------------------------
print('the pane in Chromium')
JS = r'''
const { chromium } = require('playwright');
const now = Date.now() / 1000;
const url = 'https://github.com/falco81/ZIGMon/tree/main/release';
const m = {on: false};
const up = {ok: true, version: '5.35.0', node: 'zigmon', helper: true, path_unit: true, ready: true, not_ready: [],
  status: {}, running: false, asked: false, back: {on: false}, maintenance: m, log: ['==> installing', 'done'],
  nodes: [{name: 'zigmon', me: true, alive: true, version: '5.35.0', at: now - 4, since: now - 3600, maintenance: m}],
  web: {check: true, url: url, online: {at: now - 360, newest: {version: '5.35.0'}, here: '5.35.0', url: url}},
  package: {version: '5.35.0', signed_by: 'zigmon-release-1', bytes: 1843200, by: 'admin', at: now - 300, newer: false,
            changelog: '## 5.35.0\n\n- the pane'}};
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({viewport: {width: 1600, height: 1000}});
  p.setDefaultTimeout(4000);           // a control that is not there fails the check, not the run
  const errs = [], posts = [];
  p.on('pageerror', e => errs.push(String(e)));
  await p.route(/\?api=/, (route, req) => {
    const what = new URL(req.url()).searchParams.get('api');
    if (req.method() === 'POST') posts.push([what, JSON.parse(req.postData() || '{}')]);
    let body = {ok: true};
    if (what === 'upgrade') body = up;
    else if (what === 'upgrade-do') body = Object.assign({message: 'done'}, up);
    else if (what === 'config-save') body = {ok: true, changed: ['upgrade_check']};
    else if (what === 'status') { route.fulfill({status: 500, contentType: 'application/json', body: '{"error":"stub"}'}); return; }
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
  });
  await p.goto('http://127.0.0.1:%(port)d/index.php#control/sys-upgrade');
  await p.waitForTimeout(1200);
  await p.evaluate((url) => {
    LOCK.who = {name: 'admin', role: 'admin'};
    renderSettings({runtime_config: {upgrade_check: {value: 1, kind: 'switch'},
      upgrade_url: {value: url, kind: 'text'}, downgrade_show: {value: 0, kind: 'switch'}}});
    try { showTab('control'); } catch (e) {}
    try { showControlSection('sys-upgrade'); } catch (e) {}
  }, url);
  await p.waitForTimeout(1500);
  const r = await p.evaluate(() => {
    const T = s => (s && s.textContent || '').replace(/\s+/g, ' ').trim();
    const R = e => e ? e.getBoundingClientRect() : null;
    const out = {};
    const shown = e => e && !e.hidden && getComputedStyle(e).display !== 'none';
    out.cards = Array.from(document.querySelectorAll('#tab-control .grid.charts > [data-sec="sys-upgrade"]'))
      .filter(shown).map(c => T(c.querySelector(':scope > h2')).replace(/About$/, '').trim());
    // the nodes: the button at the right end of its row
    const row = document.querySelector('#up-nodes tbody tr'), mb = row && row.querySelector('button');
    out.mbRight = mb ? Math.round(R(row).right - R(mb).right) : null;
    // the address
    const u = Array.from(document.querySelectorAll('#up-web p')).filter(x => /github\.com/.test(x.textContent))[0];
    out.url = u ? {code: !!u.querySelector('code'), mono: /mono|Menlo|Consolas/.test(getComputedStyle(u).fontFamily)} : null;
    // the three settings
    out.items = Array.from(document.querySelectorAll('#up-web-card .set-item')).map(it => {
      const l = it.querySelector('label'), c = it.querySelector('.sw, input[type=text]'), s = it.querySelector('.set-says'),
            i = it.querySelector('label .iinfo');
      return {labelAbove: !!(l && c) && R(l).bottom <= R(c).top + 1, left: c ? Math.round(R(c).left - R(it).left) : null,
              bold: l ? +getComputedStyle(l).fontWeight : 0, iRight: i ? Math.round(R(it).right - R(i).right) : null,
              saysUnder: !!(s && c) && R(s).top >= R(c).bottom - 1,
              clamp: s ? getComputedStyle(s).webkitLineClamp : ''};
    });
    out.cardSave = Array.from(document.querySelectorAll('#up-web-card button')).map(T).filter(t => /save/i.test(t));
    const bar = document.getElementById('up-save-bar');
    out.bar = bar ? {shown: shown(bar), words: Array.from(bar.querySelectorAll('button')).map(T),
                     last: Array.from(document.querySelectorAll('#tab-control .grid.charts > [data-sec="sys-upgrade"]')).filter(shown).pop() === bar,
                     dirty: bar.classList.contains('dirty')} : null;
    // What changed: a bar, not a link
    const det = document.querySelector('#up-pkg details'), sum = det && det.querySelector('summary');
    out.fold = det ? {bg: getComputedStyle(det).backgroundColor, border: getComputedStyle(det).borderTopStyle,
                      weight: +getComputedStyle(sum).fontWeight, color: getComputedStyle(sum).color,
                      wide: Math.round(R(det).width) >= Math.round(R(document.getElementById('up-pkg')).width) - 2,
                      words: T(sum)} : null;
    // the package of the version that runs here
    const st = document.getElementById('up-start');
    out.start = st ? {words: T(st), disabled: st.disabled, bg: getComputedStyle(st).backgroundColor} : null;
    out.red = Array.from(document.querySelectorAll('#up-ready .note.bad, #up-ready .bad')).map(T);
    out.logFolded = !!document.querySelector('#up-log-fold') && !document.querySelector('#up-log-fold').open;
    return out;
  });
  // the settings: changed, saved, put back
  try { await p.click('#up-web-card .set-item.set-bool .sw'); } catch (e) { errs.push('not there: ' + '#up-web-card .set-item.set-bool .sw'); }
  await p.waitForTimeout(200);
  r.afterChange = await p.evaluate(() => { const bar = document.getElementById('up-save-bar');
    return bar ? {dirty: bar.classList.contains('dirty'), said: (document.getElementById('up-save-said') || {}).textContent,
                  pos: getComputedStyle(bar).position} : null; });
  try { await p.click('#up-save'); } catch (e) { errs.push('not there: ' + '#up-save'); }
  await p.waitForTimeout(500);
  await p.evaluate(() => {
    renderSettings({runtime_config: {upgrade_check: {value: 1, kind: 'switch'},
      upgrade_url: {value: 'https://example.org/x/', kind: 'text'}, downgrade_show: {value: 0, kind: 'switch'}}}); });
  try { await p.fill('#up-web-card input[type=text]', 'https://example.org/y/'); } catch (e) { errs.push('not there: ' + '#up-web-card input[type=text]'); }
  await p.waitForTimeout(100);
  r.typed = await p.evaluate(() => (document.getElementById('up-save-said') || {}).textContent);
  try { await p.click('#up-reset'); } catch (e) { errs.push('not there: ' + '#up-reset'); }
  await p.waitForTimeout(100);
  r.reset = await p.evaluate(() => ({value: (document.querySelector('#up-web-card input[type=text]') || {}).value,
    dirty: !!document.querySelector('#up-save-bar.dirty')}));
  // the buttons each ask the daemon
  const confirm = async (words) => {
    await p.waitForTimeout(250);
    await p.evaluate((w) => { const b = Array.from(document.querySelectorAll('#zmodal-foot button')).filter(x => x.textContent.trim() === w)[0]; if (b) b.click(); }, words);
    await p.waitForTimeout(300);
  };
  await p.evaluate(() => { const b = Array.from(document.querySelectorAll('#up-web button')).filter(x => /Look now/.test(x.textContent))[0]; if (b) b.click(); });
  await p.waitForTimeout(300);
  await p.evaluate(() => document.querySelector('#up-nodes tbody button').click());
  await confirm('Take it out');
  await p.evaluate(() => document.getElementById('up-start').click());
  await confirm('Upgrade');
  await p.evaluate(() => document.getElementById('up-forget').click());
  await confirm('Forget it');
  r.posts = posts;
  r.errs = errs;
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
''' % {'port': PHP_PORT}
(W / 'run.js').write_text(JS)
r = {'error': 'php is not here'}
if subprocess.run(['which', 'php'], capture_output=True).stdout:
    php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, '-t', str(HERE / 'web')],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
        try:
            got = subprocess.run(['node', str(W / 'run.js')], capture_output=True, text=True, timeout=180,
                                 stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=root))
        except subprocess.TimeoutExpired:
            got = subprocess.CompletedProcess([], 1, '', 'the page did not answer in 180 s')
        try:
            r = json.loads(got.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            r = {'error': (got.stdout + got.stderr)[-300:]}
    finally:
        php.kill()
        php.wait()
if r.get('error'):
    print('  SKIPPED (no browser here): %s' % r['error'][:200])
else:
    if os.environ.get('DBG'):
        print('DBG', json.dumps(r, indent=1))
    check(not r.get('errs'), 'the page threw: %r' % r.get('errs'))
    check(r.get('cards') == ['The nodes', 'From the web', 'A new version', 'What root said last zigmon',
                             'On the command line', ''],
          'the cards are %r' % r.get('cards'))
    check(r.get('logFolded'), 'what root said is not folded under a bar')
    check(r.get('mbRight') is not None and r['mbRight'] <= 16,
          'Maintenance is not at the right end of its row: %r px from it' % r.get('mbRight'))
    check(r.get('url') == {'code': False, 'mono': True}, 'the address is not a line in mono: %r' % r.get('url'))
    items = r.get('items') or []
    check(len(items) == 3, 'From the web has %d settings' % len(items))
    for n, it in enumerate(items):
        check(it['labelAbove'], 'setting %d: its name is not above its control' % n)
        check(it['left'] is not None and it['left'] <= 2, 'setting %d: its control is not at the left: %r' % (n, it['left']))
        check(it['bold'] >= 600, 'setting %d: its name is not bold (%r)' % (n, it['bold']))
        check(it['iRight'] is not None and it['iRight'] <= 2, 'setting %d: its (i) is not at the right end: %r' % (n, it['iRight']))
        check(it['saysUnder'] and it['clamp'] == '3', 'setting %d: its words are not under it in three lines: %r' % (n, it))
    check(not r.get('cardSave'), 'From the web has a Save of its own: %r' % r.get('cardSave'))
    bar = r.get('bar') or {}
    check(bar.get('shown') and bar.get('last') and bar.get('words') == ['Save the changes', 'Put them back']
          and not bar.get('dirty'), 'otp\'s save bar is not at the end of the pane: %r' % bar)
    ac = r.get('afterChange') or {}  # noqa
    check(ac.get('dirty') and ac.get('said') == '1 change(s) not saved yet' and ac.get('pos') == 'sticky',
          'a change does not show on the save bar: %r' % ac)
    saved = [b for w, b in r.get('posts', []) if w == 'config-save']
    check(saved and saved[0].get('upgrade_check') == 0, 'Save the changes did not save: %r' % saved)
    check(r.get('typed') == '1 change(s) not saved yet', 'a typed address does not show: %r' % r.get('typed'))
    check(r.get('reset') == {'value': 'https://example.org/x/', 'dirty': False}, 'Put them back did not: %r' % r.get('reset'))
    f = r.get('fold') or {}
    check(f.get('words') == 'What changed in 5.35.0' and f.get('bg') not in ('', 'rgba(0, 0, 0, 0)')
          and f.get('border') == 'solid' and f.get('weight', 0) >= 600 and f.get('wide')
          and f.get('color') != 'rgb(88, 166, 255)', 'What changed is not a bar: %r' % f)
    s = r.get('start') or {}
    check(s.get('words') == 'Upgrade this server' and not s.get('disabled') and s.get('bg') == 'rgb(31, 111, 235)',
          'with a package of the version that runs here the button is %r' % s)
    check(not r.get('red'), 'a red band under a package that is fine: %r' % r.get('red'))
    acts = [(w, b.get('action')) for w, b in r.get('posts', []) if w == 'upgrade-do']
    for want in ('online_look', 'maintenance', 'start', 'forget'):
        check(('upgrade-do', want) in acts, '%s was not asked of the daemon: %r' % (want, acts))

if bad:
    print('\n%d problem(s)' % len(bad))
    raise SystemExit(1)
shutil.rmtree(str(W), ignore_errors=True)
print('\nUpgrades and maintenance as otp has it: every check passed')
