#!/usr/bin/env python3
"""The desktop app and the Stream Deck never from the internet (5.59.3).

  * the relay (web/index.php) turns api=notifier and api=deck away with 403 unless the caller
    and every address in X-Forwarded-For, X-Real-IP and Forwarded is a home one: private,
    loopback, link-local, CGNAT (100.64/10, a VPN such as Tailscale) or IPv6 unique-local;
  * a home caller is let through to the daemon as before (here there is no daemon, so it
    is told the daemon is not responding - which is past the lock);
  * an address that does not parse counts as not home;
  * the front server's file passes /tap and nothing else, and drops the query.

    python3 test/review5593_home_only.py < /dev/null

Port 20295. Every address here is made up (documentation ranges for the internet).
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-homeonly-'))
PHP_PORT = 20295
bad = []
LOCKED = 'only from the home network'


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


prep = W / 'prep.php'
prep.write_text("""<?php
$_GET = ['api' => getenv('T_API'), 'do' => getenv('T_DO')];
$_SERVER['REMOTE_ADDR'] = getenv('T_ADDR');
$_SERVER['REQUEST_METHOD'] = 'GET';
foreach (['HTTP_X_FORWARDED_FOR' => 'T_XFF', 'HTTP_X_REAL_IP' => 'T_XRI', 'HTTP_FORWARDED' => 'T_FWD'] as $k => $e) {
    if (getenv($e) !== false) { $_SERVER[$k] = getenv($e); }
}
""")


def relay(api, addr, do='hello', xff=None, xri=None, fwd=None):
    env = dict(os.environ, T_API=api, T_ADDR=addr, T_DO=do)
    for k, v in (('T_XFF', xff), ('T_XRI', xri), ('T_FWD', fwd)):
        if v is not None:
            env[k] = v
    out = subprocess.run(['php', '-d', 'auto_prepend_file=' + str(prep), str(HERE / 'web' / 'index.php')],
                         env=env, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
                         cwd=str(W)).stdout
    try:
        return json.loads(out[out.find('{'):])
    except ValueError:
        return {'raw': out[:200]}


try:
    print('the caller itself')
    for api, do in (('notifier', 'hello'), ('notifier', 'wait'), ('notifier', 'download'),
                    ('deck', 'pair'), ('deck', 'wait'), ('deck', 'do')):
        for addr in ('203.0.113.9', '198.51.100.7', '2001:db8::1', '8.8.4.4', 'garbage', ''):
            out = relay(api, addr, do)
            check(LOCKED in str(out.get('error')), '%s/%s from %r was let through: %r' % (api, do, addr, out))
        for addr in ('192.168.40.10', '10.1.2.3', '172.20.0.5', '127.0.0.1', '169.254.3.4', '100.100.1.1',
                     '::1', 'fd12:3456::5', 'fe80::1', '::ffff:192.168.1.9'):
            out = relay(api, addr, do)
            check(LOCKED not in str(out.get('error')), '%s/%s from home %r was turned away: %r' % (api, do, addr, out))
    for addr in ('172.32.0.1', '100.128.0.1', '11.0.0.1', '192.169.0.1', 'fec0::1'):
        out = relay('notifier', addr)
        check(LOCKED in str(out.get('error')), 'the edge of a home range %r was let through' % addr)

    print('what a proxy says it passed along')
    for kw in ({'xff': '192.168.1.5, 203.0.113.9'}, {'xff': '203.0.113.9'}, {'xri': '198.51.100.1'},
               {'fwd': 'for=192.0.2.60;proto=https'}, {'fwd': 'for="[2001:db8::7]:4711"'},
               {'xff': '10.0.0.3,  nonsense'}):
        out = relay('deck', '192.168.40.233', 'hello', **kw)
        check(LOCKED in str(out.get('error')), 'forwarded %r was let through: %r' % (kw, out))
    for kw in ({'xff': '192.168.1.5'}, {'xff': '192.168.1.5, 10.0.0.1'}, {'xri': '10.9.8.7'},
               {'fwd': 'for=192.168.1.20;proto=https'}, {'fwd': 'for="[fd00::4]:80"'}):
        out = relay('deck', '192.168.40.233', 'hello', **kw)
        check(LOCKED not in str(out.get('error')), 'forwarded home %r was turned away: %r' % (kw, out))

    print('the rest of the API is not touched')
    out = relay('status', '203.0.113.9')
    check(LOCKED not in str(out.get('error')), 'another api was locked by this: %r' % out)

    print('over real HTTP')
    (W / 'web').mkdir()
    php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, str(HERE / 'web' / 'index.php')],
                           cwd=str(HERE / 'web'), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           stdin=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)

        def get(path, headers):
            req = urllib.request.Request('http://127.0.0.1:%d%s' % (PHP_PORT, path), headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return r.status, r.read().decode()
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode()

        code, body = get('/?api=notifier&do=hello', {'X-Forwarded-For': '203.0.113.9',
                                                     'X-Zigmon-Notifier': 'zmn_' + 'f' * 40})
        check(code == 403 and LOCKED in body, 'the notifier from the internet is not 403: %s %s' % (code, body[:120]))
        code, body = get('/?api=deck&do=hello', {'X-Forwarded-For': '198.51.100.7'})
        check(code == 403 and LOCKED in body, 'the deck from the internet is not 403: %s %s' % (code, body[:120]))
        code, body = get('/?api=deck&do=hello', {})
        check(LOCKED not in body, 'the deck from this machine was turned away: %s %s' % (code, body[:120]))
    finally:
        php.terminate()
        php.wait(10)

    print('the front server passes /tap and nothing else')
    front = (HERE / 'deploy' / 'nginx-tap-front.conf').read_text()
    lines = [ln.split('#', 1)[0].strip() for ln in front.splitlines()]
    locs = [ln for ln in lines if ln.startswith('location')]
    check(sorted(locs) == sorted(['location / { return 404; }', 'location = /tap {']),
          'the front server has other locations: %r' % locs)
    passes = [ln for ln in lines if ln.startswith('proxy_pass')]
    check(len(passes) == 1 and passes[0].rstrip(';').endswith('/tap'), 'the front passes elsewhere: %r' % passes)
    check('set $args "";' in lines, 'the front does not drop the query')
    for word in ('notifier', 'deck'):
        check(not any(word in ln for ln in lines if ln), 'the front file names %s outside a comment' % word)
finally:
    pass

print('FAILED: %d' % len(bad) if bad else 'all good')
sys.exit(1 if bad else 0)
