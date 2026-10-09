"""Read-only Calendar connectivity check; never creates or changes events."""
from datetime import datetime, timedelta, timezone
from flask import jsonify
from app import app
from src.google_calendar_provider import check_availability


@app.get('/api/calendar/status')
def calendar_status():
    start = datetime.now(timezone.utc) + timedelta(days=1)
    receipt = check_availability({
        'start': start.isoformat(),
        'end': (start + timedelta(minutes=15)).isoformat(),
        'timezone': 'UTC',
    })
    # Connectivity proves read access only, not event creation or booking.
    return jsonify(connected=receipt.get('ok') is True,
                   check='read_only_availability',
                   booking_verified=False)
