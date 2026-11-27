#!/usr/bin/env python3
"""Rewrites a .streamDeckPlugin (a zip) made by `streamdeck pack` so the same plugin always
gives the same bytes: the CLI stamps every entry with the time of packing. The entries, their
order, names and permissions stay exactly as the CLI wrote them; only the timestamps are fixed
(2020-01-01) and each entry is deflated again at level 9.

With --from-dir it zips a .sdPlugin folder the way the CLI does instead (the folder itself as
the top entry, files sorted, .git/.env*/*.log/*.js.map left out) - for when the CLI cannot run.

    normalize-zip.py <in.streamDeckPlugin> <out.streamDeckPlugin>
    normalize-zip.py --from-dir <x.sdPlugin> <out.streamDeckPlugin>
"""
import os
import sys
import zipfile

STAMP = (2020, 1, 1, 0, 0, 0)


def entry(name, attr):
    info = zipfile.ZipInfo(name, date_time=STAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = attr
    info.create_system = 3
    return info


def from_zip(src, dest):
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest + ".tmp", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zout:
        for i in zin.infolist():
            zout.writestr(entry(i.filename, i.external_attr), zin.read(i.filename), compresslevel=9)
    os.replace(dest + ".tmp", dest)


def from_dir(folder, dest):
    folder = folder.rstrip("/")
    top = os.path.basename(folder)
    names = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in (".git", "logs"))
        for f in sorted(files):
            if f.startswith(".env") or f.endswith(".log") or f.endswith(".js.map"):
                continue
            names.append(os.path.relpath(os.path.join(root, f), folder).replace(os.sep, "/"))
    with zipfile.ZipFile(dest + ".tmp", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for n in sorted(names):
            with open(os.path.join(folder, n), "rb") as fh:
                z.writestr(entry(top + "/" + n, 0o644 << 16), fh.read(), compresslevel=9)
    os.replace(dest + ".tmp", dest)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--from-dir":
        from_dir(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 3:
        from_zip(sys.argv[1], sys.argv[2])
    else:
        sys.exit(__doc__)
