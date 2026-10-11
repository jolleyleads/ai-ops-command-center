from datetime import datetime, timedelta, timezone
import pytest
import commercial_app
import smart_search as search
import v11_evidence_upgrade as campaign
from src.job_evidence import check_job_evidence, receipt_is_current, job_page_metadata, requested_role_terms

NOW=datetime(2026,10,11,4,0,tzinfo=timezone.utc)
QUERY="Find companies currently hiring AI automation engineers in Norfolk, Virginia"


def check(row,query=QUERY,location="Norfolk, VA",company="Acme",now=NOW):
    return check_job_evidence(row,query,location,company,now)


def test_current_matching_job_is_verified_with_separate_dates(live_job_page):
    result=check(live_job_page(now=NOW))
    assert result["ok"] and result["job_title"]=="AI Automation Engineer"
    assert result["job_locations"]==["Norfolk VA US"]
    assert result["date_posted"]!=(result["checked_at"])
    assert receipt_is_current(result,QUERY,"Norfolk, VA",NOW)


@pytest.mark.parametrize("changes,reason",[
    ({"validThrough":(NOW-timedelta(seconds=1)).isoformat()},"job_expired"),
    ({"validThrough":"not-a-date"},"job_expiry_date_invalid"),
    ({"datePosted":(NOW-timedelta(days=91)).isoformat()},"job_posting_older_than_90_days"),
    ({"datePosted":(NOW+timedelta(days=1)).isoformat()},"job_posting_date_in_future"),
    ({"description":"This position is filled. Apply now."},"job_closed_or_unavailable"),
    ({"description":"We are no longer accepting applications."},"job_closed_or_unavailable"),
    ({"hiringOrganization":{"name":"Another Company"}},"job_employer_mismatch"),
    ({"url":"https://acme.example/jobs/another"},"job_detail_page_required"),
])
def test_invalid_job_status_is_never_promoted(live_job_page,changes,reason):
    result=check(live_job_page(now=NOW,changes=changes))
    assert not result["ok"] and reason in result["reasons"]


@pytest.mark.parametrize("apply_html",['<button disabled>Apply now</button>','<a aria-disabled="true" href="/apply">Apply now</a>','<a href="#">Apply now</a>','<button>Apply filters</button>','<fieldset disabled><button>Apply now</button></fieldset>','<div hidden><a href="/apply">Apply now</a></div>','<button style="display: none">Apply now</button>',''])
def test_disabled_hidden_and_unusable_apply_controls_are_not_open_signals(live_job_page,apply_html):
    result=check(live_job_page(now=NOW,apply_html=apply_html))
    assert not result["ok"] and "enabled_application_control_not_observed" in result["reasons"]


@pytest.mark.parametrize("title",["Electrical Automation Engineer","Software Engineer","AI Sales Engineer","Automation Technician"])
def test_all_role_terms_must_match_the_job_title(live_job_page,title):
    row=live_job_page(now=NOW,title=title)
    row["job_detail_text"]+=" Experience with AI automation engineers is useful."
    result=check(row)
    assert not result["ok"] and "requested_role_not_in_job_title" in result["reasons"]


def test_full_ai_name_is_supported_without_arbitrary_semantic_aliases(live_job_page):
    assert check(live_job_page(now=NOW,title="Senior Artificial Intelligence Automation Engineer"))["ok"]


@pytest.mark.parametrize("query,terms",[("machine learning engineer jobs in Norfolk",["machine","learning","engineer"]),("Find AI automation engineer openings in DC",["ai","automation","engineer"]),("jobs for software engineers near Boston",["software","engineers"]),("Find firms hiring veterinary assistants with sources",["veterinary","assistants"])])
def test_role_parsing_covers_job_first_and_role_first_queries(query,terms):
    assert requested_role_terms(query)==terms


@pytest.mark.parametrize("city,state",[("Boston","MA"),("Norfolk","NE"),("Virginia Beach","VA")])
def test_city_and_state_are_bound_to_the_actual_job(live_job_page,city,state):
    row=live_job_page(now=NOW,city=city,state=state)
    row["job_detail_text"]+=" Our headquarters are Norfolk, VA."
    assert not check(row)["ok"]


def test_footer_and_other_job_cannot_supply_city(live_job_page):
    row=live_job_page(now=NOW,city="Boston",state="MA",body='<h1>AI Automation Engineer</h1><p>Acme Boston, MA</p><p>Apply now</p><footer>Norfolk, VA</footer>')
    assert not check(row)["ok"]


def test_conflicting_query_city_and_location_field_do_not_pass(live_job_page):
    assert not check(live_job_page(now=NOW),query="AI automation engineer jobs in Boston, MA")["ok"]


def test_remote_usa_is_not_a_norfolk_job(live_job_page):
    row=live_job_page(now=NOW,changes={"jobLocation":None,"jobLocationType":"TELECOMMUTE","applicantLocationRequirements":{"name":"USA"}})
    assert not check(row,query="AI automation engineer remote jobs in Norfolk")["ok"]


def test_onsite_city_match_cannot_pass_remote_request(live_job_page):
    result=check(live_job_page(now=NOW),query="AI automation engineer remote jobs in Norfolk")
    assert not result["ok"] and "requested_remote_status_unproven" in result["reasons"]


def test_stale_fetch_cached_rag_and_http_errors_fail_closed(live_job_page):
    row=live_job_page(now=NOW)
    assert not check({**row,"job_page_fetched_at":(NOW-timedelta(hours=2)).isoformat()})["ok"]
    assert not check({**row,"rag_retrieved":True})["ok"]
    assert not check({**row,"http_status":404})["ok"]
    assert not check({**row,"directly_fetched":False})["ok"]


def test_missing_publication_date_is_explicit_not_invented(live_job_page):
    result=check(live_job_page(now=NOW,changes={"datePosted":None,"validThrough":None}))
    assert result["ok"] and result["date_posted"] is None
    assert "unconfirmed" in result["freshness_note"]


def test_metadata_cannot_override_visible_wrong_job_or_city(live_job_page):
    row=live_job_page(now=NOW,body='<h1>Electrical Engineer</h1><p>Boston, MA</p>')
    result=check(row)
    assert not result["ok"] and "job_metadata_not_supported_by_visible_page" in result["reasons"]


def test_multiple_postings_cannot_pool_role_city_and_expiry(live_job_page):
    row=live_job_page(now=NOW)
    matching=row["source_job_postings"][0]
    row["source_job_postings"]=[{**matching,"validThrough":(NOW-timedelta(days=1)).isoformat()},{**matching,"title":"Electrical Engineer"},{**matching,"jobLocation":{"address":{"addressLocality":"Boston","addressRegion":"MA"}}}]
    assert not check(row)["ok"]


def test_structured_metadata_and_malformed_types_are_safe():
    raw='<script type="application/ld+json">{"@graph":[{"@type":null},{"@type":17},{"@type":{"bad":1}}]}</script>'
    assert job_page_metadata(raw,"https://acme.example")["source_job_postings"]==[]


def test_semantic_verdict_cannot_override_wrong_role_city_or_closed_job(live_job_page):
    row=live_job_page(city="Boston",state="MA",title="Electrical Engineer")
    verdict={"verified_results":[{"entity_name":"Acme","url":row["url"],"claim":"Hiring AI automation engineers in Norfolk","supporting_urls":[row["url"]]}]}
    assert search._verified_results([row],verdict,QUERY,"Norfolk, VA")==[]


def test_engine_and_campaign_share_current_job_proof(live_job_page,monkeypatch):
    row=live_job_page()
    promoted=search._deterministic_need_verification([row],QUERY,"Norfolk, VA")
    assert promoted and promoted[0]["job_validation"]["ok"]
    monkeypatch.setattr(search,"_page_snapshot",lambda url:row)
    monkeypatch.delenv("EXA_API_KEY",raising=False)
    upgraded=campaign.enhance_discovery({"results":[{"title":"Acme","url":row["url"]}],"target_count":1},QUERY,"Norfolk, VA")
    assert upgraded["verified_count"]==1 and upgraded["target_met"]
    assert upgraded["results"][0]["job_title"]=="AI Automation Engineer"


def test_campaign_downgrades_unproved_preverified_or_wrong_city(live_job_page,monkeypatch):
    wrong=live_job_page(city="Boston",state="MA")
    monkeypatch.setattr(search,"_page_snapshot",lambda url:wrong)
    monkeypatch.delenv("EXA_API_KEY",raising=False)
    result=campaign.enhance_discovery({"results":[{"title":"Acme","classification":"Verified Lead","url":wrong["url"]}],"target_count":1},QUERY,"Norfolk, VA")
    assert result["verified_count"]==0 and result["target_met"] is False


def test_receipt_expires_and_cannot_match_new_role_city_or_remote_request(live_job_page):
    proof=check(live_job_page(now=NOW))
    assert not receipt_is_current(proof,QUERY,"Norfolk, VA",NOW+timedelta(hours=2))
    assert not receipt_is_current(proof,"Electrical engineer jobs","Norfolk, VA",NOW)
    assert not receipt_is_current(proof,QUERY,"Boston, MA",NOW)
    assert not receipt_is_current(proof,"AI automation engineer remote jobs","Norfolk, VA",NOW)


def test_rank_cannot_restore_hiring_verification_without_current_proof():
    rows=[{"title":"Acme","promotion_status":"verified","classification":"Verified Lead","verified_claim":"Fresh hiring"}]
    assert search.rank_research_results(rows,query=QUERY,location="Norfolk, VA")[0]["classification"]=="Candidate"


def test_ats_employer_metadata_must_match_exactly(live_job_page):
    row=live_job_page(now=NOW,url="https://boards.greenhouse.io/acme/jobs/123",changes={"hiringOrganization":{"@type":"Organization","name":"Acme","sameAs":"https://acme.example"}})
    assert check(row)["ok"]
    row["source_job_postings"][0]["hiringOrganization"]["name"]="Other Company"
    assert not check(row)["ok"]


def test_general_directory_is_not_a_primary_employer_job_page(live_job_page):
    row=live_job_page(now=NOW,url="https://directory.example/acme",changes={"hiringOrganization":{"@type":"Organization","name":"Acme","sameAs":"https://acme.example"}})
    assert not check(row)["ok"]


def test_duplicate_metadata_records_on_one_url_are_ambiguous(live_job_page):
    row=live_job_page(now=NOW)
    row["source_job_postings"]*=2
    result=check(row)
    assert not result["ok"] and "ambiguous_job_record_on_listing" in result["reasons"]


def test_another_companys_current_receipt_cannot_promote_entity(live_job_page):
    proof=check(live_job_page(now=NOW))
    assert not receipt_is_current(proof,QUERY,"Norfolk, VA",NOW,company="Other Company")


def test_campaign_promotion_does_not_refresh_old_check_timestamp(live_job_page):
    row=live_job_page();proof=check_job_evidence(row,QUERY,"Norfolk, VA","Acme")
    target={"title":"Acme"}
    campaign._promote(target,{"job_validation":proof},[row["url"]])
    assert target["evidence"][0]["observed_at"]==proof["checked_at"]
    assert target["evidence"][0]["job_validation"]["date_posted"]==proof["date_posted"]


def test_footer_apply_button_cannot_make_job_open(live_job_page):
    row=live_job_page(now=NOW,apply_html='<footer><a href="/unrelated-job">Apply now</a></footer>')
    assert not check(row)["ok"]


def test_unstructured_current_job_needs_labeled_local_worksite(live_job_page):
    row=live_job_page(now=NOW);row["source_job_postings"]=[]
    assert check(row)["ok"]
    row["job_detail_text"]="AI Automation Engineer Hampton Roads Acme. Job location: Boston, MA. Headquarters: Norfolk, VA. Apply now."
    assert not check(row)["ok"]


def test_unknown_posting_date_is_not_taken_from_provider_publication_estimate(live_job_page):
    row=live_job_page(now=NOW);row["source_job_postings"]=[]
    row["published_at"]="2026-10-10"
    proof=check(row)
    assert proof["ok"] and proof["date_posted"] is None


def test_hiring_job_fields_are_preserved_without_raw_page_payload(live_job_page):
    row=live_job_page()
    promoted=search._deterministic_need_verification([row],QUERY,"Norfolk, VA")[0]
    assert promoted["job_title"] and promoted["job_validation"]["checked_at"]
    assert "job_detail_text" not in promoted and "source_job_postings" not in promoted


def test_tracking_parameters_do_not_change_job_identity_but_job_ids_do(live_job_page):
    row=live_job_page(now=NOW,url="https://acme.example/jobs/1?utm_source=search")
    row["source_job_postings"][0]["url"]="https://acme.example/jobs/1"
    assert check(row)["ok"]
    row["source_job_postings"][0]["url"]="https://acme.example/jobs/1?jobId=2"
    assert not check(row)["ok"]


def test_full_schema_type_uri_is_parsed():
    raw='<script type="application/ld+json">{"@type":"https://schema.org/JobPosting","title":"Engineer"}</script>'
    assert job_page_metadata(raw,"https://acme.example")["source_job_postings"][0]["title"]=="Engineer"


def test_generic_careers_page_without_specific_job_cannot_verify_hiring(live_job_page):
    row=live_job_page(now=NOW,title="Careers");row["source_job_postings"]=[]
    assert not check(row,query="Find companies hiring",location="Norfolk, VA")["ok"]


def test_hiring_or_review_query_still_requires_identity_for_review_channel():
    row={"url":"https://reviews.example/other","candidate_name":"Acme","verification_research":True,"page_text":"Other Company never called me back.","title":"Other Company reviews"}
    assert search._deterministic_need_verification([row],"Find companies hiring engineers or with unanswered call reviews")==[]


def test_undefined_verified_channel_cannot_bypass_job_guard_using_or_query(monkeypatch):
    row={"title":"Acme","classification":"Verified Lead","promotion_status":"verified"}
    query="Find companies hiring engineers or with unanswered call reviews"
    assert search.rank_research_results([row],query=query)[0]["classification"]=="Candidate"
    monkeypatch.delenv("EXA_API_KEY",raising=False)
    assert campaign.enhance_discovery({"results":[row]},query,"")["verified_count"]==0


def test_ml_role_abbreviation_cannot_be_dropped(live_job_page):
    assert check(live_job_page(now=NOW,title="Machine Learning Engineer"),query="ML engineer jobs in Norfolk, VA")["ok"]
    assert not check(live_job_page(now=NOW,title="Software Engineer"),query="ML engineer jobs in Norfolk, VA")["ok"]


def test_short_role_specialty_cannot_be_dropped(live_job_page):
    assert not check(live_job_page(now=NOW,title="Sales Manager"),query="Find companies hiring HR managers in Norfolk, VA")["ok"]
