"""
Fix the sda_workflow_import_v2.json by removing Set Variables actions
that reference undefined output variables (workflow_results, workflow_results_code).

These orphan references likely cause the "Bad request - invalid workflow_unique_name" error
because Meraki validates all variable references during import.
"""
import json
import re

with open('sda_workflow_import_v2.json', 'r') as f:
    data = json.load(f)

def remove_output_set_vars(actions):
    """Recursively remove Set Variables actions that reference output.workflow_results*"""
    cleaned = []
    for action in actions:
        # Check if this is a Set Variables referencing output vars
        if action.get('type') == 'core.set_multiple_variables':
            vars_to_update = action.get('properties', {}).get('variables_to_update', [])
            has_output_ref = any('output.workflow_results' in v.get('variable_to_update', '') 
                               for v in vars_to_update)
            if has_output_ref:
                print(f"  REMOVING: {action['properties'].get('display_name', action.get('title', 'unknown'))}")
                continue  # Skip this action
        
        # Recurse into nested structures
        if 'actions' in action:
            action['actions'] = remove_output_set_vars(action['actions'])
        if 'blocks' in action:
            for block in action['blocks']:
                if 'actions' in block:
                    block['actions'] = remove_output_set_vars(block['actions'])
        
        cleaned.append(action)
    return cleaned

print("Scanning for Set Variables actions with orphan output refs...")
data['workflow']['actions'] = remove_output_set_vars(data['workflow']['actions'])

# Also fix category_type from "custom" to "system" (per Meraki export)
for cat_key, cat_val in data.get('categories', {}).items():
    if cat_val.get('category_type') == 'custom':
        print(f"  FIXING: category_type 'custom' -> 'system' for {cat_val['name']}")
        cat_val['category_type'] = 'system'

# Verify no orphan output refs remain
content = json.dumps(data)
remaining = re.findall(r'output\.workflow_results', content)
print(f"\nOrphan output refs remaining: {len(remaining)}")

# Write fixed file
with open('sda_workflow_import_v2.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)

print("Fixed file written: sda_workflow_import_v2.json")

# Summary stats
def count_actions(actions):
    total = 0
    for a in actions:
        total += 1
        total += count_actions(a.get('actions', []))
        for b in a.get('blocks', []):
            total += 1
            total += count_actions(b.get('actions', []))
    return total

print(f"Total actions/blocks: {count_actions(data['workflow']['actions'])}")
print(f"Variables: {len(data['workflow']['variables'])}")
