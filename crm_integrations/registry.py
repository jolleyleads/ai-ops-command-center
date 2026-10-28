"""CRM integration catalog. Listing a provider never implies authorization."""
PROVIDERS = {
    "hubspot": "HubSpot",
    "salesforce": "Salesforce",
    "pipedrive": "Pipedrive",
    "servicetitan": "ServiceTitan",
    "jobber": "Jobber",
    "clio": "Clio",
}

def catalog():
    return [
        {"id": key, "name": name, "status": "setup_required"}
        for key, name in PROVIDERS.items()
    ]
