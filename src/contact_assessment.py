"""Separate person, responsibility, locality and email-association evidence."""
import re
from html.parser import HTMLParser
from src.company_identity import contact_context_matches, email_on_domain, name_key

NAME=r"[A-Z][a-z]*(?:['’-][A-Z]?[a-z]+)?(?:\s+[A-Z][a-z]*(?:['’-][A-Z]?[a-z]+)?){1,2}"
ROLES=r"(?:chief executive officer|chief technology officer|human resources manager|operations manager|project manager|office manager|sales manager|customer service manager|customer success manager|business development manager|engineering manager|hiring manager|recruiting manager|general manager|(?:director|head) of (?:engineering|operations|recruiting|human resources|sales|customer service|customer success)|owner|founder|president|CEO|CTO|recruiter|director|principal|partner)"
# Names keep case; titles may use any case.
PAIR=re.compile(r"\b("+NAME+r")\s*[,|:\-]\s*((?i:"+ROLES+r"))\b")
HIRING=re.compile(r"\b(?:hiring|jobs?|recruiting|careers?|openings?)\b",re.I)
HIRING_RESPONSIBILITY_SYNONYMS=re.compile(r"\b(?:recruitment|staffing|talent)\b",re.I)
EMAIL=re.compile(r"(?i)(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])")
SHARED={"info","sales","support","contact","hello","office","admin","jobs","careers","hr","hiring","recruiting","recruitment","team","owner","service","billing","press","marketing","noreply","no-reply"}


def is_shared_email(email):
    local=str(email).split('@',1)[0].lower()
    return any(local==x or local.startswith(x+'.') or local.startswith(x+'-') for x in SHARED)


def email_name_consistent(email,name):
    # Compare an actually published address; never generate one from a name.
    local=re.sub(r"[^a-z]","",str(email).split('@',1)[0].split('+',1)[0].casefold())
    parts=[re.sub(r"[^a-z]","",p.casefold()) for p in name.split()]
    if len(parts)<2:return False
    first,last=parts[0],parts[-1]
    return local in {first,last,first+last,first[0]+last,first+last[0]} and len(local)>=3


def current_email_context(text,email):
    for match in re.finditer(re.escape(email),text,re.I):
        prefix=text[max(0,match.start()-180):match.start()]
        if not re.search(r"(?i)\b(?:former|previous|retired)\b",prefix):return True
    return False


def contact_sections(raw):
    """Keep explicit HTML contact cards apart and exclude navigation/footer text."""
    class Parser(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=True);self.stack=[];self.blocks=[];self.ignore=0
        def handle_starttag(self,tag,attrs):
            if tag in {'script','style','footer','nav','header','noscript','svg'}:self.ignore+=1
            if tag in {'div','section','article','li','p'}:self.stack.append([tag,[]])
            if not self.ignore and tag=='a':
                href=dict(attrs).get('href','')
                if href.lower().startswith('mailto:'):self.handle_data(href[7:].split('?',1)[0])
        def handle_data(self,data):
            if not self.ignore:
                for _,parts in self.stack:parts.append(data)
        def handle_endtag(self,tag):
            if tag in {'div','section','article','li','p'} and self.stack and self.stack[-1][0]==tag:
                _,parts=self.stack.pop();text=' '.join(' '.join(parts).split())
                if PAIR.search(text) and len(text)<=4000:self.blocks.append(text)
            if tag in {'script','style','footer','nav','header','noscript','svg'}:self.ignore=max(0,self.ignore-1)
    parser=Parser();parser.feed(str(raw or '')[:500000])
    return list(dict.fromkeys(parser.blocks))[:100]


def responsibility_matches(title,context,query,location="",company=""):
    if not query:return False
    q=query.casefold();t=title.casefold()
    hiring=bool(HIRING.search(q))
    if hiring and re.search(r'hiring|recruit|human resources',t):return 'hiring_function_title'
    if re.search(r'engineering|automation|technical|software|\bai\b',q) and re.search(r'engineering|technology|\bcto\b',t):return 'technical_function_title'
    if not hiring and re.search(r'outreach|follow.up|call.?back|operations|automation',q) and re.search(r'operations|customer service|customer success|sales|office manager|owner|founder|president|ceo|chief executive',t):return 'business_function_title'
    # Explicit responsibility statements can support other relevant titles.
    statement=re.search(r'(?i)\b(?:responsible for|oversees|leads)\s+([^.;]{3,120})',context)
    terms=set(re.findall(r'[a-z]{4,}',q))-{'companies','company','business','businesses','currently','looking','find','with','that','role','need'}
    terms-=set(re.findall(r'[a-z]{4,}',(location+' '+company).casefold()))
    if hiring and statement and not (HIRING.search(statement.group(1)) or HIRING_RESPONSIBILITY_SYNONYMS.search(statement.group(1))):return ''
    return 'explicit_responsibility_statement' if statement and terms.intersection(re.findall(r'[a-z]{4,}',statement.group(1).casefold())) else ''


def assess_people(rows,company,website,location,query):
    candidates=[]
    for row,url,text in rows:
        # Card content must actually be present in the directly fetched page.
        normalized=' '.join(text.split())
        cards=[s for s in row.get('contact_sections',[]) if isinstance(s,str) and ' '.join(s.split()) in normalized]
        cards=cards or [text]
        for card in cards:
            matches=list(PAIR.finditer(card))
            for i,match in enumerate(matches):
                start=max(matches[i-1].end() if i else 0,match.start()-180)
                stop=min(matches[i+1].start() if i+1<len(matches) else len(card),match.end()+180)
                context=card[start:stop];name,title=match.groups()
                if name_key(name) in name_key(company) or name.split()[0].casefold() in {"former","previous","retired","testimonial","customer","vendor","team","contact","meet"}:continue
                if re.search(r'(?i)\b(?:former|previous|retired|ex[- ]|testimonial|customer|vendor|alumni)\b',card[max(start,match.start()-65):match.start()]):continue
                local=bool(location and contact_context_matches(context,name,location))
                relevant=responsibility_matches(title,card[match.end():stop],query,location,company)
                # Only one person in this card may own an email. No address-format guesses.
                emails=list(dict.fromkeys(e.lower() for e in EMAIL.findall(card) if email_on_domain(e,website) and not is_shared_email(e) and email_name_consistent(e,name))) if len(matches)==1 else []
                if location:emails=[e for e in emails if contact_context_matches(card,e,location)]
                candidates.append({'name':name,'title':title,'company':company,'location':location,'company_status':'source_confirmed','location_status':'source_context_matched' if local else 'unconfirmed','responsibility_status':'source_supported' if relevant else 'unconfirmed','responsibility_basis':relevant or '','email':emails[0] if len(emails)==1 and local else '', 'email_person_status':'same_source_card' if len(emails)==1 and local else 'unconfirmed','email_association_basis':'published_address_name_consistent_in_one_person_card' if len(emails)==1 and local else '','source_url':url,'observed_at':row.get('observed_at'),'evidence_excerpt':context,'status':'source_supported' if local and relevant else 'needs_more_evidence'})
    unique={}
    for c in candidates:
        key=(name_key(c['name']),c['title'].casefold(),c['location'],c['email'],c['status'])
        unique.setdefault(key,c)
    candidates=list(unique.values())
    relevant=[c for c in candidates if c['status']=='source_supported']
    pool=relevant if query else [c for c in candidates if c['location_status']=='source_context_matched']
    # Several equally supported people do not establish a unique decision-maker.
    identities={name_key(c['name']) for c in pool}
    chosen=None
    if len(identities)==1:
        emails={c['email'] for c in pool if c['email']}
        if len(emails)<=1:chosen=max(pool,key=lambda c:bool(c['email']))
    return candidates,chosen,'source_supported' if chosen and query else ('role_relevance_unconfirmed' if chosen else ('ambiguous' if pool else 'unconfirmed'))
