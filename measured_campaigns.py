"""Persistent campaign tracking foundation for existing AutoMake AI.

No email sends or provider calls. Explicit operator authorization is required.
Multi-customer activation requires a real authenticated principal mapping; this
module does not claim that the legacy operator session is tenant authentication.
"""
import json
import secrets
from datetime import datetime, timezone, timedelta
from flask import jsonify, request
from app import app, db
from outreach_automation import _operator_session_authorized, _csrf_ok

class MeasuredCampaign(db.Model):
    __tablename__ = "measured_campaign"
    id = db.Column(db.String(48), primary_key=True)
    owner_key = db.Column(db.String(80), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    location = db.Column(db.String(180), nullable=False)
    industry = db.Column(db.String(300), nullable=False)
    target_count = db.Column(db.Integer, nullable=False, default=100)
    qualified_target = db.Column(db.Integer, nullable=False, default=25)
    outreach_limit = db.Column(db.Integer, nullable=False, default=25)
    status = db.Column(db.String(30), nullable=False, default="draft")
    outbound_enabled = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    window_ends_at = db.Column(db.DateTime, nullable=False)

class MeasuredCampaignLead(db.Model):
    __tablename__ = "measured_campaign_lead"
    campaign_id = db.Column(db.String(48), db.ForeignKey("measured_campaign.id"), primary_key=True)
    lead_id = db.Column(db.Integer, primary_key=True)
    reviewed_status = db.Column(db.String(30), nullable=False, default="candidate")
    evidence_json = db.Column(db.Text, nullable=False, default="[]")
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

def _owner():
    # Only single-operator scope is currently supported. Do not invent tenant IDs.
    from os import getenv
    return (getenv("AUTOMAKE_OPERATOR_OWNER_KEY") or "").strip()

def _authorized():
    return _operator_session_authorized() and bool(_owner())

def _view(c):
    return {"id":c.id,"name":c.name,"location":c.location,"industry":c.industry,
            "target_count":c.target_count,"qualified_target":c.qualified_target,
            "outreach_limit":c.outreach_limit,"status":c.status,
            "outbound_enabled":c.outbound_enabled,"created_at":c.created_at.isoformat(),
            "window_ends_at":c.window_ends_at.isoformat()}

@app.route("/api/chat/measured-campaigns",methods=["GET","POST"])
def measured_campaigns():
    if not _authorized():
        return jsonify({"ok":False,"error":"Authenticated operator account mapping required"}),401
    owner=_owner()
    if request.method=="GET":
        rows=MeasuredCampaign.query.filter_by(owner_key=owner).order_by(MeasuredCampaign.created_at.desc()).limit(50).all()
        return jsonify({"ok":True,"campaigns":[_view(c) for c in rows]})
    if not _csrf_ok():
        return jsonify({"ok":False,"error":"csrf_failed"}),403
    data=request.get_json(silent=True) or {}
    name=str(data.get("name") or "Hampton Roads Business Automation").strip()[:160]
    loc=str(data.get("location") or "Hampton Roads, Virginia").strip()[:180]
    industry=str(data.get("industry") or "HVAC, electrical, plumbing").strip()[:300]
    try:
        target=int(data.get("target_count",100))
        qualified=int(data.get("qualified_target",25))
        limit=int(data.get("outreach_limit",25))
    except (ValueError,TypeError):
        return jsonify({"ok":False,"error":"invalid_targets"}),400
    if not name or not loc or not industry or not (1<=target<=1000 and 0<=qualified<=target and 0<=limit<=target):
        return jsonify({"ok":False,"error":"invalid_campaign_configuration"}),400
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    c=MeasuredCampaign(id=secrets.token_urlsafe(24),owner_key=owner,name=name,location=loc,
        industry=industry,target_count=target,qualified_target=qualified,
        outreach_limit=limit,window_ends_at=now+timedelta(days=14),status="draft",outbound_enabled=False)
    db.session.add(c)
    db.session.commit()
    return jsonify({"ok":True,"campaign":_view(c)}),201

@app.route("/api/chat/measured-campaigns/<campaign_id>/metrics",methods=["GET"])
def measured_campaign_metrics(campaign_id):
    if not _authorized():
        return jsonify({"ok":False,"error":"Authenticated operator account mapping required"}),401
    campaign=MeasuredCampaign.query.filter_by(id=campaign_id,owner_key=_owner()).first()
    if not campaign:
        return jsonify({"ok":False,"error":"campaign_not_found"}),404
    linked=MeasuredCampaignLead.query.filter_by(campaign_id=campaign.id)
    count=linked.count()
    qualified=linked.filter_by(reviewed_status="qualified").count()
    return jsonify({"ok":True,"campaign":_view(campaign),"observed":{"linked_leads":count,"qualified":qualified},
                    "missing":["research_receipts","delivery_receipts","booking_receipts","customer_conversions"],
                    "qualification_rate":None,
                    "explanation":"Research denominator unavailable. No conversion rate estimated."})

# Register models at import; a reviewed migration must create tables before
# this module is enabled on a live database. No implicit create_all.
