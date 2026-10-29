"""Read-only, workspace-scoped index of verified decision-maker emails."""
import re
from datetime import datetime, timezone
from src.mailbox_verification import current, timestamp, lead_status
from src.contact_assessment import is_shared_email, person_email_supported

ROLE=re.compile(r'\b(?:owner|founder|president|ceo|chief executive|manager|director|partner|principal|chief|head)\b',re.I)


def verified_contacts():
    from outreach_automation import OutreachLead
    from background_research import ResearchJob
    from customer_dashboard import unpack,evidence_parts
    from workspace_security import scope
    from src.owned_research import _published_direct_phone
    contacts={}
    earliest=datetime.min.replace(tzinfo=timezone.utc)

    def add(email,name,role,company,phone,source,receipt):
        email=str(email or '').strip().lower()
        if not email or is_shared_email(email):return
        at=timestamp(receipt.get('checked_at')) or earliest
        old=contacts.get(email)
        if old and at < old['_at']:return
        contacts[email]={'email':email,'name':name or '', 'role':role or '', 'company':company or '',
            'phone':phone or '', 'source_url':source or '', 'provider':receipt.get('provider') or '',
            'checked_at':receipt.get('checked_at'),'verified_on':receipt.get('provider_verified_on') or receipt.get('checked_at'),
            '_at':at,'_receipt':receipt}

    def research_row(row):
        if not isinstance(row,dict):return
        for person in row.get('decision_makers') or []:
            email=person.get('email') or ''
            proof=person.get('mailbox_validation') or {}
            if not proof and email and email==row.get('contact_email'):
                projection=row.get('mailbox_verification') or {}
                proof={'email':email,'mailbox_status':'provider_verified' if projection.get('verified') is True else 'unconfirmed',
                    'checked_at':projection.get('checked_at'),'provider_verified_on':projection.get('verified_on'),
                    'provider':projection.get('provider')}
            add(email,person.get('name'),person.get('role'),row.get('company') or row.get('title'),
                person.get('direct_phone'),person.get('source_url'),proof)
        # Some older provider results have a named primary contact, no people array.
        if row.get('contact_name') and row.get('contact_email'):
            projection=row.get('mailbox_verification') or {}
            proof={'email':row['contact_email'],'mailbox_status':'provider_verified' if projection.get('verified') is True else 'unconfirmed',
                'checked_at':projection.get('checked_at'),'provider_verified_on':projection.get('verified_on'),'provider':projection.get('provider')}
            add(row['contact_email'],row['contact_name'],row.get('contact_role'),row.get('company') or row.get('title'),
                row.get('direct_phone') if row.get('direct_phone_verified') else '',row.get('email_source_url'),proof)

    for lead in OutreachLead.query.filter(OutreachLead.status!='archived',scope(OutreachLead,'lead')).yield_per(100):
        rows,enrichment,_=evidence_parts(lead)
        assessment=enrichment.get('contact_assessment') or {}
        status=lead_status(lead)
        person=(enrichment.get('fields') or {}).get('decision_maker') or {}
        candidates=enrichment.get('decision_maker_candidates') or []
        matched=next((p for p in candidates if p.get('email')==lead.contact_email),{})
        named=person_email_supported(assessment,lead.contact_email)
        add(lead.contact_email,(person.get('value') or lead.contact_name) if named else '',
            person.get('title') if named else '',lead.company,_published_direct_phone(matched) if named else '',
            person.get('source_url'),status['receipt'])
        for record in rows:
            if not isinstance(record,dict):continue
            for p in record.get('research_contacts') or []:
                add(p.get('email'),p.get('name'),p.get('role'),lead.company,p.get('direct_phone'),
                    p.get('source_url'),p.get('mailbox_validation') or {})
    for job in ResearchJob.query.filter(ResearchJob.status=='completed',scope(ResearchJob,'research')).yield_per(50):
        result=unpack(job.result_json)
        for row in (result.get('discovery') or {}).get('results') or result.get('results') or []:research_row(row)
    result=[]
    for row in contacts.values():
        if len(row['name'].split())<2 or not ROLE.search(row['role']) or not current(row['_receipt'],row['email']):continue
        result.append({k:v for k,v in row.items() if not k.startswith('_')})
    return sorted(result,key=lambda r:r['checked_at'] or '',reverse=True)
