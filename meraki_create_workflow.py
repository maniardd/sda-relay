#!/usr/bin/env python3
"""
Meraki Workflow Importer — Automatically Create SDA Workflow via API

This script reads meraki_workflow_v2_export.json and creates the complete
21-activity workflow in your Meraki Dashboard using the Meraki API.

Usage:
  python meraki_create_workflow.py --api-key YOUR_API_KEY --org-id YOUR_ORG_ID

  Or set environment variables:
    MERAKI_API_KEY=your_key
    MERAKI_ORG_ID=your_org_id
    python meraki_create_workflow.py

Prerequisites:
  pip install requests python-dotenv
"""

import argparse
import json
import os
import sys
import time
import logging
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger("meraki-workflow-importer")

# ── MERAKI API BASE ───────────────────────────────────────────────────
MERAKI_BASE = "https://api.meraki.com/api/v1"
RATE_LIMIT_WAIT = 1  # seconds between API calls to avoid 429


class MerakiWorkflowImporter:
    """Creates a Meraki Workflow programmatically via the Dashboard API."""

    def __init__(self, api_key: str, org_id: str):
        self.api_key = api_key
        self.org_id = org_id
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    # ── LOW-LEVEL API CALLS ───────────────────────────────────────────

    def _api_get(self, path: str) -> dict:
        url = f"{MERAKI_BASE}{path}"
        r = self.session.get(url, timeout=30)
        if r.status_code == 200:
            return r.json()
        logger.error(f"GET {path} → {r.status_code}: {r.text[:300]}")
        r.raise_for_status()

    def _api_post(self, path: str, payload: dict) -> dict:
        url = f"{MERAKI_BASE}{path}"
        r = self.session.post(url, json=payload, timeout=30)
        if r.status_code in (200, 201, 202):
            return r.json() if r.text.strip() else {}
        logger.error(f"POST {path} → {r.status_code}: {r.text[:500]}")
        r.raise_for_status()

    # ── VERIFY ORG ACCESS ─────────────────────────────────────────────

    def verify_org(self) -> bool:
        """Verify API key and org access."""
        try:
            org = self._api_get(f"/organizations/{self.org_id}")
            logger.info(f"✅ Connected to org: {org.get('name', 'unknown')} (ID: {self.org_id})")
            return True
        except Exception as e:
            logger.error(f"❌ Cannot access org {self.org_id}: {e}")
            return False

    # ── LIST EXISTING WORKFLOWS ───────────────────────────────────────

    def list_workflows(self) -> List[dict]:
        """List existing workflows in the org."""
        try:
            workflows = self._api_get(f"/organizations/{self.org_id}/automations/workflows")
            return workflows if isinstance(workflows, list) else []
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning("Workflows API endpoint not found — feature may not be enabled for this org")
                return []
            raise

    # ── CREATE HTTP TARGET ────────────────────────────────────────────

    def create_http_target(self, target_cfg: dict) -> Optional[str]:
        """Create an HTTP webhook target. Returns target ID."""
        payload = {
            "name": target_cfg["name"],
            "url": target_cfg["url"],
            "sharedSecret": target_cfg.get("headers", {}).get("X-Webhook-Secret", ""),
        }
        try:
            # Try org-level webhook HTTP servers
            result = self._api_post(
                f"/organizations/{self.org_id}/webhooks/httpServers",
                payload,
            )
            target_id = result.get("id")
            logger.info(f"✅ Created HTTP target: {target_cfg['name']} (ID: {target_id})")
            return target_id
        except requests.exceptions.HTTPError:
            logger.warning("Org-level webhook target creation not available — will use inline URL in workflow")
            return None

    # ── BUILD WORKFLOW PAYLOAD ────────────────────────────────────────

    def _build_activity(self, act: dict, target_url: str) -> dict:
        """Convert our JSON activity format to Meraki API format."""
        act_type = act["type"]

        if act_type == "Input Form":
            return {
                "id": act["id"],
                "type": "inputForm",
                "name": act["name"],
                "description": act.get("description", ""),
                "properties": {
                    "fields": [
                        {
                            "name": f["name"],
                            "label": f.get("label", f["name"]),
                            "type": self._map_field_type(f.get("type", "text")),
                            "defaultValue": f.get("default", ""),
                            "required": f.get("required", False),
                        }
                        for f in act.get("fields", [])
                    ]
                },
                "next": act.get("next"),
            }

        elif act_type == "Send HTTP Request":
            return {
                "id": act["id"],
                "type": "httpRequest",
                "name": act["name"],
                "description": act.get("description", ""),
                "properties": {
                    "url": f"{target_url}{act['path']}",
                    "method": act.get("method", "POST"),
                    "headers": {
                        "Content-Type": "application/json",
                    },
                    "body": json.dumps(act.get("body", {})),
                    "timeout": act.get("timeout", 30),
                },
                "next": act.get("next"),
            }

        elif act_type == "Condition":
            return {
                "id": act["id"],
                "type": "condition",
                "name": act["name"],
                "properties": {
                    "expression": act.get("condition", ""),
                },
                "truePath": act.get("true_path"),
                "falsePath": act.get("false_path"),
            }

        elif act_type == "Delay":
            return {
                "id": act["id"],
                "type": "delay",
                "name": act["name"],
                "properties": {
                    "duration": act.get("duration_seconds", 10),
                    "unit": "seconds",
                },
                "next": act.get("next"),
            }

        elif act_type == "Notification":
            return {
                "id": act["id"],
                "type": "notification",
                "name": act["name"],
                "properties": {
                    "channel": act.get("channel", "email"),
                    "recipients": act.get("to", []),
                    "subject": act.get("subject", ""),
                    "body": act.get("body", ""),
                },
                "next": act.get("next"),
            }

        elif act_type == "End":
            return {
                "id": act["id"],
                "type": "end",
                "name": act["name"],
            }

        else:
            logger.warning(f"Unknown activity type: {act_type} — passing through as-is")
            return {
                "id": act["id"],
                "type": act_type.lower().replace(" ", ""),
                "name": act["name"],
                "next": act.get("next"),
            }

    def _map_field_type(self, field_type: str) -> str:
        """Map our field types to Meraki API field types."""
        mapping = {
            "text": "string",
            "number": "number",
            "boolean": "boolean",
            "select": "enum",
        }
        return mapping.get(field_type, "string")

    def build_workflow_payload(self, workflow_def: dict, target_url: str) -> dict:
        """Build the complete Meraki API workflow creation payload."""
        activities = []
        for act in workflow_def.get("activities", []):
            converted = self._build_activity(act, target_url)
            activities.append(converted)

        return {
            "name": workflow_def["name"],
            "description": workflow_def.get("description", ""),
            "trigger": {
                "type": workflow_def.get("trigger", "manual"),
            },
            "activities": activities,
        }

    # ── CREATE WORKFLOW ───────────────────────────────────────────────

    def create_workflow(self, workflow_def: dict, target_url: str) -> Optional[str]:
        """Create the complete workflow. Returns workflow ID."""
        payload = self.build_workflow_payload(workflow_def, target_url)

        logger.info(f"Creating workflow: {payload['name']}")
        logger.info(f"  Activities: {len(payload['activities'])}")
        logger.info(f"  Target URL: {target_url}")

        try:
            result = self._api_post(
                f"/organizations/{self.org_id}/automations/workflows",
                payload,
            )
            wf_id = result.get("id", result.get("workflowId", "unknown"))
            logger.info(f"✅ Workflow created successfully! ID: {wf_id}")
            return wf_id

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            body = e.response.text[:500]

            if status == 404:
                logger.error("❌ Workflows API not found (404).")
                logger.error("   This means either:")
                logger.error("   1. Your org doesn't have the Automation/Workflows feature enabled")
                logger.error("   2. The API endpoint path is different for your org")
                logger.error("")
                logger.error("   FALLBACK: Use the manual GUI setup or try the alternative approaches below.")
                self._suggest_alternatives(workflow_def, target_url)
                return None

            elif status == 400:
                logger.error(f"❌ Bad request (400): {body}")
                logger.error("   The workflow payload format may need adjustment for your API version.")
                logger.error("   Saving payload to workflow_api_payload.json for debugging...")
                with open("workflow_api_payload.json", "w") as f:
                    json.dump(payload, f, indent=2)
                return None

            elif status == 403:
                logger.error("❌ Forbidden (403). Your API key may not have write access to Automation.")
                return None

            else:
                logger.error(f"❌ API error {status}: {body}")
                return None

    # ── ALTERNATIVE APPROACHES ────────────────────────────────────────

    def _suggest_alternatives(self, workflow_def: dict, target_url: str):
        """If the Workflows API doesn't work, suggest alternatives."""
        logger.info("")
        logger.info("=" * 60)
        logger.info("ALTERNATIVE APPROACHES:")
        logger.info("=" * 60)
        logger.info("")
        logger.info("Option A: Use Action Batches API (simpler)")
        logger.info("  POST /organizations/{orgId}/actionBatches")
        logger.info("  This creates a batch of API actions — more widely available")
        logger.info("")
        logger.info("Option B: Use the Meraki Dashboard GUI")
        logger.info("  Follow the step-by-step guide in the previous chat messages")
        logger.info("  The workflow_gui_guide.txt has been saved for reference")
        logger.info("")
        logger.info("Option C: Use Meraki Webhook + Payload Templates")
        logger.info("  Create webhooks that trigger on events and call your relay")
        logger.info("  More limited but universally available")

        # Save the GUI guide as a reference
        self._save_gui_guide(workflow_def, target_url)

    def _save_gui_guide(self, workflow_def: dict, target_url: str):
        """Save a text guide for manual GUI creation."""
        guide_lines = [
            "MERAKI WORKFLOW — GUI SETUP QUICK REFERENCE",
            "=" * 50,
            f"Workflow Name: {workflow_def['name']}",
            f"Target URL: {target_url}",
            "",
            "ACTIVITIES TO CREATE (in order):",
            "-" * 40,
        ]

        for i, act in enumerate(workflow_def.get("activities", []), 1):
            act_type = act["type"]
            name = act["name"]

            if act_type == "Send HTTP Request":
                guide_lines.append(f"\n{i}. [{act_type}] {name}")
                guide_lines.append(f"   Method: {act.get('method', 'POST')}")
                guide_lines.append(f"   URL: {target_url}{act.get('path', '')}")
                guide_lines.append(f"   Body: {json.dumps(act.get('body', {}), indent=6)}")
                guide_lines.append(f"   Timeout: {act.get('timeout', 30)}s")

            elif act_type == "Condition":
                guide_lines.append(f"\n{i}. [{act_type}] {name}")
                guide_lines.append(f"   Expression: {act.get('condition', '')}")
                guide_lines.append(f"   TRUE  → {act.get('true_path', '')}")
                guide_lines.append(f"   FALSE → {act.get('false_path', '')}")

            elif act_type == "Delay":
                guide_lines.append(f"\n{i}. [{act_type}] {name}")
                guide_lines.append(f"   Duration: {act.get('duration_seconds', 10)}s")

            elif act_type == "Input Form":
                guide_lines.append(f"\n{i}. [{act_type}] {name}")
                guide_lines.append(f"   Fields: {len(act.get('fields', []))}")
                for f in act.get("fields", []):
                    guide_lines.append(f"     - {f['name']} ({f.get('type','text')}): default={f.get('default','')}")

            elif act_type == "Notification":
                guide_lines.append(f"\n{i}. [{act_type}] {name}")
                guide_lines.append(f"   Subject: {act.get('subject', '')}")

            else:
                guide_lines.append(f"\n{i}. [{act_type}] {name}")

        filepath = os.path.join(os.path.dirname(__file__), "workflow_gui_guide.txt")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(guide_lines))
        logger.info(f"  GUI guide saved: {filepath}")

    # ── DRY RUN ───────────────────────────────────────────────────────

    def dry_run(self, workflow_def: dict, target_url: str):
        """Preview what would be created, without making API calls."""
        payload = self.build_workflow_payload(workflow_def, target_url)

        print("\n" + "=" * 60)
        print("DRY RUN — Workflow Preview (no API calls)")
        print("=" * 60)
        print(f"\nWorkflow: {payload['name']}")
        print(f"Description: {payload['description']}")
        print(f"Trigger: {payload['trigger']['type']}")
        print(f"Target URL: {target_url}")
        print(f"Total Activities: {len(payload['activities'])}")
        print("\nActivities:")
        print("-" * 50)

        for i, act in enumerate(payload["activities"], 1):
            act_type = act.get("type", "?")
            name = act.get("name", "?")
            next_id = act.get("next", act.get("truePath", "-"))

            if act_type == "httpRequest":
                url = act["properties"]["url"]
                method = act["properties"]["method"]
                print(f"  {i:2d}. [{act_type:12s}] {name}")
                print(f"      → {method} {url}")
            elif act_type == "condition":
                true_p = act.get("truePath", "?")
                false_p = act.get("falsePath", "?")
                print(f"  {i:2d}. [{act_type:12s}] {name}")
                print(f"      TRUE → {true_p}  |  FALSE → {false_p}")
            elif act_type == "delay":
                dur = act["properties"]["duration"]
                print(f"  {i:2d}. [{act_type:12s}] {name} ({dur}s)")
            elif act_type == "inputForm":
                fields = len(act["properties"]["fields"])
                print(f"  {i:2d}. [{act_type:12s}] {name} ({fields} fields)")
            else:
                print(f"  {i:2d}. [{act_type:12s}] {name}")

        print("\n" + "-" * 50)
        print("Wiring (connections):")
        for act in payload["activities"]:
            src = act.get("id", "?")
            if "truePath" in act:
                print(f"  {src} ──TRUE──► {act['truePath']}")
                print(f"  {src} ──FALSE─► {act['falsePath']}")
            elif "next" in act and act["next"]:
                print(f"  {src} ────────► {act['next']}")

        # Save payload to file for inspection
        output_file = os.path.join(os.path.dirname(__file__), "workflow_api_payload.json")
        with open(output_file, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"\n✅ API payload saved to: {output_file}")
        print("   Review this file, then run without --dry-run to create the workflow.")
        print("=" * 60)


# ══════════════════════════════════════════════════════════════════════
#  MAIN — CLI
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Create Meraki Workflow via API — SDA Fabric Deployment"
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("MERAKI_API_KEY"),
        help="Meraki Dashboard API key (or set MERAKI_API_KEY env var)",
    )
    parser.add_argument(
        "--org-id",
        default=os.getenv("MERAKI_ORG_ID"),
        help="Meraki Organization ID (or set MERAKI_ORG_ID env var)",
    )
    parser.add_argument(
        "--workflow-file",
        default=os.path.join(os.path.dirname(__file__), "meraki_workflow_v2_export.json"),
        help="Path to workflow definition JSON",
    )
    parser.add_argument(
        "--target-url",
        default=os.getenv("NGROK_URL", "https://placeholder.ngrok-free.app"),
        help="Your relay server's public URL (ngrok URL)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the workflow without creating it (no API calls)",
    )
    parser.add_argument(
        "--notification-email",
        default=os.getenv("NOTIFICATION_EMAIL", "network-engineering@company.com"),
        help="Email for success/failure notifications",
    )
    args = parser.parse_args()

    # Load workflow definition
    if not os.path.exists(args.workflow_file):
        logger.error(f"Workflow file not found: {args.workflow_file}")
        sys.exit(1)

    with open(args.workflow_file, "r", encoding="utf-8") as f:
        workflow_def = json.load(f)

    logger.info(f"Loaded workflow: {workflow_def['name']}")
    logger.info(f"  Activities: {len(workflow_def.get('activities', []))}")
    logger.info(f"  Target URL: {args.target_url}")

    # Replace placeholder email in notifications
    for act in workflow_def.get("activities", []):
        if act.get("type") == "Notification" and "to" in act:
            act["to"] = [args.notification_email]

    # Dry run mode
    if args.dry_run:
        importer = MerakiWorkflowImporter("dry-run-key", "dry-run-org")
        importer.dry_run(workflow_def, args.target_url)
        sys.exit(0)

    # Validate required params
    if not args.api_key:
        logger.error("❌ Meraki API key required. Use --api-key or set MERAKI_API_KEY env var.")
        logger.info("   Get your API key: Dashboard → My Profile → API access → Generate API key")
        sys.exit(1)

    if not args.org_id:
        logger.error("❌ Meraki Org ID required. Use --org-id or set MERAKI_ORG_ID env var.")
        logger.info("   Find your Org ID: Dashboard → Organization → Settings → Organization ID")
        sys.exit(1)

    # Create importer and verify access
    importer = MerakiWorkflowImporter(args.api_key, args.org_id)

    if not importer.verify_org():
        sys.exit(1)

    # Check for existing workflows
    logger.info("Checking for existing workflows...")
    existing = importer.list_workflows()
    for wf in existing:
        if wf.get("name") == workflow_def["name"]:
            logger.warning(f"⚠️  Workflow '{workflow_def['name']}' already exists (ID: {wf.get('id')})")
            logger.warning("   Delete it first via Dashboard or API, or rename the new one.")
            response = input("   Continue and create a duplicate? (y/N): ").strip().lower()
            if response != "y":
                sys.exit(0)

    # Create the workflow
    time.sleep(RATE_LIMIT_WAIT)
    workflow_id = importer.create_workflow(workflow_def, args.target_url)

    if workflow_id:
        print("\n" + "=" * 60)
        print(f"✅ WORKFLOW CREATED SUCCESSFULLY")
        print(f"   Name: {workflow_def['name']}")
        print(f"   ID:   {workflow_id}")
        print(f"   Activities: {len(workflow_def.get('activities', []))}")
        print(f"\n   Next steps:")
        print(f"   1. Go to dashboard.meraki.com → Organization → Automation → Workflows")
        print(f"   2. You should see '{workflow_def['name']}'")
        print(f"   3. Update the target URL from placeholder to your real ngrok URL")
        print(f"   4. Click 'Run' when your relay server is ready")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ WORKFLOW CREATION FAILED")
        print("   See error messages above for details.")
        print("   Fallback: Use the manual GUI guide that was saved.")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
