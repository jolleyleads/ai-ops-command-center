"""Shared, bounded policy for full background and campaign research."""
def research_target_count(value=10):
    return max(1, min(int(10 if value is None else value), 20))


def research_budget_seconds(target_count=10):
    return max(240, min(540, 180 + research_target_count(target_count) * 24))


def requested_target_count(value=None):
    """Public requests are validated, never silently truncated."""
    if isinstance(value, bool):
        raise ValueError('Result count must be an integer from 1 to 20.')
    try:
        count=int(10 if value is None else value)
    except (TypeError, ValueError):
        raise ValueError('Result count must be an integer from 1 to 20.')
    if str(value).strip() not in {str(count),'None'} or not 1<=count<=20:
        raise ValueError('This deployment supports 1–20 results per request. Split larger requests into batches of at most 20; no work has started.')
    return count
