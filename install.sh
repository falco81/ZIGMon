#!/usr/bin/env bash
#
# install.sh — set up zigmon on AlmaLinux 9.
#
# Packages, service user, configuration, systemd unit, log rotation, nginx
# with TLS, php-fpm, SELinux, firewall, the MQTT account, and a check that it
# all works. Run it from inside the project folder, as root:
#
#     sudo ./install.sh
#
# Everything it asks can be given on the command line instead; --help lists
# the options. --dry-run prints what would happen and changes nothing.
# --upgrade replaces the program files and restarts. --uninstall removes the
# service and the dashboard but keeps the recorded history.
#
set -euo pipefail

VERSION="5.25.0"
SERVICE_USER="zigmon"
LIB_DIR="/usr/local/lib/zigmon"
BIN_LINK="/usr/local/bin/zigmon"
CONFIG_DIR="/etc/zigmon"
CONFIG_FILE="$CONFIG_DIR/config.json"
WEB_DIR="/var/www/zigmon"
CERT_DIR="/etc/nginx/certs"
NGINX_CONF="/etc/nginx/conf.d/zigmon.conf"
UNIT_FILE="/etc/systemd/system/zigmon.service"
LOGROTATE_FILE="/etc/logrotate.d/zigmon"

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=""
ASSUME_YES=""
WITH_WEB="yes"
DO_UPGRADE=""
DO_UNINSTALL=""

MQTT_HOST="127.0.0.1"
MQTT_PORT=""
MQTT_USER="zigmon"
MQTT_PASSWORD=""
MQTT_TLS=""
MQTT_CA=""
BASE_TOPIC="zigbee2mqtt"
CREATE_MQTT_USER=""
PIN=""
SERVER_NAME="mqtt.falco81.net"
ALLOW_FROM=""
CERT_FILE="server.pem"
KEY_FILE="server.key"
CA_FILE="server.ca"
HTPASSWD_USER=""
SENSOR_LISTEN=""
SENSOR_PORT="8088"

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
    C_HEAD=$'\033[1;36m'; C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_BAD=$'\033[1;31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
    C_HEAD=""; C_OK=""; C_WARN=""; C_BAD=""; C_DIM=""; C_OFF=""
fi
step()  { printf '\n%s==> %s%s\n' "$C_HEAD" "$1" "$C_OFF"; }
say()   { printf '    %s\n' "$1"; }
note()  { printf '    %s%s%s\n' "$C_DIM" "$1" "$C_OFF"; }
good()  { printf '    %s%s%s\n' "$C_OK" "$1" "$C_OFF"; }
warn()  { printf '    %s%s%s\n' "$C_WARN" "$1" "$C_OFF"; }
fail()  { printf '\n%sERROR: %s%s\n' "$C_BAD" "$1" "$C_OFF" >&2; exit 1; }

run() {
    if [[ -n "$DRY_RUN" ]]; then
        note "[would run] $*"
        return 0
    fi
    "$@"
}

# As run, for a command whose last argument is a secret. The dry run printed
# the whole line, so --dry-run - the mode whose promise is that it changes
# nothing and only says what it would do - echoed the broker password into a
# terminal people paste into bug reports.
run_quietly() {
    if [[ -n "$DRY_RUN" ]]; then
        local shown=("${@:1:$#-1}")
        note "[would run] ${shown[*]} ********"
        return 0
    fi
    "$@"
}

ask() {          # ask VAR "prompt" "default"
    local var="$1" prompt="$2" default="${3:-}" answer
    if [[ -n "$ASSUME_YES" ]]; then
        printf -v "$var" '%s' "${!var:-$default}"
        return
    fi
    if [[ -n "$default" ]]; then
        read -r -p "    $prompt [$default]: " answer
    else
        read -r -p "    $prompt: " answer
    fi
    printf -v "$var" '%s' "${answer:-$default}"
}

ask_secret() {
    local var="$1" prompt="$2" answer
    if [[ -n "$ASSUME_YES" ]]; then
        return
    fi
    read -r -s -p "    $prompt: " answer
    echo
    printf -v "$var" '%s' "$answer"
}

confirm() {      # confirm "question" [default y|n]
    local default="${2:-y}" answer
    [[ -n "$ASSUME_YES" ]] && [[ "$default" == "y" ]] && return 0
    [[ -n "$ASSUME_YES" ]] && return 1
    read -r -p "    $1 [$( [[ $default == y ]] && echo Y/n || echo y/N )] " answer
    answer="${answer:-$default}"
    [[ "$answer" =~ ^[Yy] ]]
}

usage() {
    cat <<EOF
zigmon installer $VERSION — AlmaLinux 9

Usage: sudo ./install.sh [options]

  --mqtt-host HOST        broker address (default 127.0.0.1)
  --mqtt-port PORT        broker port (default 1883, or 8883 with --mqtt-tls)
  --mqtt-user NAME        broker account for the daemon (default zigmon)
  --mqtt-password PASS    its password
  --mqtt-tls              connect with TLS
  --mqtt-ca FILE          CA file that verifies the broker (with --mqtt-tls)
  --create-mqtt-user      create the account in the local mosquitto (passwd + ACL)
  --base-topic TOPIC      Zigbee2MQTT base topic (default zigbee2mqtt)
  --pin PIN               not used since 5.19 (the dashboard signs in by name and password);
                          with --yes still the password for --htpasswd
  --server-name HOST      hostname of the dashboard (default mqtt.falco81.net)
  --allow CIDR[,CIDR]     subnets allowed to open the dashboard
  --cert FILE --key FILE  certificate and key already in $CERT_DIR (default server.pem / server.key)
  --ca FILE               issuer chain, for OCSP (default server.ca)
  --htpasswd USER         also protect the dashboard with a password for USER
  --sensor-listen [PORT]  accept webhook pushes from battery Shelly sensors (default port 8088)
  --no-web                the daemon only, without nginx or the dashboard
  --source DIR            where the project files are (default: beside this script)
  -y, --yes               take defaults, ask nothing
  --dry-run               print every command it would run, change nothing
  --upgrade               replace the program files and restart, touching nothing else
  --uninstall             remove the service and dashboard, keep the history
  -h, --help              this text
EOF
}

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mqtt-host)      MQTT_HOST="$2"; shift 2 ;;
        --mqtt-port)      MQTT_PORT="$2"; shift 2 ;;
        --mqtt-user)      MQTT_USER="$2"; shift 2 ;;
        --mqtt-password)  MQTT_PASSWORD="$2"; shift 2 ;;
        --mqtt-tls)       MQTT_TLS="yes"; shift ;;
        --mqtt-ca)        MQTT_CA="$2"; shift 2 ;;
        --create-mqtt-user) CREATE_MQTT_USER="yes"; shift ;;
        --base-topic)     BASE_TOPIC="$2"; shift 2 ;;
        --pin)            PIN="$2"; shift 2 ;;
        --server-name)    SERVER_NAME="$2"; shift 2 ;;
        --allow)          ALLOW_FROM="$2"; shift 2 ;;
        --cert)           CERT_FILE="$2"; shift 2 ;;
        --key)            KEY_FILE="$2"; shift 2 ;;
        --ca)             CA_FILE="$2"; shift 2 ;;
        --htpasswd)       HTPASSWD_USER="$2"; shift 2 ;;
        --sensor-listen)  SENSOR_LISTEN="yes"; if [[ "${2:-}" =~ ^[0-9]+$ ]]; then SENSOR_PORT="$2"; shift; fi; shift ;;
        --no-web)         WITH_WEB=""; shift ;;
        --source)         SOURCE_DIR="$2"; shift 2 ;;
        -y|--yes)         ASSUME_YES="yes"; shift ;;
        --dry-run)        DRY_RUN="yes"; shift ;;
        --upgrade)        DO_UPGRADE="yes"; shift ;;
        --uninstall)      DO_UNINSTALL="yes"; shift ;;
        -h|--help)        usage; exit 0 ;;
        *)                fail "unknown option $1 (see --help)" ;;
    esac
done

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
# The nginx site file has had two names over time; on an existing machine use
# whichever is there, so upgrades and uninstalls edit the file nginx really reads.
resolve_nginx_conf() {
    local candidate
    for candidate in "$NGINX_CONF" /etc/nginx/conf.d/nginx-zigmon.conf /etc/nginx/conf.d/zigmon.conf; do
        if [[ -f "$candidate" ]]; then NGINX_CONF="$candidate"; return; fi
    done
}

preflight() {
    resolve_nginx_conf
    step "Checking the machine"
    [[ $EUID -eq 0 ]] || fail "run this as root (sudo ./install.sh)"
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        case "${ID:-}" in
            almalinux|rocky|rhel|centos) good "$PRETTY_NAME" ;;
            *) warn "written for AlmaLinux 9; this is ${PRETTY_NAME:-unknown}. Continuing anyway." ;;
        esac
    fi
    local f
    for f in zigmon.py deploy/zigmon.service deploy/config.json deploy/zigmon.logrotate; do
        [[ -f "$SOURCE_DIR/$f" ]] || fail "missing $SOURCE_DIR/$f — run the installer from the project folder"
    done
    if [[ -n "$WITH_WEB" ]]; then
        for f in web/index.php web/zigmon-api.php web/favicon.svg deploy/nginx-zigmon.conf; do
            [[ -f "$SOURCE_DIR/$f" ]] || fail "missing $SOURCE_DIR/$f"
        done
    fi
    good "project files found in $SOURCE_DIR"
    command -v python3 >/dev/null || warn "python3 not found yet; it will be installed"
    if command -v getenforce >/dev/null; then
        note "SELinux: $(getenforce)"
    fi
}

# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------
gather_answers() {
    step "The broker"
    say "The daemon subscribes to the MQTT broker Zigbee2MQTT publishes to."
    ask MQTT_HOST "Broker address" "$MQTT_HOST"
    if [[ -z "$MQTT_TLS" ]] && [[ -z "$ASSUME_YES" ]]; then
        if confirm "Connect with TLS? (plain is fine when the broker is on this machine)" n; then
            MQTT_TLS="yes"
        fi
    fi
    if [[ -n "$MQTT_TLS" ]]; then
        [[ -n "$MQTT_PORT" ]] || MQTT_PORT="8883"
        ask MQTT_PORT "Broker port" "$MQTT_PORT"
        ask MQTT_CA "CA file to verify the broker (empty = no verification)" "${MQTT_CA:-$CERT_DIR/server.ca}"
    else
        [[ -n "$MQTT_PORT" ]] || MQTT_PORT="1883"
        ask MQTT_PORT "Broker port" "$MQTT_PORT"
    fi
    ask BASE_TOPIC "Zigbee2MQTT base topic" "$BASE_TOPIC"
    ask MQTT_USER "Broker account for the daemon" "$MQTT_USER"
    if [[ -z "$MQTT_PASSWORD" ]]; then
        if [[ -n "$ASSUME_YES" ]]; then
            MQTT_PASSWORD="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20)"
            note "generated a random broker password"
        else
            ask_secret MQTT_PASSWORD "Its password (empty = generate one)"
            if [[ -z "$MQTT_PASSWORD" ]]; then
                MQTT_PASSWORD="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20)"
                note "generated a random broker password"
            fi
        fi
    fi
    if [[ -z "$CREATE_MQTT_USER" ]] && [[ -f /etc/mosquitto/passwd ]] \
       && [[ "$MQTT_HOST" =~ ^(127\.0\.0\.1|localhost|::1)$ || "$MQTT_HOST" == "$(hostname -f 2>/dev/null)" ]]; then
        if confirm "Create the account \"$MQTT_USER\" in the local mosquitto (passwd + ACL)?" y; then
            CREATE_MQTT_USER="yes"
        fi
    fi

    step "The dashboard"
    # 5.19: no PIN to ask for - the dashboard signs people in by name and
    # password; the first account, admin, is made when the daemon starts
    if [[ -n "$WITH_WEB" ]]; then
        ask SERVER_NAME "Hostname" "$SERVER_NAME"
        if [[ -z "$ALLOW_FROM" ]]; then
            local guess
            guess="$( (ip -4 route show 2>/dev/null || true) | awk '/proto kernel/ && /src/ {print $1}' | paste -sd, - || true)"
            ask ALLOW_FROM "Subnets allowed to open it (comma separated)" "${guess:-192.168.0.0/16}"
        fi
        if [[ -z "$HTPASSWD_USER" ]] && [[ -z "$ASSUME_YES" ]]; then
            if confirm "Also require a username and password in the browser?" n; then
                ask HTPASSWD_USER "Username" "admin"
            fi
        fi
    fi
}

# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
install_packages() {
    step "Packages"
    local wanted=(python3 python3-paho-mqtt sqlite)
    [[ -n "$WITH_WEB" ]] && wanted+=(nginx php-fpm php-opcache httpd-tools)
    if ! rpm -q epel-release >/dev/null 2>&1; then
        say "python3-paho-mqtt comes from EPEL"
        run dnf install -y epel-release >/dev/null || fail "could not enable EPEL"
    fi
    local missing=() package
    for package in "${wanted[@]}"; do
        rpm -q "$package" >/dev/null 2>&1 || missing+=("$package")
    done
    if [[ ${#missing[@]} -eq 0 ]]; then
        good "everything needed is already installed"
        return
    fi
    say "installing: ${missing[*]}"
    if [[ -n "$DRY_RUN" ]]; then
        note "[would run] dnf install -y ${missing[*]}"
        return
    fi
    dnf install -y "${missing[@]}" >/dev/null || fail "package installation failed"
    good "installed"
}

# The backups to other machines (5.21) reach SFTP and SCP servers with
# OpenSSH's own programs and SMB shares with smbclient. Neither is needed for
# anything else, so neither stops the install: missing, the page says which
# kinds cannot be used here, and FTP and FTPS (Python's own) still can.
install_backup_tools() {
    step "Tools for the backups to other machines"
    local wanted=(openssh-clients samba-client) missing=() package
    for package in "${wanted[@]}"; do
        rpm -q "$package" >/dev/null 2>&1 || missing+=("$package")
    done
    if [[ ${#missing[@]} -eq 0 ]]; then
        good "ssh, sftp, scp and smbclient are there"
        return 0
    fi
    if [[ -n "$DRY_RUN" ]]; then
        note "[would run] dnf install -y ${missing[*]}"
        return 0
    fi
    if dnf install -y -q "${missing[@]}" >/dev/null 2>&1; then
        good "installed: ${missing[*]}"
    else
        warn "could not install ${missing[*]}: backups to SFTP, SCP or SMB servers will not work until they are (FTP and FTPS do)"
    fi
}

create_user() {
    step "Service user"
    if id "$SERVICE_USER" >/dev/null 2>&1; then
        good "user $SERVICE_USER already exists"
    else
        run useradd --system --home-dir /var/lib/zigmon --no-create-home \
            --shell /sbin/nologin --comment "zigmon daemon" "$SERVICE_USER"
        good "created $SERVICE_USER"
    fi
    if [[ -n "$WITH_WEB" ]] && id nginx >/dev/null 2>&1; then
        # nginx (and php-fpm running as nginx) must read the API token, which
        # is 0640 owned by zigmon; group membership is how.
        if id -nG nginx | tr ' ' '\n' | grep -qx "$SERVICE_USER"; then
            good "nginx is already in the $SERVICE_USER group"
        else
            run usermod -aG "$SERVICE_USER" nginx
            good "added nginx to the $SERVICE_USER group"
        fi
    fi
}

install_program() {
    step "Program files"
    run install -d -m 755 "$LIB_DIR"
    run install -m 755 "$SOURCE_DIR/zigmon.py" "$LIB_DIR/zigmon.py"
    for doc in README.md INSTALL.md; do
        [[ -f "$SOURCE_DIR/$doc" ]] && run install -m 644 "$SOURCE_DIR/$doc" "$LIB_DIR/$doc"
    done
    run ln -sfn "$LIB_DIR/zigmon.py" "$BIN_LINK"
    good "$LIB_DIR/zigmon.py, command \"zigmon\""
    if [[ -z "$DRY_RUN" ]]; then
        python3 -c 'import paho.mqtt.client' 2>/dev/null || fail "python3-paho-mqtt is not importable; dnf install -y python3-paho-mqtt"
    fi
}

write_config() {
    step "Configuration"
    run install -d -m 750 -o root -g "$SERVICE_USER" "$CONFIG_DIR"
    if [[ -f "$CONFIG_FILE" ]] && [[ -n "$DO_UPGRADE" ]]; then
        good "keeping the existing $CONFIG_FILE"
        return
    fi
    if [[ -f "$CONFIG_FILE" ]]; then
        run cp -a "$CONFIG_FILE" "$CONFIG_FILE.bak"
        note "the previous configuration is in $CONFIG_FILE.bak"
    fi
    local tls_json="false" ca_json="\"\"" pin_json="\"\""
    [[ -n "$MQTT_TLS" ]] && tls_json="true"
    [[ -n "$MQTT_CA" ]] && ca_json="$(printf '%s' "$MQTT_CA" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    [[ -n "$PIN" ]] && pin_json="$(printf '%s' "$PIN" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    local pw_json user_json host_json topic_json
    pw_json="$(printf '%s' "$MQTT_PASSWORD" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    user_json="$(printf '%s' "$MQTT_USER" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    host_json="$(printf '%s' "$MQTT_HOST" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    topic_json="$(printf '%s' "$BASE_TOPIC" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    if [[ -n "$DRY_RUN" ]]; then
        note "[would write] $CONFIG_FILE (broker $MQTT_HOST:$MQTT_PORT as $MQTT_USER, topic $BASE_TOPIC)"
        return
    fi
    python3 - "$SOURCE_DIR/deploy/config.json" "$CONFIG_FILE" <<EOF
import json, sys
cfg = json.load(open(sys.argv[1]))
cfg.update({
    "mqtt_host": $host_json, "mqtt_port": int("$MQTT_PORT"), "mqtt_username": $user_json,
    "mqtt_password": $pw_json, "mqtt_tls": $tls_json, "mqtt_ca": $ca_json,
    "base_topic": $topic_json, "pin": $pin_json,
    "sensor_listen": $( [[ -n "$SENSOR_LISTEN" ]] && echo true || echo false ),
    "sensor_listen_port": int("$SENSOR_PORT"),
})
json.dump(cfg, open(sys.argv[2], "w"), indent=2)
open(sys.argv[2], "a").write("\n")
EOF
    chown root:"$SERVICE_USER" "$CONFIG_FILE"
    chmod 640 "$CONFIG_FILE"
    good "$CONFIG_FILE (root:$SERVICE_USER 640 — it holds the broker password)"
}

create_mqtt_user() {
    [[ -n "$CREATE_MQTT_USER" ]] || return 0
    step "Broker account"
    command -v mosquitto_passwd >/dev/null || { warn "mosquitto_passwd not found; create the account by hand"; return; }
    local passwd_file="/etc/mosquitto/passwd" acl_file="/etc/mosquitto/acl"
    run_quietly mosquitto_passwd -b "$passwd_file" "$MQTT_USER" "$MQTT_PASSWORD" 2>/dev/null \
        || fail "mosquitto_passwd failed"
    good "account $MQTT_USER in $passwd_file"
    if [[ -f "$acl_file" ]]; then
        if grep -q "^user $MQTT_USER\$" "$acl_file"; then
            good "an ACL block for $MQTT_USER already exists; leaving it"
        elif [[ -z "$DRY_RUN" ]]; then
            # The file must end with a newline before we append, or the new
            # block glues itself to the last line and mosquitto refuses to start.
            [[ -z "$(tail -c1 "$acl_file")" ]] || echo >> "$acl_file"
            cat >> "$acl_file" <<EOF

user $MQTT_USER
topic read $BASE_TOPIC/#
topic write $BASE_TOPIC/bridge/request/#
topic read shellies/#
EOF
            good "ACL block added to $acl_file (read $BASE_TOPIC/#, write bridge/request/#)"
        else
            note "[would append] an ACL block for $MQTT_USER to $acl_file"
        fi
    else
        note "no $acl_file — the account has full access unless you add one"
    fi
    # zigmon reads the ACL to tell you what is missing from it (Control ->
    # System -> What the broker must allow). One read is all it needs, and
    # mosquitto keeps the file to itself, so ask for that read explicitly.
    if [[ -f "$acl_file" && -z "$DRY_RUN" ]]; then
        if sudo -u "$SERVICE_USER" test -r "$acl_file" 2>/dev/null; then
            good "$SERVICE_USER can read $acl_file (the ACL check works)"
        elif command -v setfacl >/dev/null && setfacl -m "u:$SERVICE_USER:r" "$acl_file" 2>/dev/null; then
            good "$SERVICE_USER may now read $acl_file (setfacl)"
        elif chgrp mosquitto "$acl_file" 2>/dev/null && chmod 640 "$acl_file" 2>/dev/null \
             && usermod -aG mosquitto "$SERVICE_USER" 2>/dev/null; then
            good "$SERVICE_USER added to the mosquitto group; $acl_file is 640"
        else
            note "$SERVICE_USER cannot read $acl_file — the ACL check will say so; setfacl -m u:$SERVICE_USER:r $acl_file fixes it"
        fi
    fi
    if [[ -z "$DRY_RUN" ]]; then
        systemctl restart mosquitto 2>/dev/null && good "mosquitto restarted" || warn "could not restart mosquitto"
    fi
}

# "Add them for me" writes the missing lines into the broker's ACL and then
# asks mosquitto to read the file again. A HUP is the polite way, but one
# user may not signal another's process, so systemd is asked instead - and
# this is the one line that lets it. An upgrade needs it as much as a fresh
# install: the first time round it was written only on a fresh install, and
# nobody upgrading ever got it.
allow_broker_reload() {
    [[ -n "$DRY_RUN" ]] && return 0
    command -v systemctl >/dev/null || return 0
    local sudoers=/etc/sudoers.d/zigmon
    local line="$SERVICE_USER ALL=(root) NOPASSWD: /usr/bin/systemctl kill -s HUP mosquitto"
    if [[ -f "$sudoers" ]] && grep -qF "$line" "$sudoers" 2>/dev/null; then
        good "$SERVICE_USER may already ask systemd to reload mosquitto"
        return 0
    fi
    if printf '%s\n' "$line" > "$sudoers" 2>/dev/null && chmod 440 "$sudoers" 2>/dev/null; then
        if command -v visudo >/dev/null && ! visudo -cf "$sudoers" >/dev/null 2>&1; then
            rm -f "$sudoers"
            note "$sudoers was not accepted by visudo and has been removed"
            return 0
        fi
        good "$SERVICE_USER may ask systemd to reload mosquitto ($sudoers)"
    else
        note "could not write $sudoers - after mending the ACL, reload mosquitto yourself"
    fi
}

# What the dashboard may ask of root (5.18): the certificate, who may reach
# which page, the firewall, a backup of the whole installation, and a new
# version. The daemon cannot do any of it - it runs as $SERVICE_USER under
# ProtectSystem=strict - so it lays a request down under /var/lib/zigmon and a
# path unit starts a helper of root's, which checks every value and does that
# one thing. The release keys are the ones a new version from the dashboard
# must be signed by; only root, and only this script, puts them there.
install_helpers() {
    step "What the dashboard may ask of root"
    run install -m 755 "$SOURCE_DIR/deploy/zigmon_root.py" "$LIB_DIR/zigmon_root.py"
    run install -m 755 "$SOURCE_DIR/deploy/zigmon_upgrade.py" "$LIB_DIR/zigmon_upgrade.py"
    run install -d -m 755 "$LIB_DIR/release-keys"
    local k u
    for k in "$SOURCE_DIR"/deploy/release-keys/*.pub; do
        [[ -f "$k" ]] && run install -m 644 "$k" "$LIB_DIR/release-keys/"
    done
    for u in zigmon-root.path zigmon-root.service zigmon-upgrade.path zigmon-upgrade.service; do
        run install -m 644 "$SOURCE_DIR/deploy/$u" "/etc/systemd/system/$u"
    done
    run install -d -m 750 -o "$SERVICE_USER" -g "$SERVICE_USER" /var/lib/zigmon
    run install -d -m 750 -o "$SERVICE_USER" -g "$SERVICE_USER" /var/lib/zigmon/root \
        /var/lib/zigmon/root/in /var/lib/zigmon/root/out /var/lib/zigmon/upgrade
    # root's own: the kept backups of the whole installation (they hold the
    # certificate's key and every password) and the key they are sealed with
    run install -d -m 700 /var/lib/zigmon-root /var/backups/zigmon
    run systemctl daemon-reload
    run systemctl enable --now zigmon-root.path zigmon-upgrade.path
    # a path unit reads what it watches when it starts: the network and the
    # clock (5.21) are asked in files of their own, which an old one ignores
    run systemctl restart zigmon-root.path
    good "zigmon_root.py and zigmon_upgrade.py, started by zigmon-root.path and zigmon-upgrade.path"
}

install_time_tools() {
    # The clock every schedule, sunrise scene and one-tap code of the house
    # runs on (5.21): chrony keeps it, and the dashboard's Time section sets
    # its servers. systemd-timesyncd and chronyd would fight over it.
    step "The clock"
    if ! command -v chronyc >/dev/null 2>&1; then
        if [[ -n "$DRY_RUN" ]]; then
            note "[would run] dnf install -y chrony"
        else
            dnf install -y chrony >/dev/null || { warn "chrony could not be installed - the Time section reads nothing"; return; }
        fi
    fi
    if systemctl is-active --quiet systemd-timesyncd 2>/dev/null; then
        run systemctl disable --now systemd-timesyncd
    fi
    run systemctl enable --now chronyd
    run timedatectl set-ntp true || true
    grep -Eq '^(server|pool) ' /etc/chrony.conf 2>/dev/null \
        || warn "/etc/chrony.conf names no time server - set some under Control - Time"
    command -v nmcli >/dev/null 2>&1 \
        || note "NetworkManager (nmcli) is not here: the Network section can only show the network, not change it"
    good "chronyd keeps the clock"
}

install_service() {
    step "systemd"
    run install -m 644 "$SOURCE_DIR/deploy/zigmon.service" "$UNIT_FILE"
    run install -m 644 "$SOURCE_DIR/deploy/zigmon.logrotate" "$LOGROTATE_FILE"
    run install -d -m 750 -o "$SERVICE_USER" -g "$SERVICE_USER" /var/lib/zigmon /var/log/zigmon
    run systemctl daemon-reload
    good "$UNIT_FILE and $LOGROTATE_FILE"
}

# The zigmon console at login (5.21): root signing in at the machine's own
# screen or over SSH lands in `zigmon --console`; q leaves it for the shell. On
# unless switched off (`zigmon --console-at-login off`), which an upgrade
# leaves as it is. The switch is kept in /etc itself, where only root writes -
# not in /etc/zigmon, whose group is the service's: a flag the service could
# replace would be a link or a pipe for root's login to follow.
install_console() {
    step "The console at login"
    if [[ -n "$DRY_RUN" ]]; then note "[would write] /etc/profile.d/zz-zigmon-console.sh"; return 0; fi
    install -m 0644 "$SOURCE_DIR/deploy/zz-zigmon-console.sh" /etc/profile.d/zz-zigmon-console.sh
    local flag=/etc/zigmon-console-login
    # a link or anything else not a plain file is taken away, never followed
    if [[ -L "$flag" || ( -e "$flag" && ! -f "$flag" ) ]]; then rm -rf "$flag"; fi
    if [[ ! -f "$flag" ]]; then
        printf 'on\n' > "$flag"
        chmod 0644 "$flag"
    fi
    good "the zigmon console at login: $(head -c 4 "$flag" | tr -cd 'onf') (zigmon --console-at-login on|off)"
}

install_web() {
    [[ -n "$WITH_WEB" ]] || return 0
    step "Dashboard files"
    run install -d -m 755 "$WEB_DIR"
    run install -m 644 "$SOURCE_DIR/web/index.php" "$WEB_DIR/index.php"
    run install -m 644 "$SOURCE_DIR/web/zigmon-api.php" "$WEB_DIR/zigmon-api.php"
    run install -m 644 "$SOURCE_DIR/web/favicon.svg" "$WEB_DIR/favicon.svg"
    good "$WEB_DIR"

    # php-fpm serves it over a socket nginx can reach; the default pool runs as
    # apache, which is not in the zigmon group and so cannot read the token.
    if [[ -f /etc/php-fpm.d/www.conf ]] && [[ -z "$DRY_RUN" ]]; then
        if grep -q '^user = apache' /etc/php-fpm.d/www.conf; then
            cp -a /etc/php-fpm.d/www.conf /etc/php-fpm.d/www.conf.bak
            sed -i 's/^user = apache/user = nginx/; s/^group = apache/group = nginx/' /etc/php-fpm.d/www.conf
            sed -i 's/^listen.acl_users = apache,nginx/listen.acl_users = nginx/' /etc/php-fpm.d/www.conf
            good "php-fpm now runs as nginx (the original is kept as www.conf.bak)"
        else
            good "php-fpm is already running as nginx"
        fi
        if ! php -l "$WEB_DIR/index.php" >/dev/null 2>&1; then
            warn "php -l reports a problem in index.php"
        fi
        tune_php_fpm
        harden_php
    fi
    if [[ -z "$DRY_RUN" ]]; then
        systemctl enable --now php-fpm >/dev/null 2>&1 || true
        systemctl restart php-fpm >/dev/null 2>&1 || true
    fi
}

# php2shell, 21 October 2026: CVE-2026-109618 and CVE-2026-109619, both 9.2.
# Two holes in PHP's own handling of a request - one reached by running it out
# of memory, one by the state of a finished request outliving the memory it
# was in and being read by the next request on the same worker. Both are
# reached BEFORE any page of this house runs, so nothing in index.php, no PIN
# and no allow rule is between a caller and them.
#
# The only real fix is the version: 8.2.35, 8.3.36, 8.4.27, 8.5.12 or newer,
# or a distribution's backport. This function does not pretend otherwise - it
# says so, loudly, and then sets the two settings that take away one of the
# published ways in and the one that stops PHP announcing its own version to
# everybody who asks.
harden_php() {
    local ini=/etc/php.d/99-zigmon-hardening.ini
    [[ -d /etc/php.d ]] || return 0
    if [[ ! -f "$ini" ]]; then
        cat > "$ini" <<'PHPINI'
; Written by zigmon's installer. Safe to keep after PHP is updated.
;
; php2shell (CVE-2026-109618, CVE-2026-109619, 21 October 2026): the upload
; progress handler is one of the two published ways in, and nothing in this
; dashboard uses it - every file picker on the page is read in the browser
; and sent as JSON. Off.
session.upload_progress.enabled = 0
; A session id the server did not issue is never adopted. Good practice on
; its own, and it closes the door this house has no use for.
session.use_strict_mode = 1
; Do not announce the version of PHP in a header to everybody who asks. It
; does not mend anything; it stops this machine telling a scanner which of
; the two holes to try.
expose_php = Off
;
; Deliberately NOT open_basedir here. It is the obvious next line and it
; breaks this dashboard: index.php reads /etc/timezone to know what time it
; is, and a list of directories written by an installer is wrong the first
; time somebody puts the web root somewhere else. It also mends neither of
; the two holes above, which are reached before any of this page's code runs.
PHPINI
        good "PHP hardening written to $ini"
    else
        good "PHP hardening already in place ($ini)"
    fi
    # ...and then the thing that actually matters.
    local v; v="$(php-fpm -v 2>/dev/null || php -v 2>/dev/null)"
    v="$(printf '%s' "$v" | sed -n 's/^PHP \([0-9][0-9.]*\).*/\1/p' | head -n 1)"
    [[ -n "$v" ]] || return 0
    local branch="${v%.*}" patch="${v##*.}" want=""
    case "$branch" in
        8.5) want=12 ;;
        8.4) want=27 ;;
        8.3) want=36 ;;
        8.2) want=35 ;;
    esac
    # A branch newer than the four above is not "unfixed", it is newer than
    # this installer. Without this, 8.6 would be warned about as though it
    # were 8.1.
    local major="${branch%%.*}" minor="${branch##*.}"
    if [[ -z "$want" ]] && (( major > 8 || (major == 8 && minor > 5) )); then
        good "PHP $v is newer than the branches this installer knows about; nothing to say"
        return 0
    fi
    if rpm -q --changelog php-fpm 2>/dev/null | grep -qi 'CVE-2026-109618\|CVE-2026-109619'; then
        good "PHP $v — the distribution's own changelog names the php2shell fix"
    elif [[ -z "$want" ]]; then
        warn "PHP $v is on a branch upstream does not publish for (8.1 and older). php2shell (CVE-2026-109618, CVE-2026-109619, both 9.2) is reached by one request before any page runs — move to 8.2.35 / 8.3.36 / 8.4.27 / 8.5.12 or newer, or make sure this distribution carries the backport"
    elif (( patch < want )); then
        warn "PHP $v has the two php2shell holes (CVE-2026-109618, CVE-2026-109619, both 9.2). One request from anybody who can reach php-fpm is enough, and it is acted on before any page of the dashboard runs. Update to $branch.$want or newer: dnf update php php-fpm && systemctl restart php-fpm"
        warn "until then, 'pm.max_requests = 1' in /etc/php-fpm.d/www.conf retires a worker after every request, which is what the second of the two needs to survive — at the cost of a fork per request"
    else
        good "PHP $v carries the php2shell fix"
    fi
}

# The dashboard holds one php-fpm worker per open tab (the live wait) and
# fires a dozen requests when a page opens. The stock pool keeps five idle
# workers, so an opening page makes php-fpm fork the rest first - each fork
# is a visible pause. More idle workers, and the opcode cache so index.php
# is not recompiled on every request.
tune_php_fpm() {
    local conf=/etc/php-fpm.d/www.conf
    [[ -f "$conf" ]] || return 0
    if ! grep -q '^pm.start_servers = 8' "$conf"; then
        [[ -f "$conf.bak" ]] || cp -a "$conf" "$conf.bak"
        sed -i 's/^pm.max_children = .*/pm.max_children = 50/; s/^pm.start_servers = .*/pm.start_servers = 8/; s/^pm.min_spare_servers = .*/pm.min_spare_servers = 6/; s/^pm.max_spare_servers = .*/pm.max_spare_servers = 24/' "$conf"
        good "php-fpm pool: 8 workers ready, 6-24 kept idle"
    fi
    if ! rpm -q php-opcache >/dev/null 2>&1; then
        dnf install -y -q php-opcache >/dev/null 2>&1 && good "php-opcache installed" || warn "php-opcache could not be installed; the dashboard's PHP is recompiled on every request"
    fi
}

check_certificate() {
    [[ -n "$WITH_WEB" ]] || return 0
    step "TLS certificate"
    local cert="$CERT_DIR/$CERT_FILE" key="$CERT_DIR/$KEY_FILE" ca="$CERT_DIR/$CA_FILE"
    [[ "$CERT_FILE" == /* ]] && cert="$CERT_FILE"
    [[ "$KEY_FILE" == /* ]] && key="$KEY_FILE"
    [[ "$CA_FILE" == /* ]] && ca="$CA_FILE"
    if [[ -n "$DRY_RUN" ]] && { [[ ! -f "$cert" ]] || [[ ! -f "$key" ]]; }; then
        warn "[dry run] $cert / $key not found here; the real run needs them"
        CERT_FILE="$cert"; KEY_FILE="$key"; CA_FILE="$ca"
        return
    fi
    [[ -f "$cert" ]] || fail "certificate $cert not found — put it in $CERT_DIR or pass --cert"
    [[ -f "$key" ]] || fail "key $key not found — pass --key"
    CERT_FILE="$cert"; KEY_FILE="$key"
    if [[ -f "$ca" ]]; then CA_FILE="$ca"; else CA_FILE=""; warn "no CA file $ca; OCSP stapling will be left off"; fi
    if command -v openssl >/dev/null; then
        local subject
        subject="$(openssl x509 -in "$cert" -noout -subject 2>/dev/null | sed 's/^subject=//')"
        good "$cert — $subject"
        if ! openssl x509 -in "$cert" -noout -checkend 0 >/dev/null 2>&1; then
            warn "the certificate has expired"
        fi
        local cmod kmod
        cmod="$(openssl x509 -in "$cert" -noout -modulus 2>/dev/null | md5sum)"
        kmod="$(openssl rsa -in "$key" -noout -modulus 2>/dev/null | md5sum)"
        if [[ -n "$cmod" ]] && [[ -n "$kmod" ]] && [[ "$cmod" != "$kmod" ]]; then
            warn "the key does not seem to belong to the certificate"
        fi
        if ! openssl x509 -in "$cert" -noout -ext subjectAltName 2>/dev/null | grep -q "$SERVER_NAME"; then
            warn "the certificate does not list $SERVER_NAME in its SAN; browsers will complain"
        fi
    fi
}

configure_nginx() {
    [[ -n "$WITH_WEB" ]] || return 0
    step "nginx"
    if [[ -n "$DRY_RUN" ]]; then
        note "[would write] $NGINX_CONF for $SERVER_NAME, allowing $ALLOW_FROM"
        return
    fi
    local allow_lines="" cidr
    IFS=',' read -r -a cidrs <<< "$ALLOW_FROM"
    for cidr in "${cidrs[@]}"; do
        cidr="$(echo "$cidr" | xargs)"
        [[ -n "$cidr" ]] && allow_lines+="    allow $cidr;"$'\n'
    done
    python3 - "$SOURCE_DIR/deploy/nginx-zigmon.conf" "$NGINX_CONF" "$SERVER_NAME" "$CERT_FILE" "$KEY_FILE" "$CA_FILE" "$allow_lines" "$HTPASSWD_USER" <<'EOF'
import re, sys
src, dst, name, cert, key, ca, allow, htuser = sys.argv[1:9]
text = open(src).read()
text = text.replace('mqtt.falco81.net', name)
text = re.sub(r'ssl_certificate\s+\S+;', 'ssl_certificate           %s;' % cert, text)
text = re.sub(r'ssl_certificate_key\s+\S+;', 'ssl_certificate_key       %s;' % key, text)
if ca:
    text = re.sub(r'ssl_trusted_certificate\s+\S+;', 'ssl_trusted_certificate   %s;' % ca, text)
else:
    text = re.sub(r'\n\s*ssl_trusted_certificate[^\n]*', '', text)
    text = re.sub(r'\n\s*ssl_stapling(_verify)?\s+on;', '', text)
    text = re.sub(r'\n\s*resolver[^\n]*', '', text)
text = re.sub(r'(    allow [^\n]*\n)+', allow, text, count=1)
if htuser:
    text = text.replace('    # auth_basic           "Sensors";', '    auth_basic           "Sensors";')
    text = text.replace('    # auth_basic_user_file /etc/nginx/zigmon.htpasswd;', '    auth_basic_user_file /etc/nginx/zigmon.htpasswd;')
open(dst, 'w').write(text)
EOF
    if [[ -n "$HTPASSWD_USER" ]]; then
        if [[ ! -f /etc/nginx/zigmon.htpasswd ]] || ! grep -q "^$HTPASSWD_USER:" /etc/nginx/zigmon.htpasswd; then
            say "password for $HTPASSWD_USER in the browser:"
            htpasswd -B ${ASSUME_YES:+-b} -c /etc/nginx/zigmon.htpasswd "$HTPASSWD_USER" ${ASSUME_YES:+"$PIN"} \
                || fail "htpasswd failed"
        fi
        chown root:nginx /etc/nginx/zigmon.htpasswd; chmod 640 /etc/nginx/zigmon.htpasswd
    fi
    if grep -qE '^\s*listen\s+80\s+default_server' /etc/nginx/nginx.conf 2>/dev/null; then
        warn "nginx.conf still has a default server on port 80; it may catch http://$SERVER_NAME before the redirect does"
    fi
    nginx -t >/dev/null 2>&1 || { nginx -t; fail "nginx rejects the configuration"; }
    systemctl enable --now nginx >/dev/null 2>&1 || true
    systemctl reload nginx
    good "$NGINX_CONF, reloaded"
}

configure_selinux() {
    command -v getenforce >/dev/null || return 0
    [[ "$(getenforce)" == "Disabled" ]] && { note "SELinux is disabled; nothing to do"; return 0; }
    step "SELinux"
    # PHP talks to the daemon on 127.0.0.1:9849, which is not a labelled http port.
    [[ -n "$WITH_WEB" ]] && run setsebool -P httpd_can_network_connect 1
    if command -v semanage >/dev/null; then
        run semanage fcontext -a -t httpd_sys_content_t "$WEB_DIR(/.*)?" 2>/dev/null || true
        run restorecon -R "$WEB_DIR" 2>/dev/null || true
    fi
    good "done"
}

configure_firewall() {
    [[ -n "$WITH_WEB" ]] || return 0
    command -v firewall-cmd >/dev/null || return 0
    systemctl is-active firewalld >/dev/null 2>&1 || { note "firewalld is not running"; return 0; }
    step "Firewall"
    run firewall-cmd --permanent --add-service=http
    run firewall-cmd --permanent --add-service=https
    [[ -n "$SENSOR_LISTEN" ]] && run firewall-cmd --permanent --add-port="$SENSOR_PORT/tcp"
    run firewall-cmd --reload
    good "http and https open"
}

start_service() {
    step "Starting the daemon"
    run systemctl enable zigmon
    run systemctl restart zigmon
    [[ -n "$DRY_RUN" ]] && return
    sleep 3
    if systemctl is-active zigmon >/dev/null; then
        good "zigmon.service is running"
    else
        journalctl -u zigmon -n 20 --no-pager
        fail "zigmon.service did not start"
    fi
}

verify() {
    [[ -n "$DRY_RUN" ]] && return
    step "Checking"
    if "$BIN_LINK" --check --no-color; then
        good "healthy"
    else
        warn "the check reported problems (see above)"
    fi
    if [[ -n "$WITH_WEB" ]]; then
        local code
        code="$(curl -sk -o /dev/null -w '%{http_code}' --resolve "$SERVER_NAME:443:127.0.0.1" "https://$SERVER_NAME/?api=health" \
                ${HTPASSWD_USER:+-u "$HTPASSWD_USER:$PIN"} 2>/dev/null || echo 000)"
        if [[ "$code" == "200" ]]; then
            good "the dashboard answers over https"
        else
            warn "the dashboard returned HTTP $code — check: systemctl status nginx php-fpm; tail /var/log/nginx/zigmon-error.log"
        fi
    fi
}

summary() {
    step "Done"
    [[ -n "$WITH_WEB" ]] && say "Dashboard   https://$SERVER_NAME/"
    say "Service     systemctl status zigmon"
    say "Log         journalctl -u zigmon -f    or  /var/log/zigmon/zigmon.log"
    say "Config      $CONFIG_FILE"
    say "Health      zigmon --check    and    zigmon --diag"
    say "Live feed   zigmon --watch"
    say "Plugs       add them to $CONFIG_FILE under \"plugs\", then: systemctl restart zigmon"
    say "Shelly      zigmon shelly --help    (discover, info, dump, config, ble, matter, call ...)"
    # the daemon makes the first account when it starts with none: a moment
    local _w
    for _w in 1 2 3 4 5 6 7 8 9 10; do
        [[ -n "$DRY_RUN" || -f /var/lib/zigmon/first-login.txt ]] && break
        [[ -n "$(sqlite3 /var/lib/zigmon/history.db 'SELECT 1 FROM accounts LIMIT 1' 2>/dev/null || true)" ]] && break
        sleep 1
    done
    if [[ -f /var/lib/zigmon/first-login.txt ]]; then
        echo
        note "Sign in to the dashboard as admin; the first password is in /var/lib/zigmon/first-login.txt"
        note "(root only), and is changed at the first sign-in. More accounts: Settings - Access,"
        note "or sudo zigmon --account-add NAME operator"
    fi
    if [[ -n "$SENSOR_LISTEN" ]]; then
        echo
        note "Battery sensors push here: http://$(hostname -I 2>/dev/null | awk '{print $1}'):$SENSOR_PORT/?t=\${ev.tC}&rh=\${ev.rh}&id=NAME"
        note "Create the webhook on the sensor once:  zigmon shelly --host <ip> call Webhook.Create '{...}'"
    fi
    if [[ -z "$CREATE_MQTT_USER" ]]; then
        echo
        note "The broker account \"$MQTT_USER\" must exist with these rights:"
        note "  topic read  $BASE_TOPIC/#"
        note "  topic write $BASE_TOPIC/bridge/request/#     (permit join from the dashboard)"
        note "  topic read  shellies/#                         (if Shelly WiFi devices publish there)"
    fi
}

# ---------------------------------------------------------------------------
# Upgrade / uninstall
# ---------------------------------------------------------------------------
# Which deploy/ files changed in which release, and why. Kept by hand,
# because the only thing worth telling somebody is what WE changed since the
# version they are running - not how their own config differs from the
# packaged one, which it always will: a running house has its own addresses,
# its own allow rules and its own certificates in those files, and saying so
# every time teaches people to skip the message.
#
# One line per release that touched deploy/, oldest first:
#     <version>|<file>|<what changed, in a few words>
DEPLOY_CHANGES="
4.6.2|nginx-tap-front.conf|a default server that refuses anything asked for by address
4.6.3|nginx-tap-front.conf|the default blocks write to the log the house reads, so what they refuse is weighed
4.6.4|nginx-tap-front.conf|a refusal no longer names the header it wants
4.7.3|nginx-ntfy-front.conf|new: ntfy published under a name of its own
4.8.2|ntfy-server.yml|new: a private ntfy, shut properly
4.9.1|ntfy-server.yml|upstream-base-url, without which an iPhone is never woken
4.13.1|nginx-ntfy-front.conf|a rate limit, a limit on methods, and a body limit
4.19.1|nginx-ntfy-front.conf|moved from a port of its own to a name of its own
4.29.0|ntfy-server.yml|log-file is set, so the house can read what ntfy says - rotate it, see the note
4.30.0|ntfy.logrotate|new: rotates ntfy's own two files without taking them away from ntfy
4.33.0|nginx-tap-front.conf|a full JSON log of every request at /tap - body, headers, times - for the weighing to read
4.34.0|nginx-ntfy-front.conf|the same full JSON log for the ntfy name, weighed by its own rules
4.35.0|nginx-tap-front.conf|the full log is written for every request, not only the one road
4.35.0|nginx-ntfy-front.conf|its full log moved into the location, so the TLS fields are filled in
4.35.0|ntfy.logrotate|rotates the two full logs as well - they are the biggest of the lot
4.36.1|nginx-tap-front.conf|says how to log the secret itself, and what that costs, for anyone who wants it
4.36.2|nginx-ntfy-front.conf|the full line for requests turned away before they reach the location, too
4.40.0|suricata-on-the-proxy.md|new: how to put Suricata on the proxy so the house can read what it saw
4.41.2|suricata.yaml|new: the working config from a real Alma 9 proxy, beside the note
4.44.0|suricata.yaml|tls turned on, for the fingerprints - and the packet option written down
4.44.4|suricata.yaml|the fingerprinting itself turned on - asking for it in eve-log was not enough
4.47.2|nginx-zigmon.conf|a road of its own for the SMS gateway's pushed messages, shut to everybody else
5.17.0|nginx-zigmon.conf|/tap hands PHP api=tap and nothing else (it handed on the whole query); the tap rate limit counts the last X-Forwarded-For address
5.17.0|nginx-tap-front.conf|the full log says whether a cookie or an Authorization header was sent, not what it was; /tap drops the query
5.17.0|nginx-ntfy-front.conf|the full log says whether a cookie was sent, not what it was
"

report_deploy_changes() {
    local had="$1"
    step "What changed in deploy/ since the version you were running"
    if [[ -z "$had" ]]; then
        note "could not tell which version was here before, so nothing is compared"
        return
    fi
    local said="" line version file what
    while IFS='|' read -r version file what; do
        [[ -n "$version" ]] || continue
        # is this release newer than the one that was installed?
        # anything at or before the version that was already here is not news
        if [[ "$version" == "$had" ]]; then
            continue
        fi
        if [[ "$(printf '%s\n%s\n' "$version" "$had" | sort -V | head -n 1)" == "$version" ]]; then
            continue
        fi
        warn "$file - $what"
        note "    packaged: $SOURCE_DIR/deploy/$file"
        local live
        live="$(deploy_live_path "$file")"
        [[ -n "$live" ]] && note "    yours:    $live"
        said="yes"
    done <<< "$DEPLOY_CHANGES"
    if [[ -z "$said" ]]; then
        good "nothing in deploy/ has changed since $had"
    else
        note "None of these were written over: a config on a running house has its own names,"
        note "addresses and certificates in it. Look at the packaged one and take what you want."
    fi
}

deploy_live_path() {
    case "$1" in
        zigmon.service)        echo "/etc/systemd/system/zigmon.service" ;;
        zigmon.logrotate)      echo "/etc/logrotate.d/zigmon" ;;
        nginx-zigmon.conf)     echo "$NGINX_CONF" ;;
        nginx-tap-front.conf)  echo "/etc/nginx/conf.d/zigmon-tap.conf" ;;
        nginx-ntfy-front.conf) echo "/etc/nginx/conf.d/zigmon-ntfy.conf" ;;
        ntfy-server.yml)       echo "/etc/ntfy/server.yml" ;;
        ntfy.logrotate)        echo "/etc/logrotate.d/ntfy" ;;
        suricata-on-the-proxy.md) echo "" ;;   # something to read, not something to install
        suricata.yaml)         echo "/etc/suricata/suricata.yaml" ;;
        config.json)           echo "$CONFIG_FILE" ;;
        *)                     echo "" ;;
    esac
}

do_upgrade() {
    local had=""
    if [[ -f "$LIB_DIR/zigmon.py" ]]; then
        had="$(sed -n "s/^__version__ = '\(.*\)'/\1/p" "$LIB_DIR/zigmon.py" | head -n 1)"
    fi
    preflight
    install_program
    install_service          # the unit changes with the program; a reload is cheap
    install_helpers
    install_time_tools
    install_console
    allow_broker_reload
    install_backup_tools     # 5.21: ssh and smbclient for the backups to other machines
    [[ -n "$WITH_WEB" ]] && [[ -d "$WEB_DIR" ]] && {
        step "Dashboard files"
        run install -m 644 "$SOURCE_DIR/web/index.php" "$WEB_DIR/index.php"
        run install -m 644 "$SOURCE_DIR/web/zigmon-api.php" "$WEB_DIR/zigmon-api.php"
        run install -m 644 "$SOURCE_DIR/web/favicon.svg" "$WEB_DIR/favicon.svg"
        good "$WEB_DIR"
        # 2.23: backup uploads travel in pieces of a few MB; the old 16k cap would block them
        if [[ -f "$NGINX_CONF" ]] && grep -Eq 'client_max_body_size +[0-9]+[kK]?;' "$NGINX_CONF"; then
            run sed -Ei 's/client_max_body_size +[0-9]+[kK]?;/client_max_body_size 6m;/' "$NGINX_CONF"
            if nginx -t >/dev/null 2>&1; then run systemctl reload nginx; good "nginx: client_max_body_size raised to 6m"; else warn "nginx config test failed after raising client_max_body_size; check $NGINX_CONF"; fi
        fi
        # 2.58.1: compress the JSON the dashboard fetches on every live update
        if [[ -f "$NGINX_CONF" ]] && ! grep -q '^\s*gzip on;' "$NGINX_CONF" && grep -q 'client_max_body_size' "$NGINX_CONF"; then
            run sed -i '0,/client_max_body_size/s//gzip on;\n    gzip_types application\/json text\/html text\/css application\/javascript image\/svg+xml;\n    gzip_min_length 1024;\n    gzip_vary on;\n    client_max_body_size/' "$NGINX_CONF"
            if nginx -t >/dev/null 2>&1; then run systemctl reload nginx; good "nginx: gzip enabled for the dashboard"; else warn "nginx config test failed after adding gzip; check $NGINX_CONF"; fi
        fi
        # 3.54: the header road for the one-tap links - one address, the
        # secret in a header of a POST, nothing of it in this log. Written
        # whole rather than patched line by line: 3.54.0 shipped it refusing a
        # browser with a bare 403 and 3.54.1 with default_type inside an if,
        # which nginx will not start with. One block, put right whatever is
        # there now.
        # Duo's own package, if the links are set to ask Duo to approve them.
        # The daemon can sign for itself and says so, but that is four ways of
        # signing kept in step with somebody else's API by hand; theirs is the
        # reference.
        if python3 -c 'import duo_client' >/dev/null 2>&1; then
            good "duo_client present: Duo requests go through Duo's own package"
        else
            note "duo_client not installed - only needed if a one-tap link asks Duo to approve it (pip3 install duo-client)"
        fi
        # The one-tap roads. What is already there is left exactly as it is:
        # a config on a running house has been edited by hand - its own
        # addresses, its own allow rules, a server in front - and an installer
        # that writes its idea of the block over that does damage every time
        # it runs. So: missing, add the one from this package; present, say
        # nothing at all unless it differs from the packaged one, and then
        # only say so.
        #
        # And nothing is left broken: the file is copied first, and if nginx
        # refuses the result the copy goes back.
        if [[ -f "$NGINX_CONF" ]]; then
            local tap_state
            # the copy that goes back if nginx refuses what comes out
            cp -a "$NGINX_CONF" "$NGINX_CONF.zigmon-before" 2>/dev/null || true
            tap_state="$(python3 - "$NGINX_CONF" "$SOURCE_DIR/deploy/nginx-zigmon.conf" <<'PATCH'
import sys


def block_of(text, head):
    """The whole of one location, braces counted rather than guessed: the
    tap block holds an if block of its own, and looking for the first "\n    }"
    cut the file in half at that one."""
    at = text.find(head)
    if at < 0:
        return ''
    depth, i = 0, text.index('{', at)
    for j in range(i, len(text)):
        if text[j] == '{':
            depth += 1
        elif text[j] == '}':
            depth -= 1
            if depth == 0:
                return text[at:j + 1]
    return ''


live_path, shipped_path = sys.argv[1], sys.argv[2]
live = open(live_path).read()
try:
    shipped = open(shipped_path).read()
except OSError:
    shipped = ''

head = '    location = /tap {'
here, theirs = block_of(live, head), block_of(shipped, head)


def tidy(block):
    return '\n'.join(l.strip() for l in block.splitlines()
                     if l.strip() and not l.strip().startswith('#'))


if here:
    print('same' if tidy(here) == tidy(theirs) else 'theirs')
    raise SystemExit(0)
if not theirs:
    print('nothing-to-add')
    raise SystemExit(0)

# it is missing: add the zone it leans on, then the block itself
zone = 'limit_req_zone $binary_remote_addr zone=zigmon_tap:1m rate=60r/m;'
if 'zone=zigmon_tap' not in live.split('server {')[0]:
    at = live.index('server {')
    live = live[:at] + zone + '\n\n' + live[at:]
mark = '    location ~ "^/tap/'
if mark in live:
    live = live.replace(mark, theirs + '\n\n' + mark, 1)
else:
    at = live.rindex('}')
    live = live[:at] + theirs + '\n}' + live[at + 1:]
open(live_path, 'w').write(live)
print('added')
PATCH
)" || tap_state="failed"
            case "$tap_state" in
                same)   : ;;                      # already what this ships: nothing to say
                theirs) note "nginx: your own location = /tap is kept as it is (it differs from the one in this package)" ;;
                added)
                    if nginx -t >/dev/null 2>&1; then
                        run systemctl reload nginx
                        good "nginx: the one-tap header road is open at /tap"
                    else
                        warn "nginx refused the config after adding location = /tap; put back as it was"
                        run cp -a "$NGINX_CONF.zigmon-before" "$NGINX_CONF"
                    fi ;;
                *)      warn "nginx: could not read $NGINX_CONF to see whether /tap is there" ;;
            esac
        fi
        if [[ -f "$NGINX_CONF" ]] && ! grep -q 'client_max_body_size' "$NGINX_CONF"; then
            warn "$NGINX_CONF has no client_max_body_size; nginx's default 1m caps backup uploads - add 'client_max_body_size 6m;' to the server block"
        fi
        # php2shell (CVE-2026-109618, CVE-2026-109619, 21 October 2026): one
        # of the two is reached through PHP's own multipart parser, before any
        # page of the dashboard runs. Nothing here ever sends a multipart body
        # - every file picker on the page is read in the browser - so the
        # shape is refused in front of PHP. Added to a config that was
        # installed before this version existed, the same careful way as the
        # one-tap road above: written, tested, reloaded, and put back exactly
        # as it was if nginx will not have it.
        if [[ -f "$NGINX_CONF" ]] && [[ -z "$DRY_RUN" ]] \
                && ! grep -q 'content_type.*multipart' "$NGINX_CONF"; then
            cp -a "$NGINX_CONF" "$NGINX_CONF.zigmon-before-multipart"
            if python3 - "$NGINX_CONF" <<'MPATCH'
import re, sys
path = sys.argv[1]
text = open(path).read()
line = ('\n    # php2shell (CVE-2026-109618, CVE-2026-109619): PHP\'s own multipart\n'
        '    # parser is one of the two ways in, and nothing in this dashboard ever\n'
        '    # sends a multipart body - every file picker on the page is read in the\n'
        '    # browser and sent as JSON. Refused in front of PHP; costs nothing here.\n'
        '    if ($http_content_type ~* "^multipart/") { return 415; }\n')
# after client_max_body_size where there is one, otherwise before the first
# location of the server block - never inside a location, where it would
# cover one road and leave the rest open
at = text.find('client_max_body_size')
if at >= 0:
    at = text.index('\n', at) + 1
else:
    at = text.find('\n    location ')
    if at < 0:
        print('nowhere')
        raise SystemExit(1)
    at += 1
open(path, 'w').write(text[:at] + line + text[at:])
print('added')
MPATCH
            then
                if nginx -t >/dev/null 2>&1; then
                    run systemctl reload nginx
                    good "nginx now refuses multipart bodies in front of PHP (php2shell)"
                else
                    warn "nginx refused the config after adding the multipart rule; put back as it was"
                    run cp -a "$NGINX_CONF.zigmon-before-multipart" "$NGINX_CONF"
                fi
            else
                warn "could not find a place in $NGINX_CONF for the multipart rule; add by hand to the server block: if (\$http_content_type ~* \"^multipart/\") { return 415; }"
            fi
        fi
    }
    run install -m 644 "$SOURCE_DIR/deploy/zigmon.service" "$UNIT_FILE"
    run systemctl daemon-reload
    if [[ -z "$DRY_RUN" ]] && [[ -f /etc/php-fpm.d/www.conf ]]; then
        tune_php_fpm                     # 2.65: idle workers + opcache for the dashboard
        harden_php                       # 5.15: php2shell, and the version that mends it
        systemctl restart php-fpm >/dev/null 2>&1 || true
    fi
    start_service
    verify
    report_deploy_changes "$had"
}

do_uninstall() {
    [[ $EUID -eq 0 ]] || fail "run this as root"
    step "Removing zigmon (history in /var/lib/zigmon is kept)"
    run systemctl disable --now zigmon 2>/dev/null || true
    run systemctl disable --now zigmon-root.path zigmon-upgrade.path 2>/dev/null || true
    run rm -f /etc/systemd/system/zigmon-root.path /etc/systemd/system/zigmon-root.service \
        /etc/systemd/system/zigmon-upgrade.path /etc/systemd/system/zigmon-upgrade.service
    run rm -f /etc/sudoers.d/zigmon
    run rm -f /etc/profile.d/zz-zigmon-console.sh /etc/zigmon-console-login
    run rm -f "$UNIT_FILE" "$LOGROTATE_FILE" "$BIN_LINK"
    run rm -rf "$LIB_DIR" "$WEB_DIR"
    if [[ -f "$NGINX_CONF" ]]; then
        run rm -f "$NGINX_CONF"
        run systemctl reload nginx 2>/dev/null || true
    fi
    run systemctl daemon-reload
    good "removed. Left in place: $CONFIG_DIR, /var/lib/zigmon, /var/log/zigmon, the $SERVICE_USER user"
    note "and the backups of the whole installation in /var/backups/zigmon, with the key that seals them in /var/lib/zigmon-root"
    note "rules zigmon put in the firewall stay too: turn them off on the dashboard first (Firewall and access) if you want them gone"
}

# ---------------------------------------------------------------------------
main() {
    if [[ -n "$DO_UNINSTALL" ]]; then do_uninstall; exit 0; fi
    if [[ -n "$DO_UPGRADE" ]]; then do_upgrade; exit 0; fi
    preflight
    gather_answers
    install_packages
    install_backup_tools
    create_user
    install_program
    write_config
    create_mqtt_user
    allow_broker_reload
    install_service
    install_helpers
    install_time_tools
    install_console
    install_web
    check_certificate
    configure_nginx
    configure_selinux
    configure_firewall
    start_service
    verify
    summary
}
main
