#!/usr/bin/env python3
"""5.43.3: keeping addresses out and the network around - the bugs found by
going over the blocking, the router, the logs read from the server in front,
the lists, the country list and the Snort debug tool once more. Every check
here fails on 5.43.2.

    python3 test/hunt5433_net.py

No broker, no web server, no router and no network: the daemon is built
against a database of its own in a folder of its own, the router and the
server in front are a function that answers. Port 19550 (never listened on).
"""
import importlib.util
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-hunt5433-net-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    else:
        print('  ok: ' + what.split(' - ')[0])
    return ok


sys.path.insert(0, os.environ.get('HUNT5433_DAEMON') or str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 19550, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [],
                      'mqtt_host': '', 'log_file': '', 'log_to_journal': False,
                      'state_dir': str(W / 'state'), 'never_block': '', 'block_ladder': '',
                      'block_private': 'gently', 'block_mode': 'temporary', 'blacklist': 1,
                      'block_score': 15, 'block_sensitivity': 'normal', 'feeds_ban': 0,
                      'intel_shodan': 0, 'mikrotik_host': '', 'mikrotik_list': ''})
(W / 'state').mkdir()
d = zigmon.Daemon()
d.notify = lambda *a, **k: None


def fresh():
    d.store.unblock()
    d.forget_anomaly()
    d._blocked_times.clear()


try:
    # 1. A never-kept-out address was kept out by the presses at the API.
    print('1. never kept out means never put on the list')
    fresh()
    zigmon.CONFIG['never_block'] = '89.24.9.9, 45.134.26.0/24'
    for i in range(6):
        d.note_anomaly('89.24.9.9', 'bad-secret', 'guess-%d' % i)
        d.note_anomaly('45.134.26.7', 'shut-road', 'link-%d' % i)
    check(d.store.blocked_until('89.24.9.9') is None,
          'a spared address - a wrong secret five times at the API put an address written under '
          '"never kept out" on the list (announced as blocked, its ladder climbing)')
    check(d.store.blocked_until('45.134.26.7') is None,
          'a spared range - a shut road pressed six times put an address of a spared range on the list')
    check(not d._blocked_times.get('89.24.9.9'),
          'the ladder - a spared address was counted as kept out once more')
    zigmon.CONFIG['never_block'] = ''
    for i in range(6):
        d.note_anomaly('89.24.9.10', 'bad-secret', 'guess-%d' % i)
    check(d.store.blocked_until('89.24.9.10') is not None,
          'a stranger - five wrong secrets from an address nobody spared no longer keep it out')

    # 2. Suricata writes an IPv6 source in full; everything else here does not.
    print('2. one way of writing an IPv6 address')
    fresh()
    zigmon.CONFIG.update({'suricata_least': 2})
    longhand = '2a01:0430:0017:0000:0000:0000:0000:0005'
    alert = {'event_type': 'alert', 'src_ip': longhand, 'dest_port': 443,
             'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S.000000+0000', time.gmtime()),
             'alert': {'severity': 1, 'signature': 'ET EXPLOIT something', 'category': 'Attempted Admin',
                       'signature_id': 1, 'rev': 1}}
    d.suricata_weigh([json.dumps(alert), json.dumps(dict(alert, alert=dict(alert['alert'],
                                                                         signature='ET EXPLOIT other')))])
    check(d.store.blocked_until('2a01:430:17::5') is not None,
          'IPv6 from Suricata - two attacks from 2a01:430:17::5, written in full by Suricata, were '
          'blocked under the long spelling and the door (which is asked in the short one) let it in')
    check(not any(r['ip'] == longhand for r in d.store.blocked_all()),
          'IPv6 from Suricata - the long spelling is what went on the list')
    check(d._ids_about('2a01:430:17::5').get('sid') == 1,
          'IPv6 from Suricata - what Suricata said was kept under a name the list never asks for')
    fresh()
    d.note_anomaly('2A01:430:17::9', 'proxy-secret-hunt', 'GET /.env')
    d.note_anomaly('2a01:430:17:0:0:0:0:9', 'proxy-secret-hunt', 'GET /.git/config')
    check(d.store.blocked_until('2a01:430:17::9') is not None,
          'one address, two spellings - two unmistakable tries from one IPv6 address were counted as '
          'two strangers with one try each')
    check(d.note_anomaly('not-an-address', 'bad-secret', 'x') is None
          and not any(r['ip'] == 'not-an-address' for r in d.store.blocked_all())
          and 'not-an-address' not in d._anomaly,
          'something that is no address - was counted, and could be "blocked"')

    # 3. A house address on a bogon list was weighed as a stranger on a list.
    print('3. the house is on no list')
    fresh()
    zigmon.CONFIG.update({'feeds': 'firehol1', 'feeds_weight': 3, 'feeds_ban': 0})
    d.store.put_feed('firehol1', [zigmon.range_of('192.168.0.0/16'), zigmon.range_of('45.9.148.0/24')])
    d._feed_said = {}
    wanted = d.feed_wanted()
    if 'firehol1' not in wanted:
        d.feed_wanted = lambda: ['firehol1']
    for i in range(3):
        d.note_anomaly('192.168.1.20', 'bad-secret', 'old-shortcut-%d' % i)
    check(d.store.blocked_until('192.168.1.20') is None,
          'a phone of the house - three wrong secrets from 192.168.1.20 kept it out, because FireHOL '
          'level 1 names 192.168.0.0/16 (a bogon) and its tries were weighed three times over')
    check(d.feed_says('45.9.148.9') == 'firehol1',
          'a stranger on the list - is no longer said to be on it')
    fresh()

    # 4. The router went on counting down the old timeout of a block made longer.
    print('4. the router carries a block as long as it lasts here')
    zigmon.CONFIG.update({'mikrotik_host': 'router', 'mikrotik_list': 'zigmon', 'mikrotik_sync': 0})
    sent = []
    d.store.block('89.24.7.7', None, 'kept out for good by hand', auto=False)
    d.store.block('89.24.7.8', time.time() + 3600, 'an hour', auto=True)

    def router(command):
        sent.append(command)
        if 'print terse' in command and command.startswith('/ip '):
            return ('0 D list=zigmon address=89.24.7.7 creation-time=2026-11-06 10:00:00 timeout=9m58s '
                    'comment="zigmon: an hour"\n'
                    '1 D list=zigmon address=89.24.7.8 creation-time=2026-11-06 10:00:00 timeout=59m30s '
                    'comment="zigmon: an hour"\n')
        return ''
    d.mikrotik_run = router
    d.mikrotik_sync('a test')
    check(any('remove' in c and '89.24.7.7' in c for c in sent)
          and any('address-list add' in c and '89.24.7.7' in c and 'timeout' not in c for c in sent),
          'a block made for good - the router was left counting down the ten minutes it was first '
          'given, and let the address in when they ran out')
    check(not any('89.24.7.8' in c for c in sent if 'print' not in c),
          'a block the router already carries for as long - was taken off and put back for nothing')
    seconds = getattr(zigmon.Daemon, 'mikrotik_seconds', lambda line: -1)
    check(seconds('a timeout=1d02:03:04 b') == 93784
          and seconds('timeout=00:09:58') == 598 and seconds('timeout=1w2d3h') == 788400
          and seconds('list=zigmon address=1.2.3.4') is None,
          'the timeouts a router prints - read wrong')
    d.store.unblock()
    zigmon.CONFIG.update({'mikrotik_host': '', 'mikrotik_list': ''})

    # 5. The country of an address past the first /8 (or /16) of a wide range.
    print('5. the country of every address in a wide range')
    packed = zigmon.pack_address
    d.store.put_geo([(packed('28.0.0.0')[0], packed('30.255.255.255')[0], 4, 'US'),
                     (packed('2600::')[0], packed('260f:ffff:ffff:ffff:ffff:ffff:ffff:ffff')[0], 6, 'US'),
                     (packed('31.0.0.0')[0], packed('31.0.0.255')[0], 4, 'CZ')])
    check(d.store.country_of('29.1.2.3') == 'US' and d.store.country_of('30.255.0.1') == 'US',
          'a wide IPv4 range - db-ip writes 28.0.0.0 to 30.255.255.255 as one row, and every address '
          'past 28.255.255.255 had no country')
    check(d.store.country_of('2601:1:2::3') == 'US',
          'a wide IPv6 range - an address past the first /16 of 2600::/12 had no country')
    check(d.store.country_of('31.0.0.9') == 'CZ' and d.store.country_of('31.0.1.9') is None
          and d.store.country_of('27.0.0.1') is None,
          'the ranges - an address between two ranges was given one of them')

    # 6. The Snort debug tool: no false name, no token in what it prints.
    print('6. tools/snort-debug.py')
    TOOL = Path(os.environ.get('HUNT5433_DAEMON') or str(HERE)) / 'tools' / 'snort-debug.py'
    spec = importlib.util.spec_from_file_location('snortdebug', str(TOOL))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    source = TOOL.read_text()
    check('curl/' not in source,
          'the User-Agent - it asked for the public address calling itself curl')

    class Answer(object):
        status = 403

        def __init__(self):
            from email.message import Message
            self.headers = Message()
            self.headers['Location'] = 'https://www.snort.org/?__cf_chl_rt_tk=SECRETTOKEN1'

        def geturl(self):
            return 'https://www.snort.org/downloads/ip-block-list?__cf_chl_tk=SECRETTOKEN2'
    page = ('<html><title>Just a moment</title><form id="challenge-form" '
            'action="/downloads/ip-block-list?__cf_chl_f_tk=SECRETTOKEN3" method="POST"></form></html>')
    said = io.StringIO()
    with redirect_stdout(said):
        tool.show('a step', Answer(), 0.1, page)
    check('SECRETTOKEN' not in said.getvalue(),
          'a Cloudflare challenge - its tokens (final address, Location, the form) were printed into '
          'what the owner is asked to send back')
    check('snort.org' in said.getvalue(), 'what it prints - the addresses were dropped altogether')

    # 7. The firewall pane: HTTPS switched off with no rule of one's own.
    print('7. the firewall does not shut out the page it is saved from')
    conf = {'on': True, 'off': ['web'], 'rules': []}
    check(bool(d.fw_lockout(conf, None, '89.24.5.7')),
          'the web switched off - HTTP / HTTPS off and no rule for 443 was saved without a word, and '
          'the dashboard it was saved from stopped answering')
    check(d.fw_lockout({'on': True, 'off': [], 'rules': []}, None, '89.24.5.7') is None
          and d.fw_lockout({'on': True, 'off': ['web'], 'rules': [
              {'family': 0, 'proto': 'tcp', 'port': '443', 'source': '', 'action': 'accept'}]},
              None, '89.24.5.7') is None,
          'the web left on, or a rule of ones own for 443 - refused as a lockout')

    # 8. ssh: a user name is not an option.
    print('8. what is handed to ssh')
    try:
        zigmon._ssh_argv({'ssh_user': '-oProxyCommand=touch /tmp/x;#'}, 'router')
        took = True
    except RuntimeError:
        took = False
    check(not took, 'an ssh user beginning with a dash - was handed to ssh, which read it as '
                    '-o ProxyCommand and ran it on this machine')
    argv = zigmon._ssh_argv({'ssh_user': 'admin', 'ssh_port': 22}, '192.168.1.1')
    check(argv[-1] == 'admin@192.168.1.1' and zigmon._ssh_argv({'ssh_user': 'zig.mon-1'},
                                                               'fe80::1%eth0')[-1] == 'zig.mon-1@fe80::1%eth0',
          'an ordinary user and address - refused')

    # 10. The end of the ladder is "for good" - but never for the house.
    print('10. the house is never kept out for good')
    fresh()
    d.feed_wanted = lambda: []
    zigmon.CONFIG.update({'block_ladder': '10, 60, forever', 'block_private': 'gently'})
    d._blocked_times['192.168.1.30'] = 5           # it has tripped the guard before
    for i in range(12):
        d.note_anomaly('192.168.1.30', 'bad-secret', 'stale-%d' % i)
    until = d.store.blocked_until('192.168.1.30')
    check(until is not None and until > 0,
          'a phone of the house at the end of the ladder - "gently" says the family is never shut out '
          'for good, and it was kept out for good')
    ahead = d.block_ahead('192.168.1.30', d._anomaly.get('192.168.1.30') or [(time.time(), 'bad-secret', 'x')])
    check(not ahead.get('forever'), 'what the card says is ahead - "for good" for a phone of the house')
    d._blocked_times['89.24.60.9'] = 5
    for i in range(6):
        d.note_anomaly('89.24.60.9', 'bad-secret', 'guess-%d' % i)
    check(d.store.blocked_until('89.24.60.9') == 0,
          'a stranger at the end of the ladder - is no longer kept out for good')
    zigmon.CONFIG['block_ladder'] = ''
    fresh()

    # 11. The servers in front, written the way the box beside them is read.
    print('11. trusted_proxies written with spaces')
    zigmon.CONFIG['trusted_proxies'] = '10.0.0.5 10.0.0.6'
    check(d.caller_of('10.0.0.6', '89.24.5.7, 10.0.0.5') == '89.24.5.7',
          'two servers on one line - "10.0.0.5 10.0.0.6" trusted neither, and every caller was the '
          'server in front')
    check(d.caller_of('89.24.1.1', '1.2.3.4') == '89.24.1.1',
          'a stranger saying who it speaks for - was believed')
    zigmon.CONFIG['trusted_proxies'] = ''

    # 9. The meter switched off while its thread was reading.
    print('9. the performance meter, switched off mid-reading')
    kept = []
    zigmon.CONFIG['perf_meter'] = 1
    real_read = zigmon.perf_read
    zigmon.PERF_STORE = type('S', (), {'perf_keep': lambda self, *a: kept.append(a),
                                       'perf_drop': lambda self: kept.clear()})()
    real_read()
    time.sleep(0.25)

    def read_then_off():
        out = real_read()
        zigmon.CONFIG['perf_meter'] = 0             # the switch, pressed while this was reading
        zigmon.perf_forget()
        return out
    zigmon.perf_read = read_then_off
    with zigmon.PERF_WATCH_LOCK:
        zigmon.PERF_WATCH['asked'] = time.time()
        zigmon.PERF_WATCH['stop'] = __import__('threading').Event()
    zigmon._perf_watcher()
    zigmon.perf_read = real_read
    zigmon.PERF_STORE = None
    check(not kept, 'the row of the node - written back after the meter was switched off and its row '
                    'taken away, so it stayed with the meter off')
finally:
    shutil.rmtree(str(W), ignore_errors=True)

print('hunt5433_net: %s' % ('%d failed' % len(bad) if bad else 'all good'))
os._exit(1 if bad else 0)
