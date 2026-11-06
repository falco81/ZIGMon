#!/usr/bin/env python3
"""5.45: what the front server's logs of 27 October - 6 November 2026 said
about the weighing, and what was changed for it. Every check here fails on
5.44.3; the last one replays a small sample, written in the shape of those
logs, through the reader of the server in front and asks who ends up kept out.

    python3 test/review545_block.py

Every address, name and agent below is made up. None of them is from the logs:
the house's own phones, its topics and its addresses stay on the house's own
machine. No network, no broker, no web server: the daemon is built against a
database of its own in a folder of its own, and the server in front is a
function that hands back lines. Nothing listens.
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review545-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    else:
        print('  ok: ' + what.split(' - ')[0])
    return ok


sys.path.insert(0, os.environ.get('REVIEW545_DAEMON') or str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 19380, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [],
                      'mqtt_host': '', 'log_file': '', 'log_to_journal': False,
                      'state_dir': str(W / 'state'), 'never_block': '', 'block_ladder': '',
                      'block_private': 'gently', 'block_mode': 'temporary', 'blacklist': 1,
                      'block_score': 15, 'block_sensitivity': 'normal', 'feeds_ban': 0, 'feeds': '',
                      'feeds_weight': 3, 'intel_shodan': 0, 'intel_on_block': 0,
                      'mikrotik_host': '', 'mikrotik_list': '', 'trusted_proxies': '', 'proxy_host': '',
                      'suricata_least': 2, 'suricata_tls': 0})
(W / 'state').mkdir()
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
d.mikrotik_after_change = lambda *a, **k: None
d.feed_wanted = lambda: []
d.proxy_run = lambda command: ''          # the server in front: nothing over SSH, ever

NAME = 'tap.example.net'                  # the house's one-tap name, made up
NTFY = 'push.example.net'
PREVIEW = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_1) AppleWebKit/601.2.4 (KHTML, like Gecko) '
           'Version/9.0.1 Safari/601.2.4 facebookexternalhit/1.1 Facebot Twitterbot/1.0')
ICONS = 'NetworkingExtension/8625.2.8.10.7 Network/6681.42.3 iOS/27.2'
BROWSER = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0'


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


def full(ip, ago, method='GET', path='/', status=444, host='', agent=BROWSER, which='', **more):
    """One line of the full JSON log (tapfull / ntfyfull), with only what the
    weighing reads; the secrets are "sent" or "none", as the map writes them."""
    one = {'ip': ip, 't': iso(ago), 'm': method, 'u': path, 'proto': 'HTTP/1.1', 's': status,
           'bytes': 0, 'took': 0.0, 'host': host, 'ua': agent, 'ref': '', 'ct': '', 'clen': '',
           'body': '', 'secret': 'none', 'code': 'none', 'xff': '', 'xfh': '', 'xou': '', 'xru': '',
           'auth': 'none', 'cookie': 'none', 'ctlen': ''}
    if which:
        one['which'] = which
    one.update(more)
    return json.dumps(one, separators=(',', ':'))


def alert(ip, ago, signature, severity=2, category='Misc Attack', answered=False):
    """One eve.json alert. A reputation rule fires on the first SYN, before the
    server has answered anything, so its flow has no packets to the client."""
    return json.dumps({
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S.000000+0000', time.gmtime(time.time() - ago)),
        'event_type': 'alert', 'src_ip': ip, 'src_port': 40000, 'dest_ip': '10.9.0.2', 'dest_port': 443,
        'proto': 'TCP', 'flow': {'pkts_toserver': 3 if answered else 1, 'pkts_toclient': 2 if answered else 0},
        'alert': {'severity': severity, 'signature': signature, 'category': category,
                  'signature_id': 2400001, 'rev': 1}})


def kinds_of(ip):
    rows = [x for x in d.anomaly_state() if x['ip'] == ip]
    return [k['kind'] for k in (rows[0]['kinds'] if rows else [])]


def blocked(ip):
    return d.store.blocked_until(ip) is not None


# asked through these, so that 5.44.3 - which has neither - fails the checks
# rather than stopping at the first of them
def listed_by(ip):
    return getattr(d, 'ids_listed', lambda _ip: '')(ip)


def list_name(signature):
    return getattr(zigmon.Daemon, '_ids_list_name', lambda _s: '')(signature)


try:
    # 1. A link sent in a messenger: the preview asks for the page and icons.
    print('1. a messenger making a preview of a link is not somebody knocking')
    fresh()
    phone = '146.70.11.24'
    lines = []
    for n in range(3):                    # three rounds, as Apple's preview does
        lines += [access(phone, 60 - n * 10, 'GET / HTTP/2.0', 404, PREVIEW),
                  access(phone, 60 - n * 10, 'GET /apple-touch-icon-precomposed.png HTTP/2.0', 404, ICONS),
                  access(phone, 60 - n * 10, 'GET /apple-touch-icon.png HTTP/2.0', 404, ICONS),
                  access(phone, 60 - n * 10, 'GET /favicon.ico HTTP/2.0', 404, ICONS)]
    d.proxy_weigh(lines)
    check(not blocked(phone),
          'a link preview - twelve requests for /, /favicon.ico and the touch icons by iMessage\'s '
          'preview kept the house\'s own phone out of the one-tap road')
    check(not kinds_of(phone), 'a link preview - was weighed at all: %r' % kinds_of(phone))
    d.proxy_weigh([access(phone, 5, 'GET /.env HTTP/2.0', 404, PREVIEW)])
    check('proxy-secret-hunt' in kinds_of(phone),
          'a preview agent asking for .env - is still asking for .env')

    # 2. A certificate being proved.
    print('2. an ACME challenge is nobody walking addresses')
    fresh()
    lan = '192.168.77.35'                 # the house's own network, as own_house reads it
    d.proxy_weigh([access(lan, 300 - n * 4, 'GET /.well-known/acme-challenge/probe-%04x HTTP/1.1' % n, 444,
                          'acme-http01-check') for n in range(73)])
    check(not blocked(lan),
          'the house\'s own ACME check - 73 challenges at a name the front server does not carry kept '
          'the house out of its own front server ("gently" or not)')
    validator = '23.178.112.9'
    d.proxy_weigh([access(validator, 30 - n, 'GET /.well-known/acme-challenge/tok%d HTTP/1.1' % n, 444,
                          'Mozilla/5.0 (compatible; Let\'s Encrypt validation server)') for n in range(5)])
    check(not kinds_of(validator), 'a CA validator - its challenges were weighed: %r' % kinds_of(validator))
    d.proxy_weigh([access(validator, 2, 'GET /.well-known/acme-challenge/../../etc/passwd HTTP/1.1', 400)])
    check('proxy-payload' in kinds_of(validator) or 'proxy-exploit' in kinds_of(validator),
          'a challenge path that climbs - was passed over with the honest ones')

    # 3. The server in front is never kept out, and never asked about.
    print('3. the server in front, and a trusted proxy, are never kept out')
    fresh()
    front = '185.230.4.17'
    zigmon.CONFIG.update({'trusted_proxies': front, 'intel_shodan': 1, 'intel_on_block': 1})
    d._intel_working = lambda: None       # the queue is looked at, never worked: no Shodan here
    for i in range(6):                    # a press that arrived without the header names the proxy
        d.note_anomaly(d.caller_of(front, ''), 'bad-secret', 'guess-%d' % i)
    check(not blocked(front),
          'a trusted proxy - six wrong secrets from presses that came without X-Forwarded-For put the '
          'server every press comes through on the list, shutting every link for everybody')
    check(d.spared(front), 'a trusted proxy - is not counted among the never kept out')
    d.intel_ask_later(front)
    check(front not in list(d._intel_queue), 'a trusted proxy - was queued to be asked about at Shodan')
    zigmon.CONFIG.update({'trusted_proxies': '', 'proxy_host': front})
    check(d.spared(front), 'the server in front by its own setting - is not counted among the never kept out')
    zigmon.CONFIG.update({'proxy_host': '', 'trusted_proxies': '185.0.0.0/8'})
    check(not d.spared('185.99.1.2'),
          'a trusted range of sixteen million - spared every stranger in it (it was not, and should not be)')
    # ...and what the header says still frames nobody: the right-hand end is
    # what the trusted proxy saw, whatever the caller wrote before it
    zigmon.CONFIG['trusted_proxies'] = front
    check(d.caller_of(front, '146.70.11.24, 192.168.77.35, 91.240.118.50') == '91.240.118.50',
          'a spoofed X-Forwarded-For - chose who got the blame')
    check(d.caller_of('91.240.118.50', '146.70.11.24') == '91.240.118.50',
          'a stranger saying who it speaks for - was believed')
    zigmon.CONFIG.update({'trusted_proxies': '', 'intel_shodan': 0, 'intel_on_block': 0})
    with d._intel_lock:
        d._intel_queue[:] = []

    # 4. The house as the full logs show it.
    print('4. a phone signed in at the notification server is the house')
    fresh()
    roam = '172.226.40.81'                # a phone on Private Relay, made up
    d.full_weigh([full(roam, 600, path='/house-topic/json?poll=1', status=200, host=NTFY,
                       agent='ntfy/1.7.0 (build 9; iOS 27.2.0)', which='ntfy', auth='sent', secret='sent')])
    d.proxy_weigh([access(roam, 60 - n * 5, 'GET / HTTP/1.1', 444) for n in range(6)])
    check(not blocked(roam),
          'a phone signed in at the notification server - six light knocks from its address a few '
          'minutes later kept it out')
    d.suricata_weigh([alert(roam, 30, 'ET SCAN Potential SSH Scan', category='Attempted Information Leak'),
                      alert(roam, 20, 'ET SCAN Potential SSH Scan 2', category='Attempted Information Leak'),
                      alert(roam, 10, 'ET SCAN Potential SSH Scan 3', category='Attempted Information Leak'),
                      alert(roam, 1, 'ET SCAN Potential SSH Scan 4', category='Attempted Information Leak')])
    check(not blocked(roam) and not any(k.startswith('ids-') for k in kinds_of(roam)),
          'packets nobody answered - four SYN-only alerts "from" the house\'s phone were weighed '
          'against it: anybody can write its address on a packet')
    d.full_weigh([full(roam, 1, path='/.git/config', status=404, host=NTFY, which='ntfy')])
    check('proxy-secret-hunt' in kinds_of(roam), 'the house asking for .git/config - is still weighed')
    fresh()
    stranger = '91.240.118.51'
    d.full_weigh([full(stranger, 60, path='/house-topic/json', status=200, host=NTFY,
                       agent='TruffleHog', which='ntfy', auth='sent')])
    d.proxy_weigh([access(stranger, 30 - n * 4, 'GET / HTTP/1.1', 444) for n in range(6)])
    check(blocked(stranger), 'a credential checker whose found password works - became the house')

    # 5. Suricata's reputation rules.
    print('5. an address on a list Suricata carries, that then does something here')
    fresh()
    listed = '45.148.10.77'
    d.suricata_weigh([alert(listed, 40, 'ET CINS Active Threat Intelligence Poor Reputation IP group 63')])
    check(not blocked(listed), 'listed and nothing else - kept out for the packet alone')
    d.proxy_weigh([access(listed, 39, 'GET / HTTP/1.1', 444)])
    check(blocked(listed),
          'listed and asking for the machine by its address - weighed 4 + 4 and let go, as 64 such '
          'addresses were in these logs')
    check(listed_by(listed) == 'CINS', 'which list - %r' % listed_by(listed))
    other = '45.148.10.78'
    d.suricata_weigh([alert(other, 40, 'ET DROP Spamhaus DROP Listed Traffic Inbound group 13')])
    check(listed_by(other) == 'Spamhaus DROP' and 'ids-listed' in kinds_of(other),
          'Spamhaus DROP - is not read as a list')
    check(listed_by('91.240.118.52') == '' and list_name('ET SCAN Zmap User-Agent') == '',
          'a rule that is not a list - was read as one')
    check(zigmon.Daemon.ANOMALY_WEIGHT.get('ids-listed', 99) < 15 / 3,
          'the listed alert alone - weighs a block once tripled')

    # 6. One tool, many addresses.
    print('6. the same unmistakable path from three addresses in a minute')
    fresh()
    pool = ['37.27.%d.%d' % (40 + n, 11 + n) for n in range(3)]   # three different networks
    for n, ip in enumerate(pool[:2]):
        d.proxy_weigh([access(ip, 50 - n * 7, 'GET /xmlrpc.php HTTP/1.1', 444)])
    check(not any(blocked(ip) for ip in pool[:2]), 'two addresses - are already a round (they are not)')
    d.proxy_weigh([access(pool[2], 30, 'GET /xmlrpc.php HTTP/1.1', 444)])
    check(all(blocked(ip) for ip in pool),
          'a round from three addresses - one request each, so none of them was ever kept out: %r'
          % [blocked(ip) for ip in pool])
    check('proxy-swarm' in zigmon.Daemon.STRONG_KINDS, 'the round - is not remembered for the week')

    # 7. Asked for at the house's own name.
    print('7. .env asked for at the house\'s own name')
    fresh()
    aimer, walker = '193.32.162.40', '193.32.163.41'
    d.proxy_weigh([access(aimer, 20, 'GET /.env HTTP/2.0', 404)])
    check(blocked(aimer),
          'one .env at the one-tap name - the name is written down nowhere but the house\'s phones, and '
          'one ask there weighed the same as one ask at an address being walked')
    d.proxy_weigh([access(walker, 20, 'GET /.env HTTP/1.1', 444)])
    check(not blocked(walker), 'one .env at an address being walked - is still not a block on its own')
    fresh()
    d.full_weigh([full(aimer, 20, path='/.git/config', status=404, host=NTFY, which='ntfy')])
    check(blocked(aimer), 'one .git/config at the notification server\'s name - was not a block')

    # 8. Tools that say what they are, which the lists did not know.
    print('8. the tools these logs added')
    check(zigmon.Daemon._leak_checker('kingfisher/2.7.0 Mozilla/5.0 (Windows NT 10.0)'),
          'Kingfisher - a credential checker like TruffleHog, not recognised as one')
    for agent in ('Mozilla/5.0 (compatible; TernCrawler/1.0)', 'ipbase-scanner (+https://ipbase.example/)',
                  'Mozilla/5.0 (compatible; GenomeCrawlerd/1.0)', 'ApcosysBot/1.0', 'RootEvidence/1.0',
                  'fasthttp', 'Mozilla/5.0 (compatible; InternetData.io/1.0)'):
        check(zigmon.Daemon._scanning_tool(agent), '%s - is not read as a scanning tool' % agent)
    for agent in (PREVIEW, 'ntfy/1.7.0 (build 9; iOS 27.2.0)', 'Python-urllib/3.14',
                  'BackgroundShortcutRunner/5114.0.6.300.100 CFNetwork/3896.200'):
        check(not zigmon.Daemon._scanning_tool(agent), '%s - is taken for a scanning tool' % agent[:40])

    # 9. A request line that is another protocol.
    print('9. RTSP and ICAP at the web port are not pages')
    fresh()
    d.proxy_weigh([access('80.94.95.20', 9, 'OPTIONS / RTSP/1.0', 400, '-'),
                   access('80.94.95.21', 9, 'REQMOD icap://icap.example/x ICAP/1.0', 400, '-')])
    check('proxy-junk' in kinds_of('80.94.95.20') and 'proxy-junk' in kinds_of('80.94.95.21'),
          'another protocol - was weighed as a knock or a method: %r %r'
          % (kinds_of('80.94.95.20'), kinds_of('80.94.95.21')))
    d.proxy_weigh([access('80.94.95.22', 9, 'GET / HTTP/1.1', 400)])
    check('proxy-junk' not in kinds_of('80.94.95.22'), 'plain HTTP - was read as another protocol')

    # 10. One request counted once.
    print('10. bytes that are no request count once, not twice')
    fresh()
    junk = '80.94.95.23'
    d.proxy_weigh(['%s - - [%s] "\\x03\\x00\\x00/*\\xE0\\x00\\x00\\x00\\x00\\x00Cookie: mstshash=x" 400 157 "-" "-"'
                   % (junk, stamp(8))])
    d.full_weigh([full(junk, 8, method='', path='', status=400, agent='')])
    check(kinds_of(junk) == ['proxy-junk'],
          'one RDP handshake - weighed as junk by one reader and as an odd method by the other: %r'
          % kinds_of(junk))
    fresh()
    d.full_weigh([full('80.94.95.24', 8, method='PROPFIND', path='/', status=405)])
    check('proxy-odd-method' in kinds_of('80.94.95.24'), 'a method that was written - is no longer weighed')

    # 11. The replay: a sample in the shape of the logs, through the reader.
    print('11. a sample of the logs, through the reader of the server in front')
    fresh()
    zigmon.CONFIG.update({'proxy_watch': 1, 'proxy_full_watch': 1, 'proxy_full_log': '/x/tap-full.log',
                          'ntfy_full_log': '/x/ntfy-full.log', 'ntfy_watch': 1, 'ntfy_log': '',
                          'suricata_watch': 1, 'suricata_log': '/x/eve.json', 'ntfy_own_watch': 0,
                          'proxy_error_log': '/x/error.log', 'proxy_host': '185.230.4.17'})
    house_phone, house_watch, house_lan = '172.226.40.90', '146.70.11.30', '192.168.77.35'
    swarm = ['5.181.%d.%d' % (80 + n, 20 + n) for n in range(4)]
    LOGS = {
        'proxy_log': (
            # the owner sends the link in iMessage; the preview fetches it
            [access(house_watch, 590 - n, p, 404, PREVIEW if p.startswith('GET / ') else ICONS)
             for n in range(3) for p in ('GET / HTTP/2.0', 'GET /apple-touch-icon.png HTTP/2.0',
                                         'GET /apple-touch-icon-precomposed.png HTTP/2.0',
                                         'GET /favicon.ico HTTP/2.0')]
            # the house's own certificate check, at a name this server does not carry
            + [access(house_lan, 560 - n, 'GET /.well-known/acme-challenge/p%02d HTTP/1.1' % n, 444,
                      'acme-http01-check') for n in range(60)]
            # the phone on the move, opening the address by hand while the link is changed
            + [access(house_phone, 400 - n * 20, 'GET / HTTP/2.0', 444) for n in range(5)]
            # the WordPress round, from four networks in half a minute
            + [access(ip, 300 - n * 7, 'GET /%s HTTP/1.1' % ('xmlrpc.php' if n % 2 else 'wp-login.php'), 444)
               for n, ip in enumerate(swarm)]
            + [access(swarm[0], 299, 'GET /xmlrpc.php HTTP/1.1', 444),
               access(swarm[2], 285, 'GET /xmlrpc.php HTTP/1.1', 444)]
            # listed, then one look by address
            + [access('45.148.10.90', 250, 'GET / HTTP/1.1', 444)]
            # .env at the one-tap name, once
            + [access('193.32.162.50', 200, 'GET /.env HTTP/2.0', 404)]
            # .env by address, once: still not a block on its own
            + [access('193.32.163.51', 190, 'GET /.env HTTP/1.1', 444)]
            # a research crawler that names itself, one visit
            + [access('204.76.203.30', 180, 'GET / HTTP/1.1', 444, 'Mozilla/5.0 (compatible; TernCrawler/1.0)')]
            # a press that was let in
            + [access(house_watch, 100, 'POST /tap HTTP/2.0', 200,
                      'BackgroundShortcutRunner/5114.0.6.300.100 CFNetwork/3896.200')]),
        'proxy_full_log': [
            full(house_watch, 100, method='POST', path='/tap', status=200, host=NAME, secret='sent',
                 agent='BackgroundShortcutRunner/5114.0.6.300.100 CFNetwork/3896.200')],
        'ntfy_full_log': [
            full(house_phone, 500 - n * 60, path='/house-topic/json?poll=1&id=x%d' % n, status=200,
                 host=NTFY, agent='ntfy/1.7.0 (build 9; iOS 27.2.0)', which='ntfy', auth='sent',
                 secret='sent') for n in range(5)],
        'suricata_log': [alert('45.148.10.90', 251, 'ET DROP Dshield Block Listed Source group 1'),
                         alert('45.148.10.91', 240, 'ET CINS Active Threat Intelligence Poor Reputation IP group 5'),
                         alert(house_phone, 50, 'ET SCAN Potential SSH Scan', category='Attempted Information Leak'),
                         alert(house_phone, 20, 'ET SCAN Potential SSH Scan', category='Attempted Information Leak')],
        'proxy_error_log': [
            '%s [crit] 949#949: *623 SSL_do_handshake() failed (SSL: error:0A00006C:SSL routines::bad key '
            'share) while SSL handshaking, client: 64.226.80.10, server: 0.0.0.0:443'
            % time.strftime('%Y/%m/%d %H:%M:%S', time.localtime(time.time() - 120))],
    }
    real_named = d.proxy_read_named
    d.proxy_read_named = lambda setting, mark: list(LOGS.get(setting, []))
    try:
        d.proxy_sweep()
    finally:
        d.proxy_read_named = real_named
    want = {house_watch: False, house_phone: False, house_lan: False,
            '45.148.10.90': True, '45.148.10.91': False, '193.32.162.50': True, '193.32.163.51': False,
            '204.76.203.30': False, '64.226.80.10': False}
    want.update({ip: True for ip in swarm})
    for ip, should in sorted(want.items()):
        check(blocked(ip) == should, 'the replay: %s - %s, and it was %s (%r)'
              % (ip, 'should be kept out' if should else 'should be left alone',
                 'kept out' if blocked(ip) else 'left alone', kinds_of(ip)))
    print('  the replay kept out %d of %d addresses' % (sum(blocked(ip) for ip in want), len(want)))
finally:
    shutil.rmtree(str(W), ignore_errors=True)

print('review545_block: %s' % ('%d failed' % len(bad) if bad else 'all good'))
os._exit(1 if bad else 0)
