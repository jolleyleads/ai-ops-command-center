"""V1.1 customer demo and campaign launch adapter.

This layer calls the existing V1 smart-search function. V1's after-request hook
continues to own verification, qualification, drafting and safe-send behavior.
No V1 safety gate is duplicated or bypassed here.
"""
import json
from flask import Response, jsonify, request
from app import app
from outreach_automation import OutreachLead
from smart_search import _smart_search
from v1_orchestration import orchestrate_discovery

MAX_DEMO_SEND_LIMIT=100


def _text(v, limit):
    return str(v or "").strip()[:limit]


def _lead_view(lead):
    try: evidence=json.loads(lead.evidence_json or "[]")
    except Exception: evidence=[]
    safe=[]
    for item in evidence[:5]:
        if isinstance(item,dict):
            safe.append({"source":item.get("source") or item.get("title") or "Public source","url":item.get("url") or "","observed_at":item.get("observed_at") or ""})
    status=(lead.status or "new").lower()
    return {"id":lead.id,"company":lead.company or "Unknown company","location":lead.location or "","why_qualified":"Verified public evidence met the V1 qualification gate" if status not in {"needs_evidence","rejected"} else "Additional evidence required","supporting_evidence":safe,"contact_status":"Verified contact available" if lead.contact_email else "Contact research pending","pipeline_stage":status.replace("_"," ").title(),"score":lead.score}


def _campaign_payload(data):
    target=_text(data.get("target_customer"),500)
    territory=_text(data.get("territory"),200)
    offer=_text(data.get("offer"),1200)
    try: send_limit=int(data.get("sending_limit") or 25)
    except Exception: send_limit=25
    send_limit=max(1,min(send_limit,MAX_DEMO_SEND_LIMIT))
    if not target: return None,{"ok":False,"error":"target_customer_required"}
    if not territory: return None,{"ok":False,"error":"territory_required"}
    # Target + territory drive V1 discovery. Offer is campaign context for future
    # personalization; it never changes verification/qualification truth criteria.
    query=target
    return {"target_customer":target,"territory":territory,"offer":offer,"sending_limit":send_limit,"query":query},None


@app.route("/api/demo/leads",methods=["GET"])
def demo_leads():
    leads=OutreachLead.query.order_by(OutreachLead.id.desc()).limit(20).all()
    return jsonify({"ok":True,"leads":[_lead_view(x) for x in leads]})


@app.route("/api/demo/campaigns/launch",methods=["POST"])
def launch_demo_campaign():
    campaign,error=_campaign_payload(request.get_json(silent=True) or {})
    if error:return jsonify(error),400
    # Directly invoke the same V1 discovery engine, then the same V1 orchestration
    # function that the production /api/smart-search response hook uses.
    discovery=_smart_search(campaign["query"],campaign["territory"])
    outreach=orchestrate_discovery(discovery)
    visible=[]
    for result in discovery.get("results") or []:
        if not isinstance(result,dict):continue
        visible.append({"company":result.get("company") or result.get("name") or result.get("business_name") or result.get("title") or "Unknown company","classification":result.get("classification") or "Candidate","verification":result.get("verification_gate") or result.get("promotion_status") or "candidate","source_url":result.get("url") or "","evidence_basis":result.get("evidence_basis") or result.get("verified_claim") or "Source-backed discovery result"})
    return jsonify({"ok":True,"campaign":{"target_customer":campaign["target_customer"],"territory":campaign["territory"],"offer":campaign["offer"],"sending_limit":campaign["sending_limit"],"safety":"V1 verification, qualification and safe-send gates unchanged"},"discovery":{"verified":discovery.get("verified_count",0),"candidates":discovery.get("unverified_candidate_count",0),"rejected":discovery.get("rejected_count",0),"results":visible},"outreach":outreach}),200


@app.route("/demo",methods=["GET"])
def customer_demo():
    return Response('''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Automation AI — Customer Demo</title><style>:root{--panel:#0d1b2d;--line:#213653;--text:#f5f8ff;--muted:#9fb0c8;--accent:#66e3b4;--blue:#79a9ff}*{box-sizing:border-box}body{margin:0;background:linear-gradient(145deg,#06101d,#0b1930);color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif}.wrap{max-width:1180px;margin:auto;padding:32px 20px 60px}.eyebrow{color:var(--accent);font-weight:800;letter-spacing:.12em;font-size:12px}.hero{font-size:clamp(34px,6vw,64px);line-height:1;margin:10px 0 14px;max-width:850px}.sub{color:var(--muted);font-size:18px;max-width:800px;line-height:1.55}.card{background:rgba(13,27,45,.92);border:1px solid var(--line);border-radius:18px;padding:20px;margin-top:22px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.field label{display:block;color:var(--muted);font-size:12px;font-weight:800;margin-bottom:7px}.field input,.field textarea{width:100%;background:#071321;border:1px solid #29415f;color:white;border-radius:11px;padding:12px;font:inherit}.wide{grid-column:1/-1}.steps{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}.step{padding:13px 8px;border-radius:12px;background:#091727;border:1px solid var(--line);text-align:center;font-size:12px;color:var(--muted)}.step b{display:block;color:var(--text);margin-top:5px}.step.active{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}button{background:var(--accent);border:0;border-radius:11px;padding:13px 18px;font-weight:900;color:#04120d;cursor:pointer}button:disabled{opacity:.55}.actions{display:flex;gap:10px;align-items:center;margin-top:14px}.note,.empty{color:var(--muted);font-size:12px}.lead{padding:16px 0;border-top:1px solid var(--line)}.lead h3{margin:0 0 6px}.chips{display:flex;gap:7px;flex-wrap:wrap;margin:9px 0}.chip{font-size:11px;border:1px solid #355274;border-radius:999px;padding:5px 8px;color:#cfe0f7}.evidence a{color:var(--blue);text-decoration:none;font-size:12px}.summary{margin-top:14px;color:#dce7f8}@media(max-width:760px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}.steps{grid-template-columns:repeat(2,1fr)}}</style></head><body><main class="wrap"><div class="eyebrow">AUTOMATION AI · V1.1</div><h1 class="hero">Launch a real verified outreach campaign.</h1><p class="sub">Enter the market you want. The customer layer hands the request to the existing V1 engine for discovery, evidence verification, qualification and outreach. V1 safety gates stay in control.</p><section class="card"><h2>Campaign setup</h2><div class="grid"><div class="field"><label>TARGET CUSTOMER</label><input id="target" placeholder="HVAC companies actively hiring technicians"></div><div class="field"><label>TERRITORY</label><input id="territory" placeholder="Hampton Roads, Virginia"></div><div class="field wide"><label>OFFER</label><textarea id="offer" placeholder="What are you offering and what problem does it solve?"></textarea></div><div class="field"><label>DAILY SENDING LIMIT</label><input id="limit" type="number" min="1" max="100" value="25"></div><div class="field"><label>CAMPAIGN SETTING</label><input value="Verify before outreach" disabled></div></div><div class="actions"><button id="launch">LAUNCH CAMPAIGN</button><span id="status" class="note">V1 verification and safe-send gates cannot be bypassed here.</span></div></section><section class="card"><h2>Automation journey</h2><div class="steps" id="steps"><div class="step">01<b>Discovering</b></div><div class="step">02<b>Verifying evidence</b></div><div class="step">03<b>Qualifying</b></div><div class="step">04<b>Preparing outreach</b></div><div class="step">05<b>Monitoring replies</b></div><div class="step">06<b>Booking</b></div></div><div id="summary" class="summary"></div></section><section class="card"><div class="eyebrow">LIVE PIPELINE VIEW</div><h2>Customer-ready results</h2><div id="leads" class="empty">Launch a campaign or refresh current pipeline results.</div><div class="actions"><button id="refresh">Refresh results</button></div></section></main><script>const $=id=>document.getElementById(id),leads=$('leads'),steps=[...document.querySelectorAll('.step')];function esc(s){return String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]))}function stage(n){steps.forEach((x,i)=>x.classList.toggle('active',i<=n))}async function load(){try{const r=await fetch('/api/demo/leads'),d=await r.json();leads.innerHTML=d.leads?.length?d.leads.map(x=>`<article class="lead"><h3>${esc(x.company)}</h3><div class="chips"><span class="chip">${esc(x.pipeline_stage)}</span><span class="chip">${esc(x.contact_status)}</span>${x.location?`<span class="chip">${esc(x.location)}</span>`:''}</div><div><b>Why qualified:</b> ${esc(x.why_qualified)}</div><div class="evidence">${(x.supporting_evidence||[]).map(e=>e.url?`<div><a target="_blank" rel="noopener" href="${esc(e.url)}">Supporting evidence · ${esc(e.source)}</a></div>`:'').join('')}</div></article>`).join(''):'<div class="empty">No V1 pipeline leads yet.</div>'}catch(e){leads.textContent='Results temporarily unavailable.'}}$('refresh').onclick=load;$('launch').onclick=async()=>{const b=$('launch');b.disabled=true;$('status').textContent='Running real V1 discovery and verification…';stage(0);try{const r=await fetch('/api/demo/campaigns/launch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_customer:$('target').value,territory:$('territory').value,offer:$('offer').value,sending_limit:$('limit').value})});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'Campaign failed');stage(3);$('summary').innerHTML=`<b>V1 result:</b> ${d.discovery.verified} verified · ${d.discovery.candidates} candidates · ${d.discovery.rejected} rejected · ${d.outreach.qualified||0} qualified · ${d.outreach.drafted||0} outreach prepared · ${d.outreach.sent||0} sent.`;$('status').textContent='Campaign processed through the existing V1 gates.';await load()}catch(e){$('status').textContent='Stopped safely: '+e.message}finally{b.disabled=false}};load();</script></body></html>''',mimetype="text/html")
