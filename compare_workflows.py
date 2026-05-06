import json
import re

with open('sda_workflow_import.json', 'r') as f:
    content = f.read()
    
d = json.loads(content)

# Find all variable reference patterns
print("=== ALL VARIABLE REFERENCES ===")
refs = re.findall(r'workflow\.[^.]+\.(input|output|local)\.([^$]+)\$', content)
for scope, var in sorted(set(refs)):
    print("  %s.%s" % (scope, var))

# Check output references - these need defined output variables
print("\n=== OUTPUT REFS (need output variables) ===")
out_refs = re.findall(r'output\.([^$]+)\$', content)
for ref in sorted(set(out_refs)):
    print("  %s" % ref)

# Defined variables
print("\n=== DEFINED VARIABLES ===")
for v in d["workflow"]["variables"]:
    props = v["properties"]
    print("  %s: %s (%s)" % (props["scope"], props["name"], v["unique_name"]))

# Check: do output refs match any defined variable?
defined_var_names = set(v["unique_name"] for v in d["workflow"]["variables"])
print("\n=== ORPHAN OUTPUT REFS ===")
for ref in sorted(set(out_refs)):
    if ref not in defined_var_names and not ref.startswith("script_queries"):
        print("  ORPHAN: output.%s" % ref)
import sys; sys.exit(0)

print("=== WORKFLOW LEVEL ===")
for key in ['unique_name', 'name', 'title', 'type', 'base_type', 'object_type']:
    s = submitted['workflow'].get(key)
    e = exported['workflow'].get(key)
    match = 'SAME' if s == e else 'DIFF'
    print(f"  {key}: {match}")
    if match == 'DIFF':
        print(f"    submitted: {s}")
        print(f"    exported:  {e}")

print("\n=== VARIABLE ===")
sv = submitted['workflow']['variables'][0]
ev = exported['workflow']['variables'][0]
s_id = sv['unique_name']
e_id = ev['unique_name']
print(f"  unique_name match: {s_id == e_id}")
if s_id != e_id:
    print(f"    submitted: {s_id}")
    print(f"    exported:  {e_id}")
for key in set(list(sv['properties'].keys()) + list(ev['properties'].keys())):
    s = sv['properties'].get(key, '<MISSING>')
    e = ev['properties'].get(key, '<MISSING>')
    if s != e:
        print(f"  properties.{key}: submitted={s} | exported={e}")

print("\n=== ACTIVITY ===")
sa = submitted['workflow']['actions'][0]
ea = exported['workflow']['actions'][0]
s_aid = sa['unique_name']
e_aid = ea['unique_name']
print(f"  unique_name match: {s_aid == e_aid}")
if s_aid != e_aid:
    print(f"    submitted: {s_aid}")
    print(f"    exported:  {e_aid}")
for key in set(list(sa['properties'].keys()) + list(ea['properties'].keys())):
    s = sa['properties'].get(key, '<MISSING>')
    e = ea['properties'].get(key, '<MISSING>')
    if s != e:
        print(f"  properties.{key}:")
        print(f"    submitted: {s}")
        print(f"    exported:  {e}")

print("\n=== CATEGORY ===")
sc = list(submitted['categories'].values())[0]
ec = list(exported['categories'].values())[0]
for key in set(list(sc.keys()) + list(ec.keys())):
    s = sc.get(key, '<MISSING>')
    e = ec.get(key, '<MISSING>')
    if s != e:
        print(f"  {key}: submitted={s} | exported={e}")
    else:
        print(f"  {key}: SAME")
