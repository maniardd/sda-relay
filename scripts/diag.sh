#!/bin/bash
# diag.sh — One-command Phase X diagnostic + Gist upload
#
# Usage:
#   ./diag.sh                  # just current state, no deploy
#   ./diag.sh phase1           # trigger Phase 1 + capture
#   ./diag.sh phase2           # ... etc
#   ./diag.sh wipe-isis        # wipe interface ISIS+PIM augments
#
# Prints a single Gist URL when done. Paste that to Copilot.

set -e
cd /opt/sda-relay

# Load token
[ ! -f .env-gist ] && { echo "ERROR: /opt/sda-relay/.env-gist missing (need GITHUB_TOKEN=...)"; exit 1; }
source .env-gist
[ -z "$GITHUB_TOKEN" ] && { echo "ERROR: GITHUB_TOKEN empty"; exit 1; }

# Switch creds (override via env if needed)
BORDER_IP=${BORDER_IP:-192.168.128.9}
EDGE_IP=${EDGE_IP:-192.168.128.7}
SW_USER=${SW_USER:-admin}
SW_PASS=${SW_PASS:-C1scolab123!}

ACTION=${1:-status}
LOG=/tmp/diag-$(date +%Y%m%d-%H%M%S).log
exec > >(tee -a "$LOG") 2>&1

echo "=========================================="
echo "## diag.sh action=$ACTION at $(date)"
echo "=========================================="
echo "Border=$BORDER_IP Edge=$EDGE_IP"

restconf_get() {
    local ip=$1 path=$2 label=$3
    echo ""
    echo "--- GET [$label] $ip $path"
    curl -sk -u "$SW_USER:$SW_PASS" -H "Accept: application/yang-data+json" \
        -o /dev/stdout -w "\nHTTP=%{http_code}\n" \
        "https://$ip/restconf/data/$path"
}

# ── Action: trigger phase ─────────────────────────────────────────────
case "$ACTION" in
  phase1|phase2|phase3|phase4|phase5)
    PH=${ACTION#phase}
    case $PH in
      1) ENDPOINT="phase1-underlay" ;;
      2) ENDPOINT="phase2-lisp" ;;
      3) ENDPOINT="phase3-vxlan-vni" ;;
      4) ENDPOINT="phase4-vrf-bgp" ;;
      5) ENDPOINT="phase5-access" ;;
    esac
    echo ""
    echo "## Truncating relay log"
    : > /tmp/sda-relay.log

    echo ""
    echo "## Triggering /api/v2/deploy/$ENDPOINT"
    curl -s -X POST http://127.0.0.1:5000/api/v2/deploy/$ENDPOINT \
        -H "Content-Type: application/json" -d '{}' | head -c 4000
    echo ""

    echo ""
    echo "## Sleeping 5s for relay to flush log"
    sleep 5

    echo ""
    echo "## Relay log — full"
    cat /tmp/sda-relay.log
    ;;
  wipe-isis)
    echo ""
    echo "## Wiping ISIS process + interface augments"
    for ip in "$BORDER_IP" "$EDGE_IP"; do
      curl -sk -u "$SW_USER:$SW_PASS" -X DELETE -w "DELETE isis@$ip HTTP=%{http_code}\n" \
        "https://$ip/restconf/data/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-isis:isis-container" || true
    done
    ;;
  status)
    echo ""
    echo "## Last 100 lines of relay log"
    tail -100 /tmp/sda-relay.log 2>/dev/null || echo "(no log yet)"
    ;;
esac

# ── Always: capture device state ──────────────────────────────────────
echo ""
echo "=========================================="
echo "## DEVICE STATE — RESTCONF GETs"
echo "=========================================="
restconf_get "$BORDER_IP" "Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-isis:isis-container?depth=unbounded" "border-isis"
restconf_get "$BORDER_IP" "Cisco-IOS-XE-native:native/ip/Cisco-IOS-XE-multicast:mcr-conf" "border-multicast"
restconf_get "$BORDER_IP" "Cisco-IOS-XE-native:native/ip/pim" "border-pim"
restconf_get "$BORDER_IP" "Cisco-IOS-XE-native:native/interface/Loopback=0?depth=unbounded" "border-lo0"
restconf_get "$BORDER_IP" "Cisco-IOS-XE-native:native/interface/Loopback=60000?depth=unbounded" "border-lo60000"
restconf_get "$BORDER_IP" "Cisco-IOS-XE-native:native/interface/TwentyFiveGigE=1%2F0%2F2?depth=unbounded" "border-p2p"
restconf_get "$EDGE_IP"   "Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-isis:isis-container?depth=unbounded" "edge-isis"
restconf_get "$EDGE_IP"   "Cisco-IOS-XE-native:native/interface/Loopback=0?depth=unbounded" "edge-lo0"
restconf_get "$EDGE_IP"   "Cisco-IOS-XE-native:native/interface/GigabitEthernet=1%2F0%2F2?depth=unbounded" "edge-p2p"

echo ""
echo "=========================================="
echo "## ISIS adjacency / routing (oper)"
echo "=========================================="
restconf_get "$BORDER_IP" "Cisco-IOS-XE-isis-oper:isis-oper-data?depth=3" "border-isis-oper"

echo ""
echo "## Versions of relay payload + server (git)"
git log --oneline -3

# ── Upload to Gist ────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "## Uploading to Gist..."
echo "=========================================="

DESC="SDA diag $ACTION $(hostname) $(date -u +%Y-%m-%dT%H:%M:%SZ)"
FNAME="diag-$(basename $LOG)"

# Build payload using Python (no jq needed) and post in one shot
URL=$(python3 - <<PYEOF
import json, os, sys, urllib.request

with open("$LOG", "r", errors="replace") as f:
    content = f.read()

payload = {
    "description": "$DESC",
    "public": False,
    "files": {"$FNAME": {"content": content}},
}
data = json.dumps(payload).encode("utf-8")

req = urllib.request.Request(
    "https://api.github.com/gists",
    data=data,
    headers={
        "Authorization": "Bearer ${GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "sda-diag/1.0",
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    print(body.get("html_url", ""))
except urllib.error.HTTPError as e:
    sys.stderr.write("HTTP %s: %s\n" % (e.code, e.read().decode("utf-8", "replace")[:500]))
    sys.exit(2)
except Exception as e:
    sys.stderr.write("ERR: %s\n" % e)
    sys.exit(2)
PYEOF
)

if [ -z "$URL" ]; then
    echo ""
    echo "GIST UPLOAD FAILED. Local log saved at: $LOG"
    exit 2
fi

echo ""
echo "=========================================="
echo "  ✓ DONE — paste this URL to Copilot:"
echo ""
echo "  $URL"
echo ""
echo "=========================================="
