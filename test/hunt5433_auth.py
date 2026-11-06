#!/usr/bin/env python3
"""5.43.3: a hunt through signing in, the sign-ins, passkeys, the relay and the
one-tap links. Each check here failed on 5.43.2:

  * a one-tap link asked how it stands (?ask) never acts - one that runs a
    script or keeps an address out ran it, past the code and past Duo;
  * a press approved through Duo keeps what it carried (X-Zigmon-Arg-...);
  * the relay cuts a name and a password by letters, not by bytes: a long
    password with a letter outside ASCII in it could never sign in, or was
    cut in the middle of a letter and the page got an empty 500;
  * a passkey answer whose origin is not a string, or a self attestation
    whose signature is a text, is refused - not a 500;
  * the hidden values shown on the dashboard are written down as shown to
    the administrator who asked, not "from the command line";
  * an account is "signed in" as often as its live sign-ins, not counting
    the ones that ran out long ago.

    python3 test/hunt5433_auth.py
"""
import base64
import http.cookiejar
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(os.environ.get('ZIGMON_HUNT_HERE') or Path(__file__).resolve().parent.parent)
W = Path(tempfile.mkdtemp(prefix='zigmon-hunt5433-auth-'))
API_PORT, PHP_PORT = 19570, 19571
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def finish():
    for p in PROCS:
        try:
            p.terminate()
            p.wait(5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    shutil.rmtree(str(W), ignore_errors=True)
    print('hunt5433_auth: %s' % ('%d failed' % len(bad) if bad else 'all good'))
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
    d.account_add('petr', 'viewer', 'petr pass 12', must_change=False, quiet=True)
except Exception as e:                                  # noqa: BLE001
    check(False, 'the daemon could not be started: %s' % e)
    finish()
HOST = 'house.example.org'


def call(path, body=None, sess=None, client='192.168.40.10', host=HOST, cli=False):
    h = {'Content-Type': 'application/json', 'X-Zigmon-Token': d.token}
    if client:
        h['X-Zigmon-Client'] = client
    if host:
        h['X-Zigmon-Host'] = host
    if sess:
        h['X-Zigmon-Session'] = sess
    if cli:
        h['X-Zigmon-Cli'] = d.cli_key
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


def b64e(raw):
    return base64.urlsafe_b64encode(bytes(raw)).decode('ascii').rstrip('=')


try:
    T_OWNER = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token', '')
    check(T_OWNER, 'the administrator of the test could not sign in')

    # ---- a link asked how it stands acts on nothing ------------------------------------------
    print('?ask on a link that runs a script or keeps an address out')
    script = d.save_scripts([{'name': 'Hunt', 'body': 'say ran it'}])[0]
    ran = []
    real_run = d.run_script

    def counting_run(*a, **kw):
        ran.append(a[0].get('name') if a else '?')
        return real_run(*a, **kw)
    d.run_script = counting_run
    d.save_taps([{'name': 'Run it', 'target': 'script:' + script['id'], 'do': 'script'},
                 {'name': 'Keep out', 'target': '{ip}', 'do': 'ban', 'vars': [{'name': 'ip'}]}])
    d.save_tap_keys([{'name': 'phone'}])
    zigmon.CONFIG.update({'tap_code': 1, 'tap_mode': 'both', 'tap_factor': 'totp'})
    taps = {t['name']: t for t in d.taps()}
    for way in ('link', 'header'):
        ok, answer = d.tap(taps['Run it']['token'], '198.51.100.20', ask=True, way=way)
        check(ok and not ran, 'asking a script link by its %s ran the script with no code: %r %r'
              % ('address' if way == 'link' else 'header', answer, ran))
        ran[:] = []
        ok, answer = d.tap(taps['Keep out']['token'], '198.51.100.20', ask=True, way=way,
                           carried={'ip': '203.0.113.%d' % (7 if way == 'link' else 8)})
        kept = [r.get('ip') for r in d.store.blocked_all()]
        check(not kept, 'asking a ban link by its %s kept %r out with no code: %r'
              % ('address' if way == 'link' else 'header', kept, answer))
    ok, answer = d.tap(taps['Run it']['token'], '198.51.100.20', way='link')
    check(not ok and not ran, 'the address road ran a script past the code: %r' % (answer,))
    code = zigmon.totp_at(d.tap_keys()[0]['secret'], int(time.time() // zigmon.TOTP_STEP))
    ok, answer = d.tap(taps['Run it']['token'], '198.51.100.20', way='header', code=code)
    check(ok and ran, 'a press with the right code did not run the script: %r' % (answer,))
    d.run_script = real_run

    # ---- a press approved through Duo keeps what it carried --------------------------------
    print('a press approved through Duo')
    zigmon.CONFIG.update({'tap_factor': 'duo', 'duo_host': 'api-x.duosecurity.com', 'duo_ikey': 'DIXXXXXXXXXXXXXXXXXX',
                          'duo_skey': 'duo secret key of forty letters 1234567', 'duo_user': 'owner'})
    d.duo_push = lambda what, who='': (True, 'approved')
    ok, answer = d.tap(taps['Keep out']['token'], '198.51.100.21', way='header',
                       carried={'ip': '203.0.113.44'})
    check(ok and isinstance(answer, dict) and answer.get('ticket'), 'Duo was not asked: %r' % (answer,))
    if isinstance(answer, dict) and answer.get('ticket'):
        ok, said = d.tap_waiting(answer['ticket'], 10)
        kept = [r.get('ip') for r in d.store.blocked_all()]
        check('203.0.113.44' in kept, 'a ban link approved through Duo lost the address it carried: %r %r'
              % (said, kept))
    zigmon.CONFIG.update({'tap_code': 0, 'tap_mode': 'link', 'tap_factor': 'totp', 'duo_host': '',
                          'duo_ikey': '', 'duo_skey': '', 'duo_user': ''})

    # ---- passkey answers of the wrong shape -------------------------------------------------
    print('passkey answers of the wrong shape')
    zigmon.CONFIG['passkeys'] = 1
    c, o = call('/api/auth/passkey/begin', {})
    client = json.dumps({'type': 'webauthn.get', 'challenge': o.get('publicKey', {}).get('challenge', ''),
                         'origin': ['https://' + HOST]}).encode()
    c, r = call('/api/auth/passkey/login', {'id': 'AAAAAAAAAAAAAAAAAAAAAA', 'clientDataJSON': b64e(client),
                                            'authenticatorData': b64e(b'\0' * 37), 'signature': b64e(b'x')})
    check(c in (400, 401) and 'another page' in r.get('error', ''),
          'a passkey answer with a list for its origin was a %s, not a refusal: %r' % (c, r))
    try:
        said = zigmon.pk_signed_ok('-----BEGIN PUBLIC KEY-----\n-----END PUBLIC KEY-----\n', 'text', b'data')
        check(said is False, 'a signature that is a text was taken: %r' % said)
    except Exception as e:                              # noqa: BLE001
        check(False, 'a self attestation whose signature is a text threw %s (a 500)' % type(e).__name__)
    zigmon.CONFIG['passkeys'] = False

    # ---- the hidden values, said by who asked ------------------------------------------------
    print('the hidden values, written down by who asked')
    c, r = call('/api/secrets', {}, T_OWNER)
    check(c == 200, 'an administrator could not read the hidden values: %s %r' % (c, r))
    d.store.flush()
    said = [e.get('detail') or '' for e in d.store.events(20) if 'hidden values' in (e.get('detail') or '')]
    check(said and 'owner' in said[0] and 'command line' not in said[0],
          'the hidden values read on the dashboard were written down as: %r' % said[:1])
    c, r = call('/api/secrets', {}, client='', cli=True)
    d.store.flush()
    said = [e.get('detail') or '' for e in d.store.events(20) if 'hidden values' in (e.get('detail') or '')]
    check(said and 'command line' in said[0], 'the command line reading them is not said: %r' % said[:1])
    for word in (d.token, d.cli_key, T_OWNER):
        check(not any(word in (e.get('detail') or '') for e in d.store.events(200)),
              'a token or a key is in the events')

    # ---- signed in as often as it really is ----------------------------------------------------
    print('signed in as often as it really is')
    gone = [call('/api/auth/login', {'name': 'petr', 'password': 'petr pass 12'})[1].get('token', '')
            for _ in range(3)]
    for t in gone[:2]:
        d.signins[d._token_hash(t)]['last'] -= 3 * 24 * 3600          # idle for three days
    row = next((a for a in d.accounts_list() if a['name'] == 'petr'), {})
    live = [s for s in d.signins_list() if s['name'] == 'petr']
    check(row.get('signed_in') == 1 and len(live) == 1,
          'an account read "signed in %s times" beside a list of %d live sign-ins'
          % (row.get('signed_in'), len(live)))

    # ---- the relay: a long password with a letter outside ASCII --------------------------------
    print('the relay and a long password')
    php = shutil.which('php')
    if not php:
        print('  (no php here: the relay is not checked)')
    else:
        web = W / 'web'
        shutil.copytree(str(HERE / 'web'), str(web))
        api_php = web / 'zigmon-api.php'
        api_php.write_text(api_php.read_text()
                           .replace('const ZIGMON_PORT  = 9849;', 'const ZIGMON_PORT  = %d;' % API_PORT)
                           .replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';",
                                    "const ZIGMON_TOKEN = '%s';" % (W / 'run' / 'api-token')))
        srv = subprocess.Popen([php, '-S', '127.0.0.1:%d' % PHP_PORT, '-t', str(web)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        PROCS.append(srv)
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        B = 'http://127.0.0.1:%d/index.php' % PHP_PORT

        def page(path, body):
            op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            r = urllib.request.Request(B + path, data=json.dumps(body).encode(),
                                       headers={'Content-Type': 'application/json'}, method='POST')
            try:
                with op.open(r, timeout=30) as x:
                    return x.status, x.read().decode('utf-8', 'replace')
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode('utf-8', 'replace')

        for pw in ('é' * 150, 'a' + 'é' * 150):
            d.account_change('petr', password=pw, must_change=False)
            c, text = page('?api=login', {'name': 'petr', 'password': pw})
            check(c == 200 and '"petr"' in text, 'a password of %d letters (%d bytes) set by an administrator '
                  'cannot sign in on the page: %s %r' % (len(pw), len(pw.encode()), c, text[:120]))
        c, text = page('?api=login', {'name': 'a' + 'é' * 40, 'password': 'whatever it is'})
        check(c == 401 and text.startswith('{'), 'a long name cut in the middle of a letter was a %s %r, '
              'not a refusal' % (c, text[:80]))
    # ---- a save is all or nothing (5.43.3) ---------------------------------------------
    print('a settings save refused part of the way through changes nothing')
    keys = list(zigmon.Daemon.TUNABLE)
    first = next(k for k in keys if k == 'battery_warn')
    later = next(k for k in keys[keys.index(first) + 1:] if k == 'reboot_auto') \
        if 'reboot_auto' in keys[keys.index(first) + 1:] else None
    if later:
        was = zigmon.CONFIG.get(first)
        new_v = 41 if was != 41 else 42
        try:
            d.save_config_overrides({first: new_v, later: 'every full moon'})
            refused = False
        except ValueError:
            refused = True
        check(refused and zigmon.CONFIG.get(first) == was,
              'a save refused for %s left %s at %r (it was %r) - in force, not saved'
              % (later, first, zigmon.CONFIG.get(first), was))
    else:
        check(False, 'the test needs battery_warn before reboot_auto among the settings')
    # ---- the ntfy addresses in the status (5.43.3) ------------------------------------
    # whoever has one reads every notification, a token in it opens the server:
    # the status went to every page - a visitor's too, in the public view - whole
    print('the ntfy addresses only for an administrator')
    secret = 'https://:tk_hunt5433secretvalue@ntfy.example.net/zigmon-house-hunt'
    zigmon.CONFIG['notify_ntfy'] = secret
    d.seq += 1
    c, st = call('/api/status')
    check(c == 200 and 'tk_hunt5433secretvalue' not in json.dumps(st)
          and (st.get('runtime_config') or {}).get('notify_ntfy', {}).get('value') == '(kept)',
          'a visitor\'s status carried the ntfy address with its token: %r'
          % ((st.get('runtime_config') or {}).get('notify_ntfy'),))
    c, st = call('/api/status', sess=T_OWNER)
    # an administrator's page: the server and the topic, its token kept (as test/hunt5433_msg.py wants)
    _adm = (st.get('runtime_config') or {}).get('notify_ntfy', {}).get('value') or ''
    check(c == 200 and _adm.endswith('@ntfy.example.net/zigmon-house-hunt') and 'tk_hunt5433secretvalue' not in _adm,
          'an administrator\'s page lost the ntfy address it edits: %r'
          % ((st.get('runtime_config') or {}).get('notify_ntfy'),))
    d.save_config_overrides({'notify_ntfy': '(kept)'})
    check(zigmon.CONFIG.get('notify_ntfy') == secret,
          'the ntfy address as a visitor\'s page was shown it, sent back, replaced it: %r'
          % zigmon.CONFIG.get('notify_ntfy'))
except Exception as e:                                  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(False, 'the checks stopped on %s: %s' % (type(e).__name__, e))
finish()
