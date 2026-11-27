#!/usr/bin/env bash
# Builds ZIGMon Notifier for Windows (x64) - works on Linux, macOS or Windows (Git Bash)
# with the .NET 10 SDK:
#   1. runs the tests of the core (protocol, TLS pinning, filtering, settings),
#   2. draws the app icon (Assets/app.ico) from the same painter the tray icon uses,
#   3. publishes one self-contained, compressed ZigmonNotifier.exe,
#   4. zips it with the README to out/ZigmonNotifier-<version>-win-x64.zip.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"
version="1.0.0"
out="$here/out"
pub="$out/publish"
zip="$out/ZigmonNotifier-$version-win-x64.zip"

export DOTNET_CLI_TELEMETRY_OPTOUT=1
export DOTNET_NOLOGO=1

echo "== tests"
dotnet test ZigmonNotifier.Tests/ZigmonNotifier.Tests.csproj -c Release --nologo

echo "== icon"
dotnet run --project tools/IconGen/IconGen.csproj -c Release -- ZigmonNotifier/Assets/app.ico

echo "== publish"
rm -rf "$pub"
dotnet publish ZigmonNotifier/ZigmonNotifier.csproj -c Release -r win-x64 \
  --self-contained true \
  -p:EnableWindowsTargeting=true \
  -p:PublishSingleFile=true \
  -p:EnableCompressionInSingleFile=true \
  -p:IncludeNativeLibrariesForSelfExtract=true \
  -p:DebugType=none \
  -p:Version="$version" \
  -o "$pub" --nologo

exe="$pub/ZigmonNotifier.exe"
[ -f "$exe" ] || { echo "no exe produced" >&2; exit 1; }

echo "== zip"
rm -f "$zip"
stage="$out/stage"
rm -rf "$stage"
mkdir -p "$stage"
cp "$exe" "$stage/"
cp README.md "$stage/README.md"
cp NAVOD.md "$stage/NAVOD.md"
if command -v zip >/dev/null 2>&1; then
  (cd "$stage" && zip -q -9 "$zip" ZigmonNotifier.exe README.md NAVOD.md)
else
  python3 - "$stage" "$zip" <<'PY'
import sys, zipfile, os
stage, dest = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for name in ("ZigmonNotifier.exe", "README.md", "NAVOD.md"):
        z.write(os.path.join(stage, name), name)
PY
fi
rm -rf "$stage"

echo
echo "exe: $exe ($(du -h "$exe" | cut -f1))"
echo "zip: $zip ($(du -h "$zip" | cut -f1))"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$exe" "$zip"
fi
