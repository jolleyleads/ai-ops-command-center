from crm_integrations.registry import PROVIDERS, catalog

def test_expected_providers():
    assert set(PROVIDERS) == {"hubspot", "salesforce", "pipedrive", "servicetitan", "jobber", "clio"}

def test_no_unverified_connections():
    assert len(catalog()) == 6
    assert all(item["status"] == "setup_required" for item in catalog())
