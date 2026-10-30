"""Provider-independent URL discovery for source-grounded contact research.

Independent providers are queried before paid OpenAI search. An unavailable
provider must not block later providers, and failed lookups are reported rather
than fabricated as verified contact data.
"""
from src.execution_deadline import checkpoint


def _usable(result):
    if not isinstance(result, dict):
        return []
    return [row for row in result.get('results') or []
            if isinstance(row, dict) and isinstance(row.get('url'), str)
            and row['url'].startswith(('https://', 'http://'))]


def search(query, location=''):
    from smart_search import _exa_search, _web_search
    from universal_app import _search_public_records

    diagnostics = []
    providers = (
        ('Exa', _exa_search),
        ('Google public search', _search_public_records),
        ('OpenAI web search', _web_search),
    )
    for index, (name, provider) in enumerate(providers):
        if index:
            checkpoint('researching_more_sources')
        try:
            result = provider(query, location)
            rows = _usable(result)
            if rows:
                return {'results': rows, 'source': result.get('source') or name,
                        'message': '; '.join(diagnostics),
                        'providers_attempted': index + 1}
            message = result.get('message') if isinstance(result, dict) else ''
            diagnostics.append(name + ': ' + (str(message)[:300] if message else 'No usable source URLs'))
        except TimeoutError:
            raise
        except Exception as exc:
            diagnostics.append(name + ': ' + type(exc).__name__)
    return {'results': [], 'source': 'Public web sources',
            'message': 'No verified source URLs returned. ' + '; '.join(diagnostics),
            'providers_attempted': len(providers)}
