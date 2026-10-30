"""AutoHunt discovery and public contact collection. Never purchases email data.

Search providers supply hints, current company pages supply contact evidence,
and DNS supplies routing information only. Hunter checks collected mailboxes
automatically when enabled; verification never authorizes outreach.
"""
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from app import db
from src.company_identity import (host, shared_host, owned_host, identity_proof,
    current_contact_source, location_matches, page_metadata, visible_page_text, email_on_domain)
from src.contact_assessment import is_shared_email, person_email_supported
from src.enrichment import enrich_lead
from src.email_validation import check_email_domain
from src.execution_deadline import checkpoint
from src.research_policy import COUNT_WORDS


def accepts(query):
    from src.hunter_research import is_contact_list_query
    from src.job_evidence import is_hiring_query
    from src.research_intent import parse_research_request
    intent=parse_research_request(query)
    owner_request=('decision_maker' in intent['fields'] and not is_hiring_query(query)
        and not re.search(r'\b(?:needing|seeking)\b|\b(?:companies|businesses|firms)\s+looking for\b',query,re.I))
    return (is_contact_list_query(query) or owner_request) and bool(
        set(intent['fields']).intersection({'email','phone','decision_maker'})
        or re.search(r'\b(?:contacts?|enrich\w*|hunter|auto\s*hunt)\b',query,re.I))


def request_filters(query, location):
    """Conservative search hints; unsupported conditions remain visible for review."""
    clean=re.sub(r'(?i)\b(?:use|using|with)\s+auto\s*hunt\b|\bauto\s*hunt\b',' ',query)
    prefix=re.split(r'\b(?:business(?:es)?|compan(?:y|ies)|prospects?|leads?)\b',clean,1,flags=re.I)[0]
    prefix=re.split(r'\b(?:in|near|around|with|that|who)\b',prefix,1,flags=re.I)[0]
    stop=set('i give find show list research get me us please up to only a an the local nearby business businesses owners owner founders founder presidents president managers manager directors director contacts contact decision maker makers decisionmaker decisionmakers decision-maker decision-makers phone phones telephone mobile cellphone cellphones email emails numbers number ceo ceos'.split())|set(COUNT_WORDS)
    terms=[t for t in re.findall(r'[a-z][a-z-]+',prefix.lower()) if t not in stop]
    terms=[t for t in terms if t not in {'i','m','im','am','we','re','are','looking','for','need','want','their'}]
    # These conditions need their own evidence, not a keyword match on a site.
    extra=bool(re.search(r'\b(?:revenue|employees?|headcount|rating|rated|stars?|over|under|at least|more than|less than|without|excluding|except|open 24|family.owned|women.owned|veteran.owned)\b',query,re.I))
    tail=re.split(r'\b(?:business(?:es)?|compan(?:y|ies)|prospects?|leads?)\b',query,1,flags=re.I)
    instructions=set('in near around only with their its the and or also use using hunter io enrich enrichment verify verified verification valid available emails email contacts contact decision maker makers owner owners name names role roles phone phones number numbers please me give show to make sure they have those them it he s i owe autohunt auto hunt that updated current recently'.split())
    instructions.update(re.findall(r'[a-z]+',location.lower()))
    instructions.update('but i we need want information info details like manager managers ceo ceos president presidents founder founders director directors etc'.split())
    if len(tail)>1 and any(t not in instructions for t in re.findall(r'[a-z]+',tail[1].lower())):extra=True
    return {'query':query,'location':location,'industry_terms':list(dict.fromkeys(terms)),
            'additional_filters_need_review':extra}


def _primary_seed(raw):
    """Resolve a web hit's company name from its fetched primary page only."""
    from src.public_fetch import public_get
    url=raw.get('url') or ''
    if shared_host(host(url)):return None
    try:
        response=public_get(url,timeout=4,max_bytes=200000)
        if response.status_code!=200 or not owned_host(response.url,url):return None
        metadata=page_metadata(response.text)
        page={**metadata,'url':response.url,'page_text':visible_page_text(response.text)}
        names=[x.get('name') for x in metadata.get('source_organizations') or []
               if isinstance(x,dict) and owned_host(response.url,x.get('url') or '')]
        names += [x.get('name') for x in metadata.get('source_brand_links') or []
                  if isinstance(x,dict) and x.get('url')=='/']
        names += re.split(r'\s+[|–—-]\s+|\s*\|\s*',metadata.get('source_title') or '')
        names=[str(n).strip() for n in names if isinstance(n,str) and n.strip()]
        names=[n for n in names if not re.search(r'(?i)\b(?:home|contact|welcome|best|top|directory|results)\b',n)]
        website=f'{urlparse(response.url).scheme}://{urlparse(response.url).netloc}/'
        name=next((n for n in names if identity_proof(n,page,website)),None)
        if name:return {'company':name,'website':website,'source_url':website,'listing_location':'',
                        'discovery_source':'Web search','discovery_url':url}
    except Exception:pass
    return None


def discover(filters, limit, cached=()):
    from universal_app import _search_businesses
    from src.contact_sources import search as search_sources
    from src.research_intent import parse_research_request
    wants_people='decision_maker' in parse_research_request(filters['query'])['fields']
    companies=[];seen=set();diagnostics=[];leadership_domains=[]
    def add(row):
        domain=host(row.get('website'))
        if domain and not shared_host(domain) and domain not in seen and row.get('company'):
            seen.add(domain);companies.append(row)
    for row in cached:add(row)
    topic=' '.join(filters['industry_terms'])+' businesses'
    if len(companies)<limit:
        checkpoint('discovering_businesses',requested=limit)
        try:
            result=_search_businesses(topic,filters['location'])
            if result.get('message'):diagnostics.append(result['message'])
            for raw in result.get('results') or []:
                if raw.get('status')=='CLOSED_PERMANENTLY':continue
                add({'company':raw.get('title'),'website':raw.get('website'),'source_url':raw.get('website'),
                     'listing_location':raw.get('subtitle') or '', 'discovery_source':'Google Places',
                     'company_phone':raw.get('phone') or '',
                     'discovery_url':raw.get('url') or raw.get('website')})
        except Exception as exc:diagnostics.append('Business search unavailable: '+type(exc).__name__)
    if len(companies)<limit or wants_people:
        checkpoint('researching_more_sources',requested=limit)
        try:
            result=search_sources(topic+(' owner president CEO leadership official company website' if wants_people else ' official company website'),filters['location'])
            if result.get('message'):diagnostics.append(result['message'])
            for raw in result.get('results') or []:
                checkpoint('reviewing_company_source')
                seed=_primary_seed(raw)
                if seed:
                    add(seed)
                    if wants_people and host(seed['website']) not in leadership_domains:leadership_domains.append(host(seed['website']))
        except Exception as exc:diagnostics.append('Web search unavailable: '+type(exc).__name__)
    if wants_people:
        companies.sort(key=lambda row:leadership_domains.index(host(row['website'])) if host(row['website']) in leadership_domains else len(leadership_domains))
    return companies[:min(100,max(limit*2,limit))],diagnostics


def _evidence(lead):
    try:return json.loads(lead.evidence_json or '[]')
    except (ValueError,TypeError):return []


def snapshot(lead):
    return next((x for x in reversed(_evidence(lead)) if isinstance(x,dict) and x.get('source')=='automake_contact_research'),None)



def _published_direct_phone(person):
    """Only an explicitly labeled number in this person's source excerpt."""
    text=str(person.get('evidence_excerpt') or '')
    name=str(person.get('name') or '')
    at=text.find(name)
    if not name or at<0:return ''
    after=text[at+len(name):at+len(name)+180]
    match=re.search(r'(?i)\b(?:direct(?: line)?|mobile|cell(?: phone)?)\s*[:#-]?\s*((?:\+?1[ .-]?)?\(?[2-9]\d{2}\)?[ .-]?\d{3}[ .-]?\d{4})',after)
    return match.group(1) if match else ''


def _published_person_email(person, website):
    """Preserve a published profile email for research without granting send authority."""
    from src.contact_assessment import EMAIL, PAIR, email_name_consistent, current_email_context
    text=str(person.get('evidence_excerpt') or '')
    name=person.get('name') or ''
    if not name or not owned_host(person.get('source_url') or '',website):return ''
    matches=list(PAIR.finditer(text))
    if len(matches)!=1 or matches[0].group(1)!=name:return ''
    # Sentence punctuation is not part of a published address. Keep internal
    # domain dots intact and leave the shared bounded address matcher unchanged.
    address_text=re.sub(r'\.(?=\s|$)',' ',text)
    emails=list(dict.fromkeys(email.lower() for email in EMAIL.findall(address_text)
        if email_on_domain(email,website) and not is_shared_email(email)
        and email_name_consistent(email,name) and current_email_context(text,email)))
    return emails[0] if len(emails)==1 else ''


def supplement_research_contacts(record,company,intent):
    """Provider-associated contacts are research evidence, not send permission."""
    from src import hunter_mailbox, hunter_discovery
    from src.mailbox_verification import verify_mailbox, current
    from v1_orchestration import _purpose_mailbox_allowed
    enrichment=record.get('enrichment') or {}
    if not hunter_mailbox.enabled() or enrichment.get('identity_status')!='source_bound':return
    people=enrichment.get('decision_maker_candidates') or []
    if any(p.get('email') or _published_person_email(p,company['website']) for p in people) or ('email' not in intent['fields'] and people):return
    checkpoint('hunter_contact_lookup')
    receipt=hunter_discovery.discover_contacts(company['website'],decision_makers=True)
    record['research_provider']={k:v for k,v in receipt.items() if k!='contacts'}
    contacts=[]
    for contact in receipt.get('contacts') or []:
        name=contact.get('name') or '';role=contact.get('title') or '';email=contact.get('email') or ''
        if (contact.get('type')!='personal' or len(name.split())<2 or is_shared_email(email)
            or not re.search(r'\b(?:owner|founder|president|ceo|chief executive|manager|director|partner|principal)\b',role,re.I)
            or not email_on_domain(email,company['website']) or not _purpose_mailbox_allowed(email)):continue
        check=verify_mailbox(email,provider='hunter',research_only=True) if 'email' in intent['fields'] else {}
        if check.get('mailbox_status')=='provider_rejected':continue
        cited=next((url for url in contact.get('source_urls') or [] if owned_host(url,company['website'])),None)
        contacts.append({'name':name,'role':role,'email':email if 'email' in intent['fields'] else '',
            'source_url':cited or 'https://hunter.io/domain-search?domain='+host(company['website']),
            'source_kind':'provider_cited_page' if cited else 'provider_record',
            'observed_at':receipt.get('checked_at'),'scope':'Hunter company-associated contact',
            'mailbox_validation':check,'email_status':'Verified' if current(check,email) else 'Email found · Mailbox not verified'})
        if len(contacts)>=3:break
    record['research_contacts']=contacts


def view(lead, record=None):
    record=record or snapshot(lead) or {}
    enrichment=record.get('enrichment') or {};fields=enrichment.get('fields') or {}
    email=fields.get('email') or {};assessment=enrichment.get('contact_assessment') or {}
    mailbox=assessment.get('mailbox_validation') or {}
    reasons=mailbox.get('reason_codes') or []
    issue=record.get('contact_issue') or ''
    if mailbox.get('provider')=='hunter' and reasons:
        issue=('Hunter verification credits are unavailable. Check Hunter usage in Settings.' if any('QUOTA' in r for r in reasons) else
               'Hunter verification is pending. Try verifying this email again shortly.' if any('PENDING' in r or 'IN_PROGRESS' in r for r in reasons) else
               'Hunter rejected this email address.' if mailbox.get('mailbox_status')=='provider_rejected' else
               'Hunter has not confirmed this mailbox. Check the Hunter connection in Settings or retry verification.')
    address=email.get('value') if email.get('validated') else ''
    from src.mailbox_verification import lead_status
    status=lead_status(lead,record)
    verified=bool(address and status['verified'])
    named=bool(address and person_email_supported(assessment,address))
    person=(fields.get('decision_maker') or {})
    business_matched=(record.get('business_research') or {}).get('filter_status')=='matched'
    people=[{'name':p['name'],'role':p['title'],'email':p.get('email') or _published_person_email(p,lead.source_url),
             'source_url':p['source_url'],'observed_at':p.get('observed_at'),
             'direct_phone':_published_direct_phone(p),
             'scope':'Local role supported' if p.get('status')=='source_supported' else 'Company leadership'}
            for p in enrichment.get('decision_maker_candidates') or []
            if p.get('status')=='source_supported' or (p.get('company_status')=='source_confirmed'
                and re.fullmatch(r'company owner|owner|founder|president|CEO|chief executive officer|general manager',p.get('title') or '',re.I))]
    names={p['name'].casefold() for p in people}
    people += [p for p in record.get('research_contacts') or [] if p['name'].casefold() not in names]
    direct=people[0].get('direct_phone') or '' if len(people)==1 else ''
    # A documented business owner can be displayed even without a personal email.
    # A general number scraped from the website is not their direct line.
    row={**(record.get('business_research') or {}),'company':lead.company,'title':lead.company,
         'website':lead.source_url,'source_url':lead.source_url,'location':lead.location,
         'provider_contact_research':True,'owned_contact_research':True,'classification':'Business found',
         'research_source':'AutoHunt','contact_email':address or '',
         'contact_name':person.get('value') or '', 'contact_role':person.get('title') or '',
         'contact_phone':(fields.get('phone') or {}).get('value') or (record.get('business_research') or {}).get('company_phone') or '',
         'phone_type':'direct' if direct else 'business_or_unconfirmed', 'direct_phone':direct, 'direct_phone_verified':bool(direct),
         'decision_maker_source_url':person.get('source_url') or '',
         'decision_makers':people,'research_observed_at':record.get('observed_at'),
         'contact_type':'Named decision-maker email' if named else 'Company inbox' if address and is_shared_email(address) else 'Published contact; person association unconfirmed' if address else '',
         'email_status':status['label'] if address else 'No email found','mailbox_verification':{k:v for k,v in status.items() if k!='receipt'},
         'email_source_url':email.get('source_url') or '', 'phone_source_url':people[0]['source_url'] if direct else (fields.get('phone') or {}).get('source_url') or (record.get('business_research') or {}).get('company_phone_source_url') or '',
         'email_observed_at':email.get('observed_at'), 'email_verified_on':status['verified_on'] if verified else None,
         'domain_status':(email.get('mail_validation') or {}).get('domain_status') or 'unconfirmed',
         'public_contacts':record.get('contacts') or [],'contact_issue':issue,
         'contact_check':{'mailbox_verified':verified,'named_contact':bool(address and person_email_supported(assessment,address))}}
    # Show useful provider results even when public sources only have an inbox.
    # They never overwrite the persisted recipient or public-source evidence.
    provider_person=next((p for p in record.get('research_contacts') or [] if p.get('email')),None)
    if provider_person and (not named or not address):
        from src.mailbox_verification import current
        check=provider_person.get('mailbox_validation') or {}
        valid=current(check,provider_person['email'])
        row.update(contact_email=provider_person['email'],contact_name=provider_person['name'],
            contact_role=provider_person['role'],contact_type='Hunter company-associated decision-maker',
            email_status=provider_person['email_status'],email_source_url=provider_person['source_url'],
            decision_maker_source_url=provider_person['source_url'],email_verified_on=check.get('provider_verified_on') if valid else None,
            mailbox_verification={'verified':valid,'provider':'hunter','checked_at':check.get('checked_at'),
                'verified_on':check.get('provider_verified_on'),'reason_codes':check.get('reason_codes') or []},
            contact_check={'mailbox_verified':valid,'named_contact':True},research_email_only=True,contact_issue='')
    elif not row['contact_name'] and people:
        row.update(contact_name=people[0]['name'],contact_role=people[0]['role'],decision_maker_source_url=people[0]['source_url'])
    if lead.id and not row.get('research_email_only'):row['lead_id']=lead.id
    return row


def collect(company, filters, cached=None):
    from outreach_bridge import _public_contact_evidence
    from v1_orchestration import _purpose_mailbox_allowed
    from src.email_syntax import EMAIL_RE
    from src.contact_assessment import current_email_context
    from src.company_identity import contact_context_matches
    rows=[r for r in (cached or {}).get('pages') or [] if current_contact_source(r)]
    cache_hit=bool(rows)
    if not rows:
        from src.research_intent import parse_research_request
        needs_people='decision_maker' in parse_research_request(filters['query'])['fields']
        rows,_=_public_contact_evidence({**company,'location':filters['location'],
            'decision_maker_research':needs_people,'query':'business outreach contact'},use_provider=False)
    rows=[r for r in rows if current_contact_source(r) and owned_host(r.get('url') or '',company['website'])
          and identity_proof(company['company'],r,company['website'])]
    # mailto/obfuscated values are source observations, not generated addresses.
    rows=[{**r,'page_text':str(r.get('page_text') or '')+'\n'+' '.join(
        e for e in r.get('validated_emails') or [] if e.lower() not in str(r.get('page_text') or '').lower())} for r in rows]
    enrichment=enrich_lead({'company':company['company'],'website':company['website'],
        'target_location':filters['location'],'query':'business outreach'},rows,email_allowed=_purpose_mailbox_allowed)
    contacts=[];seen=set();routing_cache={}
    for row in rows:
        for email in EMAIL_RE.findall(row.get('page_text') or ''):
            email=email.lower()
            if (email in seen or not email_on_domain(email,company['website']) or not _purpose_mailbox_allowed(email)
                or not current_email_context(row['page_text'],email)
                or not contact_context_matches(row['page_text'],email,filters['location'])):continue
            seen.add(email)
            if len(contacts)>=8:break
            domain=email.rsplit('@',1)[1]
            if domain not in routing_cache:routing_cache[domain]=check_email_domain(email)
            routing={**routing_cache[domain],'email':email}
            if routing['domain_status'] in {'invalid','does_not_exist','does_not_accept_mail'}:continue
            contacts.append({'email':email,'source_url':row['url'],'observed_at':row['observed_at'],
                'domain_status':routing['domain_status'],'mailbox_status':'unconfirmed','mail_validation':routing})
    candidate=enrichment.get('fields',{}).get('email')
    if candidate and not any(c['email']==candidate.get('value') for c in contacts):enrichment['fields'].pop('email',None);candidate=None
    if not candidate and contacts:
        chosen=next((c for c in contacts if is_shared_email(c['email'])),contacts[0])
        enrichment.setdefault('fields',{})['email']={'value':chosen['email'],'source_url':chosen['source_url'],
            'validated':True,'observed_at':chosen['observed_at'],'observation_status':'source_observed',
            'mailbox_status':'unconfirmed','deliverability_status':'unconfirmed','mail_validation':chosen['mail_validation']}
    elif candidate:
        chosen=next(c for c in contacts if c['email']==candidate['value']);candidate['mail_validation']=chosen['mail_validation']
    text=' '.join(str(r.get('page_text') or '') for r in rows)
    terms=filters['industry_terms']
    patterns={'dentists':r'\b(?:dentists?|dental|dentistry)\b','dentist':r'\b(?:dentists?|dental|dentistry)\b','dental':r'\b(?:dentists?|dental|dentistry)\b','electrical':r'\belectric(?:al|ians?)\b','electrician':r'\belectric(?:al|ians?)\b',
              'hvac':r'\b(?:hvac|heating|air conditioning)\b'}
    industry=bool(rows) and all(re.search(patterns.get(t,r'\b'+re.escape(t.rstrip('s'))+r'(?:s|es)?\b'),text,re.I) for t in terms)
    geography=not filters['location'] or location_matches(text,filters['location']) or location_matches(company.get('listing_location') or '',filters['location'])
    # Clear out-of-area listings are excluded; absent evidence stays unconfirmed.
    excluded=bool(company.get('listing_location') and not geography)
    fit=industry and geography and not filters['additional_filters_need_review']
    return {'source':'automake_contact_research','enrichment':enrichment,'pages':rows,'contacts':contacts,
        'cache_hit':cache_hit,'observed_at':datetime.now(timezone.utc).isoformat(),
        'business_research':{'business_status':'Industry and location matched' if fit else 'Business filters need review',
            'filter_status':'matched' if fit else 'unconfirmed','requested_filters':filters,
            'research_source':'AutoHunt','supporting_urls':[r['url'] for r in rows],
            'company_phone':company.get('company_phone') or '' if company.get('discovery_source')=='Google Places' else '',
            'company_phone_source_url':company.get('discovery_url') or '' if company.get('discovery_source')=='Google Places' else '',
            'discovery_source':company.get('discovery_source'),'discovery_url':company.get('discovery_url'),
            'listing_location':company.get('listing_location') or ''},'excluded':excluded,
        'contact_issue':'' if rows else 'Company identity or public contact pages could not be confirmed.'}


def run(campaign, *, save_contacts=True):
    from outreach_automation import OutreachLead
    from workspace_security import OWNER,scope,claim
    from src.hunter_research import search_location
    from src.campaign_reporting import attribute_new_lead
    from src.research_intent import parse_research_request, format_research_results
    intent=parse_research_request(campaign['query'])
    from src import hunter_mailbox
    from src.mailbox_verification import verify_mailbox, current
    verify_emails=hunter_mailbox.enabled() and 'email' in intent['fields']
    location=search_location(campaign['query'],campaign.get('territory') or '')
    filters=request_filters(campaign['query'],location);limit=campaign['target_count']
    saved=[];views=[];cached=[];snapshots={}
    if save_contacts:
        for lead in OutreachLead.query.filter(scope(OutreachLead,'lead',OWNER),OutreachLead.status=='needs_evidence').order_by(OutreachLead.id.desc()).limit(200):
            record=snapshot(lead)
            if record and any(current_contact_source(p) for p in record.get('pages') or []):
                research=record.get('business_research') or {}
                if research.get('requested_filters')==filters:
                    cached.append({'company':lead.company,'website':lead.source_url,**research})
                    snapshots[host(lead.source_url)]=record
    companies,diagnostics=discover(filters,limit,cached)
    checkpoint('business_results_ready',businesses=[{**c,'owned_contact_research':True,'provider_contact_research':True,
        'research_source':'AutoHunt','contact_status':'Collecting public contacts'} for c in companies[:limit]],discovered=len(companies),requested=limit,research_intent=intent)
    wants_people='decision_maker' in intent['fields']
    def ready(row):
        people=row.get('decision_makers') or []
        named=bool(row.get('contact_name') or people)
        phone=bool(row.get('direct_phone_verified') and row.get('direct_phone')) or any(p.get('direct_phone') for p in people)
        email=any(p.get('email') for p in people) or bool((row.get('contact_check') or {}).get('named_contact') and row.get('contact_email'))
        return named and ('phone' not in intent['fields'] or phone) and ('email' not in intent['fields'] or email)
    for company in companies:
        deadline_hit=False
        if (sum(ready(row) for row in views)>=limit if wants_people else len(views)>=limit):break
        try:
            checkpoint('collecting_public_contacts',businesses=views,requested=limit)
            record=collect(company,filters,snapshots.get(host(company['website'])))
        except TimeoutError:
            if views:
                diagnostics.append('Showing contacts collected before the search time limit.')
                break
            raise
        except Exception:
            diagnostics.append('A company source was unavailable; continuing with other businesses.')
            continue
        if record['excluded']:continue
        if wants_people:
            try:supplement_research_contacts(record,company,intent)
            except TimeoutError:
                diagnostics.append('Optional contact lookup timed out; showing the public sources already collected.')
                deadline_hit=True
            except Exception:
                diagnostics.append('Contact provider unavailable; showing collected public contacts.')
        lead=OutreachLead.query.filter_by(company=company['company'],source_url=company['website']).filter(scope(OutreachLead,'lead',OWNER)).first() if save_contacts else None
        if lead and (lead.sent_at or lead.gmail_message_id or lead.status!='needs_evidence'):
            # Do not change active, stopped, or previously prepared conversations.
            shown=view(lead) if snapshot(lead) else view(OutreachLead(company=company['company'],source_url=company['website'],location=location),record)
            views.append(shown)
            if deadline_hit:break
            continue
        if not lead:
            lead=OutreachLead(company=company['company'],source_url=company['website'],location=location,status='needs_evidence',score=0,verification='CANDIDATE')
        address=(record['enrichment'].get('fields',{}).get('email') or {}).get('value') or ''
        if lead.contact_email==address:
            from src.mailbox_verification import lead_status
            previous=lead_status(lead)
            if previous['verified'] and (not verify_emails or previous['provider']=='hunter'):
                record['enrichment'].setdefault('contact_assessment',{})['mailbox_validation']=previous['receipt']
        else:lead.subject='';lead.body=''
        lead.contact_email=address
        field=record['enrichment'].get('fields',{}).get('email') or {}
        assessment=record['enrichment'].setdefault('contact_assessment',{})
        check=assessment.get('mailbox_validation') or {}
        if not deadline_hit and verify_emails and address and field.get('validated') and not (check.get('provider')=='hunter' and current(check,address)):
            try:
                checkpoint('verifying_research_mailbox',businesses=views,requested=limit)
                check=verify_mailbox(address,provider='hunter',research_only=True)
            except TimeoutError:
                check={};deadline_hit=True
                diagnostics.append('Mailbox verification timed out; published contact details remain available.')
            assessment['mailbox_validation']=check
            field['mailbox_status']=check.get('mailbox_status','unconfirmed')
            field['deliverability_status']=check.get('deliverability_status','unconfirmed')
        assessment=record['enrichment'].get('contact_assessment') or {}
        lead.contact_name=(record['enrichment'].get('fields',{}).get('decision_maker') or {}).get('value') or ''
        lead.evidence_json=json.dumps([record,{'source':'campaign_context','context':{
            'query':campaign['query'],'offer':campaign.get('offer') or '', 'target_location':location,
            'owned_contact_research':True,'require_decision_maker':campaign.get('require_decision_maker') is True}}])
        if save_contacts:
            # Hunter stores its lease in a separate transaction. Finish the
            # mailbox check before flushing a new lead (also works on SQLite).
            if lead.id is None:
                db.session.add(lead);db.session.flush();claim('lead',lead.id,OWNER);attribute_new_lead(lead)
            db.session.commit();saved.append(lead.id)
        views.append(view(lead,record))
        if deadline_hit:break
        checkpoint('public_contacts_collected',businesses=views,discovered=len(views),requested=limit,
            contacts_verified=sum(v['contact_check']['mailbox_verified'] for v in views),
            research_intent=intent,research_presentation=format_research_results(views,intent))
    # A company-only row must not displace a researched decision-maker when
    # the user asked for people. Keep partial results when sources run out.
    if wants_people:views.sort(key=lambda row:(ready(row),bool(row.get('contact_name') or row.get('decision_makers'))),reverse=True)
    views=views[:limit]
    presentation=format_research_results(views,intent)
    return {'ok':True,'contact_research':True,'owned_contact_research':True,'research_intent':intent,
        'research_presentation':presentation,'campaign':{**campaign,'territory':location},
        'discovery':{'results':views,'count':len(views),'verified':sum(v['contact_check']['mailbox_verified'] for v in views),'emails_found':sum(bool(v['contact_email']) for v in views),
            'target_count':limit,'target_met':len(views)>=limit,'contact_target_met':not wants_people or sum(ready(row) for row in views)>=limit,'decision_makers_found':sum(bool(row.get('contact_name') or row.get('decision_makers')) for row in views),'source':'automake_public_sources','diagnostics':diagnostics},
        'outreach':{'lead_ids':saved,'saved':len(saved),'qualified':0,'drafted':0,'sent':0},'business_progress':views},None,None


from app import app
from flask import request,jsonify


@app.post('/api/chat/contacts/verify')
def verify_owned_contact():
    """Explicit mailbox-only action; never discovers, drafts, sends, or activates."""
    from outreach_automation import OutreachLead
    from workspace_security import owns
    from src.mailbox_verification import verify_mailbox
    data=request.get_json(silent=True) or {}
    if not isinstance(data,dict):return jsonify(ok=False,error='Invalid contact selection.'),400
    lead_id=data.get('lead_id')
    if type(lead_id) is not int or not owns('lead',lead_id):return jsonify(ok=False,error='Contact not found.'),404
    lead=db.session.get(OutreachLead,lead_id)
    record=snapshot(lead) if lead else None
    if not record:return jsonify(ok=False,error='Public contact not found.'),404
    field=(record.get('enrichment') or {}).get('fields',{}).get('email') or {}
    email=field.get('value') or ''
    pages=[p for p in record.get('pages') or [] if current_contact_source(p)
           and p.get('url')==field.get('source_url') and identity_proof(lead.company,p,lead.source_url)]
    if not field.get('validated') or not email or email!=lead.contact_email or not pages:
        return jsonify(ok=False,error='Refresh this contact’s public sources before verifying its mailbox.'),409
    if lead.sent_at or lead.gmail_message_id or lead.status!='needs_evidence':
        return jsonify(ok=False,error='This conversation is already being managed. Its contact was not changed.'),409
    original_evidence=lead.evidence_json
    from src import hunter_mailbox
    result=verify_mailbox(email,provider='hunter') if hunter_mailbox.enabled() else verify_mailbox(email)
    # Discard a provider receipt for any other address.
    if result.get('email')!=email:return jsonify(ok=False,error='Mailbox verification did not confirm this address.'),502
    record['enrichment'].setdefault('contact_assessment',{})['mailbox_validation']=result
    rows=_evidence(lead)
    rows=[record if r.get('source')=='automake_contact_research' else r for r in rows]
    changed=OutreachLead.query.filter_by(id=lead.id,evidence_json=original_evidence,status='needs_evidence',
        contact_email=email,gmail_message_id=lead.gmail_message_id,sent_at=lead.sent_at).update({'evidence_json':json.dumps(rows)},synchronize_session=False)
    if not changed:db.session.rollback();return jsonify(ok=False,error='This contact changed while verification was running. Refresh its details.'),409
    db.session.commit();db.session.refresh(lead)
    row=view(lead,record)
    return jsonify(ok=True,contact=row,message='Mailbox verified.' if row['email_status']=='Verified' else 'Mailbox not verified. No email was sent.')
