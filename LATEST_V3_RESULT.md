# Latest SDA v3 Deploy Result

- Commit: `a703ff1b948dcc4946228f608b7ed257bd4cf427`
- Time: 2026-05-05T10:26:54Z
- Trigger: push

## /health
```json
{"deployment_status":"idle","endpoints":7,"status":"relay_running","transport":"netmiko-cli","version":"3.0"}

```
## /api/v3/precheck
```json
{"checks":{"border":{"error":"No password for border (set C9500_PASS in /opt/sda-relay/.env)","status":"fail"},"edge":{"error":"No password for edge (set C9300_PASS in /opt/sda-relay/.env)","status":"fail"}},"overall":"fail","timestamp":"2026-05-05T10:26:54.146617Z"}

```
## /api/v3/deploy/phase1-underlay
```json
{"overall":"fail","phase":"phase1-underlay","targets":{"border":{"error":"No password for border (set C9500_PASS in /opt/sda-relay/.env)","status":"fail"},"edge":{"error":"No password for edge (set C9300_PASS in /opt/sda-relay/.env)","status":"fail"}}}

```
## /api/v3/verify/phase1-underlay
```json
{"overall":"fail","phase":"phase1-underlay","targets":{"border":{"error":"No password for border (set C9500_PASS in /opt/sda-relay/.env)"},"edge":{"error":"No password for edge (set C9300_PASS in /opt/sda-relay/.env)"}}}

```
