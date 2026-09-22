"""Render cron entrypoint for deterministic outreach follow-up processing."""
import os
import sys
import urllib.request

url=os.environ.get("OUTREACH_PROCESS_URL","https://ai-ops-command-center.onrender.com/api/outreach/process-followups").strip()
token=os.environ.get("OUTREACH_CRON_TOKEN","").strip()
if not token:
    raise SystemExit("OUTREACH_CRON_TOKEN is required")
req=urllib.request.Request(url,method="POST",headers={"X-Outreach-Cron-Token":token,"Content-Type":"application/json"},data=b"{}")
try:
    with urllib.request.urlopen(req,timeout=120) as response:
        body=response.read().decode("utf-8","replace")
        print(body)
        if response.status<200 or response.status>=300:
            sys.exit(1)
except Exception as exc:
    print(f"follow-up processor failed: {exc}",file=sys.stderr)
    sys.exit(1)
