"""Read-only diagnostics for public employer job pages; no leads or sends."""
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.public_fetch import public_get
from src.company_identity import page_metadata, visible_page_text
from src.job_evidence import job_page_metadata, check_job_evidence
from src.contact_assessment import contact_sections, assess_people
from src.company_identity import identity_proof
from urllib.parse import urlparse


def diagnose(url, company, role, location):
    try:
        response = public_get(url, timeout=15, max_bytes=800000)
        if response.status_code != 200:
            return {"url":url, "http_status":response.status_code}
        stamp = datetime.now(timezone.utc).isoformat()
        row = {"url":url, "resolved_url":response.url, **page_metadata(response.text),
               **job_page_metadata(response.text, response.url),
               "page_text":visible_page_text(response.text)[:8000],
               "observed_at":stamp,"job_page_fetched_at":stamp,
               "directly_fetched":True,"http_status":200}
        website=f'{urlparse(response.url).scheme}://{urlparse(response.url).netloc}'
        people=[]
        if identity_proof(company,row,website):
            row['contact_sections']=contact_sections(response.text)
            people,_,_=assess_people([(row,response.url,row['page_text'])],company,website,location,role)
        return {**row, "check":check_job_evidence(row, role, location, company),
                "decision_maker_candidates":people,
                "identity_markup":re.findall(r'(?is)<meta\b[^>]*(?:site_name|application-name)[^>]*>|<a\b[^>]*(?:logo|brand)[^>]*>.*?</a>|<link\b[^>]*canonical[^>]*>',response.text)[:12],
                "application_markup":re.findall(r'(?is)<a\b[^>]*(?:mailto:|\.pdf)[^>]*>.*?</a>',response.text)[:10]}
    except Exception as exc:
        return {"url":url,"fetch_error":type(exc).__name__}


if __name__ == '__main__':
    for source in json.loads(Path(sys.argv[1]).read_text()):
        print('PUBLIC_JOB_DIAGNOSTIC '+json.dumps(diagnose(**source)), flush=True)
