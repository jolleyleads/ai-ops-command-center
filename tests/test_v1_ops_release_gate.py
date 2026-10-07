import json
from datetime import datetime, timedelta
import pytest
import outreach_automation as oa
import smart_search
import v1_orchestration as v1


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("OPERATOR_CONTROL_TOKEN","ops-security-test-token")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEY_VERSION","v1")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEYS","v1=ops-test-signing-key")
    monkeypatch.setenv("OUTREACH_CRON_TOKEN","cron-test-token")
    oa.app.config.update(TESTING=True,SECRET_KEY="test-secret",SESSION_COOKIE_SECURE=False)
    with oa.app.app_context():
        oa.db.session.remove();oa.db.drop_all();oa.db.create_all()
        yield
        oa.db.session.remove();oa.db.drop_all()


def lead():
    x=oa.OutreachLead(company="Ops Test",contact_email="owner@example.com",status="review")
    oa.db.session.add(x);oa.db.session.commit();return x


def login(client):
    client.get("/operator/login")
    with client.session_transaction() as s: csrf=s["csrf_token"]
    return client.post("/operator/login",data={"token":"ops-security-test-token","csrf_token":csrf})


def test_login_stores_derived_proof_not_raw_operator_secret(env):
    c=oa.app.test_client();assert login(c).status_code==303
    with c.session_transaction() as s:
        assert s.get("operator_auth")
        assert s.get("operator_auth")!="ops-security-test-token"
        assert "operator_token" not in s


def test_operator_pages_are_no_store_and_clickjacking_blocked(env):
    c=oa.app.test_client();login(c);r=c.get("/operator")
    assert r.status_code==200
    assert "no-store" in r.headers["Cache-Control"]
    assert r.headers["X-Frame-Options"]=="DENY"


def test_operator_control_rejects_missing_csrf(env):
    x=lead();c=oa.app.test_client();login(c)
    r=c.post(f"/operator/leads/{x.id}/control",data={"action":"review"})
    assert r.status_code==403


def test_uncertain_command_surfaces_in_recovery_queue(env):
    x=lead();cmd=oa._enqueue_external_command(x,"gmail_send",{"recipient":"owner@example.com"})
    token=oa._claim_external_command(cmd);oa._finish_external_command(cmd.id,token,{"ok":False,"error":"lost response"})
    c=oa.app.test_client();login(c);r=c.get("/api/operator/recovery")
    data=r.get_json();assert data["alert_count"]==1
    assert data["commands"][0]["kind"]=="gmail_send"


def test_calendar_recovery_uses_deterministic_event_lookup(env,monkeypatch):
    x=lead();cmd=oa._enqueue_external_command(x,"calendar_create",{"provider_idempotency_key":"evt-recover"})
    token=oa._claim_external_command(cmd);oa._finish_external_command(cmd.id,token,{"ok":False,"error":"timeout"})
    monkeypatch.setattr(oa,"get_event",lambda event_id:{"ok":True,"found":True,"event_id":event_id,"event_url":"test"})
    c=oa.app.test_client();login(c)
    with c.session_transaction() as s: csrf=s["csrf_token"]
    r=c.post(f"/api/operator/recovery/{cmd.id}/reconcile",headers={"X-CSRF-Token":csrf})
    assert r.status_code==200 and r.get_json()["status"]=="reconciled"


def test_expired_worker_is_alerted_as_uncertain(env):
    x=lead();cmd=oa._enqueue_external_command(x,"gmail_send",{"recipient":"stuck@example.com"})
    oa._claim_external_command(cmd)
    cmd=oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id);cmd.lease_expires_at=datetime.utcnow()-timedelta(seconds=1);oa.db.session.commit()
    c=oa.app.test_client();login(c);data=c.get("/api/operator/recovery").get_json()
    assert data["alert_count"]==1
    assert oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id).status=="uncertain"


def test_scheduler_same_hour_executes_window_only_once(env,monkeypatch):
    c=oa.app.test_client()
    headers={"X-Outreach-Cron-Token":"cron-test-token"}
    first=c.post("/api/outreach/process-followups",headers=headers,json={})
    second=c.post("/api/outreach/process-followups",headers=headers,json={})
    assert first.status_code==200 and first.get_json()["duplicate_run_suppressed"] is False
    assert second.status_code==200 and second.get_json()["duplicate_run_suppressed"] is True
    assert oa.FollowupSchedulerRun.query.count()==1


def test_scheduler_rejects_wrong_secret(env):
    c=oa.app.test_client()
    assert c.post("/api/outreach/process-followups",headers={"X-Outreach-Cron-Token":"wrong"},json={}).status_code==401


def test_verified_public_email_accepts_contact_probe_tuple(env, monkeypatch):
    monkeypatch.setattr(
        v1,
        "_public_contact_evidence",
        lambda result: (
            [{"url": "https://example.com/contact", "subtitle": "owner@example.com", "text": ""}],
            {"attempted": 1, "budget_exhausted": False},
        ),
    )
    monkeypatch.setattr(v1, "_same_company_domain", lambda email, urls: True)
    email, source = v1._verified_public_email({"company": "Example", "website": "https://example.com"})
    assert email == "owner@example.com"
    assert source == "https://example.com/contact"


def test_verified_public_email_accepts_source_visible_same_domain_email(env, monkeypatch):
    monkeypatch.setattr(v1, "_public_contact_evidence", lambda result: (_ for _ in ()).throw(AssertionError("probe should not run")))
    email, source = v1._verified_public_email({
        "company": "Example HVAC",
        "website": "https://examplehvac.com",
        "evidence": [{"url": "https://examplehvac.com/contact", "snippet": "Contact: sales@examplehvac.com"}],
    })
    assert email == "sales@examplehvac.com"
    assert source == "https://examplehvac.com/contact"


def test_verified_public_email_rejects_source_visible_off_domain_email(env, monkeypatch):
    monkeypatch.setattr(v1, "_public_contact_evidence", lambda result: ([], {"attempted": 0}))
    email, source = v1._verified_public_email({
        "company": "Example HVAC",
        "website": "https://examplehvac.com",
        "evidence": [{"url": "https://examplehvac.com/careers", "snippet": "Apply: recruiter@gmail.com"}],
    })
    assert email == ""
    assert source == ""


def test_verified_public_email_rejects_third_party_evidence_domain_even_when_source_matches(env, monkeypatch):
    monkeypatch.setattr(v1, "_public_contact_evidence", lambda result: ([], {"attempted": 0}))
    email, source = v1._verified_public_email({
        "company": "Shaw Boiler and Mechanical",
        "website": "https://www.shawboiler.com/",
        "evidence": [{"url": "https://www.wayup.com/jobs/example", "snippet": "Privacy: privacy@wayup.com"}],
    })
    assert email == ""
    assert source == ""


def test_verified_public_email_requires_explicit_company_website(env, monkeypatch):
    monkeypatch.setattr(v1, "_public_contact_evidence", lambda result: (_ for _ in ()).throw(AssertionError("probe should not run without company website")))
    email, source = v1._verified_public_email({
        "company": "Example Co",
        "evidence": [{"url": "https://jobs.example.net/posting", "snippet": "hello@jobs.example.net"}],
    })
    assert email == ""
    assert source == ""


def test_outreach_gate_is_universal_for_non_contractor_b2b_search(env):
    payload={"query":"law firms actively hiring paralegals","intent":"law firms actively hiring paralegals","results":[]}
    assert v1._outreach_search(payload) is True


def test_v11_hiring_patterns_are_not_hvac_specific(env):
    import v11_evidence_upgrade as v11
    patterns=v11._intent_patterns("auto repair companies actively hiring mechanics")
    assert patterns
    text="Now hiring experienced mechanics. Apply for an open position today."
    assert any(__import__("re").search(p,text,__import__("re").I|__import__("re").S) for p in patterns)
    assert v11._intent_supported("auto repair companies actively hiring mechanics",text) is True
    assert v11._intent_supported("plumbing companies actively hiring plumbers",text) is False


def test_initial_draft_is_universal_and_not_electrical_specific(env, monkeypatch):
    captured = {}
    def fake_run_ai(*, prompt, instructions):
        captured["prompt"] = prompt
        captured["instructions"] = instructions
        return {"ok": True, "output": json.dumps({"subject": "Hello", "body": "Body"}), "model": "test"}
    monkeypatch.setattr(oa, "run_ai", fake_run_ai)
    x = oa.OutreachLead(company="Example Law", location="Norfolk, VA", score=80, verification="VERIFIED", evidence_json="[]")
    result = oa._draft_email(x)
    assert result["ok"] is True
    combined = (captured["prompt"] + " " + captured["instructions"]).lower()
    assert "master electrician" not in combined
    assert "permit-pulling" not in combined
    assert "verified contractor" not in combined
    assert "business automation" in combined


def test_draft_falls_back_deterministically_when_ai_fails(env, monkeypatch):
    monkeypatch.setattr(oa, "run_ai", lambda **kwargs: {"ok": False, "error": "provider unavailable"})
    x = oa.OutreachLead(company="Example Roofing", location="Chesapeake, VA", score=80, verification="VERIFIED", evidence_json="[]")
    result = oa._draft_email(x)
    assert result["ok"] is True
    assert result["fallback"] is True
    assert result["model"] == "deterministic-fallback"
    assert "Example Roofing" in result["subject"]
    assert "lead generation" in result["body"]


def test_acceptance_pool_is_cross_industry(env):
    from pathlib import Path
    source = Path("customer_demo.py").read_text(encoding="utf-8").lower()
    block = source[source.index("campaign_catalog=["):source.index("attempts=[]", source.index("campaign_catalog=["))]
    assert block.count('actively hiring') >= 12
    assert "accounting firms" in block
    assert "veterinary clinics" in block
    assert "manufacturing companies" in block
    assert "staffing agencies" in block
    assert "territories=[" in block
    assert "rotated[:4]" in block
    assert "outreachlead.query.order_by" in block
    assert "hvac" not in block
    assert "heating and cooling" not in block

def test_active_orchestration_uses_universal_outreach_gate(env):
    source = __import__("inspect").getsource(v1.orchestrate_discovery)
    assert "_outreach_search(payload)" in source
    assert "not_b2b_outreach_search" in source


def test_acceptance_endpoint_iterates_defined_universal_campaign_pool(env):
    from pathlib import Path
    source = Path("customer_demo.py").read_text(encoding="utf-8")
    assert "campaign_catalog=[" in source
    assert "campaign_pool=[" in source
    assert "for controlled in campaign_pool:" in source
    assert "for controlled in campaigns:" not in source

def test_customer_demo_module_compiles(env):
    from pathlib import Path
    source = Path("customer_demo.py").read_text(encoding="utf-8")
    compile(source, "customer_demo.py", "exec")


def test_public_contact_probe_discovers_same_domain_contact_links(env, monkeypatch):
    import outreach_bridge as bridge
    class Resp:
        def __init__(self,url,text):
            self.url=url; self.text=text; self.ok=True; self.headers={"content-type":"text/html"}
    seen=[]
    def fake_get(url,**kwargs):
        seen.append(url)
        if url=="https://example.com/":
            return Resp(url, '<a href="/our-team">Team</a><a href="/reach-us">Contact</a>')
        if url=="https://example.com/reach-us":
            return Resp(url, 'Email us at hello@example.com')
        return Resp(url, 'No contact here')
    monkeypatch.setattr(bridge.requests,"get",fake_get)
    rows,meta=bridge._public_contact_evidence({"title":"Example Co","website":"https://example.com/"})
    assert rows
    assert rows[0]["url"]=="https://example.com/reach-us"
    assert "hello@example.com" in rows[0]["subtitle"]
    assert meta["attempted"] <= bridge.CONTACT_MAX_URLS

def test_public_contact_probe_rejects_off_domain_email(env, monkeypatch):
    import outreach_bridge as bridge
    class Resp:
        ok=True; headers={"content-type":"text/html"}
        def __init__(self,url): self.url=url; self.text="Email vendor@gmail.com"
    monkeypatch.setattr(bridge.requests,"get",lambda url,**kwargs: Resp(url))
    rows,meta=bridge._public_contact_evidence({"title":"Example Co","website":"https://example.com/"})
    assert not any("vendor@gmail.com" in (x.get("subtitle") or "") for x in rows)

def test_public_contact_probe_never_follows_third_party_discovered_links(env, monkeypatch):
    import outreach_bridge as bridge
    class Resp:
        ok=True; headers={"content-type":"text/html"}
        def __init__(self,url,text): self.url=url; self.text=text
    seen=[]
    def fake_get(url,**kwargs):
        seen.append(url)
        return Resp(url,'<a href="https://evil.example/contact">Contact</a>')
    monkeypatch.setattr(bridge.requests,"get",fake_get)
    bridge._public_contact_evidence({"title":"Example Co","website":"https://example.com/"})
    assert not any("evil.example" in x for x in seen)


def test_contact_enrichment_is_deeper_but_still_same_domain(env):
    from pathlib import Path
    source=Path("outreach_bridge.py").read_text(encoding="utf-8")
    assert 'CONTACT_ENRICH_MAX_URLS","8"' in source
    assert 'CONTACT_ENRICH_BUDGET_SECONDS","18"' in source
    assert 'urljoin(root,"staff")' in source
    assert 'urljoin(root,"locations")' in source
    assert "mailto:" in source
    assert "_same_company_domain" in source
    assert "blocked_hosts" in source


def test_orchestration_reports_safe_send_failure_details(env):
    from pathlib import Path
    source=Path("v1_orchestration.py").read_text(encoding="utf-8")
    assert '"reason":"safe_send_failed"' in source
    assert '"stage":_clean(execution.get("stage"),100)' in source
    assert '"gate_reasons"' in source
    assert '"receipt_reasons"' in source
    assert '"provider_error"' in source


def test_failed_provider_receipt_preserves_provider_error(env):
    from src.outreach_execution import execute_outreach_send
    lead={"contact_email":"hello@example.com","subject":"Hello","body":"Body","evidence":[],"source_url":""}
    result=execute_outreach_send(lead,lambda *args: {"ok":False,"error":"Gmail error 401: invalid credentials"})
    assert result["ok"] is False
    assert result["stage"]=="send_failed"
    assert result["error"]=="Gmail error 401: invalid credentials"
    assert "PROVIDER_SEND_FAILED" in result["send_receipt"]["reasons"]


def test_final_send_gate_rejects_off_company_domain_before_provider(env, monkeypatch):
    x=oa.OutreachLead(
        company="Shaw Boiler and Mechanical",
        contact_email="privacy@wayup.com",
        source_url="https://www.shawboiler.com/",
        status="qualified",
    )
    oa.db.session.add(x); oa.db.session.commit()
    monkeypatch.setattr(oa, "_qualification_gate", lambda lead: (_ for _ in ()).throw(AssertionError("domain gate must run first")))
    result=oa._safe_send(x,kind="followup",sequence=1,subject="Follow up",body="Body")
    assert result["ok"] is False
    assert result["stage"] == "blocked"
    assert result["gate"]["reasons"] == ["RECIPIENT_COMPANY_DOMAIN_MISMATCH"]


def test_final_send_gate_accepts_company_domain_and_subdomain_shape(env):
    x=oa.OutreachLead(company="Example",contact_email="hello@mail.example.com",source_url="https://www.example.com/")
    assert oa._recipient_matches_source_domain(x) is True
    x.contact_email="privacy@wayup.com"
    assert oa._recipient_matches_source_domain(x) is False


def test_enrichment_rejects_same_domain_non_outreach_mailboxes(env, monkeypatch):
    monkeypatch.setattr(v1, "_public_contact_evidence", lambda result: ([], {"attempted": 0}))
    for address in ("privacy@example.com","legal@example.com","medicalrecords@example.com","grievance@example.com","jobs@example.com","hr@example.com"):
        email, source = v1._verified_public_email({
            "company":"Example Co","website":"https://example.com/",
            "evidence":[{"url":"https://example.com/contact","snippet":f"Contact {address}"}],
        })
        assert email == "" and source == ""


def test_enrichment_keeps_normal_company_mailboxes(env, monkeypatch):
    monkeypatch.setattr(v1, "_public_contact_evidence", lambda result: ([], {"attempted": 0}))
    for address in ("info@example.com","sales@example.com","hello@example.com","owner@example.com"):
        email, _ = v1._verified_public_email({
            "company":"Example Co","website":"https://example.com/",
            "evidence":[{"url":"https://example.com/contact","snippet":f"Contact {address}"}],
        })
        assert email == address


def test_final_send_gate_rejects_same_domain_non_outreach_mailbox_before_provider(env, monkeypatch):
    x=oa.OutreachLead(company="Example",contact_email="privacy@example.com",source_url="https://example.com/",status="qualified")
    oa.db.session.add(x);oa.db.session.commit()
    monkeypatch.setattr(oa, "_qualification_gate", lambda lead: (_ for _ in ()).throw(AssertionError("purpose mailbox gate must run first")))
    result=oa._safe_send(x,kind="followup",sequence=1,subject="Follow up",body="Body")
    assert result["ok"] is False
    assert result["gate"]["reasons"] == ["RECIPIENT_PURPOSE_MAILBOX_BLOCKED"]


def test_final_mailbox_gate_allows_normal_business_mailboxes(env):
    for address in ("info@example.com","sales@example.com","hello@example.com","owner@example.com"):
        assert oa._recipient_mailbox_allowed(address) is True
