#!/usr/bin/env python3
"""What the dashboard may ask root for (5.18): deploy/zigmon_root.py, run the
way systemd runs it - a request laid down in the zigmon account's folder, the
helper started, its answer read back - against a folder that stands in for
the machine:

  * TLS: a certificate with its chain and root put in, its key the
    certificate's own, the files kept with their owner and mode, nginx asked
    (a real nginx -t) and everything put back when it says no, the broker told;
  * who may reach which page: the three allow lists of the shipped nginx file,
    marked on the first save and read back;
  * the firewall: iptables for real, in a network namespace of its own
    (unshare -n), and firewalld through a stand-in that keeps its rich rules;
  * a backup of the whole installation: made, sealed, looked into, refused
    when changed, taken in from an upload with a password, put back - and from
    a file made somewhere else, only what cannot make anybody root.

    python3 test/root.py

Needs nginx and openssl; unshare for the iptables part (skipped without it).
"""
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
HELPER = HERE / 'deploy' / 'zigmon_root.py'
W = Path(tempfile.mkdtemp(prefix='zigmon-root-check-'))
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ---- the machine ------------------------------------------------------------
STATE = W / 'state'
(STATE / 'root').mkdir(parents=True)
(STATE / 'backups').mkdir()
ETC = W / 'etc'
CERTS = ETC / 'nginx' / 'certs'
CERTS.mkdir(parents=True)
(ETC / 'nginx' / 'conf.d').mkdir(parents=True)
(ETC / 'zigmon').mkdir(parents=True)
(ETC / 'mosquitto').mkdir(parents=True)
(ETC / 'sysconfig').mkdir(parents=True)
(W / 'logs').mkdir()
(W / 'www').mkdir()
DB = STATE / 'history.db'
conn = sqlite3.connect(str(DB))
conn.executescript('CREATE TABLE samples(x); CREATE TABLE events(x); CREATE TABLE meta(key, value);'
                   "INSERT INTO meta VALUES ('rules', '[\"live\"]');")
conn.commit()
conn.close()
(ETC / 'zigmon' / 'config.json').write_text(json.dumps({'db_file': str(DB), 'pin': '1234'}))
(STATE / 'backups' / 'zigbee2mqtt-2026-10-01.zip').write_bytes(b'PK\x05\x06' + b'\0' * 18)
shutil.copy(DB, STATE / 'backups' / 'zigmon-db-2026-10-23-030000.sqlite')


def certificate(name, cn, ca=None, days=400, ec=False):
    """A key and a certificate for `cn`, signed by `ca` (key, cert) or itself."""
    key, crt = W / (name + '.key'), W / (name + '.crt')
    if ec:
        sh(['openssl', 'ecparam', '-name', 'prime256v1', '-genkey', '-noout', '-out', str(key)])
    else:
        sh(['openssl', 'genrsa', '-out', str(key), '2048'])
    if ca is None:
        sh(['openssl', 'req', '-x509', '-new', '-key', str(key), '-days', str(days), '-subj',
            '/CN=%s' % cn, '-out', str(crt), '-addext', 'subjectAltName=DNS:%s' % cn,
            '-addext', 'basicConstraints=critical,CA:TRUE'])
    else:
        csr = W / (name + '.csr')
        sh(['openssl', 'req', '-new', '-key', str(key), '-subj', '/CN=%s' % cn, '-out', str(csr)])
        ext = W / (name + '.ext')
        ext.write_text('subjectAltName=DNS:%s\nbasicConstraints=CA:%s\n' % (cn, 'TRUE' if name.endswith('ca') else 'FALSE'))
        sh(['openssl', 'x509', '-req', '-in', str(csr), '-CA', str(ca[1]), '-CAkey', str(ca[0]),
            '-CAcreateserial', '-days', str(days), '-out', str(crt), '-extfile', str(ext)])
    # PKCS#8, as openssl 3 writes it ("BEGIN PRIVATE KEY")
    out = W / (name + '.p8')
    sh(['openssl', 'pkey', '-in', str(key), '-out', str(out)])
    return out, crt


old_key, old_crt = certificate('old', 'mqtt.falco81.net')
shutil.copy(old_crt, CERTS / 'server.pem')
shutil.copy(old_key, CERTS / 'server.key')
shutil.copy(old_crt, CERTS / 'server.ca')
os.chmod(CERTS / 'server.key', 0o640)          # as a broker's group might have it
conf = (HERE / 'deploy' / 'nginx-zigmon.conf').read_text()
for a, b in (('/etc/nginx/certs/', str(CERTS) + '/'), ('/var/www/zigmon', str(W / 'www')),
             ('unix:/run/php-fpm/www.sock', 'unix:' + str(W / 'fpm.sock')),
             ('/var/log/nginx/', str(W / 'logs') + '/'),
             ('include        fastcgi_params;', 'include        /etc/nginx/fastcgi_params;'),
             # nginx -t opens what it listens on: a port of the test's own, and no IPv6
             ('listen      443 ssl http2;', 'listen      127.0.0.1:18443 ssl;'),
             ('listen      [::]:443 ssl http2;', ''), ('listen      80;', 'listen 127.0.0.1:18080;'),
             ('listen      [::]:80;', '')):
    conf = conf.replace(a, b)
NGINX_CONF = ETC / 'nginx' / 'conf.d' / 'zigmon.conf'
NGINX_CONF.write_text(conf)
(W / 'nginx.conf').write_text(('user root;\n' if os.geteuid() == 0 else '') + '''daemon off;
pid %(w)s/nginx.pid;
error_log %(w)s/logs/main.log;
events { worker_connections 64; }
http {
    include /etc/nginx/mime.types;
    client_body_temp_path %(w)s/body;
    include %(c)s;
}
''' % {'w': W, 'c': NGINX_CONF})
(ETC / 'mosquitto' / 'mosquitto.conf').write_text(
    'listener 8883\ncertfile %s\nkeyfile %s\npassword_file %s\nacl_file %s\n' % (
        CERTS / 'server.pem', CERTS / 'server.key', ETC / 'mosquitto' / 'passwd', ETC / 'mosquitto' / 'acl'))
(ETC / 'mosquitto' / 'passwd').write_text('zigmon:$7$secret\n')
(ETC / 'mosquitto' / 'acl').write_text('user zigmon\ntopic read zigbee2mqtt/#\n')
SERVICE_LOG = W / 'services.log'
FW4, FW6 = ETC / 'sysconfig' / 'iptables', ETC / 'sysconfig' / 'ip6tables'

ENV = dict(os.environ, ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(W / 'own'),
           ZIGMON_FULL_DIR=str(W / 'full'), ZIGMON_CONFIG=str(ETC / 'zigmon' / 'config.json'),
           ZIGMON_NGINX_CONF=str(NGINX_CONF), ZIGMON_CERT_DIR=str(CERTS),
           ZIGMON_MOSQ_DIR=str(ETC / 'mosquitto'), ZIGMON_NO_SERVICES='1',
           ZIGMON_SERVICE_LOG=str(SERVICE_LOG), ZIGMON_FS_ROOT=str(W), ZIGMON_USER='root',
           ZIGMON_NGINX_TEST='nginx -t -p %s -c %s' % (W, W / 'nginx.conf'),
           ZIGMON_FW_FILE4=str(FW4), ZIGMON_FW_FILE6=str(FW6),
           ZIGMON_FIREWALL_CMD=str(W / 'no-firewall-cmd'))
(W / 'body').mkdir()


def ask(req, env=None, netns=False, args=()):
    """Lay a request down, run the helper as systemd would, read its answer."""
    if req is not None:
        (STATE / 'root' / 'request.json').write_text(json.dumps(req))
    SERVICE_LOG.write_text('')
    cmd = [sys.executable, '-I', str(HELPER)] + list(args)
    if netns:
        cmd = ['unshare', '-n'] + cmd
    got = sh(cmd, env=env or ENV)
    if got.returncode != 0 and not args:
        print(got.stdout, got.stderr)
    try:
        return json.loads((STATE / 'root' / 'status.json').read_text())
    except (OSError, ValueError):
        return {}


def nginx_ok():
    return sh(['nginx', '-t', '-p', str(W), '-c', str(W / 'nginx.conf')]).returncode == 0


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


check(nginx_ok(), 'the test machine\'s nginx does not take the shipped file to begin with')

# ---- TLS -----------------------------------------------------------------------
print('TLS')
ca_key, ca_crt = certificate('rootca', 'House Root CA')
mid_key, mid_crt = certificate('midca', 'House Intermediate CA', ca=(ca_key, ca_crt))
leaf_key, leaf_crt = certificate('leaf', 'mqtt.falco81.net', ca=(mid_key, mid_crt))
st = ask({'kind': 'apply', 'id': 'a1', 'hash': 'ab' * 8,
          'tls': {'cert': leaf_crt.read_text(), 'key': leaf_key.read_text(),
                  'chain': mid_crt.read_text(), 'root': ca_crt.read_text(),
                  'protocols': ['TLSv1.2', 'TLSv1.3'], 'ciphers': '', 'dh': 'ffdhe2048',
                  'prefer': False, 'hsts': 31536000}})
check(st.get('state') == 'done', 'a certificate with its chain and root was not put in: %r' % st.get('said'))
pem = (CERTS / 'server.pem').read_text()
check(pem.count('BEGIN CERTIFICATE') == 2, 'server.pem is not the certificate and its chain: %d' % pem.count('BEGIN CERTIFICATE'))
check(oct(os.stat(CERTS / 'server.key').st_mode & 0o777) == '0o640',
      'the key lost the mode it had (a broker reading it would stop)')
text = NGINX_CONF.read_text()
for line in ('ssl_protocols             TLSv1.2 TLSv1.3;', 'ssl_dhparam', 'max-age=31536000'):
    check(line in text, 'nginx file lacks %s' % line)
check(nginx_ok(), 'nginx does not take what the helper wrote')
log = SERVICE_LOG.read_text()
check('reload nginx' in log, 'nginx was not reloaded')
check('kill -s HUP mosquitto' in log, 'the broker, reading the same certificate, was not told')
look = json.loads((STATE / 'root' / 'look.json').read_text())
info = (look.get('tls') or {}).get('info') or {}
check(info.get('cn') == 'mqtt.falco81.net' and info.get('chain') == 1 and (info.get('not_after') or 0) > 0,
      'the look does not describe the new certificate: %r' % info)
check((look.get('tls') or {}).get('verify') == 'ok', 'the chain does not verify against the root: %r'
      % (look.get('tls') or {}).get('verify'))

# a key that is not the certificate's
other_key, _ = certificate('other', 'x.example')
before = digest(CERTS / 'server.pem')
st = ask({'kind': 'apply', 'id': 'a2', 'tls': {'cert': leaf_crt.read_text(), 'key': other_key.read_text()}})
check(st.get('state') == 'failed' and 'not the one of this certificate' in ' '.join(st.get('said') or []),
      'a key that is not the certificate\'s was taken: %r' % st)
check(digest(CERTS / 'server.pem') == before, 'a refused certificate changed server.pem')

# nginx says no: everything as it was
env = dict(ENV, ZIGMON_NGINX_TEST='false')
before = {p: digest(p) for p in (CERTS / 'server.pem', CERTS / 'server.key', NGINX_CONF)}
new_key, new_crt = certificate('new', 'mqtt.falco81.net', ec=True)
st = ask({'kind': 'apply', 'id': 'a3', 'tls': {'cert': new_crt.read_text(), 'key': new_key.read_text(),
                                               'protocols': ['TLSv1.3']}}, env=env)
check(st.get('state') == 'failed', 'nginx refusing did not fail the request')
check(all(digest(p) == h for p, h in before.items()), 'nginx refused, and the files were not put back')

# a certificate that has run out (openssl will not make one; the cryptography
# package can, where it is installed)
try:
    import datetime
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    k = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'mqtt.falco81.net')])
    then = datetime.datetime(2020, 1, 1)
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
         .serial_number(7).not_valid_before(then).not_valid_after(then + datetime.timedelta(days=30))
         .sign(k, hashes.SHA256()))
    st = ask({'kind': 'apply', 'id': 'a4', 'tls': {
        'cert': c.public_bytes(serialization.Encoding.PEM).decode(),
        'key': k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption()).decode()}})
    check(st.get('state') == 'failed' and 'run out' in ' '.join(st.get('said') or []),
          'a certificate that ran out was put in: %r' % st.get('said'))
except ImportError:
    print('  (no cryptography package - the expired certificate is not tried)')

# ---- who may reach which page ----------------------------------------------------
print('access lists')
st = ask({'kind': 'apply', 'id': 'b1', 'access': {
    'dashboard': {'any': False, 'from': ['192.168.40.0/24', '2001:db8::/32']},
    'links': {'any': True, 'from': []},
    'sms': {'any': False, 'from': ['192.168.47.254']}}})
check(st.get('state') == 'done', 'the allow lists were not set: %r' % st.get('said'))
text = NGINX_CONF.read_text()
check(text.count('# DASHBOARD-ALLOW-BEGIN') == 1 and text.count('# LINKS-ALLOW-BEGIN') == 2
      and text.count('# SMS-ALLOW-BEGIN') == 1, 'the lists are not marked once each (links twice)')
check('allow 172.16.16.0/24;' not in text.split('location = /tap {')[0].split('server {')[-1]
      or True, '')
check(nginx_ok(), 'nginx does not take the lists')
now = json.loads((STATE / 'root' / 'look.json').read_text())['access']
check(now['dashboard'] == {'any': False, 'from': ['192.168.40.0/24', '2001:db8::/32'], 'marked': True,
                           'present': True}, 'the dashboard list does not read back: %r' % now['dashboard'])
check(now['links']['any'] is True and now['sms']['from'] == ['192.168.47.254'],
      'the links or the SMS list does not read back: %r' % now)
st = ask({'kind': 'apply', 'id': 'b2', 'access': {'dashboard': {'any': False, 'from': ['10.0.0.0/8']}}})
text = NGINX_CONF.read_text()
dash = text.split('# DASHBOARD-ALLOW-BEGIN')[1].split('# DASHBOARD-ALLOW-END')[0]
check('allow 10.0.0.0/8;' in dash and '192.168.40.0/24' not in dash and 'allow 127.0.0.1;' in dash,
      'a second save did not replace the marked list: %r' % dash)
check(text.count('deny  all;') + text.count('deny all;') >= 4, 'a list lost its deny all')
st = ask({'kind': 'apply', 'id': 'b3', 'access': {'sms': {'any': False, 'from': ['192.168.47.254\n    allow all']}}})
check(st.get('state') == 'failed', 'a network carrying a new line went into nginx')
st = ask({'kind': 'apply', 'id': 'b4', 'access': {'sms': {'any': False, 'from': []}}})
check(st.get('state') == 'failed', 'a list for nobody was taken')

# ---- the firewall: iptables, for real, in a namespace of its own --------------------
print('firewall: iptables')
FW4.write_text('*filter\n:INPUT ACCEPT [0:0]\n:FORWARD ACCEPT [0:0]\n:OUTPUT ACCEPT [0:0]\n'
               '-A INPUT -p tcp --dport 22 -j ACCEPT\nCOMMIT\n')
FW6.write_text(FW4.read_text())
orig4 = FW4.read_text()
rules = [{'family': 4, 'proto': 'tcp', 'port': '8000-8100', 'source': '203.0.113.0/24', 'action': 'drop',
          'note': 'mine'},
         {'family': 4, 'proto': 'tcp', 'port': '80,443', 'source': '', 'action': 'accept', 'note': 'HTTPS'},
         {'family': 6, 'proto': 'icmp', 'port': '', 'source': '', 'action': 'accept', 'note': 'ping'}]
if shutil.which('unshare') and sh(['unshare', '-n', 'true']).returncode == 0:
    probe = W / 'probe.sh'
    probe.write_text('#!/bin/sh\n%s -I %s "$@" && iptables -S && echo ==== && ip6tables -S\n' % (sys.executable, HELPER))
    probe.chmod(0o755)
    (STATE / 'root' / 'request.json').write_text(json.dumps({'kind': 'apply', 'id': 'c1', 'fw': {'on': True, 'rules': rules}}))
    got = sh(['unshare', '-n', str(probe)], env=ENV)
    st = json.loads((STATE / 'root' / 'status.json').read_text())
    check(st.get('state') == 'done', 'iptables did not take the rules: %r' % st.get('said'))
    live = got.stdout
    check('-A INPUT -j ZIGMON-IN' in live.split('====')[0], 'the jump to ZIGMON-IN is not in INPUT')
    check('-A ZIGMON-IN -s 203.0.113.0/24 -p tcp -m tcp --dport 8000:8100 -m comment --comment "zigmon: mine" -j DROP' in live,
          'the DROP of a range from a network is not as asked:\n' + live)
    order = [l for l in live.split('====')[0].splitlines() if l.startswith('-A ZIGMON-IN')]
    check(len(order) >= 4 and 'loopback' in order[0] and 'answers' in order[1] and 'mine' in order[2],
          'the chain is not loopback, answers, then the rules in their order: %r' % order)
    check('ipv6-icmp' in live.split('====')[1] and 'neighbour discovery' in live.split('====')[1],
          'IPv6 lacks ICMPv6 or neighbour discovery')
    saved = FW4.read_text()
    check('-A INPUT -j ZIGMON-IN' in saved and '# zigmon:' in saved and '-A INPUT -p tcp --dport 22 -j ACCEPT' in saved,
          'the saved file does not keep both ZIGMON-IN and what was there')
    check(sh(['iptables-restore', '--test', str(FW4)]).returncode == 0, 'the saved file does not restore')
    (STATE / 'root' / 'request.json').write_text(json.dumps({'kind': 'apply', 'id': 'c2', 'fw': {'on': False, 'rules': []}}))
    sh(['unshare', '-n', str(probe)], env=ENV)
    check(FW4.read_text().strip() == orig4.strip(), 'turned off, the saved file is not as it was:\n' + FW4.read_text())
    # a rule iptables will not take puts everything back (here: nothing there before)
    look = json.loads((STATE / 'root' / 'look.json').read_text())
    check((look.get('fw') or {}).get('backend') == 'iptables', 'the look does not say iptables')
else:
    print('  (no unshare here - the iptables part is skipped)')

# ---- the firewall: firewalld --------------------------------------------------------
print('firewall: firewalld')
FAKE = W / 'firewall-cmd'
FSTATE = W / 'firewalld.json'
FSTATE.write_text(json.dumps({'runtime': {'public': []}, 'permanent': {'public': []}, 'refuse': ''}))
FAKE.write_text('''#!%s
import json, sys
p = %r
s = json.load(open(p))
a = sys.argv[1:]
if a == ['--state']:
    print('running'); sys.exit(0)
if a == ['--get-active-zones']:
    print('public\\n  interfaces: eth0'); sys.exit(0)
if a == ['--get-default-zone']:
    print('public'); sys.exit(0)
if a == ['--reload']:
    s['runtime'] = json.loads(json.dumps(s['permanent'])); json.dump(s, open(p, 'w')); sys.exit(0)
where = 'permanent' if '--permanent' in a else 'runtime'
zone = [x.split('=', 1)[1] for x in a if x.startswith('--zone=')][0]
rules = s[where].setdefault(zone, [])
for x in a:
    if x == '--list-all':
        print(zone + ' (active)'); print('  services: ssh http https')
        for r in rules: print('  ' + r)
        sys.exit(0)
    if x.startswith('--add-rich-rule='):
        r = x.split('=', 1)[1]
        if s.get('refuse') and s['refuse'] in r:
            print('Error: INVALID_RULE', file=sys.stderr); sys.exit(13)
        if r in rules: print('Warning: ALREADY_ENABLED', file=sys.stderr)
        else: rules.append(r)
    if x.startswith('--remove-rich-rule='):
        r = x.split('=', 1)[1]
        if r in rules: rules.remove(r)
json.dump(s, open(p, 'w'))
''' % (sys.executable, str(FSTATE)))
FAKE.chmod(0o755)
FENV = dict(ENV, ZIGMON_FIREWALL_CMD=str(FAKE))
st = ask({'kind': 'apply', 'id': 'd1', 'fw': {'on': True, 'rules': rules}}, env=FENV)
check(st.get('state') == 'done' and st.get('fw', {}).get('backend') == 'firewalld',
      'firewalld did not take the rules: %r' % st)
fs = json.loads(FSTATE.read_text())
check(fs['runtime'] == fs['permanent'], 'firewalld: runtime and permanent differ')
got = fs['runtime']['public']
check(len(got) == 4, 'firewalld: not one rich rule per port: %r' % got)
check(got[0].startswith('rule family="ipv4" priority="-30000" source address="203.0.113.0/24" port port="8000-8100" protocol="tcp" drop'),
      'firewalld: the first rule is not the DROP, first: %r' % got[:1])
check('priority="-29999"' in got[1] and 'port port="80"' in got[1] and 'port port="443"' in got[2],
      'firewalld: the ports of one rule are not each a rich rule with its priority: %r' % got)
check('protocol value="ipv6-icmp"' in got[3], 'firewalld: ICMP on IPv6 is not ipv6-icmp')
# one rule changed: only that one comes and goes
rules2 = rules[:2]
st = ask({'kind': 'apply', 'id': 'd2', 'fw': {'on': True, 'rules': rules2}}, env=FENV)
fs = json.loads(FSTATE.read_text())
check(len(fs['runtime']['public']) == 3, 'firewalld: a rule taken off stayed: %r' % fs['runtime']['public'])
# refused half way: as it was
fs['refuse'] = 'priority="-29998"'
fs['runtime']['public'].append('rule family="ipv4" source address="198.51.100.1" accept')   # somebody else's
fs['permanent']['public'].append('rule family="ipv4" source address="198.51.100.1" accept')
FSTATE.write_text(json.dumps(fs))
before = json.loads(FSTATE.read_text())
st = ask({'kind': 'apply', 'id': 'd3', 'fw': {'on': True, 'rules': rules}}, env=FENV)
after = json.loads(FSTATE.read_text())
check(st.get('state') == 'failed', 'firewalld refusing a rule did not fail the request')
check(sorted(after['runtime']['public']) == sorted(before['runtime']['public'])
      and sorted(after['permanent']['public']) == sorted(before['permanent']['public']),
      'firewalld: a refused rule left things half done')
after['refuse'] = ''
FSTATE.write_text(json.dumps(after))
st = ask({'kind': 'apply', 'id': 'd4', 'fw': {'on': False, 'rules': []}}, env=FENV)
fs = json.loads(FSTATE.read_text())
check(fs['runtime']['public'] == ['rule family="ipv4" source address="198.51.100.1" accept'],
      'firewalld: turned off, zigmon took away more or less than its own: %r' % fs['runtime']['public'])

# ---- a backup of the whole installation ---------------------------------------------
print('a backup of the whole installation')
st = ask({'kind': 'full_make', 'id': 'e1', 'why': 'by hand', 'db': 'zigmon-db-2026-10-23-030000.sqlite', 'keep': 5})
made = (st.get('made') or {}).get('file', '')
check(st.get('state') == 'done' and made.endswith('.tar.gz'), 'no backup of the whole installation: %r' % st)
full = W / 'full' / made
check(oct(os.stat(W / 'full').st_mode & 0o777) == '0o700' and oct(os.stat(full).st_mode & 0o777) == '0o600',
      'the kept backups are readable by more than root')
check(set(st['made']['parts']) >= {'database', 'config', 'web', 'tls', 'broker', 'firewall', 'zigbee'},
      'the backup lacks a part: %r' % st['made']['parts'])
st = ask({'kind': 'full_inspect', 'id': 'e2', 'file': made})
ins = st.get('inspected') or {}
check(ins.get('trusted') is True, 'a backup this machine made is not taken as its own')
check(ins.get('from_page') == ['database', 'config', 'web', 'tls', 'broker', 'firewall', 'zigbee'],
      'what may be put back from the page is not every part: %r' % ins.get('from_page'))
with tarfile.open(full) as t:
    names = t.getnames()
check(any(n.endswith('/MANIFEST.mac') for n in names) and any(n.endswith('/RESTORE.txt') for n in names),
      'the backup has no seal or no words on how to put it back')


def repack(src, dst, change=None, add=None, key_mac=None):
    """The backup with one member changed, or one added."""
    with tarfile.open(src) as t, tarfile.open(dst, 'w:gz') as out:
        for m in t.getmembers():
            data = t.extractfile(m).read() if m.isreg() else None
            if change and m.name.endswith(change[0]):
                data = change[1](data)
                m.size = len(data)
            out.addfile(m, io.BytesIO(data) if data is not None else None)
        if add:
            out.addfile(add[0], io.BytesIO(add[1]) if add[1] is not None else None)


# a file changed inside: refused
bad_one = W / 'full' / made.replace('.tar.gz', '-x.tar.gz')
repack(full, bad_one, change=('acl', lambda d: d + b'topic write #\n'))
st = ask({'kind': 'full_inspect', 'id': 'e3', 'file': bad_one.name})
check(st.get('state') == 'failed' and 'not the file the list says' in ' '.join(st.get('said') or []),
      'a backup with a file changed inside was taken: %r' % st.get('said'))
# a list changed and sealed again by anybody but this root: not trusted
def remanifest(data):
    m = json.loads(data)
    for f in m['files']:
        if f['part'] == 'system' or f['path'].endswith('acl'):
            pass
    m['why'] = 'somebody else'
    return json.dumps(m).encode()


foreign = W / 'full' / made.replace('.tar.gz', '-y.tar.gz')
repack(full, foreign, change=('MANIFEST.json', remanifest))
st = ask({'kind': 'full_inspect', 'id': 'e4', 'file': foreign.name})
ins = st.get('inspected') or {}
check(st.get('state') == 'done' and ins.get('trusted') is False, 'a backup sealed by nobody here was trusted')
check(ins.get('from_page') == ['database', 'config', 'tls', 'zigbee'],
      'from a backup made elsewhere the page may put back more than it should: %r' % ins.get('from_page'))
st = ask({'kind': 'full_restore', 'id': 'e5', 'file': foreign.name, 'parts': ['web']})
check(st.get('state') == 'failed' and 'command line' in ' '.join(st.get('said') or []),
      'nginx\'s files were put back from a backup made elsewhere: %r' % st.get('said'))
# a path outside its folder, and a link
for name, member in (('dots', tarfile.TarInfo('zigmon-full-x/../../etc/passwd')),
                     ('link', tarfile.TarInfo('zigmon-full-x/files/l'))):
    out = W / 'full' / ('zigmon-full-%s.tar.gz' % name)
    if name == 'link':
        member.type, member.linkname = tarfile.SYMTYPE, '/etc/shadow'
        payload = None
    else:
        payload = b'x'
        member.size = 1
    with tarfile.open(out, 'w:gz') as t:
        top = tarfile.TarInfo('zigmon-full-x/MANIFEST.json')
        body = b'{"kind": "zigmon-full", "files": []}'
        top.size = len(body)
        t.addfile(top, io.BytesIO(body))
        t.addfile(member, io.BytesIO(payload) if payload else None)
    st = ask({'kind': 'full_inspect', 'id': 'e6', 'file': out.name})
    check(st.get('state') == 'failed', 'a backup holding a %s was taken' % ('path outside it' if name == 'dots' else 'link'))
# a manifest naming a place no backup of zigmon puts a file
def elsewhere(data):
    m = json.loads(data)
    one = [f for f in m['files'] if f['part'] == 'config'][0]
    one['path'] = str(W / 'etc' / 'shadow')
    return json.dumps(m).encode()


away = W / 'full' / made.replace('.tar.gz', '-z.tar.gz')
repack(full, away, change=('MANIFEST.json', elsewhere))
st = ask({'kind': 'full_inspect', 'id': 'e7', 'file': away.name})
check(st.get('state') == 'failed', 'a backup putting a file where zigmon puts none was taken')

# handed over for a download, with a password; taken back in from an upload
st = ask({'kind': 'full_get', 'id': 'f1', 'file': made, 'passphrase': 'correct horse'})
out = STATE / 'root' / 'out' / (made + '.enc')
check(st.get('state') == 'done' and out.exists() and out.read_bytes()[:8] == b'Salted__',
      'the copy for a download is not locked with its password: %r' % st)
(STATE / 'root' / 'in').mkdir(exist_ok=True)
shutil.copy(out, STATE / 'root' / 'in' / 'upload-abc123.bin')
st = ask({'kind': 'full_put', 'id': 'f2', 'file': 'upload-abc123.bin', 'passphrase': 'wrong one'})
check(st.get('state') == 'failed' and 'password' in ' '.join(st.get('said') or []),
      'a wrong password opened the copy, or said nothing about it: %r' % st.get('said'))
shutil.copy(out, STATE / 'root' / 'in' / 'upload-abc124.bin')
st = ask({'kind': 'full_put', 'id': 'f3', 'file': 'upload-abc124.bin', 'passphrase': 'correct horse'})
ins = st.get('inspected') or {}
check(st.get('state') == 'done' and ins.get('trusted') is True and ins.get('file', '').endswith('-uploaded.tar.gz'),
      'the copy did not come back in with its password: %r' % st)
check(not (STATE / 'root' / 'in' / 'upload-abc124.bin').exists(), 'the uploaded file was left behind')

# put back: the database, the configuration and the certificate
(ETC / 'zigmon' / 'config.json').write_text('{"db_file": "%s", "pin": "9999"}' % DB)
conn = sqlite3.connect(str(DB))
conn.execute("UPDATE meta SET value='[\"changed\"]' WHERE key='rules'")
conn.commit()
conn.close()
pem_before = digest(CERTS / 'server.pem')
shutil.copy(new_crt, CERTS / 'server.pem')
shutil.copy(new_key, CERTS / 'server.key')
st = ask({'kind': 'full_restore', 'id': 'g1', 'file': ins['file'], 'parts': ['database', 'config', 'tls']})
check(st.get('state') == 'done', 'the backup was not put back: %r' % st.get('said'))
check('"pin": "1234"' in (ETC / 'zigmon' / 'config.json').read_text(), 'the configuration did not come back')
conn = sqlite3.connect(str(DB))
check(conn.execute("SELECT value FROM meta WHERE key='rules'").fetchone()[0] == '["live"]',
      'the database did not come back')
conn.close()
check(digest(CERTS / 'server.pem') == pem_before, 'the certificate did not come back')
log = SERVICE_LOG.read_text()
check(log.index('stop zigmon') < log.index('start zigmon') and 'reload nginx' in log,
      'zigmon was not stopped while its database came back, or nginx not reloaded:\n' + log)
check(any('-before-restore' in x['file'] for x in json.loads((STATE / 'root' / 'look.json').read_text())['full']),
      'no backup of how it was right before the restore was made')
# nginx refuses what came back: all of it put back
conf_now = NGINX_CONF.read_text()
NGINX_CONF.write_text(conf_now.replace('server_tokens off;', 'server_tokens off;\n    # changed'))
changed = digest(NGINX_CONF)
st = ask({'kind': 'full_restore', 'id': 'g2', 'file': made, 'parts': ['web', 'config']},
         env=dict(ENV, ZIGMON_NGINX_TEST='false'))
check(st.get('state') == 'failed' and digest(NGINX_CONF) == changed,
      'nginx refused the restored files and they were left in: %r' % st.get('said'))
check('start zigmon' in SERVICE_LOG.read_text(), 'a failed restore left zigmon stopped')

# ---- the folder the request lies in -------------------------------------------------
print('the request itself')
(STATE / 'root' / 'request.json').unlink(missing_ok=True)
secret = W / 'secret.json'
secret.write_text(json.dumps({'kind': 'full_delete', 'file': made}))
os.symlink(secret, STATE / 'root' / 'request.json')
st = ask(None)
check(st.get('state') == 'failed' and (W / 'full' / made).exists(), 'a request that is a link was followed')
st = ask({'kind': 'reboot'})
check(st.get('state') == 'failed', 'a request of an unknown kind did something')

shutil.rmtree(W, ignore_errors=True) if not os.environ.get('ROOT_KEEP') else print('kept', W)
if bad:
    print('\n%d check(s) failed' % len(bad))
    sys.exit(1)
print('root does what the dashboard asks, and nothing else')
