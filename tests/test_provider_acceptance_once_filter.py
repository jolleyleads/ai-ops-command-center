from pathlib import Path

def test_runner_looks_up_exact_acceptance_identity():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "filter_by(contact_email=recipient, company=marker)" in source
    assert "order_by(OutreachLead.id.desc()).first()" in source
