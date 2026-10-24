"""Stable references to persisted research businesses; never client-supplied leads."""
import hashlib
from src.company_identity import name_key, host


def business_key(row):
    name=row.get('company') or row.get('name') or row.get('business_name') or row.get('candidate_name') or row.get('title') or ''
    url=row.get('website') or row.get('source_url') or row.get('url') or ''
    return hashlib.sha256((name_key(name)+'|'+host(url)).encode()).hexdigest()


def reference(kind,job_id,row):
    return {'kind':kind,'job_id':job_id,'key':business_key(row)}


def annotate(payload,kind,job_id):
    progress=payload.get('progress') or {}
    result=payload.get('result') or {}
    discovery=result.get('discovery') or result
    groups=[progress.get('candidates') or [],progress.get('businesses') or [],discovery.get('results') or []]
    for rows in groups:
        for row in rows:
            if isinstance(row,dict):
                row['selection']=({'kind':'lead','lead_id':row['lead_id']}
                    if row.get('provider_contact_research') is True and type(row.get('lead_id')) is int
                    else reference(kind,job_id,row))
    return payload
