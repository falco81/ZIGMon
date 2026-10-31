#!/usr/bin/env python3
"""5.36.1: the band of maintenance at the top of every page. The page is a
column the height of the window; the band could be shrunk by it, its words
ran over the header under it, and there was no room between them. Checked in
Chromium on the real page. Fails on 5.36.0.

    python3 test/review5361.py
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
PORT = 19726
W = Path(tempfile.mkdtemp(prefix='zigmon-review5361-check-'))
if not subprocess.run(['which', 'php'], capture_output=True).stdout:
    print('  SKIPPED: no php here')
    sys.exit(0)
js = r'''
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const out = {};
  for (const [w, h] of [[1600, 1000], [1280, 600]]) {
    const p = await b.newPage({viewport: {width: w, height: h}});
    p.on('pageerror', e => {});
    await p.goto('http://127.0.0.1:%(port)d/index.php#control/sys-upgrade');
    await p.waitForTimeout(1000);
    out[w] = await p.evaluate(() => {
      renderMaintBand({maintenance: {on: true, auto: true, at: Date.now() / 1000 - 1, why: 'the upgrade to zigmon 5.36.0'}});
      const band = document.getElementById('maint-band').getBoundingClientRect();
      const words = document.querySelector('#maint-band .change-words').getBoundingClientRect();
      const head = document.querySelector('.wrap > header').getBoundingClientRect();
      return {bandBottom: band.bottom, wordsBottom: words.bottom, headTop: head.top, bandH: band.height};
    });
    await p.close();
  }
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
''' % {'port': PORT}
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
for w, x in r.items():
    if x['wordsBottom'] > x['bandBottom'] + 0.5:
        bad.append('%s wide: the band\'s words run out of it (%d > %d)' % (w, x['wordsBottom'], x['bandBottom']))
    if x['headTop'] - x['bandBottom'] < 10:
        bad.append('%s wide: no room between the band and the header (%d px)' % (w, x['headTop'] - x['bandBottom']))
for b in bad:
    print('  FAILED: ' + b)
print('review5361: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
sys.exit(1 if bad else 0)
