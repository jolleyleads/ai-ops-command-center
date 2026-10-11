import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import pytest
from src.company_identity import page_metadata, visible_page_text
from src.job_evidence import job_page_metadata


@pytest.fixture
def live_job_page():
    def build(company="Acme",title="AI Automation Engineer",city="Norfolk",state="VA",url=None,*,now=None,changes=None,body=None,apply_html=None):
        now=now or datetime.now(timezone.utc)
        url=url or "https://"+re.sub(r"[^a-z0-9]","",company.lower())+".example/jobs/1"
        root="https://"+(urlparse(url).hostname or "acme.example")
        job={"@type":"JobPosting","title":title,"description":f"{company} is hiring {title}. Apply now.","url":url,"datePosted":(now-timedelta(days=7)).isoformat(),"validThrough":(now+timedelta(days=30)).isoformat(),"hiringOrganization":{"@type":"Organization","name":company,"sameAs":root},"jobLocation":{"@type":"Place","address":{"addressLocality":city,"addressRegion":state,"addressCountry":"US"}}}
        job.update(changes or {})
        detail=body if body is not None else f"<h1>{title}</h1><p>{company}</p><p>Job location: {city}, {state}</p><p>{job['description']}</p>"
        apply_html=apply_html if apply_html is not None else '<a href="/apply/1">Apply now</a>'
        raw=f'<html><head><title>{title} | {company}</title><script type="application/ld+json">{json.dumps(job)}</script></head><body><main>{detail}{apply_html}</main></body></html>'
        return {"url":url,"resolved_url":url,"candidate_name":company,"verification_research":True,"title":title,"page_text":visible_page_text(raw),"directly_fetched":True,"http_status":200,"observed_at":now.isoformat(),"job_page_fetched_at":now.isoformat(),**page_metadata(raw),**job_page_metadata(raw,url)}
    return build
