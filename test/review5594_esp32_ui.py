#!/usr/bin/env python3
"""5.59.4: the things of an ESP32 gateway made first-class everywhere a device is, against the fake gateway.

  * the status carries what the cards need: the gateway's model, uptime, clock, modules (with their
    versions and how many of their things are used), each thing's module and the gateway's Wi-Fi;
  * a lock's state is a reading of its own ("locked", yes/no): charted in the history, watched by a
    rule ("when Front drawer becomes unlocked, lock the cabinet"), and the battery beside it;
  * the object model: a thing's gateway, module and type, its state, battery, last action and how it
    went, a procedure for every action it described (no Zigbee on/off on a lock), and the gateway's
    own firmware, modules, online and detect();
  * {Front drawer.state} and {Front drawer.battery} in a text; Front drawer.lock() from a script and
    from the object view; the facts offered for the typing;
  * by type alone, nothing known of a module: a gateway restarted with a new module brings its
    devices at once, said as "new module Relay (2 devices)"; a thing it no longer describes is kept,
    offline and marked gone, with its history, until it is removed;
  * a low battery and an offline gateway said in the health of the house like any device's;
  * the page (Playwright, desktop and phone): the lock card in the Overview grid with its state in
    colour, its last action, Open / Unlock / Lock, its battery, "via Hall" and the gateway's Wi-Fi;
    the gateway's card; a switch, a sensor, a binary sensor, a button, a number and a select drawn by
    their type, an unknown type read only; the confirm step; Settings - Devices with the gateway,
    its modules and their things nested; the Devices table and the Overview picker grouped by gateway;
    "Find anything" finds them; the device key nowhere on the page.

    python3 test/review5594_esp32_ui.py < /dev/null

Ports 20380 (the API), 20381 (the fake gateway) and 20382 (php -S). Every name and number is made up.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / 'test'))
W = Path(tempfile.mkdtemp(prefix='zigmon-espui-'))
API_PORT, GW_PORT, PHP_PORT = 20380, 20381, 20382
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def port_free(port):
    for _ in range(60):
        s = socket.socket()
        try:
            s.bind(('127.0.0.1', port))
            s.close()
            return True
        except OSError:
            s.close()
            time.sleep(2)
    return False


def until(fn, secs=10.0, step=0.05):
    end = time.time() + secs
    while time.time() < end:
        try:
            got = fn()
        except Exception:                                   # noqa: BLE001
            got = None
        if got:
            return got
        time.sleep(step)
    return None


for p in (API_PORT, GW_PORT, PHP_PORT):
    if not port_free(p):
        print('port %d stays busy' % p)
        sys.exit(2)

sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                               # noqa: E402
import mockesp                                              # noqa: E402

LOG = []
zigmon.log = lambda msg, level='info', *a, **k: LOG.append('%s %s' % (level, msg))
zigmon.load_config()
(W / 'state').mkdir()
zigmon.CONFIG.update({
    'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1', 'token_file': str(W / 'token'),
    'pin': '', 'sensors': [], 'plugs': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(W / 'state'),
    'debug': 0, 'blacklist': 0, 'public_view': False, 'deck_dir': str(W / 'nodeck'), 'heating_enforce': 'never'})

d = zigmon.Daemon()
d.notify = lambda *a, **k: None
d.ESP_WAIT_S = 1
d.ESP_BACKOFF_S = (0.2, 0.5)
d.ESP_HELLO_S = 2
d.ESP_RESULT_S = 6
gw = mockesp.FakeGateway(GW_PORT)
now = int(time.time())
gw.states['yeelock.front']['last'] = {'action': 'open', 'ok': True, 'at': now - 130, 'msg': ''}
# a lock with a low battery and a failed open, and one thing of a type nobody knows yet
gw.entities.append({'id': 'yeelock.garage', 'module': 'yeelock', 'type': 'lock', 'name': 'Garage box',
                    'actions': ['open', 'unlock', 'lock', 'refresh'],
                    'attrs': [{'key': 'battery', 'label': 'Battery', 'type': 'number', 'unit': '%'}],
                    'confirm': ['open', 'unlock']})
gw.states['yeelock.garage'] = {'available': True, 'value': 'unlocked', 'busy': False, 'attrs': {'battery': 7},
                               'last': {'action': 'open', 'ok': False, 'at': now - 400, 'msg': 'wrong key'}}
gw.entities.append({'id': 'climate.ir', 'module': 'climate', 'type': 'hologram', 'name': 'Cabinet beam',
                    'actions': ['blink'], 'attrs': [], 'confirm': []})
gw.states['climate.ir'] = {'available': True, 'value': 'shimmering', 'busy': False, 'attrs': {}, 'last': None}
gw.start()
ADDR = '127.0.0.1:%d' % GW_PORT
GWID = mockesp.GW_ID
GWDEV = 'esp:%s' % GWID
FRONT, CAB, BOX = ('esp:%s:yeelock.front' % GWID, 'esp:%s:yeelock.cabinet' % GWID, 'esp:%s:climate.box' % GWID)
GAR, BEAM = 'esp:%s:yeelock.garage' % GWID, 'esp:%s:climate.ir' % GWID
FAN, LID = 'esp:%s:relay.fan' % GWID, 'esp:%s:relay.lid' % GWID
api = zigmon.ApiServer(d)
api.start()
threading.Thread(target=d.rule_worker, daemon=True).start()          # the rules, as the daemon runs them
time.sleep(0.3)


def call(path, body=None, session=None):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': '192.168.40.10'}
    if session:
        headers['X-Zigmon-Session'] = session
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                 data=None if body is None else json.dumps(body).encode(),
                                 method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def events():
    d.store.flush(10)
    with d.store.lock:
        return [r[0] for r in d.store.db.execute('SELECT detail FROM events ORDER BY id').fetchall()]


def payload(dev):
    return (d.live.get(dev) or {}).get('payload') or {}


def members(dev):
    row = d.store.device(dev)
    return {m['name']: m for m in d._obj_members('device', dev, row, values=True)}


def status_dev(dev):
    return next((x for x in d.status()['devices'] if x['id'] == dev), None)


php = None
try:
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
    S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
    check(S, 'the sign-in')
    code, out = call('/api/esp', {'action': 'probe', 'address': ADDR}, S)
    code, out = call('/api/esp', {'action': 'pair', 'address': ADDR, 'code': gw.new_code(), 'fingerprint': out.get('fingerprint'),
                                  'confirmed': True, 'name': 'Hall'}, S)
    check(code == 200, 'pairing: %s %r' % (code, out))
    KEY = (d.esp_row(GWID) or {}).get('key') or ''
    code, out = call('/api/esp', {'action': 'detect', 'id': GWID}, S)
    check(code == 200 and out.get('entities') == 5, 'detect: %s %r' % (code, out))
    check(until(lambda: payload(FRONT).get('state') == 'locked' and payload(GAR).get('state') == 'unlocked'), 'the states')
    check(until(lambda: (d.esp_dashboard()['gateways'] or [{}])[0].get('fw') if 'model' in
                (d.esp_dashboard()['gateways'] or [{}])[0] else None, 8), 'the hello')

    # ---- 1. what the cards need ------------------------------------------------------------
    print('the status carries what the cards need')
    st = d.status()
    g = (st['esp']['gateways'] or [{}])[0]
    check(g.get('model') == 'esp32s3' and g.get('uptime') == 1234 and g.get('time_set') is True
          and g.get('device') == GWDEV, 'the gateway for its card: %r' % g)
    mods = {m['id']: m for m in g.get('module_list') or []}
    check(set(mods) == {'yeelock', 'climate'} and mods['yeelock']['version'] == '1.0.0'
          and mods['yeelock']['entities'] == 3 and mods['yeelock']['used'] == 3, 'its modules: %r' % mods)
    ents = {e['id']: e for e in st['esp']['entities']}
    fr = ents.get(FRONT) or {}
    check(fr.get('module_name') == 'Yeelock locks' and fr.get('gw_rssi') == -58 and fr.get('gw_name') == 'Hall'
          and fr.get('confirm') == ['open', 'unlock'] and fr.get('last', {}).get('action') == 'open'
          and fr.get('values', {}).get('battery') == 87, 'the lock for its card: %r' % fr)
    check((ents.get(BEAM) or {}).get('type') == 'unknown' and (ents.get(BEAM) or {}).get('actions') == [],
          'an unknown type, read only: %r' % ents.get(BEAM))
    check(not any(k in json.dumps(st['esp']) for k in (KEY, gw.fingerprint, ADDR)), 'a secret or the address in the status')

    # ---- 2. the lock's state as a reading, the history, the rules -----------------------------
    print('a lock\'s state: charted and watched')
    check(payload(FRONT).get('locked') is True and payload(GAR).get('locked') is False, 'locked yes/no: %r' % payload(FRONT))
    row = status_dev(FRONT) or {}
    check((row.get('values') or {}).get('locked', {}).get('label') == 'Locked', 'its label: %r' % row.get('values'))
    check(payload(BOX).get('locked') is None, 'a sensor has no "locked"')
    code, out = call('/api/esp/command', {'id': FRONT, 'action': 'unlock', 'confirmed': True}, S)
    check(code == 202, 'unlock: %s %r' % (code, out))
    check(until(lambda: payload(FRONT).get('locked') is False, 6), 'unlocked: locked is no')
    d.store.flush(10)
    keys = d.store.keys_for(FRONT)
    check('locked' in keys and 'battery' in keys, 'the history of the lock: %r' % keys)
    with d.store.lock:
        vals = [r[0] for r in d.store.db.execute("SELECT value FROM samples WHERE device=? AND key='locked' ORDER BY ts",
                                                 (FRONT,)).fetchall()]
    check(vals and vals[-1] == 0.0, 'unlocked recorded as locked = 0: %r' % vals)
    code, out = call('/api/esp/command', {'id': FRONT, 'action': 'lock'}, S)
    check(until(lambda: payload(FRONT).get('locked') is True, 6), 'locked again')
    # a rule: when the drawer becomes unlocked, lock the cabinet
    d.save_rules([{'device': FRONT, 'key': 'locked', 'op': '==', 'value': 0, 'plug': CAB, 'do': 'lock', 'enabled': True},
                  {'device': GAR, 'key': 'battery', 'op': '<', 'value': 10, 'plug': 'notify', 'do': 'on', 'enabled': True}])
    check(len(d.rules()) == 2, 'the rules saved: %r' % d.rules())
    code, out = call('/api/esp/command', {'id': CAB, 'action': 'unlock', 'confirmed': True}, S)
    check(until(lambda: payload(CAB).get('state') == 'unlocked', 6), 'the cabinet unlocked first')
    time.sleep(0.5)
    n = len(events())
    code, out = call('/api/esp/command', {'id': FRONT, 'action': 'unlock', 'confirmed': True}, S)
    check(until(lambda: payload(CAB).get('state') == 'locked', 8), 'the rule on the lock did not lock the cabinet: %r'
          % events()[n:])
    check(until(lambda: any(e.startswith('Medicine cabinet: locked') and 'rule' in e for e in events()[n:]), 6),
          'the rule\'s event: %r' % events()[n:])
    call('/api/esp/command', {'id': FRONT, 'action': 'lock'}, S)
    until(lambda: payload(FRONT).get('locked') is True, 6)

    # ---- 3. the object model ---------------------------------------------------------------------
    print('the object model')
    until(lambda: not payload(FRONT).get('busy'), 4)
    m = members(FRONT)
    for name, kind in (('gateway', 'prop'), ('module', 'prop'), ('type', 'prop'), ('name', 'prop'), ('source', 'prop'),
                       ('state', 'func'), ('battery', 'func'), ('last_action', 'func'), ('last_ok', 'func'),
                       ('last_msg', 'func'), ('last_at', 'func'), ('busy', 'func'), ('available', 'func'),
                       ('locked', 'func'), ('open', 'proc'), ('unlock', 'proc'), ('lock', 'proc'), ('refresh', 'proc')):
        check(name in m and m[name]['kind'] == kind, 'the lock\'s %s (%s): %r' % (name, kind, m.get(name)))
    check(m.get('gateway', {}).get('value') == 'Hall' and m.get('module', {}).get('value') == 'Yeelock locks'
          and m.get('type', {}).get('value') == 'lock' and m.get('last_action', {}).get('value') == 'lock'
          and m.get('last_ok', {}).get('value') is True and m.get('available', {}).get('value') is True,
          'the values: %r' % {k: m[k].get('value') for k in m})
    check('on' not in m and 'off' not in m, 'a lock offered Zigbee\'s on and off: %r' % sorted(m))
    check('sensitive' in (m.get('unlock') or {}).get('doc', '') and 'sensitive' not in (m.get('lock') or {}).get('doc', ''),
          'which are sensitive: %r %r' % (m.get('unlock'), m.get('lock')))
    gm = members(GWDEV)
    for name, kind in (('firmware', None), ('modules', 'prop'), ('online', 'func'), ('devices', 'func'),
                       ('time_set', 'func'), ('detect', 'proc')):
        check(name in gm and (kind is None or gm[name]['kind'] == kind), 'the gateway\'s %s: %r' % (name, gm.get(name)))
    check(gm.get('online', {}).get('value') is True and gm.get('devices', {}).get('value') == 5,
          'the gateway\'s values: %r' % {k: gm[k].get('value') for k in gm})
    gar = members(GAR)
    check(gar.get('last_ok', {}).get('value') is False and gar.get('last_msg', {}).get('value') == 'wrong key',
          'a failed open: %r' % {k: gar[k].get('value') for k in gar})
    beam = members(BEAM)
    check(not [k for k, v in beam.items() if v['kind'] == 'proc' and k not in ('rename',)],
          'an unknown type has nothing to call: %r' % sorted(beam))
    objs = {o['ref']: o for o in d.objects()}
    fo = objs.get('device:' + FRONT) or {}
    names = [x[0] for x in fo.get('members') or []]
    check(fo.get('call') == 'Front drawer' and all(k in names for k in ('state', 'battery', 'last_action', 'unlock')),
          'the typing offers: %r' % fo)
    # facts in a text and in an alert
    said = d.fill_message('{Front drawer.state} {Front drawer.battery} {Front drawer.last_action} {Front drawer.locked} '
                          '{Front drawer.gateway} {Hall.online} {Garage box.last_msg}', {})
    check(said.split()[0] == 'locked' and said.split()[1].isdigit() and 70 < int(said.split()[1]) <= 87,
          'the facts: %r' % said)
    check(said.endswith('lock yes Hall yes wrong key'), 'the facts: %r' % said)
    # calling it: from the object view, from a script
    n = len(events())
    out = d.object_call('Front drawer', 'refresh', '', origin='the object view')
    check('asked' in out, 'Front drawer.refresh(): %r' % out)
    until(lambda: not payload(FRONT).get('busy'), 4)
    time.sleep(0.4)
    ran = d.run_script({'name': 'leaving', 'body': 'Garage box.lock()'}, {}, 'script leaving')
    check(not ran.get('faults'), 'Garage box.lock() from a script: %r' % ran)
    check(until(lambda: payload(GAR).get('state') == 'locked', 6), 'the script locked it')
    check(until(lambda: any(e.startswith('Garage box: locked by script leaving') for e in events()[n:]), 6),
          'the script\'s event: %r' % events()[n:])
    check(d.script_faults('Front drawer.unlock()\nFront drawer.lock()') == [], 'the lines are good: %r'
          % d.script_faults('Front drawer.unlock()'))
    check(d.script_faults('Cabinet temperature.unlock()') != [], 'a sensor cannot be unlocked')
    try:
        d.object_call('Front drawer', 'explode', '')
        check(False, 'an action it does not have was called')
    except ValueError:
        pass

    # ---- 4. the health: a low battery, an offline gateway -------------------------------------
    print('the health of the house')
    row = status_dev(GAR) or {}
    check(row.get('level') == 'crit' and any('batter' in r for r in row.get('reasons') or []), 'a low battery: %r' % row)
    gw.stop()
    check(until(lambda: (status_dev(FRONT) or {}).get('availability') == 'offline', 10), 'the lock not offline')
    check(until(lambda: (status_dev(GWDEV) or {}).get('availability') == 'offline', 5), 'the gateway not offline')
    st = d.status()
    check(st['counts']['online'] < st['counts']['devices'], 'the counts: %r' % st['counts'])
    check(members(FRONT)['available']['value'] is False and members(GWDEV)['online']['value'] is False,
          'available and online, offline')
    gw.start()
    check(until(lambda: (status_dev(FRONT) or {}).get('availability') == 'online', 10), 'the lock back')

    # ---- 5. modular: a new module after a restart, a thing gone --------------------------------
    print('a new module, a thing gone')
    gw.entities += [{'id': 'relay.fan', 'module': 'relay', 'type': 'switch', 'name': 'Cabinet fan',
                     'actions': ['toggle', 'on', 'off'], 'attrs': [], 'confirm': []},
                    {'id': 'relay.lid', 'module': 'relay', 'type': 'binary_sensor', 'name': 'Box lid', 'actions': [],
                     'attrs': [], 'confirm': []}]
    gw.states['relay.fan'] = {'available': True, 'value': 'off', 'busy': False, 'attrs': {}, 'last': None}
    gw.states['relay.lid'] = {'available': True, 'value': True, 'busy': False, 'attrs': {}, 'last': None}
    gw.entities = [e for e in gw.entities if e['id'] != 'climate.ir']        # the beam is gone
    gw.reboot()
    check(until(lambda: d.store.device(FAN) and d.store.device(LID), 10), 'the new module\'s devices: %r' % events()[-4:])
    check(until(lambda: any('ESP32 gateway Hall: new module Relay (2 devices)' in e for e in events()), 4),
          'the new module said: %r' % events()[-5:])
    check(until(lambda: payload(FAN).get('state') == 'off' and payload(LID).get('state') is True, 6), 'their states')
    ents = {e['id']: e for e in d.status()['esp']['entities']}
    check(FAN in ents and ents[FAN]['module_name'] == 'Relay' and ents[FAN]['actions'] == ['toggle', 'on', 'off'],
          'the fan for its card: %r' % ents.get(FAN))
    fm = members(FAN)
    check(all(k in fm and fm[k]['kind'] == 'proc' for k in ('toggle', 'on', 'off')) and fm['module']['value'] == 'Relay',
          'the fan\'s members: %r' % sorted(fm))
    check(any(t['value'] == FAN for t in d.status()['switch_targets']), 'the fan as a target')
    # the beam: kept, offline, gone - with its history - until removed
    check(d.store.device(BEAM) and not d.store.device(BEAM).get('removed'), 'the gone thing deleted')
    check(until(lambda: (status_dev(BEAM) or {}).get('availability') == 'offline', 4), 'the gone thing not offline')
    check((ents.get(BEAM) or {}).get('gone') is True, 'the gone thing on the dashboard: %r' % ents.get(BEAM))
    admin = (call('/api/esp', session=S)[1].get('gateways') or [{}])[0]
    check([x['id'] for x in admin.get('gone') or []] == ['climate.ir'], 'the admin view: %r' % admin.get('gone'))
    code, out = call('/api/esp', {'action': 'forget_entity', 'id': GWID, 'entity': 'yeelock.front'}, S)
    check(code == 400, 'removing one that is still there: %s %r' % (code, out))
    SO = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''
    code, out = call('/api/esp', {'action': 'forget_entity', 'id': GWID, 'entity': 'climate.ir'}, SO)
    check(code == 403, 'an operator removing: %s' % code)

    # ---- 6. the page --------------------------------------------------------------------------
    print('the page')
    web = W / 'web'
    shutil.copytree(str(HERE / 'web'), str(web))
    t = (web / 'zigmon-api.php').read_text()
    t = t.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
    t = t.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
    (web / 'zigmon-api.php').write_text(t)
    (W / 'token').write_text(d.token)
    php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, '-t', str(web)], cwd=str(web),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                           env=dict(os.environ, PHP_CLI_SERVER_WORKERS='6'))
    until(lambda: socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close() or True, 10)
    node_path = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
    if not node_path or not (Path(node_path) / 'playwright').exists():
        check(False, 'no playwright here')
    else:
        (W / 'page.js').write_text((HERE / 'test' / 'review5594_esp32_ui.js').read_text())
        cfg = {'base': 'http://127.0.0.1:%d' % PHP_PORT, 'front': FRONT, 'gar': GAR, 'gw': GWDEV, 'fan': FAN,
               'lid': LID, 'box': BOX, 'beam': BEAM, 'key': KEY, 'fp': gw.fingerprint}
        got = subprocess.run(['node', str(W / 'page.js')], capture_output=True, text=True, timeout=600, cwd=str(W),
                             stdin=subprocess.DEVNULL, env=dict(os.environ, NODE_PATH=node_path, H_CFG=json.dumps(cfg)))
        try:
            res = json.loads((got.stdout.strip().splitlines() or ['{}'])[-1])
        except ValueError:
            res = {'bad': ['the page script: ' + (got.stdout + got.stderr)[-1500:]]}
        for b in res.get('bad') or []:
            check(False, 'page: ' + b)
        for line in res.get('said') or []:
            print('  ' + line)
        check(res.get('checked', 0) > 30, 'the page checked too little: %r' % res.get('checked'))
    # after the page: the gone thing removed by the administrator (the page tried the operator's refusal)
    code, out = call('/api/esp', {'action': 'forget_entity', 'id': GWID, 'entity': 'climate.ir'}, S)
    check(code == 200 and (d.store.device(BEAM) is None or d.store.device(BEAM).get('removed')),
          'removing the gone thing: %s %r' % (code, out))
    d.store.flush(10)
    with d.store.lock:
        kept = (d.store.db.execute('SELECT COUNT(*) FROM snapshots WHERE device=?', (BEAM,)).fetchone()[0]
                + d.store.db.execute('SELECT COUNT(*) FROM samples WHERE device=?', (BEAM,)).fetchone()[0])
    check(kept > 0, 'its history kept: %r' % kept)
    check(BEAM not in {e['id'] for e in d.status()['esp']['entities']}, 'the removed thing still on the dashboard')
    check(any('Cabinet beam removed' in e for e in events()), 'the removal said: %r' % events()[-3:])
    # the device key: nowhere
    texts = {'the log': '\n'.join(LOG), 'the events': '\n'.join(events()), 'the status': json.dumps(d.status()),
             'the objects': json.dumps(d.objects()),
             'the members': json.dumps([d._obj_members('device', x, d.store.device(x), values=True)
                                        for x in (FRONT, GWDEV) if d.store.device(x)], default=str)}
    for name, text in texts.items():
        check(KEY and KEY not in text and KEY.upper() not in text, 'the device key in %s' % name)
finally:
    try:
        gw.close()
    except Exception:
        pass
    if php is not None:
        php.terminate()
    try:
        d.store.flush(5)
    except Exception:
        pass

print('FAILED: %d' % len(bad) if bad else 'all good')
sys.exit(1 if bad else 0)
