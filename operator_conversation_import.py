"""Import and execute a controlled real Gmail conversation through DOE gates."""
import os
from datetime import datetime
from email.utils import getaddresses,parseaddr
import requests
from flask import Response,jsonify,request,redirect
from app import app,db
import gmail_connect
import outreach_automation as oa

CONTROLLED_RECIPIENTS={"neyolabs@gmail.com","jolleysalesfloor@gmail.com"}

def import_and_process(data):
    recipient=oa.normalize_email(data.get("recipient"))
    thread_id=oa._clean(data.get("thread_id"),255)
    message_id=oa._clean(data.get("message_id"),255)
    if recipient not in CONTROLLED_RECIPIENTS or not thread_id or not message_id:
        return {"ok":False,"error":"controlled_recipient_and_provider_ids_required"}
    sender=oa.normalize_email(os.getenv("GMAIL_FROM_EMAIL"))
    if not sender:return {"ok":False,"error":"sender_identity_required"}
    # Verify the original message with the app's own Google credentials.
    try:
        r=requests.get(f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}",headers={"Authorization":f"Bearer {gmail_connect.gmail_access_token()}"},params={"format":"full"},timeout=20)
        if not r.ok:return {"ok":False,"error":"gmail_thread_read_failed"}
        messages=r.json().get("messages") or []
    except Exception:
        return {"ok":False,"error":"gmail_thread_read_failed"}
    original=next((m for m in messages if m.get("id")==message_id),None)
    if not original:return {"ok":False,"error":"original_message_not_in_thread"}
    headers={str(x.get("name") or "").lower():str(x.get("value") or "") for x in (original.get("payload") or {}).get("headers") or []}
    recipients={a.lower() for _,a in getaddresses([headers.get("to","")])}
    if parseaddr(headers.get("from",""))[1].lower()!=sender or recipients!={recipient}:
        return {"ok":False,"error":"provider_envelope_mismatch"}
    lead=oa.OutreachLead.query.filter_by(gmail_thread_id=thread_id).first()
    if lead and oa.normalize_email(lead.contact_email)!=recipient:
        return {"ok":False,"error":"tracked_recipient_mismatch"}
    if lead and lead.status=="booked":
        return {"ok":True,"stage":"already_booked","lead_id":lead.id,"duplicate_suppressed":True}
    if not lead:
        now=datetime.utcnow();source_url="https://gmail.com/"
        evidence=[{"url":source_url,"email":recipient,"title":"Controlled provider-backed correspondence","snippet":"Operator-authorized contact verified against Gmail From/To and message/thread receipts.","observed_at":now.isoformat()+"Z","message_id":message_id,"thread_id":thread_id}]
        lead=oa.OutreachLead(company=oa._clean(data.get("company") or "Controlled conversation",300),contact_email=recipient,source_url=source_url,evidence_json=oa._canonical_json(evidence),verification="controlled_real_inbound",score=100,status="needs_evidence",subject=oa._clean(headers.get("subject"),160),body=oa.message_to_evidence(original).get("text") or "Provider-backed original message",gmail_message_id=message_id,gmail_thread_id=thread_id,sent_at=now)
        db.session.add(lead);db.session.commit()
        qualified=oa._store_qualification(lead,{})
        if not qualified.get("ok"):return {"ok":False,"stage":"qualification_blocked","qualification":qualified,"lead_id":lead.id}
        lead.status="sent";db.session.commit()
    reply=oa._gmail_thread_reply_state(thread_id)
    if not reply.get("ok"):return {"ok":False,"stage":"reply_check_failed","lead_id":lead.id}
    # Only the identified recipient's actual incoming messages may route booking.
    reply["reply_evidence"]=[x for x in reply.get("reply_evidence") or [] if oa.normalize_email(x.get("from_email"))==recipient]
    if not reply["reply_evidence"]:
        return {"ok":True,"stage":"awaiting_real_reply","lead_id":lead.id}
    oa._persist_reply_evidence(lead,reply)
    routed=oa._route_persisted_reply(lead,reply,datetime.utcnow())
    lead.updated_at=datetime.utcnow();db.session.commit()
    oa._audit_actor(lead.id,"controlled_conversation_import",{"thread_id":thread_id,"original_message_id":message_id},{"stage":routed.get("stage"),"reply_message_ids":[x["message_id"] for x in reply["reply_evidence"]]},"operator")
    db.session.commit()
    return {"ok":routed.get("ok") is True,"lead_id":lead.id,"stage":routed.get("stage"),"thread_id":thread_id,"real_reply_message_ids":[x["message_id"] for x in reply["reply_evidence"]],"result":routed}

@app.route("/api/operator/conversation-import",methods=["POST"])
def conversation_import():
    if not oa._operator_session_authorized():return jsonify(ok=False,error="unauthorized"),401
    if not oa._csrf_ok():return jsonify(ok=False,error="csrf_failed"),403
    result=import_and_process(request.get_json(silent=True) or {})
    return jsonify(result),200 if result.get("ok") else 409

@app.route("/operator/conversation-import",methods=["GET"])
def conversation_import_page():
    if not oa._operator_session_authorized():return redirect("/operator/login",303)
    csrf=oa._csrf_token()
    return Response(f'''<!doctype html><html><head><title>Import controlled conversation</title><style>body{{font-family:system-ui;padding:25px;background:#0b1020;color:white}}label{{display:block;margin:15px 0}}input{{display:block;width:460px;padding:10px}}button{{padding:12px}}pre{{white-space:pre-wrap}}</style></head><body><h1>Continue a real conversation in AutoMake</h1><p>Verifies the original Gmail receipt and real incoming reply, then runs qualification, availability, booking and confirmation. Controlled contacts only. Default meeting length: 30 minutes; timezone: America/New_York.</p><label>Company<input id="company" value="Neo Labs"></label><label>Recipient<input id="recipient" value="neyolabs@gmail.com"></label><label>Thread ID<input id="thread"></label><label>Original message ID<input id="message"></label><button id="run">IMPORT AND PROCESS REAL REPLY</button><pre id="report">Ready.</pre><script>document.getElementById('run').onclick=async()=>{{const b=document.getElementById('run');b.disabled=true;const p=document.getElementById('report');p.textContent='Running through AutoMake workflow…';try{{const r=await fetch('/api/operator/conversation-import',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CSRF-Token':'{csrf}'}},body:JSON.stringify({{company:document.getElementById('company').value,recipient:document.getElementById('recipient').value,thread_id:document.getElementById('thread').value,message_id:document.getElementById('message').value}})}});p.textContent=JSON.stringify(await r.json(),null,2)}}catch(e){{p.textContent='Stopped: '+e.message}}finally{{b.disabled=false}}}};</script></body></html>''',mimetype="text/html")
