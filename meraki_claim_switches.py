#!/usr/bin/env python3
"""
Meraki Catalyst Switch Onboarding Script
=========================================
Claims IOS-XE Catalyst switches into a Meraki Dashboard network 
in "Device Configuration" (monitored/hybrid) mode.

This keeps CLI config control on the switch while enabling
full monitoring in Meraki Dashboard.

Prerequisites:
  1. Run 'service meraki connect' on each switch (IOS-XE CLI)
  2. Get the Cloud ID from 'show meraki connect'
  3. Switch must have: ip routing, aaa new-model, DNS, NTP, priv-15 user

Usage:
  python meraki_claim_switches.py --cloud-ids XXXX-XXXX-XXXX YYYY-YYYY-YYYY
  python meraki_claim_switches.py --interactive
  python meraki_claim_switches.py --dry-run --cloud-ids XXXX-XXXX-XXXX
"""

import argparse
import json
import os
import sys
import getpass

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required. Install with: pip install requests")
    sys.exit(1)

# ── Configuration ────────────────────────────────────────────────────────
MERAKI_API_KEY = os.environ.get("MERAKI_API_KEY", "1bbb81c532e97a19bbac32032009eeaaa264fe31")
ORG_ID = "135358"  # CiscoWLAN
NETWORK_ID = "L_591660401045811304"  # SJC23-SDA
NETWORK_NAME = "SJC23-SDA"
BASE_URL = "https://api.meraki.com/api/v1"

HEADERS = {
    "Authorization": f"Bearer {MERAKI_API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# Switch info for reference
SWITCHES = {
    "C9500-32C": {
        "system_serial": "CAT2348L0Q9",
        "ip": "192.168.128.9",
        "role": "Border Node"
    },
    "C9300X-48HXN": {
        "system_serial": "FVH2826L6QZ",
        "ip": "192.168.128.7",
        "role": "Edge Node"
    }
}


def verify_network():
    """Verify the target network exists and is accessible."""
    url = f"{BASE_URL}/networks/{NETWORK_ID}"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        net = resp.json()
        print(f"  Target network: {net['name']} ({net['id']})")
        print(f"  Product types: {', '.join(net.get('productTypes', []))}")
        return True
    else:
        print(f"  ERROR: Cannot access network {NETWORK_ID}: {resp.status_code}")
        print(f"  {resp.text}")
        return False


def check_existing_devices():
    """Check what devices are already in the network."""
    url = f"{BASE_URL}/networks/{NETWORK_ID}/devices"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        devices = resp.json()
        print(f"  Current devices in {NETWORK_NAME}: {len(devices)}")
        for d in devices:
            print(f"    - {d.get('model', 'unknown')} | {d.get('serial', 'N/A')} | {d.get('name', 'unnamed')}")
        return devices
    return []


def claim_switches(cloud_ids, switch_username, switch_password, enable_password=None, dry_run=False):
    """
    Claim switches to the SJC23-SDA network in 'monitored' (device config) mode.
    
    Args:
        cloud_ids: List of Cloud IDs from 'show meraki connect'
        switch_username: IOS-XE privilege-15 username
        switch_password: IOS-XE password
        enable_password: IOS-XE enable password (optional)
        dry_run: If True, just show the payload without sending
    """
    url = f"{BASE_URL}/networks/{NETWORK_ID}/devices/claim"
    
    # Build detailsByDevice for each Cloud ID
    details_by_device = []
    for cloud_id in cloud_ids:
        device_details = {
            "serial": cloud_id,
            "details": [
                {"name": "device mode", "value": "monitored"},
                {"name": "username", "value": switch_username},
                {"name": "password", "value": switch_password}
            ]
        }
        if enable_password:
            device_details["details"].append(
                {"name": "enable password", "value": enable_password}
            )
        details_by_device.append(device_details)
    
    payload = {
        "serials": cloud_ids,
        "addAtomically": True,
        "detailsByDevice": details_by_device
    }
    
    print("\n" + "=" * 60)
    print("CLAIM PAYLOAD")
    print("=" * 60)
    
    # Show payload with masked credentials
    safe_payload = json.loads(json.dumps(payload))
    for device in safe_payload.get("detailsByDevice", []):
        for detail in device.get("details", []):
            if detail["name"] in ("password", "enable password"):
                detail["value"] = "****"
    print(json.dumps(safe_payload, indent=2))
    
    if dry_run:
        print("\n[DRY RUN] Payload prepared but NOT sent to Meraki API.")
        # Save full payload for inspection
        with open("claim_payload.json", "w", encoding="utf-8") as f:
            json.dump(safe_payload, f, indent=2)
        print("[DRY RUN] Saved to claim_payload.json (credentials masked)")
        return None
    
    print(f"\nSending POST to: {url}")
    resp = requests.post(url, headers=HEADERS, json=payload)
    
    print(f"\nResponse Status: {resp.status_code}")
    
    if resp.status_code in (200, 201):
        result = resp.json()
        print("\nSUCCESS! Switches claimed to network.")
        print(json.dumps(result, indent=2))
        return result
    else:
        print(f"\nERROR: {resp.status_code}")
        print(resp.text)
        
        if resp.status_code == 400:
            print("\nPossible issues:")
            print("  - Cloud ID may be incorrect (get it from 'show meraki connect' on the switch)")
            print("  - Switch tunnel may not be connected yet")
            print("  - Switch may already be claimed in another network")
        elif resp.status_code == 404:
            print("\nNetwork not found or API endpoint not available.")
        
        return None


def verify_claimed_devices(cloud_ids):
    """Verify the switches appear in the network after claiming."""
    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)
    
    url = f"{BASE_URL}/networks/{NETWORK_ID}/devices"
    resp = requests.get(url, headers=HEADERS)
    
    if resp.status_code == 200:
        devices = resp.json()
        found = 0
        for d in devices:
            serial = d.get("serial", "")
            if serial in cloud_ids:
                found += 1
                print(f"  FOUND: {d.get('model', 'unknown')} | {serial}")
                print(f"         Name: {d.get('name', 'unnamed')}")
                print(f"         Status: {d.get('status', 'unknown')}")
                print(f"         MAC: {d.get('mac', 'N/A')}")
                print(f"         LAN IP: {d.get('lanIp', 'N/A')}")
        
        if found == len(cloud_ids):
            print(f"\n  All {found} switches successfully claimed and visible!")
        else:
            print(f"\n  Found {found}/{len(cloud_ids)} switches.")
            print("  Note: It may take up to 15 minutes for switches to fully appear.")
    else:
        print(f"  Could not verify: {resp.status_code}")


def interactive_mode():
    """Interactive wizard for claiming switches."""
    print("\n" + "=" * 60)
    print("MERAKI CATALYST SWITCH ONBOARDING WIZARD")
    print("=" * 60)
    
    print("\nBefore proceeding, make sure you have:")
    print("  1. SSH'd into each switch")
    print("  2. Run 'service meraki connect' in config mode")
    print("  3. Run 'show meraki connect' — tunnel should be UP")
    print("  4. Noted the Cloud ID from the output")
    
    input("\nPress Enter when ready...")
    
    # Get Cloud IDs
    cloud_ids = []
    print("\nEnter Cloud IDs (one per line, empty line to finish):")
    while True:
        cloud_id = input("  Cloud ID: ").strip()
        if not cloud_id:
            break
        cloud_ids.append(cloud_id)
    
    if not cloud_ids:
        print("No Cloud IDs entered. Exiting.")
        return
    
    print(f"\nCloud IDs to claim: {cloud_ids}")
    
    # Get switch credentials
    print("\nEnter IOS-XE switch credentials (privilege 15 user):")
    switch_username = input("  Username: ").strip()
    switch_password = getpass.getpass("  Password: ")
    enable_password = getpass.getpass("  Enable password (press Enter to skip): ")
    
    if not enable_password:
        enable_password = None
    
    # Confirm
    print(f"\nWill claim {len(cloud_ids)} switch(es) to {NETWORK_NAME}:")
    for cid in cloud_ids:
        print(f"  - {cid}")
    print(f"  Mode: Device Configuration (monitored)")
    print(f"  Username: {switch_username}")
    
    confirm = input("\nProceed? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Cancelled.")
        return
    
    # Claim
    result = claim_switches(cloud_ids, switch_username, switch_password, enable_password)
    
    if result:
        print("\nWaiting a moment before verification...")
        verify_claimed_devices(cloud_ids)


def main():
    parser = argparse.ArgumentParser(
        description="Claim Catalyst switches to Meraki Dashboard (Device Config mode)"
    )
    parser.add_argument(
        "--cloud-ids", nargs="+",
        help="Cloud IDs from 'show meraki connect' on each switch"
    )
    parser.add_argument(
        "--username", 
        help="IOS-XE privilege-15 username"
    )
    parser.add_argument(
        "--password",
        help="IOS-XE password (will prompt if not provided)"
    )
    parser.add_argument(
        "--enable-password",
        help="IOS-XE enable password (optional)"
    )
    parser.add_argument(
        "--interactive", action="store_true",
        help="Run interactive wizard"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show payload without actually claiming"
    )
    parser.add_argument(
        "--verify-only", action="store_true",
        help="Just check what devices are in the network"
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Meraki Catalyst Switch Onboarding")
    print(f"Target: {NETWORK_NAME} ({NETWORK_ID})")
    print("=" * 60)
    
    # Verify network access
    print("\n[1] Verifying network access...")
    if not verify_network():
        sys.exit(1)
    
    # Check existing devices
    print("\n[2] Checking existing devices...")
    check_existing_devices()
    
    if args.verify_only:
        return
    
    if args.interactive:
        interactive_mode()
        return
    
    if not args.cloud_ids:
        print("\nERROR: Provide --cloud-ids or use --interactive mode")
        print("\nTo get Cloud IDs, SSH into each switch and run:")
        print("  conf t")
        print("  service meraki connect")
        print("  end")
        print("  show meraki connect")
        print("\nThe Cloud ID will be in the output.")
        sys.exit(1)
    
    # Get credentials
    username = args.username
    if not username:
        username = input("\nIOS-XE username (priv 15): ").strip()
    
    password = args.password
    if not password:
        password = getpass.getpass("IOS-XE password: ")
    
    enable_pw = args.enable_password
    
    # Claim
    print(f"\n[3] Claiming {len(args.cloud_ids)} switch(es)...")
    result = claim_switches(
        args.cloud_ids, username, password, enable_pw, 
        dry_run=args.dry_run
    )
    
    if result and not args.dry_run:
        print("\n[4] Verifying...")
        verify_claimed_devices(args.cloud_ids)


if __name__ == "__main__":
    main()
