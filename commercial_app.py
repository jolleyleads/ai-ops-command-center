from app import app
import brave_app  # noqa: F401
import search_overrides  # noqa: F401
import contractor_intent  # noqa: F401
import places_diagnostic  # noqa: F401
import permit_leads  # noqa: F401
import local_jobs  # noqa: F401
import smart_search  # noqa: F401
import outreach_automation  # noqa: F401
import smart_search_outreach_hook  # noqa: F401

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
