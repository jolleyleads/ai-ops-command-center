"""Bounded child-process entrypoint; never runs commercial startup campaigns."""
import sys
from app import app, db
import customer_demo
from campaign_jobs import execute_claimed_job

if __name__ == "__main__":
    with app.app_context():
        try:
            execute_claimed_job(sys.argv[1])
        finally:
            db.session.remove()
