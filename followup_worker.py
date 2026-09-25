import os
import sys

import requests


def main():
    url = os.getenv("OUTREACH_FOLLOWUP_URL", "https://ai-ops-command-center.onrender.com/api/outreach/process-followups")
    token = os.getenv("OUTREACH_CRON_TOKEN", "").strip()
    if not token:
        raise RuntimeError("OUTREACH_CRON_TOKEN is not configured")

    # Must match the fail-closed production endpoint exactly.
    response = requests.post(
        url,
        headers={"X-Outreach-Cron-Token": token},
        timeout=120,
    )
    print(response.text)
    response.raise_for_status()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"followup worker failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
