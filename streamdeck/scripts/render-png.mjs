// Renders the plugin icon (imgs/plugin/marketplace.svg) to the PNGs the manifest needs
// (256 x 256 and @2x 512 x 512) with Playwright's Chromium. Run by hand when the icon changes;
// the PNGs are committed, so build.sh does not need a browser.
//   node scripts/render-png.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const here = dirname(fileURLToPath(import.meta.url));
const dir = join(here, "..", "com.zigmon.streamdeck.sdPlugin", "imgs", "plugin");
const svg = readFileSync(join(dir, "marketplace.svg"), "utf8");

const browser = await chromium.launch();
try {
  for (const [size, name] of [[256, "marketplace.png"], [512, "marketplace@2x.png"]]) {
    const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
    const scaled = svg.replace(/width="256" height="256"/, `width="${size}" height="${size}"`);
    await page.setContent(`<html><body style="margin:0;background:transparent">${scaled}</body></html>`);
    const png = await page.locator("svg").screenshot({ omitBackground: true });
    writeFileSync(join(dir, name), png);
    await page.close();
  }
} finally {
  await browser.close();
}
console.log("plugin icon PNGs written");
