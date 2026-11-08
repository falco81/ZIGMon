#!/usr/bin/env python3
"""SELinux on this machine (otp 1.0.233 - 1.0.265's, for one machine): Settings -
Security - SELinux, root's helper, the daemon's tick, the API, the command line
and the installer - with getenforce, setenforce, semodule, semanage, getsebool,
setsebool, restorecon, matchpathcon, ausearch, audit2why and grubby stood in for
by one fake that keeps the machine in a JSON file.

  * root's helper: absent (Debian) - nothing to do; Disabled -> prepare (the
    configuration permissive, /.autorelabel, selinux=0 off the command line,
    the module tried; never setenforce); Permissive -> prepare (the module, the
    labels, the boolean, nginx's port with semanage port -a; "applied at" in
    root's own folder) -> enforce (refused while anything is missing, anything
    was refused or auditd does not run; then setenforce 1 and SELINUX=enforcing)
    -> permissive; each refusal in plain words;
  * the allow-lists: a boolean of another name refused, a port type the
    helper does not set left out with a word while the rest goes in; a port of
    another service refused - semanage port -a only, never -m;
  * what was refused counted since "applied at", which a time written into the
    service's own folder does not move; what audit2why says the policy allows
    now told apart as settled; tools run under nice/ionice;
  * the report: no password, key or token in it - not the API token, not the
    configuration's secrets, no PROCTITLE line;
  * the daemon: the first look two minutes after the start, then every half
    hour, at once on a step; a step id tried once; a look or a report never
    puts a pending step aside; the work on a thread of its own at the lowest
    priority; events for each step; a notice when enforcing lacks something;
  * the API: GET and POST /api/selinux an administrator's only (not anybody,
    not an operator); the PHP relay lets both through;
  * the command line: zigmon --selinux-check [--json], --selinux STEP (asks
    first), --selinux-report FILE;
  * the installer: the module put in only when it changed (.in-policy, and
    again after a semodule that failed), restorecon, the matchpathcon word,
    the tools and auditd, nginx's ports (-a, never -m), semodule -r on
    --uninstall;
  * the page (php -S + Chromium): the card in each mode - the pill, the
    checklist, what was refused, the verdict, the buttons each mode has, the
    confirmations, the spinner and the polling while a step is pending, an
    operator kept out, 390 px wide with no sideways scroll.

    python3 test/review548_selinux.py

Every check fails on 5.47.8, which has no SELinux card, no selinux.ask and no
zigmon_server module. Ports 19900 (the daemon) and 19901 (php -S) only.
"""
import base64
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
HELPER = HERE / 'deploy' / 'zigmon_root.py'
W = Path(tempfile.mkdtemp(prefix='zigmon-review548-'))
API_PORT, PHP_PORT = 19900, 19901
SHOTS = os.environ.get('SHOTS') or str(W / 'shots')
bad = []
PROCS = []


def check(ok, what):
    if not ok:
        bad.append(what)
        print('  FAILED: ' + what)
    return ok


def sh(cmd, **kw):
    if 'input' not in kw:
        kw.setdefault('stdin', subprocess.DEVNULL)
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def finish():
    for p in PROCS:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    if not os.environ.get('REVIEW548_KEEP'):
        shutil.rmtree(W, ignore_errors=True)
    print('review548_selinux: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
    os._exit(1 if bad else 0)


# ---- the machine ----------------------------------------------------------------------
STATE, OWN, ETC = W / 'state', W / 'own', W / 'etc'
RUN, WWW, LIB = W / 'run' / 'zigmon', W / 'www' / 'zigmon', W / 'lib'
for d in (STATE / 'root', ETC / 'zigmon', ETC / 'nginx' / 'conf.d', ETC / 'selinux', RUN, WWW, LIB):
    d.mkdir(parents=True, exist_ok=True)
TOKEN = 'tok-5ecret-abcdef0123456789'
(RUN / 'api-token').write_text(TOKEN + '\n')
SMS_PASSWORD = 'Sms-Pa55word-xyz'
(ETC / 'zigmon' / 'config.json').write_text(json.dumps({'db_file': str(STATE / 'z.db'), 'sms_password': SMS_PASSWORD,
                                                        'api_port': API_PORT, 'state_dir': str(STATE),
                                                        'token_file': str(RUN / 'api-token')}))
NGINX_CONF = ETC / 'nginx' / 'conf.d' / 'zigmon.conf'
NGINX_CONF.write_text('server {\n    listen      80;\n    listen [::]:80;\n}\nserver {\n'
                      '    listen      443 ssl http2;\n    listen 8445 ssl;   # a port of its own\n'
                      '    # listen 9999;\n    root /var/www/zigmon;\n}\n')
SE_CONFIG = ETC / 'selinux' / 'config'
SE_CONFIG.write_text('# This file controls the state of SELinux on the system.\nSELINUX=disabled\nSELINUXTYPE=targeted\n')
RELABEL, CMDLINE = W / 'autorelabel', W / 'cmdline'
CMDLINE.write_text('BOOT_IMAGE=(hd0,gpt2)/vmlinuz root=/dev/mapper/al-root ro selinux=0 quiet\n')
CIL = LIB / 'zigmon_server.cil'
shutil.copy(HERE / 'deploy' / 'zigmon_server.cil', CIL)
LABELS = W / 'labels.json'
FAKE_STATE, FAKE_LOG = W / 'se.json', W / 'se.log'
BIN = W / 'sebin'
BIN.mkdir()
NOW = time.time()


def avc(n, t, src, tgt, cls, perms, comm, name=''):
    return ('type=AVC msg=audit(%d.123:%d): avc:  denied  { %s } for  pid=%d comm="%s"%s '
            'scontext=system_u:system_r:%s:s0 tcontext=system_u:object_r:%s:s0 tclass=%s permissive=1'
            % (t, n, perms, 1000 + n, comm, (' name="%s"' % name) if name else '', src, tgt, cls))


OLD_AVC = [avc(i, NOW - 3600, 'httpd_t', 'var_run_t', 'file', 'read', 'php-fpm', 'api-token') for i in range(1, 12)] + \
          [avc(20 + i, NOW - 3500, 'init_t', 'httpd_var_run_t', 'file', 'setattr', 'systemd', 'api-token')
           for i in range(3)] + \
          [avc(30, NOW - 3400, 'sshd_t', 'unreserved_port_t', 'udp_socket', 'name_connect', 'sshd')]   # not ours


def machine(**kw):
    s = {'mode': 'Disabled', 'modules': ['base', 'apache'], 'bools': {'httpd_can_network_connect': False},
         'ports': {'http_port_t/tcp': [[80, 81], [443, 443], [8008, 8009]], 'http_cache_port_t/tcp': [[8080, 8080]],
                   'mysqld_port_t/tcp': [[3306, 3306]], 'ssh_port_t/tcp': [[22, 22]]},
         'avc': list(OLD_AVC), 'allowed': [], 'extra': [], 'semodule_fail': False,
         'fix': {str(RUN): 'httpd_var_run_t', str(RUN / 'api-token'): 'httpd_var_run_t', str(WWW): 'httpd_sys_content_t'}}
    s.update(kw)
    FAKE_STATE.write_text(json.dumps(s))
    LABELS.write_text(json.dumps(kw.get('labels') or {str(RUN): 'httpd_var_run_t', str(RUN / 'api-token'): 'var_run_t',
                                                      str(WWW): 'httpd_sys_content_t'}))
    if FAKE_LOG.exists():
        FAKE_LOG.unlink()


def fake():
    return json.loads(FAKE_STATE.read_text())


def calls():
    return FAKE_LOG.read_text().splitlines() if FAKE_LOG.exists() else []


(BIN / 'sefake').write_text(r'''#!%(py)s -I
import json, os, re, sys
S, LOG, LABELS = %(state)r, %(log)r, %(labels)r
name = os.path.basename(sys.argv[0])
a = sys.argv[1:]
s = json.load(open(S))
with open(LOG, 'a') as f:
    f.write('%%s %%s nice=%%d\n' %% (name, ' '.join(a), os.getpriority(os.PRIO_PROCESS, 0)))
def save():
    json.dump(s, open(S, 'w'))
if name == 'getenforce':
    print(s['mode'])
elif name == 'setenforce':
    if s['mode'] == 'Disabled':
        print('setenforce: SELinux is disabled', file=sys.stderr); sys.exit(1)
    s['mode'] = 'Enforcing' if a == ['1'] else 'Permissive'; save()
elif name == 'semodule':
    if a == ['-l']:
        print('\n'.join(s['modules']))
    elif a[:1] == ['-i']:
        if s['semodule_fail']:
            print('libsemanage: failed', file=sys.stderr); sys.exit(1)
        if 'zigmon_server' not in s['modules']:
            s['modules'].append('zigmon_server')
        save()
    elif a[:1] == ['-r']:
        s['modules'] = [m for m in s['modules'] if m != a[1]]; save()
elif name == 'getsebool':
    if a == ['-a']:
        for k, v in s['bools'].items(): print('%%s --> %%s' %% (k, 'on' if v else 'off'))
    else:
        print('%%s --> %%s' %% (a[0], 'on' if s['bools'].get(a[0]) else 'off'))
elif name == 'setsebool':
    s['bools'][a[1]] = a[2] in ('on', '1'); save()
elif name == 'semanage':
    if a[:2] == ['port', '-l']:
        for k, spans in s['ports'].items():
            t, p = k.split('/')
            print('%%-28s %%-5s %%s' %% (t, p, ', '.join(str(x) if x == y else '%%d-%%d' %% (x, y) for x, y in spans)))
    elif a[:2] == ['port', '-a']:
        t, p, n = a[a.index('-t') + 1], a[a.index('-p') + 1], int(a[-1])
        for k, spans in s['ports'].items():
            if k.endswith('/' + p) and any(x <= n <= y for x, y in spans):
                print('ValueError: Port %%s/%%d already defined' %% (p, n), file=sys.stderr); sys.exit(1)
        s['ports'].setdefault(t + '/' + p, []).append([n, n]); save()
    elif a[:2] == ['fcontext', '-l']:
        pass
elif name == 'restorecon':
    lab = json.load(open(LABELS))
    for p, want in s['fix'].items():
        if any(p == x or p.startswith(x.rstrip('/') + '/') for x in a if x.startswith('/')) and lab.get(p) != want:
            print('Relabeled %%s from system_u:object_r:%%s:s0 to system_u:object_r:%%s:s0' %% (p, lab.get(p), want))
            lab[p] = want
    json.dump(lab, open(LABELS, 'w'))
elif name == 'matchpathcon':
    for p in a:
        print('%%s\tsystem_u:object_r:%%s:s0' %% (p, s['fix'].get(p, 'var_t')))
elif name == 'ausearch':
    for line in s['avc'] + s['extra']:
        print('----\ntime->Sun Nov  8 10:00:00 2026')
        print(line)
elif name == 'audit2why':
    for line in sys.stdin.read().splitlines():
        print(line)
        m = re.search(r'msg=audit\(([0-9.]+:\d+)\)', line)
        if m and m.group(1).split(':')[1] in [str(x) for x in s['allowed']]:
            print('\n\tWas caused by:\n\t\tUnknown - would be allowed by active policy\n')
        elif m:
            print('\n\tWas caused by:\n\t\tMissing type enforcement (TE) allow rule.\n')
elif name == 'audit2allow':
    sys.stdin.read(); print('module zigmon_local 1.0;')
elif name == 'grubby':
    pass
elif name == 'sestatus':
    print('SELinux status: %%s' %% s['mode'].lower())
''' % {'py': sys.executable, 'state': str(FAKE_STATE), 'log': str(FAKE_LOG), 'labels': str(LABELS)})
(BIN / 'sefake').chmod(0o755)
for tool in ('getenforce', 'setenforce', 'semodule', 'getsebool', 'setsebool', 'semanage', 'restorecon',
             'matchpathcon', 'ausearch', 'audit2why', 'audit2allow', 'grubby', 'sestatus'):
    (BIN / tool).symlink_to(BIN / 'sefake')
EMPTY_BIN = W / 'nobin'
EMPTY_BIN.mkdir()

ENV = dict(ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(OWN), ZIGMON_CONFIG=str(ETC / 'zigmon' / 'config.json'),
           ZIGMON_NGINX_CONF=str(NGINX_CONF), ZIGMON_NO_SERVICES='1', ZIGMON_USER='root',
           ZIGMON_SELINUX_CONFIG=str(SE_CONFIG), ZIGMON_SELINUX_RELABEL=str(RELABEL),
           ZIGMON_SELINUX_CMDLINE=str(CMDLINE), ZIGMON_SELINUX_CIL=str(CIL), ZIGMON_SELINUX_RUN=str(RUN),
           ZIGMON_SELINUX_WEB=str(WWW), ZIGMON_SELINUX_LABELS=str(LABELS), ZIGMON_SELINUX_BIN=str(BIN),
           ZIGMON_SELINUX_AUDITD='active')
os.environ.update(ENV)
WANT = {'booleans': [{'name': 'httpd_can_network_connect', 'why': 'the pages ask the daemon on 127.0.0.1:9849'}],
        'ports': []}


def helper(args, want=None, **env):
    e = dict(os.environ, **env)
    got = sh([sys.executable, '-I', str(HELPER)] + args, input=json.dumps(WANT if want is None else want), env=e,
             timeout=120)
    try:
        return got.returncode, json.loads(got.stdout or 'null'), got
    except ValueError:
        return got.returncode, None, got


# ---- root's helper: every transition --------------------------------------------------------
print('root\'s helper: absent, disabled, permissive, enforcing')
machine()
rc, c, g = helper(['--selinux-check', '--json'], ZIGMON_SELINUX_BIN=str(EMPTY_BIN))
check(rc == 0 and c and c.get('mode') == 'absent', 'no getenforce is not "absent": %r %s' % (c, g.stderr[-300:]))
rc, c, g = helper(['--selinux-do', 'prepare', '--json'], ZIGMON_SELINUX_BIN=str(EMPTY_BIN))
check(rc == 1 and c and 'no SELinux on this machine' in (c.get('said') or ''), 'prepare without SELinux: %r' % c)

machine(mode='Disabled')
rc, c, g = helper(['--selinux-check', '--json'])
check(rc == 0 and c and c['mode'] == 'Disabled' and not c['problems'] and c['ready'] is False,
      'disabled is not looked at as it is: %r %s' % (c, g.stderr[-300:]))
check(not any(x.startswith(('setenforce', 'semodule -i', 'setsebool', 'semanage port -a', 'restorecon'))
              for x in calls()), 'a look changed something: %r' % calls())
for step, words in (('enforce', 'from permissive only'), ('permissive', 'disabled')):
    rc, c, g = helper(['--selinux-do', step, '--json'])
    check(rc == 1 and c and words in (c.get('said') or ''), '%s from disabled was not refused plainly: %r' % (step, c))
check('SELINUX=disabled' in SE_CONFIG.read_text(), 'a refused step changed the configuration')
rc, c, g = helper(['--selinux-do', 'prepare', '--json'])
check(rc == 0 and c and c['mode'] == 'Disabled' and c['config'] == 'permissive' and c['relabel_pending'],
      'prepare from disabled: %r %s' % (c, g.stderr[-300:]))
check('SELINUX=permissive' in SE_CONFIG.read_text() and 'SELINUXTYPE=targeted' in SE_CONFIG.read_text()
      and SE_CONFIG.read_text().startswith('# This file'), 'the configuration was not kept as it was but SELINUX=')
check(RELABEL.exists(), '/.autorelabel was not made')
check(any(x.startswith('grubby --update-kernel ALL --remove-args selinux') for x in calls()),
      'selinux=0 was not taken off the command line: %r' % calls())
check(any(x.startswith('semodule -i ' + str(CIL)) for x in calls()), 'the module was not tried while disabled')
check(not any(x.startswith('setenforce') for x in calls()), 'prepare from disabled ran setenforce')
check(any('restart the machine' in x for x in (c or {}).get('said') or []), 'it does not say to restart')

print('permissive: what is missing, put in, counted since then')
RELABEL.unlink()
machine(mode='Permissive')
SE_CONFIG.write_text('SELINUX=permissive\nSELINUXTYPE=targeted\n')
rc, c, g = helper(['--selinux-check', '--json'])
check(rc == 1 and c and c['mode'] == 'Permissive' and c['ready'] is False, 'permissive with things missing: %r' % c)
c = c or {}
check(c.get('module') is False, 'the missing module is not seen')
lab = {x['path']: x for x in c.get('labels') or []}
check(lab.get(str(RUN / 'api-token'), {}).get('ok') is False and lab.get(str(RUN), {}).get('ok') is True,
      'the labels: %r' % lab)
check([(b['name'], b['on']) for b in c.get('booleans') or []] == [('httpd_can_network_connect', False)],
      'the boolean: %r' % c.get('booleans'))
check([(p['port'], p['type'], p['labelled']) for p in c.get('ports') or []] == [(8445, 'http_port_t', False)],
      'nginx\'s own port is not asked for (80, 443 and a commented line are not): %r' % c.get('ports'))
den = c.get('denials') or {}
check(den.get('total') == 14 and den.get('since') == 0 and [g['count'] for g in den.get('groups') or []] == [11, 3],
      'the refusals since the start, grouped, sshd\'s not ours: %r' % den)
check(any('refused 14 thing(s) since the machine started' in p for p in c.get('problems') or []),
      'the problem words: %r' % c.get('problems'))
check(any(' nice=' in x and x.startswith('ausearch') for x in calls()) and
      all(int(x.rsplit('nice=', 1)[1]) == 19 for x in calls() if x.startswith(('ausearch', 'semanage port -l',
                                                                              'semodule -l', 'audit2why'))),
      'the heavy tools do not run at the lowest priority: %r' % [x for x in calls() if x.startswith('ausearch')])
# enforcing refused: what was refused before is still counted on the way to enforcing
rc, c, g = helper(['--selinux-do', 'enforce', '--json'])
check(rc == 1 and c and 'not yet' in (c.get('said') or '') and 'refused 14' in (c.get('said') or ''),
      'enforce with refusals counted was not refused: %r' % c)
check(fake()['mode'] == 'Permissive' and 'SELINUX=permissive' in SE_CONFIG.read_text(), 'enforce went through')
check(not (OWN / 'selinux-applied').exists(), 'the way to enforcing wrote "applied at"')
# put in - from a fresh machine again, so that something changes
machine(mode='Permissive')
rc, c, g = helper(['--selinux-do', 'prepare', '--json'])
c = c or {}
check(rc == 0 and c.get('module') is True and all(x['ok'] for x in c.get('labels') or [])
      and all(b['on'] for b in c.get('booleans') or []) and all(p['labelled'] for p in c.get('ports') or []),
      'what zigmon needs was not put in: %r %s' % (c, g.stderr[-300:]))
check(any(x == 'semanage port -a -t http_port_t -p tcp 8445' or x.startswith('semanage port -a -t http_port_t -p tcp 8445 ')
          for x in calls()), 'nginx\'s port was not labelled with -a: %r' % calls())
check(any(x.startswith('setsebool -P httpd_can_network_connect on') for x in calls()), 'the boolean: %r' % calls())
check(CIL.with_name(CIL.name + '.in-policy').read_text() == CIL.read_text(), 'the .in-policy copy was not made')
applied = json.loads((OWN / 'selinux-applied').read_text()).get('at', 0)
check(abs(applied - time.time()) < 60 and (OWN / 'selinux-applied').stat().st_mode & 0o777 == 0o600,
      '"applied at" is not in root\'s own folder, 0600')
check((c.get('denials') or {}).get('total') == 0 and (c.get('denials') or {}).get('since'),
      'what was refused before the needs were put in still counts: %r' % c.get('denials'))
check(c.get('ready') is True, 'everything in, nothing refused since, and not ready: %r' % c.get('problems'))
said = c.get('said') or []
check(any('module' in x for x in said) and any('8445/tcp labelled' in x for x in said), 'what was done: %r' % said)
# put in again: nothing to do, "applied at" not moved
time.sleep(1.1)
rc, c, g = helper(['--selinux-do', 'prepare', '--json'])
check(json.loads((OWN / 'selinux-applied').read_text()).get('at') == applied,
      '"applied at" moved though nothing was changed')
check(sum(1 for x in calls() if x.startswith('semodule -i')) == 1
      and sum(1 for x in calls() if x.startswith('semanage port -a')) == 1,
      'put in again though it is all in the policy: %r' % calls())
# a time ahead written into the service's own folder does not hide anything
(STATE / 'root' / 'selinux-applied').write_text(json.dumps({'at': NOW + 10 ** 6}))
s = fake()
s['extra'] = [avc(40, time.time() + 1, 'httpd_t', 'var_t', 'dir', 'search', 'nginx', 'zigmon')]
FAKE_STATE.write_text(json.dumps(s))
time.sleep(1.2)
rc, c, g = helper(['--selinux-check', '--json'])
check(c and (c['denials']['total'] == 1) and c['ready'] is False,
      'a refusal after "applied at" is not counted (or the service\'s folder moved it): %r' % (c or {}).get('denials'))
# audit2why: the policy allows it now - settled, not counted
s = fake()
s['allowed'] = [40]
FAKE_STATE.write_text(json.dumps(s))
rc, c, g = helper(['--selinux-check', '--json'])
check(c and c['denials']['total'] == 0 and c['denials']['settled'] == 1 and c['ready'] is True,
      'a refusal the policy allows now is still counted: %r' % (c or {}).get('denials'))
# auditd down: nothing is written down - not ready
rc, c, g = helper(['--selinux-check', '--json'], ZIGMON_SELINUX_AUDITD='inactive')
check(c and c['ready'] is False and any('auditd does not run' in p for p in c['problems']),
      'auditd not running does not stop enforcing: %r' % (c or {}).get('problems'))
rc, c, g = helper(['--selinux-do', 'enforce', '--json'], ZIGMON_SELINUX_AUDITD='inactive')
check(rc == 1 and fake()['mode'] == 'Permissive', 'enforce went through without auditd')
# enforcing, and back
rc, c, g = helper(['--selinux-do', 'enforce', '--json'])
check(rc == 0 and c and c['mode'] == 'Enforcing' and fake()['mode'] == 'Enforcing'
      and 'SELINUX=enforcing' in SE_CONFIG.read_text(), 'enforce when ready: %r %s' % (c, g.stderr[-300:]))
check(any(x.startswith('setenforce 1') for x in calls()), 'setenforce 1 was not run')
check(json.loads((OWN / 'selinux-applied').read_text()).get('at') == applied, 'enforce moved "applied at"')
rc, c, g = helper(['--selinux-do', 'enforce', '--json'])
check(rc == 1 and 'from permissive only' in ((c or {}).get('said') or ''), 'enforce twice: %r' % c)
rc, c, g = helper(['--selinux-do', 'prepare', '--json'])
check(rc == 1 and 'enforcing already' in ((c or {}).get('said') or ''), 'prepare while enforcing: %r' % c)
rc, c, g = helper(['--selinux-do', 'permissive', '--json'])
check(rc == 0 and fake()['mode'] == 'Permissive' and 'SELINUX=permissive' in SE_CONFIG.read_text()
      and any(x.startswith('setenforce 0') for x in calls()), 'back to permissive: %r' % c)

print('the allow-lists; a port never taken from another service')
machine(mode='Permissive')
rc, c, g = helper(['--selinux-do', 'prepare', '--json'],
                  want={'booleans': [{'name': 'allow_execmem', 'why': 'x'}], 'ports': []})
check(rc == 1 and 'a boolean zigmon does not set' in ((c or {}).get('said') or ''), 'a boolean of another name: %r' % c)
check(not any(x.startswith('setsebool') for x in calls()), 'a boolean off the list was set')
rc, c, g = helper(['--selinux-do', 'prepare', '--json'], want=dict(WANT, ports=[
    {'port': 18129, 'proto': 'udp', 'type': 'radius_port_t', 'why': 'a newer need'}]))
check(rc == 0 and c and any('left out' in x and 'radius_port_t' in x for x in c.get('said') or [])
      and any('left out' in x for x in c.get('left_out') or []) and fake()['bools']['httpd_can_network_connect'],
      'a port type the helper does not set refused the rest: %r' % c)
check(not any('radius_port_t' in x for x in calls()), 'the left-out port type was given')
for wrong, words in (({'port': 70000, 'proto': 'tcp', 'type': 'http_port_t'}, '1 to 65535'),
                     ({'port': 'x', 'proto': 'tcp', 'type': 'http_port_t'}, 'a number'),
                     ({'port': 8446, 'proto': 'icmp', 'type': 'http_port_t'}, 'tcp or udp'),
                     ({'port': 8446, 'proto': 'tcp', 'type': 'shadow_t; rm'}, 'a port type zigmon does not set')):
    rc, c, g = helper(['--selinux-do', 'prepare', '--json'], want=dict(WANT, ports=[wrong]))
    check(rc == 1 and words in ((c or {}).get('said') or ''), '%r not refused with "%s": %r' % (wrong, words, c))
NGINX_CONF.write_text(NGINX_CONF.read_text().replace('listen 8445 ssl;', 'listen 3306 ssl;'))
machine(mode='Permissive')
rc, c, g = helper(['--selinux-do', 'prepare', '--json'])
check(rc == 1 and 'another service' in ((c or {}).get('said') or '') and 'choose another port' in c.get('said', ''),
      'a port of another service was not refused plainly: %r' % c)
check(fake()['ports']['mysqld_port_t/tcp'] == [[3306, 3306]] and 'http_port_t/tcp' in fake()['ports']
      and [3306, 3306] not in fake()['ports']['http_port_t/tcp'], 'the port was taken from its service')
check(not any(' -m' in x.split(' nice=')[0] for x in calls() if x.startswith('semanage')),
      'semanage port -m was run: %r' % [x for x in calls() if x.startswith('semanage')])
NGINX_CONF.write_text(NGINX_CONF.read_text().replace('listen 3306 ssl;', 'listen 8080 ssl;'))
rc, c, g = helper(['--selinux-check', '--json'])
check(c and [(p['port'], p['labelled']) for p in c['ports']] == [(8080, True)],
      'a port of http_cache_port_t is not one nginx may bind: %r' % (c or {}).get('ports'))
NGINX_CONF.write_text(NGINX_CONF.read_text().replace('listen 8080 ssl;', 'listen 8445 ssl;'))

print('the report: nothing secret in it')
machine(mode='Permissive')
s = fake()
s['extra'] = ['type=PROCTITLE msg=audit(%d.1:77): proctitle=%s' % (NOW, (TOKEN + ' --password hunter2').encode().hex()),
              'type=EXECVE msg=audit(%d.1:78): argc=3 a0="curl" a1="-H" a2="X-Zigmon-Token: %s"' % (NOW, TOKEN),
              avc(79, NOW, 'httpd_t', 'var_run_t', 'file', 'read', 'php-fpm', 'api-token') +
              ' password=hunter2 msg=%s' % SMS_PASSWORD]
FAKE_STATE.write_text(json.dumps(s))
out = W / 'report.tar.gz'
rc, c, g = helper(['--selinux-report', str(out), '--json'])
check(rc == 0 and out.is_file() and out.stat().st_mode & 0o777 == 0o600, 'the report was not written 0600: %s'
      % g.stderr[-300:])
names, blob = [], ''
try:
    with tarfile.open(str(out)) as tf:
        for m in tf.getmembers():
            names.append(m.name.split('/', 1)[-1])
            blob += tf.extractfile(m).read().decode('utf-8', 'replace')
except (OSError, tarfile.TarError) as e:
    check(False, 'the report does not open: %s' % e)
for want in ('check.json', 'avc-raw.txt', 'audit2why.txt', 'labels.txt', 'processes.txt', 'ports.txt',
             'booleans.txt', 'modules.txt', 'system.txt', 'zigmon.json', 'README.txt'):
    check(want in names, 'the report has no %s: %r' % (want, names))
for secret in (TOKEN, SMS_PASSWORD, 'hunter2', TOKEN.encode().hex()[:24]):
    check(secret not in blob, 'the report holds a secret: %s...' % secret[:6])
check('type=PROCTITLE' not in blob and 'type=EXECVE' not in blob, 'command lines in the report')
check('denied  { read }' in blob and 'php-fpm' in blob, 'the refusals are not in the report')
check(not any(x.startswith(('setenforce', 'semodule -i', 'setsebool', 'semanage port -a', 'restorecon'))
              for x in calls()), 'making the report changed something: %r' % calls())


# ---- the daemon, the API ---------------------------------------------------------------------
print('the daemon and the API')
os.environ.update(ZIGMON_ROOT_RUN='%s -I %s' % (sys.executable, HELPER))
sys.argv = ['zigmon']
sys.path.insert(0, str(HERE))
import zigmon                                               # noqa: E402

zigmon.load_config()
zigmon.CONFIG.update({'db_file': str(STATE / 'z.db'), 'api_port': API_PORT, 'api_host': '127.0.0.1',
                      'token_file': str(W / 'token'), 'pin': '', 'plugs': [], 'sensors': [], 'mqtt_host': '',
                      'log_file': '', 'state_dir': str(STATE)})
d = zigmon.Daemon()
d.notify = lambda *a, **k: None
api = zigmon.ApiServer(d)
api.start()
time.sleep(0.3)


def call(path, body=None, session=None):
    headers = {'X-Zigmon-Token': d.token, 'Content-Type': 'application/json', 'X-Zigmon-Client': '192.168.40.10'}
    if session:
        headers['X-Zigmon-Session'] = session
    if body is not None and session:
        body = dict(body, session=session)
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (API_PORT, path), headers=headers,
                                 data=None if body is None else json.dumps(body).encode(),
                                 method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
S_OP = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''
check(S and S_OP, 'could not sign in')
check('/api/selinux' in zigmon.ApiHandler.ALWAYS_LOCKED, '/api/selinux is not ALWAYS_LOCKED')
for who, sess in (('anybody', None), ('an operator', S_OP)):
    code, _ = call('/api/selinux', session=sess)
    check(code == 403, 'GET /api/selinux answered %s: %s' % (who, code))
    code, _ = call('/api/selinux', {'action': 'check'}, session=sess)
    check(code == 403, 'POST /api/selinux went through for %s: %s' % (who, code))
check(not d._mj('selinux:want'), 'a refused POST asked for something')
code, v = call('/api/selinux', session=S)
check(code == 200 and v.get('helper') is True and v.get('state') == {} and not v.get('pending'),
      'GET /api/selinux for an administrator: %s %r' % (code, v))
code, v = call('/api/selinux', {'action': 'shutdown'}, session=S)
check(code == 400, 'an action of another name: %s' % code)


def tick_wait(most=120):
    zigmon.selinux_tick(d)
    end = time.time() + most
    time.sleep(0.2)
    while zigmon.SE_WORK['busy'] and time.time() < end:
        time.sleep(0.1)


machine(mode='Permissive')
# the first look two minutes after the start, not at once
zigmon.SE_WORK.update(busy=False, seen=None, tried='')
zigmon.selinux_tick(d)
time.sleep(0.5)
check(not zigmon.SE_WORK['busy'] and not d._mj('selinux:now') and not calls(),
      'the first look was not left for two minutes after the start')
check(abs(zigmon.SE_WORK['seen'] - (time.time() - zigmon.SE_EVERY_S + zigmon.SE_FIRST_S)) < 5
      and zigmon.SE_FIRST_S == 120 and zigmon.SE_EVERY_S == 1800, 'the first look is not due in two minutes')
zigmon.SE_WORK['seen'] -= zigmon.SE_FIRST_S + 1
started = time.time()
zigmon.selinux_tick(d)
names = [t.name for t in __import__('threading').enumerate()]
check('zigmon-selinux' in names, 'the look is not on a thread of its own: %r' % names)
while zigmon.SE_WORK['busy'] and time.time() - started < 120:
    time.sleep(0.1)
now = d._mj('selinux:now') or {}
check(now.get('action') == 'check' and (now.get('data') or {}).get('mode') == 'Permissive',
      'the look did not come back: %r' % now)
check(all(int(x.rsplit('nice=', 1)[1]) == 19 for x in calls() if x.startswith('getenforce')) and calls(),
      'root\'s helper was not run at the lowest priority from the daemon: %r' % calls()[:3])
# half an hour later, not before
n = len(calls())
zigmon.selinux_tick(d)
time.sleep(0.4)
check(len(calls()) == n and not zigmon.SE_WORK['busy'], 'looked again before half an hour')
# a step: at once
code, v = call('/api/selinux', {'action': 'prepare'}, session=S)
check(code == 200 and v.get('pending') == 'prepare', 'POST prepare: %s %r' % (code, v))
want = d._mj('selinux:want') or {}
check(want.get('by') == 'owner' and want.get('do') == 'prepare', 'who asked is not kept: %r' % want)
# a look or a report does not put the pending step aside
code, v = call('/api/selinux', {'action': 'check'}, session=S)
check(code == 200 and (d._mj('selinux:want') or {}).get('id') == want.get('id'), 'a look put the step aside')
code, v = call('/api/selinux', {'action': 'report'}, session=S)
check(code == 400 and 'not done yet' in v.get('error', ''), 'a report put the step aside: %s %r' % (code, v))
tick_wait()
now = d._mj('selinux:now') or {}
check(now.get('done') == want.get('id') and now.get('action') == 'prepare' and not now.get('error')
      and (now.get('data') or {}).get('ready') is True, 'the step was not done at once: %r' % now)
code, v = call('/api/selinux', session=S)
check(code == 200 and not v.get('pending') and v.get('said') and v['state'].get('module') is True,
      'the page does not see the step done: %r' % v)
ev = ' | '.join(e.get('detail', '') for e in d.store.events(limit=50))
check('owner asked SELinux' in ev and 'SELinux: ' in ev, 'no events for the step: %s' % ev[:300])
# a step id tried once: its answer not written, it is not run again every five seconds
d._mj_put('selinux:want', {'id': 'feedface01', 'do': 'enforce', 'by': 'owner', 'at': time.time()})
zigmon.SE_WORK['tried'] = 'feedface01'
n = len(calls())
zigmon.selinux_tick(d)
time.sleep(0.4)
check(len(calls()) == n, 'a step id already tried was run again')
zigmon.SE_WORK['tried'] = ''
tick_wait()
now = d._mj('selinux:now') or {}
check(now.get('done') == 'feedface01' and (now.get('data') or {}).get('mode') == 'Enforcing',
      'enforce through the daemon: %r' % now)
check(not (d.notices_all() or {}).get('selinux'), 'a notice though enforcing has everything')
# enforcing and something missing: said on every page
s = fake()
s['bools']['httpd_can_network_connect'] = False
FAKE_STATE.write_text(json.dumps(s))
call('/api/selinux', {'action': 'check'}, session=S)
tick_wait()
check((d.notices_all() or {}).get('selinux'), 'no notice while enforcing refuses what the pages need')
s['bools']['httpd_can_network_connect'] = True
FAKE_STATE.write_text(json.dumps(s))
call('/api/selinux', {'action': 'check'}, session=S)
tick_wait()
check(not (d.notices_all() or {}).get('selinux'), 'the notice stayed once it was right')
# the report through the page's road
code, v = call('/api/selinux', {'action': 'report'}, session=S)
check(code == 200 and v.get('pending') == 'report', 'POST report: %s %r' % (code, v))
tick_wait()
code, v = call('/api/selinux', session=S)
check(code == 200 and (v.get('report') or {}).get('bytes', 0) > 100 and not v['report'].get('error'),
      'the report row: %r' % v.get('report'))
code, v = call('/api/selinux', {'action': 'download'}, session=S_OP)
check(code == 403, 'an operator downloaded the report: %s' % code)
code, v = call('/api/selinux', {'action': 'download'}, session=S)
raw = base64.b64decode(v.get('file') or '') if code == 200 else b''
blob = ''
try:
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        for m in tf.getmembers():
            blob += tf.extractfile(m).read().decode('utf-8', 'replace')
except (OSError, tarfile.TarError) as e:
    check(False, 'the downloaded report does not open: %s' % e)
check(code == 200 and v.get('name', '').startswith('zigmon-selinux-report-') and 'check.json' in blob + 'check.json',
      'download: %s %r' % (code, {k: v.get(k) for k in ('name', 'error')}))
for secret in (TOKEN, SMS_PASSWORD, 'hunter2', d.token):
    check(secret not in blob, 'the downloaded report holds a secret: %s...' % secret[:6])

# ---- the relay ----------------------------------------------------------------------------
php = (HERE / 'web' / 'index.php').read_text()
check("$what === 'selinux' && $_SERVER['REQUEST_METHOD'] === 'GET'" in php and "'selinux-do' => '/api/selinux'" in php,
      'the PHP relay does not let /api/selinux through')

# ---- the command line ------------------------------------------------------------------------
print('the command line')
cli_env = dict(os.environ)
cli_env.pop('ZIGMON_ROOT_RUN', None)
cfg = W / 'cli-config.json'
cfg.write_text(json.dumps({'db_file': str(W / 'cli.db'), 'api_port': API_PORT, 'state_dir': str(STATE),
                           'token_file': str(W / 'token'), 'log_file': ''}))
machine(mode='Permissive')
got = sh([sys.executable, str(HERE / 'zigmon.py'), '--config', str(cfg), '--selinux-check', '--json'], env=cli_env,
         timeout=300)
try:
    j = json.loads(got.stdout)
except ValueError:
    j = {}
check(got.returncode == 1 and j.get('mode') == 'Permissive' and j.get('booleans')
      and j['booleans'][0]['why'] == 'the pages ask the daemon on 127.0.0.1:%d' % API_PORT,
      'zigmon --selinux-check --json: %s %r' % (got.returncode, (got.stdout + got.stderr)[-400:]))
got = sh([sys.executable, str(HERE / 'zigmon.py'), '--config', str(cfg), '--selinux-check'], env=cli_env, timeout=300)
check('SELinux: Permissive' in got.stdout and 'FAIL' in got.stdout and 'not ready' in got.stdout,
      'zigmon --selinux-check for a person: %r' % got.stdout[-400:])
got = sh([sys.executable, str(HERE / 'zigmon.py'), '--config', str(cfg), '--selinux', 'enforce'], env=cli_env, timeout=300)
check(got.returncode == 2 and '--yes' in got.stdout and fake()['mode'] == 'Permissive',
      'zigmon --selinux enforce did not ask first: %r' % (got.stdout + got.stderr)[-300:])
got = sh([sys.executable, str(HERE / 'zigmon.py'), '--config', str(cfg), '--selinux', 'prepare', '--yes'],
         env=cli_env, timeout=300)
check(got.returncode == 0 and 'zigmon_server' in got.stdout and fake()['bools']['httpd_can_network_connect'],
      'zigmon --selinux prepare --yes: %r' % (got.stdout + got.stderr)[-400:])
rep = W / 'cli-report.tar.gz'
got = sh([sys.executable, str(HERE / 'zigmon.py'), '--config', str(cfg), '--selinux-report', str(rep)], env=cli_env,
         timeout=300)
check(got.returncode == 0 and rep.is_file() and TOKEN.encode() not in rep.read_bytes(),
      'zigmon --selinux-report FILE: %r' % (got.stdout + got.stderr)[-300:])

# ---- the installer -------------------------------------------------------------------------
print('the installer')
IB = W / 'instbin'
IB.mkdir()
for tool in ('getenforce', 'semodule', 'semanage', 'restorecon', 'matchpathcon', 'getsebool', 'setsebool'):
    (IB / tool).symlink_to(BIN / 'sefake')
(IB / 'rpm').write_text('#!/bin/sh\necho "rpm $*" >> %s\n[ "$2" = audit ] && exit 1\nexit 0\n' % FAKE_LOG)
(IB / 'dnf').write_text('#!/bin/sh\necho "dnf $*" >> %s\nexit 0\n' % FAKE_LOG)
(IB / 'systemctl').write_text('#!/bin/sh\necho "systemctl $*" >> %s\n[ "$1" = is-active ] && exit 3\nexit 0\n' % FAKE_LOG)
(IB / 'auditd').write_text('#!/bin/sh\nexit 0\n')
for x in ('rpm', 'dnf', 'systemctl', 'auditd'):
    (IB / x).chmod(0o755)
inst = W / 'install-functions.sh'
inst.write_text('\n'.join((HERE / 'install.sh').read_text().splitlines()[:-1]) + '\n')
SRC = W / 'src'
(SRC / 'deploy').mkdir(parents=True)
shutil.copy(HERE / 'deploy' / 'zigmon_server.cil', SRC / 'deploy' / 'zigmon_server.cil')
ILIB = W / 'ilib'


def installer(fn, dry=False):
    script = ('source %s\nSOURCE_DIR=%s\nLIB_DIR=%s\nSELINUX_ETC=%s\nSELINUX_RUN_DIR=%s\nWEB_DIR=%s\nNGINX_CONF=%s\n'
              'DRY_RUN=%s\n%s\n' % (inst, SRC, ILIB, ETC / 'selinux', RUN, WWW, NGINX_CONF, 'yes' if dry else '""', fn))
    return sh(['bash', '-c', script], env=dict(os.environ, PATH='%s:%s' % (IB, os.environ.get('PATH', ''))), timeout=120)


machine(mode='Permissive')
got = installer('configure_selinux')
out = got.stdout + got.stderr
check(got.returncode == 0, 'configure_selinux failed: %s' % out[-400:])
check((ILIB / 'zigmon_server.cil').is_file() and (ILIB / 'zigmon_server.cil.in-policy').is_file()
      and 'zigmon_server' in fake()['modules'], 'the installer did not put the module in: %s' % out[-300:])
check(any(x.startswith('dnf install -y audit') for x in calls()), 'the missing tools were not put in: %r' % calls())
check(any(x.startswith('systemctl enable --now auditd') for x in calls()), 'auditd was not started')
check(any(x.startswith('restorecon -R ' + str(RUN)) for x in calls()), 'restorecon of /run/zigmon: %r' % calls())
check(any(x.startswith('semanage port -a -t http_port_t -p tcp 8445') for x in calls()),
      'nginx\'s port was not labelled by the installer: %r' % [x for x in calls() if 'semanage' in x])
check(fake()['bools']['httpd_can_network_connect'], 'the boolean was not switched on')
check('does not label' not in out, 'matchpathcon said wrong for a policy that labels it: %s' % out[-300:])
n = sum(1 for x in calls() if x.startswith('semodule -i'))
got = installer('configure_selinux')
check(sum(1 for x in calls() if x.startswith('semodule -i')) == n, 'the module was put in again though unchanged')
check(sum(1 for x in calls() if x.startswith('semanage port -a')) == 1, 'the labelled port was asked again')
# changed: in again; semodule failing leaves the .in-policy copy old, and the next run tries again
(SRC / 'deploy' / 'zigmon_server.cil').write_text(CIL.read_text() + '\n; changed\n')
s = fake()
s['semodule_fail'] = True
FAKE_STATE.write_text(json.dumps(s))
got = installer('configure_selinux')
check('could not be put in' in got.stdout and '; changed' not in (ILIB / 'zigmon_server.cil.in-policy').read_text(),
      'a semodule that failed left the .in-policy copy new: %s' % got.stdout[-300:])
s = fake()
s['semodule_fail'] = False
FAKE_STATE.write_text(json.dumps(s))
n = sum(1 for x in calls() if x.startswith('semodule -i'))
got = installer('configure_selinux')
check(sum(1 for x in calls() if x.startswith('semodule -i')) == n + 1
      and '; changed' in (ILIB / 'zigmon_server.cil.in-policy').read_text(), 'the next run did not put it in')
# another service's port: said, never -m
NGINX_CONF.write_text(NGINX_CONF.read_text().replace('listen 8445 ssl;', 'listen 3306 ssl;'))
got = installer('selinux_nginx_ports')
check('could not be labelled' in got.stdout and not any(' -m ' in x for x in calls() if x.startswith('semanage')),
      'another service\'s port: %s %r' % (got.stdout[-200:], [x for x in calls() if x.startswith('semanage')]))
NGINX_CONF.write_text(NGINX_CONF.read_text().replace('listen 3306 ssl;', 'listen 8445 ssl;'))
# the policy not labelling /run/zigmon: said
s = fake()
s['fix'][str(RUN)] = 'var_run_t'
FAKE_STATE.write_text(json.dumps(s))
got = installer('selinux_module')
check('does not label' in got.stdout, 'matchpathcon saying var_run_t was not warned about: %s' % got.stdout[-300:])
# disabled: nothing changed but the module copied beside the program
machine(mode='Disabled')
got = installer('configure_selinux')
check('nothing changed' in got.stdout and not any(x.startswith(('semodule -i', 'setsebool', 'semanage port -a',
                                                                 'systemctl enable'))
                                                  for x in calls()), 'the installer changed a disabled machine: %r' % calls())
# --uninstall takes the module out (a dry run: nothing of this machine is touched)
machine(mode='Permissive', modules=['base', 'zigmon_server'])
got = installer('do_uninstall', dry=True)
check('[would run] semodule -r zigmon_server' in got.stdout, 'uninstall does not take the module out: %s'
      % got.stdout[-400:])
sh_text = (HERE / 'install.sh').read_text()
check(sh_text.count('\n    configure_selinux') >= 2, 'an upgrade does not run configure_selinux')
check('"$LIB_DIR/zigmon_server.cil"' in sh_text.split('write_system_stamp() {')[1].split('\n}\n')[0],
      'the module is not among the parts the stamp records')
unit = (HERE / 'deploy' / 'zigmon-root.path').read_text()
check('PathExists=/var/lib/zigmon/root/selinux.ask' in unit, 'zigmon-root.path does not watch selinux.ask')
cil = (HERE / 'deploy' / 'zigmon_server.cil').read_text()
check(all(x in cil for x in ('"/run/zigmon" dir', '"/run/zigmon/.*" any', '"/var/run/zigmon" dir',
                             '"/var/run/zigmon/.*" any', 'httpd_var_run_t', '(optional zigmon_server_systemd_runtime',
                             '(allow init_t httpd_var_run_t (file (getattr setattr)))')),
      'the module lacks a label or the optional allow')


# ---- the page --------------------------------------------------------------------------------
print('the page')


def state_of(mode, labels=None, conf=None, **kw):
    machine(mode=mode, labels=labels, **kw)
    CMDLINE.write_text('BOOT_IMAGE=(hd0,gpt2)/vmlinuz root=/dev/mapper/al-root ro quiet\n')
    SE_CONFIG.write_text('SELINUX=%s\nSELINUXTYPE=targeted\n' % (conf or mode.lower()))
    if (OWN / 'selinux-applied').exists():
        (OWN / 'selinux-applied').unlink()          # counted since the machine started
    rc, c, g = helper(['--selinux-check', '--json'])
    return c or {}


PERM = state_of('Permissive')
ENF = state_of('Enforcing', modules=['base', 'zigmon_server'], bools={'httpd_can_network_connect': True},
               ports={'http_port_t/tcp': [[80, 81], [443, 443], [8445, 8445]]}, avc=[],
               labels={str(RUN): 'httpd_var_run_t', str(RUN / 'api-token'): 'httpd_var_run_t', str(WWW): 'httpd_sys_content_t'})
DIS = state_of('Disabled')
RELABEL.write_text('')
MADE = state_of('Disabled', conf='permissive')
RELABEL.unlink()
READY = dict(PERM, ready=True, problems=[], module=True, booleans=[dict(b, on=True) for b in PERM.get('booleans') or []],
             ports=[dict(p, labelled=True) for p in PERM.get('ports') or []],
             labels=[dict(x, ok=True, label=x['want']) for x in PERM.get('labels') or []],
             denials={'tool': True, 'total': 0, 'groups': [], 'since': time.time() - 60, 'settled': 2})
SEEDS = {'perm': (PERM, ''), 'enf': (ENF, ''), 'dis': (DIS, ''), 'made': (MADE, 'prepare'), 'ready': (READY, '')}


ASKED = []


def seed(name):
    data, act = SEEDS[name]
    ASKED.append(str((d._mj('selinux:want') or {}).get('do') or ''))      # what the page asked before
    d._mj_put('selinux:now', {'data': data, 'at': time.time(), 'done': 'x', 'error': '', 'action': act or 'check',
                              'said': ['the files are labelled at the next start of the machine',
                                       'restart the machine - it comes up permissive'] if act else []})
    d._mj_put('selinux:want', {})


seed('perm')
# the daemon's own system loop ticks every five seconds: held off, so that a step asked on the
# page stays pending (root is not asked here) and the card's spinner and polling can be seen
zigmon.SE_WORK['busy'] = True
shutil.copytree(HERE / 'web', W / 'web')
api_php = (W / 'web' / 'zigmon-api.php').read_text()
api_php = api_php.replace("const ZIGMON_PORT  = 9849;", "const ZIGMON_PORT  = %d;" % API_PORT)
api_php = api_php.replace("const ZIGMON_TOKEN = '/run/zigmon/api-token';", "const ZIGMON_TOKEN = '%s';" % (W / 'token'))
(W / 'web' / 'zigmon-api.php').write_text(api_php)
php = subprocess.Popen(['php', '-S', '127.0.0.1:%d' % PHP_PORT, str(W / 'web' / 'index.php')], cwd=str(W / 'web'),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                       env=dict(os.environ, PHP_CLI_SERVER_WORKERS='16'))
PROCS.append(php)
for _ in range(50):
    try:
        socket.create_connection(('127.0.0.1', PHP_PORT), 0.2).close()
        break
    except OSError:
        time.sleep(0.1)
os.makedirs(SHOTS, exist_ok=True)
# the page asks the test, between its steps, to seed another state (a file it writes)
SEED_ASK = W / 'seed.ask'
js = r'''
const { chromium } = require('playwright');
const fs = require('fs');
const PORT = %(port)d, SH = %(shots)s, S = %(s)s, SOP = %(sop)s, ASK = %(ask)s;
let N = 0;
const url = () => 'http://127.0.0.1:' + PORT + '/?b=' + (++N) + '#control/sec-selinux';
async function seedIt(name) {
  console.error('seed ' + name);
  fs.writeFileSync(ASK, name);
  for (let i = 0; i < 100 && fs.existsSync(ASK); i++) await new Promise(r => setTimeout(r, 100));
}
async function card(p) {
  return await p.evaluate(() => {
    const c = document.getElementById('se-card'), q = s => c.querySelector(s);
    const txt = s => (q(s) || {}).innerText || '';
    return {shown: !!c && c.offsetParent !== null, mode: txt('.se-mode'), verdict: txt('#se-verdict'),
            list: Array.from(c.querySelectorAll('.se-row')).map(r => ({t: r.innerText, dot: r.querySelector('.se-dot').className})),
            avc: txt('#se-avc summary'), buttons: Array.from(c.querySelectorAll('.se-btns button')).map(b => ({t: b.innerText.trim(), off: b.disabled, id: b.id})),
            wait: txt('#se-wait'), said: txt('#se-said'), next: Array.from(c.querySelectorAll('.se-next')).map(x => x.innerText),
            nav: !!document.querySelector('#control-nav button[data-sec="sec-selinux"]'), text: c.innerText,
            top: Array.from(c.querySelectorAll('.se-top button')).map(b => b.innerText.trim())};
  });
}
let P = null;
(async () => {
  const b = await chromium.launch();
  const out = {};
  const ctx = await b.newContext({viewport: {width: 1440, height: 1000}, deviceScaleFactor: 2});
  await ctx.addCookies([{name: 'zigmon_session', value: S, url: 'http://127.0.0.1:' + PORT + '/'}]);
  const p = await ctx.newPage();
  P = p;
  p.errors = []; p.asks = 0;
  p.on('pageerror', e => p.errors.push(String(e)));
  p.on('request', r => { if (/[?&]api=selinux(&|$)/.test(r.url()) && r.method() === 'GET') p.asks++; });
  for (const name of ['perm', 'enf', 'dis', 'made', 'ready']) {
    await seedIt(name);
    await p.goto(url());
    await p.waitForSelector('#se-node', {timeout: 15000});
    await p.waitForTimeout(500);
    if (name === 'perm') await p.click('#se-avc summary');
    out[name] = await card(p);
    await (await p.$('#se-card')).screenshot({path: SH + '/selinux-' + name + '.png'});
  }
  /* the confirmation, and the step asked: the spinner, and the card asking again */
  await seedIt('perm');
  await p.goto(url());
  await p.waitForSelector('#se-prepare');
  await p.click('#se-prepare');
  await p.waitForSelector('#zmodal:not([hidden])');
  out.confirm = await p.evaluate(() => document.getElementById('zmodal').innerText);
  await p.screenshot({path: SH + '/selinux-confirm.png'});
  await p.click('#zmodal .btn.danger');
  await p.waitForSelector('#se-wait', {timeout: 10000});
  const before = p.asks;
  await p.waitForTimeout(5000);
  out.pending = await card(p);
  out.polls = p.asks - before;
  await (await p.$('#se-card')).screenshot({path: SH + '/selinux-pending.png'});
  /* enforcing's button asks too */
  await seedIt('enf');
  await p.goto(url());
  await p.waitForSelector('#se-permissive');
  await p.click('#se-permissive');
  await p.waitForSelector('#zmodal:not([hidden])');
  out.confirmBack = await p.evaluate(() => document.getElementById('zmodal').innerText);
  await p.keyboard.press('Escape');
  /* a phone */
  await seedIt('perm');
  const ph = await b.newContext({viewport: {width: 390, height: 844}, deviceScaleFactor: 2});
  await ph.addCookies([{name: 'zigmon_session', value: S, url: 'http://127.0.0.1:' + PORT + '/'}]);
  const q = await ph.newPage();
  await q.goto(url());
  await q.waitForSelector('#se-node', {timeout: 15000});
  await q.click('#se-avc summary');
  await q.waitForTimeout(400);
  out.phone = await q.evaluate(() => ({doc: document.documentElement.scrollWidth, win: window.innerWidth,
    card: document.getElementById('se-card').scrollWidth, cw: document.getElementById('se-card').clientWidth}));
  await (await q.$('#se-card')).screenshot({path: SH + '/selinux-phone.png'});
  /* an operator is kept out */
  const op = await b.newContext({viewport: {width: 1440, height: 900}});
  await op.addCookies([{name: 'zigmon_session', value: SOP, url: 'http://127.0.0.1:' + PORT + '/'}]);
  const o = await op.newPage();
  await o.goto(url());
  await o.waitForTimeout(2500);
  out.operator = await o.evaluate(() => ({text: document.getElementById('se-host').innerText,
                                          node: !!document.getElementById('se-node')}));
  out.errors = p.errors;
  console.log(JSON.stringify(out));
  await b.close();
})().catch(async e => {
  let seen = '';
  try { seen = await P.evaluate(() => location.href + ' ' + document.body.innerText.slice(0, 600)); } catch (x) { seen = String(x); }
  console.log(JSON.stringify({error: String(e) + ' | page errors: ' + JSON.stringify(P && P.errors) + ' | ' + seen}));
  process.exit(0);
});
'''
(W / 'page.js').write_text(js % {'port': PHP_PORT, 'shots': json.dumps(SHOTS), 's': json.dumps(S),
                                 'sop': json.dumps(S_OP), 'ask': json.dumps(str(SEED_ASK))})
root = sh(['npm', 'root', '-g']).stdout.strip()
node = subprocess.Popen(['node', str(W / 'page.js')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        env=dict(os.environ, NODE_PATH=root), stdin=subprocess.DEVNULL)
PROCS.append(node)
end = time.time() + 400
while node.poll() is None and time.time() < end:
    if SEED_ASK.exists():
        seed(SEED_ASK.read_text().strip())
        SEED_ASK.unlink()
    time.sleep(0.05)
if node.poll() is None:
    node.kill()
    o_out, o_err = node.communicate()
    check(False, 'the page did not finish in 400 s: %s' % (o_out + o_err)[-600:])
    finish()
o_out, o_err = node.communicate()
try:
    r = json.loads(o_out.strip().splitlines()[-1])
except (ValueError, IndexError):
    r = {'error': (o_out + o_err)[-400:]}
if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
    print('  SKIPPED the page (no browser here): %s' % r['error'][:200])
    finish()
check(not r.get('error'), 'the page: %s' % r.get('error'))
pm = r.get('perm') or {}
check(pm.get('nav') and pm.get('shown'), 'no SELinux section in Settings - Security')
check(pm.get('mode') == 'PERMISSIVE' and 'Not ready for enforcing yet' in pm.get('verdict', ''),
      'permissive: the pill and the verdict: %r' % {k: pm.get(k) for k in ('mode', 'verdict')})
rows = ' | '.join(x['t'] for x in pm.get('list') or [])
for want in ('zigmon_server) is not installed', 'the API token the pages read', 'var_run_t', 'httpd_var_run_t',
             'httpd_can_network_connect = off', '8445/tcp', 'SELinux refused 14 thing(s) since the machine started'):
    check(want in rows, 'the checklist lacks "%s": %s' % (want, rows[:400]))
check(any('bad' in x['dot'] for x in pm.get('list') or []) and any('ok' in x['dot'] for x in pm.get('list') or []),
      'the checklist has no red and green dots')
check(pm.get('avc') == 'What was refused (2)' and 'httpd_t → var_run_t file { read }' in pm.get('text', ''),
      'what was refused: %r' % pm.get('avc'))
btn = {x['t']: x for x in pm.get('buttons') or []}
check(set(btn) == {'Put in what zigmon needs', 'Switch to enforcing'} and btn['Switch to enforcing']['off']
      and not btn['Put in what zigmon needs']['off'], 'permissive\'s buttons: %r' % pm.get('buttons'))
check(pm.get('top') == ['Look again', 'Download the report'], 'the buttons on top: %r' % pm.get('top'))
en = r.get('enf') or {}
check(en.get('mode') == 'ENFORCING' and en.get('verdict', '').startswith('Enforcing - and everything zigmon needs is there')
      and [x['t'] for x in en.get('buttons') or []] == ['Back to permissive'], 'enforcing: %r' % en)
ds = r.get('dis') or {}
check(ds.get('mode') == 'DISABLED' and [x['t'] for x in ds.get('buttons') or []] == ['Make it ready (permissive)']
      and 'zigmon runs as always' in ds.get('text', '') and not ds.get('list'), 'disabled: %r' % ds)
md = r.get('made') or {}
check(md.get('mode') == 'DISABLED' and not md.get('buttons') and 'Made ready - waiting for a restart' in md.get('text', '')
      and 'After the next restart of the machine: permissive' in ' '.join(md.get('next') or [])
      and 'restart the machine' in md.get('said', ''), 'made ready: %r' % md)
rd = r.get('ready') or {}
check(rd.get('verdict', '').startswith('Ready for enforcing') and
      any(x['t'] == 'Switch to enforcing' and not x['off'] for x in rd.get('buttons') or []) and
      'refused before, allowed now' in rd.get('text', ''), 'ready: %r' % rd)
check('Put in what zigmon needs on' in r.get('confirm', '') and 'Still permissive' in r.get('confirm', ''),
      'no confirmation before putting in: %r' % r.get('confirm'))
check('back to permissive' in r.get('confirmBack', ''), 'no confirmation before going back: %r' % r.get('confirmBack'))
pe = r.get('pending') or {}
check(pe.get('wait') and all(x['off'] for x in pe.get('buttons') or []), 'no spinner while the step is pending: %r' % pe)
check((r.get('polls') or 0) >= 2, 'the card does not ask again while a step is pending: %r' % r.get('polls'))
check('prepare' in ASKED, 'the confirmed step was not asked: %r' % ASKED)
ph = r.get('phone') or {}
check(ph.get('doc', 9999) <= ph.get('win', 0) and ph.get('card', 9999) <= ph.get('cw', 0) + 1,
      'the card scrolls sideways at 390 px: %r' % ph)
op = r.get('operator') or {}
check(not op.get('node') and 'administrator' in op.get('text', ''), 'an operator sees the card: %r' % op)
check(not r.get('errors'), 'errors on the page: %r' % r.get('errors'))
print('  screenshots in %s' % SHOTS)
finish()
