#!/usr/bin/env python3
"""5.44, pass 1: the security and the correctness of what 5.40-5.43.4 added.
Each check here failed on 5.43.4:

  * the passkey challenges asked for with no sign-in: one address holds a few
    at the most - 500 asks from one place pushed out the one a person was
    about to answer, and nobody could sign in with a passkey;
  * /api/approvals/stop with no ticket called off every press waiting;
  * coming back for a press's answer (X-Zigmon-Wait) with the secret of any
    link at all answered for the press of another link;
  * the API token file is made 0640, never written first and narrowed after;
  * ::ffff:203.0.113.5 is spared by a never-kept-out 203.0.113.0/24;
  * the guard's own events (wrong passwords, sign-ins with their addresses,
    who was kept out by hand) are not shown to a public view;
  * the ntfy address shown with its token kept, saved with another server,
    does not send the kept token to that server;
  * zigmon --set of a secret does not echo it back;
  * an acme push pair with no pairing code waiting keeps no nonce (a pair is
    signed by the key in its own body: anybody can send one);
  * the meter's details are read by one ask at a time, the others share it;
  * in the browser: a ZIP of a certificate is unpacked no further than the
    size it says, and the meter's details of the account before are dropped
    on signing out or in as another.

    python3 test/pass1_sec.py

Ports 19440 (the daemon).
"""
import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(os.environ.get('ZIGMON_HUNT_HERE') or Path(__file__).resolve().parent.parent)
W = Path(tempfile.mkdtemp(prefix='zigmon-pass1-sec-'))
API_PORT = 19440
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def finish():
    shutil.rmtree(str(W), ignore_errors=True)
    print('pass1_sec: %s' % ('%d failed' % len(bad) if bad else 'all good'))
    sys.stdout.flush()
    os._exit(1 if bad else 0)


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'run' / 'api-token'), 'pin': '', 'plugs': [], 'sensors': [],
                      'mqtt_host': '', 'log_file': str(W / 'zigmon.log'), 'log_to_journal': False,
                      'state_dir': str(W / 'state'), 'login_tries': 5, 'login_wait_min': 15,
                      'session_idle_min': 240, 'session_hours': 720, 'public_view': True})
(W / 'state').mkdir()
try:
    d = zigmon.Daemon()
    api = zigmon.ApiServer(d)
    api.start()
    time.sleep(0.3)
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
except Exception as e:                                  # noqa: BLE001
    check(False, 'the daemon could not be started: %s' % e)
    finish()
HOST = 'house.example.org'


def call(path, body=None, sess=None, client='192.168.40.10', host=HOST, headers=None):
    h = {'Content-Type': 'application/json', 'X-Zigmon-Token': d.token}
    if client:
        h['X-Zigmon-Client'] = client
    if host:
        h['X-Zigmon-Host'] = host
    if sess:
        h['X-Zigmon-Session'] = sess
        if body is not None:
            body = dict(body, session=sess)
    h.update(headers or {})
    r = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=h,
                               data=None if body is None else json.dumps(body).encode(),
                               method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(r, timeout=60) as x:
            return x.status, json.loads(x.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'{}')
        except ValueError:
            return e.code, {}


try:
    T_OWNER = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token', '')
    check(T_OWNER, 'the administrator of the test could not sign in')

    # ---- passkey challenges from no sign-in ------------------------------------------------
    print('passkey challenges asked for with no sign-in')
    zigmon.CONFIG['passkeys'] = 1
    c, o = call('/api/auth/passkey/begin', {}, client='192.168.40.20')
    mine = o.get('publicKey', {}).get('challenge', '')
    check(c == 200 and mine, 'a passkey sign-in was not begun: %s %r' % (c, o))
    for n in range(520):
        call('/api/auth/passkey/begin', {}, client='203.0.113.9')
    check(mine in d._pk_waiting, 'a flood of challenges from one address pushed out the one a person waits on')
    theirs = len(d._pk_waiting) - (1 if mine in d._pk_waiting else 0)
    check(theirs <= 10, 'one address holds %d challenges waiting' % theirs)
    zigmon.CONFIG['passkeys'] = False

    # ---- approvals: stop with no ticket ---------------------------------------------------
    print('approvals: a stop with no ticket')
    script = d.save_scripts([{'name': 'Pass1', 'body': 'say ran it'}])[0]
    d.save_taps([{'name': 'Door A', 'target': 'script:' + script['id'], 'do': 'script'},
                 {'name': 'Door B', 'target': 'script:' + script['id'], 'do': 'script'}])
    by = {t['name']: t for t in d.taps()}
    with d._waiting_cond:
        d._waiting['TICKETAAAAAA'] = {'state': 'waiting', 'message': 'waiting', 'tap': by['Door A']['id'],
                                      'at': time.time(), 'who': '', 'link': 'Door A', 'what': '',
                                      'deadline': time.time() + 600}
    c, r = call('/api/approvals/stop', {}, T_OWNER)
    check(d._waiting['TICKETAAAAAA']['state'] == 'waiting',
          'a stop with no ticket called off every waiting press: %s %r' % (c, r))
    c, r = call('/api/approvals/stop', {'ticket': 'NOSUCHTICKET'}, T_OWNER)
    check(d._waiting['TICKETAAAAAA']['state'] == 'waiting', 'a stop of another ticket called this one off')

    # ---- X-Zigmon-Wait with another link's secret -----------------------------------------
    print('the answer of a press, asked with another link\'s secret')
    c, r = call('/api/tap', {'seconds': 1}, headers={'X-Zigmon-Tap': by['Door B']['token'],
                                                     'X-Zigmon-Wait': 'TICKETAAAAAA'}, client='192.168.40.30')
    check(c == 404, 'the secret of Door B was answered for the press of Door A: %s %r' % (c, r))
    c, r = call('/api/tap', {'seconds': 1}, headers={'X-Zigmon-Tap': by['Door A']['token'],
                                                     'X-Zigmon-Wait': 'TICKETAAAAAA'}, client='192.168.40.30')
    check(c == 200 and r.get('state') == 'waiting', 'its own link was not answered: %s %r' % (c, r))
    c, r = call('/api/approvals/stop', {'ticket': 'TICKETAAAAAA'}, T_OWNER)
    check(d._waiting['TICKETAAAAAA']['state'] == 'stopped', 'a stop of its ticket did not call it off: %r' % r)

    # ---- the token file --------------------------------------------------------------------
    print('the API token file, made 0640')
    was_umask = os.umask(0o022)
    was_conf = zigmon.CONFIG['token_file']
    real_chmod, real_pchmod = os.chmod, pathlib.Path.chmod
    try:
        zigmon.CONFIG['token_file'] = str(W / 'run2' / 'api-token')
        os.chmod = lambda *a, **k: None                  # as though the narrowing never came
        pathlib.Path.chmod = lambda *a, **k: None
        d._ensure_token()
    finally:
        os.chmod, pathlib.Path.chmod = real_chmod, real_pchmod
        os.umask(was_umask)
        zigmon.CONFIG['token_file'] = was_conf
    mode = (W / 'run2' / 'api-token').stat().st_mode & 0o777
    check(mode == 0o640, 'the token file was made %o, readable by everybody before it is narrowed' % mode)

    # ---- IPv4-mapped IPv6 ------------------------------------------------------------------
    print('an IPv4 address written as IPv6')
    zigmon.CONFIG['never_block'] = '203.0.113.0/24'
    check(d.spared('203.0.113.5'), 'the plain address is not spared')
    check(d.spared('::ffff:203.0.113.5'), '::ffff:203.0.113.5 is not spared by 203.0.113.0/24')
    check(d.own_house('::ffff:192.168.1.5'), '::ffff:192.168.1.5 is not one of the house')
    zigmon.CONFIG['never_block'] = ''

    # ---- the guard's events in a public view -----------------------------------------------
    print('the guard\'s own events, in a public view')
    d.store.add_event('security', 'a wrong password for owner from 198.51.100.66', 'warn')
    d.store.add_event('audit', 'blocked 198.51.100.77 by hand', 'info')
    d.store.add_event('control', 'the porch light went on', 'info')
    d.store.flush()

    def said(r):
        return ' '.join(str(e.get('detail') or '') for e in r.get('events') or [])
    c, r = call('/api/events?limit=200', client='198.51.100.50')
    check(c == 200 and 'porch light' in said(r), 'the public view lost the house\'s events: %s' % c)
    check('198.51.100.66' not in said(r) and '198.51.100.77' not in said(r),
          'a public view is shown the wrong passwords and who was kept out: %r' % said(r)[:200])
    c, r = call('/api/events?limit=200&kind=security', client='198.51.100.50')
    check('198.51.100.66' not in said(r), 'asked by its kind, a public view is shown the security events')
    c, r = call('/api/events?limit=200&q=198.51.100', client='198.51.100.50')
    check('198.51.100.66' not in said(r), 'searched for, a public view is shown the security events')
    c, r = call('/api/events?limit=200', sess=T_OWNER)
    check('198.51.100.66' in said(r) and '198.51.100.77' in said(r),
          'an administrator is not shown the security events: %s %r' % (c, str(r)[:300]))

    # ---- ntfy, kept, saved with another server ---------------------------------------------
    print('the ntfy address kept, saved with another server')
    real = 'https://:tk_pass1secret0001@ntfy.house.example/alerts'
    try:
        got = zigmon.ntfy_unkept('https://:(kept)@ntfy.evil.example/alerts', real)
        check('tk_pass1secret0001' not in got, 'the kept token went to another server: %s' % got)
    except ValueError:
        pass
    check(zigmon.ntfy_unkept('https://:(kept)@ntfy.house.example/other', real) ==
          'https://:tk_pass1secret0001@ntfy.house.example/other', 'the same server did not keep its token')
    zigmon.CONFIG['notify_ntfy'] = real
    c, r = call('/api/config', {'notify_ntfy': 'https://:(kept)@ntfy.evil.example/alerts'}, T_OWNER)
    check('evil' not in str(zigmon.CONFIG.get('notify_ntfy')),
          'saved with another server, the kept token goes there: %s %r' % (c, zigmon.CONFIG.get('notify_ntfy')))
    zigmon.CONFIG['notify_ntfy'] = ''

    # ---- zigmon --set of a secret ------------------------------------------------------------
    print('zigmon --set of a secret')
    real_need, real_call = zigmon._need_daemon, zigmon.api_call
    try:
        zigmon._need_daemon = lambda pal, path: {'runtime_config': {
            'duo_skey': {'kind': 'secret', 'value': True},
            'notify_ntfy': {'kind': 'text', 'value': 'https://:(kept)@ntfy.house.example/a'}}}
        zigmon.api_call = lambda *a, **k: (200, {'ok': True, 'changed': ['duo_skey', 'notify_ntfy']})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            zigmon.cmd_settings(argparse.Namespace(settings='duo_skey=PassOneSecretValue42', pin='', json=False),
                                zigmon.Palette(False))
            zigmon.cmd_settings(argparse.Namespace(settings='notify_ntfy=https://:tk_typed0042@ntfy.h/a', pin='',
                                                   json=False), zigmon.Palette(False))
    finally:
        zigmon._need_daemon, zigmon.api_call = real_need, real_call
    check('PassOneSecretValue42' not in out.getvalue() and 'tk_typed0042' not in out.getvalue(),
          'zigmon --set printed the secret back: %r' % out.getvalue())

    # ---- acme push: a pair with no code waiting ------------------------------------------------
    print('acme push: pairs sent with no code waiting')
    zigmon.CONFIG['cert_push'] = 1
    app_id = zigmon.push_identity(d)[0]
    L = 2 ** 252 + 27742317777372353535851937790883648493

    def ed_sign(seed, msg):
        a, prefix = zigmon._push_ed_secret(seed)
        B, enc, mul = zigmon._PUSH_ED_B, zigmon._push_ed_encode, zigmon._push_ed_mul
        A = enc(mul(a, B))
        r_ = int.from_bytes(hashlib.sha512(prefix + msg).digest(), 'little') % L
        R = enc(mul(r_, B))
        h = int.from_bytes(hashlib.sha512(R + A + msg).digest(), 'little') % L
        return R + ((r_ + h * a) % L).to_bytes(32, 'little')
    codes = []
    for n in range(3):
        seed = os.urandom(32)
        pub = zigmon.push_ed25519_public(seed)
        kid = zigmon.push_key_id(pub)
        raw = json.dumps({'acme_key': 'acme-push-ed25519 %s x@y' % base64.b64encode(pub).decode(),
                          'proof': '0' * 64}).encode()
        ts, nonce = int(time.time()), os.urandom(16).hex()
        sig = ed_sign(seed, zigmon.push_canonical('pair', app_id, kid, ts, nonce, raw))
        st, said_ = zigmon.push_request(d, 'pair', {'body': base64.b64encode(raw).decode(), 'headers': {
            'X-Acme-Push-Version': '1', 'X-Acme-Push-Key': kid, 'X-Acme-Push-Time': str(ts),
            'X-Acme-Push-Nonce': nonce, 'X-Acme-Push-Signature': base64.b64encode(sig).decode()}})
        codes.append((st, said_.get('code')))
    check(all(x == (403, 'pairing_closed') for x in codes), 'a pair with no code waiting: %r' % codes)
    seen = zigmon._push_meta(d, 'acme_push:nonces', {})
    check(not seen, 'pairs with no code waiting kept %d nonce(s)' % len(seen))
    zigmon.CONFIG['cert_push'] = 0

    # ---- the meter's details, one reading at a time --------------------------------------------
    print('the meter\'s details asked for at once')
    reads = []
    real_raw = zigmon._perf_detail_raw

    def slow_raw():
        reads.append(1)
        time.sleep(0.15)
        return {'at': time.time(), 'cores': {}, 'disks': {}, 'nics': {}, 'procs': {}}
    zigmon._perf_detail_raw = slow_raw
    try:
        zigmon.PERF_DETAIL.update(at=0.0, raw=None, out=None)
        ts_ = [threading.Thread(target=zigmon.perf_detail) for _ in range(12)]
        for t in ts_:
            t.start()
        for t in ts_:
            t.join(30)
    finally:
        zigmon._perf_detail_raw = real_raw
        zigmon.PERF_DETAIL.update(at=0.0, raw=None, out=None)
    check(len(reads) <= 4, 'twelve asks at once read the details %d times' % len(reads))
except Exception as e:                                  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(False, 'the daemon part threw %s: %s' % (type(e).__name__, e))
finally:
    try:
        api.stop()
    except Exception:                                   # noqa: BLE001
        pass

# ---- the browser ----------------------------------------------------------------------------
print('the browser: a ZIP that unpacks to more than it says')
page = (HERE / 'web' / 'index.php').read_text()
m = re.search(r'\nfunction certInflate\(.*?\n}\n', page, re.S)
zip_ = re.search(r'\nvar CERT_ZIP = .*?;\n', page)
if check(m and zip_, 'certInflate is not in the page'):
    js = zip_.group(0) + m.group(0) + r"""
var zlib = require('zlib');
var bomb = new Uint8Array(zlib.deflateRawSync(Buffer.alloc(20 * 1024 * 1024)));
certInflate(bomb, 1000).then(function (got) { console.log('GOT ' + got.length); },
                             function (e) { console.log('REFUSED ' + e.message); });
var small = new Uint8Array(zlib.deflateRawSync(Buffer.from('-----BEGIN CERTIFICATE-----')));
certInflate(small, 27).then(function (got) { console.log('SMALL ' + got.length); },
                            function (e) { console.log('SMALLFAIL ' + e.message); });
"""
    js_file = W / 'inflate.js'
    js_file.write_text(js)
    got = subprocess.run(['node', str(js_file)], capture_output=True, text=True, timeout=60,
                         stdin=subprocess.DEVNULL)
    out = got.stdout + got.stderr
    check('REFUSED' in out, 'a ZIP bomb was unpacked in full: %s' % out.strip()[:200])
    check('SMALL 27' in out, 'a small file in a ZIP did not unpack: %s' % out.strip()[:200])

print('the browser: the meter\'s details of the account before')
m = re.search(r'\nfunction lockChanged\(\) \{.*?\n}\n', page, re.S)
check(m and 'hloadForget()' in m.group(0) and 'HLOAD.detail = null' in m.group(0),
      'signing out leaves the administrator\'s processes in the panel and in sessionStorage')
finish()
