#!/bin/bash
# Auto-pull: runs every 30s via cron. If GitHub has new commits, pull + restart relay.
# Install: crontab -e   →   * * * * * /opt/sda-relay/scripts/auto-pull.sh
#                            * * * * * sleep 30; /opt/sda-relay/scripts/auto-pull.sh

set -e
cd /opt/sda-relay
LOCK=/tmp/sda-autopull.lock
[ -f "$LOCK" ] && exit 0
trap "rm -f $LOCK" EXIT
touch "$LOCK"

LOCAL=$(git rev-parse HEAD)
git fetch origin main -q
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "[$(date)] New commit detected: $LOCAL -> $REMOTE" >> /tmp/auto-pull.log
    git reset --hard origin/main >> /tmp/auto-pull.log 2>&1

    # Restart gunicorn
    pkill -f 'gunicorn.*sda_relay_server_v2' || true
    sleep 2
    nohup /opt/sda-relay/venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 --timeout 120 \
        sda_relay_server_v2:app > /tmp/sda-relay.log 2>&1 &
    disown
    echo "[$(date)] Relay restarted at PID $!" >> /tmp/auto-pull.log
fi
