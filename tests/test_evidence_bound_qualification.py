import json
from datetime import datetime
import pytest
import outreach_automation as oa
import smart_search


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("OPERATOR_CONTROL_TOKEN","operator-test-token")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEY_VERSION","v1")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEYS","v1=qualification-signing-secret")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEY_VERSION","v1")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEYS","v1=qualification-signing-secret")
    with oa.app.app_context():
        oa.db.session.remove();oa.db.drop_all();oa.db.create_all()
        yield
        oa.db.session.remove();oa.db.drop_all()


def make_lead():
    evidence=[{"url":"https://example.com/contact","email":"owner@example.com","title":"Example Electric contact","text":"Example Electric owner contact","observed_at":datetime.utcnow().isoformat()}]
    row=oa.OutreachLead(company="Example Electric",contact_email="owner@example.com",location="Portsmouth, VA",source_url="https://example.com",evidence_json=json.dumps(evidence),status="needs_evidence")
    oa.db.session.add(row);oa.db.session.commit();return row


def test_caller_verification_and_context_cannot_create_trust(env):
    row=make_lead()
    # Poison request data is ignored; server persisted evidence controls the result.
    receipt=oa._store_qualification(row,{"verification_ok":True,"validated":{"company_name":"Attacker Co","email":"attacker@evil.test","email_source_url":"https://evil.test"},"qualification_context":{"excluded":False},"evidence":[{"url":"https://evil.test","email":"attacker@evil.test"}]})
    assert receipt["ok"] is True
    assert receipt["company_name"]=="Example Electric"
    assert receipt["validated_input"]["email"]=="owner@example.com"
    assert "evil.test" not in json.dumps(receipt)


def test_signed_receipt_is_accepted_while_evidence_is_unchanged(env):
    row=make_lead();receipt=oa._store_qualification(row,{})
    gate=oa._qualification_gate(row)
    assert receipt["server_signature"]
    assert len(receipt["evidence_digest"])==64
    assert gate["ok"] is True


def test_tampered_receipt_fails_closed(env):
    row=make_lead();oa._store_qualification(row,{})
    dbrow=oa.OutreachQualificationReceipt.query.filter_by(lead_id=row.id).one()
    receipt=json.loads(dbrow.receipt_json);receipt["qualified"]=False
    dbrow.receipt_json=json.dumps(receipt);oa.db.session.commit()
    gate=oa._qualification_gate(row)
    assert gate["ok"] is False
    assert "QUALIFICATION_SIGNATURE_INVALID" in gate["reason_codes"]


def test_changed_lead_identity_invalidates_existing_receipt(env):
    row=make_lead();oa._store_qualification(row,{})
    row.contact_email="other@example.com";oa.db.session.commit()
    gate=oa._qualification_gate(row)
    assert gate["ok"] is False
    assert "QUALIFICATION_EVIDENCE_CHANGED" in gate["reason_codes"]


def test_changed_evidence_invalidates_existing_receipt(env):
    row=make_lead();oa._store_qualification(row,{})
    row.evidence_json=json.dumps([{"url":"https://example.com/other","email":"owner@example.com","text":"changed"}]);oa.db.session.commit()
    gate=oa._qualification_gate(row)
    assert gate["ok"] is False
    assert "QUALIFICATION_EVIDENCE_CHANGED" in gate["reason_codes"]


def test_missing_signing_key_fails_closed(env,monkeypatch):
    row=make_lead();monkeypatch.delenv("QUALIFICATION_SIGNING_KEYS",raising=False)
    receipt=oa._store_qualification(row,{})
    assert receipt["ok"] is False
    assert "QUALIFICATION_SIGNING_KEY_MISSING" in receipt["reason_codes"]
    assert oa._qualification_gate(row)["ok"] is False


def test_forged_unsigned_database_receipt_cannot_authorize_send(env):
    row=make_lead()
    fake={"ok":True,"qualified":True,"status":"Qualified","reason_codes":[]}
    oa.db.session.add(oa.OutreachQualificationReceipt(lead_id=row.id,status="Qualified",qualified=True,ok=True,receipt_json=json.dumps(fake)));oa.db.session.commit()
    gate=oa._qualification_gate(row)
    assert gate["ok"] is False
    assert "QUALIFICATION_SIGNATURE_INVALID" in gate["reason_codes"]


def test_rotation_signs_new_receipts_with_active_version_and_keeps_old_valid(env,monkeypatch):
    old=make_lead();old_receipt=oa._store_qualification(old,{})
    assert old_receipt["key_version"]=="v1"
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEY_VERSION","v2")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEYS","v1=qualification-signing-secret,v2=rotated-qualification-secret")
    assert oa._qualification_gate(old)["ok"] is True
    new=make_lead();new.contact_email="new@example.com"
    new.evidence_json=json.dumps([{"url":"https://example.com/contact2","email":"new@example.com","title":"Example Electric contact","text":"Example Electric owner contact","observed_at":datetime.utcnow().isoformat()}])
    oa.db.session.commit()
    new_receipt=oa._store_qualification(new,{})
    assert new_receipt["key_version"]=="v2"
    assert oa._qualification_gate(new)["ok"] is True


def test_retiring_old_key_invalidates_only_old_version(env,monkeypatch):
    old=make_lead();oa._store_qualification(old,{})
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEY_VERSION","v2")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEYS","v2=rotated-qualification-secret")
    gate=oa._qualification_gate(old)
    assert gate["ok"] is False
    assert "QUALIFICATION_SIGNATURE_INVALID" in gate["reason_codes"]


def test_operator_secret_cannot_forge_qualification_signature(env,monkeypatch):
    row=make_lead();receipt=oa._store_qualification(row,{})
    unsigned={k:v for k,v in receipt.items() if k!="server_signature"}
    forged=__import__("hmac").new(b"operator-test-token",oa._canonical_json(unsigned).encode(),__import__("hashlib").sha256).hexdigest()
    assert forged != receipt["server_signature"]
