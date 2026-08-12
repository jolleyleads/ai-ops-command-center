"""Workflow pipeline helpers for AI Ops Command Center."""

from typing import Any, Dict, List

from .services import run_ai


def evaluate_condition(
    value: Any,
    operator: str,
    expected: Any,
) -> bool:
    if operator == "equals":
        return str(value) == str(expected)

    if operator == "not_equals":
        return str(value) != str(expected)

    if operator == "contains":
        return str(expected).lower() in str(value or "").lower()

    if operator == "not_contains":
        return str(expected).lower() not in str(value or "").lower()

    if operator == "exists":
        return value not in (None, "")

    if operator == "gt":
        try:
            return float(value) > float(expected)
        except (TypeError, ValueError):
            return False

    if operator == "lt":
        try:
            return float(value) < float(expected)
        except (TypeError, ValueError):
            return False

    return False


def build_default_flow(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build the clean core flow:
    Trigger -> OpenAI -> IF/ELSE
    """

    trigger = next((n for n in nodes if n.get("type") == "trigger"), None)
    ai_node = next((n for n in nodes if n.get("type") == "ai"), None)
    condition = next((n for n in nodes if n.get("type") == "condition"), None)

    edges: List[Dict[str, Any]] = []

    if trigger and ai_node:
        edges.append(
            {
                "source": trigger["id"],
                "target": ai_node["id"],
            }
        )

    if ai_node and condition:
        edges.append(
            {
                "source": ai_node["id"],
                "target": condition["id"],
            }
        )

    return edges


def run_ai_node(
    node: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    config = node.get("config", {})

    prompt = config.get("prompt", "")
    instructions = config.get("instructions", "")
    model = config.get("model", "")
    output_key = config.get("output_key", "ai_output")

    result = run_ai(
        prompt=prompt,
        instructions=instructions,
        model=model,
    )

    if result.get("ok"):
        context[output_key] = result.get("output", "")

    return {
        "result": result,
        "context": context,
    }