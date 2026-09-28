from pathlib import Path

def test_result_is_printed_after_durable_readback():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("db.session.get(OutreachLead, lead.id)") < text.rindex("json.dumps(result")
