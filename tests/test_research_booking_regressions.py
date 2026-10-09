from unittest.mock import Mock
from src.calendar_booking import execute_booking
from src import google_calendar_provider as calendar
from smart_search import _relevance_filter


def test_specialized_jobs_exclude_unrelated_roles():
    rows = [{'title': 'Electrician hiring in DC'}, {'title': 'AI Automation Engineer in DC'}]
    assert _relevance_filter(rows, 'Find companies hiring AI automation engineers') == rows[1:]


def test_calendar_errors_never_mean_available(monkeypatch):
    monkeypatch.setattr(calendar, '_headers', lambda: {})
    for data in ({}, {'calendars': {'primary': {'errors': [{'reason': 'notFound'}]}}},
                 {'calendars': {'primary': {'busy': None}}}):
        monkeypatch.setattr(calendar.requests, 'post', lambda *a, **k: Mock(ok=True, json=lambda: data))
        assert calendar.check_availability({'start': 'start', 'end': 'end', 'timezone': 'UTC'})['ok'] is False
    monkeypatch.setattr(calendar.requests, 'post', lambda *a, **k: Mock(ok=True, json=lambda: {'calendars': {'primary': {'busy': []}}}))
    assert calendar.check_availability({'start': 'start', 'end': 'end', 'timezone': 'UTC'})['available'] is True


def test_booking_cannot_create_for_an_unchecked_window():
    request = dict(booking_ready=True, validated=True, start='2030-01-01T12:00:00+00:00',
                   end='2030-01-01T12:15:00+00:00', timezone='UTC', attendee_email='example@example.com')
    create = Mock()
    result = execute_booking(request, lambda _: dict(ok=True, available=True,
                             checked_start='2030-01-02T12:00:00+00:00', checked_end=request['end']), create)
    assert result['stage'] == 'unavailable'
    create.assert_not_called()


def test_health_does_not_run_schema_creation(monkeypatch):
    import commercial_app
    create = Mock(side_effect=AssertionError("request attempted schema creation"))
    monkeypatch.setattr(commercial_app.db_resilience.db, 'create_all', create)
    response = commercial_app.app.test_client().get('/api/health')
    assert response.status_code == 200
    create.assert_not_called()


def test_filled_jobs_do_not_surface_as_hiring_candidates():
    rows = [{'title':'AI engineer', 'subtitle':'The job you are trying to apply for has been filled.'}]
    assert _relevance_filter(rows, 'Find companies hiring AI engineers') == []


def test_verification_requires_a_literal_source_quote():
    from smart_search import _verified_results
    evidence = [dict(url='https://example.com/job', candidate_name='Acme', verification_research=True,
                     subtitle='Acme is hiring an AI automation engineer.')]
    verdict = dict(url=evidence[0]['url'], entity_name='Acme', claim='Hiring AI automation engineer',
                   supporting_urls=[evidence[0]['url']], evidence_quote='An invented quote')
    assert _verified_results(evidence, {'verified_results':[verdict]}, 'AI jobs') == []
    verdict['evidence_quote'] = evidence[0]['subtitle']
    assert len(_verified_results(evidence, {'verified_results':[verdict]}, 'AI jobs')) == 1


def test_job_role_matching_ignores_location_and_output_instructions():
    from smart_search import _requested_role_terms
    assert _requested_role_terms('Find companies hiring AI automation engineers in Washington DC. Include source links.') == ['automation', 'engineer']


def test_research_json_mode_names_json_in_the_input(monkeypatch):
    import research_agent as agent
    calls=[]
    class Responses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return Mock(output_text='{"intent":"jobs","tool_calls":[{"tool":"web_search","query":"jobs"}],"candidates":[],"verified_results":[]}')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-only-key')
    monkeypatch.setattr(agent, '_client', lambda: Mock(responses=Responses()))
    agent.plan_research('automation jobs')
    agent.recover_tool_plan('automation jobs')
    agent.extract_candidates('automation jobs', '', [{'url':'https://example.com','title':'Example'}])
    agent.evaluate_research('automation jobs', '', [{'url':'https://example.com','title':'Example'}])
    assert len(calls)==4
    assert all('json' in call['input'].lower() for call in calls)
