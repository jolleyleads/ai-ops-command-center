from typing import Dict, Any
from .services import run as run_service


def execute_pipeline(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute data through the AI Ops Command Center pipeline.
    """

    if not isinstance(input_data, dict):
        raise TypeError("input_data must be a dictionary")

    result = run_service(input_data)

    return {
        "success": True,
        "status": "completed",
        "input": input_data,
        "result": result,
    }


def run(input_data: Dict[str, Any]) -> Dict[str, Any]:
    return execute_pipeline(input_data)