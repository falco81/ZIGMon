#!/usr/bin/env python3
"""5.52: Settings - Devices: "What it is" and "State" are wide enough for their words.

At 92 px "What it is" read "a s..." on a wide screen. The page's own CSS is put
around the two selects of a channel line, at 1600 and 1280 px, and each one's
words (with its icon) must fit inside it.

    python3 test/review5521_mchan.py < /dev/null
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review5521-'))
page = (HERE / 'web' / 'index.php').read_text()
css = '\n'.join(re.findall(r'<style[^>]*>(.*?)</style>', page, re.S))
(W / 'p.html').write_text('''<!doctype html><html><head><meta charset="utf-8"><style>%s</style></head>
<body><div id="w"><div class="mchan">
<span>#0</span><input value="Plug-WorkshopLight"><input value="plug-workshoplight">
<select id="role"><option>\U0001f50c a socket</option></select>
<select id="en"><option>\U0001f441 monitor only</option></select>
<button>Test</button><button>Remove</button></div></div></body></html>''' % css)
js = r'''
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const out = {};
  for (const w of [1600, 1280]) {
    const p = await b.newPage({viewport: {width: w, height: 600}});
    await p.goto('file://' + process.argv[2]);
    out[w] = await p.evaluate(() => ['role', 'en'].map(id => {
      const s = document.getElementById(id), cs = getComputedStyle(s), m = document.createElement('span');
      m.style.font = cs.font; m.style.whiteSpace = 'pre'; m.textContent = s.options[0].text; document.body.appendChild(m);
      const need = m.getBoundingClientRect().width + parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) + 2;
      return {id: id, need: Math.ceil(need), have: Math.floor(s.getBoundingClientRect().width)};
    }));
    await p.close();
  }
  console.log(JSON.stringify(out)); await b.close();
})().catch(e => console.log(JSON.stringify({error: String(e)})));
'''
(W / 'm.js').write_text(js)
root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
got = subprocess.run(['node', str(W / 'm.js'), str(W / 'p.html')], capture_output=True, text=True, timeout=120,
                     env=dict(os.environ, NODE_PATH=root))
shutil.rmtree(W, ignore_errors=True)
try:
    r = json.loads(got.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    r = {'error': (got.stdout + got.stderr)[-300:]}
if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
    print('review5521_mchan: SKIPPED (no browser here)')
    sys.exit(0)
bad = [] if not r.get('error') else [r['error']]
for w, sel in r.items():
    if w == 'error':
        continue
    for x in sel:
        if x['have'] < x['need']:
            bad.append('at %s px "%s" is %d px wide and its words need %d' % (w, x['id'], x['have'], x['need']))
for b in bad:
    print('  FAILED: ' + b)
print('review5521_mchan: ' + ('all good' if not bad else '%d FAILED' % len(bad)))
sys.exit(1 if bad else 0)
