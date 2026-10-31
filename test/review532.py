#!/usr/bin/env python3
"""5.32: what running the suite on Python 3.14 brought out. Each check fails
on 5.31.0.

  * A flush waits for the write the writer is in the middle of, not only for
    the queue to be empty: the queue is empty the moment the writer takes the
    last write off it, and a backup, a restore or a reading of the log that
    went by that alone came in ahead of the write.
  * The modem's status is not lost to the AT+CMMS check: both keep five
    minutes and start on the same beat; the status, finding the box taken,
    was skipped for a whole round - every round - and the modem's card went
    silent. It is asked again a few seconds later.

    python3 test/review532.py
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review532-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 0, 'token_file': str(W / 'run' / 'api-token'),
                      'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '',
                      'state_dir': str(W / 'state')})
(W / 'state').mkdir()

# 1. a flush waits for the write in hand
st = zigmon.Storage(str(W / 'flush.db'))
landed = []
going = threading.Event()


def slow_write():
    going.set()
    time.sleep(0.6)
    landed.append(1)


st._defer(slow_write)
going.wait(5)
check(not st._wq, 'the writer did not take the write')
t0 = time.time()
st.flush(5.0)
check(landed == [1], 'flush came back before the write in hand had landed (%.2f s)' % (time.time() - t0))

# and many: every one landed when flush returns
done = []
for i in range(300):
    st._defer(done.append, i)
st.flush(10.0)
check(len(done) == 300, 'flush came back with %d of 300 writes landed' % len(done))
# an empty queue: back at once
t0 = time.time()
st.flush(5.0)
check(time.time() - t0 < 0.5, 'a flush with nothing queued waited %.2f s' % (time.time() - t0))

# 2. the modem's status asked again soon after losing the box to AT+CMMS
d = zigmon.Daemon()
zigmon.CONFIG.update({'sms_enabled': 1, 'sms_push': 1, 'sms_poll_s': 0, 'sms_api': 'rest', 'sms_status_s': 300})
asked = []


def gateway(path, method='GET', payload=None, retry=True, timeout=None):
    asked.append(path)
    if path == '/modems/status':
        return [{'id': '1-1', 'operator': 'T-Mobile CZ', 'rssi': -51, 'conntype': 'LTE'}]
    return []


d._rest, d.sms_ready, d._sms_rest, d.sms_modem_id = gateway, (lambda: True), (lambda: True), (lambda: '1-1')
d._sms_sending = d._sms_sent_at = 0
d._sms_status_busy = False
d._sms_counted_inbox_at = 0
# the CMMS check holds the box for two seconds, from the first beat
d._sms_cmms_checked = 0


def cmms_beat():
    with d._sms_send_lock:
        time.sleep(2.0)


d.sms_cmms_beat = cmms_beat
d._stop.clear()
timer = threading.Thread(target=d.timer_loop, daemon=True)
timer.start()
deadline = time.time() + 12
while time.time() < deadline and '/modems/status' not in asked:
    time.sleep(0.2)
d._stop.set()
timer.join(5)
check('/modems/status' in asked,
      'the modem\'s status, skipped while AT+CMMS had the box, was not asked again within 12 s '
      '(it waits the whole %d s)' % zigmon.CONFIG['sms_status_s'])

print('review532: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
os._exit(1 if bad else 0)
