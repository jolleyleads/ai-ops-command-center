from app import app
from flask import send_from_directory, Response

@app.route('/chat-operator')
def chat_operator_ui(force_demo=False):
    from outreach_automation import _operator_authorized, _operator_session_authorized
    if not force_demo and (_operator_authorized() or _operator_session_authorized()):
        response = send_from_directory('demo', 'index.html')
    else:
        with app.open_resource('demo/index.html') as source:
            html = source.read().decode('utf-8')
        html = html.replace('<p>Ask.Automate.Execute</p>', '<p>Ask.Automate.Execute</p><p class="small" id="public-demo-note">Explore sample data. No emails are sent in this demo.</p>')
        html = html.replace('<script src="/chat-operator/dashboard.js', '<script src="/chat-operator/public-demo.js" defer></script><script src="/chat-operator/dashboard.js', 1)
        response = Response(html, mimetype='text/html')
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Vary'] = 'Cookie, X-Operator-Token'
    return response

@app.route('/chat-operator/public-demo.js')
def public_demo_script():
    response = send_from_directory('demo', 'public-demo.js', mimetype='application/javascript')
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/chat-operator/dashboard.js')
def customer_dashboard_script():
    response = send_from_directory('demo', 'dashboard.js', mimetype='application/javascript')
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/chat-operator/automake-logo.svg')
def automake_logo():
    return send_from_directory('demo', 'automake-logo.svg', mimetype='image/svg+xml')
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

rag_research.init_rag_tables()

from configured_campaign import start_configured_campaign
start_configured_campaign()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
