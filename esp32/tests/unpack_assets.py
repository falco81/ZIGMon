#!/usr/bin/env python3
"""Unpacks esp32/ZigmonGateway/web_assets.h (the gzipped arrays) into a directory, so the exact
bytes the firmware serves can be checked (node --check) and rendered (webmock.py with WEB_DIR).

    python3 esp32/tests/unpack_assets.py <out dir>
"""
import gzip
import re
import sys
from pathlib import Path

hdr = (Path(__file__).resolve().parent.parent / 'ZigmonGateway' / 'web_assets.h').read_text()
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
arrays = {m.group(1): bytes(int(x, 16) for x in re.findall(r'0x([0-9a-f]{2})', m.group(2)))
          for m in re.finditer(r'static const uint8_t (WEB_ASSET_\d+)\[\] PROGMEM = \{(.*?)\};', hdr, re.S)}
n = 0
for path, var in re.findall(r'\{"(/[^"]+)", "[^"]+", (WEB_ASSET_\d+), sizeof', hdr):
    (out / path.lstrip('/')).write_bytes(gzip.decompress(arrays[var]))
    n += 1
print('unpacked %d files into %s' % (n, out))
