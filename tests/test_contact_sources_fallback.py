"""Regression tests for independent source lookup during OpenAI quota exhaustion."""
import pytest
from unittest.mock import Mock
import smart_search
import universal_app
from src import contact_sources


def test_google_fallback_survives_exa_and_openai_quota(monkeypatch):
    monkeypatch.setattr(smart_search, '_exa_search', lambda *a: {'results': [], 'message': 'Exa unavailable'})
    monkeypatch.setattr(universal_app, '_search_public_records', lambda *a: {
        'results': [{'title': 'Public profile', 'url': 'https://example.com/team'}],
        'source': 'Google Programmable Search'})
    blocked = Mock(side_effect=AssertionError('OpenAI should not be called after independent results'))
    monkeypatch.setattr(smart_search, '_web_search', blocked)
    result = contact_sources.search('HVAC decision makers', 'Chesapeake')
    assert len(result['results']) == 1
    assert result['providers_attempted'] == 2
    assert 'Exa unavailable' in result['message']
    blocked.assert_not_called()


def test_quota_error_is_diagnostic_not_fake_result(monkeypatch):
    monkeypatch.setattr(smart_search, '_exa_search', lambda *a: {'results': []})
    monkeypatch.setattr(universal_app, '_search_public_records', lambda *a: {'results': []})
    monkeypatch.setattr(smart_search, '_web_search', lambda *a: {
        'results': [], 'message': 'HTTP 429 no credits'})
    result = contact_sources.search('people')
    assert result['results'] == []
    assert '429' in result['message']
    assert result['providers_attempted'] == 3


def test_discard_results_without_real_source_url(monkeypatch):
    monkeypatch.setattr(smart_search, '_exa_search', lambda *a: {
        'results': [{'title': 'Unverifiable', 'url': ''}]})
    monkeypatch.setattr(universal_app, '_search_public_records', lambda *a: {
        'results': [{'title': 'Verified source', 'url': 'https://example.org'}]})
    monkeypatch.setattr(smart_search, '_web_search', Mock())
    result = contact_sources.search('lookup')
    assert result['results'][0]['url'] == 'https://example.org'
