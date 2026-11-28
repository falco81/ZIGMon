/**
 * (1.3) Where text lies on a key, as svg.ts measures it: for the text-size tests.
 */
import { textWidth } from "../src/core/svg.js";

export interface TextBox { left: number; right: number; top: number; bottom: number; text: string; size: number; roles: string[] }

const unesc = (s: string) => s.replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'");

/** Every <text> outside a transformed group (those are placed by the transform), with its box. */
export function textBoxes(svg: string): TextBox[] {
  const flat = svg.replace(/<g [^>]*transform="[^"]*"[^>]*>(?:(?!<\/g>).)*?<text[\s\S]*?<\/g>/g, "");
  const out: TextBox[] = [];
  for (const m of flat.matchAll(/<text ([^>]*)>(.*?)<\/text>/gs)) {
    const a = m[1]!;
    const num = (k: string) => Number(new RegExp(`(?:^| )${k}="([\\d.-]+)"`).exec(a)?.[1] ?? NaN);
    const x = num("x"), y = num("y"), size = num("font-size"), weight = num("font-weight") || 600;
    if (!Number.isFinite(x) || !Number.isFinite(size) || !Number.isFinite(y)) continue;
    const anchor = /text-anchor="(\w+)"/.exec(a)?.[1] ?? "start";
    const body = m[2]!;
    const main = unesc(body.replace(/<tspan[\s\S]*$/, ""));
    let w = textWidth(main, size, weight);
    let big = size;
    for (const t of body.matchAll(/<tspan([^>]*)>(.*?)<\/tspan>/g)) {
      const ts = Number(/font-size="([\d.]+)"/.exec(t[1]!)?.[1] ?? size);
      const dx = Number(/dx="([\d.-]+)"/.exec(t[1]!)?.[1] ?? 0);
      w += textWidth(unesc(t[2]!), ts, 600) + dx;
      big = Math.max(big, ts);
    }
    const spacing = Number(/letter-spacing="([\d.-]+)"/.exec(a)?.[1] ?? 0);
    w += spacing * [...main].length;
    const left = anchor === "middle" ? x - w / 2 : anchor === "end" ? x - w : x;
    const roles = (/data-role="([^"]*)"/.exec(a)?.[1] ?? "").split(" ").filter(Boolean);
    // below the baseline only what has a tail (g, j, p, q, y, commas, brackets)
    const tail = /[gjpqyQ,;()[\]{}]/.test(unesc(body)) ? 0.22 : 0.04;
    out.push({ left, right: left + w, top: y - big * 0.74, bottom: y + big * tail, text: main, size, roles });
  }
  return out;
}

/** How far the text runs off the 144 px key, at the worst (0 when inside). */
export function overflow(svg: string): { px: number; what: string } {
  let px = 0, what = "";
  for (const b of textBoxes(svg)) {
    const o = Math.max(-b.left, b.right - 144, -b.top, b.bottom - 144, 0);
    if (o > px) {
      px = o;
      what = `"${b.text}" ${Math.round(b.left)}..${Math.round(b.right)} x ${Math.round(b.top)}..${Math.round(b.bottom)}`;
    }
  }
  return { px, what };
}

/** Each role's sizes, from the texts and tspans that say their role; a text holding several roles is listed under each. */
export function roleSizes(svg: string): { role: string; size: number; shared: string[] }[] {
  const out: { role: string; size: number; shared: string[] }[] = [];
  for (const m of svg.matchAll(/<text ([^>]*)>(.*?)<\/text>/gs)) {
    const a = m[1]!;
    const size = Number(/font-size="([\d.]+)"/.exec(a)?.[1] ?? NaN);
    const roles = (/data-role="([^"]*)"/.exec(a)?.[1] ?? "").split(" ").filter(Boolean);
    const inner = [...m[2]!.matchAll(/<tspan([^>]*)>/g)].map((t) => ({
      size: Number(/font-size="([\d.]+)"/.exec(t[1]!)?.[1] ?? size), role: /data-role="([^"]*)"/.exec(t[1]!)?.[1] ?? "",
    })).filter((t) => t.role);
    const shared = [...new Set([...roles, ...inner.map((t) => t.role)])];
    if (roles[0]) out.push({ role: roles[0], size, shared });
    for (const r of roles.slice(1)) out.push({ role: r, size, shared });
    for (const t of inner) out.push({ role: t.role, size: t.size, shared });
  }
  return out;
}
