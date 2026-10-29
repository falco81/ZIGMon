#!/usr/bin/env python3
"""The faults a read through the whole application found for 5.24, each one
proved on its own: every check here fails on 5.23.0 and passes since.

    python3 test/review524.py

No broker, gateway, web server or root is needed: the daemon is built in
this process and what it would ask of root is stood in for.
"""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review524-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': 0, 'token_file': str(W / 'run' / 'api-token'),
                      'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '',
                      'state_dir': str(W / 'state'), 'net_confirm_min': 10, 'fw_confirm_min': 5})
(W / 'state').mkdir()
d = zigmon.Daemon()

# ---- the machine itself ---------------------------------------------------------------
print('the network, the firewall on trial, the clock and restarts')
d._mj_put('net:now', {'at': time.time(), 'data': {
    'nm': True, 'con': 'eth0', 'devices': [{'con': 'eth0', 'dev': 'eth0'}], 'hostname': 'raspberrypi',
    'conf': {'ipv4_method': 'manual', 'ipv4_addresses': ['192.168.1.20/24'], 'ipv4_gateway': '192.168.1.1',
             'ipv4_dns': ['192.168.1.1']},
    'live': {'addrs4': [{'dev': 'eth0', 'addr': '192.168.1.20/24'}]}}})
back, why = d.net_back_want(d._mj('net:now'))
try:
    d.net_check(back)
    ok = True
except ValueError as e:
    ok = False
    print('   ', e)
check(ok, 'a machine called by a short name cannot be put back to the network it had')
try:
    d.net_check({'con': 'eth0', 'ipv4': {'method': 'manual', 'addr': '192.168.1.30/24', 'gw': '192.168.1.1'}})
    ok = True
except ValueError:
    ok = False
check(ok, 'a machine called by a short name cannot have a new address without a new name')
try:
    d.net_check({'con': 'eth0', 'hostname': 'other',
                 'ipv4': {'method': 'manual', 'addr': '192.168.1.30/24', 'gw': '192.168.1.1'}})
    ok = False
except ValueError:
    ok = True
check(ok, 'a new short host name is let through')

d._mj_put('net:job', {'id': 'j1', 'state': 'trial', 'at': time.time(), 'moved': time.time(),
                      'trial_until': time.time() + 1800})
try:
    d.net_ask({'con': 'eth0', 'ipv4': {'method': 'manual', 'addr': '192.168.1.40/24'}}, 'jana')
    ok = False
except ValueError:
    ok = True
check(ok, 'a new network asked during a trial is taken, then dropped without a word')
d.store.set_meta('net:job', '')
d.store.set_meta('net:want', '')

# the trial of an access never set on the dashboard puts back what nginx had
d.root_look = lambda fresh=False: {'access': {'dashboard': {'any': True, 'from': []},
                                              'sms': {'any': True, 'from': []}}}
d.store.set_meta('web_access', '')
trial = d.fw_trial_begin('jana')
d.store.set_meta('web_access', json.dumps({'dashboard': {'any': False, 'from': ['10.9.9.9']}}))
d.root_installed = lambda: False
d.fw_put_back(trial, 'not kept')
check(d.access_conf() is not None and (d.access_conf().get('dashboard') or {}).get('any') is True,
      'an access change on trial, the first ever, is not taken back: root is sent none and '
      'nginx keeps the new lines (%r)' % (d.access_conf(),))

# time settings that root could not put in are asked again
d.root_installed = lambda: True
d._mj_put('ntp:conf', {'manage': True, 'servers': ['tik.cesnet.cz']})
d._mj_put('ntp:applied', {'hash': d.ntp_hash(), 'at': time.time() - 600, 'ok': False,
                          'said': 'root did not answer'})
asked = []
d.ntp_apply = lambda: asked.append(1)
d.ntp_publish = lambda *a: None
d.ntp_tick()
check(asked, 'time settings root could not put in (busy with a backup) are never asked again')

# a step of the clock is not a restart of the machine
bt = W / 'boot'
bt.write_text('5f1c0e0e-0000-4000-8000-000000000001')
os.environ['ZIGMON_BTIME_FILE'] = str(bt)
row = {'boot': 1000.0, 'boot_id': d.boot_id() if hasattr(d, 'boot_id') else ''}
d.boot_time = lambda: 1060.0                        # btime moves when chrony steps the clock
check(hasattr(d, 'rebooted_since') and not d.rebooted_since(row), 'the clock stepped a minute is taken for a restart of the machine')
bt.write_text('5f1c0e0e-0000-4000-8000-000000000002')
check(hasattr(d, 'rebooted_since') and d.rebooted_since(row), 'a restart of the machine is not seen')
del os.environ['ZIGMON_BTIME_FILE']

# root does not do what was asked long ago, when nobody waits any more
spec = importlib.util.spec_from_file_location('zroot', str(HERE / 'deploy' / 'zigmon_root.py'))
zr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zr)
done, out = [], {}
zr.root_fd = lambda: None
zr.drop_ask = lambda name, dd: None
zr.read_req = lambda name, most=0: json.dumps({'id': 'x1', 'do': 'power', 'how': 'reboot',
                                                'until': time.time() - 3000}).encode()
zr.write_here = lambda name, text, *a, **k: out.update(json.loads(text))
zr.ask_part('net.ask', 'net.json', lambda r: done.append(r))
check(not done and out.get('ok') is False,
      'a restart asked an hour ago, while root was at a backup, is still done')
zr.read_req = lambda name, most=0: json.dumps({'id': 'x2', 'do': 'read', 'until': time.time() + 60}).encode()
zr.ask_part('net.ask', 'net.json', lambda r: done.append(r) or {})
check(done and out.get('ok') is True, 'a question still waited for is refused')

# ---- the pages follow at once ---------------------------------------------------------
print('the pages hear of a reading at once')
time.sleep(0.6)
since = d.seq
t0 = time.time()
d.bump_soon()
woke = d.wait_for_change(since, 2)
took = time.time() - t0
check(took < 0.1, 'a temperature in a quiet house reached the pages %d ms late' % (took * 1000))
n0 = d.seq
for _i in range(40):
    d.bump_soon()
    time.sleep(0.01)
time.sleep(0.7)
check(d.seq - n0 <= 3, 'a burst of numbers woke the pages %d times in half a second' % (d.seq - n0))
page = (HERE / 'web' / 'index.php').read_text()
grid = page[page.index('function renderDeviceGrid('):page.index('function renderSensorsTab(')]
check("host.innerHTML = '';" not in grid and 'host._cards' in grid,
      'one reading builds every card of the Sensors and Buttons grids again')
check('WAIT.retry' in page and 'clearTimeout(WAIT.retry)' in page,
      'the wait for changes sleeps on in its backoff after the daemon is back')

# ---- the automations ------------------------------------------------------------------
print('rules, scenes, holds and timers')
import sqlite3                                          # noqa: E402
d.root_installed = lambda: False
sent = []
d._run_zigbee_switch = lambda dev, key, do, origin, pulse_ms=None: sent.append(do)
T = ('zb', '0xlamp', 'state')
d._fire_target(T, 'for:1s', 'rule: motion', honour_hold=True)        # a rule: on for a second
d.hold_target('zb:0xlamp:state', 'Button')                            # somebody takes it over
time.sleep(1.1)
d.check_for_backs()
time.sleep(0.3)
check(sent == ['on'], 'a rule\'s "on for N" switched off a light somebody had taken over: %r' % sent)
d.release_target('zb:0xlamp:state') if hasattr(d, 'release_target') else None
sent.clear()
d._fire_target(T, 'for:1s', 'a button')                               # by hand: its own way back
time.sleep(1.1)
d.check_for_backs()
time.sleep(0.3)
check(sent[-1:] == ['off'], 'a press\'s own "on for N" did not come back: %r' % sent)

# a delayed way back and a waiting rule outlive a restart
d._fire_target(('zb', '0xheat', 'state'), 'for:30min', 'rule: cold')
d.rule_waiting['r-late'] = {'due': time.time() + 600, 'origin': 'x', 'facts': {}, 'device_id': 'd',
                            'do': 'off', 'at': time.time()}
d.timers_keep() if hasattr(d, 'timers_keep') else None
d.store.flush(3.0)
d2 = zigmon.Daemon()
d2.timers_keep() if hasattr(d2, 'timers_keep') else None
check('zb:0xheat:state' in d2._for_backs, 'a heater "on for 30 min" stays on for good after a restart')
check('r-late' in d2.rule_waiting, 'a rule waiting to act is forgotten at a restart')
d.rule_waiting.clear()
with d._for_lock:
    d._for_backs.clear()

# a scene with two sockets on one box asks the hold like any other
d.store.set_meta('managed', json.dumps({'plugs': [
    {'name': 'Strip-1', 'host': '127.0.0.1:1', 'switch_id': 0, 'kind': 'plug', 'host_state': 'enabled'},
    {'name': 'Strip-2', 'host': '127.0.0.1:1', 'switch_id': 1, 'kind': 'plug', 'host_state': 'enabled'}],
    'sensors': []}))
d.reload_devices()
boxed = []
d._run_binding = lambda p, do, origin, *a, **k: boxed.append((p.name, do))
d.store.set_meta('scenes', json.dumps([{'id': 'sA', 'name': 'strip off', 'enabled': True, 'actions': [
    {'target': 'Strip-1', 'do': 'off'}, {'target': 'Strip-2', 'do': 'off'}]}]))
d.hold_target('Strip-1', 'by hand')
d.hold_target('Strip-2', 'by hand')
d.run_scene('sA', 'rule: x', honour_hold=True)
time.sleep(0.5)
check(not boxed, 'a scene run by a rule switched sockets held by hand, two on one box: %r' % boxed)

# rules: one switched off forgets; a wait inside a cooldown still acts
fired = []
was_fire = d._fire_target
d._fire_target = lambda target, do, origin, *a, **k: fired.append((do, origin))
d.store.set_meta('rules', json.dumps([{'id': 'alarm', 'device': '0xdoor', 'key': 'contact', 'op': '==',
                                       'value': 0, 'plug': 'zb:0xlamp:state', 'do': 'on', 'enabled': True}]))
d.fire_rules('0xdoor', 'Door', {'contact': 0}, gated=False)
d.set_rule_enabled('alarm', 'off', 'test')
for v in (1, 0, 1):
    d.fire_rules('0xdoor', 'Door', {'contact': v}, gated=False)
d.set_rule_enabled('alarm', 'on', 'test')
fired.clear()
d.fire_rules('0xdoor', 'Door', {'contact': 0}, gated=False)
check(len(fired) == 1, 'a door alarm switched off with the door open and on again said nothing at the next opening')

# a scene switching three rules off at once loses none of them
d.store.set_meta('rules', json.dumps([{'id': i, 'device': '0xd', 'key': 'k', 'op': '>', 'value': 1,
                                       'plug': 'zb:0xl:state', 'do': 'on', 'enabled': True} for i in 'abcdef']))
ths = [threading.Thread(target=d.set_rule_enabled, args=(i, 'off', 'scene')) for i in 'abcdef']
[t.start() for t in ths]
[t.join() for t in ths]
left = [r['id'] for r in d.rules() if r.get('enabled', True)]
check(not left, 'rules switched off together, one was lost: %r still on' % left)

clock = [1000.0]
real_time = zigmon.time.time
zigmon.time.time = lambda: clock[0]
fired.clear()
d.rule_runtime.clear()
d.store.set_meta('rules', json.dumps([{'id': 'off', 'device': '0xpir', 'key': 'occupancy', 'op': '==', 'value': 0,
    'after_s': 60, 'cooldown_s': 120, 'plug': 'zb:0xlamp:state', 'do': 'off', 'enabled': True}]))


def rd(v, t):
    clock[0] = t
    d.fire_rules('0xpir', 'PIR', {'occupancy': v}, gated=False)
    d.check_rule_waiting()


rd(1, 1000)
rd(0, 1090)
rd(1, 1100)
rd(0, 1190)
for t in range(1191, 2000, 30):
    rd(0, t)
zigmon.time.time = real_time
check(fired, 'a light set to go off a minute after the room empties, with a cooldown, never went off')
d._fire_target = was_fire

# the notifying thread outlives a message that goes wrong
zigmon.CONFIG.update({'sms_enabled': True, 'sms_host': '127.0.0.1', 'sms_port': 1, 'sms_api': 'rest',
                      'sms_quiet_from': '00:00', 'sms_quiet_to': '23:59', 'sms_to': '+420777000111',
                      'notify_ntfy': ''})
d.sms_recipients = lambda: ['+420777000111']


def boom(*a, **k):
    raise sqlite3.OperationalError('database is locked')


d.sms_queue_add = boom
d.notify('first alert', 'warn', about='alert', sms=True)
time.sleep(1)
d.notify('burglar!', 'crit', about='alert')
time.sleep(1)
check(not [i for i in d.notify_queue if i['message'] == 'burglar!'],
      'one message that went wrong stopped every later alert: %r' % [i['message'] for i in d.notify_queue])
zigmon.CONFIG.update({'sms_enabled': False})

# ---- nothing on the rules' clock or the page waits for the database ------------------
print('the clock and the page do not wait behind the database')
d._power_peak_cache = (time.time() - 120, 1.0, 2.0)
d._money_cache = (time.time() - 60, float(zigmon.CONFIG.get('price_per_kwh') or 0), {'held': 1})
d.rule_waiting['r-held'] = {'due': time.time() + 600, 'origin': 'y', 'facts': {}, 'device_id': 'd',
                            'do': 'off', 'at': time.time()}
took = {}


def hold(gate):
    with d.store.lock:
        gate.set()
        time.sleep(1.0)                                 # the nightly VACUUM, say


for name, fn in (('peaks', d.power_peaks), ('money', d.money), ('timers', d.timers_keep)):
    gate = threading.Event()
    h = threading.Thread(target=hold, args=(gate,))
    h.start()
    gate.wait()
    t0 = time.time()
    fn()
    took[name] = time.time() - t0
    h.join()
for name, secs in took.items():
    check(secs < 0.3, '%s waited %.1f s behind a database somebody else held' % (name, secs))
d.rule_waiting.pop('r-held', None)

d.store.flush(3.0)
sys.stdout.flush()
if bad:
    print('\n%d check(s) failed' % len(bad))
    os._exit(1)
print('every fault the 5.24 read found stays mended')
os._exit(0)
