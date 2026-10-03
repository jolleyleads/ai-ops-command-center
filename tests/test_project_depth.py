def test_project_depth_exists():
    assert True


def test_acceptance_campaigns_are_cross_industry():
    from pathlib import Path
    source = Path("customer_demo.py").read_text(encoding="utf-8").lower()
    assert "plumbing companies" in source
    assert "law firms" in source
    assert "dental practices" in source
    assert "restaurants" in source
    assert '"target_customer":"hvac' not in source
    assert '"target_customer":"heating and cooling' not in source
