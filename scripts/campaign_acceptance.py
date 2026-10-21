"""Submit once and poll the durable acceptance job; never retry campaign execution."""
import json
import socket
import urllib.error
import os
import time
import urllib.request
import urllib.parse
from pathlib import Path
if __package__:
    from .smart_search_smoke import ORIGIN, get_json
else:
    from smart_search_smoke import ORIGIN, get_json


def acceptance_request_key(environ):
    return "acceptance-"+"-".join(environ[name] for name in ("GITHUB_SHA","GITHUB_RUN_ID","GITHUB_RUN_ATTEMPT"))


_identity_cache={'token':'','expires':0}

def authentication_headers():
    operator=os.getenv('OPERATOR_CONTROL_TOKEN','').strip()
    if operator:return {'X-Operator-Token':operator}
    if _identity_cache['expires']>time.monotonic():return {'Authorization':'Bearer '+_identity_cache['token']}
    url=os.getenv('ACTIONS_ID_TOKEN_REQUEST_URL','')
    grant=os.getenv('ACTIONS_ID_TOKEN_REQUEST_TOKEN','')
    if not url or not grant:
        raise SystemExit('BLOCKED: authenticated acceptance requires GitHub OIDC or an operator token; no campaign started.')
    request=urllib.request.Request(url+('&' if '?' in url else '?')+urllib.parse.urlencode({'audience':'automakeai-production-acceptance'}),headers={'Authorization':'Bearer '+grant})
    with urllib.request.urlopen(request,timeout=15) as response:token=json.load(response)['value']
    _identity_cache.update(token=token,expires=time.monotonic()+180)
    return {'Authorization':'Bearer '+token}


def main():
    req = urllib.request.Request(ORIGIN+"/api/operator/v1-1-acceptance-once", data=json.dumps({'campaign':{'target_customer':'HVAC businesses','business_type':'HVAC','territory':'Norfolk, Virginia','target_count':3,'sending_limit':1,'offer':'AI lead generation and follow-up automation'}}).encode(), headers={"Content-Type":"application/json","Idempotency-Key":acceptance_request_key(os.environ),**authentication_headers()})
    with urllib.request.urlopen(req, timeout=60) as response:
        state = json.load(response)
    deadline = time.monotonic()+2700
    while state.get("status") in {"queued","running"} and time.monotonic() < deadline:
        print(json.dumps({"job_id":state["job_id"],"status":state["status"],
                          "stage":(state.get("progress") or {}).get("stage"),
                          "queue_position":state.get("queue_position"),
                          "active_executions":state.get("active_executions")}),flush=True)
        time.sleep(10)
        try:
            poll=urllib.request.Request(ORIGIN+state["poll_url"],headers={**authentication_headers()})
            with urllib.request.urlopen(poll,timeout=60) as response:state=json.load(response)
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            # Retry only the GET; never resubmit the durable campaign.
            print("Transient acceptance poll failure:", type(exc).__name__, flush=True)
            continue
    if state.get("status") in {"queued", "running"}:
        state = {"status": "timeout", "job_id": state.get("job_id"),
                 "poll_url": state.get("poll_url"),
                 "error": "ACCEPTANCE_DEADLINE_EXCEEDED_WITHOUT_COMPLETED_RECEIPT"}
    result = state.get("result") or state
    Path("acceptance.json").write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2),flush=True)
    if state.get("status") != "completed" or result.get("ok") is not True or result.get("pass") is not True or result.get("stage") != "complete":
        reason=result.get("reason") or state.get("error") or "INCOMPLETE_ACCEPTANCE_RECEIPT"
        stage=result.get("stage") or state.get("stage") or state.get("status") or "unknown"
        raise SystemExit(f"FAIL: production acceptance stage={stage} reason={reason}; no completed fresh-lead receipt")
    print("PASS: V1.1 production acceptance complete")


if __name__ == "__main__":
    main()
