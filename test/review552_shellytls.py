#!/usr/bin/env python3
"""5.52: optional HTTPS to a Shelly Gen2+ box - off unless switched on per box.

A box made with firmware 2.0 or newer speaks only HTTPS ("enhanced
security": plain HTTP is sent on to https://, Sys "HTTPS by Default"), with a
certificate from Shelly's own PKI - a CA Shelly does not publish. So:

  1. a box nobody switched HTTPS on for speaks plain HTTP exactly as before
     (an old database has no setting; the client, the URL, the kept
     connection are the plain ones; the old call signature works);
  2. a plain-HTTP box that sends us on to https:// says so in words - "speaks
     only HTTPS ... switch HTTPS on" - and its card says it; nothing is
     switched on by itself;
  3. HTTPS on: calls go over TLS with the digest as before, and the box's
     certificate (SHA-256) is kept the first time it is met (trust on first
     use), an event says so, and a kept connection is used again;
  4. a different certificate is refused - an event, once - and the call
     never reaches the box; "trust the new certificate" (with the
     fingerprint shown) takes it, a stale fingerprint is refused;
  5. a CA pasted for a box: a certificate from that CA (made out for its
     address) is taken, one from another CA refused; junk is not a CA;
  6. the setting and the pin survive a restart; the command line (tls,
     https://HOST addressing), the console, the relay and the page carry it.

    python3 test/review552_shellytls.py < /dev/null

Fake boxes on 127.0.0.1:20150-20159; openssl makes the certificates.
"""
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review552-'))
PLAIN, REDIR, SECURE, COMPANY, API = 20150, 20151, 20152, 20153, 20154
PASSWORD = 'box-pass'
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


# ---- certificates --------------------------------------------------------------------
def openssl(*args):
    subprocess.run(['openssl'] + list(args), cwd=str(W), check=True, capture_output=True,
                   stdin=subprocess.DEVNULL)


CNF = '[req]\ndistinguished_name=dn\nprompt=no\n[dn]\nCN=Shelly Device\n[v3]\nsubjectAltName=IP:127.0.0.1\n'
(W / 'v3.cnf').write_text(CNF)


def self_signed(name):
    openssl('req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes',
            '-keyout', name + '.key', '-out', name + '.crt', '-days', '30', '-config', 'v3.cnf',
            '-extensions', 'v3')


def ca(name):
    openssl('req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes',
            '-keyout', name + '.key', '-out', name + '.crt', '-days', '30', '-subj', '/CN=' + name)


def signed(name, by):
    openssl('req', '-new', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes',
            '-keyout', name + '.key', '-out', name + '.csr', '-config', 'v3.cnf')
    openssl('x509', '-req', '-in', name + '.csr', '-CA', by + '.crt', '-CAkey', by + '.key', '-CAcreateserial',
            '-out', name + '.crt', '-days', '30', '-extfile', 'v3.cnf', '-extensions', 'v3')


for n in ('boxA', 'boxB'):
    self_signed(n)
for n in ('CompanyCA', 'OtherCA'):
    ca(n)
signed('boxC', 'CompanyCA')
signed('boxD', 'OtherCA')


def fp(name):
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert((W / (name + '.crt')).read_text())).hexdigest()


def ctx(name):
    c = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    c.load_cert_chain(str(W / (name + '.crt')), str(W / (name + '.key')))
    return c


# ---- fake boxes ------------------------------------------------------------------------
SEEN = {'calls': [], 'accepted': 0, 'nc': {}}


class Box(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'          # a box keeps a connection open

    def log_message(self, *a):
        pass

    def _digest_ok(self):
        header = self.headers.get('Authorization', '')
        if not header.startswith('Digest '):
            return False
        f = dict(re.findall(r'(\w+)="?([^",]+)"?', header))

        def h(t):
            return hashlib.sha256(t.encode()).hexdigest()
        ha1 = h('admin:%s:%s' % (f.get('realm'), PASSWORD))
        ha2 = h('POST:%s' % f.get('uri'))
        return f.get('response') == h('%s:%s:%s:%s:auth:%s' % (ha1, f.get('nonce'), f.get('nc'), f.get('cnonce'), ha2))

    def _send(self, code, body=b'', headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        if not self._digest_ok():
            return self._send(401, headers=[('WWW-Authenticate', 'Digest qop="auth", realm="shellyplugsg3-aabbcc", '
                                                                  'nonce="%s", algorithm=SHA-256' % secrets.token_hex(8))])
        m = body.get('method')
        SEEN['calls'].append((self.server.server_address[1], m))
        r = {'Shelly.GetDeviceInfo': {'id': 'shellyplugsg3-aabbcc', 'model': 'S3PL-00112EU', 'app': 'PlugSG3',
                                      'ver': '2.0.0', 'gen': 3, 'auth_en': True},
             'Shelly.GetStatus': {'switch:0': {'id': 0, 'output': True, 'apower': 12.5}},
             'Switch.GetStatus': {'id': 0, 'output': True, 'apower': 12.5},
             'Switch.Set': {'was_on': True}}.get(m)
        self._send(200, json.dumps({'id': body.get('id'), 'result': r}).encode(), [('Content-Type', 'application/json')])


class Redirect(BaseHTTPRequestHandler):
    """Firmware 2.0+ with enhanced security: plain HTTP is sent on to HTTPS."""

    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length') or 0))
        self.send_response(301)
        self.send_header('Location', 'https://127.0.0.1/rpc')
        self.send_header('Content-Length', '0')
        self.end_headers()


class TLSServer(ThreadingHTTPServer):
    daemon_threads = True
    context = None

    def get_request(self):
        sock, addr = self.socket.accept()
        SEEN['accepted'] += 1
        # the handshake on the handler's thread, as a box does it on its own time
        return self.context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False), addr

    def handle_error(self, request, client_address):
        pass                                # a client that refused our certificate hangs up


servers = []


def serve(port, handler, context=None):
    srv = (TLSServer if context else ThreadingHTTPServer)(('127.0.0.1', port), handler)
    srv.daemon_threads = True
    if context:
        srv.context = context
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    servers.append(srv)
    return srv


serve(PLAIN, Box)
serve(REDIR, Redirect)
secure = serve(SECURE, Box, ctx('boxA'))
company = serve(COMPANY, Box, ctx('boxC'))

H_PLAIN, H_REDIR, H_SECURE, H_COMPANY = ['127.0.0.1:%d' % p for p in (PLAIN, REDIR, SECURE, COMPANY)]
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'zigmon.db'), 'api_port': API, 'token_file': str(W / 'token'),
                      'plugs': [{'name': 'Lamp', 'host': H_PLAIN, 'password': PASSWORD},
                                {'name': 'Redir', 'host': H_REDIR, 'password': PASSWORD},
                                {'name': 'Secure', 'host': H_SECURE, 'password': PASSWORD},
                                {'name': 'Company', 'host': H_COMPANY, 'password': PASSWORD}],
                      'sensors': [], 'backup_dir': str(W / 'backups'), 'weather': False, 'state_dir': str(W),
                      'plug_keepalive_s': 5})
d = zigmon.Daemon()


def events(word):
    return [e for e in d.store.events(200) if word in str(e.get('detail') or '')]


try:
    # -- 1. off by default: an old database, plain HTTP exactly as before ------------------
    check(d.store.get_meta('shelly_tls') in (None, ''), 'an old database came with an HTTPS setting')
    check(zigmon.ShellyRPC._tls == {}, 'HTTPS is on for a box nobody switched it on for: %r' % zigmon.ShellyRPC._tls)
    lamp = d.plugs['Lamp'].rpc()
    check(lamp.tls is False and lamp.url == 'http://%s/rpc' % H_PLAIN, 'a default box is not plain HTTP: %s' % lamp.url)
    old_style = zigmon.ShellyRPC(H_PLAIN, PASSWORD, 0, label='plug Lamp')       # the signature everyone calls
    got = old_style.switch_status()
    check(got and got.get('apower') == 12.5, 'a plain HTTP call: %r' % (got,))
    kept = [c for c, _u in zigmon.ShellyRPC._conns.get(H_PLAIN) or []]
    check(kept and all(type(c).__name__ == 'HTTPConnection' for c in kept),
          'the connection kept for a plain box is not the plain one: %r' % kept)
    check(d.plug_snapshot(d.plugs['Lamp'])['tls'] == {'on': False, 'pin': '', 'ca': False, 'changed': False,
                                                       'https_only': False},
          'the card of a plain box says something about HTTPS: %r' % d.plug_snapshot(d.plugs['Lamp'])['tls'])
    check(not d.managed_for_ui()['plugs'][0]['tls'], 'the device list says HTTPS for a plain box')
    print('off by default: a box nobody switched on speaks plain HTTP as before')

    # -- 2. a box that sends plain HTTP on to HTTPS: said in words, never switched on -------
    try:
        d.plugs['Redir'].rpc().switch_status()
        check(False, 'a box that redirects to https answered')
    except zigmon.PlugError as e:
        check('speaks only HTTPS' in str(e) and 'switch HTTPS on' in str(e) and 'firmware 2.0' in str(e),
              'the redirect is not said plainly: %s' % e)
    check(H_REDIR not in zigmon.ShellyRPC._tls, 'HTTPS was switched on by itself for a box that redirects')
    snap = d.plug_snapshot(d.plugs['Redir'])
    check(snap['tls']['https_only'] and not snap['tls']['on'], 'the card does not say it speaks only HTTPS: %r' % snap['tls'])
    ok, answer = d.shelly_tls('Redir', 'status')
    check(ok and answer['tls']['https_only'], 'the status does not say HTTPS only: %r' % (answer,))
    try:
        d.test_device(H_REDIR, PASSWORD)
        check(False, 'testing a redirecting box said it was fine')
    except zigmon.PlugError as e:
        check('speaks only HTTPS' in str(e), 'the add dialog\'s test does not say HTTPS only: %s' % e)
    print('a box that speaks only HTTPS says so, and nothing is switched on by itself')

    # -- 3. HTTPS on: TLS with the digest, the certificate kept the first time --------------
    out = d.test_device(H_SECURE, PASSWORD, tls=True)
    check(out.get('tls') and out.get('tls_fingerprint') == fp('boxA'), 'the HTTPS test: %r' % out)
    check(H_SECURE not in zigmon.ShellyRPC._tls and not (json.loads(d.store.get_meta('shelly_tls') or '{}')),
          'a test over HTTPS kept a setting')
    ok, answer = d.shelly_tls('Secure', 'on')
    check(ok and answer['tls']['on'] and answer['tls']['pin'] == fp('boxA'), 'HTTPS on: %r' % (answer,))
    kept = json.loads(d.store.get_meta('shelly_tls'))
    check(kept.get(H_SECURE, {}).get('on') is True and kept[H_SECURE].get('pin') == fp('boxA'),
          'the setting and the pin were not kept: %r' % kept)
    check(events('for the first time'), 'no event says the certificate was met and kept')
    rpc = d.plugs['Secure'].rpc()
    check(rpc.tls and rpc.url == 'https://%s/rpc' % H_SECURE, 'the socket\'s client is not HTTPS: %s' % rpc.url)
    zigmon.ShellyRPC.forget_connections(H_SECURE)
    SEEN['accepted'] = 0
    SEEN['calls'][:] = []
    for _ in range(3):
        got = d.plugs['Secure'].rpc().switch_status()
    check(got and got.get('output') is True, 'a call over HTTPS: %r' % (got,))
    check(SEEN['accepted'] == 1, 'a kept HTTPS connection was not used again: %d handshakes for 3 calls'
          % SEEN['accepted'])
    got = d.plugs['Secure'].rpc().set_output(False)
    check(('%d' % SECURE, 'Switch.Set') in [('%d' % p, m) for p, m in SEEN['calls']], 'a command over HTTPS did not arrive')
    # the device backups' own quiet client (5.51) speaks HTTPS to a box that has it on
    SEEN['calls'][:] = []
    sec = d.plugs['Secure']
    try:
        got = zigmon.sbk_call(zigmon.sbk_rpc({'host': sec.cfg['host'], 'password': sec.cfg.get('password') or '',
                                             'label': 'Secure'}), 'Switch.GetStatus', {'id': 0}, tries=1)
    except Exception as e:                                # noqa: BLE001
        got = e
    check(isinstance(got, dict) and got.get('output') is True and SEEN['calls'],
          'the device backups\' client does not speak HTTPS to an HTTPS box: %r' % (got,))
    snap = d.plug_snapshot(d.plugs['Secure'])
    check(snap['tls']['on'] and snap['tls']['pin'] == fp('boxA') and not snap['tls']['changed'],
          'the card of an HTTPS box: %r' % snap['tls'])
    check(d.plug_snapshot(d.plugs['Lamp'])['tls']['on'] is False and not d.plugs['Lamp'].rpc().tls,
          'switching one box on changed another')
    print('HTTPS on: digest over TLS, the certificate kept the first time, the connection used again')

    # the warm spare of an HTTPS box: opened on a thread of its own, checked, taken by a command
    zigmon.ShellyRPC.forget_connections(H_SECURE)
    d._warm_tls(H_SECURE, 1, {})
    for _ in range(50):
        if zigmon.ShellyRPC.warm_state(H_SECURE)[0]:
            break
        time.sleep(0.05)
    check(zigmon.ShellyRPC.warm_state(H_SECURE)[0] == 1, 'no warm HTTPS spare was opened (or it looked closed)')
    check(zigmon.ShellyRPC._take_warm(H_SECURE, 5, False) is None, 'a plain command was handed an HTTPS spare')
    d._warm_tls(H_SECURE, 1, {})
    for _ in range(50):
        if zigmon.ShellyRPC.warm_state(H_SECURE)[0]:
            break
        time.sleep(0.05)
    spare = zigmon.ShellyRPC._take_warm(H_SECURE, 5, True)
    check(isinstance(spare, zigmon.ShellyHTTPS), 'the HTTPS spare was not taken: %r' % spare)
    if spare:
        spare.close()
    sock = d.plugs['Secure'].rpc().open_socket(5)       # what `shelly watch` speaks websocket on
    check(isinstance(sock, ssl.SSLSocket), 'the websocket of an HTTPS box is not wss: %r' % sock)
    sock.close()
    print('an HTTPS box: its warm spare on a thread of its own, its websocket over TLS')

    # -- 4. a different certificate: refused, said once; trusted only on purpose ------------
    secure.context = ctx('boxB')
    zigmon.ShellyRPC.forget_connections(H_SECURE)
    SEEN['calls'][:] = []
    for attempt in range(2):
        try:
            d.plugs['Secure'].rpc().set_output(True)
            check(False, 'a box with another certificate was given a command')
        except zigmon.PlugError as e:
            check(isinstance(e, zigmon.ShellyTLSRefused) and 'different HTTPS certificate' in str(e)
                  and 'refused' in str(e), 'the refusal is not said plainly: %s' % e)
    check(not SEEN['calls'], 'a request reached the box behind the wrong certificate: %r' % SEEN['calls'])
    check(len(events('shows a different certificate')) == 1, 'the changed certificate was told %d times'
          % len(events('shows a different certificate')))
    check(zigmon.ShellyRPC._tls[H_SECURE]['pin'] == fp('boxA'), 'the new certificate was taken by itself')
    snap = d.plug_snapshot(d.plugs['Secure'])
    check(snap['tls']['changed'], 'the card does not say the certificate changed: %r' % snap['tls'])
    ok, answer = d.shelly_tls('Secure', 'status')
    check(ok and answer['tls']['seen'] == fp('boxB'), 'the status does not show the new certificate: %r' % (answer,))
    ok, answer = d.shelly_tls('Secure', 'trust', {'fingerprint': fp('boxA')})
    check(not ok and 'yet another' in str(answer), 'a stale fingerprint was trusted: %r' % (answer,))
    ok, answer = d.shelly_tls('Secure', 'trust', {'fingerprint': fp('boxB')})
    check(ok and answer['tls']['pin'] == fp('boxB') and not answer['tls']['seen'], 'trust the new one: %r' % (answer,))
    got = d.plugs['Secure'].rpc().switch_status()
    check(got and got.get('apower') == 12.5, 'after trusting it the box does not answer: %r' % (got,))
    check(not d.plug_snapshot(d.plugs['Secure'])['tls']['changed'], 'the card still says changed')
    print('a different certificate is refused and said once; trusted only with its fingerprint')

    # -- 5. a CA: its certificates taken, another CA's refused ------------------------------
    ok, answer = d.shelly_tls('Company', 'on', {'ca': 'not a certificate'})
    check(not ok and 'PEM' in str(answer), 'junk was taken as a CA: %r' % (answer,))
    ok, answer = d.shelly_tls('Company', 'on', {'ca': (W / 'OtherCA.crt').read_text()})
    check(ok and answer.get('warning') and 'does not check out' in answer['warning'],
          'a certificate from another CA was not refused: %r' % (answer,))
    try:
        d.plugs['Company'].rpc().switch_status()
        check(False, 'a box with a certificate from another CA answered')
    except zigmon.PlugError as e:
        check('does not check out against the CA' in str(e), 'the CA refusal is not said plainly: %s' % e)
    ok, answer = d.shelly_tls('Company', 'ca', {'ca': (W / 'CompanyCA.crt').read_text()})
    check(ok and not answer.get('warning'), 'the right CA was not taken: %r' % (answer,))
    got = d.plugs['Company'].rpc().switch_status()
    check(got and got.get('apower') == 12.5, 'a box signed by its CA does not answer: %r' % (got,))
    company.context = ctx('boxD')
    zigmon.ShellyRPC.forget_connections(H_COMPANY)
    try:
        d.plugs['Company'].rpc().switch_status()
        check(False, 'a certificate from another CA was taken in CA mode')
    except zigmon.PlugError as e:
        check('does not check out' in str(e), 'CA mode, another CA: %s' % e)
    company.context = ctx('boxC')
    zigmon.ShellyRPC.forget_connections(H_COMPANY)
    print('a CA: what it signed is taken, what another signed is refused')

    # -- 6. survives a restart; off again is plain HTTP ---------------------------------------
    zigmon.ShellyRPC._tls = {}
    d = zigmon.Daemon()                    # the same database, read afresh
    check(zigmon.ShellyRPC._tls.get(H_SECURE, {}).get('pin') == fp('boxB')
          and zigmon.ShellyRPC._tls.get(H_COMPANY, {}).get('ca'), 'the settings did not survive a restart: %r'
          % zigmon.ShellyRPC._tls)
    check(H_PLAIN not in zigmon.ShellyRPC._tls, 'a plain box came back with HTTPS')
    got = d.plugs['Secure'].rpc().switch_status()
    check(got and got.get('apower') == 12.5, 'after a restart the HTTPS box does not answer: %r' % (got,))
    ok, answer = d.shelly_tls('Company', 'off')
    check(ok and not answer['tls']['on'] and not d.plugs['Company'].rpc().tls, 'HTTPS off: %r' % (answer,))
    ok, answer = d.shelly_tls('Nobody', 'on')
    check(not ok, 'HTTPS was switched on for a box that is not configured')
    check('/api/shelly/tls' not in zigmon.OPERATOR_ROADS, 'an operator could change how a box is spoken to')
    print('the setting and the certificate survive a restart; off is plain HTTP again')

    # -- 7. the command line ------------------------------------------------------------------
    said = []

    def fake_api(path, method='GET', payload=None, **kw):
        said.append(payload)
        ok, answer = d.shelly_tls(payload.get('name'), payload.get('action'), payload)
        return 200, (dict(answer, ok=True) if ok else {'ok': False, 'error': answer})
    real_api = zigmon.api_call
    zigmon.api_call = fake_api

    def cli(*args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = zigmon.shelly_main(list(args), zigmon.Palette(False))
        return rc, buf.getvalue()
    try:
        rc, out = cli('Secure', 'tls')
        check(rc == 0 and 'on' in out and zigmon.ShellyRPC.fingerprint_words(fp('boxB')) in out,
              'tls status: %d %s' % (rc, out))
        rc, out = cli('Secure', 'tls', 'off')
        check(rc != 0 and 'not done' in out and H_SECURE in zigmon.ShellyRPC._tls,
              'tls off went ahead with nobody to ask: %d %s' % (rc, out))
        rc, out = cli('Secure', 'tls', 'off', '--yes')
        check(rc == 0 and H_SECURE not in zigmon.ShellyRPC._tls, 'tls off --yes: %d %s' % (rc, out))
        rc, out = cli('Secure', 'tls', 'on', '--yes')
        check(rc == 0 and H_SECURE in zigmon.ShellyRPC._tls and 'answers over HTTPS' in out, 'tls on --yes: %d %s' % (rc, out))
        secure.context = ctx('boxA')
        zigmon.ShellyRPC.forget_connections(H_SECURE)
        rc, out = cli('Secure', 'info')
        check(rc != 0 and 'different HTTPS certificate' in out, 'a changed certificate on the command line: %s' % out)
        rc, out = cli('Secure', 'tls', '--trust-new', '--yes')
        check(rc == 0 and zigmon.ShellyRPC._tls[H_SECURE]['pin'] == fp('boxA'), 'tls --trust-new: %d %s' % (rc, out))
        rc, out = cli('Redir', 'info')
        check(rc != 0 and 'speaks only HTTPS' in out, 'the command line does not say HTTPS only: %s' % out)
        rc, out = cli('https://' + H_SECURE, 'info', '--password', PASSWORD)
        check(rc == 0 and 'S3PL' in out, 'zigmon shelly https://HOST info: %d %s' % (rc, out))
    finally:
        zigmon.api_call = real_api
    src = (HERE / 'zigmon.py').read_text()
    help_block = src[src.index('HELP_LINES = ['):src.index('\n]\n\n\ndef help_text')]
    check('shelly Lednice tls' in help_block, 'the help does not name zigmon shelly NAME tls')
    check('https://10.0.0.5' in zigmon.SHELLY_EPILOG and 'tls' in zigmon.SHELLY_EPILOG, 'the shelly epilog lacks HTTPS')
    print('the command line: tls on/off/--trust-new (asked first), https://HOST, the words')

    # -- 8. the console, the relay, the page ----------------------------------------------
    class Seen(object):
        def __init__(self, answer, pick, yes=True):
            self.answer, self.pick, self.yes, self.acts = answer, pick, yes, []

        def working(self, words):
            pass

        def out(self, *args):
            return self.answer

        def choose(self, title, options, words='', cur=0):
            self.options = [o[0] for o in options]
            return self.pick

        def confirm(self, *a, **kw):
            return self.yes

        def act(self, *args, **kw):
            self.acts.append(args)
    c = Seen({'on': False, 'host': H_REDIR, 'https_only': True}, 'on')
    zigmon.Console.plug_tls(c, 'Redir')
    check(c.acts == [('shelly', 'Redir', 'tls', 'on', '--yes')], 'the console\'s HTTPS on: %r' % c.acts)
    c = Seen({'on': True, 'host': H_SECURE, 'pin': 'ab', 'pin_words': 'AB', 'seen': 'cd', 'seen_words': 'CD'}, 'trust',
             yes=False)
    zigmon.Console.plug_tls(c, 'Secure')
    check(c.options[0] == 'trust' and c.acts == [], 'the console trusted after a no, or offered no trust: %r %r'
          % (c.options, c.acts))
    console = src[src.index('    def plug_do(self, p):'):src.index('    # ---- 4 accounts of the dashboard')]
    check("'https'" in console, 'the console\'s socket menu has no HTTPS')
    php = (HERE / 'web' / 'index.php').read_text()
    check("'shelly-tls' => '/api/shelly/tls'" in php, 'the relay does not carry shelly-tls')
    js = php[php.index('function showPlugTls'):php.index('// (5.51) A socket\'s box')]
    check(js.count('zconfirm(') == 2 and 'Trust the new certificate' in js and 'textarea' in js,
          'the page\'s HTTPS popup does not ask first, or lacks trust / the CA')
    check("$row['tls'] = true" in php and 'speaks only HTTPS' in php, 'the add dialog does not offer HTTPS')
    print('the console, the relay and the page: HTTPS for a box, asked first')

    # -- 9. the page itself (php -S, Chromium): the hint, the popup, asked first ---------------
    ui = r'''
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({viewport: {width: 1300, height: 900}});
  p.on('pageerror', e => {});
  await p.goto('http://127.0.0.1:%(port)d/index.php');
  await p.waitForTimeout(800);
  const r = await p.evaluate(async () => {
    const calls = [];
    const status = {host: '10.0.0.7', on: false, pin: '', https_only: true, ca_pem: ''};
    window.signedIn = () => true;
    window.post = (what, body) => { calls.push([what, body]);
      return Promise.resolve(what === 'shelly-tls' ? {ok: true, tls: Object.assign({}, status, body.action === 'on' ? {on: true} : {}), message: 'ok'} : {ok: true}); };
    const wait = ms => new Promise(ok => setTimeout(ok, ms));
    const st = {plugs: [{name: 'Old', online: false, stale: true, error: 'speaks only HTTPS', host: '10.0.0.7', info: {}, counters: [],
                         tls: {on: false, pin: '', ca: false, changed: false, https_only: true}},
                        {name: 'Plain', online: true, output: 1, host: '10.0.0.5', info: {}, counters: [],
                         tls: {on: false, pin: '', ca: false, changed: false, https_only: false}}],
                pulse_ms: {default: 5000}};
    PLUGCTL_OPEN = {Old: true, Plain: true};
    renderPlugControls(st);
    const out = {};
    out.hintOld = !!document.querySelector('[data-plug="Old"] [data-plug-tls="hint"]');
    out.hintPlain = !!document.querySelector('[data-plug="Plain"] [data-plug-tls="hint"]');
    const open = document.querySelector('[data-plug="Old"] [data-plug-tls="open"]');
    out.button = !!open;
    if (!open) return out;
    open.click(); await wait(150);
    out.title = document.getElementById('zmodal-title').textContent;
    out.says = document.getElementById('zmodal-body').textContent.indexOf('speaks only HTTPS') >= 0;
    out.ca = !!document.querySelector('#zmodal-body [data-tls="ca"]');
    const btn = words => Array.from(document.querySelectorAll('#zmodal-foot button')).find(x => x.textContent.indexOf(words) >= 0);
    document.querySelector('#zmodal-body [data-tls="switch"] input').click();
    btn('Save').click(); await wait(100);
    out.ask = document.getElementById('zmodal-title').textContent;
    out.before = calls.filter(c => c[0] === 'shelly-tls' && c[1].action === 'on').length;
    const yes = btn('Switch it on'); if (yes) { yes.click(); await wait(150); }
    out.after = calls.filter(c => c[0] === 'shelly-tls' && c[1].action !== 'status').map(c => c[1].action + ':' + c[1].name);
    return out;
  });
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
''' % {'port': 20155}
    if shutil.which('php') and shutil.which('node'):
        (W / 'ui.js').write_text(ui)
        php_srv = subprocess.Popen(['php', '-S', '127.0.0.1:20155', '-t', str(HERE / 'web')],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    socket.create_connection(('127.0.0.1', 20155), 0.2).close()
                    break
                except OSError:
                    time.sleep(0.1)
            root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
            got = subprocess.run(['node', str(W / 'ui.js')], capture_output=True, text=True, timeout=120,
                                 stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=root))
        finally:
            php_srv.kill()
            php_srv.wait()
        try:
            r = json.loads(got.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            r = {'error': (got.stdout + got.stderr)[-300:]}
        if r.get('error'):
            print('  SKIPPED the page (no browser here): %s' % r['error'][:200])
        else:
            check(r.get('hintOld') and not r.get('hintPlain'), 'the card\'s HTTPS-only hint: %r' % r)
            check(r.get('button') and r.get('title') == 'HTTPS to Old' and r.get('says') and r.get('ca'),
                  'the HTTPS popup of an unreachable box: %r' % r)
            check(r.get('ask') == 'HTTPS to Old' and r.get('before') == 0 and r.get('after') == ['on:Old'],
                  'HTTPS on from the page was not asked first: %r' % r)
            print('the page: the card says HTTPS only, the popup switches it on after asking')
finally:
    for srv in servers:
        srv.shutdown()
    try:
        d.store.close()
    except Exception:
        pass
    shutil.rmtree(W, ignore_errors=True)

if bad:
    print('%d FAILED' % len(bad))
    sys.exit(1)
print('all good')
