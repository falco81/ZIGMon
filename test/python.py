#!/usr/bin/env python3
"""5.31: install.sh moves the daemon and the zigmon command to the newest
python3.X AlmaLinux 9's repositories offer (3.11, 3.12, ... what a later minor
release adds), gives it paho-mqtt, and stays where it was when the new one
does not run the daemon. The system's own python3 is never touched. Fails on
5.30.0 (no such step).

    python3 test/python.py

The Python functions of install.sh are run with dnf, rpm and the Pythons
stood in for by scripts that keep the machine's state in a file.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)


src = (HERE / 'install.sh').read_text()
start = src.find('# The Python the daemon runs on (5.31')
end = src.find('check_certificate() {')
if start < 0 or end < 0 or start > end:
    print('  FAILED: install.sh has no step that moves the daemon to a newer Python')
    os._exit(1)
funcs = src[start:end]

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
st_file = os.environ['FAKE_STATE']
st = json.load(open(st_file))
me = os.path.basename(sys.argv[0]); a = sys.argv[1:]
st.setdefault('log', []).append(' '.join([me] + a))
code = 0; out = ''
bindir = os.path.dirname(os.path.abspath(sys.argv[0]))
def save():
    json.dump(st, open(st_file, 'w'))
def link_py(n):
    os.symlink(os.path.join(bindir, 'fake'), os.path.join(bindir, 'python3.%d' % n))
if me == 'dnf':
    words = [x for x in a if not x.startswith('-')]
    verb, pkgs = words[0], words[1:]
    if verb == 'list':
        code = 0 if all(p.replace('python3.', '').isdigit() and int(p.replace('python3.', '')) in st['repo'] for p in pkgs) else 1
    elif verb in ('install', 'upgrade'):
        for p in pkgs:
            m = __import__('re').match(r'^python3\.(\d+)(-(.*))?$', p)
            if not m:
                if st.get('deps_ok', True):
                    st.setdefault('installed', []).append(p)
                else:
                    code = 1
                continue
            n, extra = int(m.group(1)), m.group(3)
            if extra is None:
                if n not in st['repo']:
                    code = 1; continue
                if str(n) not in st['pys']:
                    st['pys'][str(n)] = {'mods': [], 'runs': st.get('new_runs', True)}
                    link_py(n)
                st.setdefault('installed', []).append(p)
            elif extra == 'libs':
                pass
            elif extra in st.get('rpms', {}).get(str(n), []):
                mod = {'paho-mqtt': 'paho.mqtt.client', 'pip': 'pip'}.get(extra, extra)
                st['pys'].setdefault(str(n), {'mods': [], 'runs': True})['mods'].append(mod)
                st.setdefault('installed', []).append(p)
            else:
                code = 1
    save()
elif me == 'rpm':
    code = 0 if a[-1] in st.get('installed', []) else 1
elif me == 'curl':
    url = [x for x in a if x.startswith('http')][0]
    org = st.get('org')
    if org is None:
        code = 7
    elif url.endswith('/python/'):
        out = ''.join('<a href="%s/">%s/</a>\n' % (v, v) for v in org['dirs'])
    elif '-o' in a:
        v = url.split('/')[-2]
        import tarfile, io
        dest = a[a.index('-o') + 1]
        with tarfile.open(dest, 'w:xz') as t:
            data = b'#!/bin/sh\nexit 0\n'
            i = tarfile.TarInfo('Python-%s/configure' % v); i.size = len(data); i.mode = 0o755
            t.addfile(i, io.BytesIO(data))
        st['fetched'] = v
    else:
        v = url.split('/')[-2]
        code = 0 if v in org['final'] else 22
    save()
elif me == 'make':
    if 'altinstall' in a:
        v = os.path.basename(os.getcwd())[len('Python-'):]
        n = v.split('.')[1]
        own = os.environ['FAKE_OWN']
        if not os.path.exists(os.path.join(own, 'python3.' + n)):
            os.symlink(os.path.join(bindir, 'fake'), os.path.join(own, 'python3.' + n))
        st['pys']['own' + n] = {'mods': [], 'runs': True, 'patch': int(v.split('.')[2])}
        st['built'] = v
    else:
        code = 0 if st.get('builds', True) else 2
    save()
elif me.startswith('python3'):
    n = me[len('python3.'):] if me != 'python3' else '9'
    own = os.path.dirname(os.path.abspath(sys.argv[0])) == os.environ.get('FAKE_OWN')
    py = st['pys'][('own' + n) if own else n]
    joined = ' '.join(a)
    site = None
    m = __import__('re').search(r"sys\.path\.append\('([^']*)'\)", joined)
    if m: site = m.group(1)
    def has(mod):
        top = mod.split('.')[0]
        if mod in py['mods']: return True
        return bool(site and os.path.isdir(os.path.join(site, top)) and py.get('copy_ok', True))
    if a == ['-V']:
        out = 'Python 3.%s.%d\n' % (n, py.get('patch', 4))
    elif '-c' in a and 'python_version()' in joined:
        out = '3.%s.%d\n' % (n, py.get('patch', 4))
    elif '-c' in a and 'version_info[1]' in joined:
        out = n + '\n'
    elif '-c' in a and 'version_info[:2]' in joined:
        out = '3.%s\n' % n
    elif '-c' in a and '__path__' in joined:
        top = joined.split('import os, ')[1].split(';')[0].strip()
        if top in [x.split('.')[0] for x in py['mods']]:
            out = st['sys_site'] + '\n'
        else:
            code = 1
    elif '-c' in a:
        body = a[a.index('-c') + 1]
        mods = []
        for line in body.splitlines():
            line = line.split(';')[-1].strip()
            if line.startswith('import '):
                mods += [x.strip() for x in line[7:].split(',')]
        code = 0 if all(x in ('sys', 'os') or x in ('ssl', 'sqlite3', 'curses', 'json', 'hashlib', 'ctypes',
                             'http.server', 'email', 'ftplib', 'pty', 'lzma', 'bz2', 'zlib') and py.get('std', True) or has(x) for x in mods) else 1
    elif '-m' in a and 'pip' in a:
        if st.get('pypi') and 'pip' in py['mods']:
            t = a[a.index('--target') + 1]
            os.makedirs(os.path.join(t, 'paho', 'mqtt'), exist_ok=True)
            st['pip_into'] = t
        else:
            code = 1
    elif a and a[0].endswith('zigmon.py'):
        code = 0 if py.get('runs', True) else 1
    save()
sys.stdout.write(out)
sys.exit(code)
'''


def run(state, keep='', unit_py='/usr/bin/python3', nobuild=''):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bindir = tmp / 'bin'; bindir.mkdir()
        lib = tmp / 'lib'; lib.mkdir()
        syssite = tmp / 'site-packages'; (syssite / 'paho' / 'mqtt').mkdir(parents=True)
        (syssite / 'paho' / '__init__.py').write_text('')
        (syssite / 'paho' / 'mqtt' / 'client.py').write_text('# paho\n')
        (syssite / 'paho' / '__pycache__').mkdir()
        fake = bindir / 'fake'
        fake.write_text(FAKE.replace('#!/usr/bin/env python3', '#!' + sys.executable)); fake.chmod(0o755)
        for name in ('dnf', 'rpm', 'python3', 'curl', 'make'):
            (bindir / name).symlink_to(fake)
        own = tmp / 'local-bin'; own.mkdir()
        for n in list(state.get('pys', {})):
            if n.startswith('own'):
                (own / ('python3.' + n[3:])).symlink_to(fake)
        btmp = tmp / 'build'; btmp.mkdir()
        state.setdefault('pys', {})
        state['pys'].setdefault('9', {'mods': ['paho.mqtt.client'], 'runs': True})
        for n in list(state['pys']):
            if n != '9' and not n.startswith('own'):
                (bindir / ('python3.' + n)).symlink_to(fake)
        state['sys_site'] = str(syssite)
        st_file = tmp / 'state.json'
        st_file.write_text(json.dumps(state))
        unit = tmp / 'zigmon.service'
        unit.write_text('[Service]\nExecStart=%s /usr/local/lib/zigmon/zigmon.py\n' %
                        unit_py.replace('/usr/bin', str(bindir)))
        (lib / 'zigmon.py').write_text('#!/usr/bin/env python3\n__version__ = "x"\n')
        script = '''set -u
say() { printf 'SAY %%s\\n' "$*"; }; good() { printf 'GOOD %%s\\n' "$*"; }
warn() { printf 'WARN %%s\\n' "$*"; }; note() { printf 'NOTE %%s\\n' "$*"; }
step() { printf 'STEP %%s\\n' "$*"; }
LIB_DIR=%s UNIT_FILE=%s KEEP_PYTHON="%s" NO_PYTHON_BUILD="%s" DRY_RUN="" ZIGMON_PY=/usr/bin/python3
%s
PY_BIN_DIR=%s PY_OWN_DIR=%s PY_BUILD_TMP=%s PY_BUILD_LOG=%s/build.log PY_SOURCE=https://python.example/ftp/python
ensure_python
python_point_at "$ZIGMON_PY"
echo "CHOSE $ZIGMON_PY"
''' % (lib, unit, keep, nobuild, funcs, bindir, own, btmp, tmp)
        env = dict(os.environ, PATH='%s:%s' % (bindir, os.environ['PATH']), FAKE_STATE=str(st_file), FAKE_OWN=str(own))
        got = subprocess.run(['bash', '-c', script], capture_output=True, text=True, env=env,
                             stdin=subprocess.DEVNULL, timeout=60)
        st = json.loads(st_file.read_text())
        chose = ''.join(l[6:] for l in got.stdout.splitlines() if l.startswith('CHOSE '))
        chose = chose.replace(str(own), '/usr/local/bin').replace(str(bindir), '/usr/bin')
        return {'out': got.stdout + got.stderr, 'st': st, 'chose': chose,
                'unit': unit.read_text().replace(str(own), '/usr/local/bin').replace(str(bindir), '/usr/bin'),
                'shebang': (lib / 'zigmon.py').read_text().splitlines()[0].replace(str(own), '/usr/local/bin').replace(str(bindir), '/usr/bin'),
                'left': sorted(os.listdir(btmp)),
                'site': sorted(str(p.relative_to(lib)) for p in lib.rglob('*'))}


# 1. 3.11 and 3.12 in the repositories, neither installed, paho only on the system Python
r = run({'repo': [11, 12]})
check(r['chose'] == '/usr/bin/python3.12', 'the newest python3.X was not chosen: %r\n%s' % (r['chose'], r['out']))
check('ExecStart=/usr/bin/python3.12 /usr/local/lib/zigmon/zigmon.py' in r['unit'], 'the unit does not start python3.12: ' + r['unit'])
check(r['shebang'] == '#!/usr/bin/python3.12', 'the zigmon command does not run on python3.12: ' + r['shebang'])
check('python3.12/paho/mqtt/client.py' in r['site'], 'paho was not given to python3.12: %r' % r['site'])
check(not [p for p in r['site'] if '__pycache__' in p], 'the system Python\'s compiled files were copied')
check(not [l for l in r['st']['log'] if l.startswith('dnf') and re.search(r'\bpython3(\s|$)', l)],
      'the system python3 was touched by dnf')

# 2. a later minor release offers 3.13: that one
r = run({'repo': [11, 12, 13]})
check(r['chose'] == '/usr/bin/python3.13', '3.13 offered but not chosen: %r' % r['chose'])

# 3. the new one does not run the daemon: it stays where it was
r = run({'repo': [12], 'new_runs': False})
check(r['chose'] == '/usr/bin/python3', 'a Python that does not run the daemon was switched to: %r' % r['chose'])
check('ExecStart=/usr/bin/python3 /usr/local' in r['unit'], 'the unit left the working Python: ' + r['unit'])
check('WARN' in r['out'], 'nothing said about the Python that did not run it')

# 4. --keep-python: the one the unit starts now, nothing asked of dnf
r = run({'repo': [12, 13], 'pys': {'12': {'mods': ['paho.mqtt.client'], 'runs': True}}},
        keep='yes', unit_py='/usr/bin/python3.12')
check(r['chose'] == '/usr/bin/python3.12', '--keep-python moved it: %r' % r['chose'])
check(not [l for l in r['st']['log'] if l.startswith('dnf')], '--keep-python asked dnf')

# 5. the repositories build paho for it: their RPM, nothing copied
r = run({'repo': [12], 'rpms': {'12': ['paho-mqtt']}})
check(r['chose'] == '/usr/bin/python3.12', 'not moved with paho from its RPM: %r' % r['chose'])
check('python3.12-paho-mqtt' in r['st'].get('installed', []), 'its own paho RPM was not installed')
check(not [p for p in r['site'] if p.startswith('python3.12/paho')], 'paho copied though its RPM is there')

# 6. nothing newer than the system's: it stays, nothing installed
r = run({'repo': []})
check(r['chose'] == '/usr/bin/python3', 'moved though nothing newer: %r' % r['chose'])
check(not r['st'].get('installed'), 'something installed with nothing newer')

# 7. on 3.12 already: brought to its latest patch
r = run({'repo': [12], 'installed': ['python3.12'], 'pys': {'12': {'mods': ['paho.mqtt.client'], 'runs': True}}},
        unit_py='/usr/bin/python3.12')
check(r['chose'] == '/usr/bin/python3.12', 'left 3.12: %r' % r['chose'])
check([l for l in r['st']['log'] if l.startswith('dnf') and ' upgrade ' in ' %s ' % l and 'python3.12' in l],
      'python3.12 not brought to its latest patch')

# 8. the copy fails and there is no PyPI: it stays
r = run({'repo': [12], 'pys': {'9': {'mods': [], 'runs': True}}})
check(r['chose'] == '/usr/bin/python3', 'moved with no paho for it: %r' % r['chose'])

ORG = {'dirs': ['3.13.9', '3.14.4', '3.14.6', '3.14.7', '3.15.0'], 'final': ['3.13.9', '3.14.4', '3.14.6', '3.15.0']}

# 11. no repository has 3.14: the newest 3.14 release built from python.org
r = run({'repo': [11, 12], 'org': ORG})
check(r['chose'] == '/usr/local/bin/python3.14', '3.14 not built where no repository has it: %r\n%s' % (r['chose'], r['out']))
check(r['st'].get('built') == '3.14.6', 'not the newest final 3.14 release built (3.14.7 has only rc tarballs): %r' % r['st'].get('built'))
check('ExecStart=/usr/local/bin/python3.14 ' in r['unit'], 'the unit does not start the built 3.14: ' + r['unit'])
check(r['shebang'] == '#!/usr/local/bin/python3.14', 'the command does not run on the built 3.14: ' + r['shebang'])
check('python3.14/paho/mqtt/client.py' in r['site'], 'paho not given to the built 3.14: %r' % r['site'])
check(not r['left'], 'the build folder was left behind: %r' % r['left'])
check([l for l in r['st']['log'] if l.startswith('make') and '-j' in l] and
      [l for l in r['st']['log'] if 'openssl-devel' in l], 'not built with make against the system openssl')

# 12. built already at the newest: not built again
r = run({'repo': [12], 'org': ORG, 'pys': {'own14': {'mods': ['paho.mqtt.client'], 'runs': True, 'patch': 6}}},
        unit_py='/usr/local/bin/python3.14')
check(r['chose'] == '/usr/local/bin/python3.14', 'left the built 3.14: %r' % r['chose'])
check('built' not in r['st'], 'built again though it is the newest')

# 13. a newer 3.14 release: built again
r = run({'repo': [12], 'org': ORG, 'pys': {'own14': {'mods': ['paho.mqtt.client'], 'runs': True, 'patch': 4}}},
        unit_py='/usr/local/bin/python3.14')
check(r['st'].get('built') == '3.14.6', '3.14.4 not brought to 3.14.6: %r' % r['st'].get('built'))

# 14. python.org not reachable, built one there: kept; none: the repositories' newest
r = run({'repo': [12], 'pys': {'own14': {'mods': ['paho.mqtt.client'], 'runs': True, 'patch': 4}}},
        unit_py='/usr/local/bin/python3.14')
check(r['chose'] == '/usr/local/bin/python3.14', 'the built 3.14 dropped with python.org away: %r' % r['chose'])
r = run({'repo': [11, 12]})
check(r['chose'] == '/usr/bin/python3.12', 'not the repositories\' newest with python.org away: %r' % r['chose'])

# 15. the build fails: the repositories' newest, the log kept, nothing left
r = run({'repo': [12], 'org': ORG, 'builds': False})
check(r['chose'] == '/usr/bin/python3.12', 'a failed build not fallen back from: %r' % r['chose'])
check(not r['left'], 'a failed build left its folder: %r' % r['left'])

# 16. the repositories carry 3.14 (EPEL): theirs, nothing built
r = run({'repo': [12, 14], 'org': ORG})
check(r['chose'] == '/usr/bin/python3.14', 'the repositories\' 3.14 not taken: %r' % r['chose'])
check('built' not in r['st'] and 'fetched' not in r['st'], 'built though the repositories carry it')

# 17. --no-python-build: never built
r = run({'repo': [12], 'org': ORG}, nobuild='yes')
check(r['chose'] == '/usr/bin/python3.12' and 'fetched' not in r['st'], '--no-python-build built it: %r' % r['chose'])

# 9. the daemon looks in its own folder of packages for that Python
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / 'zigmon.py').write_text((HERE / 'zigmon.py').read_text())
    v = '%d.%d' % sys.version_info[:2]
    pkg = tmp / ('python' + v) / 'paho' / 'mqtt'
    pkg.mkdir(parents=True)
    (pkg.parent / '__init__.py').write_text('')
    (pkg / '__init__.py').write_text('')
    (pkg / 'client.py').write_text('ZIGMON_TEST_PAHO = 1\n')
    got = subprocess.run([sys.executable, '-c', '''
import importlib.util as u, sys
s = u.spec_from_file_location("zigmon_t", sys.argv[1]); m = u.module_from_spec(s); s.loader.exec_module(m)
print(getattr(m.mqtt, "ZIGMON_TEST_PAHO", None) if m.mqtt else None)
''', str(tmp / 'zigmon.py')], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
        cwd=str(tmp))
    check(got.stdout.strip() == '1',
          'zigmon.py does not look in its own python%s folder: %r %r' % (v, got.stdout, got.stderr[-300:]))

# 10. the option is offered
check('--keep-python' in src and 'KEEP_PYTHON="yes"' in src, 'no --keep-python option')
check(len(re.findall(r'install_program\n\s+ensure_python\b', src)) >= 2,
      'ensure_python is not run in both the install and the upgrade')

print('python: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
sys.exit(1 if bad else 0)
