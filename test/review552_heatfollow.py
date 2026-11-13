#!/usr/bin/env python3
"""Follow the room thermometer: a room may ask for its heads' offsets
(local_temperature_calibration) to be kept matched to the room thermometer,
by themselves. Off unless asked - a house that does not switch it on is
exactly as it was. Fails before 5.52: there was no such setting and no job.

  * off by default: no write at all;
  * on: the offset goes out as "Match the room" works it out (head 27.5, room
    25.6, offset 0 -> -2.0), an event says so, the time is kept per head;
  * not again before the head has reported since, nor within the interval
    (heating_follow_every_min, which Settings changes), nor across a restart;
  * nothing for a difference under heating_follow_min_diff, a thermometer
    gone quiet, a manual room, heating switched off, a room shut or with a
    window open, a head without an offset;
  * "Match the room" by hand answers as it did;
  * heat Loznice follow on|off;
  * the setting on the Settings page, the switch on the room card, and a
    screenshot of the card (php -S + Playwright) into $ZIGMON_SHOTS.

    python3 test/review552_heatfollow.py

Ports 20210-20211 (only for the screenshot).
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-heatfollow-check-'))
API_PORT, PHP_PORT = 20210, 20211
SHOTS = Path(os.environ.get('ZIGMON_SHOTS') or (W / 'shots'))
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'log_file': '', 'state_dir': str(W / 'state'), 'preheat': False})
(W / 'state').mkdir()

HEAD, HEAD2, THERMO = '0xhead0001', '0xhead0002', '0xtherm001'
HEAD_EXPOSES = {'current_heating_setpoint': {'type': 'numeric', 'access': 7, 'min': 5, 'max': 35},
                'local_temperature': {'type': 'numeric', 'access': 1},
                'local_temperature_calibration': {'type': 'numeric', 'access': 7, 'min': -9, 'max': 9}}


def build():
    x = zigmon.Daemon()
    x.valve_take_over = lambda dev: None
    x.sent = []
    x.zigbee_switch = lambda dev, key, act, origin='', *a, **k: (x.sent.append((dev, key, act)) or (True, 'published'))
    return x


d = build()
d.store.upsert_device({'id': HEAD, 'name': 'Head-Loznice', 'source': 'zigbee', 'kind': 'thermostat',
                       'exposes': HEAD_EXPOSES})
# a head that takes no offset: left alone
d.store.upsert_device({'id': HEAD2, 'name': 'Head-Plain', 'source': 'zigbee', 'kind': 'thermostat',
                       'exposes': {k: v for k, v in HEAD_EXPOSES.items() if k != 'local_temperature_calibration'}})
d.store.upsert_device({'id': THERMO, 'name': 'Temp-Loznice', 'source': 'zigbee', 'kind': 'sensor',
                       'exposes': {'temperature': {'type': 'numeric', 'access': 1}}})
d.store.set_meta('rooms', json.dumps([{'id': 'r1', 'name': 'Loznice'}]))
d.store.meta_json('rooms')
d.store._meta_cache.pop('rooms', None)
d.store.set_meta('room_of', json.dumps({HEAD: 'r1', HEAD2: 'r1', THERMO: 'r1'}))
d.save_heating({'enabled': True, 'rooms': {'r1': {'mode': 'comfort', 'comfort_c': 26.0,
                                                  'thermometer': THERMO}}, '_quiet': True})


def report(x, head_c=27.5, cal=0.0, room_c=25.6, head_age=0, room_age=0, head2=True):
    now = time.time()
    x.live[HEAD] = {'payload': {'local_temperature': head_c, 'local_temperature_calibration': cal,
                                'current_heating_setpoint': 26.0, 'system_mode': 'heat', 'position': 0},
                    'ts': now - head_age, 'availability': 'online'}
    if head2:
        x.live[HEAD2] = {'payload': {'local_temperature': 28.0, 'current_heating_setpoint': 26.0,
                                     'system_mode': 'heat'}, 'ts': now - head_age, 'availability': 'online'}
    x.live[THERMO] = {'payload': {'temperature': room_c}, 'ts': now - room_age, 'availability': 'online'}
    x._heat_state_cache = None
    x._zbt_cache = None


def follow(x):
    del x.sent[:]
    try:
        return x.heating_follow(force=True)
    except Exception as e:                               # noqa: BLE001
        check(False, 'heating_follow: %r' % e)
        return None


def calibrations(x):
    return [s for s in x.sent if s[1] == 'local_temperature_calibration']


def set_room(x, **changes):
    cfg = x.heating_config()
    rooms = {k: dict(v) for k, v in cfg['rooms'].items()}
    rooms['r1'].update(changes)
    x.save_heating({'rooms': rooms, '_quiet': True})


def age_memory(x, minutes):
    for v in x._follow_memory().values():
        v['at'] -= minutes * 60


# ---- off by default ------------------------------------------------------------------------------
print('off by default: nothing is written')
cfg = d.heating_config()
check(cfg['rooms']['r1'].get('follow_room') is False, 'a room without the setting follows: %r' % cfg['rooms']['r1'])
report(d)
follow(d)
check(not d.sent, 'a room that did not ask had its heads written to: %r' % d.sent)
check(zigmon.DEFAULTS.get('heating_follow_every_min') == 30 and zigmon.DEFAULTS.get('heating_follow_min_diff') == 0.5,
      'the defaults: %r %r' % (zigmon.DEFAULTS.get('heating_follow_every_min'),
                               zigmon.DEFAULTS.get('heating_follow_min_diff')))

# ---- on -----------------------------------------------------------------------------------------
print('on: the offset goes out, once')
set_room(d, follow_room=True)
check(d.heating_config()['rooms']['r1'].get('follow_room') is True, 'the setting was not saved')
check(next(r for r in d.heating_state()['rooms'] if r['id'] == 'r1').get('follow_room') is True,
      'the room\'s state does not say it follows')
report(d)
follow(d)
check(calibrations(d) == [(HEAD, 'local_temperature_calibration', 'set:=-2')],
      'head 27.5, room 25.6, offset 0 should be -2.0: %r' % d.sent)
check(not [s for s in d.sent if s[0] == HEAD2], 'a head without an offset was written to: %r' % d.sent)
events = [e for e in d.store.events(50, text='kept Head-Loznice') if 'matched to Temp-Loznice' in (e.get('detail') or '')]
check(events and 'offset 0 → -2 °C (room 25.6, head 27.5)' in events[0]['detail'],
      'the event: %r' % [e.get('detail') for e in events])
facts = next(r for r in d.heating_state()['rooms'] if r['id'] == 'r1')['valves']
check(any(isinstance(v.get('followed_at'), (int, float)) for v in facts), 'the valve does not say when: %r' % facts)

print('not again before the head has reported since')
age_memory(d, 31)
# the same reading as before the change: the head has not said anything since
d.live[HEAD]['ts'] = d._follow_memory()[HEAD]['at'] - 5
d.live[HEAD]['ts'] = max(d.live[HEAD]['ts'], time.time() - 600)
d._follow_memory()[HEAD]['at'] = d.live[HEAD]['ts'] + 1
follow(d)
check(not calibrations(d), 'written again before the head reported its new reading: %r' % d.sent)

print('not again within the interval')
report(d, head_c=27.0, cal=-2.0)          # the head has reported, and is still off by more than the step
d._follow_memory()[HEAD]['at'] = time.time() - 10 * 60
follow(d)
check(not calibrations(d), 'written again ten minutes after the last: %r' % d.sent)
d._follow_memory()[HEAD]['at'] = time.time() - 29 * 60
follow(d)
check(not calibrations(d), 'written again 29 minutes after the last, with 30 set: %r' % d.sent)

print('the interval is the setting\'s')
zigmon.CONFIG['heating_follow_every_min'] = 15
report(d, head_c=27.0, cal=-2.0)
d._follow_memory()[HEAD]['at'] = time.time() - 16 * 60
follow(d)
check(calibrations(d) == [(HEAD, 'local_temperature_calibration', 'set:=-3.5')],
      'with 15 min set, 16 min later (room 25.6, head 27.0, offset -2): %r' % d.sent)
zigmon.CONFIG['heating_follow_every_min'] = 30

print('a difference under the minimum: nothing')
report(d, head_c=25.9, cal=-3.5)
age_memory(d, 60)
follow(d)
check(not calibrations(d), 'written for 0.3 °C: %r' % d.sent)
zigmon.CONFIG['heating_follow_min_diff'] = 0.2
follow(d)
check(len(calibrations(d)) == 1, 'nothing for 0.3 °C with 0.2 the minimum: %r' % d.sent)
zigmon.CONFIG['heating_follow_min_diff'] = 0.5

print('a thermometer gone quiet, a head gone quiet: nothing')
report(d, room_age=3600)
age_memory(d, 60)
follow(d)
check(not calibrations(d), 'written on an hour-old room reading: %r' % d.sent)
report(d, head_age=3600)
follow(d)
check(not calibrations(d), 'written on an hour-old head reading: %r' % d.sent)
d.live.pop(THERMO, None)
d._heat_state_cache = None
follow(d)
check(not calibrations(d), 'written with no room reading at all: %r' % d.sent)

print('a manual room, a room shut, heating off, control off: nothing')
for what, changes in (('manual', {'mode': 'manual'}), ('off', {'mode': 'off'}), ('control off', {'control': False})):
    set_room(d, **changes)
    report(d)
    age_memory(d, 60)
    follow(d)
    check(not calibrations(d), 'written in a room that is %s: %r' % (what, d.sent))
    set_room(d, mode='comfort', control=True)
d.save_heating({'enabled': False, '_quiet': True})
report(d)
follow(d)
check(not calibrations(d), 'written with the heating switched off: %r' % d.sent)
d.save_heating({'enabled': True, '_quiet': True})
set_room(d, window_stop=True)
d.store.upsert_device({'id': '0xwin0001', 'name': 'Win-Loznice', 'source': 'zigbee', 'kind': 'contact',
                       'exposes': {'contact': {'type': 'binary', 'access': 1}}})
d.store.set_meta('room_of', json.dumps({HEAD: 'r1', HEAD2: 'r1', THERMO: 'r1', '0xwin0001': 'r1'}))
d.live['0xwin0001'] = {'payload': {'contact': False}, 'ts': time.time(), 'availability': 'online'}
report(d)
check(next(r for r in d.heating_state()['rooms'] if r['id'] == 'r1').get('window_open'), 'the window does not read open')
follow(d)
check(not calibrations(d), 'written with a window open: %r' % d.sent)
d.live['0xwin0001']['payload']['contact'] = True
report(d)
follow(d)
check(len(calibrations(d)) == 1, 'nothing written once the window shut: %r' % d.sent)

print('without a thermometer chosen: nothing')
set_room(d, thermometer='')
report(d)
age_memory(d, 60)
follow(d)
check(not calibrations(d), 'written without a thermometer chosen: %r' % d.sent)
set_room(d, thermometer=THERMO)

print('the offset is what it would be: nothing')
report(d, head_c=25.6, cal=-2.0, room_c=25.6)
zigmon.CONFIG['heating_follow_min_diff'] = 0.1
report(d, head_c=25.5, cal=-2.0, room_c=25.6)
follow(d)
check(not calibrations(d), 'written to send the same offset again: %r' % d.sent)
zigmon.CONFIG['heating_follow_min_diff'] = 0.5

print('the time is kept across a restart')
report(d)
age_memory(d, 60)
follow(d)
check(len(calibrations(d)) == 1, 'nothing written before the restart: %r' % d.sent)
d2 = build()
report(d2)
d2.live[HEAD]['ts'] = time.time() + 1
follow(d2)
check(not calibrations(d2), 'written again at once after a restart: %r' % d2.sent)
check(HEAD in d2._follow_memory(), 'the time was not kept: %r' % d2._follow_memory())

print('"Match the room" by hand answers as it did')
report(d)
del d.sent[:]
ok, message = d.calibrate_valve('zb:%s:current_heating_setpoint' % HEAD)
check(ok and message == 'offset set to -2 °C' and d.sent == [(HEAD, 'local_temperature_calibration', 'set:=-2')],
      'Match the room: %r %r %r' % (ok, message, d.sent))
report(d, head_c=20.0, cal=8.0, room_c=25.6)
del d.sent[:]
ok, message = d.calibrate_valve('zb:%s:current_heating_setpoint' % HEAD)
check(ok and message == 'offset set to +9 °C', 'clamped at +9: %r %r' % (ok, message))
check(zigmon.Daemon.calibration_for(None, 25.6, 27.5) == -2.0 and zigmon.Daemon.calibration_for(-2.0, 25.6, 25.6) == -2.0
      and zigmon.Daemon.calibration_for(0, 0, 30) == -9.0, 'the shared arithmetic')
d.live.pop(THERMO, None)
d._heat_state_cache = None
ok, message = d.calibrate_valve('zb:%s:current_heating_setpoint' % HEAD)

print('heat Loznice follow on|off')
said = d.heat_say('Loznice follow off')
check(d.heating_config()['rooms']['r1'].get('follow_room') is False and 'no longer follows' in said, said)
said = d.heat_say('Loznice follow')
check('does not follow' in said, said)
said = d.heat_say('Loznice follow on')
check(d.heating_config()['rooms']['r1'].get('follow_room') is True and 'follows' in said, said)
check(d.heating_config()['rooms']['r1'].get('thermometer') == THERMO, 'the thermometer was lost on the way')
said = d.heat_say('Loznice follow maybe')
check('not on, off or toggle' in said, said)
check('heat Loznice follow on | off' in (zigmon.Daemon.heat_say.__doc__ or ''), 'the help does not say it')

print('the Settings page')
rc = d.runtime_config()
every = rc.get('heating_follow_every_min') or {}
check(every.get('kind') == 'choice' and [c[0] for c in every.get('choices') or []] ==
      ['15', '30', '45', '60', '90', '120', '180', '240'] and every.get('default') == 30, 'every: %r' % every)
check((rc.get('heating_follow_min_diff') or {}).get('kind') == 'decimal', 'min diff: %r' % rc.get('heating_follow_min_diff'))
try:
    d.save_config_overrides({'heating_follow_every_min': '60'})
    check(zigmon.CONFIG.get('heating_follow_every_min') == 60, 'saved as %r' % zigmon.CONFIG.get('heating_follow_every_min'))
except ValueError as e:
    check(False, 'a choice of the page was refused: %s' % e)
try:
    d.save_config_overrides({'heating_follow_every_min': '5'})
    check(False, 'every 5 minutes was taken')
except ValueError:
    pass
check(d.heating_state().get('follow_every_min') == 60, 'the card is not told the interval')
d.save_config_overrides({'heating_follow_every_min': '30'})
page = (HERE / 'web' / 'index.php').read_text()
for words in ("['heating_follow_every_min', 'Follow the room thermometer: every N min'",
              "'heating_follow_min_diff'", "'Follow the room thermometer'",
              "so it reads what the room reads; heads without an offset setting are left alone",
              "follow_room: !!r.follow_room", "followSw.classList.add('needs-unlock')", "'matched '",
              "'reading small valve-offset'", "(d.values || {}).local_temperature_calibration", "'follows '"):
    check(words in page, 'the page has no %s' % words)

# ---- the card in Chromium ---------------------------------------------------------------------------
print('the card')
npm_root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()
if not (Path(npm_root) / 'playwright').exists() or not subprocess.run(['which', 'php'], capture_output=True,
                                                                       stdin=subprocess.DEVNULL).returncode == 0:
    print('  SKIPPED (no browser or php here)')
else:
    import shutil
    api = zigmon.ApiServer(d)
    api.start()
    time.sleep(0.3)
    try:
        def call(path, body=None):
            headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json',
                       'X-Zigmon-Client': '192.168.40.10'}
            req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                         data=None if body is None else json.dumps(body).encode(),
                                         method='GET' if body is None else 'POST')
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.status, json.loads(r.read() or b'{}')
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b'{}')

        d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
        S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
        report(d)
        age_memory(d, 60)
        follow(d)
        report(d, head_c=25.6, cal=-2.0)          # the head has taken it and said so
        shutil.copytree(HERE / 'web', W / 'web')
        api_php = (W / 'web' / 'zigmon-api.php').read_text()
        api_php = api_php.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
        api_php = api_php.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
        (W / 'web' / 'zigmon-api.php').write_text(api_php)
        php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, str(W / 'web' / 'index.php')],
                               cwd=str(W / 'web'), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               stdin=subprocess.DEVNULL, env=dict(os.environ, PHP_CLI_SERVER_WORKERS='4'))
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
const job = %(job)s;
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({viewport: {width: 1400, height: 1400}, colorScheme: 'dark'});
  await ctx.addCookies([{name: 'zigmon_session', value: job.s, url: 'http://127.0.0.1:' + job.port + '/'}]);
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.goto('http://127.0.0.1:' + job.port + '/#heating');
  await p.waitForTimeout(1500);
  try { await p.click('button[data-tab="heating"]'); } catch (e) {}
  await p.waitForSelector('#heating-rooms .heatcard .heat-follow', {timeout: 20000});
  await p.waitForTimeout(800);
  const r = await p.evaluate(() => {
    const c = document.querySelector('#heating-rooms .heatcard');
    const f = c.querySelector('.heat-follow');
    return {label: f.querySelector('label').textContent, on: f.querySelector('input').checked,
            hint: (f.querySelector('.heat-follow-hint') || {}).textContent || '',
            valves: Array.from(c.querySelectorAll('.heat-valve')).map(x => x.textContent)};
  });
  await (await p.$('#heating-rooms .heatcard')).screenshot({path: job.dir + '/room-card-follow.png'});
  // the heads' own cards on the Sensors tab
  await p.click('button[data-tab="sensors"]');
  await p.waitForSelector('#sensor-cards .card', {timeout: 20000});
  await p.waitForTimeout(800);
  r.sensors = await p.evaluate(() => {
    const out = {};
    Array.from(document.querySelectorAll('#sensor-cards .card')).forEach(c => {
      const t = c.textContent;
      const name = ['Head-Loznice', 'Head-Plain', 'Temp-Loznice'].find(n => t.indexOf(n) >= 0);
      if (!name) return;
      const o = c.querySelector('.valve-offset');
      const rs = Array.from(c.querySelectorAll('.readings .reading'));
      out[name] = o ? {v: o.querySelector('.v').textContent, l: o.querySelector('.l').textContent,
                       follows: (c.querySelector('.valve-follows') || {}).textContent || '',
                       // the offset sits in the row of the set point and the valve, or right after it
                       after: rs.indexOf(o) === rs.length - 1 && rs.length >= 3,
                       top: o.getBoundingClientRect().top - rs[1].getBoundingClientRect().top} : null;
    });
    return out;
  });
  for (const c of await p.$$('#sensor-cards .card')) {
    if ((await c.textContent()).indexOf('Head-Loznice') >= 0) { await c.screenshot({path: job.dir + '/sensor-card-offset.png'}); break; }
  }
  r.errors = errors;
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
        job = {'s': S, 'port': PHP_PORT, 'dir': str(SHOTS)}
        (W / 'page.js').write_text(js % {'job': json.dumps(job)})
        got = subprocess.run(['node', str(W / 'page.js')], capture_output=True, text=True, timeout=240,
                             stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=npm_root))
        try:
            r = json.loads(got.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            r = {'error': (got.stdout + got.stderr)[-300:]}
        if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
            print('  SKIPPED (no browser here): %s' % r['error'][:200])
        else:
            check(not r.get('error') and r.get('label') == 'Follow the room thermometer' and r.get('on') is True
                  and 'every 30 min' in r.get('hint', ''), 'the card: %r' % r)
            check(any('matched ' in v for v in r.get('valves') or []), 'the valve line has no time: %r' % r.get('valves'))
            sens = r.get('sensors') or {}
            check((sens.get('Head-Loznice') or {}).get('l') == 'Offset' and (sens.get('Head-Loznice') or {}).get('after')
                  and 0 <= (sens.get('Head-Loznice') or {}).get('top', 999) < 80, 'where the offset is: %r' % sens)
            check((sens.get('Head-Loznice') or {}).get('v') == '-2\u00b0C' and
                  (sens.get('Head-Loznice') or {}).get('follows', '').startswith('follows Temp-Loznice \u00b7 matched '),
                  'the head\'s card has no offset or no follow note: %r' % sens)
            check('Head-Plain' in sens and sens['Head-Plain'] is None, 'a head without an offset shows one: %r' % sens)
            check('Temp-Loznice' in sens and sens['Temp-Loznice'] is None, 'a thermometer shows an offset: %r' % sens)
            check(not r.get('errors'), 'the page threw: %r' % r.get('errors'))
            print('  screenshot: %s' % (SHOTS / 'room-card-follow.png'))
    finally:
        for p in PROCS:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        try:
            api.stop()
        except Exception:                                    # noqa: BLE001
            pass

print()
if bad:
    print('%d FAILED' % len(bad))
    sys.exit(1)
print('all good')
