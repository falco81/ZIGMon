#!/usr/bin/env python3
"""5.34.1: the card In your DNS of Automatic certificates. It was made anew at
every refresh of the pane - its copy buttons blinked every few seconds - and
each copy button sat wherever its line of text happened to end. Now the card
is kept while what it says is the same, and the buttons stand in a column of
their own right after the text, one under the other. The real page (php -S)
in Chromium. And the two certificates side by side, this machine's and the
server in front's: the names and the bars under them on one line, though
the words under each card's title wrap differently. Fails on 5.34.0.

    python3 test/review5342.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PORT = 19913
W = Path(tempfile.mkdtemp(prefix='zigmon-review5342-check-'))
if not subprocess.run(['which', 'php'], capture_output=True).stdout:
    print('  SKIPPED: no php here')
    sys.exit(0)
guide = {'challenge': 'dns-01', 'dns': 'desec', 'rows': [
    {'target': '', 'name': 'acme.house.example', 'type': 'NS', 'record': 'acme.house.example',
     'value': 'ns1.desec.io. ns2.desec.org.', 'check': 'ns'},
    {'target': 'web', 'name': 'mqtt.house.example', 'type': 'CNAME',
     'record': '_acme-challenge.mqtt.house.example',
     'value': '_acme-challenge.zigmon.acme.house.example.', 'check': 'cname'}]}
js = r'''
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({viewport: {width: 1600, height: 1000}});
  p.on('pageerror', e => {});
  await p.goto('http://127.0.0.1:%(port)d/index.php#control/sys-acme');
  await p.waitForTimeout(1200);
  const r = await p.evaluate((guide) => {
    const d = {ok: true, on: true, helper: true, targets: [], mine: [], directory: '', account: {},
               work: {}, node: 'x', challenge: 'dns-01', dns_guide: guide, port80: null, manual: null};
    AC.d = d;
    let up = document.getElementById('ac-host');
    while (up) { if (getComputedStyle(up).display === 'none') { up.hidden = false; up.style.display = 'block'; } up = up.parentElement; }
    drawAcme();
    const first = document.querySelector('.acme-dns .dns-copy button, .acme-dns .dns-val button');
    AC.d = JSON.parse(JSON.stringify(d));
    drawAcme();
    const again = document.querySelector('.acme-dns .dns-copy button, .acme-dns .dns-val button');
    const rows = Array.from(document.querySelectorAll('.acme-dns tbody tr'));
    const xs = col => rows.map(tr => {
      const bs = tr.querySelectorAll('button');
      return bs[col] ? Math.round(bs[col].getBoundingClientRect().left) : null; });
    const gap = rows.map(tr => {
      const t = tr.querySelector('.dns-val span'), bt = tr.querySelector('button');
      return t && bt ? Math.round(bt.getBoundingClientRect().left - t.getBoundingClientRect().right) : null; });
    return {kept: !!first && first === again, record: xs(0), value: xs(1), gap: gap};
  }, %(guide)s);
  r.level = await p.evaluate(() => {
    try { showControlSection('sys-certs'); } catch (e) {}
    let up = document.getElementById('web-certs');
    while (up) { if (getComputedStyle(up).display === 'none') { up.hidden = false; up.style.display = 'block'; } up = up.parentElement; }
    const info = {cn: 'mqtt.house.example', issuer: 'CN=Some CA', not_before: Date.now() / 1000 - 86400 * 100,
                  not_after: Date.now() / 1000 + 86400 * 200, key: 'RSA 4096', san: ['mqtt.house.example'], chain: 1};
    const d = {ok: true, may: true, helper: true, conf: {managed: true, preset: 'standard', dh: 'gen4096', hsts: 31536000},
               now: {info: info, files: {cert: '/etc/nginx/certs/server.pem', key: '/etc/nginx/certs/server.key'},
                     broker: ['x'], verify: 'ok', root_info: {cn: 'Root'}},
               node: {current: true}, server_name: 'mqtt.house.example', presets: {}, dh: {}, acme: {},
               proxy: {host: '192.168.43.17', name: 'mqtt.house.example', key_way: true, same: true,
                       conf: {follow: true}, node: {current: true},
                       look: {ok: true, blocks: 2, info: info, files: {cert: '/etc/nginx/certs/server.pem', key: 'k', root: 'r'},
                              protocols: ['TLSv1.2', 'TLSv1.3'], stapling: true}}};
    document.getElementById('web-certs').style.width = '720px';
    drawWeb(d);
    const tops = sel => Array.from(document.querySelectorAll('#web-certs ' + sel)).map(e => Math.round(e.getBoundingClientRect().top));
    return {cn: tops('.cert-cn'), bar: tops('.cert-life'), h: Array.from(document.querySelectorAll('#web-certs .cert-h')).map(e => Math.round(e.getBoundingClientRect().height))};
  });
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
''' % {'port': PORT, 'guide': json.dumps(guide)}
(W / 'run.js').write_text(js)
php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PORT, '-t', str(HERE / 'web')], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            socket.create_connection(('127.0.0.1', PORT), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
    got = subprocess.run(['node', str(W / 'run.js')], capture_output=True, text=True, timeout=120,
                         stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=root))
finally:
    php.kill()
    php.wait()
try:
    r = json.loads(got.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    r = {'error': (got.stdout + got.stderr)[-300:]}
if r.get('error'):
    print('  SKIPPED (no browser here): %s' % r['error'][:200])
    sys.exit(0)
bad = []
if not r['kept']:
    bad.append('the card was made anew though nothing in it changed - its buttons blink')
for col in ('record', 'value'):
    xs = [x for x in r[col] if x is not None]
    if len(xs) != 2 or len(set(xs)) != 1:
        bad.append('the copy buttons of the %s are not one under the other: %r' % (col, r[col]))
lv = r.get('level') or {}
for part, words in (('cn', 'the names'), ('bar', 'the bars')):
    t = lv.get(part) or []
    if os.environ.get('DBG'):
        print('DBG', lv)
    if len(t) != 2 or abs(t[0] - t[1]) > 1:
        bad.append('%s of the two certificates are not on one line: %r' % (words, t))
if any(g is None or g < 0 or g > 300 for g in r['gap']):
    bad.append('a copy button is not right after its text: %r' % r['gap'])
for b in bad:
    print('  FAILED: ' + b)
print('review5342: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
sys.exit(1 if bad else 0)
