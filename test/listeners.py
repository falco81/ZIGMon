#!/usr/bin/env python3
"""A listener put on the whole page from inside a function must come off again.

`showDialog` added an Escape handler to `document` every time it opened, and
took it off only when the dialog was closed with Escape. Closed with OK, or by
clicking outside, it stayed - and the next dialog added another. Nothing goes
visibly wrong, which is why it sat there: they simply pile up, and every
keystroke afterwards runs all of them.

A registration at the top of the script happens once and is fine. One inside a
function body happens as often as that function is called, so it must name its
handler and take it off somewhere. An anonymous function cannot be taken off
at all and is refused outright.

    python3 test/listeners.py
"""
import re
import sys
from pathlib import Path

page = (Path(__file__).resolve().parent.parent / 'web' / 'index.php').read_text()
script = page[page.index('<script>'):]

# where the braces stand at the start of each line: depth 0 is the top of the
# script, where a registration happens once
depth, at_depth = 0, []
for line in script.split('\n'):
    at_depth.append(depth)
    stripped = re.sub(r'"(\\.|[^"\\])*"|\'(\\.|[^\'\\])*\'|//.*$', '', line)
    depth += stripped.count('{') - stripped.count('}')

lines = script.split('\n')
bad = []
inside = 0
for n, line in enumerate(lines):
    m = re.search(r'\b(?:document|window)\.addEventListener\(\s*\'([a-z]+)\'\s*,\s*([^,)]+)', line)
    if not m or at_depth[n] <= 0:
        continue
    inside += 1
    event, handler = m.group(1), m.group(2).strip()
    if handler.startswith('function') or handler.startswith('('):
        bad.append('line %d: %s is given an unnamed function - it can never be taken off'
                   % (n + 1, event))
        continue
    if ('removeEventListener(\'%s\', %s' % (event, handler)) not in script:
        bad.append('line %d: %s is added as %s and never removed' % (n + 1, event, handler))

if not inside:
    print('no page-wide listeners are added from inside a function')
    sys.exit(0)
print('%d page-wide listener(s) added from inside a function' % inside)
if bad:
    print()
    for b in bad:
        print('   ' + b)
    sys.exit(1)
print('every one of them is taken off again')
