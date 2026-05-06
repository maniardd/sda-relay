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
    ms_ip = lisp["map_servers"][0]["ip"]
    ms_key = lisp["map_servers"][0]["key"]
    blocks: List[Block] = []

    # Block 1: locator-set (separate so router-lisp lock is released between sub-blocks)
    blocks.append(("lisp_locator_set", [
        "router lisp",
        f" locator-set {lisp.get('locator_set_name','rloc_fabric')}",
        "  IPv4-interface Loopback0 priority 10 weight 10",
        "  exit-locator-set",
        " exit-router-lisp",
    ]))

    # Block 2: site (border only — MS holds the site DB)
    # CRITICAL: site must list every EID prefix it will accept registers for,
    # otherwise the MS silently drops map-registers and the LISP TCP/4342
    # session never establishes (lesson learned 2026-05-06).
    if target == "border":
        site_lines = [
            "router lisp",
            f" site {fab.get('site_name','site_uci')}",
            f"  authentication-key {fab.get('site_auth_key','CiscoSDA123')}",
            "  description SDA fabric site",
        ]
        # Permit every L3 VN's EID space (use access_vlans dynamic_eid prefix
        # OR an explicit vn_supernet override) plus the per-VN test /32.
        for v in fabric.get("access_vlans", []):
            iid = v["l3_instance_id"]
            prefix = v.get("vn_supernet") or v["dynamic_eid"]["prefix"]
            site_lines.append(f"  eid-record instance-id {iid} {prefix} accept-more-specifics")
            tip = v.get("edge_test_eid") or v.get("east_west_test_ip")
            if tip:
                site_lines.append(f"  eid-record instance-id {iid} {tip}/32 accept-more-specifics")
            l2 = v.get("l2_instance_id")
            if l2:
                site_lines.append(f"  eid-record instance-id {l2} any-mac")
        site_lines += ["  exit-site", " exit-router-lisp"]
        blocks.append(("lisp_site", site_lines))

    # Block 3: service ipv4 — IOS-XE 17.x SDA: MS/MR/proxy go INSIDE service block
    svc_ipv4 = [
        "router lisp",
        " service ipv4",
        "  encapsulation vxlan",
    ]
    if target == "border":
        svc_ipv4 += [
            "  map-server",
            "  map-resolver",
            "  proxy-etr",
            f"  proxy-itr {dev['loopback0_ip']}",
            "  no map-cache away-eids send-map-request",
        ]
    else:
        svc_ipv4 += [
            f"  itr map-resolver {ms_ip}",
            f"  etr map-server {ms_ip} key {ms_key}",
            "  etr",
            f"  use-petr {ms_ip}",
        ]
    svc_ipv4 += [
        "  exit-service-ipv4",
        " exit-router-lisp",
    ]
    blocks.append(("lisp_service_ipv4", svc_ipv4))

    # Block 4: service ethernet (L2 VNI control plane)
    svc_eth = [
        "router lisp",
        " service ethernet",
    ]
    if target == "border":
        svc_eth += [
            "  map-server",
            "  map-resolver",
        ]
    else:
        svc_eth += [
            f"  itr map-resolver {ms_ip}",
            f"  etr map-server {ms_ip} key {ms_key}",
            "  etr",
        ]
    svc_eth += [
        "  exit-service-ethernet",
        " exit-router-lisp",
    ]
    blocks.append(("lisp_service_ethernet", svc_eth))

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
#           DHCP server pools live on BORDER (real SDA pattern), edge
#           SVIs use ip helper-address pointing at border Loopback0.
# ─────────────────────────────────────────────────────────────────────
def phase4_access(fabric: Dict[str, Any], target: str) -> List[Block]:
    blocks: List[Block] = []
    border = fabric["devices"]["border"]
    border_lo0 = border["loopback0_ip"]

    # ── BORDER: DHCP server pools per VRF ─────────────────────────────
    if target == "border":
        # DHCP server needs to be reachable inside each VRF; we put pools
        # in the VRF and rely on the helper-address from edge to reach us
        # via the LISP/VXLAN fabric (border Loopback0 = 10.255.255.1).
        for v in fabric.get("access_vlans", []):
            if not v.get("dhcp_pool"):
                continue
            p = v["dhcp_pool"]
            blocks.append((f"dhcp_pool_border_{v['vlan_id']}", [
                f"ip dhcp excluded-address vrf {v['vrf']} {p['excluded_start']} {p['excluded_end']}",
                f"no ip dhcp pool {p['pool_name']}",         # idempotent: clear stale pool first
                f"ip dhcp pool {p['pool_name']}",
                f" vrf {v['vrf']}",
                f" network {p['network']} {p['network_mask']}",
                f" default-router {p['default_router']}",
                f" dns-server {p['dns_server']}",
                f" lease {p.get('lease_days',1)} {p.get('lease_hours',0)} 0",
            ]))
        # Service that lets the DHCP process serve relayed requests across VRFs
        blocks.append(("dhcp_service", [
            "ip dhcp relay information trust-all",
            "ip dhcp snooping",     # harmless; useful later
        ]))
        # ── East-West test targets: per-VN loopback inside the VRF.
        # Edge endpoints can ping these to prove LISP map-cache + VXLAN
        # encap across the fabric link (no second laptop needed).
        for v in fabric.get("access_vlans", []):
            test_ip = v.get("east_west_test_ip")
            if not test_ip:
                continue
            iid = v["l3_instance_id"]
            blocks.append((f"ew_test_loopback_{iid}", [
                f"interface Loopback{iid}",
                f" description East-West test target {v['vrf']}",
                f" vrf forwarding {v['vrf']}",
                f" ip address {test_ip} 255.255.255.255",
                " no shutdown",
            ]))
            # Register this /32 as a static EID so LISP advertises it
            blocks.append((f"ew_test_lisp_{iid}", [
                "router lisp",
                f" instance-id {iid}",
                "  service ipv4",
                f"   database-mapping {test_ip}/32 locator-set " + fabric["lisp"].get("locator_set_name","rloc_fabric"),
                "   exit-service-ipv4",
                "  exit-instance-id",
                " exit-router-lisp",
            ]))
        return blocks

    # ── EDGE: VLANs, anycast SVIs (with helper-address), IPDT, L2 VNI ─
    for v in fabric.get("access_vlans", []):
        blocks.append((f"vlan_{v['vlan_id']}", [
            f"vlan {v['vlan_id']}",
            f" name {v['name']}",
        ]))

        svi = v["svi"]
        # Edge anycast SVI: helper-address points at border Loopback0.
        # Because the SVI is in the VRF, the helper resolves through the
        # fabric (LISP map-cache → VXLAN encap → border).
        svi_lines = [
            f"interface Vlan{v['vlan_id']}",
            f" description Anycast SVI {v['name']}",
            f" vrf forwarding {v['vrf']}",
            f" ip address {svi['ip']} {svi['mask']}",
            f" mac-address {svi['mac_address']}",
            " no ip redirects",
            " ip route-cache same-interface",
            f" ip helper-address vrf {v['vrf']} {border_lo0}",
            " no shutdown",
        ]
        blocks.append((f"svi_{v['vlan_id']}", svi_lines))

        # IPDT policy attached at VLAN-config level
        blocks.append((f"ipdt_{v['vlan_id']}", [
            f"device-tracking policy IPDT_POLICY_{v['vlan_id']}",
            " tracking enable",
            " security-level glean",
            f"vlan configuration {v['vlan_id']}",
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

    # ── Per-VN edge test EID ─────────────────────────────────────────
    # A static /32 inside each VN (NOT inside the SVI subnet) so LISP has
    # something concrete to register — this fires the MS map-register and
    # brings the TCP/4342 session Up even before any real endpoint plugs in.
    for v in fabric.get("access_vlans", []):
        tip = v.get("edge_test_eid")
        if not tip:
            continue
        iid = v["l3_instance_id"]
        loop_id = 4000 + iid   # e.g. 8099 for CORP_VN, 8100 for GUEST_VN
        blocks.append((f"edge_test_loopback_{iid}", [
            f"interface Loopback{loop_id}",
            f" description SDA edge test EID {v['vrf']}",
            f" vrf forwarding {v['vrf']}",
            f" ip address {tip} 255.255.255.255",
            " no shutdown",
        ]))
        blocks.append((f"edge_test_eid_{iid}", [
            "router lisp",
            f" instance-id {iid}",
            "  service ipv4",
            f"   database-mapping {tip}/32 locator-set " + fabric["lisp"].get("locator_set_name","rloc_fabric"),
            "   exit-service-ipv4",
            "  exit-instance-id",
            " exit-router-lisp",
        ]))

    # ── Endpoint port assignments (user-driven via YAML/Meraki form) ──
    # Each entry binds a physical port to a VN (= access VLAN). This is the
    # "who plugs in where" map; lets a user say "Gi1/0/5 = guest jack" without
    # editing CLI directly.
    for p in fabric.get("port_assignments", []):
        if p.get("device") and p["device"] != fabric["devices"]["edge"]["hostname"]:
            continue
        port = p["port"]
        # Find the access_vlan record for this VN to get vlan_id
        vlan_id = None
        for v in fabric.get("access_vlans", []):
            if v["vrf"] == p["vn"]:
                vlan_id = v["vlan_id"]
                break
        if not vlan_id:
            continue
        blocks.append((f"endpoint_port_{port.replace('/', '_')}", [
            f"interface {port}",
            f" description SDA endpoint :: {p['vn']} :: {p.get('label','')}",
            " switchport mode access",
            f" switchport access vlan {vlan_id}",
            " spanning-tree portfast",
            " spanning-tree bpduguard enable",
            " no shutdown",
        ]))

    return blocks


# ─────────────────────────────────────────────────────────────────────
# PHASE 5 — Internet Access (NAT overload OR border-as-fusion)
# Per design: skip true L3 handoff (external BGP) for now.
#
# nat_overload : VRF default route -> global next-hop; PAT each VN to upstream IF.
#                Cheapest. All VNs share one public IP.
# border_fusion: VRF default route -> global next-hop, plus reverse leak so
#                global has /16 route back to VN via Loopback0 -> LISP. Per-VN exit.
# ─────────────────────────────────────────────────────────────────────
def phase5_internet(fabric: Dict[str, Any], target: str) -> List[Block]:
    if target != "border":
        return []
    ia = fabric.get("internet_access", {})
    mode = ia.get("mode", "none")
    if mode == "none":
        return []

    blocks: List[Block] = []
    nh = ia["upstream_next_hop"]
    upiface = ia.get("upstream_interface", "Vlan128")

    enabled_vns = [v["vn"] for v in ia.get("per_vn", []) if v.get("enabled")]
    vrf_records = [v for v in fabric.get("vrfs", []) if v["name"] in enabled_vns]

    if mode == "nat_overload":
        # 1) Default route per VRF pointing at global upstream
        for v in vrf_records:
            blocks.append((f"vrf_default_route_{v['name']}", [
                f"ip route vrf {v['name']} 0.0.0.0 0.0.0.0 {nh} global",
            ]))
        # 2) NAT ACL + interface NAT (one shared overload to upstream IF)
        acl_lines = ["ip access-list extended ACL_NAT_VNS"]
        for v in fabric.get("access_vlans", []):
            if v["vrf"] in enabled_vns:
                net = v["dhcp_pool"]["network"]
                # convert /24 mask to wildcard 0.0.0.255 (POC: assume /24)
                acl_lines.append(f" permit ip {net} 0.0.0.255 any")
        blocks.append(("nat_acl", acl_lines))
        for v in vrf_records:
            blocks.append((f"nat_overload_{v['name']}", [
                f"ip nat inside source list ACL_NAT_VNS interface {upiface} vrf {v['name']} overload",
            ]))
        # 3) Mark fabric link as NAT inside, upstream as NAT outside
        link = fabric["underlay"]["fabric_links"][0]
        blocks.append(("nat_inside_iface", [
            f"interface {link['border_interface']}",
            " ip nat inside",
        ]))
        blocks.append(("nat_outside_iface", [
            f"interface {upiface}",
            " ip nat outside",
        ]))

    elif mode == "border_fusion":
        # Per-VN default toward global; global gets a /16 leak back via LISP RLOC
        for v in vrf_records:
            blocks.append((f"vrf_default_route_{v['name']}", [
                f"ip route vrf {v['name']} 0.0.0.0 0.0.0.0 {nh} global",
            ]))
        # Return path: per-VN supernet pointed at LISP (border itself terminates)
        # The LISP-resolved map-cache will hand it to the right edge.
        for v in fabric.get("access_vlans", []):
            if v["vrf"] not in enabled_vns:
                continue
            sn = v.get("vn_supernet") or v["dynamic_eid"]["prefix"]
            # static route in global pointing supernet at NULL0 prevents loop;
            # actual resolution happens via LISP since border is the petr/proxy-itr
            blocks.append((f"global_return_{v['vrf']}", [
                f"ip route {sn.split('/')[0]} 255.255.0.0 Null0 254",  # safety floor
            ]))

    return blocks


# Phase registry the relay calls
PHASE_BUILDERS = {
    "phase1-underlay":  phase1_underlay,
    "phase2-lisp":      phase2_lisp,
    "phase3-overlay":   phase3_vrf_overlay,
    "phase4-access":    phase4_access,
    "phase5-internet":  phase5_internet,
}

# Per-phase verify commands — relay runs these and grep-checks for keywords.
# These are now FUNCTIONAL gates, not just config existence checks:
# phase1 = ISIS adj UP + peer Loopback0 in route table
# phase2 = LISP session UP + MS sees a registered EID  (proves end-to-end CP)
# phase4 = DHCP pool exists + at least one bound or registered EID for VN
VERIFY_CMDS = {
    "phase1-underlay": [
        ("show isis neighbors",                 ["up"]),
        ("show ip interface brief Loopback0",   ["up"]),
        ("show ip pim rp mapping",              ["rp "]),
    ],
    "phase2-lisp": [
        # Functional: session must be Up (means register accepted, key matched,
        # MS site config valid, underlay reachable on TCP 4342).
        ("show lisp session 10.255.255.1",      ["established: 1"]),
    ],
    "phase3-overlay": [
        ("show vrf",                            ["corp_vn"]),
        ("show running-config | section router lisp", ["instance-id 4099"]),
    ],
    "phase4-access": [
        # Functional: edge has a registered EID for CORP_VN visible on MS.
        ("show lisp instance-id 4099 ipv4 server", ["site_uci"]),
        ("show ip dhcp pool",                   ["corp_data_pool"]),
    ],
}

# trigger-deploy: 2026-05-05T06:41:37Z
