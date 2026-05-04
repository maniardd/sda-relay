#!/usr/bin/env python3
"""
yang_schema_grabber.py — Discover live YANG schema from target switches.

Purpose: Eliminate guessing. We CONFIGURE a feature once on a switch (manually
or via a known-good payload), then GET it back via RESTCONF with
?depth=unbounded to capture the EXACT JSON structure the device expects.
That structure becomes the canonical template for our YANG payloads.

Usage on Ubuntu VM:
    cd /opt/sda-relay
    git pull origin main
    venv/bin/python3 yang_schema_grabber.py

Output:
    discovery/<switch_role>/<feature>.json   one file per (switch, feature)
    discovery/_summary.txt                   human-readable summary

Reads switch IPs/creds from /opt/sda-relay/.env (same as the relay).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Tuple

import requests
import urllib3
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ----------------------------------------------------------------------
# Load creds from .env (same format the relay uses)
# ----------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

DEVICES = {
    "border": {
        "ip":   os.getenv("C9500_IP"),
        "user": os.getenv("C9500_USER", "admin"),
        "pw":   os.getenv("C9500_PASS"),
    },
    "edge": {
        "ip":   os.getenv("C9300_IP"),
        "user": os.getenv("C9300_USER", "admin"),
        "pw":   os.getenv("C9300_PASS"),
    },
}

# ----------------------------------------------------------------------
# Paths to discover. Anything we are unsure about — list it here.
# Each entry: (label, restconf_path)
# ----------------------------------------------------------------------
DISCOVERY_PATHS = [
    # --- root/native (huge but anchors namespaces) -------------------
    ("yang_library",            "/ietf-yang-library:yang-library"),
    ("native_root_top_only",    "/Cisco-IOS-XE-native:native?depth=1"),

    # --- Phase 1 underlay --------------------------------------------
    ("ip_root",                 "/Cisco-IOS-XE-native:native/ip?depth=2"),
    ("multicast_routing",       "/Cisco-IOS-XE-native:native/ip/multicast-routing?depth=unbounded"),
    ("pim",                     "/Cisco-IOS-XE-native:native/ip/pim?depth=unbounded"),
    ("router_root",             "/Cisco-IOS-XE-native:native/router?depth=2"),
    ("router_isis",             "/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-isis:isis?depth=unbounded"),
    ("interface_loopback0",     "/Cisco-IOS-XE-native:native/interface/Loopback=0?depth=unbounded"),
    ("interface_loopback60000", "/Cisco-IOS-XE-native:native/interface/Loopback=60000?depth=unbounded"),
    # P2P interface — captured per-device (border 25G, edge 1G):
    ("p2p_interface_border",    "/Cisco-IOS-XE-native:native/interface/TwentyFiveGigE=1%2F0%2F2?depth=unbounded"),
    ("p2p_interface_edge",      "/Cisco-IOS-XE-native:native/interface/GigabitEthernet=1%2F0%2F2?depth=unbounded"),

    # --- Phase 2 LISP (forward-look) ---------------------------------
    ("router_lisp",             "/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-lisp:lisp?depth=unbounded"),

    # --- Phase 3 NVE / VXLAN -----------------------------------------
    ("nve",                     "/Cisco-IOS-XE-native:native/interface/nve=1?depth=unbounded"),

    # --- Phase 4 VRF + BGP -------------------------------------------
    ("vrf_definition",          "/Cisco-IOS-XE-native:native/vrf?depth=unbounded"),
    ("router_bgp",              "/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-bgp:bgp?depth=unbounded"),

    # --- Phase 5 access ----------------------------------------------
    ("vlan_list",               "/Cisco-IOS-XE-native:native/vlan?depth=unbounded"),
    ("dhcp",                    "/Cisco-IOS-XE-native:native/ip/dhcp?depth=unbounded"),
]


def get(ip: str, user: str, pw: str, path: str, timeout: int = 30) -> Tuple[int, str]:
    url = f"https://{ip}/restconf/data{path}"
    headers = {"Accept": "application/yang-data+json"}
    try:
        r = requests.get(url, headers=headers, auth=(user, pw),
                         verify=False, timeout=timeout)
        return r.status_code, r.text
    except Exception as exc:
        return 0, f"EXCEPTION: {exc}"


def safe_filename(label: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in label)


def main() -> int:
    out_root = HERE / "discovery"
    out_root.mkdir(exist_ok=True)
    summary_lines = []

    for role, dev in DEVICES.items():
        if not dev["ip"] or not dev["pw"]:
            print(f"[skip] {role}: missing IP or password in .env")
            summary_lines.append(f"{role:<8}  SKIPPED (missing creds)")
            continue

        dev_dir = out_root / role
        dev_dir.mkdir(exist_ok=True)
        print(f"\n=== {role}  {dev['ip']} ===")
        summary_lines.append(f"\n=== {role}  {dev['ip']} ===")

        for label, path in DISCOVERY_PATHS:
            # Skip device-irrelevant paths (border vs edge p2p)
            if label == "p2p_interface_border" and role != "border":
                continue
            if label == "p2p_interface_edge" and role != "edge":
                continue

            status, body = get(dev["ip"], dev["user"], dev["pw"], path)
            fname = dev_dir / f"{safe_filename(label)}.json"
            header = (
                f"// HTTP {status}  GET {path}\n"
                f"// device: {role} ({dev['ip']})\n"
            )

            # If we got JSON, pretty-print it. Otherwise dump raw text.
            try:
                pretty = json.dumps(json.loads(body), indent=2)
                fname.write_text(header + pretty + "\n")
            except Exception:
                fname.write_text(header + body + "\n")

            tag = "OK " if status in (200, 204) else "ERR"
            line = f"  [{tag}] {status:<3}  {label:<28}  -> {fname.name}"
            print(line)
            summary_lines.append(line)

    summary_file = out_root / "_summary.txt"
    summary_file.write_text("\n".join(summary_lines) + "\n")
    print(f"\nDone. Summary: {summary_file}")
    print(f"Bundle for sharing:")
    print(f"  cd {HERE} && tar czf discovery.tar.gz discovery/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
