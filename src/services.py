"""Service layer for AI Ops Command Center."""

import os
from typing import Any, Dict

from openai import OpenAI


def run_ai(
    prompt: str,
    instructions: str = "",
    model: str = "",
) -> Dict[str, Any]:
    """Send a workflow task to OpenAI and return the result."""

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return {
            "ok": False,
            "error": "OPENAI_API_KEY is not configured",
        }

    client = OpenAI(api_key=api_key)

    selected_model = model or os.getenv(
        "OPENAI_MODEL",
        "gpt-4.1-mini",
    )

    try:
        response = client.responses.create(
            model=selected_model,
            instructions=instructions or (
                "You are the AI processing engine inside an "
                "automation workflow platform."
            ),
            input=prompt,
        )

        return {
            "ok": True,
            "output": response.output_text,
            "model": selected_model,
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
        }


def run(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Process data sent to the service layer."""

    if not isinstance(input_data, dict):
        raise TypeError("input_data must be a dictionary")

    return {
        "status": "processed",
        "input": input_data,
    }