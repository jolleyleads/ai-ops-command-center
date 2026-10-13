"""Additive durable queue for unfinished discovery. External sends retain their gates."""
import json
import uuid
from datetime import datetime, timedelta
from flask import jsonify
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from app import app, db
from src.provider_recovery import recovery_policy


class LeadRecovery(db.Model):
    __tablename__ = 'lead_recovery'
    lead_id = db.Column(db.Integer, primary_key=True)
    payload_json = db.Column(db.Text, nullable=False)
    state = db.Column(db.String(30), nullable=False, default='retry_wait', index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    next_check_at = db.Column(db.DateTime, index=True)
    lease_token = db.Column(db.String(64), default='')
    lease_until = db.Column(db.DateTime)
    reason_json = db.Column(db.Text, default='[]')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


with app.app_context():
    db.create_all()


def schedule_recovery(lead, result, reasons):
    row = db.session.get(LeadRecovery, lead.id)
    if row and row.state == 'running':
        return row  # The current lease owner alone may finish this attempt.
    if row is None:
        row = LeadRecovery(lead_id=lead.id, payload_json=json.dumps(result))
        db.session.add(row)
    policy = recovery_policy(reasons, row.attempts or 0)
    row.payload_json = json.dumps(result)
    row.state = policy['state']
    row.reason_json = json.dumps(policy['reason_codes'])
    row.next_check_at = datetime.fromisoformat(policy['next_check_at']).replace(tzinfo=None) if policy['next_check_at'] else None
    row.updated_at = datetime.utcnow()
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()  # Another discovery worker already registered this lead.
    return row


def process_recoverable_leads(limit=3):
    import outreach_automation as oa
    import v1_orchestration as v1
    now = datetime.utcnow()
    # A killed contact research attempt is read-only and can be claimed again.
    candidates = LeadRecovery.query.filter(
        or_(LeadRecovery.next_check_at <= now,
            (LeadRecovery.state == 'running') & (LeadRecovery.lease_until < now)),
        LeadRecovery.state.in_(['retry_wait', 'quota_wait', 'configuration_required', 'running'])
    ).order_by(LeadRecovery.next_check_at).limit(max(1, min(limit, 10))).all()
    processed = []
    for candidate in candidates:
        lead_id = candidate.lead_id
        token = uuid.uuid4().hex
        claimed = LeadRecovery.query.filter_by(lead_id=lead_id).filter(
            or_(LeadRecovery.lease_until.is_(None), LeadRecovery.lease_until < now)
        ).update({'state': 'running', 'lease_token': token, 'lease_until': now + timedelta(minutes=10)}, synchronize_session=False)
        db.session.commit()
        if not claimed:
            continue
        row = db.session.get(LeadRecovery, lead_id)
        db.session.refresh(row)
        lead = db.session.get(oa.OutreachLead, lead_id)
        state, reasons = 'review_required', ['LEAD_NOT_RECOVERABLE']
        next_check = None
        try:
            # Never refresh recipients/evidence after any send or booking attempt.
            if lead and lead.status in {'needs_evidence', 'qualified', 'drafted'} and not lead.gmail_message_id and not oa.OutreachSendAttempt.query.filter_by(lead_id=lead_id).first() and not oa.OutreachBookingAttempt.query.filter_by(lead_id=lead_id).first():
                result = json.loads(row.payload_json)
                def lease_valid():
                    return bool(LeadRecovery.query.filter_by(lead_id=lead_id,lease_token=token,state='running').filter(LeadRecovery.lease_until>datetime.utcnow()).count())
                outcome = v1.resume_discovery_lead(lead, result, lease_valid)
                reasons = outcome.get('reason_codes') or []
                if outcome.get('ok'):
                    state = 'completed'
                else:
                    policy = recovery_policy(reasons, row.attempts + 1)
                    state = policy['state']
                    next_check = datetime.fromisoformat(policy['next_check_at']).replace(tzinfo=None) if policy['next_check_at'] else None
        except Exception as exc:
            db.session.rollback()
            reasons = ['RECOVERY_' + type(exc).__name__.upper()]
            policy = recovery_policy(reasons, row.attempts + 1)
            state = policy['state']
            next_check = datetime.fromisoformat(policy['next_check_at']).replace(tzinfo=None) if policy['next_check_at'] else None
        # Fencing: an expired worker cannot write over the newer queue owner.
        finished = LeadRecovery.query.filter_by(lead_id=lead_id, lease_token=token, state='running').update(
            {'state': state, 'reason_json': json.dumps(reasons), 'attempts': LeadRecovery.attempts + 1,
             'next_check_at': next_check, 'lease_until': None, 'updated_at': datetime.utcnow()}, synchronize_session=False)
        if finished and lead:
            oa._audit_actor(lead_id, 'lead_recovery', {}, {'state': state, 'reason_codes': reasons}, 'scheduler')
        db.session.commit()
        processed.append({'lead_id': lead_id, 'state': state, 'reason_codes': reasons})
    return {'ok': True, 'processed': processed}


def recovery_snapshot():
    rows = LeadRecovery.query.filter(LeadRecovery.state != 'completed').order_by(LeadRecovery.updated_at).limit(100).all()
    return [{'lead_id': r.lead_id, 'state': r.state, 'attempts': r.attempts,
             'reason_codes': json.loads(r.reason_json),
             'next_check_at': r.next_check_at.isoformat() if r.next_check_at else None} for r in rows]


@app.route('/api/operator/lead-recovery')
def operator_lead_recovery():
    import outreach_automation as oa
    if not (oa._operator_authorized() or oa._operator_session_authorized()):
        return jsonify({'ok': False, 'error': 'operator authentication required'}), 401
    response = jsonify({'ok': True, 'leads': recovery_snapshot()})
    response.headers['Cache-Control'] = 'no-store'
    return response
