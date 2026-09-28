from pathlib import Path

def test_acceptance_result_is_printed_after_build():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    start = text.index("result = {", text.index("db.session.get(OutreachLead, lead.id)"))
    assert start < text.index("json.dumps(result", start)
