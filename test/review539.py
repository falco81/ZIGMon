#!/usr/bin/env python3
"""5.38.2: which kept secret is set, for an administrator. Wherever the page
says that a password, a token or a key is kept, an administrator sees eight
dots and its last two characters ("••••••••13"), as plexmon and otp show
them; a short one (under six characters) is dots alone. Everyone else, and
everything read before the sign-in, still says only whether one is set.

  * the daemon (in this process, its API on a port of its own): every place
    the page shows a kept secret has its hint in GET /api/secret_hints for an
    administrator - the settings, the Wi-Fi controller, the boxes and their
    broker passwords, the gateways, the boxes' broker password - and the
    destinations of the backups carry theirs in GET /api/rbackup; the object
    view of the settings says it to an administrator;
  * an operator, a read-only account and nobody signed in are refused the
    hints, and the status, /api/object and /api/auth/whoami they read carry
    neither the hint nor the last two characters of any secret (the raw
    JSON is searched);
  * root's command line (--settings) and the console's settings list say the
    hint; nothing of it in the events or the log;
  * the real page (php -S) in Chromium: a settings box of a secret has the
    hint as its placeholder, an empty value and type=password, an operator's
    page says (kept), and the Wi-Fi controller's boxes say their hints.

    python3 test/review539.py

Ports 19650 (the daemon), 19651 (php -S). Fails on 5.38.1.
"""
import contextlib
import io
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

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review539-'))
API_PORT, PHP_PORT = 19650, 19651
DOTS = '•' * 8
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


# Every secret ends in two characters of its own, which nothing else in the
# house says, so the raw answers can be searched for them.
ENDS = iter(['Qj', 'Vx', 'Kz', 'Jq', 'Xw', 'Zv', 'Wk', 'Yq', 'Fz', 'Hx', 'Pj', 'Gq', 'Bz', 'Mx',
             'Qv', 'Vj', 'Kx', 'Jz', 'Xq', 'Zj', 'Wx', 'Yz', 'Fq', 'Hj', 'Pz', 'Gx', 'Bq', 'Mj'])
# a value each setting takes, ending in its own two characters
SETTINGS = {}
SHORT_KEY = 'sms_ubus_password'          # this one short: dots only
SHORT = 'r9t'

STATE = W / 'state'
STATE.mkdir()
(W / 'etc').mkdir()
DB = STATE / 'history.db'
(W / 'etc' / 'config.json').write_text(json.dumps({'db_file': str(DB)}))
os.environ.update(ZIGMON_STATE=str(STATE), ZIGMON_CONFIG=str(W / 'etc' / 'config.json'),
                  ZIGMON_NO_SERVICES='1', ZIGMON_FS_ROOT=str(W))
for _k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(_k, None)
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

LOG = W / 'zigmon.log'
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(DB), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'log_file': str(LOG), 'state_dir': str(STATE)})
api = php = None
d = None
try:
    d = zigmon.Daemon()
    api = zigmon.ApiServer(d)
    api.start()
    time.sleep(0.3)

    def call(path, body=None, session=None, raw=False):
        headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json',
                   'X-Zigmon-Client': '192.168.40.10'}
        if session:
            headers['X-Zigmon-Session'] = session
        req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                     data=None if body is None else json.dumps(body).encode(),
                                     method='GET' if body is None else 'POST')
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                text = r.read().decode()
                code = r.status
        except urllib.error.HTTPError as e:
            text = e.read().decode()
            code = e.code
        try:
            got = json.loads(text or '{}')
        except ValueError:
            got = {}
        return (code, got, text) if raw else (code, got)

    d.account_add('owner', 'admin', 'owner pass 539', must_change=False, quiet=True)
    d.account_add('jana', 'operator', 'jana pass 539', must_change=False, quiet=True)
    d.account_add('vera', 'viewer', 'vera pass 539', must_change=False, quiet=True)
    S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 539'})[1].get('token') or ''
    S_OP = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 539'})[1].get('token') or ''
    S_RO = call('/api/auth/login', {'name': 'vera', 'password': 'vera pass 539'})[1].get('token') or ''
    check(S and S_OP and S_RO, 'the accounts could not sign in')

    # ---- every kept secret, set --------------------------------------------------------
    secret_keys = sorted(k for k, v in d.runtime_config().items() if v['kind'] == 'secret')
    check(len(secret_keys) >= 14, 'fewer secret settings than there are: %r' % secret_keys)
    for key in secret_keys:
        value = SHORT if key == SHORT_KEY else 'Aa1-%s-7' % key.replace('_', '') + next(ENDS)
        if key == 'acme_dns_tsig_secret':
            value = 'QWExLXRzaWctc2VjcmV0LTUzOQ' + next(ENDS)     # base64, as tsig-keygen makes it
        try:
            d.save_config_overrides({key: value})
            SETTINGS[key] = value
        except ValueError as e:
            check(False, 'the setting %s did not take %r: %s' % (key, value, e))
    WIFI = {'api_key': 'wifiApiKey-' + next(ENDS), 'password': 'wifiPass-' + next(ENDS),
            'ssh_password': 'sshPass-' + next(ENDS)}
    d.store.set_meta('wifi', json.dumps(dict(WIFI, host='10.9.9.9', username='u', enabled=False)))
    PLUG_PW, PLUG_MQTT, SENSOR_PW = 'plugPass-' + next(ENDS), 'plugMqtt-' + next(ENDS), 'sensPass-' + next(ENDS)
    d.save_managed([{'name': 'lamp539', 'host': '10.9.9.20', 'password': PLUG_PW, 'mqtt_password': PLUG_MQTT}],
                   [{'name': 'meter539', 'host': '10.9.9.21', 'password': SENSOR_PW}])
    GW_PW = 'gwPass-' + next(ENDS)
    d.save_managed_gateways([{'name': 'gw539', 'host': '10.9.9.30', 'username': 'admin', 'password': GW_PW}])
    BROKER = 'brokerPass-' + next(ENDS)
    d.store.set_meta('plug_mqtt_password', BROKER)
    RB_PW, RB_KP = 'rbackupDest-' + next(ENDS), 'rbKeyPass-' + next(ENDS)
    zigmon.rb_put_targets(d, [{'id': 'aaaa539aaaa5', 'kind': 'sftp', 'name': 'nas', 'host': '10.9.9.40',
                               'port': 22, 'user': 'b', 'path': 'z', 'enabled': 1, 'password': RB_PW,
                               'key_pass': RB_KP}])
    d.bump()

    def hint(v):
        return DOTS + (v[-2:] if len(v) >= 6 else '')

    ALL = dict(('config.' + k, v) for k, v in SETTINGS.items())
    ALL.update(('wifi.' + k, v) for k, v in WIFI.items())
    ALL.update({'managed.plugs.lamp539.password': PLUG_PW, 'managed.plugs.lamp539.mqtt_password': PLUG_MQTT,
                'managed.sensors.meter539.password': SENSOR_PW, 'gateways.gw539': GW_PW,
                'plug_mqtt': BROKER, 'rbackup.password': RB_PW, 'rbackup.key_pass': RB_KP})
    # what anybody but an administrator must never be told: the last two
    # characters of each (the short one has none to give away)
    TAILS = {k: v[-2:] for k, v in ALL.items() if len(v) >= 6}

    # ---- the helper ------------------------------------------------------------------------
    print('the helper')
    sh = getattr(zigmon, 'secret_hint', None)
    check(sh is not None and sh('') == '' and sh(None) == '' and sh('abc') == DOTS and sh('abcde') == DOTS
          and sh('abcdef') == DOTS + 'ef' and sh('pass1234513') == DOTS + '13',
          'secret_hint is not "" / eight dots / eight dots and the last two: %r'
          % ([sh(x) for x in ('', 'abc', 'abcdef', 'pass1234513')] if sh else None))

    # ---- an administrator: every place has its hint ------------------------------------------
    print('an administrator')
    code, got = call('/api/secret_hints', session=S)
    check(code == 200 and got.get('ok'), 'the hints are not answered to an administrator: %s %r' % (code, got))
    h = got.get('hints') or {}

    def at(path):
        v = h
        for part in path.split('.'):
            v = (v or {}).get(part) if isinstance(v, dict) else None
        return v
    code, rb = call('/api/rbackup', session=S)
    rbt = ((rb.get('targets') or [{}])[0]) if code == 200 else {}
    for place, value in sorted(ALL.items()):
        if place.startswith('config.'):
            got_hint = at(place + '.value')
        elif place.startswith('rbackup.'):
            got_hint = rbt.get(place.split('.', 1)[1] + '_hint')
        else:
            got_hint = at(place)
        check(got_hint == hint(value), '%s: the administrator\'s hint is %r, not %r' % (place, got_hint, hint(value)))
    check(at('config.%s.value' % SHORT_KEY) == DOTS, 'a short secret shows more than dots: %r'
          % at('config.%s.value' % SHORT_KEY))
    # the full values are not in it
    blob = json.dumps(got) + json.dumps(rb)
    check(h and not [p for p, v in ALL.items() if v in blob], 'a whole secret is in the administrator\'s hints')
    # the object view of the settings, to an administrator
    code, ob = call('/api/object?ref=settings', session=S)
    members = {m.get('name'): m for m in ((ob.get('object') or {}).get('members') or [])}
    tg = members.get('notify_telegram_token') or {}
    check(code == 200 and tg.get('value') == hint(SETTINGS['notify_telegram_token']),
          'the object view of the settings does not say the hint to an administrator: %r' % tg.get('value'))

    # ---- everyone else: none ---------------------------------------------------------------
    print('everyone else')
    for who, sess in (('an operator', S_OP), ('a read-only account', S_RO), ('nobody signed in', None)):
        code, got2, text = call('/api/secret_hints', session=sess, raw=True)
        check(code == 403 and DOTS not in text and h,
              'the hints are answered to %s (%s), or not kept from them' % (who, code))
        code, _, text = call('/api/rbackup', session=sess, raw=True)
        check(code == 403 and rbt.get('password_hint'), 'the backups\' hints reach %s (%s)' % (who, code))
        for road in ('/api/status', '/api/object?ref=settings', '/api/auth/whoami', '/api/objects'):
            code, _, text = call(road, session=sess, raw=True)
            leaked = sorted(p for p, t in TAILS.items() if t in text)
            check(not leaked and DOTS not in text and h,
                  '%s reads the last two characters of %r in %s' % (who, leaked[:5], road))
    # the status as it is built, for anybody
    body = d.status_body()
    body = body.decode() if isinstance(body, bytes) else json.dumps(body)
    check(not [t for t in TAILS.values() if t in body] and DOTS not in body and h,
          'the status carries a hint or the end of a secret')
    code, ob = call('/api/object?ref=settings', session=S_OP)
    members = {m.get('name'): m for m in ((ob.get('object') or {}).get('members') or [])}
    check((members.get('notify_telegram_token') or {}).get('value') == 'set' and h,
          'the object view of the settings says more than "set" to an operator: %r'
          % (members.get('notify_telegram_token') or {}).get('value'))

    # ---- root: the command line and the console ----------------------------------------------
    print('root: the command line and the console')
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        zigmon.cmd_settings(type('A', (), {'settings': 'notify_telegram', 'json': False, 'pin': ''})(),
                            zigmon.Palette(False))
    check(hint(SETTINGS['notify_telegram_token']) in out.getvalue(),
          '--settings does not say the hint to root: %r' % out.getvalue()[-200:])
    con = zigmon.Console(zigmon.Palette(False))
    con.out = lambda *a: {k: bool(v) for k, v in SETTINGS.items()}
    rows = {r['key']: r['value'] for r in con._settings_rows()}
    check(rows.get('duo_skey') == hint(SETTINGS['duo_skey'])
          and rows.get('notify_telegram_token') == hint(SETTINGS['notify_telegram_token']),
          'the console\'s settings do not say the hints: %r' % {k: rows.get(k) for k in ('duo_skey', 'notify_telegram_token')})

    # ---- never written down -----------------------------------------------------------------
    print('never written down')
    time.sleep(0.5)
    events = json.dumps(d.store.events(500), default=str)
    logged = LOG.read_text(errors='replace') if LOG.exists() else ''
    check(DOTS not in events and DOTS not in logged and h, 'a hint is in the events or the log')
    code, ex, text = call('/api/export', session=S, raw=True)
    check(DOTS not in text and h, 'a hint is in the export')

    # ---- every box of the page that says a secret is kept ---------------------------------------
    print('every box of the page')
    page = (HERE / 'web' / 'index.php').read_text()
    for place, said in (
            ('the settings boxes', "box.placeholder = keptHint(info.value, secretHint('config', key, 'value'))"),
            ('a setting\'s running value', "settingShown(info, info.value, secretHint('config', key, 'value'))"),
            ('a setting\'s config.json value', "secretHint('config', key, 'file')"),
            ('the SMS gateway\'s boxes', "keptHint(meta.value, secretHint('config', name_, 'value'), 'password')"),
            ('the Wi-Fi controller\'s API key', "keptHint(w.has_api_key, secretHint('wifi', 'api_key'))"),
            ('the Wi-Fi controller\'s password', "keptHint(w.has_password, secretHint('wifi', 'password'))"),
            ('the access points\' ssh password', "keptHint(w.has_ssh_password, secretHint('wifi', 'ssh_password'))"),
            ('a box\'s password', "managedHint(dv, 'password')"),
            ('a box\'s broker password', "managedHint(dv, 'mqtt_password')"),
            ('the boxes\' broker password', "secretHint('plug_mqtt')"),
            ('a gateway\'s password', "secretHint('gateways', g.name)"),
            ('a backup destination\'s password', "t.password_hint"),
            ('the road the hints come by', "api('secret-hints')"),
            ('the relay', "zigmon_relay('/api/secret_hints')")):
        check(said in page, 'the page does not give its hint to %s (%s)' % (place, said))
    left = [x for x in ("? '(kept)' :", "'(kept)' : ''") if x in page]
    check(not left, 'a box still says (kept) whoever looks: %r' % left)

    # ---- the real page -------------------------------------------------------------------
    print('the real page')
    if not shutil.which('php') or not shutil.which('node'):
        print('  SKIPPED: no php or node here')
    else:
        status_public = call('/api/status', raw=True)[2]
        hints_admin = call('/api/secret_hints', session=S, raw=True)[2]
        js = r'''
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({viewport: {width: 1400, height: 1000}});
  const errs = [];
  p.on('pageerror', e => errs.push(String(e)));
  const a = %(args)s;
  let asked = 0;
  await p.route(/\?api=status/, r => r.fulfill({status: 200, contentType: 'application/json', body: a.status}));
  await p.route(/\?api=secret-hints/, r => { asked++; r.fulfill({status: 200, contentType: 'application/json', body: a.hints}); });
  await p.route(/\?api=whoami/, r => r.fulfill({status: 200, contentType: 'application/json',
    body: JSON.stringify({ok: true, who: {name: 'owner', role: 'admin'}, public_view: true})}));
  await p.goto('http://127.0.0.1:%(port)d/index.php');
  await p.waitForTimeout(800);
  const box = (k) => { const x = document.querySelector('[data-k="' + k + '"]');
    return x ? {type: x.type, value: x.value, ph: x.placeholder} : null; };
  const out = {};
  out.admin = await p.evaluate(async (a) => {
    const o = {};
    try {
      LOCK.who = {name: 'owner', role: 'admin'};
      const st = JSON.parse(a.status);
      STATE.status = st;
      secretHintsAsk(st);
      for (let i = 0; i < 50 && !(HINTS && HINTS.d); i++) await new Promise(r => setTimeout(r, 100));
      SETTINGS.dirty = false;
      renderSettings(st);
      const one = k => { const x = document.querySelector('input[data-k="' + k + '"]');
        return x ? {type: x.type, value: x.value, ph: x.placeholder} : null; };
      o.tg = one('notify_telegram_token'); o.wp = one('webproxy_password');
      renderWifiConfig(st);
      o.wifi = ['wifi-key', 'wifi-pass', 'ssh-pass'].map(id => { const x = document.getElementById(id);
        return x ? {type: x.type, value: x.value, ph: x.placeholder} : null; });
    } catch (e) { o.err = String(e); }
    return o;
  }, a);
  out.op = await p.evaluate((a) => {
    const o = {};
    try {
      LOCK.who = {name: 'jana', role: 'operator'};
      const st = JSON.parse(a.status);
      secretHintsAsk(st);
      SETTINGS.dirty = false;
      renderSettings(st);
      renderWifiConfig(st);
      const x = document.querySelector('input[data-k="notify_telegram_token"]');
      o.tg = x ? {type: x.type, value: x.value, ph: x.placeholder} : null;
      const dots = '•'.repeat(8);
      // what is drawn: the text and every box (the page's script holds the word too)
      o.html = document.body.innerText.indexOf(dots) >= 0
        || Array.from(document.querySelectorAll('input')).some(x => (x.placeholder + x.value).indexOf(dots) >= 0);
    } catch (e) { o.err = String(e); }
    return o;
  }, a);
  out.asked = asked;
  out.errs = errs.slice(0, 3);
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
''' % {'port': PHP_PORT, 'args': json.dumps({'status': status_public, 'hints': hints_admin})}
        (W / 'run.js').write_text(js)
        php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, '-t', str(HERE / 'web')],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        for _ in range(50):
            try:
                socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
        got = subprocess.run(['node', str(W / 'run.js')], capture_output=True, text=True, timeout=120,
                             stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=root))
        php.kill()
        php.wait()
        php = None
        try:
            r = json.loads(got.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            r = {'error': (got.stdout + got.stderr)[-300:]}
        if r.get('error') and 'playwright' in r['error'].lower():
            print('  SKIPPED (no browser here): %s' % r['error'][:200])
        else:
            ad, op = r.get('admin') or {}, r.get('op') or {}
            for k, label in (('tg', 'notify_telegram_token'), ('wp', 'webproxy_password')):
                one = ad.get(k) or {}
                check(one.get('type') == 'password' and one.get('value') == ''
                      and one.get('ph') == hint(SETTINGS[label]),
                      'the settings box of %s to an administrator: %r %s' % (label, one, ad.get('err', '')))
            want = [hint(WIFI['api_key']), hint(WIFI['password']), hint(WIFI['ssh_password'])]
            check([(x or {}).get('ph') for x in ad.get('wifi') or []] == want
                  and all((x or {}).get('value') == '' and (x or {}).get('type') == 'password'
                          for x in ad.get('wifi') or [None]),
                  'the Wi-Fi controller\'s boxes to an administrator: %r' % ad.get('wifi'))
            one = op.get('tg') or {}
            check(one.get('ph') == '(kept)' and one.get('value') == '' and not op.get('html')
                  and not op.get('err') and (r.get('asked') or 0) >= 1,
                  'an operator\'s page: %r, a hint on the page: %r, asked %r times %s'
                  % (one, op.get('html'), r.get('asked'), op.get('err', '')))
            check(not r.get('errs'), 'the page threw: %r' % r.get('errs'))
finally:
    if php is not None:
        php.kill()
        php.wait()
    try:
        if api is not None:
            api.stop()
    except Exception:                                   # noqa: BLE001
        pass

if bad:
    print('\nreview539: FAILED (%d)' % len(bad))
    raise SystemExit(1)
shutil.rmtree(str(W), ignore_errors=True)
print('\nreview539: ok')
