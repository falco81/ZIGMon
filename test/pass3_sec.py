#!/usr/bin/env python3
"""5.46, pass 3: the secrets of the full logs of the server in front, and the
administrator's roads. Each of the first checks failed on 5.46.0:

  * mask_pairs / full_mask let through whole: a key spelt pass%77ord or
    pass\\u0077ord, client_secret, id_token, jwt=, Passwort, mot_de_passe,
    the link's own X-Zigmon-Tap written in a query, a password in a list
    or in single quotes, a passphrase with a space in it (all but its first
    word), a secret under a key holding an object, a name and a password in
    front of a host in the Referer or the Origin, a JWT's claims and
    signature in an address, ntfy's tk_ token wherever it stood, a field of
    somebody's own format holding a map (written as its repr);
  * "Basic <key>:" - a key sent as the name, nothing after the colon - was
    written "Basic user:<the key> •";
  * a field "authk" holding a login that is NOT one everybody knows was
    kept as it came;
  * the plain access log: "POST /tap/<a link's secret>" and "?token=..." went
    whole into the anomalies (and so into the reasons of a block, the events
    and the notifications) and into proxy_lines, the address story;
  * the server in front as a device: a hostname that is its FQDN - the very
    proxy_host only an administrator is shown - was the device's name, which
    viewers and the public view see;
  * the front configs, in a real nginx: a body written over several lines
    went to the file whole (no map matched across a newline), and so did
    every one of the shapes above.

...and what is checked again here, which held on 5.46.0: /api/blocked,
/api/approvals, /api/trial, /api/address/intel and /api/proxy/requests answer
an administrator only - nobody signed in, a viewer and an operator are
refused - through the daemon and through the PHP relay; the SSLProxy tile
names the server and the addresses to an administrator only.

    python3 test/pass3_sec.py < /dev/null

Every secret below is made up. Ports 19800-19801 (nginx), 19804 (the daemon),
19805 (php -S).
"""
import base64
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(os.environ.get('PASS3_HERE') or Path(__file__).resolve().parent.parent)
W = Path(tempfile.mkdtemp(prefix='zigmon-pass3-sec-'))
NGX_PORT, NGX_BACK, API_PORT, PHP_PORT = 19800, 19801, 19804, 19805
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def finish():
    for p in PROCS:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    shutil.rmtree(str(W), ignore_errors=True)
    print('pass3_sec: %s' % ('%d failed' % len(bad) if bad else 'all good'))
    sys.stdout.flush()
    os._exit(1 if bad else 0)


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

S = 'Qw7-Secret-Otter-5521'                  # one made-up secret, everywhere
TK = 'tk_' + 'a1B2c3D4e5F6g7H8i9J0k1L2m3N4o'   # the shape of an ntfy token
PHRASE = 'correct horse battery staple'


def whole(text):
    """Is any recognisable part of a secret left?"""
    text = str(text)
    return any(p in text for p in (S[:8], S[-8:], TK[3:15], 'horse battery', 'battery staple'))


# ---- the shapes ----------------------------------------------------------------
print('the shapes the house masks')
SHAPES = {
    'pct-key': '/x?pass%77ord=' + S,
    'uni-key': '{"pass\\u0077ord":"' + S + '"}',
    'client_secret': '/x?client_secret=' + S,
    'id_token': '/x?id_token=' + S,
    'jwt=': '/x?jwt=' + S,
    'Passwort': '/x?Passwort=' + S,
    'mot_de_passe': 'mot_de_passe=' + S,
    'tap-in-query': '/x?X-Zigmon-Tap=' + S,
    'fragment': '/x#access_token=' + S,
    'list': '{"password":["' + S + '"]}',
    'single-quotes': "{'password': '" + S + "'}",
    'passphrase': '{"password": "' + PHRASE + '"}',
    'object': '{"data":{"credentials":{"x":"' + S + '"}}}',
    'camel': '{"accessToken":"' + S + '"}',
    'userinfo': 'https://jan:' + S + '@x.example/',
    'jwt-anywhere': '/x?x=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.' + S,
    'ntfy-token': '/x/' + TK + '/json',
}
for name, text in SHAPES.items():
    for field in ('u', 'body', 'ref'):
        out = json.dumps(zigmon.full_mask({'ip': '203.0.113.5', field: text}), ensure_ascii=False)
        check(not whole(out), '%s in %s is kept: %s' % (name, field, out[:160]))
        again = zigmon.full_mask(json.loads(out))
        check(json.dumps(again, ensure_ascii=False) == out, '%s in %s: masked twice is not masked once' % (name, field))
out = json.dumps(zigmon.full_mask({'ip': '203.0.113.5', 'origin': 'https://u:' + S + '@x.example'}))
check(not whole(out), 'a password in front of the host in the Origin is kept: %s' % out)
# ...and what is no secret stays as it was
p = zigmon.mask_pairs('/x?spin=4&keyword=lamp&x=1&q=porch&author=jan')
check(p == '/x?spin=4&keyword=lamp&x=1&q=porch&author=jan', 'what is no secret is masked: %r' % p)
p = zigmon.mask_pairs(json.dumps({'username': 'jan', 'password': S, 'q': 'lamp'}))
check('"jan"' in p and '"lamp"' in p and not whole(p), 'a JSON body: %r' % p)
# a field of somebody's own format holding a map
out = json.dumps(zigmon.full_mask({'ip': '203.0.113.5', 'hdrs': {'authorization': 'Bearer ' + S}}))
check(not whole(out), 'a map in a field of somebody\'s own format is kept: %s' % out)
# a key sent as the name of a Basic login
m, said = zigmon.mask_auth('Basic ' + base64.b64encode(('sk_live_' + S + ':').encode()).decode())
check(not whole(m), 'a key sent as a Basic login\'s name is kept: %r' % m)
m, said = zigmon.mask_auth('Basic ' + base64.b64encode(b'admin:').decode())
check(said.get('authk') == 'admin:', 'admin with no password is no longer known for what it is: %r' % said)
m, said = zigmon.mask_auth('Basic ' + base64.b64encode(('phone:' + S).encode()).decode())
check(m.startswith('Basic user:phone ') and not whole(m), 'the house\'s Basic login: %r' % m)
# authk is the login everybody knows, or nothing
one = zigmon.full_mask({'ip': '203.0.113.5', 'authk': 'phone:' + S[:12]})
check('authk' not in one, 'a login nobody knows is kept as "the login everybody knows": %r' % one)
one = zigmon.full_mask({'ip': '203.0.113.5', 'authk': 'root:toor'})
check(one.get('authk') == 'root:toor', 'root:toor is not kept: %r' % one)

# ---- a daemon ------------------------------------------------------------------
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [],
                      'mqtt_host': '', 'log_file': str(W / 'zigmon.log'), 'log_to_journal': False,
                      'state_dir': str(W / 'state'), 'never_block': '', 'block_ladder': '',
                      'block_mode': 'temporary', 'blacklist': 1, 'block_score': 15, 'feeds_ban': 0,
                      'feeds': '', 'intel_shodan': 0, 'intel_talos': 0, 'intel_on_block': 0, 'mikrotik_host': '',
                      'mikrotik_list': '', 'trusted_proxies': '', 'proxy_host': '', 'debug': 1,
                      'public_view': True})
(W / 'state').mkdir()
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
d.mikrotik_after_change = lambda *a, **k: None
d.feed_wanted = lambda: []
d.proxy_run = lambda command: ''

print('the plain access log: anomalies and the address story')
LINK = 'Zt4xQ9wLmP2vR8kS' + S[-4:]
LINES = ['203.0.113.61 - - [07/Nov/2026:10:00:0%d +0000] "POST /tap/%s?token=%s HTTP/1.1" 404 0 "-" "curl/8"'
         % (i, LINK, S) for i in range(3)]
LINES.append('203.0.113.62 - - [07/Nov/2026:10:00:05 +0000] "GET /v1/?auth=%s&password=%s HTTP/1.1" 404 0 "-" "x"'
             % (S, S))
d.proxy_weigh(LINES)
d.store.flush() if hasattr(d.store, 'flush') else None
db = sqlite3.connect(str(W / 'z.db'))
paths = [r[0] for r in db.execute('SELECT path FROM proxy_lines')]
check(paths, 'nothing was kept of the access log (the test is not testing)')
check(not any(whole(x) or LINK in x for x in paths), 'a secret is in proxy_lines whole: %r' % [x[:50] for x in paths])
told = json.dumps({k: v for k, v in d._anomaly.items()})
check('203.0.113.61' in told, 'no anomaly was noted (the test is not testing)')
check(not whole(told) and LINK not in told, 'a secret is in the anomalies whole: %s' % told[:300])
d.note_anomaly('203.0.113.63', 'proxy-poking', 'GET /x?id_token=%s' % S, source='proxy')
check(not whole(json.dumps(d._anomaly.get('203.0.113.63'))), 'a detail handed to note_anomaly is kept whole')

print('the server in front as a device: its name')
mk = 'ZT'
text = '%s host\nfront.house.example\n%s end\n' % (mk, mk)
zigmon.CONFIG['proxy_host'] = 'front.house.example'
got = zigmon.proxy_tile_parse(text, mk)
check(got['hostname'] in ('', 'SSLProxy') and 'house.example' not in got['hostname'],
      'the device is named after proxy_host: %r' % got['hostname'])
zigmon.CONFIG['proxy_host'] = '10.8.0.1'
got = zigmon.proxy_tile_parse(text, mk)
check(got['hostname'] == 'front', 'an FQDN hostname is not its first label: %r' % got['hostname'])
got = zigmon.proxy_tile_parse('%s host\nvps-7\n%s end\n' % (mk, mk), mk)
check(got['hostname'] == 'vps-7', 'a short hostname is not kept: %r' % got['hostname'])
zigmon.CONFIG['proxy_host'] = ''

# ---- the administrator's roads ---------------------------------------------------
print('the administrator\'s roads, through the daemon')
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def call(path, body=None, sess='', base=None, cookie=False):
    if base:
        h = {'Content-Type': 'application/json'}
        if sess:
            h['Cookie'] = 'zigmon_session=' + sess
        url = base + path
    else:
        h = {'Content-Type': 'application/json', 'X-Zigmon-Token': d.token, 'X-Zigmon-Client': '192.168.40.10'}
        if sess:
            h['X-Zigmon-Session'] = sess
            if body is not None:
                body = dict(body, session=sess)
        url = 'http://127.0.0.1:%d%s' % (API_PORT, path)
    r = urllib.request.Request(url, headers=h, data=None if body is None else json.dumps(body).encode(),
                               method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(r, timeout=60) as x:
            raw = x.read()
            try:
                return x.status, json.loads(raw or b'{}')
            except ValueError:
                return x.status, {'raw': raw[:200]}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'{}')
        except ValueError:
            return e.code, {}


d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
d.account_add('opal', 'operator', 'opal pass 1234', must_change=False, quiet=True)
d.account_add('watcher', 'viewer', 'watcher pass 12', must_change=False, quiet=True)
SESS = {}
for name, pw in (('owner', 'owner pass 12'), ('opal', 'opal pass 1234'), ('watcher', 'watcher pass 12')):
    SESS[name] = call('/api/auth/login', {'name': name, 'password': pw})[1].get('token', '')
    check(SESS[name], '%s could not sign in' % name)
ROADS = [('/api/blocked', None, 'blocked'), ('/api/approvals', None, 'approvals'),
         ('/api/proxy/requests', None, 'proxy-requests'),
         ('/api/trial', {'do': 'list'}, 'trial'),
         ('/api/address/intel', {'ip': '203.0.113.5'}, 'address-intel')]
for path, body, _ in ROADS:
    for who in ('', 'watcher', 'opal'):
        c, r = call(path, body, SESS.get(who, ''))
        check(c == 403, '%s answered %s to %s: %r' % (path, c, who or 'nobody signed in', str(r)[:120]))
    c, r = call(path, body, SESS['owner'])
    check(c == 200, '%s refused an administrator: %s %r' % (path, c, str(r)[:160]))

print('...and through the PHP relay')
if not shutil.which('php'):
    print('  SKIPPED: no php here')
else:
    shutil.copytree(HERE / 'web', W / 'web')
    api_php = (W / 'web' / 'zigmon-api.php').read_text()
    api_php = api_php.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
    api_php = api_php.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
    (W / 'web' / 'zigmon-api.php').write_text(api_php)
    php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, str(W / 'web' / 'index.php')], cwd=str(W / 'web'),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    PROCS.append(php)
    for _ in range(50):
        try:
            socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    base = 'http://127.0.0.1:%d/index.php?api=' % PHP_PORT
    for path, body, what in ROADS:
        for who in ('', 'watcher', 'opal'):
            c, r = call(what, body, SESS.get(who, ''), base=base)
            check(c == 403, 'the relay\'s %s answered %s to %s: %r' % (what, c, who or 'nobody', str(r)[:120]))
        c, r = call(what, body, SESS['owner'], base=base)
        check(c == 200, 'the relay\'s %s refused an administrator: %s %r' % (what, c, str(r)[:160]))

print('the SSLProxy tile: the server and the addresses an administrator\'s')
zigmon.CONFIG.update({'proxy_host': '10.8.0.1', 'proxy_log': '/var/log/nginx/zigmon-tap.log', 'proxy_watch': 1})
d._proxy_tile_look = {'ok': True, 'at': int(time.time()), 'tried': int(time.time()), 'hostname': 'vps-7',
                      'nginx': {'state': 'active', 'top': [{'n': 9, 'ip': '203.0.113.77'}]},
                      'suricata': {'state': 'active', 'top': [{'n': 2, 'priority': 1, 'msg': 'ET SCAN x'}],
                                   'sources': [{'n': 2, 'ip': '203.0.113.78'}]}}
d._proxy_tile_started = time.time()
for who in ('', 'watcher', 'opal'):
    c, r = call('/api/proxy-tile', None, SESS.get(who, ''))
    flat = json.dumps(r)
    check(c == 200 and r.get('on') and '10.8.0.1' not in flat and '203.0.113.7' not in flat and 'ET SCAN' not in flat,
          'the tile shows %s the server or the addresses: %s %s' % (who or 'nobody', c, flat[:200]))
c, r = call('/api/proxy-tile', None, SESS['owner'])
flat = json.dumps(r)
check('10.8.0.1' in flat and '203.0.113.77' in flat, 'the tile does not show an administrator: %s' % flat[:200])
zigmon.CONFIG.update({'proxy_host': '', 'proxy_log': '', 'proxy_watch': 0})

# ---- the front configs in a real nginx ----------------------------------------------
print('the front configs, in a real nginx')
if not shutil.which('nginx'):
    print('  SKIPPED: no nginx here')
    finish()
N = W / 'ngx'
(N / 'logs').mkdir(parents=True)
(N / 'tmp').mkdir()
maps = []
for f in ('nginx-tap-front.conf', 'nginx-ntfy-front.conf'):
    text = (HERE / 'deploy' / f).read_text()
    for block in re.finditer(r'(?ms)^map \$\S+ \$\S+ \{.*?^\}\n|^log_format \w+ escape=json\n.*?\';\n', text):
        maps.append(block.group(0))
(N / 'front.conf').write_text('\n'.join(maps))
(N / 'nginx.conf').write_text('''worker_processes 1; pid %(n)s/nginx.pid; error_log %(n)s/logs/error.log; daemon on;
events {}
http { client_body_temp_path tmp; proxy_temp_path tmp; fastcgi_temp_path tmp; uwsgi_temp_path tmp; scgi_temp_path tmp;
  include %(n)s/front.conf;
  server { listen 127.0.0.1:%(p)d; access_log %(n)s/logs/tap.log tapfull; access_log %(n)s/logs/ntfy.log ntfyfull;
    client_body_buffer_size 8k; client_body_in_single_buffer on;
    location / { proxy_pass http://127.0.0.1:%(b)d; } }
  server { listen 127.0.0.1:%(b)d; access_log off; location / { return 200 ok; } }
}
''' % {'n': N, 'p': NGX_PORT, 'b': NGX_BACK})
got = subprocess.run(['nginx', '-p', str(N), '-c', str(N / 'nginx.conf')], capture_output=True, text=True,
                     stdin=subprocess.DEVNULL)
if not check(got.returncode == 0, 'nginx would not start with the front maps: %s' % got.stderr[-400:]):
    finish()


def send(path, headers=(), body=None):
    h = ''.join('%s: %s\r\n' % kv for kv in headers)
    if body is not None:
        h += 'Content-Length: %d\r\nContent-Type: application/json\r\n' % len(body.encode())
    s = socket.create_connection(('127.0.0.1', NGX_PORT), 5)
    s.sendall(('%s %s HTTP/1.1\r\nHost: x\r\nConnection: close\r\n%s\r\n%s'
               % ('POST' if body is not None else 'GET', path, h, body or '')).encode())
    s.settimeout(5)
    try:
        s.recv(4096)
    except OSError:
        pass
    s.close()


CASES = [
    ('a body over several lines', '/a', (), '{\n  "user": "x",\n  "password": "' + S + '"\n}'),
    ('a passphrase', '/a', (), '{"password": "' + PHRASE + '"}'),
    ('pass%77ord', '/a?pass%77ord=' + S, (), None),
    ('X-Zigmon-Tap in a query', '/a?X-Zigmon-Tap=' + S, (), None),
    ('id_token', '/a?id_token=' + S, (), None),
    ('client_secret', '/a?client_secret=' + S, (), None),
    ('a fragment', '/a#access_token=' + S, (), None),
    ('a name and password in the Referer', '/a', (('Referer', 'https://u:' + S + '@x.example/'),), None),
    ('a name and password in the Origin', '/a', (('Origin', 'https://u:' + S + '@x.example'),), None),
    ('single quotes', '/a', (), "{'password': '" + S + "'}"),
    ('a list', '/a', (), '{"password":["' + S + '"]}'),
    ('an object', '/a', (), '{"data":{"credentials":{"x":"' + S + '"}}}'),
    ('pass\\u0077ord', '/a', (), '{"pass\\u0077ord":"' + S + '"}'),
    ('a JWT in a query', '/a?x=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.' + S, (), None),
    ('five in a form', '/a', (), 'token=a1234567&token=b1234567&token=c1234567&token=d1234567&password=' + S),
    ('lowercase basic', '/a', (('Authorization', 'basic ' + base64.b64encode(('u:' + S).encode()).decode()),), None),
    ('a cookie with spaces and quotes', '/a', (('Cookie', 'a = ' + S + '; b="' + S + ' x"'),), None),
    ('a cookie with no =', '/a', (('Cookie', S),), None),
    ('Digest', '/a', (('Authorization', 'Digest username="u", response="' + S + '"'),), None),
    ('no secret at all', '/a?spin=4&keyword=lamp&x=1', (), '{"q":"porch","n":2}'),
]
for _, path, headers, body in CASES:
    send(path, headers, body)
time.sleep(0.6)
try:
    os.kill(int((N / 'nginx.pid').read_text().strip()), 15)
except (OSError, ValueError):
    pass
for log_name in ('tap', 'ntfy'):
    lines = (N / 'logs' / (log_name + '.log')).read_text(errors='replace').splitlines()
    if not check(len(lines) == len(CASES), '%s: nginx wrote %d lines for %d requests' % (log_name, len(lines), len(CASES))):
        continue
    for (what, _p, _h, _b), line in zip(CASES, lines):
        check(not whole(line), '%s: %s written whole: %s' % (log_name, what, line[:200]))
    last = json.loads(lines[-1])
    check(last.get('u') == '/a?spin=4&keyword=lamp&x=1' and last.get('body') == '{"q":"porch","n":2}',
          '%s: what is no secret is masked: %r %r' % (log_name, last.get('u'), last.get('body')))
    # ...and read by the house as it reads them, nothing comes back whole
    for line in lines:
        check(not whole(zigmon.full_mask_line(line)), '%s: the house reads a secret whole' % log_name)
err = (N / 'logs' / 'error.log').read_text(errors='replace')
check('pcre' not in err.lower(), 'nginx\'s maps failed on a request: %s' % err[-300:])
finish()
