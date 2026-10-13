"""Public, credential-free provider states shared by queues and operators."""
from datetime import datetime, timedelta, timezone

CONFIGURATION = {'HUNTER_REAL_CREDENTIAL_REQUIRED', 'HUNTER_ACCOUNT_EMAIL_REQUIRED',
                 'HUNTER_ACCOUNT_MISMATCH', 'HUNTER_FREE_PLAN_REQUIRED'}


def recovery_policy(reason_codes, attempt=0, now=None):
    reasons = set(reason_codes or [])
    now = now or datetime.now(timezone.utc)
    if reasons & {'HUNTER_PROCESSING_RESTRICTED', 'HUNTER_ADDRESS_REJECTED', 'EMAIL_MAIL_ROUTE_REJECTED'}:
        state, delay = 'rejected', None
    elif attempt >= 8:
        state, delay = 'review_required', None
    elif reasons & CONFIGURATION:
        state, delay = 'configuration_required', 3600
    elif reasons & {'HUNTER_FREE_QUOTA_UNAVAILABLE', 'HUNTER_FREE_QUOTA_EXHAUSTED'}:
        state, delay = 'quota_wait', 3600
    elif 'HUNTER_NOT_ENABLED' in reasons:
        state, delay = 'disabled', None
    else:
        state, delay = 'retry_wait', min(3600, 60 * 2 ** min(attempt, 6))
    return {'state': state, 'retryable': delay is not None,
            'next_check_at': (now + timedelta(seconds=delay)).isoformat() if delay else None,
            'reason_codes': sorted(reasons)}
