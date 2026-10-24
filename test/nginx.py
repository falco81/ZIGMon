#!/usr/bin/env python3
"""The nginx file, read for the things nginx itself would refuse.

There is no nginx here to ask, and the file is shipped to machines where a
mistake in it stops the web server rather than the dashboard - which is worse
than any fault inside the dashboard, because it takes everything else on that
machine with it.
"""
import re
import sys
from pathlib import Path

# Every nginx file that ships, not only the dashboard's: the one in front of
# it is the piece that faces the internet, and a fault there is the same
# fault - the web server does not start, and takes every other site with it.
DEPLOY = Path(__file__).resolve().parent.parent / 'deploy'
CONFS = sorted(DEPLOY.glob('*.conf'))
text = '\n'.join(c.read_text() for c in CONFS)
bad = []

# The one that faces the internet must expose one address and refuse the rest,
# and must not carry the dashboard's own locations by being copied from it.
front = (DEPLOY / 'nginx-tap-front.conf')
if front.exists():
    words = front.read_text()
    if 'location = /tap' not in words:
        bad.append('the front server does not carry the one address it exists for')
    if 'location / { return 404; }' not in words:
        bad.append('the front server does not refuse everything that is not that address')
    for never in ('index.php$', 'fastcgi_pass', '/api/', 'location ~ \\.php'):
        if never in words:
            bad.append('the front server carries %s, which belongs only at home' % never)
    if 'X-Forwarded-For' not in words:
        bad.append('the front server does not pass the caller on, so guesses are counted against it')
    if 'limit_req zone' not in words:
        bad.append('the address that faces the internet has no rate limit')

# A location's regex may hold { or }, but only in quotes: nginx reads a brace
# as the start or end of a block and cuts the expression off there, then
# refuses to start with "missing ) in ...". This is how /tap/([A-Za-z0-9_-]
# was all nginx ever saw of a perfectly good pattern.
for match in re.finditer(r'location\s+(~\*?|=)?\s*([^\s{][^\n]*?)\s*\{', text):
    expr = match.group(2).strip()
    if ('{' in expr or '}' in expr) and not (expr.startswith('"') and expr.endswith('"')):
        bad.append('location %s needs quoting: a brace in it ends the expression' % expr)

# gzip always compresses text/html, and naming it warns at every start
for line in text.split('\n'):
    if line.strip().startswith('gzip_types') and 'text/html' in line:
        bad.append('gzip_types names text/html, which nginx compresses anyway - a warning at start')

# every brace balanced, or nginx says something far less helpful than this
depth = 0
for n, line in enumerate(text.split('\n'), 1):
    without = re.sub(r'"[^"]*"|#.*$', '', line)
    depth += without.count('{') - without.count('}')
    if depth < 0:
        bad.append('a } too many at line %d' % n)
        break
if depth > 0:
    bad.append('%d block(s) left open at the end' % depth)

# Every regex must compile. A quoted pattern is taken whole - reading up to
# the first brace is the very mistake being looked for, and doing it here
# would report a sound pattern as broken.
for match in re.finditer(r'location\s+~\*?\s*(?:"([^"]*)"|([^\s{]+))\s*\{', text):
    expr = match.group(1) if match.group(1) is not None else match.group(2)
    try:
        re.compile(expr)
    except re.error as e:
        bad.append('location %s is not a regular expression: %s' % (expr, e))

# A rewrite resets $1..$9 to its own captures, so "rewrite ^ /x?t=$1" hands
# on an empty token however well the location captured it. If a rewrite uses
# a capture, its own expression has to make one.
for match in re.finditer(r'\n\s*rewrite\s+("[^"]*"|\S+)\s+(\S+)', text):
    pattern, target = match.group(1).strip('"'), match.group(2)
    if re.search(r'\$[1-9]', target) and '(' not in pattern:
        bad.append('rewrite %s uses $1 but captures nothing itself - the token arrives empty'
                   % pattern)

# An if block takes almost nothing. The whole list nginx allows inside one is
# short, and everything else - default_type among them - stops the web server
# at start with "directive is not allowed here". That is exactly how a release
# meant to make a refusal friendlier took nginx down with it.
IF_ALLOWS = ('return', 'rewrite', 'set', 'break', 'proxy_pass', 'fastcgi_pass',
             'add_header', 'expires', 'limit_rate', 'access_log', 'log_not_found',
             'uwsgi_pass', 'scgi_pass', 'memcached_pass', 'gzip', 'if', '}', '{')
lines = text.split('\n')
depth_in_if = 0
for n, line in enumerate(lines, 1):
    # quotes and comments are not blocks: the refusal itself is a JSON string
    # with a brace at each end of it
    counted = re.sub(r'"[^"]*"|\'[^\']*\'|#.*$', '', line)
    opens = counted.count('{') - counted.count('}')
    word = line.strip().split()[0].rstrip(';') if line.strip() else ''
    if depth_in_if > 0:
        if word and not word.startswith('#') and word not in IF_ALLOWS:
            bad.append('line %d: %s is not allowed inside an if block' % (n, word))
        depth_in_if += opens
        continue
    if re.match(r'^\s*if\s*\(', line) and '{' in counted:
        depth_in_if = opens

# A limit that names a zone nobody declared stops nginx at start, and the
# declaration has to stand outside the server block - limit_req_zone is an
# http directive, and the file is included inside http. Easy to move one and
# not the other.
zones = set(re.findall(r'limit_req_zone[^;]*zone=(\w+):', text))
for used in set(re.findall(r'limit_req\s+zone=(\w+)', text)):
    if used not in zones:
        bad.append('limit_req names the zone %s, which nothing declares' % used)
for m in re.finditer(r'\n\s*limit_req_zone\b', text):
    depth_here = 0
    for line in text[:m.start()].split('\n'):
        counted = re.sub(r'"[^"]*"|\'[^\']*\'|#.*$', '', line)
        depth_here += counted.count('{') - counted.count('}')
    if depth_here:
        bad.append('limit_req_zone is inside a block; it belongs at the top of the file')

if bad:
    print('the nginx file would not start:')
    for line in bad:
        print('   ' + line)
    sys.exit(1)
print('%d nginx file(s): %d location(s), braces balanced, every pattern sound, '
      'nothing forbidden inside an if'
      % (len(CONFS), len(re.findall(r'\n\s*location\s', text))))


# The one-tap roads may be reached from a server in front while the dashboard
# itself is not. That only holds if each of those locations carries its own
# allow rules - the ones at the top of the server apply to everything else -
# and if it hands the request to PHP itself: a rewrite re-enters the location
# list and lands in the php block, where the server's own rules apply again,
# and the front server would be refused there.
_home = (DEPLOY / 'nginx-zigmon.conf').read_text()
for _road in ('location = /tap', 'location ~ "^/tap/'):
    _at = _home.index(_road)
    _block = _home[_at:_home.index('\n    }', _at)]
    # and the allow has to be a line, not a comment: a road that only talks
    # about letting the server in front through lets nothing through
    _live = '\n'.join(l for l in _block.splitlines() if not l.strip().startswith('#'))
    if 'deny  all' not in _live or 'allow ' not in _live:
        print('%s has no rules of its own, so it is open to whatever the server allows' % _road)
        raise SystemExit(1)
    if 'rewrite' in _block and 'fastcgi_pass' not in _block:
        print('%s sends the request round again instead of handing it to PHP' % _road)
        raise SystemExit(1)
    if 'fastcgi_pass' not in _block:
        print('%s never reaches PHP at all' % _road)
        raise SystemExit(1)
    if re.search(r'^\s*set_real_ip_from', _block, re.M):
        # real_ip rewrites the address before the access rules are read, so
        # the connection stops being the server in front and the allow rule
        # for it matches nothing at all
        print('%s uses set_real_ip_from, which undoes its own allow rule' % _road)
        raise SystemExit(1)
print('both one-tap roads carry their own allow rules and reach PHP without going round again')
if '$zigmon_presser' not in _home or 'map $http_x_forwarded_for' not in _home:
    print('the rate limit counts the connection, so one server in front shares one bucket')
    raise SystemExit(1)
print('the rate limit counts whoever pressed, not the server that passed it on')

# fastcgi_params sets QUERY_STRING to the request's own query, so a road that
# includes it after setting one of its own has its own wiped: PHP sees no
# query, answers with the whole dashboard page, and the daemon never hears
# about it. A 200 and a megabyte of HTML is a hard thing to read as a fault.
for _road in ('location = /tap', 'location ~ "^/tap/'):
    _at = _home.index(_road)
    _block = _home[_at:_home.index('\n    }', _at)]
    # read with the comments out of the way: one of them says the word
    _block = '\n'.join(l for l in _block.splitlines() if not l.strip().startswith('#'))
    if 'QUERY_STRING' in _block:
        if 'include' not in _block:
            print('%s never includes fastcgi_params' % _road)
            raise SystemExit(1)
        if _block.index('include') > _block.index('QUERY_STRING'):
            print('%s includes fastcgi_params after its own QUERY_STRING, which wipes it' % _road)
            raise SystemExit(1)
print('both roads set their query after including fastcgi_params, not before')

# The installer must not write its idea of the tap block over one that is
# already there: a config on a running house has its own addresses, its own
# allow rules and a server in front, and an installer that overwrites that
# does damage every time it runs. It may add the block where there is none,
# and it must put the file back if nginx refuses what came out.
_setup = (DEPLOY.parent / 'install.sh').read_text()
_where = _setup.index('location = /tap')
_around = _setup[max(0, _where - 3000):_where + 8000]
for _wanted, _why in (
        ("print('same'", 'it does not notice a config that already matches'),
        ("else 'theirs'", 'it does not leave a config of its own alone'),
        ('kept as it is', 'it does not say that it left one alone'),
        ('zigmon-before', 'it takes no copy before writing'),
        ('cp -a "$NGINX_CONF.zigmon-before"', 'it does not put the file back when nginx refuses')):
    if _wanted not in _around:
        print('the installer: %s' % _why)
        raise SystemExit(1)
if 'rewrite ^ /index.php?api=tap' in _around:
    print('the installer still writes the old rewrite form of the tap block')
    raise SystemExit(1)
print('the installer adds the tap block where there is none and leaves any other alone')

# A server published to the internet names its own cipher list. Left to nginx,
# the default still offers the TLS_RSA suites - no forward secrecy, recorded
# today and read whenever the key is taken - and a grade capped at B for it.
_front = (DEPLOY / 'nginx-tap-front.conf').read_text()
_live = '\n'.join(l for l in _front.splitlines() if not l.strip().startswith('#'))
if 'ssl_ciphers' not in _live:
    print('the front server names no cipher list, so nginx offers its default with the RSA suites in it')
    raise SystemExit(1)
_list = _live[_live.index('ssl_ciphers'):].split(';')[0]
for _bad in ('TLS_RSA', 'AES128-SHA', 'CAMELLIA', 'DES', 'RC4', '3DES'):
    if _bad in _list:
        print('the front cipher list offers %s' % _bad)
        raise SystemExit(1)
if 'ECDHE' not in _list:
    print('the front cipher list offers nothing with forward secrecy')
    raise SystemExit(1)
for _wanted in ('ssl_protocols', 'ssl_ecdh_curve', 'ssl_session_tickets', 'ssl_stapling'):
    if _wanted not in _live:
        print('the front server sets no %s' % _wanted)
        raise SystemExit(1)
print('the front server names an ECDHE-only cipher list and staples its own answer')

# The name, not the address, in the Host the front server sends on: the home
# nginx picks its server block by that header, and one that does not match
# lands in whichever block is the default.
_host = [l for l in _front.splitlines() if 'proxy_set_header Host' in l and not l.strip().startswith('#')]
if not _host:
    print('the front server sends no Host, so the home server picks its default block')
    raise SystemExit(1)
if 'example' in _host[0]:
    print('the front server sends a Host nobody answers to: %s' % _host[0].strip())
    raise SystemExit(1)
print('the front server sends the home vhost its own name')


# The front config must answer to the name and to nothing else. A server block
# is chosen by the Host header and whatever is left over goes to the default
# one - so with only the real block in the file, a request to the machine's
# bare address WAS the real block, and every scanner that walks addresses
# rather than names found the road.
_front = (DEPLOY / 'nginx-tap-front.conf').read_text()
if 'default_server' not in _front:
    print('the front config has no default server, so the bare address reaches the links')
    raise SystemExit(1)
if 'ssl_reject_handshake' not in _front:
    print('the front config does not even mention refusing an unknown name')
    raise SystemExit(1)
# and what it does by default has to be written where the daemon reads, or the
# scanners walking addresses are refused and never counted
# the default block itself, found from its listen line rather than from the
# comment above it that explains the choice
import re as _re3
_m = _re3.search(r'\nserver \{[^}]*?listen\s+443 ssl default_server;[^}]*\}', _front, _re3.S)
_default = _m.group(0) if _m else ''
if 'access_log /var/log/nginx/zigmon-tap.log' not in _default:
    print('the default block writes nowhere the daemon reads, so what it refuses is never weighed')
    raise SystemExit(1)
if 'return 444' not in _default:
    print('the default block does not close the connection')
    raise SystemExit(1)
# the directive itself, not the line of the comment that explains it
# the default block itself, found from its listen line
import re as _re3
_m = _re3.search(r'\nserver \{[^}]*?listen\s+443 ssl default_server;[^}]*\}', _front, _re3.S)
if not _m:
    print('the front config has no default block for port 443')
    raise SystemExit(1)
_default = _m.group(0)
if 'access_log /var/log/nginx/zigmon-tap.log' not in _default:
    print('the default block writes nowhere the daemon reads, so what it refuses is never weighed')
    raise SystemExit(1)
if 'return 444' not in _default and 'ssl_reject_handshake' not in _default:
    print('the default block neither closes the connection nor refuses the handshake')
    raise SystemExit(1)
if '$host !=' not in _front:
    print('a request with the right SNI and a different Host is not checked')
    raise SystemExit(1)
# ...and the real block must not be the default, or it catches them again
_real = _front[:_front.index('location = /tap')]
_real_server = _real[_real.rindex('\nserver {'):]
if 'default_server' in _real_server:
    print('the block that carries the links is the default one, so it catches every name')
    raise SystemExit(1)
print('the front server answers to its name and refuses the bare address at the handshake')


# What the front server says when it refuses. A little JSON error told
# somebody who was only guessing that there is a JSON API here worth guessing
# at; the one thing this road should give away is nothing.
if '"error"' in _front or "'{\"ok\"" in _front:
    print('the front config answers a refusal with words that describe what is behind it')
    raise SystemExit(1)
if 'return 405 ""' not in _front:
    print('a wrong method is not answered with a bare status')
    raise SystemExit(1)
if 'default_type application/json' in _front:
    print('the front server still declares itself a JSON API')
    raise SystemExit(1)
print('the front server gives nothing away when it refuses')


# ntfy beside the tap road: its own root on its own port, because ntfy serves
# its API and its web app from the root of whatever name it is given and half
# of it breaks under a path prefix.
_ntfy = (DEPLOY / 'nginx-ntfy-front.conf').read_text()
for _need, _why in (
        ('proxy_pass http://127.0.0.1:2586', 'it does not reach ntfy on the loopback'),
        ('proxy_buffering         off', 'a held-open subscription would be buffered'),
        ('Upgrade           $http_upgrade', 'the websocket cannot be upgraded'),
        ('client_max_body_size', 'there is no limit on what may be sent'),
        ('limit_req zone=ntfy_front', 'nothing limits how fast it may be asked'),
        ('limit_except GET POST', 'odd methods are passed through to ntfy'),
        ('$host !=', 'the bare address is not refused as it is everywhere else'),
        ('location / {', 'ntfy is not given a root of its own')):
    if _need not in _ntfy:
        print('the ntfy config is wrong: %s' % _why)
        raise SystemExit(1)
if 'location /ntfy' in _ntfy:
    print('ntfy is published under a path prefix, which breaks its web app and its websocket')
    raise SystemExit(1)
# a name of its own, on 443, and not the default block - the default is the one
# that refuses everything it does not know, and it stays that way
if 'server_name ntfy.' not in _ntfy:
    print('ntfy has no name of its own')
    raise SystemExit(1)
if 'default_server' in _ntfy:
    print('the ntfy block is the default one, so it would catch every name')
    raise SystemExit(1)
if 'listen      80;' not in _ntfy:
    print('the ntfy name has no door on port 80, so a certificate cannot be issued for it')
    raise SystemExit(1)
print('ntfy is published at a root of its own, with its subscriptions left unbuffered')


# The ntfy config that goes with it. Every option in it has to be one ntfy
# actually has - a misspelled key in a YAML file is not an error, it is a
# setting that silently does nothing, which for "deny-all" would be an open
# server that looks shut.
import yaml as _yaml
_conf = _yaml.safe_load((DEPLOY / 'ntfy-server.yml').read_text())
# the log it writes must be somewhere the ntfy user owns, and the house is
# told to read it, so it has to be named at all
if not _conf.get('log-file'):
    print('ntfy writes no log of its own, so there is nothing for the house to read')
    raise SystemExit(1)
for _need, _want, _why in (
        ('auth-default-access', 'deny-all', 'anybody who learns a topic name can read and write it'),
        ('web-root', 'disable', 'the web app, the login page and /static are all reachable'),
        ('enable-signup', False, 'anybody can make themselves an account'),
        ('enable-reservations', False, 'a stranger can reserve a topic'),
        ('behind-proxy', True, 'every visitor is rate-limited as though they were nginx'),
        ('enable-metrics', False, 'the server tells the world about its insides')):
    if _conf.get(_need) != _want:
        print('the ntfy config is not shut: %s' % _why)
        raise SystemExit(1)
if not str(_conf.get('listen-http', '')).startswith('127.0.0.1'):
    print('ntfy listens somewhere other than the loopback, so nginx is not the only way in')
    raise SystemExit(1)
if _conf.get('attachment-cache-dir'):
    print('attachments are on, which is an upload road and a disk to fill')
    raise SystemExit(1)
if not _conf.get('auth-file') or not _conf.get('ban-file'):
    print('the ntfy config keeps no user database, or writes down nobody it refused')
    raise SystemExit(1)
# Every file it is told to write has to be somewhere the ntfy user owns. The
# unit runs as User=ntfy, and a file it cannot open is a startup failure, not
# a warning - systemd then gives up after five tries saying "start request
# repeated too quickly", which says nothing about what was wrong.
for _key in ('auth-file', 'ban-file', 'cache-file', 'log-file'):
    _where = str(_conf.get(_key) or '')
    if _where and not _where.startswith(('/var/lib/ntfy/', '/var/cache/ntfy/')):
        print('%s is written to %s, which the ntfy user does not own' % (_key, _where))
        raise SystemExit(1)
# An iPhone cannot be woken by a server Apple has never heard of. Without an
# upstream, a self-hosted ntfy has no way to ring it at all - the message sits
# there until somebody opens the app - and the setting that fixes it is one
# line that is easy to leave out and impossible to guess from the symptom.
if not str(_conf.get('upstream-base-url') or '').startswith('https://'):
    print('no upstream is named, so an iPhone is never woken and nobody can tell why')
    raise SystemExit(1)
print('the ntfy config denies by default, listens on the loopback, and serves no web app')
print('...and names an upstream, so an iPhone can be woken without it seeing the message')


# An upgrade must say WHAT WE CHANGED in deploy/ since the version that was
# running - not how somebody's own config differs from the packaged one, which
# it always will, because a running house has its own addresses and
# certificates in those files and saying so every time teaches people to skip
# the message.
_inst = (Path(__file__).resolve().parent.parent / 'install.sh').read_text()
if 'DEPLOY_CHANGES=' not in _inst or 'report_deploy_changes' not in _inst:
    print('the installer says nothing about what changed in deploy/')
    raise SystemExit(1)
_upgrade = _inst[_inst.index('do_upgrade() {'):]
_upgrade = _upgrade[:_upgrade.index('\n}')]
if 'report_deploy_changes' not in _upgrade:
    print('the list exists but an upgrade never says it')
    raise SystemExit(1)
# every file it names must actually be in deploy/, or the note points nowhere
_listed = _inst[_inst.index('DEPLOY_CHANGES="'):]
_listed = _listed[:_listed.index('\n"\n')]
_named = {_l.split('|')[1] for _l in _listed.splitlines() if _l.count('|') >= 2}
_missing = sorted(n for n in _named if not (DEPLOY / n).is_file())
if _missing:
    print('the list names deploy file(s) that are not there: %s' % ', '.join(_missing))
    raise SystemExit(1)
# and the newest entry must not be newer than this release
_versions = [_l.split('|')[0] for _l in _listed.splitlines() if _l.count('|') >= 2]
_here = _re3.search(r"__version__ = '([^']+)'",
                    (Path(__file__).resolve().parent.parent / 'zigmon.py').read_text()).group(1)
_as_numbers = lambda v: [int(x) for x in v.split('.')]
if _versions and max(map(_as_numbers, _versions)) > _as_numbers(_here):
    print('the list mentions a release that does not exist yet')
    raise SystemExit(1)
print('an upgrade says what changed in deploy/ since the version that was running')


# ntfy's own two files are rotated by copytruncate, because ntfy holds them
# open and is never told to reopen them - and the most recent copy has to stay
# plain, because the house reads it with tail to pick up whatever was written
# between its last reading and the rotation.
_rot = (DEPLOY / 'ntfy.logrotate').read_text()
for _need, _why in (
        ('/var/lib/ntfy/ntfy.log', 'it does not rotate the log the house reads'),
        ('/var/lib/ntfy/ban.log', 'it does not rotate the ban feed'),
        ('copytruncate', 'moving a file ntfy holds open leaves it writing to one with no name'),
        ('delaycompress', 'the newest copy would be compressed, and tail cannot read that'),
        ('su ntfy ntfy', 'logrotate cannot see into /var/lib/ntfy as anybody else')):
    if _need not in _rot:
        print('the ntfy logrotate is wrong: %s' % _why)
        raise SystemExit(1)
print('ntfy\'s own two files are rotated in a way that leaves them readable')


# The full line is written for EVERY request to that name, not only the one
# road: a scanner never touches /tap, and a scanner is the thing worth
# learning from. Every server block that answers anything writes it.
_full_lines = _front.count('zigmon-tap-full.log tapfull')
if 'log_format tapfull' not in _front:
    print('the front config declares no full log format')
    raise SystemExit(1)
if _full_lines < 3:
    print('the full log is written in only %d block(s); the default blocks answer scanners too'
          % _full_lines)
    raise SystemExit(1)
if 'escape=json' not in _front:
    print('the full log is not escaped as JSON, so a crafted body writes a line of its own')
    raise SystemExit(1)
if '$http_x_zigmon_tap' in _front.split('log_format tapfull')[1].split(';')[0]:
    print('the full log writes down the link secret itself')
    raise SystemExit(1)
_ntfy_full = (DEPLOY / 'nginx-ntfy-front.conf').read_text()
if _ntfy_full.count('ntfy-full.log ntfyfull') < 2:
    print('the notification server writes its full log in only one place; a request turned away '
          'by the host check never reaches the location and would go unwritten')
    raise SystemExit(1)
if '$http_authorization' in _ntfy_full.split('log_format ntfyfull')[1].split("';")[0]:
    print('the notification server\'s full log writes down the token itself')
    raise SystemExit(1)
# ...nor anybody else's: a cookie or an Authorization header that comes with a
# request is somebody's login, and the full logs wrote both down whole. They
# say only whether one was sent.
for _name, _file in (('tapfull', 'nginx-tap-front.conf'), ('ntfyfull', 'nginx-ntfy-front.conf')):
    _fmt = (DEPLOY / _file).read_text().split('log_format ' + _name)[1].split("';")[0]
    for _var in ('$http_cookie', '$http_authorization'):
        if _var in _fmt:
            print('the full log of %s writes down %s whole' % (_file, _var))
            raise SystemExit(1)
print('the full log covers every request and carries no secret of its own')


# The Suricata note and the config that goes with it must both be in the
# package, and the note must name the tool where AlmaLinux 9 actually puts it
# - /sbin, which is not on root's PATH in a cron job, so a line that says just
# "suricata-update" runs on Monday and does nothing for ever.
_note = DEPLOY / 'suricata-on-the-proxy.md'
_conf9 = DEPLOY / 'suricata.yaml'
if not _note.is_file():
    print('the Suricata note is not in the package')
    raise SystemExit(1)
if not _conf9.is_file():
    print('the Suricata config the note talks about is not in the package')
    raise SystemExit(1)
_words = _note.read_text()
if '/sbin/suricata-update' not in _words:
    print('the note does not name suricata-update where Alma 9 keeps it')
    raise SystemExit(1)
import yaml as _yaml9
_parsed = _yaml9.safe_load(_conf9.read_text())
_eve = [o for o in _parsed['outputs'] if 'eve-log' in o][0]['eve-log']
_alert = [t for t in _eve['types'] if isinstance(t, dict) and 'alert' in t][0]['alert'] or {}
if _alert.get('payload') is not False or _alert.get('packet') is not False:
    print('the packaged Suricata config writes packets or payloads down')
    raise SystemExit(1)
if not str(_eve['filename']).startswith('/'):
    print('the packaged config names eve.json by a relative path')
    raise SystemExit(1)
# Asking for the fingerprints in eve-log is not enough: they have to be
# calculated, and left on auto they are not. Suricata says so once at startup
# - "JA3 is disabled, skipping fields" - and then the tls lines come out with
# no fingerprint in them and the house weighs nothing, with nothing anywhere
# saying why.
_layer = ((_parsed.get('app-layer') or {}).get('protocols') or {}).get('tls') or {}
_wants = [t for t in _eve['types'] if isinstance(t, dict) and 'tls' in t]
if _wants and (_wants[0]['tls'] or {}).get('custom'):
    _asked = [x for x in _wants[0]['tls']['custom'] if str(x).startswith('ja')]
    if _asked and not _layer.get('ja3-fingerprints'):
        print('the config asks eve-log for %s but never turns the fingerprinting on' % _asked)
        raise SystemExit(1)
print('the Suricata note and its config travel together, and write no payloads')


# The SMS gateway pushes an arriving message down a road of its own, so it can
# be allowed there and nowhere else in the dashboard: it is a box on another
# network with a SIM card in it. Allowing it at the top of the server would
# let it at every view the house has.
_home = (DEPLOY / 'nginx-zigmon.conf').read_text()
if 'location = /api/sms/incoming' not in _home:
    print('the SMS push has no road of its own; the gateway would have to be allowed everywhere')
    raise SystemExit(1)
_block = _home[_home.index('location = /api/sms/incoming'):]
_block = _block[:_block.index('\n    location ')]
for _need, _why in (
        ('deny  all', 'it does not shut the road to everybody else'),
        ('api=sms-incoming', 'it does not hand the request to the right road'),
        ('limit_req', 'it has no rate limit, and anybody reaching it is trying the word'),
        ('client_max_body_size', 'it takes a body of any size')):
    if _need not in _block:
        print('the SMS push road is wrong: %s' % _why)
        raise SystemExit(1)
if 'zone=zigmon_tap' in _block and 'limit_req_zone' not in _home.split('location')[0]:
    print('the SMS push road names a rate limit zone that is never declared')
    raise SystemExit(1)
print('the SMS gateway has a road of its own, shut to everybody else')



# php2shell (CVE-2026-109618, CVE-2026-109619, 21 October 2026, both 9.2): one
# of the two is reached through PHP's own multipart parser, and it is acted on
# before any page of this house runs - so no PIN, no allow rule and nothing in
# index.php is in front of it. The version of PHP is the only real mend; this
# is what can be done in front of it, and it costs the dashboard nothing,
# because nothing in the dashboard ever sends a multipart body.
#
# Both files have to carry it: the home one serves PHP on every road, and the
# one facing the internet hands /tap to it.
_PHP2SHELL = (('nginx-zigmon.conf', 'the dashboard\'s own server, which serves PHP on every road'),
              ('nginx-tap-front.conf', 'the server facing the internet, which hands /tap to PHP'))
for _name, _what in _PHP2SHELL:
    _conf = DEPLOY / _name
    if not _conf.exists():
        continue
    _words = _conf.read_text()
    _found = re.search(r'if\s*\(\s*\$http_content_type\s*~\*?\s*"\^multipart/"\s*\)\s*\{\s*return\s+(\d+)',
                       _words)
    if not _found:
        print('%s does not refuse a multipart body in front of PHP (%s)' % (_name, _what))
        raise SystemExit(1)
    # at server level, not inside one location: a rule in a location covers
    # one road and leaves every other one open
    _at = _words.index(_found.group(0))
    _before = _words[:_at]
    if _before.count('location') and _before.rindex('location') > _before.rindex('server {'):
        _head = _before[_before.rindex('location'):]
        if _head.count('{') > _head.count('}'):
            print('%s refuses multipart inside one location only; the other roads stay open' % _name)
            raise SystemExit(1)
print('both nginx files refuse a multipart body in front of PHP, at server level')

# ...and nothing in the dashboard may start sending one, or the rule above
# would break it. Every file picker on the page is read in the browser and
# sent as JSON; a <form enctype> or a FormData anywhere means that stopped
# being true.
_page = (DEPLOY.parent / 'web' / 'index.php').read_text()
for _never, _why in (('FormData', 'the page builds a multipart body with FormData'),
                     ('enctype', 'the page has a form that would be sent as multipart')):
    if _never.lower() in _page.lower():
        print('%s - the rule refusing multipart in nginx would break the dashboard' % _why)
        raise SystemExit(1)
if 'FileReader' not in _page:
    print('the page no longer reads the files it is given in the browser')
    raise SystemExit(1)
print('the dashboard still reads its own uploads in the browser, so refusing multipart costs nothing')

# The installer has to put the same two things on a machine that is being
# upgraded, not only on a fresh one: the php.ini hardening, and the word about
# which PHP carries the fix.
_sh = (DEPLOY.parent / 'install.sh').read_text()
if 'harden_php() {' not in _sh:
    print('install.sh has nothing that hardens PHP')
    raise SystemExit(1)
if _sh.count('\n        harden_php') + _sh.count('\n    harden_php') < 2:
    print('install.sh hardens PHP on one path only; an upgrade would not get it')
    raise SystemExit(1)
for _need, _why in (('session.upload_progress.enabled = 0',
                     'the upload-progress handler, one of the two published ways in, is left on'),
                    ('CVE-2026-109618', 'it never names what it is protecting against'),
                    ('8.3.36', 'it does not know which version carries the fix')):
    if _need not in _sh:
        print('install.sh: %s' % _why)
        raise SystemExit(1)
print('the installer hardens PHP and says which version carries the fix, on a fresh machine and an upgrade')
