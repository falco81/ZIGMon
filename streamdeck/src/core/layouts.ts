/**
 * The Stream Deck + touch-strip layouts (200x100 per dial), one per dial action. Written to
 * com.zigmon.streamdeck.sdPlugin/layouts/*.json by scripts/gen-assets.mjs; a test checks the
 * files match these and validates them against @elgato/schemas' layout schema.
 * Text is drawn by Stream Deck itself (crisp at any scale); the pictures - bars, sliders, the
 * thermostat's arc, the window and its blind, sparklines, the hold ring - are our SVG pixmaps.
 */
import { P } from "./palette.js";

type Rect = [number, number, number, number];
export interface LayoutItem {
  key: string;
  type: "pixmap" | "text" | "bar" | "gbar";
  rect: Rect;
  zOrder?: number;
  value?: string | number;
  font?: { size: number; weight: number };
  color?: string;
  alignment?: "left" | "center" | "right";
  "text-overflow"?: "clip" | "ellipsis" | "fade";
  background?: string;
}
export interface Layout {
  $schema: string;
  id: string;
  controller: "Encoder";
  items: LayoutItem[];
}

const SCHEMA = "https://schemas.elgato.com/streamdeck/plugins/layout.json";

const t = (key: string, rect: Rect, size: number, weight: number, color: string, z = 1, alignment: "left" | "center" | "right" = "left"): LayoutItem => ({
  key, type: "text", rect, zOrder: z, value: "", font: { size, weight }, color, alignment, "text-overflow": "ellipsis",
});
const px = (key: string, rect: Rect, z = 0): LayoutItem => ({ key, type: "pixmap", rect, zOrder: z, value: "" });

export const LAYOUTS: Record<string, Layout> = {
  control: {
    $schema: SCHEMA, id: "zigmon-control", controller: "Encoder",
    items: [
      px("icon", [12, 12, 40, 40], 1),
      t("name", [60, 10, 132, 18], 13, 600, P.dim),
      t("value", [60, 28, 132, 28], 22, 700, P.text),
      px("art", [12, 62, 176, 30], 1),
    ],
  },
  reading: {
    $schema: SCHEMA, id: "zigmon-reading", controller: "Encoder",
    items: [
      px("art", [0, 0, 200, 100], 0),
      px("icon", [12, 10, 22, 22], 1),
      t("name", [40, 10, 120, 22], 13, 600, P.dim, 2),
      t("value", [12, 34, 176, 38], 30, 700, P.text, 2),
    ],
  },
  thermostat: {
    $schema: SCHEMA, id: "zigmon-thermostat", controller: "Encoder",
    items: [
      px("art", [0, 0, 200, 100], 0),
      t("name", [12, 6, 112, 18], 12, 600, P.dim, 1),
      t("value", [12, 24, 112, 34], 28, 700, P.text, 1),
      t("target", [12, 58, 112, 20], 15, 700, P.orange, 1),
      t("mode", [12, 78, 112, 18], 12, 600, P.dim, 1),
    ],
  },
  dimmer: {
    $schema: SCHEMA, id: "zigmon-dimmer", controller: "Encoder",
    items: [
      px("icon", [12, 12, 36, 36], 1),
      t("name", [56, 10, 136, 18], 13, 600, P.dim),
      t("value", [56, 26, 136, 28], 22, 700, P.text),
      px("art", [12, 60, 176, 32], 1),
    ],
  },
  blinds: {
    $schema: SCHEMA, id: "zigmon-blinds", controller: "Encoder",
    items: [
      px("art", [138, 8, 52, 84], 0),
      t("name", [12, 10, 122, 18], 13, 600, P.dim, 1),
      t("value", [12, 30, 122, 30], 24, 700, P.text, 1),
      t("sub", [12, 66, 122, 20], 13, 600, P.purple, 1),
    ],
  },
};

/** The manifest's Encoder.layout path of each action. */
export function layoutPath(name: keyof typeof LAYOUTS | string): string {
  return "layouts/" + name + ".json";
}
