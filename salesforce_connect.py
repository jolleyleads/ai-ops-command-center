"""Optional Salesforce customer OAuth and read-only contact import preview.

Requires SALESFORCE_CLIENT_ID, SALESFORCE_CLIENT_SECRET and
SALESFORCE_TOKEN_ENCRYPTION_KEY (Fernet key) on the server.
No outbound email is triggered by this integration.
"""
import os
import secrets
import time
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet
from flask import jsonify, redirect, request, session
from app import app, db
from workspace_security import current_workspace

class SalesforceConnection(db.Model):
    __tablename__ = "salesforce_connection"
    workspace_id = db.Column(db.String(96), primary_key=True)
    instance_url = db.Column(db.String(255), nullable=False)
    refresh_token = db.Column(db.LargeBinary, nullable=False)
    updated_at = db.Column(db.Float, default=time.time)

with app.app_context():
    db.create_all()

def _settings():
    values = [os.getenv(k, "") for k in ("SALESFORCE_CLIENT_ID", "SALESFORCE_CLIENT_SECRET", "SALESFORCE_TOKEN_ENCRYPTION_KEY")]
    if not all(values):
        raise ValueError("Salesforce integration is not configured")
    return values[0], values[1], Fernet(values[2].encode())

def _redirect_uri():
    return os.getenv("SALESFORCE_REDIRECT_URI", "https://automakeai.live/integrations/salesforce/callback")

@app.get("/integrations/salesforce/connect")
def salesforce_connect():
    workspace = current_workspace()
    if not workspace:
        return jsonify(error="Sign in first"), 401
    try:
        client_id, _, _ = _settings()
    except ValueError as exc:
        return jsonify(error=str(exc)), 503
    state = secrets.token_urlsafe(32)
    session["salesforce_oauth"] = {"state": state, "workspace": workspace, "issued": time.time()}
    return redirect("https://login.salesforce.com/services/oauth2/authorize?" + urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": _redirect_uri(),
        "scope": "api refresh_token", "state": state,
    }))

@app.get("/integrations/salesforce/callback")
def salesforce_callback():
    pending = session.pop("salesforce_oauth", None)
    if not pending or time.time() - pending.get("issued", 0) > 600 or not secrets.compare_digest(
        str(pending.get("state", "")), request.args.get("state", "")
    ) or pending.get("workspace") != current_workspace():
        return jsonify(error="Invalid or expired Salesforce authorization"), 400
    if request.args.get("error") or not request.args.get("code"):
        return jsonify(error="Salesforce authorization was declined"), 400
    try:
        client_id, secret, cipher = _settings()
        response = requests.post("https://login.salesforce.com/services/oauth2/token", data={
            "grant_type": "authorization_code", "code": request.args["code"],
            "client_id": client_id, "client_secret": secret, "redirect_uri": _redirect_uri(),
        }, timeout=15)
        response.raise_for_status()
        data = response.json()
        instance = data["instance_url"]
        if not instance.startswith("https://") or not instance.endswith((".salesforce.com", ".force.com", ".salesforce.mil")):
            raise ValueError("Unexpected Salesforce instance URL")
        token = data["refresh_token"]
        db.session.merge(SalesforceConnection(workspace_id=pending["workspace"], instance_url=instance,
                                              refresh_token=cipher.encrypt(token.encode()), updated_at=time.time()))
        db.session.commit()
    except (requests.RequestException, KeyError, ValueError) as exc:
        db.session.rollback()
        return jsonify(error="Salesforce connection failed", detail=str(exc)[:120]), 502
    return redirect("/chat-operator?integration=salesforce", 303)

def _access_token(connection):
    client_id, secret, cipher = _settings()
    response = requests.post("https://login.salesforce.com/services/oauth2/token", data={
        "grant_type": "refresh_token", "client_id": client_id, "client_secret": secret,
        "refresh_token": cipher.decrypt(connection.refresh_token).decode(),
    }, timeout=15)
    response.raise_for_status()
    return response.json()["access_token"]

@app.get("/integrations/salesforce/contacts")
def salesforce_contacts():
    workspace = current_workspace()
    if not workspace:
        return jsonify(error="Sign in first"), 401
    connection = db.session.get(SalesforceConnection, workspace)
    if not connection:
        return jsonify(error="Connect Salesforce first"), 409
    try:
        token = _access_token(connection)
        response = requests.get(connection.instance_url + "/services/data/v60.0/query", params={
            "q": "SELECT Id, FirstName, LastName, Email, Account.Name FROM Contact ORDER BY LastModifiedDate DESC LIMIT 100"
        }, headers={"Authorization": "Bearer " + token}, timeout=20)
        response.raise_for_status()
        return jsonify(contacts=response.json().get("records", []), source="salesforce", sent=0)
    except (requests.RequestException, KeyError, ValueError):
        return jsonify(error="Salesforce contact sync failed"), 502
