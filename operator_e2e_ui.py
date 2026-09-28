"""Authenticated operator UI for controlled production acceptance runners."""
from flask import Response, redirect, url_for
from app import app
import outreach_automation as oa


@app.after_request
def _inject_e2e_control(response):
    """Add protected production acceptance controls to the authenticated Command Center."""
    if response.status_code != 200 or response.mimetype != "text/html":
        return response
    if not oa._operator_session_authorized() or response.direct_passthrough:
        return response
    try:
        body = response.get_data(as_text=True)
    except Exception:
        return response
    if "AI Ops Command Center" not in body or "/operator/production-e2e" in body:
        return response
    controls = ('<a href="/operator/production-e2e" style="display:inline-block;margin-top:10px;background:#fff;color:#101526;text-decoration:none;font-weight:800;border-radius:8px;padding:10px 12px">RUN PRODUCTION E2E</a> '
                '<a href="/operator/provider-acceptance" style="display:inline-block;margin-top:10px;background:#fff;color:#101526;text-decoration:none;font-weight:800;border-radius:8px;padding:10px 12px">RUN PROVIDER ACCEPTANCE</a>')
    if "</header>" in body:
        body = body.replace("</header>", controls + "</header>", 1)
        response.set_data(body)
        response.headers["Content-Length"] = str(len(response.get_data()))
    return response


@app.route("/operator/production-e2e", methods=["GET"])
def operator_e2e_page():
    if not oa._operator_session_authorized():
        return redirect(url_for("operator_login"), 303)
    csrf = oa._csrf_token()
    recipient = "jolleysalesfloor@gmail.com"
    return Response(f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Production E2E</title><style>body{{font-family:system-ui,-apple-system,sans-serif;background:#0b1020;color:#e8ecf5;margin:0;padding:22px}}.box{{max-width:760px;margin:auto;background:#141b2d;border:1px solid #27304a;border-radius:14px;padding:20px}}button,a{{display:inline-block;background:#fff;color:#101526;border:0;border-radius:9px;padding:13px 16px;font-weight:800;text-decoration:none}}button[disabled]{{opacity:.55}}pre{{white-space:pre-wrap;word-break:break-word;background:#080c18;padding:14px;border-radius:9px;min-height:120px}}.muted{{color:#9aa7c2}}.pass{{color:#7ee787}}.fail{{color:#ff7b72}}</style></head><body><div class="box"><a href="/operator">← Command Center</a><h2>Production E2E</h2><p>This intentionally sends a real Gmail message and creates a real Google Calendar event for <b>{recipient}</b>.</p><p class="muted">Validated lead → Gmail provider receipt → interested reply path → Calendar availability → event creation → durable Google read-back.</p><button id="run">RUN PRODUCTION E2E</button><h3 id="status">Ready</h3><pre id="report">No run yet.</pre></div><script>const button=document.getElementById('run'),statusEl=document.getElementById('status'),report=document.getElementById('report');button.onclick=async()=>{{button.disabled=true;statusEl.textContent='Running real Gmail + Calendar test…';try{{const r=await fetch('/api/operator/production-e2e',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CSRF-Token':'{csrf}'}},body:JSON.stringify({{recipient:'{recipient}'}})}});const data=await r.json();report.textContent=JSON.stringify(data,null,2);const passed=r.ok&&data.pass===true;statusEl.textContent=passed?'PASS — Gmail + Calendar verified':'FAIL — see exact stage below';statusEl.className=passed?'pass':'fail';}}catch(e){{statusEl.textContent='FAIL — request error';report.textContent=String(e);}}finally{{button.disabled=false;}}}};</script></body></html>''', mimetype="text/html")


@app.route("/operator/provider-acceptance", methods=["GET"])
def operator_provider_acceptance_page():
    if not oa._operator_session_authorized():
        return redirect(url_for("operator_login"), 303)
    csrf = oa._csrf_token()
    return Response(f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Provider Acceptance</title><style>body{{font-family:system-ui,-apple-system,sans-serif;background:#0b1020;color:#e8ecf5;margin:0;padding:22px}}.box{{max-width:760px;margin:auto;background:#141b2d;border:1px solid #27304a;border-radius:14px;padding:20px}}button,a{{display:inline-block;background:#fff;color:#101526;border:0;border-radius:9px;padding:13px 16px;font-weight:800;text-decoration:none}}pre{{white-space:pre-wrap;word-break:break-word;background:#080c18;padding:14px;border-radius:9px;min-height:120px}}</style></head><body><div class="box"><a href="/operator">← Command Center</a><h2>Provider Acceptance</h2><p>Runs the controlled provider acceptance inside the existing authenticated production environment. Production cron is not changed.</p><button id="run">RUN PROVIDER ACCEPTANCE TEST</button><h3 id="status">Ready</h3><pre id="report">No run yet.</pre></div><script>const b=document.getElementById('run'),s=document.getElementById('status'),p=document.getElementById('report');b.onclick=async()=>{{b.disabled=true;s.textContent='Running…';try{{const r=await fetch('/api/operator/provider-acceptance-once',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CSRF-Token':'{csrf}'}},body:JSON.stringify({{recipient:'jolleysalesfloor@gmail.com'}})}});const d=await r.json();p.textContent=JSON.stringify(d,null,2);s.textContent=r.ok&&d.ok===true?'PASS — provider send + availability verified':'FAIL — see exact stage below';}}catch(e){{s.textContent='FAIL — request error';p.textContent=String(e);}}finally{{b.disabled=false;}}}};</script></body></html>''', mimetype="text/html")
