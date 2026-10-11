import json
from datetime import datetime,timedelta,timezone
import pytest
import smart_search as search
from src.enrichment import enrich_lead,validated_payload
from src.grounded_reply import routine_answer
from src.scheduling_dates import interpret_booking

NOW=datetime(2030,1,1,tzinfo=timezone.utc)


def contact(**changes):
    row={"url":"https://acme.com/contact","candidate_name":"Acme","title":"Acme","page_text":"Acme Norfolk VA owner@acme.com (757) 555-1212","directly_fetched":True,"http_status":200,"observed_at":datetime.now(timezone.utc).isoformat()}
    row.update(changes);return row


@pytest.mark.parametrize("changes",[{"directly_fetched":False},{"http_status":404},{"rag_retrieved":True},{"observed_at":(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()}])
def test_contact_requires_current_fetched_page(changes):
    row=contact(**changes)
    assert not search._attach_source_contacts([{"title":"Acme","website":"https://acme.com"}],[row],"Norfolk VA")[0]["contacts"]
    assert not validated_payload(enrich_lead({"company":"Acme","location":"Norfolk VA"},[row]))


def test_direct_verified_source_can_match_contacts_without_extraction_label():
    source=contact();source.pop("candidate_name")
    result=search._attach_source_contacts([{"title":"Acme","supporting_urls":[source["url"]]}],[source],"Norfolk VA")[0]
    assert result["contacts"][0]["email"]=="owner@acme.com"
    assert result["contacts"][0]["status"]=="source_observed_deliverability_unconfirmed"


def test_snippet_cannot_supply_contact_missing_from_real_page():
    row=contact(page_text="Acme Norfolk VA",subtitle="fake@acme.com",snippet="madeup@acme.com")
    assert not search._attach_source_contacts([{"title":"Acme","website":"https://acme.com"}],[row],"Norfolk VA")[0]["contacts"]
    assert "email" not in validated_payload(enrich_lead({"company":"Acme"},[row]))


def test_decision_maker_requires_explicit_name_title_and_local_context():
    lead={"company":"Acme","location":"Norfolk VA"}
    assert "decision_maker" not in validated_payload(enrich_lead(lead,[contact(page_text="Acme Norfolk VA General Manager. Our Copper River team can help.")]))
    payload=validated_payload(enrich_lead(lead,[contact(page_text="Acme Norfolk VA Jane Doe, CEO. owner@acme.com")]))
    assert payload["decision_maker"]=="Jane Doe"


def test_only_approved_exact_business_facts_can_answer(monkeypatch):
    records=[{"approved":True,"questions":["What services do you offer?"],"answer":"Approved services only."}]
    monkeypatch.setenv("AUTOMAKE_APPROVED_BUSINESS_FAQ",json.dumps(records))
    assert routine_answer("What services do you offer?")=="Approved services only."
    assert not routine_answer("What services do you offer, and what does it cost?")
    records[0]["approved"]=False
    monkeypatch.setenv("AUTOMAKE_APPROVED_BUSINESS_FAQ",json.dumps(records))
    assert not routine_answer("What services do you offer?")


def test_expired_conflicting_or_malformed_approved_facts_fail_closed(monkeypatch):
    for records in ["bad",json.dumps([{"approved":True,"questions":["What is your price?"],"answer":"Old price","expires_at":"2000-01-01T00:00:00Z"}]),json.dumps([{"approved":True,"questions":["What is your price?"],"answer":a} for a in ["A","B"]])]:
        monkeypatch.setenv("AUTOMAKE_APPROVED_BUSINESS_FAQ",records)
        assert not routine_answer("What is your price?")


@pytest.mark.parametrize("text",["January 10 2030 at 2 pm America/New_York","2030-01-10 at 2:00 pm America/New_York"])
def test_unambiguous_full_dates_are_consistent(text):
    proof=interpret_booking(text,NOW)
    assert proof["ready"] and proof["start"]=="2030-01-10T14:00:00-05:00"


@pytest.mark.parametrize("text,reason",[("Tomorrow at 2 pm","RELATIVE_DATE_REQUIRES_CONFIRMATION"),("January 10 2030 at 2 pm or 4 pm America/New_York","ONE_FULL_DATE_AND_TIME_REQUIRED"),("January 10 2030 at 2 pm PST","AMBIGUOUS_TIMEZONE_ABBREVIATION"),("2030-01-10T14:00:00-04:00 to 2030-01-10T14:30:00-04:00 America/New_York","OFFSET_TIMEZONE_CONFLICT"),("March 10 2030 at 2:30 am America/New_York","NONEXISTENT_LOCAL_TIME"),("November 3 2030 at 1:30 am America/New_York","AMBIGUOUS_LOCAL_TIME")])
def test_ambiguous_dates_require_clear_clarification(text,reason):
    proof=interpret_booking(text,NOW)
    assert not proof["ready"] and proof["reason"]==reason and proof["clarification"]


def test_quoted_dates_do_not_schedule_without_current_request():
    proof=interpret_booking("Thanks.\n> 2030-01-10T14:00:00-05:00 to 2030-01-10T14:30:00-05:00 America/New_York",NOW)
    assert not proof["ready"]


def test_european_timezone_is_respected_not_replaced_by_business_default():
    proof=interpret_booking("January 10 2030 at 2 pm Europe/London",NOW)
    assert proof["ready"] and proof["start"]=="2030-01-10T14:00:00+00:00" and proof["timezone"]=="Europe/London"


def test_weekday_date_conflict_is_not_silently_ignored():
    assert not interpret_booking("Friday January 10 2030 at 2 pm America/New_York",NOW)["ready"]


def test_contact_followups_only_fetch_explicit_owned_domain_with_fresh_proof(monkeypatch):
    import time
    seen=[]
    def snapshot(url):
        seen.append(url)
        return contact(url=url,resolved_url=url)
    monkeypatch.setattr(search,"_page_snapshot",snapshot)
    rows=[{"title":"Acme","classification":"Verified Lead","supporting_urls":["https://acme.com/jobs/1"]}]
    sources=[contact(url="https://acme.com/jobs/1")]
    extra=search._contact_followups(rows,sources,time.monotonic()+8)
    assert seen==["https://acme.com/contact","https://acme.com/"]
    assert extra and all(row["candidate_name"]=="Acme" for row in extra)
    result=search._attach_source_contacts(rows,sources+extra,"Norfolk VA")[0]
    assert any(c.get("email")=="owner@acme.com" for c in result["contacts"])


def test_contact_followup_redirect_cannot_attach_another_company(monkeypatch):
    import time
    monkeypatch.setattr(search,"_page_snapshot",lambda url:contact(resolved_url="https://other.com/contact",page_text="Other Company Norfolk VA owner@other.com"))
    rows=[{"title":"Acme","classification":"Verified Lead","website":"https://acme.com"}]
    assert not search._contact_followups(rows,[],time.monotonic()+8)


def test_invalid_booking_config_fails_without_auto_answer(monkeypatch):
    monkeypatch.setenv("BOOKING_DURATION_MINUTES","bad")
    assert not routine_answer("How long is the call?")
    monkeypatch.setenv("BOOKING_TIMEZONE","Unknown/Zone")
    assert not routine_answer("What timezone are you in?")


def test_existing_contact_cannot_be_reconstructed_from_invoice_digits_or_image_name():
    row=contact(page_text="Acme. Invoice 757 and order 555 and item 1212. Asset logo@acme.com.png")
    payload=validated_payload(enrich_lead({"company":"Acme","phone":"757-555-1212","email":"logo@acme.com"},[row]))
    assert "phone" not in payload and "email" not in payload


def test_duration_crossing_clock_change_uses_real_elapsed_minutes(monkeypatch):
    monkeypatch.setenv("BOOKING_DURATION_MINUTES","30")
    proof=interpret_booking("March 10 2030 at 1:45 am America/New_York",NOW)
    assert proof["ready"] and proof["end"]=="2030-03-10T03:15:00-04:00"


@pytest.mark.parametrize("zone",["america/los_angeles","UTC+3","HST"])
def test_explicit_unresolved_timezone_never_falls_back_to_business_zone(zone):
    assert not interpret_booking("January 10 2030 at 2 pm "+zone,NOW)["ready"]


@pytest.mark.parametrize("text",[
    "January 10 2030 or January 11 2030 at 2 pm America/New_York",
    "2030-01-10 or 2030-01-11 at 2 pm America/New_York",
    "January 10 2030 at 2 pm or 2030-01-11 America/New_York",
    "2030-01-10T14:00:00-05:00 to 2030-01-10T14:30:00-05:00 America/New_York or January 11 2030",
])
def test_unpaired_alternative_date_requires_clarification(text):
    assert not interpret_booking(text,NOW)["ready"]


@pytest.mark.parametrize("address",["10.0.0.1","169.254.169.254","127.0.0.1","::1","::ffff:10.0.0.1"])
def test_public_fetch_rejects_private_resolved_addresses(monkeypatch,address):
    from src import public_fetch
    monkeypatch.setattr(public_fetch.socket,"getaddrinfo",lambda *a,**k:[(0,0,0,"",(address,80))])
    with pytest.raises(ValueError):public_fetch.public_destination("http://acme.com/contact")


def test_public_fetch_pins_dns_and_rejects_private_redirect_before_request(monkeypatch):
    from src import public_fetch
    seen=[]
    def resolve(host,*a,**k):
        return [(0,0,0,"",("93.184.216.34" if host=="acme.com" else "169.254.169.254",80))]
    class Response:
        status=302
        headers={"location":"http://metadata.local/latest"}
        def close(self):pass
    class Pool:
        def __init__(self,address,port,**kwargs):seen.append((address,port,kwargs))
        def urlopen(self,method,path,**kwargs):
            assert kwargs["redirect"] is False and kwargs["headers"]["Host"]=="acme.com"
            return Response()
        def close(self):pass
    monkeypatch.setattr(public_fetch.socket,"getaddrinfo",resolve)
    monkeypatch.setattr(public_fetch.urllib3,"HTTPSConnectionPool",Pool)
    with pytest.raises(ValueError):public_fetch.public_get("https://acme.com/contact")
    assert seen==[("93.184.216.34",443,{"server_hostname":"acme.com","assert_hostname":"acme.com","cert_reqs":"CERT_REQUIRED"})]


def test_public_fetch_rejects_mixed_public_private_dns(monkeypatch):
    from src import public_fetch
    monkeypatch.setattr(public_fetch.socket,"getaddrinfo",lambda *a,**k:[(0,0,0,"",("93.184.216.34",80)),(0,0,0,"",("10.0.0.1",80))])
    with pytest.raises(ValueError):public_fetch.public_destination("https://acme.com")


def test_public_fetch_preserves_valid_public_redirect_and_bounded_body(monkeypatch):
    from src import public_fetch
    seen=[]
    monkeypatch.setattr(public_fetch.socket,"getaddrinfo",lambda *a,**k:[(0,0,0,"",("93.184.216.34",80))])
    class Response:
        def __init__(self,path):
            self.status=302 if path=="/contact" else 200
            self.headers={"location":"/contacts"} if self.status==302 else {"content-type":"text/html"}
        def read(self,size,**kwargs):
            assert size==100000
            return b"<html>Acme</html>"
        def close(self):pass
    class Pool:
        def __init__(self,*a,**k):pass
        def urlopen(self,method,path,**kwargs):seen.append(path);return Response(path)
        def close(self):pass
    monkeypatch.setattr(public_fetch.urllib3,"HTTPSConnectionPool",Pool)
    result=public_fetch.public_get("https://acme.com/contact")
    assert result.status_code==200 and result.url=="https://acme.com/contacts" and result.text=="<html>Acme</html>"
    assert seen==["/contact","/contacts"]
