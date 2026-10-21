"""Isolated job feed boundaries; no real accounts, searches, emails or bookings."""
import json
from types import SimpleNamespace

import pytest
import requests
from src import job_sources as jobs


@pytest.fixture(autouse=True)
def config(monkeypatch):
    for key in ('ADZUNA_APP_ID', 'ADZUNA_APP_KEY', 'ADZUNA_USE_APPROVED'):
        monkeypatch.delenv(key, raising=False)


def enable(monkeypatch):
    monkeypatch.setenv('ADZUNA_APP_ID', 'test-app')
    monkeypatch.setenv('ADZUNA_APP_KEY', 'secret-not-for-output')
    monkeypatch.setenv('ADZUNA_USE_APPROVED', 'true')


def listing(**changes):
    return dict(id='one', title='Automation Engineer', company={'display_name': 'Acme'},
                location={'display_name': 'Norfolk, VA'}, redirect_url='https://www.adzuna.com/details/one',
                created='2026-10-20T12:00:00Z', description='Acme seeks an Automation Engineer', **changes)


def response(payload, status=200):
    return SimpleNamespace(status_code=status, json=lambda: payload)


def test_credentials_alone_cannot_enable_sales_prospecting(monkeypatch):
    enable(monkeypatch); monkeypatch.delenv('ADZUNA_USE_APPROVED')
    monkeypatch.setattr(jobs.requests, 'get', lambda *a, **kw: pytest.fail('Unapproved provider called'))
    assert not jobs.adzuna_ready()
    assert jobs.search_adzuna('engineer', 'Norfolk')['state'] == 'not_enabled'
    assert jobs.capabilities()[1]['state'] == 'approval_required'


def test_approval_alone_does_not_claim_access(monkeypatch):
    monkeypatch.setenv('ADZUNA_USE_APPROVED', 'true')
    assert not jobs.adzuna_ready()
    assert jobs.capabilities()[1]['state'] == 'credentials_required'


def test_location_bounded_request_and_listing_provenance(monkeypatch):
    enable(monkeypatch); calls = []
    def get(url, **kw):
        calls.append((url, kw)); return response({'results': [listing()]})
    monkeypatch.setattr(jobs.requests, 'get', get)
    result = jobs.search_adzuna('automation engineer', 'Norfolk, VA')
    assert result['state'] == 'results'
    url, args = calls[0]
    assert url == 'https://api.adzuna.com/v1/api/jobs/us/search/1'
    assert args['params']['where'] == 'Norfolk, VA'
    assert args['params']['what'] == 'automation engineer'
    assert args['params']['results_per_page'] == 20
    assert args['timeout'] == (4, 10) and args['allow_redirects'] is False
    row = result['results'][0]
    assert row['company'] == 'Acme' and row['job_location'] == 'Norfolk, VA'
    assert row['published_at'] != row['observed_at']
    assert row['source'] == 'Adzuna' and row['attribution_url'] == 'https://www.adzuna.com/'
    assert 'pending' in row['status'] and not row.get('contact_email')
    assert not row.get('qualification') and not row.get('send_authorized')
    assert 'secret-not-for-output' not in json.dumps(result)


@pytest.mark.parametrize('status', [302, 401, 403, 429, 500])
def test_http_failure_is_explicit_without_response_or_credentials(monkeypatch, status):
    enable(monkeypatch)
    monkeypatch.setattr(jobs.requests, 'get', lambda *a, **kw: response({'secret': 'secret-not-for-output'}, status))
    result = jobs.search_adzuna('engineer', 'Norfolk')
    assert result['state'] == 'provider_error' and str(status) in result['message']
    assert not result['results'] and 'secret-not-for-output' not in json.dumps(result)


@pytest.mark.parametrize('payload', [[], {'error': 'upstream'}, {'results': 'invalid'}])
def test_malformed_envelope_is_not_reported_as_no_jobs(monkeypatch, payload):
    enable(monkeypatch)
    monkeypatch.setattr(jobs.requests, 'get', lambda *a, **kw: response(payload))
    assert jobs.search_adzuna('engineer')['state'] == 'provider_error'


def test_no_results_is_distinct_from_provider_failure(monkeypatch):
    enable(monkeypatch)
    monkeypatch.setattr(jobs.requests, 'get', lambda *a, **kw: response({'results': []}))
    assert jobs.search_adzuna('engineer')['state'] == 'empty'
    def fail(*a, **kw): raise requests.Timeout('https://api.adzuna.com/?app_key=secret-not-for-output')
    monkeypatch.setattr(jobs.requests, 'get', fail)
    result = jobs.search_adzuna('engineer')
    assert result['state'] == 'provider_error' and 'secret-not-for-output' not in json.dumps(result)


def test_invalid_rows_are_not_invented_and_feed_is_bounded(monkeypatch):
    enable(monkeypatch)
    bad = listing(); bad['redirect_url'] = 'javascript:alert(1)'
    missing = listing(); missing.pop('company')
    monkeypatch.setattr(jobs.requests, 'get', lambda *a, **kw: response({'results': [None, bad, missing] + [listing()] * 30}))
    result = jobs.search_adzuna('engineer')
    assert len(result['results']) == 17


def test_provider_failure_preserves_other_feed_and_deduplicates(monkeypatch):
    enable(monkeypatch)
    monkeypatch.setattr(jobs, 'search_adzuna', lambda *a: {'source': 'Adzuna', 'state': 'provider_error', 'results': [], 'message': 'Adzuna returned HTTP 429.'})
    row = {'url': 'https://remotive.com/jobs/one', 'title': 'Engineer', 'company': 'Acme'}
    result = jobs.search_jobs('engineer', 'Norfolk', lambda q: [row, row])
    assert result['results'] == [row] and '429' in result['message']
    assert {x['state'] for x in result['providers']} == {'results', 'provider_error'}


def test_legacy_failure_row_never_becomes_a_company(monkeypatch):
    result = jobs.search_jobs('engineer', '', lambda q: [{'title': 'Error fetching jobs', 'company': 'System', 'error': 'secret'}])
    assert not result['results'] and result['providers'][0]['state'] == 'provider_error'
    assert 'secret' not in json.dumps(result)


def test_approved_feed_is_used_for_company_hiring_research(monkeypatch):
    import smart_search as search
    enable(monkeypatch)
    calls = search._company_discovery_calls('Find companies hiring automation engineers', 'Norfolk', [])
    assert len(calls) == 3 and any(x['tool'] == 'job_search' for x in calls)
    monkeypatch.setattr(search, 'search_jobs', lambda q, loc, legacy: {'results': [listing_row()], 'message': 'partial failure'})
    rows, message = search._run_tool({'tool': 'job_search', 'query': 'automation engineer', 'location': 'Norfolk'})
    assert rows[0]['research_tool'] == 'job_search' and message == 'partial failure'
    assert search._deterministic_need_verification(rows, 'companies hiring automation engineers', 'Norfolk') == []


def listing_row():
    return {'title': 'Automation Engineer at Acme', 'company': 'Acme', 'source': 'Adzuna',
            'url': 'https://www.adzuna.com/details/one', 'subtitle': 'Acme Norfolk hiring engineers'}


def test_capabilities_are_honest_and_never_return_keys(monkeypatch):
    import universal_app
    enable(monkeypatch)
    monkeypatch.setenv('OPERATOR_CONTROL_TOKEN', 'job-source-test')
    client = universal_app.app.test_client()
    assert client.get('/api/universal-search/capabilities').status_code == 401
    result = client.get('/api/universal-search/capabilities', headers={'X-Operator-Token': 'job-source-test'})
    assert result.status_code == 200
    providers = {x['source']: x for x in result.json['jobs']['providers']}
    assert providers['Adzuna']['state'] == 'configured_not_tested'
    assert providers['Indeed']['state'] == 'partner_access_required'
    assert providers['ZipRecruiter']['state'] == 'connection_verification_required'
    assert 'secret-not-for-output' not in result.get_data(as_text=True)
