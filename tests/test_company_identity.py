"""Regression coverage for the real IGT/company-contact collision."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import commercial_app  # Register production routes before any test client request.
import outreach_bridge as bridge
import smart_search as search
import v1_orchestration as orchestration
from src.company_identity import identity_proof, owned_host, email_on_domain, location_matches, page_metadata, visible_page_text, contact_context_matches
from src.enrichment import enrich_lead, validated_payload


def evidence(name, url, text, **extra):
    return dict(candidate_name=name, url=url, title=name, page_text=text,directly_fetched=True,http_status=200,
                observed_at=datetime.now(timezone.utc).isoformat(), **extra)


def test_igt_collision_cannot_attach_other_companies_or_infer_acronym_owner():
    rows=[dict(candidate_name="IGT",title="IGT",supporting_urls=["https://www.career.com/job/howmet/process-engineer-igt"])]
    sources=[
        evidence("IGT","https://www.career.com/job/howmet/process-engineer-igt","Howmet Aerospace Process Engineer IGT. TalentAcquisitionCoE_Howmet@howmet.com"),
        evidence("IGT","https://promallu.com/igt-solutions","IGT Solutions Inc. +1 865-851-9514"),
        evidence("IGT","https://www.igt.com/contact","IGT gaming support@igt.com (702) 669-7777"),
    ]
    result=search._attach_source_contacts(rows,sources,"Hampton Roads Virginia")[0]
    assert result["contacts"]==[]
    assert result["contact_status"]=="identity_unresolved"
    assert "website" not in result


def test_official_claim_can_resolve_an_acronym_without_guessing():
    rows=[dict(candidate_name="IGT",title="IGT",supporting_urls=["https://igt.com/careers"])]
    result=search._attach_source_contacts(rows,[evidence("IGT","https://igt.com/contact","IGT Hampton VA support@igt.com (757) 555-1234")],"Hampton VA")[0]
    assert {c.get("email") or c.get("phone") for c in result["contacts"]}=={"support@igt.com","(757) 555-1234"}
    assert result["website"]=="https://igt.com"


def test_directory_mentions_and_generated_search_answer_are_not_contact_proof():
    rows=[dict(candidate_name="Sunridge Management Group",title="Sunridge Management Group")]
    sources=[evidence("Sunridge Management Group","https://contactout.com/person","Previously Sunridge Management Group, now Regeneron jhafar.ali@regeneron.com"),
             dict(candidate_name="Sunridge Management Group",url="https://sunridgemanagementgroup.com/contact",subtitle="Sunridge Management Group email guessed@sunridgemanagementgroup.com")]
    assert search._attach_source_contacts(rows,sources)[0]["contacts"]==[]


@pytest.mark.parametrize("url",["https://example.com.evil.test/contact","https://evil-example.com/contact","https://com/contact","https://other.example.com/contact"])
def test_parent_sibling_and_lookalike_hosts_are_not_owned(url):
    assert not owned_host(url,"https://sales.example.com")
    assert not email_on_domain("owner@"+url.split("/")[2],"https://sales.example.com")


def test_valid_child_domain_and_boundary_matching():
    assert owned_host("https://www.acme.com/contact","https://acme.com")
    assert owned_host("https://support.acme.com/contact","https://acme.com")
    assert email_on_domain("owner@acme.com","https://acme.com")
    assert not owned_host("https://acme.com.evil.test/contact","https://acme.com")
    assert not identity_proof("IGT",evidence("IGT","https://igtsolutions.com","IGT Solutions"))


@pytest.mark.parametrize("url",["https://acme.vendor.example/contact","https://acme.vendor.com/contact","https://acme.vendor.co.uk/contact"])
def test_matching_subdomain_cannot_establish_an_unrelated_company(url):
    row=evidence("Acme",url,"Acme info@"+url.split("/")[2])
    assert identity_proof("Acme",row) is None
    assert search._attach_source_contacts([dict(title="Acme",candidate_name="Acme")],[row])[0]["contacts"]==[]


def test_company_domain_is_resolved_with_multi_label_public_suffix():
    row=evidence("Acme","https://careers.acme.co.uk/contact","Acme info@acme.co.uk")
    assert identity_proof("Acme",row)["official_host"]=="acme.co.uk"
    result=search._attach_source_contacts([dict(title="Acme",candidate_name="Acme")],[row])[0]
    assert result["website"]=="https://acme.co.uk"
    assert result["contacts"][0]["email"]=="info@acme.co.uk"


def test_conflicting_domains_stay_unresolved_instead_of_choosing_first():
    rows=[dict(candidate_name="Acme",title="Acme")]
    sources=[evidence("Acme","https://acme.com","Acme info@acme.com"),evidence("Acme","https://acme.net","Acme info@acme.net")]
    result=search._attach_source_contacts(rows,sources)[0]
    assert result["company_identity_status"]=="ambiguous" and result["contacts"]==[]


def test_explicit_website_resolves_conflicting_sources_and_blocks_off_domain_email():
    rows=[dict(candidate_name="Acme",title="Acme",website="https://acme.com")]
    sources=[evidence("Acme","https://acme.com/contact","Acme Norfolk VA owner@acme.com vendor@other.com (757) 555-1212"),
             evidence("Acme","https://acme.net/contact","Acme Norfolk VA info@acme.net")]
    result=search._attach_source_contacts(rows,sources,"Norfolk Virginia")[0]
    assert [c["email"] for c in result["contacts"] if c.get("email")]==["owner@acme.com"]
    assert all(c["source_url"]=="https://acme.com/contact" for c in result["contacts"])


def test_other_branch_contact_does_not_inherit_a_distant_matching_city():
    text="Acme Norfolk VA owner@acme.com (757) 555-1212 "+("Service details. "*50)+"Acme Las Vegas NV vegas@acme.com (702) 555-1212"
    rows=[dict(candidate_name="Acme",title="Acme",website="https://acme.com")]
    result=search._attach_source_contacts(rows,[evidence("Acme","https://acme.com/locations",text)],"Norfolk VA")[0]
    assert {c.get("email") or c.get("phone") for c in result["contacts"]}=={"owner@acme.com","(757) 555-1212"}


def test_adjacent_branches_do_not_share_location_proof():
    text="Acme Norfolk VA owner@acme.com (757) 555-1212. Acme Las Vegas NV vegas@acme.com (702) 555-1212"
    rows=[dict(candidate_name="Acme",title="Acme",website="https://acme.com")]
    result=search._attach_source_contacts(rows,[evidence("Acme","https://acme.com/locations",text)],"Norfolk VA")[0]
    assert {c.get("email") or c.get("phone") for c in result["contacts"]}=={"owner@acme.com","(757) 555-1212"}


def test_region_and_state_abbreviations_require_actual_location_evidence():
    assert location_matches("Virginia Beach, VA","Hampton Roads Virginia")
    assert location_matches("Norfolk, Virginia","Norfolk VA")
    assert not location_matches("Norfolk Nebraska","Norfolk VA")
    assert not location_matches("Las Vegas NV","Hampton Roads Virginia")
    assert contact_context_matches("Washington, DC owner@acme.com","owner@acme.com","Washington DC")


def test_mailto_contacts_keep_local_context_without_using_scripts_as_contact_proof():
    text=visible_page_text('<script>wrong@other.com</script>Acme Norfolk VA <a href="mailto:owner@acme.com?subject=Hello">Email us</a>')
    assert "wrong@other.com" not in text
    assert contact_context_matches(text,"owner@acme.com","Norfolk Virginia")


@pytest.mark.parametrize("types",[None,3,{"bad":"value"},[{}]])
def test_malformed_source_metadata_does_not_crash_research(types):
    raw='<script type="application/ld+json">'+json.dumps({"@type":types})+'</script>'
    assert page_metadata(raw)["source_organizations"]==[]


def test_current_company_page_metadata_resolves_non_matching_brand_domain():
    raw='<title>Contact</title><script type="application/ld+json">'+json.dumps({"@type":"Organization","name":"Hampton Roads Automation","url":"https://hrautomation.us"})+'</script><h1>Hampton Roads Automation</h1>'
    row=evidence("Hampton Roads Automation","https://hrautomation.us/contact","Hampton Roads Automation Norfolk VA contact@hrautomation.us",**page_metadata(raw))
    proof=identity_proof("Hampton Roads Automation",row)
    assert proof["basis"]=="organization_named_on_owned_page"
    assert len(proof["content_sha256"])==64
    assert not identity_proof("IGT",row)


def test_enrichment_cannot_validate_a_third_party_phone_or_website():
    lead=dict(company_name="Acme",email="person@contactout.com",phone="757-555-1212")
    source=evidence("Acme","https://contactout.com/person","Acme person@contactout.com (757) 555-1212")
    assert validated_payload(enrich_lead(lead,[source]))=={}


def test_probe_only_fetches_explicit_company_domain_not_job_board_roots(monkeypatch):
    seen=[]
    def get(url,**kw):
        seen.append(url)
        return SimpleNamespace(url=url,ok=True,headers={"content-type":"text/html"},text='<title>Acme</title>Acme Norfolk VA owner@acme.com vendor@other.com')
    monkeypatch.setattr(bridge,"public_get",get)
    rows,meta=bridge._public_contact_evidence(dict(title="Acme",website="https://acme.com",location="Norfolk VA",supporting_urls=["https://career.com/job/acme","https://contactout.com/person"]))
    assert all(owned_host(url,"https://acme.com") for url in seen)
    assert rows[0]["validated_emails"]==["owner@acme.com"]
    assert rows[0]["identity_version"]=="company-domain-v1"


def test_probe_preserves_local_cloudflare_contact_and_ignores_script_addresses(monkeypatch):
    email="owner@acme.com";key=0x42
    encoded=bytes([key]+[ord(c)^key for c in email]).hex()
    raw=f'<title>Acme</title><script>fake@acme.com</script>Acme Norfolk VA <span data-cfemail="{encoded}">protected</span>'
    monkeypatch.setattr(bridge,"public_get",lambda url,**kw:SimpleNamespace(url=url,ok=True,headers={"content-type":"text/html"},text=raw))
    rows,_=bridge._public_contact_evidence(dict(company="Acme",website="https://acme.com",location="Norfolk VA"))
    assert rows[0]["validated_emails"]==[email]


def test_probe_and_enrichment_examine_later_local_phone_numbers(monkeypatch):
    text="Acme Las Vegas NV (702) 555-1212. "+("Details. "*60)+"Acme Norfolk VA 757-555-3434"
    monkeypatch.setattr(bridge,"public_get",lambda url,**kw:SimpleNamespace(url=url,ok=True,headers={"content-type":"text/html"},text=text))
    lead=dict(company="Acme",website="https://acme.com",location="Norfolk VA")
    rows,_=bridge._public_contact_evidence(lead)
    assert rows[0]["validated_phones"]==["757-555-3434"]
    payload=validated_payload(enrich_lead(lead,[evidence("Acme","https://acme.com/locations",text)]))
    assert payload["phone"]=="(757) 555-3434"


def test_probe_rejects_redirect_to_parent_domain_and_wrong_location(monkeypatch):
    def get(url,**kw):
        return SimpleNamespace(url="https://other.com/contact",ok=True,headers={"content-type":"text/html"},text="Acme Norfolk VA owner@other.com")
    monkeypatch.setattr(bridge,"public_get",get)
    rows,_=bridge._public_contact_evidence(dict(title="Acme",website="https://acme.com",location="Norfolk VA"))
    assert rows==[]
    monkeypatch.setattr(bridge,"public_get",lambda url,**kw:SimpleNamespace(url=url,ok=True,headers={"content-type":"text/html"},text="Acme Las Vegas NV owner@acme.com"))
    rows,_=bridge._public_contact_evidence(dict(title="Acme",website="https://acme.com",location="Norfolk VA"))
    assert rows==[]


def test_outreach_uses_only_approved_local_emails_from_fetched_page(monkeypatch):
    import dns.resolver
    monkeypatch.setattr(dns.resolver,"resolve",lambda *a,**kw:[SimpleNamespace(exchange="mail.acme.com.",preference=10)])
    row=evidence("Acme","https://acme.com/contact","Acme Las Vegas NV vegas@acme.com. Acme Norfolk VA owner@acme.com",identity_version="company-domain-v1",company_identity={"company_name":"Acme"},contact_location="Norfolk VA")
    monkeypatch.setattr(orchestration,"_public_contact_evidence",lambda r:([row],{}))
    result=dict(company="Acme",website="https://acme.com",contact_location="Norfolk VA")
    assert orchestration._verified_public_email(result)==("owner@acme.com","https://acme.com/contact")
    stored=orchestration._evidence_with_contact(result,"owner@acme.com","https://acme.com/contact")
    assert stored[-1]["company_identity"]["company_name"]=="Acme"


def test_outreach_rejects_off_domain_source_even_if_email_matches(monkeypatch):
    monkeypatch.setattr(orchestration,"_public_contact_evidence",lambda r:([dict(url="https://thirdparty.example/contact",text="owner@acme.com")],{}))
    assert orchestration._verified_public_email(dict(company="Acme",website="https://acme.com"))==("", "")


def test_primary_business_evidence_survives_failed_contact_and_supports_only_observed_intent():
    from src.qualification import qualify_lead
    result={'company':'Acme','website':'https://acme.com','_contact_enrichment':{'fields':{}},
        '_outreach_copy_sources':[
            {'url':'https://acme.com/services','page_text':'Acme HVAC services in Norfolk Virginia',
             'directly_fetched':True,'http_status':200,'source':'outreach_primary_copy','observed_at':'2026-10-21T00:00:00Z'},
            {'url':'https://unrelated.example','page_text':'Unproven buying intent','directly_fetched':True,'http_status':200}]}
    stored=orchestration._evidence_with_contact(result,'','')
    assert any(x.get('page_text')=='Acme HVAC services in Norfolk Virginia' for x in stored)
    assert not any(x.get('url')=='https://unrelated.example' for x in stored)
    receipt=qualify_lead({'company_name':'Acme','website':'https://acme.com','website_source_url':'https://acme.com','evidence':stored},
        context={'query':'HVAC businesses'})
    assert 'intent_signal_fit' in receipt['passed_checks']
    assert 'MISSING_VALIDATED_CONTACT' in receipt['reason_codes']
    assert receipt['ok'] is False
