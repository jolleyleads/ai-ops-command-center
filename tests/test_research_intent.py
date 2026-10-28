from src.research_intent import parse_research_request, format_research_results


def test_phone_request_is_research_only():
    intent = parse_research_request("Give me 20 HVAC companies with decision-makers phone numbers")
    assert intent["fields"] == ["company", "decision_maker", "phone"]
    assert intent["count"] == 20
    assert intent["research_only"] and not intent["send_authorized"]


def test_email_followup_reuses_results():
    intent = parse_research_request("Find their emails", {"count": 20})
    assert intent["fields"] == ["company", "email"]
    assert intent["reuse_previous_results"]
    assert intent["count"] == 20


def test_partial_contacts_still_display():
    intent = parse_research_request("Give me 2 companies with phone numbers")
    rows = [{"company": "Example HVAC", "contact_phone": "757-555-0100", "website": "https://example.com"},
            {"company": "Second HVAC", "website": "https://second.example"}]
    result = format_research_results(rows, intent)
    assert len(result) == 2
    assert result[0]["phone_type"] == "business_or_unconfirmed"
    assert result[1]["phone"] is None


def test_outreach_request_does_not_grant_send_permission():
    intent = parse_research_request("Send my campaign to them", {"count": 10})
    assert not intent["research_only"]
    assert not intent["send_authorized"]
