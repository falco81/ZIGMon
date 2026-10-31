#!/usr/bin/env python3
"""5.36.2: the backups to other machines look and work as plexmon 2.5.3's
Settings -> Backups.

The real page (php -S) in Chromium, the daemon's answers stubbed:
  * the pane's head says Backups, its words folded to three lines;
  * the last backup in a card with a green edge and a check: "The last backup
    of zigmon went to every destination", the five facts Last, Next, Locked,
    Destinations, Tried, and the five buttons at the right - Back up now
    (filled blue), Try the newest, Download one here, Put one back...,
    How to put it back;
  * When, how many, and the password: the settings side by side, each its
    name in bold over its control with the (i) at the right end and its words
    under the control; Make a strong one under the password; Try the backups
    there; no Save of the card's own but plexmon's save bar after the cards;
  * Where they go: a destination as a card - the icon of its kind, its name,
    the kind in words, a switch at the right, \\\\server\\share\\folder in mono,
    the chips PASSWORD and SMB3 ENCRYPTED, "last sent" in green, and Try it,
    Edit, Backups there and a bin;
  * What was sent: When, Node, File, Size, Where it went, Who - the node this
    machine;
  * Where should the backups go? six tiles, three across and two down, each an
    icon, a name and its words; the folder one not offered here;
  * the editor of an SMB destination: WHAT IT IS CALLED, WHERE, SIGNING IN in
    small capitals, the SMB fields, the password never in its box, Save filled;
  * Back up now, Try the newest, Download one here, Put one back..., How to put
    it back, the save bar, Try it and Backups there each ask the daemon.

Fails on 5.36.1.

    python3 test/backuppane.py

Port 19745 (php -S).
"""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-backuppane-check-'))
PHP_PORT = 19745
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


print('the pane in Chromium')
JS = r'''
const { chromium } = require('playwright');
const now = Date.now() / 1000;
const rc = {
  rbackup: {value: 1, kind: 'switch'}, rbackup_at: {value: '04:15', kind: 'time'},
  rbackup_every: {value: 'daily', kind: 'choice', choices: [['daily', 'every day'], ['weekly', 'once a week']]},
  rbackup_day: {value: 7, kind: 'number'}, rbackup_keep: {value: 30, kind: 'number'}, rbackup_keep_days: {value: 0, kind: 'number'},
  rbackup_password: {value: true, kind: 'secret'},
  rbackup_verify: {value: 'off', kind: 'choice', choices: [['off', 'only by hand'], ['after', 'after every backup, the one just sent'], ['weekly', 'once a week, the newest one']]}};
const smb = {id: 'a1b2c3', kind: 'smb', kind_words: 'SMB (Windows share, Samba)', enabled: 1, name: 'Synology', host: 'synology.falco81.net',
  port: 445, share: 'Backup', path: 'OS/zigmon', user: 'backup', domain: '', smb_encrypt: 1, has_password: true,
  last: {at: now - 420, ok: true, bytes: 654 * 1048576}};
const kinds = [['ftp', 'FTP', 21], ['ftps', 'FTPS', 21], ['sftp', 'SFTP', 22], ['scp', 'SCP (ssh)', 22], ['smb', 'SMB (Windows share, Samba)', 445]]
  .map(k => ({kind: k[0], words: k[1], port: k[2]}));
const rb = {ok: true, host: 'zigmon', targets: [smb], kinds, locked: true, next: '2026-11-01T04:15', helper: true, on: true,
  tools: {openssl: true, ssh: true, sftp: true, scp: true, smbclient: true, 'ssh-keygen': true},
  runs: [{at: now - 600, host: 'zigmon', ok: true, file: 'zigmon-full-zigmon-2026-10-31-041500.tar.gz.enc', bytes: 654 * 1048576,
          encrypted: true, by: 'zigmon (on the clock)', targets: [{name: 'Synology', ok: true, secs: 12}]}],
  verified: [], job: {running: false}};
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({viewport: {width: 1600, height: 1000}});
  p.setDefaultTimeout(4000);
  const errs = [], posts = [];
  p.on('pageerror', e => errs.push(String(e)));
  await p.route(/\?api=/, (route, req) => {
    const what = new URL(req.url()).searchParams.get('api');
    let body = {ok: true};
    if (req.method() === 'POST') {
      const got = JSON.parse(req.postData() || '{}');
      if (got.data) got.data = '…';
      posts.push([what, got]);
    }
    if (what === 'rbackup') body = rb;
    else if (what === 'rbackup-do') body = {ok: true, message: 'asked', job: {running: false}, text: 'RESTORE', files: [], steps: ['signed in'], secs: 1};
    else if (what === 'fullbackup') body = {ok: true, list: [], dir: '/var/backups/zigmon', status: {id: 'x1', state: 'done', inspected: {file: 'f', parts: []}}, helper: true};
    else if (what === 'fullbackup-upload') body = {ok: true, received: 1, of: 1, asked: 'x1'};
    else if (what === 'config-save') body = {ok: true, changed: ['rbackup_keep']};
    else if (what === 'status') { route.fulfill({status: 500, contentType: 'application/json', body: '{"error":"stub"}'}); return; }
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
  });
  await p.goto('http://127.0.0.1:%(port)d/index.php#control/sys-backup');
  await p.waitForTimeout(1200);
  await p.evaluate((rc) => {
    LOCK.who = {name: 'admin', role: 'admin'};
    renderSettings({runtime_config: rc});
    try { showTab('control'); } catch (e) {}
    try { showControlSection('sys-backup'); } catch (e) {}
  }, rc);
  await p.waitForTimeout(1500);
  const r = await p.evaluate(() => {
    const T = s => (s && s.textContent || '').replace(/\s+/g, ' ').trim();
    const R = e => e ? e.getBoundingClientRect() : null;
    const out = {};
    const head = document.getElementById('ctl-head');
    out.head = head ? {title: T(head.querySelector('.ctl-title')), clamp: getComputedStyle(head.querySelector('.ctl-lede')).webkitLineClamp} : null;
    const card = document.getElementById('rb-card');
    out.hero = card ? {edge: getComputedStyle(card).borderLeftColor, edgeW: getComputedStyle(card).borderLeftWidth,
      title: T(card.querySelector('.rb-hero-words > b')), icon: !!card.querySelector('.rb-hero-ic svg'),
      facts: Array.from(card.querySelectorAll('.rb-fact .k')).map(T),
      buttons: Array.from(card.querySelectorAll('.rb-hero-acts button')).map(T),
      primaryBg: (() => { const x = card.querySelector('.rb-hero-acts button'); return x ? getComputedStyle(x).backgroundColor : ''; })(),
      actsRight: (() => { const a = card.querySelector('.rb-hero-acts'), w = card.querySelector('.rb-hero-words');
        return !!(a && w) && R(a).left > R(w).left + 300; })()} : null;
    out.items = Array.from(document.querySelectorAll('#rb-when-card .set-item')).map(it => {
      const l = it.querySelector(':scope > label:first-child'), c = l && l.nextElementSibling,
            s = it.querySelector(':scope > .set-says'), i = l && l.querySelector('.iinfo');
      return {key: (it.querySelector('[data-k]') || {dataset: {}}).dataset.k, name: l ? T(l.firstChild) : '',
              above: !!(l && c) && R(l).bottom <= R(c).top + 1, bold: l ? +getComputedStyle(l).fontWeight : 0,
              iRight: i ? Math.round(R(it).right - R(i).right) : null, saysUnder: !!(s && c) && R(s).top >= R(c).bottom - 1,
              gen: !!it.querySelector('.rb-gen'), secret: (it.querySelector('input[type=password]') || {}).value};
    });
    out.cardSave = Array.from(document.querySelectorAll('#rb-when-card button')).map(T).filter(t => /save/i.test(t));
    const bar = document.getElementById('rb-save-bar');
    out.bar = bar ? Array.from(bar.querySelectorAll('button')).map(T) : null;
    const tc = document.querySelector('#rb-targets .rb-tcard');
    out.target = tc ? {icon: !!tc.querySelector('.rb-kind.k-smb svg'), name: T(tc.querySelector('.rb-tcard-name b')),
      kind: T(tc.querySelector('.rb-kind-words')), sw: (() => { const s = tc.querySelector('.rb-tcard-top .switch, .rb-tcard-top label');
        return !!s && R(s).right > R(tc).right - 40; })(),
      where: T(tc.querySelector('.rb-where')), mono: /mono|Menlo|Consolas/.test(getComputedStyle(tc.querySelector('.rb-where')).fontFamily),
      chips: Array.from(tc.querySelectorAll('.rb-chips .tag')).map(x => [T(x), getComputedStyle(x).textTransform, getComputedStyle(x).color]),
      last: T(tc.querySelector('.rb-last')), lastColor: getComputedStyle(tc.querySelector('.rb-last')).color,
      buttons: Array.from(tc.querySelectorAll('.rb-acts button')).map(x => T(x) || (x.querySelector('svg') ? 'icon' : ''))} : null;
    out.runs = Array.from(document.querySelectorAll('#rb-runs th')).map(T);
    out.runRow = Array.from(document.querySelectorAll('#rb-runs tbody tr:first-child td')).map(T);
    out.ok = getComputedStyle(document.body).getPropertyValue('--ok');
    return out;
  });
  // the kinds
  await p.evaluate(() => { const x = document.querySelector('#rb-add-host button'); if (x) x.click(); });
  await p.waitForTimeout(400);
  r.kinds = await p.evaluate(() => {
    const tiles = Array.from(document.querySelectorAll('#zmodal-body .rb-kind-tile'));
    return {title: (document.getElementById('zmodal-title') || {}).textContent,
      tiles: tiles.map(t => ({b: (t.querySelector('b') || {}).textContent, icon: !!t.querySelector('.rb-kind svg'),
        words: !!t.querySelector('.muted'), x: Math.round(t.getBoundingClientRect().left), y: Math.round(t.getBoundingClientRect().top),
        off: t.disabled}))};
  });
  // the editor of the SMB one
  await p.evaluate(() => { const t = Array.from(document.querySelectorAll('#zmodal-body .rb-kind-tile')).filter(x => x.dataset.kind === 'smb')[0]; if (t) t.click(); });
  await p.waitForTimeout(300);
  r.newTitle = await p.evaluate(() => document.getElementById('zmodal-title').textContent);
  await p.evaluate(() => closeZModal());
  await p.evaluate(() => { const x = Array.from(document.querySelectorAll('#rb-targets .rb-acts button')).filter(b => /Edit/.test(b.textContent))[0]; if (x) x.click(); });
  await p.waitForTimeout(400);
  r.editor = await p.evaluate(() => {
    const body = document.getElementById('zmodal-body');
    return {title: document.getElementById('zmodal-title').textContent,
      secs: Array.from(body.querySelectorAll('.rb-sec > h4')).map(h => [h.textContent, getComputedStyle(h).textTransform]),
      fields: Array.from(body.querySelectorAll('.formgrid > .set-item > label:first-child')).map(l => l.textContent),
      labelCase: (() => { const l = body.querySelector('.formgrid > .set-item > label'); return l ? getComputedStyle(l).textTransform : ''; })(),
      pw: (body.querySelector('input[type=password]') || {}).value,
      save: (() => { const s = Array.from(document.querySelectorAll('#zmodal-foot button')).filter(b => /Save/.test(b.textContent))[0];
        return s ? getComputedStyle(s).backgroundColor : ''; })(),
      foot: Array.from(document.querySelectorAll('#zmodal-foot button')).map(b => b.textContent.trim())};
  });
  await p.evaluate(() => closeZModal());
  // the buttons each ask the daemon
  const click = async (sel) => { try { await p.click(sel); } catch (e) { errs.push('not there: ' + sel); } await p.waitForTimeout(350); };
  await click('#rb-now');
  await click('#rb-try-newest');
  await click('#rb-here');
  await p.waitForTimeout(300);
  await click('#rb-guide');
  await p.evaluate(() => closeZModal());
  try {
    const [fc] = await Promise.all([p.waitForEvent('filechooser', {timeout: 3000}), p.click('#rb-put-back')]);
    await fc.setFiles({name: 'zigmon-full-zigmon-2026-10-31-041500.tar.gz.enc', mimeType: 'application/octet-stream', buffer: Buffer.from('Salted__xxxxxxxx')});
    await p.waitForTimeout(300);
    await p.evaluate(() => { const x = Array.from(document.querySelectorAll('#zmodal-foot button')).filter(b => /Send it/.test(b.textContent))[0]; if (x) x.click(); });
    await p.waitForTimeout(1500);
  } catch (e) { errs.push('Put one back: ' + e); }
  await p.evaluate(() => closeZModal());
  await p.evaluate(() => { const x = Array.from(document.querySelectorAll('#rb-targets .rb-acts button')).filter(b => /Try it/.test(b.textContent))[0]; if (x) x.click(); });
  await p.waitForTimeout(400);
  await p.evaluate(() => closeZModal());
  await p.evaluate(() => { const x = Array.from(document.querySelectorAll('#rb-targets .rb-acts button')).filter(b => /Backups there/.test(b.textContent))[0]; if (x) x.click(); });
  await p.waitForTimeout(400);
  await p.evaluate(() => closeZModal());
  try { await p.fill('#rb-when-card input[data-k="rbackup_keep"]', '12'); } catch (e) { errs.push('not there: the box of rbackup_keep'); }
  await p.waitForTimeout(150);
  r.dirty = await p.evaluate(() => ({said: (document.getElementById('rb-save-said') || {}).textContent,
    dirty: !!document.querySelector('#rb-save-bar.dirty')}));
  await click('#rb-save');
  await p.waitForTimeout(500);
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
    check(not r.get('errs'), 'the page threw, or a control is missing: %r' % r.get('errs'))
    check(r.get('head') == {'title': 'Backups', 'clamp': '3'}, 'the head of the pane is %r' % r.get('head'))
    h = r.get('hero') or {}
    check(h.get('title') == 'The last backup of zigmon went to every destination' and h.get('icon')
          and h.get('edgeW') == '4px' and h.get('edge') == 'rgb(63, 185, 80)'
          and h.get('facts') == ['Last', 'Next', 'Locked', 'Destinations', 'Tried'],
          'the card of the last backup - a green edge, a check, its words and five facts - is %r' % h)
    check(h.get('buttons') == ['Back up now', 'Try the newest', 'Download one here', 'Put one back…', 'How to put it back'],
          'the buttons are %r' % h.get('buttons'))
    check(h.get('primaryBg') == 'rgb(31, 111, 235)' and h.get('actsRight'), 'Back up now is not filled, at the right: %r' % h)
    items = {i['key']: i for i in r.get('items') or []}
    want = ['rbackup', 'rbackup_at', 'rbackup_every', 'rbackup_day', 'rbackup_keep', 'rbackup_keep_days', 'rbackup_password',
            'rbackup_verify']
    check(list(items) == want, 'the settings are %r' % list(items))
    for k, it in items.items():
        check(it['above'] and it['bold'] >= 600 and it['iRight'] is not None and it['iRight'] <= 2 and it['saysUnder'],
              '%s is not its name in bold over its control, (i) at the right, words under: %r' % (k, it))
    check((items.get('rbackup_password') or {}).get('gen') and not (items.get('rbackup_password') or {}).get('secret'),
          'Make a strong one is not under the password, or the password is in its box')
    check(not r.get('cardSave'), 'the card has a Save of its own: %r' % r.get('cardSave'))
    check(r.get('bar') == ['Save the changes', 'Put them back'], 'there is no save bar: %r' % r.get('bar'))
    t = r.get('target') or {}
    check(t.get('icon') and t.get('name') == 'Synology' and t.get('kind') == 'SMB (Windows share, Samba)' and t.get('sw'),
          'the destination card is %r' % t)
    check(t.get('where') == '\\\\synology.falco81.net\\Backup\\OS\\zigmon' and t.get('mono'), 'where it is: %r' % t.get('where'))
    chips = t.get('chips') or []
    check([c[0] for c in chips] == ['password', 'SMB3 encrypted'] and all(c[1] == 'uppercase' for c in chips)
          and chips[-1][2] == 'rgb(63, 185, 80)', 'the chips are %r' % chips)
    check((t.get('last') or '').startswith('✓ last sent') and t.get('lastColor') == 'rgb(63, 185, 80)', 'last sent: %r' % t.get('last'))
    check(t.get('buttons') == ['Try it', 'Edit', 'Backups there', 'icon'], 'its buttons are %r' % t.get('buttons'))
    check(r.get('runs') == ['When', 'Node', 'File', 'Size', 'Where it went', 'Who', ''], 'What was sent says %r' % r.get('runs'))
    check(len(r.get('runRow') or []) > 1 and r['runRow'][1] == 'zigmon', 'the node of a line is %r' % r.get('runRow'))
    k = r.get('kinds') or {}
    tiles = k.get('tiles') or []
    check(k.get('title') == 'Where should the backups go?' and [x['b'] for x in tiles] ==
          ['A folder', 'FTP', 'FTPS', 'SFTP', 'SCP (ssh)', 'SMB (Windows share, Samba)'], 'the kinds are %r' % k)
    check(len(tiles) == 6 and len({x['x'] for x in tiles}) == 3 and len({x['y'] for x in tiles}) == 2
          and all(x['icon'] and x['words'] for x in tiles), 'the kinds are not three across and two down: %r' % tiles)
    check(tiles and tiles[0]['off'] and not any(x['off'] for x in tiles[1:]), 'the folder is offered, or another is not')
    check(r.get('newTitle') == 'A new destination: SMB (Windows share, Samba)', 'a tile opens %r' % r.get('newTitle'))
    e = r.get('editor') or {}
    check(e.get('title') == 'Synology' and [s[0] for s in e.get('secs') or []][:3] == ['What it is called', 'Where', 'Signing in']
          and all(s[1] == 'uppercase' for s in e.get('secs') or []), 'the editor\'s sections are %r' % e.get('secs'))
    check(e.get('fields') == ['Name', 'Backups go here', 'The server', 'Port', 'The share', 'The folder in it', 'Account', 'Password',
                              'Domain (workgroup)', 'SMB3 encryption required'] and e.get('labelCase') == 'none',
          'the editor\'s fields are %r (%r)' % (e.get('fields'), e.get('labelCase')))
    check(e.get('pw') == '', 'the password is in its box in the editor')
    check(e.get('foot') == ['Close', 'Try it', 'Save'] and e.get('save') == 'rgb(31, 111, 235)', 'the editor\'s buttons: %r' % e)
    d = r.get('dirty') or {}
    check(d.get('dirty') and d.get('said') == '1 change(s) not saved yet', 'a change does not show on the save bar: %r' % d)
    acts = [b.get('action') for w, b in r.get('posts', []) if w == 'rbackup-do']
    for want_act in ('run', 'verify', 'here', 'restore_txt', 'try', 'list'):
        check(want_act in acts, '%s was not asked of the daemon: %r' % (want_act, acts))
    up = [b for w, b in r.get('posts', []) if w == 'fullbackup-upload']
    check(up and up[0].get('rbackup_password') == 1, 'Put one back did not send the file to root: %r' % up)
    saved = [b for w, b in r.get('posts', []) if w == 'config-save']
    check(saved and str(saved[0].get('rbackup_keep')) == '12', 'Save the changes did not save: %r' % saved)

if bad:
    print('\n%d problem(s)' % len(bad))
    raise SystemExit(1)
shutil.rmtree(str(W), ignore_errors=True)
print('\nthe backups to other machines as plexmon has them: every check passed')
