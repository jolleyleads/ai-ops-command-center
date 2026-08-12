from typing import Dict, Any
from .openai_service import run as run_service


def execute_pipeline(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute data through the AI Ops Command Center pipeline.
    """

    if not isinstance(input_data, dict):
        raise TypeError("input_data must be a dictionary")

    result = run_service(input_data)

    return {
        "success": result.get("status") == "success",
        "status": "completed" if result.get("status") == "success" else "error",
        "input": input_data,
        "result": result,
    }


def run(input_data: Dict[str, Any]) -> Dict[str, Any]:
    return execute_pipeline(input_data)