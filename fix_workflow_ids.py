"""
Fix sda_workflow_import.json unique_name values to match Meraki's expected format.
Meraki expects: prefix + 36-char alphanumeric string (base62, mixed case)
Example: definition_workflow_02T738VPYWL4J71YHy065XYsD9ushobr26T
"""
import json
import string
import random
import re
import sys

# Deterministic seed so IDs are reproducible
random.seed(42)

CHARSET = string.ascii_letters + string.digits  # a-zA-Z0-9

def generate_id(length=35):
    """Generate a Meraki-style alphanumeric ID (35 chars, starts with 02)."""
    # Real Meraki IDs are exactly 35 chars: "02" + 33 alphanumeric
    return "02" + ''.join(random.choice(CHARSET) for _ in range(length - 2))

# Read the original JSON as raw text (to do global string replacement)
with open("sda_workflow_import.json", "r", encoding="utf-8") as f:
    content = f.read()

# Find all unique_name values using regex
# Patterns: definition_workflow_SDA_*, variable_workflow_SDA_*, definition_activity_SDA_*, category_SDA_*
old_names = set(re.findall(r'(definition_workflow_SDA_[A-Z0-9_]+|variable_workflow_SDA_[A-Z0-9_]+|definition_activity_SDA_[A-Z0-9_]+|category_SDA_[A-Z0-9_]+)', content))

print(f"Found {len(old_names)} unique identifiers to replace:")

# Create mapping
mapping = {}
for old_name in sorted(old_names):
    if old_name.startswith("definition_workflow_"):
        new_name = "definition_workflow_" + generate_id()
    elif old_name.startswith("variable_workflow_"):
        new_name = "variable_workflow_" + generate_id()
    elif old_name.startswith("definition_activity_"):
        new_name = "definition_activity_" + generate_id()
    elif old_name.startswith("category_"):
        new_name = "category_" + generate_id()
    else:
        continue
    mapping[old_name] = new_name
    print(f"  {old_name}")
    print(f"    -> {new_name}")

# Sort by length descending to avoid partial replacements
for old_name in sorted(mapping.keys(), key=len, reverse=True):
    content = content.replace(old_name, mapping[old_name])

# Validate JSON
try:
    parsed = json.loads(content)
    print(f"\nJSON validation: PASSED")
except json.JSONDecodeError as e:
    print(f"\nJSON validation: FAILED - {e}")
    sys.exit(1)

# Pretty-print back
with open("sda_workflow_import.json", "w", encoding="utf-8") as f:
    json.dump(parsed, f, indent=2)

print(f"Updated sda_workflow_import.json with {len(mapping)} new Meraki-compatible IDs")

# Save mapping for reference
with open("workflow_id_mapping.txt", "w", encoding="utf-8") as f:
    f.write("Old Name -> New Name\n")
    f.write("=" * 120 + "\n")
    for old, new in sorted(mapping.items()):
        f.write(f"{old}\n  -> {new}\n\n")
print("Saved ID mapping to workflow_id_mapping.txt")
