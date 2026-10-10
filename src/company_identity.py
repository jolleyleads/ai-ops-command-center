"""Conservative company/contact identity checks shared by research and outreach.

Candidate labels and search snippets are discovery hints, never ownership proof.
Unknown or conflicting identities stay unresolved; aliases are not guessed.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from urllib.parse import urlparse
import tldextract

# Use the packaged Public Suffix List; production checks never fetch a list.
_extract_domain=tldextract.TLDExtract(suffix_list_urls=(),cache_dir=None,include_psl_private_domains=True)

SHARED_HOSTS = frozenset({
    "linkedin.com", "facebook.com", "google.com", "maps.google.com", "yelp.com",
    "indeed.com", "ziprecruiter.com", "glassdoor.com", "yellowpages.com",
    "career.com", "milwaukeejobs.com", "contactout.com", "pissedconsumer.com",
    "promallu.com", "remotive.com", "github.io", "wordpress.com", "wixsite.com",
})
LEGAL_SUFFIXES = {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co", "company"}
STATES = dict(pair.split(":") for pair in (
    "alabama:al|alaska:ak|arizona:az|arkansas:ar|california:ca|colorado:co|connecticut:ct|"
    "delaware:de|florida:fl|georgia:ga|hawaii:hi|idaho:id|illinois:il|indiana:in|iowa:ia|"
    "kansas:ks|kentucky:ky|louisiana:la|maine:me|maryland:md|massachusetts:ma|michigan:mi|"
    "minnesota:mn|mississippi:ms|missouri:mo|montana:mt|nebraska:ne|nevada:nv|new hampshire:nh|"
    "new jersey:nj|new mexico:nm|new york:ny|north carolina:nc|north dakota:nd|ohio:oh|"
    "oklahoma:ok|oregon:or|pennsylvania:pa|rhode island:ri|south carolina:sc|south dakota:sd|"
    "tennessee:tn|texas:tx|utah:ut|vermont:vt|virginia:va|washington:wa|west virginia:wv|"
    "wisconsin:wi|wyoming:wy|district of columbia:dc"
).split("|"))
HAMPTON_ROADS = ("norfolk", "portsmouth", "chesapeake", "virginia beach", "suffolk", "hampton", "newport news", "poquoson", "williamsburg", "york county", "isle of wight")


def host(url):
    try:
        parsed = urlparse(str(url or ""))
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return ""
        value=(parsed.hostname or "").lower().rstrip(".").removeprefix("www.")
        if "." not in value or value in {"co.uk","com.au","co.nz","co.jp","com.br","co.in","com","net","org","edu","gov"}:
            return ""
        return value
    except ValueError:
        return ""


def shared_host(value):
    return not value or any(value == h or value.endswith("." + h) for h in SHARED_HOSTS)


def registrable_host(value):
    extracted=_extract_domain(value)
    if extracted.suffix and extracted.domain:
        return extracted.domain+"."+extracted.suffix
    # Reserved names are used only by isolated regression fixtures.
    labels=value.split(".")
    if len(labels)>=2 and labels[-1] in {"example","test"}:
        return ".".join(labels[-2:])
    return ""


def owned_host(source, website):
    """Only the website host and its children; never accept a parent or sibling."""
    source_host, company_host = host(source), host(website)
    return bool(company_host and not shared_host(company_host) and
                (source_host == company_host or source_host.endswith("." + company_host)))


def email_on_domain(email, website):
    domain = str(email or "").lower().rsplit("@", 1)[-1].rstrip(".")
    company_host = host(website)
    return bool("@" in str(email) and company_host and not shared_host(company_host) and
                (domain == company_host or domain.endswith("." + company_host)))


def name_key(name):
    tokens = re.findall(r"[a-z0-9]+", str(name or "").casefold())
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return "".join(tokens)


def page_text(row):
    # Generated answer subtitles and candidate_name/title labels are not page content.
    return str(row.get("page_text") or row.get("text") or "")


def visible_page_text(raw):
    """Keep explicit mailto/tel values beside their visible source context."""
    raw=re.sub(r"(?is)<(script|style|svg|noscript).*?>.*?</\1>"," ",raw)
    raw=re.sub(r'''(?is)<a\b[^>]*href=["'](?:mailto|tel):([^"']+)["'][^>]*>''',
               lambda m:" "+html.unescape(m.group(1)).split("?",1)[0]+" ",raw)
    return re.sub(r"\s+"," ",html.unescape(re.sub(r"(?s)<[^>]+>"," ",raw))).strip()


def location_matches(text, location):
    def normalized(value):
        value = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
        value=re.sub(r"\bwashington\s+(?:dc|district of columbia)\b","district of columbia",value)
        for state, code in sorted(STATES.items(), key=lambda p: -len(p[0])):
            value = re.sub(r"\b" + re.escape(state) + r"\b", code, value)
        return " " + value + " "
    target, source = normalized(location), normalized(text)
    if not target.strip():
        return True
    if "hampton roads" in target:
        return " va " in source and any(normalized(city) in source for city in HAMPTON_ROADS)
    terms = target.split()
    return bool(terms and all(re.search(r"\b" + re.escape(t) + r"\b", source) for t in terms))


def page_metadata(raw):
    """Read exact organization identity from HTML, never from a model proposal."""
    organizations = []
    for script in re.findall(r'(?is)<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw):
        try:
            value = json.loads(html.unescape(script))
        except (ValueError, TypeError, RecursionError):
            continue
        stack = [value]
        visited=0
        while stack and visited<1000:
            visited+=1
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                types = node.get("@type", [])
                types = [types] if isinstance(types, str) else types
                if not isinstance(types,list):types=[]
                if any(isinstance(t,str) and t in {"Organization", "Corporation", "LocalBusiness", "ProfessionalService"} for t in types):
                    organizations.append({"name": node.get("name"), "url": node.get("url"), "address": node.get("address")})
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
    title = re.search(r"(?is)<title\b[^>]*>(.*?)</title>", raw)
    heading = re.search(r"(?is)<h1\b[^>]*>(.*?)</h1>", raw)
    clean = lambda s: html.unescape(re.sub(r"(?s)<[^>]+>", " ", s)).strip()
    return {"source_title": clean(title.group(1)) if title else "", "source_heading": clean(heading.group(1)) if heading else "", "source_organizations": organizations}


def identity_proof(company, row, website=""):
    url = row.get("resolved_url") or row.get("url") or row.get("source_url")
    source_host, key = host(url), name_key(company)
    if not key or shared_host(source_host) or row.get("rag_retrieved"):
        return None
    if website and not owned_host(url, website):
        return None
    content = page_text(row)
    if not content:
        return None
    # A complete brand on the hostname is useful primary-source identity evidence.
    # Do not treat a prefix such as IGT in igtsolutions as the same legal entity.
    company_root=registrable_host(source_host)
    if not company_root:return None
    domain_brand = re.sub(r"[^a-z0-9]", "", _extract_domain(company_root).domain if not company_root.endswith((".example",".test")) else company_root.split(".")[0])
    basis = ""
    if domain_brand == key:
        basis = "exact_brand_domain"
    for organization in row.get("source_organizations") or []:
        if isinstance(organization, dict) and name_key(organization.get("name")) == key and owned_host(url, organization.get("url")) and (website or host(organization.get("url"))==company_root):
            basis = "organization_named_on_owned_page"
            break
    # A previously established website still needs the company's name in the
    # fetched page title/heading. A passing mention in a directory is insufficient.
    label = str(row.get("source_title") or row.get("title") or "") + " " + str(row.get("source_heading") or "")
    tokens = re.findall(r"[a-z0-9]+", str(company or "").casefold())
    tokens = [t for t in tokens if t not in LEGAL_SUFFIXES]
    if not basis and website and len(key) > 4 and tokens:
        pattern = r"\b" + r"[\W_]+".join(re.escape(t) for t in tokens) + r"\b"
        if re.search(pattern, label.casefold()):
            basis = "named_page_on_explicit_website"
    if not basis:
        return None
    return {"company_name": str(company), "official_host": host(website) if website else company_root, "source_url": str(url), "basis": basis,
            "content_sha256": hashlib.sha256(content.encode()).hexdigest()}


def contact_context_matches(text, value, location):
    if not location:
        return True
    # A matching city in a different branch's section cannot bless this contact.
    for match in re.finditer(re.escape(value), text, re.I):
        window = text[max(0, match.start()-240):match.end()+240]
        if not location_matches(window, location):
            continue
        # Prefer the nearest explicit state/address, so adjacent branch entries
        # cannot share a city match simply because both fall within the window.
        states=r"(?i:\b(?:"+"|".join(re.escape(s) for s in sorted(STATES,key=len,reverse=True))+r")\b)|\b(?:"+"|".join(s.upper() for s in STATES.values())+r")\b"
        positions=list(re.finditer(states,window))
        offset=match.start()-max(0,match.start()-240)
        if positions:
            nearest=min(positions,key=lambda s:min(abs(s.start()-offset),abs(s.end()-offset)))
            previous_end=max((s.end() for s in positions if s.end()<=nearest.start()),default=0)
            address=window[max(previous_end,nearest.start()-60):nearest.end()]
            if not location_matches(address,location):
                continue
        return True
    return False
