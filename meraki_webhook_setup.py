#!/usr/bin/env python3
"""
Meraki Webhook + Relay Infrastructure Setup
=============================================
Since the Workflows/Automation feature is not available on the org,
this script sets up a webhook-based deployment trigger system:

  1. Registers the relay server as a Webhook HTTP Server in Meraki
  2. Creates custom Payload Templates for each deployment phase
  3. Optionally sets up webhook alerts on the SJC23-SDA network
  4. Tests the webhook chain end-to-end

The flow:
  Dashboard Alert / Manual Trigger → Webhook → ngrok → Relay → RESTCONF → Switch

Usage:
  python meraki_webhook_setup.py --relay-url https://YOUR-NGROK-URL.ngrok-free.app
  python meraki_webhook_setup.py --relay-url https://YOUR-NGROK-URL.ngrok-free.app --setup-all
  python meraki_webhook_setup.py --list            # Show existing webhook config
  python meraki_webhook_setup.py --test             # Send test webhook
  python meraki_webhook_setup.py --cleanup          # Remove all webhook config
"""

import argparse
import json
import os
import sys
import time
import secrets

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required. Install: pip install requests")
    sys.exit(1)

# ── Configuration ────────────────────────────────────────────────────
MERAKI_API_KEY = os.environ.get("MERAKI_API_KEY", "1bbb81c532e97a19bbac32032009eeaaa264fe31")
ORG_ID = "135358"
NETWORK_ID = "L_591660401045811304"
NETWORK_NAME = "SJC23-SDA"
BASE_URL = "https://api.meraki.com/api/v1"

HEADERS = {
    "Authorization": f"Bearer {MERAKI_API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# Generate a shared secret for HMAC webhook verification
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "sda-relay-secret-" + secrets.token_hex(8))

# ── Deployment Phases ────────────────────────────────────────────────
DEPLOYMENT_PHASES = [
    {
        "name": "SDA Pre-Check",
        "endpoint": "/api/v2/precheck",
        "method": "POST",
        "description": "Validate switch reachability, IOS-XE version, and RESTCONF readiness"
    },
    {
        "name": "Phase 1 - Underlay (ISIS/BFD/PIM)",
        "endpoint": "/api/v2/deploy/phase1-underlay",
        "method": "POST",
        "description": "Deploy ISIS routing, BFD, PIM, and Loopback interfaces"
    },
    {
        "name": "Phase 1 - Verify Underlay",
        "endpoint": "/api/v2/verify/phase1-underlay",
        "method": "POST",
        "description": "Verify ISIS adjacencies and underlay connectivity"
    },
    {
        "name": "Phase 2 - LISP",
        "endpoint": "/api/v2/deploy/phase2-lisp",
        "method": "POST",
        "description": "Deploy LISP control plane (MS/MR/ETR/ITR roles)"
    },
    {
        "name": "Phase 2 - Verify LISP",
        "endpoint": "/api/v2/verify/phase2-lisp",
        "method": "POST",
        "description": "Verify LISP sessions and registrations"
    },
    {
        "name": "Phase 3 - VXLAN/VNI",
        "endpoint": "/api/v2/deploy/phase3-vxlan-vni",
        "method": "POST",
        "description": "Deploy VXLAN tunnels and VNI mappings"
    },
    {
        "name": "Phase 4 - VRF/BGP",
        "endpoint": "/api/v2/deploy/phase4-vrf-bgp",
        "method": "POST",
        "description": "Deploy VRF definitions and BGP EVPN peering"
    },
    {
        "name": "Phase 5 - Access Policies",
        "endpoint": "/api/v2/deploy/phase5-access",
        "method": "POST",
        "description": "Deploy VLANs, SVIs, and access port configurations"
    },
    {
        "name": "Phase 6 - Security",
        "endpoint": "/api/v2/deploy/phase6-security",
        "method": "POST",
        "description": "Deploy SGACL, CTS, and RADIUS integration"
    },
    {
        "name": "SDA Post-Check",
        "endpoint": "/api/v2/postcheck",
        "method": "POST",
        "description": "Full 22-point validation of deployed fabric"
    },
]


# ══════════════════════════════════════════════════════════════════════
#  WEBHOOK HTTP SERVER MANAGEMENT
# ══════════════════════════════════════════════════════════════════════

def list_http_servers():
    """List all webhook HTTP servers configured on the network."""
    url = f"{BASE_URL}/networks/{NETWORK_ID}/webhooks/httpServers"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        servers = resp.json()
        return servers
    print(f"  Error listing HTTP servers: {resp.status_code} {resp.text}")
    return []


def create_http_server(relay_url, name="SDA-Relay-Server"):
    """Register the relay server as a webhook HTTP server in Meraki."""
    url = f"{BASE_URL}/networks/{NETWORK_ID}/webhooks/httpServers"
    
    payload = {
        "name": name,
        "url": relay_url + "/api/v2/webhook",
        "sharedSecret": WEBHOOK_SECRET,
        "payloadTemplate": {"payloadTemplateId": "wpt_00001"}  # Default Meraki template
    }
    
    resp = requests.post(url, headers=HEADERS, json=payload)
    if resp.status_code in (200, 201):
        server = resp.json()
        print(f"  Created HTTP Server: {server['name']}")
        print(f"    ID: {server['id']}")
        print(f"    URL: {server['url']}")
        return server
    else:
        print(f"  Error creating HTTP server: {resp.status_code}")
        print(f"  {resp.text}")
        return None


def delete_http_server(server_id):
    """Delete a webhook HTTP server."""
    url = f"{BASE_URL}/networks/{NETWORK_ID}/webhooks/httpServers/{server_id}"
    resp = requests.delete(url, headers=HEADERS)
    return resp.status_code in (200, 204)


# ══════════════════════════════════════════════════════════════════════
#  PAYLOAD TEMPLATE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════

def list_payload_templates():
    """List all payload templates (both built-in and custom)."""
    url = f"{BASE_URL}/networks/{NETWORK_ID}/webhooks/payloadTemplates"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()
    return []


def create_payload_template(phase_name, endpoint, method, description):
    """Create a custom payload template for a deployment phase."""
    url = f"{BASE_URL}/networks/{NETWORK_ID}/webhooks/payloadTemplates"
    
    # Custom payload that the relay expects
    body_template = json.dumps({
        "action": "deploy",
        "phase": phase_name,
        "endpoint": endpoint,
        "method": method,
        "fabric_name": "SJC23-SDA-Fabric",
        "triggered_by": "meraki-webhook",
        "triggered_at": "{{occurredAt}}",
        "alert_type": "{{alertType}}",
        "network": {
            "id": "{{networkId}}",
            "name": "{{networkName}}"
        },
        "device": {
            "serial": "{{deviceSerial}}",
            "name": "{{deviceName}}",
            "model": "{{deviceModel}}"
        }
    }, indent=2)
    
    # Headers template
    headers_template = json.dumps({
        "Content-Type": "application/json",
        "X-SDA-Phase": phase_name,
        "X-SDA-Endpoint": endpoint
    })
    
    payload = {
        "name": f"SDA: {phase_name}",
        "body": body_template,
        "headers": [
            {"name": "Content-Type", "template": "application/json"},
            {"name": "X-SDA-Phase", "template": phase_name},
            {"name": "X-SDA-Endpoint", "template": endpoint}
        ]
    }
    
    resp = requests.post(url, headers=HEADERS, json=payload)
    if resp.status_code in (200, 201):
        template = resp.json()
        print(f"  Created template: {template['name']} ({template['payloadTemplateId']})")
        return template
    else:
        print(f"  Error creating template '{phase_name}': {resp.status_code}")
        # Some orgs may not support custom payload template creation
        if resp.status_code == 400:
            print(f"  Detail: {resp.text[:200]}")
        return None


# ══════════════════════════════════════════════════════════════════════
#  WEBHOOK ALERT CONFIGURATION
# ══════════════════════════════════════════════════════════════════════

def get_alert_settings():
    """Get current alert settings for the network."""
    url = f"{BASE_URL}/networks/{NETWORK_ID}/alerts/settings"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()
    return None


def send_test_webhook(server_id):
    """Send a test webhook to verify the relay is reachable."""
    url = f"{BASE_URL}/networks/{NETWORK_ID}/webhooks/webhookTests"
    
    payload = {
        "url": None,  # Uses the HTTP server's URL
        "sharedSecret": WEBHOOK_SECRET,
        "payloadTemplateId": "wpt_00001",
        "alertTypeId": "started"
    }
    
    # Actually, the test endpoint needs the HTTP server URL
    # Let's get the server details first
    servers = list_http_servers()
    target = None
    for s in servers:
        if s["id"] == server_id:
            target = s
            break
    
    if not target:
        print(f"  Server {server_id} not found")
        return None
    
    payload = {
        "url": target["url"],
        "sharedSecret": WEBHOOK_SECRET
    }
    
    resp = requests.post(url, headers=HEADERS, json=payload)
    if resp.status_code in (200, 201):
        result = resp.json()
        print(f"  Test webhook sent!")
        print(f"    Test ID: {result.get('id', 'N/A')}")
        print(f"    Status: {result.get('status', 'N/A')}")
        print(f"    URL: {result.get('url', 'N/A')}")
        return result
    else:
        print(f"  Error sending test: {resp.status_code}")
        print(f"  {resp.text[:300]}")
        return None


def check_test_status(test_id):
    """Check the status of a webhook test."""
    url = f"{BASE_URL}/networks/{NETWORK_ID}/webhooks/webhookTests/{test_id}"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()
    return None


# ══════════════════════════════════════════════════════════════════════
#  MAIN SETUP FLOW
# ══════════════════════════════════════════════════════════════════════

def show_status():
    """Show current webhook configuration."""
    print("\n" + "=" * 60)
    print("CURRENT WEBHOOK CONFIGURATION — SJC23-SDA")
    print("=" * 60)
    
    # HTTP Servers
    servers = list_http_servers()
    print(f"\nHTTP Servers: {len(servers)}")
    for s in servers:
        print(f"  [{s['id']}] {s['name']}")
        print(f"    URL: {s['url']}")
    
    # Payload Templates
    templates = list_payload_templates()
    custom = [t for t in templates if not t.get("payloadTemplateId", "").startswith("wpt_")]
    builtin = [t for t in templates if t.get("payloadTemplateId", "").startswith("wpt_")]
    print(f"\nPayload Templates: {len(templates)} ({len(builtin)} built-in, {len(custom)} custom)")
    for t in templates:
        marker = "  " if t.get("payloadTemplateId", "").startswith("wpt_") else " *"
        print(f" {marker} [{t['payloadTemplateId']}] {t['name']}")
    
    # Alert Settings
    alerts = get_alert_settings()
    if alerts:
        webhook_destinations = [d for d in alerts.get("defaultDestinations", {}).get("httpServerIds", [])]
        print(f"\nDefault Alert Webhook Destinations: {len(webhook_destinations)}")
        for wh in webhook_destinations:
            print(f"  - {wh}")
        
        alert_count = len(alerts.get("alerts", []))
        print(f"Alert rules configured: {alert_count}")
    
    return servers


def setup_all(relay_url):
    """Complete setup: HTTP server + payload templates."""
    print("\n" + "=" * 60)
    print("SETTING UP WEBHOOK INFRASTRUCTURE")
    print("=" * 60)
    
    # Step 1: Check for existing SDA relay server  
    print("\n[1/4] Checking existing HTTP servers...")
    servers = list_http_servers()
    sda_server = None
    for s in servers:
        if "SDA" in s.get("name", "") or "sda" in s.get("name", ""):
            sda_server = s
            print(f"  Found existing SDA server: {s['name']} ({s['id']})")
            break
    
    # Step 2: Create/update HTTP server
    if not sda_server:
        print("\n[2/4] Registering relay as webhook HTTP server...")
        sda_server = create_http_server(relay_url)
        if not sda_server:
            print("  FAILED to register HTTP server. Aborting.")
            return False
    else:
        print(f"\n[2/4] Using existing server: {sda_server['name']}")
    
    # Step 3: Create payload templates for each phase
    print("\n[3/4] Creating payload templates for deployment phases...")
    created_templates = []
    for phase in DEPLOYMENT_PHASES:
        template = create_payload_template(
            phase["name"], phase["endpoint"], phase["method"], phase["description"]
        )
        if template:
            created_templates.append(template)
    
    print(f"  Created {len(created_templates)}/{len(DEPLOYMENT_PHASES)} templates")
    
    # Step 4: Summary
    print("\n[4/4] Setup complete!")
    print("=" * 60)
    print("WEBHOOK INFRASTRUCTURE READY")
    print("=" * 60)
    print(f"  HTTP Server: {sda_server['name']} ({sda_server['id']})")
    print(f"  URL: {sda_server['url']}")
    print(f"  Shared Secret: {WEBHOOK_SECRET}")
    print(f"  Payload Templates: {len(created_templates)} created")
    print(f"\n  Save this info in your .env file:")
    print(f"    WEBHOOK_SECRET={WEBHOOK_SECRET}")
    print(f"    WEBHOOK_SERVER_ID={sda_server['id']}")
    
    # Save config for later use
    config = {
        "http_server_id": sda_server["id"],
        "http_server_name": sda_server["name"],
        "http_server_url": sda_server["url"],
        "webhook_secret": WEBHOOK_SECRET,
        "templates": [
            {"id": t["payloadTemplateId"], "name": t["name"]} 
            for t in created_templates
        ],
        "phases": DEPLOYMENT_PHASES
    }
    
    with open("webhook_config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print(f"\n  Config saved to: webhook_config.json")
    
    return True


def cleanup():
    """Remove all SDA webhook configuration."""
    print("\n[CLEANUP] Removing SDA webhook configuration...")
    
    # Remove HTTP servers
    servers = list_http_servers()
    for s in servers:
        if "SDA" in s.get("name", "") or "Relay" in s.get("name", ""):
            if delete_http_server(s["id"]):
                print(f"  Deleted HTTP server: {s['name']}")
    
    # Note: Can't delete built-in payload templates
    templates = list_payload_templates()
    for t in templates:
        tid = t.get("payloadTemplateId", "")
        if not tid.startswith("wpt_") and "SDA" in t.get("name", ""):
            url = f"{BASE_URL}/networks/{NETWORK_ID}/webhooks/payloadTemplates/{tid}"
            resp = requests.delete(url, headers=HEADERS)
            if resp.status_code in (200, 204):
                print(f"  Deleted template: {t['name']}")
    
    print("  Cleanup complete.")


def main():
    parser = argparse.ArgumentParser(
        description="Set up Meraki webhook infrastructure for SDA deployment"
    )
    parser.add_argument(
        "--relay-url",
        help="Public URL of relay server (e.g. https://abc123.ngrok-free.app)"
    )
    parser.add_argument("--setup-all", action="store_true", help="Full setup")
    parser.add_argument("--list", action="store_true", help="Show current config")
    parser.add_argument("--test", action="store_true", help="Send test webhook")
    parser.add_argument("--cleanup", action="store_true", help="Remove all SDA webhook config")
    parser.add_argument("--server-id", help="HTTP server ID for testing")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Meraki Webhook Infrastructure for SDA Deployment")
    print(f"Network: {NETWORK_NAME} ({NETWORK_ID})")
    print("=" * 60)
    
    if args.list:
        show_status()
        return
    
    if args.cleanup:
        confirm = input("Remove all SDA webhook config? (y/n): ").strip().lower()
        if confirm == 'y':
            cleanup()
        return
    
    if args.test:
        servers = list_http_servers()
        if not servers:
            print("\nNo HTTP servers configured. Run --setup-all first.")
            return
        
        server_id = args.server_id or servers[0]["id"]
        print(f"\nSending test webhook to server {server_id}...")
        result = send_test_webhook(server_id)
        if result and result.get("id"):
            print("\nChecking test status...")
            time.sleep(3)
            status = check_test_status(result["id"])
            if status:
                print(f"  Status: {status.get('status', 'unknown')}")
        return
    
    if args.setup_all:
        if not args.relay_url:
            print("\nERROR: --relay-url required for setup.")
            print("Example: --relay-url https://abc123.ngrok-free.app")
            print("\nTo get a URL:")
            print("  1. Start relay: python sda_relay_server_v2.py")
            print("  2. Start ngrok: ngrok http 5000")
            print("  3. Copy the https:// URL from ngrok")
            sys.exit(1)
        
        setup_all(args.relay_url)
        return
    
    # Default: show status
    show_status()
    
    print("\n\nUSAGE:")
    print("-" * 40)
    print("  Show config:  python meraki_webhook_setup.py --list")
    print("  Full setup:   python meraki_webhook_setup.py --setup-all --relay-url https://YOUR-NGROK.ngrok-free.app")
    print("  Test webhook: python meraki_webhook_setup.py --test")
    print("  Cleanup:      python meraki_webhook_setup.py --cleanup")


if __name__ == "__main__":
    main()
