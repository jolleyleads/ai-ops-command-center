"""One-shot production Gmail reconciliation worker.

Safety contract:
- reads ONLY gmail_send commands already in uncertain state
- calls the existing deterministic Gmail reconciliation implementation
- records provider proof/audit through reconcile_gmail_command
- NEVER sends or retries email
- exits after processing the current uncertain set
"""
import json

# Import the production application/module graph so models, DB config and Gmail
# reconciliation use exactly the same code and environment as the web service.
import commercial_app  # noqa: F401
import outreach_automation as oa
from app import app
from gmail_reconciliation import reconcile_gmail_command


def main():
    with app.app_context():
        commands = (
            oa.ExternalSideEffectCommand.query
            .filter_by(kind="gmail_send", status="uncertain")
            .order_by(oa.ExternalSideEffectCommand.id.asc())
            .all()
        )
        print(json.dumps({"event":"gmail_reconcile_once_start","uncertain_count":len(commands)}), flush=True)
        results=[]
        for cmd in commands:
            # Re-read immediately before mutation so stale selection cannot broaden scope.
            current=oa.db.session.get(oa.ExternalSideEffectCommand, cmd.id)
            if current is None or current.kind!="gmail_send" or current.status!="uncertain":
                results.append({"command_id":cmd.id,"outcome":"skipped_state_changed"})
                continue
            result=reconcile_gmail_command(current)
            # Deliberately log only command identity/state/proof outcome, not message body.
            results.append({
                "command_id":current.id,
                "lead_id":current.lead_id,
                "ok":result.get("ok") is True,
                "outcome":result.get("outcome") or result.get("status"),
                "command_status":result.get("command_status") or result.get("status"),
                "proof_source":(result.get("proof") or {}).get("source"),
                "provider_message_id":(result.get("proof") or {}).get("message_id"),
            })
        print(json.dumps({"event":"gmail_reconcile_once_complete","results":results}, default=str), flush=True)


if __name__ == "__main__":
    main()
