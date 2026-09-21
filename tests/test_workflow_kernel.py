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
    assert used==["exa_search"]
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
