"""V1.1 customer demo and deterministic acceptance harness.

The adapter calls the frozen V1 discovery/orchestration functions. The acceptance
endpoint exercises the same adapter without bypassing verification or safe-send.
"""
import json
from datetime import datetime, timezone
from flask import Response, jsonify, request
from app import app
from outreach_automation import OutreachLead
from smart_search import _smart_search
from v1_orchestration import orchestrate_discovery

MAX_DEMO_SEND_LIMIT=100


def _text(v, limit): return str(v or "").strip()[:limit]


def _lead_view(lead):
    try: evidence=json.loads(lead.evidence_json or "[]")
    except Exception: evidence=[]
    safe=[]
    for item in evidence[:5]:
        if isinstance(item,dict): safe.append({"source":item.get("source") or item.get("title") or "Public source","url":item.get("url") or "","observed_at":item.get("observed_at") or ""})
    status=(lead.status or "new").lower()
    return {"id":lead.id,"company":lead.company or "Unknown company","location":lead.location or "","why_qualified":"Verified public evidence met the V1 qualification gate" if status not in {"needs_evidence","rejected"} else "Additional evidence required","supporting_evidence":safe,"contact_status":"Verified contact available" if lead.contact_email else "Contact research pending","pipeline_stage":status.replace("_"," ").title(),"score":lead.score}


def _campaign_payload(data):
    target=_text(data.get("target_customer"),500); territory=_text(data.get("territory"),200); offer=_text(data.get("offer"),1200)
    try: send_limit=int(data.get("sending_limit") or 25)
    except Exception: send_limit=25
    send_limit=max(1,min(send_limit,MAX_DEMO_SEND_LIMIT))
    if not target:return None,{"ok":False,"error":"target_customer_required"}
    if not territory:return None,{"ok":False,"error":"territory_required"}
    return {"target_customer":target,"territory":territory,"offer":offer,"sending_limit":send_limit,"query":target},None


def _run_campaign(data):
    campaign,error=_campaign_payload(data)
    if error:return None,"configuration",error["error"]
    try: discovery=_smart_search(campaign["query"],campaign["territory"])
    except Exception as exc:return None,"discovery",f"{type(exc).__name__}: {exc}"
    if not isinstance(discovery,dict):return None,"discovery","DISCOVERY_NOT_OBJECT"
    if not isinstance(discovery.get("results",[]),list):return None,"discovery","DISCOVERY_RESULTS_NOT_LIST"
    try: outreach=orchestrate_discovery(discovery)
    except Exception as exc:return None,"orchestration",f"{type(exc).__name__}: {exc}"
    if not isinstance(outreach,dict):return None,"orchestration","OUTREACH_NOT_OBJECT"
    visible=[]
    for result in discovery.get("results") or []:
        if isinstance(result,dict): visible.append({"company":result.get("company") or result.get("name") or result.get("business_name") or result.get("title") or "Unknown company","classification":result.get("classification") or "Candidate","verification":result.get("verification_gate") or result.get("promotion_status") or "candidate","source_url":result.get("url") or "","evidence_basis":result.get("evidence_basis") or result.get("verified_claim") or "Source-backed discovery result"})
    payload={"ok":True,"campaign":{"target_customer":campaign["target_customer"],"territory":campaign["territory"],"offer":campaign["offer"],"sending_limit":campaign["sending_limit"],"safety":"V1 verification, qualification and safe-send gates unchanged"},"discovery":{"verified":discovery.get("verified_count",0),"candidates":discovery.get("unverified_candidate_count",0),"rejected":discovery.get("rejected_count",0),"results":visible},"outreach":outreach}
    return payload,None,None


@app.route("/api/demo/leads",methods=["GET"])
def demo_leads():
    leads=OutreachLead.query.order_by(OutreachLead.id.desc()).limit(20).all(); return jsonify({"ok":True,"leads":[_lead_view(x) for x in leads]})


@app.route("/api/demo/campaigns/launch",methods=["POST"])
def launch_demo_campaign():
    payload,stage,reason=_run_campaign(request.get_json(silent=True) or {})
    if payload:return jsonify(payload),200
    return jsonify({"ok":False,"stage":stage,"reason":reason}),400 if stage=="configuration" else 500


@app.route("/api/operator/v1-1-acceptance-once",methods=["POST"])
def v11_acceptance_once():
    """One-shot server-side acceptance of the customer launch adapter.

    Uses a controlled campaign with sending_limit=1 and the unchanged V1 gates.
    PASS means adapter + discovery + orchestration returned structurally valid
    results. A zero-lead outcome is valid; fabricated leads are never required.
    """
    started=datetime.now(timezone.utc).isoformat()
    controlled={"target_customer":"HVAC companies actively hiring technicians","territory":"Norfolk, Virginia","offer":"AI lead generation and follow-up automation","sending_limit":1}
    payload,stage,reason=_run_campaign(controlled)
    if not payload:
        return jsonify({"ok":False,"pass":False,"stage":stage,"reason":reason,"timestamp":started}),500
    d=payload["discovery"]; o=payload["outreach"]
    required=("qualified","drafted","sent")
    missing=[k for k in required if k not in o]
    if missing:
        return jsonify({"ok":False,"pass":False,"stage":"result_validation","reason":"MISSING_OUTREACH_FIELDS","missing":missing,"timestamp":started}),500
    return jsonify({"ok":True,"pass":True,"stage":"complete","timestamp":started,"controlled_campaign":controlled,"discovery":{"verified":d["verified"],"candidates":d["candidates"],"rejected":d["rejected"],"result_count":len(d["results"])},"outreach":{"qualified":o.get("qualified",0),"drafted":o.get("drafted",0),"sent":o.get("sent",0)},"safety":"Frozen V1 verification, qualification and safe-send gates remained authoritative"}),200


@app.route("/demo",methods=["GET"])
def customer_demo():
    return Response('''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Automation AI — Customer Demo</title><style>:root{--panel:#0d1b2d;--line:#213653;--text:#f5f8ff;--muted:#9fb0c8;--accent:#66e3b4}*{box-sizing:border-box}body{margin:0;background:#07111f;color:var(--text);font-family:Inter,system-ui,sans-serif}.wrap{max-width:1100px;margin:auto;padding:32px 20px}.card{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:20px;margin-top:20px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}label{display:block;color:var(--muted);font-size:12px;font-weight:800;margin-bottom:6px}input,textarea{width:100%;background:#071321;border:1px solid #29415f;color:white;border-radius:11px;padding:12px}.wide{grid-column:1/-1}button{background:var(--accent);border:0;border-radius:11px;padding:13px 18px;font-weight:900}.muted{color:var(--muted)}@media(max-width:700px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}}</style></head><body><main class="wrap"><h1>Automation AI · V1.1</h1><p class="muted">Real campaign launch through the existing V1 verification, qualification and safe-send gates.</p><section class="card"><div class="grid"><div><label>TARGET CUSTOMER</label><input id="target" placeholder="HVAC companies actively hiring technicians"></div><div><label>TERRITORY</label><input id="territory" placeholder="Norfolk, Virginia"></div><div class="wide"><label>OFFER</label><textarea id="offer"></textarea></div><div><label>DAILY SENDING LIMIT</label><input id="limit" type="number" min="1" max="100" value="25"></div></div><p><button id="launch">LAUNCH CAMPAIGN</button></p><pre id="result" class="muted">Ready.</pre></section></main><script>const $=x=>document.getElementById(x);$('launch').onclick=async()=>{const b=$('launch');b.disabled=true;$('result').textContent='Running V1 pipeline…';try{const r=await fetch('/api/demo/campaigns/launch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_customer:$('target').value,territory:$('territory').value,offer:$('offer').value,sending_limit:$('limit').value})});$('result').textContent=JSON.stringify(await r.json(),null,2)}catch(e){$('result').textContent='Stopped safely: '+e.message}finally{b.disabled=false}}</script></body></html>''',mimetype="text/html")
