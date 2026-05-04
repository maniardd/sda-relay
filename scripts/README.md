# SDA Relay Optimization Setup — One-Time

After this setup, your dev loop becomes:

1. I push code → GitHub
2. VM pulls automatically within ~30 seconds
3. You run **one command** on VM: `~/diag.sh phase1`
4. You paste me **one URL** (a private GitHub Gist)

No more screenshots, no more long copy-paste, no more email middleman.

---

## ONE-TIME SETUP (run on VM via your Win10 jump host)

```bash
# 1. Install jq (used by diag.sh for safe JSON building)
sudo apt update && sudo apt install -y jq

# 2. Pull latest code (gets the scripts/ folder)
cd /opt/sda-relay
git pull

# 3. Make scripts executable
chmod +x scripts/auto-pull.sh scripts/diag.sh

# 4. Save your GitHub token (used ONLY for posting Gists)
#    Generate at https://github.com/settings/tokens?type=beta
#    Scope: Gists Read & Write
nano /opt/sda-relay/.env-gist
#    paste:    GITHUB_TOKEN=ghp_yourTokenHere
chmod 600 /opt/sda-relay/.env-gist

# 5. Convenience symlink so you can just type ./diag.sh
ln -sf /opt/sda-relay/scripts/diag.sh ~/diag.sh

# 6. Install auto-pull cron (every 30 seconds)
( crontab -l 2>/dev/null | grep -v auto-pull.sh ; \
  echo '* * * * * /opt/sda-relay/scripts/auto-pull.sh' ; \
  echo '* * * * * sleep 30; /opt/sda-relay/scripts/auto-pull.sh' \
) | crontab -

# 7. Verify
crontab -l
ls -la ~/diag.sh /opt/sda-relay/.env-gist
```

---

## DAILY USAGE

```bash
# After Copilot pushes a fix, wait ~30s, then:
~/diag.sh phase1

# Output ends with:  https://gist.github.com/<id>
# Paste that URL to Copilot in chat. Done.
```

### Other commands

```bash
~/diag.sh                  # just snapshot current state, no deploy
~/diag.sh phase2           # trigger phase 2 + capture
~/diag.sh wipe-isis        # nuke ISIS so next phase1 truly recreates it

tail -f /tmp/auto-pull.log # watch auto-pulls happening
tail -f /tmp/sda-relay.log # watch live relay traffic
```

### If auto-pull misbehaves

```bash
# Disable temporarily
crontab -l | grep -v auto-pull | crontab -

# Or run a manual pull
cd /opt/sda-relay && git pull && pkill -f gunicorn && sleep 2 && \
  nohup ./venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 sda_relay_server_v2:app > /tmp/sda-relay.log 2>&1 & disown
```
