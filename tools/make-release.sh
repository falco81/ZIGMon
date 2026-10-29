#!/bin/bash
# make-release.sh - the signed package of the version in this folder.
#
#   tools/make-release.sh /path/to/zigmon-release-1.key
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
# The version is read from zigmon.py and must be the same in install.sh,
# tools/snort-debug.py and README.md (with an entry of its own there).
set -euo pipefail

KEY="${1:-}"
[[ -n "$KEY" && -f "$KEY" ]] || { echo "usage: $0 PRIVATE-KEY-FILE"; exit 2; }
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
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || { echo "commit first: the package is made from what git has"; exit 1; }
[[ ! -e index.php ]] || { echo "index.php at the top is not the dashboard (web/index.php is): git rm it"; exit 1; }
[[ ! -e "release/zigmon-$V.tar.gz" ]] || { echo "release/zigmon-$V.tar.gz is there already: a new version, not the same one again"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
S="$WORK/zigmon-$V"
mkdir -p "$S"
git ls-files | grep -v -E '^(release/|LICENSE.md$|MANIFEST$|MANIFEST.sig$)' | while read -r f; do
    [[ -f "$f" ]] || continue
    mkdir -p "$S/$(dirname "$f")"
    cp -p "$f" "$S/$f"
done
cd "$S"
find . -name __pycache__ -prune -exec rm -rf {} +
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
cd "$HERE"
# the same check the upgrade page and root make before anything is put in
ZIGMON_RELEASE_KEYS=deploy/release-keys python3 -I deploy/zigmon_upgrade.py --inspect "release/zigmon-$V.tar.gz" \
    | python3 -c 'import json, sys
d = json.load(sys.stdin)
if d.get("version") is None or d.get("said"):
    sys.exit("the package was refused: %s" % d.get("said"))
print("checked: zigmon %s, signed by %s, %d files" % (d["version"], d["signed_by"], d["files"]))'
echo "release/zigmon-$V.tar.gz signed by $ok"
echo "now:  git add release/zigmon-$V.tar.gz MANIFEST MANIFEST.sig && git commit -m 'Release $V' && git push"
