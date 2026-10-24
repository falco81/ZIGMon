# Suricata on the server that faces the internet (AlmaLinux 9)

It watches the packets arriving at that machine, which the house never sees:
a scan that never becomes a request, a TLS handshake with something wrong in
it, an exploit it knows by name. It does the recognising. The keeping out is
still done by zigmon, by the same weighing and the same ladder as everything
else, so nothing is ever refused for a reason nobody can read afterwards.

Everything below is run as root on the proxy.

---

## 1. Install it

    dnf install -y epel-release
    dnf install -y suricata

EPEL 9 does carry it - 7.0.16 at the time of writing. **Do not add
`suricata-update` to that line**: it is not a package, it is a Python tool
that comes inside the `suricata` one, and dnf abandons the whole transaction
over one argument it cannot match. That single wrong word is what made the
first attempt say "Unable to find a match" and install nothing at all.

    suricata --build-info | head -3        # This is Suricata version 7.0.16 RELEASE
    suricata-update --version              # suricata-update version 1.3.7

## 2. Tell it which card to watch, and what your own addresses are

    ip -brief addr

On your machine that is `ens192`, holding 192.168.43.17 and
2a02:7a00:e:4::17. In `/etc/suricata/suricata.yaml`:

    af-packet:
      - interface: ens192
        cluster-id: 99
        cluster-type: cluster_flow
        defrag: yes
        use-mmap: yes
        tpacket-v3: yes

    vars:
      address-groups:
        HOME_NET: "[192.168.43.17/32,2a02:7a00:e:4::17/128]"
        EXTERNAL_NET: "!$HOME_NET"

HOME_NET matters more than it looks. Set it to this machine and nothing else:
everything Suricata calls an attack is then something arriving *at* you, and
alerts about what you send out stay out of the counting. zigmon ignores alerts
whose source is one of the house's own addresses anyway, but it is better not
to write them at all.

**Your v4 address is private**, which tells you something about what Suricata
will see there: the internet reaches that machine through something else, so
on the v4 side the source address of everything arriving is whatever that
something puts there. If that is a straight port forward, you see the real
caller and all is well. If it is a proxy that terminates the connection, you
see the proxy, and Suricata will keep saying one address is attacking you -
which zigmon would then keep out, and with it everybody behind it. Check
before you switch the weighing on: `zigmon --proxy --test` reads the end of
eve.json and shows you the addresses it found. If they are all the same one,
leave HOME_NET as it is and set *Read what Suricata saw* to off on the v4
side of things - the v6 side, where the address is real, is the one worth
having.

## 3. Make it write eve.json, and only what is worth reading

Still in `suricata.yaml`, under `outputs:`, the `eve-log` section. The types
you want are `alert` and nothing else - `flow`, `dns`, `tls` and `http` are
interesting for an afternoon and then they are a gigabyte a day:

    outputs:
      - eve-log:
          enabled: yes
          filetype: regular
          filename: /var/log/suricata/eve.json
          types:
            - alert:
                payload: no          # the packet itself is not written down
                payload-printable: no
                http: yes            # the request line, which is worth having
                metadata: yes

`payload: no` is deliberate. The payload is whatever somebody sent, in full,
and this file is read over SSH and kept at the house.

## 4. Fetch the rules

    /sbin/suricata-update update-sources
    /sbin/suricata-update

(It came with the `suricata` package - see step 1. On AlmaLinux 9 it is in
`/sbin`, which is not on root's PATH in a cron job, so the cron line below
names it in full.) That takes the
Emerging Threats Open ruleset - the same people whose address
lists zigmon already reads - and writes `/var/lib/suricata/rules/suricata.rules`.
About forty thousand rules. Do it again weekly:

Nothing does this for you - the EPEL package brings no timer, and `dnf update`
only ever touches Suricata itself, never the rules. On AlmaLinux 9 the tool
lives in `/sbin`, so:

    cat > /etc/cron.d/suricata-update <<'EOF'
    15 4 * * 1 root /sbin/suricata-update --quiet && /bin/systemctl reload suricata
    EOF

`reload` rather than `restart`, so it picks the new rules up without a gap in
the watching. Whether it held: `ls -l /var/lib/suricata/rules/suricata.rules`
on a Monday afternoon.

## 4b. Two things the package does that the config cannot undo

**The unit names the interface on the command line**, and that beats anything
in suricata.yaml. On RHEL and its family it comes from
`/etc/sysconfig/suricata`:

    OPTIONS="-i eth0 --user suricata"

Change `eth0` to your card. `systemctl status suricata` shows the line it
actually ran, which is where to check:

    /sbin/suricata -c /etc/suricata/suricata.yaml --pidfile ... -i ens192 --user suricata

**And it runs as the suricata user while the log directory belongs to root.**
Running `suricata -T` as root first makes it worse, because that creates
`/var/log/suricata/*.log` owned by root and then the service cannot open its
own files:

    E: logopenfile: Error opening file: "/var/log/suricata/eve.json": Permission denied
    W: runmodes: output module "eve-log": setup failed

It says this and **carries on running with no output at all** - active, green,
and writing nothing, which is a worse failure than stopping. Fix it once:

    systemctl stop suricata
    chown -R suricata:suricata /var/log/suricata
    systemctl start suricata
    systemctl status suricata --no-pager | tail -5

There should be no "setup failed" in what it prints.

## 5. Check it before starting it

    suricata -T -c /etc/suricata/suricata.yaml -v

It will say how many rules it loaded and refuse to start on anything it cannot
parse. Then:

    systemctl enable --now suricata
    systemctl status suricata --no-pager
    tail -f /var/log/suricata/eve.json

If nothing appears at all after a few minutes, it is watching the wrong
interface. If the file fills up in seconds, `types:` still has more than
`alert` in it.

## 6. Let the house read it

zigmon reads it the same way it reads the nginx logs - over SSH, from where it
stopped last time - so the user it logs in as has to be able to read the file:

    setfacl -m u:zigmon:rx /var/log/suricata
    setfacl -d -m u:zigmon:r /var/log/suricata
    setfacl -m u:zigmon:r  /var/log/suricata/eve.json

**The second line is the one that matters**, and it is easy to leave out. An
ACL put on the file alone lasts until the next rotation: logrotate renames the
file - the rename carries the ACL with it, so the rotated copy is still
readable - and then Suricata creates a brand new eve.json on HUP, with no ACL
on it at all. The reading would work for a day and then stop, quietly, at four
in the morning. `setfacl -d` puts a default on the directory, so everything
made in it afterwards is readable too.

Check it after the first rotation:

    getfacl /var/log/suricata/eve.json | grep zigmon

(or `usermod -aG suricata zigmon` if you would rather use the group, which has
the same problem in reverse: the group is inherited from the directory, so
that one survives rotation on its own.)

Rotation: Suricata ships `/etc/logrotate.d/suricata` and it needs no changing.
What it does and why each part suits the reading:

    daily, rotate 5, minsize 500k    five days of it, and nothing rotated on a
                                     quiet day
    delaycompress                    eve.json.1 stays plain text, which is what
                                     the house reads with tail to pick up
                                     whatever was written between its last
                                     reading and the rotation. Without this the
                                     newest copy would be a gzip and that
                                     minute would be lost.
    compress                         .2 onwards are gzipped, and the reading
                                     passes those over rather than tailing
                                     them as binary
    kill -HUP                        Suricata reopens its files, so the new one
                                     starts at nothing - which is exactly the
                                     "smaller than where I was" the reading
                                     watches for

So: leave it alone. The only thing it does not do for you is the ACL above.

## 7. Turn it on at the house

Control -> System -> The server that faces the internet -> *Suricata, where
it is running*:

    Read what Suricata saw          on
    Where its eve.json is           /var/log/suricata/eve.json
    How sure it has to be (1-3)     2

Then `zigmon --proxy` will name it, and `zigmon --proxy --test` will read the
end of it and say what came back.

## What the three levels mean

Suricata says how sure it is about each thing it saw, and the house weighs it
accordingly:

    1  "this is an attack"          weighs 8 - two of them is a block
    2  "this looks like one"        weighs 4
    3  "worth knowing"              weighs 1

The setting is the *least* sure it may be and still be weighed at all. 2 is
the sensible answer. 1 if you want only what it is certain about. 3 for a week
if you want to see everything it has to say, and then back to 2.

Classes that say plainly nothing is wrong - Not Suspicious Traffic, Misc
activity, Generic Protocol Command Decode, Network Scan - are never weighed at
any setting. Suricata writes a lot of those, and a house that acted on them
would keep out everybody who ever pinged it.

## If it eats the machine

Suricata will use what you give it. On a small proxy:

    detect:
      profile: low
    threading:
      set-cpu-affinity: no

and in `suricata.yaml`, `max-pending-packets: 1024`. It is watching one web
server, not a datacentre.

---

## Written from a machine that is not yours

Two wrong lines in two days in this file, both from memory rather than from
anything I could run:

- `dnf install suricata suricata-update` - the second word is not a package,
  and dnf abandons the whole transaction over one argument it cannot match, so
  it installed nothing and said only "Unable to find a match".
- then "EPEL 9 does not carry Suricata", which was me over-correcting. It
  does. The copr project I sent you instead does not exist.

Everything above now matches what your machine actually printed. If a step
still does not do what it says, send me what it printed - that is faster than
me guessing a third time.

---

## The config beside this file

`deploy/suricata.yaml` is the working one from a real AlmaLinux 9 proxy, with
everything above already in it: ens192, HOME_NET set to that machine alone,
eve.json by its full path, alerts with no payload and no packet, the two
dozen other eve types turned off and kept commented at the bottom in case you
want one back. Copy it, change `ens192` and the two addresses in HOME_NET to
yours, and `suricata -T -c ... -v` before starting.

The one thing it cannot carry is `/etc/sysconfig/suricata`, where the unit
gets `-i eth0` from. That one is yours to edit - see 4b.
