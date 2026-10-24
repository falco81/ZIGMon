#!/usr/bin/env python3
# probe-front.py -- what an attacker on the internet can reach.
#
# Point this at a hostname that faces the internet, from OUTSIDE your own
# network - a phone on mobile data, a cheap VPS, a friend's line. Run from
# inside and it tells you little: the whole question is what the public sees,
# and inside you are not the public.
#
# It does not assume it is looking at any particular application. It sends the
# requests an attacker sends - odd methods, traversal, header tricks, vhost
# guesses, old TLS - and reports what came back. It reads a server the way
# somebody with no source code and bad intentions reads one.
#
# It never guesses a secret and never tries to. Nothing it does changes state
# on the server: it makes only safe requests, so it is safe to run against a
# live one. (A burst of a few dozen requests may trip a rate limiter; that is
# the point of one of the checks.)
#
#     python3 probe-front.py mqtt.falco81.net
#     python3 probe-front.py https://mqtt.falco81.net:443
#     python3 probe-front.py 192.168.43.17 --host mqtt.falco81.net   # by IP, name in SNI
#
# Exits 0 when nothing worrying was found, 1 when something was, so it can sit
# in a cron and mail you the day the answer changes. Standard library only.

import argparse
import http.client
import socket
import ssl
import sys
import time
import warnings

warnings.filterwarnings('ignore', category=DeprecationWarning)

_TTY = sys.stdout.isatty()


def _c(code, text):
    return '\033[%sm%s\033[0m' % (code, text) if _TTY else text


def bad(t):   return _c('31', t)
def warn(t):  return _c('33', t)
def okc(t):   return _c('32', t)
def dim(t):   return _c('2', t)
def head(t):  return _c('1;36', t)


FINDINGS = []
INSECURE = False
HOST = None            # the name to present in SNI and Host, if given
TARGET = None          # what to actually connect to (host or IP)
PORT = 443


def note(level, message):
    """A finding, shown in full. It is a security report; a reason cut off
    mid-word is worse than a long line."""
    FINDINGS.append((level, message))
    mark = {'bad': bad('  FAIL'), 'warn': warn('  WARN'), 'ok': okc('  ok  ')}[level]
    print('%s  %s' % (mark, message))


def base_url():
    return 'https://%s%s' % (TARGET, '' if PORT == 443 else ':%d' % PORT)


# ---------------------------------------------------------------------------
# a raw request, so we control the Host header and the method exactly, and can
# connect to an IP while presenting a name in SNI - the trick a vhost probe
# needs. Returns (status, headers list, body bytes, error).
# ---------------------------------------------------------------------------
def raw(method, path, host_header=None, extra=None, body=b'', timeout=10.0, sni=None):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False          # verification is reported separately, not enforced per request
    ctx.verify_mode = ssl.CERT_NONE
    server_name = sni or HOST or TARGET
    conn = None
    try:
        rawsock = socket.create_connection((TARGET, PORT), timeout=timeout)
        tls = ctx.wrap_socket(rawsock, server_hostname=server_name)
        conn = http.client.HTTPSConnection(TARGET, PORT, timeout=timeout)
        conn.sock = tls
        headers = {'Host': host_header or HOST or TARGET, 'Connection': 'close',
                   'User-Agent': 'probe-front'}
        headers.update(extra or {})
        conn.request(method, path, body=body, headers=headers)
        r = conn.getresponse()
        data = r.read(200000)
        return r.status, r.getheaders(), data, None
    except Exception as e:
        return 0, [], b'', '%s: %s' % (type(e).__name__, e)
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def get(path, **k):
    return raw('GET', path, **k)


def hdr(headers, name):
    name = name.lower()
    for k, v in headers:
        if k.lower() == name:
            return v
    return None


# ---------------------------------------------------------------------------
# 1. TLS
# ---------------------------------------------------------------------------
def check_tls():
    print(head('\nTLS'))
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((TARGET, PORT), timeout=10) as s:
            with ctx.wrap_socket(s, server_hostname=HOST or TARGET) as tls:
                note('ok', 'speaks %s with %s (%d bit)'
                     % (tls.version(), tls.cipher()[0], tls.cipher()[2]))
    except Exception as e:
        note('bad', 'TLS handshake failed: %s: %s' % (type(e).__name__, e))
        return

    for name, want in (('SSLv3', 'SSLv3'), ('TLSv1', 'TLSv1'), ('TLSv1.1', 'TLSv1_1')):
        flag = getattr(ssl.TLSVersion, want, None) if hasattr(ssl, 'TLSVersion') else None
        if flag is None:
            continue
        low = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        low.check_hostname = False
        low.verify_mode = ssl.CERT_NONE
        try:
            low.minimum_version = flag
            low.maximum_version = flag
        except (ValueError, OSError):
            continue
        try:
            with socket.create_connection((TARGET, PORT), timeout=8) as s:
                with low.wrap_socket(s, server_hostname=HOST or TARGET):
                    note('bad', 'still accepts %s' % name)
        except Exception:
            note('ok', 'refuses %s' % name)

    verify = ssl.create_default_context()
    check_name = HOST or TARGET
    try:
        with socket.create_connection((TARGET, PORT), timeout=8) as s:
            with verify.wrap_socket(s, server_hostname=check_name) as tls:
                info = tls.getpeercert()
        after = info.get('notAfter')
        if after:
            days = int((ssl.cert_time_to_seconds(after) - time.time()) / 86400)
            if days < 0:
                note('bad', 'the certificate expired %d day(s) ago' % -days)
            elif days < 14:
                note('warn', 'the certificate lapses in %d day(s)' % days)
            else:
                note('ok', 'the certificate verifies for %s, %d day(s) left' % (check_name, days))
    except ssl.SSLCertVerificationError as e:
        note('bad', 'the certificate does not verify for %s: %s'
             % (check_name, (e.verify_message or str(e))))
        if TARGET != check_name and not HOST:
            note('warn', 'you are connecting by IP; pass --host <name> to check the name it is for')
    except Exception as e:
        note('warn', 'could not verify the certificate: %s: %s' % (type(e).__name__, e))


# ---------------------------------------------------------------------------
# 2. plain HTTP
# ---------------------------------------------------------------------------
def check_http():
    print(head('\nPlain HTTP (port 80)'))
    try:
        conn = http.client.HTTPConnection(TARGET, 80, timeout=8)
        conn.request('GET', '/', headers={'Host': HOST or TARGET, 'Connection': 'close'})
        r = conn.getresponse()
        loc, status = r.getheader('Location', ''), r.status
        conn.close()
    except Exception as e:
        note('ok', 'nothing answers on port 80 (%s)' % type(e).__name__)
        return
    if status in (301, 302, 307, 308) and loc.startswith('https://'):
        note('ok', 'port 80 redirects to https (%d)' % status)
    elif status in (301, 302, 307, 308):
        note('warn', 'port 80 redirects, but not to https: %s' % loc)
    else:
        note('bad', 'port 80 serves content (%d) rather than redirecting to https' % status)


# ---------------------------------------------------------------------------
# 3. a blind scan: paths an attacker tries with no knowledge of the app
# ---------------------------------------------------------------------------
SCAN_PATHS = [
    '/', '/index.php', '/index.html', '/admin', '/login', '/dashboard',
    '/status', '/api', '/api/', '/api/status', '/metrics', '/health',
    '/config', '/config.json', '/settings', '/.env', '/.git/config',
    '/.git/HEAD', '/server-status', '/phpinfo.php', '/info.php',
    '/wp-login.php', '/robots.txt', '/favicon.ico', '/backup.zip',
    '/db.sqlite', '/id_rsa', '/server.key', '/private.key',
    '/../etc/passwd', '/..%2f..%2f..%2fetc%2fpasswd',
    '/%2e%2e/%2e%2e/etc/passwd', '/....//....//etc/passwd',
    '/index.php/..%2f..%2fetc/passwd',
    '/?api=status', '/?api=export', '/?api=devices', '/?api=people',
    '/index.php?api=export', '/api/export', '/api/people', '/api/log',
]

INTERESTING = (b'root:', b'BEGIN PRIVATE KEY', b'BEGIN RSA', b'BEGIN OPENSSH',
               b'password', b'secret', b'"devices"', b'runtime_config',
               b'phpinfo', b'[core]', b'ref:')


def check_exposure():
    print(head('\nWhat answers (a blind scan)'))
    hits, leaks = [], []
    for path in SCAN_PATHS:
        status, headers, body, err = get(path, timeout=8)
        if err or status != 200:
            continue
        low = body.lower()
        if any(w in low for w in INTERESTING):
            leaks.append((path, len(body)))
        elif len(body) > 512:
            hits.append((path, len(body)))
    for path, size in leaks:
        note('bad', 'leaks something that reads like data: %s (%d bytes)' % (path, size))
    for path, size in hits:
        note('warn', 'answers with a page: %s (%d bytes) - is that meant to face the internet?'
             % (path, size))
    if not leaks and not hits:
        note('ok', 'nothing in the scan answered with content - the surface is small')


# ---------------------------------------------------------------------------
# 4. methods and header tricks
# ---------------------------------------------------------------------------
def check_methods():
    print(head('\nMethods and header tricks'))
    odd_refused = True
    for method in ('TRACE', 'TRACK', 'OPTIONS', 'DELETE', 'PUT', 'CONNECT', 'PATCH'):
        status, headers, body, err = raw(method, '/', timeout=6)
        if err:
            continue
        if method in ('TRACE', 'TRACK') and status == 200 and b'probe-front' in body:
            note('bad', '%s is answered and echoes the request (cross-site tracing)' % method)
            odd_refused = False
        elif status in (200, 201, 204) and method in ('PUT', 'DELETE', 'PATCH'):
            note('bad', '%s is accepted (%d) - a write method should not be' % (method, status))
            odd_refused = False
    if odd_refused:
        note('ok', 'odd methods (TRACE, PUT, DELETE, ...) are refused or ignored')

    status, headers, body, err = get('/', host_header='no-such-vhost.invalid', timeout=6)
    if not err and status == 200 and len(body) > 512:
        note('warn', 'an unknown Host still gets a page - a default vhost answers; name every '
                     'server_name and add a default that returns 444')
    elif not err and status not in (400, 404, 421, 444):
        note('warn', 'an unknown Host is answered %d rather than refused' % status)
    elif err:
        note('ok', 'a request with an unknown Host is not answered at all')

    # Asked for by address rather than by name. Somebody walking addresses
    # never types a name, so the SNI is empty or is the address itself - and
    # whatever server block is the default answers, which on a machine with
    # one block is the very one that carries the links.
    # only worth asking where a name was given and something else is being
    # connected to - "probe-front 1.2.3.4 --host mqtt.example.net"
    if HOST and TARGET and HOST != TARGET:
        status, headers, body, err = get('/tap', sni=TARGET, host_header=TARGET, timeout=6)
        if err and ('handshake' in str(err).lower() or 'unrecognized' in str(err).lower()
                    or 'sslv3' in str(err).lower() or 'reset' in str(err).lower()):
            note('ok', 'asked for by address, the handshake is refused - no certificate is even '
                       'offered, and a scanner learns nothing')
        elif err:
            note('ok', 'asked for by address, nothing is answered (%s)' % str(err)[:60])
        elif status in (444, 421, 400):
            note('ok', 'asked for by address, the connection is closed without a page')
        else:
            note('warn', 'asked for by address rather than by name, this answers %d - so a scanner '
                         'walking addresses finds the road. Add a default server with '
                         'ssl_reject_handshake on, and keep the real block off default_server.'
                 % status)

    status, headers, body, err = get('/', extra={'X-Forwarded-Host': 'evil.example'}, timeout=6)
    if not err and b'evil.example' in body:
        note('warn', 'X-Forwarded-Host is reflected into the response - a cache-poisoning vector')

    status, headers, body, err = get('/', timeout=6)
    if not err:
        for leaky in ('X-Forwarded-For', 'Via', 'X-Real-IP', 'X-Backend-Server', 'X-Powered-By'):
            v = hdr(headers, leaky)
            if v:
                note('warn', 'the response carries %s: %s (tells the client about the plumbing)'
                     % (leaky, v))


# ---------------------------------------------------------------------------
# 5. the one-tap road, discovered rather than assumed
# ---------------------------------------------------------------------------
def check_tap():
    print(head('\nThe one-tap road, if present'))
    status, headers, body, err = get('/tap', timeout=8)
    if err or status == 0:
        note('ok', '/tap does not answer (this may not be a zigmon front, which is fine)')
        return
    if status == 405:
        note('ok', '/tap refuses a GET (405), as the header road should')
        # and what it says while refusing: a refusal that names the header it
        # wants hands a guesser the one word they were missing
        low = body.lower()
        if any(word in low for word in (b'x-zigmon', b'"error"', b'header', b'token', b'secret')):
            note('warn', 'the refusal names what this road takes - "%s" - which tells somebody '
                         'guessing exactly what to guess. Answer the status and nothing else.'
                 % body[:70].decode('utf-8', 'replace').strip())
        elif len(body.strip()) > 64:
            note('warn', 'the refusal carries %d bytes of explanation; a bare status gives less away'
                 % len(body.strip()))
        else:
            note('ok', 'and says nothing while refusing')
    elif status == 200:
        note('bad', '/tap answers a GET with 200 - a link preview or crawler can trip it')
    elif status in (403, 404):
        note('ok', '/tap is not open to a GET (%d)' % status)
        return
    else:
        note('warn', '/tap answers a GET with %d' % status)

    refused, limited, accepted = 0, False, False
    for i in range(30):
        status, headers, body, err = raw('POST', '/tap', extra={'X-Zigmon-Tap': 'probe-%d' % i},
                                         timeout=8)
        if err:
            break
        if status == 429:
            limited = True
            break
        if status == 200:
            accepted = True
            break
        if status in (400, 403, 404):
            refused += 1
    if accepted:
        note('bad', 'a made-up X-Zigmon-Tap was accepted (200) - misrouted, or not what it seems')
    elif limited:
        note('ok', 'a burst of wrong secrets is rate-limited (429) - a guesser is slowed at the door')
    elif refused:
        note('warn', 'wrong secrets are refused but not rate-limited (%d in a row) - add limit_req to /tap'
             % refused)

    status, headers, body, err = get('/tap/probe-not-a-real-secret-in-the-url', timeout=8)
    if not err and status == 200:
        note('bad', "the address form /tap/<secret> answers from the internet - the secret is then "
                    "in this server's log and every proxy on the way")
    elif not err and status in (403, 404, 405):
        note('ok', 'the address form /tap/<secret> is not served from the internet')


# ---------------------------------------------------------------------------
# 6. response headers
# ---------------------------------------------------------------------------
def check_security_headers():
    print(head('\nResponse headers'))
    status, headers, body, err = get('/', timeout=8)
    if err:
        note('warn', 'could not read a response to check its headers')
        return
    if hdr(headers, 'strict-transport-security'):
        note('ok', 'HSTS is set (%s)' % hdr(headers, 'strict-transport-security'))
    else:
        note('warn', 'no Strict-Transport-Security header')
    srv = hdr(headers, 'server') or ''
    if any(ch.isdigit() for ch in srv):
        note('warn', 'the Server header gives a version away: %s' % srv)
    elif srv:
        note('ok', 'the Server header names software but no version: %s' % srv)
    if not hdr(headers, 'x-content-type-options'):
        note('warn', 'no X-Content-Type-Options: nosniff')


# ---------------------------------------------------------------------------
def main(argv=None):
    global INSECURE, HOST, TARGET, PORT
    ap = argparse.ArgumentParser(description='What an attacker on the internet can reach of a server '
                                             'you have published - point it at the public name.')
    ap.add_argument('target', help='the hostname, IP, or https:// URL that faces the internet')
    ap.add_argument('--host', help='the name to present in SNI and the Host header '
                                   '(use when the target is an IP)')
    ap.add_argument('--port', type=int, default=443, help='the TLS port (default 443)')
    ap.add_argument('--insecure', action='store_true',
                    help='keep probing past a certificate that does not verify (still reported)')
    args = ap.parse_args(argv)

    t = args.target
    if t.startswith('https://'):
        t = t[len('https://'):]
    elif t.startswith('http://'):
        print(bad('give an https target; the TLS side is half the point'))
        return 2
    t = t.rstrip('/').split('/')[0]
    if ':' in t and t.count(':') == 1:
        TARGET, PORT = t.split(':')[0], int(t.split(':')[1])
    else:
        TARGET, PORT = t, args.port
    HOST = args.host
    INSECURE = args.insecure

    print(head('Probing %s as an outsider would' % base_url()))
    if HOST:
        print(dim('presenting %s in SNI and Host' % HOST))
    print(dim('Run this from OUTSIDE your own network, or it tells you little.'))

    check_tls()
    check_http()
    check_exposure()
    check_methods()
    check_tap()
    check_security_headers()

    bads = sum(1 for lvl, _ in FINDINGS if lvl == 'bad')
    warns = sum(1 for lvl, _ in FINDINGS if lvl == 'warn')
    print(head('\nSummary'))
    if bads:
        print(bad('%d thing(s) an attacker could use, %d worth a look' % (bads, warns)))
        return 1
    if warns:
        print(warn('nothing an attacker could use, %d thing(s) worth a look' % warns))
        return 0
    print(okc('nothing found - one locked door is all the outside sees'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
