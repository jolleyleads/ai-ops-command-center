"""Core workflow engine for AI Ops Command Center."""

from typing import Any, Dict, List

from .pipeline import execute_pipeline


def get_field(data: Dict[str, Any], path: str) -> Any:
    """Read nested data using paths such as lead.status."""
    value: Any = data

    for part in str(path or "").split("."):
        if not part:
            continue
        if not isinstance(value, dict):
            return None
        value = value.get(part)

    return value


def run_workflow(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Run input through the command-center pipeline."""

    if not isinstance(input_data, dict):
        raise TypeError("input_data must be a dictionary")

    return execute_pipeline(input_data)


def run(input_data: Dict[str, Any]) -> Dict[str, Any]:
    return run_workflow(input_data)