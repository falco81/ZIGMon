#!/usr/bin/env python3
"""5.26: the machine's own sections - Network, Time, Restart and power off,
Backups, About, Upgrades - drawn the way OTP draws them. Every check fails on
5.25.0 and passes since.

    python3 test/review526.py
"""
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review526-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


page = (HERE / 'web' / 'index.php').read_text()


def fn(name):
    m = re.search(r'\nfunction %s\(' % re.escape(name), page)
    if not m:
        return ''
    end = page.find('\nfunction ', m.end())
    return page[m.start():end]


print('the sections look as OTP draws them')
check('net-facts' in page and 'As it is now' in page, 'the network as it is now is not a grid of facts')
check('New settings for' in page, 'the network form is not "New settings for <host>"')
check('IPV6 (DUAL STACK)' in page.upper() and 'Check it' in page, 'the network form has no IPv4/IPv6 boxes and Check it')
check('ntp-off' in page and 'off the time servers' in page, 'the time card has no big offset')
check(re.search(r'\.ot \.ntp-node \.net-fact[^{]*\{[^}]*flex-direction:row', page),
      'the time card\'s facts are not a label and its value on one line')
check(re.search(r'\.ot \.pw-node \.net-fact[^{]*\{[^}]*flex-direction:row', page) or
      re.search(r'\.ot \.ntp-node \.net-fact,\.ot \.pw-node \.net-fact\{[^}]*flex-direction:row', page),
      'the restart card\'s facts are not a label and its value on one line')
check('rb-hero' in page, 'backups to other machines have no status card')
check('--upgrade-online' in page[page.find('id="up-cli-card"'):page.find('id="up-cli-card"') + 2000],
      'the command line card does not say how to upgrade online')
sw = fn('drawConsoleSwitch')
check('save.onclick' in sw and sw.index("post('about-do'") > sw.index('save.onclick'),
      'the console at login is changed on the click, not on Save')

print('the restart card says the address')
sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 0, 'token_file': str(W / 'run' / 'api-token'),
                      'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '',
                      'state_dir': str(W / 'state')})
(W / 'state').mkdir()
d = zigmon.Daemon()
d._mj_put('net:now', {'at': 1, 'data': {'conf': {'ipv4_addresses': ['192.168.1.20/24']}}})
view = d.power_view() if hasattr(d, 'power_view') else {}
check(str(view.get('address') or '').startswith('192.168.1.20'), 'the restart card does not say the machine\'s address: %r'
      % view.get('address'))

sys.stdout.flush()
if bad:
    print('\n%d check(s) failed' % len(bad))
    os._exit(1)
print('the machine\'s sections are drawn as OTP draws them')
os._exit(0)
