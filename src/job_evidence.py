"""Deterministic, source-bound current-job checks shared by search and campaigns."""
import hashlib
import html
import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, parse_qsl
from src.company_identity import identity_proof, location_matches, contact_context_matches, name_key, visible_page_text, email_on_domain, STATES

VERSION = "job-page-v1"
MAX_CHECK_AGE = timedelta(hours=1)
MAX_POSTING_AGE_DAYS = 90
ATS_HOSTS = {"greenhouse.io", "lever.co", "myworkdayjobs.com", "ashbyhq.com", "smartrecruiters.com", "icims.com", "workable.com", "bamboohr.com", "successfactors.com"}
CLOSED = re.compile(r"\b(?:no longer accepting (?:applications|candidates|resumes)|no longer available|(?:job|position|role|posting|vacancy|applications?) (?:is |are |has been |have been |has |have )?(?:closed|filled|expired|removed)|(?:this )?(?:job|position|role) (?:is )?not (?:available|found)|applications? (?:are )?closed|position filled)\b", re.I)
APPLY = re.compile(r"^(?:apply(?: now| here| today| for (?:this )?(?:job|position|role)| to (?:this )?(?:job|position|role))?|submit (?:an? )?application|start (?:an? |your )?application)$", re.I)


def is_hiring_query(query):
    q=str(query or "")
    if re.search(r"\b(?:hiring|hire|jobs?|careers?|recruiting|seeking|vacanc(?:y|ies)|open (?:roles?|positions?)|openings?)\b",q,re.I):return True
    # “Looking for” is hiring intent only when its object is a person/role,
    # not when someone asks us to find companies or automation services.
    return bool(re.search(r"\blooking\s+for\s+(?:(?:an?|the|experienced|senior|junior|ai|software|automation|electrical|mechanical|sales|support|licensed|master)\s+){0,6}(?:engineers?|developers?|technicians?|electricians?|plumbers?|assistants?|managers?|specialists?|analysts?|nurses?|staff|employees?)\b",q,re.I))


def alternative_claim_allowed(query,channels):
    if " or " not in str(query).lower():return False
    allowed=set()
    if re.search(r"\b(?:reviews?|unanswered|callbacks?|missed calls?|slow responses?)\b",str(query),re.I):allowed.add("response_complaints")
    if re.search(r"\b(?:permits?|inspections?|licenses?|licensed|licensing)\b",str(query),re.I):allowed.add("permit_license")
    if re.search(r"\b(?:projects?|contracts?|bids?|awarded|expanding|expansion)\b",str(query),re.I):allowed.add("projects")
    return bool(allowed.intersection(channels or []))


def requested_role_terms(query):
    q=str(query or "").lower()
    after=re.search(r"\b(?:hiring|hire|seeking|recruiting|looking for)\s+(.*)",q)
    if after:
        role=after.group(1)
    else:
        after=re.search(r"\b(?:jobs?|careers?|openings?|positions?|roles?)\s+(?:for|as)\s+(.*)",q)
        if after:role=after.group(1)
        else:
            before=re.search(r"^(.*?)\b(?:jobs?|careers?|openings?|positions?|roles?)\b",q)
            role=before.group(1) if before else ""
            role=re.sub(r"^.*?\b(?:with|that\s+(?:have|offer))\s+","",role)
    role=re.split(r"\b(?:in|near|around|with|that|or|include|exclude|rank|enrich(?:ing)?|using|give|provide|email|phone)\b|[.;]",role,maxsplit=1)[0]
    stop={"find","show","list","me","a","an","and","the","for","current","currently","active","actively","job","jobs","role","roles","position","positions","opening","openings","open","now","today","remote","remotely","hybrid","companies","company","businesses","business","firms","firm"}
    return [x for x in re.findall(r"[a-z0-9]+",role) if (len(x)>=3 or x in {"ai","ml","hr","it","qa","rn"}) and x not in stop and not x.isdigit()][:10]


def requested_location(query, location=""):
    if str(location or "").strip():return re.sub(r"\bhrva\b","Hampton Roads, VA",str(location).strip(),flags=re.I)
    match=re.search(r"\b(?:in|near|around)\s+(.+?)(?=\b(?:or|with|that|who|include|exclude|hiring|currently|remote)\b|[.;]|$)",str(query or ""),re.I)
    return re.sub(r"\bhrva\b","Hampton Roads, VA",match.group(1).strip(" ,"),flags=re.I) if match else ""


def role_matches(title, terms):
    value=str(title or "").casefold()
    if value.strip() in {"careers","jobs","join our team","current opportunities","job opportunities","open positions","employment","home","apply"}:return False
    value=re.sub(r"\bartificial intelligence\b","ai",value)
    value=re.sub(r"\bml\b","machine learning",value)
    terms=["ai" if t=="artificial" and "intelligence" in terms else t for t in terms]
    terms=[t for t in terms if t!="intelligence" or "artificial" not in terms]
    terms=[part for term in terms for part in (["machine","learning"] if term=="ml" else [term])]
    for term in terms:
        stem=term[:-1] if len(term)>4 and term.endswith("s") and not term.endswith(("ss","is")) else term
        if not re.search(r"\b"+re.escape(stem)+r"(?:s|es)?\b",value):return False
    return bool(str(title or "").strip())


def _stamp(value, expiry=False):
    if not isinstance(value,str) or not value.strip():return None
    try:
        stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
        if not stamp.tzinfo:stamp=stamp.replace(tzinfo=timezone.utc)
        if expiry and re.fullmatch(r"\d{4}-\d{2}-\d{2}",value):stamp+=timedelta(days=1)
        return stamp.astimezone(timezone.utc)
    except ValueError:return None


class _ApplyControls(HTMLParser):
    def __init__(self):
        super().__init__();self.stack=[];self.controls=[];self.email_controls=[];self.visible_parts=[];self.hidden=0;self.elements=[];self.form_actions=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        own_block="disabled" in attrs or "hidden" in attrs or attrs.get("aria-hidden","").lower()=="true" or attrs.get("aria-disabled","").lower()=="true" or bool(re.search(r"display\s*:\s*none|visibility\s*:\s*hidden",attrs.get("style",""),re.I))
        inherited=any(blocked for _,blocked in self.elements)
        if tag not in {"input","br","hr","img","meta","link","source","area","base","wbr"}:self.elements.append((tag,own_block or inherited))
        if tag in {"script","style"}:self.hidden+=1
        if tag=="form":self.form_actions.append(attrs.get("action", ""))
        if tag in {"a","button"}:
            blocked=own_block or inherited
            href=attrs.get("href","") if tag=="a" else attrs.get("formaction") or (self.form_actions[-1] if self.form_actions else "")
            if tag=="a" and (not href or href.startswith(("#","javascript:"))):blocked=True
            self.stack.append([tag,blocked,[],href])
        if tag=="input" and attrs.get("type","").lower() in {"submit","button"} and not (own_block or inherited):
            if APPLY.fullmatch(attrs.get("value","").strip()):self.controls.append({"label":attrs["value"],"url":attrs.get("formaction") or (self.form_actions[-1] if self.form_actions else "")})
    def handle_data(self,data):
        if not self.hidden:
            if not any(blocked for _,blocked in self.elements):self.visible_parts.append(data)
            for item in self.stack:item[2].append(data)
    def handle_endtag(self,tag):
        if tag=="form" and self.form_actions:self.form_actions.pop()
        for i in range(len(self.elements)-1,-1,-1):
            if self.elements[i][0]==tag:
                del self.elements[i:];break
        if tag in {"script","style"}:self.hidden=max(0,self.hidden-1)
        if self.stack and self.stack[-1][0]==tag:
            _,blocked,parts,href=self.stack.pop();label=" ".join(" ".join(parts).split())
            if not blocked and APPLY.fullmatch(label):self.controls.append({"label":label,"url":href})
            if not blocked and label and href.lower().startswith('mailto:'):
                self.email_controls.append({'label':label,'url':href})


def job_page_metadata(raw, source_url):
    """Extract only page-authored JobPosting records and enabled application controls."""
    records=[]
    for script in re.findall(r'''(?is)<script\b[^>]*type=["']application/ld\+json["'][^>]*>(.*?)</script>''',raw):
        try:stack=[json.loads(html.unescape(script))]
        except (ValueError,TypeError,RecursionError):continue
        count=0
        while stack and count<1000:
            count+=1;node=stack.pop()
            if isinstance(node,list):stack.extend(node)
            elif isinstance(node,dict):
                types=node.get("@type");types=[types] if isinstance(types,str) else types
                if isinstance(types,list) and any(isinstance(t,str) and t.rstrip("/").rsplit("/",1)[-1]=="JobPosting" for t in types):
                    records.append({k:node.get(k) for k in ("title","description","url","identifier","datePosted","validThrough","hiringOrganization","jobLocation","jobLocationType","applicantLocationRequirements")})
                stack.extend(v for v in node.values() if isinstance(v,(dict,list)))
    main=re.search(r"(?is)<main\b[^>]*>(.*?)</main>",raw)
    detail=main.group(1) if main else raw
    detail=re.sub(r"(?is)<(footer|nav|aside)\b.*?>.*?</\1>"," ",detail)
    parser=_ApplyControls()
    try:parser.feed(detail)
    except (ValueError,RecursionError):pass
    # Page-authored links are discovery hints only. The destination must pass the
    # complete live posting validator; a careers index never proves an opening.
    links=[]
    link_markup=re.sub(r'(?is)<(script|style|template)\b[^>]*>.*?</\1>',' ',detail)
    for anchor in re.findall(r"(?is)<a\b[^>]*>.*?</a>",link_markup):
        href=re.search(r"""(?is)href=["']([^"']+)["']""",anchor)
        if not href:continue
        target=urljoin(source_url,html.unescape(href.group(1)))
        label=visible_page_text(anchor)
        if _same_job_url(target,source_url) or re.search(r'(?i)\.(?:png|jpe?g|svg|gif|ico|css|js|pdf)(?:[?#]|$)',target):continue
        if urlparse(target).scheme in {'https','http'} and re.search(r'(?i)job|career|position|opening|requisition|vacanc|employment',target+' '+label):
            links.append({'url':target,'label':label})
    for record in records:
        if isinstance(record.get('url'),str):links.append({'url':urljoin(source_url,record['url']),'label':str(record.get('title') or '')})
    return {"source_application_text":" ".join(" ".join(parser.visible_parts).split())[:30000],"source_email_application_controls":parser.email_controls[:30],"source_job_links":list({x['url']:x for x in links}.values())[:80],"source_job_postings":records[:40],"source_apply_controls":[{**c,"url":urljoin(source_url,c["url"]) if c["url"] else ""} for c in parser.controls[:30]],"job_detail_text":visible_page_text(detail)[:30000]}


def _addresses(record):
    values=record.get("jobLocation") or [];values=values if isinstance(values,list) else [values]
    out=[]
    for place in values:
        address=place.get("address") if isinstance(place,dict) else None
        if isinstance(address,dict):
            out.append(" ".join(str(address.get(k) or "") for k in ("addressLocality","addressRegion","addressCountry")))
    return out


def _same_job_url(first,second):
    def key(value):
        parsed=urlparse(value)
        if parsed.scheme not in {"http","https"}:return None
        args=sorted((k,v) for k,v in parse_qsl(parsed.query,keep_blank_values=True) if not k.lower().startswith("utm_") and k.lower() not in {"gclid","fbclid","gh_src"})
        return ((parsed.hostname or "").lower().removeprefix("www."),parsed.path.rstrip("/"),args)
    try:return key(first) is not None and key(first)==key(second)
    except (ValueError,TypeError):return False


def _ats(url):
    host=(urlparse(url).hostname or "").lower()
    return any(host==h or host.endswith("."+h) for h in ATS_HOSTS)


def _job_application_controls(row,url,record=None):
    """Require the enabled application target to identify this specific posting."""
    parsed=urlparse(url)
    identifiers=[v for k,v in parse_qsl(parsed.query) if k.lower() in {"jobid","job_id","jid","gh_jid","requisitionid","reqid"}]
    parts=[p for p in parsed.path.split("/") if p]
    if parts and parts[-1].lower() not in {"jobs","job","careers","career","positions","apply","index.html"}:identifiers.append(parts[-1])
    # Employer pages and their ATS often use different IDs. Only page-authored
    # identifiers for this posting may bridge them; never a model-proposed ID.
    identifier=(record or {}).get('identifier')
    if isinstance(identifier,dict):identifier=identifier.get('value')
    if isinstance(identifier,(str,int)):identifiers.append(str(identifier))
    labelled=re.findall(r'(?i)\b(?:req(?:uisition)?\s*(?:id|number|#)|job\s*(?:id|number|#))\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{2,40})',str(row.get('job_detail_text') or ''))
    if len(set(labelled))==1:
        identifiers.append(labelled[0])
        year_number=re.fullmatch(r'(?:19|20)\d{2}-(\d{4,})',labelled[0])
        if year_number:identifiers.append(year_number.group(1))
    accepted=[]
    for control in row.get("source_apply_controls") or []:
        if not isinstance(control,dict):continue
        target=control.get("url")
        if not isinstance(target,str) or not target.startswith(("https://","http://")):continue
        dest=urlparse(target)
        if dest.hostname!=parsed.hostname and not _ats(target):continue
        # Job links are not application links. The target must carry this job's ID.
        if _same_job_url(target,url):continue
        target_values=[p for p in dest.path.split("/") if p]+[v for _,v in parse_qsl(dest.query)]
        if any(identifier in target_values for identifier in identifiers):accepted.append(control)
    # Dedicated employer job pages may explicitly accept applications by email.
    # Require a labeled application section, application/resume instructions and
    # a single address on the employer's own domain. General contact/footer mail
    # and third-party addresses are not application evidence.
    detail=str(row.get('source_application_text') or '')
    section=re.search(r'(?i)\bhow to apply\s*:\s*(.{0,800}?)(?=\b(?:benefits|requirements|duties|about us|contact us)\s*:|$)',detail)
    if section:
        instructions=section.group(1)
        emails=set(re.findall(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',instructions))
        if len(emails)==1 and re.search(r'(?i)\b(?:email|send|submit)\b',instructions) and re.search(r'(?i)\b(?:application|resume|résumé|cv)\b',instructions):
            email=next(iter(emails)).lower()
            enabled_emails={str(c.get('url') or '').removeprefix('mailto:').split('?',1)[0].lower() for c in row.get('source_email_application_controls') or [] if isinstance(c,dict)}
            if email in enabled_emails and email_on_domain(email,'https://'+(urlparse(url).hostname or '').removeprefix('www.')):
                accepted.append({'label':'Published email application instructions','url':'mailto:'+email,'kind':'email_application'})
    return accepted


def check_job_evidence(row,query,location="",company="",now=None):
    now=now or datetime.now(timezone.utc)
    target=requested_location(query,location);terms=requested_role_terms(query)
    requested_places=list(dict.fromkeys(p for p in (target,requested_location(query)) if p))
    url=str(row.get("resolved_url") or row.get("url") or "")
    checked=_stamp(row.get("job_page_fetched_at") or row.get("observed_at"))
    base={"version":VERSION,"ok":False,"source_url":url,"requested_role_terms":terms,"requested_location":target,"reasons":[]}
    if row.get("rag_retrieved") or not row.get("directly_fetched") or row.get("http_status")!=200:
        return {**base,"reasons":["live_job_page_required"]}
    if not checked or checked>now+timedelta(minutes=5) or now-checked>MAX_CHECK_AGE:
        return {**base,"reasons":["job_status_check_stale_or_missing"]}
    detail=str(row.get("job_detail_text") or "")
    records=row.get("source_job_postings") or []
    if not isinstance(records,list):records=[]
    fallback=not records
    if fallback:
        title=row.get("source_heading") or row.get("source_title") or ""
        records=[{"title":title,"description":detail,"datePosted":None}]
    failures=[]
    for record in records:
        if not isinstance(record,dict):continue
        title=str(record.get("title") or "");description=visible_page_text(str(record.get("description") or ""))
        reasons=[]
        if not role_matches(title,terms):reasons.append("requested_role_not_in_job_title")
        org=record.get("hiringOrganization") or {};org=org if isinstance(org,dict) else {}
        if company:
            if org.get("name") and name_key(org["name"])!=name_key(company):reasons.append("job_employer_mismatch")
            if not identity_proof(company,row) and not (_ats(url) and name_key(org.get("name"))==name_key(company)):
                reasons.append("primary_employer_job_source_required")
        record_url=record.get("url")
        if record_url and (not isinstance(record_url,str) or not _same_job_url(urljoin(url,record_url),url)):
            reasons.append("job_detail_page_required")
        exact_records=[r for r in records if isinstance(r,dict) and isinstance(r.get("url"),str) and _same_job_url(urljoin(url,r["url"]),url)]
        if (not record_url and len(records)>1) or len(exact_records)>1:reasons.append("ambiguous_job_record_on_listing")
        locations=_addresses(record)
        if fallback:
            # Require a labeled job address; a company name or HQ mention is not a worksite.
            state_pattern="|".join(re.escape(s) for s in sorted(STATES,key=len,reverse=True))+"|"+"|".join(STATES.values())
            locations=re.findall(r"(?i)\b(?:job location|work location|location|worksite)\s*[:\-]\s*([a-z .'-]{2,60}?,\s*(?:"+state_pattern+r"))\b",detail)
            if any(not any(location_matches(address,place) for address in locations) for place in requested_places):reasons.append("requested_city_not_in_job_location")
        elif any(not any(location_matches(address,place) for address in locations) for place in requested_places):
            reasons.append("requested_city_not_in_job_location")
        if re.search(r"\bremote(?:ly)?\b",str(query),re.I) and record.get("jobLocationType")!="TELECOMMUTE" and not (fallback and re.search(r"\b(?:fully remote|100% remote|remote position|remote role)\b",detail,re.I)):
            reasons.append("requested_remote_status_unproven")
        if CLOSED.search(description) or CLOSED.search(detail):reasons.append("job_closed_or_unavailable")
        expiry=_stamp(record.get("validThrough"),expiry=True)
        publication=_stamp(record.get("datePosted"))
        if record.get("validThrough") is not None and expiry is None:reasons.append("job_expiry_date_invalid")
        if expiry and expiry<=now:reasons.append("job_expired")
        if record.get("datePosted") is not None and publication is None:reasons.append("job_posting_date_invalid")
        if publication and publication>now+timedelta(minutes=5):reasons.append("job_posting_date_in_future")
        if publication and now-publication>timedelta(days=MAX_POSTING_AGE_DAYS):reasons.append("job_posting_older_than_90_days")
        controls=_job_application_controls(row,url,record)
        if not controls:reasons.append("enabled_application_control_not_observed")
        # Metadata cannot contradict the visible page's job title or city.
        if not fallback and (not role_matches(str(row.get("source_heading") or row.get("source_title") or ""),terms or re.findall(r"[a-z0-9]+",title.lower())) or not description or any(not contact_context_matches(detail,str(row.get("source_heading") or title),place) for place in requested_places)):
            reasons.append("job_metadata_not_supported_by_visible_page")
        if not reasons:
            digest=hashlib.sha256((detail+json.dumps({"record":record,"application_controls":controls,"source_url":url},sort_keys=True,default=str)).encode()).hexdigest()
            return {**base,"ok":True,"reasons":[],"company":company,"job_title":title,"job_locations":locations or [target],"checked_at":checked.isoformat(),"remote_status":record.get("jobLocationType")=="TELECOMMUTE" or bool(fallback and re.search(r"\b(?:fully remote|100% remote|remote position|remote role)\b",detail,re.I)),"date_posted":record.get("datePosted"),"valid_through":record.get("validThrough"),"open_status":"enabled_application_observed","content_sha256":digest,"freshness_note":"Live application control observed; publication date unconfirmed." if not publication else "Dated posting and live application control observed."}
        failures.extend(reasons)
    return {**base,"reasons":list(dict.fromkeys(failures)) or ["job_details_unproven"]}


def receipt_is_current(receipt,query,location="",now=None,company=""):
    now=now or datetime.now(timezone.utc)
    if not isinstance(receipt,dict) or receipt.get("version")!=VERSION or receipt.get("ok") is not True:return False
    if company and name_key(receipt.get("company"))!=name_key(company):return False
    checked=_stamp(receipt.get("checked_at"));expiry=_stamp(receipt.get("valid_through"),expiry=True);posted=_stamp(receipt.get("date_posted"))
    if not checked or checked>now+timedelta(minutes=5) or now-checked>MAX_CHECK_AGE:return False
    if receipt.get("valid_through") and expiry is None or receipt.get("date_posted") and posted is None:return False
    if expiry and expiry<=now or posted and (now-posted>timedelta(days=MAX_POSTING_AGE_DAYS) or posted>now+timedelta(minutes=5)):return False
    if re.search(r"\bremote(?:ly)?\b",str(query),re.I) and receipt.get("remote_status") is not True:return False
    if not role_matches(receipt.get("job_title"),requested_role_terms(query)):return False
    target=requested_location(query,location)
    targets=list(dict.fromkeys(p for p in (target,requested_location(query)) if p))
    if any(not any(location_matches(v,p) for v in receipt.get("job_locations") or []) for p in targets):return False
    return bool(str(receipt.get("source_url") or "").startswith(("https://","http://")) and receipt.get("open_status")=="enabled_application_observed" and re.fullmatch(r"[a-f0-9]{64}",str(receipt.get("content_sha256") or "")))
