from pathlib import Path

def test_acceptance_query_runs_inside_app_context():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("with app.app_context():") < text.index("OutreachLead.query")
