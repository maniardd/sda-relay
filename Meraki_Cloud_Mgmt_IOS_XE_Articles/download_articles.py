"""
Meraki Cloud Management with IOS XE - Article Downloader
Downloads all English articles from the documentation folder.
"""

import urllib.request
import os
import re
import ssl
import time

# Disable SSL verification for corporate environments
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

ARTICLES = {
    # ============ Product Information / Overviews and Datasheets ============
    "01_Catalyst_9200L-M_Datasheet": "https://documentation.meraki.com/@api/deki/pages/11519/pdf/Catalyst%2b9200L-M%2bDatasheet.pdf?stylesheet=default",
    "02_Catalyst_9300-M_Datasheet": "https://documentation.meraki.com/@api/deki/pages/6350/pdf/Catalyst%2b9300-M%2bDatasheet.pdf?stylesheet=default",
    "03_Catalyst_9300L-M_Datasheet": "https://documentation.meraki.com/@api/deki/pages/9602/pdf/Catalyst%2b9300L-M%2bDatasheet.pdf?stylesheet=default",
    "04_Catalyst_9300X-M_Datasheet": "https://documentation.meraki.com/@api/deki/pages/9570/pdf/Catalyst%2b9300X-M%2bDatasheet.pdf?stylesheet=default",
    "05_Cloud_Configuration_Release_Versions_and_Highlights": "https://documentation.meraki.com/@api/deki/pages/11886/pdf/Cloud%2bConfiguration%253A%2bRelease%2bVersions%2band%2bHighlights.pdf?stylesheet=default",
    "06_Cloud_Managed_Catalyst_Switches_FAQs": "https://documentation.meraki.com/@api/deki/pages/10597/pdf/Cloud%2bManaged%2bCatalyst%2bSwitches%2bFAQs.pdf?stylesheet=default",
    "07_Cloud_Management_with_IOS_XE_Overview": "https://documentation.meraki.com/@api/deki/pages/10595/pdf/Cloud%2bManagement%2bwith%2bIOS%2bXE%2bOverview.pdf?stylesheet=default",
    "08_MS390_802.3bt_Support": "https://documentation.meraki.com/@api/deki/pages/6369/pdf/MS390%2b802.3bt%2bSupport.pdf?stylesheet=default",
    "09_Terms_and_Conditions_for_Cloud_Management_with_Device_Configuration": "https://documentation.meraki.com/@api/deki/pages/11065/pdf/Terms%2band%2bConditions%2bfor%2bCloud%2bManagement%2bwith%2bDevice%2bConfiguration.pdf?stylesheet=default",
    
    # ============ Product Information / Compatibility and Firmware ============
    "10_Independent_Firmware_Releases_for_Meraki_and_Catalyst-based_switches": "https://documentation.meraki.com/@api/deki/pages/8520/pdf/Independent%2bFirmware%2bReleases%2bfor%2bMeraki%2band%2bCatalyst-based%2bswitches.pdf?stylesheet=default",
    
    # ============ Design and Configure ============
    "11_BGP_Routing_for_Cloud_Management_with_IOS_XE": "https://documentation.meraki.com/@api/deki/pages/11882/pdf/BGP%2bRouting%2bfor%2bCloud%2bManagement%2bwith%2bIOS%2bXE.pdf?stylesheet=default",
    "12_Client-Tracking_in_IOS-XE": "https://documentation.meraki.com/@api/deki/pages/14210/pdf/Client-Tracking%2bin%2bIOS-XE.pdf?stylesheet=default",
    "13_Cloud_Managed_EVPN_Fabric_Technical_Guide": "https://documentation.meraki.com/@api/deki/pages/14624/pdf/Cloud%2bManaged%2bEVPN%2bFabric%2bTechnical%2bGuide.pdf?stylesheet=default",
    "14_Cloud-Managed_Catalyst_Switches_Device_Configuration_Source_FAQs": "https://documentation.meraki.com/@api/deki/pages/11021/pdf/Cloud-Managed%2bCatalyst%2bSwitches%253A%2bDevice%2bConfiguration%2bSource%2bFAQs.pdf?stylesheet=default",
    "15_Cloud-Managed_EVPN_Fabric_Installation_Lab_Guide": "https://documentation.meraki.com/Switching/Cloud_Management_with_IOS_XE/Design_and_Configure/Cloud-Managed_EVPN_Fabric_Installation_%2F%2F_Lab_Guide",
    "16_Cloud-Managed_EVPN_Fabric_Overview": "https://documentation.meraki.com/@api/deki/pages/14521/pdf/Cloud-Managed%2bEVPN%2bFabric%2bOverview.pdf?stylesheet=default",
    "17_FAQs_Migrate_to_Meraki_management_mode": "https://documentation.meraki.com/@api/deki/pages/8602/pdf/FAQs%253A%2bMigrate%2bto%2bMeraki%2bmanagement%2bmode.pdf?stylesheet=default",
    
    # ============ Install and Get Started ============
    "18_Catalyst_9200L-M_Series_Installation_Guide": "https://documentation.meraki.com/Switching/Cloud_Management_with_IOS_XE/Install_and_Get_Started/Catalyst_9200L-M_Series_Installation_Guide",
    "19_Catalyst_9300_X_L-M_Series_Installation_Guide": "https://documentation.meraki.com/Switching/Cloud_Management_with_IOS_XE/Install_and_Get_Started/Catalyst_9300%2F%2FX%2F%2FL-M_Series_Installation_Guide",
    "20_Conversion_from_CLI-managed_to_Cloud_Management_with_Cloud_Configuration": "https://documentation.meraki.com/Switching/Cloud_Management_with_IOS_XE/Install_and_Get_Started/Conversion_from_CLI-managed_IOS_XE_Catalyst_Switches_to_Cloud_Management_with_Cloud_Configuration",
    "21_Enable_Cloud_Management_for_Cisco_Switches_with_Device_Configuration": "https://documentation.meraki.com/Switching/Cloud_Management_with_IOS_XE/Install_and_Get_Started/Enable_Cloud_Management_for_Cisco_Switches_with_Device_Configuration",
    "22_Getting_started_Cisco_Catalyst_9300_Management_with_Meraki_Dashboard": "https://documentation.meraki.com/Switching/Cloud_Management_with_IOS_XE/Install_and_Get_Started/Getting_started%3A_Cisco_Catalyst_9300_Management_with_Meraki_Dashboard",
    "23_Migrating_Switches_From_CS_Firmware_to_IOS_XE_Firmware": "https://documentation.meraki.com/Switching/Cloud_Management_with_IOS_XE/Install_and_Get_Started/Migrating_Switches_From_CS_Firmware_to_IOS_XE_Firmware",
    "24_Onboarding_Cloud-Managed_Catalyst_switches_to_the_Meraki_Dashboard": "https://documentation.meraki.com/Switching/Cloud_Management_with_IOS_XE/Install_and_Get_Started/Onboarding_Cloud-Managed_Catalyst_switches_to_the_Meraki_Dashboard",
    "25_Operating_mode_claim_to_network_API_endpoint": "https://documentation.meraki.com/Switching/Cloud_Management_with_IOS_XE/Install_and_Get_Started/Operating_mode_claim_to_network_API_endpoint",
    "26_Upgrading_Cloud-Monitored_Switches_to_Cloud_Management_with_Device_Configuration": "https://documentation.meraki.com/Switching/Cloud_Management_with_IOS_XE/Install_and_Get_Started/Upgrading_Cloud-Monitored_Switches_to_Cloud_Management_with_Device_Configuration",
    
    # ============ Operate and Maintain ============
    "27_Automated_Logins_and_Users_on_Cloud-Managed_Switches": "https://documentation.meraki.com/Switching/Cloud_Management_with_IOS_XE/Operate_and_Maintain/Automated_Logins_and_Users_on_Cloud-Managed_Switches_Running_Cloud_Management_with_IOS_XE",
    "28_Cloud_CLI_for_Cloud-Managed_IOS_XE_Switches": "https://documentation.meraki.com/Switching/Cloud_Management_with_IOS_XE/Operate_and_Maintain/Cloud_CLI_for_Cloud-Managed_IOS_XE_Switches",
    "29_Offboarding_Process_for_Catalyst_Cloud_Management_Devices_in_Monitor-Only_Mode": "https://documentation.meraki.com/Switching/Cloud_Management_with_IOS_XE/Operate_and_Maintain/Catalyst_Cloud_Management_Device_Offboarding_Process_for_Monitor-Only_Deployments_(India%2C_Canada%2C_and_China_Regions)",
    "30_Upgrade_Steps_for_Cloud-Managed_Catalyst_Switches_with_Cloud_Configuration": "https://documentation.meraki.com/Switching/Cloud_Management_with_IOS_XE/Operate_and_Maintain/Upgrade_Steps_for_Cloud-Managed_Catalyst_Switches_with_Cloud_Configuration",
    
    # ============ Troubleshooting and Support ============
    "31_Cloud_Management_with_Device_Configuration_Required_Modifications": "https://documentation.meraki.com/Switching/Cloud_Management_with_IOS_XE/Troubleshooting_and_Support/Cloud_Management_with_Device_Configuration_Required_Modifications",
}

def download_article(name, url):
    """Download a single article (PDF if available, otherwise HTML)."""
    is_pdf = "/pdf/" in url
    ext = ".pdf" if is_pdf else ".html"
    filepath = os.path.join(OUTPUT_DIR, name + ext)
    
    if os.path.exists(filepath):
        print(f"  [SKIP] {name}{ext} already exists")
        return True
    
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response = urllib.request.urlopen(req, context=ctx, timeout=60)
        data = response.read()
        
        with open(filepath, 'wb') as f:
            f.write(data)
        
        size_kb = len(data) / 1024
        print(f"  [OK]   {name}{ext} ({size_kb:.1f} KB)")
        return True
    except Exception as e:
        print(f"  [FAIL] {name}{ext}: {e}")
        return False

def main():
    print(f"Meraki Cloud Management with IOS XE - Article Downloader")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Total articles: {len(ARTICLES)}")
    print("=" * 70)
    
    success = 0
    failed = 0
    
    for name, url in ARTICLES.items():
        print(f"\nDownloading: {name}")
        if download_article(name, url):
            success += 1
        else:
            failed += 1
        time.sleep(1)  # Be respectful to the server
    
    print("\n" + "=" * 70)
    print(f"Done! Success: {success}, Failed: {failed}")

if __name__ == "__main__":
    main()
