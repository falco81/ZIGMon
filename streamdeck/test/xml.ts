import assert from "node:assert/strict";

/** A strict little XML checker: balanced tags, quoted attributes, no raw < or stray & in text. */
export function wellFormed(xml: string): void {
  const stack: string[] = [];
  const re = /<(\/?)([A-Za-z][\w:.-]*)((?:\s+[\w:.-]+="[^"<]*")*)\s*(\/?)>/y;
  let i = 0;
  const text = (t: string) => {
    if (t.includes(">") && false) return;
    assert.ok(!/&(?!(amp|lt|gt|quot|#39|#\d+);)/.test(t), "a stray & in: " + t.slice(0, 60));
  };
  while (i < xml.length) {
    const lt = xml.indexOf("<", i);
    if (lt < 0) {
      text(xml.slice(i));
      break;
    }
    text(xml.slice(i, lt));
    re.lastIndex = lt;
    const m = re.exec(xml);
    assert.ok(m, "malformed tag at " + lt + ": " + xml.slice(lt, lt + 80));
    for (const a of m[3]!.matchAll(/="([^"]*)"/g)) text(a[1]!);
    if (m[1]) assert.equal(stack.pop(), m[2], "closing " + m[2]);
    else if (!m[4]) stack.push(m[2]!);
    i = re.lastIndex;
  }
  assert.deepEqual(stack, [], "unclosed tags");
  assert.ok(xml.startsWith("<svg"), "an svg document");
}
