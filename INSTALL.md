# zigmon on AlmaLinux 9 — installation guide

Every command, what it should print, and how to confirm each step worked.
Written for a machine that already runs mosquitto and Zigbee2MQTT (the
dashboard can live on the same nginx as Node-RED and the Zigbee2MQTT
frontend; it claims its own hostname and nothing else). About ten minutes.

```
   Zigbee2MQTT ──► mosquitto ──► zigmon.service (user "zigmon")
   Shelly WiFi ──►    │              subscribes, writes /var/lib/zigmon/history.db
                      │              serves 127.0.0.1:9849, token-guarded
                      │                    ↑ unix socket
                      │           php-fpm ← nginx :443 (mqtt.falco81.net) ← browser
```

**Contents**

0. [The short way](#0-the-short-way)
1. [The broker account](#1-the-broker-account)
2. [Install packages](#2-install-packages)
3. [Create the daemon user](#3-create-the-daemon-user)
4. [Install the daemon](#4-install-the-daemon)
5. [Configure it](#5-configure-it)
6. [First test, before any service](#6-first-test-before-any-service)
7. [Start the service](#7-start-the-service)
8. [Install the web interface](#8-install-the-web-interface)
9. [Configure php-fpm](#9-configure-php-fpm)
10. [Configure nginx with TLS](#10-configure-nginx-with-tls)
11. [SELinux and the firewall](#11-selinux-and-the-firewall)
12. [Open the dashboard](#12-open-the-dashboard)
13. [Day-to-day use](#13-day-to-day-use)
14. [Troubleshooting](#14-troubleshooting)
15. [Maintenance](#15-maintenance)

---

## 0. The short way

Everything below is what the installer does, in the same order. Copy the whole
folder to the machine and run it from inside:

```bash
scp -r zigmon/ root@server:/root/
ssh root@server
cd /root/zigmon
sudo ./install.sh
```

It asks for the broker address and account, the hostname and the
subnets allowed to open the dashboard, then does the rest. The first
account of the dashboard, admin, is made when the daemon starts; its
password is in /var/lib/zigmon/first-login.txt (root only), to be changed
at the first sign-in. A PIN that unlocks the page the way it did before
5.19 is a PIN account, made on Settings - Access or with
`sudo zigmon --account-add kitchen operator --with-pin`. Everything can be
given up front:

```bash
sudo ./install.sh --mqtt-host 127.0.0.1 --mqtt-user zigmon --mqtt-password 'secret' \
     --create-mqtt-user --server-name mqtt.falco81.net \
     --allow 192.168.40.0/24,172.16.16.0/24 --yes
```

The certificate is expected in `/etc/nginx/certs/` as `server.pem`,
`server.key` and `server.ca` — the same files mosquitto's TLS listener uses.
`--cert`, `--key` and `--ca` point elsewhere.

---

## 1. The broker account

The daemon needs its own login. Read on the Zigbee2MQTT tree, write only on
the request topic (that is how the dashboard opens the network for joining),
and read on the Shelly tree if WiFi devices publish there.

```bash
mosquitto_passwd -b /etc/mosquitto/passwd zigmon 'secret'
```

Then append to `/etc/mosquitto/acl` — make sure the file ends with a newline
first, or the new block glues itself onto the previous line and mosquitto
refuses to start:

```bash
tail -c1 /etc/mosquitto/acl | od -c      # must show \n; if not:  echo >> /etc/mosquitto/acl
cat >> /etc/mosquitto/acl <<'EOF'

user zigmon
topic read zigbee2mqtt/#
topic write zigbee2mqtt/bridge/request/#
topic read shellies/#
EOF
systemctl restart mosquitto
```

Check it:

```bash
mosquitto_sub -h 127.0.0.1 -u zigmon -P 'secret' -t 'zigbee2mqtt/bridge/state' -C 1
```

Should print `{"state":"online"}` at once (it is a retained message).

## 2. Install packages

```bash
dnf install -y epel-release
dnf install -y python3 python3-paho-mqtt sqlite nginx php-fpm httpd-tools
python3 -c 'import paho.mqtt.client as m; print(m.__version__ if hasattr(m, "__version__") else "ok")'
```

`python3-paho-mqtt` is in EPEL. Both the 1.6 and the 2.x API work.

## 3. Create the daemon user

```bash
useradd --system --home-dir /var/lib/zigmon --no-create-home --shell /sbin/nologin zigmon
usermod -aG zigmon nginx
```

nginx joins the group because php-fpm (running as nginx, see step 9) must
read the API token, which the daemon writes as `zigmon:zigmon 0640`.

## 4. Install the daemon

```bash
install -d -m 755 /usr/local/lib/zigmon
install -m 755 zigmon.py /usr/local/lib/zigmon/zigmon.py
ln -sfn /usr/local/lib/zigmon/zigmon.py /usr/local/bin/zigmon
zigmon --version
```

## 5. Configure it

```bash
install -d -m 750 -o root -g zigmon /etc/zigmon
install -m 640 -o root -g zigmon deploy/config.json /etc/zigmon/config.json
vi /etc/zigmon/config.json
```

Set at least `mqtt_password` and `pin`. The rest of the defaults fit a local
mosquitto with Zigbee2MQTT on `zigbee2mqtt/`:

| option | meaning |
|---|---|
| `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password` | the broker |
| `mqtt_tls`, `mqtt_ca` | TLS, and the CA that verifies the broker (empty = no verification) |
| `base_topic` | Zigbee2MQTT's `mqtt.base_topic` |
| `extra_topics` | other trees to watch; `shellies/#` is understood as Shelly Gen2/3 status |
| `sample_interval` | seconds; readings arriving sooner replace the previous row |
| `retain_full_days`, `retain_hourly_days` | full resolution, hourly averages |
| `battery_warn/crit`, `lqi_warn/crit` | thresholds for the verdict |
| `stale_warn_min`, `stale_crit_min` | a silent device is flagged after this long |
| `temperature_min/max`, `humidity_max` | optional limits, `null` = off |
| `public_view` | the house may be watched without signing in (changing anything always needs one) |
| `session_idle_min`, `session_hours` | a sign-in not used ends after; and ends at the latest after |
| `login_tries`, `login_wait_min` | wrong passwords from one address before it waits, and for how long |
| `pin`, `pin_attempts`, `pin_lockout_s` | not used since 5.19 (the dashboard signs people in by name and password) |

`ZIGMON_<OPTION>` in the environment overrides any of them.

**Smart plugs and sensors** are easiest to add on the dashboard's Control
tab (Plugs and sensors → Add, Test, Save) — they start at once, no restart.
Or in `config.json` under `plugs`, which the tab then shows read-only. Either
way the daemon reads them over local RPC on port 80, so the address must be
reachable from this machine (`curl -s http://172.16.16.12/rpc/Shelly.GetDeviceInfo`):

```json
"plugs": [
  {"name": "Lednice", "host": "172.16.16.12", "password": "", "switch_id": 0, "mqtt_name": ""}
]
```

`password` is the plug's web-interface password, if it has one. Once it is
in the config, `zigmon shelly Lednice info` talks to it directly, and
`zigmon shelly Lednice dump` shows everything it reports. `mqtt_name`
is its `shellies/<name>` prefix if it also publishes to the broker, so the
same device is not recorded twice. Restart the daemon after editing; the
plug appears on the Overview as a socket panel, and the Control tab gains
the switch, the counter resets and the button bindings.

**Battery sensors by webhook.** A Shelly H&T on battery sleeps and cannot be
polled; it can push instead. Set `"sensor_listen": true` (the installer's
`--sensor-listen` does that and opens the port in the firewall), restart,
then create the webhook on the sensor once — wake it with its button first:

```bash
zigmon shelly --host 172.16.16.13 call Webhook.Create '{"cid":0,"enable":true,"event":"temperature.change","urls":["http://192.168.40.233:8088/?t=${ev.tC}&id=HT-Venek"]}'
zigmon shelly --host 172.16.16.13 call Webhook.Create '{"cid":0,"enable":true,"event":"humidity.change","urls":["http://192.168.40.233:8088/?rh=${ev.rh}&id=HT-Venek"]}'
```

`zigmon shelly listen --port 8089` shows pushes arriving without recording
them, if you want to check the template first.

## 6. First test, before any service

Run it in the foreground as the service user for a minute:

```bash
install -d -m 750 -o zigmon -g zigmon /var/lib/zigmon /var/log/zigmon /run/zigmon
sudo -u zigmon /usr/local/bin/zigmon
```

Expected within a few seconds:

```
... info  API token at /run/zigmon/api-token (owner zigmon, group zigmon, mode 640)
... info  connecting to mqtt://127.0.0.1:1883 as zigmon
... info  zigmon 1.0.0 running; API on http://127.0.0.1:9849
... info  connected; subscribed to zigbee2mqtt/#, shellies/#
... info  bridge is online
... info  new device: Temp-Balkon (Shelly SBHT-203C)
```

From another shell:

```bash
zigmon --status
curl -s http://127.0.0.1:9849/api/health | python3 -m json.tool
```

Ctrl-C when satisfied. `connect refused: not authorised` means the broker
account or ACL is wrong; `cannot reach the broker` means the address or port.

## 7. Start the service

```bash
install -m 644 deploy/zigmon.service /etc/systemd/system/zigmon.service
install -m 644 deploy/zigmon.logrotate /etc/logrotate.d/zigmon
systemctl daemon-reload
systemctl enable --now zigmon
systemctl status zigmon --no-pager
zigmon --check
```

The unit uses `RuntimeDirectory=`, `StateDirectory=` and `LogsDirectory=`, so
`/run/zigmon`, `/var/lib/zigmon` and `/var/log/zigmon` are created with the
right ownership on every start; the directories from step 6 are simply
reused.

## 8. Install the web interface

```bash
install -d -m 755 /var/www/zigmon
install -m 644 web/index.php web/zigmon-api.php web/favicon.svg /var/www/zigmon/
php -l /var/www/zigmon/index.php
```

## 9. Configure php-fpm

The default pool runs as `apache`, which cannot read the token. Switch it to
`nginx`:

```bash
sed -i 's/^user = apache/user = nginx/; s/^group = apache/group = nginx/' /etc/php-fpm.d/www.conf
sed -i 's/^listen.acl_users = apache,nginx/listen.acl_users = nginx/' /etc/php-fpm.d/www.conf
systemctl enable --now php-fpm
systemctl restart php-fpm
sudo -u nginx cat /run/zigmon/api-token && echo   # must print the token
```

If the last line says permission denied, nginx is not in the zigmon group
(step 3) or php-fpm was not restarted after the change.

## 10. Configure nginx with TLS

The certificate files are expected as `/etc/nginx/certs/server.pem`,
`server.key` and `server.ca`. Check the hostname is in the certificate:

```bash
openssl x509 -in /etc/nginx/certs/server.pem -noout -ext subjectAltName
```

Then:

```bash
install -m 644 deploy/nginx-zigmon.conf /etc/nginx/conf.d/zigmon.conf
vi /etc/nginx/conf.d/zigmon.conf      # server_name and the allow lines
nginx -t && systemctl reload nginx
```

The block does not claim `default_server`, so it sits beside any other site
on the same nginx. If `nginx.conf` still carries the stock
`listen 80 default_server` block, that block answers plain-http requests for
this hostname before the redirect can; comment it out or leave it, it only
affects http://.

Optional password on top of the address restriction:

```bash
htpasswd -B -c /etc/nginx/zigmon.htpasswd yourname
chown root:nginx /etc/nginx/zigmon.htpasswd; chmod 640 /etc/nginx/zigmon.htpasswd
```

and uncomment the two `auth_basic` lines.

## 11. SELinux and the firewall

Only if SELinux is enforcing (`getenforce`):

```bash
setsebool -P httpd_can_network_connect 1
semanage fcontext -a -t httpd_sys_content_t '/var/www/zigmon(/.*)?'
restorecon -R /var/www/zigmon
```

The boolean is what lets PHP connect to `127.0.0.1:9849`, which is not a
labelled http port.

```bash
firewall-cmd --permanent --add-service=http --add-service=https
firewall-cmd --reload
```

## 12. Open the dashboard

`https://mqtt.falco81.net/` — DNS (or `/etc/hosts` on the client) must point
the name at this machine. From the server itself:

```bash
curl -sk --resolve mqtt.falco81.net:443:127.0.0.1 https://mqtt.falco81.net/?api=health
```

## 13. Day-to-day use

```bash
zigmon --status                   # every device and its readings
zigmon --watch                    # what the broker is sending, live
zigmon --history Temp-Balkon --range 7d
zigmon --events
zigmon --permit-join on           # or from the Control tab
zigmon --plug                     # the plugs, live
zigmon --plug-toggle Lednice      # switch one
zigmon --bindings                 # button → plug rules (edit them on the Control tab)
zigmon shelly Lednice dump        # everything the plug reports
zigmon shelly Lednice ble on --reboot
zigmon shelly discover            # Shelly devices on this subnet
journalctl -u zigmon -f
```

Pair a new device: open the network (Control tab or `--permit-join on`),
press the device's button as its manual says (five quick presses on a Shelly
BLU), wait for the interview to finish. It appears on the Overview by itself;
rename it in the Zigbee2MQTT frontend and the dashboard follows, history
included.

## 14. Troubleshooting

| symptom | cause | fix |
|---|---|---|
| `zigmon` in a shell says "another zigmon is already running" | the service holds port 9849; the foreground run is only for step 6 | `systemctl status zigmon`; to test by hand, `systemctl stop zigmon` first, then `sudo -u zigmon zigmon` |
| `zigmon` refuses to run as root | root would leave root-owned database and WAL files the service cannot open | run it as the service user, or use the service |
| dashboard says "the monitoring daemon is not responding" | daemon not running, or a different `api_port` | `systemctl status zigmon`; `journalctl -u zigmon -n 30` |
| "the API token is unreadable" | php-fpm not running as nginx, or nginx not in the zigmon group | steps 3 and 9; `systemctl restart php-fpm` |
| `--check` says connect refused: not authorised | broker password or ACL | `mosquitto_sub -u zigmon -P … -t 'zigbee2mqtt/#' -C 1`; `/var/log/mosquitto/mosquitto.log` |
| bridge stays "unknown" | daemon is not subscribed to the right base topic | `base_topic` must equal Zigbee2MQTT's `mqtt.base_topic` |
| devices appear but never update | Zigbee2MQTT publishes, the daemon does not see it | `zigmon --watch` shows what arrives; check the ACL grants `read zigbee2mqtt/#` |
| permit join fails with "publish failed" | ACL lacks `write zigbee2mqtt/bridge/request/#` | step 1 |
| a device shows "silent for 3h" although it is fine | it reports less often than `stale_warn_min` | raise `stale_warn_min` in the config; sleepy sensors often report hourly |
| browser: 403 | your address is not in an `allow` line | edit `/etc/nginx/conf.d/zigmon.conf`, `systemctl reload nginx` |
| browser: certificate warning | the hostname is not in the certificate's SAN | `openssl x509 -in … -noout -ext subjectAltName` |
| nginx fails to start after adding the file | two `default_server` on the same port, or `http2 on;` on nginx 1.20 | the shipped block uses neither; `nginx -t` names the line |
| a plug shows "unreachable" | the daemon cannot reach port 80 on it (different subnet, firewall), or the password is wrong | `curl -s http://<ip>/rpc/Shelly.GetDeviceInfo` from this machine; `journalctl -u zigmon` names the reason |
| a plug shows "rate limiting" | too many requests too quickly (Gen3 with a password) | it backs off by itself; leave `plug_min_request_gap` at 1.0 |
| a button press does nothing to the plug | no binding, or the action name differs | Events tab shows the action exactly as reported; use that name in the binding, or `*` |
| mosquitto fails after editing the ACL | the block glued itself onto the previous line | step 1: the file must end with a newline before appending |

The event log (Events tab, `zigmon --events`) records broker connects and
disconnects, so a gap in the charts has an explanation next to it.

## 15. Maintenance

**Upgrade** — copy the new folder across and `sudo ./install.sh --upgrade`,
or by hand:

```bash
install -m 755 zigmon.py /usr/local/lib/zigmon/zigmon.py
install -m 644 web/index.php web/zigmon-api.php /var/www/zigmon/
systemctl restart zigmon
```

The database schema is created with `IF NOT EXISTS`, so an old database
simply keeps working.

**Backup** — `/var/lib/zigmon/history.db` (copy it with `sqlite3
/var/lib/zigmon/history.db ".backup /root/history.db"` while the daemon runs)
and `/etc/zigmon/config.json`.

**Backups to other machines** (5.21) — Control → Backup sends the backup of
the whole installation to an FTP, FTPS, SFTP, SCP or SMB server, on a
schedule or with *Back up now*. Set *The password of the backups* first:
nothing is sent unlocked. Each one arrives as
`zigmon-full-HOST-STAMP.tar.gz.enc` with a `.sha256` and a `-RESTORE.txt`
beside it; it opens with the password alone:

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -in FILE.tar.gz.enc -out FILE.tar.gz
sudo zigmon --full-restore FILE.tar.gz.enc --passphrase-file /root/backup-password
```

SFTP and SCP need `openssh-clients`, SMB needs `samba-client`
(`install.sh` installs both when it can). A folder on this machine is not a
destination: the daemon may write only into its own folders. Reach a NAS as
SMB or SFTP instead. `zigmon --rbackup-status` and `zigmon --rbackup-now` do
the same from the command line.

**Size** — `zigmon --diag` shows it. A dozen sensors reporting every few
minutes come to roughly 20 MB a year; the hourly roll-up runs inside the
daemon every hour, nothing to schedule.

**Remove** — `sudo ./install.sh --uninstall`, which keeps `/var/lib/zigmon`.
