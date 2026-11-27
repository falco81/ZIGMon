import commonjs from "@rollup/plugin-commonjs";
import nodeResolve from "@rollup/plugin-node-resolve";
import typescript from "@rollup/plugin-typescript";

const sdPlugin = "com.zigmon.streamdeck.sdPlugin";

/**
 * Two bundles: the plugin itself (Node 24, as Stream Deck runs it) and the property
 * inspectors' shared script (a plain browser script). Not minified: the bundle stays
 * readable, and the build is the same bytes every time.
 * @type {import('rollup').RollupOptions[]}
 */
export default [
  {
    input: "src/plugin.ts",
    output: { file: `${sdPlugin}/bin/plugin.js`, format: "es", sourcemap: false },
    plugins: [
      {
        name: "watch-externals",
        buildStart() {
          this.addWatchFile(`${sdPlugin}/manifest.json`);
        },
      },
      typescript({ tsconfig: "./tsconfig.json", include: ["src/**/*.ts"], exclude: ["src/pi/**"] }),
      nodeResolve({ browser: false, exportConditions: ["node"], preferBuiltins: true }),
      commonjs(),
      {
        name: "emit-module-package-file",
        generateBundle() {
          this.emitFile({ fileName: "package.json", source: `{ "type": "module" }`, type: "asset" });
        },
      },
    ],
  },
  {
    input: "src/pi/pi.ts",
    output: { file: `${sdPlugin}/ui/pi.js`, format: "iife", name: "ZigmonPI", sourcemap: false },
    plugins: [typescript({ tsconfig: "./tsconfig.json", include: ["src/pi/**/*.ts", "src/core/icons.ts", "src/core/palette.ts", "src/core/svg.ts", "src/core/render.ts"] }), nodeResolve({ browser: true })],
  },
];
