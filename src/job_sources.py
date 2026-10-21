"""Optional job feeds. Provider listings are discovery evidence, never send authority."""
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeout
from datetime import datetime, timezone
import os
from urllib.parse import urlparse

import requests


def adzuna_ready():
    return (os.getenv('ADZUNA_USE_APPROVED', '').lower() == 'true'
            and bool(os.getenv('ADZUNA_APP_ID') and os.getenv('ADZUNA_APP_KEY')))


def capabilities():
    credentials = bool(os.getenv('ADZUNA_APP_ID') and os.getenv('ADZUNA_APP_KEY'))
    approved = os.getenv('ADZUNA_USE_APPROVED', '').lower() == 'true'
    return [
        {'source': 'Remotive', 'state': 'available', 'scope': 'remote job listings'},
        {'source': 'Adzuna', 'state': ('configured_not_tested' if adzuna_ready() else
                                    'approval_required' if not approved else 'credentials_required'),
         'credentials_present': credentials, 'use_approved': approved,
         'access_url': 'https://developer.adzuna.com/',
         'note': 'Sales prospecting and lead generation require Adzuna written agreement.'},
        {'source': 'Indeed', 'state': 'partner_access_required',
         'access_url': 'https://docs.indeed.com/',
         'note': 'No direct Indeed search connector is enabled.'},
        {'source': 'ZipRecruiter', 'state': 'connection_verification_required',
         'access_url': 'https://api.ziprecruiter.com/mcp/docs',
         'note': 'Connection and live search contract have not been verified.'},
    ]


def _text(value, limit=1000):
    return value.strip()[:limit] if isinstance(value, str) else ''


def _public_url(value):
    value = _text(value, 1600)
    try:
        parsed = urlparse(value)
        if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return ''


def search_adzuna(query, location=''):
    if not adzuna_ready():
        return {'source': 'Adzuna', 'state': 'not_enabled', 'results': [],
                'message': 'Adzuna requires approved use and server credentials.'}
    try:
        # One bounded page per tool call. Never put credentials in diagnostic output.
        response = requests.get('https://api.adzuna.com/v1/api/jobs/us/search/1',
            params={'app_id': os.environ['ADZUNA_APP_ID'], 'app_key': os.environ['ADZUNA_APP_KEY'],
                    'what': _text(query, 700), 'where': _text(location, 200),
                    'results_per_page': 20, 'content-type': 'application/json'},
            timeout=(4, 10), allow_redirects=False)
        if response.status_code != 200:
            return {'source': 'Adzuna', 'state': 'provider_error', 'results': [],
                    'message': f'Adzuna returned HTTP {response.status_code}; other sources continue.'}
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
            raise ValueError('Invalid job-feed envelope')
        rows = []
        observed = datetime.now(timezone.utc).isoformat()
        for item in payload['results'][:20]:
            if not isinstance(item, dict):
                continue
            url = _public_url(item.get('redirect_url'))
            title = _text(item.get('title'), 500)
            company = item.get('company')
            company = _text(company.get('display_name'), 300) if isinstance(company, dict) else ''
            place = item.get('location')
            place = _text(place.get('display_name'), 300) if isinstance(place, dict) else ''
            if not url or not title or not company:
                continue
            rows.append({'type': 'job', 'id': str(item.get('id') or '')[:120],
                'title': title, 'company': company, 'job_location': place, 'url': url,
                'subtitle': ' | '.join(x for x in (company, place, _text(item.get('description'), 1800)) if x),
                'published_at': _text(item.get('created'), 80), 'observed_at': observed,
                'source': 'Adzuna', 'attribution_url': 'https://www.adzuna.com/',
                'status': 'Candidate — verification pending',
                'freshness': 'provider_listing_requires_current_posting_verification'})
        return {'source': 'Adzuna', 'state': 'results' if rows else 'empty', 'results': rows,
                'message': '' if rows else 'Adzuna returned no usable matching listings on this page.'}
    except (requests.RequestException, ValueError, TypeError, KeyError):
        # Request exceptions may contain the complete URL, including API credentials.
        return {'source': 'Adzuna', 'state': 'provider_error', 'results': [],
                'message': 'Adzuna request failed; other sources continue.'}


def search_jobs(query, location, legacy_search):
    """Keep independent feeds usable when another feed fails; no provider retry loop."""
    def remotive():
        rows = legacy_search(query)
        if not isinstance(rows, list) or any(isinstance(x, dict) and x.get('error') for x in rows):
            return {'source': 'Remotive', 'state': 'provider_error', 'results': [],
                    'message': 'Remotive request failed; other sources continue.'}
        rows = [x for x in rows if isinstance(x, dict) and _public_url(x.get('url'))]
        return {'source': 'Remotive', 'state': 'results' if rows else 'empty', 'results': rows, 'message': ''}

    feeds = {'Remotive': remotive}
    if adzuna_ready():
        feeds['Adzuna'] = lambda: search_adzuna(query, location)
    outcomes = []
    pool = ThreadPoolExecutor(max_workers=len(feeds))
    futures = {pool.submit(fn): name for name, fn in feeds.items()}
    try:
        for future in as_completed(futures, timeout=18):
            try:
                outcomes.append(future.result())
            except Exception:
                outcomes.append({'source': futures[future], 'state': 'provider_error', 'results': [],
                                 'message': f'{futures[future]} request failed; other sources continue.'})
    except FutureTimeout:
        outcomes.extend({'source': name, 'state': 'timeout', 'results': [],
                         'message': f'{name} timed out; other sources continue.'}
                        for future, name in futures.items() if not future.done())
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    rows = []; seen = set()
    for outcome in outcomes:
        for row in outcome['results']:
            key = row['url']
            if key not in seen:
                rows.append(row); seen.add(key)
    return {'configured': True, 'source': ' + '.join(feeds), 'results': rows,
            'providers': [{k: v for k, v in x.items() if k != 'results'} for x in outcomes],
            'message': ' '.join(x['message'] for x in outcomes if x.get('message'))}
