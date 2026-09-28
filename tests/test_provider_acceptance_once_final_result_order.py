from pathlib import Path

def test_acceptance_result_follows_readback():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("db.session.get(OutreachLead, lead.id)") < text.index("result = {", text.index("db.session.get(OutreachLead, lead.id)"))
