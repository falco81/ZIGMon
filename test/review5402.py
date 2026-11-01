#!/usr/bin/env python3
"""5.40.2: Certificates from acme drawn as ai 1.0.60 draws the same card - its
state a tag in the title, its words whole (three lines at a phone's width),
the two switches with their words under them, then the three tiles acme is
given (a click copies one), the pairing in one row with the code waiting,
Paired with, What acme sees here and the last push in a line; an acme to
forget waits for Save settings at the end of the card, with Keep it; the
code's popup and the key's popup as ai has them. The real page (php -S) in
Chromium, the card's answer handed to it. Fails on 5.40.1.

    python3 test/review5402.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import time

HERE = Path(__file__).resolve().parent.parent
PORT = 19612
W = Path(tempfile.mkdtemp(prefix='zigmon-review5402-check-'))
if not subprocess.run(['which', 'php'], capture_output=True).stdout:
    print('  SKIPPED: no php here')
    sys.exit(0)
js = r'''
const { chromium } = require('playwright');
const now = () => Math.floor(Date.now() / 1000);
function view(on) {
  const t = now();
  const cur = {fingerprint: 'a1b2c3d4e5f60718293a4b5c6d7e8f90', not_before: t - 20 * 86400, not_after: t + 70 * 86400,
               issuer: 'CN=R11,O=Let\'s Encrypt,C=US', names: ['house.example.org'], key_type: 'ec-256',
               alt: {fingerprint: 'ffeeddccbbaa99887766554433221100', not_after: t + 70 * 86400, key_type: 'rsa-2048'}};
  return {ok: true, on: on, other_names: false, app: 'zigmon', app_id: 'app-3f9c2a71d0b84e15',
          enc_key: 'q8V2mXr4bLz7Tn1Kc5Wd9Hf3Jg6Ys0Pa2Ue8Ri4Oo1M=', node: 'house', crypto: 'cryptography',
          url: 'https://house.example.org/', keys_most: 8, slots_error: '',
          keys: [{key_id: '56475aa75463474c', name: 'acme 1.0.5 on acme1', how: 'paired with a code', by: 'jan',
                  at: t - 3 * 86400, last: t - 300}],
          pairing: {until: t + 720, tries_left: 4, tries: 1},
          slots: [{id: 'node:house', kind: 'node', title: 'the dashboard', names: ['house.example.org'], current: cur,
                   managed_by: 'own-acme', installable: true, dual: true, how: 'ACME'},
                  {id: 'broker', kind: 'other', title: 'the MQTT broker (8883)', names: ['house.example.org'],
                   current: Object.assign({}, cur, {alt: null}), managed_by: 'follows:node:house', installable: false},
                  {id: 'front', kind: 'front', title: 'the server in front', names: ['house.example.org'],
                   current: Object.assign({}, cur, {alt: null}), managed_by: 'follows:node:house', installable: false}],
          last: {at: t - 300, acme: 'acme 1.0.5 on acme1', key_id: '56475aa75463474c', said: 'already there for node:house'}};
}
async function open(b, width, on) {
  const p = await b.newPage({viewport: {width: width, height: 1000}});
  p.setDefaultTimeout(15000);
  p.on('pageerror', e => {});
  p.posts = [];
  p.on('request', r => { if (r.method() === 'POST') p.posts.push((r.url() + ' ' + (r.postData() || '')).slice(0, 300)); });
  await p.route(/\?api=acmepush/, async r => {
    const pd = r.request().postData(), body = pd ? JSON.parse(pd) : {};
    const d = view(on);
    if (body.action === 'code') d.code = 'K7QM-3WXP-9TRH-ZD4B';
    await r.fulfill({contentType: 'application/json', body: JSON.stringify(d)});
  });
  await p.goto('http://127.0.0.1:%(port)d/index.php#control/sys-certs');
  await p.waitForTimeout(1200);
  await p.evaluate((on) => {
    LOCK.who = {name: 'jan', role: 'admin'};
    document.body.classList.remove('locked');
    SETTINGS.dirty = false;
    renderSettings({runtime_config: {cert_push: {value: on ? 1 : 0, kind: 'switch'},
                                     cert_push_other_names: {value: 0, kind: 'switch'}}});
    try { showControlSection('sys-certs'); } catch (e) {}
    let up = document.getElementById('push-card');
    while (up) { if (getComputedStyle(up).display === 'none') { up.hidden = false; up.style.display = 'block'; } up = up.parentElement; }
    loadPush();
  }, on);
  await p.waitForSelector('#push-box', {timeout: 10000, state: 'attached'});
  await p.waitForTimeout(500);
  return p;
}
(async () => {
  const b = await chromium.launch();
  const out = {};
  const p = await open(b, 1600, true);
  out.wide = await p.evaluate(() => {
    const card = document.getElementById('push-card'), box = document.getElementById('push-box');
    const r = e => e ? e.getBoundingClientRect() : null;
    const tag = card.querySelector(':scope > h2 .tag');
    const items = Array.from(card.querySelectorAll('#set-host-sys-certs .set-item'));
    const sw = items.map(it => { const l = it.querySelector('label'), s = it.querySelector('.sw'), w = it.querySelector('.set-says');
      return {label: l.childNodes[0].textContent.trim(), above: !!(s && r(l).bottom <= r(s).top + 1), says: w ? w.textContent : '',
              under: !!(w && s && r(s).bottom <= r(w).top + 1), weight: getComputedStyle(l).fontWeight}; });
    // the parts of the card in their order, from the top
    const order = Array.from(card.querySelectorAll(':scope > h2, :scope > p.note, #set-host-sys-certs, #push-box .facts, ' +
      '#push-box > .btnrow, #push-box h4, #push-box .scroll, #push-last, :scope > .set-bar'))
      .map(e => e.matches('h4') ? 'h4:' + e.textContent : (e.id || e.className.split(' ')[0] || e.tagName));
    const th = s => Array.from(box.querySelectorAll('.scroll')[s].querySelectorAll('th')).map(t => t.textContent);
    const row = (s, n) => Array.from(box.querySelectorAll('.scroll')[s].querySelectorAll('tbody tr')[n].children).map(t => t.textContent);
    const pair = document.getElementById('push-pair');
    const btns = Array.from(box.querySelectorAll('.btnrow > *')).map(e => e.textContent.trim());
    return {tag: tag ? tag.textContent + '|' + tag.className : null, folded: !!card.querySelector(':scope > h2 .card-info'),
            note: (card.querySelector(':scope > p.note') || {}).textContent || '', sw: sw,
            tiles: Array.from(box.querySelectorAll('.facts .fact')).map(f => f.querySelector('.k').textContent + '=' +
              f.querySelector('.v').textContent + (f.classList.contains('wide') ? ' (wide)' : '') +
              (f.classList.contains('copyable') ? ' (copies)' : '')),
            order: order, btns: btns, pairBg: getComputedStyle(pair).backgroundColor, pairH: r(pair).height,
            th1: th(0), th2: th(1), row1: row(0, 0), row2: row(1, 0), last: (document.getElementById('push-last') || {}).textContent,
            lastGood: !!(document.getElementById('push-last') || {classList: {contains: () => false}}).classList.contains('good'),
            day: (box.querySelector('td .day') || {}).textContent || ''};
  });
  // a tile copies what it holds
  await p.evaluate(() => { window.__copied = []; copyText = function (t) { window.__copied.push(t); }; });
  await p.click('#push-box .facts .fact:nth-child(2)');
  console.error('step copied');
  out.copied = await p.evaluate(() => window.__copied.slice());
  // an acme to forget waits for Save settings; Keep it takes it back
  p.posts.length = 0;
  await p.click('#push-box .push-forget');
  await p.waitForTimeout(400);
  console.error('step marked');
  out.marked = await p.evaluate(() => ({gone: !!document.querySelector('#push-box tr.push-gone'),
    says: (document.querySelector('#push-box tr.push-gone .rowtools') || {}).textContent || '',
    note: document.querySelector('#push-card .set-note-alt').textContent}));
  await p.click('#push-box .push-keep');
  await p.waitForTimeout(300);
  console.error('step kept');
  out.kept = await p.evaluate(() => !document.querySelector('#push-box tr.push-gone') && !!document.querySelector('#push-box .push-forget'));
  out.postsBeforeSave = p.posts.slice();
  await p.click('#push-box .push-forget');
  await p.evaluate(() => { window.__saved = 0; document.getElementById('settings-save').onclick = function () { window.__saved++; }; });
  await p.click('#push-card .set-save-alt');
  await p.waitForTimeout(1200);
  console.error('step postsOnSave');
  out.postsOnSave = p.posts.slice();
  out.savedSettings = await p.evaluate(() => window.__saved);
  // the code's popup
  await p.click('#push-pair');
  await p.waitForSelector('#push-code');
  console.error('step code');
  out.code = await p.evaluate(() => ({title: document.getElementById('zmodal-title').textContent,
    size: getComputedStyle(document.getElementById('push-code')).fontSize,
    tiles: Array.from(document.querySelectorAll('#zmodal-body .fact .k')).map(t => t.textContent),
    help: (document.querySelector('#zmodal-body .btnhelp') || {}).textContent || '',
    copies: document.getElementById('push-code').classList.contains('copyable')}));
  await p.evaluate(() => closeZModal());
  await p.click('#push-paste');
  await p.waitForSelector('#push-key');
  await p.waitForTimeout(500);
  console.error('step paste');
  out.paste = await p.evaluate(() => ({title: document.getElementById('zmodal-title').textContent,
    labels: Array.from(document.querySelectorAll('#zmodal-body .set-item > label')).map(t => t.textContent),
    buttons: Array.from(document.querySelectorAll('#zmodal-foot .btn')).map(t => t.textContent.trim()),
    width: Math.round(document.getElementById('zmodal-box').getBoundingClientRect().width)}));
  console.error('step closing');
  await p.close();
  console.error('step closed');
  // switched off: the switch alone, the second one only while it is on; a click sends nothing
  const q = await open(b, 1600, false);
  console.error('step off');
  out.off = await q.evaluate(() => ({tag: (document.querySelector('#push-card > h2 .tag') || {}).textContent,
    empty: !document.getElementById('push-box').children.length,
    other: !!document.querySelector('#set-host-sys-certs input[data-k="cert_push_other_names"]').closest('.set-item').hidden}));
  q.posts.length = 0;
  await q.click('#set-host-sys-certs .set-item:not([hidden]) .sw');
  await q.waitForTimeout(500);
  console.error('step offClick');
  out.offClick = {posts: q.posts.slice(), other: await q.evaluate(() =>
    !document.querySelector('#set-host-sys-certs input[data-k="cert_push_other_names"]').closest('.set-item').hidden)};
  await q.close();
  // a phone: the words in three lines, a click opens them; nothing wider than the card
  const n = await open(b, 420, true);
  console.error('step narrow');
  out.narrow = await n.evaluate(() => { const c = document.getElementById('push-card'), t = document.getElementById('push-note');
    return {cut: t.classList.contains('cut'), lines: Math.round(t.clientHeight / parseFloat(getComputedStyle(t).lineHeight)),
            page: document.documentElement.scrollWidth <= window.innerWidth}; });
  await n.close();
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); process.exit(0); });
''' % {'port': PORT}
(W / 'run.js').write_text(js)
got = None
for attempt in range(3):
    php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PORT, '-t', str(HERE / 'web')], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                           env=dict(os.environ, PHP_CLI_SERVER_WORKERS='4'))
    try:
        for _ in range(50):
            try:
                socket.create_connection(('127.0.0.1', PORT), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        if php.poll() is not None:              # the port is somebody else's for a moment
            time.sleep(2)
            continue
        root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
        try:
            got = subprocess.run(['node', str(W / 'run.js')], capture_output=True, text=True, timeout=240,
                                 stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=root))
        except subprocess.TimeoutExpired as e:
            print('  FAILED: Chromium did not finish: %s' % (e.stderr or b'')[-300:])
            sys.exit(1)
        break
    finally:
        php.kill()
        php.wait()
try:
    out = json.loads(got.stdout.strip().splitlines()[-1])
except (ValueError, IndexError, AttributeError):
    out = {'error': ((got.stdout + got.stderr) if got else 'php -S did not start')[-300:]}
if out.get('error') and ('Executable doesn' in out['error'] or 'Cannot find module' in out['error']):
    print('  SKIPPED (no browser here): %s' % out['error'][:200])
    sys.exit(0)
if out.get('error'):
    print('  FAILED: the card in Chromium: %s' % out['error'][:400])
    print('review5402: FAILED')
    sys.exit(1)
bad = []


def check(ok, words):
    if not ok:
        bad.append(words)


w = out['wide']
check(w['tag'] and w['tag'].startswith('on - paired|') and ' ok' in w['tag'], 'the state is not a tag in the title: %r' % w['tag'])
check(not w['folded'] and w['note'].startswith('acme, the certificate manager, can give this server its certificate'),
      'the card\'s words are not said whole, as ai says them: %r' % w['note'][:80])
check([s['label'] for s in w['sw']] == ['Take certificates from acme', 'Take certificates of other names'],
      'the switches: %r' % w['sw'])
check(all(s['above'] and s['under'] and s['weight'] == '650' for s in w['sw']),
      'each switch is not its name in bold over it and its words under it: %r' % w['sw'])
check(w['sw'] and w['sw'][0]['says'] == 'Off: hello says only that it is off, and nothing is taken.'
      and '(house.example.org)' in w['sw'][1]['says'], 'the words under the switches: %r' % w['sw'])
check(w['order'] == ['H2', 'push-note', 'set-host-sys-certs', 'facts', 'btnrow',
                     'h4:Paired with', 'scroll', 'h4:What acme sees here', 'scroll', 'push-last', 'btnrow'],
      'the parts of the card are not in ai\'s order: %r' % w['order'])
check(w['tiles'] == ['The address for acme=https://house.example.org/ (wide) (copies)',
                     'This server’s id=app-3f9c2a71d0b84e15 (copies)',
                     'Its sealing key (X25519)=q8V2mXr4bLz7Tn1Kc5Wd9Hf3Jg6Ys0Pa2Ue8Ri4Oo1M= (wide) (copies)'],
      'the three tiles: %r' % w['tiles'])
check(out['copied'] == ['app-3f9c2a71d0b84e15'], 'a click on a tile does not copy it: %r' % out['copied'])
check(len(w['btns']) == 4 and w['btns'][0] == 'Pair with an acme' and w['btns'][1] == 'Take it back'
      and w['btns'][2].startswith('A code waits until ') and w['btns'][2].endswith(' (1 wrong so far).')
      and w['btns'][3] == 'Or paste acme’s key…', 'the pairing row: %r' % w['btns'])
check(w['pairBg'] == 'rgb(31, 111, 235)' and round(w['pairH']) == 38, 'Pair with an acme is not ai\'s blue button of 38 px: %r %r'
      % (w['pairBg'], w['pairH']))
check(w['th1'] == ['acme', 'Key', 'Since', 'How', ''] and w['th2'] == ['Slot', 'Names', 'Now', 'Until', 'Looked after by'],
      'the tables\' columns: %r %r' % (w['th1'], w['th2']))
check(w['row2'][0] == 'node:house' and w['row2'][2] == 'R11 + rsa-2048' and w['row2'][4] == 'Automatic certificates',
      'what acme sees here: %r' % w['row2'])
check(w['row1'][0] == 'acme 1.0.5 on acme1' and w['row1'][4] == 'Forget it' and len(w['day']) == 11,
      'Paired with: %r (day %r)' % (w['row1'], w['day']))
check(w['lastGood'] and (w['last'] or '').startswith('The last push: acme 1.0.5 on acme1 · 5 min ago · '),
      'the last push in one line: %r' % w['last'])
m = out['marked']
check(m['gone'] and 'forgotten when saved' in m['says'] and m['note'] == 'Unsaved changes',
      'Forget it does not wait for Save settings: %r' % m)
check(out['kept'], 'Keep it does not take the forgetting back')
check(not out['postsBeforeSave'], 'Forget it was sent before Save settings: %r' % out['postsBeforeSave'])
check(any('acmepush-do' in x and '"forget"' in x and '56475aa75463474c' in x for x in out['postsOnSave']),
      'Save settings did not forget the acme marked: %r' % out['postsOnSave'])
check(out['savedSettings'] == 0, 'Save settings saved the settings though none was changed: %r' % out['savedSettings'])
c = out['code']
check(c['title'] == 'Pair with an acme' and c['size'] == '30px' and c['copies'] and
      c['tiles'] == ['The address for acme', 'Valid until'] and c['help'] == 'A click on the code or the address copies it.',
      'the code\'s popup: %r' % c)
s = out['paste']
check(s['title'] == 'Paste acme’s key' and s['labels'] == ['acme’s key', 'A name for it'] and
      s['buttons'] == ['Close', 'Take this key'] and s['width'] == 560, 'the key\'s popup: %r' % s)
o = out['off']
check(o['tag'] == 'off' and o['empty'] and o['other'], 'switched off, the card is not the switch alone: %r' % o)
check(not out['offClick']['posts'] and out['offClick']['other'],
      'switching on: sent at once, or the second switch not shown: %r' % out['offClick'])
nw = out['narrow']
check(nw['cut'] and nw['lines'] == 3 and nw['page'], 'at a phone\'s width: %r' % nw)
for b in bad:
    print('  FAILED: ' + b)
print('review5402: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
sys.exit(1 if bad else 0)
