# Catalyst Switch Onboarding to Meraki Dashboard — Device Configuration Mode

**Project:** SJC23-SDA POC  
**Date:** April 6, 2026  
**Switches:** C9500-32C (Border) @ 192.168.128.9, C9300X-48HXN (Edge) @ 192.168.128.7  
**Relay Server:** Ubuntu @ 192.168.128.10  
**IOS-XE Version:** 17.18.2 on both switches  
**Meraki Org:** CiscoWLAN (135358)  
**Meraki Network:** SJC23-SDA (L_591660401045811304)

---

## WHY Device Configuration Mode (NOT Cloud Configuration)

| Feature | Cloud Configuration | Device Configuration |
|---------|-------------------|---------------------|
| Factory reset switch? | **YES — erases everything** | **NO — keeps config** |
| CLI access | Read-only (logs only) | **Full priv-15 access** |
| RESTCONF works? | No | **YES** |
| Meraki pushes config? | Yes (full control) | No (monitoring + optional) |
| Switch retains IOS-XE config? | No | **YES** |

**We need Device Configuration** because:
- The relay server pushes SDA config via RESTCONF → needs CLI/RESTCONF intact
- We need full control of ISIS, LISP, VXLAN, VRF, BGP config
- Meraki Dashboard provides monitoring + Agentic Workflow orchestration

---

## PREREQUISITES CHECKLIST

Before starting, verify these on BOTH switches:

- [x] **Firmware**: IOS-XE 17.18.2 (meets minimum: 17.15+ for C9300X, 17.18+ for C9500H)
- [ ] **Boot mode**: Must be INSTALL mode (not BUNDLE)
- [ ] **IP routing**: `ip routing` must be enabled
- [ ] **AAA**: `aaa new-model` must be configured
- [ ] **AAA auth**: Local login permitted, exec authorization for local accounts
- [ ] **Priv-15 account**: User with privilege 15 for Dashboard to connect
- [ ] **DNS**: `ip name-server` configured, `ip domain lookup` enabled
- [ ] **NTP**: Clock must be correct (for mutual TLS tunnel)
- [ ] **Internet reachability**: Switch must resolve `dashboard.meraki.com`
- [ ] **Front-panel uplink**: NOT the Gig0/0 management port — front ports only
- [ ] **Default VRF**: Only default VRF supported for Meraki tunnel

---

## STEP 1: SWITCH CLI CONFIGURATION (Do on BOTH switches)

### 1A. Connect to the Border Switch (C9500-32C @ 192.168.128.9)

SSH or console into the switch:

```
ssh admin@192.168.128.9
```

### 1B. Verify Compatibility

```
show meraki compatibility
```

Expected output should show all checks as **Compatible**:
- Boot Mode: INSTALL — Compatible
- Stackwise Virtual: Disabled — Compatible
- SKU: C9500-32C — Compatible

If boot mode shows BUNDLE, you must convert to install mode first:
```
install add file flash:cat9k_iosxe.17.18.02.SPA.bin activate commit
```

### 1C. Verify Current Boot Mode

```
show version | include Mode
```
Should show: `Mode is INSTALL`

### 1D. Configure Prerequisites

Enter configuration mode:

```
configure terminal
```

**Enable IP routing (if not already):**
```
ip routing
```

**Enable AAA (if not already):**
```
aaa new-model
aaa authentication login default local
aaa authorization exec default local
```

**Create a privilege-15 local user for Meraki Dashboard:**
```
username meraki-admin privilege 15 secret 0 <STRONG-PASSWORD-HERE>
```
> Replace `<STRONG-PASSWORD-HERE>` with a secure password.  
> Meraki Dashboard will use this to connect to the switch after onboarding.

**Enable RESTCONF (needed for relay server):**
```
restconf
ip http server
ip http authentication local
ip http secure-server
```

**Configure DNS:**
```
ip name-server 8.8.8.8
ip domain lookup
```

**Configure NTP (critical for TLS tunnel):**
```
ntp server 192.168.128.10
```
> If Ubuntu server is not running NTP, use a public NTP server:
```
ntp server pool.ntp.org
```

**Verify clock is correct:**
```
end
show clock
```

**Ensure internet connectivity via a front-panel SVI:**

If the switch uses VLAN 1 or another VLAN for internet/uplink:

```
configure terminal

vlan 128
 name MGMT_UPLINK
exit

interface vlan 128
 ip address 192.168.128.9 255.255.255.0
 no shutdown
exit

ip route 0.0.0.0 0.0.0.0 192.168.128.1
ip http client source-interface Vlan128
```

> **IMPORTANT**: Adjust the VLAN, IP, and gateway to match your actual lab topology.  
> The switch must be able to reach the internet through a **front-panel port** (not Gig0/0).  
> The `ip http client source-interface` tells the Meraki tunnel which interface to use.

**End and save:**
```
end
write memory
```

### 1E. Verify Internet Connectivity

```
ping dashboard.meraki.com
```

Expected: Successful pings. If DNS fails:
```
ping 8.8.8.8
```
If pings to 8.8.8.8 work but DNS fails, check `ip name-server` and `ip domain lookup`.

### 1F. Initiate Meraki Registration

```
configure terminal
service meraki connect
end
```

This will:
1. Start communication with `dashboard.meraki.com`
2. Register the switch
3. Generate a **Cloud ID** (Meraki ID)

Wait 2-3 minutes, then check status:

```
show meraki connect
```

Expected output:
```
Meraki Device Registration:
  Status           : Registered
  Cloud ID         : XXXX-XXXX-XXXX          <-- SAVE THIS!
  Serial Number    : XXXXXXXX
  Meraki Tunnel    : Up
  Config Fetch     : Succeeded
```

> **SAVE THE CLOUD ID** — you will need it to claim in Dashboard.

### 1G. Repeat for Edge Switch (C9300X-48HXN @ 192.168.128.7)

SSH into the Edge switch and repeat steps 1B through 1F:

```
ssh admin@192.168.128.7
```

Same configuration but with Edge's IP:

```
configure terminal

ip routing
aaa new-model
aaa authentication login default local
aaa authorization exec default local

username meraki-admin privilege 15 secret 0 <STRONG-PASSWORD-HERE>

restconf
ip http server
ip http authentication local
ip http secure-server

ip name-server 8.8.8.8
ip domain lookup
ntp server pool.ntp.org

vlan 128
 name MGMT_UPLINK
exit

interface vlan 128
 ip address 192.168.128.7 255.255.255.0
 no shutdown
exit

ip route 0.0.0.0 0.0.0.0 192.168.128.1
ip http client source-interface Vlan128

end
write memory

! Verify
ping dashboard.meraki.com
show meraki compatibility

! Register
configure terminal
service meraki connect
end

! Wait 2-3 minutes, then check
show meraki connect
```

> **SAVE THE CLOUD ID** for this switch too.

---

## STEP 2: CLAIM SWITCHES IN MERAKI DASHBOARD

Once both switches show `Meraki Tunnel: Up` and you have both Cloud IDs:

### 2A. Log into Meraki Dashboard
1. Go to https://dashboard.meraki.com
2. Log in with your Meraki account

### 2B. Claim the Devices
1. Navigate to **Organization > Inventory**
2. Click **"Claim Devices"** (or **"+ Claim"** button)
3. Click **"Claim Individual Devices"**
4. Enter **BOTH Cloud IDs** (one per line):
   ```
   XXXX-XXXX-XXXX    (Border C9500-32C)
   YYYY-YYYY-YYYY    (Edge C9300X-48HXN)
   ```
5. Click **Claim**

### 2C. Add Switches to the SJC23-SDA Network
1. On the **Inventory** page, check the boxes next to both switches
2. Click **"Add to network"** (or select from Actions menu)
3. In the **"Add devices to network"** window:
   - Select network: **SJC23-SDA**
   - Click **Next**
4. Choose operating mode: **Device Configuration**
5. Enter the **privilege-15 credentials**:
   - Username: `meraki-admin`
   - Password: `<the password you set in Step 1D>`
6. Click **Next** → Review **Summary** → Click **Confirm**

### 2D. Wait for Onboarding to Complete
- Allow up to **15 minutes** for onboarding to finalize
- Dashboard will connect to the switch using the credentials provided
- Some configuration lines will be automatically applied (Meraki service account, SNMP, etc.)
- Navigate to **Switching > Switches** to see your devices

---

## STEP 3: VERIFY ONBOARDING

### 3A. On Dashboard
1. Go to **Switching > Switches**
2. Both switches should show as **Online** with green status
3. Click each switch to see details (model, firmware, uptime, ports)

### 3B. On Switch CLI
SSH into each switch and verify:

```
show meraki connect
```
Should show:
- Status: Registered
- Meraki Tunnel: Up

```
show running-config | include meraki
```
Should show:
- `service meraki connect`
- Meraki auto-provisioned service account

### 3C. Verify RESTCONF Still Works
From Ubuntu server (192.168.128.10):

```bash
curl -k -u admin:<password> \
  https://192.168.128.9:443/restconf/data/Cisco-IOS-XE-native:native/version \
  -H "Accept: application/yang-data+json"
```

Should return the IOS-XE version. If RESTCONF works, the relay server will work.

---

## STEP 4 (OPTIONAL): CLAIM VIA API

If you prefer using the Meraki API instead of Dashboard UI:

```bash
# Claim devices to organization
curl -X POST "https://api.meraki.com/api/v1/organizations/135358/inventory/claim" \
  -H "X-Cisco-Meraki-API-Key: 1bbb81c532e97a19bbac32032009eeaaa264fe31" \
  -H "Content-Type: application/json" \
  -d '{
    "serials": [],
    "orders": [],
    "licenses": [],
    "devices": [
      {"cloudId": "XXXX-XXXX-XXXX"},
      {"cloudId": "YYYY-YYYY-YYYY"}
    ]
  }'

# Add to network with Device Configuration mode
curl -X POST "https://api.meraki.com/api/v1/networks/L_591660401045811304/devices/claim" \
  -H "X-Cisco-Meraki-API-Key: 1bbb81c532e97a19bbac32032009eeaaa264fe31" \
  -H "Content-Type: application/json" \
  -d '{
    "serials": ["<SERIAL_1>", "<SERIAL_2>"]
  }'
```

Or use the existing script:
```powershell
python meraki_claim_switches.py --cloud-ids XXXX-XXXX-XXXX YYYY-YYYY-YYYY
```

---

## TROUBLESHOOTING

### "show meraki connect" shows Tunnel Down
1. Verify DNS: `ping dashboard.meraki.com`
2. Check firewall — switch needs outbound HTTPS (443) and port 7734
3. Verify `ip http client source-interface` points to an SVI with internet access
4. Check clock: `show clock` — must be within a few minutes of actual time
5. Check logs: `show logging | include meraki`

### Switch shows as Offline in Dashboard after claiming
1. Wait 15 minutes — onboarding takes time
2. Verify tunnel is up: `show meraki connect`
3. Check credentials — the username/password entered in Dashboard must match what's on the switch
4. Check AAA config: local authentication must be first in the method list

### RESTCONF stops working after onboarding
1. Meraki may modify `ip http` settings — re-verify:
   ```
   show running-config | include http
   ```
2. Re-apply if needed:
   ```
   configure terminal
   restconf
   ip http server
   ip http secure-server
   ip http authentication local
   end
   ```

### Cloud Monitoring vs Device Configuration confusion
- If you accidentally chose **Cloud Configuration**, the switch will factory reset!
- To recover: contact Meraki Support to convert back to DNA mode
- Always verify you selected **Device Configuration** before confirming

---

## WHAT HAPPENS AFTER ONBOARDING

After both switches are online in Dashboard with Device Configuration mode:

1. **Meraki monitors** the switches (health, alerts, topology)
2. **CLI remains fully accessible** — you can SSH and configure anything
3. **RESTCONF remains functional** — relay server can push SDA config
4. **Meraki Agentic Workflows** can orchestrate deployments via the relay server
5. The switch config is **NOT managed by Meraki** — your relay server manages it

This is exactly what we need for the SDA POC: Meraki provides visibility and
workflow orchestration, while the relay server handles all RESTCONF/SDA config.

---

## QUICK REFERENCE: COMMANDS SUMMARY

| Step | Command | Where |
|------|---------|-------|
| Check compatibility | `show meraki compatibility` | Switch CLI |
| Check boot mode | `show version \| include Mode` | Switch CLI |
| Enable AAA | `aaa new-model` | Switch config |
| Create user | `username meraki-admin privilege 15 secret 0 <PW>` | Switch config |
| Enable RESTCONF | `restconf` | Switch config |
| Set DNS | `ip name-server 8.8.8.8` | Switch config |
| Set NTP | `ntp server pool.ntp.org` | Switch config |
| Register with Meraki | `service meraki connect` | Switch config |
| Check registration | `show meraki connect` | Switch CLI |
| Get Cloud ID | `show meraki connect` | Switch CLI |
| Claim in Dashboard | Organization > Inventory > Claim | Meraki Dashboard |
| Add to network | Select switches > Add to SJC23-SDA | Meraki Dashboard |
| Choose mode | **Device Configuration** | Meraki Dashboard |
| Verify online | Switching > Switches | Meraki Dashboard |
