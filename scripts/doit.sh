#!/bin/bash
# ~/doit.sh — symlinks to /opt/sda-relay/scripts/doit.sh, kept in repo so
# auto-pull always brings in the latest version. Single-command end-to-end.
#
# Usage:  ~/doit.sh                # default = phase1
#         ~/doit.sh phase1
#         ~/doit.sh status
#
set -u
ACTION="${1:-phase1}"

cd /opt/sda-relay

echo "===== [1/4] git pull ====="
git fetch origin main 2>&1 | tail -3
git reset --hard origin/main 2>&1 | tail -3
chmod +x /opt/sda-relay/scripts/*.sh
echo "HEAD: $(git log --oneline -1)"

echo "===== [2/4] restart gunicorn ====="
pkill -f 'gunicorn.*sda_relay_server_v2' 2>/dev/null || true
sleep 2
nohup /opt/sda-relay/venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 --timeout 120 \
    sda_relay_server_v2:app > /tmp/sda-relay.log 2>&1 &
disown
sleep 3
PIDS=$(pgrep -f 'gunicorn.*sda_relay_server_v2' | tr '\n' ' ')
echo "Gunicorn PIDs: $PIDS"
curl -s http://127.0.0.1:5000/health && echo ""

echo "===== [3/4] run diag $ACTION ====="
exec /opt/sda-relay/scripts/diag.sh "$ACTION"
