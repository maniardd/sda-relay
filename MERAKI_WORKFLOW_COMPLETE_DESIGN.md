# Meraki Workflow — Complete SDA Fabric Deployment
## With Pre-Checks, 6-Phase Deployment, Post-Checks & Rollback

---

## 1. WORKFLOW ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        MERAKI WORKFLOW ENGINE                                │
│                                                                             │
│  ┌─────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────────────────┐  │
│  │ TRIGGER  │──►│  INPUT   │──►│  PRE-    │──►│     6-PHASE DEPLOY       │  │
│  │ (Manual  │   │  FORM    │   │  CHECKS  │   │                          │  │
│  │  or API) │   │ (params) │   │ (health) │   │ 1. Underlay (ISIS/OSPF)  │  │
│  └─────────┘   └──────────┘   └──────────┘   │ 2. LISP Control Plane    │  │
│                                               │ 3. VXLAN Data Plane      │  │
│                                               │ 4. VRF + BGP             │  │
│                                               │ 5. Access Layer          │  │
│                                               │ 6. Security (dot1x)      │  │
│                                               └────────────┬─────────────┘  │
│                                                            │                │
│                              ┌──────────────┐   ┌─────────▼──────────┐     │
│                              │  ROLLBACK     │◄──│   POST-CHECKS      │     │
│                              │  (on failure)  │   │   (validation)     │     │
│                              └──────────────┘   └─────────┬──────────┘     │
│                                                           │                 │
│                              ┌──────────────┐   ┌─────────▼──────────┐     │
│                              │  FAILURE      │   │   SUCCESS           │     │
│                              │  NOTIFICATION │   │   NOTIFICATION      │     │
│                              └──────────────┘   └────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────────┘

Each box = One Meraki Workflow Activity
Each arrow = HTTP POST to Relay Server → RESTCONF to switches
```

---

## 2. WHAT MERAKI WORKFLOWS CAN DO

Meraki Workflows support these activity types:

| Activity Type | What It Does | Our Usage |
|---------------|-------------|-----------|
| **Input Form** | Collects parameters from the operator | Fabric name, VRF names, IPs, VNIs |
| **HTTP Request** | Makes HTTPS POST/GET to external URL | Calls our relay server |
| **Condition** | If/then branching based on response | Check success/failure |
| **Notification** | Sends email/webhook alert | Success/failure alerts |
| **Delay** | Wait N seconds | Pause between deployment phases |
| **End** | Terminates the workflow | Final state |

**Constraint:** Meraki Workflows can ONLY call **public HTTPS URLs** — hence the ngrok + relay server.

---

## 3. COMPLETE WORKFLOW — ACTIVITY BY ACTIVITY

### Activity 1: INPUT FORM — Collect Fabric Parameters

This is the form the operator fills out in the Meraki Dashboard:

```
┌─────────────────────────────────────────────────────┐
│           SDA Fabric Deployment Form                 │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Fabric Name:        [SJC23_SDA_Fabric          ]   │
│                                                      │
│  ── Border Node (C9500) ──────────────────────────  │
│  Border IP:          [192.168.128.9              ]   │
│  Border Loopback0:   [10.255.255.1               ]   │
│  Border Router-ID:   [10.255.255.1               ]   │
│  BGP ASN:            [65001                      ]   │
│                                                      │
│  ── Edge Node (C9300X) ───────────────────────────  │
│  Edge IP:            [192.168.128.7              ]   │
│  Edge Loopback0:     [10.255.255.2               ]   │
│                                                      │
│  ── Fabric Underlay ──────────────────────────────  │
│  P2P Link (Border):  [10.255.0.0/31             ]   │
│  P2P Link (Edge):    [10.255.0.1/31             ]   │
│  ISIS Area:          [49.0001                    ]   │
│  ISIS NET (Border):  [49.0001.0102.5525.5001.00  ]   │
│  ISIS NET (Edge):    [49.0001.0102.5525.5002.00  ]   │
│                                                      │
│  ── Overlay VRFs ─────────────────────────────────  │
│  VRF 1 Name:         [CORP_VN                    ]   │
│  VRF 1 Instance ID:  [4099                       ]   │
│  VRF 1 RD:           [1:4099                     ]   │
│  VRF 1 RT Import:    [1:4099                     ]   │
│  VRF 1 RT Export:    [1:4099                     ]   │
│                                                      │
│  VRF 2 Name:         [GUEST_VN                   ]   │
│  VRF 2 Instance ID:  [4100                       ]   │
│  VRF 2 RD:           [1:4100                     ]   │
│  VRF 2 RT Import:    [1:4100                     ]   │
│  VRF 2 RT Export:    [1:4100                     ]   │
│                                                      │
│  ── Access VLANs (Edge) ──────────────────────────  │
│  VLAN 1 ID:          [100                        ]   │
│  VLAN 1 Name:        [Corp_Data                  ]   │
│  VLAN 1 Subnet:      [10.30.100.0/24            ]   │
│  VLAN 1 Gateway:     [10.30.100.1               ]   │
│  VLAN 1 VRF:         [CORP_VN                    ]   │
│  VLAN 1 L2 VNI:      [8100                       ]   │
│  VLAN 1 DHCP Helper: [10.10.10.1                 ]   │
│                                                      │
│  VLAN 2 ID:          [200                        ]   │
│  VLAN 2 Name:        [Guest_WiFi                 ]   │
│  VLAN 2 Subnet:      [10.30.200.0/24            ]   │
│  VLAN 2 Gateway:     [10.30.200.1               ]   │
│  VLAN 2 VRF:         [GUEST_VN                   ]   │
│  VLAN 2 L2 VNI:      [8200                       ]   │
│  VLAN 2 DHCP Helper: [10.10.10.1                 ]   │
│                                                      │
│  ── Multicast ────────────────────────────────────  │
│  RP Address:         [10.255.255.100             ]   │
│  (Anycast RP on Loopback60000)                       │
│                                                      │
│  ── Fusion/External ──────────────────────────────  │
│  Fusion Router IP:   [10.50.0.2                  ]   │
│  Fusion ASN:         [65535                      ]   │
│  Handoff VLAN:       [3001                       ]   │
│  Handoff Subnet:     [10.50.0.0/30              ]   │
│                                                      │
│              [ Deploy Fabric ]                        │
└─────────────────────────────────────────────────────┘
```

---

### Activity 2: PRE-CHECK — Device Health Verification

**What it does:** Before touching any config, verify both switches are alive, reachable, and ready.

```
Workflow Activity: HTTP POST → Relay Server
Endpoint: POST https://<ngrok-url>/api/v2/precheck
```

**Relay server performs these 8 pre-checks:**

| # | Pre-Check | How (RESTCONF/API) | Pass Criteria |
|---|-----------|-------------------|---------------|
| 1 | **RESTCONF reachable — Border** | `GET /restconf/data/Cisco-IOS-XE-native:native/hostname` | HTTP 200 + hostname returned |
| 2 | **RESTCONF reachable — Edge** | Same endpoint on C9300X | HTTP 200 + hostname returned |
| 3 | **IOS-XE version check** | `GET /restconf/data/Cisco-IOS-XE-native:native/version` | ≥ 17.9.x (LISP+VXLAN support) |
| 4 | **Sufficient memory** | `GET /restconf/data/Cisco-IOS-XE-memory-oper:memory-statistics` | Free memory > 500 MB |
| 5 | **Interface status — P2P link** | `GET /restconf/data/Cisco-IOS-XE-native:native/interface` | Uplink interface status = up |
| 6 | **No existing LISP config** (safety) | `GET /restconf/data/Cisco-IOS-XE-lisp:lisp` | HTTP 404 (not configured) OR skip if force=true |
| 7 | **No existing NVE config** (safety) | `GET /restconf/data/Cisco-IOS-XE-nve:nve` | HTTP 404 (not configured) OR skip if force=true |
| 8 | **DNS/NTP reachable** | `GET /restconf/data/Cisco-IOS-XE-native:native/ntp` | NTP configured |

**Response format back to Meraki:**
```json
{
  "status": "pass",
  "checks": {
    "border_restconf": {"status": "pass", "hostname": "SJC23-BORDER-01"},
    "edge_restconf": {"status": "pass", "hostname": "SJC23-EDGE-01"},
    "border_version": {"status": "pass", "version": "17.12.01"},
    "edge_version": {"status": "pass", "version": "17.12.01"},
    "border_memory": {"status": "pass", "free_mb": 2048},
    "edge_memory": {"status": "pass", "free_mb": 1536},
    "p2p_link_status": {"status": "pass", "interface": "TwentyFiveGigE1/0/1", "state": "up"},
    "no_existing_lisp": {"status": "pass", "note": "clean device"},
    "no_existing_nve": {"status": "pass", "note": "clean device"},
    "ntp_configured": {"status": "pass"}
  },
  "summary": "All 8 pre-checks passed. Ready to deploy."
}
```

---

### Activity 3: CONDITION — Pre-Check Pass/Fail

```
IF response.status == "pass" → Continue to Phase 1
IF response.status == "fail" → Jump to FAILURE NOTIFICATION
```

---

### Activity 4: PHASE 1 — Underlay Configuration

**What gets pushed (via RESTCONF):**

**On BOTH Border + Edge:**
```
✓ System MTU 9100
✓ Loopback0 interface with IP
✓ P2P fabric link with /31 addressing
✓ ISIS process (area, NET, metric-style wide, BFD)
✓ ISIS enabled on P2P link + Loopback0
✓ PIM sparse-mode on all fabric interfaces
✓ PIM RP address (anycast)
✓ BFD on fabric links (100ms interval, multiplier 3)
```

**On Border only:**
```
✓ Loopback60000 (Anycast RLOC) — shared IP for MSDP
✓ MSDP peer configuration (if dual-border)
```

```
Workflow Activity: HTTP POST → Relay Server
Endpoint: POST https://<ngrok-url>/api/v2/deploy/phase1-underlay
```

**Relay server RESTCONF calls (in order):**

| Step | Device | RESTCONF Endpoint | Payload |
|------|--------|-------------------|---------|
| 1.1 | Border | `PATCH /restconf/data/Cisco-IOS-XE-native:native` | `system { mtu 9100 }` |
| 1.2 | Edge | Same | Same |
| 1.3 | Border | `PUT /restconf/data/Cisco-IOS-XE-native:native/interface/Loopback=0` | IP, ISIS, PIM |
| 1.4 | Edge | Same | Different IP |
| 1.5 | Border | `PUT /restconf/data/Cisco-IOS-XE-native:native/interface/Loopback=60000` | Anycast RLOC IP |
| 1.6 | Border | `PATCH /restconf/data/Cisco-IOS-XE-native:native/interface/TwentyFiveGigE=1%2F0%2F1` | P2P link: no switchport, IP, ISIS, PIM, BFD |
| 1.7 | Edge | `PATCH /restconf/data/Cisco-IOS-XE-native:native/interface/TenGigabitEthernet=1%2F1%2F1` | P2P link: no switchport, IP, ISIS, PIM, BFD |
| 1.8 | Border | `PUT /restconf/data/Cisco-IOS-XE-native:native/router/isis` | ISIS process config |
| 1.9 | Edge | Same | Different NET |
| 1.10 | Both | `PUT /restconf/data/Cisco-IOS-XE-native:native/ip/pim` | RP address |

**Phase 1 Validation (inline):**
- Verify ISIS adjacency forms: `GET /restconf/data/Cisco-IOS-XE-isis:isis-state` — check neighbor count > 0
- Verify Loopback0 is reachable from peer (IP SLA probe)

---

### Activity 5: DELAY — 15 seconds

Wait for ISIS adjacency to form and converge.

---

### Activity 6: PHASE 1 VERIFY — Underlay Health

```
Endpoint: POST https://<ngrok-url>/api/v2/verify/phase1-underlay
```

| # | Check | RESTCONF Path | Pass Criteria |
|---|-------|---------------|---------------|
| 1 | ISIS neighbor UP | `Cisco-IOS-XE-isis:isis-state` | At least 1 neighbor in state UP |
| 2 | Loopback0 in ISIS database | `Cisco-IOS-XE-isis:isis-state` | Both loopbacks visible |
| 3 | PIM neighbor formed | `Cisco-IOS-XE-native:native/ip/pim` | PIM neighbor count ≥ 1 |
| 4 | BFD session UP | `Cisco-IOS-XE-bfd-oper:bfd-state` | BFD session state = UP |

---

### Activity 7: CONDITION — Phase 1 Pass/Fail

```
IF pass → Continue to Phase 2
IF fail → Jump to ROLLBACK
```

---

### Activity 8: PHASE 2 — LISP Control Plane

**On Border (Map-Server + Map-Resolver + Proxy-ITR/ETR):**
```
✓ router lisp
✓   locator-table default
✓   locator-set with Loopback0
✓   service ipv4: encapsulation vxlan, map-server, map-resolver, proxy-etr, proxy-itr, sgt
✓   service ethernet: map-server, map-resolver
✓   site definition with authentication key + EID records per instance
✓   ipv4 source-locator Loopback0
```

**On Edge (ITR + ETR):**
```
✓ router lisp
✓   locator-table default
✓   locator-set with Loopback0
✓   service ipv4: encapsulation vxlan, etr map-server (both borders), use-petr (both borders), proxy-itr self, sgt
✓   service ethernet: etr map-server (both borders)
✓   ipv4 source-locator Loopback0
```

```
Endpoint: POST https://<ngrok-url>/api/v2/deploy/phase2-lisp
```

**Phase 2 Validation:**
- LISP session established: `GET /restconf/data/Cisco-IOS-XE-lisp-oper:lisp-state` — session count > 0
- Map-Server accepting registrations

---

### Activity 9: DELAY — 10 seconds (LISP session establishment)

---

### Activity 10: PHASE 2 VERIFY — LISP Health

```
Endpoint: POST https://<ngrok-url>/api/v2/verify/phase2-lisp
```

| # | Check | Pass Criteria |
|---|-------|---------------|
| 1 | LISP session UP (Border ↔ Edge) | At least 1 established session |
| 2 | Map-Server site registered | Site "site_uci" visible |
| 3 | ETR registration accepted | Registration count > 0 |

---

### Activity 11: CONDITION — Phase 2 Pass/Fail

---

### Activity 12: PHASE 3 — VXLAN Data Plane + L3/L2 VNI

**This is the CRITICAL phase — creates the overlay transport:**

**On Border — Per VRF L3 instance:**
```
✓ LISP instance-id 4099 (CORP_VN):
    service ipv4 → eid-table vrf CORP_VN
    database-mapping <handoff-subnet> locator-set <rloc>
    route-export site-registrations
    distance site-registrations 250
    map-cache site-registration

✓ LISP instance-id 4100 (GUEST_VN): same pattern

✓ LISP instance-id 4097 (Default/INFRA):
    service ipv4 → eid-table default
    map-cache site-registration
```

**On Edge — Per VRF L3 instance:**
```
✓ LISP instance-id 4099 (CORP_VN):
    dynamic-eid <name> → database-mapping <subnet> locator-set <rloc>
    service ipv4 → eid-table vrf CORP_VN → map-cache 0.0.0.0/0 map-request

✓ LISP instance-id 4100 (GUEST_VN): same pattern
```

**On Edge — Per VLAN L2 instance:**
```
✓ LISP instance-id 8100:
    service ethernet → eid-table vlan 100
    database-mapping mac locator-set <rloc>

✓ LISP instance-id 8200: same for VLAN 200
```

```
Endpoint: POST https://<ngrok-url>/api/v2/deploy/phase3-vxlan-vni
```

---

### Activity 13: DELAY — 10 seconds

---

### Activity 14: PHASE 4 — VRF + BGP Configuration

**On Border:**
```
✓ VRF definition (CORP_VN, GUEST_VN) with RD + RT
✓ L3 Handoff SVIs (VLAN 3001, etc.) with VRF forwarding
✓ iBGP peers (if dual-border)
✓ eBGP to Fusion router (per VRF address-family)
✓ redistribute lisp metric 10 in each AF
✓ aggregate-address for summarization
✓ Border loopbacks per VRF (for DHCP relay)
```

**On Edge:**
```
✓ VRF definition (CORP_VN, GUEST_VN) — no RD/RT needed on edge
```

```
Endpoint: POST https://<ngrok-url>/api/v2/deploy/phase4-vrf-bgp
```

**Phase 4 Validation:**
- BGP neighbor UP with Fusion: `GET /restconf/data/Cisco-IOS-XE-bgp-oper:bgp-state-data`
- VRF routing table populated

---

### Activity 15: DELAY — 15 seconds (BGP convergence)

---

### Activity 16: PHASE 5 — Access Layer (Edge Only)

**On Edge:**
```
✓ VLAN creation (100, 200, etc.)
✓ SVI interfaces with:
    - mac-address 0000.0c9f.xxxx (anycast gateway)
    - VRF forwarding
    - ip address (gateway)
    - ip helper-address (DHCP)
    - lisp mobility <dynamic-eid-name>
    - no lisp mobility liveness test

✓ Device tracking policy (IPDT_POLICY)
✓ DHCP snooping on access VLANs
✓ Access port template configuration
```

```
Endpoint: POST https://<ngrok-url>/api/v2/deploy/phase5-access
```

---

### Activity 17: PHASE 6 — Security (Optional, if ISE is available)

**On Edge:**
```
✓ AAA configuration (RADIUS server, server groups)
✓ dot1x system-auth-control
✓ Interface templates (ClosedAuth, OpenAuth, LowImpact)
✓ Policy maps (type control subscriber)
✓ CTS role-based enforcement
✓ Access port: source template, spanning-tree portfast, bpduguard
```

```
Endpoint: POST https://<ngrok-url>/api/v2/deploy/phase6-security
```

> **Note:** Phase 6 is optional and should only run if ISE is deployed and RADIUS servers are reachable.

---

### Activity 18: POST-CHECK — Comprehensive Validation

**The most important step — verifies the ENTIRE fabric is working:**

```
Endpoint: POST https://<ngrok-url>/api/v2/postcheck
```

**22 Post-Checks performed by the Relay Server:**

| # | Category | Check | RESTCONF/CLI | Pass Criteria |
|---|----------|-------|-------------|---------------|
| **UNDERLAY** | | | | |
| 1 | ISIS | Neighbor adjacency | `Cisco-IOS-XE-isis:isis-state` | ≥ 1 neighbor UP |
| 2 | ISIS | Route to peer Loopback0 | `Cisco-IOS-XE-isis:isis-state/isis-route` | Peer loopback in DB |
| 3 | BFD | Session state | `Cisco-IOS-XE-bfd-oper:bfd-state` | All sessions UP |
| 4 | PIM | Neighbor formed | `Cisco-IOS-XE-native:native/ip/pim` | ≥ 1 PIM neighbor |
| 5 | Multicast | RP registered | PIM RP mapping | RP = anycast address |
| **LISP** | | | | |
| 6 | LISP | Session established | `Cisco-IOS-XE-lisp-oper:lisp-state` | Sessions UP between all nodes |
| 7 | LISP | Map-Server active (Border) | LISP site summary | Site registered |
| 8 | LISP | Map-Resolver responding | Map-cache populated | ≥ 1 entry per instance |
| 9 | LISP | ETR registrations (Edge) | ETR map-server status | Accepted |
| 10 | LISP | PETR reachable (Edge→Border) | use-petr status | PETR enabled |
| **VXLAN** | | | | |
| 11 | VXLAN | L3 VNI per VRF | LISP instance service | EID-table matches VRF |
| 12 | VXLAN | L2 VNI per VLAN | LISP instance ethernet | EID-table matches VLAN |
| 13 | VXLAN | Encapsulation type | LISP service config | Encapsulation = vxlan |
| **BGP** | | | | |
| 14 | BGP | iBGP peer UP (Border↔Border) | `Cisco-IOS-XE-bgp-oper:bgp-state-data` | Neighbor state = established |
| 15 | BGP | eBGP peer UP (Border↔Fusion) | Same | Neighbor state = established |
| 16 | BGP | LISP routes in BGP | BGP table | `redistribute lisp` routes visible |
| 17 | BGP | Per-VRF address-family active | BGP VRF summary | AF configured per VRF |
| **ACCESS** | | | | |
| 18 | VLAN | SVIs created with correct IP | `Cisco-IOS-XE-native:native/interface/Vlan` | IP matches config |
| 19 | VLAN | Anycast MAC applied | SVI mac-address | mac = 0000.0c9f.xxxx |
| 20 | DHCP | Helper configured | SVI ip helper-address | ≥ 1 helper per SVI |
| 21 | LISP | Dynamic EID mobility | SVI lisp mobility | Mobility pool configured |
| **SECURITY** | | | | |
| 22 | Access | Port template applied | Interface config | source template present |

**Post-Check Response:**
```json
{
  "status": "pass",
  "score": "22/22",
  "fabric_name": "SJC23_SDA_Fabric",
  "timestamp": "2026-04-02T14:30:00Z",
  "checks": {
    "underlay": {"passed": 5, "failed": 0, "details": [...]},
    "lisp": {"passed": 5, "failed": 0, "details": [...]},
    "vxlan": {"passed": 3, "failed": 0, "details": [...]},
    "bgp": {"passed": 4, "failed": 0, "details": [...]},
    "access": {"passed": 4, "failed": 0, "details": [...]},
    "security": {"passed": 1, "failed": 0, "details": [...]}
  },
  "summary": "All 22 post-checks passed. Fabric is fully operational."
}
```

---

### Activity 19: CONDITION — Post-Check Pass/Fail

```
IF score >= 20/22 → SUCCESS (allow minor non-critical failures)
IF score < 20/22  → ROLLBACK
```

---

### Activity 20a: SUCCESS NOTIFICATION

```
To: Network Engineering Team
Subject: ✅ SD-Access Fabric Deployed Successfully: SJC23_SDA_Fabric

Body:
Fabric Name: SJC23_SDA_Fabric
Deployed: 2026-04-02 14:30:00 UTC
Duration: 3 minutes 45 seconds

Border Node: 192.168.128.9 (C9500-32C)
Edge Node:   192.168.128.7 (C9300X-48HXN)

Validation Score: 22/22 ✅
- Underlay (ISIS+BFD+PIM): 5/5 ✅
- LISP Control Plane:       5/5 ✅
- VXLAN Data Plane:          3/3 ✅
- BGP Routing:               4/4 ✅
- Access Layer:              4/4 ✅
- Security:                  1/1 ✅

VRFs Deployed:
- CORP_VN (Instance 4099) — 1 VLAN, 1 subnet
- GUEST_VN (Instance 4100) — 1 VLAN, 1 subnet

Verification Commands:
  Border: show lisp site summary
  Border: show lisp session
  Edge:   show lisp instance-id * ipv4 map-cache
  Edge:   show vlan brief
```

---

### Activity 20b: ROLLBACK (on failure)

```
Endpoint: POST https://<ngrok-url>/api/v2/rollback
```

**Rollback strategy (reverse order):**

| Phase | Rollback Action | RESTCONF Method |
|-------|----------------|-----------------|
| 6 | Remove dot1x templates, AAA config | DELETE |
| 5 | Remove SVIs, VLANs, device-tracking | DELETE |
| 4 | Remove BGP process, VRF definitions, L3 handoff SVIs | DELETE |
| 3 | Remove LISP instances (L3 + L2) | DELETE |
| 2 | Remove router lisp configuration | DELETE |
| 1 | Remove ISIS, P2P link config, Loopbacks | DELETE |

**Rollback saves a backup before clearing:**
```json
{
  "rollback_status": "completed",
  "backup_saved": "/opt/sda-relay/backups/SJC23_SDA_Fabric_20260402_143000.json",
  "phases_rolled_back": [6, 5, 4, 3, 2, 1],
  "devices_cleaned": ["192.168.128.9", "192.168.128.7"]
}
```

---

### Activity 20c: FAILURE NOTIFICATION

```
To: Network Engineering Team
Subject: ❌ SD-Access Deployment FAILED: SJC23_SDA_Fabric

Body:
Fabric Name: SJC23_SDA_Fabric
Failed At: Phase 2 — LISP Control Plane
Error: RESTCONF 400 — Invalid LISP instance configuration

Validation Score: 5/22
- Underlay: 5/5 ✅
- LISP:     0/5 ❌ ← FAILED HERE
- Remaining phases: SKIPPED

Rollback: COMPLETED — all config removed
Backup: /opt/sda-relay/backups/SJC23_SDA_Fabric_20260402_143000.json

Next Steps:
1. Check relay server logs: journalctl -u sda-relay.service --since "30 min ago"
2. Verify YANG payload structure matches IOS-XE version
3. Test RESTCONF manually: curl -k https://192.168.128.9:443/restconf/data/Cisco-IOS-XE-lisp:lisp
4. Re-run workflow after fixing the issue
```

---

### Activity 21: END

---

## 4. VISUAL WORKFLOW MAP

```
                    ┌──────────────────┐
                    │  1. INPUT FORM    │
                    │  (collect params) │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  2. PRE-CHECK     │ POST /api/v2/precheck
                    │  (8 health tests) │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐     ┌─────────────────┐
                    │  3. CONDITION     │─NO──►  FAIL NOTIFY    │
                    │  (all pass?)      │     │  (abort, no     │
                    └────────┬─────────┘     │   config pushed) │
                          YES│               └─────────────────┘
                    ┌────────▼─────────┐
                    │  4. PHASE 1       │ POST /api/v2/deploy/phase1-underlay
                    │  UNDERLAY         │
                    │  (ISIS+BFD+PIM)   │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  5. DELAY 15s     │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  6. PHASE 1       │ POST /api/v2/verify/phase1-underlay
                    │  VERIFY           │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐     ┌──────────────────┐
                    │  7. CONDITION     │─NO──►  ROLLBACK        │──► FAIL NOTIFY
                    └────────┬─────────┘     │  Phase 1 cleanup  │
                          YES│               └──────────────────┘
                    ┌────────▼─────────┐
                    │  8. PHASE 2       │ POST /api/v2/deploy/phase2-lisp
                    │  LISP CONTROL     │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  9. DELAY 10s     │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  10. PHASE 2      │ POST /api/v2/verify/phase2-lisp
                    │  VERIFY           │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐     ┌──────────────────┐
                    │  11. CONDITION    │─NO──►  ROLLBACK        │──► FAIL NOTIFY
                    └────────┬─────────┘     │  Phase 2+1       │
                          YES│               └──────────────────┘
                    ┌────────▼─────────┐
                    │  12. PHASE 3      │ POST /api/v2/deploy/phase3-vxlan-vni
                    │  VXLAN + VNI      │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  13. DELAY 10s    │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  14. PHASE 4      │ POST /api/v2/deploy/phase4-vrf-bgp
                    │  VRF + BGP        │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  15. DELAY 15s    │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  16. PHASE 5      │ POST /api/v2/deploy/phase5-access
                    │  ACCESS LAYER     │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  17. PHASE 6      │ POST /api/v2/deploy/phase6-security
                    │  SECURITY         │ (optional — skip if no ISE)
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  18. POST-CHECK   │ POST /api/v2/postcheck
                    │  (22 validations) │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  19. CONDITION    │
                    │  (score ≥ 20?)    │
                    └───┬──────────┬───┘
                     YES│          │NO
              ┌─────────▼──┐  ┌───▼──────────────┐
              │ 20a.SUCCESS│  │ 20b. ROLLBACK     │
              │ NOTIFY     │  │ (reverse all 6    │
              └─────────┬──┘  │  phases)          │
                        │     └───┬──────────────┘
                        │         │
                        │     ┌───▼──────────────┐
                        │     │ 20c. FAIL NOTIFY  │
                        │     └───┬──────────────┘
                        │         │
                    ┌───▼─────────▼───┐
                    │    21. END       │
                    └─────────────────┘
```

---

## 5. WORKFLOW TIMING

| Phase | Duration | Cumulative | What Happens |
|-------|----------|------------|----------|
| Input Form | Manual | — | Operator fills form |
| Pre-Check | ~5 sec | 5 sec | 8 health checks via RESTCONF |
| Phase 1 (Underlay) | ~10 sec | 15 sec | 10 RESTCONF calls |
| Delay + Verify | 15 + 5 sec | 35 sec | ISIS convergence + verify |
| Phase 2 (LISP) | ~8 sec | 43 sec | 6 RESTCONF calls |
| Delay + Verify | 10 + 5 sec | 58 sec | LISP session + verify |
| Phase 3 (VXLAN/VNI) | ~12 sec | 70 sec | 8+ RESTCONF calls (per VRF+VLAN) |
| Delay | 10 sec | 80 sec | |
| Phase 4 (VRF+BGP) | ~15 sec | 95 sec | 10+ RESTCONF calls |
| Delay | 15 sec | 110 sec | BGP convergence |
| Phase 5 (Access) | ~10 sec | 120 sec | VLANs, SVIs, templates |
| Phase 6 (Security) | ~8 sec | 128 sec | dot1x/AAA (optional) |
| Post-Check | ~15 sec | 143 sec | 22 validation checks |
| Notification | ~2 sec | **~2.5 min** | Email sent |

**Total deployment time: ~2.5 minutes** (vs. 30-60 minutes manually, or 15-20 minutes via Catalyst Center)

---

## 6. MERAKI WORKFLOW JSON — STRUCTURE

This is the actual Meraki Workflow export format. You import this directly into Meraki Dashboard:

```json
{
  "version": "2.0",
  "name": "SDA-Fabric-Full-Deployment-v2",
  "description": "Complete SD-Access fabric (LISP+VXLAN+BGP) deployment with pre/post checks and rollback",
  "trigger": "manual",
  "targets": [
    {
      "name": "SDA_Relay_Server",
      "type": "HTTPS",
      "url": "https://YOUR-NGROK-URL.ngrok-free.app",
      "headers": {
        "X-Webhook-Secret": "${{ secrets.WEBHOOK_SECRET }}"
      }
    }
  ],
  "activities": [
    "1_input_form",
    "2_precheck → relay /api/v2/precheck",
    "3_condition (pass/fail)",
    "4_phase1_underlay → relay /api/v2/deploy/phase1-underlay",
    "5_delay_15s",
    "6_phase1_verify → relay /api/v2/verify/phase1-underlay",
    "7_condition",
    "... (8-17 as shown above)",
    "18_postcheck → relay /api/v2/postcheck",
    "19_condition",
    "20a_success_notify / 20b_rollback / 20c_fail_notify",
    "21_end"
  ]
}
```

> I will create the actual importable JSON file when we build the v2 code. The structure above shows the complete design.

---

## 7. HOW TO CREATE THIS IN MERAKI DASHBOARD

### Step-by-Step

1. **Login** → dashboard.meraki.com → Select your Org
2. **Navigate** → Organization → Automation → Workflows
3. **Create New Workflow** → Name: "SDA-Fabric-Full-Deployment-v2"
4. **Add Trigger** → Manual (or Schedule/API)
5. **Add Activity: Input Form** → Add all fields from Section 3, Activity 1
6. **Add Activity: HTTP Request** → Method: POST, URL: `https://ngrok-url/api/v2/precheck`
7. **Add Activity: Condition** → Check `response.body.status == "pass"`
8. **Branch TRUE** → Continue building Phase 1-6
9. **Branch FALSE** → Add Notification (failure email)
10. **Repeat** the pattern: HTTP Request → Delay → HTTP Request (verify) → Condition → next phase
11. **Final**: Post-Check HTTP → Condition → Success/Rollback/Fail notification
12. **Save and Test** with a dry-run first

### Meraki Workflow Limitations to Know

| Limitation | Impact | Workaround |
|-----------|--------|------------|
| Max 20 activities per workflow | Our design uses ~21 | Combine Phase 3+4 into single call |
| HTTP timeout: 30 sec per call | Some phases have many RESTCONF calls | Relay does all calls internally, returns summary |
| No loops/iteration | Can't loop through VLANs | Relay handles iteration in Python |
| Variables limited to form + response | Can't store intermediate state | Relay maintains deployment state |
| HTTPS only (no HTTP) | Must use TLS endpoint | ngrok provides HTTPS automatically |

---

## 8. RELAY SERVER API ENDPOINTS (v2)

The Workflow calls these endpoints on the relay server:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Server alive check |
| `/api/v2/precheck` | POST | Run 8 pre-deployment checks |
| `/api/v2/deploy/phase1-underlay` | POST | Deploy ISIS, BFD, PIM, Loopbacks |
| `/api/v2/verify/phase1-underlay` | POST | Verify underlay health |
| `/api/v2/deploy/phase2-lisp` | POST | Deploy LISP control plane |
| `/api/v2/verify/phase2-lisp` | POST | Verify LISP sessions |
| `/api/v2/deploy/phase3-vxlan-vni` | POST | Deploy L3/L2 VNI instances |
| `/api/v2/deploy/phase4-vrf-bgp` | POST | Deploy VRFs + BGP routing |
| `/api/v2/deploy/phase5-access` | POST | Deploy VLANs, SVIs, templates |
| `/api/v2/deploy/phase6-security` | POST | Deploy dot1x/AAA (optional) |
| `/api/v2/postcheck` | POST | Run 22 post-deployment validations |
| `/api/v2/rollback` | POST | Reverse all deployed config |
| `/api/v2/status` | GET | Current deployment state |
| `/api/v2/backup` | GET | Download config backup |

Each endpoint receives the full form parameters from the Meraki Workflow in the POST body and returns a standardized response:

```json
{
  "status": "pass|fail|error",
  "phase": "phase1-underlay",
  "duration_seconds": 8.5,
  "steps_completed": 10,
  "steps_total": 10,
  "details": [...],
  "message": "Phase 1 underlay deployed successfully"
}
```
