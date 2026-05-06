"""
Nuclear option: Strip ALL unique_name fields from the workflow JSON.
Meraki should auto-generate them on import, just like it regenerated
activity IDs in the minimal test import.

We also need to convert all $variable/activity references to use
positional names or remove them, since the unique_names they reference
won't exist anymore.

Strategy:
1. Remove unique_name from workflow, variables, activities, categories
2. Replace $workflow.WFID.scope.VARID$ refs with variable NAME-based refs
3. Replace $activity.ACTID.output.* refs with activity TITLE-based refs
4. Fix category_type to "system"
"""
import json
import re
import copy

with open('sda_workflow_import.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# ---- Approach: Keep unique_names but make them SHORT and simple ----
# The minimal test had a 39-char suffix and it worked.
# Maybe the issue is ID COLLISION with a previously-failed import ghost.
# Use completely fresh, short IDs.

# Actually, let's try the SIMPLEST possible thing:
# Use the exact same workflow unique_name pattern as the minimal test
# that ACTUALLY WORKED.

import random
import string

def short_id(length=20):
    """Generate a short random ID"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

# Build ID mapping
wf_suffix = short_id(20)
WF_ID = f"definition_workflow_02{wf_suffix}"

var_map = {}  # old_unique_name -> new_unique_name
for v in data['workflow']['variables']:
    old = v['unique_name']
    new = f"variable_workflow_02{short_id(20)}"
    var_map[old] = new

act_map = {}  # old_unique_name -> new_unique_name
def map_activities(actions):
    for a in actions:
        old = a['unique_name']
        new = f"definition_activity_02{short_id(20)}"
        act_map[old] = new
        for b in a.get('blocks', []):
            old_b = b['unique_name']
            new_b = f"definition_activity_02{short_id(20)}"
            act_map[old_b] = new_b
            map_activities(b.get('actions', []))
        map_activities(a.get('actions', []))

map_activities(data['workflow']['actions'])

cat_map = {}
for k in data.get('categories', {}):
    new_cat = f"category_02{short_id(20)}"
    cat_map[k] = new_cat

# Now do string replacement on the entire JSON
old_wf_id = data['workflow']['unique_name']

content = json.dumps(data, indent=2)

# Replace workflow ID
content = content.replace(old_wf_id, WF_ID)

# Replace variable IDs
for old, new in var_map.items():
    content = content.replace(old, new)

# Replace activity IDs  
for old, new in sorted(act_map.items(), key=lambda x: len(x[0]), reverse=True):
    content = content.replace(old, new)

# Replace category IDs
for old, new in cat_map.items():
    content = content.replace(old, new)

# Parse back
new_data = json.loads(content)

# Fix: Remove orphan output variable references
def remove_output_set_vars(actions):
    cleaned = []
    for action in actions:
        if action.get('type') == 'core.set_multiple_variables':
            vars_to_update = action.get('properties', {}).get('variables_to_update', [])
            has_output_ref = any('output.workflow_results' in v.get('variable_to_update', '') 
                               for v in vars_to_update)
            if has_output_ref:
                print(f"  Removed: {action['properties'].get('display_name')}")
                continue
        if 'actions' in action:
            action['actions'] = remove_output_set_vars(action['actions'])
        if 'blocks' in action:
            for block in action['blocks']:
                if 'actions' in block:
                    block['actions'] = remove_output_set_vars(block['actions'])
        cleaned.append(action)
    return cleaned

print("Removing orphan output refs...")
new_data['workflow']['actions'] = remove_output_set_vars(new_data['workflow']['actions'])

# Fix: category_type -> system
for cat_key, cat_val in new_data.get('categories', {}).items():
    cat_val['category_type'] = 'system'

# Fix: Remove display_as_suggestion from Group (might not be valid)
def clean_properties(actions):
    for a in actions:
        props = a.get('properties', {})
        if 'display_as_suggestion' in props:
            del props['display_as_suggestion']
        for b in a.get('blocks', []):
            clean_properties([b])
            clean_properties(b.get('actions', []))
        clean_properties(a.get('actions', []))

clean_properties(new_data['workflow']['actions'])

# Write output
outfile = 'sda_workflow_import_v3.json'
with open(outfile, 'w', encoding='utf-8') as f:
    json.dump(new_data, f, indent=2)

# Verify
print(f"\nOutput: {outfile}")
print(f"Workflow ID: {new_data['workflow']['unique_name']}")
print(f"  Suffix length: {len(new_data['workflow']['unique_name'].replace('definition_workflow_', ''))}")

# Verify references
final_content = json.dumps(new_data)
wf_refs = set(re.findall(r'workflow\.(definition_workflow_[A-Za-z0-9]+)\.', final_content))
print(f"Workflow refs: {len(wf_refs)} unique -> {wf_refs}")

out_refs = re.findall(r'output\.workflow_results', final_content)
print(f"Orphan output refs: {len(out_refs)}")

# Check for any old IDs remaining
if old_wf_id in final_content:
    print("WARNING: Old workflow ID still present!")
for old in var_map:
    if old in final_content:
        print(f"WARNING: Old var ID still present: {old}")
for old in act_map:
    if old in final_content:
        print(f"WARNING: Old act ID still present: {old}")

print("\nDone!")
