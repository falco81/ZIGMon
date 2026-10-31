#!/usr/bin/env python3
"""5.34.1: the CA's own certificate under Automatic certificates. Its box is a
tall one, and the rule that lays a tall box out outweighed the one that hides
a box whose choice is not made: with ACME off - or Let's Encrypt chosen - it
stayed on the card. And it was five lines high and narrow: a PEM did not fit.
The real page (php -S) in Chromium, its settings drawn from given values.
Fails on 5.34.0.

    python3 test/review5341.py
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
PORT = 19912
W = Path(tempfile.mkdtemp(prefix='zigmon-review5341-check-'))
if not subprocess.run(['which', 'php'], capture_output=True).stdout:
    print('  SKIPPED: no php here')
    sys.exit(0)
pem = '-----BEGIN CERTIFICATE-----\n' + 'MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw\n' * 20 + \
    '-----END CERTIFICATE-----'
js = r'''
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({viewport: {width: 1600, height: 1000}});
  p.on('pageerror', e => {});
  await p.goto('http://127.0.0.1:%(port)d/index.php#control/sys-acme');
  await p.waitForTimeout(1200);
  const out = {};
  for (const [name, on, ca] of [['off', 0, 'custom'], ['le', 1, 'letsencrypt'], ['custom', 1, 'custom']]) {
    out[name] = await p.evaluate(([on, ca, pem]) => {
      const rc = {acme: {value: on, kind: 'bool'},
                  acme_ca: {value: ca, kind: 'choice', choices: [['letsencrypt', 'LE'], ['custom', 'Custom']]},
                  acme_ca_pem: {value: pem, kind: 'str'}, acme_url: {value: '', kind: 'str'}};
      SETTINGS.dirty = false;
      renderSettings({runtime_config: rc});
      try { showControlSection('sys-acme'); } catch (e) {}
      let up = document.getElementById('set-host-sys-acme');
      while (up) { if (getComputedStyle(up).display === 'none') { up.hidden = false; up.style.display = 'block'; } up = up.parentElement; }
      const ta = document.querySelector('[data-k="acme_ca_pem"]');
      if (!ta) return {err: 'no box'};
      const it = ta.closest('.set-item');
      return {display: getComputedStyle(it).display, rows: ta.rows, tag: ta.tagName,
              fits: ta.scrollWidth <= ta.clientWidth + 1, h: ta.getBoundingClientRect().height,
              w: ta.getBoundingClientRect().width};
    }, [on, ca, %(pem)s]);
  }
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
''' % {'port': PORT, 'pem': json.dumps(pem)}
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
if r['off'].get('display') != 'none':
    bad.append('the CA\'s certificate is shown with ACME off (display %s)' % r['off'].get('display'))
if r['le'].get('display') != 'none':
    bad.append('the CA\'s certificate is shown with Let\'s Encrypt chosen (display %s)' % r['le'].get('display'))
c = r['custom']
if c.get('display') == 'none':
    bad.append('the CA\'s certificate is hidden for a CA of your own')
if not c.get('fits'):
    bad.append('a line of a PEM does not fit across its box (%d px)' % (c.get('w') or 0))
if (c.get('h') or 0) < 280:
    bad.append('the box is not tall enough for a certificate (%d px)' % (c.get('h') or 0))
for b in bad:
    print('  FAILED: ' + b)
print('review5341: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
sys.exit(1 if bad else 0)
