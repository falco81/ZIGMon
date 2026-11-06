#!/usr/bin/env python3
"""Realtime at the edges: what makes a light come on late, twice, or not at all.

    python3 test/pass1_edges.py

An in-process daemon, a fake Shelly answering HTTP on 19410, and a fake broker
client that records every publish and lets the test answer a box's RPC over
MQTT the way a real box does (on zigmon/rpc). Each check below failed on 5.43.4.
"""
import collections
import json
import os
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ['zigmon']
import zigmon                                            # noqa: E402

PORT = 19410
BOX = {'output': False, 'calls': []}


class Box(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        method, params = body.get('method'), body.get('params') or {}
        BOX['calls'].append((time.time(), method, params))
        if method == 'Switch.Set' and BOX.get('refuse'):
            out = None
            raw = json.dumps({'id': body.get('id'), 'error': {'code': -109, 'message': 'refused'}}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if method == 'Switch.Set':
            out = {'was_on': BOX['output']}
            BOX['output'] = bool(params.get('on'))
        elif method == 'Switch.Toggle':
            out = {'was_on': BOX['output']}
            BOX['output'] = not BOX['output']
        elif method in ('Shelly.GetStatus', 'Switch.GetStatus'):
            out = {'switch:0': {'id': 0, 'output': BOX['output'], 'apower': 5.0, 'voltage': 230.0,
                                'aenergy': {'total': 1.0}}, 'id': 0, 'output': BOX['output'],
                   'apower': 5.0, 'mqtt': {'connected': True}}
        elif method == 'Shelly.GetDeviceInfo':
            out = {'id': 'shellyplug-edge', 'model': 'S3PL-00112EU', 'gen': 3, 'ver': '1.7.1'}
        else:
            out = {}
        raw = json.dumps({'id': body.get('id'), 'result': out}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        """The page test's levers: /refuse?on=1, /sets (when each Switch.Set came)."""
        if self.path.startswith('/refuse'):
            BOX['refuse'] = self.path.endswith('=1')
            out = {'refuse': BOX['refuse']}
        elif self.path.startswith('/rule'):
            # the house switches it (a rule, a button): when does the page show it
            at = time.time()
            threading.Thread(target=d.set_plug_output, args=(d.plugs['Light-Edge'], self.path.endswith('=1'),
                                                             'rule: the page test'), daemon=True).start()
            out = {'at': at}
        else:
            out = {'sets': [[c[0], c[2].get('on')] for c in BOX['calls'] if c[1] == 'Switch.Set'],
                   'output': BOX['output']}
        raw = json.dumps(out).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


server = ThreadingHTTPServer(('127.0.0.1', PORT), Box)
threading.Thread(target=server.serve_forever, daemon=True).start()

TMP = Path('/tmp/zigmon-pass1-edges')
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True)
zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(TMP / 'z.db'), 'api_port': PORT + 1,
                      'token_file': str(TMP / 'token'), 'pin': '1234', 'plugs': [], 'sensors': [],
                      'mqtt_host': '', 'backup_dir': str(TMP / 'backups'), 'log_to_journal': False})
d = zigmon.Daemon()


class Info(object):
    def __init__(self, mid):
        self.rc = 0
        self.mid = mid


class FakeBroker(object):
    """paho as far as the daemon uses it: publish() hands back an info with
    a message id, and a QoS 1 message stays in _out_messages until the
    broker acknowledges it - which is where paho keeps what it sends again
    after a reconnect."""

    def __init__(self):
        self.sent = []
        self.mid = 0
        self._out_messages = collections.OrderedDict()
        self._out_message_mutex = threading.Lock()
        self.answer = True            # the box answers its RPC over MQTT

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.mid += 1
        self.sent.append((time.time(), topic, payload, qos))
        if qos:
            m = type('Msg', (), {})()
            m.topic, m.payload, m.qos, m.mid = topic, payload, qos, self.mid
            with self._out_message_mutex:
                self._out_messages[self.mid] = m
        if topic.endswith('/rpc') and self.answer:
            body = json.loads(payload)
            if body.get('method') == 'Switch.Set':
                BOX['output'] = bool(body['params'].get('on'))
            elif body.get('method') == 'Switch.Toggle':
                BOX['output'] = not BOX['output']

            def reply(rid=body['id']):
                time.sleep(0.01)
                msg = type('M', (), {})()
                msg.topic, msg.payload, msg.retain = 'zigmon/rpc', json.dumps(
                    {'id': rid, 'src': 'edge', 'result': {}}).encode(), False
                d._on_message(None, None, msg)
            threading.Thread(target=reply, daemon=True).start()
        return Info(self.mid)

    def subscribe(self, *a, **k):
        return (0, 1)

    def acked(self):
        with self._out_message_mutex:
            self._out_messages.clear()


BROKER = FakeBroker()
d.client = BROKER
d.connected = True


FAILED = []


def check(ok, what):
    """PASS1_KEEP_GOING=1 says every failure and goes on, so each check can
    be seen failing on the code from before its fix."""
    if not ok:
        if os.environ.get('PASS1_KEEP_GOING'):
            FAILED.append(what)
            print('FAIL: ' + what)
            return
        raise AssertionError(what)


def plug(**extra):
    entry = dict({'name': 'Light-Edge', 'host': '127.0.0.1:%d' % PORT, 'switch_id': 0, 'kind': 'plug',
                  'host_state': 'enabled'}, **extra)
    d.store.set_meta('managed', json.dumps({'plugs': [entry], 'sensors': []}))
    d.reload_devices()
    p = d.plugs['Light-Edge']
    p.output, p.flat, p.generated = (1 if BOX['output'] else 0), {'switch.output': BOX['output']}, time.time()
    return p


def http_calls(since, method='Switch'):
    return [c for c in BOX['calls'] if c[0] >= since and str(c[1]).startswith(method)]


def rpc_published(since):
    return [json.loads(s[2]) for s in BROKER.sent if s[0] >= since and s[1].endswith('/rpc')]


def settle(t=0.6):
    time.sleep(t)


# ============================================================================
# 1. A pulse goes the way every other command to the box goes
# ============================================================================
# pulse_plug spoke HTTP whatever the box was: with "MQTT only" on - which says
# in so many words that nothing goes over HTTP - and on a box on the broker,
# which paid a TCP round trip for each half of the pulse instead of a publish.
zigmon.CONFIG['mqtt_only'] = True
p = plug(mqtt=True, mqtt_name='light-edge')
t0 = time.time()
ok, msg = d.pulse_plug(p, 200)
check(ok, 'a pulse over the broker failed: %s' % msg)
check(not http_calls(t0, 'Switch.Set'), 'a pulse to an MQTT-only box went over HTTP: %r'
      % [c[1] for c in http_calls(t0)])
legs = [m['params'].get('on') for m in rpc_published(t0) if m['method'] == 'Switch.Set']
check(legs == [True, False], 'the pulse over the broker was %r, not on then off' % legs)
settle()
zigmon.CONFIG['mqtt_only'] = False
p = plug(mqtt=True, mqtt_name='light-edge')
t0 = time.time()
ok, msg = d.pulse_plug(p, 200)
check(ok and not http_calls(t0, 'Switch.Set'), 'a pulse to a box on the broker went over HTTP')
settle()
print('a pulse goes over the broker to a box set up for it, and never over HTTP with MQTT only')

# ============================================================================
# 2. A toggle with "MQTT only" on: no HTTP, whatever is known
# ============================================================================
zigmon.CONFIG['mqtt_only'] = True
p = plug(mqtt=True, mqtt_name='light-edge')
p.output = None                                   # not heard from yet
t0 = time.time()
ok, msg = d.toggle_plug(p)
check(ok, 'a toggle over the broker of a socket not heard from yet failed: %s' % msg)
check(not http_calls(t0), 'a toggle with MQTT only went over HTTP (state not known): %r'
      % [c[1] for c in http_calls(t0)])
check([m['method'] for m in rpc_published(t0)] == ['Switch.Toggle'],
      'the toggle over the broker was %r' % [m['method'] for m in rpc_published(t0)])
settle()
d.connected = False
t0 = time.time()
ok, msg = d.toggle_plug(p)
d.connected = True
check(not ok and not http_calls(t0), 'a toggle with MQTT only and the broker down went over HTTP')
zigmon.CONFIG['mqtt_only'] = False
settle()
print('a toggle with MQTT only stays on the broker: state unknown, or broker down (refused)')

# ============================================================================
# 3. A toggle right behind a command whose answer was lost
# ============================================================================
# A rule says "on" over the broker and the box's answer never comes; a press
# toggles it off half a second later. The toggle went beside the socket's
# count of commands, so two seconds after the "on" its HTTP fallback ran as
# if nothing newer had been sent - and the light came back on.
p = plug(mqtt=True, mqtt_name='light-edge')
BOX['output'] = False
p.output = 0
BROKER.answer = False
d._mqtt_road_off.clear()
t0 = time.time()
d.set_plug_output(p, True, 'rule: test')
time.sleep(0.3)
d.toggle_plug(p, 'button Edge (single)')
time.sleep(2.8)                                   # both confirmations have given up
BROKER.answer = True
late = [c[2].get('on') for c in http_calls(t0, 'Switch.Set')]
check(True not in late, 'the lost "on" was sent over HTTP after the toggle had said off: %r' % late)
check(BOX['output'] is False, 'the light ended %s after on, then a toggle' % BOX['output'])
d._mqtt_road_off.clear()
settle()
print('a toggle behind a lost command: the old one is not sent again behind it (%r)' % late)

# ============================================================================
# 4. Commands from before a broker reconnect are not sent late
# ============================================================================
# paho keeps every QoS 1 message the broker has not acknowledged and sends it
# again the moment it is connected once more (checked against paho 2.1 and a
# broker that dropped the link: the "ON" went out again 3.8 s later, marked
# DUP). A light came on when the link came back - twenty or forty seconds
# later for a link that died quietly - and a Shelly whose command had already
# gone over HTTP had the old one land on top of a newer one.
BROKER.acked()
old = d.say('zigbee2mqtt/Lamp-Edge/set', json.dumps({'state': 'ON'}), qos=1)
d.__dict__.setdefault('_cmd_mids', {})
if old.mid in d._cmd_mids:
    d._cmd_mids[old.mid] -= 30                    # sent thirty seconds ago, never acknowledged
fresh = d.say('zigbee2mqtt/Lamp-Edge/set', json.dumps({'state': 'OFF'}), qos=1)
other = d.say('zigmon/ping', '1', qos=1)          # not a command: paho's business
d.connected = False
d._on_connect(BROKER, None, {}, 0)
check(d.connected, 'the reconnect did not go through')
check(old.mid not in BROKER._out_messages, 'a command from thirty seconds before the reconnect '
      'was left for paho to send again')
check(fresh.mid in BROKER._out_messages, 'a command sent a moment ago was dropped at the reconnect')
check(other.mid in BROKER._out_messages, 'something that is not a command was dropped at the reconnect')
BROKER.acked()
print('a reconnect sends nothing late: the command from before it is dropped, a fresh one kept')

# ============================================================================
# 5. The page: click -> command -> tile, and a switch that did not happen
# ============================================================================
# The tile is painted the moment it is pressed and the answer confirms it. When
# the switch did NOT happen - the box said no, or the PIN box was dismissed -
# the redraw that was to put it right found the socket exactly as the drawing
# before had it, kept the card, and the card went on saying "on" over a
# socket that was off until something else about it changed.
import socket                                            # noqa: E402
import subprocess                                        # noqa: E402

API_PORT, PHP_PORT = PORT + 1, PORT + 3
PROCS = []


def finish(code):
    for proc in PROCS:
        try:
            proc.terminate()
            proc.wait(5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    shutil.rmtree(str(TMP), ignore_errors=True)
    if FAILED:
        print('pass1_edges: %d failed' % len(FAILED))
        os._exit(1)
    print('pass1_edges: %s' % ('all good' if code == 0 else 'failed'))
    os._exit(code)


node_root = ''
try:
    node_root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True,
                               stdin=subprocess.DEVNULL, timeout=30).stdout.strip()
except Exception:
    pass
if not shutil.which('php') or not node_root or not (Path(node_root) / 'playwright').exists():
    print('the page: skipped - php or playwright is not here')
    finish(0)

zigmon.CONFIG.update({'api_host': '127.0.0.1', 'pin': '', 'state_dir': str(TMP / 'state'),
                      'login_tries': 50, 'session_idle_min': 240, 'session_hours': 720})
(TMP / 'state').mkdir(exist_ok=True)
d.notify = lambda *a, **k: None
d.connected = False                     # the socket below is HTTP only
BOX['output'] = False
p = plug()
p.output = 0
api = zigmon.ApiServer(d)
api.start()
d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)


def keep_reading():
    while True:
        try:
            d.poll_plug(d.plugs['Light-Edge'], force=True)   # what the poll loop does
        except Exception:
            pass
        time.sleep(1.5)


threading.Thread(target=keep_reading, daemon=True).start()
WEB = TMP / 'web'
shutil.copytree(str(Path(__file__).resolve().parent.parent / 'web'), str(WEB))
relay = (WEB / 'zigmon-api.php').read_text()
relay = relay.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
relay = relay.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (TMP / 'token'))
(WEB / 'zigmon-api.php').write_text(relay)
(TMP / 'token').write_text(d.token)
php = None
for _ in range(3):
    php = subprocess.Popen(['php', '-d', 'opcache.enable_cli=1', '-S', '127.0.0.1:%d' % PHP_PORT, '-t', str(WEB)], cwd=str(WEB),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                           env=dict(os.environ, PHP_CLI_SERVER_WORKERS='6'))
    for _ in range(50):
        try:
            socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    time.sleep(0.3)
    if php.poll() is None:
        PROCS.append(php)
        break
    time.sleep(3)                       # "Address already in use": wait and go again
else:
    check(False, 'php -S could not serve the page')
    finish(1)

PAGE_JS = r'''
const { chromium } = require('playwright');
const cfg = JSON.parse(process.env.E_CFG);
const out = {errors: []};
const wait = ms => new Promise(r => setTimeout(r, ms));
const box = async path => (await fetch(cfg.box + path)).json();
const tile = p => p.evaluate(() => {
  const c = document.querySelector('#sockets .card.socket[data-plug="Light-Edge"]');
  if (!c) return null;
  const l = c.querySelector('.socket-label');
  return {on: c.classList.contains('on'), pending: c.classList.contains('pending'),
          word: l ? l.textContent.trim().split(' ').pop() : ''};
});
(async () => {
  const b = await chromium.launch();
  try {
    const ctx = await b.newContext({viewport: {width: 1400, height: 900}});
    const p = await ctx.newPage();
    p.setDefaultTimeout(15000);
    p.on('pageerror', e => out.errors.push(String(e).slice(0, 200)));
    await p.goto(cfg.base + '/');
    await p.evaluate(async () => fetch('?api=login', {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: 'owner', password: 'owner pass 12'})}));
    await p.goto(cfg.base + '/#plugs');
    await p.reload();
    await wait(2000);
    out.before = await tile(p);
    // (1) click -> the box -> the tile confirmed: on, off, on (it ends on)
    out.commandMs = []; out.tileMs = [];
    for (const want of [true, false, true]) {
      const sets0 = (await box('/sets')).sets.length;
      const t0 = await p.evaluate(() => {
        const b = document.querySelector('#sockets .card.socket[data-plug="Light-Edge"] .socket-toggle');
        const t = Date.now(); b.click(); return t;
      });
      if (want && !out.painted) out.painted = await tile(p);
      let confirmed = null;
      for (let i = 0; i < 400; i++) {
        const t = await tile(p);
        if (t && t.on === want && !t.pending && t.word === (want ? 'on' : 'off')) { confirmed = Date.now(); break; }
        await wait(3);
      }
      const sets = (await box('/sets')).sets;
      out.commandMs.push(sets.length > sets0 ? Math.round(sets[sets0][0] * 1000 - t0) : null);
      out.tileMs.push(confirmed ? confirmed - t0 : null);
      await wait(1200);
    }
    // (1b) switched by the house, not the page: on the screen how soon
    out.houseMs = [];
    for (const want of [false, true]) {
      const at = (await box('/rule?on=' + (want ? 1 : 0))).at;
      let seen = null;
      for (let i = 0; i < 1000; i++) {
        const t = await tile(p);
        if (t && t.on === want && t.word === (want ? 'on' : 'off')) { seen = Date.now(); break; }
        await wait(3);
      }
      out.houseMs.push(seen ? Math.round(seen - at * 1000) : null);
      await wait(1200);
    }
    // (2) the box says no: the tile goes back to what the socket is
    await box('/refuse?on=1');
    await p.click('#sockets .card.socket[data-plug="Light-Edge"] .socket-toggle');
    await wait(2500);
    out.refused = await tile(p);
    out.refusedBox = (await box('/sets')).output;
    await box('/refuse?on=0');
    // (3) signed out, the PIN box dismissed: nothing was sent, the tile as it was
    await p.evaluate(() => fetch('?api=logout', {method: 'POST', credentials: 'same-origin'}));
    await p.evaluate(() => { try { lockNow(); } catch (e) {} });
    await wait(1500);
    out.beforeDismiss = await tile(p);
    await p.click('#sockets .card.socket[data-plug="Light-Edge"] .socket-toggle');
    await wait(400);
    out.asked = await p.evaluate(() => !document.getElementById('pinback').hidden);
    await p.keyboard.press('Escape');
    await wait(2000);
    out.dismissed = await tile(p);
    out.dismissedBox = (await box('/sets')).output;
    await ctx.close();
  } catch (e) {
    out.error = String(e && e.stack || e).slice(0, 600);
  }
  console.log(JSON.stringify(out));
  await b.close();
})();
'''
(TMP / 'page.js').write_text(PAGE_JS)
got = subprocess.run(['node', str(TMP / 'page.js')], capture_output=True, text=True, timeout=300, cwd=str(TMP),
                     stdin=subprocess.DEVNULL,
                     env=dict(os.environ, NODE_PATH=node_root, E_CFG=json.dumps(
                         {'base': 'http://127.0.0.1:%d' % PHP_PORT, 'box': 'http://127.0.0.1:%d' % PORT})))
try:
    o = json.loads((got.stdout.strip().splitlines() or ['{}'])[-1])
except ValueError:
    o = {'error': (got.stdout + got.stderr)[-800:]}
if os.environ.get('PASS1_DUMP'):
    print(json.dumps(o, indent=1))
check(not o.get('error'), 'the page could not be driven: %s' % o.get('error'))
check(not o.get('errors'), 'the page threw: %r' % o.get('errors'))
check((o.get('before') or {}).get('on') is False, 'the socket did not start off on the page: %r' % o.get('before'))
check((o.get('painted') or {}).get('on') is True, 'the tile did not move with the click: %r' % o.get('painted'))
_cmd, _tile = o.get('commandMs') or [None], o.get('tileMs') or [None]
check(None not in _cmd and sorted(_cmd)[len(_cmd) // 2] < 400, 'click to the box took %s ms' % _cmd)
check(None not in _tile and sorted(_tile)[len(_tile) // 2] < 800,
      'click to the tile confirmed took %s ms' % _tile)
_house = o.get('houseMs') or [None]
check(None not in _house and max(_house) < 800, 'switched by the house, on the page after %s ms' % _house)
print('the page: click -> box %s ms, click -> tile confirmed %s ms; switched by the house -> tile %s ms'
      % (o.get('commandMs'), o.get('tileMs'), _house))
check(o.get('refusedBox') is True, 'the refused switch reached the box after all: %r' % o.get('refusedBox'))
check((o.get('refused') or {}).get('on') is True and (o.get('refused') or {}).get('word') == 'on',
      'the box refused "off" and the tile still says %r over a socket that is on' % o.get('refused'))
check(o.get('asked') is True, 'signed out, the click did not ask for a sign-in')
check((o.get('dismissed') or {}).get('on') is True and (o.get('dismissed') or {}).get('word') == 'on',
      'the sign-in was dismissed and the tile says %r over a socket that is on' % o.get('dismissed'))
print('the page: a refused switch and a dismissed sign-in put the tile back to what the socket is')
finish(0)
