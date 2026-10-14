from datetime import datetime,timezone
from types import SimpleNamespace
import pytest
from src.enrichment import enrich_lead,validated_payload
from src.contact_assessment import contact_sections
from src.company_identity import visible_page_text
from src.email_validation import check_email_domain,apply_email_domain_check
import dns.resolver,dns.exception


def source(text,**extra):
    return {'url':'https://acme.com/team','candidate_name':'Acme','page_text':text,'directly_fetched':True,'http_status':200,'observed_at':datetime.now(timezone.utc).isoformat(),**extra}


def lead(**extra):
    return {'company':'Acme','location':'Norfolk VA','query':'companies hiring AI automation engineers',**extra}


def test_recruiter_preferred_over_unrelated_local_executive():
    rows=[source('Acme Norfolk VA Jane Doe, CEO. jane@acme.com'),source('Acme Norfolk VA Mary Jones, Hiring Manager. mary@acme.com')]
    result=enrich_lead(lead(),rows)
    assert result['fields']['decision_maker']['value']=='Mary Jones'
    assert result['fields']['email']['value']=='mary@acme.com'
    assert result['contact_assessment']['email_person_status']=='same_source_card'
    assert result['fields']['email']['deliverability_status']=='unconfirmed'


def test_generic_inbox_is_not_attached_to_person():
    result=enrich_lead(lead(query='businesses needing automation follow-up'),[source('Acme Norfolk VA Jane Doe, CEO. info@acme.com')])
    assert result['fields']['decision_maker']['value']=='Jane Doe'
    assert result['contact_assessment']['email_person_status']=='unconfirmed'
    assert result['fields']['email']['address_kind']=='shared_inbox'


def test_wrong_city_and_social_profiles_cannot_establish_person():
    for row in [source('Acme Boston MA Jane Doe, Hiring Manager. jane@acme.com'),source('Acme Norfolk VA Jane Doe, Hiring Manager. jane@acme.com',url='https://linkedin.com/in/jane')]:
        result=enrich_lead(lead(),[row])
        assert 'decision_maker' not in validated_payload(result)
        assert 'email' not in validated_payload(result)


def test_two_equally_supported_people_remain_ambiguous():
    result=enrich_lead(lead(),[source('Acme Norfolk VA Jane Doe, Hiring Manager. jane@acme.com'),source('Acme Norfolk VA Mary Jones, Hiring Manager. mary@acme.com')])
    assert result['contact_assessment']['decision_maker_status']=='ambiguous'
    assert 'decision_maker' not in result['fields']


def test_person_card_cannot_borrow_email_from_adjacent_person():
    result=enrich_lead(lead(),[source('Acme Norfolk VA Jane Doe, Hiring Manager. Mary Jones, Director. mary@acme.com')])
    assert result['contact_assessment']['email_person_status']=='unconfirmed'


def test_former_staff_are_not_current_decision_makers():
    result=enrich_lead(lead(),[source('Acme Norfolk VA Former Jane Doe, Hiring Manager. jane@acme.com')])
    assert not result['decision_maker_candidates']


def test_html_footer_does_not_establish_person_locality():
    raw='<section>Acme Jane Doe, Hiring Manager. jane@acme.com</section><footer>Norfolk VA</footer>'
    result=enrich_lead(lead(),[source(visible_page_text(raw),contact_sections=contact_sections(raw))])
    assert 'decision_maker' not in result['fields']


def test_separate_html_cards_preserve_branch_and_person_email_binding():
    raw='<section>Acme Boston MA Jane Doe, Hiring Manager. jane@acme.com</section><section>Acme Norfolk VA Mary Jones, Hiring Manager. mary@acme.com</section>'
    result=enrich_lead(lead(),[source(visible_page_text(raw),contact_sections=contact_sections(raw))])
    assert result['fields']['decision_maker']['value']=='Mary Jones'
    assert result['fields']['email']['value']=='mary@acme.com'


def test_injected_card_not_in_actual_page_cannot_promote_person():
    result=enrich_lead(lead(),[source('Acme Norfolk VA info@acme.com',contact_sections=['Acme Norfolk VA Jane Doe, Hiring Manager. jane@acme.com'])])
    assert not result['decision_maker_candidates']


def test_missing_target_city_does_not_confirm_local_decision_maker():
    result=enrich_lead(lead(location=''),[source('Acme Norfolk VA Jane Doe, Hiring Manager. jane@acme.com')])
    assert 'decision_maker' not in result['fields']


def test_mx_does_not_prove_mailbox_or_deliverability():
    def resolve(domain,kind,**kwargs):
        assert domain=='acme.com' and kind=='MX' and kwargs['lifetime']<=2 and kwargs['search'] is False
        return [SimpleNamespace(exchange='mail.acme.com.',preference=10)]
    receipt=check_email_domain('jane@acme.com',resolve)
    assert receipt['domain_status']=='mx_published'
    assert receipt['mailbox_status']==receipt['deliverability_status']=='unconfirmed'


@pytest.mark.parametrize('error,status',[(dns.resolver.NXDOMAIN,'does_not_exist'),(dns.exception.Timeout,'unconfirmed')])
def test_missing_domain_differs_from_dns_timeout(error,status):
    def resolve(*a,**k):raise error()
    assert check_email_domain('jane@acme.com',resolve)['domain_status']==status


def test_null_mx_blocks_email_while_preserving_other_enrichment():
    result=enrich_lead(lead(),[source('Acme Norfolk VA Jane Doe, Hiring Manager. jane@acme.com')])
    apply_email_domain_check(result,lambda *a,**k:[SimpleNamespace(exchange='.',preference=0)])
    payload=validated_payload(result)
    assert 'email' not in payload and payload['website']
    assert payload['contact_assessment']['email_validation']['reason_codes']==['NULL_MX']


def test_absent_mx_checks_implicit_route_without_claiming_delivery():
    def resolve(domain,kind,**kwargs):
        if kind=='MX':raise dns.resolver.NoAnswer()
        return ['93.184.216.34']
    assert check_email_domain('jane@acme.com',resolve)['domain_status']=='implicit_mail_route'


@pytest.mark.parametrize('email',['jane..doe@acme.com','.jane@acme.com','jane@-acme.com','jane@acme..com','not-email'])
def test_bad_syntax_never_queries_dns(email):
    def resolve(*a,**k):raise AssertionError('No DNS query allowed')
    assert check_email_domain(email,resolve)['domain_status']=='invalid'


def test_outreach_bridge_passes_requested_city_to_enrichment(monkeypatch):
    import outreach_bridge as bridge
    monkeypatch.setattr(bridge,'OutreachLead',SimpleNamespace(query=SimpleNamespace(filter_by=lambda **k:SimpleNamespace(first=lambda:None))))
    monkeypatch.setattr(bridge,'_public_contact_evidence',lambda result:([],{}))
    summary=bridge.ingest_verified_results({'query':'companies hiring AI automation engineers','location':'Norfolk VA','results':[{'company':'Acme','website':'https://acme.com','location':'Norfolk VA','intent_score':80,'verification':'VERIFIED','evidence':[source('Acme Boston MA Jane Doe, Hiring Manager. jane@acme.com')]}]})
    failure=next(x for x in summary['skipped'] if x.get('reason')=='qualification_failed')
    assert 'email' not in failure['validated_contact_fields']
    assert summary['saved']==0


def test_v1_campaign_does_not_trust_unproven_search_contact_name(monkeypatch):
    import v1_orchestration as v1
    monkeypatch.setattr(v1,'_public_contact_evidence',lambda result:([source('Acme Norfolk VA Jane Doe, CEO. info@acme.com')],{}))
    monkeypatch.setattr(dns.resolver,'resolve',lambda *a,**k:[SimpleNamespace(exchange='mail.acme.com.',preference=10)])
    result={'company':'Acme','website':'https://acme.com','contact_location':'Norfolk VA','query':'businesses needing automation follow-up','contact_name':'Invented Person'}
    assert v1._verified_public_email(result)[0]=='info@acme.com'
    assert result['_contact_name']==''
    assert result['_contact_enrichment']['contact_assessment']['email_person_status']=='unconfirmed'


def test_v1_campaign_requires_fresh_actual_page_not_validated_email_label(monkeypatch):
    import v1_orchestration as v1
    monkeypatch.setattr(v1,'_public_contact_evidence',lambda result:([{'url':'https://acme.com/contact','validated_emails':['jane@acme.com'],'identity_version':'company-domain-v1','company_identity':{'company_name':'Acme'}}],{}))
    assert v1._verified_public_email({'company':'Acme','website':'https://acme.com','contact_location':'Norfolk VA'})==('','')


def test_uncertain_name_cannot_leak_into_generated_greeting(monkeypatch):
    import json,outreach_automation as oa
    lead=SimpleNamespace(company='Acme',location='Norfolk VA',score=80,verification='VERIFIED',contact_name='',source_url='https://acme.com',evidence_json=json.dumps({'enrichment':{'decision_maker_candidates':[{'name':'Jane Doe'}]}}))
    monkeypatch.setattr(oa,'run_ai',lambda **k:{'ok':True,'output':json.dumps({'subject':'Hello','body':'Hi Jane, can we chat?'})})
    monkeypatch.setattr(oa,'_fallback_draft',lambda *a:{'ok':True,'fallback':True})
    assert oa._draft_email(lead)['fallback']


def test_email_for_unlabelled_other_person_cannot_be_bound_to_decision_maker():
    result=enrich_lead(lead(),[source('Acme Norfolk VA Jane Doe, Hiring Manager. Contact Bob at bob@acme.com')])
    assert result['contact_assessment']['email_person_status']=='unconfirmed'


def test_former_staff_email_is_withheld_from_contact_enrichment():
    result=enrich_lead(lead(),[source('Acme Norfolk VA Former Jane Doe, Hiring Manager. jane@acme.com')])
    assert 'email' not in result['fields']


def test_search_exposes_role_and_person_link_separately_from_delivery():
    import smart_search
    row={'title':'Acme','website':'https://acme.com'}
    result=smart_search._attach_source_contacts([row],[source('Acme Norfolk VA Jane Doe, Hiring Manager. jane@acme.com')],'Norfolk VA','companies hiring AI automation engineers')[0]
    contact=result['contacts'][0]
    assert result['decision_maker_status']=='source_supported'
    assert contact['person_name']=='Jane Doe' and contact['mailbox_status']=='unconfirmed'


def test_null_mx_in_campaign_cannot_yield_outreach_address(monkeypatch):
    import v1_orchestration as v1
    monkeypatch.setattr(v1,'_public_contact_evidence',lambda result:([source('Acme Norfolk VA Jane Doe, Hiring Manager. jane@acme.com')],{}))
    monkeypatch.setattr(dns.resolver,'resolve',lambda *a,**k:[SimpleNamespace(exchange='.',preference=0)])
    assert v1._verified_public_email({'company':'Acme','website':'https://acme.com','contact_location':'Norfolk VA','query':'companies hiring AI automation engineers'})==('','')


def test_callback_need_selects_local_customer_service_manager():
    result=enrich_lead(lead(query='businesses with unanswered calls and poor callback responses'),[source('Acme Norfolk VA Jane Doe, Customer Service Manager. jane@acme.com')])
    assert result['fields']['decision_maker']['value']=='Jane Doe'
    assert result['contact_assessment']['decision_maker_status']=='source_supported'


def test_unrelated_person_email_is_not_a_fallback_for_relevant_person():
    result=enrich_lead(lead(),[source('Acme Norfolk VA Jane Doe, CEO. jane@acme.com'),source('Acme Norfolk VA Mary Jones, Hiring Manager.')])
    assert result['fields']['decision_maker']['value']=='Mary Jones'
    assert 'email' not in result['fields']


def test_ambiguous_people_can_only_fall_back_to_company_inbox():
    result=enrich_lead(lead(),[source('Acme Norfolk VA Jane Doe, Hiring Manager. jane@acme.com'),source('Acme Norfolk VA Mary Jones, Hiring Manager. mary@acme.com'),source('Acme Norfolk VA info@acme.com')])
    assert result['fields']['email']['value']=='info@acme.com'
    assert result['contact_assessment']['decision_maker_status']=='ambiguous'
    assert result['contact_assessment']['email_person_status']=='unconfirmed'


def test_conflicting_null_mx_remains_unknown_not_false_hard_negative():
    receipt=check_email_domain('jane@acme.com',lambda *a,**k:[SimpleNamespace(exchange='.',preference=0),SimpleNamespace(exchange='mail.acme.com.',preference=10)])
    assert receipt['domain_status']=='unconfirmed' and receipt['reason_codes']==['CONFLICTING_MX_RECORDS']


def test_domain_without_any_mail_route_is_rejected():
    def resolve(*a,**k):raise dns.resolver.NoAnswer()
    receipt=check_email_domain('jane@acme.com',resolve)
    assert receipt['domain_status']=='does_not_accept_mail' and receipt['reason_codes']==['NO_MAIL_ROUTE']


def test_contact_probe_continues_after_generic_inbox_to_explicit_team_link(monkeypatch):
    import outreach_bridge as bridge
    seen=[]
    def fetch(url,**kwargs):
        seen.append(url)
        body='<title>Acme</title>Acme Norfolk VA info@acme.com <a href="/team">Team</a>' if url.endswith('/') else '<title>Acme</title><section>Acme Norfolk VA Mary Jones, Hiring Manager. mary@acme.com</section>'
        return SimpleNamespace(url=url,status_code=200,text=body,headers={'content-type':'text/html'})
    monkeypatch.setattr(bridge,'public_get',fetch)
    rows,receipt=bridge._public_contact_evidence({'company':'Acme','website':'https://acme.com','contact_location':'Norfolk VA','query':'companies hiring AI automation engineers'})
    assert seen==['https://acme.com/','https://acme.com/team']
    result=enrich_lead(lead(),rows)
    assert result['fields']['email']['value']=='mary@acme.com'
    assert receipt['attempted']==2


def test_apostrophe_in_sourced_name_is_preserved():
    result=enrich_lead(lead(),[source("Acme Norfolk VA Mary O'Neill, Hiring Manager. mary.oneill@acme.com")])
    assert result['fields']['decision_maker']['value']=="Mary O'Neill"
    assert result['contact_assessment']['email_person_status']=='same_source_card'


def test_finance_personnel_table_is_retrieved_from_advertised_link(monkeypatch):
    import outreach_bridge as bridge
    seen=[]
    def fetch(url,**kwargs):
        seen.append(url)
        if url=='https://acme.com/':
            body='<title>Acme</title>Acme Norfolk VA info@acme.com <a href="/key-personnel/">Key Personnel</a>'
        elif url=='https://acme.com/key-personnel/':
            body='<title>Acme</title><table><tr><td>Acme Norfolk VA Mary Jones<br>Director of Finance<br>mary@acme.com</td><td>Acme Boston MA Jane Doe<br>Hiring Manager<br>jane@acme.com</td></tr></table>'
        else:raise AssertionError('Advertised personnel page must precede guessed paths')
        return SimpleNamespace(url=url,status_code=200,text=body,headers={'content-type':'text/html'})
    monkeypatch.setattr(bridge,'public_get',fetch)
    rows,_=bridge._public_contact_evidence({'company':'Acme','website':'https://acme.com','contact_location':'Norfolk VA','query':'automate accounting workflows'})
    result=enrich_lead(lead(query='automate accounting workflows'),rows)
    assert seen==['https://acme.com/','https://acme.com/key-personnel/']
    assert result['fields']['decision_maker']['value']=='Mary Jones'
    assert result['fields']['decision_maker']['title']=='Director of Finance'
    assert result['fields']['email']['value']=='mary@acme.com'
    assert result['contact_assessment']['mailbox_status']=='unconfirmed'


def test_personnel_table_cannot_borrow_city_or_email_from_adjacent_cell():
    raw='<table><tr><td>Acme Mary Jones<br>Director of Finance</td><td>Acme Norfolk VA Jane Doe<br>Hiring Manager<br>jane@acme.com</td></tr></table>'
    result=enrich_lead(lead(query='automate accounting workflows'),[source(visible_page_text(raw),contact_sections=contact_sections(raw))])
    mary=next(c for c in result['decision_maker_candidates'] if c['name']=='Mary Jones')
    assert mary['location_status']=='unconfirmed' and mary['email']==''
    assert 'decision_maker' not in result['fields']


def test_finance_title_does_not_claim_hiring_authority_or_invent_email():
    raw='<table><tr><td>Acme Norfolk VA Mary Jones<br>Director of Finance</td></tr></table>'
    result=enrich_lead(lead(query='companies hiring accounting assistants'),[source(visible_page_text(raw),contact_sections=contact_sections(raw))])
    candidate=result['decision_maker_candidates'][0]
    assert candidate['name']=='Mary Jones' and candidate['title']=='Director of Finance'
    assert candidate['responsibility_status']=='unconfirmed' and candidate['email']==''
    assert 'decision_maker' not in result['fields']


def test_inline_formatting_preserves_name_and_table_title_boundaries():
    raw='<table><tr><td>Acme Norfolk VA <span>Sara</span>h Moro<br>Director of Finance</td><td>Acme Norfolk VA Billy Gresham<br>Vice President</td><td>Acme Norfolk VA Mike Oehler<br>Safety Director</td></tr></table>'
    result=enrich_lead(lead(query='automate accounting workflows'),[source(visible_page_text(raw),contact_sections=contact_sections(raw))])
    people={c['name']:c['title'] for c in result['decision_maker_candidates']}
    assert people=={'Sarah Moro':'Director of Finance','Billy Gresham':'Vice President','Mike Oehler':'Safety Director'}
    assert result['fields']['decision_maker']['value']=='Sarah Moro'
    assert 'email' not in result['fields']


def test_career_ladder_titles_do_not_become_person_names():
    raw='<section>Acme Norfolk VA Regional Vice President<br>General Manager<br>Branch Manager<br>Director of Operations<br>Client Manager<br>Operations Manager</section>'
    result=enrich_lead(lead(query='automate accounting workflows'),[source(visible_page_text(raw),contact_sections=contact_sections(raw))])
    assert result['decision_maker_candidates']==[]


def test_campaign_skips_disallowed_inbox_without_losing_allowed_company_contact(monkeypatch):
    import v1_orchestration as v1
    monkeypatch.setattr(v1,'_public_contact_evidence',lambda result:([source('Acme Norfolk VA careers@acme.com info@acme.com')],{}))
    monkeypatch.setattr(dns.resolver,'resolve',lambda *a,**k:[SimpleNamespace(exchange='mail.acme.com.',preference=10)])
    assert v1._verified_public_email({'company':'Acme','website':'https://acme.com','contact_location':'Norfolk VA'})[0]=='info@acme.com'


def test_bridge_passes_search_request_to_contact_probe(monkeypatch):
    import outreach_bridge as bridge
    seen=[]
    monkeypatch.setattr(bridge,'OutreachLead',SimpleNamespace(query=SimpleNamespace(filter_by=lambda **k:SimpleNamespace(first=lambda:None))))
    def probe(result):seen.append(result);return [],{}
    monkeypatch.setattr(bridge,'_public_contact_evidence',probe)
    query='companies hiring AI automation engineers'
    bridge.ingest_verified_results({'query':query,'location':'Norfolk VA','results':[{'company':'Acme','website':'https://acme.com','location':'Norfolk VA','intent_score':80,'verification':'VERIFIED','evidence':[source('Acme Norfolk VA')]}]})
    assert seen[0]['query']==query and seen[0]['contact_location']=='Norfolk VA'


def test_rejected_mail_domain_receipt_persists_when_no_email_is_selected(monkeypatch):
    import v1_orchestration as v1
    monkeypatch.setattr(v1,'_public_contact_evidence',lambda result:([source('Acme Norfolk VA info@acme.com')],{}))
    monkeypatch.setattr(dns.resolver,'resolve',lambda *a,**k:[SimpleNamespace(exchange='.',preference=0)])
    result={'company':'Acme','website':'https://acme.com','contact_location':'Norfolk VA'}
    email,url=v1._verified_public_email(result)
    assert (email,url)==('','')
    evidence=v1._evidence_with_contact(result,email,url)
    receipt=next(e for e in evidence if e.get('source')=='contact_validation_receipt')
    assert receipt['url']=='https://acme.com/team'
    assert receipt['contact_assessment']['email_validation']['reason_codes']==['NULL_MX']
    assert receipt['contact_assessment']['email_validation']['checked_at']
    assert receipt['enrichment']['fields']['email']['validated'] is False


def test_city_overlap_is_not_proof_of_hiring_responsibility():
    result=enrich_lead(lead(query='Acme companies hiring AI automation engineers in Norfolk VA'),[source('Acme Norfolk VA Jane Doe, CEO. Responsible for Acme Norfolk office. jane@acme.com')])
    assert 'decision_maker' not in result['fields']
    assert result['contact_assessment']['decision_maker_status']=='unconfirmed'


def test_technical_work_alone_does_not_establish_hiring_authority():
    result=enrich_lead(lead(),[source('Acme Norfolk VA Jane Doe, CEO. Responsible for automation testing. jane@acme.com')])
    assert 'decision_maker' not in result['fields']


@pytest.mark.parametrize('term',['job openings','careers','jobs'])
def test_explicit_hiring_responsibility_uses_same_terms_as_query(term):
    result=enrich_lead(lead(query=f'companies with {term} for AI engineers'),[source(f'Acme Norfolk VA Jane Doe, CEO. Oversees {term} for AI engineers. jane@acme.com')])
    assert result['contact_assessment']['decision_maker_status']=='source_supported'
    assert result['fields']['decision_maker']['value']=='Jane Doe'


def test_staffing_company_type_does_not_replace_requested_callback_need():
    result=enrich_lead(lead(query='staffing companies with poor callback responses'),[source('Acme Norfolk VA Jane Doe, CEO. jane@acme.com')])
    assert result['contact_assessment']['decision_maker_status']=='source_supported'
    assert result['decision_maker_candidates'][0]['responsibility_basis']=='business_function_title'
