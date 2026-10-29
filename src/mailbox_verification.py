"""One mailbox policy for research, UI and sending; identity stays separate."""
import json
import re
from datetime import datetime, timezone, timedelta

MAX_AGE = timedelta(days=7)


def timestamp(value):
    try:
        at=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return at.astimezone(timezone.utc) if at.tzinfo else at.replace(tzinfo=timezone.utc) if re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(value)) else None
    except (TypeError,ValueError):return None


def current(receipt,email,now=None):
    now=now or datetime.now(timezone.utc)
    if not isinstance(receipt,dict) or str(receipt.get('email') or '').casefold()!=str(email or '').casefold():return False
    if receipt.get('mailbox_status')!='provider_verified':return False
    checked=timestamp(receipt.get('checked_at'))
    verified=timestamp(receipt.get('provider_verified_on')) if receipt.get('provider_verified_on') else checked
    return bool(checked and verified and timedelta(0)<=now-checked<=MAX_AGE and timedelta(0)<=now-verified<=MAX_AGE)


def enabled():
    from src import hunter_mailbox,verifalia_mailbox
    return verifalia_mailbox.configured() or hunter_mailbox.enabled()


def verify_mailbox(email,*,research_only=False,provider=None):
    from src import hunter_mailbox,verifalia_mailbox
    if hunter_mailbox.processing_restriction_state(email)=='restricted':
        receipt=hunter_mailbox.base_receipt(email,'HUNTER_PROCESSING_RESTRICTED');receipt['mailbox_status']='provider_rejected';return receipt
    # Default callers keep the connected free provider; AutoHunt explicitly selects Hunter.
    if provider not in {None,'hunter'}:raise ValueError('Unsupported mailbox provider')
    receipt=verifalia_mailbox.verify(email) if provider is None and verifalia_mailbox.configured() else hunter_mailbox.verify_mailbox(email)
    if receipt.get('mailbox_status')=='provider_verified' and not current(receipt,email):
        receipt={**receipt,'mailbox_status':'unconfirmed','deliverability_status':'unconfirmed',
                 'reason_codes':['MAILBOX_VERIFICATION_EXPIRED']}
    return receipt


def lead_status(lead,record=None,now=None):
    """Read-only projection shared by every saved-contact screen."""
    email=lead.contact_email or '';receipts=[]
    try:rows=json.loads(lead.evidence_json or '[]')
    except (TypeError,ValueError):rows=[]
    rows=rows if isinstance(rows,list) else [rows]
    if record:rows=rows+[record]
    for row in rows:
        if not isinstance(row,dict):continue
        for part in (row,row.get('enrichment') or {}):
            receipt=(part.get('contact_assessment') or {}).get('mailbox_validation')
            if isinstance(receipt,dict):receipts.append(receipt)
    import outreach_automation as oa
    audit=oa.OperatorAuditEvent.query.filter_by(lead_id=lead.id,action='mailbox_verification').order_by(oa.OperatorAuditEvent.id.desc()).first() if lead.id else None
    if audit:
        try:receipts.append(json.loads(audit.result_json))
        except (TypeError,ValueError):pass
    receipts=[r for r in receipts if isinstance(r,dict) and str(r.get('email') or '').casefold()==email.casefold()]
    earliest=datetime.min.replace(tzinfo=timezone.utc)
    receipt=max(receipts,key=lambda r:timestamp(r.get('checked_at')) or earliest,default={})
    verified=bool(email and current(receipt,email,now))
    reasons=receipt.get('reason_codes') or []
    state='verified' if verified else 'expired' if receipt.get('mailbox_status')=='provider_verified' or any(r in {'MAILBOX_VERIFICATION_EXPIRED','HUNTER_RESULT_DATE_UNCONFIRMED_OR_STALE'} for r in reasons) else 'rejected' if receipt.get('mailbox_status')=='provider_rejected' else 'pending' if any('PENDING' in r or 'IN_PROGRESS' in r for r in reasons) else 'unconfirmed'
    label={'verified':'Verified','expired':'Verification expired','rejected':'Email rejected','pending':'Verification pending','unconfirmed':'Email found · Mailbox not verified'}[state] if email else 'No email found'
    return {'state':state,'label':label,'verified':verified,'provider':receipt.get('provider') or '',
            'checked_at':receipt.get('checked_at'),'verified_on':receipt.get('provider_verified_on'),
            'reason_codes':reasons,'receipt':receipt}


def apply_mailbox_check(enrichment):
    record=enrichment.get('fields',{}).get('email')
    if not record or record.get('validated') is not True:return enrichment
    receipt=verify_mailbox(record['value'])
    assessment=enrichment.setdefault('contact_assessment',{});assessment['mailbox_validation']=receipt
    record['mailbox_status']=receipt['mailbox_status'];record['deliverability_status']=receipt.get('deliverability_status','unconfirmed')
    if enabled() and not current(receipt,record['value']):
        record['validated']=False
        assessment.setdefault('reason_codes',[]).append('INDEPENDENT_MAILBOX_VERIFICATION_REQUIRED')
    return enrichment
