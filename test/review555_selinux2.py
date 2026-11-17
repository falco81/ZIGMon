#!/usr/bin/env python3
"""SELinux, the new design (after fake-igd's kit): what SELinux refuses on the whole machine,
sorted by what puts it right - and the button that puts right what may safely be put right.
getenforce, semodule, semanage, getsebool, setsebool, restorecon, matchpathcon, ausearch,
audit2why and the rest stood in for by one fake that keeps the machine in a JSON file (the
ZIGMON_SELINUX_* hooks of 5.48), fed with raw ausearch output whose fields are hex-encoded as
the kernel writes them.

  * root's analysis: every AVC, USER_AVC and SELINUX_ERR read with its event (SYSCALL, PATH,
    CWD, PROCTITLE - proctitle name path comm exe cwd decoded from hex, nothing else),
    grouped, put to audit2why and sorted: allowed now, boolean, label, port, a rule of
    zigmon's, not for a button (a security-sensitive target, executing, a class of the
    kernel's, a write to a generic type, another service's port, a dangerous boolean, a
    constraint, an error of the policy) and not zigmon's; the ids the same at every look;
  * fix by ids only: the boolean set, restorecon on zigmon's path, semanage port -a, the local
    module zigmon_local written with an optional block per rule, checked, loaded (semodule -i)
    and kept as .in-policy; unknown ids refused, a request carrying a rule refused, a finding
    not for a button refused - nothing done then; a dangerous boolean never set; a port
    another type has refused, also when it became so after the look; works under enforcing;
    put right noted with its time - "put right just now", not counted; rule_drop down to the
    last: semodule -r zigmon_local; enforcing locked while anything is left;
  * the report: the os/ files of the whole machine, no secret of zigmon's in any file;
  * the daemon and the API: look, fix {ids}, rule_drop {id}; an administrator's only (an
    operator 403); a request carrying a rule refused; one end-to-end through the API; the
    events; the notice "SELinux refuses zigmon something - N can be put right on the card";
  * the command line: --selinux-look [--json], --selinux-fix ID... | --all [--yes],
    --selinux-rules [--take-away ID] [--yes]; the help; the console's menu;
  * install.sh: --uninstall takes zigmon_local away too; zigmon_server.cil's nnp_transition
    blocks; the CIL of both modules checked for its forms;
  * the card (php -S + Chromium): screenshots like the kit's 01..09.

    python3 test/review555_selinux2.py

Ports 20400 (the daemon) and 20401 (php -S) only.
"""
import json
import os
import re
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
W = Path(tempfile.mkdtemp(prefix='zigmon-review555-'))
API_PORT, PHP_PORT = 20400, 20401
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
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
    if not os.environ.get('REVIEW555_KEEP'):
        shutil.rmtree(W, ignore_errors=True)
    print('review555_selinux2: %s' % ('FAILED (%d)' % len(bad) if bad else 'ok'))
    os._exit(1 if bad else 0)


# ---- the machine ----------------------------------------------------------------------
STATE, OWN, ETC = W / 'state', W / 'own', W / 'etc'
RUN, WWW, LIB = W / 'run' / 'zigmon', W / 'www' / 'zigmon', W / 'lib'
for d in (STATE / 'root', ETC / 'zigmon', ETC / 'nginx' / 'conf.d', ETC / 'selinux', RUN, WWW / 'assets', LIB):
    d.mkdir(parents=True, exist_ok=True)
TOKEN = 'tok-5ecret-abcdef0123456789'
(RUN / 'api-token').write_text(TOKEN + '\n')
SMS_PASSWORD = 'Sms-Pa55word-xyz'
CONF = {'db_file': str(STATE / 'z.db'), 'sms_password': SMS_PASSWORD, 'api_port': 9849, 'state_dir': str(STATE),
        'token_file': str(RUN / 'api-token'), 'sensor_listen': True, 'sensor_listen_port': 8446}
(ETC / 'zigmon' / 'config.json').write_text(json.dumps(CONF))
NGINX_CONF = ETC / 'nginx' / 'conf.d' / 'zigmon.conf'
NGINX_CONF.write_text('server {\n    listen 80;\n}\nserver {\n    listen 443 ssl;\n    listen 8445 ssl;\n}\n')
SE_CONFIG = ETC / 'selinux' / 'config'
SE_CONFIG.write_text('SELINUX=permissive\nSELINUXTYPE=targeted\n')
RELABEL, CMDLINE = W / 'autorelabel', W / 'cmdline'
CMDLINE.write_text('BOOT_IMAGE=(hd0,gpt2)/vmlinuz root=/dev/mapper/al-root ro quiet\n')
CIL = LIB / 'zigmon_server.cil'
shutil.copy(HERE / 'deploy' / 'zigmon_server.cil', CIL)
CORE_JS = WWW / 'assets' / 'core.js'
CORE_JS.write_text('// the pages\n')
(WWW / 'x.sh').write_text('#!/bin/sh\n')
LABELS = W / 'labels.json'
FAKE_STATE, FAKE_LOG = W / 'se.json', W / 'se.log'
BIN = W / 'sebin'
BIN.mkdir()
NOW = time.time()
LOCAL_DIR = OWN / 'selinux-local'


def hx(text):
    return text.encode().hex().upper()


SERIAL = [4000]


def event(t, avcs, comm='', exe='', paths=(), cwd='', title='', success='no'):
    """The records of one event as ausearch writes them (raw)."""
    SERIAL[0] += 1
    head = 'msg=audit(%.3f:%d):' % (t, SERIAL[0])
    out = []
    for a in avcs:
        out.append(a.replace('@MSG@', head))
    if exe:
        out.append('type=SYSCALL %s arch=c000003e syscall=257 success=%s exit=-13 a0=ffffff9c a1=7f a2=80000 a3=0 '
                   'items=%d ppid=1 pid=%d auid=4294967295 uid=0 gid=0 euid=0 suid=0 fsuid=0 egid=0 sgid=0 '
                   'fsgid=0 tty=(none) ses=4294967295 comm=%s exe=%s subj=system_u:system_r:x_t:s0 key=(null)'
                   % (head, success, len(paths), 2000 + SERIAL[0], comm, exe))
    if cwd:
        out.append('type=CWD %s cwd=%s' % (head, cwd))
    for i, (name, obj) in enumerate(paths):
        out.append('type=PATH %s item=%d name=%s inode=1234 dev=fd:00 mode=0100644 ouid=0 ogid=0 rdev=00:00 '
                   'obj=system_u:object_r:%s:s0 nametype=NORMAL cap_fp=0 cap_fi=0 cap_fe=0 cap_fver=0'
                   % (head, i, name, obj))
    if title:
        out.append('type=PROCTITLE %s proctitle=%s' % (head, title.replace(' ', '\0').encode().hex().upper()))
    return out, SERIAL[0]


def avc(perms, src, tgt, cls, comm, more=''):
    return ('type=AVC @MSG@ avc:  denied  { %s } for  pid=4242 comm=%s %s scontext=system_u:system_r:%s:s0 '
            'tcontext=system_u:object_r:%s:s0 tclass=%s permissive=1' % (perms, comm, more, src, tgt, cls))


ZTITLE = '/usr/bin/python3 -I %s/zigmon.py' % LIB          # the daemon, by its command line
T0 = NOW - 7200
FIX = {}                                                 # what each refusal is, by serial
RAW = []


def put(kind, recs_serial, why=''):
    recs, n = recs_serial
    RAW.append(recs)
    FIX[kind] = n
    if why:
        WHY[str(n)] = why


WHY = {}
# a boolean: the pages asking the daemon - audit2why names a dangerous one and the right one
put('boolean', event(T0, [avc('name_connect', 'httpd_t', 'unreserved_port_t', 'tcp_socket', '"php-fpm"', 'dest=9849')],
                     '"php-fpm"', '"/usr/sbin/php-fpm"'), 'bool:nis_enabled,httpd_can_network_connect')
# a label: the path hex-encoded as the kernel writes it
put('label', event(T0 + 60, [avc('read', 'httpd_t', 'default_t', 'file', '"nginx"', 'name="core.js"')],
                   '"nginx"', '"/usr/sbin/nginx"', [(hx(str(CORE_JS)), 'default_t')]))
# a port: nginx on 8445, which has no type of its own
put('port', event(T0 + 120, [avc('name_bind', 'httpd_t', 'unreserved_port_t', 'tcp_socket', '"nginx"', 'src=8445')],
                  '"nginx"', '"/usr/sbin/nginx"'))
# a rule of zigmon's: the daemon running chronyc from its NoNewPrivileges unit (comm hex: a space)
put('rule', event(T0 + 180, [avc('nnp_transition', 'unconfined_service_t', 'chronyc_t', 'process2', hx('zigmon tick'))],
                  hx('zigmon tick'), '"/usr/bin/python3.9"', title=ZTITLE))
put('rule2', event(T0 + 190, [avc('write', 'chronyc_t', 'unconfined_service_t', 'fifo_file', '"chronyc"',
                                  'path="pipe:[123]"')], '"chronyc"', '"/usr/bin/chronyc"'))
# a rule from a relative path and the folder it was asked in (both hex)
put('rule3', event(T0 + 200, [avc('getattr', 'logrotate_t', 'httpd_log_t', 'file', '"logrotate"', 'name="zigmon.log"')],
                   '"logrotate"', '"/usr/sbin/logrotate"', [(hx('zigmon.log'), 'httpd_log_t')], cwd=hx('/var/log/zigmon')))
# not for a button: every list
put('nb_sensitive', event(T0 + 300, [avc('read', 'unconfined_service_t', 'shadow_t', 'file', '"python3"')],
                          '"python3"', '"/usr/bin/python3.9"', [('"/etc/shadow"', 'shadow_t')], title=ZTITLE))
put('nb_exec', event(T0 + 310, [avc('execute', 'httpd_t', 'shell_exec_t', 'file', '"python3"')],
                     '"python3"', '"/usr/bin/python3.9"', [('"%s"' % (WWW / 'x.sh'), 'shell_exec_t')]))
put('nb_class', event(T0 + 320, [avc('dac_override', 'unconfined_service_t', 'unconfined_service_t', 'capability',
                                     '"python3"')], '"python3"', '"/usr/bin/python3.9"', title=ZTITLE))
put('nb_generic', event(T0 + 330, [avc('write', 'httpd_t', 'var_t', 'file', '"php-fpm"')],
                        '"php-fpm"', '"/usr/sbin/php-fpm"', [('"%s"' % (STATE / 'scratch.tmp'), 'var_t')]))
put('nb_port', event(T0 + 340, [avc('name_bind', 'httpd_t', 'unreserved_port_t', 'tcp_socket', '"nginx"', 'src=8446')],
                     '"nginx"', '"/usr/sbin/nginx"'))
put('nb_bool', event(T0 + 350, [avc('name_connect', 'httpd_t', 'unreserved_port_t', 'tcp_socket', '"php-fpm"',
                                    'dest=1883')], '"php-fpm"', '"/usr/sbin/php-fpm"'), 'bool:nis_enabled,httpd_execmem')
put('nb_constraint', event(T0 + 360, [avc('write', 'unconfined_service_t', 'httpd_var_run_t', 'file', '"python3"')],
                           '"python3"', '"/usr/bin/python3.9"', [('"%s"' % (RUN / 'api-token'), 'httpd_var_run_t')],
                           title=ZTITLE), 'constraint')
put('nb_error', event(T0 + 370, ['type=SELINUX_ERR @MSG@ op=security_compute_sid invalid_context='
                                 '"system_u:system_r:foo_t:s0" scontext=system_u:system_r:unconfined_service_t:s0 '
                                 'tcontext=system_u:object_r:bin_t:s0 tclass=process'],
                      '"python3"', '"/usr/bin/python3.9"', title=ZTITLE))
put('nb_service', event(T0 + 380, ["type=USER_AVC @MSG@ pid=1 uid=0 auid=4294967295 ses=4294967295 "
                                   "subj=system_u:system_r:init_t:s0 msg='avc:  denied  { start } for auid=n/a uid=0 "
                                   "gid=0 path=\"/etc/systemd/system/zigmon.service\" cmdline=\"\" "
                                   "scontext=system_u:system_r:unconfined_service_t:s0 "
                                   "tcontext=system_u:object_r:systemd_unit_file_t:s0 tclass=service permissive=1 "
                                   "exe=\"/usr/lib/systemd/systemd\" sauid=0 hostname=? addr=? terminal=?'"]))
# not zigmon's
put('other_smb', event(T0 + 400, [avc('write', 'smbd_t', 'home_root_t', 'dir', '"smbd"', 'name="share"')],
                       '"smbd"', '"/usr/sbin/smbd"'))
put('other_php', event(T0 + 410, [avc('name_connect', 'httpd_t', 'unreserved_port_t', 'tcp_socket', '"php-fpm"',
                                      'dest=9862')], '"php-fpm"', '"/usr/sbin/php-fpm"'))
# allowed now
put('allowed', event(T0 + 420, [avc('read', 'httpd_t', 'httpd_var_run_t', 'file', '"php-fpm"')],
                     '"php-fpm"', '"/usr/sbin/php-fpm"', [('"%s"' % (RUN / 'api-token'), 'httpd_var_run_t')]),
    'allowed')
# the same refusal again, later: one finding, counted twice
RAW.append(event(T0 + 500, [avc('nnp_transition', 'unconfined_service_t', 'chronyc_t', 'process2',
                                hx('zigmon tick'))], hx('zigmon tick'), '"/usr/bin/python3.9"', title=ZTITLE)[0])
KINDS = {'boolean': 'boolean', 'label': 'label', 'port': 'port', 'rule': 'rule', 'rule2': 'rule', 'rule3': 'rule',
         'nb_sensitive': 'notbutton', 'nb_exec': 'notbutton', 'nb_class': 'notbutton', 'nb_generic': 'notbutton',
         'nb_port': 'notbutton', 'nb_bool': 'notbutton', 'nb_constraint': 'notbutton', 'nb_error': 'notbutton',
         'nb_service': 'notbutton', 'other_smb': 'other', 'other_php': 'other', 'allowed': 'allowed'}
WHY_WORDS = {'nb_sensitive': 'security-sensitive', 'nb_exec': 'execute', 'nb_class': 'class of the kernel',
             'nb_generic': 'many programs share', 'nb_port': 'another service', 'nb_bool': 'allows far more',
             'nb_constraint': 'constraint', 'nb_error': 'error of the policy', 'nb_service': 'class of the kernel',
             'other_smb': 'not zigmon', 'other_php': 'not zigmon'}


def machine(mode='Permissive', raw=None, keep=False, **kw):
    if not keep:                       # root's own memory of what was put right, and its rules
        shutil.rmtree(LOCAL_DIR, ignore_errors=True)
        if (OWN / 'selinux-fixed').exists():
            (OWN / 'selinux-fixed').unlink()
    s = {'mode': mode, 'modules': ['base', 'apache', 'zigmon_server'], 'texts': {},
         'bools': {'httpd_can_network_connect': False, 'nis_enabled': False, 'httpd_execmem': False},
         'ports': {'http_port_t/tcp': [[80, 81], [443, 443]], 'http_cache_port_t/tcp': [[8080, 8080]],
                   'jboss_management_port_t/tcp': [[8446, 8446]], 'ssh_port_t/tcp': [[22, 22]],
                   'unreserved_port_t/tcp': [[1024, 32767]], 'reserved_port_t/tcp': [[1, 511]]},
         'raw': raw if raw is not None else ['\n'.join(x) for x in RAW], 'why': dict(WHY), 'semodule_fail': False,
         'fix': {str(RUN): 'httpd_var_run_t', str(RUN / 'api-token'): 'httpd_var_run_t',
                 str(WWW): 'httpd_sys_content_t', str(CORE_JS): 'httpd_sys_content_t',
                 '/var/log/zigmon/zigmon.log': 'httpd_log_t'}}
    s.update(kw)
    FAKE_STATE.write_text(json.dumps(s))
    LABELS.write_text(json.dumps({str(RUN): 'httpd_var_run_t', str(RUN / 'api-token'): 'httpd_var_run_t',
                                  str(WWW): 'httpd_sys_content_t', str(CORE_JS): 'default_t'}))
    if FAKE_LOG.exists():
        FAKE_LOG.unlink()


def fake():
    return json.loads(FAKE_STATE.read_text())


def fake_set(**kw):
    s = fake()
    s.update(kw)
    FAKE_STATE.write_text(json.dumps(s))


def calls():
    return [x.rsplit(' nice=', 1)[0] for x in (FAKE_LOG.read_text().splitlines() if FAKE_LOG.exists() else [])]


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
    s['mode'] = 'Enforcing' if a == ['1'] else 'Permissive'; save()
elif name == 'semodule':
    if a == ['-l']:
        print('\n'.join(s['modules']))
    elif a == ['-lfull']:
        print('\n'.join('400 %%-20s cil' %% m for m in s['modules']))
    elif a[:1] == ['-i']:
        if s['semodule_fail']:
            print('Failed to resolve allow statement', file=sys.stderr); sys.exit(1)
        mod = os.path.basename(a[1]).rsplit('.', 1)[0]
        s['texts'][mod] = open(a[1]).read()
        if mod not in s['modules']:
            s['modules'].append(mod)
        save()
    elif a[:1] == ['-r']:
        if a[1] not in s['modules']:
            print('No such module', file=sys.stderr); sys.exit(1)
        s['modules'] = [m for m in s['modules'] if m != a[1]]; s['texts'].pop(a[1], None); save()
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
            if k.endswith('/' + p) and not k.startswith(('unreserved', 'reserved')) and any(x <= n <= y for x, y in spans):
                print('ValueError: Port %%s/%%d already defined' %% (p, n), file=sys.stderr); sys.exit(1)
        s['ports'].setdefault(t + '/' + p, []).append([n, n]); save()
    elif a == ['export']:
        print('boolean -D\nport -D\nboolean -m -1 httpd_can_network_connect')
    elif a[1:] == ['-l', '-C']:
        print('SELinux %%s local customisations' %% a[0])
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
    for ev in s['raw']:
        print('----\ntime->Tue Nov 17 08:00:00 2026')
        print(ev)
elif name == 'audit2why':
    for line in sys.stdin.read().splitlines():
        print(line)
        m = re.search(r'msg=audit\(([0-9.]+):(\d+)\)', line)
        w = s['why'].get(m.group(2), '') if m else ''
        if w == 'allowed':
            print('\n\tWas caused by:\n\t\tUnknown - would be allowed by active policy\n')
        elif w.startswith('bool:'):
            print('\n\tWas caused by:\n\tOne of the following booleans was set incorrectly.')
            for b in w[5:].split(','):
                print('\tDescription:\n\tAllow %%s\n\n\tAllow access by executing:\n\t# setsebool -P %%s 1' %% (b, b))
            print()
        elif w == 'constraint':
            print('\n\tWas caused by:\n\t\tPolicy constraint violation.\n')
        else:
            print('\n\tWas caused by:\n\t\tMissing type enforcement (TE) allow rule.\n')
elif name == 'audit2allow':
    sys.stdin.read(); print('module zigmon_local 1.0;')
elif name == 'sestatus':
    print('SELinux status: %%s' %% s['mode'].lower())
''' % {'py': sys.executable, 'state': str(FAKE_STATE), 'log': str(FAKE_LOG), 'labels': str(LABELS)})
(BIN / 'sefake').chmod(0o755)
for tool in ('getenforce', 'setenforce', 'semodule', 'getsebool', 'setsebool', 'semanage', 'restorecon',
             'matchpathcon', 'ausearch', 'audit2why', 'audit2allow', 'sestatus'):
    (BIN / tool).symlink_to(BIN / 'sefake')

ENV = dict(ZIGMON_STATE=str(STATE), ZIGMON_ROOT_OWN=str(OWN), ZIGMON_CONFIG=str(ETC / 'zigmon' / 'config.json'),
           ZIGMON_NGINX_CONF=str(NGINX_CONF), ZIGMON_NO_SERVICES='1', ZIGMON_USER='root',
           ZIGMON_SELINUX_CONFIG=str(SE_CONFIG), ZIGMON_SELINUX_RELABEL=str(RELABEL),
           ZIGMON_SELINUX_CMDLINE=str(CMDLINE), ZIGMON_SELINUX_CIL=str(CIL), ZIGMON_SELINUX_RUN=str(RUN),
           ZIGMON_SELINUX_WEB=str(WWW), ZIGMON_SELINUX_LABELS=str(LABELS), ZIGMON_SELINUX_BIN=str(BIN),
           ZIGMON_SELINUX_AUDITD='active', ZIGMON_SELINUX_LIB=str(LIB))
os.environ.update(ENV)
WANT = {'booleans': [{'name': 'httpd_can_network_connect', 'why': 'the pages ask the daemon on 127.0.0.1:9849'}],
        'ports': []}


def helper(args, want=None, **env):
    e = dict(os.environ, **env)
    got = sh([sys.executable, '-I', str(HELPER)] + args, input=json.dumps(WANT if want is None else want), env=e,
             timeout=180)
    try:
        return got.returncode, json.loads(got.stdout or 'null'), got
    except ValueError:
        return got.returncode, None, got


def ask_root(req):
    """A request as the daemon lays it down (selinux.ask), answered in selinux.json."""
    (STATE / 'root' / 'selinux.ask').write_text(json.dumps(req))
    sys.path.insert(0, str(HERE / 'deploy'))
    code = ('import sys; sys.path.insert(0, %r); import zigmon_root as z; z.selinux_part()' % str(HERE / 'deploy'))
    got = sh([sys.executable, '-c', code], env=dict(os.environ), timeout=180)
    try:
        return json.loads((STATE / 'root' / 'selinux.json').read_text()), got
    except (OSError, ValueError):
        return {}, got


def by_kind(c):
    out = {}
    for f in (c or {}).get('findings') or []:
        out.setdefault(f['kind'], []).append(f)
    return out


def serial_of(f, look):
    """Which fixture a finding is, by its words."""
    return f


def finding(c, **want):
    for f in (c or {}).get('findings') or []:
        if all(str(f.get(k)) == str(v) for k, v in want.items()):
            return f
    return None


# ---- root: the analysis -----------------------------------------------------------------
print('root: what SELinux refuses, sorted')
machine()
rc, c, g = helper(['--selinux-check', '--json'])
check(c and c.get('mode') == 'Permissive' and isinstance(c.get('findings'), list),
      'no findings in the look: %s %s' % (rc, g.stderr[-600:]))
c = c or {}
F = {
    'boolean': finding(c, source='httpd_t', port=9849),
    'label': finding(c, source='httpd_t', target='default_t'),
    'port': finding(c, source='httpd_t', port=8445),
    'rule': finding(c, source='unconfined_service_t', target='chronyc_t'),
    'rule2': finding(c, source='chronyc_t', target='unconfined_service_t'),
    'rule3': finding(c, source='logrotate_t'),
    'nb_sensitive': finding(c, target='shadow_t'),
    'nb_exec': finding(c, target='shell_exec_t'),
    'nb_class': finding(c, **{'class': 'capability'}),
    'nb_generic': finding(c, target='var_t', perms='write'),
    'nb_port': finding(c, port=8446),
    'nb_bool': finding(c, port=1883),
    'nb_constraint': finding(c, target='httpd_var_run_t', perms='write'),
    'nb_error': finding(c, perms='security_compute_sid'),
    'nb_service': finding(c, **{'class': 'service'}),
    'other_smb': finding(c, source='smbd_t'),
    'other_php': finding(c, port=9862),
}
for k, f in F.items():
    if check(f is not None, 'fixture %s not found among the findings: %r' % (k, [(x['kind'], x['source'], x['target'])
                                                                                 for x in c.get('findings') or []])):
        check(f['kind'] == KINDS[k], '%s is %s, not %s: %r' % (k, f['kind'], KINDS[k], f))
        if k in WHY_WORDS:
            check(WHY_WORDS[k] in f.get('why', ''), '%s does not say why ("%s"): %r' % (k, WHY_WORDS[k], f.get('why')))
check(not any(f['target'] == 'httpd_var_run_t' and f['perms'] == 'read' for f in c.get('findings') or []),
      'what the policy allows now is shown')
check((c.get('counts') or {}).get('allowed') == 1, 'allowed now not counted apart: %r' % c.get('counts'))
n = c.get('counts') or {}
check(n.get('fixable') == 6 and n.get('notbutton') == 9 and n.get('other') == 2,
      'the counts: %r' % n)
fb, fl, fp, fr = F['boolean'] or {}, F['label'] or {}, F['port'] or {}, F['rule'] or {}
check(fb.get('fix') == 'setsebool -P httpd_can_network_connect 1' and fb.get('program') == 'php-fpm',
      'the boolean: the safe one of the two, never nis_enabled: %r' % fb)
check(fl.get('path') == str(CORE_JS) and fl.get('fix') == 'restorecon -R -v %s' % CORE_JS
      and 'the policy says httpd_sys_content_t' in fl.get('why', ''), 'the label (a hex path decoded): %r' % fl)
check(fp.get('fix') == 'semanage port -a -t http_port_t -p tcp 8445' and fp.get('proto') == 'tcp', 'the port: %r' % fp)
check(fr.get('fix') == '(allow unconfined_service_t chronyc_t (process2 (nnp_transition)))' and fr.get('count') == 2
      and fr.get('program') == 'zigmon tick' and fr.get('permissive'),
      'the rule (comm hex-decoded, two refusals one finding): %r' % fr)
check((F['rule3'] or {}).get('path') == '/var/log/zigmon/zigmon.log',
      'a relative PATH with a hex cwd: %r' % F['rule3'])
check((F['rule2'] or {}).get('fix') == '(allow chronyc_t unconfined_service_t (fifo_file (write)))',
      'the tool writing back to the daemon: %r' % F['rule2'])
check(not any(f.get('fix') for f in c.get('findings') or [] if f['kind'] in ('notbutton', 'other')),
      'a finding not for a button has a fix')
for f in c.get('findings') or []:
    check(re.match(r'^[0-9a-f]{12}$', f['id']), 'an id is not 12 hex: %r' % f['id'])
    check('line' not in f and 'evs' not in f, 'the raw record went out with a finding')
blob = json.dumps(c)
check(ZTITLE not in blob and hx(ZTITLE) not in blob, 'the command line of a program went out with the look')
check(not any('7A69676D' in (g0.get('what') or '') for g0 in (c.get('denials') or {}).get('groups') or []),
      'the count\'s words show a name still hex: %r' % (c.get('denials') or {}).get('groups'))
check(not any(x.startswith(('setsebool', 'restorecon', 'semanage port -a', 'semodule -i', 'semodule -r', 'setenforce'))
              for x in calls()), 'a look changed something: %r' % calls())
check(c.get('ready') is False and any('can be put right here' in p for p in c.get('problems') or [])
      and any('not for a button' in p for p in c.get('problems') or []), 'the problems: %r' % c.get('problems'))
ids1 = sorted(f['id'] for f in c.get('findings') or [])
rc, c2, g = helper(['--selinux-check', '--json'])
check(sorted(f['id'] for f in (c2 or {}).get('findings') or []) == ids1, 'the ids are not the same at the next look')
# the same ids through the page's road (selinux.ask), "look" a name of the check
got, g = ask_root(dict(WANT, do='look', id='abc'))
check(got.get('ok') and sorted(f['id'] for f in (got.get('data') or {}).get('findings') or []) == ids1,
      'do=look through selinux.ask: %r %s' % ({k: got.get(k) for k in ('ok', 'said')}, g.stderr[-300:]))

# ---- root: fix by ids ---------------------------------------------------------------------
print('root: fix by ids only')
IDS = {k: (F[k] or {}).get('id', 'x') for k in F}
for wrong, words in (({'ids': ['zzzzzzzzzzzz']}, '12 hex'),
                     ({'ids': []}, 'one finding id at least'),
                     ({'ids': 'abc'}, 'one finding id'),
                     ({'ids': ['0123456789ab']}, 'not in the audit log'),
                     ({'ids': [IDS['rule']], 'rule': '(allow httpd_t shadow_t (file (read)))'}, 'finding ids only'),
                     ({'ids': [IDS['label']], 'path': '/etc'}, 'finding ids only'),
                     ({'ids': [IDS['boolean'], IDS['nb_sensitive']]}, 'not for a button'),
                     ({'ids': [IDS['other_php']]}, 'not for a button'),
                     ({'ids': [IDS['nb_bool']]}, 'not for a button')):
    got, g = ask_root(dict(WANT, do='fix', id='x1', **wrong))
    check(not got.get('ok') and words in (got.get('said') or ''), '%r not refused with "%s": %r %s'
          % (wrong, words, got, g.stderr[-200:]))
check(not any(x.startswith(('setsebool', 'restorecon', 'semanage port -a', 'semodule -i', 'semodule -r'))
              for x in calls()), 'a refused request did something: %r' % calls())
check(not fake()['bools']['nis_enabled'] and not fake()['bools']['httpd_execmem'], 'a dangerous boolean was set')
# under enforcing: put right all that may be
fake_set(mode='Enforcing')
SE_CONFIG.write_text('SELINUX=enforcing\nSELINUXTYPE=targeted\n')
fix_ids = [IDS[k] for k in ('boolean', 'label', 'port', 'rule', 'rule2')]
got, g = ask_root(dict(WANT, do='fix', id='x2', ids=fix_ids, by='owner'))
data = got.get('data') or {}
check(got.get('ok') and sorted(data.get('fixed_now') or []) == sorted(fix_ids) and not data.get('failed'),
      'fix under enforcing: %r %s' % ({k: got.get(k) for k in ('ok', 'said')}, g.stderr[-400:]))
cl = calls()
check('setsebool -P httpd_can_network_connect on' in cl and fake()['bools']['httpd_can_network_connect'],
      'the boolean was not set: %r' % cl)
check(not fake()['bools']['nis_enabled'], 'nis_enabled was set')
check('restorecon -R -v %s' % CORE_JS in cl and json.loads(LABELS.read_text())[str(CORE_JS)] == 'httpd_sys_content_t',
      'restorecon: %r' % cl)
check('semanage port -a -t http_port_t -p tcp 8445' in cl and [8445, 8445] in fake()['ports']['http_port_t/tcp'],
      'semanage port -a: %r' % cl)
cil_path = LOCAL_DIR / 'zigmon_local.cil'
check('semodule -i %s' % cil_path in cl and 'zigmon_local' in fake()['modules'], 'the local module was not loaded: %r' % cl)
check(not any(' -m ' in x for x in cl if x.startswith('semanage')), 'semanage -m was run')
cil = cil_path.read_text() if cil_path.exists() else ''
check('(optional zigmon_local_%s\n    (allow unconfined_service_t chronyc_t (process2 (nnp_transition))))' % IDS['rule']
      in cil and '(optional zigmon_local_%s\n    (allow chronyc_t unconfined_service_t (fifo_file (write))))'
      % IDS['rule2'] in cil, 'the local module: %s' % cil)
check((LOCAL_DIR / 'zigmon_local.cil.in-policy').read_text() == cil if cil else False, 'the .in-policy copy')
check(cil_path.stat().st_mode & 0o777 == 0o600 and LOCAL_DIR.stat().st_mode & 0o777 == 0o700,
      'the local module is not root\'s own')
check(fake()['mode'] == 'Enforcing', 'putting right switched the mode')
said = ' | '.join(data.get('said') or [])
for w in ('the boolean httpd_can_network_connect on', 'labelled as the policy says', 'port 8445/tcp labelled http_port_t',
          'rule (allow unconfined_service_t chronyc_t', 'zigmon_local) put into the policy - 2 rule(s)'):
    check(w in said, 'what root did does not say "%s": %s' % (w, said))
fx = by_kind(data)
check(sorted(f['id'] for f in fx.get('fixed') or []) == sorted(fix_ids),
      'put right just now: %r' % [(f['kind'], f['id']) for f in data.get('findings') or []])
check((data.get('counts') or {}).get('fixable') == 1, 'still fixable after: %r' % data.get('counts'))
rules = (data.get('local') or {}).get('rules') or []
check([x['id'] for x in rules] == [IDS['rule'], IDS['rule2']] and rules[0].get('by') == 'owner'
      and rules[0].get('rule') == '(allow unconfined_service_t chronyc_t (process2 (nnp_transition)))'
      and (data.get('local') or {}).get('in_policy') is True, 'the local rules listed: %r' % data.get('local'))
marks = json.loads((OWN / 'selinux-fixed').read_text())
check(set(marks) == set(fix_ids) and all(abs(m['at'] - time.time()) < 120 for m in marks.values()),
      'what was put right is not noted with its time: %r' % marks)
# the old count no longer counts what was put right
den = data.get('denials') or {}
check(not any(g0['source'] == 'httpd_t' and g0['target'] == 'default_t' for g0 in den.get('groups') or []),
      'a refusal put right still counts: %r' % den.get('groups'))
# again: what is in already is not done twice
n_i = sum(1 for x in calls() if x.startswith('semodule -i'))
got, g = ask_root(dict(WANT, do='fix', id='x3', ids=[IDS['rule']]))
check(got.get('ok') and sum(1 for x in calls() if x.startswith('semodule -i')) == n_i, 'put in twice: %r' % got)
# refused again after it was put right: it comes back
s = fake()
s['raw'].append('\n'.join(event(time.time() + 2, [avc('read', 'httpd_t', 'default_t', 'file', '"nginx"')],
                                '"nginx"', '"/usr/sbin/nginx"', [(hx(str(CORE_JS)), 'default_t')])[0]))
FAKE_STATE.write_text(json.dumps(s))
time.sleep(2.2)
rc, c3, g = helper(['--selinux-check', '--json'])
f3 = finding(c3, id=IDS['label']) or {}
check(f3.get('kind') == 'allowed' or f3.get('kind') == 'label' or f3 == {},
      'refused again after the fix: %r' % f3)
check(not finding(c3, id=IDS['label'], kind='fixed'), 'refused again, and still "put right"')
# the third rule: semodule failing - nothing of it kept
fake_set(semodule_fail=True)
got, g = ask_root(dict(WANT, do='fix', id='x4', ids=[IDS['rule3']]))
data = got.get('data') or {}
check(got.get('ok') and data.get('failed') and 'could not' in ' '.join(data.get('said') or []),
      'a semodule that failed is not said: %r' % got)
check(IDS['rule3'] not in (LOCAL_DIR / 'rules.json').read_text() and IDS['rule3'] not in cil_path.read_text(),
      'a rule semodule refused was kept in the list')
fake_set(semodule_fail=False)
# a port that became another service's after the look: refused at the moment of it
machine(mode='Permissive')
rc, c4, g = helper(['--selinux-check', '--json'])
check((finding(c4, port=8445) or {}).get('kind') == 'port', 'the port before: %r' % finding(c4, port=8445))
s = fake()
s['ports']['mysqld_port_t/tcp'] = [[8445, 8445]]
FAKE_STATE.write_text(json.dumps(s))
got, g = ask_root(dict(WANT, do='fix', id='x5a', ids=[IDS['port']]))
check(not got.get('ok') and 'mysqld_port_t' in (got.get('said') or ''),
      'a port that became another\'s after the look was not refused: %r' % got)
rc, c4, g = helper(['--selinux-check', '--json'])
f4 = finding(c4, port=8445) or {}
check(f4.get('kind') == 'notbutton' and 'mysqld_port_t' in f4.get('why', ''), 'a port another type has: %r' % f4)
got, g = ask_root(dict(WANT, do='fix', id='x5', ids=[f4.get('id', '')]))
check(not got.get('ok') and 'not for a button' in (got.get('said') or ''), 'fixing another\'s port: %r' % got)
check(not any(x.startswith('semanage port -a') for x in calls()), 'semanage port -a for another\'s port')

# ---- root: the local rules taken away; enforcing locked -----------------------------------
print('root: rule_drop, enforcing locked while anything is left')
machine(mode='Permissive', modules=['base', 'zigmon_server'])
got, g = ask_root(dict(WANT, do='fix', id='x5b', ids=[IDS['rule'], IDS['rule2']]))
check(got.get('ok') and 'zigmon_local' in fake()['modules'], 'the two rules put in again: %r' % got.get('said'))
got, g = ask_root(dict(WANT, do='rule_drop', id='x6', ids=['0123456789ab']))
check(not got.get('ok') and 'no rule' in (got.get('said') or ''), 'an unknown rule taken away: %r' % got)
got, g = ask_root(dict(WANT, do='rule_drop', id='x7', ids=[IDS['rule']], rule='(allow a_t b_t (file (read)))'))
check(not got.get('ok') and 'ids only' in (got.get('said') or ''), 'rule_drop carrying a rule: %r' % got)
got, g = ask_root(dict(WANT, do='rule_drop', id='x8', ids=[IDS['rule']]))
data = got.get('data') or {}
check(got.get('ok') and [x['id'] for x in (data.get('local') or {}).get('rules') or []] == [IDS['rule2']]
      and 'semodule -i %s' % cil_path in calls() and IDS['rule'] not in cil_path.read_text(),
      'a rule taken away: %r %s' % (got.get('said'), g.stderr[-300:]))
check(IDS['rule'] not in json.loads((OWN / 'selinux-fixed').read_text()), 'its "put right" stayed')
check((finding(data, id=IDS['rule']) or {}).get('kind') == 'rule', 'taken away, it comes back as a rule to put in')
got, g = ask_root(dict(WANT, do='rule_drop', id='x9', ids=[IDS['rule2']]))
data = got.get('data') or {}
check(got.get('ok') and 'semodule -r zigmon_local' in calls() and 'zigmon_local' not in fake()['modules']
      and not cil_path.exists() and not (LOCAL_DIR / 'zigmon_local.cil.in-policy').exists()
      and not (data.get('local') or {}).get('rules'), 'the last rule: semodule -r: %r %r' % (got.get('said'), calls()))
# enforcing locked while something is left
rc, c, g = helper(['--selinux-do', 'enforce', '--json'])
check(rc == 1 and 'not yet' in ((c or {}).get('said') or '') and fake()['mode'] == 'Permissive',
      'enforce while findings are left: %r' % c)
# nothing of zigmon's left: only another program's refusal, which is no partner of zigmon's
machine(mode='Permissive', raw=['\n'.join(RAW[list(FIX).index('other_smb')])],
        bools={'httpd_can_network_connect': True}, ports={'http_port_t/tcp': [[80, 81], [443, 443], [8445, 8445]]})
rc, c, g = helper(['--selinux-check', '--json'])
check(c and c.get('ready') is True and (c.get('counts') or {}).get('other') == 1, 'only another\'s refusal, '
      'and not ready: %r' % (c or {}).get('problems'))
rc, c, g = helper(['--selinux-do', 'enforce', '--json'])
check(rc == 0 and fake()['mode'] == 'Enforcing', 'enforce once nothing is left: %r' % c)
# the steps from the command line of root: fix by id
machine(mode='Permissive')
rc, c, g = helper(['--selinux-fix', IDS['port'], '--json'])
check(rc == 0 and c and (c.get('fixed_now') or []) == [IDS['port']], 'zigmon_root.py --selinux-fix: %r %s'
      % (c, g.stderr[-300:]))
rc, c, g = helper(['--selinux-fix', 'deadbeef', '--json'])
check(rc == 1 and '12 hex' in ((c or {}).get('said') or ''), 'a wrong id on root\'s command line: %r' % c)



# ---- the report: the whole machine in os/, no secret of zigmon's anywhere ------------------
print('the report: os/ files, no secret')
machine(mode='Permissive')
s = fake()
s['raw'].append('\n'.join(event(NOW, [avc('read', 'httpd_t', 'var_run_t', 'file', '"php-fpm"',
                                          'name="%s" password=hunter2' % SMS_PASSWORD)], '"php-fpm"',
                                '"/usr/sbin/php-fpm"', title='curl -H X-Zigmon-Token:%s' % TOKEN)[0]))
FAKE_STATE.write_text(json.dumps(s))
REPORT = W / 'report.tar.gz'
rc, c, g = helper(['--selinux-report', str(REPORT), '--json'])
check(rc == 0 and REPORT.is_file(), 'the report was not written: %s' % g.stderr[-300:])
part = {}
try:
    with tarfile.open(str(REPORT)) as tf:
        for m in tf.getmembers():
            part[m.name.split('/', 1)[-1]] = tf.extractfile(m).read().decode('utf-8', 'replace')
except (OSError, tarfile.TarError) as e:
    check(False, 'the report does not open: %s' % e)
for want in ('check.json', 'avc-raw.txt', 'avc.txt', 'audit2why.txt', 'audit2allow.te', 'labels.txt', 'processes.txt',
             'ports.txt', 'booleans.txt', 'modules.txt', 'system.txt', 'README.txt', 'os/processes.txt',
             'os/booleans.txt', 'os/ports.txt', 'os/modules.txt', 'os/local-changes.txt', 'os/semanage-export.txt',
             'os/listening.txt'):
    check(want in part, 'the report has no %s: %r' % (want, sorted(part)))
for name, text in part.items():
    for secret in (TOKEN, SMS_PASSWORD, 'hunter2', TOKEN.encode().hex()[:24]):
        check(secret not in text, 'the report\'s %s holds a secret: %s...' % (name, secret[:6]))
check('httpd_can_network_connect' in part.get('os/booleans.txt', '') and 'nis_enabled' in part.get('os/booleans.txt', ''),
      'os/booleans.txt is not every boolean: %r' % part.get('os/booleans.txt', '')[:200])
check('jboss_management_port_t' in part.get('os/ports.txt', ''), 'os/ports.txt is not every port type')
check('400 apache' in part.get('os/modules.txt', ''), 'os/modules.txt is not semodule -lfull: %r'
      % part.get('os/modules.txt', '')[:200])
lc = part.get('os/local-changes.txt', '')
check(all('semanage %s -l -C' % w in lc for w in ('boolean', 'port', 'fcontext', 'login', 'user', 'module', 'permissive')),
      'os/local-changes.txt: %r' % lc[:300])
check('boolean -m -1 httpd_can_network_connect' in part.get('os/semanage-export.txt', ''), 'semanage export')
check('LABEL' in part.get('os/processes.txt', '') or 'ps' in part.get('os/processes.txt', ''), 'os/processes.txt')
check('"findings"' in part.get('check.json', ''), 'check.json has no findings')
check('os/' in part.get('README.txt', ''), 'the README does not say what os/ is')
check(not any(x.startswith(('setsebool', 'restorecon', 'semanage port -a', 'semodule -i', 'semodule -r'))
              for x in calls()), 'making the report changed something: %r' % calls())

# ---- the CIL: zigmon_server's nnp blocks; both modules compiled ----------------------------
print('the modules: forms, secilc')
SERVER_CIL = (HERE / 'deploy' / 'zigmon_server.cil').read_text()
for dom in ('chronyc_t', 'iptables_t', 'ssh_t', 'ssh_keygen_t'):
    check(re.search(r'\(optional zigmon_server_nnp_\w+\n\s+\(allow unconfined_service_t %s \(process2 '
                    r'\(nnp_transition nosuid_transition\)\)\)\)' % dom, SERVER_CIL),
          'zigmon_server.cil has no optional nnp_transition block for %s' % dom)
check('NoNewPrivileges=yes' in (HERE / 'deploy' / 'zigmon.service').read_text(),
      'zigmon.service no longer runs with NoNewPrivileges - the nnp blocks are for that')


def cil_forms(text):
    """Balanced, and only the statement forms zigmon's modules use."""
    body = '\n'.join(line.split(';', 1)[0] for line in text.splitlines())
    depth = 0
    for ch in body:
        depth += {'(': 1, ')': -1}.get(ch, 0)
        if depth < 0:
            return 'a ) too many'
    if depth:
        return 'a ( not closed'
    flat = re.sub(r'\s+', ' ', body).replace('( ', '(').replace(' )', ')').strip()
    perm = r'\([a-z0-9_]+ \([a-z0-9_]+(?: [a-z0-9_]+)*\)\)'
    allow = r'\(allow [a-z0-9_]+_t [a-z0-9_]+_t %s\)' % perm
    forms = [r'\(filecon "[^"]+" (?:dir|file|any) \(system_u object_r [a-z0-9_]+_t \(\(s0\) \(s0\)\)\)\)',
             r'\(optional [a-z0-9_]+(?: %s)+\)' % allow]
    rest = flat
    for f in forms:
        rest = re.sub(f, '', rest)
    return rest.strip() and 'unknown: %s' % rest.strip()[:120] or ''


check(cil_forms(SERVER_CIL) == '', 'zigmon_server.cil: %s' % cil_forms(SERVER_CIL))
machine(mode='Permissive')
got, g = ask_root(dict(WANT, do='fix', id='c1', ids=[IDS['rule'], IDS['rule2'], IDS['rule3']]))
LOCAL_CIL = cil_path.read_text() if cil_path.exists() else ''
check(LOCAL_CIL.count('(optional zigmon_local_') == 3 and cil_forms(LOCAL_CIL) == '',
      'the local module\'s forms: %s %s' % (cil_forms(LOCAL_CIL), LOCAL_CIL[-400:]))
BASE = '''(handleunknown allow)
(class file (read write getattr setattr open))
(class dir (read search getattr setattr open))
(class fifo_file (read write))
(class process (transition))
(class process2 (nnp_transition nosuid_transition))
(classorder (file dir fifo_file process process2))
(sid kernel)
(sidorder (kernel))
(user system_u)
(role system_r)
(role object_r)
(type kernel_t)
(type init_t)
(type httpd_var_run_t)
(type unconfined_service_t)
%s
(category c0)
(categoryorder (c0))
(sensitivity s0)
(sensitivityorder (s0))
(sensitivitycategory s0 (c0))
(allow kernel_t self (file (read)))
(roletype system_r kernel_t)
(roletype object_r httpd_var_run_t)
(userrole system_u system_r)
(userrole system_u object_r)
(userlevel system_u (s0))
(userrange system_u ((s0)(s0 (c0))))
(sidcontext kernel (system_u system_r kernel_t ((s0)(s0))))
'''
secilc = shutil.which('secilc')
if secilc:
    cd = W / 'cil'
    cd.mkdir()
    (cd / 'server.cil').write_text(SERVER_CIL)
    (cd / 'local.cil').write_text(LOCAL_CIL)
    (cd / 'broken.cil').write_text(LOCAL_CIL.replace('(fifo_file (write))))', '(fifo_file (write)))', 1))
    for name, types in (('every type', '(type chronyc_t)\n(type ssh_t)\n(type ssh_keygen_t)\n(type iptables_t)\n'
                                       '(type logrotate_t)\n(type httpd_log_t)'),
                        ('no tool\'s type: the optional blocks left out', '')):
        (cd / 'base.cil').write_text(BASE % types)
        got = sh([secilc, '-M', 'true', '-o', str(cd / 'policy.bin'), '-f', str(cd / 'fc.txt'), str(cd / 'base.cil'),
                  str(cd / 'server.cil'), str(cd / 'local.cil')], timeout=60)
        check(got.returncode == 0, 'secilc refused the modules (%s): %s' % (name, (got.stdout + got.stderr)[-400:]))
        if got.returncode == 0:
            fc = (cd / 'fc.txt').read_text()
            check('/run/zigmon\t-d\tsystem_u:object_r:httpd_var_run_t:s0' in fc and '/var/run/zigmon/.*' in fc,
                  'the labels secilc made: %r' % fc)
    got = sh([secilc, '-M', 'true', '-o', str(cd / 'policy.bin'), '-f', str(cd / 'fc.txt'), str(cd / 'base.cil'),
              str(cd / 'server.cil'), str(cd / 'broken.cil')], timeout=60)
    check(got.returncode != 0, 'secilc took a broken module - the check means nothing')
else:
    print('  (secilc is not here: the forms only)')

# ---- install.sh: --uninstall takes zigmon_local away too ---------------------------------
print('install.sh')
IB = W / 'instbin'
IB.mkdir()
for tool in ('getenforce', 'semodule', 'semanage', 'restorecon', 'matchpathcon', 'getsebool', 'setsebool'):
    (IB / tool).symlink_to(BIN / 'sefake')
for x, body in (('rpm', 'exit 0'), ('dnf', 'exit 0'), ('systemctl', '[ "$1" = is-active ] && exit 0\nexit 0'),
                ('auditd', 'exit 0')):
    (IB / x).write_text('#!/bin/sh\necho "%s $*" >> %s\n%s\n' % (x, FAKE_LOG, body))
    (IB / x).chmod(0o755)
inst = W / 'install-functions.sh'
inst.write_text('\n'.join((HERE / 'install.sh').read_text().splitlines()[:-1]) + '\n')
machine(mode='Permissive', modules=['base', 'zigmon_server', 'zigmon_local'])
got = sh(['bash', '-c', 'source %s\nLIB_DIR=%s\nWEB_DIR=%s\nDRY_RUN=yes\ndo_uninstall\n' % (inst, W / 'ilib', W / 'iweb')],
         env=dict(os.environ, PATH='%s:%s' % (IB, os.environ.get('PATH', ''))), timeout=120)
check('[would run] semodule -r zigmon_server' in got.stdout and '[would run] semodule -r zigmon_local' in got.stdout,
      'uninstall does not take both modules away: %s' % got.stdout[-500:])
check('zigmon_local' in fake()['modules'], 'a dry run took a module away')
sh_text = (HERE / 'install.sh').read_text()
sel = sh_text[sh_text.index('selinux_tools() {'):sh_text.index('configure_firewall() {')]
check('setenforce' not in sel and 'SELINUX=' not in sel, 'install.sh touches the mode')

# ---- the daemon and the API ---------------------------------------------------------------
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


def tick_wait(most=180):
    zigmon.SE_WORK['busy'] = False
    zigmon.selinux_tick(d)
    end = time.time() + most
    time.sleep(0.2)
    while zigmon.SE_WORK['busy'] and time.time() < end:
        time.sleep(0.1)


d.account_add('owner', 'admin', 'owner pass 12', must_change=False, quiet=True)
d.account_add('jana', 'operator', 'jana pass 12', must_change=False, quiet=True)
d.account_add('vera', 'viewer', 'vera pass 12', must_change=False, quiet=True)
S = call('/api/auth/login', {'name': 'owner', 'password': 'owner pass 12'})[1].get('token') or ''
S_OP = call('/api/auth/login', {'name': 'jana', 'password': 'jana pass 12'})[1].get('token') or ''
S_RO = call('/api/auth/login', {'name': 'vera', 'password': 'vera pass 12'})[1].get('token') or ''
check(S and S_OP and S_RO, 'could not sign in')
zigmon.SE_WORK.update(busy=False, seen=time.time(), tried='')
machine(mode='Permissive')
for who, sess in (('anybody', None), ('an operator', S_OP), ('a read-only account', S_RO)):
    for body in ({'action': 'look'}, {'action': 'fix', 'ids': [IDS['rule']]}, {'action': 'rule_drop', 'id': IDS['rule']}):
        code, _ = call('/api/selinux', body, session=sess)
        check(code == 403, 'POST /api/selinux %s went through for %s: %s' % (body['action'], who, code))
    code, _ = call('/api/selinux', session=sess)
    check(code == 403, 'GET /api/selinux answered %s: %s' % (who, code))
check(not d._mj('selinux:want'), 'a refused POST asked for something')
for body, words in (({'action': 'fix', 'ids': [IDS['rule']], 'rule': '(allow httpd_t shadow_t (file (read)))'},
                     'finding ids only'),
                    ({'action': 'fix', 'ids': [IDS['label']], 'path': '/etc'}, 'finding ids only'),
                    ({'action': 'fix', 'ids': ['../../etc']}, '12 hex'),
                    ({'action': 'fix', 'ids': []}, 'one finding id'),
                    ({'action': 'fix', 'ids': ['a' * 12] * 0 + ['%012x' % i for i in range(65)]}, 'at most'),
                    ({'action': 'rule_drop', 'id': 'nope'}, '12 hex'),
                    ({'action': 'rule_drop', 'id': [IDS['rule'], IDS['rule2']]}, 'at most')):
    code, v = call('/api/selinux', body, session=S)
    check(code == 400 and words in v.get('error', ''), '%r: %s %r' % (body, code, v))
check(not d._mj('selinux:want'), 'a refused request asked root for something')
# a look through the page's road
code, v = call('/api/selinux', {'action': 'look'}, session=S)
check(code == 200 and v.get('pending') == 'look', 'POST look: %s %r' % (code, v))
tick_wait()
now = d._mj('selinux:now') or {}
data = now.get('data') or {}
check(now.get('action') == 'look' and len(data.get('findings') or []) == 17 and not now.get('error'),
      'the look through the daemon: %r' % {k: now.get(k) for k in ('action', 'error')})
note = (d.notices_all() or {}).get('selinux-refuses') or {}
check(note.get('title') == 'SELinux refuses zigmon something - 6 can be put right on the card'
      and note.get('link') == '#control/sec-selinux' and note.get('level') == 'info',
      'the notice: %r' % note)
ev_before = len(d.store.events(limit=500))
# looked at again: the same set, no second word of it
zigmon.selinux_notice(d, data)
check(len([e for e in d.store.events(limit=500) if 'SELinux refuses zigmon' in (e.get('detail') or '')]) == 1,
      'the notice was told twice for the same refusals')
# put right - through the API, end to end
want_ids = [IDS[k] for k in ('boolean', 'label', 'port', 'rule')]
code, v = call('/api/selinux', {'action': 'fix', 'ids': want_ids}, session=S)
check(code == 200 and v.get('pending') == 'fix', 'POST fix: %s %r' % (code, v))
want = d._mj('selinux:want') or {}
check(want.get('ids') == want_ids and want.get('by') == 'owner' and set(want) == {'id', 'do', 'by', 'at', 'ids'},
      'what the daemon keeps of the request: %r' % want)
code, v = call('/api/selinux', {'action': 'look'}, session=S)
check(code == 200 and (d._mj('selinux:want') or {}).get('id') == want.get('id'), 'a look put the fix aside')
tick_wait()
now = d._mj('selinux:now') or {}
data = now.get('data') or {}
check(now.get('done') == want.get('id') and now.get('action') == 'fix' and not now.get('error')
      and sorted(data.get('fixed_now') or []) == sorted(want_ids), 'the fix through the daemon: %r'
      % {k: now.get(k) for k in ('action', 'error', 'said')})
check(fake()['bools']['httpd_can_network_connect'] and 'zigmon_local' in fake()['modules']
      and [8445, 8445] in fake()['ports'].get('http_port_t/tcp', []), 'the machine after the fix: %r' % fake()['bools'])
ev = [e.get('detail', '') for e in d.store.events(limit=500)]
check(any('owner asked SELinux: put right 4' in x for x in ev), 'no event for the request: %r' % ev[:5])
for i in want_ids:
    check(any(x.startswith('SELinux: %s: ' % i) for x in ev), 'no event for the step of %s: %r' % (i, ev[:12]))
check(any('zigmon_local) put into the policy' in x for x in ev), 'no event for the module')
note = (d.notices_all() or {}).get('selinux-refuses') or {}
check('2 can be put right' in note.get('title', ''), 'the notice after the fix: %r' % note)
code, v = call('/api/selinux', session=S)
check(code == 200 and len([f for f in v['state'].get('findings') or [] if f['kind'] == 'fixed']) == 4
      and v.get('said'), 'the page does not see what was put right: %r' % v.get('said'))
# a rule taken away, through the API
code, v = call('/api/selinux', {'action': 'rule_drop', 'id': IDS['rule']}, session=S)
check(code == 200 and v.get('pending') == 'rule_drop', 'POST rule_drop: %s %r' % (code, v))
tick_wait()
now = d._mj('selinux:now') or {}
check(now.get('action') == 'rule_drop' and not now.get('error') and 'zigmon_local' not in fake()['modules'],
      'the last rule taken away through the daemon: %r' % {k: now.get(k) for k in ('error', 'said')})
check(any('semodule -r' in x or 'taken out of the policy' in x for x in
          [e.get('detail', '') for e in d.store.events(limit=50)]), 'no event for the module taken out')
# nothing of zigmon's left: the notice goes by itself
fake_set(raw=['\n'.join(RAW[list(FIX).index('other_smb')])])
code, v = call('/api/selinux', {'action': 'look'}, session=S)
tick_wait()
check(not (d.notices_all() or {}).get('selinux-refuses'), 'the notice stayed with nothing of zigmon\'s left')

# ---- the command line -------------------------------------------------------------------------
print('the command line')
cli_env = dict(os.environ)
cli_env.pop('ZIGMON_ROOT_RUN', None)
cfg = W / 'cli-config.json'
cfg.write_text(json.dumps(dict(CONF, db_file=str(W / 'cli.db'), api_port=API_PORT, log_file='',
                               token_file=str(W / 'token'))))


def cli(*args, **kw):
    return sh([sys.executable, str(HERE / 'zigmon.py'), '--config', str(cfg)] + list(args), env=cli_env, timeout=300,
              **kw)


parser = zigmon.build_parser()
a1 = parser.parse_args(['--selinux-fix', 'aaaaaaaaaaaa', 'bbbbbbbbbbbb', '--yes'])
a2 = parser.parse_args(['--selinux-fix', '--all'])
a3 = parser.parse_args(['--selinux-rules', '--take-away', 'cccccccccccc'])
a4 = parser.parse_args(['--selinux-look', '--json'])
check(a1.selinux_fix == ['aaaaaaaaaaaa', 'bbbbbbbbbbbb'] and a1.yes and a2.selinux_fix == [] and a2.all
      and a3.selinux_rules and a3.take_away == 'cccccccccccc' and a4.selinux_look and a4.json,
      'the command line does not parse')
help_text = '\n'.join(str(x) for x in zigmon.HELP_LINES)
for w in ('--selinux-look', '--selinux-fix', '--all', '--selinux-rules', '--take-away'):
    check(w in help_text, 'the help does not name %s' % w)
machine(mode='Permissive')
got = cli('--selinux-look', '--json')
try:
    j = json.loads(got.stdout)
except ValueError:
    j = {}
check(got.returncode == 0 and len(j.get('findings') or []) == 17 and (j.get('counts') or {}).get('fixable') == 6,
      'zigmon --selinux-look --json: %s %r' % (got.returncode, (got.stdout + got.stderr)[-400:]))
got = cli('--selinux-look')
check(got.returncode == 0 and IDS['rule'] in got.stdout and 'Not for a button (9)' in got.stdout
      and 'A rule of zigmon' in got.stdout and '-> (allow unconfined_service_t chronyc_t' in got.stdout
      and 'shadow_t is security-sensitive' in got.stdout, 'zigmon --selinux-look: %r' % got.stdout[-600:])
got = cli('--selinux-fix', IDS['rule'])
check(got.returncode != 0 and '--yes' in got.stdout and 'zigmon_local' not in fake()['modules'],
      'zigmon --selinux-fix without --yes and no terminal: %r' % (got.stdout + got.stderr)[-300:])
check('root does exactly this' in got.stdout and '(allow unconfined_service_t chronyc_t' in got.stdout,
      'it does not list what root will do: %r' % got.stdout[-400:])
got = cli('--selinux-fix', IDS['nb_sensitive'], '--yes')
check(got.returncode == 1 and 'not for a button' in got.stdout, 'a finding not for a button from the command line: %r'
      % got.stdout[-300:])
got = cli('--selinux-fix', '0123456789ab', '--yes')
check(got.returncode == 1 and 'no such finding' in got.stdout, 'an unknown id: %r' % got.stdout[-300:])
got = cli('--selinux-fix', '--all', '--yes')
check(got.returncode == 0 and 'looked again: 0 can be put right' in got.stdout
      and fake()['bools']['httpd_can_network_connect'] and 'zigmon_local' in fake()['modules'],
      'zigmon --selinux-fix --all --yes: %r' % (got.stdout + got.stderr)[-600:])
check(not fake()['bools']['nis_enabled'], '--all set a dangerous boolean')
got = cli('--selinux-rules')
check(got.returncode == 0 and 'zigmon_local): 3, in the policy' in got.stdout and IDS['rule3'] in got.stdout,
      'zigmon --selinux-rules: %r' % got.stdout[-500:])
got = cli('--selinux-rules', '--take-away', IDS['rule3'], '--yes')
check(got.returncode == 0 and IDS['rule3'] not in (LOCAL_DIR / 'rules.json').read_text(),
      'zigmon --selinux-rules --take-away: %r' % (got.stdout + got.stderr)[-400:])
got = cli('--selinux-rules', '--take-away', '0123456789ab', '--yes')
check(got.returncode == 1 and 'no rule' in got.stdout, 'taking away a rule that is not there: %r' % got.stdout[-300:])
got = cli('--selinux-check')
check('findings:' in got.stdout and 'local rules' in got.stdout, 'zigmon --selinux-check says nothing of the findings: %r'
      % got.stdout[-400:])
# the console's menu
check(any(w == 'SELinux' for w, _ in zigmon.CONSOLE_MORE['main']), 'the console has no SELinux menu')
acts = []


class FakeConsole(object):
    def sub(self, title, items, more=None):
        self.items = items
        return title

    def act(self, *a, **k):
        acts.append(a)

    def confirm(self, *a, **k):
        return True


fc = FakeConsole()
dict(zigmon.CONSOLE_MORE['main'])['SELinux'](fc)
for _, fn in fc.items:
    fn()
check(('--selinux-look',) in acts and ('--selinux-fix', '--all', '--yes') in acts and ('--selinux-rules',) in acts
      and ('--selinux-check',) in acts, 'the console\'s items: %r' % acts)


# ---- the card --------------------------------------------------------------------------------
print('the card (Chromium)')


def look_now(**kw):
    rc, c, g = helper(['--selinux-check', '--json'])
    return c or {}


# 06: enforcing, something refused (a local rule in already)
machine(mode='Enforcing')
SE_CONFIG.write_text('SELINUX=enforcing\nSELINUXTYPE=targeted\n')
got, g = ask_root(dict(WANT, do='fix', id='p1', ids=[IDS['rule']], by='owner'))
time.sleep(0.1)
ENF_BAD = look_now()
# 05: enforcing, nothing refused - the local rule stays
fake_set(raw=[], bools=dict(fake()['bools'], httpd_can_network_connect=True),
         ports=dict(fake()['ports'], **{'http_port_t/tcp': [[80, 81], [443, 443], [8445, 8445]]}))
ENF_OK = look_now()
# 08, 09: disabled; made ready
machine(mode='Disabled')
SE_CONFIG.write_text('SELINUX=disabled\nSELINUXTYPE=targeted\n')
DIS = look_now()
SE_CONFIG.write_text('SELINUX=permissive\nSELINUXTYPE=targeted\n')
RELABEL.write_text('')
MADE = look_now()
RELABEL.unlink()
# 01..04: permissive with everything of the fixture - kept as it is, so that the page's "Put in"
# is put in by root for real
machine(mode='Permissive')
PERM = look_now()
check(ENF_BAD.get('mode') == 'Enforcing' and (ENF_BAD.get('counts') or {}).get('fixable') == 5
      and len((ENF_BAD.get('local') or {}).get('rules') or []) == 1, 'the enforcing state: %r' % ENF_BAD.get('counts'))
check(ENF_OK.get('mode') == 'Enforcing' and not ENF_OK.get('problems') and (ENF_OK.get('local') or {}).get('rules'),
      'the calm enforcing state: %r' % ENF_OK.get('problems'))
SEEDS = {'perm': (PERM, 'check', []), 'enf_bad': (ENF_BAD, 'check', []), 'enf_ok': (ENF_OK, 'check', []),
         'dis': (DIS, 'check', []),
         'made': (MADE, 'prepare', ['%s: SELINUX=permissive' % SE_CONFIG, 'the files are labelled at the next start '
                                    'of the machine', 'zigmon\'s module (zigmon_server) installed',
                                    'restart the machine - it comes up permissive'])}
ASKED = []


def seed(name):
    data, act, said = SEEDS[name]
    d._mj_put('selinux:now', {'data': data, 'at': time.time(), 'done': 'x', 'error': '', 'action': act,
                              'said': said})
    d._mj_put('selinux:want', {})


seed('perm')
zigmon.SE_WORK.update(busy=False, seen=time.time(), tried='')
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
SEED_ASK = W / 'seed.ask'
js = r'''
const { chromium } = require('playwright');
const fs = require('fs');
const PORT = %(port)d, SH = %(shots)s, S = %(s)s, SOP = %(sop)s, SRO = %(sro)s, ASK = %(ask)s, OUT = %(out)s, RULE3 = %(rule3)s;
let N = 0;
const url = () => 'http://127.0.0.1:' + PORT + '/?b=' + (++N) + '#control/sec-selinux';
async function seedIt(name) {
  fs.writeFileSync(ASK, name);
  for (let i = 0; i < 100 && fs.existsSync(ASK); i++) await new Promise(r => setTimeout(r, 100));
}
async function card(p) {
  return await p.evaluate(() => {
    const c = document.getElementById('se-card');
    const q = s => c.querySelector(s), txt = s => (q(s) || {}).innerText || '';
    return {mode: txt('.se-mode'), verdict: txt('#se-verdict'), text: c.innerText,
            groups: Array.from(c.querySelectorAll('.sef-grp')).map(g => ({kind: g.dataset.kind,
              head: g.querySelector('.sef-gh').innerText, rows: g.querySelectorAll('.sef-row').length,
              boxes: g.querySelectorAll('.sef-row input[type=checkbox]').length,
              ticked: g.querySelectorAll('.sef-row input[type=checkbox]:checked').length,
              all: !!g.querySelector('.sef-gh input.sef-all'),
              fixes: Array.from(g.querySelectorAll('.sef-fix code')).map(x => x.innerText),
              whys: Array.from(g.querySelectorAll('.sef-why')).map(x => x.innerText + '|' + getComputedStyle(x).color)})),
            put: txt('#se-put'), putOff: !!(q('#se-put') || {}).disabled,
            local: Array.from(c.querySelectorAll('.sef-lrow')).map(r => r.innerText),
            steps: Array.from(c.querySelectorAll('.se-btns button')).map(b => ({t: b.innerText.trim(), off: b.disabled})),
            said: txt('#se-said'), buttons: c.querySelectorAll('button').length,
            node: !!document.getElementById('se-node'),
            wide: c.scrollWidth <= c.clientWidth + 1};
  });
}
async function waitDone(p, kind) {
  for (let i = 0; i < 120; i++) {
    const v = await p.evaluate(() => !document.getElementById('se-wait'));
    if (v && i > 1) break;
    await p.waitForTimeout(500);
  }
  await p.waitForTimeout(800);
}
let P = null;
(async () => {
  const b = await chromium.launch();
  const out = {};
  async function ctx(w, h, sess) {
    const c = await b.newContext({viewport: {width: w, height: h}, deviceScaleFactor: 1});
    await c.addCookies([{name: 'zigmon_session', value: sess, url: 'http://127.0.0.1:' + PORT + '/'}]);
    const p = await c.newPage();
    p.errors = [];
    p.on('pageerror', e => p.errors.push(String(e)));
    return p;
  }
  const p = await ctx(1920, 3200, S);
  P = p;
  async function at(name, shot) {
    await seedIt(name);
    await p.goto(url());
    await p.waitForSelector('#se-node', {timeout: 15000});
    await p.waitForTimeout(500);
    out[name] = await card(p);
    if (shot) await (await p.$('#se-card')).screenshot({path: SH + '/' + shot});
  }
  await at('perm', '01-findings-1920.png');
  const p2 = await ctx(1280, 3600, S);
  await p2.goto(url());
  await p2.waitForSelector('#se-node', {timeout: 15000});
  await p2.waitForTimeout(500);
  out.perm1280 = await card(p2);
  await (await p2.$('#se-card')).screenshot({path: SH + '/02-findings-1280.png'});
  /* one unticked, the confirm lists exactly what root will do */
  await p.click('.sef-row[data-id="' + RULE3 + '"] input[type=checkbox]');
  await p.waitForTimeout(300);
  out.unticked = await card(p);
  await p.click('#se-put');
  await p.waitForSelector('#zmodal:not([hidden])');
  out.confirm = await p.evaluate(() => ({text: document.getElementById('zmodal').innerText,
    items: Array.from(document.querySelectorAll('#se-conf li')).map(x => x.innerText)}));
  await (await p.$('#zmodal-box')).screenshot({path: SH + '/03-confirm.png'});
  await p.click('#zmodal .btn.primary');
  await p.waitForSelector('#se-wait', {timeout: 10000});
  await waitDone(p);
  out.after = await card(p);
  await (await p.$('#se-card')).screenshot({path: SH + '/04-after-put-in.png'});
  /* a rule taken away */
  await p.click('.sef-lrow .sef-drop');
  await p.waitForSelector('#zmodal:not([hidden])');
  out.dropConfirm = await p.evaluate(() => document.getElementById('zmodal').innerText);
  await p.click('#zmodal .btn.danger');
  await p.waitForSelector('#se-wait', {timeout: 10000});
  await waitDone(p);
  out.dropped = await card(p);
  await at('enf_ok', '05-enforcing-nothing-refused.png');
  await at('enf_bad', '06-enforcing-something-refused.png');
  await at('dis', '08-disabled.png');
  await at('made', '09-made-ready.png');
  /* a read-only account, an operator: the card's place, no buttons */
  await seedIt('perm');
  for (const [k, sess] of [['viewer', SRO], ['operator', SOP]]) {
    const o = await ctx(1280, 800, sess);
    await o.goto(url());
    await o.waitForTimeout(2500);
    out[k] = await o.evaluate(() => ({text: document.getElementById('se-host').innerText,
      node: !!document.getElementById('se-node'), put: !!document.getElementById('se-put'),
      boxes: document.querySelectorAll('#se-card input[type=checkbox]').length,
      buttons: Array.from(document.querySelectorAll('#se-card button')).map(b => b.innerText.trim())}));
    if (k === 'viewer') await (await o.$('#se-card')).screenshot({path: SH + '/07-read-only-account.png'});
  }
  /* a phone */
  const q = await ctx(390, 844, S);
  await q.goto(url());
  await q.waitForSelector('#se-node', {timeout: 15000});
  await q.waitForTimeout(500);
  out.phone = await q.evaluate(() => ({doc: document.documentElement.scrollWidth, win: window.innerWidth,
    card: document.getElementById('se-card').scrollWidth, cw: document.getElementById('se-card').clientWidth}));
  await (await q.$('#se-card')).screenshot({path: SH + '/10-phone.png'});
  out.errors = p.errors.concat(p2.errors, q.errors);
  fs.writeFileSync(OUT, JSON.stringify(out));
  await Promise.race([b.close(), new Promise(r => setTimeout(r, 5000))]);
  process.exit(0);
})().catch(async e => {
  let seen = '';
  try { seen = await P.evaluate(() => location.href + ' ' + document.body.innerText.slice(0, 600)); } catch (x) { seen = String(x); }
  console.log(JSON.stringify({error: String(e) + ' | page errors: ' + JSON.stringify(P && P.errors) + ' | ' + seen}));
  process.exit(0);
});
'''
(W / 'page.js').write_text(js % {'port': PHP_PORT, 'shots': json.dumps(SHOTS), 's': json.dumps(S),
                                 'sop': json.dumps(S_OP), 'sro': json.dumps(S_RO), 'ask': json.dumps(str(SEED_ASK)),
                                 'out': json.dumps(str(W / 'page.json')), 'rule3': json.dumps(IDS['rule3'])})
root_mods = sh(['npm', 'root', '-g']).stdout.strip()
node = subprocess.Popen(['node', str(W / 'page.js')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        env=dict(os.environ, NODE_PATH=root_mods), stdin=subprocess.DEVNULL)
PROCS.append(node)
end = time.time() + 600
while node.poll() is None and time.time() < end:
    if SEED_ASK.exists():
        seed(SEED_ASK.read_text().strip())
        SEED_ASK.unlink()
    w = d._mj('selinux:want') or {}
    if w.get('id') and w.get('id') not in [a.get('id') for a in ASKED]:
        ASKED.append(dict(w))            # what the page asked, as the daemon keeps it
    if zigmon.selinux_pending(w, d._mj('selinux:now') or {}) and not zigmon.SE_WORK['busy']:
        tick_wait()
    time.sleep(0.05)
if node.poll() is None:
    node.kill()
    o_out, o_err = node.communicate()
    check(False, 'the page did not finish in 600 s: %s' % (o_out + o_err)[-600:])
    finish()
o_out, o_err = node.communicate()
try:
    r = json.loads((W / 'page.json').read_text()) if (W / 'page.json').exists() else \
        json.loads(o_out.strip().splitlines()[-1])
except (ValueError, IndexError):
    r = {'error': (o_out + o_err)[-400:]}
if r.get('error') and ('Executable doesn' in r['error'] or 'Cannot find module' in r['error']):
    print('  SKIPPED the page (no browser here): %s' % r['error'][:200])
    finish()
check(not r.get('error'), 'the page: %s' % r.get('error'))
pm = r.get('perm') or {}
G = {g['kind']: g for g in pm.get('groups') or []}
check([g['kind'] for g in pm.get('groups') or []] == ['boolean', 'label', 'port', 'rule', 'notbutton', 'other'],
      'the groups, in order: %r' % [g['kind'] for g in pm.get('groups') or []])
for k, n in (('boolean', 1), ('label', 1), ('port', 1), ('rule', 3), ('notbutton', 9), ('other', 2)):
    g = G.get(k) or {}
    check(g.get('rows') == n and (' %d' % n in g.get('head', '') or '\n%d' % n in g.get('head', '')),
          'the group %s: %r' % (k, {x: g.get(x) for x in ('rows', 'head')}))
    fixable = k in ('boolean', 'label', 'port', 'rule')
    check(g.get('all') == fixable and g.get('boxes') == (n if fixable else 0) and g.get('ticked') == g.get('boxes'),
          'the group %s: select-all and ticked boxes: %r' % (k, g))
check((G.get('rule') or {}).get('fixes', [None])[0:1] == ['(allow unconfined_service_t chronyc_t (process2 (nnp_transition)))'],
      'the rule\'s preview: %r' % (G.get('rule') or {}).get('fixes'))
check((G.get('port') or {}).get('fixes') == ['semanage port -a -t http_port_t -p tcp 8445'], 'the port\'s preview')
check(all('rgb(248, 81, 73)' in x for x in (G.get('notbutton') or {}).get('whys', [])) and
      any('shadow_t is security-sensitive' in x for x in (G.get('notbutton') or {}).get('whys', [])),
      'not for a button is not red with why: %r' % (G.get('notbutton') or {}).get('whys'))
check(all('not zigmon' in x for x in (G.get('other') or {}).get('whys', [])), 'not zigmon\'s: %r' % G.get('other'))
check(pm.get('put') == 'Put in what is selected (6)' and not pm.get('putOff'), 'the button: %r' % pm.get('put'))
check(pm.get('mode') == 'PERMISSIVE' and 'Not ready for enforcing yet' in pm.get('verdict', '')
      and '6 thing(s) SELinux refused can be put right here' in pm.get('verdict', ''), 'the verdict: %r' % pm.get('verdict'))
st = {x['t']: x for x in pm.get('steps') or []}
check(st.get('Switch to enforcing', {}).get('off') is True and 'Put in what zigmon needs' in st,
      'enforcing is not locked while something is left: %r' % pm.get('steps'))
check(pm.get('wide') and (r.get('perm1280') or {}).get('wide'), 'the card scrolls sideways at 1920 or 1280')
check((r.get('unticked') or {}).get('put') == 'Put in what is selected (5)', 'unticking does not count: %r'
      % (r.get('unticked') or {}).get('put'))
cf = r.get('confirm') or {}
check(len(cf.get('items') or []) == 5 and 'Root does exactly this - nothing else' in cf.get('text', '')
      and any('restorecon -R -v %s' % CORE_JS in x for x in cf.get('items') or [])
      and any('setsebool -P httpd_can_network_connect 1' in x for x in cf.get('items') or [])
      and 'zigmon_local' in cf.get('text', ''), 'the confirm: %r' % cf)
fixes_asked = [a for a in ASKED if a.get('do') == 'fix']
check(fixes_asked and len(fixes_asked[0].get('ids') or []) == 5 and IDS['rule3'] not in fixes_asked[0]['ids']
      and set(fixes_asked[0]) == {'id', 'do', 'by', 'at', 'ids'}, 'what the page asked: %r' % fixes_asked)
af = r.get('after') or {}
AG = {g['kind']: g for g in af.get('groups') or []}
check((AG.get('fixed') or {}).get('rows') == 5 and 'Put right just now' in (AG.get('fixed') or {}).get('head', ''),
      'put right just now: %r' % [(g['kind'], g['rows']) for g in af.get('groups') or []])
check((AG.get('rule') or {}).get('rows') == 1 and af.get('put') == 'Put in what is selected (0)' and af.get('putOff'),
      'what is left to put in: %r' % af.get('put'))
check(len(af.get('local') or []) == 2 and all('Take it away' in x for x in af.get('local') or []),
      'the local rules after: %r' % af.get('local'))
check('zigmon_local) put into the policy' in af.get('said', ''), 'what root did is not said: %r' % af.get('said'))
check('(allow' in (r.get('dropConfirm') or '') and 'zigmon_local' in (r.get('dropConfirm') or ''),
      'the take-away confirm: %r' % r.get('dropConfirm'))
check(len((r.get('dropped') or {}).get('local') or []) == 1, 'a rule taken away on the card: %r'
      % (r.get('dropped') or {}).get('local'))
check(any(a.get('do') == 'rule_drop' and len(a.get('ids') or []) == 1 for a in ASKED), 'rule_drop was not asked')
eo = r.get('enf_ok') or {}
check(eo.get('mode') == 'ENFORCING' and eo.get('verdict', '').startswith('Enforcing - and everything zigmon needs is there')
      and [x['t'] for x in eo.get('steps') or []] == ['Back to permissive'] and len(eo.get('local') or []) == 1
      and 'Nothing refused since the machine started' in eo.get('text', ''), 'enforcing, nothing refused: %r' % eo)
eb = r.get('enf_bad') or {}
check(eb.get('mode') == 'ENFORCING' and eb.get('put') == 'Put in what is selected (5)' and not eb.get('putOff')
      and 'Enforcing - but something' in eb.get('verdict', ''), 'enforcing, something refused: %r'
      % {k: eb.get(k) for k in ('put', 'verdict')})
ds = r.get('dis') or {}
check(ds.get('mode') == 'DISABLED' and [x['t'] for x in ds.get('steps') or []] == ['Make it ready (permissive)']
      and not ds.get('groups'), 'disabled: %r' % ds.get('steps'))
md = r.get('made') or {}
check('Made ready - waiting for a restart' in md.get('text', '') and not md.get('steps'), 'made ready: %r' % md.get('text'))
for k in ('viewer', 'operator'):
    o = r.get(k) or {}
    check(not o.get('node') and not o.get('put') and not o.get('boxes') and 'administrator' in o.get('text', '')
          and all('Sign in' in x for x in o.get('buttons') or []), '%s sees buttons on the card: %r' % (k, o))
ph = r.get('phone') or {}
check(ph.get('doc', 9999) <= ph.get('win', 0) and ph.get('card', 9999) <= ph.get('cw', 0) + 1,
      'the card scrolls sideways at 390 px: %r' % ph)
check(not r.get('errors'), 'errors on the page: %r' % r.get('errors'))
print('  screenshots in %s' % SHOTS)
finish()
