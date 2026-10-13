"""Existing Render cron entrypoint. Never log credentials or customer message bodies."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app
from outreach_scheduler import run_scheduled_outreach_cycle

if __name__ == '__main__':
    with app.app_context():
        result = run_scheduled_outreach_cycle()
        # Summarize rather than print nested Gmail/provider responses.
        print(json.dumps({'ok': result.get('ok'),
                          'duplicate_cycle_suppressed': result.get('duplicate_cycle_suppressed', False),
                          'sections': list(result)}))
        sys.exit(0 if result.get('ok') else 1)
