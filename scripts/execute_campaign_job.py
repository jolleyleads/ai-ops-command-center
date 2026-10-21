"""Bounded child-process entrypoint; never runs commercial startup campaigns."""
import sys
import os
os.environ["AUTOMAKE_ISOLATED_EXECUTION"]="1"
from app import app, db
import gmail_connect
import customer_demo
from campaign_jobs import execute_claimed_job

if __name__ == "__main__":
    with app.app_context():
        try:
            execute_claimed_job(sys.argv[1])
        finally:
            db.session.remove()
