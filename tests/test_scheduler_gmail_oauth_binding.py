import ast
from pathlib import Path


def test_scheduler_binds_persisted_oauth_resolver():
    source = Path("outreach_scheduler.py").read_text()
    tree = ast.parse(source)

    assignments = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Attribute):
            target = node.targets[0]
            if isinstance(target.value, ast.Name) and target.attr == "gmail_access_token":
                if isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name):
                    assignments[target.value.id] = (node.value.value.id, node.value.attr)

    assert assignments.get("gmail_outreach_state") == ("gmail_connect", "gmail_access_token")
    assert assignments.get("outreach_automation") == ("gmail_connect", "gmail_access_token")
