#!/usr/bin/env python3
"""
SDA Relay Server — Local RESTCONF Bridge
Connects Meraki Workflows to IOS-XE RESTCONF API
"""

from flask import Flask, request, jsonify
from typing import Dict, Any
import requests, json, os
from datetime import datetime
from dotenv import load_dotenv
import logging

load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

C9500_IP   = os.getenv('C9500_IP')
C9500_USER = os.getenv('C9500_USER', 'admin')
C9500_PASS = os.getenv('C9500_PASS')
C9300_IP   = os.getenv('C9300_IP')
C9300_USER = os.getenv('C9300_USER', 'admin')
C9300_PASS = os.getenv('C9300_PASS')
RELAY_PORT = int(os.getenv('RELAY_PORT', 5000))

requests.packages.urllib3.disable_warnings()

# ── YANG PAYLOADS ─────────────────────────────
def get_lisp_yang_payload(instance_id: int) -> Dict[str, Any]:
    return {
        "Cisco-IOS-XE-lisp:lisp": {
            "instance_id": [{"iid": instance_id, "enable": [None], "map_cache_limit": 100000}],
            "map_server":  [{"authoritative": True, "map_registrar_connections": 3}],
            "map_resolver":[{"enabled": True}]
        }
    }

def get_vxlan_yang_payload(nve_id: int, vni_list: list) -> Dict[str, Any]:
    return {
        "Cisco-IOS-XE-nve:nve": {
            "nve": [{"interface_number": nve_id,
                     "source_interface": "Loopback0",
                     "host_reachability_protocol": "lisp",
                     "vni_list": vni_list}]
        }
    }

# ── RESTCONF OPERATIONS ───────────────────────
def restconf_put(device_ip, username, password, xpath, payload):
    url = f"https://{device_ip}:443/restconf/data{xpath}"
    headers = {"Content-Type": "application/yang-data+json",
               "Accept":       "application/yang-data+json"}
    try:
        r = requests.put(url, json=payload, auth=(username, password),
                         headers=headers, verify=False, timeout=30)
        logger.info(f"RESTCONF PUT {device_ip} {xpath} → {r.status_code}")
        if r.status_code in [200, 201, 204]:
            return (r.status_code, r.json() if r.text else {}, None)
        return (r.status_code, None, r.text)
    except Exception as e:
        logger.error(f"RESTCONF PUT failed: {e}")
        return (500, None, str(e))

def restconf_get(device_ip, username, password, xpath):
    url = f"https://{device_ip}:443/restconf/data{xpath}"
    headers = {"Accept": "application/yang-data+json"}
    try:
        r = requests.get(url, auth=(username, password),
                         headers=headers, verify=False, timeout=30)
        if r.status_code == 200:
            return (200, r.json(), None)
        return (r.status_code, None, r.text)
    except Exception as e:
        return (500, None, str(e))

# ── DEPLOYMENT LOGIC ──────────────────────────
def deploy_lisp_vxlan_fabric(config: Dict[str, Any]) -> Dict[str, Any]:
    log = {"timestamp": datetime.now().isoformat(),
           "fabric_name": config.get("fabric_name"), "steps": []}
    vni_list = [{"vlan": config.get("vlan_data", 100),
                 "vni":  config.get("vni_data", 100)}]
    try:
        # Step 1: LISP on C9500
        s, _, e = restconf_put(C9500_IP, C9500_USER, C9500_PASS,
                               "/Cisco-IOS-XE-lisp:lisp",
                               get_lisp_yang_payload(config.get("lisp_instance_id", 100)))
        if s not in [200,201,204]: raise Exception(f"C9500 LISP failed: {e}")
        log["steps"].append({"name":"C9500 LISP","status":"success"})

        # Step 2: VXLAN on C9500
        s, _, e = restconf_put(C9500_IP, C9500_USER, C9500_PASS,
                               "/Cisco-IOS-XE-nve:nve",
                               get_vxlan_yang_payload(1, vni_list))
        if s not in [200,201,204]: raise Exception(f"C9500 VXLAN failed: {e}")
        log["steps"].append({"name":"C9500 VXLAN NVE","status":"success"})

        # Step 3: VXLAN on C9300
        s, _, e = restconf_put(C9300_IP, C9300_USER, C9300_PASS,
                               "/Cisco-IOS-XE-nve:nve",
                               get_vxlan_yang_payload(1, vni_list))
        if s not in [200,201,204]: raise Exception(f"C9300 VXLAN failed: {e}")
        log["steps"].append({"name":"C9300 VXLAN NVE","status":"success"})

        # Step 4: Validate
        s, lisp_state, _ = restconf_get(C9500_IP, C9500_USER, C9500_PASS,
                                        "/Cisco-IOS-XE-lisp:lisp")
        if s == 200:
            log["steps"].append({"name":"Validation","status":"success"})

        return {"status": "success", "message": "Fabric deployment completed",
                "fabric_name": config.get("fabric_name"), "deployment_log": log,
                "next_steps": ["SSH to C9500: show lisp site",
                               "SSH to C9300: show vxlan detail",
                               "Connect device to C9300 Gi1/0/10"]}
    except Exception as e:
        logger.error(f"Deployment failed: {e}")
        log["steps"].append({"name":"Deployment","status":"failed","error":str(e)})
        return {"status": "failed", "message": str(e), "deployment_log": log}

# ── FLASK ROUTES ──────────────────────────────
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "relay_running",
                    "timestamp": datetime.now().isoformat()}), 200

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data   = request.get_json()
        action = data.get('action')
        logger.info(f"Webhook received: {action}")

        if action == 'deploy_lisp_vxlan':
            result = deploy_lisp_vxlan_fabric(data)
            return jsonify(result), 200 if result['status'] == 'success' else 400

        elif action == 'health_check_devices':
            r1 = requests.get(f"https://{C9500_IP}:443/restconf/api/status",
                              auth=(C9500_USER,C9500_PASS), verify=False, timeout=5)
            r2 = requests.get(f"https://{C9300_IP}:443/restconf/api/status",
                              auth=(C9300_USER,C9300_PASS), verify=False, timeout=5)
            return jsonify({"status":"success",
                            "c9500_reachable": r1.status_code==200,
                            "c9300_reachable": r2.status_code==200}), 200
        else:
            return jsonify({"error": f"Unknown action: {action}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/config/status', methods=['GET'])
def config_status():
    s1, lisp, _ = restconf_get(C9500_IP,C9500_USER,C9500_PASS,"/Cisco-IOS-XE-lisp:lisp")
    s2, vxlan, _ = restconf_get(C9500_IP,C9500_USER,C9500_PASS,"/Cisco-IOS-XE-nve:nve")
    return jsonify({"c9500_lisp":  lisp  if s1==200 else "not_configured",
                    "c9500_vxlan": vxlan if s2==200 else "not_configured"}), 200

if __name__ == '__main__':
    logger.info(f"Starting SDA Relay Server — Port {RELAY_PORT}")
    app.run(host='0.0.0.0', port=RELAY_PORT, debug=True)