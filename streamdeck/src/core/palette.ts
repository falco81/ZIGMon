import { cleanHex } from "./colour.js";

/** ZIGMon's dashboard palette (web/index.php :root), so the deck looks like part of ZIGMon. */
export const P = {
  bg: "#0D1117",
  panel: "#161B22",
  panel2: "#1C222B",
  line: "#262C37",
  text: "#E6E9EF",
  dim: "#8B94A3",
  muted: "#5B6472",
  ok: "#3FB950",
  warn: "#D29922",
  crit: "#F85149",
  info: "#58A6FF",
  purple: "#A371F7",
  orange: "#F0883E",
  water: "#39C5CF",
  pink: "#DB61A2",
} as const;

export type Colour = (typeof P)[keyof typeof P];

/** The font the keys are drawn in: Segoe UI is on every Windows the plugin runs on. */
export const FONT = "Segoe UI, Inter, Arial, sans-serif";

/** (1.1) The few colours the looks use beyond the dashboard's: the blinds' sky, a warm yellow,
 * the Light look's paper and ink, the High contrast look's black and white. */
export const X = {
  sky1: "#1F3A5F",
  sky2: "#2D4F6E",
  yellow: "#F2CC60",
  silver: "#C9D1D9",
  white: "#FFFFFF",
  black: "#000000",
  night: "#05070B",
  paper: "#F6F8FA",
  paper2: "#EAEEF2",
  paperLine: "#D0D7DE",
  ink: "#1F2328",
  inkDim: "#59636E",
  inkMuted: "#8C959F",
  inkCrit: "#CF222E",
  inkWarn: "#9A6700",
  hcYellow: "#FFD33D",
  hcRed: "#FF5C5C",
  hcGrey: "#BDBDBD",
} as const;

/** (1.3) The named colours added to 1.1's ten, chosen to read well on the dark keys. */
export const A = {
  indigo: "#7C8CF8",
  sky: "#7DD3FC",
  cyan: "#22D3EE",
  mint: "#6EE7B7",
  lime: "#A3E635",
  gold: "#E3B341",
  peach: "#FDBA74",
  coral: "#FF8A65",
  rose: "#FB7185",
  magenta: "#E879F9",
  lavender: "#C4B5FD",
  brown: "#B08968",
  slate: "#94A3B8",
} as const;

/**
 * The accent colours a key may be given by name (besides Auto, the item's own, and since 1.3
 * a colour of the user's own, "#RRGGBB"). Settings keep the name, never the colour. The first
 * ten are 1.1's, unchanged, so keys set up then look the same.
 */
export const ACCENTS: Readonly<Record<string, { name: string; colour: string }>> = {
  blue: { name: "Blue", colour: P.info },
  green: { name: "Green", colour: P.ok },
  amber: { name: "Amber", colour: P.warn },
  red: { name: "Red", colour: P.crit },
  purple: { name: "Purple", colour: P.purple },
  orange: { name: "Orange", colour: P.orange },
  teal: { name: "Teal", colour: P.water },
  pink: { name: "Pink", colour: P.pink },
  yellow: { name: "Yellow", colour: X.yellow },
  silver: { name: "Silver", colour: X.silver },
  indigo: { name: "Indigo", colour: A.indigo },
  sky: { name: "Sky", colour: A.sky },
  cyan: { name: "Cyan", colour: A.cyan },
  mint: { name: "Mint", colour: A.mint },
  lime: { name: "Lime", colour: A.lime },
  gold: { name: "Gold", colour: A.gold },
  peach: { name: "Peach", colour: A.peach },
  coral: { name: "Coral", colour: A.coral },
  rose: { name: "Rose", colour: A.rose },
  magenta: { name: "Magenta", colour: A.magenta },
  lavender: { name: "Lavender", colour: A.lavender },
  brown: { name: "Brown", colour: A.brown },
  slate: { name: "Slate", colour: A.slate },
  white: { name: "White", colour: X.white },
};

/** (1.3) The colour a key's setting names: one of ACCENTS by name, or the user's own "#RRGGBB" (uppercased); else none. */
export function colourOf(setting: unknown): string | undefined {
  if (typeof setting !== "string") return undefined;
  if (Object.prototype.hasOwnProperty.call(ACCENTS, setting)) return ACCENTS[setting]!.colour;
  return cleanHex(setting) ?? undefined;
}

/**
 * Every colour that may appear in what the plugin draws: our own tables, nothing from the server.
 * (1.3) Besides these, only a "#RRGGBB" the user put in a key's own settings (see colourOf).
 */
export const ALLOWED_COLOURS: ReadonlySet<string> = new Set([...Object.values(P), ...Object.values(X), ...Object.values(A)].map((c) => c.toUpperCase()));
