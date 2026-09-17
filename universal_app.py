import os
import requests
from flask import jsonify, request
from app import app, db, AutomationEvent, search_remote_jobs

def _clean(value, limit=300): return str(value or "").strip()[:limit]
def _places_key(): return os.environ.get("GOOGLE_PLACES_API_KEY") or os.environ.get("GOOGLE_MAPS_API_KEY") or ""
def _search_businesses(query, location=""):
    api_key=_places_key()
    if not api_key:return {"configured":False,"source":"Google Places","message":"Google Places key is not configured.","results":[]}
    text_query=" ".join(part for part in [query,location] if part).strip()
    if not text_query:return {"configured":True,"source":"Google Places","message":"Enter a business search.","results":[]}
    response=requests.post("https://places.googleapis.com/v1/places:searchText",headers={"Content-Type":"application/json","X-Goog-Api-Key":api_key,"X-Goog-FieldMask":"places.id,places.displayName,places.formattedAddress,places.websiteUri,places.googleMapsUri,places.nationalPhoneNumber,places.rating,places.userRatingCount,places.businessStatus,places.types"},json={"textQuery":text_query,"maxResultCount":20},timeout=20)
    if not response.ok:return {"configured":True,"source":"Google Places","message":f"Google Places returned HTTP {response.status_code}.","results":[]}
    results=[]
    for place in response.json().get("places",[]):
        results.append({"type":"business","id":place.get("id") or "","title":((place.get("displayName") or {}).get("text") or "Unknown business"),"subtitle":place.get("formattedAddress") or "","phone":place.get("nationalPhoneNumber") or "","rating":place.get("rating"),"review_count":place.get("userRatingCount"),"status":place.get("businessStatus") or "","website":place.get("websiteUri") or "","url":place.get("googleMapsUri") or place.get("websiteUri") or "","source":"Google Places"})
    return {"configured":True,"source":"Google Places","message":"","results":results}
def _google_error_message(response):
    try:payload=response.json()
    except ValueError:return ""
    error=payload.get("error")
    if isinstance(error,dict):return _clean(error.get("message"),500)
    return ""
def _request_ip():
    forwarded=request.headers.get("X-Forwarded-For","")
    return (forwarded.split(",",1)[0].strip() if forwarded else request.remote_addr or "")
def _normalize_custom_search_results(payload):
    return [{"type":"public_record","title":i.get("title") or "Search result","subtitle":i.get("snippet") or "","url":i.get("link") or "","source":i.get("displayLink") or "Google Programmable Search"} for i in payload.get("items",[])]
def _normalize_web_search_results(payload):
    return [{"type":"public_record","title":i.get("title") or "Search result","subtitle":i.get("snippet") or "","url":i.get("displayUrl") or "","source":i.get("shortenedDisplayUrl") or "Google Web Search Service"} for i in payload.get("searchResults",[])]
def _search_public_records(query,location=""):
    text_query=" ".join(part for part in [query,location] if part).strip()
    if not text_query:return {"configured":True,"source":"Google Search","message":"Enter a search.","results":[]}
    web_api_key=os.environ.get("GOOGLE_WEB_SEARCH_API_KEY") or os.environ.get("GOOGLE_SEARCH_API_KEY") or "";web_client_id=os.environ.get("GOOGLE_WEB_SEARCH_CLIENT_ID") or ""
    custom_api_key=os.environ.get("GOOGLE_SEARCH_API_KEY") or "";cx=os.environ.get("GOOGLE_SEARCH_CX") or ""
    if web_api_key and web_client_id:
        ip=_request_ip()
        if ip:
            r=requests.get("https://websearchservice.googleapis.com/v1:search",headers={"X-Goog-Api-Key":web_api_key},params={"clientContext.clientId":web_client_id,"userContext.ipAddress":ip,"userContext.regionCode":"US","searchQuery.query":text_query,"searchQuery.languageCode":"en","searchQuery.safeSearch":"ON","pageSize":10,"webSearch":""},timeout=20)
            if r.ok:return {"configured":True,"source":"Google Web Search Service","message":"","results":_normalize_web_search_results(r.json())}
    if custom_api_key and cx:
        r=requests.get("https://www.googleapis.com/customsearch/v1",params={"key":custom_api_key,"cx":cx,"q":text_query,"num":10},timeout=20)
        if r.ok:return {"configured":True,"source":"Google Programmable Search","message":"","results":_normalize_custom_search_results(r.json())}
        return {"configured":True,"source":"Google Programmable Search","message":f"Google Programmable Search returned HTTP {r.status_code}. {_google_error_message(r)}".strip(),"results":[]}
    return {"configured":False,"source":"Google Search","message":"Google search credentials are not configured.","results":[]}
def _normalize_jobs(keyword):
    return [{"type":"job","id":j.get("id") or "","title":j.get("title") or "Unknown title","subtitle":" | ".join(x for x in [j.get("company"),j.get("location")] if x),"url":j.get("url") or "","source":j.get("source") or "","status":j.get("status") or "","error":j.get("error") or ""} for j in search_remote_jobs(keyword)]
@app.route("/api/universal-search/capabilities")
def universal_search_capabilities():
    custom=bool(os.environ.get("GOOGLE_SEARCH_API_KEY") and os.environ.get("GOOGLE_SEARCH_CX"));web=bool((os.environ.get("GOOGLE_WEB_SEARCH_API_KEY") or os.environ.get("GOOGLE_SEARCH_API_KEY")) and os.environ.get("GOOGLE_WEB_SEARCH_CLIENT_ID"));source="Google Web Search Service" if web else ("Google Programmable Search" if custom else "Google Search")
    return jsonify({"jobs":{"configured":True,"source":"Remotive"},"businesses":{"configured":bool(_places_key()),"source":"Google Places"},"public_records":{"configured":custom or web,"source":source,"google_search_api_key_present":bool(os.environ.get("GOOGLE_SEARCH_API_KEY")),"google_search_cx_present":bool(os.environ.get("GOOGLE_SEARCH_CX"))}})
@app.route("/api/universal-search",methods=["GET","POST"])
def universal_search():
    data=(request.get_json(silent=True) or {}) if request.method=="POST" else request.args;mode=_clean(data.get("mode") or "jobs",40).lower();query=_clean(data.get("query") or data.get("keyword") or "",300);location=_clean(data.get("location") or "",200)
    if mode in ("job","jobs"):payload={"configured":True,"source":"Remotive","message":"","results":_normalize_jobs(query or "machine learning")};event_type="universal_job_search"
    elif mode in ("business","businesses","contractor","contractors"):payload=_search_businesses(query,location);event_type="universal_business_search"
    elif mode in ("permit","permits","public_record","public_records","records"):payload=_search_public_records(query,location);event_type="universal_public_record_search"
    else:return jsonify({"error":"Unsupported search mode"}),400
    payload.update({"mode":mode,"query":query,"location":location,"count":len(payload.get("results") or [])})
    try:
        db.session.add(AutomationEvent(event_type=event_type,source=payload.get("source") or "Universal Search",status="success" if payload.get("results") else "error",details=f"mode={mode}; query={query}; location={location}"));db.session.commit()
    except Exception:db.session.rollback()
    return jsonify(payload)
