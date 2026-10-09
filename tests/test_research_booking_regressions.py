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
