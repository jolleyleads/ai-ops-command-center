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


def _validated_qualified_fixture():
    return {
        "company_name":"ACME HVAC",
        "website":"https://acmehvac.com",
        "website_source_url":"https://acmehvac.com",
        "email":"service@acmehvac.com",
        "email_source_url":"https://acmehvac.com/contact",
        "decision_maker":"Jane Smith",
        "decision_maker_title":"owner",
        "decision_maker_source_url":"https://acmehvac.com/about",
        "evidence":[{"url":"https://acmehvac.com/jobs","title":"Careers"}],
    }

def test_qualification_accepts_only_source_validated_lead():
    from src.qualification import qualify_lead, qualification_payload
    from datetime import datetime, timezone
    validated=_validated_qualified_fixture()
    validated["evidence"]=[{"url":"https://acmehvac.com/jobs","title":"HVAC technician hiring","published_at":"2026-09-01T12:00:00+00:00"}]
    q=qualify_lead(validated,verification_ok=True,context={"intent_signal":"hiring technicians","evidence":validated["evidence"],"max_evidence_age_days":90},now=datetime(2026,9,21,tzinfo=timezone.utc))
    assert q["qualified"] and q["ok"]
    downstream=qualification_payload(validated,q)
    assert downstream["email"]=="service@acmehvac.com"
    assert downstream["decision_maker"]=="Jane Smith"

def test_qualification_fails_without_verified_lead():
    from src.qualification import qualify_lead, qualification_payload
    validated=_validated_qualified_fixture()
    q=qualify_lead(validated,verification_ok=False)
    assert not q["qualified"] and "IDENTITY_NOT_VERIFIED" in q["reason_codes"]
    assert qualification_payload(validated,q)=={}

def test_qualification_fails_without_source_backed_contact():
    from src.qualification import qualify_lead
    validated=_validated_qualified_fixture()
    validated.pop("email_source_url")
    q=qualify_lead(validated)
    assert not q["qualified"] and "MISSING_VALIDATED_CONTACT" in q["reason_codes"]

def test_qualification_fails_without_evidence_url():
    from src.qualification import qualify_lead
    validated=_validated_qualified_fixture()
    validated["evidence"]=[{"title":"unsupported"}]
    q=qualify_lead(validated)
    assert not q["qualified"] and "MISSING_SOURCE_EVIDENCE" in q["reason_codes"]

def test_failed_qualification_receipt_cannot_advance():
    v=validate_transition("enriched","qualified",{"stage":"enriched","qualification":{"ok":False,"qualified":False,"status":"Needs More Evidence","reason_codes":["MISSING_VALIDATED_CONTACT"]}})
    assert not v["allowed"] and "qualification_not_explicitly_successful" in v["reasons"]


def test_qualification_three_state_full_fit_gate():
    from datetime import datetime, timezone
    from src.qualification import qualify_lead
    validated=_validated_qualified_fixture()
    validated["evidence"]=[{"url":"https://acmehvac.com/jobs","title":"HVAC technician careers Virginia Beach","snippet":"ACME HVAC is hiring HVAC technicians in Virginia Beach.","published_at":"2026-09-01T12:00:00+00:00"}]
    ctx={"target_location":"Virginia Beach","candidate_location":"Virginia Beach, VA","business_type":"HVAC","candidate_type":"HVAC contractor","intent_signal":"hiring technicians","query":"HVAC hiring technicians","evidence":validated["evidence"],"max_evidence_age_days":90}
    q=qualify_lead(validated,verification_ok=True,context=ctx,now=datetime(2026,9,21,tzinfo=timezone.utc))
    assert q["status"]=="Qualified" and q["ok"] is True

def test_geographic_mismatch_is_not_qualified():
    from src.qualification import qualify_lead
    q=qualify_lead(_validated_qualified_fixture(),context={"target_location":"Virginia Beach","candidate_location":"Richmond, VA"})
    assert q["status"]=="Not Qualified" and "GEOGRAPHIC_MISMATCH" in q["reason_codes"]

def test_missing_intent_or_recency_needs_more_evidence():
    from src.qualification import qualify_lead
    q=qualify_lead(_validated_qualified_fixture(),context={"intent_signal":"hiring technicians"})
    assert q["status"]=="Needs More Evidence"
    assert "INTENT_SIGNAL_UNPROVEN" in q["reason_codes"]
    assert "EVIDENCE_RECENCY_UNPROVEN" in q["reason_codes"]

def test_stale_evidence_is_not_qualified():
    from datetime import datetime, timezone
    from src.qualification import qualify_lead
    v=_validated_qualified_fixture()
    v["evidence"]=[{"url":"https://acmehvac.com/jobs","title":"Hiring technicians","published_at":"2025-01-01T00:00:00+00:00"}]
    q=qualify_lead(v,context={"intent_signal":"hiring technicians","evidence":v["evidence"],"max_evidence_age_days":90},now=datetime(2026,9,21,tzinfo=timezone.utc))
    assert q["status"]=="Not Qualified" and "EVIDENCE_STALE" in q["reason_codes"]

def test_duplicate_and_exclusion_rules_fail_closed():
    from src.qualification import qualify_lead
    q=qualify_lead(_validated_qualified_fixture(),context={"duplicate":True})
    assert q["status"]=="Not Qualified" and "DUPLICATE_LEAD" in q["reason_codes"]
    q2=qualify_lead(_validated_qualified_fixture(),context={"excluded":True})
    assert q2["status"]=="Not Qualified" and "EXCLUDED_LEAD" in q2["reason_codes"]

def test_nonempty_fake_qualification_receipt_cannot_advance():
    v=validate_transition("enriched","qualified",{"stage":"enriched","qualification":{"status":"Qualified","reason_codes":[]}})
    assert not v["allowed"] and "qualification_not_explicitly_successful" in v["reasons"]

def test_only_explicit_qualified_receipt_advances():
    v=validate_transition("enriched","qualified",{"stage":"enriched","qualification":{"status":"Qualified","qualified":True,"ok":True,"reason_codes":[]}})
    assert v["allowed"]


def _outreach_fixture():
    return {"company":"ACME HVAC","contact_email":"owner@acmehvac.com","source_url":"https://acmehvac.com","evidence":{"qualified":{"email":"owner@acmehvac.com","email_source_url":"https://acmehvac.com/contact"},"verification":[{"url":"https://acmehvac.com/jobs"}]},"subject":"Quick question","body":"Would a quick call this week make sense?","status":"drafted","gmail_thread_id":""}

def test_outreach_execution_blocks_invalid_recipient_before_send():
    from src.outreach_execution import execute_outreach_send
    lead=_outreach_fixture();lead["contact_email"]=""
    calls=[]
    result=execute_outreach_send(lead,lambda *args:calls.append(args))
    assert result["ok"] is False
    assert result["stage"]=="blocked"
    assert "INVALID_OR_MISSING_RECIPIENT" in result["gate"]["reasons"]
    assert calls==[]

def test_outreach_execution_blocks_unsupported_generated_url():
    from src.outreach_execution import validate_outreach_message
    lead=_outreach_fixture()
    body="See https://made-up.example/demo and let me know."
    gate=validate_outreach_message(lead,"Quick question",body)
    assert not gate["ok"] and "UNSUPPORTED_URL_IN_MESSAGE" in gate["reasons"]

def test_outreach_execution_requires_durable_send_receipt():
    from src.outreach_execution import execute_outreach_send
    lead=_outreach_fixture()
    result=execute_outreach_send(lead,lambda *args:{"ok":True})
    assert result["ok"] is False and result["stage"]=="send_failed"
    assert "MISSING_MESSAGE_ID" in result["send_receipt"]["reasons"]
    assert "MISSING_THREAD_ID" in result["send_receipt"]["reasons"]

def test_outreach_execution_success_has_validated_receipt():
    from src.outreach_execution import execute_outreach_send
    lead=_outreach_fixture()
    result=execute_outreach_send(lead,lambda *args:{"ok":True,"message_id":"m-123","thread_id":"t-123"})
    assert result["ok"] is True and result["stage"]=="contacted"
    assert result["send_receipt"]["validated"] is True

def test_outreach_execution_blocks_opt_out_signal():
    from src.outreach_execution import execute_outreach_send
    lead=_outreach_fixture();lead["last_reply"]="Please remove me from your list."
    calls=[]
    result=execute_outreach_send(lead,lambda *args:calls.append(args))
    assert result["stage"]=="blocked"
    assert "OPT_OUT_SIGNAL_PRESENT" in result["gate"]["reasons"]
    assert calls==[]

def test_workflow_contacted_requires_explicit_successful_receipt():
    v=validate_transition("outreach_ready","contacted",{"stage":"outreach_ready","send_receipt":{"ok":True,"validated":False,"message_id":"m","thread_id":"t"}})
    assert not v["allowed"]


def test_any_inbound_reply_is_hard_stop():
    from src.followup_control import classify_inbound, followup_permission
    state=classify_inbound([
        {"from":"sales@us.example","snippet":"checking in"},
        {"from":"owner@acmehvac.com","snippet":"Thanks, I got your email.","id":"r1"},
    ],sender_email="sales@us.example")
    assert state["replied"] is True and state["stop"] is True and state["opted_out"] is False
    gate=followup_permission(reply_state=state,follow_up_count=0,max_followups=2,thread_id="t1",contact_email="owner@acmehvac.com")
    assert gate["allowed"] is False and "HARD_STOP_INBOUND_REPLY" in gate["reasons"]

def test_opt_out_is_terminal_hard_stop():
    from src.followup_control import classify_inbound
    state=classify_inbound([
        {"from":"sales@us.example","snippet":"hello"},
        {"from":"owner@acmehvac.com","snippet":"Please remove me from your list.","id":"r2"},
    ],sender_email="sales@us.example")
    assert state["stop"] is True and state["opted_out"] is True and state["reason"]=="OPT_OUT"

def test_our_own_thread_messages_do_not_count_as_reply():
    from src.followup_control import classify_inbound
    state=classify_inbound([
        {"from":"Sales <sales@us.example>","snippet":"first touch"},
        {"from":"Sales <sales@us.example>","snippet":"follow up"},
    ],sender_email="sales@us.example")
    assert state["replied"] is False and state["stop"] is False

def test_reply_check_failure_blocks_followup():
    from src.followup_control import followup_permission
    gate=followup_permission(reply_state={"ok":False,"stop":True,"reason":"REPLY_CHECK_FAILED"},follow_up_count=0,max_followups=2,thread_id="t1",contact_email="x@example.com")
    assert gate["allowed"] is False
    assert "REPLY_CHECK_FAILED" in gate["reasons"]

def test_max_followups_blocks_another_send():
    from src.followup_control import followup_permission
    gate=followup_permission(reply_state={"ok":True,"stop":False},follow_up_count=2,max_followups=2,thread_id="t1",contact_email="x@example.com")
    assert gate["allowed"] is False and "MAX_FOLLOWUPS_REACHED" in gate["reasons"]


def test_reply_opt_out_overrides_interested_proposal():
    from src.reply_booking import validate_reply_classification
    r=validate_reply_classification("Yes, but please remove me from your list.",{"classification":"interested"})
    assert r["classification"]=="not_interested"
    assert r["validated"] is False
    assert "CLASSIFICATION_CONFLICTS_WITH_OPT_OUT" in r["reasons"]

def test_reply_negative_overrides_interested_proposal():
    from src.reply_booking import validate_reply_classification
    r=validate_reply_classification("No thanks, we're not interested.",{"classification":"interested"})
    assert r["classification"]=="not_interested" and r["validated"] is False

def test_reply_question_classification():
    from src.reply_booking import validate_reply_classification
    r=validate_reply_classification("How much does the service cost?",{"classification":"question"})
    assert r["validated"] is True and r["classification"]=="question"

def test_interested_reply_can_become_booking_ready_with_complete_fields():
    from src.reply_booking import validate_reply_classification,booking_readiness
    c=validate_reply_classification("Yes, let's schedule a call tomorrow.",{"classification":"interested"})
    b=booking_readiness(c,{"start":"2026-09-23T14:00:00","end":"2026-09-23T14:30:00","timezone":"America/New_York","attendee_email":"owner@example.com"})
    assert c["validated"] is True and b["booking_ready"] is True

def test_question_cannot_be_booking_ready():
    from src.reply_booking import validate_reply_classification,booking_readiness
    c=validate_reply_classification("What does this cost?",{"classification":"question"})
    b=booking_readiness(c,{"start":"2026-09-23T14:00:00","end":"2026-09-23T14:30:00","timezone":"America/New_York","attendee_email":"owner@example.com"})
    assert b["booking_ready"] is False and "NOT_INTERESTED_FOR_BOOKING" in b["reasons"]

def test_booking_receipt_requires_provider_event_id():
    from src.reply_booking import validate_booking_receipt
    assert validate_booking_receipt({"ok":True})["validated"] is False
    assert validate_booking_receipt({"ok":True,"event_id":"evt-1"})["validated"] is True


def _booking_ready():
    return {"ok":True,"validated":True,"booking_ready":True,"start":"2026-09-23T14:00:00-04:00","end":"2026-09-23T14:30:00-04:00","timezone":"America/New_York","attendee_email":"owner@example.com"}

def test_calendar_booking_checks_availability_before_create():
    from src.calendar_booking import execute_booking
    calls=[]
    def availability(req):
        calls.append("availability");return {"ok":True,"available":True,"checked_start":req["start"],"checked_end":req["end"]}
    def create(req):
        calls.append("create");return {"ok":True,"event_id":"evt1","event_url":"https://calendar.google.com/event?eid=x","start":req["start"],"end":req["end"]}
    r=execute_booking(_booking_ready(),availability,create)
    assert r["stage"]=="booked" and calls==["availability","create"]

def test_calendar_booking_never_creates_when_busy():
    from src.calendar_booking import execute_booking
    calls=[]
    def create(req):calls.append("create");return {}
    r=execute_booking(_booking_ready(),lambda req:{"ok":True,"available":False,"checked_start":req["start"],"checked_end":req["end"]},create)
    assert r["stage"]=="unavailable" and calls==[]

def test_calendar_booking_fails_closed_on_availability_error():
    from src.calendar_booking import execute_booking
    calls=[]
    r=execute_booking(_booking_ready(),lambda req:{"ok":False,"available":False},lambda req:calls.append("create"))
    assert r["ok"] is False and calls==[]

def test_calendar_event_receipt_must_match_requested_window():
    from src.calendar_booking import execute_booking
    r=execute_booking(_booking_ready(),lambda req:{"ok":True,"available":True,"checked_start":req["start"],"checked_end":req["end"]},lambda req:{"ok":True,"event_id":"evt1","start":"2026-09-23T15:00:00-04:00","end":req["end"]})
    assert r["stage"]=="create_failed"
    assert "START_RECEIPT_MISMATCH" in r["booking_receipt"]["reasons"]

def test_calendar_event_requires_durable_event_id():
    from src.calendar_booking import execute_booking
    r=execute_booking(_booking_ready(),lambda req:{"ok":True,"available":True,"checked_start":req["start"],"checked_end":req["end"]},lambda req:{"ok":True,"start":req["start"],"end":req["end"]})
    assert r["stage"]=="create_failed" and "MISSING_EVENT_ID" in r["booking_receipt"]["reasons"]

def test_invalid_booking_ready_receipt_never_calls_provider():
    from src.calendar_booking import execute_booking
    calls=[]
    req=_booking_ready();req["validated"]=False
    r=execute_booking(req,lambda req:calls.append("availability"),lambda req:calls.append("create"))
    assert r["stage"]=="blocked" and calls==[]


def test_reply_booking_handoff_books_only_after_availability_and_receipt():
    from src.reply_booking_handoff import process_reply_to_booking
    calls=[]
    result=process_reply_to_booking(
        reply_text="Yes, let's schedule a call.",
        proposed_classification={"classification":"interested"},
        proposed_booking={"start":"2026-09-23T14:00:00-04:00","end":"2026-09-23T14:30:00-04:00","timezone":"America/New_York","attendee_email":"owner@example.com"},
        availability_func=lambda req:(calls.append("availability") or {"ok":True,"available":True,"checked_start":req["start"],"checked_end":req["end"]}),
        event_create_func=lambda req:(calls.append("create") or {"ok":True,"event_id":"fake-event","start":req["start"],"end":req["end"]}),
    )
    assert result["stage"]=="booked" and calls==["availability","create"]

def test_reply_booking_handoff_question_never_calls_calendar():
    from src.reply_booking_handoff import process_reply_to_booking
    calls=[]
    result=process_reply_to_booking(
        reply_text="How much does this cost?",proposed_classification={"classification":"question"},proposed_booking={},
        availability_func=lambda req:calls.append("availability"),event_create_func=lambda req:calls.append("create"))
    assert result["stage"]=="question" and calls==[]

def test_reply_booking_handoff_not_interested_never_calls_calendar():
    from src.reply_booking_handoff import process_reply_to_booking
    calls=[]
    result=process_reply_to_booking(
        reply_text="No thanks, not interested.",proposed_classification={"classification":"not_interested"},proposed_booking={},
        availability_func=lambda req:calls.append("availability"),event_create_func=lambda req:calls.append("create"))
    assert result["stage"]=="not_interested" and calls==[]

def test_reply_booking_handoff_incomplete_time_never_calls_calendar():
    from src.reply_booking_handoff import process_reply_to_booking
    calls=[]
    result=process_reply_to_booking(
        reply_text="Yes, let's talk.",proposed_classification={"classification":"interested"},
        proposed_booking={"timezone":"America/New_York","attendee_email":"owner@example.com"},
        availability_func=lambda req:calls.append("availability"),event_create_func=lambda req:calls.append("create"))
    assert result["stage"]=="interested" and result["booking_attempted"] is False and calls==[]


def test_smart_search_accepts_bounded_runtime_budget():
    import inspect, smart_search
    sig=inspect.signature(smart_search._smart_search)
    assert "runtime_budget" in sig.parameters
    assert sig.parameters["runtime_budget"].default==25

def test_followup_smoke_probe_is_noop_source_guard_present():
    import inspect, outreach_automation
    src=inspect.getsource(outreach_automation.process_followups)
    assert "AI-Ops-Smoke-Test/" in src
    assert '"execution":"skipped"' in src


def test_suppression_gate_blocks_opted_out_recipient():
    from src.outreach_safety import suppression_gate
    r=suppression_gate("Owner@Example.com ",True)
    assert r["ok"] is False and r["recipient"]=="owner@example.com"
    assert "RECIPIENT_SUPPRESSED" in r["reasons"]

def test_suppression_gate_allows_valid_unsuppressed_recipient():
    from src.outreach_safety import suppression_gate
    r=suppression_gate("owner@example.com",False)
    assert r["ok"] is True

def test_send_key_is_deterministic_and_sequence_specific():
    from src.outreach_safety import send_key
    a=send_key(lead_id=7,kind="followup",sequence=1,recipient="Owner@Example.com")
    b=send_key(lead_id=7,kind="followup",sequence=1,recipient="owner@example.com")
    c=send_key(lead_id=7,kind="followup",sequence=2,recipient="owner@example.com")
    assert a==b and a!=c

def test_sent_attempt_blocks_duplicate():
    from src.outreach_safety import send_attempt_gate
    r=send_attempt_gate("sent")
    assert r["allowed"] is False and r["reason"]=="DUPLICATE_ALREADY_SENT"

def test_pending_or_uncertain_attempt_fails_closed():
    from src.outreach_safety import send_attempt_gate
    assert send_attempt_gate("pending")["allowed"] is False
    assert send_attempt_gate("uncertain")["allowed"] is False

def test_failed_attempt_can_be_explicitly_retried():
    from src.outreach_safety import send_attempt_gate
    assert send_attempt_gate("failed")["allowed"] is True


def _b64(s):
    import base64
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")

def test_gmail_parser_prefers_full_plain_body_over_snippet():
    from src.gmail_reply_parser import message_to_evidence
    m={"id":"m1","threadId":"t1","snippet":"hello","payload":{"headers":[{"name":"From","value":"Owner <owner@example.com>"}],"mimeType":"multipart/alternative","parts":[{"mimeType":"text/plain","body":{"data":_b64("Please remove me from your list")}},{"mimeType":"text/html","body":{"data":_b64("<b>different</b>")}}]}}
    r=message_to_evidence(m)
    assert r["text"]=="Please remove me from your list"
    assert r["body_source"]=="text/plain" and r["from_email"]=="owner@example.com"

def test_gmail_parser_falls_back_to_html_text():
    from src.gmail_reply_parser import message_to_evidence
    m={"id":"m2","payload":{"headers":[],"mimeType":"text/html","body":{"data":_b64("<p>No more emails please</p>")}}}
    r=message_to_evidence(m)
    assert "No more emails please" in r["text"] and r["body_source"]=="text/html"

def test_full_body_optout_is_detected_even_when_snippet_would_not_show_it():
    from src.gmail_reply_parser import message_to_evidence
    from src.followup_control import classify_inbound
    m={"id":"m3","threadId":"t3","snippet":"Thanks for reaching out","payload":{"headers":[{"name":"From","value":"Owner <owner@example.com>"}],"mimeType":"text/plain","body":{"data":_b64("Thanks for reaching out. Please unsubscribe me.")}}}
    e=message_to_evidence(m)
    r=classify_inbound([e],sender_email="sales@example.com")
    assert r["opted_out"] is True and r["reason"]=="OPT_OUT"

def test_exact_sender_comparison_does_not_use_substring_matching():
    from src.followup_control import classify_inbound
    r=classify_inbound([{"message_id":"m4","from":"Other <not-sales@example.com>","from_email":"not-sales@example.com","text":"hello"}],sender_email="sales@example.com")
    assert r["replied"] is True


def test_auto_router_negative_beats_interest():
    from src.automatic_reply_router import classify_reply
    r=classify_reply("Yes, but no thanks, we're not interested.")
    assert r["classification"]=="not_interested"

def test_auto_router_question_routes_question_even_with_interest_word():
    from src.automatic_reply_router import classify_reply
    r=classify_reply("Yes, how much does it cost?")
    assert r["classification"]=="question"

def test_auto_router_clear_interest():
    from src.automatic_reply_router import classify_reply
    r=classify_reply("Sounds good, let's talk.")
    assert r["classification"]=="interested"

def test_auto_router_unclear_fails_to_review_without_llm():
    from src.automatic_reply_router import classify_reply
    r=classify_reply("Received.")
    assert r["classification"]=="unclear"

def test_booking_extraction_requires_explicit_iso_times_and_timezone():
    from src.automatic_reply_router import extract_explicit_booking
    vague=extract_explicit_booking("Tomorrow afternoon works.")
    assert vague=={"start":"","end":"","timezone":""}
    exact=extract_explicit_booking("2026-09-23T14:00:00-04:00 to 2026-09-23T14:30:00-04:00 America/New_York")
    assert exact["start"]=="2026-09-23T14:00:00-04:00"
    assert exact["end"]=="2026-09-23T14:30:00-04:00"
    assert exact["timezone"]=="America/New_York"


def test_booking_key_is_reply_and_time_specific():
    from src.booking_safety import booking_key
    a=booking_key(lead_id=1,reply_message_id="m1",start="s1",end="e1",attendee="A@EXAMPLE.COM")
    b=booking_key(lead_id=1,reply_message_id="m1",start="s1",end="e1",attendee="a@example.com")
    c=booking_key(lead_id=1,reply_message_id="m2",start="s1",end="e1",attendee="a@example.com")
    d=booking_key(lead_id=1,reply_message_id="m1",start="s2",end="e1",attendee="a@example.com")
    assert a==b and a!=c and a!=d

def test_google_event_id_is_deterministic_and_safe_subset():
    from src.booking_safety import booking_key,google_event_id
    k=booking_key(lead_id=1,reply_message_id="m1",start="s",end="e",attendee="a@example.com")
    eid=google_event_id(k)
    assert eid==google_event_id(k)
    assert eid.startswith("aocc") and len(eid)<=64
    assert all(ch in "0123456789abcdef" for ch in eid[4:])

def test_pending_and_uncertain_booking_require_reconciliation():
    from src.booking_safety import attempt_gate
    assert attempt_gate("pending")["reconcile"] is True
    assert attempt_gate("uncertain")["reconcile"] is True
    assert attempt_gate("confirmed")["reconcile"] is True
    assert attempt_gate("failed")["allowed"] is True


def test_outreach_source_no_longer_score_qualifies_new_lead():
    import inspect,outreach_automation
    src=inspect.getsource(outreach_automation.create_outreach_lead)
    assert 'status="needs_evidence"' in src
    assert "_store_qualification(lead,data)" in src
    assert "status=_rank_status(score)" not in src

def test_draft_requires_qualification_receipt():
    import inspect,outreach_automation
    src=inspect.getsource(outreach_automation.draft_outreach)
    assert "_qualification_gate(lead)" in src
    assert "evidence-validated qualification is required before drafting" in src

def test_send_requires_qualification_receipt_not_score():
    import inspect,outreach_automation
    src=inspect.getsource(outreach_automation.send_outreach)
    assert "_qualification_gate(lead)" in src
    assert "evidence-validated qualification is required before send" in src
    assert "lead.score < AUTO_SEND_MIN_SCORE" not in src


def test_operational_state_projects_pipeline_statuses():
    from src.operational_state import project_stage
    assert project_stage("qualified")=="qualified"
    assert project_stage("drafted")=="outreach_ready"
    assert project_stage("sent")=="contacted"
    assert project_stage("followup_sent")=="followup"
    assert project_stage("booked")=="booked"

def test_uncertain_side_effects_go_to_attention():
    from src.operational_state import state_snapshot
    assert state_snapshot(status="sent",send_status="uncertain")["stage"]=="needs_attention"
    assert state_snapshot(status="booking_ready",booking_status="pending")["attention_reason"]=="BOOKING_RECONCILIATION_REQUIRED"

def test_unknown_status_fails_to_attention():
    from src.operational_state import state_snapshot
    r=state_snapshot(status="mystery")
    assert r["needs_attention"] is True and r["attention_reason"]=="UNKNOWN_OPERATIONAL_STATE"

def test_failed_send_requires_operator_review_before_retry():
    import inspect,outreach_automation
    src=inspect.getsource(outreach_automation._safe_send)
    assert "FAILED_ATTEMPT_REQUIRES_OPERATOR_REVIEW" in src
    assert "CONCURRENT_SEND_ATTEMPT_EXISTS" in src

def test_attention_endpoint_exists():
    import inspect,outreach_automation
    src=inspect.getsource(outreach_automation.outreach_needs_attention)
    assert "_operational_snapshot" in src


def test_operator_dashboard_exposes_source_backed_records():
    import inspect,outreach_automation
    src=inspect.getsource(outreach_automation._dashboard_record)
    assert "OutreachQualificationReceipt" in src
    assert "OutreachSendAttempt" in src
    assert "OutreachReplyEvidence" in src
    assert "OutreachBookingAttempt" in src

def test_operator_dashboard_ui_escapes_dynamic_values():
    import inspect,outreach_automation
    src=inspect.getsource(outreach_automation.operator_dashboard)
    assert "const esc=" in src
    assert "/api/operator/dashboard" in src
    assert "Evidence & receipts" in src

def test_operator_dashboard_data_uses_operational_attention():
    import inspect,outreach_automation
    src=inspect.getsource(outreach_automation.operator_dashboard_data)
    assert "needs_attention" in src
    assert "_dashboard_record" in src
