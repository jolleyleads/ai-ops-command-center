from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from email.message import EmailMessage
import base64
import hashlib
import json
import os
import re
import time
import uuid
import requests

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///ai_ops.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

class AutomationEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(100))
    source = db.Column(db.String(100))
    status = db.Column(db.String(100))
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class SavedJob(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    company = db.Column(db.String(200))
    source = db.Column(db.String(100))
    location = db.Column(db.String(200))
    url = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Workflow(db.Model):
    id = db.Column(db.String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    status = db.Column(db.String(30), default="draft")
    definition = db.Column(db.Text, nullable=False, default='{"nodes":[],"edges":[]}')
    schedule = db.Column(db.String(120), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class WorkflowRun(db.Model):
    id = db.Column(db.String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id = db.Column(db.String(64), db.ForeignKey('workflow.id'), nullable=False)
    status = db.Column(db.String(30), default="queued")
    input_json = db.Column(db.Text, default='{}')
    output_json = db.Column(db.Text, default='{}')
    logs_json = db.Column(db.Text, default='[]')
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)

class Credential(db.Model):
    id = db.Column(db.String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(120), nullable=False)
    connector = db.Column(db.String(80), nullable=False)
    env_var = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class QualifiedLead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    workflow_run_id = db.Column(db.String(64), unique=True, nullable=False)
    lead = db.Column(db.Text, nullable=False)
    ai_output = db.Column(db.Text, default="")
    openai_response_id = db.Column(db.String(200), default="")
    status = db.Column(db.String(50), default="qualified")
    source = db.Column(db.String(100), default="Electrical Contractor Lead Qualification")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class LeadPipeline(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    qualified_lead_id = db.Column(db.Integer, unique=True, nullable=False)
    stage = db.Column(db.String(50), default="New")
    notes = db.Column(db.Text, default="")
    follow_up_date = db.Column(db.String(20), default="")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

NODE_TYPES = {
    "trigger": "Trigger", "schedule": "Schedule", "webhook": "Webhook",
    "condition": "IF / ELSE", "ai": "OpenAI", "http": "HTTP Request",
    "email": "Gmail", "sms": "SMS", "crm": "CRM", "delay": "Delay",
    "action": "Action"
}

def make_job_id(title, company, source, url):
    raw = f"{title}|{company}|{source}|{url}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def normalize_job(source, title, company, location, url):
    return {"id":make_job_id(title or "Unknown Title", company or "Unknown Company", source or "Unknown Source", url or ""),
            "title":title or "Unknown Title", "company":company or "Unknown Company", "source":source or "Unknown Source",
            "location":location or "Remote", "url":url or "", "recruiterEmail":"", "status":"New"}

def search_remote_jobs(keyword="machine learning"):
    jobs=[]
    try:
        r=requests.get("https://remotive.com/api/remote-jobs", params={"search":keyword}, timeout=15)
        for job in r.json().get("jobs",[])[:25]:
            jobs.append(normalize_job("Remotive",job.get("title"),job.get("company_name"),job.get("candidate_required_location"),job.get("url")))
    except Exception as e:
        jobs.append({"id":make_job_id("Error fetching jobs","System","AI Ops",""),"title":"Error fetching jobs","company":"System","source":"AI Ops","location":"N/A","url":"","status":"Error","error":str(e)})
    return jobs

def parse_definition(workflow):
    try: return json.loads(workflow.definition or '{}')
    except Exception: return {"nodes":[],"edges":[]}

def get_path(data, path):
    current=data
    for part in str(path or "").split('.'):
        if not part: continue
        if isinstance(current,dict): current=current.get(part)
        else: return None
    return current

def render_template_string(value, context):
    if not isinstance(value,str): return value
    def repl(match):
        v=get_path(context,match.group(1).strip())
        if isinstance(v,(dict,list)): return json.dumps(v)
        return "" if v is None else str(v)
    return re.sub(r'{{\s*([^}]+?)\s*}}', repl, value)

def evaluate_condition(config, context):
    field=config.get("field","")
    operator=config.get("operator","equals")
    expected=render_template_string(config.get("value"),context)
    actual=get_path(context,field)
    if operator=="equals": return str(actual)==str(expected)
    if operator=="not_equals": return str(actual)!=str(expected)
    if operator=="contains": return str(expected).lower() in str(actual or '').lower()
    if operator=="not_contains": return str(expected).lower() not in str(actual or '').lower()
    if operator=="exists": return actual not in (None,"")
    if operator=="gt":
        try: return float(actual)>float(expected)
        except Exception: return False
    if operator=="lt":
        try: return float(actual)<float(expected)
        except Exception: return False
    return False

def openai_text(prompt, instructions="", model=None):
    api_key=os.environ.get("OPENAI_API_KEY")
    if not api_key: raise RuntimeError("OPENAI_API_KEY is not configured on Render")
    model=model or os.environ.get("OPENAI_MODEL","gpt-5")
    payload={"model":model,"input":prompt}
    if instructions: payload["instructions"]=instructions
    r=requests.post("https://api.openai.com/v1/responses",headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},json=payload,timeout=90)
    if not r.ok: raise RuntimeError(f"OpenAI error {r.status_code}: {r.text[:600]}")
    data=r.json()
    if data.get("output_text"): return data["output_text"],data.get("id")
    parts=[]
    for item in data.get("output",[]):
        for content in item.get("content",[]):
            if content.get("type")=="output_text": parts.append(content.get("text",''))
    return "\n".join(parts),data.get("id")

def gmail_access_token():
    direct=os.environ.get("GMAIL_ACCESS_TOKEN")
    if direct: return direct
    refresh=os.environ.get("GOOGLE_REFRESH_TOKEN")
    client_id=os.environ.get("GOOGLE_CLIENT_ID")
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET")
    if not all([refresh,client_id,client_secret]):
        raise RuntimeError("Gmail is not configured. Add GMAIL_ACCESS_TOKEN or GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET + GOOGLE_REFRESH_TOKEN on Render")
    r=requests.post("https://oauth2.googleapis.com/token",data={"client_id":client_id,"client_secret":client_secret,"refresh_token":refresh,"grant_type":"refresh_token"},timeout=20)
    if not r.ok: raise RuntimeError(f"Google token error {r.status_code}: {r.text[:500]}")
    return r.json()["access_token"]

def send_gmail(to,subject,body,from_email=None):
    token=gmail_access_token()
    from_email=from_email or os.environ.get("GMAIL_FROM_EMAIL","")
    msg=EmailMessage(); msg["To"]=to; msg["Subject"]=subject
    if from_email: msg["From"]=from_email
    msg.set_content(body)
    raw=base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip('=')
    r=requests.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},json={"raw":raw},timeout=30)
    if not r.ok: raise RuntimeError(f"Gmail error {r.status_code}: {r.text[:600]}")
    return r.json()

def send_sms(to,body,from_number=None):
    sid=os.environ.get("TWILIO_ACCOUNT_SID")
    token=os.environ.get("TWILIO_AUTH_TOKEN")
    from_number=from_number or os.environ.get("TWILIO_FROM_NUMBER") or os.environ.get("TWILIO_PHONE_NUMBER")
    if not all([sid,token,from_number]): raise RuntimeError("Twilio is not configured on Render")
    url=f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    r=requests.post(url,auth=(sid,token),data={"To":to,"From":from_number,"Body":body},timeout=30)
    if not r.ok: raise RuntimeError(f"Twilio error {r.status_code}: {r.text[:600]}")
    return r.json()

def execute_node(node, context):
    node_type=node.get("type"); config=node.get("config",{}); label=node.get("label") or node_type
    if node_type in ("trigger","schedule","webhook"):
        return {"ok":True,"context":context,"summary":f"{label} fired"}
    if node_type=="condition":
        result=evaluate_condition(config,context)
        branch="true" if result else "false"
        context["condition_result"]=result
        context["condition_branch"]=branch
        return {"ok":True,"branch":branch,"context":context,"summary":f"Condition = {result}; branch = {branch.upper()}"}
    if node_type=="ai":
        prompt_template=config.get("prompt") or "{{input}}"

        if "{{lead}}" in prompt_template and not context.get("lead"):
            context["lead"]={
                k:v for k,v in context.items()
                if k not in (
                    "ai_output",
                    "condition_result",
                    "condition_branch",
                    "openai_response_id",
                    "sms_result",
                    "gmail_result"
                )
            }

        prompt=render_template_string(prompt_template,context)
        instructions=render_template_string(config.get("instructions",""),context)
        text,response_id=openai_text(prompt,instructions,config.get("model") or None)
        key=config.get("output_key","ai_output"); context[key]=text; context["openai_response_id"]=response_id
        return {"ok":True,"context":context,"summary":f"OpenAI wrote {len(text)} chars"}
    if node_type=="http":
        method=config.get("method","GET").upper(); url=render_template_string(config.get("url",""),context)
        if not url: return {"ok":False,"error":"HTTP node requires a URL"}
        body=config.get("body"); headers=config.get("headers") or {}
        if isinstance(body,dict): body={k:render_template_string(v,context) for k,v in body.items()}
        headers={k:render_template_string(v,context) for k,v in headers.items()}
        resp=requests.request(method,url,json=body,headers=headers,timeout=30)
        context[config.get("output_key","http_response")]={"status":resp.status_code,"text":resp.text[:4000]}
        return {"ok":resp.ok,"context":context,"summary":f"HTTP {resp.status_code}"}
    if node_type=="email":
        to=render_template_string(config.get("to",""),context); subject=render_template_string(config.get("subject","Automation message"),context); body=render_template_string(config.get("body",""),context)
        if not to: return {"ok":False,"error":"Gmail node requires a recipient"}
        sent=send_gmail(to,subject,body,config.get("from")); context[config.get("output_key","gmail_result")]=sent
        return {"ok":True,"context":context,"summary":f"Gmail sent to {to}"}
    if node_type=="sms":
        to=render_template_string(config.get("to",""),context); body=render_template_string(config.get("body",""),context)
        if not to or not body: return {"ok":False,"error":"SMS node requires To and Body"}
        sent=send_sms(to,body,config.get("from")); context[config.get("output_key","sms_result")]={"sid":sent.get("sid"),"status":sent.get("status")}
        return {"ok":True,"context":context,"summary":f"SMS queued for {to}"}
    if node_type=="delay":
        seconds=max(0,min(float(config.get("seconds",1) or 0),10)); time.sleep(seconds)
        return {"ok":True,"context":context,"summary":f"Waited {seconds}s"}
    if node_type in ("crm","action"):
        context.setdefault("actions",[]).append({"type":node_type,"label":label,"config":config,"status":"prepared"})
        return {"ok":True,"context":context,"summary":f"{label} prepared"}
    return {"ok":False,"error":f"Unsupported node type: {node_type}"}

def run_workflow(workflow,payload):
    definition=parse_definition(workflow); nodes=definition.get("nodes",[]); edges=definition.get("edges",[])
    by_id={n.get("id"):n for n in nodes}; incoming={n.get("id"):0 for n in nodes}
    for e in edges:
        if e.get("target") in incoming: incoming[e.get("target")]+=1
    queue=[nid for nid,count in incoming.items() if count==0]
    context=dict(payload or {}); logs=[]; visited=set()
    while queue:
        nid=queue.pop(0)
        if nid in visited or nid not in by_id: continue
        visited.add(nid); node=by_id[nid]
        try: result=execute_node(node,context)
        except Exception as e: result={"ok":False,"error":str(e)}
        logs.append({"node_id":nid,"node":node.get("label") or node.get("type"),"type":node.get("type"),"result":result})
        if not result.get("ok"): return False,context,logs
        context=result.get("context",context); branch=result.get("branch")
        outgoing=[e for e in edges if e.get("source")==nid]

        if node.get("type")=="condition":
            outgoing=[e for e in outgoing if e.get("branch")==branch]

        for e in outgoing:
            target=e.get("target")
            if target and target not in visited:
                queue.append(target)
    return True,context,logs

@app.before_request
def create_tables(): db.create_all()

@app.route("/")
def index():
    events=AutomationEvent.query.order_by(AutomationEvent.created_at.desc()).limit(10).all()
    jobs=SavedJob.query.order_by(SavedJob.created_at.desc()).limit(20).all()
    workflow_count=Workflow.query.count()

    leads=QualifiedLead.query.order_by(QualifiedLead.created_at.desc()).limit(100).all()
    pipeline_rows=LeadPipeline.query.all()
    pipeline_by_lead={row.qualified_lead_id:row for row in pipeline_rows}

    qualified_leads=[]
    for lead in leads:
        pipeline=pipeline_by_lead.get(lead.id)
        qualified_leads.append({
            "id":lead.id,
            "lead":lead.lead,
            "ai_output":lead.ai_output,
            "source":lead.source,
            "created_at":lead.created_at,
            "stage":pipeline.stage if pipeline else "New",
            "notes":pipeline.notes if pipeline else "",
            "follow_up_date":pipeline.follow_up_date if pipeline else ""
        })

    pipeline_counts={
        stage:sum(1 for lead in qualified_leads if lead["stage"]==stage)
        for stage in ["New","Contacted","Qualified","Proposal Sent","Won","Lost"]
    }

    return render_template(
        "index.html",
        events=events,
        jobs=jobs,
        workflow_count=workflow_count,
        qualified_leads=qualified_leads,
        pipeline_counts=pipeline_counts
    )

@app.route("/workflows")
def workflows_page(): return render_template("workflows.html",node_types=NODE_TYPES)

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST": session["user"]=request.form.get("email"); return redirect(url_for("index"))
    return render_template("login.html")

@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

@app.route("/api/workflows",methods=["GET","POST"])
def workflows_api():
    if request.method=="GET":
        rows=Workflow.query.order_by(Workflow.updated_at.desc()).all()
        return jsonify([{"id":w.id,"name":w.name,"description":w.description,"status":w.status,"schedule":w.schedule,"definition":parse_definition(w),"updated_at":w.updated_at.isoformat()} for w in rows])
    data=request.get_json(silent=True) or {}; wf=Workflow(name=data.get("name") or "Untitled Workflow",description=data.get("description",""),status=data.get("status","draft"),schedule=data.get("schedule",""),definition=json.dumps(data.get("definition") or {"nodes":[],"edges":[]})); db.session.add(wf); db.session.commit(); return jsonify({"id":wf.id,"status":"created"}),201

@app.route("/api/workflows/<workflow_id>",methods=["GET","PUT","DELETE"])
def workflow_detail(workflow_id):
    wf=Workflow.query.get_or_404(workflow_id)
    if request.method=="GET": return jsonify({"id":wf.id,"name":wf.name,"description":wf.description,"status":wf.status,"schedule":wf.schedule,"definition":parse_definition(wf)})
    if request.method=="DELETE": WorkflowRun.query.filter_by(workflow_id=workflow_id).delete(); db.session.delete(wf); db.session.commit(); return jsonify({"status":"deleted"})
    data=request.get_json(silent=True) or {}; wf.name=data.get("name",wf.name); wf.description=data.get("description",wf.description); wf.status=data.get("status",wf.status); wf.schedule=data.get("schedule",wf.schedule)
    if "definition" in data: wf.definition=json.dumps(data["definition"])
    db.session.commit(); return jsonify({"status":"updated"})

@app.route("/api/workflows/<workflow_id>/run",methods=["POST"])
def run_workflow_api(workflow_id):
    wf=Workflow.query.get_or_404(workflow_id)
    payload=request.get_json(silent=True) or {}

    run=WorkflowRun(
        workflow_id=wf.id,
        status="running",
        input_json=json.dumps(payload)
    )
    db.session.add(run)
    db.session.commit()

    ok,output,logs=run_workflow(wf,payload)

    run.status="success" if ok else "failed"
    run.output_json=json.dumps(output)
    run.logs_json=json.dumps(logs)
    run.finished_at=datetime.utcnow()
    db.session.commit()

    db.session.add(
        AutomationEvent(
            event_type="workflow_run",
            source=wf.name,
            status=run.status,
            details=f"Workflow {wf.id} run {run.id}"
        )
    )
    db.session.commit()

    # Dashboard save happens only AFTER the working workflow completes.
    # Any save error is isolated so it cannot break a successful workflow run.
    if ok and output.get("condition_branch")=="true" and output.get("lead"):
        try:
            existing=QualifiedLead.query.filter_by(workflow_run_id=run.id).first()
            if not existing:
                saved_lead=QualifiedLead(
                    workflow_run_id=run.id,
                    lead=str(output.get("lead","")),
                    ai_output=str(output.get("ai_output","")),
                    openai_response_id=str(output.get("openai_response_id","")),
                    status="qualified",
                    source=wf.name or "Electrical Contractor Lead Qualification"
                )
                db.session.add(saved_lead)
                db.session.commit()

                output["qualified_lead_id"]=saved_lead.id
                output["qualified_lead_saved"]=True

                run.output_json=json.dumps(output)
                db.session.commit()
        except Exception as e:
            db.session.rollback()
            output["qualified_lead_saved"]=False
            output["qualified_lead_save_error"]=str(e)[:300]

    return jsonify({
        "run_id":run.id,
        "status":run.status,
        "output":output,
        "logs":logs
    })

@app.route("/api/runs")
def runs_api():
    rows=WorkflowRun.query.order_by(WorkflowRun.started_at.desc()).limit(50).all(); return jsonify([{"id":r.id,"workflow_id":r.workflow_id,"status":r.status,"started_at":r.started_at.isoformat(),"finished_at":r.finished_at.isoformat() if r.finished_at else None} for r in rows])

@app.route("/api/credentials/status")
def credential_status():
    return jsonify({
        "openai":{"configured":bool(os.environ.get("OPENAI_API_KEY")),"model":os.environ.get("OPENAI_MODEL","gpt-5")},
        "gmail":{"configured":bool(os.environ.get("GMAIL_ACCESS_TOKEN") or (os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET") and os.environ.get("GOOGLE_REFRESH_TOKEN")))},
        "twilio":{"configured":bool(os.environ.get("TWILIO_ACCOUNT_SID") and os.environ.get("TWILIO_AUTH_TOKEN") and os.environ.get("TWILIO_FROM_NUMBER"))}
    })

@app.route("/api/credentials",methods=["GET","POST"])
def credentials_api():
    if request.method=="GET":
        rows=Credential.query.order_by(Credential.created_at.desc()).all(); return jsonify([{"id":c.id,"name":c.name,"connector":c.connector,"env_var":c.env_var,"configured":bool(os.environ.get(c.env_var))} for c in rows])
    data=request.get_json(silent=True) or {}; c=Credential(name=data.get("name") or data.get("connector") or "Credential",connector=data.get("connector") or "custom",env_var=data.get("env_var") or ""); db.session.add(c); db.session.commit(); return jsonify({"id":c.id,"status":"saved","note":"Only environment variable names are stored; secret values stay in Render."}),201

@app.route("/api/ai/generate-workflow",methods=["POST"])
def generate_workflow():
    data=request.get_json(silent=True) or {}; description=data.get("description") or ""; text=description.lower(); nodes=[{"id":"trigger-1","type":"trigger","label":"Start","x":70,"y":180,"config":{}}]; edges=[]; last="trigger-1"
    def add(ntype,label,config=None,branch=None,y=180):
        nonlocal last
        nid=f"{ntype}-{len(nodes)+1}"; nodes.append({"id":nid,"type":ntype,"label":label,"x":70+220*len(nodes),"y":y,"config":config or {}}); edges.append({"id":str(uuid.uuid4()),"source":last,"target":nid,**({"branch":branch} if branch else {})}); last=nid; return nid
    if any(k in text for k in ["if ","condition","only when","qualified"]): add("condition","Qualified?",{"field":"status","operator":"equals","value":"qualified"})
    if any(k in text for k in ["ai","openai","summar","write","classif","qualif"]): add("ai","AI Process",{"prompt":description,"output_key":"ai_output"},branch="true" if nodes[-1]["type"]=="condition" else None)
    if "email" in text or "gmail" in text: add("email","Send Gmail",{"to":"{{email}}","subject":"Automation follow-up","body":"{{ai_output}}"})
    if "sms" in text or "text" in text: add("sms","Send SMS",{"to":"{{phone}}","body":"{{ai_output}}"})
    if "crm" in text: add("crm","CRM Action",{"action":"upsert_contact"})
    if len(nodes)==1: add("action","Action",{"description":description})
    return jsonify({"name":data.get("name") or "AI Generated Workflow","definition":{"nodes":nodes,"edges":edges}})

@app.route("/api/jobs",methods=["GET","POST"])
def api_jobs():
    data=request.get_json(silent=True) or {} if request.method=="POST" else {}; keyword=data.get("keyword","machine learning") if request.method=="POST" else request.args.get("keyword","machine learning"); jobs=search_remote_jobs(keyword); db.session.add(AutomationEvent(event_type="job_search",source="AI Ops Jobs API",status="success",details=f"Searched remote jobs for: {keyword}")); db.session.commit(); return jsonify({"keyword":keyword,"count":len(jobs),"jobs":jobs})

@app.route("/api/save-job",methods=["POST"])
def save_job():
    data=request.get_json(silent=True) or {}; job=SavedJob(title=data.get("title"),company=data.get("company"),source=data.get("source"),location=data.get("location"),url=data.get("url")); db.session.add(job); db.session.add(AutomationEvent(event_type="save_job",source="dashboard_or_make",status="success",details=f"Saved job: {data.get('title')} at {data.get('company')}")); db.session.commit(); return jsonify({"status":"saved","job":data})

@app.route("/api/events")
def api_events():
    events=AutomationEvent.query.order_by(AutomationEvent.created_at.desc()).limit(25).all(); return jsonify([{"id":e.id,"event_type":e.event_type,"source":e.source,"status":e.status,"details":e.details,"created_at":e.created_at.isoformat()} for e in events])

@app.route("/api/qualified-leads/<int:lead_id>/pipeline", methods=["GET","POST"])
def qualified_lead_pipeline_api(lead_id):
    lead=QualifiedLead.query.get_or_404(lead_id)
    row=LeadPipeline.query.filter_by(qualified_lead_id=lead.id).first()

    if request.method=="GET":
        return jsonify({
            "lead_id":lead.id,
            "stage":row.stage if row else "New",
            "notes":row.notes if row else "",
            "follow_up_date":row.follow_up_date if row else ""
        })

    data=request.get_json(silent=True) or {}
    allowed_stages=["New","Contacted","Qualified","Proposal Sent","Won","Lost"]
    stage=data.get("stage","New")

    if stage not in allowed_stages:
        return jsonify({"error":"Invalid pipeline stage"}),400

    if not row:
        row=LeadPipeline(qualified_lead_id=lead.id)
        db.session.add(row)

    row.stage=stage
    row.notes=str(data.get("notes",""))[:5000]
    row.follow_up_date=str(data.get("follow_up_date",""))[:20]
    row.updated_at=datetime.utcnow()

    db.session.add(
        AutomationEvent(
            event_type="lead_pipeline_update",
            source="AI Ops Dashboard",
            status=stage,
            details=f"Lead {lead.id} moved to {stage}"
        )
    )
    db.session.commit()

    return jsonify({
        "status":"saved",
        "lead_id":lead.id,
        "stage":row.stage,
        "notes":row.notes,
        "follow_up_date":row.follow_up_date
    })

@app.route("/api/pipeline")
def pipeline_api():
    leads=QualifiedLead.query.order_by(QualifiedLead.created_at.desc()).limit(100).all()
    pipeline_rows=LeadPipeline.query.all()
    pipeline_by_lead={row.qualified_lead_id:row for row in pipeline_rows}

    return jsonify([
        {
            "id":lead.id,
            "lead":lead.lead,
            "source":lead.source,
            "created_at":lead.created_at.isoformat(),
            "stage":pipeline_by_lead[lead.id].stage if lead.id in pipeline_by_lead else "New",
            "notes":pipeline_by_lead[lead.id].notes if lead.id in pipeline_by_lead else "",
            "follow_up_date":pipeline_by_lead[lead.id].follow_up_date if lead.id in pipeline_by_lead else ""
        }
        for lead in leads
    ])

@app.route("/api/qualified-leads")
def qualified_leads_api():
    rows=QualifiedLead.query.order_by(QualifiedLead.created_at.desc()).limit(100).all()
    return jsonify([
        {
            "id":lead.id,
            "workflow_run_id":lead.workflow_run_id,
            "lead":lead.lead,
            "ai_output":lead.ai_output,
            "openai_response_id":lead.openai_response_id,
            "status":lead.status,
            "source":lead.source,
            "created_at":lead.created_at.isoformat()
        }
        for lead in rows
    ])

@app.route("/api/health")
def health(): return jsonify({"status":"AI Ops Universal Automation v2 online","workflow_builder":"/workflows","credential_status":"/api/credentials/status"})

if __name__=="__main__": app.run(debug=True)
