"""Authenticated operator control for real Gmail inbound processing."""
from flask import Response, jsonify, redirect, request, url_for
from app import app
import outreach_automation as oa
from v1_orchestration import scan_real_inbound_replies


@app.route("/operator/real-inbound", methods=["GET"])
def operator_real_inbound_page():
    if not oa._operator_session_authorized():
        return redirect(url_for("operator_login"), 303)
    csrf = oa._csrf_token()
    return Response(f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Real Inbound Gmail Test</title><style>body{{font-family:system-ui,-apple-system,sans-serif;background:#0b1020;color:#e8ecf5;margin:0;padding:22px}}.box{{max-width:800px;margin:auto;background:#141b2d;border:1px solid #27304a;border-radius:14px;padding:20px}}button,a{{display:inline-block;background:#fff;color:#101526;border:0;border-radius:9px;padding:13px 16px;font-weight:800;text-decoration:none}}button[disabled]{{opacity:.55}}pre{{white-space:pre-wrap;word-break:break-word;background:#080c18;padding:14px;border-radius:9px;min-height:120px}}.pass{{color:#7ee787}}.fail{{color:#ff7b72}}</style></head><body><div class="box"><a href="/operator">← Command Center</a><h2>Real Inbound Gmail Acceptance</h2><p>Reads actual Gmail threads. No synthetic reply injection.</p><button id="run">PROCESS REAL INBOUND REPLY</button><h3 id="status">Ready</h3><pre id="report">No run yet.</pre></div><script>const b=document.getElementById('run'),s=document.getElementById('status'),p=document.getElementById('report');b.onclick=async()=>{{b.disabled=true;s.className='';s.textContent='Reading real Gmail thread…';p.textContent='Working…';try{{const r=await fetch('/api/operator/real-inbound',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CSRF-Token':'{csrf}'}}}});const d=await r.json();p.textContent=JSON.stringify(d,null,2);const ok=r.ok&&d.ok===true;s.textContent=ok?'PROCESSING COMPLETE — inspect provider-backed stages':'FAIL — see exact stage';s.className=ok?'pass':'fail';}}catch(e){{s.textContent='FAIL — request error';s.className='fail';p.textContent=String(e)}}finally{{b.disabled=false}}}};</script></body></html>''', mimetype="text/html")


@app.route("/api/operator/real-inbound", methods=["POST"])
def operator_real_inbound_run():
    if not oa._operator_session_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if not oa._csrf_valid(request):
        return jsonify({"ok": False, "error": "csrf_failed"}), 403
    result = scan_real_inbound_replies()
    return jsonify(result), 200 if result.get("ok") else 502
