#!/usr/bin/env python3
"""A column header must stand over the boxes it names.

Every table on the Control page is built as a grid per row: the header is one
grid, each row is another. Two things then have to hold, and neither is
checked by anything that runs:

  * the header must have as many cells as the row has columns, or the names
    shift along by one from wherever the missing cell is;

  * no column may be sized by its own content (`max-content`, `auto`,
    `fit-content`), because each row answers that question for itself. The
    gateways had `max-content` on the buttons column: the header's last cell
    is empty and so asked for nothing, the five columns above the boxes ate
    the width the buttons take in the rows, and every name from Address on
    walked right - a hundred and fifty pixels of it by Target. A row carrying
    the `config.json` label drifted from its neighbours in the same way.

A content-sized column is allowed only through a variable - `var(--gw-btns,
max-content)` - which is measured once from the widest row and handed to the
header and every row alike. This test insists such a variable is really set
somewhere in the page's script, so the fallback is not the whole story.

    python3 test/columns.py
"""
import re
import sys
from pathlib import Path

page = (Path(__file__).resolve().parent.parent / 'web' / 'index.php').read_text()
bad = []

CONTENT = ('max-content', 'min-content', 'fit-content', 'auto')


def tracks(spec):
    """Split a grid-template-columns value into tracks, keeping ( ) together."""
    out, depth, cur = [], 0, ''
    for ch in spec:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch.isspace() and depth == 0:
            if cur:
                out.append(cur)
            cur = ''
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def template(kind):
    """The base rule for .kind-row, ignoring the ones inside media queries."""
    for m in re.finditer(r'\.%s-row\{([^}]*)\}' % re.escape(kind), page):
        # a media query opens a brace before the rule; the base rule is the
        # one that also says display:grid
        body = m.group(1)
        if 'grid-template-columns' in body and 'display:grid' in body:
            return re.search(r'grid-template-columns:([^;}]*)', body).group(1).strip()
    return None


def header_cells(at):
    """Count the cells the script appends to a header built at this offset."""
    tail = page[at:at + 900]
    m = re.search(r'\[(.*?)\]\s*\.?\s*\n?\s*\.?forEach', tail, re.S)
    if not m:
        return None
    items, depth, n = m.group(1), 0, 1
    if not items.strip():
        return 0
    for ch in items:
        if ch in '[(':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif ch == ',' and depth == 0:
            n += 1
    return n


heads = re.finditer(r"el\('div', '([a-z0-9]+)-row ([a-z0-9]+)-head'\)", page)
seen = 0
for m in heads:
    kind, headname = m.group(1), m.group(2)
    spec = template(kind)
    if not spec or 'repeat(' in spec:
        continue
    seen += 1
    cols = tracks(spec)
    cells = header_cells(m.end())
    note = ''
    for t in cols:
        plain = t if not t.startswith('var(') else ''
        if any(c in plain for c in CONTENT):
            bad.append('.%s-row sizes a column by its content (%s) - '
                       'each row then answers it alone and the header cannot line up' % (kind, t))
            note = '  <-- content-sized column'
        if t.startswith('var('):
            name = re.match(r'var\((--[a-z0-9-]+)', t).group(1)
            set_here = ("setProperty('%s'" % name) in page
            measured = re.search(r"shareColumn\([^;]*?'%s'\s*\)" % re.escape(name), page)
            if not (set_here or measured):
                bad.append('.%s-row reads %s, which nothing ever sets' % (kind, name))
                note = '  <-- variable never set'
    if cells is not None and cells != len(cols):
        bad.append('.%s-head has %d cells over %d columns' % (headname, cells, len(cols)))
        note = '  <-- header does not cover the row'
    print('%-12s %d columns, header %s cells%s'
          % ('.' + kind + '-row', len(cols), '?' if cells is None else cells, note))

# A mark inside a box that opens a list must not sit where the arrow is.
# A select draws its own arrow at its right edge, and the mark sat on top of
# it: two symbols in one place, and a click that could go either way.
def px(text, prop):
    m = re.search(prop + r':\s*(-?\d+)px', text)
    return None if not m else int(m.group(1))

base = re.search(r'\n  select\{([^}]*)\}', page, re.S)
mark = re.search(r'\n  \.obj-mark\{([^}]*)\}', page, re.S)
if not base or not mark:
    print('the select or the mark has moved - this check cannot see them')
    sys.exit(1)
arrow_at = re.search(r'background-position:right (\d+)px center', base.group(1))
arrow_w = px(base.group(1), 'background-size')
mark_w = px(mark.group(1), 'width')
if not arrow_at or not arrow_w or not mark_w:
    print('the arrow or the mark has no size here - this check cannot see them')
    sys.exit(1)
arrow = (int(arrow_at.group(1)), int(arrow_at.group(1)) + arrow_w)     # from the right edge
placed = 0
for sel, body in re.findall(r'\n *([^{\n]*\.obj-in > select \+ \.obj-mark)\{([^}]*)\}', page):
    if 'display:none' in body:
        continue                      # a screen too narrow for it: hidden, not misplaced
    placed += 1
    left, right = px(body, 'left'), px(body, 'right')
    if left is not None and 'right:auto' in body:
        # on the far side from the arrow: the box must keep room for it
        pad = None
        for sel2, body2 in re.findall(r'\n  ([^{\n]*\.obj-in > select)\{([^}]*)\}', page):
            got = px(body2, 'padding-left')
            if got is not None:
                pad = got if pad is None else max(pad, got)
        if pad is None or pad < left + mark_w:
            bad.append('%s puts the mark %spx from the left, and the box keeps %s for it'
                       % (sel, left, 'nothing' if pad is None else str(pad) + 'px'))
        continue
    if right is None:
        bad.append('%s places the mark neither left nor right' % sel)
    elif right < arrow[1]:
        bad.append('%s puts the mark %dpx from the right, over the arrow at %d-%dpx'
                   % (sel, right, arrow[0], arrow[1]))
print('a box that opens a list: %d rule(s) place its mark, clear of the arrow at %d-%dpx'
      % (placed, arrow[0], arrow[1]))
if not placed:
    bad.append('nothing places the mark inside a box that opens a list')

# A box that opens a list draws an arrow, and a row that sets its own
# background shorthand wipes that arrow out - so the box looked like a plain
# field with nothing to say it could be opened. Every such row must put the
# arrow back from --pickarrow.
style = page[page.index('<style>'):page.index('</style>')] if '<style>' in page else page
style = re.sub(r'/\*.*?\*/', ' ', style, flags=re.S)        # comments are not selectors
blocks = [(re.sub(r'\s+', ' ', sel).strip(), body)
          for sel, body in re.findall(r'([^{}@]+)\{([^{}]*)\}', style)]
killers, restored = [], set()
for sel, body in blocks:
    parts = [p_.strip() for p_ in sel.split(',') if p_.strip().endswith('select')]
    if not parts:
        continue
    if 'var(--pickarrow)' in body:
        restored.update(parts)
    elif re.search(r'(^|;)\s*background:', body):
        killers.extend(parts)
missing = [part for part in killers if part != 'select' and part not in restored]
print('boxes that open a list: %d rule(s) restyle one, %d put the arrow back'
      % (len(killers), len(restored)))
if missing:
    bad.append('these set their own background on a select and leave it with no arrow: '
               + ', '.join(sorted(set(missing))))

# The dashed frame a card wears while the cards are being rearranged (and the
# one being dragged) is drawn inside it: outside, the page's clipping cut the
# left edge off the first card of every row (5.19.2).
frames = re.findall(r'\n  (body\.arranging \.cangrab|\.draggingcard)\{([^}]*)\}', page)
print('rearranging frames: %d' % len(frames))
if len(frames) < 2:
    bad.append('the frame of a card being rearranged has moved - this check cannot see it')
for sel, body in frames:
    m = re.search(r'outline-offset:\s*(-?\d+)px', body)
    if 'outline' in body and (not m or int(m.group(1)) >= 0):
        bad.append('%s draws its frame outside the card, where the first card of a row loses its left edge' % sel)

if not seen:
    print('no grid headers found - has the page moved?')
    sys.exit(1)
if bad:
    print()
    for b in bad:
        print('   ' + b)
    sys.exit(1)
print('\n%d header(s) stand over their rows' % seen)
