#!/bin/bash
# make-release.sh - the signed package of the version in this folder.
#
#   tools/make-release.sh /path/to/zigmon-release-1.key
#   tools/make-release.sh KEY --needs-cli "why" [--cli-command "sudo ./install.sh --upgrade"]
#                             [--cli-from-below X.Y.Z]
#
# (5.44) --needs-cli: this release must be put in on the command line (the
# dashboard and root's upgrade service refuse it, saying why and what to run).
# It is written into release.json at the top of the package, which MANIFEST
# lists - signed like every other file, so it cannot be stripped. With
# --cli-from-below only machines coming from a version older than that need the
# command line. release.json is also written, without the flag, whenever
# SYSTEM_LEVEL (zigmon.py, install.sh) is above 1, so the level is said. Beside
# the package go zigmon-X.Y.Z.release.json and its own signature (.sig), so the
# dashboard knows before fetching it. Default: no release.json, as before.
#
# Run from a clean checkout. Takes the files git knows (not release/, not
# LICENSE.md, not MANIFEST*), writes MANIFEST, signs it with the private key
# given - which is never copied, printed or kept - checks the signature
# against the public keys in deploy/release-keys, and leaves:
#
#   release/zigmon-X.Y.Z.tar.gz      the package, as the upgrade page takes it
#   MANIFEST, MANIFEST.sig           the same two files at the top of the
#                                    repository, so what is on GitHub is the
#                                    unpacked package, file for file
#
# (5.57) windows/dist/notifier.json, the manifest of ZIGMon Notifier the package
# carries, is signed here with the same key into windows/dist/notifier.json.sig
# (when that is missing or not by this key), checked against deploy/release-keys,
# and put in the package; a new signature is to be committed with the release.
# No windows/dist: a package without the app, as before.
#
# (5.59) streamdeck/dist/plugin.json, the manifest of ZIGMon for Stream Deck, is signed the
# same way into streamdeck/dist/plugin.json.sig; no streamdeck/dist: a package without it.
#
# The version is read from zigmon.py and must be the same in install.sh,
# tools/snort-debug.py and README.md (with an entry of its own there).
set -euo pipefail

KEY="${1:-}"
[[ -n "$KEY" && -f "$KEY" ]] || { echo "usage: $0 PRIVATE-KEY-FILE [--needs-cli WHY [--cli-command CMD] [--cli-from-below X.Y.Z]]"; exit 2; }
shift
# (5.44) a release that must be put in on the command line
NEEDS_CLI="" CLI_WHY="" CLI_COMMAND="sudo ./install.sh --upgrade" CLI_BELOW=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --needs-cli)      NEEDS_CLI="yes"; CLI_WHY="${2:-}"; shift 2 || { echo "--needs-cli WHY"; exit 2; } ;;
        --cli-command)    CLI_COMMAND="${2:-}"; shift 2 || { echo "--cli-command CMD"; exit 2; } ;;
        --cli-from-below) CLI_BELOW="${2:-}"; shift 2 || { echo "--cli-from-below X.Y.Z"; exit 2; } ;;
        *) echo "unknown option $1"; exit 2 ;;
    esac
done
[[ -z "$NEEDS_CLI" || -n "$CLI_WHY" ]] || { echo "--needs-cli wants a reason, in words"; exit 2; }
[[ -z "$CLI_BELOW" || "$CLI_BELOW" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "--cli-from-below X.Y.Z"; exit 2; }
[[ -z "$CLI_BELOW$NEEDS_CLI" || -n "$NEEDS_CLI" ]] || { echo "--cli-from-below goes with --needs-cli"; exit 2; }
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

V="$(sed -n "s/^__version__ = '\(.*\)'/\1/p" zigmon.py | head -n1)"
[[ -n "$V" ]] || { echo "no __version__ in zigmon.py"; exit 1; }
bad=""
grep -q "^VERSION=\"$V\"" install.sh || bad="$bad install.sh"
sed -n 6p tools/snort-debug.py | grep -q "zigmon-$V" || bad="$bad tools/snort-debug.py"
grep -q "^Current version: \*\*$V\*\*" README.md || bad="$bad README.md(current)"
grep -q "^$V — " README.md || bad="$bad README.md(changelog)"
[[ -z "$bad" ]] || { echo "the version $V is not said in:$bad"; exit 1; }
# (5.44) the system level: the same in zigmon.py and install.sh
SL="$(sed -n 's/^SYSTEM_LEVEL = \([0-9][0-9]*\).*/\1/p' zigmon.py | head -n1)"
[[ -n "$SL" ]] || SL=1
grep -q "^SYSTEM_LEVEL=$SL\b" install.sh || { echo "SYSTEM_LEVEL is $SL in zigmon.py and not in install.sh"; exit 1; }
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || { echo "commit first: the package is made from what git has"; exit 1; }
[[ ! -e index.php ]] || { echo "index.php at the top is not the dashboard (web/index.php is): git rm it"; exit 1; }
[[ ! -e "release/zigmon-$V.tar.gz" ]] || { echo "release/zigmon-$V.tar.gz is there already: a new version, not the same one again"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
S="$WORK/zigmon-$V"
mkdir -p "$S"
# (5.57) the desktop app's manifest, signed by the release key - the app checks it
# before it replaces itself with the exe the manifest describes
NTF_DIST="windows/dist"
NTF_SIG=""
if [[ -f "$NTF_DIST/notifier.json" ]]; then
    [[ -f "$NTF_DIST/ZigmonNotifier.exe" ]] || { echo "$NTF_DIST/notifier.json without $NTF_DIST/ZigmonNotifier.exe"; exit 1; }
    python3 -I - "$NTF_DIST/notifier.json" "$NTF_DIST/ZigmonNotifier.exe" <<'NTFCHECK' || exit 1
import hashlib, json, os, sys
raw = open(sys.argv[1], 'rb').read()
try:
    m = json.loads(raw.decode('utf-8'))
except ValueError:
    sys.exit('windows/dist/notifier.json does not read')
exe = open(sys.argv[2], 'rb').read()
if m.get('product') != 'ZIGMon Notifier' or m.get('file') != 'ZigmonNotifier.exe':
    sys.exit('windows/dist/notifier.json is not of ZIGMon Notifier')
if m.get('size') != len(exe) or m.get('sha256') != hashlib.sha256(exe).hexdigest():
    sys.exit('windows/dist/notifier.json does not describe windows/dist/ZigmonNotifier.exe (build it again: windows/build.sh)')
print('desktop app: ZIGMon Notifier %s, %d bytes' % (m.get('version'), len(exe)))
NTFCHECK
    openssl pkey -in "$KEY" -pubout -out "$WORK/release-key.pub" 2>/dev/null \
        || { echo "the private key does not read"; exit 1; }
    if [[ ! -f "$NTF_DIST/notifier.json.sig" ]] || ! openssl pkeyutl -verify -pubin -inkey "$WORK/release-key.pub" -rawin \
            -in "$NTF_DIST/notifier.json" -sigfile "$NTF_DIST/notifier.json.sig" >/dev/null 2>&1; then
        openssl pkeyutl -sign -inkey "$KEY" -rawin -in "$NTF_DIST/notifier.json" -out "$NTF_DIST/notifier.json.sig"
        echo "$NTF_DIST/notifier.json signed into $NTF_DIST/notifier.json.sig"
    fi
    ntf_ok=""
    for k in deploy/release-keys/*.pub; do
        if openssl pkeyutl -verify -pubin -inkey "$k" -rawin -in "$NTF_DIST/notifier.json" \
                -sigfile "$NTF_DIST/notifier.json.sig" >/dev/null 2>&1; then
            ntf_ok="$(basename "$k" .pub)"; break
        fi
    done
    [[ -n "$ntf_ok" ]] || { echo "$NTF_DIST/notifier.json.sig does not verify against deploy/release-keys"; exit 1; }
    echo "$NTF_DIST/notifier.json signed by $ntf_ok"
    if [[ -n "$(git status --porcelain -- "$NTF_DIST/notifier.json.sig")" ]]; then
        NTF_SIG="$NTF_DIST/notifier.json.sig"
        echo "$NTF_SIG is new: it must be committed with the release"
    fi
fi
# (5.59) the Stream Deck plugin's manifest, signed the same way - the plugin checks it
# before it installs the .streamDeckPlugin the manifest describes
SD_DIST="streamdeck/dist"
SD_SIG=""
if [[ -f "$SD_DIST/plugin.json" ]]; then
    [[ -f "$SD_DIST/com.zigmon.streamdeck.streamDeckPlugin" ]] \
        || { echo "$SD_DIST/plugin.json without $SD_DIST/com.zigmon.streamdeck.streamDeckPlugin"; exit 1; }
    python3 -I - "$SD_DIST/plugin.json" "$SD_DIST/com.zigmon.streamdeck.streamDeckPlugin" <<'SDCHECK' || exit 1
import hashlib, json, sys
raw = open(sys.argv[1], 'rb').read()
try:
    m = json.loads(raw.decode('utf-8'))
except ValueError:
    sys.exit('streamdeck/dist/plugin.json does not read')
plugin = open(sys.argv[2], 'rb').read()
if m.get('product') != 'ZIGMon for Stream Deck' or m.get('file') != 'com.zigmon.streamdeck.streamDeckPlugin':
    sys.exit('streamdeck/dist/plugin.json is not of ZIGMon for Stream Deck')
if m.get('size') != len(plugin) or m.get('sha256') != hashlib.sha256(plugin).hexdigest():
    sys.exit('streamdeck/dist/plugin.json does not describe streamdeck/dist/com.zigmon.streamdeck.streamDeckPlugin '
             '(build it again: streamdeck/build.sh)')
print('Stream Deck plugin: ZIGMon for Stream Deck %s, %d bytes' % (m.get('version'), len(plugin)))
SDCHECK
    [[ -f "$WORK/release-key.pub" ]] || openssl pkey -in "$KEY" -pubout -out "$WORK/release-key.pub" 2>/dev/null \
        || { echo "the private key does not read"; exit 1; }
    if [[ ! -f "$SD_DIST/plugin.json.sig" ]] || ! openssl pkeyutl -verify -pubin -inkey "$WORK/release-key.pub" -rawin \
            -in "$SD_DIST/plugin.json" -sigfile "$SD_DIST/plugin.json.sig" >/dev/null 2>&1; then
        openssl pkeyutl -sign -inkey "$KEY" -rawin -in "$SD_DIST/plugin.json" -out "$SD_DIST/plugin.json.sig"
        echo "$SD_DIST/plugin.json signed into $SD_DIST/plugin.json.sig"
    fi
    sd_ok=""
    for k in deploy/release-keys/*.pub; do
        if openssl pkeyutl -verify -pubin -inkey "$k" -rawin -in "$SD_DIST/plugin.json" \
                -sigfile "$SD_DIST/plugin.json.sig" >/dev/null 2>&1; then
            sd_ok="$(basename "$k" .pub)"; break
        fi
    done
    [[ -n "$sd_ok" ]] || { echo "$SD_DIST/plugin.json.sig does not verify against deploy/release-keys"; exit 1; }
    echo "$SD_DIST/plugin.json signed by $sd_ok"
    if [[ -n "$(git status --porcelain -- "$SD_DIST/plugin.json.sig")" ]]; then
        SD_SIG="$SD_DIST/plugin.json.sig"
        echo "$SD_SIG is new: it must be committed with the release"
    fi
fi
git ls-files | grep -v -E '^(release/|LICENSE.md$|MANIFEST$|MANIFEST.sig$|release.json$)' | while read -r f; do
    [[ -f "$f" ]] || continue
    mkdir -p "$S/$(dirname "$f")"
    cp -p "$f" "$S/$f"
done
# (5.57) the signature just made is in the package though git does not have it yet
if [[ -n "$NTF_SIG" ]]; then
    mkdir -p "$S/$NTF_DIST"
    cp -p "$NTF_SIG" "$S/$NTF_SIG"
fi
if [[ -n "$SD_SIG" ]]; then
    mkdir -p "$S/$SD_DIST"
    cp -p "$SD_SIG" "$S/$SD_SIG"
fi
cd "$S"
find . -name __pycache__ -prune -exec rm -rf {} +
# (5.44) release.json - before MANIFEST, so the signature covers it
if [[ -n "$NEEDS_CLI" || "$SL" -gt 1 ]]; then
    V="$V" SL="$SL" NEEDS_CLI="$NEEDS_CLI" CLI_WHY="$CLI_WHY" CLI_COMMAND="$CLI_COMMAND" CLI_BELOW="$CLI_BELOW" \
    python3 -I -c 'import json, os
e = os.environ
out = {"format": 1, "version": e["V"], "needs_cli": bool(e["NEEDS_CLI"]), "system_level": int(e["SL"])}
if e["NEEDS_CLI"]:
    out.update(why=e["CLI_WHY"], command=e["CLI_COMMAND"] or "sudo ./install.sh --upgrade")
    if e["CLI_BELOW"]:
        out["only_from_below"] = e["CLI_BELOW"]
print(json.dumps(out, indent=1))' > release.json
fi
find . -type f ! -name 'MANIFEST*' -printf '%P\n' | LC_ALL=C sort | while read -r f; do
    printf '%s  %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$f"
done > MANIFEST
openssl pkeyutl -sign -inkey "$KEY" -rawin -in MANIFEST -out MANIFEST.sig
ok=""
for k in deploy/release-keys/*.pub; do
    if openssl pkeyutl -verify -pubin -inkey "$k" -rawin -in MANIFEST -sigfile MANIFEST.sig >/dev/null 2>&1; then
        ok="$(basename "$k" .pub)"; break
    fi
done
[[ -n "$ok" ]] || { echo "the signature does not verify against deploy/release-keys"; exit 1; }
cd "$WORK"
mkdir -p "$HERE/release"
tar czf "$HERE/release/zigmon-$V.tar.gz" "zigmon-$V"
cp "$S/MANIFEST" "$S/MANIFEST.sig" "$HERE/"
# (5.44) release.json at the top as well (the unpacked package, file for file),
# and beside the package with a signature of its own for the dashboard's look
if [[ -f "$S/release.json" ]]; then
    cp "$S/release.json" "$HERE/release.json"
    cp "$S/release.json" "$HERE/release/zigmon-$V.release.json"
    openssl pkeyutl -sign -inkey "$KEY" -rawin -in "$S/release.json" -out "$HERE/release/zigmon-$V.release.json.sig"
    echo "release.json: $(tr -d '\n' < "$S/release.json")"
elif [[ -f "$HERE/release.json" ]]; then
    rm -f "$HERE/release.json"
    echo "release.json of an earlier release taken away from the top: git rm --cached release.json"
fi
cd "$HERE"
# the same check the upgrade page and root make before anything is put in
ZIGMON_RELEASE_KEYS=deploy/release-keys python3 -I deploy/zigmon_upgrade.py --inspect "release/zigmon-$V.tar.gz" \
    | python3 -c 'import json, sys
d = json.load(sys.stdin)
if d.get("version") is None or d.get("said"):
    sys.exit("the package was refused: %s" % d.get("said"))
print("checked: zigmon %s, signed by %s, %d files" % (d["version"], d["signed_by"], d["files"]))'
echo "release/zigmon-$V.tar.gz signed by $ok"
if [[ -f "$HERE/release.json" ]]; then
    echo "now:  git add release/zigmon-$V.tar.gz release/zigmon-$V.release.json release/zigmon-$V.release.json.sig release.json MANIFEST MANIFEST.sig${NTF_SIG:+ $NTF_SIG}${SD_SIG:+ $SD_SIG} && git commit -m 'Release $V' && git push"
else
    echo "now:  git add release/zigmon-$V.tar.gz MANIFEST MANIFEST.sig${NTF_SIG:+ $NTF_SIG}${SD_SIG:+ $SD_SIG} && git commit -m 'Release $V' && git push"
fi
