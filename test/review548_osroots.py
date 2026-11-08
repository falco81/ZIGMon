#!/usr/bin/env python3
"""The system's trusted roots (otp 1.0.265, Control - Certificates): company
root and intermediate certificate authorities put into the trust of the whole
operating system, beside the distribution's list.

  * root's helper (deploy/zigmon_root.py, osroots.ask) against a folder of
    local additions, a system list and a tool that stand in for the machine
    (its env hooks): the flavour found (RHEL, Debian, neither), every refusal
    and warning - the same words as the daemon's -, a chain, the limits, a
    sync that is idempotent, only zigmon-<sha256>.crt|.pem written or removed,
    others' files (a link, a pipe, a subfolder) left as they are and never
    followed, a link planted in zigmon's name replaced, a folder that is a
    link or not root's alone refused, restorecon -F under SELinux, the tool
    run only on a change (its failure the request's), each of ours looked
    for in the list the tool made;
  * the daemon (root run as root would run it, ZIGMON_ROOT_RUN): check, add,
    remove, refresh through the API - an administrator's only -, DER, a chain
    without its root, a private key refused, 50 at most, the want row and the
    machine's row, the events, the tick (due at the start, every half hour,
    on a change, ten minutes after a failure; never in the caller's way), the
    Python SSL_CERT_FILE fix, the command line (--os-roots-add a DER file);
  * the relay (php -S on web/index.php): its routes;
  * the card on Certificates in Chromium (php -S + Playwright): empty, the add
    dialog checking as one types (a warning, a refusal, all good), a DER file
    read in the browser, added, the table and the machine's box, removed.

    python3 test/review548_osroots.py        (OSR_SHOTS=DIR keeps the pictures)

Needs openssl and php; Chromium by Playwright for the card (skipped without
it). Ports 19950 (the daemon) and 19951 (php -S).
"""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ROOT_HELPER = HERE / 'deploy' / 'zigmon_root.py'
W = Path(tempfile.mkdtemp(prefix='zigmon-osroots-check-'))
API_PORT, PHP_PORT = 19950, 19951
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


# ---- the certificates, made here by openssl --------------------------------------------------
CA = W / 'certs'
CA.mkdir()
(CA / 'ext.cnf').write_text("""[ca]
basicConstraints=critical,CA:TRUE
keyUsage=critical,keyCertSign,cRLSign
subjectKeyIdentifier=hash
[leaf]
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
subjectAltName=DNS:ldap.example.local
[nosign]
basicConstraints=critical,CA:TRUE
keyUsage=critical,digitalSignature
[none]
subjectKeyIdentifier=hash
""")


def ossl(*a, data=None):
    r = subprocess.run(['openssl'] + [str(x) for x in a], capture_output=True, input=data)
    if r.returncode:
        raise SystemExit('openssl %s: %s' % (' '.join(map(str, a)), r.stderr.decode()[-300:]))
    return r.stdout


def key(name, kind='rsa:3072'):
    p = CA / (name + '.key')
    if kind.startswith('rsa'):
        ossl('genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:' + kind[4:], '-out', p)
    else:
        ossl('genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256', '-out', p)
    return p


def cert(name, cn, kind='rsa:3072', ext='ca', ca=None, md='sha256', days=3650):
    k = key(name, kind)
    ossl('req', '-new', '-key', k, '-subj', '/O=Example Corp/CN=' + cn, '-out', CA / (name + '.csr'))
    a = ['x509', '-req', '-in', CA / (name + '.csr'), '-out', CA / (name + '.pem'), '-days', days, '-' + md,
         '-extfile', CA / 'ext.cnf', '-extensions', ext]
    a += ['-CA', CA / (ca + '.pem'), '-CAkey', CA / (ca + '.key'), '-CAcreateserial'] if ca else ['-signkey', k]
    ossl(*a)
    return (CA / (name + '.pem')).read_text()


def dated(name, cn, start, end):
    """A root valid only between two moments: openssl ca -selfsign."""
    db = CA / 'db'
    (db / 'new').mkdir(parents=True, exist_ok=True)
    (db / 'index.txt').touch()
    if not (db / 'serial').exists():
        (db / 'serial').write_text('1000\n')
    (db / 'ca.cnf').write_text("""[ca]
default_ca = c
[c]
dir = %s
database = $dir/index.txt
new_certs_dir = $dir/new
serial = $dir/serial
default_md = sha256
policy = p
unique_subject = no
[p]
commonName = supplied
[v3]
basicConstraints = critical,CA:TRUE
keyUsage = critical,keyCertSign,cRLSign
""" % db)
    k = key(name, 'ec')
    ossl('req', '-new', '-key', k, '-subj', '/CN=' + cn, '-out', CA / (name + '.csr'))

    def at(t):
        return time.strftime('%Y%m%d%H%M%SZ', time.gmtime(t))
    ossl('ca', '-batch', '-config', db / 'ca.cnf', '-selfsign', '-keyfile', k, '-in', CA / (name + '.csr'),
         '-startdate', at(start), '-enddate', at(end), '-extensions', 'v3', '-out', CA / (name + '.pem'), '-notext')
    return (CA / (name + '.pem')).read_text()


def fp_of(pem):
    body = ''.join(pem.split('-----')[2].split())
    return hashlib.sha256(base64.b64decode(body)).hexdigest()


print('certificates made by openssl')
ROOT = cert('root', 'Example Corp Root CA')
INTER = cert('inter', 'Example Corp Issuing CA 1', ca='root')
LEAF = cert('leaf', 'ldap.example.local', 'rsa:2048', 'leaf', ca='inter', days=30)
NOBC = cert('nobc', 'No Constraints CA', 'ec', 'none')
NOSIGN = cert('nosign', 'Cannot Sign CA', 'ec', 'nosign')
WEAK = cert('weak', 'Weak Root CA', 'rsa:1024')
SHA1 = cert('sha1', 'Old Issuing CA', 'rsa:2048', 'ca', ca='root', md='sha1')
LAB = cert('lab', 'Lab LDAPS CA', 'ec')
OTHER = cert('other', 'Another Root CA', 'ec')
EXPIRED = dated('expired', 'Gone Root CA', time.time() - 400 * 86400, time.time() - 30 * 86400)
FUTURE = dated('future', 'Later Root CA', time.time() + 30 * 86400, time.time() + 400 * 86400)
SYSTEM = [cert('sys%d' % n, 'Distribution Root %d' % n, 'ec') for n in range(3)]
ossl('x509', '-in', CA / 'root.pem', '-outform', 'DER', '-out', CA / 'root.cer')
FP_ROOT, FP_INTER = fp_of(ROOT), fp_of(INTER)
KEY_TEXT = (CA / 'leaf.key').read_text()           # a private key of the test's own, never written out

# ---- the machine: a folder of local additions, the system's list, its tool ------------------
STATE = W / 'state'
(STATE / 'root').mkdir(parents=True)
ADD = W / 'local-ca'                     # /usr/local/share/ca-certificates, as root's
ADD.mkdir(mode=0o755)
os.chmod(str(ADD), 0o755)
BUNDLE = W / 'ca-certificates.crt'
BASE = W / 'base.pem'
BASE.write_text(''.join(SYSTEM))
shutil.copy(str(BASE), str(BUNDLE))
TOOL_LOG = W / 'tool.log'
TOOL = W / 'fake-update-ca-certificates'
TOOL.write_text("""#!/bin/bash
echo run >> %(w)s/tool.log
if [ -e %(w)s/tool-fail ]; then echo "broken on purpose" >&2; exit 3; fi
if [ -e %(w)s/tool-slow ]; then sleep 1.5; fi
{
  cat %(w)s/base.pem
  if [ ! -e %(w)s/tool-skip ]; then
    for f in %(d)s/*.crt %(d)s/*.pem %(d)s/*/*.crt; do
      if [ -f "$f" ] && [ ! -L "$f" ]; then cat "$f"; fi
    done
  fi
} > %(w)s/bundle.tmp && mv %(w)s/bundle.tmp %(b)s
""" % {'w': W, 'd': ADD, 'b': BUNDLE})
TOOL.chmod(0o755)
RESTORECON = W / 'fake-restorecon'
RESTORECON.write_text('#!/bin/bash\necho "$@" >> %s/restorecon.log\n' % W)
RESTORECON.chmod(0o755)
os.environ.update(ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(W / 'own'), ZIGMON_FULL_DIR=str(W / 'full'),
                  ZIGMON_CONFIG=str(W / 'config.json'), ZIGMON_NO_SERVICES='1', ZIGMON_USER='root',
                  ZIGMON_FS_ROOT=str(W / 'fsroot'),
                  ZIGMON_OSROOTS_FLAVOUR='debian', ZIGMON_OSROOTS_DIR=str(ADD),
                  ZIGMON_OSROOTS_BUNDLE=str(BUNDLE), ZIGMON_OSROOTS_TOOL=str(TOOL),
                  ZIGMON_OSROOTS_PKG='echo ca-certificates 20260816-test',
                  ZIGMON_OSROOTS_RESTORECON=str(RESTORECON),
                  ZIGMON_ROOT_RUN='%s -I %s' % (sys.executable, ROOT_HELPER))
(W / 'config.json').write_text('{}')

spec = importlib.util.spec_from_file_location('zigmon_root', str(ROOT_HELPER))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


def ask_root(req):
    (STATE / 'root' / 'osroots.ask').write_text(json.dumps(req))
    R.serve()
    check(not (STATE / 'root' / 'osroots.ask').exists(), 'osroots.ask was left behind')
    try:
        return json.loads((STATE / 'root' / 'osroots.json').read_text())
    except (OSError, ValueError):
        return {}


def tool_runs():
    try:
        return len(TOOL_LOG.read_text().split())
    except OSError:
        return 0


def ours():
    return sorted(n for n in os.listdir(str(ADD)) if n.startswith('zigmon-'))


api = None
try:
    # ---- root: which way the system adds to its trust ------------------------------------------
    print('root: the flavour of the system')
    saved = {k: os.environ.pop(k) for k in ('ZIGMON_OSROOTS_FLAVOUR', 'ZIGMON_OSROOTS_DIR', 'ZIGMON_OSROOTS_BUNDLE',
                                            'ZIGMON_OSROOTS_TOOL')}
    path_was = os.environ.get('PATH', '')
    try:
        os.environ['PATH'] = str(W / 'no-bin')
        for layout, want in (('etc/pki/ca-trust/source', 'rhel'), ('usr/local/share/ca-certificates', 'debian'),
                             ('', None)):
            fs = W / ('fs-' + (want or 'none'))
            (fs / layout).mkdir(parents=True, exist_ok=True)
            R.FS_ROOT = str(fs)
            got = R.osroots_where()
            check((got or {}).get('flavour') == want, 'the flavour of %s: %r' % (layout or 'nothing', got))
            if want == 'rhel':
                check(got['dir'] == str(fs) + '/etc/pki/ca-trust/source/anchors' and got['ext'] == '.pem' and
                      got['tool'] == ['update-ca-trust', 'extract'] and
                      got['bundle'].endswith('/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem'),
                      'RHEL: anchors, .pem, update-ca-trust extract: %r' % got)
            if want == 'debian':
                check(got['ext'] == '.crt' and got['tool'] == ['update-ca-certificates'] and
                      got['bundle'].endswith('/etc/ssl/certs/ca-certificates.crt'), 'Debian: .crt: %r' % got)
        got = ask_root({'id': 'n1', 'do': 'sync', 'certs': [ROOT]})
        check(not got.get('ok') and 'neither update-ca-trust' in (got.get('said') or ''),
              'a system with neither tool: %r' % got)
    finally:
        os.environ['PATH'] = path_was
        os.environ.update(saved)
        R.FS_ROOT = os.environ['ZIGMON_FS_ROOT']

    # ---- root: what is refused and what is warned of -------------------------------------------
    print('root: refused and warned - the same words as the daemon\'s')
    for text, words in (('', 'no certificate in it'), ('hello', 'no certificate in it'),
                        (ROOT + KEY_TEXT, 'no private key'),
                        ('-----BEGIN ENCRYPTED PRIVATE KEY-----\nAAAA\n-----END ENCRYPTED PRIVATE KEY-----\n',
                         'no private key'),
                        ('-----BEGIN PKCS7-----\nAAAA\n-----END PKCS7-----\n' + ROOT, 'nothing but certificates'),
                        (ROOT.replace('CERTIFICATE', 'TRUSTED CERTIFICATE'), 'nothing but certificates'),
                        ('-----BEGIN CERTIFICATE-----\nAB=C\n-----END CERTIFICATE-----\n', 'not base64'),
                        ('-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----\n'
                         % base64.b64encode(b'x' * 13000).decode(), 'a few kB at most')):
        try:
            R.osroots_blocks(text)
            check(False, 'root took %r' % text[:40])
        except R.Refused as e:
            check(words in str(e), 'root\'s words for %r: %s' % (text[:30], e))
    got = ask_root({'id': 'k1', 'do': 'check', 'text': ROOT + KEY_TEXT})
    check(not got.get('ok') and 'no private key' in got.get('said', '') and 'PRIVATE' not in json.dumps(got),
          'a key in a check: %r' % str(got)[:200])
    sys.argv = ['zigmon']
    sys.path.insert(0, str(HERE))
    import zigmon                                       # noqa: E402
    Z = zigmon.__dict__
    expect = {
        'root': (ROOT, [], []), 'inter': (INTER, [], []),
        'leaf': (LEAF, ['it is not a certificate authority (CA:FALSE) - a server\'s own certificate does not go here',
                        'its key usage does not let it sign certificates (no keyCertSign)'], []),
        'nobc': (NOBC, ['it says nothing of being an authority (no basicConstraints CA:TRUE) - only a certificate '
                        'authority goes here'], []),
        'nosign': (NOSIGN, ['its key usage does not let it sign certificates (no keyCertSign)'], []),
        'weak': (WEAK, [], ['its key has 1024 bits - the system\'s crypto policy (DEFAULT) refuses fewer than 2048']),
        'sha1': (SHA1, [], ['it is signed with sha1WithRSAEncryption - the system\'s crypto policy (DEFAULT) refuses '
                            'it, and every chain through it']),
        'expired': (EXPIRED, [], ['it ran out on']), 'future': (FUTURE, [], ['it is valid only from'])}
    for name, (pem, refused, warn) in expect.items():
        (p1, d1), = R.osroots_blocks(pem)
        f = R.osroots_facts(p1, d1)
        check(f['refused'] == refused, 'root: %s refused %r' % (name, f['refused']))
        check(len(f['warn']) == len(warn) and all(w.startswith(x) for w, x in zip(f['warn'], warn)),
              'root: %s warned %r' % (name, f['warn']))
        try:
            g = Z['osr_facts'](*Z['osr_blocks'](pem)[0])
            check(g['refused'] == f['refused'] and g['warn'] == f['warn'] and g['fp'] == f['fp'] and
                  g['cn'] == f['cn'] and g['key'] == f['key'] and g['kind'] == f['kind'],
                  'the daemon says otherwise than root of %s: %r / %r' % (name, g.get('refused'), g.get('warn')))
        except KeyError as e:
            check(False, 'the daemon has no %s' % e)
    f = R.osroots_facts(*R.osroots_blocks(ROOT)[0])
    check(f['cn'] == 'Example Corp Root CA' and f['kind'] == 'root' and f['key'] == 'RSA 3072' and f['ca'],
          'the root read: %r' % {k: f[k] for k in ('cn', 'kind', 'key')})
    f = R.osroots_facts(*R.osroots_blocks(LAB)[0])
    check(f['key'] == 'EC P-256', 'an EC key: %r' % f['key'])
    got = ask_root({'id': 'c1', 'do': 'check', 'text': ROOT + '\n' + INTER})
    check(got.get('ok') and [c['cn'] for c in got['data']['certs']] == ['Example Corp Root CA', 'Example Corp Issuing CA 1'],
          'a chain checked by root: %r' % str(got)[:200])

    # ---- root: the whole set put in --------------------------------------------------------------
    print('root: the set put in, idempotent, others left as they are')
    (ADD / 'lab-ldaps-ca.crt').write_text(LAB)
    (ADD / 'corp').mkdir()
    (ADD / 'corp' / 'other.crt').write_text(OTHER)
    VICTIM = W / 'victim.txt'
    VICTIM.write_text('not yours\n')
    os.symlink(str(VICTIM), str(ADD / 'evil.crt'))
    os.mkfifo(str(ADD / 'pipe.crt'))
    others_before = {n: (ADD / n).read_bytes() for n in ('lab-ldaps-ca.crt', 'corp/other.crt')}
    got = ask_root({'id': 's1', 'do': 'sync', 'certs': [ROOT, INTER]})
    data = got.get('data') or {}
    names = ['zigmon-%s.crt' % FP_INTER[:16], 'zigmon-%s.crt' % FP_ROOT[:16]]
    check(got.get('ok') and ours() == sorted(names), 'the two not written: %r %r' % (got.get('said'), ours()))
    for n in names:
        st = os.lstat(str(ADD / n))
        check(stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o644 and st.st_uid == 0 and st.st_gid == 0,
              '%s is not root\'s 0644: %o %d' % (n, st.st_mode, st.st_uid))
    check(tool_runs() == 1 and '%s run' % TOOL in data.get('said', []), 'the tool did not run once: %r' % data.get('said'))
    check(data.get('not_in_bundle') == [] and all(f.get('in_bundle') for f in data.get('ours') or [])
          and len(data.get('ours') or []) == 2, 'ours are not in the system\'s list: %r' % data.get('ours'))
    check((data.get('system') or {}).get('count') == 3 + 2 + 2 and
          (data.get('system') or {}).get('package') == 'ca-certificates 20260816-test',
          'the system\'s list read: %r' % data.get('system'))
    oth = {o['file']: o for o in data.get('others') or []}
    check(set(oth) == {'lab-ldaps-ca.crt', 'corp/other.crt', 'evil.crt', 'pipe.crt'},
          'the others\' files shown: %r' % sorted(oth))
    check([c['cn'] for c in oth.get('lab-ldaps-ca.crt', {}).get('certs', [])] == ['Lab LDAPS CA'] and
          [c['cn'] for c in oth.get('corp/other.crt', {}).get('certs', [])] == ['Another Root CA'],
          'the others\' certificates read: %r' % oth)
    check(oth.get('evil.crt', {}).get('link') == str(VICTIM) and not oth['evil.crt'].get('certs'),
          'a link is shown as a link, never followed: %r' % oth.get('evil.crt'))
    check(oth.get('pipe.crt', {}).get('certs') == [], 'a pipe was read: %r' % oth.get('pipe.crt'))
    check(not R.OSROOTS_NAME_RE.match('lab-ldaps-ca.crt') and not R.OSROOTS_NAME_RE.match('zigmon-1234.crt') and
          not R.OSROOTS_NAME_RE.match('zigmon-%s.crt.bak' % FP_ROOT[:16]), 'zigmon\'s name matches others\' files')
    got = ask_root({'id': 's2', 'do': 'sync', 'certs': [INTER, ROOT]})
    check(got.get('ok') and got['data']['said'] == [] and tool_runs() == 1,
          'the same set again changed something or ran the tool: %r' % got.get('data', {}).get('said'))
    # changed by somebody, and a link planted in zigmon's name: both put back as wanted
    (ADD / names[0]).write_text(OTHER)
    os.unlink(str(ADD / names[1]))
    os.symlink(str(VICTIM), str(ADD / names[1]))
    got = ask_root({'id': 's3', 'do': 'sync', 'certs': [ROOT, INTER]})
    check(got.get('ok') and sorted(got['data']['said'][:2]) == sorted('added ' + n for n in names) and tool_runs() == 2,
          'what was changed was not put back: %r' % got.get('data', {}).get('said'))
    check(not os.path.islink(str(ADD / names[1])) and VICTIM.read_text() == 'not yours\n' and
          fp_of((ADD / names[1]).read_text()) == FP_ROOT, 'the link in zigmon\'s name was followed or kept')
    # one refused is said, not written; the rest go in
    got = ask_root({'id': 's4', 'do': 'sync', 'certs': [ROOT, INTER, LEAF]})
    check(got.get('ok') and [r['cn'] for r in got['data']['refused']] == ['ldap.example.local'] and
          ours() == sorted(names) and tool_runs() == 2, 'a server\'s certificate in the set: %r' % got.get('data', {}).get('refused'))
    # SELinux: the new file labelled as the folder wants
    os.environ['ZIGMON_OSROOTS_SELINUX'] = '1'
    got = ask_root({'id': 's5', 'do': 'sync', 'certs': [ROOT, INTER, WEAK]})
    os.environ.pop('ZIGMON_OSROOTS_SELINUX')
    fp_weak = fp_of(WEAK)
    check(got.get('ok') and (W / 'restorecon.log').read_text().strip() ==
          '-F %s/zigmon-%s.crt' % (ADD, fp_weak[:16]), 'restorecon -F was not run on the new file alone')
    # the tool fails: the request fails, with what it said
    (W / 'tool-fail').touch()
    got = ask_root({'id': 's6', 'do': 'sync', 'certs': [ROOT, INTER]})
    (W / 'tool-fail').unlink()
    check(not got.get('ok') and 'ended with 3: broken on purpose' in got.get('said', ''),
          'a tool that failed: %r' % got)
    # ours not in the list the tool made: said; forced, the tool runs again
    (W / 'tool-skip').touch()
    got = ask_root({'id': 's7', 'do': 'sync', 'certs': [ROOT, INTER], 'force': True})
    check(got.get('ok') and sorted(got['data']['not_in_bundle']) == sorted([FP_ROOT, FP_INTER]),
          'ours missing from the list were not said: %r' % got.get('data', {}).get('not_in_bundle'))
    (W / 'tool-skip').unlink()
    runs = tool_runs()
    got = ask_root({'id': 's8', 'do': 'sync', 'certs': [ROOT, INTER], 'force': True})
    check(got.get('ok') and tool_runs() == runs + 1 and got['data']['not_in_bundle'] == [],
          'forced, the tool did not run: %r' % got.get('data', {}).get('said'))
    # what zigmon no longer wants taken away - and only that
    (ADD / ('zigmon-%s.crt' % ('0' * 16))).write_text(OTHER)
    got = ask_root({'id': 's9', 'do': 'sync', 'certs': [INTER]})
    check(got.get('ok') and ours() == [names[0]] and 'removed zigmon-%s.crt' % ('0' * 16) in got['data']['said'],
          'what is no longer wanted was not taken away: %r' % ours())
    check({n: (ADD / n).read_bytes() for n in others_before} == others_before and os.path.islink(str(ADD / 'evil.crt'))
          and stat.S_ISFIFO(os.lstat(str(ADD / 'pipe.crt')).st_mode), 'the others\' files were touched')
    # limits
    got = ask_root({'id': 'l1', 'do': 'sync', 'certs': [ROOT] * 51})
    check(not got.get('ok') and 'a list of 50 at most' in got.get('said', ''), '51 taken: %r' % got)
    got = ask_root({'id': 'l2', 'do': 'sync', 'certs': [ROOT + INTER]})
    check(not got.get('ok') and 'one certificate in each' in got.get('said', ''), 'two in one: %r' % got)
    got = ask_root({'id': 'l3', 'do': 'sync', 'certs': [ROOT + ' ' * 17000]})
    check(not got.get('ok') and '16384 bytes at most' in got.get('said', ''), 'a big one: %r' % got)
    # the folder: a link, or not root's alone - nothing written there
    real = W / 'real-dir'
    real.mkdir(mode=0o755)
    os.environ['ZIGMON_OSROOTS_DIR'] = str(W / 'linked-dir')
    os.symlink(str(real), str(W / 'linked-dir'))
    got = ask_root({'id': 'f1', 'do': 'sync', 'certs': [ROOT]})
    check(not got.get('ok') and 'is not a folder (a link?)' in got.get('said', '') and not os.listdir(str(real)),
          'a folder that is a link: %r' % got)
    os.environ['ZIGMON_OSROOTS_DIR'] = str(real)
    os.chmod(str(real), 0o777)
    got = ask_root({'id': 'f2', 'do': 'sync', 'certs': [ROOT]})
    check(not got.get('ok') and 'is not root\'s alone' in got.get('said', '') and not os.listdir(str(real)),
          'a folder others may write: %r' % got)
    os.environ['ZIGMON_OSROOTS_DIR'] = str(W / 'made-here')
    got = ask_root({'id': 'f3', 'do': 'list'})
    check(got.get('ok') and not (W / 'made-here').exists(), 'a look made the folder')
    os.environ['ZIGMON_OSROOTS_DIR'] = str(ADD)
    # the asking file as a link is taken away, not followed
    os.symlink(str(VICTIM), str(STATE / 'root' / 'osroots.ask'))
    R.serve()
    check(not os.path.lexists(str(STATE / 'root' / 'osroots.ask')) and VICTIM.read_text() == 'not yours\n',
          'a link named osroots.ask was followed or left')
    # the RHEL way: .pem
    rh = W / 'anchors'
    rh.mkdir(mode=0o755)
    os.environ.update(ZIGMON_OSROOTS_FLAVOUR='rhel', ZIGMON_OSROOTS_DIR=str(rh))
    got = ask_root({'id': 'r1', 'do': 'sync', 'certs': [ROOT]})
    check(got.get('ok') and os.listdir(str(rh)) == ['zigmon-%s.pem' % FP_ROOT[:16]] and got['data']['flavour'] == 'rhel',
          'RHEL: not zigmon-<sha>.pem: %r' % os.listdir(str(rh)))
    os.environ.update(ZIGMON_OSROOTS_FLAVOUR='debian', ZIGMON_OSROOTS_DIR=str(ADD))
    unit = (HERE / 'deploy' / 'zigmon-root.path').read_text()
    check('PathExists=/var/lib/zigmon/root/osroots.ask' in unit, 'zigmon-root.path does not watch osroots.ask')
    helper = ROOT_HELPER.read_text()
    check('osroots_part' in helper[helper.index('def serve():'):], 'serve() does not answer osroots.ask')

    # ---- the daemon --------------------------------------------------------------------------------
    print('the daemon: check, add, remove, the tick, through the API')
    got = ask_root({'id': 'z0', 'do': 'sync', 'certs': []})           # the machine as it was
    TOOL_LOG.write_text('')
    DB = STATE / 'history.db'
    zigmon.load_config()
    zigmon.CONFIG.update({'db_file': str(DB), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                          'token_file': str(W / 'token'), 'plugs': [], 'sensors': [], 'mqtt_host': '',
                          'log_file': '', 'state_dir': str(STATE), 'acme': 0})
    d = zigmon.Daemon()
    d.notify = lambda message, *a, **k: None
    api = zigmon.ApiServer(d)
    api.start()
    time.sleep(0.3)

    def call(path, body=None, session=None, timeout=120):
        headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': '192.168.40.10'}
        if session:
            headers['X-Zigmon-Session'] = session
        req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                     data=None if body is None else json.dumps(body).encode(),
                                     method='GET' if body is None else 'POST')
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b'{}')
            except ValueError:
                return e.code, {}

    d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
    d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
    S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
    S_OP = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''

    def osr(body=None, session=None):
        return call('/api/osroots', None if body is None else dict(body), session=session or S)

    def settle(wait=60):
        """Until root has put in what is wanted (the work runs in a thread)."""
        end = time.time() + wait
        while time.time() < end:
            v = osr()[1]
            if not zigmon.OSR_WORK['busy'] and (v.get('node') or {}).get('status') in ('applied', 'failed', 'none'):
                return v
            time.sleep(0.2)
        return osr()[1]

    check('/api/osroots' in zigmon.ApiHandler.ALWAYS_LOCKED, '/api/osroots is not an administrator\'s read')
    code, out = osr(session=S_OP)
    check(code == 403, 'an operator reads the card: %s' % code)
    code, out = osr({'action': 'check', 'text': ROOT}, session=S_OP)
    check(code == 403, 'an operator checks: %s' % code)
    code, out = osr({'action': 'add', 'text': ROOT}, session='made-up')
    check(code == 403, 'a made-up sign-in adds: %s' % code)
    check(zigmon.osr_due(), 'nothing due at the start')
    check(zigmon.osr_tick(d), 'the tick at the start did not start root')
    v = settle()
    check(v.get('node', {}).get('status') == 'none' and v.get('certs') == [] and v.get('want') is None,
          'before anything was added: %r' % str(v)[:300])
    check(sorted(o['file'] for o in v['node']['others']) == ['corp/other.crt', 'evil.crt', 'lab-ldaps-ca.crt', 'pipe.crt']
          and v['node']['system'].get('count') == 5 and v['node']['dir'] == str(ADD) and tool_runs() == 0,
          'the machine read: %r' % v.get('node'))
    check(not zigmon.osr_due(), 'due again at once')
    # check: a chain, a refusal, a warning - nothing written
    code, out = osr({'action': 'check', 'text': ROOT + INTER + LEAF})
    cs = out.get('certs') or []
    check(code == 200 and [c['cn'] for c in cs] == ['Example Corp Root CA', 'Example Corp Issuing CA 1', 'ldap.example.local']
          and [bool(c['refused']) for c in cs] == [False, False, True] and cs[1]['warn'] == [],
          'a chain checked: %r' % str(out)[:300])
    code, out = osr({'action': 'check', 'text': INTER})
    check(code == 200 and out['certs'][0]['warn'] == [zigmon.OSR_NO_ROOT_WARN], 'an intermediate alone: %r' % out)
    check(zigmon.osr_want(d) is None and tool_runs() == 0, 'a check wrote something')
    code, out = osr({'action': 'check', 'text': ROOT + KEY_TEXT})
    check(code == 400 and 'no private key' in out.get('error', '') and 'PRIVATE' not in json.dumps(out),
          'a key pasted: %r' % str(out)[:200])
    der = (CA / 'root.cer').read_bytes()
    check(fp_of(zigmon.osr_text(der)) == FP_ROOT, 'DER is not read as the certificate it is')
    try:
        zigmon.osr_text(b'\x30\x03junk')
        check(False, 'junk taken as DER')
    except ValueError:
        pass
    # added: the want row, the event, root at once in a thread
    code, out = osr({'action': 'add', 'text': ROOT + INTER + LEAF})
    check(code == 200 and [a['cn'] for a in out.get('added', [])] == ['Example Corp Root CA', 'Example Corp Issuing CA 1']
          and [r['cn'] for r in out.get('refused', [])] == ['ldap.example.local'], 'added: %r' % str(out)[:300])
    want = zigmon.osr_want(d)
    check(want and [c['fp'] for c in want['certs']] == [FP_ROOT, FP_INTER] and want['by'] == 'owner',
          'the want row: %r' % str(want)[:200])
    v = settle()
    n = v.get('node') or {}
    check(n.get('status') == 'applied' and ours() == sorted(names) and tool_runs() == 1,
          'not as wanted after the add: %r %r' % (n.get('status'), n.get('why')))
    check([c['in_bundle'] for c in v['certs']] == [True, True] and [c['kind'] for c in v['certs']] == ['root', 'intermediate'],
          'the card\'s certificates: %r' % [(c['cn'], c['in_bundle']) for c in v['certs']])
    now_row = json.loads(d.store.get_meta('osroots:now'))
    check(now_row['ok'] and now_row['hash'] == want['hash'] and '-----BEGIN' not in json.dumps(now_row),
          'the machine\'s row: %r' % str(now_row)[:200])
    ev = ' | '.join(str(e) for e in d.store.events(limit=50, text='trusted roots'))
    check('owner added Example Corp Root CA (root, SHA-256 %s)' % FP_ROOT[:16] in ev and
          'added zigmon-%s.crt' % FP_ROOT[:16] in ev, 'the events: %r' % ev[:400])
    code, out = osr({'action': 'add', 'text': ROOT})
    check(code == 400 and 'there already' in out.get('error', ''), 'the same again: %r' % out)
    code, out = osr({'action': 'add', 'text': LEAF})
    check(code == 400 and 'CA:FALSE' in out.get('error', ''), 'a server\'s certificate alone: %r' % out)
    # the tick: nothing due now; half an hour on, again; a failure tried again after ten minutes
    check(not zigmon.osr_due(), 'due right after it was put in')
    check(zigmon.osr_due(now=time.time() + 1801, want=zigmon.osr_want(d)), 'not due after half an hour')
    saved_work = dict(zigmon.OSR_WORK)
    zigmon.OSR_WORK.update(done_hash=None, fail_hash=want['hash'], fail_at=time.time())
    check(not zigmon.osr_due(want=zigmon.osr_want(d)), 'tried again at once after a failure')
    check(zigmon.osr_due(now=time.time() + 601, want=zigmon.osr_want(d)), 'not tried again ten minutes after a failure')
    zigmon.OSR_WORK.update(saved_work)
    # never in the caller's way: the tick only starts the work
    (W / 'tool-slow').touch()
    zigmon.OSR_WORK['done_at'] = 0
    zigmon.OSR_WORK['force'] = True
    t0 = time.time()
    started = zigmon.osr_tick(d)
    took = time.time() - t0
    check(started and took < 0.5, 'the tick waited for root: %.2f s' % took)
    check(any(t.name == 'osroots' for t in threading.enumerate()), 'no thread of its own')
    settle()
    (W / 'tool-slow').unlink()
    # a failure: said on the card, an event; then put right
    (W / 'tool-fail').touch()
    code, out = osr({'action': 'add', 'text': WEAK})
    check(code == 200 and out['added'][0]['warn'] and 'fewer than 2048' in out['added'][0]['warn'][0], 'a weak root: %r' % out)
    v = settle()
    check(v['node']['status'] == 'failed' and 'broken on purpose' in v['node']['why'], 'a failure not said: %r' % v['node'])
    check('broken on purpose' in ' '.join(str(e) for e in d.store.events(limit=20, text='broken on purpose')),
          'a failure is not an event')
    (W / 'tool-fail').unlink()
    code, out = osr({'action': 'refresh'})
    check(code == 200, 'refresh: %r' % out)
    v = settle()
    check(v['node']['status'] == 'applied' and len(ours()) == 3, 'refresh did not put it right: %r' % v['node'])
    # removed: by a prefix of 12 or more, unique
    for fp, words in (('abc', '12 characters'), ('f' * 16, 'no certificate with that fingerprint')):
        code, out = osr({'action': 'remove', 'fp': fp})
        check(code == 400 and words in out.get('error', ''), 'remove %s: %r' % (fp, out))
    code, out = osr({'action': 'remove', 'fp': fp_weak[:12]})
    check(code == 200, 'remove: %r' % out)
    v = settle()
    check(v['node']['status'] == 'applied' and ours() == sorted(names) and
          'took away Weak Root CA' in ' '.join(str(e) for e in d.store.events(limit=50, text='took away')),
          'not taken away: %r' % ours())
    # 50 at most
    w = zigmon.osr_want(d)
    full = [{'pem': ROOT, 'fp': '%064x' % i, 'cn': 'x', 'kind': 'root'} for i in range(50)]
    d.store.set_meta('osroots:want', json.dumps({'v': w['v'] + 1, 'certs': full, 'by': 't', 'at': time.time()}))
    code, out = osr({'action': 'add', 'text': OTHER})
    check(code == 400 and '50 certificates at most' in out.get('error', ''), '51 added: %r' % out)
    d.store.set_meta('osroots:want', json.dumps(dict(w, v=w['v'] + 2)))
    zigmon.OSR_WORK['done_hash'] = w['hash']
    # the command line: a DER file read here, shown, added (--yes)
    zigmon.api_call = lambda path, method='GET', payload=None, **kw: call(path, payload, session=S)
    code, out = osr({'action': 'remove', 'fp': FP_ROOT})
    settle()
    buf = io.StringIO()
    args = zigmon.build_parser().parse_args(['--os-roots-add', str(CA / 'root.cer'), '--yes'])
    with contextlib.redirect_stdout(buf):
        rc = zigmon._dispatch(args, zigmon.Palette(False))
    check(rc == 0 and 'Example Corp Root CA' in buf.getvalue() and 'added 1' in buf.getvalue(),
          'zigmon --os-roots-add a DER file: %r' % buf.getvalue()[-300:])
    settle()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = zigmon._dispatch(zigmon.build_parser().parse_args(['--os-roots']), zigmon.Palette(False))
    check(rc == 0 and 'Example Corp Issuing CA 1' in buf.getvalue() and 'as wanted' in buf.getvalue() and
          'lab-ldaps-ca.crt' in buf.getvalue(), 'zigmon --os-roots: %r' % buf.getvalue()[-400:])
    buf = io.StringIO()
    was_in, sys.stdin = sys.stdin, io.StringIO('y\n')       # not a terminal: never asked, never done
    try:
        with contextlib.redirect_stdout(buf):
            rc = zigmon._dispatch(zigmon.build_parser().parse_args(['--os-roots-remove', FP_INTER[:14]]),
                                  zigmon.Palette(False))
    finally:
        sys.stdin = was_in
    check(rc == 2 and zigmon.osr_want(d)['certs'][-1:] and len(zigmon.osr_want(d)['certs']) == 2,
          'removed without asking (no terminal): %r' % buf.getvalue())
    # the Python fix: SSL_CERT_FILE only where OpenSSL's own places are empty
    was_paths, was_env = zigmon.ssl.get_default_verify_paths, {k: os.environ.get(k) for k in ('SSL_CERT_FILE', 'SSL_CERT_DIR')}
    try:
        for k in ('SSL_CERT_FILE', 'SSL_CERT_DIR'):
            os.environ.pop(k, None)
        zigmon.ssl.get_default_verify_paths = lambda: zigmon.ssl.DefaultVerifyPaths(
            str(W / 'nothing.pem'), str(W / 'no-dir'), '', '', '', '')
        zigmon.OSR_SYSTEM_BUNDLES[:] = [str(BUNDLE)]
        check(zigmon.osr_python_fix() == str(BUNDLE) and os.environ.get('SSL_CERT_FILE') == str(BUNDLE),
              'SSL_CERT_FILE not pointed at the system\'s list')
        check(zigmon.osr_python_trust().get('system') is True, 'the card would not say the own connections use it')
        os.environ['SSL_CERT_FILE'] = str(W / 'mine.pem')
        check(zigmon.osr_python_fix() == '' and os.environ['SSL_CERT_FILE'] == str(W / 'mine.pem'),
              'an SSL_CERT_FILE given was changed')
        os.environ.pop('SSL_CERT_FILE')
        zigmon.ssl.get_default_verify_paths = lambda: zigmon.ssl.DefaultVerifyPaths(
            str(BASE), '', '', '', '', '')
        check(zigmon.osr_python_fix() == '' and 'SSL_CERT_FILE' not in os.environ, 'a working default was changed')
    finally:
        zigmon.ssl.get_default_verify_paths = was_paths
        for k, val in was_env.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val

    # ---- the relay ------------------------------------------------------------------------------------
    print('the relay')
    page = (HERE / 'web' / 'index.php').read_text()
    allowed = page[page.index("if (in_array($what, ['scenes-save'"):]
    allowed = allowed[:allowed.index('], true)')]
    check("'osroots-do'" in allowed and "'osroots-do' => '/api/osroots'" in page and
          "if ($what === 'osroots' && $_SERVER['REQUEST_METHOD'] === 'GET')" in page and
          "zigmon_relay('/api/osroots')" in page, 'the card\'s roads are not in the relay')
    shutil.copytree(str(HERE / 'web'), str(W / 'web'))
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

    def relay(what, body=None, session=S):
        req = urllib.request.Request('http://127.0.0.1:%d/?api=%s' % (PHP_PORT, what),
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json',
                                              'Cookie': 'zigmon_session=%s' % session},
                                     method='GET' if body is None else 'POST')
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b'{}')
            except ValueError:
                return e.code, {}
    code, out = relay('osroots')
    check(code == 200 and [c['cn'] for c in out.get('certs', [])] == ['Example Corp Issuing CA 1', 'Example Corp Root CA'],
          'GET through the relay: %s %r' % (code, str(out)[:200]))
    code, out = relay('osroots-do', {'action': 'check', 'text': ROOT})
    check(code == 200 and out.get('certs', [{}])[0].get('already') is True, 'POST through the relay: %s %r' % (code, out))
    code, out = relay('osroots', session=S_OP)
    check(code == 403, 'an operator through the relay: %s' % code)

    # ---- the card in Chromium ---------------------------------------------------------------------------
    print('the card')
    for c in list(zigmon.osr_want(d)['certs']):
        osr({'action': 'remove', 'fp': c['fp']})
    settle()
    root = sh(['npm', 'root', '-g']).stdout.strip()
    js = r'''
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({viewport: {width: 1400, height: 1100}, deviceScaleFactor: 2, colorScheme: 'dark'});
  await ctx.addCookies([{name: 'zigmon_session', value: %(s)s, url: 'http://127.0.0.1:%(port)d/'}]);
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.goto('http://127.0.0.1:%(port)d/#control/sys-certs');
  await p.waitForTimeout(2500);
  try { await p.evaluate(() => showControlSection('sys-certs')); } catch (e) {}
  await p.waitForSelector('#osr-box', {timeout: 20000});
  const r = {};
  const card = await p.$('#osr-card');
  await card.scrollIntoViewIfNeeded();
  r.title = await p.textContent('#osr-card h2');
  r.empty = await p.evaluate(() => (document.querySelector('#osr-box > p.note') || {}).textContent || '');
  r.status0 = await p.textContent('#osr-status');
  r.others = await p.evaluate(() => Array.from(document.querySelectorAll('#osr-others li')).map(l => l.dataset.file));
  r.facts = await p.evaluate(() => Array.from(document.querySelectorAll('#osr-node .net-fact .k')).map(t => t.textContent));
  await card.screenshot({path: %(shot)s + '01-empty.png'});
  await p.click('#osr-add');
  await p.waitForSelector('#osr-text');
  await p.fill('#osr-text', %(inter_leaf)s);
  await p.waitForSelector('#osr-seen .osr-one', {timeout: 15000});
  await p.waitForTimeout(300);
  r.seen1 = await p.evaluate(() => Array.from(document.querySelectorAll('#osr-seen .osr-one')).map(o => ({
    cn: o.querySelector('b').textContent, tag: o.querySelector('.tag').textContent,
    warn: Array.from(o.querySelectorAll('.osr-w')).map(x => x.textContent),
    refused: Array.from(o.querySelectorAll('.osr-r')).map(x => x.textContent)})));
  await (await p.$('#zmodal-box')).screenshot({path: %(shot)s + '02-add-check-warn.png'});
  /* typing: one check 400 ms after the last key, not one a key */
  const asked = [];
  p.on('request', q => { if (q.url().includes('api=osroots-do')) asked.push(q.postData()); });
  await p.fill('#osr-text', '');
  await p.type('#osr-text', '-----BEGIN', {delay: 30});
  await p.waitForTimeout(900);
  r.asked_typing = asked.length;
  /* a DER file, made PEM in the browser */
  await p.setInputFiles('#osr-file', %(der)s);
  await p.waitForFunction(() => document.querySelectorAll('#osr-seen .osr-one').length === 1 &&
    document.querySelector('#osr-seen .osr-one b').textContent === 'Example Corp Root CA', null, {timeout: 15000});
  r.der_text = await p.inputValue('#osr-text');
  await p.fill('#osr-text', %(root_inter)s);
  await p.waitForFunction(() => document.querySelectorAll('#osr-seen .osr-one').length === 2, null, {timeout: 15000});
  await p.waitForTimeout(300);
  r.seen2 = await p.evaluate(() => Array.from(document.querySelectorAll('#osr-seen .osr-one')).map(o => ({
    tag: o.querySelector('.tag').textContent, warn: o.querySelectorAll('.osr-w').length})));
  await (await p.$('#zmodal-box')).screenshot({path: %(shot)s + '03-add-check-ok.png'});
  await p.click('#zmodal-foot .btn.primary');
  await p.waitForFunction(() => document.querySelectorAll('#osr-box tr[data-fp]').length === 2, null, {timeout: 20000});
  await p.waitForFunction(() => (document.getElementById('osr-status') || {}).textContent === 'as wanted', null, {timeout: 30000});
  r.rows = await p.evaluate(() => Array.from(document.querySelectorAll('#osr-box tr[data-fp] .osr-auth b')).map(b => b.textContent));
  r.issuer = await p.evaluate(() => document.querySelectorAll('#osr-box tr[data-fp]')[1].children[1].textContent);
  r.heads = await p.evaluate(() => Array.from(document.querySelectorAll('#osr-box th')).map(t => t.textContent));
  r.status = await p.textContent('#osr-status');
  r.ours = await p.evaluate(() => { const f = Array.from(document.querySelectorAll('#osr-node .net-fact'));
    const x = f.find(e => e.querySelector('.k').textContent.startsWith('zigmon')); return x ? x.querySelector('.v').textContent : ''; });
  r.py = await p.evaluate(() => !!document.getElementById('osr-py'));
  await card.screenshot({path: %(shot)s + '04-standalone.png'});
  await p.click('#osr-box tr[data-fp] .osr-rm');
  await p.waitForSelector('#zmodal:not([hidden])');
  r.confirm = await p.textContent('#zmodal-body');
  await (await p.$('#zmodal-box')).screenshot({path: %(shot)s + '06-remove-confirm.png'});
  await p.click('#zmodal-foot .btn.danger');
  await p.waitForFunction(() => document.querySelectorAll('#osr-box tr[data-fp]').length === 1, null, {timeout: 20000});
  r.after = await p.evaluate(() => Array.from(document.querySelectorAll('#osr-box tr[data-fp] .osr-auth b')).map(b => b.textContent));
  /* a phone: no page wider than the screen */
  await p.setViewportSize({width: 390, height: 900});
  await p.waitForTimeout(500);
  r.wide = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  r.errors = errors;
  console.log(JSON.stringify(r));
  await b.close();
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
    (W / 'card.js').write_text(js % {'s': json.dumps(S), 'port': PHP_PORT, 'shot': json.dumps(str(W) + '/'),
                                     'inter_leaf': json.dumps(INTER + LEAF), 'root_inter': json.dumps(ROOT + INTER),
                                     'der': json.dumps(str(CA / 'root.cer'))})
    got = sh(['node', str(W / 'card.js')], timeout=240, env=dict(os.environ, NODE_PATH=root))
    try:
        r = json.loads(got.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        r = {'error': (got.stdout + got.stderr)[-300:]}
    if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
        print('  SKIPPED (no browser here): %s' % r['error'][:200])
    else:
        check(not r.get('error'), 'the card in Chromium: %s' % r.get('error'))
        check((r.get('title') or '').startswith('Trusted roots of the system'), 'the title: %r' % r.get('title'))
        check('has added none' in (r.get('empty') or ''), 'the empty card: %r' % r.get('empty'))
        check(r.get('status0') == 'as wanted', 'the status with nothing wanted: %r' % r.get('status0'))
        check(r.get('others') == ['corp/other.crt', 'evil.crt', 'lab-ldaps-ca.crt', 'pipe.crt'], 'others: %r' % r.get('others'))
        check((r.get('facts') or [])[:2] == ['The system’s own list', 'Its package'], 'facts: %r' % r.get('facts'))
        s1 = r.get('seen1') or []
        check(len(s1) == 2 and s1[0]['tag'] == 'intermediate' and s1[0]['warn'] == [zigmon.OSR_NO_ROOT_WARN] and
              s1[1]['tag'] == 'not taken' and 'CA:FALSE' in ' '.join(s1[1]['refused']), 'the check as typed: %r' % s1)
        check(r.get('asked_typing') == 1, 'typing asked %r times, not once after 400 ms' % r.get('asked_typing'))
        check((r.get('der_text') or '').startswith('-----BEGIN CERTIFICATE-----\n') and
              fp_of(r.get('der_text') or '-----x-----x-----') == FP_ROOT, 'the DER file was not made PEM')
        check(r.get('seen2') == [{'tag': 'root', 'warn': 0}, {'tag': 'intermediate', 'warn': 0}], 'a whole chain: %r' % r.get('seen2'))
        check(r.get('rows') == ['Example Corp Root CA', 'Example Corp Issuing CA 1'], 'the table: %r' % r.get('rows'))
        check(r.get('issuer') == 'Example Corp Root CA', 'issued by: %r' % r.get('issuer'))
        check(r.get('heads') == ['Authority', 'Issued by', 'Valid', 'Key', 'SHA-256', ''], 'the heads: %r' % r.get('heads'))
        check(r.get('ours') == '2' and r.get('status') == 'as wanted', 'the machine\'s box: %r' % r)
        check('Example Corp Root CA' in (r.get('confirm') or '') and FP_ROOT[:16] in (r.get('confirm') or ''),
              'the confirmation: %r' % r.get('confirm'))
        check(r.get('after') == ['Example Corp Issuing CA 1'], 'after the removal: %r' % r.get('after'))
        check(r.get('wide') == 0, 'the page is wider than a phone: %r' % r.get('wide'))
        check(not r.get('errors'), 'the page threw: %r' % r.get('errors'))
        check(ours() == ['zigmon-%s.crt' % FP_INTER[:16]], 'the machine after the card: %r' % ours())
        if os.environ.get('OSR_SHOTS'):
            os.makedirs(os.environ['OSR_SHOTS'], exist_ok=True)
            for n in ('01-empty', '02-add-check-warn', '03-add-check-ok', '04-standalone', '06-remove-confirm'):
                if (W / (n + '.png')).exists():
                    shutil.copy(str(W / (n + '.png')), os.path.join(os.environ['OSR_SHOTS'], n + '.png'))
finally:
    for p in PROCS:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    try:
        if api is not None:
            api.stop()
    except Exception:                                    # noqa: BLE001
        pass

if bad:
    print('\n%d problem(s)' % len(bad))
    raise SystemExit(1)
shutil.rmtree(str(W), ignore_errors=True)
print('\nthe system\'s trusted roots: every check passed')
