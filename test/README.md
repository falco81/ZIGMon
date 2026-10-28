# Development checks

Nothing here ships to the server.

* `replay.py` — feeds the daemon real Zigbee2MQTT and Shelly messages without
  a broker, then exercises every API endpoint including wrong PIN and token.
  Run with a scratch configuration:

      cat > /tmp/zt.json <<'JSON'
      {"db_file": "/tmp/zt.db", "token_file": "/tmp/zt-token", "log_file": "/tmp/zt.log",
       "api_port": 19849, "pin": "1234", "sample_interval": 0, "log_to_journal": false}
      JSON
      ZIGMON_CONFIG=/tmp/zt.json PYTHONPATH=. python3 test/replay.py

* `render.js` — drives the dashboard in jsdom against a running daemon and
  `php -S 127.0.0.1:8099 -t web`, walks every tab, renders the charts, goes
  through the PIN dialogue and reports any JavaScript error.

      npm install jsdom && node test/render.js

* `mockplug.py PORT [PASSWORD]` — a Shelly Plug M Gen3 lookalike: `/rpc` with
  SHA-256 digest authentication, a switch, counters and resets. Point a plug
  entry at `127.0.0.1:PORT` to exercise polling, switching, resets and
  button bindings without hardware.

## endpoints.py

`python3 test/endpoints.py` — every `/api/...` path the web relay forwards
must be one the daemon serves, and in the branch that matches the method.
Needs nothing running; it reads the two files. It exists because *Put back*
once shipped answering "no such endpoint": the handler had been written into
the read branch while the page posted to it.

## rbackup.py

`python3 test/rbackup.py` (as root, like `admin.py`) — the backups to other
machines, the whole way round. A daemon on a port of its own, root's helper
run straight away (`ZIGMON_ROOT_RUN`) over a folder that stands in for the
machine, and a small FTP server started in the same process. It checks that
a destination is refused when a tool on the way would read it as more than a
value (`;`, `"`, a leading `-`, `..`, a line break), that only this
machine's old backups are taken away (never the newest, their `.sha256` and
`-RESTORE.txt` with them, nothing of another machine's or put there by hand),
the schedule with a clock of its own (once a day, also across a restart),
that nothing goes out without the password, that no password, key or
passphrase is in `GET /api/rbackup`, the log or the events, a whole run (the
copy that arrives opens with `openssl` and the password), Backups there,
Download, Delete, and Put this back through root's `full_put`. SFTP is tried
against an `sshd -D` started on a port of its own only where this machine
has one; otherwise it says it skipped it.

## mocksms.py

`python3 test/mocksms.py 18110 [user] [password]` — a Teltonika-lookalike SMS
gateway: `/cgi-bin/sms_send`, `/cgi-bin/sms_list`, `/cgi-bin/sms_delete` with
the same query parameters and the same plain-text listing. `GET /` returns
what it was asked to send, `POST /inbox {"from":…,"text":…}` puts a message
in for the daemon to find, `POST /reset` empties both. Enough to test alerts
going out and commands coming in without a SIM card.

## facts.py

`python3 test/facts.py` — every `{fact}` the daemon fills must appear in the
page's picker, and every one the picker offers must be filled. The two drifted
apart once: the picker advertised `{sunrise}`, `{sunset}` and `{daylight}`
while the daemon filled none of them, so a message quoting them arrived with
the words simply missing.

## objects.py

`PYTHONPATH=. python3 test/objects.py` — everything as an object: every kind
of thing in the house has an address `type:id` that stays when it is renamed,
properties, functions and procedures; `{Name.member}` reads them; a name two
kinds share goes to the one it always meant (a room over a link called the
same); and no secret, token or password is in anything the object view sends,
while a phone number needs the PIN. An address on the blocked list and a
Wi-Fi client are objects by their address (kept out, let back in, given to a
person), and a scene's steps are read and set as one line that loses nothing.

## realtime.py

`python3 test/realtime.py` - a sensor, a button and the light that follows,
with a stopwatch. A fake Shelly on a port of its own, the rules and the
bindings on their own threads, the command over HTTP: motion to the light,
a press to the relay, and a press while a two-second poll is already on the
wire (which used to wait the poll out). It also checks what the pages are
woken for - a light's state, a PIR, a door, a leak at once; a temperature, a
humidity, a link quality and a battery together.

## lags.py

`PYTHONPATH=. python3 test/lags.py` - what stood in front of a light without
being on its way (5.16): the database held by somebody else while a group of
sensors moves, a sequence steps or a click comes through the door; a box that
never answers over MQTT; a reading asked for before a switch and written down
after it; "too many requests" to a reading; the bridge's big answers on the
broker's thread; the half-minute chores on the quarter-second beat; a rule
wanting somebody home asking the Wi-Fi again; six tabs each building their own
status. Every check here failed on 5.15.0.

## hunt.py

`PYTHONPATH=. python3 test/hunt.py` - the bugs, holes and delays found by going
over the whole of 5.16.0 again (5.17): phone numbers in the status and the
object list, a token remade by every save of the people, the address road of a
link past the second factor, a pressed link waiting 350 ms, a proxy log line
holding its reader for seconds, the PIN compared with `==`, a number from
another country taken for the owner's, an "away" rule deaf after a homecoming,
"on for a while" pressed twice, "for N s" counted from outside its hours, a
block missed at the door, quiet hours and schedules on the nights the clocks
change, alerts from several threads, any "429" taken for "too many requests",
a restore undone by a reader, a new device's first report, on and off sent
together arriving the wrong way round, a rule's wait ending on the next beat,
and a scene's sockets shown only after the last one. Run in Prague time.
Every check here fails on 5.16.0.

## edge.py

`python3 test/edge.py` - the edge itself, by sending it requests: the shipped
nginx file in a real nginx, a real php-fpm behind it and a fake daemon that
writes down what reached it. `/tap` and the SMS road cannot be turned into any
other API by what is on the end of the address; a POST from another site is
refused; a long X-Forwarded-For keeps the address the server in front wrote;
the unlock token travels in a header, for a poll and for a download, and is in
no log. Needs nginx and php-fpm installed; `EDGE_KEEP=1` keeps the scratch
folder. Every check here fails on 5.16.0.

## bugs.py

`PYTHONPATH=. python3 test/bugs.py` — the faults a read through the whole
application found in 4.94, each proved on its own: targets written as text,
presence triggers, lists switched off, the open door and the flat battery,
per-caller PIN lockout, sequences pressed twice, the texts counted today,
a Shelly's online word, restoring the oldest backup, and over HTTP the
switched-off view, keys with no PIN, a device's detail, a bad tap and the
mesh scan.

## nginx.py

`python3 test/nginx.py` — the shipped nginx file, read for the things nginx
itself would refuse: an unquoted brace in a location pattern, a rewrite using
`$1` while capturing nothing, a `gzip_types` naming `text/html`, unbalanced
braces, and anything inside an `if` block that nginx does not allow there. A
fault in this file stops the web server and takes every other site on the
machine with it, which is worse than any fault inside the dashboard — and
`default_type` inside an `if` did exactly that once.

## taps.py

`ZIGMON_CONFIG=… PYTHONPATH=. python3 test/taps.py` — the one-tap links: all
three positions of the switch, both roads, and the code. It checks the TOTP
maths against the four test vectors in RFC 6238, that a code is taken for its
own window and one step either side and never after, that the second press
inside one code works, that a road which is shut answers word for word what an
unknown link answers, that no code secret leaves with the status, and that
asking for a code with no phone to show one is refused with neither setting
left half-changed.

## completer.js

`node test/completer.js` — the `{…}` completer, lifted out of `index.php` and
run against a made-up dashboard; it needs neither php nor a running daemon.
For each of eleven things typed it checks what is offered and where what is
chosen lands. `{PIR-Chodba.model.nl}` could not be written before it existed:
a dot after a device's reading offered nothing, and what was picked was put
back over everything after the first dot, so a turn chosen there turned
`{Name.model.nl}` into `{Name.nl}`.

## listeners.py

`python3 test/listeners.py` — a listener put on the whole page from inside a
function runs as often as that function is called, so it has to come off
again. `showDialog` added an Escape handler every time it opened and took it
off only when the dialog was closed with Escape; closed with *OK* or by
clicking outside, it stayed, and the next dialog added another. An unnamed
function cannot be taken off at all and is refused outright.

## columns.py

`python3 test/columns.py` — reads the page's own stylesheet. Every table on
Control is a grid per row, so a column left to size itself by what it holds
is answered separately in each of them: the gateways' header, whose last cell
is empty, gave that width to the five columns above the boxes and stood every
name to the right of what it named — a hundred and fifty pixels of it by
*Target*. A content-sized column is allowed only through a variable measured
off the page and handed to the header and all the rows alike, and the test
insists something really sets it. It also counts the header's cells against
the row's columns.

## version.py

`python3 test/version.py` — zigmon.py, install.sh and README.md must state
the same version. They drifted apart once: a release script replaced a string
that had moved, said nothing about it, and several releases went out carrying
an old number inside a differently named file.

`mocksms.py` also speaks RutOS 7's own API — `/api/login`, `/api/modems/status`,
`/api/modems/signal/status`, `/api/messages/status`,
`/api/messages/actions/send` — with the same rules the device enforces: a
Bearer token that expires, a required `modem` field, and a number that must
carry its country code behind a `+`. That is what a TRB140 offers out of the
box, so it is what the tests use.

`zigmon --check-sms` walks the whole road to the gateway — the settings, the
device, the SIM, the signal, who would be told, who may command, what a text
may do, and whether anything is stuck — and ends with a list of what to do
about whatever failed.

## inputs.py

`python3 test/inputs.py` — every setting the page draws must be the kind of
box the daemon says it is. The page used to keep its own idea of which
settings were yes-or-no questions and fell behind, so two were drawn as number
boxes asking for a 1 or a 0.

## tables.py

The tables the daemon keeps by hand — KEY_INFO, the weather words, the
notification presets — must not say the same thing twice: Python keeps the
last of two entries with the same key, so an earlier one is dead text that
can be edited to no effect. Three had crept into KEY_INFO before this
existed. It also refuses a class with the same method defined twice.

## switches.py

Every switch tried both ways, watching what the daemon *does* rather than
what was stored. The debug switch was saved, shown on the page and ignored
for its whole life because nothing ever checked that turning it on changed
anything; this is that check.

## roundtrip.py

Writes something distinctive into a field of every editor, saves it through
the same path the page uses, and asks for it back. A control can be wired to
a record and the record can be saved while the field is quietly dropped on
the way, by a validator that does not know it or a reader that never looks.
It also proves a scene can be called Ložnice večer.

## nginx.py

The shipped nginx file, read for what nginx itself would refuse: a brace in an
unquoted location pattern (which nginx reads as the end of the block, cutting
the expression in half), text/html named in gzip_types, unbalanced braces, a
pattern that is not a regular expression. A mistake here stops the web server
rather than the dashboard, which takes everything else on that machine with
it.

## root.py

`python3 test/root.py` - what the dashboard may ask root for (5.18):
`deploy/zigmon_root.py` run the way systemd runs it, against a folder that
stands in for the machine. The certificate put in with its chain, its key
checked against it, the files kept with their owner and mode, a real
`nginx -t` asked and everything put back when it says no; the three allow
lists of the shipped nginx file; the firewall with iptables for real in a
network namespace of its own (`unshare -n`, skipped without it) and firewalld
through a stand-in; a backup of the whole installation made, sealed, refused
when changed, taken in from an upload with a password, and put back - from a
file made elsewhere only the parts that cannot make anybody root. Needs nginx
and openssl.

## upgrade.py

`python3 test/upgrade.py` - a new version put in from the dashboard:
`deploy/zigmon_upgrade.py` with a release key of the test's own. Signed
packages taken; changed, unsigned, foreign-signed, padded, linked,
traversing and older ones refused; install.sh run and the new version asked
whether it answers; the program as it was put back by itself when it does
not, or when install.sh fails; nothing changed at all when the backup before
it fails.

## online.py

`python3 test/online.py` - a new version from the web (5.20), with nothing
leaving the machine: `_online_get` is replaced by fixtures, and urlopen
itself where its own checks are the point. A GitHub folder through the
contents API and through its page when the API refuses, an nginx folder
listing, a JSON list, one package's address and a GitHub `/blob/` page read
as the raw file - newest first, plain http links never offered; http
refused, and a redirect to http; an answer too big refused, a package
streamed to disk. A newer version said once; a package signed by the test's
own key fetched into exactly the state of one sent by hand (the same
package.json, the same `zigmon_upgrade.py --inspect`), and unsigned, older,
equal or mislabelled ones refused with nothing left behind; the API an
administrator's only and refused during an upgrade; the daily look switched
off, once a day, and again when the address changed; `upgrade_url` https
only, with no password in it.

## admin.py

`python3 test/admin.py` - the same, the whole way through the API with its
PIN: every road behind it, reads too; access lists and firewall rules saved
and refused when they would shut out the caller; certificates as PEM, PFX,
a request made here, self-signed; drift put in again once and not after a
refusal; a whole backup made, downloaded with a password and gone after it,
sent back in pieces, put back; a signed package sent in pieces and put in.

## accounts.py

`python3 test/accounts.py` - signing in to the dashboard (5.19): the first
administrator and its password in a file only root reads, to be changed
first; a wrong password, a name nobody has and an account switched off all
refused alike, five from one address and it waits; read only, operator and
administrator each kept to their own (and the old PIN opening nothing); a new
password ending every other sign-in; the last administrator kept; a sign-in
surviving a restart and ending when unused; the root command line let in by
its own key and not by the API token alone; the relay's HttpOnly,
SameSite=Strict cookie, the token never handed to the page, a session sent
by the page itself ignored, and only a sign-in page when the house is not
public; a database put back - by the daemon or by root - keeping the
accounts.

## review.py

`python3 test/review.py` — the faults the 5.20 read through the whole
application found, each proved on its own: a backlog that stopped the rules
which must hold for a while, a PIN account made with the PIN "None", the
blocked list and the alert numbers told to a visitor through the House and
Blocking objects and the message preview, money and lengths of time misread,
and the page's own (a request with `&t=` skipping the check for another site,
a room's name put into a dialogue as HTML, a countdown by the browser's
clock). Fails on 5.19.2 in 33 places. Root's half of it - an uploaded backup
choosing where root writes, and with which mode - is in `test/root.py`.

## console.py

`python3 test/console.py` - the console (5.21) and its start at root's login.
The login hook from `deploy/zz-zigmon-console.sh`, sourced by a real
interactive bash on a pseudo-terminal with its two paths pointed at a stub
that writes down that it was started (and a stub `id` on PATH saying who is
signing in): started for root with the flag on, and not with the flag
missing, a link or "off", a command run over SSH, ZIGMON_NO_CONSOLE, a shell
opened from the console, a user who is not root, or no terminal.
`--console-at-login` refused to anybody but root (run as nobody where it can
be), a link or a pipe planted where the flag goes replaced rather than
followed or waited on; `--console` without a terminal refused. The keys a
terminal sends as raw escape sequences, the live view's grep taking a broken
regular expression as plain words, and the two-digit jump in a menu of
eleven, driven directly; then the console itself on a pseudo-terminal: its
menu, a submenu and Esc back, `!` opening a shell told ZIGMON_CONSOLE=1, the
live log filtered as it is typed, and q closing it. Touches nothing on the
machine. Fails on 5.20.0.
