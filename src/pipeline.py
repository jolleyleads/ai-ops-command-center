from typing import Dict, Any
from .orchestrator import orchestrate


def execute_pipeline(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a verified DOE workflow through the AI Ops Command Center."""
    if not isinstance(input_data, dict):
        raise TypeError("input_data must be a dictionary")

    result = orchestrate(input_data)
    status = result.get("status")
    return {
        "success": status in {"ready", "completed"},
        "status": status,
        "input": input_data,
        "result": result,
    }


def run(input_data: Dict[str, Any]) -> Dict[str, Any]:
    return execute_pipeline(input_data)
