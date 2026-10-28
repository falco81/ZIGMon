# The zigmon console when root signs in (zigmon 5.21), installed as
# /etc/profile.d/zz-zigmon-console.sh. Switched with
# `zigmon --console-at-login on|off`; q in the console leaves it for this very
# shell (it is a child of it, nothing is exec'd), and `zigmon --console` opens
# it again. Nothing happens for a command run over SSH, scp/sftp, a shell that
# is not interactive, a shell opened from the console itself (ZIGMON_CONSOLE),
# or when ZIGMON_NO_CONSOLE is set (ssh -t host ZIGMON_NO_CONSOLE=1 bash -l).
# The flag is in /etc itself, where only root writes, and is read only when it
# is a plain file - never through a link.
if [ -n "${PS1:-}" ] && [ -t 0 ] && [ -t 1 ] && [ -z "${ZIGMON_CONSOLE:-}" ] \
   && [ -z "${ZIGMON_NO_CONSOLE:-}" ] && [ -z "${SSH_ORIGINAL_COMMAND:-}" ] \
   && [ "$(id -u 2>/dev/null)" = "0" ] && [ -x /usr/local/bin/zigmon ] \
   && [ -f /etc/zigmon-console-login ] && [ ! -L /etc/zigmon-console-login ] \
   && [ "$(head -c 3 /etc/zigmon-console-login 2>/dev/null)" = "on" ]; then
    export ZIGMON_CONSOLE=1
    /usr/local/bin/zigmon --console
fi
