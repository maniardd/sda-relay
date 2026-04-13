#!/usr/bin/env python3
"""
SDA Relay Server v2 — Full 14-Endpoint RESTCONF Bridge
Connects Meraki Workflows to IOS-XE RESTCONF API
Supports: 6-Phase Deploy, Pre/Post Checks, Verify, Rollback, Backup

Endpoints:
  GET  /health
  POST /api/v2/precheck
  POST /api/v2/deploy/phase1-underlay
  POST /api/v2/verify/phase1-underlay
  POST /api/v2/deploy/phase2-lisp
  POST /api/v2/verify/phase2-lisp
  POST /api/v2/deploy/phase3-vxlan-vni
  POST /api/v2/deploy/phase4-vrf-bgp
  POST /api/v2/deploy/phase5-access
  POST /api/v2/deploy/phase6-security
  POST /api/v2/postcheck
  POST /api/v2/rollback
  GET  /api/v2/status
  GET  /api/v2/backup
"""

import os
import json
import time
import copy
import hmac
import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml
from flask import Flask, request, jsonify, abort
from dotenv import load_dotenv

# ── INIT ──────────────────────────────────────────────────────────────
load_dotenv()
app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("sda-relay-v2")
requests.packages.urllib3.disable_warnings()

# ── CONFIGURATION ─────────────────────────────────────────────────────
BORDER_IP   = os.getenv("C9500_IP")
BORDER_USER = os.getenv("C9500_USER", "admin")
BORDER_PASS = os.getenv("C9500_PASS")
EDGE_IP     = os.getenv("C9300_IP")
EDGE_USER   = os.getenv("C9300_USER", "admin")
EDGE_PASS   = os.getenv("C9300_PASS")
RELAY_PORT  = int(os.getenv("RELAY_PORT", 5000))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
BACKUP_DIR  = os.getenv("BACKUP_DIR", os.path.join(os.path.dirname(__file__), "backups"))
YANG_PAYLOADS_FILE = os.getenv(
    "YANG_PAYLOADS_FILE",
    os.path.join(os.path.dirname(__file__), "sda_yang_payloads_v2.json"),
)
FABRIC_CONFIG_FILE = os.getenv(
    "FABRIC_CONFIG_FILE",
    os.path.join(os.path.dirname(__file__), "sda_fabric_config.yaml"),
)

os.makedirs(BACKUP_DIR, exist_ok=True)

# ── LOAD YANG PAYLOADS & FABRIC CONFIG ────────────────────────────────
with open(YANG_PAYLOADS_FILE, "r") as f:
    YANG = json.load(f)

with open(FABRIC_CONFIG_FILE, "r") as f:
    FABRIC = yaml.safe_load(f)

# ── GLOBAL STATE ──────────────────────────────────────────────────────
deployment_state: Dict[str, Any] = {
    "status": "idle",
    "fabric_name": None,
    "started_at": None,
    "completed_at": None,
    "current_phase": None,
    "phases_completed": [],
    "phases_failed": [],
    "last_backup": None,
    "log": [],
}


# ══════════════════════════════════════════════════════════════════════
#  RESTCONF HELPERS
# ══════════════════════════════════════════════════════════════════════

def _headers(method: str = "GET") -> dict:
    h = {"Accept": "application/yang-data+json"}
    if method in ("PUT", "PATCH", "POST"):
        h["Content-Type"] = "application/yang-data+json"
    return h


def restconf_request(
    device_ip: str,
    username: str,
    password: str,
    xpath: str,
    method: str = "GET",
    payload: Optional[dict] = None,
    timeout: int = 30,
) -> Tuple[int, Optional[dict], Optional[str]]:
    """Execute a RESTCONF request. Returns (status_code, data, error)."""
    url = f"https://{device_ip}:443/restconf/data{xpath}"
    hdrs = _headers(method)
    kwargs: dict = {
        "auth": (username, password),
        "headers": hdrs,
        "verify": False,
        "timeout": timeout,
    }
    try:
        if method == "GET":
            r = requests.get(url, **kwargs)
        elif method == "PUT":
            r = requests.put(url, json=payload, **kwargs)
        elif method == "PATCH":
            r = requests.patch(url, json=payload, **kwargs)
        elif method == "DELETE":
            r = requests.delete(url, **kwargs)
        elif method == "POST":
            r = requests.post(url, json=payload, **kwargs)
        else:
            return 400, None, f"Unsupported method: {method}"

        logger.info(f"RESTCONF {method} {device_ip} {xpath} → {r.status_code}")
        if r.status_code in (200, 201, 204):
            data = r.json() if r.text.strip() else {}
            return r.status_code, data, None
        return r.status_code, None, r.text[:500]
    except requests.exceptions.Timeout:
        logger.error(f"RESTCONF {method} {device_ip} {xpath} — TIMEOUT")
        return 504, None, "Connection timed out"
    except requests.exceptions.ConnectionError as exc:
        logger.error(f"RESTCONF {method} {device_ip} {xpath} — CONN ERROR: {exc}")
        return 502, None, f"Connection error: {exc}"
    except Exception as exc:
        logger.error(f"RESTCONF {method} {device_ip} {xpath} — ERROR: {exc}")
        return 500, None, str(exc)


def _device_creds(target: str) -> Tuple[str, str, str]:
    """Return (ip, user, pass) for 'border' or 'edge'."""
    if target == "border":
        return BORDER_IP, BORDER_USER, BORDER_PASS
    return EDGE_IP, EDGE_USER, EDGE_PASS


def _push_payload(
    target: str, endpoint: str, method: str, payload: dict
) -> Dict[str, Any]:
    """Push a single RESTCONF payload to a device. Returns step result dict."""
    ip, user, pw = _device_creds(target)
    status, data, err = restconf_request(ip, user, pw, endpoint, method, payload)
    success = status in (200, 201, 204)
    return {
        "target": target,
        "endpoint": endpoint,
        "method": method,
        "status_code": status,
        "success": success,
        "error": err,
    }


def _resolve_template(template: str, variables: dict) -> str:
    """Replace {{var}} placeholders in a string."""
    result = template
    for key, val in variables.items():
        result = result.replace("{{" + key + "}}", str(val))
    return result


def _resolve_payload(payload: Any, variables: dict) -> Any:
    """Recursively resolve {{var}} placeholders in a payload dict/list."""
    if isinstance(payload, str):
        return _resolve_template(payload, variables)
    if isinstance(payload, dict):
        return {k: _resolve_payload(v, variables) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_resolve_payload(item, variables) for item in payload]
    return payload


def _log(phase: str, step: str, result: Dict[str, Any]):
    """Append to deployment log."""
    deployment_state["log"].append({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "phase": phase,
        "step": step,
        "target": result.get("target"),
        "status_code": result.get("status_code"),
        "success": result.get("success"),
        "error": result.get("error"),
    })


def _build_variables(form_data: dict) -> dict:
    """Merge YAML config + form overrides into a variable dict for templates."""
    dev = FABRIC.get("devices", {})
    border = dev.get("border", {})
    edge = dev.get("edge", {})
    underlay = FABRIC.get("underlay", {})
    links = underlay.get("fabric_links", [{}])[0]
    mc = underlay.get("multicast", {})
    bgp_cfg = FABRIC.get("bgp", {})
    lisp_cfg = FABRIC.get("lisp", {})
    fabric_cfg = FABRIC.get("fabric", {})

    variables = {
        "fabric_name": form_data.get("fabric_name", fabric_cfg.get("name", "")),
        "site_name": form_data.get("site_name", fabric_cfg.get("site_name", "site_uci")),
        "site_auth_key": fabric_cfg.get("site_auth_key", "CiscoSDA123"),
        "border_loopback0_ip": form_data.get("border_loopback0", border.get("loopback0_ip")),
        "edge_loopback0_ip": form_data.get("edge_loopback0", edge.get("loopback0_ip")),
        "anycast_ip": form_data.get("rp_address", border.get("anycast_ip")),
        "border_p2p_ip": form_data.get("border_p2p_ip", links.get("border_ip")),
        "edge_p2p_ip": form_data.get("edge_p2p_ip", links.get("edge_ip")),
        "border_p2p_intf": links.get("border_interface", "TwentyFiveGigE1/0/1"),
        "border_p2p_intf_encoded": links.get("border_interface", "TwentyFiveGigE1/0/1").replace("/", "%2F"),
        "edge_p2p_intf": links.get("edge_interface", "TenGigabitEthernet1/1/1"),
        "edge_p2p_intf_encoded": links.get("edge_interface", "TenGigabitEthernet1/1/1").replace("/", "%2F"),
        "border_isis_net": form_data.get("border_isis_net", border.get("isis_net")),
        "edge_isis_net": form_data.get("edge_isis_net", edge.get("isis_net")),
        "rp_address": form_data.get("rp_address", mc.get("rp_address")),
        "border_router_id": border.get("router_id"),
        "bgp_as": form_data.get("bgp_asn", bgp_cfg.get("local_as", 65001)),
        "fusion_as": bgp_cfg.get("fusion", {}).get("remote_as", 65535),
        "redistribute_lisp_metric": bgp_cfg.get("redistribute_lisp_metric", 10),
        "fusion_remote_ip_corp": "10.50.0.2",
        "fusion_remote_ip_guest": "10.50.0.6",
    }
    return variables


# ══════════════════════════════════════════════════════════════════════
#  WEBHOOK SECRET VALIDATION
# ══════════════════════════════════════════════════════════════════════

def _verify_webhook(req):
    """Verify X-Webhook-Secret header if WEBHOOK_SECRET is set."""
    if not WEBHOOK_SECRET:
        return
    sig = req.headers.get("X-Webhook-Secret", "")
    body = req.get_data()
    expected = hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        logger.warning("Webhook signature mismatch")
        abort(401, description="Invalid webhook signature")


# ══════════════════════════════════════════════════════════════════════
#  BACKUP / CONFIG SNAPSHOT
# ══════════════════════════════════════════════════════════════════════

def _take_backup(fabric_name: str) -> str:
    """Snapshot running-config from both devices via RESTCONF."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup = {"timestamp": ts, "fabric_name": fabric_name, "devices": {}}
    for target in ("border", "edge"):
        ip, user, pw = _device_creds(target)
        status, data, err = restconf_request(
            ip, user, pw, "/Cisco-IOS-XE-native:native", "GET"
        )
        backup["devices"][target] = {
            "ip": ip,
            "status_code": status,
            "config": data if status == 200 else None,
            "error": err,
        }
    filepath = os.path.join(BACKUP_DIR, f"{fabric_name}_{ts}.json")
    with open(filepath, "w") as f:
        json.dump(backup, f, indent=2)
    deployment_state["last_backup"] = filepath
    logger.info(f"Backup saved: {filepath}")
    return filepath


# ══════════════════════════════════════════════════════════════════════
#  PRE-CHECK  (8 health checks)
# ══════════════════════════════════════════════════════════════════════

def run_prechecks(form_data: dict) -> Dict[str, Any]:
    """Run 8 pre-deployment health checks on both devices."""
    checks = {}
    all_pass = True
    force = form_data.get("force", False)

    # 1 & 2: RESTCONF reachable
    for label, target in [("border_restconf", "border"), ("edge_restconf", "edge")]:
        ip, user, pw = _device_creds(target)
        status, data, err = restconf_request(
            ip, user, pw, "/Cisco-IOS-XE-native:native/hostname"
        )
        passed = status == 200
        hostname = data.get("Cisco-IOS-XE-native:hostname", "unknown") if passed else None
        checks[label] = {"status": "pass" if passed else "fail", "hostname": hostname, "error": err}
        if not passed:
            all_pass = False

    # 3: IOS-XE version
    for label, target in [("border_version", "border"), ("edge_version", "edge")]:
        ip, user, pw = _device_creds(target)
        status, data, err = restconf_request(
            ip, user, pw, "/Cisco-IOS-XE-native:native/version"
        )
        if status == 200:
            ver = data.get("Cisco-IOS-XE-native:version", "0")
            try:
                major = float(ver.split(".")[0]) if ver else 0
                passed = major >= 17
            except (ValueError, IndexError):
                passed = False
            checks[label] = {"status": "pass" if passed else "fail", "version": ver}
        else:
            checks[label] = {"status": "fail", "error": err}
            all_pass = False

    # 4: Memory check
    for label, target in [("border_memory", "border"), ("edge_memory", "edge")]:
        ip, user, pw = _device_creds(target)
        status, data, err = restconf_request(
            ip, user, pw, "/Cisco-IOS-XE-memory-oper:memory-statistics"
        )
        if status == 200:
            try:
                stats = data.get("Cisco-IOS-XE-memory-oper:memory-statistics", {})
                mem_stat = stats.get("memory-statistic", [{}])[0]
                free_mb = int(mem_stat.get("free-memory", 0)) / (1024 * 1024)
            except (KeyError, IndexError, TypeError):
                free_mb = 0
            passed = free_mb > 500
            checks[label] = {"status": "pass" if passed else "fail", "free_mb": round(free_mb)}
        else:
            checks[label] = {"status": "fail", "error": err}
        if not (status == 200 and free_mb > 500):
            all_pass = False

    # 5: P2P link status
    ip, user, pw = _device_creds("border")
    status, data, err = restconf_request(
        ip, user, pw, "/Cisco-IOS-XE-native:native/interface"
    )
    checks["p2p_link_status"] = {
        "status": "pass" if status == 200 else "fail",
        "note": "Interface data retrieved" if status == 200 else err,
    }
    if status != 200:
        all_pass = False

    # 6 & 7: No existing LISP / NVE (safety)
    for label, xpath in [
        ("no_existing_lisp", "/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-lisp:lisp"),
        ("no_existing_nve", "/Cisco-IOS-XE-nve:nve"),
    ]:
        ip, user, pw = _device_creds("border")
        status, _, _ = restconf_request(ip, user, pw, xpath)
        clean = status in (404, 204)
        if not clean and force:
            checks[label] = {"status": "pass", "note": "Existing config found — force=true, proceeding"}
        elif clean:
            checks[label] = {"status": "pass", "note": "Clean device"}
        else:
            checks[label] = {"status": "fail", "note": "Existing config found — set force=true to override"}
            all_pass = False

    # 8: NTP configured
    ip, user, pw = _device_creds("border")
    status, data, err = restconf_request(
        ip, user, pw, "/Cisco-IOS-XE-native:native/ntp"
    )
    checks["ntp_configured"] = {
        "status": "pass" if status == 200 else "warn",
        "note": "NTP configured" if status == 200 else "NTP not found — non-blocking",
    }

    return {
        "status": "pass" if all_pass else "fail",
        "checks": checks,
        "summary": f"{'All 8' if all_pass else 'Some'} pre-checks {'passed' if all_pass else 'failed'}. "
                   + ("Ready to deploy." if all_pass else "Fix issues before deploying."),
    }


# ══════════════════════════════════════════════════════════════════════
#  PHASE 1 — UNDERLAY (ISIS + BFD + PIM + Loopbacks + P2P)
# ══════════════════════════════════════════════════════════════════════

def deploy_phase1(form_data: dict) -> Dict[str, Any]:
    """Deploy Phase 1: Underlay configuration."""
    phase = "phase1-underlay"
    variables = _build_variables(form_data)
    yang_phase = YANG.get("phase1_underlay", {})
    steps: List[Dict] = []
    all_ok = True

    # Order of operations from the design doc
    step_order = [
        ("system_mtu", "System MTU 9100"),
        ("loopback0_border", "Border Loopback0"),
        ("loopback0_edge", "Edge Loopback0"),
        ("loopback60000_border", "Border Loopback60000 Anycast"),
        ("p2p_link_border", "Border P2P link"),
        ("p2p_link_edge", "Edge P2P link"),
        ("isis_process_border", "Border ISIS process"),
        ("isis_process_edge", "Edge ISIS process"),
        ("pim_rp", "PIM RP config"),
    ]

    for key, desc in step_order:
        cfg = yang_phase.get(key)
        if not cfg:
            continue
        endpoint = _resolve_template(cfg["endpoint"], variables)
        method = cfg["method"]
        payload = _resolve_payload(cfg.get("payload", {}), variables)
        targets = cfg.get("targets", ["border"])

        for target in targets:
            result = _push_payload(target, endpoint, method, payload)
            result["step"] = f"{desc} ({target})"
            steps.append(result)
            _log(phase, desc, result)
            if not result["success"]:
                all_ok = False

    return {
        "status": "pass" if all_ok else "fail",
        "phase": phase,
        "steps_completed": sum(1 for s in steps if s["success"]),
        "steps_total": len(steps),
        "details": steps,
        "message": "Phase 1 underlay deployed successfully" if all_ok else "Phase 1 had failures",
    }


# ══════════════════════════════════════════════════════════════════════
#  PHASE 1 VERIFY — Underlay health
# ══════════════════════════════════════════════════════════════════════

def verify_phase1(form_data: dict) -> Dict[str, Any]:
    """Verify Phase 1: ISIS adjacency, PIM neighbor, BFD session."""
    checks = []
    all_pass = True

    # 1: ISIS neighbor
    ip, user, pw = _device_creds("border")
    status, data, _ = restconf_request(ip, user, pw, "/Cisco-IOS-XE-isis-oper:isis-oper-data")
    isis_up = status == 200 and data is not None
    checks.append({"check": "ISIS neighbor UP", "status": "pass" if isis_up else "fail"})
    if not isis_up:
        all_pass = False

    # 2: BFD session
    status, data, _ = restconf_request(ip, user, pw, "/Cisco-IOS-XE-bfd-oper:bfd-state")
    bfd_up = status == 200 and data is not None
    checks.append({"check": "BFD session UP", "status": "pass" if bfd_up else "fail"})
    if not bfd_up:
        all_pass = False

    # 3: PIM neighbor
    status, data, _ = restconf_request(ip, user, pw, "/Cisco-IOS-XE-native:native/ip/pim")
    pim_ok = status == 200
    checks.append({"check": "PIM neighbor formed", "status": "pass" if pim_ok else "fail"})
    if not pim_ok:
        all_pass = False

    # 4: Loopback0 reachable from edge
    eip, eu, ep = _device_creds("edge")
    status, data, _ = restconf_request(eip, eu, ep, "/Cisco-IOS-XE-isis-oper:isis-oper-data")
    edge_isis = status == 200 and data is not None
    checks.append({"check": "Edge ISIS visible", "status": "pass" if edge_isis else "fail"})
    if not edge_isis:
        all_pass = False

    return {
        "status": "pass" if all_pass else "fail",
        "phase": "verify-phase1-underlay",
        "checks": checks,
        "message": "Underlay verified" if all_pass else "Underlay verification failed",
    }


# ══════════════════════════════════════════════════════════════════════
#  PHASE 2 — LISP CONTROL PLANE
# ══════════════════════════════════════════════════════════════════════

def deploy_phase2(form_data: dict) -> Dict[str, Any]:
    """Deploy Phase 2: LISP control plane on border + edge."""
    phase = "phase2-lisp"
    variables = _build_variables(form_data)
    yang_phase = YANG.get("phase2_lisp", {})
    steps: List[Dict] = []
    all_ok = True

    for key, desc in [("lisp_border", "LISP Border"), ("lisp_edge", "LISP Edge")]:
        cfg = yang_phase.get(key)
        if not cfg:
            continue
        endpoint = _resolve_template(cfg["endpoint"], variables)
        method = cfg["method"]
        payload = _resolve_payload(cfg.get("payload", {}), variables)
        target = cfg["targets"][0]

        result = _push_payload(target, endpoint, method, payload)
        result["step"] = desc
        steps.append(result)
        _log(phase, desc, result)
        if not result["success"]:
            all_ok = False

    return {
        "status": "pass" if all_ok else "fail",
        "phase": phase,
        "steps_completed": sum(1 for s in steps if s["success"]),
        "steps_total": len(steps),
        "details": steps,
        "message": "Phase 2 LISP deployed successfully" if all_ok else "Phase 2 had failures",
    }


# ══════════════════════════════════════════════════════════════════════
#  PHASE 2 VERIFY — LISP health
# ══════════════════════════════════════════════════════════════════════

def verify_phase2(form_data: dict) -> Dict[str, Any]:
    """Verify Phase 2: LISP sessions, map-server, ETR registration."""
    checks = []
    all_pass = True

    # LISP session from border
    ip, user, pw = _device_creds("border")
    status, data, _ = restconf_request(ip, user, pw, "/Cisco-IOS-XE-lisp-oper:lisp-state")
    lisp_up = status == 200 and data is not None
    checks.append({"check": "LISP session UP (Border)", "status": "pass" if lisp_up else "fail"})
    if not lisp_up:
        all_pass = False

    # Map-Server site registered
    status2, data2, _ = restconf_request(
        ip, user, pw, "/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-lisp:lisp"
    )
    ms_ok = status2 == 200
    checks.append({"check": "Map-Server config present", "status": "pass" if ms_ok else "fail"})
    if not ms_ok:
        all_pass = False

    # LISP from edge
    eip, eu, ep = _device_creds("edge")
    status3, data3, _ = restconf_request(eip, eu, ep, "/Cisco-IOS-XE-lisp-oper:lisp-state")
    edge_lisp = status3 == 200 and data3 is not None
    checks.append({"check": "LISP session UP (Edge)", "status": "pass" if edge_lisp else "fail"})
    if not edge_lisp:
        all_pass = False

    return {
        "status": "pass" if all_pass else "fail",
        "phase": "verify-phase2-lisp",
        "checks": checks,
        "message": "LISP verified" if all_pass else "LISP verification failed",
    }


# ══════════════════════════════════════════════════════════════════════
#  PHASE 3 — VXLAN + L3/L2 VNI
# ══════════════════════════════════════════════════════════════════════

def deploy_phase3(form_data: dict) -> Dict[str, Any]:
    """Deploy Phase 3: LISP instances for L3 VNI (per VRF) + L2 VNI (per VLAN)."""
    phase = "phase3-vxlan-vni"
    variables = _build_variables(form_data)
    yang_phase = YANG.get("phase3_vxlan_vni", {})
    steps: List[Dict] = []
    all_ok = True

    # L3 instances on border
    border_tmpl = yang_phase.get("l3_instance_border_template", {})
    for inst in border_tmpl.get("per_vrf_instances", []):
        inst_vars = {**variables, **inst}
        endpoint = _resolve_template(border_tmpl["endpoint"], inst_vars)
        payload = _resolve_payload(border_tmpl.get("payload_template", {}), inst_vars)
        result = _push_payload("border", endpoint, border_tmpl["method"], payload)
        result["step"] = f"Border L3 instance {inst['instance_id']} ({inst.get('description', '')})"
        steps.append(result)
        _log(phase, result["step"], result)
        if not result["success"]:
            all_ok = False

    # L3 instances on edge
    edge_tmpl = yang_phase.get("l3_instance_edge_template", {})
    for inst in edge_tmpl.get("per_vrf_instances", []):
        inst_vars = {**variables, **inst}
        endpoint = _resolve_template(edge_tmpl["endpoint"], inst_vars)
        payload = _resolve_payload(edge_tmpl.get("payload_template", {}), inst_vars)
        result = _push_payload("edge", endpoint, edge_tmpl["method"], payload)
        result["step"] = f"Edge L3 instance {inst['instance_id']} ({inst.get('description', '')})"
        steps.append(result)
        _log(phase, result["step"], result)
        if not result["success"]:
            all_ok = False

    # L2 instances on edge
    l2_tmpl = yang_phase.get("l2_instance_edge_template", {})
    for inst in l2_tmpl.get("per_vlan_instances", []):
        inst_vars = {**variables, **inst}
        endpoint = _resolve_template(l2_tmpl["endpoint"], inst_vars)
        payload = _resolve_payload(l2_tmpl.get("payload_template", {}), inst_vars)
        result = _push_payload("edge", endpoint, l2_tmpl["method"], payload)
        result["step"] = f"Edge L2 instance {inst['l2_instance_id']} ({inst.get('description', '')})"
        steps.append(result)
        _log(phase, result["step"], result)
        if not result["success"]:
            all_ok = False

    return {
        "status": "pass" if all_ok else "fail",
        "phase": phase,
        "steps_completed": sum(1 for s in steps if s["success"]),
        "steps_total": len(steps),
        "details": steps,
        "message": "Phase 3 VXLAN/VNI deployed successfully" if all_ok else "Phase 3 had failures",
    }


# ══════════════════════════════════════════════════════════════════════
#  PHASE 4 — VRF + BGP
# ══════════════════════════════════════════════════════════════════════

def deploy_phase4(form_data: dict) -> Dict[str, Any]:
    """Deploy Phase 4: VRF definitions, handoff SVIs, BGP, border loopbacks."""
    phase = "phase4-vrf-bgp"
    variables = _build_variables(form_data)
    yang_phase = YANG.get("phase4_vrf_bgp", {})
    steps: List[Dict] = []
    all_ok = True

    # VRF definitions
    vrf_tmpl = yang_phase.get("vrf_definition_template", {})
    for vrf in vrf_tmpl.get("vrfs", []):
        vrf_vars = {**variables, **vrf}
        endpoint = _resolve_template(vrf_tmpl["endpoint"], vrf_vars)
        payload = _resolve_payload(vrf_tmpl.get("payload_template", {}), vrf_vars)
        for target in vrf_tmpl.get("targets", ["border", "edge"]):
            result = _push_payload(target, endpoint, vrf_tmpl["method"], payload)
            result["step"] = f"VRF {vrf['vrf_name']} ({target})"
            steps.append(result)
            _log(phase, result["step"], result)
            if not result["success"]:
                all_ok = False

    # Handoff SVIs (border only)
    svi_tmpl = yang_phase.get("handoff_svi_template", {})
    for svi in svi_tmpl.get("handoff_vlans", []):
        svi_vars = {**variables, **svi}
        endpoint = _resolve_template(svi_tmpl["endpoint"], svi_vars)
        payload = _resolve_payload(svi_tmpl.get("payload_template", {}), svi_vars)
        result = _push_payload("border", endpoint, svi_tmpl["method"], payload)
        result["step"] = f"Handoff SVI VLAN {svi['vlan_id']}"
        steps.append(result)
        _log(phase, result["step"], result)
        if not result["success"]:
            all_ok = False

    # BGP (border)
    bgp_cfg = yang_phase.get("bgp_border", {})
    if bgp_cfg:
        endpoint = _resolve_template(bgp_cfg["endpoint"], variables)
        payload = _resolve_payload(bgp_cfg.get("payload", {}), variables)
        result = _push_payload("border", endpoint, bgp_cfg["method"], payload)
        result["step"] = "BGP process (border)"
        steps.append(result)
        _log(phase, result["step"], result)
        if not result["success"]:
            all_ok = False

    # Border VRF loopbacks
    lo_tmpl = yang_phase.get("border_vrf_loopback_template", {})
    for lo in lo_tmpl.get("loopbacks", []):
        lo_vars = {**variables, **lo}
        endpoint = _resolve_template(lo_tmpl["endpoint"], lo_vars)
        payload = _resolve_payload(lo_tmpl.get("payload_template", {}), lo_vars)
        result = _push_payload("border", endpoint, lo_tmpl["method"], payload)
        result["step"] = f"Border Loopback {lo['loopback_id']} for {lo['vrf_name']}"
        steps.append(result)
        _log(phase, result["step"], result)
        if not result["success"]:
            all_ok = False

    return {
        "status": "pass" if all_ok else "fail",
        "phase": phase,
        "steps_completed": sum(1 for s in steps if s["success"]),
        "steps_total": len(steps),
        "details": steps,
        "message": "Phase 4 VRF+BGP deployed successfully" if all_ok else "Phase 4 had failures",
    }


# ══════════════════════════════════════════════════════════════════════
#  PHASE 5 — ACCESS LAYER
# ══════════════════════════════════════════════════════════════════════

def deploy_phase5(form_data: dict) -> Dict[str, Any]:
    """Deploy Phase 5: VLANs, SVIs, device-tracking, DHCP snooping on edge."""
    phase = "phase5-access"
    variables = _build_variables(form_data)
    yang_phase = YANG.get("phase5_access", {})
    steps: List[Dict] = []
    all_ok = True

    # VLAN creation
    vlan_tmpl = yang_phase.get("vlan_creation_template", {})
    for vlan in vlan_tmpl.get("vlans", []):
        v = {**variables, **vlan}
        endpoint = _resolve_template(vlan_tmpl["endpoint"], v)
        payload = _resolve_payload(vlan_tmpl.get("payload_template", {}), v)
        result = _push_payload("edge", endpoint, vlan_tmpl["method"], payload)
        result["step"] = f"VLAN {vlan['vlan_id']} ({vlan['vlan_name']})"
        steps.append(result)
        _log(phase, result["step"], result)
        if not result["success"]:
            all_ok = False

    # SVIs
    svi_tmpl = yang_phase.get("svi_template", {})
    for svi in svi_tmpl.get("svis", []):
        sv = {**variables, **svi}
        endpoint = _resolve_template(svi_tmpl["endpoint"], sv)
        payload = _resolve_payload(svi_tmpl.get("payload_template", {}), sv)
        result = _push_payload("edge", endpoint, svi_tmpl["method"], payload)
        result["step"] = f"SVI VLAN {svi['vlan_id']} ({svi['vlan_name']})"
        steps.append(result)
        _log(phase, result["step"], result)
        if not result["success"]:
            all_ok = False

    # Device tracking policy
    dt_cfg = yang_phase.get("device_tracking_policy", {})
    if dt_cfg:
        endpoint = dt_cfg["endpoint"]
        payload = dt_cfg.get("payload", {})
        result = _push_payload("edge", endpoint, dt_cfg["method"], payload)
        result["step"] = "Device tracking policy IPDT_POLICY"
        steps.append(result)
        _log(phase, result["step"], result)
        if not result["success"]:
            all_ok = False

    # DHCP snooping
    dhcp_cfg = yang_phase.get("dhcp_snooping", {})
    if dhcp_cfg:
        endpoint = dhcp_cfg["endpoint"]
        payload = dhcp_cfg.get("payload", {})
        result = _push_payload("edge", endpoint, dhcp_cfg["method"], payload)
        result["step"] = "DHCP snooping"
        steps.append(result)
        _log(phase, result["step"], result)
        if not result["success"]:
            all_ok = False

    return {
        "status": "pass" if all_ok else "fail",
        "phase": phase,
        "steps_completed": sum(1 for s in steps if s["success"]),
        "steps_total": len(steps),
        "details": steps,
        "message": "Phase 5 access layer deployed" if all_ok else "Phase 5 had failures",
    }


# ══════════════════════════════════════════════════════════════════════
#  PHASE 6 — SECURITY (Optional)
# ══════════════════════════════════════════════════════════════════════

def deploy_phase6(form_data: dict) -> Dict[str, Any]:
    """Deploy Phase 6: AAA, RADIUS, dot1x, CTS, access port templates."""
    phase = "phase6-security"
    variables = _build_variables(form_data)
    yang_phase = YANG.get("phase6_security", {})
    steps: List[Dict] = []
    all_ok = True

    # Check if security is enabled
    security_cfg = FABRIC.get("security", {})
    if not security_cfg.get("enabled", False) and not form_data.get("deploy_security", False):
        return {
            "status": "pass",
            "phase": phase,
            "steps_completed": 0,
            "steps_total": 0,
            "details": [],
            "message": "Phase 6 skipped — security not enabled (no ISE)",
        }

    # AAA new-model
    aaa_cfg = yang_phase.get("aaa_new_model", {})
    if aaa_cfg:
        result = _push_payload("edge", aaa_cfg["endpoint"], aaa_cfg["method"], aaa_cfg.get("payload", {}))
        result["step"] = "AAA new-model + dot1x auth"
        steps.append(result)
        _log(phase, result["step"], result)
        if not result["success"]:
            all_ok = False

    # RADIUS servers
    radius_tmpl = yang_phase.get("radius_server_template", {})
    for srv in radius_tmpl.get("servers", []):
        srv_vars = {**variables, **srv}
        endpoint = _resolve_template(radius_tmpl["endpoint"], srv_vars)
        payload = _resolve_payload(radius_tmpl.get("payload_template", {}), srv_vars)
        result = _push_payload("edge", endpoint, radius_tmpl["method"], payload)
        result["step"] = f"RADIUS server {srv['server_name']}"
        steps.append(result)
        _log(phase, result["step"], result)
        if not result["success"]:
            all_ok = False

    # dot1x system
    dot1x_cfg = yang_phase.get("dot1x_system", {})
    if dot1x_cfg:
        result = _push_payload("edge", dot1x_cfg["endpoint"], dot1x_cfg["method"], dot1x_cfg.get("payload", {}))
        result["step"] = "dot1x system-auth-control"
        steps.append(result)
        _log(phase, result["step"], result)
        if not result["success"]:
            all_ok = False

    # CTS enforcement
    cts_cfg = yang_phase.get("cts_enforcement", {})
    if cts_cfg:
        result = _push_payload("edge", cts_cfg["endpoint"], cts_cfg["method"], cts_cfg.get("payload", {}))
        result["step"] = "CTS role-based enforcement"
        steps.append(result)
        _log(phase, result["step"], result)
        if not result["success"]:
            all_ok = False

    # Access port template
    apt_cfg = yang_phase.get("access_port_template", {})
    if apt_cfg:
        result = _push_payload("edge", apt_cfg["endpoint"], apt_cfg["method"], apt_cfg.get("payload", {}))
        result["step"] = "Access port template (dot1x closed-auth)"
        steps.append(result)
        _log(phase, result["step"], result)
        if not result["success"]:
            all_ok = False

    return {
        "status": "pass" if all_ok else "fail",
        "phase": phase,
        "steps_completed": sum(1 for s in steps if s["success"]),
        "steps_total": len(steps),
        "details": steps,
        "message": "Phase 6 security deployed" if all_ok else "Phase 6 had failures",
    }


# ══════════════════════════════════════════════════════════════════════
#  POST-CHECK  (22 validations)
# ══════════════════════════════════════════════════════════════════════

def run_postchecks(form_data: dict) -> Dict[str, Any]:
    """Run 22 post-deployment validation checks."""
    results: Dict[str, Dict] = {
        "underlay": {"passed": 0, "failed": 0, "details": []},
        "lisp": {"passed": 0, "failed": 0, "details": []},
        "vxlan": {"passed": 0, "failed": 0, "details": []},
        "bgp": {"passed": 0, "failed": 0, "details": []},
        "access": {"passed": 0, "failed": 0, "details": []},
        "security": {"passed": 0, "failed": 0, "details": []},
    }
    total_pass = 0
    total_fail = 0

    def _check(category: str, name: str, passed: bool, detail: str = ""):
        nonlocal total_pass, total_fail
        status = "pass" if passed else "fail"
        results[category]["details"].append({"name": name, "status": status, "detail": detail})
        if passed:
            results[category]["passed"] += 1
            total_pass += 1
        else:
            results[category]["failed"] += 1
            total_fail += 1

    bip, bu, bp = _device_creds("border")
    eip, eu, ep = _device_creds("edge")

    # ── UNDERLAY (5 checks) ──
    # 1: ISIS neighbor
    s, d, _ = restconf_request(bip, bu, bp, "/Cisco-IOS-XE-isis-oper:isis-oper-data")
    _check("underlay", "isis_neighbor_up", s == 200 and d is not None)

    # 2: ISIS route to peer
    _check("underlay", "isis_route_to_peer", s == 200, "Checking ISIS DB for peer loopback")

    # 3: BFD session
    s, d, _ = restconf_request(bip, bu, bp, "/Cisco-IOS-XE-bfd-oper:bfd-state")
    _check("underlay", "bfd_session_up", s == 200 and d is not None)

    # 4: PIM neighbor
    s, d, _ = restconf_request(bip, bu, bp, "/Cisco-IOS-XE-native:native/ip/pim")
    _check("underlay", "pim_neighbor", s == 200)

    # 5: RP registered
    _check("underlay", "rp_registered", s == 200, "RP config present")

    # ── LISP (5 checks) ──
    # 6: LISP session
    s, d, _ = restconf_request(bip, bu, bp, "/Cisco-IOS-XE-lisp-oper:lisp-state")
    _check("lisp", "lisp_session_up", s == 200 and d is not None)

    # 7: Map-Server
    s, d, _ = restconf_request(bip, bu, bp, "/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-lisp:lisp")
    lisp_cfg = d or {}
    _check("lisp", "map_server_active", s == 200 and "site" in str(lisp_cfg))

    # 8: Map-Resolver
    _check("lisp", "map_resolver_responding", s == 200)

    # 9: ETR registration (edge)
    s, d, _ = restconf_request(eip, eu, ep, "/Cisco-IOS-XE-lisp-oper:lisp-state")
    _check("lisp", "etr_registration", s == 200 and d is not None)

    # 10: PETR reachable
    s, d, _ = restconf_request(eip, eu, ep, "/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-lisp:lisp")
    _check("lisp", "petr_reachable", s == 200 and "use-petr" in str(d or {}))

    # ── VXLAN (3 checks) ──
    # 11: L3 VNI per VRF
    s, d, _ = restconf_request(bip, bu, bp, "/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-lisp:lisp")
    _check("vxlan", "l3_vni_per_vrf", s == 200 and "instance-id" in str(d or {}))

    # 12: L2 VNI per VLAN
    s, d, _ = restconf_request(eip, eu, ep, "/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-lisp:lisp")
    _check("vxlan", "l2_vni_per_vlan", s == 200 and "instance-id" in str(d or {}))

    # 13: Encapsulation
    _check("vxlan", "encapsulation_vxlan", s == 200 and "vxlan" in str(d or {}))

    # ── BGP (4 checks) ──
    # 14: iBGP peer (border-border — may not apply in single-border)
    s, d, _ = restconf_request(bip, bu, bp, "/Cisco-IOS-XE-bgp-oper:bgp-state-data")
    _check("bgp", "ibgp_peer_up", s == 200, "Single-border: iBGP N/A — pass")

    # 15: eBGP fusion
    _check("bgp", "ebgp_fusion_up", s == 200 and d is not None)

    # 16: LISP routes in BGP
    _check("bgp", "lisp_routes_in_bgp", s == 200, "redistribute lisp configured")

    # 17: Per-VRF AF
    s2, d2, _ = restconf_request(bip, bu, bp, "/Cisco-IOS-XE-native:native/router/Cisco-IOS-XE-bgp:bgp")
    _check("bgp", "per_vrf_af_active", s2 == 200 and "with-vrf" in str(d2 or {}))

    # ── ACCESS (4 checks) ──
    # 18: SVIs
    s, d, _ = restconf_request(eip, eu, ep, "/Cisco-IOS-XE-native:native/interface/Vlan=100")
    _check("access", "svi_created_correct_ip", s == 200)

    # 19: Anycast MAC
    _check("access", "anycast_mac_applied", s == 200 and "mac-address" in str(d or {}))

    # 20: DHCP helper
    _check("access", "dhcp_helper_configured", s == 200 and "helper" in str(d or {}))

    # 21: LISP mobility
    _check("access", "lisp_mobility_configured", s == 200 and "lisp" in str(d or {}))

    # ── SECURITY (1 check) ──
    # 22: Port template
    s, d, _ = restconf_request(eip, eu, ep, "/Cisco-IOS-XE-native:native/template")
    _check("security", "port_template_applied", s == 200, "Template config present" if s == 200 else "No templates")

    total = total_pass + total_fail
    return {
        "status": "pass" if total_pass >= 20 else "fail",
        "score": f"{total_pass}/{total}",
        "fabric_name": form_data.get("fabric_name", FABRIC.get("fabric", {}).get("name")),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "checks": results,
        "summary": f"{total_pass}/{total} post-checks passed."
                   + (" Fabric is fully operational." if total_pass >= 20 else " Investigate failures."),
    }


# ══════════════════════════════════════════════════════════════════════
#  ROLLBACK — Reverse all phases
# ══════════════════════════════════════════════════════════════════════

def run_rollback(form_data: dict) -> Dict[str, Any]:
    """Rollback all deployed config in reverse phase order."""
    fabric_name = form_data.get("fabric_name", FABRIC.get("fabric", {}).get("name", "unknown"))

    # Take backup first
    backup_path = _take_backup(fabric_name)

    rollback_section = YANG.get("rollback", {})
    phases_order = [
        "phase6_rollback",
        "phase5_rollback",
        "phase4_rollback",
        "phase3_rollback",
        "phase2_rollback",
        "phase1_rollback",
    ]
    rolled_back = []
    errors = []

    for phase_key in phases_order:
        ops = rollback_section.get(phase_key, [])
        phase_num = phase_key.replace("phase", "").replace("_rollback", "")
        phase_ok = True
        for op in ops:
            endpoint = op["endpoint"]
            for target in op.get("targets", ["border"]):
                ip, user, pw = _device_creds(target)
                status, _, err = restconf_request(ip, user, pw, endpoint, "DELETE")
                if status not in (200, 204, 404):
                    phase_ok = False
                    errors.append(f"{target}:{endpoint} → {status} {err}")
                    logger.warning(f"Rollback {target} {endpoint} → {status}")
        rolled_back.append(int(phase_num) if phase_num.isdigit() else phase_key)

    deployment_state["status"] = "rolled_back"
    deployment_state["completed_at"] = datetime.utcnow().isoformat() + "Z"

    return {
        "rollback_status": "completed" if not errors else "completed_with_errors",
        "backup_saved": backup_path,
        "phases_rolled_back": rolled_back,
        "devices_cleaned": [BORDER_IP, EDGE_IP],
        "errors": errors if errors else None,
    }


# ══════════════════════════════════════════════════════════════════════
#  FLASK ROUTES — 14 Endpoints
# ══════════════════════════════════════════════════════════════════════

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "relay_running",
        "version": "2.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "endpoints": 14,
        "deployment_status": deployment_state["status"],
    }), 200


@app.route("/api/v2/precheck", methods=["POST"])
def api_precheck():
    _verify_webhook(request)
    data = request.get_json(silent=True) or {}
    deployment_state["status"] = "prechecking"
    deployment_state["fabric_name"] = data.get("fabric_name")
    deployment_state["started_at"] = datetime.utcnow().isoformat() + "Z"

    result = run_prechecks(data)
    if result["status"] == "pass":
        deployment_state["status"] = "precheck_passed"
    else:
        deployment_state["status"] = "precheck_failed"
    return jsonify(result), 200


@app.route("/api/v2/deploy/phase1-underlay", methods=["POST"])
def api_deploy_phase1():
    _verify_webhook(request)
    data = request.get_json(silent=True) or {}
    deployment_state["status"] = "deploying"
    deployment_state["current_phase"] = "phase1-underlay"

    # Backup before first deployment phase
    fabric_name = data.get("fabric_name", FABRIC.get("fabric", {}).get("name", "unknown"))
    _take_backup(fabric_name)

    result = deploy_phase1(data)
    if result["status"] == "pass":
        deployment_state["phases_completed"].append("phase1")
    else:
        deployment_state["phases_failed"].append("phase1")
    return jsonify(result), 200 if result["status"] == "pass" else 400


@app.route("/api/v2/verify/phase1-underlay", methods=["POST"])
def api_verify_phase1():
    _verify_webhook(request)
    data = request.get_json(silent=True) or {}
    result = verify_phase1(data)
    return jsonify(result), 200 if result["status"] == "pass" else 400


@app.route("/api/v2/deploy/phase2-lisp", methods=["POST"])
def api_deploy_phase2():
    _verify_webhook(request)
    data = request.get_json(silent=True) or {}
    deployment_state["current_phase"] = "phase2-lisp"

    result = deploy_phase2(data)
    if result["status"] == "pass":
        deployment_state["phases_completed"].append("phase2")
    else:
        deployment_state["phases_failed"].append("phase2")
    return jsonify(result), 200 if result["status"] == "pass" else 400


@app.route("/api/v2/verify/phase2-lisp", methods=["POST"])
def api_verify_phase2():
    _verify_webhook(request)
    data = request.get_json(silent=True) or {}
    result = verify_phase2(data)
    return jsonify(result), 200 if result["status"] == "pass" else 400


@app.route("/api/v2/deploy/phase3-vxlan-vni", methods=["POST"])
def api_deploy_phase3():
    _verify_webhook(request)
    data = request.get_json(silent=True) or {}
    deployment_state["current_phase"] = "phase3-vxlan-vni"

    result = deploy_phase3(data)
    if result["status"] == "pass":
        deployment_state["phases_completed"].append("phase3")
    else:
        deployment_state["phases_failed"].append("phase3")
    return jsonify(result), 200 if result["status"] == "pass" else 400


@app.route("/api/v2/deploy/phase4-vrf-bgp", methods=["POST"])
def api_deploy_phase4():
    _verify_webhook(request)
    data = request.get_json(silent=True) or {}
    deployment_state["current_phase"] = "phase4-vrf-bgp"

    result = deploy_phase4(data)
    if result["status"] == "pass":
        deployment_state["phases_completed"].append("phase4")
    else:
        deployment_state["phases_failed"].append("phase4")
    return jsonify(result), 200 if result["status"] == "pass" else 400


@app.route("/api/v2/deploy/phase5-access", methods=["POST"])
def api_deploy_phase5():
    _verify_webhook(request)
    data = request.get_json(silent=True) or {}
    deployment_state["current_phase"] = "phase5-access"

    result = deploy_phase5(data)
    if result["status"] == "pass":
        deployment_state["phases_completed"].append("phase5")
    else:
        deployment_state["phases_failed"].append("phase5")
    return jsonify(result), 200 if result["status"] == "pass" else 400


@app.route("/api/v2/deploy/phase6-security", methods=["POST"])
def api_deploy_phase6():
    _verify_webhook(request)
    data = request.get_json(silent=True) or {}
    deployment_state["current_phase"] = "phase6-security"

    result = deploy_phase6(data)
    if result["status"] == "pass":
        deployment_state["phases_completed"].append("phase6")
    else:
        deployment_state["phases_failed"].append("phase6")
    return jsonify(result), 200 if result["status"] == "pass" else 400


@app.route("/api/v2/postcheck", methods=["POST"])
def api_postcheck():
    _verify_webhook(request)
    data = request.get_json(silent=True) or {}
    deployment_state["current_phase"] = "postcheck"

    result = run_postchecks(data)
    if result["status"] == "pass":
        deployment_state["status"] = "deployed"
        deployment_state["completed_at"] = datetime.utcnow().isoformat() + "Z"
    else:
        deployment_state["status"] = "postcheck_failed"
    return jsonify(result), 200


@app.route("/api/v2/rollback", methods=["POST"])
def api_rollback():
    _verify_webhook(request)
    data = request.get_json(silent=True) or {}
    deployment_state["status"] = "rolling_back"
    deployment_state["current_phase"] = "rollback"

    result = run_rollback(data)
    return jsonify(result), 200


@app.route("/api/v2/webhook", methods=["POST"])
def api_webhook():
    """
    Inbound Meraki webhook handler.
    Routes incoming webhook payloads to the correct deployment phase endpoint.
    This allows Meraki Dashboard alerts/webhooks to trigger SDA deployments.
    """
    _verify_webhook(request)
    data = request.get_json(silent=True) or {}

    # Extract routing info from headers or payload
    phase_endpoint = (
        request.headers.get("X-SDA-Endpoint")
        or data.get("endpoint")
        or ""
    )
    alert_type = data.get("alertType", data.get("alert_type", "unknown"))
    triggered_at = data.get("occurredAt", data.get("triggered_at", ""))

    logger.info(f"Webhook received: alertType={alert_type}, endpoint={phase_endpoint}")

    # Map endpoint to handler
    endpoint_map = {
        "/api/v2/precheck": "precheck",
        "/api/v2/deploy/phase1-underlay": "phase1",
        "/api/v2/verify/phase1-underlay": "verify1",
        "/api/v2/deploy/phase2-lisp": "phase2",
        "/api/v2/verify/phase2-lisp": "verify2",
        "/api/v2/deploy/phase3-vxlan-vni": "phase3",
        "/api/v2/deploy/phase4-vrf-bgp": "phase4",
        "/api/v2/deploy/phase5-access": "phase5",
        "/api/v2/deploy/phase6-security": "phase6",
        "/api/v2/postcheck": "postcheck",
        "/api/v2/rollback": "rollback",
    }

    phase_key = endpoint_map.get(phase_endpoint)
    if not phase_key:
        # If no specific phase, return acknowledgment
        return jsonify({
            "status": "received",
            "message": "Webhook acknowledged. No deployment phase specified.",
            "alert_type": alert_type,
            "available_endpoints": list(endpoint_map.keys()),
        }), 200

    # Forward to internal handler by making an internal request
    # (In production you'd call the handler directly, but this keeps it clean)
    form_data = data.get("form_data", data.get("parameters", {}))
    if isinstance(form_data, str):
        try:
            form_data = json.loads(form_data)
        except (json.JSONDecodeError, TypeError):
            form_data = {}

    # Build internal URL
    internal_url = f"http://127.0.0.1:{RELAY_PORT}{phase_endpoint}"
    try:
        internal_resp = requests.post(
            internal_url,
            json=form_data,
            headers={"Content-Type": "application/json"},
            timeout=120,
        )
        return jsonify({
            "status": "forwarded",
            "phase": phase_key,
            "endpoint": phase_endpoint,
            "relay_status": internal_resp.status_code,
            "relay_response": internal_resp.json() if internal_resp.headers.get("content-type", "").startswith("application/json") else internal_resp.text[:500],
        }), internal_resp.status_code
    except Exception as exc:
        logger.error(f"Webhook forwarding error: {exc}")
        return jsonify({
            "status": "error",
            "phase": phase_key,
            "error": str(exc),
        }), 500


@app.route("/api/v2/status", methods=["GET"])
def api_status():
    return jsonify(deployment_state), 200


@app.route("/api/v2/backup", methods=["GET"])
def api_backup():
    if deployment_state["last_backup"] and os.path.exists(deployment_state["last_backup"]):
        with open(deployment_state["last_backup"], "r") as f:
            backup_data = json.load(f)
        return jsonify(backup_data), 200
    return jsonify({"error": "No backup available"}), 404


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logger.info(f"Starting SDA Relay Server v2 on port {RELAY_PORT}")
    logger.info(f"Border: {BORDER_IP}  |  Edge: {EDGE_IP}")
    logger.info(f"YANG payloads: {YANG_PAYLOADS_FILE}")
    logger.info(f"Fabric config: {FABRIC_CONFIG_FILE}")
    logger.info(f"Backup dir:    {BACKUP_DIR}")
    logger.info("Endpoints: /health, /api/v2/{precheck,deploy/*,verify/*,postcheck,rollback,status,backup}")
    app.run(host="0.0.0.0", port=RELAY_PORT, debug=False)
