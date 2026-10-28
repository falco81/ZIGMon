#!/usr/bin/env python3
"""The machine itself (5.21): its network, its clock, restarting it - and a
change that could cut the house off, kept on trial.

  * root (deploy/zigmon_root.py) reads the network and puts a new one in
    through NetworkManager - by hand or from DHCP, IPv6 off, automatic or by
    hand - with the host name and /etc/hosts, then asks for a restart; every
    value checked again, a connection name with a newline in it refused, and
    an asking file that is a folder or a link taken away rather than looped
    on; the clock: chrony.conf given zigmon's block and put back byte for
    byte, a time zone that is a path refused;
  * the daemon follows a new network through the restart (a fake kernel boot
    time): back up with its address it waits to be kept; kept, it is done;
    not kept in time, or come up without the address, the old network is
    asked for again - from DHCP as well;
  * the firewall saved is on trial, and not kept it goes back by itself;
  * a restart now, or at an hour of the house's own clock, called off as
    easily; a regular one once a week;
  * the roads are an administrator's: a visitor, a read-only account and an
    operator are refused, and the page has the three new sections.

    python3 test/system.py

Fakes nmcli, hostnamectl, ip, chronyc and timedatectl by small scripts; never
touches the machine's own network or clock.
"""
import importlib.util
import json
import os
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-system-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


# ---- a machine of fakes -------------------------------------------------------------
STATE = W / 'state'
(STATE / 'root').mkdir(parents=True)
BIN = W / 'bin'
BIN.mkdir()
CALLS = W / 'calls.log'
NM = W / 'nm.json'           # what the fake NetworkManager holds
NM.write_text(json.dumps({'ipv4.method': 'manual', 'ipv4.addresses': '192.168.1.20/24',
                          'ipv4.gateway': '192.168.1.1', 'ipv4.dns': '192.168.1.1',
                          'ipv4.dns-search': '', 'ipv6.method': 'disabled', 'ipv6.addresses': '',
                          'ipv6.gateway': '', 'ipv6.dns': ''}))


def fake(name, body):
    p = BIN / name
    p.write_text('#!%s\nimport json, sys\nCALLS = %r\nNM = %r\n'
                 'open(CALLS, "a").write(json.dumps([%r] + sys.argv[1:]) + "\\n")\n%s'
                 % (sys.executable, str(CALLS), str(NM), name, body))
    p.chmod(0o755)
    return str(p)


NMCLI = fake('nmcli', r'''
a = sys.argv[1:]
nm = json.load(open(NM))
if a[:3] == ['-t', '-g', 'NAME']:
    print('Wired connection 1')
elif a[:2] == ['-t', '-g'] and 'show' in a:
    for f in a[2].split(','):
        print(nm.get(f, '').replace(':', '\\:'))
elif a[:3] == ['-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION']:
    print('eth0:ethernet:connected:Wired connection 1')
    print('lo:loopback:connected (externally):lo')
elif a[:2] == ['connection', 'modify']:
    rest = a[3:]
    for k, v in zip(rest[::2], rest[1::2]):
        nm[k] = v
    json.dump(nm, open(NM, 'w'))
else:
    sys.exit(2)
''')
HOSTNAMECTL = fake('hostnamectl', r'''
if sys.argv[1:] == ['--static']:
    print('old.example.cz')
''')
IP = fake('ip', r'''
a = sys.argv[1:]
nm = json.load(open(NM))
if a[:3] == ['-o', 'addr', 'show']:
    addr = nm.get('ipv4.addresses') or '10.0.0.77/24'
    print('2: eth0    inet %s brd 192.168.1.255 scope global eth0' % addr)
elif a[:3] == ['-4', 'route', 'show']:
    print('default via %s dev eth0 proto static' % (nm.get('ipv4.gateway') or '10.0.0.1'))
''')
CHRONYC = fake('chronyc', r'''
a = sys.argv[1:]
if a == ['-c', 'tracking']:
    print('C0A80101,ntp.example.cz,3,1793300000.0,-0.000120,0.0001,0.0002,-12.5,0.1,0.02,0.0300,0.0010,64.0,Normal')
elif a == ['-c', 'sources']:
    print('^,*,ntp.example.cz,2,6,377,12,-0.000100,-0.000110,0.000200')
elif a == ['makestep']:
    print('200 OK')
''')
TIMEDATECTL = fake('timedatectl', r'''
a = sys.argv[1:]
if a == ['show']:
    print('Timezone=Europe/Prague\nNTP=yes\nNTPSynchronized=yes')
elif a[:1] == ['list-timezones']:
    print('Europe/Prague\nEurope/London\nUTC')
elif a[:3] == ['show', '-p', 'Timezone']:
    print('Europe/Prague')
''')
HOSTS = W / 'hosts'
HOSTS.write_text('127.0.0.1 localhost\n192.168.1.20 old.example.cz old\n')
RESOLV = W / 'resolv.conf'
RESOLV.write_text('nameserver 192.168.1.1\n')
POWER = W / 'power.log'
CHRONY = W / 'chrony.conf'
CHRONY_TEXT = 'driftfile /var/lib/chrony/drift\npool 2.almalinux.pool.ntp.org iburst\nmakestep 1.0 3\nrtcsync\n'
CHRONY.write_text(CHRONY_TEXT)
os.environ.update({'ZIGMON_STATE': str(STATE), 'ZIGMON_ROOT_OWN': str(W / 'own'),
                   'ZIGMON_NMCLI': NMCLI, 'ZIGMON_HOSTNAMECTL': HOSTNAMECTL, 'ZIGMON_IP_CMD': IP,
                   'ZIGMON_HOSTS_FILE': str(HOSTS), 'ZIGMON_RESOLV': str(RESOLV),
                   'ZIGMON_POWER_CMD': str(POWER), 'ZIGMON_CHRONYC': CHRONYC,
                   'ZIGMON_TIMEDATECTL': TIMEDATECTL, 'ZIGMON_CHRONY_CONF': str(CHRONY),
                   'ZIGMON_NO_SERVICES': '1', 'ZIGMON_USER': 'root', 'ZIGMON_FS_ROOT': str(W)})
(W / 'etc' / 'sysctl.d').mkdir(parents=True)

spec = importlib.util.spec_from_file_location('zigmon_root', str(HERE / 'deploy' / 'zigmon_root.py'))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


def ask_root(name, req):
    (STATE / 'root' / name).write_text(json.dumps(req))
    R.serve()
    return json.loads((STATE / 'root' / name.replace('.ask', '.json')).read_text())


# ---- root: the network ------------------------------------------------------------------
print('root reads the network, and puts a new one in')
got = ask_root('net.ask', {'id': 'r1', 'do': 'read'})
d = got.get('data') or {}
check(got.get('ok') and got.get('id') == 'r1', 'the network was not read: %r' % got)
check(d.get('con') == 'Wired connection 1' and d.get('dev') == 'eth0', 'the connection was not found: %r' % d)
check((d.get('conf') or {}).get('ipv4_addresses') == ['192.168.1.20/24'], 'the address set by hand was not read')
check(d.get('hostname') == 'old.example.cz', 'the host name was not read')
check(not (STATE / 'root' / 'net.ask').exists(), 'the asking file was left behind')
got = ask_root('net.ask', {'id': 'r2', 'do': 'apply', 'con': 'Wired connection 1',
                           'ipv4': {'addr': '192.168.1.30/24', 'gw': '192.168.1.1', 'dns': ['1.1.1.1']},
                           'ipv6': {'mode': 'off'}, 'hostname': 'new.example.cz',
                           'old': ['192.168.1.20'], 'old_hostname': 'old.example.cz', 'reboot_in': 8})
nm = json.loads(NM.read_text())
check(got.get('ok') and nm['ipv4.addresses'] == '192.168.1.30/24' and nm['ipv4.method'] == 'manual',
      'the new address was not put in: %r %r' % (got, nm))
check((got.get('data') or {}).get('before', {}).get('ipv4.addresses') == '192.168.1.20/24',
      'what was there before is not handed back for going back to')
hosts = HOSTS.read_text()
check('192.168.1.30 new.example.cz new' in hosts and 'old.example.cz' not in hosts and 'localhost' in hosts,
      '/etc/hosts was not given the new line, or kept the old one: %r' % hosts)
check((W / 'hosts.zigmon-before').read_text().startswith('127.0.0.1 localhost\n192.168.1.20'),
      'the old /etc/hosts was not kept beside it')
check('reboot 8' in POWER.read_text(), 'no restart was asked for after the change')
calls = [json.loads(l) for l in CALLS.read_text().splitlines()]
check(['hostnamectl', 'set-hostname', 'new.example.cz'] in calls, 'the host name was not set')
# from DHCP: no address, no gateway, the router's DNS unless some are given
got = ask_root('net.ask', {'id': 'r3', 'do': 'apply', 'con': 'Wired connection 1',
                           'ipv4': {'method': 'auto'}, 'ipv6': {'mode': 'auto'}, 'hostname': 'new.example.cz'})
nm = json.loads(NM.read_text())
check(got.get('ok') and nm['ipv4.method'] == 'auto' and nm['ipv4.addresses'] == '' and
      nm['ipv4.ignore-auto-dns'] == 'no' and nm['ipv6.method'] == 'auto',
      'DHCP was not put in as it should be: %r %r' % (got, nm))
check((W / 'etc' / 'sysctl.d' / '90-zigmon-ipv6.conf').is_file(), 'IPv6 switched on left the kernel switch off')
for req, why in (({'con': 'Wired\nconnection 1', 'ipv4': {'addr': '192.168.1.30/24'}}, 'a newline in the name'),
                 ({'con': 'Wired connection 1', 'ipv4': {'addr': '192.168.1.30'}}, 'no prefix'),
                 ({'con': 'Wired connection 1', 'ipv4': {'addr': '192.168.1.30/24', 'gw': '10.0.0.1'}},
                  'a gateway outside'),
                 ({'con': 'Wired connection 1', 'ipv4': {'addr': '192.168.1.30/24', 'dns': ['1.1.1.1;reboot']}},
                  'a DNS server that is a command'),
                 ({'con': 'No such', 'ipv4': {'addr': '192.168.1.30/24'}}, 'a connection that is not there'),
                 ({'con': 'Wired connection 1', 'ipv4': {'addr': '192.168.1.30/24'}, 'hostname': 'a b.cz'},
                  'a host name with a space')):
    got = ask_root('net.ask', dict(req, id='bad', do='apply'))
    check(not got.get('ok'), 'root took %s: %r' % (why, got))
got = ask_root('net.ask', {'id': 'p1', 'do': 'power', 'how': 'poweroff', 'in': 5})
check(got.get('ok') and 'poweroff 5' in POWER.read_text(), 'a power-off was not asked for')
got = ask_root('net.ask', {'id': 'p2', 'do': 'power', 'how': 'rm -rf'})
check(not got.get('ok'), 'root took a power word it does not know')
# an asking file that is not a file is taken away, not looped on
(STATE / 'root' / 'net.ask').mkdir()
R.serve()
check(not (STATE / 'root' / 'net.ask').exists(), 'a folder named net.ask was left, and the unit would loop')
os.symlink(str(W / 'hosts'), str(STATE / 'root' / 'net.ask'))
R.serve()
check(not os.path.lexists(str(STATE / 'root' / 'net.ask')) and HOSTS.read_text().startswith('127.0.0.1'),
      'a link named net.ask was followed or left')

# ---- root: the clock --------------------------------------------------------------------
print('root sets the time servers, and puts the file back as it was')
got = ask_root('ntp.ask', {'id': 't1', 'do': 'read', 'zones': True})
d = got.get('data') or {}
check(got.get('ok') and d.get('tracking', {}).get('stratum') == 3 and d.get('sources')
      and d['sources'][0]['reach'] == 255 and 'Europe/Prague' in d.get('zones', []),
      'the clock was not read: %r' % got)
got = ask_root('ntp.ask', {'id': 't2', 'do': 'apply', 'manage': True, 'makestep': [1.0, 3],
                           'servers': [{'host': 'tik.cesnet.cz', 'iburst': True, 'nts': True}],
                           'allow': ['192.168.1.0/24'], 'timezone': 'Europe/Prague'})
text = CHRONY.read_text()
check(got.get('ok') and '#zigmon# pool 2.almalinux.pool.ntp.org iburst' in text and
      'server tik.cesnet.cz iburst nts' in text and 'allow 192.168.1.0/24' in text,
      'the time servers were not put in: %r\n%s' % (got, text))
got = ask_root('ntp.ask', {'id': 't3', 'do': 'apply', 'manage': False, 'makestep': [1.0, 3]})
check(got.get('ok') and CHRONY.read_text() == CHRONY_TEXT, 'chrony.conf did not come back byte for byte:\n%s'
      % CHRONY.read_text())
for tz in ('../../etc/shadow', 'Europe/Prague\nx', '/UTC'):
    got = ask_root('ntp.ask', {'id': 't4', 'do': 'apply', 'manage': False, 'timezone': tz})
    check(not got.get('ok'), 'root took the time zone %r' % tz)
got = ask_root('ntp.ask', {'id': 't5', 'do': 'apply', 'manage': True, 'servers': [{'host': 'a;b'}]})
check(not got.get('ok'), 'root took a server name that is not one')

# ---- the daemon ---------------------------------------------------------------------------
print('the daemon follows a new network through the restart, on trial')
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

PORT = 19864
BTIME = W / 'btime'
BTIME.write_text('1000')
os.environ['ZIGMON_BTIME_FILE'] = str(BTIME)
os.environ['ZIGMON_ROOT_RUN'] = '%s -I %s' % (sys.executable, HERE / 'deploy' / 'zigmon_root.py')
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'run' / 'api-token'), 'pin': '', 'plugs': [],
                      'sensors': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(STATE),
                      'public_view': True, 'net_confirm_min': 10, 'fw_confirm_min': 5})
NM.write_text(json.dumps({'ipv4.method': 'manual', 'ipv4.addresses': '192.168.1.20/24',
                          'ipv4.gateway': '192.168.1.1', 'ipv4.dns': '192.168.1.1', 'ipv4.dns-search': '',
                          'ipv6.method': 'disabled', 'ipv6.addresses': '', 'ipv6.gateway': '',
                          'ipv6.dns': ''}))
d = zigmon.Daemon()
d._stop.set()                       # its own loops do nothing: the checks turn the handle
d.net_publish()
try:
    d.net_check({'ipv4': {'addr': '192.168.1.30/24', 'gw': '10.0.0.1'}, 'hostname': 'new.example.cz'})
    check(False, 'a gateway outside the new network was taken')
except ValueError:
    pass
try:
    d.net_check({'ipv4': {'addr': '192.168.1.30/24'}, 'hostname': 'new'})
    check(False, 'a host name that is not a whole name was taken')
except ValueError:
    pass
plan = d.net_check({'ipv4': {'method': 'auto'}, 'hostname': 'new.example.cz'})
check(plan['ipv4']['method'] == 'auto' and any('DHCP' in x for x in plan['plan']), 'DHCP was not planned')
d.net_ask({'ipv4': {'addr': '192.168.1.30/24', 'gw': '192.168.1.1', 'dns': '1.1.1.1'},
           'hostname': 'new.example.cz'}, 'jana')
d.net_tick()
job = d._mj('net:job')
check(job and job['state'] == 'rebooting' and job.get('trial_min') == 10 and
      job['back']['ipv4']['addr'] == '192.168.1.20/24', 'the job did not reach the restart: %r' % job)
check(json.loads(NM.read_text())['ipv4.addresses'] == '192.168.1.30/24', 'root was not asked for the address')
d.net_tick()
check(d._mj('net:job')['state'] == 'rebooting', 'without a restart the job moved on')
BTIME.write_text('2000')                 # the machine restarted
d.net_tick()
job = d._mj('net:job')
check(job['state'] == 'trial' and job['trial_until'] > time.time() + 500,
      'back up with its address, it does not wait to be kept: %r' % job.get('steps', [])[-2:])
check([c['kind'] for c in d.changes_view()] == ['net'], 'the banner does not say what waits')
check(d.net_trial_answer('keep', 'jana') == 'kept', 'keep was not taken')
d.net_tick()
check(d._mj('net:job')['state'] == 'done' and not d.changes_view(), 'kept, it is not done')
# not kept in time: the old network back by itself
d.store.set_meta('net:seen', d._mj('net:job')['id'])
d.net_ask({'ipv4': {'addr': '192.168.1.40/24', 'gw': '192.168.1.1'}, 'hostname': 'new.example.cz'}, 'jana')
d.net_tick()
BTIME.write_text('3000')
d.net_tick()
job = d._mj('net:job')
job['trial_until'] = time.time() - 1
d._mj_put('net:job', job)
d.net_tick()
nm = json.loads(NM.read_text())
job = d._mj('net:job')
check(nm['ipv4.addresses'] == '192.168.1.30/24' and job.get('rollback') and job['state'] == 'rebooting',
      'not kept, the old network was not asked back: %r %r' % (nm['ipv4.addresses'], job.get('steps', [])[-3:]))
BTIME.write_text('4000')
d.net_tick()
check(d._mj('net:job')['state'] == 'done', 'going back is put on trial again, or never ends')
# come up without the new address: back at once, not after the trial
d.net_ask({'ipv4': {'addr': '192.168.1.50/24'}, 'hostname': 'new.example.cz'}, 'jana')
d.net_tick()
nm = json.loads(NM.read_text())
nm['ipv4.addresses'] = '192.168.9.9/24'           # it came up with something else
NM.write_text(json.dumps(nm))
BTIME.write_text('5000')
d.net_tick()
job = d._mj('net:job')
check(job.get('rollback') and json.loads(NM.read_text())['ipv4.addresses'] == '192.168.1.30/24',
      'come up without its address, it did not go back at once')
BTIME.write_text('6000')
d.net_tick()
# from DHCP and back to DHCP
NM.write_text(json.dumps(dict(json.loads(NM.read_text()), **{'ipv4.method': 'auto', 'ipv4.addresses': ''})))
d.net_publish()
back, why = d.net_back_want(d._mj('net:now'))
check(back and back['ipv4'].get('method') == 'auto' and 'addr' not in back['ipv4'],
      'a network from DHCP cannot be gone back to: %r %r' % (back, why))

# ---- the firewall on trial --------------------------------------------------------------
print('the firewall saved is on trial, and goes back by itself')
d.store.set_meta('firewall', json.dumps({'on': False, 'off': [], 'rules': []}))
d.root_apply = lambda *a, **k: None
d.firewall_save({'on': False, 'rules': [{'family': 4, 'proto': 'tcp', 'port': '8080', 'source': '',
                                         'action': 'accept', 'note': 'x'}]}, '192.168.1.5')
trial = d._mj('fw:trial')
check(trial and not trial.get('done') and [c['kind'] for c in d.changes_view()] == ['fw'],
      'the firewall saved is not on trial')
trial['until'] = time.time() - 1
d._mj_put('fw:trial', trial)
d.fw_trial_tick()
check(json.loads(d.store.get_meta('firewall'))['rules'] == [] and d._mj('fw:trial').get('done') == 'back',
      'not kept, the firewall did not go back')
d.firewall_save({'on': False, 'rules': []}, '192.168.1.5')
check(d.fw_trial_answer('keep', 'jana') == 'kept' and not d.changes_view(), 'the firewall could not be kept')

# ---- restarting --------------------------------------------------------------------------
print('a restart now, at an hour, and regularly')
POWER.write_text('')
d.power_ask('reboot', 'jana')
d.power_tick()
check('reboot 5' in POWER.read_text() and d._mj('power:row')['state'] == 'going', 'the restart was not asked of root')
try:
    d.power_ask('reboot', 'jana')
    check(False, 'a second restart was taken while the first was under way')
except ValueError:
    pass
BTIME.write_text('7000')
d.power_tick()
check(d._mj('power:row')['state'] == 'back', 'up again, the restart is not said done')
POWER.write_text('')
later = time.localtime(time.time() + 7200)
plan = d.power_ask('reboot', 'jana', time.strftime('%Y-%m-%d %H:%M', later))
d.power_tick()
check(POWER.read_text() == '' and not d.power_busy(), 'a restart planned for later happened now, or blocks')
check(d.power_cancel('jana') == 'called off' and not d.power_view()['plan'].get('when') or
      d.power_view()['plan'].get('done'), 'a planned restart could not be called off')
for when in ('2020-01-01 04:30', 'tomorrow', '2026-13-45 99:99'):
    try:
        d.power_ask('reboot', 'jana', when)
        check(False, 'a restart was planned for %r' % when)
    except ValueError:
        pass
zigmon.CONFIG.update({'reboot_auto': 'weekly', 'reboot_at': '04:30', 'reboot_day': 3})
nxt = d.power_auto_next(time.mktime((2026, 11, 2, 12, 0, 0, 0, 0, -1)))      # a Monday noon
check(time.strftime('%a %H:%M', time.localtime(nxt)) == 'Wed 04:30', 'the weekly restart is not on its day: %s'
      % time.ctime(nxt))
zigmon.CONFIG['reboot_auto'] = 'off'

# ---- the clock, from the daemon -------------------------------------------------------------
print('the daemon sets the time servers once, and reads the clock')
CHRONY.write_text(CHRONY_TEXT)
d.ntp_save({'manage': True, 'servers': [{'host': 'tik.cesnet.cz'}], 'step_s': 1, 'step_n': 3,
            'minsources': 1, 'allow': '', 'timezone': ''}, 'jana')
d.ntp_tick()
check('server tik.cesnet.cz iburst' in CHRONY.read_text() and d._mj('ntp:applied').get('ok'),
      'the time servers saved were not put in')
before = d._mj('ntp:applied')['at']
d.ntp_tick()
check(d._mj('ntp:applied')['at'] == before, 'the same time servers were put in again and again')
check(d.ntp_problem(d._mj('ntp:now')) == '', 'a clock in step is said to be wrong')
check('not synchronised' in d.ntp_problem({'at': time.time(), 'data': {
    'chrony': True, 'tracking': {'leap': 'Not synchronised', 'stratum': 0}}}), 'a clock out of step is not said')
for b in ({'timezone': '../x'}, {'manage': True, 'servers': []}, {'manage': True, 'servers': [{'host': 'a b'}]},
          {'step_s': 99999}):
    try:
        d.ntp_checked(b)
        check(False, 'the daemon took %r' % b)
    except ValueError:
        pass

# ---- the roads ----------------------------------------------------------------------------
print('the roads are an administrator\'s')
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def call(path, body=None, sess=None):
    h = {'Content-Type': 'application/json', 'X-Zigmon-Token': d.token, 'X-Zigmon-Client': '192.168.40.10'}
    if sess:
        h['X-Zigmon-Session'] = sess
    r = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path), headers=h,
                               data=None if body is None else json.dumps(body).encode(),
                               method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(r, timeout=60) as x:
            return x.status, json.loads(x.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


pw0 = (STATE / 'first-login.txt').read_text().split('password: ')[-1].strip()
T0 = call('/api/auth/login', {'name': 'admin', 'password': pw0})[1]['token']
call('/api/auth/password', {'old': pw0, 'new': 'the admin pass 1'}, T0)
T0 = call('/api/auth/login', {'name': 'admin', 'password': 'the admin pass 1'})[1]['token']
d.account_add('olga', 'operator', 'operator pass 1', must_change=False, by='test')
TO = call('/api/auth/login', {'name': 'olga', 'password': 'operator pass 1'})[1]['token']
for path in ('/api/net', '/api/ntp', '/api/power'):
    check(call(path)[0] == 403, '%s is read by a visitor' % path)
    check(call(path, sess=TO)[0] == 403, '%s is read by an operator' % path)
    check(call(path, sess=T0)[0] == 200, '%s is not read by an administrator' % path)
for path, body in (('/api/power', {'how': 'reboot'}), ('/api/net', {'action': 'read'}),
                   ('/api/change', {'kind': 'fw', 'action': 'back'}), ('/api/ntp', {'action': 'sync'})):
    check(call(path, body)[0] == 403 and call(path, body, TO)[0] == 403,
          '%s is open to a visitor or an operator' % path)
c, r = call('/api/power', {'how': 'reboot', 'when': time.strftime('%Y-%m-%d %H:%M', later)}, T0)
check(c == 200 and r.get('plan', {}).get('by') == 'admin', 'a planned restart from the page did not say who: %r' % r)
c, r = call('/api/power', {'action': 'cancel'}, T0)
check(c == 200, 'the planned restart could not be called off from the page: %r' % r)
c, r = call('/api/change', {'kind': 'net', 'action': 'keep'}, T0)
check(c == 400, 'keeping a network that waits for nothing was not refused')
c, r = call('/api/status')
check('changes' in r and 'server_now' in r, 'the status does not carry what waits to be kept')
for key in ('net_confirm_min', 'fw_confirm_min', 'reboot_auto'):
    try:
        d.object_set('Settings', key, '0', origin='a script')
        check(False, '%s can be changed by a script' % key)
    except ValueError:
        pass

# ---- the page ------------------------------------------------------------------------------
page = (HERE / 'web' / 'index.php').read_text()
nav = page[page.index('id="control-nav"'):page.index('</nav>', page.index('id="control-nav"'))]
for group in ('Security', 'Server', 'Data', 'Monitoring and updates'):
    check('<div class="ctl-group">%s</div>' % group in nav, 'the menu has no group %s' % group)
for sec in ('sys-network', 'sys-time', 'sys-power'):
    check('data-sec="%s"' % sec in nav and "'%s': [" % sec in page, 'the section %s is missing' % sec)
check(nav.index('data-sec="sys-network"') < nav.index('Monitoring and updates') < nav.index('data-sec="sys-upgrade"'),
      'the network is not under Server, or the upgrades not under Monitoring')
check("'net-do' => '/api/net'" in page and "'change-do' => '/api/change'" in page, 'the relay does not carry the roads')
check(stat.S_IMODE(os.stat(str(HERE / 'deploy' / 'zigmon_root.py')).st_mode) & 0o022 == 0,
      'the root helper is writable by others')
unit = (HERE / 'deploy' / 'zigmon-root.path').read_text()
check('PathExists=/var/lib/zigmon/root/net.ask' in unit and 'PathExists=/var/lib/zigmon/root/ntp.ask' in unit,
      'zigmon-root.path does not start root for net.ask and ntp.ask')

# the command is a link to the program (install.sh puts /usr/local/bin/zigmon
# there): root's helper is found beside the program, not beside the link
LINKDIR = W / 'linkbin'
LINKDIR.mkdir()
os.symlink(str(HERE / 'zigmon.py'), str(LINKDIR / 'zigmon'))
import subprocess                                         # noqa: E402
got = subprocess.run([sys.executable, '-c', 'import sys, runpy; sys.argv=[%r]; '
                      'g = runpy.run_path(%r, run_name="x"); print(g["Daemon"].helper_file("zigmon_root.py"))'
                      % (str(LINKDIR / 'zigmon'), str(LINKDIR / 'zigmon'))],
                     capture_output=True, text=True, timeout=60)
check(got.stdout.strip().endswith('deploy/zigmon_root.py') and os.path.isfile(got.stdout.strip()),
      'run through a link, the program looks for root\'s helper beside the link: %r' % (got.stdout + got.stderr)[-300:])

d.store.flush(3.0)
sys.stdout.flush()
if bad:
    print('\n%d check(s) failed' % len(bad))
    os._exit(1)
print('the network, the clock and restarting: asked of root, followed, and kept or taken back')
os._exit(0)
