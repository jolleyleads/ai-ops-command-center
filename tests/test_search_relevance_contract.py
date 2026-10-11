from datetime import datetime, timedelta, timezone
import pytest
import smart_search as search
from src.job_evidence import check_job_evidence
from src.record_evidence import check_record_evidence, record_receipt_is_current
from scripts.smart_search_smoke import validate_payload


NOW=datetime.now(timezone.utc)


def record(live_job_page,city="Norfolk",state="VA",body=None):
    return live_job_page(company="Acme",title="Acme Electrical Permit 123",city=city,state=state,body=body or f"<h1>Acme Electrical Permit 123</h1><p>Project location: {city}, {state};</p><p>Date issued: {NOW.date().isoformat()}</p>")


def payload(rows,intent="jobs",query="machine learning engineer jobs",location="Norfolk, VA"):
    return {"intent":intent,"query":query,"location":location,"configured":True,"agent_mode":True,"verification_gate":True,"source":"web_search","count":len(rows),"verified_count":sum(r.get("classification")=="Verified Lead" for r in rows),"results":rows}


def test_smoke_rejects_unrelated_unverified_job_not_only_verified_labels():
    assert validate_payload(payload([{"title":"Accountant","classification":"Candidate"}]),"jobs")


def test_smoke_accepts_current_matching_job_and_rejects_changed_city_and_role(live_job_page):
    source=live_job_page(title="Machine Learning Engineer")
    proof=check_job_evidence(source,"machine learning engineer jobs","Norfolk, VA","Acme")
    row={"title":"Acme","url":source["url"],"classification":"Verified Lead","job_validation":proof}
    assert validate_payload(payload([row]),"jobs")==[]
    assert validate_payload(payload([row],location="Portsmouth, VA"),"jobs")
    assert validate_payload(payload([row],query="accountant jobs"),"jobs")
    proof["checked_at"]=(NOW-timedelta(hours=2)).isoformat()
    assert validate_payload(payload([row]),"jobs")


def test_scope_removes_unrelated_and_unproven_job_candidates(live_job_page):
    source=live_job_page(title="Machine Learning Engineer")
    proof=check_job_evidence(source,"machine learning engineer jobs","Norfolk, VA","Acme")
    rows=[{"title":"Acme","job_validation":proof},{"title":"Unrelated accountant"}]
    kept,excluded=search._scope_search_results(rows,"machine learning engineer jobs","Norfolk, VA",[])
    assert len(kept)==1 and len(excluded)==1
    assert kept[0]["relevance_status"]=="source_matched"


def test_company_hiring_search_cannot_display_unproven_role_candidates():
    kept,excluded=search._scope_search_results([{"title":"Generic company","classification":"Candidate"}],"Find companies hiring automation engineers","Norfolk, VA",[])
    assert not kept and len(excluded)==1


def test_current_record_matches_exact_city_and_preserves_real_record_date(live_job_page):
    source=record(live_job_page)
    proof=check_record_evidence(source,"recent electrical permits issued","Norfolk, VA")
    assert proof["ok"] and proof["record_date"]==NOW.date().isoformat()
    assert record_receipt_is_current(proof,"recent electrical permits issued","Norfolk, VA")
    assert not record_receipt_is_current(proof,"recent electrical permits issued","Portsmouth, VA")


@pytest.mark.parametrize("city,state",[("Boston","MA"),("Norfolk","NE"),("Chesapeake","VA")])
def test_record_wrong_city_or_state_cannot_promote(live_job_page,city,state):
    assert not check_record_evidence(record(live_job_page,city,state),"recent electrical permits issued","Norfolk, VA")["ok"]


def test_footer_and_other_record_city_cannot_supply_worksite(live_job_page):
    source=record(live_job_page,body=f'<h1>Acme Electrical Permit 123</h1><p>Project location: Boston, MA;</p><p>Date issued: {NOW.date().isoformat()}</p><footer>Norfolk, VA</footer>')
    assert not check_record_evidence(source,"recent permits","Norfolk, VA")["ok"]
    source=record(live_job_page,body=f'<h1>Acme Electrical Permit 123</h1><p>Project location: Boston, MA;</p><p>Project location: Norfolk, VA;</p><p>Date issued: {NOW.date().isoformat()}</p>')
    assert not check_record_evidence(source,"recent permits","Norfolk, VA")["ok"]


@pytest.mark.parametrize("days",[100,-5])
def test_recent_record_old_or_future_date_cannot_promote(live_job_page,days):
    date=(NOW-timedelta(days=days)).date().isoformat()
    source=record(live_job_page,body=f'<h1>Acme Electrical Permit 123</h1><p>Project location: Norfolk, VA;</p><p>Date issued: {date}</p>')
    assert not check_record_evidence(source,"recent electrical permits","Norfolk, VA")["ok"]


def test_recent_record_unknown_date_remains_unknown_not_new(live_job_page):
    source=record(live_job_page,body='<h1>Acme Electrical Permit 123</h1><p>Project location: Norfolk, VA;</p>')
    assert not check_record_evidence(source,"recent permits","Norfolk, VA")["ok"]
    proof=check_record_evidence(source,"electrical permits","Norfolk, VA")
    assert proof["ok"] and proof["record_date"] is None


def test_model_verdict_cannot_promote_other_city_permit(live_job_page):
    source=record(live_job_page,"Boston","MA")
    verdict={"verified_results":[{"url":source["url"],"entity_name":"Acme","claim":"Recent Norfolk permit","supporting_urls":[source["url"]]}]}
    assert search._verified_results([source],verdict,"recent electrical permits","Norfolk, VA")==[]


def test_scope_and_smoke_remove_other_city_permit(live_job_page):
    source=record(live_job_page,"Boston","MA")
    rows=[{"title":"Acme","url":source["url"]}]
    assert search._scope_search_results(rows,"recent electrical permits","Norfolk, VA",[source])[0]==[]
    proof=check_record_evidence(record(live_job_page),"recent permits","Norfolk, VA")
    row={"title":"Acme","record_validation":proof}
    assert validate_payload(payload([row],"permits","recent permits"),"permits")==[]
    assert validate_payload(payload([row],"permits","recent permits","Chesapeake, VA"),"permits")


def test_record_snippet_and_stale_fetch_cannot_prove_current_locality(live_job_page):
    source=record(live_job_page);source["directly_fetched"]=False
    assert not check_record_evidence(source,"permits","Norfolk, VA")["ok"]
    source["directly_fetched"]=True;source["job_page_fetched_at"]=(NOW-timedelta(hours=2)).isoformat()
    assert not check_record_evidence(source,"permits","Norfolk, VA")["ok"]


def test_multiple_same_city_records_cannot_pool_dates(live_job_page):
    source=record(live_job_page,body=f'<h1>Acme Electrical Permit 123</h1><p>Project location: Norfolk, VA;</p><section>Permit 456. Date issued: {NOW.date().isoformat()}</section>')
    assert not check_record_evidence(source,"recent permits","Norfolk, VA")["ok"]


def test_malformed_record_receipt_url_fails_without_exception(live_job_page):
    proof=check_record_evidence(record(live_job_page),"permits","Norfolk, VA")
    proof["source_url"]="https://["
    assert not record_receipt_is_current(proof,"permits","Norfolk, VA")


def test_production_acceptance_polling_import_needs_no_application_packages():
    import subprocess,sys
    from pathlib import Path
    result=subprocess.run([sys.executable,"-S","-c","from scripts.campaign_acceptance import acceptance_request_key; assert acceptance_request_key({'GITHUB_SHA':'sha','GITHUB_RUN_ID':'id','GITHUB_RUN_ATTEMPT':'1'}) == 'acceptance-sha-id-1'"],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize("type",["job","web"])
def test_inspected_direct_job_gets_receipt_without_candidate_label(live_job_page,type):
    source=live_job_page(title="Machine Learning Engineer")
    source.pop("candidate_name");source.pop("verification_research")
    row={"type":type,"title":"Machine Learning Engineer","url":source["url"],"classification":"Candidate"}
    kept,excluded=search._scope_search_results([row],"machine learning engineer jobs","Norfolk, VA",[source])
    assert len(kept)==1 and not excluded
    assert kept[0]["company"]=="Acme" and kept[0]["job_validation"]["ok"]
    assert kept[0]["title"]=="Acme" and kept[0]["job_title"]=="Machine Learning Engineer"
    assert kept[0]["classification"]=="Verified Lead"
    assert validate_payload(payload(kept),"jobs")==[]


def test_direct_job_provider_company_cannot_be_overridden_by_page(live_job_page):
    source=live_job_page(title="Machine Learning Engineer")
    row={"type":"job","company":"Other Company","title":"Machine Learning Engineer","url":source["url"]}
    assert not search._scope_search_results([row],"machine learning engineer jobs","Norfolk, VA",[source])[0]


def test_permit_lead_route_and_smoke_require_matching_record_city(live_job_page):
    source=record(live_job_page,"Boston","MA");source["job_detail_text"]+=" Master Electrician permit pulling."
    query="master electrician permit pulling leads"
    assert not search._scope_search_results([{"title":"Acme","url":source["url"]}],query,"Norfolk, VA",[source])[0]
    proof=check_record_evidence(source,query,"Boston, MA")
    assert proof["ok"]
    row={"title":"Acme","record_validation":proof}
    assert validate_payload(payload([row],"permit_leads",query,"Norfolk, VA"),"permit_leads")
    assert validate_payload(payload([row],"permit_leads",query,"Boston, MA"),"permit_leads")==[]


@pytest.mark.parametrize("kind",["Inspection","License"])
def test_inspection_and_license_identifiers_cannot_pool_records(live_job_page,kind):
    source=record(live_job_page,body=f'<h1>Acme {kind} 123</h1><p>Project location: Norfolk, VA;</p><section>{kind} 456. Date issued: {NOW.date().isoformat()}</section>')
    assert not check_record_evidence(source,"recent inspections and licenses","Norfolk, VA")["ok"]


def test_prefixed_and_cross_type_record_ids_remain_distinct(live_job_page):
    source=record(live_job_page,body=f'<h1>Acme Permit No. BLD-123</h1><p>Project location: Norfolk, VA;</p><section>Inspection No. BLD-123. Date issued: {NOW.date().isoformat()}</section>')
    assert not check_record_evidence(source,"recent permits","Norfolk, VA")["ok"]
