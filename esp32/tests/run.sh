#!/usr/bin/env bash
# ZIGMon ESP32 Gateway: native checks of the firmware.
#
#  1. Unit tests of the portable parts (Yeelock packets, request signing and verification,
#     the pairing proof, PBKDF2, the CLI tokenizer and line editor, the replay ring, the
#     event ring, sessions/lockout), built with g++ against a vendored SHA-256/SHA-1
#     (tests/vendor/mini_sha.h) instead of mbedTLS. They assert PROTOCOL.md section 7.
#  2. A syntax check (g++ -fsyntax-only) of EVERY .cpp and the .ino of the sketch against the
#     stub headers in tests/stubs/ (Arduino, ESP-IDF, mbedTLS, NimBLE-Arduino 1.4, ArduinoJson
#     7). The stubs mirror the real signatures used, so most API mistakes are caught.
#
# Usage: esp32/tests/run.sh            (needs only g++)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
sketch="$here/../ZigmonGateway"
out="${TMPDIR:-/tmp}/zigmon-gw-tests"
mkdir -p "$out"
CXX="${CXX:-g++}"
WARN="-Wall -Wextra -Wno-unused-parameter"
# AddressSanitizer + UBSan when the compiler has them.
SAN="-fsanitize=address,undefined -fno-omit-frame-pointer"
echo "int main(){}" | "$CXX" -x c++ $SAN - -o "$out/san" 2>/dev/null || SAN=""

echo "== unit tests"
"$CXX" -std=gnu++17 -O1 $WARN -Werror -g $SAN \
  -I"$here" \
  "$here/test_main.cpp" "$here/shim_crypto.cpp" \
  "$sketch/core_util.cpp" "$sketch/core_crypto_portable.cpp" "$sketch/core_proto.cpp" \
  "$sketch/core_eventring.cpp" "$sketch/core_mem.cpp" "$sketch/core_cliline.cpp" \
  "$sketch/core_authlogic.cpp" "$sketch/yeelock_proto.cpp" "$sketch/yeelock_codes.cpp" \
  -o "$out/unit"
"$out/unit"

echo
echo "== syntax check of the whole sketch against tests/stubs"
fails=0
# Each target the firmware supports gets its own pass, so per-target #ifs are exercised.
check() {  # check <label> <extra defines...>
  local label="$1"; shift
  for f in "$sketch"/*.cpp "$sketch"/ZigmonGateway.ino; do
    if ! "$CXX" -std=gnu++17 -fsyntax-only $WARN -Werror "$@" \
        -I"$here/stubs" -I"$sketch" -x c++ -include Arduino.h "$f" 2>"$out/syntax.log"; then
      echo "FAIL [$label] $(basename "$f")"
      cat "$out/syntax.log"
      fails=$((fails + 1))
    fi
  done
  echo "  $label: checked $(ls "$sketch"/*.cpp | wc -l) .cpp files + the .ino"
}
base="-DESP_PLATFORM -DARDUINO=10819 -DARDUINO_ARCH_ESP32"
for target in ${TARGETS:-ESP32S3 ESP32 ESP32C3}; do
  check "$target" $base -DCONFIG_IDF_TARGET_${target}=1
done
# The optional builds: no async long poll (IDF < 5.1), no cloud import.
check "ESP32S3, GW_HTTPD_ASYNC=0" $base -DCONFIG_IDF_TARGET_ESP32S3=1 -DGW_HTTPD_ASYNC=0
check "ESP32S3, GW_YEELOCK_CLOUD=0" $base -DCONFIG_IDF_TARGET_ESP32S3=1 -DGW_YEELOCK_CLOUD=0
if [ "$fails" -ne 0 ]; then
  echo "$fails syntax failure(s)"
  exit 1
fi
echo "syntax OK"
