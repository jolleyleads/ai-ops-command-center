"""Authenticated operator control for real Gmail inbound processing."""
from datetime import datetime
import json
from flask import Response, jsonify, redirect, request, url_for
from app import app, db
import outreach_automation as oa
from v1_orchestration import scan_real_inbound_replies

ACCEPTANCE_SUBJECT = "REAL INBOUND ACCEPTANCE TEST — REPLY TO THIS EMAIL"
ACCEPTANCE_RECIPIENT = "jolleysalesfloor@gmail.com"


def _register_acceptance_lead(data):
    message_id = str(data.get("message_id") or "").strip()
    thread_id = str(data.get("thread_id") or "").strip()
    if not message_id or not thread_id:
        return {"ok": False, "error": "message_id_and_thread_id_required"}
    existing = oa.OutreachLead.query.filter_by(gmail_thread_id=thread_id).first()
    if existing:
        return {"ok": True, "lead_id": existing.id, "stage": "already_registered", "thread_id": thread_id}
    now = datetime.utcnow()
    evidence = [{"url": "https://mail.google.com/", "email": ACCEPTANCE_RECIPIENT, "title": ACCEPTANCE_SUBJECT, "snippet": "Operator-controlled real Gmail inbound acceptance thread.", "observed_at": now.isoformat() + "Z"}]
    lead = oa.OutreachLead(company="Real Inbound Acceptance Test", contact_email=ACCEPTANCE_RECIPIENT, contact_name="Production Acceptance", location="Portsmouth, VA", source_url="https://mail.google.com/", evidence_json=oa._canonical_json(evidence), score=100, verification="controlled_real_inbound", status="needs_evidence", subject=ACCEPTANCE_SUBJECT, body="Provider-backed controlled real Gmail inbound acceptance test.", gmail_message_id=message_id, gmail_thread_id=thread_id, sent_at=now)
    db.session.add(lead); db.session.commit()
    qualification = oa._store_qualification(lead, {})
    if qualification.get("ok") is not True:
        return {"ok": False, "lead_id": lead.id, "stage": "qualification_failed", "qualification": qualification}
    lead.status = "sent"; lead.updated_at = now; db.session.commit()
    return {"ok": True, "lead_id": lead.id, "stage": "registered", "thread_id": thread_id, "message_id": message_id, "qualification": {"status": qualification.get("status"), "reason_codes": qualification.get("reason_codes") or []}}


@app.route("/operator/real-inbound", methods=["GET"])
def operator_real_inbound_page():
    if not oa._operator_session_authorized(): return redirect(url_for("operator_login"), 303)
    csrf = oa._csrf_token()
    return Response(f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Real Inbound Gmail Test</title><style>body{{font-family:system-ui,-apple-system,sans-serif;background:#0b1020;color:#e8ecf5;margin:0;padding:22px}}.box{{max-width:800px;margin:auto;background:#141b2d;border:1px solid #27304a;border-radius:14px;padding:20px}}button,a{{display:inline-block;background:#fff;color:#101526;border:0;border-radius:9px;padding:13px 16px;font-weight:800;text-decoration:none;margin:4px}}pre{{white-space:pre-wrap;word-break:break-word;background:#080c18;padding:14px;border-radius:9px;min-height:120px}}</style></head><body><div class="box"><a href="/operator">← Command Center</a><h2>Real Inbound Gmail Acceptance</h2><p>Uses actual Gmail thread evidence. No synthetic reply injection.</p><button id="reg">REGISTER ACCEPTANCE THREAD</button><button id="run">PROCESS REAL INBOUND REPLY</button><pre id="report">Ready.</pre></div><script>const p=document.getElementById('report');async function call(path,body){{const r=await fetch(path,{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CSRF-Token':'{csrf}'}},body:JSON.stringify(body||{{}})}});const d=await r.json();p.textContent=JSON.stringify(d,null,2);return d}}document.getElementById('reg').onclick=()=>call('/api/operator/real-inbound/register',{{message_id:'1a0dfc64062b2cd6',thread_id:'1a0dfc64062b2cd6'}});document.getElementById('run').onclick=()=>call('/api/operator/real-inbound',{{}});</script></body></html>''', mimetype="text/html")


@app.route("/api/operator/real-inbound/register", methods=["POST"])
def operator_real_inbound_register():
    if not oa._operator_session_authorized(): return jsonify({"ok": False, "error": "unauthorized"}), 401
    if not oa._csrf_valid(request): return jsonify({"ok": False, "error": "csrf_failed"}), 403
    result = _register_acceptance_lead(request.get_json(silent=True) or {})
    return jsonify(result), 200 if result.get("ok") else 409


@app.route("/api/operator/real-inbound", methods=["POST"])
def operator_real_inbound_run():
    if not oa._operator_session_authorized(): return jsonify({"ok": False, "error": "unauthorized"}), 401
    if not oa._csrf_valid(request): return jsonify({"ok": False, "error": "csrf_failed"}), 403
    result = scan_real_inbound_replies()
    return jsonify(result), 200 if result.get("ok") else 502
