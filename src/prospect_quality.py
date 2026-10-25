"""Evidence-led prospect assessments. Email validity never changes business fit/need."""
import json
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from src.company_identity import current_contact_source, identity_proof, location_matches, owned_host
from src.job_evidence import check_job_evidence

POLICY = 'evidence-led-v1'


def text(value, limit=1200):
    return ' '.join(str(value or '').split())[:limit]


def request_spec(query, location='', offer='', business_type=''):
    # Preserve the original request; extracted terms are conservative search hints.
    target = business_type or re.split(r'\b(?:in|near|around|with|that|hiring|seeking)\b', query, 1, flags=re.I)[0]
    stop = set('find show get give list research me us up to companies company businesses business prospects leads ten twenty a an the please'.split())
    from src.research_policy import COUNT_WORDS
    stop.update(COUNT_WORDS)
    terms = [w for w in re.findall(r'[a-z][a-z-]+', target.lower()) if w not in stop]
    return {'query': text(query), 'location': text(location, 200), 'offer': text(offer),
            'business_type': text(business_type, 300), 'business_terms': list(dict.fromkeys(terms))[:8],
            'action': 'research_and_prepare_drafts', 'sending': False}


def process_terms(offer):
    groups = [
        (r'schedul|appointment|booking|dispatch', ['scheduling', 'appointment', 'booking', 'dispatch']),
        (r'inquir|follow.?up|customer|lead|response|reception', ['inquiries', 'follow up', 'customer service', 'phone', 'calls', 'reception', 'scheduling']),
        (r'invoic|billing|account|data.?entry', ['invoice', 'billing', 'accounts', 'data entry']),
    ]
    matched=list(dict.fromkeys(term for pattern, terms in groups if re.search(pattern, offer, re.I) for term in terms))
    if matched:return matched
    stop=set('automate automation automated business service services improve improving help helping workflow workflows solution solutions'.split())
    return list(dict.fromkeys(w for w in re.findall(r'[a-z]{4,}',offer.lower()) if w not in stop))[:8]


def assess(company, website, context, evidence, contact=None, now=None):
    """Use direct company pages and current posting checks, never query text as proof."""
    now = now or datetime.now(timezone.utc)
    spec = context.get('request_spec')
    if not isinstance(spec,dict) or not spec:
        spec=request_spec(context.get('query', ''), context.get('target_location', ''),context.get('offer', ''), context.get('business_type', ''))
    sources = []; seen = set()
    for row in evidence:
        if not isinstance(row, dict) or not current_contact_source(row, now):
            continue
        url = row.get('url') or row.get('source_url')
        if not url or url in seen or not identity_proof(company, row, website):
            continue
        seen.add(url); sources.append(row)
    location = spec.get('location') or ''
    terms = spec.get('business_terms') or []
    fit_pages = [r for r in sources if (not location or location_matches(r.get('page_text') or r.get('text') or '', location))
                 and all(re.search(r'\b'+re.escape(w)+r'(?:s|es)?\b', str(r.get('page_text') or r.get('text') or ''), re.I) for w in terms)]
    fit_ok = bool(fit_pages and terms and spec.get('offer'))
    fit = {'state': 'Strong' if fit_ok else 'Partial' if sources else 'Missing',
           'reason': 'Direct company evidence supports the requested business type and geography.' if fit_ok else
                     'Confirm business type, geography and the offer using current company evidence.'}
    needs = []; relevant = process_terms(spec.get('offer', ''))
    for row in fit_pages:
        page = text(row.get('page_text') or row.get('text'), 20000)
        # A source-authored current job, not a generic careers link, can show workload.
        for posting in row.get('source_job_postings') or []:
            if not isinstance(posting, dict):continue
            title = text(posting.get('title'), 250)
            description = text(posting.get('description'), 6000)
            if not any(t in (title+' '+description).lower() for t in relevant):continue
            query = 'companies hiring '+title
            proof = check_job_evidence(row, query, location, company, now=now)
            if proof.get('ok'):
                needs.append({'kind': 'current_relevant_hiring', 'url': row['url'],
                    'observation': title, 'interpretation': 'This role suggests workload relevant to the offer; interest in automation and budget are unconfirmed.',
                    'published_at': proof.get('date_posted'), 'observed_at': row.get('observed_at')})
        # Only explicit first-person ongoing need/process language; service advertising
        # and generic scheduling/contact controls cannot establish the company's need.
        for match in re.finditer(r'\bwe\s+(?:currently\s+)?(?:need help|are seeking help|are looking for help|manually (?:process|manage|schedule|track|enter))\b[^.!?]{0,200}', page, re.I):
            quote = match.group(0)
            if relevant and any(t in quote.lower() for t in relevant) and not re.search(r'\b(?:not|no longer|previously|used to)\b', quote, re.I):
                needs.append({'kind': 'observed_ongoing_process', 'url': row['url'], 'observation': quote,
                    'interpretation': 'The source describes an ongoing process relevant to the offer; purchase intent and budget are unconfirmed.',
                    'published_at': row.get('published_at'), 'observed_at': row.get('observed_at')})
    need = {'state': 'Supported' if needs else 'Missing', 'signals': needs[:4],
            'reason': needs[0]['interpretation'] if needs else 'No directly supported need relevant to this offer has been established.'}
    contact = contact or {}
    person = contact.get('person_supported') is True
    mailbox = contact.get('mailbox_verified') is True
    ready = person and mailbox
    contact_state = {'state': 'Ready' if ready else 'Partial' if contact.get('email_present') else 'Pending',
                     'reason': 'Named buyer association and mailbox checks are supported.' if ready else
                               'Confirm the responsible buyer, their email association and mailbox status.',
                     'buyer': contact.get('name') if person else '', 'role': contact.get('role') if person else '',
                     'mailbox_status': contact.get('mailbox_status') or 'unconfirmed'}
    missing = []
    if not fit_ok:missing.append('BUSINESS_FIT_EVIDENCE_REQUIRED')
    if not needs:missing.append('OFFER_NEED_EVIDENCE_REQUIRED')
    if not person:missing.append('RESPONSIBLE_BUYER_REQUIRED')
    if not mailbox:missing.append('VERIFIED_MAILBOX_REQUIRED')
    return {'version': POLICY, 'checked_at': now.isoformat(), 'request': spec, 'fit': fit, 'need': need,
            'contact': contact_state, 'well_supported': fit_ok and bool(needs), 'ready': fit_ok and bool(needs) and ready,
            'missing': missing, 'rank': (2 if fit_ok else 1 if sources else 0)*10+(2 if needs else 0),
            'ranking_basis': 'Business fit and source-supported offer need. Contact validity adds no ranking points.',
            'why_business': fit['reason'], 'why_now': (needs[0]['observation']+' — publication date '+str(needs[0].get('published_at') or 'unconfirmed')) if needs else 'Urgency and current business need are unconfirmed.',
            'who': ' '.join(x for x in [contact_state['buyer'], contact_state['role']] if x) or 'Responsible buyer not confirmed.',
            'sources': [{'url': r['url'], 'observed_at': r.get('observed_at'), 'published_at': r.get('published_at')} for r in sources[:6]]}


def collect_sources(result, context):
    """Bounded additional primary-source research, only for the new quality policy."""
    from smart_search import _page_snapshot, _exa_search
    from src.execution_deadline import checkpoint
    company = result.get('company') or result.get('title') or ''
    website = result.get('website') or ''
    if not website:return []
    deadline = time.monotonic()+25
    rows = []; seen = set()
    def fetch(url):
        if url in seen or not owned_host(url, website) or time.monotonic() >= deadline:return
        seen.add(url); checkpoint('checking_business_need')
        snap = _page_snapshot(url)
        row = {'url': url, **snap, 'source': 'prospect_primary_evidence'}
        if current_contact_source(row) and identity_proof(company, row, website):rows.append(row)
    fetch(website)
    if assess(company, website, context, rows)['well_supported']:return rows
    # One targeted retrieval and at most two advertised same-company destinations.
    if time.monotonic() < deadline-15:
        terms = ' '.join(process_terms(context.get('offer') or '')[:5])
        if terms:
            try:result = _exa_search(f'"{company}" site:{urlparse(website).hostname} {terms} hiring careers manual process', context.get('target_location') or '')
            except Exception:return rows
            for hint in (result.get('results') or [])[:3]:
                if len(seen)>=3:break
                fetch(hint.get('url') or '')
    return rows


def for_lead(lead, now=None):
    from outreach_automation import _server_qualification_inputs
    from src.contact_assessment import person_email_supported
    validated, context, evidence = _server_qualification_inputs(lead)
    assessment = validated.get('contact_assessment') or {}
    mailbox = assessment.get('mailbox_validation') or {}
    checked = mailbox.get('checked_at')
    try:
        stamp = datetime.fromisoformat(str(checked).replace('Z', '+00:00'))
        fresh = timedelta(0) <= (now or datetime.now(timezone.utc))-stamp <= timedelta(hours=1)
    except (TypeError, ValueError):fresh = False
    contact = {'person_supported': person_email_supported(assessment, lead.contact_email),
               'mailbox_verified': fresh and mailbox.get('mailbox_status')=='provider_verified' and mailbox.get('email')==lead.contact_email,
               'mailbox_status': mailbox.get('mailbox_status'), 'email_present': bool(lead.contact_email), 'name': lead.contact_name}
    buyer_supported=False
    for row in evidence:
        enrichment=row.get('enrichment') or {}
        for person in enrichment.get('decision_maker_candidates') or []:
            if (person.get('name')!=lead.contact_name or person.get('status')!='source_supported'
                    or person.get('responsibility_status')!='source_supported'
                    or not owned_host(person.get('source_url') or '',lead.source_url)):
                continue
            try:
                stamp=datetime.fromisoformat(str(person.get('observed_at')).replace('Z','+00:00'))
                recent=timedelta(0)<=(now or datetime.now(timezone.utc))-stamp<=timedelta(hours=1)
            except (TypeError,ValueError):recent=False
            if recent:
                buyer_supported=True;contact['role']=person.get('title') or ''
    contact['person_supported']=contact['person_supported'] and buyer_supported
    return assess(lead.company, lead.source_url, context, evidence, contact, now)
