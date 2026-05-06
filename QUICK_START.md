# Quick Start — SDA LISP+VXLAN via Meraki (No CC)

## Pre-requisites
- IOS XE 17.15.3+ on C9500 and C9300
- Python 3.9+ on lab server
- Meraki Dashboard admin access

## Step 1 — Enable RESTCONF on Both Switches

configure terminal
restconf
ip http secure-server
exit
write memory


## Step 2 — Verify RESTCONF

show ip http secure server status
show yang module | include lisp
show yang module | include vxlan


## Step 3 — Deploy Relay Server (Lab VM)
```bash
mkdir sda-lab && cd sda-lab
# Copy all files here
pip3 install -r requirements.txt
# Edit .env with your switch IPs and credentials
python3 sda_relay_server.py
```

## Step 4 — Test Relay
```bash
curl http://localhost:5000/health
# Expected: {"status": "relay_running"}

curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{"action":"health_check_devices"}'
# Expected: {"c9500_reachable": true, "c9300_reachable": true}
```

## Step 5 — Configure Meraki Target
Dashboard → Automation → Workflows → Targets → Add:
- Name: SDA_Relay
- URL: http://localhost:5000 (or ngrok URL)

## Step 6 — Import Workflow
Dashboard → Workflows → Import → Upload meraki_workflow_export.json

## Step 7 — Execute Workflow
Workflows → Deploy-SDA-Fabric-LISP-VXLAN → Execute
Fill: fabric_name, instance_id=100, vni=100, vlan=100

## Step 8 — Validate
```bash
python3 sda_deployment_validator.py
```

## Validation on Switches
C9500: show lisp site
C9500: show lisp instance-id 100 statistics
C9300: show vxlan detail
C9300: show interface nve 1