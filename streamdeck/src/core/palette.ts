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
