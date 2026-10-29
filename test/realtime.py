#!/usr/bin/env python3
"""Sensors, buttons, and the switching that follows: instantly, or not at all.

    python3 test/realtime.py

The house here is a fake Shelly on a port of its own, so the whole chain is
real - the report arrives the way the broker delivers it, the rules and the
bindings run on their own threads, the command goes out over HTTP - and the
only thing left out is the broker itself.

Every check is a stopwatch: a motion report, a button press and a click must
reach the box in milliseconds, and a press must not wait out a poll already on
the wire.
"""
import json
import sys
import socket
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

BOX = {'output': False, 'sets': [], 'poll_delay': 0.0, 'polls': 0,
       # a box that says "too many requests": for this long from now, or for
       # this many answers, whichever is set
       'busy_until': 0.0, 'busy_times': 0, 'refused': [],
       # a box that simply never answers this many commands - a packet lost
       # on the way, which on this house's own month happened 326 times
       'swallow': 0, 'toggles': 0, 'set_delay': 0.0}


class Box(BaseHTTPRequestHandler):
    """A Shelly that answers Switch.Set at once and can be told to be slow."""

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        method, params = body.get('method'), body.get('params') or {}
        if time.time() < BOX['busy_until'] or BOX['busy_times'] > 0:
            if BOX['busy_times'] > 0:
                BOX['busy_times'] -= 1
            BOX['refused'].append((time.time(), method))
            raw = b'{"error":"too many requests"}'
            self.send_response(429)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if method == 'Switch.Toggle':
            BOX['toggles'] += 1
            if BOX.get('toggle_delay'):
                time.sleep(BOX['toggle_delay'])   # slow, but it did hear it
            was, BOX['output'] = BOX['output'], not BOX['output']
            BOX['sets'].append((time.time(), bool(BOX['output'])))
            out = {'was_on': was}
            raw = json.dumps({'id': body.get('id'), 'result': out}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if method == 'Switch.Set' and BOX.get('swallow', 0) > 0:
            BOX['swallow'] -= 1
            time.sleep(8.0)                       # it went nowhere; the caller waits
            return
        if method == 'Switch.Set':
            if BOX.get('set_delay'):
                time.sleep(BOX['set_delay'])      # a box answers one command at a time
            BOX['sets'].append((time.time(), bool(params.get('on'))))
            was, BOX['output'] = BOX['output'], bool(params.get('on'))
            out = {'was_on': was}
        elif method in ('Shelly.GetStatus', 'Switch.GetStatus'):
            BOX['polls'] += 1
            if BOX['poll_delay']:
                time.sleep(BOX['poll_delay'])
            # four channels, so a strip can be driven as the house's own are
            out = {'switch:%d' % i: {'id': i, 'output': BOX['output'], 'apower': 12.0,
                                     'voltage': 231.0, 'aenergy': {'total': 1.0}}
                   for i in range(4)}
        elif method == 'Shelly.GetDeviceInfo':
            out = {'id': 'shellyplug-test', 'model': 'S3PL-00112EU', 'gen': 3, 'ver': '1.7.1'}
        else:
            out = {}
        raw = json.dumps({'id': body.get('id'), 'result': out}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


server = ThreadingHTTPServer(('127.0.0.1', 19871), Box)
threading.Thread(target=server.serve_forever, daemon=True).start()

zigmon.load_config()
zigmon.CONFIG['db_file'] = '/tmp/zigmon-realtime.db'
zigmon.CONFIG['api_port'] = 19872
zigmon.CONFIG['token_file'] = '/tmp/zigmon-realtime-token'
zigmon.CONFIG['pin'] = '1234'
zigmon.CONFIG['plugs'] = []
zigmon.CONFIG['sensors'] = []
zigmon.CONFIG['mqtt_host'] = ''
for old in ('/tmp/zigmon-realtime.db', '/tmp/zigmon-realtime.db-wal', '/tmp/zigmon-realtime.db-shm'):
    Path(old).unlink(missing_ok=True)

d = zigmon.Daemon()
d.store.set_meta('managed', json.dumps({'plugs': [{'name': 'Light-Test', 'host': '127.0.0.1:19871',
                                                   'switch_id': 0, 'kind': 'plug', 'host_state': 'enabled'}],
                                        'sensors': []}))
d.reload_devices()
# the two rule threads, as the daemon starts them
threading.Thread(target=d.rule_worker, name='rules', daemon=True).start()
threading.Thread(target=d.rule_worker, args=(True,), name='rules-presence', daemon=True).start()

FAST_MS = 400          # a whole chain, on one machine, over loopback


def check(ok, what):
    if not ok:
        raise AssertionError(what)


def waited(n=1, limit=3.0):
    """Wait for the box to be told something, and say how long it took."""
    asked = time.time()
    while time.time() - asked < limit:
        if len(BOX['sets']) >= n:
            return (BOX['sets'][n - 1][0] - asked) * 1000
        time.sleep(0.002)
    return None


# -- a PIR sees somebody: the light is on before anybody has taken a step ---------
d.store.upsert_device({'id': 'zigbee:PIR-Test', 'name': 'PIR-Test', 'source': 'zigbee', 'kind': 'sensor',
                       'exposes': {'occupancy': {}}})
d.names['PIR-Test'] = 'zigbee:PIR-Test'        # as the bridge's list would say
# `==` is what a comparison is written as; `=` is not one of RULE_OPS and
# save_rules refuses it. Written straight into the table here it used to reach
# _rule_holds, which read anything it did not know as "<" - so "occupancy = 1"
# acted as "occupancy < 1" and the rule fired when the PIR went QUIET and did
# nothing when it saw somebody. The fire from the quiet report landed on the
# rule worker's thread a moment later and this check counted it as the answer
# to the movement: 2 ms, measured on the wrong edge, for six releases.
d.store.set_meta('rules', json.dumps([{'id': 'r-rt', 'device': 'zigbee:PIR-Test', 'key': 'occupancy',
                                       'op': '==', 'value': 1, 'plug': 'Light-Test', 'do': 'on',
                                       'enabled': True}]))
d.handle_zigbee('PIR-Test', json.dumps({'occupancy': False}).encode())
time.sleep(0.3)                                # whatever that report was going to do, it has done
BOX['sets'] = []
d.handle_zigbee('PIR-Test', json.dumps({'occupancy': False}).encode())
time.sleep(0.3)
check(not BOX['sets'], 'the light was switched by the PIR going quiet, not by it seeing somebody')
BOX['sets'] = []
started = time.time()
d.handle_zigbee('PIR-Test', json.dumps({'occupancy': True}).encode())
took = waited(1)
check(took is not None, 'motion never reached the light')
check(BOX['sets'][0][1] is True, 'motion switched the light the wrong way: %r' % (BOX['sets'][0][1],))
took = (BOX['sets'][0][0] - started) * 1000
check(took < FAST_MS, 'motion took %.0f ms to reach the light' % took)
print('a PIR seeing somebody reaches the light in %.0f ms, and its going quiet does not' % took)

# -- a button press: the relay moves before the finger is off it ------------------
d.store.upsert_device({'id': 'zigbee:Button-Test', 'name': 'Button-Test', 'source': 'zigbee', 'kind': 'button',
                       'exposes': {'action': {}}})
d.names['Button-Test'] = 'zigbee:Button-Test'
d.store.set_meta('bindings', json.dumps([{'device': 'zigbee:Button-Test', 'action': 'single',
                                          'plug': 'Light-Test', 'do': 'off', 'enabled': True}]))
BOX['sets'] = []
started = time.time()
d.handle_zigbee('Button-Test', json.dumps({'action': 'single'}).encode())
check(waited(1) is not None, 'a button press never reached the light')
took = (BOX['sets'][0][0] - started) * 1000
check(took < FAST_MS, 'a button press took %.0f ms to reach the light' % took)
print('a button press reaches the light in %.0f ms' % took)

# -- and a press does not wait out a poll already on the wire ---------------------
# The box is told to take two seconds over its next poll; the press must land
# long before that poll is answered.
BOX['sets'] = []
BOX['poll_delay'] = 2.0
plug = d.plugs['Light-Test']
threading.Thread(target=lambda: plug.rpc().call('Shelly.GetStatus'), daemon=True).start()
time.sleep(0.25)                      # the poll is on the wire now
# This presses the same button again, a fraction of a second after the check
# above - which is what a button reporting one press twice looks like, and is
# dropped as one (see binding_debounce_ms). What is being checked here is the
# poll, not the press, so the daemon is told to forget the last one.
d.__dict__.pop('_press_seen', None)
started = time.time()
d.handle_zigbee('Button-Test', json.dumps({'action': 'single'}).encode())
check(waited(1) is not None, 'a press during a slow poll never reached the light')
took = (BOX['sets'][0][0] - started) * 1000
BOX['poll_delay'] = 0.0
check(took < FAST_MS, 'a press waited %.0f ms for a poll that was already on the wire' % took)
print('a press during a two-second poll still reaches the light in %.0f ms' % took)

# -- what the pages are woken for --------------------------------------------------
# A state - a light, a PIR, a door, a leak - is on the screen at once. The slow
# numbers wake them together, at most twice a second.
woke = []
d.bump = lambda: woke.append('now')
d.bump_soon = lambda delay=0.5: woke.append('soon')
d.store.upsert_device({'id': 'zigbee:Mixed-Test', 'name': 'Mixed-Test', 'source': 'zigbee', 'kind': 'sensor',
                       'exposes': {'state': {}, 'occupancy': {}, 'contact': {}, 'water_leak': {},
                                   'temperature': {}, 'humidity': {}, 'linkquality': {}, 'battery': {}}})
d.names['Mixed-Test'] = 'zigbee:Mixed-Test'
d.handle_zigbee('Mixed-Test',
                json.dumps({'state': 'OFF', 'occupancy': False, 'contact': True, 'water_leak': False,
                            'temperature': 21.0, 'humidity': 40, 'linkquality': 90, 'battery': 100}).encode())
for said, what in (({'state': 'ON'}, 'a light switching'),
                   ({'occupancy': True}, 'a PIR seeing somebody'),
                   ({'contact': False}, 'a door opening'),
                   ({'water_leak': True}, 'a leak')):
    woke[:] = []
    d.handle_zigbee('Mixed-Test', json.dumps(said).encode())
    check(woke == ['now'], '%s waited for the next half second: %r' % (what, woke))
for said, what in (({'temperature': 21.4}, 'a temperature'),
                   ({'humidity': 41}, 'a humidity'),
                   ({'linkquality': 88}, 'a link quality'),
                   ({'battery': 99}, 'a battery level')):
    woke[:] = []
    d.handle_zigbee('Mixed-Test', json.dumps(said).encode())
    check(woke == ['soon'], '%s woke every page on its own: %r' % (what, woke))
# and saying the same thing again wakes nobody twice
woke[:] = []
d.handle_zigbee('Mixed-Test', json.dumps({'state': 'ON'}).encode())
check(woke == ['soon'], 'a light saying the same thing again woke every page: %r' % woke)
print('states are seen at once; the slow numbers wake the pages together')

print('the whole chain: a sensor or a button to the light, and the pages, without a wait')

# ============================================================================
# 5.4: an action put off for a while - "off, then wait 120 s"
# ============================================================================
# A PIR holds its own occupancy for a minute or two after the last movement
# and then says 0. The light should go out some time AFTER that, and not at
# all if somebody moves again in the meantime.
threading.Thread(target=lambda: [d.check_rule_waiting() or time.sleep(0.05) for _ in range(2000)],
                 name='beat', daemon=True).start()
d.store.set_meta('rules', json.dumps([
    {'id': 'r-late', 'device': 'zigbee:PIR-Test', 'key': 'occupancy', 'op': '==', 'value': 0,
     'plug': 'Light-Test', 'do': 'off', 'enabled': True, 'after_s': 2, 'cooldown_s': 0},
]))
d.rule_runtime.pop('r-late', None)
d.rule_waiting.clear()
BOX['sets'] = []
d.handle_zigbee('PIR-Test', json.dumps({'occupancy': True}).encode())    # somebody is there
time.sleep(0.2)
started = time.time()
d.handle_zigbee('PIR-Test', json.dumps({'occupancy': False}).encode())   # ...and gone
time.sleep(0.4)
check(not BOX['sets'], 'the light went off at once, not after the wait')
check('r-late' in d.rule_waiting, 'nothing was put down as waiting')
check(waited(1, limit=4.0) is not None, 'the light never went off')
took = BOX['sets'][0][0] - started
check(1.6 < took < 2.8, 'the wait was %.1f s, not the two it was told' % took)
print('a rule told to wait two seconds switches off after %.1f s' % took)

# ...and somebody moving again calls it off
d.rule_runtime.pop('r-late', None)
d.rule_waiting.clear()
BOX['sets'] = []
d.handle_zigbee('PIR-Test', json.dumps({'occupancy': True}).encode())
time.sleep(0.2)
d.handle_zigbee('PIR-Test', json.dumps({'occupancy': False}).encode())
time.sleep(0.3)
check('r-late' in d.rule_waiting, 'nothing was put down as waiting the second time: %r %r'
      % (d.rule_runtime.get('r-late'), d.rule_waiting))
time.sleep(0.5)
d.handle_zigbee('PIR-Test', json.dumps({'occupancy': True}).encode())    # moved again
time.sleep(0.3)
check('r-late' not in d.rule_waiting, 'the waiting action was not called off by the new movement')
time.sleep(2.2)
check(not BOX['sets'], 'the light went off although somebody had moved again')
print('somebody moving again calls the waiting off, and the light stays on')

# ...and the waiting starts again from the last time it became true
d.rule_runtime.pop('r-late', None)
d.rule_waiting.clear()
BOX['sets'] = []
d.handle_zigbee('PIR-Test', json.dumps({'occupancy': False}).encode())
time.sleep(0.3)
_first_due = d.rule_waiting['r-late']['due']
time.sleep(0.6)
d.handle_zigbee('PIR-Test', json.dumps({'occupancy': True}).encode())
time.sleep(0.2)
d.handle_zigbee('PIR-Test', json.dumps({'occupancy': False}).encode())
time.sleep(0.3)
check(d.rule_waiting['r-late']['due'] > _first_due + 0.4,
      'the waiting was not counted again from the last movement')
d.rule_waiting.clear()
print('the wait is counted from the last time the condition became true')

# ...and what is waiting is said in the status, so the page can count it down
d.rule_runtime.pop('r-late', None)
BOX['sets'] = []
d.handle_zigbee('PIR-Test', json.dumps({'occupancy': True}).encode())
time.sleep(0.2)
d.handle_zigbee('PIR-Test', json.dumps({'occupancy': False}).encode())
time.sleep(0.3)
_said = next(x for x in d.status()['rules'] if x['id'] == 'r-late')
check(_said.get('waiting_s') is not None and _said['waiting_s'] <= 2,
      'the status does not say what is waiting: %r' % _said.get('waiting_s'))
_why = d.rule_why('r-late') if hasattr(d, 'rule_why') else None
d.rule_waiting.clear()
d.rule_runtime.pop('r-late', None)
print('what is waiting to happen is in the status, with the seconds left')

# ...a rule switched off while something of its own is waiting does nothing
d.store.set_meta('rules', json.dumps([
    {'id': 'r-late', 'device': 'zigbee:PIR-Test', 'key': 'occupancy', 'op': '==', 'value': 0,
     'plug': 'Light-Test', 'do': 'off', 'enabled': False, 'after_s': 1, 'cooldown_s': 0},
]))
d.rule_waiting['r-late'] = {'due': time.time() - 1, 'origin': 'a test', 'facts': {},
                            'device_id': 'zigbee:PIR-Test', 'do': 'off', 'at': time.time()}
BOX['sets'] = []
d.check_rule_waiting()
check('r-late' not in d.rule_waiting and not BOX['sets'],
      'a rule switched off still did what it had waiting')
print('a rule switched off while it was waiting does nothing when the moment comes')

# ===== 5.5: the waiting clock does not wait on anything slow =======================

# A rule with a presence gate asks the Wi-Fi controller who is at home. That
# question goes over the network, and the quarter-second clock that counts the
# waiting rules down ran it on its own thread: one slow controller and every
# delayed action in the house was late by as long as it took to answer.
d.store.set_meta('rules', json.dumps([
    {'id': 'r-slow', 'device': 'zigbee:PIR-Test', 'key': 'occupancy', 'op': '==', 'value': 0,
     'plug': 'Light-Test', 'do': 'off', 'enabled': True, 'after_s': 1, 'cooldown_s': 0,
     'when': 'home'},
]))
# a controller that takes three seconds to answer, and a gate that would ask it
_asked = []
_was_poll = d.wifi_poll_once
d.wifi_poll_once = lambda cfg=None, force=False: (_asked.append(time.time()), time.sleep(3), {})[2]
d.wifi = dict(getattr(d, 'wifi', {}) or {}, checked=0,
              presence={'people': {'p1': {'home': True}}, 'known': True})
d.store.set_meta('wifi', json.dumps({'enabled': True, 'host': '10.9.9.9', 'method': 'official',
                                     'user': 'x', 'password': 'y', 'site': 'default'}))
d.rule_waiting.clear()
d.rule_runtime.pop('r-slow', None)
BOX['sets'] = []
d.rule_waiting['r-slow'] = {'due': time.time() - 0.1, 'origin': 'a test', 'facts': {},
                            'device_id': 'zigbee:PIR-Test', 'do': 'off', 'at': time.time()}
_before = time.time()
d.check_rule_waiting()
_took = time.time() - _before
check(_took < 1.0, 'the waiting clock stood still for %.1f s asking who was at home' % _took)
check(not _asked, 'the quarter-second clock went to the controller after all')
# ...while a rule firing in the moment still asks afresh, which is the point
_before = time.time()
d.presence_allows({'when': 'home'})
check(_asked and time.time() - _before > 2, 'a rule firing now no longer looks afresh at who is at home')
d.wifi_poll_once = _was_poll
print('the waiting clock does not stop to ask the Wi-Fi controller (%.0f ms)' % (_took * 1000))

# An hourly cap counts what HAPPENS, not what is armed. Somebody at a desk
# moving every couple of minutes arms and cancels the same wait over and over;
# each arming used to be counted against "max per hour", so the rule met its
# cap without a single socket having been switched, and then stayed quiet for
# the rest of the hour.
d.store.set_meta('rules', json.dumps([
    {'id': 'r-cap', 'device': 'zigbee:PIR-Test', 'key': 'occupancy', 'op': '==', 'value': 0,
     'plug': 'Light-Test', 'do': 'on', 'enabled': True, 'after_s': 3, 'cooldown_s': 0,
     'max_per_hour': 2},
]))
d.rule_waiting.clear()
d.rule_runtime.pop('r-cap', None)
BOX['sets'] = []
for _ in range(3):                       # armed and called off three times over
    d.handle_zigbee('PIR-Test', json.dumps({'occupancy': False}).encode())
    time.sleep(0.25)
    check('r-cap' in d.rule_waiting, 'nothing was put down as waiting')
    d.handle_zigbee('PIR-Test', json.dumps({'occupancy': True}).encode())
    time.sleep(0.25)
    check('r-cap' not in d.rule_waiting, 'the waiting was not called off')
check(not BOX['sets'], 'something was switched although every wait was called off')
check(len((d.rule_runtime.get('r-cap') or {}).get('fire_log') or []) == 0,
      'arming a wait was counted against the hourly cap: %r'
      % ((d.rule_runtime.get('r-cap') or {}).get('fire_log'),))
# ...and now it is left alone, so it acts - which on the old build it could not
d.store.set_meta('rules', json.dumps([
    {'id': 'r-cap', 'device': 'zigbee:PIR-Test', 'key': 'occupancy', 'op': '==', 'value': 0,
     'plug': 'Light-Test', 'do': 'on', 'enabled': True, 'after_s': 1, 'cooldown_s': 0,
     'max_per_hour': 2},
]))
d.handle_zigbee('PIR-Test', json.dumps({'occupancy': False}).encode())
check(waited(1, limit=4.0) is not None, 'the light never came on: the cap was spent on arming')
check(len((d.rule_runtime.get('r-cap') or {}).get('fire_log') or []) == 1,
      'what happened was not counted against the cap')
d.rule_waiting.clear()
d.rule_runtime.pop('r-cap', None)
print('an hourly cap counts what happens, not what is armed and called off')

# ===== 5.8: nothing a person is waiting on sits behind the network ================

# "I'm leaving" on a button says somebody has gone, and saying so asks the
# Wi-Fi controller whether they really have - three seconds behind a lock of
# the same. That ran on the broker's own thread, so for those seconds no
# sensor report, no other press and no light confirming itself was handled.
d.store.set_meta('people', json.dumps([{'id': 'p-away', 'name': 'Tester', 'macs': [], 'watch': True}]))
d._presence_cache = None
d.store.set_meta('wifi', json.dumps({'enabled': True, 'host': '10.9.9.9', 'method': 'official',
                                     'user': 'x', 'password': 'y', 'site': 'default'}))
d.wifi = dict(getattr(d, 'wifi', {}) or {}, checked=0)
# ...and the phone is still on the house Wi-Fi, which is when a reported
# departure is checked against the controller before it is believed
d.presence['p-away'] = {'home': True, 'last_seen': time.time(), 'since': time.time(),
                        'device': 'phone', 'on_wifi': True}
_slow = []
_was_poll = d.wifi_poll_once
d.wifi_poll_once = lambda cfg=None, force=False: (_slow.append(time.time()), time.sleep(3), {})[2]
_before = time.time()
d._fire_target(('presence', 'p-away'), 'off', 'a test')
_took = time.time() - _before
check(_took < 0.5, 'saying somebody has left held the caller for %.1f s' % _took)
# ...and it still happens, on a thread of its own
time.sleep(0.3)
check(_slow, 'saying somebody has left did not reach the controller at all')
d.wifi_poll_once = _was_poll
d.store.set_meta('wifi', json.dumps({'enabled': False}))
print('saying somebody has left does not hold the thread a press arrived on (%.0f ms)' % (_took * 1000))

# ...and so does switching a rule off from a button: that writes the whole
# rule list back to the database, which on the message path stands behind
# whatever the database is doing.
d.store.set_meta('rules', json.dumps([{'id': 'r-switch', 'device': 'zigbee:PIR-Test', 'key': 'occupancy',
                                       'op': '==', 'value': 1, 'plug': 'Light-Test', 'do': 'on',
                                       'enabled': True}]))
_held = []
_was_set = d.set_rule_enabled
d.set_rule_enabled = lambda ident, act, origin='': (_held.append(time.time()), time.sleep(2))[0]
_before = time.time()
d._fire_target(('switchable', 'rule', 'r-switch'), 'off', 'a test')
_took2 = time.time() - _before
check(_took2 < 0.5, 'switching a rule off held the caller for %.1f s' % _took2)
time.sleep(0.3)
check(_held, 'switching a rule off from a press did nothing at all')
d.set_rule_enabled = _was_set
print('switching a rule off from a press does not hold that thread either (%.0f ms)' % (_took2 * 1000))

# ===== 5.9: a box saying "too many requests" must not cost somebody a light ======
# 16 October 2026, 23:50: the kitchen, the hall and the entrance all answered
# HTTP 429 to a press of their PIR. Each command was tried twice inside a
# second and a quarter and then dropped - three dark rooms, nothing on the
# page, and everything working again two minutes later by itself.

zigmon.CONFIG['plug_command_patience_s'] = 5.0
BOX['sets'] = []
BOX['refused'] = []
BOX['busy_until'] = time.time() + 2.0          # the box refuses for two seconds
_before = time.time()
_ok, _words = d.set_plug_output(d.plugs['Light-Test'], True, 'a test')
_took = time.time() - _before
check(_ok, 'a box that refused for two seconds cost the light altogether: %s' % _words)
check(BOX['sets'], 'nothing ever reached the box')
check(_took < 5.0, 'the command took %.1f s' % _took)
print('a command waits out a box that says "too many requests" (%.1f s, %d refusal(s))'
      % (_took, len(BOX['refused'])))

# ...and a box that refuses for longer than the patience is given up on, so a
# thread is never held for ever
BOX['sets'] = []
BOX['busy_until'] = time.time() + 30.0
zigmon.CONFIG['plug_command_patience_s'] = 1.5
_before = time.time()
try:
    _ok, _words = d.set_plug_output(d.plugs['Light-Test'], True, 'a test')
except zigmon.PlugError as e:
    _ok, _words = False, str(e)
_took = time.time() - _before
check(not _ok, 'a box that never stops refusing was said to have switched')
check(_took < 4.0, 'giving up took %.1f s, which is not giving up' % _took)
BOX['busy_until'] = 0.0
zigmon.CONFIG['plug_command_patience_s'] = 5.0
print('a box that goes on refusing is given up on, in its own time')

# A reading nobody is waiting on must not spend the box's second while a
# command is in the air for it: the poll's own patient retries - 2 s, 4 s,
# 6 s - were what kept the budget empty.
BOX['refused'] = []
BOX['busy_times'] = 3                           # three refusals, then it answers
zigmon.ShellyRPC._cmd_at[d.plugs['Light-Test'].cfg['host']] = time.time()   # a command just went
_before = time.time()
try:
    d.plugs['Light-Test'].rpc().call('Shelly.GetStatus')
    _gave_up = False
except zigmon.PlugError as e:
    _gave_up = 'busy with a command' in str(e)
_took = time.time() - _before
check(_gave_up, 'a poll went on retrying into a box somebody was waiting on')
check(_took < 1.0, 'the poll held the box for %.1f s before giving up' % _took)
zigmon.ShellyRPC._cmd_at.clear()
BOX['busy_times'] = 0
print('a reading gives way at once to a command on the same box')

# ...and a box that has just said "too many requests" is left alone for a
# moment, so what it has left to answer with goes to the press
zigmon.ShellyRPC._rate_limited[d.plugs['Light-Test'].cfg['host']] = (time.time(), 1)
check(zigmon.ShellyRPC.cooling(d.plugs['Light-Test'].cfg['host']),
      'a box that just refused is not counted as cooling')
_polls = BOX['polls']
d.poll_plug(d.plugs['Light-Test'])
check(BOX['polls'] == _polls, 'a box that just said "too many requests" was polled anyway')
zigmon.ShellyRPC._rate_limited.clear()
print('a box that just refused is left what it has for the press')

# A light that was asked for and did not come on is on the page, not only in
# the log - which is how three dark rooms were found a day later.
BOX['busy_until'] = time.time() + 30.0
zigmon.CONFIG['plug_command_patience_s'] = 0.5
d._run_binding(d.plugs['Light-Test'], 'on', 'a test')
BOX['busy_until'] = 0.0
zigmon.CONFIG['plug_command_patience_s'] = 5.0
_waited = 0.0
_said = []
while _waited < 3.0 and not _said:              # the events are written on their own thread
    time.sleep(0.2)
    _waited += 0.2
    _said = [e for e in d.store.events(limit=50, text='did not') if 'Light-Test' in (e.get('detail') or '')]
check(_said, 'a light that never came on was not written down anywhere the page looks')
print('a light that did not come on is on the page: %r' % (_said[0]['detail'][:70] if _said else ''))

# 5.11: a press that touches many sockets must not hold the broker's thread.
# fire_bindings runs on paho's own callback thread. A binding naming every
# socket - or an action group of a dozen - fanned out inline: a thread started
# per target from that thread, each going straight into HTTP, and the broker
# thread lost the processor to them for twenty-six milliseconds and more,
# during which no message from the house was handled at all. One target still
# fires inline, because that is the common press.
_many = [{'name': 'Fan-%d' % i, 'host': '127.0.0.1:%d' % (19500 + i), 'switch_id': 0,
          'kind': 'plug', 'host_state': 'enabled'} for i in range(12)]
d.store.set_meta('managed', json.dumps(
    {'plugs': [{'name': 'Light-Test', 'host': '127.0.0.1:19871', 'switch_id': 0,
                'kind': 'plug', 'host_state': 'enabled'}] + _many, 'sensors': []}))
d.reload_devices()
d.store.set_meta('bindings', json.dumps([{'device': 'zigbee:Button-Test', 'action': 'single',
                                          'plug': '*', 'do': 'on', 'enabled': True}]))
check(len(d._binding_targets('*')) >= 12,
      'the test house has only %d socket(s) to fan out to' % len(d._binding_targets('*')))
_held = []
for _ in range(5):
    _t0 = time.perf_counter()
    d.fire_bindings('zigbee:Button-Test', 'Button-Test', 'single')
    _held.append((time.perf_counter() - _t0) * 1000)
    time.sleep(0.35)
_held.sort()
_mid = _held[len(_held) // 2]
check(_mid < 8.0,
      'a press on every socket held the broker thread %.1f ms, so nothing from the house '
      'was heard meanwhile' % _mid)
print('a press on a dozen sockets holds the broker thread %.1f ms' % _mid)

# ...and one socket still goes straight out, as fast as it ever did
d.store.set_meta('bindings', json.dumps([{'device': 'zigbee:Button-Test', 'action': 'single',
                                          'plug': 'Light-Test', 'do': 'off', 'enabled': True}]))
BOX['sets'] = []
_started = time.time()
d.handle_zigbee('Button-Test', json.dumps({'action': 'single'}).encode())
check(waited(1) is not None, 'one socket no longer hears a press at all')
_took = (BOX['sets'][0][0] - _started) * 1000
check(_took < FAST_MS, 'one socket took %.0f ms to hear a press' % _took)
print('a press on one socket still reaches it in %.0f ms' % _took)
d.store.set_meta('managed', json.dumps({'plugs': [{'name': 'Light-Test', 'host': '127.0.0.1:19871',
                                                   'switch_id': 0, 'kind': 'plug',
                                                   'host_state': 'enabled'}], 'sensors': []}))
d.reload_devices()


# 5.11: a state change carries the numbers that were waiting with it.
# A number schedules a wake half a second out; a state change wakes the pages
# at once. In a busy house there is nearly always a number's timer running, so
# a press was followed within half a second by a second wake for numbers the
# page had already fetched - another quarter-megabyte and another repaint for
# nothing.
# the wake-up checks above left stubs in place of these two
d.bump = zigmon.Daemon.bump.__get__(d)
_real_soon = zigmon.Daemon.bump_soon.__get__(d)
_main = threading.current_thread()
# only the numbers these checks send: the sockets above go on being polled,
# and since 5.24 a number in a quiet moment wakes the pages at once
d.bump_soon = lambda delay=0.5: _real_soon(delay) if threading.current_thread() is _main else None


def _wakes(what, settle=0.8):
    d.seq = 0
    d._numbers_pending = False
    if d._bump_timer is not None:
        d._bump_timer.cancel()
        d._bump_timer = None
    what()
    time.sleep(settle)
    return d.seq


check(_wakes(lambda: d.bump_soon(0.2)) == 1, 'a number alone did not wake the pages once')
d.seq = 0
time.sleep(0.3)
d.bump_soon(0.2)
check(d.seq == 1, 'a number in a quiet house waited for its timer before the pages heard of it')
time.sleep(0.5)
_one = _wakes(lambda: d.bump())
check(_one == 1, 'a state change alone did not wake the pages once: %d' % _one)
time.sleep(0.3)
_burst = _wakes(lambda: [d.bump_soon(0.2) for _ in range(10)])
check(_burst <= 2, 'ten numbers in a burst woke the pages %d times, not at once and once after' % _burst)
time.sleep(0.3)
_both = _wakes(lambda: (d.bump_soon(0.2), time.sleep(0.05), d.bump_soon(0.2), time.sleep(0.05), d.bump()))
check(_both == 2,
      'a press with a number waiting behind it woke the pages %d times, so the status was '
      'fetched and drawn again for numbers it already carried' % _both)
time.sleep(0.3)
_after = _wakes(lambda: (d.bump_soon(0.2), time.sleep(0.05), d.bump_soon(0.2), time.sleep(0.05), d.bump(),
                         time.sleep(0.02), d.bump_soon(0.2)))
check(_after == 3, 'a number that arrived after the press was never carried: %d wake(s)' % _after)
print('a state change carries the waiting numbers; a number after it still gets its own wake')
d.bump_soon = _real_soon


# ============================================================================
# 5.11: the seam between the house and the page
# ============================================================================
# Everything above measures the house. This measures what a browser sees: a
# page hangs a wait on the daemon, something happens, and the wait must let go
# and the status that follows must already carry the new truth. A press from
# the page must answer with the new state in hand rather than leaving the tile
# to wait for the next poll - and every other page open on the house must be
# woken by it.
_api = zigmon.ApiServer(d)
_api.start()
time.sleep(0.5)
_tok = Path(zigmon.CONFIG['token_file']).read_text().strip()
_base = 'http://127.0.0.1:%d/' % zigmon.CONFIG['api_port']


# the page is signed in as somebody who uses the house (5.19; it was the PIN)
d.account_add('realtime-op', 'operator', 'realtime pass 1', must_change=False, quiet=True)
_sess = d.login('realtime-op', 'realtime pass 1', '192.0.2.20')[0]['token']


def _ask(path, body=None, timeout=40):
    req = urllib.request.Request(_base + path,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'X-Zigmon-Token': _tok, 'Content-Type': 'application/json',
                                          'X-Zigmon-Session': _sess})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _hang_a_wait():
    """A page waiting on the next change, and how long it waited."""
    out = {}
    seq = _ask('api/status')['seq']

    def run():
        t0 = time.perf_counter()
        try:
            out['seq'] = _ask('api/wait?seq=%d' % seq)['seq']
        except Exception as e:
            out['err'] = repr(e)
        out['ms'] = (time.perf_counter() - t0) * 1000
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    time.sleep(0.25)                      # the wait is on the wire now
    return out, thread


SEAM_MS = 250          # loopback, one machine: a tenth of this in practice

# whichever way the door is now, say the other: a report that says nothing
# new is a number, and numbers wake the pages together half a second later
_now = {s['name']: s for s in _ask('api/status').get('devices', [])}
_was = ((_now.get('Mixed-Test') or {}).get('values') or {}).get('contact', {}).get('value')
_out, _thread = _hang_a_wait()
_t0 = time.perf_counter()
d.handle_zigbee('Mixed-Test', json.dumps({'contact': not _was}).encode())
_thread.join(10)
_woke = (time.perf_counter() - _t0) * 1000
check('ms' in _out, 'a door opening never let the page go: %r' % _out)
check(_woke < SEAM_MS, 'the page waited %.0f ms to hear a door open' % _woke)
_t1 = time.perf_counter()
_st = _ask('api/status')
_sms = (time.perf_counter() - _t1) * 1000
check(_sms < SEAM_MS, 'the status the page then fetched took %.0f ms' % _sms)
_seen = {s['name']: s for s in _st.get('sensors', []) + _st.get('devices', [])}
_vals = ((_seen.get('Mixed-Test') or {}).get('values') or {})
check(_vals.get('contact', {}).get('value') is (not _was),
      'the status that followed the wake did not carry the door moving: %r' % (_vals.get('contact'),))
print('a door moving lets the page go in %.0f ms, and the status after it already says so' % _woke)

# a press from the page: the answer carries the new state, and another page is woken
for _want in (True, False):
    BOX['sets'] = []
    _out, _thread = _hang_a_wait()
    _t0 = time.perf_counter()
    _r = _ask('api/plug/switch', {'name': 'Light-Test', 'on': _want, 'pin': '1234'})
    _press = (time.perf_counter() - _t0) * 1000
    _thread.join(10)
    check(_r.get('ok') is True, 'a press from the page was refused: %r' % _r)
    check(_press < SEAM_MS, 'a press from the page took %.0f ms to answer' % _press)
    check((_r.get('plug') or {}).get('output') == (1 if _want else 0),
          'the press answered without the new state, so the tile has to wait for a poll: %r'
          % ((_r.get('plug') or {}).get('output'),))
    check('ms' in _out, 'another page open on the house was not woken by the press: %r' % _out)
    check(len(BOX['sets']) == 1, 'a press reached the box %d time(s)' % len(BOX['sets']))
print('a press answers in %.0f ms carrying the new state, and wakes every other page' % _press)


# -- 5.13: the row counts are never counted on the thread that asked -------------
# /api/health carries them and the page asks for it on every refresh. `samples`
# is WITHOUT ROWID keyed (device, key, ts), so counting it - and asking for its
# oldest row - is a walk of the whole table: 270 MB on the house, 1592 ms off a
# cold disk, which is what `zigmon check` reported as the daemon's answer time
# right after a restart.
d.store._stats_cache = None
_slow = {'calls': 0}
_real_count = d.store._count_rows


def _slow_count():
    _slow['calls'] += 1
    time.sleep(2.0)                       # what the house's own disk costs
    return _real_count()


d.store._count_rows = _slow_count
_t0 = time.perf_counter()
_first = d.store.stats()
_asked = (time.perf_counter() - _t0) * 1000
check(_asked < 300, 'asking for the header figures counted the whole database first: %.0f ms' % _asked)
check(isinstance(_first, dict) and _first.get('path'),
      'the figures came back without even the file: %r' % (_first,))
_waited = 0.0
while _waited < 8.0 and d.store.stats().get('samples') is None:
    time.sleep(0.2)
    _waited += 0.2
check(d.store.stats().get('samples') is not None,
      'the counting that was moved off the request never landed')
check(_slow['calls'] >= 1, 'nothing ever counted the rows at all')
d.store._count_rows = _real_count
print('the header figures are answered in %.0f ms and counted behind the page' % _asked)

# ...and the oldest reading is read from the hourly table, which is indexed on
# ts, instead of walking every sample to find it (83 ms warm on the house, and
# the whole file off the disk when it is cold).
d.store.store_sample('0xoldest', int(time.time()), {'temperature': 1.0})
with d.store.lock:
    d.store.db.execute('INSERT OR REPLACE INTO samples_hourly (ts, device, key, n, avg, min, max) '
                       'VALUES (?,?,?,?,?,?,?)', (int(time.time()) - 86400, '0xoldest', 'temperature',
                                                  1, 1.0, 1.0, 1.0))
    d.store.db.commit()
_sql = []
_real_connect = zigmon.sqlite3.connect


def _spy_connect(*a, **kw):
    conn = _real_connect(*a, **kw)
    conn.set_trace_callback(_sql.append)
    return conn


zigmon.sqlite3.connect = _spy_connect
try:
    _counts = d.store._count_rows()
finally:
    zigmon.sqlite3.connect = _real_connect
_walks = [s for s in _sql if 'MIN(ts)' in s and 'hourly' not in s]
check(not _walks, 'the oldest reading is still looked for by walking every sample: %r' % (_walks[:2],))
check(_counts.get('oldest'), 'the oldest reading went missing with the walk: %r' % (_counts.get('oldest'),))
print('the oldest reading is read from the folded table, not by walking %d samples'
      % (_counts.get('samples') or 0))


# -- 5.13: after a restart every box is read at once, not over seven seconds ----
# The round spreads the boxes over half the interval so a dozen answers are not
# parsed in the same instant. On the FIRST round there is nothing to spread:
# until a box has been read once it has no reading at all, so the last of
# seventeen boxes had none for seven seconds and `zigmon check` listed seven
# sockets as "not polled yet (the daemon just started)".
_N = 12
_boxes = []
for _i in range(_N):
    _s = ThreadingHTTPServer(('127.0.0.1', 19900 + _i), Box)
    threading.Thread(target=_s.serve_forever, daemon=True).start()
    _boxes.append(_s)
BOX['poll_delay'] = 0.05                  # what a Shelly takes to answer
d.store.set_meta('managed', json.dumps({'plugs': [
    {'name': 'Round-%d' % _i, 'host': '127.0.0.1:%d' % (19900 + _i), 'switch_id': 0,
     'kind': 'plug', 'host_state': 'enabled'} for _i in range(_N)], 'sensors': []}))
d.reload_devices()
zigmon.CONFIG['networkmap_interval'] = 0
d._polled_once = False
for _p in d.plugs.values():
    _p.flat = {}
_t0 = time.time()
threading.Thread(target=d.plug_loop, name='round', daemon=True).start()
_read = {}
while len(_read) < _N and time.time() - _t0 < 20:
    for _name, _p in list(d.plugs.items()):
        if _name not in _read and getattr(_p, 'flat', None):
            _read[_name] = time.time() - _t0
    time.sleep(0.01)
check(len(_read) == _N, 'only %d of %d boxes were ever read' % (len(_read), _N))
_last = max(_read.values())
check(_last < 3.0, 'the last of %d boxes had no reading for %.1f s after the daemon started'
      % (_N, _last))
print('every one of %d boxes has a reading %.1f s after a restart' % (_N, _last))

# ...and a later round does not eat the interval either. The spread was half
# the round - 7.5 s of 15 with seventeen boxes - and the one socket that is
# unplugged costs 5 s more of its own, so the rounds ran 12-15 s against a
# 15 s interval and a second slow box would have made them run back to back.
# A quarter of the round is enough to keep one request in flight at a time.
zigmon.CONFIG['plug_poll_interval'] = 4
for _p in d.plugs.values():
    _p.flat = {}
    _p.last_poll = 0.0
_t0 = time.time()
_again = {}
while len(_again) < _N and time.time() - _t0 < 15:
    for _name, _p in list(d.plugs.items()):
        if _name not in _again and getattr(_p, 'flat', None):
            _again[_name] = time.time() - _t0
    time.sleep(0.01)
check(len(_again) == _N, 'only %d of %d boxes were read in the round after the first'
      % (len(_again), _N))
_spread = max(_again.values()) - min(_again.values())
check(_spread < 1.3, 'a round of %d boxes is spread over %.2f s of a 4 s interval, so one slow '
                     'box leaves it no headroom at all' % (_N, _spread))
print('a later round of %d boxes is spread over %.2f s of its %d s interval'
      % (_N, _spread, zigmon.CONFIG['plug_poll_interval']))
zigmon.CONFIG['plug_poll_interval'] = 15
for _s in _boxes:
    _s.shutdown()


# -- 5.13: one scene is one repaint, not one a socket ---------------------------
# A strip answers one command at a time, so the four sockets of a scene came
# back about 200 ms apart - and each answer woke every open page, which fetches
# the whole quarter-megabyte status and repaints. One press of one button cost
# six fetches and six repaints; on a phone that is a stutter. The sockets still
# switch exactly as fast; it is the telling that is gathered up.
BOX['poll_delay'] = 0.0
BOX['set_delay'] = 0.2
d.store.set_meta('managed', json.dumps({'plugs': [
    {'name': 'Strip-%d' % _i, 'host': '127.0.0.1:19871', 'switch_id': _i, 'kind': 'plug',
     'host_state': 'enabled'} for _i in range(4)], 'sensors': []}))
d.reload_devices()
d.store.set_meta('scenes', json.dumps([{'id': 'sc-wake', 'name': 'Strip',
                                        'actions': [{'target': 'Strip-%d' % _i, 'do': 'on'}
                                                    for _i in range(4)]}]))
d.store.set_meta('bindings', json.dumps([{'device': 'zigbee:Button-Test', 'action': 'single',
                                          'plug': 'scene:sc-wake', 'do': 'on', 'enabled': True}]))
BOX['sets'] = []
# A box that has answered "too many requests" is given one command at a time
# for two minutes (see ShellyRPC.at_once) - and the check further up made this
# one refuse three. It is forgiven here, because what follows is about a box
# that is behaving.
zigmon.ShellyRPC._crowded.clear()
_woke, _stop_watch = [], threading.Event()


def _watch_seq():
    _was = d.seq
    while not _stop_watch.is_set():
        if d.seq != _was:
            _woke.append(time.time())
            _was = d.seq
        time.sleep(0.002)


threading.Thread(target=_watch_seq, daemon=True).start()
_t0 = time.time()
d.fire_bindings('zigbee:Button-Test', 'Button-Test', 'single')
_deadline = time.time() + 4.0
while time.time() < _deadline and len(BOX['sets']) < 4:
    time.sleep(0.01)
time.sleep(0.8)                            # let any wake that was owed land
_stop_watch.set()
BOX['set_delay'] = 0.0
check(len(BOX['sets']) == 4, 'the scene reached the strip %d time(s), not four' % len(BOX['sets']))
_switched = (BOX['sets'][-1][0] - _t0) * 1000
check(_switched < 1500, 'the four sockets took %.0f ms to switch' % _switched)
check(len(_woke) <= 3, 'one press of a four-socket scene woke the pages %d time(s), each of '
                       'them a whole status fetched and repainted' % len(_woke))
check(len(_woke) >= 1, 'the pages were never told the scene had run at all')
check(max(_woke) - _t0 >= (BOX['sets'][-1][0] - _t0),
      'the last wake came before the last socket had answered, so the page never heard the end')
print('a four-socket scene switches in %.0f ms and wakes the pages %d time(s)'
      % (_switched, len(_woke)))

# ...and the four of them go to the box TOGETHER. A four-socket strip is four
# relays and a box that will answer four requests; sent one at a time the last
# socket switched a second after the first (measured 1014 ms against 267), and
# when such a box is off the air the four timeouts add up to twenty seconds
# instead of five. A box that says "too many requests" is taken at its word
# and asked one at a time for the next two minutes.
check(_switched < 700, 'the four sockets of one strip took %.0f ms, so they are still being sent '
                       'one at a time' % _switched)
check(zigmon.ShellyRPC.at_once('127.0.0.1:19871') > 1,
      'a box that has said nothing against it is still asked one command at a time')
BOX['busy_times'] = 4                        # it refuses the next four commands
BOX['sets'] = []
d.fire_bindings('zigbee:Button-Test', 'Button-Test', 'single')
_deadline = time.time() + 8.0
while time.time() < _deadline and len(BOX['sets']) < 4:
    time.sleep(0.01)
BOX['busy_times'] = 0
check(zigmon.ShellyRPC.at_once('127.0.0.1:19871') == 1,
      'a box that answered "too many requests" is still being given four at a time')
zigmon.ShellyRPC._crowded.clear()
check(zigmon.ShellyRPC.at_once('127.0.0.1:19871') > 1,
      'a box stays on one at a time for ever once it has refused anything')
print('a strip of four is switched as four, and a box that refuses is given one at a time')

# -- 5.14: a rule never waits on the network -----------------------------------
# A rule gated on who is home asked the wi-fi controller afresh, on the rule
# worker, with a three-second timeout. A controller that accepts the
# connection and then says nothing held that worker for 3,027 ms - measured,
# three times running - with every other gated rule of every other report
# queued behind it. The look is worth having when the controller is healthy
# (it answers in a fraction of a second); when it is not, the last answer
# stands.
_hole2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
_hole2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
_hole2.bind(('127.0.0.1', 19878))
_hole2.listen(8)                             # accepts, never answers: a controller off the air
_was_wifi = d.store.get_meta('wifi')
d.store.set_meta('wifi', json.dumps({'enabled': True, 'host': '127.0.0.1', 'port': 19878,
                                     'method': 'official', 'api_key': 'k', 'verify_ssl': False,
                                     'site': 'default', 'poll_s': 30}))
d.store.set_meta('people', json.dumps([{'id': 'p-rt', 'name': 'Somebody', 'enabled': True,
                                        'macs': ['aa:bb:cc:dd:ee:00']}]))
try:
    d.wifi = {'ok': True, 'clients': [], 'checked': 0, 'names': {}, 'error': None}
    d._presence_cache = None
    _t0 = time.time()
    d.presence_allows({'when': 'away'})
    _held = (time.time() - _t0) * 1000
    check(_held < 1200, 'a rule waited %.0f ms on a wi-fi controller that says nothing, and every '
                        'other gated rule waited behind it' % _held)
finally:
    d.store.set_meta('wifi', _was_wifi or json.dumps({'enabled': False}))
    _hole2.close()
    d.wifi = {'ok': None, 'clients': [], 'checked': 0, 'names': {}, 'error': None}
    d._presence_cache = None
print('a rule gated on who is home waits %.0f ms on a controller that says nothing' % _held)


# -- 5.14: the way to the light does not touch the database lock at all --------
# This is the whole point of the house: a sensor sees somebody and the light is
# told, with nothing in between that can wait. The one lock this database has
# is held for a second and a half by a backup, longer by an optimise - so the
# path must not ask for it even once. Measured on the house's own database:
# three acquisitions on the FIRST firing after a start (three settings nobody
# had ever written, each fetched under the lock), none on any firing after.
# Every setting row is read once at startup now, and a key that is not among
# them is known to be absent rather than looked for.
d.store.set_meta('managed', json.dumps({'plugs': [
    {'name': 'Light-Test', 'host': '127.0.0.1:19871', 'switch_id': 0, 'kind': 'plug',
     'host_state': 'enabled'}], 'sensors': []}))
d.reload_devices()
d.store.set_meta('rules', json.dumps([{'id': 'r-cold', 'device': 'zigbee:PIR-Test',
                                       'key': 'occupancy', 'op': '==', 'value': 1,
                                       'plug': 'Light-Test', 'do': 'on', 'enabled': True,
                                       'cooldown_s': 0}]))
d.handle_zigbee('PIR-Test', json.dumps({'occupancy': False}).encode())
time.sleep(0.4)
# as a restart leaves it: nothing in memory but what the table holds
d.store._meta_raw.clear()
d.store._warm_meta()
_real_lock = d.store.lock
_touch = {'on': False, 'where': []}


class _Counting(object):
    """Hands out the real lock and writes down who asked for it."""

    def acquire(self, *a, **kw):
        if _touch['on'] and threading.current_thread().name in ('MainThread', 'rules', 'binding',
                                                                'rules-presence'):
            import traceback as _tb
            lines = [x.strip() for x in _tb.format_stack(limit=8) if '/zigmon.py' in x]
            _touch['where'].append(lines[-1].split('\n')[-1].strip() if lines else '?')
        return _real_lock.acquire(*a, **kw)

    def release(self):
        return _real_lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *e):
        self.release()


d.store.lock = _Counting()
try:
    BOX['sets'] = []
    _touch['on'] = True
    d.handle_zigbee('PIR-Test', json.dumps({'occupancy': True}).encode())
    _reached = waited(1, limit=4.0)
    _touch['on'] = False
finally:
    d.store.lock = _real_lock
check(_reached is not None, 'the light was never told at all')
check(not _touch['where'], 'the way from a sensor to the light took the database lock %d time(s), '
                           'so a backup or an optimise can stand in front of a light: %r'
      % (len(_touch['where']), _touch['where'][:3]))
print('the way from a sensor to the light takes the database lock %d time(s), cold'
      % len(_touch['where']))
d.store.set_meta('rules', json.dumps([]))


# -- 5.14: a socket's own report reaches the rules, not only the poll ----------
# A Shelly on the broker says the moment its relay moves or its watts change -
# a wall button, its own app, the washing machine finishing. That is the fast
# road, and it updated the page and the state and then skipped every rule
# watching that socket: such a rule was served by the reading that comes round
# every fifteen seconds, and once a box is on the broker that is the slow road.
d.store.set_meta('managed', json.dumps({'plugs': [
    {'name': 'Plug-Washer', 'host': '127.0.0.1:19871', 'switch_id': 0, 'kind': 'plug',
     'host_state': 'enabled', 'mqtt': True, 'mqtt_name': 'plug-washer'},
    {'name': 'Light-Test', 'host': '127.0.0.1:19871', 'switch_id': 1, 'kind': 'plug',
     'host_state': 'enabled'}], 'sensors': []}))
d.reload_devices()
d.store.set_meta('rules', json.dumps([{'id': 'r-washer', 'device': 'plug:Plug-Washer',
                                       'key': 'switch.apower', 'op': '<', 'value': 5,
                                       'plug': 'Light-Test', 'do': 'on', 'enabled': True,
                                       'cooldown_s': 0}]))


def _washer_says(watts):
    d.handle_plug_push(d.plug_prefix_map()['plug-washer'], ['events', 'rpc'], json.dumps(
        {'method': 'NotifyStatus',
         'params': {'switch:0': {'id': 0, 'output': True, 'apower': watts}}}).encode())


_washer_says(340.0)                          # it is running
time.sleep(0.3)
BOX['sets'] = []
_t0 = time.time()
_washer_says(0.6)                            # ...and it has finished
_woke = waited(1, limit=4.0)
check(_woke is not None, 'a socket reporting on its own MQTT reached the page but not the rules, so '
                         'a rule on its watts waited for the poll')
_push_ms = (BOX['sets'][0][0] - _t0) * 1000
check(_push_ms < FAST_MS, 'a socket\'s own report took %.0f ms to reach the rule' % _push_ms)
print('a socket\'s own report reaches a rule in %.0f ms, not at the next poll' % _push_ms)
d.store.set_meta('rules', json.dumps([]))


# -- 5.14: a command nobody heard is asked again, and a dead box is not waited on
# This house's own month: 326 commands timed out and 67 found no route, and on
# 97% of them the box was still unreachable two minutes later - so most of them
# are boxes that are really gone. But nothing retried the other kind, so a
# single lost packet was a dark room; and every one of them spent the full
# five-second timeout first, 164 of them at one light.
d.store.set_meta('managed', json.dumps({'plugs': [
    {'name': 'Light-Test', 'host': '127.0.0.1:19871', 'switch_id': 0, 'kind': 'plug',
     'host_state': 'enabled'}], 'sensors': []}))
d.reload_devices()
_probe = d.plugs['Light-Test']
_probe.failures = 0
BOX['sets'] = []
BOX['swallow'] = 1                           # the first command goes nowhere
_t0 = time.time()
_ok, _said = d.set_plug_output(_probe, True, 'a test')
_took = (time.time() - _t0) * 1000
BOX['swallow'] = 0
check(_ok and BOX['sets'], 'a command lost on the way was never asked again, so the light stayed '
                           'dark: %r' % (_said,))
check(_took < 2500, 'the light came on, but only after %.0f ms' % _took)
print('a command lost on the way is asked again: the light comes on in %.0f ms' % _took)

# ...and a Toggle is NOT asked again, whatever happens: the box may have had
# the first one, and the light would end up where it started.
BOX['sets'] = []
BOX['toggles'] = 0
BOX['toggle_delay'] = 1.4                    # slower than the first rung of the ladder
_t0 = time.time()
d.toggle_plug(_probe, 'a test')
BOX['toggle_delay'] = 0.0
check(BOX['toggles'] == 1, 'a slow toggle was sent %d time(s), so the light may have gone back to '
                           'where it started' % BOX['toggles'])
print('a toggle that is slow to answer is sent once, not twice')

# ...and a box whose last readings all failed is given up on in a moment,
# rather than holding whoever pressed the button for the whole timeout.
_hole = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
_hole.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
_hole.bind(('127.0.0.1', 19877))
_hole.listen(8)                              # accepts and never answers: a box off the air
d.store.set_meta('managed', json.dumps({'plugs': [
    {'name': 'Light-Test', 'host': '127.0.0.1:19871', 'switch_id': 0, 'kind': 'plug',
     'host_state': 'enabled'},
    {'name': 'Light-Gone', 'host': '127.0.0.1:19877', 'switch_id': 0, 'kind': 'plug',
     'host_state': 'enabled'}], 'sensors': []}))
d.reload_devices()
_gone = d.plugs['Light-Gone']
_gone.failures = 5                           # as three failed readings leave it
_t0 = time.time()
d.set_plug_output(_gone, True, 'a test')
_gave_up = (time.time() - _t0) * 1000
check(_gave_up < 2000, 'a box known to be off the air held the command %.0f ms' % _gave_up)
print('a box known to be off the air is given up on in %.0f ms' % _gave_up)
_hole.close()
d.store.set_meta('managed', json.dumps({'plugs': [
    {'name': 'Light-Test', 'host': '127.0.0.1:19871', 'switch_id': 0, 'kind': 'plug',
     'host_state': 'enabled'}], 'sensors': []}))
d.reload_devices()

# -- 5.16: nothing on the way to a light waits on the journal or the disk ----
# A rule writes its line and THEN sends the command; a press does the same; the
# broker's own thread writes a line for what it hears, and while it is writing
# no Zigbee command can leave at all. Every one of those lines was written by
# the thread that said it: into the journal, a pipe journald empties when it
# gets round to it, and into a file that lands in the page cache only until a
# backup has the disk busy. With a journal taking 150 ms over a line, a sensor
# reached its light in 154 ms every time instead of 3.
d.store.set_meta('managed', json.dumps({'plugs': [
    {'name': 'Light-Test', 'host': '127.0.0.1:19871', 'switch_id': 0, 'kind': 'plug',
     'host_state': 'enabled'}], 'sensors': []}))
d.reload_devices()
d.store.set_meta('rules', json.dumps([
    {'id': 'r-j-on', 'device': 'zigbee:PIR-Test', 'key': 'occupancy', 'op': '==', 'value': 1,
     'plug': 'Light-Test', 'do': 'on', 'enabled': True, 'cooldown_s': 0},
    {'id': 'r-j-off', 'device': 'zigbee:PIR-Test', 'key': 'occupancy', 'op': '==', 'value': 0,
     'plug': 'Light-Test', 'do': 'off', 'enabled': True, 'cooldown_s': 0}]))
BOX.update({'poll_delay': 0.0, 'set_delay': 0.0, 'swallow': 0, 'busy_until': 0.0, 'busy_times': 0})
zigmon.ShellyRPC._crowded.clear()


def _light_after_motion(rounds=5):
    """Motion, the light, and how long between: the middle of a few rounds."""
    took = []
    for _ in range(rounds):
        BOX['sets'] = []
        d.handle_zigbee('PIR-Test', json.dumps({'occupancy': False}).encode())
        waited(1, limit=3.0)
        time.sleep(0.2)
        BOX['sets'] = []
        _t0 = time.time()
        d.handle_zigbee('PIR-Test', json.dumps({'occupancy': True}).encode())
        _got = waited(1, limit=5.0)
        took.append((BOX['sets'][0][0] - _t0) * 1000 if _got is not None else 99999)
        time.sleep(0.2)
    took.sort()
    return took[len(took) // 2], took[-1]


class _StuckJournal(object):
    """A journal that has stopped reading for a moment: every write waits."""

    def __init__(self, delay):
        self.delay = delay

    def write(self, text):
        time.sleep(self.delay)
        return len(text)

    def flush(self):
        pass


_was_streams = sys.stdout, sys.stderr
_was_journal = zigmon.CONFIG.get('log_to_journal', True)
zigmon.CONFIG['log_to_journal'] = True
sys.stdout, sys.stderr = _StuckJournal(0.3), _StuckJournal(0.3)
try:
    _mid, _worst = _light_after_motion()
finally:
    sys.stdout, sys.stderr = _was_streams
    zigmon.CONFIG['log_to_journal'] = _was_journal
check(_mid < 100, 'with the journal taking 300 ms over a line, motion took %.0f ms to reach the '
                  'light (worst %.0f): the line was written on the way' % (_mid, _worst))
zigmon.log_drain(10.0)
print('a journal taking 300 ms over a line: motion still reaches the light in %.0f ms' % _mid)

# -- 5.16: two threads busy in Python do not stand in front of the light ------
# Python runs one thread at a time and hands over every five milliseconds
# unless told otherwise, and the way from a sensor to a light changes hands
# half a dozen times. With two threads busy - the page's status being built
# for each open tab after the very report that turned the light on, the words
# of a message - motion took 91 ms to reach the light, 143 at worst.
_busy = {'on': True}


def _python_busy():
    _x = 0
    while _busy['on']:
        for _i in range(20000):
            _x += _i * _i


_hogs = [threading.Thread(target=_python_busy, daemon=True) for _ in range(2)]
for _h in _hogs:
    _h.start()
try:
    _mid, _worst = _light_after_motion(7)
finally:
    _busy['on'] = False
check(_mid < 45, 'with two threads busy in Python, motion took %.0f ms to reach the light '
                 '(worst %.0f)' % (_mid, _worst))
print('two threads busy in Python: motion still reaches the light in %.0f ms (worst %.0f)'
      % (_mid, _worst))
d.store.set_meta('rules', json.dumps([]))


# -- 5.14: the bridge's device list is not taken in on the broker's thread -----
# Zigbee2MQTT publishes it retained, so a copy arrives on every connect and
# again on every rename, pairing or restart. Walking it cost the broker's own
# callback thread 226 ms cold and as much as 443 ms while the writer had a
# restart's worth of readings queued - and for that whole time the house is
# not heard and nothing can be published.
check(hasattr(d, 'devices_settled'),
      'the bridge device list is still taken in on the thread that hears the house')
_list = [{'ieee_address': '0xdev%04d' % i, 'friendly_name': 'Probe-%d' % i, 'type': 'EndDevice',
          'definition': {'model': 'M', 'vendor': 'V', 'exposes': [
              {'access': 5, 'label': 'Battery', 'name': 'battery', 'property': 'battery',
               'type': 'numeric', 'unit': '%'},
              {'access': 5, 'label': 'Temperature', 'name': 'temperature',
               'property': 'temperature', 'type': 'numeric', 'unit': '\u00b0C'}]}}
         for i in range(40)]
_t0 = time.perf_counter()
d.handle('zigbee2mqtt/bridge/devices', json.dumps(_list).encode())
_handed = (time.perf_counter() - _t0) * 1000
check(_handed < 20, 'the broker thread spent %.0f ms taking in the device list' % _handed)
check(d.devices_settled(10.0), 'the device list was never taken in at all')
check(d.store.device('0xdev0039') is not None,
      'the device list was handed to a worker and the worker lost it')
print('the bridge device list leaves the broker thread in %.1f ms and is taken in behind it'
      % _handed)


server.shutdown()
_api.stop() if hasattr(_api, "stop") else None

