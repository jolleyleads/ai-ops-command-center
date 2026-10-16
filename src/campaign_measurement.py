"""Evidence-aware campaign scorecards. No provider calls or outreach side effects."""
from __future__ import annotations

WEIGHTS = {
    "buying_signal": 30, "business_relevance": 20,
    "decision_maker": 15, "contact_verification": 15,
    "geographic_fit": 10, "evidence_freshness": 10,
}

def score_lead(evidence: dict) -> dict:
    """Score only explicitly supported criteria, separately from hard qualification."""
    evidence = evidence if isinstance(evidence, dict) else {}
    breakdown = {}
    for criterion, maximum in WEIGHTS.items():
        item = evidence.get(criterion)
        # A true evidence receipt is necessary; freeform AI assertions score zero.
        verified = isinstance(item, dict) and item.get("supported") is True and bool(item.get("source_url"))
        raw = item.get("points", 0) if verified else 0
        points = min(maximum, max(0, int(raw))) if type(raw) is int else 0
        breakdown[criterion] = {"points": points, "maximum": maximum, "supported": verified}
    return {"score": sum(v["points"] for v in breakdown.values()), "breakdown": breakdown,
            "qualification_independent": True}

def rate(numerator: int, denominator: int):
    """None means insufficient denominator, never an invented 0% rate."""
    if not isinstance(numerator, int) or not isinstance(denominator, int):
        return None
    if denominator <= 0 or numerator < 0 or numerator > denominator:
        return None
    return round(100 * numerator / denominator, 2)

def campaign_metrics(counts: dict) -> dict:
    counts = counts if isinstance(counts, dict) else {}
    def count(key):
        value = counts.get(key, 0)
        return value if type(value) is int and value >= 0 else 0
    researched, qualified = count("researched"), count("qualified")
    sent, delivered, replies = count("sent"), count("delivered"), count("replies")
    positive, booked, customers = count("positive_replies"), count("booked"), count("customers")
    contacted = count("contacted")
    return {
        "qualification_rate": rate(qualified, researched),
        "reply_rate_per_delivered": rate(replies, delivered) if counts.get("delivery_evidence") is True else None,
        "reply_rate_per_sent": rate(replies, sent),
        "positive_reply_rate_per_sent": rate(positive, sent),
        "booking_rate_per_sent": rate(booked, sent),
        "contact_to_customer_rate": rate(customers, contacted),
        "rates_are_percentages": True,
        "source": "persisted_counts_required",
    }
