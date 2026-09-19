from src.execution import normalize_lead, verify_lead, lead_fingerprint

def test_normalization_is_deterministic():
    lead = {"company_name": "  ACME   Electric ", "email": " SALES@EXAMPLE.COM ", "sources": ["https://example.com"]}
    a = normalize_lead(lead)
    b = normalize_lead(lead)
    assert a == b
    assert a["company_name"] == "ACME Electric"
    assert a["email"] == "sales@example.com"

def test_missing_evidence_blocks_workflow():
    result = verify_lead({"company_name": "ACME"})
    assert result["verified"] is False
    assert "missing source evidence" in result["reasons"]

def test_bad_email_blocks_workflow():
    result = verify_lead({"company_name": "ACME", "email": "not-an-email", "sources": ["https://example.com"]})
    assert result["verified"] is False

def test_fingerprint_is_stable():
    lead = {"company_name": "ACME", "sources": ["https://example.com"]}
    assert lead_fingerprint(lead) == lead_fingerprint(lead)
