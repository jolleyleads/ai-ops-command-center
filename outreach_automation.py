import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from flask import jsonify, request

from app import app, gmail_access_token, send_gmail
from src.services import run_ai

DB_PATH = Path(os.getenv("OUTREACH_DB_PATH", "/tmp/ai_ops_outreach.sqlite3"))
AUTO_SEND_MIN_SCORE = int(os.getenv("OUTREACH_AUTO_SEND_MIN_SCORE", "75"))
REVIEW_MIN_SCORE = int(os.getenv("OUTREACH_REVIEW_MIN_SCORE", "60"))
FIRST_FOLLOWUP_DAYS = int(os.getenv("OUTREACH_FIRST_FOLLOWUP_DAYS", "3"))
SECOND_FOLLOWUP_DAYS = int(os.getenv("OUTREACH_SECOND_FOLLOWUP_DAYS", "4"))
MAX_FOLLOWUPS = int(os.getenv("OUTREACH_MAX_FOLLOWUPS", "2"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _clean(value: Any, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS outreach_leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            contact_email TEXT,
            contact_name TEXT,
            location TEXT,
            source_url TEXT,
            evidence_json TEXT,
            score INTEGER NOT NULL,
            verification TEXT,
            status TEXT NOT NULL,
            subject TEXT,
            body TEXT,
            gmail_message_id TEXT,
            gmail_thread_id TEXT,
            sent_at TEXT,
            follow_up_due_at TEXT,
            follow_up_count INTEGER NOT NULL DEFAULT 0,
            replied_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _row(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    try:
        data["evidence"] = json.loads(data.pop("evidence_json") or "[]")
    except Exception:
        data["evidence"] = []
    return data


def _rank_status(score: int) -> str:
    if score >= AUTO_SEND_MIN_SCORE:
        return "qualified"
    if score >= REVIEW_MIN_SCORE:
        return "review"
    return "rejected"


def _draft_email(lead: Dict[str, Any], follow_up_number: int = 0) -> Dict[str, Any]:
    company = _clean(lead.get("company"), 300)
    evidence = lead.get("evidence") or []
    location = _clean(lead.get("location"), 200)
    previous_subject = _clean(lead.get("subject"), 500)
    previous_body = _clean(lead.get("body"), 4000)

    if follow_up_number:
        instructions = (
            "Write a concise B2B follow-up email. Use only facts in the supplied workflow data. "
            "Do not invent names, needs, credentials, dates, or claims. Return strict JSON with keys subject and body."
        )
        prompt = (
            f"Write follow-up #{follow_up_number} to {company}. Keep the same subject when appropriate. "
            "Reference the prior outreach naturally, be professional, and ask for a simple reply or brief call. "
            "Do not claim they still need help unless the evidence says so."
        )
        workflow_data = {
            "company": company,
            "location": location,
            "evidence": evidence,
            "previous_subject": previous_subject,
            "previous_body": previous_body,
        }
    else:
        instructions = (
            "Write a concise personalized B2B outreach email for a verified contractor lead. "
            "Use only facts supplied in workflow data. Never invent a contact name, company need, license, project, or claim. "
            "Return strict JSON with keys subject and body."
        )
        prompt = (
            "Draft a short first-touch email offering Master Electrician / qualifying-agent / permit-pulling support only when "
            "the supplied evidence supports that need. Mention one specific verified signal, avoid hype, and end with a low-friction call to action."
        )
        workflow_data = {
            "company": company,
            "location": location,
            "score": lead.get("score"),
            "verification": lead.get("verification"),
            "evidence": evidence,
            "source_url": lead.get("source_url"),
        }

    result = run_ai(
        prompt=f"{prompt}\n\nWORKFLOW DATA:\n{json.dumps(workflow_data, indent=2)}",
        instructions=instructions,
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "OpenAI drafting failed."}

    raw = _clean(result.get("output"), 8000)
    try:
        parsed = json.loads(raw)
    except Exception:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return {"ok": False, "error": "OpenAI did not return valid JSON."}
        try:
            parsed = json.loads(raw[start:end + 1])
        except Exception:
            return {"ok": False, "error": "OpenAI did not return valid JSON."}

    subject = _clean(parsed.get("subject"), 500)
    body = _clean(parsed.get("body"), 6000)
    if not subject or not body:
        return {"ok": False, "error": "OpenAI response was missing subject or body."}
    return {"ok": True, "subject": subject, "body": body, "model": result.get("model")}


def _gmail_send(to_email: str, subject: str, body: str, thread_id: str = "") -> Dict[str, Any]:
    try:
        if thread_id:
            token = gmail_access_token()
            from email.message import EmailMessage
            import base64

            msg = EmailMessage()
            msg["To"] = to_email
            msg["Subject"] = subject
            from_email = os.environ.get("GMAIL_FROM_EMAIL", "")
            if from_email:
                msg["From"] = from_email
            msg.set_content(body)
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")
            response = requests.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"raw": raw, "threadId": thread_id},
                timeout=30,
            )
            if not response.ok:
                return {"ok": False, "error": f"Gmail error {response.status_code}: {response.text[:500]}"}
            data = response.json()
        else:
            data = send_gmail(to_email, subject, body)

        return {
            "ok": True,
            "message_id": data.get("id"),
            "thread_id": data.get("threadId") or thread_id,
            "raw": data,
        }
    except Exception as exc:
        return {"ok": False, "error": _clean(exc, 1000)}


def _gmail_thread_has_reply(thread_id: str) -> Dict[str, Any]:
    try:
        token = gmail_access_token()
        response = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"format": "metadata", "metadataHeaders": ["From", "To"]},
            timeout=30,
        )
        if not response.ok:
            return {"ok": False, "replied": False, "error": f"Gmail thread lookup failed {response.status_code}: {response.text[:500]}"}
        data = response.json()
        messages = data.get("messages") or []
        if len(messages) <= 1:
            return {"ok": True, "replied": False, "raw": data}

        sender = (os.environ.get("GMAIL_FROM_EMAIL") or "").lower().strip()
        replied = False
        for message in messages[1:]:
            headers = {
                str(h.get("name") or "").lower(): str(h.get("value") or "")
                for h in ((message.get("payload") or {}).get("headers") or [])
            }
            from_value = headers.get("from", "").lower()
            if sender:
                if sender not in from_value:
                    replied = True
                    break
            else:
                replied = True
                break
        return {"ok": True, "replied": replied, "raw": data}
    except Exception as exc:
        return {"ok": False, "replied": False, "error": _clean(exc, 1000)}


@app.route("/api/outreach/leads", methods=["POST"])
def create_outreach_lead():
    data = request.get_json(silent=True) or {}
    company = _clean(data.get("company") or data.get("title") or data.get("name"), 300)
    if not company:
        return jsonify({"error": "company is required"}), 400
    try:
        score = int(data.get("score") if data.get("score") is not None else data.get("intent_score", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "score must be an integer"}), 400
    score = max(0, min(score, 100))
    status = _rank_status(score)
    now = _iso(_now())
    evidence = data.get("evidence") if isinstance(data.get("evidence"), list) else []

    conn = _db()
    cur = conn.execute(
        """
        INSERT INTO outreach_leads
        (company, contact_email, contact_name, location, source_url, evidence_json, score, verification, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            company,
            _clean(data.get("contact_email") or data.get("email"), 500),
            _clean(data.get("contact_name"), 300),
            _clean(data.get("location"), 300),
            _clean(data.get("source_url") or data.get("url") or data.get("website"), 1500),
            json.dumps(evidence),
            score,
            _clean(data.get("verification"), 100),
            status,
            now,
            now,
        ),
    )
    conn.commit()
    lead = _row(conn.execute("SELECT * FROM outreach_leads WHERE id=?", (cur.lastrowid,)).fetchone())
    conn.close()
    return jsonify({"lead": lead, "auto_send_eligible": status == "qualified"}), 201


@app.route("/api/outreach/leads/<int:lead_id>/draft", methods=["POST"])
def draft_outreach(lead_id: int):
    conn = _db()
    row = conn.execute("SELECT * FROM outreach_leads WHERE id=?", (lead_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "lead not found"}), 404
    lead = _row(row)
    if lead["status"] == "rejected":
        conn.close()
        return jsonify({"error": "lead is below the review threshold and cannot be auto-drafted"}), 409
    drafted = _draft_email(lead)
    if not drafted.get("ok"):
        conn.execute("UPDATE outreach_leads SET last_error=?, updated_at=? WHERE id=?", (drafted.get("error"), _iso(_now()), lead_id))
        conn.commit(); conn.close()
        return jsonify(drafted), 502
    conn.execute(
        "UPDATE outreach_leads SET subject=?, body=?, status=?, last_error=NULL, updated_at=? WHERE id=?",
        (drafted["subject"], drafted["body"], "drafted", _iso(_now()), lead_id),
    )
    conn.commit()
    updated = _row(conn.execute("SELECT * FROM outreach_leads WHERE id=?", (lead_id,)).fetchone())
    conn.close()
    return jsonify({"ok": True, "lead": updated, "model": drafted.get("model")})


@app.route("/api/outreach/leads/<int:lead_id>/send", methods=["POST"])
def send_outreach(lead_id: int):
    conn = _db()
    row = conn.execute("SELECT * FROM outreach_leads WHERE id=?", (lead_id,)).fetchone()
    if not row:
        conn.close(); return jsonify({"error": "lead not found"}), 404
    lead = _row(row)
    if lead["score"] < AUTO_SEND_MIN_SCORE:
        conn.close(); return jsonify({"error": f"lead score must be at least {AUTO_SEND_MIN_SCORE} for automatic send"}), 409
    if not lead.get("contact_email"):
        conn.close(); return jsonify({"error": "verified contact_email is required before send"}), 409
    if not lead.get("subject") or not lead.get("body"):
        drafted = _draft_email(lead)
        if not drafted.get("ok"):
            conn.close(); return jsonify(drafted), 502
        lead["subject"], lead["body"] = drafted["subject"], drafted["body"]
    sent = _gmail_send(lead["contact_email"], lead["subject"], lead["body"])
    if not sent.get("ok"):
        conn.execute("UPDATE outreach_leads SET last_error=?, updated_at=? WHERE id=?", (sent.get("error"), _iso(_now()), lead_id)); conn.commit(); conn.close()
        return jsonify(sent), 502
    sent_at = _now(); due = sent_at + timedelta(days=FIRST_FOLLOWUP_DAYS)
    conn.execute(
        """UPDATE outreach_leads SET subject=?, body=?, gmail_message_id=?, gmail_thread_id=?, sent_at=?, follow_up_due_at=?,
        status='sent', last_error=NULL, updated_at=? WHERE id=?""",
        (lead["subject"], lead["body"], sent.get("message_id"), sent.get("thread_id"), _iso(sent_at), _iso(due), _iso(sent_at), lead_id),
    )
    conn.commit(); updated = _row(conn.execute("SELECT * FROM outreach_leads WHERE id=?", (lead_id,)).fetchone()); conn.close()
    return jsonify({"ok": True, "lead": updated})


@app.route("/api/outreach/process-followups", methods=["POST"])
def process_followups():
    now = _now(); conn = _db()
    rows = conn.execute(
        "SELECT * FROM outreach_leads WHERE status IN ('sent','followup_sent') AND follow_up_due_at IS NOT NULL AND follow_up_due_at <= ? AND replied_at IS NULL",
        (_iso(now),),
    ).fetchall()
    processed = []
    for row in rows:
        lead = _row(row); lead_id = lead["id"]
        if not lead.get("gmail_thread_id"):
            processed.append({"id": lead_id, "status": "skipped", "reason": "missing Gmail thread id"}); continue
        reply = _gmail_thread_has_reply(lead["gmail_thread_id"])
        if not reply.get("ok"):
            conn.execute("UPDATE outreach_leads SET last_error=?, updated_at=? WHERE id=?", (reply.get("error"), _iso(now), lead_id))
            processed.append({"id": lead_id, "status": "error", "error": reply.get("error")}); continue
        if reply.get("replied"):
            conn.execute("UPDATE outreach_leads SET status='responded', replied_at=?, follow_up_due_at=NULL, last_error=NULL, updated_at=? WHERE id=?", (_iso(now), _iso(now), lead_id))
            processed.append({"id": lead_id, "status": "responded"}); continue
        count = int(lead.get("follow_up_count") or 0)
        if count >= MAX_FOLLOWUPS:
            conn.execute("UPDATE outreach_leads SET status='completed_no_reply', follow_up_due_at=NULL, updated_at=? WHERE id=?", (_iso(now), lead_id))
            processed.append({"id": lead_id, "status": "completed_no_reply"}); continue
        next_number = count + 1
        drafted = _draft_email(lead, follow_up_number=next_number)
        if not drafted.get("ok"):
            conn.execute("UPDATE outreach_leads SET last_error=?, updated_at=? WHERE id=?", (drafted.get("error"), _iso(now), lead_id))
            processed.append({"id": lead_id, "status": "error", "error": drafted.get("error")}); continue
        sent = _gmail_send(lead["contact_email"], drafted["subject"], drafted["body"], lead["gmail_thread_id"])
        if not sent.get("ok"):
            conn.execute("UPDATE outreach_leads SET last_error=?, updated_at=? WHERE id=?", (sent.get("error"), _iso(now), lead_id))
            processed.append({"id": lead_id, "status": "error", "error": sent.get("error")}); continue
        due = now + timedelta(days=SECOND_FOLLOWUP_DAYS)
        conn.execute(
            """UPDATE outreach_leads SET subject=?, body=?, gmail_message_id=?, gmail_thread_id=?, follow_up_count=?, follow_up_due_at=?,
            status='followup_sent', last_error=NULL, updated_at=? WHERE id=?""",
            (drafted["subject"], drafted["body"], sent.get("message_id"), sent.get("thread_id") or lead["gmail_thread_id"], next_number, _iso(due), _iso(now), lead_id),
        )
        processed.append({"id": lead_id, "status": "followup_sent", "follow_up_count": next_number})
    conn.commit(); conn.close()
    return jsonify({"ok": True, "processed_count": len(processed), "processed": processed})


@app.route("/api/outreach/leads", methods=["GET"])
def list_outreach_leads():
    conn = _db(); rows = conn.execute("SELECT * FROM outreach_leads ORDER BY id DESC LIMIT 200").fetchall(); conn.close()
    return jsonify({"leads": [_row(r) for r in rows]})
