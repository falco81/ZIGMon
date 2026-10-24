#!/usr/bin/env python3
"""The dashboard's own roads to root (5.18), the whole way: the API with its
PIN, the daemon keeping what is wanted, deploy/zigmon_root.py run as root
would run it, and the files of a machine stood in for by a folder.

  * every road behind the PIN, reads too;
  * who may reach the pages: saved, put in nginx - and refused when it would
    shut out the address the dashboard is being used from;
  * the firewall: the rules of your own and what the house needs, in that
    order (firewalld, through a stand-in); a DROP that would shut the caller
    out refused;
  * the certificate: PEM in any order, a PFX with its password, a request made
    here and only its certificate sent back, a self-signed one, the TLS
    settings - each put in by root; the certificate handed back without its
    key;
  * what is wanted put in again by itself when it drifted - and not a second
    time when root refused it;
  * a backup of the whole installation made, handed over for a download with a
    password and gone after it, sent back in pieces and taken in, put back;
  * a new version: a package signed by a key of the test's own taken, one
    older than what runs refused, the upgrade asked for;
  * the certificate running out, said once.

    PYTHONPATH=. python3 test/admin.py
"""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ROOT_HELPER = HERE / 'deploy' / 'zigmon_root.py'
W = Path(tempfile.mkdtemp(prefix='zigmon-admin-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ---- the machine ------------------------------------------------------------------
STATE, ETC = W / 'state', W / 'etc'
CERTS = ETC / 'nginx' / 'certs'
for d in (STATE / 'root', STATE / 'backups', CERTS, ETC / 'nginx' / 'conf.d', ETC / 'zigmon',
          ETC / 'mosquitto', W / 'logs', W / 'www', W / 'body'):
    d.mkdir(parents=True, exist_ok=True)


def certificate(name, cn, ca=None, days=400):
    key, crt = W / (name + '.key'), W / (name + '.crt')
    sh(['openssl', 'genrsa', '-out', str(key), '2048'])
    if ca is None:
        sh(['openssl', 'req', '-x509', '-new', '-key', str(key), '-days', str(days), '-subj', '/CN=%s' % cn,
            '-out', str(crt), '-addext', 'subjectAltName=DNS:%s' % cn,
            '-addext', 'basicConstraints=critical,CA:TRUE'])
    else:
        csr = W / (name + '.csr')
        sh(['openssl', 'req', '-new', '-key', str(key), '-subj', '/CN=%s' % cn, '-out', str(csr)])
        ext = W / (name + '.ext')
        ext.write_text('subjectAltName=DNS:%s\nbasicConstraints=CA:%s\n' % (cn, 'TRUE' if 'ca' in name else 'FALSE'))
        sh(['openssl', 'x509', '-req', '-in', str(csr), '-CA', str(ca[1]), '-CAkey', str(ca[0]),
            '-CAcreateserial', '-days', str(days), '-out', str(crt), '-extfile', str(ext)])
    return key, crt


old_key, old_crt = certificate('old', 'mqtt.falco81.net')
shutil.copy(old_crt, CERTS / 'server.pem')
shutil.copy(old_key, CERTS / 'server.key')
shutil.copy(old_crt, CERTS / 'server.ca')
conf = (HERE / 'deploy' / 'nginx-zigmon.conf').read_text()
for a, b in (('/etc/nginx/certs/', str(CERTS) + '/'), ('/var/www/zigmon', str(W / 'www')),
             ('unix:/run/php-fpm/www.sock', 'unix:' + str(W / 'fpm.sock')),
             ('/var/log/nginx/', str(W / 'logs') + '/'),
             ('include        fastcgi_params;', 'include        /etc/nginx/fastcgi_params;'),
             ('listen      443 ssl http2;', 'listen      127.0.0.1:18444 ssl;'),
             ('listen      [::]:443 ssl http2;', ''), ('listen      80;', 'listen 127.0.0.1:18081;'),
             ('listen      [::]:80;', '')):
    conf = conf.replace(a, b)
NGINX_CONF = ETC / 'nginx' / 'conf.d' / 'zigmon.conf'
NGINX_CONF.write_text(conf)
(W / 'nginx.conf').write_text(('user root;\n' if os.geteuid() == 0 else '') + '''daemon off;
pid %(w)s/nginx.pid;
error_log %(w)s/logs/main.log;
events { worker_connections 64; }
http { include /etc/nginx/mime.types; client_body_temp_path %(w)s/body; include %(c)s; }
''' % {'w': W, 'c': NGINX_CONF})
(ETC / 'mosquitto' / 'mosquitto.conf').write_text('listener 8883\ncertfile %s\nkeyfile %s\n' % (
    CERTS / 'server.pem', CERTS / 'server.key'))
DB = STATE / 'history.db'
(ETC / 'zigmon' / 'config.json').write_text(json.dumps({'db_file': str(DB), 'pin': '1234'}))
FSTATE = W / 'firewalld.json'
FSTATE.write_text(json.dumps({'runtime': {'public': []}, 'permanent': {'public': []}}))
FAKE = W / 'firewall-cmd'
FAKE.write_text('''#!%s
import json, sys
p = %r
s = json.load(open(p))
a = sys.argv[1:]
if a == ['--state']: print('running'); sys.exit(0)
if a == ['--get-active-zones']: print('public\\n  interfaces: eth0'); sys.exit(0)
if a == ['--get-default-zone']: print('public'); sys.exit(0)
where = 'permanent' if '--permanent' in a else 'runtime'
zone = [x.split('=', 1)[1] for x in a if x.startswith('--zone=')][0]
rules = s[where].setdefault(zone, [])
for x in a:
    if x == '--list-all':
        print(zone); [print('  ' + r) for r in rules]; sys.exit(0)
    if x.startswith('--add-rich-rule=') and x.split('=', 1)[1] not in rules: rules.append(x.split('=', 1)[1])
    if x.startswith('--remove-rich-rule=') and x.split('=', 1)[1] in rules: rules.remove(x.split('=', 1)[1])
json.dump(s, open(p, 'w'))
''' % (sys.executable, str(FSTATE)))
FAKE.chmod(0o755)
SERVICE_LOG = W / 'services.log'
os.environ.update(ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(W / 'own'), ZIGMON_FULL_DIR=str(W / 'full'),
                  ZIGMON_CONFIG=str(ETC / 'zigmon' / 'config.json'), ZIGMON_NGINX_CONF=str(NGINX_CONF),
                  ZIGMON_CERT_DIR=str(CERTS), ZIGMON_MOSQ_DIR=str(ETC / 'mosquitto'),
                  ZIGMON_NO_SERVICES='1', ZIGMON_SERVICE_LOG=str(SERVICE_LOG), ZIGMON_FS_ROOT=str(W),
                  ZIGMON_USER='root', ZIGMON_NGINX_TEST='nginx -t -p %s -c %s' % (W, W / 'nginx.conf'),
                  ZIGMON_FIREWALL_CMD=str(FAKE), ZIGMON_FW_FILE4=str(W / 'no4'), ZIGMON_FW_FILE6=str(W / 'no6'),
                  ZIGMON_ROOT_RUN='%s -I %s' % (sys.executable, ROOT_HELPER))
# a release key of the test's own, for the packages
KEYS = W / 'release-keys'
KEYS.mkdir()
rel_key = W / 'release.key'
sh(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', str(rel_key)])
sh(['openssl', 'pkey', '-in', str(rel_key), '-pubout', '-out', str(KEYS / 'zigmon-release-test.pub')])
os.environ.update(ZIGMON_RELEASE_KEYS=str(KEYS), ZIGMON_LIB=str(HERE))

sys.path.insert(0, str(HERE))
sys.argv = ['zigmon']
import zigmon                                           # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(DB), 'api_port': 19973, 'token_file': str(W / 'token'),
                      'pin': '1234', 'plugs': [], 'sensors': [], 'mqtt_host': '', 'log_file': '',
                      'state_dir': str(STATE)})
d = zigmon.Daemon()
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)
CLIENT = '192.168.40.10'


def call(path, body=None, session=None, client=CLIENT, raw=False):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': client}
    if session:
        headers['X-Zigmon-Session'] = session
    req = urllib.request.Request('http://127.0.0.1:19973' + path, headers=headers,
                                 data=None if body is None else json.dumps(body).encode(),
                                 method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
            return r.status, (data if raw else json.loads(data or b'{}'))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}') if not raw else b''


# signed in as an administrator (5.19; it was the PIN), and an operator beside
d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
_c, _u = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})
S = _u.get('token') or ''
_c, _u = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})
S_OP = _u.get('token') or ''


def post(path, body):
    return call(path, dict(body, session=S))


def nginx_ok():
    return sh(['nginx', '-t', '-p', str(W), '-c', str(W / 'nginx.conf')]).returncode == 0


# ---- behind the PIN ---------------------------------------------------------------------
print('behind the PIN')
for road in ('/api/firewall', '/api/tls', '/api/upgrade', '/api/fullbackup'):
    code, _ = call(road)
    check(code == 403, '%s was answered without the PIN (%s)' % (road, code))
    code, _ = call(road, {'action': 'look'})
    check(code == 403, 'a POST to %s went through without the PIN (%s)' % (road, code))
# ...and not to an operator either: root's roads are an administrator's
for road in ('/api/firewall', '/api/tls', '/api/upgrade', '/api/fullbackup', '/api/fullbackup/upload'):
    code, _ = call(road, {'action': 'look'}, session=S_OP)
    check(code == 403, 'an operator went through to %s (%s)' % (road, code))
    code, _ = call(road.replace('/upload', ''), session=S_OP)
    check(code == 403, 'an operator read %s (%s)' % (road, code))
code, fw = call('/api/firewall?fresh=1', session=S)
check(code == 200 and fw.get('from_nginx') is True and fw['access']['sms']['from'] == ['192.168.47.254', '192.168.40.0/24'],
      'the firewall does not start from what nginx says: %r' % (fw.get('access'),))

# ---- who may reach the pages -----------------------------------------------------------------
print('who may reach the pages')
code, got = post('/api/firewall', {'action': 'save', 'on': False, 'off': [], 'rules': [],
                                   'access': {'dashboard': {'any': False, 'from': ['10.0.0.0/8']},
                                              'links': {'any': True}, 'sms': {'any': False, 'from': ['192.168.47.254']}}})
check(code == 400 and 'address you are on now' in got.get('error', ''),
      'a list that shuts out the address the dashboard is used from was saved: %r' % got)
check('10.0.0.0/8' not in NGINX_CONF.read_text(), 'a refused list reached nginx')
code, got = post('/api/firewall', {'action': 'save', 'on': False, 'off': [], 'rules': [],
                                   'access': {'dashboard': {'any': False, 'from': ['192.168.40.0/24', '10.0.0.0/8']},
                                              'links': {'any': False, 'from': ['192.168.43.17']},
                                              'sms': {'any': False, 'from': ['192.168.47.254']}}})
check(code == 200, 'a good list was not saved: %r' % got)
text = NGINX_CONF.read_text()
check('# DASHBOARD-ALLOW-BEGIN' in text and 'allow 10.0.0.0/8;' in text and nginx_ok(),
      'the list did not reach nginx, or nginx does not take it')
code, fw = call('/api/firewall', session=S)
check(fw.get('from_nginx') is False and fw['nodes'][0]['current'] is True,
      'the dashboard does not say the lists are its own and in place: %r' % fw['nodes'][0])

# ---- the firewall -------------------------------------------------------------------------------
print('the firewall')
mine = {'id': 'r1', 'family': 0, 'proto': 'tcp', 'port': '8000-8100', 'source': '203.0.113.0/24',
        'action': 'drop', 'note': 'scanners'}
code, got = post('/api/firewall', {'action': 'rule_check', 'rule': dict(mine, port='70000')})
check(code == 400, 'a port that is not one was taken')
code, got = post('/api/firewall', {'action': 'save', 'on': True, 'off': ['mdns'], 'rules': [mine]})
check(code == 200, 'the firewall was not turned on: %r' % got)
rules = json.loads(FSTATE.read_text())['runtime']['public']
check(rules and 'source address="203.0.113.0/24"' in rules[0] and 'drop' in rules[0],
      'the rule of your own is not first: %r' % rules[:2])
check(any('port port="22"' in r for r in rules) and any('port port="1883"' in r for r in rules)
      and not any('5353' in r for r in rules), 'what the house needs is not in, or mDNS switched off still is')
web = [r for r in rules if 'port port="443"' in r]
check(web and all('source address=' in r for r in web) and any('192.168.40.0/24' in r for r in web)
      and any('192.168.43.17' in r for r in web), 'HTTPS is not let in from the networks of the page lists only: %r' % web)
# one list for everybody: HTTPS from everybody
code, got = post('/api/firewall', {'action': 'save', 'on': True, 'off': ['mdns'], 'rules': [mine],
                                   'access': {'links': {'any': True}}})
web = [r for r in json.loads(FSTATE.read_text())['runtime']['public'] if 'port port="443"' in r]
check(web and not any('source address=' in r for r in web),
      'with the links for everybody, HTTPS is still let in from some networks only: %r' % web)
code, got = post('/api/firewall', {'action': 'save', 'on': True, 'off': [], 'rules': [
    {'family': 4, 'proto': 'tcp', 'port': '443', 'source': '192.168.40.0/24', 'action': 'reject'}]})
check(code == 400 and 'shut out' in got.get('error', ''), 'a REJECT of the caller on 443 was saved: %r' % got)

# ---- the certificate ---------------------------------------------------------------------------
print('the certificate')
ca_key, ca_crt = certificate('rootca', 'House Root CA')
mid_key, mid_crt = certificate('midca', 'House Intermediate CA', ca=(ca_key, ca_crt))
leaf_key, leaf_crt = certificate('leaf', 'mqtt.falco81.net', ca=(mid_key, mid_crt))
mixed = ca_crt.read_text() + leaf_key.read_text() + mid_crt.read_text() + leaf_crt.read_text()
code, got = post('/api/tls', {'action': 'tls_upload', 'cert': mixed})
check(code == 200, 'PEM in any order was not taken: %r' % got)
pem = (CERTS / 'server.pem').read_text()
check(pem.startswith(leaf_crt.read_text().strip()[:60]) and pem.count('BEGIN CERTIFICATE') == 2,
      'server.pem is not the certificate followed by its chain')
check((CERTS / 'server.ca').read_text().count('BEGIN CERTIFICATE') == 2, 'server.ca is not the root and the chain')
code, st = call('/api/tls', session=S)
check(st['now'].get('verify') == 'ok' and st['conf']['managed'] is True and st['node']['current'] is True,
      'the dashboard does not see the new certificate in place: %r' % st.get('node'))
check('HSTS' in json.dumps(st) or st['conf']['hsts'] == 63072000,
      'taking over TLS changed what nginx had (HSTS of two years): %r' % st['conf'])
# a PFX with its password
pfx = W / 'leaf.pfx'
sh(['openssl', 'pkcs12', '-export', '-in', str(leaf_crt), '-inkey', str(leaf_key), '-certfile', str(mid_crt),
    '-out', str(pfx), '-passout', 'pass:s3cret'])
code, got = post('/api/tls', {'action': 'tls_upload', 'pfx': base64.b64encode(pfx.read_bytes()).decode(),
                              'password': 'wrong'})
check(code == 400 and 'password' in got.get('error', ''), 'a PFX opened with a wrong password: %r' % got)
code, got = post('/api/tls', {'action': 'tls_upload', 'pfx': base64.b64encode(pfx.read_bytes()).decode(),
                              'password': 's3cret'})
check(code == 200, 'a PFX with its password was not taken: %r' % got)
# a request made here; only the certificate comes back
code, got = post('/api/tls', {'action': 'tls_csr', 'cn': 'mqtt.falco81.net', 'names': 'mqtt2.falco81.net, 192.0.2.11',
                              'kind': 'ec', 'org': 'Falco', 'country': 'CZ'})
csr = got.get('csr', '')
check(code == 200 and 'CERTIFICATE REQUEST' in csr, 'no request was made: %r' % got)
(W / 'here.csr').write_text(csr)
sh(['openssl', 'x509', '-req', '-in', str(W / 'here.csr'), '-CA', str(mid_crt), '-CAkey', str(mid_key),
    '-CAcreateserial', '-days', '90', '-out', str(W / 'here.crt')])
code, got = post('/api/tls', {'action': 'tls_upload', 'cert': (W / 'here.crt').read_text()})
check(code == 200, 'the certificate for the request made here was not taken without its key: %r' % got)
code, st = call('/api/tls', session=S)
check('pending' not in st['conf'] and st['now'].get('info', {}).get('key', '').startswith('EC'),
      'the waiting key was not used, or the request not cleared: %r' % st['conf'].get('pending'))
check(not (STATE / 'tls' / 'pending.key').exists(), 'the waiting key was left behind')
# the TLS settings
code, got = post('/api/tls', {'action': 'tls_policy', 'preset': 'modern', 'dh': 'none', 'hsts': 31536000})
check(code == 200 and 'ssl_protocols             TLSv1.3;' in NGINX_CONF.read_text() and nginx_ok(),
      'TLS 1.3 only did not reach nginx: %r' % got)
code, got = post('/api/tls', {'action': 'tls_policy', 'preset': 'custom', 'protocols': ['TLSv1.2'],
                              'ciphers': 'NOT-A-CIPHER'})
check(code == 400, 'a cipher list OpenSSL does not know was taken')
code, got = post('/api/tls', {'action': 'tls_selfsigned', 'cn': 'mqtt.falco81.net', 'kind': 'rsa2048', 'days': '30'})
check(code == 200, 'no self-signed certificate: %r' % got)
code, got = post('/api/tls', {'action': 'tls_pem'})
check(code == 200 and 'BEGIN CERTIFICATE' in got.get('pem', '') and 'PRIVATE' not in got.get('pem', ''),
      'the certificate was not handed back, or came with its key')

# ---- put in again by itself -----------------------------------------------------------------------
print('what drifted')
d.store.set_meta('web_access', json.dumps({'dashboard': {'any': True, 'from': []}}))
check(d.root_drift() is True and 'allow all;' in NGINX_CONF.read_text().split('# DASHBOARD-ALLOW-END')[0].split('# DASHBOARD-ALLOW-BEGIN')[1],
      'a wanted list that differs from what is in place was not put in by itself')
check(d.root_drift() is False, 'what is in place was asked for again')
os.environ['ZIGMON_NGINX_TEST'] = 'false'
d.store.set_meta('web_access', json.dumps({'dashboard': {'any': False, 'from': ['192.168.40.0/24']}}))
d.root_drift()
st = d.root_read('status.json')
check(st.get('state') == 'failed', 'nginx refusing did not fail the request')
check(d.root_drift() is False, 'a request root refused was asked for again by itself')
os.environ['ZIGMON_NGINX_TEST'] = 'nginx -t -p %s -c %s' % (W, W / 'nginx.conf')
code, got = post('/api/firewall', {'action': 'retry'})
check(code == 200 and d.root_read('status.json').get('state') == 'done', 'Try again did not try again: %r' % got)

# ---- a backup of the whole installation -----------------------------------------------------------
print('a backup of the whole installation')
code, got = post('/api/fullbackup', {'action': 'make'})
check(code == 200, 'no backup of the whole installation: %r' % got)
code, fb = call('/api/fullbackup?fresh=1', session=S)
names = [x['file'] for x in fb.get('list') or []]
check(names and fb['status'].get('state') == 'done', 'the backup is not listed: %r' % fb)
check(not any('-whole' in x['file'] for x in d.db_backups()), 'the database copy for it shows among the copies')
code, got = post('/api/fullbackup', {'action': 'get', 'file': names[0], 'passphrase': 'short'})
check(code == 400, 'a password of five letters was taken')
code, got = post('/api/fullbackup', {'action': 'get', 'file': names[0], 'passphrase': 'correct horse battery'})
code, fb = call('/api/fullbackup', session=S)
ready = (fb.get('ready') or {}).get('file')
check(ready and ready.endswith('.enc'), 'the copy was not handed over: %r' % fb.get('status'))
code, data = call('/api/fullbackup/download?file=%s' % ready, session=S, raw=True)
check(code == 200 and data[:8] == b'Salted__', 'the download is not the copy locked with its password')
check(not (STATE / 'root' / 'out' / ready).exists(), 'the copy handed over stayed behind after its download')
code, _ = call('/api/fullbackup/download?file=%s' % ready, raw=True)
check(code == 403, 'a download went out without the PIN')
# sent back in pieces
blob = base64.b64encode(data).decode()
step = 40000
pieces = [blob[i:i + step] for i in range(0, len(blob), step)]
# base64 cut at a multiple of four keeps each piece decodable
pieces = [blob[i:i + 40000] for i in range(0, len(blob), 40000)]
for n, piece in enumerate(pieces):
    code, got = post('/api/fullbackup/upload', {'part': n + 1, 'of': len(pieces), 'data': piece,
                                               'upload_id': 'up1', 'passphrase': 'correct horse battery'})
check(code == 200, 'the copy was not taken back in: %r' % got)
st = d.root_read('status.json')
check(st.get('state') == 'done' and (st.get('inspected') or {}).get('trusted') is True,
      'the copy sent back is not recognised as this machine\'s: %r' % st)
uploaded = (st.get('inspected') or {}).get('file')
(ETC / 'zigmon' / 'config.json').write_text(json.dumps({'db_file': str(DB), 'pin': '0000'}))
code, got = post('/api/fullbackup', {'action': 'restore', 'file': uploaded, 'parts': ['config']})
check(code == 200 and d.root_read('status.json').get('state') == 'done'
      and '"1234"' in (ETC / 'zigmon' / 'config.json').read_text(), 'the configuration was not put back: %r'
      % d.root_read('status.json').get('said'))
# an apply asked after it - the drift, once the restore restarted the daemon - must
# not hide how the restore ended from the page waiting for it
restored = d.root_read('status.json').get('id')
post('/api/firewall', {'action': 'retry'})
code, fb = call('/api/fullbackup', session=S)
check(d.root_read('status.json').get('kind') == 'apply' and fb['status'].get('id') == restored
      and fb['status'].get('state') == 'done', 'an apply after a restore hid how it ended: %r' % fb.get('status'))
# while root works on a request, nothing else is asked behind its back
(STATE / 'root' / 'request.taken').write_text('{}')
check(bool(d.root_busy()), 'root working on a request does not count as busy')
(STATE / 'root' / 'request.taken').unlink()
code, got = post('/api/fullbackup', {'action': 'restore', 'file': '../../etc/passwd', 'parts': ['config']})
check(code == 400, 'a file name that is not a backup reached root')

# ---- a new version -----------------------------------------------------------------------------------
print('a new version')


def package(version, folder):
    top = 'zigmon-%s' % version
    dd = W / folder / top
    dd.mkdir(parents=True)
    (dd / 'zigmon.py').write_text("__version__ = '%s'\n" % version)
    (dd / 'install.sh').write_text('#!/bin/bash\nexit 0\n')
    (dd / 'README.md').write_text('%s — a test.\n' % version)
    lines = ['%s  %s' % (hashlib.sha256((dd / n).read_bytes()).hexdigest(), n) for n in sorted(['README.md', 'install.sh', 'zigmon.py'])]
    (dd / 'MANIFEST').write_text('\n'.join(lines) + '\n')
    sh(['openssl', 'pkeyutl', '-sign', '-inkey', str(rel_key), '-rawin', '-in', str(dd / 'MANIFEST'),
        '-out', str(dd / 'MANIFEST.sig')])
    out = W / folder / (top + '.tar.gz')
    with tarfile.open(out, 'w:gz') as t:
        t.add(dd, arcname=top)
    return out


def send(pkg):
    blob = base64.b64encode(pkg.read_bytes()).decode()
    pieces = [blob[i:i + 40000] for i in range(0, len(blob), 40000)] or ['']
    got = {}
    for n, piece in enumerate(pieces):
        code, got = post('/api/upgrade/upload', {'part': n + 1, 'of': len(pieces), 'data': piece,
                                                'upload_id': 'p%d' % len(pkg.name)})
        if code != 200:
            return code, got
    return 200, got


code, got = send(package('1.0.0', 'old'))
check(code == 400 and 'older than' in got.get('error', ''), 'a version older than this one was taken: %r' % got)
code, got = send(package('99.0.0', 'new'))
check(code == 200 and (got.get('package') or {}).get('version') == '99.0.0'
      and got['package'].get('signed_by') == 'zigmon-release-test', 'a signed newer version was not taken: %r' % got)
code, st = call('/api/upgrade', session=S)
check(st.get('package', {}).get('version') == '99.0.0' and 'a test' in st['package'].get('changelog', ''),
      'the package and what changed in it are not shown: %r' % st.get('package'))
check(st.get('ready') is False and st.get('helper') is False,
      'with no zigmon-upgrade.path here the upgrade was offered anyway')
os.environ['ZIGMON_UPGRADE_RUN'] = 'true'
code, got = post('/api/upgrade', {'action': 'start'})
check(code == 200 and (STATE / 'upgrade' / 'request.json').exists(), 'the upgrade was not asked for: %r' % got)
req = json.loads((STATE / 'upgrade' / 'request.json').read_text())
check(req.get('sha') == hashlib.sha256((STATE / 'upgrade' / 'zigmon-99.0.0.tar.gz').read_bytes()).hexdigest(),
      'the request does not name the package by its SHA-256')
code, got = post('/api/upgrade', {'action': 'start'})
check(code == 400, 'a second upgrade was started over the first')
code, got = post('/api/upgrade', {'action': 'forget'})
check(code == 400, 'the package was thrown away while it was being put in')

# ---- the certificate running out ----------------------------------------------------------------------
# an upgrade asked for that nothing took in half an hour does not stand in the
# way of every later one
stale = STATE / 'upgrade' / 'request.json'
stale.write_text('{}')
os.utime(str(stale), (time.time() - 4000, time.time() - 4000))
check(d.upgrade_state()['asked'] is False and not stale.exists(),
      'an upgrade request nothing took blocks every later upgrade')
# pieces of an upload left behind are cleared after an hour
left = STATE / 'root' / 'in' / '.upload-gone.part'
left.write_bytes(b'x' * 10)
os.utime(str(left), (time.time() - 4000, time.time() - 4000))
d.full_tidy()
check(not left.exists(), 'the pieces of an upload that never finished stay for ever')

print('the certificate running out')
look = d.root_read('look.json')
look['tls']['info']['not_after'] = int(time.time() + 5 * 86400)
(STATE / 'root' / 'look.json').write_text(json.dumps(look))
told = []
_was = d.notify
d.notify = lambda words, level='info', **k: told.append((words, level, k.get('about')))
d.check_certificate()
d.check_certificate()
d.notify = _was
check(len(told) == 1 and told[0][2] == 'certificate' and told[0][1] == 'crit' and 'broker' in told[0][0],
      'a certificate with five days left was not said once, as critical, with the broker: %r' % told)

shutil.rmtree(W, ignore_errors=True)
if bad:
    print('\n%d check(s) failed' % len(bad))
    sys.stdout.flush()
    os._exit(1)
print('the dashboard asks root for what only root can do, and only that')
sys.stdout.flush()
os._exit(0)
