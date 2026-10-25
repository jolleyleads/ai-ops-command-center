"""Provider-native business discovery -> contact association -> mailbox check.

This path researches contacts only. It cannot send, book or infer purchase intent.
Existing selected-workflow activation owns all subsequent outreach.
"""
import json
import hashlib
import os
import re
import time
import uuid

import requests

from app import app, db
from src import hunter_mailbox as mailbox
from src.company_identity import host, shared_host
from src.execution_deadline import checkpoint


class ContactResearchUnavailable(RuntimeError):
    """A safe, user-facing provider failure with no credential contents."""


def is_contact_list_query(query):
    from src.job_evidence import is_hiring_query
    return bool(re.search(r'\b(?:businesses|companies|prospects|leads)\b',query,re.I)
                and not is_hiring_query(query)
                and not re.search(r'\b(?:permits?|licenses?|needing|needs?|seeking|looking for|buying|struggling)\b',query,re.I))


def use_native_contact_search(query):
    return is_contact_list_query(query) and (mailbox.enabled() or bool(re.search(r'\bhunter\b|verified\s+emails?',query,re.I)))


def search_location(query, fallback=''):
    from src.job_evidence import requested_location
    # A city explicitly typed in chat wins over the saved territory field.
    explicit=requested_location(query)
    explicit=re.split(r'\b(?:use|using|enrich|verify|verified|contacts?|emails?)\b',explicit,1,flags=re.I)[0].strip(' ,. ')
    return explicit or fallback


def allows_company_inbox(query):
    """Only an explicit fallback request permits a shared company address."""
    return bool(re.search(r'(?is)\b(?:fallback|otherwise|if\s+(?:unavailable|not\s+(?:found|available)))\b.{0,100}\bcompany\s+(?:email|inbox)\b', query))


def _web_companies(query, location, limit):
    from smart_search import _smart_search
    # Keep every business constraint, including clauses after a Hunter request.
    # The search relevance parser treats enrichment words as instructions.
    result=_smart_search(query,location,runtime_budget=35,target_count=limit)
    companies=[];seen=set()
    for raw in result.get('results') or []:
        if not isinstance(raw,dict) or raw.get('classification')=='Rejected':continue
        website=raw.get('website') or raw.get('source_url') or raw.get('url') or ''
        domain=host(website);name=raw.get('company') or raw.get('name') or raw.get('title')
        if not domain or shared_host(domain) or domain in seen or not name:continue
        seen.add(domain)
        companies.append({**raw,'company':name,'title':name,'website':website,'source_url':website,
            'location':raw.get('location') or location,'provider_contact_research':True,
            'research_source':'Web research','business_status':('Business verified' if raw.get('classification')=='Verified Lead' else 'Business match unconfirmed'),
            'contact_status':'Finding contact'})
    return companies[:limit]


def discover_companies(query, location, limit, get=None, post=None):
    """Research businesses first; Hunter Discover is the explicit fallback."""
    if get is None and post is None:
        try:
            companies=_web_companies(query,location,limit)
        except TimeoutError:
            raise  # Cancellation/deadline must never launch another provider.
        except Exception as exc:
            app.logger.warning('BUSINESS_WEB_DISCOVERY_UNAVAILABLE type=%s',type(exc).__name__)
            companies=[]
        if companies:return {'provider':'web','companies':companies,'reason_codes':[]}
        checkpoint('discovering_businesses')
    receipt={'provider':'hunter','companies':[],'reason_codes':[]}
    key=os.getenv('HUNTER_API_KEY','').strip()
    expected=os.getenv('HUNTER_ACCOUNT_EMAIL','').strip().lower()
    if not mailbox.enabled():return {**receipt,'reason_codes':['HUNTER_NOT_ENABLED']}
    if not key or key=='test-api-key':return {**receipt,'reason_codes':['HUNTER_REAL_CREDENTIAL_REQUIRED']}
    if not expected:return {**receipt,'reason_codes':['HUNTER_ACCOUNT_EMAIL_REQUIRED']}
    token=uuid.uuid4().hex
    # Discover and account checks cost no credits. A prior paid-operation quota
    # pause must not block these free calls or conceal a restored balance.
    account_key,blocked=mailbox._claim_account(expected,token,time.time(),free_lookup=True)
    if blocked:return {**receipt,'reason_codes':[blocked]}
    try:
        account,code=mailbox._request('account',key,{},get or requests.get)
        receipt['account_http_status']=code
        if not isinstance(account,dict):receipt['reason_codes']=['HUNTER_ACCOUNT_CHECK_FAILED']
        elif str(account.get('email') or '').lower()!=expected:receipt['reason_codes']=['HUNTER_ACCOUNT_MISMATCH']
        elif str(account.get('plan_name') or '').lower()!='free':receipt['reason_codes']=['HUNTER_FREE_PLAN_REQUIRED']
        else:
            usage=account.get('requests') or {}
            app.logger.warning('HUNTER_CONTACT_ACCOUNT fingerprint=%s credits_remaining=%s searches_remaining=%s verifications_remaining=%s',
                hashlib.sha256(str(account.get('email') or '').lower().encode()).hexdigest()[:12],
                mailbox.remaining_requests(usage.get('credits')),mailbox.remaining_requests(usage.get('searches')),
                mailbox.remaining_requests(usage.get('verifications')))
            # Natural language is interpreted by Hunter's own company filters.
            # The original prompt is kept for inspection; geography is explicit.
            prompt=query+'\nCompany headquarters location: '+location if location else query
            response=(post or requests.post)('https://api.hunter.io/v2/discover',
                headers={'X-API-KEY':key},json={'query':prompt,'limit':limit},
                timeout=(2,30),allow_redirects=False)
            receipt['provider_http_status']=response.status_code
            if response.status_code==429:receipt['reason_codes']=['HUNTER_DISCOVER_QUOTA_EXHAUSTED']
            elif response.status_code in {401,403}:receipt['reason_codes']=['HUNTER_DISCOVER_ACCESS_REQUIRED']
            elif response.status_code!=200 or len(response.content)>200000:receipt['reason_codes']=['HUNTER_DISCOVER_UNAVAILABLE']
            else:
                body=response.json();data=body.get('data') if isinstance(body,dict) and not body.get('errors') else None
                if not isinstance(data,list):receipt['reason_codes']=['HUNTER_DISCOVER_UNCONFIRMED']
                else:
                    seen=set()
                    for row in data[:limit]:
                        if not isinstance(row,dict):continue
                        domain=str(row.get('domain') or '').strip().lower()
                        name=str(row.get('organization') or '').strip()[:300]
                        if (not re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}',domain)
                                or host('https://'+domain)!=domain or shared_host(domain)
                                or domain in seen or not name):continue
                        seen.add(domain)
                        receipt['companies'].append({'company':name,'title':name,'website':'https://'+domain,
                            'source_url':'https://'+domain,'url':'https://'+domain,'source':'Hunter Discover',
                            'location':location,'classification':'Candidate','contact_status':'Finding contact',
                            'provider_contact_research':True,'research_source':'Hunter Discover fallback',
                            'business_status':'Business match unconfirmed'})
                    receipt['filters']=(body.get('meta') or {}).get('filters') or {}
    except Exception as exc:
        receipt['diagnostic_error']=type(exc).__name__
        receipt['reason_codes']=['HUNTER_DISCOVER_UNAVAILABLE']
    finally:
        try:mailbox._release_account(account_key,token,receipt['reason_codes'])
        except Exception:receipt={'provider':'hunter','companies':[],'reason_codes':['HUNTER_CACHE_UNAVAILABLE']}
    return receipt


def contact_view(lead):
    from customer_dashboard import evidence_parts
    rows,enrichment,_=evidence_parts(lead)
    research=next((r.get('business_research') or {} for r in reversed(rows) if r.get('business_research')), {})
    assessment=enrichment.get('contact_assessment') or {}
    check=assessment.get('mailbox_validation') or {}
    reasons=list(dict.fromkeys((assessment.get('hunter_discovery') or {}).get('reason_codes',[])+check.get('reason_codes',[])))
    issue=('Hunter email credits are unavailable. Check your Hunter usage.' if any('QUOTA' in code for code in reasons) else
           'Hunter is already checking another contact. Please try again shortly.' if 'HUNTER_CHECK_IN_PROGRESS' in reasons else
           'Your Hunter connection needs attention.' if any(code in reasons for code in ['HUNTER_ACCOUNT_MISMATCH','HUNTER_ACCOUNT_EMAIL_REQUIRED','HUNTER_REAL_CREDENTIAL_REQUIRED','HUNTER_FREE_PLAN_REQUIRED','HUNTER_NOT_ENABLED']) else
           'Hunter could not verify this contact yet.' if reasons and 'HUNTER_NO_DOMAIN_CONTACTS' not in reasons else '')
    person=(enrichment.get('fields') or {}).get('decision_maker') or {}
    valid=bool(lead.contact_email and check.get('email')==lead.contact_email
               and check.get('mailbox_status')=='provider_verified')
    return {**research,'company':lead.company,'title':lead.company,'website':lead.source_url,
        'source_url':lead.source_url,'location':lead.location,'lead_id':lead.id,
        'contact_name':lead.contact_name or '', 'contact_role':person.get('title') if lead.contact_name else '',
        'contact_email':lead.contact_email if valid else '',
        'contact_type':'Decision-maker' if valid and lead.contact_name else 'Company inbox' if valid else '',
        'contact_issue':issue if not valid else '',
        'email_status':'Verified' if valid else 'Not verified',
        'email_verified_on':check.get('provider_verified_on') if valid else None,
        'contact_status':'Verified email' if valid else 'No verified email found',
        'classification':'Business found','provider_contact_research':True,
        'contact_check':{'mailbox_verified':valid,'named_contact':bool(valid and lead.contact_name)}}


def run_contact_research(campaign, *, save_contacts=True):
    from v1_orchestration import discovery_lock, _purpose_mailbox_allowed
    from outreach_automation import OutreachLead
    from workspace_security import OWNER, claim, scope
    from src.campaign_reporting import attribute_new_lead
    query=campaign['query'];location=search_location(query,campaign['territory'])
    checkpoint('discovering_businesses')
    receipt=discover_companies(query,location,campaign['target_count'])
    if receipt['reason_codes']:
        app.logger.warning('HUNTER_CONTACT_RESEARCH_FAILED reasons=%s account_http=%s provider_http=%s error_type=%s',
            receipt['reason_codes'],receipt.get('account_http_status'),receipt.get('provider_http_status'),receipt.get('diagnostic_error'))
        messages={'HUNTER_NOT_ENABLED':'Connect Hunter in Settings to find and verify business contacts.',
            'HUNTER_REAL_CREDENTIAL_REQUIRED':'Your Hunter API connection needs attention in Settings.',
            'HUNTER_FREE_QUOTA_UNAVAILABLE':'Hunter has no confirmed email lookup credits available. Check your Hunter usage.',
            'HUNTER_FREE_QUOTA_EXHAUSTED':'Hunter email lookup credits are used up. Company discovery is still available.',
            'HUNTER_DISCOVER_QUOTA_EXHAUSTED':'Your Hunter search allowance is used up. Check Hunter usage in Settings.',
            'HUNTER_DISCOVER_ACCESS_REQUIRED':'Hunter did not allow this search. Check your Hunter API connection and plan.'}
        return None,'contact_research',messages.get(receipt['reason_codes'][0],'Hunter could not complete the search. Please try again shortly.')
    rows=receipt['companies'];views=[dict(row) for row in rows];saved=[]
    checkpoint('business_results_ready',businesses=views,discovered=len(rows))
    for index,row in enumerate(rows):
        checkpoint('hunter_contact_lookup',businesses=views)
        context={'query':query,'offer':campaign.get('offer') or '', 'target_location':location,
            'provider_contact_research':True,'require_decision_maker':not allows_company_inbox(query)}
        row={**row,'contact_location':location,'query':query,'_campaign_context':context}
        with discovery_lock(row['company'],row['website']) as acquired:
            if not acquired:
                views[index]['contact_status']='Contact lookup already running';continue
            lead=(OutreachLead.query.filter_by(company=row['company'],source_url=row['website']).filter(scope(OutreachLead,'lead',OWNER)).first()
                  if save_contacts else None)
            # Research never changes a sent/active conversation or its recipient.
            if lead and (lead.gmail_message_id or lead.sent_at or lead.status not in {'needs_evidence','qualified','drafted'}):
                views[index]=contact_view(lead);saved.append(lead.id);continue
            # The list uses Hunter's company/domain and named-contact records
            # directly, just like Discover. This is provider provenance, never
            # fabricated proof that a company website published an address.
            from src.hunter_discovery import enrich_contact
            from src.contact_assessment import person_email_supported
            provider_source='https://hunter.io/domain-search?domain='+host(row['website'])
            enrichment={'company_name':row['company'],'identity_status':'provider_bound',
                'fields':{'website':{'value':row['website'],'source_url':provider_source,'validated':True}},
                'contact_assessment':{'company_status':'hunter_domain_association','reason_codes':[]},'validated':True}
            try:
                enrich_contact(enrichment,row['website'],required_person=context['require_decision_maker'],email_allowed=_purpose_mailbox_allowed,provider_people=True,research_only=True)
            except TimeoutError:
                raise
            except Exception as exc:
                # A broken contact/provider response must not erase the business
                # or prevent the next independent company's lookup.
                db.session.rollback()
                app.logger.warning('HUNTER_CONTACT_LOOKUP_FAILED type=%s',type(exc).__name__)
                enrichment['contact_assessment']={'hunter_discovery':{'reason_codes':['HUNTER_PROVIDER_UNAVAILABLE']}}
            assessment=enrichment['contact_assessment'];field=enrichment['fields'].get('email') or {}
            check=assessment.get('mailbox_validation') or {}
            email=(field.get('value') if field.get('validated') and check.get('email')==field.get('value')
                   and check.get('mailbox_status')=='provider_verified'
                   and (person_email_supported(assessment,field.get('value')) or
                        (not context['require_decision_maker'] and assessment.get('email_person_status')=='shared_inbox')) else '') or ''
            if not email:
                reasons=list(dict.fromkeys((assessment.get('hunter_discovery') or {}).get('reason_codes',[])+check.get('reason_codes',[])))
                app.logger.warning('HUNTER_CONTACT_LOOKUP_HELD reasons=%s',reasons)
            contact_name=assessment.get('person_name') if email else ''
            if not lead:
                lead=OutreachLead(company=row['company'],source_url=row['website'],location=location,
                    status='needs_evidence',score=0,verification='CANDIDATE')
                if save_contacts:
                    db.session.add(lead);db.session.flush();claim('lead',lead.id,OWNER);attribute_new_lead(lead)
            if lead.contact_email!=email:lead.subject='';lead.body=''
            lead.contact_email=email;lead.contact_name=contact_name or ''
            lead.location=row.get('location') or location;lead.status='needs_evidence'
            lead.evidence_json=json.dumps([{'source':'hunter_contact_research','url':provider_source,
                'business_research':{k:row[k] for k in ('research_source','business_status','supporting_urls') if k in row},
                'enrichment':enrichment,'contact_assessment':assessment,'observed_at':check.get('checked_at')},
                {'source':'campaign_context','context':context}])
            if save_contacts:
                db.session.commit();saved.append(lead.id)
            views[index]=contact_view(lead)
        checkpoint('hunter_contact_checked',businesses=views,discovered=len(rows),contacts_verified=sum(v.get('email_status')=='Verified' for v in views))
    verified=sum(v.get('email_status')=='Verified' for v in views)
    return {'ok':True,'contact_research':True,'campaign':{**campaign,'territory':location},
        'discovery':{'results':views,'verified':verified,'count':len(views),'target_count':campaign['target_count'],
                     'target_met':len(views)>=campaign['target_count'],'source':receipt.get('provider','hunter'),
                     'provider_filters':receipt.get('filters') or {}},
        'outreach':{'lead_ids':saved,'saved':len(saved),'qualified':0,'drafted':0,'sent':0},
        'business_progress':views},None,None
