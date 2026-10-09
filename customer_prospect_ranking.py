"""Customer prospect discovery: source-backed complaints and hiring, fail closed."""
import re
from datetime import date
from urllib.parse import urlparse
from flask import jsonify, request
from app import app
from smart_search import _exa_search
from prospect_ranking import Evidence, Prospect, rank_prospects

COMPLAINT=re.compile(r"no one answers|never answers?|unanswered calls?|missed calls?|never called back|no call.?back|poor communication|unresponsive",re.I)
HIRING=re.compile(r"hiring|job opening|open position|careers|recruiting|apply now",re.I)
ROLE=re.compile(r"receptionist|front desk|customer service|scheduler|appointment|inside sales|call center|outreach",re.I)
DATE=re.compile(r"\\b20\\d{2}-\\d{2}-\\d{2}\\b")

def _evidence(rows,company,kind):
    found=[]
    for row in rows[:10]:
        if not isinstance(row,dict):
            continue
        url=str(row.get("url") or "")
        parsed=urlparse(url)
        if parsed.scheme!="https" or not parsed.hostname:
            continue
        title=str(row.get("title") or "")
        body=" ".join(str(row.get(k) or "") for k in ("title","subtitle","page_text"))
        # Do not attribute third-party complaints or jobs to an unrelated company.
        if company.casefold() not in body.casefold():
            continue
        if kind=="complaint":
            if not COMPLAINT.search(body) or not re.search(r"review|rating|customer|client",body,re.I):
                continue
        elif not (HIRING.search(body) and ROLE.search(body)):
            continue
        # A search observation is not a publication date. Require explicit dated evidence.
        dates=[]
        for match in DATE.findall(body):
            try:
                day=date.fromisoformat(match)
                if 0<=(date.today()-day).days<=(365 if kind=="complaint" else 60):
                    dates.append(day)
            except ValueError:
                pass
        if dates:
            found.append(Evidence(source_url=url,observed_at=max(dates),verified=True,description=title))
    return found

def discover(companies,territory):
    prospects=[]
    diagnostics=[]
    for company in companies:
        reviews=_exa_search('"' + company + '" reviews unanswered calls poor communication',territory)
        jobs=_exa_search('"' + company + '" hiring receptionist customer service scheduler',territory)
        complaints=_evidence(reviews.get("results") or [],company,"complaint")
        hiring=_evidence(jobs.get("results") or [],company,"hiring")
        prospects.append(Prospect(company=company,complaints=complaints,hiring=hiring))
        diagnostics.append({"company":company,"review_search_message":reviews.get("message") or "","hiring_search_message":jobs.get("message") or ""})
    return rank_prospects(prospects),diagnostics

@app.route("/api/demo/prospect-ranking",methods=["POST"])
def demo_prospect_ranking():
    data=request.get_json(silent=True) or {}
    companies=data.get("companies")
    territory=str(data.get("territory") or "").strip()[:150]
    if not territory or not isinstance(companies,list) or not 1<=len(companies)<=5 or any(not isinstance(x,str) or not x.strip() or len(x)>150 for x in companies):
        return jsonify({"ok":False,"error":"Provide territory and 1-5 company names"}),400
    ranked,diagnostics=discover([x.strip() for x in companies],territory)
    return jsonify({"ok":True,"results":ranked,"diagnostics":diagnostics,"note":"Search results are conservative source-linked leads, not independently authenticated Google reviews or job listings. No outreach sent."})
