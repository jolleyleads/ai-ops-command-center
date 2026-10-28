from src.research_intent import parse_research_request, format_research_results


def test_phone_request_is_research_only():
    intent = parse_research_request("Give me 20 HVAC companies with decision-makers phone numbers")
    assert intent["fields"] == ["company", "decision_maker", "phone"]
    assert intent["count"] == 20
    assert intent["research_only"] and not intent["send_authorized"]


def test_email_followup_reuses_results():
    intent = parse_research_request("Find their emails", {"count": 20})
    assert intent["fields"] == ["company", "email"]
    assert intent["reuse_previous_results"]
    assert intent["count"] == 20


def test_partial_contacts_still_display():
    intent = parse_research_request("Give me 2 companies with phone numbers")
    rows = [{"company": "Example HVAC", "contact_phone": "757-555-0100", "website": "https://example.com"},
            {"company": "Second HVAC", "website": "https://second.example"}]
    result = format_research_results(rows, intent)
    assert len(result) == 2
    assert result[0]["phone_type"] == "business_or_unconfirmed"
    assert result[1]["phone"] is None


def test_outreach_request_does_not_grant_send_permission():
    intent = parse_research_request("Send my campaign to them", {"count": 10})
    assert not intent["research_only"]
    assert not intent["send_authorized"]


def test_phone_only_company_query_routes_to_owned_research():
    from src.owned_research import accepts
    assert accepts('Give me 20 HVAC companies with the decision-makers phone numbers only in Chesapeake Virginia')
    assert accepts('List 10 plumbing businesses with owner telephone numbers in Norfolk')
    assert not accepts('Find 20 companies looking for automation engineers')


def test_full_contact_request_keeps_all_fields_and_word_count():
    intent = parse_research_request('Give me five HVAC companies in Chesapeake, Virginia, with decision-maker contact information like manager, CEO, etc.')
    assert intent['count'] == 5
    assert intent['fields'] == ['company', 'decision_maker', 'email', 'phone', 'website']
    assert intent['research_only'] and not intent['send_authorized']
    explicit = parse_research_request('Find 5 HVAC companies with owner emails and phone numbers')
    assert {'decision_maker', 'email', 'phone'} <= set(explicit['fields'])


def test_contact_table_keeps_multiple_people_and_field_sources():
    intent = parse_research_request('Give me five HVAC companies with decision-maker contact information')
    people = [{'name':'Jane Doe','role':'CEO','source_url':'https://acme.example/team'},
              {'name':'Mary Jones','role':'President','source_url':'https://acme.example/team'}]
    rows = [{'company':'Acme','website':'https://acme.example','decision_makers':people,
             'contact_phone':'757-555-0100','contact_email':'info@acme.example',
             'contact_type':'Company inbox','decision_maker_source_url':'https://acme.example/team',
             'email_source_url':'https://acme.example/contact','phone_source_url':'https://acme.example/contact'}]
    result = format_research_results(rows, intent)[0]
    assert result['decision_makers'] == people
    assert result['email_type'] == 'Company inbox'
    assert result['phone'] is None and result['business_phone'] == '757-555-0100'
    assert len(result['sources']) == 3
