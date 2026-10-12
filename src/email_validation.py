"""Bounded DNS mail-routing checks; never claim mailbox delivery from DNS."""
import re,time
from datetime import datetime,timezone
import dns.resolver
import dns.exception


def check_email_domain(email, resolver=None, lifetime=2):
    email=str(email or '').strip()
    result={'email':email,'checked_at':datetime.now(timezone.utc).isoformat(),'method':'dns_mail_routing','domain_status':'unconfirmed','mailbox_status':'unconfirmed','deliverability_status':'unconfirmed','reason_codes':[]}
    if len(email)>254 or not re.fullmatch(r'[A-Za-z0-9_%+.-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',email):
        result.update(domain_status='invalid',reason_codes=['INVALID_EMAIL_SYNTAX']);return result
    local,domain=email.rsplit('@',1)
    if len(local)>64 or local.startswith('.') or local.endswith('.') or '..' in local or any(not label or len(label)>63 or label.startswith('-') or label.endswith('-') for label in domain.split('.')):
        result.update(domain_status='invalid',reason_codes=['INVALID_EMAIL_SYNTAX']);return result
    resolve=resolver or dns.resolver.resolve
    deadline=time.monotonic()+max(0.1,min(float(lifetime),3))
    def ask(kind):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise dns.exception.Timeout()
        return resolve(domain,kind,lifetime=remaining,search=False)
    try:
        try:
            records=list(ask('MX'))
        except dns.resolver.NoAnswer:records=[]
        if records:
            exchanges=[str(r.exchange).lower() for r in records]
            if '.' in exchanges:
                if len(records)==1 and int(records[0].preference)==0:
                    result.update(domain_status='does_not_accept_mail',reason_codes=['NULL_MX'])
                else:result['reason_codes']=['CONFLICTING_MX_RECORDS']
            else:result.update(domain_status='mx_published',mx_hosts=exchanges)
            return result
        for kind in ('A','AAAA'):
            try:
                if list(ask(kind)):
                    result.update(domain_status='implicit_mail_route',reason_codes=['NO_EXPLICIT_MX']);return result
            except dns.resolver.NoAnswer:pass
        result.update(domain_status='does_not_accept_mail',reason_codes=['NO_MAIL_ROUTE'])
    except dns.resolver.NXDOMAIN:
        result.update(domain_status='does_not_exist',reason_codes=['DOMAIN_NOT_FOUND'])
    except (dns.exception.DNSException,OSError,ValueError):result['reason_codes']=['DNS_CHECK_INCONCLUSIVE']
    return result


def apply_email_domain_check(enrichment, resolver=None):
    record=enrichment.get('fields',{}).get('email')
    if not record:return enrichment
    receipt=check_email_domain(record.get('value'),resolver=resolver)
    record['mail_validation']=receipt
    enrichment.setdefault('contact_assessment',{})['email_validation']=receipt
    # Hard negative routing evidence cannot flow as a validated email.
    if receipt['domain_status'] in {'invalid','does_not_exist','does_not_accept_mail'}:
        record['validated']=False
        enrichment['contact_assessment']['reason_codes'].append('EMAIL_MAIL_ROUTE_REJECTED')
    from src.hunter_mailbox import apply_mailbox_check
    return apply_mailbox_check(enrichment)
