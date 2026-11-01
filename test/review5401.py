#!/usr/bin/env python3
"""5.40.1: Certificates from acme - its switches are saved with Save settings
at the end of the card, as on every other card, never when clicked. The
button stood in the middle of the card, above the pairing and the slots.
The real page (php -S) in Chromium. Fails on 5.40.0.

    python3 test/review5401.py
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
PORT = 19727
W = Path(tempfile.mkdtemp(prefix='zigmon-review5401-check-'))
if not subprocess.run(['which', 'php'], capture_output=True).stdout:
    print('  SKIPPED: no php here')
    sys.exit(0)
js = r'''
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({viewport: {width: 1600, height: 1000}});
  p.on('pageerror', e => {});
  const posts = [];
  p.on('request', r => { if (r.method() === 'POST') posts.push((r.url() + ' ' + (r.postData() || '')).slice(0, 300)); });
  await p.goto('http://127.0.0.1:%(port)d/index.php#control/sys-certs');
  await p.waitForTimeout(1200);
  await p.evaluate(() => {
    SETTINGS.dirty = false;
    renderSettings({runtime_config: {cert_push: {value: 0, kind: 'switch'}, cert_push_other_names: {value: 0, kind: 'switch'}}});
    try { showControlSection('sys-certs'); } catch (e) {}
    let up = document.getElementById('push-card');
    while (up) { if (getComputedStyle(up).display === 'none') { up.hidden = false; up.style.display = 'block'; } up = up.parentElement; }
  });
  posts.length = 0;
  const sw = await p.$('[data-k="cert_push"]');
  await (await sw.evaluateHandle(e => e.closest('label') || e)).asElement().click();
  await p.waitForTimeout(1200);
  const afterClick = posts.slice();
  const r = await p.evaluate(() => {
    const card = document.getElementById('push-card');
    const kids = Array.from(card.children).filter(x => x.tagName !== 'SCRIPT');
    const bar = card.querySelector('.set-bar');
    return {last: kids[kids.length - 1] === bar, barAfterPush: !!(bar && document.getElementById('acme-push') &&
              (document.getElementById('acme-push').compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING)),
            dirty: SETTINGS.dirty, note: (card.querySelector('.set-note-alt') || {}).textContent || ''};
  });
  // what Save settings does: the settings' save (it asks who you are first)
  await p.evaluate(() => { window.__saved = 0; var b = document.getElementById('settings-save');
    b.onclick = function () { window.__saved++; }; });
  await p.click('#push-card .set-save-alt');
  await p.waitForTimeout(1200);
  const saved = await p.evaluate(() => window.__saved);
  console.log(JSON.stringify({afterClick: afterClick, r: r, saved: saved}));
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
    out = json.loads(got.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    out = {'error': (got.stdout + got.stderr)[-300:]}
if out.get('error'):
    print('  SKIPPED (no browser here): %s' % out['error'][:200])
    sys.exit(0)
bad = []
if out['afterClick']:
    bad.append('a click on the switch was sent at once: %r' % out['afterClick'])
r = out['r']
if not (r['dirty'] and 'Unsaved' in r['note']):
    bad.append('the switch did not wait for Save: %r' % r)
if not (r['last'] and r['barAfterPush']):
    bad.append('Save settings is not at the end of the card, after the pairing and the slots')
if out['saved'] != 1:
    bad.append('Save settings at the end of the card does not save the settings: %r' % out['saved'])
for b in bad:
    print('  FAILED: ' + b)
print('review5401: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
sys.exit(1 if bad else 0)
