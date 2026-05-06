"""
Generate 5 incremental test workflow JSONs, each building from the working minimal.
Uses the EXACT format that Meraki accepted for the minimal import.
Each file has a unique workflow ID to avoid collisions.
"""
import json
import copy
import random
import string

def rand_id(prefix, length=30):
    chars = string.ascii_letters + string.digits
    suffix = ''.join(random.choices(chars, k=length))
    return f"{prefix}{suffix}"

# Base template from the working minimal export
BASE_WF_ID = "definition_workflow_"
BASE_VAR_ID = "variable_workflow_"
BASE_ACT_ID = "definition_activity_"
BASE_CAT_ID = "category_"

def make_base(test_num, title):
    wf_id = rand_id(BASE_WF_ID)
    cat_id = rand_id(BASE_CAT_ID)
    var_test = rand_id(BASE_VAR_ID)
    
    return {
        "wf_id": wf_id,
        "cat_id": cat_id,
        "var_test": var_test,
        "workflow": {
            "unique_name": wf_id,
            "name": title,
            "title": title,
            "type": "generic.workflow",
            "base_type": "workflow",
            "variables": [
                {
                    "schema_id": "datatype.string",
                    "properties": {
                        "value": "hello",
                        "scope": "input",
                        "name": "Test Variable",
                        "type": "datatype.string",
                        "description": "A test variable",
                        "is_required": False,
                        "display_on_wizard": False,
                        "is_invisible": False,
                        "variable_string_format": ""
                    },
                    "unique_name": var_test,
                    "object_type": "variable_workflow"
                }
            ],
            "properties": {
                "atomic": {"is_atomic": False},
                "delete_workflow_instance": False,
                "description": f"Incremental test {test_num}: {title}",
                "display_name": title,
                "runtime_user": {
                    "override_target_runtime_user": False,
                    "specify_on_workflow_start": False,
                    "target_default": True
                },
                "target": {"no_target": True}
            },
            "object_type": "definition_workflow",
            "actions": [],
            "categories": [cat_id]
        },
        "categories": {
            cat_id: {
                "unique_name": cat_id,
                "name": "SDA Test",
                "title": "SDA Test",
                "type": "basic.category",
                "base_type": "category",
                "description": "Incremental import test",
                "category_type": "custom",
                "object_type": "category"
            }
        }
    }

def python_activity(act_id, title, script_args, script_body, queries, timeout=60, continue_on_failure=False):
    return {
        "unique_name": act_id,
        "name": "Execute Python Script",
        "title": title,
        "type": "python3.script",
        "base_type": "activity",
        "properties": {
            "action_timeout": timeout,
            "continue_on_failure": continue_on_failure,
            "description": title,
            "display_name": title,
            "script_arguments": script_args,
            "script_body": script_body,
            "script_queries": queries,
            "skip_execution": False
        },
        "object_type": "definition_activity"
    }

def set_variables_activity(act_id, title, vars_to_update):
    return {
        "unique_name": act_id,
        "name": "Set Variables",
        "title": title,
        "type": "core.set_multiple_variables",
        "base_type": "activity",
        "properties": {
            "continue_on_failure": False,
            "description": title,
            "display_name": title,
            "skip_execution": False,
            "variables_to_update": vars_to_update
        },
        "object_type": "definition_activity"
    }

# ─── TEST 1: Minimal + Condition Block ───
def generate_test1():
    b = make_base(1, "Test 1 - Condition Block")
    wf_id = b["wf_id"]
    var_test = b["var_test"]
    
    py_id = rand_id(BASE_ACT_ID)
    cb_id = rand_id(BASE_ACT_ID)
    br_pass_id = rand_id(BASE_ACT_ID)
    br_fail_id = rand_id(BASE_ACT_ID)
    
    py_act = python_activity(
        py_id, "Hello World Test",
        [f"$workflow.{wf_id}.input.{var_test}$"],
        "import sys\nval = sys.argv[1] if len(sys.argv) > 1 else 'none'\nsucceeded = True\nresult = f'Got: {val}'\nprint(result)",
        [
            {"script_query_name": "succeeded", "script_query_type": "boolean"},
            {"script_query_name": "result", "script_query_type": "string"}
        ]
    )
    
    condition_block = {
        "unique_name": cb_id,
        "name": "Condition Block",
        "title": "Check Result",
        "type": "logic.if_else",
        "base_type": "activity",
        "properties": {
            "conditions": [],
            "continue_on_failure": False,
            "description": "Check if script succeeded",
            "display_name": "Check Result",
            "skip_execution": False
        },
        "object_type": "definition_activity",
        "blocks": [
            {
                "unique_name": br_pass_id,
                "name": "Condition Branch",
                "title": "Passed",
                "type": "logic.condition_block",
                "base_type": "activity",
                "properties": {
                    "condition": {
                        "left_operand": f"$activity.{py_id}.output.script_queries.succeeded$",
                        "operator": "ne",
                        "right_operand": ""
                    },
                    "continue_on_failure": False,
                    "description": "Script passed",
                    "display_name": "Passed",
                    "skip_execution": False
                },
                "object_type": "definition_activity",
                "actions": []
            },
            {
                "unique_name": br_fail_id,
                "name": "Condition Branch",
                "title": "Failed",
                "type": "logic.condition_block",
                "base_type": "activity",
                "properties": {
                    "condition": {
                        "left_operand": f"$activity.{py_id}.output.script_queries.succeeded$",
                        "operator": "eq",
                        "right_operand": ""
                    },
                    "continue_on_failure": False,
                    "description": "Script failed",
                    "display_name": "Failed",
                    "skip_execution": False
                },
                "object_type": "definition_activity",
                "actions": []
            }
        ]
    }
    
    b["workflow"]["actions"] = [py_act, condition_block]
    return {"workflow": b["workflow"], "categories": b["categories"]}


# ─── TEST 2: Minimal + Group wrapping Python activity ───
def generate_test2():
    b = make_base(2, "Test 2 - Group Activity")
    wf_id = b["wf_id"]
    var_test = b["var_test"]
    
    py_id = rand_id(BASE_ACT_ID)
    grp_id = rand_id(BASE_ACT_ID)
    
    py_act = python_activity(
        py_id, "Nested Script",
        [f"$workflow.{wf_id}.input.{var_test}$"],
        "import sys\nval = sys.argv[1] if len(sys.argv) > 1 else 'none'\nresult = f'Inside group: {val}'\nprint(result)",
        [{"script_query_name": "result", "script_query_type": "string"}]
    )
    
    group = {
        "unique_name": grp_id,
        "name": "Group",
        "title": "Test Group",
        "type": "logic.group",
        "base_type": "activity",
        "properties": {
            "continue_on_failure": False,
            "description": "Group containing a Python activity",
            "display_name": "Test Group",
            "skip_execution": False
        },
        "object_type": "definition_activity",
        "actions": [py_act]
    }
    
    b["workflow"]["actions"] = [group]
    return {"workflow": b["workflow"], "categories": b["categories"]}


# ─── TEST 3: Minimal + Set Variables + local variable ───
def generate_test3():
    b = make_base(3, "Test 3 - Set Variables")
    wf_id = b["wf_id"]
    var_test = b["var_test"]
    
    var_local = rand_id(BASE_VAR_ID)
    py_id = rand_id(BASE_ACT_ID)
    sv_id = rand_id(BASE_ACT_ID)
    
    # Add a local boolean variable
    b["workflow"]["variables"].append({
        "schema_id": "datatype.boolean",
        "properties": {
            "value": False,
            "scope": "local",
            "name": "Test Flag",
            "type": "datatype.boolean",
            "description": "A test local flag",
            "is_required": False,
            "display_on_wizard": False,
            "is_invisible": False
        },
        "unique_name": var_local,
        "object_type": "variable_workflow"
    })
    
    py_act = python_activity(
        py_id, "Hello Test",
        [f"$workflow.{wf_id}.input.{var_test}$"],
        "import sys\nresult = 'done'\nprint(result)",
        [{"script_query_name": "result", "script_query_type": "string"}]
    )
    
    sv_act = set_variables_activity(sv_id, "Set Test Flag", [
        {
            "variable_to_update": f"$workflow.{wf_id}.local.{var_local}$",
            "variable_value_new": "true"
        }
    ])
    
    b["workflow"]["actions"] = [py_act, sv_act]
    return {"workflow": b["workflow"], "categories": b["categories"]}


# ─── TEST 4: Minimal + Condition Block + Group + Set Variables (combined) ───
def generate_test4():
    b = make_base(4, "Test 4 - Combined Features")
    wf_id = b["wf_id"]
    var_test = b["var_test"]
    
    var_failed = rand_id(BASE_VAR_ID)
    var_phase = rand_id(BASE_VAR_ID)
    py_precheck = rand_id(BASE_ACT_ID)
    cb_id = rand_id(BASE_ACT_ID)
    br_pass_id = rand_id(BASE_ACT_ID)
    br_fail_id = rand_id(BASE_ACT_ID)
    sv_fail_id = rand_id(BASE_ACT_ID)
    grp_id = rand_id(BASE_ACT_ID)
    py_deploy = rand_id(BASE_ACT_ID)
    
    # Add local variables
    b["workflow"]["variables"].extend([
        {
            "schema_id": "datatype.boolean",
            "properties": {
                "value": False,
                "scope": "local",
                "name": "Deployment Failed",
                "type": "datatype.boolean",
                "description": "Tracks failure",
                "is_required": False,
                "display_on_wizard": False,
                "is_invisible": False
            },
            "unique_name": var_failed,
            "object_type": "variable_workflow"
        },
        {
            "schema_id": "datatype.string",
            "properties": {
                "value": "",
                "scope": "local",
                "name": "Failed Phase",
                "type": "datatype.string",
                "description": "Which phase failed",
                "is_required": False,
                "display_on_wizard": False,
                "is_invisible": False,
                "variable_string_format": ""
            },
            "unique_name": var_phase,
            "object_type": "variable_workflow"
        }
    ])
    
    # Pre-Check Python
    precheck = python_activity(
        py_precheck, "Pre-Check",
        [f"$workflow.{wf_id}.input.{var_test}$"],
        "import sys\nsucceeded = True\nstatus = 'pass'\nresult_json = '{\"status\": \"pass\"}'\nprint(result_json)",
        [
            {"script_query_name": "succeeded", "script_query_type": "boolean"},
            {"script_query_name": "status", "script_query_type": "string"},
            {"script_query_name": "result_json", "script_query_type": "string"}
        ],
        timeout=120,
        continue_on_failure=True
    )
    
    # Condition Block
    condition_block = {
        "unique_name": cb_id,
        "name": "Condition Block",
        "title": "Pre-Check Pass/Fail",
        "type": "logic.if_else",
        "base_type": "activity",
        "properties": {
            "conditions": [],
            "continue_on_failure": False,
            "description": "Route on pre-check result",
            "display_name": "Pre-Check Pass/Fail",
            "skip_execution": False
        },
        "object_type": "definition_activity",
        "blocks": [
            {
                "unique_name": br_pass_id,
                "name": "Condition Branch",
                "title": "Pre-Check Passed",
                "type": "logic.condition_block",
                "base_type": "activity",
                "properties": {
                    "condition": {
                        "left_operand": f"$activity.{py_precheck}.output.script_queries.succeeded$",
                        "operator": "ne",
                        "right_operand": ""
                    },
                    "continue_on_failure": False,
                    "description": "Passed",
                    "display_name": "Pre-Check Passed",
                    "skip_execution": False
                },
                "object_type": "definition_activity",
                "actions": []
            },
            {
                "unique_name": br_fail_id,
                "name": "Condition Branch",
                "title": "Pre-Check Failed",
                "type": "logic.condition_block",
                "base_type": "activity",
                "properties": {
                    "condition": {
                        "left_operand": f"$activity.{py_precheck}.output.script_queries.succeeded$",
                        "operator": "eq",
                        "right_operand": ""
                    },
                    "continue_on_failure": False,
                    "description": "Failed",
                    "display_name": "Pre-Check Failed",
                    "skip_execution": False
                },
                "object_type": "definition_activity",
                "actions": [
                    set_variables_activity(sv_fail_id, "Set Pre-Check Failed", [
                        {
                            "variable_to_update": f"$workflow.{wf_id}.local.{var_failed}$",
                            "variable_value_new": "true"
                        },
                        {
                            "variable_to_update": f"$workflow.{wf_id}.local.{var_phase}$",
                            "variable_value_new": "Pre-Check"
                        }
                    ])
                ]
            }
        ]
    }
    
    # Deploy Group
    deploy_py = python_activity(
        py_deploy, "Deploy Phase 1",
        [f"$workflow.{wf_id}.input.{var_test}$"],
        "import sys\nresult = 'deployed'\nprint(result)",
        [{"script_query_name": "result", "script_query_type": "string"}]
    )
    
    group = {
        "unique_name": grp_id,
        "name": "Group",
        "title": "Phase 1 - Deploy",
        "type": "logic.group",
        "base_type": "activity",
        "properties": {
            "continue_on_failure": False,
            "description": "Deploy phase 1",
            "display_name": "Phase 1 - Deploy",
            "skip_execution": False
        },
        "object_type": "definition_activity",
        "actions": [deploy_py]
    }
    
    b["workflow"]["actions"] = [precheck, condition_block, group]
    return {"workflow": b["workflow"], "categories": b["categories"]}


# ─── TEST 5: Real Pre-Check + Phase 1 full structure (nested condition inside group) ───
def generate_test5():
    b = make_base(5, "Test 5 - Nested Structure")
    wf_id = b["wf_id"]
    var_test = b["var_test"]
    
    var_failed = rand_id(BASE_VAR_ID)
    py_precheck = rand_id(BASE_ACT_ID)
    cb_precheck = rand_id(BASE_ACT_ID)
    br_precheck_pass = rand_id(BASE_ACT_ID)
    br_precheck_fail = rand_id(BASE_ACT_ID)
    sv_precheck_fail = rand_id(BASE_ACT_ID)
    cb_continue = rand_id(BASE_ACT_ID)
    br_continue = rand_id(BASE_ACT_ID)
    br_stop = rand_id(BASE_ACT_ID)
    grp_phase1 = rand_id(BASE_ACT_ID)
    py_deploy = rand_id(BASE_ACT_ID)
    cb_deploy = rand_id(BASE_ACT_ID)
    br_deploy_pass = rand_id(BASE_ACT_ID)
    br_deploy_fail = rand_id(BASE_ACT_ID)
    py_verify = rand_id(BASE_ACT_ID)
    sv_deploy_fail = rand_id(BASE_ACT_ID)
    
    b["workflow"]["variables"].append({
        "schema_id": "datatype.boolean",
        "properties": {
            "value": False,
            "scope": "local",
            "name": "Deployment Failed",
            "type": "datatype.boolean",
            "description": "Tracks failure",
            "is_required": False,
            "display_on_wizard": False,
            "is_invisible": False
        },
        "unique_name": var_failed,
        "object_type": "variable_workflow"
    })
    
    # Pre-Check
    precheck = python_activity(
        py_precheck, "Pre-Check",
        [f"$workflow.{wf_id}.input.{var_test}$"],
        "import sys\nsucceeded = True\nstatus = 'pass'\nresult_json = '{\"status\": \"pass\"}'\nprint(result_json)",
        [
            {"script_query_name": "succeeded", "script_query_type": "boolean"},
            {"script_query_name": "result_json", "script_query_type": "string"}
        ],
        timeout=120,
        continue_on_failure=True
    )
    
    # Pre-Check Condition
    precheck_cb = {
        "unique_name": cb_precheck,
        "name": "Condition Block",
        "title": "Pre-Check Pass/Fail",
        "type": "logic.if_else",
        "base_type": "activity",
        "properties": {
            "conditions": [],
            "continue_on_failure": False,
            "description": "Route on pre-check",
            "display_name": "Pre-Check Pass/Fail",
            "skip_execution": False
        },
        "object_type": "definition_activity",
        "blocks": [
            {
                "unique_name": br_precheck_pass,
                "name": "Condition Branch",
                "title": "Passed",
                "type": "logic.condition_block",
                "base_type": "activity",
                "properties": {
                    "condition": {
                        "left_operand": f"$activity.{py_precheck}.output.script_queries.succeeded$",
                        "operator": "ne",
                        "right_operand": ""
                    },
                    "continue_on_failure": False,
                    "display_name": "Passed",
                    "skip_execution": False
                },
                "object_type": "definition_activity",
                "actions": []
            },
            {
                "unique_name": br_precheck_fail,
                "name": "Condition Branch",
                "title": "Failed",
                "type": "logic.condition_block",
                "base_type": "activity",
                "properties": {
                    "condition": {
                        "left_operand": f"$activity.{py_precheck}.output.script_queries.succeeded$",
                        "operator": "eq",
                        "right_operand": ""
                    },
                    "continue_on_failure": False,
                    "display_name": "Failed",
                    "skip_execution": False
                },
                "object_type": "definition_activity",
                "actions": [
                    set_variables_activity(sv_precheck_fail, "Set Failed", [
                        {"variable_to_update": f"$workflow.{wf_id}.local.{var_failed}$", "variable_value_new": "true"}
                    ])
                ]
            }
        ]
    }
    
    # Continue to Phase 1? (nested condition block checking variable)
    continue_cb = {
        "unique_name": cb_continue,
        "name": "Condition Block",
        "title": "Continue to Phase 1?",
        "type": "logic.if_else",
        "base_type": "activity",
        "properties": {
            "conditions": [],
            "continue_on_failure": False,
            "display_name": "Continue to Phase 1?",
            "skip_execution": False
        },
        "object_type": "definition_activity",
        "blocks": [
            {
                "unique_name": br_continue,
                "name": "Condition Branch",
                "title": "Continue - Deploy",
                "type": "logic.condition_block",
                "base_type": "activity",
                "properties": {
                    "condition": {
                        "left_operand": f"$workflow.{wf_id}.local.{var_failed}$",
                        "operator": "eq",
                        "right_operand": "false"
                    },
                    "continue_on_failure": False,
                    "display_name": "Continue - Deploy",
                    "skip_execution": False
                },
                "object_type": "definition_activity",
                "actions": [
                    {
                        "unique_name": grp_phase1,
                        "name": "Group",
                        "title": "Phase 1 - Deploy & Verify",
                        "type": "logic.group",
                        "base_type": "activity",
                        "properties": {
                            "continue_on_failure": False,
                            "description": "Deploy and verify phase 1",
                            "display_name": "Phase 1 - Deploy & Verify",
                            "skip_execution": False
                        },
                        "object_type": "definition_activity",
                        "actions": [
                            python_activity(
                                py_deploy, "Deploy Phase 1",
                                [f"$workflow.{wf_id}.input.{var_test}$"],
                                "import sys\nsucceeded = True\nresult_json = '{\"status\": \"ok\"}'\nprint(result_json)",
                                [
                                    {"script_query_name": "succeeded", "script_query_type": "boolean"},
                                    {"script_query_name": "result_json", "script_query_type": "string"}
                                ],
                                timeout=180,
                                continue_on_failure=True
                            ),
                            {
                                "unique_name": cb_deploy,
                                "name": "Condition Block",
                                "title": "Phase 1 Deploy Success?",
                                "type": "logic.if_else",
                                "base_type": "activity",
                                "properties": {
                                    "conditions": [],
                                    "continue_on_failure": False,
                                    "display_name": "Phase 1 Deploy Success?",
                                    "skip_execution": False
                                },
                                "object_type": "definition_activity",
                                "blocks": [
                                    {
                                        "unique_name": br_deploy_pass,
                                        "name": "Condition Branch",
                                        "title": "Succeeded - Verify",
                                        "type": "logic.condition_block",
                                        "base_type": "activity",
                                        "properties": {
                                            "condition": {
                                                "left_operand": f"$activity.{py_deploy}.output.script_queries.succeeded$",
                                                "operator": "ne",
                                                "right_operand": ""
                                            },
                                            "continue_on_failure": False,
                                            "display_name": "Succeeded - Verify",
                                            "skip_execution": False
                                        },
                                        "object_type": "definition_activity",
                                        "actions": [
                                            python_activity(
                                                py_verify, "Verify Phase 1",
                                                [f"$workflow.{wf_id}.input.{var_test}$"],
                                                "import sys\nsucceeded = True\nresult_json = '{\"status\": \"pass\"}'\nprint(result_json)",
                                                [
                                                    {"script_query_name": "succeeded", "script_query_type": "boolean"},
                                                    {"script_query_name": "result_json", "script_query_type": "string"}
                                                ]
                                            )
                                        ]
                                    },
                                    {
                                        "unique_name": br_deploy_fail,
                                        "name": "Condition Branch",
                                        "title": "Failed",
                                        "type": "logic.condition_block",
                                        "base_type": "activity",
                                        "properties": {
                                            "condition": {
                                                "left_operand": f"$activity.{py_deploy}.output.script_queries.succeeded$",
                                                "operator": "eq",
                                                "right_operand": ""
                                            },
                                            "continue_on_failure": False,
                                            "display_name": "Failed",
                                            "skip_execution": False
                                        },
                                        "object_type": "definition_activity",
                                        "actions": [
                                            set_variables_activity(sv_deploy_fail, "Set Phase 1 Failed", [
                                                {"variable_to_update": f"$workflow.{wf_id}.local.{var_failed}$", "variable_value_new": "true"}
                                            ])
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "unique_name": br_stop,
                "name": "Condition Branch",
                "title": "Stop - Failed",
                "type": "logic.condition_block",
                "base_type": "activity",
                "properties": {
                    "condition": {
                        "left_operand": f"$workflow.{wf_id}.local.{var_failed}$",
                        "operator": "eq",
                        "right_operand": "true"
                    },
                    "continue_on_failure": False,
                    "display_name": "Stop - Failed",
                    "skip_execution": False
                },
                "object_type": "definition_activity",
                "actions": []
            }
        ]
    }
    
    b["workflow"]["actions"] = [precheck, precheck_cb, continue_cb]
    return {"workflow": b["workflow"], "categories": b["categories"]}


# ─── Generate all test files ───
tests = [
    (1, generate_test1),
    (2, generate_test2),
    (3, generate_test3),
    (4, generate_test4),
    (5, generate_test5),
]

for num, gen_func in tests:
    data = gen_func()
    filename = f"test_incremental_{num}.json"
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)
    
    # Count activities
    def count_acts(actions):
        c = 0
        for a in actions:
            c += 1
            for b in a.get("blocks", []):
                c += 1
                c += count_acts(b.get("actions", []))
            c += count_acts(a.get("actions", []))
        return c
    
    act_count = count_acts(data["workflow"]["actions"])
    var_count = len(data["workflow"]["variables"])
    wf_id = data["workflow"]["unique_name"]
    print(f"  {filename}: {var_count} vars, {act_count} activities, ID={wf_id}")

print("\n--- Test descriptions ---")
print("Test 1: Python + Condition Block with activity output refs")
print("Test 2: Group wrapping a Python activity")
print("Test 3: Python + Set Variables + local boolean variable")
print("Test 4: Pre-Check + Condition Block + Group + Set Variables (combined)")
print("Test 5: Full nested structure (Pre-Check → Condition → Continue CB → Group → Deploy → CB → Verify/Fail)")
print("\nImport in order. First failure reveals the breaking feature.")
