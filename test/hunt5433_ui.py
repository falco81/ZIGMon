#!/usr/bin/env python3
"""5.43.3: what a bug hunt through the dashboard found. Fails on 5.43.2's page.

    python3 test/hunt5433_ui.py          (HUNT_PAGE=old: the same checks on
                                          5.43.2's page - every one must fail)

  * #sms is kept over a reload: the list of tabs the page may open with left
    the SMS tab out, so a reload of #sms opened the Overview;
  * a device with a long name with no space in it, on a phone: the name was
    never broken, so its card - and with it the whole page - was wider than
    the screen; and a text in the SMS log, whose "sent · ..." and two buttons
    stood beside it and ran off the screen;
  * a viewer (or an operator) on the SMS tab: the log is an administrator's,
    and the refusal was forgotten, so it was asked for - and refused - again
    with every change in the house;
  * the Public API tab behind another tab: it went on asking for the presses
    every five seconds while nobody could see them;
  * Escape over a popup: the box asked for over it - the PIN, a name to type
    (renaming a passkey) - and the popup under it, with all that was typed
    into it, both went with one Escape;
  * an administrator's Overview kept every card it had ever drawn: the button
    that takes a card off was made inside the drawing and held its whole
    scope, the cards before among them, a chain back to the first drawing -
    thousands of elements more every minute in a house that reports;
  * a valve's preset - a word the device's own converter sends - written into
    the PIN box's HTML unescaped.

Ports 19562 (the daemon) and 19563 (php -S).
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
W = Path(tempfile.mkdtemp(prefix='zigmon-hunt5433-ui-'))
API_PORT, PHP_PORT = 19562, 19563
AGAINST_OLD = os.environ.get('HUNT_PAGE') == 'old'
bad = []
PROCS = []
EVIL = '<img src=x onerror="window.__xss=(window.__xss||0)+1">'
LONG = 'Living_room_temperature_sensor_by_the_big_window_next_to_the_door'


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
    print('hunt5433_ui: %s' % ('%d failed' % len(bad) if bad else 'all good'))
    os._exit(1 if bad else 0)


__import__('atexit').register(lambda: [p.kill() for p in PROCS if p.poll() is None])

sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [],
                      'mqtt_host': '', 'log_file': str(W / 'zigmon.log'), 'log_to_journal': False,
                      'state_dir': str(W / 'state'), 'login_tries': 50, 'login_wait_min': 1,
                      'session_idle_min': 240, 'session_hours': 720, 'public_view': True})
(W / 'state').mkdir()
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)
d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
d.account_add('vik', 'viewer', 'vik pass 1234', must_change=False, quiet=True)

# ---- the house: a sensor with a long name, one with a hostile one, two texts -----------------
NAMES = [LONG, 'Hall ' + EVIL]
devs = [{'ieee_address': '0x%016x' % (i + 1), 'friendly_name': n, 'type': 'EndDevice',
         'definition': {'model': 'WSDCGQ11LM', 'vendor': 'Aqara', 'description': 'thermometer',
                        'exposes': [{'type': 'numeric', 'property': 'temperature', 'name': 'temperature', 'unit': '°C'},
                                    {'type': 'numeric', 'property': 'humidity', 'name': 'humidity', 'unit': '%'}]}}
        for i, n in enumerate(NAMES)]
d.handle_zigbee('bridge/devices', json.dumps(devs).encode())
d.devices_settled(10)
for n in NAMES:
    d.handle_zigbee(n, json.dumps({'temperature': 21.5, 'humidity': 44}).encode())
d.sms_note('in', '+420777123456', 'Is the heating on?')
d.sms_note('out', '+420777123456', 'It is, 21.5 in the hall', ok=None)
with d._sms_lock():                    # a quarter of an hour ago: "no answer from the gateway"
    _rows = d.sms_log(50)
    for _r in _rows:
        _r['at'] -= 900
    d._sms_log_write(_rows)


def reports():
    # the house keeps talking: every report wakes the page
    t = 20.0
    while not STOP.is_set():
        t = 20.0 if t > 24 else t + 0.1
        for n in NAMES:
            try:
                d.handle_zigbee(n, json.dumps({'temperature': round(t, 1), 'humidity': 44}).encode())
            except Exception:
                pass
        time.sleep(0.5)


threading.Thread(target=reports, daemon=True).start()

# ---- the page (this one, or 5.43.2's) relaying to the daemon above ----------------------------
NOW = W / 'web'
shutil.copytree(str(HERE / 'web'), str(NOW))
if AGAINST_OLD:
    pack = HERE / 'release' / 'zigmon-5.43.2.tar.gz'
    if not pack.exists():
        check(False, 'no release package of 5.43.2 to compare with')
        finish()
    with tarfile.open(str(pack)) as tar:
        for name in ('index.php', 'zigmon-api.php'):
            (NOW / name).write_bytes(tar.extractfile('zigmon-5.43.2/web/' + name).read())
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

PAGE_JS = r'''
const { chromium, devices } = require('playwright');
const cfg = JSON.parse(process.env.H_CFG);
const out = {errors: []};
const wait = ms => new Promise(r => setTimeout(r, ms));
async function open(b, as, opts, hash) {
  const ctx = await b.newContext(opts || {viewport: {width: 1600, height: 1000}});
  const p = await ctx.newPage();
  p.setDefaultTimeout(15000);
  p.on('pageerror', e => out.errors.push(String(e).slice(0, 200)));
  await p.goto(cfg.base + '/');
  const creds = {owner: ['owner', 'owner pass 12'], vik: ['vik', 'vik pass 1234']}[as];
  if (creds) await p.evaluate(async c => fetch('?api=login', {method: 'POST', credentials: 'same-origin',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: c[0], password: c[1]})}), creds);
  await p.goto(cfg.base + '/' + (hash || ''));
  await p.reload();
  await wait(1500);
  return [ctx, p];
}
function counting(p) {
  const n = {};
  p.on('request', r => { const m = /[?&]api=([^&]*)/.exec(r.url()); if (m) n[m[1]] = (n[m[1]] || 0) + 1; });
  return n;
}
(async () => {
  const b = await chromium.launch();
  try {
    // (1) #sms over a reload
    {
      const [ctx, p] = await open(b, 'owner', null, '#sms');
      out.hash = await p.evaluate(() => ({tab: STATE.tab, shown: !document.getElementById('tab-sms').hidden}));
      await ctx.close();
    }
    // (2) a phone, 420 wide: the long name, the text messages
    {
      const opts = Object.assign({}, devices['iPhone 13'], {viewport: {width: 420, height: 900}, screen: {width: 420, height: 900}});
      const [ctx, p] = await open(b, 'owner', opts);
      out.phone = {};
      for (const t of ['overview', 'sensors', 'sms']) {
        await p.evaluate(t => showTab(t), t);
        await wait(2000);
        out.phone[t] = await p.evaluate(() => ({iw: innerWidth, sw: document.documentElement.scrollWidth,
          lines: document.querySelectorAll('#sms-log .sms-line').length}));
      }
      await ctx.close();
    }
    // (3) a viewer on the SMS tab, with the house reporting twice a second
    {
      const [ctx, p] = await open(b, 'vik');
      await p.evaluate(() => showTab('sms'));
      await wait(1500);
      // the sign-in as an administrator it offers, said no to
      await p.evaluate(() => { if (!document.getElementById('pinback').hidden) closePin(null); });
      await wait(500);
      const n = counting(p);
      await wait(12000);
      out.viewerSms = {log: n['sms-log'] || 0, status: n['status'] || 0, wait: n['wait'] || 0};
      await ctx.close();
    }
    // (4) the Public API tab, then the browser tab hidden
    {
      const [ctx, p] = await open(b, 'owner');
      await p.evaluate(() => showTab('approvals'));
      await wait(2500);
      await p.evaluate(() => {
        Object.defineProperty(document, 'hidden', {value: true, configurable: true});
        Object.defineProperty(document, 'visibilityState', {value: 'hidden', configurable: true});
        document.dispatchEvent(new Event('visibilitychange'));
      });
      await wait(500);
      const n = counting(p);
      await wait(12000);
      out.hiddenApprovals = (n['approvals'] || 0) + (n['blocked'] || 0);
      await ctx.close();
    }
    // (5) Escape over a popup; (6) the Overview's cards, drawn again and again
    {
      const [ctx, p] = await open(b, 'owner');
      const state = () => p.evaluate(() => ({popup: !document.getElementById('zmodal').hidden,
        ask: !document.getElementById('askback').hidden, pin: !document.getElementById('pinback').hidden}));
      out.esc = {};
      await p.evaluate(() => accountMenu()); await wait(400);
      await p.evaluate(() => { askText('Rename the passkey', 'What it is called in this list.', 'iPad', null).then(v => window.__asked = v); });
      await wait(300);
      out.esc.askBefore = await state();
      await p.keyboard.press('Escape'); await wait(300);
      out.esc.askAfter = await state();
      out.esc.asked = await p.evaluate(() => window.__asked);
      await p.evaluate(() => { closeZModal(); accountMenu(); }); await wait(400);
      await p.evaluate(() => { askPin('Confirm', 'Sure?', false, false, true).then(v => window.__pinned = v); });
      await wait(300);
      out.esc.pinBefore = await state();
      await p.keyboard.press('Escape'); await wait(300);
      out.esc.pinAfter = await state();
      await p.evaluate(() => closeZModal());
      // the Overview: one card's facts change and it is drawn again, 60 times
      await p.evaluate(() => showTab('overview'));
      await wait(1000);
      const cdp = await ctx.newCDPSession(p);
      await cdp.send('Performance.enable');
      const nodes = async () => {
        await cdp.send('HeapProfiler.collectGarbage');
        const m = (await cdp.send('Performance.getMetrics')).metrics.filter(x => x.name === 'Nodes')[0];
        return m ? m.value : -1;
      };
      const redraw = k => p.evaluate(k => {
        STATE.paused = true;                 // only the drawings made here
        for (let i = 0; i < k; i++) {
          (STATE.status.devices || []).forEach(d => { d.last_seen = (d.last_seen || 0) + 1; });
          renderOverviewCustom(STATE.status);
        }
        return document.querySelectorAll('#overview-custom > *').length;
      }, k);
      out.cards = await redraw(10);
      const a = await nodes();
      await redraw(60);
      const z = await nodes();
      out.leak = {before: a, after: z, cards: out.cards};
      await ctx.close();
    }
    // (7) a valve's preset with markup in it, chosen by somebody not signed in
    {
      const [ctx, p] = await open(b, null);
      out.trv = await p.evaluate(async (evil) => {
        const d = {id: 'trv-1', name: 'Valve', online: true};
        const st = {switch_targets: [{id: 'trv-1', kind: 'enum', key: 'preset', name: 'Valve preset',
                                      value: 'trv-1:preset', values: ['comfort', evil], state: 'comfort'}]};
        const box = thermostatControls(d, st);
        document.body.appendChild(box);
        const sel = box.querySelector('select');
        sel.value = evil; sel.dispatchEvent(new Event('change'));
        await new Promise(r => setTimeout(r, 500));
        const what = document.getElementById('pinwhat');
        return {open: !document.getElementById('pinback').hidden, img: !!what.querySelector('img'),
                xss: window.__xss || 0, text: what.textContent.slice(0, 120)};
      }, cfg.evil);
      await ctx.close();
    }
  } catch (e) {
    out.error = String(e && e.stack || e).slice(0, 600);
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
    cfg = {'base': 'http://127.0.0.1:%d' % PHP_PORT, 'evil': EVIL}
    got = subprocess.run(['node', str(W / 'page.js')], capture_output=True, text=True, timeout=900, cwd=str(W),
                         stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=node_path, H_CFG=json.dumps(cfg)))
    try:
        return json.loads((got.stdout.strip().splitlines() or ['{}'])[-1])
    except ValueError:
        return {'error': (got.stdout + got.stderr)[-800:]}


o = browser()
check(not o.get('error'), 'the page could not be driven: %s' % o.get('error'))
if os.environ.get('HUNT_DUMP'):
    print(json.dumps(o, indent=1))

h = o.get('hash') or {}
check(h.get('tab') == 'sms' and h.get('shown'),
      '#sms reloaded opens %r, not the SMS tab - the tabs the page may open with left SMS out' % h.get('tab'))
print('#sms over a reload')

for t, m in sorted((o.get('phone') or {}).items()):
    check(m.get('iw') == 420 and m.get('sw', 0) <= 421,
          'a phone, %s: the page is %s wide on a 420 screen (laid out %s wide) - a long name or the '
          'SMS log not broken to fit' % (t, m.get('sw'), m.get('iw')))
check(((o.get('phone') or {}).get('sms') or {}).get('lines', 0) >= 2, 'the SMS log was not drawn on the phone')
check(len(o.get('phone') or {}) == 3, 'not every tab was measured on the phone')
print('a phone: a long name, the SMS log')

v = o.get('viewerSms') or {}
check(v.get('wait', 0) >= 3, 'the house did not wake the viewer\'s page (%r) - nothing measured' % v)
check(v.get('log', 99) <= 1,
      'a viewer on the SMS tab asked for the (refused) log %s times in 12 s - the refusal is forgotten '
      'and asked again with every change' % v.get('log'))
print('a viewer on the SMS tab')

check(o.get('hiddenApprovals', 99) == 0,
      'the Public API tab, out of sight, asked for the presses %s times in 12 s' % o.get('hiddenApprovals'))
print('the Public API tab out of sight')

e = o.get('esc') or {}
check((e.get('askBefore') or {}).get('popup') and (e.get('askBefore') or {}).get('ask'), 'the box over the popup did not open: %r' % e)
check((e.get('askAfter') or {}).get('popup') and not (e.get('askAfter') or {}).get('ask') and e.get('asked') is None,
      'Escape in a box asked for over a popup closed the popup as well: %r' % e.get('askAfter'))
check((e.get('pinAfter') or {}).get('popup') and not (e.get('pinAfter') or {}).get('pin'),
      'Escape on the PIN box over a popup closed the popup as well: %r' % e.get('pinAfter'))
print('Escape over a popup')

lk = o.get('leak') or {}
check(lk.get('cards', 0) >= 2, 'the Overview drew no cards to measure: %r' % lk)
check(lk.get('before', 0) > 0 and lk.get('after', 0) - lk.get('before', 0) < 400,
      'an administrator\'s Overview drawn 60 times more holds %s elements more (%r) - every card it '
      'ever drew is kept' % (lk.get('after', 0) - lk.get('before', 0), lk))
print('the Overview drawn again and again')

tv = o.get('trv') or {}
check(tv.get('open'), 'the PIN box did not open for a valve\'s preset: %r' % tv)
check(not tv.get('img') and not tv.get('xss'),
      'a valve\'s preset went into the PIN box as HTML: %r' % tv)
print('a valve\'s preset in the PIN box')

check(not o.get('errors'), 'errors on the page: %r' % (o.get('errors') or [])[:5])
finish()
