"""Core workflow engine for AI Ops Command Center."""

from typing import Any, Dict, List

from .pipeline import evaluate_condition, run_ai_node


def get_field(data: Dict[str, Any], path: str) -> Any:
    """Read a nested value using a path like lead.status."""

    value: Any = data

    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)

    return value


def execute_node(
    node: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:

    node_type = node.get("type")
    config = node.get("config", {})

    if node_type == "trigger":
        return {
            "ok": True,
            "type": "trigger",
            "context": context,
        }

    if node_type == "ai":
        return run_ai_node(node, context)

    if node_type == "condition":
        field_path = config.get("field_path", "")
        operator = config.get("operator", "equals")
        compare_value = config.get("compare_value", "")

        actual_value = get_field(context, field_path)

        result = evaluate_condition(
            actual_value,
            operator,
            compare_value,
        )

        context["condition_result"] = result

        return {
            "ok": True,
            "type": "condition",
            "branch": "true" if result else "false",
            "context": context,
        }

    return {
        "ok": True,
        "type": node_type,
        "context": context,
    }


def run_workflow(
    nodes: List[Dict[str, Any]],
    input_data: Dict[str, Any],
) -> Dict[str, Any]:

    context = dict(input_data)
    results: List[Dict[str, Any]] = []

    for node in nodes:
        result = execute_node(node, context)
        results.append(result)

        if isinstance(result.get("context"), dict):
            context.update(result["context"])

    return {
        "status": "success",
        "results": results,
        "output": context,
    }