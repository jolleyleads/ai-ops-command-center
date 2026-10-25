"""Bounded, cached Hunter discovery. Provider results never establish company identity.

Names/roles must independently occur on the company's current primary pages.
Hunter supplies the address association; the mailbox verifier supplies deliverability.
"""
import hashlib
import json
import math
import os
import re
import time
import uuid
from datetime import datetime, timezone
import requests
from flask import has_app_context
from sqlalchemy import update
from sqlalchemy.orm import Session
from app import db
from src import hunter_mailbox as mailbox
from src.company_identity import host, email_on_domain, name_key, owned_host, shared_host
from src.contact_assessment import is_shared_email


def discover_contacts(website, get=None, *, decision_makers=False):
    domain=host(website)
    receipt={"provider":"hunter","domain":domain,"contacts":[],"reason_codes":[],"checked_at":datetime.now(timezone.utc).isoformat()}
    def fail(reason):
        receipt["contacts"]=[]
        receipt["reason_codes"]=[reason]
        return receipt
    if not domain or shared_host(domain):return fail("HUNTER_COMPANY_DOMAIN_REQUIRED")
    if not mailbox.enabled():return fail("HUNTER_NOT_ENABLED")
    key=os.getenv("HUNTER_API_KEY","").strip();expected=os.getenv("HUNTER_ACCOUNT_EMAIL","").strip().lower()
    if not key or key=="test-api-key":return fail("HUNTER_REAL_CREDENTIAL_REQUIRED")
    if not expected:return fail("HUNTER_ACCOUNT_EMAIL_REQUIRED")
    if not has_app_context():return fail("HUNTER_CACHE_UNAVAILABLE")
    cache_key=hashlib.sha256(("hunter-discovery:"+hashlib.sha256(key.encode()).hexdigest()+":"+expected+":"+domain+(':decision-makers' if decision_makers else '')).encode()).hexdigest()
    receipt["cache_key"]=cache_key
    now=time.time();token=uuid.uuid4().hex
    try:
        with Session(db.engine) as session:
            row=session.get(mailbox.HunterMailboxCheck,cache_key)
            if row and row.expires_at>now:
                if row.state=="complete":return {**json.loads(row.receipt_json),"cache_hit":True}
                return fail("HUNTER_CHECK_IN_PROGRESS")
            if row:
                claimed=session.execute(update(mailbox.HunterMailboxCheck).where(mailbox.HunterMailboxCheck.key==cache_key,mailbox.HunterMailboxCheck.expires_at<=now).values(state="reserved",lease_token=token,expires_at=now+120,receipt_json="{}")).rowcount
                if not claimed:return fail("HUNTER_CHECK_IN_PROGRESS")
            else:session.add(mailbox.HunterMailboxCheck(key=cache_key,state="reserved",lease_token=token,expires_at=now+120))
            session.commit()
    except Exception:return fail("HUNTER_CACHE_UNAVAILABLE")
    account_key,blocked=mailbox._claim_account(expected,token,now)
    try:
        get=get or requests.get
        if blocked:fail(blocked)
        else:
            account,code=mailbox._request("account",key,{},get)
            if not isinstance(account,dict):fail("HUNTER_ACCOUNT_CHECK_FAILED")
            elif str(account.get("email") or "").lower()!=expected:fail("HUNTER_ACCOUNT_MISMATCH")
            elif str(account.get("plan_name") or "").lower()!="free":fail("HUNTER_FREE_PLAN_REQUIRED")
            else:
                buckets=account.get("requests") or {}
                bucket=buckets.get("credits") or buckets.get("searches") or {}
                remaining=mailbox.remaining_requests(bucket)
                if isinstance(remaining,bool) or not isinstance(remaining,(int,float)) or not math.isfinite(remaining) or remaining<1:fail("HUNTER_FREE_QUOTA_UNAVAILABLE")
                else:
                    params={"domain":domain,"limit":10}
                    if decision_makers:params.update(type='personal',decision_maker='true',required_field='full_name,position',verification_status='valid')
                    data,code=mailbox._request("domain-search",key,params,get)
                    if code==429:fail("HUNTER_FREE_QUOTA_EXHAUSTED")
                    elif code!=200 or not isinstance(data,dict) or host("https://"+str(data.get("domain") or ""))!=domain:fail("HUNTER_DISCOVERY_UNCONFIRMED")
                    else:
                        for raw in (data.get("emails") or [])[:10]:
                            if not isinstance(raw,dict):continue
                            email=str(raw.get("value") or "").strip().lower()
                            if not re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}",email) or not email_on_domain(email,website):continue
                            sources=[str(s.get("uri") or "") for s in raw.get("sources") or [] if isinstance(s,dict) and owned_host(s.get("uri"),website)]
                            receipt["contacts"].append({"email":email,"name":" ".join(str(raw.get(k) or "").strip() for k in ("first_name","last_name")).strip(),"title":str(raw.get("position") or "")[:200],"type":raw.get("type"),"source_urls":sources[:5]})
                        if not receipt["contacts"]:fail("HUNTER_NO_DOMAIN_CONTACTS")
    except Exception:fail("HUNTER_PROVIDER_UNAVAILABLE")
    finally:
        if not blocked:
            try:mailbox._release_account(account_key,token,receipt["reason_codes"])
            except Exception:fail("HUNTER_CACHE_UNAVAILABLE")
    try:
        with Session(db.engine) as session:
            updated=session.execute(update(mailbox.HunterMailboxCheck).where(mailbox.HunterMailboxCheck.key==cache_key,mailbox.HunterMailboxCheck.state=="reserved",mailbox.HunterMailboxCheck.lease_token==token).values(state="complete",expires_at=time.time()+(3600 if receipt["contacts"] else 60),receipt_json=json.dumps(receipt))).rowcount
            session.commit()
            if updated!=1:return fail("HUNTER_RECEIPT_STORAGE_FAILED")
    except Exception:return fail("HUNTER_CACHE_UNAVAILABLE")
    return receipt


def enrich_contact(enrichment, website, *, required_person=False, email_allowed=None, provider_people=False, research_only=False):
    """Prefer a current source-supported person; retain shared inboxes as shared."""
    if enrichment.get('identity_status')!='source_bound' and not (provider_people and enrichment.get('identity_status')=='provider_bound'):return enrichment
    receipt=discover_contacts(website,decision_makers=True) if provider_people else discover_contacts(website)
    assessment=enrichment.setdefault("contact_assessment",{})
    assessment["hunter_discovery"]={k:v for k,v in receipt.items() if k!="contacts"}
    people=[p for p in enrichment.get("decision_maker_candidates") or [] if p.get("status")=="source_supported"]
    # Multiple relevant people remain ambiguous, even if only one has a Hunter address.
    names={name_key(p.get("name")) for p in people}
    options=[]
    for contact in receipt["contacts"]:
        email=contact["email"]
        if email_allowed and not email_allowed(email):continue
        person=next((p for p in people if name_key(p["name"])==name_key(contact["name"])),None) if len(names)==1 else None
        if person and contact["type"]=="personal" and not is_shared_email(email):options.append((person,contact))
    # Contact-list research can select a Hunter-associated person without
    # pretending the company's website published their name. Company identity
    # is still independently bound above; deliverability is checked below.
    if not options and provider_people:
        from src.contact_assessment import responsibility_matches
        for contact in receipt['contacts']:
            if (contact.get('type')!='personal' or is_shared_email(contact['email'])
                    or len(contact.get('name','').split())<2
                    or (email_allowed and not email_allowed(contact['email']))):continue
            basis=responsibility_matches(contact.get('title',''),'','business outreach follow-up automation')
            if not basis:continue
            person={'name':contact['name'],'title':contact['title'],
                    'source_url':enrichment['fields']['website']['source_url'],
                    'status':'provider_supported','responsibility_status':'provider_supported'}
            options.append((person,contact))
    if not options and not required_person:
        options=[(None,c) for c in receipt["contacts"] if c["type"]=="generic" and is_shared_email(c["email"]) and (not email_allowed or email_allowed(c["email"]))]
    # Prefer a named contact, otherwise keep a valid published email already found.
    if options and options[0][0] is None and enrichment.get("fields",{}).get("email",{}).get("validated"):return enrichment
    def candidates():
        nonlocal receipt
        yield from options[:3]
        # Fetch shared inboxes only after named contacts are unavailable or
        # fail mailbox verification. The personal-only query excludes them.
        if provider_people and not required_person:
            receipt=discover_contacts(website)
            assessment['hunter_discovery']={k:v for k,v in receipt.items() if k!='contacts'}
            shared=[c for c in receipt['contacts'] if c.get('type')=='generic'
                    and is_shared_email(c['email']) and (not email_allowed or email_allowed(c['email']))]
            for contact in shared[:3]:yield None,contact
    for person,contact in candidates():
        check=mailbox.verify_mailbox(contact['email'],research_only=True) if research_only else mailbox.verify_mailbox(contact['email'])
        if check.get("mailbox_status")!="provider_verified":
            assessment["mailbox_validation"]=check
            continue
        source=person["source_url"] if person else enrichment["fields"]["website"]["source_url"]
        enrichment["fields"]["email"]={"value":contact["email"],"source_url":source,"validated":True,"observation_status":"hunter_discovered","observed_at":receipt["checked_at"],"mailbox_status":"provider_verified","deliverability_status":check["deliverability_status"]}
        assessment.update(mailbox_validation=check,email_person_status="hunter_verified_person" if person else "shared_inbox",person_email=contact["email"] if person else "")
        if person:
            enrichment["fields"]["decision_maker"]={"value":person["name"],"title":person["title"],"source_url":source,"validated":True}
            assessment.update(decision_maker_status=person.get('status','source_supported'),person_name=person["name"],person_title=person['title'],hunter_association={"cache_key":receipt["cache_key"],"domain":receipt["domain"],"email":contact["email"],"name":person["name"]})
        enrichment["validated"]=True
        break
    return enrichment


def current_person_association(assessment,email):
    """A client-supplied flag cannot stand in for the durable provider receipt."""
    association=assessment.get("hunter_association") or {}
    if not has_app_context() or association.get("email")!=email or name_key(association.get("name"))!=name_key(assessment.get("person_name")):return False
    try:
        with Session(db.engine) as session:
            row=session.get(mailbox.HunterMailboxCheck,association.get("cache_key",""))
            if not row or row.state!="complete":return False
            receipt=json.loads(row.receipt_json)
            checked=datetime.fromisoformat(receipt["checked_at"])
            if not 0<=(datetime.now(timezone.utc)-checked).total_seconds()<=7*86400:return False
            if receipt.get("domain")!=association.get("domain"):return False
            return any(c.get("email")==email and c.get("type")=="personal" and name_key(c.get("name"))==name_key(association.get("name")) for c in receipt.get("contacts") or [])
    except Exception:return False
