"""Safe, plain-text outreach copy for opt-in reviewed campaigns.

This module only renders drafts. Sending, verification and scheduling belong to
existing authorization-protected workflow handlers.
"""
import re

STRATEGIES = ("curiosity", "professional", "direct", "custom")
SUBJECT = "a thought about {company_name}"


def clean_field(value, fallback, limit=100):
    value = re.sub(r"[\r\n\t]+", " ", str(value or "")).strip()
    value = re.sub(r"\s+", " ", value)
    return value[:limit] or fallback


def render_sequence(company_name, first_name, sender_first_name="Matthew", industry="HVAC"):
    """Three editable default drafts, not authorization to send."""
    company = clean_field(company_name, "your company")
    first = clean_field(first_name, "there")
    sender = clean_field(sender_first_name, "Matthew")
    field = clean_field(industry, "service")
    subject = SUBJECT.format(company_name=company)
    emails = [
        {
            "day": 1,
            "subject": subject,
            "body": (
                f"Hey {first},\n\n"
                "Quick question — have you found a reliable way to follow up with "
                "every estimate request without adding more work for your team?\n\n"
                "Curious how you guys handle that.\n\n"
                f"{sender}"
            ),
        },
        {
            "day": 4,
            "subject": "Re: " + subject,
            "body": (
                f"Hey {first},\n\nFollowing up on my question.\n\n"
                f"I've been working on a way for local {field} companies to "
                "handle lead follow-ups automatically, without adding staff or "
                "chasing customers manually.\n\n"
                "Would it be worth sending you a quick example?\n\n"
                f"{sender}"
            ),
        },
        {
            "day": 9,
            "subject": "Re: " + subject,
            "body": (
                f"Hey {first},\n\nLast note from me.\n\n"
                f"I don't know if improving lead follow-up is a priority for "
                f"{company} right now, but I figured it was worth reaching out.\n\n"
                "Would you prefer I send over a quick example, or leave it here?\n\n"
                f"{sender}"
            ),
        },
    ]
    return {
        "strategy": "curiosity",
        "status": "draft_only",
        "emails": emails,
        "follow_up_day_offsets": [0, 3, 8],
        "requires_send_authorization": True,
        "attachment": None,
        "note": "These are preview drafts; activation remains disabled until safe sending integration is completed.",
    }
