"""
SDA CLI Templates — generates IOS-XE CLI blocks per phase from sda_fabric_config.yaml.
Build tag: v3.0.1-ci-trigger-2

Why CLI not YANG: Cisco's own Catalyst Center pushes raw CLI templates for SDA
features (LISP fabric mode, L2/L3 VNI, anycast SVI, IPDT, dynamic-EID) because the
YANG models for those features are incomplete on 17.x — RESTCONF returns 204 but the
feature subsystem silently drops the payload. Pushing CLI via Netmiko is what every
working SDA-style automation actually does.

Each builder returns: list[ tuple[str_label, list[str_cli_lines]] ]
Grouped per-block so the relay can push & verify each block independently.
"""
from __future__ import annotations
from typing import List, Tuple, Dict, Any

Block = Tuple[str, List[str]]   # (label, cli_lines)


# ─────────────────────────────────────────────────────────────────────
# PHASE 1 — UNDERLAY  (Loopback0, P2P L3, ISIS, BFD, PIM)
# ─────────────────────────────────────────────────────────────────────
def phase1_underlay(fabric: Dict[str, Any], target: str) -> List[Block]:
    dev = fabric["devices"][target]
    underlay = fabric["underlay"]
    isis = underlay["isis"]
    link = underlay["fabric_links"][0]
    mc = underlay["multicast"]

    if target == "border":
        intf = link["border_interface"]
        intf_ip = link["border_ip"]
    else:
        intf = link["edge_interface"]
        intf_ip = link["edge_ip"]
    intf_mask = link.get("border_mask", "255.255.255.254")

    blocks: List[Block] = []

    # NOTE: hostname change is appended LAST so prior blocks finish before prompt mutates.

    blocks.append(("system_mtu", [
        f"system mtu {fabric['fabric'].get('system_mtu', 9100)}",
    ]))

    blocks.append(("ip_routing_multicast", [
        "ip routing",
        "ip multicast-routing",
        "ipv6 unicast-routing",
    ]))

    blocks.append(("loopback0", [
        "interface Loopback0",
        f" description SDA Fabric RLOC - {target}",
        f" ip address {dev['loopback0_ip']} {dev['loopback0_mask']}",
        " ip pim sparse-mode",
        f" ip router isis {isis['area_tag']}",
        " no shutdown",
    ]))

    # Anycast loopback only on border (RP)
    if target == "border" and dev.get("anycast_ip"):
        blocks.append(("loopback_anycast", [
            f"interface Loopback{dev.get('anycast_loopback_id', 60000)}",
            " description SDA Anycast RP",
            f" ip address {dev['anycast_ip']} {dev.get('anycast_mask','255.255.255.255')}",
            " ip pim sparse-mode",
            f" ip router isis {isis['area_tag']}",
            " no shutdown",
        ]))

    # Convert L2 port to L3, then add IP/PIM/ISIS/BFD
    blocks.append((f"p2p_{intf}", [
        f"interface {intf}",
        " no switchport",
        f" description Fabric link to peer",
        f" ip address {intf_ip} {intf_mask}",
        " ip pim sparse-mode",
        f" ip router isis {isis['area_tag']}",
        " isis network point-to-point",
        f" bfd interval {link.get('bfd_interval',100)} min_rx {link.get('bfd_min_rx',100)} multiplier {link.get('bfd_multiplier',3)}",
        " no shutdown",
    ]))

    blocks.append(("router_isis", [
        f"router isis {isis['area_tag']}",
        f" net {dev['isis_net']}",
        " is-type level-2-only",
        f" metric-style {isis.get('metric_style','wide')}",
        " log-adjacency-changes",
        " bfd all-interfaces",
        " nsf ietf",
        " passive-interface Loopback0",
    ]))

    blocks.append(("pim_rp", [
        f"ip pim rp-address {mc['rp_address']}",
        "ip pim ssm default" if mc.get("ssm_default") else "",
    ]))

    # Apply hostname LAST (changes the prompt; safer to do after other blocks)
    blocks.append(("hostname", [
        f"hostname {dev['hostname']}",
    ]))

    return blocks


# ─────────────────────────────────────────────────────────────────────
# PHASE 2 — LISP control plane  (site, instance-id, MS/MR, ETR/ITR)
# ─────────────────────────────────────────────────────────────────────
def phase2_lisp(fabric: Dict[str, Any], target: str) -> List[Block]:
    dev = fabric["devices"][target]
    lisp = fabric["lisp"]
    fab = fabric["fabric"]
    blocks: List[Block] = []

    # router lisp skeleton + locator-set
    rlisp = ["router lisp"]
    rlisp.append(f" locator-set {lisp.get('locator_set_name','rloc_fabric')}")
    rlisp.append(f"  IPv4-interface Loopback0 priority 10 weight 10")
    rlisp.append("  exit-locator-set")

    # Service IPv4 + ethernet (control plane)
    rlisp += [
        " service ipv4",
        "  encapsulation vxlan",
        "  itr map-resolver " + lisp["map_servers"][0]["ip"],
        "  etr map-server " + lisp["map_servers"][0]["ip"] + " key " + lisp["map_servers"][0]["key"],
        "  etr",
        "  sgt",
        "  no map-cache away-eids send-map-request" if lisp.get("border_roles",{}).get("no_map_cache_away_eids") and target=="border" else "  exit-service-ipv4",
    ]
    if not (lisp.get("border_roles",{}).get("no_map_cache_away_eids") and target=="border"):
        # already exited
        pass
    else:
        rlisp.append("  exit-service-ipv4")

    rlisp += [
        " service ethernet",
        "  itr map-resolver " + lisp["map_servers"][0]["ip"],
        "  etr map-server " + lisp["map_servers"][0]["ip"] + " key " + lisp["map_servers"][0]["key"],
        "  etr",
        "  exit-service-ethernet",
    ]

    # Border roles: map-server + map-resolver + proxy
    if target == "border":
        rlisp += [
            " site " + fab.get("site_name", "site_uci"),
            f"  authentication-key {fab.get('site_auth_key','CiscoSDA123')}",
            "  description SDA fabric site",
            "  exit-site",
            " ipv4 map-server",
            " ipv4 map-resolver",
            " ipv4 proxy-etr",
            " ipv4 proxy-itr " + dev["loopback0_ip"],
        ]
    else:
        # Edge: use border as PETR
        for petr in lisp.get("edge_roles", {}).get("use_petr", []):
            rlisp.append(f" ipv4 use-petr {petr}")
        rlisp.append(f" ipv4 proxy-itr {dev['loopback0_ip']}")

    rlisp.append(" exit-router-lisp")
    blocks.append(("router_lisp_base", rlisp))
    return blocks


# ─────────────────────────────────────────────────────────────────────
# PHASE 3 — VRF + L3 instance binding  (per-VN)
# ─────────────────────────────────────────────────────────────────────
def phase3_vrf_overlay(fabric: Dict[str, Any], target: str) -> List[Block]:
    blocks: List[Block] = []
    for vrf in fabric.get("vrfs", []):
        blocks.append((f"vrf_{vrf['name']}", [
            f"vrf definition {vrf['name']}",
            f" description {vrf.get('description','')}",
            f" rd {vrf['rd']}",
            " address-family ipv4",
            f"  route-target export {vrf['rt_export']}",
            f"  route-target import {vrf['rt_import']}",
            "  exit-address-family",
        ]))

    # Bind each L3 instance under router lisp
    for inst in fabric.get("l3_instances", []):
        if inst["instance_id"] == 4097:
            continue  # default global, no eid-table binding needed for POC
        blocks.append((f"lisp_l3_inst_{inst['instance_id']}", [
            "router lisp",
            f" instance-id {inst['instance_id']}",
            "  service ipv4",
            f"   eid-table {inst['eid_table']}",
            "   database-mapping limit dynamic 5000",
            "   exit-service-ipv4",
            "  exit-instance-id",
            " exit-router-lisp",
        ]))
    return blocks


# ─────────────────────────────────────────────────────────────────────
# PHASE 4 — Access VLANs / Anycast SVIs / L2 VNI / dynamic-EID  (EDGE)
# ─────────────────────────────────────────────────────────────────────
def phase4_access(fabric: Dict[str, Any], target: str) -> List[Block]:
    if target != "edge":
        return []
    blocks: List[Block] = []

    for v in fabric.get("access_vlans", []):
        blocks.append((f"vlan_{v['vlan_id']}", [
            f"vlan {v['vlan_id']}",
            f" name {v['name']}",
        ]))

        svi = v["svi"]
        blocks.append((f"svi_{v['vlan_id']}", [
            f"interface Vlan{v['vlan_id']}",
            f" description Anycast SVI {v['name']}",
            f" vrf forwarding {v['vrf']}",
            f" ip address {svi['ip']} {svi['mask']}",
            f" mac-address {svi['mac_address']}",
            " ip helper-address " + " ".join(svi.get("dhcp_helpers", [])) if svi.get("dhcp_helpers") else " no shutdown",
            " no ip redirects",
            " ip route-cache same-interface",
            " no shutdown",
        ]))

        # IPDT policy on SVI (device-tracking required for LISP dynamic-EID detection)
        blocks.append((f"ipdt_{v['vlan_id']}", [
            f"device-tracking policy IPDT_POLICY_{v['vlan_id']}",
            " tracking enable",
            " security-level glean",
            f"interface Vlan{v['vlan_id']}",
            f" device-tracking attach-policy IPDT_POLICY_{v['vlan_id']}",
        ]))

        # dynamic-EID + L2 VNI under router lisp
        deid = v["dynamic_eid"]
        blocks.append((f"lisp_dyneid_{v['vlan_id']}", [
            "router lisp",
            f" instance-id {v['l3_instance_id']}",
            "  dynamic-eid " + deid["name"],
            f"   database-mapping {deid['prefix']} locator-set " + fabric["lisp"].get("locator_set_name","rloc_fabric"),
            "   exit-dynamic-eid",
            "  exit-instance-id",
            f" instance-id {v['l2_instance_id']}",
            "  service ethernet",
            f"   eid-table vlan {v['vlan_id']}",
            "   broadcast-underlay 232.0.0.1",
            "   database-mapping mac locator-set " + fabric["lisp"].get("locator_set_name","rloc_fabric"),
            "   exit-service-ethernet",
            "  exit-instance-id",
            " exit-router-lisp",
        ]))

        # DHCP local pool on Edge (POC simplification)
        if v.get("dhcp_pool"):
            p = v["dhcp_pool"]
            blocks.append((f"dhcp_pool_{v['vlan_id']}", [
                f"ip dhcp excluded-address vrf {v['vrf']} {p['excluded_start']} {p['excluded_end']}",
                f"ip dhcp pool {p['pool_name']}",
                f" vrf {v['vrf']}",
                f" network {p['network']} {p['network_mask']}",
                f" default-router {p['default_router']}",
                f" dns-server {p['dns_server']}",
                f" lease {p.get('lease_days',1)} {p.get('lease_hours',0)} 0",
            ]))
    return blocks


# ─────────────────────────────────────────────────────────────────────
# PHASE 5 — Border handoff / BGP (skipped for POC if fusion disabled)
# ─────────────────────────────────────────────────────────────────────
def phase5_border_handoff(fabric: Dict[str, Any], target: str) -> List[Block]:
    if not fabric.get("bgp", {}).get("fusion", {}).get("enabled", False):
        return []  # POC: fusion disabled
    return []


# Phase registry the relay calls
PHASE_BUILDERS = {
    "phase1-underlay":  phase1_underlay,
    "phase2-lisp":      phase2_lisp,
    "phase3-overlay":   phase3_vrf_overlay,
    "phase4-access":    phase4_access,
    "phase5-handoff":   phase5_border_handoff,
}

# Per-phase verify commands — relay runs these and grep-checks for keywords
VERIFY_CMDS = {
    "phase1-underlay": [
        ("show isis neighbors",          ["Up"]),
        ("show ip route isis | inc /32", []),                     # any line is fine
        ("show ip pim rp mapping",       ["RP "]),
        ("show ip interface brief Loopback0", ["up"]),
    ],
    "phase2-lisp": [
        ("show lisp instance-id 4097 ipv4 server", ["site_uci"]),
        ("show lisp session",            ["Up"]),
    ],
    "phase3-overlay": [
        ("show vrf",                     ["CORP_VN", "GUEST_VN"]),
        ("show lisp instance-id 4099 ipv4", ["instance"]),
    ],
    "phase4-access": [
        ("show ip interface brief | inc Vlan", ["Vlan100", "Vlan200"]),
        ("show ip dhcp pool",            ["CORP_DATA_POOL"]),
        ("show device-tracking policy IPDT_POLICY_100", ["tracking enable"]),
    ],
}

# trigger-deploy: 2026-05-05T06:41:37Z
