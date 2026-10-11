"""Submit once and poll the durable acceptance job; never retry campaign execution."""
import json
import os
import time
import urllib.request
from pathlib import Path
if __package__:
    from .smart_search_smoke import ORIGIN, get_json
else:
    from smart_search_smoke import ORIGIN, get_json


def acceptance_request_key(environ):
    return "acceptance-"+"-".join(environ[name] for name in ("GITHUB_SHA","GITHUB_RUN_ID","GITHUB_RUN_ATTEMPT"))


def main():
    req = urllib.request.Request(ORIGIN+"/api/operator/v1-1-acceptance-once", data=b"{}", headers={"Content-Type":"application/json","Idempotency-Key":acceptance_request_key(os.environ)})
    with urllib.request.urlopen(req, timeout=60) as response:
        state = json.load(response)
    deadline = time.monotonic()+2700
    while state.get("status") in {"queued","running"} and time.monotonic() < deadline:
        print("Acceptance job",state["job_id"],state["status"],flush=True)
        time.sleep(10)
        state = get_json(ORIGIN+state["poll_url"])
    result = state.get("result") or state
    Path("acceptance.json").write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2),flush=True)
    if state.get("status") != "completed" or result.get("ok") is not True or result.get("pass") is not True or result.get("stage") != "complete":
        raise SystemExit("FAIL: no completed fresh-lead acceptance receipt")
    print("PASS: V1.1 production acceptance complete")


if __name__ == "__main__":
    main()
