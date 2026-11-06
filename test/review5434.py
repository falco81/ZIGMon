#!/usr/bin/env python3
"""5.43.4: Upgrades and maintenance as acme draws it, and "Your account" as
plexmon draws it. Fails on 5.43.3.

    python3 test/review5434.py
    REVIEW5434_RELEASE=5.43.3 python3 test/review5434.py   (the page of that
        release, from release/zigmon-5.43.3.tar.gz: its checks fail)
    SHOTS=dir also keeps the screenshots.

  * the real page (php -S) in Chromium at 1600 and 1194 wide, the daemon's
    answers stubbed, From the web in every state - nothing newer, a newer
    version (Look now, Upgrade to X now, Only fetch it), more than one newer
    version (which one picked from a list), looking, a look that failed, the
    older versions offered for going back, a package sent:
    - the buttons on one line, each 38 px tall, Upgrade filled blue;
    - the list of versions in that line too, as tall as the buttons and as
      wide as its words (not the whole card on a line of its own), drawn as
      the page's other lists are (the font, the weight, the background, the
      arrow), every version in it, nothing running out of it or the card;
    - the strip of what was found green (an error red), rounded;
    - beside the title: a dot for looking every day, a dot for the last look,
      and a circle that turns while it looks;
  * the account's popup, for a password account and a PIN account: "Your
    account", the round mark with the initials, the name, the badges (FULL
    ADMIN, LOCAL ACCOUNT or PIN), the headings WHAT YOU MAY DO, PASSKEYS -
    FACE ID, TOUCH ID and THE PERFORMANCE METER, Close at the right end of
    the footer beside what was there; a passkey renamed in its row - the
    name a box, focused and chosen; Enter keeps it (passkeys-do rename),
    Escape leaves it as it was and the popup open, nothing sent.

Port 19600 (php -S).
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
W = Path(tempfile.mkdtemp(prefix='zigmon-review5434-'))
PHP_PORT = 19600
SHOTS = os.environ.get('SHOTS', '')
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


WEB = HERE / 'web'
rel = os.environ.get('REVIEW5434_RELEASE', '')
if rel:
    with tarfile.open(str(HERE / 'release' / ('zigmon-%s.tar.gz' % rel))) as t:
        pre = 'zigmon-%s/web/' % rel
        for m in t.getmembers():
            if m.name == 'zigmon-%s/zigmon.py' % rel:
                (W / 'daemon').mkdir(exist_ok=True)
                (W / 'daemon' / 'zigmon.py').write_bytes(t.extractfile(m).read())
            if m.name.startswith(pre) and m.isfile():
                dst = W / 'web' / m.name[len(pre):]
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(t.extractfile(m).read())
    WEB = W / 'web'
    print('the page of %s' % rel)

JS = r'''
const { chromium } = require('playwright');
const port = @PORT@, SHOTS = @SHOTS@;
const now = Date.now() / 1000;
const url = 'https://github.com/falco81/ZIGMon/tree/main/release';
const m = {on: false};
const base = () => ({ok: true, version: '5.43.3', node: 'zigmon', helper: true, path_unit: true, ready: false, not_ready: [],
  status: {}, running: false, asked: false, back: {on: false}, maintenance: m, log: ['done'],
  nodes: [{name: 'zigmon', me: true, alive: true, version: '5.43.3', at: now - 4, since: now - 3600, maintenance: m}],
  web: {check: true, url: url, online: {at: now - 60, newest: {version: '5.43.3'}, here: '5.43.3', url: url}}, package: null});
const S = {
  none: d => d,
  newer: d => { d.web.online = {at: now - 1, newer: true, newest: {version: '5.44.0', url: url}, here: '5.43.3', url: url,
                newer_list: [{version: '5.44.0', url: url}]}; return d; },
  several: d => { d.web.online = {at: now - 1, newer: true, newest: {version: '5.45.1', url: url}, here: '5.43.3', url: url,
                newer_list: ['5.45.1', '5.45.0', '5.44.2', '5.44.0'].map(v => ({version: v, url: url}))}; return d; },
  looking: d => { d.web.busy = true; d.web.online = {}; return d; },
  failed: d => { d.web.online = {at: now - 30, error: 'the address did not answer: timed out after 20 s', here: '5.43.3', url: url}; return d; },
  back: d => { d.back = {on: true, ready: true, floor: '5.30.0', high: '5.43.3'};
    d.web.online = {at: now - 30, newest: {version: '5.43.3'}, here: '5.43.3', url: url,
      older_list: [{version: '5.43.2', ok: true}, {version: '5.43.1', ok: true}, {version: '5.29.0', ok: false, why: 'below 5.30.0'}]};
    return d; },
  package: d => { d.ready = true; d.package = {version: '5.44.0', signed_by: 'zigmon-release-1', bytes: 1843200, by: 'admin',
                  at: now - 300, newer: true, changelog: '## 5.44.0'}; return d; },
};
const measure = () => {
  const R = e => { const x = e.getBoundingClientRect(); return {l: x.left, r: x.right, t: x.top, b: x.bottom, w: x.width, h: x.height}; };
  const cs = e => getComputedStyle(e);
  const o = {};
  const card = document.getElementById('up-web-card'), rc = R(card);
  const kids = Array.from(document.querySelectorAll('#up-web .btnrow > *')).filter(e => e.getClientRects().length);
  o.kids = kids.map(e => ({tag: e.tagName, words: e.textContent.trim().slice(0, 40), h: Math.round(R(e).h), t: Math.round(R(e).t),
    w: Math.round(R(e).w), r: R(e).r, bg: cs(e).backgroundColor, ws: cs(e).whiteSpace}));
  o.cardRight = rc.r; o.cardW = rc.w;
  o.cardOver = card.scrollWidth > card.clientWidth + 1;
  o.pageOver = document.documentElement.scrollWidth > window.innerWidth + 1;
  const s = document.querySelector('#up-web > p.note');
  o.strip = s ? {cls: s.className, bg: cs(s).backgroundColor, br: cs(s).borderTopLeftRadius, pad: cs(s).paddingLeft} : null;
  const pick = document.querySelector('#up-web select');
  if (pick) {
    // isemon's line: the words, then the list after them, over the buttons
    const line = pick.closest('p'), words = line && line.querySelector('span'), row = document.querySelector('#up-web .btnrow');
    o.many = {line: !!line, words: words ? words.textContent.trim() : null, pickH: Math.round(R(pick).h), pickW: Math.round(R(pick).w),
      after: words ? R(pick).l >= R(words).r - 1 && Math.abs((R(pick).t + R(pick).b) / 2 - (R(words).t + R(words).b) / 2) < 4 : false,
      above: row ? R(pick).b <= R(row).t : false, scheme: cs(pick).colorScheme, border: cs(pick).borderTopColor,
      fsize: line ? cs(line).fontSize : null};
    const probe = zSelect([['a', 'a']], 'a'); document.body.appendChild(probe);
    const P = cs(probe), Q = cs(pick);
    o.pick = {n: pick.options.length, first: pick.options[0] && pick.options[0].textContent, value: pick.value,
      fs: Q.fontSize, fw: Q.fontWeight, ff: Q.fontFamily, bg: Q.backgroundColor, bgi: Q.backgroundImage, br: Q.borderTopLeftRadius,
      color: Q.color, probe: {fs: P.fontSize, fw: P.fontWeight, ff: P.fontFamily, bg: P.backgroundColor, bgi: P.backgroundImage, color: P.color},
      over: pick.scrollWidth > pick.clientWidth + 1, tab: pick.tabIndex};
    probe.remove();
  }
  const st = document.querySelector('#up-web-card > h2 .up-state');
  o.state = st ? {dots: st.querySelectorAll('.dot').length, spin: !!st.querySelector('.up-spin'),
    on: !!st.querySelector('.up-spin.on'), crit: !!st.querySelector('.dot.crit')} : null;
  o.title = (document.querySelector('#up-web-card > h2').textContent || '').replace(/About$/, '').trim();
  o.start = document.getElementById('up-start') ? !document.getElementById('up-start').disabled : null;
  return o;
};
(async () => {
  const b = await chromium.launch();
  const out = {pane: {}, popup: {}};
  for (const w of [1600, 1194]) {
    const p = await b.newPage({viewport: {width: w, height: 1000}});
    p.setDefaultTimeout(4000);
    let cur = base();
    const errs = [], posts = [];
    p.on('pageerror', e => errs.push(String(e)));
    await p.route(/\?api=/, (route, req) => {
      const what = new URL(req.url()).searchParams.get('api');
      if (req.method() === 'POST') posts.push([what, JSON.parse(req.postData() || '{}')]);
      let body = {ok: true};
      if (what === 'upgrade') body = cur;
      else if (what === 'upgrade-do') body = Object.assign({message: 'done'}, cur);
      else if (what === 'status') { route.fulfill({status: 500, contentType: 'application/json', body: '{"error":"stub"}'}); return; }
      route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
    });
    await p.goto('http://127.0.0.1:' + port + '/index.php#control/sys-upgrade');
    await p.waitForTimeout(1200);
    await p.evaluate(url => {
      LOCK.who = {name: 'admin', role: 'admin'};
      renderSettings({runtime_config: {upgrade_check: {value: 1, kind: 'switch'},
        upgrade_url: {value: url, kind: 'text'}, downgrade_show: {value: 1, kind: 'switch'}}});
      try { showTab('control'); } catch (e) {}
      try { showControlSection('sys-upgrade'); } catch (e) {}
    }, url);
    await p.waitForTimeout(800);
    for (const st of Object.keys(S)) {
      cur = S[st](base());
      await p.evaluate(d => drawUpgrade(d), cur);
      await p.waitForTimeout(200);
      out.pane[w + '-' + st] = await p.evaluate(measure);
      if (SHOTS) await p.locator(st === 'back' ? '#up-back-card' : (st === 'package' ? '#up-new-card' : '#up-web-card'))
        .screenshot({path: SHOTS + '/upgrade-' + w + '-' + st + '.png'}).catch(() => {});
    }
    // the list works: another version picked, the button says it, Upgrade asks for it
    cur = S.several(base());
    await p.evaluate(d => drawUpgrade(d), cur);
    await p.waitForTimeout(150);
    if (w === 1600) {
      try {
        await p.focus('#up-web select');
        await p.keyboard.press('ArrowDown');
        await p.waitForTimeout(100);
        out.picked = await p.evaluate(() => ({value: document.querySelector('#up-web select').value,
          up: Array.from(document.querySelectorAll('#up-web .btnrow button')).map(x => x.textContent.trim())}));
        await p.evaluate(() => Array.from(document.querySelectorAll('#up-web .btnrow button')).filter(x => /^Upgrade to/.test(x.textContent.trim()))[0].click());
        await p.waitForTimeout(250);
        await p.evaluate(() => { const x = Array.from(document.querySelectorAll('#zmodal-foot button')).filter(x => x.textContent.trim() === 'Upgrade')[0]; if (x) x.click(); });
        await p.waitForTimeout(300);
        out.asked = posts.filter(x => x[0] === 'upgrade-do').map(x => x[1]);
      } catch (e) { errs.push('the list: ' + e); }
    }
    out['errs' + w] = errs;
    await p.close();
  }
  // the account's popup
  for (const as of ['password', 'pin']) {
    const p = await b.newPage({viewport: {width: 1600, height: 1000}});
    p.setDefaultTimeout(4000);
    const errs = [], posts = [];
    p.on('pageerror', e => errs.push(String(e)));
    let keys = [{id: 'k1', label: 'iPad · 5. 11. 2026', host: 'zigmon.example.net', created: now - 86400, last_used: now - 3600}];
    await p.route(/\?api=/, (route, req) => {
      const what = new URL(req.url()).searchParams.get('api');
      let body = {ok: true};
      if (req.method() === 'POST') posts.push([what, JSON.parse(req.postData() || '{}')]);
      if (what === 'passkeys') body = {on: true, passkeys: keys, most: 20};
      else if (what === 'passkeys-do') {
        const q = JSON.parse(req.postData() || '{}');
        if (q.do === 'rename') keys = keys.map(k => k.id === q.id ? Object.assign({}, k, {label: q.name}) : k);
        body = {ok: true, passkeys: keys, on: true};
      } else if (what === 'status') { route.fulfill({status: 500, contentType: 'application/json', body: '{"error":"stub"}'}); return; }
      route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
    });
    await p.goto('http://127.0.0.1:' + port + '/index.php');
    await p.waitForTimeout(1000);
    await p.evaluate(as => {
      STATE.status = Object.assign(STATE.status || {}, {runtime_config: {perf_meter: {value: 1}}});
      LOCK.who = as === 'pin' ? {name: 'jana.novak', role: 'admin', kind: 'pin', until: Date.now() / 1000 + 900, left: 900}
        : {name: 'admin', role: 'admin'};
      document.getElementById('userbtn').click();
    }, as);
    await p.waitForSelector('#zmodal-body .pk-list[data-n]', {timeout: 5000}).catch(() => {});
    await p.waitForTimeout(300);
    const r = await p.evaluate(() => {
      const T = s => (s && s.textContent || '').replace(/\s+/g, ' ').trim();
      const U = s => getComputedStyle(s).textTransform === 'uppercase' ? T(s).toUpperCase() : T(s);
      const body = document.getElementById('zmodal-body'), av = body.querySelector('.acct-av');
      const foot = Array.from(document.querySelectorAll('#zmodal-foot .btn')).filter(x => x.getClientRects().length);
      const fr = document.getElementById('zmodal-foot').getBoundingClientRect();
      const close = foot.filter(x => T(x) === 'Close')[0];
      return {title: T(document.getElementById('zmodal-title')), x: !!document.getElementById('zmodal-x'),
        av: av ? {t: T(av), round: getComputedStyle(av).borderRadius === '50%', ring: getComputedStyle(av).borderTopStyle,
                  w: Math.round(av.getBoundingClientRect().width)} : null,
        name: body.querySelector('.acct-name') ? {t: T(body.querySelector('.acct-name')),
          mono: /mono|Menlo|Consolas/.test(getComputedStyle(body.querySelector('.acct-name')).fontFamily),
          bold: +getComputedStyle(body.querySelector('.acct-name')).fontWeight} : null,
        badges: Array.from(body.querySelectorAll('.acct-badges > *')).map(U),
        heads: Array.from(body.querySelectorAll('.acct-sec > h4')).map(U),
        lines: Array.from(body.querySelectorAll('.acct-sec')).map(x => getComputedStyle(x).borderTopStyle),
        foot: foot.map(T), closeRight: close ? Math.round(fr.right - close.getBoundingClientRect().right) : null,
        add: !!document.getElementById('pk-add'), pickers: !!body.querySelector('#hl-pickers'),
        body: T(body).slice(0, 300)};
    });
    if (SHOTS) await p.locator('#zmodal-box').screenshot({path: SHOTS + '/account-' + as + '.png'}).catch(() => {});
    const ren = '#zmodal-body .pk-list tbody tr td.acts .btn:first-child';
    try {
      await p.click(ren);
      await p.waitForTimeout(200);
      r.inline = await p.evaluate(() => {
        const i = document.querySelector('#zmodal-body .pk-list tbody tr td input.pk-rename');
        const ask = document.getElementById('askback');
        return i ? {focused: document.activeElement === i, chosen: i.selectionStart === 0 && i.selectionEnd === i.value.length,
                    value: i.value, other: !!(ask && !ask.hidden)} : {other: !!(ask && !ask.hidden)};
      });
      if (SHOTS) await p.locator('#zmodal-box').screenshot({path: SHOTS + '/account-' + as + '-rename.png'}).catch(() => {});
      await p.keyboard.press('Escape');
      await p.waitForTimeout(200);
      r.esc = await p.evaluate(() => ({open: !document.getElementById('zmodal').hidden,
        box: !!document.querySelector('#zmodal-body input.pk-rename'),
        name: ((document.querySelector('#zmodal-body .pk-list tbody td') || {}).textContent || '').trim()}));
      r.escPosts = posts.filter(x => x[0] === 'passkeys-do').length;
      await p.click(ren);
      await p.waitForTimeout(150);
      await p.keyboard.type('My iPad');
      await p.keyboard.press('Enter');
      await p.waitForTimeout(400);
      r.enter = await p.evaluate(() => ({open: !document.getElementById('zmodal').hidden,
        box: !!document.querySelector('#zmodal-body input.pk-rename'),
        name: ((document.querySelector('#zmodal-body .pk-list tbody td') || {}).textContent || '').trim()}));
    } catch (e) { errs.push('the rename: ' + String(e).slice(0, 200)); }
    r.posts = posts.filter(x => x[0] === 'passkeys-do').map(x => x[1]);
    r.errs = errs;
    out.popup[as] = r;
    await p.close();
  }
  // the performance meter (stubbed /api/perf): one phase, at once when back
  {
    const p = await b.newPage({viewport: {width: 1600, height: 1000}});
    p.setDefaultTimeout(4000);
    const errs = [];
    p.on('pageerror', e => errs.push(String(e)));
    const R = {at: 1000, cpu: 10, next_in: 3.2};
    let delay = 0, asks = 0;
    const answer = (q) => {
      const d = {ok: true, at: R.at, cpu: R.cpu, mem_used: 2e9, mem_total: 8e9, disk_rd: 1000, disk_wr: 2000,
                 net_rx: 3000, net_tx: 4000, cores: 4, load: [0.5, 0.4, 0.3], over_s: 5, next_in: R.next_in, every_s: 5};
      if (q.get('history') === '1') d.history = [0, 1, 2].map(i => ({at: R.at - 10 + i * 5, cpu: 5 + i, mem: 25, disk: 3000, net: 7000}));
      if (q.get('detail') === '1') d.detail = {cores: [0, 1, 2, 3].map(n => ({n: n, busy: 5 + n, mhz: 1200})), model: 'Test CPU',
        temps: {cpu: [], cores: {}, other: []}, disks: [], nics: [], mem: {total: 8e9, available: 6e9}, uptime: 1000, procs: 10};
      return d;
    };
    await p.route(/\?api=/, async (route, req) => {
      const u = new URL(req.url()), what = u.searchParams.get('api');
      if (what === 'perf') {
        asks++;
        const d = answer(u.searchParams);
        if (delay) await new Promise(ok => setTimeout(ok, delay));
        route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(d)}).catch(() => {});
        return;
      }
      if (what === 'status') { route.fulfill({status: 500, contentType: 'application/json', body: '{"error":"stub"}'}); return; }
      route.fulfill({status: 200, contentType: 'application/json', body: '{"ok":true}'});
    });
    const start = async () => {
      await p.waitForFunction(() => typeof perfSync === 'function');
      await p.evaluate(() => { STATE.status = Object.assign(STATE.status || {}, {runtime_config: {perf_meter: {value: 1}}}); perfSync(STATE.status); });
    };
    const graphs = () => p.evaluate(() => Array.from(document.querySelectorAll('#hload .hl-scroll, #hload-panel .hl-scroll')).map(g => {
      const c = getComputedStyle(g);
      return {panel: !!g.closest('#hload-panel'), dur: c.animationDuration, delay: c.animationDelay, name: c.animationName};
    }));
    const cpuText = () => p.evaluate(() => { const h = document.getElementById('hload'), v = h && h.querySelector('.hl-cpu .hl-v');
      return {shown: !!h && !h.hidden && h.getClientRects().length > 0, cpu: v ? v.textContent.trim() : null}; });
    const pf = {};
    try {
      await p.goto('http://127.0.0.1:' + port + '/index.php');
      await start();
      await p.waitForTimeout(700);
      R.at = 1001; R.cpu = 11;
      await p.evaluate(() => hloadTick(true)); await p.waitForTimeout(300);
      await p.evaluate(() => hloadPanelOpen('cpu', document.querySelector('#hload [data-k="cpu"]')));
      await p.waitForTimeout(400);
      R.at = 1002; R.cpu = 12; R.next_in = 4.0;
      await p.evaluate(() => hloadTick(true)); await p.waitForTimeout(300);
      pf.g1 = await graphs();
      R.at = 1003; R.cpu = 13; R.next_in = 2.5;
      await p.evaluate(() => hloadTick(true)); await p.waitForTimeout(300);
      pf.g2 = await graphs();
      // away and back: the numbers at once, the answer held up 1.5 s
      delay = 1500;
      await p.evaluate(() => {
        Object.defineProperty(document, 'hidden', {value: true, configurable: true});
        document.dispatchEvent(new Event('visibilitychange'));
      });
      await p.evaluate(() => { const h = document.getElementById('hload'); if (h) { hlClear(h); h.hidden = true; } });  // as a tab put away may be
      await p.waitForTimeout(200);
      await p.evaluate(() => {
        Object.defineProperty(document, 'hidden', {value: false, configurable: true});
        document.dispatchEvent(new Event('visibilitychange'));
      });
      await p.waitForTimeout(100);
      pf.back = await cpuText();
      pf.backGraphs = (await graphs()).length;
      await p.waitForTimeout(1600);
      // the panel shut and opened again: what it had, at once
      await p.evaluate(() => hloadPanelClose());
      await p.evaluate(() => hloadPanelOpen('cpu', document.querySelector('#hload [data-k="cpu"]')));
      await p.waitForTimeout(80);
      pf.panel = await p.evaluate(() => { const x = document.getElementById('hload-panel');
        return x ? {shown: !x.hidden, words: (x.textContent || '').slice(0, 300)} : null; });
      await p.waitForTimeout(1600);
      await p.evaluate(() => hloadPanelClose());
      // loaded again: the numbers drawn before the first answer comes
      delay = 1500;
      await p.reload({waitUntil: 'domcontentloaded'});
      await start();
      await p.waitForTimeout(250);
      pf.reload = await cpuText();
      await p.waitForTimeout(1700);
      pf.reloadAfter = await cpuText();
    } catch (e) { errs.push('the meter: ' + String(e).slice(0, 200)); }
    pf.errs = errs;
    out.perf = pf;
    await p.close();
  }
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''.replace('@PORT@', str(PHP_PORT)).replace('@SHOTS@', json.dumps(SHOTS))

(W / 'run.js').write_text(JS)
r = {'error': 'php is not here'}
if subprocess.run(['which', 'php'], capture_output=True).stdout:
    php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, '-t', str(WEB)],
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
            got = subprocess.run(['node', str(W / 'run.js')], capture_output=True, text=True, timeout=240,
                                 stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=root))
        except subprocess.TimeoutExpired:
            got = subprocess.CompletedProcess([], 1, '', 'the page did not answer in 240 s')
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
    print('Upgrades and maintenance, every state, 1600 and 1194 wide')
    for w in (1600, 1194):
        check(not r.get('errs%d' % w), '%d: the page threw: %r' % (w, r.get('errs%d' % w)))
        for st, m in sorted((k.split('-', 1)[1], v) for k, v in r['pane'].items() if k.startswith('%d-' % w)):
            k = '%d %s' % (w, st)
            kids = m.get('kids') or []
            check(m.get('title') == 'From the web', '%s: the title is %r' % (k, m.get('title')))
            check(kids and len(set(x['t'] for x in kids)) == 1,
                  '%s: the buttons are not on one line: %r' % (k, [(x['words'], x['t']) for x in kids]))
            check(all(x['h'] == 38 for x in kids), '%s: not all 38 px tall: %r' % (k, [(x['words'], x['h']) for x in kids]))
            check(all(x['r'] <= m['cardRight'] for x in kids) and not m.get('cardOver') and not m.get('pageOver'),
                  '%s: something runs out of the card or the page' % k)
            stt = m.get('state') or {}
            check(stt.get('dots') == 2 and stt.get('spin'), '%s: no dots and circle beside the title: %r' % (k, m.get('state')))
            check(bool(stt.get('on')) == (st == 'looking'), '%s: the circle turns %r' % (k, stt.get('on')))
            s = m.get('strip') or {}
            if st in ('newer', 'several'):
                words = [x['words'] for x in kids]
                check(words[0] == 'Look now' and any(x.startswith('Upgrade to 5.4') for x in words) and words[-1] == 'Only fetch it',
                      '%s: the buttons are %r' % (k, words))
                up = [x for x in kids if x['words'].startswith('Upgrade to')][0]
                check(up['bg'] == 'rgb(31, 111, 235)', '%s: Upgrade is not filled blue: %r' % (k, up['bg']))
                check('good' in s.get('cls', '') and s.get('bg') == 'rgba(63, 185, 80, 0.12)' and s.get('br') == '10px',
                      '%s: the strip of what was found: %r' % (k, s))
            if st == 'failed':
                check('bad' in s.get('cls', '') and s.get('bg') not in ('', 'rgba(0, 0, 0, 0)') and stt.get('crit'),
                      '%s: a failed look is not red: %r %r' % (k, s, stt))
            if st == 'several':
                pk = m.get('pick') or {}
                mn = m.get('many') or {}
                check(mn.get('line') and mn.get('words') == '4 versions newer than this one are there - put in:'
                      and mn.get('after') and mn.get('above'),
                      '%s: not isemon\'s line (the words, then the list, over the buttons): %r' % (k, mn))
                check(mn.get('pickH') == 38 and 'dark' in (mn.get('scheme') or '') and mn.get('border') != 'rgb(38, 44, 55)',
                      '%s: the list is not as tall as a button, bordered, its open list dark: %r' % (k, mn))
                check([x['words'] for x in kids] == ['Look now', 'Upgrade to 5.45.1 now', 'Only fetch it'],
                      '%s: the buttons under it are %r' % (k, [x['words'] for x in kids]))
                check(pk.get('n') == 4 and pk.get('first') == 'zigmon 5.45.1 (the newest)' and pk.get('value') == '5.45.1',
                      '%s: the versions in the list: %r' % (k, pk))
                pr = pk.get('probe') or {}
                check(all(pk.get(f) == pr.get(f) for f in ('fs', 'fw', 'ff', 'bg', 'bgi', 'color')) and pk.get('br') == '10px',
                      '%s: the list is not drawn as the page\'s other lists: %r' % (k, pk))
                check(mn.get('pickW', 9999) < m['cardW'] / 3 and not pk.get('over'),
                      '%s: the list is not as wide as its words (%r of %r)' % (k, mn.get('pickW'), m['cardW']))
                check(pk.get('tab', -1) >= 0, '%s: the list cannot be reached with the keyboard' % k)
            if st == 'looking':
                check(kids and kids[0]['words'] == 'Look now', '%s: %r' % (k, kids))
            if st == 'package':
                check(m.get('start') is True, '%s: Upgrade this server is not offered' % k)
    pk = r.get('picked') or {}
    check(pk.get('value') == '5.45.0' and 'Upgrade to 5.45.0 now' in pk.get('up', []),
          'another version picked from the list with the keyboard: %r' % pk)
    asked = [x for x in r.get('asked') or [] if x.get('action') == 'online_get']
    check(asked and asked[-1].get('version') == '5.45.0' and asked[-1].get('start'),
          'Upgrade did not ask for the version picked: %r' % r.get('asked'))

    print('Your account, a password account and a PIN account')
    for as_, kind, ini, name in (('password', 'LOCAL ACCOUNT', 'AD', 'admin'), ('pin', 'PIN', 'JN', 'jana.novak')):
        p = r['popup'].get(as_) or {}
        k = 'the popup of a %s account' % as_
        check(not p.get('errs'), '%s: the page threw: %r' % (k, p.get('errs')))
        check(p.get('title') == 'Your account' and p.get('x'), '%s: the title is %r' % (k, p.get('title')))
        av = p.get('av') or {}
        check(av.get('t') == ini and av.get('round') and av.get('ring') == 'solid' and av.get('w', 0) >= 40,
              '%s: no round mark with the initials %s: %r' % (k, ini, p.get('av')))
        nm = p.get('name') or {}
        check(nm.get('t') == name and nm.get('mono') and nm.get('bold', 0) >= 600, '%s: the name: %r' % (k, nm))
        check(p.get('badges') == ['FULL ADMIN', kind], '%s: the badges are %r' % (k, p.get('badges')))
        check(p.get('heads') == ['WHAT YOU MAY DO', 'PASSKEYS - FACE ID, TOUCH ID', 'THE PERFORMANCE METER'],
              '%s: the headings are %r' % (k, p.get('heads')))
        check(p.get('lines') and all(x == 'solid' for x in p['lines']), '%s: the sections have no line over them' % k)
        want = ['Lock now', 'Change PIN', 'Accounts', 'Close'] if as_ == 'pin' else ['Sign out', 'Change password', 'Accounts', 'Close']
        check(p.get('foot') == want and p.get('closeRight') is not None and p['closeRight'] <= 30,
              '%s: the footer is %r (Close %r px from the right)' % (k, p.get('foot'), p.get('closeRight')))
        check(p.get('add') and p.get('pickers') and 'Administrator' in p.get('body', ''),
              '%s: something it had is gone: %r' % (k, p))
        i = p.get('inline') or {}
        check(i.get('focused') and i.get('chosen') and i.get('value') == 'iPad · 5. 11. 2026' and not i.get('other'),
              '%s: the passkey is not renamed in its row: %r' % (k, i))
        e = p.get('esc') or {}
        check(e.get('open') and not e.get('box') and e.get('name') == 'iPad · 5. 11. 2026' and p.get('escPosts') == 0,
              '%s: Escape did not leave the name as it was (and the popup open): %r' % (k, e))
        n = p.get('enter') or {}
        check(n.get('open') and not n.get('box') and n.get('name') == 'My iPad'
              and p.get('posts') == [{'do': 'rename', 'id': 'k1', 'name': 'My iPad', 'owner': ''}],
              '%s: Enter did not keep the name: %r %r' % (k, n, p.get('posts')))

    print('The performance meter: one phase, and at once when back')
    pf = r.get('perf') or {}
    check(not pf.get('errs'), 'the meter: the page threw: %r' % pf.get('errs'))
    for g, nxt in (('g1', 4.0), ('g2', 2.5)):
        gs = pf.get(g) or []
        want = '%gs' % round(2 * (nxt + 0.35), 3)
        check(len([x for x in gs if not x['panel']]) >= 4 and any(x['panel'] for x in gs),
              'the meter (%s): not the four graphs and a panel\'s: %r' % (g, gs))
        check(gs and len(set((x['dur'], x['delay']) for x in gs)) == 1,
              'the meter (%s): the graphs are not in one phase: %r' % (g, sorted(set((x['dur'], x['delay']) for x in gs))))
        check(gs and all(x['dur'] == want for x in gs),
              'the meter (%s): the slide does not last to the next reading (next_in %s: %s wanted): %r'
              % (g, nxt, want, sorted(set(x['dur'] for x in gs))))
    check((pf.get('back') or {}).get('shown') and (pf.get('back') or {}).get('cpu') == '13 %' and pf.get('backGraphs', 0) >= 4,
          'the meter: back on the page, the numbers were not there at once: %r' % pf.get('back'))
    pn = pf.get('panel') or {}
    check(pn.get('shown') and 'reading…' not in pn.get('words', '') and 'Test CPU' in pn.get('words', ''),
          'the meter: a panel opened again did not show what it had at once: %r' % pn)
    check((pf.get('reload') or {}).get('shown') and (pf.get('reload') or {}).get('cpu') == '13 %',
          'the meter: loaded again, nothing was drawn before the first answer: %r' % pf.get('reload'))
    check((pf.get('reloadAfter') or {}).get('cpu') == '13 %', 'the meter: after the first answer: %r' % pf.get('reloadAfter'))

# ---- the daemon: a page coming back is answered at once ------------------------
print('The performance meter: the daemon answers at once from what it kept')
(W / 'etc').mkdir(exist_ok=True)
(W / 'etc' / 'config.json').write_text(json.dumps({'db_file': str(W / 'state' / 'perf.db')}))
os.environ.update(ZIGMON_STATE=str(W / 'state'), ZIGMON_CONFIG=str(W / 'etc' / 'config.json'), ZIGMON_NO_SERVICES='1',
                  ZIGMON_FS_ROOT=str(W))
(W / 'state').mkdir(exist_ok=True)
sys.path.insert(0, str(W / 'daemon') if (W / 'daemon' / 'zigmon.py').exists() else str(HERE))
sys.argv = ['zigmon']
try:
    import zigmon                                       # noqa: E402
    zigmon.CONFIG['perf_meter'] = 1
    store = zigmon.Storage(str(W / 'state' / 'perf.db'))
    zigmon.PERF_STORE = store
    node = socket.gethostname().split('.')[0] or 'this machine'
    old = time.time() - 120
    with zigmon.PERF_LOCK:
        zigmon.PERF_LAST.update(at=old, raw={'at': old}, out={'at': round(old, 3), 'cpu': 42.0, 'mem_used': 1, 'mem_total': 4,
                                                             'cores': 4})
    t0 = time.time()
    got = zigmon.perf_load()
    took = time.time() - t0
    check(took < 0.3 and got.get('cpu') == 42.0 and got.get('at') == round(old, 3) and got.get('next_in', 9) <= 1.5,
          'the watching ended, a page coming back waited %.2f s for %r' % (took, {k: got.get(k) for k in ('cpu', 'at', 'next_in')}))
    zigmon.perf_forget()
    w_ = zigmon.PERF_WATCH['thread']
    if w_ is not None:
        w_.join(10)
    try:
        store.flush()
    except Exception:                                   # noqa: BLE001
        pass
    store._write_perf(node, old, json.dumps({'cpu': 37.5, 'mem_used': 2, 'mem_total': 8, 'disk_rd': 1, 'disk_wr': 2,
                                             'net_rx': 3, 'net_tx': 4, 'load': [0.1, 0.1, 0.1]}))
    t0 = time.time()
    got = zigmon.perf_load()
    took = time.time() - t0
    check(took < 0.3 and got.get('cpu') == 37.5 and got.get('mem_total') == 8,
          'the daemon started again, the first ask waited %.2f s and was answered %r (the row kept: cpu 37.5)'
          % (took, {k: got.get(k) for k in ('cpu', 'mem_total', 'at')}))
    time.sleep(1.6)
    fresh = zigmon.perf_load()
    check('cpu' in fresh and not fresh.get('stale') and fresh.get('at', 0) > old + 60,
          'the reading after it is not a fresh one: %r' % {k: fresh.get(k) for k in ('cpu', 'at', 'stale')})
    zigmon.perf_forget()
    w_ = zigmon.PERF_WATCH['thread']
    if w_ is not None:
        w_.join(10)
    try:
        store.flush()
    except Exception:                                   # noqa: BLE001
        pass
except Exception as e:                                  # noqa: BLE001
    check(False, 'the daemon\'s checks broke off: %r' % e)

if bad:
    print('\n%d problem(s)' % len(bad))
    shutil.rmtree(str(W), ignore_errors=True)
    raise SystemExit(1)
shutil.rmtree(str(W), ignore_errors=True)
print('\nUpgrades and maintenance as acme, Your account as plexmon: every check passed')
