from datetime import datetime
import json


def register_prospect_model(db):
    """Register and return the Prospect SQLAlchemy model for the host app."""

    class Prospect(db.Model):
        __tablename__ = "prospect"

        id = db.Column(db.Integer, primary_key=True)
        company = db.Column(db.String(200), nullable=False, index=True)
        website = db.Column(db.Text, default="")
        email = db.Column(db.String(254), default="", index=True)
        phone = db.Column(db.String(50), default="")
        contact_name = db.Column(db.String(200), default="")
        contact_title = db.Column(db.String(160), default="")
        source = db.Column(db.String(120), default="")
        source_url = db.Column(db.Text, default="")
        city = db.Column(db.String(120), default="")
        state = db.Column(db.String(80), default="")
        industry = db.Column(db.String(120), default="")

        hiring_signal = db.Column(db.Boolean, default=False)
        hiring_roles = db.Column(db.Text, default="[]")
        review_count = db.Column(db.Integer, default=0)
        google_rating = db.Column(db.Float)
        locations_count = db.Column(db.Integer, default=1)
        high_lead_volume_signal = db.Column(db.Boolean, default=False)
        manual_followup_signal = db.Column(db.Boolean, default=False)
        crm_need_signal = db.Column(db.Boolean, default=False)
        growth_signal = db.Column(db.Boolean, default=False)
        automation_opportunities = db.Column(db.Text, default="[]")
        evidence = db.Column(db.Text, default="[]")

        score = db.Column(db.Integer, default=0, index=True)
        score_band = db.Column(db.String(30), default="poor")
        score_reason = db.Column(db.Text, default="")
        status = db.Column(db.String(50), default="new", index=True)

        created_at = db.Column(db.DateTime, default=datetime.utcnow)
        updated_at = db.Column(
            db.DateTime,
            default=datetime.utcnow,
            onupdate=datetime.utcnow,
        )

        def to_dict(self):
            return {
                "id": self.id,
                "company": self.company,
                "website": self.website,
                "email": self.email,
                "phone": self.phone,
                "contact_name": self.contact_name,
                "contact_title": self.contact_title,
                "source": self.source,
                "source_url": self.source_url,
                "city": self.city,
                "state": self.state,
                "industry": self.industry,
                "hiring_signal": bool(self.hiring_signal),
                "hiring_roles": _json_list(self.hiring_roles),
                "review_count": self.review_count or 0,
                "google_rating": self.google_rating,
                "locations_count": self.locations_count or 1,
                "high_lead_volume_signal": bool(self.high_lead_volume_signal),
                "manual_followup_signal": bool(self.manual_followup_signal),
                "crm_need_signal": bool(self.crm_need_signal),
                "growth_signal": bool(self.growth_signal),
                "automation_opportunities": _json_list(self.automation_opportunities),
                "evidence": _json_list(self.evidence),
                "score": self.score or 0,
                "score_band": self.score_band,
                "score_reason": self.score_reason,
                "status": self.status,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            }

    return Prospect


def _json_list(value):
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def score_band(score):
    score = max(0, min(100, int(score or 0)))
    if score >= 80:
        return "hot"
    if score >= 60:
        return "strong"
    if score >= 40:
        return "possible"
    return "poor"


def score_prospect(data):
    """Evidence-based deterministic 0-100 scoring before AI explanation/enrichment."""
    score = 0
    reasons = []

    hiring_signal = bool(data.get("hiring_signal"))
    growth_signal = bool(data.get("growth_signal"))
    high_lead_volume_signal = bool(data.get("high_lead_volume_signal"))
    manual_followup_signal = bool(data.get("manual_followup_signal"))
    crm_need_signal = bool(data.get("crm_need_signal"))

    review_count = _safe_int(data.get("review_count"), 0)
    locations_count = max(1, _safe_int(data.get("locations_count"), 1))
    opportunities = data.get("automation_opportunities") or []
    evidence = data.get("evidence") or []

    if hiring_signal:
        score += 20
        reasons.append("active hiring signal")

    if growth_signal:
        score += 15
        reasons.append("growth signal")

    if high_lead_volume_signal:
        score += 20
        reasons.append("high lead-volume signal")

    if manual_followup_signal:
        score += 15
        reasons.append("manual follow-up pain signal")

    if crm_need_signal:
        score += 15
        reasons.append("CRM/automation need signal")

    if review_count >= 500:
        score += 8
        reasons.append("500+ public reviews")
    elif review_count >= 150:
        score += 6
        reasons.append("150+ public reviews")
    elif review_count >= 50:
        score += 3
        reasons.append("50+ public reviews")

    if locations_count >= 3:
        score += 5
        reasons.append("multiple locations")
    elif locations_count == 2:
        score += 3
        reasons.append("two locations")

    if isinstance(opportunities, list):
        opportunity_points = min(10, len([x for x in opportunities if x]) * 2)
        if opportunity_points:
            score += opportunity_points
            reasons.append("documented automation opportunities")

    # Require some real evidence for elite scores. This prevents weak, guessed leads
    # from appearing as 80+ just because boolean fields were populated carelessly.
    evidence_count = len([x for x in evidence if x]) if isinstance(evidence, list) else 0
    if evidence_count == 0:
        score = min(score, 69)
    elif evidence_count == 1:
        score = min(score, 79)

    score = max(0, min(100, score))
    band = score_band(score)

    return {
        "score": score,
        "score_band": band,
        "qualified": score >= 80,
        "reason": ", ".join(reasons) if reasons else "insufficient buying-signal evidence",
    }


def apply_score(prospect):
    """Score a Prospect model instance in place and return the scoring result."""
    result = score_prospect(prospect.to_dict())
    prospect.score = result["score"]
    prospect.score_band = result["score_band"]
    prospect.score_reason = result["reason"]
    return result


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
