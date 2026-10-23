"""V1.1 customer demo and deterministic acceptance harness.

The adapter calls the frozen V1 discovery/orchestration functions. V1.1 may add
candidate-specific evidence and campaign context before orchestration, but never
bypasses V1 verification, qualification, enrichment, or safe-send gates.
"""
import json
from datetime import datetime, timezone
from flask import Response, jsonify, request
from app import app
from outreach_automation import OutreachLead
from smart_search import _smart_search
from src.research_policy import research_budget_seconds, research_target_count, requested_target_count, target_count_from_prompt
from campaign_jobs import enqueue_execution, execution_status
from v1_orchestration import orchestrate_discovery
from v11_evidence_upgrade import enhance_discovery

MAX_DEMO_SEND_LIMIT=100

def _text(v,limit):return str(v or "").strip()[:limit]
def _lead_view(lead):
    try:evidence=json.loads(lead.evidence_json or "[]")
    except Exception:evidence=[]
    safe=[]
    if isinstance(evidence,list):
        for item in evidence[:5]:
            if isinstance(item,dict):safe.append({"source":item.get("source") or item.get("title") or "Public source","url":item.get("url") or "","observed_at":item.get("observed_at") or ""})
    status=(lead.status or "new").lower()
    return {"id":lead.id,"company":lead.company or "Unknown company","location":lead.location or "","why_qualified":"Verified public evidence met the V1 qualification gate" if status not in {"needs_evidence","rejected"} else "Additional evidence required","supporting_evidence":safe,"contact_status":"Verified contact available" if lead.contact_email else "Contact research pending","pipeline_stage":status.replace("_"," ").title(),"score":lead.score}
def _campaign_payload(data):
    target=_text(data.get("target_customer"),500);territory=_text(data.get("territory"),200);offer=_text(data.get("offer"),1200)
    try:send_limit=int(data.get("sending_limit") or 25)
    except Exception:send_limit=25
    send_limit=max(1,min(send_limit,MAX_DEMO_SEND_LIMIT))
    try:target_count=target_count_from_prompt(target,data.get("target_count"))
    except (TypeError,ValueError) as exc:return None,{"ok":False,"error":str(exc),"maximum_results":20,"work_started":False}
    if not target:return None,{"ok":False,"error":"target_customer_required"}
    if not territory:return None,{"ok":False,"error":"territory_required"}
    return {"target_customer":target,"territory":territory,"offer":offer,"sending_limit":send_limit,"target_count":target_count,"business_type":_text(data.get("business_type"),300),"query":target},None
def _orchestration_payload(discovery,campaign,*,research_contacts=False):
    payload=dict(discovery);target=campaign["target_customer"]
    payload.update({"query":target,"goal":target,"intent":target,"location":campaign["territory"],"offer":campaign.get("offer") or "AI lead generation and customer follow-up automation","business_type":_text(campaign.get("business_type"),300),"intent_signal":target,"outreach_limit":campaign["sending_limit"],"require_decision_maker":campaign.get("require_decision_maker") is True})
    if research_contacts:
        # Only authenticated draft-only work may investigate unconfirmed companies.
        # These rows never enter the confirmed hiring results or a sending campaign.
        from src.company_identity import name_key
        rows=list(payload.get('results') or []);seen={name_key(r.get('company') or r.get('title')) for r in rows}
        for raw in discovery.get('contact_research_candidates') or []:
            key=name_key(raw.get('company') or raw.get('title'))
            if key and key not in seen:
                rows.append({**raw,'classification':'Candidate','promotion_status':'candidate',
                             'verification_gate':'pending','request_match_status':'unconfirmed'})
                seen.add(key)
        payload['results']=rows
    if campaign.get('prospect_policy'):
        payload.update(prospect_policy=campaign['prospect_policy'],request_spec=campaign['request_spec'])
    return payload
def _run_campaign(data):
    from src.execution_deadline import checkpoint
    checkpoint("configuration")
    campaign,error=_campaign_payload(data)
    if error:return None,"configuration",error["error"]
    # This bit exists only in the server-created authenticated job payload.
    campaign["send_authorized"]=data.get("send_authorized") is True
    campaign["require_decision_maker"]=data.get("require_decision_maker") is True
    from src.prospect_quality import POLICY, request_spec
    if data.get('prospect_policy')==POLICY:
        campaign.update(prospect_policy=POLICY,request_spec=request_spec(campaign['query'],campaign['territory'],campaign['offer'],campaign['business_type']))
    checkpoint("researching",requested=campaign["target_count"])
    try:discovery=_smart_search(campaign["query"],campaign["territory"],runtime_budget=research_budget_seconds(campaign["target_count"]),target_count=campaign["target_count"])
    except Exception as exc:return None,"discovery",f"{type(exc).__name__}: {exc}"
    if not isinstance(discovery,dict):return None,"discovery","DISCOVERY_NOT_OBJECT"
    if discovery.get("agent_error"):return None,"discovery","RESEARCH_AGENT_FAILED"
    if not isinstance(discovery.get("results",[]),list):return None,"discovery","DISCOVERY_RESULTS_NOT_LIST"
    checkpoint("verifying_sources")
    try:discovery=enhance_discovery(discovery,campaign["query"],campaign["territory"])
    except Exception as exc:app.logger.exception("V11_EVIDENCE_UPGRADE_ERROR");return None,"verification",f"{type(exc).__name__}: {exc}"
    try:
        checkpoint("qualifying_contacts")
        payload=_orchestration_payload(discovery,campaign,research_contacts=data.get("draft_only") is True and not campaign["send_authorized"])
        outreach=orchestrate_discovery(payload,authorized_send=True) if campaign["send_authorized"] and data.get("draft_only") is not True else orchestrate_discovery(payload,draft_only=True)
    except Exception as exc:return None,"orchestration",f"{type(exc).__name__}: {exc}"
    if not isinstance(outreach,dict):return None,"orchestration","OUTREACH_NOT_OBJECT"
    if campaign.get('prospect_policy'):
        from src.prospect_quality import for_lead
        from app import db
        qualities=[for_lead(lead) for key in set(outreach.get('lead_ids') or [])
                   if (lead:=db.session.get(OutreachLead,key)) is not None]
        supported=sum(q['well_supported'] for q in qualities)
        outreach['prospect_summary']={'requested':campaign['target_count'],'businesses_researched':len(discovery.get('results') or []),
            'well_supported':supported,'buyer_identified':sum(bool(q['contact']['buyer']) for q in qualities),
            'contact_ready':sum(q['contact']['state']=='Ready' for q in qualities),
            'remaining_well_supported':max(0,campaign['target_count']-supported),
            'note':'A well-supported business is not automatically ready for outreach. No automatic increase in volume.'}
    visible=[]
    for result in discovery.get("results") or []:
        if isinstance(result,dict):visible.append({"company":result.get("company") or result.get("name") or result.get("business_name") or result.get("title") or "Unknown company","classification":result.get("classification") or "Candidate","verification":result.get("verification_gate") or result.get("promotion_status") or "candidate","source_url":result.get("url") or "","website":result.get("website") or "","supporting_urls":result.get("supporting_urls") or [],"evidence_basis":result.get("evidence_basis") or result.get("verified_claim") or "Source-backed discovery result"})
    return {"ok":True,"campaign":{"target_customer":campaign["target_customer"],"territory":campaign["territory"],"offer":campaign["offer"],"sending_limit":campaign["sending_limit"],"target_count":campaign["target_count"],"research_budget_seconds":research_budget_seconds(campaign["target_count"]),"safety":"V1 verification, qualification and safe-send gates unchanged"},"discovery":{"provider_message":discovery.get("provider_message", ""),"live_source_count":discovery.get("live_source_count",0),"candidate_count":discovery.get("candidate_count",0),"excluded_result_count":discovery.get("excluded_result_count",0),"verification_diagnostics":discovery.get("verification_diagnostics",{}),"target_met":discovery.get("target_met",False),"runtime_budget_seconds":discovery.get("runtime_budget_seconds"),"budget_exhausted":discovery.get("budget_exhausted",False),"verified":discovery.get("verified_count",0),"candidates":discovery.get("unverified_candidate_count",0),"rejected":discovery.get("rejected_count",0),"results":visible,"contact_research_candidates":[{"company":r.get("company") or r.get("title"),"website":r.get("website"),"source_url":r.get("url"),"request_match_status":"unconfirmed"} for r in discovery.get("contact_research_candidates") or []]},"outreach":outreach},None,None

@app.route("/api/chat/lead-status",methods=["GET"])
def chat_lead_status():
    """Read-only, redacted qualification visibility; never triggers outreach."""
    from flask import request as _req
    from outreach_automation import _operator_authorized, _operator_session_authorized
    if not (_operator_authorized() or _operator_session_authorized()):
        return jsonify({"ok":False,"error":"Operator authentication required"}),401
    from lead_recovery import recovery_snapshot
    leads=OutreachLead.query.order_by(OutreachLead.id.desc()).limit(50).all()
    recoveries={row["lead_id"]:row for row in recovery_snapshot()}
    items=[]
    for lead in leads:
        r=recoveries.get(lead.id) or {}
        items.append({"id":lead.id,"company":lead.company,"status":lead.status,
           "verification":lead.verification,"last_error":lead.last_error or "",
           "has_contact_email":bool(lead.contact_email),"has_sent_message":bool(lead.gmail_message_id),
           "recovery_state":r.get("state"),"reason_codes":r.get("reason_codes") or [],
           "next_check_at":r.get("next_check_at")})
    resp=jsonify({"ok":True,"leads":items})
    resp.headers["Cache-Control"]="no-store"
    return resp

@app.route("/api/chat/campaigns/prepare",methods=["POST"])
def chat_prepare_campaign():
    """Explicit, authenticated draft-only campaign path; never authorizes live sends."""
    from outreach_automation import _operator_authorized, _operator_session_authorized
    if not (_operator_authorized() or _operator_session_authorized()):
        return jsonify({"ok":False,"error":"Operator authentication required"}),401
    data=request.get_json(silent=True) or {}
    query=_text(data.get("target_customer") or data.get("prompt"),500)
    offer=_text(data.get('offer') if 'offer' in data else 'AI lead generation and customer follow-up automation',1200)
    if not offer:return jsonify(ok=False,error='Describe your offer in Task options before preparing prospects.'),400
    campaign,error=_campaign_payload({
        "target_customer":query,"territory":_text(data.get("territory"),200),
        "offer":offer,
        "sending_limit":1,"target_count":data.get("target_count") or 10,
    })
    if error:return jsonify(error),400
    from src.prospect_quality import POLICY
    campaign.update(draft_only=True,send_authorized=False,prospect_policy=POLICY)
    return enqueue_execution("campaign",campaign,request.headers.get("Idempotency-Key"))

@app.route("/api/demo/leads",methods=["GET"])
def demo_leads():
    leads=OutreachLead.query.order_by(OutreachLead.id.desc()).limit(20).all();return jsonify({"ok":True,"leads":[_lead_view(x) for x in leads]})

@app.route("/api/chat/campaigns/launch",methods=["POST"])
def chat_launch_campaign():
    """Explicit operator authorization applies only to this durable campaign."""
    from outreach_automation import _operator_authorized, _operator_session_authorized, _csrf_ok
    if not (_operator_authorized() or _operator_session_authorized()):return jsonify({"ok":False,"error":"Operator authentication required"}),401
    if not _operator_authorized() and not _csrf_ok():return jsonify({"ok":False,"error":"Invalid session request token"}),403
    data=request.get_json(silent=True) or {}
    campaign,error=_campaign_payload({**data,"target_customer":data.get("target_customer") or data.get("prompt")})
    if error:return jsonify(error),400
    if data.get("send_emails") is not True:return jsonify({"ok":False,"error":"Choose campaign sending to launch outreach."}),400
    campaign.update(send_authorized=True,require_decision_maker=data.get("require_decision_maker") is True)
    return enqueue_execution("campaign",campaign,request.headers.get("Idempotency-Key"))

@app.route("/api/chat/campaign-settings",methods=["GET"])
def chat_campaign_settings():
    from outreach_automation import _operator_authorized, _operator_session_authorized, _csrf_token
    if not (_operator_authorized() or _operator_session_authorized()):return jsonify({"ok":False,"error":"Operator authentication required"}),401
    response=jsonify({"ok":True,"csrf_token":_csrf_token()})
    response.headers['Cache-Control']='no-store'
    return response
@app.route("/api/demo/campaigns/launch",methods=["POST"])
def launch_demo_campaign():
    campaign,error=_campaign_payload(request.get_json(silent=True) or {})
    if error:return jsonify(error),400
    return enqueue_execution("campaign",campaign,request.headers.get("Idempotency-Key"))

@app.route("/api/demo/campaigns/jobs/<job_id>",methods=["GET"])
def campaign_execution_status(job_id):
    return execution_status(job_id)

@app.route("/api/operator/v1-1-acceptance-once",methods=["POST"])
def v11_acceptance_once():
    data=request.get_json(silent=True) or {}
    payload={}
    if 'campaign' in data:
        if not isinstance(data['campaign'],dict):return jsonify({'ok':False,'error':'campaign_must_be_an_object'}),400
        campaign,error=_campaign_payload(data['campaign'])
        if error:return jsonify(error),400
        payload={'campaign':campaign}
    return enqueue_execution("acceptance",payload,request.headers.get("Idempotency-Key"))


def _run_acceptance(campaign=None, progress_callback=None):
    started=datetime.now(timezone.utc).isoformat()
    # Search a bounded set of distinct discovery pools. A pool that only
    # rediscovers already-queued companies remains a truthful non-pass; the
    # harness continues to the next pool and stops on the first genuinely fresh
    # lead that crosses the unchanged V1 qualification + drafting gates.
    # Nothing is deleted, reset, or mutated to manufacture freshness.
    campaign_catalog=[
      ("accounting firms","accounting firm"),
      ("insurance agencies","insurance agency"),
      ("veterinary clinics","veterinary clinic"),
      ("construction companies","construction"),
      ("real estate brokerages","real estate brokerage"),
      ("physical therapy clinics","physical therapy"),
      ("manufacturing companies","manufacturing"),
      ("security companies","security company"),
      ("moving companies","moving company"),
      ("cleaning companies","cleaning company"),
      ("printing companies","printing company"),
      ("staffing agencies","staffing agency"),
    ]
    territories=["Norfolk, Virginia","Chesapeake, Virginia","Virginia Beach, Virginia","Hampton, Virginia","Newport News, Virginia","Suffolk, Virginia"]
    # Deterministically rotate the bounded proof window using durable DB state.
    # This does not delete/reuse leads or relax duplicate checks; it simply prevents
    # every acceptance run from querying the same exhausted discovery pools.
    latest=OutreachLead.query.order_by(OutreachLead.id.desc()).first()
    rotation=(latest.id if latest else 0)%len(campaign_catalog)
    rotated=campaign_catalog[rotation:]+campaign_catalog[:rotation]
    campaign_pool=[
      {"target_customer":target,"business_type":kind,"territory":territories[(rotation+i)%len(territories)],"offer":"AI lead generation and follow-up automation","sending_limit":1,"target_count":1}
      for i,(target,kind) in enumerate(rotated[:4])
    ]
    if campaign is not None:
        controlled,error=_campaign_payload(campaign)
        if error:return jsonify(error),400
        campaign_pool=[controlled]
    # Keep each one-shot proof bounded to four campaigns while the catalog rotates
    # across industries and territories between runs.
    attempts=[]
    def report(stage, index=0):
        if progress_callback:
            progress_callback({"stage": stage, "campaign_index": index,
                               "campaign_total": len(campaign_pool),
                               "attempt_count": len(attempts),
                               "updated_at": datetime.now(timezone.utc).isoformat()})
    try:
        report("starting")
        for index, controlled in enumerate(campaign_pool, start=1):
            report("researching", index)
            before_max=0
            latest=OutreachLead.query.order_by(OutreachLead.id.desc()).first()
            if latest:before_max=latest.id
            payload,stage,reason=_run_campaign({**controlled,"draft_only":True})
            if not payload:
                attempts.append({"campaign":controlled,"stage":stage or "unknown","reason":reason or "UNKNOWN_FAILURE"})
                report("campaign_failed", index)
                continue
            d=payload.get("discovery") or {};o=payload.get("outreach") or {};required=("qualified","drafted","sent");missing=[k for k in required if k not in o]
            if missing:return jsonify({"ok":False,"pass":False,"stage":"result_validation","reason":"MISSING_OUTREACH_FIELDS","missing":missing,"timestamp":started,"attempts":attempts}),500
            owned_ids={x for x in o.get('lead_ids') or [] if type(x) is int}
            fresh=OutreachLead.query.filter(OutreachLead.id>before_max,OutreachLead.id.in_(owned_ids)).order_by(OutreachLead.id.asc()).all()
            fresh_receipt=[{"lead_id":x.id,"company":x.company,"status":x.status,"validated_contact":bool(x.contact_email),"gmail_message_id":x.gmail_message_id or ""} for x in fresh]
            attempt={"campaign":controlled,"discovery":{**d,"result_count":len(d.get("results") or [])},"outreach":{"eligible":o.get("eligible",0),"saved":o.get("saved",0),"qualified":o.get("qualified",0),"drafted":o.get("drafted",0),"sent":o.get("sent",0),"skipped":o.get("skipped",[])},"fresh_leads":fresh_receipt}
            attempts.append(attempt)
            report("campaign_evaluated", index)
            # Acceptance now proves a genuinely new DB lead crossed qualification
            # and drafting. Sending remains governed by the unchanged safe-send
            # gate; if production autosend is enabled, require its durable receipt.
            from outreach_automation import OutreachQualificationReceipt
            def has_qualification(lead):
                receipt=OutreachQualificationReceipt.query.filter_by(lead_id=lead.id).first()
                try:return bool(lead.contact_email and receipt and json.loads(receipt.receipt_json or '{}').get('ok') is True)
                except (TypeError,ValueError):return False
            qualified_fresh=[x for x in fresh if has_qualification(x)]
            drafted_fresh=[x for x in qualified_fresh if x.subject and x.body and (x.status or "").lower() in {"drafted","sent","followup_sent","replied","booked"}]
            if qualified_fresh and drafted_fresh:
                sent_expected=bool(o.get("autosend_enabled"))
                sent_fresh=[x for x in fresh if x.gmail_message_id]
                if sent_expected and not sent_fresh:
                    send_failures=[x for x in (o.get("skipped") or []) if x.get("reason")=="safe_send_failed"]
                    if send_failures:
                        return jsonify({"ok":False,"pass":False,"stage":"safe_send","reason":"FRESH_QUALIFIED_DRAFT_FAILED_SAFE_SEND","timestamp":started,"controlled_campaign":controlled,"discovery":attempt["discovery"],"outreach":attempt["outreach"],"fresh_proof":{"new_lead_ids":[x.id for x in fresh],"validated_contact_count":sum(1 for x in fresh if x.contact_email),"qualified_count":len(qualified_fresh),"drafted_count":len(drafted_fresh),"sent_count":0},"attempts":attempts,"safety":"V1 verification, qualification and safe-send gates remained authoritative"}),409
                    continue
                return jsonify({"ok":True,"pass":True,"stage":"complete","timestamp":started,"controlled_campaign":controlled,"discovery":attempt["discovery"],"outreach":attempt["outreach"],"fresh_proof":{"new_lead_ids":[x.id for x in fresh],"validated_contact_count":sum(1 for x in fresh if x.contact_email),"qualified_count":len(qualified_fresh),"drafted_count":len(drafted_fresh),"sent_count":len(sent_fresh)},"attempts":attempts,"safety":"V1 verification, qualification and safe-send gates remained authoritative"}),200
        report("completed_without_fresh_proof", len(campaign_pool))
        return jsonify({"ok":False,"pass":False,"stage":"fresh_lead_proof","reason":"NO_FRESH_LEAD_REACHED_QUALIFIED_AND_DRAFTED","timestamp":started,"attempts":attempts,"safety":"V1 gates were not weakened; acceptance refused to count already-queued leads"}),409
    except Exception as exc:app.logger.exception("V11_ACCEPTANCE_UNEXPECTED_ERROR");return jsonify({"ok":False,"pass":False,"stage":"unexpected_error","reason":f"{type(exc).__name__}: {exc}","timestamp":started,"attempts":attempts}),500
@app.route("/demo",methods=["GET"])
def customer_demo():
    return Response('''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Automation AI — Customer Demo</title><style>:root{--panel:#0d1b2d;--line:#213653;--text:#f5f8ff;--muted:#9fb0c8;--accent:#66e3b4}*{box-sizing:border-box}body{margin:0;background:#07111f;color:var(--text);font-family:Inter,system-ui,sans-serif}.wrap{max-width:1100px;margin:auto;padding:32px 20px}.card{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:20px;margin-top:20px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}label{display:block;color:var(--muted);font-size:12px;font-weight:800;margin-bottom:6px}input,textarea{width:100%;background:#071321;border:1px solid #29415f;color:white;border-radius:11px;padding:12px}.wide{grid-column:1/-1}button{background:var(--accent);border:0;border-radius:11px;padding:13px 18px;font-weight:900}.muted{color:var(--muted)}@media(max-width:700px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}}</style></head><body><main class="wrap"><h1>Automation AI · V1.1</h1><p class="muted">Real campaign launch through the existing V1 verification, qualification and safe-send gates.</p><section class="card"><div class="grid"><div><label>TARGET CUSTOMER</label><input id="target" placeholder="e.g. law firms actively hiring paralegals"></div><div><label>TERRITORY</label><input id="territory" placeholder="Norfolk, Virginia"></div><div class="wide"><label>OFFER</label><textarea id="offer"></textarea></div><div><label>DAILY SENDING LIMIT</label><input id="limit" type="number" min="1" max="100" value="25"></div></div><p><button id="launch">LAUNCH CAMPAIGN</button></p><pre id="result" class="muted">Ready.</pre></section></main><script>
const $=x=>document.getElementById(x);
let campaignKey='',campaignBody='';
$('launch').onclick=async()=>{
  const button=$('launch');button.disabled=true;
  $('result').textContent='Researching and verifying prospects…';
  try{
    const body=JSON.stringify({target_customer:$('target').value,territory:$('territory').value,offer:$('offer').value,sending_limit:$('limit').value});
    if(body!==campaignBody||!campaignKey){campaignBody=body;campaignKey=crypto.randomUUID()}
    const response=await fetch('/api/demo/campaigns/launch',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':campaignKey},body});
    let data=await response.json();
    if(!response.ok)throw new Error(data.error||data.reason||'Campaign launch failed');
    while(data.status==='queued'||data.status==='running'){
      $('result').textContent='Researching and verifying prospects… '+data.status;
      await new Promise(resolve=>setTimeout(resolve,5000));
      const poll=await fetch(data.poll_url);
      if(!poll.ok)throw new Error('Could not read campaign status');
      data=await poll.json();
    }
    $('result').textContent=JSON.stringify(data.status==='failed'?{status:data.status,error:data.error,result:data.result}:data.result||data,null,2);
    if(data.status==='completed')campaignKey='';
  }catch(error){
    $('result').textContent='Connection or launch issue: '+error.message+'. A submitted campaign may still be running. Click again with the same fields to resume its status.';
  }finally{button.disabled=false}
};
</script></body></html>''',mimetype="text/html")
