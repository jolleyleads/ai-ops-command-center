import os
import json
from typing import Any, Dict

from openai import OpenAI


def run(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send workflow data to OpenAI and return the AI response.
    """

    if not isinstance(input_data, dict):
        raise TypeError("input_data must be a dictionary")

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return {
            "status": "error",
            "error": "OPENAI_API_KEY is not configured"
        }

    client = OpenAI(api_key=api_key)

    model = input_data.get("model") or os.getenv(
        "OPENAI_MODEL",
        "gpt-5.2"
    )

    instructions = input_data.get(
        "instructions",
        "You are an AI automation assistant."
    )

    prompt = input_data.get("prompt", "")

    workflow_data = input_data.get("data", {})

    full_prompt = f"""
{prompt}

WORKFLOW DATA:
{json.dumps(workflow_data, indent=2)}
"""

    try:
        response = client.responses.create(
            model=model,
            instructions=instructions,
            input=full_prompt,
        )

        return {
            "status": "success",
            "ai_output": response.output_text,
            "model": model,
        }

    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
        }