#!/usr/bin/env python3
"""A fake ZIGMon ESP32 Gateway (esp32/PROTOCOL.md, protocol v1), for the tests and the screenshots.

    python3 test/mockesp.py 20361            # prints the fingerprint and a pairing code

HTTPS on its own self-signed EC P-256 certificate (made here: the cryptography package when it
is installed, else the openssl command), pairing by a 6-digit code (used once, 10 minutes, five
wrong proofs lock pairing for 15 minutes), every later request's signature, time and nonce
checked, every answer signed back with X-Gw-Sig, describe / state / events (a long poll) /
command (202, then the result as an event) / unpair. Two fake Yeelock locks and a fake sensor.

What the tests turn: stop() and start() (offline and back, or back with another certificate),
reboot() (a new boot id, seq from 0, perhaps a new entity), bad_sig (answers signed wrong),
replay (each answer is the one given to an earlier request), fail_next (a lock that does not
answer), push() (a sensor's new value).
"""
import collections
import hashlib
import hmac
import json
import os
import secrets
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

GW_ID = 'a1b2c3d4e5f6'


def make_cert(where, cn='zigmon-gw-d4e5f6'):
    """(cert.pem, key.pem, sha256 of the DER) - EC P-256, self-signed, as the firmware makes it."""
    cert, key = os.path.join(where, 'cert.pem'), os.path.join(where, 'key.pem')
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        import datetime
        k = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
        now = datetime.datetime.now(datetime.timezone.utc)
        c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
             .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
             .not_valid_after(now + datetime.timedelta(days=7300)).sign(k, hashes.SHA256()))
        with open(cert, 'wb') as f:
            f.write(c.public_bytes(serialization.Encoding.PEM))
        with open(key, 'wb') as f:
            f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
        der = c.public_bytes(serialization.Encoding.DER)
    except ImportError:
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes',
                        '-keyout', key, '-out', cert, '-days', '7300', '-subj', '/CN=' + cn],
                       check=True, capture_output=True)
        der = subprocess.run(['openssl', 'x509', '-in', cert, '-outform', 'DER'], check=True,
                             capture_output=True).stdout
    return cert, key, hashlib.sha256(der).hexdigest()


def sha(b):
    return hashlib.sha256(b or b'').hexdigest()


class FakeGateway(object):
    def __init__(self, port, host='127.0.0.1', name='Hall gateway'):
        self.port, self.host, self.name = port, host, name
        self.dir = tempfile.mkdtemp(prefix='mockesp-')
        self.new_cert()
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)
        self.key = None
        self.zigmon = None
        self.code = None                 # (code, until)
        self.wrong = 0
        self.locked_until = 0.0
        self.nonces = collections.deque(maxlen=64)
        self.seen_nonces = []            # every nonce ever received, for the tests
        self.requests = []               # (method, path) of every request
        self.boot = secrets.token_hex(4)
        self.seq = 0
        self.events = []
        self.bad_sig = False
        self.replay = False
        self.last_answer = None
        self.fail_next = set()           # actions that fail once
        self.server = None
        self.clock_set = False
        self.entities = [
            {'id': 'yeelock.front', 'module': 'yeelock', 'type': 'lock', 'name': 'Front drawer',
             'actions': ['open', 'unlock', 'lock', 'refresh'],
             'attrs': [{'key': 'battery', 'label': 'Battery', 'type': 'number', 'unit': '%', 'min': 0, 'max': 100}],
             'confirm': ['open', 'unlock']},
            {'id': 'yeelock.cabinet', 'module': 'yeelock', 'type': 'lock', 'name': 'Medicine cabinet',
             'actions': ['open', 'unlock', 'lock', 'refresh'],
             'attrs': [{'key': 'battery', 'label': 'Battery', 'type': 'number', 'unit': '%', 'min': 0, 'max': 100}],
             'confirm': ['open', 'unlock']},
            {'id': 'climate.box', 'module': 'climate', 'type': 'sensor', 'name': 'Cabinet temperature',
             'actions': [], 'attrs': [], 'unit': '°C', 'confirm': []}]
        self.states = {
            'yeelock.front': {'available': True, 'value': 'locked', 'busy': False, 'attrs': {'battery': 87},
                              'last': {'action': 'lock', 'ok': True, 'at': int(time.time()) - 3600, 'msg': ''}},
            'yeelock.cabinet': {'available': True, 'value': 'unknown', 'busy': False, 'attrs': {'battery': 41},
                                'last': None},
            'climate.box': {'available': True, 'value': 21.5, 'busy': False, 'attrs': {}, 'last': None}}

    # -- the certificate, the code --
    def new_cert(self):
        where = tempfile.mkdtemp(dir=self.dir)
        self.cert, self.keyfile, self.fingerprint = make_cert(where)
        return self.fingerprint

    def new_code(self):
        with self.lock:
            self.code = ('%06d' % secrets.randbelow(1000000), time.time() + 600)
            return self.code[0]

    # -- the server --
    def start(self, new_cert=False):
        if new_cert:
            self.new_cert()
        gw = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *a):
                pass

            def do_GET(self):
                gw.handle(self, 'GET')

            def do_POST(self):
                gw.handle(self, 'POST')

        class Server(ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                pass                     # a client that went away mid-answer (a stopped poll) is no news
        srv = Server((self.host, self.port), Handler)
        srv.daemon_threads = True
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.cert, self.keyfile)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        self.server = srv
        threading.Thread(target=srv.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True).start()
        return self

    def stop(self):
        srv, self.server = self.server, None
        if srv is not None:
            srv.shutdown()
            srv.server_close()
        with self.cond:
            self.cond.notify_all()

    def reboot(self, add=None):
        """A restart: a new boot id, the events from 0 - and perhaps a module that came with it."""
        with self.cond:
            self.boot = secrets.token_hex(4)
            self.seq = 0
            self.events = []
            if add:
                self.entities.append(add[0])
                self.states[add[0]['id']] = add[1]
            self.cond.notify_all()

    def push(self, entity, what='', **changes):
        with self.cond:
            st = self.states[entity]
            st.update(changes)
            self.seq += 1
            self.events.append({'seq': self.seq, 'entity': entity, 'state': json.loads(json.dumps(st)), 'what': what})
            self.events = self.events[-100:]
            self.cond.notify_all()

    # -- answering --
    def answer(self, h, status, obj, nonce=None, sign=True):
        body = json.dumps(obj).encode()
        heads = {'Content-Type': 'application/json'}
        if sign and self.key is not None and nonce is not None:
            sig = hmac.new(self.key, ('resp\n%s\n%d\n%s' % (nonce, status, sha(body))).encode(), hashlib.sha256).hexdigest()
            if self.bad_sig:
                sig = hmac.new(b'not the key', sig.encode(), hashlib.sha256).hexdigest()
            heads['X-Gw-Sig'] = sig
            if self.replay and self.last_answer is not None:
                status, body, heads = self.last_answer          # an old answer, with its old signature
            elif 200 <= status < 300:
                self.last_answer = (status, body, dict(heads))
        h.send_response(status)
        for k, v in heads.items():
            h.send_header(k, v)
        h.send_header('Content-Length', str(len(body)))
        h.end_headers()
        h.wfile.write(body)

    def handle(self, h, method):
        url = urlsplit(h.path)
        n = int(h.headers.get('Content-Length') or 0)
        raw = h.rfile.read(n) if n else b''
        self.requests.append((method, h.path))
        if not url.path.startswith('/zigmon/v1/'):
            return self.answer(h, 404, {'ok': False, 'error': 'not here'}, sign=False)
        what = url.path[len('/zigmon/v1/'):]
        if what == 'pair' and method == 'POST':
            return self.pair(h, raw)
        # every other request is signed
        ts, nonce, sig = (h.headers.get('X-Zigmon-Ts') or ''), (h.headers.get('X-Zigmon-Nonce') or ''), \
            (h.headers.get('X-Zigmon-Sig') or '')
        with self.lock:
            if self.key is None:
                return self.answer(h, 401, {'ok': False, 'error': 'not paired'}, sign=False)
            want = hmac.new(self.key, ('%s\n%s\n%s\n%s\n%s' % (method, h.path, ts, nonce, sha(raw))).encode(),
                            hashlib.sha256).hexdigest()
            if not hmac.compare_digest(want, sig):
                return self.answer(h, 401, {'ok': False, 'error': 'bad signature'}, sign=False)
            now = time.time()
            if not ts.isdigit() or abs(int(ts) - now) > 120:
                return self.answer(h, 401, {'ok': False, 'error': 'time'}, sign=False)
            if any(x == nonce and now - t < 300 for x, t in self.nonces):
                return self.answer(h, 401, {'ok': False, 'error': 'nonce seen'}, sign=False)
            self.nonces.append((nonce, now))
            self.seen_nonces.append(nonce)
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            return self.answer(h, 400, {'ok': False, 'error': 'bad json'}, nonce)
        if what == 'hello' and method == 'GET':
            return self.answer(h, 200, {'v': 1, 'id': GW_ID, 'name': self.name, 'fw': '1.0.0', 'model': 'esp32s3',
                                        'mac_tail': GW_ID[-6:], 'time_set': True, 'uptime': 1234, 'rssi': -58}, nonce)
        if what == 'describe' and method == 'GET':
            mods = collections.OrderedDict()
            for e in self.entities:
                m = mods.setdefault(e['module'], {'id': e['module'], 'name': {'yeelock': 'Yeelock locks'}.get(
                    e['module'], e['module'].capitalize()), 'version': '1.0.0', 'entities': []})
                m['entities'].append(e)
            return self.answer(h, 200, {'v': 1, 'modules': list(mods.values())}, nonce)
        if what == 'state' and method == 'GET':
            with self.lock:
                return self.answer(h, 200, {'v': 1, 'seq': self.seq, 'entities': json.loads(json.dumps(self.states))}, nonce)
        if what == 'events' and method == 'GET':
            q = parse_qs(url.query)
            after = int((q.get('after') or ['0'])[0])
            wait = min(25.0, float((q.get('wait') or ['0'])[0]))
            until = time.time() + wait
            with self.cond:
                while self.seq <= after and time.time() < until and self.server is not None:
                    self.cond.wait(max(0.01, min(0.2, until - time.time())))
                out = [e for e in self.events if e['seq'] > after]
                return self.answer(h, 200, {'v': 1, 'boot': self.boot, 'seq': self.seq, 'events': out}, nonce)
        if what == 'command' and method == 'POST':
            ent = next((e for e in self.entities if e['id'] == body.get('entity')), None)
            if ent is None:
                return self.answer(h, 404, {'ok': False, 'error': 'unknown entity'}, nonce)
            action = body.get('action')
            if action not in ent['actions']:
                return self.answer(h, 400, {'ok': False, 'error': 'unknown action'}, nonce)
            if self.states[ent['id']].get('busy'):
                return self.answer(h, 409, {'ok': False, 'error': 'busy'}, nonce)
            job = secrets.token_hex(4)
            threading.Thread(target=self.run_job, args=(ent['id'], action), daemon=True).start()
            return self.answer(h, 202, {'ok': True, 'job': job}, nonce)
        if what == 'unpair' and method == 'POST':
            self.answer(h, 200, {'ok': True}, nonce)
            with self.lock:
                self.key = None
                self.zigmon = None
            return None
        return self.answer(h, 404, {'ok': False, 'error': 'unknown'}, nonce)

    def run_job(self, eid, action):
        self.push(eid, 'busy', busy=True)
        time.sleep(0.15)
        failed = action in self.fail_next
        self.fail_next.discard(action)
        st = dict(self.states[eid])
        if failed:
            last = {'action': action, 'ok': False, 'at': int(time.time()), 'msg': 'no answer from the lock'}
            self.push(eid, action, busy=False, last=last)
            return
        value = {'open': 'locked', 'unlock': 'unlocked', 'lock': 'locked'}.get(action, st.get('value'))
        last = {'action': action, 'ok': True, 'at': int(time.time()), 'msg': ''}
        attrs = dict(st.get('attrs') or {})
        if 'battery' in attrs:
            attrs['battery'] = max(0, attrs['battery'] - 1)
        self.push(eid, action, busy=False, value=value, last=last, attrs=attrs)

    def pair(self, h, raw):
        try:
            body = json.loads(raw)
        except ValueError:
            return self.answer(h, 400, {'ok': False, 'error': 'bad json'}, sign=False)
        with self.lock:
            if time.time() < self.locked_until:
                return self.answer(h, 429, {'ok': False, 'error': 'pairing locked for a while'}, sign=False)
            code, self.code = self.code, None              # spent, whatever happens
            if code is None or time.time() > code[1]:
                self.wrong += 1
                self._lock_maybe()
                return self.answer(h, 401, {'ok': False, 'error': 'no pairing code is open'}, sign=False)
            want = hmac.new(code[0].encode(), ('zigmon-pair-v1\n%s\n%s' % (self.fingerprint, body.get('nonce'))).encode(),
                            hashlib.sha256).hexdigest()
            if not hmac.compare_digest(want, str(body.get('proof') or '')):
                self.wrong += 1
                self._lock_maybe()
                return self.answer(h, 401, {'ok': False, 'error': 'wrong code'}, sign=False)
            self.wrong = 0
            self.key = bytes.fromhex(body['key'])
            self.zigmon = body.get('zigmon')
        return self.answer(h, 200, {'ok': True, 'id': GW_ID, 'name': self.name, 'fw': '1.0.0'}, sign=False)

    def _lock_maybe(self):
        if self.wrong >= 5:
            self.locked_until = time.time() + 900
            self.wrong = 0

    def close(self):
        self.stop()
        shutil.rmtree(self.dir, ignore_errors=True)


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 20361
    gw = FakeGateway(port, host=sys.argv[2] if len(sys.argv) > 2 else '127.0.0.1').start()
    print('fake ESP32 gateway on https://127.0.0.1:%d' % port)
    print('fingerprint', gw.fingerprint)
    print('code', gw.new_code(), flush=True)
    try:
        while True:
            line = sys.stdin.readline()
            if not line:
                time.sleep(3600)
                continue
            if line.strip() == 'code':
                print('code', gw.new_code(), flush=True)
    except KeyboardInterrupt:
        gw.close()
