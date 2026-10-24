#!/usr/bin/env python3
"""The dashboard's own nginx file, the real index.php and php-fpm, and a fake
daemon behind them that writes down every request it is handed: what an
attacker on the internet, or a page on another site, can make reach the
daemon - checked by sending it.

    python3 test/edge.py

Needs nginx and php-fpm installed (skipped, and says so, where they are not).
Nothing of the machine's own nginx or php-fpm is used: both run from a
scratch directory on ports of their own, as the user running the check.
"""
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import http.client
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
NGINX = shutil.which('nginx') or '/usr/sbin/nginx'
FPM = next((p for p in (shutil.which('php-fpm'), shutil.which('php-fpm8.3'), '/usr/sbin/php-fpm8.3',
                        '/usr/sbin/php-fpm') if p and os.path.exists(p)), None)
if not os.path.exists(NGINX) or not FPM:
    print('nginx or php-fpm is not installed here: the edge was not checked')
    sys.exit(0)

DAEMON_PORT, HTTPS_PORT = 19948, 18443
work = Path(tempfile.mkdtemp(prefix='zigmon-edge-'))
(work / 'logs').mkdir()

# -- a fake daemon that writes down what reaches it ---------------------------
SEEN = []


def serve(conn):
    conn.settimeout(3)
    data = b''
    try:
        while b'\r\n\r\n' not in data:
            got = conn.recv(65536)
            if not got:
                break
            data += got
        head, _, body = data.partition(b'\r\n\r\n')
        m = re.search(rb'Content-Length: *(\d+)', head, re.I)
        want = int(m.group(1)) if m else 0
        while len(body) < want:
            got = conn.recv(65536)
            if not got:
                break
            body += got
        line = head.split(b'\r\n', 1)[0].decode('latin-1')
        headers = head.decode('latin-1')
        SEEN.append((line, headers, body.decode('utf-8', 'replace')))
    except Exception:
        pass
    answer = b'{"ok": true, "message": "fake"}'
    try:
        conn.sendall(b'HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n'
                     % len(answer) + answer)
    finally:
        conn.close()


lsock = socket.socket()
lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
lsock.bind(('127.0.0.1', DAEMON_PORT))
lsock.listen(64)
threading.Thread(target=lambda: [threading.Thread(target=serve, args=(lsock.accept()[0],),
                                                  daemon=True).start() for _ in iter(int, 1)],
                 daemon=True).start()

# -- the page, pointed at the fake daemon --------------------------------------
web = work / 'web'
shutil.copytree(HERE / 'web', web)
token = work / 'api-token'
token.write_text('edge-check-token\n')
api = (web / 'zigmon-api.php').read_text()
api = re.sub(r"const ZIGMON_PORT\s*=\s*\d+;", 'const ZIGMON_PORT  = %d;' % DAEMON_PORT, api)
api = re.sub(r"const ZIGMON_TOKEN\s*=\s*'[^']*';", "const ZIGMON_TOKEN = '%s';" % token, api)
(web / 'zigmon-api.php').write_text(api)

# -- php-fpm, on a socket of its own --------------------------------------------
sock = work / 'fpm.sock'
user = os.environ.get('USER') or 'root'
(work / 'fpm.conf').write_text('''[global]
error_log = %(w)s/logs/fpm.log
daemonize = no
[edge]
listen = %(s)s
pm = static
pm.max_children = 6
clear_env = no
''' % {'w': work, 's': sock})
fpm = subprocess.Popen([FPM, '-R', '-n', '-y', str(work / 'fpm.conf')],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# -- nginx, from the file that ships ----------------------------------------------
subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                '-subj', '/CN=mqtt.falco81.net', '-keyout', str(work / 'server.key'),
                '-out', str(work / 'server.pem')], capture_output=True, check=True)
shutil.copy(work / 'server.pem', work / 'server.ca')
conf = (HERE / 'deploy' / 'nginx-zigmon.conf').read_text()
for old, new in (('/etc/nginx/certs/', str(work) + '/'), ('/var/www/zigmon', str(web)),
                 ('unix:/run/php-fpm/www.sock', 'unix:' + str(sock)),
                 ('/var/log/nginx/', str(work / 'logs') + '/'),
                 ('listen      443 ssl http2;', 'listen      127.0.0.1:%d ssl;' % HTTPS_PORT),
                 ('listen      [::]:443 ssl http2;', ''), ('listen      80;', 'listen 127.0.0.1:18080;'),
                 ('listen      [::]:80;', ''), ('ssl_stapling              on;', ''),
                 ('ssl_stapling_verify       on;', '')):
    conf = conf.replace(old, new)
conf = conf.replace('include        fastcgi_params;', 'include        /etc/nginx/fastcgi_params;')
(work / 'zigmon.conf').write_text(conf)
(work / 'nginx.conf').write_text(('user root;\n' if os.geteuid() == 0 else '') + '''daemon off;
pid %(w)s/nginx.pid;
error_log %(w)s/logs/nginx-main.log;
events { worker_connections 256; }
http {
    include /etc/nginx/mime.types;
    client_body_temp_path %(w)s/body;
    fastcgi_temp_path %(w)s/fcgi;
    proxy_temp_path %(w)s/proxy;
    uwsgi_temp_path %(w)s/uwsgi;
    scgi_temp_path %(w)s/scgi;
    include %(w)s/zigmon.conf;
}
''' % {'w': work})
test = subprocess.run([NGINX, '-t', '-p', str(work), '-c', str(work / 'nginx.conf')],
                      capture_output=True, text=True)
if test.returncode != 0:
    print('nginx refuses the dashboard\'s file:\n' + test.stderr)
    fpm.kill()
    sys.exit(1)
ngx = subprocess.Popen([NGINX, '-p', str(work), '-c', str(work / 'nginx.conf')],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(100):
    if sock.exists():
        try:
            socket.create_connection(('127.0.0.1', HTTPS_PORT), 0.2).close()
            break
        except OSError:
            pass
    time.sleep(0.05)

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
bad = []


def ask(method, path, body=None, headers=None):
    """A request to the dashboard's nginx; the daemon paths it caused."""
    SEEN[:] = []
    c = http.client.HTTPSConnection('127.0.0.1', HTTPS_PORT, timeout=10, context=CTX)
    h = {'Host': 'mqtt.falco81.net'}
    h.update(headers or {})
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    text = r.read().decode('utf-8', 'replace')
    c.close()
    time.sleep(0.05)
    return r.status, text, [line for line, _h, _b in SEEN]


def check(ok, what):
    if not ok:
        bad.append(what)


try:
    # -- the one-tap road cannot be turned into any other road ---------------
    # nginx hands /tap to PHP as api=tap followed by the caller's own query,
    # and PHP kept the LAST api= - so one POST to /tap from the internet
    # reached the whole of the API: the house's state, unlocking, a socket.
    for query, daemon_path in (('?api=status', '/api/status'),
                               ('?api=plug-switch', '/api/plug/switch'),
                               ('?api=unlock', '/api/unlock'),
                               ('?api=permit-join', '/api/permit_join'),
                               ('?api=tap&api=config-save', '/api/config')):
        status, text, hit = ask('POST', '/tap' + query, body='{"name":"Boiler","on":true,"pin":"1234"}',
                                headers={'Content-Type': 'text/plain', 'X-Zigmon-Tap': 'abcdefgh1234'})
        check(not any(daemon_path in h for h in hit) and all('/api/tap' in h for h in hit),
              'POST /tap%s reached %r' % (query, hit))
    status, text, hit = ask('POST', '/tap', body='{}', headers={'Content-Type': 'application/json',
                                                                 'X-Zigmon-Tap': 'abcdefgh1234'})
    check(hit == ['POST /api/tap HTTP/1.0'] or (len(hit) == 1 and hit[0].startswith('POST /api/tap')),
          'an ordinary press of the header road did not reach the daemon as one: %r' % hit)
    # ...nor the link road, nor the SMS gateway's own
    status, text, hit = ask('GET', '/tap/abcdefgh1234?api=status')
    check(hit and all(h.startswith('GET /api/tap/abcdefgh1234') for h in hit),
          'GET /tap/<link>?api=status reached %r' % hit)
    status, text, hit = ask('GET', '/tap/abcdefgh1234?ask')
    check(hit and hit[0].startswith('GET /api/tap/abcdefgh1234?ask'),
          'a link asking how things stand lost its ?ask on the way: %r' % hit)
    status, text, hit = ask('POST', '/api/sms/incoming?api=status&word=x',
                            body='{"number":"+420777000000","text":"hi"}',
                            headers={'Content-Type': 'application/json'})
    check(hit and all(h.startswith('POST /api/sms/incoming') for h in hit),
          'the SMS road with ?api=status reached %r' % hit)
    # ...and a path written to look like something else is still the tap road
    status, text, hit = ask('POST', '/x/../tap?api=status', body='{}',
                            headers={'X-Zigmon-Tap': 'abcdefgh1234'})
    check(not any('/api/status' in h for h in hit), 'POST /x/../tap?api=status reached %r' % hit)
    print('the one-tap road, the link road and the SMS road reach nothing but themselves')

    # -- a page on another site cannot drive the dashboard ------------------
    for headers in ({'Origin': 'https://evil.example', 'Content-Type': 'text/plain'},
                    {'Sec-Fetch-Site': 'cross-site', 'Content-Type': 'text/plain'},
                    {'Origin': 'null', 'Content-Type': 'text/plain'},
                    {'Origin': 'https://red.falco81.net', 'Sec-Fetch-Site': 'same-site'}):
        status, text, hit = ask('POST', '/index.php?api=plug-switch',
                                body='{"name":"Boiler","on":false,"pin":"1234"}', headers=headers)
        check(status == 403 and not hit, 'a POST from another site (%r) was passed on: %s %r'
              % (headers, status, hit))
    # ...while the page itself, and a tool that says nothing about where it is, are not refused
    status, text, hit = ask('POST', '/index.php?api=plug-switch',
                            body='{"name":"Boiler","on":false,"pin":"1234"}',
                            headers={'Origin': 'https://mqtt.falco81.net', 'Sec-Fetch-Site': 'same-origin',
                                     'Content-Type': 'application/json'})
    check(hit and hit[0].startswith('POST /api/plug/switch'),
          'the dashboard\'s own POST was refused: %s %r' % (status, hit))
    status, text, hit = ask('POST', '/index.php?api=plug-switch', body='{"name":"Boiler","on":false}',
                            headers={'Content-Type': 'application/json'})
    check(hit and hit[0].startswith('POST /api/plug/switch'),
          'a POST from a tool with no Origin was refused: %s %r' % (status, hit))
    print('a page on another site cannot POST to the dashboard; the dashboard and a tool still can')

    # -- what the relay says the caller was ----------------------------------
    # The header was cut to 120 characters BEFORE anything else, which cut off
    # its right-hand end - the one address in it the server in front wrote.
    status, text, hit = ask('GET', '/index.php?api=status',
                            headers={'X-Forwarded-For': ','.join(['1'] * 60) + ',127.0.0.1, 203.0.113.9'})
    via = [h for _l, h, _b in SEEN if 'X-Zigmon-Via' in h]
    said = re.search(r'X-Zigmon-Via: ([^\r\n]*)', via[0]).group(1) if via else ''
    check(said.rstrip(', ').endswith('203.0.113.9'),
          'a long X-Forwarded-For lost the address the server in front wrote: %r' % said[-60:])
    print('a long X-Forwarded-For keeps its last address, the one the server in front wrote')

    # -- the sign-in does not travel in the address of every poll -----------
    # Since 5.19 it is a cookie the relay set (HttpOnly: no script reads it)
    # and passes on in a header; one the page's own script tried to send in a
    # header, or in an address, is not passed on at all.
    status, text, hit = ask('GET', '/index.php?api=status',
                            headers={'Cookie': 'zigmon_session=sess-abcdefghijklmnopqrst'})
    sent = [h for _l, h, _b in SEEN]
    check(sent and 'X-Zigmon-Session: sess-abcdefghijklmnopqrst' in sent[0],
          'a sign-in kept in its cookie did not reach the daemon')
    status, text, hit = ask('GET', '/index.php?api=status&session=sess-fromtheaddress12345',
                            headers={'X-Zigmon-Session': 'sess-fromthescript123456'})
    sent = [h for _l, h, _b in SEEN]
    check(sent and 'X-Zigmon-Session' not in sent[0],
          'a session the page sent in a header or an address was passed on: %r' % sent[:1])

    # -- the SMS road carries the modem's headers, not anybody's login ---------
    # The headers that came with a text are carried to the daemon to be written
    # down; a cookie or an Authorization header among them was written down
    # whole.
    status, text, hit = ask('POST', '/api/sms/incoming?secret=abc', body='number=1&text=hi',
                            headers={'Cookie': 'zsess=CookieValue123456', 'Authorization': 'Basic QXV0aFZhbHVl',
                                     'Content-Type': 'application/x-www-form-urlencoded'})
    _body = ''.join(b for _l, _h, b in SEEN)
    check(hit and 'CookieValue123456' not in _body and 'QXV0aFZhbHVl' not in _body,
          'the SMS road carried a cookie or an Authorization header to the daemon whole (%s, %r)' % (status, hit))
    print('the SMS road carries the modem\'s headers to the daemon, and only whether a login came with them')

    # -- ...nor in the address of a download -----------------------------------
    # A private key or a backup of the whole house was fetched by a link with
    # the unlock token in its address: written whole into this nginx's access
    # log, and the token is the PIN for as long as it lasts.
    for _what in ('wifi-sshkey-download', 'mikrotik-key-download', 'db-backup-download&file=zigmon-db-20261021.sqlite'):
        status, text, hit = ask('GET', '/index.php?api=' + _what,
                                headers={'Cookie': 'zigmon_session=sessDownloadabcdefghij'})
        sent = [h for _l, h, _b in SEEN]
        check(status == 200 and hit and 'sessDownload' not in hit[0]
              and 'X-Zigmon-Session: sessDownloadabcdefghij' in sent[0],
              'a download with its session in a header: %s, daemon asked %r' % (status, hit))
    _logged = ''.join(x.read_text(errors='replace') for x in (work / 'logs').glob('*.log'))
    check('sessDownload' not in _logged, 'the unlock token of a download is in the web server\'s log')
    _page = (HERE / 'web' / 'index.php').read_text()
    check(not re.search(r"session=' \+ encodeURIComponent", _page),
          'the page still puts the unlock token in the address of a link')
    print('a download carries its sign-in in a cookie and a header, and no log has it')
finally:
    ngx.terminate()
    fpm.terminate()
    try:
        ngx.wait(5)
        fpm.wait(5)
    except Exception:
        pass
    if not os.environ.get('EDGE_KEEP'):
        shutil.rmtree(work, ignore_errors=True)
    else:
        print('kept', work)

if bad:
    print('\nFAILED:')
    for b in bad:
        print('  - ' + b)
    sys.exit(1)
print('the edge holds: nginx, PHP and the relay, checked by sending them requests')
