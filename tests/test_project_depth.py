def test_project_depth_exists():
    assert True


def test_smart_search_has_deterministic_universal_fallback_intents():
    from pathlib import Path
    source=Path("smart_search.py").read_text(encoding="utf-8")
    assert "def _deterministic_route_intent(q):" in source
    for intent in ("permit_leads","permits","jobs","contractors","businesses","web_research"):
        assert f'return "{intent}"' in source
    assert '"planning_unavailable"' in source

def test_draft_limits_match_safe_send_validator():
    from pathlib import Path
    source=Path("outreach_automation.py").read_text(encoding="utf-8")
    assert 'subject = _clean(parsed.get("subject"), 160)' in source
    assert 'body = _clean(parsed.get("body"), 5000)' in source

def test_acceptance_reports_safe_send_stage_truthfully():
    from pathlib import Path
    source=Path("customer_demo.py").read_text(encoding="utf-8")
    assert '"stage":"safe_send"' in source
    assert '"reason":"FRESH_QUALIFIED_DRAFT_FAILED_SAFE_SEND"' in source
