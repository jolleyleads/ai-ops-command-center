"""Customer-selected sending: contact safety is separate from prospect ranking."""
import json
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime,timezone,timedelta
import re
from app import db
from workspace_security import OWNER,owns
from src.company_identity import owned_host,name_key

_active=ContextVar('manual_selected_send',default=None)
POLICY='selected-contact-v1'


def contact_readiness(lead):
    import outreach_automation as oa
    reasons=[]
    if not owns('lead',lead.id,OWNER):reasons.append('CONTACT_OWNERSHIP_REQUIRED')
    address=oa.normalize_email(lead.contact_email)
    if not oa._recipient_matches_source_domain(lead):reasons.append('RECIPIENT_COMPANY_DOMAIN_MISMATCH')
    if not oa._recipient_mailbox_allowed(address):reasons.append('RECIPIENT_PURPOSE_MAILBOX_BLOCKED')
    if lead.status in {'archived','unsubscribed','opted_out','completed_no_reply'} or oa._is_suppressed(address):reasons.append('CONTACT_STOPPED_OR_SUPPRESSED')
    validated,_,evidence=oa._server_qualification_inputs(lead)
    now=datetime.now(timezone.utc)
    def fresh(value):
        try:return timedelta(0)<=now-datetime.fromisoformat(str(value).replace('Z','+00:00'))<=timedelta(hours=1)
        except (TypeError,ValueError):return False
    source=validated.get('email_source_url')
    require_person=any((x.get('context') or {}).get('require_decision_maker') is True for x in evidence if x.get('source')=='campaign_context')
    person_found=False
    proof_found=False;mailbox_found=False
    for row in evidence:
        if oa.normalize_email(row.get('email'))!=address:continue
        from src.contact_assessment import person_email_supported
        if person_email_supported(row.get('contact_assessment') or {},address):person_found=True
        proof=row.get('company_identity') or {}
        if (source and owned_host(source,lead.source_url) and owned_host(row.get('url') or '',lead.source_url)
            and name_key(proof.get('company_name'))==name_key(lead.company)
            and owned_host(proof.get('source_url') or '',lead.source_url)
            and re.fullmatch(r'[a-f0-9]{64}',str(proof.get('content_sha256') or '')) and fresh(row.get('observed_at'))):proof_found=True
        mailbox=(row.get('contact_assessment') or {}).get('mailbox_validation') or {}
        if mailbox.get('mailbox_status')=='provider_verified' and oa.normalize_email(mailbox.get('email'))==address and fresh(mailbox.get('checked_at')):mailbox_found=True
    if require_person and not person_found:reasons.append('NAMED_DECISION_MAKER_EMAIL_REQUIRED')
    if not proof_found:reasons.append('CURRENT_COMPANY_EMAIL_SOURCE_REQUIRED')
    if not mailbox_found:reasons.append('VERIFIED_MAILBOX_REQUIRED')
    return {'ok':not reasons,'reason_codes':reasons}


def _job_allows(lead,job_id):
    from campaign_jobs import CampaignExecutionJob
    job=db.session.get(CampaignExecutionJob,job_id)
    if not job or not owns('campaign',job_id,OWNER):return None
    data=json.loads(job.payload_json or '{}')
    options=[x.get('payload') or {} for x in data.get('items',[])] if data.get('_selected_bulk') else [data]
    for item in options:
        row=item.get('_selected_business') or {}
        if (item.get('_manual_selected_send')==POLICY and item.get('_selection_send_authorized') is True
            and item.get('_selected_workspace')==OWNER and name_key(row.get('company') or row.get('name') or row.get('title') or row.get('business_name') or row.get('candidate_name'))==name_key(lead.company)
            and owned_host(row.get('website') or row.get('source_url') or row.get('url') or '',lead.source_url)
            and (not item.get('_selected_lead_id') or item['_selected_lead_id']==lead.id)):
            return job
    return None


def permitted(lead,kind):
    import outreach_automation as oa
    if kind=='initial':
        grant=_active.get()
        if not grant or grant[:2]!=(lead.id,oa.normalize_email(lead.contact_email)):return False
        job=_job_allows(lead,grant[2])
        return bool(job and job.status=='running' and contact_readiness(lead)['ok'])
    if kind not in {'followup','automatic_reply','booking_confirmation','booking'}:return False
    if not owns('lead',lead.id,OWNER):return False
    # Only real initial-send history can extend the customer's workflow grant.
    initial=oa.OutreachSendAttempt.query.filter_by(lead_id=lead.id,kind='initial',status='sent',recipient=oa.normalize_email(lead.contact_email)).first()
    if not initial or not initial.message_id or not initial.thread_id:return False
    grant=oa.OperatorAuditEvent.query.filter_by(lead_id=lead.id,action='selected_contact_send_approved').order_by(oa.OperatorAuditEvent.id.desc()).first()
    if not grant:return False
    data=json.loads(grant.request_json or '{}')
    return bool(data.get('recipient')==oa.normalize_email(lead.contact_email) and _job_allows(lead,data.get('job_id')))


@contextmanager
def authorize(lead,job_id):
    import outreach_automation as oa
    job=_job_allows(lead,job_id)
    if not job or job.status!='running' or not contact_readiness(lead)['ok']:
        yield False;return
    oa._audit_actor(lead.id,'selected_contact_send_approved',{'job_id':job_id,'recipient':oa.normalize_email(lead.contact_email),'policy':POLICY},
        {'basis':'customer_selected_verified_contact','business_qualification_unchanged':True},'customer')
    db.session.commit()
    token=_active.set((lead.id,oa.normalize_email(lead.contact_email),job_id))
    try:yield True
    finally:_active.reset(token)


def prepare_contact(selected,existing,query,territory,offer):
    """Reuse a current verified address; otherwise verify the selected source email."""
    import outreach_automation as oa
    from src.outreach_copy import initial_email
    from src.execution_deadline import checkpoint
    from workspace_security import claim
    from v1_orchestration import _public_contact_evidence,EMAIL_SCAN_RE
    from src.company_identity import current_contact_source
    from src.hunter_mailbox import verify_mailbox,enabled
    from src.enrichment import enrich_lead
    from src.hunter_discovery import enrich_contact
    from src.contact_assessment import person_email_supported
    from src.prospect_quality import POLICY as QUALITY_POLICY,request_spec
    if existing and (existing.gmail_message_id or existing.sent_at or oa.OutreachSendAttempt.query.filter_by(lead_id=existing.id).first()):return existing
    lead=existing
    if lead and (lead.status in {'archived','unsubscribed','opted_out','completed_no_reply'} or oa._is_suppressed(lead.contact_email)):return lead
    required_person=bool(re.search(r'(?i)\b(?:decision[ -]?makers?|named contacts?|owners?|founders?|ceos?)\b',query))
    prior_assessment=oa._server_qualification_inputs(lead)[0].get('contact_assessment') or {} if lead else {}
    person_ready=bool(lead and person_email_supported(prior_assessment,oa.normalize_email(lead.contact_email)))
    try:
        checked=datetime.fromisoformat(str((prior_assessment.get('hunter_discovery') or {}).get('checked_at') or '').replace('Z','+00:00'))
        hunter_checked=timedelta(0)<=datetime.now(timezone.utc)-checked<=timedelta(hours=1)
    except (ValueError,TypeError):hunter_checked=False
    if lead and contact_readiness(lead)['ok'] and (not required_person or person_ready) and (person_ready or not enabled() or hunter_checked):
        if not lead.subject or not lead.body:
            draft=initial_email(lead,json.loads(lead.evidence_json or '[]'));lead.subject=draft['subject'];lead.body=draft['body'];db.session.commit()
        return lead
    company=selected['company'];website=selected['website']
    preferred=oa.normalize_email((lead.contact_email if lead else '') or selected.get('contact_email') or selected.get('email') or next((x.get('email') for x in selected.get('contacts') or [] if isinstance(x,dict) and x.get('email')),''))
    # Directory/support addresses are not this company's contact. Discover a
    # real address on its own current source instead of pinning an unrelated one.
    if preferred and not oa.email_on_domain(preferred,website):preferred=''
    checkpoint('verifying_selected_email_source')
    fetched=_public_contact_evidence({**selected,'location':territory,'target_location':territory,'query':query})
    rows=fetched[0] if isinstance(fetched,tuple) else fetched
    rows=[x for x in rows or [] if current_contact_source(x) and owned_host(x.get('url') or '',website)
          and name_key((x.get('company_identity') or {}).get('company_name'))==name_key(company)]
    choices=[]
    for row in rows:
        for email in EMAIL_SCAN_RE.findall(str(row.get('page_text') or row.get('text') or '')):
            email=oa.normalize_email(email)
            if (not preferred or email==preferred) and oa._recipient_mailbox_allowed(email) and oa.email_on_domain(email,website) and email not in [x[0] for x in choices]:choices.append((email,row))
    checkpoint('hunter_contact_lookup')
    enrichment=enrich_lead({'company':company,'website':website,'target_location':territory,'query':query+' '+offer},rows,email_allowed=oa._recipient_mailbox_allowed)
    provider_people=selected.get('provider_contact_research') is True or bool(lead and any((r.get('context') or {}).get('provider_contact_research') is True
        for r in oa._server_qualification_inputs(lead)[2]))
    options={'provider_people':True} if provider_people else {}
    allowed=(lambda email:oa._recipient_mailbox_allowed(email) and (not preferred or email==preferred)) if provider_people else oa._recipient_mailbox_allowed
    enrich_contact(enrichment,website,required_person=required_person,email_allowed=allowed,**options)
    assessment=enrichment.get('contact_assessment') or {}
    candidate=(enrichment.get('fields') or {}).get('email') or {}
    named=person_email_supported(assessment,candidate.get('value'))
    contact=None;mailbox=assessment.get('mailbox_validation') or {}
    # Hunter may associate a source-supported buyer with an address not printed
    # on the page. Its durable association and independent mailbox check must pass.
    if named and candidate.get('validated'):
        row=next((x for x in rows if x.get('url')==candidate.get('source_url')),None)
        email=oa.normalize_email(candidate.get('value'))
        if row and oa.email_on_domain(email,website):
            mailbox=verify_mailbox(email)
            if mailbox.get('mailbox_status')=='provider_verified' and oa.normalize_email(mailbox.get('email'))==email:contact=(email,row)
    if not contact and not required_person:
        for email,row in choices[:3]:
            checkpoint('verifying_selected_mailbox')
            mailbox=verify_mailbox(email)
            if mailbox.get('mailbox_status')=='provider_verified' and oa.normalize_email(mailbox.get('email'))==email:
                contact=(email,row);break
    if contact:
        assessment['mailbox_validation']=mailbox
        if not person_email_supported(assessment,contact[0]):
            # A general inbox never inherits another person's name or association.
            assessment={**assessment,'email_person_status':'unconfirmed','person_email':'','person_name':''}
    if not lead:
        lead=oa.OutreachLead(company=company,source_url=website,location=territory,status='needs_evidence',score=0,evidence_json='[]')
        db.session.add(lead);db.session.flush();claim('lead',lead.id,OWNER)
    evidence=oa._server_qualification_inputs(lead)[2]+[{**x,'source':'outreach_primary_copy'} for x in rows]
    if contact:
        email,row=contact;lead.contact_email=email
        lead.contact_name=assessment.get('person_name') or ''
        evidence.append({'email':email,'url':row['url'],'observed_at':row.get('observed_at'),
            'identity_version':'company-domain-v1','company_identity':row['company_identity'],
            'contact_assessment':assessment,'source':'hunter_verified_contact' if assessment.get('email_person_status')=='hunter_verified_person' else 'verified_public_contact'})
    else:
        lead.contact_email=preferred
        lead.last_error='No email sent: '+(', '.join((mailbox.get('reason_codes') or [])+(assessment.get('hunter_discovery') or {}).get('reason_codes',[])) or ('A named decision-maker email is still needed.' if required_person else 'The selected email could not be verified on a current company source.'))
    evidence.append({'source':'campaign_context','context':{'query':query,'target_location':territory,'offer':offer,'prospect_policy':QUALITY_POLICY,'require_decision_maker':required_person,'request_spec':request_spec(query,territory,offer)}})
    lead.evidence_json=json.dumps(evidence)
    # Publish the owned record before suppression checks use an independent
    # database session (also important for SQLite's shared connection).
    db.session.commit()
    if contact and contact_readiness(lead)['ok']:
        draft=initial_email(lead,evidence);lead.subject=draft['subject'];lead.body=draft['body'];lead.last_error=''
    db.session.commit();return lead
