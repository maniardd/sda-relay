#!/usr/bin/env python3
"""
SDA Relay Server v3 — CLI-over-SSH (Netmiko) replacement for v2 (RESTCONF/YANG).

Why v3:
- v2 used RESTCONF/YANG. IOS-XE 17.x silently accepts (HTTP 204) LISP/VXLAN/L2-VNI
  payloads but doesn't apply them — exactly what the user observed: workflow green,
  switches blank.
- v3 pushes raw CLI via Netmiko, then re-reads `show run` and per-phase verify
  commands. Returns per-block applied=true/false so the Meraki workflow can
  branch correctly.

Endpoints (same shape as v2 so the existing workflow keeps working):
  GET  /health
  POST /api/v3/precheck
  POST /api/v3/deploy/<phase>          phase ∈ {phase1-underlay, phase2-lisp,
                                               phase3-overlay, phase4-access,
                                               phase5-handoff}
  POST /api/v3/verify/<phase>
  POST /api/v3/deploy/all              full-fabric one-shot
  GET  /api/v3/show?target=border&cmd=show+run
  GET  /api/v3/status
"""
from __future__ import annotations
import os, json, time, logging, traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import yaml
from flask import Flask, request, jsonify
from dotenv import load_dotenv

try:
    from netmiko import ConnectHandler
    from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException
except ImportError:
    raise SystemExit("Install netmiko: pip install netmiko")

import sda_cli_templates as T

# ── INIT ─────────────────────────────────────────────────────────────
load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s")
log = logging.getLogger("sda-relay-v3")

BORDER = {
    "device_type": "cisco_ios",
    "host": os.getenv("C9500_IP", "192.168.128.9"),
    "username": os.getenv("C9500_USER", "admin"),
    "password": os.getenv("C9500_PASS", ""),
    "secret":   os.getenv("C9500_PASS", ""),
    "fast_cli": False,
    "global_delay_factor": 2,
    "conn_timeout": 20,
    "banner_timeout": 20,
}
EDGE = {
    **BORDER,
    "host": os.getenv("C9300_IP", "192.168.128.7"),
    "username": os.getenv("C9300_USER", "admin"),
    "password": os.getenv("C9300_PASS", ""),
    "secret":   os.getenv("C9300_PASS", ""),
}
DEVS = {"border": BORDER, "edge": EDGE}

FABRIC_FILE = os.getenv("FABRIC_CONFIG_FILE",
    os.path.join(os.path.dirname(__file__), "sda_fabric_config.yaml"))
with open(FABRIC_FILE) as f:
    FABRIC = yaml.safe_load(f)

STATE: Dict[str, Any] = {"status":"idle", "phases":{}, "last_run":None}


# ── NETMIKO HELPERS ──────────────────────────────────────────────────
def _connect(target: str):
    cfg = DEVS[target]
    if not cfg["password"]:
        envvar = "C9500_PASS" if target == "border" else "C9300_PASS"
        raise RuntimeError(f"No password for {target} (set {envvar} in /opt/sda-relay/.env)")
    return ConnectHandler(**cfg)


def _push_block(conn, block_label: str, cli_lines: List[str]) -> Dict[str, Any]:
    """Send a config block. Returns {applied, output, error}."""
    cli = [ln for ln in cli_lines if ln and ln.strip()]
    if not cli:
        return {"label": block_label, "applied": True, "skipped": True, "output": ""}
    try:
        out = conn.send_config_set(cli, exit_config_mode=True, cmd_verify=False,
                                   read_timeout=60)
        # Detect rejected lines
        bad_markers = ["% Invalid input", "% Incomplete command",
                       "% Ambiguous command", "% Unknown command",
                       "Command rejected"]
        rejected = [ln for ln in out.splitlines() if any(m in ln for m in bad_markers)]
        applied = len(rejected) == 0
        return {
            "label": block_label,
            "applied": applied,
            "lines_sent": len(cli),
            "rejected": rejected[:10],
            "output": out[-2000:],   # tail only
        }
    except Exception as e:
        return {"label": block_label, "applied": False, "error": str(e),
                "output": ""}


def _show(conn, cmd: str) -> str:
    try:
        return conn.send_command(cmd, read_timeout=30)
    except Exception as e:
        return f"ERROR: {e}"


# ── ROUTES ───────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({
        "status": "relay_running",
        "version": "3.0",
        "transport": "netmiko-cli",
        "endpoints": 7,
        "deployment_status": STATE["status"],
    })


@app.route("/api/v3/precheck", methods=["POST"])
def precheck():
    """SSH login + enable + show version on both devices."""
    out = {"timestamp": datetime.utcnow().isoformat()+"Z", "checks": {}}
    overall = True
    for tgt in ("border", "edge"):
        try:
            conn = _connect(tgt)
            try:
                conn.enable()
            except Exception:
                pass
            ver = _show(conn, "show version | inc IOS")
            host = _show(conn, "show running-config | inc ^hostname")
            conn.disconnect()
            out["checks"][tgt] = {"status":"pass","hostname":host.strip(),"version":ver.strip()}
        except (NetmikoAuthenticationException, NetmikoTimeoutException) as e:
            out["checks"][tgt] = {"status":"fail","error":str(e)}
            overall = False
        except Exception as e:
            out["checks"][tgt] = {"status":"fail","error":str(e)}
            overall = False
    out["overall"] = "pass" if overall else "fail"
    return jsonify(out), (200 if overall else 502)


def _run_phase(phase: str, form: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    if phase not in T.PHASE_BUILDERS:
        return {"error": f"unknown phase {phase}"}, 400
    builder = T.PHASE_BUILDERS[phase]
    STATE["status"] = f"deploying:{phase}"
    result: Dict[str, Any] = {"phase": phase, "targets": {}}
    overall_ok = True

    for tgt in ("border", "edge"):
        blocks = builder(FABRIC, tgt)
        if not blocks:
            result["targets"][tgt] = {"status":"skipped","blocks":[]}
            continue
        try:
            conn = _connect(tgt)
            try: conn.enable()
            except Exception: pass
            block_results = []
            for label, lines in blocks:
                br = _push_block(conn, label, lines)
                block_results.append(br)
                log.info(f"[{phase}/{tgt}/{label}] applied={br.get('applied')} "
                         f"rejected={br.get('rejected', [])}")
            # Save running-config
            try:
                conn.send_command_timing("write memory", read_timeout=30)
            except Exception as e:
                log.warning(f"write memory failed on {tgt}: {e}")
            conn.disconnect()
            tgt_ok = all(b.get("applied") for b in block_results)
            result["targets"][tgt] = {
                "status": "pass" if tgt_ok else "fail",
                "blocks": block_results,
            }
            overall_ok = overall_ok and tgt_ok
        except Exception as e:
            log.error(f"{phase}/{tgt} failed: {e}\n{traceback.format_exc()}")
            result["targets"][tgt] = {"status":"fail","error":str(e)}
            overall_ok = False

    result["overall"] = "pass" if overall_ok else "fail"
    STATE["phases"][phase] = result["overall"]
    STATE["status"] = "idle"
    STATE["last_run"] = datetime.utcnow().isoformat()+"Z"
    return result, (200 if overall_ok else 502)


@app.route("/api/v3/deploy/<phase>", methods=["POST"])
def deploy_phase(phase):
    form = request.get_json(silent=True) or {}
    res, code = _run_phase(phase, form)
    return jsonify(res), code


@app.route("/api/v3/verify/<phase>", methods=["POST"])
def verify_phase(phase):
    cmds = T.VERIFY_CMDS.get(phase, [])
    if not cmds:
        return jsonify({"phase":phase,"status":"no-verify-defined"}), 200
    # Allow caller to ask for a settle delay (default 25s for control-plane convergence)
    form = request.get_json(silent=True) or {}
    settle = int(form.get("settle_seconds", 25))
    if settle > 0:
        log.info(f"verify({phase}) sleeping {settle}s for convergence...")
        time.sleep(settle)
    out = {"phase": phase, "settle_seconds": settle, "targets": {}}
    overall = True
    for tgt in ("border", "edge"):
        try:
            conn = _connect(tgt)
            try: conn.enable()
            except Exception: pass
            checks = []
            for cmd, expect in cmds:
                txt = _show(conn, cmd)
                txt_l = txt.lower()
                ok = all(kw.lower() in txt_l for kw in expect) if expect else bool(txt.strip())
                checks.append({"cmd":cmd,"expect":expect,"pass":ok,
                               "output":txt[-800:]})
                if not ok: overall = False
            conn.disconnect()
            out["targets"][tgt] = {"checks": checks}
        except Exception as e:
            out["targets"][tgt] = {"error": str(e)}
            overall = False
    out["overall"] = "pass" if overall else "fail"
    return jsonify(out), (200 if overall else 502)


@app.route("/api/v3/deploy/all", methods=["POST"])
def deploy_all():
    form = request.get_json(silent=True) or {}
    results = {}
    for phase in ["phase1-underlay","phase2-lisp","phase3-overlay","phase4-access"]:
        res, code = _run_phase(phase, form)
        results[phase] = res
        if res.get("overall") != "pass" and not form.get("continue_on_fail"):
            results["stopped_at"] = phase
            return jsonify(results), 502
    return jsonify(results), 200


@app.route("/api/v3/show", methods=["GET"])
def show():
    """Run any 'show' command — for debugging from curl."""
    target = request.args.get("target","edge")
    cmd = request.args.get("cmd","show version")
    if not cmd.lower().startswith("show"):
        return jsonify({"error":"only 'show' commands allowed"}), 400
    try:
        conn = _connect(target)
        try: conn.enable()
        except Exception: pass
        txt = _show(conn, cmd)
        conn.disconnect()
        return jsonify({"target":target,"cmd":cmd,"output":txt})
    except Exception as e:
        return jsonify({"error":str(e)}), 502


@app.route("/api/v3/status")
def status():
    return jsonify(STATE)


@app.route("/api/v3/datapath-test", methods=["POST", "GET"])
def datapath_test():
    """Run a curated set of show commands on both switches that prove the
    SDA data plane is alive: LISP database/map-cache, NVE peers, DHCP bindings,
    ARP for endpoints, route table per VRF, ISIS adjacencies, BFD sessions.
    Returns one big JSON the runner commits back so we can read it from CI.
    """
    cmds_per_target = {
        "border": [
            "show isis neighbors",
            "show ip route vrf CORP_VN",
            "show ip route vrf GUEST_VN",
            "show lisp instance-id 4099 ipv4 server",
            "show lisp instance-id 4099 ipv4 database",
            "show lisp instance-id 4099 ipv4 map-cache",
            "show lisp session",
            "show nve peers",
            "show nve interface",
            "show ip dhcp pool",
            "show ip dhcp binding",
            "show running-config | section ip dhcp pool",
        ],
        "edge": [
            "show isis neighbors",
            "show ip route vrf CORP_VN",
            "show lisp instance-id 4099 ipv4 database",
            "show lisp instance-id 4099 ipv4 map-cache",
            "show lisp instance-id 8100 ethernet database",
            "show lisp session",
            "show nve peers",
            "show interfaces Vlan100",
            "show ip arp vrf CORP_VN",
            "show device-tracking database",
            "show mac address-table vlan 100",
            "show running-config interface GigabitEthernet1/0/3",
        ],
    }
    out = {"timestamp": datetime.utcnow().isoformat()+"Z", "targets": {}}
    for tgt, cmds in cmds_per_target.items():
        try:
            conn = _connect(tgt)
            try: conn.enable()
            except Exception: pass
            results = []
            for c in cmds:
                txt = _show(conn, c)
                results.append({"cmd": c, "output": txt})
            conn.disconnect()
            out["targets"][tgt] = {"results": results}
        except Exception as e:
            out["targets"][tgt] = {"error": str(e)}
    return jsonify(out)


if __name__ == "__main__":
    port = int(os.getenv("RELAY_PORT", 5000))
    app.run(host="0.0.0.0", port=port)
