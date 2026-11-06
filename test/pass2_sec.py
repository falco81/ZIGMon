#!/usr/bin/env python3
"""5.44.1, pass 2: the boundary between the zigmon account and root. Each
check here failed on 5.44.0:

  * a database put back: the files beside it (-wal, -shm, -journal) were
    given back to the service by their names, in the zigmon account's own
    folder - a link there had root hand the file it points at to zigmon;
  * the Zigbee2MQTT backup put back: written by its path into the state
    folder's backups/, which the zigmon account may replace with a link to a
    folder of root's - it now goes in through the folder's descriptor.

The root helper is run in-process against a folder that stands in for the
machine, as test/root.py and test/upgrade.py do. Needs root (the checks are
about owners) and openssl.

    python3 test/pass2_sec.py
"""
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-pass2-sec-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def finish():
    shutil.rmtree(str(W), ignore_errors=True)
    print('pass2_sec: %s' % ('%d failed' % len(bad) if bad else 'all good'))
    sys.stdout.flush()
    os._exit(1 if bad else 0)


if os.geteuid() != 0:
    print('pass2_sec: needs root (the checks are about who owns a file) - skipped')
    finish()

STATE, ETC, OWN, FULL = W / 'state', W / 'etc', W / 'own', W / 'full'
for d in (STATE / 'root', STATE / 'backups', ETC / 'zigmon', ETC / 'nginx' / 'conf.d', OWN, FULL,
          W / 'elsewhere'):
    d.mkdir(parents=True)
DB = STATE / 'history.db'
con = sqlite3.connect(str(DB))
con.execute('PRAGMA journal_mode=WAL')
con.executescript('CREATE TABLE meta(key, value);')
con.commit()
con.close()
(ETC / 'zigmon' / 'config.json').write_text(json.dumps({'db_file': str(DB)}))
os.environ.update(ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(OWN), ZIGMON_FULL_DIR=str(FULL),
                  ZIGMON_CONFIG=str(ETC / 'zigmon' / 'config.json'), ZIGMON_NO_SERVICES='1',
                  ZIGMON_FS_ROOT=str(W), ZIGMON_USER='root', ZIGMON_NGINX_TEST='true',
                  ZIGMON_NGINX_CONF=str(ETC / 'nginx' / 'conf.d' / 'zigmon.conf'),
                  ZIGMON_CERT_DIR=str(ETC / 'nginx' / 'certs'), ZIGMON_MOSQ_DIR=str(ETC / 'mosquitto'),
                  ZIGMON_FW_FILE4=str(ETC / 'iptables'), ZIGMON_FW_FILE6=str(ETC / 'ip6tables'),
                  ZIGMON_FIREWALL_CMD='/nonexistent/firewall-cmd')
spec = importlib.util.spec_from_file_location('zigmon_root_p2', str(HERE / 'deploy' / 'zigmon_root.py'))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

try:
    # ---- the files beside the database, given back by name -------------------------
    print('a database put back: the files beside it are not followed')
    victim = W / 'elsewhere' / 'shadow'
    victim.write_text('')                       # an empty file of root's: SQLite takes it
    os.chown(str(victim), 0, 0)
    journal = Path(str(DB) + '-journal')
    os.symlink(str(victim), str(journal))
    R.accounts_into(str(DB), {'accounts': [], 'signins': [], 'passkeys': []}, (4321, 4321))
    st = victim.stat()
    check((st.st_uid, st.st_gid) == (0, 0),
          'a link beside the database had root give the file it points at to %d:%d' % (st.st_uid, st.st_gid))
    check(DB.stat().st_uid == 4321, 'the database itself was not given back to the service')
    if journal.is_symlink():
        journal.unlink()

    # ---- the Zigbee2MQTT backup put back into a folder made a link ------------------
    print('the Zigbee2MQTT backup put back: never into a link put in place of backups/')
    (STATE / 'backups' / 'zigbee2mqtt-2026-11-01.zip').write_bytes(b'PK\x05\x06' + b'\0' * 18)
    made = R.full_make('the check', keep=7)
    check('zigbee' in made['parts'], 'the backup made has no Zigbee2MQTT part: %r' % made)
    shutil.rmtree(str(STATE / 'backups'))
    R.FD.clear()
    os.symlink(str(W / 'elsewhere'), str(STATE / 'backups'))
    try:
        R.full_restore(str(FULL / made['file']), ['zigbee'], from_page=True, before=False)
    except Exception as e:                              # noqa: BLE001 - refusing is right too
        print('  (refused: %s)' % str(e)[:120])
    check(not (W / 'elsewhere' / 'zigbee2mqtt-2026-11-01.zip').exists(),
          'root wrote the Zigbee2MQTT backup through a link put in place of backups/')
    # and into a real folder it still goes back
    (STATE / 'backups').unlink()
    (STATE / 'backups').mkdir()
    R.FD.clear()
    said = R.full_restore(str(FULL / made['file']), ['zigbee'], from_page=True, before=False)
    zipf = STATE / 'backups' / 'zigbee2mqtt-2026-11-01.zip'
    check(zipf.is_file() and zipf.read_bytes().startswith(b'PK'),
          'the Zigbee2MQTT backup did not go back into the state folder: %r' % said)
except Exception as e:                                  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(False, 'the check broke: %s' % e)
finish()
