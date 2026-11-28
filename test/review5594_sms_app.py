#!/usr/bin/env python3
"""5.59.4: SMS for the desktop app and the Stream Deck asking it (windows/PROTOCOL-SMS.md, sections 2-3).

  * a desktop app key's "sms" block - read, send, contacts - every flag off until an
    administrator grants it (an operator cannot); hello says them, with "ready";
  * GET /api/notifier/sms (ZIGMon's own log, newest first, full numbers, the contact), GET
    /api/notifier/contacts and POST /api/notifier/sms/send, each refused (403, in words) without
    its flag; the send through sms_send - to numbers, contact:<id> and group:<name>, each number
    once, reply_to - at most 10 recipients, 10 a minute for each key (429), 409 with no gateway;
    the answer shaped as /api/sms/send's; the event names the key, never the text or a number,
    and the log file holds neither;
  * an incoming SMS in the wait of a key with sms.read only; one found already in the inbox is not;
  * the deck items sms:last and sms:compose under the new cap "sms" (off by default, and not shown
    by "view"); their state (today, last_from as a contact's name or …123, unread); the ask handed
    to the linked running apps as an event in their wait; 409 when none is linked, running, or
    allowed; the links: automatic by the computer's name (ignoring case), set by hand from the
    deck's side (action "apps", an administrator's, PIN) or from the key's side ("decks");
  * the relay: api=notifier&do=sms / contacts / sms-send (POST only), and the home network lock;
  * the pages in Chromium (Playwright), desktop and 390 px: a key's row with its three SMS switches
    (one switched there is saved), the key's dialog laid out as the Stream Deck's - presets, the
    sentence, the cards (sensors, conditions, SMS read, send, contacts, Stream Deck pop-ups) - a key
    made there; an installation's "Desktop apps on this deck's computer" with the automatic one and
    one ticked by hand; the deck's dialog with the "SMS via the desktop app" card and the new
    items in the "Only these" lists. Screenshots into $ZIGMON_SHOTS (or a temporary folder, kept).

    python3 test/review5594_sms_app.py < /dev/null

Ports 20340-20341. Every name, number and key here is made up.
"""
import hashlib
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
W = Path(tempfile.mkdtemp(prefix='zigmon-smsapp-'))
API_PORT, PHP_PORT = 20340, 20341
SHOTS = Path(os.environ.get('ZIGMON_SHOTS') or tempfile.mkdtemp(prefix='zigmon-smsapp-shots-'))
bad = []
PROCS = []


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


for p_ in (API_PORT, PHP_PORT):
    if not port_free(p_):
        print('port %d stays busy' % p_)
        sys.exit(2)

sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                               # noqa: E402

LOG = []
_real_log = zigmon.log
zigmon.log = lambda msg, level='info', *a, **k: LOG.append('%s %s' % (level, msg))
zigmon.load_config()
(W / 'state').mkdir()
zigmon.CONFIG.update({
    'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1', 'token_file': str(W / 'token'),
    'pin': '', 'sensors': [], 'plugs': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(W / 'state'),
    'debug': 1, 'blacklist': 0, 'public_view': False, 'deck_dir': str(W / 'nodeck'), 'notifier_dir': str(W / 'noapp'),
    'sms_enabled': 1, 'sms_host': '192.0.2.1', 'sms_api': 'rest', 'sms_modem': '1-1', 'sms_send_gap_s': 0,
    'sms_daily_cap': 0, 'heating_enforce': 'never'})
d = zigmon.Daemon()
d.notify = lambda message, *a, **k: None
d.sms_status_poll = lambda *a, **k: None
SENT = []


def _rest(path, method='GET', payload=None, retry=True, timeout=None):
    if path == '/messages/actions/send':
        SENT.append(dict(payload['data']))
        return {'success': True, 'data': {'sms_used': 1}}
    return {'success': True, 'data': []}


d._rest = _rest
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def call(path, body=None, session=None, key=None, deck=None, client='192.168.40.10', timeout=60, method=None):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': client}
    if session:
        headers['X-Zigmon-Session'] = session
    if key is not None:
        headers['X-Zigmon-Notifier'] = key
    if deck is not None:
        headers['X-Zigmon-Deck'], headers['X-Zigmon-Deck-Install'] = deck
    if body is not None and session:
        body = dict(body, session=session)
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                 data=None if body is None else json.dumps(body).encode(),
                                 method=method or ('GET' if body is None else 'POST'))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def events():
    d.store.flush(10)
    with d.store.lock:
        return [r[0] for r in d.store.db.execute('SELECT detail FROM events ORDER BY id').fetchall()]


CONTACTS = [
    {'id': 'c_5f2a9e', 'name': 'Jana Nováková', 'numbers': [{'label': 'mobile', 'number': '+420777123456'}],
     'group': 'Family', 'note': '', 'favourite': True},
    {'id': 'c_0b1c2d', 'name': 'Petr Novák', 'numbers': [{'label': 'mobile', 'number': '+420602111222'},
                                                         {'label': 'work', 'number': '+420602111333'}],
     'group': 'Family', 'note': 'brother', 'favourite': False},
    {'id': 'c_77aa88', 'name': 'Instalatér', 'numbers': [{'label': '', 'number': '+420731000999'}],
     'group': 'Work', 'note': '', 'favourite': False}]
TEXT = 'Ahoj Jano, dorazim v sest'
SECRETS = ('+420777123456', '420777123456', '777123456', '602111222', '603555123', TEXT, 'Prijdu pozdeji', 'Jsem doma')

try:
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
    S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
    SO = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''
    check(S and SO, 'could not sign in')
    d.store.set_meta('contacts', json.dumps(CONTACTS))
    d.store.set_meta('notifier_enabled', '1')
    d._ntf_on = None
    d.store.set_meta('deck_enabled', '1')

    print('keys: the sms flags, every one off until granted')
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'OFFICE-PC'}, session=S)
    check(code == 200 and out.get('key', '').startswith('zmn_'), 'create: %s %r' % (code, out))
    KEY, KID = out['key'], out['id']
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'Laptop',
                                            'sms': {'read': True, 'send': False, 'contacts': False}}, session=S)
    KEY2, KID2 = out['key'], out['id']
    code, out = call('/api/notifier/keys', session=S)
    rows = {k['id']: k for k in out.get('keys') or []}
    check(rows[KID]['sms'] == {'read': False, 'send': False, 'contacts': False}, 'a new key is not all off: %r' % rows[KID])
    check(rows[KID2]['sms'] == {'read': True, 'send': False, 'contacts': False}, 'a key made with read: %r' % rows[KID2])
    check(out.get('sms_ready') is True and out.get('deck_installs') == [], 'the keys page: %r' % [out.get('sms_ready'),
                                                                                                 out.get('deck_installs')])
    stored = {k['id']: k for k in d.notifier_keys()}
    check('sms' not in stored[KID], 'a key with nothing granted got an sms block: %r' % stored[KID])
    code, out = call('/api/notifier/hello', key=KEY)
    check(code == 200 and out.get('sms') == {'read': False, 'send': False, 'contacts': False, 'ready': True},
          'hello.sms: %s %r' % (code, out.get('sms')))
    for path in ('/api/notifier/sms', '/api/notifier/contacts'):
        code, out = call(path, key=KEY)
        check(code == 403 and 'may not' in out.get('error', '') and 'Settings - Messages - Desktop app' in out['error'],
              '%s without the flag: %s %r' % (path, code, out))
    code, out = call('/api/notifier/sms/send', {'to': ['+420777123456'], 'text': TEXT}, key=KEY)
    check(code == 403 and out.get('sent') == [] and out.get('failed') == [] and 'may not send' in out.get('error', '')
          and SENT == [], 'a send without the flag: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', {'action': 'update', 'id': KID, 'sms': {'read': True, 'send': True}}, session=SO)
    check(code == 403, 'an operator granted SMS: %s %r' % (code, out))
    for wrong in ({'read': 'yes'}, {'write': True}, ['read']):
        code, out = call('/api/notifier/keys', {'action': 'update', 'id': KID, 'sms': wrong}, session=S)
        check(code == 400, 'a wrong sms block %r: %s %r' % (wrong, code, out))
    code, out = call('/api/notifier/keys', {'action': 'update', 'id': KID,
                                            'sms': {'read': True, 'send': True, 'contacts': True}}, session=S)
    check(code == 200, 'grant: %s %r' % (code, out))
    check(any("owner changed the desktop notifier key 'OFFICE-PC' (every sensor; SMS: read, send, contacts)" in e
              for e in events()), 'the grant is not in the events')
    code, out = call('/api/notifier/hello', key=KEY)
    check(out.get('sms') == {'read': True, 'send': True, 'contacts': True, 'ready': True}, 'hello after: %r' % out.get('sms'))
    code, out = call('/api/notifier/keys', {'action': 'update', 'id': KID, 'name': 'OFFICE-PC'}, session=S)
    check(d.notifier_sms_flags(d.notifier_key_by_id(KID))['send'] is True, 'a rename took the flags away')

    print('the history: ZIGMon’s own log, full numbers, the contact')
    d.sms_note('in', '+420603555123', 'Jsem doma', True, 'was already here', key='old1', road='modem')
    d.sms_note('out', '+420777123456', 'Prijdu pozdeji', True, 'by hand')
    seq = d._ntf_seq
    d.sms_handle('+420777123456', TEXT, key='k1', road='push')
    code, out = call('/api/notifier/sms?limit=50', key=KEY)
    msgs = out.get('messages') or []
    check(code == 200 and [m['dir'] for m in msgs] == ['in', 'out', 'in'] and msgs[0]['text'] == TEXT
          and msgs[0]['number'] == '+420777123456' and msgs[0]['contact'] == {'id': 'c_5f2a9e', 'name': 'Jana Nováková'}
          and msgs[2]['contact'] is None and msgs[1]['ok'] is True and set(msgs[0]) == {'id', 'dir', 'number', 'contact',
                                                                                       'text', 'at', 'ok'},
          'the history: %s %r' % (code, msgs))
    code, out = call('/api/notifier/sms?limit=1', key=KEY)
    check(len(out.get('messages') or []) == 1, 'limit: %r' % out)
    code, out = call('/api/notifier/sms?limit=x', key=KEY)
    check(code == 200 and len(out.get('messages') or []) == 3, 'a bad limit: %s %r' % (code, out))

    print('an incoming SMS in the waits of keys with sms.read only')
    k1, k2 = d.notifier_key_by_id(KID), d.notifier_key_by_id(KID2)
    got = d.notifier_wait(k1, seq, d.notifier_boot, timeout=0.2)
    ev = [e for e in got.get('events') or [] if e['kind'] == 'sms']
    check(len(ev) == 1 and ev[0]['device'] == 'sms' and ev[0]['key'] == 'in' and ev[0]['active'] is True
          and ev[0]['what'] == 'sms' and ev[0]['sms']['text'] == TEXT and ev[0]['sms']['from'] == '+420777123456'
          and ev[0]['sms']['contact'] == {'id': 'c_5f2a9e', 'name': 'Jana Nováková'} and ev[0]['sms']['id'] == msgs[0]['id']
          and isinstance(ev[0]['sms']['at'], int), 'the event: %r' % ev)
    code, out = call('/api/notifier/keys', {'action': 'create', 'name': 'NoSMS'}, session=S)
    KEY3, KID3 = out['key'], out['id']
    got = d.notifier_wait(d.notifier_key_by_id(KID3), seq, d.notifier_boot, timeout=0.2)
    check(not [e for e in got.get('events') or [] if e['kind'] == 'sms'], 'a key without read heard it: %r' % got)
    got = d.notifier_wait(k2, seq, d.notifier_boot, timeout=0.2)
    check([e['kind'] for e in got.get('events') or []] == ['sms'], 'the other key with read: %r' % got)
    seq2 = d._ntf_seq
    d.sms_note('in', '+420603555123', 'old', True, 'was already here', key='old2', road='modem')
    check(d._ntf_seq == seq2, 'one found in the inbox went into the waits')
    code, out = call('/api/notifier/wait?after=%d&boot=%s' % (seq, d.notifier_boot), key=KEY)
    check(code == 200 and [e['kind'] for e in out.get('events') or []] == ['sms'], 'the wait over http: %s %r' % (code, out))

    print('the contacts, read-only')
    code, out = call('/api/notifier/contacts', key=KEY)
    check(code == 200 and [c['name'] for c in out.get('contacts') or []] == ['Jana Nováková', 'Petr Novák', 'Instalatér']
          and out.get('groups') == ['Family', 'Work'] and out['contacts'][1]['numbers'][1]['number'] == '+420602111333',
          'contacts: %s %r' % (code, out))
    code, out = call('/api/notifier/contacts', {'action': 'delete', 'id': 'c_5f2a9e'}, key=KEY)
    check(code in (400, 405), 'the contacts are not read-only: %s %r' % (code, out))

    print('sending')
    LOG.clear()
    code, out = call('/api/notifier/sms/send', {'to': ['contact:c_5f2a9e', '+420 777 123 456', 'group:Family'],
                                                'text': TEXT}, key=KEY)
    check(code == 200 and out.get('ok') is True and out.get('sent') == ['+420777123456', '+420602111222']
          and out.get('failed') == [] and out.get('message') == '2 sent' and out.get('error') is None,
          'send: %s %r' % (code, out))
    check([s['number'] for s in SENT] == ['+420777123456', '+420602111222'] and all(s['message'] == TEXT for s in SENT),
          'what reached the gateway: %r' % SENT)
    ev = events()
    check(any("SMS sent from the desktop app 'OFFICE-PC' to 2 recipients" == e for e in ev), 'the event: %r' % ev[-4:])
    check(any(e == 'sent to …456 (desktop app)' for e in ev), 'sms_send’s own event (counted for the cap): %r' % ev[-4:])
    check(d.sms_sent_today() >= 2, 'the day’s count did not grow')
    log_ = d.sms_log(5)
    check(log_[0]['dir'] == 'out' and log_[0]['why'] == 'desktop app' and log_[0]['text'] == TEXT, 'the SMS tab: %r' % log_[0])
    SENT.clear()
    code, out = call('/api/notifier/sms/send', {'reply_to': msgs[0]['id'], 'text': 'Jo'}, key=KEY)
    check(code == 200 and out.get('sent') == ['+420777123456'] and [s['number'] for s in SENT] == ['+420777123456'],
          'reply_to: %s %r' % (code, out))
    for body, want, words in (({'to': ['+420777123456'], 'text': '   '}, 400, 'empty'),
                              ({'to': ['+420777123456'], 'text': 'x' * 1001}, 400, 'too long'),
                              ({'to': ['contact:c_0000ff'], 'text': 'x'}, 400, 'is not a contact, a group or a phone number'),
                              ({'to': ['group:Nobody'], 'text': 'x'}, 400, 'is not a contact, a group or a phone number'),
                              ({'to': ['ab'], 'text': 'x'}, 400, 'is not a contact, a group or a phone number'),
                              ({'to': [], 'text': 'x'}, 400, 'at least one recipient'),
                              ({'to': '+420777123456', 'text': 'x'}, 400, 'a list'),
                              ({'to': ['+4207771234%02d' % i for i in range(11)], 'text': 'x'}, 400, 'at most 10'),
                              ({'reply_to': 'nope', 'text': 'x'}, 400, 'no longer')):
        code, out = call('/api/notifier/sms/send', body, key=KEY)
        check(code == want and words in (out.get('error') or '') and out.get('sent') == [] and out.get('failed') == [],
              '%s: %s %r' % (words, code, out))
    code, out = call('/api/notifier/sms/send', {'to': ['+420777123456', 'contact:c_0000ff', 'group:Nobody'], 'text': 'x'},
                     key=KEY)
    check(code == 400 and out.get('bad_to') == ['contact:c_0000ff', 'group:Nobody'] and SENT == [] or code == 400
          and out.get('bad_to') == ['contact:c_0000ff', 'group:Nobody'], 'bad_to of a send: %s %r' % (code, out))
    SENT.clear()
    code, out = call('/api/notifier/sms/send', {'to': ['+4207771234%02d' % i for i in range(7)], 'text': 'x'}, key=KEY)
    check(code == 200 and len(out.get('sent') or []) == 7, '7 more in the minute: %s %r' % (code, out))
    code, out = call('/api/notifier/sms/send', {'to': ['+420777123499'], 'text': 'x'}, key=KEY)
    check(code == 429 and 'at most 10 messages a minute' in out.get('error', '') and len(SENT) == 7,
          'the rate: %s %r' % (code, out))
    d._ntf_sms_rates.clear()
    zigmon.CONFIG['sms_host'] = ''
    code, out = call('/api/notifier/sms/send', {'to': ['+420777123456'], 'text': 'x'}, key=KEY)
    check(code == 409 and 'No SMS gateway' in out.get('error', ''), 'no gateway: %s %r' % (code, out))
    code, out = call('/api/notifier/hello', key=KEY)
    check(out['sms']['ready'] is False, 'hello.sms.ready with no gateway')
    zigmon.CONFIG['sms_host'] = '192.0.2.1'
    code, out = call('/api/notifier/sms/send', key=KEY)
    check(code == 405, 'sms/send by GET: %s %r' % (code, out))
    code, out = call('/api/notifier/hello', {}, key=KEY)
    check(code == 405, 'hello by POST: %s %r' % (code, out))
    code, out = call('/api/notifier/sms/send', {'to': ['+420777123456'], 'text': 'x'}, key='zmn_' + 'x' * 40)
    check(code == 401, 'a wrong key sends: %s %r' % (code, out))
    code, out = call('/api/notifier/sms/send', {'to': ['+420777123456'], 'text': 'x'})
    check(code == 401, 'no key sends: %s %r' % (code, out))
    whole = '\n'.join(LOG)
    for s_ in SECRETS:
        check(s_ not in whole, 'the log holds %r' % s_)
    for e in events():
        if 'desktop app' in e:
            for s_ in SECRETS:
                check(s_ not in e, 'an event of the desktop app holds %r: %r' % (s_, e))

    print('the Stream Deck: the cap "sms" and the items')
    INSTALL = 'a1b2c3d4e5f60718293a4b5c6d7e8f90'
    XL = {'id': 'C0FFEE00XL09', 'type': 2, 'name': 'Stream Deck XL', 'cols': 8, 'rows': 4, 'approved': True}
    TOKEN = 'zsd_' + 'R' * 40
    check('sms' in zigmon.Daemon.DECK_CAPS and zigmon.Daemon.deck_default_caps()['sms'] ==
          {'on': False, 'all': False, 'targets': [], 'hold': False}, 'the default sms cap: %r'
          % zigmon.Daemon.deck_default_caps().get('sms'))
    old_caps = zigmon.Daemon.deck_default_caps()
    old_caps.pop('sms')                                       # as an installation approved before 5.59.4 holds them
    old_caps['view'] = {'on': True, 'all': True, 'targets': []}
    INST = {'id': INSTALL, 'name': 'Office deck', 'computer': 'office-pc', 'decks': [XL], 'caps': old_caps,
            'hash': hashlib.sha256(TOKEN.encode()).hexdigest(), 'hint': TOKEN[-2:]}
    d.store.set_meta('deck_installs', json.dumps([INST]))

    def inst():
        return next(r for r in d.deck_installs() if r['id'] == INSTALL)

    def do(body):
        d._deck_setup()
        d._deck_rates.clear()
        d._deck_items_kept = None
        return d.deck_do(inst(), dict(body, deck=XL['id']))

    cat = {it['id']: it for it in d.deck_catalog(inst(), True)['items']}
    check('sms:last' not in cat and 'sms:compose' not in cat, 'the sms items without the cap (view: every): %r'
          % [i for i in cat if i.startswith('sms:')])
    code, out = do({'id': 'sms:compose', 'action': 'run'})
    check(code == 404, 'compose without the cap: %s %r' % (code, out))
    whole_cat = d.deck_catalog(inst(), True)
    check('sms_contacts' not in whole_cat and 'sms_groups' not in whole_cat, 'the contacts without the cap')
    check('sms' not in d.deck_hello(inst())['features'], 'hello features without the cap')
    check('sms' not in d.deck_caps_words(old_caps), 'the words: %r' % d.deck_caps_words(old_caps))
    rows_ = d.deck_installs()
    rows_[0]['caps'] = d._deck_clean_caps({'sms': {'on': True, 'all': False, 'targets': ['sms:compose']}}, old_caps)
    d._deck_put(rows_)
    check(inst()['caps']['sms'] == {'on': True, 'all': False, 'targets': ['sms:compose'], 'hold': False}
          and inst()['caps']['view']['on'] is True, 'the caps: %r' % inst()['caps'])
    try:
        d._deck_clean_caps({'switch': {'on': True, 'all': False, 'targets': ['sms:last']}})
        check(False, 'sms:last granted under switch')
    except ValueError:
        pass
    d._deck_items_kept = None
    cat = {it['id']: it for it in d.deck_catalog(inst(), True)['items']}
    old_cat = {it['id']: it for it in d.deck_catalog(inst(), False)['items']}
    check('sms:compose' in cat and 'sms:last' not in cat and 'sms:compose' not in old_cat,
          'only the one granted, and only to a plugin that asks: %r' % [i for i in cat if i.startswith('sms')])
    whole_cat = d.deck_catalog(inst(), True)
    check(whole_cat.get('sms_contacts') == [{'id': 'c_5f2a9e', 'name': 'Jana Nováková', 'group': 'Family', 'favourite': True},
                                            {'id': 'c_0b1c2d', 'name': 'Petr Novák', 'group': 'Family', 'favourite': False},
                                            {'id': 'c_77aa88', 'name': 'Instalatér', 'group': 'Work', 'favourite': False}]
          and whole_cat.get('sms_groups') == ['Family', 'Work'], 'sms_contacts: %r' % [whole_cat.get('sms_contacts'),
                                                                                       whole_cat.get('sms_groups')])
    check('602111' not in json.dumps(whole_cat) and '777123' not in json.dumps(whole_cat), 'a number in the catalogue')
    check('sms_contacts' not in d.deck_catalog(inst(), False), 'the contacts to an older plugin')
    check(d.deck_hello(inst())['features'] == ['extended', 'timer', 'summaries-5.59.4', 'sms'], 'hello features: %r'
          % d.deck_hello(inst())['features'])
    one = cat['sms:compose']
    st = one['state']
    check(one['kind'] == 'sms' and one['cap'] == 'sms' and one['actions'] == ['run'] and one['allowed'] is True
          and st['on'] is None and st['value'] == 3 and st['value_text'] == '3 today'
          and st['attrs']['last_from'] == '…123' and isinstance(st['attrs']['last_at'], int)
          and st['attrs']['unread'] == 1, 'the item (the last one masked, one since the app read them): %r' % one)
    call('/api/notifier/sms', key=KEY)                     # the app reads them: unread back to 0
    d._deck_items_kept = None
    st = {it['id']: it for it in d.deck_catalog(inst(), True)['items']}['sms:compose']['state']
    check(st['attrs']['unread'] == 0, 'unread after the app read them: %r' % st['attrs'])
    d.sms_note('in', '+420777123456', 'Jsem doma', True, 'received', key='k9', road='push')
    d._deck_items_kept = None
    cat = {it['id']: it for it in d.deck_catalog(inst(), True)['items']}
    st = cat['sms:compose']['state']
    check(st['attrs']['last_from'] == 'Jana Nováková' and st['attrs']['unread'] == 1 and st['value'] == 4,
          'the contact\u2019s name: %r' % st)
    blob = json.dumps(cat['sms:compose'])
    for s_ in ('603555', '777123', '+420', 'Jsem doma'):
        check(s_ not in blob, 'the item holds %r' % s_)

    print('the ask: linked by the computer’s name, handed to the waits')
    view = {r['id']: r for r in d.deck_installs_view()}[INSTALL]
    check(view['apps'] is None and view['apps_linked'] == [KID], 'automatic link (ignoring case): %r' % view)
    d._ntf_seen.pop(KID, None)
    code, out = do({'id': 'sms:compose', 'action': 'run'})
    check(code == 409 and out.get('error') == 'no desktop app linked to this Stream Deck is running'
          and out.get('no_app') is True, 'not running: %s %r'
          % (code, out))
    d.notifier_seen(d.notifier_key_by_id(KID), '192.168.40.10')
    seq = d._ntf_seq
    code, out = do({'id': 'sms:compose', 'action': 'run', 'to': ['contact:c_0b1c2d', 'group:Work', '+420 603 555 123']})
    check(code == 200 and out.get('ok') is True and "asked the desktop app 'OFFICE-PC' to write an SMS" in out.get('said', ''),
          'compose: %s %r' % (code, out))
    got = d.notifier_wait(d.notifier_key_by_id(KID), seq, d.notifier_boot, timeout=0.2)
    ev = got.get('events') or []
    check(len(ev) == 1 and ev[0]['kind'] == 'deck' and ev[0]['device'] == 'deck' and ev[0]['key'] == 'sms'
          and ev[0]['what'] == 'compose' and ev[0]['active'] is True and ev[0]['deck']['install'] == INSTALL
          and ev[0]['deck']['computer'] == 'office-pc'
          and ev[0]['deck']['to'] == [{'id': 'c_0b1c2d', 'name': 'Petr Novák', 'number': '+420602111222'},
                                      {'id': 'c_77aa88', 'name': 'Instalatér', 'number': '+420731000999'},
                                      {'id': None, 'name': None, 'number': '+420603555123'}],
          'the deck event: %r' % ev)
    got = d.notifier_wait(d.notifier_key_by_id(KID2), seq, d.notifier_boot, timeout=0.2)
    check(not got.get('events'), 'an app not linked heard the deck: %r' % got)
    check(any(e.startswith("Stream Deck 'Office deck' (XL) asked the desktop app 'OFFICE-PC' to write an SMS") for e in events()),
          'the deck event in the events')
    code, out = do({'id': 'sms:last', 'action': 'run'})
    check(code == 404, 'sms:last not granted: %s %r' % (code, out))
    rows_ = d.deck_installs()
    rows_[0]['caps']['sms'] = {'on': True, 'all': True, 'targets': [], 'hold': True}
    d._deck_put(rows_)
    code, out = do({'id': 'sms:last', 'action': 'run'})
    check(code == 409 and out.get('hold') is True, 'the hold: %s %r' % (code, out))
    seq = d._ntf_seq
    code, out = do({'id': 'sms:last', 'action': 'run', 'held_ms': 1600})
    check(code == 200, 'last: %s %r' % (code, out))
    got = d.notifier_wait(d.notifier_key_by_id(KID), seq, d.notifier_boot, timeout=0.2)
    check([(e['kind'], e['what'], e['deck']['to']) for e in got.get('events') or []] == [('deck', 'last', [])],
          'last in the wait: %r' % got)
    for to in (['x'] * 21, 'contact:c_5f2a9e', ['contact:c_0000ff']):
        code, out = do({'id': 'sms:compose', 'action': 'run', 'to': to, 'held_ms': 1600})
        check(code == 400, 'a bad to %r: %s %r' % (str(to)[:30], code, out))
    code, out = do({'id': 'sms:compose', 'action': 'run', 'to': ['contact:c_0000ff', '+420602111222', 'group:Nobody', 'zz'],
                    'held_ms': 1600})
    check(code == 400 and out.get('bad_to') == ['contact:c_0000ff', 'group:Nobody', 'zz'], 'bad_to: %s %r' % (code, out))
    d.store.set_meta('notifier_keys', json.dumps([dict(k, sms={'read': True, 'send': False}) if k['id'] == KID else k
                                                   for k in d.notifier_keys()]))
    code, out = do({'id': 'sms:compose', 'action': 'run', 'held_ms': 1600})
    check(code == 409 and out.get('error') == 'the desktop app linked to this Stream Deck may not send SMS'
          and out.get('not_allowed') is True and 'no_app' not in out,
          'linked but not allowed to send: %s %r' % (code, out))
    d.store.set_meta('notifier_keys', json.dumps([dict(k, sms={'read': True, 'send': True, 'contacts': True})
                                                   if k['id'] == KID else k for k in d.notifier_keys()]))

    print('acknowledge with no alert standing says "nothing"')
    d.store.set_meta('active_alerts', '[]')
    rows_ = d.deck_installs()
    keep = dict(rows_[0]['caps']['system'])
    rows_[0]['caps']['system'] = {'on': True, 'all': True, 'targets': [], 'hold': True}
    d._deck_put(rows_)
    code, out = do({'id': 'status:security', 'action': 'ack', 'held_ms': 1600})
    check(code == 409 and out.get('nothing') is True, 'ack with nothing: %s %r' % (code, out))
    rows_ = d.deck_installs()
    rows_[0]['caps']['system'] = keep
    d._deck_put(rows_)

    print('the links set by hand')
    check('/api/deck/admin' in zigmon.ApiHandler.ALWAYS_LOCKED and '/api/notifier/keys' in zigmon.ApiHandler.ALWAYS_LOCKED,
          'the admin roads are not locked')
    code, out = call('/api/deck/admin', {'action': 'apps', 'install': INSTALL, 'apps': [KID2]}, session=SO)
    check(code == 403, 'an operator set the links: %s %r' % (code, out))
    code, out = call('/api/deck/admin', {'action': 'apps', 'install': INSTALL, 'apps': ['nope']}, session=S)
    check(code == 400, 'an unknown key: %s %r' % (code, out))
    code, out = call('/api/deck/admin', {'action': 'apps', 'install': INSTALL, 'apps': [KID2]}, session=S)
    iv = {r['id']: r for r in out.get('installs') or []}.get(INSTALL) or {}
    check(code == 200 and iv.get('apps') == [KID2] and iv.get('apps_linked') == [KID2]
          and {a['id'] for a in out.get('apps') or []} == {KID, KID2, KID3}, 'apps: %s %r' % (code, iv))
    check(any("owner set the desktop apps the Stream Deck installation 'Office deck' may ask ('Laptop')" in e for e in events()),
          'the link in the events')
    d.notifier_seen(d.notifier_key_by_id(KID2), '192.168.40.11')
    seq = d._ntf_seq
    code, out = do({'id': 'sms:last', 'action': 'run', 'held_ms': 1600})
    check(code == 200, 'last to Laptop: %s %r' % (code, out))
    check(not d.notifier_wait(d.notifier_key_by_id(KID), seq, d.notifier_boot, timeout=0.2).get('events'),
          'the unlinked OFFICE-PC heard it')
    check(len(d.notifier_wait(d.notifier_key_by_id(KID2), seq, d.notifier_boot, timeout=0.2).get('events') or []) == 1,
          'Laptop did not hear it')
    code, out = call('/api/deck/admin', {'action': 'apps', 'install': INSTALL, 'apps': []}, session=S)
    code, out = do({'id': 'sms:last', 'action': 'run', 'held_ms': 1600})
    check(code == 409 and out.get('error') == 'no desktop app linked to this Stream Deck is running'
          and out.get('no_app') is True, 'linked to none: %s %r'
          % (code, out))
    code, out = call('/api/deck/admin', {'action': 'apps', 'install': INSTALL, 'apps': None}, session=S)
    check('apps' not in inst() and d.deck_linked_apps(inst())[0]['id'] == KID, 'back to automatic: %r' % inst())
    print('the links set from the key’s side')
    code, out = call('/api/notifier/keys', session=S)
    rows = {k['id']: k for k in out['keys']}
    check(rows[KID]['decks'] == [{'id': INSTALL, 'auto': True}] and rows[KID2]['decks'] == []
          and out['deck_installs'] == [{'id': INSTALL, 'name': 'Office deck', 'computer': 'office-pc', 'sms': True,
                                        'auto': True}], 'the key view: %r' % [rows[KID].get('decks'), out.get('deck_installs')])
    code, out = call('/api/notifier/keys', {'action': 'update', 'id': KID2, 'decks': [INSTALL]}, session=S)
    check(code == 200 and inst().get('apps') == [KID, KID2], 'linked from the key: %s %r' % (code, inst().get('apps')))
    code, out = call('/api/notifier/keys', {'action': 'update', 'id': KID, 'decks': []}, session=S)
    check(code == 200 and inst().get('apps') == [KID2], 'unlinked from the key: %s %r' % (code, inst().get('apps')))
    code, out = call('/api/notifier/keys', {'action': 'update', 'id': KID, 'decks': ['nope']}, session=S)
    check(code == 400, 'an unknown installation: %s %r' % (code, out))
    code, out = call('/api/notifier/keys', {'action': 'update', 'id': KID, 'decks': [INSTALL]}, session=SO)
    check(code == 403, 'an operator linked: %s %r' % (code, out))

    print('the deck over http')
    code, out = call('/api/deck/do', {'deck': XL['id'], 'id': 'sms:last', 'action': 'run', 'held_ms': 1600},
                     deck=(TOKEN, INSTALL))
    check(code == 200 and out.get('ok') is True, 'do over http: %s %r' % (code, out))
    code, out = call('/api/deck/catalog?extended=1', deck=(TOKEN, INSTALL))
    check(code == 200 and {'sms:last', 'sms:compose'} <= {i['id'] for i in out.get('items') or []}, 'the catalogue over http')

    print('an app with nothing granted is as it was')
    d.store.upsert_device({'id': '0x00158d0001a2b3c4', 'name': 'PIR', 'source': 'zigbee', 'kind': 'EndDevice',
                           'exposes': {'occupancy': {}}})
    d.names['PIR'] = '0x00158d0001a2b3c4'
    seq = d._ntf_seq
    d.handle_zigbee('PIR', json.dumps({'occupancy': True}).encode())
    got = d.notifier_wait(d.notifier_key_by_id(KID3), seq, d.notifier_boot, timeout=0.5)
    check([(e['kind'], e['what']) for e in got.get('events') or []] == [('motion', 'motion')]
          and 'sms' not in got['events'][0] and 'deck' not in got['events'][0], 'a sensor’s edge: %r' % got)

    print('the relay')
    page = (HERE / 'web' / 'index.php').read_text()
    shutil.copytree(HERE / 'web', W / 'web')
    api_php = (W / 'web' / 'zigmon-api.php').read_text()
    api_php = api_php.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
    api_php = api_php.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
    (W / 'web' / 'zigmon-api.php').write_text(api_php)
    php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, str(W / 'web' / 'index.php')], cwd=str(W / 'web'),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                           env=dict(os.environ, PHP_CLI_SERVER_WORKERS='4'))
    PROCS.append(php)
    for _ in range(50):
        try:
            socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)

    def relay(query, key=None, body=None, method=None, headers=None):
        h = {'User-Agent': 'ZigmonNotifier/1.4.0 (Windows)', 'Content-Type': 'application/json'}
        h.update(headers or {})
        if key is not None:
            h['X-Zigmon-Notifier'] = key
        req = urllib.request.Request('http://127.0.0.1:%d/index.php?%s' % (PHP_PORT, query), headers=h,
                                     data=None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode()),
                                     method=method or ('GET' if body is None else 'POST'))
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')

    d._ntf_sms_rates.clear()
    code, out = relay('api=notifier&do=sms&limit=2', key=KEY)
    check(code == 200 and len(out.get('messages') or []) == 2, 'sms through the relay: %s %r' % (code, out))
    code, out = relay('api=notifier&do=contacts', key=KEY)
    check(code == 200 and len(out.get('contacts') or []) == 3, 'contacts through the relay: %s %r' % (code, out))
    SENT.clear()
    code, out = relay('api=notifier&do=sms-send', key=KEY, body={'to': ['contact:c_77aa88'], 'text': 'Prosim zavolejte'})
    check(code == 200 and out.get('sent') == ['+420731000999'] and SENT and SENT[0]['number'] == '+420731000999',
          'sms-send through the relay: %s %r' % (code, out))
    code, out = relay('api=notifier&do=sms-send', key=KEY)
    check(code == 405, 'sms-send by GET: %s %r' % (code, out))
    code, out = relay('api=notifier&do=hello', key=KEY, body={})
    check(code == 405, 'hello by POST through the relay: %s %r' % (code, out))
    code, out = relay('api=notifier&do=sms-send', key=KEY, body=b'not json')
    check(code == 400 and out.get('error'), 'a body that is not JSON: %s %r' % (code, out))
    code, out = relay('api=notifier&do=sms-send', key=KEY3, body={'to': ['+420731000999'], 'text': 'x'})
    check(code == 403 and 'may not send' in out.get('error', ''), 'a key without send through the relay: %s %r' % (code, out))
    code, out = relay('api=notifier&do=sms/send', key=KEY, body={'to': ['+420731000999'], 'text': 'x'})
    check(code in (400, 405), 'a do that is not one of them: %s %r' % (code, out))
    for q, body in (('api=notifier&do=sms', None), ('api=notifier&do=contacts', None),
                    ('api=notifier&do=sms-send', {'to': ['+420731000999'], 'text': 'x'})):
        for hdr in ({'X-Forwarded-For': '203.0.113.9'}, {'X-Real-IP': '198.51.100.7'},
                    {'Forwarded': 'for=192.168.1.5, for="[2001:db8::1]"'}):
            n = len(SENT)
            code, out = relay(q, key=KEY, body=body, headers=hdr)
            check(code == 403 and 'home network' in out.get('error', '') and len(SENT) == n,
                  'the home network lock, %s %r: %s %r' % (q, hdr, code, out))
    print('the pages (Playwright)')
    SHOTS.mkdir(parents=True, exist_ok=True)
    # a house worth drawing: two more keys, a second installation linked by hand, conditions on one key
    rows_ = d.deck_installs()
    rows_[0]['apps'] = None
    rows_[0].pop('apps', None)
    rows_[0]['caps']['sms'] = {'on': True, 'all': True, 'targets': [], 'hold': False}
    rows_[0]['caps']['system'] = {'on': True, 'all': False, 'targets': ['status:sms'], 'hold': True}
    rows_.append({'id': 'b' * 32, 'name': 'Kitchen deck', 'computer': 'KITCHEN', 'decks': [dict(XL, id='C0FFEE00XL10')],
                  'caps': zigmon.Daemon.deck_default_caps(), 'apps': [KID2], 'hint': 'zz',
                  'hash': hashlib.sha256(b'zsd_other').hexdigest(), 'approved_by': 'owner', 'approved_at': time.time()})
    d._deck_put(rows_)
    d.store.set_meta('notifier_keys', json.dumps([dict(k, sms={'read': True, 'send': True, 'contacts': True})
                                                   if k['id'] == KID else k for k in d.notifier_keys()]))
    d._deck_items_kept = None
    js = r'''
const { chromium } = require('playwright');
const job = %(job)s;
(async () => {
  const b = await chromium.launch();
  const r = {errors: []};
  for (const shot of [{n: 'desktop', w: 1400, h: 1100}, {n: 'phone', w: 390, h: 1500}]) {
    const ctx = await b.newContext({viewport: {width: shot.w, height: shot.h}, colorScheme: 'dark'});
    await ctx.addCookies([{name: 'zigmon_session', value: job.s, url: 'http://127.0.0.1:' + job.port + '/'}]);
    const p = await ctx.newPage();
    p.on('pageerror', e => r.errors.push(String(e)));
    p.setDefaultTimeout(10000);
    const x = r[shot.n] = {};
    // ---- Desktop app: the rows, their switches, the key's dialog
    console.error('step 1 ' + shot.n);
    await p.goto('http://127.0.0.1:' + job.port + '/#control/msg-desktop');
    await p.waitForTimeout(1500);
    try { await p.evaluate(() => showControlSection('msg-desktop')); } catch (e) {}
    console.error('step 2 ' + shot.n);
    await p.waitForSelector('#ntf-host .ntf-key .ntf-smsrow', {timeout: 15000});
    await p.waitForTimeout(400);
    console.error('step 3 ' + shot.n);
    x.rows = await p.evaluate(() => Array.from(document.querySelectorAll('#ntf-host .ntf-key')).map(k => ({
      id: k.dataset.id, sms: k.querySelector('.ntf-smsrow').textContent,
      on: Array.from(k.querySelectorAll('.ntf-smsrow input[data-sms]')).filter(i => i.checked).map(i => i.dataset.sms)})));
    const row = '#ntf-host .ntf-key[data-id="' + job.kid3 + '"]';
    console.error('step 4 ' + shot.n);
    await (await p.$('#ntf-list')).screenshot({path: job.dir + '/desktop-keys-' + shot.n + '.png'});
    if (shot.n === 'desktop') {
      console.error('step 5 ' + shot.n);
      await p.evaluate((sel) => document.querySelector(sel).click(), row + ' .ntf-smsrow input[data-sms="read"]');
      await p.waitForTimeout(900);
      console.error('step 6 ' + shot.n);
      x.afterSwitch = await p.evaluate((row) => Array.from(document.querySelectorAll(row + ' .ntf-smsrow input[data-sms]'))
        .filter(i => i.checked).map(i => i.dataset.sms), row);
    }
    console.error('step 7 ' + shot.n);
    await p.click('#ntf-host .ntf-key[data-id="' + job.kid + '"] .ntf-edit');
    console.error('step 8 ' + shot.n);
    await p.waitForSelector('#zmodal:not([hidden]) .ntf-caps', {timeout: 5000});
    await p.waitForTimeout(300);
    console.error('step 9 ' + shot.n);
    x.dlg = await p.evaluate(() => ({
      title: (document.querySelector('#zmodal-title') || document.querySelector('#zmodal h2') || {}).textContent || '',
      cards: Array.from(document.querySelectorAll('#zmodal .dk-cap')).map(c => c.dataset.cap),
      on: Array.from(document.querySelectorAll('#zmodal .dk-cap.on')).map(c => c.dataset.cap),
      presets: Array.from(document.querySelectorAll('#zmodal .dk-preset')).map(c => c.textContent),
      chosen: (document.querySelector('#zmodal .dk-preset.on') || {dataset: {}}).dataset.p || '',
      summary: document.querySelector('#ntf-summary').textContent,
      decks: Array.from(document.querySelectorAll('#zmodal .ntf-deckopts .dk-opt')).map(o => [o.dataset.id, o.querySelector('input').checked, o.textContent]),
      wide: document.documentElement.scrollWidth, view: window.innerWidth}));
    console.error('step 10 ' + shot.n);
    await p.screenshot({path: job.dir + '/desktop-dialog-' + shot.n + '.png', fullPage: shot.n === 'phone'});
    const box = await p.$('#zmodal .zmodal-box') || await p.$('#zmodal > div');
    if (box) await box.screenshot({path: job.dir + '/desktop-dialog-box-' + shot.n + '.png'});
    console.error('step 11 ' + shot.n);
    await p.click('#zmodal .dk-preset[data-p="read"]');
    console.error('step 12 ' + shot.n);
    x.dlg.read = await p.evaluate(() => ({on: Array.from(document.querySelectorAll('#zmodal .dk-cap.on')).map(c => c.dataset.cap),
      summary: document.querySelector('#ntf-summary').textContent,
      chosen: (document.querySelector('#zmodal .dk-preset.on') || {dataset: {}}).dataset.p || ''}));
    console.error('step 13 ' + shot.n);
    await p.click('#zmodal-foot button:has-text("Cancel")');
    await p.waitForTimeout(300);
    // the new key: a name that is a deck's computer links it by itself
    console.error('step 14 ' + shot.n);
    await p.click('#ntf-new');
    console.error('step 15 ' + shot.n);
    await p.waitForSelector('#zmodal:not([hidden]) #ntf-name', {timeout: 5000});
    console.error('step 16 ' + shot.n);
    await p.fill('#ntf-name', shot.n === 'desktop' ? 'KITCHEN' : 'Phone PC');
    console.error('step 17 ' + shot.n);
    x.newdlg = await p.evaluate(() => ({on: Array.from(document.querySelectorAll('#zmodal .dk-cap.on')).map(c => c.dataset.cap),
      summary: document.querySelector('#ntf-summary').textContent}));
    console.error('step 18 ' + shot.n);
    await p.check('#zmodal input[name="ntf-mode"][value="some"]');
    console.error('step 19 ' + shot.n);
    await p.fill('#ntf-find', 'pir');
    console.error('step 20 ' + shot.n);
    await p.check('#ntf-opts .ntf-opt[data-id="' + job.pir + '"] input');
    console.error('step 21 ' + shot.n);
    await p.evaluate(() => document.querySelector('#zmodal .dk-cap[data-cap="sms-read"] .dk-cap-sw input').click());
    console.error('step 22 ' + shot.n);
    await p.screenshot({path: job.dir + '/desktop-newkey-' + shot.n + '.png', fullPage: shot.n === 'phone'});
    console.error('step 23 ' + shot.n);
    await p.click('#zmodal-foot button:has-text("Make the key")');
    console.error('step 24 ' + shot.n);
    await p.waitForSelector('#zmodal:not([hidden]) #ntf-secret', {timeout: 8000});
    console.error('step 25 ' + shot.n);
    x.newkey = await p.evaluate(() => document.querySelector('#ntf-secret').textContent);
    console.error('step 26 ' + shot.n);
    await p.click('#zmodal-foot button:has-text("I have copied it")');
    await p.waitForTimeout(500);
    // ---- Stream Deck: the installation's desktop apps, the dialog's SMS card and the new items
    console.error('step 27 ' + shot.n);
    await p.goto('http://127.0.0.1:' + job.port + '/#control/msg-deck');
    await p.waitForTimeout(1500);
    try { await p.evaluate(() => showControlSection('msg-deck')); } catch (e) {}
    console.error('step 28 ' + shot.n);
    await p.waitForSelector('#dk-host .dk-inst .dk-apps', {timeout: 15000});
    await p.waitForTimeout(400);
    console.error('step 29 ' + shot.n);
    x.apps = await p.evaluate(() => Array.from(document.querySelectorAll('#dk-installs .dk-inst')).map(c => ({
      id: c.dataset.id, text: c.querySelector('.dk-apps').textContent,
      ticked: Array.from(c.querySelectorAll('.dk-apps .dk-app')).filter(a => a.querySelector('input').checked).map(a => a.dataset.id)})));
    const inst = '#dk-installs .dk-inst[data-id="' + job.install + '"]';
    console.error('step 30 ' + shot.n);
    await (await p.$(inst)).screenshot({path: job.dir + '/deck-install-' + shot.n + '.png'});
    console.error('step 31 ' + shot.n);
    await p.click(inst + ' .dk-perms');
    console.error('step 32 ' + shot.n);
    await p.waitForSelector('#zmodal:not([hidden]) .dk-caps', {timeout: 5000});
    await p.waitForTimeout(300);
    console.error('step 33 ' + shot.n);
    x.deck = await p.evaluate(() => ({
      cards: Array.from(document.querySelectorAll('#zmodal .dk-cap')).map(c => c.dataset.cap),
      on: Array.from(document.querySelectorAll('#zmodal .dk-cap.on')).map(c => c.dataset.cap),
      summary: document.querySelector('#dk-summary').textContent,
      sms: (document.querySelector('#zmodal .dk-cap[data-cap="sms"]') || {}).textContent || '',
      system: Array.from(document.querySelectorAll('#zmodal .dk-cap[data-cap="system"] .dk-opt')).map(o => o.dataset.id),
      view: Array.from(document.querySelectorAll('#zmodal .dk-cap[data-cap="view"] .dk-opt')).map(o => o.dataset.id),
      smsopts: Array.from(document.querySelectorAll('#zmodal .dk-cap[data-cap="sms"] .dk-opt')).map(o => o.dataset.id),
      wide: document.documentElement.scrollWidth, view_w: window.innerWidth}));
    console.error('step 34 ' + shot.n);
    await p.screenshot({path: job.dir + '/deck-dialog-' + shot.n + '.png', fullPage: shot.n === 'phone'});
    console.error('step 35 ' + shot.n);
    await (await p.$('#zmodal .dk-cap[data-cap="sms"]')).scrollIntoViewIfNeeded();
    console.error('step 36 ' + shot.n);
    await p.click('#zmodal .dk-cap[data-cap="system"] input[value="some"]').catch(() => {});
    await p.waitForTimeout(200);
    console.error('step 37 ' + shot.n);
    await (await p.$('#zmodal .dk-cap[data-cap="sms"]')).screenshot({path: job.dir + '/deck-sms-card-' + shot.n + '.png'});
    console.error('step 38 ' + shot.n);
    await (await p.$('#zmodal .dk-cap[data-cap="system"]')).screenshot({path: job.dir + '/deck-system-card-' + shot.n + '.png'});
    console.error('step 39 ' + shot.n);
    await p.click('#zmodal-foot button:has-text("Cancel")');
    await p.waitForTimeout(300);
    if (shot.n === 'desktop') {
      // tick the Laptop by hand: the automatic link becomes a list of its own
      console.error('step 40 ' + shot.n);
      await p.click(inst + ' .dk-apps .dk-app[data-id="' + job.kid2 + '"] input');
      await p.waitForTimeout(900);
      console.error('step 41 ' + shot.n);
      x.afterTick = await p.evaluate((inst) => ({ticked: Array.from(document.querySelectorAll(inst + ' .dk-apps .dk-app'))
        .filter(a => a.querySelector('input').checked).map(a => a.dataset.id),
        back: !!document.querySelector(inst + ' .dk-apps-auto')}), inst);
      console.error('step 42 ' + shot.n);
      await (await p.$(inst)).screenshot({path: job.dir + '/deck-install-byhand.png'});
    }
    await ctx.close();
  }
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e && e.stack || e)})); });
'''
    npm_root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()
    (W / 'page.js').write_text(js % {'job': json.dumps({'s': S, 'port': PHP_PORT, 'dir': str(SHOTS), 'kid': KID, 'kid2': KID2,
                                                        'kid3': KID3, 'install': INSTALL, 'pir': '0x00158d0001a2b3c4'})})
    try:
        got = subprocess.run(['node', str(W / 'page.js')], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=400,
                             env=dict(os.environ, NODE_PATH=npm_root))
    except subprocess.TimeoutExpired as e:
        err = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr or '')
        got = subprocess.CompletedProcess([], 1, '', 'timed out after: %s' % err.strip().splitlines()[-1:])
    try:
        r = json.loads(got.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        r = {'error': (got.stdout + got.stderr)[-600:]}
    if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
        print('  SKIPPED (no browser here): %s' % r['error'][:200])
    else:
        check(not r.get('error'), 'the page: %r' % r.get('error'))
        check(not r.get('errors'), 'the page threw: %r' % r.get('errors'))
        for n in ('desktop', 'phone'):
            x = r.get(n) or {}
            rows = {k['id']: k for k in x.get('rows') or []}
            check(rows.get(KID, {}).get('on') == ['read', 'send', 'contacts'] and 'SMS: read' in rows[KID]['sms']
                  and ('asked by 1 Stream Deck (automatic)' if n == 'desktop' else 'asked by 1 Stream Deck') in rows[KID]['sms'], '%s: the row’s switches: %r' % (n, rows.get(KID)))
            dl = x.get('dlg') or {}
            check(dl.get('cards') == ['sensors', 'rules', 'sms-read', 'sms-send', 'sms-contacts', 'decks']
                  and len(dl.get('presets') or []) == 3 and dl.get('chosen') == 'all'
                  and set(dl.get('on') or []) >= {'sensors', 'sms-read', 'sms-send', 'sms-contacts', 'decks'}
                  and 'writes and answers SMS' in dl.get('summary', '') and 'What OFFICE-PC may do' in dl.get('title', ''),
                  '%s: the key’s dialog: %r' % (n, dl))
            check([dd[0] for dd in dl.get('decks') or [] if dd[1]] == [INSTALL]
                  and (n == 'phone' or any('(automatic: office-pc)' in dd[2] for dd in dl.get('decks') or [])), '%s: its decks: %r' % (n, dl.get('decks')))
            rd = dl.get('read') or {}
            check(rd.get('chosen') == 'read' and 'sms-send' not in (rd.get('on') or []) and 'decks' not in (rd.get('on') or [])
                  and 'shows each incoming SMS' in rd.get('summary', ''), '%s: the preset: %r' % (n, rd))
            check(x.get('newkey', '').startswith('zmn_'), '%s: the new key: %r' % (n, x.get('newkey')))
            ap = {a['id']: a for a in x.get('apps') or []}
            # the phone comes after the desktop ticked the Laptop by hand
            check(ap.get(INSTALL, {}).get('ticked') == ([KID] if n == 'desktop' else [KID, KID2])
                  and (n == 'phone' or '(automatic: office-pc)' in ap[INSTALL]['text'])
                  and 'Desktop apps on this deck’s computer' in ap[INSTALL]['text'], '%s: the deck’s apps: %r' % (n, ap.get(INSTALL)))
            dk = x.get('deck') or {}
            check('sms' in (dk.get('cards') or []) and 'sms' in (dk.get('on') or []) and 'OFFICE-PC' in dk.get('sms', '')
                  and 'reads & sends SMS' in dk.get('sms', '') and set(dk.get('smsopts') or []) == {'sms:last', 'sms:compose'}
                  and 'asks the desktop app for SMS' in dk.get('summary', ''), '%s: the deck’s dialog: %r' % (n, dk))
            check('status:sms' in (dk.get('system') or []) and not any(i.startswith('sms:') for i in dk.get('view') or []),
                  '%s: the Only these lists: %r' % (n, [dk.get('system'), dk.get('view')]))
            check(dl.get('wide', 9999) <= dl.get('view', 0) + 1 and dk.get('wide', 9999) <= dk.get('view_w', 0) + 1,
                  '%s: scrolls sideways' % n)
        dx = r.get('desktop') or {}
        check(dx.get('afterSwitch') == ['read'] and d.notifier_sms_flags(d.notifier_key_by_id(KID3))['read'] is True,
              'the row’s switch did not save: %r' % dx.get('afterSwitch'))
        made = [k for k in d.notifier_keys() if k['name'] == 'KITCHEN']
        check(made and d.notifier_sms_flags(made[0]) == {'read': True, 'send': False, 'contacts': False}
              and made[0]['devices'] == ['0x00158d0001a2b3c4'], 'the key made in the browser: %r' % made)
        check(dx.get('afterTick', {}).get('ticked') == [KID, KID2] and dx['afterTick'].get('back') is True
              and next(i for i in d.deck_installs() if i['id'] == INSTALL).get('apps') == [KID, KID2],
              'ticking the Laptop by hand: %r' % dx.get('afterTick'))
        print('  screenshots: %s' % SHOTS)
    for words in ("'sms', 'contacts', 'sms-send'", "'/api/notifier/sms/send'"):
        check(words in page, 'the page has no %s' % words)
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
    except Exception:                                       # noqa: BLE001
        pass

zigmon.log = _real_log
shutil.rmtree(W, ignore_errors=True)
if bad:
    print('%d FAILED' % len(bad))
    sys.exit(1)
print('all good')
