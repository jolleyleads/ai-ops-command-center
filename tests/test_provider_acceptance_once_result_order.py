from pathlib import Path

def test_result_emitted_after_reload():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("db.session.get(OutreachLead, lead.id)") < text.rindex("PROVIDER_ACCEPTANCE_RESULT")
