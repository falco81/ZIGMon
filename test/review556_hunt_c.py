#!/usr/bin/env python3
"""Hunt C: following the room thermometer, and fetching a missing authority.

  * Follow the room thermometer corrected one difference twice. Zigbee2MQTT
    answers the write of an offset with the head's whole state: the new
    offset beside the old, cached local_temperature. The report's time said
    "the head has reported since", so the next pass (after the interval, or
    a minute after "Match the room" by hand, which the job was not told of)
    took the old reading with the new offset and moved it as far again:
    room 25.6, head 27.5 -> -2, and then -4.
  * A CA Issuers (AIA) address that redirected was followed to ftp:// too -
    any host and port it named - and an answer that came a byte at a time
    held the fetch far past its ten seconds (the timeout is per read).

    python3 test/review556_hunt_c.py < /dev/null

Ports 20490-20491.
"""
import http.server
import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-hunt-c-'))
AIA_PORT, FTP_PORT = 20490, 20491
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


for k in list(os.environ):
    if k.lower() in ('http_proxy', 'https_proxy', 'all_proxy', 'ftp_proxy'):
        del os.environ[k]

sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 20492, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'log_file': '', 'state_dir': str(W / 'state'), 'preheat': False, 'webproxy': 0})
(W / 'state').mkdir()

HEAD, THERMO = '0xhead0001', '0xtherm001'
HEAD_EXPOSES = {'current_heating_setpoint': {'type': 'numeric', 'access': 7, 'min': 5, 'max': 35},
                'local_temperature': {'type': 'numeric', 'access': 1},
                'local_temperature_calibration': {'type': 'numeric', 'access': 7, 'min': -9, 'max': 9}}

d = zigmon.Daemon()
d.valve_take_over = lambda dev: None
d.sent = []
d.zigbee_switch = lambda dev, key, act, origin='', *a, **k: (d.sent.append((dev, key, act)) or (True, 'published'))
d.store.upsert_device({'id': HEAD, 'name': 'Head-Loznice', 'source': 'zigbee', 'kind': 'thermostat',
                       'exposes': HEAD_EXPOSES})
d.store.upsert_device({'id': THERMO, 'name': 'Temp-Loznice', 'source': 'zigbee', 'kind': 'sensor',
                       'exposes': {'temperature': {'type': 'numeric', 'access': 1}}})
d.store.set_meta('rooms', json.dumps([{'id': 'r1', 'name': 'Loznice'}]))
d.store._meta_cache.pop('rooms', None)
d.store.set_meta('room_of', json.dumps({HEAD: 'r1', THERMO: 'r1'}))
d.save_heating({'enabled': True, 'rooms': {'r1': {'mode': 'comfort', 'comfort_c': 26.0, 'thermometer': THERMO,
                                                  'follow_room': True}}, '_quiet': True})


def report(head_c=27.5, cal=0.0, room_c=25.6, head_at=None):
    now = time.time()
    d.live[HEAD] = {'payload': {'local_temperature': head_c, 'local_temperature_calibration': cal,
                                'current_heating_setpoint': 26.0, 'system_mode': 'heat'},
                    'ts': now if head_at is None else head_at, 'availability': 'online'}
    d.live[THERMO] = {'payload': {'temperature': room_c}, 'ts': now, 'availability': 'online'}
    d._heat_state_cache = None
    d._zbt_cache = None


def follow():
    del d.sent[:]
    try:
        d.heating_follow(force=True)
    except Exception as e:                               # noqa: BLE001
        check(False, 'heating_follow: %r' % e)
    return [s for s in d.sent if s[1] == 'local_temperature_calibration']


def age(minutes):
    for v in d._follow_memory().values():
        v['at'] -= minutes * 60


try:
    # ---- the echo of its own write ---------------------------------------------------------------
    print('follow: the echo of its own write is not a new reading')
    report()
    check(follow() == [(HEAD, 'local_temperature_calibration', 'set:=-2')], 'the first write: %r' % d.sent)
    age(31)
    # Zigbee2MQTT's answer to the write: the new offset, the head's old reading, now
    report(head_c=27.5, cal=-2.0)
    got = follow()
    check(not got, 'the same difference corrected twice on the write\'s echo (-2 then %r)' % got)
    # the head measures again with its new offset: on the room, nothing to do
    report(head_c=25.6, cal=-2.0)
    check(not follow(), 'written with the head on the room: %r' % d.sent)
    # later it drifts: followed as before
    report(head_c=26.6, cal=-2.0)
    check(follow() == [(HEAD, 'local_temperature_calibration', 'set:=-3')],
          'a real difference after the head measured again was not followed: %r' % d.sent)

    # ---- Match the room by hand, then the job ---------------------------------------------------
    print('"Match the room" by hand, then the follow job a minute later')
    d._follow_memory().clear()
    d.store.set_meta('heating_follow', '{}')
    report(head_c=27.5, cal=0.0)
    del d.sent[:]
    ok, message = d.calibrate_valve('zb:%s:current_heating_setpoint' % HEAD)
    check(ok and d.sent == [(HEAD, 'local_temperature_calibration', 'set:=-2')], 'by hand: %r %r' % (message, d.sent))
    report(head_c=27.5, cal=-2.0)                     # the echo
    got = follow()
    check(not got, 'the follow job corrected again what was matched by hand a moment before: %r' % got)
    age(31)
    got = follow()
    check(not got, 'corrected again on the echo half an hour later: %r' % got)
    report(head_c=27.0, cal=-2.0)                     # the head measured again, still warm
    check(follow() == [(HEAD, 'local_temperature_calibration', 'set:=-3.5')],
          'not followed once the head measured again: %r' % d.sent)
    # a head that went back to no offset (reset) with the old reading is not an echo
    age(31)
    report(head_c=25.6, cal=0.0, room_c=24.0)
    check(follow() == [(HEAD, 'local_temperature_calibration', 'set:=-1.5')],
          'a head reset to no offset was taken for an echo: %r' % d.sent)

    # ---- the AIA address -------------------------------------------------------------------------
    print('AIA: a redirect to ftp://, an answer a byte at a time')
    CONNECTED = []
    lsock = socket.socket()
    lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lsock.bind(('127.0.0.1', FTP_PORT))
    lsock.listen(5)
    lsock.settimeout(0.2)
    stop = threading.Event()

    def ftp_side():
        while not stop.is_set():
            try:
                c, _ = lsock.accept()
            except OSError:
                continue
            CONNECTED.append(time.time())
            try:
                c.sendall(b'421 no\r\n')
            except OSError:
                pass
            c.close()
    threading.Thread(target=ftp_side, daemon=True).start()

    ROOTPEM = (W / 'r.pem')
    zigmon.subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(W / 'r.key'),
                           '-out', str(ROOTPEM), '-subj', '/CN=Hunt C Root', '-days', '5'],
                          capture_output=True, stdin=zigmon.subprocess.DEVNULL, check=True)
    DER = zigmon.subprocess.run(['openssl', 'x509', '-in', str(ROOTPEM), '-outform', 'DER'], capture_output=True,
                                stdin=zigmon.subprocess.DEVNULL, check=True).stdout

    class Serve(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/ftp':
                self.send_response(302)
                self.send_header('Location', 'ftp://127.0.0.1:%d/int.der' % FTP_PORT)
                self.send_header('Content-Length', '0')
                self.end_headers()
            elif self.path == '/hop':
                self.send_response(302)
                self.send_header('Location', '/root.der')
                self.send_header('Content-Length', '0')
                self.end_headers()
            elif self.path == '/root.der':
                self.send_response(200)
                self.send_header('Content-Length', str(len(DER)))
                self.end_headers()
                self.wfile.write(DER)
            elif self.path == '/drip':
                self.send_response(200)
                self.send_header('Content-Length', '60')
                self.end_headers()
                for _ in range(60):
                    try:
                        self.wfile.write(b'x')
                        self.wfile.flush()
                    except OSError:
                        return
                    time.sleep(0.25)
            else:
                self.send_response(404)
                self.send_header('Content-Length', '0')
                self.end_headers()

        def log_message(self, *a):
            pass

    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', AIA_PORT), Serve)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:%d' % AIA_PORT

    got = d.tls_aia_fetch(base + '/hop')
    check(len(got) == 1 and 'BEGIN CERTIFICATE' in got[0], 'an http redirect is no longer followed: %r' % got)
    try:
        got = d.tls_aia_fetch(base + '/ftp')
        said = 'answered %r' % got
    except Exception as e:                               # noqa: BLE001
        said = 'refused: %s' % e
    time.sleep(0.5)
    check(not CONNECTED, 'a redirect to ftp:// was followed - it connected to port %d (%s)' % (FTP_PORT, said))

    d.TLS_AIA_TIMEOUT_S = 2
    t0 = time.time()
    try:
        d.tls_aia_fetch(base + '/drip')
        said = 'answered'
    except Exception as e:                               # noqa: BLE001
        said = 'refused: %s' % e
    took = time.time() - t0
    check(took < 6, 'an answer a byte at a time held the fetch %.1f s with 2 s the limit (%s)' % (took, said))
    stop.set()
    httpd.shutdown()
    httpd.server_close()
    lsock.close()
finally:
    try:
        d.store.close()
    except Exception:                                    # noqa: BLE001
        pass

print()
if bad:
    print('%d FAILED' % len(bad))
    sys.exit(1)
print('all good')
