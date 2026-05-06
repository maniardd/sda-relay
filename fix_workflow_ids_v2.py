"""
Fix workflow IDs to use real Meraki-pattern prefixes.

The minimal test import worked because its IDs were derived from real
LTROPS-1424 example IDs (prefix 02T738V for workflow/variable/activity,
02SK2E2 for categories). The full workflow used completely random IDs which
may fail Meraki's validation.

This script replaces all unique_name IDs with ones using the proven prefixes.
"""
import json
import random
import string
import re
import sys

CHARS = string.ascii_letters + string.digits

# Proven working prefixes from LTROPS-1424 example + minimal test
WF_PREFIX = "02T738V"    # workflow, variable, activity IDs
CAT_PREFIX = "02SK2E2"   # category IDs
SUFFIX_LEN = 28          # 7 prefix + 28 suffix = 35 total

def gen_suffix():
    return ''.join(random.choice(CHARS) for _ in range(SUFFIX_LEN))

def main():
    infile = "sda_workflow_import.json"
    outfile = "sda_workflow_import_v2.json"
    
    with open(infile, 'r', encoding='utf-8') as f:
        content = f.read()
    
    data = json.loads(content)
    
    # Collect all unique IDs - only those with suffix starting with "02" (real Meraki pattern)
    # This avoids matching field names like "category_type", "object_type", etc.
    id_pattern = re.compile(
        r'(definition_workflow|variable_workflow|definition_activity|category)_(02[A-Za-z0-9]{20,})'
    )
    
    # Find all unique old IDs
    old_ids = set()
    for match in id_pattern.finditer(content):
        full_id = match.group(0)
        old_ids.add(full_id)
    
    print(f"Found {len(old_ids)} unique IDs to replace")
    
    # Create mapping: old_full_id -> new_full_id
    id_map = {}
    used_suffixes = set()
    
    for old_id in sorted(old_ids):
        type_prefix = old_id.rsplit('_', 1)[0]  # e.g. "definition_workflow"
        # Actually need to split correctly for multi-part prefixes
        if old_id.startswith("definition_workflow_"):
            type_prefix = "definition_workflow"
        elif old_id.startswith("variable_workflow_"):
            type_prefix = "variable_workflow"
        elif old_id.startswith("definition_activity_"):
            type_prefix = "definition_activity"
        elif old_id.startswith("category_"):
            type_prefix = "category"
        else:
            print(f"WARNING: Unknown ID type: {old_id}")
            continue
        
        # Pick prefix based on type
        if type_prefix == "category":
            meraki_prefix = CAT_PREFIX
        else:
            meraki_prefix = WF_PREFIX
        
        # Generate unique suffix
        while True:
            suffix = gen_suffix()
            new_suffix = meraki_prefix + suffix
            if new_suffix not in used_suffixes:
                used_suffixes.add(new_suffix)
                break
        
        new_id = f"{type_prefix}_{new_suffix}"
        id_map[old_id] = new_id
    
    # Replace all occurrences in content (handles both JSON keys and string references)
    new_content = content
    # Sort by length descending to avoid partial replacements
    for old_id in sorted(id_map.keys(), key=len, reverse=True):
        new_id = id_map[old_id]
        new_content = new_content.replace(old_id, new_id)
    
    # Validate JSON
    try:
        new_data = json.loads(new_content)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON after replacement: {e}")
        sys.exit(1)
    
    # Write with pretty formatting
    with open(outfile, 'w', encoding='utf-8') as f:
        json.dump(new_data, f, indent=2)
    
    print(f"\nReplaced {len(id_map)} unique IDs")
    print(f"Output: {outfile}")
    
    # Verify all IDs use correct prefixes
    new_content_str = json.dumps(new_data)
    
    wf_ids = re.findall(r'definition_workflow_(02[A-Za-z0-9]+)', new_content_str)
    var_ids = re.findall(r'variable_workflow_(02[A-Za-z0-9]+)', new_content_str)
    act_ids = re.findall(r'definition_activity_(02[A-Za-z0-9]+)', new_content_str)
    cat_ids = re.findall(r'category_(02[A-Za-z0-9]+)', new_content_str)
    
    print(f"\nVerification:")
    print(f"  Workflow IDs with T738V prefix: {sum(1 for x in set(wf_ids) if x.startswith('02T738V'))}/{len(set(wf_ids))}")
    print(f"  Variable IDs with T738V prefix: {sum(1 for x in set(var_ids) if x.startswith('02T738V'))}/{len(set(var_ids))}")
    print(f"  Activity IDs with T738V prefix: {sum(1 for x in set(act_ids) if x.startswith('02T738V'))}/{len(set(act_ids))}")
    print(f"  Category IDs with SK2E2 prefix: {sum(1 for x in set(cat_ids) if x.startswith('02SK2E2'))}/{len(set(cat_ids))}")
    
    # Show sample mappings
    print(f"\nSample mappings:")
    for old_id, new_id in list(id_map.items())[:5]:
        suffix = new_id.split('_', 2)[-1] if new_id.startswith("definition_") else new_id.split('_', 1)[-1]
        # Get just the alphanumeric part
        parts = new_id.split('_')
        alnum = parts[-1]
        print(f"  {old_id[:50]}... -> ...{alnum[:15]}... (len={len(alnum)})")

if __name__ == "__main__":
    main()
