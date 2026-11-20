#!/usr/bin/env python3
"""5.56 bug hunt (a): the upgrade's file beside the pages, SELinux's local rules.

  * /healthz says "in maintenance" only while an upgrade runs: once the file says
    done or failed and zigmon does not answer, the machine is down - what watches
    it must not see maintenance (and hold its alerts) for ten minutes. Every other
    relayed call keeps answering "upgrading" as before;
  * a rule of zigmon's local list allows a refusal only while its module
    (zigmon_local) is in the policy: taken out (install.sh --uninstall, which keeps
    root's folder, or semodule -r by hand) the refusal is a rule to put in again -
    not "allowed now", hidden with no button; put right, the module goes in again.

    python3 test/review556_hunt_a.py

Ports 20450 (a daemon that is not there) only.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
W = Path(tempfile.mkdtemp(prefix='zigmon-review556a-'))
API_PORT = 20450
bad = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def finish():
    if not os.environ.get('REVIEW556_KEEP'):
        shutil.rmtree(W, ignore_errors=True)
    print('review556_hunt_a: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
    sys.exit(1 if bad else 0)


def sh(cmd, **kw):
    if 'input' not in kw:
        kw.setdefault('stdin', subprocess.DEVNULL)
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ---------------------------------------------------------------------------------------
# 1. /healthz after an upgrade that ended, zigmon not answering
# ---------------------------------------------------------------------------------------
print('PHP: /healthz in maintenance only while an upgrade runs')
if not shutil.which('php'):
    print('  SKIPPED (no php here)')
else:
    WEB = W / 'web'
    shutil.copytree(HERE / 'web', WEB)
    api_php = (WEB / 'zigmon-api.php').read_text()
    check("const ZIGMON_PORT  = 9849;" in api_php, 'the port line of zigmon-api.php is not where it was')
    api_php = api_php.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
    api_php = api_php.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';",
                              "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
    (WEB / 'zigmon-api.php').write_text(api_php)
    (W / 'token').write_text('tok-0123456789abcdef\n')
    UPG = WEB / '.upgrade.json'

    def put(state, ago=5):
        now = int(time.time())
        UPG.write_text(json.dumps({'state': state, 'id': 'k1', 'version': '5.99.0', 'from': '5.98.0',
                                   'by': 'owner on the dashboard', 'part': 3, 'parts': 16, 'words': 'Program files',
                                   'started': now - ago - 60, 'at': now - ago, 'said': '', 'downgrade': False}))

    def relay(path):
        script = W / 'probe.php'
        script.write_text("<?php\ndeclare(strict_types=1);\nrequire %s;\nzigmon_relay(%s);\n"
                          % (json.dumps(str(WEB / 'zigmon-api.php')), json.dumps(path)))
        got = sh(['php', str(script)], timeout=60)
        try:
            return json.loads(got.stdout)
        except ValueError:
            check(False, 'php said no JSON for %s: %r %r' % (path, got.stdout[-300:], got.stderr[-300:]))
            return {}

    put('running')
    got = relay('/api/healthz')
    check(got.get('state') == 'in maintenance' and (got.get('upgrading') or {}).get('state') == 'running',
          'healthz while an upgrade runs and zigmon is away is no longer maintenance: %r' % got)
    for state in ('failed', 'done'):
        put(state)
        got = relay('/api/healthz')
        check('upgrading' not in got and got.get('state') != 'in maintenance'
              and 'not responding' in str(got.get('error')),
              'healthz after an upgrade that %s, zigmon not answering, says maintenance: %r' % (state, got))
        got = relay('/api/status')
        check((got.get('upgrading') or {}).get('state') == state,
              'the status relayed after an upgrade that %s no longer carries it: %r' % (state, got))
    UPG.unlink()
    got = relay('/api/healthz')
    check('upgrading' not in got and 'not responding' in str(got.get('error')), 'healthz with no file: %r' % got)


# ---------------------------------------------------------------------------------------
# 2. SELinux: a local rule whose module is not in the policy allows nothing
# ---------------------------------------------------------------------------------------
print('root: a local rule allows only while zigmon_local is in the policy')
HELPER = HERE / 'deploy' / 'zigmon_root.py'
STATE, OWN, ETC = W / 'state', W / 'own', W / 'etc'
RUN, WWW, LIB = W / 'run' / 'zigmon', W / 'www' / 'zigmon', W / 'lib'
for d in (STATE / 'root', ETC / 'zigmon', ETC / 'nginx' / 'conf.d', ETC / 'selinux', RUN, WWW, LIB):
    d.mkdir(parents=True, exist_ok=True)
(RUN / 'api-token').write_text('tok\n')
(ETC / 'zigmon' / 'config.json').write_text(json.dumps({'api_port': 9849, 'state_dir': str(STATE)}))
NGINX_CONF = ETC / 'nginx' / 'conf.d' / 'zigmon.conf'
NGINX_CONF.write_text('server {\n    listen 80;\n}\n')
SE_CONFIG = ETC / 'selinux' / 'config'
SE_CONFIG.write_text('SELINUX=permissive\nSELINUXTYPE=targeted\n')
CMDLINE = W / 'cmdline'
CMDLINE.write_text('BOOT_IMAGE=/vmlinuz ro quiet\n')
CIL = LIB / 'zigmon_server.cil'
shutil.copy(HERE / 'deploy' / 'zigmon_server.cil', CIL)
LABELS = W / 'labels.json'
LABELS.write_text('{}')
FAKE_STATE, FAKE_LOG = W / 'se.json', W / 'se.log'
BIN = W / 'sebin'
BIN.mkdir()
LOCAL_DIR = OWN / 'selinux-local'
T0 = time.time() - 3600
head = 'msg=audit(%.3f:%d):' % (T0, 5001)
comm = 'zigmon tick'.encode().hex().upper()
RAW = '\n'.join([
    'type=AVC %s avc:  denied  { nnp_transition } for  pid=4242 comm=%s '
    'scontext=system_u:system_r:unconfined_service_t:s0 tcontext=system_u:object_r:chronyc_t:s0 '
    'tclass=process2 permissive=1' % (head, comm),
    'type=SYSCALL %s arch=c000003e syscall=59 success=yes exit=0 items=0 ppid=1 pid=4242 comm=%s '
    'exe="/usr/bin/python3.9" subj=system_u:system_r:unconfined_service_t:s0 key=(null)' % (head, comm),
    'type=PROCTITLE %s proctitle=%s' % (head, ('/usr/bin/python3 -I %s/zigmon.py' % LIB).replace(' ', '\0')
                                         .encode().hex().upper())])


def machine(modules):
    FAKE_STATE.write_text(json.dumps({'mode': 'Permissive', 'modules': modules, 'raw': RAW, 'bools': {},
                                      'semodule_fail': False}))
    if FAKE_LOG.exists():
        FAKE_LOG.unlink()


def fake():
    return json.loads(FAKE_STATE.read_text())


(BIN / 'sefake').write_text(r'''#!%(py)s -I
import json, os, sys
S, LOG = %(state)r, %(log)r
name = os.path.basename(sys.argv[0])
a = sys.argv[1:]
s = json.load(open(S))
with open(LOG, 'a') as f:
    f.write('%%s %%s\n' %% (name, ' '.join(a)))
def save():
    json.dump(s, open(S, 'w'))
if name == 'getenforce':
    print(s['mode'])
elif name == 'semodule':
    if a == ['-l']:
        print('\n'.join(s['modules']))
    elif a[:1] == ['-i']:
        mod = os.path.basename(a[1]).rsplit('.', 1)[0]
        if mod not in s['modules']:
            s['modules'].append(mod)
        save()
    elif a[:1] == ['-r']:
        s['modules'] = [m for m in s['modules'] if m != a[1]]; save()
elif name == 'getsebool':
    print('%%s --> off' %% (a[0] if a else 'x'))
elif name == 'semanage':
    if a[:2] == ['port', '-l']:
        print('http_port_t                  tcp   80, 443')
elif name == 'matchpathcon':
    for p in a:
        print('%%s\tsystem_u:object_r:var_t:s0' %% p)
elif name == 'ausearch':
    print('----\ntime->Tue Nov 17 08:00:00 2026')
    print(s['raw'])
elif name == 'audit2why':
    for line in sys.stdin.read().splitlines():
        print(line)
        print('\n\tWas caused by:\n\t\tMissing type enforcement (TE) allow rule.\n')
''' % {'py': sys.executable, 'state': str(FAKE_STATE), 'log': str(FAKE_LOG)})
(BIN / 'sefake').chmod(0o755)
for tool in ('getenforce', 'semodule', 'getsebool', 'semanage', 'matchpathcon', 'ausearch', 'audit2why',
             'restorecon'):
    (BIN / tool).symlink_to(BIN / 'sefake')
ENV = dict(os.environ, ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(OWN),
           ZIGMON_CONFIG=str(ETC / 'zigmon' / 'config.json'), ZIGMON_NGINX_CONF=str(NGINX_CONF),
           ZIGMON_NO_SERVICES='1', ZIGMON_USER='root', ZIGMON_SELINUX_CONFIG=str(SE_CONFIG),
           ZIGMON_SELINUX_RELABEL=str(W / 'autorelabel'), ZIGMON_SELINUX_CMDLINE=str(CMDLINE),
           ZIGMON_SELINUX_CIL=str(CIL), ZIGMON_SELINUX_RUN=str(RUN), ZIGMON_SELINUX_WEB=str(WWW),
           ZIGMON_SELINUX_LABELS=str(LABELS), ZIGMON_SELINUX_BIN=str(BIN), ZIGMON_SELINUX_AUDITD='active',
           ZIGMON_SELINUX_LIB=str(LIB))


def helper(args):
    got = sh([sys.executable, '-I', str(HELPER)] + args, input=json.dumps({'booleans': [], 'ports': []}),
             env=ENV, timeout=180)
    try:
        return got.returncode, json.loads(got.stdout or 'null'), got
    except ValueError:
        return got.returncode, None, got


def the_rule(c):
    return next((f for f in (c or {}).get('findings') or [] if f.get('target') == 'chronyc_t'), None)


machine(['base', 'zigmon_server'])
rc, c, g = helper(['--selinux-check', '--json'])
f = the_rule(c)
if check(f is not None and f.get('kind') == 'rule', 'the refusal is not a rule to begin with: %r %s' % (f, g.stderr[-400:])):
    rid = f['id']
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    rule = {'id': rid, 'source': 'unconfined_service_t', 'target': 'chronyc_t', 'class': 'process2',
            'perms': ['nnp_transition'], 'why': 'zigmon tick: test', 'program': 'zigmon tick', 'at': T0 + 60,
            'by': 'owner'}
    (LOCAL_DIR / 'rules.json').write_text(json.dumps([rule]))
    # the module in the policy: allowed now, as before
    machine(['base', 'zigmon_server', 'zigmon_local'])
    rc, c, g = helper(['--selinux-check', '--json'])
    check(the_rule(c) is None and (c.get('counts') or {}).get('allowed') == 1,
          'with zigmon_local in the policy its rule no longer allows: %r' % (c or {}).get('counts'))
    # the module taken out, the list left: a rule to put in again
    machine(['base', 'zigmon_server'])
    rc, c, g = helper(['--selinux-check', '--json'])
    f = the_rule(c)
    check(f is not None and f.get('kind') == 'rule' and (c.get('counts') or {}).get('fixable') == 1,
          'a rule whose module is not in the policy hid the refusal as allowed: %r %r'
          % (f, (c or {}).get('counts')))
    check((c.get('local') or {}).get('in_policy') is False, 'the card does not say the module is out: %r'
          % (c or {}).get('local'))
    # put right: the module goes in again, the rule once in the list
    rc, c, g = helper(['--selinux-fix', rid, '--json'])
    check(c and c.get('ok') and 'zigmon_local' in fake()['modules'],
          'putting it right did not put zigmon_local in again: %r %s' % ((c or {}).get('said'), g.stderr[-400:]))
    rules = json.loads((LOCAL_DIR / 'rules.json').read_text())
    check([x['id'] for x in rules] == [rid], 'the rule is in the list twice or not at all: %r' % rules)
    rc, c, g = helper(['--selinux-check', '--json'])
    f = the_rule(c)
    check(f is None or f.get('kind') in ('fixed', 'allowed'), 'put right, it is still to be put right: %r' % f)

finish()
