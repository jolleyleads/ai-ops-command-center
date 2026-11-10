"""Unit tests for channel-specific readiness. No production sends."""
from datetime import datetime, timezone
from src.qualification import qualify_lead


def _validated():
    return {
        "company_name": "Example Business",
        "website": "https://example.test",
        "website_source_url": "https://example.test/about",
        "phone": "(757) 555-0100",
        "phone_source_url": "https://example.test/contact",
        "evidence": [{"url": "https://example.test/contact",
                      "title": "Example Business Contact",
                      "observed_at": datetime.now(timezone.utc).isoformat()}],
    }


def test_source_bound_phone_can_be_manual_call_ready_without_email():
    receipt = qualify_lead(_validated())
    assert receipt["ok"] is True
    assert receipt["call_ready"] is True
    assert receipt["email_outreach_ready"] is False


def test_named_email_requirement_does_not_block_manual_call_readiness():
    receipt = qualify_lead(_validated(), context={"require_decision_maker": True})
    assert receipt["ok"] is False
    assert "NAMED_DECISION_MAKER_EMAIL_REQUIRED" in receipt["reason_codes"]
    assert receipt["call_ready"] is True
    assert receipt["email_outreach_ready"] is False


def test_missing_phone_cannot_be_marked_call_ready():
    item = _validated()
    item.pop("phone")
    item.pop("phone_source_url")
    receipt = qualify_lead(item)
    assert receipt["call_ready"] is False


def test_unverified_identity_is_never_call_ready():
    receipt = qualify_lead(_validated(), verification_ok=False)
    assert receipt["call_ready"] is False


def test_duplicate_cannot_be_call_ready():
    receipt = qualify_lead(_validated(), context={"duplicate": True})
    assert receipt["call_ready"] is False
