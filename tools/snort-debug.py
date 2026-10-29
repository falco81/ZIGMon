#!/usr/bin/env python3
"""Why snort.org will not hand the Talos list to this machine.

Run it on the server, as root, and send back everything it prints:

    cd zigmon-5.29.3          # the folder the package was unpacked into
    sudo python3 tools/snort-debug.py            # two requests, no more
    sudo python3 tools/snort-debug.py --accept   # also press Accept, as zigmon does

It asks snort.org the way zigmon does - the same program name, the same
steps - and prints what came back at each step: the status, the headers that
say who answered and why (Cloudflare's ray, Retry-After, the kind of block),
the start of any page it was given instead of the list, which address family
the connection used, and what zigmon itself has remembered about the list.

It never prints a cookie's value, a token or a session: only their names and
lengths. It waits between requests, and stops at the first "too many
requests", so running it does not make the wait longer.

Nothing here changes zigmon or its database; it only reads them.
"""
import argparse
import http.cookiejar
import json
import os
import re
import socket
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get('SNORT_BASE', 'https://www.snort.org').rstrip('/')   # only for testing this script
LIST = BASE + '/downloads/ip-block-list'
TERMS = BASE + '/downloads/ip-block-list/terms'
CONFIG = os.environ.get('ZIGMON_CONFIG', '/etc/zigmon/config.json')
PAUSE = 4.0            # seconds between requests: a person clicking, not a program
SAY_HEADERS = ('server', 'date', 'content-type', 'content-length', 'location', 'retry-after',
               'cf-ray', 'cf-mitigated', 'cf-cache-status', 'x-ratelimit-limit',
               'x-ratelimit-remaining', 'x-ratelimit-reset', 'x-amz-request-id', 'etag',
               'last-modified', 'cache-control', 'x-frame-options', 'vary')


def shown_url(where):
    """An address fit to print: no user, no password, no query string.

    This script's own header asks for everything it prints to be sent back,
    and an own-address setting may carry a key in its query - the daemon
    strips exactly that before showing the same setting (_feed_where). This
    one printed it whole.
    """
    where = str(where or '').strip()
    if not where:
        return '(none - snort.org itself)'
    if where.startswith('file://'):
        return where[7:]
    if not re.match(r'^https?://', where):
        return where.split('?')[0]
    try:
        bits = urllib.parse.urlsplit(where)
        host = bits.hostname or ''
        if bits.port:
            host += ':%d' % bits.port
        return '%s://%s%s%s' % (bits.scheme, host, bits.path or '/',
                                '?\u2026' if bits.query else '')
    except ValueError:
        return where.split('?')[0]


def line(text=''):
    print(text, flush=True)


def head(text):
    line()
    line('=' * 78)
    line(text)
    line('=' * 78)


def zigmon_version():
    for where in ('/usr/local/lib/zigmon/zigmon.py', os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                 '..', 'zigmon.py')):
        try:
            with open(where, errors='ignore') as fh:
                found = re.search(r"^__version__ = '([^']+)'", fh.read(20000), re.M)
            if found:
                return found.group(1), where
        except OSError:
            continue
    return '?', ''


def what_zigmon_remembers():
    """Only reads: the settings for the list and what was kept about it."""
    head('1. What zigmon has set and remembered')
    try:
        with open(CONFIG) as fh:
            cfg = json.load(fh)
    except (OSError, ValueError) as e:
        line('  could not read %s: %s' % (CONFIG, e))
        cfg = {}
    db = cfg.get('db_file') or '/var/lib/zigmon/history.db'
    line('  config            %s' % CONFIG)
    line('  database          %s' % db)
    try:
        con = sqlite3.connect('file:%s?mode=ro' % db, uri=True, timeout=5)
        meta = dict(con.execute("SELECT key, value FROM meta WHERE key LIKE 'feed%talos%' "
                                "OR key LIKE 'snort%' OR key IN ('feeds', 'feeds_every_h', "
                                "'feed_talos_accept', 'feed_talos_url')").fetchall())
        settings = {}
        raw = con.execute("SELECT value FROM meta WHERE key='config_overrides'").fetchone()
        if raw and raw[0]:
            try:
                settings = json.loads(raw[0])
            except ValueError:
                pass
        con.close()
    except sqlite3.Error as e:
        line('  could not read the database: %s' % e)
        meta, settings = {}, {}
    both = dict(cfg, **settings)
    line('  lists switched on %s' % (both.get('feeds') or '(the defaults)'))
    line('  every             %s h' % (both.get('feeds_every_h') or 24))
    line('  terms accepted    %s' % (both.get('feed_talos_accept') or 0))
    line('  own address       %s' % shown_url(both.get('feed_talos_url')))
    now = time.time()

    def when(value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return '(never)'
        if not v:
            return '(never)'
        return '%s  (%s)' % (time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(v)),
                             ('in %d min' % ((v - now) / 60)) if v > now else ('%d min ago' % ((now - v) / 60)))
    line('  last fetched      %s' % when(meta.get('feed_at_talos')))
    line('  asked to wait to  %s' % when(meta.get('feed_wait_talos')))
    line('  list etag         %s' % (meta.get('feed_etag_talos') or '(none)'))
    line('  list modified     %s' % (meta.get('feed_modified_talos') or '(none)'))
    try:
        err = json.loads(meta.get('feed_error_talos') or '{}') or {}
    except ValueError:
        err = {}
    line('  last error        %s' % (('%s  %s' % (when(err.get('at')), err.get('words'))) if err else '(none)'))
    try:
        kept = json.loads(meta.get('snort_cookies') or '[]') or []
    except ValueError:
        kept = []
    if kept:
        for c in kept:
            line('  kept cookie       %-28s domain %-18s %d chars, expires %s'
                 % (c.get('name'), c.get('domain'), len(str(c.get('value') or '')),
                    when(c.get('expires')) if c.get('expires') else 'with the session'))
    else:
        line('  kept cookies      (none - the next fetch agrees to the terms from the start)')
    try:
        asked = [float(t) for t in json.loads(meta.get('snort_asked') or '[]')]
    except (ValueError, TypeError):
        asked = []
    if asked:
        line('  requests sent     %d in the last hour, the latest %s'
             % (len([t for t in asked if now - t < 3600]), when(max(asked))))
    return meta


def where_we_come_from():
    head('2. This machine, as snort.org sees it')
    try:
        infos = socket.getaddrinfo('www.snort.org', 443, proto=socket.IPPROTO_TCP)
        v4 = sorted({i[4][0] for i in infos if i[0] == socket.AF_INET})
        v6 = sorted({i[4][0] for i in infos if i[0] == socket.AF_INET6})
        line('  www.snort.org     IPv4 %s' % (', '.join(v4) or '-'))
        line('                    IPv6 %s' % (', '.join(v6) or '-'))
    except OSError as e:
        line('  could not resolve www.snort.org: %s' % e)
    for family, name in ((socket.AF_INET, 'IPv4'), (socket.AF_INET6, 'IPv6')):
        try:
            s = socket.socket(family, socket.SOCK_STREAM)
            s.settimeout(8)
            target = [i for i in socket.getaddrinfo('www.snort.org', 443, family, socket.SOCK_STREAM)][0][4]
            s.connect(target)
            line('  leaves by %-7s  from %s' % (name, s.getsockname()[0]))
            s.close()
        except (OSError, IndexError) as e:
            line('  leaves by %-7s  no route (%s)' % (name, str(e)[:60]))
    # the public address, from a service that only echoes it
    for url in ('https://api.ipify.org', 'https://ifconfig.me/ip'):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'curl/8'}),
                                        timeout=8) as r:
                line('  public address    %s   (from %s)' % (r.read(100).decode().strip(), url.split('/')[2]))
                break
        except OSError:
            continue


def show(step, answer_or_error, took, text):
    code = getattr(answer_or_error, 'status', None) or getattr(answer_or_error, 'code', '?')
    hdrs = getattr(answer_or_error, 'headers', None)
    line('  -> HTTP %s   in %.2f s   final url %s'
         % (code, took, (getattr(answer_or_error, 'geturl', lambda: '')() or '')[:90]))
    if hdrs:
        for name in SAY_HEADERS:
            value = hdrs.get(name)
            if value:
                line('     %-22s %s' % (name, value[:120]))
        for value in hdrs.get_all('Set-Cookie') or []:
            name = value.split('=', 1)[0]
            attrs = '; '.join(a.strip() for a in value.split(';')[1:] if not a.strip().lower().startswith('path'))
            line('     set-cookie             %s  (%s)' % (name, attrs[:90]))
    body = text or ''
    if body:
        if '<html' in body[:3000].lower():
            title = re.search(r'<title>([^<]*)', body, re.I)
            h1 = re.search(r'<h1[^>]*>([^<]*)', body, re.I)
            cf = re.search(r'error code:?\s*(\d{3,4})|Error\s*(10\d\d)', body, re.I)
            line('     page title             %s' % ((title.group(1).strip() if title else '-')[:100]))
            if h1:
                line('     page heading           %s' % h1.group(1).strip()[:100])
            if cf:
                line('     cloudflare error       %s' % (cf.group(1) or cf.group(2)))
            forms = re.findall(r'<form\b[^>]*action="([^"]*)"', body, re.I)
            if forms:
                line('     forms post to          %s' % ', '.join(forms[:4]))
            words = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', re.sub(r'<(script|style)\b.*?</\1>', ' ', body,
                                                                         flags=re.S | re.I))).strip()
            line('     the page says          %s' % words[:400])
        else:
            rows = [r for r in body.splitlines() if r.strip() and not r.startswith('#')]
            line('     a list of %d line(s), first: %s' % (len(rows), ', '.join(rows[:3])))


def ask(web, step, url, data=None, referer='', extra=None):
    line()
    line('  %s' % step)
    line('  %s %s' % ('POST' if data is not None else 'GET ', url))
    req = urllib.request.Request(url, data=data)
    if referer:
        req.add_header('Referer', referer)
    if data is not None:
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        req.add_header('Origin', 'https://www.snort.org')
    for k, v in (extra or {}).items():
        req.add_header(k, v)
    started = time.time()
    try:
        with web.open(req, timeout=40) as answer:
            text = answer.read(4 * 1024 * 1024).decode('utf-8', 'replace')
            show(step, answer, time.time() - started, text)
            return answer.status, text, answer.geturl()
    except urllib.error.HTTPError as e:
        try:
            text = e.read(200000).decode('utf-8', 'replace')
        except Exception:
            text = ''
        show(step, e, time.time() - started, text)
        return e.code, text, url
    except (urllib.error.URLError, OSError, ssl.SSLError) as e:
        line('  -> no answer at all after %.2f s: %s' % (time.time() - started, e))
        return None, '', url


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--accept', action='store_true',
                        help='also press Accept on the terms page, as zigmon does (a few more requests)')
    parser.add_argument('--ipv4', action='store_true', help='leave by IPv4 only')
    parser.add_argument('--force', action='store_true',
                        help='ask even while snort.org has told this address to wait')
    args = parser.parse_args()

    version, where = zigmon_version()
    head('snort.org, asked the way zigmon %s asks it   (%s)' % (version, time.strftime('%Y-%m-%d %H:%M:%S %Z')))
    line('  python %s, openssl %s' % (sys.version.split()[0], ssl.OPENSSL_VERSION))
    meta = what_zigmon_remembers() or {}
    try:
        wait = float(meta.get('feed_wait_talos') or 0)
    except ValueError:
        wait = 0
    # The daemon allows itself four requests a minute, against snort.org's
    # five; this script makes up to four of its own and the daemon cannot see
    # them. Together they cross the line and earn the day-long block this
    # script exists to diagnose - so its own asking waits on the ledger the
    # daemon keeps, which it already reads and prints above.
    try:
        recent = [float(t) for t in json.loads(meta.get('snort_asked') or '[]')
                  if time.time() - float(t) < 60]
    except (ValueError, TypeError):
        recent = []
    if len(recent) >= 2 and not args.force:
        line()
        line('  NOT ASKING YET: zigmon itself sent %d request(s) to snort.org in the last minute,'
             % len(recent))
        line('  and snort.org counts five a minute from one address. This script would send up to')
        line('  four more. Wait a minute and run it again (or --force, if you really mean it).')
        return
    if wait > time.time() and not args.force:
        line()
        line('  NOT ASKING: snort.org told this address to wait until %s. Every request before'
             % time.strftime('%H:%M', time.localtime(wait)))
        line('  then is counted by it, and answered "too many requests" whatever it is. Run this again')
        line('  after that time, and before zigmon asks (or with --force, if you really mean it).')
        return
    where_we_come_from()

    if args.ipv4:
        real = socket.getaddrinfo
        socket.getaddrinfo = lambda *a, **k: [i for i in real(*a, **k) if i[0] == socket.AF_INET]

    jar = http.cookiejar.CookieJar()
    web = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    web.addheaders = [('User-Agent', 'zigmon/%s' % version), ('Accept', 'text/plain, text/html, */*')]

    head('3. The list, asked for as zigmon asks for it')
    code, text, _at = ask(web, 'step 1: the list itself', LIST)
    if code is None:
        line()
        line('  STOPPED: no answer at all - the machine cannot reach snort.org (a firewall, DNS or a')
        line('  proxy in the way). That is a different thing from being told to wait.')
        return
    if code == 429:
        line()
        line('  STOPPED: snort.org said "too many requests" to the very first request, before any')
        line('  terms or cookies came into it. Whatever it is counting, it is counting this address')
        line('  (or this program name) - not something zigmon is doing wrong in one fetch.')
        if 'exceeded' in (text or '') and 'minute' in (text or ''):
            line()
            line('  Its own words say which: more than five requests to the list inside one minute')
            line('  shuts the address out, and Retry-After says for how long. zigmon 4.85.0 and later')
            line('  send at most four in any minute and fetch at most once every ten minutes. If this')
            line('  keeps happening, something ELSE behind %s asks snort.org too - a router or'
                 % 'the same public address')
            line('  firewall with a Talos list, suricata-update, a cron job:')
            line('      grep -rIl "snort.org" /etc /var/spool/cron 2>/dev/null')
        return
    if code == 200 and '<html' not in text[:2000].lower():
        line()
        line('  THE LIST CAME STRAIGHT BACK: nothing to accept, nothing refused.')
        return
    time.sleep(PAUSE)
    code, terms, where_terms = ask(web, 'step 2: the terms page', TERMS, referer=LIST)
    if code == 429:
        line()
        line('  STOPPED at the terms page: "too many requests".')
        return
    token = re.search(r'name="csrf-token"[^>]*content="([^"]+)"', terms or '') or \
        re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', terms or '')
    line('     csrf token             %s' % (('present, %d chars' % len(token.group(1))) if token else 'NOT FOUND'))
    line('     cookies now            %s' % (', '.join('%s (%d chars)' % (c.name, len(c.value)) for c in jar) or '-'))
    if not args.accept:
        line()
        line('  Stopped before pressing Accept. Run again with --accept to go the whole way.')
        return

    head('4. Pressing Accept, as zigmon does')
    form = re.search(r'<form\b[^>]*action="([^"]*accept[^"]*)"[^>]*>(.*?)</form>', terms or '', re.S | re.I)
    if not form:
        line('  the terms page has no form that posts to an accept address')
        return
    action = urllib.parse.urljoin(where_terms, form.group(1))
    fields = dict(re.findall(r'<input\b[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form.group(2)))
    fields.update(dict((n, v) for v, n in re.findall(r'<input\b[^>]*value="([^"]*)"[^>]*name="([^"]+)"',
                                                      form.group(2))))
    fields = {k: v for k, v in fields.items() if v and k != 'commit'}
    if token and 'authenticity_token' not in fields:
        fields['authenticity_token'] = token.group(1)
    line('  form fields            %s' % ', '.join('%s (%d chars)' % (k, len(v)) for k, v in fields.items()))
    time.sleep(PAUSE)
    code, _t, _w = ask(web, 'step 3: Accept', action, data=urllib.parse.urlencode(fields).encode(),
                       referer=where_terms)
    if code == 429:
        line()
        line('  STOPPED at Accept: "too many requests".')
        return
    line('     cookies now            %s' % (', '.join('%s (%d chars)' % (c.name, len(c.value)) for c in jar) or '-'))
    time.sleep(PAUSE)
    code, text, _w = ask(web, 'step 4: the list again, now agreed', LIST, referer=where_terms)
    line()
    if code == 200 and '<html' not in text[:2000].lower():
        line('  IT WORKED from this machine: the terms were agreed and the list came back.')
    else:
        line('  It did not work - the answers above say where it stopped.')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        line('\n  stopped')
