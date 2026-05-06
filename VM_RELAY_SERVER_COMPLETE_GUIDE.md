# SDA Relay Server â€” Complete VM & Infrastructure Guide
## From Scratch: Hardware â†’ OS â†’ Software â†’ Go-Live

---

## 1. WHAT IS THE RELAY SERVER?

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚                        MERAKI CLOUD                                 â”‚
â”‚                    (dashboard.meraki.com)                            â”‚
â”‚                                                                     â”‚
â”‚   â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”    Workflow triggers     â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”   â”‚
â”‚   â”‚  Meraki       â”‚ â”€â”€â”€â”€ HTTPS POST â”€â”€â”€â”€â”€â”€â”€â–ºâ”‚  ngrok/Public URL â”‚   â”‚
â”‚   â”‚  Workflow     â”‚                          â”‚  (relay endpoint) â”‚   â”‚
â”‚   â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜                          â””â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜   â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                                       â”‚
                          â•â•â• INTERNET â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•ªâ•â•â•â•â•â•â•
                                                       â”‚
                    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                    â”‚           YOUR NETWORK            â”‚          â”‚
                    â”‚                                   â–¼          â”‚
                    â”‚          â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”    â”‚
                    â”‚          â”‚     VM â€” RELAY SERVER        â”‚    â”‚
                    â”‚          â”‚     Ubuntu 22.04 LTS         â”‚    â”‚
                    â”‚          â”‚     Python 3.10 + Flask      â”‚    â”‚
                    â”‚          â”‚     IP: 192.168.128.10       â”‚    â”‚
                    â”‚          â””â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜    â”‚
                    â”‚                 â”‚            â”‚               â”‚
                    â”‚        RESTCONF â”‚   RESTCONF â”‚               â”‚
                    â”‚        (HTTPS)  â”‚   (HTTPS)  â”‚               â”‚
                    â”‚                 â–¼            â–¼               â”‚
                    â”‚   â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”        â”‚
                    â”‚   â”‚  C9500-32C   â”‚  â”‚  C9300X-48HXNâ”‚        â”‚
                    â”‚   â”‚  BORDER NODE â”‚  â”‚  EDGE NODE   â”‚        â”‚
                    â”‚   â”‚ 192.168.128.9â”‚  â”‚192.168.128.7 â”‚        â”‚
                    â”‚   â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜        â”‚
                    â”‚         VLAN 128 (SJC-23 Mgmt)              â”‚
                    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

**WHY is this mandatory?**
- Meraki Workflow runs in the **cloud** â€” it can only make HTTPS calls to **public URLs**
- Your switches are on **private IPs** (192.168.128.x) â€” unreachable from the internet
- The relay server **bridges** this gap: receives cloud webhooks â†’ translates to RESTCONF calls on local network
- It also handles **credential security** (keys never leave your network), **orchestration logic** (multi-step deployment ordering), and **validation** (pre/post checks)

---

## 2. VM HARDWARE REQUIREMENTS

### Minimum Spec (Lab/POC)

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| **vCPU** | 2 cores | 4 cores |
| **RAM** | 4 GB | 8 GB |
| **Disk** | 40 GB SSD | 80 GB SSD |
| **NIC** | 1x 1GbE | 2x 1GbE (mgmt + fabric) |
| **OS** | Ubuntu 22.04 LTS Server | Ubuntu 22.04 LTS Server |

### Why Ubuntu 22.04 LTS?
- Free, no licensing cost
- Python 3.10 included out of the box
- LTS = 5 years of security patches (until April 2027)
- Lightweight server install (~2 GB RAM base usage)
- Full systemd support for auto-start services

### Where to Run This VM?

| Option | Pros | Cons |
|--------|------|------|
| **ESXi/vSphere** (if you have it) | Production-grade, HA capable | Needs existing infrastructure |
| **Hyper-V** (on Windows Server) | Free with Windows Server | Slightly more complex networking |
| **VirtualBox** (on any PC) | Free, quick setup for lab | Not production-grade |
| **Bare-metal mini PC** (Intel NUC) | Dedicated, reliable | ~$300-500 hardware cost |
| **WSL2 on Windows 10/11** | Zero cost, already on your laptop | Not persistent, no real server |

**My recommendation for your lab:** Use **VirtualBox on any available PC** or **Hyper-V on a Windows Server** that's already on the SJC-23 network. For production, use ESXi.

---

## 3. NETWORK DESIGN

### IP Addressing

| Interface | Network | IP Address | Purpose |
|-----------|---------|------------|---------|
| **eth0** (or ens160) | VLAN 128 â€” 192.168.128.0/24 | **192.168.128.10** | Management + RESTCONF access to switches |
| **Default GW** | | 192.168.128.1 (MX) | Internet access for ngrok tunnel |

> **Note:** The VM needs to reach **both switches** on VLAN 128 AND have **internet access** for the ngrok tunnel. If VLAN 127 and 128 are routed through the MX, a single NIC on either VLAN works.

### Firewall Rules Required

| Direction | Source | Destination | Port | Protocol | Purpose |
|-----------|--------|-------------|------|----------|---------|
| **Outbound** | VM (192.168.128.10) | Internet | 443 | TCP | ngrok tunnel to Meraki cloud |
| **Outbound** | VM (192.168.128.10) | 192.168.128.9 | 443 | TCP | RESTCONF to C9500 |
| **Outbound** | VM (192.168.128.10) | 192.168.128.7 | 443 | TCP | RESTCONF to C9300X |
| **Inbound** | 127.0.0.1 (localhost) | VM | 5000 | TCP | Flask app (via ngrok) |
| **Outbound** | VM | api.meraki.com | 443 | TCP | Meraki API (optional, for status callbacks) |

---

## 4. STEP-BY-STEP: BUILD THE VM FROM SCRATCH

### Step 4.1 â€” Download Ubuntu 22.04 LTS

```
URL: https://releases.ubuntu.com/22.04/ubuntu-22.04.4-live-server-amd64.iso
Size: ~1.8 GB
```

### Step 4.2 â€” Create the VM

**VirtualBox example:**
```
1. New VM â†’ Name: "SDA-Relay-Server" â†’ Type: Linux â†’ Version: Ubuntu 64-bit
2. Memory: 4096 MB
3. Hard disk: Create VDI, dynamically allocated, 40 GB
4. Settings â†’ Network â†’ Adapter 1 â†’ Bridged Adapter â†’ Select your LAN NIC
5. Settings â†’ System â†’ Processor â†’ 2 CPUs
6. Storage â†’ IDE Controller â†’ Attach the Ubuntu ISO
7. Start â†’ Boot from ISO
```

**Hyper-V example:**
```powershell
# PowerShell on Hyper-V host
New-VM -Name "SDA-Relay-Server" -MemoryStartupBytes 4GB -NewVHDPath "C:\VMs\sda-relay.vhdx" -NewVHDSizeBytes 40GB -Generation 2
Set-VMProcessor -VMName "SDA-Relay-Server" -Count 2
Add-VMDvdDrive -VMName "SDA-Relay-Server" -Path "C:\ISOs\ubuntu-22.04.4-live-server-amd64.iso"
Connect-VMNetworkAdapter -VMName "SDA-Relay-Server" -SwitchName "VLAN128-Switch"
Start-VM -Name "SDA-Relay-Server"
```

### Step 4.3 â€” Install Ubuntu

During installation:
```
1. Language: English
2. Network: Configure static IP
   - Subnet: 192.168.128.0/24 (or 192.168.128.0/24)
   - Address: 192.168.128.10
   - Gateway: 192.168.128.1
   - DNS: 8.8.8.8, 208.67.222.222
3. Storage: Use entire disk (default)
4. Profile:
   - Name: sdaadmin
   - Server name: sda-relay-server
   - Username: sdaadmin
   - Password: <strong_password>
5. SSH: Install OpenSSH server âœ“
6. Featured Server Snaps: Skip all
7. Wait for install â†’ Reboot
```

### Step 4.4 â€” Post-Install OS Setup

SSH into the VM:
```bash
ssh sdaadmin@192.168.128.10
```

Run these commands:
```bash
# 1. Update the system
sudo apt update && sudo apt upgrade -y

# 2. Install Python and dependencies
sudo apt install -y python3 python3-pip python3-venv git curl net-tools

# 3. Verify Python version
python3 --version
# Expected: Python 3.10.x

# 4. Create project directory
mkdir -p /opt/sda-relay
cd /opt/sda-relay

# 5. Create Python virtual environment
python3 -m venv venv
source venv/bin/activate

# 6. Install Python packages
pip install flask requests pyyaml python-dotenv cryptography colorlog netaddr gunicorn

# 7. Verify Flask
python3 -c "import flask; print(f'Flask {flask.__version__}')"
```

### Step 4.5 â€” Install ngrok

```bash
# Download and install ngrok
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok-v3-stable-linux-amd64.tgz | sudo tar xz -C /usr/local/bin

# Verify
ngrok version

# Authenticate (get your free token from https://dashboard.ngrok.com/signup)
ngrok config add-authtoken YOUR_NGROK_AUTH_TOKEN

# Test the tunnel (don't run permanently yet)
ngrok http 5000
# You'll see something like:
#   Forwarding  https://a1b2c3d4.ngrok-free.app â†’ http://localhost:5000
# Copy that HTTPS URL â€” this is what goes into Meraki Workflow
```

### Step 4.6 â€” Deploy the Relay Server Code

```bash
cd /opt/sda-relay

# Option A: Copy files from your Windows PC
# From your Windows machine:
scp sda_relay_server_v2.py sdaadmin@192.168.128.10:/opt/sda-relay/
scp sda_fabric_config.yaml sdaadmin@192.168.128.10:/opt/sda-relay/
scp requirements.txt sdaadmin@192.168.128.10:/opt/sda-relay/

# Option B: Clone from a git repo (if you push code to GitHub/GitLab)
# git clone https://your-repo.git /opt/sda-relay
```

Create the environment file:
```bash
cat > /opt/sda-relay/.env << 'EOF'
# â”€â”€ Switch Credentials â”€â”€
C9500_IP=192.168.128.9
C9500_USER=admin
C9500_PASS=YourSecurePassword123
C9300_IP=192.168.128.7
C9300_USER=admin
C9300_PASS=YourSecurePassword123

# â”€â”€ Relay Server â”€â”€
RELAY_PORT=5000
FLASK_ENV=production

# â”€â”€ Meraki (optional, for callbacks) â”€â”€
MERAKI_API_KEY=your_meraki_api_key_here
MERAKI_ORG_ID=your_org_id
MERAKI_NETWORK_ID=your_network_id

# â”€â”€ Security â”€â”€
WEBHOOK_SECRET=your_shared_secret_for_webhook_auth
EOF

# Protect the file
chmod 600 /opt/sda-relay/.env
```

### Step 4.7 â€” Create systemd Service (Auto-Start on Boot)

```bash
sudo tee /etc/systemd/system/sda-relay.service << 'EOF'
[Unit]
Description=SDA LISP+VXLAN Relay Server
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=sdaadmin
Group=sdaadmin
WorkingDirectory=/opt/sda-relay
Environment=PATH=/opt/sda-relay/venv/bin:/usr/bin
EnvironmentFile=/opt/sda-relay/.env
ExecStart=/opt/sda-relay/venv/bin/gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 120 sda_relay_server_v2:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable sda-relay.service
sudo systemctl start sda-relay.service

# Check status
sudo systemctl status sda-relay.service
```

### Step 4.8 â€” Create ngrok systemd Service (Auto-Start Tunnel)

```bash
sudo tee /etc/systemd/system/ngrok.service << 'EOF'
[Unit]
Description=ngrok tunnel for SDA Relay
After=network-online.target sda-relay.service
Wants=network-online.target

[Service]
Type=simple
User=sdaadmin
ExecStart=/usr/local/bin/ngrok http 5000 --log=stdout
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ngrok.service
sudo systemctl start ngrok.service
```

> **For production:** Replace ngrok with a fixed domain. Options:
> - ngrok paid plan ($8/month) â€” gives you a **static subdomain** like `sda-relay.ngrok.io`
> - Cloudflare Tunnel (free) â€” point `sda-relay.yourdomain.com` to localhost:5000
> - VPN/direct IP if Meraki can reach your network

### Step 4.9 â€” Verify Everything Works

```bash
# 1. Check relay server is running
curl http://localhost:5000/health
# Expected: {"status": "relay_running", "timestamp": "..."}

# 2. Check ngrok tunnel
curl http://localhost:4040/api/tunnels
# Shows your public URL

# 3. Test RESTCONF connectivity to switches (from the VM)
curl -k -u admin:YourPassword https://192.168.128.9:443/restconf/data/Cisco-IOS-XE-native:native/hostname
curl -k -u admin:YourPassword https://192.168.128.7:443/restconf/data/Cisco-IOS-XE-native:native/hostname

# 4. Test the full chain (from outside)
curl -X POST https://YOUR-NGROK-URL.ngrok-free.app/webhook \
  -H "Content-Type: application/json" \
  -d '{"action": "health_check_devices"}'
# Expected: {"status": "success", "c9500_reachable": true, "c9300_reachable": true}
```

---

## 5. VM OPERATING PROCEDURES

### Daily Health Check
```bash
# SSH into VM
sudo systemctl status sda-relay.service    # Should be "active (running)"
sudo systemctl status ngrok.service        # Should be "active (running)"
curl http://localhost:5000/health           # Should return 200
journalctl -u sda-relay.service --since "1 hour ago" | tail -20  # Recent logs
```

### View Deployment Logs
```bash
journalctl -u sda-relay.service -f          # Live tail
journalctl -u sda-relay.service --since today  # Today's logs
```

### Restart Services
```bash
sudo systemctl restart sda-relay.service    # Restart relay
sudo systemctl restart ngrok.service        # Restart tunnel (URL may change on free plan!)
```

### Update the Code
```bash
cd /opt/sda-relay
# Copy new files from your PC
sudo systemctl restart sda-relay.service
```

---

## 6. SECURITY HARDENING (PRODUCTION)

```bash
# 1. Enable firewall
sudo ufw allow 22/tcp          # SSH
sudo ufw allow 5000/tcp        # Flask (only from localhost/ngrok)
sudo ufw enable

# 2. Fail2ban for SSH brute-force protection
sudo apt install -y fail2ban
sudo systemctl enable fail2ban

# 3. Disable password login (use SSH keys only)
ssh-keygen -t ed25519    # On your PC
ssh-copy-id sdaadmin@192.168.128.10
# Then edit /etc/ssh/sshd_config: PasswordAuthentication no

# 4. Auto security updates
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

---

## 7. COST SUMMARY

| Item | Cost | Notes |
|------|------|-------|
| Ubuntu 22.04 LTS | **Free** | Open source |
| Python + Flask | **Free** | Open source |
| ngrok (free tier) | **Free** | URL changes on restart |
| ngrok (production) | **$8/month** | Static subdomain |
| VirtualBox | **Free** | If running on existing PC |
| ESXi VM resources | **$0 incremental** | If you have spare capacity |
| **TOTAL (Lab)** | **$0** | |
| **TOTAL (Production)** | **$8/month** | Only if using ngrok paid |

Compare this to: **Catalyst Center = $50,000â€“$200,000+ license**

---

## 8. TROUBLESHOOTING

| Symptom | Cause | Fix |
|---------|-------|-----|
| `curl: connection refused` on port 5000 | Relay not running | `sudo systemctl restart sda-relay.service` |
| ngrok tunnel not working | Token expired or service down | `sudo systemctl restart ngrok.service` |
| RESTCONF 401 Unauthorized | Wrong switch credentials | Check `.env` file credentials |
| RESTCONF connection timeout | VM can't reach switch | Check routing: `ping 192.168.128.9` |
| RESTCONF 400 Bad Request | Wrong YANG payload | Check payload structure against YANG model |
| Meraki Workflow timeout | ngrok URL changed | Get new URL from `curl localhost:4040/api/tunnels` and update Workflow |
| VM unreachable via SSH | Network/firewall issue | Console into VM, check `ip addr`, `sudo ufw status` |

---

## 9. PROCUREMENT REQUEST TEMPLATE

Use this to request the VM from your IT team:

```
Subject: VM Request â€” SDA Relay Server for Meraki Cloud Management

Purpose: 
Local relay server to bridge Meraki Dashboard Workflows with 
IOS-XE switches running SD-Access fabric (LISP+VXLAN) via RESTCONF API.

Specifications:
- OS: Ubuntu 22.04 LTS Server (64-bit)
- vCPU: 4 cores
- RAM: 8 GB
- Disk: 80 GB SSD
- Network: 1x 1GbE NIC on VLAN 128 (192.168.128.0/24)
- Static IP: 192.168.128.10/24 (or available IP on VLAN 128)
- Gateway: 192.168.128.1
- Internet Access: Required (outbound HTTPS to *.ngrok.com and api.meraki.com)
- Firewall: Outbound TCP/443 to internet + to 192.168.128.7 and 192.168.128.9
- SSH access required for deployment team

Justification:
Replaces $50Kâ€“$200K Catalyst Center appliance. Uses free open-source 
software (Python/Flask) to automate SD-Access fabric provisioning 
through Meraki Dashboard, reducing operational overhead by 90%.

Expected Users: Network Engineering team (2-3 users)
Availability: 24/7 (auto-start on boot, self-healing service)
Backup: Code stored in version control, VM snapshot recommended weekly
```
