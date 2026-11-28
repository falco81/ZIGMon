#!/usr/bin/env python3
"""5.59.4: contacts kept in ZIGMon (windows/PROTOCOL-SMS.md, section 1).

  * the store (meta contacts): ids c_ + hex, names 1-80 and unique ignoring case, 1-5 numbers
    normalised as sms_number_for_gateway does (00 written as +), labels 20, groups 40, notes 200,
    favourites, at most 2000;
  * GET /api/contacts and POST /api/contacts (save, delete, import with a dry run) - an
    administrator's: signed out 403, an operator 403, both in ALWAYS_LOCKED;
  * import: vCard 2.1 (an Android export, quoted-printable Czech in UTF-8 and in windows-1250,
    soft line breaks, bare TYPE words), 3.0 (an iPhone export: item1.TEL with X-ABLabel, folded
    lines, a BASE64 photo; a Google export: CATEGORIES with myContacts and starred), 4.0
    (tel: URIs, quoted TYPE lists); CSV from Google (the old and the new headers, ::: in a
    cell), Outlook with ; between the cells and a BOM, Czech Outlook headers; merge and replace;
    hostile files: past 2 MB, past the row cap, junk, NULs, a card with no END, a card inside a
    card, a cell with no closing quote, thirty thousand folded lines of a photo;
  * export: vCard 3.0 (folded at 75 octets, escaped) and Google's CSV, both read back the same;
  * POST /api/sms/send takes contact:<id> and group:<name> in `to`, expanded with the same phone
    sent once; a plain number as before; contacts_expand and contact_by_number for the others;
  * /api/sms/log has the contact of each number; nothing of a contact goes into the log or the
    events ("contacts imported: 3 added");
  * the relay (php -S): api=contacts (GET, POST), api=contacts-export as a download;
  * the page (Playwright): SMS -> Contacts (cards with initials, search, group chips, favourites,
    the drawer, delete with a question, import with a preview), Write a message with recipient
    chips (autocomplete by keyboard, a contact's number picked, a typed number, a group, the
    quick row), the facts completer still there, the contact's name in the Messages.
    Screenshots into $ZIGMON_SHOTS or a temporary folder.

    python3 test/review5594_contacts.py < /dev/null

Ports 20336 (the daemon), 20337 (php -S). Every name and number here is made up.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-contacts-'))
API_PORT, PHP_PORT = 20336, 20337
SHOTS = Path(os.environ.get('ZIGMON_SHOTS') or tempfile.mkdtemp(prefix='zigmon-contacts-shots-'))
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


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


for _p in (API_PORT, PHP_PORT):
    if not port_free(_p):
        print('port %d stays busy' % _p)
        sys.exit(2)

# ---- the files, as the phones and the services write them (made-up people) ---------------------
ANDROID_21 = (
    'BEGIN:VCARD\r\n'
    'VERSION:2.1\r\n'
    'N;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:=C5=A0imon;Ji=C5=99=C3=AD;;;\r\n'
    'FN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:Ji=C5=99=C3=AD =C5=A0imon\r\n'
    'TEL;CELL;PREF:+420777000301\r\n'
    'TEL;WORK:+420 777 000 302\r\n'
    'NOTE;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:Soused odvedle, m=C3=A1 kl=C3=AD=C4=8De od gar=C3=A1=\r\n'
    '=C5=BEe\r\n'
    'END:VCARD\r\n'
    'BEGIN:VCARD\r\n'
    'VERSION:2.1\r\n'
    'N;CHARSET=windows-1250;ENCODING=QUOTED-PRINTABLE:=8Akoda;Old=F8ich;;;\r\n'
    'FN;CHARSET=windows-1250;QUOTED-PRINTABLE:Old=F8ich =8Akoda\r\n'
    'TEL;HOME;VOICE:00420777000311\r\n'
    'X-ANDROID-CUSTOM:vnd.android.cursor.item/nickname;Olda;1;;;;;;;;;;;;;\r\n'
    'END:VCARD\r\n'
    'BEGIN:VCARD\r\n'
    'VERSION:2.1\r\n'
    'FN:Bez Telefonu\r\n'
    'EMAIL;HOME:nikdo@example.invalid\r\n'
    'END:VCARD\r\n')
IPHONE_30 = (
    'BEGIN:VCARD\n'
    'VERSION:3.0\n'
    'PRODID:-//Apple Inc.//iPhone OS 17.1//EN\n'
    'N:Svobodová;Petra;;;\n'
    'FN:Petra Svobodová\n'
    'ORG:Pekárna U Lípy;\n'
    'item1.TEL;type=pref:+420 777 000 201\n'
    'item1.X-ABLabel:_$!<Mobile>!$_\n'
    'TEL;type=HOME;type=VOICE:777 000 202\n'
    'item2.TEL:+420777000203\n'
    'item2.X-ABLabel:Chata\n'
    'NOTE:Klíče od chaty\\nv kuchyni\\, vlevo\n'
    'PHOTO;ENCODING=b;TYPE=JPEG:' + 'A' * 60 + '\n' + ''.join(' ' + 'B' * 74 + '\n' for _ in range(40)) +
    'END:VCARD\n'
    'BEGIN:VCARD\n'
    'VERSION:3.0\n'
    'N:;;;;\n'
    'FN:\n'
    'ORG:Instalatér Novotný;\n'
    'TEL;type=WORK;type=VOICE;type=pref:+420 777 000 211\n'
    'END:VCARD\n')
GOOGLE_VCF = (
    'BEGIN:VCARD\r\n'
    'VERSION:3.0\r\n'
    'FN:Karel Dvořák\r\n'
    'N:Dvořák;Karel;;;\r\n'
    'TEL;TYPE=CELL:+420 777 000 401\r\n'
    'TEL;TYPE=WORK:+420 777 000 402\r\n'
    'CATEGORIES:myContacts,starred,Práce\r\n'
    'NOTE:Kolega z\r\n'
    '  kanceláře\r\n'
    'END:VCARD\r\n')
VCARD_40 = (
    'BEGIN:VCARD\r\n'
    'VERSION:4.0\r\n'
    'FN:Eva Malá\r\n'
    'TEL;VALUE=uri;TYPE="voice,cell":tel:+420-777-000-501\r\n'
    'TEL;VALUE=uri;TYPE=home:tel:+420-777-000-502;ext=12\r\n'
    'CATEGORIES:Kamarádi\r\n'
    'END:VCARD\r\n')
GOOGLE_CSV = (
    'Name,Given Name,Additional Name,Family Name,Yomi Name,Given Name Yomi,Additional Name Yomi,Family Name Yomi,'
    'Name Prefix,Name Suffix,Initials,Nickname,Short Name,Maiden Name,Birthday,Gender,Location,Billing Information,'
    'Directory Server,Mileage,Occupation,Hobby,Sensitivity,Priority,Subject,Notes,Language,Photo,Group Membership,'
    'E-mail 1 - Type,E-mail 1 - Value,Phone 1 - Type,Phone 1 - Value,Phone 2 - Type,Phone 2 - Value\r\n'
    'Jana Nováková,Jana,,Nováková,,,,,,,,,,,,,,,,,,,,,,"Teta, z Brna",,,'
    '* myContacts ::: Rodina ::: * starred,* Home,jana@example.invalid,Mobile,+420 777 000 101,Home,'
    '+420 777 000 102 ::: +420 777 000 103\r\n'
    'Marek Novák,Marek,,Novák,,,,,,,,,,,,,,,,,,,,,,,,,* myContacts ::: Rodina,,,Mobile,+420 777 000 104,,\r\n'
    ',,,,,,,,,,,,,,,,,,,,,,,,,,,,* myContacts,,,Mobile,+420 777 000 105,,\r\n')
GOOGLE_CSV_NEW = (
    'First Name,Middle Name,Last Name,Phonetic First Name,Phonetic Middle Name,Phonetic Last Name,Name Prefix,'
    'Name Suffix,Nickname,File As,Organization Name,Organization Title,Organization Department,Birthday,Notes,Photo,'
    'Labels,E-mail 1 - Label,E-mail 1 - Value,Phone 1 - Label,Phone 1 - Value\n'
    'Lucie,,Krásná,,,,,,,,,,,,,,* myContacts ::: Sousedi,,,Mobile,+420 777 000 121\n')
OUTLOOK_CSV = (
    '\ufeff"First Name";"Middle Name";"Last Name";"Title";"Suffix";"Nickname";"E-mail Address";"Home Phone";'
    '"Home Phone 2";"Business Phone";"Business Phone 2";"Mobile Phone";"Car Phone";"Other Phone";"Primary Phone";'
    '"Business Fax";"Company";"Categories";"Notes"\r\n'
    '"Tomáš";"";"Malý";"";"";"";"tomas@example.invalid";"777000602";"";"+420 777 000 603";"";'
    '"+420 777 000 601";"";"";"";"+420 777 000 699";"";"Práce;Sport";"Hraje tenis; výborně"\r\n'
    '"Alena";"";"Veselá";"";"";"";"";"";"";"";"";"+420 777 000 611";"";"";"";"";"";"Sousedi";"Řádek 1\r\n'
    'řádek 2"\r\n')
OUTLOOK_CZ = (
    '"Oslovení";"Jméno";"Prostřední jméno";"Příjmení";"Společnost";'
    '"Telefon do zaměstnání";"Telefon domů";"Mobilní telefon";"Kategorie";"Poznámky"\r\n'
    '"";"Věra";"";"Černá";"";"";"777 000 622";"+420 777 000 621";"Rodina";""\r\n')

sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                               # noqa: E402

LOG = []


def _log(msg, level='info', *a, **k):
    LOG.append('%s %s' % (level, msg))


zigmon.log = _log
zigmon.load_config()
(W / 'state').mkdir()
zigmon.CONFIG.update({
    'db_file': str(W / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1', 'token_file': str(W / 'token'),
    'pin': '', 'sensors': [], 'plugs': [], 'mqtt_host': '', 'log_file': '', 'state_dir': str(W / 'state'),
    'debug': 1, 'blacklist': 0, 'public_view': False, 'sms_enabled': True, 'sms_host': '192.0.2.1',
    'sms_api': 'rest'})
d = zigmon.Daemon()
d.notify = lambda message, *a, **k: None
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)
SENT = []


def _sms_send(number, text, why='alert', queue=True):
    SENT.append((number, text, why))
    d.sms_note('out', number, text, ok=True, why=why)
    return True, 'sent'


d.sms_send = _sms_send


def call(path, body=None, session=None, timeout=60, raw=False, method=None, data=None):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': '192.168.40.10'}
    if session:
        headers['X-Zigmon-Session'] = session
    if data is None and body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers, data=data,
                                 method=method or ('GET' if data is None else 'POST'))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            got = r.read()
            return (r.status, got, dict(r.headers)) if raw else (r.status, json.loads(got or b'{}'))
    except urllib.error.HTTPError as e:
        got = e.read()
        return (e.code, got, dict(e.headers)) if raw else (e.code, json.loads(got or b'{}'))


def events():
    d.store.flush(10)
    with d.store.lock:
        return [r[0] for r in d.store.db.execute('SELECT detail FROM events ORDER BY id').fetchall()]


def finish():
    for p in PROCS:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    shutil.rmtree(W, ignore_errors=True)
    print('review5594_contacts: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
    os._exit(1 if bad else 0)


def by_name(book):
    return {c['name']: c for c in book}


try:
    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
    S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
    SO = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''
    check(S and SO, 'could not sign in')

    # ---- the parsers on their own ----------------------------------------------------------
    print('the files')
    rows, skipped = zigmon.contacts_parse_vcf(ANDROID_21)
    clean = [zigmon.contact_clean(r, strict=False)[0] for r in rows]
    check([c and c['name'] for c in clean] == ['Jiří Šimon', 'Oldřich Škoda', None],
          'Android 2.1 names (quoted-printable, UTF-8 and windows-1250): %r' % [r['name'] for r in rows])
    check(clean[0]['numbers'] == [{'label': 'mobile', 'number': '+420777000301'},
                                  {'label': 'work', 'number': '+420777000302'}], 'Android numbers: %r' % clean[0])
    check(clean[0]['note'] == 'Soused odvedle, má klíče od garáže',
          'a soft line break of quoted-printable: %r' % clean[0]['note'])
    check(clean[1]['numbers'] == [{'label': 'home', 'number': '+420777000311'}], '00420 is +420: %r' % clean[1])
    check(zigmon.contact_clean(rows[2], strict=False) == (None, 'no phone number'), 'a card with no number')
    check([r['line'] for r in rows] == [1, 10, 17], 'the line each card starts on: %r' % [r['line'] for r in rows])
    rows, skipped = zigmon.contacts_parse_vcf(IPHONE_30)
    c0 = zigmon.contact_clean(rows[0], strict=False)[0]
    check(c0['name'] == 'Petra Svobodová' and [n['label'] for n in c0['numbers']] == ['mobile', 'home', 'Chata']
          and [n['number'] for n in c0['numbers']] == ['+420777000201', '777000202', '+420777000203'],
          'iPhone: item1.TEL with X-ABLabel, type=HOME: %r' % c0)
    check(c0['note'] == 'Klíče od chaty\nv kuchyni, vlevo', 'an escaped note: %r' % c0['note'])
    check(zigmon.contact_clean(rows[1], strict=False)[0]['name'] == 'Instalatér Novotný',
          'a card with only an ORG is named by it: %r' % rows[1])
    rows, skipped = zigmon.contacts_parse_vcf(GOOGLE_VCF)
    c0 = zigmon.contact_clean(rows[0], strict=False)[0]
    check(c0['group'] == 'Práce' and c0['favourite'] is True and c0['note'] == 'Kolega z kanceláře',
          'Google vCard: CATEGORIES myContacts,starred,Práce and a folded NOTE: %r' % c0)
    rows, skipped = zigmon.contacts_parse_vcf(VCARD_40)
    c0 = zigmon.contact_clean(rows[0], strict=False)[0]
    check([n['number'] for n in c0['numbers']] == ['+420777000501', '+420777000502']
          and c0['numbers'][0]['label'] == 'mobile' and c0['group'] == 'Kamarádi',
          'vCard 4.0: tel: URIs, a quoted TYPE list, ;ext=: %r' % c0)
    rows, skipped = zigmon.contacts_parse_csv(GOOGLE_CSV)
    cs = [zigmon.contact_clean(r, strict=False) for r in rows]
    check(cs[0][0]['name'] == 'Jana Nováková' and cs[0][0]['group'] == 'Rodina' and cs[0][0]['favourite']
          and [n['number'] for n in cs[0][0]['numbers']] == ['+420777000101', '+420777000102', '+420777000103']
          and cs[0][0]['numbers'][1]['label'] == 'home' and cs[0][0]['note'] == 'Teta, z Brna',
          'Google CSV: Group Membership, * starred, ::: in a cell: %r' % (cs[0],))
    check(cs[2] == (None, 'no name') and rows[2]['line'] == 4, 'a row with no name: %r %r' % (cs[2], rows[2]))
    rows, skipped = zigmon.contacts_parse_csv(GOOGLE_CSV_NEW)
    c0 = zigmon.contact_clean(rows[0], strict=False)[0]
    check(c0['name'] == 'Lucie Krásná' and c0['group'] == 'Sousedi' and c0['numbers'][0]['number'] == '+420777000121',
          'Google CSV, the new headers (Labels, Phone 1 - Label): %r' % c0)
    rows, skipped = zigmon.contacts_parse_csv(OUTLOOK_CSV)
    cs = [zigmon.contact_clean(r, strict=False)[0] for r in rows]
    check(cs[0]['name'] == 'Tomáš Malý' and cs[0]['group'] == 'Práce'
          and sorted((n['label'], n['number']) for n in cs[0]['numbers']) ==
          [('home', '777000602'), ('mobile', '+420777000601'), ('work', '+420777000603')]
          and cs[0]['note'] == 'Hraje tenis; výborně',
          'Outlook CSV with ; and a BOM (a fax left out): %r' % cs[0])
    check(cs[1]['note'] == 'Řádek 1\nřádek 2' and rows[1]['line'] == 3,
          'a note over two lines in a quoted cell: %r %r' % (cs[1], rows[1]))
    rows, skipped = zigmon.contacts_parse_csv(OUTLOOK_CZ)
    c0 = zigmon.contact_clean(rows[0], strict=False)[0]
    check(c0['name'] == 'Věra Černá' and c0['group'] == 'Rodina' and len(c0['numbers']) == 2,
          'Czech Outlook headers: %r' % c0)

    print('hostile files')
    t0 = time.time()
    junk = ''.join(chr(c) for c in range(0, 0x250)) * 300
    for fn in (zigmon.contacts_parse_vcf, zigmon.contacts_parse_csv):
        rows, skipped = fn(junk)
        check(isinstance(rows, list) and isinstance(skipped, list), '%s on junk' % fn.__name__)
    rows, skipped = zigmon.contacts_parse_vcf('BEGIN:VCARD\nFN:Cut Short\nTEL:+420777000901\n')
    check(len(rows) == 1 and rows[0]['name'] == 'Cut Short', 'a card with no END is what there is of it: %r' % rows)
    rows, skipped = zigmon.contacts_parse_vcf('BEGIN:VCARD\nFN:Outer Agent\nAGENT:\nBEGIN:VCARD\nFN:Inner\n'
                                              'TEL:+420777000903\nEND:VCARD\nTEL:+420777000902\nEND:VCARD\n')
    check([r['name'] for r in rows] == ['Outer Agent'] and rows[0]['numbers'][0]['number'] == '+420777000902',
          'a card inside a card is not one: %r' % rows)
    rows, skipped = zigmon.contacts_parse_vcf('just some text\nnot a card')
    check(not rows and skipped and 'BEGIN:VCARD' in skipped[0]['why'], 'a file that is no vCard: %r' % skipped)
    rows, skipped = zigmon.contacts_parse_csv('Name,Phone\n"Open quote,+420777000904\nNext,+420777000905\n')
    check(isinstance(rows, list), 'a cell with no closing quote: %r %r' % (rows, skipped))
    rows, skipped = zigmon.contacts_parse_csv('Name\x00,Phone\nA\x00B,+420777000906\n')
    check(rows and rows[0]['name'] == 'AB', 'NULs: %r %r' % (rows, skipped))
    rows, skipped = zigmon.contacts_parse_csv('Foo,Bar\n1,2\n')
    check(not rows and 'phone' in skipped[0]['why'], 'a CSV with no column of numbers: %r' % skipped)
    photo = 'BEGIN:VCARD\nFN:Big Photo\nTEL:+420777000907\nPHOTO;ENCODING=b:' + ''.join(
        'Q' * 74 + '\n ' for _ in range(30000)) + 'Q\nEND:VCARD\n'
    t1 = time.time()
    rows, skipped = zigmon.contacts_parse_vcf(photo)
    check(rows and rows[0]['name'] == 'Big Photo' and time.time() - t1 < 3,
          'thirty thousand folded lines of a photo: %.1f s' % (time.time() - t1))
    many = ''.join('BEGIN:VCARD\nFN:Person %d\nTEL:+420777%06d\nEND:VCARD\n' % (i, i) for i in range(5200))
    rows, skipped = zigmon.contacts_parse_vcf(many)
    check(len(rows) == zigmon.CONTACTS_IMPORT_ROWS and skipped and 'not read' in skipped[-1]['why'],
          'the row cap: %d %r' % (len(rows), skipped[-1:]))
    many_csv = 'Name,Phone\n' + ''.join('P %d,+420777%06d\n' % (i, i) for i in range(5200))
    rows, skipped = zigmon.contacts_parse_csv(many_csv)
    check(len(rows) == zigmon.CONTACTS_IMPORT_ROWS and skipped and 'not read' in skipped[-1]['why'],
          'the row cap of a CSV: %d %r' % (len(rows), skipped[-1:]))
    rows, skipped = zigmon.contacts_parse_vcf('BEGIN:VCARD\nFN:' + 'X' * 500 + '\n' + ''.join(
        'TEL:+420777%06d\n' % i for i in range(9)) + 'NOTE:' + 'n' * 900 + '\nCATEGORIES:' + 'g' * 90 + '\nEND:VCARD\n')
    c0 = zigmon.contact_clean(rows[0], strict=False)[0]
    check(len(c0['name']) == 80 and len(c0['numbers']) == 5 and len(c0['note']) == 200 and len(c0['group']) == 40,
          'an import cuts to size: %d %d %d %d' % (len(c0['name']), len(c0['numbers']), len(c0['note']), len(c0['group'])))
    check(time.time() - t0 < 30, 'the hostile files took %.1f s' % (time.time() - t0))
    check('eval(' not in (HERE / 'zigmon.py').read_text().split('# ---- contacts (5.59.4)')[1].split('\nclass Daemon')[0],
          'no eval in the parsers')

    # ---- the API ---------------------------------------------------------------------------
    print('the API')
    for path in ('/api/contacts', '/api/contacts/export'):
        check(path in zigmon.ApiHandler.ALWAYS_LOCKED, '%s is not in ALWAYS_LOCKED' % path)
    code, out = call('/api/contacts')
    check(code == 403 and 'administrator' in (out.get('error') or ''), 'signed out: %s %r' % (code, out))
    code, out = call('/api/contacts', session=SO)
    check(code == 403, 'an operator reads the contacts: %s %r' % (code, out))
    code, out = call('/api/contacts/export?format=vcf', session=SO)
    check(code == 403, 'an operator exports: %s %r' % (code, out))
    code, out = call('/api/contacts', {'action': 'save', 'contact': {'name': 'X', 'numbers': ['+420777000001']}}, session=SO)
    check(code == 403 and not d.contacts(), 'an operator saves: %s %r' % (code, out))
    code, out = call('/api/contacts', {'action': 'save', 'contact': {'name': 'X', 'numbers': ['+420777000001']}})
    check(code == 403 and not d.contacts(), 'nobody saves: %s %r' % (code, out))
    code, out = call('/api/contacts', session=S)
    check(code == 200 and out == {'ok': True, 'contacts': [], 'groups': [], 'most': 2000, 'numbers_most': 5},
          'an empty book: %s %r' % (code, out))
    code, out = call('/api/contacts', {'action': 'save', 'contact': {
        'name': '  Jana   Nováková ', 'group': 'Rodina', 'note': 'Teta', 'favourite': True,
        'numbers': [{'label': 'mobile', 'number': '+420 777 000 101'}, {'label': 'home', 'number': '00420777000102'},
                    {'label': 'again', 'number': '+420777000101'}]}}, session=S)
    jana = out.get('contact') or {}
    check(code == 200 and re.match(r'^c_[0-9a-f]{6,12}$', jana.get('id') or '') and jana.get('name') == 'Jana Nováková'
          and jana.get('numbers') == [{'label': 'mobile', 'number': '+420777000101'},
                                      {'label': 'home', 'number': '+420777000102'}]
          and jana.get('favourite') is True and out.get('groups') == ['Rodina'],
          'a contact made (spaces folded, 00 as +, the same phone once): %s %r' % (code, out))
    for wrong, why in (({'name': '', 'numbers': ['+420777000110']}, 'no name'),
                       ({'name': 'A' * 81, 'numbers': ['+420777000110']}, '80'),
                       ({'name': 'Kdo', 'numbers': []}, 'no phone number'),
                       ({'name': 'Kdo', 'numbers': ['12']}, 'does not look like'),
                       ({'name': 'Kdo', 'numbers': ['+420 777 abc 110']}, 'does not look like'),
                       ({'name': 'Kdo', 'numbers': ['+42077700011%d' % i for i in range(6)]}, 'at most 5'),
                       ({'name': 'Kdo', 'numbers': [{'label': 'L' * 21, 'number': '+420777000110'}]}, '20'),
                       ({'name': 'Kdo', 'numbers': ['+420777000110'], 'group': 'G' * 41}, '40'),
                       ({'name': 'Kdo', 'numbers': ['+420777000110'], 'note': 'n' * 201}, '200'),
                       ({'name': 'JANA nováková', 'numbers': ['+420777000110']}, 'already')):
        code, out = call('/api/contacts', {'action': 'save', 'contact': wrong}, session=S)
        check(code == 400 and why in (out.get('error') or ''), 'refused %r: %s %r' % (why, code, out))
    code, out = call('/api/contacts', {'action': 'save', 'contact': {'id': 'c_00000000', 'name': 'Nobody',
                                                                     'numbers': ['+420777000110']}}, session=S)
    check(code == 404, 'an id that names nobody: %s %r' % (code, out))
    code, out = call('/api/contacts', {'action': 'save', 'contact': dict(jana, note='Teta z Brna', group='Family')}, session=S)
    check(code == 200 and out['contact']['id'] == jana['id'] and out['contact']['note'] == 'Teta z Brna'
          and len(d.contacts()) == 1 and out.get('groups') == ['Family'], 'a contact changed by its id: %s %r' % (code, out))
    code, out = call('/api/contacts', {'action': 'save', 'contact': dict(jana, name='jana nováková')}, session=S)
    check(code == 200 and d.contacts()[0]['name'] == 'jana nováková', 'its own name in another case: %s %r'
          % (code, out))
    call('/api/contacts', {'action': 'save', 'contact': dict(jana)}, session=S)
    code, out = call('/api/contacts', {'action': 'frobnicate'}, session=S)
    check(code == 400, 'an action that is none: %s %r' % (code, out))
    code, out = call('/api/contacts', {'action': 'delete', 'id': 'c_ffffffff'}, session=S)
    check(code == 404, 'deleting nobody: %s %r' % (code, out))
    code, out = call('/api/contacts', {'action': 'save', 'contact': {'name': 'Do Koše', 'numbers': ['+420777000199']}},
                     session=S)
    gone = out['contact']['id']
    code, out = call('/api/contacts', {'action': 'delete', 'id': gone}, session=S)
    check(code == 200 and [c['name'] for c in out['contacts']] == ['Jana Nováková'], 'deleted: %s %r' % (code, out))

    # import: a dry run, then merge
    code, out = call('/api/contacts', {'action': 'import', 'format': 'csv', 'text': GOOGLE_CSV, 'dry': True}, session=S)
    check(code == 200 and out.get('dry') is True and out.get('added') == 1 and out.get('updated') == 1
          and out.get('skipped_n') == 1 and out['skipped'][0] == {'line': 4, 'why': 'no name'}
          and [p['action'] for p in out.get('plan')] == ['update', 'add', 'skip'] and len(d.contacts()) == 1,
          'a dry run changes nothing and says what would: %s %r' % (code, out))
    code, out = call('/api/contacts', {'action': 'import', 'format': 'csv', 'text': GOOGLE_CSV, 'mode': 'merge'}, session=S)
    book = by_name(d.contacts())
    check(code == 200 and out['added'] == 1 and out['updated'] == 1 and 'plan' not in out
          and book['Jana Nováková']['id'] == jana['id']
          and [n['number'] for n in book['Jana Nováková']['numbers']] == ['+420777000101', '+420777000102', '+420777000103']
          and book['Jana Nováková']['group'] == 'Rodina' and book['Marek Novák']['group'] == 'Rodina',
          'merged: %s %r' % (code, out))
    code, out = call('/api/contacts', {'action': 'import', 'format': 'csv', 'text': GOOGLE_CSV}, session=S)
    check(code == 200 and out['added'] == 0 and out['updated'] == 0 and out['unchanged'] == 2,
          'the same file again: %s %r' % (code, out))
    for text, fmt in ((ANDROID_21, 'vcf'), (IPHONE_30, 'vcf'), (GOOGLE_VCF, 'vcf'), (VCARD_40, 'vcf'),
                      (OUTLOOK_CSV, 'csv'), (OUTLOOK_CZ, 'csv'), (GOOGLE_CSV_NEW, 'csv')):
        code, out = call('/api/contacts', {'action': 'import', 'format': fmt, 'text': text}, session=S)
        check(code == 200 and out['added'] >= 1, 'imported %s: %s %r' % (text[:40], code, out))
    book = by_name(d.contacts())
    check(len(book) == 12, 'twelve contacts: %r' % sorted(book))
    check(set(out['groups']) == {'Rodina', 'Práce', 'Kamarádi', 'Sousedi'}, 'the groups: %r' % out['groups'])
    code, out = call('/api/contacts', {'action': 'import', 'format': 'vcf', 'text': 'x' * (2 * 1024 * 1024 + 1)}, session=S)
    check(code == 400 and '2 MB' in out.get('error', ''), 'past 2 MB: %s %r' % (code, out))
    code, out = call('/api/contacts', {'action': 'import', 'format': 'pdf', 'text': 'x'}, session=S)
    check(code == 400, 'a format that is none: %s' % code)
    code, out = call('/api/contacts', {'action': 'import', 'format': 'vcf', 'text': ['x']}, session=S)
    check(code == 400, 'text that is not text: %s' % code)
    code, out = call('/api/contacts', {'action': 'import', 'format': 'vcf', 'text': junk[:500000]}, session=S)
    check(code == 200 and out['added'] == 0, 'junk through the API: %s %r' % (code, str(out)[:200]))
    try:
        code, out = call('/api/contacts', data=b'{"action": "import", "text": "' + b'a' * (7 * 1024 * 1024) + b'"}',
                         session=S)
    except (urllib.error.URLError, ConnectionError):
        code = 'closed'                  # refused before it was read: the daemon hung up on the rest
    check(code in (400, 'closed') and len(d.contacts()) == 12, 'a body past 6 MB: %s' % code)

    # export, and read back
    print('export')
    code, data, hdr = call('/api/contacts/export?format=vcf', session=S, raw=True)
    vcf = data.decode('utf-8')
    check(code == 200 and hdr.get('Content-Type', '').startswith('text/vcard')
          and 'filename="contacts.vcf"' in hdr.get('Content-Disposition', '')
          and vcf.count('BEGIN:VCARD') == 12 and 'VERSION:3.0' in vcf and '\r\n' in vcf,
          'the vCard export: %s %r' % (code, hdr))
    check(all(len(x.encode('utf-8')) <= 75 for x in vcf.split('\r\n')), 'a line past 75 octets')
    check('NOTE:Hraje tenis\\; výborně' in vcf and 'CATEGORIES:Rodina' in vcf and 'X-ZIGMON-FAVOURITE:TRUE' in vcf
          and 'X-ABLabel:Chata' in vcf, 'what the vCard says: %s' % vcf[:600])
    code, data, hdr = call('/api/contacts/export?format=csv', session=S, raw=True)
    csvt = data.decode('utf-8')
    check(code == 200 and csvt.startswith('\ufeffName,Given Name,Family Name,Group Membership,Phone 1 - Type,Phone 1 - Value,')
          and 'filename="contacts.csv"' in hdr.get('Content-Disposition', ''), 'the CSV export: %s %r' % (code, csvt[:200]))
    check('* starred' in csvt, 'a favourite is * starred')
    code, out = call('/api/contacts/export?format=exe', session=S)
    check(code == 400, 'an export of another kind: %s' % code)
    before = sorted((c['name'], tuple((n['label'], n['number']) for n in c['numbers']), c['group'], c['note'], c['favourite'])
                    for c in d.contacts())
    for text, fmt in ((vcf, 'vcf'), (csvt, 'csv')):
        rows, skipped = (zigmon.contacts_parse_vcf if fmt == 'vcf' else zigmon.contacts_parse_csv)(text)
        back = sorted((c['name'], tuple((n['label'], n['number']) for n in c['numbers']), c['group'], c['note'],
                       c['favourite']) for c in (zigmon.contact_clean(r, strict=False)[0] for r in rows))
        check(back == before and not skipped, 'the %s export read back is not the same: %r' % (
            fmt, [x for x in back if x not in before][:3]))
    code, out = call('/api/contacts', {'action': 'import', 'format': 'vcf', 'text': vcf}, session=S)
    check(code == 200 and out['added'] == 0 and out['updated'] == 0 and out['unchanged'] == 12,
          'its own export again changes nothing: %r' % out)

    # replace: a name kept keeps its id, the others go
    ids = {c['name']: c['id'] for c in d.contacts()}
    code, out = call('/api/contacts', {'action': 'import', 'format': 'csv', 'text': GOOGLE_CSV, 'mode': 'replace',
                                       'dry': True}, session=S)
    check(code == 200 and out['removed'] == 10 and len(d.contacts()) == 12, 'a dry replace: %r' % out)
    code, out = call('/api/contacts', {'action': 'import', 'format': 'csv', 'text': GOOGLE_CSV, 'mode': 'replace'}, session=S)
    book = by_name(d.contacts())
    check(code == 200 and sorted(book) == ['Jana Nováková', 'Marek Novák']
          and book['Jana Nováková']['id'] == ids['Jana Nováková'] and out['removed'] == 10,
          'replaced: %s %r' % (code, out))
    check(len(json.loads(d.store.get_meta('contacts_before_replace'))) == 12, 'the book before a replace is kept')
    call('/api/contacts', {'action': 'import', 'format': 'vcf', 'text': vcf}, session=S)
    check(len(d.contacts()) == 12, 'back again')

    # at most 2000
    full = [{'id': 'c_%08x' % i, 'name': 'Filler %d' % i, 'numbers': [{'label': '', 'number': '+420700%06d' % i}],
             'group': '', 'note': '', 'favourite': False} for i in range(2000)]
    kept = d.store.get_meta('contacts')
    d.store.set_meta('contacts', json.dumps(full))
    code, out = call('/api/contacts', {'action': 'save', 'contact': {'name': 'One Too Many', 'numbers': ['+420777000999']}},
                     session=S)
    check(code == 400 and 'full' in out.get('error', ''), 'the 2001st: %s %r' % (code, out))
    code, out = call('/api/contacts', {'action': 'import', 'format': 'vcf', 'text': GOOGLE_VCF}, session=S)
    check(code == 200 and out['added'] == 0 and 'full' in out['skipped'][0]['why'], 'an import into a full book: %r' % out)
    t1 = time.time()
    for _ in range(300):
        d.contact_by_number('+420700001999')
    check(d.contact_by_number('+420700001999')['name'] == 'Filler 1999' and time.time() - t1 < 1,
          'a number found among 2000 (300 times in %.2f s)' % (time.time() - t1))
    d.store.set_meta('contacts', kept)

    # ---- the helpers the desktop app and the Stream Deck use ---------------------------------
    print('expanding')
    book = by_name(d.contacts())
    jid, mid = book['Jana Nováková']['id'], book['Marek Novák']['id']
    unknown = []
    got = d.contacts_expand(['contact:' + jid, 'group:rodina', '+420 777 000 101', '777000104', 'contact:c_000000',
                             'group:Nobody', 'not a number'], unknown)
    check(got and got[0][0] == '+420777000101' and [n for n, _ in got].count('+420777000101') == 1
          and {c['name'] for _, c in got if c} >= {'Jana Nováková', 'Marek Novák'}
          and unknown == ['contact:c_000000', 'group:Nobody', 'not a number'],
          'contacts_expand: %r %r' % (got, unknown))
    rodina = [c['name'] for c in d.contacts() if c['group'].lower() == 'rodina']
    check(len(got) == len(rodina), 'one number for each of the group and no more: %r %r' % (got, rodina))
    check(d.contact_by_number('00420777000104')['id'] == mid and d.contact_by_number('777000104')['id'] == mid
          and d.contact_by_number('+421777000104') is None and d.contact_by_number('') is None,
          'contact_by_number: the same phone however written, another country not')

    # ---- sending ---------------------------------------------------------------------------
    print('sending')
    SENT.clear()
    code, out = call('/api/sms/send', {'to': ['+420 777 000 777'], 'text': 'Ahoj'}, session=S)
    check(code == 200 and SENT == [('+420 777 000 777', 'Ahoj', 'by hand')], 'a plain number as before: %r' % SENT)
    SENT.clear()
    code, out = call('/api/sms/send', {'number': '777000778', 'text': 'Ahoj'}, session=S)
    check(code == 200 and [s[0] for s in SENT] == ['777000778'], 'number instead of to, as before: %r' % SENT)
    SENT.clear()
    code, out = call('/api/sms/send', {'to': ['777000779', '777000779'], 'text': 'Ahoj'}, session=S)
    check([s[0] for s in SENT] == ['777000779', '777000779'], 'plain numbers are not changed at all: %r' % SENT)
    SENT.clear()
    code, out = call('/api/sms/send', {'to': ['contact:' + jid, 'group:Rodina', '+420777000101', 'contact:c_0000ff'],
                                       'text': 'Večeře v 6'}, session=S)
    numbers = [s[0] for s in SENT]
    check(code == 200 and numbers[0] == '+420777000101' and len(numbers) == len(rodina) and len(set(numbers)) == len(numbers)
          and out.get('failed') == ['contact:c_0000ff'], 'contact: and group: expanded, the same phone once: %r %r'
          % (numbers, out))
    SENT.clear()
    code, out = call('/api/sms/send', {'to': ['contact:' + jid], 'text': 'x'}, session=SO)
    check(code == 403 and not SENT, 'an operator sends to the contacts: %s %r' % (code, out))
    code, out = call('/api/sms/log?limit=50', session=S)
    named = {m['number']: (m.get('contact') or {}).get('name') for m in out.get('messages', [])}
    check(named.get('+420777000101') == 'Jana Nováková' and named.get('+420 777 000 777') is None,
          'the contact of a number in the log: %r' % named)

    # ---- nothing of a contact in the log -----------------------------------------------------
    print('the log')
    evs = '\n'.join(events())
    whole = '\n'.join(LOG)
    for word in ('Nováková', 'Svobodová', '777000101', '777 000 101', 'Rodina', 'Teta', 'Kolega'):
        check(word not in evs, '%r is in the events' % word)
        check(word not in whole.replace('+420 777 000 777', ''), '%r is in the log' % word)
    check(re.search(r'contacts imported: \d+ added, \d+ updated', evs) and 'a contact added' in evs
          and 'a contact removed' in evs, 'the events say how many: %s' % evs[-600:])
    check(any('/api/contacts' in x for x in LOG), 'the debug log wrote nothing of the road')

    # ---- the relay ---------------------------------------------------------------------------
    print('the relay')
    page = (HERE / 'web' / 'index.php').read_text()
    for words in ("$what === 'contacts' && $_SERVER['REQUEST_METHOD'] === 'GET'", "'contacts' => '/api/contacts'",
                  "$what === 'contacts-export'", 'data-sub="contacts"', 'id="ct-card"'):
        check(words in page, 'the page has no %s' % words)
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

    def relay(query, body=None, session=None, raw=False):
        headers = {'Content-Type': 'application/json'}
        if session:
            headers['Cookie'] = 'zigmon_session=' + session
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request('http://127.0.0.1:%d/index.php?%s' % (PHP_PORT, query), headers=headers, data=data,
                                     method='GET' if body is None else 'POST')
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                got = r.read()
                return (r.status, got, dict(r.headers)) if raw else (r.status, json.loads(got or b'{}'))
        except urllib.error.HTTPError as e:
            got = e.read()
            return (e.code, got, dict(e.headers)) if raw else (e.code, json.loads(got or b'{}'))

    code, out = relay('api=contacts')
    check(code == 403, 'the relay, signed out: %s %r' % (code, out))
    code, out = relay('api=contacts', session=S)
    check(code == 200 and len(out.get('contacts') or []) == 12, 'the relay, an administrator: %s' % code)
    code, out = relay('api=contacts', {'action': 'import', 'format': 'vcf', 'text': VCARD_40, 'dry': True}, session=S)
    check(code == 200 and out.get('unchanged') == 1, 'an import through the relay: %s %r' % (code, out))
    big = ''.join('BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Velký Soubor %d\r\nNOTE:%s\r\nTEL:+420778%06d\r\nEND:VCARD\r\n'
                  % (i, 'ž' * 300, i) for i in range(1800))
    check(1024 * 1024 < len(big.encode()) < 2 * 1024 * 1024, 'the big file is %d bytes' % len(big.encode()))
    code, out = relay('api=contacts', {'action': 'import', 'format': 'vcf', 'text': big, 'dry': True}, session=S)
    check(code == 200 and out.get('added') == 1800, 'a file of 1.2 MB through the relay: %s %r' % (code, str(out)[:200]))
    code, data, hdr = relay('api=contacts-export&format=csv', session=S, raw=True)
    check(code == 200 and data.decode('utf-8').startswith('\ufeffName,') and 'contacts.csv' in hdr.get('Content-Disposition', ''),
          'the CSV through the relay: %s %r' % (code, hdr))
    code, data, hdr = relay('api=contacts-export&format=vcf', session=S, raw=True)
    check(code == 200 and data.count(b'BEGIN:VCARD') == 12, 'the vCard through the relay: %s' % code)
    code, data, hdr = relay('api=contacts-export&format=vcf', raw=True)
    check(code == 403 and b'BEGIN:VCARD' not in data, 'the export through the relay, signed out: %s' % code)

    # ---- the page ----------------------------------------------------------------------------
    print('the page')
    d.save_people([{'name': 'Pavel Testovací', 'phone': '+420 777 000 900', 'macs': [], 'sms_alerts': False}])
    d.sms_note('in', '+420777000401', 'Budu tam v osm.', ok=True, road='push')
    d.sms_note('in', '+420777000888', 'Neznámé číslo.', ok=True, road='push')
    (W / 'phone.vcf').write_text(ANDROID_21 + GOOGLE_VCF.replace('Karel', 'Karlík'), encoding='utf-8')
    (W / 'phone2.vcf').write_text(ANDROID_21 + GOOGLE_VCF.replace('Karel', 'Kristýna'), encoding='utf-8')
    SHOTS.mkdir(parents=True, exist_ok=True)
    js = r'''
const { chromium } = require('playwright');
const job = %(job)s;
(async () => {
  const b = await chromium.launch();
  const r = {errors: []};
  const base = 'http://127.0.0.1:' + job.port + '/';
  for (const shot of [{n: 'desktop', w: 1400, h: 950}, {n: 'phone', w: 390, h: 844}]) {
    const ctx = await b.newContext({viewport: {width: shot.w, height: shot.h}, colorScheme: 'dark', deviceScaleFactor: 2});
    await ctx.addCookies([{name: 'zigmon_session', value: job.s, url: base}]);
    const p = await ctx.newPage();
    p.on('pageerror', e => r.errors.push(String(e)));
    const x = r[shot.n] = {};
    await p.goto(base + '#sms/contacts');
    await p.waitForSelector('#ct-list .ct-one', {timeout: 20000});
    await p.waitForTimeout(500);
    x.pills = await p.evaluate(() => Array.from(document.querySelectorAll('#sms-parts button')).map(b => b.getAttribute('data-sub')));
    x.cards = await p.evaluate(() => Array.from(document.querySelectorAll('#ct-list .ct-one')).map(c => [
      c.querySelector('.ct-av').textContent, c.querySelector('.ct-name').textContent, getComputedStyle(c.querySelector('.ct-av')).color]));
    x.letters = await p.evaluate(() => Array.from(document.querySelectorAll('#ct-list .ct-letter')).map(c => c.textContent));
    x.chips = await p.evaluate(() => Array.from(document.querySelectorAll('#ct-groups .ct-chip')).map(c => c.textContent));
    x.drop = await p.evaluate(() => getComputedStyle(document.querySelector('#ct-drop')).display === 'none');
    x.count = await p.evaluate(() => document.querySelector('#sms-n-contacts').textContent);
    x.wide = await p.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    await p.screenshot({path: job.dir + '/contacts-' + shot.n + '.png'});
    await p.fill('#ct-find', '000 40');
    await p.waitForTimeout(150);
    x.found = await p.evaluate(() => Array.from(document.querySelectorAll('#ct-list .ct-name')).map(c => c.textContent));
    await p.fill('#ct-find', 'nov');
    await p.waitForTimeout(150);
    x.foundName = await p.evaluate(() => Array.from(document.querySelectorAll('#ct-list .ct-name')).map(c => c.textContent));
    await p.fill('#ct-find', '');
    await p.click('#ct-groups .ct-chip:has-text("Rodina")');
    x.family = await p.evaluate(() => Array.from(document.querySelectorAll('#ct-list .ct-name')).map(c => c.textContent));
    await p.click('#ct-groups .ct-chip[data-filter="fav"]');
    x.favs = await p.evaluate(() => Array.from(document.querySelectorAll('#ct-list .ct-name')).map(c => c.textContent));
    await p.click('#ct-groups .ct-chip[data-filter="all"]');
    // the drawer
    await p.click('#ct-list .ct-one:has-text("Petra")');
    await p.waitForSelector('#ct-drawer.open', {timeout: 5000});
    await p.waitForTimeout(350);
    x.drawer = await p.evaluate(() => ({
      name: document.querySelector('#ct-e-name').value,
      labels: Array.from(document.querySelectorAll('#ct-drawer .ct-lbl')).map(i => i.value),
      tels: Array.from(document.querySelectorAll('#ct-drawer .ct-tel')).map(i => i.value),
      note: document.querySelector('#ct-e-note').value, title: document.querySelector('#ct-d-title').textContent,
      av: document.querySelector('#ct-drawer .ct-av').textContent,
      box: (() => { const q = document.querySelector('#ct-drawer').getBoundingClientRect(); return [q.left, q.width]; })()}));
    await p.screenshot({path: job.dir + '/drawer-' + shot.n + '.png'});
    if (shot.n === 'desktop') {
      await p.click('#ct-drawer .ct-addnum');
      await p.fill('#ct-drawer .ct-nrow:last-child .ct-tel', '+420 777 000 204');
      await p.fill('#ct-drawer .ct-nrow:last-child .ct-lbl', 'work');
      await p.fill('#ct-e-group', 'Sousedi');
      await p.click('#ct-e-save');
      await p.waitForSelector('#ct-drawer', {state: 'detached', timeout: 8000});
      // a new one, refused, then right
      await p.click('#ct-add');
      await p.waitForSelector('#ct-drawer.open', {timeout: 5000});
      await p.fill('#ct-e-name', 'Zuzana Testová');
      await p.fill('#ct-drawer .ct-tel', '12');
      await p.click('#ct-e-save');
      await p.waitForSelector('#ct-drawer .ct-said:not(:empty)', {timeout: 5000});
      x.refused = await p.evaluate(() => document.querySelector('#ct-drawer .ct-said').textContent);
      await p.fill('#ct-drawer .ct-tel', '+420 777 000 131');
      await p.click('#ct-drawer .ct-favrow');
      await p.waitForTimeout(250);
      await p.screenshot({path: job.dir + '/drawer-new-desktop.png'});
      await p.click('#ct-e-save');
      await p.waitForSelector('#ct-drawer', {state: 'detached', timeout: 8000});
      // delete, with a question
      await p.click('#ct-list .ct-one:has-text("Zuzana")');
      await p.waitForSelector('#ct-drawer.open');
      await p.click('#ct-e-delete');
      await p.waitForSelector('#zmodal:not([hidden])', {timeout: 5000});
      x.ask = await p.evaluate(() => document.querySelector('#zmodal-title').textContent);
      await p.screenshot({path: job.dir + '/delete-desktop.png'});
      await p.click('#zmodal-foot button:has-text("Delete the contact")');
      await p.waitForSelector('#ct-drawer', {state: 'detached', timeout: 8000});
      await p.waitForTimeout(300);
      x.afterDelete = await p.evaluate(() => Array.from(document.querySelectorAll('#ct-list .ct-name')).map(c => c.textContent));
      // a star from the card
      await p.click('#ct-list .ct-one:has-text("Eva") .ct-ib.star');
      await p.waitForTimeout(500);
    } else {
      await p.click('#ct-drawer .ct-dfoot button:has-text("Cancel")');
      await p.waitForSelector('#ct-drawer', {state: 'detached', timeout: 8000});
    }
    // import with a preview
    await p.setInputFiles('#ct-file', shot.n === 'desktop' ? job.file : job.file2);
    await p.waitForSelector('#zmodal:not([hidden]) .ct-imp-row', {timeout: 10000});
    await p.waitForTimeout(300);
    x.preview = await p.evaluate(() => ({
      title: document.querySelector('#zmodal-title').textContent,
      sum: Array.from(document.querySelectorAll('#zmodal .ct-pill')).map(c => c.textContent),
      rows: Array.from(document.querySelectorAll('#zmodal .ct-imp-row:not(.ct-imp-h)')).map(c => [c.className.replace('ct-imp-row ', ''),
        (c.querySelector('.who span:last-child') || {}).textContent || '', (c.querySelector('.why') || {}).textContent || '']),
      go: document.querySelector('#zmodal-foot .btn.primary').textContent}));
    await p.screenshot({path: job.dir + '/import-' + shot.n + '.png'});
    await p.click('#zmodal .ct-seg button[data-mode="replace"]');
    await p.waitForSelector('#zmodal .ct-imp-warn', {timeout: 8000});
    x.replace = await p.evaluate(() => document.querySelector('#zmodal .ct-imp-warn').textContent);
    await p.click('#zmodal .ct-seg button[data-mode="merge"]');
    await p.waitForFunction(() => !document.querySelector('#zmodal .ct-imp-warn'), null, {timeout: 8000});
    if (shot.n === 'desktop') {
      await p.click('#zmodal-foot .btn.primary');
      await p.waitForSelector('#zmodal[hidden]', {state: 'attached', timeout: 8000});
      await p.waitForTimeout(400);
      x.imported = await p.evaluate(() => Array.from(document.querySelectorAll('#ct-list .ct-name')).map(c => c.textContent));
    } else {
      await p.click('#zmodal-foot button:has-text("Cancel")');
    }
    // Write a message
    await p.click('#sms-parts button[data-sub="write"]');
    await p.waitForSelector('#rc-in', {timeout: 5000});
    x.quick = await p.evaluate(() => Array.from(document.querySelectorAll('#rc-quick .rc-q')).map(c => c.textContent));
    await p.click('#rc-in');
    await p.keyboard.type('nov');
    await p.waitForSelector('#rc-pop:not([hidden]) .rc-opt', {timeout: 5000});
    x.offered = await p.evaluate(() => Array.from(document.querySelectorAll('#rc-pop .rc-opt b')).map(c => c.textContent));
    if (shot.n === 'desktop') await p.screenshot({path: job.dir + '/write-autocomplete-desktop.png'});
    await p.keyboard.press('ArrowDown');
    x.sel = await p.evaluate(() => (document.querySelector('#rc-pop .rc-opt.on b') || {}).textContent);
    await p.keyboard.press('ArrowUp');
    await p.keyboard.press('Enter');            // Jana has three numbers: which?
    await p.waitForSelector('#rc-pop .rc-ph:has-text("Which of")', {timeout: 5000});
    x.pick = await p.evaluate(() => Array.from(document.querySelectorAll('#rc-pop .rc-opt b')).map(c => c.textContent));
    if (shot.n === 'desktop') await p.screenshot({path: job.dir + '/write-pick-desktop.png'});
    await p.keyboard.press('ArrowDown');
    await p.keyboard.press('Enter');
    await p.keyboard.type('rodi');
    await p.waitForSelector('#rc-pop .rc-opt:has-text("Everybody in the group")', {timeout: 5000});
    await p.click('#rc-pop .rc-opt:has-text("Everybody in the group")');
    await p.keyboard.type('+420 777 000 555');
    await p.keyboard.press('Enter');
    await p.click('#rc-quick .rc-q:has-text("Karel")');
    await p.waitForSelector('#rc-pop .rc-ph:has-text("Which of")', {timeout: 5000});
    await p.keyboard.press('Enter');
    x.rchips = await p.evaluate(() => Array.from(document.querySelectorAll('#rc-field .rc-chip')).map(c => [c.className.replace('rc-chip ', ''),
      c.dataset.value, c.querySelector('.nm').textContent]));
    await p.keyboard.press('Backspace');
    await p.keyboard.press('Backspace');
    x.afterBack = await p.evaluate(() => document.querySelectorAll('#rc-field .rc-chip').length);
    await p.click('#rc-quick .rc-q:has-text("Karel")');
    await p.waitForSelector('#rc-pop .rc-ph:has-text("Which of")', {timeout: 5000});
    await p.keyboard.press('Enter');
    // the facts completer of the text, as before
    await p.click('#sms-text');
    await p.keyboard.type('Ahoj ');
    await p.keyboard.press('Control+Space');
    await p.waitForTimeout(300);
    x.facts = await p.evaluate(() => { const a = document.querySelector('.acbox'); return !!a && a.offsetParent !== null && a.textContent.length > 0; });
    await p.keyboard.press('Escape');
    await p.evaluate(() => { const t = document.querySelector('#sms-text'); t.value = 'Večeře je v šest.'; t.dispatchEvent(new Event('input')); });
    await p.waitForTimeout(500);
    await p.screenshot({path: job.dir + '/write-' + shot.n + '.png'});
    if (shot.n === 'desktop') {
      await p.click('#sms-write-send');
      await p.waitForTimeout(1200);
    }
    // the messages, with the contact's name
    await p.click('#sms-parts button[data-sub="log"]');
    await p.waitForSelector('#sms-log .sms-line', {timeout: 8000});
    await p.waitForTimeout(400);
    x.log = await p.evaluate(() => Array.from(document.querySelectorAll('#sms-log .sms-line .sms-who')).map(c => c.textContent));
    await p.screenshot({path: job.dir + '/messages-' + shot.n + '.png'});
    x.wideEnd = await p.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    await ctx.close();
  }
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e && e.stack || e)})); });
'''
    npm_root = sh(['npm', 'root', '-g']).stdout.strip()
    (W / 'page.js').write_text(js % {'job': json.dumps({'s': S, 'port': PHP_PORT, 'dir': str(SHOTS),
                                                         'file': str(W / 'phone.vcf'), 'file2': str(W / 'phone2.vcf')})})
    SENT.clear()
    got = sh(['node', str(W / 'page.js')], timeout=400, env=dict(os.environ, NODE_PATH=npm_root))
    try:
        r = json.loads(got.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        r = {'error': (got.stdout + got.stderr)[-800:]}
    if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
        print('  SKIPPED (no browser here): %s' % r['error'][:200])
    else:
        check(not r.get('error'), 'the page: %s' % r.get('error'))
        check(not r.get('errors'), 'errors on the page: %r' % r.get('errors'))
        dt, ph = r.get('desktop') or {}, r.get('phone') or {}
        check(dt.get('pills') == ['log', 'write', 'contacts'], 'the SMS pills: %r' % dt.get('pills'))
        cards = {c[1]: c for c in dt.get('cards') or []}
        check(len(cards) == 12 and cards.get('Jana Nováková', [''])[0] == 'JN'
              and cards.get('Instalatér Novotný', [''])[0] == 'IN' and dt.get('count') == '12',
              'the cards with their initials: %r' % dt.get('cards'))
        check(len({c[2] for c in dt.get('cards') or []}) >= 5, 'the avatars are not of several colours')
        check(dt.get('letters') == [] and dt.get('drop') is True, 'letters over twelve, or the drop shown: %r %r' % (dt.get('letters'), dt.get('drop')))
        check(dt.get('found') == ['Karel Dvořák'], 'found by a number: %r' % dt.get('found'))
        check(set(dt.get('foundName') or []) == {'Jana Nováková', 'Marek Novák', 'Instalatér Novotný'},
              'found by a name, without its accents: %r' % dt.get('foundName'))
        check(set(dt.get('family') or []) == set(rodina), 'the group chip: %r' % dt.get('family'))
        check(set(dt.get('favs') or []) == {'Jana Nováková', 'Karel Dvořák'}, 'favourites: %r' % dt.get('favs'))
        dr = dt.get('drawer') or {}
        check(dr.get('name') == 'Petra Svobodová' and dr.get('labels') == ['mobile', 'home', 'Chata']
              and dr.get('tels') == ['+420 777 000 201', '777 000 202', '+420 777 000 203'] and dr.get('av') == 'PS'
              and 'v kuchyni' in dr.get('note', ''), 'the drawer: %r' % dr)
        check(abs((ph.get('drawer') or {}).get('box', [1, 0])[0]) < 1 and (ph.get('drawer') or {}).get('box', [0, 0])[1] == 390,
              'the drawer is the whole width of a phone: %r' % (ph.get('drawer') or {}).get('box'))
        petra = by_name(d.contacts()).get('Petra Svobodová') or {}
        check([n['number'] for n in petra.get('numbers', [])][-1:] == ['+420777000204'] and petra.get('group') == 'Sousedi',
              'the drawer saved: %r' % petra)
        check('does not look like a phone number' in (dt.get('refused') or ''), 'refused in the drawer: %r' % dt.get('refused'))
        check(dt.get('ask') == 'Delete Zuzana Testová?' and 'Zuzana Testová' not in (dt.get('afterDelete') or [])
              and 'Zuzana Testová' not in by_name(d.contacts()), 'deleted with a question: %r' % dt.get('ask'))
        check(by_name(d.contacts()).get('Eva Malá', {}).get('favourite') is True, 'the star on the card')
        pv = dt.get('preview') or {}
        kinds = sorted(x[0] for x in pv.get('rows') or [])
        check(pv.get('title') == 'Import contacts' and kinds == ['add', 'same', 'same', 'skip']
              and any(x[0] == 'add' and x[1] == 'Karlík Dvořák' for x in pv.get('rows') or [])
              and any(x[0] == 'skip' and 'no phone number' in x[2] for x in pv.get('rows') or [])
              and pv.get('go') == 'Import 1 contact', 'the preview: %r' % pv)
        check('contacts that are not in it are removed' in (dt.get('replace') or ''), 'replace warns: %r' % dt.get('replace'))
        check('Karlík Dvořák' in (dt.get('imported') or []), 'imported from the page: %r' % dt.get('imported'))
        check(any('Jana' in q for q in dt.get('quick') or []) and any('Pavel' in q for q in dt.get('quick') or []),
              'the quick row: favourites and the people: %r' % dt.get('quick'))
        check((dt.get('offered') or [])[:3] == ['Jana Nováková', 'Instalatér Novotný', 'Marek Novák'],
              'offered: %r' % dt.get('offered'))
        check(dt.get('sel') == 'Instalatér Novotný', 'the arrows: %r' % dt.get('sel'))
        check(dt.get('pick') == ['+420 777 000 101', '+420 777 000 102', '+420 777 000 103'], 'the pick: %r' % dt.get('pick'))
        chips = dt.get('rchips') or []
        check([c[1] for c in chips] == ['+420777000102', 'group:Rodina', '+420 777 000 555', 'contact:' + by_name(d.contacts())[
            'Karel Dvořák']['id']] and chips[0][2] == 'Jana Nováková' and chips[1][0] == 'group',
              'the chips: %r' % chips)
        check(dt.get('afterBack') == 3, 'Backspace twice takes the last chip: %r' % dt.get('afterBack'))
        check(dt.get('facts') is True, 'the facts completer is gone from the text')
        sent = [s[0] for s in SENT]
        check(sent[:1] == ['+420777000102'] and '+420 777 000 555' in sent and '+420777000401' in sent
              and len(sent) == len(set(sent)), 'sent from the page: %r' % sent)
        check(any('Karel Dvořák' in w and '777 000 401' in w for w in dt.get('log') or [])
              and any('+420777000888' in w for w in dt.get('log') or []), 'the names in the messages: %r' % dt.get('log'))
        for sh_ in (dt, ph):
            check((sh_.get('wide') or [0, 0])[0] <= (sh_.get('wide') or [0, 0])[1] and
                  (sh_.get('wideEnd') or [0, 0])[0] <= (sh_.get('wideEnd') or [0, 0])[1],
                  'wider than the screen: %r %r' % (sh_.get('wide'), sh_.get('wideEnd')))
        check(ph.get('preview', {}).get('go') == 'Import 1 contact', 'the preview on a phone: %r' % ph.get('preview'))
        print('  screenshots in %s' % SHOTS)
except Exception as e:                                      # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(False, 'the test broke: %s' % e)
finish()
