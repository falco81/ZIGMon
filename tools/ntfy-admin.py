#!/usr/bin/env python3
"""ntfy-admin - everything the ntfy command line can do, without having to
remember any of it.

Arrow keys move, Enter chooses, Esc goes back, q quits. Every screen shows
what is actually there rather than asking you to know it: the users and their
roles, what each may read and write, the tokens each one holds and when they
were last used, and what the server itself says.

It shells out to `ntfy` for everything, so it can only do what you could do by
hand - and where ntfy wants to ask for a password itself, it is handed the
terminal to ask on. Nothing here ever holds a password.

    sudo ./ntfy-admin.py

Needs nothing but Python 3.7 and the ntfy binary. colorama is used if it is
installed; without it the same colours are written as plain ANSI, which every
terminal worth the name understands.
"""

import os
import re
import shutil
import subprocess
import sys
import termios

NTFY = shutil.which('ntfy') or '/usr/bin/ntfy'

try:                                   # nice on Windows, irrelevant elsewhere
    import colorama
    colorama.just_fix_windows_console()
except Exception:
    pass

COLOUR = sys.stdout.isatty() and os.environ.get('NO_COLOR') is None


def _c(code, text):
    return '\033[%sm%s\033[0m' % (code, text) if COLOUR else text


def dim(t):    return _c('2', t)
def bold(t):   return _c('1', t)
def head(t):   return _c('1;36', t)
def ok(t):     return _c('32', t)
def warn(t):   return _c('33', t)
def bad(t):    return _c('31', t)
def pick(t):   return _c('7', t)       # the line the cursor is on


# ---- talking to ntfy ---------------------------------------------------------

def run(args, quiet=True):
    """Run an ntfy command and hand back (ok, output)."""
    try:
        done = subprocess.run([NTFY] + args, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return False, 'ntfy is not installed, or not where this expected it: %s' % NTFY
    except Exception as e:
        return False, str(e)
    out = (done.stdout or '') + (done.stderr or '')
    return done.returncode == 0, out.strip()


def run_attached(args):
    """Run a command that wants to ask something itself - a password, a yes.

    The terminal is handed over whole: ntfy prompts, the person answers, and
    nothing of it passes through here.
    """
    show_cursor()
    sys.stdout.write('\n' + dim('$ ntfy ' + ' '.join(args)) + '\n\n')
    sys.stdout.flush()
    try:
        done = subprocess.run([NTFY] + args)
        good = done.returncode == 0
    except Exception as e:
        sys.stdout.write(bad(str(e)) + '\n')
        good = False
    sys.stdout.write('\n' + dim('any key to carry on') + ' ')
    sys.stdout.flush()
    try:
        key()
    except KeyboardInterrupt:
        pass
    return good


# ---- reading what ntfy says --------------------------------------------------

USER_LINE = re.compile(r'^user\s+(\S+)\s*(?:\((?P<role>[^)]*)\))?\s*$')
GRANT_LINE = re.compile(r'^-\s+(?P<what>.+)$')
TOKEN_LINE = re.compile(r'^-\s+(?P<token>tk_\S+)\s*(?:\((?P<label>[^)]*)\))?\s*(?P<rest>.*)$')


def users():
    """[{name, role, grants: [...]}] as `ntfy access` lists them."""
    good, out = run(['access'])
    if not good:
        return [], out
    found, current = [], None
    for line in out.splitlines():
        line = line.rstrip()
        m = USER_LINE.match(line.strip())
        if m:
            role = (m.group('role') or '').strip()
            # "role: user, tier: none" on newer builds, "admin" on older
            role = role.replace('role:', '').split(',')[0].strip() or 'user'
            current = {'name': m.group(1), 'role': role, 'grants': []}
            found.append(current)
            continue
        m = GRANT_LINE.match(line.strip())
        if m and current is not None:
            current['grants'].append(m.group('what').strip())
    return found, ''


def tokens(user):
    """[{token, label, rest}] for one user."""
    good, out = run(['token', 'list', user])
    if not good:
        return [], out
    found = []
    for line in out.splitlines():
        m = TOKEN_LINE.match(line.strip())
        if m:
            found.append({'token': m.group('token'),
                          'label': (m.group('label') or '').strip(),
                          'rest': (m.group('rest') or '').strip(' ,')})
    return found, ''


def tiers():
    good, out = run(['tier', 'list'])
    if not good:
        return [], out
    return [l.strip() for l in out.splitlines() if l.strip()], ''


def service_state():
    """What systemd says, where there is a systemd."""
    try:
        done = subprocess.run(['systemctl', 'is-active', 'ntfy'],
                              capture_output=True, text=True, timeout=10)
        return (done.stdout or done.stderr or '').strip()
    except Exception:
        return 'unknown'


def config_lines():
    """The settings that decide what anybody can do, as the file has them."""
    want = ('base-url', 'listen-http', 'auth-file', 'auth-default-access', 'web-root',
            'enable-signup', 'enable-login', 'upstream-base-url', 'behind-proxy',
            'attachment-cache-dir', 'ban-file', 'visitor-message-daily-limit')
    found = {}
    try:
        with open('/etc/ntfy/server.yml') as fh:
            for line in fh:
                bare = line.strip()
                if not bare or bare.startswith('#') or ':' not in bare:
                    continue
                key, value = bare.split(':', 1)
                if key.strip() in want:
                    found[key.strip()] = value.strip().strip('"\'')
    except Exception as e:
        return [('the config could not be read', str(e))]
    return [(k, found.get(k, dim('not set'))) for k in want]


# ---- the screen --------------------------------------------------------------

def hide_cursor():
    if COLOUR:
        sys.stdout.write('\033[?25l')


def show_cursor():
    if COLOUR:
        sys.stdout.write('\033[?25h')


def clear():
    sys.stdout.write('\033[2J\033[H' if COLOUR else '\n' * 3)


class Raw(object):
    """The terminal, put into raw mode for as long as this is held.

    VMIN=1, VTIME=0: a read waits for at least one byte and then hands over
    everything that arrived with it. An arrow key is three bytes sent in one
    breath, so one read returns all three - no guessing with a timer, which
    over an SSH link from another country is guessing badly.
    """

    def __enter__(self):
        self.fd = sys.stdin.fileno()
        try:
            self.was = termios.tcgetattr(self.fd)
        except Exception:
            self.was = None
            return self
        mode = termios.tcgetattr(self.fd)
        mode[3] &= ~(termios.ECHO | termios.ICANON)      # no echo, no line at a time
        mode[6][termios.VMIN] = 1
        mode[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, mode)
        return self

    def __exit__(self, *_):
        if self.was is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.was)

    def read(self):
        return os.read(self.fd, 16)


def key(raw=None):
    """One keypress. Held open where a screen reads many in a row."""
    if raw is not None:
        return read_key_bytes(raw.read())
    with Raw() as one:
        return read_key_bytes(one.read())


ARROWS = {b'A': 'up', b'B': 'down', b'C': 'right', b'D': 'left',
          b'H': 'home', b'F': 'end', b'5~': 'up', b'6~': 'down',
          b'1~': 'home', b'4~': 'end', b'7~': 'home', b'8~': 'end'}


def read_key_bytes(chunk):
    """Name the key, given every byte that arrived together."""
    if not chunk:
        return 'esc'
    if chunk[:1] == b'\x1b':
        rest = chunk[1:]
        if rest[:1] in (b'[', b'O'):
            return ARROWS.get(rest[1:], 'other')
        return 'esc'                     # Esc alone: back, or cancel
    first = chunk[:1]
    if first in (b'\r', b'\n'):
        return 'enter'
    if first == b'\x03':
        raise KeyboardInterrupt
    if first in (b'\x7f', b'\x08'):
        return 'back'
    try:
        return chunk.decode('utf-8', 'replace')[0]
    except Exception:
        return 'other'


def frame(lines):
    """Paint a whole screen in one write.

    Drawn over what is there rather than wiped first: clearing and then
    writing means a moment with nothing on the screen, and over a slow link
    that moment is what flickers. Each row is written and then the rest of
    that row is erased, and the rest of the screen after the last row.
    """
    out = ['\033[H'] if COLOUR else ['\n']
    for line in lines:
        out.append(line + ('\033[K\r\n' if COLOUR else '\n'))
    if COLOUR:
        out.append('\033[J')
    sys.stdout.write(''.join(out))
    sys.stdout.flush()


def menu(title, rows, note='', where=0):
    """Draw a list and let somebody walk it.

    rows: [(label, value)] - a row whose value is None is a heading or a rule
    and is never landed on, so the cursor moves between the things that can
    actually be chosen rather than stopping on the lines between them.
    """
    if not rows:
        rows = [(dim('nothing here'), None)]
    live = [i for i, r in enumerate(rows) if r[1] is not None]
    if not live:
        live = [0]
    if where not in live:
        where = live[0]
    hide_cursor()
    clear()
    try:
        with Raw() as raw:
            while True:
                shown = [head(title)]
                if note:
                    for part in _wrapped(note, 76):
                        shown.append(dim(part))
                shown.append('')
                for i, (label, value) in enumerate(rows):
                    if i == where:
                        shown.append(pick('\u25b8 ' + label + ' '))
                    elif value is None:
                        shown.append('  ' + label)
                    else:
                        shown.append('  ' + label)
                shown.append('')
                shown.append(dim('\u2191\u2193 move \u00b7 Enter choose \u00b7 Esc back \u00b7 q quit'))
                frame(shown)
                k = key(raw)
                at = live.index(where) if where in live else 0
                if k == 'up':
                    where = live[(at - 1) % len(live)]
                elif k == 'down':
                    where = live[(at + 1) % len(live)]
                elif k == 'home':
                    where = live[0]
                elif k == 'end':
                    where = live[-1]
                elif k == 'enter':
                    return rows[where][1]
                elif k == 'esc':
                    return None
                elif k in ('q', 'Q'):
                    show_cursor()
                    clear()
                    sys.exit(0)
    finally:
        show_cursor()


def _wrapped(text, width):
    words, line, out = str(text).split(), '', []
    for word in words:
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = (line + ' ' + word).strip()
    if line:
        out.append(line)
    return out or ['']


def ask(question, hint='', value=''):
    """A line of typing, with Esc to give up on it.

    The line reader that comes with Python cannot do that: it has no idea
    what Esc is, so a question once
    asked had to be answered. This reads the keys itself - letters, Backspace,
    Enter, Esc - and hands back None when somebody changes their mind.
    """
    hide_cursor()
    clear()
    try:
        with Raw() as raw:
            while True:
                shown = [head(question)]
                if hint:
                    for part in _wrapped(hint, 76):
                        shown.append(dim(part))
                shown.append('')
                shown.append('  ' + bold(value) + pick(' '))
                shown.append('')
                shown.append(dim('Enter to accept \u00b7 Esc to give up \u00b7 Backspace to rub out'))
                frame(shown)
                k = key(raw)
                if k == 'enter':
                    return value.strip() or None
                if k == 'esc':
                    return None
                if k == 'back':
                    value = value[:-1]
                elif len(k) == 1 and k.isprintable():
                    value += k
    finally:
        show_cursor()


def tell(message, good=True):
    hide_cursor()
    clear()
    try:
        frame([ok(message) if good else bad(message), '', dim('any key to carry on')])
        key()
    finally:
        show_cursor()


def pager(title, text):
    """Show something long, and stay there until a key is pressed.

    The log used to flash past: the command wrote to the terminal and the next
    screen wiped it before anybody could read a word.
    """
    lines = str(text).rstrip().splitlines() or ['(nothing)']
    rows = max(10, (shutil.get_terminal_size((80, 24)).lines or 24) - 6)
    at = 0
    hide_cursor()
    clear()
    try:
        with Raw() as raw:
            while True:
                shown = [head(title), dim('%d line(s), showing %d\u2013%d'
                                         % (len(lines), at + 1, min(len(lines), at + rows))), '']
                shown += [l[:220] for l in lines[at:at + rows]]
                shown.append('')
                shown.append(dim('\u2191\u2193 scroll \u00b7 Esc or q back'))
                frame(shown)
                k = key(raw)
                if k in ('esc', 'q', 'Q', 'enter'):
                    return
                if k == 'down':
                    at = min(max(0, len(lines) - rows), at + 1)
                elif k == 'up':
                    at = max(0, at - 1)
                elif k == 'end':
                    at = max(0, len(lines) - rows)
                elif k == 'home':
                    at = 0
    finally:
        show_cursor()


def confirm(question):
    return menu(question, [('No, leave it as it is', False), ('Yes, do it', True)],
                'Nothing has happened yet.') is True


# ---- what each screen does ---------------------------------------------------

def screen_access_add(name):
    topic = ask('Which topic, or a pattern with * in it',
                'e.g. zigmon-house, or zigmon-* for every topic beginning that way')
    if not topic:
        return
    permission = menu('What may %s do with %s' % (name, topic), [
        ('read and write', 'rw'),
        ('read only  \u2014 subscribe, never publish', 'ro'),
        ('write only \u2014 publish, never subscribe', 'wo'),
        ('nothing    \u2014 deny it outright', 'deny'),
    ])
    if not permission:
        return
    good, out = run(['access', name, topic, permission])
    tell(out or ('%s may now %s %s' % (name, permission, topic)), good)


def screen_user(name):
    while True:
        people, err = users()
        who = next((u for u in people if u['name'] == name), None)
        if who is None:
            return
        held, _ = tokens(name)
        lines = []
        lines.append(('Role: %s' % bold(who['role']), 'role'))
        for grant in who['grants']:
            lines.append((dim('  ' + grant), None))
        lines.append((dim('\u2500' * 40), None))
        lines.append(('Give it access to a topic', 'access'))
        lines.append(('Take all its access away', 'reset'))
        lines.append((dim('\u2500' * 40), None))
        lines.append(('Tokens (%d)' % len(held), 'tokens'))
        lines.append(('Change its password', 'pass'))
        lines.append(('Make it %s' % ('a plain user' if who['role'] == 'admin' else 'an admin'), 'role'))
        lines.append(('Delete this user', 'delete'))
        what = menu('User: %s' % name, lines,
                    'An admin may read and write every topic, whatever the list says.')
        if what is None:
            return
        if what == 'access':
            screen_access_add(name)
        elif what == 'reset':
            if confirm('Take away every access %s has?' % name):
                good, out = run(['access', '--reset', name])
                tell(out or 'done', good)
        elif what == 'tokens':
            screen_tokens(name)
        elif what == 'pass':
            run_attached(['user', 'change-pass', name])
        elif what == 'role':
            to = 'user' if who['role'] == 'admin' else 'admin'
            if confirm('Make %s %s?' % (name, 'an admin' if to == 'admin' else 'a plain user')):
                good, out = run(['user', 'change-role', name, to])
                tell(out or 'done', good)
        elif what == 'delete':
            if confirm('Delete the user %s? Its tokens go with it.' % name):
                good, out = run(['user', 'del', name])
                tell(out or 'deleted', good)
                return


def screen_tokens(name):
    while True:
        held, err = tokens(name)
        lines = []
        for t in held:
            label = t['label'] or dim('no label')
            lines.append(('%s  %s  %s' % (bold(t['token'][:16] + '\u2026'), label, dim(t['rest'][:46])),
                          ('drop', t['token'])))
        if not held:
            lines.append((dim(err or 'no tokens yet'), None))
        lines.append((dim('\u2500' * 40), None))
        lines.append(('Make a new token', ('add', None)))
        what = menu('Tokens: %s' % name, lines,
                    'Choosing a token offers to take it away. A token is not a password: '
                    'it can be taken away on its own.')
        if what is None:
            return
        verb, which = what
        if verb == 'add':
            label = ask('A label, so you know later what holds it', 'e.g. my phone, the house')
            expires = menu('How long should it last', [
                ('for ever', ''), ('30 days', '30d'), ('90 days', '90d'), ('a year', '365d')])
            if expires is None:
                continue
            args = ['token', 'add']
            if expires:
                args.append('--expires=' + expires)
            if label:
                args += ['--label', label]
            args.append(name)
            good, out = run(args)
            tell(out or 'made', good)
        elif verb == 'drop' and which:
            if confirm('Take away the token %s\u2026?' % which[:16]):
                good, out = run(['token', 'remove', name, which])
                tell(out or 'taken away', good)


def screen_users():
    while True:
        people, err = users()
        if err:
            tell(err, False)
            return
        lines = []
        for u in people:
            mark = warn(' admin') if u['role'] == 'admin' else ''
            held, _ = tokens(u['name'])
            lines.append(('%-18s %s%s  %s' % (bold(u['name']), dim('%d grant(s)' % len(u['grants'])),
                                              mark, dim('%d token(s)' % len(held))), u['name']))
        lines.append((dim('\u2500' * 40), None))
        lines.append(('Add a user', '\0add'))
        name = menu('Users', lines, 'Choose one to see and change what it may do.')
        if name is None:
            return
        if name == '\0add':
            new = ask('A name for the new user', 'letters and numbers; it will ask for a password next')
            if not new:
                continue
            role = menu('What kind of user', [
                ('a plain user \u2014 give it access topic by topic', 'user'),
                ('an admin \u2014 every topic, always', 'admin')])
            if role is None:
                continue
            args = ['user', 'add']
            if role == 'admin':
                args.append('--role=admin')
            args.append(new)
            run_attached(args)          # ntfy asks for the password itself
        elif name:
            screen_user(name)


def screen_everyone():
    """What somebody with no name at all may do."""
    while True:
        people, _ = users()
        who = next((u for u in people if u['name'] in ('*', 'everyone')), None)
        lines = [(dim('  ' + g), None) for g in (who or {}).get('grants', [])] or \
                [(dim('  nothing at all, which is the shut door'), None)]
        lines.append((dim('\u2500' * 40), None))
        lines.append(('Let anonymous callers at a topic', 'add'))
        lines.append(('Take all anonymous access away', 'reset'))
        what = menu('Anybody, with no name given', lines,
                    'With auth-default-access set to deny-all, this is empty and every '
                    'request must say who it is. Anything here is a hole in that.')
        if what is None:
            return
        if what == 'add':
            screen_access_add('everyone')
        elif what == 'reset':
            if confirm('Take away every anonymous access?'):
                good, out = run(['access', '--reset', 'everyone'])
                tell(out or 'done', good)


def screen_server():
    state = service_state()
    lines = [('%-24s %s' % ('the service', ok(state) if state == 'active' else bad(state)), None)]
    for name, value in config_lines():
        lines.append(('%-24s %s' % (name, value), None))
    lines.append((dim('\u2500' * 46), None))
    lines.append(('Send a test message', 'test'))
    lines.append(('Show the last of the log', 'log'))
    lines.append(('Everything ntfy is set to', 'all'))
    what = menu('The server', lines, 'Read from /etc/ntfy/server.yml and systemd.')
    if what == 'all':
        try:
            text = open('/etc/ntfy/server.yml').read()
        except Exception as e:
            text = str(e)
        pager('/etc/ntfy/server.yml', text)
    if what == 'test':
        base = dict(config_lines()).get('base-url') or ''
        topic = ask('Which topic to publish to', 'it will ask nothing else; use a token below if needed')
        if topic:
            good, out = run(['publish', '%s/%s' % (base.rstrip('/'), topic), 'A test from ntfy-admin'])
            tell(out or 'sent', good)
    elif what == 'log':
        screen_log()


def screen_log():
    try:
        done = subprocess.run(['journalctl', '-u', 'ntfy', '-n', '200', '--no-pager'],
                              capture_output=True, text=True, timeout=20)
        text = (done.stdout or '') + (done.stderr or '')
    except Exception as e:
        text = str(e)
    pager('The last of the ntfy log', text)


def main():
    if not os.path.exists(NTFY):
        print(bad('ntfy is not installed, or not at %s' % NTFY))
        return 2
    good, version = run(['--version'])
    while True:
        what = menu('ntfy-admin', [
            ('Users and what they may do', 'users'),
            ('Anybody, with no name given', 'everyone'),
            ('The server, and what it is set to', 'server'),
            ('The last of the log', 'log'),
            (dim('\u2500' * 40), None),
            ('Quit', 'quit'),
        ], (version.splitlines()[-1] if good and version else 'ntfy') + '  \u00b7  '
           + ('the service is ' + service_state()))
        if what in (None, 'quit'):
            clear()
            return 0
        if what == 'users':
            screen_users()
        elif what == 'everyone':
            screen_everyone()
        elif what == 'server':
            screen_server()
        elif what == 'log':
            screen_log()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        show_cursor()
        print()
        sys.exit(130)
    finally:
        show_cursor()
