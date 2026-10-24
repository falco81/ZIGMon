# tools

Standalone helpers that are not part of the running daemon.

## probe-front.py

Run it against the hostname your one-tap **front** server answers on, **from
outside your own network** — a phone on mobile data, a small VPS, a friend's
line. Run from inside and it tells you nothing: the whole question is what the
public sees, and inside you are not the public.

    python3 probe-front.py mqtt.falco81.net

It reads the server the way somebody with no source code reads one, and
reports what comes back:

- the TLS version and cipher, whether SSLv3/TLS 1.0/1.1 still answer, and
  whether the certificate verifies for that name and how long it has left;
- whether plain HTTP redirects to HTTPS or serves;
- a **blind path scan** — admin pages, `.git`, `.env`, keys, phpinfo, path
  traversal plain and encoded — and whether any of it answers with content;
- odd methods (TRACE, PUT, DELETE, CONNECT), an unknown Host that finds a
  default vhost, an X-Forwarded-Host reflection, echoed proxy headers;
- how `/tap` answers a GET, a burst of wrong secrets, and the address form,
  if it answers at all;
- the response headers a browser is told to obey.

Point it at an IP with `--host <name>` to check the certificate against the
name it is actually for:

    python3 probe-front.py 192.168.43.17 --host mqtt.falco81.net

It never guesses a real link's secret and never tries to; a front done right
gives an attacker nothing to guess with, and that is what it looks for.
Nothing it does changes anything on the server — it presses no real link and
blocks no address — so it is safe against a live one.

It exits `0` when nothing worrying was found and `1` when something was, so it
can sit in a weekly cron and mail you the day the answer changes:

    0 6 * * 1  you  python3 /opt/zigmon/tools/probe-front.py mqtt.falco81.net || true

`--insecure` keeps probing past a certificate that does not verify (it still
reports it), for a server whose cert is self-signed or not yet in place.

No dependencies beyond the Python standard library.


## ntfy-admin.py

Everything the ntfy command line can do, without having to remember any of it.

    sudo tools/ntfy-admin.py

Arrow keys move, Enter chooses, Esc goes back, q quits. Every screen shows
what is actually there rather than asking you to know it: the users and their
roles, what each may read and write, the tokens each holds and when each was
last used, what the server is set to, and the last of the log.

It can make a user, change its password or its role, give it access to a topic
or a pattern, take all its access away, make and take away tokens with a label
and a life, open or shut what anonymous callers may do, and send a test
message. It shells out to `ntfy` for all of it, so it can do nothing you could
not do by hand - and where ntfy wants to ask for a password itself, it is
handed the terminal to ask on. Nothing here ever holds a password.

Needs Python 3.7 and the ntfy binary. colorama is used if it is installed;
without it the same colours are written as plain ANSI.

## snort-debug.py

Why snort.org will not hand the Talos list to this machine. Run it on the
server from the folder the package was unpacked into, and send back what it
prints:

    sudo python3 tools/snort-debug.py            # two requests, no more
    sudo python3 tools/snort-debug.py --accept   # also press Accept, as zigmon does
    sudo python3 tools/snort-debug.py --ipv4     # leave by IPv4 only

It asks the way zigmon does and prints, at each step, the status, the headers
that say who answered and why (Cloudflare's ray, Retry-After, the kind of
block), the start of any page given instead of the list, the address it left
from, and what zigmon has remembered about the list. It never prints a
cookie's value, a token or a session - only names and lengths - waits four
seconds between requests, and stops at the first "too many requests", so
running it does not lengthen the wait. It only reads zigmon's database.

While snort.org has told this address to wait it does not ask at all (add
`--force` to ask anyway): snort.org counts five requests to the list a minute
from one address, and past that it answers "too many requests" to everything
for a day. If the lock-out keeps coming back while zigmon keeps to its four a
minute, something else behind the same public address is asking snort.org too.
