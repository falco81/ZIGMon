#!/usr/bin/env python3
"""5.30: install.sh brings the dashboard's PHP to 8.3.36 - the 8.3 release
with the php2shell fix - at every install and upgrade, and puts back what was
there when the new one does not run. Fails on 5.29.7 (no such step).

    python3 test/php.py

The PHP functions of install.sh are run with dnf, rpm, php, php-fpm and
systemctl stood in for by scripts that keep the machine's state in a file.
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
start = src.find('php_version() {')
end = src.find('# The dashboard holds one php-fpm worker')
if start < 0 or end < 0:
    print('  FAILED: install.sh has no step that brings PHP to 8.3.36')
    os._exit(1)
funcs = src[start:end]
head = '\n'.join(l for l in src.splitlines() if re.match(r'^(PHP_BRANCH|PHP_PATCH)=', l))

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
st_file = os.environ['FAKE_STATE']
st = json.load(open(st_file))
me = os.path.basename(sys.argv[0]); a = sys.argv[1:]
log = st.setdefault('log', []); log.append(' '.join([me] + a))
out = ''
code = 0
def save():
    json.dump(st, open(st_file, 'w'))
if me in ('php', 'php-fpm'):
    if '-v' in a:
        out = 'PHP %s (fpm-fcgi)\n' % st['version'] if st.get('version') else ''
        code = 0 if st.get('version') else 1
    elif '-t' in a or '-l' in a:
        code = 0 if st.get('works', True) and st.get('version') else 1
elif me == 'systemctl':
    code = 0 if st.get('works', True) else 1
elif me == 'rpm':
    pkg = a[-1]
    code = 0 if pkg in st.get('installed', []) or (pkg.startswith('php') and st.get('version')) else 1
elif me == 'dnf':
    words = [x for x in a if not x.startswith('-')]
    if words[:2] == ['module', 'list']:
        if '--enabled' in a:
            out = ('php %s [e]\n' % st['stream']) if st.get('stream') else ''
        else:
            out = ''.join('php %s\n' % k for k in st['streams'] if not k.startswith('remi') or 'remi-release' in st.get('installed', []))
    elif words[:2] == ['module', 'reset']:
        st['stream'] = ''
    elif words[:2] == ['module', 'enable']:
        st['stream'] = words[2].split(':', 1)[1]
    elif words[:1] == ['distro-sync']:
        st['version'] = st['streams'].get(st.get('stream') or st.get('default_stream', ''), st.get('version'))
        st['works'] = st.get('works_on', {}).get(st.get('stream') or '', True)
    elif words[:1] == ['upgrade']:
        st['version'] = st.get('upgrade_to') or st['version']
    elif words[:1] == ['install']:
        for w in words[1:]:
            if 'remi-release' in w:
                if not st.get('remi_reachable', True):
                    code = 1
                else:
                    st.setdefault('installed', []).append('remi-release')
            else:
                st.setdefault('installed', []).append(w)
save()
sys.stdout.write(out)
sys.exit(code)
'''


def run(state, keep=''):
    w = Path(tempfile.mkdtemp(prefix='zigmon-php-check-'))
    bin_ = w / 'bin'
    bin_.mkdir()
    for name in ('dnf', 'rpm', 'php', 'php-fpm', 'systemctl'):
        (bin_ / name).write_text(FAKE)
        (bin_ / name).chmod(0o755)
    sf = w / 'state.json'
    sf.write_text(json.dumps(state))
    (w / 'os-release').write_text('VERSION_ID="9.6"\n')
    script = '''set -euo pipefail
%s
WITH_WEB=yes DRY_RUN="" KEEP_PHP="%s" WEB_DIR=%s
step() { echo "== $*"; }; say() { echo "   $*"; }; good() { echo "OK $*"; }
warn() { echo "WARN $*"; }; note() { echo "   $*"; }
%s
ensure_php
''' % (head, keep, w, funcs)
    got = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                         env=dict(os.environ, PATH='%s:%s' % (bin_, os.environ['PATH']), FAKE_STATE=str(sf)))
    return json.loads(sf.read_text()), got.stdout + got.stderr, got.returncode


print('PHP is brought to 8.3.36 at an install and an upgrade')
st, out, rc = run({'version': '8.3.40', 'stream': '8.3', 'streams': {'8.3': '8.3.40'}})
check(rc == 0 and not [l for l in st['log'] if l.startswith('dnf')], '8.3.40 was touched: %r' % st['log'])
st, out, rc = run({'version': '8.4.30', 'stream': '8.4', 'streams': {'8.4': '8.4.30'}})
check(st['version'] == '8.4.30', 'a newer branch that has the fix was taken back to 8.3')
st, out, rc = run({'version': '8.3.20', 'stream': '8.3', 'streams': {'8.3': '8.3.36'}, 'upgrade_to': '8.3.36'})
check(st['version'] == '8.3.36' and st['stream'] == '8.3', 'an update within the stream did not bring 8.3.36: %r' % st)
st, out, rc = run({'version': '8.2.10', 'stream': '8.2', 'streams': {'8.2': '8.2.10', '8.3': '8.3.38'}})
check(st['version'] == '8.3.38' and st['stream'] == '8.3', 'PHP 8.2 was not moved to the system\'s 8.3 stream: %r' % st)
st, out, rc = run({'version': '8.2.10', 'stream': '8.2', 'installed': ['epel-release'],
                   'streams': {'8.2': '8.2.10', '8.3': '8.3.19', 'remi-8.3': '8.3.36'}})
check(st['version'] == '8.3.36' and st['stream'] == 'remi-8.3' and 'remi-release' in st.get('installed', []),
      'an 8.3 stream too old was not followed by Remi\'s: %r' % {k: st[k] for k in ('version', 'stream')})
st, out, rc = run({'version': '8.2.10', 'stream': '8.2', 'installed': ['epel-release'],
                   'streams': {'8.2': '8.2.10', '8.3': '8.3.19', 'remi-8.3': '8.3.36'},
                   'works_on': {'remi-8.3': False}})
check(st['version'] == '8.2.10' and st['stream'] == '8.2' and 'WARN' in out,
      'a PHP that does not run was left in, not the old stream put back: %r' % {k: st.get(k) for k in ('version', 'stream')})
st, out, rc = run({'version': '8.2.10', 'stream': '8.2', 'streams': {'8.2': '8.2.10'}}, keep='yes')
check(st['version'] == '8.2.10' and not [l for l in st['log'] if l.startswith('dnf')], '--keep-php did not keep it')
check(rc == 0, 'a failed move stopped the installer (set -e)')

if bad:
    print('\n%d check(s) failed' % len(bad))
    os._exit(1)
print('PHP is 8.3.36 or newer after an install or an upgrade, or put back as it was')
os._exit(0)
