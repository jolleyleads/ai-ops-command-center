import hashlib
import json
import math
import os
import re
from datetime import datetime, timedelta

from app import app, db


class ResearchDocument(db.Model):
    __tablename__ = "research_document"
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.Text, nullable=False, unique=True)
    title = db.Column(db.Text, default="")
    source = db.Column(db.String(160), default="")
    entity_key = db.Column(db.String(64), index=True, default="")
    content = db.Column(db.Text, default="")
    metadata_json = db.Column(db.Text, default="{}")
    content_hash = db.Column(db.String(64), index=True, default="")
    first_seen = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class ResearchChunk(db.Model):
    __tablename__ = "research_chunk"
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("research_document.id"), nullable=False, index=True)
    chunk_index = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)
    terms_json = db.Column(db.Text, default="[]")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ResearchEntity(db.Model):
    __tablename__ = "research_entity"
    id = db.Column(db.Integer, primary_key=True)
    entity_key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.Text, nullable=False)
    entity_type = db.Column(db.String(80), default="unknown")
    location = db.Column(db.Text, default="")
    facts_json = db.Column(db.Text, default="{}")
    evidence_urls_json = db.Column(db.Text, default="[]")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def init_rag_tables():
    with app.app_context():
        db.create_all()


def _terms(text):
    return sorted(set(re.findall(r"[a-z0-9][a-z0-9+.#'-]{1,}", str(text or "").lower())))


def _entity_key(item):
    name=str(item.get("company") or item.get("business") or item.get("title") or "").strip().lower()
    loc=str(item.get("location") or "").strip().lower()
    return hashlib.sha256((name+"|"+loc).encode()).hexdigest()[:64] if name else ""


def _chunks(text, size=1800, overlap=250):
    text=re.sub(r"\s+"," ",str(text or "")).strip()
    if not text: return []
    out=[]; pos=0
    while pos < len(text):
        out.append(text[pos:pos+size]); pos += max(1,size-overlap)
    return out[:40]


def remember_evidence(items):
    """Persist source-backed discovery. No model-generated facts are stored as evidence."""
    init_rag_tables()
    saved=0
    with app.app_context():
        for item in items or []:
            url=str(item.get("url") or "").strip()[:4000]
            if not url: continue
            title=str(item.get("title") or "")[:2000]
            content=str(item.get("page_text") or item.get("subtitle") or "")[:50000]
            if not content: continue
            digest=hashlib.sha256(content.encode("utf-8","ignore")).hexdigest()
            doc=ResearchDocument.query.filter_by(url=url).first()
            changed=not doc or doc.content_hash != digest
            if not doc:
                doc=ResearchDocument(url=url); db.session.add(doc); db.session.flush()
            doc.title=title; doc.source=str(item.get("source") or "")[:160]
            doc.entity_key=_entity_key(item); doc.content=content; doc.content_hash=digest
            doc.last_seen=datetime.utcnow(); doc.metadata_json=json.dumps({k:v for k,v in item.items() if k not in ("page_text",)},default=str)[:20000]
            if changed:
                ResearchChunk.query.filter_by(document_id=doc.id).delete()
                for i,text in enumerate(_chunks(content)):
                    db.session.add(ResearchChunk(document_id=doc.id,chunk_index=i,text=text,terms_json=json.dumps(_terms(text))))
            saved += 1
        db.session.commit()
    return saved


def retrieve_context(query, location="", limit=8, max_age_days=90):
    """Lightweight persistent RAG retrieval using lexical relevance; vector provider can replace scorer later."""
    init_rag_tables(); q=set(_terms(query+" "+location)); scored=[]
    if not q: return []
    cutoff=datetime.utcnow()-timedelta(days=max_age_days)
    with app.app_context():
        chunks=(ResearchChunk.query.join(ResearchDocument).filter(ResearchDocument.last_seen>=cutoff).order_by(ResearchDocument.last_seen.desc()).limit(600).all())
        for c in chunks:
            terms=set(json.loads(c.terms_json or "[]")); overlap=len(q & terms)
            if not overlap: continue
            score=overlap/math.sqrt(max(1,len(terms)))
            d=ResearchDocument.query.get(c.document_id)
            scored.append((score,{"title":d.title,"url":d.url,"source":d.source,"text":c.text[:2400],"last_seen":d.last_seen.isoformat()}))
    scored.sort(key=lambda x:x[0],reverse=True)
    out=[]; seen=set()
    for _,x in scored:
        if x["url"] in seen: continue
        seen.add(x["url"]); out.append(x)
        if len(out)>=limit: break
    return out


def evidence_score(item, query=""):
    """Deterministic evidence quality, not a truth oracle. Source evidence remains visible to the LLM."""
    score=0.0
    if item.get("url"): score += .20
    if item.get("page_text"): score += .35
    if item.get("title"): score += .10
    hay=(str(item.get("title") or "")+" "+str(item.get("subtitle") or "")+" "+str(item.get("page_text") or "")).lower()
    q=_terms(query)
    if q: score += min(.25, .25*len(set(q)&set(_terms(hay)))/max(1,len(set(q))))
    if any(x in str(item.get("url") or "").lower() for x in (".gov/","government","permits","careers","jobs")): score += .10
    return round(min(1.0,score),3)


def annotate_evidence(items, query=""):
    for x in items or []:
        x["evidence_score"]=evidence_score(x,query)
    return items
