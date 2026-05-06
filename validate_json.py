import json

with open('SDA_Fabric_Full_Deployment_Complete.json', 'r') as f:
    d = json.load(f)

acts = d['workflow']['actions']
print(f"Top-level actions: {len(acts)}")
print()
for i, a in enumerate(acts):
    print(f"  {i+1}. [{a['type']}] {a['title']}")

print()
vars_list = d['workflow']['variables']
print(f"Variables: {len(vars_list)}")
for v in vars_list:
    print(f"  - {v['properties']['name']} ({v['properties']['scope']}, {v['schema_id'].split('.')[1]})")

print()
print("Bug #1 check (Pre-Check Passed branch):")
precheck_cond = acts[1]
b1 = precheck_cond['blocks'][0]
print(f"  Operator: {b1['properties']['condition']['operator']}")
print(f"  Right operand: {b1['properties']['condition']['right_operand']}")

print()
print("Bug #2 check (Phase 1 Verify condition after verify script):")
p1_group = acts[2]['blocks'][0]['actions'][0]
p1_deploy_cond = p1_group['actions'][1]
p1_verify_branch = p1_deploy_cond['blocks'][0]
verify_actions = p1_verify_branch.get('actions', [])
print(f"  Actions inside 'Phase 1 Succeeded - Verify' branch: {len(verify_actions)}")
for a in verify_actions:
    print(f"    - {a['title']} ({a['type']})")
    if a['type'] == 'logic.if_else':
        for blk in a.get('blocks', []):
            print(f"      Branch: {blk['title']}")
            for sub in blk.get('actions', []):
                print(f"        -> {sub['title']}")

print()
print("Bug #2 check (Phase 2 Verify condition after verify script):")
p2_group = acts[3]['blocks'][0]['actions'][0]
p2_deploy_cond = p2_group['actions'][1]
p2_verify_branch = p2_deploy_cond['blocks'][0]
verify_actions2 = p2_verify_branch.get('actions', [])
print(f"  Actions inside 'Phase 2 Succeeded - Verify' branch: {len(verify_actions2)}")
for a in verify_actions2:
    print(f"    - {a['title']} ({a['type']})")
    if a['type'] == 'logic.if_else':
        for blk in a.get('blocks', []):
            print(f"      Branch: {blk['title']}")
            for sub in blk.get('actions', []):
                print(f"        -> {sub['title']}")

# Count all unique_names to check for duplicates
all_ids = []
def collect_ids(obj):
    if isinstance(obj, dict):
        if 'unique_name' in obj:
            all_ids.append(obj['unique_name'])
        for v in obj.values():
            collect_ids(v)
    elif isinstance(obj, list):
        for item in obj:
            collect_ids(item)

collect_ids(d)
print(f"\nTotal unique_names: {len(all_ids)}")
dupes = [x for x in all_ids if all_ids.count(x) > 1]
if dupes:
    print(f"DUPLICATES FOUND: {set(dupes)}")
else:
    print("No duplicate unique_names - GOOD")
