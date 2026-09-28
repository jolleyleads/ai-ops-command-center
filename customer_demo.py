"""V1.1 customer-facing demo layer.

Read/presentation layer over the existing V1 pipeline. This module deliberately
avoids changing V1 discovery, qualification, outreach, inbound, or booking logic.
"""
import json
from flask import Response, jsonify, request
from app import app
from outreach_automation import OutreachLead


def _lead_view(lead):
    try:
        evidence = json.loads(lead.evidence_json or "[]")
    except Exception:
        evidence = []
    safe_evidence=[]
    for item in evidence[:5]:
        if not isinstance(item,dict):
            continue
        safe_evidence.append({
            "source": item.get("source") or item.get("title") or "Public source",
            "url": item.get("url") or "",
            "observed_at": item.get("observed_at") or "",
        })
    status=(lead.status or "new").lower()
    return {
        "id": lead.id,
        "company": lead.company or "Unknown company",
        "location": lead.location or "",
        "why_qualified": "Verified public evidence met the V1 qualification gate" if status not in {"needs_evidence","rejected"} else "Additional evidence required",
        "supporting_evidence": safe_evidence,
        "contact_status": "Verified contact available" if lead.contact_email else "Contact research pending",
        "pipeline_stage": status.replace("_"," ").title(),
        "score": lead.score,
    }


@app.route("/api/demo/leads", methods=["GET"])
def demo_leads():
    leads=OutreachLead.query.order_by(OutreachLead.id.desc()).limit(20).all()
    return jsonify({"ok":True,"leads":[_lead_view(x) for x in leads]})


@app.route("/demo", methods=["GET"])
def customer_demo():
    return Response('''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Automation AI — Customer Demo</title><style>
:root{--bg:#07111f;--panel:#0d1b2d;--line:#213653;--text:#f5f8ff;--muted:#9fb0c8;--accent:#66e3b4;--blue:#79a9ff}*{box-sizing:border-box}body{margin:0;background:linear-gradient(145deg,#06101d,#0b1930);color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif}.wrap{max-width:1180px;margin:auto;padding:32px 20px 60px}.eyebrow{color:var(--accent);font-weight:800;letter-spacing:.12em;font-size:12px}.hero{font-size:clamp(34px,6vw,64px);line-height:1;margin:10px 0 14px;max-width:850px}.sub{color:var(--muted);font-size:18px;max-width:760px;line-height:1.55}.card{background:rgba(13,27,45,.92);border:1px solid var(--line);border-radius:18px;padding:20px;margin-top:22px;box-shadow:0 18px 55px rgba(0,0,0,.25)}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.field label{display:block;color:var(--muted);font-size:12px;font-weight:800;margin-bottom:7px}.field input,.field textarea{width:100%;background:#071321;border:1px solid #29415f;color:white;border-radius:11px;padding:12px;font:inherit}.field textarea{min-height:82px;resize:vertical}.wide{grid-column:1/-1}.steps{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-top:18px}.step{padding:13px 8px;border-radius:12px;background:#091727;border:1px solid var(--line);text-align:center;font-size:12px;color:var(--muted)}.step b{display:block;color:var(--text);margin-top:5px}.step.on{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}button{background:var(--accent);border:0;border-radius:11px;padding:13px 18px;font-weight:900;color:#04120d;cursor:pointer}.actions{display:flex;gap:10px;align-items:center;margin-top:14px}.note{color:var(--muted);font-size:12px}.lead{padding:16px 0;border-top:1px solid var(--line)}.lead:first-child{border-top:0}.lead h3{margin:0 0 6px}.chips{display:flex;gap:7px;flex-wrap:wrap;margin:9px 0}.chip{font-size:11px;border:1px solid #355274;border-radius:999px;padding:5px 8px;color:#cfe0f7}.reason{color:#dce7f8}.evidence a{color:var(--blue);text-decoration:none;font-size:12px}.empty{color:var(--muted);padding:18px 0}@media(max-width:760px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}.steps{grid-template-columns:repeat(2,1fr)}}
</style></head><body><main class="wrap"><div class="eyebrow">AUTOMATION AI · V1.1 CUSTOMER DEMO</div><h1 class="hero">Turn a target market into qualified conversations.</h1><p class="sub">Set the campaign. Automation AI discovers prospects, verifies evidence, qualifies opportunities, prepares outreach, monitors replies and moves interested prospects toward booking using the existing V1 production pipeline.</p>
<section class="card"><h2>Campaign setup</h2><div class="grid"><div class="field"><label>TARGET CUSTOMER</label><input id="target" placeholder="HVAC companies actively hiring technicians"></div><div class="field"><label>TERRITORY</label><input id="territory" placeholder="Hampton Roads, Virginia"></div><div class="field wide"><label>OFFER</label><textarea id="offer" placeholder="What are you offering and what problem does it solve?"></textarea></div><div class="field"><label>DAILY SENDING LIMIT</label><input id="limit" type="number" min="1" value="25"></div><div class="field"><label>CAMPAIGN SETTING</label><input id="setting" value="Verify before outreach"></div></div><div class="actions"><button id="preview">Preview campaign</button><span class="note">Demo mode does not bypass V1 verification or safety gates.</span></div></section>
<section class="card"><h2>Automation journey</h2><div class="steps"><div class="step on">01<b>Discovering</b></div><div class="step on">02<b>Verifying evidence</b></div><div class="step on">03<b>Qualifying</b></div><div class="step on">04<b>Preparing outreach</b></div><div class="step on">05<b>Monitoring replies</b></div><div class="step on">06<b>Booking</b></div></div></section>
<section class="card"><div style="display:flex;justify-content:space-between;gap:12px;align-items:center"><div><div class="eyebrow">LIVE PIPELINE VIEW</div><h2 style="margin-bottom:4px">Useful results, not developer noise</h2></div><button id="refresh">Refresh results</button></div><div id="leads" class="empty">Loading current pipeline…</div></section></main><script>
const leads=document.getElementById('leads');function esc(s){return String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]))}async function load(){leads.textContent='Loading current pipeline…';try{const r=await fetch('/api/demo/leads');const d=await r.json();if(!d.leads?.length){leads.innerHTML='<div class="empty">No pipeline results yet. Run a V1 campaign and verified leads will appear here.</div>';return}leads.innerHTML=d.leads.map(x=>`<article class="lead"><h3>${esc(x.company)}</h3><div class="chips"><span class="chip">${esc(x.pipeline_stage)}</span><span class="chip">${esc(x.contact_status)}</span>${x.location?`<span class="chip">${esc(x.location)}</span>`:''}</div><div class="reason"><b>Why qualified:</b> ${esc(x.why_qualified)}</div><div class="evidence">${(x.supporting_evidence||[]).map(e=>e.url?`<div><a target="_blank" rel="noopener" href="${esc(e.url)}">Supporting evidence · ${esc(e.source)}</a></div>`:'').join('')}</div></article>`).join('')}catch(e){leads.innerHTML='<div class="empty">Results are temporarily unavailable.</div>'}}document.getElementById('refresh').onclick=load;document.getElementById('preview').onclick=()=>{const t=document.getElementById('target').value.trim(),a=document.getElementById('territory').value.trim();document.getElementById('preview').textContent=t?`Ready: ${t}${a?' · '+a:''}`:'Add a target customer';};load();</script></body></html>''',mimetype="text/html")
