#!/usr/bin/env bash
# One-shot deploy/restart for sda_relay_server_v3 on the Ubuntu VM.
# Run from /opt/sda-relay  (single paste, no interactive prompts):
#   bash scripts/deploy_v3.sh
#
# What it does:
#  1. git pull
#  2. pip install netmiko (idempotent)
#  3. kill any existing gunicorn on :5000
#  4. start gunicorn for sda_relay_server_v3:app
#  5. wait + curl /health to confirm
set -e

cd /opt/sda-relay

echo "==> git pull"
git fetch origin main
git reset --hard origin/main

echo "==> ensure venv"
[ -d venv ] || python3 -m venv venv
. venv/bin/activate

echo "==> pip install"
pip install -q -r requirements.txt
pip install -q gunicorn

echo "==> stop existing relay (if any)"
pkill -f "gunicorn.*sda_relay_server" || true
sleep 1

echo "==> start v3 relay"
nohup venv/bin/gunicorn sda_relay_server_v3:app \
  -b 0.0.0.0:5000 --timeout 180 --workers 2 \
  > relay.log 2>&1 &

sleep 2
echo "==> health check"
curl -s http://localhost:5000/health | head -c 400 ; echo

echo "==> ngrok URL (current):"
grep -oE 'https://[a-z0-9-]+\.ngrok-free\.dev' /opt/sda-relay/ngrok.log 2>/dev/null | tail -1 || echo "(ngrok log not found — start ngrok separately)"

echo "==> done."
