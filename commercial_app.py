from app import app
from flask import send_from_directory

@app.route('/chat-operator')
def chat_operator_ui():
    return send_from_directory('demo', 'index.html')

@app.route('/chat-operator/dashboard.js')
def customer_dashboard_script():
    response = send_from_directory('demo', 'dashboard.js', mimetype='application/javascript')
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/chat-operator/access.js')
def customer_access_script():
    response = send_from_directory('demo', 'access.js', mimetype='application/javascript')
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/chat-operator/automake-logo.svg')
def automake_logo():
    return send_from_directory('demo', 'automake-logo.svg', mimetype='image/svg+xml')

# Public marketing landing page. Existing login and customer routes remain unchanged.
from flask import request, Response
_AUTOMAKE_HOME = "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><meta name=\"description\" content=\"AutoMake AI turns business research, verified leads and outreach into a connected workflow.\"><title>AutoMake AI | Ask. Automate. Execute.</title><style>:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#080e1b;color:#f7f9ff;font:16px/1.6 system-ui,-apple-system,Segoe UI,sans-serif}a{color:inherit;text-decoration:none}.wrap{max-width:1160px;margin:auto;padding:0 24px}header{border-bottom:1px solid #25334d;background:#0a1324}nav{min-height:80px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}.brand{display:flex;align-items:center;gap:12px;font-size:21px;font-weight:800}.brand img{width:44px;height:44px}.links{display:flex;gap:20px;align-items:center;flex-wrap:wrap}.btn{display:inline-block;border-radius:12px;padding:12px 20px;background:#d8ad50;color:#101725;font-weight:750}.outline{background:transparent;color:#fff;border:1px solid #64748b}.hero{padding:105px 0 85px;background:radial-gradient(ellipse at 75% 20%,#1d3657 0%,transparent 53%)}.eyebrow{color:#e6bc69;font-weight:700;letter-spacing:.14em;text-transform:uppercase;font-size:13px}h1{font-size:clamp(42px,7vw,76px);line-height:1.08;max-width:850px;margin:15px 0 22px;letter-spacing:-.045em}h1 span{color:#e6bc69}.lead{font-size:clamp(18px,2vw,22px);color:#c4cfdf;max-width:720px}.actions{display:flex;gap:14px;flex-wrap:wrap;margin-top:32px}section{padding:70px 0}h2{font-size:clamp(28px,4vw,42px);line-height:1.2;letter-spacing:-.025em}p{color:#c4cfdf}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-top:30px}.tile{background:#111e32;border:1px solid #30415b;padding:26px;border-radius:18px}.tile h3{margin-top:0;color:#f6d38a}.muted{background:#0d1728}.cta{background:#14253c;border:1px solid #435773;border-radius:24px;padding:42px;margin:40px 0}footer{border-top:1px solid #30415b;padding:30px 0;color:#aebdd1}@media(max-width:700px){nav{padding:16px 0}.links{gap:10px}.hero{padding:70px 0}.grid{grid-template-columns:1fr}.cta{padding:26px}}</style></head><body><header><div class=\"wrap\"><nav><a class=\"brand\" href=\"/\"><img src=\"/chat-operator/automake-logo.svg\" alt=\"AutoMake AI logo\">AutoMake AI</a><div class=\"links\"><a href=\"#how\">How it works</a><a href=\"#demo\">Book a demo</a><a class=\"btn outline\" href=\"/login\">Log In</a></div></nav></div></header><main><div class=\"hero\"><div class=\"wrap\"><div class=\"eyebrow\">Ask. Automate. Execute.</div><h1>Stop losing customers to <span>slow follow-up.</span></h1><p class=\"lead\">Your next customer shouldn't slip away because your team is busy. AutoMake AI helps you research prospects, organize verified contacts, prepare personalized outreach, and manage follow-ups in one connected workspace.</p><div class=\"actions\"><a class=\"btn\" href=\"#demo\">Book a Demo</a><a class=\"btn outline\" href=\"/login\">Access Your Workspace</a></div></div></div><section class=\"muted\"><div class=\"wrap\"><div class=\"eyebrow\">The problem</div><h2>Too many leads. Too many tabs. Not enough time.</h2><p>Manual prospecting, scattered conversations, and missed follow-ups slow down growth. AutoMake AI brings the process together so your team can focus on relationships and closing deals.</p></div></section><section id=\"how\"><div class=\"wrap\"><div class=\"eyebrow\">One connected workflow</div><h2>From finding prospects to starting conversations.</h2><div class=\"grid\"><article class=\"tile\"><h3>01 / Research</h3><p>Describe the businesses you want to reach and organize relevant prospects in one place.</p></article><article class=\"tile\"><h3>02 / Verify &amp; prepare</h3><p>Enrich contact details, review verification status, and prepare tailored email drafts.</p></article><article class=\"tile\"><h3>03 / Execute &amp; track</h3><p>Manage outreach, follow-ups, conversations, and campaign progress from your existing customer dashboard.</p></article></div></div></section><section class=\"muted\"><div class=\"wrap\"><div class=\"eyebrow\">Built for real teams</div><h2>Less busywork. More time for business.</h2><p>Designed for service businesses, sales teams, and operators who need a simpler path from research to outreach. Results depend on data quality, account configuration, and campaign execution.</p><div class=\"cta\" id=\"demo\"><h2 id=\"book-demo\">See what AutoMake AI can do for your business.</h2><p>Tell us about your team and the outreach tasks slowing you down. We'll help you explore a workflow that fits.</p><div class=\"actions\"><a class=\"btn\" href=\"mailto:jolleyleads@gmail.com?subject=AutoMake%20AI%20Demo%20Request\">Request a Demo by Email</a><a class=\"btn outline\" href=\"/login\">Customer Log In</a></div></div></div></section></main><footer><div class=\"wrap\">© 2026 AutoMake AI · Ask. Automate. Execute. · <a href=\"mailto:jolleyleads@gmail.com\">Contact</a></div></footer></body></html>"
@app.before_request
def automake_public_homepage():
    if request.path == '/' and request.method in ('GET', 'HEAD'):
        return Response(_AUTOMAKE_HOME, mimetype='text/html')

import db_resilience  # noqa: F401
import gmail_connect  # noqa: F401
import search_overrides  # noqa: F401
import contractor_intent  # noqa: F401
import places_diagnostic  # noqa: F401
import permit_leads  # noqa: F401
import local_jobs  # noqa: F401
import rag_research  # noqa: F401
import smart_search  # noqa: F401
import background_research  # noqa: F401
import automation_monitor  # noqa: F401
import provider_circuit_breaker  # noqa: F401
import outreach_automation  # noqa: F401
import production_e2e  # noqa: F401
import operator_e2e_ui  # noqa: F401
import gmail_reconciliation  # noqa: F401
import v1_orchestration  # noqa: F401
import lead_recovery  # noqa: F401
import operator_inbound_ui  # noqa: F401
import operator_conversation_import  # noqa: F401
import outreach_scheduler  # noqa: F401
import db_diagnostic  # noqa: F401
import provider_acceptance_ui  # noqa: F401
import customer_demo  # noqa: F401
import customer_dashboard  # noqa: F401
import customer_auth  # noqa: F401
import google_drive_connect  # noqa: F401
import crm_catalog_api  # noqa: F401
import crm_oauth_api  # noqa: F401

import workspace_security  # noqa: F401
import src.selection_workflows  # noqa: F401
import src.campaign_reporting  # noqa: F401
import src.progressive_campaign  # noqa: F401
import src.owned_research  # noqa: F401

rag_research.init_rag_tables()

from owner_test_cleanup import run_startup_cleanup
run_startup_cleanup()

from configured_campaign import start_configured_campaign
start_configured_campaign()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
