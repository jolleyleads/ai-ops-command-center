"""Provider-independent URL discovery. Returned pages still require live fetching."""
from src.execution_deadline import checkpoint


def search(query, location=''):
    from smart_search import _exa_search, _web_search
    try:
        first = _exa_search(query, location)
    except TimeoutError:
        raise
    except Exception:
        first = {'results': []}
    if first.get('results'):
        return first
    checkpoint('researching_more_sources')
    try:
        second = _web_search(query, location)
    except TimeoutError:
        raise
    except Exception:
        second = {'results': []}
    if second.get('results'):
        return second
    return {'results': [], 'source': 'Public web sources',
            'message': 'Live source search did not return usable source URLs.'}
