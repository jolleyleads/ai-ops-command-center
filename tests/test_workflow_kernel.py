from src.workflow_kernel import validate_transition, apply_transition

def test_verified_requires_evidence():
    v=validate_transition("discovered","verified",{"stage":"discovered"})
    assert not v["allowed"] and "missing_evidence" in v["reasons"]

def test_verified_with_evidence_passes():
    r=apply_transition({"stage":"discovered","evidence":["https://example.com"]},"verified")
    assert r["ok"] and r["state"]["stage"]=="verified"

def test_llm_cannot_skip_stages():
    v=validate_transition("verified","contacted",{"evidence":["x"],"send_receipt":{"id":"1"}})
    assert not v["allowed"] and "transition_not_allowed" in v["reasons"]

def test_send_requires_receipt():
    v=validate_transition("outreach_ready","contacted",{"stage":"outreach_ready"})
    assert not v["allowed"] and "missing_send_receipt" in v["reasons"]

def test_booking_requires_receipt():
    v=validate_transition("booking_ready","booked",{"stage":"booking_ready"})
    assert not v["allowed"] and "missing_booking_receipt" in v["reasons"]

def test_crm_requires_receipt():
    v=validate_transition("booked","crm_synced",{"stage":"booked"})
    assert not v["allowed"] and "missing_crm_receipt" in v["reasons"]


def test_candidate_identity_join_is_not_url_dependent():
    from smart_search import _verification_gate
    discovery=[{"title":"ACME Electric LLC","url":"https://places.example/acme","research_tool":"business_search"}]
    promoted=[{"candidate_name":"ACME Electric LLC","url":"https://jobs.example/acme-master","supporting_urls":["https://jobs.example/acme-master"],"verified_claim":"Hiring a master electrician."}]
    result=_verification_gate(discovery,promoted,{})
    assert result[0]["classification"]=="Verified Lead"
    assert result[0]["url"]=="https://places.example/acme"
    assert result[0]["supporting_urls"]==["https://jobs.example/acme-master"]

def test_other_company_evidence_cannot_promote_candidate():
    from smart_search import _verification_gate
    discovery=[{"title":"ACME Electric LLC","url":"https://places.example/acme","research_tool":"business_search"}]
    promoted=[{"candidate_name":"Different Electric","url":"https://jobs.example/different","supporting_urls":["https://jobs.example/different"],"verified_claim":"Hiring a master electrician."}]
    result=_verification_gate(discovery,promoted,{})
    assert result[0]["classification"]=="Candidate"


def test_exa_verification_evidence_promotes_matching_candidate(monkeypatch):
    import smart_search
    monkeypatch.setattr(smart_search, "_exa_search", lambda q,loc="": {"results":[{"title":"ACME hiring","url":"https://jobs.example/acme","subtitle":"We are hiring a master electrician for permit work.","page_text":"ACME Electric LLC is hiring a master electrician required for electrical permits.","source":"Exa"}],"message":"","source":"Exa"})
    rows,msg,used=smart_search._candidate_followups("find electrical contractors in Chesapeake","",[{"name":"ACME Electric LLC","discovery_urls":["https://places.example/acme"]}],10**12,1)
    promoted=smart_search._deterministic_need_verification(rows,"find electrical contractors in Chesapeake")
    gated=smart_search._verification_gate([{"title":"ACME Electric LLC","url":"https://places.example/acme","research_tool":"business_search"}],promoted,{})
    assert used and set(used)=={"exa_search"}
    assert len(used)==len(smart_search._verification_queries("ACME Electric LLC","find electrical contractors in Chesapeake",smart_search._verification_intent("find electrical contractors in Chesapeake")))
    assert rows[0]["candidate_name"]=="ACME Electric LLC"
    assert gated[0]["classification"]=="Verified Lead"
    assert gated[0]["supporting_urls"]==["https://jobs.example/acme"]

def test_exa_discovery_without_need_evidence_stays_candidate(monkeypatch):
    import smart_search
    monkeypatch.setattr(smart_search, "_exa_search", lambda q,loc="": {"results":[{"title":"ACME homepage","url":"https://acme.example","subtitle":"Electrical contractor serving Chesapeake.","page_text":"Residential and commercial electrical services.","source":"Exa"}],"message":"","source":"Exa"})
    rows,msg,used=smart_search._candidate_followups("find electrical contractors in Chesapeake","",[{"name":"ACME Electric LLC","discovery_urls":["https://places.example/acme"]}],10**12,1)
    promoted=smart_search._deterministic_need_verification(rows,"find electrical contractors in Chesapeake")
    gated=smart_search._verification_gate([{"title":"ACME Electric LLC","url":"https://places.example/acme","research_tool":"business_search"}],promoted,{})
    assert promoted==[]
    assert gated[0]["classification"]=="Candidate"


def test_electrical_verification_queries_cover_multiple_evidence_channels():
    import smart_search
    queries=smart_search._verification_queries("ACME Electric LLC","find electrical contractors in Chesapeake",smart_search._verification_intent("find electrical contractors in Chesapeake"))
    joined=" ".join(queries).lower()
    assert len(queries) >= 6
    assert "master electrician" in joined
    assert "jobs" in joined or "careers" in joined
    assert "permit" in joined
    assert "project" in joined
    assert "license" in joined


def test_candidate_followups_preserve_candidate_identity_across_exa_queries(monkeypatch):
    import smart_search
    calls=[]
    def fake_exa(q,loc=""):
        calls.append(q)
        return {"results":[{"title":"source","url":f"https://evidence.example/{len(calls)}","subtitle":"public evidence","page_text":"public evidence","source":"Exa"}],"message":"","source":"Exa"}
    monkeypatch.setattr(smart_search,"_exa_search",fake_exa)
    rows,msg,used=smart_search._candidate_followups(
        "find electrical contractors in Chesapeake","",
        [{"name":"ACME Electric LLC","discovery_urls":["https://places.example/acme"]}],
        10**12,1)
    assert len(calls) >= 6
    assert all(x["candidate_name"]=="ACME Electric LLC" for x in rows)
    assert all(x["verification_research"] is True for x in rows)
    assert all(x.get("verification_query") for x in rows)
    assert all(x["candidate_discovery_urls"]==["https://places.example/acme"] for x in rows)


def test_hvac_hiring_gets_deterministic_verification_plan():
    import smart_search
    q="Find HVAC companies in Virginia Beach that are currently hiring technicians."
    assert smart_search._needs_candidate_verification(q)
    intents=smart_search._verification_intent(q)
    assert "hiring" in intents
    queries=smart_search._verification_queries("Coastal HVAC",q,intents)
    joined=" ".join(queries).lower()
    assert "hiring" in joined or "careers" in joined
    assert "technician" in joined

def test_active_projects_get_project_verification_plan():
    import smart_search
    q="Find commercial contractors in Norfolk with evidence of active projects or recent permits."
    assert smart_search._needs_candidate_verification(q)
    intents=smart_search._verification_intent(q)
    assert "projects" in intents
    assert "permit_license" in intents
    joined=" ".join(smart_search._verification_queries("ACME Construction",q,intents)).lower()
    assert "project" in joined
    assert "permit" in joined

def test_hvac_hiring_requires_candidate_specific_source_evidence():
    import smart_search
    q="Find HVAC companies in Virginia Beach that are currently hiring technicians."
    discovery_only=[{"title":"Coastal HVAC","url":"https://places.example/coastal","subtitle":"HVAC services in Virginia Beach"}]
    assert smart_search._deterministic_need_verification(discovery_only,q)==[]
    evidence=[{"candidate_name":"Coastal HVAC","verification_research":True,"url":"https://coastal.example/careers","title":"Careers","subtitle":"We are hiring HVAC technicians now.","page_text":""}]
    promoted=smart_search._deterministic_need_verification(evidence,q)
    assert len(promoted)==1
    assert promoted[0]["supporting_urls"]==["https://coastal.example/careers"]


def test_failed_receipt_cannot_advance_workflow():
    v=validate_transition("outreach_ready","contacted",{"stage":"outreach_ready","send_receipt":{"ok":False,"error":"send failed"}})
    assert not v["allowed"] and "missing_send_receipt" in v["reasons"]

def test_enrichment_requires_successful_validated_proof():
    v=validate_transition("verified","enriched",{"stage":"verified","enrichment":{"validated":False,"fields":{}}})
    assert not v["allowed"] and "missing_enrichment" in v["reasons"]

def test_enrichment_omits_unsupported_contact_fields():
    from src.enrichment import enrich_lead, validated_payload
    lead={"company_name":"ACME HVAC","email":"madeup@acmehvac.com","phone":"757-555-1212"}
    evidence=[{"candidate_name":"ACME HVAC","url":"https://acmehvac.com/about","title":"About","page_text":"ACME HVAC serves Hampton Roads."}]
    enriched=enrich_lead(lead,evidence)
    payload=validated_payload(enriched)
    assert "email" not in payload
    assert "phone" not in payload

def test_enrichment_accepts_source_bound_company_contact():
    from src.enrichment import enrich_lead, validated_payload
    lead={"company_name":"ACME HVAC"}
    evidence=[{"candidate_name":"ACME HVAC","url":"https://acmehvac.com/contact","title":"Contact","page_text":"Call (757) 555-1212 or email service@acmehvac.com"}]
    payload=validated_payload(enrich_lead(lead,evidence))
    assert payload["email"]=="service@acmehvac.com"
    assert payload["phone"]=="(757) 555-1212"
    assert payload["email_source_url"]=="https://acmehvac.com/contact"

def test_enrichment_rejects_cross_company_evidence():
    from src.enrichment import enrich_lead, validated_payload
    lead={"company_name":"ACME HVAC"}
    evidence=[{"candidate_name":"Different HVAC","url":"https://different.example/contact","page_text":"Owner Jane Smith jane@different.example 757-555-9999"}]
    assert validated_payload(enrich_lead(lead,evidence))=={}
