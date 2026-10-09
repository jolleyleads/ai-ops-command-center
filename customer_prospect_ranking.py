"""Read-only customer prospect ranking API; evidence supplied by verified research."""
from datetime import date
from flask import jsonify, request
from app import app
from prospect_ranking import Evidence, Prospect, rank_prospects

def _evidence(rows):
    result=[]
    for item in rows[:20]:
        if not isinstance(item,dict):
            continue
        try:
            observed=date.fromisoformat(item.get("observed_at",""))
        except (ValueError,TypeError):
            continue
        result.append(Evidence(source_url=str(item.get("source_url") or ""),observed_at=observed,verified=item.get("verified") is True))
    return result

@app.route("/api/demo/prospect-ranking",methods=["POST"])
def demo_prospect_ranking():
    payload=request.get_json(silent=True) or {}
    rows=payload.get("prospects")
    if not isinstance(rows,list) or len(rows)>100:
        return jsonify({"ok":False,"error":"Expected a list of up to 100 prospects"}),400
    prospects=[]
    for row in rows:
        if not isinstance(row,dict) or not str(row.get("company") or "").strip():
            return jsonify({"ok":False,"error":"Every prospect needs a company name"}),400
        prospects.append(Prospect(company=str(row["company"])[:200],complaints=_evidence(row.get("complaints") or []),hiring=_evidence(row.get("hiring") or [])))
    return jsonify({"ok":True,"results":rank_prospects(prospects),"note":"Ranking only. No external verification or outreach is performed by this endpoint."})
