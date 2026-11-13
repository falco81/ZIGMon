#!/usr/bin/env python3
"""The device tiles, variant H (5.53): a thin band on top of every device card
holds the state pill and the object mark on the left, the chart button and
(on a curated Overview, while editing) the remove button on the right; under
it the name has the card's whole width, and the model and the description are
two lines of their own instead of one "model · description" string wrapped
over three.

Nothing behaves differently: the chart button and the remove button are the
same elements with the same classes, sizes, titles, hover and show/hide rules
and the same clicks; the object mark is the same mark. Nothing on a card is
shortened: no text overflows its box and nothing is ellipsized.

One device of every kind on the Sensors and Buttons tabs (thermometer, PIR,
door contact, single and 4-button remotes, the knob with its "+N", a radiator
head in a room with its offset and level, a router, the coordinator, the SMS
gateway, an offline one, one with a low battery, a long unbroken name), the
same on the Overview, with Rearrange on and a card being dragged, and at
phone width.

    python3 test/review553_tilesH.py

Screenshots into $TILESH_SHOTS (default: a temporary directory). With
TILESH_BEFORE=1 and TILESH_WEB pointing at an older web/ it only takes the
"before-" screenshots and prints the measurements of the buttons (that is how
the BEFORE values below were recorded, from 5.52.0).

Ports 20250 (the daemon), 20251 (php -S).
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-tilesH-'))
API_PORT, PHP_PORT = 20250, 20251
SHOTS = Path(os.environ.get('TILESH_SHOTS') or (W / 'shots'))
BEFORE_MODE = os.environ.get('TILESH_BEFORE') == '1'
WEB = Path(os.environ.get('TILESH_WEB') or (HERE / 'web'))
bad = []
PROCS = []

# How the buttons looked and behaved in 5.52.0, measured in Chromium by this
# very script with TILESH_BEFORE=1 against that version's web/ (rounded).
# The chart button: 26 x 26, radius 8, hidden until the card is hovered.
# The remove button: 24 x 24, round, always there while editing the Overview.
# The object mark: 14 x 14, at .55 until pointed at.
BEFORE = {
    'hist': {'w': 26, 'h': 26, 'radius': '8px', 'opacity': '0', 'hover_opacity': '1', 'visibility': 'visible',
             'display': 'flex', 'cursor': 'pointer', 'self_hover_color': 'rgb(88, 166, 255)'},
    'remove': {'w': 24, 'h': 24, 'radius': '50%', 'opacity': '1', 'hover_opacity': '1', 'visibility': 'visible',
               'display': 'flex', 'cursor': 'pointer', 'self_hover_color': 'rgb(248, 81, 73)'},
    'mark': {'w': 14, 'h': 14, 'radius': '4px', 'opacity': '0.55', 'hover_opacity': '0.55', 'visibility': 'visible',
             'display': 'inline-flex', 'cursor': 'pointer', 'self_hover_color': 'rgb(88, 166, 255)'},
}


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def finish():
    for p in PROCS:
        # php -S with workers: the workers are children of their own, so the
        # whole group goes, by its id, not only the parent
        try:
            os.killpg(p.pid, 15)
        except OSError:
            pass
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    try:
        api.stop()
    except Exception:                                        # noqa: BLE001
        pass
    shutil.rmtree(W, ignore_errors=True)
    print('review553_tilesH: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
    os._exit(1 if bad else 0)


sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                                # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'log_file': '', 'state_dir': str(W / 'state'), 'preheat': False})
(W / 'state').mkdir()

d = zigmon.Daemon()
d.notify = lambda *a, **k: None
d.valve_take_over = lambda dev: None
d.zigbee_switch = lambda *a, **k: (True, 'published')
now = time.time()

ROUTER = '0xrouter01'
HEAD = '0xhead0001'
THERMO = '0xtemp0001'
BUTTON1 = ['single', 'double', 'triple', 'long', 'single_long', 'double_long', 'triple_long']
BUTTON4 = ['%d_%s' % (n, a) for n in range(1, 5) for a in ('single', 'double', 'triple', 'single_long',
                                                             'double_long', 'triple_long', 'hold')]
KNOB = ['toggle', 'brightness_step_up', 'brightness_step_down', 'color_temperature_step_up',
        'color_temperature_step_down', 'saturation_move', 'hue_move', 'hue_stop', 'brightness_move_up',
        'brightness_move_down', 'rotate_left', 'rotate_right', 'single']
# name, id, vendor, model, description, kind, exposes, payload, extra
DEVICES = [
    ('Temp-Koupelna', THERMO, 'Shelly', 'SBHT-203C', 'Humidity & temperature sensor', 'EndDevice', {},
     {'temperature': 24.1, 'humidity': 32.9, 'battery': 100, 'linkquality': 156}, {}),
    ('PIR-Chodba', '0xpir00001', 'Philips', '9290012607', 'Hue motion sensor', 'EndDevice', {},
     {'occupancy': False, 'illuminance': 23, 'illuminance_lux': 23, 'temperature': 21.4, 'battery': 87,
      'linkquality': 120}, {}),
    ('Door-Vchod', '0xdoor0001', 'Aqara', 'MCCGQ11LM', 'Door & window contact sensor', 'EndDevice', {},
     {'contact': True, 'battery': 100, 'voltage': 3005, 'linkquality': 96}, {}),
    ('Head-Loznice', HEAD, 'TuYa', 'TS0601_thermostat', 'Thermostatic radiator valve', 'EndDevice',
     {'current_heating_setpoint': {'type': 'numeric', 'access': 7, 'min': 5, 'max': 35},
      'local_temperature': {'type': 'numeric', 'access': 1},
      'local_temperature_calibration': {'type': 'numeric', 'access': 7, 'min': -9, 'max': 9}},
     {'local_temperature': 22.5, 'local_temperature_calibration': -1.5, 'current_heating_setpoint': 21.0,
      'position': 35, 'system_mode': 'heat', 'battery': 64, 'linkquality': 88}, {}),
    ('Router', ROUTER, 'IKEA', 'E1746', 'TRADFRI signal repeater', 'Router', {}, {'linkquality': 210}, {}),
    ('Coordinator', '0x00124b0000000001', 'Texas Instruments', 'CC2652P', 'Zigbee coordinator', 'Coordinator', {},
     {}, {}),
    ('Temp-Garaz', '0xtemp0002', 'SONOFF', 'SNZB-02', 'Temperature and humidity sensor', 'EndDevice', {},
     {'temperature': 8.4, 'humidity': 71.0, 'battery': 90, 'linkquality': 40}, {'offline': True}),
    ('Temp-Puda', '0xtemp0003', 'SONOFF', 'SNZB-02D', 'Temperature and humidity sensor with LCD', 'EndDevice', {},
     {'temperature': 12.9, 'humidity': 58.0, 'battery': 6, 'linkquality': 64}, {}),
    ('Living_room_sensor_by_the_window', '0xtemp0004', 'Xiaomi', 'WSDCGQ11LM',
     'Aqara temperature, humidity and pressure sensor', 'EndDevice', {},
     {'temperature': 22.0, 'humidity': 45.0, 'pressure': 1003, 'battery': 100, 'linkquality': 150}, {}),
    ('Button-Black', '0xbtn00001', 'Shelly', 'SBBT-102C', 'BLU Button Tough 1 ZB', 'EndDevice',
     {'action': {'type': 'enum', 'values': BUTTON1}}, {'battery': 99, 'linkquality': 156},
     {'last': 'single'}),
    ('Button4X-Workshop', '0xbtn00004', 'Shelly', 'SBBT-104CUS', 'BLU RC Button 4 ZB', 'EndDevice',
     {'action': {'type': 'enum', 'values': BUTTON4}}, {'battery': 100, 'linkquality': 156},
     {'last': '1_double'}),
    ('Button-Topeni', '0xknob0001', 'Tuya', 'ERS-10TZBVK-AA', 'Smart knob', 'EndDevice',
     {'action': {'type': 'enum', 'values': KNOB}}, {'battery': 100, 'linkquality': 212},
     {'last': 'rotate_right'}),
]
DEV_NAMES = [x[0] for x in DEVICES] + ['SMS-Gateway']
SENSOR_NAMES = [x[0] for x in DEVICES if 'action' not in x[6]] + ['SMS-Gateway']
BUTTON_NAMES = [x[0] for x in DEVICES if 'action' in x[6]]

parents = {}
for name, did, vendor, model, desc, kind, exposes, payload, extra in DEVICES:
    d.store.upsert_device({'id': did, 'name': name, 'source': 'zigbee', 'kind': kind, 'vendor': vendor,
                           'model': model, 'description': desc, 'exposes': exposes, 'last_seen': int(now - 60)})
    d.live[did] = {'payload': dict(payload), 'ts': now - 60,
                   'availability': 'offline' if extra.get('offline') else 'online'}
    if extra.get('last'):
        d.store._last_action[did] = {'action': extra['last'], 'ts': now - 23 * 3600}
    if kind == 'EndDevice':
        parents[did] = {'parent': ROUTER, 'parent_type': 'Router', 'lqi': 120, 'relation': 'parent', 'ts': now}
d.parents = parents
# the SMS gateway, as the modem's status makes it
d.store.upsert_device({'id': 'sms:gateway', 'name': 'SMS-Gateway', 'source': 'sms', 'kind': 'SMS gateway',
                       'vendor': 'Teltonika', 'model': 'LTE', 'last_seen': int(now - 30)})
d.live['sms:gateway'] = {'payload': {'rssi': -67, 'operator': 'O2 CZ', 'network': 'LTE', 'sent_today': 3,
                                     'received_today': 5, 'waiting_to_go': 0},
                         'ts': now - 30, 'availability': 'online'}
# the head in a room that follows the room thermometer: the level select, the offset
d.store.set_meta('rooms', json.dumps([{'id': 'r1', 'name': 'Loznice'}]))
d.store._meta_cache.pop('rooms', None)
d.store.set_meta('room_of', json.dumps({HEAD: 'r1', THERMO: 'r1'}))
d.save_heating({'enabled': True, 'rooms': {'r1': {'mode': 'comfort', 'comfort_c': 21.0, 'thermometer': THERMO,
                                                  'follow_room': True}}, '_quiet': True})
d._heat_state_cache = None

api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def login(name, role, password):
    d.account_add(name, role, password, must_change=False, quiet=True)
    req = urllib.request.Request('http://127.0.0.1:%d/api/auth/login' % API_PORT,
                                 data=json.dumps({'name': name, 'password': password}).encode(),
                                 headers={'X-Zigmon-Token': d.token, 'Content-Type': 'application/json',
                                          'X-Zigmon-Client': '192.168.40.10'}, method='POST')
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read()).get('token') or ''


S_ADMIN = login('owner', 'admin', 'owner pass 12')
S_OPER = login('worker', 'operator', 'worker pass 12')

npm_root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()
if not (Path(npm_root) / 'playwright').exists() or subprocess.run(['which', 'php'], capture_output=True,
                                                                     stdin=subprocess.DEVNULL).returncode != 0:
    print('  SKIPPED (no browser or php here)')
    finish()

try:
    socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
    check(False, 'port %d is taken by something else' % PHP_PORT)
    finish()
except OSError:
    pass
shutil.copytree(WEB, W / 'web')
api_php = (W / 'web' / 'zigmon-api.php').read_text()
api_php = api_php.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
api_php = api_php.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
(W / 'web' / 'zigmon-api.php').write_text(api_php)
php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, str(W / 'web' / 'index.php')], cwd=str(W / 'web'),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                       env=dict(os.environ, PHP_CLI_SERVER_WORKERS='4'), start_new_session=True)
PROCS.append(php)
for _ in range(50):
    try:
        socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
        break
    except OSError:
        time.sleep(0.1)
SHOTS.mkdir(parents=True, exist_ok=True)

js = r'''
const { chromium } = require('playwright');
const job = __JOB__;
const pre = job.before ? 'before-' : '';
const ownText = e => e ? Array.from(e.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim() : '';
const slug = s => s.toLowerCase().replace(/[^a-z0-9]+/g, '-');
(async () => {
  const b = await chromium.launch();
  const out = {errors: []};
  async function page(s, width, height) {
    const ctx = await b.newContext({viewport: {width: width, height: height}, deviceScaleFactor: 2, colorScheme: 'dark'});
    await ctx.addCookies([{name: 'zigmon_session', value: s, url: 'http://127.0.0.1:' + job.port + '/'}]);
    const p = await ctx.newPage();
    p.setDefaultTimeout(8000);
    p.on('dialog', dl => { out.errors.push('dialog: ' + dl.message()); dl.dismiss().catch(() => {}); });
    p.on('pageerror', e => out.errors.push(String(e)));
    return p;
  }
  async function tab(p, name, host) {
    await p.goto('http://127.0.0.1:' + job.port + '/#' + name);
    await p.waitForTimeout(1200);
    try { await p.click('button[data-tab="' + name + '"]', {timeout: 1500}); } catch (e) {}
    await p.waitForSelector(host + ' .card.dev', {timeout: 20000});
    await p.mouse.move(1, 1);
    await p.waitForTimeout(900);
  }
  // every card in a grid: what is where, and whether anything is cut
  const survey = host => Array.from(document.querySelectorAll(host + ' .card.dev')).map(c => {
    const band = c.querySelector(':scope > .dev-band');
    const inBand = sel => !!(band && band.querySelector(sel));
    const left = band && band.querySelector('.band-l'), right = band && band.querySelector('.band-r');
    const nameEl = c.querySelector('.name');
    const cut = [];
    c.querySelectorAll('*').forEach(e => {
      const cs = getComputedStyle(e);
      if (cs.display === 'inline' || cs.display === 'none' || e.tagName === 'svg' || e.closest('svg')) return;
      if (e.tagName === 'SELECT' || e.tagName === 'INPUT' || e.tagName === 'OPTION') return;
      if (e.scrollWidth > e.clientWidth + 1 && cs.overflowX !== 'visible')
        cut.push((e.className || e.tagName) + ': ' + e.textContent.slice(0, 40));
      if (cs.textOverflow === 'ellipsis' && e.scrollWidth > e.clientWidth + 1) cut.push('ellipsis ' + e.className);
      // a child wider than its card is as bad as a clipped one
      const r = e.getBoundingClientRect(), cr = c.getBoundingClientRect();
      if (r.width && (r.right > cr.right + 0.5 || r.left < cr.left - 0.5)) cut.push('outside ' + (e.className || e.tagName));
    });
    const lh = nameEl ? parseFloat(getComputedStyle(nameEl).lineHeight) : 20;
    const model = c.querySelector('.head .model'), desc = c.querySelector('.head .desc');
    const lines = e => e ? Math.round(e.getBoundingClientRect().height / parseFloat(getComputedStyle(e).lineHeight)) : 0;
    return {
      name: nameEl ? Array.from(nameEl.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim() : '', band: !!band,
      left: left ? Array.from(left.children).map(x => x.className.split(' ')[0]) : [],
      right: right ? Array.from(right.children).map(x => x.className.split(' ')[0]) : [],
      tagInBand: inBand('.tag'), markInBand: inBand('.obj-mark'), histInBand: inBand('.dev-hist'),
      removeInBand: inBand('.ov-remove'), hasHist: !!c.querySelector('.dev-hist'),
      hasRemove: !!c.querySelector('.ov-remove'), hasMark: !!c.querySelector('.obj-mark'),
      icon: !!c.querySelector('.name .dev-ic'),
      nameLines: nameEl ? Math.round(nameEl.getBoundingClientRect().height / lh) : 0,
      modelText: model ? model.innerText : '', descText: desc ? desc.innerText : '',
      modelLines: lines(model), descLines: lines(desc),
      modelWeight: model ? getComputedStyle(model).fontWeight : '', cut: cut,
      bandBg: band ? getComputedStyle(band).backgroundColor : '', bandBorder: band ? getComputedStyle(band).borderBottomStyle : '',
      bandTopRadius: band ? getComputedStyle(band).borderTopLeftRadius : '',
      cardW: Math.round(c.getBoundingClientRect().width),
    };
  });
  // one button as it is drawn, at rest and with the card under the pointer
  async function measure(p, card, sel) {
    const one = async () => card.evaluate((c, s) => {
      const e = c.querySelector(s);
      if (!e) return null;
      const cs = getComputedStyle(e), r = e.getBoundingClientRect();
      return {w: Math.round(r.width), h: Math.round(r.height), radius: cs.borderTopLeftRadius === '50%' || (parseFloat(cs.borderTopLeftRadius) >= r.width / 2 - 0.5 && r.width) ? '50%' : cs.borderTopLeftRadius,
              opacity: cs.opacity, visibility: cs.visibility, display: cs.display, cursor: cs.cursor,
              color: cs.color, title: e.title || e.dataset.said || '', cls: e.className, type: e.type || '',
              html: e.innerHTML.length};
    }, sel);
    await card.scrollIntoViewIfNeeded();
    await p.mouse.move(1, 1); await p.waitForTimeout(350);
    const rest = await one();
    if (!rest) return null;
    const box = await card.boundingBox();
    await p.mouse.move(box.x + box.width / 2, box.y + box.height - 8); await p.waitForTimeout(350);
    const hov = await one();
    await card.locator(sel).first().hover(); await p.waitForTimeout(350);
    const self = await one();
    await p.mouse.move(1, 1); await p.waitForTimeout(350);
    rest.hover_opacity = hov.opacity; rest.self_hover_color = self.color; rest.self_hover_opacity = self.opacity;
    return rest;
  }
  // a locator, not a handle: a card is built again whenever what it shows changes
  function cardByName(p, host, name) {
    const re = new RegExp(name.replace(/[.*+?^${}()|[\]\\-]/g, '\\$&') + '\\s*$');
    return p.locator(host + ' .card.dev').filter({has: p.locator('.name', {hasText: re})}).first();
  }

  // ---- the Sensors and the Buttons tab, as the owner -------------------------------------
  const p = await page(job.admin, 1200, 1600);
  await tab(p, 'sensors', '#sensor-cards');
  out.sensors = await p.evaluate(survey, '#sensor-cards');
  await p.screenshot({path: job.dir + '/' + pre + 'sensors.png', fullPage: true});
  for (const n of job.sensors) {
    const c = await cardByName(p, '#sensor-cards', n);
    await c.screenshot({path: job.dir + '/' + pre + 'card-' + slug(n) + '.png'}).catch(e => out.errors.push('no card ' + n));
  }
  const tc = await cardByName(p, '#sensor-cards', 'Temp-Koupelna');
  out.hist = await measure(p, tc, '.dev-hist');
  out.mark = await measure(p, tc, '.obj-mark');
  // hovered: the card under the pointer, its chart button showing
  {
    await tc.scrollIntoViewIfNeeded();
    const box = await tc.boundingBox();
    await p.mouse.move(box.x + box.width / 2, box.y + box.height - 8); await p.waitForTimeout(400);
    await tc.screenshot({path: job.dir + '/' + pre + 'card-hovered.png'});
    await p.mouse.move(1, 1); await p.waitForTimeout(300);
  }
  // the chart button opens the device's history
  {
    const box = await tc.boundingBox();
    await p.mouse.move(box.x + box.width / 2, box.y + box.height - 8); await p.waitForTimeout(300);
    await tc.locator('.dev-hist').click();
    await p.waitForTimeout(700);
    out.chartClick = await p.evaluate(() => ({tab: STATE.tab, dev: STATE.hDevice}));
  }
  // the object mark opens what the device is
  await tab(p, 'sensors', '#sensor-cards');
  {
    const c = await cardByName(p, '#sensor-cards', 'Temp-Koupelna');
    await c.locator('.obj-mark').click();
    await p.waitForTimeout(700);
    out.markClick = await p.evaluate(() => { const o = document.getElementById('objpop'); return !!o && !o.hidden; });
    await p.keyboard.press('Escape'); await p.waitForTimeout(200);
  }
  await tab(p, 'buttons', '#button-cards');
  out.buttons = await p.evaluate(survey, '#button-cards');
  await p.screenshot({path: job.dir + '/' + pre + 'buttons.png', fullPage: true});
  for (const n of job.buttons) {
    const c = await cardByName(p, '#button-cards', n);
    await c.screenshot({path: job.dir + '/' + pre + 'card-' + slug(n) + '.png'}).catch(e => out.errors.push('no card ' + n));
  }
  out.buttonHist = await measure(p, await cardByName(p, '#button-cards', 'Button4X-Workshop'), '.dev-hist');

  // ---- the Overview, every device on it: the remove button while editing ---------------
  await tab(p, 'overview', '#overview-custom');
  out.overview = await p.evaluate(survey, '#overview-custom');
  await p.screenshot({path: job.dir + '/' + pre + 'overview.png', fullPage: true});
  const oc = await cardByName(p, '#overview-custom', 'Temp-Koupelna');
  await oc.screenshot({path: job.dir + '/' + pre + 'overview-card.png'});
  out.remove = await measure(p, oc, '.ov-remove');
  out.ovHist = await measure(p, oc, '.dev-hist');
  // the card under the pointer: the chart button and the x both showing, and
  // never on top of each other
  {
    await oc.scrollIntoViewIfNeeded();
    const box = await oc.boundingBox();
    await p.mouse.move(box.x + box.width / 2, box.y + box.height - 8); await p.waitForTimeout(400);
    out.ovPair = await oc.evaluate(c => {
      const r = s => { const e = c.querySelector(s), b = e.getBoundingClientRect(), cs = getComputedStyle(e);
                       return {l: b.left, r: b.right, t: b.top, b: b.bottom, opacity: cs.opacity, visibility: cs.visibility}; };
      return {hist: r('.dev-hist'), rm: r('.ov-remove')};
    });
    await oc.screenshot({path: job.dir + '/' + pre + 'overview-card-hovered.png'});
    await p.mouse.move(1, 1); await p.waitForTimeout(300);
  }
  await oc.locator('.ov-remove').click();
  await p.waitForTimeout(800);
  out.removeClick = await p.evaluate(() => ({
    gone: !Array.from(document.querySelectorAll('#overview-custom .card.dev .name')).some(n => n.textContent.indexOf('Temp-Koupelna') >= 0),
    layout: overviewLayoutIds(STATE.status).indexOf('0xtemp0001') < 0}));

  // ---- Rearrange, a card being dragged ---------------------------------------------------
  await tab(p, 'sensors', '#sensor-cards');
  await p.click('#arrangepill'); await p.waitForTimeout(900);
  out.arrange = await p.evaluate(() => {
    const c = document.querySelector('#sensor-cards .card.dev');
    c.dispatchEvent(new DragEvent('dragstart', {bubbles: true, dataTransfer: new DataTransfer()}));
    const h = c.querySelector('.dev-hist');
    return {grab: c.classList.contains('cangrab'), dragging: c.classList.contains('draggingcard'),
            histEvents: h ? getComputedStyle(h).pointerEvents : ''};
  });
  await p.waitForTimeout(300);
  await (await p.$('#sensor-cards')).screenshot({path: job.dir + '/' + pre + 'rearrange-dragging.png'});
  await p.evaluate(() => { const c = document.querySelector('#sensor-cards .card.dev'); c.dispatchEvent(new DragEvent('dragend', {bubbles: true})); });
  await p.waitForTimeout(400);
  await p.click('#arrangepill'); await p.waitForTimeout(500);

  // ---- an operator: no remove button on the Overview, the chart button as before ------
  const po = await page(job.oper, 1200, 1600);
  await tab(po, 'overview', '#overview-custom');
  out.operOverview = await po.evaluate(survey, '#overview-custom');

  // ---- at phone width --------------------------------------------------------------------
  const ph = await page(job.admin, 390, 844);
  await tab(ph, 'sensors', '#sensor-cards');
  out.phoneSensors = await ph.evaluate(survey, '#sensor-cards');
  out.phoneScroll = await ph.evaluate(() => document.documentElement.scrollWidth);
  await ph.screenshot({path: job.dir + '/' + pre + 'phone-sensors.png', fullPage: true});
  await tab(ph, 'buttons', '#button-cards');
  out.phoneButtons = await ph.evaluate(survey, '#button-cards');
  await ph.screenshot({path: job.dir + '/' + pre + 'phone-buttons.png', fullPage: true});
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e && e.stack || e)})); }).then(() => process.exit(0));
'''
job = {'admin': S_ADMIN, 'oper': S_OPER, 'port': PHP_PORT, 'dir': str(SHOTS), 'before': BEFORE_MODE,
       'sensors': SENSOR_NAMES, 'buttons': BUTTON_NAMES}
(W / 'page.js').write_text(js.replace('__JOB__', json.dumps(job)))
try:
    got = subprocess.run(['node', str(W / 'page.js')], capture_output=True, text=True, timeout=int(os.environ.get("TILESH_TIMEOUT") or 400),
                         stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=npm_root))
except subprocess.TimeoutExpired as e:
    check(False, 'the page did not answer: %s %s' % (str(e.stdout or '')[-800:], str(e.stderr or '')[-1500:]))
    finish()
try:
    r = json.loads(got.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    r = {'error': (got.stdout + got.stderr)[-600:]}
if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
    print('  SKIPPED (no browser here): %s' % r['error'][:200])
    finish()
if not check(not r.get('error'), 'the page: %s\n%s' % (r.get('error'), got.stderr[-600:])):
    finish()


def keep(m):
    return {k: m.get(k) for k in ('w', 'h', 'radius', 'opacity', 'hover_opacity', 'visibility', 'display',
                                  'cursor', 'self_hover_color')} if m else None


if BEFORE_MODE:
    print(json.dumps({'hist': keep(r.get('hist')), 'remove': keep(r.get('remove')), 'mark': keep(r.get('mark')),
                      'raw': {k: r.get(k) for k in ('hist', 'remove', 'mark', 'buttonHist', 'ovHist', 'chartClick',
                                                    'markClick', 'removeClick', 'arrange', 'ovPair')},
                      'oper_remove': any(c.get('hasRemove') for c in r.get('operOverview') or [])}, indent=1))
    print('screenshots: %s' % SHOTS)
    finish()

# ---- the buttons: exactly as they were ----------------------------------------------------
print('the buttons as they were')
for what, now_m, was in (('chart button (Sensors)', r.get('hist'), BEFORE['hist']),
                         ('chart button (Buttons)', r.get('buttonHist'), BEFORE['hist']),
                         ('chart button (Overview)', r.get('ovHist'), BEFORE['hist']),
                         ('remove button (Overview)', r.get('remove'), BEFORE['remove']),
                         ('object mark', r.get('mark'), BEFORE['mark'])):
    check(keep(now_m) == was, '%s changed: was %r, is %r' % (what, was, keep(now_m)))
h = r.get('hist') or {}
check(h.get('cls') == 'dev-hist' and h.get('type') == 'button' and h.get('title') == 'History and charts of Temp-Koupelna',
      'the chart button is not the same element: %r' % h)
rm = r.get('remove') or {}
check(rm.get('cls') == 'ov-remove' and rm.get('title') == 'Remove from Overview', 'the remove button: %r' % rm)
check(r.get('chartClick') == {'tab': 'history', 'dev': '0xtemp0001'}, 'the chart button: %r' % r.get('chartClick'))
check(r.get('markClick') is True, 'the object mark did not open the object')
check(r.get('removeClick') == {'gone': True, 'layout': True}, 'the remove button: %r' % r.get('removeClick'))
# On the Overview, with the card under the pointer, both buttons show and do
# not touch: the chart button first, the x after it, at least 4 px apart.
# (5.52.0 had the x under the chart button, 6 px below it; the hidden chart
# button kept its place there as it does here.)
pair = r.get('ovPair') or {}
hb, xb = pair.get('hist') or {}, pair.get('rm') or {}
apart = max(xb.get('l', 0) - hb.get('r', 0), hb.get('l', 0) - xb.get('r', 0),
            xb.get('t', 0) - hb.get('b', 0), hb.get('t', 0) - xb.get('b', 0))
check(hb.get('opacity') == '1' and xb.get('opacity') == '1' and hb.get('visibility') == 'visible'
      and xb.get('visibility') == 'visible', 'the chart button and the x do not both show on hover: %r' % pair)
check(apart >= 4, 'the chart button and the x overlap or touch (%.1f px apart): %r' % (apart, pair))
check(hb.get('r', 0) <= xb.get('l', 0) and abs((hb.get('t', 0) + hb.get('b', 0)) / 2 - (xb.get('t', 0) + xb.get('b', 0)) / 2) < 1,
      'the chart button and the x are not side by side, chart first: %r' % pair)
a = r.get('arrange') or {}
check(a.get('grab') and a.get('dragging') and a.get('histEvents') == 'none',
      'Rearrange: the card is not draggable, or its buttons are live: %r' % a)
check(not any(c.get('hasRemove') for c in r.get('operOverview') or []),
      'an operator is offered the remove button on the Overview')
check(all(c.get('hasHist') for c in r.get('operOverview') or []), 'an operator lost a chart button')

# ---- the band, the name and the two lines ----------------------------------------------------
print('the band on every card')
for where, cards, names, remove in (('Sensors', r.get('sensors'), SENSOR_NAMES, False),
                                    ('Buttons', r.get('buttons'), BUTTON_NAMES, False),
                                    ('Overview', r.get('overview'), DEV_NAMES, True),
                                    # (taken off the Overview above, by its x)
                                    ('Overview (operator)', r.get('operOverview'), [n for n in DEV_NAMES if n != 'Temp-Koupelna'], False),
                                    ('Sensors on a phone', r.get('phoneSensors'), SENSOR_NAMES, False),
                                    ('Buttons on a phone', r.get('phoneButtons'), BUTTON_NAMES, False)):
    cards = cards or []
    got_names = [c['name'] for c in cards]
    check(all(n in got_names for n in names), '%s: cards missing: %r' % (where, [n for n in names if n not in got_names]))
    for c in cards:
        if c['name'] not in names:
            continue
        right = ['dev-hist', 'ov-remove'] if remove else ['dev-hist']
        check(c['band'] and c['left'] == ['tag', 'obj-mark'] and c['right'] == right,
              '%s / %s: the band is %r | %r' % (where, c['name'], c['left'], c['right']))
        check(c['bandBg'] == 'rgba(255, 255, 255, 0.02)' and c['bandBorder'] == 'solid' and c['bandTopRadius'] != '0px',
              '%s / %s: the band is drawn %r %r %r' % (where, c['name'], c['bandBg'], c['bandBorder'], c['bandTopRadius']))
        check(c['icon'], '%s / %s: no mark of its kind before the name' % (where, c['name']))
        check(not c['cut'], '%s / %s: text cut: %r' % (where, c['name'], c['cut'][:4]))
        if c['name'] != 'Living_room_sensor_by_the_window':
            check(c['nameLines'] == 1, '%s / %s: the name takes %d lines' % (where, c['name'], c['nameLines']))
        check(c['modelLines'] == 1 and c['modelWeight'] == '600' and ' · ' not in c['modelText'] or c['name'] == 'SMS-Gateway',
              '%s / %s: the model line: %r (%d lines, %s)' % (where, c['name'], c['modelText'], c['modelLines'], c['modelWeight']))
        if c['name'] in ('Temp-Koupelna', 'Button4X-Workshop', 'Button-Black', 'Door-Vchod'):
            check(c['descLines'] == 1, '%s / %s: the description takes %d lines: %r'
                  % (where, c['name'], c['descLines'], c['descText']))
tk = next((c for c in r.get('sensors') or [] if c['name'] == 'Temp-Koupelna'), {})
check(tk.get('modelText') == 'Shelly SBHT-203C' and tk.get('descText') == 'Humidity & temperature sensor',
      'the model and the description: %r / %r' % (tk.get('modelText'), tk.get('descText')))
check(r.get('phoneScroll', 999) <= 390, 'the phone page scrolls sideways: %r' % r.get('phoneScroll'))
check(not r.get('errors'), 'the page threw: %r' % r.get('errors'))
print('screenshots: %s' % SHOTS)
finish()
