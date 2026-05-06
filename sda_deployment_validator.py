#!/usr/bin/env python3
"""Post-Deployment Validation Script"""

import requests, json, sys, logging
from datetime import datetime
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
requests.packages.urllib3.disable_warnings()

class SDAValidator:
    def __init__(self, c9500_ip, c9500_user, c9500_pass,
                       c9300_ip, c9300_user, c9300_pass):
        self.c9500_ip, self.c9500_user, self.c9500_pass = c9500_ip, c9500_user, c9500_pass
        self.c9300_ip, self.c9300_user, self.c9300_pass = c9300_ip, c9300_user, c9300_pass
        self.results = {"passed": 0, "failed": 0, "errors": []}

    def _get(self, ip, user, pw, xpath):
        url = f"https://{ip}:443/restconf/data{xpath}"
        try:
            r = requests.get(url, auth=(user, pw), verify=False,
                             headers={"Accept":"application/yang-data+json"}, timeout=10)
            return r.status_code, r.json() if r.text else {}
        except Exception as e:
            return 500, str(e)

    def check(self, name, passed, error=None):
        if passed:
            logger.info(f"  ✅ {name}: PASSED")
            self.results["passed"] += 1
        else:
            logger.error(f"  ❌ {name}: FAILED — {error}")
            self.results["failed"] += 1
            if error: self.results["errors"].append(f"{name}: {error}")

    def run(self):
        logger.info("="*60)
        logger.info("SDA LISP+VXLAN Deployment Validation")
        logger.info(f"Started: {datetime.now().isoformat()}")
        logger.info("="*60)

        # Test 1: RESTCONF Connectivity
        for name, ip, u, p in [("C9500",self.c9500_ip,self.c9500_user,self.c9500_pass),
                                ("C9300",self.c9300_ip,self.c9300_user,self.c9300_pass)]:
            try:
                r = requests.get(f"https://{ip}:443/restconf/api/status",
                                 auth=(u,p), verify=False, timeout=10)
                self.check(f"RESTCONF Connectivity — {name}", r.status_code==200)
            except Exception as e:
                self.check(f"RESTCONF Connectivity — {name}", False, str(e))

        # Test 2: LISP on C9500
        s, d = self._get(self.c9500_ip, self.c9500_user, self.c9500_pass,
                         "/Cisco-IOS-XE-lisp:lisp")
        self.check("LISP on C9500", s==200 and "Cisco-IOS-XE-lisp:lisp" in d,
                   "LISP not configured" if s!=200 else None)

        # Test 3: VXLAN on C9500 + C9300
        for name, ip, u, p in [("C9500",self.c9500_ip,self.c9500_user,self.c9500_pass),
                                ("C9300",self.c9300_ip,self.c9300_user,self.c9300_pass)]:
            s, d = self._get(ip, u, p, "/Cisco-IOS-XE-nve:nve")
            self.check(f"VXLAN NVE — {name}", s==200 and "Cisco-IOS-XE-nve:nve" in d,
                       "VXLAN not configured" if s!=200 else None)

        # Test 4: VNI Mapping
        s, d = self._get(self.c9500_ip, self.c9500_user, self.c9500_pass,
                         "/Cisco-IOS-XE-nve:nve")
        if s == 200:
            nve = d.get("Cisco-IOS-XE-nve:nve", [{}])[0]
            vni_ok = any(v.get("vni")==100 and v.get("vlan")==100
                         for v in nve.get("vni_list", []))
            self.check("VNI 100 → VLAN 100 Mapping", vni_ok, "VNI mapping missing")

        logger.info("="*60)
        logger.info(f"RESULT: {self.results['passed']} passed, "
                    f"{self.results['failed']} failed")
        if self.results["errors"]:
            logger.error("\nErrors:")
            for e in self.results["errors"]: logger.error(f"  • {e}")
        logger.info("="*60)
        return self.results

if __name__ == "__main__":
    v = SDAValidator("<C9500_IP>","admin","<PASSWORD>",
                     "<C9300_IP>","admin","<PASSWORD>")
    r = v.run()
    sys.exit(0 if r["failed"] == 0 else 1)