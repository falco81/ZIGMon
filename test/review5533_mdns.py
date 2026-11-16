#!/usr/bin/env python3
"""5.53.3: mDNS answers are let in, and discover reads the firewall zigmon keeps.

The firewall's mDNS let in only questions TO port 5353. A Shelly box asked for a
unicast answer replies FROM 5353 to the port the question went out of, so
"zigmon shelly discover" heard nothing until a rule by hand let --sport 5353 in.
And discover's advice looked at INPUT alone - zigmon's rules are in ZIGMON-IN -
and told to add rules by hand to a firewall zigmon rewrites.

    python3 test/review5533_mdns.py < /dev/null
"""
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review5533-'))
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

spec = importlib.util.spec_from_file_location('zigmon_root_t', str(HERE / 'deploy' / 'zigmon_root.py'))
root = importlib.util.module_from_spec(spec)
spec.loader.exec_module(root)

bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


# -- root takes a rule by the port an answer comes from -------------------------------
r = root.fw_rule_checked({'family': 4, 'proto': 'udp', 'sport': '5353', 'action': 'accept', 'note': 'mDNS answers'})
check(r.get('sport') == '5353' and not r['port'], 'root dropped the source port: %r' % r)
args = root.fw_args(r)
check('-p udp' in args and '--sport 5353' in args and '--dport' not in args and args.endswith('-j ACCEPT'),
      'the iptables rule: %s' % args)
rr = root.rich(r, 0)
check(rr and 'source-port port="5353" protocol="udp"' in rr[0], 'the firewalld rule: %r' % rr)
for bad_rule in ({'family': 4, 'proto': 'icmp', 'sport': '5353'}, {'family': 4, 'proto': 'udp', 'sport': 'x'},
                 {'family': 4, 'proto': 'udp', 'port': '53', 'sport': '5353'}):
    try:
        root.fw_rule_checked(bad_rule)
        check(False, 'root took %r' % bad_rule)
    except root.Refused:
        pass
check(root.fw_args(root.fw_rule_checked({'family': 4, 'proto': 'tcp', 'port': '22', 'action': 'accept'}))
      .count('--sport') == 0, 'a rule without a source port got one')

# -- the daemon asks for the answers' rule, and only of a helper that knows it ----------
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 20300, 'token_file': str(W / 'token'),
                      'plugs': [], 'sensors': [], 'weather': False, 'state_dir': str(W)})
d = zigmon.Daemon()
try:
    mdns = [x for x in d.fw_auto() if x['key'] == 'mdns'][0]
    sports = [x for x in mdns['rules'] if x.get('sport') == '5353']
    check(len(sports) == 2 and {x['family'] for x in sports} == {4, 6} and all(not x['port'] for x in sports),
          'the mDNS function does not let the answers in: %r' % mdns['rules'])
    for x in mdns['rules']:
        root.fw_rule_checked(x)                       # every one of them taken by root
    old = W / 'zigmon_root.py'
    old.write_text('# a helper from before 5.53.3\nFW_PROTOS = ()\n')
    d.helper_file = lambda name: old
    d.__dict__.pop('_fw_sport', None)
    mdns = [x for x in d.fw_auto() if x['key'] == 'mdns'][0]
    check(not [x for x in mdns['rules'] if x.get('sport')], 'an older helper is handed a rule it would read as all of UDP')
finally:
    try:
        d.store.close()
    except Exception:                                    # noqa: BLE001
        pass

# -- discover's advice reads every chain, and points to zigmon's own switch -------------
pal = zigmon.Palette(False)
real = subprocess.run


def fake(rules):
    def run(argv, *a, **k):
        if argv[:1] == ['iptables']:
            return subprocess.CompletedProcess(argv, 0, rules, '')
        return real(argv, *a, **k)
    return run


ZIG = ('-P INPUT ACCEPT\n-N ZIGMON-IN\n-A INPUT -j ZIGMON-IN\n-A INPUT -j REJECT --reject-with icmp-host-prohibited\n'
       '-A ZIGMON-IN -p udp -m udp --dport 5353 -m comment --comment "zigmon: mDNS" -j ACCEPT\n')
try:
    subprocess.run = fake(ZIG)
    said = ' '.join(zigmon.iptables_diagnosis(pal))
    check('Settings - Firewall' in said and 'answers' in said and 'iptables -I INPUT' not in said,
          'with zigmon\'s firewall letting only questions in, discover says: %s' % said)
    subprocess.run = fake(ZIG + '-A ZIGMON-IN -p udp -m udp --sport 5353 -m comment --comment "zigmon: mDNS answers" -j ACCEPT\n')
    said = ' '.join(zigmon.iptables_diagnosis(pal))
    check('both ways' in said, 'with both rules in zigmon\'s chain, discover says: %s' % said)
finally:
    subprocess.run = real
shutil.rmtree(W, ignore_errors=True)
print('review5533_mdns: ' + ('all good' if not bad else '%d FAILED' % len(bad)))
sys.exit(1 if bad else 0)
