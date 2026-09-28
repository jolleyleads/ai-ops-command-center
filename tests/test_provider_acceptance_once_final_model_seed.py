from outreach_automation import OutreachLead

def test_acceptance_model_has_seed_fields():
    for name in ("location", "source_url", "evidence_json", "score", "verification", "status", "subject", "body"):
        assert hasattr(OutreachLead, name)
