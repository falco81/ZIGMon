#!/usr/bin/env python3
"""5.58: what the front server's logs of 17-27 November 2026 said about the
weighing, and what was changed for it. Every check marked "(new)" fails on
5.58.0; the rest say the house is still left alone.

    python3 test/review558_hunt.py

Every address below is from the documentation ranges (192.0.2.0/24,
198.51.100.0/24, 203.0.113.0/24, 2001:db8::/32), every name and agent made
up; none of it is from the logs. Python counts those ranges as private, so
the daemon's own_house() is told here that they are the internet - every
other address keeps its own answer. No network, no broker, no web server:
the daemon is built against a database of its own in a folder of its own,
and the server in front is a function that hands back lines. Nothing listens.
"""
import ipaddress
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review558-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    else:
        print('  ok: ' + what.split(' - ')[0])
    return ok


sys.path.insert(0, os.environ.get('REVIEW558_DAEMON') or str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 20240, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [],
                      'mqtt_host': '', 'log_file': '', 'log_to_journal': False,
                      'state_dir': str(W / 'state'), 'never_block': '', 'block_ladder': '',
                      'block_private': 'gently', 'block_mode': 'temporary', 'blacklist': 1,
                      'block_score': 15, 'block_sensitivity': 'normal', 'feeds_ban': 0, 'feeds': '',
                      'feeds_weight': 3, 'intel_shodan': 0, 'intel_on_block': 0,
                      'mikrotik_host': '', 'mikrotik_list': '', 'trusted_proxies': '', 'proxy_host': '',
                      'suricata_least': 2, 'suricata_tls': 0, 'block_window_min': 10})
(W / 'state').mkdir()
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
d.mikrotik_after_change = lambda *a, **k: None
d.feed_wanted = lambda: []
d.proxy_run = lambda command: ''          # the server in front: nothing over SSH, ever

DOCS = [ipaddress.ip_network(n) for n in ('192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24', '2001:db8::/32')]
_own = zigmon.Daemon.own_house


def own_house(addr):
    try:
        one = ipaddress.ip_address(addr)
    except ValueError:
        return True
    if any(one in net for net in DOCS if net.version == one.version):
        return False                      # the documentation ranges stand in for the internet
    return _own(addr)


d.own_house = own_house

NTFY = 'push.example.net'
TAP = 'tap.example.net'
BROWSER = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0'
PHONE = 'BackgroundShortcutRunner/3607.0.2 CFNetwork/3860.100.1 Darwin/25.0.0'


def fresh():
    d.store.unblock()
    d.forget_anomaly()
    d._blocked_times.clear()
    d.__dict__.pop('_seen_friends', None)
    d.__dict__.pop('_friends', None)


def stamp(ago):
    return time.strftime('%d/%b/%Y:%H:%M:%S +0000', time.gmtime(time.time() - ago))


def iso(ago):
    return time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime(time.time() - ago))


def access(ip, ago, request, status, agent=BROWSER):
    """One line of the one-tap road's access log, as nginx writes it."""
    return '%s - - [%s] "%s" %d 0 "-" "%s"' % (ip, stamp(ago), request, status, agent)


def full(ip, ago, method='GET', path='/', status=444, host='', agent=BROWSER, which='', scheme='https', **more):
    """One line of the full JSON log, with only what the weighing reads."""
    one = {'ip': ip, 't': iso(ago), 'm': method, 'u': path, 'proto': 'HTTP/1.1' if method else '', 's': status,
           'bytes': 0, 'took': 0.0, 'host': host, 'ua': agent, 'ref': '', 'ct': '', 'clen': '',
           'body': '', 'secret': 'none', 'code': 'none', 'xff': '', 'xfh': '', 'xou': '', 'xru': '',
           'auth': 'none', 'cookie': 'none', 'ctlen': '', 'scheme': scheme,
           'ssl': 'TLSv1.3/TLS_AES_128_GCM_SHA256' if scheme == 'https' else '/'}
    if which:
        one['which'] = which
    one.update(more)
    return json.dumps(one, separators=(',', ':'))


def alert(ip, ago, signature, severity=2, category='Misc Attack', answered=False, sid=2400001):
    return json.dumps({
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S.000000+0000', time.gmtime(time.time() - ago)),
        'event_type': 'alert', 'src_ip': ip, 'src_port': 40000, 'dest_ip': '10.9.0.2', 'dest_port': 443,
        'proto': 'TCP', 'flow': {'pkts_toserver': 3 if answered else 1, 'pkts_toclient': 2 if answered else 0},
        'alert': {'severity': severity, 'signature': signature, 'category': category,
                  'signature_id': sid, 'rev': 1}}, separators=(',', ':'))


def kinds_of(ip):
    rows = [x for x in d.anomaly_state() if x['ip'] == ip]
    return [k['kind'] for k in (rows[0]['kinds'] if rows else [])]


def blocked(ip):
    return d.store.blocked_until(ip) is not None


try:
    # 1. What the logs asked for that nothing recognised.
    print('1. the paths of these logs that were weighed as pages that are not there')
    fresh()
    named = [('POST /GponForm/diag_Form?style/ HTTP/1.1', 400, 'proxy-exploit'),
             ('POST /nf/auth/doAuthentication.do HTTP/1.1', 444, 'proxy-exploit'),
             ('POST /p/u/doAuthentication.do HTTP/1.1', 444, 'proxy-exploit'),
             ('GET /redfish/v1/ HTTP/1.1', 444, 'proxy-fingerprint'),
             ('GET /ReportServer HTTP/1.1', 444, 'proxy-fingerprint'),
             ('GET /logon/LogonPoint/index.html HTTP/1.1', 444, 'proxy-fingerprint'),
             ('GET /+webvpn+/index.html HTTP/1.1', 444, 'proxy-fingerprint'),
             ('GET /webvpn.html HTTP/1.1', 444, 'proxy-fingerprint'),
             ('GET /axis/services HTTP/1.1', 444, 'proxy-fingerprint'),
             ('GET /havoc/ HTTP/1.1', 444, 'proxy-fingerprint'),
             ('POST /dns-query HTTP/1.1', 444, 'proxy-fingerprint'),
             ('GET /dns-query?dns=q80BAAABAAAAAAAAB2V4YW1wbGUDY29tAAABAAE HTTP/1.1', 444, 'proxy-fingerprint'),
             ('POST /mcp HTTP/1.1', 444, 'proxy-fingerprint'),
             ('GET /swagger/v1/swagger.json HTTP/1.1', 444, 'proxy-fingerprint'),
             ('GET /api/swagger HTTP/1.1', 444, 'proxy-fingerprint'),
             ('GET /php_info.php HTTP/1.1', 444, 'proxy-secret-hunt'),
             ('GET /phpinf.php HTTP/1.1', 444, 'proxy-secret-hunt'),
             ('GET /sysinfo.php HTTP/1.1', 444, 'proxy-secret-hunt'),
             ('GET /env.php HTTP/1.1', 444, 'proxy-secret-hunt'),
             ('GET /Dockerfile HTTP/1.1', 444, 'proxy-secret-hunt')]
    for n, (request, status, kind) in enumerate(named):
        ip = '203.0.113.%d' % (10 + n)
        d.proxy_weigh([access(ip, 30, request, status)])
        check(kind in kinds_of(ip), '(new) %s - weighed as %r, not as %s' % (request.split(' H')[0], kinds_of(ip), kind))
    # ...and what they must not catch: the house's topics and pages that only
    # start with the same words, and the notification server answering them
    fresh()
    for n, path in enumerate(('/mcp-house/json', '/mcp/json', '/redfish-alerts/json', '/dns-query-log/json',
                              '/havoc-topic/sse', '/api/swaggerish', '/environment.php.txt')):
        ip = '198.51.100.%d' % (100 + n)
        d.full_weigh([full(ip, 20, path=path, status=200, host=NTFY, which='ntfy', agent='ntfy/1.7.0',
                           auth='Basic:sent')])
        d.full_weigh([full(ip, 10, path=path, status=502, host=NTFY, which='ntfy', agent='ntfy/1.7.0',
                           auth='Basic:sent')])
        check(not kinds_of(ip), 'a topic of the house at %s - was weighed: %r' % (path, kinds_of(ip)))

    # 2. Plain HTTP at the TLS port.
    print('2. plain HTTP sent to the TLS port: the round that came back to eleven addresses')
    fresh()
    probe = '198.51.100.20'
    d.proxy_weigh([access(probe, 22, 'GET / HTTP/1.1', 444, 'curl/7.64.1')])
    d.full_weigh([full(probe, 22, path='/', status=444, agent='curl/7.64.1', host='192.0.2.1')])
    d.proxy_weigh(['%s - - [%s] "" 400 150 "-" "-"' % (probe, stamp(12))])
    d.full_weigh([full(probe, 12, method='', path='', status=400, agent='', scheme='http')])
    check(not blocked(probe), 'the first two of the round - are already a block (they were not, and are not)')
    d.proxy_weigh([access(probe, 11, 'GET / HTTP/1.1', 400, 'curl/7.74.0')])
    d.full_weigh([full(probe, 11, path='/', status=400, agent='curl/7.74.0', host='192.0.2.1', scheme='http')])
    check('proxy-junk' in kinds_of(probe) and kinds_of(probe).count('proxy-junk') == 1
          and any('plain HTTP' in str(dd) for _t, _k, dd in d._anomaly.get(probe, [])),
          '(new) plain HTTP at the TLS port - not weighed as bytes that are not what the port speaks: %r'
          % kinds_of(probe))
    check(blocked(probe), '(new) curl, nothing, curl again in plain HTTP - weighed 10 of 15 and let go')
    # the house's own publisher talks to the notification server in plain
    # HTTP, and a request of it refused is not a probe
    fresh()
    publisher = '198.51.100.21'
    for n in range(4):
        d.full_weigh([full(publisher, 40 - n, method='POST', path='/house-topic', status=200 if n % 2 else 400,
                           host=NTFY, which='ntfy', agent='Python-urllib/3.9', scheme='http', auth='Basic:sent')])
    check(not kinds_of(publisher), 'the house\'s publisher in plain HTTP - was weighed: %r' % kinds_of(publisher))
    # ...and a phone that pressed a link and was let in, whatever it is
    # typed into next
    phone = '203.0.113.40'
    d.full_weigh([full(phone, 300, method='POST', path='/tap', status=200, host=TAP, agent=PHONE,
                       secret='sent:43', ct='application/json')])
    for n in range(3):
        d.full_weigh([full(phone, 30 - n, path='/', status=400, host=TAP, agent=PHONE, scheme='http')])
    check(not blocked(phone) and 'proxy-junk' not in kinds_of(phone),
          'a phone of the house in plain HTTP - was weighed as a probe: %r' % kinds_of(phone))

    # 3. Tor is a list, not an attack.
    print('3. ET TOR is where the packet came from, not what it was')
    fresh()
    exit_node = '192.0.2.50'
    d.suricata_weigh([alert(exit_node, 20, 'ET TOR Known Tor Exit Node Traffic group 53'),
                      alert(exit_node, 20, 'ET TOR Known Tor Relay/Router (Not Exit) Node Traffic group 53')])
    check('ids-listed' in kinds_of(exit_node) and 'ids-likely' not in kinds_of(exit_node),
          '(new) a Tor exit - weighed as "Suricata saw something that looks like an attack": %r'
          % kinds_of(exit_node))
    check(d.ids_listed(exit_node) == 'Tor', '(new) a Tor exit - is not on a list: %r' % d.ids_listed(exit_node))
    check(not blocked(exit_node), 'a Tor exit that did nothing else - was kept out')
    check(zigmon.Daemon._ids_list_name('ET TOR Known Tor Exit Node Traffic group 7') == 'Tor'
          and zigmon.Daemon._ids_list_name('ET SCAN Zmap User-Agent (Inbound)') == ''
          and zigmon.Daemon._ids_list_name('ET CINS Active Threat Intelligence Poor Reputation IP group 46') == 'CINS',
          '(new) which rules are lists - read wrongly')
    d.proxy_weigh([access(exit_node, 10, 'GET /.env HTTP/1.1', 444)])
    check(blocked(exit_node), 'a Tor exit then asking for .env - is the list tripling it as any other')

    # 4. A severity below the floor is passed over before it is read.
    print('4. Suricata\'s chatter at severity 3 costs a substring test, not a JSON read and an address')
    fresh()
    chatter = [alert('198.51.100.%d' % (n % 200 + 1), 5, 'SURICATA STREAM ESTABLISHED packet out of window',
                     severity=3, category='Generic Protocol Command Decode') for n in range(20000)]
    real = alert('198.51.100.222', 4, 'ET EXPLOIT Something Remote Code Execution', severity=1,
                 category='Attempted Administrator Privilege Gain', answered=True)
    looked = {'n': 0}
    _same = d.same_address

    def counting(addr):
        looked['n'] += 1
        return _same(addr)
    d.same_address = counting
    began = time.perf_counter()
    d.suricata_weigh(chatter + [real])
    took = time.perf_counter() - began
    d.same_address = _same
    check(looked['n'] <= 1, '(new) 20,000 severity-3 alerts - each had its address worked out and checked '
                            'before its severity: %d' % looked['n'])
    check('ids-serious' in kinds_of('198.51.100.222'), 'the one real alert among them - was lost')
    check(not any(kinds_of('198.51.100.%d' % n) for n in (1, 2, 3)), 'the chatter - was weighed')
    print('  (20,001 lines read in %.3f s)' % took)
    zigmon.CONFIG['suricata_least'] = 3
    d.suricata_weigh([alert('198.51.100.223', 3, 'ET INFO Something Worth Knowing', severity=3,
                            category='Potentially Bad Traffic', answered=True)])
    check('ids-noted' in kinds_of('198.51.100.223'), 'severity 3 with the floor at 3 - was passed over')
    zigmon.CONFIG['suricata_least'] = 2

    # 5. A street that does not hurry.
    print('5. the same named thing from one street, a day apart')
    fresh()
    first, second = '198.51.100.30', '198.51.100.77'
    d.proxy_weigh([access(first, 22 * 3600, 'GET /developmentserver/metadatauploader HTTP/1.1', 444,
                          'Mozilla/5.0 zgrab/0.x')])
    check(not blocked(first), 'one SAP upload from one address - is a block on its own (it is not)')
    d.proxy_weigh([access(second, 30, 'GET /developmentserver/metadatauploader HTTP/1.1', 444,
                          'Mozilla/5.0 zgrab/0.x')])
    check(blocked(second), '(new) the second address of a /24 sending the SAP upload a day later - was one '
                           'request and nothing, as in these logs')
    fresh()
    pool = ['203.0.113.%d' % n for n in (5, 77, 140)]
    for n, ip in enumerate(pool):
        d.proxy_weigh([access(ip, (3 - n) * 86400 + 60, 'GET /rest/applinks/1.0/manifest HTTP/1.1', 444)])
        if n < 2:
            check(not blocked(ip), 'the %s of a street asking for a manifest - kept out already'
                  % ('first', 'second')[n])
    check(blocked(pool[2]), '(new) the third address of one /24 asking for the same manifest over three days '
                            '- never kept out')
    # what does not travel along a street: the agent's name, and a different thing
    fresh()
    d.proxy_weigh([access('192.0.2.10', 20 * 3600, 'GET / HTTP/1.1', 444, 'Mozilla/5.0 zgrab/0.x')])
    d.proxy_weigh([access('192.0.2.11', 60, 'GET / HTTP/1.1', 444, 'Mozilla/5.0 zgrab/0.x')])
    check(not blocked('192.0.2.11'), 'a named scanner\'s single visit - counted its neighbour\'s of yesterday')
    d.proxy_weigh([access('192.0.2.12', 20 * 3600, 'GET /.git/config HTTP/1.1', 444)])
    d.proxy_weigh([access('192.0.2.13', 60, 'GET /redfish/v1/ HTTP/1.1', 444)])
    check(not blocked('192.0.2.13'), 'a different thing in the street - counted as the same round')
    fresh()
    d.proxy_weigh([access('192.0.2.200', 9 * 86400, 'GET /.env HTTP/1.1', 444)])
    d.proxy_weigh([access('192.0.2.201', 60, 'GET /.env HTTP/1.1', 444)])
    check(not blocked('192.0.2.201'), 'a neighbour of nine days ago - still counted')
    d.proxy_weigh([access('2001:db8:5:1::10', 20 * 3600, 'GET /.git/config HTTP/1.1', 444)])
    d.proxy_weigh([access('2001:db8:5:1::99', 60, 'GET /.git/config HTTP/1.1', 444)])
    check(blocked('2001:db8:5:1::99'), '(new) the same in one IPv6 /64 - never kept out')

    # 6. WordPress.com is not a WordPress round.
    print('6. WordPress.com knocking at the xmlrpc.php of a blog that used to live here')
    fresh()
    wpcom = '192.0.2.60'
    d.proxy_weigh([access(wpcom, 20 * 3600, 'POST /xmlrpc.php HTTP/1.1', 444, 'WordPress.com; https://wordpress.com')])
    d.proxy_weigh([access(wpcom, 60, 'POST /xmlrpc.php HTTP/1.1', 444,
                          'Jetpack by WordPress.com (Jetpack 12.0; WordPress 6.4)')])
    check(not blocked(wpcom) and 'proxy-exploit' not in kinds_of(wpcom),
          '(new) WordPress.com\'s own servers - kept out as a WordPress break-in: %r' % kinds_of(wpcom))
    fresh()
    round_ = '192.0.2.61'
    d.proxy_weigh([access(round_, 20 * 3600, 'POST /xmlrpc.php HTTP/1.1', 444)])
    d.proxy_weigh([access(round_, 60, 'POST /xmlrpc.php HTTP/1.1', 444)])
    check(blocked(round_), 'the same from a browser\'s agent - is no longer the WordPress round')

    # 7. The house, as these logs show it.
    print('7. the house\'s own traffic, the way these logs show it, is left alone')
    fresh()
    lines, access_lines = [], []
    sub = '203.0.113.90'                       # a phone subscribed to a topic, polling all day
    for n in range(30):
        lines.append(full(sub, 9000 - n * 300, path='/house-topic/json?poll=1&id=AbCdEf%02d' % n, status=200,
                          host=NTFY, which='ntfy', agent='ntfy/1.7.0 (build 9; iOS 27.2.1)', auth='Basic:sent'))
    lines.append(full(sub, 8000, path='/house-alerts/auth', status=403, host=NTFY, which='ntfy',
                      agent='ntfy/1.7.0 (build 9; iOS 27.2.1)', auth='Basic:sent'))
    pub = '203.0.113.91'                       # the house server publishing
    for n in range(20):
        lines.append(full(pub, 9000 - n * 400, method='POST', path='/house-topic', status=200, host=NTFY,
                          which='ntfy', agent='Python-urllib/3.9', scheme='http', auth='Basic:sent',
                          ct='application/x-www-form-urlencoded', body='msg %d' % n))
    presser = '203.0.113.92'                   # the watch pressing a link
    for n in range(6):
        lines.append(full(presser, 7000 - n * 600, method='POST', path='/tap', status=200, host=TAP, agent=PHONE,
                          secret='sent:43', ct='application/json', body='{}'))
        access_lines.append(access(presser, 7000 - n * 600, 'POST /tap HTTP/2.0', 200, PHONE))
    for n in range(5):                         # ...and then a stale shortcut and a slow house
        access_lines.append(access(presser, 600 - n * 30, 'POST /tap HTTP/2.0', 504, PHONE))
        access_lines.append(access(presser, 590 - n * 30, 'GET / HTTP/2.0', 404, PHONE))
    preview = '203.0.113.93'                   # a messenger making a preview of a link
    for n in range(3):
        access_lines.append(access(preview, 120 - n * 10, 'GET / HTTP/2.0', 404,
                                   'Mozilla/5.0 (Macintosh) facebookexternalhit/1.1 Facebot Twitterbot/1.0'))
        access_lines.append(access(preview, 120 - n * 10, 'GET /favicon.ico HTTP/2.0', 404,
                                   'NetworkingExtension/8625 Network/6681 iOS/27.2'))
    d._friends_from(lines)
    d.full_weigh(lines)
    d.proxy_weigh(access_lines)
    for who, what in ((sub, 'a subscribed phone'), (pub, 'the house\'s publisher'), (presser, 'the watch'),
                      (preview, 'a link preview')):
        check(not blocked(who), '%s - was kept out: %r' % (what, kinds_of(who)))
finally:
    shutil.rmtree(str(W), ignore_errors=True)

print('review558_hunt: %s' % ('%d failed' % len(bad) if bad else 'all good'))
os._exit(1 if bad else 0)
