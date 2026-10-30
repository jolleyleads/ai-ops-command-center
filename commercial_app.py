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
_AUTOMAKE_HOME = "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\"><meta name=\"description\" content=\"AutoMake AI connects real business research, decision-maker contacts, outreach, conversations, and appointment booking in one simple workflow.\"><meta name=\"theme-color\" content=\"#080b09\"><title>AutoMake AI | Ask. Automate. Execute.</title>\n<style>\n:root{color-scheme:dark;--bg:#080b09;--panel:#101713;--line:#26372d;--green:#18d77e;--green-light:#80f6b6;--white:#f8fbf9;--muted:#adbbb2}\n*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--white);font:16px/1.65 system-ui,-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif}a{color:inherit;text-decoration:none}button,a{touch-action:manipulation}a:focus-visible,summary:focus-visible{outline:2px solid var(--green);outline-offset:4px}\n.wrap{width:min(1160px,calc(100% - 40px));margin:auto}header{position:sticky;top:0;z-index:20;background:#080b09f2;backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}\n.nav{display:flex;justify-content:space-between;align-items:center;gap:18px;min-height:80px}.brand{display:flex;align-items:center;gap:12px;font-weight:850;font-size:20px;white-space:nowrap;letter-spacing:-.03em}.brand img{width:48px;height:48px;border-radius:12px}.brand span span{color:var(--green)}\n.navlinks{display:flex;gap:18px;align-items:center;flex-wrap:wrap}.navlinks>a:not(.btn){font-size:14px;color:#d5dfd8}.navlinks>a:hover{color:var(--green)}\n.btn{display:inline-flex;justify-content:center;align-items:center;min-height:46px;gap:8px;border-radius:12px;padding:11px 19px;background:var(--green);color:#07130c;font-weight:750;line-height:1.3;text-align:center}.btn.secondary{color:#fff;border:1px solid #56725f;background:transparent}.btn:hover{filter:brightness(1.08)}\n.hero{padding:95px 0 88px;background:radial-gradient(ellipse at 83% 30%,#103f2875,transparent 54%)}.eyebrow{color:var(--green-light);font-size:12px;font-weight:800;letter-spacing:.16em;text-transform:uppercase}h1,h2,h3,p{margin-top:0}h1{font-size:clamp(42px,6.5vw,76px);letter-spacing:-.055em;line-height:1.09;max-width:980px;margin:16px 0 23px}h1 em{font-style:normal;color:var(--green)}.lead{font-size:clamp(17px,2vw,21px);color:#c3d1c8;max-width:750px}.hero-actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:30px}.hero-note{font-size:13px;color:#94a99b;margin:16px 0 0}\nsection{padding:74px 0}h2{font-size:clamp(30px,4vw,45px);line-height:1.18;letter-spacing:-.035em;margin:12px 0 16px}h3{font-size:19px;letter-spacing:-.015em;margin:0 0 9px}p{color:var(--muted)}.intro{max-width:740px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-top:30px}.tile{position:relative;isolation:isolate;min-width:0;padding:30px 26px 27px;background:linear-gradient(155deg,#15241a 0%,#101713 55%,#0e1511 100%);border:1px solid #2b4433;border-radius:22px;box-shadow:0 12px 35px #00000018;transition:transform .22s ease,border-color .22s ease,box-shadow .22s ease}.tile:before{content:'';position:absolute;inset:0 auto auto 0;width:100%;height:2px;border-radius:22px 22px 0 0;background:linear-gradient(90deg,var(--green),transparent 83%);opacity:.75}.tile:hover{transform:translateY(-4px);border-color:#387b52;box-shadow:0 16px 38px #0004}.tile h3{font-size:20px;font-weight:750;letter-spacing:-.045em;line-height:1.25;margin-bottom:11px}.tile p{font-size:14px;line-height:1.72;letter-spacing:.005em;margin:0;color:#b8c9be}.step{display:inline-flex;align-items:center;justify-content:center;min-width:54px;height:41px;padding:0 13px;background:#143322;border:1px solid #316848;color:#7ff0b0;border-radius:12px;font-size:15px;line-height:1;font-weight:850;font-variant-numeric:tabular-nums;letter-spacing:.02em;margin-bottom:25px;box-shadow:inset 0 1px #ffffff0d}.section-alt{background:#0c120e}.flow{margin:35px 0 0;display:flex;align-items:center;justify-content:center;gap:8px;flex-wrap:wrap;padding:17px;background:#0e1711;border:1px solid #2b4734;border-radius:19px}.flow span{display:inline-flex;align-items:center;gap:10px;padding:10px 13px;background:#13291b;border:1px solid #2c5d3d;border-radius:11px;color:#ecfff2;font-size:12px;letter-spacing:.075em;text-transform:uppercase;font-weight:800;white-space:nowrap}.flow span:not(:last-child):after{content:'›';font-size:19px;line-height:0;color:#54d68b;margin-left:6px;font-weight:500}.feature{display:grid;grid-template-columns:1fr 1fr;gap:30px;align-items:center}.feature-copy{max-width:520px}.feature-list{display:grid;gap:12px}.feature-list div{background:#0a140e;border:1px solid var(--line);border-radius:12px;padding:15px 18px;font-size:14px}.feature-list b{color:var(--green-light)}.cta{padding:44px;border:1px solid #376d49;border-radius:24px;background:linear-gradient(135deg,#123321,#0c1710)}.cta p{max-width:690px}.footer{border-top:1px solid var(--line);padding:28px 0 38px}.footrow{display:flex;justify-content:space-between;align-items:center;gap:15px;flex-wrap:wrap}.footrow a{color:var(--green-light);overflow-wrap:anywhere}\n@media(max-width:800px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.feature{grid-template-columns:1fr}.hero{padding:70px 0}.navlinks{gap:10px}}\n@media(max-width:600px){.wrap{width:min(100% - 32px,1160px)}.nav{align-items:center;min-height:70px;flex-wrap:wrap;padding:10px 0}.brand{font-size:17px}.brand img{width:39px;height:39px}.navlinks{width:100%;display:grid;grid-template-columns:1fr 1fr;gap:9px}.navlinks>a:not(.btn){display:none}.navlinks .btn{width:100%;min-width:0;font-size:13px;padding:11px 8px;min-height:44px}.hero{padding:60px 0 58px}h1{font-size:clamp(38px,10vw,54px)}.hero-actions{display:grid;grid-template-columns:1fr;gap:10px}.hero-actions .btn{width:100%}section{padding:54px 0}.grid{grid-template-columns:1fr}.tile{padding:20px}.cta{padding:25px 20px}.flow{gap:8px;padding:12px;justify-content:flex-start}.flow span{font-size:11px;padding:10px 12px}.tile{padding:23px 21px}.tile:hover{transform:none}.footrow{align-items:flex-start;flex-direction:column}}\n@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}.tile{transition:none}.tile:hover{transform:none}}\n</style></head><body>\n<header><nav class=\"wrap nav\" aria-label=\"Main navigation\"><a href=\"/\" class=\"brand\"><img src=\"/chat-operator/automake-logo.svg\" alt=\"AutoMake AI logo\"><span>AUTO<span>MAKE</span> AI</span></a><div class=\"navlinks\"><a href=\"#how\">How it works</a><a href=\"#who\">Who it's for</a><a href=\"/login\" class=\"btn secondary\">Log In</a><a href=\"#demo\" class=\"btn\">Book a Demo</a></div></nav></header>\n<main><div class=\"hero\"><div class=\"wrap\"><div class=\"eyebrow\">Ask. Automate. Execute.</div><h1>Find the right people. <em>Start real conversations.</em> Grow without the busywork.</h1><p class=\"lead\">You know who you want to reach. AutoMake AI helps you find the right businesses, connect with their decision-makers, and keep the conversation moving—right through to a booked appointment.</p><div class=\"hero-actions\"><a class=\"btn\" href=\"#demo\">Book a Demo</a><a class=\"btn secondary\" href=\"/login\">Log In to Your Workspace</a></div><p class=\"hero-note\">One place for research, outreach, follow-ups, and results.</p></div></div>\n<section id=\"how\"><div class=\"wrap\"><div class=\"eyebrow\">How AutoMake AI works</div><h2>From one simple request to a real opportunity.</h2><p class=\"intro\">Tell AutoMake AI what you're looking for. It brings your research, contacts, and outreach together in a clear, goal-driven workflow—so you can focus on the people, not the tabs.</p><div class=\"grid\">\n<article class=\"tile\"><span class=\"step\">01</span><h3>Tell it your goal</h3><p>Type what you need in plain English. For example, ask for HVAC owners in Chesapeake and Portsmouth, with business contacts and emails.</p></article>\n<article class=\"tile\"><span class=\"step\">02</span><h3>Find the right businesses</h3><p>Research companies by industry and location using connected public sources. See relevant business details and where the information came from.</p></article>\n<article class=\"tile\"><span class=\"step\">03</span><h3>Reach the decision-makers</h3><p>Find publicly documented owners, managers, and other key contacts, along with available professional email addresses and phone numbers.</p></article>\n<article class=\"tile\"><span class=\"step\">04</span><h3>Keep everything organized</h3><p>Review your leads and contact details in one workspace. Choose exactly who you want to contact, individually or in groups.</p></article>\n<article class=\"tile\"><span class=\"step\">05</span><h3>Put outreach in motion</h3><p>When you approve it, AutoMake AI prepares and sends personalized outreach through your connected email. No outreach starts just because you ran a search.</p></article>\n<article class=\"tile\"><span class=\"step\">06</span><h3>Follow through to booking</h3><p>Manage replies, follow-ups, conversations, and appointment scheduling—all connected to your original goal.</p></article>\n</div><div class=\"flow\" aria-label=\"Workflow overview\"><span>Ask</span><span>Research</span><span>Organize</span><span>Activate</span><span>Follow up</span><span>Book</span><span>Track</span></div></div></section>\n<section class=\"section-alt\" id=\"who\"><div class=\"wrap feature\"><div class=\"feature-copy\"><div class=\"eyebrow\">Built around your goals</div><h2>For businesses. For nonprofits. For people who need to get things done.</h2><p>Whether you're growing a service business, building relationships for a nonprofit, or researching potential partners, the process starts with your objective—not a complicated dashboard.</p><p>AutoMake AI handles the connected steps and gives you a clear view of what's happening. You're always in control of which contacts you activate.</p><a class=\"btn secondary\" href=\"#demo\">See it in action</a></div><div class=\"feature-list\"><div><b>Research & contacts</b> — Find organizations and relevant people.</div><div><b>Outreach workflows</b> — Select recipients and authorize personalized email.</div><div><b>Conversations & follow-ups</b> — Keep interested contacts moving forward.</div><div><b>Appointments & tracking</b> — See progress from first contact to booking.</div><div><b>Connected tools</b> — Work with available email, calendar, document, and CRM integrations.</div></div></div></section>\n<section id=\"demo\"><div class=\"wrap\"><div class=\"cta\"><div class=\"eyebrow\">Let's make your next move easier</div><h2>See what AutoMake AI can do for your goals.</h2><p>Tell us who you're trying to reach and what you'd like to accomplish. We'll show you how AutoMake AI can bring your research and outreach into one practical workflow.</p><div class=\"hero-actions\"><a class=\"btn\" href=\"mailto:info@automake.live?subject=AutoMake%20AI%20Demo%20Request&body=Hi%20AutoMake%20AI%2C%0A%0AI%27d%20like%20to%20book%20a%20demo.%20My%20goal%20is%3A%20\">Request a Demo</a><a class=\"btn secondary\" href=\"/login\">Already a Customer? Log In</a></div><p style=\"margin:18px 0 0\">Or email us directly: <a style=\"color:var(--green-light);font-weight:700;overflow-wrap:anywhere\" href=\"mailto:info@automake.live\">info@automake.live</a></p></div></div></section></main>\n<footer class=\"footer\"><div class=\"wrap footrow\"><span>© 2026 AutoMake AI · Ask. Automate. Execute.</span><a href=\"mailto:info@automake.live\">info@automake.live</a></div></footer></body></html>"
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
import src.email_workflows  # noqa: F401
import src.campaign_reporting  # noqa: F401
import src.progressive_campaign  # noqa: F401
import src.owned_research  # noqa: F401
import omniscope_integration  # noqa: F401

rag_research.init_rag_tables()

from owner_test_cleanup import run_startup_cleanup
run_startup_cleanup()

from configured_campaign import start_configured_campaign
start_configured_campaign()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
