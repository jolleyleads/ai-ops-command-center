from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import requests
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///ai_ops.db"
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

def search_remote_jobs(keyword="machine learning"):
    jobs = []

    try:
        r = requests.get("https://remotive.com/api/remote-jobs", params={"search": keyword}, timeout=10)
        data = r.json()

        for job in data.get("jobs", [])[:15]:
            jobs.append({
                "source": "Remotive",
                "title": job.get("title"),
                "company": job.get("company_name"),
                "location": job.get("candidate_required_location"),
                "url": job.get("url")
            })
    except Exception:
        pass

    return jobs

@app.route("/")
def index():
    events = AutomationEvent.query.order_by(AutomationEvent.created_at.desc()).limit(10).all()
    jobs = SavedJob.query.order_by(SavedJob.created_at.desc()).limit(10).all()
    return render_template("index.html", events=events, jobs=jobs)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        session["user"] = request.form.get("email")
        return redirect(url_for("index"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/api/jobs", methods=["GET", "POST"])
def api_jobs():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        keyword = data.get("keyword", "machine learning")
    else:
        keyword = request.args.get("keyword", "machine learning")

    jobs = search_remote_jobs(keyword)

    event = AutomationEvent(
        event_type="job_search",
        source="api",
        status="success",
        details=f"Searched remote jobs for: {keyword}"
    )
    db.session.add(event)
    db.session.commit()

    return jsonify({
        "keyword": keyword,
        "count": len(jobs),
        "jobs": jobs
    })

@app.route("/api/save-job", methods=["POST"])
def save_job():
    data = request.get_json(silent=True) or {}

    job = SavedJob(
        title=data.get("title"),
        company=data.get("company"),
        source=data.get("source"),
        location=data.get("location"),
        url=data.get("url")
    )

    db.session.add(job)

    event = AutomationEvent(
        event_type="save_job",
        source="api",
        status="success",
        details=f"Saved job: {data.get('title')}"
    )
    db.session.add(event)

    db.session.commit()

    return jsonify({"status": "saved", "job": data})

@app.route("/api/email-assistant", methods=["POST"])
def email_assistant():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")

    if "free" in message.lower() or "winner" in message.lower() or "click now" in message.lower():
        classification = "Spam"
        suggested_action = "Label as AI-Spam"
    else:
        classification = "Not Spam"
        suggested_action = "Draft a follow-up response"

    event = AutomationEvent(
        event_type="email_classification",
        source="gmail_make_api",
        status="success",
        details=f"Classified message as {classification}"
    )
    db.session.add(event)
    db.session.commit()

    return jsonify({
        "classification": classification,
        "suggested_action": suggested_action,
        "draft_reply": "Thanks for reaching out. I will review this and follow up shortly."
    })

@app.route("/api/events")
def api_events():
    events = AutomationEvent.query.order_by(AutomationEvent.created_at.desc()).limit(25).all()

    return jsonify([
        {
            "id": event.id,
            "event_type": event.event_type,
            "source": event.source,
            "status": event.status,
            "details": event.details,
            "created_at": event.created_at.isoformat()
        }
        for event in events
    ])

@app.before_request
def create_tables():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)
