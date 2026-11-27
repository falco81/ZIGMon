#!/usr/bin/env bash
# Builds ZIGMon for Stream Deck (Linux, macOS or Git Bash; Node.js 20+ and python3):
#   1. npm ci (exact versions from package-lock.json),
#   2. writes src/core/release-keys.generated.ts from ../deploy/release-keys/*.pub
#      (the keys updates must be signed with; a test checks the two agree),
#   3. draws the layouts and icons (scripts/gen-assets.ts) and runs the tests
#      (protocol, pairing, TLS pins, hold, dials, rendering, updates, end to end),
#   4. bundles the plugin and the property inspectors with rollup, then runs the bundle once
#      against a fake Stream Deck app and a fake ZIGMon (scripts/smoke.mjs),
#   5. `streamdeck validate`, then `streamdeck pack`; the package is rewritten with fixed
#      timestamps so the same sources give the same bytes (scripts/normalize-zip.py),
#   6. writes dist/com.zigmon.streamdeck.streamDeckPlugin and dist/plugin.json (the manifest
#      tools/make-release.sh signs into dist/plugin.json.sig - not made here).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"
sd="com.zigmon.streamdeck.sdPlugin"
file="com.zigmon.streamdeck.streamDeckPlugin"
dist="$here/dist"
stage="$here/out/pack"

version="$(node -p 'require("./package.json").version')"
grep -q "\"Version\": \"$version.0\"" "$sd/manifest.json" || { echo "manifest.json Version is not $version.0" >&2; exit 1; }
grep -q "PLUGIN_VERSION = \"$version\";" src/core/version.ts || { echo "src/core/version.ts is not $version" >&2; exit 1; }

export npm_config_fund=false npm_config_audit=false npm_config_update_notifier=false

echo "== dependencies"
npm ci --no-audit --no-fund

echo "== release keys"
node scripts/gen-release-keys.mjs

echo "== assets and tests"
rm -rf out
npx tsc -p tsconfig.test.json
node out/scripts/gen-assets.js
node --test --test-reporter=spec out/test/*.test.js

echo "== bundle"
npx rollup -c

echo "== smoke test of the built plugin (the real SDK, a fake Stream Deck app and a fake ZIGMon)"
node scripts/smoke.mjs
rm -rf "$sd/logs"

echo "== validate"
npx streamdeck validate "$sd" --no-update-check

echo "== pack"
rm -rf "$stage"
mkdir -p "$stage" "$dist"
if npx streamdeck pack "$sd" --output "$stage" --force --no-update-check --no-file-list; then
  python3 scripts/normalize-zip.py "$stage/$file" "$dist/$file"
else
  echo "note: streamdeck pack could not run here - zipping $sd the way it does" >&2
  python3 scripts/normalize-zip.py --from-dir "$sd" "$dist/$file"
fi

size="$(wc -c < "$dist/$file" | tr -d ' ')"
if command -v sha256sum >/dev/null 2>&1; then
  sha="$(sha256sum "$dist/$file" | cut -d' ' -f1)"
else
  sha="$(shasum -a 256 "$dist/$file" | cut -d' ' -f1)"
fi
# one line, these keys in this order, LF at the end: these exact bytes are what gets signed
printf '{"product":"ZIGMon for Stream Deck","file":"%s","version":"%s","size":%s,"sha256":"%s","requires":"Stream Deck 7.1, Windows 10/11"}\n' \
  "$file" "$version" "$size" "$sha" > "$dist/plugin.json"
if [ -f "$dist/plugin.json.sig" ]; then
  echo "note: dist/plugin.json.sig is from an earlier build - tools/make-release.sh signs the new plugin.json"
fi

echo
echo "plugin: $dist/$file ($size bytes)"
echo "json:   $(cat "$dist/plugin.json")"
