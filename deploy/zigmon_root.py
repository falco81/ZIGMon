#!/usr/bin/python3 -I
"""zigmon_root.py - what the dashboard may ask for that only root can do (5.18).

The daemon runs as `zigmon`, under ProtectSystem=strict, and may not change
nginx, the certificates, the firewall or any file under /etc. What it may do
is lay a request down in /var/lib/zigmon/root/request.json; systemd
(zigmon-root.path) sees it and starts zigmon-root.service, which runs this as
root. Four kinds of thing can be asked for, and nothing else:

  * apply        - the TLS of the dashboard (the certificate with its chain,
                   the root it is checked against, the protocols, the
                   ciphers, the DH parameters, HSTS), who may reach which
                   pages (the allow lists of the dashboard, the one-tap
                   links and the SMS gateway in nginx), and the machine's
                   firewall (iptables / ip6tables, or firewalld);
  * full_*       - a backup of the whole installation: the database, the
                   configuration, nginx, the certificates and their keys,
                   the broker, the firewall and the units - made, handed
                   over for a download, taken in from an upload, looked into,
                   put back, deleted;
  * look.ask     - what is in place now (the certificate, the firewall as
                   iptables-save or firewall-cmd shows it, the allow lists,
                   the kept backups), written for the dashboard.

Nothing in a request is trusted: every value is checked against the one shape
it may have before it goes into a file, certificates and keys are read by
openssl and the key must be the certificate's own, nginx is asked (nginx -t)
before it is reloaded and every file is put back as it was when it says no,
and the folder the zigmon account owns is used through one descriptor, never
a path it could swap for a link.

  zigmon_root.py                          serve request.json (root, from systemd)
  zigmon_root.py --look                   what is in place here (JSON)
  zigmon_root.py --backup [--why WORDS]   a backup of the whole installation, now
  zigmon_root.py --restore FILE [--parts a,b] [--passphrase-file F] [--yes]
                                          put a backup back - any part, from any
                                          machine: root on the command line is
                                          trusted with what the dashboard is not
  zigmon_root.py --inspect FILE [--passphrase-file F]
                                          what a backup holds
"""
import calendar
import grp
import hashlib
import hmac
import io
import ipaddress
import json
import os
import pwd
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

STATE_DIR = os.environ.get('ZIGMON_STATE', '/var/lib/zigmon')
ROOT_SUB = 'root'
ROOT_DIR = os.path.join(STATE_DIR, ROOT_SUB)
# root's own: where the kept backups of the whole installation live, and what
# this helper remembers between runs (the firewalld rules it added, the key
# its backups are sealed with). Never in the zigmon account's folder.
OWN_DIR = os.environ.get('ZIGMON_ROOT_OWN', '/var/lib/zigmon-root')
FULL_DIR = os.environ.get('ZIGMON_FULL_DIR', '/var/backups/zigmon')
CONFIG_FILE = os.environ.get('ZIGMON_CONFIG', '/etc/zigmon/config.json')
NGINX_CANDIDATES = [p for p in (os.environ.get('ZIGMON_NGINX_CONF'),
                                '/etc/nginx/conf.d/zigmon.conf',
                                '/etc/nginx/conf.d/nginx-zigmon.conf') if p]
CERT_DIR = os.environ.get('ZIGMON_CERT_DIR', '/etc/nginx/certs')
MOSQ_DIR = os.environ.get('ZIGMON_MOSQ_DIR', '/etc/mosquitto')
NO_SERVICES = bool(os.environ.get('ZIGMON_NO_SERVICES'))     # tests: no systemctl
NGINX_TEST = shlex.split(os.environ.get('ZIGMON_NGINX_TEST', 'nginx -t'))
FIREWALL_CMD = os.environ.get('ZIGMON_FIREWALL_CMD', 'firewall-cmd')
IPT_PREFIX = os.environ.get('ZIGMON_IPTABLES_PREFIX', '')      # tests: a folder of fakes
MARK = '# written by zigmon (zigmon_root.py) - change it on the dashboard'
SERVICE_USER = os.environ.get('ZIGMON_USER', 'zigmon')
# tests: where /etc is (the places a backup may put a file back are written
# as they are on a real machine, and looked at under this)
FS_ROOT = os.environ.get('ZIGMON_FS_ROOT', '').rstrip('/')
SERVICE_LOG = os.environ.get('ZIGMON_SERVICE_LOG', '')


class Refused(Exception):
    pass


# ---- the folder the zigmon account owns: one descriptor, never a path ------
FD = {}


def sub_fd(name):
    """A descriptor for /var/lib/zigmon/<name>, opened without following a
    link at either step: the zigmon account owns /var/lib/zigmon and could
    otherwise put a link to anywhere in its place between two steps."""
    if name not in FD:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        top = os.open(STATE_DIR, flags)
        try:
            FD[name] = os.open(name, flags, dir_fd=top)
        finally:
            os.close(top)
    return FD[name]


def root_fd():
    return sub_fd(ROOT_SUB)


def child_fd(parent_fd, name, make=False):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        if not make:
            raise
        # the zigmon account takes what is handed over out of it again
        os.mkdir(name, 0o770, dir_fd=parent_fd)
        fd = os.open(name, flags, dir_fd=parent_fd)
        try:
            os.fchown(fd, 0, service_gid())
        except (OSError, KeyError):
            pass
        return fd


def service_gid():
    return grp.getgrnam(SERVICE_USER).gr_gid


def service_uid():
    return pwd.getpwnam(SERVICE_USER).pw_uid


def open_plain(dir_fd, name, most=None):
    """A plain file in a folder of the zigmon account's, opened without
    following a link and without waiting on a FIFO put in its place."""
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        os.close(fd)
        raise Refused('%s is not a plain file' % name)
    if most is not None and st.st_size > most:
        os.close(fd)
        raise Refused('%s is far bigger than it can be' % name)
    return os.fdopen(fd, 'rb')


def read_req(name, most=4 * 1024 * 1024):
    with open_plain(root_fd(), name, most) as f:
        data = f.read(most + 1)
    if len(data) > most:
        raise Refused('the request is far bigger than any request needs')
    return data


def write_here(name, text, dir_fd=None, mode=0o640):
    """A file the dashboard reads, written into the zigmon account's folder:
    a new file beside it, renamed over it - a link put there is replaced,
    never followed."""
    d = root_fd() if dir_fd is None else dir_fd
    data = text if isinstance(text, bytes) else text.encode('utf-8')
    for n in range(50):
        tmp = '.%s.%d.%d' % (name, os.getpid(), n)
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode,
                         dir_fd=d)
        except FileExistsError:
            continue
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            try:
                os.fchown(f.fileno(), 0, service_gid())
            except (OSError, KeyError):
                pass
        os.replace(tmp, name, src_dir_fd=d, dst_dir_fd=d)
        return
    raise OSError('could not write %s' % name)


def write_root(path, data, mode, owner=None):
    """A file of root's, replaced whole - with the owner and the mode the
    one before it had, unless told otherwise: the key nginx and mosquitto
    share may belong to the mosquitto group, and a key written back as
    root:root 0600 would stop the broker at its next start."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    keep = None
    try:
        st = os.lstat(path)
        if stat.S_ISREG(st.st_mode):
            keep = (st.st_uid, st.st_gid, st.st_mode & 0o777)
    except FileNotFoundError:
        pass
    if owner is not None:
        uid, gid, m = owner[0], owner[1], mode
    elif keep:
        uid, gid, m = keep
    else:
        uid, gid, m = 0, 0, mode
    fd, tmp = tempfile.mkstemp(prefix='.zigmon-', dir=folder)
    try:
        # owner and mode set on the open file, never by its name: the folder
        # may be zigmon's own (the backups, the Zigbee2MQTT data), and a name
        # swapped for a link to /etc/shadow while the data was written gave
        # that file zigmon's owner and the mode the backup asked for
        with os.fdopen(fd, 'wb') as f:
            f.write(data if isinstance(data, bytes) else data.encode('utf-8'))
            f.flush()
            os.fchown(f.fileno(), uid, gid)
            os.fchmod(f.fileno(), m)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    relabel(path)


def relabel(path):
    if not NO_SERVICES and shutil.which('restorecon'):
        subprocess.run(['restorecon', path], capture_output=True)


def snapshot(paths):
    got = {}
    for p in paths:
        try:
            st = os.lstat(p)
            if not stat.S_ISREG(st.st_mode):
                got[p] = None
                continue
            with open(p, 'rb') as f:
                got[p] = (f.read(), st.st_mode & 0o777, st.st_uid, st.st_gid)
        except FileNotFoundError:
            got[p] = None
    return got


def put_back(snap):
    for p, was in snap.items():
        if was is None:
            try:
                os.unlink(p)
            except OSError:
                pass
            continue
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p) or '.')
        with os.fdopen(fd, 'wb') as f:          # by the open file, as write_root does
            f.write(was[0])
            f.flush()
            os.fchown(f.fileno(), was[2], was[3])
            os.fchmod(f.fileno(), was[1])
        os.replace(tmp, p)
        relabel(p)


def run(cmd, what, ok=(0,), data=None, env=None):
    got = subprocess.run(cmd, capture_output=True, text=True, input=data, env=env)
    if got.returncode not in ok:
        raise Refused('%s: %s' % (what, (got.stderr or got.stdout).strip()[-300:] or
                                  'ended with %d' % got.returncode))
    return got.stdout


def service(*args):
    """systemctl, or nothing at all under the tests."""
    if NO_SERVICES:
        if SERVICE_LOG:
            with open(SERVICE_LOG, 'a') as f:
                f.write(' '.join(args) + '\n')
        return subprocess.CompletedProcess(args, 0, '', '')
    return subprocess.run(['systemctl'] + list(args), capture_output=True, text=True)


# ---- what a request may hold ------------------------------------------------
ADDR_RE = re.compile(r'^[0-9A-Fa-f:.]+(/[0-9]{1,3})?$')
CERT_RE = re.compile(r'^(\s*-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\s]+-----END CERTIFICATE-----)+\s*$')
KEY_RE = re.compile(r'^\s*-----BEGIN (RSA |EC )?PRIVATE KEY-----[A-Za-z0-9+/=\s:,-]+'
                    r'-----END (RSA |EC )?PRIVATE KEY-----\s*$')
PROTOCOLS = ('TLSv1.2', 'TLSv1.3')
DH_CHOICES = ('none', 'ffdhe2048', 'ffdhe3072', 'ffdhe4096', 'gen2048', 'gen3072', 'gen4096')
NAME_FILE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$')
FULL_FILE = re.compile(r'^zigmon-full-[A-Za-z0-9._-]{1,100}\.tar\.gz$')


def plain(text, how):
    """An address or a network, and nothing else: ipaddress keeps an IPv6
    scope id (fe80::1%eth0) with any character in it, newlines and braces
    included, and so into nginx and iptables files root writes."""
    text = str(text or '').strip()
    if not ADDR_RE.match(text):
        raise ValueError('not a plain address')
    got = {'address': ipaddress.ip_address,
           'network': lambda t: ipaddress.ip_network(t, strict=False)}[how](text)
    if '%' in str(got):
        raise ValueError('a scope id is not taken')
    return got


def openssl(args, what, data=None):
    got = subprocess.run(['openssl'] + args, capture_output=True, text=True, input=data)
    if got.returncode != 0:
        raise Refused('%s: %s' % (what, ((got.stderr or got.stdout).strip().splitlines()
                                         or ['openssl said no'])[-1][:300]))
    return got.stdout


def pem_set(cert, key, chain='', root=''):
    """A certificate, its key, the certificates between it and the root, and
    the root - each read by openssl, the key the certificate's own."""
    cert, key = str(cert or '').strip(), str(key or '').strip()
    chain, root = str(chain or '').strip(), str(root or '').strip()
    if not cert and not key:
        return None
    if not cert or not key:
        raise Refused('a certificate needs its key, and a key its certificate')
    for what, text in (('the certificate', cert), ('the chain', chain), ('the root', root)):
        if text and not CERT_RE.match(text):
            raise Refused('%s is not PEM (-----BEGIN CERTIFICATE-----)' % what)
    if not KEY_RE.match(key):
        raise Refused('the key is not a PEM private key without a passphrase')
    with tempfile.TemporaryDirectory(prefix='zigmon-root-') as t:
        cf, kf = os.path.join(t, 'c.pem'), os.path.join(t, 'k.pem')
        with open(cf, 'w') as f:
            f.write(cert + '\n')
        fd = os.open(kf, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(key + '\n')
        a = openssl(['x509', '-in', cf, '-noout', '-pubkey'], 'the certificate')
        b = openssl(['pkey', '-in', kf, '-pubout'], 'the key')
        if a.strip() != b.strip():
            raise Refused('the key is not the one of this certificate')
        if subprocess.run(['openssl', 'x509', '-in', cf, '-noout', '-checkend', '0'],
                          capture_output=True).returncode != 0:
            raise Refused('the certificate has run out')
    return {'cert': cert + '\n', 'key': key + '\n', 'chain': (chain + '\n') if chain else '',
            'root': (root + '\n') if root else ''}


def tls_checked(t):
    if t is None:
        return None
    if not isinstance(t, dict):
        raise Refused('the TLS is not an object')
    out = {'pem': pem_set(t.get('cert'), t.get('key'), t.get('chain'), t.get('root'))}
    prot = t.get('protocols') or list(PROTOCOLS)
    if not isinstance(prot, list) or not prot or any(p not in PROTOCOLS for p in prot):
        raise Refused('the protocols are TLSv1.2 and/or TLSv1.3')
    out['protocols'] = [p for p in PROTOCOLS if p in prot]
    ciphers = str(t.get('ciphers') or '').strip()
    if ciphers:
        if not re.match(r'^[A-Za-z0-9_+!@=:.-]{1,2000}$', ciphers):
            raise Refused('the ciphers are an OpenSSL cipher list: letters, digits, : + ! - =')
        openssl(['ciphers', ciphers], 'OpenSSL does not know that cipher list')
    out['ciphers'] = ciphers
    out['prefer'] = bool(t.get('prefer'))
    dh = str(t.get('dh') or 'none')
    if dh not in DH_CHOICES:
        raise Refused('the DH parameters are one of %s' % ', '.join(DH_CHOICES))
    out['dh'] = dh
    try:
        out['hsts'] = int(t.get('hsts') or 0)
    except (TypeError, ValueError):
        raise Refused('HSTS is a number of seconds')
    if not 0 <= out['hsts'] <= 63072000:
        raise Refused('HSTS is 0 to 63072000 seconds')
    return out


def checked(r):
    """An apply request, every value in the one shape it may have."""
    if not isinstance(r, dict):
        raise Refused('the request is not an object')
    out = {'id': re.sub(r'[^A-Za-z0-9]', '', str(r.get('id') or ''))[:32],
           'hash': re.sub(r'[^0-9a-f]', '', str(r.get('hash') or ''))[:64]}
    out['tls'] = tls_checked(r.get('tls'))
    fw = r.get('fw')
    if isinstance(fw, dict):
        rules = fw.get('rules') or []
        if not isinstance(rules, list) or len(rules) > 2000:
            raise Refused('the firewall rules are a list, 2000 at most')
        out['fw'] = {'on': bool(fw.get('on')), 'rules': [fw_rule_checked(x) for x in rules]}
    else:
        out['fw'] = None
    out['access'] = access_checked(r.get('access'))
    return out


# ---- nginx: the dashboard's HTTPS server ------------------------------------
def nginx_conf():
    for p in NGINX_CANDIDATES:
        if os.path.isfile(p):
            return p
    return NGINX_CANDIDATES[0] if NGINX_CANDIDATES else '/etc/nginx/conf.d/zigmon.conf'


def block_end(text, brace):
    """Where the { at `brace` is closed."""
    depth = 0
    for j in range(brace, len(text)):
        if text[j] == '{':
            depth += 1
        elif text[j] == '}':
            depth -= 1
            if depth == 0:
                return j + 1
    return None


def server_block(text):
    """(start, end) of the HTTPS server { } of an nginx file."""
    i = 0
    while True:
        m = re.search(r'(?m)^[ \t]*server[ \t]*\{', text[i:])
        if not m:
            return None
        start = i + m.start()
        end = block_end(text, i + m.end() - 1)
        if end is None:
            return None
        block = text[start:end]
        if re.search(r'(?m)^\s*listen\s+[^;]*443[^;]*ssl', block) or \
                re.search(r'(?m)^\s*ssl_certificate\s', block):
            return start, end
        i = end


def directive(block, name):
    """The value of `name` at the server's own level, or None."""
    depth = 0
    for line in block.split('\n'):
        if depth == 1:
            m = re.match(r'^\s*%s\s+([^;]+);' % re.escape(name), line)
            if m:
                return m.group(1).strip().strip('"')
        depth += line.count('{') - line.count('}')
    return None


def set_directive(block, name, value):
    """`name value;` in a server { } - replaced where it is, put in after
    server_name where it is not, taken out for None. Only the server's own
    lines: a location { } inside is left alone."""
    lines = block.split('\n')
    depth, at, insert_at = 0, [], None
    for n, line in enumerate(lines):
        if depth == 1 and re.match(r'^\s*%s(\s|;)' % re.escape(name), line):
            at.append(n)
        if depth == 1 and insert_at is None and re.match(r'^\s*server_name\s', line):
            insert_at = n + 1
        depth += line.count('{') - line.count('}')
    if value is None:
        for n in reversed(at):
            del lines[n]
        return '\n'.join(lines)
    text = '    %-25s %s;' % (name, value)
    if at:
        lines[at[0]] = text
        for n in reversed(at[1:]):
            del lines[n]
    else:
        lines.insert(insert_at if insert_at is not None else 1, text)
    return '\n'.join(lines)


CIPHERS_DEFAULT = ('ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:'
                   'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:'
                   'ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305')


def tls_files(block):
    """The files the dashboard's server reads its certificate from - the
    same files mosquitto may read for its TLS listener, which is why they are
    written where they are rather than under names of zigmon's own."""
    cert = directive(block, 'ssl_certificate') or os.path.join(CERT_DIR, 'server.pem')
    key = directive(block, 'ssl_certificate_key') or os.path.join(CERT_DIR, 'server.key')
    ca = directive(block, 'ssl_trusted_certificate') or os.path.join(CERT_DIR, 'server.ca')
    dh = directive(block, 'ssl_dhparam') or os.path.join(CERT_DIR, 'zigmon-dh.pem')
    for p in (cert, key, ca, dh):
        if not p.startswith('/') or '..' in p.split('/'):
            raise Refused('nginx names a certificate file that is not a plain path: %s' % p[:120])
    return {'cert': cert, 'key': key, 'root': ca, 'dh': dh}


PROGRESS = {'step': 0, 'total': 5, 'id': ''}
DH_EXPECT_S = {'gen2048': 15, 'gen3072': 120, 'gen4096': 600}


def progress(words, step=None, expect=None):
    if step is not None:
        PROGRESS['step'] = step
    try:
        write_here('progress.json', json.dumps({
            'id': PROGRESS['id'], 'step': PROGRESS['step'], 'total': PROGRESS['total'],
            'words': words, 'at': time.time(), 'expect_s': expect}))
    except OSError:
        pass


def dh_file(choice, path, had):
    """The DH parameters for `choice` in `path`: a group of RFC 7919, or made
    here (which takes a while - 4096 bits minutes). Made ones are made once."""
    if choice == 'none':
        return None
    if choice == had and os.path.exists(path):
        return path
    if choice.startswith('ffdhe'):
        pem = openssl(['genpkey', '-genparam', '-algorithm', 'DH', '-pkeyopt',
                       'group:%s' % choice], 'the DH group %s' % choice)
    else:
        progress('making DH parameters of %s bits' % choice[3:], 2, DH_EXPECT_S.get(choice))
        pem = openssl(['dhparam', choice[3:]], 'making DH parameters of %s bits' % choice[3:])
    write_root(path, pem, 0o644)
    return path


def tls_into(block, t, files, had_dh):
    """The server { } with the TLS of `t`: its files written, its lines set.
    Returns (block, words, mosquitto to be told)."""
    said = []
    wrote_cert = False
    progress('writing the certificate and the TLS settings', 3)
    if t['pem']:
        write_root(files['cert'], t['pem']['cert'] + t['pem']['chain'], 0o644)
        write_root(files['key'], t['pem']['key'], 0o600)
        wrote_cert = True
        block = set_directive(block, 'ssl_certificate', files['cert'])
        block = set_directive(block, 'ssl_certificate_key', files['key'])
        trust = t['pem']['root'] + t['pem']['chain']
        if trust:
            write_root(files['root'], trust, 0o644)
            block = set_directive(block, 'ssl_trusted_certificate', files['root'])
        else:
            block = set_directive(block, 'ssl_trusted_certificate', None)
        subj = openssl(['x509', '-noout', '-subject', '-enddate'], 'the certificate',
                       t['pem']['cert']).strip().replace('\n', ', ')
        said.append('certificate: %s' % subj)
    block = set_directive(block, 'ssl_protocols', ' '.join(t['protocols']))
    block = set_directive(block, 'ssl_ciphers', t['ciphers'] or CIPHERS_DEFAULT)
    block = set_directive(block, 'ssl_prefer_server_ciphers', 'on' if t['prefer'] else 'off')
    dh = dh_file(t['dh'], files['dh'], had_dh)
    block = set_directive(block, 'ssl_dhparam', dh)
    if t['hsts']:
        block = set_directive(block, 'add_header Strict-Transport-Security',
                              '"max-age=%d" always' % t['hsts'])
    else:
        block = set_directive(block, 'add_header Strict-Transport-Security', None)
    said.append('%s; %s; DH %s%s' % (' '.join(t['protocols']),
                                     'ciphers as set' if t['ciphers'] else 'the usual ciphers',
                                     t['dh'], '; HSTS %d s' % t['hsts'] if t['hsts'] else ''))
    return block, said, wrote_cert


# ---- the broker: does it read the same certificate? ------------------------
def mosquitto_confs():
    out = []
    main = os.path.join(MOSQ_DIR, 'mosquitto.conf')
    if os.path.isfile(main):
        out.append(main)
    d = os.path.join(MOSQ_DIR, 'conf.d')
    if os.path.isdir(d):
        out += sorted(os.path.join(d, n) for n in os.listdir(d) if n.endswith('.conf'))
    return out


def mosquitto_files():
    """Every file the broker's configuration names: its password file, its
    ACL, its certificates."""
    named = {}
    for conf in mosquitto_confs():
        try:
            with open(conf) as f:
                for line in f:
                    m = re.match(r'^\s*(password_file|acl_file|certfile|keyfile|cafile|'
                                 r'dhparamfile|crlfile)\s+(\S+)\s*$', line)
                    if m:
                        named.setdefault(m.group(2), m.group(1))
        except OSError:
            continue
    return named


def mosquitto_reads(paths):
    return sorted(p for p in mosquitto_files() if p in set(paths))


def mosquitto_hup():
    """mosquitto 2.0 and later read their certificates again on SIGHUP: the
    broker stays up, and the house's devices stay connected."""
    got = service('kill', '-s', 'HUP', 'mosquitto')
    return 'mosquitto told to read its certificate again' if got.returncode == 0 else \
        'mosquitto could not be told (%s) - restart it to use the new certificate' % (
            (got.stderr or '').strip()[-120:] or got.returncode)


# ---- who may reach which pages ------------------------------------------------
# Three lists, as nginx-zigmon.conf has them: the dashboard (the server's own
# allow lines), the one-tap links (both of their locations) and the road the
# SMS gateway pushes a message down. Between marks once the dashboard has set
# them; before that, the allow lines that are there are read as they are and
# the first save puts the marks round them.
ACCESS_PAGES = (('dashboard', 'DASHBOARD', None),
                ('links', 'LINKS', ('location = /tap {', 'location ~ "^/tap/')),
                ('sms', 'SMS', ('location = /api/sms/incoming {',)))
ALWAYS = ('127.0.0.1', '::1')


def access_checked(a):
    if not isinstance(a, dict):
        return None
    out = {}
    for k, _mark, _locs in ACCESS_PAGES:
        one = a.get(k)
        if one is None:
            continue
        if not isinstance(one, dict):
            raise Refused('who may reach the %s is not given' % k)
        nets = []
        for x in (one.get('from') or [])[:400]:
            try:
                net = plain(x, 'network')
            except ValueError:
                raise Refused('%r is not an address or a network' % str(x)[:60])
            # one address is written as one address, as people write it
            nets.append(str(net.network_address) if net.prefixlen == net.max_prefixlen else str(net))
        if not one.get('any') and not nets:
            raise Refused('the %s would be for nobody: give a network or everybody' % k)
        out[k] = {'any': bool(one.get('any')),
                  'from': [n for n in dict.fromkeys(nets) if n not in ALWAYS]}
    return out or None


def access_lines(one, pad):
    lines = ['%sallow %s;' % (pad, a) for a in ALWAYS]
    if one['any']:
        lines.append(pad + 'allow all;                    # everybody (set on the dashboard)')
    else:
        lines += ['%sallow %s;' % (pad, n) for n in one['from']]
    return '\n'.join(lines)


def scopes(text, page):
    """(start, end) of every block a list of `page` lives in: the HTTPS
    server itself for the dashboard, its locations for the others."""
    where = server_block(text)
    if not where:
        return []
    if page[2] is None:
        return [where]
    out = []
    for head in page[2]:
        i = where[0]
        while True:
            i = text.find(head, i, where[1])
            if i < 0:
                break
            # the brace that opens the block ends its line: the one-tap
            # link's own expression has {8,64} in it before that
            m = re.compile(r'\{[ \t]*(#[^\n]*)?\n').search(text, i)
            end = block_end(text, m.start()) if m else None
            if end is None:
                break
            out.append((i, end))
            i = end
    return out


def own_lines(text, start, end):
    """The lines of the block at its own depth: (offset, line) pairs."""
    out, depth, pos = [], 0, start
    for line in text[start:end].split('\n'):
        if depth == 1:
            out.append((pos, line))
        depth += line.count('{') - line.count('}')
        pos += len(line) + 1
    return out


def access_into(text, access):
    """The nginx file with the lists as asked. A list between its marks is
    replaced; one without marks yet has its run of allow lines replaced by a
    marked one, and a block with no allow lines at all gets one - with its
    deny all after it. The blocks are found again after every change, since
    each change moves everything after it."""
    for page in ACCESS_PAGES:
        if page[0] not in access:
            continue
        i = 0
        while True:
            found = scopes(text, page)
            if i >= len(found):
                break
            start, end = found[i]
            text = text[:start] + one_list(text[start:end], page, access[page[0]]) + text[end:]
            i += 1
    return text


def one_list(block, page, one):
    """One block (the server, or a location) with its list as asked."""
    mark = page[1]
    if re.search(r'#\s*%s-ALLOW-BEGIN' % mark, block):
        rx = re.compile(r'([ \t]*)# %s-ALLOW-BEGIN[^\n]*\n.*?\n([ \t]*)# %s-ALLOW-END[^\n]*'
                        % (mark, mark), re.S)
        return rx.sub(lambda m: '%s# %s-ALLOW-BEGIN (set on the dashboard)\n%s\n%s# %s-ALLOW-END'
                      % (m.group(1), mark, access_lines(one, m.group(1)), m.group(2), mark),
                      block, count=1)
    lines = own_lines(block, 0, len(block))
    allow = [(p, l) for p, l in lines if re.match(r'^\s*allow\s', l)]
    deny = [(p, l) for p, l in lines if re.match(r'^\s*deny\s+all\s*;', l)]
    if allow:
        first, last = allow[0][0], allow[-1][0] + len(allow[-1][1])
        pad = re.match(r'[ \t]*', allow[0][1]).group(0)
        body = '%s# %s-ALLOW-BEGIN (set on the dashboard)\n%s\n%s# %s-ALLOW-END' % (
            pad, mark, access_lines(one, pad), pad, mark)
        if not deny or deny[0][0] < first:
            body += '\n%sdeny  all;' % pad
        return block[:first] + body + block[last:]
    pad = '    ' if page[2] is None else '        '
    at = re.compile(r'\{[ \t]*(#[^\n]*)?\n').search(block).end()
    body = '%s# %s-ALLOW-BEGIN (set on the dashboard)\n%s\n%s# %s-ALLOW-END\n%sdeny  all;\n' % (
        pad, mark, access_lines(one, pad), pad, mark, pad)
    return block[:at] + body + block[at:]


def access_now(text=None):
    """What the nginx file says now, for the dashboard."""
    if text is None:
        try:
            with open(nginx_conf()) as f:
                text = f.read()
        except OSError:
            return {}
    out = {}
    for page in ACCESS_PAGES:
        k, mark = page[0], page[1]
        found = scopes(text, page)
        if not found:
            out[k] = {'any': True, 'from': [], 'marked': False, 'present': False}
            continue
        start, end = found[0]
        block = text[start:end]
        m = re.search(r'# %s-ALLOW-BEGIN[^\n]*\n(.*?)\n[ \t]*# %s-ALLOW-END' % (mark, mark), block, re.S)
        if m:
            nets = re.findall(r'(?m)^\s*allow\s+([^;\s]+);', m.group(1))
            marked = True
        else:
            nets = [re.match(r'^\s*allow\s+([^;\s]+);', l).group(1)
                    for _p, l in own_lines(text, start, end) if re.match(r'^\s*allow\s+[^;\s]+;', l)]
            marked = False
        out[k] = {'any': 'all' in nets or not nets,
                  'from': [n for n in nets if n not in ('all',) + ALWAYS],
                  'marked': marked, 'present': True}
    return out


def nginx_part(r, last):
    """The dashboard's server: its TLS, and who may reach which page."""
    said = []
    conf = nginx_conf()
    if not r['tls'] and not r['access']:
        return said, False
    try:
        with open(conf) as f:
            main = f.read()
    except OSError as e:
        raise Refused('the dashboard\'s nginx file cannot be read (%s): %s' % (conf, e))
    where = server_block(main)
    if not where:
        raise Refused('no HTTPS server { } was found in %s' % conf)
    files = tls_files(main[where[0]:where[1]])
    snap = snapshot([conf] + list(files.values()))
    changed, hup = False, False
    try:
        if r['tls']:
            # DH parameters first: making them can take minutes, and nginx's
            # file is read after it, so nothing changed in it meanwhile is
            # written over with an older copy
            dh_file(r['tls']['dh'], files['dh'], last.get('dh'))
            with open(conf) as f:
                main = f.read()
            where = server_block(main)
            block = main[where[0]:where[1]]
            new, words, wrote = tls_into(block, r['tls'], files, r['tls']['dh'])
            if new != block:
                main = main[:where[0]] + new + main[where[1]:]
                write_root(conf, main, 0o644)
            changed = True
            said += words
            if wrote and mosquitto_reads([files['cert'], files['key']]):
                hup = True
        if r['access']:
            new_main = access_into(main, r['access'])
            if new_main != main:
                write_root(conf, new_main, 0o644)
                main, changed = new_main, True
                said.append('nginx: who may reach the dashboard, the one-tap links and the SMS '
                            'road set')
        if changed:
            progress('asking nginx, and reloading it', 4)
            t = subprocess.run(NGINX_TEST, capture_output=True, text=True)
            if t.returncode != 0:
                raise Refused('nginx does not take it, so it is as it was: %s'
                              % ((t.stderr or '').strip().splitlines() or ['?'])[-1][:300])
            service('reload', 'nginx')
            said.append('nginx reloaded')
    except BaseException:
        put_back(snap)
        raise
    if hup:
        said.append(mosquitto_hup())
    return said, changed


def cert_info(path):
    """What a certificate file says about itself, for the dashboard."""
    try:
        with open(path) as f:
            text = f.read()
    except OSError:
        return None
    blocks = re.findall(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', text, re.S)
    if not blocks:
        return None
    try:
        out = openssl(['x509', '-noout', '-subject', '-issuer', '-startdate', '-enddate',
                       '-nameopt', 'RFC2253', '-ext', 'subjectAltName', '-text'],
                      'the certificate', blocks[0] + '\n')
    except Refused:
        return None
    info = {'chain': len(blocks) - 1}

    def field(name):
        m = re.search(r'(?m)^%s=\s*(.*)$' % name, out)
        return m.group(1).strip() if m else ''
    info['subject'] = field('subject')
    info['issuer'] = field('issuer')
    m = re.search(r'(?:^|,)CN=([^,]+)', info['subject'])
    info['cn'] = m.group(1) if m else info['subject']
    for k, name in (('not_before', 'notBefore'), ('not_after', 'notAfter')):
        try:
            info[k] = int(calendar.timegm(time.strptime(field(name), '%b %d %H:%M:%S %Y %Z')))
        except ValueError:
            info[k] = None
    san = re.search(r'Subject Alternative Name:[^\n]*\n\s*([^\n]+)', out)
    info['san'] = [x.strip().split(':', 1)[-1] for x in san.group(1).split(',')] if san else []
    alg = re.search(r'Public Key Algorithm:\s*(\S+)', out)
    bits = re.search(r'Public-Key:\s*\((\d+) bit\)', out)
    kind = (alg.group(1) if alg else '?').replace('rsaEncryption', 'RSA').replace('id-ecPublicKey', 'EC')
    info['key'] = '%s %s' % (kind, bits.group(1)) if bits else kind
    info['self_signed'] = info['subject'] == info['issuer']
    return info


def tls_now():
    conf = nginx_conf()
    try:
        with open(conf) as f:
            text = f.read()
    except OSError:
        return {'conf': conf, 'readable': False}
    where = server_block(text)
    if not where:
        return {'conf': conf, 'readable': True, 'server': False}
    block = text[where[0]:where[1]]
    files = tls_files(block)
    out = {'conf': conf, 'readable': True, 'server': True, 'files': files,
           'info': cert_info(files['cert']),
           'root_info': cert_info(files['root']) if os.path.exists(files['root']) else None,
           'protocols': (directive(block, 'ssl_protocols') or '').split(),
           'ciphers': directive(block, 'ssl_ciphers') or '',
           'prefer': (directive(block, 'ssl_prefer_server_ciphers') or 'off') == 'on',
           'dhparam': directive(block, 'ssl_dhparam') or '',
           'hsts': 0, 'broker': mosquitto_reads([files['cert'], files['key']])}
    m = re.search(r'(?m)^\s*add_header\s+Strict-Transport-Security\s+"?max-age=(\d+)', block)
    if m:
        out['hsts'] = int(m.group(1))
    names = directive(block, 'server_name')
    out['server_name'] = (names or '').split()[0] if names else ''
    if out['info'] and os.path.exists(files['root']):
        got = subprocess.run(['openssl', 'verify', '-CAfile', files['root'], files['cert']],
                             capture_output=True, text=True)
        out['verify'] = 'ok' if got.returncode == 0 else (
            (got.stdout + got.stderr).strip().splitlines() or ['does not verify'])[-1][:200]
    return out


# ---- the firewall -------------------------------------------------------------
# iptables: a chain of its own, ZIGMON-IN, jumped to first from INPUT - the
# loopback, the answers to what this machine asked itself, IPv6's neighbour
# discovery, then the rules in the order the dashboard gives them; what it
# does not let in goes back to INPUT and the rules that were there before.
# Kept in /etc/sysconfig/iptables and ip6tables between lines that start
# "# zigmon:", so it is there after a reboot.
#
# firewalld: rich rules, in every active zone, with a priority below zero so
# they are looked at before the zone's own services and ports - in the order
# the dashboard gives them. firewalld's own rules are left exactly as they
# are; which rich rules are zigmon's is kept in root's own folder, so they
# can be taken away again and nothing else is ever touched.
FW_CHAIN = 'ZIGMON-IN'
FW_FILES = {4: os.environ.get('ZIGMON_FW_FILE4', '/etc/sysconfig/iptables'),
            6: os.environ.get('ZIGMON_FW_FILE6', '/etc/sysconfig/ip6tables')}
FW_TOOLS = {4: ('iptables', 'iptables-restore', 'iptables-save'),
            6: ('ip6tables', 'ip6tables-restore', 'ip6tables-save')}
FW_PROTOS = ('tcp', 'udp', 'icmp', 'vrrp', 'any')
FW_MARK = '# zigmon:'
FWD_STATE = 'firewalld-rules.json'
FWD_FIRST = -30000                  # the first rule; one more for every rule after it


def tool(name):
    if IPT_PREFIX:
        p = os.path.join(IPT_PREFIX, name)
        return p if os.access(p, os.X_OK) else None
    return shutil.which(name)


def firewalld_running():
    if not (shutil.which(FIREWALL_CMD) or os.access(FIREWALL_CMD, os.X_OK)):
        return False
    return subprocess.run([FIREWALL_CMD, '--state'], capture_output=True).returncode == 0


def fw_backend():
    if firewalld_running():
        return 'firewalld'
    if tool('iptables'):
        return 'iptables'
    return ''


def fw_rule_checked(x):
    if not isinstance(x, dict):
        raise Refused('a firewall rule is not an object')
    try:
        fam = int(x.get('family') or 0)
    except (TypeError, ValueError):
        fam = 0
    if fam not in (4, 6):
        raise Refused('a firewall rule is for IPv4 or IPv6')
    proto = str(x.get('proto') or 'any')
    if proto not in FW_PROTOS:
        raise Refused('the protocol is one of %s' % ', '.join(FW_PROTOS))
    port = str(x.get('port') or '').replace(' ', '')
    if port:
        if proto not in ('tcp', 'udp'):
            raise Refused('a port is for TCP or UDP')
        parts = port.split(',')
        if sum(2 if '-' in p else 1 for p in parts) > 15 or \
                not all(re.fullmatch(r'[0-9]{1,5}(-[0-9]{1,5})?', p) for p in parts):
            raise Refused('the ports are numbers or ranges, by commas: 80,443 or 8000-8100')
        for p in parts:
            a, _, b = p.partition('-')
            if not 1 <= int(a) <= 65535 or (b and not int(a) <= int(b) <= 65535):
                raise Refused('%s is not a port or a range of them' % p)
    src = str(x.get('source') or '').strip()
    if src:
        try:
            net = plain(src, 'network')
        except ValueError:
            raise Refused('%r is not an address or a network' % src[:60])
        if net.version != fam:
            raise Refused('%s is not an IPv%d address' % (src, fam))
        src = str(net)
    action = str(x.get('action') or 'accept')
    if action not in ('accept', 'drop', 'reject'):
        raise Refused('a rule accepts, drops or rejects')
    note = re.sub(r'[^A-Za-z0-9 ._:/@()+,-]', '', str(x.get('note') or ''))[:120]
    return {'family': fam, 'proto': proto, 'port': port, 'source': src, 'action': action,
            'note': note}


# -- iptables --
def fw_args(r):
    a = ['-A', FW_CHAIN]
    if r['source']:
        a += ['-s', r['source']]
    if r['proto'] != 'any':
        proto = 'ipv6-icmp' if (r['proto'] == 'icmp' and r['family'] == 6) else r['proto']
        a += ['-p', proto]
    if r['port']:
        if ',' in r['port']:
            a += ['-m', 'multiport', '--dports', r['port'].replace('-', ':')]
        else:
            a += ['--dport', r['port'].replace('-', ':')]
    a += ['-m', 'comment', '--comment', '"zigmon: %s"' % (r['note'] or r['proto'])]
    a += ['-j', r['action'].upper()]
    return ' '.join(a)


def fw_base(fam):
    """What the chain lets through before anybody's rule: the loopback, the
    answers to what this machine asked itself (MQTT out to a broker, the
    boxes it polls, DNS, ntfy), and on IPv6 the neighbour discovery it
    cannot live without. Ahead of the rules, so a DROP of somebody's never
    shuts them out."""
    out = ['-A %s -i lo -m comment --comment "zigmon: loopback" -j ACCEPT' % FW_CHAIN,
           '-A %s -m conntrack --ctstate ESTABLISHED,RELATED -m comment --comment '
           '"zigmon: answers" -j ACCEPT' % FW_CHAIN]
    if fam == 6:
        out += ['-A %s -p ipv6-icmp -m icmp6 --icmpv6-type %d -m comment --comment '
                '"zigmon: neighbour discovery" -j ACCEPT' % (FW_CHAIN, t) for t in (133, 134, 135, 136)]
    return out


def fw_strip(text):
    """A saved ruleset without anything zigmon put in it."""
    out = []
    for line in text.split('\n'):
        k = re.sub(r'^\[\d+:\d+\]\s+', '', line.strip())
        if k.startswith(FW_MARK) or re.match(r'^:%s - \[\d+:\d+\]$' % FW_CHAIN, k) or \
                k == '-A INPUT -j %s' % FW_CHAIN or k.startswith('-A %s ' % FW_CHAIN):
            continue
        out.append(line)
    return '\n'.join(out)


def fw_into(text, lines, on):
    """zigmon's chain into a saved ruleset (iptables-services' file), in the
    *filter table: its name, the jump from INPUT first, its rules last."""
    text = fw_strip(text)
    if not on:
        return text
    rows = text.split('\n')
    try:
        start = next(i for i, l in enumerate(rows) if l.strip() == '*filter')
    except StopIteration:
        rows += ['*filter', ':INPUT ACCEPT [0:0]', ':FORWARD ACCEPT [0:0]',
                 ':OUTPUT ACCEPT [0:0]', 'COMMIT']
        start = len(rows) - 5
    end = next((i for i in range(start + 1, len(rows)) if rows[i].strip() == 'COMMIT'), None)
    if end is None:
        raise Refused('the saved firewall has a *filter table without COMMIT')
    last_decl = max([i for i in range(start, end) if rows[i].startswith(':')] or [start])
    first_input = next((i for i in range(start, end) if rows[i].startswith('-A INPUT')), end)
    block = ['%s zigmon opens what its functions need here (dashboard: Firewall and access); '
             'changed only there' % FW_MARK] + lines + ['%s end' % FW_MARK]
    rows = (rows[:last_decl + 1] + [':%s - [0:0]' % FW_CHAIN] +
            rows[last_decl + 1:first_input] +
            ['%s every rule zigmon makes is in %s' % (FW_MARK, FW_CHAIN), '-A INPUT -j %s' % FW_CHAIN] +
            rows[first_input:end] + block + rows[end:])
    return '\n'.join(rows)


def fw_said(stderr):
    lines = [x.strip() for x in (stderr or '').strip().splitlines()
             if x.strip() and not x.strip().startswith('Try `')]
    return '; '.join(lines[-3:]) or '?'


def ipt_apply(f, said):
    for fam in (4, 6):
        ipt, restore, _save = (tool(n) for n in FW_TOOLS[fam])
        lines = fw_base(fam) + [fw_args(r) for r in f['rules'] if r['family'] == fam]
        if not ipt or not restore:
            continue
        if f['on']:
            snippet = '*filter\n:%s - [0:0]\n%s\nCOMMIT\n' % (FW_CHAIN, '\n'.join(lines))
            got = subprocess.run([restore, '--noflush'], input=snippet, capture_output=True, text=True)
            if got.returncode != 0:
                raise Refused('%s does not take the rules: %s' % (FW_TOOLS[fam][1], fw_said(got.stderr)))
            if subprocess.run([ipt, '-C', 'INPUT', '-j', FW_CHAIN], capture_output=True).returncode != 0:
                subprocess.run([ipt, '-I', 'INPUT', '1', '-j', FW_CHAIN], capture_output=True)
            said.append('IPv%d: %d rule(s) in %s' % (fam, len(lines), FW_CHAIN))
        else:
            ipt_take_away(ipt)
        path = FW_FILES[fam]
        if os.path.exists(path):
            with open(path) as fh:
                old = fh.read()
            new = fw_into(old, lines, f['on'])
            if new != old:
                fd, tmp = tempfile.mkstemp(prefix='.zigmon-fw-', dir=os.path.dirname(path))
                with os.fdopen(fd, 'w') as fh:
                    fh.write(new if new.endswith('\n') else new + '\n')
                    fh.flush()
                    os.fchmod(fh.fileno(), os.stat(path).st_mode & 0o777)
                test = subprocess.run([restore, '--test', tmp], capture_output=True, text=True)
                if test.returncode != 0:
                    os.unlink(tmp)
                    raise Refused('%s would not take the file, so it was left as it was: %s' % (
                        FW_TOOLS[fam][1], fw_said(test.stderr)))
                os.replace(tmp, path)
                relabel(path)
                said.append('%s: kept over a reboot' % path)
        elif f['on']:
            said.append('IPv%d: not kept over a reboot - %s is not there (dnf install '
                        'iptables-services)' % (fam, path))


def ipt_take_away(ipt):
    while subprocess.run([ipt, '-D', 'INPUT', '-j', FW_CHAIN], capture_output=True).returncode == 0:
        pass
    subprocess.run([ipt, '-F', FW_CHAIN], capture_output=True)
    subprocess.run([ipt, '-X', FW_CHAIN], capture_output=True)


def ipt_full(fam):
    save = tool(FW_TOOLS[fam][2])
    if not save:
        return []
    got = subprocess.run([save, '-t', 'filter'], capture_output=True, text=True)
    out = []
    for line in got.stdout.split('\n'):
        line = re.sub(r'^\[\d+:\d+\]\s+', '', line.strip())
        if not line or line.startswith('#') or line in ('*filter', 'COMMIT'):
            continue
        out.append(re.sub(r' \[\d+:\d+\]$', '', line))
    return out[:1500]


def ipt_part(f, said):
    was_live, was_file = {}, {}
    for fam in (4, 6):
        save = tool(FW_TOOLS[fam][2])
        if save:
            was_live[fam] = subprocess.run([save], capture_output=True, text=True).stdout
        if os.path.exists(FW_FILES[fam]):
            was_file[fam] = snapshot([FW_FILES[fam]])
    try:
        ipt_apply(f, said)
    except BaseException:
        for fam, text in was_live.items():
            restore, ipt = tool(FW_TOOLS[fam][1]), tool(FW_TOOLS[fam][0])
            if text.strip() and restore:
                subprocess.run([restore], input=text, capture_output=True, text=True)
            elif ipt:
                ipt_take_away(ipt)
        for snap in was_file.values():
            put_back(snap)
        raise


# -- firewalld --
def fwd(*args):
    return subprocess.run([FIREWALL_CMD] + list(args), capture_output=True, text=True)


def fwd_zones():
    """Every zone an interface or a source is in now; the default zone when
    none is."""
    got = fwd('--get-active-zones')
    zones = [l.strip() for l in got.stdout.split('\n') if l.strip() and not l.startswith((' ', '\t'))]
    zones = [z for z in zones if re.match(r'^[A-Za-z0-9_-]{1,40}$', z)]
    if not zones:
        d = fwd('--get-default-zone').stdout.strip()
        if re.match(r'^[A-Za-z0-9_-]{1,40}$', d):
            zones = [d]
    return list(dict.fromkeys(zones))


def rich(r, priority):
    """One rule as firewalld's rich rules - one per port where it names
    several, since a rich rule takes one port or one range."""
    head = 'rule family="ipv%d" priority="%d"' % (r['family'], priority)
    if r['source']:
        head += ' source address="%s"' % r['source']
    act = {'accept': 'accept', 'drop': 'drop', 'reject': 'reject'}[r['action']]
    if r['proto'] in ('tcp', 'udp') and r['port']:
        return ['%s port port="%s" protocol="%s" %s' % (head, p, r['proto'], act)
                for p in r['port'].split(',')]
    if r['proto'] in ('tcp', 'udp'):
        return ['%s protocol value="%s" %s' % (head, r['proto'], act)]
    if r['proto'] == 'icmp':
        return ['%s protocol value="%s" %s' % (head, 'icmp' if r['family'] == 4 else 'ipv6-icmp', act)]
    if r['proto'] == 'vrrp':
        return ['%s protocol value="vrrp" %s' % (head, act)]
    return ['%s %s' % (head, act)]


def own_fd():
    os.makedirs(OWN_DIR, mode=0o700, exist_ok=True)
    os.chmod(OWN_DIR, 0o700)
    return OWN_DIR


def own_read(name):
    try:
        with open(os.path.join(own_fd(), name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def own_write(name, data):
    path = os.path.join(own_fd(), name)
    fd, tmp = tempfile.mkstemp(dir=OWN_DIR)
    with os.fdopen(fd, 'w') as f:
        f.write(json.dumps(data))
        f.flush()
        os.fchmod(f.fileno(), 0o600)
    os.replace(tmp, path)


def fwd_part(f, said):
    had = own_read(FWD_STATE) or []
    had = [(z, r) for z, r in had if isinstance(z, str) and isinstance(r, str)]
    want = []
    if f['on']:
        zones = fwd_zones()
        if not zones:
            raise Refused('firewalld says no zone is active and names no default zone')
        n = 0
        for r in f['rules']:
            for one in rich(r, FWD_FIRST + n):
                for z in zones:
                    want.append((z, one))
            n += 1
    gone = [x for x in had if x not in want]
    new = [x for x in want if x not in had]
    done_add, done_rm = [], []
    try:
        for z, rr in gone:
            for perm in ([], ['--permanent']):
                fwd(*(perm + ['--zone=%s' % z, '--remove-rich-rule=%s' % rr]))
            done_rm.append((z, rr))
        for z, rr in new:
            for perm in ([], ['--permanent']):
                got = fwd(*(perm + ['--zone=%s' % z, '--add-rich-rule=%s' % rr]))
                if got.returncode != 0 and 'ALREADY_ENABLED' not in (got.stderr + got.stdout):
                    raise Refused('firewalld does not take %s in %s: %s' % (
                        rr, z, fw_said(got.stderr or got.stdout)))
            done_add.append((z, rr))
    except BaseException:
        for z, rr in done_add:
            for perm in ([], ['--permanent']):
                fwd(*(perm + ['--zone=%s' % z, '--remove-rich-rule=%s' % rr]))
        for z, rr in done_rm:
            for perm in ([], ['--permanent']):
                fwd(*(perm + ['--zone=%s' % z, '--add-rich-rule=%s' % rr]))
        raise
    own_write(FWD_STATE, want)
    if f['on']:
        said.append('firewalld: %d rich rule(s) of zigmon\'s in %s' % (
            len(want), ', '.join(sorted({z for z, _r in want})) or '-'))
    elif had:
        said.append('firewalld: zigmon\'s rich rules taken away; the rest is as it was')


def fwd_full():
    out = []
    ours = {r for _z, r in (own_read(FWD_STATE) or []) if isinstance(r, str)}
    for z in fwd_zones():
        got = fwd('--zone=%s' % z, '--list-all')
        for line in got.stdout.split('\n'):
            if line.strip():
                out.append(line.rstrip())
    return out[:1500], sorted(ours)


def fw_part(f):
    """The firewall as asked: (words, report)."""
    said = []
    backend = fw_backend()
    if f is None:
        return said, {'backend': backend}
    if not backend:
        if f['on']:
            raise Refused('there is neither firewalld nor iptables on this machine')
        return said, {'backend': backend}
    progress('the firewall', 5)
    if backend == 'firewalld':
        fwd_part(f, said)
    else:
        ipt_part(f, said)
    return said, {'backend': backend}


def fw_look():
    backend = fw_backend()
    out = {'backend': backend, 'at': time.time()}
    if backend == 'iptables':
        out['full'] = {'4': ipt_full(4), '6': ipt_full(6)}
        out['chain'] = FW_CHAIN
        out['files'] = {str(k): v for k, v in FW_FILES.items() if os.path.exists(v)}
    elif backend == 'firewalld':
        lines, ours = fwd_full()
        out['full'] = {'4': lines, '6': []}
        out['ours'] = ours
        out['zones'] = fwd_zones()
    return out


# ---- a backup of the whole installation -------------------------------------
# One .tar.gz with everything this machine needs to be this house again: the
# database (a consistent copy, made while the daemon runs), /etc/zigmon, the
# dashboard's nginx files and its password file, the certificate and its key,
# the broker's configuration with its passwords and ACL, the firewall's saved
# rules, the units. MANIFEST.json lists every file with its place, owner, mode
# and SHA-256, and MANIFEST.mac seals the list with a key that only root on
# this machine has (/var/lib/zigmon-root/backup.key) - so a backup this
# machine made can be put back whole from the dashboard, while one from
# anywhere else can only give its database, its configuration and its
# certificate back there: putting a unit, nginx's configuration or the
# broker's files back from an uploaded file would be root for anybody holding
# the PIN. Root on the command line may put anything back from anywhere.
PARTS = ('database', 'config', 'web', 'tls', 'broker', 'firewall', 'system', 'zigbee')
UNTRUSTED_OK = ('database', 'config', 'tls', 'zigbee')
PART_WORDS = {'database': 'the database: history, events, every setting made on the dashboard',
              'config': '/etc/zigmon/config.json - the broker, the PIN, the paths',
              'web': 'the dashboard\'s nginx files and its password file',
              'tls': 'the certificate, its chain and its private key',
              'broker': 'mosquitto: its configuration, passwords and ACL',
              'firewall': 'the firewall\'s saved rules',
              'system': 'the zigmon unit, its log rotation and its sudo line',
              'zigbee': 'the newest Zigbee2MQTT coordinator backup'}
MOST_FULL = 4 * 1024 ** 3


def backup_key():
    path = os.path.join(own_fd(), 'backup.key')
    try:
        with open(path) as f:
            k = f.read().strip()
        if re.fullmatch(r'[0-9a-f]{64}', k):
            return bytes.fromhex(k)
    except OSError:
        pass
    k = os.urandom(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(k.hex() + '\n')
    return k


def config_values():
    try:
        with open(CONFIG_FILE) as f:
            got = json.load(f)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def db_file():
    p = str(config_values().get('db_file') or '').strip()
    return p if p.startswith('/') else os.path.join(STATE_DIR, 'history.db')


# What in config.json belongs to this machine rather than to the house - the
# daemon's own FILE_LOCAL. A backup from elsewhere does not bring them: a
# db_file of /etc/ld.so.preload, put back from an uploaded file, made the
# next database put back a file root wrote anywhere it was told.
CONFIG_LOCAL = ('db_file', 'log_file', 'token_file', 'log_to_journal', 'api_host', 'api_port',
                'state_dir')
SQLITE_HEAD = b'SQLite format 3\x00'


def config_kept_local(data):
    """An uploaded config.json with this machine's own paths and port kept
    as they are now."""
    got = json.loads(data.decode('utf-8') if isinstance(data, bytes) else data)
    if not isinstance(got, dict):
        raise Refused('the configuration in the backup is not a JSON object')
    now = config_values()
    for key in CONFIG_LOCAL:
        if key in now:
            got[key] = now[key]
        else:
            got.pop(key, None)
    return (json.dumps(got, indent=2) + '\n').encode('utf-8')


def db_file_ours(path):
    """The database is in the state folder, by its real path."""
    real = os.path.realpath(path)
    return os.path.dirname(real) == os.path.realpath(STATE_DIR)


def owner_names(st):
    try:
        u = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        u = str(st.st_uid)
    try:
        g = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        g = str(st.st_gid)
    return u, g


def nginx_files_of(conf_text, block):
    out = []
    m = re.search(r'(?m)^\s*auth_basic_user_file\s+([^;\s]+);', conf_text)
    if m:
        out.append(m.group(1))
    return out


def gather():
    """{part: [absolute paths]} of what is on this machine to keep."""
    parts = {p: [] for p in PARTS}
    if os.path.isfile(CONFIG_FILE):
        parts['config'].append(CONFIG_FILE)
    conf = nginx_conf()
    text = ''
    if os.path.isfile(conf):
        parts['web'].append(conf)
        with open(conf) as f:
            text = f.read()
    for extra in ('/etc/nginx/conf.d/zigmon-tap.conf', '/etc/nginx/conf.d/zigmon-ntfy.conf'):
        if os.path.isfile(extra) and extra not in parts['web']:
            parts['web'].append(extra)
    where = server_block(text) if text else None
    if where:
        files = tls_files(text[where[0]:where[1]])
        for k in ('cert', 'key', 'root', 'dh'):
            if os.path.isfile(files[k]):
                parts['tls'].append(files[k])
        parts['web'] += [p for p in nginx_files_of(text, None) if os.path.isfile(p)]
    for conf_file in mosquitto_confs():
        parts['broker'].append(conf_file)
    for path in mosquitto_files():
        if os.path.isfile(path) and path not in parts['tls'] and path.startswith(FS_ROOT + '/etc/'):
            parts['broker'].append(path)
    for path in FW_FILES.values():
        if os.path.isfile(path):
            parts['firewall'].append(path)
    zones = '/etc/firewalld/zones'
    if os.path.isdir(zones):
        parts['firewall'] += sorted(os.path.join(zones, n) for n in os.listdir(zones)
                                    if n.endswith('.xml'))
    for path in ('/etc/systemd/system/zigmon.service', '/etc/logrotate.d/zigmon',
                 '/etc/sudoers.d/zigmon'):
        if os.path.isfile(path):
            parts['system'].append(path)
    try:
        bfd = sub_fd('backups')
        zips = sorted(n for n in os.listdir(bfd) if re.match(r'^zigbee2mqtt-[0-9-]+\.zip$', n))
        if zips:
            parts['zigbee'].append(os.path.join(STATE_DIR, 'backups', zips[-1]))
    except OSError:
        pass
    return parts


def hostname():
    return re.sub(r'[^A-Za-z0-9.-]', '', socket.gethostname())[:60] or 'zigmon'


def installed_version():
    for p in ('/usr/local/lib/zigmon/zigmon.py',):
        try:
            with open(p, encoding='utf-8') as f:
                for line in f:
                    m = re.match(r"^__version__ = '([0-9.]+)'", line)
                    if m:
                        return m.group(1)
        except OSError:
            pass
    return ''


def add_bytes(tar, name, data, mode=0o600):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    info.mtime = int(time.time())
    tar.addfile(info, io.BytesIO(data))


def full_make(why='by hand', db_name=None, keep=7, suffix=''):
    """A backup of the whole installation into FULL_DIR. `db_name` is a copy
    of the database the daemon made a moment ago in its backups folder;
    without one (the command line, the daemon stopped) the live file itself is
    copied with SQLite's own backup."""
    os.makedirs(FULL_DIR, mode=0o700, exist_ok=True)
    os.chmod(FULL_DIR, 0o700)
    stamp = time.strftime('%Y-%m-%d-%H%M%S')
    top = 'zigmon-full-%s-%s%s' % (hostname(), stamp, suffix)
    name = top + '.tar.gz'
    path = os.path.join(FULL_DIR, name)
    n = 1
    while os.path.exists(path):
        n += 1
        name = '%s-%d.tar.gz' % (top, n)
        path = os.path.join(FULL_DIR, name)
    parts = gather()
    manifest = {'kind': 'zigmon-full', 'format': 1, 'version': installed_version(),
                'host': hostname(), 'made_at': int(time.time()), 'why': str(why)[:80],
                'top': top, 'files': []}
    work = tempfile.mkdtemp(prefix='zigmon-full-')
    tmp_path = path + '.part'
    try:
        db_copy = os.path.join(work, 'history.db')
        if db_name:
            if not re.match(r'^zigmon-db-[0-9A-Za-z._-]+\.sqlite$', db_name):
                raise Refused('the database copy has no name of a copy')
            with open_plain(sub_fd('backups'), db_name) as src, open(db_copy, 'xb') as out:
                shutil.copyfileobj(src, out, 1 << 20)
        elif os.path.exists(db_file()):
            import sqlite3
            src = sqlite3.connect('file:%s?mode=ro' % db_file(), uri=True)
            dst = sqlite3.connect(db_copy)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as raw, tarfile.open(fileobj=raw, mode='w:gz') as tar:
            def put(part, real, dest, st_from):
                st = os.stat(st_from)
                u, g = owner_names(st)
                h = hashlib.sha256()
                arc = '%s/%s/%s' % (top, part, dest.lstrip('/'))
                with open(real, 'rb') as fh:
                    info = tar.gettarinfo(fileobj=fh, arcname=arc)
                    info.mode, info.uid, info.gid, info.uname, info.gname = 0o600, 0, 0, 'root', 'root'
                    tar.addfile(info, fh)
                with open(real, 'rb') as fh:
                    for lump in iter(lambda: fh.read(1 << 20), b''):
                        h.update(lump)
                manifest['files'].append({'part': part, 'path': dest, 'archive': arc,
                                          'mode': '%o' % (st.st_mode & 0o7777), 'owner': u,
                                          'group': g, 'bytes': os.path.getsize(real),
                                          'sha256': h.hexdigest()})
            if os.path.exists(db_copy):
                live = db_file()
                put('database', db_copy, live, live if os.path.exists(live) else db_copy)
            for part in PARTS:
                if part == 'database':
                    continue
                for p in parts[part]:
                    if part == 'zigbee':
                        with open_plain(sub_fd('backups'), os.path.basename(p)) as src:
                            data = src.read()
                        z = os.path.join(work, os.path.basename(p))
                        with open(z, 'wb') as out:
                            out.write(data)
                        put(part, z, p, z)
                        continue
                    put(part, p, p, p)
            body = json.dumps(manifest, indent=1, sort_keys=True).encode('utf-8')
            add_bytes(tar, '%s/MANIFEST.json' % top, body)
            add_bytes(tar, '%s/MANIFEST.mac' % top,
                      hmac.new(backup_key(), body, hashlib.sha256).hexdigest().encode() + b'\n')
            add_bytes(tar, '%s/RESTORE.txt' % top, RESTORE_TXT.encode('utf-8'), 0o644)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if keep:
        full_prune(int(keep), spare=name)
    return {'file': name, 'bytes': os.path.getsize(path), 'parts': sorted({f['part'] for f in manifest['files']})}


RESTORE_TXT = """A backup of a whole zigmon installation.

Put it back, as root, on this machine or a freshly installed one
(./install.sh first, from the same version or newer):

    zigmon --full-restore THIS-FILE.tar.gz            everything in it
    zigmon --full-restore THIS-FILE.tar.gz --parts database,config,tls

MANIFEST.json says what each file is and where it goes, with its owner, mode
and SHA-256. The private key of the certificate and every password of the
house are in here: keep this file as carefully as those.
"""


def full_list():
    try:
        names = sorted((n for n in os.listdir(FULL_DIR) if FULL_FILE.match(n)), reverse=True)
    except OSError:
        return []
    out = []
    for n in names:
        try:
            st = os.stat(os.path.join(FULL_DIR, n))
        except OSError:
            continue
        out.append({'file': n, 'bytes': st.st_size, 'ts': int(st.st_mtime),
                    'why': 'uploaded' if '-uploaded' in n else
                    'before a restore' if '-before-restore' in n else ''})
    return out


def full_prune(keep, spare=None):
    """The newest `keep` made on the clock or by hand; of those made before a
    restore and those uploaded, the newest three each."""
    names = [x['file'] for x in full_list()]
    groups = {'made': [], 'before': [], 'uploaded': []}
    for n in names:
        groups['uploaded' if '-uploaded' in n else 'before' if '-before-restore' in n else 'made'].append(n)
    for kind, kept in (('made', keep), ('before', 3), ('uploaded', 3)):
        for n in groups[kind][kept:]:
            if n != spare:
                try:
                    os.unlink(os.path.join(FULL_DIR, n))
                except OSError:
                    pass


def full_path(name):
    name = os.path.basename(str(name or ''))
    if not FULL_FILE.match(name):
        raise Refused('that is not the name of a backup of the whole installation')
    path = os.path.join(FULL_DIR, name)
    if not os.path.isfile(path):
        raise Refused('there is no backup called %s' % name)
    return path


def decrypt(src, dst, passphrase):
    env = dict(os.environ, ZIGMON_PASS=passphrase)
    got = subprocess.run(['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-iter', '600000',
                          '-in', src, '-out', dst, '-pass', 'env:ZIGMON_PASS'],
                         capture_output=True, text=True, env=env)
    if got.returncode != 0:
        raise Refused('it does not open with that password')


def encrypt(src, dst, passphrase):
    env = dict(os.environ, ZIGMON_PASS=passphrase)
    run(['openssl', 'enc', '-aes-256-cbc', '-pbkdf2', '-iter', '600000', '-salt',
         '-in', src, '-out', dst, '-pass', 'env:ZIGMON_PASS'], 'encrypting the copy', env=env)


def full_inspect(path, extract_to=None):
    """What a backup holds, trusting none of it: one folder, plain files
    only, every one listed in MANIFEST.json with the right hash, every place
    it names one this kind of backup may have. `trusted` says whether its
    list was sealed by this machine's root."""
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise Refused('the file cannot be read: %s' % e)
    if size > MOST_FULL:
        raise Refused('the file is bigger than any backup of this house can be')
    try:
        tar = tarfile.open(path, 'r:gz')
    except (tarfile.TarError, OSError, EOFError) as e:
        raise Refused('that is not a .tar.gz (or it needs its password): %s' % e)
    with tar:
        members = []
        try:
            while True:
                one = tar.next()
                if one is None:
                    break
                members.append(one)
                if len(members) > 2000:
                    raise Refused('the file holds far too many files')
        except (tarfile.TarError, OSError, EOFError) as e:
            raise Refused('the file is damaged: %s' % e)
        if not members:
            raise Refused('the file holds nothing')
        top = members[0].name.split('/')[0]
        if not re.match(r'^zigmon-full-[A-Za-z0-9._-]{1,100}$', top):
            raise Refused('that is not a backup of a zigmon installation')
        files, total = {}, 0
        for one in members:
            parts = one.name.split('/')
            if one.name.startswith('/') or '..' in parts or parts[0] != top or '\\' in one.name:
                raise Refused('the file has a path outside its folder: %s' % one.name[:120])
            if one.isdir():
                continue
            if not one.isreg():
                raise Refused('the file holds something that is not a plain file: %s' % one.name[:120])
            total += one.size
            if total > 3 * MOST_FULL:
                raise Refused('the file unpacks to far more than any backup of this house')
            files[one.name] = one
        man_name, mac_name = top + '/MANIFEST.json', top + '/MANIFEST.mac'
        if man_name not in files:
            raise Refused('the file has no MANIFEST.json')
        if files[man_name].size > 4 * 1024 * 1024:
            raise Refused('MANIFEST.json is far too big')
        body = tar.extractfile(files[man_name]).read()
        mac = tar.extractfile(files[mac_name]).read().decode('ascii', 'replace').strip() \
            if mac_name in files else ''
        trusted = bool(mac) and hmac.compare_digest(
            mac, hmac.new(backup_key(), body, hashlib.sha256).hexdigest())
        try:
            man = json.loads(body.decode('utf-8'))
        except ValueError:
            raise Refused('MANIFEST.json does not read')
        if not isinstance(man, dict) or man.get('kind') != 'zigmon-full':
            raise Refused('MANIFEST.json does not describe a backup of a zigmon installation')
        listed = []
        for f in man.get('files') or []:
            if not isinstance(f, dict):
                raise Refused('MANIFEST.json has a line that is not a file')
            part, dest, arc = str(f.get('part') or ''), str(f.get('path') or ''), str(f.get('archive') or '')
            if part not in PARTS:
                raise Refused('MANIFEST.json names a part this kind of backup does not have')
            if arc not in files:
                raise Refused('MANIFEST.json names %s, which is not in the file' % arc[:120])
            if not place_ok(part, dest):
                raise Refused('MANIFEST.json would put a file where no backup of zigmon puts one: %s'
                              % dest[:160])
            if not re.fullmatch(r'[0-7]{3,4}', str(f.get('mode') or '')):
                raise Refused('MANIFEST.json gives %s a mode that is not one' % dest[:120])
            h = hashlib.sha256()
            src = tar.extractfile(files[arc])
            for lump in iter(lambda: src.read(1 << 20), b''):
                h.update(lump)
            if h.hexdigest() != str(f.get('sha256') or ''):
                raise Refused('%s is not the file the list says it is' % dest[:120])
            listed.append({'part': part, 'path': dest, 'archive': arc, 'bytes': files[arc].size,
                           'mode': str(f['mode']), 'owner': str(f.get('owner') or 'root')[:32],
                           'group': str(f.get('group') or 'root')[:32]})
        if extract_to:
            for f in listed:
                out = os.path.join(extract_to, f['archive'])
                os.makedirs(os.path.dirname(out), mode=0o700, exist_ok=True)
                with tar.extractfile(files[f['archive']]) as src, open(out, 'xb') as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
    by_part = {}
    for f in listed:
        p = by_part.setdefault(f['part'], {'part': f['part'], 'files': 0, 'bytes': 0,
                                           'words': PART_WORDS.get(f['part'], f['part']), 'paths': []})
        p['files'] += 1
        p['bytes'] += f['bytes']
        if len(p['paths']) < 12:
            p['paths'].append(f['path'])
    return {'top': top, 'version': str(man.get('version') or '')[:20],
            'host': str(man.get('host') or '')[:60], 'made_at': man.get('made_at'),
            'why': str(man.get('why') or '')[:80], 'trusted': trusted, 'bytes': size,
            'parts': [by_part[p] for p in PARTS if p in by_part],
            'from_page': [p for p in PARTS if p in by_part and (trusted or p in UNTRUSTED_OK)],
            'files': listed}


def tls_check(work, files, trusted):
    """The certificate that comes back has its key with it, and from a backup
    made somewhere else it goes back only into the files nginx reads its
    certificate from now - nowhere else under /etc."""
    pems = {}
    for f in files:
        with open(os.path.join(work, f['archive']), 'r', errors='replace') as fh:
            pems[f['path']] = fh.read()
    keys = [t for t in pems.values() if 'PRIVATE KEY' in t]
    certs = []
    for text in pems.values():
        certs += re.findall(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', text, re.S)
    if keys:
        for c in certs:
            try:
                pem_set(c, keys[0])
                break
            except Refused:
                continue
        else:
            raise Refused('no certificate in the backup belongs to its key')
    if not trusted:
        try:
            with open(nginx_conf()) as fh:
                text = fh.read()
            where = server_block(text)
            now = set(tls_files(text[where[0]:where[1]]).values()) if where else set()
        except OSError:
            now = set()
        stray = [p for p in pems if p not in now]
        if stray:
            raise Refused('from a backup made somewhere else a certificate goes back only where '
                          'nginx reads it now (%s), not to %s' % (', '.join(sorted(now)) or '-', stray[0]))


PLACES = {
    'config': (r'^/etc/zigmon/config\.json$',),
    'web': (r'^/etc/nginx/conf\.d/[A-Za-z0-9._-]+\.conf$', r'^/etc/nginx/[A-Za-z0-9._-]+\.htpasswd$'),
    'tls': (r'^/etc/nginx/certs/[A-Za-z0-9._-]+$', r'^/etc/mosquitto/(certs/|ca_certificates/)?[A-Za-z0-9._-]+$'),
    'broker': (r'^/etc/mosquitto/[A-Za-z0-9._/-]+$',),
    'firewall': (r'^/etc/sysconfig/ip6?tables$', r'^/etc/firewalld/zones/[A-Za-z0-9_-]+\.xml$'),
    'system': (r'^/etc/systemd/system/zigmon\.service$', r'^/etc/logrotate\.d/zigmon$',
               r'^/etc/sudoers\.d/zigmon$'),
    'zigbee': (r'^/var/lib/zigmon/backups/zigbee2mqtt-[0-9-]+\.zip$',),
    'database': (r'^/[A-Za-z0-9._/-]+\.db$',),
}


def place_ok(part, dest):
    if '..' in dest.split('/') or not dest.startswith('/'):
        return False
    if part == 'zigbee':
        return bool(re.match(r'^%s/backups/zigbee2mqtt-[0-9-]+\.zip$' % re.escape(STATE_DIR), dest))
    if FS_ROOT:
        if not dest.startswith(FS_ROOT + '/'):
            return part == 'database' and bool(re.match(PLACES['database'][0], dest))
        dest = dest[len(FS_ROOT):]
    return any(re.match(rx, dest) for rx in PLACES.get(part) or ())


def owner_ids(user, group):
    try:
        uid = pwd.getpwnam(user).pw_uid
    except KeyError:
        uid = 0
    try:
        gid = grp.getgrnam(group).gr_gid
    except KeyError:
        gid = 0
    return uid, gid


ACCOUNT_TABLES = ("CREATE TABLE IF NOT EXISTS accounts (name TEXT PRIMARY KEY COLLATE NOCASE, "
                  "role TEXT NOT NULL, pw TEXT NOT NULL, disabled INTEGER DEFAULT 0, "
                  "must_change INTEGER DEFAULT 0, note TEXT DEFAULT '', created INTEGER, "
                  "last_in INTEGER, last_from TEXT DEFAULT '', kind TEXT DEFAULT 'password', "
                  "pin_len INTEGER DEFAULT 0);"
                  "CREATE TABLE IF NOT EXISTS signins (token_hash TEXT PRIMARY KEY, name TEXT NOT NULL, "
                  "created INTEGER, last INTEGER, expires INTEGER, ip TEXT DEFAULT '', "
                  "agent TEXT DEFAULT '');")


def accounts_of(db):
    """The accounts of the dashboard and its sign-ins, as the live database
    has them now (5.19) - kept across putting a database back: a backup
    from before 5.19 has none, and one from last month an old password, and
    the person restoring would be signed out of the house they are mending."""
    import sqlite3
    if not os.path.isfile(db):
        return None
    try:
        con = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
        try:
            con.row_factory = sqlite3.Row
            acc = [dict(r) for r in con.execute('SELECT * FROM accounts')]
            sig = [dict(r) for r in con.execute('SELECT * FROM signins')]
        finally:
            con.close()
    except sqlite3.Error as e:
        print('zigmon_root.py: the accounts of the dashboard could not be read before the database '
              'was put back (%s): it brings its own' % e, file=sys.stderr)
        return None
    return {'accounts': acc, 'signins': sig} if acc else None


def accounts_into(db, kept, owner):
    import sqlite3
    con = sqlite3.connect(db)
    try:
        con.executescript(ACCOUNT_TABLES)
        for col in ("kind TEXT DEFAULT 'password'", 'pin_len INTEGER DEFAULT 0'):
            try:
                con.execute('ALTER TABLE accounts ADD COLUMN ' + col)
            except sqlite3.OperationalError:
                pass
        con.execute('DELETE FROM accounts')
        con.execute('DELETE FROM signins')
        for table in ('accounts', 'signins'):
            for row in kept[table]:
                cols = sorted(row)
                con.execute('INSERT INTO %s (%s) VALUES (%s)' % (table, ','.join(cols), ','.join('?' * len(cols))),
                            [row[c] for c in cols])
        con.commit()
    finally:
        con.close()
    # root opened it: anything it left beside the file is the daemon's again
    for extra in (db, db + '-wal', db + '-shm', db + '-journal'):
        try:
            os.chown(extra, owner[0], owner[1])
        except OSError:
            pass


def full_restore(path, parts, from_page=True, passphrase='', before=True, say=None):
    """Put the chosen parts of a backup back. The daemon is stopped while its
    database or its configuration are put back, everything is put back as it
    was when nginx refuses what came out, and a backup of how it was right
    before is made first - so a restore can itself be undone."""
    said = []

    def note(text):
        said.append(text)
        if say:
            say(text)
    info = full_inspect(path)
    parts = [p for p in parts if p in PARTS]
    if not parts:
        raise Refused('choose what to put back')
    missing = [p for p in parts if p not in {x['part'] for x in info['parts']}]
    if missing:
        raise Refused('the backup has no %s' % ', '.join(missing))
    if from_page and not info['trusted']:
        bad = [p for p in parts if p not in UNTRUSTED_OK]
        if bad:
            raise Refused('this backup was not made by this machine, so %s can only be put back by '
                          'root on the command line (zigmon --full-restore FILE --parts %s)'
                          % (', '.join(bad), ','.join(parts)))
    work = tempfile.mkdtemp(prefix='zigmon-restore-')
    os.chmod(work, 0o700)
    stopped = False
    snap = {}
    try:
        full_inspect(path, extract_to=work)
        chosen = [f for f in info['files'] if f['part'] in parts]
        if 'tls' in parts:
            tls_check(work, [f for f in chosen if f['part'] == 'tls'], trusted=info['trusted'])
        if 'config' in parts:
            for f in chosen:
                if f['part'] == 'config':
                    try:
                        json.load(open(os.path.join(work, f['archive'])))
                    except ValueError:
                        raise Refused('the configuration in the backup is not JSON')
        if before:
            note('a backup of how it is now: %s' % full_make('before a restore', keep=7,
                                                               suffix='-before-restore')['file'])
        if {'database', 'config'} & set(parts):
            service('stop', 'zigmon')
            stopped = True
            note('zigmon stopped')
        dests = [f['path'] for f in chosen if f['part'] != 'database']
        live_db = db_file()
        if 'database' in parts and from_page and not db_file_ours(live_db):
            raise Refused('the database is not in %s (db_file is %s), so it is put back by root on '
                          'the command line only' % (STATE_DIR, live_db))
        if 'database' in parts:
            dests += [live_db, live_db + '-wal', live_db + '-shm']
        snap = snapshot(dests)
        for f in chosen:
            src = os.path.join(work, f['archive'])
            with open(src, 'rb') as fh:
                data = fh.read()
            if f['part'] == 'database':
                if not data.startswith(SQLITE_HEAD):
                    raise Refused('the database in the backup is not an SQLite database')
                kept = accounts_of(live_db)
                for extra in (live_db + '-wal', live_db + '-shm'):
                    try:
                        os.unlink(extra)
                    except OSError:
                        pass
                try:
                    owner = (service_uid(), service_gid())
                except KeyError:
                    owner = (0, 0)
                write_root(live_db, data, 0o640, owner=owner)
                if kept:
                    accounts_into(live_db, kept, owner)
                note('the database put back (%d MB)%s' % (
                    len(data) // 1048576, ', the accounts of the dashboard kept as they were' if kept else ''))
                continue
            uid, gid = owner_ids(f['owner'], f['group'])
            mode = int(f['mode'], 8) & 0o777
            if f['part'] == 'zigbee':
                uid, gid = owner_ids(SERVICE_USER, SERVICE_USER)
            if from_page and not info['trusted']:
                # who owns it and who may read it are not the uploaded list's
                # to say: it made config.json 0666, and the private key
                # anybody's. The file there now keeps its own; a new one is
                # nobody's but its owner's.
                mode &= 0o640
                if f['part'] == 'config':
                    data = config_kept_local(data)
                if f['part'] != 'zigbee':
                    write_root(f['path'], data, 0o600)
                    note('%s put back' % f['path'])
                    continue
            write_root(f['path'], data, mode, owner=(uid, gid))
            note('%s put back' % f['path'])
        if {'web', 'tls'} & set(parts):
            t = subprocess.run(NGINX_TEST, capture_output=True, text=True)
            if t.returncode != 0:
                raise Refused('nginx does not take what came back, so all of it is as it was: %s'
                              % ((t.stderr or '').strip().splitlines() or ['?'])[-1][:300])
            service('reload', 'nginx')
            note('nginx reloaded')
        if 'system' in parts:
            service('daemon-reload')
        if 'broker' in parts:
            got = service('restart', 'mosquitto')
            note('mosquitto restarted' if got.returncode == 0 else
                 'mosquitto did not restart: %s' % (got.stderr or '').strip()[-160:])
        elif 'tls' in parts:
            tls_paths = [f['path'] for f in chosen if f['part'] == 'tls']
            if mosquitto_reads(tls_paths):
                note(mosquitto_hup())
        if 'firewall' in parts:
            if firewalld_running():
                got = fwd('--reload')
                note('firewalld read its zones again' if got.returncode == 0 else
                     'firewalld did not reload: %s' % fw_said(got.stderr))
            else:
                for fam in (4, 6):
                    restore = tool(FW_TOOLS[fam][1])
                    if restore and os.path.exists(FW_FILES[fam]):
                        got = subprocess.run([restore, FW_FILES[fam]], capture_output=True, text=True)
                        note('IPv%d: the saved rules put in' % fam if got.returncode == 0 else
                             'IPv%d: %s' % (fam, fw_said(got.stderr)))
    except BaseException:
        if snap:
            put_back(snap)
            note('everything put back as it was')
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if stopped:
            service('start', 'zigmon')
            note('zigmon started')
    return said


# ---- the requests ---------------------------------------------------------------
def status_read():
    try:
        got = json.loads(read_req('status.json').decode('utf-8'))
    except (OSError, ValueError, Refused):
        return {}
    return got if isinstance(got, dict) else {}


def look(write=True):
    out = {'at': time.time(), 'tls': tls_now(), 'access': access_now(), 'fw': fw_look(),
           'full': full_list(), 'full_dir': FULL_DIR, 'host': hostname(),
           'version': installed_version()}
    if write:
        write_here('look.json', json.dumps(out))
    return out


def handle(raw):
    """One request, by its kind: (state fields, words)."""
    kind = str(raw.get('kind') or 'apply')
    if kind == 'apply':
        r = checked(raw)
        last = status_read().get('dh_last') or {}
        said_n, _ = nginx_part(r, {'dh': last.get('dh')} if isinstance(last, dict) else {})
        said_f, fw = fw_part(r['fw'])
        fields = {'fw': fw, 'hash': r['hash']}
        if r['tls']:
            fields['dh_last'] = {'dh': r['tls']['dh']}
        return fields, said_n + said_f
    if kind == 'full_make':
        keep = raw.get('keep')
        try:
            keep = max(1, min(365, int(keep)))
        except (TypeError, ValueError):
            keep = 7
        db = raw.get('db')
        made = full_make(str(raw.get('why') or 'by hand'), str(db) if db else None, keep)
        return {'made': made}, ['a backup of the whole installation: %s (%d MB)' % (
            made['file'], made['bytes'] // 1048576)]
    if kind == 'full_get':
        path = full_path(raw.get('file'))
        pw = str(raw.get('passphrase') or '')
        out_fd = child_fd(root_fd(), 'out', make=True)
        for n in os.listdir(out_fd):                    # one hand-over at a time
            try:
                os.unlink(n, dir_fd=out_fd)
            except OSError:
                pass
        name = os.path.basename(path) + ('.enc' if pw else '')
        with tempfile.TemporaryDirectory(prefix='zigmon-get-') as t:
            src = path
            if pw:
                if len(pw) < 8:
                    raise Refused('a password for the copy is eight characters or more')
                src = os.path.join(t, 'enc')
                encrypt(path, src, pw)
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640,
                         dir_fd=out_fd)
            with os.fdopen(fd, 'wb') as out, open(src, 'rb') as fh:
                shutil.copyfileobj(fh, out, 1 << 20)
                os.fchown(out.fileno(), 0, service_gid())
        return {'out': name, 'out_bytes': os.stat(name, dir_fd=out_fd).st_size}, \
            ['handed over for a download: %s%s' % (name, ' (with a password)' if pw else '')]
    if kind == 'full_put':
        name = os.path.basename(str(raw.get('file') or ''))
        if not re.match(r'^upload-[A-Za-z0-9]{1,32}\.bin$', name):
            raise Refused('the request names no uploaded file')
        in_fd = child_fd(root_fd(), 'in', make=True)
        os.makedirs(FULL_DIR, mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='zigmon-put-', dir=FULL_DIR) as t:
            copy = os.path.join(t, 'copy')
            with open_plain(in_fd, name, MOST_FULL) as src, open(copy, 'xb') as out:
                shutil.copyfileobj(src, out, 1 << 20)
            try:
                os.unlink(name, dir_fd=in_fd)
            except OSError:
                pass
            with open(copy, 'rb') as fh:
                magic = fh.read(8)
            pw = str(raw.get('passphrase') or '')
            if magic == b'Salted__':
                if not pw:
                    raise Refused('this copy is locked with a password: give it')
                plain_copy = os.path.join(t, 'plain')
                decrypt(copy, plain_copy, pw)
                copy = plain_copy
            info = full_inspect(copy)
            base = re.sub(r'\.tar\.gz$', '', info['top']) + '-uploaded'
            target = os.path.join(FULL_DIR, base + '.tar.gz')
            n = 1
            while os.path.exists(target):
                n += 1
                target = os.path.join(FULL_DIR, '%s-%d.tar.gz' % (base, n))
            shutil.copyfile(copy, target)
            os.chmod(target, 0o600)
        info['file'] = os.path.basename(target)
        info.pop('files', None)
        return {'inspected': info}, ['taken in: %s%s' % (info['file'], '' if info['trusted'] else
                                                          ' (made somewhere else)')]
    if kind == 'full_inspect':
        info = full_inspect(full_path(raw.get('file')))
        info['file'] = os.path.basename(full_path(raw.get('file')))
        info.pop('files', None)
        return {'inspected': info}, []
    if kind == 'full_restore':
        parts = raw.get('parts') or []
        if not isinstance(parts, list):
            raise Refused('the parts are a list')
        said = full_restore(full_path(raw.get('file')), [str(p) for p in parts][:10], from_page=True)
        return {'restored': os.path.basename(str(raw.get('file'))), 'parts': parts}, said
    if kind == 'full_delete':
        path = full_path(raw.get('file'))
        os.unlink(path)
        return {}, ['deleted: %s' % os.path.basename(path)]
    raise Refused('nothing is done for a request of the kind %r' % kind[:40])


def serve():
    d = root_fd()
    asked_look = False
    try:
        os.unlink('look.ask', dir_fd=d)
        asked_look = True
    except FileNotFoundError:
        pass
    except OSError:
        asked_look = True
    try:
        os.replace('request.json', 'request.taken', src_dir_fd=d, dst_dir_fd=d)
    except FileNotFoundError:
        if asked_look:
            look()
        return 0
    last = status_read()
    out = {'at': time.time()}
    if isinstance(last.get('dh_last'), dict):
        out['dh_last'] = last['dh_last']
    for k in ('applied_hash', 'failed_hash'):
        if isinstance(last.get(k), str):
            out[k] = last[k]
    try:
        try:
            raw = json.loads(read_req('request.taken').decode('utf-8'))
        except ValueError as e:
            raise Refused('the request does not read: %s' % e)
        if not isinstance(raw, dict):
            raise Refused('the request is not an object')
        out['id'] = re.sub(r'[^A-Za-z0-9]', '', str(raw.get('id') or ''))[:32]
        out['kind'] = re.sub(r'[^a-z_]', '', str(raw.get('kind') or 'apply'))[:20]
        # what was asked for, so a request refused is not asked for again by itself
        out['asked_hash'] = re.sub(r'[^0-9a-f]', '', str(raw.get('hash') or ''))[:64]
        PROGRESS['id'] = out['id']
        progress('checking what was asked', 1)
        fields, said = handle(raw)
        out.update(fields)
        if out['kind'] == 'apply':
            out['applied_hash'] = fields.get('hash', '')
        out.update(state='done', said=[s for s in said if s])
    except Refused as e:
        out.update(state='failed', said=[str(e)])
    except Exception as e:                              # noqa: BLE001 - said, never lost
        out.update(state='failed', said=['it broke: %s' % e])
    finally:
        for name in ('request.taken', 'progress.json'):
            try:
                os.unlink(name, dir_fd=d)
            except OSError:
                pass
    if out.get('kind') == 'apply':
        # the last apply refused, kept across the requests of other kinds, so
        # the daemon does not ask for it again by itself
        out['failed_hash'] = out.get('asked_hash', '') if out.get('state') == 'failed' else ''
    write_here('status.json', json.dumps(out))
    if str(out.get('kind') or '').startswith('full_'):
        # kept apart too: the next apply must not hide how a restore ended
        write_here('status-full.json', json.dumps(out))
    try:
        look()
    except Exception as e:                              # noqa: BLE001
        print('zigmon_root.py: looking at what is in place: %s' % e, file=sys.stderr)
    return 0


def passphrase_from(argv):
    if '--passphrase-file' in argv:
        with open(argv[argv.index('--passphrase-file') + 1]) as f:
            return f.read().strip()
    return ''


def opened(path, argv, work):
    """The backup itself, decrypted into `work` first when it is locked."""
    with open(path, 'rb') as fh:
        magic = fh.read(8)
    if magic != b'Salted__':
        return path
    pw = passphrase_from(argv)
    if not pw:
        raise Refused('this copy is locked with a password: --passphrase-file FILE')
    out = os.path.join(work, 'plain.tar.gz')
    decrypt(path, out, pw)
    return out


def main(argv):
    if argv[:1] == ['--look']:
        print(json.dumps(look(write=False), indent=1))
        return 0
    if os.geteuid() != 0:
        print('zigmon_root.py: root only', file=sys.stderr)
        return 2
    try:
        if argv[:1] == ['--backup']:
            why = argv[argv.index('--why') + 1] if '--why' in argv else 'the command line'
            made = full_make(why)
            print('%s/%s (%d MB): %s' % (FULL_DIR, made['file'], made['bytes'] // 1048576,
                                         ', '.join(made['parts'])))
            return 0
        if argv[:1] == ['--inspect'] and len(argv) >= 2:
            with tempfile.TemporaryDirectory(prefix='zigmon-look-') as t:
                info = full_inspect(opened(argv[1], argv, t))
            info.pop('files', None)
            print(json.dumps(info, indent=1))
            return 0
        if argv[:1] == ['--restore'] and len(argv) >= 2:
            with tempfile.TemporaryDirectory(prefix='zigmon-cli-') as t:
                path = opened(os.path.abspath(argv[1]), argv, t)
                info = full_inspect(path)
                parts = argv[argv.index('--parts') + 1].split(',') if '--parts' in argv else \
                    [p['part'] for p in info['parts']]
                print('%s, made on %s by zigmon %s%s' % (
                    info['top'], info['host'], info['version'] or '?',
                    '' if info['trusted'] else ' (on another machine)'))
                for p in info['parts']:
                    print('  %-9s %s %s' % (p['part'], '*' if p['part'] in parts else ' ', p['words']))
                if '--yes' not in argv:
                    answer = input('Put back the parts marked * ? [y/N] ').strip().lower()
                    if answer not in ('y', 'yes'):
                        print('nothing done')
                        return 1
                full_restore(path, parts, from_page=False, say=print)
            return 0
        if not argv:
            return serve()
    except Refused as e:
        print('refused: %s' % e, file=sys.stderr)
        return 1
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
