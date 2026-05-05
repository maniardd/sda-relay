# Latest SDA v3 Deploy Result

- Commit: `e3655ca53e031525cd0ac2eaf0ad7e1a5df04369`
- Time: 2026-05-05T10:25:26Z
- Trigger: push

## /health
```json
{"deployment_status":"idle","endpoints":7,"status":"relay_running","transport":"netmiko-cli","version":"3.0"}

```
## /api/v3/precheck
```json
{"checks":{"border":{"error":"No password for border (set C9500_PASS in /opt/sda-relay/.env)","status":"fail"},"edge":{"error":"No password for edge (set C9300_PASS in /opt/sda-relay/.env)","status":"fail"}},"overall":"fail","timestamp":"2026-05-05T10:25:26.335825Z"}

```
## /api/v3/deploy/phase1-underlay
```json
{"overall":"fail","phase":"phase1-underlay","targets":{"border":{"error":"No password for border (set C9500_PASS in /opt/sda-relay/.env)","status":"fail"},"edge":{"error":"No password for edge (set C9300_PASS in /opt/sda-relay/.env)","status":"fail"}}}

```
## /api/v3/verify/phase1-underlay
```json
{"overall":"fail","phase":"phase1-underlay","targets":{"border":{"error":"No password for border (set C9500_PASS in /opt/sda-relay/.env)"},"edge":{"error":"No password for edge (set C9300_PASS in /opt/sda-relay/.env)"}}}

```
