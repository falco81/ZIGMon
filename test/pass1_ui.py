#!/usr/bin/env python3
"""5.44, pass 1: the dashboard driven end to end in a 65-device house. Fails on
5.43.4's page.

    python3 test/pass1_ui.py          (PASS1_PAGE=old: the same checks on
                                       5.43.4's page - every one must fail;
                                       PASS1_DUMP=1 prints what was measured)

  * the rules editor of a house with thirty rules held 120 lists of every
    device and target, eleven thousand options: drawing it took 300 ms on a
    desktop and over a second on an iPad, and showing the section again cost
    140 ms of style work. A long list now goes into its select when the
    select is opened (by the pointer, a finger, the keyboard or a script),
    the closed select as wide as before and showing the same entry;
  * Alerts - Add message, then a name typed into "by text to": the box was
    given no status, and the first letter threw (whoCandidates);
  * the account's popup opened with the focus on Sign out (Lock now): Enter
    or a Space signed the person out; it is on Close;
  * the performance meter: an ask that hung past its 5 s and then failed left
    no next ask, and the meter stood still until a reload;
  * signed out, a socket that is on, its button pressed and the sign-in
    dismissed with Escape: the card went on saying "off";
  * signed out, a room's slider on the Heating tab (and a valve's on its
    card) dragged and the sign-in dismissed: the slider stayed where it was
    dragged, saying a temperature the room was not holding;
  * the Devices tab: a rename left with Escape (or its sign-in dismissed)
    left the box in the row, and a second rename of that device did nothing.

Ports 19430 (the daemon), 19431 (php -S), 19432 (a Shelly box).
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-pass1-ui-'))
API_PORT, PHP_PORT, BOX_PORT = 19430, 19431, 19432
AGAINST_OLD = os.environ.get('PASS1_PAGE') == 'old'
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


STOP = threading.Event()


def finish():
    STOP.set()
    for p in PROCS:
        try:
            p.terminate()
            p.wait(5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    shutil.rmtree(str(W), ignore_errors=True)
    print('pass1_ui: %s' % ('%d failed' % len(bad) if bad else 'all good'))
    os._exit(1 if bad else 0)


__import__('atexit').register(lambda: [p.kill() for p in PROCS if p.poll() is None])

box = subprocess.Popen([sys.executable, str(HERE / 'test' / 'mockplug.py'), str(BOX_PORT)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
PROCS.append(box)

sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'sensors': [], 'mqtt_host': '',
                      'log_file': str(W / 'zigmon.log'), 'log_to_journal': False,
                      'state_dir': str(W / 'state'), 'login_tries': 50, 'login_wait_min': 1,
                      'session_idle_min': 240, 'session_hours': 720, 'public_view': True, 'weather': False,
                      'plugs': [{'name': 'Plug-Lamp', 'host': '127.0.0.1:%d' % BOX_PORT}]})
(W / 'state').mkdir()
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)
d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)

# ---- the house: 65 Zigbee devices, thirty rules, ten scenes, a room ------------------------
LIGHT = {'type': 'light', 'features': [{'type': 'binary', 'property': 'state', 'name': 'state', 'value_on': 'ON',
                                        'value_off': 'OFF', 'access': 7}]}
SWITCH = {'type': 'switch', 'features': [{'type': 'binary', 'property': 'state', 'name': 'state', 'value_on': 'ON',
                                          'value_off': 'OFF', 'access': 7}]}
BATT = {'type': 'numeric', 'property': 'battery', 'name': 'battery', 'unit': '%'}
THERMO = [{'type': 'numeric', 'property': 'temperature', 'name': 'temperature', 'unit': '°C'},
          {'type': 'numeric', 'property': 'humidity', 'name': 'humidity', 'unit': '%'}, BATT]
PIR = [{'type': 'binary', 'property': 'occupancy', 'name': 'occupancy', 'value_on': True, 'value_off': False}, BATT]
DOOR = [{'type': 'binary', 'property': 'contact', 'name': 'contact', 'value_on': False, 'value_off': True}, BATT]
BUTTON = [{'type': 'enum', 'property': 'action', 'name': 'action', 'values': ['single', 'double', 'hold']}, BATT]
devs, first = [], {}


def add(name, kind, exposes, model, payload):
    devs.append({'ieee_address': '0x%016x' % (len(devs) + 1), 'friendly_name': name, 'type': kind,
                 'definition': {'model': model, 'vendor': 'Acme', 'description': model, 'exposes': exposes}})
    first[name] = payload


for i in range(16):
    add('Light-%02d' % i, 'Router', [LIGHT], 'LED1545G12', {'state': 'OFF'})
for i in range(8):
    add('Switch-%02d' % i, 'Router', [SWITCH], 'ZBMINI', {'state': 'OFF'})
for i in range(16):
    add('Temp-%02d' % i, 'EndDevice', THERMO, 'WSDCGQ11LM', {'temperature': 21.0, 'humidity': 44, 'battery': 90})
for i in range(10):
    add('PIR-%02d' % i, 'EndDevice', PIR, 'RTCGQ11LM', {'occupancy': False, 'battery': 80})
for i in range(10):
    add('Door-%02d' % i, 'EndDevice', DOOR, 'MCCGQ11LM', {'contact': True, 'battery': 70})
for i in range(5):
    add('Button-%02d' % i, 'EndDevice', BUTTON, 'WXKG11LM', {'battery': 60})
d.handle_zigbee('bridge/devices', json.dumps(devs).encode())
d.devices_settled(10)
for n, payload in first.items():
    d.handle_zigbee(n, json.dumps(payload).encode())
ids = {x['name']: x['id'] for x in d.store.devices()}
d.save_rules([{'device': ids['PIR-%02d' % (i % 10)], 'key': 'occupancy', 'op': '==', 'value': 1,
               'plug': 'Plug-Lamp', 'do': 'on', 'cooldown_s': 60, 'enabled': True,
               'device2': ids['Temp-%02d' % (i % 16)] if i % 3 == 0 else '', 'key2': 'temperature',
               'op2': '<', 'value2': 20} for i in range(30)])
d.store.set_meta('scenes', json.dumps([{'id': 'sc%d' % i, 'name': 'Scene %d' % i, 'enabled': True,
                                        'actions': [{'target': 'Plug-Lamp', 'do': 'on'}, {'target': 'Plug-Lamp', 'do': 'off'}]}
                                       for i in range(10)]))
d.store.set_meta('people', json.dumps([{'id': 'p1', 'name': 'Jana', 'enabled': True, 'phone': '+420777123456',
                                        'macs': ['aa:bb:cc:dd:ee:01']}]))
d.save_rooms([{'name': 'Living room'}])
d.save_config_overrides({'perf_meter': 1})
d._running = True
threading.Thread(target=d.plug_loop, daemon=True).start()     # the socket is read, and switched


def reports():
    # the house keeps talking: a thermometer a fifth of a second
    t = 0
    while not STOP.is_set():
        t += 1
        try:
            d.handle_zigbee('Temp-%02d' % (t % 16), json.dumps({'temperature': 20 + t % 30 / 10.0, 'humidity': 44,
                                                                 'battery': 90}).encode())
        except Exception:
            pass
        time.sleep(0.2)


threading.Thread(target=reports, daemon=True).start()

# ---- the page (this one, or 5.43.4's) relaying to the daemon above ----------------------------
NOW = W / 'web'
shutil.copytree(str(HERE / 'web'), str(NOW))
if AGAINST_OLD:
    pack = HERE / 'release' / 'zigmon-5.43.4.tar.gz'
    if not pack.exists():
        check(False, 'no release package of 5.43.4 to compare with')
        finish()
    with tarfile.open(str(pack)) as tar:
        for name in ('index.php', 'zigmon-api.php'):
            (NOW / name).write_bytes(tar.extractfile('zigmon-5.43.4/web/' + name).read())
text = (NOW / 'zigmon-api.php').read_text()
text = text.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
text = text.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
(NOW / 'zigmon-api.php').write_text(text)
(W / 'token').write_text(d.token)


def serve(folder, port):
    for _ in range(3):
        p = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % port, '-t', str(folder)], cwd=str(folder),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                             env=dict(os.environ, PHP_CLI_SERVER_WORKERS='6'))
        for _ in range(50):
            try:
                socket.create_connection(('127.0.0.1', port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        time.sleep(0.3)
        if p.poll() is None:
            PROCS.append(p)
            return p
        time.sleep(3)
    return None


if not shutil.which('php') or not serve(NOW, PHP_PORT):
    check(False, 'php -S could not serve the page')
    finish()
# the socket read at least once, so its card is drawn as a socket that answers
time.sleep(3)

PAGE_JS = r'''
const { chromium } = require('playwright');
const cfg = JSON.parse(process.env.H_CFG);
const out = {errors: []};
const wait = ms => new Promise(r => setTimeout(r, ms));
async function open(b, as, hash) {
  const ctx = await b.newContext({viewport: {width: 1600, height: 1000}});
  const p = await ctx.newPage();
  p.setDefaultTimeout(15000);
  p.on('pageerror', e => out.errors.push(String(e).slice(0, 200)));
  await p.goto(cfg.base + '/');
  if (as) await p.evaluate(async c => fetch('?api=login', {method: 'POST', credentials: 'same-origin',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: c[0], password: c[1]})}), ['owner', 'owner pass 12']);
  await p.goto(cfg.base + '/' + (hash || ''));
  await p.reload();
  await wait(1500);
  return [ctx, p];
}
(async () => {
  const b = await chromium.launch();
  try {
    // (1) the rules editor of thirty rules, and the scenes
    {
      const [ctx, p] = await open(b, true);
      await p.evaluate(() => {
        window.__lt = [];
        new PerformanceObserver(l => l.getEntries().forEach(e => window.__lt.push(Math.round(e.duration)))).observe({type: 'longtask'});
        const was = renderRules;
        window.__rr = [];
        renderRules = function () { const t0 = performance.now(); try { return was.apply(this, arguments); } finally { window.__rr.push(Math.round(performance.now() - t0)); } };
        showTab('control'); showControlSection('auto-rules');
      });
      await wait(3000);
      out.rules = await p.evaluate(() => {
        STATE.paused = true;
        const host = document.getElementById('rules-list');
        const sels = Array.from(host.querySelectorAll('select'));
        const dev = host.querySelector('.rule-row:not(.bind-head) select');
        const before = {value: dev.value, text: (dev.querySelector('option:checked') || {}).textContent,
                        width: Math.round(dev.getBoundingClientRect().width)};
        const res = {selects: sels.length, options: host.querySelectorAll('option').length, renders: window.__rr.slice(),
                     longtasks: window.__lt.slice(), before: before, rows: host.querySelectorAll('.rule-row:not(.bind-head)').length};
        // every select as wide, and showing the same, as with its whole list in it
        const shown = sels.map(s => [Math.round(s.getBoundingClientRect().width), s.value]);
        // showing the section again: the style work for it
        const sec = host.closest('[data-sec]');
        sec.hidden = true; void document.body.offsetHeight;
        let t0 = performance.now(); sec.hidden = false; void document.body.offsetHeight; res.reshowMs = Math.round(performance.now() - t0);
        // the first select opened from the keyboard: its whole list, the same entry chosen
        dev.focus();
        res.focused = {options: dev.querySelectorAll('option').length, value: dev.value};
        dev.blur();
        sels.forEach(s => { if (typeof fillSelectNow === 'function') fillSelectNow(s); });
        const full = sels.map(s => [Math.round(s.getBoundingClientRect().width), s.value]);
        res.sameLook = shown.filter((x, i) => x[0] !== full[i][0] || x[1] !== full[i][1]).length;
        res.optionsFilled = host.querySelectorAll('option').length;
        STATE.paused = false;
        return res;
      });
      // a list nobody has opened, picked from: by a script in the page (its value
      // set), and by Playwright, which reads the options from a world of its own
      // and so focuses the select first, as a person's Tab does
      const target = await p.evaluate(() => {
        const s = document.querySelectorAll('#rules-list .rule-row:not(.bind-head)')[1].querySelector('select');
        const o = Array.from(s.querySelectorAll('option')).filter(o => o.value && o.value !== s.value)[3];
        return o ? o.value : null;
      });
      await p.evaluate(() => { RULES.dirty = false; renderRules(STATE.status); });   // drawn afresh: unopened again
      const second = (await p.$$('#rules-list .rule-row:not(.bind-head)'))[1];
      const sel = await second.$('select');
      out.rules.scripted = await p.evaluate(t => {
        const s = document.querySelectorAll('#rules-list .rule-row:not(.bind-head)')[2].querySelector('select');
        s.value = t; return s.value === t;
      }, target);
      await sel.focus();
      await sel.selectOption(target);
      await wait(300);
      out.rules.picked = await p.evaluate(t => ({value: document.querySelectorAll('#rules-list .rule-row:not(.bind-head)')[1].querySelector('select').value,
        want: t, note: document.getElementById('rule-note').textContent}), target);
      await p.evaluate(() => { RULES.dirty = false; RULES.rows = null; showControlSection('auto-scenes'); });
      await wait(2500);
      out.scenes = await p.evaluate(() => ({options: document.querySelectorAll('#scenes-list option').length,
                                           actions: document.querySelectorAll('#scenes-list select').length}));
      await ctx.close();
    }
    // (2) Alerts: a message added, a name typed into "by text to"
    {
      const [ctx, p] = await open(b, true);
      await p.evaluate(() => { showTab('control'); showControlSection('msg-alerts'); });
      await wait(1500);
      const before = out.errors.length;
      await p.click('#message-add');
      await wait(300);
      await p.click('#messages-list .msg-smsto');
      await p.keyboard.type('Ja', {delay: 120});
      await wait(400);
      out.who = {errors: out.errors.slice(before), offered: await p.evaluate(() =>
        Array.from(document.querySelectorAll('.whopick button')).map(b => b.textContent))};
      // the account's popup opened from the keyboard, and Enter
      await p.keyboard.press('Escape');
      await p.evaluate(() => { document.activeElement && document.activeElement.blur && document.activeElement.blur(); accountMenu(); });
      await wait(400);
      out.acct = {focus: await p.evaluate(() => (document.activeElement || {}).textContent || '')};
      await p.keyboard.press('Enter');
      await wait(1200);
      out.acct.after = await p.evaluate(() => ({open: !document.getElementById('zmodal').hidden, who: !!LOCK.who}));
      await ctx.close();
    }
    // (3) the performance meter, one ask hung for 6.5 s and then failed
    {
      const [ctx, p] = await open(b, true);
      await wait(2500);
      out.meter = await p.evaluate(async () => {
        const shown = !document.getElementById('hload').hidden;
        let asks = 0, hung = false;
        const real = window.fetch;
        window.fetch = function (url) {
          if (/api=perf/.test(String(url))) {
            asks++;
            if (!hung) { hung = true; return new Promise((_, no) => setTimeout(() => no(new TypeError('Failed to fetch')), 6500)); }
          }
          return real.apply(this, arguments);
        };
        await new Promise(r => setTimeout(r, 22000));
        return {shown, asks};
      });
      await ctx.close();
    }
    // (4) signed out: the socket, then the room's slider and a valve's, each dismissed with Escape
    {
      const [ctx, p] = await open(b, false);
      await p.evaluate(() => showTab('plugs'));
      await wait(1500);
      const card = () => p.evaluate(() => { const c = document.querySelector('#tab-plugs .card.socket');
        return {on: c.classList.contains('on'), pending: c.classList.contains('pending'), output: (STATE.status.plugs || [])[0].output,
                asked: !document.getElementById('pinback').hidden}; });
      out.socket = {before: await card()};
      await p.click('#tab-plugs .card.socket .socket-toggle');
      await wait(500);
      out.socket.asked = await card();
      await p.keyboard.press('Escape');
      await wait(3000);
      out.socket.after = await card();
      await p.evaluate(() => showTab('heating'));
      await wait(1500);
      const slider = () => p.evaluate(() => { const s = document.querySelector('#heating-rooms .heat-slider');
        const r = ((STATE.status.heating || {}).rooms || [])[0] || {};
        return s ? {value: +s.value, read: s.parentNode.querySelector('.heat-read').textContent, room: r.wanted_c,
                    asked: !document.getElementById('pinback').hidden} : null; });
      out.room = {before: await slider()};
      await p.evaluate(() => { const s = document.querySelector('#heating-rooms .heat-slider');
        s.value = 27; s.dispatchEvent(new Event('input')); s.dispatchEvent(new Event('change')); });
      await wait(500);
      out.room.asked = await slider();
      await p.keyboard.press('Escape');
      await wait(3000);
      out.room.after = await slider();
      // the Devices tab: a device renamed in its row, Escape; again, Enter, the sign-in dismissed
      await p.evaluate(() => showTab('devices'));
      await wait(1500);
      const cell = () => p.evaluate(() => { const d = STATE.status.devices.filter(x => x.name === 'Temp-05')[0];
        const c = document.getElementById('name-' + cssId(d.id)); return {box: !!c.querySelector('input'), asked: !document.getElementById('pinback').hidden}; });
      const rename = () => p.evaluate(() => renameDevice(STATE.status.devices.filter(x => x.name === 'Temp-05')[0]));
      out.rename = {};
      await rename(); await wait(300);
      out.rename.open = await cell();
      await p.keyboard.press('Escape'); await wait(1500);
      out.rename.esc = await cell();
      await rename(); await wait(300);
      out.rename.again = await cell();
      await p.keyboard.press('End'); await p.keyboard.type('X'); await p.keyboard.press('Enter'); await wait(600);
      out.rename.asked = await cell();
      await p.keyboard.press('Escape'); await wait(1500);
      out.rename.dismissed = await cell();
      // a valve in no room: its own target on its card
      out.valve = await p.evaluate(async () => {
        const d = {id: 'trv-1', name: 'Valve', online: true};
        const st = {switch_targets: [{id: 'trv-1', kind: 'number', key: 'current_heating_setpoint', name: 'Valve target',
                                      value: 'zb:trv-1:current_heating_setpoint', state: 21, min: 5, max: 30},
                                     {id: 'trv-1', kind: 'enum', key: 'preset', name: 'Valve preset',
                                      value: 'zb:trv-1:preset', values: ['comfort', 'eco'], state: 'comfort'}]};
        const box = thermostatControls(d, st);
        document.body.appendChild(box);
        const s = box.querySelector('input[type=range]'), sel = box.querySelector('select');
        const res = {};
        s.value = 27; s.dispatchEvent(new Event('input')); s.dispatchEvent(new Event('change'));
        await new Promise(r => setTimeout(r, 400));
        res.asked = !document.getElementById('pinback').hidden;
        closePin(null);
        await new Promise(r => setTimeout(r, 400));
        res.slider = +s.value; res.shown = box.querySelector('.trv-value').textContent;
        sel.value = 'eco'; sel.dispatchEvent(new Event('change'));
        await new Promise(r => setTimeout(r, 400));
        closePin(null);
        await new Promise(r => setTimeout(r, 400));
        res.preset = sel.value;
        box.remove();
        return res;
      });
      await ctx.close();
    }
  } catch (e) {
    out.error = String(e && e.stack || e).slice(0, 800);
  }
  console.log(JSON.stringify(out));
  await b.close();
})();
'''


def browser():
    node_path = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
    if not node_path or not (Path(node_path) / 'playwright').exists():
        check(False, 'no playwright here')
        return {}
    (W / 'page.js').write_text(PAGE_JS)
    cfg = {'base': 'http://127.0.0.1:%d' % PHP_PORT}
    got = subprocess.run(['node', str(W / 'page.js')], capture_output=True, text=True, timeout=900, cwd=str(W),
                         stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=node_path, H_CFG=json.dumps(cfg)))
    try:
        return json.loads((got.stdout.strip().splitlines() or ['{}'])[-1])
    except ValueError:
        return {'error': (got.stdout + got.stderr)[-800:]}


o = browser()
check(not o.get('error'), 'the page could not be driven: %s' % o.get('error'))
if os.environ.get('PASS1_DUMP'):
    print(json.dumps(o, indent=1))

r = o.get('rules') or {}
check(r.get('rows') == 30, 'the rules editor did not draw the thirty rules: %r' % r.get('rows'))
check(0 < r.get('options', 99999) < 2000,
      'the rules editor of thirty rules holds %s options in its lists (%s selects) - every device and target in '
      'every row, drawn and styled whether opened or not' % (r.get('options'), r.get('selects')))
check(r.get('sameLook') == 0, '%s of the rules\' selects look different (width or entry) from the same select '
                              'with its whole list in it' % r.get('sameLook'))
check((r.get('focused') or {}).get('options', 0) > 30 and (r.get('focused') or {}).get('value') == (r.get('before') or {}).get('value'),
      'a rule\'s device list opened from the keyboard is not the whole list with the same device chosen: %r / %r'
      % (r.get('focused'), r.get('before')))
check(r.get('optionsFilled', 0) > 5000, 'the lists filled in are not the house\'s whole lists: %r' % r.get('optionsFilled'))
pk = r.get('picked') or {}
check(r.get('scripted'), 'a value set by a script on a rule\'s list nobody had opened did not take')
check(pk.get('want') and pk.get('value') == pk.get('want') and pk.get('note') == 'Unsaved changes',
      'a device picked by a script from a rule\'s list nobody had opened did not take: %r' % pk)
sc = o.get('scenes') or {}
check(sc.get('actions', 0) >= 20 and sc.get('options', 99999) < 1000,
      'the scenes editor (ten scenes, two actions each) holds %s options' % sc.get('options'))
print('the rules editor of thirty rules: drawn in %s ms, shown again in %s ms, long tasks %s, %s options'
      % (r.get('renders'), r.get('reshowMs'), r.get('longtasks'), r.get('options')))

w = o.get('who') or {}
check(not w.get('errors'), 'a name typed into a new message\'s "by text to" threw: %r' % w.get('errors'))
check(any('Jana' in x for x in w.get('offered') or []),
      'a name typed into a new message\'s "by text to" offered nobody: %r' % w.get('offered'))
print('Alerts: a new message, a name typed into "by text to"')
ac = o.get('acct') or {}
check('Close' in ac.get('focus', '') and ac.get('after') == {'open': False, 'who': True},
      'the account\'s popup opened with the focus on %r, and Enter left it %r - Enter signed the person out'
      % (ac.get('focus'), ac.get('after')))
print('the account\'s popup and Enter')

m = o.get('meter') or {}
check(m.get('shown'), 'the performance meter was not shown: %r' % m)
check(m.get('asks', 0) >= 3, 'the performance meter asked %s time(s) in 22 s after one ask hung and failed - '
                             'no next ask was left, and it stood still' % m.get('asks'))
print('the performance meter after an ask that hung and failed')

s = o.get('socket') or {}
check((s.get('before') or {}).get('output') is not None and (s.get('asked') or {}).get('asked'),
      'signed out, the socket\'s button did not ask for the sign-in: %r' % s)
check((s.get('after') or {}).get('on') == ((s.get('before') or {}).get('output') == 1)
      and not (s.get('after') or {}).get('pending'),
      'signed out, the sign-in over a socket\'s button dismissed: the card says %s for a socket that is %s'
      % ('on' if (s.get('after') or {}).get('on') else 'off', 'on' if (s.get('before') or {}).get('output') == 1 else 'off'))
print('signed out: a socket\'s button, the sign-in dismissed')

rm = o.get('room') or {}
check(rm.get('before') and (rm.get('asked') or {}).get('asked'), 'the room\'s slider did not ask for the sign-in: %r' % rm)
check((rm.get('after') or {}).get('value') == (rm.get('before') or {}).get('value')
      and (rm.get('after') or {}).get('read') == (rm.get('before') or {}).get('read'),
      'signed out, a room\'s slider dragged to 27 and the sign-in dismissed: it says %r for a room holding %r'
      % ((rm.get('after') or {}).get('read'), (rm.get('before') or {}).get('room')))
v = o.get('valve') or {}
check(v.get('asked') and v.get('slider') == 21 and v.get('shown') == '21 °C' and v.get('preset') == 'comfort',
      'signed out, a valve\'s target and preset changed on its card and the sign-in dismissed: %r' % v)
print('signed out: a room\'s slider and a valve\'s, the sign-in dismissed')

rn = o.get('rename') or {}
check((rn.get('open') or {}).get('box') and rn.get('esc') == {'box': False, 'asked': False},
      'the Devices tab: a rename left with Escape left its box in the row: %r' % rn)
check((rn.get('again') or {}).get('box') and (rn.get('asked') or {}).get('asked')
      and rn.get('dismissed') == {'box': False, 'asked': False},
      'the Devices tab: a second rename of the device, the sign-in dismissed: %r' % rn)
print('the Devices tab: a rename left with Escape, and one whose sign-in was dismissed')

check(not o.get('errors'), 'errors on the page: %r' % (o.get('errors') or [])[:5])
finish()
