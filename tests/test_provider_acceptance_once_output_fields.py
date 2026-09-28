from pathlib import Path

def test_core_output_fields_are_present():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    for key in ("recipient", "lead_id", "created", "before", "after", "cycle", "timestamp"):
        assert key in text
